# Session 230 Continuation — Deploy V12 Model 1 to Production

## Context

We're deploying V12 Model 1 (Vegas-free CatBoost, 50 features, MAE loss) to production. The current V9 champion has decayed to 39.9% HR. V12 averages 67% HR across 4 eval windows (+8.7pp over V9).

**What's been done (Sessions 227-230):**
- Phase 0: Diagnostics complete — Stars OVER terrible (36.4%), Role/Bench OVER good (55-57%), ALL UNDER loses money
- Phase 1A: Vegas-free baseline validated (V9 no-vegas: 48.9-69.4%)
- Phase 1B: V12 (54 features) validated at 67% avg HR, Feb 2026 crossed breakeven (60%)
- Phase 2: Edge Classifier (Model 2) built and tested — **NEGATIVE RESULT, AUC < 0.50, don't revisit**
- Key learning: Never use in-sample predictions as training data for a second model. Use OOF (out-of-fold) predictions.
- CLAUDE.md updated with lessons learned

**Key docs to read:**
```
cat docs/08-projects/current/model-improvement-analysis/22-PHASE1B-RESULTS.md
cat docs/08-projects/current/model-improvement-analysis/23-PHASE2-EDGE-CLASSIFIER-RESULTS.md
cat docs/09-handoff/2026-02-13-SESSION-230-HANDOFF.md
```

## Your Task: Deploy V12 to Production

### Architecture

V12 is "no-vegas" — trained WITHOUT features 25-28. Feature store has 39 features (V11 schema). V12 needs 15 additional features (indices 39-53) that are currently only computed at training time via `augment_v12_features()` in `quick_retrain.py`.

**Approach: Augment at prediction time** (same pattern as existing Vegas/opponent enrichment in worker). Feature store extension is future optimization.

### Step 1: Create CatBoostV12 Prediction System

**New file:** `predictions/worker/prediction_systems/catboost_v12.py`

Reference files:
- `predictions/worker/prediction_systems/catboost_v9.py` — model loading pattern
- `predictions/worker/prediction_systems/catboost_v8.py` — feature vector construction (lines 691-795)
- `predictions/worker/prediction_systems/catboost_monthly.py` — shadow model pattern
- `ml/experiments/quick_retrain.py` lines 596-966 — V12 augmentation SQL + computation logic to port

Key requirements:
- `SYSTEM_ID = "catboost_v12"`
- Loads model from `CATBOOST_V12_MODEL_PATH` env var (fallback to GCS)
- Builds **50-feature vector** (54 V12 features minus 4 vegas) using name-based extraction
- Batch-loads V12 features from UPCG + player_game_summary, caches per game_date
- Features 0-38 from feature store (skip 25-28 vegas)
- Features 39-53 from batch augmentation queries

V12 augmentation sources:
| Index | Feature | Source | Notes |
|-------|---------|--------|-------|
| 39 | days_rest | UPCG | From upcoming_player_game_context |
| 40 | minutes_load_last_7d | UPCG | minutes_in_last_7_days |
| 41 | spread_magnitude | UPCG | abs(game_spread) — **DEAD (0% importance, default 5.0)** |
| 42 | implied_team_total | UPCG | (total ± spread)/2 — **DEAD (0%, default 112.0)** |
| 43 | points_avg_last_3 | player_game_summary rolling | avg last 3 games |
| 44 | scoring_trend_slope | player_game_summary rolling | OLS slope last 7 games |
| 45 | deviation_from_avg_last3 | derived | (avg_L3 - season_avg) / std |
| 46 | consecutive_games_below_avg | player_game_summary | cold streak counter |
| 47 | teammate_usage_available | N/A | **DEAD — always 0.0** |
| 48 | usage_rate_last_5 | player_game_summary rolling | avg usage last 5 |
| 49 | games_since_structural_change | derived | team change / gap detection |
| 50 | multi_book_line_std | N/A | **DEAD — default 0.5** |
| 51 | prop_over_streak | UPCG | consecutive games over prop |
| 52 | prop_under_streak | UPCG | consecutive games under prop |
| 53 | line_vs_season_avg | derived | vegas_line - points_avg_season (**3rd most important feature, 7-11%**) |

For feature 53 (line_vs_season_avg) at inference: use `line_value` (betting line from coordinator) minus `features['points_avg_season']` (feature 2 from store).

### Step 2: Update Feature Contract

**File:** `shared/ml/feature_contract.py`
- Add `V12_NOVEG_FEATURE_NAMES` (50 features = V12 minus indices 25-28)
- Add `V12_NOVEG_CONTRACT` (ModelFeatureContract with feature_count=50)
- Update `FEATURES_OPTIONAL` to include dead V12 features: `{38, 41, 42, 47, 50, 51, 52, 53}`

### Step 3: Wire into Worker

**File:** `predictions/worker/worker.py`
- Add V12 import and lazy-load (inside try/except so failure doesn't break V9)
- Add V12 dispatch block after monthly models section
- V12 runs in shadow mode alongside V9 champion

### Step 4: Upload Model + Deploy

```bash
# Upload model to GCS
gsutil cp models/catboost_v9_50f_noveg_train20251102-20260131_20260212_234326.cbm \
  gs://nba-props-platform-models/catboost/v12/catboost_v12_50f_noveg_train20251102-20260131.cbm

# Set env var (NEVER --set-env-vars, ALWAYS --update-env-vars)
gcloud run services update prediction-worker --region=us-west2 \
  --update-env-vars="CATBOOST_V12_MODEL_PATH=gs://nba-props-platform-models/catboost/v12/catboost_v12_50f_noveg_train20251102-20260131.cbm"

# Push to main (auto-deploys)
git add predictions/worker/prediction_systems/catboost_v12.py shared/ml/feature_contract.py predictions/worker/worker.py
git commit -m "feat: add CatBoost V12 prediction system (shadow mode)"
git push origin main
```

### Step 5: Shadow Monitor (5+ game days)

```sql
-- V12 shadow grading check
SELECT game_date, COUNT(*) as total,
  COUNTIF(prediction_correct = TRUE AND ABS(predicted_points - line_value) >= 3) as edge3_correct,
  COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_total,
  ROUND(100.0 * COUNTIF(prediction_correct = TRUE AND ABS(predicted_points - line_value) >= 3) /
    NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v12' AND game_date >= CURRENT_DATE() - 7
GROUP BY 1 ORDER BY 1 DESC;
```

### Step 6: Subset Definitions (after shadow validation)

Based on segmented analysis (Jan 2026, edge >= 3):
- **OVER: 84.1%** vs UNDER: 69.4% → Create OVER-preferred subsets
- **Edge [5-7): 89%**, [7+): 91% → Create premium edge subset
- **Starters OVER: 87.8%** → Best single segment

Proposed subsets (insert into `dynamic_subset_definitions`):
1. `v12_over_edge_3` — OVER picks, edge >= 3
2. `v12_premium` — edge >= 5, any direction
3. `v12_all_edge_3` — all picks edge >= 3

### Step 7: Promote (after shadow passes)

- Update `CHAMPION_SYSTEM_ID` in `data_processors/publishing/subset_materializer.py`
- Update `tonight_player_exporter.py` system_id query
- Update `best_bets_exporter.py` system_id
- Update CLAUDE.md model section

## Multi-Book Line Std Coverage

User noted we should have multiple books from BettingPros + Odds API. Current coverage:
- Oct-Jan: Only 2 distinct bookmakers in odds_api_player_points_props → can't compute std
- Feb 2026: 5 bookmakers, 249 player-games with 3+ books

The multi_book_line_std feature (index 50) had 0% importance in V12 training because there was no data. As more books become available, this could become useful in future retrains. For now it defaults to 0.5.

**Check BettingPros coverage too** — the user says we should have multiple books from both sources. Investigate:
```sql
SELECT FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(DISTINCT bookmaker) as distinct_books,
  COUNT(*) as total_rows
FROM nba_raw.bettingpros_player_points_props
WHERE game_date >= '2025-10-22'
GROUP BY 1 ORDER BY 1;
```

## Training Data Strategy

- **Standard window:** 2025-11-02 to latest (rolling end date for monthly retrains)
- **Retrain command:** `PYTHONPATH=. python ml/experiments/quick_retrain.py --name "V12_MONTHLY" --feature-set v12 --no-vegas --train-start 2025-11-02 --train-end YYYY-MM-DD --walkforward --force`
- **Governance gates:** All existing gates apply (edge 3+ HR >= 60%, vegas bias, tier bias, sample size)

## Files Created This Session

| File | Purpose |
|------|---------|
| `ml/experiments/edge_classifier.py` | Phase 2 edge classifier experiment (negative result) |
| `docs/08-projects/current/model-improvement-analysis/23-PHASE2-EDGE-CLASSIFIER-RESULTS.md` | Full results documentation |
| `docs/09-handoff/2026-02-13-SESSION-230-HANDOFF.md` | Session handoff |

## Key Lessons from This Session

1. **NEVER use in-sample predictions as training data for a downstream model** — causes 88% hit rate inflation. Always use out-of-fold (OOF) temporal cross-validation.
2. **Edge Classifier (Model 2) doesn't work** — pre-game features can't discriminate winning from losing edges (AUC < 0.50). Edge outcomes are dominated by game-specific noise.
3. **Simple rules beat ML filtering** — OVER picks (84% HR), higher edge thresholds ([7+): 91%), and Model 1 alone outperform any Model 2 filtering.
