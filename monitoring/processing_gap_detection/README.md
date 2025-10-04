# Processing Gap Detection System

**Status:** Phase 1 - Foundation Implementation  
**Current Coverage:** NBA.com Player List  
**Priority:** Medium-High (prevents data loss from silent failures)

---

## Overview

Monitors GCS scraped data files to ensure they've been processed into BigQuery. Detects and alerts when files exist in GCS but haven't been processed, indicating pub/sub failures, processor errors, or other pipeline issues.

### The Pipeline

```
Scraper → GCS File → Pub/Sub Message → Processor → BigQuery Table
```

### Failure Points Detected

1. **Scraper crashes** before sending pub/sub message
2. **Pub/sub delivery fails** (retry exhaustion, service outage)  
3. **Processor errors out** silently without alerting
4. **Network issues** prevent message delivery

---

## Quick Start

### Prerequisites

- Google Cloud project: `nba-props-platform`
- Service account: `nba-processors@nba-props-platform.iam.gserviceaccount.com`
- Permissions: Cloud Run, Cloud Scheduler, BigQuery, GCS read access
- Notification system configured (see `shared/utils/notification_system.py`)

### Installation

```bash
cd monitoring/processing_gap_detection

# Install dependencies
pip install -r requirements.txt

# Validate configuration
python config/processor_config.py

# Test locally
python processing_gap_monitor_job.py --date=2025-10-02
```

### Deployment

```bash
# Deploy to Cloud Run with automatic scheduling
./deploy.sh

# The script will:
# 1. Deploy Cloud Run job
# 2. Create Cloud Scheduler (season-aware schedule)
# 3. Configure automatic monitoring
```

---

## Architecture

### Directory Structure

```
monitoring/processing_gap_detection/
├── config/
│   └── processor_config.py         # Processor configurations
├── utils/
│   ├── gap_detector.py             # Core detection logic
│   └── gcs_inspector.py            # GCS file utilities
├── processing_gap_monitor_job.py   # Cloud Run job entry point
├── deploy.sh                       # Deployment script
├── job-config.env                  # Job configuration
├── requirements.txt                # Python dependencies
└── README.md                       # This file
```

### Components

#### 1. Processor Configuration (`config/processor_config.py`)

Central registry of all processors with monitoring parameters:

```python
'nbac_player_list': {
    'display_name': 'NBA.com Player List',
    'gcs_bucket': 'nba-scraped-data',
    'gcs_pattern': 'nba-com/player-list/{date}/',
    'bigquery_table': 'nba_raw.nbac_player_list_current',
    'source_file_field': 'source_file_path',
    'tolerance_hours': 6,
    'enabled': True
}
```

#### 2. GCS Inspector (`utils/gcs_inspector.py`)

Utilities for inspecting GCS buckets:
- Find latest file for a date
- Get all files matching pattern
- Check file existence
- Get file metadata

#### 3. Gap Detector (`utils/gap_detector.py`)

Core detection logic:
- Compares GCS files against BigQuery records
- Checks time-based tolerance
- Validates record counts
- Sends alerts via notification system
- Logs retry information for future auto-retry

#### 4. Cloud Run Job (`processing_gap_monitor_job.py`)

Entry point for scheduled execution:
- Parses command line arguments
- Runs gap detection for specified dates
- Outputs results (text or JSON)
- Returns appropriate exit codes

---

## Usage

### Scheduled Execution (Automatic)

The job runs automatically via Cloud Scheduler:

**During Season (Oct-Jun):**
- Hourly from 10 AM - 6 PM PT
- Checks today's processing

**Offseason (Jul-Sep):**
- Twice daily: 11 AM PT, 5 PM PT
- Reduced frequency

### Manual Execution

```bash
# Check today's processing
gcloud run jobs execute processing-gap-monitor \
  --region=us-west2 \
  --project=nba-props-platform

# Check specific date
gcloud run jobs execute processing-gap-monitor \
  --region=us-west2 \
  --args="--date=2025-10-02"

# Check multiple days
gcloud run jobs execute processing-gap-monitor \
  --region=us-west2 \
  --args="--lookback-days=7"

# Check specific processors only
gcloud run jobs execute processing-gap-monitor \
  --region=us-west2 \
  --args="--processors=nbac_player_list"

# Dry run (no alerts)
gcloud run jobs execute processing-gap-monitor \
  --region=us-west2 \
  --args="--dry-run"

# JSON output for programmatic use
gcloud run jobs execute processing-gap-monitor \
  --region=us-west2 \
  --args="--json-output"
```

### Local Testing

```bash
# Test with today's date
python processing_gap_monitor_job.py

# Test with specific date
python processing_gap_monitor_job.py --date=2025-10-02

# Test specific processors
python processing_gap_monitor_job.py --processors=nbac_player_list

# Dry run (suppress alerts)
python processing_gap_monitor_job.py --dry-run --lookback-days=7
```

---

## Monitoring & Alerts

### Alert Flow

When a gap is detected:

1. **Individual Alert** sent via notification system:
   - Level: ERROR
   - Channels: Email + Slack (configurable)
   - Details: File path, timestamp, tolerance exceeded
   - **Retry Info:** Pub/Sub topic and message attributes logged

2. **Summary Alert** if multiple gaps found:
   - Level: WARNING
   - Shows count and affected processors
   - Highlights high-priority/revenue-impacting gaps

3. **Success Notification** when no gaps found:
   - Level: INFO
   - Confirms monitoring completed successfully
   - Lists processors checked

### Example Alert

```
🚨 Processing Gap Detected: NBA.com Player List

GCS file exists but not processed in BigQuery after 8.3 hours

Details:
- Processor: nbac_player_list
- GCS File: gs://nba-scraped-data/nba-com/player-list/2025-10-02/1234567890.json
- Created: 2025-10-02T08:00:00Z
- Hours Since: 8.3
- Table: nba-props-platform.nba_raw.nbac_player_list_current
- Tolerance: 6 hours
- Priority: high
- Revenue Impact: YES

Retry Info:
- Pub/Sub Topic: nba-data-processing
- Attributes: {'processor': 'nbac_player_list', 'file_path': '...', 'retry': 'true'}

Action: Investigate processor logs and consider manual retry
```

---

## Configuration

### Processor Configuration

To add a new processor to monitoring, edit `config/processor_config.py`:

```python
'new_processor_name': {
    'display_name': 'Human Readable Name',
    'gcs_bucket': 'nba-scraped-data',
    'gcs_pattern': 'source/data/{date}/',
    'bigquery_dataset': 'nba_raw',
    'bigquery_table': 'table_name',
    'source_file_field': 'source_file_path',
    'tolerance_hours': 6,
    'enabled': True,
    
    # Optional validations
    'expected_record_count': {'min': 100, 'max': 1000},
    
    # For Phase 2 retries
    'pubsub_topic': 'nba-data-processing',
    'pubsub_attributes': {'processor': 'new_processor'},
    
    # Metadata
    'priority': 'high',  # high, medium, low
    'revenue_impact': True
}
```

### Notification Configuration

Notifications use `shared/utils/notification_system.py`. Configure via environment variables:

```bash
# Email
EMAIL_ALERTS_ENABLED=true
EMAIL_ALERTS_TO=alerts@example.com
EMAIL_CRITICAL_TO=critical@example.com

# Slack
SLACK_ALERTS_ENABLED=true
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_WEBHOOK_URL_ERROR=https://hooks.slack.com/services/...

# Discord (alternative)
DISCORD_ALERTS_ENABLED=false
DISCORD_WEBHOOK_URL_CRITICAL=https://discord.com/api/webhooks/...
```

---

## Phase 1 Implementation Details

### Current Coverage

**Processor:** NBA.com Player List (`nbac_player_list`)

**Why This Processor First?**
- Simple: 1 file per day, current-state only
- Critical: Foundation for player lookups across system
- Clean test case: MERGE_UPDATE strategy is straightforward
- High visibility: ~600 players, easy to validate

**Detection Logic:**
1. Check if GCS file exists for target date
2. Query BigQuery for records with that `source_file_path`
3. Validate record count (500-700 expected)
4. If file exists but no records AND tolerance exceeded → Alert
5. Log retry pub/sub message structure

**Tolerance:** 6 hours
- Scraper runs in morning operations workflow
- Allows time for normal processing delays
- Alerts only if truly stuck

### What's NOT Included in Phase 1

- ❌ Automatic retries (logged only)
- ❌ Scraper failure detection (assumes scraper succeeded if file exists)
- ❌ Performance monitoring (slow runs, high error rates)
- ❌ Data quality validation beyond record counts
- ❌ Multiple processors (just nbac_player_list)
- ❌ Real-time monitoring (scheduled checks only)

---

## Future Phases

### Phase 2: Auto-Retry & Multi-Processor

**Goals:**
- Automatic retry via pub/sub for common errors
- Expand to 5-10 high-priority processors
- Configurable retry policies

**Implementation:**
- Read retry config from processor config
- Publish pub/sub message when gap detected + retry allowed
- Track retry attempts in BigQuery
- Escalate to manual after N retries

**Processors to Add:**
- `br_roster` - Basketball Reference rosters
- `nbac_schedule` - NBA.com schedule
- `odds_api_props` - Odds API props (revenue critical)
- `bdl_player_boxscores` - Ball Don't Lie box scores
- `nbac_gamebook` - NBA.com gamebooks

### Phase 3: Comprehensive Monitoring

**Goals:**
- Scraper success/failure monitoring
- Performance tracking (processing time, error rates)
- Data quality validation (schema, nulls, ranges)
- Real-time alerting via Cloud Functions

**Implementation:**
- Cloud Function triggered on GCS file creation
- Track scraper runs in monitoring table
- Dashboard for system health
- SLA tracking and reporting

---

## Troubleshooting

### Gap Detected But File Was Processed

**Cause:** `source_file_path` field doesn't match GCS path exactly

**Fix:**
1. Check BigQuery for similar paths: `SELECT DISTINCT source_file_path FROM table WHERE DATE(processed_at) = '2025-10-02'`
2. Verify processor writes correct path format
3. Check for typos in `source_file_field` in config

### No Gaps Detected But Processing Failed

**Cause:** Tolerance too long, or processor enabled incorrectly

**Fix:**
1. Reduce `tolerance_hours` in config if too permissive
2. Verify `enabled: True` for processor
3. Check if file actually exists in GCS for that date

### Monitor Job Timing Out

**Cause:** Too many processors or lookback days

**Fix:**
1. Reduce `--lookback-days`
2. Increase `TIMEOUT` in `job-config.env`
3. Check for processors with slow BigQuery queries

### Alerts Not Sending

**Cause:** Notification system not configured

**Fix:**
1. Verify environment variables set correctly
2. Check service account has permissions
3. Test notification system: `python -c "from shared.utils.notification_system import notify_info; notify_info('Test', 'Test message')"`

---

## Logs & Monitoring

### View Logs

```bash
# Recent logs
gcloud logging read "resource.type=cloud_run_job \
  AND resource.labels.job_name=processing-gap-monitor" \
  --limit=50 \
  --project=nba-props-platform \
  --format=json

# Filter by severity
gcloud logging read "resource.type=cloud_run_job \
  AND resource.labels.job_name=processing-gap-monitor \
  AND severity>=WARNING" \
  --limit=20

# Specific date
gcloud logging read "resource.type=cloud_run_job \
  AND resource.labels.job_name=processing-gap-monitor \
  AND timestamp>='2025-10-02T00:00:00Z'" \
  --limit=100
```

### Key Log Messages

Look for these patterns:

```
✅ No processing gaps detected for 2025-10-02
⚠️ Processing gap detected: nbac_player_list
❌ Error checking processor: <name>
🔍 DRY RUN MODE: Alerts will be suppressed
RETRY INFO for nbac_player_list: Pub/Sub topic=...
```

---

## Testing

### Unit Tests (Future)

```bash
# Run all tests
pytest tests/

# Specific test
pytest tests/test_gap_detector.py -v

# With coverage
pytest --cov=utils --cov-report=html
```

### Integration Testing

```bash
# Test with known gap (should alert)
python processing_gap_monitor_job.py --date=2025-09-15 --dry-run

# Test with known success (should pass)
python processing_gap_monitor_job.py --date=2025-08-31

# Test multiple days
python processing_gap_monitor_job.py --lookback-days=7 --dry-run
```

---

## Best Practices

### When Adding New Processors

1. **Start disabled:** Set `enabled: False` initially
2. **Test locally:** Run with `--dry-run` for the processor
3. **Validate tolerance:** Ensure hours match scraper schedule
4. **Check BigQuery field:** Verify `source_file_field` exists
5. **Set expectations:** Add `expected_record_count` if applicable
6. **Document priority:** Mark revenue-impacting processors
7. **Enable gradually:** Enable in production, monitor for false alerts

### Monitoring the Monitor

The monitoring system itself needs monitoring:

1. **Cloud Monitoring Alert:** If job hasn't run in 25 hours
2. **Dashboard:** Track gaps found per day, processor reliability
3. **Weekly Review:** Check for false positives, adjust tolerances

---

## Related Documentation

- [Processor Reference](../../docs/processors_reference.md)
- [Notification System](../../shared/utils/notification_system.py)
- [Backfill Jobs](../../backfill_jobs/)

---

## Support

**Questions?** Check the troubleshooting section above.

**Found a bug?** Check logs first, then report with:
- Date checked
- Processor name  
- Expected vs actual behavior
- Relevant log snippets

**Feature requests?** Consider which phase (2 or 3) aligns best.

---

**Last Updated:** 2025-10-03  
**Phase:** 1 - Foundation  
**Status:** Production Ready (Single Processor)