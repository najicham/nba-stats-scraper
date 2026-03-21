# Session 472 Handoff — Pick Drought Diagnosed & Fixed, CF Eval Window Bug

**Date:** 2026-03-18
**Previous:** Session 471 (multi-framework retrain, filter crash fix)

## TL;DR

4-day pick drought (March 15-18) caused by weekly-retrain CF deploying models that predict within ±1pt of Vegas line. Root cause: governance gates were evaluated on **in-sample** data. The new models "passed" but were useless. All 4 broken models disabled, correct models retrained and enabled, CF bug fixed.

---

## What Was Done

### 1. Diagnosed Pick Drought (March 15-18)

The system produced 0-1 best bets picks per day for 4 consecutive days. Investigated the full chain:

- **Filter audit** (`best_bets_filter_audit`): only 3-16 candidates/day reaching the pipeline, 0 passing filters. This is the symptom.
- **Root cause**: New models deployed March 16 predict avg_abs_diff of **0.84-1.04 pts from the Vegas line** (vs. 4-5 pts for prior models). With MIN_EDGE = 3.0, 98%+ of predictions were HOLD/PASS. The pipeline starved.
- **Why they were deployed**: The weekly-retrain CF evaluated governance gates on the **last 14 days of the training window** (in-sample). Overfit models showed high HR on training data, passed all gates, then predicted the Vegas line on new dates.

**Key diagnostic query that revealed the issue:**
```sql
SELECT system_id,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_abs_diff,
  COUNTIF(ABS(predicted_points - current_points_line) >= 3) as edge_3plus,
  COUNT(*) as total
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-03-18'
  AND system_id IN ('catboost_v12_noveg_train0118_0315','catboost_v12_train0118_0315','catboost_v9_train0118_0315')
  AND is_active = TRUE AND current_points_line IS NOT NULL
GROUP BY 1
-- Result: avg_abs_diff = 0.84-1.04, edge_3plus = 1-5 / 110 predictions
```

### 2. Disabled the 4 Broken March 16 Models

All 4 models from the March 16 auto-retrain disabled via `bin/deactivate_model.py`:
- `catboost_v12_noveg_train0118_0315`
- `catboost_v12_train0118_0315`
- `catboost_v9_train0118_0315`
- `xgb_v12_noveg_train0118_0315`

### 3. Re-enabled lgbm Bridge Model

`lgbm_v12_noveg_vw015_train1215_0208` (HEALTHY, 60% HR 7d) re-enabled as bridge.
This model generates normal edge distributions (avg 4-5 pts for directional picks).

### 4. Fixed CF Eval Window Bug (CRITICAL)

**File:** `orchestration/cloud_functions/weekly_retrain/main.py`

**Before (broken):**
```python
eval_start = (train_end + timedelta(days=1) - timedelta(days=EVAL_DAYS))  # last 14d of training
eval_end = train_end  # in-sample!
```

**After (fixed):**
```python
# Reserve the most recent EVAL_DAYS for out-of-sample evaluation
eval_end = train_end
eval_start = eval_end - timedelta(days=EVAL_DAYS - 1)
train_end = eval_start - timedelta(days=1)  # shift training window back
train_start = train_end - timedelta(days=ROLLING_WINDOW_DAYS)
```

**Effect:** When the CF runs next Monday (March 23) with "yesterday" = March 22:
- eval_end = March 22, eval_start = March 9 (14 days, all graded)
- train_end = March 8, train_start = Jan 11 (56 days)
- Governance gates will evaluate on genuinely out-of-sample data.

### 5. Demoted `downtrend_under` to SHADOW_SIGNALS

**File:** `ml/signals/aggregator.py`

- Removed from `UNDER_SIGNAL_WEIGHTS` (was weight 2.0, counted toward real_sc)
- Added to `SHADOW_SIGNALS` (0.0x, excluded from real_sc, no longer inflates signal counts)
- Reason: 16.7% HR (N=6, 7d) — catastrophic. Was inflating real_sc on losing picks.

### 6. Manual Retrain with Correct Out-of-Sample Eval

Ran `quick_retrain.py` directly with venv Python for 4 families:
- Train: Jan 13 – Mar 10 | **Eval: Mar 11-17 (out-of-sample, all graded)**

Results:
| Family | Result | HR @ Edge 3+ | N |
|--------|--------|-------------|---|
| v12_mae (CatBoost) | **PASSED** | 66.7% | 45 |
| lgbm_v12_noveg_mae | PASSED (same as v12_mae — registry misconfigured, ran as CatBoost) | 66.7% | 45 |
| v9_mae | FAILED | 60.0% | 20 (< min 25) + UNDER 50% |
| xgb_v12_noveg_mae | FAILED | 57.1% | — |

Manually enabled `catboost_v12_noveg_train0113_0310` (the passing model).

### 7. Fixed Pre-existing Bugs Exposed by Pre-commit

- **BettingPros query validator**: Updated to only flag table references inside backticks (SQL context), not docstring mentions. Previously flagging 4+ false positives per commit.
- **CF import validator**: Now uses `.venv/bin/python` for import tests (has google packages). System Python was causing "No module named 'google'" failures on every CF commit.
- **4 production queries missing `market_type = 'points'`**: Fixed in `player_universe.py`, `monthly_retrain/main.py`, `line_quality_self_heal/main.py`, `evaluate_model.py`.
- **Removed `phase2_to_phase3` from CF import validator**: Phase 2→3 uses direct Pub/Sub, no CF directory exists.

---

## Current State

### Enabled Fleet (2 models)

| Model | Family | Gov HR | Gov N | Trained Through |
|-------|--------|--------|-------|-----------------|
| `catboost_v12_noveg_train0113_0310` | v12_noveg_mae | **66.7%** | 45 | Mar 10 |
| `lgbm_v12_noveg_vw015_train1215_0208` | lgbm_v12_noveg_mae | 60.0% (7d) | 10 | Feb 8 (bridge) |

### Algorithm Version

`v470_demote_high_skew` (no change to aggregator version string — signal weight changes only)

### Deployment Status at Handoff

Cloud builds were WORKING (not yet complete) for:
- `prediction-coordinator` (weekly_retrain CF is part of coordinator build)
- Cloud Function `weekly_retrain` (eval window fix)
- Cloud Function `prediction_worker` (aggregator signal weight change)

```bash
# Verify builds completed:
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

---

## P0 — Immediate Actions (Next Session)

### 1. Check if Picks Are Flowing Again (March 19)

```sql
SELECT game_date, COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  COUNTIF(NOT pa.prediction_correct) as losses
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date >= '2026-03-18'
GROUP BY 1 ORDER BY 1 DESC
```

Expected: 3-7 picks/day from the 2 enabled models. If still 0, check `best_bets_filter_audit` for candidate counts.

### 2. Verify `catboost_v12_noveg_train0113_0310` Edge Distribution

The new model should produce normal edges (avg 4-5 pts for directional picks):
```sql
SELECT system_id,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_abs_diff,
  COUNTIF(ABS(predicted_points - current_points_line) >= 3) as edge_3plus,
  COUNTIF(ABS(predicted_points - current_points_line) >= 5) as edge_5plus,
  COUNT(*) as total
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v12_noveg_train0113_0310'
  AND is_active = TRUE AND current_points_line IS NOT NULL
GROUP BY 1
```

**If avg_abs_diff < 2.0**: same edge collapse problem. This model has the same date range as the March 11 batch. If the March 11 models also had the collapse issue, we need a different training window.

### 3. Fix `filter_counts` to Use `defaultdict(int)` (P1 from Session 471, still open)

The hardcoded `filter_counts` dict in `aggregator.py` will crash again when the next filter is added without a matching key. Session 471 flagged this. Still not fixed.

```python
# In ml/signals/aggregator.py, replace:
filter_counts = {'blacklist': 0, 'edge_floor': 0, ...}
# With:
from collections import defaultdict
filter_counts = defaultdict(int)
```

### 4. Fix lgbm Family Registry Config

The `lgbm_v12_noveg_mae` family in `model_registry` doesn't include `--framework lightgbm` in its args column. When `retrain.sh --all` runs, the lgbm family trains as CatBoost (default). This means we're getting duplicate CatBoost models instead of LightGBM.

```sql
-- Check current family config:
SELECT model_family, feature_set, loss_function, extra_args
FROM nba_predictions.model_registry
WHERE model_family = 'lgbm_v12_noveg_mae'
LIMIT 1
```

Fix: update the `extra_args` or equivalent column to include `--framework lightgbm`.

---

## P1 — Follow-up Tasks

### Monitor New Models Building Performance History

`model_performance_daily` only has data through March 15. New models (`catboost_v12_noveg_train0113_0310`) won't appear until 7+ days accumulate. Until then, decay detection will show INSUFFICIENT_DATA — normal.

### UNDER Signal Collapse — Ongoing Watch

UNDER signals have been broadly failing for 2+ weeks:
- `projection_consensus_under`: 34.4% HR (N=32)
- `star_favorite_under`: 21.4% HR (N=14)
- `blowout_risk_under`: 29.4% HR (N=17)
- `day_of_week_under`: 20.0% HR (N=15)

These are already in BASE_SIGNALS or SHADOW_SIGNALS so they don't inflate real_sc. No code action needed. But if UNDER signal collapse continues for another week, consider whether the scoring environment shift (PPG 10.2→11.0 over 2 weeks) warrants a signal audit.

### combo_3way / combo_he_ms Still COLD (10+ days)

These are model-dependent and are at 0.0x weight while COLD. They were COLD even before the drought. Will self-correct when model HR recovers above COLD threshold.

### Season-End Planning

NBA regular season ends ~April 13. Last 2 weeks typically have tanking teams — consider pausing picks or adding a `tanking_risk` filter by April 1.

### Weekly-Retrain Next Run (Monday March 23)

First CF run with the fixed out-of-sample eval window. It will:
- eval_end = March 22, eval_start = March 9 (14 days)
- train_end = March 8, train_start = January 11

Watch the Slack `#deployment-alerts` channel for the retrain completion notification. If governance gates fail (N too small), the issue is that only 14 days of data were graded in the eval window — may need to increase `EVAL_DAYS` back to a smaller window.

---

## What NOT to Do

- **Don't re-enable the March 16 batch** (`train0118_0315` models) — they predict within ±1pt of the line
- **Don't lower MIN_EDGE or OVER_FLOOR** to compensate for broken models — the floor thresholds are 5-season validated
- **Don't run `retrain.sh --all` without checking `retrain.sh --all --dry-run` first** — the families enabled in BQ determine what gets retrained
- **Don't assume `--enable` flag reliably enables new models** — the BQ streaming buffer issue (~30 min delay) means manual enable via `bq query UPDATE` is more reliable
- **Don't use system `python3` for scripts requiring google packages** — always use `.venv/bin/python`
- **Don't add a new filter to `aggregator.py` without adding its key to `filter_counts`** — will crash the entire BB pipeline silently producing 0 picks

---

## Key Files Changed This Session

| File | Change |
|------|--------|
| `orchestration/cloud_functions/weekly_retrain/main.py` | **CF eval window: in-sample → out-of-sample** |
| `ml/signals/aggregator.py` | Demoted `downtrend_under` to SHADOW_SIGNALS |
| `bin/validation/validate_cloud_function_imports.py` | Use venv Python for import tests; remove phase2_to_phase3 |
| `.pre-commit-hooks/validate_bettingpros_queries.py` | Only flag backtick SQL refs, not docstrings |
| `shared/validation/context/player_universe.py` | Add `market_type = 'points'` to BettingPros query |
| `orchestration/cloud_functions/monthly_retrain/main.py` | Add `market_type = 'points'` to BettingPros query |
| `orchestration/cloud_functions/line_quality_self_heal/main.py` | Add `market_type = 'points'` to BettingPros query |
| `ml/experiments/evaluate_model.py` | Add `market_type = 'points'` to BettingPros query |

---

## Opus Agent Findings (Research Done This Session)

Two Opus agents reviewed the situation from different angles:

**Agent 1 (Model Training):**
- The CF eval window overlap was the primary cause of governance gate gaming
- `min_n_graded` has been progressively lowered (50→25→15) reducing statistical power
- `retrain.sh` correctly uses out-of-sample eval (both `--train-start` and `--train-end` provided → `eval = train_end + 1` through `train_end + eval_days`)
- The CF ran differently from `retrain.sh` — this discrepancy was the bug

**Agent 2 (Signal/Pipeline):**
- MIN_EDGE=3.0 and OVER_FLOOR=5.0 are correct — do NOT lower them for broken models
- `mae_gap_obs` is observation-only (no `continue` statement) — was NOT blocking picks
- `signal_density` filter is not too aggressive — the 3-9 candidate counts were from genuine lack of edge
- `downtrend_under` was the only active UNDER signal in UNDER_SIGNAL_WEIGHTS with catastrophic HR — all others are already BASE/SHADOW

---

## Quick Start for Next Session

```bash
# 1. Check picks for March 19
/todays-predictions

# 2. Verify edge distribution of new model
bq query --use_legacy_sql=false "
SELECT system_id, ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_edge,
  COUNTIF(ABS(predicted_points - current_points_line) >= 3) as edge_3plus, COUNT(*) as total
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE AND current_points_line IS NOT NULL
  AND system_id IN ('catboost_v12_noveg_train0113_0310','lgbm_v12_noveg_vw015_train1215_0208')
GROUP BY 1"

# 3. Full steering report if something looks off
/daily-steering
```
