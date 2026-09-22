"""Regression tests for scheduled configuration failures."""

import logging
import os
import re
import sys
import unittest
from unittest.mock import Mock, patch

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr as app  # noqa: E402


class ScheduledConfigRecoveryTests(unittest.TestCase):
    def test_scheduled_scan_survives_bad_series_settings(self):
        for error in (KeyError('url'), TypeError('series'), ValueError('offset'), re.error('regex')):
            with self.subTest(error=type(error).__name__):
                client = Mock()
                client.filterseries.side_effect = error
                with patch.object(app, 'StreamHarvester', return_value=client):
                    with self.assertLogs(app.logger, level=logging.ERROR):
                        app.main(Mock(), job=Mock())
                client.start_scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
