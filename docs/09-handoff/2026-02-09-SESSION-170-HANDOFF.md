# Session 170 Handoff — Post-Vegas-Fix Hardening + Multi-Line Bug Discovery

**Date:** 2026-02-09
**Duration:** Full session
**Commits:** 6 (cd29878b → 1a903d38)

## Executive Summary

Session 170 implemented the planned hardening from Session 169's Vegas line fix, then discovered and fixed a **critical multi-line dedup bug** that was adding +2.0 systematic UNDER bias to all FIRST-run predictions. This bug explains why active predictions showed 89% UNDER recommendations despite the model being unchanged.

## What Was Done

### Planned Hardening (5 changes from Session 170 plan)

| Step | Change | Commit | Risk |
|------|--------|--------|------|
| 1 | **PVL bias monitoring alert** — alerts when avg(predicted - line) > ±2.0 after consolidation | `cd29878b` | LOW |
| 2 | **Vegas source tracking** — logs which code path provided Vegas feature (recovery_median/coordinator_actual/feature_store/none) in features_snapshot | `cd29878b` | LOW |
| 3 | **Fresh actual_prop_line** — coordinator now uses `line_info['base_line']` from fresh odds query instead of stale Phase 3 `current_points_line` | `fc1c6aaf` | MED-LOW |
| 4 | **model_version filter** — self-healing subquery in subset queries prevents stale model predictions leaking | `100ca7e6` | MED |
| 5 | **avg_pvl in daily signals** — tracks prediction bias historically in `daily_prediction_signals` table + Slack alerts | `a316df97` | MED-HIGH |

### Critical Discovery: Multi-Line Dedup Bug

**Commit:** `1a903d38`

The system generates 5 predictions per player at base_line ±2.0 when `use_multiple_lines=True` (the default for FIRST runs). The dedup logic (`_deactivate_older_predictions` in `batch_staging_writer.py:583`) keeps the prediction with the latest `created_at`. Since predictions are inserted in order (base-2, base-1, base, base+1, base+2), **base+2 always wins**.

**Evidence (Feb 9 FIRST run):**
- 32/32 multi-line players: active prediction = max line (base+2)
- Average active_vs_median offset: exactly +2.0
- Active edge: -4.86 (vs true base edge of -2.86)
- Result: 50 UNDER, 3 OVER, 3 PASS (89% UNDER)

**Fix:** Set `use_multiple_lines_default = False` in orchestration config. BACKFILL runs already used single-line and had healthy avg_pvl (-0.03 to -0.24).

### Infrastructure Changes

- **ALTER TABLE** applied: `daily_prediction_signals.avg_pvl FLOAT64`
- **Backfills triggered:** Feb 4 (complete, 100 preds, avg_pvl -0.24), Feb 8 and Feb 9 (in progress at session end)

## Files Modified (8 files, ~200 lines)

| File | Changes |
|------|---------|
| `predictions/coordinator/quality_alerts.py` | Added `send_pvl_bias_alert()` function |
| `predictions/coordinator/coordinator.py` | Added PVL bias check after consolidation (both code paths) |
| `predictions/worker/worker.py` | Added `vegas_source` tracking at each Vegas code path + features_snapshot |
| `predictions/coordinator/player_loader.py` | Use `line_info['base_line']` for `actual_prop_line` when ACTUAL_PROP |
| `shared/notifications/subset_picks_notifier.py` | Added model_version filter to 2 queries |
| `data_processors/publishing/subset_materializer.py` | Added model_version filter to prediction query |
| `predictions/coordinator/signal_calculator.py` | Added avg_pvl to INSERT, summary query, logging, and Slack data |
| `shared/utils/slack_channels.py` | Added avg_pvl to signal Slack alert message |
| `shared/config/orchestration_config.py` | `use_multiple_lines_default = False` |

## Current State (End of Session)

### Deployments
- All 6 commits pushed to main
- Cloud Build triggered for all 10 services
- prediction-coordinator: **deployed** (commit 1a903d38)
- prediction-worker: **deploying** (was in Step 2: Cloud Run deploy at session end)

### Backfill Status
| Date | Status | avg_pvl | Notes |
|------|--------|---------|-------|
| Feb 4 | **Complete** | -0.24 | 100 active predictions |
| Feb 5 | Complete (earlier) | -0.11 | 104 active predictions |
| Feb 6 | Complete (earlier) | -0.15 | 73 active predictions |
| Feb 7 | Complete (earlier) | -0.03 | 137 active predictions |
| Feb 8 | **In progress** | TBD | Background agent triggering after deploy |
| Feb 9 | **In progress** | TBD | Background agent triggering after Feb 8 |

### Grading Status
| Date | Graded? | Notes |
|------|---------|-------|
| Feb 4 | 16 rows (old model) | Needs re-grading with new backfill predictions |
| Feb 5-7 | Yes | Graded with BACKFILL predictions |
| Feb 8 | **Not graded** | Games are final, needs grading after backfill |
| Feb 9 | N/A | Games haven't started yet |

### Hit Rate Performance (Edge 3+)
| Week | Edge 3+ HR | Sample | avg_pvl |
|------|-----------|--------|---------|
| Jan 11 | **71.7%** | 127 | +0.95 |
| Jan 18 | **67.3%** | 110 | -0.05 |
| Jan 25 | **57.1%** | 98 | -0.20 |
| Feb 1 | **48.1%** | 81 | -0.01 |

Declining trend — partially explained by multi-line bug on FIRST runs, model version transitions, and small Feb sample sizes. BACKFILL predictions (single-line, healthy avg_pvl) should show better performance.

## Root Causes Identified (3 layers of UNDER bias)

### Layer 1: Multi-Line Dedup Bug (Session 170 discovery)
- **Impact:** +2.0 systematic UNDER bias on FIRST-run active predictions
- **Root cause:** `_deactivate_older_predictions` keeps latest `created_at` = highest line
- **Fix:** Disabled multi-line (`use_multiple_lines_default = False`)
- **Status:** Fixed and deployed

### Layer 2: Vegas Line NULL from Coordinator (Session 169)
- **Impact:** Model runs without feature #25 (most important), predicts conservatively low
- **Root cause:** `actual_prop_line` from Phase 3's `current_points_line` was NULL pre-game
- **Fix:** Recovery median path (Session 169) + fresh base_line (Session 170)
- **Status:** Fixed and deployed

### Layer 3: Feature Store Vegas Overwrite (Session 168)
- **Impact:** Good feature store Vegas data overwritten with NULL from coordinator
- **Root cause:** Worker code unconditionally set Vegas features from coordinator data
- **Fix:** Preserve feature store values when coordinator has no line (Session 168)
- **Status:** Fixed and deployed

## Investigation Findings

### BettingPros vs OddsAPI Lines
- **Priority order is correct:** OddsAPI → BettingPros per sportsbook, then fallback
- **Raw line difference:** +0.09 average (BettingPros slightly higher) — not significant
- **BUT:** On Feb 9, 30 players got BettingPros despite OddsAPI data existing in BigQuery
- **Possible cause:** Query timeout (30s per player, sequential), or timing mismatch
- **Action needed:** Investigate why OddsAPI queries fail for players with available data

### Model Identity
- **Production model:** `catboost_v9_33features_20260201_011018.cbm` (SHA: 5b3a187b)
- **Deployed since:** Feb 8 (restored after Feb 2 retrain disaster)
- **Model version string:** `v9_20260201_011018`
- **Same model as January** — the hit rate decline is NOT from a model change
- **Model file confirmed unchanged** via SHA256 hash

### Feature Store
- **Vegas coverage:** 90-100% for Feb 4-9 in `ml_feature_store_v2`
- **The feature store has good data** — the problem was the coordinator→worker handoff losing it

---

## NEXT SESSION PROMPT

Copy this into the next session:

---

### Session 171 — Verify Vegas Fix + Investigate Hit Rate Decline

**Context:** Session 170 found and fixed 3 layers of UNDER bias:
1. Multi-line dedup bug (+2.0 UNDER bias) — fixed by disabling multi-line
2. Vegas line NULL from coordinator — fixed with recovery_median + fresh base_line
3. Feature store Vegas overwrite — fixed in Session 168

**Read:** `docs/09-handoff/2026-02-09-SESSION-170-HANDOFF.md`

### P0: Verify Fixes Are Working

```sql
-- 1. Check Feb 9 BACKFILL predictions (should have healthy avg_pvl)
SELECT game_date, prediction_run_mode, COUNT(*) as preds,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders,
  COUNTIF(recommendation = 'PASS') as passes
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date = '2026-02-09' AND is_active = TRUE
GROUP BY 1, 2;

-- 2. Check Vegas source distribution (should show coordinator_actual or recovery_median, NOT null)
SELECT JSON_EXTRACT_SCALAR(features_snapshot, '$.vegas_source') as source,
  COUNT(*) as cnt,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-09' AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1;

-- 3. Check PVL bias alert fired correctly
-- Look in #nba-alerts Slack channel for PVL_BIAS_DETECTED messages

-- 4. Check avg_pvl in daily signals
SELECT game_date, system_id, avg_pvl, daily_signal, pct_over
FROM nba_predictions.daily_prediction_signals
WHERE game_date >= '2026-02-09';

-- 5. Verify multi-line is disabled (should be 1.0 rows per player)
SELECT prediction_run_mode,
  ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT player_lookup), 1) as rows_per_player
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-10' AND system_id = 'catboost_v9'
GROUP BY 1;
```

### P1: Complete Backfills if Needed

Check if Feb 8 and Feb 9 backfills completed:
```sql
SELECT game_date, prediction_run_mode, is_active, COUNT(*) as cnt,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date IN ('2026-02-08', '2026-02-09')
GROUP BY 1, 2, 3
ORDER BY 1, 2;
```

If missing, trigger:
```
POST /start {"game_date":"2026-02-08","prediction_run_mode":"BACKFILL"}
POST /start {"game_date":"2026-02-09","prediction_run_mode":"BACKFILL"}
```

### P2: Grade Feb 8 and Re-grade Feb 4

Feb 8 games are final but ungraded. Feb 4 was backfilled with new predictions. Check:
```sql
SELECT game_date, COUNT(*) FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND game_date IN ('2026-02-04', '2026-02-08')
GROUP BY 1;
```

### P3: Investigate Hit Rate Decline

Edge 3+ hit rate dropped from 71.7% (Jan 11 week) to 48.1% (Feb 1 week). Now that multi-line bug is fixed and backfills are clean, re-evaluate:

```sql
-- Re-check hit rate using only BACKFILL (single-line) predictions
SELECT
  DATE_TRUNC(pa.game_date, WEEK) as week,
  COUNT(*) as graded,
  COUNTIF(pa.prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(pa.predicted_points - pa.line_value), 2) as avg_pvl
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.player_prop_predictions p
  ON pa.player_lookup = p.player_lookup AND pa.game_date = p.game_date AND pa.system_id = p.system_id
WHERE pa.system_id = 'catboost_v9'
  AND pa.game_date >= '2026-01-12'
  AND pa.actual_points IS NOT NULL
  AND pa.line_value IS NOT NULL
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND p.is_active = TRUE
  AND p.prediction_run_mode = 'BACKFILL'
GROUP BY 1
ORDER BY 1;
```

If hit rate is still declining with clean backfill predictions, possible causes:
1. **Market sharpening** — Vegas lines getting more accurate over time
2. **Feature staleness** — model trained on Nov-Jan data, Feb patterns may differ
3. **Player rotation changes** — All-Star break, trade deadline shifts
4. **Time for retrain** — consider `/model-experiment` with extended training window

### P4: Investigate OddsAPI Query Failures

On Feb 9, 30 players got BettingPros lines despite OddsAPI having DraftKings data. Investigate:
- Add logging to `_query_actual_betting_line` to distinguish "no data" vs "query timeout"
- Check if 30-second per-player BQ query timeout is too short
- Consider batching line queries instead of per-player sequential

### P5: Fix Multi-Line Dedup (Long-term)

The multi-line feature is disabled, not fixed. If we want to re-enable it:
- `_deactivate_older_predictions` in `predictions/shared/batch_staging_writer.py:583`
- Current: `ORDER BY created_at DESC` → always picks last-inserted (highest line)
- Fix option 1: `PARTITION BY game_id, player_lookup, system_id, current_points_line` → keep newest per line
- Fix option 2: Select the prediction where `current_points_line` matches `base_line` from line_source_info
- Fix option 3: Keep disabled — multi-line provides marginal value vs complexity

### P6: Monitor Feb 10 FIRST Run

Feb 10 will be the first FIRST-run with ALL fixes deployed (multi-line disabled + Vegas recovery + fresh base_line). This is the true test.

```sql
-- After Feb 10 FIRST run (~6 AM ET):
SELECT prediction_run_mode, COUNT(*) as preds,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders,
  JSON_EXTRACT_SCALAR(features_snapshot, '$.vegas_source') as vegas_source
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-10' AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1, 6;
```

**Target:** avg_pvl within ±1.5, OVER/UNDER balance >25% each direction, vegas_source NOT null.

---
