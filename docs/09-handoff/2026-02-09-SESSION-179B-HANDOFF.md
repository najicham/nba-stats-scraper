# Session 179B Handoff — Experiment Infrastructure & Feature Weighting

**Date:** 2026-02-09
**Previous:** Session 179 (operational: deploy, backfill, 4-way comparison)
**This session:** Built experiment infrastructure to break Vegas dependency

---

## What Was Done

### 1. Alternative Experiment Modes Added to `quick_retrain.py`

Addresses the **retrain paradox**: `vegas_points_line` accounts for 29-36% of feature importance. Retrained models track Vegas too closely, generating almost no edge 3+ picks (4-6 vs hundreds). These modes let us explore the full spectrum from "fully dependent on Vegas" to "completely independent."

**New flags:**

| Flag | What It Does |
|------|-------------|
| `--no-vegas` | Drops all 4 vegas features (25-28). Model predicts with 29 features. |
| `--residual` | Trains on `actual - vegas_line`. Model learns where Vegas is wrong. Prediction = `vegas + model(residual)`. |
| `--two-stage` | Trains without vegas features. Edge = `model_prediction - vegas_line` at eval. |
| `--quantile-alpha F` | Quantile regression. Alpha > 0.5 biases predictions upward (e.g., 0.55 = 55th percentile). |
| `--exclude-features` | Drop any features by name (comma-separated). |

### 2. Feature Weighting (Gray Area Between Full Vegas and No Vegas)

Instead of all-or-nothing, CatBoost's `feature_weights` parameter dials down any feature's influence during split selection. Weight 0.3 means the feature needs 3.3x the information gain to be selected.

**New flags:**

| Flag | What It Does |
|------|-------------|
| `--feature-weights` | Per-feature: `vegas_points_line=0.3,fatigue_score=0.5` |
| `--category-weight` | Per-category: `vegas=0.3,composite=0.5` |

**9 feature categories defined:**

| Category | Features (indices) | Default Importance |
|----------|-------------------|-------------------|
| `recent_performance` | pts_avg_last_5/10/season, std, games_7d (0-4) | ~25-30% |
| `composite` | fatigue, shot_zone, pace, usage (5-8) | ~5-8% |
| `derived` | rest, injury, trend, min_change (9-12) | ~3-5% |
| `matchup` | opp_def, opp_pace, home_away, b2b, playoff (13-17) | ~5-8% |
| `shot_zone` | pct_paint/mid/three/ft (18-21) | ~2-4% |
| `team_context` | team_pace/off_rating/win_pct (22-24) | ~3-5% |
| `vegas` | vegas_line/opening/move/has_line (25-28) | **~43-53%** |
| `opponent_history` | avg_vs_opp, games_vs_opp (29-30) | ~2-3% |
| `minutes_efficiency` | min_avg, ppm_avg (31-32) | ~3-5% |

Individual `--feature-weights` override `--category-weight` for the same feature.

### 3. Advanced CatBoost Training Parameters

**New flags:**

| Flag | What It Does | Why It Matters |
|------|-------------|----------------|
| `--rsm 0.5-0.7` | Feature subsampling per split. 0.5 = 50% of features available per level. | Directly reduces vegas dominance — 50% chance it's excluded from any split. |
| `--grow-policy Depthwise` | Asymmetric trees (different branches use different features). | Default symmetric trees use same split at each depth; Depthwise lets branches specialize. Unlocks full RSM and min-data-in-leaf. |
| `--min-data-in-leaf 10-20` | Min samples per leaf node. | Prevents overfitting to narrow player/game combos. Requires Depthwise/Lossguide. |
| `--bootstrap MVS` | Importance sampling (focuses on hard examples). | Prioritizes games where Vegas is wrong — exactly the signal we want. |
| `--subsample 0.7-0.8` | Row subsampling fraction. | More diversity between trees. Requires Bernoulli or MVS bootstrap. |
| `--random-strength 2-5` | Split score noise multiplier. | Prevents always picking vegas as first split. More diverse trees. |
| `--loss-function STR` | CatBoost loss: `Huber:delta=5`, `LogCosh`, `MAE`, `RMSE`, etc. | Huber is robust to outlier games (50-point nights). LogCosh is smooth MAE. |

### 4. Bookmaker Expansion

Expanded default OddsAPI bookmakers from 2 to 6: added `betmgm`, `pointsbetus`, `williamhill_us`, `betrivers` alongside existing `draftkings`, `fanduel` in both game lines and player props scrapers.

### 5. Documentation

| File | What |
|------|------|
| `docs/08-projects/current/session-179-validation-and-retrain/01-RETRAIN-PARADOX-AND-STRATEGY.md` | Updated with Approach 7 (feature weighting), revised experiment priority, new implementation plan |
| `docs/08-projects/current/session-179-validation-and-retrain/02-ML-TRAINING-CONCEPTS-GUIDE.md` | **NEW** — Learning guide: how CatBoost works, loss functions, regularization, feature importance, tree structure, sampling, accuracy vs profitability, 14 concepts to study further |
| `.claude/skills/model-experiment/SKILL.md` | Full options table with all 16+ new flags, feature weighting docs, advanced params section, Master Experiment Plan (A/B/C phases with ready-to-paste commands) |

---

## Commits

```
1f46133b feat: Expand default OddsAPI bookmakers to 6 sportsbooks
abd4882a feat: Add alternative experiment modes and advanced training params to quick_retrain.py
```

---

## Files Modified

| File | Change |
|------|--------|
| `ml/experiments/quick_retrain.py` | 16 new CLI flags, `prepare_features()` exclude_features param, `FEATURE_CATEGORIES` dict, `parse_feature_weights()`, residual/two-stage/quantile modes in main(), experiment_type registration |
| `.claude/skills/model-experiment/SKILL.md` | All new flags documented, feature weighting section, advanced params section, Master Experiment Plan |
| `scrapers/oddsapi/oddsa_game_lines.py` | Default bookmakers expanded to 6 |
| `scrapers/oddsapi/oddsa_player_props.py` | Default bookmakers expanded to 6 |
| `scrapers/oddsapi/README.md` | Updated bookmaker list |
| `docs/08-projects/current/session-179-validation-and-retrain/01-RETRAIN-PARADOX-AND-STRATEGY.md` | Added Approach 7, updated priority and plan |
| `docs/08-projects/current/session-179-validation-and-retrain/02-ML-TRAINING-CONCEPTS-GUIDE.md` | NEW — ML training concepts learning guide |

---

## What Still Needs Doing

### P0: Run the Experiment Sweep (Next Session Priority)

All infrastructure is built and tested (dry-run verified). Now run the experiments. The SKILL.md has a complete Master Experiment Plan with ready-to-paste commands.

**Recommended order:**

1. **A1: Vegas Weight Sweep** (6 experiments, ~30 min) — Find the sweet spot for vegas influence:
   ```bash
   # Replace [COMMON] with: --train-start 2025-11-02 --train-end 2026-01-31 --eval-start 2026-02-01 --eval-end 2026-02-08 --walkforward --force

   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1a_BASELINE" [COMMON]
   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1b_VEG10" --category-weight "vegas=0.1" [COMMON]
   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1c_VEG30" --category-weight "vegas=0.3" [COMMON]
   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1d_VEG50" --category-weight "vegas=0.5" [COMMON]
   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1e_VEG70" --category-weight "vegas=0.7" [COMMON]
   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1f_NO_VEG" --no-vegas [COMMON]
   ```

2. **A2-A5: Other Sweeps** (RSM, loss function, tree structure, bootstrap) — Run in parallel

3. **B: Targeted Combos** — Combine winners from phase A

4. **C: Random Exploration** — Unusual combos to find surprises

**After running, compare with:**
```sql
SELECT experiment_name,
  JSON_VALUE(config_json, '$.category_weight') as cat_weights,
  JSON_VALUE(results_json, '$.mae') as mae,
  JSON_VALUE(results_json, '$.hit_rate_all') as hr_all,
  JSON_VALUE(results_json, '$.hit_rate_edge_3plus') as hr_3plus,
  JSON_VALUE(results_json, '$.bets_edge_3plus') as n_3plus,
  JSON_VALUE(results_json, '$.feature_importance.vegas_points_line') as vegas_imp
FROM nba_predictions.ml_experiments
WHERE experiment_name LIKE 'A%' OR experiment_name LIKE 'B%' OR experiment_name LIKE 'C%'
ORDER BY created_at DESC
```

**What to look for:**
- `n_3plus` > 50 (enough edge 3+ picks to be useful)
- `hr_3plus` >= 58% (profitable after -110 vig)
- `vegas_imp` decreasing as we dampen vegas (confirms weighting works)
- Walk-forward stability (consistent week-to-week, not just one lucky week)

### P1: Operational (Carry Over from Session 179)

These are unchanged from the original Session 179 handoff:

1. **Grade Feb 9** — raw data should be scraped by now
   ```bash
   bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_raw.nbac_gamebook_player_stats WHERE game_date='2026-02-09'"
   gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-09","trigger_source":"manual"}' --project=nba-props-platform
   ```

2. **Verify Feb 10 live predictions** — first overnight run with challengers
   ```sql
   SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions
   WHERE game_date='2026-02-10' AND system_id LIKE 'catboost_v9%' GROUP BY 1
   ```

3. **Monitor promotion readiness** — Jan 31 defaults at 54.8% HR (5 days). Need ~2 more weeks.

### P2: Future

4. **Based on experiment results:** If a weighted/advanced model beats both champion AND Jan 31 defaults, consider training a shadow challenger with those settings and deploying via `catboost_monthly.py`.

5. **Signal recalibration** — Thresholds were tuned for champion's prediction distribution (stddev 2.23). New models have different distributions.

6. **Update CLAUDE.md** — Add Session 179B experiment infrastructure to the MODEL section.

---

## Key Technical Details for Next Session

### How Feature Weighting Works Under the Hood

`parse_feature_weights()` in `quick_retrain.py` (line ~114) resolves both `--feature-weights` and `--category-weight` into a `{feature_index: weight}` dict that goes to CatBoost's `feature_weights` parameter. Individual weights override category weights.

### How Residual Mode Works

1. `prepare_features()` is called with full features (including vegas)
2. Vegas line is extracted from `X_train['vegas_points_line']`
3. Training target becomes `y = actual_points - vegas_line` (only rows with `vegas > 0`)
4. Model trains on residuals
5. At eval: `prediction = vegas_line + model.predict(X_eval)`
6. MAE/HR computed on reconstructed absolute predictions

### How Two-Stage Mode Works

1. Vegas features excluded via `prepare_features(exclude_features=VEGAS_FEATURE_NAMES)`
2. Model trains on 29 features, target = `actual_points`
3. At eval: model predicts independently, edge = `prediction - vegas_line`
4. HR computed against vegas lines as usual

### Experiment Registration

All experiments go to `nba_predictions.ml_experiments` with:
- `experiment_type`: `monthly_retrain_no_vegas`, `_residual`, `_two_stage`, `_quantile`, `_weighted`, or default `monthly_retrain`
- `config_json`: includes all flags — `no_vegas`, `residual`, `two_stage`, `quantile_alpha`, `exclude_features`, `feature_weights`, `category_weight`, `feature_weights_resolved` (actual index→weight map), plus all CatBoost HP overrides

### Model Filename Convention

```
catboost_v9_{n_features}f{mode_suffix}_train{start}-{end}_{timestamp}.cbm
```
Examples:
- `catboost_v9_29f_noveg_train20251102-20260131_20260209_180000.cbm`
- `catboost_v9_33f_wt_train20251102-20260131_20260209_180000.cbm`
- `catboost_v9_33f_resid_train20251102-20260131_20260209_180000.cbm`
- `catboost_v9_33f_q0.55_train20251102-20260131_20260209_180000.cbm`

---

## Context: The Retrain Paradox

**Why we built all this**: The model's #1 feature (`vegas_points_line`, ~30% importance) causes retrained models to track Vegas closely. More recent training data → better MAE but near-zero edge. The champion (trained Jan 8) generates edge because its "staleness" creates natural divergence from current Vegas lines.

**What we're testing**: Whether we can get a model that is both (a) trained on recent data and (b) independent enough from Vegas to generate profitable edge 3+ picks. Feature weighting, RSM, Depthwise trees, and residual modeling are all different approaches to this same goal.

**Success criteria**: 50+ edge 3+ picks with >= 58% HR at any setting = candidate for shadow testing.

See `docs/08-projects/current/session-179-validation-and-retrain/01-RETRAIN-PARADOX-AND-STRATEGY.md` for the full strategy doc.
