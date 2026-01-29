# Game ID Formats - Cross-Table Reference Guide

## Overview

Different tables in the NBA data pipeline use different game ID formats. This document explains the formats and how to join tables correctly.

## Game ID Formats by Table

### NBA Reference / Schedule Tables
- **Table**: `nba_reference.nba_schedule`
- **Column**: `game_id`
- **Format**: `0022500665` (10-digit string with leading zeros)
- **Example**: `0022500665` = Game 665 of the 2025-26 season

### BigDataBall Play-by-Play
- **Table**: `nba_raw.bigdataball_play_by_play`
- **Columns**:
  - `game_id`: `20260127_MIL_PHI` (date + away @ home format) - **DO NOT USE FOR JOINS**
  - `bdb_game_id`: `22500665` (8-digit integer without leading zeros) - **USE THIS FOR JOINS**

### NBA.com Tables
- **Tables**: `nba_raw.nbac_*` tables
- **Column**: `game_id`
- **Format**: `0022500665` (10-digit string, matches schedule)

## Joining Tables

### Correct: Schedule to BDB PBP
```sql
-- Use bdb_game_id and strip leading zeros from schedule
SELECT s.*, p.*
FROM nba_reference.nba_schedule s
JOIN nba_raw.bigdataball_play_by_play p
  ON CAST(SUBSTR(s.game_id, 3) AS INT64) = p.bdb_game_id
  AND s.game_date = p.game_date
```

### Correct: Schedule to NBA.com
```sql
-- Direct join on game_id (same format)
SELECT s.*, n.*
FROM nba_reference.nba_schedule s
JOIN nba_raw.nbac_player_boxscore n
  ON s.game_id = n.game_id
  AND s.game_date = n.game_date
```

### WRONG: Do NOT join on BDB game_id column
```sql
-- THIS WILL RETURN 0 ROWS!
SELECT s.*, p.*
FROM nba_reference.nba_schedule s
JOIN nba_raw.bigdataball_play_by_play p
  ON s.game_id = p.game_id  -- WRONG! Different formats
```

## PBP Coverage Check Query

Use this query to check PBP coverage with correct join logic:

```sql
WITH scheduled AS (
  SELECT
    game_id,
    game_date,
    CAST(SUBSTR(game_id, 3) AS INT64) as game_id_int,
    home_team_tricode,
    away_team_tricode
  FROM nba_reference.nba_schedule
  WHERE game_date = '2026-01-27'
),
has_pbp AS (
  SELECT DISTINCT bdb_game_id, game_date
  FROM nba_raw.bigdataball_play_by_play
  WHERE game_date = '2026-01-27'
)
SELECT
  s.game_date,
  COUNT(*) as scheduled_games,
  COUNT(p.bdb_game_id) as games_with_pbp,
  COUNT(*) - COUNT(p.bdb_game_id) as missing_pbp
FROM scheduled s
LEFT JOIN has_pbp p
  ON s.game_id_int = p.bdb_game_id
  AND s.game_date = p.game_date
GROUP BY 1
```

## Data Source Tracking

As of Session 10 (2026-01-28), the `bigdataball_play_by_play` table has a `data_source` column:
- `'bigdataball'` - Primary source with full lineup data
- `'nbacom_fallback'` - Fallback source when BDB unavailable (no lineup data)
- `NULL` - Legacy data before migration

## Related Files

- Schema: `schemas/bigquery/raw/bigdataball_tables.sql`
- Processor: `data_processors/raw/bigdataball/bigdataball_pbp_processor.py`
- Schedule: `shared/utils/schedule/service.py`
