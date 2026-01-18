# NBA Backfill Gap Analysis

**Generated**: 2026-01-17 14:00 UTC
**Analysis Scope**: Phase 3 → Phase 4 gaps (dates with analytics but missing precompute)

## Executive Summary

- **Total Phase 3 dates**: 918 (from Nov 2021 to Jan 2026)
- **Dates with Phase 4**: 816
- **Dates missing Phase 4**: **102 dates**
- **Completion**: 89% (816/918)

## Gap Breakdown by Year

| Year | Phase 3 | Phase 4 | Missing | % Complete |
|------|---------|---------|---------|------------|
| 2021 | 59 | 58 | **1** | 98% |
| 2022 | 213 | 188 | **25** | 88% |
| 2023 | 203 | 177 | **26** | 87% |
| 2024 | 210 | 186 | **24** | 89% |
| 2025 | 217 | 191 | **26** | 88% |
| 2026 | 16 | 16 | **0** | 100% |
| **Total** | **918** | **816** | **102** | **89%** |

## Sample Missing Dates

### 2021 (1 date)
- 2021-11-01

### 2022 (25 dates) - Sample
- 2022-10-18 through 2022-11-05 (many early season dates)
- Full list requires detailed query

### Processing Estimates

#### For 102 Missing Dates

**Phase 4 Processing** (Sequential Steps):
1. TDZA + PSZA (parallel): ~25-30 seconds
2. PDC: ~15-20 seconds (if exists)
3. PCF: ~15-20 seconds
4. MLFS: ~15-20 seconds (if exists)

**Total per date**: ~70-90 seconds
**Total for 102 dates**: 119-153 minutes = **~2-2.5 hours**

## Recommended Execution Plan

### Option A: Process All at Once
```bash
# Process all 102 dates in one batch
./bin/backfill/run_year_phase4.sh \
  --start-date 2021-11-01 \
  --end-date 2026-01-16
```

**Pros**: Simplest approach
**Cons**: Long single run, no incremental validation
**Time**: ~2.5 hours

### Option B: Process by Year (Recommended)
```bash
# 2021 gap (1 date - ~1.5 min)
./bin/backfill/run_year_phase4.sh --year 2021

# 2022 gaps (25 dates - ~30 min)
./bin/backfill/run_year_phase4.sh --year 2022

# 2023 gaps (26 dates - ~35 min)
./bin/backfill/run_year_phase4.sh --year 2023

# 2024 gaps (24 dates - ~30 min)
./bin/backfill/run_year_phase4.sh --year 2024

# 2025 gaps (26 dates - ~35 min)
./bin/backfill/run_year_phase4.sh --year 2025
```

**Pros**: Incremental validation, easier to monitor
**Cons**: Requires manual year-by-year execution
**Time**: ~2.5 hours total, spread over 5 runs

### Option C: Test Then Batch
```bash
# 1. Test on 2021 (1 date - validate everything works)
./bin/backfill/run_year_phase4.sh --year 2021

# 2. If successful, batch the rest
./bin/backfill/run_year_phase4.sh \
  --start-date 2022-01-01 \
  --end-date 2025-12-31
```

**Pros**: Quick validation, then automated
**Cons**: Less granular monitoring
**Time**: ~2.5 hours total

## Important Notes

### Table Name Mapping
The actual Phase 4 table names differ from some documentation:
- ✅ `team_defense_zone_analysis` (not `team_defensive_zone_analytics`)
- ✅ `player_shot_zone_analysis` (not `player_shot_zone_analytics`)
- ✅ `player_composite_factors`
- ❓ `player_defensive_context` - May not exist or different name
- ❓ `ml_feature_store` - May not exist or different name

### Verification Needed
Before large-scale execution:
1. Verify which Phase 4 processors actually exist
2. Test orchestration script on 1 date (2021-11-01)
3. Check if PDC and MLFS tables exist
4. Update scripts if table names differ

### Missing Phase 4 Tables Investigation
Query to list all precompute tables:
```bash
bq ls nba-props-platform:nba_precompute
```

Current known tables:
- `team_defense_zone_analysis`
- `player_shot_zone_analysis`
- `player_composite_factors`
- `player_daily_cache`
- `daily_game_context`
- `daily_opponent_defense_zones`

## Cost Estimates

**BigQuery Processing**:
- 102 dates × 5 processors = 510 table queries
- Estimated: ~0.5 GB scanned per query
- Total: ~255 GB scanned
- Cost: ~$1.28 (at $5/TB)

**Cloud Run Execution** (if using Cloud Run):
- 102 dates × 90 seconds = 9,180 seconds = 2.55 hours
- At 2 vCPU, 2 GB: ~$0.15/hour
- Cost: ~$0.40

**Total Estimated Cost**: ~$1.70 (very low)

## Next Actions

1. ✅ Identify missing dates (completed - 102 dates)
2. ⏳ Investigate PDC and MLFS table existence
3. ⏳ Test backfill on 2021-11-01 (1 date)
4. ⏳ Execute year-by-year Phase 4 backfill
5. ⏳ Validate completion
6. ⏳ Generate final coverage report

## Full Missing Dates Query

To get the complete list of 102 missing dates:

```sql
SELECT
  p3.game_date,
  EXTRACT(YEAR FROM p3.game_date) as year,
  COUNT(DISTINCT p3.player_lookup) as players_in_game
FROM `nba-props-platform.nba_analytics.player_game_summary` p3
LEFT JOIN `nba-props-platform.nba_precompute.team_defense_zone_analysis` p4
  ON p3.game_date = p4.analysis_date
WHERE p3.game_date >= '2021-11-01'
  AND p3.game_date < '2026-01-17'
  AND p4.analysis_date IS NULL
GROUP BY p3.game_date
ORDER BY p3.game_date;
```

## Phase 3 Gap Analysis (Future Work)

Current Phase 3 coverage is 918 dates. To determine if more Phase 3 dates need processing:
1. Need to identify actual NBA game schedule (no schedule table found)
2. Can infer from boxscore_traditional or other raw tables
3. Likely most "missing" dates are off-days (no games)

**Current focus**: Fill the 102 Phase 4 gaps first, then investigate Phase 3 needs.
