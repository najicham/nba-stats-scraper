# Phase 2→3 Mapping: Upcoming Player Game Context

**File:** `docs/data-flow/06-phase2-to-phase3-upcoming-player-game-context.md`
**Created:** 2025-11-15
**Last Updated:** 2025-11-15
**Purpose:** Data mapping from Phase 2 raw tables to Phase 3 pre-game player context analytics
**Audience:** Engineers implementing Phase 3 processors and debugging pre-game context generation
**Status:** ⚠️ Reference - Implementation complete, deployment blocked

---

## 🚧 Current Deployment Status

**Implementation:** ✅ **COMPLETE**
- Phase 2 Processors: Multiple scrapers required (see dependencies below)
- Phase 3 Processor: `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` (1198 lines, 89 tests)
- Analytics Table: `nba_analytics.upcoming_player_game_context` (created, 64 fields)

**Blocker:** ❌ **2 critical Phase 2 raw tables do NOT exist**
- `nba_raw.odds_api_player_points_props` - MISSING (DRIVER table - identifies which players to process)
- `nba_raw.nbac_schedule` - MISSING (CRITICAL - game timing and context)
- Without these 2 tables, processor cannot run

**To Unblock:**
1. Deploy Phase 2 processor for Odds API player props scraper
2. Deploy Phase 2 processor for NBA.com schedule scraper
3. Run backfill to populate both tables with historical data
4. Verify `nba_raw.bdl_player_boxscores` has sufficient historical depth (30+ days)
5. Then Phase 3 processor can be scheduled

**Additional Missing Sources (Optional - Degrade Gracefully):**
- `nba_raw.odds_api_game_lines` - Game spreads/totals (processor handles missing)
- `nba_static.travel_distances` - Travel context enrichment (future enhancement)

**See:** `docs/processors/` for Phase 2 deployment procedures

---

## 📊 Executive Summary

This Phase 3 processor creates comprehensive pre-game context for every player with a prop bet available today. It's the most complex Phase 3 processor, pulling from **8 Phase 2 raw sources** to calculate fatigue metrics, performance trends, injury status, prop line movement, and game situation factors.

**Processor:** `upcoming_player_game_context_processor.py`
**Output Table:** `nba_analytics.upcoming_player_game_context`
**Processing Strategy:** MERGE_UPDATE (run multiple times per day)
**Update Frequency:** Morning, midday, pre-game (3-4x per day)
**Driver Table:** `nba_raw.odds_api_player_points_props` (identifies which players to process)

**Key Complexity:**
- **8 Phase 2 sources** with complex fallback logic
- Driver pattern: Props table determines which players to process
- Historical lookback windows (5 games, 10 games, 7 days, 14 days, 30 days)
- Multi-source fallback (BDL → NBA.com for boxscores, Odds API → ESPN for schedule)
- Handles rookies, limited history, missing data gracefully
- Quality tier assignment based on sample size

**Data Quality:** Variable - depends on data availability
- **High:** 10+ games history, all optional sources available
- **Medium:** 5-9 games history, some optional sources missing
- **Low:** <5 games history, minimal data

---

## 🗂️ Raw Sources (Phase 2)

### CRITICAL Sources (Must Exist)

#### Source 1: Odds API Player Points Props (DRIVER - CRITICAL)

**Table:** `nba_raw.odds_api_player_points_props`
**Status:** ❌ **Not yet created (BLOCKER)**
**Update Frequency:** Live (multiple snapshots before game)
**Dependency:** CRITICAL - This is the DRIVER table that identifies which players to process

**Purpose:**
- Determines which players have prop bets today (drives entire pipeline)
- Provides points line (opening and current)
- Tracks line movement across snapshots

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| player_lookup | STRING | Normalized player key |
| game_id | STRING | System format: "20250115_LAL_PHI" |
| game_date | DATE | Game date (partition key) |
| points_line | NUMERIC | Points prop line (24.5, 25.5, etc.) |
| bookmaker | STRING | Bookmaker name ("draftkings", "fanduel") |
| snapshot_timestamp | TIMESTAMP | When this snapshot was captured |
| over_price_american | INT64 | Over odds (American format) |
| under_price_american | INT64 | Under odds (American format) |

**Processing Logic:**
- Extract **latest snapshot** (before game time) → `current_points_line`
- Extract **earliest snapshot** → `opening_points_line`
- Calculate: `line_movement = current_points_line - opening_points_line`

**Why CRITICAL:**
Without this table, processor doesn't know which players to process. The entire workflow is driven by "players with prop bets available today."

---

#### Source 2: NBA.com Schedule (CRITICAL)

**Table:** `nba_raw.nbac_schedule`
**Status:** ❌ **Not yet created (BLOCKER)**
**Update Frequency:** Daily (schedule published weeks in advance)
**Dependency:** CRITICAL - Needed for game timing, teams, and back-to-back detection

**Purpose:**
- Game timing and venue context
- Home/away team identification
- Back-to-back detection (query team's recent schedule)
- Primetime game flagging

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| game_id | STRING | System format: "20250115_LAL_PHI" |
| game_date | DATE | Game date |
| game_date_est | TIMESTAMP | Game start time (Eastern) |
| home_team_tricode | STRING | Home team abbreviation |
| away_team_tricode | STRING | Away team abbreviation |
| is_primetime | BOOLEAN | Primetime game flag (future use) |

**Processing Logic:**
- Join on `game_id` to get teams and timing
- Determine player's team vs opponent team
- Query 5 days before/after to detect back-to-backs:
  ```sql
  -- Back-to-back detection
  SELECT game_date
  FROM nba_raw.nbac_schedule
  WHERE (home_team_tricode = @team OR away_team_tricode = @team)
    AND game_date BETWEEN @game_date - 5 AND @game_date + 5
  ORDER BY game_date
  ```
- Calculate: `days_rest = current_game_date - last_game_date`
- Set: `back_to_back = TRUE` if `days_rest = 0`

**Why CRITICAL:**
Cannot identify player's team or opponent without schedule. Cannot calculate fatigue metrics (back-to-backs, rest days).

---

#### Source 3: BDL Player Boxscores (PRIMARY - Historical Performance)

**Table:** `nba_raw.bdl_player_boxscores`
**Status:** ✅ **EXISTS**
**Update Frequency:** ~1 hour after game completion
**Dependency:** CRITICAL - Primary source for historical stats
**Fallback:** `nba_raw.nbac_player_boxscores` if BDL missing recent games

**Purpose:**
- Last 30 days of player performance stats
- Calculate recent averages (last 5, last 10 games)
- Determine games played in windows (last 7 days, last 14 days)
- Calculate minutes load and rest patterns

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| player_lookup | STRING | Join key |
| game_date | DATE | Filter: last 30 days before context date |
| points | INT64 | Points scored |
| minutes | STRING | Minutes played ("35:42" format) |
| assists | INT64 | Assists |
| rebounds | INT64 | Total rebounds |
| team_abbr | STRING | Current team (fallback if roster missing) |

**Processing Logic:**
- Window: `WHERE game_date < @target_date AND game_date >= @target_date - 30`
- Calculations:
  - `points_avg_last_5` = AVG(points) for last 5 games
  - `points_avg_last_10` = AVG(points) for last 10 games
  - `games_in_last_7_days` = COUNT(*) WHERE game_date >= target - 7
  - `minutes_in_last_7_days` = SUM(minutes_decimal) for last 7 days
  - `days_rest` = date_diff(target_date, MAX(game_date))

**Data Quality:**
- ✅ Excellent: 99%+ coverage of NBA games
- ⚠️ Minutes as STRING: Requires parsing "MM:SS" → decimal
- ⚠️ Combined rebounds only (no offensive/defensive split)

---

### OPTIONAL Sources (Enhance Quality if Available)

#### Source 4: Odds API Game Lines (OPTIONAL)

**Table:** `nba_raw.odds_api_game_lines`
**Status:** ❌ **Not yet created**
**Update Frequency:** Live (pre-game)
**Impact if Missing:** Set `game_spread`, `game_total` to NULL (processor handles gracefully)

**Purpose:**
- Game spread (expected competitiveness)
- Game total (expected pace)
- Line movement tracking

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| game_id | STRING | Join key |
| market_key | STRING | "spreads" or "totals" |
| outcome_point | NUMERIC | Spread value or total value |
| outcome_name | STRING | Team name or "Over"/"Under" |
| bookmaker_key | STRING | Bookmaker identifier |
| snapshot_timestamp | TIMESTAMP | When captured |

**Processing Logic:**
- Use **consensus median** across bookmakers (require ≥3 bookmakers)
- Extract opening and closing spreads/totals
- Calculate: `spread_movement`, `total_movement`

---

#### Source 5: ESPN Team Rosters (OPTIONAL)

**Table:** `nba_raw.espn_team_rosters`
**Status:** ✅ **EXISTS**
**Impact if Missing:** Use last known team from boxscores

**Purpose:**
- Verify player's current team
- Get jersey number and position

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| player_lookup | STRING | Join key |
| team_abbr | STRING | Current team |
| roster_date | DATE | When roster snapshot was captured |
| jersey_number | STRING | Player's jersey number |
| position | STRING | Player's position |

**Processing Logic:**
- Query most recent roster before target date
- Fallback to recent boxscores if not in roster (handles new call-ups, trades)

---

#### Source 6: NBA.com Injury Report (OPTIONAL)

**Table:** `nba_raw.nbac_injury_report`
**Status:** ✅ **EXISTS**
**Impact if Missing:** Set injury fields to NULL

**Purpose:**
- Player's injury status
- Injury reason/description
- Teammate injury context

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| player_lookup | STRING | Join key |
| game_date | DATE | Join key |
| injury_status | STRING | "Out", "Questionable", "Doubtful", "Probable" |
| reason | STRING | Injury description |

**Processing Logic:**
- Normalize status to lowercase
- Count questionable/probable teammates
- Supplement with BDL injuries if available

---

#### Source 7: BDL Injuries (OPTIONAL - Backup)

**Table:** `nba_raw.bdl_injuries`
**Status:** ✅ **EXISTS**
**Impact if Missing:** Rely only on NBA.com injury reports

**Purpose:**
- Backup injury data if NBA.com unavailable

---

#### Source 8: NBA Players Registry (OPTIONAL)

**Table:** `nba_reference.nba_players_registry`
**Status:** ✅ **EXISTS**
**Impact if Missing:** Leave `universal_player_id` as NULL

**Purpose:**
- Universal player ID resolution

---

## 🔄 Data Flow

### Processing Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Identify Target Players (DRIVER)                        │
│ Query: nba_raw.odds_api_player_points_props                    │
│ WHERE game_date = @target_date                                 │
│ Result: List of players with prop bets today                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Get Game Context                                        │
│ Query: nba_raw.nbac_schedule                                   │
│ JOIN on game_id                                                │
│ Result: Teams, timing, home/away                               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Historical Performance (30-day lookback)                │
│ Query: nba_raw.bdl_player_boxscores                            │
│ WHERE game_date BETWEEN target_date - 30 AND target_date       │
│ Calculate: Averages, games played, minutes load, rest days     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Prop Line Movement                                      │
│ Extract opening line (earliest snapshot)                        │
│ Extract current line (latest snapshot)                          │
│ Calculate: line_movement = current - opening                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: Optional Enhancements                                   │
│ - Game lines (spread/total) if available                        │
│ - Injury status if available                                    │
│ - Universal player ID if in registry                            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: Calculate Quality Tier                                  │
│ High: 10+ games, all sources available                          │
│ Medium: 5-9 games, some sources missing                         │
│ Low: <5 games, minimal data                                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 Field Mappings Summary

### Output Schema: 72 Fields

**Core Identifiers (5 fields):**
- `player_lookup`, `game_id`, `game_date`, `team_abbr`, `opponent_team_abbr`

**Prop Lines (8 fields):**
- `current_points_line`, `opening_points_line`, `line_movement`
- `current_points_line_source`, `opening_points_line_source`
- Plus line metadata

**Fatigue Metrics (7 fields):**
- `days_rest`, `back_to_back`, `games_in_last_7_days`, `games_in_last_14_days`
- `minutes_in_last_7_days`, `minutes_in_last_14_days`, `avg_minutes_per_game_last_7`

**Performance Trends (3 fields):**
- `points_avg_last_5`, `points_avg_last_10`, `games_in_last_30_days`

**Game Context (6 fields):**
- `game_spread`, `game_total`, `home_game`
- `spread_movement`, `total_movement`, `game_competitiveness` (calculated)

**Injury Context (3 fields):**
- `player_status`, `injury_report`, `questionable_teammates`

**Data Quality (4 fields):**
- `data_quality_tier`, `primary_source_used`, `processed_with_issues`, `processed_at`

**Deferred Fields (Future - Currently NULL):**
- `next_game_days_rest`, `opponent_days_rest`, `next_opponent_win_pct`

---

## ⚠️ Known Issues & Edge Cases

### Issue 1: Missing Critical Tables
**Problem:** Processor cannot run without props and schedule tables
**Solution:** Must deploy Phase 2 scrapers first (see "To Unblock" above)

### Issue 2: Rookie Players
**Problem:** Player has prop bet but no NBA history
**Solution:** Processor handles gracefully - sets historical averages to NULL, quality_tier = 'low'

### Issue 3: Player Name Variations
**Problem:** Different formats across sources ("LeBron James", "L. James")
**Solution:** All sources use `player_lookup` (normalized) as join key

### Issue 4: Limited Sample Size
**Problem:** Player has <5 games of history
**Solution:** Calculate with available games, set `data_quality_tier = 'low'`

### Issue 5: Multiple Prop Snapshots
**Problem:** Props table has 5+ snapshots per player per game
**Solution:** Use `ORDER BY snapshot_timestamp DESC LIMIT 1` for current, `ASC LIMIT 1` for opening

---

## ✅ Validation Rules

### Critical Validations (Reject Record)
- ✅ `player_lookup` IS NOT NULL
- ✅ `game_id` IS NOT NULL
- ✅ `team_abbr` IS NOT NULL
- ✅ `current_points_line` BETWEEN 5.0 AND 50.0
- ✅ `days_rest` >= 0

### Warning Validations (Flag but Process)
- ⚠️ `games_in_last_30_days` < 5 → Set `data_quality_tier = 'low'`
- ⚠️ `game_spread` IS NULL → Set `processed_with_issues = TRUE`
- ⚠️ ABS(`line_movement`) > 3.0 → Log warning
- ⚠️ Bookmaker count < 3 → Set `processed_with_issues = TRUE`

---

## 📈 Success Criteria

**Processing Success:**
- ✅ At least 90% of players with props have context record created
- ✅ No more than 5% of records have `processed_with_issues = TRUE`
- ✅ Processing completes within 60 seconds for typical day (100-150 players)

**Data Quality Success:**
- ✅ 100% of records have `team_abbr` populated
- ✅ 95% of records have `game_spread` and `game_total` populated (when game lines available)
- ✅ 80% of records have `data_quality_tier = 'high'` (10+ games history)
- ✅ 100% of records have `points_avg_last_5` if player has 5+ games

---

## 🔗 Related Documentation

**Processor Implementation:**
- Code: `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Phase 2 Dependencies:**
- Schema: Run `bq show --schema nba_raw.odds_api_player_points_props` (when created)
- Schema: Run `bq show --schema nba_raw.nbac_schedule` (when created)

**Monitoring:**
- `docs/monitoring/` - Data quality metrics for Phase 3

---

**Document Version:** 1.0
**Status:** Implementation complete - BLOCKED on 2 critical Phase 2 tables
**Next Steps:** Deploy Phase 2 processors for Odds API props and NBA.com schedule
