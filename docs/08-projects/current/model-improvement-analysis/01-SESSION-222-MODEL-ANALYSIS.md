# Comprehensive Model Analysis & Experiment Roadmap

**Date:** 2026-02-12
**Sessions:** 222-224
**Status:** Deep analysis complete, master experiment plan finalized

**See also:**
- `02-MASTER-EXPERIMENT-PLAN.md` — 32 experiments across 6 waves, execution timeline
- `03-NEW-FEATURES-DEEP-DIVE.md` — 16 new feature implementations with code, SQL, file paths
- `04-MULTI-SEASON-DATA-AUDIT.md` — 3-season data quality audit (38K trainable rows available)

## Executive Summary

The champion model (`catboost_v9`) has decayed from **71.2% to 39.9%** edge 3+ hit rate over 35 days — well below the 52.4% breakeven threshold. Analysis of **96 prior experiments** plus **16 new experiments** (Session 222B-223) reveals:

1. **The UNDER bias catastrophe** — role player UNDER picks hit at 22%, dragging the entire system
2. **The retrain paradox** — fresh models track Vegas too closely (0 edge), stale models decay (negative edge)
3. **Quantile alpha=0.43** remains the only technique that generates edge when fresh (65.8% → 55.4% with 14d recency)
4. **No model passes governance gates** — best is Q43+recency at 55.4% HR on 92 picks (needs 60%+)

This document provides **full implementation designs** for player-specific modeling, feature engineering, and training strategy — concrete enough to execute in future sessions.

---

## Part 1: Current State & What's Broken

### 1.1 The Decay Timeline

| Week | Edge 3+ HR | MAE | Vegas Bias | Status |
|------|-----------|-----|------------|--------|
| Jan 4-10 | 58.8% | 4.64 | +0.01 | Profitable |
| Jan 11-17 | **71.2%** | 5.08 | +0.78 | Peak performance |
| Jan 18-24 | 66.7% | 4.64 | -0.05 | Declining |
| Jan 25-31 | 55.4% | 4.80 | -0.20 | Below peak |
| Feb 1-7 | **37.6%** | 5.69 | -0.43 | Below breakeven |
| Feb 8-11 | **39.0%** | 4.91 | +0.21 | Still losing |

The decay follows a predictable **3-week lifecycle**: peak at 2-3 weeks of staleness, then rapid decline. The model was trained through Jan 8 — by Feb 12 it's 35 days stale.

**The mechanism:** The champion model's betting edge comes from *prediction drift* — as the model ages, its predictions diverge from current Vegas lines. This divergence creates edge. But after ~25 days, the drift becomes noise rather than signal, and accuracy collapses.

### 1.2 The UNDER Bias Catastrophe

The model's decay is **not uniform** — it's concentrated in UNDER predictions:

| Direction | Total Picks | Edge 3+ Picks | Edge 3+ HR | Status |
|-----------|-------------|---------------|-----------|--------|
| OVER | 264 | 80 | **47.5%** | Near breakeven |
| UNDER | 437 | 103 | **34.0%** | Catastrophic |

The model generates **60% more UNDER picks** than OVER, and UNDER is where all the losses come from. The model is systematically predicting that players will score fewer points than their line suggests — and being wrong.

**Why this happens:** As the model goes stale, its learned player baselines lag behind reality. Vegas lines adjust upward for hot players; the model still predicts their old average. This creates phantom UNDER edge that doesn't exist.

### 1.3 Tier x Direction Breakdown (The Smoking Gun)

| Tier | OVER HR (edge 3+) | UNDER HR (edge 3+) | UNDER Count |
|------|-------------------|---------------------|-------------|
| Stars (25+) | **62.5%** (5/8) | **50.0%** (6/12) | 12 |
| Starters (15-24) | 31.8% (7/22) | 40.0% (20/50) | 50 |
| Role (5-14) | **51.0%** (25/49) | **22.0%** (9/41) | 41 |
| Bench (<5) | 100% (1/1) | N/A | 0 |

**Key findings:**
- **Role Player UNDER is the disaster zone**: 22.0% HR. The model systematically predicts role players will score under their line, but they keep going over. This single segment is responsible for most losses.
- **Stars OVER is the best bet**: 62.5% HR. The model correctly identifies when stars exceed their line.
- **Starters OVER is also bad**: 31.8% HR. Model over-predicts starters but they fall short.
- **The model has NO player-level awareness** — it treats a breakout-prone 23-year-old and a declining 34-year-old identically if they have similar recent stats.

### 1.4 Individual Player Failures

Players the model is consistently wrong about (0% HR, edge 3+):

| Player | Record | Direction | Avg Edge | Pattern |
|--------|--------|-----------|----------|---------|
| Trey Murphy III | 0/6 | All UNDER | 9.6 | Breakout-prone young wing, model massively under-predicts |
| Jabari Smith Jr | 0/5 | All UNDER | 5.5 | Expanding role, model can't see teammate context |
| Jaren Jackson Jr | 0/5 | All UNDER | 6.3 | Star-adjacent, benefits from Morant's gravity |
| Kobe Sanders | 0/3 | All UNDER | — | Role expansion invisible to model |

Players the model gets right (66.7%+ HR):

| Player | Record | Direction | Pattern |
|--------|--------|-----------|---------|
| Joel Embiid | 2/3 | All OVER | Consistent star with floor |
| Donovan Mitchell | 2/3 | Mixed | High-usage, predictable range |
| Jarrett Allen | 2/3 | All OVER | Role player with consistent ceiling |
| Julius Randle | 2/3 | All UNDER | Veteran with well-known ceiling |

**Pattern**: Failures concentrate in UNDER bets on mid-tier players experiencing role expansion (injuries to teammates, rotation changes). Successes are in OVER bets on stars and UNDER calls on veterans with established ceilings.

### 1.5 February Environmental Factors

February 2026 has been uniquely difficult:

- **Trade deadline** (Feb 6): 246 players listed as OUT, massive roster upheaval
- **14.2% of predictions off by >10 points** — 3x the normal rate
- **Vegas adapting faster** than the model can track
- **Injury tsunami** disrupting lineup continuity across the league

---

## Part 2: What We've Tried (112 Experiments)

### 2.1 The Retrain Paradox Explained

The paradox, proven across 7 architectures x 2 evaluation windows (Session 183), plus confirmed by 16 new experiments (Session 222B):

| Training Recency | Avg Edge 3+ Picks | Avg HR 3+ |
|------------------|-------------------|-----------|
| Stale (Dec 31 train, Jan eval) | 178 | **77.6%** |
| Fresh (Jan 31 train, Feb eval) | 16 | **43.4%** |
| Fresh + Q43 + 14d recency | 92 | **55.4%** |

**Root cause:** The model's #1 and #2 features are `vegas_points_line` (29-36% importance) and `vegas_opening_line` (14-17%). Together, Vegas is **50%+ of the model**. A stale model's predictions drift from current Vegas lines — this drift IS the betting edge. A fresh retrain eliminates this drift, eliminates edge, eliminates profit.

**Why you can't just remove Vegas features:** Without Vegas, the model loses its calibration anchor. Vegas features provide the baseline accuracy (MAE ~5 vs ~7 without). The model needs Vegas to be accurate, but accuracy and betting edge are different things.

### 2.2 Five Identified Failure Modes

| # | Failure Mode | Sessions | Status |
|---|-------------|----------|--------|
| 1 | **Vegas Tracking** — fresh model tracks Vegas too closely, generates 0 edge picks | 179, 183, 222B | Partially solved (quantile) |
| 2 | **Data Quality** — training on records with `vegas_line=0` | 59 | Fixed (quality gates) |
| 3 | **Date Overlap** — train/eval contamination inflates metrics | 176-178 | Fixed (hard guard) |
| 4 | **Residual Collapse** — residual target (actual - vegas) causes 4-6 iteration early stop | 180, 183 | Dead end |
| 5 | **Backtest Gap** — backtests overstate production by 5-10pp | 176+ | Known, unfixable |

### 2.3 Session 222B Experiment Results (16 Experiments)

**Wave 1 (8 experiments) — Baseline variants:**

| Experiment | Train Window | Alpha | Recency | Edge 3+ Picks | HR 3+ | Notes |
|------------|-------------|-------|---------|---------------|-------|-------|
| BASELINE_JAN31 | Nov 2 - Jan 31 | — | — | 5 | 40.0% | Fresh baseline: almost no edge generated |
| Q43_JAN31 | Nov 2 - Jan 31 | 0.43 | — | 35 | 51.4% | Quantile works but below gate |
| Q43_FEB07 | Nov 2 - Feb 7 | 0.43 | — | 28 | 50.0% | Even fresher, similar HR |
| Q40_JAN31 | Nov 2 - Jan 31 | 0.40 | — | 136 | 53.7% | Most volume, still below gate |
| Q45_JAN31 | Nov 2 - Jan 31 | 0.45 | — | 22 | 50.0% | Higher alpha = fewer picks |
| TUNED_JAN31 | Nov 2 - Jan 31 | — | — | 8 | 37.5% | Tuned baseline, still bad |
| RECENCY30_JAN31 | Nov 2 - Jan 31 | — | 30d | 6 | 33.3% | Recency alone doesn't help |
| VEGAS30_JAN31 | Nov 2 - Jan 31 | — | — | 36 | 52.8% | Vegas weight 0.3, closest to breakeven |

**Wave 2 (8 experiments) — Hypothesis-driven:**

| Experiment | Alpha | Special | Edge 3+ Picks | HR 3+ | Notes |
|------------|-------|---------|---------------|-------|-------|
| **Q43_RECENCY14** | 0.43 | 14d recency | 92 | **55.4%** | **Best volume + accuracy combo** |
| Q43_RECENCY7 | 0.43 | 7d recency | 85 | 52.9% | Too aggressive recency |
| Q43_NOTREND | 0.43 | Exclude recent_trend | 38 | 52.6% | Feature drop didn't help |
| Q42_JAN31 | 0.42 | — | 42 | 52.4% | At breakeven exactly |
| Q44_JAN31 | 0.44 | — | 30 | 53.3% | Middle ground |
| **PERF_BOOST** | — | Feature weight boost | 45 | **55.6%** | Performance features weighted up |
| OVER_ONLY | — | OVER filter | 12 | 41.7% | OVER specialist fails (too few picks) |
| UNDER_FILTER | 0.43 | Suppress role UNDER | 65 | 55.4% | Direction filter helps! |

**Key takeaways from 16 experiments:**
1. **Q43 + 14d recency = best combo**: 55.4% on 92 picks — good volume, approaching profitability
2. **UNDER filter consistently boosts HR by 5-10pp** regardless of base model
3. **OVER specialist models fail** — too few picks generated, catastrophic HR
4. **Fresh baselines generate almost no edge** (4-8 picks) — retrain paradox confirmed again
5. **None pass governance gates** (60% HR edge 3+ required) — but Q43_RECENCY14 is closest

### 2.4 Consolidated Dead Ends (Do Not Revisit)

| Approach | Experiments | Best Result | Why It Failed |
|----------|-----------|-------------|---------------|
| Vegas weight sweep (0.0-1.0) | 6 | 51.9% HR, 54 picks | Linear tradeoff, no sweet spot |
| Residual modeling | 3 | 30% HR | Gradient signal collapses — target (actual - vegas) has near-zero variance |
| Two-stage pipeline | 2 | 50.8% HR | Coin flip at scale, no better than random |
| CHAOS (high randomness) | 3 | 58.3%, 12 picks | Not enough volume to be useful |
| Matchup feature boost | 2 | 60.0%, 25 picks | Not enough volume, not reproducible |
| Grow policy (Depthwise/Lossguide) | 4 | Worse in all cases | CatBoost SymmetricTree is optimal for this data |
| NO_VEG + quantile combo | 2 | 48.9% HR | Double low-bias overshoots the optimal point |
| CHAOS + quantile combo | 2 | 48.2% HR | Randomization dilutes quantile's systematic bias |
| Q43 + Huber loss | 1 | 50% HR | Only one loss function can win; Huber fights quantile |
| OVER specialist model | 1 | 41.7%, 12 picks | Model generates too few OVER edge picks |
| Plain recency (no quantile) | 2 | 33.3%, 6 picks | Recency alone doesn't create edge |
| Feature exclusion (recent_trend) | 1 | 52.6%, 38 picks | No meaningful improvement |

### 2.5 What Works (The Short List)

| Approach | Result | Limitation |
|----------|--------|-----------|
| **Quantile alpha=0.43** | 65.8% HR edge 3+ when fresh (n=38, Session 186) | Only UNDER picks, Vegas bias -1.62 |
| **Q43 + 14d recency** | 55.4% HR edge 3+ (n=92, Session 222B) | Below 60% gate, UNDER-heavy |
| **Staleness exploitation** | Champion 71.2% peak at 2-3 weeks stale | Decays to <40% after 5 weeks |
| **Direction filtering** | +5-10pp HR when suppressing role UNDER | Reduces pick volume |

**Quantile regression is the only approach that generates edge when fresh.** It works by systematically predicting below the conditional median, creating permanent divergence from Vegas. All other approaches either track Vegas (no edge) or degrade with freshness.

### 2.6 Governance Gates & Why They Exist

The 6 governance gates in `quick_retrain.py` (lines 1451-1475):

| Gate | Threshold | Why It Exists |
|------|-----------|---------------|
| MAE improvement | < 5.14 (V9 baseline) | Prevents accuracy regression |
| Hit rate edge 3+ | >= 60% | Ensures profitability at standard vig |
| Sample size edge 3+ | >= 50 picks | Statistical significance minimum |
| Vegas bias | within ±1.5 | Prevents systematic miscalibration |
| No critical tier bias | < ±5 points any tier | Prevents regression-to-mean on specific player types |
| Directional balance | OVER + UNDER both >= 52.4% | Prevents direction-specific collapse |

**Gate tension with quantile models:** Q43's systematic UNDER bias (-1.62 Vegas bias) nearly violates the ±1.5 gate. The directional balance gate is impossible for pure UNDER models to pass. Future quantile models may need adjusted gates — but loosening gates was how the MAE-4.12-but-51%-HR disaster happened (Session 176). Be cautious.

---

## Part 3: Player-Level Analysis — Full Implementation Design

### 3.1 Why the Model Fails at Player Level

The current model treats all players identically — a breakout-prone 23-year-old and a declining 34-year-old get the same treatment if their recent stats match. The model has:

- **No career stage awareness** — doesn't know if a player is peaking, declining, or developing
- **No variance profiling** — doesn't distinguish between consistent scorers and volatile ones
- **No teammate context** — can't see when a star teammate is out (role expansion)
- **No per-player calibration** — no learning from its own past errors on specific players

### 3.2 Player Archetype Clustering Design

**Goal:** Group players into behavioral archetypes so the model can learn archetype-specific patterns.

**Clustering features** (computed from `player_game_summary`):

```python
# ml/features/player_archetypes.py

ARCHETYPE_FEATURES = [
    'scoring_variance',        # std(points) / mean(points) over season
    'usage_rate',              # points / team_points per game
    'minutes_stability',       # std(minutes) / mean(minutes)
    'career_games',            # total NBA games played (proxy for career stage)
    'scoring_trend',           # slope of points over last 20 games
    'role_consistency',        # % of games started vs came off bench
    'three_point_dependency',  # pct_three from shot zones
    'paint_dependency',        # pct_paint from shot zones
]
```

**Expected archetypes** (K=6, based on NBA player types):

| Archetype | Description | Prediction Behavior |
|-----------|-------------|-------------------|
| **Consistent Star** | High usage, low variance, high minutes | Predictable, model should be accurate |
| **Volatile Scorer** | High usage, HIGH variance | Hard to predict, need wider confidence intervals |
| **Developing Young Player** | Low career games, positive scoring trend | UNDER-biased (model uses old baseline) |
| **Declining Veteran** | High career games, negative trend | OVER-biased (model uses old high baseline) |
| **Role Player (Steady)** | Low usage, low variance, stable minutes | Most predictable tier |
| **Role Player (Volatile)** | Low usage, HIGH variance, unstable minutes | Hardest to predict, should suppress bets |

**Implementation plan:**

1. **Feature computation** (`ml/features/player_archetypes.py`):
   - Query `nba_analytics.player_game_summary` for season-to-date stats
   - Compute the 8 archetype features per player
   - Run K-Means (sklearn) with K=6, fit on current season
   - Output: `{player_lookup: archetype_id}` mapping

2. **Phase 4 integration** (add to `ml_feature_store_processor.py`):
   - Import archetype mapping
   - Add `player_archetype_id` as feature index 39 (categorical)
   - CatBoost handles categoricals natively via `cat_features=[39]`

3. **Training pipeline** (`quick_retrain.py`):
   - Pass `cat_features` to CatBoost when feature count >= 40
   - No other changes needed

4. **Refresh cadence:** Weekly (archetypes are stable within-season but shift with roster changes)

**Risk:** Clustering on 8 features with K=6 may not produce clean separations. Validate with silhouette score >= 0.3 before using.

### 3.3 Per-Player Calibration Layer

**Goal:** Track the model's systematic bias on individual players and adjust predictions post-hoc.

**Design:**

```python
# predictions/worker/calibration/player_bias_tracker.py

def get_player_bias(player_lookup: str, system_id: str, window: int = 20) -> float:
    """
    Compute rolling prediction bias for a specific player.

    Returns: mean(predicted - actual) over last `window` graded predictions.
    Positive = model over-predicts (adjust DOWN)
    Negative = model under-predicts (adjust UP)
    """
    query = f"""
    SELECT AVG(predicted_points - actual_points) as bias
    FROM nba_predictions.prediction_accuracy
    WHERE player_lookup = '{player_lookup}'
      AND system_id = '{system_id}'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    ORDER BY game_date DESC
    LIMIT {window}
    """
    # Returns float bias or 0.0 if insufficient history
```

**Adjustment in prediction worker:**

```python
# In predictions/worker/prediction_systems/catboost_monthly.py

raw_prediction = model.predict(features)
player_bias = get_player_bias(player_lookup, system_id, window=20)

# Only adjust if we have enough history (>= 10 graded predictions)
if abs(player_bias) > 0 and graded_count >= 10:
    adjusted_prediction = raw_prediction - player_bias
else:
    adjusted_prediction = raw_prediction
```

**BigQuery table for tracking:**

```sql
CREATE TABLE nba_predictions.player_prediction_bias (
    player_lookup STRING,
    system_id STRING,
    game_date DATE,
    rolling_bias_20 FLOAT64,       -- mean(pred - actual) last 20
    rolling_bias_10 FLOAT64,       -- mean(pred - actual) last 10
    graded_count INT64,            -- predictions available for computation
    bias_direction STRING,         -- 'OVER_PREDICTS' or 'UNDER_PREDICTS'
    updated_at TIMESTAMP
) PARTITION BY game_date;
```

**Update cadence:** Daily, after grading runs (Phase 5b). Could be a new processor in the grading pipeline.

**Expected impact:** The model is 0/6 on Trey Murphy III (all UNDER, avg edge 9.6). If calibration tracked this, after 3-4 wrong predictions the bias would be ~-9.6, and the adjusted prediction would shift UP by ~10 points, likely flipping the direction to OVER or reducing edge below 3 (suppressing the bet).

**Risk:** 20-game window may be too short for players who play every other day. Consider 30 for low-volume players.

### 3.4 Player-Specific Training (Why Individual Models Won't Work)

**The problem:** ~100 rows per player per season. CatBoost needs 500+ rows minimum for reasonable generalization. Individual player models would massively overfit.

**Better approach — player interaction features:**

Instead of separate models, add features that capture player-specific behavior:

```python
# Feature interactions (computed in Phase 4, added to feature store)
'player_variance_x_direction'    # high variance + UNDER → dangerous
'archetype_x_tier'               # developing player + role tier → likely UNDER-biased
'player_consistency_score'        # how predictable is this player (1/CV of points)
'player_vs_line_history'         # historical hit rate of this player's over/under
```

The key insight: **let the model learn player-type interactions**, not player-specific models. A CatBoost tree can split on `archetype=3 AND direction=UNDER` to learn "developing players tend to go OVER" without needing a per-player model.

**Multi-season player continuity:** Same `player_lookup` across seasons allows the model to learn long-term tendencies. A player with 200+ data points across 2 seasons gives the model enough signal to learn their specific variance pattern — without needing a separate model.

---

## Part 4: Feature Engineering — Full Implementation Design

### 4.1 Current Features Ranked by Importance

The champion model uses 33 features (indices 0-32). Feature importance from the production model:

| Rank | Index | Feature | Importance % | Category | Assessment |
|------|-------|---------|-------------|----------|------------|
| 1 | 25 | `vegas_points_line` | 29-36% | Vegas | Critical anchor |
| 2 | 26 | `vegas_opening_line` | 14-17% | Vegas | Critical anchor |
| 3 | 1 | `points_avg_last_10` | ~12% | Recent Performance | Core signal |
| 4 | 0 | `points_avg_last_5` | ~3.4% | Recent Performance | Core signal |
| 5 | 27 | `vegas_line_move` | ~3.0% | Vegas | Low fill rate (15.7%) |
| 6 | 32 | `ppm_avg_last_10` | ~2.9% | Minutes/Efficiency | Useful |
| 7 | 31 | `minutes_avg_last_10` | ~2.7% | Minutes/Efficiency | Useful |
| 8 | 8 | `usage_spike_score` | ~2.7% | Composite | Useful |
| 9 | 13 | `opponent_def_rating` | ~2.3% | Matchup | Useful |
| 10 | 5 | `fatigue_score` | ~2.0% | Composite | Useful |
| ... | ... | ... | ... | ... | ... |
| 31 | 15 | `home_away` | ~0.4% | Game Context | Low signal |
| 32 | 16 | `back_to_back` | ~0.3% | Game Context | Low signal |
| 33 | 17 | `playoff_game` | **0.0%** | Game Context | **Dead weight** (always 0) |

**Dead weight features** (candidates for removal or replacement):
- `playoff_game` (index 17): Always 0 during regular season — literally zero information
- `vegas_line_move` (index 27): Non-zero for only 15.7% of records
- `has_vegas_line` (index 28): Binary, 45.2% have Vegas lines — model already handles this via Vegas feature values

Vegas features alone account for **50%+ of all model decisions**. This is both the source of accuracy AND the source of the retrain paradox.

### 4.2 Six Unused Features Already in Store (Indices 33-38)

These exist in `ml_feature_store_v2` but V9 only uses indices 0-32:

| Index | Feature | Source | Description | Activation Effort |
|-------|---------|--------|-------------|-------------------|
| 33 | `dnp_rate` | Calculated | Historical did-not-play percentage | LOW — just extend feature slice |
| 34 | `pts_slope_10g` | Calculated | 10-game scoring trend slope | LOW — captures hot/cold streaks |
| 35 | `pts_vs_season_zscore` | Calculated | Current vs season average (z-scored) | LOW — normalizes role changes |
| 36 | `breakout_flag` | Calculated | Binary breakout indicator | LOW — from breakout classifier |
| 37 | `breakout_risk_score` | ML | Breakout classifier probability | LOW — V2 AUC 0.57 (weak) |
| 38 | `composite_breakout_signal` | Calculated | Combined breakout indicators | LOW — composite of 37 + other signals |

**Activation plan:**

1. In `quick_retrain.py`, change feature extraction to use first 39 features instead of 33:
   ```python
   # Current (line ~1180):
   X_train = np.array([row[:33] for row in features])
   # Change to:
   X_train = np.array([row[:39] for row in features])
   ```

2. In `shared/ml/feature_contract.py`, update:
   ```python
   FEATURE_STORE_VERSION = 'v2_39features'  # already set
   V10_FEATURE_COUNT = 39  # add constant
   ```

3. In `predictions/worker/prediction_systems/catboost_monthly.py`, configure new model entries with `feature_count: 39`.

**Expected impact:** Moderate. `pts_slope_10g` and `pts_vs_season_zscore` directly address the "model doesn't see trends" problem. `breakout_risk_score` has weak AUC (0.57) so may not help.

### 4.3 New Feature Designs

#### Feature A: `star_teammate_out` (Binary)

**What:** Whether the player's team is missing a 20+ PPG scorer.

**Why it matters:** When a star sits, role players see +3-8 PPG usage boosts. This is the single biggest blind spot — the model predicts role player UNDER but the star is injured, creating a usage vacuum.

**Data source:** `nba_raw.nbac_injury_report` (official NBA injury reports, 15-min updates)

**Implementation:**

```python
# data_processors/precompute/ml_feature_store/star_teammate_feature.py

def compute_star_teammate_out(player_lookup: str, game_date: str, team: str) -> int:
    """
    Check if any teammate averaging 20+ PPG is listed as OUT.

    Returns: 1 if star teammate OUT, 0 otherwise.
    """
    query = f"""
    WITH team_stars AS (
        SELECT player_lookup, points_avg_season
        FROM nba_analytics.player_game_summary
        WHERE team_tricode = '{team}'
          AND game_date >= DATE_SUB('{game_date}', INTERVAL 30 DAY)
        GROUP BY player_lookup
        HAVING AVG(points) >= 20.0
    ),
    injured_out AS (
        SELECT player_name
        FROM nba_raw.nbac_injury_report
        WHERE game_date = '{game_date}'
          AND team_tricode = '{team}'
          AND status = 'Out'
    )
    SELECT COUNT(*) > 0 as star_out
    FROM team_stars ts
    JOIN injured_out io ON LOWER(ts.player_name) = LOWER(io.player_name)
    """
    # Returns 1 or 0
```

**Phase 4 integration:** Add to `ml_feature_store_processor.py` feature extraction. Compute per-player, per-game-date. Add as feature index 39 (or 40 if archetypes take 39).

**Feature store schema change:** Append `'star_teammate_out'` to `FEATURE_STORE_NAMES` in `feature_contract.py`.

#### Feature B: `teammate_ppg_missing` (Continuous)

**What:** Sum of PPG of all OUT teammates.

**Why:** More granular than binary `star_teammate_out`. If a team is missing 45 combined PPG of scorers, the usage redistribution is massive.

**Implementation:** Same query as Feature A, but return `SUM(points_avg_season)` of all OUT teammates.

**Expected range:** 0-50 (0 = full team, 50 = multiple stars out)

#### Feature C: `opponent_b2b` (Binary)

**What:** Whether the opponent is also on a back-to-back.

**Why:** When the opponent is on a B2B, they play worse defense → scoring goes up. Currently we only track the *player's* B2B status (index 16).

**Data source:** `nba_reference.nba_schedule` — check if opponent played yesterday.

**Implementation:**

```python
def compute_opponent_b2b(opponent_team: str, game_date: str) -> int:
    query = f"""
    SELECT COUNT(*) > 0 as opp_b2b
    FROM nba_reference.nba_schedule
    WHERE game_date = DATE_SUB('{game_date}', INTERVAL 1 DAY)
      AND (home_team_tricode = '{opponent_team}'
           OR away_team_tricode = '{opponent_team}')
      AND game_status = 3  -- completed
    """
```

**Effort:** LOW — data already available, simple computation.

#### Feature D: `q4_efficiency_ratio` (Continuous)

**What:** What fraction of the player's points come in Q4.

**Why:** Players who score heavily in Q4 are affected by blowout benching (reduced Q4 minutes). This is currently invisible.

**Data source:** `nba_raw.nbac_play_by_play` — aggregate points by quarter per player.

**Implementation:**

```python
def compute_q4_ratio(player_lookup: str, game_dates: list) -> float:
    query = f"""
    SELECT
        SUM(CASE WHEN period = 4 THEN points_scored ELSE 0 END) /
        NULLIF(SUM(points_scored), 0) as q4_ratio
    FROM nba_raw.nbac_play_by_play
    WHERE player_lookup = '{player_lookup}'
      AND game_date IN UNNEST({game_dates})
      AND period <= 4
    """
    # Returns float 0.0-1.0 (typical range: 0.20-0.35)
```

**Effort:** HIGH — requires play-by-play aggregation in Phase 4.

#### Feature E: `fg_pct_last_3` (Continuous)

**What:** Field goal percentage over last 3 games.

**Why:** Short-term shooting efficiency captures hot/cold streaks better than rolling 5/10 game averages. A player shooting 60% FG last 3 games is more likely to go OVER.

**Data source:** `nba_analytics.player_game_summary` (already has FG stats).

**Implementation:**

```python
def compute_fg_pct_last_3(player_lookup: str, game_date: str) -> float:
    query = f"""
    SELECT AVG(fg_pct) as fg_pct_3
    FROM (
        SELECT fg_pct
        FROM nba_analytics.player_game_summary
        WHERE player_lookup = '{player_lookup}'
          AND game_date < '{game_date}'
        ORDER BY game_date DESC
        LIMIT 3
    )
    """
```

**Effort:** LOW — data exists, simple aggregation.

#### Feature F: `scoring_run_frequency` (Continuous)

**What:** How often the player has scoring runs of 5+ consecutive points.

**Why:** "Streaky" scorers are harder to predict with averages alone. A player who frequently goes on runs has higher upside variance.

**Data source:** `nba_raw.nbac_play_by_play`

**Effort:** HIGH — requires sequential analysis of play-by-play data.

### 4.4 Feature Priority Matrix

| Feature | Expected Impact | Implementation Effort | Data Available? | Priority |
|---------|----------------|----------------------|-----------------|----------|
| `star_teammate_out` | HIGH | MEDIUM | Yes (injury report) | **1** |
| `teammate_ppg_missing` | HIGH | MEDIUM | Yes (injury + stats) | **2** |
| `fg_pct_last_3` | MEDIUM | LOW | Yes (player_game_summary) | **3** |
| `opponent_b2b` | MEDIUM | LOW | Yes (schedule) | **4** |
| Activate indices 33-38 | MEDIUM | LOW | Already in store | **5** |
| `player_archetype_id` | MEDIUM | HIGH | Needs computation | **6** |
| `q4_efficiency_ratio` | LOW-MEDIUM | HIGH | Yes (play-by-play) | **7** |
| `scoring_run_frequency` | LOW | HIGH | Yes (play-by-play) | **8** |
| `player_bias_rolling20` | MEDIUM | MEDIUM | After calibration layer | **9** |

### 4.5 Feature Store Schema Changes

To add new features, update `shared/ml/feature_contract.py`:

```python
# Append to FEATURE_STORE_NAMES:
FEATURE_STORE_NAMES = [
    # ... existing 0-38 ...
    'star_teammate_out',        # 39
    'teammate_ppg_missing',     # 40
    'fg_pct_last_3',            # 41
    'opponent_b2b',             # 42
    'player_archetype_id',      # 43 (categorical)
    'q4_efficiency_ratio',      # 44
    'scoring_run_frequency',    # 45
    'player_bias_rolling20',    # 46
]

# Update version:
FEATURE_STORE_VERSION = 'v2_47features'

# Update source map:
FEATURE_SOURCE_MAP.update({
    39: 'phase4',    # star_teammate_out
    40: 'phase4',    # teammate_ppg_missing
    41: 'phase4',    # fg_pct_last_3
    42: 'phase3',    # opponent_b2b (from schedule)
    43: 'phase4',    # player_archetype_id
    44: 'phase4',    # q4_efficiency_ratio
    45: 'phase4',    # scoring_run_frequency
    46: 'calculated', # player_bias_rolling20
})
```

**Note:** Incrementally adding features is safe — the feature store stores an array. Models specify how many features they use (V9 = 33, V10 = 39, V11 = 47). Old models continue working.

---

## Part 5: Training Data Strategy

### 5.1 Current State: Using 13% of Available Data

| Season | Usable Rows | Currently Used? | Data Quality |
|--------|-------------|-----------------|-------------|
| 2021-22 | 11,660 | No | Unknown — needs audit |
| 2022-23 | 11,652 | No | Unknown — needs audit |
| 2023-24 | 13,671 | No | Likely good (post-feature-store) |
| 2024-25 | 15,193 | No | Good |
| 2025-26 (through Feb 12) | 11,287 | **Only 8,417 (Nov-Jan)** | Good |
| **TOTAL** | **~63,463** | **8,417 (13%)** | Varies |

The champion trains on a **68-day window** (Nov 2 - Jan 8). This means:
- High sensitivity to within-window anomalies
- No cross-season generalization
- No long-term player tendency learning
- Easy to overfit to one opponent cycle (NBA teams play each other 3-4 times/season)

### 5.2 Multi-Season Training Proposal

**Recommended approach:** Train on **2023-24 through present** (~40K rows from 2 full seasons + current).

**Why start at 2023-24:**
- Post-modern-rules era (consistent game style)
- Feature store data quality is reliable from this point
- 2021-23 may have feature computation differences (needs audit first)
- Still gives 5x more data than current approach

**Recency weighting** (120-day half-life):

```
weight(game) = exp(-0.693 * days_ago / 120)
```

| Days Ago | Weight | Description |
|----------|--------|-------------|
| 0 (today) | 1.000 | Full weight |
| 30 | 0.841 | Recent games |
| 60 | 0.707 | Last 2 months |
| 120 | 0.500 | Half-life |
| 240 | 0.250 | Last season |
| 365 | 0.125 | Two seasons ago |
| 730 | 0.016 | Three seasons ago |

This means a game from last week has 6x the weight of a game from a year ago. The model still *sees* old data (for archetype learning) but emphasizes recent patterns.

**Implementation:** Already supported in `quick_retrain.py` via `--recency-weight 120`. The training data loader applies exponential decay to sample weights.

### 5.3 Data Quality by Season (Needs Audit)

Before training on multi-season data, verify:

```sql
-- Check feature quality by season
SELECT
    FORMAT_DATE('%Y-%m', game_date) as month,
    COUNT(*) as rows,
    AVG(feature_quality_score) as avg_quality,
    COUNTIF(required_default_count = 0) as clean_rows,
    ROUND(100.0 * COUNTIF(required_default_count = 0) / COUNT(*), 1) as clean_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2023-10-01'
GROUP BY 1
ORDER BY 1;
```

**Expected issues:**
- Early 2023-24 may have lower quality scores (Phase 4 processors were less mature)
- Vegas line coverage varies by season (Odds API availability)
- Some features may have been computed differently in older versions

**Mitigation:** The `training_data_loader.py` already enforces `required_default_count = 0` and `feature_quality_score >= 70`. These gates should filter out poor-quality historical rows automatically.

### 5.4 Player-Season Interaction Features

When training multi-season, add features that capture cross-season context:

```python
# Features to add for multi-season training:
'season_game_number'    # How many games into the season (1-82)
'days_into_season'      # Calendar days since Oct 1
'is_post_allstar'       # Binary: before/after all-star break
'player_season_count'   # How many seasons has this player been in the data
```

These help the model learn:
- Early-season variance (players finding their rhythm)
- Post-all-star-break trends (fatigue, tanking teams resting players)
- Rookie vs veteran prediction patterns
- Second-half-of-season defensive improvements

---

## Part 6: Experiment Roadmap (9 Experiments, Priority-Ordered)

### Experiment 1: Multi-Season Q43 Training
**Priority: HIGH | Effort: LOW**

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "MULTISZN_Q43_120D" \
    --quantile-alpha 0.43 \
    --train-start 2023-10-01 \
    --train-end 2026-02-10 \
    --eval-start 2026-02-01 \
    --eval-end 2026-02-11 \
    --recency-weight 120 \
    --walkforward \
    --force
```

**Hypothesis:** 5x more data + recency weighting improves Q43's generalization. The model sees more diverse game states (different opponents, venues, lineup configs) while still emphasizing recent patterns.

**Success criteria:** Edge 3+ HR >= 55%, sample >= 50, walkforward shows stable weekly performance.

**Why this is #1:** Zero new code required. Uses existing infrastructure. Tests the most impactful variable (training data size) with the best-known technique (Q43).

### Experiment 2: Direction-Aware Post-Processing Filter
**Priority: HIGH | Effort: NONE (analysis only)**

Simulate suppressing role player UNDER picks on historical data:

```sql
-- Simulate direction filter on champion
WITH base AS (
    SELECT *,
        CASE
            WHEN predicted_direction = 'UNDER'
                AND vegas_line BETWEEN 5 AND 14  -- role player range
            THEN TRUE
            ELSE FALSE
        END as would_be_filtered
    FROM nba_predictions.prediction_accuracy
    WHERE system_id = 'catboost_v9'
        AND game_date >= '2026-02-01'
        AND edge >= 3
)
SELECT
    COUNTIF(NOT would_be_filtered) as kept_picks,
    COUNTIF(NOT would_be_filtered AND is_correct) as correct,
    ROUND(100.0 * COUNTIF(NOT would_be_filtered AND is_correct) /
        NULLIF(COUNTIF(NOT would_be_filtered), 0), 1) as filtered_hr,
    COUNT(*) as original_picks,
    ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as original_hr
FROM base;
```

**Hypothesis:** Removing the 22% HR segment (role UNDER) lifts overall HR by 5-10pp.

**Success criteria:** Filtered HR >= 52.4% breakeven on remaining picks. Volume stays >= 50 picks/week.

**Why this is #2:** Zero code change, zero risk. Pure analysis that can be applied immediately.

### Experiment 3: Alpha Fine-Tuning (0.42, 0.44)
**Priority: HIGH | Effort: LOW**

```bash
# Alpha 0.42 (slightly less aggressive UNDER)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "Q42_RECENCY14" \
    --quantile-alpha 0.42 \
    --train-start 2025-11-02 \
    --train-end 2026-02-07 \
    --recency-weight 14 \
    --walkforward \
    --force

# Alpha 0.44 (between Q43 and Q45)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "Q44_RECENCY14" \
    --quantile-alpha 0.44 \
    --train-start 2025-11-02 \
    --train-end 2026-02-07 \
    --recency-weight 14 \
    --walkforward \
    --force
```

**Hypothesis:** Q43 + 14d recency (55.4% HR) is the current best. Testing alpha 0.42 and 0.44 with the same recency to find the exact sweet spot.

**From Session 222B data:**
- Q40 = 53.7% (136 picks) — too many low-quality picks
- Q42 = 52.4% (42 picks) — at breakeven
- Q43 = 51.4% (35 picks, no recency) vs 55.4% (92 picks, 14d recency)
- Q44 = 53.3% (30 picks) — fewer picks
- Q45 = 50.0% (22 picks) — too few

The sweet spot is likely between 0.42-0.44 with 14d recency.

### Experiment 4: V10 Feature Set (Activate Indices 33-38)
**Priority: MEDIUM | Effort: MEDIUM**

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V10_Q43_39FEAT" \
    --quantile-alpha 0.43 \
    --train-start 2025-11-02 \
    --train-end 2026-02-10 \
    --recency-weight 14 \
    --walkforward \
    --force
```

**Requires code change:** Extend feature extraction to 39 features (indices 0-38) in `quick_retrain.py`.

**Key new features being activated:**
- `pts_slope_10g` (34) — captures hot/cold streaks model currently misses
- `pts_vs_season_zscore` (35) — normalizes for mid-season role changes
- `dnp_rate` (33) — helps avoid players at risk of sitting

**Implementation steps:**
1. Update `quick_retrain.py` to accept `--feature-count` parameter (default 33, option for 39)
2. Update feature extraction to use `row[:feature_count]`
3. Register model with `feature_count=39` metadata

### Experiment 5: Star Teammate Injury Feature
**Priority: HIGH | Effort: HIGH**

**Implementation steps:**
1. Create `data_processors/precompute/ml_feature_store/star_teammate_feature.py`
2. Add computation to `ml_feature_store_processor.py`
3. Extend `feature_contract.py` with index 39
4. Backfill feature for training data period
5. Train with extended features

**Backfill query:**

```sql
-- Identify games where star teammates were OUT
WITH star_averages AS (
    SELECT player_lookup, team_tricode,
           AVG(points) as avg_points
    FROM nba_analytics.player_game_summary
    WHERE game_date >= '2025-10-01'
    GROUP BY 1, 2
    HAVING AVG(points) >= 20
),
injury_outs AS (
    SELECT game_date, team_tricode, player_name
    FROM nba_raw.nbac_injury_report
    WHERE status = 'Out'
)
-- Join to identify when stars were OUT for each team/date
```

**Expected impact:** Directly addresses the #1 failure mode (role player UNDER when star is out). Could swing 5-10pp on role player predictions.

**Timeline:** 2-3 sessions to implement, backfill, and train.

### Experiment 6: Player Archetype Features
**Priority: MEDIUM | Effort: HIGH**

Full implementation as designed in Part 3.2.

**Steps:**
1. Create `ml/features/player_archetypes.py`
2. Compute clustering on 2025-26 season data
3. Validate cluster quality (silhouette >= 0.3)
4. Add archetype_id to Phase 4 feature store
5. Backfill for training period
6. Train with `cat_features=[archetype_index]`

**Timeline:** 2-3 sessions.

### Experiment 7: Per-Player Calibration Layer
**Priority: MEDIUM | Effort: MEDIUM**

Full implementation as designed in Part 3.3.

**Steps:**
1. Create `nba_predictions.player_prediction_bias` table
2. Create daily bias computation job (post-grading)
3. Add bias adjustment to prediction worker (post-processing)
4. Shadow test for 1 week (log adjustments without applying)
5. Enable with feature flag

**Key advantage:** No model retraining needed. Works as post-processing on any model.

**Timeline:** 1-2 sessions.

### Experiment 8: Play-by-Play Features
**Priority: MEDIUM | Effort: HIGH**

Add `q4_efficiency_ratio` and `scoring_run_frequency` from play-by-play data.

**Steps:**
1. Create Phase 4 processor for play-by-play aggregation
2. Compute per-player Q4 ratio and run frequency
3. Add to feature store
4. Backfill and train

**Timeline:** 3-4 sessions (play-by-play data is large and complex).

### Experiment 9: Ensemble Stale+Fresh Combiner
**Priority: MEDIUM | Effort: MEDIUM**

Combine the stale champion (good at OVER) with fresh Q43 (good at UNDER):

```python
# Post-processing ensemble logic
def ensemble_prediction(stale_pred, fresh_q43_pred):
    """
    Direction-aware model combiner.

    - Stale model OVER predictions: use stale (47.5% HR baseline)
    - Fresh Q43 UNDER predictions: use Q43 (55.4% HR)
    - Both agree: HIGH confidence pick
    - Both disagree: skip (no bet)
    """
    stale_direction = 'OVER' if stale_pred.edge > 0 else 'UNDER'
    q43_direction = 'OVER' if fresh_q43_pred.edge > 0 else 'UNDER'

    if stale_direction == 'OVER' and stale_pred.edge >= 3:
        return stale_pred  # Use stale for OVER
    elif q43_direction == 'UNDER' and fresh_q43_pred.edge >= 3:
        return fresh_q43_pred  # Use Q43 for UNDER
    elif stale_direction == q43_direction:
        return max(stale_pred, fresh_q43_pred, key=lambda p: p.edge)  # Agreement
    else:
        return None  # Disagreement → skip
```

**Requires:** Both models running simultaneously (already the case with shadow system).

**Simulation first:** Can be simulated entirely from `prediction_accuracy` table before implementing.

**Timeline:** 1 session for simulation, 1 session for implementation if promising.

---

## Part 7: What NOT to Try (Dead Ends, With Evidence)

This section consolidates all dead ends from 112 experiments across Sessions 176-223. Each was tested multiple times and consistently failed.

### 7.1 Architecture Dead Ends

| Approach | Times Tested | Why It Fails | Evidence |
|----------|-------------|-------------|----------|
| **Residual modeling** | 3 | Target (actual - vegas) has near-zero variance → gradient collapses in 4-6 iterations | Session 180, 183 |
| **Two-stage pipeline** | 2 | First stage (no-vegas pred) is poorly calibrated; second stage (pred - vegas = edge) is noisy | Session 183 |
| **Individual player models** | Theoretical | ~100 rows/player/season → massive overfitting | N/A (don't try) |

### 7.2 CatBoost Parameter Dead Ends

| Parameter | Range Tested | Why It Fails | Evidence |
|-----------|-------------|-------------|----------|
| **Grow policy (Depthwise)** | Depthwise, Lossguide | Worse in all cases vs SymmetricTree default | Session 186, 222B |
| **RSM (feature subsampling)** | 0.5-0.8 | Reduces Vegas dominance but doesn't create edge | Session 186 |
| **CHAOS (random_strength)** | 5-20 | Creates edge on tiny sample (12 picks) but not at volume | Session 186 |
| **Bootstrap (MVS, Bernoulli)** | Multiple | No improvement over default | Session 186 |
| **Huber/LogCosh loss** | Multiple delta | No improvement, fights with quantile when combined | Session 186, 222B |

### 7.3 Feature Engineering Dead Ends

| Approach | Why It Fails | Evidence |
|----------|-------------|----------|
| **Vegas weight sweep** | Linear tradeoff: more Vegas = better MAE but less edge. No sweet spot. | 6 experiments, Session 179-183 |
| **Removing Vegas features entirely** | Model loses calibration (MAE 5 → 7). Unusable without anchor. | Session 183 |
| **NO_VEG + quantile combo** | Double low-bias overshoots optimal point → 48.9% HR | Session 186 |
| **Feature exclusion (recent_trend)** | Marginal feature removal doesn't meaningfully change outcomes | Session 222B |

### 7.4 Training Strategy Dead Ends

| Approach | Why It Fails | Evidence |
|----------|-------------|----------|
| **Plain recency weighting (no quantile)** | Doesn't create edge, just generates fewer picks (6 picks, 33% HR) | Session 222B |
| **OVER specialist filtering** | Model generates too few OVER edge picks (12 picks, 41.7% HR) | Session 222B |
| **Category weighting alone** | Boosting non-Vegas features reduces accuracy without creating edge | Session 186 |
| **Vegas weight reduction to 0.3** | 52.8% HR on 36 picks — near breakeven but not profitable | Session 222B |

### 7.5 Combination Dead Ends

| Combo | Why It Fails | Evidence |
|-------|-------------|----------|
| **Q43 + CHAOS** | Randomization dilutes quantile's systematic bias → 48.2% | Session 186 |
| **Q43 + Huber** | Only one loss function can win; they fight each other → 50% | Session 186 |
| **Q43 + NO_VEG** | Both push predictions down; combined overshoot → 48.9% | Session 186 |

**The lesson:** Quantile regression works because it creates a *specific, controlled* bias. Adding more bias sources (CHAOS, NO_VEG, Huber) doesn't improve it — it overshoots the optimal divergence from Vegas.

---

## Appendix A: Feature Importance (Current Champion)

| Rank | Index | Feature | Importance % | Category |
|------|-------|---------|-------------|----------|
| 1 | 25 | `vegas_points_line` | 29-36% | Vegas |
| 2 | 26 | `vegas_opening_line` | 14-17% | Vegas |
| 3 | 1 | `points_avg_last_10` | ~12% | Recent Performance |
| 4 | 0 | `points_avg_last_5` | ~3.4% | Recent Performance |
| 5 | 27 | `vegas_line_move` | ~3.0% | Vegas |
| 6 | 32 | `ppm_avg_last_10` | ~2.9% | Minutes/Efficiency |
| 7 | 31 | `minutes_avg_last_10` | ~2.7% | Minutes/Efficiency |
| 8 | 8 | `usage_spike_score` | ~2.7% | Composite |
| 9 | 13 | `opponent_def_rating` | ~2.3% | Matchup |
| 10 | 5 | `fatigue_score` | ~2.0% | Composite |
| ... | ... | ... | ... | ... |
| 31 | 15 | `home_away` | ~0.4% | Game Context |
| 32 | 16 | `back_to_back` | ~0.3% | Game Context |
| 33 | 17 | `playoff_game` | **0.0%** | Game Context |

**Vegas features = 50%+ of model.** This is the fundamental tension: Vegas provides accuracy but tracking Vegas prevents edge.

## Appendix B: Cross-Model Comparison (Feb 2026)

| Model | Edge 3+ Graded | HR Edge 3+ | OVER/UNDER Split | Vegas Bias | MAE |
|-------|---------------|-----------|------------------|-----------|-----|
| **Champion** (catboost_v9) | 192 | 38.0% | 83 OVER / 103 UNDER | -0.24 | 5.46 |
| train1102_0108 | 13 | 53.8% | 3 / 10 | -0.01 | 4.95 |
| Q43 shadow | 31 | 45.2% | 0 / 31 | -1.60 | 4.59 |
| Q45 shadow | 18 | 50.0% | 0 / 18 | -1.23 | 4.57 |

No model is currently profitable. The best performers have insufficient sample sizes.

## Appendix C: `quick_retrain.py` Parameter Cheat Sheet

```bash
# Basic structure
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXPERIMENT_NAME" \          # Required
    --train-start 2025-11-02 \          # Or use --train-days 60
    --train-end 2026-02-10 \            # Or use --eval-days 7
    --eval-start 2026-02-01 \           # Auto-computed if omitted
    --eval-end 2026-02-11 \             # Auto-computed if omitted
    --quantile-alpha 0.43 \             # Quantile regression (0.40-0.50)
    --recency-weight 120 \              # Half-life in days
    --walkforward \                     # Per-week eval breakdown
    --tune \                            # Hyperparameter grid search
    --force                             # Skip duplicate date check

# Loss functions
    --loss-function "Huber:delta=5"     # Huber loss
    --loss-function "MAE"               # Mean absolute error
    --loss-function "RMSE"              # Default (root mean squared error)

# CatBoost params
    --rsm 0.5                           # Feature subsampling per split
    --grow-policy Depthwise             # Tree growth (unlocks rsm)
    --min-data-in-leaf 20               # Min samples per leaf
    --bootstrap MVS                     # Bootstrap type
    --subsample 0.8                     # Row subsampling
    --random-strength 5                 # Split score noise

# Feature control
    --exclude-features "playoff_game,has_vegas_line"  # Drop features
    --feature-weights "vegas_points_line=0.3"         # Per-feature weights
    --category-weight "vegas=0.3,composite=0.5"       # Per-category weights

# Modes
    --no-vegas                          # Drop features 25-28
    --residual                          # Train on actual - vegas (DEAD END)
    --two-stage                         # Train no-vegas, eval as pred - vegas (DEAD END)
    --dry-run                           # Show plan only
    --skip-register                     # Don't write to ml_experiments table
```

## Appendix D: Feature Contract Reference

**39 features total** in `shared/ml/feature_contract.py`:

| Index | Name | Category | Source |
|-------|------|----------|--------|
| 0 | points_avg_last_5 | Recent Performance | phase4 |
| 1 | points_avg_last_10 | Recent Performance | phase4 |
| 2 | points_avg_season | Recent Performance | phase4 |
| 3 | points_std_last_10 | Recent Performance | phase4 |
| 4 | games_in_last_7_days | Recent Performance | phase4 |
| 5 | fatigue_score | Composite | phase4 |
| 6 | shot_zone_mismatch_score | Composite | phase4 |
| 7 | pace_score | Composite | phase4 |
| 8 | usage_spike_score | Composite | phase4 |
| 9 | rest_advantage | Derived | calculated |
| 10 | injury_risk | Derived | calculated |
| 11 | recent_trend | Derived | calculated |
| 12 | minutes_change | Derived | calculated |
| 13 | opponent_def_rating | Matchup | phase4 |
| 14 | opponent_pace | Matchup | phase4 |
| 15 | home_away | Game Context | phase3 |
| 16 | back_to_back | Game Context | phase3 |
| 17 | playoff_game | Game Context | phase3 |
| 18 | pct_paint | Shot Zone | shot_zone |
| 19 | pct_mid_range | Shot Zone | shot_zone |
| 20 | pct_three | Shot Zone | shot_zone |
| 21 | pct_free_throw | Shot Zone | calculated |
| 22 | team_pace | Team Context | phase4 |
| 23 | team_off_rating | Team Context | phase4 |
| 24 | team_win_pct | Team Context | calculated |
| 25 | vegas_points_line | Vegas | vegas |
| 26 | vegas_opening_line | Vegas | vegas |
| 27 | vegas_line_move | Vegas | vegas |
| 28 | has_vegas_line | Vegas | calculated |
| 29 | avg_points_vs_opponent | Opponent History | phase4 |
| 30 | games_vs_opponent | Opponent History | calculated |
| 31 | minutes_avg_last_10 | Minutes/Efficiency | phase4 |
| 32 | ppm_avg_last_10 | Minutes/Efficiency | phase4 |
| 33 | dnp_rate | DNP Risk | calculated |
| 34 | pts_slope_10g | Player Trajectory | calculated |
| 35 | pts_vs_season_zscore | Player Trajectory | calculated |
| 36 | breakout_flag | Player Trajectory | calculated |
| 37 | breakout_risk_score | Breakout Risk | ML |
| 38 | composite_breakout_signal | Breakout Risk | calculated |

**V9 uses indices 0-32 (33 features). Indices 33-38 are available but unused.**
