"""Regression tests for service credential inheritance."""

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


class ServiceOriginSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(app.StreamHarvester)
        self.client.services = {
            'members': {
                'title': 'members',
                'url': 'https://example.test/members',
                'username': 'user',
                'password': 'secret',
                'cookies_file': 'cookies.txt',
            }
        }

    def test_downgrade_to_http_does_not_inherit_credentials(self):
        merged = self.client.merge_service_config(
            {
                'title': 'Show',
                'service': 'members',
                'url': 'http://example.test/show',
            }
        )

        self.assertNotIn('username', merged)
        self.assertNotIn('password', merged)
        self.assertNotIn('cookies_file', merged)

    def test_protocol_relative_urls_do_not_inherit_credentials_between_hosts(self):
        self.client.services['members']['url'] = '//trusted.example/members'
        merged = self.client.merge_service_config(
            {
                'title': 'Show',
                'service': 'members',
                'url': '//other.example/video',
            }
        )

        self.assertEqual(merged['url'], '//other.example/video')
        self.assertNotIn('username', merged)
        self.assertNotIn('password', merged)
        self.assertNotIn('cookies_file', merged)

    def test_absolute_urls_with_other_schemes_do_not_inherit_credentials(self):
        for url in (
            'HTTPS://attacker.example/steal',
            'ftp://attacker.example/steal',
            '//attacker.example/steal',
        ):
            with self.subTest(url=url):
                merged = self.client.merge_service_config(
                    {'title': 'Show', 'service': 'members', 'url': url}
                )

                self.assertEqual(merged['url'], url)
                self.assertNotIn('username', merged)
                self.assertNotIn('password', merged)
                self.assertNotIn('cookies_file', merged)

    def test_secret_query_parameters_are_not_logged_during_url_merge(self):
        cases = (
            (
                'https://example.test/members?access_token=TOPSECRET',
                '',
            ),
            (
                'https://example.test/members',
                'channel?access_token=TOPSECRET',
            ),
        )
        for service_url, series_url in cases:
            with self.subTest(service_url=service_url, series_url=series_url):
                self.client.services['members']['url'] = service_url
                with self.assertLogs(app.logger, level='DEBUG') as captured:
                    self.client.merge_service_config(
                        {
                            'title': 'Show',
                            'service': 'members',
                            **({'url': series_url} if series_url else {}),
                        }
                    )

                self.assertNotIn('TOPSECRET', '\n'.join(captured.output))

    def test_collection_result_urls_are_not_logged(self):
        self.client.playlist_cache = Mock()
        self.client.playlist_cache.get.return_value = [
            {
                '_type': 'playlist',
                'url': 'https://example.test/playlist?access_token=TOPSECRET',
            }
        ]

        with self.assertLogs(app.logger, level='DEBUG') as captured:
            self.client.ytsearch({}, 'https://example.test/source')

        self.assertNotIn('TOPSECRET', '\n'.join(captured.output))

    def test_relative_url_preserves_service_path(self):
        merged = self.client.merge_service_config(
            {'title': 'Show', 'service': 'members', 'url': 'channel/123'}
        )

        self.assertEqual(merged['url'], 'https://example.test/members/channel/123')

    def test_unknown_service_skips_only_its_series(self):
        self.client.get_series = lambda: [
            {'id': 1, 'title': 'Unknown', 'path': '/tv/Unknown', 'monitored': True},
            {'id': 2, 'title': 'Known', 'path': '/tv/Known', 'monitored': True},
        ]
        self.client.series = [
            {'title': 'Unknown', 'service': 'missing', 'url': 'channel/123'},
            {'title': 'Known', 'service': 'members', 'url': 'channel/456'},
        ]

        matched = self.client.filterseries()

        self.assertEqual([series['title'] for series in matched], ['Known'])
        self.assertEqual(matched[0]['url'], 'https://example.test/members/channel/456')


if __name__ == '__main__':
    unittest.main()
