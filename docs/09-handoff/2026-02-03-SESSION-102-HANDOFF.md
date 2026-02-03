# Session 102 Handoff - Feb 3, 2026

## Session Summary

Fixed a critical bug where regeneration batches were losing predictions due to edge filtering, leaving orphan superseded predictions.

## Issue Identified

After Session 101's regeneration to fix the feature mismatch issue:
- **Feb 2**: Only 11 active catboost_v9 predictions (expected 69)
- **Feb 3**: Only 45 active catboost_v9 predictions (expected 154)
- **92 players** missing predictions including Markkanen, LeBron, Luka

### Root Cause

The MERGE edge filter (MIN_EDGE_THRESHOLD=3.0) was blocking regenerated predictions:

1. Old predictions marked `superseded=TRUE` (from 07:00 overnight batch)
2. Regeneration created new predictions with **corrected features**
3. Corrected features produced **different predicted values** (closer to betting lines)
4. New predictions had edge < 3.0 → **filtered out during MERGE**
5. Old superseded predictions remained unchanged → **no active prediction exists**

Example: Markkanen
- Old catboost_v9: 15.3 pts predicted (edge 11.2) - with bad features
- New catboost_v9: 27.0 pts predicted (edge 0.5) - with correct features
- The correct prediction was filtered because edge < 3!

## Fix Applied

Modified `predictions/shared/batch_staging_writer.py`:
- Auto-detect regeneration batches by `batch_id.startswith("regen_")`
- Skip edge filter for regeneration batches
- All predictions included, preventing orphan superseded predictions

```python
# Session 102: Auto-detect regeneration batches and skip edge filter
is_regeneration = batch_id.startswith("regen_")
skip_edge_filter = is_regeneration
```

## Results After Fix

| Date | Before | After | Quality |
|------|--------|-------|---------|
| Feb 2 | 11 active | 69 active | 87.0 |
| Feb 3 | 45 active | 154 active | 87.6 |

All 154 players for Feb 3 and 69 players for Feb 2 now have complete predictions.

## Commits

| Commit | Description |
|--------|-------------|
| 10da0ee4 | fix: Skip edge filter for regeneration batches (Session 102) |

## Files Modified

- `predictions/shared/batch_staging_writer.py` - Skip edge filter for regeneration batches
- `predictions/coordinator/coordinator.py` - Rate limit publishing (Session 101 change)

## Verification

```sql
-- After regeneration
SELECT game_date, system_id,
  COUNTIF(superseded IS NOT TRUE) as active
FROM nba_predictions.player_prop_predictions
WHERE game_date IN ('2026-02-02', '2026-02-03')
  AND system_id = 'catboost_v9'
GROUP BY 1, 2
-- Feb 2: 69 active, Feb 3: 154 active
```

## Open Items

1. **P2**: Consider making edge filter behavior configurable per batch (not just auto-detect)
2. **P2**: Add monitoring for "orphan superseded predictions" to catch this issue proactively
3. **P3**: Update `/validate-daily` skill to check for mismatched active/superseded counts

## Key Insight

The feature mismatch fix (Session 101) **changed the predictions** because correct features lead to different model outputs. The old predictions had high edges because the bad features produced outlier predictions. The correct predictions are actually more accurate (closer to betting lines) but have lower "edge" values.

This highlights an important system behavior: **edge is not a direct quality metric** - low edge can indicate a high-confidence prediction that agrees with the market, not just a low-quality bet.
