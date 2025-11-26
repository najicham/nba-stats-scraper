# NBA Data Sources - Response Structures & Field Reference

## Overview

This document provides detailed analysis of response structures from all 22 NBA data scrapers. Use this reference for processor development, data validation, and understanding cross-source relationships.

## Document Purpose

- **Processor Development**: Exact field names and data types for mapping
- **Data Validation**: Expected formats and required fields
- **Cross-Referencing**: How to link entities across different APIs
- **Schema Mapping**: API responses → BigQuery table columns
- **Quality Assurance**: Known data quirks and edge cases

---

## Ball Don't Lie API Response Structures

### BdlGamesScraper - NBA Games

#### **Sample Response Structure**
```json
{
  "startDate": "2025-02-20",
  "endDate": "2025-02-20", 
  "timestamp": "2025-07-17T14:30:00Z",
  "gameCount": 2,
  "games": [
    {
      "id": 15908525,
      "date": "2025-02-20",
      "season": 2024,
      "status": "Final",
      "period": 4,
      "time": "Final",
      "postseason": false,
      "home_team_score": 129,
      "visitor_team_score": 115,
      "datetime": "2025-02-21T02:00:00.000Z",
      "home_team": {
        "id": 8,
        "conference": "West",
        "division": "Northwest", 
        "city": "Denver",
        "name": "Nuggets",
        "full_name": "Denver Nuggets",
        "abbreviation": "DEN"
      },
      "visitor_team": {
        "id": 4,
        "conference": "East",
        "division": "Southeast",
        "city": "Charlotte", 
        "name": "Hornets",
        "full_name": "Charlotte Hornets",
        "abbreviation": "CHA"
      }
    }
  ]
}
```

#### **Key Fields Analysis**
| **Field** | **Type** | **Description** | **Business Critical** | **Notes** |
|-----------|----------|-----------------|----------------------|-----------|
| `games[].id` | Integer | Game ID (primary key) | ✅ **CRITICAL** | For linking across sources |
| `games[].date` | String | Game date (ET) | ✅ **CRITICAL** | Format: "YYYY-MM-DD" |
| `games[].datetime` | String | Game time (UTC) | ✅ **CRITICAL** | ISO format with timezone |
| `games[].status` | String | Game status | ✅ **CRITICAL** | "Final", "In Progress", etc. |
| `games[].home_team.abbreviation` | String | Team abbreviation | ✅ **CRITICAL** | Standardization key |
| `games[].visitor_team.abbreviation` | String | Team abbreviation | ✅ **CRITICAL** | Standardization key |
| `games[].home_team_score` | Integer | Final score | Important | NULL for upcoming games |
| `games[].visitor_team_score` | Integer | Final score | Important | NULL for upcoming games |

#### **Cross-Reference Opportunities**
- **Game Linking**: Use `id` + `date` + team abbreviations to link with other sources
- **Team Matching**: `abbreviation` field matches ESPN and NBA.com formats
- **Time Correlation**: `datetime` for matching with Odds API `commence_time`

#### **Data Quality Notes**
- **Consistent abbreviations** across all NBA teams
- **UTC timestamps** require timezone conversion for ET display
- **Score fields** are NULL for upcoming/postponed games
- **Season field** represents the season start year (2024 = 2024-25 season)

---

### BdlPlayerBoxScoresScraper - Player Statistics

#### **Sample Response Structure**
```json
{
  "data": [
    {
      "id": 20743640,
      "min": "38",
      "fgm": 7,
      "fga": 20,
      "fg_pct": 0.35,
      "fg3m": 2,
      "fg3a": 7,
      "fg3_pct": 0.2857143,
      "ftm": 4,
      "fta": 6,
      "ft_pct": 0.6666667,
      "oreb": 0,
      "dreb": 4,
      "reb": 4,
      "ast": 4,
      "stl": 2,
      "blk": 0,
      "turnover": 1,
      "pf": 4,
      "pts": 20,
      "player": {
        "id": 38017703,
        "first_name": "Jalen",
        "last_name": "Williams",
        "position": "G-F",
        "height": "6-5",
        "weight": "211",
        "jersey_number": "8",
        "college": "Santa Clara",
        "country": "USA",
        "draft_year": 2022,
        "draft_round": 1,
        "draft_number": 12,
        "team_id": 21
      },
      "team": {
        "id": 21,
        "abbreviation": "OKC"
      },
      "game": {
        "id": 18444564,
        "date": "2025-06-22",
        "season": 2024,
        "status": "Final",
        "postseason": true,
        "home_team_score": 103,
        "visitor_team_score": 91,
        "home_team_id": 21,
        "visitor_team_id": 12
      }
    }
  ]
}
```

#### **Key Fields Analysis**
| **Field** | **Type** | **Description** | **Business Critical** | **Notes** |
|-----------|----------|-----------------|----------------------|-----------|
| `data[].id` | Integer | Boxscore record ID | Important | Unique per player-game |
| `data[].pts` | Integer | **Points scored** | ✅ **CRITICAL** | **Primary prop bet stat** |
| `data[].reb` | Integer | Total rebounds | ✅ **CRITICAL** | **Future prop expansion** |
| `data[].ast` | Integer | Assists | ✅ **CRITICAL** | **Future prop expansion** |
| `data[].player.id` | Integer | Player ID | ✅ **CRITICAL** | Cross-reference key |
| `data[].player.first_name` | String | Player first name | ✅ **CRITICAL** | For Odds API matching |
| `data[].player.last_name` | String | Player last name | ✅ **CRITICAL** | For Odds API matching |
| `data[].team.abbreviation` | String | Team abbreviation | ✅ **CRITICAL** | Team context |
| `data[].game.id` | Integer | Game ID | ✅ **CRITICAL** | Links to games table |

#### **Cross-Reference Strategy**
- **Player Matching**: `player.id` + `first_name + last_name` for Odds API
- **Game Linking**: `game.id` matches BdlGamesScraper IDs
- **Team Validation**: `team.abbreviation` for consistency checks

#### **Data Quality Notes**
- **Minutes format**: String "38" not integer (requires parsing)
- **Percentage fields**: Decimal format (0.35 = 35%)
- **Team context**: Includes both player's team and game opponents
- **Nested objects**: Player, team, and game data embedded

---

### BdlInjuriesScraper - Player Injuries

#### **Sample Response Structure**
```json
{
  "data": [
    {
      "player": {
        "id": 434,
        "first_name": "Jayson",
        "last_name": "Tatum",
        "position": "F",
        "height": "6-8",
        "weight": "210",
        "jersey_number": "0",
        "college": "Duke",
        "country": "USA",
        "draft_year": 2017,
        "draft_round": 1,
        "draft_number": 3,
        "team_id": 2
      },
      "return_date": "Feb 1",
      "description": "Jul 3: Tatum will miss the rest of the season after undergoing surgery to repair a torn left Achilles tendon Tuesday, Shams Charania of ESPN reports.",
      "status": "Out"
    }
  ]
}
```

#### **Key Fields Analysis**
| **Field** | **Type** | **Description** | **Business Critical** | **Notes** |
|-----------|----------|-----------------|----------------------|-----------|
| `data[].player.id` | Integer | Player ID | ✅ **CRITICAL** | Cross-reference key |
| `data[].status` | String | Injury status | ✅ **CRITICAL** | Affects prop availability |
| `data[].return_date` | String | Expected return | ✅ **CRITICAL** | Format: "Feb 1", "Jul 17" |
| `data[].description` | String | Injury details | Important | Full injury context |
| `data[].player.team_id` | Integer | Team ID | ✅ **CRITICAL** | Team context |

#### **Status Values Observed**
- `"Out"` - Player unavailable
- `"Day-To-Day"` - Questionable availability
- `"Questionable"` - Game-time decision

#### **Business Impact for Props**
- **"Out" status** = No props available for player
- **"Day-To-Day"** = Props may be pulled closer to game time
- **Description parsing** can identify injury type and severity

---

## Odds API Response Structures (CORE BUSINESS DATA)

### GetOddsApiEvents - Betting Events

#### **Sample Response Structure**
```json
{
  "timestamp": "2025-03-09T23:55:38Z",
  "previous_timestamp": "2025-03-09T23:50:38Z",
  "next_timestamp": "2025-03-10T00:00:38Z",
  "data": [
    {
      "id": "242c77a8d5890e18bab91773ad32fcb5",
      "sport_key": "basketball_nba",
      "sport_title": "NBA",
      "commence_time": "2025-03-09T23:11:00Z",
      "home_team": "New Orleans Pelicans",
      "away_team": "Memphis Grizzlies"
    }
  ]
}
```

#### **Key Fields Analysis**
| **Field** | **Type** | **Description** | **Business Critical** | **Notes** |
|-----------|----------|-----------------|----------------------|-----------|
| `data[].id` | String | Event ID (hash) | ✅ **CRITICAL** | Required for props API |
| `data[].commence_time` | String | Game start time (UTC) | ✅ **CRITICAL** | For game matching |
| `data[].home_team` | String | Home team full name | ✅ **CRITICAL** | Requires mapping to abbreviations |
| `data[].away_team` | String | Away team full name | ✅ **CRITICAL** | Requires mapping to abbreviations |

#### **Team Name Mapping Examples**
| **Odds API Name** | **Standard Abbreviation** | **Mapping Challenge** |
|-------------------|---------------------------|----------------------|
| "Los Angeles Lakers" | "LAL" | Multiple LA teams |
| "New York Knicks" | "NYK" | vs "Brooklyn Nets" |
| "Los Angeles Clippers" | "LAC" | vs "Lakers" |

#### **Critical Dependency**
- **MUST run before GetOddsApiCurrentEventOdds**
- **Event IDs required** for all prop collection
- **Failure blocks entire prop betting pipeline**

---

### GetOddsApiCurrentEventOdds - Player Props (PRIMARY BUSINESS DATA)

#### **Sample Response Structure**
```json
{
  "timestamp": "2025-03-09T23:50:38Z",
  "data": {
    "id": "242c77a8d5890e18bab91773ad32fcb5",
    "sport_key": "basketball_nba",
    "home_team": "New Orleans Pelicans",
    "away_team": "Memphis Grizzlies",
    "bookmakers": [
      {
        "key": "fanduel",
        "title": "FanDuel",
        "last_update": "2025-03-09T23:49:20Z",
        "markets": [
          {
            "key": "player_points",
            "last_update": "2025-03-09T23:50:34Z",
            "outcomes": [
              {
                "name": "Over",
                "description": "Jaylen Wells",
                "price": 1.8,
                "point": 11.5
              },
              {
                "name": "Under", 
                "description": "Jaylen Wells",
                "price": 1.94,
                "point": 11.5
              },
              {
                "name": "Over",
                "description": "Desmond Bane",
                "price": 1.8,
                "point": 28.5
              },
              {
                "name": "Under",
                "description": "Desmond Bane", 
                "price": 1.94,
                "point": 28.5
              }
            ]
          }
        ]
      }
    ]
  }
}
```

#### **Key Fields Analysis**
| **Field** | **Type** | **Description** | **Business Critical** | **Notes** |
|-----------|----------|-----------------|----------------------|-----------|
| `data.id` | String | Event ID | ✅ **CRITICAL** | Links to events table |
| `bookmakers[].key` | String | Sportsbook identifier | ✅ **CRITICAL** | "fanduel", "draftkings" |
| `markets[].key` | String | Prop type | ✅ **CRITICAL** | "player_points", "player_rebounds" |
| `outcomes[].description` | String | **Player name** | ✅ **CRITICAL** | **ONLY player identifier** |
| `outcomes[].name` | String | Bet type | ✅ **CRITICAL** | "Over", "Under" |
| `outcomes[].point` | Float | Prop line | ✅ **CRITICAL** | 11.5, 28.5, etc. |
| `outcomes[].price` | Float | Decimal odds | ✅ **CRITICAL** | 1.8, 1.94, etc. |

#### **Player Name Matching Strategy**
| **Odds API Name** | **Ball Don't Lie Name** | **Matching Strategy** |
|-------------------|-------------------------|----------------------|
| "Jaylen Wells" | first_name: "Jaylen", last_name: "Wells" | Direct concatenation |
| "Desmond Bane" | first_name: "Desmond", last_name: "Bane" | Direct concatenation |
| "G.G. Jackson" | first_name: "GG", last_name: "Jackson" | Name variation handling |

#### **Business Logic**
- **Over/Under pairs**: Each player has both bets at same line
- **Multiple sportsbooks**: FanDuel + DraftKings for comparison
- **Line movement**: Track `price` changes over time
- **Market expansion**: Currently "player_points", future: rebounds, assists

#### **Data Quality Challenges**
- **Player names only** - No IDs provided
- **Name variations** - Nicknames, abbreviations, punctuation
- **Team context missing** - Must infer from event teams
- **Real-time updates** - Rapid odds changes

---

## ESPN Response Structures

### GetEspnTeamRosterAPI - Team Rosters

#### **Sample Response Structure**
```json
{
  "teamAbbr": "bos",
  "teamSlug": "boston-celtics",
  "season": "2025-26",
  "timestamp": "2025-06-19T23:05:36.294991+00:00",
  "playerCount": 17,
  "players": [
    {
      "number": "7",
      "name": "Jaylen Brown",
      "playerId": "3917376",
      "slug": "jaylen-brown",
      "fullUrl": "https://www.espn.com/nba/player/_/id/3917376/jaylen-brown",
      "position": "SG",
      "age": "28",
      "height": "6' 6\"",
      "weight": "223 lbs"
    }
  ]
}
```

#### **Key Fields Analysis**
| **Field** | **Type** | **Description** | **Business Critical** | **Notes** |
|-----------|----------|-----------------|----------------------|-----------|
| `teamAbbr` | String | Team abbreviation | ✅ **CRITICAL** | Lowercase format |
| `players[].playerId` | String | ESPN player ID | ✅ **CRITICAL** | Cross-reference key |
| `players[].name` | String | Full player name | ✅ **CRITICAL** | For Odds API matching |
| `players[].number` | String | Jersey number | Important | Cross-reference aid |
| `players[].position` | String | Player position | Important | Context for props |

#### **Data Format Notes**
- **Team abbreviation**: Lowercase ("bos" not "BOS")
- **Player ID**: String format vs Ball Don't Lie integers  
- **Height/Weight**: Formatted strings ("6' 6\"", "223 lbs")
- **Rich metadata**: URLs, slugs for ESPN integration

---

### GetEspnScoreboard - Game Scores

#### **Sample Response Structure**
```json
{
  "timestamp": "2025-07-17T17:16:27.235360+00:00",
  "scoreDate": "20240115",
  "gameCount": 11,
  "games": [
    {
      "gameId": "401585183",
      "statusId": "3",
      "state": "post",
      "status": "Final",
      "startTime": "2024-01-15T18:00Z",
      "teams": [
        {
          "teamId": "20",
          "displayName": "Philadelphia 76ers",
          "abbreviation": "PHI",
          "score": "124",
          "winner": true,
          "homeAway": "home"
        },
        {
          "teamId": "10", 
          "displayName": "Houston Rockets",
          "abbreviation": "HOU",
          "score": "115",
          "winner": false,
          "homeAway": "away"
        }
      ]
    }
  ]
}
```

#### **Key Fields Analysis**
| **Field** | **Type** | **Description** | **Business Critical** | **Notes** |
|-----------|----------|-----------------|----------------------|-----------|
| `games[].gameId` | String | ESPN game ID | ✅ **CRITICAL** | Cross-reference key |
| `games[].status` | String | Game status | ✅ **CRITICAL** | "Final", "In Progress" |
| `teams[].abbreviation` | String | Team abbreviation | ✅ **CRITICAL** | Matches other sources |
| `teams[].score` | String | Final score | Important | String format |
| `teams[].winner` | Boolean | Game winner | Important | Result indicator |

---

## NBA.com Response Structures (Official Data)

### GetNbaComPlayerList - Master Player Database

#### **Sample Response Structure**
```json
{
  "resource": "playerindex",
  "parameters": {
    "LeagueID": "00",
    "Season": "2025-26",
    "Historical": 0
  },
  "resultSets": [
    {
      "name": "PlayerIndex",
      "headers": [
        "PERSON_ID", "PLAYER_LAST_NAME", "PLAYER_FIRST_NAME", 
        "PLAYER_SLUG", "TEAM_ID", "TEAM_SLUG", "TEAM_ABBREVIATION",
        "JERSEY_NUMBER", "POSITION", "HEIGHT", "WEIGHT", 
        "COLLEGE", "COUNTRY", "DRAFT_YEAR", "DRAFT_ROUND", "DRAFT_NUMBER"
      ],
      "rowSet": [
        [
          1630173, "Achiuwa", "Precious", "precious-achiuwa",
          1610612752, "knicks", "NYK", "5", "F", "6-8", "243",
          "Memphis", "Nigeria", 2020, 1, 20, 1.0, "2020", "2025"
        ]
      ]
    }
  ]
}
```

#### **Key Fields Analysis (Array Position)**
| **Position** | **Header** | **Type** | **Description** | **Business Critical** |
|--------------|------------|----------|-----------------|----------------------|
| 0 | PERSON_ID | Integer | NBA.com player ID | ✅ **CRITICAL** |
| 1 | PLAYER_LAST_NAME | String | Last name | ✅ **CRITICAL** |
| 2 | PLAYER_FIRST_NAME | String | First name | ✅ **CRITICAL** |
| 6 | TEAM_ABBREVIATION | String | Team abbreviation | ✅ **CRITICAL** |
| 7 | JERSEY_NUMBER | String | Jersey number | Important |
| 8 | POSITION | String | Position | Important |

#### **Data Format Notes**
- **Array format**: Data as arrays mapped to headers
- **Official source**: Master NBA player database
- **Season filtered**: Auto-filters to current season
- **Comprehensive**: All active players with full details

---

### GetDataNbaSeasonSchedule - Comprehensive Schedule

#### **Sample Response Structure**
```json
{
  "meta": {
    "version": 1,
    "request": "http://nba.cloud/league/00/2024-25/scheduleleaguev2...",
    "time": "2025-07-11T19:31:05.315Z"
  },
  "leagueSchedule": {
    "seasonYear": "2024-25",
    "leagueId": "00",
    "gameDates": [
      {
        "gameDate": "10/04/2024 00:00:00",
        "games": [
          {
            "gameId": "0012400001",
            "gameCode": "20241004/BOSDEN",
            "gameStatus": 3,
            "gameStatusText": "Final",
            "gameDateTimeEst": "2024-10-04T12:00:00Z",
            "arenaName": "Etihad Arena",
            "arenaCity": "Abu Dhabi",
            "isNeutral": true,
            "homeTeam": {
              "teamId": 1610612743,
              "teamTricode": "DEN",
              "score": 103
            },
            "awayTeam": {
              "teamId": 1610612738,
              "teamTricode": "BOS", 
              "score": 107
            }
          }
        ]
      }
    ]
  }
}
```

#### **Key Fields Analysis**
| **Field** | **Type** | **Description** | **Business Critical** | **Notes** |
|-----------|----------|-----------------|----------------------|-----------|
| `games[].gameId` | String | NBA.com game ID | ✅ **CRITICAL** | Format: "0012400001" |
| `games[].gameStatus` | Integer | Status code | ✅ **CRITICAL** | 1=Scheduled, 3=Final |
| `games[].homeTeam.teamTricode` | String | Team abbreviation | ✅ **CRITICAL** | Matches other sources |
| `games[].awayTeam.teamTricode` | String | Team abbreviation | ✅ **CRITICAL** | Matches other sources |

---

### GetNbaComInjuryReport - Official Game Availability

#### **Sample Response Structure**
```json
[
  {
    "date": "03/15/25",
    "gametime": "06:00 (ET)",
    "matchup": "BOS@BKN",
    "team": "Nets",
    "player": "Claxton, Nic",
    "status": "Out",
    "reason": "Rest"
  },
  {
    "date": "03/15/25",
    "gametime": "06:00 (ET)", 
    "matchup": "BOS@BKN",
    "team": "Nets",
    "player": "Melton, De'Anthony",
    "status": "Out",
    "reason": "Injury/Illness Left Knee; ACL Tear"
  }
]
```

#### **Key Fields Analysis**
| **Field** | **Type** | **Description** | **Business Critical** | **Notes** |
|-----------|----------|-----------------|----------------------|-----------|
| `player` | String | Player name | ✅ **CRITICAL** | Format: "Last, First" |
| `status` | String | Availability status | ✅ **CRITICAL** | Game-specific availability |
| `reason` | String | Reason for status | ✅ **CRITICAL** | Rest vs injury distinction |
| `matchup` | String | Game matchup | ✅ **CRITICAL** | Links to specific game |

#### **Status Categories**
- **"Out"** - Player unavailable
- **"Questionable"** - Game-time decision  
- **"Probable"** - Likely to play

#### **Reason Categories**
- **"Rest"** - Load management
- **"Injury/Illness [Body Part]; [Type]"** - Actual injury
- **"G League - Two Way"** - Player assignment

#### **Business Impact for Props**
- **Game-specific availability** - Exactly what prop betting needs
- **Rest vs injury** - Different implications for betting strategy
- **Official source** - NBA's official pre-game report

---

### GetNbaComScoreboardV2 - Enhanced Game Data

#### **Sample Response Structure**
```json
{
  "scoreboard": {
    "games": [
      {
        "gameId": "0022300555",
        "gameStatus": 3,
        "gameStatusText": "Final",
        "homeTeam": {
          "teamTricode": "PHI",
          "points": 124,
          "quarters": {
            "q1": 33, "q2": 33, "q3": 32, "q4": 26
          },
          "stats": {
            "fgPct": 0.482,
            "ftPct": 0.853,
            "fg3Pct": 0.484,
            "assists": 25,
            "rebounds": 41,
            "turnovers": 10
          }
        },
        "awayTeam": {
          "teamTricode": "HOU",
          "points": 115,
          "quarters": {
            "q1": 19, "q2": 28, "q3": 30, "q4": 38
          }
        }
      }
    ]
  }
}
```

#### **Unique Value vs Other Sources**
- **Quarter-by-quarter scoring** - Not available elsewhere
- **Game-level team stats** - Shooting percentages, team totals
- **Live game data** - For in-progress games

---

## Cross-Source Entity Linking Examples

### **Player Cross-Reference Example: Jaylen Brown**

| **Source** | **ID** | **Name Format** | **Team** | **Additional Context** |
|------------|--------|-----------------|----------|----------------------|
| **Ball Don't Lie** | `434` | `"Jaylen"` + `"Brown"` | `"BOS"` | Position: "G-F" |
| **ESPN** | `"3917376"` | `"Jaylen Brown"` | `"bos"` | Height: "6' 6\"" |
| **NBA.com** | `201935` | `"Jaylen"` + `"Brown"` | `"BOS"` | Jersey: "7" |
| **Odds API** | N/A | `"Jaylen Brown"` | Via event teams | Props available |

#### **Matching Strategy**
1. **Primary**: `first_name + last_name + team_abbreviation`
2. **Secondary**: Jersey number validation
3. **Tertiary**: Position and physical attributes

### **Game Cross-Reference Example: LAL vs BOS**

| **Source** | **Game ID** | **Date** | **Teams** | **Status** |
|------------|-------------|----------|-----------|-----------|
| **Ball Don't Lie** | `15908525` | `"2025-02-20"` | `"LAL"` vs `"BOS"` | `"Final"` |
| **ESPN** | `"401585183"` | `"2024-01-15"` | `"LAL"` vs `"BOS"` | `"Final"` |
| **NBA.com** | `"0022400500"` | `"2025-01-07"` | `"LAL"` vs `"BOS"` | `3` (Final) |
| **Odds API** | `"242c77a8d5..."` | `"2025-03-09T23:11:00Z"` | `"Los Angeles Lakers"` vs `"Boston Celtics"` | Event |

#### **Linking Strategy**
1. **Date matching**: Convert all to same timezone and format
2. **Team matching**: Map full names to abbreviations
3. **Time correlation**: Account for timezone differences
4. **Status validation**: Ensure game states align

---

## Processor Development Guidelines

### **Data Validation Checklist**

#### **Required Field Validation**
```python
# Example validation for player props
def validate_player_prop(prop_data):
    required_fields = [
        'description',  # Player name
        'point',        # Prop line
        'price',        # Odds
        'name'          # Over/Under
    ]
    for field in required_fields:
        if field not in prop_data or prop_data[field] is None:
            raise ValidationError(f"Missing required field: {field}")
```

#### **Cross-Reference Validation**
```python
# Example player matching validation
def validate_player_match(odds_name, db_player, confidence_threshold=0.8):
    # Name similarity check
    similarity = calculate_name_similarity(odds_name, db_player.full_name)
    
    # Team validation
    team_match = validate_team_context(odds_name, db_player.team_abbr)
    
    # Overall confidence
    confidence = (similarity * 0.7) + (team_match * 0.3)
    
    return confidence >= confidence_threshold
```

### **Error Handling Patterns**

#### **Missing Data Scenarios**
- **Player not found**: Log for manual review, continue processing
- **Game not linked**: Process props but flag for later linking
- **Invalid odds format**: Skip record, log error details
- **Team mapping failure**: Use fallback mapping or manual intervention

#### **Data Quality Monitoring**
```python
# Track processing quality metrics
quality_metrics = {
    'player_match_rate': matched_players / total_players,
    'game_link_rate': linked_games / total_games,
    'data_completeness': complete_records / total_records,
    'processing_errors': error_count / total_processed
}
```

---

## Business Logic Implementation

### **Prop Betting Data Flow**
1. **Events API** → Extract event IDs and team names
2. **Team mapping** → Convert full names to abbreviations  
3. **Game linking** → Match events to games table
4. **Props API** → Collect prop odds using event IDs
5. **Player matching** → Link prop player names to player IDs
6. **Odds tracking** → Store current odds and track changes

### **Player Availability Logic**
```python
# Determine player availability for props
def determine_prop_availability(player_id, game_date):
    # Check NBA.com game-specific injury report
    game_status = get_game_injury_status(player_id, game_date)
    if game_status in ['Out']:
        return 'unavailable'
    
    # Check general injury status
    general_status = get_general_injury_status(player_id)
    if general_status in ['Out']:
        return 'questionable'
    
    return 'available'
```

### **Data Freshness Requirements**
- **Betting Events**: Update every 5 minutes during active hours
- **Player Props**: Update every 2 minutes when markets are active
- **Injury Reports**: Update hourly on game days
- **Game Results**: Update within 10 minutes of game completion

---

## Implementation Priorities

### **Phase 1: Core Data Quality**
1. **Team standardization** - Ensure consistent abbreviations
2. **Player cross-referencing** - Build reliable ID mapping
3. **Game linking** - Connect games across all sources

### **Phase 2: Betting Pipeline** 
1. **Events processing** - Foundation for all prop data
2. **Props processing** - Core business value
3. **Player matching** - Critical for prop analysis

### **Phase 3: Performance Integration**
1. **Boxscores processing** - Historical performance context
2. **Injury integration** - Player availability tracking
3. **Analytics foundation** - Link performance to prop outcomes

---

## Conclusion

This response structure reference provides the foundation for implementing robust processors that can handle the complexity of NBA data across multiple sources. The key to success is:

1. **Reliable cross-referencing** between different ID systems
2. **Consistent data validation** across all sources
3. **Graceful error handling** for missing or invalid data
4. **Business logic alignment** with prop betting requirements
5. **Quality monitoring** to ensure data accuracy over time

Use this document alongside the main pipeline reference for complete implementation guidance.
