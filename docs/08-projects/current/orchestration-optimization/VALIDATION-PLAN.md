# NBA Pipeline Validation Plan

**Created**: 2026-01-15 (Session 61)
**Purpose**: Comprehensive validation framework for daily orchestration and backfilled data

---

## Table of Contents

1. [Daily Orchestration Validation](#daily-orchestration-validation)
2. [Backfill Data Validation](#backfill-data-validation)
3. [Cross-Phase Consistency Checks](#cross-phase-consistency-checks)
4. [Automated Monitoring](#automated-monitoring)
5. [Manual Validation Scripts](#manual-validation-scripts)

---

## Daily Orchestration Validation

### 1. Pipeline Health Check (Run Daily)

```bash
# Quick pipeline status check
bq query --nouse_legacy_sql "
SELECT
  'Phase2_boxscores' as phase, MAX(game_date) as latest, 'nba_raw' as dataset
FROM nba_raw.bdl_player_boxscores WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT 'Phase3_player_summary', MAX(game_date), 'nba_analytics'
FROM nba_analytics.player_game_summary WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT 'Phase3_team_offense', MAX(game_date), 'nba_analytics'
FROM nba_analytics.team_offense_game_summary WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT 'Phase3_team_defense', MAX(game_date), 'nba_analytics'
FROM nba_analytics.team_defense_game_summary WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT 'Phase4_composite', MAX(game_date), 'nba_precompute'
FROM nba_precompute.player_composite_factors WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT 'Phase5_predictions', MAX(game_date), 'nba_predictions'
FROM nba_predictions.player_prop_predictions WHERE is_active = TRUE
ORDER BY phase
"
```

**Expected Results**:
- All phases should have data for yesterday (games processed)
- Predictions should have data for today (upcoming games)

### 2. Prediction Coverage Validation

```bash
# Check prediction coverage vs prop lines
bq query --nouse_legacy_sql "
WITH props AS (
  SELECT DISTINCT player_lookup FROM nba_raw.odds_api_player_points_props WHERE game_date = CURRENT_DATE()
),
predictions AS (
  SELECT DISTINCT player_lookup FROM nba_predictions.player_prop_predictions WHERE game_date = CURRENT_DATE() AND is_active = TRUE
)
SELECT
  COUNT(DISTINCT p.player_lookup) as players_with_props,
  COUNT(DISTINCT pred.player_lookup) as players_with_predictions,
  COUNT(DISTINCT p.player_lookup) - COUNT(DISTINCT pred.player_lookup) as missing_predictions,
  ROUND((COUNT(DISTINCT pred.player_lookup) / NULLIF(COUNT(DISTINCT p.player_lookup), 0)) * 100, 1) as coverage_pct
FROM props p
LEFT JOIN predictions pred ON p.player_lookup = pred.player_lookup
"
```

**Expected Results**:
- Coverage should be >90%
- Missing predictions should be explained by low-minutes players or recent injuries

### 2b. List Missing Players (Props without Predictions)

```bash
# Identify specific players with prop bets but no predictions
bq query --nouse_legacy_sql "
SELECT DISTINCT player_lookup
FROM nba_raw.odds_api_player_points_props
WHERE game_date = CURRENT_DATE()
  AND player_lookup NOT IN (
    SELECT DISTINCT player_lookup
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = CURRENT_DATE() AND is_active = TRUE
  )
ORDER BY player_lookup
"
```

**Expected Results**: List should be small (<5 players) and explainable

### 2c. Enhanced Coverage with Alias Resolution

```bash
# Coverage validation that resolves aliases for accurate reporting
bq query --nouse_legacy_sql "
WITH props AS (
  SELECT DISTINCT
    p.player_lookup as props_lookup,
    COALESCE(a.nba_canonical_lookup, p.player_lookup) as canonical_lookup
  FROM nba_raw.odds_api_player_points_props p
  LEFT JOIN nba_reference.player_aliases a ON p.player_lookup = a.alias_lookup AND a.is_active = TRUE
  WHERE p.game_date = CURRENT_DATE()
),
predictions AS (
  SELECT DISTINCT player_lookup
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE() AND is_active = TRUE
)
SELECT
  COUNT(DISTINCT props_lookup) as players_with_props,
  COUNT(DISTINCT CASE WHEN pred.player_lookup IS NOT NULL THEN props_lookup END) as matched_via_canonical,
  COUNT(DISTINCT CASE WHEN pred.player_lookup IS NULL THEN props_lookup END) as truly_missing,
  ROUND(COUNT(DISTINCT CASE WHEN pred.player_lookup IS NOT NULL THEN props_lookup END) /
        NULLIF(COUNT(DISTINCT props_lookup), 0) * 100, 1) as coverage_pct
FROM props
LEFT JOIN predictions pred ON props.canonical_lookup = pred.player_lookup
"
```

**Expected Results**:
- `truly_missing` should be 0 or very small
- Any missing should be explained by timing issues (context created after coordinator)

### 2d. Name Normalization Gap Check

```bash
# Find players in props but NOT in upcoming_player_game_context (name mismatch)
bq query --nouse_legacy_sql "
SELECT DISTINCT player_lookup
FROM nba_raw.odds_api_player_points_props
WHERE game_date = CURRENT_DATE()
  AND player_lookup NOT IN (
    SELECT DISTINCT player_lookup
    FROM nba_analytics.upcoming_player_game_context
    WHERE game_date = CURRENT_DATE()
  )
"
```

**Expected Results**: 0 players (name resolution should handle all variants)

**Known Name Normalization Issues (Fixed)**:
- `isaiahstewartii` → `isaiahstewart` (alias added Session 62)
- `vincentwilliamsjr` → `vincewilliamsjr` (alias exists)

### 2d. Timing Validation (Context vs Coordinator)

```bash
# Check if context data was created BEFORE coordinator ran
bq query --nouse_legacy_sql "
WITH context_times AS (
  SELECT player_lookup, MAX(created_at) as context_created
  FROM nba_analytics.upcoming_player_game_context
  WHERE game_date = CURRENT_DATE()
  GROUP BY player_lookup
),
coordinator_runs AS (
  SELECT MAX(started_at) as last_successful_run
  FROM nba_reference.processor_run_history
  WHERE processor_name = 'PredictionCoordinator'
    AND data_date = CURRENT_DATE()
    AND status = 'success'
)
SELECT
  ct.player_lookup,
  ct.context_created,
  cr.last_successful_run,
  CASE WHEN ct.context_created > cr.last_successful_run THEN 'CREATED_AFTER_COORDINATOR' ELSE 'OK' END as timing_status
FROM context_times ct
CROSS JOIN coordinator_runs cr
WHERE ct.context_created > cr.last_successful_run
ORDER BY ct.context_created DESC
LIMIT 20
"
```

**Expected Results**: Ideally 0 players created after coordinator. If found, coordinator needs re-run

### 3. Error Log Monitoring

```bash
# Check for errors in last 6 hours
gcloud logging read '
  (resource.labels.service_name=~"nba-phase" OR resource.labels.service_name="prediction-coordinator")
  AND severity>=ERROR
  AND NOT textPayload:"bigdataball"
  AND NOT textPayload:"No games found"
' --limit=20 --freshness=6h --format="table(timestamp,resource.labels.service_name,textPayload)"
```

**Expected Results**:
- No critical errors
- Acceptable: "No data for future dates", "Games not started yet"

### 3. Coordinator Run Duration Check

```bash
# Check if coordinator has been running too long
bq query --nouse_legacy_sql "
SELECT
  processor_name,
  status,
  data_date,
  started_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as minutes_running
FROM nba_reference.processor_run_history
WHERE processor_name = 'PredictionCoordinator'
  AND status = 'running'
ORDER BY started_at DESC
"
```

**Expected Results**: No coordinator running >30 minutes (typical run is 2-5 minutes)

### 3b. Coordinator Batch Progress Check

```bash
# Check recent coordinator completions from logs
gcloud logging read '
  resource.labels.service_name="prediction-coordinator"
  AND textPayload=~"completed.*[0-9]+/[0-9]+"
' --limit=5 --freshness=2h --format="value(textPayload)" 2>/dev/null | head -10
```

**Expected Results**: Progress should show X/X (complete), not X/Y where X < Y

### 3c. Staging Tables vs Main Predictions

```bash
# Compare staging tables count vs main predictions
echo "=== Staging tables for today ==="
bq ls nba_predictions 2>/dev/null | grep -c "staging.*$(date +%Y_%m_%d)"

echo "=== Main predictions count ==="
bq query --nouse_legacy_sql "
SELECT COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
"
```

**Expected Results**: If staging > main, consolidation may be pending due to incomplete batch

### 4. Stuck Run History Check

```bash
# Find stuck entries (should be 0)
bq query --nouse_legacy_sql "
SELECT processor_name, COUNT(*) as stuck_count
FROM nba_reference.processor_run_history
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) > 1
GROUP BY processor_name
"
```

**Expected Results**: 0 stuck entries

### 5. Grading Pipeline Validation

```bash
# Check grading accuracy trends
bq query --nouse_legacy_sql "
SELECT
  game_date,
  COUNT(*) as graded,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as accuracy_pct
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
"
```

**Expected Results**:
- All completed game dates should have graded predictions
- Accuracy should be relatively stable (40-55% is typical for player props)

---

## Backfill Data Validation

### 1. Data Completeness Check

```bash
# Check for gaps in daily data
bq query --nouse_legacy_sql "
WITH date_range AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY(DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY), CURRENT_DATE())) as date
),
scheduled AS (
  SELECT DISTINCT game_date
  FROM nba_raw.nbac_schedule
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),
processed AS (
  SELECT DISTINCT game_date
  FROM nba_analytics.player_game_summary
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)
SELECT
  s.game_date,
  CASE WHEN p.game_date IS NULL THEN 'MISSING' ELSE 'OK' END as status
FROM scheduled s
LEFT JOIN processed p ON s.game_date = p.game_date
ORDER BY s.game_date
"
```

**Expected Results**: No MISSING dates

### 2. Player Count Consistency

```bash
# Check player counts across phases for a date
bq query --nouse_legacy_sql "
DECLARE check_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

SELECT
  'boxscores' as source,
  COUNT(DISTINCT player_lookup) as player_count
FROM nba_raw.bdl_player_boxscores
WHERE game_date = check_date
UNION ALL
SELECT 'player_game_summary', COUNT(DISTINCT player_lookup)
FROM nba_analytics.player_game_summary
WHERE game_date = check_date
UNION ALL
SELECT 'composite_factors', COUNT(DISTINCT player_lookup)
FROM nba_precompute.player_composite_factors
WHERE game_date = check_date
"
```

**Expected Results**: Counts should be within 10% of each other

### 3. Record Quality Analysis

```bash
# Check for NULL rates in critical fields
bq query --nouse_legacy_sql "
SELECT
  'player_game_summary' as table_name,
  COUNT(*) as total,
  COUNTIF(points IS NULL) as null_points,
  COUNTIF(minutes_played IS NULL) as null_minutes,
  ROUND(COUNTIF(points IS NULL) / COUNT(*) * 100, 2) as null_points_pct
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
"
```

**Expected Results**: NULL rates should be <1%

---

## Cross-Phase Consistency Checks

### 1. Phase 2 → Phase 3 Flow

```bash
# Verify boxscores processed to summary
bq query --nouse_legacy_sql "
WITH box AS (
  SELECT game_date, COUNT(DISTINCT player_lookup) as box_players
  FROM nba_raw.bdl_player_boxscores
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
),
summary AS (
  SELECT game_date, COUNT(DISTINCT player_lookup) as sum_players
  FROM nba_analytics.player_game_summary
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
)
SELECT
  b.game_date,
  b.box_players,
  s.sum_players,
  b.box_players - COALESCE(s.sum_players, 0) as difference
FROM box b
LEFT JOIN summary s ON b.game_date = s.game_date
ORDER BY b.game_date DESC
"
```

**Expected Results**: Difference should be 0 or very small (some players may be filtered)

### 2. Phase 3 → Phase 4 Flow

```bash
# Verify analytics processed to precompute
bq query --nouse_legacy_sql "
WITH analytics AS (
  SELECT game_date, COUNT(DISTINCT player_lookup) as ana_players
  FROM nba_analytics.player_game_summary
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
),
precompute AS (
  SELECT game_date, COUNT(DISTINCT player_lookup) as pre_players
  FROM nba_precompute.player_composite_factors
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
)
SELECT
  a.game_date,
  a.ana_players,
  p.pre_players,
  a.ana_players - COALESCE(p.pre_players, 0) as difference
FROM analytics a
LEFT JOIN precompute p ON a.game_date = p.game_date
ORDER BY a.game_date DESC
"
```

**Expected Results**: Phase 4 should have similar or more players (includes predictions context)

---

## Automated Monitoring

### Self-Heal Function Checks (12:45 PM ET Daily)

The self-heal function automatically checks:
1. Phase 3 data for yesterday
2. OddsAPI data freshness
3. Predictions for today
4. Quality scores
5. Stuck run_history entries (>4h threshold)

### Alerting Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Prediction coverage | <80% | <50% |
| Stuck entries | 1-5 | >5 |
| Phase lag | 1 day | 2+ days |
| Quality score avg | <85 | <70 |

---

## Manual Validation Scripts

### Full Pipeline Validation Script

```bash
#!/bin/bash
# Save as: scripts/validate_pipeline.sh

echo "=== NBA Pipeline Validation ==="
echo "Run at: $(date)"
echo ""

echo "1. Pipeline Status:"
bq query --nouse_legacy_sql "
SELECT 'Phase2' as phase, MAX(game_date) as latest FROM nba_raw.bdl_player_boxscores WHERE game_date >= '2026-01-01'
UNION ALL SELECT 'Phase3', MAX(game_date) FROM nba_analytics.player_game_summary WHERE game_date >= '2026-01-01'
UNION ALL SELECT 'Phase4', MAX(game_date) FROM nba_precompute.player_composite_factors WHERE game_date >= '2026-01-01'
UNION ALL SELECT 'Phase5', MAX(game_date) FROM nba_predictions.player_prop_predictions WHERE is_active = TRUE
"

echo ""
echo "2. Today's Predictions:"
bq query --nouse_legacy_sql "
SELECT COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
"

echo ""
echo "3. Stuck Entries:"
bq query --nouse_legacy_sql "
SELECT COUNT(*) as stuck FROM nba_reference.processor_run_history
WHERE status = 'running' AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) > 1
"

echo ""
echo "4. Recent Errors (last 2h):"
gcloud logging read 'resource.labels.service_name=~"nba-phase" AND severity>=ERROR' --limit=5 --freshness=2h --format="table(timestamp,textPayload)" 2>/dev/null | head -15

echo ""
echo "=== Validation Complete ==="
```

### Backfill Validation Script

```bash
#!/bin/bash
# Save as: scripts/validate_backfill.sh
# Usage: ./validate_backfill.sh 2026-01-12

DATE=${1:-$(date -d "yesterday" +%Y-%m-%d)}

echo "=== Backfill Validation for $DATE ==="

echo "1. Data Counts:"
bq query --nouse_legacy_sql "
SELECT 'boxscores' as source, COUNT(*) as records FROM nba_raw.bdl_player_boxscores WHERE game_date = '$DATE'
UNION ALL SELECT 'player_summary', COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date = '$DATE'
UNION ALL SELECT 'team_offense', COUNT(*) FROM nba_analytics.team_offense_game_summary WHERE game_date = '$DATE'
UNION ALL SELECT 'team_defense', COUNT(*) FROM nba_analytics.team_defense_game_summary WHERE game_date = '$DATE'
UNION ALL SELECT 'composite', COUNT(*) FROM nba_precompute.player_composite_factors WHERE game_date = '$DATE'
"

echo ""
echo "2. Processing Status:"
bq query --nouse_legacy_sql "
SELECT processor_name, status, duration_seconds
FROM nba_reference.processor_run_history
WHERE data_date = '$DATE'
ORDER BY started_at DESC
LIMIT 10
"
```

---

## Cleanup Scripts

### Clear Stuck Run History

```bash
# Clear entries stuck >1h (use cautiously)
bq query --nouse_legacy_sql "
UPDATE nba_reference.processor_run_history
SET
  status = 'failed',
  processed_at = CURRENT_TIMESTAMP(),
  duration_seconds = TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, SECOND),
  errors = TO_JSON(STRUCT('Cleanup: stuck in running state' as message)),
  failure_category = 'timeout'
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) > 1
"
```

### Force Reprocess Date

```bash
# Reprocess a specific date through Phase 3
curl -X POST "https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "backfill_mode": true}'
```

---

## Validation Checklist

### Daily (Automated by Self-Heal)
- [ ] Phase 3 data exists for yesterday
- [ ] Predictions exist for today
- [ ] No stuck run_history entries
- [ ] OddsAPI data is fresh

### Weekly (Manual)
- [ ] Review grading accuracy trends
- [ ] Check for data gaps in last 7 days
- [ ] Verify player count consistency across phases
- [ ] Review error log patterns

### Monthly (Manual)
- [ ] Full backfill validation for last 30 days
- [ ] Confidence calibration analysis
- [ ] Player-level accuracy breakdown
- [ ] Cost analysis (BigQuery, Cloud Run)

---

## Known Issues & Resolutions

| Issue | Detection | Resolution |
|-------|-----------|------------|
| Stuck run_history | Query shows >0 stuck | Run cleanup script |
| Missing date data | Gap in daily counts | Trigger Phase 3 backfill |
| Low prediction coverage | <80% coverage | Check coordinator logs |
| MERGE syntax errors | Error logs | Check MERGE validation in analytics_base.py |
| NULL projected_minutes | Coordinator crash | v3.7.1 adds COALESCE |
| Name normalization gap | Props player not in context | Add alias to player_aliases table |
| Context created after coordinator | Timing validation shows >0 | Re-run coordinator or wait for next scheduled run |
| Coordinator stuck waiting | Running >30 min, progress < 100% | Force-start new batch or manual consolidation |
| Staging tables orphaned | Staging count > 0, main stale | Trigger consolidation manually |

### Coordinator Stuck Issues (Session 62)

**Root Cause**: Coordinator waits indefinitely for 100% worker completion. If 2/104 workers fail silently (timeout, crash, Pub/Sub issue), batch never completes.

**Detection**:
```bash
# Check if coordinator is stalled
gcloud logging read '
  resource.labels.service_name="prediction-coordinator"
  AND textPayload=~"completed.*[0-9]+/[0-9]+"
' --limit=1 --freshness=1h --format="value(textPayload)"
```

If shows "102/104" and no updates in >10 minutes → stalled.

**Resolution Options**:

1. **Force new batch** (restarts from scratch):
   ```bash
   curl -X POST "https://prediction-coordinator-756957797294.us-west2.run.app/start" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"game_date": "2026-01-15", "force": true}'
   ```

2. **Cleanup stuck run_history** (marks as failed):
   ```sql
   UPDATE nba_reference.processor_run_history
   SET status = 'failed', errors = '{"message":"Manual cleanup: stuck batch"}'
   WHERE processor_name = 'PredictionCoordinator' AND status = 'running'
   ```

**Recommended Improvements**:
- Add completion timeout (e.g., complete with partial after 30 min)
- Add `/force-complete` endpoint for manual consolidation
- Alert when batch stalls (102/104 with no progress for 10+ min)

### Name Normalization Issues (Session 62)

Players in `odds_api_player_points_props` with different `player_lookup` than canonical:

| Props Name | Canonical Name | Status |
|------------|----------------|--------|
| `isaiahstewartii` | `isaiahstewart` | ✅ Alias added |
| `vincentwilliamsjr` | `vincewilliamsjr` | ✅ Has alias |

**Resolution**: Add entries to `nba_reference.player_aliases`:
```sql
INSERT INTO nba_reference.player_aliases (
  alias_lookup, nba_canonical_lookup, alias_display, nba_canonical_display,
  alias_type, alias_source, is_active, notes, created_by, created_at, processed_at
)
VALUES (
  'isaiahstewartii', 'isaiahstewart', 'Isaiah Stewart II', 'Isaiah Stewart',
  'name_variation', 'odds_api', TRUE, 'Odds API uses suffix II for Isaiah Stewart',
  'session_62_validation', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
)
```

---

## Related Documentation

- [Session 60 Handoff](../../../09-handoff/2026-01-15-SESSION-60-NBA-PIPELINE-HANDOFF.md) - MERGE fixes
- [Session 61 Handoff](../../../09-handoff/2026-01-15-SESSION-61-HANDOFF.md) - v3.7.1 NULL fix
- [Self-Heal Function](../../../../orchestration/cloud_functions/self_heal/main.py)

---

## Validation Session Log

### Session 62 - 2026-01-15 (Evening)

**Validation Run Results**:

| Check | Result | Details |
|-------|--------|---------|
| Pipeline Status | ✅ Current | All phases at Jan 15, predictions at Jan 16 |
| Stuck Entries | ✅ None | 0 entries stuck >1h |
| Props Coverage | ⚠️ 8 missing | 40 props, 77 predictions, 8 gaps |
| Name Normalization | ⚠️ 2 issues | `isaiahstewartii`, `vincentwilliamsjr` |
| Timing Issue | ⚠️ 3 players | Context created after coordinator ran |

**Root Causes Identified**:
1. **2 name normalization gaps**: `isaiahstewartii` and `vincentwilliamsjr` in props but different names in context
2. **3 players** (`cadecunningham`, `franzwagner`, `jalenduren`) had context created at 23:51 but coordinator last ran at 16:31
3. **Coordinator currently running** (started 23:58:41) should pick up new players

**Actions Completed**:
- [x] Add alias for `isaiahstewartii` → `isaiahstewart` ✅
- [ ] Monitor running coordinator for completion (stuck 60+ min)
- [ ] Verify coverage after coordinator completes

**Enhanced Validation Query Added**:
- Coverage query now JOINs through `player_aliases` table for accurate reporting
- After alias fix: 33/40 props matched (82.5%), 7 truly missing due to timing

**Coordinator Investigation**:
- Batch `batch_2026-01-15_1768521409` stuck at 102/104 workers
- 2 workers failed silently (never responded)
- 50 staging tables exist with predictions, but not merged to main table
- Root cause: No completion timeout - waits forever for 100%

**Recommended Code Improvements**:
1. Add `completion_timeout_seconds` config (default 30 min)
2. Add `/force-complete` endpoint for manual consolidation
3. Add stall detection alerting (no progress for 10+ min)
4. Consider partial completion threshold (e.g., 95% is "good enough")

**Code Changes Made (Session 62, pending deployment)**:
- `batch_state_manager.py`: Added `check_and_complete_stalled_batch()` method
- `batch_state_manager.py`: Modified `record_completion()` to check for stall at 95%+
- `coordinator.py`: Added `/check-stalled` endpoint for manual trigger

**Deployment Note**:
The coordinator must be deployed from the project root (not just coordinator dir) because it imports `shared.config.orchestration_config`. Use Cloud Build or ensure the shared module is available.

```bash
# WRONG - fails with ModuleNotFoundError
cd predictions/coordinator && gcloud run deploy ...

# CORRECT - needs proper build context with shared module
gcloud builds submit --config=<cloudbuild-coordinator.yaml>
```

---

**Last Updated**: 2026-01-15 (Session 62)
