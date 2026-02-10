# Session 174 Handoff — START HERE

**Date:** 2026-02-09
**Commit:** `f0af164c` (deployed via Cloud Build auto-deploy)
**Previous:** Session 173 consolidated handoff (Sessions 170-172)

---

## Current Production State

- **Model:** `catboost_v9_33features_20260201_011018` (SHA: `5b3a187b`)
- **Deployed commit:** `f0af164c` (Session 174, auto-deployed)
- **Multi-line:** Disabled (Session 170)
- **Vegas pipeline:** Fixed (Sessions 168-170)
- **Post-consolidation alerts:** PVL bias + recommendation skew + vegas source (Sessions 170-171)
- **Worker completion:** Now reports for quality-skipped players (Session 174)
- **Signal calculator:** Now filters on `is_active = TRUE` (Session 174)

---

## What Was Done in Session 174

### 1. Feb 9 Predictions Regenerated (UNDER bias eliminated)

The Feb 9 FIRST-run had extreme UNDER bias (avg_pvl = -3.84) because predictions ran before Session 170-171 fixes deployed. Regenerated using `/regenerate-with-supersede`:

| Metric | Before (FIRST) | After (OVERNIGHT) |
|--------|---------------|-------------------|
| avg_pvl | -3.84 | **+0.15** |
| OVER % | 0% | **24.4%** |
| Active preds | 42 | **82** |

### 2. Two Code Fixes Deployed

**Fix A: Signal calculator `is_active` filter** (`signal_calculator.py:125`)
- Signals now only count active predictions, not superseded ones
- Without this, signals showed 188 total picks instead of 82 active

**Fix B: Worker completion for skipped players** (`worker.py:850-858, 868-873`)
- Workers now call `publish_completion_event()` for permanent skips and stale messages
- Previously, quality-blocked workers ACK'd Pub/Sub but never told the coordinator
- This caused regeneration batches to stall at <100% (82/95 in our case)

### 3. Session 172 Fixes Confirmed Already Deployed

Both fixes (line_values type-check at line 1142, recovery_median log at line 1152) were already in the codebase.

### 4. OddsAPI Line Matching Investigated (Not Resolved)

Highly variable: 4% OddsAPI (Feb 7) → 83% (Feb 8) → 24% (Feb 9). Not correlated with run mode. Root cause still unknown.

### 5. Logging Verification

All Session 170-171 logging working: PUBLISH_METRICS, CONSOLIDATION_METRICS, STALE_MESSAGE (not triggered = good). Signal calculator errors from Feb 5 were pre-deploy, now fixed.

---

## Priority Work for Next Session

### P0: Verify Feb 10 FIRST-run (CRITICAL)

**This is the first FIRST-run with ALL fixes deployed.** Check after ~6 AM ET.

```sql
SELECT prediction_run_mode, COUNT(*) as preds,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders,
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / NULLIF(COUNT(*), 0), 1) as pct_over
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-10' AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1;
```

| Metric | Target | Bad (pre-fix) |
|--------|--------|---------------|
| avg_pvl | Within +/-1.5 | -3.84 |
| OVER % | >25% | 0-7% |
| UNDER % | <75% | 89-95% |
| vegas_source | NOT null | null (many) |

Also check `#nba-alerts` — these alerts should NOT fire if healthy:
- `RECOMMENDATION_SKEW` — fires if >85% one direction
- `VEGAS_SOURCE_RECOVERY_HIGH` — fires if >30% used recovery_median
- `PVL_BIAS_DETECTED` — fires if avg_pvl > +/-2.0

### P1: Grade Feb 9 (After Games Finish)

Feb 9 has 10 games (all status=1 scheduled as of session end). Once games are Final:

```sql
-- Check if games are Final
SELECT game_id, away_team_tricode, home_team_tricode, game_status
FROM nba_reference.nba_schedule WHERE game_date = '2026-02-09';

-- Check grading
SELECT game_date, COUNT(*) FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND game_date = '2026-02-09'
GROUP BY 1;
```

If no grading records appear after games are Final, trigger grading manually.

### P2: OddsAPI Line Matching Root Cause

Need diagnostic logging in `player_loader.py:_query_actual_betting_line()` to distinguish:
- "No OddsAPI data in BigQuery for this player"
- "Query timeout"
- "Player name format mismatch"

```sql
-- Check OddsAPI raw data availability
SELECT game_date, COUNT(DISTINCT player_name) as players, COUNT(*) as rows
FROM nba_raw.odds_api_player_props
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1;
```

### P3: Hit Rate Investigation with Clean Data

Now that bugs are fixed, re-evaluate with clean BACKFILL predictions:

```sql
SELECT DATE_TRUNC(pa.game_date, WEEK) as week,
  COUNT(*) as graded, COUNTIF(pa.prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.player_prop_predictions p
  ON pa.player_lookup = p.player_lookup AND pa.game_date = p.game_date AND pa.system_id = p.system_id
WHERE pa.system_id = 'catboost_v9' AND pa.game_date >= '2026-01-12'
  AND pa.actual_points IS NOT NULL AND pa.line_value IS NOT NULL
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND p.is_active = TRUE AND p.prediction_run_mode = 'BACKFILL'
GROUP BY 1 ORDER BY 1;
```

If hit rate stays below 55% with clean data, consider `/model-experiment` with extended training window through Jan 31.

### P4: Fix `subset_picks_notifier.py` Correlated Subquery Bug

Found by P5 logging verification. Throwing errors 8+ times/hour:
```
google.api_core.exceptions.BadRequest: 400 Correlated subqueries that reference other tables are not supported
```
File: `shared/notifications/subset_picks_notifier.py:277`. Needs rewrite as a JOIN.

### P5 (Low): Regeneration Auto-Consolidation

The `/regenerate-with-supersede` endpoint doesn't auto-consolidate staging tables. Options:
1. Add `/consolidate` endpoint to coordinator
2. Have `/reset` trigger consolidation before clearing tracker
3. Have `_generate_predictions_for_date()` use the quality gate

---

## Known Operational Issues (Watch List)

### Stale Batches Block New Runs
Always check `/status` before triggering new runs. If stale batch exists, `/reset` it first:
```bash
COORD_URL=$(gcloud run services describe prediction-coordinator --region=us-west2 --project=nba-props-platform --format='value(status.url)')
curl -s "$COORD_URL/status" -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

### Regeneration Requires Manual Consolidation
See "Quick Reference: Regeneration Procedure" below. The `/regenerate-with-supersede` endpoint publishes to workers, but if the batch stalls (quality-blocked workers), you must `/reset` + manually consolidate. Session 174's worker fix should reduce this, but if quality-blocked workers still exist at the Pub/Sub level, it can still happen.

### Breakout Classifier Feature Mismatch (Non-Fatal)
Worker logs show `CatBoostError: Feature points_avg_season is present in model but not in pool`. Shadow mode only — doesn't affect predictions. Fix requires updating feature prep or retraining the breakout model.

---

## Quick Reference: Regeneration Procedure

For future sessions that need to regenerate predictions:

```bash
# 1. Get coordinator URL
COORD_URL=$(gcloud run services describe prediction-coordinator --region=us-west2 --project=nba-props-platform --format='value(status.url)')

# 2. Check for stale batches, reset if needed
curl -s "$COORD_URL/status" -H "Authorization: Bearer $(gcloud auth print-identity-token)"
# If stale:
curl -s -X POST "$COORD_URL/reset" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" -d '{"game_date":"YYYY-MM-DD"}'

# 3. Regenerate with supersede
curl -s -X POST "$COORD_URL/regenerate-with-supersede" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" -d '{"game_date":"YYYY-MM-DD","reason":"description"}'
# Note the batch_id from the response!

# 4. Wait 5-10 min, check progress
curl -s -X POST "$COORD_URL/check-stalled" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" -d '{}'

# 5. If stalled (quality-blocked workers), reset the batch
curl -s -X POST "$COORD_URL/reset" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" -d '{"batch_id":"BATCH_ID_FROM_STEP_3"}'

# 6. CRITICAL: Manually consolidate staging tables
PYTHONPATH=. python3 -c "
from google.cloud import bigquery
from predictions.shared.batch_staging_writer import BatchConsolidator
client = bigquery.Client(project='nba-props-platform')
consolidator = BatchConsolidator(client, 'nba-props-platform')
batch_id = 'BATCH_ID_FROM_STEP_3'
tables = consolidator._find_staging_tables(batch_id)
print(f'Found {len(tables)} staging tables')
if tables:
    result = consolidator.consolidate_batch(batch_id=batch_id, game_date='YYYY-MM-DD', cleanup=True)
    print(f'Consolidated: {result.rows_affected} rows, success={result.success}')
"

# 7. Verify results
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT prediction_run_mode, is_active, COUNT(*) as cnt,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders
FROM nba_predictions.player_prop_predictions
WHERE system_id='catboost_v9' AND game_date='YYYY-MM-DD'
GROUP BY 1,2 ORDER BY 1,2"
```

---

## Key Files Modified in Session 174

| File | Change |
|------|--------|
| `predictions/coordinator/signal_calculator.py:125` | Added `is_active = TRUE` filter |
| `predictions/worker/worker.py:850-858` | Completion reporting for permanent skips |
| `predictions/worker/worker.py:868-873` | Completion reporting for stale messages |

---

## Architecture Reference (Sessions 170-174)

| File | What It Does |
|------|-------------|
| `predictions/coordinator/coordinator.py` | Orchestrates batches, publishes to Pub/Sub, consolidation |
| `predictions/coordinator/quality_alerts.py` | Slack alerts for #nba-alerts |
| `predictions/coordinator/signal_calculator.py` | Daily GREEN/YELLOW/RED signals |
| `predictions/coordinator/player_loader.py` | Loads player data + betting lines |
| `predictions/worker/worker.py` | Individual player predictions via Pub/Sub push |
| `predictions/shared/batch_staging_writer.py` | Staging writes + MERGE consolidation |
| `shared/config/orchestration_config.py` | `use_multiple_lines_default = False` |
