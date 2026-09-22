"""Regression tests for log secret redaction."""

import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))

from utils import redact_sensitive  # noqa: E402


class SensitiveRedactionTests(unittest.TestCase):
    def test_api_key_query_parameter_is_redacted(self):
        result = redact_sensitive('https://sonarr/api?api_key=SECRET&other=value')

        self.assertNotIn('SECRET', result)
        self.assertIn('api_key=***REDACTED***', result)
        self.assertIn('other=value', result)


if __name__ == '__main__':
    unittest.main()
