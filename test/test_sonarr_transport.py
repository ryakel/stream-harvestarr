"""Regression tests for Sonarr request construction and transport limits."""

import copy
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


CONFIG = {
    'streamharvestarr': {'scan_interval': '60', 'debug': 'False'},
    'sonarr': {
        'host': 'sonarr',
        'port': '8989',
        'ssl': 'false',
        'apikey': 'key',
        'basedir': '/sonarr/',
    },
    'series': [],
    'ytdl': {'default_format': 'best', 'merge_output_format': 'mkv'},
}


class SonarrTransportTests(unittest.TestCase):
    def test_sonarr_requests_have_finite_timeouts(self):
        client = object.__new__(app.StreamHarvester)
        client.api_key = 'key'
        get_response = Mock()
        post_response = Mock()
        with patch.object(app.requests, 'get', return_value=get_response) as get:
            self.assertIs(client.request_get('http://sonarr/api'), get_response)
        with patch.object(app.requests, 'post', return_value=post_response) as post:
            self.assertIs(client.request_put('http://sonarr/api', jsondata={}), post_response)
        get.assert_called_once_with(
            'http://sonarr/api?apikey=key', timeout=app.SONARR_TIMEOUT
        )
        post.assert_called_once_with(
            'http://sonarr/api',
            headers={'Content-Type': 'application/json'},
            params=(('apikey', 'key'),),
            json={},
            timeout=app.SONARR_TIMEOUT,
        )

    def test_basedir_is_joined_once(self):
        with patch.object(app, 'checkconfig', return_value=copy.deepcopy(CONFIG)), \
             patch.object(app.StreamHarvester, 'get_naming_config', return_value={}):
            client = app.StreamHarvester()
        self.assertEqual(client.base_url, 'http://sonarr:8989/sonarr')


if __name__ == '__main__':
    unittest.main()
