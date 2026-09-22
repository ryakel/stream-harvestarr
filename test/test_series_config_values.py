"""Regression tests for Sonarr series configuration values."""

import copy
import os
import sys
import unittest
from unittest.mock import Mock

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr as app  # noqa: E402


class SeriesConfigValueTests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(app.StreamHarvester)
        self.client.services = {}
        self.client.series = [{
            'title': 'Show',
            'url': 'https://www.youtube.com/@Show',
        }]
        self.client.get_series = Mock(return_value=[{
            'id': 1,
            'title': 'Show',
            'path': '/tv/Show',
            'monitored': True,
        }])

    def test_unmonitored_series_is_not_downloaded(self):
        self.client.get_series.return_value[0]['monitored'] = False
        self.assertEqual(self.client.filterseries(), [])

    def test_lowercase_false_disables_playlist_reverse(self):
        self.client.series[0]['playlistreverse'] = 'false'
        self.assertFalse(self.client.filterseries()[0]['playlistreverse'])


if __name__ == '__main__':
    unittest.main()
