# V8 Investigation Learnings - Prevention & Monitoring Improvements

**Created:** 2026-02-01 (Session 64)
**Status:** Action Required
**Priority:** HIGH

---

## Executive Summary

Session 64 investigation took ~2 hours to identify the root cause of the V8 hit rate collapse. The investigation was difficult because we lacked proper tracking of:

1. **Code version** that generated each prediction
2. **Features actually used** at prediction time
3. **Deployment timing** relative to prediction generation
4. **Automated alerting** for hit rate degradation

This document outlines specific improvements to make future investigations faster and prevent similar issues.

---

## Part 1: What Made This Investigation Difficult

### 1.1 No Code Version Tracking

**Problem:** We couldn't tell what code version generated each prediction.

**Investigation Pain:**
- Had to manually query Cloud Run revision history
- Cross-referenced git commits with deployment timestamps
- No way to filter "predictions made with broken code" vs "predictions made with fixed code"

**Impact:** 30+ minutes spent tracing deployment timelines

### 1.2 Feature Store Overwritten

**Problem:** The feature store was re-run on Jan 31, overwriting features from Jan 30.

**Investigation Pain:**
- Current feature store doesn't reflect what features existed when predictions were made
- Can't verify if Vegas line was 0.0 or correct value at prediction time
- Lost the "ground truth" needed to diagnose feature extraction bugs

**Impact:** Couldn't definitively prove feature values were wrong

### 1.3 No Deployment-Prediction Correlation

**Problem:** No automated tracking of which deployment was active when predictions ran.

**Investigation Pain:**
```
Had to manually trace:
- Jan 30 03:17 UTC - Fix committed
- Jan 30 07:41 UTC - Backfill ran (which deployment?)
- Jan 30 19:10 UTC - Fix deployed

Required: gcloud run revisions describe ... for 5+ revisions
```

**Impact:** 20+ minutes querying Cloud Run

### 1.4 No Feature Snapshot in Predictions

**Problem:** Predictions table has `feature_version` but not actual feature values.

**Investigation Pain:**
- Couldn't verify if `has_vegas_line` was 1.0 or 0.0 at prediction time
- Couldn't check if `ppm_avg_last_10` was correct or defaulted to 0.4
- Critical for debugging feature enrichment bugs

**Impact:** Had to infer issues from hit rate patterns, not direct evidence

### 1.5 No Automated Hit Rate Alerting

**Problem:** Hit rate dropped from 66% to 50% over 3 weeks without detection.

**Why It Wasn't Detected:**
- No automated daily hit rate monitoring
- No alerting on degradation thresholds
- Manual `/validate-daily` doesn't check hit rate trends

**Impact:** Issue persisted for 3 weeks before investigation

### 1.6 No Pre-Backfill Deployment Check

**Problem:** Jan 30 backfill ran with old code (fix deployed 12 hours later).

**Why It Happened:**
- No automation to verify latest code is deployed before backfill
- Manual backfill script doesn't check deployment status
- No integration between deployment and orchestration

**Impact:** Entire Jan 9-28 period has broken predictions

---

## Part 2: Schema Improvements

### 2.1 `player_prop_predictions` Table Additions

```sql
ALTER TABLE nba_predictions.player_prop_predictions
ADD COLUMN IF NOT EXISTS build_commit_sha STRING,           -- Git commit that built the service
ADD COLUMN IF NOT EXISTS deployment_revision STRING,        -- Cloud Run revision ID
ADD COLUMN IF NOT EXISTS predicted_at TIMESTAMP,            -- When model.predict() was called
ADD COLUMN IF NOT EXISTS feature_store_read_at TIMESTAMP,   -- When features were read
ADD COLUMN IF NOT EXISTS feature_source_mode STRING,        -- 'daily' or 'backfill'
ADD COLUMN IF NOT EXISTS orchestration_run_id STRING,       -- Links to orchestration run

-- CRITICAL: Store actual feature values used for prediction
ADD COLUMN IF NOT EXISTS features_snapshot JSON,            -- All features as JSON
ADD COLUMN IF NOT EXISTS critical_features JSON;            -- Key features: vegas_line, has_vegas_line, ppm, etc.
```

**Why Each Field Matters:**

| Field | Purpose | Investigation Use |
|-------|---------|-------------------|
| `build_commit_sha` | Track which code version | Filter predictions by code version |
| `deployment_revision` | Cloud Run revision | Verify fix was deployed |
| `predicted_at` | When prediction made | Distinguish fresh vs backfilled |
| `feature_store_read_at` | Feature timestamp | Verify features weren't stale |
| `feature_source_mode` | Daily vs backfill | Compare performance by mode |
| `features_snapshot` | All 33+ features | Verify feature extraction worked |
| `critical_features` | Key features | Quick debugging of common issues |

### 2.2 `critical_features` JSON Structure

Store the features most likely to cause issues:

```json
{
  "vegas_points_line": 18.5,
  "vegas_opening_line": 18.0,
  "has_vegas_line": 1.0,
  "ppm_avg_last_10": 0.52,
  "avg_points_vs_opponent": 17.2,
  "team_win_pct": 0.65,
  "pace_score": 0.0,
  "usage_spike_score": 0.0,
  "has_shot_zone_data": 1.0
}
```

**Benefits:**
- Instantly see if Vegas line was used vs defaulted
- Check if PPM was 0.4 (default) or real value
- Detect broken features (pace_score = 0)
- No need to join with feature store (which may be overwritten)

### 2.3 `ml_feature_store_v2` Table Additions

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS build_commit_sha STRING,
ADD COLUMN IF NOT EXISTS feature_source_mode STRING,        -- 'daily' or 'backfill'
ADD COLUMN IF NOT EXISTS vegas_line_source STRING,          -- 'phase3' or 'raw_tables'
ADD COLUMN IF NOT EXISTS feature_extraction_method STRING,  -- Version of extraction logic
ADD COLUMN IF NOT EXISTS predictions_made_count INT64,      -- Track if predictions used this
ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP;               -- Prevent overwrites once used
```

### 2.4 `prediction_accuracy` Table Additions

```sql
ALTER TABLE nba_predictions.prediction_accuracy
ADD COLUMN IF NOT EXISTS prediction_generated_at TIMESTAMP, -- From predictions table
ADD COLUMN IF NOT EXISTS build_commit_sha STRING,           -- Code version
ADD COLUMN IF NOT EXISTS critical_features JSON,            -- Snapshot from predictions
ADD COLUMN IF NOT EXISTS feature_source_mode STRING;        -- Daily vs backfill
```

**Why:** The grading table is what we query for hit rate analysis. Having feature context here eliminates joins.

---

## Part 3: Code Changes

### 3.1 Add Build Info to Predictions

**File:** `predictions/worker/prediction_worker.py`

```python
import os

# At startup, load build info
BUILD_COMMIT_SHA = os.environ.get('BUILD_COMMIT', 'unknown')
DEPLOYMENT_REVISION = os.environ.get('K_REVISION', 'unknown')

# When generating prediction
prediction = {
    ...
    'build_commit_sha': BUILD_COMMIT_SHA,
    'deployment_revision': DEPLOYMENT_REVISION,
    'predicted_at': datetime.utcnow().isoformat(),
    ...
}
```

**File:** `bin/deploy-service.sh` (already sets BUILD_COMMIT, verify it's passed)

### 3.2 Add Feature Snapshot to Predictions

**File:** `predictions/worker/prediction_systems/catboost_v8.py`

```python
def predict(self, player_lookup: str, features: Dict, betting_line: Optional[float], ...) -> Dict:
    ...
    # Store critical features for debugging
    critical_features = {
        'vegas_points_line': features.get('vegas_points_line'),
        'has_vegas_line': 1.0 if features.get('vegas_points_line') else 0.0,
        'ppm_avg_last_10': features.get('ppm_avg_last_10'),
        'avg_points_vs_opponent': features.get('avg_points_vs_opponent'),
        'team_win_pct': features.get('team_win_pct'),
        'pace_score': features.get('pace_score'),
        'usage_spike_score': features.get('usage_spike_score'),
    }

    return {
        ...
        'critical_features': json.dumps(critical_features),
        'features_snapshot': json.dumps(features) if STORE_FULL_FEATURES else None,
    }
```

### 3.3 Add Feature Source Mode Tracking

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

```python
def _build_record(self, player_lookup: str, features: Dict) -> Dict:
    return {
        ...
        'feature_source_mode': 'backfill' if self.is_backfill_mode else 'daily',
        'vegas_line_source': 'raw_tables' if self.is_backfill_mode else 'phase3',
        'build_commit_sha': os.environ.get('BUILD_COMMIT', 'unknown'),
    }
```

---

## Part 4: Automated Monitoring

### 4.1 Daily Hit Rate Monitoring

Add to `/validate-daily` skill or create new `hit-rate-monitor` function:

```sql
-- Daily hit rate with 7-day rolling comparison
WITH daily_rates AS (
  SELECT
    game_date,
    COUNT(*) as predictions,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
  FROM nba_predictions.prediction_accuracy
  WHERE system_id = 'catboost_v8'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
    AND prediction_correct IS NOT NULL
  GROUP BY 1
),
rolling AS (
  SELECT
    game_date,
    predictions,
    hit_rate,
    AVG(hit_rate) OVER (ORDER BY game_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) as rolling_7d_avg,
    LAG(hit_rate, 7) OVER (ORDER BY game_date) as hit_rate_7d_ago
  FROM daily_rates
)
SELECT *,
  CASE
    WHEN hit_rate < 50 THEN '🔴 CRITICAL: Hit rate below 50%'
    WHEN hit_rate < rolling_7d_avg - 10 THEN '🟠 WARNING: 10+ pt drop from rolling avg'
    WHEN hit_rate < hit_rate_7d_ago - 5 THEN '🟡 NOTICE: 5+ pt drop from last week'
    ELSE '✅ Normal'
  END as alert_status
FROM rolling
ORDER BY game_date DESC
LIMIT 7
```

### 4.2 Alert Thresholds

| Condition | Severity | Action |
|-----------|----------|--------|
| Hit rate < 50% | 🔴 CRITICAL | Immediate investigation |
| Drop > 10 pts from 7d avg | 🟠 WARNING | Check within 24 hours |
| Drop > 5 pts from last week | 🟡 NOTICE | Monitor closely |
| Any 3 consecutive days below 55% | 🔴 CRITICAL | Stop predictions, investigate |

### 4.3 Pre-Backfill Deployment Check

Create `bin/verify-deployment-before-backfill.sh`:

```bash
#!/bin/bash
# Run before any backfill to ensure latest code is deployed

SERVICE=$1
REQUIRED_COMMIT=$(git rev-parse HEAD)

echo "Verifying $SERVICE is deployed with commit $REQUIRED_COMMIT..."

# Get deployed commit
DEPLOYED_COMMIT=$(gcloud run services describe $SERVICE --region=us-west2 \
  --format="value(metadata.labels.commit-sha)" 2>/dev/null)

if [[ "$DEPLOYED_COMMIT" != "$REQUIRED_COMMIT" ]]; then
  echo "❌ DEPLOYMENT MISMATCH!"
  echo "   Required: $REQUIRED_COMMIT"
  echo "   Deployed: $DEPLOYED_COMMIT"
  echo ""
  echo "Run: ./bin/deploy-service.sh $SERVICE"
  exit 1
fi

echo "✅ Deployment verified. Safe to run backfill."
```

### 4.4 Feature Quality Monitoring

Add to `/validate-daily`:

```sql
-- Check for suspicious feature patterns
SELECT
  'Vegas Line' as feature,
  ROUND(100.0 * COUNTIF(features[OFFSET(28)] = 1.0) / COUNT(*), 1) as pct_available,
  CASE WHEN COUNTIF(features[OFFSET(28)] = 1.0) * 100.0 / COUNT(*) < 30
       THEN '🔴 LOW COVERAGE' ELSE '✅ OK' END as status
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE() - 1
UNION ALL
SELECT
  'PPM (non-default)' as feature,
  ROUND(100.0 * COUNTIF(features[OFFSET(32)] != 0.4) / COUNT(*), 1) as pct_available,
  CASE WHEN COUNTIF(features[OFFSET(32)] != 0.4) * 100.0 / COUNT(*) < 80
       THEN '🔴 TOO MANY DEFAULTS' ELSE '✅ OK' END as status
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE() - 1
UNION ALL
SELECT
  'Pace Score (non-zero)' as feature,
  ROUND(100.0 * COUNTIF(features[OFFSET(7)] != 0) / COUNT(*), 1) as pct_available,
  CASE WHEN COUNTIF(features[OFFSET(7)] != 0) * 100.0 / COUNT(*) < 10
       THEN '🟡 MOSTLY ZEROS (known issue)' ELSE '✅ HAS VALUES' END as status
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE() - 1
```

---

## Part 5: Process Improvements

### 5.1 Deployment-First Policy

**Rule:** Always deploy fixes BEFORE running backfills.

**Enforcement:**
1. Backfill scripts call `verify-deployment-before-backfill.sh`
2. CI/CD auto-deploys on merge to main
3. Document in CLAUDE.md

### 5.2 Feature Store Immutability

**Rule:** Once predictions are made against a feature store record, it should not be overwritten.

**Implementation Options:**
1. **Soft lock:** Add `locked_at` timestamp, warn if overwriting
2. **Hard lock:** Create new version instead of overwriting
3. **Snapshot:** Store feature snapshot in predictions table (recommended)

### 5.3 Code Version in All Outputs

**Rule:** Every table that stores generated data must include `build_commit_sha`.

**Tables to Update:**
- `player_prop_predictions` ✅ (proposed above)
- `ml_feature_store_v2` ✅ (proposed above)
- `prediction_accuracy` ✅ (proposed above)
- `player_game_summary`
- `player_daily_cache`
- All Phase 3/4 precompute tables

---

## Part 6: Updated Execution Plan

### Immediate Actions (This Session)

| # | Action | Priority |
|---|--------|----------|
| 1 | Add `build_commit_sha` to predictions table schema | HIGH |
| 2 | Add `critical_features` JSON to predictions | HIGH |
| 3 | Update prediction worker to populate new fields | HIGH |
| 4 | Create pre-backfill deployment check script | HIGH |

### Short-Term (Next Session)

| # | Action | Priority |
|---|--------|----------|
| 5 | Add hit rate monitoring to /validate-daily | HIGH |
| 6 | Add feature quality checks to /validate-daily | MEDIUM |
| 7 | Regenerate Jan 9-28 predictions with fixed code | HIGH |

### Medium-Term (This Week)

| # | Action | Priority |
|---|--------|----------|
| 8 | Add schema fields to prediction_accuracy | MEDIUM |
| 9 | Add schema fields to ml_feature_store_v2 | MEDIUM |
| 10 | Create automated hit rate alerting function | MEDIUM |

---

## Part 7: Queries for Future Investigations

### Find Predictions by Code Version

```sql
-- After implementing build_commit_sha
SELECT
  build_commit_sha,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-01-01'
  AND build_commit_sha IS NOT NULL
GROUP BY 1
ORDER BY predictions DESC
```

### Check Feature Values at Prediction Time

```sql
-- After implementing critical_features JSON
SELECT
  player_lookup,
  JSON_VALUE(critical_features, '$.has_vegas_line') as has_vegas,
  JSON_VALUE(critical_features, '$.ppm_avg_last_10') as ppm,
  predicted_points,
  actual_points,
  prediction_correct
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-01-12'
  AND JSON_VALUE(critical_features, '$.has_vegas_line') = '0.0'
```

### Compare Daily vs Backfill Performance

```sql
-- After implementing feature_source_mode
SELECT
  feature_source_mode,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-01-01'
GROUP BY 1
```

---

## Summary

**Key Insight:** The V8 hit rate collapse was caused by a deployment timing issue that would have been caught immediately with:

1. **Code version tracking** - Would see predictions made with old commit
2. **Feature snapshots** - Would see has_vegas_line=0 in predictions
3. **Pre-backfill checks** - Would block backfill until fix deployed
4. **Automated alerting** - Would detect 16% hit rate drop on day 1

**Estimated Prevention Value:**
- 3 weeks of bad predictions avoided
- 2+ hours of investigation time saved
- Higher confidence in prediction quality

---

*Created: 2026-02-01 Session 64*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
