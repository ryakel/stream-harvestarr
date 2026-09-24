"""Every option we hand yt-dlp must be one yt-dlp actually reads.

yt-dlp's Python API takes a plain dict and **ignores keys it does not
recognise, silently**. There is no warning and no error, so an option named
after the CLI flag rather than the API key simply never happens. Five of ours
were in that state for years:

    forceipv4  nocontinue  throttled_rate  concurrent_fragments
    audio_multistreams

All five are ``--force-ipv4``-style CLI spellings. None appears anywhere in
yt-dlp's source. The code read as though it forced IPv4, disabled resuming and
capped throttled downloads; none of it ran.

A test that pins the *current* names catches a revert of the fix. It does not
catch the sixth wrong name somebody adds next year, which is the actual
failure mode. So this test derives what yt-dlp accepts from the installed
yt-dlp itself and checks every key we pass against it.
"""
import inspect
import os
import re
import pathlib
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr as app  # noqa: E402
import yt_dlp  # noqa: E402
from yt_dlp.downloader.common import FileDownloader  # noqa: E402

# Documented params look like "    name: description" in the class docstrings.
# One space is enough -- sleep_interval_requests is written with exactly one,
# and requiring two silently dropped it.
_DOC_PARAM_RE = re.compile(r'^\s*([a-z_][a-z0-9_]*)\s*:\s+\S', re.MULTILINE)

# yt-dlp reads options three ways. Miss any one and real keys look dead:
# throttledratelimit only ever appears as params.get() in downloader/http.py,
# and sleep_interval_requests only as get_param() in extractor/common.py.
_PARAM_READ_RE = re.compile(
    r"""(?:params(?:\.get\(|\[)|get_param\()\s*['"]([a-z_][a-z0-9_]*)['"]"""
)

# Names yt-dlp has never accepted, used to prove the detector still bites.
# The first five are the real ones this test exists because of.
_SENTINEL_DEAD_NAMES = (
    'forceipv4',
    'nocontinue',
    'throttled_rate',
    'concurrent_fragments',
    'audio_multistreams',
    'definitely_not_a_ytdlp_option',
)

def accepted_parameters():
    """Return every option name the installed yt-dlp actually reads."""
    names = set()
    for obj in (yt_dlp.YoutubeDL, FileDownloader):
        names |= set(_DOC_PARAM_RE.findall(inspect.getdoc(obj) or ''))

    package_root = pathlib.Path(os.path.dirname(yt_dlp.__file__))
    for source_file in package_root.rglob('*.py'):
        names |= set(_PARAM_READ_RE.findall(source_file.read_text(errors='ignore')))
    return names


def make_client(**overrides):
    """Build a StreamHarvester without touching config.yml or Sonarr."""
    client = object.__new__(app.StreamHarvester)
    client.ytdl_format = 'best'
    client.ytdl_merge_output_format = 'mkv'
    client.root_folder = ''
    client.season_padding = client.episode_padding = 0
    client.sleep_requests = 0
    client.debug = False
    for name, value in overrides.items():
        setattr(client, name, value)
    return client


SERIES = {'id': 1, 'title': 'Show', 'path': '/tv/Show'}
EPISODE = {'title': 'Episode', 'seasonNumber': 1, 'episodeNumber': 1}


class DetectorSanityTests(unittest.TestCase):
    """The detector fails open, so prove it is still discriminating.

    If yt-dlp reformats its docstrings or renames its params mapping, the
    regexes above could match nothing or everything. Either way the contract
    test below would pass vacuously and we would learn nothing. These checks
    are what stop that being silent.
    """

    def setUp(self):
        self.accepted = accepted_parameters()

    def test_detector_finds_a_plausible_number_of_parameters(self):
        """A collapsed or exploded known-set means the regexes stopped working."""
        self.assertGreater(
            len(self.accepted), 100,
            'yt-dlp option detection collapsed -- the contract test below is '
            'now vacuous. Check _DOC_PARAM_RE / _PARAM_READ_RE against the '
            'installed yt-dlp.')
        self.assertLess(
            len(self.accepted), 2000,
            'yt-dlp option detection is matching far too much; the contract '
            'test below would accept almost any key.')

    def test_detector_rejects_names_ytdlp_has_never_accepted(self):
        """The five real dead options, plus one invented, must not be accepted."""
        for name in _SENTINEL_DEAD_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(
                    name, self.accepted,
                    f'{name!r} is not a yt-dlp option but the detector accepts '
                    f'it, so this suite can no longer catch dead options.')

    def test_detector_accepts_options_we_know_are_live(self):
        """Guard against the opposite failure: real keys reported as dead."""
        for name in ('format', 'outtmpl', 'quiet', 'logger', 'continuedl',
                     'throttledratelimit', 'sleep_interval_requests',
                     'extract_flat', 'match_filter', 'js_runtimes'):
            with self.subTest(name=name):
                self.assertIn(name, self.accepted)


class OptionNameContractTests(unittest.TestCase):
    """Every key the app passes must be one yt-dlp reads."""

    def setUp(self):
        self.accepted = accepted_parameters()

    def assertOptionsAccepted(self, options, origin):
        unknown = sorted(set(options) - self.accepted)
        self.assertEqual(
            unknown, [],
            f'{origin} passes {unknown} to yt-dlp, which does not read '
            f'{"them" if len(unknown) > 1 else "it"}. yt-dlp ignores unknown '
            f'keys silently, so {"these settings do" if len(unknown) > 1 else "this setting does"} '
            f'nothing. Check the Python API name -- it is usually not the CLI '
            f'flag spelling.')

    def test_download_options_across_configurations(self):
        """Cover the branches that add keys, not just the default path."""
        cases = {
            'defaults': (make_client(), dict(SERIES)),
            'debug enabled': (make_client(debug=True), dict(SERIES)),
            'sleep_requests set': (make_client(sleep_requests=5), dict(SERIES)),
            'padded naming': (
                make_client(season_padding=2, episode_padding=2), dict(SERIES)),
            # Both subtitle keys are supplied deliberately. download_options()
            # reads series['subtitles_languages'] and
            # series['subtitles_autogenerated'] with bare indexing, but
            # filterseries() only sets each when the corresponding key is in
            # the config -- so the realistic shapes (`subtitles: true`, or
            # only one sub-key) raise KeyError before reaching yt-dlp. That is
            # a separate bug; this file is about option names, so it passes
            # the shape that gets there.
            'subtitles': (make_client(), {
                **SERIES, 'subtitles': True, 'subtitles_languages': 'en',
                'subtitles_autogenerated': 'false'}),
            'subtitles autogenerated': (make_client(), {
                **SERIES, 'subtitles': True, 'subtitles_languages': 'en',
                'subtitles_autogenerated': True}),
            'cookies': (make_client(), {**SERIES, 'cookies_file': '/tmp/c.txt'}),
            'credentials': (make_client(), {
                **SERIES, 'username': 'u', 'password': 'p'}),
            'custom format': (make_client(), {**SERIES, 'format': 'bestaudio'}),
        }
        for label, (client, series) in cases.items():
            with self.subTest(case=label):
                self.assertOptionsAccepted(
                    client.download_options(series, dict(EPISODE)),
                    f'download_options() [{label}]')

    def test_search_options_across_configurations(self):
        """ytdl_eps_search_opts() has its own debug and credential branches."""
        cases = {
            'defaults': (make_client(), {}),
            'debug enabled': (make_client(debug=True), {}),
            'sleep_requests set': (make_client(sleep_requests=5), {}),
            'cookies': (make_client(), {'cookies': '/tmp/c.txt'}),
            'credentials': (make_client(), {'username': 'u', 'password': 'p'}),
        }
        for label, (client, kwargs) in cases.items():
            with self.subTest(case=label):
                for playlistreverse in (True, False):
                    self.assertOptionsAccepted(
                        client.ytdl_eps_search_opts(playlistreverse, **kwargs),
                        f'ytdl_eps_search_opts() [{label}]')


if __name__ == '__main__':
    unittest.main()
