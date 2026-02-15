# Subset Redesign Plan — Session 253

## Problem

25 active subsets create confusion for website users. Too many choices, fragmented records, and no single source of truth for "how is the system performing?"

Additionally, every subset collapsed in Feb because the underlying champion model decayed:

```
Subset           Jan HR    Feb HR    Collapse
Top 3            88.5%     27.3%     -61.2pp
Top Pick         81.8%     25.0%     -56.8pp
Green Light      85.5%     41.7%     -43.8pp
Top 5            85.0%     44.4%     -40.6pp
High Edge All    80.5%     46.2%     -34.3pp
Ultra High Edge  85.7%     61.1%     -24.6pp
All Picks        65.8%     44.4%     -21.4pp
```

The subset logic is fine. The model underneath broke from staleness.

---

## New Subset Architecture

### Tier 1: "Best Bets" Meta-Subset (Primary — what the website tracks)

**Purpose:** Single, curated subset. 3-5 picks per day. One clean W/L record.

**Selection logic (picks qualify if ANY source fires):**

| Source | Rule | Tag |
|--------|------|-----|
| `high_edge` | Primary model edge 5+ | Best single-model picks |
| `dual_agree` | Both E and C models agree on direction at edge 3+ | Cross-model validation |
| `3pt_bounce` | 3PT% mean-reversion signal + model agrees on OVER | Shooting regression |

**Daily cap:** Top 5 by combined confidence score. If fewer than 3 qualify, show fewer (don't dilute with weak picks).

**Provenance tracking:** Each pick stores `source_tag` (which rule qualified it) and `source_models` (which model(s) contributed). This lets us analyze which sources are performing.

**Historical record display:**
```
Best Bets: 75-30 (71.4%) | +38.2 units | Since Feb 21
Source breakdown: high_edge 40-15 (72.7%), dual_agree 25-8 (75.8%), 3pt_bounce 10-7 (58.8%)
```

### Tier 2: Model-Level Subsets (for power users / internal monitoring)

| Subset | Definition | Purpose |
|--------|-----------|---------|
| **All Picks** | Primary model edge 3+ | Broadest profitable set |
| **High Confidence** | Primary model edge 5+ | Also feeds Best Bets |

### Retire

Everything else: Top 3, Top 5, Top Pick, Green Light, all Nova *, Q43 *, Q45 * subsets. These served their purpose during experimentation but create noise now.

---

## 3PT% Bounce-Back Signal Design

### Concept

Players who shot significantly below their season 3PT average in recent games tend to regress toward their mean. When the model also predicts OVER for that player, it's a high-confidence play.

### Detection Logic

```python
# Pseudocode
season_3pt_pct = player.three_point_pct_season  # e.g., 0.380
recent_3pt_pct = player.three_point_pct_last_3_games  # e.g., 0.250
season_3pt_std = player.three_point_pct_std_season  # e.g., 0.08

# Trigger conditions
z_score = (recent_3pt_pct - season_3pt_pct) / season_3pt_std
is_cold = z_score < -1.0  # More than 1 std dev below mean
has_volume = player.three_point_attempts_per_game >= 4  # Needs to be a regular shooter
model_says_over = primary_model.recommendation == 'OVER'
model_has_edge = primary_model.edge >= 2.0  # Lower edge threshold since signal adds confidence

qualifies = is_cold and has_volume and model_says_over and model_has_edge
```

### Data Sources

V13 features already include 3PT% data:
- `fg3_pct_last_3` (feature 45) — rolling 3PT% last 3 games
- `fg3_pct_std_last_5` (feature 49) — 3PT% standard deviation
- `three_pa_avg_last_3` (feature 50) — 3-point attempts volume

Season 3PT% would need to be pulled from player_game_summary or added as a new feature.

### Where It Fits

This signal feeds into the "Best Bets" meta-subset as a `source: "3pt_bounce"` pick. It doesn't need its own model — it uses the existing primary model prediction plus a shooting regression signal.

### Implementation Steps

1. Build `detect_3pt_bounce(player_lookup, game_date)` function in `shared/ml/`
2. Integrate into the Best Bets selection logic (Phase 5 or Phase 6)
3. Store `source_tag = "3pt_bounce"` in pick metadata
4. Backtest on W1-W4 to validate signal strength before deploying

---

## "Best Bets" Implementation Plan

### Schema Addition

Add to `dynamic_subset_definitions`:
```sql
INSERT INTO nba_predictions.dynamic_subset_definitions
(subset_name, subset_description, system_id, min_edge, is_active)
VALUES
('Best Bets', 'Curated meta-subset: top 3-5 daily picks from high_edge, dual_agree, and 3pt_bounce sources', 'meta', 5.0, TRUE)
```

### New Table: `best_bets_picks`

```sql
CREATE TABLE nba_predictions.best_bets_picks (
  game_date DATE,
  player_lookup STRING,
  recommendation STRING,  -- OVER/UNDER
  predicted_points FLOAT64,
  line_value FLOAT64,
  edge FLOAT64,
  source_tag STRING,  -- 'high_edge', 'dual_agree', '3pt_bounce'
  source_models ARRAY<STRING>,  -- ['catboost_v9_...', 'catboost_v12_...']
  confidence_rank INT64,  -- 1-5 for daily ordering
  actual_points FLOAT64,  -- filled after grading
  prediction_correct BOOL,  -- filled after grading
  created_at TIMESTAMP
)
PARTITION BY game_date;
```

### Integration Points

1. **Phase 5 (predictions):** After both models run, a new step evaluates Best Bets criteria
2. **Phase 6 (export):** Best Bets exported to `v1/best-bets/{date}.json` (endpoint already exists)
3. **Grading:** Post-grading export updates Best Bets with actuals
4. **Website:** Consumes `best-bets` endpoint, displays single W/L record + source breakdown

### Rollout

1. Implement after ASB retrain (Feb 18)
2. Shadow alongside old subsets for 1 week (Feb 19-25)
3. If Best Bets HR > 60%, switch website to display it as primary
4. Retire old subsets from website (keep in BQ for historical analysis)

---

## Production Model Cleanup

### Current State (18 models producing predictions — too many)

| Model | Status | Action |
|-------|--------|--------|
| `catboost_v9` | Champion, 40.6% HR Feb | **Replace** after ASB retrain |
| `catboost_v8` | Legacy, 45.6% HR Feb | **Disable** |
| `catboost_v12` | Nova, 56.0% HR Feb | **Replace** with fresh V12 RSM50 |
| `ensemble_v1` / `ensemble_v1_1` | Ensemble, 46-47% | **Disable** |
| `moving_average` / `moving_average_baseline_v1` | Baseline, 47% | **Disable** |
| `zone_matchup_v1` | Zone, 52.5% | **Disable** |
| `similarity_balanced_v1` | Similarity, 40.3% | **Disable** |
| `xgboost_v1` | XGBoost, discontinued | **Disable** |
| `catboost_v9_2026_02` | Feb retrain, 30% | **Disable** (bad retrain) |
| `catboost_v9_train*` | Shadow challengers | **Disable** old ones |
| `catboost_v9_q43/q45*` | Quantile shadows | **Disable** |

### Target State (3 models)

1. **Primary (Config E):** `catboost_v9_train1102_0213` — V9 33f MAE, sniper
2. **Secondary (Config C):** `catboost_v12_rsm50_train1102_0213` — V12 50f MAE RSM50 no-vegas, workhorse
3. **Legacy (read-only):** `catboost_v9` — keep for historical comparison, stop predicting
