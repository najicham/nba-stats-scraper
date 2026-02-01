# V8 Hit Rate Fix - Execution Plan

**Created:** 2026-02-01 (Session 63)
**Status:** Ready for Execution
**Priority:** CRITICAL

---

## Executive Summary

V8 hit rate collapsed from 62-70% (Jan 1-7) to 40-58% (Jan 9+) when daily orchestration started. The likely cause is that daily mode uses Phase 3 for Vegas lines (43% coverage) while backfill uses raw tables (95% coverage).

This plan outlines a methodical approach to:
1. **Verify** the hypothesis before making changes
2. **Fix** the daily orchestration
3. **Add monitoring** to prevent recurrence
4. **Backfill** historical data and consider retraining

---

## Phase 1: Verify Hypothesis (CRITICAL - Do First)

### Goal
Confirm that the daily vs backfill code path difference is causing the hit rate drop.

### Test Design

Pick **one specific date** that had bad hit rate and re-process it with backfill mode:

**Recommended Test Date:** `2026-01-12` (43.7% hit rate, 87 predictions)

| Metric | Current (Daily) | Target (Backfill) |
|--------|-----------------|-------------------|
| Hit Rate | 43.7% | >60% |
| Vegas Coverage | ~43% | >90% |

### Step 1.1: Save Current State

```bash
# Save current predictions for comparison
bq query --use_legacy_sql=false --format=csv "
SELECT
  player_lookup,
  predicted_points,
  actual_points,
  prediction_correct,
  confidence_score
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date = '2026-01-12'
" > /tmp/predictions_2026-01-12_before.csv

# Save current feature store for comparison
bq query --use_legacy_sql=false --format=csv "
SELECT
  player_lookup,
  features[OFFSET(25)] as vegas_line,
  features[OFFSET(28)] as has_vegas_line,
  features[OFFSET(24)] as team_win_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-01-12'
  AND ARRAY_LENGTH(features) >= 33
" > /tmp/features_2026-01-12_before.csv
```

### Step 1.2: Re-run Feature Store (Backfill Mode)

```python
# bin/test_backfill_single_date.py
"""
Test script to re-run feature store for a single date in backfill mode.
Saves to a STAGING table for comparison without affecting production.
"""
import sys
from datetime import date
from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor

TEST_DATE = date(2026, 1, 12)
STAGING_TABLE = "nba_predictions.ml_feature_store_v2_staging"

def main():
    # Create processor in backfill mode
    processor = MLFeatureStoreProcessor()
    processor.table_name = "ml_feature_store_v2_staging"  # Write to staging

    # Process with backfill_mode=True
    result = processor.process({
        'analysis_date': TEST_DATE.isoformat(),
        'backfill_mode': True
    })

    print(f"Processed {TEST_DATE}")
    print(f"Records: {result.get('records_written', 'N/A')}")

    # Compare Vegas coverage
    # ... (add comparison logic)

if __name__ == "__main__":
    main()
```

### Step 1.3: Compare Features

```sql
-- Compare Vegas coverage between daily (production) and backfill (staging)
WITH production AS (
  SELECT player_lookup,
    CAST(features[OFFSET(25)] AS FLOAT64) as vegas_line
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date = '2026-01-12'
),
staging AS (
  SELECT player_lookup,
    CAST(features[OFFSET(25)] AS FLOAT64) as vegas_line
  FROM nba_predictions.ml_feature_store_v2_staging
  WHERE game_date = '2026-01-12'
)
SELECT
  'Production (Daily)' as source,
  COUNT(*) as total,
  COUNTIF(vegas_line > 0) as with_vegas,
  ROUND(100.0 * COUNTIF(vegas_line > 0) / COUNT(*), 1) as coverage_pct
FROM production
UNION ALL
SELECT
  'Staging (Backfill)' as source,
  COUNT(*) as total,
  COUNTIF(vegas_line > 0) as with_vegas,
  ROUND(100.0 * COUNTIF(vegas_line > 0) / COUNT(*), 1) as coverage_pct
FROM staging
```

### Step 1.4: Re-run Predictions (Using Staging Features)

```python
# This requires modifying the prediction worker to read from staging table
# OR manually running predictions with the new features
```

### Step 1.5: Compare Results

| Metric | Before (Daily) | After (Backfill) | Difference |
|--------|----------------|------------------|------------|
| Vegas Coverage | ? | ? | ? |
| Predictions Made | 87 | ? | ? |
| Hit Rate | 43.7% | ? | ? |

**Decision Point:**
- If Vegas coverage increases significantly (>80%) AND hit rate improves (>55%), **proceed to Phase 2**
- If no significant difference, **investigate other causes**

---

## Phase 2: Fix Daily Orchestration

### Goal
Make daily orchestration use the same Vegas line source as backfill.

### Option A: Always Use Backfill Mode for Vegas (Recommended)

**Change:** Modify `_batch_extract_vegas_lines()` to ALWAYS query raw betting tables, regardless of backfill_mode.

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

**Rationale:** Raw betting tables have better coverage, and there's no downside to using them for daily processing.

```python
def _batch_extract_vegas_lines(self, game_date: date, player_lookups: List[str],
                                 backfill_mode: bool = False) -> None:
    # CHANGE: Always use raw betting tables for better coverage
    # The Phase 3 source has lower coverage (~43%) due to timing issues

    # Query raw betting tables (same as current backfill mode)
    query = f"""
    WITH odds_api_lines AS (
        -- Primary source: Odds API (DraftKings preferred)
        ...
    ),
    bettingpros_lines AS (
        -- Fallback source: BettingPros
        ...
    )
    ...
    """
```

### Option B: Pass backfill_mode=True for Vegas Only

**Change:** Keep the dual logic but always call with backfill_mode=True for Vegas extraction.

**Less invasive but adds complexity.**

### Deployment Steps

1. Make code change
2. Run unit tests
3. Test on one date manually
4. Deploy to Cloud Run
5. Monitor hit rates for 3 days

---

## Phase 3: Add Monitoring & Timestamps

### Goal
Add fields and checks to detect issues earlier in the future.

### Step 3.1: Add Schema Fields

```sql
-- Add to ml_feature_store_v2
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS feature_source_mode STRING,  -- 'daily' or 'backfill'
ADD COLUMN IF NOT EXISTS feature_generated_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS orchestration_run_id STRING;

-- Add to prediction_accuracy
ALTER TABLE nba_predictions.prediction_accuracy
ADD COLUMN IF NOT EXISTS predicted_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS feature_source_mode STRING;
```

### Step 3.2: Update Code to Populate Fields

**File:** `ml_feature_store_processor.py`

```python
# In _build_record()
record['feature_source_mode'] = 'backfill' if self.is_backfill_mode else 'daily'
record['feature_generated_at'] = datetime.utcnow().isoformat()
record['orchestration_run_id'] = self.run_id
```

### Step 3.3: Add Broken Feature Detection to /validate-daily

```sql
-- Add to validate-daily skill
SELECT
  'pace_score' as feature,
  ROUND(100.0 * COUNTIF(features[OFFSET(7)] = 0) / COUNT(*), 1) as zero_pct,
  CASE WHEN COUNTIF(features[OFFSET(7)] = 0) * 100.0 / COUNT(*) > 90
       THEN '🔴 BROKEN' ELSE '✅ OK' END as status
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT
  'usage_spike_score' as feature,
  ROUND(100.0 * COUNTIF(features[OFFSET(8)] = 0) / COUNT(*), 1) as zero_pct,
  CASE WHEN COUNTIF(features[OFFSET(8)] = 0) * 100.0 / COUNT(*) > 90
       THEN '🔴 BROKEN' ELSE '✅ OK' END as status
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
```

### Step 3.4: Add Daily vs Backfill Comparison Alert

```sql
-- Alert if daily has significantly lower coverage than expected
SELECT
  game_date,
  feature_source_mode,
  COUNT(*) as records,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_coverage
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1, 2
-- ALERT if daily vegas_coverage < 80%
```

---

## Phase 4: Backfill & Consider Retraining

### Goal
Fix historical data and potentially retrain V8 on clean data.

### Step 4.1: Re-run Feature Store Backfill

```bash
# After Phase 2 fix is deployed and verified
# Re-run feature store for Nov 2025 - Feb 2026

PYTHONPATH="$PWD" python -c "
from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor
from datetime import date, timedelta

processor = MLFeatureStoreProcessor()
start = date(2025, 11, 1)
end = date(2026, 2, 1)

current = start
while current <= end:
    try:
        processor.process({'analysis_date': current.isoformat(), 'backfill_mode': True})
        print(f'Processed {current}')
    except Exception as e:
        print(f'Error {current}: {e}')
    current += timedelta(days=1)
"
```

### Step 4.2: Verify Coverage Improved

```sql
SELECT FORMAT_DATE('%Y-%m', game_date) as month,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_coverage
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1 ORDER BY 1
-- Should be >90% for all months after backfill
```

### Step 4.3: Consider Retraining V8

**Options:**
1. **Quick fix:** Just use the improved feature store - existing V8 may perform better
2. **Retrain V8:** Train on Nov 2025+ data with clean features
3. **Train V9:** New model with improved architecture

**Recommendation:** Start with option 1, measure impact, then decide on 2 or 3.

---

## Execution Timeline

| Phase | Task | Est. Effort | Dependency |
|-------|------|-------------|------------|
| **1.1** | Save current state | 10 min | - |
| **1.2** | Create test script | 30 min | 1.1 |
| **1.3** | Run test & compare features | 30 min | 1.2 |
| **1.4** | Re-run predictions (manual) | 1 hour | 1.3 |
| **1.5** | Analyze results & decide | 30 min | 1.4 |
| **2** | Fix daily orchestration | 1 hour | 1.5 confirms hypothesis |
| **2** | Deploy & monitor | 3 days | 2 |
| **3.1** | Add schema fields | 30 min | 2 stable |
| **3.2** | Update code | 1 hour | 3.1 |
| **3.3** | Add validation checks | 30 min | 3.2 |
| **4.1** | Run backfill | 4-6 hours | 2 stable |
| **4.2** | Verify & decide on retrain | 1 hour | 4.1 |

**Total estimated effort:** 1-2 days active work + 3 days monitoring

---

## Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| Daily Vegas coverage | ~43% | >90% |
| Jan 9+ hit rate | 40-58% | >60% |
| Broken features detected | 0 | 2 (pace, usage_spike) |
| Feature source tracking | None | All records |

---

## Rollback Plan

If the fix makes things worse:

1. Revert code change
2. Restore production table from backup (if needed)
3. Investigate what went wrong

---

## Related Documents

- [Session 63 Investigation Findings](./2026-02-01-SESSION-63-INVESTIGATION-FINDINGS.md)
- [Vegas Line Root Cause Analysis](./2026-02-01-VEGAS-LINE-ROOT-CAUSE-ANALYSIS.md)
- [V8 Training Distribution Mismatch](../ml-challenger-training-strategy/V8-TRAINING-DISTRIBUTION-MISMATCH.md)

---

*Created: 2026-02-01 Session 63*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
