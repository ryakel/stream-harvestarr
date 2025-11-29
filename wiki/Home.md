# Stream Harvestarr Documentation

Welcome to the Stream Harvestarr documentation. This wiki provides comprehensive guides for configuring and using Stream Harvestarr with Sonarr and YT-DLP.

## Quick Links

- [Getting Started](#getting-started)
- [Upgrading Guide](Upgrading)
- [Configuration Guide](Configuration)
- [Rate Limiting & Performance](Rate-Limiting)
- [Troubleshooting](Troubleshooting)
- [Advanced Features](Advanced-Features)

## Getting Started

Stream Harvestarr is a Sonarr companion script that automatically downloads web series from supported streaming sites using YT-DLP. It monitors your Sonarr library and downloads episodes as they become available.

### Prerequisites

Before using Stream Harvestarr, you need:

1. **Docker** - Container runtime
2. **Sonarr** - TV series management (v3 or v4)
3. **Web series available on supported sites** - See [YT-DLP supported sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)

### Basic Setup

1. **Deploy the container** using Docker or Docker Compose (see main README)
2. **Configure your volumes** - Map config, logs, and Sonarr root directories
3. **Copy the config template** - `cp config.yml.template config.yml`
4. **Edit configuration** - Add your Sonarr details and series
5. **Start the container** - Stream Harvestarr will begin monitoring

## Documentation Sections

### [Upgrading Guide](Upgrading)

Upgrading to the latest version:
- Backward compatibility guarantee
- Latest features and improvements
- Step-by-step upgrade process
- Post-upgrade configuration
- Troubleshooting upgrades

### [Configuration Guide](Configuration)

Complete reference for all configuration options including:
- Sonarr connection settings
- YT-DLP download options
- Rate limiting configuration
- Per-series customization
- Cookie authentication

### [Rate Limiting & Performance](Rate-Limiting)

Handling YouTube and other site rate limits:
- Understanding rate limits
- Preventive measures
- Exponential backoff
- Optimal configuration for bulk downloads

### [Troubleshooting](Troubleshooting)

Common issues and solutions:
- Rate limit errors
- Connection problems
- Download failures
- TVDB matching issues

### [Advanced Features](Advanced-Features)

Advanced configuration options:
- Custom video formats
- Subtitle handling
- Time offsets for early releases
- Regex title matching
- Cookie-based authentication

## Getting Help

If you encounter issues not covered in this documentation:

1. Check the [Troubleshooting](Troubleshooting) guide
2. Review container logs in your `/logs` volume
3. Open an issue on [GitHub](https://github.com/ryakel/stream-harvestarr/issues)

## Contributing

Found an error in the documentation or want to improve it? Contributions are welcome! The documentation source files are in the `wiki/` directory of the main repository.
