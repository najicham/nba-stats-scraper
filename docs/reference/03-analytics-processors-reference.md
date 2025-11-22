# NBA Analytics Processors Reference

**Created:** 2025-11-21 17:25:00 PST
**Last Updated:** 2025-11-21 17:25:00 PST

Quick reference for Phase 3 analytics processors transforming raw NBA data into analytical datasets.

**Active Processors:** 5 operational + 1 in development

## Architecture

**Base Class:** `AnalyticsProcessorBase`

**Processing Pattern:**
1. Check dependencies (Phase 2 raw tables)
2. Extract from raw BigQuery tables
3. Validate extracted data
4. Calculate analytics metrics
5. Save to analytics tables (MERGE_UPDATE)
6. Track source metadata

**Key Features:**
- Dependency checking (freshness + completeness)
- Source hash tracking for smart reprocessing
- Batch NDJSON inserts (no streaming buffer)
- Multi-channel notifications (Email + Slack)
- Quality issue logging

## Player Game Summary

**Status:** ✅ Production Ready

**Purpose:** Player performance analytics with prop bet outcomes

```
Table: nba_analytics.player_game_summary
Partition: game_date
Clustering: universal_player_id, team_abbr, player_lookup
Strategy: MERGE_UPDATE
```

**Data Sources (6):**
- `nba_raw.nbac_gamebook_player_stats` (PRIMARY - critical)
- `nba_raw.bdl_player_boxscores` (FALLBACK - critical)
- `nba_raw.bigdataball_play_by_play` (shot zones - optional)
- `nba_raw.nbac_play_by_play` (shot zones backup - optional)
- `nba_raw.odds_api_player_points_props` (prop lines - optional)
- `nba_raw.bettingpros_player_points_props` (prop backup - optional)

**Key Fields:**
```
player_lookup, universal_player_id, game_id, game_date
points, assists, rebounds, minutes_played
points_line, over_under_result, margin
ts_pct, efg_pct, usage_rate
data_quality_tier, primary_source_used
```

**Features:**
- Universal player ID via RegistryReader (5-min cache)
- Bookmaker deduplication (DraftKings → FanDuel priority)
- NBA.com → BDL fallback logic
- Batch insert (no streaming buffer conflicts)

**Performance:**
- Single game day (154 players): ~15 seconds
- Full week: 3-5 minutes
- Registry coverage: 100% active players

**Processor:** `PlayerGameSummaryProcessor`
**File:** `data_processors/analytics/player_game_summary/`

## Team Offense Game Summary

**Status:** ✅ Production Ready

**Purpose:** Team offensive analytics and advanced metrics

```
Table: nba_analytics.team_offense_game_summary
Partition: game_date
Clustering: team_abbr, game_date
Strategy: MERGE_UPDATE
```

**Data Sources (2):**
- `nba_raw.nbac_team_boxscore` (PRIMARY - critical)
- `nba_raw.nbac_play_by_play` (shot zones - optional)

**Key Fields:**
```
game_id, game_date, team_abbr, opponent_team_abbr
points_scored, fg_attempts, fg_makes, three_pt_makes
offensive_rating, pace, possessions, ts_pct
home_game, win_flag (future)
```

**Advanced Metrics:**
- Effective FG%: `(FGM + 0.5 × 3PM) / FGA`
- True Shooting%: `Points / (2 × (FGA + 0.44 × FTA))`
- Possessions: `FGA + 0.44 × FTA + TO - ORB`
- Offensive Rating: `(Points × 100) / Possessions`

**Performance:**
- Single game day (30 teams): 5-10 seconds
- Weekly backfill: 1-2 minutes

**Processor:** `TeamOffenseGameSummaryProcessor`
**File:** `data_processors/analytics/team_offense_game_summary/`

## Team Defense Game Summary

**Status:** ✅ Production Ready

**Purpose:** Team defensive analytics by flipping opponent offense

```
Table: nba_analytics.team_defense_game_summary
Partition: game_date
Clustering: defending_team_abbr, game_date
Strategy: MERGE_UPDATE
```

**Data Sources (2):**
- `nba_analytics.team_offense_game_summary` (opponent stats - required)
- `nba_analytics.player_game_summary` (defensive actions - required)

**Key Fields:**
```
game_id, game_date, defending_team_abbr, opponent_team_abbr
points_allowed, opp_fg_attempts, opp_fg_makes
steals, blocks, defensive_rebounds, turnovers_forced
defensive_rating (lower is better)
```

**Logic:**
- Opponent's offense = Your defense
- Flip perspective: `opponent_team_abbr → defending_team_abbr`
- Add defensive actions: steals, blocks from player stats
- Defensive Rating: `Points Allowed × 100 / Possessions`

**Performance:**
- Single game day (30 teams): 5-10 seconds
- Weekly backfill: 1-2 minutes

**Processor:** `TeamDefenseGameSummaryProcessor`
**File:** `data_processors/analytics/team_defense_game_summary/`

## Upcoming Team Game Context

**Status:** ✅ Production Ready

**Purpose:** Pregame team context for betting analysis

```
Table: nba_analytics.upcoming_team_game_context
Partition: game_date
Clustering: team_abbr, game_date
Strategy: MERGE_UPDATE
```

**Data Sources (3):**
- `nba_raw.nbac_schedule` (games, results - critical)
- `nba_raw.odds_api_game_lines` (betting lines - optional)
- `nba_raw.nbac_injury_report` (player status - optional)

**Key Fields:**
```
team_abbr, game_id, game_date, opponent_team_abbr
game_spread, spread_movement, game_total, total_movement
team_days_rest, team_back_to_back, games_in_last_7_days
team_win_streak_entering, team_loss_streak_entering
starters_out_count, questionable_players_count
travel_miles, home_game
```

**Context Categories:**
- **Betting:** Spreads, totals, line movement
- **Fatigue:** Days rest, back-to-backs, game density
- **Personnel:** Injuries, questionable players
- **Momentum:** Win/loss streaks, recent margins
- **Travel:** Miles traveled (away games)

**Performance:**
- Single game day (30 team records): 15-20 seconds
- Weekly backfill: 2-3 minutes

**Processor:** `UpcomingTeamGameContextProcessor`
**File:** `data_processors/analytics/upcoming_team_game_context/`

## Upcoming Player Game Context

**Status:** 🚧 In Development

**Purpose:** Pregame player context for prop betting

```
Table: nba_analytics.upcoming_player_game_context
Partition: game_date
Clustering: universal_player_id, player_lookup
Strategy: MERGE_UPDATE
```

**Planned Sources:**
- Player registry (universal IDs)
- Recent performance (last 5/10/20 games)
- Matchup history vs opponent
- Prop line history
- Injury status

**Processor:** `UpcomingPlayerGameContextProcessor`
**File:** `data_processors/analytics/upcoming_player_game_context/`

## Game Referees (View)

**Status:** ✅ Production Ready (SQL View)

**Implementation:** SQL VIEW (not processor)

**Why View?** Raw data already complete, no calculations needed

**Main View:** `nba_raw.nbac_referee_game_pivot`

Pivots one-row-per-official to one-row-per-game:

```sql
SELECT
  game_id, game_date,
  chief_referee,        -- Position 1
  crew_referee_1,       -- Position 2
  crew_referee_2,       -- Position 3
  crew_referee_3        -- Position 4 (if present)
FROM nba_raw.nbac_referee_game_assignments
```

**Helper Views:**
- `nbac_referee_game_pivot_recent` - Last 30 days
- `nbac_chief_referee_summary` - Career statistics

**Usage:** JOIN to context processors for referee assignments

## Common Patterns

### Dependency Tracking

All processors define dependencies in `get_dependencies()`:

```python
def get_dependencies(self) -> dict:
    return {
        'nba_raw.source_table': {
            'field_prefix': 'source_name',
            'description': 'Human description',
            'date_field': 'game_date',
            'check_type': 'date_range',
            'expected_count_min': 200,
            'max_age_hours_warn': 6,
            'max_age_hours_fail': 24,
            'critical': True
        }
    }
```

### Source Metadata Tracking

Per dependency, 4 fields tracked:
- `{prefix}_last_updated` - Timestamp of last update
- `{prefix}_rows_found` - Actual row count
- `{prefix}_completeness_pct` - % of expected rows found
- `{prefix}_hash` - Data hash for smart reprocessing

### Smart Reprocessing

Phase 3 equivalent of Phase 2 smart idempotency:

```python
skip, reason = processor.should_skip_processing(game_date, game_id)
if skip:
    logger.info(f"Skipping: {reason}")
    return []
```

Compares Phase 2 source hashes to detect unchanged data.

### Backfill Discovery

Find historical games needing processing:

```python
candidates = processor.find_backfill_candidates(lookback_days=30)
for game in candidates:
    processor.run({'start_date': game['game_date'],
                   'end_date': game['game_date']})
```

## Running Analytics Processors

### Local Execution

```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  -c "
from data_processors.analytics.player_game_summary import PlayerGameSummaryProcessor
p = PlayerGameSummaryProcessor()
p.run({'start_date': '2024-11-20', 'end_date': '2024-11-20'})
"
```

### Cloud Run Service

```bash
# Trigger via Pub/Sub
gcloud pubsub topics publish analytics-player-game-summary \
  --message='{"start_date":"2024-11-20","end_date":"2024-11-20"}'
```

### Monitoring

```sql
-- Processing runs
SELECT
  processor_name,
  run_date,
  success,
  records_processed,
  duration_seconds
FROM nba_processing.analytics_processor_runs
WHERE run_date >= CURRENT_DATE() - 7
ORDER BY run_date DESC;

-- Quality issues
SELECT
  processor_name,
  issue_type,
  severity,
  identifier,
  created_at
FROM nba_processing.analytics_data_issues
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY created_at DESC;
```

## Processing Strategy

**MERGE_UPDATE (all analytics processors):**
1. Delete existing data for date range
2. Batch insert new calculated analytics
3. Avoids duplicates, allows reprocessing

**Advantages:**
- Can reprocess to add enrichments (shot zones, etc.)
- No streaming buffer conflicts (uses batch loads)
- Clean state per date range

## Files

**Base Classes:**
- `data_processors/analytics/analytics_base.py`

**Processors:**
- `data_processors/analytics/player_game_summary/`
- `data_processors/analytics/team_offense_game_summary/`
- `data_processors/analytics/team_defense_game_summary/`
- `data_processors/analytics/upcoming_team_game_context/`
- `data_processors/analytics/upcoming_player_game_context/`

**Schemas:**
- `schemas/bigquery/analytics/*.sql`

**Registry:**
- `shared/utils/player_registry/reader.py`

## See Also

- [Scrapers Reference](01-scrapers-reference.md)
- [Processors Reference](02-processors-reference.md)
- [Dependency Tracking Guide](../guides/dependency-tracking.md)
