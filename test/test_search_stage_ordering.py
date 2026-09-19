"""
Unit tests for candidate ordering across ``find_episode()``'s three stages.

``playlistreverse`` is the user's oldest-first/newest-first axis on a
*chronological* video tab, and ``PlaylistCache.get()`` applies it by reversing
the candidate list. Stages one and two do not read a video tab: they read
``@CHANNEL/search?query=...``, which YouTube orders by **relevance**. Reversing
that means preferring the worst result that still passes the matching rules,
and ``playlistreverse`` defaults to True (``ser['playlistreverse'] = True`` in
``filterseries``), so the default config is the affected one. ``playlistend``
bounds stage one to CHANNEL_SEARCH_LIMIT hits, so leaving it set made the
default prefer rank 20 over rank 1.

This matters because "the pattern matched" is not "this is the only match".
Where several candidates pass every rule -- a re-upload beside an original, a
multi-part upload with ``strict_parts`` at its default off -- ordering alone
picks the winner, and the failure mode is filing the wrong video under the
episode's fixed outtmpl and flipping ``hasFile``.

The video-tab stage must keep honouring ``playlistreverse``: there it is
meaningful and is the documented behaviour.
"""
import os
import sqlite3
import sys
import unittest
from unittest.mock import patch

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402
from playlist_snapshot import PlaylistSnapshot  # noqa: E402

CHANNEL = 'https://www.youtube.com/@VICE'
EPISODE = {'title': "Chef's Night Out", 'seasonNumber': 1, 'episodeNumber': 1}

# A channel search for that title. YouTube ranks these by relevance, best
# first. All three pass the matching rules -- the pattern is punctuation
# tolerant and nothing here names a part -- so ordering alone decides.
RANKED = [
    ("Chef's Night Out", 'https://www.youtube.com/watch?v=RANK01'),
    ("Chef's Night Out (Remastered)", 'https://www.youtube.com/watch?v=RANK02'),
    ("Chef's Night Out - FULL EPISODE", 'https://www.youtube.com/watch?v=RANK03'),
]


class SearchStageOrderingTestCase(unittest.TestCase):
    """Drive find_episode() with extraction stubbed, recording the options."""

    def setUp(self):
        """Record the opts each stage extracts with, and serve RANKED."""
        self.client = object.__new__(stream_harvestarr.StreamHarvester)
        self.client.debug = False
        self.client.playlist_cache = stream_harvestarr.PlaylistCache()
        self.extract_calls = []

        def fake_extract(ydl_opts, playlist):
            self.extract_calls.append((playlist, dict(ydl_opts)))
            return PlaylistSnapshot(iter(RANKED))

        # patch.object restores the original *descriptor*. Saving
        # PlaylistCache._extract by attribute access instead would read the
        # staticmethod through it and hand back a plain function, and putting
        # that back would rebind it as an instance method -- which silently
        # breaks every other module in the suite that calls it.
        patcher = patch.object(stream_harvestarr.PlaylistCache, '_extract',
                               staticmethod(fake_extract))
        patcher.start()
        self.addCleanup(patcher.stop)

    def series(self, playlistreverse):
        """Build a minimal series dict for the channel under test."""
        return {'url': CHANNEL, 'playlistreverse': playlistreverse, 'channel_search': True}

    def test_search_stage_keeps_relevance_order_when_reverse_is_on(self):
        """The default playlistreverse=True must not invert search ranking."""
        match = self.client.find_episode(self.series(True), dict(EPISODE))
        self.assertEqual(match, RANKED[0][1],
                         'search stage returned a lower-ranked candidate')

    def test_search_stage_unchanged_when_reverse_is_off(self):
        """playlistreverse=False picks the same candidate, so it is not a flip."""
        match = self.client.find_episode(self.series(False), dict(EPISODE))
        self.assertEqual(match, RANKED[0][1])

    def test_search_stages_run_with_reverse_disabled(self):
        """Both channel-search stages extract with playlistreverse off."""
        self.client.find_episode(self.series(True), dict(EPISODE, title='Absent'))
        searches = [opts for url, opts in self.extract_calls if '/search' in url]
        self.assertEqual(len(searches), 2)
        for opts in searches:
            self.assertFalse(opts.get('playlistreverse'))

    def test_video_tab_stage_still_honours_playlistreverse(self):
        """The chronological tab keeps the user's ordering choice."""
        def extract(options, url):
            self.extract_calls.append((url, dict(options)))
            return PlaylistSnapshot([] if '/search' in url else RANKED)

        with patch.object(stream_harvestarr.PlaylistCache, '_extract', side_effect=extract):
            match = self.client.find_episode(self.series(True), dict(EPISODE))
        self.assertEqual(match, RANKED[-1][1])
        tabs = [opts for url, opts in self.extract_calls if '/search' not in url]
        self.assertTrue(tabs, 'no video-tab stage ran')
        self.assertTrue(tabs[-1].get('playlistreverse'))

    def test_default_uses_configured_source_order(self):
        """Existing configurations must not silently switch to relevance order."""
        for reverse, expected in ((True, RANKED[-1][1]), (False, RANKED[0][1])):
            self.extract_calls.clear()
            self.client.start_scan()
            match = self.client.find_episode(
                {'url': CHANNEL, 'playlistreverse': reverse}, dict(EPISODE))
            self.assertEqual(match, expected)
            self.assertEqual([url for url, _ in self.extract_calls], [CHANNEL])

    def test_search_snapshots_are_closed_after_each_episode(self):
        """A backlog must not retain a database or refresh key per query."""
        for _ in range(200):
            snapshot = PlaylistSnapshot(RANKED)
            connection = snapshot._connection
            with patch.object(stream_harvestarr.PlaylistCache, '_extract', return_value=snapshot):
                self.client.find_episode(self.series(True), dict(EPISODE))
            self.assertEqual(self.client.playlist_cache.entries, {})
            self.assertEqual(self.client.playlist_cache.refreshed, set())
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')

    def test_search_snapshot_is_released_when_matching_raises(self):
        """Matching failures must also release the temporary database."""
        with patch.object(stream_harvestarr, 'title_matches', side_effect=RuntimeError('bad match')):
            with self.assertRaisesRegex(RuntimeError, 'bad match'):
                self.client.find_episode(self.series(True), dict(EPISODE))
        self.assertEqual(self.client.playlist_cache.entries, {})
        self.assertEqual(self.client.playlist_cache.refreshed, set())


class ChannelSearchConfigTests(unittest.TestCase):
    def test_inherited_option_is_coerced_and_series_can_disable_it(self):
        """YAML strings and native booleans must produce the same opt-in."""
        client = object.__new__(stream_harvestarr.StreamHarvester)
        client.services = {'shared': {'url': CHANNEL, 'channel_search': 'True'}}
        for value, expected in (('False', False), ('false', False), (False, False),
                                ('True', True), ('true', True), (True, True)):
            with self.subTest(value=value):
                client.series = [{'title': 'Show', 'service': 'shared', 'channel_search': value}]
                client.get_series = lambda: [{'title': 'Show', 'monitored': True}]
                self.assertIs(client.filterseries()[0]['channel_search'], expected)
        client.series = [{'title': 'Show', 'service': 'shared'}]
        self.assertTrue(client.filterseries()[0]['channel_search'])
        client.services['shared'].pop('channel_search')
        self.assertFalse(client.filterseries()[0]['channel_search'])
        self.assertIn('channel_search', stream_harvestarr.KNOWN_SERIES_KEYS)
        self.assertIn('channel_search', stream_harvestarr.KNOWN_SERVICE_KEYS)


if __name__ == '__main__':
    unittest.main()
