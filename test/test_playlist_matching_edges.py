"""Regression tests for playlist source and entry edge cases."""

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
from playlists import video_playlist_url  # noqa: E402


class PlaylistMatchingEdgeTests(unittest.TestCase):
    def test_share_query_is_removed_when_normalizing_channel_url(self):
        self.assertEqual(
            video_playlist_url('https://www.youtube.com/@Show?si=share-token'),
            'https://www.youtube.com/@Show/videos',
        )

    def test_tiktok_video_is_a_single_video(self):
        self.assertTrue(app.is_single_video({
            'url': 'https://www.tiktok.com/@show/video/123',
            'title': 'Episode',
        }))

    def test_untitled_url_entries_are_not_hydrated_or_matchable(self):
        source = 'https://www.patreon.com/creator'
        entry = {
            '_type': 'url',
            'ie_key': 'Patreon',
            'url': 'https://www.patreon.com/posts/episode-123',
        }

        class YoutubeDL:
            calls = []

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def extract_info(self, url, **kwargs):
                self.calls.append(url)
                if url == source:
                    return {'_type': 'playlist', 'entries': [entry]}
                return {'title': 'Episode', 'webpage_url': url}

            def process_ie_result(self, result, download=False):
                return result

        with patch.object(app.yt_dlp, 'YoutubeDL', return_value=YoutubeDL()):
            snapshot = app.PlaylistCache._extract({}, source)
        self.addCleanup(snapshot.close)
        candidate = list(snapshot)[0]
        self.assertEqual(candidate, {'title': None, 'url': entry['url']})
        self.assertEqual(YoutubeDL.calls, [source])
        self.assertFalse(app.title_matches(candidate, 'Episode'))


if __name__ == '__main__':
    unittest.main()
