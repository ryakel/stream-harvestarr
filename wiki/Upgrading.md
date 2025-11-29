# Upgrading Guide

This guide helps you upgrade Stream Harvestarr to the latest version and explains what's changed.

## Table of Contents

- [Backward Compatibility](#backward-compatibility)
- [Latest Features](#latest-features)
- [Upgrade Process](#upgrade-process)
- [Post-Upgrade Configuration](#post-upgrade-configuration)
- [Troubleshooting Upgrades](#troubleshooting-upgrades)

## Backward Compatibility

**Stream Harvestarr is fully backward compatible.** You can upgrade to the latest version without modifying your existing `config.yml` file.

### What This Means

- ✅ Your existing configuration continues to work exactly as before
- ✅ No breaking changes to existing features
- ✅ New features are opt-in with sensible defaults
- ✅ No data loss or migration required

### Default Behavior

When upgrading, new features are configured with defaults that maintain existing behavior:

| Feature | Default | Effect |
|---------|---------|--------|
| `download_delay` | `0` | No delays between downloads (original behavior) |
| `sleep_requests` | `0` | No delays between API requests (original behavior) |
| `rate_limit_sleep` | `900` | 15-minute wait when rate limited (only activates if rate limited) |
| `exponential_backoff` | `True` | Smart backoff enabled (only activates if rate limited) |
| `backoff_multiplier` | `2.0` | Doubles wait time on repeated rate limits |
| `backoff_max` | `3600` | Maximum 1-hour wait between attempts |

## Latest Features

### Rate Limiting Protection (v1.3+)

Recent versions include comprehensive rate limiting protection:

1. **Preventive Delays** - Configurable delays between downloads and API requests
2. **Smart Detection** - Automatically detects rate limit errors
3. **Exponential Backoff** - Intelligently increases wait times when repeatedly rate limited
4. **Auto-Recovery** - Resets to normal operation after successful downloads

### Security Improvements (v1.3+)

1. **Sensitive Data Redaction** - API keys and cookies no longer appear in logs
2. **Workflow Permissions** - GitHub Actions use least-privilege security model
3. **Updated Dependencies** - Latest secure versions of all dependencies

### Documentation (v1.3+)

Comprehensive wiki documentation covering:
- Complete configuration reference
- Rate limiting strategies
- Troubleshooting guides
- Advanced features

## Upgrade Process

### Docker (Recommended)

**1. Stop the existing container:**
```bash
docker stop stream-harvestarr
```

**2. Remove the old container:**
```bash
docker rm stream-harvestarr
```

**3. Pull the latest image:**
```bash
docker pull ryakel/stream-harvestarr:latest
```

**4. Start with your existing config:**
```bash
docker create \
  --name=stream-harvestarr \
  -v /path/to/config:/config \
  -v /path/to/sonarrmedia:/sonarr_root \
  -v /path/to/logs:/logs \
  --restart unless-stopped \
  ryakel/stream-harvestarr:latest

docker start stream-harvestarr
```

### Docker Compose

**1. Update your docker-compose.yml image tag (if pinned):**
```yaml
services:
  stream-harvestarr:
    image: ryakel/stream-harvestarr:latest  # or specific version
```

**2. Pull and restart:**
```bash
docker-compose pull stream-harvestarr
docker-compose up -d stream-harvestarr
```

### Verify Upgrade

Check the logs to confirm successful upgrade:
```bash
docker logs stream-harvestarr --tail 50
```

You should see:
```
INFO - Initial run
INFO - Scan interval set to every X minutes
INFO - Exponential backoff enabled for rate limiting  # New feature active
```

## Post-Upgrade Configuration

After upgrading, you can optionally enable new rate limiting features.

### Basic Rate Limiting (Recommended)

Add these lines to your `config.yml` under `streamharvestarr:`:

```yaml
streamharvestarr:
    scan_interval: 1
    debug: False
    download_delay: 5              # NEW: Wait 5 seconds between downloads
    sleep_requests: 1              # NEW: Wait 1 second between API calls
    rate_limit_sleep: 900          # NEW: Wait 15 minutes if rate limited
    exponential_backoff: True      # NEW: Smart backoff (enabled by default)
    backoff_multiplier: 2.0        # NEW: Double wait time each occurrence
    backoff_max: 3600              # NEW: Cap at 1 hour maximum
```

**After adding these settings:**
```bash
docker restart stream-harvestarr
```

### Verify New Settings

Check logs for confirmation:
```bash
docker logs stream-harvestarr | grep -E "(Download delay|Sleep requests|backoff)"
```

Expected output:
```
INFO - Download delay set to 5 seconds between downloads
INFO - Sleep requests set to 1 seconds between API requests
INFO - Exponential backoff enabled for rate limiting
```

## Upgrade Scenarios

### Scenario 1: Upgrade Without Config Changes

**What happens:**
- Container upgrades successfully
- All existing functionality works as before
- Rate limiting features are available but not actively preventing downloads
- If you hit rate limits, exponential backoff automatically activates

**When to use:**
- You rarely experience rate limiting
- You want to upgrade but test before enabling new features
- You have a small number of series

### Scenario 2: Upgrade With Rate Limiting

**What happens:**
- Container upgrades successfully
- Preventive delays reduce rate limit risk
- Downloads are slightly slower but more reliable
- Automatic recovery if rate limited

**When to use:**
- You frequently experience rate limiting
- You're downloading many episodes at once
- You want maximum reliability

### Scenario 3: Upgrade From Very Old Versions

If upgrading from versions before v1.2:

1. **Check for config format changes:**
   - Old: `sonarrytdl:` (deprecated but still supported)
   - New: `streamharvestarr:` (recommended)

2. **Update config key if needed:**
```yaml
# Old format (still works)
sonarrytdl:
    scan_interval: 1

# New format (recommended)
streamharvestarr:
    scan_interval: 1
```

3. **Both formats work** - The code automatically detects which you're using

## Troubleshooting Upgrades

### Issue: Container Won't Start After Upgrade

**Symptom:**
```bash
docker logs stream-harvestarr
Error with streamharvestarr config.yml values.
```

**Solution:**
Check your config.yml syntax:
```bash
# Validate YAML syntax
cat /path/to/config/config.yml
```

Common issues:
- Incorrect indentation (use spaces, not tabs)
- Missing colons after keys
- Invalid boolean values (use `True`/`False` or `true`/`false`)

**Test with template:**
```bash
# Backup your config
cp /path/to/config/config.yml /path/to/config/config.yml.backup

# Try with fresh template
docker run --rm ryakel/stream-harvestarr cat /app/config.yml.template > /path/to/config/config.yml

# Edit with your settings
nano /path/to/config/config.yml
```

### Issue: New Features Not Working

**Symptom:**
Downloads still getting rate limited frequently.

**Check:**
1. Verify settings are in config:
```bash
grep -A 5 "streamharvestarr:" /path/to/config/config.yml
```

2. Verify settings are loaded:
```bash
docker logs stream-harvestarr | grep -E "(delay|sleep|backoff)"
```

3. If no output, settings aren't loading:
   - Check indentation (must be under `streamharvestarr:`)
   - Ensure using `streamharvestarr:` not `sonarrytdl:`
   - Restart container after config changes

### Issue: Downloads Slower After Upgrade

**This is expected** if you enabled rate limiting features.

**Adjust delays if too slow:**
```yaml
streamharvestarr:
    download_delay: 2     # Reduce from 5 to 2
    sleep_requests: 0     # Disable request delays
```

**Monitor for rate limits:**
```bash
docker logs stream-harvestarr | grep "RATE LIMITED"
```

If you see rate limit errors, increase delays again.

### Issue: Old Config Format Warning

**Symptom:**
Everything works but you want to use the new format.

**Migration:**
```yaml
# Change this:
sonarrytdl:
    scan_interval: 1
    debug: False

# To this:
streamharvestarr:
    scan_interval: 1
    debug: False
```

Both work, but `streamharvestarr:` is recommended for future compatibility.

## Version-Specific Notes

### v1.3.x
- Added rate limiting features
- Added security improvements for logging
- Added comprehensive documentation
- Fully backward compatible

### v1.2.x
- Renamed from sonarr-yt-dlp to stream-harvestarr
- Both config keys supported: `sonarrytdl:` and `streamharvestarr:`

### v1.1.x and earlier
- Original functionality
- Basic YT-DLP integration with Sonarr

## Best Practices

### Before Upgrading

1. **Backup your config:**
```bash
cp /path/to/config/config.yml /path/to/config/config.yml.backup
```

2. **Note your current version:**
```bash
docker inspect ryakel/stream-harvestarr | grep "Created"
```

3. **Check current functionality:**
```bash
docker logs stream-harvestarr --tail 100 > pre-upgrade-logs.txt
```

### After Upgrading

1. **Monitor first few scans:**
```bash
docker logs -f stream-harvestarr
```

2. **Verify downloads still work:**
   - Check Sonarr for new downloads
   - Look for "Downloaded" messages in logs
   - Confirm no unexpected errors

3. **Gradually enable rate limiting:**
   - Start conservative (delays: 5-10 seconds)
   - Monitor for rate limits
   - Adjust based on results

### Rollback Plan

If you encounter issues:

**1. Stop new version:**
```bash
docker stop stream-harvestarr
docker rm stream-harvestarr
```

**2. Pull previous version:**
```bash
docker pull ryakel/stream-harvestarr:v1.2.17  # or your previous version
```

**3. Start with backup config:**
```bash
cp /path/to/config/config.yml.backup /path/to/config/config.yml
docker create \
  --name=stream-harvestarr \
  -v /path/to/config:/config \
  -v /path/to/sonarrmedia:/sonarr_root \
  -v /path/to/logs:/logs \
  --restart unless-stopped \
  ryakel/stream-harvestarr:v1.2.17

docker start stream-harvestarr
```

## Related Pages

- [Configuration Guide](Configuration) - Complete configuration reference
- [Rate Limiting](Rate-Limiting) - Detailed rate limiting guide
- [Troubleshooting](Troubleshooting) - Common issues and solutions
