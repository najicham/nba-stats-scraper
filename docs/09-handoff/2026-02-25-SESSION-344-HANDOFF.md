# Session 344 Handoff — Model Health Crisis Deep-Dive, Stale Export Diagnosis, Prevention

**Date:** 2026-02-25
**Focus:** Daily validation, stale export root cause + fix verification, comprehensive model degradation investigation, prevention mechanisms.

---

## Executive Summary

Ran `/validate-daily` and found:
- **Stale best-bets exports** — `latest.json` stale 4 days, `record.json`/`history.json` stale 3 days (fix was committed in Session 343 but unverified — now verified correct)
- **ALL models BLOCKED or DEGRADING** — comprehensive BQ investigation reveals 5 root causes
- **Q55 shadow model NOT generating predictions** — registered in Session 343 but not yet active in pipeline
- **Best bets edge 5+ picks catastrophically bad** — 19-36% HR in recent days

Session 344 verified the export fixes, fixed a bug in the freshness monitor, and produced a full data-backed diagnosis of the model health crisis with prioritized recommendations.

---

## Issue 1: Stale Phase 6 Exports

### What Happened

| File | Last Updated | Stale Since | Root Cause |
|------|-------------|-------------|------------|
| `best-bets/latest.json` | Feb 21 | 4 days | Legacy `BestBetsExporter` was decommissioned; nothing replaced it |
| `best-bets/record.json` | Feb 22 | 3 days | `BestBetsRecordExporter` runs in daily export but NOT in post-grading re-export |
| `best-bets/history.json` | Feb 22 | 3 days | Same as record.json |
| `signal-best-bets/*.json` | Today | FRESH | Working correctly |
| `best-bets/all.json` | Today | FRESH | Working correctly |
| `best-bets/today.json` | Today | FRESH | Working correctly |

### Fixes Applied (Session 343, verified Session 344)

**Fix 1:** `data_processors/publishing/signal_best_bets_exporter.py` — Added backward-compat write to `best-bets/latest.json` alongside `signal-best-bets/latest.json`. Non-fatal try/except wrapper.

**Fix 2:** `orchestration/cloud_functions/post_grading_export/main.py` — Added Step 8: `BestBetsRecordExporter` re-export of `record.json` + `history.json` post-grading. Version bumped to 1.5.

### Prevention: Export Freshness Monitor

**New file:** `bin/monitoring/check_export_freshness.py`

Monitors 10 GCS export files with configurable max staleness thresholds (12-36h). Detects STALE, MISSING, or FRESH status with severity levels (CRITICAL/HIGH/MEDIUM).

```bash
python bin/monitoring/check_export_freshness.py          # Human-readable
python bin/monitoring/check_export_freshness.py --json   # Machine-readable
python bin/monitoring/check_export_freshness.py --max-age-hours 6  # Override threshold
```

**Bug fix (Session 344):** Fixed `blob.reload()` being called before `blob.exists()` check — would throw exception on missing files. Now correctly calls `exists()` first, then `reload()` only if blob exists.

### How This Could Have Been Prevented

1. **No export freshness monitoring existed.** The daily validation checked a single news file, not the full export suite. The new freshness monitor closes this gap.
2. **No integration test for export endpoints.** When the legacy `BestBetsExporter` was decommissioned, there was no test asserting `best-bets/latest.json` was still being written.
3. **Recommendation:** Add the freshness monitor to `/validate-daily` flow and consider a Cloud Function that runs it automatically (could alert to Slack on STALE/MISSING).

---

## Issue 2: Model Health Crisis — All Models BLOCKED or DEGRADING

### Current State (Feb 24-25 data)

| Model | State | 7d HR | 14d HR | Days Since Training | N (7d) |
|-------|-------|-------|--------|---------------------|--------|
| `catboost_v12` (champion) | **BLOCKED** | 50.0% | 47.6% | 9 | 69-70 |
| `catboost_v12_noveg_train1102_0205` | WATCH/DEGRADING | 52.8-55.6% | — | 9 | 36 |
| `catboost_v9_low_vegas_train0106_0205` | **DEGRADING** | 53.7% | — | 19 | 52-54 |
| `catboost_v9` | **BLOCKED** | 42-45% | 43-44% | 19 | 19-20 |
| `catboost_v12_noveg_q43_train1102_0125` | **BLOCKED** | 43-46% | — | 9 | 74-76 |
| `catboost_v12_noveg_q45_train1102_0125` | **BLOCKED** | 46-48% | — | 30 | 65-67 |
| `catboost_v12_q43_train1225_0205` | **BLOCKED** | 14.3% | — | 9 | 28 |
| `catboost_v12_vegas_q43_train0104_0215` | **BLOCKED** | 16.7-25.0% | — | 9 | 6-8 |

**Breakeven threshold: 52.4%.** Only `catboost_v12_noveg_train1102_0205` is marginally above.

### Root Cause 1: Structural UNDER Bias (PRIMARY)

The system is predicting UNDER **66-78% of the time**. This is not noise — it's structural.

| Date | Actionable Predictions | OVER | UNDER | UNDER % |
|------|----------------------|------|-------|---------|
| Feb 25 | 377 | 89 | 288 | **76.4%** |
| Feb 24 | 717 | 245 | 472 | **65.8%** |
| Feb 23 | 186 | 41 | 145 | **78.0%** |
| Feb 22 | 1,018 | 295 | 723 | **71.0%** |
| Feb 21 | 164 | 51 | 113 | **68.9%** |
| Feb 20 | 342 | 96 | 246 | **71.9%** |
| Feb 19 | 394 | 108 | 286 | **72.6%** |

**Likely cause:** Models anchored to historical scoring averages that lag current trends. Vegas lines may have systematically increased (league-wide scoring trend mid-season) and models haven't recalibrated.

### Root Cause 2: Quantile q43/q45 Models Are Structurally Broken

By design, quantile regression at Q43/Q45 predicts the 43rd/45th percentile of scoring. This **mathematically guarantees** predictions below most prop lines:

| Model | Total | OVER | UNDER | UNDER % |
|-------|-------|------|-------|---------|
| `v9_q43_train1102_0125` | 402 | 5 | 397 | **98.8%** |
| `v9_q45_train1102_0125` | 363 | 2 | 361 | **99.4%** |
| `v12_noveg_q43_train1102_0125` | 79 | 2 | 77 | **97.5%** |
| `v12_noveg_q45_train1102_0125` | 75 | 5 | 70 | **93.3%** |
| `v12_q43_train1225_0205` | 12 | 0 | 12 | **100.0%** |
| `v12_noveg_q43_train0104_0215` | 10 | 0 | 10 | **100.0%** |

These models flood the prediction pool with near-100% UNDER picks that artificially inflate edge (predicting far below prop lines = high edge but wrong direction).

### Root Cause 3: Training Staleness

| Staleness Group | Models | Days Since Training |
|-----------------|--------|---------------------|
| **Critically stale (30d)** | `v9_q43_train1102_0125`, `v9_q45_train1102_0125`, `v12_noveg_q45_train1102_0125` | 30 |
| **Stale (19d)** | `catboost_v9`, `v9_low_vegas_train0106_0205` | 19 |
| **Moderate (9d)** | All v12 variants, most recent retrains | 9 |

The 7-day retrain cadence has been violated. However, even the freshest models (9 days) are BLOCKED — staleness alone does not explain the crisis.

### Root Cause 4: Vegas Feature Anchoring

The `catboost_v12_noveg` variants (no Vegas features) consistently outperform the Vegas-included models:
- `v12_noveg_train1102_0205`: 55.6% HR (WATCH)
- `v12` production: 50.0% HR (BLOCKED)

This suggests Vegas features introduce harmful correlation — the model learns to "regress toward" historical averages rather than making independent predictions.

### Root Cause 5: Q55 Shadow Model Not Active

The Q55 shadow model (`catboost_v12_noveg_q55_train1225_0209`) was registered in Session 343 with `enabled=true, status='shadow'`, but **zero predictions found** in either `prediction_accuracy` or `player_prop_predictions` tables.

This is the model designed to counterbalance UNDER bias (80% OVER predictions in backtest, 60% edge 3+ HR, best MAE of 5.024, best calibration -0.24 bias). It needs to be actively generating predictions before it can help.

**Investigation needed:** Check if the prediction worker is picking up shadow models, or if `status='shadow'` is being filtered out by the coordinator/worker.

### Best Bets Performance is Catastrophic

Edge 5+ actionable picks (the best bets tier) are performing terribly:

| Date | Picks | HR | OVER | UNDER |
|------|-------|----|------|-------|
| Feb 24 | 25 | **36.0%** | 9 | 16 |
| Feb 22 | 42 | **19.0%** | 6 | 36 |
| Feb 21 | 4 | 50.0% | 3 | 1 |
| Feb 19 | 10 | 40.0% | 5 | 5 |
| Feb 11 | 36 | **33.3%** | 16 | 20 |

The high-edge UNDER predictions from q43/q45 models are making it through filters and losing badly.

### OVER vs UNDER Hit Rate by Edge Tier

| Edge Bucket | Direction | Picks | HR |
|-------------|-----------|-------|----|
| 3-5 | OVER | 210 | 44.3% |
| 3-5 | UNDER | 594 | **53.5%** |
| 5+ | OVER | 54 | 48.1% |
| 5+ | UNDER | 175 | 49.7% |
| Under 3 | OVER | 778 | 48.2% |
| Under 3 | UNDER | 1,858 | **53.9%** |

UNDER is winning at edge 3-5 (53.5%) but **UNDER at edge 5+ is near-random** (49.7%). The q43/q45 models generate high-edge UNDER picks that don't actually win.

### Grading Coverage is NOT a Bug

| Date | Total | Graded | Ungraded | Grade % |
|------|-------|--------|----------|---------|
| Feb 24 | 3,129 | 681 | 2,448 | 21.8% |
| Feb 23 | 839 | 176 | 663 | 21.0% |
| Feb 22 | 3,152 | 873 | 2,279 | 27.7% |

The "ungraded" predictions are HOLD (1,517) and PASS (895) recommendations — intentionally not graded because they aren't actionable. All OVER/UNDER predictions are properly graded. Prop line availability is 99-100%.

---

## Recommended Actions for Next Session

### PRIORITY 1: Get Q55 Shadow Model Generating Predictions

The Q55 model is the most promising solution to the UNDER bias crisis (80% OVER in backtest) but it's sitting idle.

**Steps:**
1. Check prediction worker logs for `q55` — is it loading the model?
2. Check if `status='shadow'` is filtered out by the coordinator or worker model loading
3. Verify GCS model path is accessible: `gs://nba-props-platform-models/catboost/v12/monthly/catboost_v9_50f_noveg_train20251225-20260209_20260225_100720.cbm`
4. If needed, change status to `'active'` in model_registry to get it generating predictions

```sql
-- Check if Q55 has any predictions at all
SELECT system_id, COUNT(*) as predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2026-02-25'
  AND system_id LIKE '%q55%'
GROUP BY 1;

-- Check model_registry entry
SELECT model_id, enabled, status, model_path
FROM `nba-props-platform.nba_predictions.model_registry`
WHERE model_id LIKE '%q55%';
```

### PRIORITY 2: Emergency Retrain Best Models

Retrain the top 2 performers with data through Feb 23:
- **`v12_noveg`** — Best HR among fresh models (55.6%), no Vegas feature anchoring
- **`v9_low_vegas`** — Best sample size + decent HR (53.7%), UNDER HR 59.5%

```bash
# Use /model-experiment to retrain with fresh data
/model-experiment v12_noveg --train-end 2026-02-23
/model-experiment v9_low_vegas --train-end 2026-02-23
```

### PRIORITY 3: Isolate q43/q45 Quantile Models from Best Bets

These models generate near-100% UNDER at artificially high edge, polluting best bets selection. Options:
1. **Disable q43/q45 in model_registry** — simplest, removes them entirely
2. **Add direction-affinity block** — block q43/q45 UNDER at edge 5+ (they're already partially blocked by Session 343's affinity blocking, but verify)
3. **Cap quantile model edge contribution** — limit how much their predictions influence cross-model scoring

### PRIORITY 4: Investigate Vegas Line Drift

Check if Vegas lines have systematically increased in recent weeks vs. the training period:

```sql
-- Compare average prop lines by week
SELECT DATE_TRUNC(game_date, WEEK) as week,
  ROUND(AVG(line_value), 1) as avg_line,
  COUNT(*) as n
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-12-01'
  AND line_value IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

If lines are trending up, models trained on older data will systematically predict below the new lines.

### PRIORITY 5: Decommission v12_vegas_q43

20% HR at edge 5+ — catastrophic. Should be disabled immediately:

```sql
UPDATE `nba-props-platform.nba_predictions.model_registry`
SET enabled = false, status = 'disabled',
    notes = CONCAT(notes, ' | Session 344: decommissioned, 20% HR edge 5+')
WHERE model_id = 'catboost_v12_vegas_q43_train0104_0215';
```

### PRIORITY 6: Deploy Export Freshness Monitor to Cloud Function

The freshness monitor at `bin/monitoring/check_export_freshness.py` currently runs manually. Consider:
1. Adding it to the `daily-health-check` Cloud Function
2. Or creating a standalone Cloud Scheduler job (every 6h)
3. Alert to `#nba-alerts` Slack channel on STALE/MISSING

---

## Files Modified This Session

| File | Change | Status |
|------|--------|--------|
| `bin/monitoring/check_export_freshness.py` | Fixed `blob.reload()` bug (called before `exists()`) | Uncommitted |

**Note:** The export fixes (`signal_best_bets_exporter.py`, `post_grading_export/main.py`) and freshness monitor creation were committed in Session 343 (`733005a6`). This session verified them and fixed a minor bug.

---

## Key Diagnostic Queries

### Check model health
```sql
SELECT model_id, days_since_training, state,
  ROUND(rolling_hr_7d / 100.0, 1) as hr_7d,
  rolling_n_7d
FROM nba_predictions.model_performance_daily
WHERE game_date = CURRENT_DATE() - 1
  AND rolling_n_7d >= 5
ORDER BY days_since_training DESC;
```

### Check UNDER bias trend
```sql
SELECT game_date,
  COUNTIF(predicted_direction = 'OVER') as overs,
  COUNTIF(predicted_direction = 'UNDER') as unders,
  ROUND(COUNTIF(predicted_direction = 'UNDER') * 100.0 / COUNT(*), 1) as under_pct
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY 1 ORDER BY 1 DESC;
```

### Check Q55 activation
```sql
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-25'
  AND system_id LIKE '%q55%'
GROUP BY 1;
```

### Check export freshness
```bash
python bin/monitoring/check_export_freshness.py
```

---

## Quick Start for Next Session

```bash
# 1. Check current state
/validate-daily

# 2. Check if Q55 is generating predictions now
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT system_id, COUNT(*) FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` WHERE game_date = CURRENT_DATE() AND system_id LIKE '%q55%' GROUP BY 1"

# 3. If Q55 not active, investigate prediction worker model loading
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload:"q55"' \
  --project=nba-props-platform --limit=20 --format='table(timestamp, textPayload)'

# 4. Check export freshness (verify Session 343 fixes working)
python bin/monitoring/check_export_freshness.py

# 5. Emergency retrain if Q55 still not helping
/model-experiment v12_noveg --train-end 2026-02-23

# 6. Decommission v12_vegas_q43 (Priority 5)
```

---

## Cross-References

- **Session 343 handoff:** `docs/09-handoff/2026-02-25-SESSION-343-HANDOFF.md` — Shadow model registration, evaluation plan, zombie decommission
- **Session 342 handoff:** `docs/09-handoff/2026-02-25-SESSION-342-HANDOFF.md` — Direction affinity blocking, model state diagnosis
- **Evaluation plan:** `docs/08-projects/current/model-system-evaluation-session-343/00-EVALUATION-PLAN.md` — 7-part evaluation framework
- **CLAUDE.md model section:** Current model registry state, dead ends, governance gates
