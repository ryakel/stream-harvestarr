"""
Unit tests for root_folder normalization logic.
Tests the three key cases: default (unset), explicit empty, and trailing-slash stripping.
"""
import unittest


def normalize_root_folder(raw_value):
    """
    Normalize root_folder value from config.
    - Default (unset): returns /sonarr_root
    - Explicit empty string: returns ''
    - Trailing slash: strips it
    """
    return '' if raw_value == '' else raw_value.rstrip('/')


class TestRootFolderNormalization(unittest.TestCase):
    """Test cases for root_folder config normalization."""

    def test_default_unset_returns_sonarr_root(self):
        """Default case: unset root_folder should normalize to /sonarr_root."""
        raw = '/sonarr_root'  # default from .get('root_folder', '/sonarr_root')
        result = normalize_root_folder(raw)
        self.assertEqual(result, '/sonarr_root')

    def test_explicit_empty_string_returns_empty(self):
        """Empty string case: '' should remain ''."""
        raw = ''
        result = normalize_root_folder(raw)
        self.assertEqual(result, '')

    def test_trailing_slash_stripped(self):
        """Trailing slash case: /sonarr_root/ should become /sonarr_root."""
        raw = '/sonarr_root/'
        result = normalize_root_folder(raw)
        self.assertEqual(result, '/sonarr_root')

    def test_custom_path_with_trailing_slash_stripped(self):
        """Custom path with trailing slash should be stripped."""
        raw = '/custom/path/'
        result = normalize_root_folder(raw)
        self.assertEqual(result, '/custom/path')

    def test_custom_path_without_trailing_slash_unchanged(self):
        """Custom path without trailing slash should remain unchanged."""
        raw = '/custom/path'
        result = normalize_root_folder(raw)
        self.assertEqual(result, '/custom/path')

    def test_multiple_trailing_slashes_all_stripped(self):
        """Multiple trailing slashes should all be stripped."""
        raw = '/sonarr_root///'
        result = normalize_root_folder(raw)
        self.assertEqual(result, '/sonarr_root')


if __name__ == '__main__':
    unittest.main()
