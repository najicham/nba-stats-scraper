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

## Wave 7: Post-Processing & Layered Systems (Zero Training Required)

**Purpose:** Stack multiple weak signals as filters on top of any model. Each is independently testable via SQL backtests. Combined, they could dramatically improve pick quality.
**Effort:** Most are SQL simulations first, then simple post-processing code
**Dependencies:** None — works on top of any model from Waves 1-6

### 7a: Multi-Model Consensus Scoring

Run 3-4 models simultaneously. When multiple models agree on direction AND all show edge 3+, that's a high-confidence pick.

```sql
-- How many models agreed on each pick, and what's the HR?
WITH model_picks AS (
  SELECT player_lookup, game_date, predicted_direction, is_correct, system_id
  FROM nba_predictions.prediction_accuracy
  WHERE edge >= 3 AND game_date >= '2026-01-15'
),
agreement AS (
  SELECT player_lookup, game_date, predicted_direction,
    COUNT(DISTINCT system_id) as models_agreeing,
    MAX(CASE WHEN system_id = 'catboost_v9' THEN is_correct END) as champion_correct
  FROM model_picks
  GROUP BY 1, 2, 3
)
SELECT models_agreeing, COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(champion_correct) / COUNT(*), 1) as hr
FROM agreement
GROUP BY 1 ORDER BY 1;
```

**Hypothesis:** If 3-model agreement picks hit at 65%+ while 1-model picks hit at 40%, that's actionable without any new model work.

### 7b: Direction Router (Stale OVER + Fresh UNDER)

Use champion for OVER calls, Q43 for UNDER calls. Disagreement = no bet.

**Note from reviewer:** Champion's OVER is at 47.5% — below breakeven. Only route champion OVER picks for **star players** (62.5% HR) or apply a higher edge threshold (edge >= 5) for champion OVER picks. Simulation first:

```sql
-- Test filtered ensemble: champion star OVER + Q43 UNDER
SELECT 'Champion Star OVER' as source, COUNT(*), ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1)
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND edge >= 3 AND predicted_direction = 'OVER'
  AND vegas_line >= 25 AND game_date >= '2026-02-01'
UNION ALL
SELECT 'Q43 UNDER', COUNT(*), ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1)
FROM nba_predictions.prediction_accuracy
WHERE system_id LIKE '%q43%' AND edge >= 3 AND predicted_direction = 'UNDER'
  AND game_date >= '2026-02-01';
```

### 7c: Player Regime Detection

Track minutes expansion/contraction as a filter signal:

```python
regime_indicator = minutes_avg_last_3 / minutes_avg_last_10
# > 1.3 = expanding role (suppress UNDER)
# < 0.7 = contracting role (suppress OVER)
```

When `regime_indicator > 1.3` AND model predicts UNDER → suppress. This directly catches the role-expansion players (Trey Murphy, Jabari Smith) killing UNDER hit rate.

### 7d: Blowout Risk Suppression

When `game_spread > 8` AND player is on the favored team AND model predicts OVER → reduce confidence or suppress. Starters in blowouts sit Q4, capping their scoring.

### 7e: "Hot Hand" Streak Filter

Track consecutive games where the player exceeded their prop line. If 4+ consecutive OVERs, boost OVER confidence. If 4+ consecutive UNDERs, boost UNDER confidence. Vegas adjusts lines slowly for role players.

### 7f: Anti-Correlation Pick Suppression

If the model generates 5+ OVER picks on the same game, that's suspicious — where do all the extra points come from? Same-team OVER picks are correlated.

```sql
-- Find same-game pick clusters and their HR
SELECT game_id, predicted_direction, COUNT(*) as picks_on_game,
  ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE edge >= 3 AND game_date >= '2026-01-15'
GROUP BY 1, 2
HAVING COUNT(*) >= 3
ORDER BY picks_on_game DESC;
```

**Rule:** Limit to 2-3 picks per game maximum. When 4+ picks exist, keep the 2-3 with highest edge.

### 7g: Dynamic Edge Threshold (Adapts to Model Age)

Since model edge decays predictably over 3-5 weeks, auto-tighten the edge filter:

| Model Age | Edge Threshold | Rationale |
|-----------|---------------|-----------|
| Week 1-2 | edge >= 3 | Fresh model, standard threshold |
| Week 3 | edge >= 4 | Early decay, raise bar |
| Week 4 | edge >= 5 | Significant decay |
| Week 5+ | edge >= 7 | Only highest-conviction picks |

This exploits the known decay curve without requiring a retrain.

### 7h: Layered Filter Stack

Combine all filters into a scoring system. Each pick gets a confidence score 0-6:

```
+1: Model edge >= 3
+1: Direction filter passes (not role UNDER)
+1: Regime check passes (minutes not expanding if UNDER)
+1: No blowout risk (spread < 8 for OVER)
+1: 2+ models agree on direction
+1: Game total supports direction (high total + OVER, low total + UNDER)
```

Only bet on picks scoring 4+/6. Backtest each layer independently, then combined.

### 7i: Line Shopping Post-Processor

**Free edge, zero model changes.** Already have multi-book data from The Odds API.

For each pick:
- UNDER predictions: use the **highest** available line across all books
- OVER predictions: use the **lowest** available line across all books

This is worth 2-3% to the bottom line per reviewer estimates.

### 7j: Per-Game Correlation Limits

Cap picks at 2 per game. Track correlation-adjusted metrics.

---

## Wave 8: Advanced ML Techniques (From Expert Review)

**Purpose:** CatBoost-specific optimizations and ML techniques not yet explored.
**Source:** Technical ML review of experiment plan.

### 8a: Monotonic Constraints (HIGH PRIORITY — Unexplored)

Force domain-correct relationships. Prevents spurious splits that break down out-of-sample:

```python
constraints = [0] * 37  # Start unconstrained
constraints[25] = 1   # vegas_points_line: higher line -> higher prediction
constraints[13] = -1  # opponent_def_rating: better defense -> lower prediction
constraints[31] = 1   # minutes_avg_last_10: more minutes -> more points
constraints[5] = -1   # fatigue_score: more fatigue -> fewer points
constraints[1] = 1    # points_avg_last_10: higher avg -> higher prediction
```

**Why this matters:** The retrain paradox stems from overly complex Vegas-tracking splits. Monotonic constraints force the model to use Vegas as a floor/ceiling rather than a splitting maze.

**CatBoost parameter:** `monotone_constraints` (list of -1/0/1 per feature)

### 8b: Multi-Quantile Ensemble (Q30/Q43/Q57)

Train three models instead of one. Use the spread as confidence:

```python
model_q30 = CatBoostRegressor(loss_function='Quantile:alpha=0.30')
model_q43 = CatBoostRegressor(loss_function='Quantile:alpha=0.43')
model_q57 = CatBoostRegressor(loss_function='Quantile:alpha=0.57')

# High-confidence UNDER: even Q57 < line - 1
confident_under = pred_q57 < vegas_line - 1.0
# High-confidence OVER: even Q30 > line + 1
confident_over = pred_q30 > vegas_line + 1.0
```

**Hypothesis:** Picks where the entire prediction interval is on one side of the line have much higher hit rates.

### 8c: Platt/Isotonic Calibration on Edge

Convert raw edge into calibrated win probability:

```python
from sklearn.linear_model import LogisticRegression
# Train: X = edge values, y = is_correct
calibrator = LogisticRegression()
calibrator.fit(historical_edges, historical_outcomes)
# At prediction time:
win_prob = calibrator.predict_proba(edge)[:, 1]
# Only bet when win_prob > 0.55
```

**Why:** Replaces the arbitrary edge >= 3 threshold with a probability-based threshold. Edge=5 may not be twice as good as edge=2.5 — calibration finds the true relationship.

### 8d: Q43 on Residual Target (NOT the tested dead end)

Previous dead end: RMSE loss on `actual - vegas`. That collapses because residuals have near-zero variance.

**Untested:** Quantile loss (Q43) on `actual - vegas`. The quantile loss function handles low-variance targets differently than RMSE — it systematically predicts below the conditional median of residuals. This is mechanistically different from both:
- Q43 on absolute points (tested, works)
- RMSE on residuals (tested, dead end)

### 8e: Feature Interaction Constraints

Prevent Vegas features from dominating feature interactions:

```python
# CatBoost parameter: feature_interaction_constraints
# Group 0: Vegas [25,26,27,28] — can only interact with each other
# Group 1: Performance [0,1,2,3,4] — can only interact with each other
hp['feature_interaction_constraints'] = [[25,26,27,28], [0,1,2,3,4]]
```

Forces the model to learn Vegas patterns and performance patterns independently, then combine at higher tree levels.

### 8f: Regularization Tuning (Unexplored Parameters)

| Parameter | What It Does | Suggested Range |
|-----------|-------------|-----------------|
| `model_size_reg` | Penalizes number of leaves | 1.0-10.0 |
| `min_data_in_leaf` | Min samples per leaf (works with SymmetricTree!) | 20-100 |
| `bagging_temperature` | Strength of Bayesian bootstrap | 1.0-10.0 |
| `leaf_estimation_method` | How leaf values are computed | 'Gradient' vs default 'Newton' |
| `l2_leaf_reg` | Currently tested 1.5-5.0, try higher | 7.0-15.0 |

**Key misconception corrected:** `min_data_in_leaf` works with SymmetricTree. The dead-end conclusion about Depthwise grow policy should NOT discourage testing `min_data_in_leaf=50` with the default tree policy. With 8K rows, this forces each leaf to represent 50+ players, preventing memorization.

### 8g: Optuna Hyperparameter Search (100+ Trials)

Replace the 18-combo grid search with Bayesian optimization:

```python
import optuna
def objective(trial):
    params = {
        'depth': trial.suggest_int('depth', 4, 8),
        'l2_leaf_reg': trial.suggest_float('l2_leaf_reg', 0.5, 20.0, log=True),
        'learning_rate': trial.suggest_float('lr', 0.01, 0.1, log=True),
        'min_data_in_leaf': trial.suggest_int('min_leaf', 5, 100),
        'model_size_reg': trial.suggest_float('msr', 0.0, 10.0),
        'loss_function': f'Quantile:alpha={trial.suggest_float("alpha", 0.38, 0.48)}',
    }
    # Returns edge 3+ HR
study = optuna.create_study(direction='maximize')
study.optimize(objective, n_trials=100)
```

**Why:** Jointly optimizes alpha AND regularization. The optimal alpha may depend on regularization strength. Each trial is <5 min with 38K rows.

### 8h: Model Stacking with Meta-Learner

Train a classifier on top of multiple base model predictions:

- **Layer 1:** Train Q43, Q50 (median), RMSE, Q43-no-vegas models
- **Layer 2:** Meta-learner takes `[pred_q43, pred_q50, pred_rmse, pred_noveg, vegas_line, player_tier, direction]` → outputs `P(bet wins)`

The meta-learner learns WHEN each base model is trustworthy. Must use out-of-fold predictions from base models to avoid leakage. Use `TimeSeriesSplit`.

### 8i: Pre-Computed Feature Interactions

CatBoost learns interactions through splits but may not find high-order ones reliably with limited data. Pre-compute domain-relevant combinations:

| Interaction | Formula | Why |
|-------------|---------|-----|
| `star_out × scoring_cv` | binary × continuous | Volatile scorers benefit MORE from star absence |
| `opponent_b2b × opp_def_rating` | binary × continuous | B2B + bad defense = scoring bonanza |
| `b2b × minutes_avg_10` | binary × continuous | High-minute players hurt more by B2B |
| `pts_slope × line_move` | continuous × continuous | Trending up + line moving up = market catching up (less edge) |
| `pred_vs_season_ratio` | `vegas_line / points_avg_season` | How far line deviates from baseline |

---

## Wave 9: Betting Operations (From Professional Review)

**Purpose:** Non-model improvements that directly impact profitability.
**Source:** Professional sports bettor review.

### 9a: Closing Line Value (CLV) Tracking (CRITICAL — Missing Entirely)

**The single most important analytical improvement.** CLV measures whether predictions beat the closing line — the gold standard for sports betting edge.

```sql
-- For each prediction, compare to closing line
-- If model predicted UNDER and closing line moved DOWN, that's positive CLV
SELECT
  pa.player_lookup,
  pa.game_date,
  pa.predicted_direction,
  pa.vegas_line as bet_line,
  closing.points_line as closing_line,
  CASE
    WHEN pa.predicted_direction = 'UNDER' THEN pa.vegas_line - closing.points_line
    ELSE closing.points_line - pa.vegas_line
  END as clv_points,
  pa.is_correct
FROM nba_predictions.prediction_accuracy pa
LEFT JOIN (
  -- Get closing line (latest snapshot before game time)
  SELECT player_lookup, game_date, points_line
  FROM nba_raw.odds_api_player_points_props
  WHERE bookmaker = 'draftkings'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup, game_date ORDER BY snapshot_timestamp DESC) = 1
) closing ON pa.player_lookup = closing.player_lookup AND pa.game_date = closing.game_date
WHERE pa.edge >= 3 AND pa.game_date >= '2026-01-01'
ORDER BY pa.game_date;
```

**If CLV is consistently negative** even during the 71.2% peak window → the model never had real edge, just variance on lucky staleness. This fundamentally changes the strategy.

**If CLV was positive in January and negative in February** → real edge that decayed, confirming staleness hypothesis.

### 9b: Late Injury Cascade Re-Evaluation Trigger

**Worth more than all model experiments combined** (per reviewer). When a star is ruled OUT 2-3 hours before tip, books take 30-60 minutes to adjust downstream player lines. Build a trigger:

1. Monitor injury reports at 5-6 PM ET
2. When star ruled OUT, identify all teammates
3. Re-calculate predictions for affected players using `star_teammate_out` feature
4. Output urgent picks in the 30-60 minute window before lines correct

### 9c: EV-Based Bet Sizing (Kelly Criterion)

Stop treating all edge 3+ picks equally. Convert edge to win probability (via calibration from 8c), then size bets:

```python
# Fractional Kelly (quarter Kelly for safety)
win_prob = calibrated_probability  # From Platt scaling
decimal_odds = 1.91  # -110
kelly_fraction = (win_prob * decimal_odds - 1) / (decimal_odds - 1)
bet_size = 0.25 * kelly_fraction * bankroll  # Quarter Kelly
```

**Edge=3 and edge=8 should NOT get the same bet size.**

### 9d: Alternate Line Exploitation

Books offer alternate lines (e.g., Tatum OVER 22.5 at -130 vs OVER 25.5 at +120). If model predicts 28, the +120 on OVER 25.5 may be better EV. Currently the system only evaluates primary lines.

### 9e: Reduce Vegas Feature Dependency (Strategic Goal)

**Target:** Vegas features below 30% of model importance (currently 50%+).

A model that's 50% Vegas is a noisy echo of the market. The new features (injury context, referee, game total, spread) need to collectively push Vegas dependency down. If they don't gain importance after training, they aren't informative enough.

**This is the fundamental strategic direction** — not more quantile/recency tuning.

---

## Revised Governance Gates (From Expert Review)

The 60% absolute threshold is statistically unsound at current sample sizes. Replacement:

### Tiered Gate System

| Gate | Requirement | Rationale |
|------|-------------|-----------|
| **Gate 1: Breakeven** | Edge 3+ HR > 52.4% on >= 100 picks | Are we above breakeven? |
| **Gate 2: Statistical** | Wilson CI lower bound (90%) on HR > 50% | Sample-size-aware |
| **Gate 3: Relative** | New model > champion + 5pp on same eval window | Is it better than current? |
| **Gate 4: Stability** | No walkforward week below 45% | No single-week collapse |
| **Gate 5: Volume** | >= 30 edge 3+ picks per week | Commercially viable |

**Wilson confidence interval formula:**
```python
from scipy.stats import beta
# Promote if P(true_HR > 52.4%) > 0.90
p_above_breakeven = 1 - beta.cdf(0.524, wins + 1, losses + 1)
promote = p_above_breakeven > 0.90
```

Drop the absolute 60% threshold. This adapts to sample size — with 50 picks you need higher observed HR; with 200 picks, lower HR suffices.

---

## Revised Priority Order (Post-Review)

Reviews unanimously agreed: **direction filter + CLV tracking should be #1, not multi-season training.**

### New Execution Order

| Priority | What | Wave | Effort | Expected Impact |
|----------|------|------|--------|-----------------|
| **1** | Direction filter + dynamic edge threshold | 7d, 7g | SQL + 1 rule | IMMEDIATE — stops bleeding |
| **2** | CLV tracking | 9a | SQL query | CRITICAL — validates whether edge exists |
| **3** | Line shopping post-processor | 7i | Post-processing | FREE 2-3% lift |
| **4** | Per-game pick limits (2-3 max) | 7f, 7j | Post-processing | Reduces variance |
| **5** | V10 activation + star_teammate_out | 3a, 4a | 1 code change | Addresses root failure modes |
| **6** | Monotonic constraints + regularization | 8a, 8f | CatBoost params | Prevents overfitting |
| **7** | Multi-quantile ensemble (Q30/Q43/Q57) | 8b | Train 3 models | Confidence scoring |
| **8** | Multi-season training (best 2-3 configs) | 1b, 1f, 1g | None | Test data volume impact |
| **9** | Calibration (Platt/isotonic) | 8c | Post-processing | Replaces arbitrary thresholds |
| **10** | New features (shooting, context, profile) | 4b-4d | Feature eng. | Incremental signal |
| **11** | Late injury cascade trigger | 9b | New trigger | Highest-alpha opportunity |
| **12** | Referee features | 4e | New processor | Unknown signal, medium effort |

---

## Key Warnings from Reviewers

1. **The 71.2% peak was probably noise**, not a baseline. Realistic target is 55-58%.
2. **32 experiments with 4-day eval = p-hacking risk.** Require 100+ picks and Wilson CI before promoting.
3. **14d recency on 8K rows = effective ~2-3K samples.** Multi-season data is mandatory when using aggressive recency weighting.
4. **Per-player calibration layer is a lagging indicator** — by the time bias is detected (20 games = 5-7 weeks), the situation has changed. Feature-based approaches (star_teammate_out, pts_slope) capture the CAUSE, not the symptom.
5. **Alpha fine-tuning within 0.01 increments is curve-fitting.** The difference between Q42 (52.4%) and Q43 (55.4%) on these sample sizes is noise. Pick Q43 and move on.
6. **Backtests overstate production by 5-10pp.** A 55% backtest result is probably 45-50% in production. Factor this into all decisions.

---

## Updated Experiment Count

| Wave | Experiments | Type |
|------|-----------|------|
| Wave 0 | 5 | SQL analyses |
| Waves 1-2 | 12 | Multi-season + alpha |
| Wave 3 | 4 | V10 activation |
| Wave 4 | 6 | New features |
| Wave 5 | 5 | Advanced techniques |
| Wave 7 | 10 | Post-processing (SQL sims) |
| Wave 8 | 9 | Advanced ML |
| Wave 9 | 5 | Betting operations |
| **TOTAL** | **~56 experiments** | |

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
