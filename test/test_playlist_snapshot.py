"""Large snapshots must stream both construction and ordered reads."""

import gc
import os
import sqlite3
import sys
import tracemalloc
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from playlist_snapshot import PlaylistSnapshot


class PlaylistSnapshotTests(unittest.TestCase):
    def test_large_snapshot_does_not_retain_python_entries(self):
        """Verify large snapshot does not retain python entries."""
        tracemalloc.start()
        try:
            snapshot = PlaylistSnapshot(
                (f'Episode {number}', f'https://youtu.be/{number}')
                for number in range(100_000)
            )
            self.assertEqual(len(snapshot), 100_000)
            self.assertEqual(next(iter(snapshot))['title'], 'Episode 0')
            self.assertEqual(next(reversed(snapshot))['title'], 'Episode 99999')
            self.assertEqual(sum(1 for _ in snapshot), 100_000)
            self.assertLess(tracemalloc.get_traced_memory()[1], 2 * 1024 * 1024)
        finally:
            tracemalloc.stop()

    def test_readers_are_independent_and_preserve_duplicate_titles(self):
        """Verify readers are independent and preserve duplicate titles."""
        snapshot = PlaylistSnapshot([
            ('Same title', 'https://youtu.be/one'),
            ('Same title', 'https://youtu.be/two'),
            (None, 'https://youtu.be/three'),
        ])
        first, second = iter(snapshot), iter(snapshot)
        self.assertEqual(next(first), next(second))
        self.assertEqual(next(first)['url'], 'https://youtu.be/two')
        self.assertEqual(list(reversed(snapshot)), list(snapshot)[::-1])
        first.close()
        self.assertEqual(next(second)['url'], 'https://youtu.be/two')
        second.close()

    def test_discarded_snapshot_closes_temporary_database(self):
        """Verify discarded snapshot closes temporary database."""
        snapshot = PlaylistSnapshot([])
        connection = snapshot._connection
        del snapshot
        gc.collect()
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT count(*) FROM entries')
