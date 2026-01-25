# Comprehensive System Analysis & Remediation Guide

**Date:** 2026-01-25
**Purpose:** Complete system analysis with fixes, improvements, and study guide for future sessions
**Scope:** Orchestration, validation, data pipeline, and resilience systems

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current System State](#current-system-state)
3. [Critical Bugs & Fixes](#critical-bugs--fixes)
4. [Recommended Improvements](#recommended-improvements)
5. [Architecture Deep Dive](#architecture-deep-dive)
6. [Study Guide for Finding More Issues](#study-guide-for-finding-more-issues)
7. [Quick Reference](#quick-reference)

---

## Executive Summary

### System Health Score: 6/10

**What's Working:**
- Phase orchestrators (3→4, 4→5, 5→6) deployed and running
- Workflow decisions active (180 today)
- Validation framework comprehensive (15+ scripts)
- Multi-source fallback for data resilience
- Jan 23 fully recovered (8/8 games)

**What's Broken:**
- **Grading not running for 3 games with complete boxscores** (CRITICAL - NEW)
- Auto-retry processor has 3 broken topic mappings (CRITICAL)
- Phase execution logging not populating (needs investigation)
- GSW@MIN boxscore missing from Jan 24 (blocked by auto-retry bug)
- Feature quality degraded (avg 64.4, all bronze tier)

**Technical Debt:**
- Dependency cascade problem in shared/utils/__init__.py
- Game ID format mismatch between tables
- No subscriptions on fallback trigger topics

---

## Current System State

### Data Completeness (as of 2026-01-25 ~16:00 UTC)

#### January 24, 2026

| Phase | Table | Expected | Actual | Coverage |
|-------|-------|----------|--------|----------|
| Schedule | `nba_raw.v_nbac_schedule_latest` | 7 games | 7 games | 100% |
| Boxscores | `nba_raw.bdl_player_boxscores` | 7 games | 6 games | 85.7% |
| Analytics | `nba_analytics.player_game_summary` | 6 games | 6 games | 100%* |
| Predictions | `nba_predictions.player_prop_predictions` | - | 486 | - |

*Analytics matches boxscores - correctly only processed available data

**Missing Game:** GSW @ MIN
- Schedule game_id: `0022500644`
- BDL game_id format: `20260124_GSW_MIN`
- Team IDs: away=1610612744 (GSW), home=1610612750 (MIN)
- Error: "Max decode/download retries reached: 8"

#### January 25, 2026

| Check | Status |
|-------|--------|
| Games Scheduled | 7 games |
| Boxscores | 0 (games not finished yet) |
| First tipoff | ~8 PM ET |

### Orchestration Health

| Component | Status | Details |
|-----------|--------|---------|
| Workflow Decisions | ACTIVE | 180 decisions on Jan 25, last at 15:00 UTC |
| phase3-to-phase4 | DEPLOYED | Updated 2026-01-25 15:21:34 UTC |
| phase4-to-phase5 | DEPLOYED | Updated 2026-01-25 15:28:08 UTC |
| phase5-to-phase6 | DEPLOYED | Updated 2026-01-25 15:28:18 UTC |
| auto-retry-processor | BROKEN | Pub/Sub topic doesn't exist |

### Failed Processor Queue

```
| game_date  | processor_name       | status  | retry_count | error_message                          |
|------------|----------------------|---------|-------------|----------------------------------------|
| 2026-01-24 | nbac_player_boxscore | pending | 0           | Max decode/download retries reached: 8 |
```

The entry exists but auto-retry cannot process it due to the topic bug.

---

## Critical Bugs & Fixes

### Bug #0: Grading Not Running for 3 Games with Complete Data (CRITICAL)

**Severity:** CRITICAL - 50% of Jan 24 games with boxscores have no grading

**Discovery:** Jan 24 has 6 games with boxscores, but only 3 have ANY grading data:

| Game | Boxscore Players | Grading Status |
|------|------------------|----------------|
| 20260124_BOS_CHI | 35 | **NO GRADING** |
| 20260124_CLE_ORL | 34 | **NO GRADING** |
| 20260124_GSW_MIN | 0 (missing) | No grading (expected) |
| 20260124_LAL_DAL | 36 | Graded (35 rows) |
| 20260124_MIA_UTA | 35 | **NO GRADING** |
| 20260124_NYK_PHI | 34 | Graded (47 rows) |
| 20260124_WAS_CHA | 35 | Graded (42 rows) |

**Impact:**
- 124 predictions graded out of 486 made (25.5%)
- 3 games with complete data have ZERO grading
- This is NOT caused by missing boxscores

**Possible Causes:**
1. Grading processor didn't run for all games
2. Game ID mismatch between predictions and boxscores
3. Timing issue - grading ran before boxscores were available
4. Filtering logic excluding these games

**Investigation Steps:**
```bash
# Check when grading last ran
bq query --use_legacy_sql=false "
SELECT processor_name, MAX(timestamp) as last_run
FROM nba_orchestration.pipeline_event_log
WHERE processor_name LIKE '%grad%'
  AND event_type = 'processor_complete'
GROUP BY 1
"

# Check if predictions exist for ungraded games
bq query --use_legacy_sql=false "
SELECT game_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-24'
  AND game_id IN ('20260124_BOS_CHI', '20260124_CLE_ORL', '20260124_MIA_UTA')
GROUP BY 1
"

# Check grading processor logs
gcloud functions logs read daily-grading-processor --region us-west2 --limit 50
```

**Fix:** Run grading backfill for Jan 24:
```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-24 --end-date 2026-01-24
```

---

### Bug #1: Auto-Retry Processor Topic Doesn't Exist (CRITICAL)

**Severity:** CRITICAL - Prevents all Phase 2 automatic retries

**Location:** `/orchestration/cloud_functions/auto_retry_processor/main.py`

**Problem:**
```python
# Lines 44-49
PHASE_TOPIC_MAP = {
    'phase_2': 'nba-phase1-scraper-trigger',      # THIS TOPIC DOESN'T EXIST
    'phase_3': 'nba-phase3-analytics-trigger',    # Also doesn't exist
    'phase_4': 'nba-phase4-precompute-trigger',   # Also doesn't exist
    'phase_5': 'nba-predictions-trigger',          # Also doesn't exist
}
```

**Evidence from logs:**
```
Failed to publish retry message: 404 Resource not found (resource=nba-phase1-scraper-trigger)
```
This error occurs every 15 minutes since deployment.

**Available Topics (from `gcloud pubsub topics list`):**
```
nba-phase1-scrapers-complete        # Scraper completion notifications
nba-phase2-raw-complete             # Phase 2 completion notifications
nba-phase2-fallback-trigger         # Exists but NO SUBSCRIBERS
nba-phase3-trigger                  # Phase 3 trigger
nba-phase3-fallback-trigger         # Exists but may have no subscribers
nba-phase4-trigger                  # Phase 4 trigger
nba-phase4-fallback-trigger         # Exists but may have no subscribers
nba-phase5-fallback-trigger         # Exists but may have no subscribers
nba-phase6-export-trigger           # Phase 6 trigger
```

**ALL Topic Mappings Are Wrong (Except phase_5):**

| Configured | Actual Topic | Fix |
|------------|--------------|-----|
| `nba-phase1-scraper-trigger` | Does not exist | Use `nba-phase2-fallback-trigger` |
| `nba-phase3-analytics-trigger` | `nba-phase3-trigger` exists | Use `nba-phase3-fallback-trigger` |
| `nba-phase4-precompute-trigger` | `nba-phase4-trigger` exists | Use `nba-phase4-fallback-trigger` |
| `nba-predictions-trigger` | EXISTS - OK | Keep as-is |

**Fix Option A: Update Topic Mapping (Quick)**

```python
# Replace lines 44-49 with:
PHASE_TOPIC_MAP = {
    'phase_2': 'nba-phase2-fallback-trigger',     # Use fallback trigger
    'phase_3': 'nba-phase3-fallback-trigger',     # Use fallback trigger
    'phase_4': 'nba-phase4-fallback-trigger',     # Use fallback trigger
    'phase_5': 'nba-predictions-trigger',          # Keep - this one works!
}
```

Then create subscriptions for fallback topics:
```bash
# Create subscription for phase2-fallback-trigger
gcloud pubsub subscriptions create nba-phase2-fallback-sub \
  --topic=nba-phase2-fallback-trigger \
  --push-endpoint=https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process \
  --push-auth-service-account=756957797294-compute@developer.gserviceaccount.com
```

**Fix Option B: Direct HTTP Calls (More Reliable)**

Instead of Pub/Sub, call Cloud Run endpoints directly:

```python
# Add new constant after line 49
PHASE_HTTP_ENDPOINTS = {
    'phase_2': 'https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process',
    'phase_3': 'https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process',
    'phase_4': 'https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process',
    'phase_5': 'https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/predict',
}

# Replace publish_retry_message function (lines 109-161) with:
def publish_retry_message(
    phase: str,
    processor_name: str,
    game_date: str,
    correlation_id: Optional[str] = None,
    retry_count: int = 0
) -> bool:
    """
    Trigger retry via HTTP call to Cloud Run endpoint.
    """
    endpoint = PHASE_HTTP_ENDPOINTS.get(phase)
    if not endpoint:
        logger.warning(f"Unknown phase '{phase}', cannot determine retry endpoint")
        return False

    if DRY_RUN:
        logger.info(f"DRY RUN: Would POST to {endpoint} for {processor_name} on {game_date}")
        return True

    try:
        import google.auth.transport.requests
        import google.oauth2.id_token

        # Get ID token for Cloud Run authentication
        auth_req = google.auth.transport.requests.Request()
        id_token = google.oauth2.id_token.fetch_id_token(auth_req, endpoint)

        headers = {
            'Authorization': f'Bearer {id_token}',
            'Content-Type': 'application/json'
        }

        payload = {
            'action': 'retry',
            'processor_name': processor_name,
            'game_date': game_date,
            'correlation_id': correlation_id or f"retry-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'retry_count': retry_count + 1,
            'trigger_source': 'auto_retry',
        }

        response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        logger.info(f"Triggered retry via HTTP to {endpoint}: {response.status_code}")
        return True

    except Exception as e:
        logger.error(f"Failed to trigger retry via HTTP: {e}")
        return False
```

**Deployment Command:**
```bash
cd /home/naji/code/nba-stats-scraper
./bin/orchestrators/deploy_auto_retry_processor.sh
```

---

### Bug #2: Phase Execution Log Not Populating

**Severity:** MEDIUM - Observability gap, not blocking operations

**Location:**
- Logger: `/shared/utils/phase_execution_logger.py`
- Table: `nba_orchestration.phase_execution_log`

**Current State:**
```sql
SELECT COUNT(*) FROM nba_orchestration.phase_execution_log
-- Result: 0 rows
```

**Possible Causes:**

1. **Logger not called in deployed code**
   - Check if `log_phase_execution()` is actually called in main.py files
   - May have been added but not deployed

2. **BigQuery write permission issue**
   - Cloud function service account may lack bigquery.tables.updateData permission
   - Check: `gcloud functions describe phase3-to-phase4-orchestrator --region us-west2 | grep serviceAccount`

3. **Exception being swallowed**
   - Logger may be failing silently
   - Check cloud function logs for errors around logging calls

**Investigation Steps:**
```bash
# 1. Check if logging is in deployed code
gcloud functions describe phase3-to-phase4-orchestrator --region us-west2 --format='value(sourceUploadUrl)'
# Download and inspect main.py

# 2. Check for logging errors
gcloud functions logs read phase3-to-phase4-orchestrator --region us-west2 --limit 100 2>&1 | grep -i "phase_execution\|log"

# 3. Verify table permissions
bq show --format=prettyjson nba_orchestration.phase_execution_log | grep -A5 "access"

# 4. Test manual insert
bq query --use_legacy_sql=false "
INSERT INTO nba_orchestration.phase_execution_log
(execution_timestamp, phase_name, game_date, status, duration_seconds, games_processed)
VALUES (CURRENT_TIMESTAMP(), 'test', '2026-01-25', 'test', 0.1, 0)
"
```

**Fix:** Once root cause identified, either:
- Add logging calls to main.py and redeploy
- Fix permissions
- Fix exception handling in logger

---

### Bug #3: Game ID Format Mismatch

**Severity:** LOW - Causes confusing validation results, not blocking

**Problem:** Different tables use different game ID formats:

| Table | Format | Example |
|-------|--------|---------|
| `v_nbac_schedule_latest` | NBA.com numeric | `0022500644` |
| `bdl_player_boxscores` | Date_Away_Home | `20260124_GSW_MIN` |
| `player_game_summary` | Date_Away_Home | `20260124_GSW_MIN` |

**Impact:** Direct joins on game_id fail; must join on date + teams.

**Fix: Create Mapping View**

File exists but may not be deployed: `/schemas/bigquery/raw/v_game_id_mappings.sql`

```sql
-- Create or update: nba_raw.v_game_id_mappings
CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.v_game_id_mappings` AS
SELECT
  s.game_id as nba_game_id,
  CONCAT(
    FORMAT_DATE('%Y%m%d', s.game_date), '_',
    away.abbreviation, '_',
    home.abbreviation
  ) as bdl_game_id,
  s.game_date,
  away.abbreviation as away_team,
  home.abbreviation as home_team,
  s.game_status
FROM `nba-props-platform.nba_raw.v_nbac_schedule_latest` s
JOIN `nba-props-platform.nba_raw.nbac_teams_current` away ON s.away_team_id = away.team_id
JOIN `nba-props-platform.nba_raw.nbac_teams_current` home ON s.home_team_id = home.team_id
```

---

## Recommended Improvements

### Improvement #1: Lazy Imports in shared/utils/__init__.py

**Problem:** Eager imports cause dependency cascades and deployment failures.

**Current Code (`/shared/utils/__init__.py`):**
```python
# Imports everything at module load time
from .roster_manager import RosterManager  # Imports pandas
from .prometheus_metrics import PrometheusMetrics  # Imports psutil
# ... 20+ more imports
```

**Improved Code:**
```python
"""
Shared utilities with lazy loading to prevent dependency cascades.
"""

# Lightweight imports only - no external dependencies
from .game_id_converter import GameIdConverter, convert_game_id
from .env_validation import validate_required_env_vars

# Define what's available for import
__all__ = [
    'GameIdConverter',
    'convert_game_id',
    'validate_required_env_vars',
    # Lazy-loaded modules listed below
    'RosterManager',
    'PrometheusMetrics',
    'RateLimiter',
    'BigQueryClient',
    'StorageClient',
]

# Lazy loading implementation
def __getattr__(name):
    """Lazy load heavy modules only when accessed."""
    if name == 'RosterManager':
        from .roster_manager import RosterManager
        return RosterManager
    elif name == 'PrometheusMetrics':
        from .prometheus_metrics import PrometheusMetrics
        return PrometheusMetrics
    elif name == 'RateLimiter':
        from .rate_limiter import RateLimiter
        return RateLimiter
    elif name == 'BigQueryClient':
        from .bigquery_client import BigQueryClient
        return BigQueryClient
    elif name == 'StorageClient':
        from .storage_client import StorageClient
        return StorageClient
    # Add more as needed
    raise AttributeError(f"module 'shared.utils' has no attribute '{name}'")
```

**Benefit:** Cloud functions only load what they need, reducing cold start time and preventing import errors.

---

### Improvement #2: Fallback Topic Subscriptions

**Problem:** Fallback trigger topics exist but have no subscribers.

**Fix:** Create push subscriptions for each fallback topic:

```bash
#!/bin/bash
# bin/orchestrators/setup_fallback_subscriptions.sh

PROJECT_ID="nba-props-platform"
REGION="us-west2"

# Phase 2 fallback
gcloud pubsub subscriptions create nba-phase2-fallback-sub \
  --topic=nba-phase2-fallback-trigger \
  --push-endpoint=https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process \
  --push-auth-service-account=756957797294-compute@developer.gserviceaccount.com \
  --ack-deadline=600 \
  --message-retention-duration=1d

# Phase 3 fallback
gcloud pubsub subscriptions create nba-phase3-fallback-sub \
  --topic=nba-phase3-fallback-trigger \
  --push-endpoint=https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process \
  --push-auth-service-account=756957797294-compute@developer.gserviceaccount.com \
  --ack-deadline=600 \
  --message-retention-duration=1d

# Phase 4 fallback
gcloud pubsub subscriptions create nba-phase4-fallback-sub \
  --topic=nba-phase4-fallback-trigger \
  --push-endpoint=https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process \
  --push-auth-service-account=756957797294-compute@developer.gserviceaccount.com \
  --ack-deadline=600 \
  --message-retention-duration=1d

echo "Fallback subscriptions created"
```

---

### Improvement #3: ESPN Boxscore Fallback

**Problem:** When BDL fails (like GSW@MIN), there's no automatic fallback.

**Solution:** Add ESPN as secondary boxscore source.

**Implementation Location:** `/scrapers/espn/espn_boxscores.py` (new file)

**Architecture:**
```
BDL Scraper (primary)
    ↓ fails
ESPN Scraper (fallback, triggered by auto-retry)
    ↓
Phase 2 Processor (handles both formats)
```

**Key Considerations:**
- ESPN has different data format - needs transformer
- Rate limiting important for ESPN
- Only trigger ESPN if BDL fails 2+ times

---

### Improvement #4: Real-Time Monitoring During Game Hours

**Problem:** Validation is on-demand; issues discovered hours after they occur.

**Solution:** Cloud Function triggered every 30 minutes during game hours (7 PM - 1 AM ET).

**Implementation:**
```python
# bin/monitoring/realtime_health_monitor.py
"""
Real-time health monitor for NBA pipeline.
Runs every 30 minutes during game hours.
Sends Slack alerts when metrics degrade.
"""

CHECKS = [
    ('boxscore_lag', 'Games finished >2 hours ago without boxscores'),
    ('phase_stuck', 'Data stuck at phase boundary >1 hour'),
    ('retry_queue', 'Items in retry queue >3 attempts'),
    ('prediction_missing', 'Games with props but no predictions'),
]

def check_boxscore_lag():
    """Alert if games finished >2 hours ago still missing boxscores."""
    query = """
    SELECT s.game_id, s.game_date,
           TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), s.game_status_updated_at, HOUR) as hours_since_final
    FROM nba_raw.v_nbac_schedule_latest s
    LEFT JOIN (SELECT DISTINCT game_date FROM nba_raw.bdl_player_boxscores) b
      ON s.game_date = b.game_date
    WHERE s.game_status = 3  -- Final
      AND s.game_date >= CURRENT_DATE() - 1
      AND b.game_date IS NULL
      AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), s.game_status_updated_at, HOUR) > 2
    """
    # Execute and alert if rows returned
```

**Cloud Scheduler Setup:**
```bash
gcloud scheduler jobs create pubsub realtime-health-monitor \
  --schedule="*/30 19-1 * * *" \
  --time-zone="America/New_York" \
  --topic=realtime-health-monitor-trigger \
  --location=us-central1
```

---

### Improvement #5: Data Lineage Tracing

**Problem:** Hard to debug why a specific player's prediction is missing or wrong.

**Solution:** Script to trace entity through all phases.

```python
# bin/validation/trace_entity.py
"""
Trace a player or game through all pipeline phases.

Usage:
    python trace_entity.py --player "LeBron James" --date 2026-01-24
    python trace_entity.py --game 0022500644
"""

def trace_player(player_lookup: str, game_date: str):
    """Trace player through all phases."""

    results = {
        'player': player_lookup,
        'date': game_date,
        'phases': {}
    }

    # Phase 1: Schedule
    schedule = query(f"""
        SELECT game_id, away_team_id, home_team_id
        FROM nba_raw.v_nbac_schedule_latest
        WHERE game_date = '{game_date}'
    """)
    results['phases']['schedule'] = {'games': len(schedule)}

    # Phase 2: Boxscores
    boxscore = query(f"""
        SELECT game_id, points, assists, rebounds, minutes
        FROM nba_raw.bdl_player_boxscores
        WHERE game_date = '{game_date}' AND player_lookup = '{player_lookup}'
    """)
    results['phases']['boxscore'] = boxscore[0] if boxscore else {'status': 'MISSING'}

    # Phase 3: Analytics
    analytics = query(f"""
        SELECT game_id, points, usage_rate, ts_pct, source_coverage_pct
        FROM nba_analytics.player_game_summary
        WHERE game_date = '{game_date}' AND player_lookup = '{player_lookup}'
    """)
    results['phases']['analytics'] = analytics[0] if analytics else {'status': 'MISSING'}

    # Phase 4: Features
    features = query(f"""
        SELECT points_avg_last_10, feature_quality_score, is_production_ready
        FROM nba_precompute.player_daily_cache
        WHERE analysis_date = '{game_date}' AND player_lookup = '{player_lookup}'
    """)
    results['phases']['features'] = features[0] if features else {'status': 'MISSING'}

    # Phase 5: Predictions
    prediction = query(f"""
        SELECT predicted_points, confidence, model_version
        FROM nba_predictions.player_prop_predictions
        WHERE game_date = '{game_date}' AND player_lookup = '{player_lookup}'
    """)
    results['phases']['prediction'] = prediction[0] if prediction else {'status': 'MISSING'}

    # Phase 6: Grading
    grading = query(f"""
        SELECT actual_points, prediction_result, margin
        FROM nba_predictions.prediction_accuracy
        WHERE game_date = '{game_date}' AND player_lookup = '{player_lookup}'
    """)
    results['phases']['grading'] = grading[0] if grading else {'status': 'MISSING'}

    return results
```

---

## Architecture Deep Dive

### Pipeline Phase Overview

```
Phase 1: Scrapers (External APIs → GCS)
    │
    │  Pub/Sub: nba-phase1-scrapers-complete
    ↓
Phase 2: Raw Processors (GCS → BigQuery nba_raw.*)
    │
    │  Pub/Sub: nba-phase2-raw-complete
    │  Orchestrator: phase2-to-phase3-orchestrator (monitoring only)
    ↓
Phase 3: Analytics Processors (nba_raw.* → nba_analytics.*)
    │
    │  Pub/Sub: nba-phase3-analytics-complete
    │  Orchestrator: phase3-to-phase4-orchestrator (ACTIVE)
    ↓
Phase 4: Precompute Processors (nba_analytics.* → nba_precompute.*)
    │
    │  Pub/Sub: nba-phase4-precompute-complete
    │  Orchestrator: phase4-to-phase5-orchestrator (ACTIVE)
    ↓
Phase 5: Predictions (nba_precompute.* → nba_predictions.*)
    │
    │  Pub/Sub: nba-phase5-predictions-complete
    │  Orchestrator: phase5-to-phase6-orchestrator (ACTIVE)
    ↓
Phase 6: Export/Grading (nba_predictions.* → external systems)
```

### Key Tables

| Phase | Table | Purpose |
|-------|-------|---------|
| 2 | `nba_raw.bdl_player_boxscores` | BDL player stats |
| 2 | `nba_raw.nbac_gamebook_player_stats` | NBA.com player stats |
| 2 | `nba_raw.v_nbac_schedule_latest` | Game schedule (deduped) |
| 3 | `nba_analytics.player_game_summary` | Unified stats + advanced metrics |
| 4 | `nba_precompute.player_daily_cache` | Pre-computed features |
| 4 | `nba_predictions.ml_feature_store_v2` | ML features with quality scores |
| 5 | `nba_predictions.player_prop_predictions` | ML predictions |
| 6 | `nba_predictions.prediction_accuracy` | Grading results |

### Orchestration Tables

| Table | Purpose |
|-------|---------|
| `nba_orchestration.workflow_decisions` | Master controller decisions |
| `nba_orchestration.pipeline_event_log` | Phase completion events |
| `nba_orchestration.failed_processor_queue` | Retry queue |
| `nba_orchestration.phase_execution_log` | Orchestrator timing (NEW) |
| `nba_orchestration.streaming_conflict_log` | BigQuery buffer conflicts |

### Cloud Functions

| Function | Region | Purpose |
|----------|--------|---------|
| `phase2-to-phase3-orchestrator` | us-west2 | Monitor Phase 2 completion |
| `phase3-to-phase4-orchestrator` | us-west2 | Trigger Phase 4 when Phase 3 ready |
| `phase4-to-phase5-orchestrator` | us-west2 | Trigger predictions when features ready |
| `phase5-to-phase6-orchestrator` | us-west2 | Trigger grading when predictions ready |
| `auto-retry-processor` | us-west2 | Retry failed processors |
| `daily-health-summary` | us-west2 | Daily health report |

### Key Design Patterns

**1. Firestore State Tracking**
```python
# Each orchestrator tracks completion in Firestore
doc_ref = db.collection('phase3_completion').document(game_date)
# Uses atomic transactions to prevent race conditions
```

**2. Dual Tracking (Firestore + BigQuery)**
- Firestore: Fast state tracking, atomic transactions
- BigQuery: Backup tracking, queryable history
- Non-blocking: BigQuery failures don't break orchestration

**3. Validation Gates**
```python
# BLOCKING mode (Phase 3→4): Stops pipeline if validation fails
# WARNING mode (Phase 2→3): Logs but allows to proceed
validator = PhaseBoundaryValidator(mode=ValidationMode.BLOCKING)
```

**4. Tiered Timeouts (Phase 4→5)**
- Tier 1: 30 min for all 5 processors
- Tier 2: 1 hour for 4/5 processors
- Tier 3: 2 hours for 3/5 processors
- Max: 4 hours, trigger regardless

---

## Study Guide for Finding More Issues

### Area 1: Validation Scripts

**Location:** `/bin/validation/`

**Key Scripts to Study:**

| Script | What It Checks | Study For |
|--------|----------------|-----------|
| `daily_data_completeness.py` | Phase coverage | Understanding phase flow |
| `workflow_health.py` | Orchestration gaps | Detecting silent failures |
| `phase_transition_health.py` | Data flow between phases | Finding bottlenecks |
| `root_cause_analyzer.py` | Why things fail | Diagnostic patterns |
| `advanced_validation_angles.py` | 15 specialized checks | Edge cases |

**Pattern to Look For:**
```python
# Each validator follows this pattern:
class Validator:
    def __init__(self):
        self.client = bigquery.Client()

    def run_checks(self, date_range) -> List[Result]:
        # Queries BigQuery tables
        # Compares expected vs actual
        # Returns issues with severity

    def print_report(self):
        # Formats output for CLI
```

**Questions to Ask:**
1. What tables does each validator query?
2. What thresholds trigger warnings vs errors?
3. Are there any missing checks for your use case?

---

### Area 2: Orchestrator Code

**Location:** `/orchestration/cloud_functions/*/main.py`

**Key Files:**

| File | Lines | Key Logic |
|------|-------|-----------|
| `phase2_to_phase3/main.py` | 1,175 | Monitoring only, deadline logic |
| `phase3_to_phase4/main.py` | 1,506 | Mode-aware orchestration, coverage gating |
| `phase4_to_phase5/main.py` | 1,419 | Tiered timeouts, HTTP trigger |
| `phase5_to_phase6/main.py` | ~1,000 | Grading trigger logic |

**Pattern to Look For:**
```python
# Completion tracking
@firestore.transactional
def update_completion_atomic(transaction, doc_ref, processor_name):
    # Atomic update to prevent race conditions

# Validation before triggering
if not validation_result.is_valid:
    if mode == ValidationMode.BLOCKING:
        raise ValueError("Cannot proceed")
    else:
        send_alert()  # Warning only

# Phase trigger
publish_to_topic('nba-phase{N+1}-trigger', message)
```

**Questions to Ask:**
1. What conditions must be met to trigger next phase?
2. What happens if a processor never completes?
3. How are errors logged and alerted?

---

### Area 3: Shared Utilities

**Location:** `/shared/utils/`

**Key Files:**

| File | Purpose | Dependencies |
|------|---------|--------------|
| `__init__.py` | Export all utilities | PROBLEM: Eager imports |
| `phase_execution_logger.py` | Log orchestrator timing | BigQuery |
| `completion_tracker.py` | Track processor completions | BigQuery, Firestore |
| `bigquery_utils.py` | BQ helper functions | google-cloud-bigquery |
| `bigquery_utils_v2.py` | Updated BQ helpers | Same |

**Questions to Ask:**
1. Which modules have heavy dependencies (pandas, psutil)?
2. What happens if a utility function fails silently?
3. Are there duplicate utilities that should be consolidated?

---

### Area 4: Data Processors

**Location:** `/data_processors/`

**Key Files:**

| Directory | Purpose |
|-----------|---------|
| `raw/` | GCS → BigQuery (Phase 2) |
| `analytics/` | Raw → Analytics (Phase 3) |
| `precompute/` | Analytics → Features (Phase 4) |
| `grading/` | Predictions → Grading (Phase 6) |

**Base Classes to Study:**
- `/data_processors/raw/processor_base.py` - Smart idempotency, heartbeat
- `/data_processors/analytics/analytics_base.py` - Multi-source fallback
- `/data_processors/precompute/precompute_base.py` - Rolling windows, circuit breaker

**Questions to Ask:**
1. How does each processor handle partial failures?
2. What deduplication logic prevents reprocessing?
3. Where might data quality issues slip through?

---

### Area 5: Scrapers

**Location:** `/scrapers/`

**Key Files:**

| File | Source | Data |
|------|--------|------|
| `balldontlie/bdl_player_box_scores.py` | BDL API | Player boxscores |
| `nba_com/nbac_gamebook.py` | NBA.com | Official boxscores |
| `odds_api/` | Odds API | Prop lines |

**Questions to Ask:**
1. What retry logic exists for API failures?
2. How are rate limits handled?
3. What fallback sources exist when primary fails?

---

### Area 6: Configuration

**Location:** `/shared/config/`

**Key Files:**

| File | Purpose |
|------|---------|
| `orchestration_config.py` | Phase configuration, timeouts |
| `gcp_config.py` | GCP project settings |

**Cloud Function Configs:**
Each cloud function has its own `/shared/config/orchestration_config.py` that may drift from the root version.

**Questions to Ask:**
1. Are configs consistent across cloud functions?
2. What timeouts might be too short/long?
3. Are all phases configured correctly?

---

### Recommended Investigation Order

1. **Start with validation scripts** - They reveal what the system monitors
2. **Then study orchestrators** - They control the pipeline flow
3. **Then examine processors** - They do the actual data work
4. **Finally review configs** - They tune behavior

---

## Quick Reference

### Validation Commands

```bash
# Daily health check
python bin/validation/daily_data_completeness.py --days 3

# Orchestration health
python bin/validation/workflow_health.py --hours 48

# Deep analysis for specific date
python bin/validation/comprehensive_health_check.py --date 2026-01-24

# Diagnose issues with fix commands
python bin/validation/daily_pipeline_doctor.py --days 3 --show-fixes

# Root cause analysis
python bin/validation/root_cause_analyzer.py --date 2026-01-24

# Phase transitions
python bin/validation/phase_transition_health.py --days 7
```

### BigQuery Validation Queries

```sql
-- Check schedule vs boxscore coverage
SELECT
  'schedule' as source, COUNT(*) as count
FROM `nba-props-platform.nba_raw.v_nbac_schedule_latest`
WHERE game_date = '2026-01-24' AND game_status = 3
UNION ALL
SELECT
  'boxscores' as source, COUNT(DISTINCT game_id) as count
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date = '2026-01-24';

-- Check failed processor queue
SELECT game_date, processor_name, status, retry_count, error_message
FROM `nba_orchestration.failed_processor_queue`
WHERE status IN ('pending', 'retrying', 'failed_permanent')
ORDER BY first_failure_at DESC
LIMIT 20;

-- Check phase execution logging
SELECT phase_name, game_date, status, duration_seconds, games_processed
FROM `nba_orchestration.phase_execution_log`
WHERE DATE(execution_timestamp) >= CURRENT_DATE() - 3
ORDER BY execution_timestamp DESC;

-- Check workflow decisions (orchestration health)
SELECT
  DATE(decision_time) as date,
  COUNT(*) as decisions,
  MAX(decision_time) as last_decision
FROM `nba_orchestration.workflow_decisions`
WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
GROUP BY 1
ORDER BY 1 DESC;

-- Feature quality distribution
SELECT
  CASE
    WHEN feature_quality_score >= 75 THEN 'gold'
    WHEN feature_quality_score >= 65 THEN 'silver'
    ELSE 'bronze'
  END as tier,
  COUNT(*) as count,
  ROUND(AVG(feature_quality_score), 1) as avg_score
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = '2026-01-24'
GROUP BY 1;
```

### Cloud Function Commands

```bash
# Check function status
gcloud functions list --region us-west2 | grep -E "phase|retry|health"

# View recent logs
gcloud functions logs read FUNCTION_NAME --region us-west2 --limit 50

# Check for errors
gcloud functions logs read FUNCTION_NAME --region us-west2 --limit 100 2>&1 | grep -E "ERROR|Error|Traceback"

# Deploy a function
./bin/orchestrators/deploy_phase3_to_phase4.sh
```

### Pub/Sub Commands

```bash
# List topics
gcloud pubsub topics list | grep nba

# List subscriptions
gcloud pubsub subscriptions list | grep nba

# Publish test message
gcloud pubsub topics publish nba-phase2-fallback-trigger --message='{"test": true}'
```

### Manual Backfill Commands

```bash
# Boxscores
python bin/backfill/bdl_boxscores.py --date 2026-01-24

# Phase 3 analytics
python bin/backfill/phase3.py --date 2026-01-24

# Phase 4 features
python bin/backfill/phase4.py --date 2026-01-24

# Grading
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-24 --end-date 2026-01-24
```

---

## Immediate Action Items

### Priority 1: Run Grading Backfill for Jan 24 (CRITICAL - Quick Win)

3 games have complete boxscores but zero grading. This is the fastest fix:
```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-24 --end-date 2026-01-24
```

Verify after:
```bash
bq query --use_legacy_sql=false "
SELECT game_id, COUNT(*) as graded
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-01-24'
GROUP BY 1
"
# Should show 6 games (not 3)
```

### Priority 2: Fix Auto-Retry Topic Mappings (CRITICAL)

1. Edit `/orchestration/cloud_functions/auto_retry_processor/main.py`
2. Update `PHASE_TOPIC_MAP` (3 of 4 entries are wrong):
   ```python
   PHASE_TOPIC_MAP = {
       'phase_2': 'nba-phase2-fallback-trigger',     # Was: nba-phase1-scraper-trigger
       'phase_3': 'nba-phase3-fallback-trigger',     # Was: nba-phase3-analytics-trigger
       'phase_4': 'nba-phase4-fallback-trigger',     # Was: nba-phase4-precompute-trigger
       'phase_5': 'nba-predictions-trigger',          # Keep - this works
   }
   ```
3. Redeploy: `./bin/orchestrators/deploy_auto_retry_processor.sh`
4. Verify: `gcloud functions logs read auto-retry-processor --region us-west2 --limit 10`

### Priority 3: Create Fallback Topic Subscriptions

The fallback topics exist but have no subscribers:
```bash
# Create subscription for phase2-fallback-trigger → Phase 2 processor
gcloud pubsub subscriptions create nba-phase2-fallback-sub \
  --topic=nba-phase2-fallback-trigger \
  --push-endpoint=https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process \
  --push-auth-service-account=756957797294-compute@developer.gserviceaccount.com \
  --ack-deadline=600

# Repeat for phase3, phase4 fallback triggers
```

### Priority 4: Recover GSW@MIN Boxscore

After fixing auto-retry, OR manually:
```bash
python bin/backfill/bdl_boxscores.py --date 2026-01-24
```

### Priority 5: Verify Phase Execution Logging

```bash
# Check if table can receive data
bq query --use_legacy_sql=false "
INSERT INTO nba_orchestration.phase_execution_log
(execution_timestamp, phase_name, game_date, status, duration_seconds, games_processed)
VALUES (CURRENT_TIMESTAMP(), 'manual_test', '2026-01-25', 'test', 0.1, 0)
"

# Check cloud function has logging calls
gcloud functions logs read phase3-to-phase4-orchestrator --region us-west2 --limit 50
```

### Priority 6: Tonight's Games Monitoring

After 11 PM ET, verify all 7 games have boxscores:
```bash
python bin/validation/daily_data_completeness.py --days 1
```

---

*Document created: 2026-01-25*
*Last validation run: 2026-01-25 ~16:00 UTC*
