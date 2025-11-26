# System Architecture

Complete architecture overview of the NBA Props Platform.

## High-Level Architecture

```
┌─────────────────┐
│ Cloud Scheduler │  ← Triggers workflows on schedule
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Workflows     │  ← Orchestrates scraping & processing
└────────┬────────┘
         │
         ├──────────────────────┬──────────────────────┐
         ▼                      ▼                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐
│  nba-scrapers   │    │ nba-processors  │    │ nba-analytics-   │
│  (Cloud Run)    │    │  (Cloud Run)    │    │ processors       │
└────────┬────────┘    └────────┬────────┘    └────────┬─────────┘
         │                      │                       │
         ▼                      ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐
│   GCS Buckets   │───→│    BigQuery     │←───│   BigQuery       │
│   (Raw JSON)    │    │   (Processed)   │    │   (Analytics)    │
└─────────────────┘    └─────────────────┘    └──────────────────┘
```

## Data Flow

### 1. Scraping Phase
```
External API → nba-scrapers → GCS (raw JSON files)
```

**Sources:**
- Ball Don't Lie API (NBA stats)
- The Odds API (betting odds/props)
- ESPN.com (backup rosters/scores)
- NBA.com (official play-by-play, injury reports)
- Big Ball Data (enhanced play-by-play)

**Output:** JSON files in GCS buckets organized by:
- Source: `raw/bdl_box_scores/`, `raw/odds_props/`
- Date: `YYYY/MM/DD/`
- File: `data.json` or timestamped files

### 2. Processing Phase
```
GCS (raw) → nba-processors → BigQuery (structured tables)
```

**Processing:**
- Parse JSON
- Normalize data formats
- Resolve player names/IDs
- Deduplicate records
- Validate data quality

**Output:** BigQuery tables in `raw` dataset

### 3. Analytics Phase
```
BigQuery (raw) → nba-analytics-processors → BigQuery (analytics)
```

**Analytics:**
- Player game summaries
- Team offense/defense summaries
- Upcoming game context
- Historical trends

**Output:** BigQuery tables in `analytics` dataset

### 4. Report Generation Phase _(Future)_
```
BigQuery (analytics) → report-generator → BigQuery (reports)
```

**Reports:**
- Player prop predictions
- Value bets identification
- Performance forecasts

## Component Details

### Cloud Scheduler Jobs

| Job | Schedule | Workflow Triggered |
|-----|----------|-------------------|
| `real-time-business-trigger` | Every 2h (8am-8pm PT) | `real-time-business` |
| `morning-operations-trigger` | Daily 8am PT | `morning-operations` |
| `post-game-collection-trigger` | 8pm & 11pm PT | `post-game-collection` |
| `late-night-recovery-trigger` | 2am PT | `late-night-recovery` |
| `early-morning-final-check-trigger` | 6am PT | `early-morning-final-check` |

### Workflows

#### `real-time-business`
**Purpose:** Critical revenue chain - keep odds/props updated

**Steps:**
1. Scrape current events from Odds API
2. Scrape player props from Odds API
3. Process events into BigQuery
4. Process props into BigQuery
5. Update team rosters if changed

**Runs:** Every 2 hours during business hours (8am-8pm PT)

**Critical:** Yes - directly affects revenue

#### `morning-operations`
**Purpose:** Daily setup and recovery

**Steps:**
1. Scrape season schedule (weekly)
2. Scrape injury reports
3. Scrape player movement
4. Recover any missed data from previous day
5. Process enhanced play-by-play

**Runs:** Daily at 8am PT

**Critical:** Yes - sets up the day

#### `post-game-collection`
**Purpose:** Collect game data after games finish

**Steps:**
1. Scrape box scores (multiple sources)
2. Scrape play-by-play
3. Scrape scoreboard
4. Process all data into BigQuery

**Runs:** 8pm & 11pm PT (after early/late games)

**Critical:** High - main game data collection

#### `late-night-recovery` & `early-morning-final-check`
**Purpose:** Retry any failures, collect late data

**Steps:**
1. Check for missing data
2. Retry failed scrapers
3. Collect enhanced play-by-play (available 2h after game)
4. Final validation

**Runs:** 2am & 6am PT

**Critical:** Medium - recovery/backup

### Cloud Run Services

#### nba-scrapers
**Purpose:** Fetch data from external APIs

**Endpoints:**
- `/scrape/bdl-box-scores` - Ball Don't Lie box scores
- `/scrape/bdl-injuries` - Ball Don't Lie injuries
- `/scrape/odds-events` - Odds API events
- `/scrape/odds-props` - Odds API player props
- `/scrape/espn-scoreboard` - ESPN scoreboard
- `/scrape/nbacom-play-by-play` - NBA.com play-by-play
- ... (20+ scraper endpoints)

**Technology:** Python Flask app with scraper modules

**Authentication:** API keys stored in Secret Manager

**Scaling:** Auto-scale 0-10 instances

#### nba-processors
**Purpose:** Process raw data into structured BigQuery tables

**Endpoints:**
- `/process/bdl-box-scores` - Process box scores
- `/process/odds-props` - Process player props
- ... (20+ processor endpoints)

**Technology:** Python Flask app with processor modules

**Trigger:** Called by workflows or Pub/Sub messages

**Scaling:** Auto-scale 0-10 instances

#### nba-analytics-processors
**Purpose:** Generate analytics and summaries

**Endpoints:**
- `/analyze/player-game-summary`
- `/analyze/team-defense-summary`
- `/analyze/team-offense-summary`
- `/analyze/upcoming-game-context`

**Technology:** Python Flask app with analytics modules

**Data Source:** Reads from BigQuery `raw` dataset

**Output:** Writes to BigQuery `analytics` dataset

### Storage

#### GCS Buckets

**nba-props-platform-raw:**
- Raw JSON files from scrapers
- Organized by source and date
- Retention: 90 days
- Used as source of truth

**nba-scraper-logs:**
- Structured scraper logs
- Daily JSONL files
- Used by monitoring tools

**nba-alerts:**
- Alert system state
- Error batching during backfills

#### BigQuery Datasets

**raw:**
- Tables for each data source
- Partitioned by date
- Directly from processors
- Examples: `bdl_box_scores`, `odds_api_props`

**analytics:**
- Derived/aggregated data
- Player summaries, team summaries
- Examples: `player_game_summary`, `team_defense_summary`

**nba_reference:**
- Reference data (players, teams, schedules)
- Slowly changing dimensions
- Examples: `players`, `teams`, `schedule`

**validation:**
- Data quality checks
- Validation results
- Gap detection

## Data Models

### Raw Data (GCS)

**File Structure:**
```
gs://nba-props-platform-raw/
├── bdl_box_scores/
│   └── 2025/10/14/
│       └── data.json          # Array of box scores
├── odds_api_props/
│   └── 2025/10/14/
│       ├── 1728950400_props.json  # Timestamp_props.json
│       └── 1728954000_props.json
└── espn_scoreboard/
    └── 2025/10/14/
        └── data.json
```

**JSON Schema Example (Box Score):**
```json
{
  "game_id": "12345",
  "game_date": "2025-10-14",
  "home_team": "GSW",
  "away_team": "LAL",
  "players": [
    {
      "player_id": "123",
      "player_name": "Stephen Curry",
      "team": "GSW",
      "pts": 30,
      "reb": 5,
      "ast": 8
    }
  ]
}
```

### Processed Data (BigQuery)

**Table:** `raw.bdl_box_scores`

| Column | Type | Description |
|--------|------|-------------|
| game_id | STRING | Unique game identifier |
| game_date | DATE | Date of game |
| player_id | STRING | Player identifier |
| player_name | STRING | Player name |
| team_abbr | STRING | Team abbreviation |
| pts | INTEGER | Points scored |
| reb | INTEGER | Rebounds |
| ast | INTEGER | Assists |
| scraped_at | TIMESTAMP | When data was scraped |

**Partitioned by:** `game_date`

**Table:** `raw.odds_api_player_props`

| Column | Type | Description |
|--------|------|-------------|
| event_id | STRING | Odds API event ID |
| game_date | DATE | Date of game |
| player_id | STRING | Player identifier |
| player_name | STRING | Player name |
| market | STRING | Prop market (e.g., "points") |
| line | FLOAT | Prop line (e.g., 25.5) |
| over_odds | INTEGER | Over odds (e.g., -110) |
| under_odds | INTEGER | Under odds (e.g., -110) |
| bookmaker | STRING | Sportsbook name |
| scraped_at | TIMESTAMP | When data was scraped |

**Partitioned by:** `game_date`

### Analytics Data (BigQuery)

**Table:** `analytics.player_game_summary`

| Column | Type | Description |
|--------|------|-------------|
| universal_player_id | STRING | Universal player ID |
| game_date | DATE | Date of game |
| pts_avg_last_5 | FLOAT | Avg points last 5 games |
| pts_avg_last_10 | FLOAT | Avg points last 10 games |
| home_away_split | FLOAT | Home vs away performance |
| opponent_defense_rank | INTEGER | Opponent defense ranking |
| minutes_trend | FLOAT | Minutes trend |
| ... | ... | Many more analytics fields |

## Event Flow (Pub/Sub)

```
Scraper completes → Publishes to topic → Processor subscribes → Processes data
```

**Topics:**
- `nba-scraper-completed` - Scraper finished
- `nba-processor-completed` - Processor finished
- `nba-analytics-completed` - Analytics finished

**Messages:**
```json
{
  "scraper": "bdl_box_scores",
  "date": "2025-10-14",
  "status": "SUCCESS",
  "gcs_path": "gs://nba-props-platform-raw/bdl_box_scores/2025/10/14/data.json"
}
```

## Monitoring & Alerting

### Logging

**Cloud Logging:**
- All Cloud Run logs
- Workflow execution logs
- Structured logs from scrapers/processors

**Custom Logs (GCS):**
- Scraper run logs (JSONL)
- Alert system state

### Monitoring Tools

**nba-monitor:**
- CLI tool for daily status checks
- Shows workflow executions
- Shows errors
- Color-coded output

**Dashboards:**
- GCP Monitoring dashboard
- Custom monitoring dashboard (JSON config in repo)

### Alerting

**Email Alerts:**
- Critical workflow failures
- Data quality issues
- Proxy/API failures

**Smart Alerting:**
- Batches errors during backfills
- Rate limits per error type
- Summary emails

## Security

### Service Accounts

**workflow-scheduler@**
- Triggers workflows
- Minimal permissions

**nba-scrapers@**
- Read from Secret Manager (API keys)
- Write to GCS
- Publish to Pub/Sub

**nba-processors@**
- Read from GCS
- Write to BigQuery
- Subscribe to Pub/Sub

### Secrets

Stored in Secret Manager:
- API keys (Ball Don't Lie, Odds API, etc.)
- Proxy credentials
- Database credentials (if any)

## Scalability

### Current Scale
- ~50 scrapers running daily
- ~30 games per day (in season)
- ~400 player props per day
- ~2GB raw data per day

### Auto-scaling
- Cloud Run scales 0-10 instances per service
- Workflow can run concurrent steps
- BigQuery handles large queries automatically

### Cost Optimization
- Cloud Run scales to zero when idle
- GCS lifecycle policies (90 day retention)
- BigQuery partitioned tables (scan only needed dates)
- Workflow retries with backoff

## Future Enhancements

### Planned
1. **Report Generator Service** - ML predictions for props
2. **Real-time Dashboard** - Live game tracking
3. **API Gateway** - Public API for prop data
4. **Mobile App** - iOS/Android apps

### Potential Improvements
1. **Caching Layer** - Redis for frequently accessed data
2. **GraphQL API** - More flexible querying
3. **Data Warehouse** - Snowflake or Databricks for advanced analytics
4. **CI/CD Pipeline** - Automated testing and deployment

## Related Documentation

- [Workflow Monitoring Guide](./WORKFLOW_MONITORING.md)
- [Troubleshooting Guide](./TROUBLESHOOTING.md)
- [Deployment Guide](./DEPLOYMENT.md)
- [Scraper Development Guide](./SCRAPER_DEVELOPMENT.md)
