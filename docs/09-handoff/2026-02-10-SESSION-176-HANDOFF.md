# Session 176 Handoff

**Date:** 2026-02-10
**Previous:** Session 175

---

## What Was Done

### 1. Regenerated Feb 4-8 Predictions (P2)

Regenerated all 5 dates using `/regenerate-with-supersede` to fix misaligned recommendations from pre-Session 170 multi-line bug. Results:

| Date | Active Predictions | Direction Mismatches | avg_pvl | OVER% |
|------|-------------------|---------------------|---------|-------|
| Feb 4 | 112 | 0 | -0.30 | 25.5% |
| Feb 5 | 125 | 0 | -0.06 | 26.6% |
| Feb 6 | 93 | 0 | -0.05 | 24.7% |
| Feb 7 | 165 | 0 | -0.02 | 27.5% |
| Feb 8 | 64 | 0 | +0.01 | 37.5% |

All active predictions verified clean. Old predictions properly superseded with `superseded=TRUE`.

### 2. Triggered Re-Grading for Feb 4-8

Published grading triggers via Pub/Sub for all 5 dates. Results after re-grading:

| Week | Graded (edge 3+) | Hit Rate | OVER HR | UNDER HR |
|------|-----------------|----------|---------|----------|
| Jan 12 | 139 | **71.2%** | 76.8% | 59.1% |
| Jan 19 | 112 | **67.0%** | 64.7% | 68.9% |
| Jan 26 | 100 | **58.0%** | 63.4% | 54.2% |
| Feb 2 | 91 | **47.3%** | 46.8% | 47.7% |

**Key finding:** Model decay confirmed at 47.3% for Feb 2 week (below 55% profitability threshold). OVER/UNDER now balanced (direction fix worked) but both directions underperforming. Model retrain is needed.

### 3. Made `/regenerate-with-supersede` Async

The endpoint now returns `202 Accepted` immediately and processes in a background thread. Previously it blocked for 2-5 minutes per date, causing client timeouts.

- Returns `batch_id` for tracking
- Poll `/status` for progress
- Background thread logs success/failure

### 4. Added Post-Batch Direction Alignment Check

New `RECOMMENDATION_DIRECTION_MISMATCH` quality alert fires after every batch consolidation. Queries active predictions for `pred > line BUT rec = UNDER` (or vice versa). Sends Slack alert to `#nba-alerts` if any found. Added to both normal and stalled-batch consolidation paths.

### 5. Bumped Gunicorn Timeout

Increased from 300s to 540s to match Cloud Run timeout. Prevents gunicorn from killing long-running requests before Cloud Run does.

### 6. Fixed `prediction_regeneration_audit` Silent Failure

The audit table existed but had zero rows. Root cause: `metadata` field sent as `json.dumps()` string but BQ column is JSON type (expects dict). Also missing `processing_time_seconds` and `created_at` fields. Fixed to send dict directly with all schema fields.

### 7. Pushed Prior Session Changes

Pushed uncommitted Session 175 commit (`e79219ac` — model diagnosis script + directional balance governance gate) and prior `quick_retrain.py` changes (recency weighting, walk-forward validation, hyperparameter tuning).

---

## Backfill Validation

Investigated all potential backfill quality concerns:

| Concern | Status | Root Cause |
|---------|--------|------------|
| `superseded_count: 0` from API | Non-issue | Superseding worked (verified in BQ). Counter tracks explicit supersede step, not consolidation. |
| 191 ungraded predictions | Working as designed | All are `recommendation = PASS` (edge too small). Cannot be graded correct/wrong. |
| 77 players missing from accuracy | Expected | `NO_LINE` players — grading requires valid line source. |
| Different prediction counts vs original | Expected | Feature store coverage improved since original runs. |

---

## Files Modified

| File | Change |
|------|--------|
| `predictions/coordinator/coordinator.py` | Async regen endpoint, direction alignment check, audit fix |
| `predictions/coordinator/gunicorn_config.py` | Timeout 300s → 540s |
| `predictions/coordinator/quality_alerts.py` | `send_direction_mismatch_alert()` function |
| `ml/experiments/quick_retrain.py` | Recency weighting, walk-forward, hyperparameter tuning |

---

## Commits

| SHA | Description |
|-----|-------------|
| `e79219ac` | feat: Model diagnosis script + directional balance governance gate (Session 175 — pushed) |
| `63608a5e` | feat: Async regeneration endpoint, direction alignment check, gunicorn timeout |
| `d55fcb56` | feat: Recency weighting, walk-forward validation, hyperparameter tuning |
| `b9bae63c` | docs: Retrain infrastructure docs, model strategy roadmap |
| `d0060dd3` | fix: prediction_regeneration_audit silent insert failure |

---

## Priority Work for Next Session

### P0: Verify Feb 10 FIRST-run Predictions
First run with ALL Session 175+176 fixes deployed (async regen, direction check, audit logging, OddsAPI diagnostics). Check:
- avg_pvl within +/-1.5
- OVER% > 25%
- Zero `RECOMMENDATION_DIRECTION_MISMATCH` in logs
- `ODDS_API_COVERAGE` and `NO_LINE_DIAGNOSTIC` messages appear (new Session 175 logging)

### P1: Grade Feb 9 Games
10 games played tonight. Trigger grading once all are Final (status=3).

### P2: Model Retrain with Extended Data
Model decay confirmed: 71.2% → 47.3% over 4 weeks. Train through Jan 31, eval on Feb 1-8 (clean graded data now available). Use:
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_FEB_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end 2026-01-31 \
    --walkforward
```
Follow full governance gates before any promotion.

### P3: Check OddsAPI Diagnostic Logs
After Feb 10 prediction run, check Cloud Run logs for `ODDS_API_COVERAGE` and `NO_LINE_DIAGNOSTIC` messages to diagnose line coverage gaps.

### P4 (Low): Verify Regeneration Audit
After next regeneration, confirm `prediction_regeneration_audit` table has data (was empty, fix deployed this session).

---

## Key Queries

```sql
-- Check Feb 10 predictions + direction alignment
SELECT game_date, prediction_run_mode,
  COUNT(*) as cnt,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  ROUND(COUNTIF(recommendation = 'OVER') * 100.0 / COUNT(*), 1) as over_pct,
  COUNTIF(predicted_points > current_points_line AND recommendation = 'UNDER') as direction_mismatches
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date = '2026-02-10'
  AND is_active = TRUE AND current_points_line IS NOT NULL
GROUP BY 1, 2;

-- Verify regeneration audit is now being written
SELECT * FROM nba_predictions.prediction_regeneration_audit
ORDER BY regeneration_timestamp DESC LIMIT 5;

-- Weekly edge 3+ hit rate (key metric)
SELECT DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
  COUNT(*) as graded,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND game_date >= '2026-01-12'
  AND prediction_correct IS NOT NULL AND ABS(predicted_points - line_value) >= 3
GROUP BY 1 ORDER BY 1;
```
