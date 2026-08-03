"""
Unit tests for the unrecognised-config-key warning.

Nothing validated series or service blocks, so a key nothing reads was
indistinguishable from a working one. A live config carried four
``title_regex:`` entries — a key that has never existed in this project — and
they did nothing, silently, for months. The near-miss is worse than the typo:
the feature the user wanted (``regex.site``) was real and documented, so there
was no reason to suspect the config rather than the code.
"""
import logging
import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402


class CaptureWarnings(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.messages = []

    def emit(self, record):
        if record.levelno >= logging.WARNING:
            self.messages.append(record.getMessage())


class WarnUnknownKeysTestCase(unittest.TestCase):

    def setUp(self):
        self.handler = CaptureWarnings()
        stream_harvestarr.logger.addHandler(self.handler)

    def tearDown(self):
        stream_harvestarr.logger.removeHandler(self.handler)

    def warn(self, entries, known=None, kind='Series'):
        stream_harvestarr.warn_unknown_keys(
            entries, known or stream_harvestarr.KNOWN_SERIES_KEYS, kind)
        return self.handler.messages


class TestUnknownSeriesKeys(WarnUnknownKeysTestCase):

    def test_the_real_case(self):
        msgs = self.warn([{
            'title': 'Hot Ones',
            'url': 'https://www.youtube.com/playlist?list=X',
            'cookies_file': 'c.txt',
            'title_regex': r'(?P<title>.*?)(\s*\|.*)?',
        }])
        self.assertEqual(len(msgs), 1)
        self.assertIn('title_regex', msgs[0])
        self.assertIn('Hot Ones', msgs[0])

    def test_valid_config_is_silent(self):
        self.assertEqual(self.warn([{
            'title': 'CHUMP',
            'url': 'https://www.youtube.com/playlist?list=X',
            'offset': {'days': 2},
            'regex': {'sonarr': {'match': 'x', 'replace': ''}},
            'subtitles': {'languages': ['en']},
            'service': 'YouTube Members',
        }]), [])

    def test_every_inheritable_key_is_accepted(self):
        entry = {'title': 'S', 'url': 'u'}
        entry.update({k: 'v' for k in stream_harvestarr.INHERITABLE_KEYS})
        self.assertEqual(self.warn([entry]), [])

    def test_multiple_unknown_keys_are_listed_once(self):
        msgs = self.warn([{'title': 'S', 'url': 'u', 'zzz': 1, 'aaa': 2}])
        self.assertEqual(len(msgs), 1)
        self.assertIn('aaa, zzz', msgs[0])

    def test_message_names_the_valid_keys(self):
        msgs = self.warn([{'title': 'S', 'url': 'u', 'nope': 1}])
        self.assertIn('cookies_file', msgs[0])

    def test_unknown_regex_subkey_is_caught(self):
        msgs = self.warn([{'title': 'S', 'url': 'u', 'regex': {'website': {'match': 'x'}}}])
        self.assertEqual(len(msgs), 1)
        self.assertIn('website', msgs[0])

    def test_series_without_a_title_still_warns(self):
        msgs = self.warn([{'url': 'u', 'nope': 1}])
        self.assertEqual(len(msgs), 1)

    def test_non_dict_entries_are_skipped(self):
        self.assertEqual(self.warn(['not-a-dict', None]), [])

    def test_empty_and_none_are_safe(self):
        self.assertEqual(self.warn([]), [])
        self.assertEqual(self.warn(None), [])


class TestUnknownServiceKeys(WarnUnknownKeysTestCase):

    def test_service_cannot_declare_a_service(self):
        """'service' is series-only; a service referencing one is a mistake."""
        msgs = self.warn(
            [{'title': 'YouTube Members', 'url': 'u', 'service': 'other'}],
            stream_harvestarr.KNOWN_SERVICE_KEYS, 'Service')
        self.assertEqual(len(msgs), 1)
        self.assertIn('service', msgs[0])

    def test_valid_service_is_silent(self):
        self.assertEqual(self.warn(
            [{'title': 'YouTube Members', 'url': 'u', 'cookies_file': 'c.txt'}],
            stream_harvestarr.KNOWN_SERVICE_KEYS, 'Service'), [])


class TestInheritableKeysStayInSync(unittest.TestCase):
    """merge_service_config iterates the same constant the validator uses."""

    def test_merge_uses_the_shared_constant(self):
        harvester = stream_harvestarr.StreamHarvester.__new__(
            stream_harvestarr.StreamHarvester)
        harvester.services = {'svc': {
            'title': 'svc', 'url': 'https://example.com',
            **{k: 'from-service' for k in stream_harvestarr.INHERITABLE_KEYS},
        }}
        merged = stream_harvestarr.StreamHarvester.merge_service_config(
            harvester, {'title': 'S', 'service': 'svc', 'url': '/path'})
        for key in stream_harvestarr.INHERITABLE_KEYS:
            self.assertEqual(merged.get(key), 'from-service', key)


if __name__ == '__main__':
    unittest.main()
