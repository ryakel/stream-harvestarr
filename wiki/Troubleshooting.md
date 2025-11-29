# Troubleshooting Guide

This guide helps diagnose and resolve common issues with Stream Harvestarr.

## Table of Contents

- [Rate Limiting Issues](#rate-limiting-issues)
- [Download Failures](#download-failures)
- [Connection Problems](#connection-problems)
- [TVDB Matching Issues](#tvdb-matching-issues)
- [Container Issues](#container-issues)
- [Log Analysis](#log-analysis)

## Rate Limiting Issues

### Symptoms

```
ERROR: [youtube] This content isn't available, try again later
The current session has been rate-limited by YouTube
```

### Quick Fix

Add these settings to your `config.yml`:

```yaml
streamharvestarr:
    download_delay: 5
    sleep_requests: 1
    rate_limit_sleep: 900
    exponential_backoff: True
```

Restart the container:
```bash
docker restart stream-harvestarr
```

### Detailed Solutions

**1. Enable Preventive Delays**

If you're getting rate limited frequently, increase delays:

```yaml
streamharvestarr:
    download_delay: 10      # Increased from 5
    sleep_requests: 3       # Increased from 1
```

**2. Check Current Backoff Status**

Look for these log messages:
```
INFO - Rate limit recovered - resetting backoff counter
```

This shows the system is working and recovering automatically.

**3. Verify Backoff Configuration**

Ensure exponential backoff is enabled:

```yaml
streamharvestarr:
    exponential_backoff: True
    backoff_multiplier: 2.0
    backoff_max: 3600
```

**4. Wait It Out**

YouTube rate limits can last:
- 15 minutes to 1 hour typically
- Up to several hours for repeated violations
- The system will automatically retry after waiting

**5. Check Your IP**

Rate limits are often IP-based. Issues may occur if:
- Using a VPN (try different server)
- Using shared hosting/datacenter IP
- Multiple users on same network downloading

**6. Validate Cookies**

If using cookies for authentication:

```bash
# Check cookie file exists
ls -la /path/to/config/youtube_cookies.txt

# Verify it's not empty
cat /path/to/config/youtube_cookies.txt
```

Expired or invalid cookies can trigger rate limits.

## Download Failures

### "Failed - Episode Title - ERROR"

**Check video availability:**

1. Open the channel/playlist URL in a browser
2. Verify the episode exists and is accessible
3. Check if it requires authentication (members-only)

**Common causes:**

```yaml
# Video is members-only but no cookies provided
series:
  - title: Series Name
    url: https://youtube.com/channel/...
    cookies_file: youtube_cookies.txt  # Add this
```

### "Missing - Episode Title"

This is normal and means:
- Episode hasn't been released yet
- Episode title doesn't match TVDB exactly
- Episode is not in the playlist/channel yet

**Check title matching:**

1. Compare Sonarr episode title with YouTube video title
2. Use regex to adjust if needed:

```yaml
series:
  - title: Series Name
    url: https://youtube.com/...
    regex:
      sonarr:
        match: 'Episode ([0-9]+)'
        replace: 'Ep\\1'
```

### Format Selection Errors

If getting "No suitable format" errors:

```
ERROR: No suitable format found
```

**Solution:** Adjust format requirements:

```yaml
# Too restrictive
format: bestvideo[height=1080][ext=mp4]+bestaudio[ext=m4a]

# More flexible
format: bestvideo[height<=1080]+bestaudio/best
```

### SSL/Certificate Errors

```
ERROR: SSL: CERTIFICATE_VERIFY_FAILED
```

**Solution 1:** Add certificate bundle (Docker):
```yaml
volumes:
  - /etc/ssl/certs:/etc/ssl/certs:ro
```

**Solution 2:** Update YT-DLP:
```bash
docker pull ryakel/stream-harvestarr:latest
docker restart stream-harvestarr
```

## Connection Problems

### Cannot Connect to Sonarr

```
Error with sonarr config.yml values
```

**Check 1: Verify connection details**

```yaml
sonarr:
    host: 192.168.1.100  # Correct IP?
    port: 8989           # Correct port?
    apikey: ...          # Valid API key?
```

**Check 2: Test connection manually**

```bash
curl http://192.168.1.100:8989/api/v3/system/status?apikey=YOUR_KEY
```

Should return JSON with Sonarr version info.

**Check 3: Network connectivity**

From inside the container:
```bash
docker exec stream-harvestarr ping -c 3 192.168.1.100
```

**Check 4: Firewall rules**

Ensure Sonarr port is accessible:
- Check host firewall
- Check Docker network settings
- Verify Sonarr is listening on all interfaces (0.0.0.0)

### Docker Network Issues

If using Docker Compose with custom networks:

```yaml
services:
  sonarr:
    networks:
      - media

  stream-harvestarr:
    networks:
      - media  # Must be on same network
    environment:
      - SONARR_HOST=sonarr  # Can use service name
```

## TVDB Matching Issues

### Episode Titles Don't Match

Stream Harvestarr requires exact title matches between:
1. Sonarr (which uses TVDB data)
2. YouTube video titles

**Symptoms:**
- Episodes show as "Missing" despite existing on YouTube
- Wrong episodes download

**Solution 1: Update TVDB**

1. Visit [TheTVDB.com](https://thetvdb.com)
2. Find your series
3. Update episode titles to match YouTube
4. Refresh series in Sonarr after 24 hours

**Solution 2: Use regex to adjust titles**

```yaml
series:
  - title: My Series
    url: https://youtube.com/...
    regex:
      sonarr:
        match: ' - Part ([0-9]+)$'
        replace: ' Pt\\1'
      site:
        match: '^Episode ([0-9]+):'
        replace: 'Ep\\1 -'
```

**Solution 3: Check episode naming in Sonarr**

Ensure Sonarr is using absolute episode numbers for web series:
1. Go to Series in Sonarr
2. Edit series
3. Check "Season" numbering matches YouTube playlist structure

## Container Issues

### Container Keeps Restarting

**Check logs:**
```bash
docker logs stream-harvestarr
```

**Common causes:**

1. **Missing config file:**
```
Error: /config/config.yml not found
```
Solution: Ensure config.yml exists in mapped volume

2. **Invalid YAML:**
```
Error: Invalid YAML syntax
```
Solution: Validate YAML at [yamllint.com](http://www.yamllint.com/)

3. **Permission issues:**
```
Error: Permission denied
```
Solution: Check volume permissions:
```bash
ls -la /path/to/config
chmod -R 755 /path/to/config
```

### High CPU/Memory Usage

**Normal during downloads:**
- YT-DLP and FFmpeg use significant resources
- CPU spike during video merging/conversion

**Abnormal usage:**
- Continuous high CPU when idle
- Memory steadily increasing

**Solutions:**

1. **Limit concurrent operations:**
```yaml
streamharvestarr:
    scan_interval: 5  # Increase from 1
```

2. **Check for stuck processes:**
```bash
docker exec stream-harvestarr ps aux
```

3. **Restart container:**
```bash
docker restart stream-harvestarr
```

### Container Won't Start

**Check volume mappings:**
```bash
docker inspect stream-harvestarr | grep -A 10 Mounts
```

**Verify paths exist:**
```bash
ls -la /path/to/config
ls -la /path/to/sonarr_root
ls -la /path/to/logs
```

**Check Docker logs:**
```bash
docker logs stream-harvestarr --tail 50
```

## Log Analysis

### Enabling Debug Logging

```yaml
streamharvestarr:
    debug: True
```

Or pass debug flag:
```bash
docker run -e DEBUG=True ryakel/stream-harvestarr
```

### Understanding Log Levels

**INFO** - Normal operations:
```
INFO - Downloaded - Episode Name
INFO - Waiting...
```

**WARNING** - Non-critical issues:
```
WARNING - Series Name is not currently monitored
WARNING - YouTube rate limit detected
```

**ERROR** - Failed operations:
```
ERROR - Failed - Episode Name - No suitable format
ERROR - Cannot connect to Sonarr
```

**DEBUG** - Detailed information (when debug enabled):
```
DEBUG - DEBUGGING ENABLED
DEBUG - Begin call Sonarr for all episodes
DEBUG - yt-dlp opts used for downloading
```

### Common Log Patterns

**Healthy operation:**
```
INFO - Initial run
INFO - Smarter Every Day missing 2 episodes
INFO - Processing Wanted Downloads
INFO - Downloaded - Episode Title
INFO - Waiting...
```

**Rate limit pattern:**
```
INFO - Downloaded - Episode 1
INFO - Downloaded - Episode 2
ERROR - Failed - Episode 3 - RATE LIMITED
WARNING - Exponential backoff: Sleeping for 900 seconds
INFO - Resuming downloads after rate limit cooldown
INFO - Downloaded - Episode 3
INFO - Rate limit recovered - resetting backoff counter
```

**Connection issue pattern:**
```
ERROR - Cannot connect to Sonarr
ERROR - Connection refused at http://192.168.1.100:8989
```

### Log File Locations

**Inside container:**
```
/logs/stream-harvestarr.log
```

**On host:**
```
/path/to/your/mapped/logs/stream-harvestarr.log
```

**View logs:**
```bash
# Real-time
tail -f /path/to/logs/stream-harvestarr.log

# Last 100 lines
tail -n 100 /path/to/logs/stream-harvestarr.log

# Search for errors
grep ERROR /path/to/logs/stream-harvestarr.log

# Search for specific series
grep "Series Name" /path/to/logs/stream-harvestarr.log
```

## Getting Additional Help

If your issue isn't covered here:

### Before Opening an Issue

1. **Check existing issues** on [GitHub](https://github.com/ryakel/stream-harvestarr/issues)
2. **Gather information:**
   - Stream Harvestarr version/tag
   - Docker version
   - Sonarr version
   - Error messages from logs
   - Your config.yml (redact API keys)

3. **Enable debug logging** and capture relevant output

### Opening an Issue

Include:

```markdown
**Environment:**
- Stream Harvestarr: latest / v1.x.x
- Docker: 20.x.x
- Sonarr: v3/v4
- Platform: Linux/Windows/Mac

**Issue Description:**
[Clear description of the problem]

**Config (redacted):**
```yaml
[Your config with API keys removed]
```

**Logs:**
```
[Relevant log output]
```

**Steps to Reproduce:**
1. Step one
2. Step two
3. Issue occurs
```

### Useful Debug Commands

```bash
# Container status
docker ps -a | grep stream-harvestarr

# Recent logs
docker logs stream-harvestarr --tail 100

# Follow logs real-time
docker logs -f stream-harvestarr

# Exec into container
docker exec -it stream-harvestarr /bin/bash

# Check config
docker exec stream-harvestarr cat /config/config.yml

# Check YT-DLP version
docker exec stream-harvestarr yt-dlp --version

# Test Sonarr connection
docker exec stream-harvestarr curl http://SONARR_IP:PORT/api/v3/system/status?apikey=KEY
```

## Related Pages

- [Configuration Guide](Configuration) - Full config reference
- [Rate Limiting](Rate-Limiting) - Detailed rate limiting guide
- [Advanced Features](Advanced-Features) - Advanced configuration options
