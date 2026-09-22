"""Regression tests for log secret redaction."""

import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))

from utils import YoutubeDLLogger, redact_sensitive  # noqa: E402


class SensitiveRedactionTests(unittest.TestCase):
    def test_api_key_query_parameter_is_redacted(self):
        result = redact_sensitive('https://sonarr/api?api_key=SECRET&other=value')

        self.assertNotIn('SECRET', result)
        self.assertIn('api_key=***REDACTED***', result)
        self.assertIn('other=value', result)

    def test_sensitive_query_parameters_are_redacted(self):
        result = redact_sensitive(
            'https://site.example/?access_token=SECRET&client_id=public'
        )

        self.assertNotIn('SECRET', result)
        self.assertIn('access_token=***REDACTED***', result)
        self.assertIn('client_id=public', result)

    def test_encoded_secret_keys_and_url_userinfo_are_redacted(self):
        result = redact_sensitive(
            'https://alice:p@ssSECRET@site.example/?access%5Ftoken=TOKEN'
        )

        self.assertNotIn('p@ssSECRET', result)
        self.assertNotIn('ssSECRET', result)
        self.assertNotIn('TOKEN', result)
        self.assertIn('***REDACTED***@site.example', result)
        self.assertIn('access%5Ftoken=***REDACTED***', result)

    def test_ytdlp_logger_omits_serialized_credential_options(self):
        options = (
            "yt-dlp opts: {'username': 'alice', 'password': 'TOPSECRET', "
            "'cookiefile': '/home/alice/cookies.txt'}"
        )

        with self.assertLogs('stream_harvestarr', level='DEBUG') as logs:
            YoutubeDLLogger().debug(options)

        output = '\n'.join(logs.output)
        for secret in ('alice', 'TOPSECRET', '/home/alice/cookies.txt'):
            self.assertNotIn(secret, output)
        self.assertIn('omitted', output)


if __name__ == '__main__':
    unittest.main()
