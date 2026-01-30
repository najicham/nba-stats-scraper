# Session 35 Handoff - V8 Performance Degradation Investigation

**Date:** 2026-01-30
**Priority:** HIGH
**Status:** Investigation COMPLETE - See Session 36 Findings Below

---

## Executive Summary

V8 CatBoost model is performing significantly worse this season (2025-26) compared to last season (2024-25). However, **the highest confidence predictions are still performing well** - the degradation is coming from mid-tier confidence predictions.

---

## Performance Data

### Season Comparison

| Season | Predictions | MAE | Hit Rate |
|--------|-------------|-----|----------|
| 2024-25 | 17,498 | **4.04** | **56.5%** |
| 2025-26 | 4,921 | **5.62** | **48.8%** |

**Degradation: +39% MAE, -7.7% hit rate**

### Monthly Breakdown

| Month | Predictions | MAE | Hit Rate |
|-------|-------------|-----|----------|
| Nov 2024 | 2,431 | 3.92 | 58.9% |
| Dec 2024 | 2,694 | 4.09 | 57.0% |
| Jan 2025 | 3,282 | 4.00 | 55.5% |
| Feb 2025 | 2,642 | 4.19 | 53.8% |
| Mar 2025 | 3,484 | 4.12 | 56.5% |
| Apr 2025 | 2,215 | 4.03 | 57.5% |
| May 2025 | 618 | 3.60 | 59.5% |
| Jun 2025 | 132 | 3.21 | 54.5% |
| **Nov 2025** | 391 | **7.80** | **39.9%** |
| Dec 2025 | 2,022 | 5.51 | 57.5% |
| **Jan 2026** | 2,508 | **5.37** | **43.1%** |

### Confidence Decile Analysis (Key Finding)

| Month | Decile 10 (Top) | Decile 9 | Decile 10 Count | Decile 9 Count |
|-------|-----------------|----------|-----------------|----------------|
| Nov 2025 | 7.53 MAE | 10.81 MAE | 228 | 90 |
| Dec 2025 | 4.64 MAE | 8.40 MAE | 1,552 | 470 |
| **Jan 2026** | **3.61 MAE** | **6.19 MAE** | 793 | 1,715 |

**Critical Insight**: In January 2026:
- Top confidence (decile 10): MAE 3.61 (GOOD - matches last season)
- Next tier (decile 9): MAE 6.19 (BAD - dragging down average)
- Decile 9 has 2x more predictions than decile 10

---

## Data Quality Issues

### Missing Dates in January 2026

Games existed but no graded V8 predictions:
- Jan 8 (3 games)
- Jan 19 (9 games)
- Jan 21-25 (6-8 games each day)
- Jan 29 (8 games) - may just not be graded yet

**Feature store has data for these dates** - issue is in prediction generation pipeline.

### Prediction Generation Check

```sql
-- Predictions exist for some missing dates but low counts
SELECT game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
  AND game_date IN ('2026-01-21', '2026-01-22', '2026-01-23', '2026-01-24', '2026-01-25')
GROUP BY 1
ORDER BY 1;

-- Results:
-- 2026-01-22: 2 predictions (should be ~100+)
-- 2026-01-24: 44 predictions
-- 2026-01-25: 564 predictions
```

---

## Investigation Questions

### 1. Why is decile 9 performing so poorly?
- What distinguishes decile 9 from decile 10 predictions?
- Are there specific player types, matchups, or game contexts?
- Is the confidence calibration broken?

### 2. What happened in November 2025?
- MAE spiked from ~4.0 to 7.8
- Only 391 predictions (low volume)
- Was this a pipeline issue or model issue?

### 3. Why are predictions missing for Jan 21-25?
- Feature store has data
- Prediction coordinator/worker may have failed
- Check Cloud Run logs for those dates

### 4. Is the model drift or data drift?
- V8 model hasn't changed
- Are features calculating differently?
- Are player behaviors different this season?

---

## Suggested Investigation Steps

### Step 1: Analyze Decile 9 vs Decile 10

```sql
-- Compare characteristics of decile 9 vs 10 predictions
SELECT
  confidence_decile,
  AVG(line_value) as avg_line,
  AVG(predicted_points) as avg_predicted,
  AVG(actual_points) as avg_actual,
  AVG(ABS(predicted_points - line_value)) as avg_edge,
  COUNT(DISTINCT player_lookup) as unique_players
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-01'
  AND confidence_decile IN (9, 10)
GROUP BY 1;
```

### Step 2: Check Feature Quality This Season

```sql
-- Compare feature distributions this season vs last
SELECT
  CASE WHEN game_date < '2025-07-01' THEN '2024-25' ELSE '2025-26' END as season,
  AVG(features[OFFSET(0)]) as points_avg_last_5,
  AVG(features[OFFSET(5)]) as fatigue_score,
  AVG(features[OFFSET(25)]) as vegas_points_line
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2024-11-01'
GROUP BY 1;
```

### Step 3: Check Prediction Worker Logs

```bash
# Check logs for Jan 21-25
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-worker"
  AND timestamp >= "2026-01-21T00:00:00Z"
  AND timestamp <= "2026-01-26T00:00:00Z"
  AND severity >= WARNING' --limit=100
```

### Step 4: Check Specific Bad Predictions

```sql
-- Find worst predictions in decile 9
SELECT
  game_date,
  player_lookup,
  predicted_points,
  actual_points,
  absolute_error,
  line_value,
  confidence_score
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-01'
  AND confidence_decile = 9
ORDER BY absolute_error DESC
LIMIT 20;
```

---

## Session 35 Accomplishments (Context)

Before this investigation started, Session 35:
1. Removed V9 code (recency weighting failed)
2. Tested V11 seasonal features (also failed)
3. Confirmed V8 remains the best model architecture

The performance degradation is NOT about the model design - it's about data/pipeline issues.

---

## Files to Reference

- Grading queries: `docs/02-operations/runbooks/`
- Prediction worker: `predictions/worker/worker.py`
- V8 prediction system: `predictions/worker/prediction_systems/catboost_v8.py`
- Feature store processor: `data_processors/precompute/ml_feature_store/`

---

## Quick Commands

```bash
# Check recent V8 predictions
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8' AND game_date >= '2026-01-01'
GROUP BY 1 ORDER BY 1"

# Check prediction worker logs
gcloud logging read 'resource.labels.service_name="prediction-worker"' --limit=50

# Run daily validation
/validate-daily
```

---

## Session 36 Investigation Findings (2026-01-30)

### Data Validity Analysis

#### ✅ VALID DATA
| Check | Result |
|-------|--------|
| Actual points vs source | **100% match** - All graded actuals match `player_game_summary` |
| Impossible values | **None found** - No negative or extreme outliers |
| Hit calculation logic | **Correct** - Verified on sample |
| DNP verification | **Real DNPs** - Confirmed via minutes=0 in source |

#### ⚠️ DATA ISSUES FOUND

| Issue | Count | Impact | Action Required |
|-------|-------|--------|-----------------|
| Duplicate predictions | 20+ records | Minor - Nov-Dec 2025 | De-duplicate |
| NULL prediction_correct | 1,069 (22%) | Medium | Investigate cause |
| **2026-01-12 line bug** | 90 predictions | **HIGH** | **Re-grade** |

#### 🔴 CRITICAL: 2026-01-12 Grading Bug

The grading pipeline used **average of ALL prop types** instead of filtering for `market_type = 'points'`:

| Player | Graded Line | Correct Points Line | Error |
|--------|-------------|---------------------|-------|
| Luka Doncic | 11.9 | 34.5 | -22.6 |
| Cooper Flagg | 7.9 | 22.9 | -15.0 |
| Brandon Ingram | 7.2 | 20.5 | -13.3 |

**Action**: Re-grade 2026-01-12 predictions with correct line values.

**Bug Fix Applied (Session 36)**:
Added `market_type = 'points'` filter to 3 files:
- `data_processors/analytics/upcoming_player_game_context/queries/shared_ctes.py:212`
- `data_processors/analytics/upcoming_player_game_context/betting_data.py:185`
- `predictions/coordinator/player_loader.py:710,940`

---

### Root Cause: Decile 9 Degradation

**Conclusion**: The data is valid. The confidence calibration is the issue.

#### Season Comparison (Key Finding)
| Season | Decile 9 Hit Rate | Decile 10 Hit Rate |
|--------|-------------------|-------------------|
| 2024-25 | **57.6%** | 57.8% |
| 2025-26 | **42.3%** | 55.8% |

Last season decile 9 performed nearly identical to decile 10. This season it crashed to below coin-flip.

#### Why Decile 9 is Degraded

| Factor | Decile 9 | Decile 10 | Impact |
|--------|----------|-----------|--------|
| DNP Rate | **5.5%** | 1.5% | 3.7x higher DNP risk |
| Player Volatility | **7.27** std | 6.14 std | 18% more volatile players |
| OVER Prediction Bias | **+3.61** pts | +1.14 pts | 3x larger systematic error |
| MAE (excluding DNPs) | **5.76** | 3.47 | Still 2.3 pts worse |

**Root Cause**: The model assigns 84-89% confidence to volatile players with high DNP risk. The confidence formula (based on `feature_quality_score` + `points_std_last_10`) isn't penalizing volatility enough.

---

### Root Cause: Jan 21-25 Missing Predictions

**~63,000 HTTP 500 errors** from LINE QUALITY VALIDATION:

```
Issues: moving_average: line_value=20.0 (PLACEHOLDER),
zone_matchup_v1: line_value=20.0 (PLACEHOLDER),
catboost_v8: line_value=20.0 (PLACEHOLDER)...
```

**Cause**: Predictions blocked because `line_value=20.0` (placeholder value when no betting line exists).

**Location**: `predictions/worker/worker.py:348-415` - validation intentionally blocks 20.0 to prevent data corruption.

**Betting lines data exists** (54-131 players/day), but ~140-190 players/day lack lines and get estimated values, some hitting exactly 20.0.

---

### Confidence Score Analysis

| Confidence Range | Decile | Count | Avg MAE | Hit Rate |
|------------------|--------|-------|---------|----------|
| 0.84-0.89 | 9 | 1,715 | 6.19 | ~50% (coin-flip) |
| 0.90-0.95 | 10 | 793 | 3.61 | 65-68% |

The 0.90 threshold is the critical dividing line between good and poor performance.

---

### Challenger Procedure Reference

Before any model changes, follow the challenger framework at:
`docs/08-projects/current/ml-model-v8-deployment/CHAMPION-CHALLENGER-FRAMEWORK.md`

**Promotion Criteria:**
- ≥3% win rate improvement for 7+ days
- ≥0.2 MAE improvement
- ≥100 predictions sample size
- p < 0.05 statistical significance

---

### Recommended Actions (Do NOT Change Model Yet)

| Priority | Action | Rationale |
|----------|--------|-----------|
| **1** | Re-grade 2026-01-12 predictions | Fix invalid line values |
| **2** | Investigate NULL prediction_correct | 22% of records affected |
| **3** | De-duplicate Nov-Dec 2025 records | Data hygiene |
| **4** | Consider raising recommendation threshold to 0.90 | Quick win - filter out bad decile 9 |
| **5** | If modifying confidence formula, use challenger procedure | Requires backfill + 7-day comparison |

---

### Queries for Next Session

```sql
-- Find the grading bug source for 2026-01-12
SELECT * FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-01-12' AND system_id = 'catboost_v8'
LIMIT 10;

-- Check NULL prediction_correct records
SELECT game_date, COUNT(*) as nulls
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2025-11-01'
  AND prediction_correct IS NULL
GROUP BY 1
ORDER BY 1;

-- Verify duplicate records
SELECT player_lookup, game_date, COUNT(*)
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8' AND game_date >= '2025-11-01'
GROUP BY 1, 2
HAVING COUNT(*) > 1;
```

---

---

## Session 36 Prevention Mechanisms Added

### 1. Pre-commit Hook
**File**: `.pre-commit-hooks/validate_bettingpros_queries.py`
- Scans all Python code for queries against `bettingpros_player_points_props`
- Fails if `market_type='points'` filter is missing
- Prevents this bug from being committed again

### 2. Validation Query
**File**: `validation/queries/predictions/line_value_validation.sql`
- Compares graded `line_value` against raw betting data
- Flags discrepancies > 0.5 points as issues
- Can be run after grading to catch problems

### 3. Schema Documentation Updated
**File**: `schemas/bigquery/raw/bettingpros_player_props_tables.sql`
- Added warning that table contains ALL prop types despite name
- Example query showing required filter
- Reference to pre-commit hook

### 4. Code Fixes Applied
Files fixed with `market_type='points'` filter:
- `data_processors/analytics/upcoming_player_game_context/queries/shared_ctes.py:212`
- `data_processors/analytics/upcoming_player_game_context/betting_data.py:185`
- `predictions/coordinator/player_loader.py:710,940`

### 5. Re-graded 2026-01-12
- Deleted incorrect graded records
- Updated `player_prop_predictions.current_points_line` with correct values from raw data
- Re-ran grading with correct line values

---

## Files Modified This Session

```
# Bug fixes
data_processors/analytics/upcoming_player_game_context/queries/shared_ctes.py
data_processors/analytics/upcoming_player_game_context/betting_data.py
predictions/coordinator/player_loader.py

# Prevention mechanisms
.pre-commit-hooks/validate_bettingpros_queries.py (NEW)
.pre-commit-config.yaml
validation/queries/predictions/line_value_validation.sql (NEW)
schemas/bigquery/raw/bettingpros_player_props_tables.sql

# Documentation
docs/09-handoff/2026-01-30-SESSION-35-V8-DEGRADATION-INVESTIGATION.md
```

---

*Session 36 completed investigation. Data is valid except for 2026-01-12 grading bug (now fixed). Added prevention mechanisms to catch future issues. Model confidence calibration needs adjustment but must follow challenger procedure.*
