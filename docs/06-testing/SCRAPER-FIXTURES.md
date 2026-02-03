# Scraper Test Fixtures Catalog

This document provides a comprehensive catalog of test fixtures for all scrapers in the NBA Stats Scraper project. Use these fixtures for unit testing, integration testing, and regression testing.

## Overview

Test fixtures are located in `tests/fixtures/scrapers/` and are organized by data source:

```
tests/fixtures/scrapers/
├── balldontlie/      # BallDontLie API fixtures
├── espn/             # ESPN API/HTML fixtures
├── nbacom/           # NBA.com API fixtures
├── oddsapi/          # The Odds API fixtures
├── basketball_ref/   # Basketball Reference HTML fixtures
├── bigdataball/      # BigDataBall fixtures
└── bettingpros/      # BettingPros fixtures
```

---

## BallDontLie API Scrapers

BallDontLie provides JSON APIs with cursor-based pagination. All responses follow the same envelope structure.

### Common Response Envelope

```json
{
  "data": [...],
  "meta": {
    "next_cursor": null,
    "per_page": 25
  }
}
```

### bdl_games

**Scraper:** `scrapers/balldontlie/bdl_games.py`
**Class:** `BdlGamesScraper`
**Fixture:** `tests/fixtures/scrapers/balldontlie/bdl_games_raw.json`

#### Sample Raw Response

```json
{
  "data": [
    {
      "id": 123456,
      "date": "2025-01-20",
      "season": 2024,
      "status": "Final",
      "period": 4,
      "time": "",
      "postseason": false,
      "home_team": {
        "id": 1,
        "conference": "West",
        "division": "Pacific",
        "city": "Los Angeles",
        "name": "Lakers",
        "full_name": "Los Angeles Lakers",
        "abbreviation": "LAL"
      },
      "visitor_team": {
        "id": 2,
        "conference": "East",
        "division": "Atlantic",
        "city": "Boston",
        "name": "Celtics",
        "full_name": "Boston Celtics",
        "abbreviation": "BOS"
      },
      "home_team_score": 110,
      "visitor_team_score": 105
    }
  ],
  "meta": {
    "next_cursor": null,
    "per_page": 100
  }
}
```

#### Expected Transformed Output

```json
{
  "startDate": "2025-01-19",
  "endDate": "2025-01-21",
  "timestamp": "2025-01-20T15:30:00.000000+00:00",
  "gameCount": 1,
  "games": [
    {
      "id": 123456,
      "date": "2025-01-20",
      "season": 2024,
      "status": "Final",
      "home_team": { "id": 1, "abbreviation": "LAL" },
      "visitor_team": { "id": 2, "abbreviation": "BOS" },
      "home_team_score": 110,
      "visitor_team_score": 105
    }
  ]
}
```

#### Edge Cases

| Fixture | Description |
|---------|-------------|
| `bdl_games_empty.json` | Empty data array (no games scheduled) |
| `bdl_games_paginated.json` | Response with next_cursor for pagination |
| `bdl_games_preseason.json` | Preseason games |
| `bdl_games_postseason.json` | Playoff games with postseason=true |

---

### bdl_injuries

**Scraper:** `scrapers/balldontlie/bdl_injuries.py`
**Class:** `BdlInjuriesScraper`
**Fixture:** `tests/fixtures/scrapers/balldontlie/bdl_injuries_raw.json`

#### Sample Raw Response

```json
{
  "data": [
    {
      "id": 789,
      "player_id": 100,
      "team": {
        "id": 1,
        "abbreviation": "LAL"
      },
      "status": "Out",
      "comment": "Right ankle sprain",
      "date": "2025-01-18"
    }
  ],
  "meta": {
    "next_cursor": null,
    "per_page": 100
  }
}
```

#### Expected Transformed Output

```json
{
  "ident": "league",
  "timestamp": "2025-01-20T15:30:00.000000+00:00",
  "rowCount": 1,
  "injuries": [
    {
      "id": 789,
      "player_id": 100,
      "team": { "id": 1, "abbreviation": "LAL" },
      "status": "Out",
      "comment": "Right ankle sprain"
    }
  ]
}
```

#### Edge Cases

| Fixture | Description |
|---------|-------------|
| `bdl_injuries_empty.json` | No injuries (normal during healthy periods) |
| `bdl_injuries_team.json` | Filtered by single team |
| `bdl_injuries_high_count.json` | Unusually high injury count (>150) |

---

### bdl_box_scores

**Scraper:** `scrapers/balldontlie/bdl_box_scores.py`
**Class:** `BdlBoxScoresScraper`
**Fixture:** `tests/fixtures/scrapers/balldontlie/bdl_box_scores_raw.json`

#### Sample Raw Response

```json
{
  "data": [
    {
      "id": 789,
      "player": {
        "id": 100,
        "first_name": "LeBron",
        "last_name": "James"
      },
      "team": { "id": 1, "abbreviation": "LAL" },
      "game": { "id": 123456, "date": "2025-01-20" },
      "min": "35:22",
      "pts": 28,
      "reb": 8,
      "ast": 12,
      "stl": 2,
      "blk": 1,
      "turnover": 3,
      "pf": 2,
      "fgm": 10,
      "fga": 18,
      "fg_pct": 0.556,
      "fg3m": 2,
      "fg3a": 5,
      "fg3_pct": 0.400,
      "ftm": 6,
      "fta": 7,
      "ft_pct": 0.857,
      "oreb": 1,
      "dreb": 7
    }
  ],
  "meta": {
    "next_cursor": 456,
    "per_page": 25
  }
}
```

---

### bdl_standings

**Scraper:** `scrapers/balldontlie/bdl_standings.py`
**Class:** `BdlStandingsScraper`
**Fixture:** `tests/fixtures/scrapers/balldontlie/bdl_standings_raw.json`

#### Sample Raw Response

```json
{
  "data": [
    {
      "team": {
        "id": 2,
        "abbreviation": "BOS",
        "full_name": "Boston Celtics",
        "conference": "East"
      },
      "conference_rank": 1,
      "wins": 35,
      "losses": 10,
      "win_pct": 0.778,
      "home_record": "20-3",
      "road_record": "15-7",
      "streak": "W5"
    }
  ],
  "meta": {}
}
```

---

## ESPN Scrapers

ESPN scrapers handle both JSON API responses and HTML page parsing.

### espn_scoreboard_api

**Scraper:** `scrapers/espn/espn_scoreboard_api.py`
**Class:** `GetEspnScoreboard`
**Fixture:** `tests/fixtures/scrapers/espn/espn_scoreboard_raw.json`

#### Sample Raw Response

```json
{
  "leagues": [
    {
      "id": "46",
      "name": "National Basketball Association"
    }
  ],
  "events": [
    {
      "id": "401585725",
      "name": "Boston Celtics at Los Angeles Lakers",
      "competitions": [
        {
          "id": "401585725",
          "date": "2025-01-14T03:00Z",
          "status": {
            "type": {
              "id": "3",
              "state": "post",
              "description": "Final"
            }
          },
          "competitors": [
            {
              "id": "17",
              "homeAway": "home",
              "winner": true,
              "score": "110",
              "team": {
                "id": "17",
                "displayName": "Los Angeles Lakers",
                "abbreviation": "LAL"
              }
            },
            {
              "id": "2",
              "homeAway": "away",
              "winner": false,
              "score": "105",
              "team": {
                "id": "2",
                "displayName": "Boston Celtics",
                "abbreviation": "BOS"
              }
            }
          ]
        }
      ]
    }
  ]
}
```

#### Expected Transformed Output

```json
{
  "timestamp": "2025-01-20T15:30:00.000000+00:00",
  "gamedate": "20250114",
  "season_type": "Regular Season",
  "gameCount": 1,
  "games": [
    {
      "gameId": "401585725",
      "statusId": "3",
      "state": "post",
      "status": "Final",
      "startTime": "2025-01-14T03:00Z",
      "teams": [
        {
          "teamId": "17",
          "displayName": "Los Angeles Lakers",
          "abbreviation": "LAL",
          "score": "110",
          "winner": true,
          "homeAway": "home"
        },
        {
          "teamId": "2",
          "displayName": "Boston Celtics",
          "abbreviation": "BOS",
          "score": "105",
          "winner": false,
          "homeAway": "away"
        }
      ]
    }
  ]
}
```

#### Edge Cases

| Fixture | Description |
|---------|-------------|
| `espn_scoreboard_no_games.json` | Empty events array |
| `espn_scoreboard_live.json` | Games in progress (state: "in") |
| `espn_scoreboard_pregame.json` | Scheduled games (state: "pre") |
| `espn_scoreboard_playoffs.json` | Playoff games |

---

### espn_game_boxscore

**Scraper:** `scrapers/espn/espn_game_boxscore.py`
**Class:** `GetEspnBoxscore`
**Fixture:** `tests/fixtures/scrapers/espn/espn_boxscore_raw.html`

This scraper has two parsing modes:
1. **Embedded JSON** - Preferred method using `bxscr` data embedded in HTML
2. **HTML Tables** - Fallback method parsing HTML tables directly

#### Sample Embedded JSON (bxscr)

```json
[
  {
    "tm": {
      "abbrev": "LAL"
    },
    "stats": [
      {
        "type": "starters",
        "athlts": [
          {
            "athlt": {
              "id": "123",
              "dspNm": "LeBron James",
              "jersey": "23"
            },
            "stats": ["35:22", "10-18", "2-5", "6-7", "1", "7", "8", "12", "2", "1", "3", "2", "+15", "28"]
          }
        ]
      },
      {
        "type": "bench",
        "athlts": [
          {
            "athlt": {
              "id": "456",
              "dspNm": "Austin Reaves",
              "jersey": "15"
            },
            "stats": ["25:10", "4-8", "2-3", "2-2", "0", "3", "3", "5", "1", "0", "1", "2", "+8", "12"]
          }
        ]
      }
    ]
  }
]
```

#### Expected Transformed Output

```json
{
  "game_id": "401766123",
  "gamedate": "20250120",
  "timestamp": "2025-01-20T15:30:00.000000+00:00",
  "teams": {
    "away": "BOS",
    "home": "LAL"
  },
  "playerCount": 24,
  "players": [
    {
      "playerId": "123",
      "playerName": "LeBron James",
      "jersey": "23",
      "stats": ["35:22", "10-18", "2-5", "6-7", "1", "7", "8", "12", "2", "1", "3", "2", "+15", "28"],
      "type": "starters",
      "team": "LAL",
      "teamType": "home"
    }
  ]
}
```

#### DNP (Did Not Play) Handling

```json
{
  "playerId": "789",
  "playerName": "Anthony Davis",
  "jersey": "3",
  "stats": [],
  "dnpReason": "RIGHT ANKLE SPRAIN",
  "type": "bench",
  "team": "LAL",
  "teamType": "home"
}
```

#### Edge Cases

| Fixture | Description |
|---------|-------------|
| `espn_boxscore_no_json.html` | HTML without embedded JSON (tests fallback) |
| `espn_boxscore_dnp.html` | Players marked as DNP |
| `espn_boxscore_overtime.html` | Overtime game with extended minutes |

---

## NBA.com Scrapers

NBA.com APIs use a stats endpoint with header authentication.

### nbac_scoreboard_v2

**Scraper:** `scrapers/nbacom/nbac_scoreboard_v2.py`
**Class:** `GetNbaComScoreboardV2`
**Fixture:** `tests/fixtures/scrapers/nbacom/nbac_scoreboard_v2_raw.json`

#### Sample Raw Response

```json
{
  "resultSets": [
    {
      "name": "GameHeader",
      "headers": ["GAME_DATE_EST", "GAME_SEQUENCE", "GAME_ID", "GAME_STATUS_ID", "GAME_STATUS_TEXT", "GAMECODE", "HOME_TEAM_ID", "VISITOR_TEAM_ID"],
      "rowSet": [
        ["2025-01-20T00:00:00", 1, "0022400123", 3, "Final", "20250120/BOSLAL", 1610612747, 1610612738]
      ]
    },
    {
      "name": "LineScore",
      "headers": ["GAME_DATE_EST", "GAME_SEQUENCE", "GAME_ID", "TEAM_ID", "TEAM_ABBREVIATION", "TEAM_CITY_NAME", "TEAM_NAME", "PTS"],
      "rowSet": [
        ["2025-01-20T00:00:00", 1, "0022400123", 1610612747, "LAL", "Los Angeles", "Lakers", 110],
        ["2025-01-20T00:00:00", 1, "0022400123", 1610612738, "BOS", "Boston", "Celtics", 105]
      ]
    }
  ]
}
```

---

### nbac_schedule_api

**Scraper:** `scrapers/nbacom/nbac_schedule_api.py`
**Class:** `GetNbaComScheduleApi`
**Fixture:** `tests/fixtures/scrapers/nbacom/nbac_schedule_api_raw.json`

#### Sample Raw Response

```json
{
  "meta": {
    "version": 1,
    "request": "scheduleleaguev2int"
  },
  "leagueSchedule": {
    "seasonYear": "2024",
    "leagueId": "00",
    "gameDates": [
      {
        "gameDate": "01/20/2025 12:00:00 AM",
        "games": [
          {
            "gameId": "0022400123",
            "gameCode": "20250120/BOSLAL",
            "gameStatus": 3,
            "gameStatusText": "Final",
            "gameSequence": 1,
            "gameDateEst": "2025-01-20",
            "gameTimeEst": "2025-01-20T19:30:00",
            "gameLabel": "",
            "gameSubLabel": "",
            "weekName": "Week 14",
            "day": "Mon",
            "homeTeam": {
              "teamId": 1610612747,
              "teamName": "Lakers",
              "teamCity": "Los Angeles",
              "teamTricode": "LAL",
              "score": 110
            },
            "awayTeam": {
              "teamId": 1610612738,
              "teamName": "Celtics",
              "teamCity": "Boston",
              "teamTricode": "BOS",
              "score": 105
            },
            "broadcasters": {
              "nationalTvBroadcasters": [
                { "broadcasterDisplay": "ESPN" }
              ]
            }
          }
        ]
      }
    ]
  }
}
```

#### Enhanced Flags (Added by Transform)

The transform adds computed flags for easy querying:

```json
{
  "isPrimetime": true,
  "hasNationalTV": true,
  "primaryNetwork": "ESPN",
  "traditionalNetworks": ["ESPN"],
  "streamingPlatforms": [],
  "isRegularSeason": true,
  "isPlayoffs": false,
  "isAllStar": false,
  "isEmiratesCup": false,
  "playoffRound": null,
  "isChristmas": false,
  "isMLKDay": false,
  "dayOfWeek": "mon",
  "isWeekend": false,
  "timeSlot": "primetime"
}
```

---

### nbac_play_by_play

**Scraper:** `scrapers/nbacom/nbac_play_by_play.py`
**Class:** `GetNbaComPlayByPlay`
**Fixture:** `tests/fixtures/scrapers/nbacom/nbac_play_by_play_raw.json`

#### Sample Raw Response

```json
{
  "resultSets": [
    {
      "name": "PlayByPlay",
      "headers": ["GAME_ID", "EVENTNUM", "EVENTMSGTYPE", "EVENTMSGACTIONTYPE", "PERIOD", "PCTIMESTRING", "HOMEDESCRIPTION", "NEUTRALDESCRIPTION", "VISITORDESCRIPTION", "SCORE", "SCOREMARGIN"],
      "rowSet": [
        ["0022400123", 1, 12, 0, 1, "12:00", null, "Period Start", null, null, null],
        ["0022400123", 2, 10, 0, 1, "12:00", null, "Jump Ball", null, "0 - 0", "TIE"],
        ["0022400123", 3, 1, 1, 1, "11:45", "James 25' 3PT Jump Shot (3 PTS)", null, null, "3 - 0", "+3"]
      ]
    }
  ]
}
```

---

### nbac_player_boxscore

**Scraper:** `scrapers/nbacom/nbac_player_boxscore.py`
**Class:** `GetNbaComPlayerBoxscore`
**Fixture:** `tests/fixtures/scrapers/nbacom/nbac_player_boxscore_raw.json`

#### Sample Raw Response

```json
{
  "resultSets": [
    {
      "name": "PlayerStats",
      "headers": ["GAME_ID", "TEAM_ID", "TEAM_ABBREVIATION", "PLAYER_ID", "PLAYER_NAME", "START_POSITION", "MIN", "FGM", "FGA", "FG_PCT", "FG3M", "FG3A", "FG3_PCT", "FTM", "FTA", "FT_PCT", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "PTS", "PLUS_MINUS"],
      "rowSet": [
        ["0022400123", 1610612747, "LAL", 2544, "LeBron James", "F", "35:22", 10, 18, 0.556, 2, 5, 0.400, 6, 7, 0.857, 1, 7, 8, 12, 2, 1, 3, 2, 28, 15]
      ]
    }
  ]
}
```

---

## The Odds API Scrapers

The Odds API provides betting data in JSON format.

### oddsa_events

**Scraper:** `scrapers/oddsapi/oddsa_events.py`
**Class:** `GetOddsApiEvents`
**Fixture:** `tests/fixtures/scrapers/oddsapi/oddsa_events_raw.json`

#### Sample Raw Response

```json
[
  {
    "id": "abc123def456",
    "sport_key": "basketball_nba",
    "sport_title": "NBA",
    "commence_time": "2025-01-20T23:00:00Z",
    "home_team": "Los Angeles Lakers",
    "away_team": "Boston Celtics"
  }
]
```

#### Expected Transformed Output

```json
{
  "sport": "basketball_nba",
  "game_date": "2025-01-20",
  "rowCount": 1,
  "events": [
    {
      "id": "abc123def456",
      "sport_key": "basketball_nba",
      "commence_time": "2025-01-20T23:00:00Z",
      "home_team": "Los Angeles Lakers",
      "away_team": "Boston Celtics"
    }
  ]
}
```

#### Edge Cases

| Fixture | Description |
|---------|-------------|
| `oddsa_events_empty.json` | No events for date range |
| `oddsa_events_error.json` | API error response with message |

---

### oddsa_player_props

**Scraper:** `scrapers/oddsapi/oddsa_player_props.py`
**Class:** `GetOddsApiCurrentEventOdds`
**Fixture:** `tests/fixtures/scrapers/oddsapi/oddsa_player_props_raw.json`

#### Sample Raw Response

```json
{
  "id": "abc123def456",
  "sport_key": "basketball_nba",
  "commence_time": "2025-01-20T23:00:00Z",
  "home_team": "Los Angeles Lakers",
  "away_team": "Boston Celtics",
  "bookmakers": [
    {
      "key": "draftkings",
      "title": "DraftKings",
      "markets": [
        {
          "key": "player_points",
          "outcomes": [
            {
              "name": "Over",
              "description": "LeBron James",
              "price": -115,
              "point": 25.5
            },
            {
              "name": "Under",
              "description": "LeBron James",
              "price": -105,
              "point": 25.5
            }
          ]
        }
      ]
    }
  ]
}
```

---

### oddsa_game_lines

**Scraper:** `scrapers/oddsapi/oddsa_game_lines.py`
**Class:** `GetOddsApiCurrentGameLines`
**Fixture:** `tests/fixtures/scrapers/oddsapi/oddsa_game_lines_raw.json`

#### Sample Raw Response

```json
{
  "id": "abc123def456",
  "sport_key": "basketball_nba",
  "commence_time": "2025-01-20T23:00:00Z",
  "home_team": "Los Angeles Lakers",
  "away_team": "Boston Celtics",
  "bookmakers": [
    {
      "key": "draftkings",
      "title": "DraftKings",
      "markets": [
        {
          "key": "spreads",
          "outcomes": [
            { "name": "Los Angeles Lakers", "price": -110, "point": -4.5 },
            { "name": "Boston Celtics", "price": -110, "point": 4.5 }
          ]
        },
        {
          "key": "totals",
          "outcomes": [
            { "name": "Over", "price": -110, "point": 224.5 },
            { "name": "Under", "price": -110, "point": 224.5 }
          ]
        },
        {
          "key": "h2h",
          "outcomes": [
            { "name": "Los Angeles Lakers", "price": -180 },
            { "name": "Boston Celtics", "price": 155 }
          ]
        }
      ]
    }
  ]
}
```

---

## Basketball Reference Scrapers

Basketball Reference provides HTML pages that must be parsed.

### br_season_roster

**Scraper:** `scrapers/basketball_ref/br_season_roster.py`
**Class:** `BasketballRefSeasonRoster`
**Fixture:** `tests/fixtures/scrapers/basketball_ref/br_roster_raw.html`

#### Key HTML Structure

```html
<table id="roster">
  <thead>
    <tr>
      <th>No.</th>
      <th>Player</th>
      <th>Pos</th>
      <th>Ht</th>
      <th>Wt</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>23</td>
      <td><a href="/players/j/jamesle01.html">LeBron James</a></td>
      <td>SF</td>
      <td>6-9</td>
      <td>250</td>
    </tr>
  </tbody>
</table>
```

#### Expected Transformed Output

```json
{
  "team": "Los Angeles Lakers",
  "team_abbrev": "LAL",
  "season": "2024-25",
  "year": 2025,
  "timestamp": "2025-01-20T15:30:00.000000+00:00",
  "playerCount": 15,
  "players": [
    {
      "jersey_number": "23",
      "full_name": "LeBron James",
      "full_name_ascii": "LeBron James",
      "last_name": "James",
      "normalized": "lebron james",
      "suffix": "",
      "position": "SF",
      "height": "6-9",
      "weight": "250"
    }
  ],
  "source_url": "https://www.basketball-reference.com/teams/LAL/2025.html",
  "name_processing": {
    "enhanced": true,
    "suffix_handling": true,
    "normalization": true,
    "unicode_handling": true,
    "version": "2.1"
  }
}
```

#### Unicode Handling

International player names are normalized:
- `Dāvis Bertāns` -> `Davis Bertans`
- `Bogdan Bogdanović` -> `Bogdan Bogdanovic`
- `Nikola Jokić` -> `Nikola Jokic`

#### Edge Cases

| Fixture | Description |
|---------|-------------|
| `br_roster_unicode.html` | Players with international names |
| `br_roster_suffix.html` | Players with Jr., Sr., II, III |
| `br_roster_multi_number.html` | Players who changed jersey numbers |
| `br_roster_empty.html` | No roster table found |

---

## Error Response Formats

### HTTP Error Responses

```json
{
  "error": "Request failed with status code 429",
  "status_code": 429,
  "message": "Rate limit exceeded"
}
```

### API Error Responses

BallDontLie API error:
```json
{
  "error": {
    "message": "Invalid API key",
    "status": 401
  }
}
```

The Odds API error:
```json
{
  "message": "Invalid API key"
}
```

NBA.com error (empty result):
```json
{
  "resultSets": []
}
```

---

## Creating New Fixtures

### Using the Capture Tool

The recommended way to create new fixtures is using the capture tool:

```bash
# Capture raw and expected output for a scraper
python tools/fixtures/capture.py bdl_games \
    --startDate 2025-01-15 --endDate 2025-01-16 \
    --debug

# Files created:
# /tmp/raw_<run_id>.json    - Raw API response
# /tmp/exp_<run_id>.json    - Transformed output
```

### Fixture Naming Convention

```
<scraper_name>_<variant>.json

Examples:
- bdl_games_raw.json           # Standard raw response
- bdl_games_empty.json         # Empty data edge case
- bdl_games_paginated.json     # Multi-page response
- espn_boxscore_raw.html       # HTML source file
- espn_boxscore_expected.json  # Expected parsed output
```

### Fixture File Structure

Each fixture should include:

1. **Raw Response** (`*_raw.json` or `*_raw.html`)
   - Exact API/HTML response
   - Preserves original structure

2. **Expected Output** (`*_expected.json`)
   - Transformed data structure
   - Matches `self.data` after `transform_data()`

3. **Edge Case Variants** (as needed)
   - Empty responses
   - Error responses
   - Pagination scenarios
   - Special game types

---

## Test Usage Examples

### Unit Test with Fixtures

```python
import json
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scrapers"

class TestBdlGamesScraper:
    @pytest.fixture
    def raw_response(self):
        fixture_path = FIXTURES_DIR / "balldontlie" / "bdl_games_raw.json"
        with open(fixture_path) as f:
            return json.load(f)

    @pytest.fixture
    def expected_output(self):
        fixture_path = FIXTURES_DIR / "balldontlie" / "bdl_games_expected.json"
        with open(fixture_path) as f:
            return json.load(f)

    def test_transform_data(self, raw_response, expected_output):
        # Mock the scraper with raw response
        scraper = BdlGamesScraper()
        scraper.decoded_data = raw_response
        scraper.opts = {"startDate": "2025-01-19", "endDate": "2025-01-21"}

        # Run transform
        scraper.transform_data()

        # Verify output structure
        assert scraper.data["gameCount"] == expected_output["gameCount"]
        assert len(scraper.data["games"]) == len(expected_output["games"])
```

### Parameterized Tests with Edge Cases

```python
@pytest.mark.parametrize("fixture_name,expected_count", [
    ("bdl_games_raw.json", 1),
    ("bdl_games_empty.json", 0),
    ("bdl_games_paginated.json", 25),
])
def test_game_counts(fixture_name, expected_count):
    fixture_path = FIXTURES_DIR / "balldontlie" / fixture_name
    with open(fixture_path) as f:
        data = json.load(f)

    assert len(data.get("data", [])) == expected_count
```

---

## Maintenance

### Updating Fixtures

When APIs change their response format:

1. Run capture tool against live API
2. Compare with existing fixtures
3. Update fixtures and expected outputs
4. Update this documentation

### Version Control

Fixtures should be committed to git:
- Track API changes over time
- Enable offline testing
- Support CI/CD pipelines

---

## Related Documentation

- [Scraper Base Architecture](./SCRAPER-ARCHITECTURE.md)
- [Registry System](./SCRAPER-REGISTRY.md)
- [Testing Guide](./TESTING.md)
