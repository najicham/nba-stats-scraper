# Monitoring Setup

How to set up monitoring tools for the NBA Props Platform.

**Last Updated:** $(date +%Y-%m-%d)

## Installation

```bash
# From repo root
chmod +x monitoring/scripts/nba-monitor
chmod +x monitoring/scripts/check-scrapers.py

# Add to PATH
export PATH="$PATH:$(pwd)/monitoring/scripts"

# Or create symlink
sudo ln -s $(pwd)/monitoring/scripts/nba-monitor /usr/local/bin/nba-monitor
```

## Usage

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

## Daily Routine

Every morning at 9am:
```bash
# 1. Check yesterday's status
nba-monitor status yesterday

# 2. If errors, investigate
nba-monitor errors 24

# 3. Check specific workflow if needed
gcloud workflows executions list morning-operations --location=us-west2 --limit=3
```

## Full Documentation

See [../../monitoring/scripts/README.md](../../monitoring/scripts/README.md) for:
- All available commands
- Integration with existing systems
- Advanced usage

## Related

- [Wiki: Monitoring Guide](https://your-wiki-url/monitoring) - Complete monitoring procedures
- [Wiki: Troubleshooting](https://your-wiki-url/troubleshooting) - How to fix common issues
