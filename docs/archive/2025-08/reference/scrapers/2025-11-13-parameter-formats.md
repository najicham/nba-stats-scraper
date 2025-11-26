# NBA Scrapers - Parameter Formats Reference

**Created:** 2025-11-13
**Purpose:** Exact parameter format documentation for all NBA scrapers
**Source:** Code-verified from scraper source files (November 2025)
**Note:** File paths and validation logic documented; line numbers omitted to prevent documentation drift

---

## Overview

This document provides the **exact parameter formats** for all scrapers, verified directly from the source code. Each entry includes:
- ✅ **Verified** `required_opts` and `optional_params` from scraper classes
- ✅ **Source file paths** for reference
- ✅ **Actual default values** when parameters are omitted
- ✅ **Validation logic descriptions** (without line numbers to avoid drift)
- ✅ **Parameter name variations** (snake_case vs camelCase)

Use this guide to ensure correct parameter values when calling scrapers directly, writing backfill scripts, or debugging parameter validation errors.

---

## Common Parameter Patterns

### **Season Parameters**

#### **Pattern**: `season`

**Format Variations:**
- **4-digit year** (preferred for most scrapers): `"2025"` (represents 2025-26 season)
- **NBA format**: `"2025-26"` (some scrapers accept, some auto-convert)

**Scrapers Using Season Parameter:**
- `GetNbaComScheduleApi`: **4-digit year** (e.g., `2025`), auto-converts to `2025-26`
- `GetNbaComPlayerBoxscore`: 4-digit year or NBA format, auto-converts internally
- `BasketballRefSeasonRoster`: **Ending year** (e.g., `2024` for 2023-24 season)

**Examples:**
```python
# NBA.com Schedule API
opts = {"season": "2025"}  # ✅ Correct - represents 2025-26 season

# Basketball Reference Season Roster
opts = {"year": "2024"}    # ✅ Correct - represents 2023-24 season
```

---

### **Date Parameters**

Multiple date parameter names exist across scrapers. Most are flexible about format:

#### **`gamedate` (NBA.com scrapers)**
- **Format**: `YYYYMMDD` or `YYYY-MM-DD` (both accepted, normalized internally)
- **Examples**:
  - `"20250115"` ✅
  - `"2025-01-15"` ✅
- **Scrapers**:
  - `GetNbaComScoreboardV2`
  - `GetNbaComPlayByPlay`
  - `GetNbaComPlayerBoxscore`
  - `GetEspnScoreboard`

#### **`game_date` (Odds API scrapers)**
- **Format**: `YYYY-MM-DD` (strict format)
- **Examples**: `"2025-01-15"` ✅
- **Auto-calculation**: Converts to Eastern timezone day boundaries → UTC for API
- **Scrapers**:
  - `GetOddsApiEvents`
  - `GetOddsApiCurrentEventOdds`

#### **`date` (Generic date parameter)**
- **Format**: `YYYY-MM-DD` (standard across most scrapers)
- **Examples**: `"2025-01-15"` ✅
- **Scrapers**:
  - `BettingProsEvents`
  - `BettingProsPlayerProps`
  - `BdlBoxScoresScraper`
  - `GetNbaComGamebooks`

#### **`startDate` / `endDate` (Range parameters)**
- **Format**: `YYYY-MM-DD`
- **Examples**:
  - `startDate="2025-01-15"` ✅
  - `endDate="2025-01-16"` ✅
- **Defaults**: Auto-calculated if not provided
- **Scrapers**:
  - `BdlGamesScraper`: Defaults to yesterday → tomorrow if not specified

---

### **Game Identifier Parameters**

#### **`game_id` (NBA.com Game ID)**
- **Format**: 10-character string `00XXYYYYYY`
  - `00` = League code (NBA)
  - `XX` = Season type (e.g., `22` = regular season, `41` = playoffs)
  - `YYYYYY` = Sequential game number
- **Examples**:
  - `"0022400561"` ✅ (Regular season game)
  - `"0042400001"` ✅ (Playoff game)
- **Season Detection**: First 5 characters determine season (e.g., `00224` = 2024-25 season)
- **Scrapers**:
  - `GetNbaComPlayByPlay`
  - `BigDataBallPbpScraper`
  - `GetEspnBoxscore`

#### **`event_id` (Odds API Event ID)**
- **Format**: String from Events API response
- **Examples**: Varies by API provider
- **Dependency**: **Must** run `GetOddsApiEvents` first to obtain IDs
- **Scrapers**:
  - `GetOddsApiCurrentEventOdds`
  - `BettingProsPlayerProps` (comma-separated list)

---

### **Time Parameters**

#### **`hour` (12-hour format with period)**
- **Format**: Integer `1-12`
- **Companion**: Requires `period` parameter (`"AM"` or `"PM"`)
- **Examples**:
  - `hour=8, period="AM"` ✅
  - `hour=8, period="PM"` ✅
- **Scrapers**:
  - `GetNbaComInjuryReport`

#### **`hour24` (24-hour format)**
- **Format**: Integer `0-23`
- **Examples**:
  - `"08"` (8 AM)
  - `"20"` (8 PM)
- **Scrapers**: Currently not in active use, but supported by infrastructure

---

### **Team Parameters**

#### **`teamAbbr` (Team Abbreviation)**
- **Format**: 3-letter uppercase team code
- **Examples**:
  - `"LAL"` ✅ (Lakers)
  - `"BOS"` ✅ (Celtics)
  - `"GSW"` ✅ (Warriors)
- **Scrapers**:
  - `BasketballRefSeasonRoster`

---

### **Sport Parameters**

#### **`sport` (Sport Identifier)**
- **Format**: Snake-case sport name
- **Examples**:
  - `"basketball_nba"` ✅
- **Scrapers**:
  - `GetOddsApiEvents`
  - `GetOddsApiCurrentEventOdds`

---

### **Optional Enhancement Parameters**

#### **`season_type` (Season Phase)**
- **Format**: String (space-separated words)
- **Values**:
  - `"Regular Season"` (default)
  - `"Playoffs"`
  - `"Pre Season"`
- **Auto-detection**: Derived from `gamedate` if not provided
- **Scrapers**:
  - `GetNbaComPlayerBoxscore`

#### **`market_type` (Betting Market)**
- **Format**: Lowercase market name
- **Values**:
  - `"points"` (default/primary)
  - `"rebounds"` (optional)
  - `"assists"` (optional)
- **Scrapers**:
  - `BettingProsPlayerProps`

---

## Code-Verified Scraper Parameters

This section contains exact parameter details verified from source code.

### **NBA.com Scrapers**

#### **GetNbaComScheduleApi**
**Source:** `scrapers/nbacom/nbac_schedule_api.py`
- **Required**: `season`
- **Optional**: `api_key` (default: `None`)
- **Format**: 4-digit year string (e.g., `"2025"`)
- **Validation**: Auto-converts to NBA format `YYYY-YY` (e.g., `"2025-26"`)
- **Default Behavior**: **No default** - season is required

#### **GetNbaComScoreboardV2**
**Source:** `scrapers/nbacom/nbac_scoreboard_v2.py`
- **Required**: `gamedate`
- **Optional**: `api_key` (default: `None`)
- **Format**: `YYYYMMDD` or `YYYY-MM-DD` (both accepted)
- **Validation**: Normalizes to `YYYY-MM-DD`, validates 8-digit format
- **Default Behavior**: **No default** - gamedate is required

#### **GetNbaComPlayByPlay**
**Source:** `scrapers/nbacom/nbac_play_by_play.py`
- **Required**: `game_id`, `gamedate`
- **Optional**: `api_key` (default: `None`)
- **Format**:
  - `game_id`: 10-character NBA game ID (e.g., `"0022400561"`)
  - `gamedate`: `YYYYMMDD` format
- **Validation**: Derives season from first 5 chars of game_id
- **Default Behavior**: **No defaults** - both required

#### **GetNbaComPlayerBoxscore**
**Source:** `scrapers/nbacom/nbac_player_boxscore.py`
- **Required**: `gamedate`
- **Optional**:
  - `season`: Auto-detected from gamedate if not provided
  - `season_type`: Defaults to `"Regular Season"`
- **Format**: `YYYYMMDD` or `YYYY-MM-DD`
- **Validation**:
  - Normalizes gamedate to `YYYYMMDD`
  - Auto-calculates season from gamedate (Oct-Dec → current year, Jan-Sep → previous year)
  - Season type defaults to `"Regular Season"` if not provided
- **Default Behavior**:
  - ✅ **Season auto-detected** from gamedate
  - ✅ **Season type defaults** to `"Regular Season"`

#### **GetNbaComInjuryReport**
**Source:** `scrapers/nbacom/nbac_injury_report.py`
- **Required**: `gamedate`, `hour`, `period`
- **Optional**: None
- **Format**:
  - `gamedate`: `YYYYMMDD` or `YYYY-MM-DD`
  - `hour`: Integer 1-12
  - `period`: `"AM"` or `"PM"` (case insensitive)
- **Validation**:
  - Hour must be 1-12 (raises error otherwise)
  - Period must be "AM" or "PM"
  - Auto-calculates `hour24` for internal use
- **Default Behavior**: **No defaults** - all three parameters required

#### **GetNbaComPlayerList**
**Source:** `scrapers/nbacom/nbac_player_list.py`
- **Required**: None
- **Optional**: None
- **Format**: N/A
- **Validation**: None - fetches current season players
- **Default Behavior**: ✅ **Auto-fetches current season** active players

#### **GetNbaComPlayerMovement**
**Source:** `scrapers/nbacom/nbac_player_movement.py`
- **Required**: `year`
- **Optional**: None
- **Format**: 4-digit calendar year (e.g., `"2024"`)
- **Default Behavior**: **No default** - year is required

#### **GetNbaComTeamBoxscore**
**Source:** `scrapers/nbacom/nbac_team_boxscore.py`
- **Required**: `game_id`, `game_date`
- **Optional**: `api_key` (default: `None`)
- **Format**:
  - `game_id`: 10-character NBA game ID (e.g., `"0022400561"`)
  - `game_date`: `YYYY-MM-DD`
- **Validation**: Game ID must be exactly 10 digits
- **Default Behavior**: **No defaults** - both required

#### **GetNbaComRefereeAssignments**
**Source:** `scrapers/nbacom/nbac_referee_assignments.py`
- **Required**: `date`
- **Optional**: `api_key` (default: `None`)
- **Format**: `YYYY-MM-DD`
- **Validation**: Auto-derives season from date
- **Default Behavior**: **No default** - date is required
- **Special**: Daily scheduled scraper (9:15 AM ET)

#### **GetNbaComScheduleCdn**
**Source:** `scrapers/nbacom/nbac_schedule_cdn.py`
- **Required**: **None**
- **Optional**: `api_key` (default: `None`)
- **Format**: N/A
- **Validation**: None - fetches current season from CDN
- **Default Behavior**: ✅ **Auto-fetches current season** from static CDN files
- **Special**: Backup scraper for Schedule API

#### **GetNbaComGamebookPdf**
**Source:** `scrapers/nbacom/nbac_gamebook_pdf.py`
- **Required**: `game_code`
- **Optional**:
  - `version`: `"short"` (default)
  - `pdf_source`: `"download"` or `"gcs"` (default: `"download"`)
  - `bucket_name`: `"nba-scraped-data"` (default)
  - `date`, `away_team`, `home_team`: Auto-derived from game_code
- **Format**: `game_code` = `"YYYYMMDD/AWYHOM"` (e.g., `"20240410/MEMCLE"`)
- **Validation**: Auto-derives date and teams from game_code
- **Default Behavior**:
  - ✅ **Auto-derives** date, away_team, home_team from game_code
  - ✅ **Version defaults** to "short"
  - ✅ **PDF source defaults** to "download" (can read from GCS for re-parsing)
- **Special**: Extracts DNP reasons (critical for prop betting)

#### **GetNbaComTeamRoster**
**Source:** `scrapers/nbacom/nbac_roster.py`
- **Required**: `team_abbr`
- **Optional**: None
- **Format**: 3-letter uppercase team code (e.g., `"GSW"`)
- **Validation**: Validates against NBA_TEAMS config
- **Default Behavior**: **No default** - team_abbr required

---

### **Odds API Scrapers**

#### **GetOddsApiEvents**
**Source:** `scrapers/oddsapi/oddsa_events.py`
- **Required**: `sport`, `game_date`
- **Optional**:
  - `api_key`: `None`
  - `commenceTimeFrom`: Auto-calculated from game_date
  - `commenceTimeTo`: Auto-calculated from game_date
  - `dateFormat`: `None`
- **Format**:
  - `sport`: `"basketball_nba"`
  - `game_date`: `YYYY-MM-DD`
- **Validation**: Auto-calculates ET timezone day boundaries → UTC
- **Default Behavior**:
  - ✅ **Commence times auto-calculated** from game_date (midnight to midnight ET)

#### **GetOddsApiCurrentEventOdds**
**Source:** `scrapers/oddsapi/oddsa_player_props.py`
- **Required**: `event_id`
- **Optional**: `api_key` (default: `None`)
- **Format**: Event ID string from `GetOddsApiEvents` response
- **Validation**: None - passes through event ID
- **Default Behavior**: **No default** - event_id required
- **Critical Dependency**: ⚠️ **MUST** run `GetOddsApiEvents` first to obtain event IDs

#### **GetOddsApiCurrentGameLines**
**Source:** `scrapers/oddsapi/oddsa_game_lines.py`
- **Required**: `event_id`, `game_date`
- **Optional**:
  - `api_key`: `None`
  - `sport`: `"basketball_nba"` (default)
  - `markets`: `"spreads,totals"` (default)
  - `regions`: `"us"` (default)
  - `bookmakers`: `"draftkings,fanduel"` (default)
  - `oddsFormat`, `dateFormat`, `teams`: Optional
- **Format**:
  - `event_id`: String from Events API
  - `game_date`: `YYYY-MM-DD`
- **Default Behavior**:
  - ✅ **Markets default** to spreads,totals
  - ✅ **Regions default** to us
  - ✅ **Bookmakers default** to draftkings,fanduel

#### **GetOddsApiHistoricalEvents** ⚠️ **TIMING CRITICAL**
**Source:** `scrapers/oddsapi/oddsa_events_his.py`
- **Required**: `game_date`, `snapshot_timestamp`
- **Optional**:
  - `sport`: `"basketball_nba"` (default)
  - `api_key`: `None`
  - `commenceTimeFrom`, `commenceTimeTo`: Auto-calculated
  - `event_ids`, `dateFormat`: Optional
- **Format**:
  - `game_date`: `YYYY-MM-DD` (Eastern timezone date for GCS directory)
  - `snapshot_timestamp`: `YYYY-MM-DDTHH:MM:SSZ` (ISO 8601 UTC)
- **Validation**: Snaps timestamp to 5-minute boundary
- **Default Behavior**:
  - ✅ **Sport defaults** to "basketball_nba"
  - ✅ **Timestamp snapped** to nearest 5-minute mark
- **⚠️ CRITICAL TIMING CONSTRAINT**:
  - Events disappear from API when games start
  - Use `00:00:00Z` (midnight UTC) to get full day's event lineup
  - API returns closest snapshot <= your timestamp
  - Events typically available until game commence time

#### **GetOddsApiHistoricalEventOdds** ⚠️ **TIMING CRITICAL**
**Source:** `scrapers/oddsapi/oddsa_player_props_his.py`
- **Required**: `event_id`, `game_date`, `snapshot_timestamp`
- **Optional**:
  - `sport`: `"basketball_nba"` (default)
  - `regions`: `"us"` (default)
  - `markets`: `"player_points"` (default)
  - `bookmakers`: `"draftkings,fanduel"` (default)
  - `oddsFormat`, `dateFormat`, `teams`: Optional
- **Format**:
  - `event_id`: String from Historical Events API
  - `game_date`: `YYYY-MM-DD`
  - `snapshot_timestamp`: `YYYY-MM-DDTHH:MM:SSZ` (ISO 8601 UTC)
- **Validation**: Snaps timestamp to 5-minute boundary
- **Default Behavior**:
  - ✅ **Markets default** to player_points
  - ✅ **Timestamp snapped** to nearest 5-minute mark
- **⚠️ CRITICAL TIMING CONSTRAINT**:
  - **MUST** use same or slightly later timestamp than Events scraper
  - Events disappear from API when games start
  - ✗ Events at 03:55 AM, odds at 2:00 PM = 404 ERROR
  - ✓ Events at 03:55 AM, odds at 4:00 AM = SUCCESS
  - Safe windows: Early morning (04:00-10:00 UTC) for opening lines

#### **GetOddsApiHistoricalGameLines** ⚠️ **TIMING CRITICAL**
**Source:** `scrapers/oddsapi/oddsa_game_lines_his.py`
- **Required**: `event_id`, `game_date`, `snapshot_timestamp`
- **Optional**:
  - `sport`: `"basketball_nba"` (default)
  - `regions`: `"us"` (default)
  - `markets`: `"spreads,totals"` (default)
  - `bookmakers`: `"draftkings,fanduel"` (default)
  - `oddsFormat`, `dateFormat`, `teams`: Optional
- **Format**: Same as GetOddsApiHistoricalEventOdds
- **Validation**: Snaps timestamp to 5-minute boundary
- **Default Behavior**:
  - ✅ **Markets default** to spreads,totals (game lines, not props)
  - ✅ **Timestamp snapped** to nearest 5-minute mark
- **⚠️ CRITICAL TIMING CONSTRAINT**: Same as Historical Event Odds

---

### **BettingPros Scrapers**

#### **BettingProsEvents**
**Source:** `scrapers/bettingpros/bp_events.py`
- **Required**: `date`
- **Optional**: `sport` (default: `"NBA"`)
- **Format**: `YYYY-MM-DD`
- **Validation**: Validates datetime parsing with strptime
- **Default Behavior**: ✅ **Sport defaults to "NBA"**

#### **BettingProsPlayerProps**
**Source:** `scrapers/bettingpros/bp_player_props.py`
- **Required**: **Either** `event_ids` **OR** `date`
- **Optional**:
  - `event_ids`: `None` (comma-separated list)
  - `date`: `None` (YYYY-MM-DD format)
  - `sport`: `"NBA"`
  - `market_type`: `"points"` (can be: points, rebounds, assists, threes, steals, blocks)
  - `page_limit`: `10` (API maximum)
- **Format**:
  - `event_ids`: Comma-separated string (e.g., `"20879,20880,20881"`)
  - `date`: `YYYY-MM-DD`
- **Validation**: Custom - requires one of event_ids or date
- **Default Behavior**:
  - ✅ **Market type defaults to "points"**
  - ✅ **Auto-fetches events** if date provided
  - ✅ **Page limit defaults to 10** (API max)

---

### **Ball Don't Lie Scrapers**

#### **BdlGamesScraper**
**Source:** `scrapers/balldontlie/bdl_games.py`
- **Required**: **None**
- **Optional**:
  - `startDate`: Auto-calculated to yesterday if not provided
  - `endDate`: Auto-calculated to tomorrow if not provided
  - `api_key`: `None`
- **Format**: `YYYY-MM-DD`
- **Validation**: Defaults to yesterday → tomorrow window
- **Default Behavior**: ✅ **Auto-calculates date range** (yesterday to tomorrow)

#### **BdlBoxScoresScraper**
**Source:** `scrapers/balldontlie/bdl_box_scores.py`
- **Required**: `date`
- **Optional**: `api_key` (default: `None`)
- **Format**: `YYYY-MM-DD`
- **Default Behavior**: **No default** - date is required

#### **BdlActivePlayersScraper**
**Source:** `scrapers/balldontlie/bdl_active_players.py`
- **Required**: None
- **Optional**: None
- **Format**: N/A
- **Validation**: None
- **Default Behavior**: ✅ **Auto-fetches current active players** with pagination (5-6 requests)

#### **BdlStandingsScraper**
**Source:** `scrapers/balldontlie/bdl_standings.py`
- **Required**: None
- **Optional**: None
- **Format**: N/A
- **Default Behavior**: ✅ **Auto-fetches current season standings**

#### **BdlInjuriesScraper**
**Source:** `scrapers/balldontlie/bdl_injuries.py`
- **Required**: None
- **Optional**: None
- **Format**: N/A
- **Default Behavior**: ✅ **Auto-fetches current injuries**

---

### **ESPN Scrapers**

#### **GetEspnScoreboard**
**Source:** `scrapers/espn/espn_scoreboard_api.py`
- **Required**: `gamedate`
- **Optional**: None
- **Format**: `YYYYMMDD` (strict - no dashes)
- **Validation**: Constructs URL with `?dates=YYYYMMDD`
- **Default Behavior**: **No default** - gamedate is required

#### **GetEspnBoxscore**
**Source:** `scrapers/espn/espn_game_boxscore.py`
- **Required**: `game_id`
- **Optional**: None
- **Format**: ESPN game ID (from scoreboard response)
- **Default Behavior**: **No default** - game_id is required

#### **GetEspnTeamRoster**
**Source:** `scrapers/espn/espn_roster.py`
- **Required**: `teamSlug`, `teamAbbr`
- **Optional**: None
- **Format**:
  - `teamSlug`: Lowercase team name with hyphens (e.g., `"boston-celtics"`)
  - `teamAbbr`: 3-letter uppercase team code (e.g., `"BOS"`)
- **Validation**: Parses HTML roster page
- **Default Behavior**: **No defaults** - both required
- **Special**: Backup roster source (HTML scraping)

---

### **BigDataBall Scrapers**

#### **BigDataBallPbpScraper**
**Source:** `scrapers/bigdataball/bigdataball_pbp.py`
- **Required**: `game_id`
- **Optional**: None
- **Format**: NBA.com 10-character game ID (e.g., `"0022400561"`)
- **Default Behavior**: **No default** - game_id is required

---

### **Basketball Reference Scrapers**

#### **BasketballRefSeasonRoster**
**Source:** `scrapers/basketball_ref/br_season_roster.py`
- **Required**: `teamAbbr`, `year`
- **Optional**: None
- **Format**:
  - `teamAbbr`: 3-letter uppercase team code (e.g., `"LAL"`, `"BOS"`)
  - `year`: 4-digit ending year (e.g., `"2024"` for 2023-24 season)
- **Validation**: Validates against shared team config
- **Default Behavior**: **No defaults** - both required

---

## Scraper-Specific Parameter Quick Reference

**Legend:**
- ✅ = Has useful defaults / Auto-calculated
- ⚠️ = Required, no defaults
- 🔗 = Requires another scraper to run first

| Scraper | Required Parameters | Optional Parameters | Format Examples | Key Notes |
|---------|-------------------|---------------------|-----------------|-----------|
| **NBA.com Scrapers** | | | | |
| `GetNbaComScheduleApi` | `season` ⚠️ | - | `"2025"` | Auto-converts to `2025-26` |
| `GetNbaComScoreboardV2` | `gamedate` ⚠️ | - | `"20250115"` or `"2025-01-15"` | Both formats accepted |
| `GetNbaComPlayByPlay` | `game_id` ⚠️, `gamedate` ⚠️ | - | `"0022400561"`, `"20250115"` | Game ID determines season |
| `GetNbaComPlayerBoxscore` | `gamedate` ⚠️ | `season` ✅, `season_type` ✅ | `"20250115"` | Season auto-detected; type defaults to "Regular Season" |
| `GetNbaComInjuryReport` | `gamedate` ⚠️, `hour` ⚠️, `period` ⚠️ | - | `"2025-01-15"`, `hour=8, period="AM"` | All three required; auto-calculates hour24 |
| `GetNbaComPlayerList` | None | - | - | ✅ Current season auto-fetched |
| `GetNbaComPlayerMovement` | `year` ⚠️ | - | `"2024"` | Calendar year for transactions |
| `GetNbaComTeamBoxscore` | `game_id` ⚠️, `game_date` ⚠️ | - | `"0022400561"`, `"2025-01-15"` | Team-level stats per game |
| `GetNbaComRefereeAssignments` | `date` ⚠️ | - | `"2025-01-15"` | Daily 9:15 AM ET schedule |
| `GetNbaComScheduleCdn` | None | - | - | ✅ Auto-fetches current season from CDN (backup) |
| `GetNbaComGamebookPdf` | `game_code` ⚠️ | `version` ✅, `pdf_source` ✅ | `"20240410/MEMCLE"` | ✅ Auto-derives date/teams; extracts DNP reasons |
| `GetNbaComTeamRoster` | `team_abbr` ⚠️ | - | `"GSW"` | Current roster for team |
| **Odds API Scrapers** | | | | |
| `GetOddsApiEvents` | `sport` ⚠️, `game_date` ⚠️ | `commenceTimeFrom` ✅, `commenceTimeTo` ✅ | `"basketball_nba"`, `"2025-01-15"` | ✅ Commence times auto-calculated from game_date |
| `GetOddsApiCurrentEventOdds` | `event_id` ⚠️ | - | From Events API | 🔗 **MUST run GetOddsApiEvents first** |
| `GetOddsApiCurrentGameLines` | `event_id` ⚠️, `game_date` ⚠️ | `markets` ✅, `regions` ✅, `bookmakers` ✅ | `"abc123"`, `"2025-01-15"` | ✅ Markets default to spreads,totals |
| `GetOddsApiHistoricalEvents` | `game_date` ⚠️, `snapshot_timestamp` ⚠️ | `sport` ✅ | `"2025-01-15"`, `"2025-01-15T04:00:00Z"` | ⚠️ **TIMING CRITICAL** - events disappear at game time |
| `GetOddsApiHistoricalEventOdds` | `event_id` ⚠️, `game_date` ⚠️, `snapshot_timestamp` ⚠️ | `markets` ✅ | From Events API, `"2025-01-15"`, `"2025-01-15T04:00:00Z"` | ⚠️ **TIMING CRITICAL** - use same timestamp as Events |
| `GetOddsApiHistoricalGameLines` | `event_id` ⚠️, `game_date` ⚠️, `snapshot_timestamp` ⚠️ | `markets` ✅ | From Events API, `"2025-01-15"`, `"2025-01-15T04:00:00Z"` | ⚠️ **TIMING CRITICAL** - use same timestamp as Events |
| **BettingPros Scrapers** | | | | |
| `BettingProsEvents` | `date` ⚠️ | `sport` ✅ | `"2025-01-15"` | ✅ Sport defaults to "NBA" |
| `BettingProsPlayerProps` | `date` OR `event_ids` ⚠️ | `market_type` ✅, `page_limit` ✅ | `"2025-01-15"` or `"20879,20880"` | ✅ Market defaults to "points"; auto-fetches events if date given |
| **Ball Don't Lie Scrapers** | | | | |
| `BdlGamesScraper` | None | `startDate` ✅, `endDate` ✅ | `"2025-01-15"`, `"2025-01-16"` | ✅ Defaults to yesterday → tomorrow |
| `BdlBoxScoresScraper` | `date` ⚠️ | - | `"2025-01-15"` | Single date |
| `BdlActivePlayersScraper` | None | - | - | ✅ Current players; paginated (5-6 requests) |
| `BdlStandingsScraper` | None | - | - | ✅ Current season standings |
| `BdlInjuriesScraper` | None | - | - | ✅ Current injuries |
| **ESPN Scrapers** | | | | |
| `GetEspnScoreboard` | `gamedate` ⚠️ | - | `"20250115"` | YYYYMMDD format only (no dashes) |
| `GetEspnBoxscore` | `game_id` ⚠️ | - | ESPN game ID | From scoreboard response |
| `GetEspnTeamRoster` | `teamSlug` ⚠️, `teamAbbr` ⚠️ | - | `"boston-celtics"`, `"BOS"` | Backup roster source (HTML scraping) |
| **BigDataBall Scrapers** | | | | |
| `BigDataBallPbpScraper` | `game_id` ⚠️ | - | `"0022400561"` | NBA.com game ID |
| **Basketball Reference** | | | | |
| `BasketballRefSeasonRoster` | `teamAbbr` ⚠️, `year` ⚠️ | - | `"LAL"`, `"2024"` | Year is **ending** year (2024 = 2023-24) |

---

## Critical: Historical Odds API Timing Constraints ⚠️

### **The Problem: Events Disappear at Game Time**

Historical Odds API scrapers have a **critical timing constraint** that can cause 404 errors if not understood:

**Events disappear from the API when games start (or shortly before).**

If your `snapshot_timestamp` is too far after the event was available, the API returns 404.

### **How It Works**

1. **The API stores snapshots** at 5-minute intervals
2. **When you request** a snapshot timestamp, the API returns the **closest available snapshot ≤ your timestamp**
3. **Events are available** from early morning until they start/commence
4. **Events disappear** when games start (typically 23:00-02:00 UTC for NBA)

### **What Causes 404 Errors**

```python
# ✗ WRONG - Will cause 404 errors
events = get_events(game_date="2024-01-25", snapshot_timestamp="2024-01-25T03:55:40Z")  # Morning
odds = get_odds(event_id="abc123", snapshot_timestamp="2024-01-25T14:00:00Z")  # Afternoon - FAILS!
# ERROR: Events already started, no longer available at 2 PM
```

```python
# ✓ CORRECT - Use consistent timestamps
events = get_events(game_date="2024-01-25", snapshot_timestamp="2024-01-25T04:00:00Z")  # 4 AM UTC
odds = get_odds(event_id="abc123", snapshot_timestamp="2024-01-25T04:00:00Z")  # Same time - SUCCESS!
```

### **Safe Timing Windows**

| Time Window (UTC) | Description | Recommended For | Risk Level |
|-------------------|-------------|-----------------|------------|
| **00:00 - 10:00** | Early morning | Opening lines discovery | ✅ Low |
| **04:00 - 10:00** | Morning | Opening lines collection | ✅ Low |
| **14:00 - 18:00** | Afternoon | Updated lines | ⚠️ Medium (some events may have started) |
| **20:00+** | Evening | Final lines | 🔴 High (games starting) |

### **Recommended Workflow**

```python
# Step 1: Get events early in the day
events = GetOddsApiHistoricalEvents()
events.run(opts={
    "game_date": "2024-01-25",
    "snapshot_timestamp": "2024-01-25T04:00:00Z"  # 4 AM UTC = morning
})

# Step 2: Extract event IDs from response
event_id = events_data[0]['id']

# Step 3: Get odds using SAME or slightly LATER timestamp
props = GetOddsApiHistoricalEventOdds()
props.run(opts={
    "event_id": event_id,
    "game_date": "2024-01-25",
    "snapshot_timestamp": "2024-01-25T04:00:00Z"  # SAME timestamp as events
})
```

### **Best Practices**

1. ✅ **Use `00:00:00Z` for events discovery** - Gets full day's lineup
2. ✅ **Use same timestamp for odds** - Ensures consistency
3. ✅ **Prefer early morning timestamps** (04:00-10:00 UTC) - Most reliable
4. ✅ **Always run Events scraper first** - Verify events exist before requesting odds
5. ⚠️ **Avoid late afternoon/evening** - Games may have already started

### **Timestamp Auto-Snapping**

All historical scrapers automatically snap timestamps to 5-minute boundaries:

```python
# Input: "2024-01-25T04:03:17Z"
# Auto-snapped to: "2024-01-25T04:00:00Z"
```

This is done automatically - you don't need to manually round timestamps.

---

## Parameter Validation Rules

### **Date Validation**
- **YYYYMMDD format**: 8 characters, all digits
- **YYYY-MM-DD format**: 10 characters with dashes in positions 4 and 7
- **Internal normalization**: Most scrapers accept both formats, normalize to required format
- **Timezone handling**: Odds API converts Eastern timezone dates to UTC for API calls

### **Season Validation**
- **4-digit year**: Must be >= 2000 (modern NBA era)
- **NBA format conversion**: Automatic `YYYY` → `YYYY-YY` conversion in most scrapers
- **Season logic**:
  - October-December dates → current year is season start year
  - January-September dates → previous year is season start year
  - Example: `2025-01-15` → `2024-25` season

### **Game ID Validation**
- **Length**: Exactly 10 characters
- **Format**: `00XXYYYYYY` pattern
- **Season extraction**: Characters 3-5 represent season year (e.g., `224` = 2024-25)
- **Season type**: Characters 2-3 indicate game type (`22` = regular, `41` = playoffs)

### **Team Abbreviation Validation**
- **Length**: Exactly 3 characters
- **Case**: Uppercase (e.g., `LAL`, not `lal`)
- **Validity**: Must match active NBA team codes

---

## Common Parameter Errors and Solutions

### **Error: "Missing required option [season]"**
- **Cause**: Season parameter not provided when required
- **Solution**: Add `season="2025"` (4-digit year) to opts
- **Example**:
  ```python
  # ❌ Wrong
  scraper.run(opts={})

  # ✅ Correct
  scraper.run(opts={"season": "2025"})
  ```

### **Error: "gamedate must be YYYYMMDD or YYYY-MM-DD"**
- **Cause**: Invalid date format
- **Solution**: Use either `20250115` or `2025-01-15`
- **Example**:
  ```python
  # ❌ Wrong
  opts = {"gamedate": "2025/01/15"}

  # ✅ Correct
  opts = {"gamedate": "20250115"}  # or "2025-01-15"
  ```

### **Error: "Invalid game_id format for season derivation"**
- **Cause**: Game ID is not 10 characters or doesn't match pattern
- **Solution**: Verify game ID from NBA.com or schedule data
- **Example**:
  ```python
  # ❌ Wrong
  opts = {"game_id": "224561"}  # Too short

  # ✅ Correct
  opts = {"game_id": "0022400561"}  # Full 10-character ID
  ```

### **Error: API returns no data (Events before Props)**
- **Cause**: Props scraper run before Events scraper
- **Solution**: **Always** run Events scraper first to populate event IDs
- **Example**:
  ```python
  # ✅ Correct order
  events_scraper.run(opts={"sport": "basketball_nba", "game_date": "2025-01-15"})
  # Wait for completion, extract event IDs from response
  props_scraper.run(opts={"event_id": "abc123..."})
  ```

---

## Testing Parameter Formats

Use the capture tool to test parameter formats without affecting production:

```bash
# Test date format variations
python tools/fixtures/capture.py nbac_scoreboard_v2 --gamedate 20250115 --debug
python tools/fixtures/capture.py nbac_scoreboard_v2 --gamedate 2025-01-15 --debug

# Test season format
python tools/fixtures/capture.py nbac_schedule_api --season 2025 --debug

# Test game ID
python tools/fixtures/capture.py nbac_play_by_play --game_id 0022400561 --gamedate 20250115 --debug

# Test date ranges
python tools/fixtures/capture.py bdl_games --startDate 2025-01-15 --endDate 2025-01-16 --debug
```

---

## Related Documentation

- **Operational Reference**: `2025-08-12-op-ref__.md` - Complete scraper inventory and workflows
- **Scraper Base Class**: `scrapers/scraper_base.py` - Base implementation with validation logic
- **Capture Tool Guide**: `docs/development/fixture-capture.md` - Testing scrapers with capture tool

---

## Key Findings from Code Verification

### **Important Discoveries**

1. **GetNbaComPlayerBoxscore has Auto-Detection** ✅
   - **Season** is auto-detected from gamedate (Oct-Dec → current year, Jan-Sep → previous year)
   - **Season type** defaults to `"Regular Season"` if omitted
   - **Source:** `scrapers/nbacom/nbac_player_boxscore.py`

2. **GetNbaComGamebookPdf Auto-Derives Everything from game_code** ✅
   - Single parameter `game_code` (e.g., `"20240410/MEMCLE"`) → auto-derives date, away_team, home_team
   - Can read from GCS or download from NBA.com (`pdf_source` parameter)
   - **Critical for prop betting** - extracts DNP reasons
   - **Source:** `scrapers/nbacom/nbac_gamebook_pdf.py`

3. **BdlGamesScraper and GetNbaComScheduleCdn Require NO Parameters** ✅
   - BdlGames defaults to yesterday → tomorrow date range
   - ScheduleCdn fetches current season from static CDN
   - Fully autonomous for current games/schedule
   - **Source:** `scrapers/balldontlie/bdl_games.py`, `scrapers/nbacom/nbac_schedule_cdn.py`

4. **GetNbaComInjuryReport Calculates hour24 Automatically**
   - You provide `hour` (1-12) and `period` ("AM"/"PM")
   - Scraper auto-calculates `hour24` (0-23) for internal use
   - **Source:** `scrapers/nbacom/nbac_injury_report.py`

5. **Historical Odds API Scrapers Have CRITICAL Timing Constraints** ⚠️
   - Events disappear from API when games start
   - `snapshot_timestamp` must be close to when events were available
   - ✗ Events at 3:55 AM, odds at 2:00 PM = 404 ERROR
   - ✓ Events at 4:00 AM, odds at 4:00 AM = SUCCESS
   - Auto-snaps timestamps to 5-minute boundaries
   - **Source:** `scrapers/oddsapi/oddsa_events_his.py`, `oddsa_player_props_his.py`

6. **GetOddsApiEvents Auto-Calculates Time Windows**
   - You provide `game_date` (YYYY-MM-DD)
   - Scraper auto-calculates `commenceTimeFrom` and `commenceTimeTo` (ET midnight to midnight → UTC)
   - **Source:** `scrapers/oddsapi/oddsa_events.py`

7. **BettingProsPlayerProps Has Dual-Mode Operation**
   - **Mode 1**: Provide `date` → scraper fetches events automatically
   - **Mode 2**: Provide `event_ids` → skips event fetch
   - Defaults: `market_type="points"`, `page_limit=10`
   - **Source:** `scrapers/bettingpros/bp_player_props.py`

8. **ESPN Scoreboard Requires Strict Format**
   - Must use `YYYYMMDD` (no dashes) - stricter than NBA.com scrapers
   - **Source:** `scrapers/espn/espn_scoreboard_api.py`

### **Parameter Name Patterns**

**Verified from Source Code:**
- **Date parameters**: Mix of `gamedate`, `game_date`, and `date` (check scraper-specific section)
- **Team parameters**: Always `teamAbbr` (camelCase, not snake_case)
- **Season parameters**: Always `season` (not `season_year`)
- **Time parameters**: `hour` + `period` (12-hour), NOT `hour24` (calculated internally)

### **Critical Dependencies** (Must Run in Order)

1. **GetOddsApiEvents → GetOddsApiCurrentEventOdds** ⚠️ REQUIRED
   - Props scraper cannot run without event IDs from Events scraper

2. **BettingProsEvents → BettingProsPlayerProps** (Optional)
   - Can skip if you provide `event_ids` directly
   - Auto-fetches events if you provide `date` instead

---

## Using This Reference

### **For Direct Scraper Calls**
```python
from scrapers.nbacom.nbac_player_boxscore import GetNbaComPlayerBoxscore

scraper = GetNbaComPlayerBoxscore()
# ✅ Minimal - season and season_type auto-detected
scraper.run(opts={"gamedate": "20250115"})

# ✅ Explicit - override defaults
scraper.run(opts={
    "gamedate": "20250115",
    "season": "2024",
    "season_type": "Playoffs"
})
```

### **For Backfill Scripts**
```python
# ✅ Verified format for Basketball Reference
from scrapers.basketball_ref.br_season_roster import BasketballRefSeasonRoster

for team in ["LAL", "BOS", "GSW"]:
    for year in [2022, 2023, 2024, 2025]:  # Ending years
        scraper = BasketballRefSeasonRoster()
        scraper.run(opts={"teamAbbr": team, "year": str(year)})
```

### **For Cloud Run Deployments**
```bash
# ✅ Verified parameters for Flask endpoints
curl -X POST "https://scraper-service.run.app/nbac_scoreboard_v2" \
  -H "Content-Type: application/json" \
  -d '{"gamedate": "20250115"}'  # Both YYYYMMDD and YYYY-MM-DD accepted

curl -X POST "https://scraper-service.run.app/nbac_injury_report" \
  -H "Content-Type: application/json" \
  -d '{"gamedate": "20250115", "hour": 8, "period": "AM"}'  # All three required
```

---

**Last Updated:** 2025-11-13
**Total Scrapers Documented:** 30+ (all active production scrapers)
**Verification:** Code-verified from scraper source files (November 2025)
**Confidence:** High - All parameters verified from actual `required_opts`, `optional_params`, and validation logic
**Coverage:** Complete - includes all NBA.com, Odds API (current + historical), BettingPros, Ball Don't Lie, ESPN, BigDataBall, and Basketball Reference scrapers
**Maintenance Note:** Line numbers omitted intentionally to prevent documentation drift as code evolves
