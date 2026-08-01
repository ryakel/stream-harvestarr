"""
Unit tests for ``upperescape()`` on multi-part episode titles.

``upperescape`` builds the regex handed to yt-dlp as ``matchtitle``, and
yt-dlp ``re.search``es it against each candidate title. Two ways that used to
go wrong for a series split into parts:

1. The parenthetical was wrapped in a group closed with ``?``, which made its
   *contents* optional, not just the brackets. "Ricky Oyola (Part 3)" reduced
   to "RICKY OYOLA" and matched all five parts — so every part downloaded
   whichever one the site happened to list first.
2. A bare "Part 1" is a prefix of "Part 10", so a series numbered into double
   digits mis-assigns the low-numbered parts.

Titles here are real, from the VICE channel search and the Sonarr series they
are matched against.
"""
import os
import re
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))

from utils import upperescape  # noqa: E402


def matches(episode_title, candidate_title):
    """Apply the pattern the way yt-dlp's matchtitle does."""
    return re.search(upperescape(episode_title), candidate_title, re.IGNORECASE) is not None


class TestParentheticalIsRequired(unittest.TestCase):

    def test_part_matches_its_own_part(self):
        self.assertTrue(matches(
            'Ricky Oyola (Part 3/5)', "Epicly Later'd: Ricky Oyola (Part 3/5)"))

    def test_part_does_not_match_a_sibling_part(self):
        for other in (1, 2, 4, 5):
            self.assertFalse(
                matches('Ricky Oyola (Part 3/5)',
                        "Epicly Later'd: Ricky Oyola (Part {}/5)".format(other)),
                'part 3 matched part {}'.format(other))

    def test_part_does_not_match_the_unnumbered_edit(self):
        """The whole parenthetical used to be optional."""
        self.assertFalse(matches(
            'Ed Templeton (Part 2)', "Epicly Later'd: Ed Templeton"))

    def test_brackets_themselves_stay_optional(self):
        """Sites drop the brackets; that much is still tolerated."""
        self.assertTrue(matches(
            'Ethan Fowler (Part 2)', "Epicly Later'd: Ethan Fowler Part 2"))

    def test_trailing_total_is_tolerated(self):
        """Sonarr says "(Part 1)", the upload says "(Part 1/5)"."""
        self.assertTrue(matches(
            'Eric Dressen (Part 1)', "Epicly Later'd: Eric Dressen (Part 1/5)"))

    def test_of_form_is_tolerated(self):
        self.assertTrue(matches(
            'Josh Kalis 1 of 7', 'Skateboarder Josh Kalis 1 of 7 - Epicly Later\'d - VICE'))


class TestNumbersAreFenced(unittest.TestCase):

    def test_part_1_does_not_match_part_10(self):
        self.assertFalse(matches(
            'Gino Iannucci - Pt. 1/10', 'Gino Iannucci - Pt. 10/10'))

    def test_part_1_still_matches_part_1(self):
        self.assertTrue(matches(
            'Gino Iannucci - Pt. 1/10', "Gino Iannucci - Pt. 1/10 - Epicly Later'd"))

    def test_part_10_matches_itself(self):
        self.assertTrue(matches(
            'Wild Ride  - Pt. 10/17', "Wild Ride - Pt. 10/17 - Epicly Later'd"))

    def test_single_digit_does_not_match_two_digit_prefix(self):
        self.assertFalse(matches('Guy Mariano Part 1', 'Guy Mariano Part 12'))


class TestUnchangedBehaviour(unittest.TestCase):
    """Titles without parts or numbers must match exactly as before."""

    def test_plain_title_matches_decorated_upload(self):
        self.assertTrue(matches(
            'Ben Kadow', 'Ben Kadow: An American Original | Epicly Later’d'))

    def test_apostrophes_stay_optional(self):
        self.assertTrue(matches(
            "Don 'Nuge' Nguyen",
            "The Skate Legend Who Escaped Death & Saved Thrasher: Don 'Nuge' Nguyen | Epicly Later'd"))

    def test_ascii_apostrophe_stays_optional(self):
        self.assertTrue(matches(
            "Tim O'Connor", "Pro Skater Tim OConnor Can Draw - Epicly Later'd - VICE"))

    def test_unrelated_title_does_not_match(self):
        self.assertFalse(matches('Ben Kadow', "Jamie Foy: Two-Time Skater | Epicly Later'd"))


class TestKnownLimitations(unittest.TestCase):
    """Pre-existing gaps, asserted so a future fix is a visible change.

    Neither affects any title in the corpus this work was validated against,
    so both are left alone rather than fixed speculatively.
    """

    def test_curly_apostrophe_in_the_site_title_does_not_match(self):
        """_normalize_quotes runs on the pattern; the candidate is untouched.

        The optional-apostrophe class is ASCII-only, so it can't skip a curly
        one on the site's side.
        """
        self.assertFalse(matches(
            "Tim O'Connor", "Pro Skater Tim O’Connor Can Draw - Epicly Later'd"))

    def test_and_ampersand_alternation_is_dead_code(self):
        r"""The '\ AND\ ' replacement never fires.

        Spaces are rewritten to '[\ ]*' on the line above it, so the literal
        it looks for is already gone by the time it runs.
        """
        self.assertFalse(matches('Gonz and Hosoi', 'Gonz & Hosoi'))


if __name__ == '__main__':
    unittest.main()
