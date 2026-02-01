# Session 64 Handoff - V8 Hit Rate Root Cause & Prevention

**Date:** 2026-02-01
**Session:** 64
**Focus:** Investigate V8 hit rate collapse, identify root cause, plan prevention
**Status:** Root cause confirmed, schema changes ready to implement

---

## Executive Summary

**Session 63 hypothesis was WRONG.** The V8 hit rate collapse was NOT caused by Vegas line coverage differences between daily and backfill modes.

**Actual Root Cause:** The Jan 30 morning backfill ran with **broken code** because the feature enrichment fix (ea88e526) was committed but not deployed for 12 hours.

---

## Root Cause: Deployment Timing Bug

### The Timeline (UTC)

| Time | Event | Impact |
|------|-------|--------|
| Jan 30 03:17 | Feature enrichment fix committed (ea88e526) | Fix in git |
| **Jan 30 07:41-08:37** | **Jan 9-28 backfill ran** | **Used BROKEN code** |
| Jan 30 19:10 | Fix finally deployed to Cloud Run | Too late |

### The Bug (from commit ea88e526)

```
Worker wasn't populating Vegas/opponent/PPM features (indices 25-32).
has_vegas_line=0.0 and ppm=0.4 defaults caused +29 point prediction errors.
```

### Evidence That Disproves Session 63 Hypothesis

| Period | Vegas Coverage | Hit Rate | Conclusion |
|--------|---------------|----------|------------|
| Jan 1-7 | **37.5%** | **66.1%** | Lower coverage, HIGHER hit rate |
| Jan 9+ | **45.3%** | **50.4%** | Higher coverage, LOWER hit rate |

**Vegas coverage is HIGHER in the broken period!** This proves the issue is NOT about Vegas data source differences.

### Prediction Quality Metrics

| Metric | Jan 1-7 (good) | Jan 9+ (broken) | Impact |
|--------|----------------|-----------------|--------|
| Mean Absolute Error | 4.3 pts | 5.8 pts | **35% worse** |
| Std Dev of Error | 5.6 | 7.4 | **32% worse** |
| Direction Accuracy | 66% | 51% | **-15 pts** |
| High-Edge Hit Rate | 76.6% | 50.9% | **-26 pts** |

### Predictions Made After Fix

| Code Version | Predictions | Graded | Hit Rate |
|--------------|-------------|--------|----------|
| Before fix (broken) | 2,303 | 668 | 50.6% |
| After fix | 559 | 41 | **58.5%** |

The fix shows **+8 percentage point improvement**.

---

## Session 52 Feature Store Backfill - Already Complete

Session 52 (different chat) already backfilled the ML feature store with fixed `usage_spike_score`:

| Phase | Status | Date Range |
|-------|--------|------------|
| Phase 3 (upcoming_player_game_context) | ✅ Complete | Nov 13 - Jan 30 |
| Phase 4 (player_composite_factors) | ✅ Complete | Nov 13 - Jan 30 |
| **ML Feature Store** | ✅ Complete | Nov 13 - Jan 30 |

Verified: `usage_spike_score` now shows 65-75% non-zero values, avg ~0.9 (was 100% zeros before).

**We do NOT need to wait for any feature store backfill.**

---

## Schema Changes to Implement

### 1. Add to `player_prop_predictions` table

```sql
ALTER TABLE nba_predictions.player_prop_predictions
ADD COLUMN IF NOT EXISTS build_commit_sha STRING,
ADD COLUMN IF NOT EXISTS deployment_revision STRING,
ADD COLUMN IF NOT EXISTS predicted_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS critical_features JSON;
```

**Purpose:**
- `build_commit_sha`: Know which code version generated each prediction
- `deployment_revision`: Cloud Run revision ID
- `predicted_at`: When model.predict() was called (not record insertion time)
- `critical_features`: JSON snapshot of Vegas/PPM/key features for debugging

### 2. Add to `ml_feature_store_v2` table

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS build_commit_sha STRING,
ADD COLUMN IF NOT EXISTS feature_source_mode STRING,
ADD COLUMN IF NOT EXISTS vegas_line_source STRING;
```

### 3. Add to `prediction_accuracy` table

```sql
ALTER TABLE nba_predictions.prediction_accuracy
ADD COLUMN IF NOT EXISTS build_commit_sha STRING,
ADD COLUMN IF NOT EXISTS critical_features JSON;
```

### 4. Create `prediction_execution_log` table

```sql
CREATE TABLE IF NOT EXISTS nba_predictions.prediction_execution_log (
  execution_id STRING NOT NULL,
  batch_id STRING,
  build_commit_sha STRING NOT NULL,
  deployment_revision STRING,
  execution_start_timestamp TIMESTAMP NOT NULL,
  execution_end_timestamp TIMESTAMP,
  duration_seconds FLOAT64,
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,
  players_requested INT64,
  players_predicted INT64,
  status STRING NOT NULL,
  error_message STRING,
  error_count INT64,
  avg_feature_quality_score FLOAT64,
  pct_with_vegas_line FLOAT64,
  pct_with_ppm FLOAT64,
  pct_with_shot_zones FLOAT64,
  feature_store_snapshot_time TIMESTAMP,
  feature_source_mode STRING,
  orchestration_run_id STRING
)
PARTITION BY DATE(execution_start_timestamp)
CLUSTER BY system_id, game_date;
```

---

## Code Changes Required

### 1. Prediction Worker (`predictions/worker/worker.py`)

```python
import os

BUILD_COMMIT_SHA = os.environ.get('BUILD_COMMIT', 'unknown')
DEPLOYMENT_REVISION = os.environ.get('K_REVISION', 'unknown')

# When generating prediction record:
prediction = {
    ...
    'build_commit_sha': BUILD_COMMIT_SHA,
    'deployment_revision': DEPLOYMENT_REVISION,
    'predicted_at': datetime.utcnow().isoformat(),
    'critical_features': json.dumps({
        'vegas_points_line': features.get('vegas_points_line'),
        'has_vegas_line': 1.0 if features.get('vegas_points_line') else 0.0,
        'ppm_avg_last_10': features.get('ppm_avg_last_10'),
        'team_win_pct': features.get('team_win_pct'),
    }),
}
```

### 2. Feature Store Processor

```python
record['build_commit_sha'] = os.environ.get('BUILD_COMMIT', 'unknown')
record['feature_source_mode'] = 'backfill' if self.is_backfill_mode else 'daily'
record['vegas_line_source'] = 'raw_tables' if self.is_backfill_mode else 'phase3'
```

---

## Prevention Mechanisms Added

| Mechanism | File | Status |
|-----------|------|--------|
| Pre-backfill deployment check | `bin/verify-deployment-before-backfill.sh` | ✅ Created |
| Investigation learnings doc | `V8-INVESTIGATION-LEARNINGS.md` | ✅ Created |
| Updated execution plan | `V8-FIX-EXECUTION-PLAN.md` | ✅ Updated |
| Regeneration plan | `JAN-9-28-PREDICTION-REGENERATION-PLAN.md` | ✅ Created |

---

## Next Session Checklist

### Immediate (Do First)
- [ ] Run schema ALTER TABLE statements (see above)
- [ ] Deploy prediction worker with new fields populated
- [ ] Test that new fields are being written

### After Schema Changes
- [ ] Mark old Jan 9-28 predictions as superseded
- [ ] Regenerate predictions using fixed code
- [ ] Wait for grading to complete
- [ ] Verify hit rate improvement (expect >58%)

### Monitoring
- [ ] Add hit rate monitoring to /validate-daily skill
- [ ] Create alert for hit rate < 55%

---

## Key Queries for Future Investigation

### Find predictions by code version
```sql
SELECT build_commit_sha, COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-01-01'
  AND build_commit_sha IS NOT NULL
GROUP BY 1;
```

### Check feature values at prediction time
```sql
SELECT player_lookup,
  JSON_VALUE(critical_features, '$.has_vegas_line') as has_vegas,
  JSON_VALUE(critical_features, '$.ppm_avg_last_10') as ppm,
  predicted_points, actual_points, prediction_correct
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-01-12'
  AND JSON_VALUE(critical_features, '$.has_vegas_line') = '0.0';
```

---

## Related Documents

| Document | Purpose |
|----------|---------|
| `docs/09-handoff/2026-02-01-SESSION-64-INVESTIGATION.md` | Detailed investigation notes |
| `docs/08-projects/current/feature-quality-monitoring/V8-INVESTIGATION-LEARNINGS.md` | Prevention mechanisms |
| `docs/08-projects/current/feature-quality-monitoring/V8-FIX-EXECUTION-PLAN.md` | Corrected execution plan |
| `docs/08-projects/current/feature-quality-monitoring/JAN-9-28-PREDICTION-REGENERATION-PLAN.md` | Prediction regeneration steps |
| `docs/09-handoff/2026-01-31-SESSION-52-USAGE-RATE-FIX-HANDOFF.md` | Feature store backfill (already complete) |

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| `da51c332` | docs: Session 64 investigation - DISPROVED Vegas hypothesis |
| `044358af` | feat: Add prevention mechanisms from V8 investigation |
| `cf95a4ff` | docs: Consolidate prevention mechanisms and execution log design |

---

## Key Learnings

1. **Deployment timing matters**: 12-hour gap between commit and deploy caused 3 weeks of bad predictions

2. **Session 63 hypothesis was wrong**: Higher Vegas coverage in broken period proves it's not the issue

3. **Schema fields needed**: `build_commit_sha` would have made this investigation 5 minutes instead of 2 hours

4. **Pre-backfill checks are critical**: Created `verify-deployment-before-backfill.sh` to prevent recurrence

5. **Feature store backfill already done**: Session 52 fixed usage_spike_score, no waiting needed

---

*Session 64 Handoff*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
