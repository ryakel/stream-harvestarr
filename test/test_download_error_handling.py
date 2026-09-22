"""
Regression tests for the error paths in ``download()``.

``for e, eps in enumerate(episodes)`` uses ``e`` as the episode index in every
log line in the loop. The exception handler caught ``as e``, rebinding it to
the exception object, so the moment any download failed the handler's own
``e + 1`` raised::

    TypeError: unsupported operand type(s) for +: 'DownloadError' and 'int'

That escaped ``main()`` and killed the process, so the container restart-looped
for as long as downloads kept failing. Worse, the rate-limit branch logs
*before* it sleeps, so the exponential backoff the config carefully configures
could never run — the one situation it exists for was the one that crashed.

Same shape as issue #150: an unhandled TypeError in the scan takes the whole
container down rather than skipping one episode.
"""

import os
import sys
import unittest
from unittest.mock import Mock

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402

SERIES = [
    {
        'id': 1,
        'title': "Epicly Later'd",
        'url': 'https://www.youtube.com/@VICE/search?query=x',
        'playlistreverse': False,
        'path': "/tv/Epicly Later'd",
    }
]
EPISODES = [
    {
        'seriesId': 1,
        'title': 'Ben Kadow',
        'seasonNumber': 5,
        'episodeNumber': 8,
    }
]


class ExplodingYoutubeDL(object):
    """Stands in for yt_dlp.YoutubeDL; download() always fails."""

    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def download(self, urls):
        raise RuntimeError(self.message)


class ScriptedYoutubeDL(object):
    instances = []
    outcomes = []

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        type(self).instances.append(self)
        return self

    def __exit__(self, *exc_info):
        return False

    def download(self, urls):
        """Record the requested fake download."""
        outcome = type(self).outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome


class DownloadErrorTestCase(unittest.TestCase):
    def setUp(self):
        self._real_ydl = stream_harvestarr.yt_dlp.YoutubeDL
        self._real_sleep = stream_harvestarr.time.sleep
        self.slept = []
        stream_harvestarr.time.sleep = self.slept.append

    def tearDown(self):
        stream_harvestarr.yt_dlp.YoutubeDL = self._real_ydl
        stream_harvestarr.time.sleep = self._real_sleep

    def client(self, message):
        c = object.__new__(stream_harvestarr.StreamHarvester)
        c.debug = False
        c.ytdl_format = 'best'
        c.ytdl_merge_output_format = 'mkv'
        c.root_folder = ''
        c.season_padding = 0
        c.episode_padding = 0
        c.sleep_requests = 0
        c.download_delay = 0
        c.rate_limit_sleep = 1800
        c.rate_limit_count = 0
        c.current_backoff = 1800
        c.video_403_count = 0
        c.backoff_enabled = True
        c.backoff_multiplier = 1.5
        c.backoff_max = 5400
        c.ytsearch = lambda *a, **kw: 'https://www.youtube.com/watch?v=YrmakZiZTOE'
        c.rescanseries = lambda series_id: None
        stream_harvestarr.yt_dlp.YoutubeDL = lambda opts: ExplodingYoutubeDL(message)
        return c

    def test_generic_download_error_does_not_escape(self):
        """This used to raise TypeError out of main() and kill the process."""
        self.client('boom').download(SERIES, list(EPISODES))

    def test_sonarr_rescan_failure_does_not_undo_download(self):
        """A completed video remains successful when Sonarr is unavailable."""
        c = self.client('unused')
        c.download_video = Mock()
        c.rescanseries = Mock(
            side_effect=stream_harvestarr.requests.ConnectionError('Sonarr unavailable')
        )
        c.download_delay = 5
        c.rate_limit_count = 2
        c.video_403_count = 2
        with self.assertLogs(stream_harvestarr.logger, level='WARNING'):
            c.download(SERIES, EPISODES * 2)
        self.assertEqual(c.download_video.call_count, 2)
        self.assertEqual(c.rate_limit_count, 0)
        self.assertEqual(c.video_403_count, 0)
        self.assertEqual(self.slept, [5, 5])

    def test_malformed_sonarr_response_does_not_undo_download(self):
        c = self.client('unused')
        c.download_video = Mock()
        c.rescanseries = Mock(side_effect=ValueError('invalid JSON'))
        with self.assertLogs(stream_harvestarr.logger, level='WARNING'):
            self.assertFalse(c.download_episode(SERIES[0], EPISODES[0], 1))
        c.rescanseries.assert_called_once_with(1)

    def test_sonarr_http_failure_is_logged_without_leaking_api_key(self):
        c = self.client('unused')
        c.download_video = Mock()
        c.base_url = 'http://sonarr:8989'
        c.sonarr_api_version = 'api/v3'
        c.rescanseries = stream_harvestarr.StreamHarvester.rescanseries.__get__(c)
        response = Mock()
        response.raise_for_status.side_effect = stream_harvestarr.requests.HTTPError(
            '500 Server Error for url: http://sonarr/command?apikey=do-not-log'
        )
        c.request_put = Mock(return_value=response)
        with self.assertLogs(stream_harvestarr.logger, level='WARNING') as logs:
            self.assertFalse(c.download_episode(SERIES[0], EPISODES[0], 1))
        response.json.assert_not_called()
        self.assertNotIn('do-not-log', str(logs.output))

    def test_long_rate_limit_streak_cannot_overflow(self):
        c = self.client('HTTP Error 429: Too Many Requests')
        c.rate_limit_count = 10_000
        c.download(SERIES, list(EPISODES))
        self.assertEqual(self.slept, [c.backoff_max])

    def test_rate_limit_error_does_not_escape(self):
        self.client('HTTP Error 429: Too Many Requests').download(
            SERIES, list(EPISODES)
        )

    def test_rate_limit_actually_sleeps(self):
        """The crash happened before the sleep, so backoff never ran."""
        c = self.client('HTTP Error 429: Too Many Requests')
        c.download(SERIES, list(EPISODES))
        self.assertEqual(self.slept, [1800])
        self.assertEqual(c.rate_limit_count, 1)

    def test_unavailable_content_is_not_rate_limited(self):
        c = self.client("This content isn't available, try again later")
        c.download(SERIES, list(EPISODES))
        self.assertEqual(self.slept, [])
        self.assertEqual(c.rate_limit_count, 0)

    def test_second_rate_limit_backs_off_further(self):
        """Verify repeated rate limits increase the backoff delay."""
        c = self.client('rate-limited')
        c.download(SERIES, list(EPISODES))
        c.download(SERIES, list(EPISODES))
        self.assertEqual(self.slept, [1800, 2700])
        self.assertEqual(c.rate_limit_count, 2)

    def test_three_video_403s_stop_the_scan(self):
        """Repeated forbidden responses must not hot-loop every episode."""
        c = self.client('HTTP Error 403: Forbidden')
        attempts = []

        def fail(*args, **kwargs):
            """Fail the test if the download callback is not stopped."""
            attempts.append(1)
            raise RuntimeError('HTTP Error 403: Forbidden')

        c.download_video = fail
        episodes = [dict(EPISODES[0], episodeNumber=number) for number in range(1, 5)]
        c.download(SERIES, episodes)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(c.video_403_count, 3)

    def test_subtitle_failure_retries_without_subtitle_options(self):
        """Verify subtitle failure retries without subtitle options."""
        c = self.client('unused')
        ScriptedYoutubeDL.instances = []
        ScriptedYoutubeDL.outcomes = [
            stream_harvestarr.yt_dlp.utils.DownloadError(
                "ERROR: Unable to download video subtitles for 'en': HTTP Error 429"
            ),
            None,
        ]
        stream_harvestarr.yt_dlp.YoutubeDL = ScriptedYoutubeDL
        options = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en'],
            'postprocessors': [
                {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'},
                {'key': 'FFmpegEmbedSubtitle'},
                {'key': 'Exec'},
            ],
        }

        c.download_video('https://youtu.be/x', options, 'Episode')

        self.assertEqual(len(ScriptedYoutubeDL.instances), 2)
        fallback = ScriptedYoutubeDL.instances[1].options
        self.assertNotIn('writesubtitles', fallback)
        self.assertNotIn('writeautomaticsub', fallback)
        self.assertNotIn('subtitleslangs', fallback)
        self.assertEqual(fallback['postprocessors'], [{'key': 'Exec'}])

    def test_unrelated_subtitle_text_does_not_retry(self):
        """A title or postprocessor mentioning subtitles is not a transport failure."""
        c = self.client('unused')
        stream_harvestarr.yt_dlp.YoutubeDL = ScriptedYoutubeDL
        for message in (
            'ERROR: subtitle video is unavailable',
            'ERROR: Postprocessing: subtitle conversion failed',
        ):
            ScriptedYoutubeDL.instances = []
            ScriptedYoutubeDL.outcomes = [stream_harvestarr.yt_dlp.utils.DownloadError(message)]
            with self.assertRaises(stream_harvestarr.yt_dlp.utils.DownloadError):
                c.download_video('https://youtu.be/x', {'writesubtitles': True}, 'Episode')
            self.assertEqual(len(ScriptedYoutubeDL.instances), 1)

    def test_subtitle_retry_failure_propagates_once(self):
        """A failed fallback must not loop or suppress the video error."""
        c = self.client('unused')
        stream_harvestarr.yt_dlp.YoutubeDL = ScriptedYoutubeDL
        ScriptedYoutubeDL.instances = []
        ScriptedYoutubeDL.outcomes = [
            stream_harvestarr.yt_dlp.utils.DownloadError(
                "Unable to download video subtitles for 'en': 429"
            ),
            stream_harvestarr.yt_dlp.utils.DownloadError('HTTP Error 403: Forbidden'),
        ]
        with self.assertRaisesRegex(stream_harvestarr.yt_dlp.utils.DownloadError, '403'):
            c.download_video('https://youtu.be/x', {'writesubtitles': True}, 'Episode')
        self.assertEqual(len(ScriptedYoutubeDL.instances), 2)

    def test_subtitle_diagnostic_without_enabled_subtitles_does_not_retry(self):
        """Do not retry with unchanged options when subtitles were already off."""
        c = self.client('unused')
        stream_harvestarr.yt_dlp.YoutubeDL = ScriptedYoutubeDL
        ScriptedYoutubeDL.instances = []
        ScriptedYoutubeDL.outcomes = [
            stream_harvestarr.yt_dlp.utils.DownloadError(
                "Unable to download video subtitles for 'en': 429"
            )
        ]
        with self.assertRaises(stream_harvestarr.yt_dlp.utils.DownloadError):
            c.download_video('https://youtu.be/x', {}, 'Episode')
        self.assertEqual(len(ScriptedYoutubeDL.instances), 1)

    def test_non_forbidden_error_resets_consecutive_counter(self):
        """Only consecutive forbidden download failures stop the scan."""
        c = self.client('unused')
        for message in ('HTTP Error 403', 'other failure') * 4:
            self.assertFalse(c.handle_download_error(RuntimeError(message), 1))
        self.assertEqual(c.video_403_count, 0)

    def test_new_scan_resets_forbidden_counter(self):
        """Each scheduled scan gets three attempts, even after the last aborted."""
        c = self.client('HTTP Error 403: Forbidden')
        c.playlist_cache = stream_harvestarr.PlaylistCache()
        for _ in range(2):
            c.start_scan(SERIES)
            self.assertEqual(c.video_403_count, 0)
            c.download(SERIES, [dict(EPISODES[0], episodeNumber=n) for n in range(4)])
            self.assertEqual(c.video_403_count, 3)

    def test_backoff_is_capped(self):
        """Verify exponential backoff stops at its configured maximum."""
        c = self.client('rate limit')
        c.rate_limit_count = 40
        c.download(SERIES, list(EPISODES))
        self.assertEqual(self.slept, [c.backoff_max])

    def test_every_episode_is_attempted_after_a_failure(self):
        """One bad episode must not end the run."""
        c = self.client('boom')
        seen = []
        c.ytsearch = lambda *a, **kw: (seen.append(1), 'https://youtu.be/x')[1]
        episodes = [dict(EPISODES[0], title='One'), dict(EPISODES[0], title='Two')]
        c.download(SERIES, episodes)
        self.assertEqual(len(seen), 2)


if __name__ == '__main__':
    unittest.main()
