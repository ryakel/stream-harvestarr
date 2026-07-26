"""
Unit tests for the Shorts exclusion in ytdl_eps_search_opts().

yt-dlp calls match_filter with (info_dict, incomplete) and expects None to mean
"keep" or a string to mean "skip, and here is why". These bind to the options
the app actually builds, so the filter can't regress to a value yt-dlp ignores.
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

# Shapes taken from a flat extraction of a channel's shorts and videos tabs.
SHORT = {'id': 'vWMkRkYbq5A', 'title': 'a clip', 'url': 'https://www.youtube.com/shorts/vWMkRkYbq5A'}
EPISODE = {'id': 'mc9WVVAUQGE', 'title': 'an episode', 'url': 'https://www.youtube.com/watch?v=mc9WVVAUQGE'}


class TestShortsFilter(unittest.TestCase):
    """The built options must carry a working Shorts filter."""

    def setUp(self):
        # Bypass __init__ (it needs a real config.yml); ytdl_eps_search_opts
        # only reads self.debug, and the cookie/credential helpers no-op on None.
        self.client = object.__new__(stream_harvestarr.StreamHarvester)
        self.client.debug = False

    def match_filter(self):
        opts = self.client.ytdl_eps_search_opts('SOME[\\ ]*EPISODE', 'False')
        return opts['match_filter']

    def test_filter_is_callable(self):
        """A plain string here raises TypeError when yt-dlp calls it."""
        self.assertTrue(callable(self.match_filter()))

    def test_short_is_skipped(self):
        """A skip returns the reason string, not None."""
        self.assertIsNotNone(self.match_filter()(SHORT))

    def test_episode_is_kept(self):
        self.assertIsNone(self.match_filter()(EPISODE))

    def test_missing_url_is_kept(self):
        """Merged formats have no top-level url; those must not be dropped."""
        entry = {'id': 'x', 'title': 'y'}
        self.assertIsNone(self.match_filter()(entry))
        self.assertIsNone(self.match_filter()(entry, incomplete=True))


if __name__ == '__main__':
    unittest.main()
