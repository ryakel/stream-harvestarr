"""
Unit tests for ``ytsearch()`` when yt-dlp hands back no metadata.

``ignoreerrors`` makes yt-dlp swallow errors and return None from
``extract_info``; ``ytsearch()`` must report "not found" rather than raise, or
the exception escapes ``main()`` and the container restart-loops.

These exercise the *actual* method on the shipped class rather than a local
copy, so the tests stay bound to the real code path.
"""
import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

# stream_harvestarr reads CONFIGPATH and parses argv at import time, and
# setup_logging() opens ../logs. No config file is read until __init__ runs.
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402

PLAYLIST = 'https://www.youtube.com/playlist?list=TEST'


class FakeYoutubeDL(object):
    """Minimal yt_dlp.YoutubeDL stand-in usable as a context manager."""

    def process_ie_result(self, result, download=False):
        return result

    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


    def extract_info(self, url, download=False, process=True, ie_key=None):
        """Return the configured fake extraction result."""
        if self.exc is not None:
            raise self.exc
        return self.result


class TestYtsearchMissingMetadata(unittest.TestCase):
    """ytsearch() returns a URL or None."""

    def tearDown(self):
        stream_harvestarr.yt_dlp.YoutubeDL = self._real_ydl

    def setUp(self):
        self._real_ydl = stream_harvestarr.yt_dlp.YoutubeDL
        self.client = object.__new__(stream_harvestarr.StreamHarvester)
        self.client.playlist_cache = stream_harvestarr.PlaylistCache()

    def ytsearch(self, **kwargs):
        """Return the configured test search result."""
        stream_harvestarr.yt_dlp.YoutubeDL = lambda opts: FakeYoutubeDL(**kwargs)
        return self.client.ytsearch({}, PLAYLIST)

    def test_none_result_returns_not_found(self):
        """A None result must not raise."""
        self.assertIsNone(self.ytsearch(result=None))

    def test_extraction_error_returns_not_found(self):
        """The except branch must not return a bare None."""
        self.assertIsNone(self.ytsearch(exc=RuntimeError('boom')))

    def test_entries_prefers_webpage_url(self):
        """webpage_url is preferred over url."""
        result = {'entries': [{'webpage_url': 'https://youtu.be/abc', 'url': None}]}
        self.assertEqual(self.ytsearch(result=result), 'https://youtu.be/abc')

    def test_entries_skips_none_entries(self):
        """Unavailable members come back as None entries."""
        result = {'entries': [None, {'url': 'https://youtu.be/def'}]}
        self.assertEqual(self.ytsearch(result=result), 'https://youtu.be/def')

    def test_single_video_result(self):
        """Non-playlist results read top-level keys."""
        result = {'webpage_url': 'https://youtu.be/ghi'}
        self.assertEqual(self.ytsearch(result=result), 'https://youtu.be/ghi')

    def test_no_match_returns_not_found(self):
        """Empty entries means matchtitle filtered everything out."""
        self.assertIsNone(self.ytsearch(result={'entries': []}))

    def test_playlist_url_echoed_back_is_not_a_match(self):
        """The playlist URL echoed back is not a found episode."""
        self.assertIsNone(self.ytsearch(result={'webpage_url': PLAYLIST}))


if __name__ == '__main__':
    unittest.main()
