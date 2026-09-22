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


if __name__ == '__main__':
    unittest.main()
