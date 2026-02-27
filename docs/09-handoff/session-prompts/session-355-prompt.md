# Session 355 Prompt

Read the Session 354 handoff and execute the experiment roadmap:

```
docs/09-handoff/2026-02-27-SESSION-354-HANDOFF.md
```

## What to do (in priority order):

### 1. Prop Line Anchor Training (HIGHEST PRIORITY)
Add an `--anchor-line` flag to `quick_retrain.py` that changes the training target from `actual_points` to `actual_points - prop_line`. At eval time, `final_prediction = prop_line + model.predict(X)`. The prop line (`feature_25_value`) is available in training data but NOT passed as a feature — the model only learns deviations. Use quantile alpha 0.50 for this mode (predict median deviation). Train it, evaluate, and if gates pass, force-register as shadow.

### 2. Differenced Features
Add 2-3 features to the V12 augmentation: `season_avg_vs_line`, `last5_avg_vs_line`, `last10_avg_vs_line` (each = scoring avg minus prop line). These are computed from existing data (`feature_2_value - feature_25_value`, etc.). Train a model with these added and compare.

### 3. New Negative Filters (no retraining)
Add to `ml/signals/aggregator.py`:
- **Medium teammate usage UNDER block**: Block UNDER when `teammate_usage_available` between 15-30 (32% HR, N=25). Requires piping `teammate_usage_available` through `supplemental_data.py` into the pred dict.
- **Starter V12 UNDER block**: Block V12 UNDER when `points_avg_season` between 15-20 (46.7% HR, N=30).
- **Exempt combo_3way and combo_he_ms signals from edge floor** (95%+ HR signals being filtered unnecessarily).

### 4. Conformal Prediction Intervals
Train Q20 and Q80 bracket models. Design a filter: only take UNDER when Q80 < line, only take OVER when Q20 > line. This uses existing multi-quantile infrastructure.

### 5. V16 Feature Experiment
Start with just 2 features from player_game_summary (no new pipeline needed):
- `over_rate_last_10`: fraction of last 10 games where actual > prop line
- `margin_vs_line_avg_last_5`: avg(actual - prop_line) over last 5 games

## Key context:
- All models are BLOCKED but best bets still profitable (62.5% 30d)
- Star UNDER filter was deployed this session — should be live now
- V12's core problem is UNDER bias (82% of edge 3+ picks are UNDER, 48.6% HR)
- The model anchors to season averages (46% feature importance in top 3)
- v9_low_vegas is the UNDER specialist (80% HR at edge 5-7)
- V12 OVER is actually profitable (62.5%)
- Don't revisit dead ends listed in CLAUDE.md

## Important: the prop-line-anchor approach is NOT the same as these dead ends:
- NOT two-stage pipeline (no cascaded models)
- NOT residual model (that used vegas_line AS a feature causing error compounding)
- The prop line is the ANCHOR (target transformation), not a feature
