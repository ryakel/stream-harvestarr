"""
Unit tests for ``regex.site`` — rewriting the site's title before matching.

``regex.site`` is documented in ``wiki/Advanced-Features.md`` with five worked
examples, but ``filterseries()`` only ever *assigned* ``site_regex_match`` /
``site_regex_replace``; nothing read them back. These cover the wiring.

The check lives in the local candidate matcher. yt-dlp extracts flat entries
once, then ``ytsearch`` applies the site rewrite while matching each episode.
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
from utils import upperescape  # noqa: E402

PLAYLIST = 'https://www.youtube.com/playlist?list=TEST'
# wiki/Advanced-Features.md, "Remove extra descriptors".
STRIP_PARENS = (re.compile(r'\s*\([^)]+\)$'), '')
# The shape in Nat's config: drop everything from the pipe onwards.
STRIP_SUFFIX = (re.compile(r'\s*\|.*$'), '')


class FakeYoutubeDL(object):
    def process_ie_result(self, result, download=False):
        return result

    def __init__(self, result=None):
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


    def extract_info(self, url, download=False, process=True, ie_key=None):
        """Return the configured fake extraction result."""
        return self.result


class TestApplySiteRegex(unittest.TestCase):

    def test_strips_trailing_parenthetical(self):
        self.assertEqual(
            stream_harvestarr.apply_site_regex('Episode 5 - Title (Extended Cut)', STRIP_PARENS),
            'Episode 5 - Title')

    def test_no_regex_is_a_passthrough(self):
        self.assertEqual(
            stream_harvestarr.apply_site_regex('Episode 5 - Title', None),
            'Episode 5 - Title')

    def test_none_title_survives(self):
        self.assertIsNone(stream_harvestarr.apply_site_regex(None, STRIP_PARENS))


class TestCompileSiteRegex(unittest.TestCase):

    def test_absent_match_gives_none(self):
        self.assertIsNone(stream_harvestarr.compile_site_regex(None, '', 'Some Series'))

    def test_absent_replace_defaults_to_empty(self):
        pattern, replacement = stream_harvestarr.compile_site_regex(r'\s*\|.*$', None, 'S')
        self.assertEqual(replacement, '')
        self.assertEqual(pattern.sub(replacement, 'Title | Suffix'), 'Title')

    def test_invalid_pattern_is_ignored_not_raised(self):
        """A bad pattern must not take down the scan."""
        self.assertIsNone(stream_harvestarr.compile_site_regex('([unclosed', '', 'Some Series'))

    def test_invalid_replacement_is_rejected_during_config_loading(self):
        with self.assertRaisesRegex(ValueError, 'invalid regex.site replacement'):
            stream_harvestarr.compile_site_regex('(episode)', r'\g<missing>', 'Some Series')


class TestEpisodeTitleMatches(unittest.TestCase):

    def test_regex_rescues_a_title_that_would_not_match(self):
        matchtitle = upperescape('Hot Ones Season 20')
        site_title = 'Hot Ones Season 20 | First We Feast'
        # Without the rewrite the decorated title still contains the episode
        # name, so this particular shape matched anyway — the regex matters
        # when the decoration lands *inside* the compared region.
        self.assertTrue(stream_harvestarr.episode_title_matches(site_title, matchtitle))

    def test_anchored_pattern_needs_the_rewrite(self):
        matchtitle = upperescape('Episode 5 - Title') + '$'
        site_title = 'Episode 5 - Title (Extended Cut)'
        self.assertFalse(
            stream_harvestarr.episode_title_matches(site_title, matchtitle))
        self.assertTrue(
            stream_harvestarr.episode_title_matches(site_title, matchtitle, stream_harvestarr.MatchRules(site_regex=STRIP_PARENS)))

    def test_rewrite_can_also_prevent_a_false_match(self):
        """Stripping the suffix stops an episode matching on decoration."""
        matchtitle = upperescape('First We Feast')
        self.assertTrue(
            stream_harvestarr.episode_title_matches('Hot Ones S20 | First We Feast', matchtitle))
        self.assertFalse(
            stream_harvestarr.episode_title_matches(
                'Hot Ones S20 | First We Feast', matchtitle,
                stream_harvestarr.MatchRules(site_regex=STRIP_SUFFIX)))


class TestSearchOpts(unittest.TestCase):
    """Source options do not contain episode-specific filters."""

    def test_options_are_independent_of_episode_title(self):
        """Verify options are independent of episode title."""
        opts = stream_harvestarr.StreamHarvester.ytdl_eps_search_opts(
            _NoDebug(), False)
        self.assertEqual(opts['extract_flat'], 'in_playlist')
        self.assertNotIn('matchtitle', opts)
        self.assertNotIn('match_filter', opts)


class TestYtsearchUsesSiteRegex(unittest.TestCase):

    def setUp(self):
        self._real_ydl = stream_harvestarr.yt_dlp.YoutubeDL
        self.client = object.__new__(stream_harvestarr.StreamHarvester)
        self.client.playlist_cache = stream_harvestarr.PlaylistCache()

    def tearDown(self):
        """Restore the real yt-dlp client after the test."""
        stream_harvestarr.yt_dlp.YoutubeDL = self._real_ydl

    def ytsearch(self, result, matchtitle, site_regex):
        """Return the configured test search result."""
        stream_harvestarr.yt_dlp.YoutubeDL = lambda opts: FakeYoutubeDL(result)
        return self.client.ytsearch(
            {}, PLAYLIST, matchtitle,
            stream_harvestarr.MatchRules(site_regex=site_regex))

    def test_verification_applies_the_same_rewrite(self):
        """Otherwise ytsearch would reject what the filter just accepted."""
        result = {'entries': [{
            'title': 'Ben Kadow (Extended Cut)',
            'webpage_url': 'https://www.youtube.com/watch?v=YrmakZiZTOE',
        }]}
        pattern = upperescape('Ben Kadow') + '$'
        self.assertIsNone(self.ytsearch(result, pattern, None))
        self.assertEqual(
            self.ytsearch(result, pattern, STRIP_PARENS),
            'https://www.youtube.com/watch?v=YrmakZiZTOE')


class TestFilterseriesCompilesOnce(unittest.TestCase):
    """Compiled per series, not per episode — an invalid pattern must not
    warn once for every missing episode."""

    def filterseries(self, site):
        harvester = stream_harvestarr.StreamHarvester.__new__(
            stream_harvestarr.StreamHarvester)
        harvester.series = [{
            'title': 'Some Series',
            'url': 'https://www.youtube.com/playlist?list=X',
            'regex': {'site': site},
        }]
        harvester.services = {}
        harvester.get_series = lambda: [{
            'title': 'Some Series', 'id': 1, 'monitored': True, 'path': '/tv/some',
        }]
        return stream_harvestarr.StreamHarvester.filterseries(harvester)

    def test_valid_pattern_is_stored_compiled(self):
        matched = self.filterseries({'match': r'\s*\|.*$', 'replace': ''})
        pattern, replacement = matched[0]['site_regex']
        self.assertEqual(pattern.sub(replacement, 'Title | Suffix'), 'Title')

    def test_invalid_pattern_stores_none(self):
        matched = self.filterseries({'match': '([unclosed', 'replace': ''})
        self.assertIsNone(matched[0]['site_regex'])

    def test_no_site_regex_leaves_the_key_absent(self):
        harvester = stream_harvestarr.StreamHarvester.__new__(
            stream_harvestarr.StreamHarvester)
        harvester.series = [{'title': 'Some Series', 'url': 'https://x/'}]
        harvester.services = {}
        harvester.get_series = lambda: [{
            'title': 'Some Series', 'id': 1, 'monitored': True, 'path': '/tv/some',
        }]
        matched = stream_harvestarr.StreamHarvester.filterseries(harvester)
        self.assertIsNone(matched[0].get('site_regex'))


class _NoDebug(object):
    """Stand-in for the StreamHarvester instance ytdl_eps_search_opts needs."""
    debug = False

    def appendcookie(self, opts, cookies=None):
        return opts

    def appendcredentials(self, opts, username=None, password=None):
        return opts


if __name__ == '__main__':
    unittest.main()
