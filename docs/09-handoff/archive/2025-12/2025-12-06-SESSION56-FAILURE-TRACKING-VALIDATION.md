# Session 56: Failure Tracking Validation

**Date:** 2025-12-06
**Previous Session:** 55 (Failure Tracking Observability)
**Status:** Backfills complete, validation reveals key insight

## Executive Summary

This session completed the backfills with failure tracking and ran validation. Key finding: **PDC and PSZA achieve near-100% reconciliation, but PCF/MLFS use date-level failures rather than player-level failures**.

## Accomplishments

### 1. Added Failure Tracking to TDZA
- Added `save_failures_to_bq()` call to `team_defense_zone_analysis_processor.py`
- File modified: `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py:764-778`

### 2. Completed Backfills

| Processor | Date Range | Status |
|-----------|------------|--------|
| PDC | Nov 5-30 | Complete |
| PCF | Nov 5-30 | Complete |
| MLFS | Nov 5-9 | Complete |

### 3. Validation Results

```
Processor   Coverage   Unaccounted   Status
---------------------------------------------
PDC            98%            67    EXCELLENT (Nov 29-30 was running)
PSZA           99%            30    EXCELLENT
PCF            86%           600    NEEDS WORK (date-level failures only)
MLFS           75%          1060    NEEDS WORK (date-level failures only)
```

## Key Insight: Date-Level vs Player-Level Failures

**The Problem:**
- PCF and MLFS record failures at the **date level** when upstream data is missing
- They record `entity_id='DATE_LEVEL'` with one row per missing date
- The validation script expects **player-level** failures (one row per player)

**Example:**
- Nov 5 is missing PSZA data
- PCF records: 1 failure with `entity_id='DATE_LEVEL'`
- Validation expects: 201 failures (one per player who played)

**Result:** Dates with missing upstream data show 0% coverage in validation even though failures are being tracked.

## Failure Records in BigQuery

```sql
SELECT processor_name, failure_category, COUNT(*) as count
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN '2021-11-01' AND '2021-11-30'
GROUP BY 1, 2 ORDER BY 1, 2
```

| Processor | Category | Count |
|-----------|----------|-------|
| MLFeatureStoreProcessor | MISSING_DEPENDENCIES | 6 |
| PlayerCompositeFactorsProcessor | MISSING_DEPENDENCIES | 6 |
| PlayerDailyCacheProcessor | INSUFFICIENT_DATA | 1,929 |
| PlayerDailyCacheProcessor | MISSING_DEPENDENCY | 1,043 |
| PlayerShotZoneAnalysisProcessor | INSUFFICIENT_DATA | 4,662 |

## Next Steps (Priority Order)

### 1. Re-run PDC for Nov 29-30 (Quick Win)
```bash
rm -rf /tmp/backfill_checkpoints/player_daily_cache*
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2021-11-29 --end-date 2021-11-30
```

### 2. Decision: Date-Level vs Player-Level Failures
Two options for PCF/MLFS:

**Option A: Expand date-level failures to player-level**
- When upstream data is missing, enumerate all players who played that date
- Record individual failure for each player
- Pro: Validation shows 100%
- Con: More rows in failures table

**Option B: Update validation to handle date-level failures**
- Modify `validate_backfill_coverage.py` to recognize date-level failures
- Count date-level failure as "covering" all players for that date
- Pro: No changes to processors
- Con: Less granular tracking

### 3. TDZA Backfill with Failure Tracking
```bash
python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-30 2>&1 | tee /tmp/tdza_backfill_v2.log
```

## Files Modified This Session

1. `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`
   - Added failure tracking save (lines 764-778)

## Quick Reference Commands

```bash
# Run validation
python scripts/validate_backfill_coverage.py \
  --start-date 2021-11-05 --end-date 2021-11-30 --reconcile

# Check failure counts
bq query --use_legacy_sql=false "
SELECT processor_name, failure_category, COUNT(*) as count
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN '2021-11-01' AND '2021-11-30'
GROUP BY 1, 2 ORDER BY 1, 2"

# Check date-level failures
bq query --use_legacy_sql=false "
SELECT processor_name, analysis_date, failure_reason
FROM nba_processing.precompute_failures
WHERE entity_id = 'DATE_LEVEL'
ORDER BY processor_name, analysis_date"
```

## Related Documentation

- Previous Session: `docs/09-handoff/2025-12-06-SESSION55-FAILURE-TRACKING-HANDOFF.md`
- Design Doc: `docs/08-projects/current/observability/FAILURE-TRACKING-DESIGN.md`
- Validation Script: `scripts/validate_backfill_coverage.py`
