# Rate Limiting & Performance

This guide explains how to handle rate limiting from streaming platforms like YouTube and configure Stream Harvestarr for optimal performance during bulk downloads.

## Table of Contents

- [Understanding Rate Limits](#understanding-rate-limits)
- [Prevention Strategies](#prevention-strategies)
- [Exponential Backoff](#exponential-backoff)
- [Configuration Examples](#configuration-examples)
- [Monitoring and Logs](#monitoring-and-logs)

## Understanding Rate Limits

### What is Rate Limiting?

Rate limiting occurs when streaming platforms detect too many requests from a single source in a short time period. This is a protective measure to prevent abuse and ensure fair usage.

### Common Rate Limit Error

When YouTube rate limits your requests, you'll see errors like:

```
ERROR: [youtube] Zaqf-YFJ_Wk: This content isn't available, try again later.
The current session has been rate-limited by YouTube for up to an hour.
```

### Why Does This Happen?

Rate limiting typically occurs when:

1. **Downloading many episodes back-to-back** without delays
2. **Making rapid API requests** to check for video information
3. **Multiple concurrent downloads** from the same platform
4. **Previous rate limit penalties** still in effect

## Prevention Strategies

Stream Harvestarr provides multiple layers of protection against rate limiting.

### Layer 1: Request Delays

Add delays between YouTube API requests:

```yaml
streamharvestarr:
    sleep_requests: 1  # Wait 1 second between API calls
```

This setting uses YT-DLP's `sleep_interval_requests` option, which is specifically recommended by YT-DLP for avoiding rate limits.

**Recommended values:**
- Light usage (1-5 series): `1` second
- Medium usage (5-10 series): `2` seconds
- Heavy usage (10+ series): `3` seconds

### Layer 2: Download Delays

Add delays between completed downloads:

```yaml
streamharvestarr:
    download_delay: 5  # Wait 5 seconds between downloads
```

This prevents hammering the platform with back-to-back download requests.

**Recommended values:**
- Normal downloads: `5` seconds
- Bulk catching up: `10` seconds
- After previous rate limits: `15` seconds

### Layer 3: Fragment Controls

YT-DLP automatically includes fragment-level controls (already configured in Stream Harvestarr):

- `sleep_interval: 5` - Wait 5 seconds between download fragments
- `max_sleep_interval: 30` - Maximum fragment sleep time
- `concurrent_fragments: 5` - Download 5 fragments at a time
- `throttled_rate: 100K` - Throttle download speed to 100 KB/s

These settings are built-in and don't require configuration.

## Exponential Backoff

When rate limiting does occur, Stream Harvestarr uses exponential backoff to intelligently handle the situation.

### How It Works

Instead of using a fixed wait time, exponential backoff increases the wait duration with each consecutive rate limit:

```
1st rate limit → Wait 15 minutes
2nd rate limit → Wait 30 minutes (15m × 2¹)
3rd rate limit → Wait 60 minutes (15m × 2²)
4th rate limit → Wait 60 minutes (capped at maximum)
```

After a successful download, the counter resets to the base wait time.

### Configuration

```yaml
streamharvestarr:
    rate_limit_sleep: 900          # Base wait time (15 minutes)
    exponential_backoff: True      # Enable smart backoff
    backoff_multiplier: 2.0        # Double wait time each occurrence
    backoff_max: 3600              # Cap at 1 hour maximum
```

### Settings Explained

| Setting | Description | Effect |
|---------|-------------|--------|
| `rate_limit_sleep` | Base wait time in seconds | First rate limit waits this long |
| `exponential_backoff` | Enable/disable exponential increase | If false, always uses base wait time |
| `backoff_multiplier` | Growth factor | 2.0 = doubles, 1.5 = increases 50% |
| `backoff_max` | Maximum wait time | Prevents extremely long waits |

### Backoff Behavior Examples

**Conservative (slower growth):**
```yaml
backoff_multiplier: 1.5
rate_limit_sleep: 900
```

Result: 15m → 22.5m → 33.75m → 50.6m

**Aggressive (faster growth):**
```yaml
backoff_multiplier: 3.0
rate_limit_sleep: 600
```

Result: 10m → 30m → 90m (capped) → 90m (capped)

**Disable backoff (fixed time):**
```yaml
exponential_backoff: False
rate_limit_sleep: 1800
```

Result: 30m → 30m → 30m → 30m

## Configuration Examples

### Conservative (Recommended for Most Users)

Best for regular usage with occasional bulk downloads:

```yaml
streamharvestarr:
    scan_interval: 1
    download_delay: 5
    sleep_requests: 1
    rate_limit_sleep: 900
    exponential_backoff: True
    backoff_multiplier: 2.0
    backoff_max: 3600
```

**Characteristics:**
- Minimal delays during normal operation
- Smart recovery from rate limits
- Balances speed with reliability

### Aggressive (Fast Downloads)

For users who rarely hit rate limits and want maximum speed:

```yaml
streamharvestarr:
    scan_interval: 1
    download_delay: 2
    sleep_requests: 0
    rate_limit_sleep: 600
    exponential_backoff: True
    backoff_multiplier: 2.0
    backoff_max: 3600
```

**Characteristics:**
- Minimal preventive delays
- Faster but higher risk of rate limiting
- Quick recovery if rate limited

### Ultra-Safe (Bulk Downloads)

For catching up on many episodes or after previous rate limit issues:

```yaml
streamharvestarr:
    scan_interval: 1
    download_delay: 10
    sleep_requests: 3
    rate_limit_sleep: 1800
    exponential_backoff: True
    backoff_multiplier: 1.5
    backoff_max: 5400
```

**Characteristics:**
- Maximum preventive measures
- Significantly reduces rate limit risk
- Slower but extremely reliable
- Longer cooldown if rate limited

### Member/Premium Content

For channels with member-only or premium content that may have stricter limits:

```yaml
streamharvestarr:
    scan_interval: 1
    download_delay: 15
    sleep_requests: 5
    rate_limit_sleep: 1800
    exponential_backoff: True
    backoff_multiplier: 2.0
    backoff_max: 7200
```

**Characteristics:**
- Very conservative approach
- Respects platform limits for premium content
- Extended cooldown periods

## Monitoring and Logs

### Understanding Log Messages

**Normal operation:**
```
2025-11-29 10:30:15 - INFO - Downloaded - Episode Title
2025-11-29 10:30:20 - DEBUG - Waiting 5 seconds before next download
```

**Rate limit detected:**
```
2025-11-29 10:35:42 - ERROR - Failed - Episode Title - RATE LIMITED
2025-11-29 10:35:42 - WARNING - YouTube rate limit detected. Sleeping for 900 seconds...
2025-11-29 10:50:42 - INFO - Resuming downloads after rate limit cooldown
```

**Exponential backoff active:**
```
2025-11-29 11:05:15 - ERROR - Failed - Episode Title - RATE LIMITED (attempt 2)
2025-11-29 11:05:15 - WARNING - Exponential backoff: Sleeping for 1800 seconds (30m 0s)...
2025-11-29 11:35:15 - INFO - Resuming downloads after rate limit cooldown
```

**Recovery:**
```
2025-11-29 12:10:30 - INFO - Downloaded - Episode Title
2025-11-29 12:10:30 - INFO - Rate limit recovered - resetting backoff counter
```

### Checking Logs

View real-time logs:
```bash
docker logs -f stream-harvestarr
```

View log file:
```bash
tail -f /path/to/logs/stream-harvestarr.log
```

Search for rate limit issues:
```bash
grep "RATE LIMITED" /path/to/logs/stream-harvestarr.log
```

### What to Look For

**Healthy operation:**
- Regular "Downloaded" messages
- Occasional "Missing" for not-yet-released episodes
- No rate limit warnings

**Potential issues:**
- Multiple "RATE LIMITED" messages in succession
- Backoff attempts reaching maximum values
- Long gaps between successful downloads

## Best Practices

### Initial Setup

1. **Start conservative** - Use recommended settings first
2. **Monitor for 24-48 hours** - Check logs for rate limit issues
3. **Adjust gradually** - Reduce delays if no issues occur

### Bulk Catching Up

If catching up on many episodes:

1. **Enable ultra-safe configuration** before starting
2. **Monitor the first few downloads** closely
3. **Let it run unattended** once stable
4. **Return to normal config** after catching up

### After Rate Limiting

If you've been rate limited:

1. **Don't panic** - The backoff will handle it automatically
2. **Check your settings** - Ensure delays are configured
3. **Consider increasing delays** if it happens repeatedly
4. **Wait for recovery message** in logs before making changes

### Multiple Series Sources

If downloading from multiple platforms:

- Rate limits are typically **per-platform**
- YouTube rate limits don't affect other sites
- Each platform may have different tolerance levels
- Monitor logs to identify which platform is rate limiting

## Troubleshooting

### Still Getting Rate Limited?

If you're still experiencing rate limiting with recommended settings:

1. **Increase `sleep_requests`** to 3-5 seconds
2. **Increase `download_delay`** to 15-20 seconds
3. **Check your IP reputation** - Shared IPs (VPN, datacenter) may have stricter limits
4. **Verify cookies are valid** - Invalid auth may trigger rate limits
5. **Reduce `scan_interval`** - Less frequent scans = fewer requests

### Downloads Too Slow?

If downloads are taking too long:

1. **Reduce `download_delay`** incrementally (try 3, then 2 seconds)
2. **Reduce `sleep_requests`** (try 0)
3. **Monitor for rate limits** - If they occur, increase delays again
4. **Consider scheduling** - Download during off-peak hours

### Backoff Not Working?

If exponential backoff isn't triggering:

1. **Check `exponential_backoff: True`** is set
2. **Verify log messages** show backoff activation
3. **Ensure `rate_limit_sleep`** is reasonable (900+ seconds)
4. **Check YT-DLP version** - Update if outdated

## Related Pages

- [Configuration Guide](Configuration) - Full config reference
- [Troubleshooting](Troubleshooting) - Common issues and solutions
- [Advanced Features](Advanced-Features) - Additional configuration options
