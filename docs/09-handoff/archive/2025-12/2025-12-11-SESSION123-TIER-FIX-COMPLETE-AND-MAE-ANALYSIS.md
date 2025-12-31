# Session 123 Handoff - Tier Fix Complete, Streaming Buffer Fix, MAE Analysis

**Date:** 2025-12-11
**Focus:** Completed tier boundary fix, fixed streaming buffer issues, analyzed MAE impact

---

## Executive Summary

This session completed the tier classification fix from Sessions 120-122, fixed a critical BigQuery streaming buffer issue affecting multiple processors, and performed comprehensive MAE analysis revealing that **tier adjustments are currently making predictions worse**.

### Key Accomplishments
1. Verified tier boundary fix is working correctly
2. Fixed streaming buffer issues in 3 files (predictions backfill, grading processor, tier processor)
3. Re-ran predictions backfill for Dec 5 2021 - Jan 7 2022 (33 dates, 5142 predictions)
4. Ran grading backfill (24,931 predictions graded)
5. Discovered tier adjustments are net-negative on MAE (+0.089 worse overall)

### Critical Finding
**Tier adjustments should be disabled or recalibrated** - they currently make predictions 0.089 points worse on average.

---

## Current System State

### Data Coverage
| Table | Date Range | Record Count | Status |
|-------|------------|--------------|--------|
| player_prop_predictions | 2021-12-05 to 2022-01-07 | 25,710 (5 systems) | Updated with correct tiers |
| prediction_accuracy | 2021-12-05 to 2022-01-07 | 24,931 | Freshly graded |
| scoring_tier_adjustments | Multiple as_of_dates | ~20 rows | Needs recalibration |

### Tier Classification (VERIFIED CORRECT)
| Tier | Count | Avg PPG | Min | Max | Status |
|------|-------|---------|-----|-----|--------|
| BENCH_0_9 | 3023 | 5.5 | 0.0 | 10.0 | ✓ Correct |
| ROTATION_10_19 | 1782 | 13.9 | 10.0 | 19.9 | ✓ Correct |
| STARTER_20_29 | 337 | 24.1 | 20.0 | 29.9 | ✓ Correct |
| STAR_30PLUS | 0 | N/A | N/A | N/A | ✓ Expected (early season) |

### Pending Issues
1. **3 dates with streaming buffer errors**: Dec 18, 19, 21 2021 - DELETE failed during backfill
2. **Tier adjustments making MAE worse** - need recalibration or disabling

---

## Streaming Buffer Fix Details

### Problem
BigQuery `insert_rows_json()` creates a 90-minute streaming buffer that blocks DML operations (DELETE, UPDATE, MERGE). This was causing backfill failures when trying to delete existing records.

### Solution Applied
Changed from `insert_rows_json()` to `load_table_from_json()` (batch loading) in 3 files:

#### 1. `backfill_jobs/prediction/player_prop_predictions_backfill.py` (lines 511-535)
```python
# BEFORE (streaming - causes buffer)
errors = self.bq_client.insert_rows_json(table_ref, rows)

# AFTER (batch loading - no buffer)
job_config = bigquery.LoadJobConfig(
    schema=table_ref.schema,
    autodetect=False,
    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    ignore_unknown_values=True
)
load_job = self.bq_client.load_table_from_json(rows, PREDICTIONS_TABLE, job_config=job_config)
load_job.result()
```

#### 2. `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` (lines 314-337)
Same pattern applied. Also added NUMERIC precision rounding to fix batch loading errors.

#### 3. `data_processors/ml_feedback/scoring_tier_processor.py` (lines 104-125)
Same pattern applied.

### Reference Documentation
- `docs/05-development/guides/bigquery-best-practices.md` - Full explanation of streaming vs batch loading

---

## MAE Analysis Results

### By System (Overall)
| System | Predictions | MAE | Bias | Within 3pt | Within 5pt |
|--------|-------------|-----|------|------------|------------|
| xgboost_v1 | 5142 | 4.73 | -1.91 | 42.9% | 63.3% |
| ensemble_v1 | 5142 | 4.73 | -1.54 | 42.5% | 63.3% |
| moving_average_baseline_v1 | 5142 | 4.82 | -1.87 | 41.7% | 62.6% |
| similarity_balanced_v1 | 4363 | 5.01 | -1.27 | 39.3% | 60.0% |
| zone_matchup_v1 | 5142 | 6.03 | -1.42 | 33.1% | 50.7% |

### By Tier (Ensemble Only - Has Adjustments)
| Tier | n | MAE Raw | MAE Adjusted | Bias | Adjustment | MAE Change |
|------|-----|---------|--------------|------|------------|------------|
| BENCH_0_9 | 3025 | 3.99 | 4.15 | -1.59 | -0.78 | **+0.16 worse** |
| ROTATION_10_19 | 1786 | 5.58 | 5.52 | -1.34 | +1.51 | **-0.06 better** |
| STARTER_20_29 | 337 | 6.78 | 7.05 | -2.15 | +5.36 | **+0.27 worse** |
| **Overall** | **5148** | **4.724** | **4.813** | - | - | **+0.089 worse** |

### Root Cause of Poor Adjustments
The adjustments don't match actual bias:
- **BENCH**: Bias is -1.59 (under-predicting), but adjustment is -0.78 (wrong direction!)
- **STARTER**: Bias is -2.15, but adjustment is +5.36 (overcorrecting by 3+ points!)

The adjustment values in `scoring_tier_adjustments` table are computed based on **actual game points** classification, but applied based on **season_avg** classification. This mismatch causes problems.

---

## Important File Locations

### Documentation
| Document | Path | Purpose |
|----------|------|---------|
| BigQuery Best Practices | `docs/05-development/guides/bigquery-best-practices.md` | Streaming vs batch loading |
| Backfill Validation Checklist | `docs/02-operations/backfill/backfill-validation-checklist.md` | Comprehensive validation queries |
| Session 122 Handoff | `docs/09-handoff/2025-12-10-SESSION122-TIER-BOUNDARY-FIX-COMPLETE.md` | Previous session context |
| Phase 5C Design | `docs/08-projects/current/phase-5c-ml-feedback/` | ML feedback loop design |

### Validation Scripts
| Script | Path | Purpose |
|--------|------|---------|
| Backfill Coverage | `scripts/validate_backfill_coverage.py` | Check processor coverage |
| Cascade Contamination | `scripts/validate_cascade_contamination.py` | Detect upstream gaps |
| Validation Directory | `validation/` | Base validator and configs |

### Key Processors
| Processor | Path | Purpose |
|-----------|------|---------|
| Predictions Backfill | `backfill_jobs/prediction/player_prop_predictions_backfill.py` | Phase 5 predictions |
| Grading Backfill | `backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py` | Phase 5B grading |
| Grading Processor | `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` | Grades predictions |
| Tier Processor | `data_processors/ml_feedback/scoring_tier_processor.py` | Computes tier adjustments |
| Tier Adjuster | `data_processors/ml_feedback/scoring_tier_adjuster.py` | Applies tier adjustments |

### BigQuery Tables
| Table | Purpose |
|-------|---------|
| `nba_predictions.player_prop_predictions` | All predictions with tier info |
| `nba_predictions.prediction_accuracy` | Graded predictions |
| `nba_predictions.scoring_tier_adjustments` | Tier-based adjustment values |
| `nba_predictions.ml_feature_store_v2` | ML features (includes season_avg) |

---

## Pending Tasks

### High Priority

#### 1. Re-run 3 Dates with Streaming Buffer Errors
Dec 18, 19, 21 2021 had DELETE failures. Wait 90 mins from last write, then:
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --dates 2021-12-18,2021-12-19,2021-12-21
```

#### 2. Decide on Tier Adjustment Strategy
Options:
- **Option A**: Disable tier adjustments entirely (set to 0)
- **Option B**: Recalibrate adjustments to match actual bias by season_avg tier
- **Option C**: Change adjustment computation to use season_avg classification

### Medium Priority

#### 3. Extend Backfill Date Range
Current: Dec 5 2021 - Jan 7 2022 (33 dates)
Consider extending to full 2021-22 season for better analysis.

#### 4. Validate Streaming Buffer Fix
After running more backfills, verify no streaming buffer errors occur.

---

## Validation Queries

### Check Tier Classification
```sql
-- Verify tier boundaries match names
WITH mlfs AS (
  SELECT player_lookup, game_date, features[OFFSET(2)] as season_avg
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date >= '2021-12-05'
)
SELECT
  p.scoring_tier,
  COUNT(*) as count,
  ROUND(AVG(m.season_avg), 1) as avg_season_ppg,
  ROUND(MIN(m.season_avg), 1) as min_season_ppg,
  ROUND(MAX(m.season_avg), 1) as max_season_ppg
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
JOIN mlfs m ON p.player_lookup = m.player_lookup AND p.game_date = m.game_date
WHERE p.system_id = 'ensemble_v1' AND p.scoring_tier IS NOT NULL
GROUP BY 1 ORDER BY 1;

-- Expected: BENCH 0-10, ROTATION 10-20, STARTER 20-30, STAR 30+
```

### Check MAE by Tier
```sql
-- MAE impact of tier adjustments
WITH predictions_with_tier AS (
  SELECT
    p.scoring_tier,
    p.predicted_points,
    p.adjusted_points,
    p.tier_adjustment,
    pa.actual_points
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
  JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
    ON p.player_lookup = pa.player_lookup
    AND p.game_date = pa.game_date
    AND p.system_id = pa.system_id
  WHERE p.system_id = 'ensemble_v1'
    AND p.scoring_tier IS NOT NULL
    AND p.game_date BETWEEN '2021-12-05' AND '2022-01-07'
)
SELECT
  scoring_tier,
  COUNT(*) as n,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae_raw,
  ROUND(AVG(ABS(adjusted_points - actual_points)), 2) as mae_adjusted,
  ROUND(AVG(predicted_points - actual_points), 2) as bias,
  ROUND(AVG(tier_adjustment), 2) as avg_adjustment,
  ROUND(AVG(ABS(adjusted_points - actual_points)) - AVG(ABS(predicted_points - actual_points)), 2) as mae_change
FROM predictions_with_tier
GROUP BY 1 ORDER BY 1;
```

### Check Current Tier Adjustments
```sql
SELECT
  as_of_date,
  scoring_tier,
  ROUND(avg_signed_error, 2) as bias,
  ROUND(recommended_adjustment, 2) as adjustment,
  sample_size
FROM `nba-props-platform.nba_predictions.scoring_tier_adjustments`
ORDER BY as_of_date DESC, scoring_tier
LIMIT 20;
```

---

## Backfill Commands

### Predictions Backfill
```bash
# Full date range
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2021-12-05 --end-date 2022-01-07

# Specific dates only
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --dates 2021-12-18,2021-12-19,2021-12-21

# Dry run
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2021-12-05 --end-date 2022-01-07 --dry-run
```

### Grading Backfill
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-12-05 --end-date 2022-01-07
```

---

## Bug History (Sessions 120-123)

| Session | Bug | Fix |
|---------|-----|-----|
| 120 | Tiers classified by predicted_points instead of season_avg | Added `classify_tier_by_season_avg()` |
| 121 | Tier boundaries wrong (STAR >=25 instead of >=30) | Fixed boundaries to match tier names |
| 122 | Backfill hitting streaming buffer errors | Documented issue, started backfill |
| 123 | Streaming buffer blocking DML | Changed to batch loading in 3 files |
| 123 | NUMERIC precision errors in batch loading | Added rounding for float values |

---

## Files Modified This Session

1. `backfill_jobs/prediction/player_prop_predictions_backfill.py`
   - Changed `insert_rows_json` to `load_table_from_json` (lines 511-535)

2. `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
   - Changed `insert_rows_json` to `load_table_from_json` (lines 314-337)
   - Added `round_numeric()` helper for NUMERIC precision (lines 244-248)

3. `data_processors/ml_feedback/scoring_tier_processor.py`
   - Changed `insert_rows_json` to `load_table_from_json` (lines 104-125)

---

## Recommendations for Next Session

1. **First**: Re-run the 3 failed dates (Dec 18, 19, 21) after streaming buffer clears

2. **Then**: Decide on tier adjustment strategy:
   - If disabling: Set all adjustments to 0 or remove from predictions
   - If recalibrating: Update `scoring_tier_processor.py` to use season_avg for classification

3. **Consider**: Extending backfill to cover more of 2021-22 season for better analysis

4. **Monitor**: Watch for any streaming buffer errors in future backfills (should be fixed now)

---

## Related Sessions

- Session 120: Identified tier adjustment bug (adjustments making MAE worse)
- Session 121: Fixed classification basis + tier boundaries
- Session 122: Documented streaming buffer issue, started backfill
- Session 123: Fixed streaming buffer, completed backfill, analyzed MAE

---

**End of Handoff**
