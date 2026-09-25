"""Regression test for request pacing during discovery."""

import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'logs', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr as app  # noqa: E402


class DiscoveryRequestPacingTests(unittest.TestCase):
    def test_search_options_honor_request_delay(self):
        client = object.__new__(app.StreamHarvester)
        client.debug = False
        client.sleep_requests = 5
        client.appendcookie = lambda options, cookies=None: options
        client.appendcredentials = lambda options, username=None, password=None: options
        self.assertEqual(client.ytdl_eps_search_opts(False)['sleep_interval_requests'], 5)


if __name__ == '__main__':
    unittest.main()
