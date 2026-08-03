"""
Unit tests for keeping episode titles inside the filename.

The series and episode titles are interpolated into the yt-dlp *output
template*, not substituted by yt-dlp for one of its own fields. yt-dlp
sanitizes the latter; it cannot sanitize the former, because a separator the
caller baked into the template is indistinguishable from one the caller meant.

So an episode called "James Kelch (Part 1/2)" produced::

    Season 0/Epicly Later'd - S0E82 - James Kelch (Part 1/    <- a directory
    └── 2) WEBDL.mkv                                          <- the episode

30 of those appeared the moment multi-part episodes were monitored, which is
the only reason any episode title here contains a slash.
"""
import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr  # noqa: E402
from stream_harvestarr import path_safe  # noqa: E402


class TestPathSafe(unittest.TestCase):

    def test_forward_slash_is_replaced(self):
        self.assertEqual(path_safe('James Kelch (Part 1/2)'), 'James Kelch (Part 1⧸2)')

    def test_backslash_is_replaced(self):
        self.assertEqual(path_safe(r'Foo\Bar'), 'Foo⧹Bar')

    def test_no_separator_is_untouched(self):
        """Colons, apostrophes and quotes are legal and must survive."""
        for title in (
            "Eric Koston: Epicly Later'd (Part 1)",
            'Revisiting Kevin "Spanky" Long',
            'MILKY☆SUBWAY THE GALACTIC LIMITED EXPRESS',
            "Andrew Reynolds' Madness",
        ):
            self.assertEqual(path_safe(title), title)

    def test_replacement_matches_yt_dlp(self):
        """The archive yt-dlp wrote itself uses U+29F8, so match it."""
        self.assertEqual(path_safe('Ricky Oyola (Part 1/5)'), 'Ricky Oyola (Part 1⧸5)')

    def test_empty_and_none(self):
        self.assertEqual(path_safe(''), '')
        self.assertIsNone(path_safe(None))


class TestOuttmplStaysOneFile(unittest.TestCase):
    """The rendered template must have exactly the intended directory depth."""

    def render(self, series_title, episode_title):
        return '{0}{1}/Season {2}/{3} - S{2}E{4} - {5} WEBDL.%(ext)s'.format(
            '', "/data/TV/Epicly Later'd", '0',
            stream_harvestarr.path_safe(series_title), '82',
            stream_harvestarr.path_safe(episode_title))

    # /data /TV /<series> /Season 0 /<file>
    EXPECTED_DEPTH = 5

    def test_part_title_does_not_add_a_directory(self):
        out = self.render("Epicly Later'd", 'James Kelch (Part 1/2)')
        self.assertEqual(out.count('/'), self.EXPECTED_DEPTH, out)
        self.assertEqual(out.rsplit('/', 1)[1],
                         "Epicly Later'd - S0E82 - James Kelch (Part 1⧸2) WEBDL.%(ext)s")

    def test_series_title_with_a_slash_is_also_contained(self):
        out = self.render('Face/Off', 'Some Episode')
        self.assertEqual(out.count('/'), self.EXPECTED_DEPTH, out)
        self.assertEqual(out.rsplit('/', 1)[1],
                         'Face⧸Off - S0E82 - Some Episode WEBDL.%(ext)s')

    def test_ordinary_title_is_unchanged(self):
        out = self.render("Epicly Later'd", 'Ben Kadow')
        self.assertTrue(out.endswith("Epicly Later'd - S0E82 - Ben Kadow WEBDL.%(ext)s"), out)


if __name__ == '__main__':
    unittest.main()
