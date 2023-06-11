FROM python:3.11-slim-bullseye
LABEL maintainer="github.com/ryakel"

# Copy requirements
COPY requirements.txt requirements.txt

# Update and install ffmpeg and requirements
RUN apt update && \
    apt upgrade -y && \
    apt install -y gcc g++ ffmpeg fontconfig wget lbzip2 libssl1.1 libssl-dev libfreetype6 libfreetype6-dev libfontconfig1 libfontconfig1-dev && \
    pip install --upgrade pip && \
    pip3 install -r requirements.txt

# create abc user so root isn't used
RUN \
	groupmod -g 1000 users && \
	useradd -u 911 -U -d /config -s /bin/false abc && \
	usermod -G users abc && \
# create necessary files / folders
	mkdir -p /config /app /sonarr_root /logs && \
	touch /var/lock/sonarr_youtube.lock && \
    wget https://bitbucket.org/ariya/phantomjs/downloads/phantomjs-2.1.1-linux-x86_64.tar.bz2 && \
    tar xf phantomjs-2.1.1-linux-x86_64.tar.bz2 && \
    mv phantomjs-2.1.1-linux-x86_64/bin/phantomjs /usr/local/bin/phantomjs && \
    rm -rf phantomjs-2.1.1-linux-x86_64* && \
    sed -e '/ssl_conf = ssl_sect/ s/^#*/#/' -i /etc/ssl/openssl.cnf

# add volumes
VOLUME /config
VOLUME /sonarr_root
VOLUME /logs

# add local files
COPY app/ /app

# update file permissions
RUN \
    chmod a+x \
    /app/sonarr_youtubedl.py \
    /app/utils.py \
    /app/config.yml.template && \
# clean up the container
    apt-get remove g++ gcc wget lbzip2 -y && \
    apt-get autoremove -y && \
    apt-get clean -y && \
    apt-get install curl -y 

# ENV setup
ENV CONFIGPATH /config/config.yml

CMD [ "python", "-u", "/app/sonarr_youtubedl.py" ]