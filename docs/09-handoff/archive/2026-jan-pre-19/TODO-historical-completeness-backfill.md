# TODO: Historical Completeness Backfill

**Created:** 2026-01-23
**Status:** On Hold - Needs Design Decision

## Problem

124,564 records in `ml_feature_store_v2` have NULL `historical_completeness` (dating back to Nov 2021).

## Why This Is Hard

The `historical_completeness` field is meant to capture the state of data **at the time features were computed**:
- How many of the last 10 games were available when the processor ran
- Which game dates contributed to the rolling averages

If we backfill now using current data, we'd be computing based on **current state**, not the state when the record was created. This could be misleading because:
- More games might exist now (backfills happened since original computation)
- Data corrections might have changed values

## Options Considered

| Option | Approach | Pros | Cons |
|--------|----------|------|------|
| A | Leave NULL, only populate going forward | Honest, no false data | 124k records without quality signal |
| B | Backfill with current completeness + add `backfill_flag` | Better than nothing | Doesn't reflect actual computation state |
| C | Reprocess all features from scratch | Accurate | Very expensive, changes feature values |
| D | Infer from `created_at` timestamps + audit logs | Could approximate | Complex, might not be accurate |

## Questions to Answer Before Proceeding

1. How are these records used? Do predictions filter on `historical_completeness.is_complete`?
2. Is the main goal forward-looking (detect future cascades) or backward-looking (audit past predictions)?
3. Is Option A acceptable? (Just ensure new records are populated correctly)

## Current State

- Code to populate `historical_completeness` was added in commit `63a05702` on 2026-01-22
- Only Jan 21, 2026 has some records (156) with populated values
- Going forward, new records should have this field populated

## Decision

**Deferred** - Need to clarify use case before investing in backfill approach.
