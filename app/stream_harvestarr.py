import requests
import urllib.parse
import yt_dlp
import os
import sys
import re
from utils import upperescape, normalize_title, checkconfig, offsethandler, YoutubeDLLogger, ytdl_hooks, ytdl_hooks_debug, setup_logging  # NOQA
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
now = datetime.now()

CONFIGFILE = os.environ['CONFIGPATH']
CONFIGPATH = CONFIGFILE.replace('config.yml', '')
SCANINTERVAL = 60

# yt-dlp needs a JavaScript runtime for YouTube extraction.  Prefer deno
# (upstream default, installed on amd64/arm64 images) and fall back to
# node (installed on every image, including 386/armv7 where deno is not
# packaged for Alpine).  See issue #96.
JS_RUNTIMES = {'deno': {'path': None}, 'node': {'path': None}}


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
        except Exception:
            sys.exit("Error with sonarr config.yml values.")
        except Exception as e:
            sys.exit("Error with sonarr config.yml values: {e}")

        # Series Setup
        try:
            self.ytdl_format = cfg['ytdl']['default_format']
        except Exception:
            sys.exit("Error with ytdl config.yml values.")
        except Exception as e:
            sys.exit(f"Error with ytdl config.yml values: {e}")

        # YTDL Setup
        try:
            self.series = cfg["series"]
        except Exception:
            sys.exit("Error with series config.yml values.")
        except Exception as e:
            sys.exit("Error with series config.yml values: {e}")

        # Merge output format
        try:
            self.ytdl_merge_output_format = cfg["ytdl"]["merge_output_format"]
        except Exception:
            sys.exit("Error with ytdl config.yml values.")

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
            "seriesId": str(series_id)
        }
        res = self.request_put(
            "{}/{}/command".format(self.base_url, self.sonarr_api_version),
            None, 
            data
        )
        return res.json()

    def filterseries(self):
        """Return all series in Sonarr that are to be downloaded by yt-dlp"""
        series = self.get_series()
        matched = []
        for ser in series[:]:
            for wnt in self.series:
                if normalize_title(wnt['title']) == normalize_title(ser['title']):
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

    def ytdl_eps_search_opts(self, regextitle, playlistreverse, cookies=None, username=None, password=None):
        ytdlopts = {
            'ignoreerrors': True,
            'playlistreverse': playlistreverse,
            'matchtitle': regextitle,
            'quiet': True,
            'match-filter': '!is_short & !url =~ /shorts/',  # Exclude YouTube Shorts
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

    def ytsearch(self, ydl_opts, playlist):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(
                    playlist,
                    download=False
                )
        except Exception as e:
            logger.error(e)
        else:
            video_url = None
            # Prefer webpage_url over url: yt-dlp's YouTube extractor only sets
            # url when format selection picks a single non-merge format. HLS
            # videos (most modern YouTube uploads) trigger ffmpeg audio+video
            # merge — the "merged format" dict (YoutubeDL._merge) has
            # requested_formats but no top-level url, so info_dict.update gives
            # us an entry with .get('url') == None even though extraction
            # succeeded. webpage_url is always set by the YouTube extractor
            # directly; the .get('url') fallback covers other extractors that
            # only populate url. See issue #114.
            if 'entries' in result and len(result['entries']) > 0:
                for entry in result['entries']:
                    if entry is None:
                        continue
                    video_url = entry.get('webpage_url') or entry.get('url')
                    if video_url:
                        break
            else:
                video_url = result.get('webpage_url') or result.get('url')
            if playlist == video_url:
                return False, ''
            if video_url is None:
                logger.error('No video_url')
                return False, ''
            else:
                return True, video_url

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
                        ydleps = self.ytdl_eps_search_opts(upperescape(eps['title']), ser['playlistreverse'], cookies, username, password)
                        found, dlurl = self.ytsearch(ydleps, url)
                        if found:
                            logger.info("    {}: Found - {}:".format(e + 1, eps['title']))
                            ytdl_format_options = {
                                'format': self.ytdl_format,
                                'quiet': True,
                                "merge_output_format": self.ytdl_merge_output_format,
                                'outtmpl': '/sonarr_root{0}/Season {1}/{2} - S{1}E{3} - {4} WEBDL.%(ext)s'.format(
                                    ser['path'],
                                    eps['seasonNumber'],
                                    ser['title'],
                                    eps['episodeNumber'],
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
                                    _autosubs = ser['subtitles_autogenerated']
                                    autosubs = _autosubs if isinstance(_autosubs, bool) else _autosubs.lower() in ['true', 't', 'y', 'yes']
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
    logger.info('Initial run')
    main()
    schedule.every(int(SCANINTERVAL)).minutes.do(main)
    while True:
        schedule.run_pending()
        time.sleep(1)
