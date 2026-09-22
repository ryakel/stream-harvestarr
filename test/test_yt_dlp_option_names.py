"""Regression tests for the yt-dlp Python API option names."""

import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'logs', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr as app  # noqa: E402


class YtDlpOptionNameTests(unittest.TestCase):
    def test_download_options_use_python_api_names(self):
        client = object.__new__(app.StreamHarvester)
        client.ytdl_format = 'best'
        client.ytdl_merge_output_format = 'mkv'
        client.root_folder = ''
        client.season_padding = client.episode_padding = 0
        client.sleep_requests = 0
        client.debug = False
        series = {'id': 1, 'title': 'Show', 'path': '/tv/Show'}
        episode = {'title': 'Episode', 'seasonNumber': 1, 'episodeNumber': 1}
        options = client.download_options(series, episode)
        self.assertEqual(options['source_address'], '0.0.0.0')
        self.assertFalse(options['continuedl'])
        self.assertEqual(options['concurrent_fragment_downloads'], 5)
        self.assertTrue(options['allow_multiple_audio_streams'])
        self.assertEqual(options['throttledratelimit'], 102400)
        for old_name in (
            'forceipv4', 'nocontinue', 'concurrent_fragments', 'audio_multistreams',
            'throttled_rate',
        ):
            self.assertNotIn(old_name, options)


if __name__ == '__main__':
    unittest.main()
