# Session 59: Clean Backfill Plan - 2021-22 Season First 4 Weeks

**Date:** 2025-12-06
**Objective:** Delete all 2021-22 Phase 3 & 4 data and re-run first 4 weeks with registry_failures tracking
**Date Range:** October 19, 2021 - November 15, 2021

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Pre-Flight Checks](#pre-flight-checks)
3. [Phase 1: Data Cleanup](#phase-1-data-cleanup)
4. [Phase 2: Phase 3 Analytics Backfill](#phase-2-phase-3-analytics-backfill)
5. [Phase 3: Phase 4 Precompute Backfill](#phase-3-phase-4-precompute-backfill)
6. [Phase 4: Registry Failures Resolution](#phase-4-registry-failures-resolution)
7. [Validation Scripts](#validation-scripts)
8. [Rollback Plan](#rollback-plan)

---

## Executive Summary

### Why Are We Doing This?

1. **Registry failures tracking** - Code was added but backfills ran before it existed
2. **Clean validation** - Verify the full lifecycle works end-to-end
3. **Performance optimizations** - Session 58 added 60s timeouts and notification suppression
4. **Focused scope** - 4 weeks is manageable for validation

### Scope

| Metric | Value |
|--------|-------|
| Date range | 2021-10-19 to 2021-11-15 |
| Calendar days | 28 |
| Estimated game days | ~25 |
| Estimated games | ~120 |
| Estimated player-game records | ~3,000 |

### Expected Duration

| Phase | Estimated Time |
|-------|---------------|
| Cleanup | 5-10 minutes |
| Phase 3 (PGS) | 30-60 minutes |
| Phase 4 (PSZA, PDC, TDZA parallel) | 30-45 minutes |
| Phase 4 (PCF) | 15-20 minutes |
| Phase 4 (MLFS) | 15-20 minutes |
| **Total** | **~2-3 hours** |

---

## Pre-Flight Checks

Before starting, verify the following:

### 1. Check Phase 2 Raw Data Exists

```bash
# Verify raw data exists for our date range
bq query --use_legacy_sql=false "
SELECT
  'nbac_gamebook_player_stats' as source,
  COUNT(*) as records,
  COUNT(DISTINCT game_date) as dates,
  COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'bdl_player_boxscores', COUNT(*), COUNT(DISTINCT game_date), COUNT(DISTINCT game_id)
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'game_schedule', COUNT(*), COUNT(DISTINCT game_date), COUNT(DISTINCT game_id)
FROM \`nba-props-platform.nba_raw.game_schedule\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
"
```

**Expected:**
- nbac_gamebook_player_stats: ~3,000+ records, ~25 dates, ~120 games
- bdl_player_boxscores: similar coverage
- game_schedule: ~120 games

### 2. Check Player Registry Coverage

```bash
# Verify registry has 2021-22 season data
bq query --use_legacy_sql=false "
SELECT
  season,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT team_abbr) as teams
FROM \`nba-props-platform.nba_reference.nba_players_registry\`
WHERE season = '2021-22'
GROUP BY season
"
```

**Expected:** ~500+ players, 30 teams

### 3. Check Aliases Exist

```bash
# Verify aliases are loaded
bq query --use_legacy_sql=false "
SELECT COUNT(*) as total_aliases
FROM \`nba-props-platform.nba_reference.player_aliases\`
"
```

**Expected:** 700+ aliases (717 resolved from unresolved_player_names)

### 4. Verify No Active Backfills Running

```bash
# Check for running processes
ps aux | grep -E "(backfill|processor)" | grep -v grep
```

**Expected:** No active backfill processes

---

## Phase 1: Data Cleanup

### 1.1 Document Current State (Before Delete)

```bash
# Save current record counts for reference
bq query --use_legacy_sql=false --format=csv "
SELECT
  'player_game_summary' as table_name,
  COUNT(*) as records,
  '2021-22' as season
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
UNION ALL
SELECT 'upcoming_player_game_context', COUNT(*), '2021-22'
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
UNION ALL
SELECT 'player_daily_cache', COUNT(*), '2021-22'
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= '2021-10-01' AND cache_date < '2022-07-01'
UNION ALL
SELECT 'player_shot_zone_analysis', COUNT(*), '2021-22'
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date >= '2021-10-01' AND analysis_date < '2022-07-01'
UNION ALL
SELECT 'player_composite_factors', COUNT(*), '2021-22'
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
UNION ALL
SELECT 'team_defense_zone_analysis', COUNT(*), '2021-22'
FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date >= '2021-10-01' AND analysis_date < '2022-07-01'
UNION ALL
SELECT 'ml_feature_store_v2', COUNT(*), '2021-22'
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
UNION ALL
SELECT 'precompute_failures', COUNT(*), 'all'
FROM \`nba-props-platform.nba_processing.precompute_failures\`
UNION ALL
SELECT 'registry_failures', COUNT(*), 'all'
FROM \`nba-props-platform.nba_processing.registry_failures\`
" > /tmp/pre_delete_counts.csv

cat /tmp/pre_delete_counts.csv
```

### 1.2 Delete Phase 3 Analytics Data (2021-22 Season)

```bash
# Delete player_game_summary
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
"

# Delete upcoming_player_game_context
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
"
```

### 1.3 Delete Phase 4 Precompute Data (2021-22 Season)

```bash
# Delete player_daily_cache
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= '2021-10-01' AND cache_date < '2022-07-01'
"

# Delete player_shot_zone_analysis
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date >= '2021-10-01' AND analysis_date < '2022-07-01'
"

# Delete player_composite_factors
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
"

# Delete team_defense_zone_analysis
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date >= '2021-10-01' AND analysis_date < '2022-07-01'
"

# Delete ml_feature_store_v2
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
"
```

### 1.4 Clear Processing Tables

```bash
# Clear all precompute_failures (fresh start)
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_processing.precompute_failures\`
WHERE TRUE
"

# registry_failures is already empty, but clear just in case
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE TRUE
"
```

### 1.5 Verify Cleanup Complete

```bash
# Verify all tables are empty for 2021-22
bq query --use_legacy_sql=false "
SELECT 'player_game_summary' as t, COUNT(*) as c FROM \`nba-props-platform.nba_analytics.player_game_summary\` WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
UNION ALL SELECT 'upcoming_player_game_context', COUNT(*) FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\` WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
UNION ALL SELECT 'player_daily_cache', COUNT(*) FROM \`nba-props-platform.nba_precompute.player_daily_cache\` WHERE cache_date >= '2021-10-01' AND cache_date < '2022-07-01'
UNION ALL SELECT 'player_shot_zone_analysis', COUNT(*) FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\` WHERE analysis_date >= '2021-10-01' AND analysis_date < '2022-07-01'
UNION ALL SELECT 'player_composite_factors', COUNT(*) FROM \`nba-props-platform.nba_precompute.player_composite_factors\` WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
UNION ALL SELECT 'team_defense_zone_analysis', COUNT(*) FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\` WHERE analysis_date >= '2021-10-01' AND analysis_date < '2022-07-01'
UNION ALL SELECT 'ml_feature_store_v2', COUNT(*) FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\` WHERE game_date >= '2021-10-01' AND game_date < '2022-07-01'
UNION ALL SELECT 'precompute_failures', COUNT(*) FROM \`nba-props-platform.nba_processing.precompute_failures\`
UNION ALL SELECT 'registry_failures', COUNT(*) FROM \`nba-props-platform.nba_processing.registry_failures\`
"
```

**Expected:** All counts = 0

---

## Phase 2: Phase 3 Analytics Backfill

### 2.1 Run Player Game Summary Processor

```bash
cd /home/naji/code/nba-stats-scraper

# Activate virtual environment
source .venv/bin/activate

# Set environment variables
export GCP_PROJECT_ID=nba-props-platform
export ENABLE_PLAYER_PARALLELIZATION=true
export PGS_WORKERS=10

# Run backfill for first 4 weeks
python -c "
from datetime import date, timedelta
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor

processor = PlayerGameSummaryProcessor()

start_date = date(2021, 10, 19)
end_date = date(2021, 11, 15)

current = start_date
while current <= end_date:
    print(f'\\n========== Processing {current} ==========')
    result = processor.run({
        'start_date': current,
        'end_date': current,
        'backfill_mode': True,
        'skip_downstream_trigger': True
    })
    print(f'Result: {\"SUCCESS\" if result else \"FAILED\"}')
    current += timedelta(days=1)

print('\\n========== BACKFILL COMPLETE ==========')
"
```

### 2.2 Validate Phase 3 Results

```bash
# Check player_game_summary coverage
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_date) as dates,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_lookup) as players,
  SUM(CASE WHEN universal_player_id IS NULL THEN 1 ELSE 0 END) as missing_uid
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
"
```

**Expected:**
- ~3,000 records
- ~25 dates
- ~120 games
- ~400+ players
- missing_uid should be low (players without registry match)

### 2.3 Check Registry Failures

```bash
# Check if registry_failures were tracked
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_failures,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT game_date) as dates_affected
FROM \`nba-props-platform.nba_processing.registry_failures\`
"
```

---

## Phase 3: Phase 4 Precompute Backfill

### Dependency Order

```
┌─────────────────────────────────────────────────────────┐
│                    DEPENDENCY GRAPH                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Level 1 (No dependencies - run in parallel):           │
│  ├── PlayerShotZoneAnalysisProcessor (PSZA)             │
│  ├── PlayerDailyCacheProcessor (PDC)                    │
│  └── TeamDefenseZoneAnalysisProcessor (TDZA)            │
│                                                          │
│  Level 2 (Depends on Level 1):                          │
│  └── PlayerCompositeFactorsProcessor (PCF)              │
│       ├── requires: PSZA                                │
│       └── requires: PDC                                 │
│                                                          │
│  Level 3 (Depends on Level 2):                          │
│  └── MLFeatureStoreProcessor (MLFS)                     │
│       ├── requires: PCF                                 │
│       ├── requires: PSZA                                │
│       ├── requires: PDC                                 │
│       └── requires: TDZA                                │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 3.1 Run Level 1 Processors (Parallel)

```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate
export GCP_PROJECT_ID=nba-props-platform

# Create backfill script for Level 1
cat > /tmp/run_level1_backfill.py << 'EOF'
import sys
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import processors
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor
from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import TeamDefenseZoneAnalysisProcessor

def run_processor_for_date(processor_class, target_date):
    """Run a single processor for a single date."""
    try:
        processor = processor_class()
        result = processor.run({
            'analysis_date': target_date,
            'cache_date': target_date,  # PDC uses cache_date
            'backfill_mode': True,
            'skip_downstream_trigger': True
        })
        return (processor_class.__name__, target_date, result)
    except Exception as e:
        return (processor_class.__name__, target_date, False, str(e))

def main():
    start_date = date(2021, 10, 19)
    end_date = date(2021, 11, 15)

    processors = [
        PlayerShotZoneAnalysisProcessor,
        PlayerDailyCacheProcessor,
        TeamDefenseZoneAnalysisProcessor
    ]

    # Generate all (processor, date) combinations
    tasks = []
    current = start_date
    while current <= end_date:
        for proc_class in processors:
            tasks.append((proc_class, current))
        current += timedelta(days=1)

    print(f"Running {len(tasks)} tasks ({len(processors)} processors x {(end_date - start_date).days + 1} dates)")

    success_count = 0
    fail_count = 0

    # Run with limited parallelism to avoid overwhelming BQ
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_processor_for_date, proc, dt): (proc.__name__, dt)
            for proc, dt in tasks
        }

        for future in as_completed(futures):
            result = future.result()
            proc_name, dt = futures[future]
            if len(result) == 3 and result[2]:
                success_count += 1
                print(f"✅ {proc_name} {dt}")
            else:
                fail_count += 1
                error = result[3] if len(result) > 3 else "Unknown error"
                print(f"❌ {proc_name} {dt}: {error}")

    print(f"\n========== LEVEL 1 COMPLETE ==========")
    print(f"Success: {success_count}, Failed: {fail_count}")

if __name__ == "__main__":
    main()
EOF

python /tmp/run_level1_backfill.py
```

### 3.2 Validate Level 1 Results

```bash
bq query --use_legacy_sql=false "
SELECT 'PSZA' as processor, COUNT(*) as records, COUNT(DISTINCT analysis_date) as dates
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'PDC', COUNT(*), COUNT(DISTINCT cache_date)
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'TDZA', COUNT(*), COUNT(DISTINCT analysis_date)
FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date BETWEEN '2021-10-19' AND '2021-11-15'
"
```

### 3.3 Run Level 2 Processor (PCF)

```bash
cat > /tmp/run_level2_backfill.py << 'EOF'
from datetime import date, timedelta
from data_processors.precompute.player_composite_factors.player_composite_factors_processor import PlayerCompositeFactorsProcessor

start_date = date(2021, 10, 19)
end_date = date(2021, 11, 15)

processor = PlayerCompositeFactorsProcessor()
current = start_date

while current <= end_date:
    print(f"Processing PCF for {current}...")
    result = processor.run({
        'game_date': current,
        'backfill_mode': True,
        'skip_downstream_trigger': True
    })
    status = "✅" if result else "❌"
    print(f"{status} PCF {current}")
    current += timedelta(days=1)

print("\n========== LEVEL 2 COMPLETE ==========")
EOF

python /tmp/run_level2_backfill.py
```

### 3.4 Run Level 3 Processor (MLFS)

```bash
cat > /tmp/run_level3_backfill.py << 'EOF'
from datetime import date, timedelta
from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor

start_date = date(2021, 10, 19)
end_date = date(2021, 11, 15)

processor = MLFeatureStoreProcessor()
current = start_date

while current <= end_date:
    print(f"Processing MLFS for {current}...")
    result = processor.run({
        'game_date': current,
        'backfill_mode': True,
        'skip_downstream_trigger': True
    })
    status = "✅" if result else "❌"
    print(f"{status} MLFS {current}")
    current += timedelta(days=1)

print("\n========== LEVEL 3 COMPLETE ==========")
EOF

python /tmp/run_level3_backfill.py
```

### 3.5 Final Phase 4 Validation

```bash
bq query --use_legacy_sql=false "
SELECT
  'PSZA' as processor,
  COUNT(*) as records,
  COUNT(DISTINCT analysis_date) as dates
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'PDC', COUNT(*), COUNT(DISTINCT cache_date)
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'TDZA', COUNT(*), COUNT(DISTINCT analysis_date)
FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'PCF', COUNT(*), COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'MLFS', COUNT(*), COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
"
```

---

## Phase 4: Registry Failures Resolution

After backfill completes, check for registry failures and resolve them.

### 4.1 Check Registry Failures Status

```bash
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN reprocessed_at IS NOT NULL THEN 'complete'
    WHEN resolved_at IS NOT NULL THEN 'ready'
    ELSE 'pending'
  END as status,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as total_records
FROM \`nba-props-platform.nba_processing.registry_failures\`
GROUP BY status
ORDER BY status
"
```

### 4.2 View Pending Players (if any)

```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  COUNT(*) as dates,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE resolved_at IS NULL
GROUP BY player_lookup
ORDER BY dates DESC
LIMIT 20
"
```

### 4.3 Run AI Resolution (if pending failures exist)

```bash
# Dry run first
python tools/player_registry/resolve_unresolved_batch.py --dry-run

# If looks good, run for real
python tools/player_registry/resolve_unresolved_batch.py
```

### 4.4 Reprocess Resolved Players

```bash
# Check what would be reprocessed
python tools/player_registry/reprocess_resolved.py --dry-run

# Run reprocessing
python tools/player_registry/reprocess_resolved.py
```

---

## Validation Scripts

### Complete Coverage Check

```bash
bq query --use_legacy_sql=false "
WITH expected_dates AS (
  SELECT DISTINCT game_date
  FROM \`nba-props-platform.nba_raw.game_schedule\`
  WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
),
pgs_dates AS (
  SELECT DISTINCT game_date FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
)
SELECT
  e.game_date,
  CASE WHEN p.game_date IS NOT NULL THEN 'YES' ELSE 'MISSING' END as pgs_covered
FROM expected_dates e
LEFT JOIN pgs_dates p ON e.game_date = p.game_date
WHERE p.game_date IS NULL
ORDER BY e.game_date
"
```

### Failure Summary

```bash
bq query --use_legacy_sql=false "
SELECT
  processor_name,
  failure_category,
  COUNT(*) as count,
  COUNT(DISTINCT entity_id) as unique_entities
FROM \`nba-props-platform.nba_processing.precompute_failures\`
WHERE analysis_date BETWEEN '2021-10-19' AND '2021-11-15'
GROUP BY processor_name, failure_category
ORDER BY processor_name, count DESC
"
```

### Registry Failures Lifecycle

```bash
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN reprocessed_at IS NOT NULL THEN 'COMPLETE'
    WHEN resolved_at IS NOT NULL THEN 'READY_TO_REPROCESS'
    ELSE 'PENDING_RESOLUTION'
  END as lifecycle_status,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as game_dates
FROM \`nba-props-platform.nba_processing.registry_failures\`
GROUP BY lifecycle_status
"
```

---

## Rollback Plan

If something goes wrong, the data can be recovered by:

1. **Phase 2 raw data is untouched** - We only delete Phase 3 & 4 derived data
2. **Re-run backfill** - Simply re-run the processors for any missing dates
3. **Registry/aliases untouched** - Player resolution data is preserved

### Emergency Stop

```bash
# Kill all running backfill processes
pkill -f "python.*processor"
pkill -f "python.*backfill"
```

---

## Checklist

- [ ] Pre-flight checks passed
- [ ] Pre-delete counts saved
- [ ] Phase 3 data deleted (player_game_summary, upcoming_player_game_context)
- [ ] Phase 4 data deleted (PDC, PSZA, PCF, TDZA, MLFS)
- [ ] Processing tables cleared (precompute_failures, registry_failures)
- [ ] Cleanup verified (all counts = 0)
- [ ] Phase 3 backfill complete (PGS)
- [ ] Phase 3 validation passed
- [ ] Phase 4 Level 1 complete (PSZA, PDC, TDZA)
- [ ] Phase 4 Level 2 complete (PCF)
- [ ] Phase 4 Level 3 complete (MLFS)
- [ ] Registry failures checked
- [ ] AI resolution run (if needed)
- [ ] Reprocessing complete (if needed)
- [ ] Final validation passed

---

## Related Documentation

- Registry Failures: `docs/02-operations/runbooks/observability/registry-failures.md`
- Backfill Runbook: `docs/02-operations/runbooks/backfill/README.md`
- Session 58 Optimizations: `docs/09-handoff/2025-12-06-SESSION58-BACKFILL-OPTIMIZATION.md`

---

**Document Created:** 2025-12-06
**Status:** Ready for execution
