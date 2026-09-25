"""Each scan reads a complete configuration; only playlist data is shared."""

import copy
import logging
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
    'sonarr': {'host': 'sonarr', 'port': '8989', 'ssl': 'false', 'apikey': 'old'},
    'series': [{'title': 'Before', 'url': 'https://example.test/channel'}],
    'ytdl': {'default_format': 'best', 'merge_output_format': 'mkv'},
}


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.cache = app.PlaylistCache()
        self.addCleanup(self.cache.close)
        self.enterContext(patch.object(app, 'SCANINTERVAL', 60))
        self.enterContext(patch.object(app.StreamHarvester, 'get_naming_config', return_value={}))
        self.enterContext(patch.object(app.StreamHarvester, 'getseriesepisodes', return_value=[]))
        self.enterContext(patch.object(app.StreamHarvester, 'download'))
        self.clients = []

        def filterseries(client):
            self.clients.append(client)
            return client.series

        self.enterContext(patch.object(app.StreamHarvester, 'filterseries', filterseries))

    def test_next_scan_reads_all_settings_and_keeps_cache(self):
        changed = copy.deepcopy(CONFIG)
        changed['sonarr'].update(host='new-sonarr', apikey='new', root_folder='/new')
        changed['streamharvestarr'].update(download_delay='15', rate_limit_sleep='40')
        changed['ytdl']['default_format'] = 'worst'
        changed['series'][0]['title'] = 'After'
        changed['services'] = [{'title': 'shared', 'url': 'https://example.test'}]
        with patch.object(app, 'checkconfig', side_effect=[CONFIG, changed]) as read:
            app.main(self.cache)
            app.main(self.cache)
        self.assertEqual(read.call_count, 2)
        first, second = self.clients
        self.assertIsNot(first, second)
        self.assertIs(second.playlist_cache, self.cache)
        self.assertEqual(first.api_key, 'old')
        self.assertEqual(second.api_key, 'new')
        self.assertEqual(second.base_url, 'http://new-sonarr:8989')
        self.assertEqual(second.root_folder, '/new')
        self.assertEqual(second.download_delay, 15)
        self.assertEqual(second.rate_limit_sleep, 40)
        self.assertEqual(second.series[0]['title'], 'After')
        self.assertEqual(second.services['shared']['url'], 'https://example.test')
        self.assertEqual(second.ytdl_format, 'worst')

    def test_invalid_config_does_not_mutate_an_existing_client(self):
        with patch.object(app, 'checkconfig', return_value=CONFIG):
            app.main(self.cache)
        previous = self.clients[0]
        broken = copy.deepcopy(CONFIG)
        broken['series'][0]['title'] = 'Must not apply'
        del broken['ytdl']['merge_output_format']
        with patch.object(app, 'checkconfig', return_value=broken):
            with self.assertRaises(SystemExit):
                app.main(self.cache)
        self.assertEqual(previous.series[0]['title'], 'Before')
        self.assertEqual(len(self.clients), 1)

    def test_config_can_turn_debug_back_off(self):
        debug_config = copy.deepcopy(CONFIG)
        debug_config['streamharvestarr']['debug'] = 'True'
        with patch.object(app, 'checkconfig', side_effect=[debug_config, CONFIG]):
            app.main(self.cache)
            self.assertEqual(app.logger.level, logging.DEBUG)
            app.main(self.cache)
        self.assertEqual(app.logger.level, logging.INFO)

    def test_scheduled_scan_applies_new_interval(self):
        cfg = copy.deepcopy(CONFIG)
        cfg['streamharvestarr']['scan_interval'] = '15'
        scheduler = app.schedule.Scheduler()
        job = scheduler.every(60).minutes
        job.do(app.main, self.cache, job=job)
        with patch.object(app, 'checkconfig', return_value=cfg):
            job.run()
        self.assertEqual(job.interval, 15)
        seconds = (job.next_run - job.last_run).total_seconds()
        self.assertAlmostEqual(seconds, 15 * 60, delta=1)

    def test_scheduled_scan_keeps_retrying_after_invalid_config(self):
        scheduler = app.schedule.Scheduler()
        job = scheduler.every(60).minutes
        job.do(app.main, self.cache, job=job)
        with patch.object(app, 'checkconfig', return_value={'broken': True}):
            job.run()
        self.assertEqual(self.clients, [])

    def test_scheduled_scan_survives_malformed_config(self):
        scheduler = app.schedule.Scheduler()
        job = scheduler.every(60).minutes
        job.do(app.main, self.cache, job=job)
        with patch.object(
            app, 'checkconfig', side_effect=app.yaml.YAMLError('password=SYNTHETIC_PASSWORD')
        ):
            with self.assertLogs(app.logger, level='ERROR') as logs:
                job.run()
        self.assertEqual(self.clients, [])
        self.assertNotIn('SYNTHETIC_PASSWORD', '\n'.join(logs.output))

    def test_initial_run_still_raises_malformed_config(self):
        with patch.object(app, 'checkconfig', side_effect=app.yaml.YAMLError('malformed')):
            with self.assertRaises(app.yaml.YAMLError):
                app.main(self.cache)

    def test_scan_interval_rejects_scheduler_overflow(self):
        with self.assertRaisesRegex(ValueError, 'too large'):
            app.StreamHarvester.set_scan_interval(object.__new__(app.StreamHarvester), 10**20)
        self.assertEqual(app.SCANINTERVAL, 60)

    def test_invalid_later_config_does_not_apply_scan_interval(self):
        cfg = copy.deepcopy(CONFIG)
        cfg['streamharvestarr']['scan_interval'] = '15'
        del cfg['ytdl']['merge_output_format']

        with patch.object(app, 'checkconfig', return_value=cfg), \
             patch.object(app.StreamHarvester, 'get_naming_config', return_value={}):
            with self.assertRaises(SystemExit):
                app.StreamHarvester()

        self.assertEqual(app.SCANINTERVAL, 60)

    def test_nonfinite_backoff_multiplier_uses_safe_default(self):
        cfg = copy.deepcopy(CONFIG)
        cfg['streamharvestarr']['backoff_multiplier'] = 'nan'
        with patch.object(app, 'checkconfig', return_value=cfg), \
             patch.object(app.StreamHarvester, 'get_naming_config', return_value={}):
            client = app.StreamHarvester()
        self.assertEqual(client.backoff_multiplier, 2.0)

    def test_negative_durations_use_safe_defaults(self):
        cfg = copy.deepcopy(CONFIG)
        cfg['streamharvestarr'].update(
            download_delay='-1',
            sleep_requests='-1',
            rate_limit_sleep='-1',
            backoff_max='-1',
        )
        with patch.object(app, 'checkconfig', return_value=cfg), \
             patch.object(app.StreamHarvester, 'get_naming_config', return_value={}):
            client = app.StreamHarvester()

        self.assertEqual(client.download_delay, 0)
        self.assertEqual(client.sleep_requests, 0)
        self.assertEqual(client.rate_limit_sleep, 900)
        self.assertEqual(client.backoff_max, 3600)


class WantedEpisodeTests(unittest.TestCase):
    def test_filtering_is_ordered_and_does_not_mutate_api_results(self):
        client = object.__new__(app.StreamHarvester)
        series = [
            {'id': 1, 'title': 'One', 'sonarr_regex_match': '^Prefix ', 'sonarr_regex_replace': ''},
            {'id': 2, 'title': 'Two'},
        ]
        episodes = [
            {'title': 'Prefix Wanted', 'monitored': True, 'hasFile': False},
            {'title': 'Disabled', 'monitored': False, 'hasFile': False},
            {'title': 'Downloaded', 'monitored': True, 'hasFile': True},
            {
                'title': 'Future',
                'monitored': True,
                'hasFile': False,
                'airDateUtc': '2999-01-01T00:00:00Z',
            },
        ]
        original = copy.deepcopy(episodes)
        client.get_episodes_by_series_id = Mock(side_effect=[episodes, []])
        wanted = client.getseriesepisodes(series)
        self.assertEqual([episode['title'] for episode in wanted], ['Wanted'])
        self.assertEqual([item['id'] for item in series], [1])
        self.assertEqual(episodes, original)


if __name__ == '__main__':
    unittest.main()
