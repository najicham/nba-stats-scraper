# Model Attribution Tracking System

**Created**: February 2, 2026 (Session 84)
**Status**: In Development
**Priority**: P0 - Critical for ML Operations

---

## Problem Statement

### Current State (Broken)

We cannot determine which exact model file generated which predictions:

1. **prediction_execution_log is empty** (0 records) - logging isn't working
2. **No model file tracking** - `model_version` field exists but contains generic values like "v9_current_season", not actual file names
3. **No training metadata** - We don't know what date range each model was trained on
4. **No performance tracking** - Expected MAE/hit rate not stored with predictions
5. **Historical analysis impossible** - Cannot distinguish OLD vs NEW model performance

### Real Impact (Session 83-84)

**Problem**: Session 83 reported 75.9% historical hit rate for v9_top5 subset, but we **don't know which model version** produced those results.

**Options**:
- Was it the OLD model (catboost_v9_2026_02.cbm, MAE 5.08, HR 50.84%)?
- Was it the NEW model (catboost_v9_feb_02_retrain.cbm, MAE 4.12, HR 74.6%)?

**We literally cannot tell** because there's no model provenance tracking.

### Why This Matters

1. **Model debugging** - When hit rates change, we need to know if it's due to model changes or data changes
2. **A/B testing** - Can't compare model versions without attribution
3. **Rollback decisions** - Can't identify which model to rollback to
4. **Compliance** - No audit trail for which model made which bet recommendations
5. **Reproducibility** - Cannot reproduce predictions without knowing exact model file used

---

## Solution Design

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ Prediction Worker (prediction_systems/catboost_v9.py)      │
│                                                             │
│ 1. Load model from GCS                                     │
│    - catboost_v9_feb_02_retrain.cbm                       │
│                                                             │
│ 2. Extract model metadata:                                 │
│    ├── model_file_name: "catboost_v9_feb_02_retrain.cbm" │
│    ├── training_start: "2025-11-02"                       │
│    ├── training_end: "2026-01-31"                         │
│    ├── expected_mae: 4.12                                 │
│    └── trained_at: Timestamp                              │
│                                                             │
│ 3. Include in prediction result                            │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Batch Writer (predictions/shared/batch_staging_writer.py)  │
│                                                             │
│ Write to player_prop_predictions with model metadata:      │
│   - model_file_name                                        │
│   - model_training_start_date                              │
│   - model_training_end_date                                │
│   - model_expected_mae                                     │
│   - model_trained_at                                       │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ BigQuery: nba_predictions.player_prop_predictions           │
│                                                             │
│ Each prediction now includes full model provenance         │
└─────────────────────────────────────────────────────────────┘
```

### Schema Changes

#### 1. player_prop_predictions Table

Add new columns to track model file and training metadata:

```sql
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`

-- Exact model file that generated this prediction
ADD COLUMN IF NOT EXISTS model_file_name STRING
  OPTIONS (description='Exact model file name (e.g., catboost_v9_feb_02_retrain.cbm)'),

-- Model training period
ADD COLUMN IF NOT EXISTS model_training_start_date DATE
  OPTIONS (description='Start date of training data window'),

ADD COLUMN IF NOT EXISTS model_training_end_date DATE
  OPTIONS (description='End date of training data window'),

-- Expected performance metrics
ADD COLUMN IF NOT EXISTS model_expected_mae FLOAT64
  OPTIONS (description='Expected MAE from model training'),

ADD COLUMN IF NOT EXISTS model_expected_hit_rate FLOAT64
  OPTIONS (description='Expected hit rate for high-edge picks (5+ edge)'),

-- Model training timestamp
ADD COLUMN IF NOT EXISTS model_trained_at TIMESTAMP
  OPTIONS (description='When this model was trained');
```

**Note**: We already have `model_version` (added v4.0) but it contains generic identifiers. We'll keep it for backward compatibility and populate both.

#### 2. prediction_execution_log Table

Add model tracking fields (and fix the fact that it's not being written to):

```sql
ALTER TABLE `nba-props-platform.nba_predictions.prediction_execution_log`

-- Model identification
ADD COLUMN IF NOT EXISTS model_file_name STRING
  OPTIONS (description='Exact model file name used for this execution'),

ADD COLUMN IF NOT EXISTS model_path STRING
  OPTIONS (description='Full GCS path to model file'),

-- Model metadata
ADD COLUMN IF NOT EXISTS model_training_start_date DATE
  OPTIONS (description='Start date of model training window'),

ADD COLUMN IF NOT EXISTS model_training_end_date DATE
  OPTIONS (description='End date of model training window'),

ADD COLUMN IF NOT EXISTS model_expected_mae FLOAT64
  OPTIONS (description='Expected MAE from model training');
```

---

## Implementation Plan

### Phase 1: Schema Updates (30 min)

1. ✅ Create migration SQL file
2. ✅ Run migrations on BigQuery
3. ✅ Update schema documentation
4. ✅ Verify fields created successfully

### Phase 2: Fix prediction_execution_log Population (1 hour)

**Current Issue**: Table has 0 records despite code existing to write to it.

**Investigation needed**:
1. Find where execution log is supposed to be written
2. Identify why writes are failing or not happening
3. Fix the code to actually write records
4. Verify writes work

**Expected files to check**:
- `predictions/coordinator/coordinator.py` - Orchestrates predictions
- `predictions/worker/main.py` - Worker entry point
- `predictions/shared/` - Shared utilities

### Phase 3: Update Prediction Systems (1 hour)

Update `catboost_v9.py` (and optionally other systems) to emit model metadata:

```python
class CatBoostV9(CatBoostV8):
    def predict(self, player_lookup, features, betting_line):
        result = super().predict(player_lookup, features, betting_line)

        # Add model attribution metadata
        result["model_metadata"] = {
            "model_file_name": self.model_file_name,  # e.g., "catboost_v9_feb_02_retrain.cbm"
            "model_training_start_date": self.TRAINING_INFO["training_start"],
            "model_training_end_date": self.TRAINING_INFO["training_end"],
            "model_expected_mae": self.TRAINING_INFO["mae"],
            "model_expected_hit_rate": 74.6,  # From training analysis
            "model_trained_at": self.model_trained_at,  # Parse from file metadata
        }

        return result
```

### Phase 4: Update Batch Writer (30 min)

Update `batch_staging_writer.py` to write model metadata fields to BigQuery.

### Phase 5: Update Notifications (30 min)

Enhance subset pick notifications to show model provenance:

```
🔥 Today's Top Picks - Feb 3, 2026

Model: CatBoost V9 Feb-02 Retrain
  File: catboost_v9_feb_02_retrain.cbm
  Trained: Nov 2, 2025 - Jan 31, 2026 (91 days)
  Expected: MAE 4.12, High-Edge HR 74.6%
  Deployed: Feb 2, 2026 1:31 PM PST (Session 82)

Signal: 🟢 GREEN (35% OVER)

Top 5 Picks (v9_top5):
...
```

### Phase 6: Create Verification Script (30 min)

Create `bin/verify-model-attribution.sh`:
- Check if model metadata fields are populated
- Verify model file names match actual files in GCS
- Confirm training dates are valid
- Check execution log is being written

### Phase 7: Documentation (30 min)

Document in:
- This design doc
- Implementation guide
- Runbook for checking model attribution
- Update CLAUDE.md with new fields

---

## Data Model

### Model Metadata Structure

```python
{
    "model_file_name": "catboost_v9_feb_02_retrain.cbm",
    "model_training_start_date": "2025-11-02",
    "model_training_end_date": "2026-01-31",
    "model_expected_mae": 4.12,
    "model_expected_hit_rate": 74.6,  # High-edge (5+ edge) picks
    "model_trained_at": "2026-02-02T10:15:00Z"
}
```

### Extraction from Model Files

**Option 1: Hardcode in system class** (Recommended for V9)
- Store TRAINING_INFO in `catboost_v9.py`
- Update when deploying new model
- Simple, no file parsing needed

**Option 2: Embed in model file metadata**
- Store as custom metadata in .cbm file during training
- Extract at load time
- More dynamic, but requires training script changes

**Decision**: Use Option 1 for now (already have TRAINING_INFO dict)

---

## Verification Queries

### Check Model Attribution Coverage

```sql
-- What % of recent predictions have model attribution?
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNTIF(model_file_name IS NOT NULL) as with_file_name,
  ROUND(100.0 * COUNTIF(model_file_name IS NOT NULL) / COUNT(*), 1) as pct_coverage
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND system_id = 'catboost_v9'
GROUP BY game_date
ORDER BY game_date DESC;
```

### Check Model Version Distribution

```sql
-- Which model files are being used?
SELECT
  model_file_name,
  model_training_start_date,
  model_training_end_date,
  model_expected_mae,
  COUNT(*) as predictions,
  MIN(game_date) as first_used,
  MAX(game_date) as last_used
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9'
  AND model_file_name IS NOT NULL
GROUP BY 1, 2, 3, 4
ORDER BY last_used DESC;
```

### Verify Performance Matches Expectations

```sql
-- Does actual MAE match expected MAE?
SELECT
  p.model_file_name,
  p.model_expected_mae as expected_mae,
  ROUND(AVG(ABS(pa.predicted_points - pa.actual_points)), 2) as actual_mae,
  COUNT(*) as graded_predictions
FROM nba_predictions.player_prop_predictions p
JOIN nba_predictions.prediction_accuracy pa
  ON p.prediction_id = pa.prediction_id
WHERE p.system_id = 'catboost_v9'
  AND p.model_file_name IS NOT NULL
  AND pa.prediction_correct IS NOT NULL
GROUP BY p.model_file_name, p.model_expected_mae
ORDER BY MAX(pa.game_date) DESC;
```

---

## Success Criteria

### Must Have (Before Deployment)

- ✅ Schema migrations applied
- ✅ prediction_execution_log writing records
- ✅ catboost_v9 emitting model metadata
- ✅ New predictions include model_file_name
- ✅ Verification script passes

### Nice to Have (Phase 2)

- 📋 Other prediction systems emit metadata
- 📋 Notifications show model provenance
- 📋 Dashboard shows model version distribution
- 📋 Alerting on model drift

---

## Rollout Plan

### Step 1: Schema Deployment (Today)

```bash
# Apply migrations
bq query < schemas/bigquery/predictions/migrations/2026-02-02-model-attribution.sql

# Verify
bq show --schema nba_predictions.player_prop_predictions | grep model_
```

### Step 2: Code Deployment (Today)

```bash
# Deploy prediction-worker with model attribution code
./bin/deploy-service.sh prediction-worker

# Verify deployment
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
```

### Step 3: Verification (Tomorrow AM)

After overnight predictions run (7 AM ET), verify:

```bash
# Check if model attribution is working
./bin/verify-model-attribution.sh

# Expected: 100% of catboost_v9 predictions have model_file_name
```

### Step 4: Backfill Historical Data (Optional)

We can backfill model metadata for past predictions by:
1. Checking deployment_revision or build_commit_sha
2. Mapping to known model versions
3. Updating historical records

**Note**: This is optional and can be done later if needed.

---

## Risk Mitigation

### Risk 1: Schema Changes Break Existing Code

**Mitigation**: Use `ADD COLUMN IF NOT EXISTS` - safe for online schema evolution

### Risk 2: Model Metadata Slows Down Predictions

**Mitigation**: Metadata is extracted once at model load time, not per prediction

### Risk 3: Wrong Metadata Written

**Mitigation**:
- Verification script checks metadata validity
- Cross-reference with GCS bucket contents
- Alert if mismatch detected

### Risk 4: prediction_execution_log Still Doesn't Write

**Mitigation**:
- Investigate thoroughly before deploying
- Add explicit logging around writes
- Test locally first

---

## Future Enhancements

### Phase 2 (Future Sessions)

1. **Model Registry Service**
   - Central registry of all models with metadata
   - Automatic versioning and tracking
   - Deployment history

2. **Model Performance Monitoring**
   - Real-time drift detection
   - Automatic alerts when performance deviates
   - A/B test framework

3. **Model Lineage Tracking**
   - Full lineage from training data → model → predictions
   - Feature importance tracking
   - Data quality correlation

4. **Automated Model Attribution Backfill**
   - Script to backfill model metadata for historical predictions
   - Use deployment timestamps and git history

---

## References

### Related Sessions

- **Session 82**: Deployed NEW V9 model (catboost_v9_feb_02_retrain.cbm)
- **Session 83**: Discovered we can't track which model produced 75.9% HR
- **Session 64**: Added build_commit_sha and deployment tracking
- **Session 76**: Trained the Feb-02 retrain model

### Related Files

- `predictions/worker/prediction_systems/catboost_v9.py` - V9 system with TRAINING_INFO
- `predictions/shared/batch_staging_writer.py` - Writes predictions to BigQuery
- `schemas/bigquery/predictions/01_player_prop_predictions.sql` - Schema definition
- `schemas/bigquery/predictions/prediction_execution_log.sql` - Execution log schema

### Documentation

- `/docs/08-projects/current/ml-model-v9-architecture/` - V9 architecture docs
- `/docs/08-projects/current/feature-quality-monitoring/` - Feature tracking
- `/docs/05-development/schema-evolution.md` - Schema change best practices

---

## Questions & Decisions

### Q1: Should we track model metadata in both execution_log AND player_prop_predictions?

**A**: Yes. They serve different purposes:
- `execution_log`: Batch-level tracking (one record per prediction run)
- `player_prop_predictions`: Prediction-level tracking (one record per prediction)

### Q2: Should we backfill historical predictions?

**A**: Optional. We can infer model versions from deployment timestamps if needed, but it's not critical for current operations.

### Q3: What about non-ML systems (moving_average, ensemble)?

**A**: They can emit generic metadata or skip it. Focus on ML systems (CatBoost) first since that's where model tracking matters most.

### Q4: Should model_file_name include the full GCS path?

**A**: No. Store just the filename in `model_file_name` and the full path in `execution_log.model_path` if needed. Filename is more readable and stable.

---

**Last Updated**: February 2, 2026
**Next Review**: After first deployment and verification
