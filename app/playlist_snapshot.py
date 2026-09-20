"""Compact, temporary on-disk snapshots for arbitrarily large playlists."""

import sqlite3
import weakref
from collections.abc import Iterable, Iterator
from contextlib import closing


class PlaylistSnapshot:
    """Store matching fields without retaining yt-dlp's metadata in memory.

    An empty SQLite filename creates a private temporary database, deleted when
    the connection closes. A snapshot is only published after extraction ends.
    """

    def __init__(self, entries: Iterable[tuple[str | None, str]]):
        self._connection = sqlite3.connect('')
        self._close = weakref.finalize(self, self._connection.close)
        try:
            self._connection.execute('PRAGMA cache_size = -2048')
            self._connection.execute(
                'CREATE TABLE entries (position INTEGER PRIMARY KEY, title TEXT, url TEXT)'
            )
            with self._connection:
                self._connection.executemany(
                    'INSERT INTO entries (title, url) VALUES (?, ?)', entries
                )
            self._count = self._connection.execute('SELECT count(*) FROM entries').fetchone()[0]
        except BaseException:
            self._close()
            raise

    def __len__(self):
        return self._count

    def close(self):
        """Release the temporary database; repeated calls are harmless."""
        self._close()

    def __iter__(self):
        return self._read('ASC')

    def __reversed__(self):
        return self._read('DESC')

    def _read(self, order: str) -> Iterator[dict[str, str | None]]:
        with closing(
            self._connection.execute(f'SELECT title, url FROM entries ORDER BY position {order}')
        ) as cursor:
            for title, url in cursor:
                yield {'title': title, 'url': url}
