"""
Unit tests for the RescanSeries command payload.

Sonarr v4 types seriesId as a nullable int and rejects a JSON string with
HTTP 500, so the rescan issued after every download failed and Sonarr never
imported the downloaded file.
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


class FakeResponse(object):

    def json(self):
        return {}


class TestRescanSeriesPayload(unittest.TestCase):
    """The command body must carry seriesId as an int."""

    def setUp(self):
        # Bypass __init__ (it needs a real config.yml) and set only what
        # rescanseries reads.
        self.client = object.__new__(stream_harvestarr.StreamHarvester)
        self.client.base_url = 'http://sonarr:8989'
        self.client.sonarr_api_version = 'api/v3'
        self.sent = {}

        def request_put(url, params=None, jsondata=None):
            self.sent['url'] = url
            self.sent['data'] = jsondata
            return FakeResponse()

        self.client.request_put = request_put

    def test_series_id_sent_as_int(self):
        self.client.rescanseries(314)
        self.assertEqual(self.sent['data'], {'name': 'RescanSeries', 'seriesId': 314})

    def test_numeric_string_is_coerced(self):
        self.client.rescanseries('314')
        self.assertIsInstance(self.sent['data']['seriesId'], int)

    def test_posts_to_command_endpoint(self):
        self.client.rescanseries(314)
        self.assertEqual(self.sent['url'], 'http://sonarr:8989/api/v3/command')


if __name__ == '__main__':
    unittest.main()
