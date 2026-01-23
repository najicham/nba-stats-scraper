# NBA Scrapers Reference

**Created:** 2025-11-21 17:12:03 PST
**Last Updated:** 2026-01-23

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

### Live Game Data ⭐ (NEW)

**Timing:** Every 3 min during games (7 PM - 2 AM ET)
**Purpose:** Real-time stats for challenge grading

- `BdlLiveBoxScoresScraper` - Live player stats during games

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

> ⚠️ **CRITICAL: Historical Betting Lines** - When predictions have placeholder lines (20.0),
> you MUST use the historical Odds API scrapers to backfill. The current/live scrapers
> only work for upcoming games. See [Historical Odds API Backfill](#historical-odds-api-backfill-workflow) below.

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

### Ball Don't Lie (5 scrapers)

```python
# Validation
BdlActivePlayersScraper()  # 5-6 paginated requests
BdlInjuriesScraper()

# Game Data
BdlBoxScoresScraper(date)
BdlStandingsScraper(season)

# Live Game Data (NEW - Session 174)
BdlLiveBoxScoresScraper()  # Every 3 min during games
# Output: /ball-dont-lie/live-boxscores/{date}/{poll_id}.json
# Schedule: bdl-live-boxscores-evening (7-11 PM ET)
#           bdl-live-boxscores-late (12-2 AM ET)
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

### News RSS Feeds (NEW - 2026-01-08)

**Timing:** On-demand (planned: every 15 minutes)
**Purpose:** Sports news, injury updates, trades, lineup changes
**Cost:** Free (RSS) + ~$0.54/month (AI summaries)

```python
from scrapers.news import RSSFetcher, NewsSummarizer, NewsPlayerLinksStorage

# Fetch news from RSS
fetcher = RSSFetcher()
articles = fetcher.fetch_all(sports=['nba', 'mlb'])

# Get news for a player (website API)
storage = NewsPlayerLinksStorage()
articles = storage.get_player_articles('lebronjames', sport='nba', limit=10)

# Generate AI summary
summarizer = NewsSummarizer()  # Requires ANTHROPIC_API_KEY
result = summarizer.summarize(article_id, title, content, sport='NBA')
```

**Sources:**
- ESPN NBA/MLB RSS (espn.com/espn/rss/nba/news)
- CBS Sports NBA/MLB RSS (cbssports.com/rss/headlines/nba/)

**BigQuery Tables:**
- `nba_raw.news_articles_raw` - Raw articles
- `nba_analytics.news_insights` - Categories + AI summaries
- `nba_analytics.news_player_links` - Player-article links

**Auth:** `ANTHROPIC_API_KEY` (for AI summaries only)

**CLI:**
```bash
python bin/scrapers/fetch_news.py --dry-run --sport nba
python bin/scrapers/fetch_news.py --save --dedupe
```

**See:** [News & AI Analysis Project](../08-projects/current/news-ai-analysis/README.md)

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

## Historical Odds API Backfill Workflow

> **CRITICAL**: This section explains how to backfill betting lines for past dates.
> The live Odds API scrapers (`oddsa_events`, `oddsa_player_props`, `oddsa_game_lines`)
> only work for upcoming/current games. For any historical date, you MUST use the
> historical scrapers.

### When to Use Historical Scrapers

Use historical Odds API scrapers when:
- Predictions show placeholder lines (current_points_line = 20.0)
- Odds API scraper failed on a past date
- Backfilling betting context for ML training data
- Re-running predictions for a past game date

### The Three Historical Scrapers

| Scraper | File | Purpose |
|---------|------|---------|
| `GetOddsApiHistoricalEvents` | `scrapers/oddsapi/oddsa_events_his.py` | Get event IDs for a past date |
| `GetOddsApiHistoricalEventOdds` | `scrapers/oddsapi/oddsa_player_props_his.py` | Get player prop odds (points, rebounds, assists) |
| `GetOddsApiHistoricalGameLines` | `scrapers/oddsapi/oddsa_game_lines_his.py` | Get spreads and totals |

### Step-by-Step Backfill Process

#### Step 1: Get Event IDs for the Date

```bash
# Get all NBA events for Jan 21, 2026
python -m scrapers.oddsapi.oddsa_events_his \
    --game_date 2026-01-21 \
    --snapshot_timestamp 2026-01-21T00:00:00Z \
    --debug

# Output includes event IDs like:
# "id": "a1b2c3d4e5f6g7h8i9j0..."
```

**Snapshot timestamp tips:**
- Use `00:00:00Z` to get the full day's schedule
- Events disappear from API when games start
- For most NBA games: safe window is 04:00-18:00 UTC

#### Step 2: Fetch Historical Player Props

```bash
# For each event_id from Step 1:
python -m scrapers.oddsapi.oddsa_player_props_his \
    --event_id <EVENT_ID> \
    --game_date 2026-01-21 \
    --snapshot_timestamp 2026-01-21T18:00:00Z \
    --markets player_points \
    --debug

# Can also fetch multiple markets:
# --markets player_points,player_rebounds,player_assists
```

#### Step 3: Fetch Historical Game Lines (Optional)

```bash
python -m scrapers.oddsapi.oddsa_game_lines_his \
    --event_id <EVENT_ID> \
    --game_date 2026-01-21 \
    --snapshot_timestamp 2026-01-21T18:00:00Z \
    --debug
```

### Timing Constraints

**Critical: Use snapshot_timestamp BEFORE game time**

| Game Time (Local) | Game Time (UTC) | Safe Snapshot Window |
|-------------------|-----------------|---------------------|
| 7:00 PM ET        | 00:00 UTC       | 00:00-23:00 UTC previous day |
| 7:30 PM ET        | 00:30 UTC       | 00:00-23:30 UTC previous day |
| 10:00 PM ET       | 03:00 UTC       | 00:00-02:00 UTC |
| 10:30 PM PT       | 06:30 UTC       | 00:00-05:30 UTC |

**Rule of thumb:** Use `18:00:00Z` (1 PM ET / 10 AM PT) for most backfills - this is before any NBA games start.

### Full Date Backfill Script Example

```bash
#!/bin/bash
# backfill_odds_for_date.sh

GAME_DATE=$1
SNAPSHOT="$GAME_DATE"T18:00:00Z

echo "=== Backfilling betting lines for $GAME_DATE ==="

# Step 1: Get events
python -m scrapers.oddsapi.oddsa_events_his \
    --game_date $GAME_DATE \
    --snapshot_timestamp $SNAPSHOT \
    --debug 2>&1 | tee /tmp/events_$GAME_DATE.log

# Extract event IDs (adjust jq path based on actual output)
EVENT_IDS=$(cat /tmp/oddsapi_hist_events_$GAME_DATE.json | jq -r '.events[].id')

# Step 2: Fetch props for each event
for event_id in $EVENT_IDS; do
    echo "Fetching props for event: $event_id"
    python -m scrapers.oddsapi.oddsa_player_props_his \
        --event_id $event_id \
        --game_date $GAME_DATE \
        --snapshot_timestamp $SNAPSHOT \
        --markets player_points \
        --debug
done

echo "=== Complete! ==="
```

### API Rate Limits

- Historical API requests count against the same 500/month limit
- Each event lookup costs 1 request
- Each props/lines lookup costs 1 request
- Typical date with 10 games = ~11 requests (1 events + 10 props)

### After Backfilling

After scraping historical data:

1. **Run processors** to load data into BigQuery:
   ```bash
   # Run the odds API processor for the date
   python -m data_processors.raw.odds_api_props_processor \
       --date 2026-01-21
   ```

2. **Re-run predictions** with the new betting context:
   ```bash
   COORD_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)
   curl -X POST "https://prediction-coordinator-756957797294.us-west2.run.app/start" \
       -H "Content-Type: application/json" \
       -H "X-API-Key: $COORD_KEY" \
       -d '{"game_date": "2026-01-21"}'
   ```

3. **Verify predictions** no longer have placeholders:
   ```sql
   SELECT game_date, COUNT(*) as total,
          COUNTIF(current_points_line = 20.0) as placeholders
   FROM `nba_predictions.player_prop_predictions`
   WHERE game_date = '2026-01-21'
   GROUP BY 1
   ```

---

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
