"""Pure path helpers shared between the app and its unit tests.

This module is deliberately free of import-time side effects (no env-var
reads, no argument parsing) so it can be imported directly from tests --
unlike ``stream_harvestarr.py`` and ``utils.py``, which both read
``os.environ['CONFIGPATH']`` at module load and therefore can't be imported
in a bare test environment.
"""

# Default download-path prefix, preserved for backward compatibility with the
# original hardcoded ``/sonarr_root`` mount point (see issue #137).
DEFAULT_ROOT_FOLDER = '/sonarr_root'


def normalize_root_folder(raw_value):
    """Normalize a configured ``root_folder`` value.

    - An explicit empty string stays ``''`` -- meaning "use Sonarr's absolute
      path directly, with no prefix" (the TRaSH Guides same-path layout).
    - Any other value has its trailing slashes stripped so that ``/data`` and
      ``/data/`` behave identically.
    """
    return '' if raw_value == '' else raw_value.rstrip('/')
