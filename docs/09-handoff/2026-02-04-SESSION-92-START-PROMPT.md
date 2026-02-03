# Session 92 Start Prompt - Phase 6 Verification & Phase 2 Planning

**Date:** 2026-02-04
**Previous Session:** Session 91 - Phase 6 Deployment Complete
**Status:** ⏳ Awaiting production verification

---

## Quick Start

Run the automated verification script:

```bash
./bin/verify-phase6-deployment.sh
```

This will check:
- ✅ Model attribution is populated (not NULL)
- ✅ Phase 6 export files exist and are valid
- ✅ No security leaks
- ✅ No NULL team/opponent values
- ✅ ROI values are reasonable

---

## What Happened in Session 91

### Deployed Phase 6 Subset Exporters ✅
- **Commit:** 2993e9fd, 7a16dc28
- **Status:** Production deployment complete
- **Files:** 4 new exporters + integration + tests

**Exporters Created:**
1. `AllSubsetsPicksExporter` → `/picks/{date}.json`
2. `DailySignalsExporter` → `/signals/{date}.json`
3. `SubsetPerformanceExporter` → `/subsets/performance.json`
4. `SubsetDefinitionsExporter` → `/systems/subsets.json`

**Critical Fixes Applied (Opus Review):**
- ROI calculation corrected (was inflated by 30-50 points)
- Security fallback no longer leaks internal IDs
- NULL team/opponent filtering added
- N+1 query pattern optimized (9 queries → 1)
- Public IDs reordered for logical sorting

**Testing:**
- All 4 unit tests passing
- ROI values verified accurate
- Security audit clean
- Integration test successful

### Discovered Model Attribution Issue 🔍
- **Problem:** Today's predictions (2026-02-03) show `model_file_name = NULL`
- **Root Cause:** Session 88 fix was incomplete - required 2 commits, predictions ran between them
- **Status:** Fix is now deployed (rev 00087-8nb, commit 4ada201f)
- **Expected:** Tomorrow's predictions should have correct attribution

**Affected Predictions:**
- Feb 2: 224 predictions
- Feb 3: 136 predictions
- Total: 360 predictions with NULL model_file_name

---

## Your Tasks for This Session

### Task 1: Run Verification Script ✅/❌

```bash
./bin/verify-phase6-deployment.sh
```

**If all checks pass:**
- ✅ Phase 6 is working correctly
- ✅ Model attribution is fixed
- ✅ Ready for Phase 2

**If any checks fail:**
- 🔍 Investigate failures
- 🛠️ Fix issues before Phase 2
- 📝 Document findings

---

### Task 2: Decide on Next Steps

Based on verification results:

#### Option A: Phase 2 - Model Attribution Exporters
**If verification passes, proceed with:**

1. Create `ModelRegistryExporter`
   - Output: `/models/registry.json`
   - Content: List of active models with training metadata
   - Update frequency: Daily

2. Enhance existing exporters with model attribution:
   - `PredictionsExporter` → Add `model_version` field
   - `BestBetsExporter` → Add model attribution
   - `SystemPerformanceExporter` → Add model metadata

**Estimated effort:** 2-3 hours

**Why this matters:** Enables tracking which model version generated predictions, critical for A/B testing and debugging.

---

#### Option B: Backfill Missing Attribution (Optional)
**If you want complete historical data:**

```sql
-- Backfill Feb 2-3 predictions with correct model name
UPDATE nba_predictions.player_prop_predictions
SET
  model_file_name = 'catboost_v9_feb_02_retrain.cbm',
  model_training_start_date = '2025-11-02',
  model_training_end_date = '2026-01-31',
  model_expected_mae = 6.8,
  model_expected_hit_rate = 65.0,
  model_trained_at = TIMESTAMP('2026-02-02 12:00:00 UTC')
WHERE game_date IN ('2026-02-02', '2026-02-03')
  AND system_id = 'catboost_v9'
  AND model_file_name IS NULL
```

**Verify before running:**
```bash
# Check what model was actually used
gsutil cat gs://nba-props-platform-models/catboost_v9/active_model.txt
```

---

#### Option C: Add Deployment Verification (Prevention)
**If you want to prevent future issues:**

Create post-deployment verification that automatically checks critical fields after each prediction run:

```python
# predictions/worker/validation/post_deployment_check.py
def verify_prediction_quality():
    """Run after predictions complete to verify data quality."""
    checks = [
        verify_model_attribution(),
        verify_no_null_lines(),
        verify_recommendations_valid(),
        verify_bigquery_write_succeeded()
    ]
    # Alert if any fail
```

Similar to P0-1 BigQuery write verification added in Session 88.

---

## Manual Verification (If Script Fails)

### Check Model Attribution
```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total,
  COUNT(model_file_name) as with_attribution,
  MAX(model_file_name) as example_model
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-04'
  AND system_id = 'catboost_v9'
GROUP BY 1
ORDER BY 1 DESC"
```

**Expected:**
```
+------------+-------+------------------+-------------------------------+
| game_date  | total | with_attribution | example_model                 |
+------------+-------+------------------+-------------------------------+
| 2026-02-04 |  ~140 |             ~140 | catboost_v9_feb_02_retrain.cbm|
+------------+-------+------------------+-------------------------------+
```

---

### Check Phase 6 Exports
```bash
# Check today's files exist
gsutil ls gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json
gsutil ls gs://nba-props-platform-api/v1/signals/$(date +%Y-%m-%d).json

# Verify structure
gsutil cat gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json | \
  jq '{date, model, groups: (.groups | length), total_picks: [.groups[].picks | length] | add}'

# Security audit
gsutil cat gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json | \
  grep -iE "(system_id|subset_id|catboost|v9_)" && echo "LEAK!" || echo "Clean"
```

---

### Check Orchestrator Logs
```bash
gcloud logging read 'resource.labels.function_name="phase5-to-phase6"
  AND timestamp>="'$(date -u -d '2 hours ago' +%Y-%m-%dT%H:%M:%SZ)'"' \
  --limit=20 --format="table(timestamp, severity, textPayload)"
```

Look for:
- "Orchestrating tonight exports"
- "subset-picks" export success
- "daily-signals" export success

---

## Known Issues

### 1. Model Attribution NULL (360 predictions)
- **Affected:** Feb 2-3 predictions only
- **Status:** Fix deployed, waiting for verification
- **Action:** Check if Feb 4+ predictions have attribution

### 2. Empty Picks on Some Days
- **Not a Bug:** Some days may have 0 picks if market conditions are unfavorable
- **Expected Behavior:** Challenging signal filtering is working correctly

---

## Success Criteria for Phase 2

Before starting Phase 2 work:
- [ ] Model attribution verified working (not NULL)
- [ ] All Phase 6 export files exist and valid
- [ ] No security leaks detected
- [ ] ROI values are reasonable
- [ ] No NULL team/opponent values

---

## Phase 2 Implementation Plan (Preview)

### New Exporter: ModelRegistryExporter

**Output file:** `/models/registry.json`

**Structure:**
```json
{
  "generated_at": "2026-02-04T...",
  "active_models": [
    {
      "model_id": "926A",
      "version": "v9",
      "trained_date": "2026-02-02",
      "training_period": {
        "start": "2025-11-02",
        "end": "2026-01-31"
      },
      "performance": {
        "expected_mae": 6.8,
        "expected_hit_rate": 65.0,
        "edge_3plus_hit_rate": 65.0,
        "edge_5plus_hit_rate": 79.0
      },
      "metadata": {
        "feature_count": 33,
        "training_games": 1234,
        "model_type": "catboost"
      }
    }
  ]
}
```

### Enhanced Exporters

**PredictionsExporter enhancement:**
```json
{
  "predictions": [
    {
      "player": "LeBron James",
      "prediction": 26.1,
      "line": 24.5,
      "model_version": "926A",  // <-- NEW
      "model_trained": "2026-02-02"  // <-- NEW
    }
  ]
}
```

**BestBetsExporter enhancement:**
```json
{
  "best_bets": [
    {
      "player": "LeBron James",
      "model_version": "926A",  // <-- NEW
      "confidence": "high"
    }
  ]
}
```

---

## Quick Reference

### Key Files
- **Verification Script:** `bin/verify-phase6-deployment.sh`
- **Exporters:** `data_processors/publishing/*_exporter.py`
- **Config:** `shared/config/subset_public_names.py`
- **Tests:** `bin/test-phase6-exporters.py`

### Key Commands
```bash
# Run verification
./bin/verify-phase6-deployment.sh

# Check latest predictions
bq query --use_legacy_sql=false "SELECT MAX(game_date), COUNT(*) FROM nba_predictions.player_prop_predictions WHERE system_id='catboost_v9'"

# List exported files
gsutil ls gs://nba-props-platform-api/v1/picks/*.json | tail -5

# View orchestrator logs
gcloud logging read 'resource.labels.function_name="phase5-to-phase6"' --limit=10
```

---

## Documentation References

- **Session 91 Deployment:** `docs/09-handoff/2026-02-03-SESSION-91-DEPLOYMENT-COMPLETE.md`
- **Session 90 Handoff:** `docs/09-handoff/2026-02-03-SESSION-90-FINAL-HANDOFF.md`
- **Model Attribution Investigation:** See Session 91 agent output
- **Opus Review:** `docs/08-projects/current/phase6-subset-model-enhancements/SESSION_90_OPUS_REVIEW_FOR_SONNET.md`

---

## Recommended Session Flow

1. **Start here:** Run `./bin/verify-phase6-deployment.sh`
2. **If PASS:** Proceed to Phase 2 planning and implementation
3. **If FAIL:** Investigate and fix issues first
4. **Optional:** Backfill Feb 2-3 attribution
5. **Optional:** Add deployment verification checks

---

**Session 92 Goal:** Verify Phase 6 works in production, then start Phase 2 (Model Attribution Exporters)
