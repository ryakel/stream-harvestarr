"""Regression tests for scheduled scan lifecycle behavior."""

import os
import sys
import unittest
from unittest.mock import Mock, call, patch

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402


SERIES = [{'id': 1, 'title': 'Show', 'path': '/tv/Show'}]
EPISODE = {'seriesId': 1, 'title': 'Episode', 'seasonNumber': 1, 'episodeNumber': 1}


class ScanLifecycleTests(unittest.TestCase):
    def test_each_scan_reloads_the_harvester_around_shared_cache(self):
        cache = Mock()
        clients = []
        for _ in range(2):
            client = Mock()
            client.playlist_cache = cache
            client.filterseries.return_value = []
            client.getseriesepisodes.return_value = []
            clients.append(client)

        with patch.object(stream_harvestarr, 'StreamHarvester', side_effect=clients) as constructor:
            stream_harvestarr.main(cache)
            stream_harvestarr.main(cache)

        self.assertEqual(constructor.call_args_list, [call(cache), call(cache)])
        for client in clients:
            client.start_scan.assert_called_once_with([])
            client.getseriesepisodes.assert_called_once_with([])
            client.download.assert_called_once_with([], [])
        self.assertEqual(cache.end_scan.call_count, 2)

    def test_sonarr_rescan_failure_stays_inside_download_error_boundary(self):
        client = object.__new__(stream_harvestarr.StreamHarvester)
        client.find_episode = Mock(return_value='https://youtu.be/video')
        client.download_options = Mock(return_value={})
        client.download_video = Mock()
        client.rescanseries = Mock(side_effect=RuntimeError('Sonarr unavailable'))
        client.handle_download_error = Mock(return_value=False)

        series = SERIES[0]
        with self.assertLogs(stream_harvestarr.logger, level='WARNING'):
            result = client.download_episode(series, EPISODE, 1)

        self.assertFalse(result)
        client.rescanseries.assert_called_once_with(series['id'])
        client.handle_download_error.assert_not_called()


if __name__ == '__main__':
    unittest.main()
