"""Regression tests for rate limits encountered during discovery."""

import os
import sys
import unittest
from unittest.mock import Mock, patch

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr as app  # noqa: E402
from playlists import PlaylistRateLimitError  # noqa: E402
from playlist_snapshot import PlaylistSnapshot  # noqa: E402


SERIES = {'id': 1, 'title': 'Show', 'path': '/tv/Show', 'monitored': True}
EPISODE = {
    'seriesId': 1,
    'title': 'Episode',
    'seasonNumber': 1,
    'episodeNumber': 1,
    'monitored': True,
    'hasFile': False,
}


class DiscoveryRateLimitTests(unittest.TestCase):
    def test_discovery_rate_limit_enters_download_error_handling(self):
        client = object.__new__(app.StreamHarvester)
        client.find_episode = Mock(side_effect=PlaylistRateLimitError('HTTP Error 429'))
        client.handle_download_error = Mock(return_value=False)
        self.assertFalse(client.download_episode(SERIES, EPISODE, 1))
        client.handle_download_error.assert_called_once()

    def test_playlist_rate_limit_is_preserved_for_the_download_loop(self):
        source = 'https://www.youtube.com/@Show'

        class RateLimitedYoutubeDL:
            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def extract_info(self, *args, **kwargs):
                raise app.yt_dlp.utils.DownloadError('HTTP Error 429: Too Many Requests')

        with patch.object(app.yt_dlp, 'YoutubeDL', return_value=RateLimitedYoutubeDL()):
            with self.assertRaises(PlaylistRateLimitError):
                app.PlaylistCache._extract({}, source)

    def test_rate_limit_retry_preserves_previous_snapshot_until_scan_end(self):
        source = 'https://www.youtube.com/@Show'
        cache = app.PlaylistCache()
        self.addCleanup(cache.close)
        key = cache._key({}, source)
        cache.entries[key] = PlaylistSnapshot(
            [('Episode', 'https://youtu.be/abcdefghijk')]
        )
        cache.begin_scan({source})

        with patch.object(cache, '_extract', side_effect=PlaylistRateLimitError('HTTP Error 429')):
            with self.assertRaises(PlaylistRateLimitError):
                cache.get({}, source)

        self.assertIn(key, cache.entries)
        cache.end_scan()
        self.assertIn(key, cache.entries)
        self.assertEqual(
            list(cache.entries[key]),
            [{'title': 'Episode', 'url': 'https://youtu.be/abcdefghijk'}],
        )

    def test_untitled_entry_is_not_extracted_individually(self):
        source = 'https://www.patreon.com/creator'
        entry = {
            '_type': 'url',
            'url': 'https://www.patreon.com/posts/episode-123',
        }

        class UntitledEntryYoutubeDL:
            calls = []

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def extract_info(self, url, **kwargs):
                self.calls.append(url)
                if url == source:
                    return {'_type': 'playlist', 'entries': [entry]}
                raise AssertionError(f'unexpected per-entry extraction: {url}')

            def process_ie_result(self, result, download=False):
                return result

        with patch.object(app.yt_dlp, 'YoutubeDL', return_value=UntitledEntryYoutubeDL()):
            snapshot = app.PlaylistCache._extract({}, source)
        self.addCleanup(snapshot.close)

        self.assertEqual(UntitledEntryYoutubeDL.calls, [source])
        self.assertEqual(
            list(snapshot),
            [{'title': None, 'url': 'https://www.patreon.com/posts/episode-123'}],
        )

if __name__ == '__main__':
    unittest.main()
