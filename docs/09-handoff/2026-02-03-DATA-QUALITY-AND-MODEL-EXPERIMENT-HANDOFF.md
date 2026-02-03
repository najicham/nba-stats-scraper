# Data Quality & Model Experiment Handoff

**Date:** 2026-02-03
**For:** Next Claude Code session
**Priority:** HIGH - Affects model training reliability

---

## Executive Summary

Session 101 discovered critical model bias issues. Investigation revealed that:
1. Model has **regression-to-mean bias** (-9 pts on stars, +6 pts on bench)
2. **Data provenance tracking is incomplete** - can't identify fallback/partial data
3. **Model experiments may train on low-quality data** without knowing it

This document outlines work needed to ensure model experiments produce reliable results.

---

## Problem 1: Model Bias Detection Gap

### Current State
- CatBoost V9 has -9.3 bias on stars, +5.6 bias on bench
- Overall bias ~0 (tiers cancel out)
- Existing monitoring missed this for weeks

### Root Cause
No tier-specific bias monitoring in model health checks or experiment evaluation.

### Session 101 Fixes Applied
- Added tier bias checks to: validate-daily, model-health, hit-rate-analysis, todays-predictions, top-picks, yesterdays-grading, trend-check
- Created `MODEL-BIAS-INVESTIGATION.md` documenting findings

### Remaining Work
**Add tier bias evaluation to `ml/experiments/quick_retrain.py`:**

Currently the script evaluates:
- MAE
- Hit rate (all)
- Hit rate (high edge 5+)
- Hit rate (premium 92+/3+)

**Should also evaluate:**
- Bias by player tier (Stars/Starters/Role/Bench)
- Flag if any tier bias > ±5 points

**Suggested code location:** After line 206 in `quick_retrain.py`, add tier bias computation.

---

## Problem 2: Data Provenance Tracking Gaps

### Current State

**Feature Store (`ml_feature_store_v2`):**
```sql
-- All recent records show "mixed" data source
SELECT data_source, COUNT(*) FROM ml_feature_store_v2
WHERE game_date >= '2025-11-01' GROUP BY 1

-- Result:
-- mixed: 23,953 records
-- phase4_partial: 8 records
-- NULL: 1 record
```

**Completeness tracking columns are NULL:**
```sql
-- source_daily_cache_completeness_pct: NULL for all
-- source_composite_completeness_pct: NULL for all
```

### Impact
1. **Can't filter training data** by quality/completeness
2. **Can't detect fallback data** that might degrade model
3. **Model experiments may include low-quality records** without warning

### Required Work

#### A. Enable Data Provenance Population

Files to investigate:
- `data_processors/precompute/ml_feature_store/` - Feature store processor
- Session 99 added provenance fields but they may not be populated

**Query to verify provenance is populating:**
```sql
SELECT
  game_date,
  COUNTIF(source_daily_cache_completeness_pct IS NOT NULL) as has_provenance,
  COUNTIF(source_daily_cache_completeness_pct IS NULL) as missing_provenance
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-02-01'
GROUP BY 1
```

#### B. Add Quality Filter to Model Training

In `ml/experiments/quick_retrain.py`, modify `load_train_data()`:

```python
# Current (line 126-137):
def load_train_data(client, start, end):
    query = f"""
    SELECT mf.features, pgs.points as actual_points
    FROM ml_feature_store_v2 mf
    JOIN player_game_summary pgs ON ...
    WHERE mf.game_date BETWEEN '{start}' AND '{end}'
      AND mf.feature_count >= 33
      AND pgs.points IS NOT NULL AND pgs.minutes_played > 0
    """

# Suggested addition - filter by quality:
    query = f"""
    SELECT mf.features, pgs.points as actual_points
    FROM ml_feature_store_v2 mf
    JOIN player_game_summary pgs ON ...
    WHERE mf.game_date BETWEEN '{start}' AND '{end}'
      AND mf.feature_count >= 33
      AND pgs.points IS NOT NULL AND pgs.minutes_played > 0
      AND mf.feature_quality_score >= 80  -- NEW: Quality filter
      AND mf.data_source != 'phase4_partial'  -- NEW: Exclude partial data
    """
```

#### C. Add Pre-Training Data Quality Report

Before training, output a quality summary:

```python
def check_training_data_quality(client, start, end):
    """Report on training data quality before training."""
    query = f"""
    SELECT
      COUNT(*) as total_records,
      COUNTIF(feature_quality_score >= 85) as high_quality,
      COUNTIF(feature_quality_score >= 70 AND feature_quality_score < 85) as medium_quality,
      COUNTIF(feature_quality_score < 70) as low_quality,
      COUNTIF(data_source = 'phase4_partial') as partial_data,
      ROUND(AVG(feature_quality_score), 1) as avg_quality
    FROM ml_feature_store_v2
    WHERE game_date BETWEEN '{start}' AND '{end}'
      AND feature_count >= 33
    """
    result = client.query(query).to_dataframe()

    print("\n=== Training Data Quality ===")
    print(f"Total records: {result['total_records'].iloc[0]:,}")
    print(f"High quality (85+): {result['high_quality'].iloc[0]:,}")
    print(f"Low quality (<70): {result['low_quality'].iloc[0]:,}")
    print(f"Partial data: {result['partial_data'].iloc[0]:,}")
    print(f"Avg quality score: {result['avg_quality'].iloc[0]}")

    if result['low_quality'].iloc[0] > result['total_records'].iloc[0] * 0.1:
        print("⚠️  WARNING: >10% low quality data in training set")
```

---

## Problem 3: Spot Check Skills Need Enhancement

### Current Spot Check Skills

| Skill | Purpose | Status |
|-------|---------|--------|
| `/spot-check-player` | Verify player game history | OK |
| `/spot-check-gaps` | Find system-wide data gaps | OK |
| `/spot-check-date` | Check all players for one date | OK |
| `/spot-check-team` | Check team roster completeness | OK |
| `/spot-check-cascade` | Track cascade impact of gaps | OK |

### Missing: Feature Store Quality Check

**Add `/spot-check-features` skill** to validate feature store data:

```markdown
# /spot-check-features - Feature Store Quality Validation

## Purpose
Validate feature store data quality before model training.

## Usage
/spot-check-features [date_range]

## Checks
1. Feature completeness (all 33 features populated)
2. Quality score distribution
3. Data source breakdown (mixed/partial/etc)
4. Vegas line coverage
5. Rolling average staleness
```

**Key Query:**
```sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(feature_quality_score >= 85) as high_quality,
  COUNTIF(features[OFFSET(25)] > 0) as has_vegas_line,
  COUNTIF(features[OFFSET(0)] > 0) as has_points_avg,
  data_source,
  ROUND(AVG(feature_quality_score), 1) as avg_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND feature_count >= 33
GROUP BY game_date, data_source
ORDER BY game_date DESC
```

---

## Problem 4: Analytics Data Quality

### Current State

`player_game_summary` tracks `primary_source_used`:
```sql
-- Recent data all from nbac_gamebook (good)
SELECT primary_source_used, COUNT(*)
FROM player_game_summary WHERE game_date >= '2026-01-25'
GROUP BY 1
-- Result: nbac_gamebook: all records
```

### Known Issue: 40% Records Have NULL Points

```sql
SELECT game_date,
  COUNTIF(points IS NULL) as null_points,
  COUNT(*) as total
FROM player_game_summary
WHERE game_date >= '2026-01-27'
GROUP BY 1
-- Result: 40-44% NULL points each day
```

**Finding from Session 101:** These are **legitimate DNPs** (bench players who didn't play), NOT data quality issues. The raw BDL data includes all rostered players (140/game) while only ~80 actually play.

### Verification Query
```sql
-- Confirm NULL points = DNP (0 minutes in raw data)
SELECT
  pgs.player_lookup,
  pgs.points,
  b.minutes
FROM nba_analytics.player_game_summary pgs
JOIN nba_raw.bdl_player_boxscores b
  ON pgs.player_lookup = b.player_lookup AND pgs.game_date = b.game_date
WHERE pgs.game_date = '2026-02-02'
  AND pgs.points IS NULL
LIMIT 10
-- Should show minutes = '00' for all
```

---

## Problem 5: Model Experiment Baseline Outdated

### Current State

`ml/experiments/quick_retrain.py` uses V8 baseline (line 54-60):
```python
V8_BASELINE = {
    "mae": 5.36,
    "hit_rate_all": 50.24,
    "hit_rate_premium": 78.5,  # 92+ conf, 3+ edge
    "hit_rate_high_edge": 62.8,  # 5+ edge
}
```

### Issues
1. V8 baseline is from January 2026 (outdated)
2. No V9 baseline defined
3. Doesn't track tier-specific performance

### Required Work

**Update to V9 baseline and add tier metrics:**

```python
# V9 baseline (updated Feb 2026)
V9_BASELINE = {
    "mae": None,  # TBD - need to compute
    "hit_rate_all": None,  # TBD
    "hit_rate_edge_3plus": 65.0,  # From CLAUDE.md
    "hit_rate_edge_5plus": 79.0,  # From CLAUDE.md
    # NEW: Tier-specific baselines
    "bias_stars": 0.0,  # Target: no bias
    "bias_starters": 0.0,
    "bias_role": 0.0,
    "bias_bench": 0.0,
}
```

**Query to compute V9 baseline:**
```sql
SELECT
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 2) as hit_rate_all,
  ROUND(100.0 * COUNTIF(prediction_correct AND ABS(predicted_points - line_value) >= 3) /
    NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 2) as hit_rate_edge_3plus,
  ROUND(100.0 * COUNTIF(prediction_correct AND ABS(predicted_points - line_value) >= 5) /
    NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 5), 0), 2) as hit_rate_edge_5plus
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= '2026-01-31'  -- V9 start date
  AND recommendation IN ('OVER', 'UNDER')
```

---

## Implementation Checklist

### Priority 1: Model Experiment Reliability
- [ ] Add tier bias evaluation to `quick_retrain.py`
- [ ] Add quality filter to training data query
- [ ] Add pre-training data quality report
- [ ] Update V8 baseline to V9 baseline

### Priority 2: Data Provenance
- [ ] Investigate why provenance columns are NULL
- [ ] Fix feature store processor to populate provenance
- [ ] Add provenance checks to model training

### Priority 3: Spot Check Enhancement
- [ ] Create `/spot-check-features` skill
- [ ] Add feature quality trending to `/validate-daily`
- [ ] Add model bias check to post-training evaluation

### Priority 4: Documentation
- [ ] Update model-experiment skill with quality checks
- [ ] Document V9 baseline computation
- [ ] Add tier bias thresholds to training evaluation

---

## Key Files

| File | Purpose | Changes Needed |
|------|---------|----------------|
| `ml/experiments/quick_retrain.py` | Model training | Add quality filter, tier bias eval |
| `data_processors/precompute/ml_feature_store/` | Feature store | Fix provenance population |
| `.claude/skills/model-experiment/SKILL.md` | Skill docs | Add quality check instructions |
| `.claude/skills/spot-check-*.md` | Spot checks | Add feature quality skill |

---

## Validation Queries

### 1. Check Feature Store Quality Distribution
```sql
SELECT
  CASE
    WHEN feature_quality_score >= 85 THEN 'High (85+)'
    WHEN feature_quality_score >= 70 THEN 'Medium (70-84)'
    ELSE 'Low (<70)'
  END as quality_tier,
  COUNT(*) as records,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-15'
  AND feature_count >= 33
GROUP BY 1
ORDER BY 1
```

### 2. Check Vegas Line Coverage in Training Data
```sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(features[OFFSET(25)] > 0) as has_vegas,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-15'
  AND feature_count >= 33
GROUP BY 1
ORDER BY 1 DESC
```

### 3. Check for Tier Bias in Current Model
```sql
SELECT
  CASE
    WHEN actual_points >= 25 THEN 'Stars (25+)'
    WHEN actual_points >= 15 THEN 'Starters (15-24)'
    WHEN actual_points >= 5 THEN 'Role (5-14)'
    ELSE 'Bench (<5)'
  END as tier,
  COUNT(*) as predictions,
  ROUND(AVG(predicted_points - actual_points), 1) as bias,
  CASE WHEN ABS(AVG(predicted_points - actual_points)) > 5 THEN '🔴 CRITICAL' ELSE '✅ OK' END as status
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY 1
ORDER BY 1
```

---

## Related Documents

- `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md` - Session 101 bias analysis
- `docs/09-handoff/2026-02-03-SESSION-101-CONTINUED-HANDOFF.md` - Session 101 handoff
- `CLAUDE.md` - Model performance expectations (edge >= 3: 65%, edge >= 5: 79%)

---

## Quick Start for Next Session

```bash
# 1. Check current feature store quality
bq query --use_legacy_sql=false "
SELECT data_source, ROUND(AVG(feature_quality_score),1) as avg_quality, COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-25' GROUP BY 1"

# 2. Check if provenance is being populated
bq query --use_legacy_sql=false "
SELECT COUNTIF(source_daily_cache_completeness_pct IS NOT NULL) as has_provenance
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-02-01'"

# 3. Check tier bias in current model
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN actual_points >= 25 THEN 'Stars' ELSE 'Other' END as tier,
  ROUND(AVG(predicted_points - actual_points), 1) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND game_date >= '2026-01-20'
GROUP BY 1"

# 4. Read the key files
cat ml/experiments/quick_retrain.py | head -100
cat data_processors/precompute/ml_feature_store/*.py | grep -A10 "data_source\|provenance"
```

---

**End of Handoff**
