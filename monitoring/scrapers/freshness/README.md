# Scraper Freshness Monitoring System

**Location:** `monitoring/scrapers/freshness/`

## Overview

Monitors the freshness and availability of scraped data files in Google Cloud Storage. Ensures all scrapers are running on schedule and producing valid output files.

## Features

- ✅ **GCS-Based Monitoring** - Checks file existence, age, and size
- ✅ **Schedule-Aware** - Knows when each scraper should run
- ✅ **Season-Aware** - Adjusts thresholds based on NBA season phase
- ✅ **Game-Day Aware** - Only checks game-dependent scrapers when games are scheduled
- ✅ **Multi-Channel Alerts** - Integrates with existing Slack/Email notification system
- ✅ **No Database Dependencies** - Pure GCS inspection, no processor coupling

## Architecture

```
Cloud Scheduler (hourly)
    ↓
Cloud Run Job (scheduled_monitor.py)
    ↓
Freshness Checker (checks GCS files)
    ↓
Season Manager (adjusts thresholds)
    ↓
Alert Formatter (formats results)
    ↓
Notification System (Slack/Email)
```

## Configuration

All scraper monitoring is defined in `config/monitoring_config.yaml`:

```yaml
scrapers:
  nbacom_player_list:
    enabled: true
    gcs:
      bucket: "nba-raw-data"
      path_pattern: "nba-com/player-list/{date}/*.json"
    schedule:
      cron: "0 6 * * *"  # Daily at 6 AM ET
    freshness:
      max_age_hours:
        regular_season: 24
        preseason: 48
        playoffs: 12
        offseason: 168
    validation:
      min_file_size_mb: 0.1
    seasonality:
      active_during: ["regular_season", "preseason", "playoffs"]
      requires_games_today: false
```

## Quick Start

### 1. Configure Environment

```bash
cd monitoring/scrapers/freshness
cp .env.example .env
# Edit .env with your settings
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Test Locally

```bash
# Dry run (no alerts sent)
python runners/scheduled_monitor.py --dry-run

# Test with alerts
python runners/scheduled_monitor.py --test
```

### 4. Deploy to Cloud Run

```bash
./deploy.sh
```

### 5. Set Up Cloud Scheduler

```bash
./setup-scheduler.sh
```

## Configuration Guide

### Adding a New Scraper

Add to `config/monitoring_config.yaml`:

```yaml
scrapers:
  my_new_scraper:
    enabled: true
    description: "Description of what this scraper does"
    
    gcs:
      bucket: "nba-raw-data"
      path_pattern: "my-source/data/{date}/*.json"
    
    schedule:
      cron: "0 */6 * * *"  # Every 6 hours
      timezone: "America/New_York"
    
    freshness:
      max_age_hours:
        regular_season: 8
        playoffs: 4
    
    validation:
      min_file_size_mb: 0.01
      max_file_size_mb: 100.0
    
    seasonality:
      active_during: ["regular_season", "playoffs"]
      requires_games_today: true  # Only check on game days
    
    alerting:
      severity_missing: "critical"
      severity_stale: "warning"
```

### Path Pattern Variables

Supported variables in `path_pattern`:
- `{date}` - YYYY-MM-DD format
- `{timestamp}` - YYYYMMDDHHmmss format
- `{hour}` - HH format (00-23)
- `{game_id}` - Game ID (if applicable)

### Season Phases

Defined in `config/nba_schedule_config.yaml`:

- **Offseason** - June 15 - Sept 30
- **Preseason** - Oct 1 - Oct 21
- **Regular Season** - Oct 22 - Apr 13
- **Playoffs** - Apr 14 - Jun 20

Freshness thresholds automatically adjust based on current phase.

## Monitoring Schedule

Default: Runs every hour via Cloud Scheduler

Recommended schedule:
- **6:00 AM** - Check overnight scrapes
- **9:00 AM** - Check daily morning scrapes
- **Every hour** - Continuous monitoring during day
- **11:00 PM** - Check post-game scrapes

Edit Cloud Scheduler job to change frequency.

## Alert Severity Levels

**CRITICAL** 🔴
- File missing and scraper should have run
- Data is >48 hours stale during season
- File size is 0 bytes
- Action: Immediate investigation required

**WARNING** 🟡
- File is 24-48 hours old
- File size is suspiciously small
- Expected multiple files, got fewer
- Action: Check within 24 hours

**INFO** 🔵
- All checks passed
- No files expected (offseason, no games)
- Action: None required

## Integration with Existing Systems

### Notification System

Uses your existing notification system:
```python
from shared.utils.notification_system import notify_error, notify_warning, notify_info
```

Alerts are routed based on severity:
- **CRITICAL/ERROR** → Slack (#nba-alerts-critical) + Email
- **WARNING** → Slack (#nba-alerts)
- **INFO** → Logs only

### GCS Path Builder

Integrates with `scrapers.utils.gcs_path_builder`:
```python
from scrapers.utils.gcs_path_builder import GCSPathBuilder
```

Automatically uses correct paths for each scraper.

### Ball Don't Lie API

Fetches daily NBA schedule to determine game days:
```python
from monitoring.scrapers.freshness.utils.nba_schedule_api import has_games_today
```

## Troubleshooting

### No Alerts Received

1. Check notification system environment variables:
   ```bash
   gcloud run jobs describe freshness-monitor \
     --region=us-west2 \
     --format='value(template.template.containers[0].env)'
   ```

2. Check Cloud Run logs:
   ```bash
   gcloud logging read "resource.type=cloud_run_job \
     AND resource.labels.job_name=freshness-monitor" \
     --limit=50 \
     --format=json
   ```

3. Test notifications locally:
   ```bash
   python runners/scheduled_monitor.py --test
   ```

### False Positives

If getting alerts for scrapers that shouldn't run:

1. Check `seasonality.active_during` in config
2. Set `requires_games_today: true` for game-dependent scrapers
3. Adjust `max_age_hours` thresholds

### Missing Files Not Detected

1. Verify `path_pattern` matches actual GCS structure
2. Check `schedule.cron` matches scraper schedule
3. Ensure scraper is `enabled: true`

## Files Reference

```
monitoring/scrapers/freshness/
├── config/
│   ├── monitoring_config.yaml      # Scraper definitions
│   └── nba_schedule_config.yaml    # Season phases
├── core/
│   ├── freshness_checker.py        # Main checking logic
│   └── season_manager.py           # Season awareness
├── runners/
│   └── scheduled_monitor.py        # Cloud Run entry point
├── utils/
│   ├── nba_schedule_api.py         # Fetch game schedule
│   └── alert_formatter.py          # Format alerts
├── tests/
│   └── test_freshness_checker.py   # Unit tests
├── requirements.txt
├── deploy.sh                       # Deploy to Cloud Run
├── setup-scheduler.sh              # Configure Cloud Scheduler
└── README.md                       # This file
```

## Cloud Resources

**Cloud Run Job:**
- Name: `freshness-monitor`
- Region: `us-west2`
- Memory: 512 MB
- Timeout: 5 minutes
- Cost: ~$5-10/month

**Cloud Scheduler:**
- Name: `freshness-monitor-hourly`
- Schedule: `0 * * * *` (every hour)
- Cost: Free (included in free tier)

## Maintenance

### Weekly Tasks
- Review alert trends
- Adjust thresholds if needed
- Update scraper schedules in config

### Monthly Tasks
- Review Cloud Run costs
- Update season dates before new season
- Test notification system

### Before Each Season
- Update `nba_schedule_config.yaml` with new dates
- Verify all scraper configurations
- Test end-to-end with dry-run

## Support

For issues or questions:
1. Check Cloud Run logs
2. Review this README
3. Check notification system documentation
4. Review scraper-specific GCS paths

## Future Enhancements

Potential additions (not implemented yet):
- [ ] Baseline tracking for anomaly detection
- [ ] GCS trigger-based immediate validation
- [ ] Looker Studio dashboard
- [ ] Automated scraper recovery
- [ ] Historical trend analysis
