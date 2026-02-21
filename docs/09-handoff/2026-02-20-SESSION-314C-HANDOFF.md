# Session 314C Handoff — What-If Retrain Tool + Feb Collapse Root Cause

**Date:** 2026-02-20
**Focus:** Built what-if retrain simulation tool, loaded actual production models, root-caused the Feb 2-9 collapse
**Status:** Tool built and tested. Root cause identified. Directional cap recommendation ready for next session.
**Prior sessions:** 314 (investigation), 314B (consolidation + backfill plan)

---

## What Was Done

### 1. What-If Retrain Tool (`bin/what_if_retrain.py`)

Built a counterfactual simulation tool with two modes:

**Mode 1: Load actual saved model files from GCS**
```bash
# Run the ACTUAL stale production model against Feb 1-14
PYTHONPATH=. python bin/what_if_retrain.py \
    --model-path gs://nba-props-platform-models/catboost/v9/catboost_v9_33f_train20251102-20260108_20260208_170526.cbm \
    --eval-start 2026-02-01 --eval-end 2026-02-14

# Compare stale vs fresh — actual production .cbm files
PYTHONPATH=. python bin/what_if_retrain.py \
    --model-path gs://nba-props-platform-models/catboost/v9/catboost_v9_33f_train20251102-20260108_20260208_170526.cbm \
    --eval-start 2026-02-01 --eval-end 2026-02-14 \
    --compare-with gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20251102-20260131_20260209_212708.cbm
```

**Mode 2: Train a new model from scratch**
```bash
PYTHONPATH=. python bin/what_if_retrain.py \
    --train-end 2026-01-31 --eval-start 2026-02-08 --eval-end 2026-02-14
```

**Features:**
- Loads actual `.cbm` model files from GCS (same predictions as production)
- OR trains a temporary CatBoost V9 in-memory (42-day rolling window)
- Reports hit rates at edge thresholds 0/1/2/3/5
- **OVER/UNDER direction breakdown** at each threshold
- UNDER-specific negative filters (edge 7+ block, bench UNDER, line jump/drop)
- A/B comparison with `--compare-with` (accepts dates OR model paths)
- Low-N warnings (`*` when N < 20)
- NO writes to BigQuery or GCS

### 2. What-If Claude Skill (`.claude/skills/what-if/SKILL.md`)

### 3. Root Cause Analysis: Feb 2-9 Collapse

We investigated the Feb collapse (production edge 3+ HR dropped from 71% to 36%) using the what-if tool with actual production model files and BQ queries.

---

## The Feb 2-9 Collapse: Root Cause

### It wasn't model staleness. It was directional concentration.

**Production weekly results (edge 3+, catboost_v9 champion):**

| Week | N | HR | OVER HR | UNDER HR | % UNDER |
|------|---|-----|---------|----------|---------|
| Jan 12 | 139 | **71.2%** | 76.8% | 59.1% | 32% |
| Jan 19 | 112 | **67.0%** | 64.7% | 68.9% | 54% |
| Jan 26 | 96 | 57.3% | 58.8% | 56.5% | 65% |
| **Feb 2** | **124** | **36.3%** | **46.8%** | **29.9%** | **62%** |
| Feb 9 | 51 | 45.1% | 46.4% | 43.5% | 45% |

### Feb 2 was the catastrophe day

| Date | Edge 3+ OVER | Edge 3+ UNDER | UNDER % | UNDER result |
|------|-------------|---------------|---------|--------------|
| Jan 25 | 9 | 5 | 36% | normal |
| Jan 31 | 3 | 14 | **82%** | warning |
| **Feb 2** | **2** | **31** | **94%** | **4W-27L (12.9%)** |
| Feb 3 | 6 | 12 | 67% | 3W-9L |
| Feb 5 | 7 | 6 | 46% | back to normal |

On Feb 2, **94% of edge 3+ picks were UNDER** (31 of 33). Players like Jaren Jackson Jr (pred 13.8, line 17.5, actual 30), Jordan Miller (pred 8.2, line 12.5, actual 21), and Trey Murphy III (pred 11.1, line 19.5, actual 27) all massively exceeded their lines. This was a league-wide scoring explosion that no model could predict.

### Would retraining have helped?

**Actual production models (from GCS), Feb 1-14:**

| Metric | Stale (train>Jan 8, 238 trees) | Fresh (train>Jan 31, 169 trees) |
|--------|-------------------------------|--------------------------------|
| MAE | 4.91 | 4.91 |
| Edge 1+ HR | **53.4%** (183W-160L, +$700) | 52.8% (133W-119L, +$210) |
| Edge 3+ HR | 68.4% (13W-6L, N=19) | 77.8% (7W-2L, N=9) |
| Edge 3+ OVER | 42.9% (3W-4L) | 50.0% (1W-1L) |
| Edge 3+ UNDER | **83.3%** (10W-2L) | **85.7%** (6W-1L) |

Both models were profitable when run through the what-if tool with today's negative filters. The stale model was actually slightly better at edge 1+ because it generated more volume (343 vs 252 picks). Edge 3+ UNDER was 83-86% for BOTH models.

**Key insight:** The what-if tool applies UNDER-specific negative filters that production didn't have at the time. The what-if tool's UNDER filters would have killed many of the Feb 2 UNDER picks (bench UNDER block, line jump block). The problem in production was **volume** — 31 UNDER picks getting through at edge 3+ on one day.

### Conclusion

**Retraining alone would not have prevented the collapse.** The fresh model's MAE is identical (4.91) and its UNDER predictions are similar. The fix is in the **pick selection pipeline** — specifically, limiting directional concentration.

---

## Recommendation for Next Session: Directional Concentration Cap

### The Problem
The aggregator has no limit on how many picks can be in one direction. On Feb 2, 94% of edge 3+ picks were UNDER. When UNDER collapsed, every pick lost.

### The Fix
Add a **directional concentration cap** as a negative filter in `ml/signals/aggregator.py`. When >60% of qualifying picks are in one direction, randomly drop excess picks from the overrepresented direction to reach 60%.

### Why This Works
- Jan 12-19 (good weeks): UNDER was 32-54% of picks — cap wouldn't trigger
- Jan 31: UNDER was 82% — cap would have trimmed from 14 to ~10
- Feb 2: UNDER was 94% — cap would have trimmed from 31 to ~12, limiting losses from 27L to ~10L
- Estimated savings on Feb 2 alone: ~$1,870 ($110 * 17 avoided losses)

### What Already Exists
- `validate-daily` Phase 0.57 already detects >80% directional concentration — but only as a monitoring **alert**, not a production **filter**
- CLAUDE.md documents this: "Directional concentration (Session 266): flags when >80% of edge 3+ picks are in same direction"
- The alert was created in Session 266 but never promoted to a production blocking filter

### Investigation Plan for Next Session

1. **Read the best bets architecture:** `docs/01-architecture/best-bets-and-subsets.md`
2. **Read the aggregator code:** `ml/signals/aggregator.py` (the `aggregate()` method, lines 104-230)
3. **Backtest the directional cap:**
   ```bash
   # Use the what-if tool to compare model behavior
   PYTHONPATH=. python bin/what_if_retrain.py \
       --model-path gs://nba-props-platform-models/catboost/v9/catboost_v9_33f_train20251102-20260108_20260208_170526.cbm \
       --eval-start 2026-01-15 --eval-end 2026-02-14
   ```
4. **Query directional concentration history:**
   ```sql
   -- Days where >60% of edge 3+ picks were in one direction
   SELECT game_date,
     COUNTIF(recommendation = 'OVER' AND ABS(predicted_points - line_value) >= 3) as over_e3,
     COUNTIF(recommendation = 'UNDER' AND ABS(predicted_points - line_value) >= 3) as under_e3,
     ROUND(100.0 * GREATEST(
       COUNTIF(recommendation = 'OVER' AND ABS(predicted_points - line_value) >= 3),
       COUNTIF(recommendation = 'UNDER' AND ABS(predicted_points - line_value) >= 3)
     ) / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 0) as max_pct
   FROM `nba-props-platform.nba_predictions.prediction_accuracy`
   WHERE game_date BETWEEN '2026-01-01' AND '2026-02-14'
     AND system_id = 'catboost_v9' AND is_voided = FALSE AND prediction_correct IS NOT NULL
   GROUP BY 1
   HAVING max_pct > 60
   ORDER BY 1;
   ```
5. **Simulate the cap:** Modify the what-if tool or write a one-off script that re-grades with a 60% directional cap
6. **If profitable:** Add the cap to `BestBetsAggregator.aggregate()` as a new negative filter, after all other filters but before ranking

### What NOT to do
- **Don't build an "UNDER day detector" model.** Predicting directional market regime is market timing, which historically fails (AUC < 0.50 — see dead ends: `hot_streak`, `cold_continuation`, `dual_agree`). The directional cap is a portfolio diversification rule, not a prediction.
- **Don't change the retrain cadence based on this.** The 7-day retrain cadence is working well. The collapse was a pick construction problem, not a model quality problem.

---

## Files Created/Modified

| File | Action | Description |
|------|--------|-------------|
| `bin/what_if_retrain.py` | CREATE | What-if retrain simulation (~350 lines, --model-path + direction breakdown) |
| `.claude/skills/what-if/SKILL.md` | CREATE | Claude skill definition |
| `docs/09-handoff/2026-02-20-SESSION-314C-HANDOFF.md` | CREATE | This handoff |

---

## Other Remaining Work

1. **Subset backfill (Jan 1 — Feb 19)** — Planned in Session 314B, not yet executed. Use `/backfill-subsets` skill.
2. **Commit and push** all Session 314C changes (what-if tool, skill, handoff).

---

## Quick Start for Next Session

```bash
# 1. Read the best bets architecture
# docs/01-architecture/best-bets-and-subsets.md

# 2. Read the aggregator (where the directional cap would go)
# ml/signals/aggregator.py — class BestBetsAggregator, method aggregate()

# 3. Query directional concentration history (see SQL above)

# 4. Run what-if tool on the collapse period
PYTHONPATH=. python bin/what_if_retrain.py \
    --model-path gs://nba-props-platform-models/catboost/v9/catboost_v9_33f_train20251102-20260108_20260208_170526.cbm \
    --eval-start 2026-01-15 --eval-end 2026-02-14

# 5. Check system health
/validate-daily
```

## Available Model Files on GCS

```bash
# Stale production model (Nov 2 - Jan 8)
gs://nba-props-platform-models/catboost/v9/catboost_v9_33f_train20251102-20260108_20260208_170526.cbm

# Jan 31 retrain
gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20251102-20260131_20260209_212708.cbm

# Current ASB retrain (Jan 6 - Feb 5, current production)
gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20260106-20260205_20260218_223530.cbm  # (check exact path)

# List all:
gsutil ls -r gs://nba-props-platform-models/ | grep catboost_v9
```
