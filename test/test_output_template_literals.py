"""Regression tests for literal output-template path components."""

import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'logs', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr as app  # noqa: E402


class OutputTemplateLiteralTests(unittest.TestCase):
    def make_client(self):
        client = object.__new__(app.StreamHarvester)
        client.ytdl_format = 'best'
        client.ytdl_merge_output_format = 'mkv'
        client.root_folder = ''
        client.season_padding = client.episode_padding = 0
        client.sleep_requests = 0
        client.debug = False
        return client

    def test_percent_in_path_is_literal(self):
        options = self.make_client().download_options(
            {'title': 'Show', 'path': '/tv/100%(title)s'},
            {'title': 'Episode', 'seasonNumber': 1, 'episodeNumber': 1},
        )
        with app.yt_dlp.YoutubeDL(options) as ydl:
            filename = ydl.prepare_filename({'title': 'WRONG', 'id': 'x', 'ext': 'mkv'})
        self.assertTrue(filename.startswith('/tv/100%(title)s/'), filename)

    def test_percent_in_title_is_literal(self):
        options = self.make_client().download_options(
            {'title': 'Show', 'path': '/tv/Show'},
            {'title': '100%(title)s', 'seasonNumber': 1, 'episodeNumber': 1},
        )
        with app.yt_dlp.YoutubeDL(options) as ydl:
            filename = ydl.prepare_filename({'title': 'WRONG', 'id': 'x', 'ext': 'mkv'})
        self.assertIn('100%(title)s WEBDL', filename)


if __name__ == '__main__':
    unittest.main()
