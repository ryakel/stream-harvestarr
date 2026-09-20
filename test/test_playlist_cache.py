"""Regression tests for the once-per-scan flat playlist extraction."""

import os
import sqlite3
import sys
import tracemalloc
import unittest
from unittest.mock import Mock, patch

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402
from playlists import is_youtube_url, video_playlist_url


class FakeYoutubeDL(object):
    calls = []
    results = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        type(self).calls.append(self.opts)
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False, process=True, ie_key=None):
        """Return the configured fake extraction result."""
        type(self).urls.append(url)
        self.opts['process'] = process
        result = type(self).results.pop(0)
        if result is not None and is_youtube_url(url):
            result.setdefault('extractor_key', 'YoutubeTab')
        return result

    def process_ie_result(self, result, download=False):
        self.opts['process'] = True
        return result


class PlaylistCacheTestCase(unittest.TestCase):
    def setUp(self):
        self.cache = stream_harvestarr.PlaylistCache()
        self.addCleanup(self.cache.close)
        FakeYoutubeDL.calls = []
        FakeYoutubeDL.urls = []
        FakeYoutubeDL.results = []
        self.enterContext(patch.object(stream_harvestarr.yt_dlp, 'YoutubeDL', FakeYoutubeDL))

    def test_bare_channel_uses_videos_tab(self):
        """Verify bare channel uses videos tab."""
        self.assertEqual(
            video_playlist_url('https://www.youtube.com/@VICE'),
            'https://www.youtube.com/@VICE/videos',
        )
        self.assertEqual(
            video_playlist_url('https://www.youtube.com/@VICE/search?query=x'),
            'https://www.youtube.com/@VICE/search?query=x',
        )
        self.assertEqual(
            video_playlist_url('https://www.youtube.com/@VICE/videos'),
            'https://www.youtube.com/@VICE/videos',
        )
        self.assertEqual(
            video_playlist_url('https://example.com/@VICE'), 'https://example.com/@VICE'
        )
        self.assertEqual(
            stream_harvestarr.video_search_url('https://www.youtube.com/@VICE/videos', 'Episode 1'),
            'https://www.youtube.com/@VICE/search?query=Episode+1',
        )
        self.assertIsNone(
            stream_harvestarr.video_search_url('https://example.com/@VICE', 'Episode 1')
        )

    def test_refreshes_once_and_replaces_entries(self):
        """Verify refreshes once and replaces entries."""
        playlist = 'https://www.youtube.com/@VICE'
        opts = {'playlistreverse': False}
        first = {'entries': [{'url': 'https://youtu.be/old', 'title': 'old'}]}
        second = {'entries': [{'url': 'https://youtu.be/new', 'title': 'new'}]}
        FakeYoutubeDL.results = [first, second]

        first_scan = self.cache.get(opts, playlist)
        same_scan = self.cache.get(opts, playlist)
        self.assertEqual(first_scan, same_scan)
        self.assertEqual(len(FakeYoutubeDL.calls), 1)
        self.assertEqual(FakeYoutubeDL.urls, [playlist + '/videos'])

        self.cache.begin_scan()
        next_scan = self.cache.get(opts, playlist)
        self.assertEqual([entry['url'] for entry in next_scan], ['https://youtu.be/new'])
        self.assertNotIn('playlistend', FakeYoutubeDL.calls[1])

    def test_failed_refresh_keeps_last_good_entries(self):
        """Verify failed refresh keeps last good entries."""
        playlist = 'https://www.youtube.com/@VICE'
        opts = {'playlistreverse': False}
        FakeYoutubeDL.results = [
            {'entries': [{'url': 'https://youtu.be/old', 'title': 'old'}]},
            None,
        ]

        self.assertEqual(len(self.cache.get(opts, playlist)), 1)
        self.cache.begin_scan()
        self.assertEqual(
            [entry['url'] for entry in self.cache.get(opts, playlist)], ['https://youtu.be/old']
        )

    def test_extraction_failure_is_diagnosed_and_preserves_snapshot(self):
        """Extraction errors must be visible with and without a cached snapshot."""
        url = 'https://www.youtube.com/@VICE/videos'
        FakeYoutubeDL.results = [{'entries': [{'url': 'https://youtu.be/old'}]}]
        previous = self.cache.get({}, url)
        for cache, diagnostic in (
            (self.cache, 'previous complete snapshot'),
            (stream_harvestarr.PlaylistCache(), 'no snapshot is available'),
        ):
            cache.begin_scan()
            with patch.object(
                FakeYoutubeDL, 'extract_info', side_effect=ValueError('invalid response')
            ):
                with self.assertLogs(stream_harvestarr.logger, level='WARNING') as logs:
                    result = cache.get({}, url)
            self.assertIn('invalid response', '\n'.join(logs.output))
            self.assertIn(diagnostic, '\n'.join(logs.output))
            if cache is self.cache:
                self.assertIs(result, previous)
            else:
                self.assertEqual(list(result), [])

    def test_playlist_reverse_is_applied_without_duplicate_extraction(self):
        """Verify playlist reverse is applied without duplicate extraction."""
        playlist = 'https://www.youtube.com/playlist?list=TEST'
        FakeYoutubeDL.results = [
            {
                'entries': [
                    {'url': 'https://youtu.be/one', 'title': 'one'},
                    {'url': 'https://youtu.be/two', 'title': 'two'},
                ]
            }
        ]

        self.assertEqual(
            [entry['url'] for entry in self.cache.get({'playlistreverse': False}, playlist)],
            ['https://youtu.be/one', 'https://youtu.be/two'],
        )
        self.assertEqual(
            [entry['url'] for entry in self.cache.get({'playlistreverse': True}, playlist)],
            ['https://youtu.be/two', 'https://youtu.be/one'],
        )
        self.assertEqual(len(FakeYoutubeDL.calls), 1)

    def test_begin_scan_prunes_removed_sources(self):
        """Verify begin scan prunes removed sources."""
        first = 'https://www.youtube.com/playlist?list=FIRST'
        second = 'https://www.youtube.com/playlist?list=SECOND'
        FakeYoutubeDL.results = [
            {'entries': [{'url': 'https://youtu.be/one'}]},
            {'entries': [{'url': 'https://youtu.be/two'}]},
        ]
        self.cache.get({}, first)
        self.cache.get({}, second)

        self.cache.begin_scan({first})
        self.assertEqual(len(self.cache.entries), 1)
        self.assertEqual(len(FakeYoutubeDL.calls), 2)

    def test_begin_scan_closes_removed_source_snapshots(self):
        """Verify removed source snapshots close at scan start."""
        first = 'https://www.youtube.com/playlist?list=FIRST'
        second = 'https://www.youtube.com/playlist?list=SECOND'
        FakeYoutubeDL.results = [
            {'entries': [{'url': 'https://youtu.be/one'}]},
            {'entries': [{'url': 'https://youtu.be/two'}]},
        ]
        self.cache.get({}, first)
        self.cache.get({}, second)
        connection = self.cache.entries[self.cache._key({}, second)]._connection

        self.cache.begin_scan({first})

        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')

    def test_refresh_closes_replaced_snapshot(self):
        """Verify a successful refresh closes the previous snapshot."""
        playlist = 'https://www.youtube.com/@VICE'
        FakeYoutubeDL.results = [
            {'entries': [{'url': 'https://youtu.be/old'}]},
            {'entries': [{'url': 'https://youtu.be/new'}]},
        ]
        self.cache.get({}, playlist)
        connection = self.cache.entries[self.cache._key({}, playlist)]._connection

        self.cache.begin_scan()
        self.cache.get({}, playlist)

        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')

    def test_later_page_failure_preserves_complete_snapshot(self):
        """Verify later page failure preserves complete snapshot."""

        def broken_pages():
            """Provide a partial page followed by an extraction failure."""
            yield {'url': 'https://youtu.be/partial', 'title': 'Partial'}
            raise RuntimeError('second page failed')

        url = 'https://www.youtube.com/@VICE/videos'
        FakeYoutubeDL.results = [
            {'entries': [{'url': 'https://youtu.be/old', 'title': 'Old'}]},
            {'entries': broken_pages()},
        ]
        previous = self.cache.get({}, url)
        self.cache.begin_scan()
        with self.assertLogs(stream_harvestarr.logger, level='ERROR'):
            current = self.cache.get({}, url)
        self.assertIs(current, previous)
        self.assertEqual(list(current), [{'url': 'https://youtu.be/old', 'title': 'Old'}])

    def test_cache_extraction_disables_ignored_errors(self):
        """Verify extraction cannot silently publish a partial playlist."""
        FakeYoutubeDL.results = [{'entries': []}]
        self.cache.get({'ignoreerrors': True}, 'https://www.youtube.com/@VICE/videos')
        self.assertFalse(FakeYoutubeDL.calls[0]['ignoreerrors'])

    def test_non_youtube_sources_preserve_error_tolerance(self):
        FakeYoutubeDL.results = [{'entries': []}]
        self.cache.get({'ignoreerrors': True}, 'https://example.com/playlist')
        self.assertTrue(FakeYoutubeDL.calls[0]['ignoreerrors'])

    def test_cache_extraction_raises_on_incomplete_youtube_data(self):
        """Verify incomplete YouTube responses are configured as failures."""
        FakeYoutubeDL.results = [{'entries': []}]
        self.cache.get({}, 'https://www.youtube.com/@VICE/videos')
        self.assertEqual(
            FakeYoutubeDL.calls[0]['extractor_args']['youtube']['raise_incomplete_data'], ['true']
        )

    def test_non_youtube_sources_keep_normal_processing(self):
        """Verify non youtube sources keep normal processing."""
        FakeYoutubeDL.results = [{'entries': [{'url': 'https://example.com/video'}]}]
        self.cache.get({}, 'https://example.com/playlist')
        self.assertTrue(FakeYoutubeDL.calls[0]['process'])

    def test_end_scan_releases_obsolete_credentials(self):
        url = 'https://www.youtube.com/@VICE'
        FakeYoutubeDL.results = [{'entries': []}, {'entries': []}]
        previous = self.cache.get({'password': 'old'}, url)
        self.cache.begin_scan({url})
        current = self.cache.get({'password': 'new'}, url)
        self.cache.end_scan()
        self.assertEqual(len(self.cache.entries), 1)
        self.assertEqual(list(current), [])
        with self.assertRaises(sqlite3.ProgrammingError):
            list(previous)

    def test_close_releases_all_snapshots(self):
        FakeYoutubeDL.results = [{'entries': []}]
        snapshot = self.cache.get({}, 'https://example.test/playlist')
        self.cache.close()
        self.cache.close()
        self.assertEqual(self.cache.entries, {})
        self.assertEqual(self.cache.refreshed, set())
        with self.assertRaises(sqlite3.ProgrammingError):
            list(snapshot)

    def test_redirect_loop_preserves_previous_snapshot(self):
        url = 'https://www.youtube.com/@VICE/videos'
        FakeYoutubeDL.results = [
            {'entries': [{'url': 'https://youtu.be/old'}]},
            {'_type': 'url', 'url': url},
        ]
        previous = self.cache.get({}, url)
        self.cache.begin_scan()
        with self.assertLogs(stream_harvestarr.logger, level='ERROR') as logs:
            self.assertIs(self.cache.get({}, url), previous)
        self.assertIn('redirect loop', str(logs.output))


class UpstreamExtractionTests(unittest.TestCase):
    """Exercise real yt-dlp processing with network responses replaced."""

    def setUp(self):
        from yt_dlp.extractor.common import InfoExtractor
        from yt_dlp.extractor.youtube import YoutubeTabIE

        self.cache = stream_harvestarr.PlaylistCache()
        self.addCleanup(self.cache.close)
        self.seen = []
        self.incomplete = False
        self.tab = False
        self.count = 25
        test = self

        class FixtureIE(InfoExtractor):
            _VALID_URL = r'https://example.test/(?P<id>playlist|redirect)'

            def _real_extract(self, url):
                if self._match_id(url) == 'redirect':
                    result = self.url_result('https://example.test/playlist', ie=FixtureIE)
                else:
                    result = self.playlist_result(self.entries(), 'fixture')
                if test.tab:
                    result['extractor_key'] = 'YoutubeTab'
                return result

            def entries(self):
                for number in range(test.count):
                    if test.count < 100:
                        test.seen.append(number)
                    yield {
                        '_type': 'url',
                        'ie_key': 'Youtube',
                        'url': f'https://www.youtube.com/watch?v={number:011d}',
                        'id': f'{number:011d}',
                        'title': f'Episode {number}',
                    }
                if test.incomplete:
                    extractor = YoutubeTabIE(self._downloader)
                    with patch.object(extractor, '_call_api', return_value={}):
                        extractor._extract_response('fixture', {}, check_get_keys='contents')

        real_ydl = stream_harvestarr.yt_dlp.YoutubeDL

        def client(options):
            ydl = real_ydl({**options, 'quiet': True, 'extractor_retries': 0}, auto_init=False)
            ydl.add_info_extractor(FixtureIE())
            return ydl

        self.enterContext(patch.object(stream_harvestarr.yt_dlp, 'YoutubeDL', side_effect=client))

    def test_search_limit_and_redirect_use_upstream_processing(self):
        url = 'https://example.test/redirect'
        bounded = self.cache.get({'playlistend': 20}, url)
        self.assertEqual(len(bounded), 20)
        self.assertEqual(self.seen, list(range(20)))
        self.seen.clear()
        full = self.cache.get({}, url)
        self.assertEqual(len(full), 25)
        self.assertEqual(self.seen, list(range(25)))
        self.assertEqual(next(reversed(full))['title'], 'Episode 24')

    def test_incomplete_response_preserves_previous_snapshot(self):
        for tab in (False, True):
            with self.subTest(tab=tab):
                self.tab = tab
                self.incomplete = False
                self.cache.begin_scan()
                url = 'https://example.test/playlist'
                previous = self.cache.get({}, url)
                self.assertEqual(len(previous), 25)
                self.cache.begin_scan()
                self.incomplete = True
                with self.assertLogs(stream_harvestarr.logger, level='ERROR'):
                    current = self.cache.get({}, url)
                self.assertIs(current, previous)
                self.assertEqual(len(current), 25)

    def test_tab_redirect_and_limit_keep_streaming(self):
        self.tab = True
        self.test_search_limit_and_redirect_use_upstream_processing()

    def test_tab_extraction_does_not_retain_full_metadata(self):
        self.tab = True
        self.count = 100_000
        tracemalloc.start()
        try:
            snapshot = self.cache.get({}, 'https://example.test/redirect')
            self.assertEqual(len(snapshot), self.count)
            self.assertEqual(next(reversed(snapshot))['title'], 'Episode 99999')
            self.assertLess(tracemalloc.get_traced_memory()[1], 8 * 1024 * 1024)
        finally:
            tracemalloc.stop()


class EpisodeSearchTestCase(unittest.TestCase):
    def test_channel_search_is_bounded_before_full_scan(self):
        """Verify channel search is bounded before full scan."""
        client = object.__new__(stream_harvestarr.StreamHarvester)
        client.playlist_cache = stream_harvestarr.PlaylistCache()
        client.ytdl_eps_search_opts = Mock(return_value={'playlistreverse': False})
        options_seen = []
        urls_seen = []
        results = iter((None, None, 'https://youtu.be/full-scan'))

        def ytsearch(options, url, *args):
            """Return the next staged channel-search result."""
            options_seen.append(dict(options))
            urls_seen.append(url)
            return next(results)

        client.ytsearch = Mock(side_effect=ytsearch)
        series = {
            'channel_search': True,
            'url': 'https://www.youtube.com/@VICE/videos',
            'playlistreverse': False,
        }
        episode = {'title': 'Episode 1'}

        result = client.find_episode(series, episode)

        self.assertEqual(result, 'https://youtu.be/full-scan')
        first_options = options_seen[0]
        self.assertEqual(first_options['playlistend'], 20)
        self.assertTrue(first_options['lazy_playlist'])
        self.assertEqual(urls_seen[0], 'https://www.youtube.com/@VICE/search?query=Episode+1')
        second_options = options_seen[1]
        self.assertNotIn('playlistend', second_options)
        self.assertEqual(urls_seen[1], 'https://www.youtube.com/@VICE/search?query=Episode+1')
        self.assertEqual(urls_seen[2], 'https://www.youtube.com/@VICE/videos')


if __name__ == '__main__':
    unittest.main()
