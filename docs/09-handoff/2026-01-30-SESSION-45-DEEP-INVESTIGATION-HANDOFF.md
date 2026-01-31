# Session 45 Handoff - Deep Investigation of Model Performance

**Date:** 2026-01-30
**Duration:** ~1 hour
**Focus:** Comprehensive multi-agent investigation of model drift and performance collapse
**Status:** Investigation complete, strategic decisions needed

---

## Executive Summary

Session 45 conducted a deep investigation into the CatBoost V8 model performance collapse using 6 parallel investigation agents. The investigation revealed **data corruption** as the primary root cause.

### The Critical Finding

**DNP (Did Not Play) players are being recorded with `points = 0` instead of `NULL`, corrupting 32.7% of January 2026 data and causing star player features to be artificially lowered.**

This explains:
- Why stars are under-predicted by 10+ points (their features show 0s)
- Why the model collapsed on Jan 9 (V8 deployed with corrupted data)
- Why training MAE (4.02) differs from production MAE (5.5+)

### Secondary Finding

**The model has NEVER had sustained edge over Vegas lines across 277,000+ predictions over 4+ years.**

| Season | Line MAE | Model MAE | Model Edge |
|--------|----------|-----------|------------|
| 2021-22 | 5.03 | 5.13 | **-0.10** |
| 2022-23 | 5.08 | 5.23 | **-0.16** |
| 2023-24 | 4.95 | 5.20 | **-0.25** |
| 2024-25 | 4.90 | 5.15 | **-0.25** |
| 2025-26 | 5.15 | 5.59 | **-0.44** |

This is not a recent drift - it's a fundamental limitation that has worsened over time.

---

## Investigation Findings

### 1. Sportsbook Line Analysis

**Finding:** Lines haven't gotten more accurate - the model has gotten worse.

- Line MAE: Stable at ~5.0 pts across all seasons
- Model MAE: Degraded from 5.13 → 5.59 (9% worse)
- Model-line correlation: Dropped from 0.857 → 0.803
- Model deviation from lines: Increased from 2.97 → 3.43 pts

**Critical Insight:** The model is making LARGER deviations from lines this season, but these deviations are HURTING not helping performance.

**Line Movement Impact:**
| Line Movement | Model Edge |
|---------------|------------|
| Minimal (<0.5 pts) | **+0.03** ✓ |
| Large (>3 pts) | **-0.62** ✗ |

The model only shows positive edge on games with minimal line movement.

### 2. Player Cohort Analysis

**Finding:** Regime shift between December and January for star players.

| Month | Star Lines | Star Actual | Line Error |
|-------|------------|-------------|------------|
| December | Underestimated | Higher | **-0.68** |
| January | **Overestimated** | Lower | **+0.40** |

**Most Affected Players (January 2026):**
| Player | Avg Line | Avg Actual | Overestimate |
|--------|----------|------------|--------------|
| Brandon Ingram | 22.8 | 13.2 | **+9.63** |
| Jalen Brunson | 28.5 | 19.8 | **+8.75** |
| Stephen Curry | 28.2 | 19.8 | **+8.41** |

**Tier Performance:**
| Tier | Hit Rate | Bias |
|------|----------|------|
| Stars (25+ pts) | **30%** | -10.26 |
| Bench (<5 pts) | 58% | +5.36 |

**Surprising Finding:** Star OVER bets have 62% hit rate - the model correctly identifies star OVERs, but confidence calibration doesn't account for this.

### 3. Feature Store Code Issues

**Finding:** Multiple code bugs that could contribute to performance degradation.

**Bug 1: 30-Day Window Approximation (MAJOR)**
```python
# Current: Uses 30-day window
WHERE game_date >= DATE_SUB('{game_date}', INTERVAL 30 DAY)
# Should: Use actual last 10 games
```
Impact: 10.9% feature importance (minutes/PPM)

**Bug 2: DNP Filtering Inflates PPM (MAJOR)**
```python
WHERE minutes_played > 0  # Removes DNP games!
```
Impact: 14.6% feature importance

**Bug 3: Missing Points = 0 (HIGH)**
```python
points_list = [(g.get('points') or 0) for g in last_10_games]
```
Impact: 45% feature importance

**Bug 4: L5/L10 Data Leakage (FIXED)**
- Fixed in commit b3406785 (Jan 29)
- 8,456 records had incorrect values

### 4. Experiments Already Failed

| Experiment | Result |
|------------|--------|
| V9 Recency Weighting | All variants WORSE |
| V11 Seasonal Features | 0.86% WORSE |

Time-based features do not help.

---

## CRITICAL: Collapse Date Identified - January 9, 2026

The confidence calibration investigation found the **exact moment** performance collapsed:

| Date | 90%+ Confidence Hit Rate | Overall Hit Rate |
|------|-------------------------|------------------|
| Before Jan 9 | **57.6%** | 53.4% |
| Jan 7 | 59.2% | - |
| **Jan 9** | **29.6%** | 34.6% |
| After Jan 9 | 34.8% | ~35-38% |

**The collapse was sudden, not gradual!**

### Changes Deployed January 7-9
1. `feat(predictions): Switch production to catboost_v8 with champion/challenger framework`
2. `feat(filtering): Implement 88-90 confidence tier filtering with shadow tracking`
3. Various feature store and pipeline changes

### Calibration Is Inverted
After Jan 9, confidence has no predictive value:
- 90%+ confidence: 34.8% hit rate
- 70-80% confidence: **43.4%** hit rate (higher!)

### No Actual Calibration Implemented
Code shows `calibration_method = 'none'` - no Platt scaling or isotonic regression.

---

## Root Causes (Ranked by Impact)

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| **0** | **DNP = 0 instead of NULL (DATA CORRUPTION)** | **CRITICAL** | **FIX FIRST** |
| 1 | Jan 7-9 deployment used corrupted data | CRITICAL | Explains collapse |
| 2 | Model never had edge vs Vegas | CRITICAL | Structural |
| 3 | Star player lines inflated | HIGH | Market shift |
| 4 | CatBoost V8 OVER predictions overshoot +3.23 pts | HIGH | Model bias |
| 5 | 30-day window approximation | HIGH | Code bug - FIXABLE |
| 6 | DNP filtering inflates PPM | MEDIUM | Code bug - FIXABLE |
| 7 | Missing points = 0 in averages | MEDIUM | Code bug - FIXABLE |
| 8 | Large line movements hurt model | MEDIUM | Feature gap |
| 9 | No confidence calibration | MEDIUM | Missing feature |

### Data Corruption Details

**Evidence:**
- Jan 2026: 32.7% zero-point games (vs 10-12% historical)
- Jan 27: 105 zero-point records, 0 DNP marked
- Jan 26: 113 zero-point records, 0 DNP marked

**Impact:**
- `points_avg_last_5` mean: 10.53 → 8.49 (-19.4%)
- Star players showing `points_avg_last_5 = 0.0`
- Model under-predicts because features are artificially lowered

---

## Strategic Options

### Option A: Fix Data Issues & Re-evaluate (Recommended)
1. Fix code bugs (30-day window, DNP, missing points)
2. Retrain model with clean data
3. Measure if fixes restore any edge
4. **Effort:** Medium | **Timeline:** 1-2 weeks

### Option B: Niche Strategy - Minimal Line Movement
1. Only predict when line movement < 0.5 pts
2. Model shows +0.03 edge in this niche
3. Severely limits prediction volume (~5% of games)
4. **Effort:** Low | **Timeline:** Days

### Option C: Accept Market Efficiency
1. Use model for information/analysis only
2. Stop treating predictions as actionable
3. Focus on trend analysis, injury detection
4. **Effort:** None | **Timeline:** Immediate

### Option D: Major Model Redesign
1. Tier-specific models (stars vs bench)
2. Heavy line integration (>4% importance)
3. Line movement features
4. **Effort:** Very High | **Timeline:** Months

---

## Code Bugs to Fix

### 1. Fix 30-Day Window (feature_extractor.py)

**Location:** `data_processors/precompute/ml_feature_store/feature_extractor.py` lines 700-748

**Current:**
```python
WHERE game_date >= DATE_SUB('{game_date}', INTERVAL 30 DAY)
```

**Should be:**
```python
-- Use actual last 10 games with ROW_NUMBER
WITH ranked_games AS (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
  FROM nba_analytics.player_game_summary
  WHERE game_date < '{game_date}'
)
SELECT ... FROM ranked_games WHERE rn <= 10
```

### 2. Fix DNP Filtering (feature_extractor.py)

**Current:**
```python
WHERE minutes_played > 0  # Excludes DNP games
```

**Should be:**
```python
-- Include all games, handle DNP in calculation
-- Or use conditional aggregation
AVG(CASE WHEN minutes_played > 0 THEN minutes_played ELSE NULL END)
```

### 3. Fix Missing Points Handling (feature_extractor.py)

**Current:**
```python
points_list = [(g.get('points') or 0) for g in last_10_games]
```

**Should be:**
```python
points_list = [g.get('points') for g in last_10_games if g.get('points') is not None]
```

---

## Monitoring Additions Needed

1. **Vegas Edge Tracking** - Alert when edge drops below -0.5
2. **Tier-Specific Hit Rate** - Monitor star player accuracy separately
3. **Line Movement Analysis** - Track performance by movement bucket
4. **Model Deviation Tracking** - Monitor pred-line correlation

---

## Files to Review

| File | Purpose |
|------|---------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | 30-day window, DNP, missing points bugs |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Default values |
| `predictions/worker/prediction_systems/catboost_v8.py` | Feature loading |

---

## Key Queries

### Check Model Edge by Season
```sql
SELECT
  CASE
    WHEN game_date >= '2025-11-01' THEN '2025-26'
    WHEN game_date >= '2024-11-01' THEN '2024-25'
    ELSE 'Earlier'
  END as season,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as line_mae,
  ROUND(AVG(absolute_error), 2) as model_mae,
  ROUND(AVG(ABS(line_value - actual_points)) - AVG(absolute_error), 2) as model_edge
FROM nba_predictions.prediction_accuracy
WHERE line_value IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

### Check Star Player Performance
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  AVG(actual_points) as avg_actual,
  AVG(line_value) as avg_line,
  AVG(line_value - actual_points) as line_overestimate
FROM nba_predictions.prediction_accuracy
WHERE actual_points >= 20  -- Stars
  AND game_date >= '2025-12-01'
GROUP BY 1
ORDER BY 1 DESC;
```

---

## Uncommitted Changes

```
M .pre-commit-hooks/check_import_paths.py
M data_processors/analytics/upcoming_player_game_context/calculators/__init__.py
M data_processors/analytics/upcoming_player_game_context/calculators/context_builder.py
M data_processors/analytics/upcoming_player_game_context/team_context.py
M docs/09-handoff/2026-01-30-SESSION-34-CATBOOST-V9-EXPERIMENTS-HANDOFF.md
?? data_processors/analytics/upcoming_player_game_context/calculators/schedule_context_calculator.py
?? docs/08-projects/current/2026-01-30-session-44-maintenance/
?? docs/09-handoff/2026-01-30-SESSION-43-VERIFICATION-AND-FIXES-HANDOFF.md
?? docs/09-handoff/2026-01-30-SESSION-44-INVESTIGATION-HANDOFF.md
?? ml/experiments/results/catboost_v11_*.json
```

---

## Next Session Priorities

1. **DECISION NEEDED:** Choose strategic option (A, B, C, or D)
2. If Option A: Fix code bugs in feature_extractor.py
3. Add Vegas edge monitoring to daily validation
4. Commit investigation documentation
5. Review uncommitted schedule_context_calculator.py

---

## Key Learnings

1. **Always verify edge vs baseline** - The model was never validated against Vegas lines historically
2. **Market efficiency is real** - Vegas has more data and resources
3. **Code bugs compound** - Multiple small bugs in feature calculation add up
4. **Time-based features don't work** - Both recency and seasonality failed
5. **Tier-specific behavior matters** - Stars and bench require different handling

---

## Session 45 Complete

Comprehensive investigation done. Strategic decision needed before proceeding with fixes.

*Investigation conducted with 6 parallel agents analyzing: feature drift, confidence calibration, sportsbook lines, OVER/UNDER bias, feature store code, and player cohorts.*
