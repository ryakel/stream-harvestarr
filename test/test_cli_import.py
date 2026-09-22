"""Importing the application must not consume the host process's arguments."""

import os
import subprocess
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
CONFIG_PATH = os.path.abspath(os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)


class CliImportTests(unittest.TestCase):
    def test_import_ignores_unrelated_host_arguments(self):
        env = os.environ.copy()
        env['CONFIGPATH'] = CONFIG_PATH
        env['PYTHONPATH'] = os.pathsep.join(
            filter(None, (APP_DIR, env.get('PYTHONPATH')))
        )

        result = subprocess.run(
            [
                sys.executable,
                '-c',
                "import sys; sys.argv = ['host', '--unrelated-flag']; "
                "import stream_harvestarr; "
                "assert stream_harvestarr.parse_args(['--debug']).debug",
            ],
            cwd=APP_DIR,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
