"""Regression test for direct video source matching."""

import os
import sys
import unittest
from unittest.mock import patch

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr as app  # noqa: E402
from playlist_snapshot import PlaylistSnapshot  # noqa: E402


class DirectVideoMatchingTests(unittest.TestCase):
    def test_direct_video_source_can_match_itself(self):
        client = object.__new__(app.StreamHarvester)
        client.playlist_cache = app.PlaylistCache()
        self.addCleanup(client.playlist_cache.close)
        with patch.object(
            app.PlaylistCache,
            '_extract',
            staticmethod(lambda options, url: PlaylistSnapshot([('Episode', url)])),
        ):
            self.assertEqual(
                client.ytsearch({}, 'https://example.com/video', app.upperescape('Episode')),
                'https://example.com/video',
            )


if __name__ == '__main__':
    unittest.main()
