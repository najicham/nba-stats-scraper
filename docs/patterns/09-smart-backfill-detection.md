# 09 - Smart Backfill Detection (Auto-Recovery)

**Created:** 2025-11-20 8:14 AM PST
**Last Updated:** 2025-11-20 8:14 AM PST
**Pattern:** Smart Backfill Detection
**Effort:** 2-3 hours
**Impact:** High (prevents cascade failures, auto-recovery)
**Status:** 💡 **Can implement - BUT wait for monitoring data first**
**Reference:** [Optimization Pattern Catalog](../reference/02-optimization-pattern-catalog.md), Pattern #15

> **⚠️ IMPORTANT: Don't Implement Yet!**
>
> **Timeline:** Week 4-8 (AFTER Week 1-8 monitoring shows need)
>
> **Why wait:**
> 1. We don't know if gaps are frequent enough to justify complexity
> 2. Week 1-8 monitoring will show actual gap frequency
> 3. Manual backfill might be rare and easy
> 4. This adds infrastructure (Cloud Function, new table, Pub/Sub topic)
>
> **Implement ONLY if Week 1-8 data shows:**
> - ✅ Data gaps occur > 3 times/week
> - ✅ Manual backfill takes > 1 hour/week
> - ✅ Cascade failures are common
>
> **This document:** Reference for IF gaps become a problem

---

## Overview

This pattern automatically detects missing historical data and queues backfill jobs for small gaps, preventing repeated dependency failures and enabling automatic recovery.

**What it does:**
- Before processing, checks for gaps in lookback window (e.g., last 30 days)
- If small gap (≤3 days): Auto-queue backfill jobs
- If large gap (>3 days): Alert for manual intervention
- Skips current processing until backfill completes
- Resumes automatically once gaps are filled

**Value when needed:**
- ✅ Eliminates manual gap investigation
- ✅ Prevents cascade failures (missing day X → fails day X+1, X+2, X+3...)
- ✅ Automatic recovery from data gaps
- ✅ Clear visibility into gap frequency

**Key insight:** Transforms reactive "firefighting" into proactive auto-recovery

---

## The Problem (If It Exists)

### Scenario: Missing Data Cascade

**Without Smart Backfill:**
```
Nov 15 - Data missing (scraper failed, source down, etc.)
Nov 16 - Processor fails: "Missing dependency for Nov 15"
Nov 17 - Processor fails: "Missing dependency for Nov 15"
Nov 18 - Processor fails: "Missing dependency for Nov 15"
Nov 19 - Engineer notices pattern in logs
         → Investigates (30 min)
         → Identifies missing Nov 15 (15 min)
         → Manually runs backfill (15 min)
Nov 20 - Processing resumes

Total: 5 days of failures, 1 hour manual work
```

**With Smart Backfill:**
```
Nov 15 - Data missing
Nov 16 - Processor detects gap in lookback window
         → Auto-queues backfill for Nov 15
         → Skips processing (waits for backfill)
Nov 16 (5 min later) - Backfill completes
Nov 16 (10 min later) - Next run succeeds
Nov 17+ - Normal processing

Total: 0 manual work, automatic recovery in 10 minutes
```

---

## Is This Needed? (Check First!)

Before implementing, run these queries to see if you have a gap problem:

### Query 1: Gap Frequency (Last 30 Days)

```sql
-- How often do we have missing dates?
WITH expected_dates AS (
    SELECT DISTINCT game_date
    FROM `nba_raw.game_schedule`
    WHERE game_date >= CURRENT_DATE() - 30
      AND game_status IN ('Final', 'Completed')
),
actual_dates AS (
    SELECT DISTINCT game_date
    FROM `nba_analytics.player_game_summary`  -- Your target table
    WHERE game_date >= CURRENT_DATE() - 30
)
SELECT
    e.game_date as missing_date,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), TIMESTAMP(e.game_date), DAY) as days_ago
FROM expected_dates e
LEFT JOIN actual_dates a ON e.game_date = a.game_date
WHERE a.game_date IS NULL
ORDER BY e.game_date;
```

**Interpret results:**
- **0-2 gaps in 30 days:** Manual backfill is fine, don't implement
- **3-5 gaps in 30 days:** Borderline, monitor for another month
- **> 5 gaps in 30 days:** Implement Smart Backfill

### Query 2: Dependency Failure Rate

```sql
-- How often do processors fail due to missing dependencies?
SELECT
    processor_name,
    COUNTIF(success = FALSE AND error_message LIKE '%dependency%') as dependency_failures,
    COUNTIF(success = FALSE) as total_failures,
    COUNT(*) as total_runs,
    ROUND(COUNTIF(success = FALSE AND error_message LIKE '%dependency%') / COUNT(*) * 100, 1) as dependency_failure_pct
FROM `nba_processing.analytics_processor_runs`
WHERE run_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY processor_name
HAVING dependency_failures > 0
ORDER BY dependency_failures DESC;
```

**Interpret results:**
- **< 5% dependency failures:** Don't need Smart Backfill
- **5-10% dependency failures:** Consider implementing
- **> 10% dependency failures:** Definitely implement

### Query 3: Manual Backfill Time

**Track how much time you spend on manual backfills:**
- Week 1: Count manual backfills
- Week 2-4: Continue tracking
- Week 4: Calculate avg time/week

**Decision criteria:**
- **< 30 min/week:** Don't implement (manual is fine)
- **30-60 min/week:** Consider implementing
- **> 1 hour/week:** Implement Smart Backfill

---

## Implementation (If Justified)

### Step 1: Create Backfill Tracking Infrastructure

```sql
-- Backfill request tracking table
CREATE TABLE IF NOT EXISTS `nba_processing.backfill_requests` (
    processor_name STRING NOT NULL,
    game_date DATE NOT NULL,
    request_type STRING NOT NULL,      -- 'auto' or 'manual'
    priority STRING NOT NULL,           -- 'high', 'normal', 'low'
    requested_at TIMESTAMP NOT NULL,
    requested_by STRING NOT NULL,

    -- Status tracking
    status STRING NOT NULL,             -- 'queued', 'processing', 'completed', 'failed'
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message STRING,

    -- Metadata
    metadata JSON
)
PARTITION BY game_date
CLUSTER BY processor_name, status, requested_at;
```

```bash
# Create Pub/Sub topic for backfill requests
gcloud pubsub topics create nba-backfill-requests

# Create subscription for backfill worker
gcloud pubsub subscriptions create backfill-worker-sub \
  --topic=nba-backfill-requests \
  --ack-deadline=540
```

### Step 2: Create Smart Backfill Mixin

```python
# shared/processors/patterns/smart_backfill_mixin.py

from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
import json
from google.cloud import pubsub_v1

logger = logging.getLogger(__name__)


class SmartBackfillMixin:
    """
    Mixin to add smart backfill detection to processors.

    Automatically detects and recovers from missing historical data.
    """

    # Configuration (override in subclass)
    AUTO_BACKFILL_THRESHOLD = 3        # Auto-queue backfill for gaps ≤ N days
    LOOKBACK_WINDOW_DAYS = 30          # Check this many days back
    CRITICAL_LOOKBACK_DAYS = 10        # Critical dependencies (always check)
    MIN_RECORDS_PER_DATE = 100         # Expect at least N records per date

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pubsub_client = pubsub_v1.PublisherClient()
        self.backfill_topic = f'projects/{self.project_id}/topics/nba-backfill-requests'

    def run(self, opts: Dict) -> bool:
        """
        Enhanced run with backfill detection.

        Checks for historical gaps before processing.
        """
        start_date = opts.get('start_date')
        end_date = opts.get('end_date')

        # Skip backfill check if this IS a backfill job
        if opts.get('is_backfill', False):
            logger.info("Backfill job detected, skipping gap check")
            return super().run(opts)

        # Detect gaps in historical data
        gap_analysis = self._detect_missing_history(end_date)

        if gap_analysis['has_gaps']:
            logger.warning(
                f"Detected {gap_analysis['gap_size']} missing dates "
                f"in lookback window"
            )

            return self._handle_historical_gaps(end_date, gap_analysis)

        # No gaps - proceed with normal processing
        logger.info("Historical data complete, proceeding")
        return super().run(opts)

    def _detect_missing_history(self, current_date: str) -> Dict:
        """
        Detect missing dates in lookback window.

        Returns:
            {
                'has_gaps': bool,
                'missing_dates': List[str],
                'gap_size': int,
                'critical_missing': List[str],
                'window_start': str,
                'window_end': str
            }
        """
        window_start = (
            datetime.strptime(current_date, '%Y-%m-%d') -
            timedelta(days=self.LOOKBACK_WINDOW_DAYS)
        ).strftime('%Y-%m-%d')

        critical_start = (
            datetime.strptime(current_date, '%Y-%m-%d') -
            timedelta(days=self.CRITICAL_LOOKBACK_DAYS)
        ).strftime('%Y-%m-%d')

        # Find missing dates in target table
        missing_dates = self._query_missing_dates(
            window_start,
            current_date
        )

        # Classify missing dates
        critical_missing = [
            d for d in missing_dates
            if d >= critical_start
        ]

        return {
            'has_gaps': len(missing_dates) > 0,
            'missing_dates': missing_dates,
            'gap_size': len(missing_dates),
            'critical_missing': critical_missing,
            'critical_gap_size': len(critical_missing),
            'window_start': window_start,
            'window_end': current_date
        }

    def _query_missing_dates(
        self,
        start_date: str,
        end_date: str
    ) -> List[str]:
        """
        Query for dates with missing or insufficient data.

        Strategy:
        1. Get all dates with scheduled games
        2. Get all dates with adequate data in target table
        3. Find dates in (1) but not in (2)
        """
        target_table = f"{self.project_id}.{self.dataset_id}.{self.table_name}"

        query = f"""
        WITH expected_dates AS (
            -- Dates that should have data (games were scheduled)
            SELECT DISTINCT game_date
            FROM `{self.project_id}.nba_raw.game_schedule`
            WHERE game_date BETWEEN DATE('{start_date}') AND DATE('{end_date}')
              AND game_status IN ('Final', 'Completed')
        ),
        actual_dates AS (
            -- Dates that have adequate data in target table
            SELECT
                DATE(date_range_start) as game_date,
                COUNT(*) as record_count
            FROM `{target_table}`
            WHERE DATE(date_range_start) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
            GROUP BY game_date
            HAVING record_count >= {self.MIN_RECORDS_PER_DATE}
        )
        SELECT e.game_date
        FROM expected_dates e
        LEFT JOIN actual_dates a ON e.game_date = a.game_date
        WHERE a.game_date IS NULL  -- Missing entirely
        ORDER BY e.game_date
        """

        result = self.bq_client.query(query).to_dataframe()

        if result.empty:
            return []

        missing_dates = [
            d.strftime('%Y-%m-%d')
            for d in result['game_date']
        ]

        return missing_dates

    def _handle_historical_gaps(
        self,
        current_date: str,
        gap_analysis: Dict
    ) -> bool:
        """
        Handle detected gaps based on size and criticality.

        Strategy:
        - Small gaps (≤ threshold): Auto-queue backfill
        - Large gaps (> threshold): Alert and skip
        """
        missing_dates = gap_analysis['missing_dates']
        gap_size = gap_analysis['gap_size']

        # Check if gap is small enough to auto-backfill
        if gap_size <= self.AUTO_BACKFILL_THRESHOLD:
            logger.info(
                f"Small gap detected ({gap_size} ≤ {self.AUTO_BACKFILL_THRESHOLD}), "
                f"auto-queueing backfill"
            )

            self._queue_backfill(missing_dates)

            logger.info(
                f"Skipping processing until backfill completes: {missing_dates}"
            )

            return True  # Skip current processing

        # Large gap - needs manual intervention
        logger.error(
            f"Large gap detected ({gap_size} > {self.AUTO_BACKFILL_THRESHOLD}), "
            f"manual intervention required"
        )

        # Send alert
        logger.error(
            f"Missing dates: {missing_dates[:10]}"  # Show first 10
        )

        return True  # Skip current processing

    def _queue_backfill(self, missing_dates: List[str]):
        """
        Queue backfill jobs for missing dates.

        Args:
            missing_dates: List of date strings to backfill
        """
        logger.info(f"Queueing backfill for {len(missing_dates)} dates")

        for date in missing_dates:
            message = {
                'start_date': date,
                'end_date': date,
                'processor_name': self.__class__.__name__,
                'is_backfill': True,
                'trigger_reason': 'auto_backfill',
                'requested_at': datetime.utcnow().isoformat()
            }

            # Publish to backfill topic
            try:
                future = self.pubsub_client.publish(
                    self.backfill_topic,
                    json.dumps(message).encode('utf-8')
                )
                message_id = future.result(timeout=5)
                logger.info(f"Backfill queued for {date}, msg_id: {message_id}")

                # Track in BigQuery
                self._track_backfill_request(date)

            except Exception as e:
                logger.error(f"Failed to queue backfill for {date}: {e}")

    def _track_backfill_request(self, game_date: str):
        """Track backfill request for monitoring."""
        tracking_row = {
            'processor_name': self.__class__.__name__,
            'game_date': game_date,
            'request_type': 'auto',
            'priority': 'normal',
            'requested_at': datetime.utcnow().isoformat(),
            'requested_by': 'smart_backfill_detection',
            'status': 'queued',
            'metadata': json.dumps({
                'pattern': 'smart_backfill',
                'auto_queued': True
            })
        }

        try:
            errors = self.bq_client.insert_rows_json(
                f'{self.project_id}.nba_processing.backfill_requests',
                [tracking_row]
            )

            if errors:
                logger.error(f"Error tracking backfill: {errors}")
        except Exception as e:
            logger.error(f"Failed to track backfill request: {e}")
```

### Step 3: Add to Your Processor

```python
# data_processors/analytics/player_game_summary/player_game_summary_processor.py

from shared.processors.patterns.smart_backfill_mixin import SmartBackfillMixin
from data_processors.analytics.analytics_base import AnalyticsProcessorBase


class PlayerGameSummaryProcessor(SmartBackfillMixin, AnalyticsProcessorBase):
    """Player stats processor with smart backfill detection."""

    def __init__(self):
        super().__init__()
        self.table_name = 'player_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'

    # ✅ Configure backfill thresholds
    AUTO_BACKFILL_THRESHOLD = 3        # Auto-queue for gaps ≤3 days
    LOOKBACK_WINDOW_DAYS = 30          # Check last 30 days
    CRITICAL_LOOKBACK_DAYS = 10        # Last 10 days are critical
    MIN_RECORDS_PER_DATE = 100         # Expect at least 100 player records per day

    # Rest of processor implementation...
```

### Step 4: Create Backfill Worker (Cloud Function)

```python
# services/backfill-worker/main.py

import base64
import json
import logging
from google.cloud import bigquery
from importlib import import_module

logger = logging.getLogger(__name__)


def handle_backfill_request(event, context):
    """
    Cloud Function triggered by Pub/Sub backfill requests.

    Processes individual backfill jobs.
    """
    # Decode message
    message_data = base64.b64decode(event['data']).decode('utf-8')
    message = json.loads(message_data)

    processor_name = message['processor_name']
    start_date = message['start_date']
    end_date = message['end_date']

    logger.info(f"Processing backfill: {processor_name} for {start_date}")

    # Update status to processing
    bq_client = bigquery.Client()
    update_backfill_status(bq_client, processor_name, start_date, 'processing')

    try:
        # Get processor class
        processor_class = get_processor_class(processor_name)
        processor = processor_class()

        # Run backfill
        result = processor.run({
            'start_date': start_date,
            'end_date': end_date,
            'is_backfill': True,
            'trigger_reason': 'backfill'
        })

        if result:
            update_backfill_status(bq_client, processor_name, start_date, 'completed')
            logger.info(f"Backfill completed: {processor_name} for {start_date}")
        else:
            raise Exception("Processor returned False")

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        update_backfill_status(
            bq_client,
            processor_name,
            start_date,
            'failed',
            error_message=str(e)
        )
        raise


def get_processor_class(processor_name: str):
    """Import processor class dynamically."""
    # Map processor names to modules
    processors = {
        'PlayerGameSummaryProcessor': 'data_processors.analytics.player_game_summary.player_game_summary_processor',
        'TeamDefenseGameSummaryProcessor': 'data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor',
        # Add more as needed
    }

    module_path = processors.get(processor_name)
    if not module_path:
        raise ValueError(f"Unknown processor: {processor_name}")

    module = import_module(module_path)
    return getattr(module, processor_name)


def update_backfill_status(
    bq_client,
    processor_name: str,
    game_date: str,
    status: str,
    error_message: str = None
):
    """Update backfill request status in BigQuery."""
    if status == 'processing':
        query = f"""
        UPDATE `nba_processing.backfill_requests`
        SET status = 'processing', started_at = CURRENT_TIMESTAMP()
        WHERE processor_name = '{processor_name}'
          AND game_date = DATE('{game_date}')
          AND status = 'queued'
        """
    elif status == 'completed':
        query = f"""
        UPDATE `nba_processing.backfill_requests`
        SET status = 'completed', completed_at = CURRENT_TIMESTAMP()
        WHERE processor_name = '{processor_name}'
          AND game_date = DATE('{game_date}')
          AND status = 'processing'
        """
    elif status == 'failed':
        error_clause = f"'{error_message}'" if error_message else "NULL"
        query = f"""
        UPDATE `nba_processing.backfill_requests`
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP(), error_message = {error_clause}
        WHERE processor_name = '{processor_name}'
          AND game_date = DATE('{game_date}')
          AND status = 'processing'
        """

    bq_client.query(query)
```

**Deploy Cloud Function:**

```bash
cd services/backfill-worker

gcloud functions deploy backfill-worker \
  --runtime python39 \
  --trigger-topic nba-backfill-requests \
  --timeout 540 \
  --memory 2048MB \
  --entry-point handle_backfill_request
```

---

## Configuration Guide

### Threshold Tuning

**AUTO_BACKFILL_THRESHOLD:**
- **Conservative (2 days):** Only auto-backfill very small gaps
- **Balanced (3 days):** Good default - catches typical gaps
- **Aggressive (5-7 days):** Auto-backfill larger gaps

**LOOKBACK_WINDOW_DAYS:**
- Depends on your dependencies
- If you need 30-day rolling averages → set to 35+
- If you only need last 10 games → set to 15+
- **Recommended:** 30 days for most use cases

**CRITICAL_LOOKBACK_DAYS:**
- Window where gaps ALWAYS cause issues
- Recent missing data → immediate failure
- **Recommended:** 10-14 days

**MIN_RECORDS_PER_DATE:**
- Expected records per date
- Player processor: 200-400 records typical
- Team processor: 20-30 records typical
- Set to 50% of typical to catch severe gaps

---

## Monitoring

### Query: Gap Detection Frequency

```sql
-- How often are gaps detected?
SELECT
    DATE(run_date) as date,
    processor_name,
    COUNT(*) as gap_detections,
    SUM(JSON_EXTRACT_SCALAR(metadata, '$.gap_size')) as total_missing_dates
FROM `nba_processing.analytics_processor_runs`
WHERE skip_reason = 'backfill_queued'
  AND run_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY date, processor_name
ORDER BY date DESC, gap_detections DESC;
```

### Query: Backfill Success Rate

```sql
-- Are backfills completing successfully?
SELECT
    processor_name,
    status,
    COUNT(*) as count,
    AVG(TIMESTAMP_DIFF(completed_at, started_at, MINUTE)) as avg_duration_min
FROM `nba_processing.backfill_requests`
WHERE requested_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name, status
ORDER BY processor_name, status;
```

### Query: Time to Recovery

```sql
-- How long from gap detection to recovery?
WITH gaps AS (
    SELECT
        processor_name,
        DATE(run_date) as detection_date,
        JSON_EXTRACT_SCALAR(metadata, '$.missing_dates[0]') as first_missing_date,
        run_date as detected_at
    FROM `nba_processing.analytics_processor_runs`
    WHERE skip_reason = 'backfill_queued'
),
completions AS (
    SELECT
        processor_name,
        game_date,
        completed_at
    FROM `nba_processing.backfill_requests`
    WHERE status = 'completed'
)
SELECT
    g.processor_name,
    g.detection_date,
    AVG(TIMESTAMP_DIFF(c.completed_at, g.detected_at, MINUTE)) as avg_recovery_time_min
FROM gaps g
JOIN completions c
    ON g.processor_name = c.processor_name
    AND DATE(g.first_missing_date) = c.game_date
GROUP BY g.processor_name, g.detection_date
ORDER BY g.detection_date DESC;
```

---

## Expected Impact (If Implemented)

**Before:**
- Manual gap investigation: 1-2 hours/week
- Cascade failures: 3-5 days until noticed
- Delayed processing: Until manual intervention

**After:**
- Automatic gap detection: Real-time
- Auto-recovery: 5-10 minutes
- Manual work: 0 hours/week (for small gaps)

**Value:**
- ✅ 1-2 hours saved per week
- ✅ Zero cascade failures
- ✅ Faster recovery (minutes vs days)

---

## Decision Checklist

Before implementing, verify:

- [ ] Week 1-8 monitoring shows gap frequency > 3/week
- [ ] Manual backfill time > 30 min/week
- [ ] Dependency failures > 5% of runs
- [ ] ROI calculation shows value (> 1 hour saved/week)
- [ ] Considered simpler alternatives (better scraper reliability, dependency precheck improvements)

**If ANY unchecked:** Don't implement yet, continue monitoring

**If ALL checked:** Proceed with implementation

---

## Alternatives to Consider First

Before implementing Smart Backfill, try these simpler solutions:

**1. Better Dependency Precheck (Pattern #2)**
- We already have this (analytics_base.py:319-413)
- Shows clear errors when dependencies missing
- No new infrastructure needed

**2. Improve Scraper Reliability**
- Add retries to scrapers
- Better error handling
- May prevent gaps in first place

**3. Manual Backfill Script**
- Simple Python script to backfill date ranges
- Run manually when needed
- No complex infrastructure

**4. Better Alerting**
- Alert when dependency check fails
- Engineer responds manually
- Simpler than auto-backfill

**Only implement Smart Backfill if:**
- Manual backfill is frequent AND time-consuming
- Simple solutions don't address root cause

---

## Summary

**Status:** 💡 Can implement, but **WAIT for monitoring data**

**Prerequisites:**
- ✅ Week 1-8 monitoring shows gap frequency justifies complexity
- ✅ Manual backfill time > 30 min/week
- ✅ Dependency failures > 5% of runs

**Implementation effort:** 2-3 hours (infrastructure + mixin + worker)

**When to implement:** Week 4-8 (IF monitoring shows need)

**Expected value (if needed):**
- 1-2 hours saved per week
- Zero cascade failures
- Automatic recovery in minutes

**This document:** Reference material for IF gaps become a problem

**Next steps:**
1. **Week 1-8:** Monitor gap frequency with queries above
2. **Week 4:** Review data, check decision criteria
3. **Week 8:** Decide if implementation justified
4. **IF yes:** Implement using this guide

---

## References

- [Optimization Pattern Catalog](../reference/02-optimization-pattern-catalog.md) - Pattern #15
- [Dependency Precheck](02-dependency-precheck-comparison.md) - Simpler alternative
- [Phase 2→3 Roadmap](../architecture/09-phase2-phase3-implementation-roadmap.md) - Week 1-8 plan
- [Week 8 Decision Guide](../reference/04-week8-decision-guide.md) - Data-driven decisions

---

**Remember:** Don't implement based on fear of gaps - implement based on **measured frequency** of actual gaps! Week 1-8 monitoring will tell you if this is needed.
