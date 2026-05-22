import re
import os
import sys
import stat
import datetime
import tempfile
import yaml
import logging
from logging.handlers import RotatingFileHandler


CONFIGFILE = os.environ['CONFIGPATH']
# CONFIGPATH = CONFIGFILE.replace('config.yml', '')

# Cache file lives alongside config.yml.  Using dirname+join rather than
# str.replace avoids producing a wrong path if 'config.yml' appears as a
# directory component in CONFIGPATH.
CACHEFILE = os.path.join(os.path.dirname(os.path.abspath(CONFIGFILE)), 'cache.yml')

# Maximum number of cache entries allowed.  If the file grows beyond this
# something has gone wrong (e.g. a bug generating synthetic titles) and we
# should refuse to load it rather than consuming unbounded memory.
_CACHE_MAX_ENTRIES = 1000

# Substrings (case-insensitive) that mark a dict key as holding a secret.
# Note on username: not a secret on its own, but it pairs with password in
# yt-dlp opts and we'd rather not leak the pair when users share debug logs.
SENSITIVE_KEY_SUBSTRINGS = (
    'apikey', 'api_key', 'cookie', 'cookies', 'cookiefile', 'cookies_file',
    'password', 'passwd', 'token', 'secret', 'credential', 'auth',
    'username',
)

# Pre-compiled patterns for redacting secrets that appear inside strings
# (URLs, JSON-ish blobs). Keep these narrow on purpose — any pattern
# broad enough to chew on legitimate log content is worse than no
# redaction at all, because users stop trusting the redacted output.
_APIKEY_QUERY_RE = re.compile(r'(apikey=)[^&\s]+', re.IGNORECASE)
_APIKEY_JSON_RE = re.compile(r'(api[_-]?key["\']?\s*:\s*["\']?)[^&\s,}"\']+', re.IGNORECASE)

# Expected format for resolved_at timestamps stored in the cache.
# Validated on load so a tampered value can never influence time-based logic.
_CACHE_TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S'


def redact_sensitive(data):
    """Recursively redact secrets from data so it is safe to log.

    Handles dicts (redacts values for sensitive keys), lists (recurses),
    and strings (redacts known URL/JSON apikey patterns). Other scalars
    are returned unchanged so types are preserved for ``%s`` formatting.
    """
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            key_str = str(key).lower()
            if any(s in key_str for s in SENSITIVE_KEY_SUBSTRINGS):
                redacted[key] = '***REDACTED***'
            else:
                redacted[key] = redact_sensitive(value)
        return redacted
    if isinstance(data, (list, tuple)):
        return type(data)(redact_sensitive(item) for item in data)
    if isinstance(data, str):
        data = _APIKEY_QUERY_RE.sub(r'\1***REDACTED***', data)
        data = _APIKEY_JSON_RE.sub(r'\1***REDACTED***', data)
        return data
    return data


def _normalize_quotes(string):
    """Replace common Unicode curly quote characters with their ASCII equivalents.

    Shared by normalize_title (pre-match) and upperescape (pre-regex) so the
    two paths can't drift on which curly variants they recognize.
    """
    return (string
        .replace('\u2019', "'")  # right single quotation mark
        .replace('\u2018', "'")  # left single quotation mark
        .replace('\u201c', '"')  # left double quotation mark
        .replace('\u201d', '"')  # right double quotation mark
    )


def normalize_title(title):
    """Normalize a title for equality comparison against another title.

    Standardizes curly Unicode quotes to ASCII and strips leading/trailing
    whitespace. Internal whitespace is preserved as-is. Pure: no logging,
    so callers can drive the debug story from their own context.
    """
    return _normalize_quotes(title).strip()


def upperescape(string):
    """Uppercase and Escape string. Used to help with YT-DL regex match.
    - ``string``: string to manipulate

    returns:
        ``string``: str new string
    """
    # UPPERCASE as YTDL is case insensitive for ease.
    string = string.upper()
    # Normalize Unicode curly quotes to ASCII (shared with normalize_title).
    string = _normalize_quotes(string)
    # Replace >1 space with single space
    string = re.sub(" +", " ", string)
    # Escape the characters
    string = re.escape(string)
    # Handle none to multiple spaces
    string = string.replace("\\ ", "[\\ ]*")
    # Make parenthesis optional
    string = string.replace("\\(", "([\\(]?")
    string = string.replace("\\)", "[\\)]?)?")
    # Make it look for and as whole or ampersands
    string = string.replace('\\ AND\\ ', '\\ (AND|&)\\ ')
    # Make punctuation optional for human error
    string = string.replace("'", "([']?)")       # optional apostrophe
    string = string.replace(",", "([,]?)")       # optional comma
    string = string.replace("!", "([!]?)")       # optional exclamation mark
    string = string.replace("\\.", "([\\.]?)")   # optional period
    string = string.replace("\\?", "([\\?]?)")   # optional question mark
    string = string.replace(":", "([:]?)")       # optional colon
    string = re.sub("S\\\\", "([']?)" + "S\\\\", string)  # optional belonging apostrophe (has to be last due to question mark)
    return string


def checkconfig():
    """Checks if config files exist in config path
    If no config available, will copy template to config folder and exit script

    returns:

        `cfg`: dict containing configuration values
    """
    logger = logging.getLogger('stream_harvestarr')
    config_template = os.path.abspath(CONFIGFILE + '.template')
    config_template_exists = os.path.exists(os.path.abspath(config_template))
    config_file = os.path.abspath(CONFIGFILE)
    config_file_exists = os.path.exists(os.path.abspath(config_file))
    if not config_file_exists:
        logger.critical('Configuration file not found.')
        if not config_template_exists:
            os.system('cp /app/config.yml.template ' + config_template)
        logger.critical("Create a config.yml using config.yml.template as an example.")
        sys.exit()
    else:
        logger.info('Configuration Found. Loading file.')
        with open(config_file, "r") as ymlfile:
            # BaseLoader reads everything as strings, which avoids arbitrary
            # Python object deserialisation.  Do not switch to safe_load or
            # full_load here without careful review of every cfg value consumer.
            cfg = yaml.load(ymlfile, Loader=yaml.BaseLoader)
        return cfg


def offsethandler(airdate, offset):
    """Adjusts an episodes airdate
    - ``airdate``: Airdate from sonarr # (datetime)
    - ``offset``: Offset from series config.yml # (dict)

    returns:
        ``airdate``: datetime updated original airdate
    """
    weeks = 0
    days = 0
    hours = 0
    minutes = 0
    if 'weeks' in offset:
        weeks = int(offset['weeks'])
    if 'days' in offset:
        days = int(offset['days'])
    if 'hours' in offset:
        hours = int(offset['hours'])
    if 'minutes' in offset:
        minutes = int(offset['minutes'])
    airdate = airdate + datetime.timedelta(
        weeks=weeks, days=days, hours=hours, minutes=minutes
    )
    return airdate


class SeriesCache:
    """Cache mapping config series titles to Sonarr series IDs.

    By default (``persist=True``) the cache is backed by ``cache.yml``
    alongside ``config.yml``: entries survive restarts and title-based
    matching only happens once per series.

    When ``persist=False`` (set via ``streamharvestarr.caching: false``
    in ``config.yml``) the cache is memory-only.  Lookups still avoid
    redundant title matching within a single run, but nothing is read
    from or written to disk.  The cache resets on every container restart.

    Instantiate once at startup and pass into ``filterseries()``.
    Call ``save()`` once after each scan cycle — it is a no-op when
    ``persist=False``.
    """

    def __init__(self, path=None, persist=True):
        self._path = path or CACHEFILE
        self._persist = persist
        self._logger = logging.getLogger('stream_harvestarr')

        if self._persist:
            self._logger.debug('Cache: persistence enabled — backing store: %s', self._path)
            self._data = self._load()
        else:
            self._logger.info(
                'Cache: persistence disabled (caching: false in config) — '
                'running in memory-only mode; resolved IDs will not survive a restart'
            )
            self._data = {}

    def get_id(self, title):
        """Return the cached Sonarr series ID for *title*, or ``None``."""
        entry = self._data.get(title)
        if entry is None:
            return None
        return entry.get('sonarr_id')

    def set(self, title, sonarr_id):
        """Record a resolved *sonarr_id* for *title* with the current timestamp."""
        self._data[title] = {
            'sonarr_id': sonarr_id,
            'resolved_at': datetime.datetime.now().strftime(_CACHE_TIMESTAMP_FORMAT),
        }

    def evict_stale(self, live_sonarr_ids):
        """Remove entries whose Sonarr ID is no longer present in *live_sonarr_ids*.

        Call this once per scan with the full set of IDs returned by Sonarr so
        that series removed and re-added in Sonarr (which get a new ID) don't
        silently match nothing forever.

        live_sonarr_ids:
            Iterable of integer series IDs currently known to Sonarr.
        """
        live = set(live_sonarr_ids)
        stale = [
            title for title, entry in self._data.items()
            if entry.get('sonarr_id') not in live
        ]
        for title in stale:
            self._logger.warning(
                'Cache: evicting stale entry for "%s" '
                '(sonarr_id %s no longer exists) — will re-resolve via title match',
                title,
                self._data[title].get('sonarr_id'),
            )
            del self._data[title]

    def save(self):
        """Flush the cache to disk.

        No-op when ``persist=False`` — the cache is intentionally memory-only
        and nothing should be written to disk.

        When ``persist=True``: atomically writes via a temp-file + ``os.replace``
        so readers always see a complete file even if the process is killed
        mid-write.  A ``finally`` block ensures the temp file is always cleaned
        up on failure, regardless of the exception type raised.
        """
        if not self._persist:
            return

        cache_dir = os.path.dirname(self._path)
        tmp_path = None
        renamed = False
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                dir=cache_dir,
                delete=False,
                suffix='.tmp',
            ) as tf:
                tmp_path = tf.name
                # Set restrictive permissions before writing any data.
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
                yaml.dump(
                    {'series_id_cache': self._data},
                    tf,
                    default_flow_style=False,
                    allow_unicode=True,
                )
            # Atomic on POSIX — readers see old or new, never partial.
            os.replace(tmp_path, self._path)
            renamed = True
            self._logger.debug('Cache: saved %d entries to %s', len(self._data), self._path)
        except Exception as exc:
            self._logger.error('Cache: failed to save cache file: %s', exc)
        finally:
            # Clean up the temp file if it was created but the rename did
            # not complete, regardless of what exception type was raised.
            if tmp_path is not None and not renamed:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _load(self):
        """Load and validate the cache file.

        Returns a clean dict of validated entries.  Any entry that fails
        validation is dropped with a warning rather than propagated, so a
        tampered or corrupt cache degrades gracefully to title-based matching
        rather than causing a crash or exploitable state.
        """
        if not os.path.exists(self._path):
            self._logger.debug('Cache: no cache file found at %s, starting fresh', self._path)
            return {}

        try:
            with open(self._path, 'r') as f:
                # safe_load is used here (not BaseLoader) because we own the
                # cache format and need native int types for ID comparisons.
                # Do not use full_load or load(Loader=None) — those allow
                # arbitrary Python object deserialisation.
                raw = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            self._logger.error(
                'Cache: failed to parse cache file (corrupt or truncated?) — '
                'starting with empty cache. Error: %s', exc
            )
            return {}
        except OSError as exc:
            self._logger.error('Cache: failed to read cache file: %s', exc)
            return {}

        if raw is None:
            return {}

        entries = raw.get('series_id_cache', {})
        if not isinstance(entries, dict):
            self._logger.error(
                'Cache: unexpected top-level type %s — starting with empty cache',
                type(entries).__name__,
            )
            return {}

        # Guard against unbounded memory consumption from a bloated/corrupt file.
        if len(entries) > _CACHE_MAX_ENTRIES:
            self._logger.error(
                'Cache: file contains %d entries (max %d) — '
                'this is abnormal; starting with empty cache',
                len(entries),
                _CACHE_MAX_ENTRIES,
            )
            return {}

        return self._validate_entries(entries)

    def _validate_entries(self, entries):
        """Validate each entry, returning only those that pass all checks.

        Validates:
        - ``sonarr_id`` is a positive integer (guards against path-traversal
          payloads if the ID is ever interpolated into a Sonarr API URL).
        - ``resolved_at`` matches the expected timestamp format (guards against
          a tampered future timestamp being used to bypass future eviction logic).
        """
        valid = {}
        for title, entry in entries.items():
            if not isinstance(entry, dict):
                self._logger.warning('Cache: dropping malformed entry for "%s"', title)
                continue

            sonarr_id = entry.get('sonarr_id')
            if not isinstance(sonarr_id, int) or sonarr_id <= 0:
                self._logger.warning(
                    'Cache: dropping entry for "%s" — sonarr_id %r is not a positive integer',
                    title, sonarr_id,
                )
                continue

            resolved_at = entry.get('resolved_at', '')
            try:
                datetime.datetime.strptime(str(resolved_at), _CACHE_TIMESTAMP_FORMAT)
            except ValueError:
                self._logger.warning(
                    'Cache: dropping entry for "%s" — resolved_at %r does not match '
                    'expected format %s',
                    title, resolved_at, _CACHE_TIMESTAMP_FORMAT,
                )
                continue

            valid[title] = entry

        dropped = len(entries) - len(valid)
        if dropped:
            self._logger.warning('Cache: dropped %d invalid entries on load', dropped)
        else:
            self._logger.debug('Cache: loaded %d valid entries', len(valid))

        return valid


class YoutubeDLLogger(object):
    """Bridge yt-dlp's logging into our logger with secrets redacted.

    yt-dlp's verbose output can echo the full opts dict (including
    cookiefile paths and any username/password) and URLs containing
    Sonarr-style apikey query params. Route every message through
    redact_sensitive so debug logs are safe to share in bug reports.
    """

    def __init__(self):
        self.logger = logging.getLogger('stream_harvestarr')

    def info(self, msg: str) -> None:
        self.logger.info(redact_sensitive(msg))

    def debug(self, msg: str) -> None:
        self.logger.debug(redact_sensitive(msg))

    def warning(self, msg: str) -> None:
        self.logger.info(redact_sensitive(msg))

    def error(self, msg: str) -> None:
        self.logger.error(redact_sensitive(msg))


def ytdl_hooks_debug(d):
    logger = logging.getLogger('stream_harvestarr')
    if d['status'] == 'finished':
        file_tuple = os.path.split(os.path.abspath(d['filename']))
        logger.info("      Done downloading {}".format(file_tuple[1]))
    if d['status'] == 'downloading':
        progress = "      {} - {} - {}".format(d['filename'], d['_percent_str'], d['_eta_str'])
        logger.debug(progress)


def ytdl_hooks(d):
    logger = logging.getLogger('stream_harvestarr')
    if d['status'] == 'finished':
        file_tuple = os.path.split(os.path.abspath(d['filename']))
        logger.info("      Downloaded - {}".format(file_tuple[1]))


def setup_logging(lf_enabled=True, lc_enabled=True, debugging=False):
    log_level = logging.INFO
    log_level = logging.DEBUG if debugging is True else log_level
    logger = logging.getLogger('stream_harvestarr')
    logger.setLevel(log_level)
    log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    if lf_enabled:
        log_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs'))
        log_file = os.path.abspath(log_file + '/stream_harvestarr.log')
        loggerfile = RotatingFileHandler(
            log_file,
            maxBytes=5000000,
            backupCount=5,
        )
        loggerfile.setLevel(log_level)
        loggerfile.set_name('FileHandler')
        loggerfile.setFormatter(log_format)
        logger.addHandler(loggerfile)

    if lc_enabled:
        loggerconsole = logging.StreamHandler()
        loggerconsole.setLevel(log_level)
        loggerconsole.set_name('StreamHandler')
        loggerconsole.setFormatter(log_format)
        logger.addHandler(loggerconsole)

    return logger
