"""
Unit tests for ``ytsearch()`` when yt-dlp hands back no metadata.

``ignoreerrors`` makes yt-dlp log and swallow extraction failures and return
None from ``extract_info`` rather than raise. That is reachable on any playlist
holding a video with a null title, which trips yt-dlp's own ``matchtitle``
regex ("expected string or bytes-like object, got 'NoneType'"). ``ytsearch()``
has to report "not found" instead of raising, or the exception escapes
``main()``, kills the scheduler, and the container restart-loops.

These exercise the *actual* method on the shipped class rather than a local
copy, so the tests stay bound to the real code path.
"""
import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

# stream_harvestarr reads CONFIGPATH and parses argv at import time, and
# setup_logging() opens ../logs/stream_harvestarr.log. Satisfy all three
# before importing; no config file is read until StreamHarvester() is built.
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402

PLAYLIST = 'https://www.youtube.com/playlist?list=TEST'


class FakeYoutubeDL(object):
    """Minimal yt_dlp.YoutubeDL stand-in usable as a context manager."""

    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        if self.exc is not None:
            raise self.exc
        return self.result


class TestYtsearchMissingMetadata(unittest.TestCase):
    """ytsearch() must always return a (found, url) pair."""

    def tearDown(self):
        stream_harvestarr.yt_dlp.YoutubeDL = self._real_ydl

    def setUp(self):
        self._real_ydl = stream_harvestarr.yt_dlp.YoutubeDL

    def ytsearch(self, **kwargs):
        stream_harvestarr.yt_dlp.YoutubeDL = lambda opts: FakeYoutubeDL(**kwargs)
        # ytsearch touches no instance state, so call it unbound rather than
        # constructing a StreamHarvester (which needs a real config.yml).
        return stream_harvestarr.StreamHarvester.ytsearch(None, {}, PLAYLIST)

    def test_none_result_returns_not_found(self):
        """extract_info() returning None must not raise."""
        self.assertEqual(self.ytsearch(result=None), (False, ''))

    def test_extraction_error_returns_not_found(self):
        """A raised extraction error must not return a bare None."""
        self.assertEqual(self.ytsearch(exc=RuntimeError('boom')), (False, ''))

    def test_entries_prefers_webpage_url(self):
        """Regression guard for issue #114 handling."""
        result = {'entries': [{'webpage_url': 'https://youtu.be/abc', 'url': None}]}
        self.assertEqual(self.ytsearch(result=result), (True, 'https://youtu.be/abc'))

    def test_entries_skips_none_entries(self):
        """Unavailable playlist members come back as None entries."""
        result = {'entries': [None, {'url': 'https://youtu.be/def'}]}
        self.assertEqual(self.ytsearch(result=result), (True, 'https://youtu.be/def'))

    def test_single_video_result(self):
        """Non-playlist results read the top-level keys."""
        result = {'webpage_url': 'https://youtu.be/ghi'}
        self.assertEqual(self.ytsearch(result=result), (True, 'https://youtu.be/ghi'))

    def test_no_match_returns_not_found(self):
        """An empty entries list means matchtitle filtered everything out."""
        self.assertEqual(self.ytsearch(result={'entries': []}), (False, ''))

    def test_playlist_url_echoed_back_is_not_a_match(self):
        """yt-dlp echoing the playlist URL back is not a found episode."""
        self.assertEqual(self.ytsearch(result={'webpage_url': PLAYLIST}), (False, ''))


if __name__ == '__main__':
    unittest.main()
