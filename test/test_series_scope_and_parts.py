"""
Unit tests for the two rules that decide *which* match is acceptable.

Both come from the same shape of failure: an episode title that is only a
person's name matches something that isn't the episode.

``regex.require`` — a channel that carries more than one show will have the
same person in another one. Sonarr's "Max Schaaf" matched "From Vert Legend to
Chopper Icon: Max Schaaf | Let It Kill You", and "Arto Saari" matched "Death
Defying Skateboarding: The Untold Arto Saari Story | Let it Kill You" — both
a different series on the same VICE channel. Requiring the show name in the
upload title scopes the search.

Part refusal — a documentary Sonarr models as one episode is often several
uploads. Matching "Ricky Oyola" against "Epicly Later'd: Ricky Oyola (Part
1/5)" downloads a fifth of the episode and flips ``hasFile``, so the rest is
never fetched. Only an episode that names a part may match a part.

Titles are real, from the VICE channel search and the Sonarr series.
"""
import os
import re
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402
from stream_harvestarr import MatchRules, has_part_marker  # noqa: E402
from utils import upperescape  # noqa: E402

REQUIRE_SHOW = re.compile(r"epicly\s*later", re.IGNORECASE)


class TestHasPartMarker(unittest.TestCase):
    """Every part-marker shape the source channel actually uses."""

    def test_marked(self):
        for title in (
            "Epicly Later'd: Ricky Oyola (Part 1/5)",
            "Epicly Later'd: Ricky Oyola (Part 1⧸5)",
            "Epicly Later'd: Ed Templeton (Part 4)",
            "ANTHONY PAPPALARDO PART 1 of 2 | EPICLY LATER'D | VICE",
            "Skateboarder Josh Kalis 1 of 7 - Epicly Later'd - VICE",
            "Wild Ride - Pt. 10/17 - Epicly Later'd",
            "Street Skater Lizard King Goes Nuts on the Board - Part 1 or 3",
            "Eric Koston: Epicly Later'd (Part 1/6)",
        ):
            self.assertTrue(has_part_marker(title), title)

    def test_unmarked(self):
        for title in (
            "Ben Kadow: An American Original | Epicly Later’d",
            "Epicly Later'd: Chima Ferguson",
            "All Hail Cardiel: The John Cardiel Story | Epicly Later'd",
            "Jamie Foy: Two-Time Skater Of The Year And Fisherman | Epicly Later'd",
            "Skating With Brian Anderson: Epicly Later'd",
        ):
            self.assertFalse(has_part_marker(title), title)

    def test_empty(self):
        self.assertFalse(has_part_marker(''))
        self.assertFalse(has_part_marker(None))


class TestRequireScopesToTheSeries(unittest.TestCase):

    def rules(self):
        return MatchRules(require=REQUIRE_SHOW)

    def test_the_max_schaaf_case(self):
        """Its only match was a different show on the same channel."""
        self.assertTrue(stream_harvestarr.episode_title_matches(
            'From Vert Legend to Chopper Icon: Max Schaaf | Let It Kill You',
            upperescape('Max Schaaf')))
        self.assertFalse(stream_harvestarr.episode_title_matches(
            'From Vert Legend to Chopper Icon: Max Schaaf | Let It Kill You',
            upperescape('Max Schaaf'), self.rules()))

    def test_the_arto_saari_case(self):
        """Two candidates; the wrong-series one is listed first."""
        wrong = 'Death Defying Skateboarding: The Untold Arto Saari Story | Let it Kill You'
        right = "Arto Saari: Finland’s Skating Phenom | Epicly Later'd"
        pattern = upperescape('Arto Saari')
        self.assertFalse(stream_harvestarr.episode_title_matches(wrong, pattern, self.rules()))
        self.assertTrue(stream_harvestarr.episode_title_matches(right, pattern, self.rules()))

    def test_require_is_case_insensitive(self):
        self.assertTrue(stream_harvestarr.episode_title_matches(
            "STEVE RODRIGUEZ | EPICLY LATER'D | FULL LENGTH",
            upperescape('Steve Rodriguez'), self.rules()))

    def test_require_reads_the_raw_title_not_the_rewritten_one(self):
        """A site regex usually strips the suffix the show name lives in."""
        strip_suffix = (re.compile(r'\s*\|.*$'), '')
        rules = MatchRules(site_regex=strip_suffix, require=REQUIRE_SHOW)
        self.assertTrue(stream_harvestarr.episode_title_matches(
            "Ben Kadow: An American Original | Epicly Later’d",
            upperescape('Ben Kadow'), rules))

    def test_no_require_keeps_previous_behaviour(self):
        self.assertTrue(stream_harvestarr.episode_title_matches(
            'From Vert Legend to Chopper Icon: Max Schaaf | Let It Kill You',
            upperescape('Max Schaaf')))


class TestPartRefusal(unittest.TestCase):

    def test_whole_episode_refuses_a_part(self):
        """Sonarr's S03E03 is "Ricky Oyola"; the uploads are five parts."""
        self.assertFalse(stream_harvestarr.episode_title_matches(
            "Epicly Later'd: Ricky Oyola (Part 1/5)",
            upperescape('Ricky Oyola'),
            MatchRules(allow_parts=False)))

    def test_whole_episode_accepts_a_whole_upload(self):
        self.assertTrue(stream_harvestarr.episode_title_matches(
            "Epicly Later'd: Chima Ferguson",
            upperescape('Chima Ferguson'),
            MatchRules(allow_parts=False)))

    def test_part_episode_accepts_its_part(self):
        """Season-0 entries name the part, so they may match one."""
        self.assertTrue(stream_harvestarr.episode_title_matches(
            "Epicly Later'd: Ricky Oyola (Part 3/5)",
            upperescape('Ricky Oyola (Part 3/5)'),
            MatchRules(allow_parts=True)))

    def test_part_episode_still_rejects_the_wrong_part(self):
        self.assertFalse(stream_harvestarr.episode_title_matches(
            "Epicly Later'd: Ricky Oyola (Part 4/5)",
            upperescape('Ricky Oyola (Part 3/5)'),
            MatchRules(allow_parts=True)))

    def test_allow_parts_defaults_to_permissive(self):
        self.assertTrue(stream_harvestarr.episode_title_matches(
            "Epicly Later'd: Ricky Oyola (Part 1/5)", upperescape('Ricky Oyola')))


class TestRulesReachTheFilter(unittest.TestCase):
    """Both rules must cull early, not only at ytsearch verification."""

    def match_filter(self, **kw):
        client = object.__new__(stream_harvestarr.StreamHarvester)
        client.debug = False
        return client.ytdl_eps_search_opts(
            upperescape('Ricky Oyola'), False, rules=MatchRules(**kw))['match_filter']

    def test_part_is_culled_by_the_filter(self):
        f = self.match_filter(allow_parts=False)
        self.assertIsNotNone(f({'title': "Epicly Later'd: Ricky Oyola (Part 1/5)",
                                'url': 'https://youtu.be/x'}))

    def test_wrong_series_is_culled_by_the_filter(self):
        f = self.match_filter(require=REQUIRE_SHOW)
        self.assertIsNotNone(f({'title': 'Ricky Oyola | Let It Kill You',
                                'url': 'https://youtu.be/x'}))

    def test_a_good_candidate_survives_both(self):
        f = self.match_filter(require=REQUIRE_SHOW, allow_parts=False)
        self.assertIsNone(f({'title': "Epicly Later'd: Ricky Oyola",
                             'url': 'https://youtu.be/x'}))


class TestCompileRequire(unittest.TestCase):

    def test_absent_is_none(self):
        self.assertIsNone(stream_harvestarr.compile_require(None, 'S'))

    def test_invalid_pattern_is_ignored_not_raised(self):
        self.assertIsNone(stream_harvestarr.compile_require('([unclosed', 'S'))

    def test_compiles_case_insensitive(self):
        self.assertTrue(stream_harvestarr.compile_require('epicly', 'S').search('EPICLY'))


class TestFilterseriesWiring(unittest.TestCase):

    def filterseries(self, regex_block):
        harvester = stream_harvestarr.StreamHarvester.__new__(
            stream_harvestarr.StreamHarvester)
        harvester.series = [{'title': 'Some Series', 'url': 'https://x/', 'regex': regex_block}]
        harvester.services = {}
        harvester.get_series = lambda: [{
            'title': 'Some Series', 'id': 1, 'monitored': True, 'path': '/tv/some'}]
        return stream_harvestarr.StreamHarvester.filterseries(harvester)[0]

    def test_require_is_compiled_onto_the_series(self):
        ser = self.filterseries({'require': "Epicly Later"})
        self.assertTrue(ser['site_require'].search("x | Epicly Later'd"))

    def test_invalid_require_stores_none(self):
        self.assertIsNone(self.filterseries({'require': '([unclosed'})['site_require'])

    def test_absent_require_leaves_the_key_off(self):
        self.assertIsNone(self.filterseries(
            {'sonarr': {'match': 'x', 'replace': ''}}).get('site_require'))


if __name__ == '__main__':
    unittest.main()
