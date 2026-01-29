# Monitoring Setup

## Monitoring Scripts

### Scraper Failure Cleanup (`cleanup_scraper_failures.py`)

Automatically cleans up scraper failures that have been successfully backfilled.

**Purpose**: The scraper_failures table tracks scraper failures for automatic recovery. This script verifies if data has been successfully backfilled and marks those failures as completed, preventing false alerts and unnecessary backfill attempts.

**Usage**:
```bash
# Test mode - see what would be cleaned up
python bin/monitoring/cleanup_scraper_failures.py --dry-run

# Production mode - actually mark as backfilled
python bin/monitoring/cleanup_scraper_failures.py

# Look back 14 days
python bin/monitoring/cleanup_scraper_failures.py --days-back=14

# Clean up specific scraper only
python bin/monitoring/cleanup_scraper_failures.py --scraper=bdb_pbp_scraper

# Or use the shell wrapper
./bin/monitoring/cleanup_scraper_failures.sh --dry-run
```

**What it does**:
1. Queries scraper_failures where backfilled=FALSE
2. For each failure, checks if data exists in the corresponding BigQuery table
3. If data exists, marks the failure as backfilled=TRUE
4. Handles postponed games (all games on a date postponed = auto-mark backfilled)
5. Reports still-missing data for manual investigation

**Supported scrapers**:
- `nbac_play_by_play` - NBA.com play-by-play data
- `nbac_player_boxscore` - NBA.com player boxscores
- `nbac_team_boxscore` - NBA.com team boxscores
- `bdl_boxscores` - BallDontLie boxscores
- `bdb_pbp_scraper` - BigDataBall play-by-play
- `nbac_scoreboard_v2` - NBA.com scoreboard
- `nbac_injury_report` - NBA.com injury report
- `nbac_gamebook` - NBA.com gamebook PDFs
- `bdl_injuries` - BallDontLie injuries

**Example output**:
```
Processing 5 unbackfilled failures...
================================================================================

Checking bdb_pbp_scraper / 2026-01-26:
  Error: ValueError
  Retries: 168
  Last failed: 2026-01-27 03:06:08+00:00
  ✅ Data exists (4100 records) - marking as backfilled
✅ Marked as backfilled: bdb_pbp_scraper / 2026-01-26

Checking nbac_play_by_play / 2026-01-25:
  Error: DownloadDecodeMaxRetryException
  Retries: 53
  Last failed: 2026-01-26 10:02:38+00:00
  ❌ Data still missing (6 games finished)

================================================================================
CLEANUP SUMMARY
================================================================================
Total failures checked:       5
  ✅ Data exists:             2
  📅 All games postponed:     0
  ❌ Still missing data:      3
  ⚠️  Errors:                  0

✅ Marked 2 failures as backfilled
```

**When to run**:
- Daily after backfill operations complete
- After manually backfilling data
- When investigating scraper gap alerts
- As part of weekly maintenance

**Related systems**:
- Uses table mappings in `SCRAPER_TABLE_MAP` to verify data
- Works with `scraper_gap_backfiller` Cloud Function
- Reduces false positives in gap alerting

---

## Alert Policies

Configure these alerts in Cloud Console:

1. **Health Check Failures**
   - Metric: `run.googleapis.com/request_count`
   - Filter: `response_code_class="5xx" AND path="/ready"`
   - Threshold: >5 errors in 5 minutes
   - Notification: Slack + Email

2. **Deployment Failures**
   - Metric: `run.googleapis.com/request_count`
   - Filter: `response_code_class="5xx"`
   - Threshold: >10 errors in 1 minute (spike detection)
   - Notification: Slack + Email

3. **Error Rate**
   - Metric: `logging.googleapis.com/log_entry_count`
   - Filter: `severity>=ERROR`
   - Threshold: >5 errors in 5 minutes
   - Notification: Slack

## Dashboards

Create dashboard with:
- Health check success rate by service
- Deployment frequency
- Error rate trends
- Response time p50/p95/p99

## Commands

```bash
# List existing alert policies
gcloud alpha monitoring policies list --project=nba-props-platform

# Create notification channel
gcloud alpha monitoring channels create \
  --display-name="Slack Alerts" \
  --type=slack \
  --project=nba-props-platform

# Get notification channel ID
gcloud alpha monitoring channels list --project=nba-props-platform
```
