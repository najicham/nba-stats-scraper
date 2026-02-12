# Master Experiment Plan — Model Recovery & Improvement

**Date:** 2026-02-12
**Sessions:** 222-224 (planning)
**Status:** Plan finalized, ready for execution
**Related:** `01-SESSION-222-MODEL-ANALYSIS.md`, `03-NEW-FEATURES-DEEP-DIVE.md`, `04-MULTI-SEASON-DATA-AUDIT.md`

---

## Executive Summary

The champion model (`catboost_v9`) has decayed from **71.2% to 38.0%** edge 3+ hit rate — well below the 52.4% breakeven. Edge 5+ collapsed from 79.3% to 30.5%. Analysis of **112 prior experiments** reveals the retrain paradox remains unsolved, but several promising directions haven't been tried:

1. **Multi-season training** — we're using only 11% of available data (8.4K of ~38K trainable rows)
2. **Untapped features** — referee data (0% utilized despite full pipeline), game totals, injury context
3. **Features 33-36** already computed but never activated in any model
4. **Alpha + recency sweet spot** — Q43 + 14d recency hit 55.4% but wasn't tested with more data

This plan defines **32+ experiments across 6 waves**, prioritized by effort and expected impact.

---

## The Situation

| Metric | January 2026 | February 2026 | Change |
|--------|-------------|---------------|--------|
| Edge 3+ HR | **64.8%** | **38.0%** | -26.8pp |
| Edge 5+ HR | **79.3%** | **30.5%** | -48.8pp |
| Edge 3+ picks | 392 | 192 | -51% |
| Model staleness | 23 days | 35 days | +12 days |

**Root cause:** Model trained through Jan 8. By Feb 12, it's 35 days stale. Predictions drift from current Vegas lines — this drift IS the betting edge, but after ~25 days the drift becomes noise. UNDER predictions are catastrophically bad (34% HR) because the model's player baselines lag reality while Vegas adjusts upward.

---

## Strategic Decision: Governance Gates

Before executing experiments, resolve this:

**The 60% gate is currently counterproductive.** It was set when the champion was at 71% — now the champion is at 38%. A 55% model would save significant money but fails the gate.

| Option | Gate | Risk | Recommendation |
|--------|------|------|----------------|
| **A: Keep 60%** | No change | Champion stays at 38%, losing daily | Only if experiments approach 60% |
| **B: Relative improvement** | New > champion + 10pp AND > 52.4% | Medium | **Recommended** |
| **C: Lower to 53%** | Absolute threshold drop | Higher — close to breakeven | If best is 53-55% |
| **D: Direction-specific** | Allow pure UNDER model if UNDER >= 58% | Medium | For Q43 models |

**Recommendation:** Add a relative improvement override. If new model beats champion by 10+ pp AND exceeds 52.4% breakeven on 50+ picks, it should be deployable.

---

## Data Availability (Multi-Season Audit)

Full audit in `04-MULTI-SEASON-DATA-AUDIT.md`. Key numbers:

| Season | Trainable Rows | Clean % | Vegas Coverage | Actuals Join |
|--------|---------------|---------|----------------|-------------|
| 2023-24 | **13,671** | 54-70% | 59-75% | 100% |
| 2024-25 | **13,193** | 61-76% | 64-83% | 100% |
| 2025-26 (partial) | **11,287** | 69-74% | 31-47% | 59-64% |
| **TOTAL** | **38,151** | — | — | — |

**Critical constraints:**
- **Exclude November** from all seasons (21-28% clean, bad opponent defense data)
- **Vegas coverage dropped in 2025-26** (43% vs 70% historically) — models trained on current season see more missing Vegas data
- **Features 33-36 are 96-100% populated** across all seasons — safe to activate
- **February is NOT structurally anomalous** — scoring averages are stable (10.5-10.9) across years

---

## Wave 0: Pattern Mining (SQL Only, No Training)

**Purpose:** Zero-cost analyses that inform experiment priorities. Run before any training.
**Effort:** 30 minutes
**Dependencies:** None

### Analysis 0a: UNDER collapse — February-specific or systemic?

```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  predicted_direction,
  COUNT(*) as picks,
  COUNTIF(is_correct) as correct,
  ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE edge >= 3 AND system_id = 'catboost_v9'
GROUP BY 1, 2
ORDER BY 1, 2;
```

**If UNDER was fine in January:** Problem is model staleness, not systematic bias. Focus on freshness (retrain).
**If UNDER was always weak:** Problem is structural. Focus on direction filtering or UNDER-specialized models.

### Analysis 0b: Trade deadline impact window

```sql
SELECT
  CASE
    WHEN game_date BETWEEN '2026-02-01' AND '2026-02-08' THEN 'Trade window'
    WHEN game_date BETWEEN '2026-02-09' AND '2026-02-12' THEN 'Post-trade'
    ELSE 'Normal'
  END as period,
  COUNT(*) as picks,
  COUNTIF(is_correct) as correct,
  ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE edge >= 3 AND system_id = 'catboost_v9' AND game_date >= '2026-01-15'
GROUP BY 1;
```

### Analysis 0c: Role player UNDER — the 22% HR disaster zone

```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as role_under_picks,
  ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE edge >= 3
  AND predicted_direction = 'UNDER'
  AND vegas_line BETWEEN 5 AND 14
  AND system_id = 'catboost_v9'
GROUP BY 1 ORDER BY 1;
```

### Analysis 0d: Direction filter simulation — all models

```sql
SELECT
  system_id,
  COUNT(*) as total_e3,
  COUNTIF(NOT (predicted_direction = 'UNDER' AND vegas_line BETWEEN 5 AND 14)) as filtered_picks,
  ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as original_hr,
  ROUND(100.0 * COUNTIF(is_correct AND NOT (predicted_direction = 'UNDER' AND vegas_line BETWEEN 5 AND 14)) /
    NULLIF(COUNTIF(NOT (predicted_direction = 'UNDER' AND vegas_line BETWEEN 5 AND 14)), 0), 1) as filtered_hr
FROM nba_predictions.prediction_accuracy
WHERE edge >= 3 AND game_date >= '2026-02-01'
GROUP BY 1
ORDER BY filtered_hr DESC;
```

### Analysis 0e: Ensemble simulation (champion OVER + Q43 UNDER)

```sql
WITH champion AS (
  SELECT player_lookup, game_date, predicted_direction, edge, is_correct
  FROM nba_predictions.prediction_accuracy
  WHERE system_id = 'catboost_v9' AND edge >= 3 AND game_date >= '2026-02-01'
),
q43 AS (
  SELECT player_lookup, game_date, predicted_direction, edge, is_correct
  FROM nba_predictions.prediction_accuracy
  WHERE system_id = 'catboost_v9_q43_train1102_0131' AND edge >= 3 AND game_date >= '2026-02-01'
)
-- Compare: champion OVER picks + Q43 UNDER picks + agreement picks
SELECT
  'Champion OVER' as source,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as hr
FROM champion WHERE predicted_direction = 'OVER'
UNION ALL
SELECT 'Q43 UNDER', COUNT(*), ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1)
FROM q43 WHERE predicted_direction = 'UNDER';
```

---

## Wave 1: Multi-Season Training Matrix (8 Experiments)

**Purpose:** Test the biggest untested variable — training data volume. We're at 11% utilization.
**Effort:** ~30 min per experiment, all runnable in parallel
**Dependencies:** None (uses existing `quick_retrain.py` as-is)
**Code changes:** None

### Multi-Season Design Principles

1. **Start from December** (not October/November) — November data is 21-28% clean across all seasons
2. **Always use recency weighting** — prevents old data from dominating
3. **Q43 quantile** — the only technique that generates edge when fresh
4. **Walk-forward eval** — ensures week-over-week stability

### Experiments

| # | Name | Seasons | Train Window | Alpha | Recency | Hypothesis |
|---|------|---------|-------------|-------|---------|------------|
| 1a | `2SZN_Q43_R60` | 2 | Dec 2024 → Feb 7, 2026 | 0.43 | 60d | 2x data with moderate recency |
| 1b | `2SZN_Q43_R120` | 2 | Dec 2024 → Feb 7, 2026 | 0.43 | 120d | 2x data with balanced recency |
| 1c | `3SZN_Q43_R120` | 3 | Dec 2023 → Feb 7, 2026 | 0.43 | 120d | Maximum data (3 seasons) |
| 1d | `3SZN_Q43_R240` | 3 | Dec 2023 → Feb 7, 2026 | 0.43 | 240d | Gentle decay, max history |
| 1e | `2SZN_BASE_R120` | 2 | Dec 2024 → Feb 7, 2026 | — | 120d | Control: does more data solve retrain paradox without quantile? |
| 1f | `2SZN_Q43_R14` | 2 | Dec 2024 → Feb 7, 2026 | 0.43 | 14d | Best single-season combo (14d) with 2x data |
| 1g | `FEB_FOCUS_Q43` | 3 | Dec 2023 → Feb 7, 2026 | 0.43 | 14d | 14d recency on 3 seasons = recent Feb dominates but model sees past Feb patterns |
| 1h | `2SZN_PERF_Q43_R14` | 2 | Dec 2024 → Feb 7, 2026 | 0.43 | 14d | Combines PERF_BOOST + Q43 + R14 + 2 seasons |

### Commands

```bash
# 1a: 2 seasons, Q43, 60-day recency
/model-experiment --name "2SZN_Q43_R60" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 60 --walkforward --force

# 1b: 2 seasons, Q43, 120-day recency
/model-experiment --name "2SZN_Q43_R120" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force

# 1c: 3 seasons, Q43, 120-day recency
/model-experiment --name "3SZN_Q43_R120" --quantile-alpha 0.43 --train-start 2023-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force

# 1d: 3 seasons, Q43, 240-day recency (gentle)
/model-experiment --name "3SZN_Q43_R240" --quantile-alpha 0.43 --train-start 2023-12-01 --train-end 2026-02-07 --recency-weight 240 --walkforward --force

# 1e: 2 seasons, baseline (no quantile), 120-day recency
/model-experiment --name "2SZN_BASE_R120" --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force

# 1f: 2 seasons, Q43, 14-day recency (best single-season combo)
/model-experiment --name "2SZN_Q43_R14" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 14 --walkforward --force

# 1g: 3 seasons, Q43, 14-day recency (February-focused)
/model-experiment --name "FEB_FOCUS_Q43" --quantile-alpha 0.43 --train-start 2023-12-01 --train-end 2026-02-07 --recency-weight 14 --walkforward --force

# 1h: 2 seasons + PERF_BOOST + Q43 + 14d recency
/model-experiment --name "2SZN_PERF_Q43_R14" --quantile-alpha 0.43 --recency-weight 14 --category-weight "composite=2.0,recent_performance=1.5,vegas=0.5" --train-start 2024-12-01 --train-end 2026-02-07 --walkforward --force
```

### Decision Gate After Wave 1

**Key questions:**
- Does more data help? (Compare 1a/1b vs original single-season Q43)
- Which recency weight wins? (60d vs 120d vs 240d vs 14d)
- Does 3 seasons beat 2? (1b vs 1c)
- Does baseline + multi-season solve the retrain paradox? (1e — if yes, quantile unnecessary)

**Advance to Wave 2 if:** Any experiment achieves 55%+ HR on 50+ picks. Take the winning config forward.
**Skip to Wave 3 if:** All stay below 53%. Multi-season alone isn't enough; need new features.

---

## Wave 2: Alpha Fine-Tuning (4 Experiments)

**Purpose:** Find the exact alpha sweet spot with the best multi-season config from Wave 1.
**Effort:** ~30 min each
**Dependencies:** Wave 1 results (need best recency weight and season count)

### Experiments

Take the winning Wave 1 configuration (e.g., 2 seasons, 120d recency) and sweep alpha:

```bash
# Alpha 0.41 (less aggressive UNDER than Q43)
/model-experiment --name "BEST_Q41" --quantile-alpha 0.41 --train-start {BEST} --train-end 2026-02-07 --recency-weight {BEST} --walkforward --force

# Alpha 0.42
/model-experiment --name "BEST_Q42" --quantile-alpha 0.42 --train-start {BEST} --train-end 2026-02-07 --recency-weight {BEST} --walkforward --force

# Alpha 0.44 (more aggressive UNDER)
/model-experiment --name "BEST_Q44" --quantile-alpha 0.44 --train-start {BEST} --train-end 2026-02-07 --recency-weight {BEST} --walkforward --force

# Alpha 0.45
/model-experiment --name "BEST_Q45" --quantile-alpha 0.45 --train-start {BEST} --train-end 2026-02-07 --recency-weight {BEST} --walkforward --force
```

### Known Alpha Data Points (Session 222B, Single-Season)

| Alpha | Edge 3+ Picks | HR | Notes |
|-------|--------------|-----|-------|
| 0.40 | 136 | 53.7% | Most volume, many low-quality |
| 0.42 | 42-84 | 52.4-53.6% | At breakeven |
| 0.43 | 35-92 | 51.4-55.4% | Best with recency |
| 0.44 | 30 | 53.3% | Fewer, slightly higher |
| 0.45 | 22 | 50.0% | Too few picks |

Multi-season data may shift where the sweet spot lands.

---

## Wave 3: V10 Feature Activation (4 Experiments)

**Purpose:** Activate features 33-36 that are already computed and 96-100% populated but never used.
**Effort:** 1 code change + ~30 min per experiment
**Dependencies:** None (can run in parallel with Waves 1-2)

### Code Change Required

In `ml/experiments/quick_retrain.py`, update feature extraction:
```python
# Current:
X_train = np.array([row[:33] for row in features])
# Change to:
X_train = np.array([row[:37] for row in features])
```

### Features Being Activated

| Index | Feature | What It Captures | Expected Impact |
|-------|---------|-----------------|-----------------|
| 33 | `dnp_rate` | Load management / sit risk | LOW — suppresses volatile players |
| 34 | `pts_slope_10g` | Hot/cold streak momentum | **HIGH** — directly addresses trend blindness |
| 35 | `pts_vs_season_zscore` | Role change detection | **HIGH** — catches mid-season breakouts |
| 36 | `breakout_flag` | Binary breakout indicator | MEDIUM — signals unusual performance |

### Experiments

```bash
# 3a: V10 + best Wave 1/2 config
/model-experiment --name "V10_BEST" --quantile-alpha {BEST} --train-start {BEST} --train-end 2026-02-07 --recency-weight {BEST} --walkforward --force

# 3b: V10 + single season (control — isolate feature impact)
/model-experiment --name "V10_1SZN_Q43_R14" --quantile-alpha 0.43 --train-start 2025-11-02 --train-end 2026-02-07 --recency-weight 14 --walkforward --force

# 3c: V10 + multi-season + no quantile (does V10 solve retrain paradox?)
/model-experiment --name "V10_2SZN_BASE" --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force

# 3d: V10 + drop dead-weight features (remove playoff_game, has_vegas_line, injury_risk)
/model-experiment --name "V10_NODEAD" --quantile-alpha 0.43 --exclude-features "playoff_game,has_vegas_line,injury_risk" --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force
```

### Decision Gate After Wave 3

Compare V10 experiments vs V9 counterparts:
- If V10 improves HR by 2+ pp → features are valuable, keep them permanently
- If V10 is neutral → 33 features are sufficient, skip feature engineering
- Check feature importance: do `pts_slope_10g` and `pts_vs_season_zscore` rank in top 15?

---

## Wave 4: New Feature Engineering (6 Feature Groups, 6+ Experiments)

**Purpose:** Build new features targeting specific failure modes.
**Effort:** 1-3 sessions per feature group (implementation + backfill + training)
**Dependencies:** Wave 3 results (confirms whether new features help)

Full implementation details in `03-NEW-FEATURES-DEEP-DIVE.md`. Summary:

### Feature Group A: Injury Context (addresses role player UNDER collapse)

| Feature | Index | Type | Data Source | Effort | Status |
|---------|-------|------|------------|--------|--------|
| `star_teammate_out` | 37 | INT64 (count) | Already in `upcoming_player_game_context` | **ZERO** — already computed! | Extract into feature store |
| `teammate_ppg_missing` | 38 | FLOAT64 | Injury report + player stats | MEDIUM | Build: join injury + PPG |
| `opponent_star_out` | 39 | INT64 | Injury report + opponent stats | MEDIUM | Same pattern as teammate |

**Key discovery:** `star_teammates_out` is **already computed and stored** in Phase 3 (`nba_analytics.upcoming_player_game_context`). Dynamic star identification exists (18+ PPG OR 28+ MPG OR 25%+ usage). We just need to extract it into the feature store — no new computation needed.

### Feature Group B: Shooting Efficiency (addresses streak blindness)

| Feature | Index | Type | Data Source | Effort |
|---------|-------|------|------------|--------|
| `fg_pct_last_3` | 40 | FLOAT64 | `player_game_summary` (FG stats exist) | **LOW** — add 2 lines to stats_aggregator |
| `ts_pct_last_5` | 41 | FLOAT64 | `player_game_summary` (`ts_pct` already computed) | **LOW** — same pattern |

**Key discovery:** `ts_pct` and `efg_pct` are **already computed per game** in Phase 3. Rolling averages for TS% last 10 already cached. Adding last-3 and last-5 windows is trivial.

### Feature Group C: Game Context (addresses environment blindness)

| Feature | Index | Type | Data Source | Effort |
|---------|-------|------|------------|--------|
| `opponent_b2b` | 42 | BINARY | Schedule (opponent_days_rest already in Phase 3) | **LOW** — one-line addition |
| `game_total_line` | 43 | FLOAT64 | `odds_api_game_lines` (99.52% coverage) | **LOW** — utility functions exist |
| `days_since_2day_rest` | 44 | INT64 | Already computed in Phase 3 | **ZERO** — already exists |

**Key discovery:** `opponent_days_rest` is **already computed** in Phase 3 `schedule_context_calculator.py`. `game_total_line` available from `odds_api_game_lines` with 99.52% DraftKings coverage. Both just need extraction.

### Feature Group D: Player Profile (addresses player-type blindness)

| Feature | Index | Type | Data Source | Effort |
|---------|-------|------|------------|--------|
| `scoring_cv_season` | 45 | FLOAT64 | `points_std_last_10` / `points_avg_season` (both exist) | **LOW** — one calculation |
| `minutes_cv_last_10` | 46 | FLOAT64 | Need `minutes_std_last_10` (not tracked yet) | MEDIUM — add to aggregator |
| `player_age` | 47 | INT64 | Already in `upcoming_player_game_context` | **ZERO** — already exists |
| `career_games_estimate` | 48 | INT64 | `experience_years` from BR rosters | MEDIUM — join + estimate |

### Feature Group E: Referee Signal (completely untapped gold mine)

| Feature | Index | Type | Data Source | Effort |
|---------|-------|------|------------|--------|
| `ref_crew_avg_total_pts` | 49 | FLOAT64 | `nbac_referee_game_assignments` + scoreboard | MEDIUM |
| `ref_crew_foul_rate` | 50 | FLOAT64 | Same + gamebook | MEDIUM |

**Key discovery:** Complete referee pipeline exists — scraper running, data in BigQuery, pivot views built, validation queries written. But `referee_adj = 0.0` is **hardcoded** in production. An 817-line implementation plan exists at `docs/08-projects/current/data-source-enhancements/REFEREE-TENDENCIES-IMPLEMENTATION-PLAN.md` but was never executed. Research shows 5-10 point variance per crew.

### Feature Group F: Game Total & Spread Context

| Feature | Index | Type | Data Source | Effort |
|---------|-------|------|------------|--------|
| `game_spread` | 51 | FLOAT64 | `odds_api_game_lines` (market_key='spreads') | **LOW** |
| `game_total_movement` | 52 | FLOAT64 | Opening vs closing total from snapshots | MEDIUM |

### Experiment Commands (Wave 4)

```bash
# 4a: V11 with injury context features (Group A)
/model-experiment --name "V11_INJURY_Q43" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight {BEST} --walkforward --force

# 4b: V11 with shooting efficiency (Group B)
/model-experiment --name "V11_SHOOTING_Q43" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight {BEST} --walkforward --force

# 4c: V11 with game context (Group C)
/model-experiment --name "V11_CONTEXT_Q43" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight {BEST} --walkforward --force

# 4d: V11 with player profile (Group D)
/model-experiment --name "V11_PROFILE_Q43" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight {BEST} --walkforward --force

# 4e: V11 with referee features (Group E)
/model-experiment --name "V11_REFEREE_Q43" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight {BEST} --walkforward --force

# 4f: V12 ALL features (kitchen sink)
/model-experiment --name "V12_ALL_Q43" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight {BEST} --walkforward --force
```

---

## Wave 5: Advanced Techniques (5 Experiments)

**Purpose:** Higher-risk, higher-reward ideas that build on Wave 1-4 learnings.
**Effort:** 1-2 sessions each
**Dependencies:** Results from earlier waves

### 5a: Per-Player Calibration Layer (Post-Processing)

No retraining needed. Works on top of ANY model.

**Design:**
- Build `nba_predictions.player_prediction_bias` table
- Daily: compute rolling 20-game bias per player after grading
- Prediction time: adjust `prediction = raw - bias` for players with 10+ graded predictions
- Shadow test 1 week before enabling

**Expected impact:** Fixes repeat failures (Trey Murphy 0/6, Jabari Smith 0/5). After 3-4 wrong predictions, bias tracker shifts prediction by ~10 points, flipping direction or suppressing edge.

**Implementation:** `predictions/worker/calibration/player_bias_tracker.py`

### 5b: Direction-Aware Ensemble (Stale + Fresh)

Combine champion's remaining OVER strength with fresh Q43's UNDER strength:
- Route champion's OVER predictions (47.5% HR baseline)
- Route Q43's UNDER predictions (55.4% HR)
- Both agree → HIGH confidence
- Both disagree → skip (no bet)

**Can simulate from `prediction_accuracy` before implementing.** Zero risk.

### 5c: February Specialist Model

```bash
# Train ONLY on January-March data from all 3 seasons
/model-experiment --name "FEB_SPECIALIST_Q43" --quantile-alpha 0.43 --train-start 2024-01-15 --train-end 2024-03-15 --recency-weight 30 --walkforward --force
```

**Hypothesis:** A model trained on mid-season data from multiple years learns February-specific patterns (trade deadline effects, all-star break, mid-season fatigue).

**Note:** This uses only ~3 months × 2 seasons = ~6K rows. May be insufficient. Consider combining Jan-Mar from all 3 seasons if eval shows promise.

### 5d: Seasonal Cycle Training (Mid-Season Windows)

```bash
# Train on Dec-Mar from all 3 seasons with standard recency
/model-experiment --name "MIDSZN_Q43_R120" --quantile-alpha 0.43 --train-start 2023-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force
```

Wait — this is the same as 1c. The real question: can we train on ONLY past Februaries?

```bash
# Would need custom date ranges. Conceptually:
# Train: Feb 2024 + Feb 2025 + Jan 2026 (~6K rows)
# Eval: Feb 2026
```

This requires a custom training data loader that accepts multiple date ranges. Currently `quick_retrain.py` only supports a single contiguous range. Worth building if other waves show February-specific patterns.

### 5e: Game Total Feature + Direction Filter Combo

Apply the direction filter (suppress role UNDER) to the best model AND add game total line:
- Models that already lean OVER should improve with better game-pace context
- High game totals (225+) should boost OVER confidence
- Low game totals (<210) should suppress OVER predictions

This is a post-processing enhancement, not a new model.

---

## Wave 6: Production Strategy

### Shadow Deployment (after finding a viable model)

1. Deploy best model alongside champion
2. Grade independently for 7+ days
3. Monitor with `validate-daily` Phase 0.56 and `reconcile-yesterday` Phase 9
4. Auto-healed by pipeline canary if prediction gaps detected

### Promotion Criteria

| Metric | Threshold |
|--------|-----------|
| Edge 3+ HR | >= 55% (or 52.4% with relative improvement override) |
| Sample size | >= 50 graded edge 3+ picks |
| Walk-forward stability | No single week below 45% |
| Tier bias | No tier > ±5 points systematic error |
| Direction balance | Both OVER and UNDER > 48% (relaxed for Q43) |

### Fallback: Direction Filter

If NO model passes gates, implement a **production post-processor** that suppresses role player UNDER picks from the decaying champion. Analysis 0d will show the expected lift. This alone could move HR from 38% to ~45-50% with zero model changes.

---

## Experiment Count & Timeline

| Wave | Experiments | Code Changes | Sessions |
|------|-----------|-------------|----------|
| **Wave 0** | 5 SQL analyses | None | 0.5 |
| **Wave 1** | 8 multi-season | None | 1-2 |
| **Wave 2** | 4 alpha sweep | None | 1 |
| **Wave 3** | 4 V10 activation | 1 line change | 1 |
| **Wave 4** | 6 new features | Feature engineering | 3-5 |
| **Wave 5** | 5 advanced | Mixed | 2-3 |
| **TOTAL** | **32 experiments** | | **8-12 sessions** |

### Recommended Execution Order

| Session | What | Expected Output |
|---------|------|-----------------|
| **A** | Wave 0 (SQL analyses) + Wave 1a-1d (first 4 multi-season) | Pattern insights + 4 trained models |
| **B** | Wave 1e-1h + Wave 2 (alpha sweep on early winners) | 8 more models, best config identified |
| **C** | Wave 3 (V10 activation) | Feature impact assessment |
| **D** | Wave 4 Group A (injury context — mostly extraction) | star_teammate_out in feature store |
| **E** | Wave 4 Groups B+C (shooting + game context) | 4 low-effort features added |
| **F** | Wave 4 Group E (referee features) | Untapped signal evaluated |
| **G-H** | Wave 5 (calibration, ensemble, specialist) | Advanced techniques tested |
| **I** | Wave 6 (shadow deploy best model) | Production candidate running |

**Waves 0-2 require ZERO code changes** and produce 17 trained models. Start there.

---

## Dead Ends — Do NOT Revisit

Consolidated from 112+ experiments. See `01-SESSION-222-MODEL-ANALYSIS.md` Part 7.

| Category | Dead End | Times Tested |
|----------|----------|-------------|
| Architecture | Residual modeling, two-stage pipeline | 5 |
| CatBoost params | Grow policy, CHAOS, bootstrap, Huber | 10+ |
| Feature engineering | Vegas weight sweep, NO_VEG, feature exclusion | 10+ |
| Training | Pure recency (no quantile), OVER specialist | 4 |
| Combinations | Q43+CHAOS, Q43+Huber, Q43+NO_VEG, Q43+Vegas30 | 6 |

**The lesson:** Quantile regression works by creating controlled, systematic bias. Adding more bias sources overshoots the optimum.

---

## Success Metrics

| Outcome | What It Means | Next Action |
|---------|--------------|-------------|
| Model hits 60%+ HR edge 3+ | Passes original governance gate | Shadow → promote |
| Model hits 55-59% | Strong improvement over 38% champion | Discuss gate adjustment → shadow |
| Model hits 52.4-54% | Above breakeven but marginal | Deploy only if 50+ picks/week volume |
| Nothing above 52.4% | February is structurally unprofitable | Direction filter + wait for March |

---

## Appendix: Quick Reference Commands

```bash
# Model experiment (all use this pattern)
/model-experiment --name "NAME" --quantile-alpha 0.43 --train-start YYYY-MM-DD --train-end YYYY-MM-DD --recency-weight N --walkforward --force

# Compare model performance
PYTHONPATH=. python bin/compare-model-performance.py SYSTEM_ID --days 7

# Check all shadow models
/validate-daily

# Direction filter (SQL)
# See Wave 0 Analysis 0d
```
