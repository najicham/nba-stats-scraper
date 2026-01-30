# Safeguards and Error Tracking Plan

**Date:** 2026-01-30
**Purpose:** Prevent recurrence of the January 7-9 model collapse

---

## Part 1: What is Confidence Calibration?

### Current State
Confidence is **NOT** from the model - it's a separate heuristic:

```python
# catboost_v8.py lines 681-715
confidence = 75.0  # Base
confidence += quality_bonus(feature_quality_score)    # +2 to +10
confidence += consistency_bonus(points_std_last_10)   # +2 to +10
# Result: 77-95%
```

### The Problem
| Confidence Level | Expected Hit Rate | Actual Hit Rate (Jan 25) |
|------------------|-------------------|--------------------------|
| 90%+ (Decile 10) | ~90% | **25%** |
| 80-89% (Decile 9) | ~80% | **51%** |

The confidence scores are **miscalibrated** - they don't match actual performance.

### Why No Challenger Needed
1. Confidence is calculated POST-model, independent of predictions
2. Adjusting thresholds or adding calibration layers doesn't change predictions
3. Only changes which predictions we surface to users

### Calibration Options (No Model Change)

| Option | Complexity | Impact |
|--------|------------|--------|
| **Temperature Scaling** | Low | `confidence * 0.85` reduces over-confidence |
| **Threshold Adjustment** | Low | Raise from 0.84 to 0.90 |
| **Isotonic Regression** | Medium | Non-parametric mapping to actual accuracy |
| **Feature Staleness Penalty** | Medium | Reduce confidence if features > 6 hours old |

---

## Part 2: Safeguards to Prevent Future Issues

### Safeguard 1: Feature Version Validation

**Problem:** V8 expected 33 features but got 25 during mismatch window.

**Solution:** Fail-fast validation in prediction worker.

```python
# predictions/worker/prediction_systems/catboost_v8.py

REQUIRED_FEATURE_VERSION = 'v2_33features'
REQUIRED_FEATURE_COUNT = 33

def predict(self, features, prop_line, ...):
    # SAFEGUARD: Validate feature version
    feature_version = features.get('feature_version', 'unknown')
    feature_count = len(features.get('features', []))

    if feature_version != REQUIRED_FEATURE_VERSION:
        logger.error(f"Feature version mismatch: got {feature_version}, expected {REQUIRED_FEATURE_VERSION}")
        return self._fallback_prediction(features, prop_line,
            error_reason=f"feature_version_mismatch:{feature_version}")

    if feature_count < REQUIRED_FEATURE_COUNT:
        logger.error(f"Feature count too low: got {feature_count}, expected {REQUIRED_FEATURE_COUNT}")
        return self._fallback_prediction(features, prop_line,
            error_reason=f"feature_count_low:{feature_count}")

    # Proceed with normal prediction...
```

### Safeguard 2: Data Completeness Gates

**Problem:** Missing betting data (Jan 6, 8) and lineup data (Jan 9) caused silent failures.

**Solution:** Pre-flight data validation before prediction runs.

```python
# predictions/coordinator/coordinator.py

def validate_data_completeness(self, game_date: str) -> Dict:
    """Validate all required data exists before generating predictions."""

    issues = []

    # Check betting data
    betting_count = self._count_betting_lines(game_date)
    if betting_count == 0:
        issues.append({
            'type': 'MISSING_BETTING_DATA',
            'severity': 'CRITICAL',
            'message': f'No betting lines for {game_date}',
            'action': 'BLOCK_PREDICTIONS'
        })

    # Check lineup data
    lineup_count = self._count_lineup_data(game_date)
    if lineup_count == 0:
        issues.append({
            'type': 'MISSING_LINEUP_DATA',
            'severity': 'CRITICAL',
            'message': f'No lineup data for {game_date}',
            'action': 'BLOCK_PREDICTIONS'
        })

    # Check feature store
    feature_count = self._count_feature_store_records(game_date)
    expected_players = self._get_expected_players(game_date)
    if feature_count < expected_players * 0.8:
        issues.append({
            'type': 'INCOMPLETE_FEATURES',
            'severity': 'WARNING',
            'message': f'Only {feature_count}/{expected_players} players have features',
            'action': 'PROCEED_WITH_WARNING'
        })

    return {
        'is_valid': len([i for i in issues if i['action'] == 'BLOCK_PREDICTIONS']) == 0,
        'issues': issues
    }
```

### Safeguard 3: Confidence Distribution Monitoring

**Problem:** Confidence scores changed dramatically (0.95 disappeared) without alerting.

**Solution:** Daily confidence distribution check with alerts.

```sql
-- validation/queries/monitoring/confidence_distribution_alert.sql

WITH today_distribution AS (
    SELECT
        ROUND(confidence_score, 1) as confidence_bucket,
        COUNT(*) as count
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = CURRENT_DATE()
      AND system_id = 'catboost_v8'
    GROUP BY 1
),
baseline_distribution AS (
    -- Use last 7 days as baseline
    SELECT
        ROUND(confidence_score, 1) as confidence_bucket,
        AVG(daily_count) as avg_count
    FROM (
        SELECT
            game_date,
            ROUND(confidence_score, 1) as confidence_bucket,
            COUNT(*) as daily_count
        FROM nba_predictions.player_prop_predictions
        WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
              AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
          AND system_id = 'catboost_v8'
        GROUP BY 1, 2
    )
    GROUP BY confidence_bucket
)
SELECT
    t.confidence_bucket,
    t.count as today_count,
    b.avg_count as baseline_avg,
    ROUND(100.0 * (t.count - b.avg_count) / NULLIF(b.avg_count, 0), 1) as pct_change,
    CASE
        WHEN t.count = 0 AND b.avg_count > 10 THEN 'ALERT: Bucket disappeared'
        WHEN ABS(t.count - b.avg_count) / NULLIF(b.avg_count, 0) > 0.5 THEN 'WARNING: >50% change'
        ELSE 'OK'
    END as status
FROM today_distribution t
FULL OUTER JOIN baseline_distribution b USING (confidence_bucket)
WHERE t.confidence_bucket >= 0.9  -- Focus on high-confidence
ORDER BY t.confidence_bucket DESC
```

### Safeguard 4: Deployment Atomic Validation

**Problem:** Model and feature store were deployed separately, causing mismatch.

**Solution:** Pre-deployment validation script.

```bash
#!/bin/bash
# bin/pre-deploy-validation.sh

echo "=== Pre-Deployment Validation ==="

# 1. Check feature version alignment
MODEL_FEATURE_VERSION=$(grep "REQUIRED_FEATURE_VERSION" predictions/worker/prediction_systems/catboost_v8.py | cut -d"'" -f2)
FEATURE_STORE_VERSION=$(grep "FEATURE_VERSION" data_processors/precompute/ml_feature_store/ml_feature_store_processor.py | cut -d"'" -f2)

if [ "$MODEL_FEATURE_VERSION" != "$FEATURE_STORE_VERSION" ]; then
    echo "❌ FATAL: Feature version mismatch!"
    echo "   Model expects: $MODEL_FEATURE_VERSION"
    echo "   Feature store produces: $FEATURE_STORE_VERSION"
    exit 1
fi

# 2. Check feature count alignment
MODEL_FEATURE_COUNT=$(grep "REQUIRED_FEATURE_COUNT" predictions/worker/prediction_systems/catboost_v8.py | grep -o '[0-9]*')
FEATURE_STORE_COUNT=$(grep "FEATURE_COUNT" data_processors/precompute/ml_feature_store/feature_extractor.py | grep -o '[0-9]*' | head -1)

if [ "$MODEL_FEATURE_COUNT" != "$FEATURE_STORE_COUNT" ]; then
    echo "❌ FATAL: Feature count mismatch!"
    echo "   Model expects: $MODEL_FEATURE_COUNT features"
    echo "   Feature store produces: $FEATURE_STORE_COUNT features"
    exit 1
fi

echo "✅ All pre-deployment checks passed"
```

---

## Part 3: New Database Fields for Error Tracking

### Current Gap
The `ml_feature_store_v2` table has excellent tracking:
- `feature_version`, `feature_count`, `feature_quality_score`, `data_source`

But this metadata **doesn't flow through** to prediction tables!

### New Fields for player_prop_predictions

```sql
ALTER TABLE nba_predictions.player_prop_predictions
ADD COLUMN IF NOT EXISTS feature_version STRING,
ADD COLUMN IF NOT EXISTS feature_count INT64,
ADD COLUMN IF NOT EXISTS feature_quality_score NUMERIC(5,2),
ADD COLUMN IF NOT EXISTS data_source STRING,
ADD COLUMN IF NOT EXISTS early_season_flag BOOLEAN,
ADD COLUMN IF NOT EXISTS prediction_error_code STRING,
ADD COLUMN IF NOT EXISTS prediction_warnings ARRAY<STRING>;
```

### New Fields for prediction_accuracy

```sql
ALTER TABLE nba_predictions.prediction_accuracy
ADD COLUMN IF NOT EXISTS feature_version STRING,
ADD COLUMN IF NOT EXISTS feature_count INT64,
ADD COLUMN IF NOT EXISTS feature_quality_score NUMERIC(5,2),
ADD COLUMN IF NOT EXISTS data_source STRING,
ADD COLUMN IF NOT EXISTS early_season_flag BOOLEAN;
```

### Error Code Taxonomy

| Code | Meaning | Action |
|------|---------|--------|
| `FEATURE_VERSION_MISMATCH` | Got different feature version than expected | Block, alert |
| `FEATURE_COUNT_LOW` | Missing features | Fallback prediction |
| `NO_BETTING_DATA` | No lines available | Skip player |
| `NO_LINEUP_DATA` | Missing from lineup projections | Skip player |
| `STALE_FEATURES` | Features > 6 hours old | Reduce confidence |
| `LOW_QUALITY_SCORE` | feature_quality_score < 70 | Reduce confidence |
| `API_TIMEOUT` | External API failed | Retry or skip |
| `MODEL_LOAD_FAILED` | CatBoost model couldn't load | Use fallback |

### Warning Flag Taxonomy

| Warning | Meaning |
|---------|---------|
| `EARLY_SEASON` | < 10 games of history |
| `RECENT_TRADE` | Player traded in last 7 days |
| `INJURY_QUESTIONABLE` | Listed as questionable |
| `HIGH_VARIANCE` | points_std_last_10 > 8 |
| `LINE_MOVEMENT` | Line moved > 1.5 pts |
| `MISSING_OPPONENT_HISTORY` | No games vs opponent |

---

## Part 4: Implementation Plan

### Phase 1: Immediate (No Code Deploy Needed)

1. **Add DB fields** via ALTER TABLE
   ```bash
   bq query --use_legacy_sql=false < schemas/bigquery/migrations/add_error_tracking_fields.sql
   ```

2. **Create monitoring queries**
   - Confidence distribution alert
   - Feature version mismatch detection
   - Data completeness check

### Phase 2: Code Changes (This Week)

1. **Add feature validation to catboost_v8.py**
   - Validate feature_version matches expected
   - Validate feature_count >= 33
   - Log and track mismatches

2. **Flow metadata through predictions**
   - Pass feature_version, feature_count, feature_quality_score from features to prediction output
   - Store in player_prop_predictions

3. **Add pre-deployment script**
   - Run before any prediction system deploy
   - Validate feature alignment

### Phase 3: Calibration Layer (Next Week)

1. **Build calibration curve**
   ```python
   # Use historical data to map predicted confidence → actual accuracy
   from sklearn.isotonic import IsotonicRegression

   calibrator = IsotonicRegression(out_of_bounds='clip')
   calibrator.fit(predicted_confidences, actual_accuracies)
   ```

2. **Apply as post-processing**
   ```python
   def _apply_calibration(self, raw_confidence: float) -> float:
       return self.calibrator.transform([raw_confidence])[0]
   ```

3. **Monitor calibration drift**
   - Weekly recalibration check
   - Alert if calibration curve shifts > 5%

---

## Part 5: Monitoring Dashboard Additions

### Daily Checks (Add to /validate-daily)

```
1. Feature Version Check
   - All predictions use expected feature_version?
   - Any FEATURE_VERSION_MISMATCH errors?

2. Confidence Distribution Check
   - High-confidence (0.90+) count vs 7-day baseline?
   - Any confidence buckets disappeared?

3. Data Completeness Check
   - Betting data exists for all games?
   - Lineup data exists for all games?
   - Feature store coverage >= 90%?

4. Error Rate Check
   - prediction_error_code distribution
   - Any new error codes appearing?

5. Model Performance Check
   - Yesterday's hit rate by confidence decile
   - Alert if decile 10 < 60%
```

### Weekly Checks

```
1. Calibration Drift Check
   - Compare predicted vs actual accuracy per bucket
   - Alert if gap > 10%

2. Vegas Sharpness Check
   - Vegas MAE trend
   - Model edge trend
   - Alert if model edge negative for 2+ weeks

3. Feature Quality Trend
   - Average feature_quality_score by week
   - Alert if declining
```

---

## Summary

| Area | Current State | After Safeguards |
|------|---------------|------------------|
| Feature validation | None | Fail-fast on mismatch |
| Data completeness | Silent failures | Pre-flight checks + alerts |
| Confidence monitoring | None | Daily distribution check |
| Error tracking | Limited | Rich error codes + warnings |
| Deployment safety | Manual | Automated validation script |
| Calibration | None | Isotonic regression layer |

**No challenger needed** for:
- Threshold changes (0.84 → 0.90)
- Calibration layer (post-processing)
- Error tracking fields
- Monitoring additions

**Challenger required** for:
- Model architecture changes
- Feature engineering changes
- Retraining on different data

---

*This plan prevents the January 7-9 failure mode by making issues visible immediately rather than discovering them weeks later through degraded performance.*
