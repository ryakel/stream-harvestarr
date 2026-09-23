"""Sonarr-derived text must reach the filename literally, never as a template.

``download_options()`` builds the yt-dlp ``outtmpl`` by interpolating four
values that come from Sonarr: the configured root folder, the series path, the
series title and the episode title. yt-dlp then treats the result as a format
string, so any ``%`` in those values is a directive rather than a character.

Before this was escaped (#180), a root folder of ``/mnt/%(uploader)s``
resolved to ``/mnt/NA`` and filed downloads outside the library, silently. A
series path of ``/tv/100%(title)s`` became a directory named after whatever
video was being downloaded.

#180 fixed it with three examples. This states the property instead: for every
hostile value, in every interpolated position, the text must survive verbatim,
no metadata may leak in, and the one directive we *do* intend -- ``%(ext)s`` --
must still resolve.
"""
import os
import sys
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.path.insert(0, APP_DIR)

os.environ.setdefault('CONFIGPATH', os.path.join(APP_DIR, '..', 'config', 'config.yml'))
os.makedirs(os.path.join(APP_DIR, '..', 'logs'), exist_ok=True)
sys.argv = sys.argv[:1]

import stream_harvestarr as app  # noqa: E402

# Values a real Sonarr library can contain. "100% Real" and "50%% off" are not
# contrived: percent signs show up in documentary and deal-of-the-week titles.
HOSTILE_VALUES = (
    '%(title)s',        # the #180 case: expands to the video's own title
    '%(id)s',           # expands to the video id
    '%(uploader)s',     # expands to NA when absent -- the silent-misfile case
    '%(ext)s',          # collides with the directive we actually intend
    '%(title)+05d',     # a format spec, not just a plain field
    '100% Real',        # lone percent followed by text
    '50%% off',         # already-doubled percent must not become %%%%
    'Trailing %',       # lone trailing percent
)

# Values yt-dlp would substitute if any directive were honoured. None of these
# may ever appear in a rendered filename.
METADATA = {'title': 'LEAKED_TITLE', 'id': 'LEAKED_ID',
            'uploader': 'LEAKED_UPLOADER', 'ext': 'mkv'}
LEAK_MARKERS = ('LEAKED_TITLE', 'LEAKED_ID', 'LEAKED_UPLOADER', 'NA')


def render(root_folder='', path='/tv/Show', series_title='Show',
           episode_title='Episode'):
    """Return the filename yt-dlp would write for this series and episode."""
    client = object.__new__(app.StreamHarvester)
    client.ytdl_format = 'best'
    client.ytdl_merge_output_format = 'mkv'
    client.root_folder = root_folder
    client.season_padding = client.episode_padding = 0
    client.sleep_requests = 0
    client.debug = False
    options = client.download_options(
        {'id': 1, 'title': series_title, 'path': path},
        {'title': episode_title, 'seasonNumber': 1, 'episodeNumber': 1},
    )
    with app.yt_dlp.YoutubeDL(options) as ydl:
        return ydl.prepare_filename(dict(METADATA))


class OutputTemplateContractTests(unittest.TestCase):

    def test_hostile_values_survive_in_every_position(self):
        """Each interpolated field must render its input verbatim."""
        positions = ('root_folder', 'path', 'series_title', 'episode_title')
        for position in positions:
            for value in HOSTILE_VALUES:
                with self.subTest(position=position, value=value):
                    # path_safe() rewrites separators in the two title fields,
                    # so keep the probe free of them and compare what remains.
                    probe = f'X{value}X'
                    kwargs = {position: probe}
                    if position == 'root_folder':
                        kwargs[position] = f'/mnt/{probe}'
                    elif position == 'path':
                        kwargs[position] = f'/tv/{probe}'
                    filename = render(**kwargs)
                    self.assertIn(
                        probe, filename,
                        f'{position}={probe!r} did not survive into the '
                        f'filename; yt-dlp consumed part of it as a template '
                        f'directive. Got: {filename}')

    def test_no_metadata_ever_leaks_into_the_filename(self):
        """No yt-dlp field value may appear, in any position."""
        for position in ('root_folder', 'path', 'series_title', 'episode_title'):
            for value in HOSTILE_VALUES:
                with self.subTest(position=position, value=value):
                    kwargs = {position: f'/mnt/{value}' if position == 'root_folder'
                              else f'/tv/{value}' if position == 'path' else value}
                    filename = render(**kwargs)
                    for marker in LEAK_MARKERS:
                        self.assertNotIn(
                            marker, filename,
                            f'{position}={value!r} leaked {marker!r} into the '
                            f'filename: {filename}')

    def test_intended_extension_directive_still_resolves(self):
        """Escaping must not disable the one directive the template owns."""
        for position in ('root_folder', 'path', 'series_title', 'episode_title'):
            for value in HOSTILE_VALUES:
                with self.subTest(position=position, value=value):
                    kwargs = {position: f'/mnt/{value}' if position == 'root_folder'
                              else f'/tv/{value}' if position == 'path' else value}
                    self.assertTrue(
                        render(**kwargs).endswith('.mkv'),
                        f'%(ext)s stopped resolving with {position}={value!r}')

    def test_ordinary_values_are_unaffected(self):
        """The common path must render exactly as it always has."""
        self.assertEqual(
            render(),
            '/tv/Show/Season 1/Show - S1E1 - Episode WEBDL.mkv')

    def test_escape_helper_is_idempotent_per_application(self):
        """One escape pass per value -- double-escaping would show as %%."""
        self.assertEqual(app.escape_template_literal('100%'), '100%%')
        self.assertEqual(app.escape_template_literal('100%%'), '100%%%%')
        self.assertEqual(app.escape_template_literal(''), '')
        self.assertIsNone(app.escape_template_literal(None))


if __name__ == '__main__':
    unittest.main()
