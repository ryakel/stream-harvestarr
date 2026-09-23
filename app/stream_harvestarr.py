import argparse
import collections
import logging
import math
import os
import re
import sys
import time
import urllib.parse
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
import schedule
import yaml
import yt_dlp
from pathutils import DEFAULT_ROOT_FOLDER, normalize_root_folder
from playlists import PlaylistCache, entry_url, is_single_video, video_search_url
from utils import (
    YoutubeDLLogger,
    checkconfig,
    is_rate_limit_error,
    normalize_title,
    offsethandler,
    redact_sensitive,
    setup_logging,
    upperescape,
    ytdl_hooks,
    ytdl_hooks_debug,
)

# allow debug arg for verbose logging
parser = argparse.ArgumentParser(description='Process some integers.')
parser.add_argument('--debug', action='store_true', help='Enable debug logging')
args = parser.parse_args()

# setup logger
logger = setup_logging(True, True, args.debug)

date_format = '%Y-%m-%dT%H:%M:%SZ'

CONFIGFILE = os.environ['CONFIGPATH']
CONFIGPATH = CONFIGFILE.replace('config.yml', '')
SCANINTERVAL = 60
SONARR_TIMEOUT = (10, 60)

# yt-dlp needs a JavaScript runtime for YouTube extraction.  Prefer deno
# (upstream default, installed on amd64/arm64 images) and fall back to
# node (installed on every image, including 386/armv7 where deno is not
# packaged for Alpine).  See issue #96.
JS_RUNTIMES = {'deno': {'path': None}, 'node': {'path': None}}
CHANNEL_SEARCH_LIMIT = 20

SHORT_URL_RE = re.compile(r'/shorts/', re.IGNORECASE)


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
PART_RE = re.compile(
    r"""
    \(\s*(?:part|pt\.?)?\s*\d+\s*(?:[/⧸]\s*\d+)?\s*\)      # (Part 1/5) (Part 1) (1/5)
  | \b(?:part|pt\.?)\s*\d+\s*(?:[/⧸]|\s+o[fr]\s+)\s*\d+    # Part 1 of 2, Pt. 1/17, "1 or 3"
  | \b\d+\s+of\s+\d+\b                                      # 1 of 4
  | \b(?:part|pt\.?)\s*\d+\b                                # Part 2
""",
    re.IGNORECASE | re.VERBOSE,
)


def has_part_marker(title):
    """True when a title advertises itself as one part of a longer whole."""
    return bool(title) and PART_RE.search(title) is not None


def parts_allowed(episode_title, strict_parts):
    """Whether a "Part N" upload may satisfy this Sonarr episode.

    Opt-in, and off by default. When off, any candidate may match: part 1 of a
    split documentary satisfies an episode Sonarr models as whole, flips
    ``hasFile``, and the remaining parts are never fetched — the episode looks
    complete and is a fragment. That is the wrong behaviour, but it is the
    behaviour users' libraries were built against, so correcting it silently
    would make a third of an affected library go missing on upgrade.

    With ``strict_parts`` on, intent is read from Sonarr's own title rather
    than from more config: an episode that names a part accepts a part, an
    episode that does not, does not.
    """
    if not strict_parts:
        return True
    return has_part_marker(episode_title)


def path_safe(name):
    """Make a title safe to interpolate into an output template.

    Only path separators are touched. They are the characters that change the
    *shape* of the output rather than just the name: yt-dlp sanitizes what it
    substitutes for its own fields, but a separator we bake into the template
    ourselves is indistinguishable from one we meant, so it silently creates a
    directory. Replacements match yt-dlp's own (U+29F8 / U+29F9), so a title
    written by either route looks the same on disk.
    """
    if not name:
        return name
    return name.replace('/', '⧸').replace('\\', '⧹')


def escape_template_literal(value):
    """Escape percent signs in text interpolated into a yt-dlp template."""
    return value.replace('%', '%%') if value else value


# The per-series rules that decide whether a candidate title is the episode.
@dataclass(frozen=True)
class MatchRules:
    site_regex: tuple[re.Pattern[str], str] | None = None
    require: re.Pattern[str] | None = None
    allow_parts: bool = True


DEFAULT_RULES = MatchRules()


def episode_title_matches(title, matchtitle, rules=DEFAULT_RULES):
    """True when a site title matches the episode pattern.

    The single definition of "is this the episode we want". Flat playlist
    entries are cached once, then this matcher is applied locally for each
    missing episode.

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
    return (
        re.search(matchtitle, apply_site_regex(title, rules.site_regex), re.IGNORECASE) is not None
    )


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


# Keys filterseries() and merge_service_config() actually read. Anything else
# in a series or service block is silently ignored by the config loader, which
# makes a typo — or an invented key — indistinguishable from a working one.
INHERITABLE_KEYS = frozenset(
    (
        'username',
        'password',
        'cookies_file',
        'format',
        'playlistreverse',
        'offset',
        'subtitles',
        'regex',
        'strict_parts',
        'channel_search',
    )
)
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
                'Valid keys: {}'.format(kind, name, ', '.join(unknown), ', '.join(sorted(known)))
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


class StreamHarvester:
    def __init__(self, playlist_cache=None):
        """Set up app with config file settings"""
        cfg = checkconfig()
        # Set config key for backwards compatibility in config.yml
        config_key = 'sonarrytdl' if 'sonarrytdl' in cfg else 'streamharvestarr'
        self.config_section = cfg[config_key]

        # Stream Harvestarr Setup
        try:
            self.scan_interval = self.set_scan_interval(self.config_section['scan_interval'])
            self.debug = args.debug or self.config_section.get('debug') in ('true', 'True', True)
            level = logging.DEBUG if self.debug else logging.INFO
            logger.setLevel(level)
            for handler in logger.handlers:
                handler.setLevel(level)
            # Rate limiting configuration
            try:
                self.download_delay = int(self.config_section.get('download_delay', 0))
                if self.download_delay < 0:
                    raise ValueError('download_delay must be non-negative')
                if self.download_delay > 0:
                    logger.info(
                        'Download delay set to {} seconds between downloads'.format(
                            self.download_delay
                        )
                    )
            except (AttributeError, ValueError):
                self.download_delay = 0
            try:
                self.sleep_requests = int(self.config_section.get('sleep_requests', 0))
                if self.sleep_requests < 0:
                    raise ValueError('sleep_requests must be non-negative')
                if self.sleep_requests > 0:
                    logger.info(
                        'Sleep requests set to {} seconds between API requests'.format(
                            self.sleep_requests
                        )
                    )
            except (AttributeError, ValueError):
                self.sleep_requests = 0
            try:
                self.rate_limit_sleep = int(self.config_section.get('rate_limit_sleep', 900))
                if self.rate_limit_sleep < 0:
                    raise ValueError('rate_limit_sleep must be non-negative')
                logger.debug('Rate limit sleep set to {} seconds'.format(self.rate_limit_sleep))
            except (AttributeError, ValueError):
                self.rate_limit_sleep = 900
            # Exponential backoff configuration
            try:
                self.backoff_enabled = self.config_section.get('exponential_backoff', True) in [
                    'true',
                    'True',
                    True,
                ]
                if self.backoff_enabled:
                    logger.info('Exponential backoff enabled for rate limiting')
            except (AttributeError, ValueError):
                self.backoff_enabled = True
            try:
                self.backoff_multiplier = float(self.config_section.get('backoff_multiplier', 2.0))
                if not math.isfinite(self.backoff_multiplier) or self.backoff_multiplier <= 0:
                    raise ValueError('backoff_multiplier must be finite and positive')
                logger.debug('Backoff multiplier set to {}'.format(self.backoff_multiplier))
            except (AttributeError, ValueError):
                self.backoff_multiplier = 2.0
            try:
                self.backoff_max = int(self.config_section.get('backoff_max', 3600))
                if self.backoff_max < 0:
                    raise ValueError('backoff_max must be non-negative')
                logger.debug('Max backoff set to {} seconds'.format(self.backoff_max))
            except (AttributeError, ValueError):
                self.backoff_max = 3600
            # Exponential backoff state tracking
            self.rate_limit_count = 0
            self.current_backoff = self.rate_limit_sleep
            self.video_403_count = 0
            self.playlist_cache = playlist_cache if playlist_cache is not None else PlaylistCache()
        except Exception:
            sys.exit('Error with streamharvestarr config.yml values.')

        # Sonarr Setup
        try:
            api = 'api'
            scheme = 'http'
            basedir = ''
            if cfg['sonarr'].get('version', '').lower() == 'v4':
                api = 'api/v3'
                logger.debug('Sonarr api set to v4')
            if cfg['sonarr']['ssl'].lower() == 'true':
                scheme = 'https'
            configured_basedir = cfg['sonarr'].get('basedir', '').strip('/')
            if configured_basedir:
                basedir = '/' + configured_basedir

            self.base_url = '{0}://{1}:{2}{3}'.format(
                scheme, cfg['sonarr']['host'], str(cfg['sonarr']['port']), basedir
            )
            self.sonarr_api_version = api
            self.api_key = cfg['sonarr']['apikey']
            # Handle root_folder: default to /sonarr_root for backward compat,
            # but allow empty string (no prefix) or custom path. Normalization
            # lives in pathutils.normalize_root_folder so it can be unit-tested.
            raw = cfg['sonarr'].get('root_folder', DEFAULT_ROOT_FOLDER)
            self.root_folder = normalize_root_folder(raw)
        except Exception as e:
            sys.exit(f'Error with sonarr config.yml values: {e}')

        # YTDL Setup
        try:
            self.ytdl_format = cfg['ytdl']['default_format']
        except Exception as e:
            sys.exit(f'Error with ytdl config.yml values: {e}')

        # Series Setup
        try:
            self.series = cfg['series']
            warn_unknown_keys(self.series, KNOWN_SERIES_KEYS, 'Series')
        except Exception as e:
            sys.exit(f'Error with series config.yml values: {e}')

        # Services setup - optional, provides base config for series to inherit from
        try:
            self.services = {}
            warn_unknown_keys(cfg.get('services', []), KNOWN_SERVICE_KEYS, 'Service')
            for svc in cfg.get('services', []):
                self.services[svc['title']] = svc
            if self.services:
                logger.info(
                    'Loaded {} service(s): {}'.format(
                        len(self.services), ', '.join(self.services.keys())
                    )
                )
        except Exception:
            self.services = {}
            logger.warning('Error loading services config, continuing without services')

        # Merge output format
        try:
            self.ytdl_merge_output_format = cfg['ytdl']['merge_output_format']
        except Exception:
            sys.exit('Error with ytdl config.yml values.')

        # Sonarr's naming config controls zero-padding (e.g. Season {season:00}).
        # Refresh it with each scan so paths follow Sonarr naming changes.
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

        global SCANINTERVAL
        if self.scan_interval != SCANINTERVAL:
            SCANINTERVAL = self.scan_interval
            logger.info('Scan interval set to every %s minutes by config.yml', self.scan_interval)
        else:
            logger.info('Default scan interval of every %s minutes in use', self.scan_interval)

    def get_naming_config(self):
        """Return Sonarr naming configuration including season folder format"""
        logger.debug('Begin call Sonarr for naming config')
        res = self.request_get('{}/{}/config/naming'.format(self.base_url, self.sonarr_api_version))
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
        res = self.request_get('{}/{}/episode'.format(self.base_url, self.sonarr_api_version), args)
        return res.json()

    def get_episode_files_by_series_id(self, series_id):
        """Returns all episode files for the given series"""
        res = self.request_get(
            '{}/{}/episodefile?seriesId={}'.format(
                self.base_url, self.sonarr_api_version, series_id
            )
        )
        return res.json()

    def get_series(self):
        """Return all series in your collection"""
        logger.debug('Begin call Sonarr for all available series')
        res = self.request_get('{}/{}/series'.format(self.base_url, self.sonarr_api_version))
        return res.json()

    def get_series_by_series_id(self, series_id):
        """Return the series with the matching ID or 404 if no matching series is found"""
        logger.debug('Begin call Sonarr for specific series series_id: {}'.format(series_id))
        res = self.request_get(
            '{}/{}/series/{}'.format(self.base_url, self.sonarr_api_version, series_id)
        )
        return res.json()

    def request_get(self, url, params=None):
        """Wrapper on the requests.get"""
        logger.debug('Begin GET request to Sonarr API')
        args = {'apikey': self.api_key}
        if params is not None:
            logger.debug('GET request with %d additional params', len(params))
            args.update(params)
        url = '{}?{}'.format(url, urllib.parse.urlencode(args))
        response = requests.get(url, timeout=SONARR_TIMEOUT)
        response.raise_for_status()
        return response

    def request_put(self, url, params=None, jsondata=None):
        """Wrapper on the requests.put"""
        logger.debug('Begin PUT request to Sonarr API')
        headers = {
            'Content-Type': 'application/json',
        }
        args = (('apikey', self.api_key),)
        if params is not None:
            args.update(params)
            logger.debug('PUT request params keys: {}'.format(list(params.keys())))
        res = requests.post(
            url, headers=headers, params=args, json=jsondata, timeout=SONARR_TIMEOUT
        )
        return res

    def rescanseries(self, series_id):
        """Refresh series information from trakt and rescan disk"""
        logger.debug('Begin call Sonarr to rescan for series_id: {}'.format(series_id))
        data = {'name': 'RescanSeries', 'seriesId': int(series_id)}
        res = self.request_put(
            '{}/{}/command'.format(self.base_url, self.sonarr_api_version), None, data
        )
        res.raise_for_status()
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
            logger.warning(
                'Series "{}" references unknown service "{}" - ignoring'.format(
                    wnt.get('title', '?'), service_name
                )
            )
            return wnt

        svc = self.services[service_name]
        logger.debug(
            'Merging service "{}" into series "{}"'.format(service_name, wnt.get('title', '?'))
        )

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
                        logger.debug(
                            '  Removed inherited {} due to domain mismatch'.format(cred_key)
                        )
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
                    ser['strict_parts'] = False
                    ser['channel_search'] = wnt.get('channel_search') in ('true', 'True', True)
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
                            ser['site_require'] = compile_require(regex['require'], ser['title'])
                    if 'strict_parts' in wnt:
                        # checkconfig() parses with yaml.BaseLoader, so every
                        # scalar arrives as a string and a bare truth test would
                        # read 'False' as True — enabling the flag for exactly
                        # the users who wrote it to opt out. Coerce like debug
                        # and exponential_backoff do.
                        ser['strict_parts'] = wnt['strict_parts'] in ('true', 'True', True)
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
                        ser['playlistreverse'] = wnt['playlistreverse'] not in (
                            'false', 'False', False
                        )
                    if 'subtitles' in wnt:
                        ser['subtitles'] = True
                        if 'languages' in wnt['subtitles']:
                            ser['subtitles_languages'] = wnt['subtitles']['languages']
                        if 'autogenerated' in wnt['subtitles']:
                            ser['subtitles_autogenerated'] = wnt['subtitles']['autogenerated']
                    ser['url'] = wnt['url']
                    if not ser['monitored']:
                        logger.warning('%s is not currently monitored', ser['title'])
                    else:
                        matched.append(ser)
        del series[:]
        return matched

    def getseriesepisodes(self, series):
        """Return monitored episodes without an existing file for each series."""
        now = datetime.now(timezone.utc)
        needed = []
        active_series = []
        for ser in series:
            episodes = []
            for eps in self.get_episodes_by_series_id(ser['id']):
                if not eps['monitored'] or eps['hasFile']:
                    continue
                eps_date = now
                if eps.get('airDateUtc'):
                    eps_date = datetime.strptime(eps['airDateUtc'], date_format).replace(
                        tzinfo=timezone.utc
                    )
                    if 'offset' in ser:
                        eps_date = offsethandler(eps_date, ser['offset'])
                if eps_date > now:
                    continue
                if 'sonarr_regex_match' in ser:
                    eps = {
                        **eps,
                        'title': re.sub(
                            ser['sonarr_regex_match'], ser['sonarr_regex_replace'], eps['title']
                        ),
                    }
                episodes.append(eps)
            if not episodes:
                logger.info('%s no episodes needed', ser['title'])
                continue
            active_series.append(ser)
            needed.extend(episodes)
            logger.info('%s missing %d episodes', ser['title'], len(episodes))
            for number, episode in enumerate(episodes, start=1):
                logger.info('  %d: %s - %s', number, ser['title'], episode['title'])
        series[:] = active_series
        return needed

    def start_scan(self, series=None):
        """Prepare the playlist cache for the current series set."""
        self.video_403_count = 0
        playlists = None if series is None else {item['url'] for item in series}
        self.playlist_cache.begin_scan(playlists)

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
                ytdlopts.update({'cookiefile': cookie_path})
                # if self.debug is True:
                logger.debug('  Cookies file loaded successfully')
            if cookie_exists is False:
                logger.warning('  cookie files specified but doesnt exist.')
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
            ytdlopts.update(
                {
                    'username': username,
                    'password': password,
                }
            )
            logger.debug('  Credentials loaded successfully')
        elif username is not None or password is not None:
            logger.warning(
                '  username or password specified but both are required - skipping credentials'
            )
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
            ytdlopts.update({'format': customformat})
            return ytdlopts
        else:
            return ytdlopts

    def ytdl_eps_search_opts(self, playlistreverse, cookies=None, username=None, password=None):
        """Build yt-dlp options for local episode matching."""
        ytdlopts = {
            'ignoreerrors': True,
            'playlistreverse': playlistreverse,
            'quiet': True,
            # Search resolves only the configured source. Playlist entries stay
            # flat and are matched locally for each missing episode.
            'extract_flat': 'in_playlist',
            'js_runtimes': JS_RUNTIMES,
        }
        if self.debug is True:
            ytdlopts.update(
                {
                    'quiet': False,
                    'logger': YoutubeDLLogger(),
                    'progress_hooks': [ytdl_hooks],
                }
            )
        ytdlopts = self.appendcookie(ytdlopts, cookies)
        ytdlopts = self.appendcredentials(ytdlopts, username, password)
        if self.debug is True:
            logger.debug('yt-dlp opts configured for episode matching')
        return ytdlopts

    def ytsearch(self, ydl_opts, playlist, matchtitle=None, rules=DEFAULT_RULES):
        """Return the first candidate matching the URL and title rules."""
        if matchtitle is None:
            matchtitle = ydl_opts.get('matchtitle')
        candidates = self.playlist_cache.get(ydl_opts, playlist)
        count = 0
        for count, entry in enumerate(candidates, start=1):
            url = entry_url(entry)
            if SHORT_URL_RE.search(url or ''):
                continue
            if not is_single_video(entry):
                logger.debug('  Skipping collection result: %s', entry.get('title') or url)
                continue
            if not title_matches(entry, matchtitle, rules):
                logger.debug('  Skipping title mismatch: %s', entry.get('title'))
                continue
            if not url or url == playlist:
                continue
            logger.debug('  Matched "%s"', entry.get('title'))
            return url
        logger.debug('  No single video matched in %d result(s)', count)
        return None

    def _episode_rules(self, series, episode):
        """Build matching rules for one series episode."""
        return MatchRules(
            site_regex=series.get('site_regex'),
            require=series.get('site_require'),
            allow_parts=parts_allowed(episode['title'], series.get('strict_parts')),
        )

    def find_episode(self, series, episode):
        """Return the first matching video URL for one missing episode."""
        options = self.ytdl_eps_search_opts(
            series['playlistreverse'],
            cookies=series.get('cookies_file'),
            username=series.get('username'),
            password=series.get('password'),
        )
        matchtitle = upperescape(episode['title'])
        rules = self._episode_rules(series, episode)
        search_url = video_search_url(series['url'], episode['title'])
        if search_url and series.get('channel_search', False):
            for limit in (CHANNEL_SEARCH_LIMIT, None):
                # Relevance order is independent of chronological preference.
                search_options = {**options, 'lazy_playlist': True, 'playlistreverse': False}
                if limit is not None:
                    search_options['playlistend'] = limit
                try:
                    match = self.ytsearch(search_options, search_url, matchtitle, rules)
                    if match:
                        return match
                finally:
                    self.playlist_cache.discard(search_options, search_url)
        return self.ytsearch(options, series['url'], matchtitle, rules)

    def download_options(self, series, episode):
        """Build yt-dlp options for one video download."""
        season = self.format_season(episode['seasonNumber'])
        number = self.format_episode(episode['episodeNumber'])
        options = {
            'format': self.ytdl_format,
            'quiet': True,
            'merge_output_format': self.ytdl_merge_output_format,
            'outtmpl': ('{0}{1}/Season {2}/{3} - S{2}E{4} - {5} WEBDL.%(ext)s').format(
                escape_template_literal(self.root_folder),
                escape_template_literal(series['path']),
                season,
                escape_template_literal(path_safe(series['title'])),
                number,
                escape_template_literal(path_safe(episode['title'])),
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
            'audio_multistreams': True,
            'js_runtimes': JS_RUNTIMES,
        }
        if self.sleep_requests > 0:
            options['sleep_interval_requests'] = self.sleep_requests

        options = self.appendcookie(options, series.get('cookies_file'))
        options = self.appendcredentials(options, series.get('username'), series.get('password'))
        if 'format' in series:
            options = self.customformat(options, series['format'])
        if series.get('subtitles'):
            # Both companion keys are optional. filterseries() sets
            # subtitles=True whenever the key is present but only fills these
            # in when their sub-keys are, so `subtitles: true` and either
            # sub-key alone used to raise KeyError here -- and because this
            # call sits outside the try in download_episode(), that killed the
            # process rather than skipping the episode.
            autosubs_raw = series.get('subtitles_autogenerated', False)
            autosubs = (
                autosubs_raw
                if isinstance(autosubs_raw, bool)
                else str(autosubs_raw).lower() in ('true', 't', 'y', 'yes')
            )
            options.update(
                {
                    'writesubtitles': True,
                    'writeautomaticsub': autosubs,
                    'postprocessors': [
                        {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'},
                        {'key': 'FFmpegEmbedSubtitle'},
                    ],
                }
            )
            languages = series.get('subtitles_languages')
            if languages:
                # yt-dlp iterates this, so a bare 'en' would be read as the
                # characters 'e' and 'n', match nothing, and download no
                # subtitles at all without erroring. The template documents
                # the list form; accept the scalar people actually type.
                options['subtitleslangs'] = (
                    [languages] if isinstance(languages, str) else languages
                )
            # No languages configured: leave subtitleslangs unset rather than
            # guessing. yt-dlp then prefers 'en', falls back to any 'en*'
            # variant, and finally takes the first available language --
            # which is better than hardcoding English onto a foreign channel.
        if self.debug:
            options.update(
                {
                    'quiet': False,
                    'logger': YoutubeDLLogger(),
                    'progress_hooks': [ytdl_hooks_debug],
                }
            )
        return options

    @staticmethod
    def without_subtitles(options):
        """Remove subtitle options and postprocessors for a fallback download."""
        fallback = dict(options)
        for key in ('writesubtitles', 'writeautomaticsub', 'subtitleslangs'):
            fallback.pop(key, None)
        postprocessors = [
            processor
            for processor in fallback.get('postprocessors', [])
            if processor.get('key')
            not in {
                'FFmpegSubtitlesConvertor',
                'FFmpegEmbedSubtitle',
            }
        ]
        if postprocessors:
            fallback['postprocessors'] = postprocessors
        else:
            fallback.pop('postprocessors', None)
        return fallback

    def download_video(self, url, options, title):
        """Retry once without subtitles when their download fails."""
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadError as error:
            if self.is_rate_limit_error(error):
                raise
            # yt-dlp wraps subtitle transport errors in a plain DownloadError;
            # there is no dedicated subtitle exception type. Fail closed if
            # its diagnostic changes, or subtitle downloading was not enabled.
            message = str(error).removeprefix('ERROR: ')
            if not (
                (options.get('writesubtitles') or options.get('writeautomaticsub'))
                and message.startswith('Unable to download video subtitles for ')
            ):
                raise
            logger.warning(
                'Subtitles unavailable for %s; retrying video without subtitles',
                title,
            )
            fallback = self.without_subtitles(options)
            with yt_dlp.YoutubeDL(fallback) as ydl:
                ydl.download([url])

    @staticmethod
    def is_forbidden_error(error):
        """Return whether an error indicates an HTTP 403 response."""
        message = str(error).lower()
        return 'http error 403' in message or '403 forbidden' in message

    @staticmethod
    def is_rate_limit_error(error):
        """Return whether an error indicates rate limiting."""
        return is_rate_limit_error(error)

    def handle_download_error(self, error, episode_number):
        """Log a download error and return whether the scan should stop."""
        if self.is_forbidden_error(error):
            self.video_403_count += 1
            if self.video_403_count >= 3:
                logger.warning('Three video 403s; stopping this scan and retrying later')
                return True
        else:
            self.video_403_count = 0

        if self.is_rate_limit_error(error):
            self.rate_limit_count += 1
            self.current_backoff = min(self.rate_limit_sleep, self.backoff_max)
            if self.backoff_enabled and self.rate_limit_count > 1:
                try:
                    self.current_backoff = min(
                        int(
                            self.rate_limit_sleep
                            * (self.backoff_multiplier ** (self.rate_limit_count - 1))
                        ),
                        self.backoff_max,
                    )
                except OverflowError:
                    self.current_backoff = self.backoff_max
            logger.error(
                '      Failed - entry %d - RATE LIMITED (attempt %d)',
                episode_number,
                self.rate_limit_count,
            )
            logger.warning(
                '      Rate limit cooldown: sleeping for %s seconds', self.current_backoff
            )
            time.sleep(self.current_backoff)
            logger.info('      Resuming downloads after rate limit cooldown')
        else:
            logger.error(
                '      Failed - entry %d - download error: %s',
                episode_number,
                redact_sensitive(str(error)),
            )
        return False

    def download_episode(self, series, episode, episode_number):
        """Find and download one episode, returning whether the scan should stop."""
        try:
            url = self.find_episode(series, episode)
        except Exception as error:
            return self.handle_download_error(error, episode_number)
        if url is None:
            logger.info('    %s: Missing - %s:', episode_number, episode['title'])
            return False

        logger.info('    %s: Found - %s:', episode_number, episode['title'])
        options = self.download_options(series, episode)
        try:
            self.download_video(url, options, episode['title'])
        except Exception as error:
            return self.handle_download_error(error, episode_number)
        try:
            self.rescanseries(series['id'])
        except Exception as error:
            logger.warning(
                '      Sonarr rescan failed after download: %s',
                redact_sensitive(str(error)),
            )
        logger.info('      Downloaded - %s', episode['title'])
        self.video_403_count = 0
        if getattr(self, 'rate_limit_count', 0) > 0:
            logger.info('      Rate limit recovered - resetting backoff counter')
            self.rate_limit_count = 0
            self.current_backoff = self.rate_limit_sleep
        if getattr(self, 'download_delay', 0) > 0:
            logger.debug('      Waiting %s seconds before next download', self.download_delay)
            time.sleep(self.download_delay)
        return False

    def download(self, series, episodes):
        """Process wanted episodes grouped by series."""
        if not series:
            logger.info('Nothing to process')
            return

        episodes_by_series = collections.defaultdict(list)
        for episode in episodes:
            episodes_by_series[episode['seriesId']].append(episode)

        logger.info('Processing Wanted Downloads')
        for current_series in series:
            wanted = episodes_by_series.get(current_series['id'], [])
            if not wanted:
                continue
            logger.info('  %s:', current_series['title'])
            for number, episode in enumerate(wanted, start=1):
                if self.download_episode(current_series, episode, number):
                    return

    def set_scan_interval(self, interval):
        interval = int(interval)
        if interval <= 0:
            raise ValueError('scan_interval must be positive')
        try:
            datetime.now() + timedelta(minutes=interval)
        except OverflowError as error:
            raise ValueError('scan_interval is too large') from error
        return interval


def main(playlist_cache=None, job=None):
    """Run one scan of the configured series."""
    try:
        client = StreamHarvester(playlist_cache)
    except (SystemExit, KeyError, TypeError, ValueError, OSError, yaml.YAMLError) as error:
        if job is None:
            raise
        if isinstance(error, yaml.YAMLError):
            detail = getattr(error, 'problem', None) or 'invalid YAML'
            mark = getattr(error, 'problem_mark', None)
            if mark is not None:
                detail = f'{detail} at line {mark.line + 1}, column {mark.column + 1}'
        else:
            detail = redact_sensitive(str(error))
        logger.error(
            'Skipping scheduled scan because configuration is invalid (%s): %s',
            type(error).__name__,
            detail,
        )
        return
    if job is not None:
        job.interval = int(SCANINTERVAL)
    try:
        series = client.filterseries()
        client.start_scan(series)
        try:
            episodes = client.getseriesepisodes(series)
            client.download(series, episodes)
        finally:
            client.playlist_cache.end_scan()
    except requests.RequestException as error:
        if job is None:
            raise
        logger.warning(
            'Skipping scheduled scan because Sonarr request failed: %s',
            redact_sensitive(str(error)),
        )
        return
    except (KeyError, TypeError, ValueError, OverflowError, re.error) as error:
        if job is None:
            raise
        logger.error(
            'Skipping scheduled scan because configuration is invalid (%s): %s',
            type(error).__name__,
            redact_sensitive(str(error)),
        )
        return
    logger.info('Waiting...')


if __name__ == '__main__':
    if os.geteuid() == 0:
        logger.warning(
            'Container is running as root (uid 0). A future release will '
            'switch to non-root by default (uid 911, the ytdlp user already '
            'created in this image). To prepare: add "user: \'911:1000\'" to '
            'your docker-compose, or run: chown -R 911:1000 <config-path> '
            '<logs-path> on the host. See the wiki Upgrading guide for details.'
        )
    logger.info('Initial run')
    with closing(PlaylistCache()) as playlist_cache:
        main(playlist_cache)
        job = schedule.every(int(SCANINTERVAL)).minutes
        job.do(main, playlist_cache, job=job)
        while True:
            schedule.run_pending()
            time.sleep(1)
