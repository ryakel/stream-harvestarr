import re
import os
import sys
import datetime
import yaml
import logging
from logging.handlers import RotatingFileHandler


CONFIGFILE = os.environ['CONFIGPATH']
# CONFIGPATH = CONFIGFILE.replace('config.yml', '')


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

# yaml-language-server modeline written to the top of config file so
# editors (VS Code, IntelliJ, etc.) automatically validate it against the
# published schema without any per-workspace configuration.
_SCHEMA_MODELINE = (
    "# yaml-language-server: $schema=https://raw.githubusercontent.com/"
    "ryakel/stream-harvestarr/main/app/config-schema.json"
)
_SCHEMA_GUARD = "## Do not remove the above line"
_SCHEMA_HEADER = "{}\n{}\n".format(_SCHEMA_MODELINE, _SCHEMA_GUARD)


def _has_schema_modeline(content: str) -> bool:
    """Return True if *content* already contains a yaml-language-server modeline."""
    return bool(re.search(r'#\s*yaml-language-server\s*:', content))


def ensure_schema_modeline(path: str, logger=None) -> bool:
    """Prepend the yaml-language-server schema modeline to a config file if absent.

    If any ``yaml-language-server`` comment is
    already present (including a user-supplied local ``$schema`` path) the
    file is left untouched so local overrides are respected.

    Args:
        path:   Absolute path to the ``config.yml`` (or template) file.
        logger: Optional logger instance for info/warning messages.

    Returns:
        ``True`` if the file was modified, ``False`` if it was already up-to-date
        or if an I/O error prevented modification.
    """
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            content = fh.read()
    except OSError as exc:
        if logger:
            logger.warning('Could not read {} to check schema modeline: {}'.format(path, exc))
        return False

    if _has_schema_modeline(content):
        return False  # already present — nothing to do

    try:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(_SCHEMA_HEADER + content)
        if logger:
            logger.info('Added yaml-language-server schema modeline to {}'.format(path))
        return True
    except OSError as exc:
        if logger:
            logger.warning(
                'Could not write schema modeline to {} (check file permissions): {}'.format(path, exc)
            )
        return False


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
    string = string.replace('\\ AND\\ ','\\ (AND|&)\\ ')
    # Make punctuation optional for human error
    string = string.replace("'","([']?)") # optional apostrophe
    string = string.replace(",","([,]?)") # optional comma
    string = string.replace("!","([!]?)") # optional question mark
    string = string.replace("\\.","([\\.]?)") # optional period
    string = string.replace("\\?","([\\?]?)") # optional question mark
    string = string.replace(":","([:]?)") # optional colon
    string = re.sub("S\\\\", "([']?)"+"S\\\\", string) # optional belonging apostrophe (has to be last due to question mark)
    return string


def checkconfig():
    """Checks if config files exist in config path.

    If no config.yml is present, copies the template into place and exits so
    the user can fill it in. If a config.yml *is* present, ensures it carries
    a ``yaml-language-server`` modeline at the top so editors validate it
    against the published schema automatically.

    Returns:
        ``cfg``: dict containing configuration values
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
            # Ensure the template itself carries the modeline so users see it
            # immediately when they open it to create their config.yml.
            ensure_schema_modeline(config_template, logger)
        logger.critical("Create a config.yml using config.yml.template as an example.")
        sys.exit()
    else:
        logger.info('Configuration Found. Loading file.')
        # Ensure the modeline is present before parsing — a missing modeline is
        # harmless to YAML loading, so we can safely write it first.  If the
        # line is already there (or the user has their own local $schema
        # override) the file is left unchanged.
        ensure_schema_modeline(config_file, logger)
        with open(config_file, "r") as ymlfile:
            cfg = yaml.load(
                ymlfile,
                Loader=yaml.BaseLoader
            )
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
    airdate = airdate + datetime.timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes)
    return airdate


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
        # setup logfile
        log_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs'))
        log_file = os.path.abspath(log_file + '/stream_harvestarr.log')
        loggerfile = RotatingFileHandler(
            log_file,
            maxBytes=5000000,
            backupCount=5
        )
        loggerfile.setLevel(log_level)
        loggerfile.set_name('FileHandler')
        loggerfile.setFormatter(log_format)
        logger.addHandler(loggerfile)

    if lc_enabled:
        # setup console log
        loggerconsole = logging.StreamHandler()
        loggerconsole.setLevel(log_level)
        loggerconsole.set_name('StreamHandler')
        loggerconsole.setFormatter(log_format)
        logger.addHandler(loggerconsole)

    return logger