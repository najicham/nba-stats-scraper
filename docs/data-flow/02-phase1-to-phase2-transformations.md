# Phase 1→2 Transformations: JSON/GCS → BigQuery Raw Tables

**File:** `docs/data-flow/02-phase1-to-phase2-transformations.md`
**Created:** 2025-11-08
**Last Updated:** 2025-11-15
**Purpose:** Document how each Phase 2 processor transforms JSON from GCS into BigQuery raw tables
**Audience:** Engineers building processors, debugging data pipelines, and understanding transformations
**Status:** Current

---

## Table of Contents

1. [Overview](#overview)
2. [Common Transformation Patterns](#common-transformation-patterns)
3. [Odds API Processors](#odds-api-processors)
4. [NBA.com Processors](#nbacom-processors)
5. [Ball Don't Lie Processors](#ball-dont-lie-processors)
6. [BettingPros Processors](#bettingpros-processors)
7. [BigDataBall Processors](#bigdataball-processors)
8. [ESPN Processors](#espn-processors)
9. [Basketball Reference Processors](#basketball-reference-processors)

---

## Overview

### Data Transformation Architecture

```
GCS Storage (Phase 1 JSON)
    ↓
Phase 2: Processors (21 processors)
    ↓ [Read JSON from GCS]
    ↓ [Transform & normalize]
    ↓ [Validate data quality]
    ↓ [Enrich with lookups]
    ↓
BigQuery Raw Tables (nba_raw.* - 21 tables)
    ↓
Phase 3: Analytics
```

### Processor Summary by Source

| Source | Processors | Strategy | Tables |
|--------|-----------|----------|--------|
| Odds API | 2 | APPEND_ALWAYS, MERGE_UPDATE | 2 |
| NBA.com | 9 | MERGE_UPDATE, APPEND_ALWAYS | 9 |
| Ball Don't Lie | 4 | MERGE_UPDATE, APPEND_ALWAYS | 4 |
| BettingPros | 1 | APPEND_ALWAYS | 1 |
| BigDataBall | 1 | MERGE_UPDATE | 1 |
| ESPN | 3 | MERGE_UPDATE | 3 |
| Basketball Reference | 1 | MERGE_UPDATE | 1 |
| **Total** | **21** | **Various** | **21** |

### Processing Strategies Explained

| Strategy | Behavior | Use Case | Examples |
|----------|----------|----------|----------|
| APPEND_ALWAYS | Insert all records, keep duplicates | Line movement tracking, audit trails | Odds props, injury reports |
| MERGE_UPDATE | Delete existing → Insert new | Game-level data, current state | Box scores, schedules, rosters |
| INSERT_NEW_ONLY | Insert only if not exists | Historical transactions | Player movement |

---

## Common Transformation Patterns

### 1. Game ID Standardization

**System Format:** `YYYYMMDD_AWAY_HOME`

All processors normalize diverse source formats into this standard:

```python
# From Ball Don't Lie
{
    "game": {
        "id": 12345,
        "date": "2025-01-15T00:00:00.000Z",
        "visitor_team": {"abbreviation": "PHI"},
        "home_team": {"abbreviation": "LAL"}
    }
}

# Transformation
game_date = "2025-01-15"  # Parse from date field
away_team = "PHI"          # From visitor_team.abbreviation
home_team = "LAL"          # From home_team.abbreviation
game_id = f"{game_date.replace('-', '')}_{away_team}_{home_team}"
# Result: "20250115_PHI_LAL"
```

```python
# From NBA.com
{
    "gameCode": "20250115/PHILAL"
}

# Transformation
parts = game_code.split('/')
date_str = parts[0]  # "20250115"
teams = parts[1]      # "PHILAL"
away_team = teams[:3]  # "PHI"
home_team = teams[3:]  # "LAL"
game_id = f"{date_str}_{away_team}_{home_team}"
# Result: "20250115_PHI_LAL"
```

```python
# From Odds API (via event lookup)
{
    "id": "abc123def456",
    "home_team": "Los Angeles Lakers",
    "away_team": "Philadelphia 76ers"
}

# Transformation (requires team name → abbreviation mapping)
home_team_abbr = team_name_to_abbr("Los Angeles Lakers")  # "LAL"
away_team_abbr = team_name_to_abbr("Philadelphia 76ers")  # "PHI"
game_date = parse_from_commence_time(event["commence_time"])
game_id = f"{game_date.replace('-', '')}_{away_team_abbr}_{home_team_abbr}"
# Result: "20250115_PHI_LAL"
```

---

### 2. Player Lookup Normalization

**System Format:** `{firstname}{lastname}` (lowercase, no spaces, no suffixes)

```python
# From Ball Don't Lie
{
    "player": {
        "first_name": "LeBron",
        "last_name": "James"
    }
}

# Transformation
player_lookup = f"{first_name.lower()}{last_name.lower()}"
# Result: "lebronjames"
```

```python
# From NBA.com (full name)
{
    "playerName": "LeBron James"
}

# Transformation
parts = player_name.split()
first_name = parts[0]
last_name = parts[-1]
player_lookup = f"{first_name.lower()}{last_name.lower()}"
# Result: "lebronjames"
```

```python
# From Gamebooks (last name only - requires lookup)
{
    "name": "James",
    "team": "LAL"
}

# Transformation (requires Basketball Reference roster lookup)
full_name = resolve_player_name(
    last_name="James",
    team="LAL",
    season=2024,
    game_date="2025-01-15"
)  # Returns "LeBron James"

player_lookup = normalize_name(full_name)
# Result: "lebronjames"
```

---

### 3. Team Abbreviation Mapping

**System Format:** Three-letter NBA codes (LAL, BOS, GSW, PHI, etc.)

```python
# ESPN uses non-standard codes
ESPN_TEAM_MAPPING = {
    "NY": "NYK",    # New York Knicks
    "GS": "GSW",    # Golden State Warriors
    "SA": "SAS",    # San Antonio Spurs
    "NO": "NOP",    # New Orleans Pelicans
}

def normalize_team_abbr(espn_abbr):
    return ESPN_TEAM_MAPPING.get(espn_abbr, espn_abbr)

# Result: "NY" → "NYK", "GS" → "GSW"
```

```python
# Odds API uses full team names
TEAM_NAME_MAPPING = {
    "Los Angeles Lakers": "LAL",
    "Philadelphia 76ers": "PHI",
    "Golden State Warriors": "GSW",
    # ... all 30 teams
}

def team_name_to_abbr(team_name):
    return TEAM_NAME_MAPPING.get(team_name)
```

---

### 4. Odds Format Conversion

```python
# Odds API returns decimal odds
{
    "price": 1.91  # Decimal format
}

# Transform to American odds
def decimal_to_american(decimal_odds):
    if decimal_odds >= 2.0:
        # Positive odds (underdog)
        return int((decimal_odds - 1) * 100)
    else:
        # Negative odds (favorite)
        return int(-100 / (decimal_odds - 1))

# Result: 1.91 → -110
```

```python
# BettingPros returns American odds
{
    "odds": -110  # American format
}

# Transform to decimal odds
def american_to_decimal(american_odds):
    if american_odds > 0:
        return (american_odds / 100) + 1
    else:
        return (100 / abs(american_odds)) + 1

# Result: -110 → 1.909
```

---

### 5. Timestamp Extraction

```python
# Common pattern: Extract GCS file timestamp
source_file_path = "gs://nba-scraped-data/ball-dont-lie/boxscores/2025-01-15/2025-01-16T04:32:18.123456Z.json"

# Extract timestamp from path
import re
timestamp_pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\.json'
match = re.search(timestamp_pattern, source_file_path)
scrape_timestamp = match.group(1) if match else None

# Result: "2025-01-16T04:32:18.123456Z"
```

---

## Odds API Processors

### 1. OddsApiPropsProcessor

**Purpose:** Transform player prop betting lines into structured records for analysis

#### Input Source

- **Phase 1 Scraper:** GetOddsApiHistoricalEventOdds, GetOddsApiCurrentEventOdds
- **GCS Path:**
  - Historical: `gs://nba-scraped-data/odds-api/player-props-history/{date}/{event_id}-{teams}/{timestamp}-snap-{time}.json`
  - Current: `gs://nba-scraped-data/odds-api/player-props/{date}/{event_id}-{teams}/{timestamp}-snap-{time}.json`

#### JSON Structure

```json
{
  "id": "abc123def456",
  "sport_key": "basketball_nba",
  "commence_time": "2025-01-15T23:00:00Z",
  "home_team": "Los Angeles Lakers",
  "away_team": "Philadelphia 76ers",
  "bookmakers": [
    {
      "key": "draftkings",
      "title": "DraftKings",
      "last_update": "2025-01-15T18:30:00Z",
      "markets": [
        {
          "key": "player_points",
          "last_update": "2025-01-15T18:30:00Z",
          "outcomes": [
            {
              "name": "Over",
              "description": "LeBron James",
              "price": 1.91,
              "point": 25.5
            },
            {
              "name": "Under",
              "description": "LeBron James",
              "price": 1.91,
              "point": 25.5
            }
          ]
        }
      ]
    }
  ]
}
```

#### Field Mapping

| BigQuery Field | Source JSON Path | Transformation |
|----------------|------------------|----------------|
| game_id | Derived | Map event_id → schedule → construct YYYYMMDD_AWAY_HOME |
| game_date | commence_time | Parse date component |
| event_id | id | Direct copy |
| snapshot_timestamp | bookmakers[].last_update | Direct copy as TIMESTAMP |
| player_name | outcomes[].description | Direct copy (e.g., "LeBron James") |
| player_lookup | Derived | Normalize: lebronjames |
| team_name | home_team or away_team | Based on player lookup |
| team_abbr | Derived | Map full name → abbreviation (e.g., "LAL") |
| bookmaker | bookmakers[].key | Normalize: "draftkings" → "DraftKings" |
| points_line | outcomes[].point | Direct copy (e.g., 25.5) |
| over_price_decimal | outcomes[].price where name="Over" | Direct copy |
| under_price_decimal | outcomes[].price where name="Under" | Direct copy |
| over_price_american | Derived | Convert decimal → American (1.91 → -110) |
| under_price_american | Derived | Convert decimal → American (1.91 → -110) |
| market_key | markets[].key | Direct copy ("player_points") |

#### Transformation Logic

```python
# 1. Extract game identifiers
event_id = json_data["id"]
home_team_name = json_data["home_team"]
away_team_name = json_data["away_team"]

# Map team names to abbreviations
home_team_abbr = TEAM_NAME_MAPPING[home_team_name]  # "LAL"
away_team_abbr = TEAM_NAME_MAPPING[away_team_name]  # "PHI"

# Parse game date from commence_time
commence_time = datetime.fromisoformat(json_data["commence_time"].replace('Z', '+00:00'))
game_date = commence_time.date()  # 2025-01-15

# Construct game_id
game_id = f"{game_date.strftime('%Y%m%d')}_{away_team_abbr}_{home_team_abbr}"
# Result: "20250115_PHI_LAL"

# 2. Process each bookmaker
for bookmaker in json_data["bookmakers"]:
    bookmaker_key = bookmaker["key"]
    snapshot_timestamp = bookmaker["last_update"]

    # 3. Process each market (player_points, player_rebounds, etc.)
    for market in bookmaker["markets"]:
        market_key = market["key"]

        # 4. Group outcomes by player (Over + Under)
        players = {}
        for outcome in market["outcomes"]:
            player_name = outcome["description"]  # "LeBron James"
            bet_side = outcome["name"]  # "Over" or "Under"
            price = outcome["price"]  # Decimal odds
            line = outcome["point"]  # Prop line

            if player_name not in players:
                players[player_name] = {}

            players[player_name][bet_side.lower()] = {
                "price_decimal": price,
                "price_american": decimal_to_american(price),
                "line": line
            }

        # 5. Create BigQuery record for each player
        for player_name, sides in players.items():
            # Normalize player name
            player_lookup = normalize_player_name(player_name)

            # Determine player's team (lookup in player registry)
            player_team_abbr = get_player_team(player_lookup, game_date)

            record = {
                "game_id": game_id,
                "game_date": game_date,
                "event_id": event_id,
                "snapshot_timestamp": snapshot_timestamp,
                "player_name": player_name,
                "player_lookup": player_lookup,
                "team_name": home_team_name if player_team_abbr == home_team_abbr else away_team_name,
                "team_abbr": player_team_abbr,
                "bookmaker": bookmaker_key,
                "points_line": sides["over"]["line"],
                "over_price_decimal": sides["over"]["price_decimal"],
                "under_price_decimal": sides["under"]["price_decimal"],
                "over_price_american": sides["over"]["price_american"],
                "under_price_american": sides["under"]["price_american"],
                "market_key": market_key,
                "source_file_path": gcs_path,
                "processed_at": datetime.now()
            }
```

#### Output Schema

**Table:** `nba_raw.odds_api_player_points_props`

**Schema Definition:** `schemas/bigquery/raw/odds_api_props_tables.sql`

```sql
CREATE TABLE nba_raw.odds_api_player_points_props (
  game_id              STRING,       -- "20250115_PHI_LAL"
  game_date            DATE,         -- 2025-01-15
  event_id             STRING,       -- "abc123def456"
  snapshot_timestamp   TIMESTAMP,    -- 2025-01-15 18:30:00 UTC
  player_name          STRING,       -- "LeBron James"
  player_lookup        STRING,       -- "lebronjames"
  team_name            STRING,       -- "Los Angeles Lakers"
  team_abbr            STRING,       -- "LAL"
  bookmaker            STRING,       -- "draftkings"
  points_line          FLOAT64,      -- 25.5
  over_price_american  INT64,        -- -110
  under_price_american INT64,        -- -110
  over_price_decimal   FLOAT64,      -- 1.91
  under_price_decimal  FLOAT64,      -- 1.91
  market_key           STRING,       -- "player_points"
  source_file_path     STRING,
  processed_at         TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup, bookmaker, game_date;
```

#### Data Quality Validations

```python
# Validation rules applied during processing
validations = {
    "price_range": lambda p: 1.01 <= p <= 10.0,  # Decimal odds
    "line_positive": lambda l: l > 0,             # Points line must be positive
    "both_sides_exist": lambda sides: "over" in sides and "under" in sides,
    "player_team_match": lambda p, teams: p in [teams["home"], teams["away"]],
}
```

#### Transformation Example

**Input JSON (excerpt):**

```json
{
  "id": "abc123",
  "commence_time": "2025-01-15T23:00:00Z",
  "home_team": "Los Angeles Lakers",
  "away_team": "Philadelphia 76ers",
  "bookmakers": [{
    "key": "draftkings",
    "markets": [{
      "key": "player_points",
      "outcomes": [
        {"name": "Over", "description": "LeBron James", "price": 1.91, "point": 25.5},
        {"name": "Under", "description": "LeBron James", "price": 1.91, "point": 25.5}
      ]
    }]
  }]
}
```

**Output BigQuery Record:**

```
game_id: "20250115_PHI_LAL"
game_date: 2025-01-15
event_id: "abc123"
snapshot_timestamp: 2025-01-15 18:30:00 UTC
player_name: "LeBron James"
player_lookup: "lebronjames"
team_name: "Los Angeles Lakers"
team_abbr: "LAL"
bookmaker: "draftkings"
points_line: 25.5
over_price_american: -110
under_price_american: -110
over_price_decimal: 1.91
under_price_decimal: 1.91
market_key: "player_points"
```

#### Processing Strategy

- **Strategy:** APPEND_ALWAYS
- **Reason:** Preserves all snapshots for line movement tracking
- **Records per Game:**
  - Regular season: ~20-23 records (11-15 players × 1.9 bookmakers avg)
  - Playoffs: ~26-28 records (14-15 players × 1.9 bookmakers avg)

---

### 2. OddsGameLinesProcessor

**Purpose:** Transform game-level betting lines (spreads, totals) into structured records

#### Input Source

- **Phase 1 Scraper:** GetOddsApiHistoricalGameLines
- **GCS Path:** `gs://nba-scraped-data/odds-api/game-lines-history/{date}/{event_id}-{teams}/{timestamp}-snap-{time}.json`

#### JSON Structure

```json
{
  "id": "abc123def456",
  "commence_time": "2025-01-15T23:00:00Z",
  "home_team": "Los Angeles Lakers",
  "away_team": "Philadelphia 76ers",
  "bookmakers": [
    {
      "key": "draftkings",
      "title": "DraftKings",
      "last_update": "2025-01-15T18:30:00Z",
      "markets": [
        {
          "key": "spreads",
          "outcomes": [
            {"name": "Los Angeles Lakers", "price": 1.91, "point": -4.5},
            {"name": "Philadelphia 76ers", "price": 1.91, "point": 4.5}
          ]
        },
        {
          "key": "totals",
          "outcomes": [
            {"name": "Over", "price": 1.91, "point": 227.5},
            {"name": "Under", "price": 1.91, "point": 227.5}
          ]
        }
      ]
    }
  ]
}
```

#### Field Mapping

| BigQuery Field | Source JSON Path | Transformation |
|----------------|------------------|----------------|
| snapshot_timestamp | bookmakers[].last_update | Direct copy as TIMESTAMP |
| game_id | Derived | Construct from date + teams |
| game_date | commence_time | Parse date component |
| commence_time | commence_time | Direct copy as TIMESTAMP |
| home_team | home_team | Direct copy |
| away_team | away_team | Direct copy |
| home_team_abbr | Derived | Map name → abbreviation |
| away_team_abbr | Derived | Map name → abbreviation |
| bookmaker_key | bookmakers[].key | Direct copy |
| bookmaker_title | bookmakers[].title | Direct copy |
| market_key | markets[].key | Direct copy ("spreads" or "totals") |
| outcome_name | outcomes[].name | Direct copy (team name, "Over", "Under") |
| outcome_price | outcomes[].price | Direct copy (decimal odds) |
| outcome_point | outcomes[].point | Direct copy (spread or total) |

#### Output Schema

**Table:** `nba_raw.odds_api_game_lines`

**Schema Definition:** `schemas/bigquery/raw/odds_api_props_tables.sql`

```sql
CREATE TABLE nba_raw.odds_api_game_lines (
  snapshot_timestamp  TIMESTAMP,    -- 2025-01-15 18:30:00 UTC
  game_id            STRING,       -- "20250115_PHI_LAL"
  game_date          DATE,         -- 2025-01-15
  commence_time      TIMESTAMP,    -- 2025-01-15 23:00:00 UTC
  home_team          STRING,       -- "Los Angeles Lakers"
  away_team          STRING,       -- "Philadelphia 76ers"
  home_team_abbr     STRING,       -- "LAL"
  away_team_abbr     STRING,       -- "PHI"
  bookmaker_key      STRING,       -- "draftkings"
  bookmaker_title    STRING,       -- "DraftKings"
  market_key         STRING,       -- "spreads" or "totals"
  outcome_name       STRING,       -- Team name, "Over", "Under"
  outcome_price      FLOAT64,      -- 1.91
  outcome_point      FLOAT64       -- -4.5 (spread) or 227.5 (total)
)
PARTITION BY game_date
CLUSTER BY game_id, bookmaker_key, market_key;
```

#### Expected Records per Game

**Formula:** 2 bookmakers × 2 markets × 2 outcomes = 8 records per game

**Example breakdown:**
1. DraftKings - Spreads - Lakers (-4.5)
2. DraftKings - Spreads - 76ers (+4.5)
3. DraftKings - Totals - Over (227.5)
4. DraftKings - Totals - Under (227.5)
5. FanDuel - Spreads - Lakers (-4.5)
6. FanDuel - Spreads - 76ers (+4.5)
7. FanDuel - Totals - Over (227.5)
8. FanDuel - Totals - Under (227.5)

#### Processing Strategy

- **Strategy:** MERGE_UPDATE
- **Deduplication Key:** (game_id, snapshot_timestamp, bookmaker_key, market_key, outcome_name)
- **Data Quality:** 99.2% of games have expected 8 records

---

## NBA.com Processors

### 3. NbacScheduleProcessor

**Purpose:** Foundation table providing complete NBA schedule with enhanced metadata

#### Input Source

- **Phase 1 Scraper:** GetNbaComScheduleApi
- **GCS Path:** `gs://nba-scraped-data/nba-com/schedule/{season}/{timestamp}.json`

#### JSON Structure (excerpt)

```json
{
  "leagueSchedule": {
    "seasonYear": "2024-25",
    "gameDates": [
      {
        "gameDate": "2025-01-15",
        "games": [
          {
            "gameId": "0022400561",
            "gameCode": "20250115/PHILAL",
            "gameStatus": 1,
            "gameStatusText": "7:00 pm ET",
            "gameDateTimeUTC": "2025-01-16T00:00:00Z",
            "gameEt": "2025-01-15T19:00:00",
            "homeTeam": {
              "teamId": 1610612747,
              "teamName": "Lakers",
              "teamCity": "Los Angeles",
              "teamTricode": "LAL",
              "wins": 35,
              "losses": 15
            },
            "awayTeam": {
              "teamId": 1610612755,
              "teamName": "76ers",
              "teamCity": "Philadelphia",
              "teamTricode": "PHI",
              "wins": 28,
              "losses": 22
            },
            "broadcasters": {
              "nationalBroadcasters": [
                {"broadcasterDisplay": "ESPN"}
              ]
            }
          }
        ]
      }
    ]
  }
}
```

#### Field Mapping

| BigQuery Field | Source JSON Path | Transformation |
|----------------|------------------|----------------|
| game_id | Derived | Construct from gameCode: 20250115_PHI_LAL |
| nba_game_id | gameId | Direct copy: "0022400561" |
| game_date | gameDate | Parse as DATE |
| season_year | seasonYear | Parse starting year: 2024 |
| game_code | gameCode | Direct copy: "20250115/PHILAL" |
| game_status | gameStatus | Direct copy (1=scheduled, 2=live, 3=final) |
| home_team_tricode | homeTeam.teamTricode | Direct copy: "LAL" |
| away_team_tricode | awayTeam.teamTricode | Direct copy: "PHI" |
| home_team_name | homeTeam.teamName | Direct copy: "Lakers" |
| away_team_name | awayTeam.teamName | Direct copy: "76ers" |
| home_team_wins | homeTeam.wins | Direct copy: 35 |
| home_team_losses | homeTeam.losses | Direct copy: 15 |
| away_team_wins | awayTeam.wins | Direct copy: 28 |
| away_team_losses | awayTeam.losses | Direct copy: 22 |
| is_primetime | Derived | Detect ESPN/TNT/ABC in broadcasters |
| has_national_tv | Derived | Any national broadcaster present |
| primary_network | Derived | First national broadcaster |

#### Transformation Logic

```python
# 1. Parse game identifiers
game_code = game_json["gameCode"]  # "20250115/PHILAL"
parts = game_code.split('/')
date_str = parts[0]   # "20250115"
teams_str = parts[1]  # "PHILAL"

away_team_tricode = teams_str[:3]  # "PHI"
home_team_tricode = teams_str[3:]  # "LAL"

game_id = f"{date_str}_{away_team_tricode}_{home_team_tricode}"
# Result: "20250115_PHI_LAL"

# 2. Enhanced analytical fields
broadcasters = game_json.get("broadcasters", {})
national = broadcasters.get("nationalBroadcasters", [])

# Primetime detection
primetime_networks = {"ESPN", "TNT", "ABC", "NBA TV"}
is_primetime = any(
    b.get("broadcasterDisplay") in primetime_networks
    for b in national
)

# Network extraction
primary_network = national[0].get("broadcasterDisplay") if national else None

# 3. Game classification
game_date = datetime.strptime(date_str, "%Y%m%d").date()
day_of_week = game_date.strftime("%A")
is_weekend = day_of_week in ["Saturday", "Sunday"]

# Christmas game detection
is_christmas = (game_date.month == 12 and game_date.day == 25)
```

#### Output Schema

**Table:** `nba_raw.nbac_schedule`

**Schema Definition:** `schemas/bigquery/raw/nbac_schedule_tables.sql`

```sql
CREATE TABLE nba_raw.nbac_schedule (
  game_id               STRING,      -- "20250115_PHI_LAL"
  nba_game_id          STRING,      -- "0022400561"
  game_date            DATE,        -- 2025-01-15
  season_year          INT64,       -- 2024
  game_code            STRING,      -- "20250115/PHILAL"
  game_status          INT64,       -- 1, 2, or 3
  home_team_tricode    STRING,      -- "LAL"
  away_team_tricode    STRING,      -- "PHI"
  home_team_name       STRING,      -- "Lakers"
  away_team_name       STRING,      -- "76ers"

  -- Enhanced analytical fields (18 total)
  is_primetime         BOOLEAN,     -- ESPN/TNT/ABC detected
  has_national_tv      BOOLEAN,     -- Any national broadcaster
  primary_network      STRING,      -- "ESPN", "TNT", etc.
  is_regular_season    BOOLEAN,     -- TRUE if regular season
  is_playoffs          BOOLEAN,     -- TRUE if playoffs
  is_christmas         BOOLEAN,     -- TRUE if Dec 25
  day_of_week          STRING,      -- "Wednesday"
  is_weekend           BOOLEAN,     -- TRUE if Sat/Sun

  processed_at         TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY game_date, home_team_tricode, away_team_tricode, season_year;
```

#### Processing Strategy

- **Strategy:** MERGE_UPDATE
- **Business Filtering:** Excludes preseason games, includes regular season + playoffs + All-Star
- **Critical:** This is the foundation table - all game-based processing joins against this table

---

### 4. NbacTeamBoxscoreProcessor

**Purpose:** Official team statistics for completed games (replaces deprecated Scoreboard V2)

#### Input Source

- **Phase 1 Scraper:** GetNbaComTeamBoxscore
- **GCS Path:** `gs://nba-scraped-data/nba-com/team-boxscore/{game_date}/{game_id}/{timestamp}.json`

#### JSON Structure

```json
{
  "boxScoreTraditional": {
    "gameId": "0022400561",
    "homeTeam": {
      "teamId": 1610612747,
      "teamTricode": "LAL",
      "teamCity": "Los Angeles",
      "teamName": "Lakers",
      "statistics": {
        "fieldGoalsMade": 42,
        "fieldGoalsAttempted": 88,
        "fieldGoalsPercentage": 0.477,
        "threePointersMade": 15,
        "threePointersAttempted": 38,
        "freeThrowsMade": 19,
        "freeThrowsAttempted": 24,
        "reboundsOffensive": 8,
        "reboundsDefensive": 35,
        "reboundsTotal": 43,
        "assists": 28,
        "steals": 9,
        "blocks": 6,
        "turnovers": 12,
        "foulsPersonal": 18,
        "points": 118,
        "plusMinusPoints": 6
      }
    },
    "awayTeam": {
      "teamId": 1610612755,
      "teamTricode": "PHI",
      "statistics": { /* same structure */ }
    }
  }
}
```

#### Field Mapping

| BigQuery Field | Source JSON Path | Transformation |
|----------------|------------------|----------------|
| game_id | Derived | Construct from game_date + teams |
| nba_game_id | gameId | Direct copy |
| game_date | From GCS path | Extract from path |
| team_abbr | teamTricode | Direct copy |
| is_home | Derived | TRUE for homeTeam, FALSE for awayTeam |
| fg_made | statistics.fieldGoalsMade | Direct copy |
| fg_attempted | statistics.fieldGoalsAttempted | Direct copy |
| fg_percentage | statistics.fieldGoalsPercentage | Direct copy |
| three_pt_made | statistics.threePointersMade | Direct copy |
| points | statistics.points | Direct copy |
| plus_minus | statistics.plusMinusPoints | Direct copy |

#### Transformation Logic

```python
# 1. Extract game identifiers from path
# Path: gs://.../team-boxscore/2025-01-15/20250115_PHI_LAL/timestamp.json
game_id = extract_from_path(gcs_path, -2)  # "20250115_PHI_LAL"
game_date = extract_from_path(gcs_path, -3)  # "2025-01-15"

# 2. Process both teams (home and away)
home_team = json_data["boxScoreTraditional"]["homeTeam"]
away_team = json_data["boxScoreTraditional"]["awayTeam"]

for team, is_home in [(home_team, True), (away_team, False)]:
    record = {
        "game_id": game_id,
        "nba_game_id": json_data["boxScoreTraditional"]["gameId"],
        "game_date": game_date,
        "team_abbr": team["teamTricode"],
        "is_home": is_home,
        "fg_made": team["statistics"]["fieldGoalsMade"],
        "fg_attempted": team["statistics"]["fieldGoalsAttempted"],
        "points": team["statistics"]["points"],
        # ... all stats fields
    }

# 3. Validation
validate_shooting_stats(record)  # FGM <= FGA
validate_rebounds(record)        # OFF + DEF = TOTAL
validate_points(record)          # Calculate from FG2, 3PT, FT
```

#### Output Schema

**Table:** `nba_raw.nbac_team_boxscore`

**Schema Definition:** `schemas/bigquery/raw/nbac_team_boxscore_tables.sql`

```sql
CREATE TABLE nba_raw.nbac_team_boxscore (
  game_id              STRING NOT NULL,    -- "20250115_PHI_LAL"
  nba_game_id          STRING NOT NULL,    -- "0022400561"
  game_date            DATE NOT NULL,
  season_year          INT64 NOT NULL,
  team_abbr            STRING NOT NULL,    -- "LAL"
  is_home              BOOLEAN NOT NULL,   -- TRUE/FALSE

  -- Shooting
  fg_made              INT64,
  fg_attempted         INT64,
  fg_percentage        FLOAT64,
  three_pt_made        INT64,
  three_pt_attempted   INT64,
  three_pt_percentage  FLOAT64,
  ft_made              INT64,
  ft_attempted         INT64,
  ft_percentage        FLOAT64,

  -- Rebounds
  offensive_rebounds   INT64,
  defensive_rebounds   INT64,
  total_rebounds       INT64,

  -- Other stats
  assists              INT64,
  steals               INT64,
  blocks               INT64,
  turnovers            INT64,
  personal_fouls       INT64,
  points               INT64,
  plus_minus           INT64,

  processed_at         TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY game_id, team_abbr, season_year, is_home;
```

#### Records per Game

**Expected:** Exactly 2 records per game (1 home + 1 away)

#### Processing Strategy

- **Strategy:** MERGE_UPDATE
- **Deduplication:** Game-level (deletes both teams' records, inserts fresh)

---

### 5. NbacGamebookProcessor

**Purpose:** Complete player rosters including inactive players with DNP reasons (critical for availability intelligence)

#### Input Source

- **Phase 1 Scraper:** GetNbaComGamebooks
- **GCS Path:** `gs://nba-scraped-data/nba-com/gamebooks-data/{date}/{game-code}/{timestamp}.json`

#### JSON Structure

```json
{
  "game_id": "20250115_PHI_LAL",
  "game_date": "2025-01-15",
  "game_code": "20250115/PHILAL",
  "teams": {
    "home": {
      "team_code": "LAL",
      "players": [
        {
          "status": "active",
          "number": "23",
          "name": "James",
          "position": "F",
          "minutes": "35:22",
          "points": "28",
          "assists": "7"
          // ... full stats
        },
        {
          "status": "dnp",
          "number": "15",
          "name": "Bryant",
          "position": "G",
          "dnp_reason": "Coach's Decision"
        },
        {
          "status": "inactive",
          "number": "32",
          "name": "Christie",
          "position": "G",
          "dnp_reason": "Injury - Left Knee"
        }
      ]
    },
    "away": { /* same structure */ }
  }
}
```

#### Field Mapping

| BigQuery Field | Source JSON Path | Transformation |
|----------------|------------------|----------------|
| game_id | game_id | Direct copy |
| game_date | game_date | Direct copy |
| team_abbr | teams.home.team_code or teams.away.team_code | Direct copy |
| player_name | Derived | **REQUIRES NAME RESOLUTION** |
| player_name_original | players[].name | Direct copy (e.g., "James") |
| player_lookup | Derived | Normalize resolved name |
| player_status | players[].status | Direct copy ("active", "dnp", "inactive") |
| dnp_reason | players[].dnp_reason | Direct copy or NULL |
| minutes | players[].minutes | Active players only |
| points | players[].points | Active players only |
| name_resolution_status | Derived | "resolved", "multiple_matches", "not_found" |
| name_resolution_confidence | Derived | 0.0-1.0 confidence score |

#### Critical Name Resolution Logic

**Problem:** Inactive players only have last names (e.g., "James")

**Solution:** Multi-source resolution with fallback chain

```python
def resolve_player_name(last_name, team_abbr, game_date, season_year):
    """
    Resolve incomplete player name using multiple sources

    Resolution Chain:
    1. Injury Database (99%+ success via exact game/team/date match)
    2. Basketball Reference Rosters (critical fallback)
    3. NBA.com Player List (current rosters only)
    """

    # Method 1: Injury Database (Primary - 99%+ accuracy)
    query = f"""
        SELECT player_full_name, COUNT(*) as matches
        FROM nba_raw.nbac_injury_report
        WHERE DATE(report_date) = '{game_date}'
          AND team = '{team_abbr}'
          AND LOWER(player_full_name) LIKE '%{last_name.lower()}%'
        GROUP BY player_full_name
    """
    results = execute_query(query)

    if len(results) == 1:
        return {
            "player_full_name": results[0]["player_full_name"],
            "status": "resolved",
            "confidence": 1.0,
            "method": "injury_db_exact"
        }

    # Method 2: Basketball Reference Rosters (Fallback)
    query = f"""
        SELECT player_full_name, COUNT(*) as matches
        FROM nba_raw.br_rosters_current
        WHERE season_year = {season_year}
          AND team_abbrev = '{team_abbr}'
          AND player_last_name = '{last_name}'
    """
    results = execute_query(query)

    if len(results) == 1:
        return {
            "player_full_name": results[0]["player_full_name"],
            "status": "resolved",
            "confidence": 0.95,
            "method": "basketball_ref"
        }
    elif len(results) > 1:
        # Disambiguation needed
        return {
            "player_full_name": None,
            "status": "multiple_matches",
            "confidence": 0.5,
            "method": "basketball_ref",
            "candidates": [r["player_full_name"] for r in results]
        }

    # Method 3: Not Found
    return {
        "player_full_name": None,
        "status": "not_found",
        "confidence": 0.0,
        "method": "none"
    }
```

#### Output Schema

**Table:** `nba_raw.nbac_gamebook_player_stats`

**Schema Definition:** `schemas/bigquery/raw/nbac_player_boxscore_tables.sql`

```sql
CREATE TABLE nba_raw.nbac_gamebook_player_stats (
  game_id              STRING,      -- "20250115_PHI_LAL"
  game_date            DATE,
  season_year          INT64,
  team_abbr            STRING,      -- "LAL"

  -- Player identity
  player_name          STRING,      -- "LeBron James" (resolved)
  player_name_original STRING,      -- "James" (from source)
  player_lookup        STRING,      -- "lebronjames"
  player_status        STRING,      -- "active", "dnp", "inactive"
  dnp_reason           STRING,      -- NULL or reason text

  -- Name resolution tracking
  name_resolution_status      STRING,   -- "resolved", "multiple_matches", "not_found"
  name_resolution_confidence  FLOAT64,  -- 0.0-1.0
  name_resolution_method      STRING,   -- "injury_db_exact", "basketball_ref"

  -- Stats (NULL for inactive players)
  minutes              STRING,
  points               INT64,
  assists              INT64,
  rebounds             INT64,

  processed_at         TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup, game_date, player_status;
```

#### Critical Dependencies

**REQUIRES:**
- `nba_raw.br_rosters_current` (Basketball Reference rosters)
- `nba_raw.nbac_injury_report` (injury database)

Without these tables, name resolution fails

#### Name Resolution Performance

**Current Metrics (September 2025):**
- Overall accuracy: 98.92%
- Injury DB success: 99%+ (primary method)
- Basketball Reference fallback: Critical for edge cases
- Unresolved: 232 cases (0.88%) - mostly legitimate exclusions

#### Processing Strategy

- **Strategy:** MERGE_UPDATE
- **Coverage:** ~30-35 players per game (active + DNP + inactive)

---

### 6. NbacPlayerListProcessor

**Purpose:** Current roster state for all active NBA players (player-team lookup)

#### Input Source

- **Phase 1 Scraper:** GetNbaComPlayerList
- **GCS Path:** `gs://nba-scraped-data/nba-com/player-list/{date}/{timestamp}.json`

#### JSON Structure

```json
{
  "resultSets": [
    {
      "headers": [
        "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION",
        "AGE", "GP", "W", "L", "MIN", "PTS" /* ... 60+ fields */
      ],
      "rowSet": [
        [
          2544, "LeBron James", 1610612747, "LAL",
          40.2, 50, 35, 15, 34.5, 25.2 /* ... */
        ]
      ]
    }
  ]
}
```

#### Field Mapping

| BigQuery Field | Column Index | Transformation |
|----------------|--------------|----------------|
| player_id | 0 | Direct copy (NBA.com player ID) |
| player_full_name | 1 | Direct copy |
| player_lookup | Derived | Normalize: "lebronjames" |
| team_id | 2 | Direct copy |
| team_abbr | 3 | Direct copy |
| age | 4 | Direct copy |
| games_played | 5 | Direct copy |
| minutes_per_game | 8 | Direct copy |
| points_per_game | 9 | Direct copy |

#### Transformation Logic

```python
# NBA.com returns array-based data
headers = json_data["resultSets"][0]["headers"]
rows = json_data["resultSets"][0]["rowSet"]

for row in rows:
    # Map array positions to named fields
    player_id = row[0]
    player_full_name = row[1]
    team_id = row[2]
    team_abbr = row[3]

    # Normalize player name
    parts = player_full_name.split()
    first_name = parts[0]
    last_name = parts[-1]
    player_lookup = f"{first_name.lower()}{last_name.lower()}"

    record = {
        "player_lookup": player_lookup,  # PRIMARY KEY
        "player_id": player_id,
        "player_full_name": player_full_name,
        "team_abbr": team_abbr,
        # ... all fields
    }
```

#### Output Schema

**Table:** `nba_raw.nbac_player_list_current`

**Schema Definition:** `schemas/bigquery/raw/nbac_player_list_tables.sql`

```sql
CREATE TABLE nba_raw.nbac_player_list_current (
  player_lookup     STRING,      -- PRIMARY KEY: "lebronjames"
  player_id         INT64,       -- NBA.com player ID
  player_full_name  STRING,      -- "LeBron James"
  team_id           INT64,
  team_abbr         STRING,      -- "LAL"
  position          STRING,
  age               FLOAT64,
  games_played      INT64,
  points_per_game   FLOAT64,

  last_seen_date    DATE,
  processed_at      TIMESTAMP
)
PARTITION BY RANGE_BUCKET(season_year, GENERATE_ARRAY(2021, 2030, 1))
CLUSTER BY team_abbr, is_active;
```

#### Processing Strategy

- **Strategy:** MERGE_UPDATE
- **Current State Only:** No historical data (always latest roster)
- **Usage:** Critical for player-team lookups in all processors

---

### 7. NbacInjuryReportProcessor

**Purpose:** Track player availability and injury status changes over time

#### Input Source

- **Phase 1 Scraper:** GetNbaComInjuryReport
- **GCS Path:** `gs://nba-scraped-data/nba-com/injury-report-data/{date}/{hour24}/{timestamp}.json`

#### JSON Structure

```json
{
  "report_date": "2025-01-15",
  "report_hour": 17,
  "games": [
    {
      "game_id": "20250115_PHI_LAL",
      "game_date": "2025-01-15",
      "injuries": [
        {
          "team": "LAL",
          "player_name": "Anthony Davis",
          "current_status": "Questionable",
          "reason": "Left ankle sprain",
          "return_date": ""
        }
      ]
    }
  ]
}
```

#### Field Mapping

| BigQuery Field | Source JSON Path | Transformation |
|----------------|------------------|----------------|
| report_date | report_date | Direct copy |
| report_hour | report_hour | Direct copy (0-23) |
| game_id | games[].game_id | Direct copy |
| team | injuries[].team | Direct copy |
| player_full_name | injuries[].player_name | Direct copy |
| player_lookup | Derived | Normalize player name |
| injury_status | injuries[].current_status | Normalize: lowercase |
| reason | injuries[].reason | Direct copy |
| reason_category | Derived | Categorize: "injury", "g_league", "suspension" |

#### Status Normalization

```python
# Normalize injury status
STATUS_MAPPING = {
    "Out": "out",
    "OUT": "out",
    "Questionable": "questionable",
    "QUESTIONABLE": "questionable",
    "Doubtful": "doubtful",
    "Probable": "probable"
}

def normalize_status(raw_status):
    return STATUS_MAPPING.get(raw_status, raw_status.lower())

# Categorize reason
def categorize_reason(reason_text):
    reason_lower = reason_text.lower()

    if "g league" in reason_lower or "g-league" in reason_lower:
        return "g_league"
    elif "suspension" in reason_lower or "suspended" in reason_lower:
        return "suspension"
    elif "personal" in reason_lower:
        return "personal"
    else:
        return "injury"  # Default
```

#### Output Schema

**Table:** `nba_raw.nbac_injury_report`

**Schema Definition:** `schemas/bigquery/raw/nbac_injury_report_tables.sql`

```sql
CREATE TABLE nba_raw.nbac_injury_report (
  report_date          DATE,        -- 2025-01-15
  report_hour          INT64,       -- 17 (5 PM ET)
  season               STRING,
  game_id              STRING,      -- "20250115_PHI_LAL"
  team                 STRING,      -- "LAL"
  player_full_name     STRING,      -- "Anthony Davis"
  player_lookup        STRING,      -- "anthonydavis"
  injury_status        STRING,      -- "questionable" (normalized)
  reason               STRING,      -- "Left ankle sprain"
  reason_category      STRING,      -- "injury"

  source_file_path     STRING,
  processed_at         TIMESTAMP
)
PARTITION BY report_date
CLUSTER BY player_lookup, game_id, injury_status;
```

#### Processing Strategy

- **Strategy:** APPEND_ALWAYS
- **Reason:** Tracks intraday status changes (24 snapshots per day)
- **Peak Hours:** 17:00 ET (5 PM), 20:00 ET (8 PM)

---

## Ball Don't Lie Processors

### 12. BdlBoxscoresProcessor

**Purpose:** Primary source for player game statistics (cross-validation with NBA.com)

#### Input Source

- **Phase 1 Scraper:** BdlBoxScoresScraper
- **GCS Path:** `gs://nba-scraped-data/ball-dont-lie/boxscores/{date}/{timestamp}.json`

#### JSON Structure

```json
{
  "date": "2025-01-15",
  "timestamp": "2025-01-16T04:32:18.123456Z",
  "rowCount": 324,
  "boxScores": [
    {
      "game": {
        "id": 12345,
        "date": "2025-01-15T00:00:00.000Z",
        "season": 2024,
        "status": "Final",
        "home_team": {
          "id": 14,
          "abbreviation": "LAL",
          "full_name": "Los Angeles Lakers"
        },
        "visitor_team": {
          "id": 13,
          "abbreviation": "PHI",
          "full_name": "Philadelphia 76ers"
        }
      },
      "team": {
        "id": 14,
        "abbreviation": "LAL"
      },
      "player": {
        "id": 237,
        "first_name": "LeBron",
        "last_name": "James",
        "position": "F"
      },
      "min": "35:22",
      "pts": 28,
      "ast": 7,
      "reb": 8,
      "fgm": 10,
      "fga": 18,
      "fg3m": 2,
      "fg3a": 6,
      "ftm": 6,
      "fta": 8,
      "plus_minus": 6
    }
  ]
}
```

#### Field Mapping

| BigQuery Field | Source JSON Path | Transformation |
|----------------|------------------|----------------|
| game_id | Derived | Construct from date + teams |
| game_date | game.date | Parse date component |
| season_year | game.season | Direct copy |
| team_abbr | team.abbreviation | Direct copy |
| player_full_name | Derived | Combine first_name + last_name |
| player_lookup | Derived | Normalize: lebronjames |
| bdl_player_id | player.id | Direct copy |
| minutes | min | Direct copy as STRING |
| points | pts | Direct copy |
| assists | ast | Direct copy |
| rebounds | reb | Direct copy |
| field_goals_made | fgm | Direct copy |
| three_pointers_made | fg3m | Direct copy |

#### Transformation Logic

```python
# 1. Construct standardized game_id
game_date = parse_date(box_score["game"]["date"])
home_team = box_score["game"]["home_team"]["abbreviation"]
away_team = box_score["game"]["visitor_team"]["abbreviation"]

game_id = f"{game_date.strftime('%Y%m%d')}_{away_team}_{home_team}"
# Result: "20250115_PHI_LAL"

# 2. Player name normalization
player = box_score["player"]
first_name = player["first_name"]
last_name = player["last_name"]

player_full_name = f"{first_name} {last_name}"
player_lookup = f"{first_name.lower()}{last_name.lower()}"
# Result: "lebronjames"

# 3. Team determination
team_abbr = box_score["team"]["abbreviation"]

record = {
    "game_id": game_id,
    "game_date": game_date,
    "player_full_name": player_full_name,
    "player_lookup": player_lookup,
    "team_abbr": team_abbr,
    "points": box_score["pts"],
    "minutes": box_score["min"],
    # ... all stats
}
```

#### Output Schema

**Table:** `nba_raw.bdl_player_boxscores`

**Schema Definition:** `schemas/bigquery/raw/bdl_boxscores_tables.sql`

```sql
CREATE TABLE nba_raw.bdl_player_boxscores (
  game_id              STRING,      -- "20250115_PHI_LAL"
  game_date            DATE,        -- 2025-01-15
  season_year          INT64,       -- 2024
  team_abbr            STRING,      -- "LAL"

  -- Player identity
  player_full_name     STRING,      -- "LeBron James"
  player_lookup        STRING,      -- "lebronjames"
  bdl_player_id        INT64,       -- 237

  -- Playing time
  minutes              STRING,      -- "35:22"

  -- Scoring
  points               INT64,       -- 28 ⭐ CRITICAL FOR PROPS
  field_goals_made     INT64,       -- 10
  field_goals_attempted INT64,      -- 18
  three_pointers_made  INT64,       -- 2
  three_pointers_attempted INT64,   -- 6
  free_throws_made     INT64,       -- 6
  free_throws_attempted INT64,      -- 8

  -- Other stats
  assists              INT64,       -- 7
  rebounds             INT64,       -- 8
  steals               INT64,
  blocks               INT64,
  turnovers            INT64,
  plus_minus           INT64,       -- 6

  processed_at         TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr, game_date;
```

#### Key Differences from NBA.com Gamebooks

| Aspect | BDL Box Scores | NBA.com Gamebooks |
|--------|----------------|-------------------|
| Players included | Active players only | Active + DNP + Inactive |
| Name format | Full names (first + last) | Last names only (inactive) |
| Name resolution | Not needed | Critical (98.92% accuracy) |
| Availability | Immediate post-game | ~2 hours post-game |
| DNP reasons | Not included | Includes DNP reasons |
| Stats coverage | Standard box score | Standard box score |

#### Processing Strategy

- **Strategy:** MERGE_UPDATE
- **Coverage:** ~165,070 player-game records (4 complete seasons)
- **Primary Use:** Settlement source for prop bets

---

### 13. BdlActivePlayersProcessor

**Purpose:** Cross-validate player-team assignments against NBA.com

#### Input Source

- **Phase 1 Scraper:** BdlActivePlayersScraper
- **GCS Path:** `gs://nba-scraped-data/ball-dont-lie/active-players/{date}/{timestamp}.json`

#### JSON Structure

```json
{
  "date": "2025-01-15",
  "timestamp": "2025-01-15T14:22:00.000000Z",
  "playerCount": 542,
  "players": [
    {
      "id": 237,
      "first_name": "LeBron",
      "last_name": "James",
      "position": "F",
      "height": "6-9",
      "weight": "250",
      "team": {
        "id": 14,
        "abbreviation": "LAL",
        "full_name": "Los Angeles Lakers",
        "conference": "West",
        "division": "Pacific"
      }
    }
  ]
}
```

#### Field Mapping & Validation

```python
# Extract from BDL
bdl_player = {
    "player_lookup": normalize_name(player["first_name"], player["last_name"]),
    "team_abbr": player["team"]["abbreviation"]
}

# Cross-validate with NBA.com
nba_player = query_nba_com_player_list(bdl_player["player_lookup"])

if nba_player:
    if bdl_player["team_abbr"] == nba_player["team_abbr"]:
        validation_status = "validated"
    else:
        validation_status = "team_mismatch"
        validation_details = f"BDL: {bdl_player['team_abbr']}, NBA.com: {nba_player['team_abbr']}"
else:
    validation_status = "missing_nba_com"

record = {
    **bdl_player,
    "validation_status": validation_status,
    "validation_details": validation_details if validation_status != "validated" else None,
    "nba_com_team_abbr": nba_player["team_abbr"] if nba_player else None
}
```

#### Output Schema

**Table:** `nba_raw.bdl_active_players_current`

**Schema Definition:** `schemas/bigquery/raw/bdl_active_players_tables.sql`

```sql
CREATE TABLE nba_raw.bdl_active_players_current (
  player_lookup            STRING,      -- PRIMARY KEY: "lebronjames"
  bdl_player_id            INT64,
  player_full_name         STRING,
  team_abbr                STRING,      -- BDL team
  position                 STRING,

  -- Cross-validation
  has_validation_issues    BOOLEAN,
  validation_status        STRING,      -- "validated", "team_mismatch", "missing_nba_com"
  validation_details       STRING,      -- JSON with mismatch details
  nba_com_team_abbr        STRING,      -- NBA.com team (for comparison)

  last_seen_date           DATE,
  processed_at             TIMESTAMP
)
CLUSTER BY team_abbr, has_validation_issues, validation_status;
```

#### Validation Results (Typical)

| Status | Count | Percentage | Description |
|--------|-------|------------|-------------|
| validated | ~352 | 61.9% | Teams match across sources |
| team_mismatch | ~89 | 15.6% | Different teams (trade lag) |
| missing_nba_com | ~128 | 22.5% | Not in NBA.com list |

**Note:** 60%+ validation rate is healthy - differences often due to recent trades or two-way contracts

#### Processing Strategy

- **Strategy:** MERGE_UPDATE
- **Current State Only:** No historical tracking

---

## ESPN Processors

### 18. EspnScoreboardProcessor

**Purpose:** Backup validation source for final game scores

#### Input Source

- **Phase 1 Scraper:** EspnScoreboard
- **GCS Path:** `gs://nba-scraped-data/espn/scoreboard/{date}/{timestamp}.json`

#### JSON Structure

```json
{
  "events": [
    {
      "id": "401692583",
      "date": "2025-01-15T23:00Z",
      "competitions": [
        {
          "competitors": [
            {
              "id": "13",
              "team": {
                "abbreviation": "PHI",
                "displayName": "Philadelphia 76ers"
              },
              "score": "112",
              "homeAway": "away"
            },
            {
              "id": "14",
              "team": {
                "abbreviation": "LAL",
                "displayName": "Los Angeles Lakers"
              },
              "score": "118",
              "homeAway": "home"
            }
          ],
          "status": {
            "type": {
              "id": "3",
              "description": "Final"
            }
          }
        }
      ]
    }
  ]
}
```

#### Critical Team Mapping

ESPN uses non-standard abbreviations that must be normalized:

```python
ESPN_TEAM_MAPPING = {
    "NY": "NYK",    # New York Knicks
    "GS": "GSW",    # Golden State Warriors
    "SA": "SAS",    # San Antonio Spurs
    "NO": "NOP",    # New Orleans Pelicans
}

def normalize_espn_team(espn_abbr):
    return ESPN_TEAM_MAPPING.get(espn_abbr, espn_abbr)
```

#### Field Mapping

| BigQuery Field | Source JSON Path | Transformation |
|----------------|------------------|----------------|
| game_id | Derived | Construct from date + normalized teams |
| espn_game_id | id | Direct copy: "401692583" |
| game_date | date | Parse date component |
| home_team_abbr | competitors[].team.abbreviation | **NORMALIZE** via mapping |
| away_team_abbr | competitors[].team.abbreviation | **NORMALIZE** via mapping |
| home_team_espn_abbr | competitors[].team.abbreviation | Store original ESPN code |
| away_team_espn_abbr | competitors[].team.abbreviation | Store original ESPN code |
| home_team_score | competitors[].score | Parse to INT64 |
| away_team_score | competitors[].score | Parse to INT64 |
| game_status | status.type.description | Normalize: "final", "scheduled" |

#### Transformation Logic

```python
# Identify home/away teams
competitors = event["competitions"][0]["competitors"]

home_team = [c for c in competitors if c["homeAway"] == "home"][0]
away_team = [c for c in competitors if c["homeAway"] == "away"][0]

# Extract ESPN abbreviations
home_espn_abbr = home_team["team"]["abbreviation"]  # May be "NY", "GS"
away_espn_abbr = away_team["team"]["abbreviation"]

# Normalize to standard codes
home_team_abbr = normalize_espn_team(home_espn_abbr)  # "NY" → "NYK"
away_team_abbr = normalize_espn_team(away_espn_abbr)  # "GS" → "GSW"

# Construct game_id with normalized teams
game_date = parse_date(event["date"])
game_id = f"{game_date.strftime('%Y%m%d')}_{away_team_abbr}_{home_team_abbr}"

record = {
    "game_id": game_id,
    "espn_game_id": event["id"],
    "home_team_abbr": home_team_abbr,           # Normalized: "NYK"
    "away_team_abbr": away_team_abbr,           # Normalized: "GSW"
    "home_team_espn_abbr": home_espn_abbr,      # Original: "NY"
    "away_team_espn_abbr": away_espn_abbr,      # Original: "GS"
    "home_team_score": int(home_team["score"]),
    "away_team_score": int(away_team["score"]),
}
```

#### Output Schema

**Table:** `nba_raw.espn_scoreboard`

**Schema Definition:** `schemas/bigquery/raw/espn_scoreboard_tables.sql`

```sql
CREATE TABLE nba_raw.espn_scoreboard (
  game_id                STRING,      -- "20250115_PHI_LAL"
  espn_game_id          STRING,      -- "401692583"
  game_date             DATE,

  -- Normalized teams (for joins)
  home_team_abbr        STRING,      -- "NYK", "GSW", "SAS"
  away_team_abbr        STRING,      -- Standard codes

  -- Original ESPN teams (for reference)
  home_team_espn_abbr   STRING,      -- "NY", "GS", "SA"
  away_team_espn_abbr   STRING,      -- As ESPN provides

  home_team_score       INT64,
  away_team_score       INT64,
  game_status           STRING,

  processed_at          TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY home_team_abbr, away_team_abbr, game_status;
```

#### Processing Strategy

- **Strategy:** MERGE_UPDATE
- **Usage:** Backup validation in Early Morning Final Check workflow

---

## BigDataBall Processors

### 17. BigDataBallPbpProcessor

**Purpose:** Most detailed play-by-play available with shot coordinates and complete lineups

#### Input Source

- **Phase 1 Scraper:** BigDataBallPbpScraper
- **GCS Path:** `gs://nba-scraped-data/big-data-ball/{season}/{date}/game_{id}/{filename}.csv`

#### CSV Structure

```csv
game_id,event_num,event_type,player_1,shot_made,shot_type,original_x,original_y,away_player_1,away_player_2,away_player_3,away_player_4,away_player_5,home_player_1,home_player_2,home_player_3,home_player_4,home_player_5,game_clock,period,home_score,away_score
0022400561,1,shot,LeBron James,1,Pullup Jump Shot,15,10,Joel Embiid,Tyrese Maxey,Kelly Oubre Jr.,Tobias Harris,De'Anthony Melton,LeBron James,Anthony Davis,Austin Reaves,D'Angelo Russell,Rui Hachimura,11:45,1,2,0
```

#### Field Mapping

| BigQuery Field | CSV Column | Transformation |
|----------------|------------|----------------|
| game_id | game_id | Map NBA.com ID → standard format |
| game_date | From path | Extract from GCS path |
| event_sequence | event_num | Direct copy |
| event_type | event_type | Direct copy: "shot", "foul", "rebound" |
| player_1_name | player_1 | Direct copy |
| player_1_lookup | Derived | Normalize player name |
| shot_made | shot_made | Convert to BOOLEAN (1=TRUE, 0=FALSE) |
| shot_type | shot_type | Direct copy: "Pullup Jump Shot" |
| original_x | original_x | Direct copy as FLOAT64 |
| original_y | original_y | Direct copy as FLOAT64 |
| away_player_1_lookup | away_player_1 | Normalize: complete 5-man lineup |
| away_player_2_lookup | away_player_2 | Normalize |
| ... | ... | All 5 away players |
| home_player_1_lookup | home_player_1 | Normalize: complete 5-man lineup |
| ... | ... | All 5 home players |

#### Unique Features

**Shot Coordinates:** X, Y positioning for spatial analysis

```python
# Shot coordinates (feet from basket)
shot_x = 15.0  # Lateral position
shot_y = 10.0  # Distance from basket

# Can calculate:
# - Shot charts
# - Hot zones
# - Defender proximity
```

**Complete 5-Man Lineups:** Every possession

```python
away_lineup = [
    "joelembiid",
    "tyresemaxey",
    "kellyoubrejr",
    "tobiasharris",
    "deanthonymelton"
]

home_lineup = [
    "lebronjames",
    "anthonydavis",
    "austinreaves",
    "dangelorussel",
    "ruihachimura"
]

# Can analyze:
# - Lineup efficiency
# - Plus/minus by lineup
# - Matchup advantages
```

#### Transformation Logic

```python
# 1. Parse CSV (special handling needed)
# BigDataBall wraps data in JSON-like structure
import pandas as pd

df = pd.read_csv(gcs_path)

# 2. Convert NBA.com game ID to standard format
nba_game_id = df.iloc[0]["game_id"]  # "0022400561"
game_id = convert_nba_game_id_to_standard(nba_game_id)

# 3. Normalize all player names in lineups
for col in ["away_player_1", "away_player_2", "away_player_3",
            "away_player_4", "away_player_5",
            "home_player_1", "home_player_2", "home_player_3",
            "home_player_4", "home_player_5"]:
    df[f"{col}_lookup"] = df[col].apply(normalize_player_name)

# 4. Convert shot_made to boolean
df["shot_made"] = df["shot_made"].astype(bool)

# 5. Extract game_date from path
# Path: .../2024-25/2025-01-15/game_0022400561/...
game_date = extract_date_from_path(gcs_path)

records = []
for _, row in df.iterrows():
    record = {
        "game_id": game_id,
        "game_date": game_date,
        "event_sequence": row["event_num"],
        "event_type": row["event_type"],
        "player_1_lookup": normalize_player_name(row["player_1"]),
        "shot_made": row["shot_made"],
        "original_x": row["original_x"],
        "original_y": row["original_y"],
        "away_player_1_lookup": row["away_player_1_lookup"],
        # ... all 10 lineup positions
    }
    records.append(record)
```

#### Output Schema

**Table:** `nba_raw.bigdataball_play_by_play`

**Schema Definition:** `schemas/bigquery/raw/bigdataball_tables.sql`

```sql
CREATE TABLE nba_raw.bigdataball_play_by_play (
  game_id              STRING,      -- "20250115_PHI_LAL"
  game_date            DATE,
  season_year          INT64,
  event_sequence       INT64,

  -- Event details
  event_type           STRING,      -- "shot", "foul", "rebound"
  event_description    STRING,
  player_1_lookup      STRING,      -- Primary player

  -- Shot data
  shot_made            BOOLEAN,
  shot_type            STRING,      -- "Pullup Jump Shot"
  original_x           FLOAT64,     -- Shot coordinate X
  original_y           FLOAT64,     -- Shot coordinate Y

  -- Complete lineups (10 players)
  away_player_1_lookup STRING,
  away_player_2_lookup STRING,
  away_player_3_lookup STRING,
  away_player_4_lookup STRING,
  away_player_5_lookup STRING,
  home_player_1_lookup STRING,
  home_player_2_lookup STRING,
  home_player_3_lookup STRING,
  home_player_4_lookup STRING,
  home_player_5_lookup STRING,

  -- Timing
  game_clock           STRING,
  period               INT64,

  processed_at         TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr, game_date;
```

#### Data Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Total events | 566,034 | All play-by-play |
| Games covered | 1,211 | Complete 2024-25 |
| Events per game | ~400-500 | Very detailed |
| Update lag | ~2 hours | Post-game release |

#### Processing Strategy

- **Strategy:** MERGE_UPDATE with streaming-compatible deduplication
- **Critical:** Prevents BigQuery streaming buffer conflicts

---

## Basketball Reference Processors

### 21. BasketballRefRosterProcessor

**Purpose:** **CRITICAL DEPENDENCY** for gamebook name resolution

#### Input Source

- **Phase 1 Scraper:** BasketballRefSeasonRoster
- **GCS Path:** `gs://nba-scraped-data/basketball-ref/season-rosters/{season}/{team}.json`

#### JSON Structure

```json
{
  "season": "2024-25",
  "team": "LAL",
  "roster": [
    {
      "player_name": "LeBron James",
      "position": "F",
      "height": "6-9",
      "weight": 250,
      "birth_date": "1984-12-30",
      "experience": "21",
      "college": "St. Vincent-St. Mary HS (OH)"
    }
  ]
}
```

#### Field Mapping

| BigQuery Field | Source JSON Path | Transformation |
|----------------|------------------|----------------|
| season_year | season | Parse starting year: 2024 |
| season_display | season | Direct copy: "2024-25" |
| team_abbrev | team | Direct copy: "LAL" |
| player_full_name | roster[].player_name | Direct copy |
| player_last_name | Derived | Extract last name for matching |
| player_lookup | Derived | Normalize: "lebronjames" |
| position | roster[].position | Direct copy |
| height | roster[].height | Direct copy |
| weight | roster[].weight | Direct copy |

#### Critical Usage: Name Resolution

```python
# Gamebook processor needs this table
def resolve_incomplete_name(last_name, team, season_year):
    """
    Gamebooks only have last names for inactive players
    Example: "James" on "LAL" in 2024 season
    """
    query = f"""
        SELECT player_full_name, COUNT(*) as matches
        FROM nba_raw.br_rosters_current
        WHERE season_year = {season_year}
          AND team_abbrev = '{team}'
          AND player_last_name = '{last_name}'
        GROUP BY player_full_name
    """

    results = execute_query(query)

    if len(results) == 1:
        # Unique match found
        return results[0]["player_full_name"]  # "LeBron James"
    elif len(results) > 1:
        # Multiple players with same last name (e.g., "Davis")
        # Need disambiguation logic
        return None
    else:
        # Not found
        return None
```

#### Output Schema

**Table:** `nba_raw.br_rosters_current`

**Schema Definition:** `schemas/bigquery/raw/br_roster_tables.sql`

```sql
CREATE TABLE nba_raw.br_rosters_current (
  season_year         INT64,       -- 2024
  season_display      STRING,      -- "2024-25"
  team_abbrev         STRING,      -- "LAL"

  -- Player identity
  player_full_name    STRING,      -- "LeBron James"
  player_last_name    STRING,      -- "James" (for matching)
  player_normalized   STRING,      -- "lebron james" (lowercase with spaces)
  player_lookup       STRING,      -- "lebronjames"

  -- Player details
  position            STRING,
  jersey_number       STRING,
  height              STRING,
  weight              STRING,
  birth_date          STRING,
  college             STRING,
  experience_years    INT64,

  processed_at        TIMESTAMP
)
PARTITION BY RANGE_BUCKET(season_year, GENERATE_ARRAY(2021, 2030, 1))
CLUSTER BY team_abbrev, player_lookup;
```

#### Multi-Team Players

**Important:** Players appear on multiple teams if they:
- Were traded mid-season
- Signed with new team after waiver
- Had 10-day contracts with multiple teams

This is intentional and correct - shows historical team assignments for that season.

#### Processing Strategy

- **Strategy:** MERGE_UPDATE
- **Scope:** Historical season rosters (2021-2025)
- **Update Frequency:** Quarterly during season
- **CRITICAL:** Must be populated before processing gamebooks

---

## Summary

### Phase 2 Transformation Pipeline

```
GCS JSON Files
    ↓
[Read & Parse JSON/CSV]
    ↓
[Apply Transformations]
  • Standardize game_id
  • Normalize player_lookup
  • Map team abbreviations
  • Convert data types
  • Enrich with lookups
    ↓
[Validate Data Quality]
  • Check required fields
  • Validate ranges
  • Cross-source validation
    ↓
[Write to BigQuery]
  • Apply processing strategy
  • Handle deduplication
  • Track metadata
    ↓
BigQuery Raw Tables (nba_raw.*)
    ↓
Phase 3 Analytics
```

### Common Transformation Summary

| Transformation | Input Format | Output Format | Purpose |
|----------------|--------------|---------------|---------|
| Game ID | Various (BDL ID, NBA.com code, Odds event) | YYYYMMDD_AWAY_HOME | Universal join key |
| Player Name | Various (full, split, last only) | {firstname}{lastname} | Universal player ID |
| Team Code | ESPN codes, full names | Standard 3-letter | Consistent team IDs |
| Odds Format | Decimal or American | Both formats | Analysis flexibility |
| Timestamps | Various ISO formats | BigQuery TIMESTAMP | Consistent timing |

### Critical Processing Strategies

| Strategy | Processors | Key Characteristic |
|----------|-----------|-------------------|
| APPEND_ALWAYS | 5 | Preserves all snapshots (props, injuries) |
| MERGE_UPDATE | 14 | Replaces game-level data |
| INSERT_NEW_ONLY | 1 | Historical transactions only |

### Data Quality Validations

All processors implement:

- ✅ Required field checks
- ✅ Data type validation
- ✅ Range validations (scores, percentages)
- ✅ Referential integrity (game IDs exist in schedule)
- ✅ Cross-source validation where applicable

---

## Related Documentation

- **Phase 1 Outputs:** `docs/data-flow/01-phase1-scraper-outputs.md` - What Phase 1 collects
- **BigQuery Schemas:** `schemas/bigquery/raw/` - Table definitions
- **Phase 3 Mappings:** `docs/data-flow/03-phase2-to-phase3-*.md` - Analytics transformations
- **Orchestration:** `docs/orchestration/` - Scraper scheduling and workflows

---

**Document Version:** 1.0
**Last Updated:** 2025-11-15
**Status:** Current
