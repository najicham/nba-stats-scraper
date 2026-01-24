# PLACEHOLDER LINE ELIMINATION STRATEGY V2
**Created**: 2026-01-16
**Approach**: Delete Invalid → Fix Code → Regenerate Clean
**Priority**: CRITICAL

---

## STRATEGY OVERVIEW

**Key Insight**: Instead of patching invalid data, we should:
1. **Delete all invalid predictions** (clean slate)
2. **Fix the code** (prevent future issues)
3. **Regenerate predictions properly** (with validation gates)
4. **Validate results** (ensure quality)

This approach is:
- ✅ Cleaner (no patching over bad data)
- ✅ Safer (validates entire pipeline works)
- ✅ More auditable (fresh data with timestamps)
- ✅ Tests the fixes (proves validation gates work)

---

## AFFECTED DATA BREAKDOWN

### Category 1: XGBoost V1 - Complete Regeneration Required
**Volume**: 6,548 predictions
**Date Range**: Nov 19, 2025 - Jan 10, 2026
**Issue**: 100% placeholder lines (line_value = 20.0)
**Action**: DELETE all + REGENERATE

**Why regenerate?**
- Model may have been using mock/placeholder features
- Need to validate real ML model integration works
- Predictions themselves may be invalid, not just lines

### Category 2: System-Wide Blackout - Line Backfill Possible
**Volume**: 15,915 predictions
**Date Range**: Nov 19 - Dec 19, 2025
**Issue**: 100% placeholder lines across ALL systems
**Root Cause**: No DraftKings props available during this period

**Decision Point**: Can we backfill or must regenerate?

**Option A: Backfill Lines Only** (if predictions are valid)
- Query historical props from `odds_api_player_points_props`
- Update `current_points_line` field
- Recalculate `line_margin` and `recommendation`
- ✅ Pros: Faster (no prediction regeneration needed)
- ❌ Cons: Assumes predictions themselves are valid

**Option B: Full Regeneration** (safer)
- Delete all predictions for Nov 19 - Dec 19, 2025
- Re-run coordinator + workers for each date
- Generate fresh predictions with real lines
- ✅ Pros: Clean data, validates pipeline
- ❌ Cons: Slower (~31 dates to regenerate)

**Recommendation**: Start with Option A (backfill), validate results, fall back to Option B if issues found

### Category 3: Jan 9-10, 2026 - Recent Incident
**Volume**: 1,570 predictions
**Date Range**: 2 days
**Issue**: 63-100% placeholder lines
**Action**: DELETE + REGENERATE (dates are recent, easy to regenerate)

**Why regenerate?**
- Recent dates have fresh data
- Quick to regenerate (2 days)
- Tests that fixes work

---

## DECISION MATRIX: BACKFILL vs REGENERATE

| Criteria | Nov 19 - Dec 19, 2025 | Jan 9-10, 2026 | XGBoost V1 All Dates |
|----------|----------------------|----------------|---------------------|
| **Volume** | 15,915 predictions | 1,570 predictions | 6,548 predictions |
| **Prediction Quality** | Likely valid (just missing lines) | Unknown | Invalid (mock model?) |
| **Historical Props Available** | YES (scraped to odds_api) | YES | YES |
| **Regeneration Effort** | HIGH (31 days) | LOW (2 days) | MEDIUM (53 days) |
| **Risk of Regeneration** | Medium (old data) | Low (recent) | Medium (model validation) |
| **RECOMMENDED ACTION** | BACKFILL first, validate | REGENERATE | REGENERATE |

---

## REVISED IMPLEMENTATION PLAN

### PHASE 0: ANALYSIS & VALIDATION (Day 1 - 2 hours)

**Goal**: Understand exactly what data we have and what's salvageable

**Tasks**:

1. **Query Available Historical Props** [30 min]
   ```sql
   -- Check if we have props for blackout period
   SELECT
       game_date,
       COUNT(DISTINCT player_lookup) as players_with_props,
       COUNT(*) as total_props,
       COUNT(DISTINCT bookmaker) as sportsbooks
   FROM nba_raw.odds_api_player_points_props
   WHERE game_date BETWEEN '2025-11-19' AND '2025-12-19'
   GROUP BY game_date
   ORDER BY game_date;
   ```

2. **Analyze Prediction Quality** [30 min]
   ```sql
   -- Check if predictions themselves are reasonable
   SELECT
       system_id,
       DATE_TRUNC(game_date, MONTH) as month,
       COUNT(*) as predictions,
       AVG(predicted_points) as avg_prediction,
       STDDEV(predicted_points) as stddev_prediction,
       AVG(confidence_score) as avg_confidence,
       -- Check for suspicious patterns
       COUNTIF(predicted_points = 20.0) as pred_20_count,
       COUNTIF(predicted_points < 0) as negative_preds,
       COUNTIF(predicted_points > 60) as unrealistic_high
   FROM nba_predictions.player_prop_predictions
   WHERE game_date BETWEEN '2025-11-19' AND '2025-12-19'
   GROUP BY system_id, month
   ORDER BY system_id, month;
   ```

3. **Create Categorization** [1 hour]
   ```sql
   -- Tag predictions by remediation strategy
   CREATE OR REPLACE TABLE nba_predictions.placeholder_remediation_plan AS
   SELECT
       prediction_id,
       system_id,
       player_lookup,
       game_date,
       game_id,
       current_points_line,
       predicted_points,
       line_source,
       CASE
           -- Category 1: XGBoost V1 - Always regenerate
           WHEN system_id = 'xgboost_v1' THEN 'REGENERATE'

           -- Category 2: Jan 9-10 - Always regenerate (recent)
           WHEN game_date IN ('2026-01-09', '2026-01-10') THEN 'REGENERATE'

           -- Category 3: Nov-Dec blackout - Backfill if props available
           WHEN game_date BETWEEN '2025-11-19' AND '2025-12-19'
               AND current_points_line = 20.0
               AND predicted_points > 0 AND predicted_points < 60  -- Reasonable prediction
               THEN 'BACKFILL'

           -- Category 4: Suspicious predictions - Regenerate
           WHEN current_points_line = 20.0
               AND (predicted_points <= 0 OR predicted_points > 60)
               THEN 'REGENERATE'

           -- Category 5: Other placeholders - Backfill
           WHEN current_points_line = 20.0 THEN 'BACKFILL'

           -- Everything else is valid
           ELSE 'VALID'
       END as remediation_strategy,

       CASE
           WHEN system_id = 'xgboost_v1' THEN 'XGBoost V1 - Mock Model'
           WHEN game_date BETWEEN '2025-11-19' AND '2025-12-19' THEN 'Nov-Dec Blackout'
           WHEN game_date IN ('2026-01-09', '2026-01-10') THEN 'Jan 9-10 Incident'
           ELSE 'Other'
       END as incident_category

   FROM nba_predictions.player_prop_predictions
   WHERE current_points_line = 20.0
       OR line_source IS NULL
       OR line_source = 'NEEDS_BOOTSTRAP'
       OR (line_source = 'ESTIMATED_AVG' AND sportsbook IS NULL);

   -- Summary report
   SELECT
       remediation_strategy,
       incident_category,
       COUNT(*) as predictions,
       COUNT(DISTINCT game_date) as dates,
       COUNT(DISTINCT system_id) as systems,
       MIN(game_date) as first_date,
       MAX(game_date) as last_date
   FROM nba_predictions.placeholder_remediation_plan
   GROUP BY remediation_strategy, incident_category
   ORDER BY remediation_strategy, incident_category;
   ```

**Output**: Detailed remediation plan with categorization

---

### PHASE 1: FIX THE CODE (Day 2 - 4 hours)

**Goal**: Prevent placeholders from happening again

**Critical**: DO THIS BEFORE regenerating data!

**Tasks**:

1. **Add Validation Gate to Worker** [1 hour]

   File: `predictions/worker/worker.py` (before line 482)

   ```python
   def validate_line_quality(predictions: List[Dict], player_lookup: str, game_date_str: str) -> Tuple[bool, Optional[str]]:
       """
       CRITICAL VALIDATION: Block placeholder lines before BigQuery write.

       Returns:
           (is_valid, error_message)
       """
       placeholder_count = 0
       issues = []

       for pred in predictions:
           line_value = pred.get('current_points_line')
           line_source = pred.get('line_source')
           system_id = pred.get('system_id')

           # Check 1: Placeholder 20.0
           if line_value == 20.0:
               placeholder_count += 1
               issues.append(f"{system_id}: line_value=20.0")

           # Check 2: Missing line source
           if line_source in [None, 'NEEDS_BOOTSTRAP']:
               issues.append(f"{system_id}: invalid line_source={line_source}")
               placeholder_count += 1

           # Check 3: NULL line with actual prop claim
           if line_value is None and pred.get('has_prop_line') == True:
               issues.append(f"{system_id}: NULL line but has_prop_line=TRUE")
               placeholder_count += 1

       if placeholder_count > 0:
           error_msg = (
               f"❌ LINE QUALITY VALIDATION FAILED\\n"
               f"Player: {player_lookup}\\n"
               f"Date: {game_date_str}\\n"
               f"Issues: {placeholder_count}/{len(predictions)}\\n"
               f"Details: {', '.join(issues[:5])}"  # First 5 issues
           )

           # Send Slack alert
           logger.error(error_msg)
           webhook = os.environ.get('SLACK_WEBHOOK_URL_WARNING')
           if webhook:
               send_to_slack(
                   webhook,
                   f"🚨 PLACEHOLDER LINE BLOCKED\\n\\n{error_msg}\\n\\n"
                   f"Investigation needed - check coordinator line fetching.",
                   icon_emoji=":rotating_light:"
               )

           return False, error_msg

       return True, None

   # INSERT before BigQuery write
   is_valid, error_msg = validate_line_quality(predictions, player_lookup, game_date_str)
   if not is_valid:
       logger.error(f"Validation failed, returning 500 to trigger retry: {error_msg}")
       return (f'Line quality validation failed: {error_msg}', 500)

   # Proceed with write only if valid
   write_success = write_predictions_to_bigquery(predictions, batch_id=batch_id)
   ```

2. **Fix Data Loaders 20.0 Default** [1 hour]

   File: `predictions/worker/data_loaders.py` (lines 317, 613)

   ```python
   # OLD CODE (REMOVE):
   # season_avg = sum(all_points) / len(all_points) if all_points else 20.0

   # NEW CODE:
   if all_points:
       season_avg = sum(all_points) / len(all_points)
   else:
       # Player has no historical games - cannot generate prediction
       logger.warning(
           f"⚠️  Player {player_lookup} has 0 historical games. "
           f"Cannot calculate season average. Skipping prediction."
       )
       return []  # Return empty list to skip this player
   ```

3. **Update Grading Filters** [1 hour]

   File: `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

   ```python
   # Add to prediction query WHERE clause:
   WHERE game_date = '{target_date}'
       AND current_points_line IS NOT NULL
       AND current_points_line != 20.0  -- Exclude placeholders
       AND line_source IN ('ACTUAL_PROP', 'ODDS_API')  -- Only real lines
       AND has_prop_line = TRUE
       AND sportsbook IS NOT NULL  -- Must have sportsbook attribution
   ```

4. **Deploy Code Changes** [1 hour]
   ```bash
   # Deploy worker with validation gate
   gcloud run deploy nba-prediction-worker-prod \
       --region=us-west2 \
       --source=predictions/worker

   # Deploy grading with filters
   gcloud functions deploy prediction-accuracy-grading-prod \
       --region=us-west2 \
       --source=data_processors/grading/prediction_accuracy
   ```

**Validation**:
```bash
# Test validation gate blocks placeholders
# (will need test prediction with line_value=20.0)

# Test grading excludes placeholders
PYTHONPATH=. python -c "
from datetime import date
from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import PredictionAccuracyProcessor
proc = PredictionAccuracyProcessor()
result = proc.process_date(date(2026, 1, 15))
print(f'Graded {result} predictions (should exclude any with line=20.0)')
"
```

---

### PHASE 2: DELETE INVALID DATA (Day 3 - 2 hours)

**Goal**: Remove all placeholder predictions from database

**Critical**: Only do this AFTER Phase 1 is deployed!

**Tasks**:

1. **Backup to Archive Table** [30 min]
   ```sql
   -- Create archive of deleted predictions (for audit trail)
   CREATE OR REPLACE TABLE nba_predictions.deleted_placeholder_predictions_20260116 AS
   SELECT
       *,
       CURRENT_TIMESTAMP() as deleted_at,
       'Session 76 - Placeholder elimination' as deletion_reason
   FROM nba_predictions.player_prop_predictions
   WHERE prediction_id IN (
       SELECT prediction_id
       FROM nba_predictions.placeholder_remediation_plan
       WHERE remediation_strategy IN ('REGENERATE', 'BACKFILL')
   );

   -- Verify backup
   SELECT
       COUNT(*) as backed_up_predictions,
       MIN(game_date) as first_date,
       MAX(game_date) as last_date,
       COUNT(DISTINCT system_id) as systems
   FROM nba_predictions.deleted_placeholder_predictions_20260116;
   ```

2. **Delete XGBoost V1 Predictions** [15 min]
   ```sql
   -- Category 1: XGBoost V1 - Complete deletion
   DELETE FROM nba_predictions.player_prop_predictions
   WHERE system_id = 'xgboost_v1'
       AND game_date BETWEEN '2025-11-19' AND '2026-01-10';

   -- Verify
   SELECT COUNT(*) as remaining_xgboost_v1
   FROM nba_predictions.player_prop_predictions
   WHERE system_id = 'xgboost_v1';
   -- Should return 0
   ```

3. **Delete Jan 9-10 Predictions** [15 min]
   ```sql
   -- Category 2: Jan 9-10 - All systems
   DELETE FROM nba_predictions.player_prop_predictions
   WHERE game_date IN ('2026-01-09', '2026-01-10');

   -- Verify
   SELECT COUNT(*) as remaining_jan_9_10
   FROM nba_predictions.player_prop_predictions
   WHERE game_date IN ('2026-01-09', '2026-01-10');
   -- Should return 0
   ```

4. **Delete or Keep Nov-Dec based on Analysis** [1 hour]

   **IF Analysis Shows Props Available → Keep for Backfill**:
   ```sql
   -- Don't delete Nov-Dec predictions (will backfill in Phase 3)
   SELECT 'Nov-Dec predictions preserved for backfill' as status;
   ```

   **IF Analysis Shows Props Missing OR Predictions Invalid → Delete**:
   ```sql
   -- Delete Nov-Dec predictions (will regenerate in Phase 4)
   DELETE FROM nba_predictions.player_prop_predictions
   WHERE game_date BETWEEN '2025-11-19' AND '2025-12-19'
       AND current_points_line = 20.0;

   -- Verify
   SELECT COUNT(*) as remaining_nov_dec_placeholders
   FROM nba_predictions.player_prop_predictions
   WHERE game_date BETWEEN '2025-11-19' AND '2025-12-19'
       AND current_points_line = 20.0;
   -- Should return 0
   ```

**Summary Report**:
```sql
SELECT
    'BEFORE' as phase,
    COUNT(*) as total_predictions,
    COUNTIF(current_points_line = 20.0) as placeholders
FROM nba_predictions.deleted_placeholder_predictions_20260116

UNION ALL

SELECT
    'AFTER' as phase,
    COUNT(*) as total_predictions,
    COUNTIF(current_points_line = 20.0) as placeholders
FROM nba_predictions.player_prop_predictions;
```

---

### PHASE 3: BACKFILL NOV-DEC (Day 4 - 4 hours)

**Goal**: Update Nov-Dec predictions with real DraftKings lines

**Only if**: Props available AND predictions look valid

**Tasks**:

1. **Create Backfill Script** [2 hours]

   File: `scripts/nba/backfill_nov_dec_lines.py`

   (Use script from previous plan, but only for Nov-Dec dates)

2. **Execute Backfill** [1 hour]
   ```bash
   PYTHONPATH=. python scripts/nba/backfill_nov_dec_lines.py \
       --start-date 2025-11-19 \
       --end-date 2025-12-19 \
       --dry-run

   # Review dry run results, then execute
   PYTHONPATH=. python scripts/nba/backfill_nov_dec_lines.py \
       --start-date 2025-11-19 \
       --end-date 2025-12-19
   ```

3. **Validate Backfill** [1 hour]
   ```sql
   -- Check backfill success
   SELECT
       game_date,
       COUNT(*) as predictions,
       COUNTIF(current_points_line = 20.0) as still_placeholder,
       COUNTIF(line_source = 'ACTUAL_PROP') as backfilled,
       COUNTIF(enriched_at IS NOT NULL) as enriched_count
   FROM nba_predictions.player_prop_predictions
   WHERE game_date BETWEEN '2025-11-19' AND '2025-12-19'
   GROUP BY game_date
   ORDER BY game_date;
   ```

---

### PHASE 4: REGENERATE PREDICTIONS (Days 5-6 - 8 hours)

**Goal**: Generate fresh predictions for deleted dates

**Tasks**:

1. **Regenerate Jan 9-10** [2 hours]
   ```bash
   # Trigger coordinator for each date
   for date in 2026-01-09 2026-01-10; do
       echo "Regenerating $date..."
       gcloud pubsub topics publish nba-prediction-coordinator-trigger \
           --message="{\"target_date\": \"$date\", \"mode\": \"backfill\"}"

       # Wait for completion (check Firestore batch state)
       sleep 300  # 5 min
   done
   ```

2. **Validate Jan 9-10 Regeneration** [30 min]
   ```sql
   SELECT
       game_date,
       system_id,
       COUNT(*) as predictions,
       COUNTIF(current_points_line = 20.0) as placeholders,
       COUNTIF(line_source = 'ACTUAL_PROP') as actual_props,
       ROUND(AVG(confidence_score), 1) as avg_confidence
   FROM nba_predictions.player_prop_predictions
   WHERE game_date IN ('2026-01-09', '2026-01-10')
   GROUP BY game_date, system_id
   ORDER BY game_date, system_id;

   -- Should show:
   -- 0 placeholders
   -- 100% actual_props
   -- Reasonable confidence scores
   ```

3. **Regenerate XGBoost V1** [4 hours]
   ```bash
   # Generate date list
   dates=$(gcloud bigquery query --use_legacy_sql=false --format=csv \
       "SELECT DISTINCT game_date
        FROM nba_predictions.deleted_placeholder_predictions_20260116
        WHERE system_id = 'xgboost_v1'
        ORDER BY game_date")

   # For each date, trigger regeneration
   echo "$dates" | tail -n +2 | while read date; do
       echo "Regenerating XGBoost V1 for $date..."
       gcloud pubsub topics publish nba-prediction-coordinator-trigger \
           --message="{\"target_date\": \"$date\", \"mode\": \"backfill\", \"systems\": [\"xgboost_v1\"]}"
       sleep 180  # 3 min between batches
   done
   ```

4. **Regenerate Nov-Dec (if backfill failed)** [1.5 hours]

   Only if Phase 3 failed or was skipped

   ```bash
   # Similar to above but for Nov 19 - Dec 19
   for i in {19..30}; do
       date="2025-11-$(printf %02d $i)"
       echo "Regenerating $date..."
       gcloud pubsub topics publish nba-prediction-coordinator-trigger \
           --message="{\"target_date\": \"$date\", \"mode\": \"backfill\"}"
       sleep 180
   done

   for i in {1..19}; do
       date="2025-12-$(printf %02d $i)"
       echo "Regenerating $date..."
       gcloud pubsub topics publish nba-prediction-coordinator-trigger \
           --message="{\"target_date\": \"$date\", \"mode\": \"backfill\"}"
       sleep 180
   done
   ```

---

### PHASE 5: MONITORING & PREVENTION (Day 7 - 3 hours)

**Goal**: Ensure this never happens again

**Tasks**:

1. **Deploy Line Quality Monitor** [1.5 hours]

   Create: `orchestration/cloud_functions/line_quality_monitor/main.py`

   (Use code from previous plan)

   Schedule daily at 19:00 UTC

2. **Add R-009 Validation** [1 hour]

   Update: `validation/validators/nba/r009_validation.py`

   Add check for placeholder lines

3. **Create Dashboard** [30 min]
   ```sql
   CREATE OR REPLACE VIEW nba_predictions.line_quality_daily AS
   SELECT
       game_date,
       system_id,
       COUNT(*) as total,
       COUNTIF(line_source = 'ACTUAL_PROP') as actual_prop,
       COUNTIF(current_points_line = 20.0) as placeholders,
       ROUND(100.0 * COUNTIF(line_source = 'ACTUAL_PROP') / COUNT(*), 1) as actual_prop_pct
   FROM nba_predictions.player_prop_predictions
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
   GROUP BY game_date, system_id
   ORDER BY game_date DESC, system_id;
   ```

---

## FINAL VALIDATION

After all phases complete:

```sql
-- Should return 0
SELECT COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE current_points_line = 20.0;

-- Should show 95%+ actual props
SELECT
    COUNT(*) as total,
    COUNTIF(line_source = 'ACTUAL_PROP') as actual,
    ROUND(100.0 * COUNTIF(line_source = 'ACTUAL_PROP') / COUNT(*), 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2025-11-19';

-- Win rates should be 50-65%
SELECT
    system_id,
    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2025-11-19'
    AND line_source = 'ACTUAL_PROP'
GROUP BY system_id;
```

---

## ROLLBACK PLAN

### If Phase 1 (Code Fixes) Breaks Production
- Revert Cloud Run deployment (worker)
- Revert Cloud Function deployment (grading)
- Keep validation as warning-only instead of blocking

### If Phase 2 (Deletion) Has Issues
- Restore from backup table: `deleted_placeholder_predictions_20260116`
- ```sql
  INSERT INTO nba_predictions.player_prop_predictions
  SELECT * EXCEPT(deleted_at, deletion_reason)
  FROM nba_predictions.deleted_placeholder_predictions_20260116;
  ```

### If Phase 3 (Backfill) Fails
- Proceed to Phase 4 (regeneration) instead
- Original deleted data is in backup table

### If Phase 4 (Regeneration) Produces Bad Data
- Delete regenerated predictions
- Investigate validation gate failures
- Fix code and retry regeneration

---

## ESTIMATED EFFORT

| Phase | Duration | Risk | Can Rollback? |
|-------|----------|------|---------------|
| Phase 0: Analysis | 2 hours | LOW | N/A |
| Phase 1: Fix Code | 4 hours | LOW | YES (revert deploy) |
| Phase 2: Delete Invalid | 2 hours | MEDIUM | YES (restore from backup) |
| Phase 3: Backfill Nov-Dec | 4 hours | LOW | YES (delete backfills) |
| Phase 4: Regenerate | 8 hours | MEDIUM | YES (delete regenerated) |
| Phase 5: Monitoring | 3 hours | LOW | N/A |
| **TOTAL** | **23 hours** | **LOW-MEDIUM** | **YES** |

---

## KEY DIFFERENCES FROM V1 PLAN

**V1 Plan**: Patch in place (update line_value directly)
**V2 Plan**: Delete and regenerate (clean slate)

**V2 Advantages**:
- ✅ Validates entire pipeline works correctly
- ✅ Tests that code fixes prevent future issues
- ✅ More auditable (fresh data with timestamps)
- ✅ Confidence in data quality

**V2 Disadvantages**:
- ⚠️  Takes longer (regeneration time)
- ⚠️  Requires coordination across multiple dates
- ⚠️  Depends on historical props availability

**Why V2 is Better**:
For XGBoost V1 and Jan 9-10, we MUST regenerate anyway. For Nov-Dec, we can try backfill first, but have regeneration as fallback. This hybrid approach gives us the best of both worlds.

---

## NEXT STEPS

1. Review this strategy
2. Run Phase 0 analysis queries
3. Decide: Backfill or Regenerate Nov-Dec based on analysis
4. Create detailed TODO list
5. Begin implementation

---

**END OF STRATEGY V2**
