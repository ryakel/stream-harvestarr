#!/bin/sh
set -e

PUID=${PUID:-911}
PGID=${PGID:-1000}
UMASK=${UMASK:-002}

umask "$UMASK"

if [ "$PUID" != "911" ] || [ "$PGID" != "1000" ]; then
    deluser ytdlp 2>/dev/null || true
    delgroup ytdlpg 2>/dev/null || true

    addgroup -g "$PGID" ytdlpg
    adduser -D -u "$PUID" -h /config -s /bin/false -G ytdlpg ytdlp
fi

current_uid=$(stat -c "%u" /config)
current_gid=$(stat -c "%g" /config)

if [ "$current_uid" != "$PUID" ] || [ "$current_gid" != "$PGID" ]; then
    chown -R "$PUID:$PGID" /config /logs
fi

exec su-exec "$PUID:$PGID" python -u /app/stream_harvestarr.py
