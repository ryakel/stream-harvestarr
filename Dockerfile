FROM python:3.12-alpine
LABEL maintainer="github.com/ryakel"
LABEL org.opencontainers.image.source="https://github.com/ryakel/stream-harvestarr"

# Copy requirements
COPY requirements.txt requirements.txt

# Update and install ffmpeg and requirements
RUN apk update --no-cache && \
    apk upgrade --no-cache && \
    apk add --no-cache ffmpeg curl alpine-sdk && \
    pip3 install --upgrade pip && \
    pip3 install -r requirements.txt

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
RUN \
    chmod a+x \
    /app/stream_harvestarr.py \
    /app/utils.py \
    /app/config.yml.template && \
    cp /app/config.yml.template /config/config.yml && \
# clean up container
    apk del alpine-sdk

# ENV setup
ENV CONFIGPATH /config/config.yml

CMD [ "python", "-u", "/app/stream_harvestarr.py" ]