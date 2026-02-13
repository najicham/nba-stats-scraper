# Testing Plan: V2 Model Architecture

**Date:** 2026-02-13 (Session 227)
**Status:** Active — executing
**Companion doc:** `17-FINAL-EXECUTION-PLAN.md`

---

## Evaluation Windows (Used for ALL Experiments)

Every experiment is evaluated on all 4 windows. Results aggregated.

| Window | Train Period | Eval Period | Purpose | Notes |
|--------|-------------|-------------|---------|-------|
| **Feb 2025** | 2024-11-02 to 2025-01-31 | 2025-02-01 to 2025-02-28 | Known-good benchmark | Uses DK lines (pre-production) |
| **Dec 2025** | 2025-10-22 to 2025-11-30 | 2025-12-01 to 2025-12-31 | Early season baseline | Shorter training (40d) |
| **Jan 2026** | 2025-10-22 to 2025-12-31 | 2026-01-01 to 2026-01-31 | Pre-decay validation | ~70d training |
| **Feb 2026** | 2025-11-02 to 2026-01-31 | 2026-02-01 to 2026-02-12 | Problem period | Uses production lines |

**Convention:** Append `_FEB25`, `_DEC25`, `_JAN26`, `_FEB26` to experiment names.

**Standard flags for all experiments:**
```bash
--walkforward --force --skip-register
```

---

## Phase 0: Diagnostics (BQ Queries)

Run these 6 queries in BigQuery. Each answers a specific question.

### Query 0: Actual OVER/UNDER Outcome Rates by Month

**Question:** Was Feb 2025 genuinely UNDER-favorable (explaining why Q43 worked)?

```sql
SELECT
  FORMAT_DATE('%Y-%m', pa.game_date) as month,
  COUNT(*) as total_picks,
  COUNTIF(pa.actual_points > pa.line_value) as actual_overs,
  COUNTIF(pa.actual_points < pa.line_value) as actual_unders,
  COUNTIF(pa.actual_points = pa.line_value) as pushes,
  ROUND(100.0 * COUNTIF(pa.actual_points > pa.line_value) / NULLIF(COUNT(*), 0), 1) as pct_actual_over,
  ROUND(100.0 * COUNTIF(pa.actual_points < pa.line_value) / NULLIF(COUNT(*), 0), 1) as pct_actual_under
FROM nba_predictions.prediction_accuracy pa
WHERE pa.game_date BETWEEN '2024-10-22' AND '2026-02-12'
  AND pa.is_voided = FALSE
  AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
GROUP BY 1
ORDER BY 1
```

**Decision gate:**
- If Feb 2025 had >55% UNDER outcomes: Q43 accidentally aligned with market bias. Vegas-free + MAE is correct.
- If Feb 2025 was ~50/50: Q43's edge came from something else (model accuracy, not directional bias).

### Query 1: Vegas Line Sharpness Comparison

**Question:** Has Vegas gotten significantly more accurate, shrinking the edge pool?

```sql
SELECT
  FORMAT_DATE('%Y-%m', pgs.game_date) as month,
  COUNT(*) as n_players,
  ROUND(AVG(ABS(pgs.points - oap.line)), 2) as vegas_mae,
  ROUND(STDDEV(pgs.points - oap.line), 2) as vegas_std,
  ROUND(AVG(pgs.points - oap.line), 2) as vegas_bias
FROM nba_analytics.player_game_summary pgs
JOIN (
  SELECT player_lookup, game_date, line,
    ROW_NUMBER() OVER (PARTITION BY player_lookup, game_date ORDER BY processed_at DESC) as rn
  FROM nba_raw.odds_api_player_points_props
  WHERE sportsbook = 'draftkings'
    AND game_date BETWEEN '2024-10-22' AND '2026-02-12'
) oap ON pgs.player_lookup = oap.player_lookup
  AND pgs.game_date = oap.game_date
  AND oap.rn = 1
WHERE pgs.game_date BETWEEN '2024-10-22' AND '2026-02-12'
  AND pgs.points IS NOT NULL
GROUP BY 1
ORDER BY 1
```

**Decision gate:**
- Vegas MAE dropped >1.0 from Feb 2025 to Feb 2026: Edge pool genuinely smaller. Target 53-55%.
- Vegas MAE stable (~5.0-5.5 both periods): Edges still exist. Current model just can't find them.

### Query 2: Trade Deadline Impact

**Question:** What % of Feb 2026 misses involve recently traded or roster-disrupted players?

```sql
-- First identify players with team changes
WITH player_teams AS (
  SELECT
    player_lookup,
    game_date,
    team_tricode,
    LAG(team_tricode) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_team
  FROM nba_analytics.player_game_summary
  WHERE game_date BETWEEN '2025-01-01' AND '2026-02-12'
    AND team_tricode IS NOT NULL
),
traded_players AS (
  SELECT DISTINCT player_lookup,
    MIN(game_date) as trade_date
  FROM player_teams
  WHERE prev_team IS NOT NULL AND team_tricode != prev_team
    AND game_date BETWEEN '2026-01-15' AND '2026-02-12'
  GROUP BY player_lookup
),
feb_predictions AS (
  SELECT pa.*,
    CASE WHEN tp.player_lookup IS NOT NULL THEN 'traded' ELSE 'stable' END as roster_status
  FROM nba_predictions.prediction_accuracy pa
  LEFT JOIN traded_players tp ON pa.player_lookup = tp.player_lookup
  WHERE pa.game_date BETWEEN '2026-02-01' AND '2026-02-12'
    AND pa.is_voided = FALSE
    AND ABS(pa.predicted_margin) >= 3
)
SELECT
  roster_status,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM feb_predictions
GROUP BY 1
```

**Decision gate:**
- Stable-roster HR > 55%: Trade deadline is the primary problem. Fast-track structural break features.
- Stable-roster HR ~ 50%: Problem is deeper than trade disruption.

### Query 3: Miss Clustering by Player Tier and Direction

**Question:** Are misses uniform or concentrated in specific player types?

```sql
WITH player_tiers AS (
  SELECT player_lookup,
    AVG(points) as season_avg,
    CASE
      WHEN AVG(points) >= 25 THEN 'star_25plus'
      WHEN AVG(points) >= 15 THEN 'mid_15_25'
      WHEN AVG(points) >= 8 THEN 'role_8_15'
      ELSE 'bench_under8'
    END as tier
  FROM nba_analytics.player_game_summary
  WHERE game_date BETWEEN '2025-10-22' AND '2026-01-31'
  GROUP BY player_lookup
)
SELECT
  pt.tier,
  pa.recommendation as direction,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(pa.signed_error)), 2) as mae
FROM nba_predictions.prediction_accuracy pa
JOIN player_tiers pt ON pa.player_lookup = pt.player_lookup
WHERE pa.game_date BETWEEN '2026-02-01' AND '2026-02-12'
  AND pa.is_voided = FALSE
  AND ABS(pa.predicted_margin) >= 3
GROUP BY 1, 2
ORDER BY 1, 2
```

**Decision gate:**
- Stars dominate misses: Consider tier filtering (only bet mid/role).
- Misses uniform: Problem is architectural, not tier-specific.
- OVER misses cluster in one tier: Q43 bias affects some tiers more than others.

### Query 4: OVER/UNDER Prediction Distribution

**Question:** How does the model's edge distribution differ between Feb 2025 and Feb 2026?

```sql
-- Compare prediction edge distributions
SELECT
  CASE
    WHEN pa.game_date BETWEEN '2025-02-01' AND '2025-02-28' THEN 'feb_2025'
    WHEN pa.game_date BETWEEN '2026-02-01' AND '2026-02-12' THEN 'feb_2026'
  END as period,
  COUNT(*) as total_picks,
  ROUND(AVG(pa.predicted_points - pa.line_value), 2) as avg_edge,
  ROUND(STDDEV(pa.predicted_points - pa.line_value), 2) as std_edge,
  COUNTIF(pa.predicted_points > pa.line_value) as over_picks,
  COUNTIF(pa.predicted_points < pa.line_value) as under_picks,
  ROUND(100.0 * COUNTIF(pa.predicted_points > pa.line_value) / COUNT(*), 1) as pct_over_picks,
  -- Edge size buckets
  COUNTIF(ABS(pa.predicted_points - pa.line_value) >= 3) as edge_3plus,
  COUNTIF(ABS(pa.predicted_points - pa.line_value) >= 5) as edge_5plus
FROM nba_predictions.prediction_accuracy pa
WHERE (pa.game_date BETWEEN '2025-02-01' AND '2025-02-28'
   OR pa.game_date BETWEEN '2026-02-01' AND '2026-02-12')
  AND pa.is_voided = FALSE
GROUP BY 1
ORDER BY 1
```

**Decision gate:**
- Feb 2026 avg_edge is strongly negative (< -2): Q43 pulling everything under. Confirms MAE loss fix.
- Feb 2026 has near-zero OVER picks: Same — Q43 artifact.
- Feb 2025 had balanced edges: OVER collapse is new to Feb 2026 model, not inherent.

### Query 5: Feature Drift Detection

**Question:** Have key feature distributions shifted between training and eval?

```sql
WITH train_stats AS (
  SELECT
    'train' as period,
    AVG(CAST(JSON_VALUE(features_snapshot, '$.points_avg_last_5') AS FLOAT64)) as avg_pts_l5,
    STDDEV(CAST(JSON_VALUE(features_snapshot, '$.points_avg_last_5') AS FLOAT64)) as std_pts_l5,
    AVG(CAST(JSON_VALUE(features_snapshot, '$.vegas_points_line') AS FLOAT64)) as avg_vegas,
    STDDEV(CAST(JSON_VALUE(features_snapshot, '$.vegas_points_line') AS FLOAT64)) as std_vegas,
    AVG(CAST(JSON_VALUE(features_snapshot, '$.opponent_def_rating') AS FLOAT64)) as avg_opp_def,
    AVG(CAST(JSON_VALUE(features_snapshot, '$.minutes_avg_last_10') AS FLOAT64)) as avg_mins
  FROM nba_predictions.player_prop_predictions
  WHERE game_date BETWEEN '2025-11-02' AND '2026-01-31'
    AND system_id = 'catboost_v9'
    AND is_active = TRUE
),
eval_stats AS (
  SELECT
    'eval' as period,
    AVG(CAST(JSON_VALUE(features_snapshot, '$.points_avg_last_5') AS FLOAT64)) as avg_pts_l5,
    STDDEV(CAST(JSON_VALUE(features_snapshot, '$.points_avg_last_5') AS FLOAT64)) as std_pts_l5,
    AVG(CAST(JSON_VALUE(features_snapshot, '$.vegas_points_line') AS FLOAT64)) as avg_vegas,
    STDDEV(CAST(JSON_VALUE(features_snapshot, '$.vegas_points_line') AS FLOAT64)) as std_vegas,
    AVG(CAST(JSON_VALUE(features_snapshot, '$.opponent_def_rating') AS FLOAT64)) as avg_opp_def,
    AVG(CAST(JSON_VALUE(features_snapshot, '$.minutes_avg_last_10') AS FLOAT64)) as avg_mins
  FROM nba_predictions.player_prop_predictions
  WHERE game_date BETWEEN '2026-02-01' AND '2026-02-12'
    AND system_id = 'catboost_v9'
    AND is_active = TRUE
)
SELECT * FROM train_stats
UNION ALL
SELECT * FROM eval_stats
```

**Decision gate:**
- Large drift in rolling averages (>1 std): Structural break contamination. Prioritize games_since_structural_change feature.
- Drift in Vegas lines but not player stats: Market shifted, not player behavior. Confirms Vegas-free approach.

---

## Phase 1A: Quick Vegas-Free Baseline

**Run 4 experiments (one per eval window) in parallel.**

```bash
# Feb 2026 (primary)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VF_BASE_FEB26" \
    --no-vegas --loss-function MAE \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force --skip-register

# Feb 2025 (benchmark)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VF_BASE_FEB25" \
    --no-vegas --loss-function MAE \
    --train-start 2024-11-02 --train-end 2025-01-31 \
    --eval-start 2025-02-01 --eval-end 2025-02-28 \
    --walkforward --force --skip-register

# Jan 2026
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VF_BASE_JAN26" \
    --no-vegas --loss-function MAE \
    --train-start 2025-10-22 --train-end 2025-12-31 \
    --eval-start 2026-01-01 --eval-end 2026-01-31 \
    --walkforward --force --skip-register

# Dec 2025
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VF_BASE_DEC25" \
    --no-vegas --loss-function MAE \
    --train-start 2025-10-22 --train-end 2025-11-30 \
    --eval-start 2025-12-01 --eval-end 2025-12-31 \
    --walkforward --force --skip-register
```

### What to Measure

| Metric | How | Success Threshold |
|--------|-----|-------------------|
| Edge 3+ HR | Walk-forward output | > 52% on Feb 2026, > 60% on Feb 2025 |
| Edge 3+ N | Count of picks with \|edge\| >= 3 | > 30 per window |
| OVER pick % | % of edge 3+ picks that are OVER | > 10% (proof OVER collapse is fixed) |
| OVER HR | Hit rate on OVER picks | > 45% |
| UNDER HR | Hit rate on UNDER picks | > 45% |
| MAE | Mean absolute error | < 6.0 |
| Vegas bias | avg(pred - vegas_line) | Within +/- 1.5 |
| Top feature | #1 feature importance | Should NOT be a single feature > 25% |

### Decision Gate After Phase 1A

| Result | Decision |
|--------|----------|
| Feb 2025 HR > 60% AND Feb 2026 HR > 50% | **PROCEED** to Phase 1B (add features) |
| Feb 2025 HR > 60% BUT Feb 2026 HR < 50% | **PROCEED** but expect Feb 2026 is hard; focus on new features to help |
| Feb 2025 HR < 55% | **PAUSE** — Vegas-free model can't predict points well enough alone. Re-examine feature set before continuing. |
| OVER picks still < 5% | **INVESTIGATE** — MAE loss should have fixed this. Check if model is still implicitly biased. |
| All 4 windows > 55% | **STRONG PROCEED** — Architecture is validated. Fast-track to Phase 1B-D. |

### Also Run: Training Window Comparison

Test whether longer training helps the Vegas-free model (hypothesis: basketball patterns are more stable than Vegas calibration, so more data helps).

```bash
# 180-day training (vs default 90-day) on Feb 2026
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VF_BASE_180D_FEB26" \
    --no-vegas --loss-function MAE \
    --train-start 2025-08-01 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force --skip-register

# Season-to-date training on Feb 2026
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VF_BASE_STD_FEB26" \
    --no-vegas --loss-function MAE \
    --train-start 2025-10-22 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force --skip-register
```

### Also Run: Loss Function Comparison

Test MAE vs Huber (recommended by 2 of 3 reviews).

```bash
# Huber loss (robust to outliers)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VF_HUBER_FEB26" \
    --no-vegas --loss-function "Huber:delta=4" \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force --skip-register
```

---

## Phase 1B: P0 New Features

**Only after Phase 1A gate passes.**

### Feature Implementation

Each new feature needs:
1. A BQ query to compute it from existing tables
2. An augmentation function (like `augment_v11_features`) to inject at training time
3. A feature name added to a custom contract

**Features to add:**

```
days_since_last_game     — DATE_DIFF(game_date, previous game_date, DAY)
scoring_trend_slope      — OLS regression slope of points over last 7 games
minutes_load_last_7d     — SUM(minutes) for games in last 7 days
deviation_from_avg_last3 — (AVG(points, last 3 games) - season_avg) / points_std
```

**Implementation pattern (extend augment_v11_features):**

```python
def augment_new_features(client, df):
    """Augment with P0 features from game logs."""
    query = """
    WITH game_data AS (
      SELECT player_lookup, game_date, points, minutes,
        LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_game_date,
        AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date
          ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) as avg_last_3,
        AVG(points) OVER (PARTITION BY player_lookup ORDER BY game_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as season_avg_prior,
        STDDEV(points) OVER (PARTITION BY player_lookup ORDER BY game_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as season_std_prior
      FROM nba_analytics.player_game_summary
      WHERE game_date BETWEEN '{min_date}' AND '{max_date}'
    )
    SELECT player_lookup, game_date,
      DATE_DIFF(game_date, prev_game_date, DAY) as days_since_last_game,
      -- minutes_load_last_7d computed separately
      SAFE_DIVIDE(avg_last_3 - season_avg_prior, NULLIF(season_std_prior, 0)) as deviation_from_avg_last3
    FROM game_data
    """
    # ... inject into features arrays
```

### Experiments (Phase 1B)

Run with augmented features on all 4 windows. Compare to Phase 1A baseline.

```bash
# After implementing augment_new_features:
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VF_P0_FEB26" \
    --no-vegas --loss-function MAE \
    --feature-set v12 \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force --skip-register
# ... repeat for FEB25, DEC25, JAN26
```

### What to Measure (vs Phase 1A baseline)

| Metric | Compare To | Keep Features If... |
|--------|-----------|---------------------|
| Edge 3+ HR | Phase 1A same window | Improved or flat |
| MAE | Phase 1A | Improved or within 0.1 |
| New feature importance | N/A | > 1% for at least 2 of 4 features |
| Walk-forward stability | Phase 1A | No week-to-week degradation |

### Decision Gate After Phase 1B

| Result | Decision |
|--------|----------|
| 2+ new features > 1% importance, HR improved | **KEEP all** — proceed to Phase 1C |
| 1 feature useful, others dead | **KEEP useful one**, drop dead ones, proceed |
| No new features > 1% | **DROP all P0 features**. Proceed to Phase 1C (game environment may be different) |

---

## Phase 1C: P1 New Features

Same pattern. Add:
```
game_total_line          — From odds_api (already in V11, use augment_v11_features)
implied_team_total       — (game_total +/- spread) / 2
spread_magnitude         — abs(point spread)
teammate_usage_available — SUM(usage_rate) for OUT teammates
```

**Hard decision gate for game_total_line:** If it shows <1% importance in this Vegas-free context (as it did in V11), drop ALL game-total-derived features and don't revisit.

---

## Phase 1D: P2 New Features

Add:
```
games_since_structural_change  — Games since trade/ASB/return
consecutive_games_below_avg    — Streak of games under own season avg
```

### Full Model 1 Evaluation After Phase 1D

After all feature batches, run the full Model 1 with best features on all 4 windows.

**Results table to fill:**

| Window | Phase 1A HR | Phase 1B HR | Phase 1C HR | Phase 1D HR | Final HR | N |
|--------|------------|------------|------------|------------|----------|---|
| Feb 2025 | | | | | | |
| Dec 2025 | | | | | | |
| Jan 2026 | | | | | | |
| Feb 2026 | | | | | | |

### Decision Gate After Phase 1D (Model 1 Complete)

| Result | Decision |
|--------|----------|
| Avg HR across 4 windows > 55%, balanced OVER/UNDER | **PROCEED** to Phase 2 (Model 2) |
| Avg HR 52-55% | **PROCEED** cautiously — Model 2 might push it over |
| Avg HR < 52% | **STOP** — Model 1 alone isn't finding enough edge. Investigate why before building Model 2. |
| Feb 2025 > 65% but Feb 2026 < 50% | Model 1 works but Feb 2026 is uniquely hard. **PROCEED** — Model 2 may help filter bad bets |

---

## Phase 2: Edge Classifier (Model 2)

**Prerequisite:** Model 1 validated (avg HR > 52% across windows).

### Implementation

Add `--classification` mode to quick_retrain.py:
- Target: binary (did edge hit? 1/0)
- Loss: binary cross-entropy (CatBoost `Logloss`)
- Input: Only rows where Model 1 edge >= 2 points
- Features: edge_size, edge_direction, vegas_line_move, line_vs_season_avg, player_volatility, game_total_line, etc.

**Or:** Use sklearn LogisticRegression first (simpler, interpretable), upgrade to CatBoost if needed.

### Experiments

```bash
# Train Model 2 on Model 1's backtested edges
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EDGE_CLF_FEB26" \
    --classification \
    --model1-path models/VF_BEST_FEB26.cbm \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force --skip-register
```

### What to Measure

| Metric | Success Threshold |
|--------|-------------------|
| AUC-ROC | > 0.55 (better than random) |
| Precision at confidence >= 0.6 | > 55% |
| Model 1 alone HR vs Model 1+2 HR | Model 1+2 >= Model 1 alone |
| Volume (Model 1+2 picks/day) | >= 3 |

### Decision Gate After Phase 2

| Result | Decision |
|--------|----------|
| Model 1+2 HR > Model 1 alone by 2+ pp | **KEEP Model 2** — proceed to Phase 3 integration |
| Model 1+2 HR ~ Model 1 alone | **Model 2 adds no value** — just use Model 1 with threshold |
| Model 1+2 HR < Model 1 alone | **Model 2 is hurting** — drop it, use Model 1 only |

---

## Phase 3: Full Integration Backtest

Wire final Models 1+2 together. Run on all 4 windows.

### Final Results Table

| Window | Model 1 HR | Model 1+2 HR | N (1+2) | OVER HR | UNDER HR | MAE | Daily Volume |
|--------|-----------|-------------|---------|---------|----------|-----|-------------|
| Feb 2025 | | | | | | | |
| Dec 2025 | | | | | | | |
| Jan 2026 | | | | | | | |
| Feb 2026 | | | | | | | |
| **Average** | | | | | | | |

### Final Go/No-Go Criteria

| Metric | Minimum | Target |
|--------|---------|--------|
| Avg edge 3+ HR (4 windows) | 55% | 58% |
| All windows > breakeven (52.4%) | Required | -- |
| OVER HR (avg) | 50% | 55% |
| UNDER HR (avg) | 50% | 55% |
| Total N across 4 windows | > 400 | > 600 |
| Avg daily volume | > 3 | > 5 |

**If minimum criteria met:** Shadow deploy alongside decaying champion. Monitor 2+ weeks.
**If not met:** Review diagnostic insights, consider whether market is permanently tighter. Possible pivots: tier-specific models, reduced volume/higher threshold, or accept lower expectations.

---

## Parallel Experiments (Can Run Alongside Main Path)

These are independent experiments that don't block the main path.

### Dead Feature Ablation

Confirm the 5 dead features (injury_risk, back_to_back, playoff_game, rest_advantage, has_vegas_line) are truly dead in Vegas-free context:

```bash
# WITH dead features (baseline has them via V9 contract)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VF_WITH_DEAD_FEB26" \
    --no-vegas --loss-function MAE \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force --skip-register

# WITHOUT dead features
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VF_NO_DEAD_FEB26" \
    --no-vegas --loss-function MAE \
    --exclude-features "injury_risk,back_to_back,playoff_game,rest_advantage,has_vegas_line" \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force --skip-register
```

### Also Exclude Composites

The composite scores (fatigue_score, shot_zone_mismatch_score) are black boxes. Test removing them too:

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VF_LEAN_FEB26" \
    --no-vegas --loss-function MAE \
    --exclude-features "injury_risk,back_to_back,playoff_game,rest_advantage,has_vegas_line,fatigue_score,shot_zone_mismatch_score,pct_mid_range,recent_trend,minutes_change" \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12 \
    --walkforward --force --skip-register
```

---

## Experiment Tracking

All results tracked in this format:

```
| # | Name | Config | Feb25 HR | Dec25 HR | Jan26 HR | Feb26 HR | Avg HR | N(3+) | OVER% | Notes |
|---|------|--------|----------|----------|----------|----------|--------|-------|-------|-------|
| 0 | VF_BASE | no-vegas, MAE, 90d | | | | | | | | |
| 1 | VF_BASE_180D | no-vegas, MAE, 180d | | | | | | | | |
| 2 | VF_HUBER | no-vegas, Huber | | | | | | | | |
| 3 | VF_P0 | +4 P0 features | | | | | | | | |
| 4 | VF_P1 | +4 P1 features | | | | | | | | |
| 5 | VF_P2 | +2 P2 features | | | | | | | | |
| 6 | VF_NO_DEAD | -5 dead features | | | | | | | | |
| 7 | VF_LEAN | -10 pruned features | | | | | | | | |
| 8 | EDGE_CLF | Model 2 classifier | | | | | | | | |
| 9 | COMBINED | Model 1+2 pipeline | | | | | | | | |
```

---

## Order of Operations

```
Phase 0 (diagnostics)  ─────────────────────── ~30 min
  ├── 6 BQ queries (parallel)
  │
Phase 1A (baselines)   ─────────────────────── ~1 hour
  ├── VF_BASE × 4 windows (parallel)
  ├── VF_BASE_180D (parallel)
  ├── VF_BASE_STD (parallel)
  ├── VF_HUBER (parallel)
  ├── Dead feature ablation (parallel)
  │
  ├── DECISION GATE ──────────────────────────
  │
Phase 1B (P0 features) ─────────────────────── ~2-3 hours
  ├── Implement augment function
  ├── Train × 4 windows
  │
Phase 1C (P1 features) ─────────────────────── ~2-3 hours
  ├── Implement augment function
  ├── Train × 4 windows
  │
Phase 1D (P2 features) ─────────────────────── ~2-3 hours
  ├── Implement augment function
  ├── Train × 4 windows
  │
  ├── DECISION GATE (Model 1 complete) ───────
  │
Phase 2 (edge classifier) ──────────────────── ~1 day
  ├── Implement classification mode
  ├── Train Model 2
  ├── Evaluate combined pipeline
  │
  ├── DECISION GATE (Model 1+2 complete) ─────
  │
Phase 3 (integration) ──────────────────────── ~1 day
  ├── Full backtest × 4 windows
  ├── Final go/no-go decision
```
