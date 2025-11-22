# Phase 5: Predictions Coordinator - Dependency Checks
**Detailed Specification**
**Version**: 1.2
**Last Updated**: 2025-11-21
**Status**: Production

📖 **Parent Document**: [Dependency Checking System Overview](./00-overview.md)

---

## Table of Contents

1. [Phase 5 Overview](#phase-5-overview)
2. [Dependency Check Pattern](#dependency-check-pattern)
3. [Dependency Verification Queries](#dependency-verification-queries)
4. [Failure Scenarios](#failure-scenarios)

---

## Phase 5 Overview

### Purpose

Phase 5 coordinator loads players with games scheduled for a given date and publishes prediction requests to workers.

### Key Characteristics

- **Service**: Predictions Coordinator (Cloud Run)
- **Dependencies**: Phase 3 `upcoming_player_game_context` table
- **Pattern**: Direct query (no hash checking)
- **Flow**: Query players → Publish to Pub/Sub → Workers process
- **Output**: Prediction requests (not predictions themselves)

### Data Flow

```
Phase 3 (Analytics)
    ↓ direct query
Phase 5 (Coordinator) - THIS PHASE
    ├─ Query: upcoming_player_game_context
    ├─ Filter: min_minutes, injury status
    ├─ Publish: prediction-request messages
    └─ Track: completion progress
    ↓
Phase 5 Workers (Prediction Systems)
```

---

## Dependency Check Pattern

### Direct Query (No Hash Checking)

Phase 5 uses **direct table query** - no hash-based dependency checking:

```python
def load_players_for_date(self, game_date: date, min_minutes: int = 15) -> List[Dict]:
    """
    Query Phase 3 to get players with games scheduled.

    No hash checking - simply queries current state of Phase 3 table.
    """
    query = f"""
    SELECT
        player_lookup,
        game_id,
        game_date,
        projected_minutes,
        injury_status,
        player_points_line  -- from odds data
    FROM `nba_analytics.upcoming_player_game_context`
    WHERE game_date = '{game_date}'
      AND projected_minutes >= {min_minutes}
      AND injury_status NOT IN ('OUT', 'DOUBTFUL')
    ORDER BY projected_minutes DESC
    """

    results = self.bq_client.query(query).result()
    return [dict(row) for row in results]
```

**Why No Hash Checking**: Phase 5 coordinator queries Phase 3 once per day (forward-looking data). No need to track changes - just uses current state.

**Implicit Dependency**: Phase 3 `upcoming_player_game_context` must exist for target game_date.

---

## Dependency Verification Queries

### Check Phase 3 Availability for Target Date

```sql
-- Verify Phase 3 upcoming_player_game_context exists for target date
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as total_players,
  COUNT(DISTINCT game_id) as total_games,
  COUNT(DISTINCT team_abbr) as teams_playing,
  AVG(projected_minutes) as avg_projected_minutes,
  COUNTIF(injury_status IN ('OUT', 'DOUBTFUL')) as injured_out,
  COUNTIF(player_points_line IS NOT NULL) as have_betting_lines
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;

-- Expected: 450+ players, 12-15 games, 28-30 teams, avg 25+ minutes
-- If COUNT = 0: Phase 3 hasn't run yet or no games scheduled
```

### Check Player Load Query Result

```sql
-- Simulate coordinator's player load query
SELECT
  player_lookup,
  game_id,
  projected_minutes,
  injury_status,
  player_points_line
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE()
  AND projected_minutes >= 15
  AND injury_status NOT IN ('OUT', 'DOUBTFUL')
ORDER BY projected_minutes DESC
LIMIT 20;

-- Expected: 350-450 players (after filtering)
-- If empty: Check Phase 3 processor or date filter
```

---

## Failure Scenarios

### Scenario 1: No Players Found for Target Date

**Error**: `No players found for {game_date}`

**Dependency Issue**: Phase 3 `upcoming_player_game_context` empty for target date

**Verification**:
```sql
SELECT COUNT(*) FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = '{game_date}';
-- Expected: >0, Actual: 0
```

**Resolution**:
- Verify Phase 3 processor ran for target date
- Check if games scheduled (offseason / no-game days expected)
- Verify Phase 2 `nbac_schedule` has data for target date

### Scenario 2: All Players Filtered Out

**Error**: Coordinator loads 0 players after filtering (min_minutes, injury_status)

**Dependency Issue**: Data exists but filters too aggressive

**Verification**:
```sql
SELECT
  COUNT(*) as total_players,
  COUNTIF(projected_minutes >= 15) as meets_minutes,
  COUNTIF(injury_status NOT IN ('OUT', 'DOUBTFUL')) as not_injured,
  COUNTIF(projected_minutes >= 15 AND injury_status NOT IN ('OUT', 'DOUBTFUL')) as final_count
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = '{game_date}';
```

**Resolution**: Adjust filter thresholds or investigate Phase 3 data quality

---

**Previous**: [Phase 4 Dependency Checks](./03-precompute-processors.md)
**Next**: [Phase 6 Dependency Checks](./05-publishing-api.md)

**Last Updated**: 2025-11-21
**Version**: 1.2
