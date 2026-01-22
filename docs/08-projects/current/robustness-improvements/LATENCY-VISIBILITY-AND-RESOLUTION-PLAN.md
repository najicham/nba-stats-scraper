# Latency Visibility & Resolution - Comprehensive Implementation Plan
**Date:** January 21, 2026
**Status:** Ready for Implementation
**Priority:** P0 - Critical for Production Data Quality

---

## Executive Summary

This plan synthesizes findings from multiple investigation sessions to create a unified strategy for improving scraper latency visibility and automated issue resolution.

### Current Situation

**What Exists (Strong Foundation):**
- ✅ Comprehensive BigQuery monitoring views deployed (BDL, NBAC, OddsAPI availability + latency)
- ✅ Phase boundary validation system deployed to staging
- ✅ Multi-window retry strategy configured (1 AM, 2 AM, 4 AM, 6 AM ET)
- ✅ Rate limiting and circuit breaker infrastructure
- ✅ Scraper execution logging to BigQuery
- ✅ End-to-end pipeline latency tracking (Phase 1-6)

**Critical Gaps:**
- ❌ **Scraper availability monitor not deployed** - Daily alerts ready but inactive
- ❌ **BDL availability logger not integrated** - Per-game tracking code exists but unused
- ❌ **No automated completeness validation** - Missing games discovered days later
- ❌ **No retry queue** - Manual backfills required for every gap
- ❌ **Recovery windows may not be executing** - Only 1 AM window logs found
- ❌ **BDL systematic data gaps** - 30-40% missing games (ongoing issue)

### This Plan's Approach

Rather than building everything from scratch, this plan:
1. **Activates what exists** - Deploy ready-to-go monitoring (15 mins)
2. **Completes what's started** - Integrate BDL logger into scrapers (30 mins)
3. **Fills critical gaps** - Add completeness validation + retry queue (4 hours)
4. **Investigates root causes** - Fix workflow execution issues (2 hours)
5. **Expands coverage** - Apply patterns to NBAC, OddsAPI (6 hours)

**Expected ROI:**
- Detection time: Days → < 10 minutes
- Missing game rate: 17% → < 1%
- Recovery: Manual → 80%+ automatic

---

## Phase 0: Deploy What Exists (Week 1, Day 1 - 30 minutes)

**Goal:** Activate already-built monitoring for immediate visibility

### 0.1 Deploy Scraper Availability Monitor ⏰ 15 mins

**Status:** Code complete, deploy script ready

**Action:**
```bash
cd orchestration/cloud_functions/scraper_availability_monitor
./deploy.sh --scheduler
```

**What This Gives You:**
- Daily 8 AM ET Slack alerts showing:
  - BDL, NBAC, OddsAPI coverage percentages
  - Missing matchups (up to 5 listed + count)
  - West Coast pattern analysis
  - Average latency metrics
- Alert routing:
  - CRITICAL (< 50% BDL, < 80% NBAC) → `#app-error-alerts` + email
  - WARNING (< 90% BDL) → `#nba-alerts`
  - OK → Silent (logged to Firestore only)
- Historical tracking in Firestore `scraper_availability_checks`

**Immediate Benefit:** Tomorrow morning you'll know if tonight's games (Jan 21) have BDL issues

**Files:**
- `orchestration/cloud_functions/scraper_availability_monitor/main.py`
- `orchestration/cloud_functions/scraper_availability_monitor/deploy.sh`

### 0.2 Verify Monitoring Views ⏰ 5 mins

**Check all views exist:**
```sql
-- Should return 3 views
SELECT table_name
FROM `nba-props-platform.nba_orchestration.INFORMATION_SCHEMA.VIEWS`
WHERE table_name LIKE 'v_%availability%';

-- Test daily summary
SELECT * FROM nba_orchestration.v_scraper_availability_daily_summary
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
LIMIT 1;
```

**Expected output:**
- `v_scraper_game_availability`
- `v_scraper_availability_daily_summary`
- `v_bdl_game_availability` (plus 2 more BDL views)

### 0.3 Set Up Daily Monitoring Queries ⏰ 10 mins

**Create monitoring dashboard file:**
```bash
# File: monitoring/daily_scraper_health.sql
```

```sql
-- Daily Scraper Health Dashboard
-- Run every morning at 9 AM ET to check yesterday's data

-- 1. Overall Coverage Summary
SELECT
  game_date,
  total_games,
  bdl_games_available,
  nbac_games_available,
  bdl_coverage_pct,
  nbac_coverage_pct,
  alert_level,
  CASE
    WHEN alert_level = 'CRITICAL' THEN '🚨'
    WHEN alert_level = 'WARNING' THEN '⚠️'
    ELSE '✅'
  END as status
FROM nba_orchestration.v_scraper_availability_daily_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC;

-- 2. Missing Games Detail
SELECT
  game_date,
  matchup,
  bdl_available,
  nbac_available,
  oddsapi_available,
  first_available_source,
  hours_since_game_end,
  availability_status
FROM nba_orchestration.v_scraper_game_availability
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND availability_status IN ('WARNING', 'CRITICAL')
ORDER BY game_date DESC, matchup;

-- 3. Latency Trends
SELECT
  game_date,
  ROUND(AVG(bdl_latency_hours), 1) as avg_bdl_latency_h,
  ROUND(AVG(nbac_latency_hours), 1) as avg_nbac_latency_h,
  COUNT(CASE WHEN bdl_latency_hours > 4 THEN 1 END) as bdl_slow_count,
  COUNT(CASE WHEN nbac_latency_hours > 2 THEN 1 END) as nbac_slow_count
FROM nba_orchestration.v_scraper_game_availability
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND bdl_available
GROUP BY game_date
ORDER BY game_date DESC;
```

**Save as:** `monitoring/daily_scraper_health.sql`

---

## Phase 1: Integrate BDL Availability Logger (Week 1, Day 1-2 - 2 hours)

**Goal:** Get per-scrape-attempt visibility into BDL availability

### 1.1 Deploy BDL Game Scrape Attempts Table ⏰ 5 mins

**Action:**
```bash
bq query --nouse_legacy_sql --location=us-west2 < \
  schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql
```

**Verify:**
```bash
bq show nba-props-platform:nba_orchestration.bdl_game_scrape_attempts
```

### 1.2 Integrate Logger into BDL Box Scores Scraper ⏰ 30 mins

**File:** `scrapers/balldontlie/bdl_box_scores.py`

**Location:** In `transform_data()` method, after `self.data` is set

**Add import at top (after existing imports around line 70):**
```python
try:
    from shared.utils.bdl_availability_logger import log_bdl_game_availability
except ImportError:
    logger.warning("Could not import bdl_availability_logger - game availability tracking disabled")
    def log_bdl_game_availability(*args, **kwargs):
        pass
```

**Add logging call in `transform_data()` method (after line ~280):**
```python
def transform_data(self) -> None:
    try:
        # ... existing code that sets self.data ...

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rowCount": len(rows),
            "boxScores": rows,
        }

        # NEW: Log which games were available from BDL
        try:
            log_bdl_game_availability(
                game_date=self.opts["date"],
                execution_id=self.run_id,
                box_scores=self.data["boxScores"],
                workflow=self.opts.get("workflow", "unknown")
            )
            logger.info(f"Logged BDL game availability for {self.opts['date']}")
        except Exception as e:
            logger.warning(f"Failed to log BDL game availability: {e}", exc_info=True)

        logger.info("Fetched %d box-score rows for %s across %d pages",
                   len(rows), self.opts["date"], pages_fetched)
        # ... rest of method ...
```

### 1.3 Test Locally ⏰ 15 mins

**Test with recent date:**
```bash
cd scrapers
python balldontlie/bdl_box_scores.py --date 2026-01-20 --debug

# Check data appeared
bq query --nouse_legacy_sql --location=us-west2 "
SELECT
  scrape_timestamp,
  game_date,
  home_team,
  away_team,
  was_available,
  player_count,
  is_west_coast
FROM nba_orchestration.bdl_game_scrape_attempts
WHERE game_date = '2026-01-20'
ORDER BY scrape_timestamp DESC
LIMIT 10"
```

**Expected:** 7 rows (one per game for Jan 20)

### 1.4 Deploy to Production ⏰ 10 mins

**Your deployment process** (adapt to your CI/CD):
```bash
# Example if using Cloud Run
gcloud run deploy nba-scrapers \
  --source=. \
  --region=us-west2 \
  --memory=2Gi

# Or if using Cloud Functions
gcloud functions deploy bdl-box-scores-scraper \
  --source=scrapers/ \
  --entry-point=main \
  --runtime=python312
```

### 1.5 Create BDL Latency Analysis Query ⏰ 30 mins

**Save as:** `monitoring/bdl_latency_analysis.sql`

```sql
-- BDL Latency Analysis - Per-Game Timeline
-- Shows when we checked for games and when they appeared

WITH game_timeline AS (
  SELECT
    game_date,
    home_team,
    away_team,
    matchup,
    scrape_timestamp,
    was_available,
    player_count,
    workflow,
    estimated_end_time,
    TIMESTAMP_DIFF(scrape_timestamp, estimated_end_time, MINUTE) as minutes_after_game_end,
    ROW_NUMBER() OVER (
      PARTITION BY game_date, home_team, away_team
      ORDER BY scrape_timestamp
    ) as attempt_number
  FROM nba_orchestration.bdl_game_scrape_attempts
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),
first_available AS (
  SELECT
    game_date,
    home_team,
    away_team,
    MIN(scrape_timestamp) FILTER (WHERE was_available) as first_seen_at,
    COUNT(*) as total_attempts,
    COUNTIF(was_available) as successful_attempts,
    COUNTIF(NOT was_available) as failed_attempts
  FROM game_timeline
  GROUP BY game_date, home_team, away_team
)
SELECT
  t.game_date,
  t.matchup,
  t.attempt_number,
  t.workflow,
  FORMAT_TIMESTAMP('%H:%M ET', t.scrape_timestamp, 'America/New_York') as checked_at,
  t.was_available,
  t.player_count,
  t.minutes_after_game_end,
  f.total_attempts,
  f.first_seen_at,
  CASE
    WHEN t.was_available AND t.scrape_timestamp = f.first_seen_at THEN '✅ FIRST SEEN HERE'
    WHEN t.was_available THEN '✓ Available'
    ELSE '❌ Not available'
  END as status
FROM game_timeline t
LEFT JOIN first_available f USING (game_date, home_team, away_team)
WHERE t.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
ORDER BY t.game_date DESC, t.matchup, t.attempt_number;
```

**Use case:** Understand exactly when games became available in BDL API

---

## Phase 2: Add Completeness Validation (Week 1, Day 2-3 - 4 hours)

**Goal:** Detect missing games immediately after each scrape

### 2.1 Create Completeness Validator Utility ⏰ 1.5 hours

**New File:** `shared/validation/scraper_completeness_validator.py`

```python
"""
Scraper Completeness Validator

Validates that scrapers retrieved all expected games by comparing
actual games returned vs expected games from schedule.

Usage:
    from shared.validation.scraper_completeness_validator import validate_completeness

    validate_completeness(
        game_date='2026-01-20',
        games_returned=4,
        source='BDL',
        notify_on_incomplete=True
    )
"""

from typing import Dict, List, Optional
from google.cloud import bigquery
from datetime import date
import logging

logger = logging.getLogger(__name__)

# Import notification system
try:
    from shared.utils.notification_system import notify_warning, notify_error
except ImportError:
    def notify_warning(*args, **kwargs): pass
    def notify_error(*args, **kwargs): pass


class CompletenessResult:
    """Result of completeness validation"""
    def __init__(self, expected: int, actual: int, missing_games: List[Dict] = None):
        self.expected = expected
        self.actual = actual
        self.missing_games = missing_games or []
        self.is_complete = actual >= expected
        self.completeness_pct = (actual / expected * 100) if expected > 0 else 0
        self.missing_count = max(0, expected - actual)

    def __repr__(self):
        status = "✅ COMPLETE" if self.is_complete else f"⚠️ INCOMPLETE ({self.missing_count} missing)"
        return f"<CompletenessResult {self.actual}/{self.expected} games - {status}>"


def get_expected_game_count(game_date: str) -> int:
    """
    Query schedule to get expected number of games for a date.

    Args:
        game_date: Date in 'YYYY-MM-DD' format

    Returns:
        Number of games scheduled (game_status = 3 = Final)
    """
    client = bigquery.Client()

    query = """
    SELECT COUNT(*) as expected_games
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE game_date = @game_date
      AND season_year = 2025
      AND game_status = 3
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    try:
        results = list(client.query(query, job_config=job_config).result())
        expected = results[0].expected_games if results else 0
        logger.info(f"Expected {expected} games for {game_date}")
        return expected
    except Exception as e:
        logger.error(f"Failed to query expected game count: {e}")
        return 0


def identify_missing_games(game_date: str, source: str) -> List[Dict]:
    """
    Identify which specific games are missing from a source.

    Args:
        game_date: Date in 'YYYY-MM-DD' format
        source: 'BDL', 'NBAC', or 'ODDSAPI'

    Returns:
        List of missing games with home_team, away_team, matchup
    """
    client = bigquery.Client()

    # Map source to table
    source_tables = {
        'BDL': 'nba_raw.bdl_player_boxscores',
        'NBAC': 'nba_raw.nbac_gamebook_player_stats',
        'ODDSAPI': 'nba_raw.oddsapi_events'
    }

    if source not in source_tables:
        logger.warning(f"Unknown source: {source}")
        return []

    query = f"""
    SELECT
      s.home_team,
      s.away_team,
      CONCAT(s.away_team, ' @ ', s.home_team) as matchup,
      s.game_date,
      s.arena_timezone
    FROM `nba-props-platform.nba_raw.nbac_schedule` s
    LEFT JOIN `nba-props-platform.{source_tables[source]}` d
      ON s.game_id = d.game_id AND s.game_date = d.game_date
    WHERE s.game_date = @game_date
      AND s.season_year = 2025
      AND s.game_status = 3
      AND d.game_id IS NULL  -- Missing from source
    ORDER BY s.home_team
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    try:
        results = client.query(query, job_config=job_config).result()
        missing_games = [dict(row) for row in results]
        logger.info(f"Found {len(missing_games)} missing games from {source} for {game_date}")
        return missing_games
    except Exception as e:
        logger.error(f"Failed to identify missing games: {e}")
        return []


def validate_completeness(
    game_date: str,
    games_returned: int,
    source: str = 'BDL',
    notify_on_incomplete: bool = True,
    completeness_threshold: float = 0.9
) -> CompletenessResult:
    """
    Validate scraper completeness by comparing actual vs expected games.

    Args:
        game_date: Date scraped ('YYYY-MM-DD')
        games_returned: Number of games the scraper found
        source: Data source ('BDL', 'NBAC', 'ODDSAPI')
        notify_on_incomplete: Send Slack alert if incomplete
        completeness_threshold: Minimum acceptable completeness (0.9 = 90%)

    Returns:
        CompletenessResult with validation outcome
    """
    expected = get_expected_game_count(game_date)

    # Handle edge case: no games scheduled
    if expected == 0:
        logger.info(f"No games scheduled for {game_date}")
        return CompletenessResult(expected=0, actual=games_returned)

    # Calculate completeness
    result = CompletenessResult(expected=expected, actual=games_returned)

    # Check if incomplete
    if not result.is_complete:
        # Identify which games are missing
        result.missing_games = identify_missing_games(game_date, source)

        # Determine severity
        is_critical = result.completeness_pct < (completeness_threshold * 100)

        # Build alert message
        message = (
            f"{source} Box Scores - Incomplete Data for {game_date}\n"
            f"Expected: {expected} games\n"
            f"Returned: {games_returned} games\n"
            f"Missing: {result.missing_count} games ({result.completeness_pct:.1f}% complete)"
        )

        details = {
            'source': source,
            'game_date': game_date,
            'expected_games': expected,
            'returned_games': games_returned,
            'missing_count': result.missing_count,
            'completeness_pct': result.completeness_pct,
            'missing_matchups': [g['matchup'] for g in result.missing_games[:10]],  # Limit to 10
            'action': 'Retry windows should catch these games. Check logs at next window (2 AM, 4 AM, 6 AM ET).'
        }

        # Send notification
        if notify_on_incomplete:
            if is_critical:
                notify_error(
                    title=f"{source} Critical Data Gap - {game_date}",
                    message=message,
                    details=details
                )
            else:
                notify_warning(
                    title=f"{source} Incomplete Data - {game_date}",
                    message=message,
                    details=details
                )

        # Log result
        logger.warning(
            f"INCOMPLETE DATA: {source} returned {games_returned} of {expected} games for {game_date} "
            f"({result.missing_count} missing, {result.completeness_pct:.1f}% complete)"
        )
    else:
        logger.info(
            f"COMPLETE: {source} returned all {games_returned} expected games for {game_date}"
        )

    return result
```

### 2.2 Integrate into BDL Box Scores Scraper ⏰ 30 mins

**File:** `scrapers/balldontlie/bdl_box_scores.py`

**Add import:**
```python
from shared.validation.scraper_completeness_validator import validate_completeness
```

**Add validation in `transform_data()` after data logging:**
```python
def transform_data(self) -> None:
    # ... existing code ...

    self.data = {
        "date": self.opts["date"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rowCount": len(rows),
        "boxScores": rows,
    }

    # Log game availability (from Phase 1)
    try:
        log_bdl_game_availability(...)
    except Exception as e:
        logger.warning(f"Failed to log game availability: {e}")

    # NEW: Validate completeness
    try:
        # Count unique games in response
        games_returned = len(set(
            (r.get("game", {}).get("home_team", {}).get("abbreviation"),
             r.get("game", {}).get("visitor_team", {}).get("abbreviation"))
            for r in self.data["boxScores"]
        ))

        # Validate
        result = validate_completeness(
            game_date=self.opts["date"],
            games_returned=games_returned,
            source='BDL',
            notify_on_incomplete=True,
            completeness_threshold=0.8  # 80% minimum (accounts for BDL API issues)
        )

        # Store result for logging
        self.data["completeness_check"] = {
            "expected": result.expected,
            "actual": result.actual,
            "is_complete": result.is_complete,
            "completeness_pct": result.completeness_pct,
            "missing_count": result.missing_count
        }

    except Exception as e:
        logger.warning(f"Completeness check failed: {e}", exc_info=True)
```

### 2.3 Test Completeness Validation ⏰ 30 mins

**Test with known incomplete date (Jan 20):**
```bash
python scrapers/balldontlie/bdl_box_scores.py --date 2026-01-20 --debug
```

**Expected:**
- Warning logged: "INCOMPLETE DATA: BDL returned 4 of 7 games..."
- Slack notification sent to `#nba-alerts`
- Missing games identified: LAL @ DEN, MIA @ SAC, TOR @ GSW

### 2.4 Create Completeness Tracking Table ⏰ 1 hour

**New Schema:** `schemas/bigquery/nba_orchestration/scraper_completeness_checks.sql`

```sql
-- Scraper Completeness Checks Table
-- Tracks completeness validation results for all scrapers

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.scraper_completeness_checks` (
  check_id STRING NOT NULL,              -- UUID for this check
  check_timestamp TIMESTAMP NOT NULL,    -- When validation ran

  -- Scraper context
  source STRING NOT NULL,                -- 'BDL', 'NBAC', 'ODDSAPI'
  game_date DATE NOT NULL,               -- Date being validated
  execution_id STRING,                   -- Links to scraper_execution_log
  workflow STRING,                       -- Which workflow triggered

  -- Completeness metrics
  expected_games INT64 NOT NULL,
  actual_games INT64 NOT NULL,
  missing_count INT64 NOT NULL,
  completeness_pct FLOAT64 NOT NULL,
  is_complete BOOL NOT NULL,

  -- Missing games detail
  missing_matchups ARRAY<STRING>,        -- List of missing games
  missing_game_ids ARRAY<STRING>,

  -- Alert tracking
  alert_sent BOOL DEFAULT FALSE,
  alert_severity STRING,                 -- 'WARNING', 'CRITICAL'
  alert_channel STRING,                  -- '#nba-alerts', '#app-error-alerts'

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(game_date)
CLUSTER BY source, is_complete, alert_sent;
```

**Deploy:**
```bash
bq query --nouse_legacy_sql --location=us-west2 < \
  schemas/bigquery/nba_orchestration/scraper_completeness_checks.sql
```

**Update validator to log to this table** (add to `scraper_completeness_validator.py`):
```python
def log_completeness_check(result: CompletenessResult, game_date: str, source: str, execution_id: str = None):
    """Log completeness check to BigQuery"""
    import uuid
    client = bigquery.Client()

    row = {
        "check_id": str(uuid.uuid4()),
        "check_timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "game_date": game_date,
        "execution_id": execution_id,
        "expected_games": result.expected,
        "actual_games": result.actual,
        "missing_count": result.missing_count,
        "completeness_pct": result.completeness_pct,
        "is_complete": result.is_complete,
        "missing_matchups": [g['matchup'] for g in result.missing_games],
        "alert_sent": not result.is_complete,
        "alert_severity": "CRITICAL" if result.completeness_pct < 70 else "WARNING"
    }

    table_id = "nba-props-platform.nba_orchestration.scraper_completeness_checks"
    client.insert_rows_json(table_id, [row])
```

---

## Phase 3: Investigate Workflow Execution Issues (Week 1, Day 3-4 - 2 hours)

**Goal:** Fix recovery windows (2 AM, 4 AM, 6 AM) not executing

### 3.1 Check Workflow Configuration ⏰ 15 mins

**Verify workflows are enabled:**
```bash
grep -A 15 "post_game_window_2b:" config/workflows.yaml
grep -A 15 "post_game_window_3:" config/workflows.yaml
grep -A 15 "morning_recovery:" config/workflows.yaml
```

**Expected:** Each workflow should have `enabled: true`

### 3.2 Check Controller Logs ⏰ 30 mins

**Query controller logs for Jan 1-2 (example of missing windows):**
```bash
gcloud logging read "
  resource.type=cloud_run_revision
  AND resource.labels.service_name=master-controller
  AND timestamp>='2026-01-01T00:00:00Z'
  AND timestamp<='2026-01-02T12:00:00Z'
  AND (
    textPayload:'post_game_window_2b'
    OR textPayload:'post_game_window_3'
    OR textPayload:'morning_recovery'
  )" \
  --limit=100 \
  --format=json > /tmp/controller_logs_jan1.json

# Analyze
cat /tmp/controller_logs_jan1.json | jq '.[] | select(.textPayload | contains("SKIP") or contains("ABORT"))'
```

**Look for:**
- SKIP decisions with reasons
- ABORT due to dependency failures
- Missing workflow evaluations entirely

### 3.3 Check Scheduler Configuration ⏰ 15 mins

**List all Cloud Scheduler jobs:**
```bash
gcloud scheduler jobs list --location=us-west2 | grep -E "(post_game|morning)"
```

**Verify master controller schedule:**
```bash
gcloud scheduler jobs describe master-controller-hourly \
  --location=us-west2 \
  --format="value(schedule,state)"
```

**Expected:** `0 * * * *` (hourly), state=ENABLED

### 3.4 Check Workflow Decision Logic ⏰ 30 mins

**Query workflow decisions table:**
```sql
SELECT
  workflow_name,
  game_date,
  decision_time,
  decision,
  reason,
  metadata
FROM nba_orchestration.workflow_decisions
WHERE game_date = '2026-01-01'
  AND workflow_name IN (
    'post_game_window_2',
    'post_game_window_2b',
    'post_game_window_3',
    'morning_recovery'
  )
ORDER BY decision_time;
```

**Analyze:**
- Are all workflows being evaluated?
- What decision was made (RUN/SKIP/ABORT)?
- What's the reason for SKIP/ABORT?

**Common issues:**
- `game_aware: yesterday` may skip if schedule not updated
- Dependencies (`requires: [phase3_analytics]`) may block if upstream failed
- Time window too restrictive
- Distributed lock not released

### 3.5 Fix and Verify ⏰ 30 mins

**If workflows are disabled:** Enable in `config/workflows.yaml`

**If decision logic issue:** Adjust conditions
- Remove unnecessary dependencies
- Widen time windows
- Change decision type (e.g., `always` vs `game_aware`)

**If scheduler issue:** Fix schedule or add missing job

**Test fix:**
```bash
# Manually trigger controller
gcloud scheduler jobs run master-controller-hourly --location=us-west2

# Check logs in 2 minutes
gcloud logging read "resource.labels.service_name=master-controller" \
  --limit=50 \
  --format=json
```

**Verification query after tonight's games:**
```sql
-- Should see multiple workflows for same date
SELECT
  workflow,
  DATE(triggered_at) as date,
  COUNT(*) as executions,
  COUNTIF(status = 'success') as successes
FROM nba_orchestration.scraper_execution_log
WHERE scraper_name = 'bdl_box_scores'
  AND DATE(triggered_at) = CURRENT_DATE()
GROUP BY workflow, date
ORDER BY workflow;

-- Expected:
-- post_game_window_1  | 2026-01-21 | 1 | 1
-- post_game_window_2  | 2026-01-21 | 1 | 1
-- post_game_window_2b | 2026-01-21 | 1 | 1
-- post_game_window_3  | 2026-01-21 | 1 | 1
-- morning_recovery    | 2026-01-21 | 1 | 1
```

---

## Phase 4: Build Retry Queue (Week 2 - 6 hours)

**Goal:** Automatically retry missing games without manual intervention

### 4.1 Create Retry Queue Table ⏰ 1 hour

**Schema:** `schemas/bigquery/nba_orchestration/missing_game_retry_queue.sql`

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.missing_game_retry_queue` (
  -- Game identification
  game_date DATE NOT NULL,
  home_team STRING NOT NULL,
  away_team STRING NOT NULL,
  game_id STRING,                        -- Composite ID: YYYYMMDD_AWAY_HOME
  matchup STRING,                        -- Display: "AWAY @ HOME"

  -- Source tracking (one entry per source)
  source STRING NOT NULL,                -- 'BDL', 'NBAC', 'ODDSAPI'

  -- Detection
  detected_at TIMESTAMP NOT NULL,
  detection_source STRING,               -- 'completeness_check', 'manual', 'daily_monitor'
  detection_check_id STRING,             -- Links to scraper_completeness_checks

  -- Retry logic
  retry_count INT64 DEFAULT 0,
  last_retry_at TIMESTAMP,
  next_retry_at TIMESTAMP,               -- When to retry next
  retry_backoff_minutes INT64,           -- Current backoff (2, 4, 8, 16, 32...)

  -- Resolution
  resolved_at TIMESTAMP,
  resolved_by STRING,                    -- 'auto_retry', 'manual_backfill', 'data_unavailable'
  resolution_notes STRING,

  -- Priority
  priority STRING DEFAULT 'NORMAL',      -- 'HIGH', 'NORMAL', 'LOW'

  -- Metadata
  is_west_coast BOOL,                    -- For pattern analysis
  is_late_game BOOL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(game_date)
CLUSTER BY source, priority, resolved_at;

-- Index for retry worker
CREATE INDEX idx_next_retry
ON `nba-props-platform.nba_orchestration.missing_game_retry_queue`(next_retry_at)
WHERE resolved_at IS NULL;
```

### 4.2 Add to Retry Queue from Completeness Validator ⏰ 1 hour

**Update `scraper_completeness_validator.py`:**

```python
def add_to_retry_queue(result: CompletenessResult, game_date: str, source: str, check_id: str):
    """Add missing games to retry queue"""
    if result.is_complete:
        return

    client = bigquery.Client()
    rows = []

    for game in result.missing_games:
        # Calculate next retry (2 hours from now)
        next_retry = datetime.now(timezone.utc) + timedelta(hours=2)

        row = {
            "game_date": game_date,
            "home_team": game['home_team'],
            "away_team": game['away_team'],
            "game_id": f"{game_date.replace('-', '')}_{game['away_team']}_{game['home_team']}",
            "matchup": game['matchup'],
            "source": source,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "detection_source": "completeness_check",
            "detection_check_id": check_id,
            "retry_count": 0,
            "next_retry_at": next_retry.isoformat(),
            "retry_backoff_minutes": 120,  # 2 hours
            "priority": "HIGH" if source == 'BDL' else "NORMAL",
            "is_west_coast": game.get('arena_timezone') in ('America/Los_Angeles', 'America/Phoenix'),
            "is_late_game": False  # Would need game start time to determine
        }
        rows.append(row)

    if rows:
        table_id = "nba-props-platform.nba_orchestration.missing_game_retry_queue"
        errors = client.insert_rows_json(table_id, rows)

        if not errors:
            logger.info(f"Added {len(rows)} games to retry queue for {source} {game_date}")
        else:
            logger.error(f"Failed to add to retry queue: {errors}")
```

**Call in `validate_completeness()`:**
```python
if not result.is_complete and notify_on_incomplete:
    check_id = str(uuid.uuid4())
    log_completeness_check(result, game_date, source, check_id=check_id)
    add_to_retry_queue(result, game_date, source, check_id=check_id)
```

### 4.3 Create Retry Worker Cloud Function ⏰ 3 hours

**New File:** `orchestration/cloud_functions/missing_game_retry_worker/main.py`

```python
"""
Missing Game Retry Worker

Runs every 2 hours to:
1. Query retry queue for unresolved games where next_retry_at <= NOW
2. Trigger scraper for each missing game's date
3. Check if game now exists
4. If yes: mark resolved
5. If no: increment retry_count, calculate next backoff
6. After 10 retries (48 hours): escalate to CRITICAL alert, mark data_unavailable
"""

import functions_framework
from google.cloud import bigquery
from datetime import datetime, timezone, timedelta
import logging
import requests
import os
import json

logger = logging.getLogger(__name__)

# Configuration
MAX_RETRIES = 10
BACKOFF_MULTIPLIER = 2  # 2h → 4h → 8h → 16h
SCRAPER_SERVICE_URL = os.getenv('SCRAPER_SERVICE_URL', 'https://nba-scrapers-XXXXX.run.app')


@functions_framework.http
def retry_missing_games_handler(request):
    """HTTP handler for retry worker"""
    try:
        result = retry_missing_games()
        return {"status": "success", "result": result}, 200
    except Exception as e:
        logger.error(f"Retry worker failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}, 500


def retry_missing_games():
    """Main retry logic"""
    client = bigquery.Client()

    # Get games due for retry
    query = """
    SELECT
      game_date,
      home_team,
      away_team,
      game_id,
      matchup,
      source,
      retry_count,
      priority,
      detected_at,
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), detected_at, HOUR) as hours_since_detected
    FROM `nba-props-platform.nba_orchestration.missing_game_retry_queue`
    WHERE resolved_at IS NULL
      AND next_retry_at <= CURRENT_TIMESTAMP()
    ORDER BY priority DESC, detected_at ASC
    LIMIT 20  -- Process max 20 per run
    """

    games_to_retry = list(client.query(query).result())

    if not games_to_retry:
        logger.info("No games to retry")
        return {"games_processed": 0}

    logger.info(f"Processing {len(games_to_retry)} games")

    results = {
        "resolved": 0,
        "retried": 0,
        "escalated": 0,
        "failed": 0
    }

    for game in games_to_retry:
        try:
            if game.retry_count >= MAX_RETRIES:
                # Escalate after max retries
                escalate_game(game, client)
                results["escalated"] += 1
            else:
                # Attempt retry
                success = retry_game(game, client)
                if success:
                    results["resolved"] += 1
                else:
                    results["retried"] += 1
        except Exception as e:
            logger.error(f"Failed to process {game.matchup}: {e}")
            results["failed"] += 1

    logger.info(f"Retry results: {results}")
    return results


def retry_game(game, client):
    """
    Trigger scraper for this game and check if resolved.

    Returns:
        True if game now exists (resolved)
        False if still missing (needs more retries)
    """
    # Trigger scraper for this date
    scraper_name = {
        'BDL': 'bdl_box_scores',
        'NBAC': 'nbac_gamebook',
        'ODDSAPI': 'odds_events'
    }[game.source]

    # Call scraper service
    response = requests.post(
        f"{SCRAPER_SERVICE_URL}/scrape",
        json={
            "scraper": scraper_name,
            "date": str(game.game_date),
            "force": True,
            "workflow": "retry_worker"
        },
        timeout=300  # 5 minutes
    )

    if response.status_code != 200:
        logger.warning(f"Scraper call failed for {game.matchup}: {response.status_code}")
        increment_retry(game, client, success=False)
        return False

    # Wait 10 seconds for data to land
    import time
    time.sleep(10)

    # Check if game now exists
    exists = check_game_exists(game, client)

    if exists:
        # Resolve
        mark_resolved(game, client, resolved_by='auto_retry')
        logger.info(f"✅ Resolved {game.matchup} after {game.retry_count + 1} retries")
        return True
    else:
        # Increment retry count, schedule next attempt
        increment_retry(game, client, success=False)
        logger.info(f"Still missing {game.matchup}, will retry again (attempt {game.retry_count + 1})")
        return False


def check_game_exists(game, client):
    """Check if game now exists in target table"""
    source_tables = {
        'BDL': 'nba_raw.bdl_player_boxscores',
        'NBAC': 'nba_raw.nbac_gamebook_player_stats',
        'ODDSAPI': 'nba_raw.oddsapi_events'
    }

    query = f"""
    SELECT COUNT(*) as count
    FROM `nba-props-platform.{source_tables[game.source]}`
    WHERE game_id = @game_id
      AND game_date = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_id", "STRING", game.game_id),
            bigquery.ScalarQueryParameter("game_date", "DATE", str(game.game_date))
        ]
    )

    results = list(client.query(query, job_config=job_config).result())
    count = results[0].count if results else 0

    return count > 0


def mark_resolved(game, client, resolved_by):
    """Mark game as resolved in retry queue"""
    query = f"""
    UPDATE `nba-props-platform.nba_orchestration.missing_game_retry_queue`
    SET
      resolved_at = CURRENT_TIMESTAMP(),
      resolved_by = @resolved_by,
      updated_at = CURRENT_TIMESTAMP()
    WHERE game_id = @game_id
      AND source = @source
      AND game_date = @game_date
      AND resolved_at IS NULL
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_id", "STRING", game.game_id),
            bigquery.ScalarQueryParameter("source", "STRING", game.source),
            bigquery.ScalarQueryParameter("game_date", "DATE", str(game.game_date)),
            bigquery.ScalarQueryParameter("resolved_by", "STRING", resolved_by)
        ]
    )

    client.query(query, job_config=job_config).result()


def increment_retry(game, client, success):
    """Increment retry count and schedule next attempt"""
    # Calculate exponential backoff
    new_retry_count = game.retry_count + 1
    backoff_minutes = 120 * (BACKOFF_MULTIPLIER ** new_retry_count)  # 2h, 4h, 8h, 16h, 32h...
    backoff_minutes = min(backoff_minutes, 1440)  # Cap at 24 hours

    next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)

    query = f"""
    UPDATE `nba-props-platform.nba_orchestration.missing_game_retry_queue`
    SET
      retry_count = @retry_count,
      last_retry_at = CURRENT_TIMESTAMP(),
      next_retry_at = @next_retry_at,
      retry_backoff_minutes = @backoff_minutes,
      updated_at = CURRENT_TIMESTAMP()
    WHERE game_id = @game_id
      AND source = @source
      AND game_date = @game_date
      AND resolved_at IS NULL
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_id", "STRING", game.game_id),
            bigquery.ScalarQueryParameter("source", "STRING", game.source),
            bigquery.ScalarQueryParameter("game_date", "DATE", str(game.game_date)),
            bigquery.ScalarQueryParameter("retry_count", "INT64", new_retry_count),
            bigquery.ScalarQueryParameter("next_retry_at", "TIMESTAMP", next_retry_at.isoformat()),
            bigquery.ScalarQueryParameter("backoff_minutes", "INT64", backoff_minutes)
        ]
    )

    client.query(query, job_config=job_config).result()


def escalate_game(game, client):
    """Escalate to CRITICAL alert after max retries"""
    from shared.utils.notification_system import notify_error

    hours_missing = game.hours_since_detected

    notify_error(
        title=f"CRITICAL: {game.source} Game Permanently Missing",
        message=f"Game {game.matchup} for {game.game_date} still missing after {game.retry_count} retries ({hours_missing}h)",
        details={
            'game_id': game.game_id,
            'source': game.source,
            'retries': game.retry_count,
            'hours_missing': hours_missing,
            'action': 'Manual intervention required or data unavailable from source'
        }
    )

    # Mark as data_unavailable
    mark_resolved(game, client, resolved_by='data_unavailable')

    logger.error(f"❌ Escalated {game.matchup} after {game.retry_count} failed retries")
```

**Deploy script:** `orchestration/cloud_functions/missing_game_retry_worker/deploy.sh`

```bash
#!/bin/bash
gcloud functions deploy missing-game-retry-worker \
  --gen2 \
  --region=us-west2 \
  --runtime=python312 \
  --source=. \
  --entry-point=retry_missing_games_handler \
  --timeout=540s \
  --memory=512Mi \
  --set-env-vars="SCRAPER_SERVICE_URL=https://nba-scrapers-XXXXX.run.app" \
  --trigger-http \
  --allow-unauthenticated

# Create Cloud Scheduler job
gcloud scheduler jobs create http missing-game-retry-worker \
  --location=us-west2 \
  --schedule="0 */2 * * *" \
  --time-zone="UTC" \
  --uri="$(gcloud functions describe missing-game-retry-worker --gen2 --region=us-west2 --format='value(serviceConfig.uri)')" \
  --http-method=POST \
  --oidc-service-account-email="scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com"
```

### 4.4 Create Retry Queue Dashboard ⏰ 30 mins

**Save as:** `monitoring/retry_queue_dashboard.sql`

```sql
-- Retry Queue Dashboard

-- 1. Current Queue Status
SELECT
  source,
  priority,
  COUNT(*) as games_in_queue,
  COUNT(CASE WHEN retry_count = 0 THEN 1 END) as never_retried,
  COUNT(CASE WHEN retry_count BETWEEN 1 AND 5 THEN 1 END) as active_retries,
  COUNT(CASE WHEN retry_count > 5 THEN 1 END) as many_retries,
  MIN(detected_at) as oldest_detection,
  MAX(next_retry_at) as latest_retry_scheduled
FROM nba_orchestration.missing_game_retry_queue
WHERE resolved_at IS NULL
GROUP BY source, priority
ORDER BY priority DESC, source;

-- 2. Recently Resolved
SELECT
  game_date,
  matchup,
  source,
  TIMESTAMP_DIFF(resolved_at, detected_at, HOUR) as hours_to_resolve,
  retry_count,
  resolved_by
FROM nba_orchestration.missing_game_retry_queue
WHERE resolved_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY resolved_at DESC
LIMIT 20;

-- 3. Stuck Games (> 24 hours)
SELECT
  game_date,
  matchup,
  source,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), detected_at, HOUR) as hours_missing,
  retry_count,
  next_retry_at,
  is_west_coast
FROM nba_orchestration.missing_game_retry_queue
WHERE resolved_at IS NULL
  AND detected_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY detected_at;

-- 4. Resolution Statistics (Last 7 Days)
SELECT
  DATE(detected_at) as date,
  source,
  COUNT(*) as total_missing,
  COUNTIF(resolved_by = 'auto_retry') as auto_resolved,
  COUNTIF(resolved_by = 'manual_backfill') as manual_resolved,
  COUNTIF(resolved_by = 'data_unavailable') as unavailable,
  ROUND(100.0 * COUNTIF(resolved_by = 'auto_retry') / COUNT(*), 1) as auto_resolve_pct
FROM nba_orchestration.missing_game_retry_queue
WHERE detected_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY date, source
ORDER BY date DESC, source;
```

---

## Phase 5: Expand to NBAC and OddsAPI (Week 2-3 - 6 hours)

**Goal:** Apply same patterns to other scrapers

### 5.1 NBAC Availability Logger ⏰ 2 hours

**Copy BDL pattern:**
1. Create `shared/utils/nbac_availability_logger.py` (similar to BDL)
2. Create `schemas/bigquery/nba_orchestration/nbac_game_scrape_attempts.sql`
3. Integrate into `scrapers/nbac/nbac_gamebook.py`

**Key differences:**
- NBAC typically 100% complete (more reliable than BDL)
- Track different fields: `gamebook_present`, `play_by_play_present`
- Lower alert threshold (< 95% = WARNING)

### 5.2 NBAC Completeness Validation ⏰ 1 hour

**Integrate into NBAC gamebook scraper:**
```python
result = validate_completeness(
    game_date=self.opts["date"],
    games_returned=games_returned,
    source='NBAC',
    notify_on_incomplete=True,
    completeness_threshold=0.95  # Higher threshold for NBAC
)
```

### 5.3 OddsAPI Availability Logger ⏰ 2 hours

**Similar pattern:**
1. Create `shared/utils/oddsapi_availability_logger.py`
2. Create `schemas/bigquery/nba_orchestration/oddsapi_game_scrape_attempts.sql`
3. Integrate into `scrapers/oddsapi/odds_events.py`

**Key differences:**
- OddsAPI has different completion criteria (odds lines vs game events)
- Track: `odds_count`, `bookmaker_count`, `props_available`
- Alert only if no odds for games > 2 hours after start

### 5.4 Update Monitoring Views ⏰ 1 hour

**Add NBAC and OddsAPI to existing views:**

Already done! Views support NBAC and OddsAPI:
- `v_scraper_game_availability` - tracks all 3 sources
- `v_scraper_availability_daily_summary` - aggregates all 3

Just need to populate the underlying attempt tables.

---

## Success Metrics & Monitoring

### Key Performance Indicators

**Before Implementation:**
- Detection time: Days (manual audit)
- Missing game rate: 17% (31 of 180 games in Jan)
- Recovery: 100% manual backfills
- Alert coverage: 0%
- Latency visibility: Aggregate only

**After Phase 2 (Week 1):**
- Detection time: < 10 minutes (completeness check)
- Missing game visibility: 100%
- Alert coverage: BDL (100%)
- Latency visibility: Per-game, per-attempt

**After Phase 4 (Week 2):**
- Missing game rate: < 5% (with retry queue)
- Recovery: 80%+ automatic
- Recovery time: < 4 hours (exponential backoff)

**After Phase 5 (Week 3):**
- Alert coverage: BDL + NBAC + OddsAPI (100%)
- Missing game rate: < 1%
- Multi-source redundancy: 95%+

### Daily Monitoring Routine

**Morning (9 AM ET):**
```sql
-- Run daily scraper health dashboard
\i monitoring/daily_scraper_health.sql

-- Check retry queue
\i monitoring/retry_queue_dashboard.sql

-- Review completeness checks
SELECT * FROM nba_orchestration.scraper_completeness_checks
WHERE check_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND NOT is_complete
ORDER BY check_timestamp DESC;
```

**Slack alerts received:**
- 8 AM ET: Daily scraper availability report
- Real-time: Completeness warnings (if missing games detected)
- Real-time: Retry worker escalations (after 10 failed attempts)

---

## Implementation Timeline

### Week 1: Foundation
- **Day 1 (4 hours):**
  - Phase 0: Deploy existing monitoring (30 mins)
  - Phase 1: BDL availability logger (2 hours)
  - Test and verify (1.5 hours)

- **Day 2-3 (6 hours):**
  - Phase 2: Completeness validation (4 hours)
  - Phase 3: Investigate workflows (2 hours)

### Week 2: Automation
- **Day 1-3 (6 hours):**
  - Phase 4: Build retry queue (6 hours)
  - Test retry worker (2 hours)
  - Monitor first auto-resolutions (ongoing)

### Week 3: Expansion
- **Day 1-5 (6 hours):**
  - Phase 5: Expand to NBAC (3 hours)
  - Phase 5: Expand to OddsAPI (3 hours)
  - Integration testing (2 hours)

**Total time investment:** ~20 hours over 3 weeks
**Expected ongoing time savings:** 5-10 hours/week (no manual backfills, investigations)

---

## Integration with Existing Infrastructure

### Builds On:
- ✅ Existing monitoring views (already deployed)
- ✅ Phase boundary validation (staging deployment)
- ✅ Rate limiting and circuit breakers
- ✅ Notification system (Slack, email)
- ✅ Scraper execution logging

### Connects To:
- **Workflows:** Uses existing retry windows (2 AM, 4 AM, 6 AM)
- **Notifications:** Reuses existing Slack channels
- **Validation:** Integrates with phase boundary validator
- **Storage:** Uses existing BigQuery datasets

### Complements:
- **BDL Root Cause Fixes:** Provides detection + automated recovery
- **Multi-Scraper Visibility Plan:** Implements per-game tracking
- **Staging Deployment:** Validation infrastructure ready for production

---

## Next Steps

**Immediate (Today):**
1. Review this plan with team
2. Deploy scraper availability monitor (Phase 0.1)
3. Check tomorrow morning's alert

**This Week:**
1. Implement Phase 1 (BDL logger)
2. Implement Phase 2 (completeness validation)
3. Investigate workflow execution issues (Phase 3)

**Next Week:**
1. Build retry queue (Phase 4)
2. Monitor auto-resolution effectiveness
3. Tune retry backoff timing

**Week 3:**
1. Expand to NBAC and OddsAPI (Phase 5)
2. Create dashboards
3. Document operational procedures

---

**Document Created:** January 21, 2026
**Last Updated:** January 21, 2026
**Owner:** Data Engineering Team
**Status:** Ready for Implementation
**Priority:** P0 - Critical
