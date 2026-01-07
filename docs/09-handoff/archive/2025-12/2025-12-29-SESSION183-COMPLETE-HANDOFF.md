# Session 183 Complete Handoff - Pipeline Robustness

**Date:** 2025-12-29 (04:35 UTC)
**Session:** 183
**Previous Session:** 182 (data gaps investigation)
**Status:** Major fixes complete, follow-up work documented

---

## Context for New Chat

Session 182 discovered that **5 teams had 0 players in predictions** due to a cascading failure:

```
Root Cause Chain:
1. bdl_player_box_scores scraper writes to ball-dont-lie/player-box-scores/
2. NO PROCESSOR was registered for this path in Phase 2
3. Data went to GCS but NEVER loaded to BigQuery
4. Completeness checks failed (<70%) for affected teams
5. Circuit breakers tripped after 5 failures
6. Players locked out for 7 DAYS (too aggressive!)
7. Even after backfilling data, players remained locked out
```

Session 183 fixed the critical issues. This handoff documents remaining work.

---

## What Was Completed (Session 183)

### 1. New Processor for player-box-scores Path ✅

**Problem:** Data was being lost - scraper worked but no processor loaded to BigQuery.

**Fix:** Created `BdlPlayerBoxScoresProcessor`

**Files:**
- `data_processors/raw/balldontlie/bdl_player_box_scores_processor.py` (NEW)
- `data_processors/raw/main_processor_service.py` (registry entry added)

**Registry Entry (line 86):**
```python
# NOTE: player-box-scores MUST come before boxscores due to substring matching
'ball-dont-lie/player-box-scores': BdlPlayerBoxScoresProcessor,  # /stats endpoint
'ball-dont-lie/boxscores': BdlBoxscoresProcessor,  # /boxscores endpoint
```

**Tested:** Published message, processor ran successfully (405s for 6982 rows).

### 2. Boxscore Completeness Scheduler ✅

**Scheduler:** `boxscore-completeness-check`
- **Schedule:** 6 AM ET daily (`0 6 * * *`)
- **Endpoint:** `https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/monitoring/boxscore-completeness`
- **Action:** Alerts when any team below 70% boxscore coverage

**IAM Fix Required:**
```bash
# scheduler-orchestration SA needed invoker permission on Phase 2
gcloud run services add-iam-policy-binding nba-phase2-raw-processors \
    --region=us-west2 \
    --member="serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com" \
    --role="roles/run.invoker"
```

**Test Command:**
```bash
gcloud scheduler jobs run boxscore-completeness-check --location=us-west2
```

### 3. Circuit Breaker Lockout Reduced (7 days → 24 hours) ✅

**New Config:** `shared/config/orchestration_config.py`

```python
@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    # Entity-level lockout (WAS 7 days, NOW 24 hours)
    entity_lockout_hours: int = 24
    entity_failure_threshold: int = 5
    auto_reset_on_data: bool = True

    # Processor-level (unchanged)
    processor_timeout_minutes: int = 30
    processor_failure_threshold: int = 5
```

**Environment Override:**
```bash
CIRCUIT_BREAKER_ENTITY_LOCKOUT_HOURS=24  # Can set to any value
```

**Updated Processors (use config):**
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

### 4. Notification Parameter Bug Fixed ✅

**Problem:** `notify_error()` was called with `context=` but parameter is `details=`

**File:** `data_processors/raw/main_processor_service.py` (lines 218-230)

```python
# Before (broken):
notify_error(..., context={'critical_teams': critical_teams})

# After (fixed):
notify_error(..., details={'critical_teams': critical_teams}, processor_name="Boxscore Completeness Check")
```

---

## Remaining Work (TODO List)

### P1: Fix Prediction Worker Duplicates

**Priority:** HIGH - causes 5x data bloat, frontend has workaround but needs fix

**Problem:**
- Prediction worker uses `WRITE_APPEND` for BigQuery inserts
- Pub/Sub retries cause duplicate messages
- Result: 5 copies of each prediction row

**File:** `predictions/worker/worker.py` (lines 996-1041)

**Current Code (problematic):**
```python
# Around line 1020
job_config = bigquery.LoadJobConfig(
    schema=table.schema,
    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,  # PROBLEM!
)
load_job = self.bq_client.load_table_from_json(predictions, table_id, job_config=job_config)
```

**Recommended Fix - Use MERGE:**
```python
# Replace load_table_from_json with MERGE statement
merge_query = f"""
MERGE `{table_id}` T
USING UNNEST(@predictions) S
ON T.player_lookup = S.player_lookup
   AND T.game_date = S.game_date
   AND T.prop_type = S.prop_type
WHEN MATCHED THEN
  UPDATE SET
    predicted_value = S.predicted_value,
    confidence_score = S.confidence_score,
    is_active = S.is_active,
    updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (player_lookup, game_date, prop_type, predicted_value, confidence_score, is_active, created_at, updated_at)
  VALUES (S.player_lookup, S.game_date, S.prop_type, S.predicted_value, S.confidence_score, S.is_active, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
"""
```

**Current Workaround:** Tonight exporter uses `ROW_NUMBER() QUALIFY` to deduplicate.

### P1: Update Remaining Circuit Breaker Hardcodes

**Priority:** HIGH - other processors still use 7-day lockout

**Files with hardcoded `timedelta(days=7)`:**
```bash
# Find all occurrences:
grep -rn "timedelta(days=7)" data_processors/
```

**Results:**
1. `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py:1066`
2. `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py:810`
3. `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py:1172, 1237`
4. `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py:607`
5. `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py:1036`

**Pattern to Apply (copy from updated files):**
```python
def _increment_reprocess_count(self, entity_id: str, analysis_date: date, completeness_pct: float, skip_reason: str) -> None:
    """Track reprocessing attempt and trip circuit breaker if needed."""
    from shared.config.orchestration_config import get_orchestration_config
    config = get_orchestration_config()

    # ... existing code ...

    if circuit_breaker_tripped:
        # Use config for lockout duration (default: 24 hours, was 7 days)
        circuit_breaker_until = datetime.now(timezone.utc) + timedelta(hours=config.circuit_breaker.entity_lockout_hours)
        logger.error(f"{entity_id}: Circuit breaker TRIPPED (lockout: {config.circuit_breaker.entity_lockout_hours}h)")
```

### P2: Add Automatic Backfill Trigger

**Priority:** MEDIUM - would auto-heal gaps instead of manual intervention

**Concept:**
1. `boxscore-completeness-check` runs at 6 AM ET
2. If gaps found, publish to `boxscore-gaps-detected` topic
3. New Cloud Function triggers backfill scraper for missing dates

**Implementation Location:** `orchestration/cloud_functions/boxscore_backfill/`

**Scraper to Trigger:**
```bash
curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scraper_name": "bdl_player_box_scores", "params": {"startDate": "2025-12-27", "endDate": "2025-12-27"}}'
```

### P2: Extend Self-Heal to Phase 2

**Priority:** MEDIUM - current self-heal only checks predictions exist

**Current Self-Heal:** `orchestration/cloud_functions/self_heal/main.py`
- Runs at 2:15 PM ET
- Checks if tomorrow's predictions exist
- Triggers Phase 3/4/5 if missing

**Proposed Enhancement:**
```python
def check_phase2_health(bq_client, target_date):
    """Check if Phase 2 raw data is complete."""
    yesterday = target_date - timedelta(days=1)

    # Check boxscore completeness for yesterday
    query = f"""
    SELECT
      s.team,
      COUNTIF(b.team_abbr IS NOT NULL) as has_boxscore
    FROM (
      SELECT DISTINCT home_team_tricode as team, game_date FROM nba_raw.nbac_schedule
      WHERE game_date = '{yesterday}' AND game_status = 3
      UNION ALL
      SELECT DISTINCT away_team_tricode, game_date FROM nba_raw.nbac_schedule
      WHERE game_date = '{yesterday}' AND game_status = 3
    ) s
    LEFT JOIN nba_raw.bdl_player_boxscores b
      ON s.game_date = b.game_date AND s.team = b.team_abbr
    GROUP BY s.team
    HAVING has_boxscore = 0
    """
    missing_teams = list(bq_client.query(query).result())

    if missing_teams:
        # Trigger backfill
        trigger_boxscore_backfill(yesterday, [t.team for t in missing_teams])
```

### P2: Circuit Breaker Auto-Reset

**Priority:** MEDIUM - players stay locked even after data is fixed

**Concept:**
When boxscore data becomes available for a player/team, automatically clear their circuit breaker.

**Implementation:**
```python
def auto_reset_circuit_breakers(game_date: date):
    """Clear circuit breakers for entities that now have data."""
    query = f"""
    UPDATE `nba_orchestration.reprocess_attempts`
    SET circuit_breaker_tripped = FALSE,
        circuit_breaker_until = NULL,
        notes = CONCAT(notes, ' | Auto-reset: data available')
    WHERE circuit_breaker_tripped = TRUE
      AND circuit_breaker_until > CURRENT_TIMESTAMP()
      AND entity_id IN (
        SELECT DISTINCT player_lookup
        FROM nba_raw.bdl_player_boxscores
        WHERE game_date >= DATE_SUB('{game_date}', INTERVAL 3 DAY)
      )
    """
```

### P3: Morning Data Completeness Report

**Priority:** LOW - nice visibility but not critical

**Concept:** Email summary at 7 AM ET after overnight collection.

**Content:**
- Games collected: X/Y
- Boxscore coverage: 98%
- Gamebook coverage: 95%
- Missing teams/dates
- Active circuit breakers

---

## Key Files Reference

### Processor Registry
```
data_processors/raw/main_processor_service.py
  - Line 72-104: PROCESSOR_REGISTRY
  - Line 129-245: /monitoring/boxscore-completeness endpoint
  - Line 791-809: extract_opts_from_path for player-box-scores
```

### Circuit Breaker Config
```
shared/config/orchestration_config.py
  - Line 124-144: CircuitBreakerConfig dataclass
  - Line 176: Added to OrchestrationConfig
  - Line 207-214: Environment variable support
```

### Updated Processors (use config)
```
data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
  - Line 1486-1508: _increment_reprocess_count (UPDATED)

data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
  - Line 564-586: _increment_reprocess_count (UPDATED)
```

### Processors Needing Update (still hardcoded)
```
data_processors/precompute/player_composite_factors/player_composite_factors_processor.py:1066
data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py:810
data_processors/precompute/player_daily_cache/player_daily_cache_processor.py:1172,1237
data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py:607
data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py:1036
```

### Prediction Worker (duplicates issue)
```
predictions/worker/worker.py
  - Line 996-1041: BigQuery insert logic (needs MERGE)
```

### Self-Heal Function
```
orchestration/cloud_functions/self_heal/main.py
  - Current: Checks predictions exist
  - Needed: Add Phase 2 data checks
```

---

## Deployment Commands

### Phase 2 (Raw Processors)
```bash
./bin/raw/deploy/deploy_processors_simple.sh
```

### Phase 3 (Analytics)
```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
```

### Phase 4 (Precompute)
```bash
./bin/precompute/deploy/deploy_precompute_processors.sh
```

### Phase 5 (Predictions)
```bash
./bin/predictions/deploy/deploy_prediction_worker.sh
```

---

## Verification Commands

### Check processor registry loaded:
```bash
PYTHONPATH=. python3 -c "
from data_processors.raw.main_processor_service import PROCESSOR_REGISTRY
print('Registry entries:', len(PROCESSOR_REGISTRY))
for k in sorted(PROCESSOR_REGISTRY.keys()):
    print(f'  {k}')
"
```

### Check circuit breaker config:
```bash
PYTHONPATH=. python3 -c "
from shared.config.orchestration_config import get_orchestration_config
config = get_orchestration_config()
print(f'Entity lockout: {config.circuit_breaker.entity_lockout_hours} hours')
print(f'Failure threshold: {config.circuit_breaker.entity_failure_threshold}')
print(f'Auto reset: {config.circuit_breaker.auto_reset_on_data}')
"
```

### Check active circuit breakers:
```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT processor_name, entity_id, analysis_date, circuit_breaker_until
FROM nba_orchestration.reprocess_attempts
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
ORDER BY circuit_breaker_until DESC
LIMIT 20
"
```

### Check prediction duplicates:
```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT player_lookup, game_date, prop_type, COUNT(*) as copies
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
GROUP BY player_lookup, game_date, prop_type
HAVING COUNT(*) > 1
LIMIT 10
"
```

### Test boxscore completeness:
```bash
gcloud scheduler jobs run boxscore-completeness-check --location=us-west2

# Check logs
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors" AND textPayload=~"completeness"' --limit=5 --freshness=5m
```

---

## Current Service Revisions

| Service | Revision | Deployed |
|---------|----------|----------|
| Phase 2 | `nba-phase2-raw-processors-00045-pmr` | 04:07 UTC |
| Phase 3 | `nba-phase3-analytics-processors-*` | 04:20 UTC |
| Phase 4 | `nba-phase4-precompute-processors-00026-lrn` | 04:31 UTC |

---

## Git Commits (Session 183)

```
ffed66b feat: Add processor for ball-dont-lie/player-box-scores path
c163982 fix: Use correct parameters for notify_error/notify_warning
cd5f22c feat: Reduce circuit breaker lockout from 7 days to 24 hours
99696c6 docs: Add Session 183 handoff - pipeline robustness improvements
```

---

## Related Documentation

- `docs/08-projects/current/PIPELINE-ROBUSTNESS-PLAN.md` - Full improvement plan with all tasks
- `docs/08-projects/current/BOXSCORE-DATA-GAPS-ANALYSIS.md` - Session 182 root cause analysis
- `docs/08-projects/current/self-healing-pipeline/README.md` - Current self-heal system
- `docs/09-handoff/2025-12-28-SESSION182-COMPLETE-HANDOFF.md` - Previous session handoff

---

## Quick Start for New Chat

1. **Read this handoff** - understand what was done and what remains
2. **Pick a P1 task** - either prediction duplicates or circuit breaker hardcodes
3. **Use verification commands** - confirm current state before making changes
4. **Deploy after changes** - use appropriate deploy script
5. **Update docs** - keep PIPELINE-ROBUSTNESS-PLAN.md current
