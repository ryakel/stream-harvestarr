"""Regression tests for UTC episode airdate filtering."""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr as app  # noqa: E402


class UtcAirdateTests(unittest.TestCase):
    def test_missing_utc_airdate_is_treated_as_available(self):
        client = object.__new__(app.StreamHarvester)
        client.get_episodes_by_series_id = Mock(return_value=[{
            'seriesId': 1,
            'title': 'TBA episode',
            'monitored': True,
            'hasFile': False,
            'airDateUtc': None,
        }])

        self.assertEqual(
            [episode['title'] for episode in client.getseriesepisodes([{'id': 1, 'title': 'Show'}])],
            ['TBA episode'],
        )

    def test_future_utc_episode_is_not_downloaded_from_ahead_timezone(self):
        current = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return current if tz is not None else (current + timedelta(hours=8)).replace(tzinfo=None)

        client = object.__new__(app.StreamHarvester)
        client.get_episodes_by_series_id = Mock(return_value=[{
            'seriesId': 1,
            'title': 'Episode',
            'monitored': True,
            'hasFile': False,
            'airDateUtc': '2026-01-01T12:30:00Z',
        }])
        series = [{'id': 1, 'title': 'Show'}]
        with patch.object(app, 'datetime', Clock):
            self.assertEqual(client.getseriesepisodes(series), [])


if __name__ == '__main__':
    unittest.main()
