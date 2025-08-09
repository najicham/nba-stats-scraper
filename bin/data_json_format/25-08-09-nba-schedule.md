# NBA Schedule JSON Format Documentation

**Version:** 1.0  
**Date:** August 2025  
**Source:** NBA.com Stats API (`scheduleleaguev2int`)

## Overview

The NBA schedule JSON contains comprehensive game data for an entire NBA season, including regular season games, playoffs, All-Star events, and preseason games. This document describes the structure and fields based on analysis of actual NBA.com API responses.

## Top-Level Structure

```json
{
  "season": "2023",
  "season_nba_format": "2023-24", 
  "seasonYear": "2024",
  "leagueId": "00",
  "timestamp": "2025-08-04T00:09:45.275610+00:00",
  "meta": {},
  "game_count": 1484,
  "date_count": 177,
  "games": [...],  // Flattened array of all games
  "gameDates": [...] // Original nested structure by date
}
```

### Top-Level Fields

- **`season`**: Input season year (e.g., "2023" for 2023-24 season)
- **`season_nba_format`**: NBA's season format (e.g., "2023-24")
- **`seasonYear`**: NBA's internal season year
- **`game_count`**: Total number of games in the schedule
- **`date_count`**: Number of unique game dates
- **`games`**: Flattened array of all games, sorted chronologically
- **`gameDates`**: Original nested structure grouping games by date

## Game Object Structure

Each game in the `games` array contains the following fields:

### Core Game Identification

```json
{
  "gameId": "0022300001",
  "gameCode": "20231018/PHXGSW",
  "gameStatus": 3,
  "gameStatusText": "Final",
  "gameSequence": 1
}
```

- **`gameId`**: NBA's unique game identifier
  - **Format**: `TTSSSSSSSS` where:
    - `TT` = Game type: `00` (preseason), `01` (regular), `03` (All-Star), `04` (playoffs)
    - `SSSSSSSS` = Sequential game number
- **`gameCode`**: Date and team code (`YYYYMMDD/AWAYTEAMHOMETEAM`)
- **`gameStatus`**: Numeric status (1=scheduled, 2=live, 3=final)
- **`gameStatusText`**: Human-readable status
- **`gameSequence`**: Order of games on the same date

### Date and Time Fields

```json
{
  "gameDateEst": "2023-10-18T00:00:00Z",
  "gameTimeEst": "1900-01-01T22:30:00Z", 
  "gameDateTimeEst": "2023-10-18T22:30:00Z",
  "gameDateUTC": "2023-10-18T04:00:00Z",
  "gameTimeUTC": "1900-01-01T02:30:00Z",
  "gameDateTimeUTC": "2023-10-19T02:30:00Z",
  "awayTeamTime": "2023-10-18T19:30:00Z",
  "homeTeamTime": "2023-10-18T22:30:00Z",
  "gameDate": "10/18/2023 00:00:00",
  "gameDateObj": "10/18/2023 00:00:00"
}
```

#### 🚨 **Critical Sorting Note**

**ALWAYS use `gameDateEst` for chronological sorting, NOT `gameDate`!**

- **`gameDateEst`**: ISO format (`2023-10-18T00:00:00Z`) - sorts correctly ✅
- **`gameDate`**: MM/DD/YYYY format (`10/18/2023 00:00:00`) - sorts incorrectly ❌

**Example sorting issue:**
```
❌ WRONG (using gameDate):
"01/01/2023" → "06/12/2023" → "09/30/2022" (Sept 2022 sorts AFTER June 2023!)

✅ CORRECT (using gameDateEst): 
"2022-09-30T00:00:00Z" → "2023-01-01T00:00:00Z" → "2023-06-12T00:00:00Z"
```

#### Date Field Descriptions

- **`gameDateEst`**: Game date in Eastern Time (ISO format) - **USE FOR SORTING**
- **`gameTimeEst`**: Game time only (Eastern Time)
- **`gameDateTimeEst`**: Combined date and time (Eastern Time)
- **`gameDateUTC`**: Game date in UTC
- **`gameTimeUTC`**: Game time only (UTC)
- **`gameDateTimeUTC`**: Combined date and time (UTC)
- **`awayTeamTime`**: Game time in away team's timezone
- **`homeTeamTime`**: Game time in home team's timezone
- **`gameDate`**: Legacy MM/DD/YYYY format (for display only)
- **`gameDateObj`**: Duplicate of `gameDate`

### Season Context

```json
{
  "day": "Wed",
  "monthNum": 10,
  "weekNumber": 1,
  "weekName": "Week 1"
}
```

- **`day`**: Day of week abbreviation
- **`monthNum`**: Month number (1-12)
- **`weekNumber`**: NBA week number (starts from 1, resets to 0 for playoffs)
- **`weekName`**: NBA week name or special event name

### Game Type Classification

```json
{
  "gameLabel": "NBA Finals",
  "gameSubLabel": "Game 4",
  "seriesGameNumber": "Game 4",
  "weekName": "All-Star"
}
```

#### 🔍 **How to Identify Game Types**

**Regular Season Games:**
```json
{
  "gameId": "0022300001",  // Starts with "002"
  "weekName": "Week 15",   // "Week N" format
  "gameLabel": "",         // Empty
  "gameSubLabel": ""       // Empty
}
```

**All-Star Games:**
```json
{
  "gameId": "0032300006",     // Starts with "003"
  "weekName": "All-Star",     // Exactly "All-Star" 🎯
  "gameLabel": "Rising Stars Final",
  "gameSubLabel": "Championship"
}
```

**Playoff Games:**
```json
{
  "gameId": "0042300405",     // Starts with "004"
  "weekName": "",             // Usually empty
  "gameLabel": "NBA Finals",
  "gameSubLabel": "Game 5"
}
```

**Preseason Games:**
```json
{
  "gameId": "0012300001",     // Starts with "001"
  "weekName": "",             // Usually empty
  "gameLabel": "",            // Usually empty
  "gameSubLabel": ""          // Usually empty
}
```

#### 🛡️ **Filtering Logic for Gamebook Collection**

```python
def should_process_game(game):
    """Determine if game should be processed for gamebook collection."""
    
    # Check game ID type
    game_id = game.get('gameId', '')
    if game_id.startswith('001'):  # Preseason
        return False
    if game_id.startswith('003'):  # All-Star
        return False  
    if game_id.startswith('004'):  # Playoffs (optional - you might want these)
        return False
    
    # Check for All-Star indicators
    week_name = game.get('weekName', '')
    if week_name == "All-Star":
        return False
    
    # Check for special events
    game_label = game.get('gameLabel', '')
    game_sub_label = game.get('gameSubLabel', '')
    if game_label or game_sub_label:
        return False
    
    # Validate team codes
    away_team = game.get('awayTeam', {}).get('teamTricode', '')
    home_team = game.get('homeTeam', {}).get('teamTricode', '')
    
    valid_nba_teams = {
        'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
        'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
        'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
    }
    
    if away_team not in valid_nba_teams or home_team not in valid_nba_teams:
        return False
    
    # Only process completed games
    return game.get('gameStatus') == 3
```

### Arena Information

```json
{
  "arenaName": "Chase Center",
  "arenaState": "CA", 
  "arenaCity": "San Francisco",
  "isNeutral": false
}
```

- **`arenaName`**: Venue name
- **`arenaState`**: State/province abbreviation (empty for international games)
- **`arenaCity`**: City name
- **`isNeutral`**: Whether it's a neutral site game

### Team Information

Each game contains `homeTeam` and `awayTeam` objects:

```json
{
  "homeTeam": {
    "teamId": 1610612744,
    "teamName": "Warriors",
    "teamCity": "Golden State", 
    "teamTricode": "GSW",
    "teamSlug": "warriors",
    "wins": 42,
    "losses": 17,
    "score": 123,
    "seed": 0
  }
}
```

- **`teamId`**: NBA's unique team identifier
- **`teamName`**: Team nickname (e.g., "Warriors")
- **`teamCity`**: Team city (e.g., "Golden State")
- **`teamTricode`**: 3-letter team code (e.g., "GSW") - **CRITICAL FOR GAME CODES**
- **`teamSlug`**: URL-friendly team name
- **`wins`**: Team wins at time of game
- **`losses`**: Team losses at time of game  
- **`score`**: Final score (if game completed)
- **`seed`**: Playoff seeding (0 for regular season)

### Game Status Flags

```json
{
  "ifNecessary": false,
  "postponedStatus": "A",
  "gameSubtype": ""
}
```

- **`ifNecessary`**: Whether this is an "if necessary" playoff game
- **`postponedStatus`**: Postponement status ("A" = as scheduled)
- **`gameSubtype`**: Additional game classification

### External References

```json
{
  "branchLink": "https://app.link.nba.com/...",
}
```

- **`branchLink`**: Deep link to NBA app (removed in our processing to keep files lean)

## Data Processing Notes

### Removed Fields

To keep schedule files lean, the following fields are removed during processing:
- `broadcasters`: TV/radio broadcast information
- `tickets`: Ticket sales links  
- `links`: Various external links
- `promotions`: Marketing promotions
- `seriesText`: Series description text
- `pointsLeaders`: Leading scorers (redundant with other data)

### Sorting Implementation

```python
# Correct sorting for chronological order:
all_games.sort(key=lambda x: (x.get("gameDateEst", ""), x.get("gameSequence", 0)))
```

### Common Data Issues

1. **Mixed Game Types**: Schedules contain regular season, playoffs, All-Star, and preseason games mixed together
2. **Date Format Confusion**: Multiple date fields in different formats
3. **Team Code Validation**: All-Star games have fake team codes like "PAU", "JKM"
4. **Empty Fields**: Many optional fields are empty strings rather than null

## Usage Examples

### Extract Regular Season Games Only

```python
regular_season_games = [
    game for game in schedule_data['games']
    if game.get('gameId', '').startswith('002') and  # Regular season
       game.get('weekName', '').startswith('Week') and  # Not All-Star
       not game.get('gameLabel') and  # No special events
       game.get('gameStatus') == 3  # Completed games only
]
```

### Sort Games Chronologically

```python
# Always use gameDateEst for proper chronological sorting
games.sort(key=lambda x: (x.get("gameDateEst", ""), x.get("gameSequence", 0)))
```

### Generate Game Codes

```python
def extract_game_code(game):
    """Extract properly formatted game code."""
    game_code = game.get('gameCode', '')
    if not game_code or '/' not in game_code:
        return None
    
    # Validate format: YYYYMMDD/TEAMTEAM
    date_part, teams_part = game_code.split('/', 1)
    if len(date_part) != 8 or len(teams_part) != 6:
        return None
        
    return game_code
```

## Error Prevention

### All-Star Weekend Errors

**Problem**: All-Star games generate corrupted game codes like `20230217/JKMPAU` that cause HTTP 500 errors when trying to fetch gamebooks.

**Solution**: Filter out using the classification logic above.

### Sorting Errors

**Problem**: Using `gameDate` field causes games to sort out of chronological order.

**Solution**: Always use `gameDateEst` field for sorting.

### Invalid Team Codes

**Problem**: Special events use fake team codes that don't correspond to real NBA teams.

**Solution**: Validate team tricodes against the list of 30 valid NBA team codes.

---

**This documentation reflects the actual NBA schedule JSON structure as of the 2023-24 season and should be updated as the API evolves.**
