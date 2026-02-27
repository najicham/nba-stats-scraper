# Session 354 Handoff — Star UNDER Fix, Tier Weighting, Experiment Roadmap

**Date:** 2026-02-27
**Previous:** Session 353 — All models BLOCKED, recovery investigation

## What Session 354 Did

### 1. Diagnostic Analysis (completed)
Ran comprehensive diagnostics revealing:
- **V12 UNDER is the root problem**: 82% of edge 3+ picks are UNDER, hitting at 48.6%. OVER is profitable at 62.5%.
- **Star UNDER bias**: 95% of star (line 25+) edge 3+ predictions are UNDER, hitting at only 51.3%. Root cause: top 3 features (season avg, L10 avg, L5 avg) = 46% of model importance. Model anchors to season average, books price in hot streaks.
- **Vegas collapsed**: Full-vegas models went from 57.6% (Jan) → 50.3% (Feb 15+). Low-vegas (56.1%) and no-vegas (50.9%) are holding better.
- **Injury signal**: When 1 star teammate is out, UNDER HR = 62.5% (N=40). When 0 stars out, UNDER HR = 46.0% (N=63).
- **Teammate usage**: `teammate_usage_available` has 0% model importance but medium usage (15-30) + UNDER = 32.0% HR (N=25). Model is blind to an actionable signal.
- **Starter tier (15-20 line)**: Worst performer at 46.7% HR (N=30).

### 2. Deployed Changes
- **Star UNDER filter** in `ml/signals/aggregator.py`: Blocks UNDER picks when `points_avg_season >= 25`. Deployed via auto-deploy (commit `345526cc`). TODO: make injury-aware (allow when `star_teammates_out >= 1` — requires piping this field through `supplemental_data.py`).
- **Edge floor test fix**: Updated test from `edge=3.0` to `edge=2.5` to match Session 352's MIN_EDGE=3.0 change.

### 3. New Infrastructure
- **`--tier-weight` flag** in `ml/experiments/quick_retrain.py`: Per-tier sample weighting for CatBoost training. Usage: `--tier-weight "star=3.0,starter=1.5,role=1.0,bench=0.8"`. Multiplies with recency weights if both active.

### 4. Shadow Models
- **Q55 TW** (`catboost_v12_noveg_q55_train0115_0222`): Force-registered as shadow. 80% edge 3+ HR on N=10 (too small). Enabled in registry.
- **Tier-weighted Q55 TW**: Trained but NOT registered (failed directional balance gate — UNDER=50%). Results inconclusive on tiny eval window.
- **Disabled duplicate**: `catboost_v12_noveg_q55_train1225_0209` disabled to prevent duplicate family.

### 5. Builds Triggered
Three Cloud Build jobs triggered at 19:41 UTC. Star UNDER filter should be live.

---

## Experiment Roadmap — What to Do Next

Four independent agents analyzed the system and converged on a prioritized experiment roadmap. **Execute in order of priority.**

### Priority 1: Prop Line Anchor Training (HIGHEST IMPACT, EASIEST)

**What:** Change the training target from `actual_points` to `actual_points - prop_line`. The model learns to predict *deviations from the line* instead of raw points. At eval time: `final_prediction = prop_line + model_prediction`.

**Why:** The model's top features predict raw points well but direction poorly. By anchoring to the prop line, the model only needs to learn the adjustment — matchup, fatigue, injury signals that cause deviations. The prop line never enters the feature set, so this is NOT the same as the failed residual model (which used vegas_line as a feature and caused error compounding).

**How:** In `quick_retrain.py`, modify the target variable computation. The prop line is available as `feature_25_value` (vegas_points_line) in the training data.

```python
# Current:
y_train = df_train['actual_points']

# New:
prop_lines = df_train['feature_25_value'].fillna(0)
valid = prop_lines > 0
df_train = df_train[valid]
y_train = df_train['actual_points'] - prop_lines[valid]
# At eval: predicted_points = prop_line + model.predict(X)
```

**Add a `--anchor-line` flag** to make this togglable. When active, the quantile alpha should be 0.50 (predict median deviation, not 55th percentile of deviation).

**Train command:**
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V12_NOVEG_ANCHOR_LINE" --feature-set v12 --no-vegas \
    --anchor-line \
    --category-weight "recent_performance=2.0,derived=1.5,matchup=0.5" \
    --train-start 2026-01-15 --train-end 2026-02-22 \
    --eval-start 2026-02-23 --eval-end 2026-02-27 \
    --force --enable
```

**IMPORTANT:** This is different from dead ends because:
- NOT two-stage (no cascaded models)
- NOT residual with vegas as feature (prop line is the anchor, not a feature)
- The model cannot see the line, only the deviation target

---

### Priority 2: Differenced Features

**What:** Add 2-3 new features that encode the gap between player metrics and the prop line:
- `season_avg_vs_line = points_avg_season - prop_line`
- `last5_avg_vs_line = points_avg_last_5 - prop_line`
- `last10_avg_vs_line = points_avg_last_10 - prop_line`

**Why:** The model currently sees "player averages 27 PPG" and "prop line is 29.5" as separate, unrelated features. The differenced features explicitly tell the model: "the line is 2.5 points above the season average — this is an UNDER setup." Currently the model must learn this interaction implicitly, which is hard when season_avg dominates.

**How:** Add to the V12 feature augmentation in `quick_retrain.py` (lines ~2600-2650 area where V12 features are computed). These use `feature_25_value` (vegas_points_line) which is available even in no-vegas mode (just excluded from the model features).

**Can combine with Priority 1** — test both together and separately.

---

### Priority 3: New Negative Filters (no retraining needed)

Add these filters to `ml/signals/aggregator.py` after the star UNDER block:

#### 3a. Medium Teammate Usage UNDER Block
```python
# Medium teammate usage UNDER block (Session 354): 32.0% HR (N=25)
# Model has 0% importance on this feature but production data shows clear signal.
# When moderate teammate usage is available (15-30), UNDER predictions are catastrophic.
teammate_usage = pred.get('teammate_usage_available') or 0
if (pred.get('recommendation') == 'UNDER'
        and 15 <= teammate_usage <= 30):
    filter_counts['med_usage_under'] += 1
    continue
```

**Requires:** `teammate_usage_available` must be added to the pred dict. Check if it's in `supplemental_data.py` query. If not, add it from the feature store (`feature_47_value` in `ml_feature_store_v2`).

#### 3b. Starter V12 UNDER Block (line 15-20)
```python
# Starter V12 UNDER block (Session 354): 46.7% HR (N=30)
# V12 UNDER is specifically bad for 15-20 line range.
if (pred.get('recommendation') == 'UNDER'
        and 15 <= season_avg < 20
        and source_family.startswith('v12')):
    filter_counts['starter_v12_under'] += 1
    continue
```

**Note:** `season_avg` is already available on pred dict. Use `points_avg_season` (already there from Session 354 star filter).

#### 3c. Exempt combo_3way and combo_he_ms from Edge Floor
These signals have 95%+ HR. Picks with these signals should bypass the edge floor entirely.

---

### Priority 4: Conformal Prediction Intervals

**What:** Train Q20 and Q80 models alongside Q55. Only take UNDER when Q80 prediction < prop_line. Only take OVER when Q20 prediction > prop_line.

**Why:** The binary classifier (AUC 0.507) failed because it tried to learn direction directly. Conformal intervals keep the point prediction (which works) and use the prediction spread as a confidence filter. If even the optimistic Q80 model says UNDER, that's high conviction.

**How:**
```bash
# Train the bracket models
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V12_NOVEG_Q20_BRACKET" --feature-set v12 --no-vegas \
    --quantile-alpha 0.20 \
    --train-start 2026-01-15 --train-end 2026-02-22 \
    --eval-start 2026-02-23 --eval-end 2026-02-27 --force

PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V12_NOVEG_Q80_BRACKET" --feature-set v12 --no-vegas \
    --quantile-alpha 0.80 \
    --train-start 2026-01-15 --train-end 2026-02-22 \
    --eval-start 2026-02-23 --eval-end 2026-02-27 --force
```

Then implement a post-processing filter in the aggregator that uses the Q20/Q80 predictions to gate directional picks. This requires the bracket models to produce predictions alongside the main model — may need infrastructure work.

---

### Priority 5: New V16 Features

Add these "deviation from baseline" features. All computable from existing BigQuery tables, no new scrapers needed.

#### From player_game_summary (easy):
1. **`over_rate_last_10`**: Fraction of last 10 games where `actual_points > prop_line`. Direct OVER/UNDER tendency.
2. **`margin_vs_line_avg_last_5`**: Average of `(actual_points - prop_line)` over last 5 games. How much player has been beating/missing lines.
3. **`points_cv_last_10`**: `points_std_last_10 / points_avg_last_10`. Normalized volatility — a std of 5 means different things for a 30ppg player vs 10ppg.
4. **`def_rating_vs_recent_opponents`**: Tonight's opponent def_rating minus avg def_rating of last 5 opponents. "Is tonight harder or easier than what inflated the recent average?"
5. **`free_throw_trip_rate_last_5`**: `SUM(ft_attempts) / SUM(fg_attempts)` over last 5. Leading indicator of aggressiveness changes.

#### From play-by-play (requires new Phase 3 processor):
6. **`fourth_quarter_scoring_share`**: % of points scored in Q4, averaged over last 5 games. Garbage time inflates averages — the starters OVER collapse explained.
7. **`quarter_scoring_entropy`**: Shannon entropy of quarter-level scoring. High = consistent across quarters. Low = burst scorer.

**Implementation approach:** Start with features 1-2 only (easiest, highest expected impact). Add to the V12 augmentation in `quick_retrain.py`. If they show signal (importance > 1%), add the rest.

---

### Priority 6: Volume Increases

After filters are tightened, re-expand volume in profitable segments:
- **Lower edge to 2.5 for high-starter (line 20-25)**: 64% HR supports it
- **Lower OVER edge to 2.0 with signal confirmation**: OVER signals at 70-95% HR are underexploited
- **Exempt 95% HR signals from edge floor**: `combo_3way` and `combo_he_ms` — free money being filtered

---

## Key Files to Reference

| File | What |
|------|------|
| `ml/signals/aggregator.py` | Best bets filter pipeline — add new filters here |
| `ml/signals/supplemental_data.py` | Query that builds pred dict — add new fields here |
| `ml/experiments/quick_retrain.py` | Training script — add `--anchor-line`, new features |
| `shared/ml/feature_contract.py` | Feature definitions — V16 contract goes here |
| `data_processors/precompute/ml_feature_store/feature_calculator.py` | Feature computation |
| `tests/unit/signals/test_aggregator.py` | Aggregator tests — update when adding filters |

## Dead Ends (Don't Revisit)

See CLAUDE.md "Dead ends" section. Key ones for this work:
- Binary OVER/UNDER classifier (AUC 0.507 = random)
- Two-stage pipeline (error compounding)
- Residual model with vegas as feature (different from prop-line-anchor approach!)
- Tier models on small windows (star=244 samples)
- Min-PPG filter (33.3%), recency weighting (33.3%)
- Q43 (catastrophic UNDER), Q60 (OVER volume but not profitably)
- Min-data-in-leaf 25/50 (kills feature diversity)

## Current Model Fleet Status

| Model | Status | HR 7d | Notes |
|-------|--------|-------|-------|
| catboost_v12 | BLOCKED | 44.7% | 27 days stale, production |
| catboost_v9_low_vegas_train0106_0205 | BLOCKED | 50-51.9% | Best performer, UNDER specialist |
| catboost_v12_noveg_q55_train0115_0222 | Shadow (NEW) | TBD | Session 354 retrain, freshest data |
| 11 other shadow models | BLOCKED | Various | Most have 0-1 graded edge 3+ bets |
| LightGBM (2 models) | Shadow | TBD | First predictions expected Feb 28 |

## Critical Context

- **Best bets are still profitable** (62.5% 30d, 72.7% 7d) despite all models BLOCKED
- **Star UNDER filter is now deployed** — will immediately cut ~30+ losing picks from pool
- **Pick volume is the real problem** (1-4/day) — filters help HR but hurt volume more
- **The prop-line-anchor experiment is the single highest-leverage change** — fundamentally reshapes what the model learns with minimal code change
- All 4 agents agreed: the model needs to predict deviations, not raw points
