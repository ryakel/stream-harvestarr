# Configuration Guide

This guide covers all configuration options available in Stream Harvestarr's `config.yml` file.

## Table of Contents

- [Overview](#overview)
- [Stream Harvestarr Settings](#stream-harvestarr-settings)
- [Sonarr Connection](#sonarr-connection)
- [YT-DLP Settings](#yt-dlp-settings)
- [Series Configuration](#series-configuration)
- [Rate Limiting Configuration](#rate-limiting-configuration)

## Overview

Stream Harvestarr uses a YAML configuration file located at `/config/config.yml` inside the container. On first run, a template file (`config.yml.template`) is created automatically.

To get started:

```bash
cd /path/to/your/config
cp config.yml.template config.yml
nano config.yml
```

## Stream Harvestarr Settings

### Basic Settings

```yaml
streamharvestarr:
    scan_interval: 1
    debug: False
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `scan_interval` | integer | 60 | Minutes between each scan for new episodes |
| `debug` | boolean | False | Enable verbose logging output |

### Rate Limiting Settings

These settings help prevent and handle rate limiting from streaming sites like YouTube. See the [Rate Limiting guide](Rate-Limiting) for detailed information.

```yaml
streamharvestarr:
    download_delay: 5
    sleep_requests: 1
    rate_limit_sleep: 900
    exponential_backoff: True
    backoff_multiplier: 2.0
    backoff_max: 3600
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `download_delay` | integer | 0 | Seconds to wait between downloads. Recommended: 5-10 for rate limit prevention |
| `sleep_requests` | integer | 0 | Seconds to wait between API requests to streaming sites. Recommended: 1-3 |
| `rate_limit_sleep` | integer | 900 | Initial wait time in seconds when rate limited (15 minutes default) |
| `exponential_backoff` | boolean | True | Enable exponential backoff for repeated rate limiting |
| `backoff_multiplier` | float | 2.0 | Multiply wait time by this factor on each subsequent rate limit |
| `backoff_max` | integer | 3600 | Maximum backoff time in seconds (1 hour default) |

**Recommended settings for bulk downloads:**

```yaml
streamharvestarr:
    scan_interval: 1
    debug: False
    download_delay: 5        # Wait between downloads
    sleep_requests: 1        # Wait between API calls
    rate_limit_sleep: 900    # Start with 15 minute wait
    exponential_backoff: True
    backoff_multiplier: 2.0
    backoff_max: 3600
```

## Sonarr Connection

Configure how Stream Harvestarr connects to your Sonarr instance.

```yaml
sonarr:
    host: 192.168.1.123
    port: 8989
    apikey: your_api_key_here
    ssl: false
    # basedir: '/sonarr'  # Optional
    # version: v4         # Optional
```

| Setting | Type | Required | Description |
|---------|------|----------|-------------|
| `host` | string | Yes | Sonarr server IP address or hostname |
| `port` | integer | Yes | Sonarr port (default: 8989) |
| `apikey` | string | Yes | Sonarr API key (found in Settings → General) |
| `ssl` | boolean | Yes | Use HTTPS instead of HTTP |
| `basedir` | string | No | Base directory if Sonarr runs behind a proxy (e.g., `/sonarr`) |
| `version` | string | No | Set to `v4` if running Sonarr v4 beta |

### Finding Your Sonarr API Key

1. Open Sonarr web interface
2. Go to Settings → General
3. Scroll to Security section
4. Copy the API Key value

## YT-DLP Settings

Global download settings for YT-DLP.

```yaml
ytdl:
    default_format: bestvideo[width<=1920]+bestaudio/best[width<=1920]
    merge_output_format: "mkv"
```

| Setting | Type | Description |
|---------|------|-------------|
| `default_format` | string | Default video quality format selector |
| `merge_output_format` | string | Output container format (avi, flv, mkv, mov, mp4, webm) |

### Format Selection Examples

**1080p maximum:**
```yaml
default_format: bestvideo[width<=1920]+bestaudio/best[width<=1920]
```

**720p maximum:**
```yaml
default_format: bestvideo[width<=1280]+bestaudio/best[width<=1280]
```

**Best available quality:**
```yaml
default_format: bestvideo+bestaudio/best
```

**MP4 only with fallback:**
```yaml
default_format: bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best
```

For more format options, see the [YT-DLP format selection documentation](https://github.com/yt-dlp/yt-dlp#format-selection).

## Series Configuration

Define which series to monitor and download.

### Basic Series Entry

```yaml
series:
  - title: Smarter Every Day
    url: https://www.youtube.com/channel/UC6107grRI4m0o2-emgoDnAA
```

### Series with Custom Format

```yaml
series:
  - title: The Slow Mo Guys
    url: https://www.youtube.com/channel/UCUK0HBIBWgM2c4vsPhkYY4w
    format: bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best
```

### Series with Cookies

```yaml
series:
  - title: Members Only Series
    url: https://www.youtube.com/channel/UC_CHANNEL_ID
    cookies_file: youtube_cookies.txt
```

### Series with Time Offset

For early access content that requires a delay before being considered "aired":

```yaml
series:
  - title: CHUMP
    url: https://www.youtube.com/playlist?list=PLUBVPK8x-XMiVzV098TtYq55awkA2XmXm
    offset:
      days: 2
      hours: 3
```

### Series with Subtitles

```yaml
series:
  - title: Ready Set Show
    url: https://www.youtube.com/playlist?list=PLTur7oukosPEwFTPJ1WeDvitauWzRiIhp
    playlistreverse: False
    subtitles:
      languages: ['en']
      autogenerated: True
```

### Series with Regex Matching

```yaml
series:
  - title: CHUMP
    url: https://www.youtube.com/playlist?list=PLUBVPK8x-XMiVzV098TtYq55awkA2XmXm
    regex:
      sonarr:
        match: '.-.#[0-9]*$'
        replace: ''
```

### Complete Series Options

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `title` | string | Required | Series name (must match Sonarr exactly) |
| `url` | string | Required | Channel or playlist URL |
| `format` | string | Optional | Override default format for this series |
| `cookies_file` | string | Optional | Cookie file for authentication (relative to config dir) |
| `playlistreverse` | boolean | True | Process playlist in reverse order |
| `offset` | object | Optional | Time offset for early access content |
| `offset.weeks` | integer | Optional | Weeks to wait after air date |
| `offset.days` | integer | Optional | Days to wait after air date |
| `offset.hours` | integer | Optional | Hours to wait after air date |
| `offset.minutes` | integer | Optional | Minutes to wait after air date |
| `subtitles` | object | Optional | Enable subtitle downloading |
| `subtitles.languages` | array | ['en'] | Subtitle language codes |
| `subtitles.autogenerated` | boolean | False | Include auto-generated subtitles |
| `regex` | object | Optional | Title matching patterns |
| `regex.sonarr.match` | string | Optional | Regex pattern to match in Sonarr title |
| `regex.sonarr.replace` | string | Optional | Replacement string for matched pattern |
| `regex.site.match` | string | Optional | Regex pattern to match in site title |
| `regex.site.replace` | string | Optional | Replacement string for matched pattern |

## Example Complete Configuration

```yaml
streamharvestarr:
    scan_interval: 1
    debug: False
    download_delay: 5
    sleep_requests: 1
    rate_limit_sleep: 900
    exponential_backoff: True
    backoff_multiplier: 2.0
    backoff_max: 3600

sonarr:
    host: 192.168.1.100
    port: 8989
    apikey: 1234567890abcdef1234567890abcdef
    ssl: false

ytdl:
    default_format: bestvideo[width<=1920]+bestaudio/best[width<=1920]
    merge_output_format: "mkv"

series:
  # Standard channel
  - title: Smarter Every Day
    url: https://www.youtube.com/channel/UC6107grRI4m0o2-emgoDnAA

  # With custom format and cookies
  - title: The Slow Mo Guys
    url: https://www.youtube.com/channel/UCUK0HBIBWgM2c4vsPhkYY4w
    cookies_file: youtube_cookies.txt
    format: bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best

  # With time offset and regex
  - title: CHUMP
    url: https://www.youtube.com/playlist?list=PLUBVPK8x-XMiVzV098TtYq55awkA2XmXm
    offset:
      days: 2
      hours: 3
    regex:
      sonarr:
        match: '.-.#[0-9]*$'
        replace: ''

  # With subtitles
  - title: Ready Set Show
    url: https://www.youtube.com/playlist?list=PLTur7oukosPEwFTPJ1WeDvitauWzRiIhp
    playlistreverse: False
    subtitles:
      languages: ['en', 'es']
      autogenerated: True
```

## Next Steps

- Learn about [Rate Limiting configuration](Rate-Limiting)
- Explore [Advanced Features](Advanced-Features)
- Review [Troubleshooting](Troubleshooting) for common issues
