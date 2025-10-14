# NBA.com Player Movement - Daily Operations & Monitoring Guide

**Document Version:** 1.0  
**Last Updated:** October 13, 2025  
**For:** Production Operations During NBA Season  
**Table:** `nba-props-platform.nba_raw.nbac_player_movement`

---

## Table of Contents

1. [Overview & Seasonal Context](#overview--seasonal-context)
2. [Daily Validation Workflows](#daily-validation-workflows)
3. [Freshness Monitoring Strategy](#freshness-monitoring-strategy)
4. [Processor Run Tracking Architecture](#processor-run-tracking-architecture)
5. [Automated Monitoring Setup](#automated-monitoring-setup)
6. [Alert Thresholds by Season](#alert-thresholds-by-season)
7. [Troubleshooting Guide](#troubleshooting-guide)

---

## Overview & Seasonal Context

### The Challenge: Cumulative Data Sources

NBA.com Player Movement is a **cumulative data source** - one JSON file contains 10+ years of transaction history. This creates unique monitoring challenges:

**Problem:** Can't distinguish "scraper failed" from "no new transactions today"
- ✅ Scraper runs successfully but finds 0 new transactions = **NORMAL**
- ❌ Scraper fails to run = **CRITICAL**
- Both scenarios result in: No new records in BigQuery

**Solution:** Context-aware monitoring that considers seasonal patterns and tracks processor execution metadata.

### Seasonal Transaction Patterns

Transaction volumes vary dramatically by NBA calendar period. Your monitoring must account for this:

| Season Period | Months | Expected Activity | Alert Threshold | Notes |
|---------------|--------|-------------------|-----------------|-------|
| **Free Agency** | Jul-Aug | 🔥 30-50 txns/day | 3 days | Peak activity, expect daily updates |
| **Pre-Season** | Sep-Oct | 🟡 5-10 txns/day | 7 days | Roster finalizing, moderate activity |
| **Regular Season** | Nov-Apr | 🟢 2-5 txns/week | 14 days | Low activity is NORMAL |
| **Trade Deadline** | Early Feb | 🔥 10-20 txns/day | 3 days | Brief spike around deadline |
| **Playoffs** | May-Jun | 🟢 1-3 txns/month | 30 days | Minimal activity is NORMAL |
| **Off-Season** | Jun-Jul | ⚪ 0-5 txns/week | 30 days | Quiet period before free agency |

**Key Insight:** A 7-day gap between transactions is:
- 🔴 **CRITICAL** during Free Agency (should be daily)
- 🟢 **NORMAL** during Playoffs (expected quiet period)

---

## Daily Validation Workflows

### Morning Health Check (Every Day at 9am)

**Purpose:** Verify scraper ran and data is fresh  
**Duration:** ~2 minutes  
**Required During:** All NBA calendar periods

```bash
#!/bin/bash
# File: scripts/morning-health-check

echo "=== NBA Player Movement - Morning Health Check ==="
echo "Date: $(date)"
echo ""

# 1. Check scraper freshness (with seasonal context)
echo "🔍 Checking scraper freshness..."
./scripts/validate-player-movement freshness

echo ""

# 2. Check for recent activity (last 30 days)
echo "📊 Checking recent activity..."
./scripts/validate-player-movement recent

echo ""
echo "✅ Morning health check complete!"
```

**Expected Results:**
- **During Active Periods (Jul-Aug, Feb):** ✅ Recent activity, scraper ran <24h ago
- **During Quiet Periods (May-Jun, Nov-Apr):** ⚪ No recent activity, scraper health OK

**Action Required If:**
- 🔴 Scraper hasn't run in 48+ hours → Investigate scraper logs
- ⚠️ Old data during Free Agency → Re-run scraper manually

### Weekly Data Quality Check (Every Monday)

**Purpose:** Ensure data integrity and completeness  
**Duration:** ~5 minutes  
**Required During:** NBA season (Oct-Jun)

```bash
#!/bin/bash
# File: scripts/weekly-quality-check

echo "=== Weekly Data Quality Check ==="
date
echo ""

# 1. Data quality checks (NULLs, duplicates, flags)
echo "🔍 Running quality checks..."
./scripts/validate-player-movement quality

echo ""

# 2. Trade validation (orphaned parts)
echo "🔄 Validating trades..."
./scripts/validate-player-movement trades

echo ""

# 3. All teams active
echo "🏀 Checking all 30 teams..."
./scripts/validate-player-movement teams

echo ""

# 4. Transaction type distribution
echo "📈 Checking transaction distribution..."
./scripts/validate-player-movement distribution

echo ""
echo "✅ Weekly quality check complete!"
```

**Action Required If:**
- 🔴 New duplicates detected (>18 records) → Run deduplication script
- ⚠️ Orphaned trades increased (>25) → Investigate recent trades
- ⚠️ Team missing from current season → Check team roster changes
- ⚠️ Transaction distribution off (>10% variance) → Verify source data

### Monthly Completeness Audit (First Monday of Month)

**Purpose:** Comprehensive historical data validation  
**Duration:** ~10 minutes  
**Required During:** Year-round

```bash
#!/bin/bash
# File: scripts/monthly-completeness-audit

echo "=== Monthly Completeness Audit ==="
date
echo ""

# Run all validation queries
./scripts/validate-player-movement all

echo ""

# Export results to CSV for archival
REPORT_DATE=$(date +%Y%m%d)
echo "📊 Exporting audit results..."

./scripts/validate-player-movement completeness --csv > \
  "reports/monthly_audits/completeness_$REPORT_DATE.csv"

./scripts/validate-player-movement quality --csv > \
  "reports/monthly_audits/quality_$REPORT_DATE.csv"

echo ""
echo "✅ Monthly audit complete! Reports saved to reports/monthly_audits/"
```

**Action Required If:**
- Missing season data → Run backfill processor
- Significant data quality degradation → Investigate processor changes
- Transaction counts declining → Check scraper configuration

### Post-Backfill Validation

**Purpose:** Verify backfill completed successfully  
**Duration:** ~3 minutes  
**Required:** After any historical data backfill

```bash
#!/bin/bash
# File: scripts/post-backfill-validation

BACKFILL_START_DATE=$1
BACKFILL_END_DATE=$2

echo "=== Post-Backfill Validation ==="
echo "Date Range: $BACKFILL_START_DATE to $BACKFILL_END_DATE"
echo ""

# 1. Check season completeness
echo "✓ Checking season completeness..."
./scripts/validate-player-movement completeness

# 2. Check for duplicates (common after backfills)
echo "✓ Checking for duplicates..."
./scripts/validate-player-movement quality

# 3. Verify date range coverage
echo "✓ Verifying date range coverage..."
bq query --use_legacy_sql=false "
SELECT 
  MIN(transaction_date) as earliest,
  MAX(transaction_date) as latest,
  COUNT(*) as total_records,
  COUNT(DISTINCT transaction_date) as unique_dates
FROM \`nba-props-platform.nba_raw.nbac_player_movement\`
WHERE transaction_date BETWEEN '$BACKFILL_START_DATE' AND '$BACKFILL_END_DATE'
"

echo ""
echo "✅ Post-backfill validation complete!"
```

---

## Freshness Monitoring Strategy

### The "Silent Success" Problem

**Challenge:** How do you monitor a cumulative data source where "0 new records" is often normal?

**Traditional Approach (Doesn't Work):**
```python
# ❌ NAIVE APPROACH - False alarms constantly
if hours_since_last_insert > 24:
    alert("No new data in 24 hours!")
    # Problem: This fires during Playoffs when no transactions is EXPECTED
```

**Smart Approach (Context-Aware):**
```python
# ✅ CONTEXT-AWARE APPROACH
season_period = get_current_season_period()  # Free Agency, Playoffs, etc.
alert_threshold = THRESHOLDS[season_period]  # 3 days vs 30 days

if hours_since_last_insert > alert_threshold:
    if season_period in ['Free Agency', 'Trade Deadline']:
        alert_level = "CRITICAL"  # Should be daily activity
    else:
        alert_level = "WARNING"   # Worth checking but may be normal
```

This is implemented in `scraper_freshness_check.sql` - it considers seasonal context when determining if data is stale.

### Three-Tier Monitoring Strategy

#### Tier 1: Data Timestamp Monitoring ⭐ **Already Implemented**

**What:** Track timestamps in the data itself  
**Tables:** `nba_raw.nbac_player_movement` has 3 timestamps:
- `transaction_date` - When the transaction occurred (from NBA.com)
- `scrape_timestamp` - When scraper retrieved the data
- `created_at` - When BigQuery record was inserted

**Implementation:** `scraper_freshness_check.sql` query

**Pros:**
- ✅ Easy to implement (already done)
- ✅ Works with existing data
- ✅ Seasonal context aware

**Cons:**
- ❌ Can't distinguish scraper failure from "no new data"
- ❌ No visibility into failed processor runs

**Recommendation:** Use as first line of defense ✓

#### Tier 2: Processor Run Tracking ⭐ **RECOMMENDED - Implement Next**

**What:** Track every processor execution in dedicated table  
**Status:** Not yet implemented - **This solves the "silent success" problem!**

**Benefits:**
- ✅ Know when processor last ran (success or failure)
- ✅ Track records processed per run
- ✅ Detect processor failures immediately
- ✅ Distinguish "no new data" from "didn't run"

**Implementation:** See [Processor Run Tracking Architecture](#processor-run-tracking-architecture) below

**Recommendation:** **Implement this first** - highest value for cumulative sources ⭐

#### Tier 3: GCS File Monitoring

**What:** Cloud Function monitors GCS bucket for unprocessed scraper outputs  
**Status:** Not yet implemented - future enhancement

**Benefits:**
- ✅ Detect scraper successes that processor missed
- ✅ Alert on growing backlog of unprocessed files
- ✅ Verify scraper → processor pipeline health

**Implementation:**
```python
# Cloud Function triggered on GCS file creation
def on_new_scraper_file(event, context):
    file_path = event['name']  # gs://nba-scraped-data/nba-com/player-movement/...
    
    # Wait 10 minutes for processor to handle file
    time.sleep(600)
    
    # Check if file was processed
    if not was_processed(file_path):
        alert(f"Unprocessed scraper file: {file_path}")
```

**Recommendation:** Implement after Tier 2 (lower priority)

---

## Processor Run Tracking Architecture

### Overview

**Purpose:** Track every processor execution to distinguish failures from "no new data"  
**Cost:** <$0.10/month (minimal BigQuery storage + query costs)  
**Complexity:** Low - single table + 10 lines of code per processor

### Schema Design

```sql
-- File: schemas/monitoring/processor_runs.sql
CREATE TABLE `nba-props-platform.nba_monitoring.processor_runs` (
  -- Execution identification
  run_id STRING NOT NULL,                    -- UUID for this run
  processor_name STRING NOT NULL,            -- 'nbac_player_movement_processor'
  run_timestamp TIMESTAMP NOT NULL,          -- When processor started
  
  -- Execution details
  trigger_type STRING,                       -- 'scheduled', 'manual', 'backfill', 'retry'
  trigger_source STRING,                     -- 'cloud_scheduler', 'pubsub', 'manual_cli'
  
  -- Processing metrics
  status STRING NOT NULL,                    -- 'started', 'success', 'failed', 'partial'
  duration_seconds FLOAT64,                  -- How long it ran
  records_checked INT64,                     -- Total records examined from source
  records_inserted INT64,                    -- New records inserted
  records_updated INT64,                     -- Existing records updated
  records_skipped INT64,                     -- Duplicates/unchanged records
  
  -- Data range processed
  data_date_start DATE,                      -- Earliest transaction_date processed
  data_date_end DATE,                        -- Latest transaction_date processed
  source_file_path STRING,                   -- GCS path of source data
  
  -- Error tracking
  error_message STRING,                      -- If status='failed', why?
  error_type STRING,                         -- 'network', 'auth', 'data_quality', 'timeout'
  
  -- Validation results
  validation_passed BOOL,                    -- Did post-insert validation pass?
  validation_warnings INT64,                 -- Count of warnings
  duplicates_detected INT64,                 -- Duplicates found post-insert
  
  -- Metadata
  git_commit_hash STRING,                    -- Version of processor code
  host_environment STRING,                   -- 'cloud_run', 'local', 'cloud_function'
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(run_timestamp)
CLUSTER BY processor_name, status;

-- Indexes for common queries
CREATE INDEX idx_processor_status 
  ON `nba-props-platform.nba_monitoring.processor_runs` (processor_name, status, run_timestamp);
```

### Integration with Processor Code

Add this to `data_processors/raw/nbacom/nbac_player_movement_processor.py`:

```python
import uuid
from datetime import datetime

class ProcessorRunTracker:
    """Tracks processor execution metadata to nba_monitoring.processor_runs"""
    
    def __init__(self, processor_name):
        self.processor_name = processor_name
        self.run_id = str(uuid.uuid4())
        self.start_time = datetime.now()
        self.metrics = {
            'records_checked': 0,
            'records_inserted': 0,
            'records_updated': 0,
            'records_skipped': 0,
            'duplicates_detected': 0,
            'validation_warnings': 0
        }
    
    def start_run(self, trigger_type='scheduled', trigger_source='cloud_scheduler'):
        """Log processor start"""
        self.bq_client.query(f"""
            INSERT INTO `nba-props-platform.nba_monitoring.processor_runs` (
                run_id, processor_name, run_timestamp, 
                trigger_type, trigger_source, status
            )
            VALUES (
                '{self.run_id}',
                '{self.processor_name}',
                CURRENT_TIMESTAMP(),
                '{trigger_type}',
                '{trigger_source}',
                'started'
            )
        """)
    
    def update_metrics(self, **kwargs):
        """Update processing metrics"""
        self.metrics.update(kwargs)
    
    def complete_run(self, status='success', error_message=None):
        """Log processor completion"""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        validation_passed = (
            self.metrics['duplicates_detected'] == 0 and
            self.metrics['validation_warnings'] == 0
        )
        
        self.bq_client.query(f"""
            UPDATE `nba-props-platform.nba_monitoring.processor_runs`
            SET 
                status = '{status}',
                duration_seconds = {duration},
                records_checked = {self.metrics['records_checked']},
                records_inserted = {self.metrics['records_inserted']},
                records_updated = {self.metrics['records_updated']},
                records_skipped = {self.metrics['records_skipped']},
                duplicates_detected = {self.metrics['duplicates_detected']},
                validation_passed = {validation_passed},
                validation_warnings = {self.metrics['validation_warnings']},
                error_message = {f"'{error_message}'" if error_message else 'NULL'}
            WHERE run_id = '{self.run_id}'
        """)

# Usage in processor:
def main():
    tracker = ProcessorRunTracker('nbac_player_movement_processor')
    
    try:
        tracker.start_run(trigger_type='scheduled', trigger_source='cloud_scheduler')
        
        # Process data
        source_data = fetch_player_movement_data()
        tracker.update_metrics(records_checked=len(source_data))
        
        # Insert to BigQuery
        new_records = insert_new_records(source_data)
        tracker.update_metrics(records_inserted=len(new_records))
        
        # Validate
        duplicates = check_for_duplicates()
        tracker.update_metrics(duplicates_detected=duplicates)
        
        # Success!
        tracker.complete_run(status='success')
        
    except Exception as e:
        tracker.complete_run(status='failed', error_message=str(e))
        raise
```

### Monitoring Queries

#### Check Last Processor Run
```sql
-- When did processor last run? Did it succeed?
SELECT 
  run_timestamp,
  status,
  duration_seconds,
  records_inserted,
  records_skipped,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), run_timestamp, HOUR) as hours_ago
FROM `nba-props-platform.nba_monitoring.processor_runs`
WHERE processor_name = 'nbac_player_movement_processor'
ORDER BY run_timestamp DESC
LIMIT 1;
```

#### Detect Processor Failures
```sql
-- Alert if processor hasn't run in 24 hours OR last run failed
WITH latest_run AS (
  SELECT 
    run_timestamp,
    status,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), run_timestamp, HOUR) as hours_ago
  FROM `nba-props-platform.nba_monitoring.processor_runs`
  WHERE processor_name = 'nbac_player_movement_processor'
  ORDER BY run_timestamp DESC
  LIMIT 1
)

SELECT
  CASE
    WHEN hours_ago > 24 THEN 'CRITICAL: Processor has not run in 24+ hours'
    WHEN status = 'failed' THEN 'CRITICAL: Last processor run failed'
    WHEN status = 'partial' THEN 'WARNING: Last run completed with errors'
    WHEN hours_ago > 12 THEN 'WARNING: Processor has not run in 12+ hours'
    ELSE 'OK: Processor healthy'
  END as alert_status,
  run_timestamp,
  status,
  hours_ago
FROM latest_run;
```

#### Processor Performance Trends
```sql
-- Track processor performance over time
SELECT 
  DATE(run_timestamp) as run_date,
  COUNT(*) as runs_per_day,
  ROUND(AVG(duration_seconds), 1) as avg_duration_sec,
  SUM(records_inserted) as total_inserted,
  SUM(records_skipped) as total_skipped,
  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failures,
  SUM(CASE WHEN duplicates_detected > 0 THEN 1 ELSE 0 END) as runs_with_dupes
FROM `nba-props-platform.nba_monitoring.processor_runs`
WHERE processor_name = 'nbac_player_movement_processor'
  AND run_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY run_date
ORDER BY run_date DESC;
```

### CLI Tool for Processor Monitoring

```bash
#!/usr/bin/env bash
# File: scripts/check-processor-health

PROCESSOR_NAME="${1:-nbac_player_movement_processor}"

echo "=== Processor Health Check: $PROCESSOR_NAME ==="
echo ""

# Check last run
echo "📊 Last Run:"
bq query --use_legacy_sql=false --format=pretty "
SELECT 
  run_timestamp,
  status,
  ROUND(duration_seconds, 1) as duration_sec,
  records_inserted,
  records_skipped,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), run_timestamp, HOUR) as hours_ago
FROM \`nba-props-platform.nba_monitoring.processor_runs\`
WHERE processor_name = '$PROCESSOR_NAME'
ORDER BY run_timestamp DESC
LIMIT 1
"

echo ""
echo "📈 Last 7 Days:"
bq query --use_legacy_sql=false --format=pretty "
SELECT 
  DATE(run_timestamp) as date,
  COUNT(*) as runs,
  SUM(records_inserted) as inserted,
  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failures
FROM \`nba-props-platform.nba_monitoring.processor_runs\`
WHERE processor_name = '$PROCESSOR_NAME'
  AND run_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY date
ORDER BY date DESC
"

echo ""
echo "✅ Health check complete!"
```

---

## Automated Monitoring Setup

### Cloud Scheduler Configuration

Create scheduled jobs to run validation queries automatically:

```bash
# File: infrastructure/cloud_scheduler_setup.sh

PROJECT_ID="nba-props-platform"
REGION="us-central1"

# 1. Daily morning health check (9am ET = 14:00 UTC)
gcloud scheduler jobs create http player-movement-morning-check \
  --project=$PROJECT_ID \
  --location=$REGION \
  --schedule="0 14 * * *" \
  --uri="https://[your-cloud-run-endpoint]/validation/player-movement/freshness" \
  --http-method=POST \
  --time-zone="America/New_York" \
  --description="Daily morning freshness check for player movement data"

# 2. Weekly quality check (Monday 10am ET = 15:00 UTC)
gcloud scheduler jobs create http player-movement-weekly-quality \
  --project=$PROJECT_ID \
  --location=$REGION \
  --schedule="0 15 * * 1" \
  --uri="https://[your-cloud-run-endpoint]/validation/player-movement/quality" \
  --http-method=POST \
  --time-zone="America/New_York" \
  --description="Weekly data quality check"

# 3. Monthly completeness audit (1st of month, 11am ET = 16:00 UTC)
gcloud scheduler jobs create http player-movement-monthly-audit \
  --project=$PROJECT_ID \
  --location=$REGION \
  --schedule="0 16 1 * *" \
  --uri="https://[your-cloud-run-endpoint]/validation/player-movement/all" \
  --http-method=POST \
  --time-zone="America/New_York" \
  --description="Monthly completeness audit"

# 4. Processor health check (every 6 hours)
gcloud scheduler jobs create http processor-health-check \
  --project=$PROJECT_ID \
  --location=$REGION \
  --schedule="0 */6 * * *" \
  --uri="https://[your-cloud-run-endpoint]/monitoring/processor-health/nbac_player_movement" \
  --http-method=GET \
  --time-zone="America/New_York" \
  --description="Check processor health every 6 hours"
```

### BigQuery Scheduled Queries

Create scheduled queries that run validation checks and send alerts:

```sql
-- File: scheduled_queries/player_movement_daily_freshness.sql
-- Schedule: Daily at 09:00 ET
-- Destination: Pub/Sub topic for Slack alerts

WITH freshness AS (
  SELECT
    MAX(transaction_date) as last_transaction,
    DATE_DIFF(CURRENT_DATE(), MAX(transaction_date), DAY) as days_old,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_since_insert,
    
    -- Determine season period
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (7, 8) THEN 'Free Agency'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) = 2 THEN 'Trade Deadline'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (5, 6) THEN 'Playoffs'
      ELSE 'Regular Season'
    END as season_period,
    
    -- Alert thresholds vary by season
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (7, 8) THEN 3
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) = 2 THEN 7
      ELSE 14
    END as alert_threshold_days
    
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
)

SELECT
  'player_movement_freshness' as alert_type,
  season_period,
  last_transaction,
  days_old,
  hours_since_insert,
  alert_threshold_days,
  
  CASE
    WHEN days_old > alert_threshold_days AND season_period IN ('Free Agency', 'Trade Deadline')
    THEN 'CRITICAL'
    WHEN days_old > alert_threshold_days
    THEN 'WARNING'
    WHEN days_old > (alert_threshold_days / 2)
    THEN 'INFO'
    ELSE 'OK'
  END as severity,
  
  CASE
    WHEN days_old > alert_threshold_days AND season_period IN ('Free Agency', 'Trade Deadline')
    THEN CONCAT('🔴 CRITICAL: No player movement data in ', CAST(days_old AS STRING), ' days during ', season_period)
    WHEN days_old > alert_threshold_days
    THEN CONCAT('🟡 WARNING: Player movement data is ', CAST(days_old AS STRING), ' days old')
    WHEN days_old > (alert_threshold_days / 2)
    THEN CONCAT('ℹ️ INFO: Player movement data is ', CAST(days_old AS STRING), ' days old (approaching alert threshold)')
    ELSE CONCAT('✅ OK: Player movement data is fresh (', CAST(days_old AS STRING), ' days old)')
  END as message

FROM freshness
WHERE days_old > (alert_threshold_days / 2);  -- Only send alerts when approaching or exceeding threshold
```

### Slack/Email Alerting

**Cloud Function to process BigQuery alerts:**

```python
# File: cloud_functions/bigquery_alerts_to_slack.py

import functions_framework
import requests
import os
from google.cloud import pubsub_v1

SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL')

@functions_framework.cloud_event
def process_bigquery_alert(cloud_event):
    """Process BigQuery scheduled query results and send to Slack"""
    
    # Parse Pub/Sub message
    import base64
    import json
    
    pubsub_message = base64.b64decode(cloud_event.data["message"]["data"]).decode()
    alert_data = json.loads(pubsub_message)
    
    severity = alert_data.get('severity', 'INFO')
    message = alert_data.get('message', 'Unknown alert')
    alert_type = alert_data.get('alert_type', 'general')
    
    # Color code by severity
    color_map = {
        'CRITICAL': '#FF0000',  # Red
        'WARNING': '#FFA500',   # Orange
        'INFO': '#00BFFF',      # Blue
        'OK': '#00FF00'         # Green
    }
    
    # Send to Slack
    slack_message = {
        "text": f"NBA Props Platform - Data Alert",
        "attachments": [{
            "color": color_map.get(severity, '#808080'),
            "fields": [
                {
                    "title": "Alert Type",
                    "value": alert_type,
                    "short": True
                },
                {
                    "title": "Severity",
                    "value": severity,
                    "short": True
                },
                {
                    "title": "Message",
                    "value": message,
                    "short": False
                }
            ],
            "footer": "NBA Props Platform Monitoring",
            "ts": int(time.time())
        }]
    }
    
    response = requests.post(SLACK_WEBHOOK, json=slack_message)
    
    if response.status_code != 200:
        raise Exception(f"Slack notification failed: {response.text}")
    
    return "Alert sent successfully"
```

---

## Alert Thresholds by Season

### Recommended Thresholds

| Metric | Free Agency | Trade Deadline | Regular Season | Playoffs | Off-Season |
|--------|-------------|----------------|----------------|----------|------------|
| **Days since last transaction** | | | | | |
| → INFO | 2 days | 4 days | 7 days | 15 days | 15 days |
| → WARNING | 3 days | 7 days | 14 days | 30 days | 30 days |
| → CRITICAL | 5 days | 10 days | 21 days | 45 days | 45 days |
| **Hours since processor run** | | | | | |
| → INFO | 12 hours | 12 hours | 12 hours | 24 hours | 24 hours |
| → WARNING | 24 hours | 24 hours | 24 hours | 48 hours | 48 hours |
| → CRITICAL | 48 hours | 48 hours | 48 hours | 72 hours | 72 hours |
| **Duplicates detected** | | | | | |
| → INFO | 1-5 | 1-5 | 1-5 | 1-5 | 1-5 |
| → WARNING | 6-15 | 6-15 | 6-15 | 6-15 | 6-15 |
| → CRITICAL | 16+ | 16+ | 16+ | 16+ | 16+ |
| **Orphaned trades** | | | | | |
| → INFO | 1-3 new | 1-5 new | 1-2 new | 1 new | 1 new |
| → WARNING | 4-7 new | 6-10 new | 3-5 new | 2-3 new | 2-3 new |
| → CRITICAL | 8+ new | 11+ new | 6+ new | 4+ new | 4+ new |

### Implementation in Code

```python
# File: monitoring/alert_thresholds.py

from datetime import datetime

def get_season_period():
    """Determine current NBA season period"""
    month = datetime.now().month
    
    if month in [7, 8]:
        return 'free_agency'
    elif month == 2:
        return 'trade_deadline'
    elif month in [5, 6]:
        return 'playoffs'
    elif month in [9, 10]:
        return 'preseason'
    else:
        return 'regular_season'

THRESHOLDS = {
    'free_agency': {
        'days_since_transaction': {'info': 2, 'warning': 3, 'critical': 5},
        'hours_since_processor': {'info': 12, 'warning': 24, 'critical': 48},
        'duplicates': {'info': 5, 'warning': 15, 'critical': 16},
        'orphaned_trades': {'info': 3, 'warning': 7, 'critical': 8}
    },
    'trade_deadline': {
        'days_since_transaction': {'info': 4, 'warning': 7, 'critical': 10},
        'hours_since_processor': {'info': 12, 'warning': 24, 'critical': 48},
        'duplicates': {'info': 5, 'warning': 15, 'critical': 16},
        'orphaned_trades': {'info': 5, 'warning': 10, 'critical': 11}
    },
    'regular_season': {
        'days_since_transaction': {'info': 7, 'warning': 14, 'critical': 21},
        'hours_since_processor': {'info': 12, 'warning': 24, 'critical': 48},
        'duplicates': {'info': 5, 'warning': 15, 'critical': 16},
        'orphaned_trades': {'info': 2, 'warning': 5, 'critical': 6}
    },
    'playoffs': {
        'days_since_transaction': {'info': 15, 'warning': 30, 'critical': 45},
        'hours_since_processor': {'info': 24, 'warning': 48, 'critical': 72},
        'duplicates': {'info': 5, 'warning': 15, 'critical': 16},
        'orphaned_trades': {'info': 1, 'warning': 3, 'critical': 4}
    },
    'preseason': {
        'days_since_transaction': {'info': 4, 'warning': 7, 'critical': 14},
        'hours_since_processor': {'info': 12, 'warning': 24, 'critical': 48},
        'duplicates': {'info': 5, 'warning': 15, 'critical': 16},
        'orphaned_trades': {'info': 2, 'warning': 5, 'critical': 6}
    }
}

def get_alert_severity(metric_name, value):
    """Determine alert severity based on season and metric value"""
    period = get_season_period()
    thresholds = THRESHOLDS[period][metric_name]
    
    if value >= thresholds['critical']:
        return 'CRITICAL'
    elif value >= thresholds['warning']:
        return 'WARNING'
    elif value >= thresholds['info']:
        return 'INFO'
    else:
        return 'OK'

# Usage:
days_old = 4
season = get_season_period()  # 'free_agency'
severity = get_alert_severity('days_since_transaction', days_old)  # 'WARNING'
```

---

## Troubleshooting Guide

### Common Issues & Solutions

#### Issue: "No new transactions in X days during Free Agency"

**Severity:** 🔴 CRITICAL  
**Season:** July-August

**Investigation Steps:**
1. Check processor run history:
   ```bash
   ./scripts/check-processor-health nbac_player_movement_processor
   ```

2. Check scraper logs:
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND \
     resource.labels.service_name=nba-scraper AND \
     textPayload:player-movement" \
     --limit=50 --format=json
   ```

3. Verify NBA.com source manually:
   - Visit https://www.nba.com/stats/transactions
   - Check if transactions are being reported

**Common Causes:**
- ❌ Scraper failing silently (check error logs)
- ❌ Processor not scheduled/running (check Cloud Scheduler)
- ❌ NBA.com API down or changed structure
- ❌ Authentication issue with NBA.com

**Resolution:**
1. If scraper failing: Check error logs, may need to update scraper
2. If processor not running: Verify Cloud Scheduler job exists and is enabled
3. If NBA.com changed: Update scraper to handle new structure
4. Manual trigger: Run scraper and processor manually to catch up

#### Issue: "Processor hasn't run in 24+ hours"

**Severity:** 🔴 CRITICAL  
**Season:** Any

**Investigation:**
```bash
# Check Cloud Scheduler status
gcloud scheduler jobs describe player-movement-processor \
  --location=us-central1

# Check recent executions
gcloud scheduler jobs logs player-movement-processor \
  --location=us-central1 \
  --limit=10
```

**Common Causes:**
- ❌ Cloud Scheduler job paused
- ❌ Cloud Run service down
- ❌ Pub/Sub subscription issues
- ❌ Processor crashing immediately

**Resolution:**
1. Resume Cloud Scheduler if paused
2. Check Cloud Run service health
3. Manually trigger processor to test
4. Check processor logs for crashes

#### Issue: "New duplicates detected"

**Severity:** 🟡 WARNING → 🔴 CRITICAL (if >16)  
**Season:** Any

**Investigation:**
```bash
# Check which records are duplicated
bq query --use_legacy_sql=false "
SELECT 
  player_id, transaction_date, transaction_type, COUNT(*) as count,
  STRING_AGG(CAST(created_at AS STRING) ORDER BY created_at) as timestamps
FROM \`nba-props-platform.nba_raw.nbac_player_movement\`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY player_id, team_id, transaction_date, transaction_type, group_sort
HAVING COUNT(*) > 1
"
```

**Common Causes:**
- ❌ Processor ran multiple times on same data
- ❌ INSERT_NEW_ONLY logic failed
- ❌ Concurrent processor executions
- ❌ Source data has duplicates

**Resolution:**
1. Check processor_runs table for duplicate executions
2. Run deduplication script (see Data Quality Issues doc)
3. Fix processor logic to prevent future duplicates
4. Add idempotency check before insert

#### Issue: "Orphaned trades increasing"

**Severity:** 🟡 WARNING  
**Season:** Any (especially Trade Deadline, Free Agency)

**Investigation:**
```bash
# List recent orphaned trades
./scripts/validate-player-movement trades | grep "ORPHANED"
```

**Common Causes:**
- ⚠️ Trade announced but not finalized (waiting for physicals)
- ⚠️ Future considerations not yet disclosed
- ⚠️ NBA.com updated one side before other side
- ❌ Scraper ran mid-update

**Resolution:**
1. Document new orphaned trades
2. Wait 24-48 hours for NBA.com to complete entry
3. Re-run scraper/processor after 48 hours
4. If still orphaned, manually investigate trade details

#### Issue: "Validation query failing/timing out"

**Severity:** 🟡 WARNING  
**Season:** Any

**Common Causes:**
- ❌ Missing partition filter (queries must filter on season_year)
- ❌ Query too complex for BigQuery limits
- ❌ Table not properly partitioned

**Resolution:**
1. Check query has `WHERE season_year >= 2021` filter
2. Reduce date range if querying large span
3. Verify table is properly partitioned on season_year

---

## Summary & Quick Reference

### Daily Checklist (During Season)

**Every Morning (9am):**
- [ ] Run `./scripts/validate-player-movement freshness`
- [ ] Run `./scripts/validate-player-movement recent`
- [ ] Check for CRITICAL/WARNING alerts

**Every Monday:**
- [ ] Run `./scripts/weekly-quality-check`
- [ ] Review processor_runs for failures
- [ ] Check orphaned trades count

**First Monday of Month:**
- [ ] Run `./scripts/monthly-completeness-audit`
- [ ] Export reports for archival
- [ ] Review trends in processor performance

### Key Commands

```bash
# Quick health check
./scripts/validate-player-movement freshness

# Full validation suite
./scripts/validate-player-movement all

# Check processor health
./scripts/check-processor-health nbac_player_movement_processor

# Manual processor trigger
curl -X POST https://[endpoint]/processors/nbac_player_movement/run
```

### Seasonal Alert Expectations

| Period | Expected Activity | Alert Threshold | False Alarm Risk |
|--------|------------------|-----------------|------------------|
| Free Agency (Jul-Aug) | High | 3 days | Low |
| Trade Deadline (Feb) | Medium | 7 days | Low |
| Regular Season (Nov-Apr) | Low | 14 days | Medium |
| Playoffs (May-Jun) | Very Low | 30 days | High |
| Pre-Season (Sep-Oct) | Medium | 7 days | Low |

### Priority Action Items

**🔴 Critical (Immediate):**
1. Processor hasn't run in 24+ hours
2. Last processor run failed
3. No transactions during Free Agency (3+ days)
4. 16+ new duplicates detected

**🟡 Warning (Within 24 hours):**
5. Data stale during active period
6. Multiple processor failures (3+ in 24h)
7. 6-15 new duplicates
8. 5+ new orphaned trades during Trade Deadline

**🟢 Info (When convenient):**
9. Data approaching staleness threshold
10. 1-5 new duplicates
11. Normal seasonal quiet period

---

**Document Owner:** Data Engineering Team  
**Last Updated:** October 13, 2025  
**Next Review:** Monthly or after processor changes  
**Related Docs:**
- `validation/queries/raw/nbac_player_movement/README.md`
- Player Movement Data Quality Issues & Resolutions (Document 1)
- `docs/PROCESSOR_MONITORING_IDEAS.md`
