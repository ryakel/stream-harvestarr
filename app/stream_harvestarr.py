import requests
import urllib.parse
import yt_dlp
from yt_dlp.utils import match_filter_func
import collections
import os
import sys
import re
from utils import upperescape, normalize_title, checkconfig, offsethandler, YoutubeDLLogger, ytdl_hooks, ytdl_hooks_debug, setup_logging  # NOQA
from pathutils import normalize_root_folder, DEFAULT_ROOT_FOLDER
from datetime import datetime
import schedule
import time
import logging
import argparse

# allow debug arg for verbose logging
parser = argparse.ArgumentParser(description='Process some integers.')
parser.add_argument('--debug', action='store_true', help='Enable debug logging')
args = parser.parse_args()

# setup logger
logger = setup_logging(True, True, args.debug)

date_format = "%Y-%m-%dT%H:%M:%SZ"

CONFIGFILE = os.environ['CONFIGPATH']
CONFIGPATH = CONFIGFILE.replace('config.yml', '')
SCANINTERVAL = 60

# yt-dlp needs a JavaScript runtime for YouTube extraction.  Prefer deno
# (upstream default, installed on amd64/arm64 images) and fall back to
# node (installed on every image, including 386/armv7 where deno is not
# packaged for Alpine).  See issue #96.
JS_RUNTIMES = {'deno': {'path': None}, 'node': {'path': None}}

# yt-dlp results that are a *collection* rather than one video. Three shapes
# reach ytsearch(): a resolved playlist ('playlist' / 'multi_video'), an
# unresolved reference to one (_type 'url' whose url is a playlist or channel
# page), and the top-level result for the configured url when nothing in it
# matched. None of them may be handed to download(): with a fixed outtmpl and
# nooverwrites, yt-dlp writes the collection's *first* item into the episode's
# filename, so every episode gets the same wrong video.
#
# This is not theoretical. A channel-search url
# (https://www.youtube.com/@CHANNEL/search?query=...) returns playlist entries
# interleaved with videos, and YoutubeDL._match_entry deliberately skips
# matchtitle for entries it can't confirm are a single video — so the playlist
# sitting at index 0 was never filtered and won every episode.
COLLECTION_TYPES = ('playlist', 'multi_video')
# Markers that positively identify one video. Checked first so a legitimate
# watch?v=ID&list=ID url isn't discarded along with the collections.
VIDEO_URL_RE = re.compile(
    r'(?:/watch\b|[?&]v=|/shorts/|youtu\.be/|/embed/)',
    re.IGNORECASE
)
COLLECTION_URL_RE = re.compile(
    r'(?:/playlist\b|[?&]list=|/@[^/]+/|/channel/|/user/|/c/|/results\b|/search\b)',
    re.IGNORECASE
)


def is_single_video(entry):
    """True when a yt-dlp result entry is one downloadable video."""
    if entry.get('_type') in COLLECTION_TYPES:
        return False
    if entry.get('entries') is not None:
        return False
    url = entry.get('webpage_url') or entry.get('url') or ''
    if VIDEO_URL_RE.search(url):
        return True
    return not COLLECTION_URL_RE.search(url)


def apply_site_regex(title, site_regex):
    """Rewrite a site-supplied title before it is matched.

    ``site_regex`` is a compiled (pattern, replacement) pair from the series'
    ``regex.site`` config, or None. Used to strip decoration the site adds and
    Sonarr doesn't have — "Episode 5 - Title (Extended Cut)" -> "Episode 5 -
    Title" — so the two can be compared.
    """
    if not site_regex or not title:
        return title
    pattern, replacement = site_regex
    return pattern.sub(replacement, title)


# "Part N" markers, in the shapes uploaders actually use. Deliberately broad:
# a false positive costs one episode staying missing, a false negative files a
# fragment as the whole episode.
PART_RE = re.compile(r"""
    \(\s*(?:part|pt\.?)?\s*\d+\s*(?:[/⧸]\s*\d+)?\s*\)      # (Part 1/5) (Part 1) (1/5)
  | \b(?:part|pt\.?)\s*\d+\s*(?:[/⧸]|\s+o[fr]\s+)\s*\d+    # Part 1 of 2, Pt. 1/17, "1 or 3"
  | \b\d+\s+of\s+\d+\b                                      # 1 of 4
  | \b(?:part|pt\.?)\s*\d+\b                                # Part 2
""", re.IGNORECASE | re.VERBOSE)


def has_part_marker(title):
    """True when a title advertises itself as one part of a longer whole."""
    return bool(title) and PART_RE.search(title) is not None


# The per-series rules that decide whether a candidate title is the episode.
# Bundled rather than passed as four positional arguments through four layers.
#   site_regex:  compiled (pattern, replacement) from regex.site, or None
#   require:     compiled pattern a title must contain, from regex.require
#   allow_parts: whether a "Part N" upload may satisfy this episode
MatchRules = collections.namedtuple(
    'MatchRules', ('site_regex', 'require', 'allow_parts'), defaults=(None, None, True))
DEFAULT_RULES = MatchRules()


def episode_title_matches(title, matchtitle, rules=DEFAULT_RULES):
    """True when a site title matches the episode pattern.

    The single definition of "is this the episode we want". It is used twice
    per search: by yt-dlp, wrapped in a match_filter so non-matching entries
    are culled before they are fully extracted, and again by ytsearch() on
    whatever survives.

    ``require`` and the part check both read the *raw* title, deliberately.
    A site regex often strips exactly the decoration those two rely on — the
    series name lives in the suffix that regex.site is usually there to remove.
    """
    if not title:
        # Nothing to verify against, so accept only when no rule constrains us.
        return not matchtitle and rules.require is None and rules.allow_parts
    if rules.require is not None and not rules.require.search(title):
        return False
    if not rules.allow_parts and has_part_marker(title):
        return False
    if not matchtitle:
        return True
    return re.search(
        matchtitle, apply_site_regex(title, rules.site_regex), re.IGNORECASE) is not None


def title_matches(entry, matchtitle, rules=DEFAULT_RULES):
    """Re-apply the episode rules to a result entry ourselves.

    yt-dlp is not a reliable filter here. When an entry fails the title check
    in ``process_video_result`` it is returned anyway (just not downloaded),
    and entries it can't confirm are a single video skip the check entirely.
    Both land in ``result['entries']`` looking exactly like a match.

    An entry with no title cannot be verified, so it is rejected: a missing
    episode is recoverable, a wrong one silently isn't.
    """
    return episode_title_matches(entry.get('title'), matchtitle, rules)


def make_title_filter(matchtitle, rules=DEFAULT_RULES, base_filter=None):
    """Build the match_filter callable yt-dlp culls entries with.

    This replaces yt-dlp's ``matchtitle`` option outright. Two reasons, either
    sufficient on its own:

    1. **A single null title kills the whole extraction.** ``_match_entry``
       guards with ``if 'title' in info_dict`` — key present, value possibly
       None — then hands it straight to ``re.search``. One private or deleted
       video in a playlist raises TypeError, ``ignoreerrors`` swallows it, and
       ``extract_info`` returns None for *every* entry. A 517-video playlist
       with one private member returned nothing at all, for every episode, and
       the log line ("No metadata returned") pointed at the playlist rather
       than at the one bad video.
    2. **It can't be combined with a site regex.** ``matchtitle`` tests the raw
       title, which is precisely the title ``regex.site`` exists to rewrite, so
       the entries the regex is meant to rescue get dropped before we see them.

    A match_filter runs at the same points ``matchtitle`` does — including the
    cheap pre-filter over unresolved playlist entries — so the early culling
    that keeps a large channel affordable is unchanged.
    """
    def _filter(info_dict, incomplete=False):
        if base_filter is not None:
            rejected = base_filter(info_dict, incomplete)
            if rejected is not None:
                return rejected
        title = info_dict.get('title')
        if title is None:
            # Unavailable video, or a pre-filter pass that hasn't resolved the
            # title yet. Keep it: extraction will fail on its own if it's dead,
            # and ytsearch rejects a null title before ever returning it.
            return None
        if not episode_title_matches(title, matchtitle, rules):
            return '"{}" did not match the episode'.format(title)
        return None
    return _filter


# Keys filterseries() and merge_service_config() actually read. Anything else
# in a series or service block is silently ignored by the config loader, which
# makes a typo — or an invented key — indistinguishable from a working one.
INHERITABLE_KEYS = frozenset((
    'username', 'password', 'cookies_file', 'format',
    'playlistreverse', 'offset', 'subtitles', 'regex',
))
KNOWN_SERIES_KEYS = INHERITABLE_KEYS | frozenset(('title', 'url', 'service'))
KNOWN_SERVICE_KEYS = INHERITABLE_KEYS | frozenset(('title', 'url'))
KNOWN_REGEX_KEYS = frozenset(('sonarr', 'site', 'require'))


def warn_unknown_keys(entries, known, kind):
    """Log config keys that nothing reads, so typos don't fail silently."""
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get('title', '?')
        unknown = sorted(set(entry) - known)
        if unknown:
            logger.warning(
                '{} "{}" has unrecognised config key(s): {} - these are ignored. '
                'Valid keys: {}'.format(
                    kind, name, ', '.join(unknown), ', '.join(sorted(known))
                )
            )
        regex = entry.get('regex')
        if isinstance(regex, dict):
            unknown_regex = sorted(set(regex) - KNOWN_REGEX_KEYS)
            if unknown_regex:
                logger.warning(
                    '{} "{}" has unrecognised regex key(s): {} - these are ignored. '
                    'Valid keys: sonarr, site'.format(kind, name, ', '.join(unknown_regex))
                )


def compile_site_regex(match, replace, series_title):
    """Compile a series' regex.site pair, or None if it is unusable."""
    if match is None:
        return None
    try:
        return (re.compile(match), replace if replace is not None else '')
    except re.error as e:
        logger.warning(
            'Series "{}" has an invalid regex.site match pattern ({}) - ignoring'.format(
                series_title, e
            )
        )
        return None


def compile_require(pattern, series_title):
    """Compile a series' regex.require pattern, or None if unusable.

    A candidate title must contain this to be considered. It exists because an
    episode title is often just a person's name, and a channel that carries
    more than one show will have that person in another show too: Sonarr's
    "Max Schaaf" matched "From Vert Legend to Chopper Icon: Max Schaaf | Let
    It Kill You", a different series on the same channel. Requiring the show
    name in the upload title scopes the search to the right series.
    """
    if pattern is None:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        logger.warning(
            'Series "{}" has an invalid regex.require pattern ({}) - ignoring'.format(
                series_title, e
            )
        )
        return None


class StreamHarvester(object):

    def __init__(self):
        """Set up app with config file settings"""
        cfg = checkconfig()
        # Set config key for backwards compatibility in config.yml
        config_key = 'sonarrytdl' if 'sonarrytdl' in cfg else 'streamharvestarr'
        self.config_section = cfg[config_key]

        # Stream Harvestarr Setup
        try:
            self.set_scan_interval(self.config_section['scan_interval'])
            try:
                self.debug = self.config_section['debug'] in ['true', 'True']
                if self.debug:
                    logger.setLevel(logging.DEBUG)
                    for logs in logger.handlers:
                        if logs.name == 'FileHandler':
                            logs.setLevel(logging.DEBUG)
                        if logs.name == 'StreamHandler':
                            logs.setLevel(logging.DEBUG)
                    logger.debug('DEBUGGING ENABLED')
            except AttributeError:
                self.debug = False
            # Rate limiting configuration
            try:
                self.download_delay = int(self.config_section.get('download_delay', 0))
                if self.download_delay > 0:
                    logger.info('Download delay set to {} seconds between downloads'.format(self.download_delay))
            except (AttributeError, ValueError):
                self.download_delay = 0
            try:
                self.sleep_requests = int(self.config_section.get('sleep_requests', 0))
                if self.sleep_requests > 0:
                    logger.info('Sleep requests set to {} seconds between API requests'.format(self.sleep_requests))
            except (AttributeError, ValueError):
                self.sleep_requests = 0
            try:
                self.rate_limit_sleep = int(self.config_section.get('rate_limit_sleep', 900))
                logger.debug('Rate limit sleep set to {} seconds'.format(self.rate_limit_sleep))
            except (AttributeError, ValueError):
                self.rate_limit_sleep = 900
            # Exponential backoff configuration
            try:
                self.backoff_enabled = self.config_section.get('exponential_backoff', True) in ['true', 'True', True]
                if self.backoff_enabled:
                    logger.info('Exponential backoff enabled for rate limiting')
            except (AttributeError, ValueError):
                self.backoff_enabled = True
            try:
                self.backoff_multiplier = float(self.config_section.get('backoff_multiplier', 2.0))
                logger.debug('Backoff multiplier set to {}'.format(self.backoff_multiplier))
            except (AttributeError, ValueError):
                self.backoff_multiplier = 2.0
            try:
                self.backoff_max = int(self.config_section.get('backoff_max', 3600))
                logger.debug('Max backoff set to {} seconds'.format(self.backoff_max))
            except (AttributeError, ValueError):
                self.backoff_max = 3600
            # Exponential backoff state tracking
            self.rate_limit_count = 0
            self.current_backoff = self.rate_limit_sleep
        except Exception:
            sys.exit("Error with streamharvestarr config.yml values.")

        # Sonarr Setup
        try:
            api = "api"
            scheme = "http"
            basedir = ""
            if cfg['sonarr'].get('version', '').lower() == 'v4':
                api = "api/v3"
                logger.debug('Sonarr api set to v4')
            if cfg['sonarr']['ssl'].lower() == 'true':
                scheme = "https"
            if cfg['sonarr'].get('basedir', ''):
                basedir = '/' + cfg['sonarr'].get('basedir', '')

            self.base_url = "{0}://{1}:{2}{3}".format(
                scheme,
                cfg['sonarr']['host'],
                str(cfg['sonarr']['port']),
                basedir
            )
            self.sonarr_api_version = api
            self.api_key = cfg['sonarr']['apikey']
            # Handle root_folder: default to /sonarr_root for backward compat,
            # but allow empty string (no prefix) or custom path. Normalization
            # lives in pathutils.normalize_root_folder so it can be unit-tested.
            raw = cfg['sonarr'].get('root_folder', DEFAULT_ROOT_FOLDER)
            self.root_folder = normalize_root_folder(raw)
        except Exception as e:
            sys.exit(f"Error with sonarr config.yml values: {e}")

        # YTDL Setup
        try:
            self.ytdl_format = cfg['ytdl']['default_format']
        except Exception as e:
            sys.exit(f"Error with ytdl config.yml values: {e}")

        # Series Setup
        try:
            self.series = cfg["series"]
            warn_unknown_keys(self.series, KNOWN_SERIES_KEYS, 'Series')
        except Exception as e:
            sys.exit(f"Error with series config.yml values: {e}")

        # Services setup - optional, provides base config for series to inherit from
        try:
            self.services = {}
            warn_unknown_keys(cfg.get('services', []), KNOWN_SERVICE_KEYS, 'Service')
            for svc in cfg.get('services', []):
                self.services[svc['title']] = svc
            if self.services:
                logger.info('Loaded {} service(s): {}'.format(
                    len(self.services), ', '.join(self.services.keys())
                ))
        except Exception:
            self.services = {}
            logger.warning('Error loading services config, continuing without services')

        # Merge output format
        try:
            self.ytdl_merge_output_format = cfg["ytdl"]["merge_output_format"]
        except Exception:
            sys.exit("Error with ytdl config.yml values.")

        # Sonarr's naming config controls zero-padding (e.g. Season {season:00}).
        # Read it once at startup so downloaded paths match the user's media layout.
        # Format strings themselves are not logged: CodeQL flags any value derived
        # from a Sonarr API response as a potential credential leak (the request
        # carries apikey=), and the format string isn't worth a per-line suppression.
        try:
            naming = self.get_naming_config()
            season_folder_format = naming.get('seasonFolderFormat') or 'Season {season}'
            episode_format = naming.get('standardEpisodeFormat') or ''
            self.season_padding = self.parse_number_format(season_folder_format, 'season')
            self.episode_padding = self.parse_number_format(episode_format, 'episode')
        except Exception:
            logger.warning('Could not retrieve Sonarr naming config, defaulting to no padding')
            self.season_padding = 0
            self.episode_padding = 0

    def get_naming_config(self):
        """Return Sonarr naming configuration including season folder format"""
        logger.debug('Begin call Sonarr for naming config')
        res = self.request_get("{}/{}/config/naming".format(
            self.base_url,
            self.sonarr_api_version
        ))
        return res.json()

    def parse_number_format(self, format_string, token):
        """Derive zero-padding width from a Sonarr format token.

        e.g. parse_number_format('S{season:00}E{episode:00}', 'episode') -> 2
             parse_number_format('S{season}E{episode}', 'episode') -> 0

        Capped at 10 so a malformed format string can't cause unbounded zfill.
        """
        match = re.search(r'\{{{}(?::(0+))?\}}'.format(token), format_string)
        if match and match.group(1):
            return min(len(match.group(1)), 10)
        return 0

    def format_season(self, season_number):
        if self.season_padding > 0:
            return str(season_number).zfill(self.season_padding)
        return str(season_number)

    def format_episode(self, episode_number):
        if self.episode_padding > 0:
            return str(episode_number).zfill(self.episode_padding)
        return str(episode_number)

    def get_episodes_by_series_id(self, series_id):
        """Returns all episodes for the given series"""
        logger.debug('Begin call Sonarr for all episodes for series_id: {}'.format(series_id))
        args = {'seriesId': series_id}
        res = self.request_get("{}/{}/episode".format(
            self.base_url, 
            self.sonarr_api_version
            ), args
        )
        return res.json()

    def get_episode_files_by_series_id(self, series_id):
        """Returns all episode files for the given series"""
        res = self.request_get("{}/{}/episodefile?seriesId={}".format(
            self.base_url, 
            self.sonarr_api_version,
            series_id
        ))
        return res.json()

    def get_series(self):
        """Return all series in your collection"""
        logger.debug('Begin call Sonarr for all available series')
        res = self.request_get("{}/{}/series".format(
            self.base_url, 
            self.sonarr_api_version
        ))
        return res.json()

    def get_series_by_series_id(self, series_id):
        """Return the series with the matching ID or 404 if no matching series is found"""
        logger.debug('Begin call Sonarr for specific series series_id: {}'.format(series_id))
        res = self.request_get("{}/{}/series/{}".format(
            self.base_url,
            self.sonarr_api_version,
            series_id
        ))
        return res.json()

    def request_get(self, url, params=None):
        """Wrapper on the requests.get"""
        logger.debug('Begin GET request to Sonarr API')
        args = {
            "apikey": self.api_key
        }
        if params is not None:
            logger.debug('GET request with %d additional params', len(params))
            args.update(params)
        url = "{}?{}".format(
            url,
            urllib.parse.urlencode(args)
        )
        res = requests.get(url)
        return res

    def request_put(self, url, params=None, jsondata=None):
        """Wrapper on the requests.put"""
        logger.debug('Begin PUT request to Sonarr API')
        headers = {
            'Content-Type': 'application/json',
        }
        args = (
            ('apikey', self.api_key),
        )
        if params is not None:
            args.update(params)
            logger.debug('PUT request params keys: {}'.format(list(params.keys())))
        res = requests.post(
            url,
            headers=headers,
            params=args,
            json=jsondata
        )
        return res

    def rescanseries(self, series_id):
        """Refresh series information from trakt and rescan disk"""
        logger.debug('Begin call Sonarr to rescan for series_id: {}'.format(series_id))
        data = {
            "name": "RescanSeries",
            "seriesId": int(series_id)
        }
        res = self.request_put(
            "{}/{}/command".format(self.base_url, self.sonarr_api_version),
            None, 
            data
        )
        return res.json()

    def merge_service_config(self, wnt):
        # Merge a service config into a series config entry.
        # Resolution order (highest to lowest priority):
        #   1. Series-level key (explicitly present in YAML)
        #   2. Service-level key (from the named service)
        #   3. Absent (defaults applied later in filterseries)
        # URL: if series url is not absolute, it is joined onto the service url.

        if 'service' not in wnt:
            return wnt

        service_name = wnt['service']

        if service_name not in self.services:
            logger.warning('Series "{}" references unknown service "{}" - ignoring'.format(
                wnt.get('title', '?'), service_name
            ))
            return wnt

        svc = self.services[service_name]
        logger.debug('Merging service "{}" into series "{}"'.format(service_name, wnt.get('title', '?')))

        # Copy series config so we never mutate the original YAML-parsed dict
        merged = dict(wnt)

        # Inheritable keys: series value wins if present, else fall back to
        # service. Shared with the config-key validation so the two can't drift.
        for key in sorted(INHERITABLE_KEYS):
            if key not in merged and key in svc:
                merged[key] = svc[key]
                logger.debug('  Inherited {} from service "{}"'.format(key, service_name))

        # URL resolution
        svc_url = svc.get('url', '')
        series_url = merged.get('url', '')

        if not series_url:
            # No series url at all - use service url directly
            merged['url'] = svc_url
            logger.debug('  URL inherited from service: {}'.format(svc_url))
        elif not series_url.startswith('http'):
            # Relative path - join onto service base url
            base = svc_url.rstrip('/')
            path = series_url.lstrip('/')
            merged['url'] = '{}/{}'.format(base, path)
            logger.debug('  URL joined from service: {}'.format(merged['url']))
        else:
            # Absolute URL provided — verify it shares the same domain as the service
            # to prevent credentials/cookies inherited from the service being sent to
            # a different site than intended.
            svc_domain = urllib.parse.urlparse(svc_url).netloc
            series_domain = urllib.parse.urlparse(series_url).netloc

            if svc_domain and series_domain != svc_domain:
                logger.warning(
                    '  Series "{}" uses service "{}" but URL domain "{}" does not match '
                    'service domain "{}". Credentials and cookies will NOT be inherited '
                    'to avoid sending them to an unintended site. '
                    'Use a relative URL or move credentials to the series directly.'.format(
                        wnt.get('title', '?'), service_name, series_domain, svc_domain
                    )
                )
                # Strip inherited credentials and cookies from merged config
                for cred_key in ('username', 'password', 'cookies_file'):
                    if cred_key in merged and cred_key not in wnt:
                        del merged[cred_key]
                        logger.debug('  Removed inherited {} due to domain mismatch'.format(cred_key))
            else:
                logger.debug('  Absolute URL domain matches service domain - credentials retained')

        return merged

    def filterseries(self):
        """Return all series in Sonarr that are to be downloaded by yt-dlp"""
        series = self.get_series()
        matched = []
        for ser in series[:]:
            for wnt in self.series:
                if normalize_title(wnt['title']) == normalize_title(ser['title']):
                    # Merge service config before reading any keys (series overrides service)
                    wnt = self.merge_service_config(wnt)
                    # Set default values
                    ser['subtitles'] = False
                    ser['playlistreverse'] = True
                    ser['subtitles_languages'] = ['en']
                    ser['subtitles_autogenerated'] = False
                    # Update values
                    if 'regex' in wnt:
                        regex = wnt['regex']
                        if 'sonarr' in regex:
                            ser['sonarr_regex_match'] = regex['sonarr']['match']
                            ser['sonarr_regex_replace'] = regex['sonarr']['replace']
                        if 'site' in regex:
                            ser['site_regex_match'] = regex['site']['match']
                            ser['site_regex_replace'] = regex['site']['replace']
                            # Compile once per series, not once per episode:
                            # an invalid pattern should warn a single time.
                            ser['site_regex'] = compile_site_regex(
                                regex['site']['match'],
                                regex['site'].get('replace'),
                                ser['title'],
                            )
                        if 'require' in regex:
                            ser['site_require'] = compile_require(
                                regex['require'], ser['title'])
                    if 'offset' in wnt:
                        ser['offset'] = wnt['offset']
                    if 'cookies_file' in wnt:
                        ser['cookies_file'] = wnt['cookies_file']
                    if 'username' in wnt:
                        ser['username'] = wnt['username']
                    if 'password' in wnt:
                        ser['password'] = wnt['password']
                    if 'format' in wnt:
                        ser['format'] = wnt['format']
                    if 'playlistreverse' in wnt:
                        if wnt['playlistreverse'] == 'False':
                            ser['playlistreverse'] = False
                    if 'subtitles' in wnt:
                        ser['subtitles'] = True
                        if 'languages' in wnt['subtitles']:
                            ser['subtitles_languages'] = wnt['subtitles']['languages']
                        if 'autogenerated' in wnt['subtitles']:
                            ser['subtitles_autogenerated'] = wnt['subtitles']['autogenerated']
                    ser['url'] = wnt['url']
                    matched.append(ser)
        for check in matched:
            if not check['monitored']:
                logger.warning('{0} is not currently monitored'.format(ser['title']))
        del series[:]
        return matched

    def getseriesepisodes(self, series):
        now = datetime.now()
        needed = []
        for ser in series[:]:
            episodes = self.get_episodes_by_series_id(ser['id'])
            for eps in episodes[:]:
                eps_date = now
                if "airDateUtc" in eps:
                    eps_date = datetime.strptime(eps['airDateUtc'], date_format)
                    if 'offset' in ser:
                        eps_date = offsethandler(eps_date, ser['offset'])
                if not eps['monitored']:
                    episodes.remove(eps)
                elif eps['hasFile']:
                    episodes.remove(eps)
                elif eps_date > now:
                    episodes.remove(eps)
                else:
                    if 'sonarr_regex_match' in ser:
                        match = ser['sonarr_regex_match']
                        replace = ser['sonarr_regex_replace']
                        eps['title'] = re.sub(match, replace, eps['title'])
                    needed.append(eps)
                    continue
            if len(episodes) == 0:
                logger.info('{0} no episodes needed'.format(ser['title']))
                series.remove(ser)
            else:
                logger.info('{0} missing {1} episodes'.format(
                    ser['title'],
                    len(episodes)
                ))
                for i, e in enumerate(episodes):
                    logger.info('  {0}: {1} - {2}'.format(
                        i + 1,
                        ser['title'],
                        e['title']
                    ))
        return needed

    def appendcookie(self, ytdlopts, cookies=None):
        """Checks if specified cookie file exists in config
        - ``ytdlopts``: yt-dlp options to append cookie to
        - ``cookies``: filename of cookie file to append to yt-dlp opts
        returns:
            ytdlopts
                original if problem with cookies file
                updated with cookies value if cookies file exists
        """
        if cookies is not None:
            cookie_path = os.path.abspath(CONFIGPATH + cookies)
            cookie_exists = os.path.exists(cookie_path)
            if cookie_exists is True:
                ytdlopts.update({
                    'cookiefile': cookie_path
                })
                # if self.debug is True:
                logger.debug('  Cookies file loaded successfully')
            if cookie_exists is False:
                logger.warning('  cookie files specified but doesn''t exist.')
            return ytdlopts
        else:
            return ytdlopts

    def appendcredentials(self, ytdlopts, username=None, password=None):
        """Appends username and password to yt-dlp options if both are provided
        - ``ytdlopts``: yt-dlp options to append credentials to
        - ``username``: username to authenticate with
        - ``password``: password to authenticate with
        returns:
            ytdlopts
                original if username or password are missing
                updated with username and password if both are provided
        """
        if username is not None and password is not None:
            ytdlopts.update({
                'username': username,
                'password': password,
            })
            logger.debug('  Credentials loaded successfully')
        elif username is not None or password is not None:
            logger.warning('  username or password specified but both are required - skipping credentials')
        return ytdlopts

    def customformat(self, ytdlopts, customformat=None):
        """Checks if specified cookie file exists in config
        - ``ytdlopts``: yt-dlp options to change the ytdl format for
        - ``customformat``: format to download
        returns:
            ytdlopts
                original: if no custom format
                updated: with new format value if customformat exists
        """
        if customformat is not None:
            ytdlopts.update({
                'format': customformat
            })
            return ytdlopts
        else:
            return ytdlopts

    def ytdl_eps_search_opts(self, regextitle, playlistreverse, cookies=None, username=None,
                             password=None, rules=DEFAULT_RULES):
        # Exclude YouTube Shorts. match_filter takes a callable, negation
        # goes between the key and the operator, and the '?' keeps entries
        # whose url is absent (merged formats have no top-level url).
        shorts_filter = match_filter_func('url !*=? /shorts/')
        ytdlopts = {
            'ignoreerrors': True,
            'playlistreverse': playlistreverse,
            'quiet': True,
            # Search for the episode without resolving anything. Two effects,
            # both large:
            #
            #  - Nested collections are not walked. A channel-search result
            #    carries the channel's playlists alongside its videos, and
            #    yt-dlp recurses into every one of them: on the VICE search
            #    that is 13 playlists, the largest 1773 items, walked again
            #    for *every* episode. is_single_video() already refuses to
            #    return one, so resolving them only ever cost requests.
            #  - Candidates are matched on their flat title instead of being
            #    fully extracted first.
            #
            # Nothing downstream needs a resolved entry: a flat one carries
            # the title to match on and the canonical watch url, and
            # download() re-extracts that url anyway (see issue #114).
            'extract_flat': 'in_playlist',
            # The title check lives in the match_filter, never in yt-dlp's
            # 'matchtitle' option. See make_title_filter for why.
            'match_filter': make_title_filter(regextitle, rules, shorts_filter),
            'js_runtimes': JS_RUNTIMES,
        }
        if self.debug is True:
            ytdlopts.update({
                'quiet': False,
                'logger': YoutubeDLLogger(),
                'progress_hooks': [ytdl_hooks],
            })
        ytdlopts = self.appendcookie(ytdlopts, cookies)
        ytdlopts = self.appendcredentials(ytdlopts, username, password)
        if self.debug is True:
            logger.debug('yt-dlp opts configured for episode matching')
        return ytdlopts

    def ytsearch(self, ydl_opts, playlist, matchtitle=None, rules=DEFAULT_RULES):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(
                    playlist,
                    download=False
                )
        except Exception as e:
            logger.error(e)
            return False, ''
        else:
            # ignoreerrors makes yt-dlp swallow errors and return None: a null
            # entry title trips its own matchtitle regex.
            if result is None:
                logger.error('No metadata returned for {}'.format(playlist))
                return False, ''
            # The caller passes the same pattern object it built the opts from,
            # so our check can't drift from the one yt-dlp applied. The fallback
            # covers callers that only set it in the opts dict.
            if matchtitle is None:
                matchtitle = ydl_opts.get('matchtitle')
            entries = result.get('entries')
            candidates = list(entries) if entries else [result]
            for entry in candidates:
                if entry is None:
                    continue
                if not is_single_video(entry):
                    logger.debug('  Skipping collection result: {}'.format(
                        entry.get('title') or entry.get('url')
                    ))
                    continue
                if not title_matches(entry, matchtitle, rules):
                    logger.debug('  Skipping title mismatch: {}'.format(entry.get('title')))
                    continue
                # Prefer webpage_url over url: yt-dlp's YouTube extractor only
                # sets url when format selection picks a single non-merge
                # format. HLS videos (most modern YouTube uploads) trigger
                # ffmpeg audio+video merge — the "merged format" dict
                # (YoutubeDL._merge) has requested_formats but no top-level
                # url, so info_dict.update gives us an entry with
                # .get('url') == None even though extraction succeeded.
                # webpage_url is always set by the YouTube extractor directly;
                # the .get('url') fallback covers other extractors that only
                # populate url. See issue #114. Since the search runs flat
                # (extract_flat), that fallback is now the normal path: a flat
                # entry has no webpage_url, and its url is the canonical watch
                # url rather than a media stream.
                video_url = entry.get('webpage_url') or entry.get('url')
                if not video_url or video_url == playlist:
                    continue
                logger.debug('  Matched "{}"'.format(entry.get('title')))
                return True, video_url
            logger.debug('  No single video matched in {} result(s)'.format(len(candidates)))
            return False, ''

    def download(self, series, episodes):
        if len(series) != 0:
            logger.info("Processing Wanted Downloads")
            for s, ser in enumerate(series):
                logger.info("  {}:".format(ser['title']))
                for e, eps in enumerate(episodes):
                    if ser['id'] == eps['seriesId']:
                        cookies = None
                        username = None
                        password = None
                        url = ser['url']
                        if 'cookies_file' in ser:
                            cookies = ser['cookies_file']
                        if 'username' in ser:
                            username = ser['username']
                        if 'password' in ser:
                            password = ser['password']
                        # Build the pattern once and hand the same value to the
                        # search opts and to the verification inside ytsearch.
                        matchtitle = upperescape(eps['title'])
                        # An episode Sonarr models as whole is not satisfied by
                        # one "Part N" upload: taking part 1 flips hasFile and
                        # the rest is never fetched. Only an episode that names
                        # a part may match a part.
                        rules = MatchRules(
                            site_regex=ser.get('site_regex'),
                            require=ser.get('site_require'),
                            allow_parts=has_part_marker(eps['title']),
                        )
                        ydleps = self.ytdl_eps_search_opts(matchtitle, ser['playlistreverse'], cookies, username, password, rules)
                        found, dlurl = self.ytsearch(ydleps, url, matchtitle, rules)
                        if found:
                            logger.info("    {}: Found - {}:".format(e + 1, eps['title']))
                            season = self.format_season(eps['seasonNumber'])
                            episode = self.format_episode(eps['episodeNumber'])
                            ytdl_format_options = {
                                'format': self.ytdl_format,
                                'quiet': True,
                                "merge_output_format": self.ytdl_merge_output_format,
                                'outtmpl': '{0}{1}/Season {2}/{3} - S{2}E{4} - {5} WEBDL.%(ext)s'.format(
                                    self.root_folder,
                                    ser['path'],
                                    season,
                                    ser['title'],
                                    episode,
                                    eps['title']
                                ),
                                'progress_hooks': [ytdl_hooks],
                                'noplaylist': True,
                                'forceipv4': True,
                                'sleep_interval': 5,
                                'max_sleep_interval': 30,
                                'nocontinue': True,
                                'nooverwrites': True,
                                'throttled_rate': '100K',
                                'concurrent_fragments': 5,
                                'js_runtimes': JS_RUNTIMES,
                            }

                            # Add sleep_interval_requests if configured
                            if self.sleep_requests > 0:
                                ytdl_format_options['sleep_interval_requests'] = self.sleep_requests

                            ytdl_format_options = self.appendcookie(ytdl_format_options, cookies)
                            ytdl_format_options = self.appendcredentials(ytdl_format_options, username, password)

                            if 'format' in ser:
                                ytdl_format_options = self.customformat(ytdl_format_options, ser['format'])
                            if 'subtitles' in ser:
                                if ser['subtitles']:
                                    postprocessors = []
                                    postprocessors.append({
                                        'key': 'FFmpegSubtitlesConvertor',
                                        'format': 'srt',
                                    })
                                    postprocessors.append({
                                        'key': 'FFmpegEmbedSubtitle',
                                    })
                                    # filterseries() seeds this to a Python bool (False)
                                    # before optionally overriding with the user's YAML
                                    # string, so handle both shapes.
                                    autosubs_raw = ser['subtitles_autogenerated']
                                    autosubs = autosubs_raw if isinstance(autosubs_raw, bool) else autosubs_raw.lower() in ['true', 't', 'y', 'yes']
                                    ytdl_format_options.update({
                                        'writesubtitles': True,
                                        'writeautomaticsub': autosubs,
                                        'subtitleslangs': ser['subtitles_languages'],
                                        'postprocessors': postprocessors,
                                    })

                            if self.debug is True:
                                ytdl_format_options.update({
                                    'quiet': False,
                                    'logger': YoutubeDLLogger(),
                                    'progress_hooks': [ytdl_hooks_debug],
                                })
                                logger.debug('yt-dlp opts configured for downloading')
                            try:
                                with yt_dlp.YoutubeDL(ytdl_format_options) as ydl:
                                     ydl.download([dlurl])
                                self.rescanseries(ser['id'])
                                logger.info("      Downloaded - {}".format(eps['title']))
                                # Reset backoff on successful download
                                if self.rate_limit_count > 0:
                                    logger.info("      Rate limit recovered - resetting backoff counter")
                                    self.rate_limit_count = 0
                                    self.current_backoff = self.rate_limit_sleep
                                # Add delay between downloads if configured
                                if self.download_delay > 0:
                                    logger.debug("      Waiting {} seconds before next download".format(self.download_delay))
                                    time.sleep(self.download_delay)
                            except Exception as e:
                                error_msg = str(e)
                                # Check if this is a rate limit error
                                if 'rate-limited' in error_msg.lower() or 'rate limit' in error_msg.lower() or 'try again later' in error_msg.lower():
                                    self.rate_limit_count += 1

                                    # Calculate backoff with exponential increase if enabled
                                    if self.backoff_enabled and self.rate_limit_count > 1:
                                        self.current_backoff = min(
                                            int(self.rate_limit_sleep * (self.backoff_multiplier ** (self.rate_limit_count - 1))),
                                            self.backoff_max
                                        )
                                        logger.error("      Failed - entry %d - RATE LIMITED (attempt %d)", e + 1, self.rate_limit_count)
                                        logger.warning("      Exponential backoff: Sleeping for {} seconds ({}m {}s)...".format(
                                            self.current_backoff,
                                            self.current_backoff // 60,
                                            self.current_backoff % 60
                                        ))
                                    else:
                                        self.current_backoff = self.rate_limit_sleep
                                        logger.error("      Failed - entry %d - RATE LIMITED", e + 1)
                                        logger.warning("      YouTube rate limit detected. Sleeping for {} seconds...".format(self.current_backoff))

                                    time.sleep(self.current_backoff)
                                    logger.info("      Resuming downloads after rate limit cooldown")
                                else:
                                    logger.error("      Failed - entry %d - download error", e + 1)
                        else:
                            logger.info("    {}: Missing - {}:".format(e + 1, eps['title']))
        else:
            logger.info("Nothing to process")

    def set_scan_interval(self, interval):
        global SCANINTERVAL
        if interval != SCANINTERVAL:
            SCANINTERVAL = interval
            logger.info('Scan interval set to every {} minutes by config.yml'.format(interval))
        else:
            logger.info('Default scan interval of every {} minutes in use'.format(interval))
        return


def main():
    client = StreamHarvester()
    series = client.filterseries()
    episodes = client.getseriesepisodes(series)
    client.download(series, episodes)
    logger.info('Waiting...')


if __name__ == "__main__":
    if os.geteuid() == 0:
        logger.warning(
            'Container is running as root (uid 0). A future release will '
            'switch to non-root by default (uid 911, the ytdlp user already '
            'created in this image). To prepare: add "user: \'911:1000\'" to '
            'your docker-compose, or run: chown -R 911:1000 <config-path> '
            '<logs-path> on the host. See the wiki Upgrading guide for details.'
        )
    logger.info('Initial run')
    main()
    schedule.every(int(SCANINTERVAL)).minutes.do(main)
    while True:
        schedule.run_pending()
        time.sleep(1)
