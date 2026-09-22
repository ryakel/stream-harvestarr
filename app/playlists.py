"""Flat source extraction, channel URLs, and scan-scoped playlist caching."""

import logging
import re
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import islice

import yt_dlp
from playlist_snapshot import PlaylistSnapshot
from utils import is_rate_limit_error, redact_sensitive

logger = logging.getLogger('stream_harvestarr')

# yt-dlp results that are a *collection* rather than one video. Three shapes
# reach ytsearch(): a resolved playlist ('playlist' / 'multi_video'), an
# unresolved reference to one (_type 'url' whose url is a playlist or channel
# page), and the top-level result for the configured url when nothing in it
# matched. None of them may be handed to download(): with a fixed outtmpl and
# nooverwrites, yt-dlp writes the collection's *first* item into the episode's
# filename, so every episode gets the same wrong video.
#
# This is not theoretical. A channel-search url
# (https://www.youtube.com/@CHANNEL/search?query=...) returns playlist entries
# interleaved with videos, and YoutubeDL._match_entry deliberately skips
# matchtitle for entries it can't confirm are a single video — so the playlist
# sitting at index 0 was never filtered and won every episode.
COLLECTION_TYPES = ('playlist', 'multi_video')
# Markers that positively identify one video. Checked first so a legitimate
# watch?v=ID&list=ID url isn't discarded along with the collections.
VIDEO_URL_RE = re.compile(r'(?:/watch\b|[?&]v=|/shorts/|youtu\.be/|/embed/)', re.IGNORECASE)
COLLECTION_URL_RE = re.compile(
    r'(?:/playlist\b|[?&]list=|/@[^/]+/|/channel/|/user/|/c/|/results\b|/search\b)', re.IGNORECASE
)
YOUTUBE_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com'}


class PlaylistRateLimitError(RuntimeError):
    """A playlist refresh was rejected by the source's rate limiter."""


def is_single_video(entry):
    """True when a yt-dlp result entry is one downloadable video."""
    if entry.get('_type') in COLLECTION_TYPES:
        return False
    if entry.get('entries') is not None:
        return False
    url = entry.get('webpage_url') or entry.get('url') or ''
    if VIDEO_URL_RE.search(url):
        return True
    return not COLLECTION_URL_RE.search(url)


def video_playlist_url(playlist):
    """Resolve a bare YouTube channel URL to its videos tab."""
    try:
        parsed = urllib.parse.urlsplit(playlist)
    except ValueError:
        return playlist

    if parsed.scheme not in ('http', 'https'):
        return playlist
    if parsed.hostname not in YOUTUBE_HOSTS:
        return playlist
    if parsed.query or parsed.fragment:
        return playlist

    path = parsed.path.rstrip('/')
    if re.fullmatch(r'/(?:@[^/]+|channel/[^/]+|user/[^/]+|c/[^/]+)', path):
        return parsed._replace(path=path + '/videos').geturl()
    return playlist


def video_search_url(playlist, query):
    """Resolve a YouTube channel URL to its bounded search tab."""
    try:
        parsed = urllib.parse.urlsplit(playlist)
    except ValueError:
        return None

    if parsed.scheme not in ('http', 'https'):
        return None
    if parsed.hostname not in YOUTUBE_HOSTS:
        return None

    path = parsed.path.rstrip('/')
    if path.endswith('/videos'):
        path = path[: -len('/videos')].rstrip('/')
    if not re.fullmatch(r'/(?:@[^/]+|channel/[^/]+|user/[^/]+|c/[^/]+)', path):
        return None

    return parsed._replace(
        path=path + '/search',
        query=urllib.parse.urlencode({'query': query}),
        fragment='',
    ).geturl()


def entry_url(entry):
    """Return the preferred page URL for an extracted entry."""
    return entry.get('webpage_url') or entry.get('url')


def is_youtube_url(url):
    """Return whether a source URL belongs to a supported YouTube host."""
    try:
        return urllib.parse.urlsplit(url).hostname in YOUTUBE_HOSTS
    except ValueError:
        return False


CacheKey = tuple[str, str | None, str | None, str | None, int | None]


@dataclass(repr=False)
class PlaylistCache:
    """Cache flat playlist entries and refresh each source once per scan."""

    entries: dict[CacheKey, PlaylistSnapshot] = field(default_factory=dict)
    refreshed: set[CacheKey] = field(default_factory=set)

    def begin_scan(self, playlists=None):
        """Reset refresh tracking and remove sources no longer in the scan."""
        self.refreshed.clear()
        if playlists is not None:
            for key in list(self.entries):
                if key[0] not in playlists:
                    self._discard(key)

    def end_scan(self):
        """Release unused credential variants and sources with no wanted episodes."""
        for key in self.entries.keys() - self.refreshed:
            self._discard(key)

    def close(self):
        for key in list(self.entries):
            self._discard(key)

    def get(self, ydl_opts, playlist):
        """Return cached candidates, refreshing the source once when needed."""
        key = self._key(ydl_opts, playlist)
        if key not in self.refreshed:
            self.refreshed.add(key)
            try:
                fresh_entries = self._extract(ydl_opts, playlist)
            except PlaylistRateLimitError:
                self.refreshed.discard(key)
                raise
            if fresh_entries is not None:
                previous = self.entries.get(key)
                self.entries[key] = fresh_entries
                if previous is not None and previous is not fresh_entries:
                    previous.close()
            else:
                logger.warning(
                    'Source refresh failed for %s; %s',
                    redact_sensitive(playlist),
                    'using the previous complete snapshot'
                    if key in self.entries
                    else 'no snapshot is available; episode matching is unavailable',
                )

        candidates = self.entries.get(key, [])
        if ydl_opts.get('playlistreverse'):
            return reversed(candidates)
        return candidates

    def discard(self, ydl_opts, playlist):
        """Release an episode-specific search snapshot and its refresh marker."""
        self._discard(self._key(ydl_opts, playlist))

    def _discard(self, key):
        snapshot = self.entries.pop(key, None)
        self.refreshed.discard(key)
        if snapshot is not None:
            snapshot.close()

    @staticmethod
    def _key(ydl_opts, playlist) -> CacheKey:
        """Build the cache key for a source and its extraction options."""
        return (
            playlist,
            ydl_opts.get('cookiefile'),
            ydl_opts.get('username'),
            ydl_opts.get('password'),
            ydl_opts.get('playlistend'),
        )

    @staticmethod
    def _extract(ydl_opts, playlist) -> PlaylistSnapshot | None:
        """Extract flat entries into a snapshot, preserving the prior snapshot on failure."""
        options = dict(ydl_opts)
        options.pop('matchtitle', None)
        options.pop('match_filter', None)
        options['extract_flat'] = 'in_playlist'
        url = video_playlist_url(playlist)
        # A lazy YouTube continuation can otherwise swallow a later-page error
        # and publish the prefix as if it were a complete source snapshot.
        if is_youtube_url(url):
            options['ignoreerrors'] = False
        options['lazy_playlist'] = True
        extractor_args = dict(options.get('extractor_args', {}))
        youtube_args = dict(extractor_args.get('youtube', {}))
        youtube_args['raise_incomplete_data'] = ['true']
        extractor_args['youtube'] = youtube_args
        options['extractor_args'] = extractor_args
        options['playlistreverse'] = False
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                entries = PlaylistCache._entries(ydl, url, options.get('playlistend'))
                # Publish only after the entire result has been consumed.
                return PlaylistSnapshot(
                    (entry.get('title'), entry_url(entry))
                    for entry in entries
                    if isinstance(entry, dict) and entry_url(entry) and is_single_video(entry)
                )
        # yt-dlp exposes several extractor-specific failure types. Keep this
        # boundary broad so one failed refresh cannot destroy a good snapshot.
        except Exception as error:  # noqa: BLE001
            if is_rate_limit_error(error):
                raise PlaylistRateLimitError(str(error)) from error
            logger.error(
                'Playlist extraction failed for %s: %s',
                redact_sensitive(playlist),
                redact_sensitive(str(error)),
            )
            return None

    @staticmethod
    def _entries(ydl, url: str, limit: int | None) -> Iterator[dict]:
        """Stream upstream YouTube tabs; preserve normal processing elsewhere."""
        seen = set()
        ie_key = None
        while (url, ie_key) not in seen:
            seen.add((url, ie_key))
            result = ydl.extract_info(url, download=False, process=False, ie_key=ie_key)
            if result is None:
                raise ValueError('No playlist metadata returned')
            if (
                result.get('extractor_key') != 'YoutubeTab'
                or result.get('_type') == 'url_transparent'
            ):
                result = ydl.process_ie_result(result, download=False)
                if result is None:
                    raise ValueError('No playlist metadata returned')
                entries = result.get('entries')
                yield from entries if entries is not None else (result,)
                return
            if result.get('_type') == 'url':
                # Resolve tab redirects without materializing their destination.
                url, ie_key = result['url'], result.get('ie_key')
                continue
            entries = result.get('entries')
            yield from islice(entries if entries is not None else (result,), limit)
            return
        raise ValueError('Playlist redirect loop')
