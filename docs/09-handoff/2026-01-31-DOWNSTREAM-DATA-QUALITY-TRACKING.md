# Downstream Data Quality Tracking - Analysis & Recommendations

**Date**: 2026-01-31
**Context**: Session 53 - BDB retry system implementation
**Focus**: How downstream systems handle BDB data source and missing data

## Executive Summary

The system has **excellent source tracking and NULL handling** but lacks **prediction quality analysis by data source**. We track whether predictions used BDB or NBAC fallback, but don't analyze if this impacts accuracy.

---

## Current State: Data Lineage

### Complete Tracking Through Pipeline

```
┌─────────────────────────────────────────────────────┐
│ Phase 2: Raw Data Sources                          │
│ ─────────────────────────────────────────────────── │
│ • BigDataBall PBP (preferred - shot coordinates)   │
│ • NBAC PBP (fallback - basic zones)                │
└──────────────┬──────────────────────────────────────┘
               │ shot_zones_source: 'bigdataball_pbp' | 'nbac_play_by_play' | null
               ▼
┌─────────────────────────────────────────────────────┐
│ Phase 3: player_game_summary                        │
│ ─────────────────────────────────────────────────── │
│ Fields: paint_attempts, paint_makes,                │
│         mid_range_attempts, mid_range_makes,        │
│         three_attempts_pbp, three_makes_pbp         │
│ Metadata: shot_zones_source, has_complete_zones    │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│ Phase 4: player_shot_zone_analysis                  │
│ ─────────────────────────────────────────────────── │
│ Features: paint_rate_last_10,                       │
│           mid_range_rate_last_10,                   │
│           three_pt_rate_last_10                     │
│ Metadata: source_shot_zones_hash,                  │
│           source_completeness_pct                   │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│ Phase 5: ml_feature_store_v2                        │
│ ─────────────────────────────────────────────────── │
│ Features[18]: pct_paint                             │
│ Features[19]: pct_mid_range                         │
│ Features[20]: pct_three                             │
│ Features[33]: has_shot_zone_data (1.0 | 0.0)       │
│ Metadata: feature_quality_score (0-100),           │
│           data_quality_tier (gold/silver/bronze)    │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│ CatBoost V8 Model                                   │
│ ─────────────────────────────────────────────────── │
│ NULL Handling: np.nan for features 18-20           │
│ Indicator Flag: Feature 33 signals completeness    │
│ Quality Tracking: shot_zones_source in metadata    │
└─────────────────────────────────────────────────────┘
```

---

## Missing Data Handling: EXCELLENT ✅

### 1. NULL → np.nan Conversion

**Location**: `predictions/worker/prediction_systems/catboost_v8.py:750-754`

```python
# Shot zone features (18-20) - NULLABLE since 2026-01-25
features.get('pct_paint') if features.get('pct_paint') is not None else np.nan,
features.get('pct_mid_range') if features.get('pct_mid_range') is not None else np.nan,
features.get('pct_three') if features.get('pct_three') is not None else np.nan,
```

CatBoost natively handles NaN values using decision tree splits.

### 2. Data Availability Indicator

**Feature 33**: `has_shot_zone_data`
- `1.0` = All three zones have data (complete)
- `0.0` = Any zone is missing (incomplete/fallback)

This tells the model to trust (or not trust) the shot zone features.

### 3. Quality Tier System

| Tier | Condition | Quality Score | Confidence Impact |
|------|-----------|---------------|-------------------|
| **GOLD** | BDB available, all zones | 95-100 | +10 confidence |
| **SILVER** | NBAC fallback OR 1-2 features missing | 70-94 | +5-7 confidence |
| **BRONZE** | Shot zones unavailable | <70 | +2 confidence |

### 4. Validation Safeguards

**Catches Data Corruption**:
- All zones = 0.0 → CRITICAL validation failure
- Partial zones NULL → WARNING (may corrupt rate calculations)
- All zones NULL → ALLOWED (model handles via NaN)

**Distribution Monitoring**:
- Expected ranges: paint 15-65%, mid-range 3-40%, three 10-60%
- Alerts if >5 days show drift from expected distribution

---

## Critical Gap: Prediction Quality by Data Source ❌

### What's Tracked

✅ **shot_zones_source** is captured in:
- `quality_tracker.py` → tracks 'bigdataball', 'nbac_fallback', 'unavailable'
- `prediction_audit_log` schema → has shot_zones_source column
- `ml_feature_store_v2` → source metadata propagates

### What's NOT Analyzed

❌ **No grading by source**:
- `prediction_accuracy` table doesn't include shot_zones_source
- Can't query: "Accuracy for BDB predictions vs NBAC predictions"
- Can't answer: "Should we reduce confidence for NBAC fallback?"

❌ **No A/B comparison**:
- No side-by-side analysis of same game with different sources
- When BDB re-run happens, old NBAC prediction not compared to new BDB prediction

❌ **No automatic confidence adjustment**:
- NBAC fallback predictions have same confidence as BDB predictions
- Quality tier impacts confidence, but not strongly differentiated

---

## Recommendations

### Priority 1: Add Source Columns to Grading Table (HIGH)

**Schema Enhancement**:
```sql
ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN shot_zones_source STRING,
ADD COLUMN data_quality_tier STRING,
ADD COLUMN feature_completeness_pct FLOAT64,
ADD COLUMN bdb_available_at_prediction BOOL;
```

**Update Grading Logic** (`predictions/worker/grade_predictions.py`):
```python
# Join with prediction metadata to get quality info
quality_metadata = load_prediction_quality_metadata(game_date)

for prediction in predictions:
    grade_record = {
        # Existing grading fields...
        'shot_zones_source': prediction.metadata.get('shot_zones_source'),
        'data_quality_tier': prediction.metadata.get('data_quality_tier'),
        'feature_completeness_pct': prediction.metadata.get('feature_completeness_pct'),
        'bdb_available_at_prediction': prediction.metadata.get('bdb_available')
    }
```

**Analysis Query**:
```sql
-- Compare accuracy by data source
SELECT
    shot_zones_source,
    data_quality_tier,
    COUNT(*) as predictions,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 2) as accuracy_pct,
    ROUND(AVG(absolute_error), 2) as avg_error,
    ROUND(AVG(confidence_score), 3) as avg_confidence,
    ROUND(STDDEV(absolute_error), 2) as error_stddev
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-01-01'
GROUP BY shot_zones_source, data_quality_tier
ORDER BY accuracy_pct DESC;
```

### Priority 2: Trigger Re-Prediction When BDB Arrives (MEDIUM)

**Current State**:
- BDB retry processor triggers Phase 3 re-run (player_game_summary)
- But does NOT trigger Phase 4 (precompute) or Phase 5 (predictions)
- Old NBAC predictions remain in production

**Enhancement Needed** (`bin/monitoring/bdb_retry_processor.py`):
```python
def trigger_full_reprocessing_pipeline(self, game: Dict) -> bool:
    """
    Trigger complete re-processing when BDB data arrives:
    1. Phase 3: player_game_summary (already implemented)
    2. Phase 4: precompute processors (NEW)
    3. Phase 5: re-generate predictions (NEW)
    """
    # Phase 3
    self.trigger_phase3_rerun(game)

    # Phase 4: Trigger precompute re-run
    self.publisher.publish('nba-phase4-trigger', {
        'game_date': game['game_date'],
        'reason': 'bdb_data_available',
        'processors': ['player_shot_zone_analysis', 'ml_feature_store']
    })

    # Phase 5: Trigger prediction re-generation
    self.publisher.publish('nba-prediction-trigger', {
        'game_date': game['game_date'],
        'reason': 'bdb_upgrade',
        'replace_existing': True,
        'mark_superseded': True  # Mark old NBAC predictions as superseded
    })
```

### Priority 3: Confidence Penalty for Fallback Data (LOW)

**Current Behavior**:
- Quality tier impacts confidence (+2 to +10)
- But difference is small

**Proposed Enhancement**:
```python
# In catboost_v8.py _calculate_confidence()
if features.get('shot_zones_source') == 'nbac_fallback':
    confidence -= 5  # Reduce confidence for fallback data
    logger.info(f"Reduced confidence by 5 points (NBAC fallback used)")
elif features.get('shot_zones_source') == 'unavailable':
    confidence -= 10  # Larger penalty for missing shot zones
```

**Validation**: After implementing, analyze if confidence better matches actual accuracy.

### Priority 4: BDB Availability Trend Dashboard (LOW)

**Create Monitoring Query**:
```sql
-- BDB coverage trend (last 30 days)
WITH daily_coverage AS (
    SELECT
        game_date,
        COUNT(DISTINCT game_id) as total_games,
        COUNTIF(shot_zones_source = 'bigdataball_pbp') as bdb_games,
        COUNTIF(shot_zones_source = 'nbac_play_by_play') as nbac_games,
        COUNTIF(shot_zones_source IS NULL) as missing_games
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= CURRENT_DATE() - 30
    GROUP BY game_date
)
SELECT
    game_date,
    total_games,
    bdb_games,
    nbac_games,
    missing_games,
    ROUND(100.0 * bdb_games / total_games, 1) as bdb_coverage_pct,
    ROUND(100.0 * nbac_games / total_games, 1) as nbac_coverage_pct
FROM daily_coverage
ORDER BY game_date DESC;
```

**Alert Threshold**: If BDB coverage < 80% for 3+ consecutive days, investigate.

---

## Implementation Checklist

### Phase 1: Enhanced Grading (Immediate)
- [ ] Add columns to `prediction_accuracy` table
- [ ] Update grading logic to capture source metadata
- [ ] Create analysis query for accuracy by source
- [ ] Run backfill for last 30 days of predictions

### Phase 2: Full Re-processing Pipeline (Next Sprint)
- [ ] Extend `bdb_retry_processor.py` to trigger Phase 4 & 5
- [ ] Add "superseded" flag to old predictions when re-run
- [ ] Test end-to-end: BDB arrives → full pipeline re-runs
- [ ] Validate that new predictions replace old ones

### Phase 3: Confidence Calibration (Future)
- [ ] Analyze accuracy by shot_zones_source
- [ ] Determine if confidence penalty needed
- [ ] Implement and test penalty logic
- [ ] Re-calibrate confidence using historical data

### Phase 4: Monitoring Dashboard (Future)
- [ ] Create BDB coverage trend dashboard
- [ ] Set up automated alerts for low coverage
- [ ] Add to daily validation reports

---

## Testing Scenarios

### Scenario 1: BDB Data Arrives After NBAC Fallback

**Initial State**:
- Game processed with NBAC fallback on Jan 29
- Prediction generated: shot_zones_source='nbac_play_by_play', confidence=0.72
- Accuracy (graded later): 68% (below expected)

**BDB Arrives (Jan 31)**:
1. Retry processor detects BDB now available
2. Triggers Phase 3 → player_game_summary re-run with BDB
3. Triggers Phase 4 → ml_feature_store_v2 updated
4. Triggers Phase 5 → New prediction generated
   - shot_zones_source='bigdataball_pbp', confidence=0.78
5. Old prediction marked: superseded=True, superseded_at=TIMESTAMP
6. New prediction becomes active

**Analysis**:
```sql
-- Compare old NBAC vs new BDB predictions for same game
SELECT
    game_date,
    player_name,
    prediction_value as old_nbac_prediction,
    actual_value,
    ABS(prediction_value - actual_value) as old_error,
    superseded_by_prediction_id
FROM prediction_accuracy
WHERE game_date = '2026-01-29'
  AND superseded = TRUE
  AND shot_zones_source = 'nbac_play_by_play'
```

### Scenario 2: Complete BDB Outage (Jan 17-19)

**State**:
- 0% BDB coverage for 3 days
- All predictions use NBAC fallback
- Quality tier: SILVER for all predictions

**Expected Behavior**:
1. Daily validation detects 0% BDB coverage → CRITICAL alert
2. BDB retry processor adds all 24 games to pending_bdb_games
3. Predictions generated with confidence penalty (-5 points)
4. When BDB arrives, full re-processing triggered
5. Analyze: Did accuracy improve after BDB re-run?

---

## Key Metrics to Monitor

### Daily Metrics
```sql
SELECT
    game_date,
    COUNTIF(shot_zones_source = 'bigdataball_pbp') as bdb_count,
    COUNTIF(shot_zones_source = 'nbac_play_by_play') as nbac_count,
    COUNTIF(shot_zones_source IS NULL) as missing_count,
    ROUND(AVG(CASE WHEN shot_zones_source = 'bigdataball_pbp' THEN accuracy_pct END), 2) as bdb_accuracy,
    ROUND(AVG(CASE WHEN shot_zones_source = 'nbac_play_by_play' THEN accuracy_pct END), 2) as nbac_accuracy
FROM prediction_accuracy_with_metadata  -- View joining prediction + quality metadata
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

### Weekly Analysis
- Accuracy delta: BDB vs NBAC (expect BDB to be 2-5% better if shot zones matter)
- Confidence calibration: Are NBAC predictions overconfident?
- Feature importance: How much does shot zone data impact predictions?

---

## Conclusion

**Current State**:
- ✅ Excellent data lineage tracking
- ✅ Sophisticated NULL handling in ML models
- ✅ Quality tier system exists
- ❌ But no analysis of prediction quality by data source

**Next Steps**:
1. Add source columns to grading table (schema change)
2. Extend retry processor to trigger full re-processing
3. Analyze if BDB vs NBAC impacts prediction accuracy
4. Calibrate confidence based on findings

This will close the loop on data quality tracking and allow us to quantify the value of BigDataBall data vs fallback sources.

---

**Files to Modify**:
- `schemas/bigquery/nba_predictions/prediction_accuracy.sql` - Add source columns
- `predictions/worker/grade_predictions.py` - Capture quality metadata
- `bin/monitoring/bdb_retry_processor.py` - Trigger full pipeline
- `predictions/worker/prediction_systems/catboost_v8.py` - Confidence penalty (optional)

**Created**: 2026-01-31, Session 53
**Status**: Analysis complete, implementation pending
