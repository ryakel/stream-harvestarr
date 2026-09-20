"""
Unit tests for running the episode search flat.

The search only ever needs two things from a candidate: a title to match on and
a url to hand to ``download()``. Resolving anything further is wasted, and on a
channel search it is expensive in a way that is easy to miss — the result
carries the channel's *playlists* alongside its videos, and yt-dlp recurses
into every one. On the VICE search that is 13 playlists, the largest 1773
items, walked again for every episode. ``is_single_video()`` refuses to return
a playlist anyway, so resolving them only ever cost requests, and enough of
them to get the session rate-limited by YouTube.

``extract_flat: 'in_playlist'`` resolves the configured url into a list and
stops there. These pin the two properties that makes safe: a flat video entry
still yields the canonical watch url, and a flat playlist entry is still
refused.
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

# Exactly the shapes a flat extraction of that search returns: _type 'url',
# no webpage_url, and a url that is canonical rather than a media stream.
FLAT_VIDEO = {
    '_type': 'url', 'ie_key': 'Youtube', 'id': 'YrmakZiZTOE',
    'title': 'Ben Kadow: An American Original | Epicly Later’d',
    'url': 'https://www.youtube.com/watch?v=YrmakZiZTOE',
}
FLAT_PLAYLIST = {
    '_type': 'url', 'ie_key': 'YoutubeTab',
    'id': 'PLDbSvEZka6GGm9cigiCJImOCKj6XZ9-gY',
    'title': "Epicly Later'd",
    'url': 'https://www.youtube.com/playlist?list=PLDbSvEZka6GGm9cigiCJImOCKj6XZ9-gY',
}


class FakeYoutubeDL(object):
    def process_ie_result(self, result, download=False):
        return result

    def __init__(self, result=None):
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


    def extract_info(self, url, download=False, process=True, ie_key=None):
        """Return the configured fake extraction result."""
        return self.result


class _NoDebug(object):
    debug = False

    def appendcookie(self, opts, cookies=None):
        return opts

    def appendcredentials(self, opts, username=None, password=None):
        return opts


class TestSearchRunsFlat(unittest.TestCase):

    def opts(self):
        return stream_harvestarr.StreamHarvester.ytdl_eps_search_opts(
            _NoDebug(), False)

    def test_extract_flat_is_in_playlist(self):
        """Not True — the configured url itself must still resolve."""
        self.assertEqual(self.opts()['extract_flat'], 'in_playlist')

    def test_episode_filter_is_not_part_of_source_options(self):
        """Episode matching happens against the shared cached candidates."""
        self.assertNotIn('match_filter', self.opts())


class TestFlatEntriesResolve(unittest.TestCase):

    def setUp(self):
        self._real_ydl = stream_harvestarr.yt_dlp.YoutubeDL
        self.client = object.__new__(stream_harvestarr.StreamHarvester)
        self.client.playlist_cache = stream_harvestarr.PlaylistCache()

    def tearDown(self):
        stream_harvestarr.yt_dlp.YoutubeDL = self._real_ydl

    def ytsearch(self, result, episode='Ben Kadow'):
        """Return the configured test search result."""
        stream_harvestarr.yt_dlp.YoutubeDL = lambda opts: FakeYoutubeDL(result)
        pattern = upperescape(episode)
        return self.client.ytsearch({}, SEARCH_URL, pattern)

    def test_flat_video_yields_the_watch_url(self):
        """No webpage_url on a flat entry; the url fallback carries it."""
        self.assertNotIn('webpage_url', FLAT_VIDEO)
        self.assertEqual(
            self.ytsearch({'entries': [FLAT_VIDEO]}),
            'https://www.youtube.com/watch?v=YrmakZiZTOE')

    def test_flat_playlist_is_still_refused(self):
        """Verify flat playlist is still refused."""
        self.assertFalse(stream_harvestarr.is_single_video(FLAT_PLAYLIST))
        self.assertEqual(
            self.ytsearch({'entries': [FLAT_PLAYLIST]}, "Epicly Later'd"),
            None)

    def test_playlist_before_video_still_picks_the_video(self):
        """Verify playlist before video still picks the video."""
        self.assertEqual(
            self.ytsearch({'entries': [FLAT_PLAYLIST, FLAT_VIDEO]}),
            'https://www.youtube.com/watch?v=YrmakZiZTOE')

    def test_flat_url_is_a_watch_url_not_a_stream(self):
        """download() re-extracts this, so it must be the canonical page."""
        url = self.ytsearch({'entries': [FLAT_VIDEO]})
        self.assertIsNotNone(url)
        self.assertIn('youtube.com/watch?v=', url)
        self.assertNotIn('googlevideo.com', url)


if __name__ == '__main__':
    unittest.main()
