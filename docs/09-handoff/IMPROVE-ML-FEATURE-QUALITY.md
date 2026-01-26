# Improve ML Feature Quality

**Type:** Critical Enhancement
**Priority:** High
**Estimated Effort:** 6-8 hours (split into phases)
**Model:** Sonnet recommended (Opus for Phase 1 investigation)

---

## Executive Summary

A comprehensive audit of the ML feature store revealed critical data quality issues that significantly impact prediction accuracy. The most severe finding: **95.8% of minutes data and 100% of usage rate data are NULL**, meaning the model is learning from imputed defaults rather than real data.

This document outlines a systematic approach to fix data pipeline issues, improve default handling, and add visibility into feature quality.

---

## Critical Findings

### Severity: CRITICAL (P0)

| Issue | Impact | Root Cause |
|-------|--------|------------|
| `minutes_avg_last_10` is 95.8% NULL | Model uses 28.0 default for almost all players | Upstream pipeline issue in player_game_summary |
| `usage_rate_last_10` is 100% NULL | Feature is completely broken | Field never populated |

### Severity: HIGH (P1)

| Issue | Impact | Root Cause |
|-------|--------|------------|
| Vegas lines fallback to season_avg | Circular dependency (feature 25 uses features 0-2) | Poor fallback design |
| XGBoost vs CatBoost default mismatch | Inconsistent predictions between models | Code divergence |
| Shot zones use league averages | Hides missingness from model | Discussed in separate doc |

### Severity: MEDIUM (P2)

| Issue | Impact | Root Cause |
|-------|--------|------------|
| Points defaults at 10.0 | Slightly biased (should be ~15 league median) | Arbitrary default |
| High feature redundancy (0.96+ correlation) | Wasted model capacity | No feature selection |
| Outdated shot zone distribution | 30/20/35 vs modern 25/15/45 | Stale defaults |

---

## Phase 1: Investigate Data Pipeline Issues (P0)

**Goal:** Find and fix why minutes and usage rate are almost entirely NULL.

### Task 1.1: Investigate minutes_played NULL Issue

**Symptom:** `minutes_avg_last_10` is 95.8% NULL in ml_feature_store_v2

**Investigation Steps:**

1. **Check source table (player_game_summary):**
```sql
-- How many records have minutes_played?
SELECT
    COUNT(*) as total,
    COUNTIF(minutes_played IS NOT NULL) as has_minutes,
    COUNTIF(minutes_played IS NULL) as missing_minutes,
    ROUND(100.0 * COUNTIF(minutes_played IS NULL) / COUNT(*), 1) as pct_missing
FROM `nba_analytics.player_game_summary`
WHERE game_date >= '2024-10-01'
```

2. **Check raw source (gamebook or boxscore):**
```sql
-- Does raw data have minutes?
SELECT
    COUNT(*) as total,
    COUNTIF(minutes IS NOT NULL OR min IS NOT NULL) as has_minutes
FROM `nba_raw.nbac_gamebook_player_stats`
WHERE game_date >= '2024-10-01'
```

3. **Trace the pipeline:**
   - File: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
   - Find where `minutes_played` is extracted
   - Check if field name changed or extraction is broken

**Likely Root Causes:**
- Field name mismatch (e.g., `min` vs `minutes` vs `minutes_played`)
- Source table changed schema
- Extraction logic has a bug
- Field exists but isn't being propagated

**Fix Location:** `data_processors/analytics/player_game_summary/`

### Task 1.2: Investigate usage_rate NULL Issue

**Symptom:** `usage_rate_last_10` is 100% NULL - never populated

**Investigation Steps:**

1. **Check if field exists in source:**
```sql
SELECT column_name
FROM `nba_analytics.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'player_game_summary'
AND column_name LIKE '%usage%'
```

2. **Check if it's calculated or sourced:**
   - Search codebase: `grep -r "usage_rate" data_processors/`
   - Is it supposed to come from raw data or be calculated?

3. **Check feature store extraction:**
   - File: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
   - Find where `usage_rate_last_10` is extracted
   - Is it looking for the right field?

**Likely Root Causes:**
- Feature was planned but never implemented
- Source field has different name
- Calculation depends on data that doesn't exist

**Fix Options:**
- A) Implement usage rate calculation from play-by-play
- B) Remove feature from model if data unavailable
- C) Source from alternative data (e.g., Basketball Reference)

### Task 1.3: Check Other High-NULL Features

Run this query to find all features with high NULL rates:

```sql
SELECT
    'fatigue_score' as feature,
    ROUND(100.0 * COUNTIF(fatigue_score IS NULL) / COUNT(*), 1) as pct_null
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= '2024-10-01'
UNION ALL
SELECT 'pace_score', ROUND(100.0 * COUNTIF(pace_score IS NULL) / COUNT(*), 1)
FROM `nba_predictions.ml_feature_store_v2` WHERE game_date >= '2024-10-01'
UNION ALL
SELECT 'shot_zone_mismatch_score', ROUND(100.0 * COUNTIF(shot_zone_mismatch_score IS NULL) / COUNT(*), 1)
FROM `nba_predictions.ml_feature_store_v2` WHERE game_date >= '2024-10-01'
UNION ALL
SELECT 'team_pace_last_10', ROUND(100.0 * COUNTIF(team_pace_last_10 IS NULL) / COUNT(*), 1)
FROM `nba_predictions.ml_feature_store_v2` WHERE game_date >= '2024-10-01'
UNION ALL
SELECT 'team_off_rating_last_10', ROUND(100.0 * COUNTIF(team_off_rating_last_10 IS NULL) / COUNT(*), 1)
FROM `nba_predictions.ml_feature_store_v2` WHERE game_date >= '2024-10-01'
UNION ALL
SELECT 'opponent_def_rating', ROUND(100.0 * COUNTIF(opponent_def_rating IS NULL) / COUNT(*), 1)
FROM `nba_predictions.ml_feature_store_v2` WHERE game_date >= '2024-10-01'
ORDER BY pct_null DESC
```

**Expected Results (from prior analysis):**
| Feature | NULL % |
|---------|--------|
| minutes_avg_last_10 | 95.8% |
| usage_rate_last_10 | 100% |
| team_pace_last_10 | 36.7% |
| team_off_rating_last_10 | 36.7% |
| fatigue_score | 11.6% |

For each >10% NULL, investigate and document root cause.

---

## Phase 2: Fix Default Value Issues (P1)

**Goal:** Improve how missing data is handled in feature extraction.

### Task 2.1: Fix Vegas Line Circular Fallback

**Current Problem:**
```python
# ml_feature_store_processor.py lines ~1199-1215
fallback_line = phase4_data.get('points_avg_season', phase3_data.get('points_avg_season', 15.0))
vegas_points_line = vegas_data.get('vegas_points_line', fallback_line)
```

This uses the player's season average as fallback for Vegas line - creating circular dependency where feature 25 depends on features 0-2.

**Fix:**
```python
# Option A: Use NULL with indicator
vegas_points_line = vegas_data.get('vegas_points_line')  # Can be None
has_vegas_line = 1.0 if vegas_points_line is not None else 0.0

# Option B: Use league median (not player-specific)
LEAGUE_MEDIAN_POINTS_LINE = 18.5  # Based on historical data
vegas_points_line = vegas_data.get('vegas_points_line', LEAGUE_MEDIAN_POINTS_LINE)
```

**Recommended:** Option A (NULL with indicator) - already have `has_vegas_line` feature (#28)

**Files to Update:**
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

### Task 2.2: Fix XGBoost vs CatBoost Default Mismatch

**Current Problem:**
| Feature | Feature Store | CatBoost | XGBoost |
|---------|--------------|----------|---------|
| points_avg_last_5 | 10.0 | 10.0 | **0.0** |
| points_avg_last_10 | 10.0 | 10.0 | **0.0** |
| points_avg_season | 10.0 | 10.0 | **0.0** |

**Root Cause:** XGBoost prediction system has different default handling.

**Fix:** Standardize all defaults in feature store, not in prediction systems.

**File:** `predictions/worker/prediction_systems/xgboost_v1.py`

```python
# Change from:
features.get('points_avg_last_5', 0),

# To:
features.get('points_avg_last_5', 10.0),  # Match feature store default

# OR better - don't override, trust feature store:
features['points_avg_last_5'],  # Will already have default from feature store
```

**Files to Update:**
- `predictions/worker/prediction_systems/xgboost_v1.py` (~lines 148-230)
- `predictions/worker/prediction_systems/catboost_v8.py` (verify consistency)
- `predictions/worker/prediction_systems/ensemble_v1.py` (verify consistency)

### Task 2.3: Add Missingness Indicators

**Goal:** Let the model know when data is missing instead of hiding it.

**Current features to add indicators for:**

| Feature | Add Indicator | Indicator Name |
|---------|--------------|----------------|
| minutes_avg_last_10 | YES | `has_minutes_data` |
| vegas_points_line | Already exists | `has_vegas_line` (#28) |
| shot zones (18-20) | YES | `has_shot_zone_data` |
| opponent history (29) | YES | `has_opponent_history` |

**Implementation Pattern:**
```python
# In ml_feature_store_processor.py

# For minutes
minutes_avg = self._get_feature_nullable('minutes_avg_last_10', phase4_data, phase3_data)
features.append(minutes_avg if minutes_avg is not None else 28.0)  # Keep default for now
features.append(1.0 if minutes_avg is not None else 0.0)  # NEW: indicator

# For shot zones
paint_rate = self._get_feature_nullable('paint_rate_last_10', phase4_data, phase3_data)
mid_rate = self._get_feature_nullable('mid_range_rate_last_10', phase4_data, phase3_data)
three_rate = self._get_feature_nullable('three_pt_rate_last_10', phase4_data, phase3_data)
has_shot_zone = all(x is not None for x in [paint_rate, mid_rate, three_rate])
features.append(1.0 if has_shot_zone else 0.0)  # NEW: indicator
```

**Note:** Adding new features requires model retraining. Consider adding indicators now but not using them until next model version.

---

## Phase 3: Improve Defaults (P2)

### Task 3.1: Update Points Defaults

**Current:** 10.0 (arbitrary, below league median)
**Proposed:** 15.0 (closer to league median)

```python
# ml_feature_store_processor.py
# Change:
features.append(self._get_feature_with_fallback(0, 'points_avg_last_5', ..., 10.0, ...))
# To:
features.append(self._get_feature_with_fallback(0, 'points_avg_last_5', ..., 15.0, ...))
```

**Impact:** Low - only affects players with no historical data (rare in production)

### Task 3.2: Update Shot Zone Defaults

**Current:** 30% paint, 20% mid-range, 35% three
**Proposed:** 25% paint, 15% mid-range, 45% three (modern NBA distribution)

Or better: Use NULL with `has_shot_zone_data` indicator (see IMPROVE-SHOT-ZONE-HANDLING.md)

### Task 3.3: Document All Defaults

Create a feature catalog documenting every default:

**File to create:** `docs/05-ml/features/FEATURE-DEFAULTS.md`

```markdown
# ML Feature Defaults Reference

| Index | Feature | Default | Rationale | Indicator |
|-------|---------|---------|-----------|-----------|
| 0 | points_avg_last_5 | 15.0 | League median | has_points_history |
| 1 | points_avg_last_10 | 15.0 | League median | has_points_history |
| ... | ... | ... | ... | ... |
```

---

## Phase 4: Add Visibility & Monitoring

### Task 4.1: Create Feature Quality Dashboard Query

**File:** `services/admin_dashboard/services/bigquery_service.py`

```python
def get_feature_quality_metrics(self, game_date: str) -> Dict:
    """Get NULL rates for all ML features."""
    query = f"""
    SELECT
        '{game_date}' as game_date,
        COUNT(*) as total_records,
        -- Points features
        ROUND(100.0 * COUNTIF(points_avg_last_5 IS NULL) / COUNT(*), 1) as points_avg_last_5_null_pct,
        ROUND(100.0 * COUNTIF(points_avg_last_10 IS NULL) / COUNT(*), 1) as points_avg_last_10_null_pct,
        -- Minutes features
        ROUND(100.0 * COUNTIF(minutes_avg_last_10 IS NULL) / COUNT(*), 1) as minutes_null_pct,
        -- Composite features
        ROUND(100.0 * COUNTIF(fatigue_score IS NULL) / COUNT(*), 1) as fatigue_null_pct,
        ROUND(100.0 * COUNTIF(shot_zone_mismatch_score IS NULL) / COUNT(*), 1) as shot_zone_null_pct,
        -- Team features
        ROUND(100.0 * COUNTIF(team_pace_last_10 IS NULL) / COUNT(*), 1) as team_pace_null_pct,
        -- Vegas features
        ROUND(100.0 * COUNTIF(vegas_points_line IS NULL) / COUNT(*), 1) as vegas_null_pct
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date = '{game_date}'
    """
    return self._execute_query(query)
```

### Task 4.2: Add to Daily Validation

**File:** `scripts/validate_tonight_data.py`

```python
def check_feature_quality(self, game_date: str) -> ValidationResult:
    """Check ML feature NULL rates."""
    metrics = self.bq_service.get_feature_quality_metrics(game_date)

    issues = []
    # Alert thresholds
    if metrics['minutes_null_pct'] > 50:
        issues.append(f"CRITICAL: minutes_avg_last_10 is {metrics['minutes_null_pct']}% NULL")
    if metrics['fatigue_null_pct'] > 20:
        issues.append(f"WARNING: fatigue_score is {metrics['fatigue_null_pct']}% NULL")
    if metrics['vegas_null_pct'] > 30:
        issues.append(f"WARNING: vegas_points_line is {metrics['vegas_null_pct']}% NULL")

    return ValidationResult(
        check_name='feature_quality',
        passed=len([i for i in issues if 'CRITICAL' in i]) == 0,
        message=f"Feature quality check: {len(issues)} issues",
        issues=issues
    )
```

### Task 4.3: Create Feature Quality Report

**File to create:** `bin/reports/feature_quality_report.py`

Script that generates a comprehensive feature quality report:
- NULL rates by feature
- Trend over last 30 days
- Comparison to expected thresholds
- Recommendations for investigation

---

## Phase 5: Model Retraining Preparation

After fixing data issues and defaults, the model should be retrained.

### Task 5.1: Document Feature Changes

Before retraining, document all changes in:
- `ml/CHANGELOG.md` or similar
- Include: old default → new default, rationale

### Task 5.2: Create Training Data Audit

```python
# ml/audit_training_data.py
# Script to verify training data quality before retraining
# - Check NULL rates in training set
# - Verify no circular dependencies
# - Confirm indicator features populated
```

### Task 5.3: A/B Test New Defaults

Use shadow mode to test new defaults:
1. Deploy new feature store logic
2. Run predictions with both old and new defaults
3. Compare accuracy on graded predictions
4. Promote if improvement confirmed

---

## Success Criteria

### Phase 1 (Data Pipeline)
- [ ] Root cause identified for minutes_avg_last_10 95.8% NULL
- [ ] Root cause identified for usage_rate_last_10 100% NULL
- [ ] Fix deployed, NULL rates drop to <10%
- [ ] All features >10% NULL documented with root cause

### Phase 2 (Default Values)
- [ ] Vegas line no longer uses season_avg as fallback
- [ ] XGBoost and CatBoost use identical defaults
- [ ] Missingness indicators added for key features

### Phase 3 (Improved Defaults)
- [ ] Points defaults updated to 15.0
- [ ] Shot zone defaults updated (or using NULL + indicator)
- [ ] Feature defaults documented in catalog

### Phase 4 (Visibility)
- [ ] Feature quality metrics in admin dashboard
- [ ] Daily validation includes feature quality check
- [ ] Feature quality report script created

### Phase 5 (Model Prep)
- [ ] All changes documented for model retraining
- [ ] Training data audit script created
- [ ] Shadow mode comparison planned

---

## Documentation Updates Required

After completing this work, update:

1. **Feature Catalog**
   - File: `docs/05-ml/features/FEATURE-DEFAULTS.md` (create)
   - Content: All 33 features with defaults and rationale

2. **Daily Validation Checklist**
   - File: `docs/02-operations/daily-validation-checklist.md`
   - Add: Feature quality check section

3. **Model Training Runbook**
   - File: `docs/MODEL-TRAINING-RUNBOOK.md`
   - Add: Data quality verification steps

4. **Data Quality Report**
   - File: `ml/reports/COMPREHENSIVE_DATA_QUALITY_REPORT.md`
   - Update: With findings and fixes from this work

---

## Appendix: Full Feature List

| Index | Feature Name | Current Default | Source | Priority |
|-------|--------------|-----------------|--------|----------|
| 0 | points_avg_last_5 | 10.0 | Phase4→Phase3 | P2 |
| 1 | points_avg_last_10 | 10.0 | Phase4→Phase3 | P2 |
| 2 | points_avg_season | 10.0 | Phase4→Phase3 | P2 |
| 3 | points_std_last_10 | 5.0 | Phase4→Phase3 | OK |
| 4 | games_in_last_7_days | 3.0 | Phase4→Phase3 | OK |
| 5 | fatigue_score | 50.0 | Phase4 only | OK |
| 6 | shot_zone_mismatch_score | 0.0 | Phase4 only | P1 |
| 7 | pace_score | 0.0 | Phase4 only | OK |
| 8 | usage_spike_score | 0.0 | Phase4 only | OK |
| 9 | rest_advantage | 0.0 | Calculated | OK |
| 10 | injury_risk | 0.0 | Calculated | OK |
| 11 | recent_trend | 0.0 | Calculated | OK |
| 12 | minutes_change | 0.0 | Calculated | OK |
| 13 | opponent_def_rating | 112.0 | Phase4→Phase3 | OK |
| 14 | opponent_pace | 100.0 | Phase4→Phase3 | OK |
| 15 | home_away | 0.0 | Phase3 only | P1 |
| 16 | back_to_back | 0.0 | Phase3 only | OK |
| 17 | playoff_game | 0.0 | Phase3 only | OK |
| 18 | pct_paint | 30.0 | Phase4→Phase3 | P1 |
| 19 | pct_mid_range | 20.0 | Phase4→Phase3 | P2 |
| 20 | pct_three | 35.0 | Phase4→Phase3 | P1 |
| 21 | pct_free_throw | 0.15 | Calculated | OK |
| 22 | team_pace | 100.0 | Phase4→Phase3 | OK |
| 23 | team_off_rating | 112.0 | Phase4→Phase3 | OK |
| 24 | team_win_pct | 0.500 | Calculated | OK |
| 25 | vegas_points_line | season_avg | Vegas→fallback | **P1** |
| 26 | vegas_opening_line | season_avg | Vegas→fallback | **P1** |
| 27 | vegas_line_move | 0.0 | Vegas | OK |
| 28 | has_vegas_line | 0.0 | Vegas | OK |
| 29 | avg_points_vs_opponent | season_avg | Opponent→fallback | **P1** |
| 30 | games_vs_opponent | 0.0 | Opponent | OK |
| 31 | minutes_avg_last_10 | 28.0 | Minutes | **P0** |
| 32 | ppm_avg_last_10 | 0.4 | Minutes | OK |

---

## Related Documents

- `docs/09-handoff/IMPROVE-SHOT-ZONE-HANDLING.md` - Shot zone specific improvements
- `ml/reports/COMPREHENSIVE_DATA_QUALITY_REPORT.md` - Full data quality analysis
- `ml/reports/EXECUTIVE_SUMMARY.md` - Executive summary of ML issues
- `docs/MODEL-TRAINING-RUNBOOK.md` - Model training guide
