"""
Unit tests for which entry ``ytsearch()`` is willing to return.

yt-dlp's ``matchtitle`` cannot be trusted as the only filter. Two of its
behaviours put non-matching entries into ``result['entries']`` looking exactly
like a match:

1. ``YoutubeDL._match_entry`` skips the title check for any entry it can't
   confirm is a single video, which includes every playlist that turns up in a
   channel-search result. A ``@CHANNEL/search?query=...`` url returns those
   interleaved with the videos, and one of them sat at index 0.
2. When an entry *does* fail matchtitle in ``process_video_result``, yt-dlp
   returns the info dict anyway — it just declines to download it.

Handing either to ``download()`` is worse than finding nothing: the outtmpl is
fixed per episode and ``nooverwrites`` is set, so yt-dlp writes the
collection's first item into the episode's filename and every episode in the
series ends up as the same wrong video.

Fixtures use real titles and ids from the VICE channel search that surfaced
this, so the shapes are the ones yt-dlp actually produces.
"""
import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402
from utils import upperescape  # noqa: E402

SEARCH_URL = "https://www.youtube.com/@VICE/search?query=epicly laterd"

# Index 0 of the real search result: a playlist, never filtered by matchtitle.
PLAYLIST_ENTRY = {
    '_type': 'url',
    'ie_key': 'YoutubeTab',
    'id': 'PLDbSvEZka6GGm9cigiCJImOCKj6XZ9-gY',
    'title': "Epicly Later'd",
    'url': 'https://www.youtube.com/playlist?list=PLDbSvEZka6GGm9cigiCJImOCKj6XZ9-gY',
}
# The same playlist after yt-dlp resolved it, which is what actually lands in
# entries once the reference is processed.
RESOLVED_PLAYLIST_ENTRY = {
    '_type': 'playlist',
    'id': 'PLDbSvEZka6GGm9cigiCJImOCKj6XZ9-gY',
    'title': "Epicly Later'd",
    'entries': [],
    'webpage_url': 'https://www.youtube.com/playlist?list=PLDbSvEZka6GGm9cigiCJImOCKj6XZ9-gY',
}
BEN_KADOW = {
    'id': 'YrmakZiZTOE',
    'title': 'Ben Kadow: An American Original | Epicly Later’d',
    'webpage_url': 'https://www.youtube.com/watch?v=YrmakZiZTOE',
}
JAMIE_FOY = {
    'id': 'bB5U9T9KZC8',
    'title': "Jamie Foy: Two-Time Skater Of The Year And Fisherman | Epicly Later'd",
    'webpage_url': 'https://www.youtube.com/watch?v=bB5U9T9KZC8',
}


class FakeYoutubeDL(object):
    """Minimal yt_dlp.YoutubeDL stand-in usable as a context manager."""

    def __init__(self, result=None):
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        return self.result


class YtsearchTestCase(unittest.TestCase):

    def setUp(self):
        self._real_ydl = stream_harvestarr.yt_dlp.YoutubeDL

    def tearDown(self):
        stream_harvestarr.yt_dlp.YoutubeDL = self._real_ydl

    def ytsearch(self, result, episode_title=None):
        stream_harvestarr.yt_dlp.YoutubeDL = lambda opts: FakeYoutubeDL(result)
        opts = {'matchtitle': upperescape(episode_title)} if episode_title else {}
        return stream_harvestarr.StreamHarvester.ytsearch(None, opts, SEARCH_URL)


class TestCollectionEntriesRejected(YtsearchTestCase):
    """A playlist or channel is never an episode."""

    def test_unresolved_playlist_reference_is_skipped(self):
        result = {'entries': [PLAYLIST_ENTRY, BEN_KADOW]}
        self.assertEqual(
            self.ytsearch(result, 'Ben Kadow'),
            (True, 'https://www.youtube.com/watch?v=YrmakZiZTOE'),
        )

    def test_resolved_playlist_is_skipped(self):
        result = {'entries': [RESOLVED_PLAYLIST_ENTRY, BEN_KADOW]}
        self.assertEqual(
            self.ytsearch(result, 'Ben Kadow'),
            (True, 'https://www.youtube.com/watch?v=YrmakZiZTOE'),
        )

    def test_playlist_alone_is_not_found(self):
        """The bug: nothing matched, so only the playlist was left."""
        result = {'entries': [PLAYLIST_ENTRY]}
        self.assertEqual(self.ytsearch(result, 'Lizard King'), (False, ''))

    def test_search_page_result_is_not_found(self):
        """The configured url resolving to itself is not an episode."""
        result = {
            '_type': 'playlist',
            'title': 'VICE - Search',
            'webpage_url': 'https://www.youtube.com/@VICE/search?query=epicly+laterd',
        }
        self.assertEqual(self.ytsearch(result, 'Lizard King'), (False, ''))

    def test_channel_videos_tab_is_not_found(self):
        result = {'entries': [{
            '_type': 'url',
            'ie_key': 'YoutubeTab',
            'title': 'MILKY☆SUBWAY - Videos',
            'url': 'https://www.youtube.com/@milkygalacticuniverse/videos',
        }]}
        self.assertEqual(self.ytsearch(result, 'MILKY☆SUBWAY'), (False, ''))

    def test_watch_url_carrying_a_list_param_is_kept(self):
        """A video inside a playlist is still a video."""
        result = {'entries': [{
            'title': 'Ben Kadow: An American Original | Epicly Later’d',
            'webpage_url': 'https://www.youtube.com/watch?v=YrmakZiZTOE&list=PLDbSvEZka6GG',
        }]}
        found, url = self.ytsearch(result, 'Ben Kadow')
        self.assertTrue(found)
        self.assertIn('watch?v=YrmakZiZTOE', url)


class TestTitleReverified(YtsearchTestCase):
    """yt-dlp returns entries it rejected, so re-check the pattern."""

    def test_entry_failing_matchtitle_is_skipped(self):
        """process_video_result returns rejected entries rather than None."""
        result = {'entries': [JAMIE_FOY, BEN_KADOW]}
        self.assertEqual(
            self.ytsearch(result, 'Ben Kadow'),
            (True, 'https://www.youtube.com/watch?v=YrmakZiZTOE'),
        )

    def test_no_entry_matches_is_not_found(self):
        result = {'entries': [JAMIE_FOY]}
        self.assertEqual(self.ytsearch(result, 'Ben Kadow'), (False, ''))

    def test_untitled_entry_is_rejected(self):
        """Unverifiable is treated as not a match: missing beats wrong."""
        result = {'entries': [{'webpage_url': 'https://youtu.be/mystery'}]}
        self.assertEqual(self.ytsearch(result, 'Ben Kadow'), (False, ''))

    def test_no_matchtitle_keeps_first_video(self):
        """Without a pattern there is nothing to verify against."""
        result = {'entries': [BEN_KADOW]}
        self.assertEqual(
            self.ytsearch(result),
            (True, 'https://www.youtube.com/watch?v=YrmakZiZTOE'),
        )


class TestIsSingleVideo(unittest.TestCase):
    """The url classifier, exercised directly on real url shapes."""

    def test_video_urls(self):
        for url in (
            'https://www.youtube.com/watch?v=YrmakZiZTOE',
            'https://youtu.be/YrmakZiZTOE',
            'https://www.youtube.com/shorts/abc123',
            'https://www.youtube.com/embed/abc123',
        ):
            self.assertTrue(
                stream_harvestarr.is_single_video({'webpage_url': url}), url)

    def test_collection_urls(self):
        for url in (
            'https://www.youtube.com/playlist?list=PLDbSvEZka6GG',
            'https://www.youtube.com/@VICE/search?query=epicly+laterd',
            'https://www.youtube.com/@milkygalacticuniverse/videos',
            'https://www.youtube.com/channel/UCzn/videos',
            'https://www.youtube.com/results?search_query=skate',
        ):
            self.assertFalse(
                stream_harvestarr.is_single_video({'webpage_url': url}), url)

    def test_unknown_extractor_url_is_allowed(self):
        """Non-YouTube sites keep the pre-existing permissive behaviour."""
        self.assertTrue(stream_harvestarr.is_single_video(
            {'url': 'https://example.com/media/12345.mp4'}))


if __name__ == '__main__':
    unittest.main()
