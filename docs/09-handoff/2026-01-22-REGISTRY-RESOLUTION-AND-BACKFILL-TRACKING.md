# Registry Resolution and Backfill Impact Tracking

**Date:** 2026-01-22
**Session Focus:** Player registry backfill tracking and impact analysis

## Executive Summary

This document tracks player name resolutions and their backfill requirements. When a player name is resolved, historical games with that player need reprocessing to ensure complete analytics data.

## Resolution Status (as of 2026-01-22)

### Summary by Resolution Type

| Type | Total Records | Unique Names |
|------|---------------|--------------|
| `alias_created` | 1,637 | 47 |
| `timing_auto` | 698 | 599 |
| `data_error` | 484 | 5 |
| `new_player_detected` | 22 | 1 |

### Pending vs Resolved

| Status | Count |
|--------|-------|
| Resolved | 2,833 |
| Pending | 7 (all one player - alexantetokounmpo, now resolved) |
| Snoozed | 2 |

## Backfill Impact Analysis

### Top 20 Players by Affected Games

| Player | Affected Games | Date Range | Reprocessed | Pending |
|--------|----------------|------------|-------------|---------|
| alexantetokounmpo | 47 | 2025-10-22 → 2026-01-21 | 144 | 155 |
| nikoladurisic | 41 | 2025-10-22 → 2026-01-09 | 0 | 251 |
| airiousbailey | 33 | 2025-10-22 → 2026-01-08 | 0 | 209 |
| kasparasjakuionis | 33 | 2025-10-22 → 2026-01-06 | 0 | 212 |
| hansenyang | 33 | 2025-10-22 → 2026-01-03 | 0 | 232 |
| nolantraor | 32 | 2025-10-22 → 2026-01-09 | 0 | 196 |
| jahmaimashack | 30 | 2025-11-18 → 2026-01-11 | 0 | 174 |
| chrismaon | 29 | 2025-10-21 → 2026-01-06 | 0 | 174 |
| hugogonzlez | 29 | 2025-10-22 → 2026-01-05 | 0 | 192 |
| danielbatcho | 24 | 2025-10-22 → 2025-12-14 | 0 | 57 |

### Backfill by Age Bucket

| Age Bucket | Players | Games | Priority |
|------------|---------|-------|----------|
| Last 7 days | 1 | 3 | HIGH |
| Last 30 days | 42 | 70 | HIGH |
| Last 90 days | 230 | 425 | MEDIUM |
| Older than 90 days | 556 | 47 | LOW |

**Total Reprocessing Backlog:** 628 players, 533+ unique games

## Tracking Infrastructure

### Key Tables

1. **`nba_reference.unresolved_player_names`** - Master list of unresolved names
   - `status`: pending, resolved, snoozed
   - `resolution_type`: alias_created, new_player_detected, data_error, timing_auto
   - `resolved_to_name`: canonical player name for matches

2. **`nba_processing.registry_failures`** - Game-level tracking
   - `player_lookup`: the unresolved name
   - `game_id`, `game_date`: affected game
   - `resolved_at`: when the name was resolved
   - `reprocessed_at`: when the game was reprocessed

3. **`nba_reference.ai_resolution_cache`** - AI decision cache
   - Prevents redundant API calls
   - Must be invalidated when registry changes (see alexantetokounmpo stale cache issue fixed today)

4. **`nba_reference.player_aliases`** - Alias mappings
   - `alias_lookup` → `nba_canonical_lookup`
   - Includes confidence scores and AI model used

## Monitoring Queries

### Check Reprocessing Backlog
```sql
SELECT
  CASE
    WHEN game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) THEN 'Last 7 days'
    WHEN game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) THEN 'Last 30 days'
    WHEN game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY) THEN 'Last 90 days'
    ELSE 'Older than 90 days'
  END as age_bucket,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT game_id) as games
FROM nba_processing.registry_failures
WHERE resolved_at IS NOT NULL AND reprocessed_at IS NULL
GROUP BY 1
ORDER BY 1;
```

### Check Resolution Progress
```sql
SELECT
  status,
  COUNT(*) as count
FROM nba_reference.unresolved_player_names
GROUP BY status;
```

### Check Stale Cache Entries
```sql
-- Find cache entries for names that are now in the registry
SELECT c.unresolved_lookup, c.resolution_type, c.created_at, r.player_lookup
FROM nba_reference.ai_resolution_cache c
JOIN nba_reference.nba_players_registry r
  ON c.unresolved_lookup = r.player_lookup
WHERE c.resolution_type = 'DATA_ERROR'
  AND r.season = '2025-26';
```

### Top Unresolved Names by Impact
```sql
SELECT
  player_lookup,
  COUNT(DISTINCT game_id) as affected_games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM nba_processing.registry_failures
WHERE resolved_at IS NULL
GROUP BY player_lookup
ORDER BY affected_games DESC
LIMIT 20;
```

## Reprocessing Commands

### Run Full Reprocessing
```bash
PYTHONPATH=. python tools/player_registry/resolve_unresolved_batch.py --reprocess-only
```

### Dry Run Resolution
```bash
PYTHONPATH=. python tools/player_registry/resolve_unresolved_batch.py --dry-run
```

### Resolve + Reprocess (Full Pipeline)
```bash
PYTHONPATH=. python tools/player_registry/resolve_unresolved_batch.py
```

## Issues Fixed This Session

### 1. Stale AI Cache Issue
**Problem:** `alexantetokounmpo` was cached as DATA_ERROR from Jan 10, but Alex Antetokounmpo was added to the registry on Jan 12.
**Fix:** Deleted stale cache entry, re-ran resolution which correctly matched.
**Prevention:** When adding new players to registry, check for stale cache entries.

### 2. Partition Filter Bug in Reprocessing
**Problem:** `process_single_game()` in `player_game_summary_processor.py` didn't include `game_date` partition filter.
**Fix:** Added `AND game_date = @game_date` to queries for:
- `bdl_player_boxscores` (line ~1530)
- `team_offense_game_summary` (line ~1602)

Added `game_date` parameter to query config.

## How to Handle Future Resolutions

When a player name is resolved:

1. **Check if alias was created** - Look in `player_aliases` table
2. **Check affected games** - Query `registry_failures` for that `player_lookup`
3. **Run reprocessing** - Use `--reprocess-only` flag
4. **Verify completion** - Check `reprocessed_at` is populated

### Reprocessing Priority Order
1. Games < 7 days old (impacts current predictions)
2. Games 7-30 days old (recent analytics)
3. Games 30-90 days old (historical completeness)
4. Games > 90 days old (batch backfill only)

## Scheduled Automation

Two scheduler jobs handle ongoing resolution:

| Job | Schedule | Purpose |
|-----|----------|---------|
| `registry-ai-resolution` | 4:30 AM ET | Batch AI resolution of pending names |
| `registry-health-check` | 5:00 AM ET | Daily registry health check |

**Note:** Reprocessing is NOT automated - it runs after resolution in the batch resolver script.

## Next Steps

1. Complete current reprocessing run (background task b73f574)
2. Run additional reprocessing cycles until backlog cleared
3. Monitor scheduled jobs for ongoing resolution
4. Consider automating reprocessing in Cloud Run
