# Session 46: SQL Hash Approach Feasibility Test

**Date:** 2025-12-05
**Status:** Ready for feasibility test
**Previous Session:** 45 (Data Hash Backfill Continuation)

## Current Status: First Month COMPLETE

All 5 Phase 3 Analytics tables now have 100% data_hash coverage for the first month (2021-10-19 to 2021-11-19):

| Table                        | Total | With Hash | Coverage |
|------------------------------|-------|-----------|----------|
| player_game_summary          | 5,182 | 5,182     | 100%     |
| team_defense_game_summary    | 1,802 | 1,802     | 100%     |
| team_offense_game_summary    | 1,802 | 1,802     | 100%     |
| upcoming_player_game_context | 8,349 | 8,349     | 100%     |
| upcoming_team_game_context   | 476   | 476       | 100%     |

## Next Task: SQL Hash Feasibility Test

The original plan was to complete the first 30 days, evaluate, and then decide how to proceed with the remaining ~3 years of historical data.

### Option C: SQL-Based Hash Calculation (RECOMMENDED TO TEST)

Instead of running processor-based backfills for 25-40 days, we can potentially compute data_hash directly in BigQuery SQL - reducing time to hours.

### Why SQL Could Work

The Python hash is computed as:
```python
hash_data = {field: record.get(field) for field in HASH_FIELDS}  # 34 fields
sorted_data = json.dumps(hash_data, sort_keys=True, default=str)
return hashlib.sha256(sorted_data.encode()).hexdigest()[:16]
```

**Key insight:** `json.dumps(sort_keys=True)` produces alphabetically sorted keys.

We can manually construct the exact same JSON string in BigQuery with fields in alphabetical order, then compute SHA256.

### HASH_FIELDS for team_offense_game_summary (34 fields)

From `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`:

```python
HASH_FIELDS = [
    # Core identifiers (6)
    'game_id', 'nba_game_id', 'game_date', 'team_abbr',
    'opponent_team_abbr', 'season_year',

    # Basic offensive stats (11)
    'points_scored', 'fg_attempts', 'fg_makes', 'three_pt_attempts',
    'three_pt_makes', 'ft_attempts', 'ft_makes', 'rebounds',
    'assists', 'turnovers', 'personal_fouls',

    # Team shot zone performance (6)
    'team_paint_attempts', 'team_paint_makes', 'team_mid_range_attempts',
    'team_mid_range_makes', 'points_in_paint_scored',
    'second_chance_points_scored',

    # Advanced offensive metrics (4)
    'offensive_rating', 'pace', 'possessions', 'ts_pct',

    # Game context (4)
    'home_game', 'win_flag', 'margin_of_victory', 'overtime_periods',

    # Team situation context (2)
    'players_inactive', 'starters_inactive',

    # Referee integration (1)
    'referee_crew_id'
]
```

### Risk Analysis

| Risk                        | Likelihood | Impact | Mitigation                        |
|-----------------------------|------------|--------|-----------------------------------|
| Key order mismatch          | Low        | High   | Careful alphabetical ordering     |
| Type coercion differences   | Medium     | High   | Test with actual data             |
| Null handling differences   | Medium     | High   | Match Python's None → "null"      |
| Float precision differences | Medium     | Medium | Use CAST(x AS STRING)             |

### Feasibility Test Plan (30-60 min)

1. **Pick ONE table** with existing processor-computed hashes (team_offense_game_summary)
2. **Write SQL** that computes hash for 10 rows using alphabetically sorted JSON construction
3. **Compare** SQL-computed vs processor-computed hashes
4. **If 100% match** → proceed with SQL backfill for all tables
5. **If any mismatch** → analyze why, fix, or fall back to processor-based backfill

### If SQL Works

- Generate SQL UPDATE scripts for all 5 Analytics tables
- Run historical backfill in ~1-2 hours total (vs 25-40 days)
- Verify 100% match on sample dates

### If SQL Doesn't Work

- Fall back to processor-based (Option A)
- Accept longer runtime but guaranteed correctness
- Run backfills in background over 25-40 days

## Immediate Next Steps

1. **Create test SQL query** for team_offense_game_summary that:
   - Constructs JSON with 34 fields in alphabetical order
   - Computes SHA256 and takes first 16 chars
   - Compares to existing data_hash values

2. **Run on 10 rows** from the first month where data_hash exists

3. **Verify 100% match** before proceeding with full backfill

## SQL Template to Test

```sql
-- Alphabetically ordered JSON construction for team_offense_game_summary
WITH computed_hashes AS (
  SELECT
    game_id,
    team_abbr,
    data_hash as existing_hash,
    SUBSTR(TO_HEX(SHA256(
      CONCAT(
        '{"assists": ', COALESCE(CAST(assists AS STRING), 'null'),
        ', "fg_attempts": ', COALESCE(CAST(fg_attempts AS STRING), 'null'),
        ', "fg_makes": ', COALESCE(CAST(fg_makes AS STRING), 'null'),
        ', "ft_attempts": ', COALESCE(CAST(ft_attempts AS STRING), 'null'),
        ', "ft_makes": ', COALESCE(CAST(ft_makes AS STRING), 'null'),
        ', "game_date": "', CAST(game_date AS STRING), '"',
        ', "game_id": "', game_id, '"',
        ', "home_game": ', CASE WHEN home_game THEN 'true' ELSE 'false' END,
        ', "margin_of_victory": ', COALESCE(CAST(margin_of_victory AS STRING), 'null'),
        ', "nba_game_id": "', COALESCE(nba_game_id, ''), '"',
        ', "offensive_rating": ', COALESCE(CAST(offensive_rating AS STRING), 'null'),
        ', "opponent_team_abbr": "', COALESCE(opponent_team_abbr, ''), '"',
        ', "overtime_periods": ', COALESCE(CAST(overtime_periods AS STRING), 'null'),
        ', "pace": ', COALESCE(CAST(pace AS STRING), 'null'),
        ', "personal_fouls": ', COALESCE(CAST(personal_fouls AS STRING), 'null'),
        ', "players_inactive": ', COALESCE(CAST(players_inactive AS STRING), 'null'),
        ', "points_in_paint_scored": ', COALESCE(CAST(points_in_paint_scored AS STRING), 'null'),
        ', "points_scored": ', COALESCE(CAST(points_scored AS STRING), 'null'),
        ', "possessions": ', COALESCE(CAST(possessions AS STRING), 'null'),
        ', "rebounds": ', COALESCE(CAST(rebounds AS STRING), 'null'),
        ', "referee_crew_id": ', COALESCE(CONCAT('"', referee_crew_id, '"'), 'null'),
        ', "season_year": "', COALESCE(season_year, ''), '"',
        ', "second_chance_points_scored": ', COALESCE(CAST(second_chance_points_scored AS STRING), 'null'),
        ', "starters_inactive": ', COALESCE(CAST(starters_inactive AS STRING), 'null'),
        ', "team_abbr": "', team_abbr, '"',
        ', "team_mid_range_attempts": ', COALESCE(CAST(team_mid_range_attempts AS STRING), 'null'),
        ', "team_mid_range_makes": ', COALESCE(CAST(team_mid_range_makes AS STRING), 'null'),
        ', "team_paint_attempts": ', COALESCE(CAST(team_paint_attempts AS STRING), 'null'),
        ', "team_paint_makes": ', COALESCE(CAST(team_paint_makes AS STRING), 'null'),
        ', "three_pt_attempts": ', COALESCE(CAST(three_pt_attempts AS STRING), 'null'),
        ', "three_pt_makes": ', COALESCE(CAST(three_pt_makes AS STRING), 'null'),
        ', "ts_pct": ', COALESCE(CAST(ts_pct AS STRING), 'null'),
        ', "turnovers": ', COALESCE(CAST(turnovers AS STRING), 'null'),
        ', "win_flag": ', CASE WHEN win_flag THEN 'true' ELSE 'false' END,
        '}'
      )
    )), 1, 16) as computed_hash
  FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
  WHERE data_hash IS NOT NULL
    AND game_date BETWEEN '2021-10-19' AND '2021-11-19'
  LIMIT 10
)
SELECT
  game_id,
  team_abbr,
  existing_hash,
  computed_hash,
  existing_hash = computed_hash as match
FROM computed_hashes;
```

**NOTE:** This SQL template needs testing and refinement. Python's JSON serialization may differ in:
- Float precision (Python might show 123.0 vs SQL showing 123)
- Date formatting
- Boolean representation
- Null handling for strings vs numbers

## Files to Reference

- `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py:83-109` - HASH_FIELDS definition
- `data_processors/analytics/analytics_base.py` - `_calculate_data_hash` method

## Verification Query

```sql
-- Check first month coverage (should all be 100%)
SELECT
  'player_game_summary' as tbl, COUNT(*) as total, COUNTIF(data_hash IS NOT NULL) as with_hash
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-19'
UNION ALL
SELECT 'team_defense_game_summary', COUNT(*), COUNTIF(data_hash IS NOT NULL)
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-19'
UNION ALL
SELECT 'team_offense_game_summary', COUNT(*), COUNTIF(data_hash IS NOT NULL)
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-19'
UNION ALL
SELECT 'upcoming_player_game_context', COUNT(*), COUNTIF(data_hash IS NOT NULL)
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-19'
UNION ALL
SELECT 'upcoming_team_game_context', COUNT(*), COUNTIF(data_hash IS NOT NULL)
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-19'
ORDER BY tbl;
```
