# Session 48: Data Cleanup and Optimization Handoff

**Date:** 2025-12-05
**Previous Session:** 47 (Data Hash Backfill Monitoring)
**Status:** Research complete, action required

## Executive Summary

Session 48 researched the current state of all data across Phase 3 (Analytics) and Phase 4 (Precompute) tables. The goal is to:
1. Keep only first ~6 weeks of 2021 season data (2021-10-19 to 2021-11-30)
2. Delete all data beyond that cutoff
3. Validate the system works correctly on this subset
4. Investigate and optimize slow processors before running 4 full seasons

## Critical Finding: MLFeatureStoreProcessor Performance

**This is the #1 blocker for running 4 seasons of data.**

| Metric | Value | Impact |
|--------|-------|--------|
| Average duration | **33 minutes/day** | 4 seasons (~1200 days) = **660+ hours** |
| Max duration | **2+ hours** | Single bad day can take forever |
| Runs recorded | 33 | Limited sample size |

The `ml_feature_store` table was **NOT FOUND** in BigQuery (`us-west2`), despite 33 processor runs being logged. This needs investigation.

---

## Current Data State

### Phase 3 Analytics (nba_analytics) - Needs Cleanup

| Table | Min Date | Max Date | Rows | Data to Delete |
|-------|----------|----------|------|----------------|
| player_game_summary | 2021-10-19 | **2025-06-22** | 92,534 | > 2021-11-30 |
| team_offense_game_summary | 2021-10-19 | **2024-12-31** | 34,638 | > 2021-11-30 |
| team_defense_game_summary | 2021-10-19 | **2024-12-31** | 34,638 | > 2021-11-30 |
| upcoming_player_game_context | 2021-10-19 | **2024-11-25** | 15,503 | > 2021-11-30 |
| upcoming_team_game_context | 2021-10-19 | 2022-01-02 | 1,080 | > 2021-11-30 |

### Phase 4 Precompute (nba_precompute) - Partial Cleanup Needed

| Table | Date Column | Min Date | Max Date | Rows | Status |
|-------|-------------|----------|----------|------|--------|
| player_composite_factors | game_date | 2021-11-10 | **2025-12-03** | 4,763 | Needs cleanup |
| player_daily_cache | cache_date | 2021-11-05 | 2021-11-30 | 3,342 | OK |
| ml_feature_store | game_date | - | - | - | **TABLE NOT FOUND** |
| player_shot_zone_analysis | ? | ? | ? | ? | Unknown date column |
| team_defense_zone_analysis | ? | ? | ? | ? | Unknown date column |

---

## Processor Performance Analysis (from processor_run_history)

| Processor | Avg (sec) | Max (sec) | Runs | Priority |
|-----------|-----------|-----------|------|----------|
| **MLFeatureStoreProcessor** | **1989** | **7231** | 33 | **P0 - CRITICAL** |
| PlayerShotZoneAnalysisProcessor | 316 | 879 | 64 | P1 - Review |
| PlayerDailyCacheProcessor | 286 | 1041 | 27 | P1 - Review |
| PlayerCompositeFactorsProcessor | 121 | 1038 | 35 | P2 - Monitor |
| UpcomingTeamGameContextProcessor | 96 | 2119 | 167 | P2 - Monitor |
| TeamDefenseZoneAnalysisProcessor | 57 | 1066 | 117 | P2 - Monitor |
| TeamOffenseGameSummaryProcessor | 82 | 414 | 6 | OK |
| TeamDefenseGameSummaryProcessor | 28 | 67 | 7 | OK |
| PlayerGameSummaryProcessor | 24 | 1055 | 741 | OK (usually) |

---

## TODO List for Next Session

### Priority 0: Investigate MLFeatureStoreProcessor

- [ ] **Find why ml_feature_store table doesn't exist in BigQuery**
  ```bash
  # Check all datasets
  bq ls nba-props-platform:

  # Search for ml_feature
  bq ls nba-props-platform:nba_precompute | grep -i ml
  bq ls nba-props-platform:nba_analytics | grep -i ml
  ```

- [ ] **Read the MLFeatureStoreProcessor code**
  - Location: `data_processors/precompute/ml_feature_store/`
  - Understand what it's computing
  - Identify bottlenecks (likely BigQuery queries or data volume)

- [ ] **Check if table is in different location/dataset**
  ```bash
  bq query --use_legacy_sql=false "
  SELECT table_schema, table_name
  FROM \`nba-props-platform\`.INFORMATION_SCHEMA.TABLES
  WHERE table_name LIKE '%ml%' OR table_name LIKE '%feature%'
  "
  ```

### Priority 1: Execute Data Cleanup

- [ ] **Delete Phase 3 Analytics data > 2021-11-30**
  ```sql
  -- Example for one table (CAREFUL - this deletes data!)
  DELETE FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date > '2021-11-30';

  -- Repeat for all 5 tables
  ```

- [ ] **Delete Phase 4 Precompute data > 2021-11-30**
  - First identify date columns for player_shot_zone_analysis and team_defense_zone_analysis
  ```bash
  bq show --schema nba-props-platform:nba_precompute.player_shot_zone_analysis
  bq show --schema nba-props-platform:nba_precompute.team_defense_zone_analysis
  ```

- [ ] **Verify row counts after cleanup**

### Priority 2: Research Other Slow Processors

- [ ] **PlayerShotZoneAnalysisProcessor** - avg 5 min, max 15 min
  - Location: `data_processors/precompute/player_shot_zone_analysis/`

- [ ] **PlayerDailyCacheProcessor** - avg 5 min, max 17 min
  - Location: `data_processors/precompute/player_daily_cache/`

### Priority 3: Validate First Month Data

- [ ] After cleanup, verify data integrity for 2021-10-19 to 2021-11-30
- [ ] Run validation queries to ensure data_hash coverage
- [ ] Test end-to-end processing for a single date

---

## Questions to Answer

1. **Where is the ml_feature_store data?** The processor ran 33 times but the table doesn't exist in `nba_precompute`.

2. **Why is MLFeatureStoreProcessor so slow?** 33 minutes average per day is not sustainable for 4 seasons.

3. **What optimizations have already been done?** Check git history and handoff docs for parallelization work (Sessions 31-37).

4. **Should we skip MLFeatureStore for now?** If it's not critical for predictions, we could defer it.

---

## Relevant Files to Read

### Processor Code
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

### Previous Optimization Work
- `docs/09-handoff/2025-12-04-SESSION28-PERFORMANCE-OPTIMIZATION-RESEARCH.md`
- `docs/09-handoff/2025-12-04-SESSION29-PERFORMANCE-OPTIMIZATION-HANDOFF.md`
- `docs/09-handoff/2025-12-04-SESSION31-PARALLELIZE-ALL-PROCESSORS.md`
- `docs/09-handoff/2025-12-05-SESSION37-PRIORITY3-PARALLELIZATION.md`

### Schema Files
- `schemas/bigquery/precompute/` - Check table schemas

---

## Quick Commands

### Check Processor Run History
```bash
bq query --use_legacy_sql=false --format=prettyjson "
SELECT
  processor_name,
  COUNT(*) as runs,
  ROUND(AVG(duration_seconds), 1) as avg_sec,
  ROUND(MAX(duration_seconds), 1) as max_sec,
  MIN(data_date) as min_date,
  MAX(data_date) as max_date
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE status = 'success' AND duration_seconds IS NOT NULL
GROUP BY processor_name
ORDER BY avg_sec DESC
"
```

### List All Tables in Precompute Dataset
```bash
bq ls --format=prettyjson nba-props-platform:nba_precompute
```

### Check Table Row Counts (Analytics)
```bash
for table in player_game_summary team_offense_game_summary team_defense_game_summary upcoming_player_game_context upcoming_team_game_context; do
  echo "=== $table ==="
  bq query --use_legacy_sql=false "
  SELECT
    COUNTIF(game_date <= '2021-11-30') as keep_rows,
    COUNTIF(game_date > '2021-11-30') as delete_rows,
    COUNT(*) as total
  FROM \`nba-props-platform.nba_analytics.$table\`
  WHERE game_date >= '2020-01-01'
  "
done
```

---

## Summary

**Target state:** Only data from 2021-10-19 to 2021-11-30 across all tables.

**Critical blocker:** MLFeatureStoreProcessor averages 33 min/day - investigate and optimize before running 4 seasons.

**Mystery:** ml_feature_store table doesn't exist despite 33 logged processor runs.
