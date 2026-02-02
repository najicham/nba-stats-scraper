# Critical Prediction Issues - February 1, 2026

**Date**: February 1, 2026 (Afternoon/Evening)
**Severity**: 🔴 P1 CRITICAL
**Status**: BLOCKING - Predictions not actionable
**Games Today**: 4 games scheduled (CHA-NOP, IND-HOU, MEM-MIN, LAC-PHI)

---

## Executive Summary

Daily validation revealed **critical issues** that make today's predictions unusable:

1. **🔴 CRITICAL**: All 59 predictions have **ZERO Vegas lines** (cannot calculate edge)
2. **🔴 CRITICAL**: Grading coverage <50% for multiple models (affects performance analysis)
3. **⚠️ HIGH**: Pre-game signal not calculated (no warning system active)
4. **ℹ️ NEW**: Model changed from `catboost_v9` → `catboost_v9_2026_02` (monthly retrain?)

**Time Sensitive**: Games start in ~3-5 hours (typical 7-10 PM ET). Issues need resolution before game time.

---

## Issue 1: Missing Vegas Lines (P1 CRITICAL)

### Problem

```
Model: catboost_v9_2026_02
Predictions: 59
Lines available: 0 ❌
High-edge picks: 0 ❌
```

**Impact**:
- Cannot calculate prediction edge (no comparison to Vegas line)
- Cannot identify high-edge picks (≥5 points edge)
- Predictions are not actionable for betting
- Signal system cannot calculate pct_over (needs lines)

### Root Cause Investigation

**Hypothesis 1: Betting data not scraped**

Check if odds data exists for today:

```sql
-- Check if betting data exists
SELECT COUNT(*) as props_count
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date = DATE('2026-02-01');
```

**Expected**: 150-200 player props for 4 games

**If 0 props**: Betting data scraper didn't run
- Check scheduler: `gcloud scheduler jobs list | grep odds`
- Check logs: `gcloud logging read 'resource.labels.service_name="nba-scrapers" AND jsonPayload.scraper_name="odds_api_player_points_props"' --limit=10`
- Manual trigger: See scraper trigger commands below

**Hypothesis 2: Feature enrichment failed to join betting data**

Check if feature store has Vegas line feature:

```sql
-- Check Vegas line coverage in feature store
SELECT
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = DATE('2026-02-01');
```

**Expected**: ≥80% coverage

**If low coverage**: Phase 4 didn't join betting data
- Check Phase 4 logs: `gcloud run services logs read nba-phase4-precompute-processors --limit=50`
- Look for: "upcoming_player_game_context" errors
- Check if betting data available when Phase 4 ran

**Hypothesis 3: Prediction worker didn't enrich with lines**

Check prediction worker logs:

```bash
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND timestamp>="2026-02-01T00:00:00Z"
  AND severity>=WARNING' \
  --limit=50 --format=json
```

**Look for**:
- Errors about missing line data
- "current_points_line" field errors
- JOIN failures with betting tables

### Recommended Fix

**If betting data missing** (Hypothesis 1):
1. Manually trigger odds scraper
2. Wait for scraper completion (~5-10 min)
3. Re-run Phase 4 (feature enrichment)
4. Re-run Phase 5 (predictions)

**If betting data exists but not joined** (Hypothesis 2/3):
1. Check Phase 4 completion status in Firestore
2. Re-run Phase 4 with correct date
3. Re-run Phase 5 to regenerate predictions with lines

**Commands**:

```bash
# Manually trigger odds scraper (if needed)
gcloud scheduler jobs run odds-api-player-props --location=us-west2

# Re-run Phase 4
gcloud scheduler jobs run same-day-phase4 --location=us-west2

# Re-run Phase 5
gcloud scheduler jobs run same-day-phase5 --location=us-west2
```

---

## Issue 2: Grading Coverage <50% (P1 CRITICAL)

### Problem

Multiple models have critically low grading coverage in last 7 days:

| Model | Predictions | Graded | Coverage | Status |
|-------|-------------|--------|----------|--------|
| ensemble_v1 | 1,238 | 35 | **2.8%** | 🔴 CRITICAL |
| ensemble_v1_1 | 1,238 | 237 | **19.1%** | 🔴 CRITICAL |
| catboost_v8 | 1,691 | 362 | **21.4%** | 🔴 CRITICAL |
| catboost_v9 | 902 | 687 | **76.2%** | 🟡 WARNING |
| similarity_balanced_v1 | 1,043 | 0 | **0%** | 🔴 CRITICAL |
| moving_average | 1,238 | 0 | **0%** | 🔴 CRITICAL |
| zone_matchup_v1 | 1,238 | 0 | **0%** | 🔴 CRITICAL |

### Impact

**Why this matters** (Session 68 lesson):
- Session 68 analyzed catboost_v9 with 94 graded records instead of 6,665 total
- Wrong conclusion: "42% hit rate"
- Actual (after joining player_game_summary): **79.4% hit rate**
- 37-point error due to incomplete grading!

**Current impact**:
- Cannot accurately assess model performance
- Hit rate analysis will be wrong
- Model drift monitoring unreliable
- Performance tracking broken for 7/7 models

### Root Cause

**Likely causes**:
1. Grading processor not running daily
2. Scheduler job for grading missing or failing
3. Backfilled predictions not graded (only production graded)

### Recommended Fix

**Immediate**: Run grading backfill for last 7 days

```bash
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-26 \
  --end-date 2026-02-01
```

**Expected runtime**: 10-20 minutes depending on volume

**Verification after backfill**:

```sql
-- Re-check coverage after backfill
WITH prediction_counts AS (
  SELECT 'player_prop_predictions' as source, system_id, COUNT(*) as record_count
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND current_points_line IS NOT NULL
  GROUP BY system_id
  UNION ALL
  SELECT 'prediction_accuracy' as source, system_id, COUNT(*) as record_count
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY system_id
)
SELECT
  system_id,
  MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END) as predictions,
  MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) as graded,
  ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
        NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) as coverage_pct
FROM prediction_counts
GROUP BY system_id
ORDER BY coverage_pct DESC;
```

**Expected**: All models ≥80% coverage

**Long-term fix**:
1. Verify grading scheduler job exists and runs daily
2. Add grading completeness check to morning validation
3. Alert if coverage drops below 80%

---

## Issue 3: Signal Not Calculated (P2 HIGH)

### Problem

Pre-game signal table has no entry for today (Feb 1, 2026):

```sql
-- Returns 0 rows
SELECT * FROM `nba-props-platform.nba_predictions.daily_prediction_signals`
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9';
```

### Impact

- No pre-game warning for users
- Cannot use `/subset-picks` skill effectively
- Signal-based subsets (v9_high_edge_balanced) won't filter correctly
- Validation dashboard missing signal status

### Root Cause

**Signal calculation not automated** (known limitation from Session 71):
- Phase 1 implemented signal infrastructure
- Phase 4 (automated calculation) not yet implemented
- Signals must be calculated manually after predictions generated

### Recommended Fix

**Immediate**: Run manual signal calculation

**IMPORTANT**: Update model ID to `catboost_v9_2026_02` (if that's the active model)

```sql
INSERT INTO `nba-props-platform.nba_predictions.daily_prediction_signals`
SELECT
  CURRENT_DATE() as game_date,
  system_id,
  COUNT(*) as total_picks,
  COUNTIF(ABS(predicted_points - current_points_line) >= 5) as high_edge_picks,
  COUNTIF(confidence_score >= 0.92 AND ABS(predicted_points - current_points_line) >= 3) as premium_picks,
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
  ROUND(100.0 * COUNTIF(recommendation = 'UNDER') / COUNT(*), 1) as pct_under,
  ROUND(AVG(confidence_score), 2) as avg_confidence,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_edge,
  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25 THEN 'UNDER_HEAVY'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 40 THEN 'OVER_HEAVY'
    ELSE 'BALANCED'
  END as skew_category,
  CASE
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3 THEN 'LOW'
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) > 8 THEN 'HIGH'
    ELSE 'NORMAL'
  END as volume_category,
  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25 THEN 'RED'
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3 THEN 'YELLOW'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 45 THEN 'YELLOW'
    ELSE 'GREEN'
  END as daily_signal,
  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25
      THEN 'Heavy UNDER skew - historically 54% hit rate vs 82% on balanced days'
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3
      THEN 'Low pick volume - high variance expected'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 45
      THEN 'Heavy OVER skew - monitor for potential underperformance'
    ELSE 'Balanced signals - historical 82% hit rate on high-edge picks'
  END as signal_explanation,
  CURRENT_TIMESTAMP() as calculated_at
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND current_points_line IS NOT NULL
GROUP BY system_id;
```

**NOTE**: This will only work AFTER Issue 1 is fixed (need Vegas lines for calculation)

**Verification**:

```sql
-- Check signal was calculated
SELECT game_date, system_id, pct_over, daily_signal, signal_explanation
FROM `nba-props-platform.nba_predictions.daily_prediction_signals`
WHERE game_date = CURRENT_DATE()
ORDER BY system_id;
```

---

## Issue 4: Model ID Changed (ℹ️ INFO)

### Problem

Model ID changed from `catboost_v9` → `catboost_v9_2026_02`

**Yesterday's model**: `catboost_v9` (used in Session 71 analysis)
**Today's model**: `catboost_v9_2026_02`

### Impact

**Positive (if expected)**:
- Monthly model retrain is good practice (adapts to current season)
- Session 70 recommended monthly retraining

**Negative (if unexpected)**:
- Signal tracking expects `catboost_v9`
- Historical validation data uses `catboost_v9`
- Subset definitions reference `catboost_v9`
- Documentation references `catboost_v9`

### Investigation Needed

**Questions to answer**:

1. **Is this intentional monthly retrain?**
   - Check: `docs/08-projects/current/ml-monthly-retraining/` for retraining schedule
   - Check: Deployment logs for prediction-worker
   - Check: ML experiment tracking

2. **What training data was used?**
   - Current season only (Nov 2025 - Jan 2026)?
   - Same as V9 or expanded window?
   - Feature set identical to V9?

3. **Was model validated before deployment?**
   - Hit rate on validation set?
   - MAE compared to V9?
   - Edge over Vegas maintained?

**Verification queries**:

```sql
-- Check if V9 still exists for comparison
SELECT system_id, COUNT(*) as prediction_count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
GROUP BY system_id;

-- Check when v9_2026_02 first appeared
SELECT MIN(game_date) as first_date, MAX(game_date) as last_date, COUNT(DISTINCT game_date) as days
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'catboost_v9_2026_02';
```

### Recommended Actions

1. **Update signal tracking** to use `catboost_v9_2026_02`
   - Modify signal calculation query
   - Update `/validate-daily` skill expectations
   - Update subset definitions if needed

2. **Validate model performance**
   - Wait for tonight's games to complete
   - Grade Feb 1 predictions
   - Compare v9_2026_02 vs v9 performance

3. **Update documentation**
   - Note model rotation in CLAUDE.md
   - Update handoff docs with new model ID
   - Add to validation tracker

4. **Verify intentional deployment**
   - Check deployment logs for prediction-worker
   - Confirm with team that monthly retrain occurred
   - Document training parameters

---

## Recommended Workflow

### Step 1: Investigate Vegas Lines (URGENT)

**Time estimate**: 5-10 minutes

```bash
# Check if betting data exists
bq query --use_legacy_sql=false "
SELECT COUNT(*) as props_count
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE game_date = DATE('2026-02-01')"

# If 0, trigger odds scraper
gcloud scheduler jobs run odds-api-player-props --location=us-west2

# Wait 5-10 min, then verify
bq query --use_legacy_sql=false "
SELECT COUNT(*) as props_count
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE game_date = DATE('2026-02-01')"
```

**Expected result**: 150-200 props

### Step 2: Re-run Pipeline if Needed

**Time estimate**: 30-45 minutes

```bash
# If betting data was missing, re-run phases 4 & 5
gcloud scheduler jobs run same-day-phase4 --location=us-west2
# Wait for completion (~10-15 min)

gcloud scheduler jobs run same-day-phase5 --location=us-west2
# Wait for completion (~15-20 min)

# Verify predictions now have lines
bq query --use_legacy_sql=false "
SELECT COUNT(*) as with_lines
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = CURRENT_DATE()
  AND current_points_line IS NOT NULL"
```

### Step 3: Calculate Signal

**Time estimate**: 2 minutes

Run the INSERT query from Issue 3 section above.

### Step 4: Run Grading Backfill (Parallel)

**Time estimate**: 15-20 minutes (can run while waiting for Step 2)

```bash
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-26 --end-date 2026-02-01
```

### Step 5: Verify Everything Works

**Time estimate**: 5 minutes

```bash
# Check predictions have lines
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as predictions,
  COUNTIF(current_points_line IS NOT NULL) as has_lines,
  COUNTIF(ABS(predicted_points - current_points_line) >= 5) as high_edge
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
GROUP BY system_id"

# Check signal exists
bq query --use_legacy_sql=false "
SELECT * FROM \`nba-props-platform.nba_predictions.daily_prediction_signals\`
WHERE game_date = CURRENT_DATE()"

# Check grading coverage improved
bq query --use_legacy_sql=false "
SELECT system_id,
  ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE system_id = pa.system_id AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)), 1) as coverage_pct
FROM nba_predictions.prediction_accuracy pa
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY system_id"
```

**Success criteria**:
- ✅ Predictions have lines (100% coverage)
- ✅ High-edge picks > 0
- ✅ Signal calculated
- ✅ Grading coverage ≥80% for all models

---

## Context for Next Session

### What Happened

- **Session 71** (yesterday): Implemented dynamic subset system (Phases 1-3)
  - Created `daily_prediction_signals` table
  - Backfilled signals for Jan 9 - Feb 1
  - Yesterday's signal: RED (10.6% pct_over, 4 high-edge picks)
  - Created 9 subset definitions
  - Built `/subset-picks` skill

- **Today's validation**: Found critical issues preventing system use
  - No Vegas lines in predictions
  - Grading coverage critically low
  - Signal not calculated
  - Model ID changed

### Why This Matters

**Yesterday (Feb 1) was supposed to be a natural experiment**:
- RED signal predicted 54% hit rate vs 82% on GREEN days
- 4 high-edge picks to validate signal
- After games complete, we should grade and validate signal

**But**: Without lines, cannot calculate signal. Without grading, cannot validate performance.

### Expected Next Steps

1. Fix issues (this document)
2. Wait for games to complete (tonight)
3. Grade Feb 1 predictions (tomorrow morning)
4. Validate if RED signal correctly predicted poor performance
5. Update validation tracker with results

---

## Files to Reference

- **Signal design**: `docs/08-projects/current/pre-game-signals-strategy/DYNAMIC-SUBSET-DESIGN.md`
- **Session 71 handoff**: `docs/09-handoff/2026-02-01-SESSION-71-DYNAMIC-SUBSET-IMPLEMENTATION.md`
- **Implementation docs**: `docs/08-projects/current/pre-game-signals-strategy/IMPLEMENTATION-COMPLETE-PHASE1-3.md`
- **Grading backfill script**: `backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py`

---

## Related Issues

- **Session 68**: Grading coverage < 80% caused 37-point hit rate error
- **Session 62**: Feature store Vegas line coverage directly affects hit rate
- **Session 64**: Backfill with stale code produced bad predictions

---

**Status**: Document complete. Next session should prioritize fixing Vegas lines issue, then grading backfill, then signal calculation.

---

*Created by: Claude Sonnet 4.5*
*Date: February 1, 2026*
*Session: 71 (validation phase)*
