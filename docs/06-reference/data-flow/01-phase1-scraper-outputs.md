# Phase 1 Scraper Outputs: External APIs → JSON/GCS

**File:** `docs/data-flow/01-phase1-scraper-outputs.md`
**Created:** 2025-11-08
**Last Updated:** 2025-11-15
**Purpose:** Document which fields each scraper retrieves from external APIs and how data is stored in GCS
**Audience:** Engineers building Phase 2 processors and understanding data collection
**Status:** Current

---

## Table of Contents

1. [Overview](#overview)
2. [Ball Don't Lie API Scrapers](#ball-dont-lie-api-scrapers)
3. [Odds API Scrapers](#odds-api-scrapers)
4. [NBA.com Scrapers](#nbacom-scrapers)
5. [ESPN Scrapers](#espn-scrapers)
6. [Basketball Reference Scrapers](#basketball-reference-scrapers)
7. [BettingPros Scrapers](#bettingpros-scrapers)
8. [BigDataBall Scrapers](#bigdataball-scrapers)
9. [Orchestration Summary](#orchestration-summary)
10. [GCS Storage Patterns](#gcs-storage-patterns)

---

## Overview

### Data Collection Architecture

```
External APIs (7 sources)
    ↓
Phase 1: Scrapers (26 scrapers)
    ↓ [HTTP GET requests]
    ↓ [Rate limiting + retries]
    ↓ [Validation]
    ↓
GCS Storage (gs://nba-scraped-data/)
    ↓ [Pub/Sub message trigger]
    ↓
Phase 2: Processors
    ↓
BigQuery Raw Tables (nba_raw.*)
```

### Scraper Summary by Source

| Data Source | Scrapers | Update Frequency | Primary Purpose |
|-------------|----------|------------------|-----------------|
| Ball Don't Lie | 4 | Post-game, every 2 hours | Player/team statistics |
| Odds API | 6 | 15 min snapshots (game days) | Betting lines (props + games) |
| NBA.com | 9 | Varies (hourly to daily) | Official statistics & schedules |
| ESPN | 3 | Post-game | Backup statistics |
| Basketball Reference | 1 | Quarterly (backfill) | Name resolution support |
| BettingPros | 2 | Daily | Backup betting lines |
| BigDataBall | 1 | ~2 hours post-game | Enhanced play-by-play |
| **Total** | **26** | **Various** | **Complete data coverage** |

### Common Scraper Characteristics

All scrapers implement:

- ✅ Rate limiting and retry logic
- ✅ HTTP timeout handling
- ✅ Response validation
- ✅ GCS storage with timestamps
- ✅ Pub/Sub trigger messages
- ✅ Error notification system
- ✅ Pagination support (where needed)

**Export Modes:**
- **RAW:** Unmodified API response
- **DECODED:** Parsed JSON
- **DATA:** Transformed/enriched payload

---

## Ball Don't Lie API Scrapers

### Overview

- **API Base:** https://api.balldontlie.io/v1/
- **Authentication:** Bearer token (BDL_API_KEY)
- **Rate Limit:** ~60 requests/minute
- **Pagination:** Cursor-based (100 items per page)

---

### BdlBoxScoresScraper

**File:** `scrapers/balldontlie/bdl_box_scores.py`
**Endpoint:** `GET /v1/box_scores?date={YYYY-MM-DD}&per_page=100`
**Purpose:** Collect player box score statistics for completed games
**Update Frequency:** Post-game (~2 hours after game ends) + daily backfill
**Default Date:** Yesterday (UTC)

#### API Response Structure

```json
{
  "data": [
    {
      "game": {
        "id": 12345,
        "date": "2025-01-15T00:00:00.000Z",
        "season": 2024,
        "status": "Final",
        "home_team_id": 14,
        "visitor_team_id": 13,
        "home_team_score": 118,
        "visitor_team_score": 112,
        "home_team": {
          "id": 14,
          "conference": "West",
          "division": "Pacific",
          "city": "Los Angeles",
          "name": "Lakers",
          "full_name": "Los Angeles Lakers",
          "abbreviation": "LAL"
        },
        "visitor_team": {
          "id": 13,
          "conference": "East",
          "division": "Atlantic",
          "city": "Philadelphia",
          "name": "76ers",
          "full_name": "Philadelphia 76ers",
          "abbreviation": "PHI"
        }
      },
      "team": {
        "id": 14,
        "conference": "West",
        "division": "Pacific",
        "city": "Los Angeles",
        "name": "Lakers",
        "full_name": "Los Angeles Lakers",
        "abbreviation": "LAL"
      },
      "player": {
        "id": 237,
        "first_name": "LeBron",
        "last_name": "James",
        "position": "F",
        "height": "6-9",
        "weight": "250",
        "jersey_number": "23"
      },
      "min": "35:22",
      "fgm": 10,
      "fga": 18,
      "fg_pct": 0.556,
      "fg3m": 2,
      "fg3a": 6,
      "fg3_pct": 0.333,
      "ftm": 6,
      "fta": 8,
      "ft_pct": 0.750,
      "oreb": 1,
      "dreb": 7,
      "reb": 8,
      "ast": 7,
      "stl": 2,
      "blk": 1,
      "turnover": 3,
      "pf": 2,
      "pts": 28,
      "plus_minus": 6
    }
  ],
  "meta": {
    "next_cursor": "eyJnYW1lX2lkIjoxMjM0NX0=",
    "per_page": 100
  }
}
```

#### Fields Retrieved (47 fields per player-game)

| Field Path | Type | Description | Example |
|------------|------|-------------|---------|
| **Game Identifiers** | | | |
| game.id | INT64 | BDL game identifier | 12345 |
| game.date | STRING | Game date ISO format | "2025-01-15T00:00:00.000Z" |
| game.season | INT64 | NBA season year | 2024 |
| game.status | STRING | Game status | "Final" |
| **Score** | | | |
| game.home_team_score | INT64 | Home team final score | 118 |
| game.visitor_team_score | INT64 | Away team final score | 112 |
| **Home Team** | | | |
| game.home_team.id | INT64 | Home team BDL ID | 14 |
| game.home_team.full_name | STRING | Home team full name | "Los Angeles Lakers" |
| game.home_team.abbreviation | STRING | Home team code | "LAL" |
| game.home_team.conference | STRING | Conference | "West" |
| game.home_team.division | STRING | Division | "Pacific" |
| **Away Team** | | | |
| game.visitor_team.id | INT64 | Away team BDL ID | 13 |
| game.visitor_team.full_name | STRING | Away team full name | "Philadelphia 76ers" |
| game.visitor_team.abbreviation | STRING | Away team code | "PHI" |
| game.visitor_team.conference | STRING | Conference | "East" |
| game.visitor_team.division | STRING | Division | "Atlantic" |
| **Player Team** | | | |
| team.id | INT64 | Player's team BDL ID | 14 |
| team.abbreviation | STRING | Player's team code | "LAL" |
| **Player Identity** | | | |
| player.id | INT64 | BDL player identifier | 237 |
| player.first_name | STRING | Player first name | "LeBron" |
| player.last_name | STRING | Player last name | "James" |
| player.position | STRING | Position | "F" |
| player.height | STRING | Height | "6-9" |
| player.weight | STRING | Weight in lbs | "250" |
| player.jersey_number | STRING | Jersey number | "23" |
| **Statistics** | | | |
| min | STRING | Minutes played | "35:22" |
| fgm | INT64 | Field goals made | 10 |
| fga | INT64 | Field goals attempted | 18 |
| fg_pct | FLOAT64 | Field goal percentage | 0.556 |
| fg3m | INT64 | Three-pointers made | 2 |
| fg3a | INT64 | Three-pointers attempted | 6 |
| fg3_pct | FLOAT64 | Three-point percentage | 0.333 |
| ftm | INT64 | Free throws made | 6 |
| fta | INT64 | Free throws attempted | 8 |
| ft_pct | FLOAT64 | Free throw percentage | 0.750 |
| oreb | INT64 | Offensive rebounds | 1 |
| dreb | INT64 | Defensive rebounds | 7 |
| reb | INT64 | Total rebounds | 8 |
| ast | INT64 | Assists | 7 |
| stl | INT64 | Steals | 2 |
| blk | INT64 | Blocks | 1 |
| turnover | INT64 | Turnovers | 3 |
| pf | INT64 | Personal fouls | 2 |
| pts | INT64 | Points scored | 28 |
| plus_minus | INT64 | Plus/minus | 6 |

#### Transformed Output Structure

```json
{
  "date": "2025-01-15",
  "timestamp": "2025-01-16T04:32:18.123456Z",
  "rowCount": 324,
  "boxScores": [
    {
      "game": { /* full game object */ },
      "team": { /* player's team object */ },
      "player": { /* player identity */ },
      "min": "35:22",
      "pts": 28
      /* ... all stats ... */
    }
  ]
}
```

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/ball-dont-lie/boxscores/{date}/{timestamp}.json`

**Example Path:**
```
gs://nba-scraped-data/ball-dont-lie/boxscores/2025-01-15/2025-01-16T04:32:18.123456Z.json
```

**Storage Characteristics:**
- **Format:** JSON
- **Size:** ~50-150 KB per file (varies by number of games)
- **Retention:** Permanent
- **Partitioning:** By date directory

#### Data Quality Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Coverage | ~5,400 games (4 seasons) | Complete regular + playoffs |
| Records per game | ~30-35 active players | Only players who played |
| Update lag | ~2 hours post-game | API availability dependent |
| Completeness | 99%+ | Very reliable |
| Historical backfill | 2021-2025 complete | Full 4 seasons available |

**Quality Alerts:**
- ⚠️ Zero rows: Off-days or future dates (normal)
- ⚠️ <50 rows: Partial data or few games (warning sent)
- ✅ 100+ rows: Normal game day

#### Next Phase

**Phase 2 Processor:** BdlBoxscoresProcessor
**Output Table:** `nba_raw.bdl_player_boxscores`
**Transformation:**
- Standardizes game_id → YYYYMMDD_AWAY_HOME
- Creates player_lookup → {firstname}{lastname}
- Normalizes team abbreviations
- Converts minutes string to INT64 seconds

---

### BdlActivePlayersScraper

**File:** `scrapers/balldontlie/bdl_active_players.py`
**Endpoint:** `GET /v1/players?per_page=100&active=true`
**Purpose:** Current roster of all active NBA players
**Update Frequency:** Every 2 hours during season
**Pagination:** 5-6 requests to fetch ~500 players

#### API Response Structure

```json
{
  "data": [
    {
      "id": 237,
      "first_name": "LeBron",
      "last_name": "James",
      "position": "F",
      "height": "6-9",
      "weight": "250",
      "jersey_number": "23",
      "college": "St. Vincent-St. Mary HS (OH)",
      "country": "USA",
      "draft_year": 2003,
      "draft_round": 1,
      "draft_number": 1,
      "team": {
        "id": 14,
        "conference": "West",
        "division": "Pacific",
        "city": "Los Angeles",
        "name": "Lakers",
        "full_name": "Los Angeles Lakers",
        "abbreviation": "LAL"
      }
    }
  ],
  "meta": {
    "next_cursor": "eyJwbGF5ZXJfaWQiOjIzN30=",
    "per_page": 100
  }
}
```

#### Fields Retrieved (18 fields per player)

| Field Path | Type | Description | Example |
|------------|------|-------------|---------|
| id | INT64 | BDL player identifier | 237 |
| first_name | STRING | Player first name | "LeBron" |
| last_name | STRING | Player last name | "James" |
| position | STRING | Position abbreviation | "F" |
| height | STRING | Height (feet-inches) | "6-9" |
| weight | STRING | Weight in pounds | "250" |
| jersey_number | STRING | Current jersey number | "23" |
| college | STRING | College/high school | "St. Vincent-St. Mary HS (OH)" |
| country | STRING | Country of origin | "USA" |
| draft_year | INT64 | Draft year | 2003 |
| draft_round | INT64 | Draft round | 1 |
| draft_number | INT64 | Draft pick number | 1 |
| team.id | INT64 | Current team BDL ID | 14 |
| team.full_name | STRING | Current team name | "Los Angeles Lakers" |
| team.abbreviation | STRING | Current team code | "LAL" |
| team.conference | STRING | Team conference | "West" |
| team.division | STRING | Team division | "Pacific" |
| team.city | STRING | Team city | "Los Angeles" |

#### Transformed Output Structure

```json
{
  "date": "2025-01-15",
  "timestamp": "2025-01-15T14:22:00.000000Z",
  "playerCount": 542,
  "players": [
    {
      "id": 237,
      "first_name": "LeBron",
      "last_name": "James"
      /* ... all fields ... */
    }
  ]
}
```

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/ball-dont-lie/active-players/{date}/{timestamp}.json`

**Example:**
```
gs://nba-scraped-data/ball-dont-lie/active-players/2025-01-15/2025-01-15T14:22:00.000000Z.json
```

#### Data Quality Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Player count | ~500-600 | Full active rosters |
| Update lag | Real-time | API updated quickly |
| Completeness | 100% | All active players |
| Validation rate | 60%+ vs NBA.com | Expected healthy rate |

#### Next Phase

**Phase 2 Processor:** BdlActivePlayersProcessor
**Output Table:** `nba_raw.bdl_active_players_current`
**Usage:** Cross-validate player-team assignments with NBA.com data

---

### BdlInjuriesScraper

**File:** `scrapers/balldontlie/bdl_injuries.py`
**Endpoint:** `GET /v1/injuries?per_page=100`
**Purpose:** Current injury report for all players
**Update Frequency:** Every 2 hours during season

#### API Response Structure

```json
{
  "data": [
    {
      "id": 12345,
      "player_id": 237,
      "player_name": "LeBron James",
      "team_id": 14,
      "team_abbreviation": "LAL",
      "status": "Day-To-Day",
      "description": "Left ankle sprain",
      "created_at": "2025-01-14T18:00:00.000Z",
      "updated_at": "2025-01-15T12:00:00.000Z"
    }
  ],
  "meta": {
    "next_cursor": null,
    "per_page": 100
  }
}
```

#### Fields Retrieved (10 fields per injury)

| Field Path | Type | Description | Example |
|------------|------|-------------|---------|
| id | INT64 | Injury record ID | 12345 |
| player_id | INT64 | BDL player ID | 237 |
| player_name | STRING | Player full name | "LeBron James" |
| team_id | INT64 | Team BDL ID | 14 |
| team_abbreviation | STRING | Team code | "LAL" |
| status | STRING | Injury status | "Day-To-Day", "Out" |
| description | STRING | Injury description | "Left ankle sprain" |
| created_at | STRING | When injury added | "2025-01-14T18:00:00.000Z" |
| updated_at | STRING | Last status update | "2025-01-15T12:00:00.000Z" |

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/ball-dont-lie/injuries/{date}/{timestamp}.json`

#### Next Phase

**Phase 2 Processor:** BdlInjuriesProcessor
**Output Table:** `nba_raw.bdl_injuries`
**Usage:** Cross-validate with NBA.com injury reports

---

### BdlStandingsScraper

**File:** `scrapers/balldontlie/bdl_standings.py`
**Endpoint:** `GET /v1/standings?season={YYYY}`
**Purpose:** Current league standings by conference
**Update Frequency:** Daily at 6 AM ET

#### API Response Structure

```json
{
  "data": [
    {
      "conference": "West",
      "team_id": 14,
      "team_name": "Los Angeles Lakers",
      "team_abbreviation": "LAL",
      "wins": 35,
      "losses": 15,
      "win_percentage": 0.700,
      "games_back": 0.0,
      "conference_rank": 1,
      "home_record": "20-5",
      "away_record": "15-10",
      "last_10": "7-3"
    }
  ]
}
```

#### Fields Retrieved (13 fields per team)

| Field Path | Type | Description | Example |
|------------|------|-------------|---------|
| conference | STRING | Conference name | "West", "East" |
| team_id | INT64 | BDL team ID | 14 |
| team_name | STRING | Team name | "Los Angeles Lakers" |
| team_abbreviation | STRING | Team code | "LAL" |
| wins | INT64 | Total wins | 35 |
| losses | INT64 | Total losses | 15 |
| win_percentage | FLOAT64 | Win percentage | 0.700 |
| games_back | FLOAT64 | Games behind leader | 0.0 |
| conference_rank | INT64 | Conference ranking | 1 |
| home_record | STRING | Home W-L | "20-5" |
| away_record | STRING | Away W-L | "15-10" |
| last_10 | STRING | Last 10 games | "7-3" |

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/ball-dont-lie/standings/{season_formatted}/{date}/{timestamp}.json`

**Example:**
```
gs://nba-scraped-data/ball-dont-lie/standings/2024-25/2025-01-15/2025-01-15T11:00:00.000000Z.json
```

#### Next Phase

**Phase 2 Processor:** BdlStandingsProcessor
**Output Table:** `nba_raw.bdl_standings`
**Usage:** Track team performance over season

---

## Odds API Scrapers

### Overview

- **API Base:** https://api.the-odds-api.com/v4/
- **Authentication:** API key in query string (apiKey={key})
- **Rate Limit:** 500 requests/month (shared across all endpoints)
- **Snapshot Strategy:** Multiple captures per day to track line movement

---

### GetOddsApiHistoricalEventOdds (Player Props History)

**File:** `scrapers/odds_api/get_odds_api_historical_event_odds.py`
**Endpoint:** `GET /v4/historical/sports/basketball_nba/events/{event_id}/odds`
**Purpose:** Backfill historical player prop betting lines
**Update Frequency:** Backfill only (historical data)
**Markets:** player_points, player_rebounds, player_assists

#### API Response Structure

```json
{
  "id": "abc123def456",
  "sport_key": "basketball_nba",
  "sport_title": "NBA",
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

#### Fields Retrieved (20+ fields per prop)

| Field Path | Type | Description | Example |
|------------|------|-------------|---------|
| **Event** | | | |
| id | STRING | Odds API event ID | "abc123def456" |
| sport_key | STRING | Sport identifier | "basketball_nba" |
| commence_time | STRING | Game start time (ISO) | "2025-01-15T23:00:00Z" |
| home_team | STRING | Home team name | "Los Angeles Lakers" |
| away_team | STRING | Away team name | "Philadelphia 76ers" |
| **Bookmaker** | | | |
| bookmakers[].key | STRING | Bookmaker identifier | "draftkings" |
| bookmakers[].title | STRING | Bookmaker display name | "DraftKings" |
| bookmakers[].last_update | STRING | Last odds update | "2025-01-15T18:30:00Z" |
| **Market** | | | |
| markets[].key | STRING | Market type | "player_points" |
| markets[].last_update | STRING | Market last update | "2025-01-15T18:30:00Z" |
| **Outcome** | | | |
| outcomes[].name | STRING | Bet side | "Over", "Under" |
| outcomes[].description | STRING | Player full name | "LeBron James" |
| outcomes[].price | FLOAT64 | Decimal odds | 1.91 |
| outcomes[].point | FLOAT64 | Prop line | 25.5 |

#### Transformed Output Structure

```json
{
  "event_id": "abc123def456",
  "date": "2025-01-15",
  "teams": "PHILAL",
  "timestamp": "2025-01-15T18:30:00.000000Z",
  "snapshot_time": "18:30",
  "commence_time": "2025-01-15T23:00:00Z",
  "home_team": "Los Angeles Lakers",
  "away_team": "Philadelphia 76ers",
  "markets": {
    "player_points": [
      {
        "bookmaker": "draftkings",
        "player": "LeBron James",
        "line": 25.5,
        "over_price": 1.91,
        "under_price": 1.91,
        "last_update": "2025-01-15T18:30:00Z"
      }
    ]
  }
}
```

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/odds-api/player-props-history/{date}/{event_id}-{AWAYTEAM}{HOMETEAM}/{timestamp}-snap-{time}.json`

**Example:**
```
gs://nba-scraped-data/odds-api/player-props-history/2025-01-15/abc123-PHILAL/2025-01-15T18:30:00-snap-1830.json
```

**Snapshot Strategy:**
- Morning: 10:00 AM ET (opening lines)
- Afternoon: 3:00 PM ET, 5:00 PM ET
- Pre-game: 6:00 PM ET, 6:30 PM ET
- Game time: 7:00 PM ET (closing lines)

#### Data Quality Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Games processed | 2,429 games | 4 seasons |
| Total prop records | 53,871 | All player props |
| Props per game (regular) | ~20-23 | 11-15 players × 1.9 bookmakers |
| Props per game (playoffs) | ~26-28 | More coverage |
| Bookmakers per player | ~1.9 avg | DraftKings, FanDuel primary |
| Historical backfill | 2023-2025 | 3 seasons complete |

#### Next Phase

**Phase 2 Processor:** OddsApiPropsProcessor
**Output Table:** `nba_raw.odds_api_player_points_props`
**Transformation:**
- Parse player names → player_lookup
- Convert decimal odds → American format
- Standardize game_id
- Preserve snapshot timestamps (line movement tracking)

---

### GetOddsApiCurrentEventOdds (Player Props Current)

**File:** `scrapers/odds_api/get_odds_api_current_event_odds.py`
**Endpoint:** Same as historical
**Purpose:** Real-time player prop lines (intraday)
**Update Frequency:** Every 15 minutes on game days
**Status:** ⚠️ Needs processor enhancement for Season 2025-26

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/odds-api/player-props/{date}/{event_id}-{AWAYTEAM}{HOMETEAM}/{timestamp}-snap-{time}.json`

---

### GetOddsApiHistoricalGameLines

**File:** `scrapers/odds_api/get_odds_api_historical_game_lines.py`
**Endpoint:** `GET /v4/historical/sports/basketball_nba/events/{event_id}/odds`
**Purpose:** Backfill historical spreads and totals
**Update Frequency:** Backfill only
**Markets:** spreads, totals

#### API Response Structure

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
      "markets": [
        {
          "key": "spreads",
          "outcomes": [
            {
              "name": "Los Angeles Lakers",
              "price": 1.91,
              "point": -4.5
            },
            {
              "name": "Philadelphia 76ers",
              "price": 1.91,
              "point": 4.5
            }
          ]
        },
        {
          "key": "totals",
          "outcomes": [
            {
              "name": "Over",
              "price": 1.91,
              "point": 227.5
            },
            {
              "name": "Under",
              "price": 1.91,
              "point": 227.5
            }
          ]
        }
      ]
    }
  ]
}
```

#### Fields Retrieved (15+ fields per game)

| Field Path | Type | Description | Example |
|------------|------|-------------|---------|
| id | STRING | Event ID | "abc123def456" |
| commence_time | STRING | Game start time | "2025-01-15T23:00:00Z" |
| home_team | STRING | Home team | "Los Angeles Lakers" |
| away_team | STRING | Away team | "Philadelphia 76ers" |
| bookmakers[].key | STRING | Bookmaker | "draftkings", "fanduel" |
| markets[].key | STRING | Market type | "spreads", "totals" |
| outcomes[].name | STRING | Outcome | Team name, "Over", "Under" |
| outcomes[].price | FLOAT64 | Decimal odds | 1.91 |
| outcomes[].point | FLOAT64 | Spread/total | -4.5, 227.5 |

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/odds-api/game-lines-history/{date}/{event_id}-{AWAYTEAM}{HOMETEAM}/{timestamp}-snap-{time}.json`

**Example:**
```
gs://nba-scraped-data/odds-api/game-lines-history/2025-01-15/abc123-PHILAL/2025-01-15T18:30:00-snap-1830.json
```

#### Data Quality Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Clean records | 39,256 | High quality |
| Game snapshots | 4,930 | 3.75 seasons |
| Games with 8 records | 99.2% | Expected structure |
| Formula | 2 bookmakers × 2 markets × 2 outcomes | Standard |

#### Next Phase

**Phase 2 Processor:** OddsGameLinesProcessor
**Output Table:** `nba_raw.odds_api_game_lines`

---

### GetOddsApiEvents (Lookup Only)

**File:** `scrapers/odds_api/get_odds_api_events.py`
**Endpoint:** `GET /v4/sports/basketball_nba/events`
**Purpose:** Get event IDs for current/upcoming games
**Update Frequency:** Hourly
**Usage:** Lookup only - not processed into BigQuery

#### API Response Structure

```json
[
  {
    "id": "abc123def456",
    "sport_key": "basketball_nba",
    "commence_time": "2025-01-15T23:00:00Z",
    "home_team": "Los Angeles Lakers",
    "away_team": "Philadelphia 76ers"
  }
]
```

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/odds-api/events/{date}/{timestamp}.json`

**Usage:** Scraper workflows use this to determine which event IDs to fetch odds for.

---

### GetOddsApiHistoricalEvents (Lookup Only)

**File:** `scrapers/odds_api/get_odds_api_historical_events.py`
**Purpose:** Historical event ID mapping for backfills
**Path Pattern:** `gs://nba-scraped-data/odds-api/events-history/{date}/{timestamp}.json`
**Usage:** Lookup only - not processed into BigQuery

---

## NBA.com Scrapers

### Overview

- **API Base:** Various (cdn.nba.com, stats.nba.com, ak-static.cms.nba.com)
- **Authentication:** None required (public APIs)
- **Rate Limit:** Aggressive (429 errors common), requires careful throttling
- **Format:** JSON (some PDFs for reports)

---

### GetNbaComScheduleApi

**File:** `scrapers/nba_com/get_nba_com_schedule_api.py`
**Endpoint:** `GET https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_{season_year}.json`
**Purpose:** Complete season schedule with metadata
**Update Frequency:** Daily at 6 AM ET
**Seasons:** Historical (2021-2026 available)

#### API Response Structure

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
            "gameSequence": 123,
            "gameDateTimeUTC": "2025-01-16T00:00:00Z",
            "gameEt": "2025-01-15T19:00:00",
            "regulationPeriods": 4,
            "seriesGameNumber": "",
            "seriesText": "",
            "homeTeam": {
              "teamId": 1610612747,
              "teamName": "Lakers",
              "teamCity": "Los Angeles",
              "teamTricode": "LAL",
              "teamSlug": "lakers",
              "wins": 35,
              "losses": 15,
              "score": 0
            },
            "awayTeam": {
              "teamId": 1610612755,
              "teamName": "76ers",
              "teamCity": "Philadelphia",
              "teamTricode": "PHI",
              "teamSlug": "sixers",
              "wins": 28,
              "losses": 22,
              "score": 0
            },
            "pointsLeaders": [],
            "seriesConference": "",
            "broadcasters": {
              "nationalBroadcasters": [
                {
                  "broadcasterDisplay": "ESPN",
                  "broadcasterAbbreviation": "ESPN",
                  "regionalBroadcasterDisplay": ""
                }
              ],
              "nationalRadioBroadcasters": [],
              "homeTvBroadcasters": [],
              "homeRadioBroadcasters": [],
              "awayTvBroadcasters": [],
              "awayRadioBroadcasters": []
            }
          }
        ]
      }
    ]
  }
}
```

#### Fields Retrieved (35+ fields per game)

| Field Path | Type | Description | Example |
|------------|------|-------------|---------|
| **Game Identifiers** | | | |
| gameId | STRING | NBA.com game ID | "0022400561" |
| gameCode | STRING | Date/team code | "20250115/PHILAL" |
| gameDate | STRING | Game date | "2025-01-15" |
| gameSequence | INT64 | Season game number | 123 |
| **Timing** | | | |
| gameDateTimeUTC | STRING | Start time UTC | "2025-01-16T00:00:00Z" |
| gameEt | STRING | Start time ET | "2025-01-15T19:00:00" |
| gameStatus | INT64 | Status code | 1=scheduled, 2=live, 3=final |
| gameStatusText | STRING | Status display | "7:00 pm ET", "Final" |
| **Home Team** | | | |
| homeTeam.teamId | INT64 | NBA.com team ID | 1610612747 |
| homeTeam.teamTricode | STRING | Team abbreviation | "LAL" |
| homeTeam.teamName | STRING | Team name | "Lakers" |
| homeTeam.teamCity | STRING | Team city | "Los Angeles" |
| homeTeam.wins | INT64 | Season wins | 35 |
| homeTeam.losses | INT64 | Season losses | 15 |
| homeTeam.score | INT64 | Final score (if complete) | 0, 118 |
| **Away Team** | | | |
| awayTeam.teamId | INT64 | NBA.com team ID | 1610612755 |
| awayTeam.teamTricode | STRING | Team abbreviation | "PHI" |
| awayTeam.wins | INT64 | Season wins | 28 |
| awayTeam.losses | INT64 | Season losses | 22 |
| awayTeam.score | INT64 | Final score | 0, 112 |
| **Special Context** | | | |
| broadcasters.nationalBroadcasters | ARRAY | National TV | [{"broadcasterDisplay": "ESPN"}] |
| seriesText | STRING | Playoff series info | "LAL leads 2-1" |
| seriesGameNumber | STRING | Playoff game number | "3" |

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/nba-com/schedule/{season_nba_format}/{timestamp}.json`

**Example:**
```
gs://nba-scraped-data/nba-com/schedule/2024-25/2025-01-15T11:00:00.000000Z.json
```

#### Data Quality Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Games per season | ~1,230 | Regular (1,230) + playoffs (70-100) |
| Historical coverage | 2021-2026 | 5 complete seasons |
| Update lag | Real-time | Very current |
| Completeness | 100% | Official NBA source |

#### Next Phase

**Phase 2 Processor:** NbacScheduleProcessor
**Output Table:** `nba_raw.nbac_schedule`
**Usage:** Foundation table - all game-based processing starts here

---

### GetNbaComGamebooks

**File:** `scrapers/nba_com/get_nba_com_gamebooks.py`
**Endpoint:** `GET https://ak-static.cms.nba.com/referee/injury/Gamebook_{gameCode}_pdf.pdf`
**Purpose:** Official gamebook PDFs with full player lists (active + inactive)
**Update Frequency:** Post-game (~2 hours after completion)
**Format:** PDF + parsed JSON

#### Parsed JSON Structure

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
          "field_goals": "10-18",
          "three_pointers": "2-6",
          "free_throws": "6-8",
          "rebounds_off": "1",
          "rebounds_def": "7",
          "rebounds_total": "8",
          "assists": "7",
          "personal_fouls": "2",
          "steals": "2",
          "turnovers": "3",
          "blocks": "1",
          "points": "28",
          "plus_minus": "+6"
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
    "away": {
      "team_code": "PHI",
      "players": [ /* same structure */ ]
    }
  }
}
```

#### Fields Retrieved per Player

**Active Players (17 fields):**

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| status | STRING | Player status | "active" |
| number | STRING | Jersey number | "23" |
| name | STRING | Last name (or full) | "James" |
| position | STRING | Position | "F", "G", "C" |
| minutes | STRING | Minutes played | "35:22" |
| field_goals | STRING | FGM-FGA | "10-18" |
| three_pointers | STRING | 3PM-3PA | "2-6" |
| free_throws | STRING | FTM-FTA | "6-8" |
| rebounds_off | STRING | Offensive rebounds | "1" |
| rebounds_def | STRING | Defensive rebounds | "7" |
| rebounds_total | STRING | Total rebounds | "8" |
| assists | STRING | Assists | "7" |
| personal_fouls | STRING | Personal fouls | "2" |
| steals | STRING | Steals | "2" |
| turnovers | STRING | Turnovers | "3" |
| blocks | STRING | Blocks | "1" |
| points | STRING | Points | "28" |
| plus_minus | STRING | Plus/minus | "+6" |

**Inactive Players (4 fields):**

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| status | STRING | Player status | "dnp", "inactive" |
| number | STRING | Jersey number | "15" |
| name | STRING | Last name only | "Bryant" |
| dnp_reason | STRING | Reason for DNP | "Coach's Decision", "Injury" |

#### GCS Storage

**PDF:** `gs://nba-scraped-data/nba-com/gamebooks-pdf/{date}/{clean_game_code_dashes}/{timestamp}.pdf`
**JSON:** `gs://nba-scraped-data/nba-com/gamebooks-data/{date}/{clean_game_code_dashes}/{timestamp}.json`

**Example:**
```
gs://nba-scraped-data/nba-com/gamebooks-pdf/2025-01-15/20250115-PHILAL/2025-01-15T21:30:00.pdf
gs://nba-scraped-data/nba-com/gamebooks-data/2025-01-15/20250115-PHILAL/2025-01-15T21:30:00.json
```

#### Data Quality Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Total player-game records | ~118,000 | 4 seasons |
| Active players per game | ~26 | 13 per team |
| Inactive players per game | ~8-12 | DNP + injuries |
| Name resolution accuracy | 98.92% | Via Basketball Reference + injury DB |
| Update lag | ~2 hours post-game | PDF generation time |

**Unique Value:**
- ✅ Only source with complete inactive player lists
- ✅ Only source with DNP reasons
- ✅ Enables accurate roster tracking

#### Critical Dependency

**REQUIRES:** `nba_raw.br_rosters_current` for name resolution (last names → full names)

#### Next Phase

**Phase 2 Processor:** NbacGamebookProcessor
**Output Table:** `nba_raw.nbac_gamebook_player_stats`
**Transformation:** Name resolution via Basketball Reference rosters

---

### GetNbaComInjuryReport

**File:** `scrapers/nba_com/get_nba_com_injury_report.py`
**Endpoint:** `GET https://ak-static.cms.nba.com/referee/injury/Injury-Report_{date}.pdf`
**Purpose:** Official daily injury report
**Update Frequency:** Hourly (24 snapshots per day)
**Format:** PDF + parsed JSON

#### Parsed JSON Structure

```json
{
  "report_date": "2025-01-15",
  "report_hour": 17,
  "games": [
    {
      "game_id": "20250115_PHI_LAL",
      "game_date": "2025-01-15",
      "game_time": "7:00 PM ET",
      "home_team": "LAL",
      "away_team": "PHI",
      "injuries": [
        {
          "team": "LAL",
          "player_name": "Anthony Davis",
          "current_status": "Questionable",
          "reason": "Left ankle sprain",
          "return_date": ""
        },
        {
          "team": "PHI",
          "player_name": "Joel Embiid",
          "current_status": "Out",
          "reason": "Left knee injury management",
          "return_date": "01/18/2025"
        }
      ]
    }
  ]
}
```

#### Fields Retrieved per Injury (7 fields)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| game_id | STRING | System game ID | "20250115_PHI_LAL" |
| game_date | STRING | Game date | "2025-01-15" |
| team | STRING | Team abbreviation | "LAL" |
| player_name | STRING | Player full name | "Anthony Davis" |
| current_status | STRING | Injury status | "Out", "Questionable", "Doubtful", "Probable" |
| reason | STRING | Injury description | "Left ankle sprain" |
| return_date | STRING | Expected return | "01/18/2025", "" |

#### GCS Storage

**PDF:** `gs://nba-scraped-data/nba-com/injury-report-pdf/{date}/{hour24}/{timestamp}.pdf`
**JSON:** `gs://nba-scraped-data/nba-com/injury-report-data/{date}/{hour24}/{timestamp}.json`

**Example:**
```
gs://nba-scraped-data/nba-com/injury-report-pdf/2025-01-15/17/2025-01-15T22:00:00.json
gs://nba-scraped-data/nba-com/injury-report-data/2025-01-15/17/2025-01-15T22:00:00.json
```

#### Data Quality Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Snapshots per day | 24 | Hourly captures |
| Hours with no report | 60-70% | Normal (no updates) |
| Peak times | 17:00, 20:00 ET | Pre-game updates |
| Total records (4 years) | ~500-600K | All snapshots |

#### Next Phase

**Phase 2 Processor:** NbacInjuryReportProcessor
**Output Table:** `nba_raw.nbac_injury_report`
**Strategy:** APPEND_ALWAYS (tracks status changes over time)

---

### GetNbaComPlayerList

**File:** `scrapers/nba_com/get_nba_com_player_list.py`
**Endpoint:** `GET https://stats.nba.com/stats/leaguedashplayerstats?Season=2024-25`
**Purpose:** All players with current team assignments
**Update Frequency:** Every 2 hours

#### API Response Structure

```json
{
  "resultSets": [
    {
      "headers": [
        "PLAYER_ID",
        "PLAYER_NAME",
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "AGE",
        "GP",
        "W",
        "L",
        "MIN",
        "PTS"
        /* ... 60+ stats fields ... */
      ],
      "rowSet": [
        [
          2544,
          "LeBron James",
          1610612747,
          "LAL",
          40.2,
          50,
          35,
          15,
          34.5,
          25.2
          /* ... */
        ]
      ]
    }
  ]
}
```

#### Fields Retrieved (65+ fields per player)

**Key Fields Extracted:**

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| PLAYER_ID | INT64 | NBA.com player ID | 2544 |
| PLAYER_NAME | STRING | Player full name | "LeBron James" |
| TEAM_ID | INT64 | NBA.com team ID | 1610612747 |
| TEAM_ABBREVIATION | STRING | Team code | "LAL" |
| AGE | FLOAT64 | Player age | 40.2 |
| GP | INT64 | Games played | 50 |
| MIN | FLOAT64 | Minutes per game | 34.5 |
| PTS | FLOAT64 | Points per game | 25.2 |
| REB | FLOAT64 | Rebounds per game | 7.8 |
| AST | FLOAT64 | Assists per game | 8.1 |

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/nba-com/player-list/{date}/{timestamp}.json`

#### Next Phase

**Phase 2 Processor:** NbacPlayerListProcessor
**Output Table:** `nba_raw.nbac_player_list_current`
**Usage:** Player-team lookup for all processors

---

### GetNbaComRefereeAssignments

**File:** `scrapers/nba_com/get_nba_com_referee_assignments.py`
**Endpoint:** `GET https://cdn.nba.com/static/json/staticData/GameOfficials.json`
**Purpose:** Daily referee crew assignments
**Update Frequency:** Daily at 9:15 AM ET

#### API Response Structure

```json
{
  "gameDates": [
    {
      "gameDate": "2025-01-15",
      "games": [
        {
          "gameCode": "20250115/PHILAL",
          "officials": [
            {
              "personId": "12345",
              "name": "Scott Foster",
              "jerseyNum": "71",
              "assignment": "Crew Chief"
            },
            {
              "personId": "12346",
              "name": "Tony Brothers",
              "jerseyNum": "25",
              "assignment": "Referee"
            }
          ]
        }
      ]
    }
  ]
}
```

#### Fields Retrieved (5 fields per official)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| gameCode | STRING | Game identifier | "20250115/PHILAL" |
| personId | STRING | Official ID | "12345" |
| name | STRING | Official name | "Scott Foster" |
| jerseyNum | STRING | Jersey number | "71" |
| assignment | STRING | Role | "Crew Chief", "Referee", "Umpire" |

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/nba-com/referee-assignments/{date}/{timestamp}.json`

#### Data Quality Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Officials per game (regular) | 3.0 avg | Standard crew |
| Officials per game (playoffs) | 4.0 avg | Enhanced crew |
| Release time | 9:15 AM ET | Daily |

#### Next Phase

**Phase 2 Processor:** NbacRefereeProcessor
**Output Table:** `nba_raw.nbac_referee_game_assignments`

---

### GetNbaComTeamBoxscore

**File:** `scrapers/nba_com/get_nba_com_team_boxscore.py`
**Endpoint:** `GET https://stats.nba.com/stats/boxscoretraditionalv3?GameID={nba_game_id}`
**Purpose:** Official team statistics for completed games
**Update Frequency:** Post-game (8 PM PT, 11 PM PT)

#### API Response Structure

```json
{
  "boxScoreTraditional": {
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
      /* same structure */
    }
  }
}
```

#### Fields Retrieved (20+ fields per team)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| teamId | INT64 | NBA.com team ID | 1610612747 |
| teamTricode | STRING | Team abbreviation | "LAL" |
| fieldGoalsMade | INT64 | Total FGM | 42 |
| fieldGoalsAttempted | INT64 | Total FGA | 88 |
| threePointersMade | INT64 | Total 3PM | 15 |
| freeThrowsMade | INT64 | Total FTM | 19 |
| reboundsTotal | INT64 | Total rebounds | 43 |
| assists | INT64 | Total assists | 28 |
| steals | INT64 | Total steals | 9 |
| blocks | INT64 | Total blocks | 6 |
| turnovers | INT64 | Total turnovers | 12 |
| points | INT64 | Total points | 118 |
| plusMinusPoints | INT64 | Point differential | 6 |

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/nba-com/team-boxscore/{game_date}/{game_id}/{timestamp}.json`

**Example:**
```
gs://nba-scraped-data/nba-com/team-boxscore/2025-01-15/20250115_PHI_LAL/2025-01-15T23:30:00.json
```

#### Next Phase

**Phase 2 Processor:** NbacTeamBoxscoreProcessor
**Output Table:** `nba_raw.nbac_team_boxscore`
**Note:** Replaces deprecated Scoreboard V2

---

### GetNbaComPlayByPlay

**File:** `scrapers/nba_com/get_nba_com_play_by_play.py`
**Endpoint:** `GET https://stats.nba.com/stats/playbyplayv3?GameID={nba_game_id}`
**Purpose:** Official play-by-play events
**Update Frequency:** Post-game

#### API Response Structure

```json
{
  "game": {
    "gameId": "0022400561",
    "actions": [
      {
        "actionNumber": 1,
        "clock": "PT12M00.00S",
        "period": 1,
        "teamId": 1610612747,
        "personId": 2544,
        "actionType": "2pt",
        "shotResult": "Made",
        "description": "James 15' Pullup Jump Shot (2 PTS)",
        "scoreHome": "2",
        "scoreAway": "0"
      }
    ]
  }
}
```

#### Fields Retrieved (15+ fields per action)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| actionNumber | INT64 | Event sequence | 1 |
| clock | STRING | Game clock | "PT12M00.00S" |
| period | INT64 | Quarter/OT | 1, 2, 3, 4, 5 |
| teamId | INT64 | Team involved | 1610612747 |
| personId | INT64 | Player involved | 2544 |
| actionType | STRING | Event type | "2pt", "3pt", "rebound" |
| shotResult | STRING | Shot outcome | "Made", "Missed" |
| description | STRING | Event description | "James 15' Pullup..." |
| scoreHome | STRING | Home score | "2" |
| scoreAway | STRING | Away score | "0" |

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/nba-com/play-by-play/{date}/game-{game_id}/{timestamp}.json`

#### Next Phase

**Phase 2 Processor:** NbacPlayByPlayProcessor
**Output Table:** `nba_raw.nbac_play_by_play`

---

### GetNbaComPlayerMovement

**File:** `scrapers/nba_com/get_nba_com_player_movement.py`
**Endpoint:** `GET https://stats.nba.com/stats/playermovementlist`
**Purpose:** Player transactions (trades, signings, releases)
**Update Frequency:** Daily at 10 AM ET

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/nba-com/player-movement/{date}/{timestamp}.json`

#### Next Phase

**Phase 2 Processor:** NbacPlayerMovementProcessor
**Output Table:** `nba_raw.nbac_player_movement`

---

## ESPN Scrapers

### Overview

- **API Base:** https://site.api.espn.com/apis/site/v2/sports/basketball/nba/
- **Authentication:** None required
- **Rate Limit:** Moderate (less aggressive than NBA.com)
- **Purpose:** Backup statistics when primary sources fail

---

### EspnScoreboard

**File:** `scrapers/espn/espn_scoreboard.py`
**Endpoint:** `GET /scoreboard?dates={YYYYMMDD}`
**Purpose:** Game scores and basic stats
**Update Frequency:** Post-game

#### API Response Structure

```json
{
  "events": [
    {
      "id": "401692583",
      "date": "2025-01-15T23:00Z",
      "name": "Philadelphia 76ers at Los Angeles Lakers",
      "shortName": "PHI @ LAL",
      "competitions": [
        {
          "id": "401692583",
          "competitors": [
            {
              "id": "13",
              "team": {
                "id": "13",
                "abbreviation": "PHI",
                "displayName": "Philadelphia 76ers",
                "shortDisplayName": "76ers"
              },
              "score": "112",
              "homeAway": "away"
            },
            {
              "id": "14",
              "team": {
                "id": "14",
                "abbreviation": "LAL",
                "displayName": "Los Angeles Lakers",
                "shortDisplayName": "Lakers"
              },
              "score": "118",
              "homeAway": "home"
            }
          ]
        }
      ]
    }
  ]
}
```

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/espn/scoreboard/{date}/{timestamp}.json`

#### Next Phase

**Phase 2 Processor:** EspnScoreboardProcessor
**Output Table:** `nba_raw.espn_scoreboard`
**Note:** Team abbreviations need mapping (NY → NYK, GS → GSW, SA → SAS)

---

### EspnBoxscore

**File:** `scrapers/espn/espn_boxscore.py`
**Endpoint:** `GET /summary?event={event_id}`
**Purpose:** Player statistics for completed games
**Update Frequency:** Post-game

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/espn/boxscores/{date}/game-{game_id}/{timestamp}.json`

#### Next Phase

**Phase 2 Processor:** EspnBoxscoresProcessor
**Output Table:** `nba_raw.espn_boxscores`

---

### EspnTeamRoster

**File:** `scrapers/espn/espn_team_roster.py`
**Endpoint:** `GET /teams/{team_id}/roster`
**Purpose:** Current team rosters
**Update Frequency:** Daily

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/espn/rosters/{date}/team_{team_abbr}/{timestamp}.json`

#### Next Phase

**Phase 2 Processor:** EspnTeamRostersProcessor
**Output Table:** `nba_raw.espn_team_rosters`

---

## Basketball Reference Scrapers

### BasketballRefSeasonRoster

**File:** `scrapers/basketball_ref/basketball_ref_season_roster.py`
**Endpoint:** Web scraping from https://www.basketball-reference.com/
**Purpose:** Historical season rosters for name resolution
**Update Frequency:** Quarterly during season (backfill)

#### Scraped Data Structure

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

#### Fields Retrieved (8+ fields per player)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| player_name | STRING | Full player name | "LeBron James" |
| position | STRING | Position | "F", "G", "C" |
| height | STRING | Height | "6-9" |
| weight | INT64 | Weight (lbs) | 250 |
| birth_date | STRING | Date of birth | "1984-12-30" |
| experience | STRING | Years in NBA | "21" |
| college | STRING | College/high school | "St. Vincent-St. Mary HS (OH)" |

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/basketball-ref/season-rosters/{season}/{team}.json`

**Example:**
```
gs://nba-scraped-data/basketball-ref/season-rosters/2024-25/LAL.json
```

#### Data Quality Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Roster files | 120 | 30 teams × 4 seasons |
| Historical coverage | 2022-2025 | 4 complete seasons |
| Maintenance | Quarterly | During season |

#### Critical Usage

**REQUIRED BY:** NbacGamebookProcessor
**Purpose:** Resolve incomplete player names (last name only) in gamebooks

**Resolution Flow:**
1. Gamebook has: "James" (last name only), team "LAL", season 2024
2. Query Basketball Reference: WHERE player_last_name = 'James' AND team = 'LAL' AND season = 2024
3. Result: "LeBron James"
4. Success: 98.92% accuracy

#### Next Phase

**Phase 2 Processor:** BasketballRefRosterProcessor
**Output Table:** `nba_raw.br_rosters_current`
**Strategy:** MERGE_UPDATE (maintains current state per season)

---

## BettingPros Scrapers

### Overview

- **API Base:** https://api.bettingpros.com/v3/
- **Authentication:** API key required
- **Rate Limit:** Moderate
- **Purpose:** Backup betting lines

---

### BettingProsEvents

**File:** `scrapers/bettingpros/bettingpros_events.py`
**Endpoint:** `GET /nba/events`
**Purpose:** Current/upcoming NBA events
**Update Frequency:** Hourly

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/bettingpros/events/{date}/{timestamp}.json`

#### Next Phase

Not processed - lookup only for player props scraper

---

### BettingProsPlayerProps

**File:** `scrapers/bettingpros/bettingpros_player_props.py`
**Endpoint:** `GET /nba/markets/{market_type}/offers`
**Purpose:** Player prop lines (backup to Odds API)
**Update Frequency:** Daily
**Markets:** player-points, player-rebounds, player-assists

#### API Response Structure

```json
{
  "offers": [
    {
      "offer_id": "12345",
      "player_name": "LeBron James",
      "team": "LAL",
      "opponent": "PHI",
      "game_date": "2025-01-15",
      "market_type": "player-points",
      "line": 25.5,
      "over_odds": -110,
      "under_odds": -110,
      "book_name": "DraftKings",
      "timestamp": "2025-01-15T18:00:00Z"
    }
  ]
}
```

#### Fields Retrieved (10 fields per prop)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| offer_id | STRING | Unique offer ID | "12345" |
| player_name | STRING | Player full name | "LeBron James" |
| team | STRING | Player's team | "LAL" |
| opponent | STRING | Opponent team | "PHI" |
| game_date | STRING | Game date | "2025-01-15" |
| market_type | STRING | Prop type | "player-points" |
| line | FLOAT64 | Prop line | 25.5 |
| over_odds | INT64 | Over odds (American) | -110 |
| under_odds | INT64 | Under odds (American) | -110 |
| book_name | STRING | Bookmaker | "DraftKings" |

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/bettingpros/player-props/{market_type}/{date}/{timestamp}.json`

**Example:**
```
gs://nba-scraped-data/bettingpros/player-props/player-points/2025-01-15/2025-01-15T14:00:00.json
```

#### Data Quality Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Total prop records | 1,087,315 | 4 seasons |
| Coverage | ~5,400 games | Complete backfill |
| Props per game | ~200-300 | More comprehensive than Odds API |
| Bookmakers | 10+ | Multiple sources |

#### Next Phase

**Phase 2 Processor:** BettingProsPlayerPropsProcessor
**Output Table:** `nba_raw.bettingpros_player_points_props`
**Usage:** Backup when Odds API unavailable

---

## BigDataBall Scrapers

### BigDataBallPbpScraper

**File:** `scrapers/bigdataball/bigdataball_pbp.py`
**Source:** Google Drive CSV files
**Purpose:** Enhanced play-by-play with shot coordinates and lineups
**Update Frequency:** ~2 hours post-game
**Format:** CSV

#### CSV Structure

```
game_id,event_num,event_type,player_1,player_2,shot_made,shot_type,original_x,original_y,away_player_1,away_player_2,away_player_3,away_player_4,away_player_5,home_player_1,home_player_2,home_player_3,home_player_4,home_player_5,game_clock,period,home_score,away_score
0022400561,1,shot,LeBron James,,1,Pullup Jump Shot,15,10,Joel Embiid,Tyrese Maxey,Kelly Oubre Jr.,Tobias Harris,De'Anthony Melton,LeBron James,Anthony Davis,Austin Reaves,D'Angelo Russell,Rui Hachimura,11:45,1,2,0
```

#### Fields Retrieved (25+ fields per event)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| game_id | STRING | Game identifier | "0022400561" |
| event_num | INT64 | Event sequence | 1 |
| event_type | STRING | Event type | "shot", "rebound", "foul" |
| player_1 | STRING | Primary player | "LeBron James" |
| player_2 | STRING | Secondary player | "" |
| shot_made | INT64 | Shot result | 1=made, 0=missed |
| shot_type | STRING | Shot description | "Pullup Jump Shot" |
| original_x | FLOAT64 | Shot X coordinate | 15.0 |
| original_y | FLOAT64 | Shot Y coordinate | 10.0 |
| away_player_1 | STRING | Away player 1 | "Joel Embiid" |
| away_player_2 | STRING | Away player 2 | "Tyrese Maxey" |
| away_player_3 | STRING | Away player 3 | "Kelly Oubre Jr." |
| away_player_4 | STRING | Away player 4 | "Tobias Harris" |
| away_player_5 | STRING | Away player 5 | "De'Anthony Melton" |
| home_player_1 | STRING | Home player 1 | "LeBron James" |
| home_player_2 | STRING | Home player 2 | "Anthony Davis" |
| home_player_3 | STRING | Home player 3 | "Austin Reaves" |
| home_player_4 | STRING | Home player 4 | "D'Angelo Russell" |
| home_player_5 | STRING | Home player 5 | "Rui Hachimura" |
| game_clock | STRING | Game clock | "11:45" |
| period | INT64 | Quarter/OT | 1, 2, 3, 4 |
| home_score | INT64 | Home score | 2 |
| away_score | INT64 | Away score | 0 |

#### GCS Storage

**Path Pattern:** `gs://nba-scraped-data/big-data-ball/{season}/{date}/game_{id}/{filename}.csv`

**Example:**
```
gs://nba-scraped-data/big-data-ball/2024-25/2025-01-15/game_0022400561/bigdataball_abc123_20250115-0022400561-PHI@LAL.csv
```

#### Data Quality Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Total events | 566,034 | All play-by-play |
| Games processed | 1,211 | Complete 2024-25 |
| Events per game | ~400-500 | Detailed coverage |
| Update lag | ~2 hours | Post-game availability |

**Unique Capabilities:**
- ✅ Shot coordinates (X, Y positioning)
- ✅ Complete 5-man lineups for every possession
- ✅ Advanced timing (game clock, elapsed time, play length)
- ✅ Shot chart data

#### Next Phase

**Phase 2 Processor:** BigDataBallPbpProcessor
**Output Table:** `nba_raw.bigdataball_play_by_play`
**Usage:** Enhanced analytics, shot zone analysis, lineup efficiency

---

## Orchestration Summary

### Scraper Execution Patterns

#### Real-Time Scrapers (Every 15 minutes on game days)

- GetOddsApiCurrentEventOdds (player props)
- GetOddsApiCurrentGameLines (spreads/totals)

#### Hourly Scrapers

- GetNbaComInjuryReport (24 times per day)
- GetOddsApiEvents (event lookup)
- BettingProsEvents (event lookup)

#### Every 2 Hours

- BdlActivePlayersScraper
- BdlInjuriesScraper
- GetNbaComPlayerList

#### Daily Morning (6-10 AM ET)

- GetNbaComScheduleApi (6 AM)
- BdlStandingsScraper (6 AM)
- BasketballRefSeasonRoster (morning operations)
- GetNbaComRefereeAssignments (9:15 AM)
- GetNbaComPlayerMovement (10 AM)

#### Post-Game (~2 hours after game ends)

- BdlBoxScoresScraper
- GetNbaComGamebooks (PDF + parsing)
- GetNbaComTeamBoxscore (8 PM PT, 11 PM PT)
- GetNbaComPlayByPlay
- BigDataBallPbpScraper
- EspnScoreboard
- EspnBoxscore

#### Backfill/Historical (On-demand)

- GetOddsApiHistoricalEventOdds
- GetOddsApiHistoricalGameLines
- BasketballRefSeasonRoster (quarterly)

---

### Critical Path Dependencies

#### Morning Operations (Must Complete First):

1. GetNbaComScheduleApi → Defines games for the day
2. BasketballRefSeasonRoster → Required for gamebook name resolution
3. GetNbaComPlayerList → Player-team assignments

#### Game Day Operations:

- GetOddsApiCurrentEventOdds → Multiple snapshots track line movement
- GetNbaComInjuryReport → Hourly injury status updates

#### Post-Game Operations:

1. BdlBoxScoresScraper → Primary player stats (triggers Phase 2)
2. GetNbaComGamebooks → DNP context + inactive players
3. GetNbaComTeamBoxscore → Team statistics
4. BigDataBallPbpScraper → Enhanced analytics (~2 hour delay)

---

## GCS Storage Patterns

### Path Structure Standards

All GCS paths follow: `gs://nba-scraped-data/{source}/{type}/{date_or_structure}/{timestamp}.{ext}`

**Date Formats:**
- Standard: YYYY-MM-DD (2025-01-15)
- Season: YYYY-YY (2024-25)
- Hour: 24-hour format (00-23)

**Timestamp Formats:**
- ISO 8601: YYYY-MM-DDTHH:MM:SS.ffffffZ
- Example: 2025-01-15T18:30:00.123456Z

**File Extensions:**
- JSON: .json (most scrapers)
- PDF: .pdf (injury reports, gamebooks)
- CSV: .csv (BigDataBall)

### Storage Best Practices

**Retention:**
- ✅ Permanent: All scraped data (never deleted)
- ✅ Immutable: Files never modified after creation
- ✅ Append-only: New snapshots = new files

**Organization:**
- ✅ Date-partitioned directories
- ✅ Consistent naming conventions
- ✅ Hierarchical structure (source → type → date → file)

**Metadata:**
- ✅ Timestamps in filenames
- ✅ Source identifiers in paths
- ✅ Game/event IDs embedded where relevant

---

## Summary

### Data Collection Coverage

**Complete Coverage:**
- ✅ 26 scrapers across 7 data sources
- ✅ 4+ years of historical data (2021-2025)
- ✅ Real-time updates during games (15-min snapshots)
- ✅ Multiple validation sources (primary + backup)

**Data Quality:**
- ✅ 99%+ completeness for primary sources
- ✅ 98.92% name resolution accuracy
- ✅ Cross-source validation enabled
- ✅ Comprehensive error tracking and notifications

**Update Frequencies:**
- Real-time: 15 minutes (betting lines)
- Hourly: Injury reports, player lists
- Daily: Schedules, standings, rosters
- Post-game: Statistics (~2 hours after game)
- Quarterly: Historical roster backfills

---

## Next Phase

All scrapers feed into **Phase 2 Processors** which:

1. Read JSON from GCS
2. Transform and normalize data
3. Validate and enrich
4. Write to BigQuery `nba_raw.*` tables
5. Trigger Phase 3 analytics processing

**See:** Phase 2 data mapping documentation for detailed processor transformations.

---

## Related Documentation

- **Phase 2 Transformations:** `docs/data-flow/02-phase1-to-phase2-transformations.md` (for JSON → BigQuery field mappings)
- **Phase 1 Orchestration:** `docs/orchestration/` - Scraper scheduling and workflows
- **GCS Path Standards:** Infrastructure documentation
- **BigQuery Schemas:** `docs/orchestration/03-bigquery-schemas.md`

---

**Document Version:** 1.0
**Last Updated:** 2025-11-15
**Status:** Current
