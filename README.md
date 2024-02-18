![Screen Harvester logo](/img/stream-harvestarr-logo_small.png)
# Stream Harvestarr by [@ryakel](https://github.com/ryakel)

![Docker Build](https://img.shields.io/docker/cloud/automated/ryakel/stream-harvestarr?style=flat-square)
![Docker Pulls](https://img.shields.io/docker/pulls/ryakel/stream-harvestarr?style=flat-square)
![Docker Stars](https://img.shields.io/docker/stars/ryakel/stream-harvestarr?style=flat-square)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Docker Hub](https://img.shields.io/badge/Open%20On-DockerHub-blue)](https://hub.docker.com/r/ryakel/stream-harvestarr)

[ryakel/stream-harvestarr](https://github.com/ryakel/stream-harvestarr) is a [Sonarr](https://sonarr.tv/) companion script to allow the automatic downloading of web series normally not available for Sonarr to search for. Using [YT-DLP](https://github.com/yt-dlp/yt-dlp) (a youtube-dl fork with added features) it allows you to download your webseries from the list of [supported sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).

## Features

* Downloading **Web Series** using online sources normally unavailable to Sonarr
* Ability to specify the downloaded video format globally or per series
* Downloads new episodes automatically once available
* Imports directly to Sonarr and it can then update your plex as and example
* Allows setting time offsets to handle prerelease series
* Can pass cookies.txt to handle site logins

## How do I use it

1. Firstly you need a series that is available online in the supported sites that YouTube-DL can grab from.
1. Secondly you need to add this to Sonarr and monitor the episodes that you want.
1. Thirdly edit your config.yml accordingly so that this knows where your Sonarr is, which series you are after and where to grab it from.
1. Lastly be aware that this requires the TVDB to match exactly what the episodes titles are in the scan, generally this is ok but as its an openly editable site sometime there can be differences.

## Supported Architectures

The following **Linux** architectures supported by this image are:

| Architectures | Tag |
| :----: | --- |
| 386<br>amd64 | latest |
| 386<br>amd64 | dev |
| armv7 (deprecated)<br>arm64 (deprecated) | ≤ 0.3.30 |

:warning: ARM builds have been deprecated as of v0.3.30.<br> 
No further development is expected on them going forward. :warning:

## Version Tags

| Tag | Description |
| :----: | --- |
| latest | Current release code |
| dev | Pre-release code for testing issues |
| v.X.Y.Z | Versions matching [GitHub Releases](https://github.com/ryakel/stream-harvestarr/releases) |

## Great how do I get started

Obviously its a docker image so you need docker, if you don't know what that is you need to look into that first.

### docker

```bash
docker create \
  --name=stream-harvestarr \
  -v /path/to/data:/config \
  -v /path/to/sonarrmedia:/sonarr_root \
  -v /path/to/logs:/logs \
  --restart unless-stopped \
  ryakel/stream-harvestarr
```

### docker-compose

```yaml
---
version: '3.4'
services:
  stream-harvestarr:
    image: ryakel/stream-harvestarr
    container_name: stream-harvestarr
    volumes:
      - /path/to/data:/config
      - /path/to/sonarrmedia:/sonarr_root
      - /path/to/logs:/logs
    healthcheck:
      test: curl --fail https://youtube.com || exit 1
      interval: 5s
      retries: 5
      start_period: 20s
      timeout: 10s
```

### Docker volumes

| Parameter | Function |
| :----: | --- |
| `-v /config` | Stream Harvestarr configs |
| `-v /sonarr_root` | Root library location from Sonarr container |
| `-v /logs` | log location |

**Clarification on sonarr_root**

A couple of people are not sure what is meant by the sonarr root. As this downloads directly to where you media is stored I mean the root folder where sonarr will place the files. So in sonarr you have your files moving to `/mnt/sda1/media/tv/Smarter Every Day/` as an example, in sonarr you will see that it saves this series to `/tv/Smarter Every Day/` meaning the sonarr root is `/mnt/sda1/media/` as this is the root folder sonarr is working from.

## Configuration file

On first run the docker will create a template file in the config folder. Example [config.yml.template](./app/config.yml.template)

Copy the `config.yml.template` to a new file called `config.yml` and edit accordingly.

If you found this helpful, please consider donating below.

<!-- markdownlint-disable MD033 -->
<a href="https://www.buymeacoffee.com/ryakel" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/lato-black.png" alt="Buy Me A Coffee" style="height: 51px !important;width: 217px !important;" ></a>
<!-- markdownlint-enable MD033 -->

Credit to [@whatdaybob](https://github.com/whatdaybob/sonarr_youtubedl) for the original code.