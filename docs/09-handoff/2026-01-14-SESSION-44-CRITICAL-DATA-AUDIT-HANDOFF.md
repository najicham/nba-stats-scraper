# Session 44 Handoff: Critical Data Audit & Pipeline Fixes

**Date:** 2026-01-14
**Session:** 44
**Status:** CRITICAL FINDINGS - Action Required
**Duration:** Deep investigation with 4 parallel agents

---

## Quick Start for Next Session

### Essential Reading
```
docs/08-projects/current/ml-model-v8-deployment/CRITICAL-DATA-AUDIT-2026-01-14.md  # Main findings
docs/08-projects/current/monitoring-improvements/ODDSAPI-BATCH-IMPLEMENTATION.md   # Future fix plan
```

### Key SQL Views (Use These!)
```sql
-- ALWAYS use these views for accurate analysis:
SELECT * FROM nba_predictions.prediction_accuracy_real_lines;
SELECT * FROM nba_predictions.daily_performance_real_lines;

-- NEVER use prediction_accuracy directly without filtering line_value != 20
```

### Verification Commands
```bash
# Check daily hit rates with real lines
bq query --use_legacy_sql=false 'SELECT * FROM nba_predictions.daily_performance_real_lines ORDER BY game_date DESC LIMIT 7'

# Check catboost_v8 performance by edge
bq query --use_legacy_sql=false '
SELECT
  CASE WHEN ABS(predicted_points - line_value) >= 5 THEN "5+ edge"
       WHEN ABS(predicted_points - line_value) >= 3 THEN "3-5 edge"
       ELSE "<3 edge" END as edge_tier,
  recommendation,
  COUNT(*) as picks,
  ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 1) as hit_rate
FROM nba_predictions.prediction_accuracy_real_lines
WHERE system_id = "catboost_v8"
GROUP BY 1, 2 ORDER BY 1, 2'
```

---

## Critical Discovery: Fake Line Data

### The Problem

**26% of predictions (1,570 of 5,976) used fake `line_value=20`** instead of real sportsbook lines. This was a default value in pre-v3.2 worker code.

| Date | Fake Lines (line=20) | Impact |
|------|---------------------|--------|
| Jan 9 | **100%** | All predictions used fake lines |
| Jan 10 | **63%** | Mixed real/fake |
| Jan 11-13 | **0%** | All real lines |

### Impact on Reported Metrics

| Metric | Session 43 (Fake) | Reality (Real Lines) |
|--------|-------------------|----------------------|
| Overall Hit Rate | 84% | **42%** |
| UNDER Hit Rate | 95% | **57%** |
| OVER Hit Rate | 53% | **51%** |
| 5+ Edge Hit Rate | 93% | **59%** |

### Root Cause

Pre-v3.2 worker code defaulted to `line_value=20` when no prop was available:
- `has_prop_line`: NULL (not tracked)
- `line_source`: NULL (not tracked)
- `estimated_line_value`: NULL

Model predicts 8-12 points for most players, so "UNDER 20" was almost always correct → artificial 84% hit rate.

---

## Validated Findings (Use These!)

### catboost_v8 is the ONLY Good System

| System | Hit Rate | Bias | Status |
|--------|----------|------|--------|
| **catboost_v8** | **57.6%** | +0.13 | ✅ USE THIS |
| ensemble_v1 | 25.7% | -1.71 | ❌ DO NOT USE |
| zone_matchup_v1 | 22.0% | -3.85 | ❌ DO NOT USE |
| moving_average_baseline_v1 | 21.7% | -2.61 | ❌ DO NOT USE |
| similarity_balanced_v1 | 21.3% | +0.26 | ❌ DO NOT USE |

### catboost_v8 Performance by Edge (VALIDATED)

| Configuration | Picks | Hit Rate |
|---------------|-------|----------|
| **catboost_v8 + UNDER + 5+ edge** | 5,357 | **88.3%** |
| **catboost_v8 + OVER + 5+ edge** | 7,459 | **83.9%** |
| catboost_v8 + UNDER + 3-5 edge | 6,665 | 79.3% |
| catboost_v8 + OVER + 3-5 edge | 6,346 | 74.6% |
| catboost_v8 + <3 edge | varies | 63-69% |

### xgboost_v1 is a MOCK Model

The "best performing" xgboost_v1 (87.5%) was actually a test heuristic, not real ML:
```python
# From mock_xgboost_model.py - NOT real ML!
baseline = points_last_5 * 0.35 + points_last_10 * 0.40 + points_season * 0.25
```

It only appeared on Jan 9-10 due to a feature version bug.

---

## Fixes Applied This Session

### 1. MERGE Deduplication (analytics_base.py)

**Problem:** `PlayerGameSummaryProcessor` failing with "UPDATE/MERGE must match at most one source row"

**Fix:** Added ROW_NUMBER deduplication to `_save_with_proper_merge()`:
```python
# File: data_processors/analytics/analytics_base.py:1763-1785
MERGE `{table_id}` AS target
USING (
    SELECT * EXCEPT(__row_num) FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY {primary_keys_partition}
            ORDER BY processed_at DESC
        ) as __row_num
        FROM `{temp_table_id}`
    ) WHERE __row_num = 1
) AS source
...
```

### 2. SQL Views for Clean Data

Created views that exclude fake line=20 data:
- `nba_predictions.prediction_accuracy_real_lines`
- `nba_predictions.daily_performance_real_lines`

### 3. Container Concurrency Reduction

**Problem:** OddsAPI processors taking 60+ minutes due to resource contention

**Fix:** Reduced Phase 2 containerConcurrency from 10 to 4
```bash
gcloud run services update nba-phase2-raw-processors --region=us-west2 --concurrency=4
# Deployed as revision 00091
```

### 4. Best Bets Strategy Update

Updated `data_processors/publishing/best_bets_exporter.py`:
- Now uses catboost_v8 ONLY
- Allows both UNDER and OVER (both 83%+ with 5+ edge)
- Tiers based on edge, not confidence
- Excludes fake line_value=20 data

---

## Files Changed

| File | Change |
|------|--------|
| `data_processors/analytics/analytics_base.py` | Added ROW_NUMBER deduplication |
| `data_processors/publishing/best_bets_exporter.py` | Updated strategy |
| `docs/.../ml-model-v8-deployment/ANALYSIS-FRAMEWORK.md` | Added deprecation warning |
| `docs/.../ml-model-v8-deployment/CRITICAL-DATA-AUDIT-2026-01-14.md` | **NEW** |
| `docs/.../monitoring-improvements/ODDSAPI-BATCH-IMPLEMENTATION.md` | **NEW** |

---

## Future Recommendations

### HIGH Priority

#### 1. Implement OddsAPI Batch Processing
**Effort:** 2-3 hours
**Location:** See `docs/.../monitoring-improvements/ODDSAPI-BATCH-IMPLEMENTATION.md`

The container concurrency reduction helps, but proper batch processing (like ESPN/BR rosters) would eliminate MERGE contention entirely.

Pattern:
```python
# First file triggers batch processing with Firestore lock
lock_id = f"oddsapi_batch_{game_date}"
lock_ref.create(lock_data)  # Atomic - fails if exists

batch_processor = OddsApiBatchProcessor()
batch_processor.run(...)  # Single MERGE instead of 14
```

#### 2. Fix Bench Player Underprediction
**Effort:** Investigation + retraining
**Impact:** 145K picks with -2.3 pts bias

The model systematically underpredicts bench players by 2.3 points. This is the largest source of prediction error.

Investigation needed:
- Is training data biased toward starters?
- Are features missing for bench players?
- Should bench players have a separate model?

#### 3. Remove Other Systems from Production
**Effort:** 1 hour
**Impact:** Cleaner predictions, less confusion

Since catboost_v8 is the only good system (57.6% vs 21-26% for others), consider:
- Removing ensemble_v1, zone_matchup_v1, moving_average_baseline_v1, similarity_balanced_v1
- Or at minimum, excluding them from grading/analysis

### MEDIUM Priority

#### 4. Backfill Historical Data with Real Lines
**Effort:** 2-3 hours

The Jan 9-10 predictions have fake lines. Options:
- Re-run enrichment processor for those dates
- Mark those predictions as "ungraded" in BigQuery
- Exclude from all historical analysis

#### 5. Add Data Quality Monitoring
**Effort:** 1-2 hours

Create alerts for:
- `line_value = 20` appearing in new predictions
- Systems other than catboost_v8 being used
- High percentage of NULL lines

#### 6. Cloud Monitoring Alert for Auth Errors
**Effort:** 5 minutes (manual)
**Location:** See `docs/.../monitoring-improvements/TODO.md`

The log-based metric exists, just needs alert policy setup in Cloud Console.

### LOW Priority

#### 7. Investigate 88-90% Confidence Anomaly
**Effort:** 1-2 hours

The 88-90% confidence tier has poor hit rates. Unclear why. Query to investigate:
```sql
SELECT system_id, recommendation, COUNT(*), AVG(absolute_error)
FROM nba_predictions.prediction_accuracy_real_lines
WHERE confidence_score >= 0.88 AND confidence_score < 0.90
GROUP BY 1, 2;
```

#### 8. Document Model Training Data
**Effort:** 1 hour

The catboost_v8 model was trained on 76,863 games, but:
- Was training data affected by the line=20 issue?
- What features were used?
- When was it last trained?

---

## Key Tables & Views

### Use These (Clean Data)
```sql
nba_predictions.prediction_accuracy_real_lines  -- Excludes line=20
nba_predictions.daily_performance_real_lines    -- Daily summary
```

### Avoid These (Has Fake Data)
```sql
nba_predictions.prediction_accuracy  -- Contains line=20 fake data!
```

### For System Analysis
```sql
-- catboost_v8 only
SELECT * FROM nba_predictions.prediction_accuracy_real_lines
WHERE system_id = 'catboost_v8';
```

---

## Quick Reference Queries

### Check Current Hit Rates
```bash
bq query --use_legacy_sql=false '
SELECT game_date, hit_rate, prediction_bias, total_picks
FROM nba_predictions.daily_performance_real_lines
ORDER BY game_date DESC LIMIT 7'
```

### Check System Performance
```bash
bq query --use_legacy_sql=false '
SELECT system_id, COUNT(*) as picks,
       ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 1) as hit_rate
FROM nba_predictions.prediction_accuracy_real_lines
GROUP BY 1 ORDER BY hit_rate DESC'
```

### Verify No Fake Lines in New Data
```bash
bq query --use_legacy_sql=false '
SELECT game_date, COUNTIF(line_value = 20) as fake_lines
FROM nba_predictions.prediction_accuracy
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1 ORDER BY 1 DESC'
```

---

## Git Status

### Modified (Uncommitted)
```
data_processors/analytics/analytics_base.py
data_processors/publishing/best_bets_exporter.py
docs/08-projects/current/ml-model-v8-deployment/ANALYSIS-FRAMEWORK.md
```

### New Files (Untracked)
```
docs/08-projects/current/ml-model-v8-deployment/CRITICAL-DATA-AUDIT-2026-01-14.md
docs/08-projects/current/monitoring-improvements/ODDSAPI-BATCH-IMPLEMENTATION.md
docs/09-handoff/2026-01-14-SESSION-44-CRITICAL-DATA-AUDIT-HANDOFF.md
```

### Deployed Changes
- Phase 2 Cloud Run: revision 00091 (containerConcurrency: 4)

---

## Summary

This session discovered a **critical data integrity issue** where 26% of predictions used fake `line_value=20`, inflating reported hit rates from 42% to 84%.

**Good news:** catboost_v8 with 5+ edge achieves **83-88% hit rates** with real sportsbook lines - this is validated, real performance.

**Key actions for next session:**
1. Commit the fixes
2. Consider implementing OddsAPI batch processing
3. Investigate bench player underprediction

---

*Last Updated: 2026-01-14 Session 44*
