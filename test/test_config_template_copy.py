"""Regression tests for config template creation."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)
os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))

import utils  # noqa: E402


class ConfigTemplateCopyTests(unittest.TestCase):
    def test_config_path_with_shell_metacharacters_is_copied_as_a_path(self):
        with tempfile.TemporaryDirectory() as directory:
            config = os.path.join(directory, 'config; touch SHOULD_NOT_RUN', 'config.yml')
            with patch.object(utils, 'CONFIGFILE', config), \
                 patch.object(shutil, 'copyfile') as copyfile, \
                 patch.object(utils.os, 'system') as system:
                with self.assertRaises(SystemExit):
                    utils.checkconfig()

        copyfile.assert_called_once_with('/app/config.yml.template', config + '.template')
        system.assert_not_called()


if __name__ == '__main__':
    unittest.main()
