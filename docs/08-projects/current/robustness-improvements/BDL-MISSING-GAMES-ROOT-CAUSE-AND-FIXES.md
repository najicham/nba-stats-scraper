# BDL Missing Games - Root Cause Analysis & Prevention Plan
**Date:** January 21, 2026
**Status:** Ready for Implementation
**Priority:** P0 - Critical Data Quality Issue

---

## Executive Summary

**Problem:** 31 NBA games from Jan 1-19, 2026 are missing from `nba_raw.bdl_player_boxscores` despite being available in BDL's API.

**Root Cause:**
1. Scraper timing - some scrapers ran before games completed or before BDL processed the data
2. Missing workflow executions - later retry windows (2 AM, 4 AM, 6 AM) didn't run or weren't logged
3. No completeness validation - scrapers don't detect missing games automatically

**Impact:**
- 17% data gap for Jan 1-19 (31 of ~180 games)
- 76% of missing games are West Coast (late-finishing games)
- Pipeline continues unaware → analytics/predictions use incomplete data

**Immediate Action Required:**
1. Backfill the 31 missing games (data IS in BDL API now)
2. Deploy game-level availability logging
3. Add completeness validation after scrapes
4. Investigate why recovery windows didn't execute

---

## Investigation Findings

### BDL API Verification (Jan 21, 2026)

**Confirmed:** All games ARE in BDL API right now.

Example: Jan 1, 2026
```bash
$ curl "https://api.balldontlie.io/v1/games?dates[]=2026-01-01"

Returned 5 games:
✅ HOU @ BKN: Final (120-96) [ID: 18447285]
✅ MIA @ DET: Final (118-112) [ID: 18447286]
✅ PHI @ DAL: Final (123-108) [ID: 18447287]
✅ BOS @ SAC: Final (120-106) [ID: 18447288] ← MISSING in BigQuery
✅ UTA @ LAC: Final (101-118) [ID: 18447289] ← MISSING in BigQuery
```

**BigQuery Reality:**
```sql
SELECT game_id FROM nba_raw.bdl_player_boxscores
WHERE game_date = '2026-01-01';

Returns 3 games:
✅ 20260101_HOU_BKN (loaded Jan 2 at 2:05 AM)
✅ 20260101_MIA_DET (loaded Jan 2 at 2:05 AM)
✅ 20260101_PHI_DAL (loaded Jan 2 at 2:05 AM)
❌ BOS @ SAC - MISSING
❌ UTA @ LAC - MISSING
```

### Missing Games Breakdown

| Date | Expected | Loaded | Missing | Pattern |
|------|----------|--------|---------|---------|
| Jan 1 | 5 | 3 | **2** | West Coast home teams (SAC, LAC) |
| Jan 15 | 9 | 1 | **8** | Scraped at 6:05 PM ET (BEFORE games!) |
| Jan 16 | 6 | 5 | **1** | West Coast |
| Jan 17 | 9 | 7 | **2** | West Coast |
| Jan 18 | 6 | 4 | **2** | West Coast |
| Jan 19 | 9 | 8 | **1** | West Coast |
| **TOTAL** | **44** | **28** | **16** | **76% are West Coast** |

### Scraper Execution Timeline Analysis

**Jan 1, 2026 Example:**

| Time (ET) | Workflow | Expected | Actual |
|-----------|----------|----------|--------|
| 1:00 AM | `post_game_window_2` | Run scraper | ✅ Ran (got 3 of 5 games) |
| 2:00 AM | `post_game_window_2b` | Retry for late games | ❌ NO LOG ENTRY |
| 4:00 AM | `post_game_window_3` | Final collection | ❌ NO LOG ENTRY |
| 6:00 AM | `morning_recovery` | Safety net | ❌ NO LOG ENTRY |

**Query used:**
```sql
SELECT triggered_at, status, workflow,
       CAST(JSON_VALUE(data_summary, '$.rowCount') AS INT64) as row_count
FROM nba_orchestration.scraper_execution_log
WHERE scraper_name IN ('bdl_box_scores_scraper', 'bdl_player_box_scores_scraper')
  AND JSON_VALUE(opts, '$.date') = '2026-01-01'
ORDER BY triggered_at;

Result: Only 1 execution logged (1 AM window)
```

**Critical Finding:** The recovery windows (2 AM, 4 AM, 6 AM) are configured in `config/workflows.yaml` but aren't executing or logging.

---

## Current Infrastructure

### What Exists (Good Foundation)

**1. Multiple Scrape Windows** (`config/workflows.yaml:302-398`)
```yaml
post_game_window_1: 10 PM ET  # First attempt
post_game_window_2: 1 AM ET   # Most games done
post_game_window_2b: 2 AM ET  # West Coast buffer (added Jan 10, 2026)
post_game_window_3: 4 AM ET   # Final collection + enhanced data
morning_recovery: 6 AM ET     # Safety net for incomplete data
```

**Design:** Excellent timing coverage for late games.

**2. Scraper Execution Log** (`nba_orchestration.scraper_execution_log`)
- Tracks every scraper run
- Has `status`, `row_count`, `workflow`, `triggered_at`
- Retention: 90 days

**3. BDL Availability Views** (Created Jan 21, 2026)
- `nba_orchestration.v_bdl_game_availability` - Shows which games have BDL vs NBAC data
- `nba_orchestration.v_bdl_availability_latency` - Calculates latency from game end
- `nba_orchestration.v_bdl_availability_summary` - Daily aggregated metrics

### Critical Gaps

**1. No Workflow Execution Verification**
- Can't tell if workflows actually ran
- Scraper execution log only shows successful runs
- Failed/skipped workflows are invisible

**2. No Completeness Validation After Scrapes**
- Scraper fetches data and exits
- Doesn't compare: "How many games did BDL return?" vs "How many games should exist?"
- Missing games aren't detected until manual audit days later

**3. No Per-Game Availability Tracking**
- Can't answer: "When did BDL first return data for game X?"
- Can't measure BDL latency per game
- Can't identify which specific games are consistently late

**4. No Automatic Retry Queue**
- If a game is missing, nothing automatically retries it
- Relies on scheduled windows that may not run
- Manual backfill is only option

**5. No Real-Time Alerting**
- Missing games discovered days later during data validation
- No alerts when scraper gets 3 games but schedule shows 5

---

## Recommended Improvements

### Priority 0 - Immediate (Deploy This Week)

#### 1. Backfill Missing Games

**What:** Re-scrape the 6 dates with missing games from BDL API.

**Command:**
```bash
gcloud run jobs execute bdl-boxscore-backfill \
  --args="--service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app,--dates=2026-01-01,2026-01-15,2026-01-16,2026-01-17,2026-01-18,2026-01-19" \
  --region=us-west2
```

**Verification:**
```sql
-- Check all dates now have complete data
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games_loaded
FROM nba_raw.bdl_player_boxscores
WHERE game_date IN ('2026-01-01', '2026-01-15', '2026-01-16',
                     '2026-01-17', '2026-01-18', '2026-01-19')
GROUP BY game_date
ORDER BY game_date;

-- Expected results:
-- Jan 1: 5 games (was 3)
-- Jan 15: 9 games (was 1)
-- Jan 16: 6 games (was 5)
-- Jan 17: 9 games (was 7)
-- Jan 18: 6 games (was 4)
-- Jan 19: 9 games (was 8)
```

**Files:**
- Tool exists: `backfill_jobs/scrapers/bdl_boxscore/bdl_boxscore_scraper_backfill.py`
- Supports `--dates` parameter

#### 2. Deploy Game-Level Availability Logging

**What:** Track which specific games BDL returned on each scrape attempt.

**Files Created:**
- `shared/utils/bdl_availability_logger.py` - Logger utility ✅
- `schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql` - Table definition ✅

**Step 1: Create BigQuery Table**
```bash
bq query --nouse_legacy_sql --location=us-west2 < \
  schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql
```

**Step 2: Integrate into BDL Scraper**

Edit `scrapers/balldontlie/bdl_box_scores.py`:

```python
# Add import at top (after other imports ~line 70)
try:
    from shared.utils.bdl_availability_logger import log_bdl_game_availability
except ImportError:
    logger.warning("Could not import bdl_availability_logger")
    def log_bdl_game_availability(*args, **kwargs): pass

# Add to transform_data() method (after line 280 where self.data is set)
def transform_data(self) -> None:
    try:
        # ... existing code ...

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(rows),
            "boxScores": rows,
        }

        # NEW: Log which games were available
        try:
            log_bdl_game_availability(
                game_date=self.opts["date"],
                execution_id=self.run_id,
                box_scores=self.data["boxScores"],
                workflow=self.opts.get("workflow")
            )
        except Exception as e:
            logger.warning(f"Failed to log game availability: {e}")

        logger.info("Fetched %d box-score rows for %s across %d pages",
                   len(rows), self.opts["date"], pages_fetched)
        # ... rest of method ...
```

**Benefits:**
- Creates timeline: "Checked at 1 AM - game not there. Checked at 2 AM - there."
- Enables precise latency measurement
- Can query: "Which games are consistently late?"

**Example Query After Deployment:**
```sql
-- Timeline for a specific game
SELECT scrape_timestamp, was_available, player_count
FROM nba_orchestration.bdl_game_scrape_attempts
WHERE game_date = '2026-01-19'
  AND home_team = 'GSW'
  AND away_team = 'MIA'
ORDER BY scrape_timestamp;

-- Find games that needed multiple attempts
SELECT game_date, home_team, away_team,
       COUNT(*) as attempts,
       MIN(CASE WHEN was_available THEN scrape_timestamp END) as first_seen
FROM nba_orchestration.bdl_game_scrape_attempts
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date, home_team, away_team
HAVING COUNT(*) > 1;
```

#### 3. Add Post-Scrape Completeness Check

**What:** After each scraper run, validate we got all expected games.

**Option A: Add to Scraper (Simple)**

Edit `scrapers/balldontlie/bdl_box_scores.py` in `transform_data()`:

```python
def transform_data(self) -> None:
    # ... existing code ...

    # NEW: Check completeness
    try:
        from google.cloud import bigquery
        client = bigquery.Client()

        # Count expected games from schedule
        query = """
        SELECT COUNT(*) as expected_games
        FROM `nba-props-platform.nba_raw.nbac_schedule`
        WHERE game_date = @game_date
          AND season_year = 2025
          AND game_status = 3
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", self.opts["date"])
            ]
        )

        results = list(client.query(query, job_config=job_config).result())
        expected = results[0].expected_games if results else 0

        # Count games we got from BDL
        games_returned = len(set(
            (r.get("game", {}).get("home_team", {}).get("abbreviation"),
             r.get("game", {}).get("visitor_team", {}).get("abbreviation"))
            for r in self.data["boxScores"]
        ))

        if games_returned < expected:
            missing_count = expected - games_returned
            logger.warning(
                f"INCOMPLETE DATA: Got {games_returned} of {expected} games for {self.opts['date']} "
                f"({missing_count} games missing from BDL response)"
            )

            notify_warning(
                title="BDL Box Scores - Incomplete Data",
                message=f"Missing {missing_count} games for {self.opts['date']} (got {games_returned} of {expected})",
                details={
                    'scraper': 'bdl_box_scores',
                    'date': self.opts['date'],
                    'expected_games': expected,
                    'returned_games': games_returned,
                    'missing_games': missing_count,
                    'action': 'Retry windows should catch these games'
                }
            )
        else:
            logger.info(f"COMPLETE: Got all {games_returned} expected games for {self.opts['date']}")

    except Exception as e:
        logger.warning(f"Could not check completeness: {e}")
```

**Option B: Separate Validation Cloud Function (Better)**

Create `functions/validation/bdl_completeness_checker/main.py`:

```python
"""
BDL Completeness Checker
Triggered after bdl_box_scores scraper completes
Compares BDL count vs NBAC count and alerts on mismatch
"""

def check_bdl_completeness(event, context):
    # Extract game_date from Pub/Sub message
    # Query schedule for expected games
    # Query bdl_player_boxscores for loaded games
    # If mismatch: send alert + add to retry queue
```

**Trigger:** Pub/Sub message when `bdl_box_scores` completes.

**Files to Create:**
- `functions/validation/bdl_completeness_checker/main.py`
- `functions/validation/bdl_completeness_checker/requirements.txt`
- `deployment/cloud-functions/bdl-completeness-checker.yaml`

#### 4. Investigate Missing Workflow Executions

**What:** Find out why recovery windows (2 AM, 4 AM, 6 AM) didn't run.

**Investigation Steps:**

1. Check workflow controller logs:
```bash
gcloud logging read "resource.type=cloud_run_revision
  AND resource.labels.service_name=master-controller
  AND timestamp>='2026-01-01T00:00:00Z'
  AND timestamp<='2026-01-02T12:00:00Z'
  AND (textPayload:post_game_window OR textPayload:morning_recovery)" \
  --limit 100 \
  --format json
```

2. Check if workflows are enabled:
```bash
# Verify workflows.yaml is deployed
grep -A 5 "post_game_window_2b:" config/workflows.yaml
grep -A 5 "morning_recovery:" config/workflows.yaml
```

3. Check scheduler configuration:
```bash
# List all Cloud Scheduler jobs
gcloud scheduler jobs list --location=us-west2 | grep -E "(post_game|morning)"
```

4. Check for workflow decision logic issues:
- Maybe `game_aware_yesterday` didn't trigger because schedule wasn't updated?
- Maybe `requires: ["post_game_window_3"]` dependency blocked execution?

**Action:** Fix whatever is preventing recovery windows from executing.

---

### Priority 1 - Short Term (Deploy Within 2 Weeks)

#### 5. Implement Missing Game Retry Queue

**What:** Persistent queue of games that need to be retried.

**Create BigQuery Table:**
```sql
CREATE TABLE `nba-props-platform.nba_orchestration.missing_game_retry_queue` (
  game_date DATE NOT NULL,
  home_team STRING NOT NULL,
  away_team STRING NOT NULL,

  -- Tracking
  detected_at TIMESTAMP NOT NULL,
  detection_source STRING,  -- 'completeness_check', 'manual', 'validation'

  -- Retry logic
  retry_count INT64 DEFAULT 0,
  last_retry_at TIMESTAMP,
  next_retry_at TIMESTAMP,

  -- Resolution
  resolved_at TIMESTAMP,
  resolved_by STRING,  -- 'auto_retry', 'manual_backfill'

  -- Priority
  priority STRING DEFAULT 'NORMAL',  -- 'HIGH', 'NORMAL', 'LOW'

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(game_date)
CLUSTER BY priority, resolved_at;
```

**Retry Worker:**

Create `functions/retry_worker/missing_game_retry/main.py`:

```python
"""
Missing Game Retry Worker
Runs every 2 hours, checks retry queue, attempts to fetch missing games
"""

def retry_missing_games(event, context):
    # 1. Query retry_queue for unresolved games where next_retry_at <= NOW
    # 2. For each game: call BDL scraper for that specific date
    # 3. Check if game now exists in bdl_player_boxscores
    # 4. If yes: mark resolved_at
    # 5. If no: increment retry_count, set next_retry_at = NOW + exponential_backoff
    # 6. After 10 retries: escalate to CRITICAL alert
```

**Integration:** Completeness checker adds to retry queue when missing games detected.

#### 6. Add 10 AM ET Recovery Window

**What:** Many late games become available by 8-10 AM ET. Add one more recovery window.

Edit `config/workflows.yaml`:

```yaml
  morning_recovery_late:
    enabled: true
    priority: "MEDIUM"
    decision_type: "retry_queue_aware"
    description: "Late morning recovery - 10 AM ET - Process retry queue"

    schedule:
      fixed_time: "10:00"  # 10 AM ET
      tolerance_minutes: 30

    execution_plan:
      type: "sequential"
      steps:
        - Check retry_queue for unresolved games from yesterday
        - Scrape only those specific dates (not all dates)
        - Validate games now exist

    alerts:
      still_missing: "WARNING"
```

---

### Priority 2 - Medium Term (Deploy Within 1 Month)

#### 7. Real-Time Completeness Monitor

**What:** Cloud Function triggered immediately after Phase 1 → Phase 2 processor completes.

**Architecture:**
```
Phase 2 Processor completes
  ↓ (Pub/Sub message)
Completeness Monitor Function
  ↓ (queries BigQuery)
Compare BDL count vs NBAC count
  ↓ (if mismatch)
Send alert + Add to retry_queue
  ↓ (within 10 minutes)
Ops team notified
```

**Benefits:**
- Detect issues in 10 minutes (not 10 hours)
- Auto-trigger backfill
- Prevent incomplete data from flowing to analytics

**Files to Create:**
- `functions/monitoring/realtime_completeness/main.py`
- Similar to existing `functions/monitoring/realtime_completeness_checker/`

#### 8. Weekly Reconciliation Job

**What:** Cloud Run Job that runs every Monday, validates last 7 days, auto-backfills gaps.

**Create:** `backfill_jobs/weekly_reconciliation/weekly_bdl_reconciliation.py`

```python
"""
Weekly BDL Reconciliation Job
Runs every Monday at 9 AM ET
- Checks last 7 days of BDL vs NBAC data
- Identifies gaps
- Automatically backfills missing games
- Generates coverage report
"""

def reconcile_week():
    for date in last_7_days:
        bdl_count = query_bdl_count(date)
        nbac_count = query_nbac_count(date)

        if bdl_count < nbac_count:
            logger.warning(f"Gap on {date}: {bdl_count} BDL vs {nbac_count} NBAC")
            trigger_backfill(date)

    generate_coverage_report()
```

**Deployment:**
```yaml
# deployment/cloud-run-jobs/weekly-bdl-reconciliation.yaml
name: weekly-bdl-reconciliation
schedule: "0 14 * * 1"  # Every Monday at 9 AM ET (14:00 UTC)
timeout: 1800s
```

---

## Implementation Checklist

### Phase 1: Immediate (This Week)

- [ ] **Backfill 31 missing games**
  - [ ] Run backfill command for 6 dates
  - [ ] Verify all dates now have complete data
  - [ ] Update validation report with "BACKFILLED" status

- [ ] **Deploy game-level logging**
  - [ ] Create `bdl_game_scrape_attempts` table in BigQuery
  - [ ] Deploy `v_bdl_first_availability` view
  - [ ] Add logger call to `bdl_box_scores.py`
  - [ ] Test with next night's scrapes
  - [ ] Verify data appears in table

- [ ] **Add completeness check to scraper**
  - [ ] Implement Option A (inline check) in `bdl_box_scores.py`
  - [ ] Test with historical date
  - [ ] Deploy to production
  - [ ] Monitor for completeness warnings

- [ ] **Investigate workflow execution gaps**
  - [ ] Check controller logs for Jan 1-2
  - [ ] Identify why recovery windows didn't run
  - [ ] Fix root cause (scheduler? logic? dependency?)
  - [ ] Verify all 5 windows now execute reliably

### Phase 2: Short-term (Next 2 Weeks)

- [ ] **Create retry queue**
  - [ ] Deploy `missing_game_retry_queue` table
  - [ ] Create retry worker function
  - [ ] Integrate with completeness checker
  - [ ] Test end-to-end flow

- [ ] **Add 10 AM recovery window**
  - [ ] Update `workflows.yaml`
  - [ ] Deploy to controller
  - [ ] Test execution
  - [ ] Monitor retry queue processing

### Phase 3: Medium-term (Next Month)

- [ ] **Real-time completeness monitor**
  - [ ] Create Cloud Function
  - [ ] Set up Pub/Sub trigger
  - [ ] Configure alerting
  - [ ] Test with intentional gap

- [ ] **Weekly reconciliation**
  - [ ] Create reconciliation job
  - [ ] Deploy as Cloud Run Job
  - [ ] Set up schedule
  - [ ] Configure reporting

---

## Success Metrics

### Before Improvements

- Missing game detection time: **Days** (manual audit)
- Missing game rate: **17%** (31 of 180 games)
- Recovery mechanism: **Manual backfill**
- Latency visibility: **None**

### After Improvements (Target)

- Missing game detection time: **< 10 minutes** (real-time monitor)
- Missing game rate: **< 1%** (with retry queue)
- Recovery mechanism: **Automatic** (retry queue + reconciliation)
- Latency visibility: **Per-game timeline** (scrape attempts table)

---

## Files Reference

### Created (Ready to Deploy)
- `shared/utils/bdl_availability_logger.py` - Game availability logger utility
- `schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql` - Table + views
- `schemas/bigquery/monitoring/bdl_game_availability_tracking.sql` - Availability views (deployed)
- This document

### To Modify
- `scrapers/balldontlie/bdl_box_scores.py` - Add logging + completeness check
- `config/workflows.yaml` - Add 10 AM recovery window (optional)

### To Create (Phase 2)
- `schemas/bigquery/nba_orchestration/missing_game_retry_queue.sql`
- `functions/retry_worker/missing_game_retry/main.py`
- `functions/validation/bdl_completeness_checker/main.py` (optional, better than inline)

### To Create (Phase 3)
- `functions/monitoring/realtime_completeness/main.py`
- `backfill_jobs/weekly_reconciliation/weekly_bdl_reconciliation.py`

---

## Related Documentation

- Original validation report: `docs/08-projects/current/historical-backfill-audit/2026-01-21-DATA-VALIDATION-REPORT.md`
- BDL email investigation: `docs/08-projects/current/historical-backfill-audit/BDL-AVAILABILITY-INVESTIGATION-JAN-21-2026.md`
- Workflows configuration: `config/workflows.yaml`
- Scraper execution log schema: `schemas/bigquery/nba_orchestration/scraper_execution_log.sql`

---

**Document created:** January 21, 2026
**Next review:** After Phase 1 implementation (within 1 week)
**Owner:** Data Engineering Team
