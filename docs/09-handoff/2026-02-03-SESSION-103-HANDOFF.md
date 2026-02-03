# Session 103 Handoff: Data Quality & Model Bias Investigation

**Date:** 2026-02-03
**Priority:** P0 - Critical Data Bug Blocking Model Training
**Status:** Investigation Complete, Fixes Needed

---

## Executive Summary

Session 103 investigated model bias (-9.3 pts on stars, +5.6 on bench) and discovered:

1. **CRITICAL: 40% of raw boxscore data is corrupted** - Star players like Tatum, Lillard have 0 points
2. **Vegas lines themselves are biased** - Sportsbooks under-predict stars by ~8 pts intentionally
3. **Model follows Vegas too closely** - Inherits sportsbook bias instead of learning to diverge
4. **Tier features are a band-aid** - Real fix needs mechanism features (usage, FGA, FTA)

---

## P0: Critical Data Pipeline Bug

### The Problem
35-45% of `nba_raw.bdl_player_boxscores` has corrupted data:
- Points = 0
- Minutes = "00"
- Affects star players: Jayson Tatum, Damian Lillard, Kyrie Irving, Chris Paul

### Impact Chain
```
nba_raw.bdl_player_boxscores (0 points, 00 minutes)
    ↓
nba_analytics.player_game_summary (NULL points, is_dnp=true)
    ↓
nba_predictions.ml_feature_store_v2 (points_avg_l5/l10/season = 0.0)
    ↓
Model Training (CORRUPTED)
```

### Validation Query
```sql
-- Check BDL data quality
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(points = 0 AND minutes = '00') as corrupted,
  ROUND(100.0 * COUNTIF(points = 0 AND minutes = '00') / COUNT(*), 1) as pct_bad
FROM nba_raw.bdl_player_boxscores
WHERE game_date >= '2026-01-15'
GROUP BY 1 ORDER BY 1 DESC
```

### Files to Investigate
| File | Purpose |
|------|---------|
| `scrapers/bdl/` | BDL API scraper - likely source of bug |
| `data_processors/analytics/player_game_summary/` | Where NULL propagates |

### Immediate Fix Needed
1. Fix BDL scraper or switch to backup source (ESPN, Basketball Reference)
2. Backfill corrupted dates
3. Add data quality validation in pipeline

---

## Model Bias Root Cause Analysis

### Finding 1: Vegas Lines Are Biased
Sportsbooks intentionally set conservative lines:

| Tier | Vegas Line | Actual | Vegas Bias |
|------|------------|--------|------------|
| Star | 22.2 | 30.4 | **-8.2** |
| Starter | 16.3 | 18.7 | -2.4 |
| Role | 10.8 | 9.5 | +1.3 |
| Bench | 7.3 | 2.2 | **+5.1** |

### Finding 2: Model Follows Vegas Too Closely
| Tier | Vegas Line | Model Pred | Difference |
|------|------------|------------|------------|
| Star | 22.2 | 21.1 | -1.1 |
| Starter | 16.3 | 15.9 | -0.4 |
| Role | 10.8 | 11.0 | +0.2 |
| Bench | 7.3 | 7.8 | +0.5 |

The model stays within 1-2 points of Vegas instead of learning when to diverge.

### Finding 3: Vegas Coverage Varies by Tier
| Tier | % with Vegas Props |
|------|-------------------|
| Star | 77.5% |
| Starter | 67.9% |
| Role | 46.7% |
| Bench | **16.0%** |

95% of training data has NO vegas line - model learns primarily from players without props.

---

## Tier Features: Band-Aid vs Real Fix

### The Argument Against Tier Features
From analysis document:
1. **Circular logic** - Tier derived from `points_avg_season` which model already has
2. **Doesn't explain variance** - Doesn't explain why star scores 40 one night, 25 another
3. **Same as calibration** - Just building calibration INTO model
4. **Masks real problem** - Should understand WHY model regresses

### Missing Mechanism Features
What actually explains scoring variance:

| Feature | Why It Matters | Data Source |
|---------|----------------|-------------|
| **Usage rate** | Stars have 30%+ usage | player_game_summary |
| **FGA (shot attempts)** | Volume of shots | player_game_summary |
| **FTA (free throws)** | Low variance points | player_game_summary |
| **Game total (O/U)** | Scoring environment | odds_api (we have) |
| **Spread** | Game script/minutes | odds_api (we have) |
| **Teammate injuries** | Usage spikes | Would need roster data |

### The Real Issue
Stars score more because:
1. They get more **opportunities** (usage, shot attempts)
2. They play more **minutes** (especially close games)
3. They get to the **free throw line** more

Our model knows the OUTCOME (averages 28) but not the MECHANISM (high usage, more FTA).

---

## Current Feature Architecture

### What We Have
| Component | Features |
|-----------|----------|
| Feature Store | 37 features available |
| V8/V9 Models | Use first 33 features |
| Unused | 4 trajectory features (indices 33-36) |

### Unused Trajectory Features
Already in feature store, not used in training:
- `dnp_rate` (index 33)
- `pts_slope_10g` (index 34)
- `pts_vs_season_zscore` (index 35)
- `breakout_flag` (index 36)

### What We Added This Session
In prediction records (metadata only, raw prediction unchanged):
- `scoring_tier`: 'star', 'starter', 'role', 'bench'
- `tier_adjustment`: +9, +3, -1.5, -5.5 suggested calibration

---

## Recommended Investigation Path

### Phase 1: Fix Data (P0)
1. Investigate BDL scraper bug
2. Backfill corrupted data from backup source
3. Add data quality checks to pipeline

### Phase 2: Understand Current Model
```python
# Extract feature importance from CatBoost V9
from catboost import CatBoostRegressor
model = CatBoostRegressor()
model.load_model('models/catboost_v9_2026_02.cbm')
importance = model.get_feature_importance()
```

Questions to answer:
- How much does model rely on `vegas_points_line`?
- What happens without Vegas features?

### Phase 3: Analyze Variance Drivers
```sql
-- What predicts over-performance for stars?
SELECT
  player_lookup, game_date, points,
  points - points_avg_season as over_avg,
  minutes_played, fga, fta, usage_pct
FROM nba_analytics.player_game_summary
WHERE points_avg_season >= 25  -- Stars
  AND points >= points_avg_season + 10  -- Big over-performance
ORDER BY over_avg DESC
```

### Phase 4: Feature Audit
Check if `usage_pct`, `fga`, `fta` are in player_game_summary and populated.

### Phase 5: Experiment
Based on findings:
- If Vegas-following → try Vegas-deviation feature
- If missing volume features → add usage_rate, fga
- If fundamental → consider tier-specific models

---

## Training Data Quality Validation

Before any model training, run `/spot-check-features` and check:

```sql
-- Deep validation: Find players with suspicious data
SELECT player_lookup, COUNT(*) as games,
  ROUND(AVG(features[OFFSET(0)]), 1) as avg_pts_l5,
  ROUND(STDDEV(features[OFFSET(0)]), 2) as std_pts_l5
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01' AND feature_count >= 33
GROUP BY 1 HAVING COUNT(*) >= 10
  AND (STDDEV(features[OFFSET(0)]) = 0 OR AVG(features[OFFSET(0)]) = 0)
```

### Temporary Training Filter
Until data is fixed:
```python
# Filter out corrupted data
df = df[df['features'].apply(lambda x: x[0] > 0)]  # points_avg_l5 > 0
```

---

## Files Changed This Session

| File | Change |
|------|--------|
| `predictions/worker/worker.py` | Added `scoring_tier`, `tier_adjustment` metadata |
| `.claude/skills/spot-check-features/SKILL.md` | Enhanced with tier checks |
| `docs/08-projects/current/feature-mismatch-investigation/` | Multiple analysis docs |

---

## Deployments

| Service | Status | Commit |
|---------|--------|--------|
| prediction-worker | ✅ Deployed | 6124a3fe |

---

## Key Documents

| Document | Purpose |
|----------|---------|
| `CRITICAL-DATA-BUG.md` | P0 data bug details |
| `MODEL-STRATEGY.md` | Feature architecture |
| `SESSION-103-ROOT-CAUSE-ANALYSIS.md` | Vegas bias analysis |
| `TIER-FEATURES-VS-MISSING-FEATURES.md` | Band-aid vs real fix analysis |

---

## Next Session Checklist

1. [ ] **P0: Fix BDL scraper** - Investigate why 40% of data is corrupted
2. [ ] **Backfill corrupted data** - Use ESPN or Basketball Reference as backup
3. [ ] **Check feature importance** - How much does V9 rely on Vegas?
4. [ ] **Audit player_game_summary** - Do we have usage_pct, fga, fta?
5. [ ] **Test trajectory features** - Try training with features 33-36
6. [ ] **Consider Vegas-deviation feature** - Instead of raw Vegas line

---

## Summary

**Don't just add tier features** - that's a band-aid that masks the real problem.

The model bias exists because:
1. Raw data is corrupted (P0 fix needed)
2. Model follows biased Vegas lines too closely
3. Missing mechanism features that explain scoring variance

**Fix order:**
1. Data quality first (corrupted data)
2. Then investigate Vegas-following behavior
3. Then audit/add mechanism features
4. Tier features only if fundamentally needed

---

**End of Handoff**
