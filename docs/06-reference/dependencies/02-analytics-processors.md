# Phase 3: Analytics Processors - Dependency Checks

**File:** `docs/dependency-checks/02-analytics-processors.md`
**Created:** 2025-11-21
**Last Updated:** 2025-11-25
**Purpose:** Dependency checking specs for 5 Phase 3 analytics processors
**Status:** Current - All 5 processors in production

📖 **Parent Document**: [Dependency Checking System Overview](./00-overview.md)

---

## Table of Contents

1. [Phase 3 Overview](#phase-3-overview)
2. [Dependency Check Pattern](#dependency-check-pattern)
3. [All 5 Processors](#all-5-processors)
4. [Dependency Verification Queries](#dependency-verification-queries)
5. [Failure Scenarios](#failure-scenarios)

---

## Phase 3 Overview

### Purpose

Phase 3 processors aggregate Phase 2 raw data into analytics features for downstream phases.

### Key Characteristics

- **5 Processors** (player, team offense/defense, upcoming contexts)
- **Dependencies**: 2-6 Phase 2 tables each
- **Pattern**: Point-in-time (hash-based) - see `00-overview.md`
- **Tracking**: 3 fields per dependency (hash, last_updated, rows_found)
- **Output**: `nba_analytics.*` tables

### Data Flow

```
Phase 2 (Raw)
    ↓ hash-based dependency check
Phase 3 (Analytics) - THIS PHASE
    ├─ Check: Phase 2 data_hash changed?
    ├─ Query: Multiple Phase 2 sources
    └─ Write: Analytics table with source metadata
    ↓
Phase 4 (Precompute)
Phase 5 (Predictions)
```

---

## Dependency Check Pattern

### Point-in-Time Hash Check (Pattern 1)

Phase 3 uses **Pattern 1** from `00-overview.md` - hash-based checking:

```python
def check_phase2_dependency(self, game_id: str, source_table: str) -> bool:
    """
    Check if Phase 2 source has new data for this game.

    Returns True if reprocessing needed (source hash changed).
    """
    # Get existing Phase 3 record
    existing = self.query(f"""
        SELECT source_{prefix}_hash, source_{prefix}_last_updated
        FROM `nba_analytics.{self.table_name}`
        WHERE game_id = '{game_id}'
    """)

    # Get current Phase 2 hash
    phase2 = self.query(f"""
        SELECT data_hash, processed_at
        FROM `nba_raw.{source_table}`
        WHERE game_id = '{game_id}'
    """)

    if not phase2:
        return False  # No source data

    # Compare hashes
    if not existing or existing['source_{prefix}_hash'] != phase2['data_hash']:
        return True  # Reprocess - source changed

    return False  # Skip - unchanged
```

**Why This Pattern**: Phase 3 needs same-game data from Phase 2 (not historical ranges).

---

## All 5 Processors

### 1. Player Game Summary

**File**: `player_game_summary/player_game_summary_processor.py`
**Table**: `nba_analytics.player_game_summary`
**Dependencies**: 6 Phase 2 sources (stats, shot zones, props)

**Tracked Sources**:
- `nbac_gamebook_player_stats` (primary boxscore)
- `bdl_player_boxscores` (fallback boxscore)
- `bigdataball_play_by_play` (preferred shot zones)
- `nbac_play_by_play` (backup shot zones)
- `odds_api_player_points_props` (primary props)
- `bettingpros_player_points_props` (backup props)

### 2. Team Offense Summary

**File**: `team_offense_game_summary/team_offense_game_summary_processor.py`
**Table**: `nba_analytics.team_offense_game_summary`
**Dependencies**: 2 Phase 2 sources

**Tracked Sources**:
- `nbac_team_boxscore` (team stats)
- `nbac_play_by_play` OR `bigdataball_play_by_play` (shot zones)

### 3. Team Defense Summary

**File**: `team_defense_game_summary/team_defense_game_summary_processor.py`
**Table**: `nba_analytics.team_defense_game_summary`
**Dependencies**: 3 Phase 2 sources

**Tracked Sources**:
- `nbac_team_boxscore` (team stats)
- `nbac_gamebook_player_stats` (opponent player stats)
- `bdl_player_boxscores` (fallback opponent stats)

### 4. Upcoming Player Game Context

**File**: `upcoming_player_game_context/upcoming_player_game_context_processor.py`
**Table**: `nba_analytics.upcoming_player_game_context`
**Dependencies**: 4 Phase 2 sources

**Tracked Sources**:
- `nbac_schedule` (game schedule)
- `nbac_injury_report` (injury status)
- `odds_api_player_points_props` (betting lines)
- `nbac_roster` OR `basketball_ref_roster` (roster data)

### 5. Upcoming Team Game Context

**File**: `upcoming_team_game_context/upcoming_team_game_context_processor.py`
**Table**: `nba_analytics.upcoming_team_game_context`
**Dependencies**: 3 Phase 2 sources

**Tracked Sources**:
- `nbac_schedule` (game schedule)
- `odds_game_lines` (spread/total lines)
- `nbac_injury_report` (team injury status)

---

## Dependency Verification Queries

### Check Phase 2 → Phase 3 Dependency Status

```sql
-- Verify Phase 2 sources exist for Phase 3 processing
SELECT
  -- Game identification
  g.game_id,
  g.game_date,

  -- Phase 2 source availability
  (SELECT COUNT(*) FROM `nba_raw.nbac_gamebook_player_stats`
   WHERE game_id = g.game_id) as gamebook_players,
  (SELECT COUNT(*) FROM `nba_raw.nbac_team_boxscore`
   WHERE game_id = g.game_id) as team_boxscores,
  (SELECT COUNT(*) FROM `nba_raw.nbac_play_by_play`
   WHERE game_id = g.game_id) as pbp_events,

  -- Phase 3 output status
  (SELECT COUNT(*) FROM `nba_analytics.player_game_summary`
   WHERE game_id = g.game_id) as phase3_player_rows,
  (SELECT COUNT(*) FROM `nba_analytics.team_offense_game_summary`
   WHERE game_id = g.game_id) as phase3_team_offense,
  (SELECT COUNT(*) FROM `nba_analytics.team_defense_game_summary`
   WHERE game_id = g.game_id) as phase3_team_defense

FROM `nba_raw.nbac_schedule` g
WHERE g.game_date = CURRENT_DATE() - 1
ORDER BY g.game_id;

-- Expected: 25-30 players per team, 2 team summaries per game
```

### Check Hash Staleness

```sql
-- Find Phase 3 records where Phase 2 source has newer hash
WITH phase2_hashes AS (
  SELECT
    game_id,
    data_hash as current_hash,
    processed_at as current_timestamp
  FROM `nba_raw.nbac_gamebook_player_stats`
  WHERE game_date >= CURRENT_DATE() - 7
),
phase3_hashes AS (
  SELECT
    game_id,
    source_nbac_hash as stored_hash,
    source_nbac_last_updated as stored_timestamp
  FROM `nba_analytics.player_game_summary`
  WHERE game_date >= CURRENT_DATE() - 7
)
SELECT
  p2.game_id,
  p2.current_hash as phase2_hash,
  p3.stored_hash as phase3_hash,
  (p2.current_hash != p3.stored_hash) as needs_reprocess,
  TIMESTAMP_DIFF(p2.current_timestamp, p3.stored_timestamp, HOUR) as hours_stale
FROM phase2_hashes p2
LEFT JOIN phase3_hashes p3 USING (game_id)
WHERE p2.current_hash != p3.stored_hash OR p3.stored_hash IS NULL
ORDER BY hours_stale DESC;

-- Expected: Empty result (all hashes match) or only recent games (<6h stale)
```

---

## Failure Scenarios

### Scenario 1: Phase 2 Source Missing

**Error**: `No data found in nba_raw.nbac_gamebook_player_stats for game {game_id}`

**Dependency Issue**: Phase 2 processor didn't run or failed

**Verification**:
```sql
SELECT COUNT(*) FROM `nba_raw.nbac_gamebook_player_stats` WHERE game_id = '{game_id}';
-- Expected: >0, Actual: 0
```

**Resolution**: Run Phase 2 processor for this game_id

### Scenario 2: Hash Changed But No Reprocessing

**Error**: Phase 3 record exists but hash doesn't match Phase 2

**Dependency Issue**: Phase 2 updated but Phase 3 didn't detect change

**Verification**: Use "Check Hash Staleness" query above

**Resolution**: Trigger Phase 3 processor manually for affected game_id

---

**Previous**: [Phase 2 Dependency Checks](./01-raw-processors.md)
**Next**: [Phase 4 Dependency Checks](./03-precompute-processors.md)

**Last Updated**: 2025-11-21
**Version**: 1.1
