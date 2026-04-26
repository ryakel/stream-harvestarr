# syntax=docker/dockerfile:1.7
FROM python:3.14-alpine
LABEL maintainer="github.com/ryakel"
LABEL org.opencontainers.image.source="https://github.com/ryakel/stream-harvestarr"

ARG TARGETARCH

# Copy requirements
COPY requirements.txt requirements.txt

# yt-dlp needs a JavaScript runtime for YouTube extraction (issue #96).
# nodejs is available on every Alpine arch we publish for; deno is only
# packaged for x86_64 / aarch64, so install it conditionally. yt-dlp is
# configured to prefer deno when present and fall back to node.
#
# BuildKit cache mounts (per TARGETARCH so parallel multi-arch builds don't
# fight over arch-specific package files) make rebuilds -- including under
# QEMU emulation for non-native architectures -- dramatically faster.
RUN --mount=type=cache,target=/var/cache/apk,id=apk-${TARGETARCH},sharing=locked \
    --mount=type=cache,target=/root/.cache/pip,id=pip-${TARGETARCH},sharing=locked \
    ln -vsf /var/cache/apk /etc/apk/cache && \
    apk update && \
    apk upgrade && \
    apk add ffmpeg curl alpine-sdk nodejs && \
    case "$TARGETARCH" in \
        amd64|arm64) apk add deno ;; \
    esac && \
    pip3 install --upgrade pip && \
    pip3 install -r requirements.txt && \
    apk del alpine-sdk

# create ytdlp user so root isn't used
RUN addgroup -g 1000 ytdlpg && \
	adduser -u 911 -h /config -s /bin/false ytdlp -D && \
	addgroup ytdlp ytdlpg && \
# create necessary files / folders
	mkdir -p /config /app /sonarr_root /logs /run/lock && \
	touch /var/lock/sonarr_youtube.lock

# add volumes
VOLUME /config
VOLUME /sonarr_root
VOLUME /logs

# add local files
COPY app/ /app

# update file permissions
RUN chmod a+x \
    /app/stream_harvestarr.py \
    /app/utils.py \
    /app/config.yml.template && \
    cp /app/config.yml.template /config/config.yml

# ENV setup
ENV CONFIGPATH /config/config.yml

CMD [ "python", "-u", "/app/stream_harvestarr.py" ]
