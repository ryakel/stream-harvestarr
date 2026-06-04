"""
Unit tests for root_folder normalization logic.

These exercise the *actual* helper used by the application
(``pathutils.normalize_root_folder``) rather than a local copy, so the test
stays bound to the shipped code path.
"""
import os
import sys
import unittest

# pathutils lives in the app/ directory alongside stream_harvestarr.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from pathutils import normalize_root_folder, DEFAULT_ROOT_FOLDER  # noqa: E402


class TestRootFolderNormalization(unittest.TestCase):
    """Test cases for root_folder config normalization."""

    def test_default_unset_returns_sonarr_root(self):
        """Default case: unset root_folder should normalize to /sonarr_root."""
        # Mirrors __init__: cfg['sonarr'].get('root_folder', DEFAULT_ROOT_FOLDER)
        result = normalize_root_folder(DEFAULT_ROOT_FOLDER)
        self.assertEqual(result, '/sonarr_root')

    def test_explicit_empty_string_returns_empty(self):
        """Empty string case: '' should remain ''."""
        result = normalize_root_folder('')
        self.assertEqual(result, '')

    def test_trailing_slash_stripped(self):
        """Trailing slash case: /sonarr_root/ should become /sonarr_root."""
        result = normalize_root_folder('/sonarr_root/')
        self.assertEqual(result, '/sonarr_root')

    def test_custom_path_with_trailing_slash_stripped(self):
        """Custom path with trailing slash should be stripped."""
        result = normalize_root_folder('/custom/path/')
        self.assertEqual(result, '/custom/path')

    def test_custom_path_without_trailing_slash_unchanged(self):
        """Custom path without trailing slash should remain unchanged."""
        result = normalize_root_folder('/custom/path')
        self.assertEqual(result, '/custom/path')

    def test_multiple_trailing_slashes_all_stripped(self):
        """Multiple trailing slashes should all be stripped."""
        result = normalize_root_folder('/sonarr_root///')
        self.assertEqual(result, '/sonarr_root')


if __name__ == '__main__':
    unittest.main()
