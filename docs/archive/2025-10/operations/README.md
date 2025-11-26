# Operations Documentation

For detailed operational guides, see the **[Wiki](https://your-wiki-url)**.

## Quick Links to Wiki

- **[Workflow Monitoring Guide](https://your-wiki-url/monitoring)** - Daily monitoring procedures
- **[Troubleshooting Guide](https://your-wiki-url/troubleshooting)** - Common issues and fixes
- **[System Overview](https://your-wiki-url/overview)** - How the system works
- **[Runbooks](https://your-wiki-url/runbooks)** - Step-by-step procedures

## Monitoring Tools

### nba-monitor (Main Tool)

Daily status check:
```bash
nba-monitor status yesterday
```

View errors:
```bash
nba-monitor errors 24
```

View workflows:
```bash
nba-monitor workflows
```

**Installation:**
```bash
chmod +x monitoring/scripts/nba-monitor
export PATH="$PATH:$(pwd)/monitoring/scripts"
```

**Full documentation:** [../monitoring/scripts/README.md](../../monitoring/scripts/README.md)

### Other Tools

- **check-scrapers.py** - Simple status checker
- **workflow_monitoring.py** - Python library for custom monitoring
- See [../../monitoring/scripts/README.md](../../monitoring/scripts/README.md) for all tools

## Local Operational Docs

- **[monitoring-setup.md](monitoring-setup.md)** - How to set up monitoring tools

## Related

- **[../../shared/utils/README.md](../../shared/utils/README.md)** - Shared utilities documentation
- **[../../monitoring/scripts/README.md](../../monitoring/scripts/README.md)** - Monitoring tools documentation
