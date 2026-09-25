![Screen Harvester logo](/img/stream-harvestarr-logo_small.png)
# Stream Harvestarr by [@ryakel](https://github.com/ryakel)

![Docker Pulls](https://img.shields.io/docker/pulls/ryakel/stream-harvestarr?style=flat-square)
![Docker Stars](https://img.shields.io/docker/stars/ryakel/stream-harvestarr?style=flat-square)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Docker Hub](https://img.shields.io/badge/Open%20On-DockerHub-blue)](https://hub.docker.com/r/ryakel/stream-harvestarr)

:warning: NOTE: The image name and repo have changed to ```ryakel/stream-havestarr```. 
```ryakel/sonarr-yt-dlp``` has been deprecated as of version ```1.2.17```. 
Please update your image and update your config.yml. :warning:

[ryakel/stream-harvestarr](https://github.com/ryakel/stream-harvestarr) is a [Sonarr](https://sonarr.tv/) companion script to allow the automatic downloading of web series normally not available for Sonarr to search for. Using [YT-DLP](https://github.com/yt-dlp/yt-dlp) (a youtube-dl fork with added features) it allows you to download your webseries from the list of [supported sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).

## Features

* Downloading **Web Series** using online sources normally unavailable to Sonarr
* Ability to specify the downloaded video format globally or per series
* Downloads new episodes automatically once available
* Imports directly to Sonarr and it can then update your plex as and example
* Allows setting time offsets to handle prerelease series
* Can pass cookies.txt to handle site logins
* Smart rate limiting with exponential backoff to prevent YouTube throttling
* Comprehensive configuration options for bulk downloads

## Documentation

### Playlist scans and download recovery

Sources are extracted once per scan and stored in temporary SQLite snapshots
containing titles and URLs. Full sources retain their last complete snapshot if
a refresh fails; the log distinguishes that fallback from a failure with no
snapshot available. Snapshots require temporary disk space and do not survive a
restart. Full enumeration still needs to fetch every page.

YouTube tabs stream through upstream yt-dlp's public unprocessed-result API into
SQLite. There is no custom extractor or private method override. Normal yt-dlp
playlist processing retains all video metadata, even with `lazy_playlist`;
the tab path avoids that allocation. Other extractors retain normal processing.
SQLite uses a small page cache, while temporary disk use grows with the source.
yt-dlp still owns its page buffers and continuation bookkeeping; this is not a
claim of constant memory inside the upstream extractor.

Channel searches are opt-in: set `channel_search: True` on a series or shared
service to try 20 channel-search results, then all search results, before the
configured source. Search stages use YouTube's relevance order, regardless of
`playlistreverse`. This can select a different upload when several titles match,
and rankings can change over time. Leave the option off to preserve the configured
source's ordering. Use `regex.require` for channels carrying multiple shows and
`strict_parts` to reject partial uploads for whole episodes. Search snapshots are
closed after each lookup, so their open databases do not grow with the backlog.

A subtitle-download failure retries once without subtitle options and subtitle
postprocessors. Conversion, embedding, filesystem, and unrelated download errors
do not trigger that retry. A successful fallback can leave a video without
subtitles. Three consecutive video HTTP 403 errors stop the entire scan until
the next scheduled run. A successful download or a non-403 download error resets
the counter; episodes without a match do not. Each new scan starts at zero.

Playlist extraction fails closed when yt-dlp reports incomplete YouTube data, so
a partial continuation cannot replace a previously complete snapshot. Failed
refreshes keep the last complete snapshot and are logged for diagnosis.

Configuration and Sonarr naming settings are read before each scan. Only playlist
snapshots are shared between scans; removed sources and unused credential variants
are released. Invalid configuration stops the scan without partially updating an
existing client. A failed Sonarr rescan request is logged separately from a
successful video download, and subsequent episodes continue.

**For detailed documentation, configuration guides, and troubleshooting, visit the [Stream Harvestarr Wiki](https://github.com/ryakel/stream-harvestarr/wiki)**

Key documentation sections:
- [Configuration Guide](https://github.com/ryakel/stream-harvestarr/wiki/Configuration) - Complete configuration reference
- [Rate Limiting & Performance](https://github.com/ryakel/stream-harvestarr/wiki/Rate-Limiting) - Handling YouTube rate limits
- [Troubleshooting](https://github.com/ryakel/stream-harvestarr/wiki/Troubleshooting) - Common issues and solutions
- [Advanced Features](https://github.com/ryakel/stream-harvestarr/wiki/Advanced-Features) - Cookies, subtitles, regex, and more

## How do I use it

1. Firstly you need a series that is available online in the supported sites that YouTube-DL can grab from.
1. Secondly you need to add the series to Sonarr (the way you would any other) and monitor the episodes that you want.
1. Thirdly edit your config.yml accordingly so that this knows where your Sonarr is, which series you are after and where to grab it from.
1. Lastly be aware that this requires the TVDB to match exactly what the episodes titles are in the scan, generally this is ok but as its an openly editable site sometime there can be differences.

## Supported Architectures

The following **Linux** architectures supported by this image are:

| Architectures | Tag | JS runtime for yt-dlp |
| :----: | --- | --- |
| arm64<br>amd64 | latest | deno (yt-dlp's recommended sandboxed runtime) |
| armv7<br>386 | latest | node (deno is not packaged on Alpine for these arches) |
| arm64<br>amd64 | dev | deno |
| armv7<br>386 | dev | node |

YouTube extraction works on all four arches. The `armv7` and `386` images
fall back to `nodejs` because Alpine doesn't ship a `deno` package for
them; if yt-dlp ever requires deno-specific extractor features, those
arches may lag behind `amd64` / `arm64`. amd64 and arm64 remain the
recommended targets.

:spiral_notepad: ARM builds have been restored as of v1.3.3. :spiral_notepad:	

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
    # user: "1000:1000"  # match your host uid:gid — see wiki/Upgrading
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

### Upgrading from Previous Versions

Stream Harvestarr is fully backward compatible with existing configuration files. New rate limiting features (added in recent versions) use sensible defaults if not specified in your config:

- **Rate limiting is disabled by default** - Your existing config will continue working as before
- **No config changes required** - Update the container and it just works
- **Optional improvements** - Add new settings to enable rate limit protection (see [Rate Limiting guide](https://github.com/ryakel/stream-harvestarr/wiki/Rate-Limiting))

To take advantage of the new rate limiting features, you can optionally add these settings to your existing `config.yml` under the `streamharvestarr:` section. See the [config.yml.template](./app/config.yml.template) for examples.

If you found this helpful, please consider donating below.

<!-- markdownlint-disable MD033 -->
<a href="https://www.buymeacoffee.com/ryakel" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/lato-black.png" alt="Buy Me A Coffee" style="height: 51px !important;width: 217px !important;" ></a>
<!-- markdownlint-enable MD033 -->

Credit to [@whatdaybob](https://github.com/whatdaybob/sonarr_youtubedl) for the original code.
