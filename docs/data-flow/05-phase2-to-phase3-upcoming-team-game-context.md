# Phase 2→3 Mapping: Upcoming Team Game Context

**File:** `docs/data-flow/05-phase2-to-phase3-upcoming-team-game-context.md`
**Created:** 2025-11-02
**Last Updated:** 2025-11-15
**Purpose:** Multi-source data mapping from Phase 2 raw tables to Phase 3 upcoming game context analytics
**Audience:** Engineers implementing Phase 3 processors, debugging multi-source integrations
**Status:** 🟡 Implementation In Progress - Source tracking incomplete

---

## 🚧 Current Deployment Status

**Implementation:** 🟡 **PARTIALLY COMPLETE**
- Phase 3 Processor: `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py` (1502 lines, 83 tests)
- Analytics Table: `nba_analytics.upcoming_team_game_context` (created, 40 fields)

**Incomplete Features:**
- ⬜ Source tracking fields not yet added to schema (marked "TO BE ADDED" in doc)
- ⬜ Dependency checking not yet implemented (marked in "Next Steps")
- ⬜ Multi-source completeness tracking not implemented

**Phase 2 Dependency Status:**
- ❓ `nba_raw.nbac_schedule` - Need to verify existence
- ❓ `nba_raw.odds_api_game_lines` - Need to verify existence
- ✅ `nba_raw.nbac_injury_report` - EXISTS (verified earlier)
- ❓ `nba_raw.espn_scoreboard` - Need to verify existence
- ❓ `nba_static.travel_distances` - Need to verify existence

**To Fully Unblock:**
1. Verify all 5 Phase 2 dependencies exist
2. Add source tracking fields to analytics table schema
3. Implement dependency checking in processor
4. Implement `track_source_usage()` method
5. Test multi-source fallback logic

**See:** `docs/processors/` for deployment procedures

---

## 📋 Executive Summary

This document maps how Phase 2 (Raw) processors populate tables that feed into the Phase 3 (Analytics) `upcoming_team_game_context` processor. It provides complete lineage from GCS files → Phase 2 tables → Phase 3 analytics.

**Processor:** `upcoming_team_game_context_processor.py`
**Output Table:** `nba_analytics.upcoming_team_game_context`
**Processing Strategy:** MERGE_UPDATE
**Version:** 1.0

**Unique Complexity:**
- **5 Phase 2 source tables** (most complex processor in system)
- Multi-source fallback (schedule + ESPN backup)
- Team name mapping challenges (Odds API uses full names)
- Optional dependencies (betting lines, injuries can be NULL)
- Static reference table (travel distances)

---

## 🗂️ Quick Reference

### Phase 2 Dependencies

| Phase 2 Processor | Table | Phase 3 Usage | Criticality |
|-------------------|-------|---------------|-------------|
| nbac_schedule_processor | nba_raw.nbac_schedule | Core schedule + matchups | 🔴 CRITICAL |
| oddsa_game_lines | nba_raw.odds_api_game_lines | Betting lines (spreads/totals) | 🟡 OPTIONAL |
| nbac_injury_report_processor | nba_raw.nbac_injury_report | Player availability | 🟡 OPTIONAL |
| (fallback) espn_scoreboard_processor | nba_raw.espn_scoreboard | Historical game results | 🟢 FALLBACK |
| (static) | nba_static.travel_distances | Distance calculations | 🟢 ENRICHMENT |

---

## 📊 Data Flow Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           PHASE 2: RAW DATA                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [NBA.com API]  →  nbac_schedule_processor.py                          │
│       ↓                                                                 │
│  [GCS: schedule JSON files]                                            │
│       ↓              MERGE_UPDATE strategy                             │
│  nba_raw.nbac_schedule                                                 │
│       • game_date, game_id, teams, status                              │
│       • Source tracking: api_stats vs cdn_static                       │
│       • Updates: Every 2-4 hours (on new files)                        │
│       • Coverage: ~81.4% of games                                      │
│                                                                         │
│  [The Odds API]  →  oddsa_game_lines.py                               │
│       ↓                                                                 │
│  [Direct API calls]                                                     │
│       ↓              APPEND snapshot strategy                          │
│  nba_raw.odds_api_game_lines                                          │
│       • spreads, totals per bookmaker                                  │
│       • Snapshot timestamps                                            │
│       • Updates: Every 15 minutes during game days                     │
│       • Coverage: Variable (high near game time)                       │
│                                                                         │
│  [NBA.com Injury]  →  nbac_injury_report_processor.py                 │
│       ↓                                                                 │
│  [GCS: injury JSON files]                                              │
│       ↓              APPEND_ALWAYS strategy                            │
│  nba_raw.nbac_injury_report                                           │
│       • Player status per game                                         │
│       • Updates: 3-5 times daily (6 AM, 12 PM, 5 PM ET typical)      │
│       • Coverage: 0-50 players per day (variable)                      │
│                                                                         │
│  [ESPN API]  →  espn_scoreboard_processor.py (FALLBACK)               │
│       ↓                                                                 │
│  [GCS: scoreboard JSON files]                                          │
│       ↓              APPEND strategy                                   │
│  nba_raw.espn_scoreboard                                              │
│       • Game results (scores, winners)                                 │
│       • Updates: Real-time during games                                │
│       • Coverage: >95% (higher than nbac_schedule for results)        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                        PHASE 3: ANALYTICS                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  upcoming_team_game_context_processor.py                               │
│       • Extracts from all Phase 2 tables                               │
│       • Calculates: fatigue, betting, personnel, momentum              │
│       • Strategy: MERGE_UPDATE (deletes date range, inserts new)       │
│       • Updates: On-demand or scheduled (after Phase 2 updates)        │
│       ↓                                                                 │
│  nba_analytics.upcoming_team_game_context                             │
│       • 2 rows per game (home + away team perspective)                │
│       • Includes source tracking (TO BE ADDED)                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🗺️ Detailed Processor Mappings

### 1. Schedule Processor → Phase 3

**Source Information:**
- **Processor File:** `data_processors/raw/nbacom/nbac_schedule_processor.py`
- **Table:** `nba_raw.nbac_schedule`
- **Strategy:** MERGE_UPDATE (deletes entire season, re-inserts)
- **Trigger:** GCS file arrival (Pub/Sub on new schedule JSON)
- **Frequency:** Every 2-4 hours (when NBA.com updates)

**Data Source Tracking:**

```python
# Dual source detection from file path
def detect_data_source(self, file_path: str) -> str:
    if '/schedule-cdn/' in file_path:
        return "cdn_static"  # CDN scraper
    elif '/schedule/' in file_path:
        return "api_stats"   # API scraper
    else:
        return "api_stats"   # Default
```

**GCS File Paths:**
- API scraper: `gs://bucket/nba-com/schedule/2024/schedule_2024-25.json`
- CDN scraper: `gs://bucket/nba-com/schedule-cdn/2024/schedule_2024-25.json`

**Key Fields Populated:**

| Field | Source | Notes |
|-------|--------|-------|
| game_id | game.gameId | NBA.com unique ID (e.g., "0022400123") |
| game_date | game.gameDateEst | Parsed from ISO timestamp |
| season_year | Calculated | Based on game date (Oct+ = new season) |
| home_team_tricode | game.homeTeam.teamTricode | "LAL", "GSW", etc. |
| away_team_tricode | game.awayTeam.teamTricode | "DEN", "BOS", etc. |
| game_status | game.gameStatus | 1=scheduled, 2=in progress, 3=final |
| home_team_score | game.homeTeam.score | NULL if not complete |
| away_team_score | game.awayTeam.score | NULL if not complete |
| winning_team_tricode | Calculated | From scores (if status=3) |
| data_source | File path | "api_stats" or "cdn_static" |
| source_updated_at | Current timestamp | When processor ran |

**Phase 3 Usage:**

```sql
-- Extended window query (30 days before, 7 days after target)
SELECT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode,
    season_year,
    game_status,
    home_team_score,
    away_team_score,
    winning_team_tricode
FROM `nba_raw.nbac_schedule`
WHERE game_date BETWEEN extended_start AND extended_end
  AND game_status = 3  -- Only completed games
```

**Used For:**
- Core identifiers: game_id, game_date, teams
- Days rest calculation: LAG(game_date) for team schedule
- Momentum: win/loss streaks from winning_team_tricode
- Last game margin: Score differential for team

**Known Issues:**

| Issue | Impact | Mitigation |
|-------|--------|------------|
| Missing ~18.6% of games | Phase 3 has gaps | ESPN scoreboard fallback |
| Delayed score updates | Results lag 2-3 hours | Use espn_scoreboard for recency |
| NULL scores with status=3 | Incomplete data | Filter on NOT NULL scores |
| Dual sources | Potential duplicates | MERGE_UPDATE deduplicates |

---

### 2. Odds API Scraper → Phase 3

**Source Information:**
- **Scraper File:** `scrapers/oddsapi/oddsa_game_lines.py`
- **Table:** `nba_raw.odds_api_game_lines`
- **Strategy:** APPEND (every snapshot saved)
- **Trigger:** Scheduled (every 15 minutes during game days)
- **Frequency:** 96 snapshots per day per game (15-min intervals)

**API Configuration:**

```python
# Default settings
sport = "basketball_nba"
markets = "spreads,totals"     # Both spreads and totals
regions = "us"                 # US bookmakers only
bookmakers = "draftkings,fanduel"  # Default books
```

**API Endpoint:**
```
GET /v4/sports/{sport}/events/{eventId}/odds
```

**Required Parameters:**
- `event_id` - Odds API unique event ID
- `game_date` - For GCS path organization
- `api_key` - From env var ODDS_API_KEY

**GCS Path Structure:**
```
gs://bucket/odds-api/game-lines/
    2024/11/02/              # game_date
    LALDET/                  # teams_suffix
    game_lines_1430.json     # snap_hour
```

**Key Fields Populated:**

| Field | Source | Notes |
|-------|--------|-------|
| snapshot_timestamp | Request time | When snapshot was taken |
| game_id | Constructed | From game_date + teams |
| game_date | Request param | Eastern date |
| home_team_abbr | API response | Mapped from full name |
| away_team_abbr | API response | Mapped from full name |
| bookmaker_key | bookmaker.key | "draftkings", "fanduel" |
| market_key | market.key | "spreads" or "totals" |
| outcome_name | outcome.name | Team name OR "Over"/"Under" |
| outcome_point | outcome.point | Spread value or total value |
| outcome_price | outcome.price | Decimal odds |
| data_source | "current" | Indicates live scraper |

**Phase 3 Usage:**

```sql
-- Get latest snapshot for each game
WITH latest_lines AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY game_id, bookmaker_key, market_key, outcome_name
      ORDER BY snapshot_timestamp DESC
    ) as rn
  FROM `nba_raw.odds_api_game_lines`
  WHERE game_date BETWEEN start_date AND end_date
)
SELECT
    game_date,
    home_team_abbr,
    away_team_abbr,
    bookmaker_key,
    market_key,
    outcome_name,
    outcome_point as current_line,
    outcome_price as current_price
FROM latest_lines
WHERE rn = 1
```

**Used For:**
- Game spread: Filter `market_key='spreads'`, map `outcome_name` to team
- Game total: Filter `market_key='totals'`, take "Over" `outcome_point`
- Line movement: Opening vs current line (requires multiple snapshots)
- Bookmaker consensus: Average across DraftKings + FanDuel

**Team Name Mapping Challenge:**

**Problem:** Odds API uses full team names, we use abbreviations

```python
# Odds API Format:
{
  "outcome_name": "Los Angeles Lakers"  // Full name
}

# Our Format:
team_abbr = "LAL"  // Abbreviation
```

**Phase 3 Solution:**

```python
# In upcoming_team_game_context_processor.py
TEAM_NAME_MAP = {
    'Atlanta Hawks': 'ATL',
    'Boston Celtics': 'BOS',
    'Brooklyn Nets': 'BKN',
    # ... all 30 teams
    'Los Angeles Lakers': 'LAL',
    'Golden State Warriors': 'GSW',
}

# Multi-strategy matching
# 1. Try TEAM_NAME_MAP[outcome_name] → team_abbr
# 2. Try exact match (outcome_name == team_abbr)
# 3. Try contains (team_abbr in outcome_name)
# 4. Try home/away designation
```

**Known Issues:**

| Issue | Impact | Mitigation |
|-------|--------|------------|
| Team name mismatch | Can't match to team_abbr | TEAM_NAME_MAP in Phase 3 |
| Lines appear 24-48h before game | Early requests return NULL | Phase 3 accepts NULL gracefully |
| Multiple bookmakers | Need to choose one | Prioritize DraftKings in Phase 3 |
| Snapshot frequency | Storage costs | Keep only last 24 hours in hot storage |

---

### 3. Injury Report Processor → Phase 3

**Source Information:**
- **Processor File:** `data_processors/raw/nbacom/nbac_injury_report_processor.py`
- **Table:** `nba_raw.nbac_injury_report`
- **Strategy:** APPEND_ALWAYS (keep all historical reports)
- **Trigger:** GCS file arrival (Pub/Sub on new injury JSON)
- **Frequency:** 3-5 times daily (typically 6 AM, 12 PM, 5 PM ET)

**GCS File Paths:**

```
gs://bucket/nba-com/injury-reports/
    2024/11/02/                    # report_date
    injury_report_0600.json        # report_hour (24h format)
    injury_report_1200.json
    injury_report_1700.json
```

**Key Fields Populated:**

| Field | Type | Description |
|-------|------|-------------|
| report_date | DATE | Date report was issued |
| report_hour | INT64 | Hour of report (0-23) |
| game_date | DATE | Which game this applies to |
| game_id | STRING | Constructed from matchup + game_date |
| team | STRING | Team abbreviation |
| player_name_original | STRING | Original: "Hayes, Killian" |
| player_full_name | STRING | Normalized: "Killian Hayes" |
| player_lookup | STRING | Searchable: "killianhayes" |
| injury_status | STRING | Lowercase: "out", "questionable", etc. |
| reason | STRING | Full injury reason text |
| reason_category | STRING | "injury", "g_league", "rest", etc. |
| confidence_score | FLOAT64 | Per-record parsing confidence |
| overall_report_confidence | FLOAT64 | Overall report quality |

**Phase 3 Usage:**

```sql
-- Get latest report for each player per game
WITH latest_injury_status AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY game_date, player_lookup
      ORDER BY report_date DESC, report_hour DESC
    ) as rn
  FROM `nba_raw.nbac_injury_report`
  WHERE game_date BETWEEN start_date AND end_date
)
SELECT
  game_date,
  team,
  COUNT(CASE WHEN injury_status = 'out' THEN 1 END) as players_out,
  COUNT(CASE WHEN injury_status IN ('questionable', 'doubtful') THEN 1 END) as questionable_players
FROM latest_injury_status
WHERE rn = 1
GROUP BY game_date, team
```

**Used For:**
- Starters out count: Aggregate players with status='out'
- Questionable players: Count 'questionable' and 'doubtful'
- Personnel context: Overall team availability

**Confidence Scoring:**

```python
confidence_score = record.get('confidence', 1.0)  # 0.0-1.0
overall_confidence = parsing_stats.get('overall_confidence', 1.0)
```

**Phase 3 Should:**
- Prefer records with `confidence_score >= 0.8`
- Log warning if `overall_confidence < 0.85`
- Track which reports had low confidence for review

---

### 4. ESPN Scoreboard (Fallback) → Phase 3

**Source Information:**
- **Processor File:** `data_processors/raw/espn/espn_scoreboard_processor.py` (inferred)
- **Table:** `nba_raw.espn_scoreboard`
- **Strategy:** APPEND (historical snapshots)
- **Trigger:** GCS file arrival or scheduled scraper
- **Frequency:** Real-time during games, nightly batch for completed games

**Purpose:** Backup validation source for game results when `nba_raw.nbac_schedule` is missing games.

**Key Fields:**

```sql
game_id STRING,
game_date DATE,
home_team_abbr STRING,
away_team_abbr STRING,
home_team_score INT64,
away_team_score INT64,
home_team_winner BOOLEAN,
away_team_winner BOOLEAN,
is_completed BOOLEAN,
game_status STRING  -- "final", "scheduled"
```

**Phase 3 Usage (Fallback):**

```python
# Step 1: Try primary source (nbac_schedule)
schedule_results = query_nbac_schedule(lookback_period)

# Step 2: Check for gaps
dates_found = set(schedule_results['game_date'].unique())
dates_needed = set(date_range(lookback_period))
missing_dates = dates_needed - dates_found

# Step 3: Backfill from ESPN
if missing_dates:
    espn_query = f"""
    SELECT
        game_date,
        game_id,
        home_team_abbr,
        away_team_abbr,
        home_team_score,
        away_team_score,
        CASE
            WHEN home_team_winner THEN home_team_abbr
            WHEN away_team_winner THEN away_team_abbr
        END as winning_team_abbr,
        'espn_scoreboard' as source
    FROM `nba_raw.espn_scoreboard`
    WHERE game_date IN UNNEST({missing_dates})
      AND is_completed = true
      AND game_status = 'final'
    """

    espn_results = bq_client.query(espn_query).to_dataframe()

    # Combine sources
    all_results = pd.concat([schedule_results, espn_results], ignore_index=True)
```

**Coverage Analysis:**

| Source | Coverage | Freshness | Use Case |
|--------|----------|-----------|----------|
| nbac_schedule | ~81.4% | 2-3 hours lag | Primary |
| espn_scoreboard | >95% | Real-time | Fallback + validation |

**Recommendation:** Always try nbac_schedule first, fall back to ESPN for gaps.

---

### 5. Travel Distances (Static) → Phase 3

**Source Information:**
- **Table:** `nba_static.travel_distances`
- **Type:** Static reference table
- **Updates:** Only when teams relocate (rare)
- **Records:** 870 (30 teams × 29 destinations)

**Table Structure:**

```sql
CREATE TABLE nba_static.travel_distances (
    from_team STRING,              -- Origin team abbreviation
    to_team STRING,                -- Destination team abbreviation
    from_city STRING,              -- Origin city
    to_city STRING,                -- Destination city
    distance_miles INT64,          -- Great circle distance
    time_zones_crossed INT64,      -- Number of time zones (0-4)
    travel_direction STRING,       -- 'east', 'west', 'neutral'
    jet_lag_factor FLOAT64,        -- Weighted impact
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)
CLUSTER BY from_team, to_team
```

**Phase 3 Usage:**

```python
# In _calculate_basic_context() method
def _calculate_basic_context(self, game: pd.Series) -> Dict:
    home_game = game['home_game']

    # Travel distance (only for away games)
    travel_miles = 0
    if not home_game:
        # Away game - calculate travel from last game location
        last_opponent = game.get('last_opponent')
        opponent = game['opponent_team_abbr']

        if pd.notna(last_opponent):
            try:
                # Lookup in travel_distances table
                travel_info = self.travel.get_travel_distance(last_opponent, opponent)
                if travel_info:
                    travel_miles = travel_info['distance_miles']
            except Exception as e:
                logger.debug(f"Could not calculate travel: {e}")
                travel_miles = 0  # Safe fallback

    return {
        'home_game': bool(home_game),
        'travel_miles': travel_miles
    }
```

**Edge Cases:**

| Scenario | Handling |
|----------|----------|
| Home back-to-back | travel_miles = 0 (no travel) |
| Neutral site | May be inaccurate (manual override needed) |
| International games | May be inaccurate (London, Paris, Mexico City) |
| First game of season | travel_miles = 0 (no previous game) |
| Lookup failure | travel_miles = 0 (safe fallback) |

---

## 🔗 Field-Level Lineage

### Core Identifiers

```
[nbac_schedule.game_id]
    → (direct copy)
    → upcoming_team_game_context.game_id

[nbac_schedule.game_date]
    → (direct copy)
    → upcoming_team_game_context.game_date

[nbac_schedule.season_year]
    → (direct copy)
    → upcoming_team_game_context.season_year

[nbac_schedule.home_team_tricode]
    → (split into 2 records: home + away view)
    → upcoming_team_game_context.team_abbr (when home_game=TRUE)
    → upcoming_team_game_context.opponent_team_abbr (when home_game=FALSE)

[nbac_schedule.away_team_tricode]
    → (split into 2 records: home + away view)
    → upcoming_team_game_context.team_abbr (when home_game=FALSE)
    → upcoming_team_game_context.opponent_team_abbr (when home_game=TRUE)
```

### Betting Context

```
[odds_api_game_lines.outcome_point]
    WHERE market_key = 'spreads'
    AND bookmaker_key = 'draftkings'
    AND outcome_name MAPPED TO team_abbr
    → upcoming_team_game_context.game_spread

[odds_api_game_lines.outcome_point]
    WHERE market_key = 'totals'
    AND bookmaker_key = 'draftkings'
    AND outcome_name = 'Over'
    → upcoming_team_game_context.game_total

[current_line - opening_line]
    → upcoming_team_game_context.spread_movement
    → upcoming_team_game_context.total_movement
```

### Fatigue Metrics

```
[LAG(nbac_schedule.game_date) OVER (PARTITION BY team)]
    → (calculate date difference)
    → upcoming_team_game_context.team_days_rest

[DATE_DIFF(current_game_date, last_game_date)]
    = 1
    → upcoming_team_game_context.team_back_to_back = TRUE

[COUNT(nbac_schedule.game_date in last 7 days)]
    → upcoming_team_game_context.games_in_last_7_days

[COUNT(nbac_schedule.game_date in last 14 days)]
    → upcoming_team_game_context.games_in_last_14_days
```

### Personnel Context

```
[COUNT(nbac_injury_report WHERE injury_status = 'out')]
    GROUP BY game_date, team
    → upcoming_team_game_context.starters_out_count

[COUNT(nbac_injury_report WHERE injury_status IN ('questionable', 'doubtful'))]
    GROUP BY game_date, team
    → upcoming_team_game_context.questionable_players_count
```

### Momentum

```
[nbac_schedule.winning_team_tricode]
    → (count consecutive wins)
    → upcoming_team_game_context.team_win_streak_entering

[nbac_schedule.winning_team_tricode]
    → (count consecutive losses)
    → upcoming_team_game_context.team_loss_streak_entering

[home_score - away_score]
    for last game
    → upcoming_team_game_context.last_game_margin
```

### Travel

```
[travel_distances.distance_miles]
    WHERE from_team = last_opponent
    AND to_team = current_opponent
    AND home_game = FALSE
    → upcoming_team_game_context.travel_miles
```

---

## 📈 Data Quality Impact Matrix

| Phase 2 Issue | Phase 3 Impact | Severity | Mitigation |
|---------------|----------------|----------|------------|
| Schedule: Missing 18.6% of games | Gaps in team context | 🔴 HIGH | ESPN fallback implemented |
| Schedule: Delayed scores (2-3h lag) | Stale momentum data | 🟡 MEDIUM | Use ESPN for recent games |
| Schedule: NULL scores with status=3 | Incomplete streaks | 🟡 MEDIUM | Filter on NOT NULL |
| Odds: Team name mismatch | NULL spreads/totals | 🟡 MEDIUM | TEAM_NAME_MAP + multi-strategy |
| Odds: Lines missing 24h+ before game | NULL betting context | 🟢 LOW | Expected, Phase 5 waits |
| Injury: Multiple reports per day | Need latest only | 🟢 LOW | ROW_NUMBER() by time DESC |
| Injury: Low confidence scores | Unreliable data | 🟡 MEDIUM | Filter confidence >= 0.8 |
| Travel: Lookup failure | Missing distance | 🟢 LOW | Fallback to 0 |

---

## 🎯 Error Handling Strategy

### Phase 3 Should:

**For Missing Schedule Data (CRITICAL):**

```python
if schedule_data is None or len(schedule_data) == 0:
    # FAIL - cannot process without schedule
    raise ValueError("No schedule data - cannot continue")
```

**For Missing Betting Lines (OPTIONAL):**

```python
if betting_lines is None or len(betting_lines) == 0:
    # CONTINUE - betting is optional
    game_spread = NULL
    game_total = NULL
    logger.info("No betting lines available")
```

**For Missing Injury Data (OPTIONAL):**

```python
if injury_data is None or len(injury_data) == 0:
    # CONTINUE - assume healthy roster
    starters_out_count = 0
    questionable_players_count = 0
    logger.info("No injury data available")
```

**For Travel Lookup Failure (ENRICHMENT):**

```python
try:
    travel_info = self.travel.get_travel_distance(from_team, to_team)
    travel_miles = travel_info['distance_miles']
except Exception:
    # CONTINUE - fallback to 0
    travel_miles = 0
    logger.debug("Travel lookup failed, using 0")
```

---

## 🏷️ Source Completeness Tracking

### TO BE ADDED: Source Metadata Fields

```sql
-- Add to nba_analytics.upcoming_team_game_context schema

-- Schedule source (CRITICAL - always present)
source_nbac_schedule_last_updated TIMESTAMP,
source_nbac_schedule_rows_found INT64,
source_nbac_schedule_completeness_pct NUMERIC(5,2),

-- Betting lines source (OPTIONAL)
source_odds_lines_last_updated TIMESTAMP,
source_odds_lines_rows_found INT64,
source_odds_lines_completeness_pct NUMERIC(5,2),

-- Injury report source (OPTIONAL)
source_injury_report_last_updated TIMESTAMP,
source_injury_report_rows_found INT64,
source_injury_report_completeness_pct NUMERIC(5,2)
```

### Completeness Calculation

```python
def track_source_usage(self, dep_check: dict) -> None:
    """Record what sources were used during processing."""

    # Schedule source (critical)
    schedule_rows = dep_check['details']['nba_raw.nbac_schedule']['row_count']
    expected_schedule = 20  # ~10 games × 2 teams
    schedule_completeness = min((schedule_rows / expected_schedule) * 100, 100.0)

    self.source_nbac_schedule_last_updated = dep_check['details']['nba_raw.nbac_schedule']['last_updated']
    self.source_nbac_schedule_rows_found = schedule_rows
    self.source_nbac_schedule_completeness_pct = round(schedule_completeness, 2)

    # Betting lines source (optional)
    if 'nba_raw.odds_api_game_lines' in dep_check['details']:
        odds_rows = dep_check['details']['nba_raw.odds_api_game_lines']['row_count']
        expected_odds = 40  # Multiple bookmakers × games
        odds_completeness = min((odds_rows / expected_odds) * 100, 100.0)

        self.source_odds_lines_last_updated = dep_check['details']['nba_raw.odds_api_game_lines']['last_updated']
        self.source_odds_lines_rows_found = odds_rows
        self.source_odds_lines_completeness_pct = round(odds_completeness, 2)

    # Injury report source (optional)
    if 'nba_raw.nbac_injury_report' in dep_check['details']:
        injury_rows = dep_check['details']['nba_raw.nbac_injury_report']['row_count']
        expected_injury = 10  # Variable by day
        injury_completeness = min((injury_rows / expected_injury) * 100, 100.0)

        self.source_injury_report_last_updated = dep_check['details']['nba_raw.nbac_injury_report']['last_updated']
        self.source_injury_report_rows_found = injury_rows
        self.source_injury_report_completeness_pct = round(injury_completeness, 2)
```

---

## 🔍 Troubleshooting Guide

### Issue: Phase 3 Shows NULL Spreads

**Symptoms:**
- `game_spread = NULL` for many games
- `game_total = NULL` for many games

**Diagnosis:**

```sql
-- Check if betting lines exist
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games_with_lines,
  COUNT(*) as total_line_records,
  COUNT(DISTINCT bookmaker_key) as bookmakers_seen
FROM `nba_raw.odds_api_game_lines`
WHERE game_date = '2024-11-02'
GROUP BY game_date;
```

**Possible Causes:**
- Lines not yet available (>24h before game) ✅ Expected
- Odds scraper not running ❌ Check scheduler
- Team name mismatch ❌ Check TEAM_NAME_MAP
- Wrong bookmaker ❌ Verify DraftKings has lines

**Solution:**

```python
# In Phase 3 processor logs, check for:
logger.warning(f"✗ Could not match spread for team {team_abbr}")

# If seeing this, add missing team to TEAM_NAME_MAP
TEAM_NAME_MAP = {
    # ... existing mappings
    'New Team Name': 'ABV',  # Add if missing
}
```

### Issue: Phase 3 Shows Missing Schedule Data

**Symptoms:**
- Phase 3 processor fails with "No schedule data"
- Or processes with <10 games when expecting 10+

**Diagnosis:**

```sql
-- Check schedule coverage
SELECT
  game_date,
  COUNT(*) as games_in_schedule,
  COUNT(DISTINCT data_source) as sources_used,
  MIN(processed_at) as earliest_processed,
  MAX(processed_at) as latest_processed
FROM `nba_raw.nbac_schedule`
WHERE game_date BETWEEN '2024-11-01' AND '2024-11-07'
GROUP BY game_date
ORDER BY game_date;
```

**Possible Causes:**
- Schedule processor hasn't run ❌ Check GCS triggers
- Schedule files missing in GCS ❌ Check scraper
- Date range issue ❌ Verify date parameters
- Preseason games filtered ✅ Expected behavior

**Solution:**

```bash
# Check GCS for schedule files
gsutil ls -l gs://bucket/nba-com/schedule/2024/

# Manually trigger schedule processor
python -m data_processors.raw.nbac_schedule.run_processor \
    --file_path=gs://bucket/nba-com/schedule/2024/schedule_2024-25.json

# Use ESPN fallback if schedule missing
# Phase 3 processor should automatically fall back to espn_scoreboard
```

### Issue: Injury Counts Always Zero

**Symptoms:**
- `starters_out_count = 0` for all games
- `questionable_players_count = 0` for all games

**Diagnosis:**

```sql
-- Check if injury reports exist
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as injured_players,
  COUNT(DISTINCT team) as teams_affected,
  MAX(report_date) as latest_report,
  COUNT(CASE WHEN injury_status = 'out' THEN 1 END) as out_count,
  COUNT(CASE WHEN injury_status = 'questionable' THEN 1 END) as questionable_count
FROM `nba_raw.nbac_injury_report`
WHERE game_date = '2024-11-02'
GROUP BY game_date;
```

**Possible Causes:**
- No injury reports for this date ✅ Everyone healthy?
- Injury processor hasn't run ❌ Check triggers
- Team abbreviation mismatch ❌ Check team field
- Report date vs game date confusion ❌ Verify date logic

**Solution:**

```python
# In Phase 3 processor, verify injury query:
injury_data = self.injury_data[
    (self.injury_data['team'] == team_abbr) &  # Check team field name
    (self.injury_data['game_date'] == game_date)  # Check date matching
]

# If empty, log for debugging:
if len(injury_data) == 0:
    logger.debug(f"No injury data for {team_abbr} on {game_date}")
    logger.debug(f"Available teams: {self.injury_data['team'].unique()}")
    logger.debug(f"Available dates: {self.injury_data['game_date'].unique()}")
```

---

## 🚀 Next Steps

### ⬜ Implementation Checklist

- [ ] **Verify Phase 2 dependencies** - Confirm all 5 tables exist
- [ ] **Add source tracking fields** - Update analytics table schema
- [ ] **Implement dependency checking** - Add `get_dependencies()` method
- [ ] **Implement source tracking** - Add `track_source_usage()` method
- [ ] **Create unit tests** - Test each Phase 2 source integration
- [ ] **Set up scheduling** - Configure Pub/Sub or cron triggers
- [ ] **Add monitoring** - Dashboards for Phase 2 → Phase 3 flow
- [ ] **Optimize queries** - Implement caching and batching

---

**Document Status:** 🟡 In Progress - Source tracking and dependency checking needed
**Version:** 1.0
**Last Updated:** 2025-11-15
**Next Review:** After source tracking implementation
