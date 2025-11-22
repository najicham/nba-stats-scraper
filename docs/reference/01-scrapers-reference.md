# NBA Scrapers Reference

**Created:** 2025-11-21 17:12:03 PST
**Last Updated:** 2025-11-21 17:12:03 PST

Quick reference for NBA data scrapers - deployment, debugging, and monitoring.

## GCS Storage

**Bucket:** `gs://nba-scraped-data/`

```
nba-scraped-data/
├── odds-api/              # Odds API (revenue critical)
├── nba-com/              # NBA.com official data
├── ball-dont-lie/        # Ball Don't Lie validation
├── big-data-ball/        # Enhanced analytics
├── espn/                 # ESPN backup
├── basketball-ref/       # Basketball Reference
└── bettingpros/          # BettingPros backup
```

## Scraper Categories

### Revenue Critical ⭐

**Timing:** Every 2 hours (8 AM - 8 PM PT)
**Purpose:** Live betting markets

- `GetOddsApiEvents` - Must run first (provides event IDs)
- `GetOddsApiCurrentEventOdds` - Player props
- `GetOddsApiCurrentGameLines` - Spreads/totals

**Dependencies:** Events → Props + Game Lines

### Player Intelligence

**Timing:** Daily + Real-Time
**Purpose:** Player → team lookup

- `GetNbaComPlayerList` - Primary source
- `BdlActivePlayersScraper` - Validation
- `GetNbaComPlayerMovement` - Transaction history

### Player Availability

**Timing:** Daily + Real-Time
**Purpose:** Injury status

- `GetNbaComInjuryReport` - Official status
- `BdlInjuriesScraper` - Backup

### Game Context

**Timing:** Daily 9:15 AM ET
**Purpose:** Referee assignments

- `GetNbaComRefereeAssignments` - Official assignments

### Game Scheduling

**Timing:** Daily
**Purpose:** Game timing

- `GetNbaComScheduleApi` - Primary + Backfill
- `GetNbaComScheduleCdn` - Backup/monitoring
- `BdlStandingsScraper` - Standings

### Game Results

**Timing:** Post-Game (8 PM & 11 PM PT)
**Purpose:** Performance data

- `GetNbaComTeamBoxscore` - Official team stats
- `BdlBoxScoresScraper` - Team + player stats

### Advanced Analytics

**Timing:** Recovery (2 AM & 5 AM PT)
**Purpose:** Detailed analysis

- `BigDataBallPbpScraper` - Enhanced play-by-play
- `GetNbaComPlayByPlay` - Official backup
- `GetEspnScoreboard` - Final check
- `GetEspnBoxscore` - Final check

### Backfill

**Timing:** On-demand
**Purpose:** Historical data

- `GetOddsApiHistoricalEvents` - Game discovery
- `GetOddsApiHistoricalEventOdds` - Historical props
- `GetOddsApiHistoricalGameLines` - Historical spreads/totals
- `GetNbaComScheduleApi` - Historical schedules
- `GetNbaComGamebooks` - Game books with DNP
- `BasketballRefSeasonRoster` - Name mapping

## Quick Reference

### Odds API (6 scrapers)

**Revenue Critical**

```python
# Current Events
GetOddsApiEvents()
# Output: /odds-api/events/{date}/{timestamp}.json

# Current Props
GetOddsApiCurrentEventOdds(event_id)
# Output: /odds-api/player-props/{date}/{event_id}-{teams}/{timestamp}-snap-{snap}.json

# Current Game Lines
GetOddsApiCurrentGameLines(event_id, game_date)
# Output: /odds-api/game-lines/{date}/{event_id}-{teams}/{timestamp}-snap-{snap}.json
```

**Historical**

```python
# Historical Events
GetOddsApiHistoricalEvents(game_date, snapshot_timestamp)

# Historical Props
GetOddsApiHistoricalEventOdds(event_id, game_date, snapshot_timestamp)

# Historical Game Lines
GetOddsApiHistoricalGameLines(event_id, game_date, snapshot_timestamp)
```

**Rate Limit:** 500 requests/month

### NBA.com (9 scrapers)

```python
# Player Data
GetNbaComPlayerList()  # Master player database
GetNbaComPlayerMovement(year)  # Transaction history

# Referee Data
GetNbaComRefereeAssignments(date)  # Daily assignments at 9:15 AM ET

# Schedule
GetNbaComScheduleApi(season=None)  # Current + backfill
GetNbaComScheduleCdn()  # Backup/monitoring

# Availability
GetNbaComInjuryReport(date, hour24)  # Official injury reports

# Game Results
GetNbaComTeamBoxscore(game_id, game_date)  # Team stats
GetNbaComPlayerBoxscore(date)  # Player stats
GetNbaComPlayByPlay(game_id, gamedate)  # Play-by-play

# Backfill
GetNbaComGamebooks(date)  # PDFs with DNP reasons
```

**Rate Limit:** None (be respectful)

### Ball Don't Lie (4 scrapers)

```python
# Validation
BdlActivePlayersScraper()  # 5-6 paginated requests
BdlInjuriesScraper()

# Game Data
BdlBoxScoresScraper(date)
BdlStandingsScraper(season)
```

**Rate Limit:** 600 requests/minute
**Auth:** `BDL_API_KEY`

### BigDataBall (1 scraper)

```python
BigDataBallPbpScraper(game_id)
# Output: /big-data-ball/{nba_season}/{date}/game_{game_id}/{filename}.csv
```

**Auth:** Google Drive service account

### ESPN (3 scrapers - backup only)

```python
GetEspnScoreboard(gamedate)
GetEspnBoxscore(game_id, gamedate)
GetEspnTeamRoster(team_abbr, date)
```

**Schedule:** 5 AM PT final check only

### Basketball Reference (1 scraper)

```python
BasketballRefSeasonRoster(teamAbbr, year)
# Output: /basketball-ref/season-rosters/{season}/{teamAbbr}.json
```

**Rate Limit:** 20 requests/minute (3.5s delay)
**Purpose:** Name mapping for gamebook PDFs

### BettingPros (2 scrapers - backup)

```python
GetBettingProEvents(date)
GetBettingProPlayerProps(market_type, date)
```

**Auth:** `BETTINGPROS_API_KEY`

## Daily Operations

**Morning Setup (8 AM PT)**
- 9 scrapers, ~13-14 requests
- Player data, schedules, injuries, standings

**Real-Time Business (Every 2 hours)**
- 8 scrapers × 7 cycles = ~84-91 requests
- Events → Props + Game Lines

**Post-Game (8 PM & 11 PM PT)**
- Team boxscores, results

**Recovery (2 AM & 5 AM PT)**
- Enhanced analytics, final checks

## Critical Dependencies

**Revenue Critical:**
- `GetOddsApiEvents` → `GetOddsApiCurrentEventOdds`
- `GetOddsApiEvents` → `GetOddsApiCurrentGameLines`

**Backfill:**
- `GetOddsApiEventsHistory` → `GetOddsApiHistoricalEventOdds`
- `GetOddsApiEventsHistory` → `GetOddsApiHistoricalGameLines`
- `BasketballRefSeasonRoster` → `GetNbaComGamebooks` (name mapping)

## Troubleshooting

### Historical Odds 404 Errors

Events disappear from API when games start. Solution:

```bash
# ✓ CORRECT: Use same timestamp as events scraper
Events at:  2024-01-25T03:55:40Z
Odds at:    2024-01-25T04:00:00Z  # Works

# ✗ WRONG: Hours later
Events at:  2024-01-25T03:55:40Z
Odds at:    2024-01-25T14:00:00Z  # 404 Error
```

### Authentication

- **Odds API:** `ODDS_API_KEY`
- **Ball Don't Lie:** `BDL_API_KEY`
- **BettingPros:** `BETTINGPROS_API_KEY`
- **BigDataBall:** Google Drive service account

### Rate Limits

- Odds API: 500/month (paid plan)
- Ball Don't Lie: 600/minute
- Basketball Reference: 20/minute (3.5s delay)
- NBA.com: No official limit

## Usage Examples

```bash
# Current game lines
python tools/fixtures/capture.py oddsa_game_lines \
  --event_id 6f0b6f8d8cc9c5bc6375cdee \
  --game_date 2025-11-04

# Historical game lines
python tools/fixtures/capture.py odds_api_historical_game_lines \
  --event_id cd0bc7d0c238f4446ce1c03d0cea7ec4 \
  --game_date 2024-01-25 \
  --snapshot_timestamp 2024-01-25T04:00:00Z

# Referee assignments
python tools/fixtures/capture.py nbac_referee_assignments \
  --date 2025-01-08

# Team boxscore
python tools/fixtures/capture.py nbac_team_boxscore \
  --game_id 0022400561 \
  --game_date 2025-01-15
```

## Files

**Repository:**
- Scrapers: `scrapers/{source}/{scraper_name}.py`
- Utilities: `scrapers/utils/gcs_path_builder.py`
- Scripts: `scripts/scrape_br_season_rosters.py`

**Cloud Run Service:**
- `nba-scrapers-756957797294.us-west2.run.app`

## See Also

- [Processor Reference](02-processors-reference.md)
- [Backfill Guides](../backfill/)
