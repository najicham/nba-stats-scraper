# Confidence Tier Filtering Implementation Guide

**Created:** 2026-01-09
**Status:** Ready for Implementation
**Priority:** High - Addresses 61.8% hit rate in 88-90 confidence tier
**Estimated Effort:** 2-3 hours

---

## Executive Summary

The 88-90 confidence tier in CatBoost V8 predictions consistently underperforms (61.8% hit rate vs 74-76% for other tiers). This document provides a complete implementation plan to filter these picks while preserving them for shadow tracking.

**Goal:** Stop recommending 88-90 confidence picks to users while continuing to track their performance in case they improve.

---

## Problem Statement

### The Data

| Confidence Tier | Picks | Avg Edge | Hit Rate | ROI |
|-----------------|-------|----------|----------|-----|
| 90+ (Very High) | 35,538 | 3.65 pts | **75.8%** | +44.8% |
| **88-90 (Problem)** | **2,763** | **3.08 pts** | **61.8%** | +18.0% |
| 86-88 (Medium-High) | 9,015 | 5.46 pts | **74.5%** | +42.3% |
| 84-86 (Medium) | 354 | 5.05 pts | **79.9%** | +52.7% |

### Key Findings

1. **Consistent across 5 seasons** - Not random noise
2. **Affects both OVER and UNDER** - Not directional bias
3. **All line ranges affected** - Not player-type specific
4. **Smallest average edge** - These are "borderline" picks

---

## Design Overview

### Architecture

```
┌─────────────────────────┐
│   CatBoost V8           │  Generates: predicted_points, confidence_score
│   (catboost_v8.py)      │  Outputs: recommendation (OVER/UNDER/PASS)
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   Worker                │  ◄── ADD FILTER LOGIC HERE
│   (worker.py)           │
│                         │  If confidence in [0.88, 0.90):
│                         │    - Keep recommendation as OVER/UNDER
│                         │    - Set is_actionable = false
│                         │    - Set filter_reason = 'confidence_tier_88_90'
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   Predictions Table     │  Stores ALL predictions with:
│   (BigQuery)            │  - Original recommendation preserved
│                         │  - is_actionable flag for filtering
│                         │  - filter_reason for audit trail
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   Downstream Systems    │  Filter to: is_actionable = true
│   (API, Dashboards)     │  Shadow track: is_actionable = false
└─────────────────────────┘
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where to filter | worker.py | Centralized, applies to all systems |
| Preserve original recommendation | Yes | Enables shadow tracking |
| Change recommendation field | No | Keep original OVER/UNDER value |
| New fields | is_actionable, filter_reason | Clean separation of concerns |
| Backfill existing data | Yes, with defaults | Backward compatibility |
| Grade filtered picks | Yes | Enables performance monitoring |

---

## Implementation Steps

### Step 1: Schema Changes (BigQuery)

Add two new columns to the predictions table:

```sql
-- Run in BigQuery console
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS is_actionable BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS filter_reason STRING;

-- Verify
SELECT column_name, data_type, is_nullable
FROM `nba-props-platform.nba_predictions.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'player_prop_predictions'
  AND column_name IN ('is_actionable', 'filter_reason');
```

### Step 2: Backfill Existing Data

Mark existing 88-90 confidence predictions as not actionable:

```sql
-- Backfill is_actionable for existing predictions
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions`
SET
  is_actionable = CASE
    -- Handle both decimal (0.88-0.90) and percentage (88-90) formats
    WHEN (confidence_score >= 0.88 AND confidence_score < 0.90) THEN false
    WHEN (confidence_score >= 88 AND confidence_score < 90) THEN false
    ELSE true
  END,
  filter_reason = CASE
    WHEN (confidence_score >= 0.88 AND confidence_score < 0.90) THEN 'confidence_tier_88_90'
    WHEN (confidence_score >= 88 AND confidence_score < 90) THEN 'confidence_tier_88_90'
    ELSE NULL
  END
WHERE system_id = 'catboost_v8'
  AND is_actionable IS NULL;  -- Only update if not already set
```

### Step 3: Update Worker Code

**File:** `predictions/worker/worker.py`

Find the `_build_prediction_result` function (around line 990-1050) and add filtering logic:

```python
def _build_prediction_result(
    player_lookup: str,
    game_id: str,
    system_result: Dict,
    features: Dict,
    line_value: float,
    game_date: str
) -> Dict:
    """Build the final prediction result with confidence tier filtering."""

    # ... existing code to build result ...

    confidence = system_result.get('confidence_score', 0)
    recommendation = system_result.get('recommendation', 'PASS')

    # Normalize confidence to decimal if in percentage format
    confidence_decimal = confidence / 100.0 if confidence > 1 else confidence

    # NEW: Confidence tier filtering
    # 88-90% confidence tier has 61.8% hit rate vs 74-76% for others
    is_actionable = True
    filter_reason = None

    if 0.88 <= confidence_decimal < 0.90:
        is_actionable = False
        filter_reason = 'confidence_tier_88_90'
        # NOTE: We keep the original recommendation (OVER/UNDER) for shadow tracking
        logger.info(
            f"Filtered pick for {player_lookup}: confidence={confidence_decimal:.2f} "
            f"in 88-90 tier, original_recommendation={recommendation}"
        )

    return {
        # ... existing fields ...
        'recommendation': recommendation,  # Keep original - don't change to PASS
        'confidence_score': confidence,

        # NEW: Filtering fields
        'is_actionable': is_actionable,
        'filter_reason': filter_reason,

        # ... rest of existing fields ...
    }
```

### Step 4: Update Batch Staging Writer

**File:** `predictions/worker/batch_staging_writer.py`

Add the new fields to the MERGE statement (around line 370):

```python
# In the MERGE SQL template, add:
is_actionable = S.is_actionable,
filter_reason = S.filter_reason,
```

Also update the staging table schema to include the new fields.

### Step 5: Update Grading Processor

**File:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

The grading processor should continue grading ALL predictions (including filtered ones). No changes needed to the core grading logic.

However, add the filtering fields to the graded output:

```python
# In grade_prediction() method, add to the return dict:
return {
    # ... existing fields ...

    # Filtering fields (pass through from prediction)
    'is_actionable': prediction.get('is_actionable', True),
    'filter_reason': prediction.get('filter_reason'),
}
```

### Step 6: Update Prediction Accuracy Table Schema

```sql
ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN IF NOT EXISTS is_actionable BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS filter_reason STRING;
```

### Step 7: Create Shadow Performance Monitoring View

```sql
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_shadow_performance` AS
SELECT
  filter_reason,
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as filtered_picks,
  COUNTIF(prediction_correct = true) as wins,
  COUNTIF(prediction_correct = false) as losses,
  ROUND(SAFE_DIVIDE(
    COUNTIF(prediction_correct = true),
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0)
  ) * 100, 1) as shadow_hit_rate
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE is_actionable = false
  AND filter_reason IS NOT NULL
GROUP BY 1, 2
ORDER BY 2 DESC, 1;
```

### Step 8: Update Health Alert

**File:** `orchestration/cloud_functions/prediction_health_alert/main.py`

Add check for filtered picks ratio:

```python
def check_filtered_ratio(bq_client, game_date):
    """Check that filtered picks aren't too high (indicates model issues)."""
    query = f"""
    SELECT
      COUNTIF(is_actionable = false) as filtered,
      COUNT(*) as total
    FROM `nba-props-platform.nba_predictions.player_prop_predictions`
    WHERE game_date = '{game_date}'
      AND system_id = 'catboost_v8'
      AND has_prop_line = true
    """
    result = bq_client.query(query).to_dataframe()

    if result.empty:
        return {'status': 'OK', 'filtered_ratio': 0}

    filtered = result.iloc[0]['filtered']
    total = result.iloc[0]['total']
    ratio = filtered / total if total > 0 else 0

    # Alert if more than 20% are filtered (indicates broader model issue)
    if ratio > 0.20:
        return {
            'status': 'WARNING',
            'message': f'High filter ratio: {ratio:.1%} of picks filtered',
            'filtered': filtered,
            'total': total
        }

    return {'status': 'OK', 'filtered_ratio': ratio}
```

---

## Downstream Changes Required

### API Endpoints

Any API that returns picks should filter:

```python
# Example: Get today's picks
def get_todays_picks():
    query = """
    SELECT * FROM player_prop_predictions
    WHERE game_date = CURRENT_DATE('America/Los_Angeles')
      AND is_actionable = true  -- ADD THIS FILTER
      AND has_prop_line = true
      AND recommendation IN ('OVER', 'UNDER')
    ORDER BY confidence_score DESC
    """
```

### Dashboard Queries

Update any dashboard queries to filter actionable picks:

```sql
-- Good picks for display
WHERE is_actionable = true

-- Shadow tracking (internal only)
WHERE is_actionable = false AND filter_reason = 'confidence_tier_88_90'
```

---

## Testing Plan

### Unit Tests

```python
def test_confidence_tier_filtering():
    """Test that 88-90 confidence picks are filtered correctly."""

    # Test case: 89% confidence should be filtered
    result = _build_prediction_result(
        player_lookup='testplayer',
        game_id='20260109_LAL_GSW',
        system_result={'confidence_score': 89, 'recommendation': 'OVER'},
        features={},
        line_value=25.5,
        game_date='2026-01-09'
    )
    assert result['is_actionable'] == False
    assert result['filter_reason'] == 'confidence_tier_88_90'
    assert result['recommendation'] == 'OVER'  # Original preserved

    # Test case: 91% confidence should NOT be filtered
    result = _build_prediction_result(
        player_lookup='testplayer',
        game_id='20260109_LAL_GSW',
        system_result={'confidence_score': 91, 'recommendation': 'OVER'},
        features={},
        line_value=25.5,
        game_date='2026-01-09'
    )
    assert result['is_actionable'] == True
    assert result['filter_reason'] is None
```

### Integration Test

1. Run prediction for a test date
2. Verify some picks have `is_actionable = false`
3. Verify `filter_reason = 'confidence_tier_88_90'`
4. Verify original recommendation is preserved
5. Run grading and verify filtered picks are still graded

### Validation Query

After deployment, run:

```sql
-- Verify filtering is working
SELECT
  is_actionable,
  filter_reason,
  COUNT(*) as cnt,
  AVG(confidence_score) as avg_confidence
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE('America/Los_Angeles')
  AND system_id = 'catboost_v8'
GROUP BY 1, 2;
```

---

## Rollback Plan

If issues arise, filtering can be disabled by:

### Quick Disable (No Code Deploy)

```sql
-- Set all picks to actionable
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions`
SET is_actionable = true, filter_reason = NULL
WHERE game_date >= CURRENT_DATE('America/Los_Angeles');
```

### Code Rollback

In worker.py, comment out or set:

```python
# Disable filtering temporarily
is_actionable = True
filter_reason = None
```

---

## Re-enabling 88-90 Tier

Monitor shadow performance weekly. If hit rate improves:

```sql
-- Check if 88-90 tier should be re-enabled
SELECT
  DATE_TRUNC(game_date, MONTH) as month,
  COUNT(*) as picks,
  ROUND(COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL) * 100, 1) as hit_rate
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE filter_reason = 'confidence_tier_88_90'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY 1
ORDER BY 1 DESC;
```

**Criteria to re-enable:**
- Hit rate > 70% for 3 consecutive months
- At least 200 picks per month
- Consistent across OVER and UNDER

---

## Future Extensions

The `filter_reason` field enables future filtering rules:

| filter_reason | Description | Threshold |
|---------------|-------------|-----------|
| `confidence_tier_88_90` | Current implementation | 88-90% confidence |
| `low_edge` | Edge too small | < 2 points |
| `injury_uncertainty` | Key player questionable | Injury report flag |
| `back_to_back_away` | Fatigue situation | Schedule flag |
| `rookie_early_season` | Insufficient data | < 10 games played |

---

## Files to Modify

| File | Change |
|------|--------|
| `predictions/worker/worker.py` | Add filtering logic in `_build_prediction_result()` |
| `predictions/worker/batch_staging_writer.py` | Add new columns to MERGE |
| `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` | Pass through filtering fields |
| `orchestration/cloud_functions/prediction_health_alert/main.py` | Add filtered ratio check |

---

## Verification Checklist

After implementation:

- [ ] Schema changes applied to `player_prop_predictions`
- [ ] Schema changes applied to `prediction_accuracy`
- [ ] Backfill query run for historical data
- [ ] Worker code updated and deployed
- [ ] Grading processor updated
- [ ] Health alert updated
- [ ] Shadow performance view created
- [ ] Unit tests passing
- [ ] Integration test passing
- [ ] Verified in production with validation query
- [ ] Downstream APIs filtering correctly
- [ ] Documentation updated

---

## Ongoing Monitoring & Review Plan

### Related Documentation

- **Decision Rationale:** See [FILTER-DECISIONS.md](./FILTER-DECISIONS.md) for full analysis and rollback instructions

### Weekly Shadow Performance Check

Run this query weekly to monitor how filtered picks are performing:

```sql
-- Weekly shadow performance check
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as filtered_picks,
  COUNTIF(prediction_correct = true) as wins,
  COUNTIF(prediction_correct = false) as losses,
  ROUND(SAFE_DIVIDE(
    COUNTIF(prediction_correct = true),
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0)
  ) * 100, 1) as shadow_hit_rate,
  ROUND((COUNTIF(prediction_correct = true) * 91.0 -
         COUNTIF(prediction_correct = false) * 100.0) /
        NULLIF(COUNT(*) * 110.0, 0) * 100, 1) as shadow_roi
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE filter_reason = 'confidence_tier_88_90'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 28 DAY)
GROUP BY 1
ORDER BY 1 DESC;
```

### Monthly Review Checklist

| Check | Query/Action | Decision |
|-------|--------------|----------|
| Shadow hit rate trend | Run weekly query, check 4-week trend | If > 70% for 4 weeks, flag for review |
| Sample size | Check picks per week | Need 50+ picks/week for significance |
| Compare to 90+ tier | Run tier comparison query | Gap should be narrowing |
| OVER vs UNDER split | Check directional balance | Should be balanced |

### Monthly Comparison Query

```sql
-- Monthly comparison: filtered tier vs active tiers
WITH all_predictions AS (
  SELECT
    DATE_TRUNC(game_date, MONTH) as month,
    CASE
      WHEN filter_reason = 'confidence_tier_88_90' THEN 'FILTERED: 88-90'
      WHEN confidence_score >= 90 OR (confidence_score >= 0.90 AND confidence_score <= 1) THEN 'ACTIVE: 90+'
      WHEN (confidence_score >= 86 AND confidence_score < 88) OR (confidence_score >= 0.86 AND confidence_score < 0.88) THEN 'ACTIVE: 86-88'
      ELSE 'OTHER'
    END as tier,
    prediction_correct
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE has_prop_line = true
    AND recommendation IN ('OVER', 'UNDER')
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
)
SELECT
  month,
  tier,
  COUNT(*) as picks,
  ROUND(SAFE_DIVIDE(
    COUNTIF(prediction_correct = true),
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0)
  ) * 100, 1) as hit_rate
FROM all_predictions
WHERE tier != 'OTHER'
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

### Re-enabling Decision Framework

If shadow performance shows sustained improvement (see [FILTER-DECISIONS.md](./FILTER-DECISIONS.md#re-enabling-criteria)):

1. **Confirm criteria met:** 70%+ hit rate, 3 months, 200+ picks/month
2. **Run rollback SQL:** Quick re-enable without code deploy
3. **Monitor closely:** Check daily for first week
4. **Update documentation:** Record decision in FILTER-DECISIONS.md

### Review Schedule

| Date | Review Type | Status |
|------|-------------|--------|
| 2026-01-17 | Week 1 shadow check | Pending |
| 2026-01-24 | Week 2 shadow check | Pending |
| 2026-01-31 | Week 3 shadow check | Pending |
| 2026-02-07 | Week 4 + Monthly review | Pending |
| 2026-03-07 | Month 2 review | Pending |
| 2026-04-07 | Quarterly decision point | Pending |

---

## Document History

| Date | Change |
|------|--------|
| 2026-01-09 | Initial implementation guide created |
| 2026-01-10 | Added monitoring/review plan, linked to FILTER-DECISIONS.md |
