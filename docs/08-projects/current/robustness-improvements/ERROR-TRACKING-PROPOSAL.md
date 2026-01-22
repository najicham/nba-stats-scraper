# Error Tracking & Recovery System Proposal

**Created:** January 21, 2026
**Context:** 30-day data validation revealed 33 BDL games missing, highlighting need for better error tracking

---

## Current State

### What Already Exists (Good Foundation)

1. **Self-Heal Function** (`orchestration/cloud_functions/self_heal/main.py`)
   - Runs daily at 12:45 PM ET
   - Checks Phase 2/3/4 completeness
   - Triggers healing pipelines
   - Logs to Firestore (`self_heal_history` collection)
   - Sends Slack alerts

2. **Scraper Notifications** (`shared/utils/notification_system.py`)
   - `notify_error()`, `notify_warning()`, `notify_info()`
   - Sends to Slack on errors
   - Already integrated into BDL scrapers

3. **Rate Limit Handler** (`shared/utils/rate_limit_handler.py`)
   - Circuit breaker pattern
   - Exponential backoff
   - Request tracking

### What's Missing (The Gap)

| User Need | Current Gap |
|-----------|-------------|
| Know sooner there was an error | No real-time BDL vs NBAC comparison |
| Record of the exact error | Errors logged but not structured for analysis |
| Retry later | One-shot scraping, no automatic retry queue |
| Record when it recovered | No recovery timestamp tracking |

---

## Proposed Solution: Scrape Event Tracking System

### Architecture Overview

```
┌─────────────────┐     ┌──────────────────────┐     ┌───────────────────┐
│  Scrapers       │────▶│  BigQuery Event Log  │────▶│  Recovery Monitor │
│  (BDL, NBAC)    │     │  scrape_events       │     │  (Cloud Function) │
└─────────────────┘     └──────────────────────┘     └───────────────────┘
        │                         │                           │
        │                         ▼                           │
        │               ┌──────────────────────┐              │
        └──────────────▶│  Retry Queue         │◀─────────────┘
                        │  (Firestore)         │
                        └──────────────────────┘
```

### Component 1: Scrape Event Log (BigQuery)

**Table:** `nba_monitoring.scrape_events`

```sql
CREATE TABLE `nba-props-platform.nba_monitoring.scrape_events` (
  event_id STRING NOT NULL,           -- UUID
  scraper_name STRING NOT NULL,       -- 'bdl_games', 'nbac_gamebook', etc.
  target_date DATE NOT NULL,          -- Date being scraped

  -- Execution details
  started_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  duration_seconds FLOAT64,

  -- Results
  status STRING NOT NULL,             -- 'success', 'partial', 'failed'
  records_expected INT64,             -- How many games/records expected
  records_received INT64,             -- How many actually received
  records_missing INT64,              -- Difference (for discrepancy detection)

  -- Error details (if failed)
  error_type STRING,                  -- 'rate_limit', 'timeout', 'api_error', 'validation_error'
  error_message STRING,
  error_details JSON,                 -- Full context (URL, response code, etc.)

  -- API-specific tracking
  api_response_code INT64,
  api_response_time_ms INT64,
  pages_fetched INT64,

  -- Recovery tracking
  is_recovered BOOL DEFAULT FALSE,
  recovered_at TIMESTAMP,
  recovery_event_id STRING,           -- Links to the successful retry

  -- Metadata
  correlation_id STRING,
  cloud_run_revision STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(target_date)
CLUSTER BY scraper_name, status;
```

### Component 2: Real-Time Discrepancy Detection

Add to BDL scrapers - compare with NBAC immediately after scraping:

```python
# scrapers/balldontlie/bdl_box_scores.py - Add after successful scrape

def check_discrepancy(self, scraped_games: list, target_date: str) -> dict:
    """Compare scraped games with NBAC to detect missing games immediately."""
    from google.cloud import bigquery

    bq = bigquery.Client()
    query = f"""
    SELECT COUNT(DISTINCT game_id) as nbac_games
    FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
    WHERE game_date = '{target_date}'
    """
    result = list(bq.query(query).result())
    nbac_count = result[0].nbac_games if result else 0
    bdl_count = len(scraped_games)

    discrepancy = {
        'target_date': target_date,
        'bdl_games': bdl_count,
        'nbac_games': nbac_count,
        'missing': max(0, nbac_count - bdl_count),
        'has_discrepancy': nbac_count > bdl_count
    }

    if discrepancy['has_discrepancy']:
        # Log to BigQuery and alert immediately
        self.log_scrape_event(
            status='partial',
            records_expected=nbac_count,
            records_received=bdl_count,
            records_missing=nbac_count - bdl_count,
            error_type='api_incomplete',
            error_message=f"BDL returned {bdl_count} games but NBAC has {nbac_count}"
        )

        # Queue for retry
        self.add_to_retry_queue(target_date, 'bdl_discrepancy')

    return discrepancy
```

### Component 3: Retry Queue (Firestore)

**Collection:** `scrape_retry_queue`

```python
# Document structure
{
    "doc_id": "bdl_box_scores_2026-01-19",  # scraper_date
    "scraper_name": "bdl_box_scores",
    "target_date": "2026-01-19",
    "reason": "bdl_discrepancy",  # or 'rate_limit', 'timeout', etc.
    "original_error": "BDL returned 4 games but NBAC has 9",

    "retry_attempts": 0,
    "max_retries": 3,
    "next_retry_at": "2026-01-20T04:00:00Z",  # Exponential backoff
    "retry_history": [
        {
            "attempt": 1,
            "attempted_at": "2026-01-20T04:00:00Z",
            "result": "partial",
            "games_received": 6
        }
    ],

    "status": "pending",  # 'pending', 'retrying', 'recovered', 'exhausted'
    "created_at": "2026-01-19T12:00:00Z",
    "recovered_at": null,
    "correlation_id": "abc123"
}
```

### Component 4: Recovery Monitor (Cloud Function)

New function: `scrape_retry_processor`

```python
# orchestration/cloud_functions/scrape_retry_processor/main.py

"""
Scrape Retry Processor

Schedule: Every 4 hours (0 */4 * * *)
Purpose: Process retry queue, attempt re-scrapes, track recovery

Retry schedule with exponential backoff:
- Attempt 1: 4 hours after failure
- Attempt 2: 12 hours after attempt 1
- Attempt 3: 24 hours after attempt 2
"""

import functions_framework
from google.cloud import firestore, bigquery
from datetime import datetime, timezone, timedelta

@functions_framework.http
def process_retry_queue(request):
    """Process pending retry items."""
    db = firestore.Client()
    bq = bigquery.Client()

    results = {
        "processed": 0,
        "recovered": 0,
        "still_failing": 0,
        "exhausted": 0
    }

    # Get items ready for retry
    now = datetime.now(timezone.utc)
    pending = (
        db.collection('scrape_retry_queue')
        .where('status', '==', 'pending')
        .where('next_retry_at', '<=', now)
        .limit(10)  # Process in batches
        .stream()
    )

    for doc in pending:
        item = doc.to_dict()
        results["processed"] += 1

        # Attempt scrape
        success, games_received = attempt_scrape(
            item['scraper_name'],
            item['target_date']
        )

        # Check if recovered
        if success and games_received >= item.get('expected_games', 0):
            # RECOVERED!
            doc.reference.update({
                'status': 'recovered',
                'recovered_at': firestore.SERVER_TIMESTAMP,
                'retry_history': firestore.ArrayUnion([{
                    'attempt': item['retry_attempts'] + 1,
                    'attempted_at': now.isoformat(),
                    'result': 'recovered',
                    'games_received': games_received
                }])
            })

            # Log recovery to BigQuery
            log_recovery_event(bq, item, games_received)

            # Send success notification
            send_recovery_alert(item)

            results["recovered"] += 1

        elif item['retry_attempts'] >= item.get('max_retries', 3):
            # Exhausted retries
            doc.reference.update({
                'status': 'exhausted',
                'exhausted_at': firestore.SERVER_TIMESTAMP
            })

            # Alert for manual intervention
            send_exhausted_alert(item)

            results["exhausted"] += 1

        else:
            # Still failing, schedule next retry
            next_delay = calculate_backoff(item['retry_attempts'] + 1)
            doc.reference.update({
                'retry_attempts': item['retry_attempts'] + 1,
                'next_retry_at': now + next_delay,
                'retry_history': firestore.ArrayUnion([{
                    'attempt': item['retry_attempts'] + 1,
                    'attempted_at': now.isoformat(),
                    'result': 'failed',
                    'games_received': games_received
                }])
            })

            results["still_failing"] += 1

    return results
```

### Component 5: Dashboard Queries

**Daily Health Report:**
```sql
-- Query for daily monitoring dashboard
SELECT
  target_date,
  scraper_name,
  COUNT(*) as total_scrapes,
  COUNTIF(status = 'success') as successful,
  COUNTIF(status = 'partial') as partial,
  COUNTIF(status = 'failed') as failed,
  SUM(records_missing) as total_missing_records,
  COUNTIF(is_recovered) as recovered,
  AVG(duration_seconds) as avg_duration
FROM `nba-props-platform.nba_monitoring.scrape_events`
WHERE target_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY target_date, scraper_name
ORDER BY target_date DESC, scraper_name;
```

**Recovery Time Analysis:**
```sql
-- How long does it typically take to recover?
SELECT
  scraper_name,
  error_type,
  COUNT(*) as incidents,
  AVG(TIMESTAMP_DIFF(recovered_at, started_at, HOUR)) as avg_recovery_hours,
  MIN(TIMESTAMP_DIFF(recovered_at, started_at, HOUR)) as min_recovery_hours,
  MAX(TIMESTAMP_DIFF(recovered_at, started_at, HOUR)) as max_recovery_hours
FROM `nba-props-platform.nba_monitoring.scrape_events`
WHERE is_recovered = TRUE
  AND target_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY scraper_name, error_type
ORDER BY incidents DESC;
```

---

## Implementation Plan

### Phase 1: Core Infrastructure (Week 1)
- [ ] Create `nba_monitoring.scrape_events` BigQuery table
- [ ] Create `scrape_retry_queue` Firestore collection
- [ ] Add `log_scrape_event()` utility function to `scraper_base.py`

### Phase 2: Scraper Integration (Week 2)
- [ ] Integrate event logging into `bdl_box_scores.py`
- [ ] Integrate event logging into `bdl_games.py`
- [ ] Add discrepancy detection (compare BDL vs NBAC)

### Phase 3: Retry Processor (Week 3)
- [ ] Create `scrape_retry_processor` cloud function
- [ ] Deploy with Cloud Scheduler (every 4 hours)
- [ ] Add Slack alerts for recovery and exhaustion

### Phase 4: Dashboard & Alerts (Week 4)
- [ ] Create Looker Studio dashboard for scrape health
- [ ] Add daily email digest of scrape issues
- [ ] Document runbooks for manual intervention

---

## Benefits

| Metric | Before | After |
|--------|--------|-------|
| Time to detect missing data | Next day (self-heal) | Real-time |
| Error context available | Partial (logs) | Full (structured JSON) |
| Automatic retry | None | 3 attempts with backoff |
| Recovery tracking | None | Full audit trail |
| Historical analysis | Manual queries | Dashboard |

---

## Immediate Actions

1. **For BDL missing games (current issue)**:
   - Send email to BDL support (draft ready)
   - The 33 missing games are external API issue, not our system

2. **For Phase 2/3 gaps we found**:
   - Already triggered backfills
   - Will be recovered by the pipeline

3. **For future prevention**:
   - Implement Phase 1-2 of this proposal
   - Add BDL vs NBAC comparison to catch discrepancies immediately
