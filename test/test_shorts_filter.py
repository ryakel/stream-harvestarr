"""Regression tests for local Shorts filtering."""
import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402


class FakeYoutubeDL(object):
    def process_ie_result(self, result, download=False):
        return result


    def __init__(self, result):
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


    def extract_info(self, url, download=False, process=True, ie_key=None):
        """Return the configured fake extraction result."""
        return self.result


class TestShortsFilter(unittest.TestCase):

    def setUp(self):
        self.real_ydl = stream_harvestarr.yt_dlp.YoutubeDL
        self.client = object.__new__(stream_harvestarr.StreamHarvester)
        self.client.playlist_cache = stream_harvestarr.PlaylistCache()

    def tearDown(self):
        stream_harvestarr.yt_dlp.YoutubeDL = self.real_ydl

    def search(self, entry):
        """Return the configured test search result."""
        stream_harvestarr.yt_dlp.YoutubeDL = lambda options: FakeYoutubeDL({
            'entries': [entry],
        })
        return self.client.ytsearch(
            {}, 'https://www.youtube.com/@VICE', 'some episode')

    def test_short_is_skipped(self):
        """Verify short is skipped."""
        self.assertIsNone(self.search({
            'title': 'some episode',
            'url': 'https://www.youtube.com/shorts/abc',
        }))

    def test_episode_is_kept(self):
        """Verify episode is kept."""
        self.assertEqual(
            self.search({
                'title': 'some episode',
                'url': 'https://www.youtube.com/watch?v=abc',
            }),
            'https://www.youtube.com/watch?v=abc')


if __name__ == '__main__':
    unittest.main()
