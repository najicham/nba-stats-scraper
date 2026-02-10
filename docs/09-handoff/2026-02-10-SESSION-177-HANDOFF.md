# Session 177 Handoff

**Date:** 2026-02-10
**Previous:** Session 176
**Type:** Feature implementation — Parallel V9 Models

---

## What Was Done

### 1. Parallel Models Infrastructure (Core)

Built the system to run multiple CatBoost V9 models simultaneously in shadow mode. Each challenger gets its own `system_id`, is graded independently, and does NOT affect user-facing picks or alerts.

**Files modified:**
- `predictions/worker/prediction_systems/catboost_monthly.py` — GCS loading, SHA256 tracking, model attribution metadata, 3 challenger configs
- `ml/experiments/quick_retrain.py` — Prints ready-to-paste MONTHLY_MODELS config snippet when gates pass
- `bin/model-registry.sh` — Added `compare` subcommand

**Files created:**
- `bin/compare-model-performance.py` — Backtest vs production comparison
- `bin/backfill-challenger-predictions.py` — Generates historical predictions for challengers
- `.claude/skills/compare-models/SKILL.md` — `/compare-models` skill
- `docs/08-projects/current/retrain-infrastructure/03-PARALLEL-MODELS-GUIDE.md`
- `docs/08-projects/current/retrain-infrastructure/04-HYPERPARAMETERS-AND-TUNING.md`

**Files updated:**
- `docs/08-projects/current/retrain-infrastructure/01-EXPERIMENT-RESULTS-REVIEW.md` — Full rewrite with all 8 experiments
- `.claude/skills/model-experiment/SKILL.md` — Shadow deploy workflow
- `CLAUDE.md` — Parallel Models section under MODEL keyword

### 2. Three Challengers Deployed

| system_id | Experiment | Training | Backtest HR All | Notes |
|---|---|---|---|---|
| `catboost_v9_train1102_0108` | V9_BASELINE_CLEAN | Nov 2 - Jan 8 | 62.4% | Same dates as prod, better features |
| `catboost_v9_train1102_0208` | V9_FULL_FEB | Nov 2 - Feb 8 | 75.4%* | Extended training + tuning + recency |
| `catboost_v9_train1102_0208_tuned` | V9_TUNED_FEB | Nov 2 - Feb 8 | 74.8%* | Extended training + tuning only |

*Contaminated backtest (train/eval overlap). Real performance will be lower.

Models uploaded to `gs://nba-props-platform-models/catboost/v9/monthly/`.

### 3. Backfill of catboost_v9_train1102_0108

- Ran `backfill-challenger-predictions.py` for Jan 9 - Feb 8 (28 game dates)
- **2,958 predictions** written to `player_prop_predictions`
- **Grading triggered** via Pub/Sub for all 31 dates (Jan 9 - Feb 8)
- Grading was processing at end of session — may take 5-10 minutes

### 4. Comprehensive Documentation

- **04-HYPERPARAMETERS-AND-TUNING.md** — Explains what hyperparameters are, what tuning found, all training factors (recency weighting, walk-forward, training window length), 12 future experiments ranked by priority
- **01-EXPERIMENT-RESULTS-REVIEW.md** — All 8 experiments with results, contamination flags, deployment status, and hyperparameters used
- **03-PARALLEL-MODELS-GUIDE.md** — How to add/monitor/promote/retire challengers

---

## What the Next Session Should Do

### Priority 1: Check Grading Results

Grading was triggered but may not have completed. Check:

```bash
# Check if challenger predictions are graded
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as n_graded,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9_train1102_0108'
  AND game_date >= '2026-01-09'
  AND prediction_correct IS NOT NULL
GROUP BY 1"

# If empty, re-trigger grading (safe — idempotent DELETE+INSERT)
# Use the loop from this session or trigger individual dates
```

### Priority 2: Run Model Comparison

Once graded:

```bash
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0108 --days 31
```

This will show backtest vs production performance and compare against the champion.

### Priority 3: Backfill Feb 8 Models (Feb 9 Onwards)

The two Feb 8 models (`catboost_v9_train1102_0208` and `_tuned`) had no post-training dates to backfill at session end. Once Feb 9 games are graded:

```bash
PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0208
PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0208_tuned
```

But these models will also generate live predictions going forward from the next overnight run, so backfill is only needed if you want Feb 9 data specifically.

### Priority 4: Evaluate Backfill Results

After grading completes, the key question: **Does the challenger's real production performance match its backtest?**

Expected:
- `catboost_v9_train1102_0108` backtest HR All: 62.4% → expect 57-60% in production (3-5pp backtest advantage)
- If production shows < 55% → model is no better than champion
- If production shows > 58% → real improvement, consider promotion after more data

### Priority 5: Check Feb 10 Live Predictions

The challengers should generate their first live predictions in the Feb 10 overnight run:

```bash
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as n
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-10'
  AND system_id LIKE 'catboost_v9_train%'
GROUP BY 1"
```

---

## Known Issues

1. **Jan 12 anomaly:** The backfill shows 81 actionable predictions (edge 3+) on Jan 12, with avg edge +7.57. Investigate — could be a feature store anomaly for that date or a legitimate high-edge day.

2. **Feb 8 models can't be backfilled yet:** They trained through Feb 8, so Feb 9 is the first out-of-sample day. Feb 9 games were still scheduled at session end.

3. **Contaminated backtest metrics:** The Feb 8 models (V9_FULL_FEB, V9_TUNED_FEB) have inflated backtest metrics due to train/eval overlap. DO NOT use backtest numbers for promotion decisions — only use real production graded results.

---

## Commits (Session 177)

```
428ba011 feat: Add challenger prediction backfill script (Session 177)
a12b910d feat: Add /compare-models skill for monitoring shadow challengers (Session 177)
309c494c docs: Full experiment review, hyperparameters guide, skill update (Session 177)
fb664d68 feat: Add 2 more challengers — V9_FULL_FEB and V9_TUNED_FEB (Session 177)
e65aae09 feat: Parallel V9 models — GCS loading, comparison tooling, first challenger (Session 177)
```

---

## Quick Start for Next Session

```bash
# 1. Check grading status
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as graded
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9_train1102_0108'
GROUP BY 1"

# 2. If graded, run comparison
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0108 --days 31

# 3. Check Feb 10 live predictions
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as n
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-10' AND system_id LIKE 'catboost_v9%'
GROUP BY 1"
```
