# Processor Optimization Project

**Created:** 2025-12-05
**Status:** In Progress
**Priority:** Critical - Enables 4-season backfill at feasible speed

---

## Project Goal

Optimize Phase 4 precompute processors to reduce processing time from ~33 minutes/day to ~3-5 minutes/day, enabling practical backfill of 4 seasons (~1,400 days) of historical data.

---

## Background

The MLFeatureStoreProcessor was averaging **33 minutes per day** due to:
1. Sequential BigQuery queries (4 separate hash queries)
2. Inefficient upstream completeness checks (4 separate queries)
3. Slow write pattern (DELETE + batch INSERTs creating streaming buffer issues)

With 1,400 days to backfill, the original approach would take **770+ hours** (32 days of continuous processing).

---

## Optimization Summary

### MLFeatureStoreProcessor (Primary Focus)

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Total time/day** | ~33 min | ~3.2 min | **10.3x faster** |
| Source hash queries | 30-60s | 2.5s | 12-24x |
| Completeness check | 120-180s | 10s | 12-18x |
| Write phase | 600-1200s | 6.9s | **87-174x** |

### Key Changes

1. **Combined Hash Queries** (`ml_feature_store_processor.py:352-407`)
   - Before: 4 sequential BigQuery queries
   - After: 1 UNION ALL query

2. **Combined Completeness Queries** (`ml_feature_store_processor.py:566-702`)
   - Before: 4 separate queries
   - After: 2 combined queries with FULL OUTER JOINs

3. **MERGE Write Pattern** (`batch_writer.py`)
   - Before: DELETE all rows + batch INSERTs (100 rows each)
   - After: Load to temp table + MERGE (atomic operation)
   - Bonus: Eliminates streaming buffer issues

4. **Deduplication Fix** (`batch_writer.py:274-284`)
   - Added ROW_NUMBER() to handle duplicate player records in MERGE

---

## Processor Parallelization Status

All Phase 4 processors now use ThreadPoolExecutor:

| Processor | Workers | Status |
|-----------|---------|--------|
| PlayerShotZoneAnalysisProcessor | 10 | Complete |
| PlayerDailyCacheProcessor | 8 | Complete |
| PlayerCompositeFactorsProcessor | 10 | Complete |
| TeamDefenseZoneAnalysisProcessor | 4 | Complete |
| MLFeatureStoreProcessor | 10 | Complete |

---

## Current Backfill Status

### First Month (2021-10-19 to 2021-11-30)

| Phase | Table | Status |
|-------|-------|--------|
| Phase 3 | player_game_summary | 100% data_hash |
| Phase 3 | team_defense_game_summary | 100% data_hash |
| Phase 3 | team_offense_game_summary | 100% data_hash |
| Phase 3 | upcoming_player_game_context | 100% data_hash |
| Phase 3 | upcoming_team_game_context | 100% data_hash |
| Phase 4 | player_daily_cache | Nov 5-30 covered |
| Phase 4 | player_composite_factors | Nov 7-28 covered |
| Phase 4 | player_shot_zone_analysis | Nov 5-30 covered |
| Phase 4 | team_defense_zone_analysis | Nov 2-30 covered |
| Phase 4 | ml_feature_store | In progress (Nov 7-28) |

---

## Files Modified

### Session 49-50 Changes

1. **data_processors/precompute/ml_feature_store/ml_feature_store_processor.py**
   - `_extract_source_hashes()` - Combined query
   - `_query_upstream_completeness()` - Combined queries
   - Timing instrumentation throughout

2. **data_processors/precompute/ml_feature_store/batch_writer.py**
   - `write_batch()` - New MERGE pattern with deduplication
   - `_load_to_temp_table()` - Single batch load
   - `_merge_to_target()` - MERGE query with ROW_NUMBER dedup
   - `write_batch_legacy()` - Preserved for rollback

---

## Project Structure

```
docs/08-projects/current/processor-optimization/
├── overview.md          # This file - project summary
├── checklist.md         # Processor-by-processor status
└── changelog.md         # Session-by-session updates
```

---

## Next Steps

1. Complete MLFeatureStore backfill for Nov 7-28 (in progress)
2. Validate data quality after backfill
3. Extend backfill to remaining seasons
4. Monitor production performance

---

## Related Documentation

- **Session 49 Handoff:** `docs/09-handoff/2025-12-05-SESSION49-MLFEATURESTORE-OPTIMIZATION.md`
- **BigQuery Best Practices:** `docs/05-development/guides/bigquery-best-practices.md`
- **Backfill Project:** `docs/08-projects/current/backfill/`

---

**Last Updated:** 2025-12-05 (Session 50)
**Next Review:** After first month backfill complete
