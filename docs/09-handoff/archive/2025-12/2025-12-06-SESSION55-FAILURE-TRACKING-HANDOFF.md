# Session 55: Failure Tracking Observability Handoff

**Date:** 2025-12-06
**Previous Session:** 54 (Backfill Observability Implementation)
**Status:** Design complete, implementation in progress

## Executive Summary

This session identified a critical observability gap: **"When a record is missing, is it expected or an error?"** We created a comprehensive design document and started implementing failure tracking across all processors.

## The Problem

When running backfills or daily processing, some records don't get created. Without failure tracking, we have no visibility into:
- Is the missing record **expected** (insufficient data, early season, etc.)?
- Is it an **actual error** that needs investigation?

## Solution Architecture

**ONE shared failure table:** `nba_processing.precompute_failures`

Each processor saves failure records with:
- `processor_name` - which processor
- `entity_id` - player_lookup, team_abbr, or 'DATE_LEVEL'
- `failure_category` - INSUFFICIENT_DATA, MISSING_UPSTREAM, PROCESSING_ERROR, etc.
- `analysis_date` - the date being processed
- `failure_reason` - detailed explanation

## Current State

### Failure Tracking by Processor

| Phase | Processor | Has Tracking? | Status |
|-------|-----------|---------------|--------|
| 4 | PSZA (PlayerShotZone) | Yes | Working, has data |
| 4 | PDC (PlayerDailyCache) | Yes | Backfill running NOW |
| 4 | PCF (PlayerComposite) | Yes | Code exists, needs backfill |
| 4 | MLFS (MLFeatureStore) | Yes | Code exists, needs backfill |
| 4 | TDZA (TeamDefenseZone) | **NO** | **NEEDS IMPLEMENTATION** |
| 3 | All Phase 3 processors | **NO** | **NEEDS IMPLEMENTATION** |
| 5 | Phase 5 processors | Unknown | Needs audit |

### Running Processes

**PDC Backfill (Nov 5-30):**
- Log: `/tmp/pdc_backfill_v2.log`
- Progress: 4/25 dates (~20 min remaining)
- Saving failure records to BigQuery

Monitor with:
```bash
tail -f /tmp/pdc_backfill_v2.log | grep -E "Processing game date|Saved.*failure"
```

## Validation Script

The script `scripts/validate_backfill_coverage.py` does exactly what we need:

```bash
# Basic coverage check
python scripts/validate_backfill_coverage.py \
  --start-date 2021-11-05 --end-date 2021-11-30

# TRUE RECONCILIATION (what we care about)
python scripts/validate_backfill_coverage.py \
  --start-date 2021-11-05 --end-date 2021-11-30 --reconcile
```

The `--reconcile` mode shows:
- **Expected:** Players who played (from player_game_summary)
- **Has Record:** Players with output records
- **Has Failure:** Players with failure records explaining why no output
- **Unaccounted:** Players with NEITHER (THIS IS THE GAP!)

**Target State:** `Unaccounted = 0` for all processors

## Immediate Next Steps

### 1. Wait for PDC Backfill to Complete
```bash
# Monitor
tail -f /tmp/pdc_backfill_v2.log | grep "Processing game date"

# Check when done
grep "Backfill complete" /tmp/pdc_backfill_v2.log
```

### 2. Run PCF Backfill with New Code
```bash
rm -rf /tmp/backfill_checkpoints/player_composite*

python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-30 2>&1 | tee /tmp/pcf_backfill_v2.log
```

### 3. Run MLFS Backfill for Early Nov
```bash
rm -rf /tmp/backfill_checkpoints/ml_feature*

python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-09 2>&1 | tee /tmp/mlfs_early_nov.log
```

### 4. Run Validation
```bash
python scripts/validate_backfill_coverage.py \
  --start-date 2021-11-05 --end-date 2021-11-30 --reconcile
```

### 5. Add Failure Tracking to TDZA
See design doc for implementation pattern.

## Design Document

**Location:** `docs/08-projects/current/observability/FAILURE-TRACKING-DESIGN.md`

Contains:
- Problem statement
- Current state audit (all processors by phase)
- Implementation pattern
- Task list for each processor
- Success criteria
- Quick reference SQL queries

## Key Files Modified (Session 54)

1. `data_processors/precompute/precompute_base.py`
   - Added `save_failures_to_bq()` method
   - Added `_record_date_level_failure()` method

2. `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
   - Added failure tracking and `save_failures_to_bq()` call

3. `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`
   - Added failure tracking and `save_failures_to_bq()` call

4. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
   - Added failure tracking and `save_failures_to_bq()` call

5. `scripts/validate_backfill_coverage.py`
   - Added `--reconcile` mode for true player-level reconciliation

## Key Files to Modify (Next Session)

1. `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`
   - Add `save_failures_to_bq()` call (tracking exists, save doesn't)

2. Phase 3 processors (bigger project):
   - `data_processors/analytics/player_game_summary/`
   - `data_processors/analytics/team_offense_game_summary/`
   - `data_processors/analytics/team_defense_game_summary/`
   - `data_processors/analytics/upcoming_player_game_context/`
   - `data_processors/analytics/upcoming_team_game_context/`

## Quick Reference Commands

```bash
# Check failure records
bq query --use_legacy_sql=false "
SELECT processor_name, failure_category, COUNT(*)
FROM nba_processing.precompute_failures
GROUP BY 1, 2 ORDER BY 1, 2"

# Check PDC failures for Nov 5
bq query --use_legacy_sql=false "
SELECT failure_category, COUNT(*) as count
FROM nba_processing.precompute_failures
WHERE processor_name = 'PlayerDailyCacheProcessor'
  AND analysis_date = '2021-11-05'
GROUP BY failure_category"

# Run validation
python scripts/validate_backfill_coverage.py \
  --start-date 2021-11-05 --end-date 2021-11-30 --reconcile
```

## Success Criteria

After implementing failure tracking on all processors:

```
Processor   Expected   Has Record   Has Failure   Unaccounted   Coverage
-------------------------------------------------------------------------
PSZA           XXXX         XXXX          XXXX             0       100%
PDC            XXXX         XXXX          XXXX             0       100%
PCF            XXXX         XXXX          XXXX             0       100%
MLFS           XXXX         XXXX          XXXX             0       100%
```

**Unaccounted = 0** means complete observability.

## Related Documentation

- Design Doc: `docs/08-projects/current/observability/FAILURE-TRACKING-DESIGN.md`
- Session 54: `docs/09-handoff/2025-12-06-SESSION54-OBSERVABILITY-HANDOFF.md`
- Validation Script: `scripts/validate_backfill_coverage.py`
