# BigDataBall Google Drive Integration - Technical Documentation

## Overview

BigDataBall provides enhanced NBA play-by-play data through a shared Google Drive folder containing CSV files. This document details the file organization, data structure, and integration patterns discovered through comprehensive exploration and testing.

## Authentication & Access

### Service Account Setup
- **Method**: Google Cloud Service Account with JSON key file
- **Scopes**: `https://www.googleapis.com/auth/drive.readonly`
- **Access Grant**: Must contact BigDataBall to add service account email to shared folder
- **Our Service Account**: `bigdataball-puller@nba-props-platform.iam.gserviceaccount.com`

### Environment Configuration
```bash
# Required environment variable
BIGDATABALL_SERVICE_ACCOUNT_KEY_PATH="/path/to/service-account-key.json"
```

## Folder Structure

### Root Folders
```
BigDataBall Shared Drive/
├── 24-25-nba-pbp/          # Current season data
│   ├── Individual games     # Single game files
│   └── Season combined      # Full season aggregate
└── daily-archive/           # Daily combined files
    └── Daily games          # All games per day
```

### Folder Details

#### `24-25-nba-pbp/` 
- **Purpose**: Primary folder for 2024-25 NBA season
- **Last Modified**: 2025-06-24 (end of Finals)
- **Contents**: 20 files total
  - 19 individual game files
  - 1 full season combined file

#### `daily-archive/`
- **Purpose**: Daily aggregated files (all games per day)
- **Last Modified**: 2024-10-24 (season start)
- **Contents**: 20+ daily combined files

## File Types & Naming Patterns

### 1. Individual Game Files
**Pattern**: `[YYYY-MM-DD]-GGGGGGGGGG-AAA@HHH.csv`

**Examples**:
- `[2025-06-22]-0042400407-IND@OKC.csv`
- `[2025-06-19]-0042400406-OKC@IND.csv`

**Structure**:
- `YYYY-MM-DD`: Game date
- `GGGGGGGGGG`: NBA game ID (10 digits)
- `AAA@HHH`: Away team @ Home team

**Characteristics**:
- **Size**: 0.1-0.2 MB per file
- **Plays**: 500-1,000 plays per game
- **Update Time**: 2-3 hours after game completion

### 2. Daily Combined Files
**Pattern**: `[MM-DD-YYYY]-[MM-DD-YYYY]-combined-stats.csv`

**Examples**:
- `[05-07-2025]-[05-07-2025]-combined-stats.csv`
- `[05-06-2025]-[05-06-2025]-combined-stats.csv`

**Structure**:
- Same start/end date indicates single day
- Contains all games played on that date

**Characteristics**:
- **Size**: 0.3-0.5 MB per file
- **Plays**: 1,000-3,000 plays (multiple games)
- **Location**: Stored in `daily-archive/` folder

### 3. Season Combined File
**Pattern**: `[MM-DD-YYYY]-[MM-DD-YYYY]-combined-stats.csv`

**Example**: `[10-22-2024]-[06-22-2025]-combined-stats.csv`

**Structure**:
- Different start/end dates indicate date range
- Spans from season start to Finals end

**Characteristics**:
- **Size**: 198.9 MB (massive!)
- **Plays**: 617,280 plays (entire season)
- **Location**: Stored in `24-25-nba-pbp/` folder

## Data Structure

### Column Schema (44 fields)
```json
{
  "columns": [
    "game_id",           # NBA game identifier
    "data_set",          # e.g., "NBA 2025 Playoffs"
    "date",              # Game date YYYY-MM-DD
    
    # Player Lineups (10 players on court)
    "a1", "a2", "a3", "a4", "a5",  # Away team positions 1-5
    "h1", "h2", "h3", "h4", "h5",  # Home team positions 1-5
    
    # Game State
    "period",            # Quarter/OT number
    "away_score",        # Away team score
    "home_score",        # Home team score
    "remaining_time",    # Time left in period
    "elapsed",           # Time elapsed in period
    "play_length",       # Duration of play
    "play_id",           # Sequential play number
    
    # Event Details
    "team",              # Team executing play
    "event_type",        # Type of event
    "player",            # Primary player involved
    "type",              # Detailed event type
    "description",       # Human readable description
    
    # Action Specifics
    "assist",            # Assisting player
    "block",             # Blocking player
    "steal",             # Stealing player
    "points",            # Points scored on play
    "result",            # Made/missed for shots
    "reason",            # Reason for certain events
    
    # Shot Analytics
    "shot_distance",     # Distance of shot attempt
    "original_x",        # Court X coordinate
    "original_y",        # Court Y coordinate  
    "converted_x",       # Converted X coordinate
    "converted_y",       # Converted Y coordinate
    
    # Substitutions
    "entered",           # Player entering game
    "left",              # Player leaving game
    
    # Statistical Context
    "possession",        # Possession indicator
    "num",               # Number (free throw attempts, etc.)
    "outof",             # Out of (free throw attempts, etc.)
    "away",              # Away team context
    "home",              # Home team context
    "opponent"           # Opponent context
  ]
}
```

### Sample Play Data

#### Game Start
```json
{
  "game_id": 42400407,
  "data_set": "NBA 2025 Playoffs",
  "date": "2025-06-22",
  "a1": "Myles Turner",
  "a2": "Tyrese Haliburton", 
  "a3": "Andrew Nembhard",
  "a4": "Aaron Nesmith",
  "a5": "Pascal Siakam",
  "h1": "Chet Holmgren",
  "h2": "Jalen Williams",
  "h3": "Luguentz Dort", 
  "h4": "Shai Gilgeous-Alexander",
  "h5": "Isaiah Hartenstein",
  "period": 1,
  "away_score": 0,
  "home_score": 0,
  "remaining_time": "0:12:00",
  "event_type": "start of period",
  "type": "start of period"
}
```

#### Scoring Play
```json
{
  "game_id": 42400407,
  "period": 1,
  "away_score": 22,
  "home_score": 25,
  "remaining_time": "0:00:01",
  "team": "OKC",
  "event_type": "free throw",
  "player": "Chet Holmgren",
  "points": 1.0,
  "result": "made",
  "num": 2.0,
  "outof": 2.0,
  "type": "free throw 2/2",
  "description": "Holmgren Free Throw 2 of 2 (5 PTS)"
}
```

#### Game End
```json
{
  "game_id": 42400407,
  "period": 4,
  "away_score": 91,
  "home_score": 103,
  "remaining_time": "0:00:00",
  "event_type": "end of period",
  "type": "end of period"
}
```

## Data Characteristics

### Game Example: IND@OKC Game 7 Finals
- **Teams**: Indiana Pacers @ Oklahoma City Thunder
- **Date**: June 22, 2025
- **Game ID**: 0042400407
- **Total Plays**: 510
- **Final Score**: OKC 103, IND 91
- **File Size**: ~0.2 MB

### Key Data Features

#### Player Tracking
- Complete starting lineups for each play
- Real-time substitution tracking
- Position-by-position player assignment

#### Game State Precision
- Second-by-second game clock
- Running score maintenance
- Period/overtime tracking

#### Event Granularity
- Every possession recorded
- Shot attempts with coordinates
- Assists, blocks, steals attribution
- Free throw sequences (1 of 2, 2 of 2)

#### Advanced Analytics Ready
- Shot distance calculations
- Court coordinates (original + converted)
- Possession indicators
- Player entry/exit tracking

## Data Freshness & Availability

### Update Schedule
- **Regular Season**: Games updated 2-3 hours post-completion
- **Playoffs**: Same 2-3 hour delay
- **Off-Season**: No new data (July-September)

### Current Status (July 2025)
- **Latest Game**: June 22, 2025 (NBA Finals Game 7)
- **Season Complete**: 2024-25 season fully available
- **Next Updates**: October 2025 (new season start)

### Historical Availability
- **Complete Season**: Oct 22, 2024 - June 22, 2025
- **Daily Archives**: Available in `daily-archive/` folder
- **Individual Games**: All playoff and regular season games

## Scraper Implementation

### Scraper Architecture
BigDataBall integration consists of **two focused scrapers** following clean separation of concerns:

#### **1. 🔍 Discovery Scraper** (`scrapers/bigdataball/bigdataball_discovery.py`)
- **Purpose**: Fast file discovery and metadata collection (no downloading)
- **Class**: `BigDataBallDiscoveryScraper`
- **Inheritance**: `ScraperBase` + `ScraperFlaskMixin`
- **Performance**: 2-3 seconds (vs 30+ seconds for large downloads)

#### **2. 📥 Download Scraper** (`scrapers/bigdataball/bigdataball_pbp.py`)
- **Purpose**: Targeted downloading of specific games/files
- **Class**: `BigDataBallPbpScraper` 
- **Inheritance**: `ScraperBase` + `ScraperFlaskMixin`
- **Performance**: 3-60 seconds depending on file size

### Dependencies
```bash
# Required packages (install with pip)
google-api-python-client>=2.176.0
google-auth-httplib2>=0.2.0
google-auth-oauthlib>=1.2.2
pandas>=2.3.0
openpyxl>=3.1.5  # For Excel compatibility
```

### Environment Configuration
```bash
# Required environment variable
BIGDATABALL_SERVICE_ACCOUNT_KEY_PATH="/path/to/service-account-key.json"

# Alternative (uses standard Google credential)
GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

## Discovery Scraper Usage

### Command Line Usage

#### Basic Discovery Commands
```bash
# Discover files for specific date (default format: detailed)
python scrapers/bigdataball/bigdataball_discovery.py --debug --date=2025-06-22

# Simple format for programmatic access
python scrapers/bigdataball/bigdataball_discovery.py --debug --date=2025-06-22 --format=simple

# Recent files discovery
python scrapers/bigdataball/bigdataball_discovery.py --debug --scope=recent

# Team-focused discovery
python scrapers/bigdataball/bigdataball_discovery.py --debug --scope=team_focus --teams=LAL

# All individual games
python scrapers/bigdataball/bigdataball_discovery.py --debug --scope=all_individual
```

#### Capture Tool Integration
```bash
# Via capture tool (recommended for production)
python tools/fixtures/capture.py bigdataball_discovery --date=2025-06-22 --format=simple --debug
python tools/fixtures/capture.py bigdataball_discovery --scope=recent --format=simple --debug
```

### Discovery Parameters

#### Required Parameters
None (all parameters have defaults)

#### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `date` | string | yesterday | Target date (YYYY-MM-DD format) |
| `scope` | string | `date_specific` | Discovery scope |
| `format` | string | `detailed` | Output format |
| `teams` | string | none | Team filter (for team_focus scope) |
| `days` | integer | 7 | Number of days for recent scope |
| `service_account_key_path` | string | env variable | Path to service account JSON key |

#### Discovery Scope Options

| Scope | Description | Use Case |
|-------|-------------|----------|
| `date_specific` | Files for specific date | Daily game discovery |
| `recent` | Recent files (last N days) | Catch-up processing |
| `all_individual` | All individual games | Full catalog |
| `team_focus` | Games for specific teams | Team analysis |

#### Output Format Options

| Format | Description | Best For |
|--------|-------------|----------|
| `detailed` | Rich categorized output with download commands | Human review, complex workflows |
| `simple` | Flat structure optimized for code | Automated processing, game ID extraction |

### Discovery Output Formats

#### Simple Format (Recommended for Automation)
```json
{
  "date": "2025-06-22",
  "timestamp": "2025-07-23T01:51:51.830484+00:00",
  "source": "bigdataball",
  "mode": "discovery",
  "scope": "date_specific", 
  "results": {
    "format": "simple",
    "discovery_date": "2025-06-22",
    "count": 1,
    "games": [
      {
        "file_id": "1kAXcvezicVCMNDTAY3Byovev3yqF_KvE",
        "file_name": "[2025-06-22]-0042400407-IND@OKC.csv",
        "size": "170.0 KB",
        "size_bytes": 174127,
        "modified": "2025-06-23T06:58:05.000Z",
        "game_id": "0042400407",
        "date": "2025-06-22",
        "teams": "IND@OKC",
        "away_team": "IND", 
        "home_team": "OKC"
      }
    ]
  }
}
```

#### Detailed Format (Rich Metadata)
```json
{
  "results": {
    "format": "detailed",
    "total_files": 4,
    "categories": {
      "individual_games": {
        "count": 3,
        "files": [
          {
            "id": "1kAXcvezicVCMNDTAY3Byovev3yqF_KvE",
            "name": "[2025-06-22]-0042400407-IND@OKC.csv",
            "size": "170.0 KB",
            "download_commands": {
              "by_game_id": "python scrapers/bigdataball/bigdataball_pbp.py --data_type=specific_game --game_id=0042400407",
              "by_teams": "python scrapers/bigdataball/bigdataball_pbp.py --data_type=specific_game --teams=IND@OKC"
            }
          }
        ]
      },
      "daily_combined": { "count": 0, "files": [] },
      "season_combined": { "count": 1, "files": [...] }
    }
  }
}
```

## Download Scraper Usage

### Command Line Usage

#### Basic Download Commands
```bash
# Get latest individual game (default behavior)
python scrapers/bigdataball/bigdataball_pbp.py --debug

# Get specific game by ID
python scrapers/bigdataball/bigdataball_pbp.py --debug --data_type=specific_game --game_id=0042400407

# Get specific team matchup
python scrapers/bigdataball/bigdataball_pbp.py --debug --data_type=specific_game --teams="IND@OKC"

# Get all individual games from a date (separate files)
python scrapers/bigdataball/bigdataball_pbp.py --debug --data_type=daily_individual --date=2025-06-22

# Get daily combined file
python scrapers/bigdataball/bigdataball_pbp.py --debug --data_type=daily_combined --date=2025-05-07

# Get full season file (WARNING: 200MB)
python scrapers/bigdataball/bigdataball_pbp.py --debug --data_type=season_combined
```

#### Capture Tool Integration
```bash
# Via capture tool (recommended for production)
python tools/fixtures/capture.py bigdataball_pbp --data_type=latest_individual --debug
python tools/fixtures/capture.py bigdataball_pbp --data_type=specific_game --game_id=0042400407 --debug
python tools/fixtures/capture.py bigdataball_pbp --data_type=daily_individual --date=2025-06-22 --debug
```

### Download Parameters

#### Required Parameters
None (all parameters have defaults)

#### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `date` | string | yesterday | Target date (YYYY-MM-DD format) |
| `data_type` | string | `latest_individual` | Type of data to retrieve |
| `game_id` | string | none | Specific NBA game ID |
| `teams` | string | none | Team matchup filter |
| `service_account_key_path` | string | env variable | Path to service account JSON key |
| `debug` | boolean | false | Enable verbose logging |

#### Data Type Options

| Data Type | Description | File Pattern | Use Case |
|-----------|-------------|--------------|----------|
| `latest_individual` | Most recent single game | `[YYYY-MM-DD]-GGGGGGGGGG-AAA@HHH.csv` | Daily prop analysis |
| `daily_individual` | All games from date, separate files | Multiple individual files | Parallel processing |
| `specific_game` | Target by game ID or teams | Single matching file | Targeted analysis |
| `daily_combined` | All games from specific date | `[MM-DD-YYYY]-[MM-DD-YYYY]-combined-stats.csv` | Historical analysis |
| `season_combined` | Full season data | `[10-22-2024]-[06-22-2025]-combined-stats.csv` | Model training |

### GCS Storage Integration

#### Discovery Results
```
gs://your-nba-props-bucket/
└── big-data-ball/
    └── discovery/
        └── {date}/
            └── {timestamp}.json
```

#### Download Results
```
gs://your-nba-props-bucket/
└── big-data-ball/
    └── enhanced-pbp/
        └── {date}/
            └── {timestamp}.json
```

#### GCS Path Templates
```python
# Discovery scraper
"big-data-ball/discovery/%(date)s/%(timestamp)s.json"

# Download scraper  
"big-data-ball/enhanced-pbp/%(date)s/%(timestamp)s.json"
```

#### Example Paths
```
# Discovery results
gs://nba-props-bucket/big-data-ball/discovery/2025-07-22/20250722_140530.json

# Individual game download
gs://nba-props-bucket/big-data-ball/enhanced-pbp/2025-07-22/20250722_143022.json

# Multiple games (daily_individual creates multiple files)
/tmp/bigdataball_game_abc123_[2025-06-22]-0042400407-IND@OKC.json
/tmp/bigdataball_game_abc123_[2025-06-22]-0042400406-LAL@GSW.json
```

### Export Modes

#### Development/Testing
```python
# Discovery scraper
{
    "type": "file",
    "filename": "/tmp/bigdataball_discovery_%(date)s.json",
    "pretty_print": True,
    "export_mode": ExportMode.DATA
}

# Download scraper
{
    "type": "file", 
    "filename": "/tmp/bigdataball_pbp_%(date)s.json",
    "pretty_print": True,
    "export_mode": ExportMode.DATA
}
```

#### Production
```python
# Discovery scraper
{
    "type": "gcs",
    "key": "big-data-ball/discovery/%(date)s/%(timestamp)s.json",
    "export_mode": ExportMode.DATA
}

# Download scraper
{
    "type": "gcs", 
    "key": "big-data-ball/enhanced-pbp/%(date)s/%(timestamp)s.json",
    "export_mode": ExportMode.DATA
}
```

## Optimal Workflows

### Recommended Discovery → Download Pattern

#### 1. **Fast Discovery First**
```bash
# See what's available (2-3 seconds)
python scrapers/bigdataball/bigdataball_discovery.py --date=2025-06-22 --format=simple
```

#### 2. **Programmatic Game ID Extraction**
```python
import json

# Load discovery results
with open('/tmp/bigdataball_discovery_2025-06-22.json') as f:
    results = json.load(f)['results']

# Extract game IDs
game_ids = [game['game_id'] for game in results['games']]
print(f"Found {results['count']} games: {game_ids}")
```

#### 3. **Targeted Downloads**
```bash
# Download specific games by ID
python scrapers/bigdataball/bigdataball_pbp.py --data_type=specific_game --game_id=0042400407
```

### Production Deployment Patterns

#### Morning Discovery Workflow
```bash
# 1. Discover overnight games
python tools/fixtures/capture.py bigdataball_discovery --scope=recent --format=simple --group=prod

# 2. Process discovery results and download key games
# (automated processing based on discovery JSON)

# 3. Generate prop bet analysis from downloaded data
```

#### Game-Specific Analysis
```bash
# 1. Target specific matchup
python tools/fixtures/capture.py bigdataball_discovery --scope=team_focus --teams=LAL --format=simple --group=prod

# 2. Download Lakers games for detailed analysis
python tools/fixtures/capture.py bigdataball_pbp --data_type=specific_game --teams=LAL --group=prod
```

#### Historical Research
```bash
# 1. Discover games from playoff dates
python tools/fixtures/capture.py bigdataball_discovery --date=2025-05-15 --format=simple --group=prod

# 2. Download all games from that date for batch analysis
python tools/fixtures/capture.py bigdataball_pbp --data_type=daily_individual --date=2025-05-15 --group=prod
```

### Performance Characteristics

#### Discovery Scraper Performance
- **Individual game discovery**: 2-3 seconds
- **Recent files (7 days)**: 3-5 seconds  
- **Team-focused discovery**: 2-4 seconds
- **Memory usage**: 20-50MB
- **Network**: Minimal (metadata only)

#### Download Scraper Performance
- **Individual game**: 3-5 seconds (500-1000 plays)
- **Daily combined**: 5-10 seconds (1000-3000 plays)
- **Season combined**: 30-60 seconds (617K+ plays, 200MB)
- **Memory usage**: 50-100MB for individual games, 500MB+ for season file
- **Network**: 0.1-200MB depending on file type

### Error Handling & Monitoring

#### Common Discovery Issues
```python
# No files found for date (off-season)
"totalGames": 0, "games": []

# Service account access issues
ValueError: Service account key file not found

# BigDataBall access not granted
google.api_core.exceptions.Forbidden: 403 Forbidden
```

#### Discovery Stats Output
```python
{
    "mode": "discovery",
    "format": "simple", 
    "scope": "date_specific",
    "totalGames": 1,
    "date": "2025-06-22",
    "source": "bigdataball"
}
```

#### Download Stats Output  
```python
{
    "playCount": 510,
    "dataType": "individual_game", 
    "requestedDataType": "specific_game",
    "gameId": "0042400407",
    "teams": "IND@OKC",
    "source": "bigdataball"
}
```

### Sample Output Structures

#### Discovery Simple Format Result
```json
{
  "results": {
    "format": "simple",
    "count": 1,
    "games": [
      {
        "file_id": "1kAXcvezicVCMNDTAY3Byovev3yqF_KvE",
        "game_id": "0042400407",
        "date": "2025-06-22",
        "teams": "IND@OKC",
        "away_team": "IND",
        "home_team": "OKC", 
        "size": "170.0 KB",
        "size_bytes": 174127,
        "modified": "2025-06-23T06:58:05.000Z"
      }
    ]
  }
}
```

#### Download Scraper Result
```json
{
    "date": "2025-07-22",
    "timestamp": "2025-07-23T01:03:39.716312+00:00",
    "source": "bigdataball",
    "file_info": {
        "name": "bigdataball_8bb6f4b9_[2025-06-22]-0042400407-IND@OKC.csv",
        "processed_at": "2025-07-23T01:03:39.716312+00:00", 
        "total_plays": 510,
        "columns": ["game_id", "data_set", "date", ...]
    },
    "playByPlay": [
        {
            "game_id": 42400407,
            "date": "2025-06-22",
            "period": 1,
            "away_score": 0,
            "home_score": 0,
            "event_type": "start of period",
            ...
        }
    ]
}
```

### Testing & Validation

#### Discovery Test Commands
```bash
# Test service account access
python scrapers/bigdataball/bigdataball_discovery.py --debug --scope=recent

# Test specific date discovery
python scrapers/bigdataball/bigdataball_discovery.py --debug --date=2025-06-22 --format=simple

# Test team discovery
python scrapers/bigdataball/bigdataball_discovery.py --debug --scope=team_focus --teams=LAL --format=simple
```

#### Download Test Commands
```bash
# Test latest individual game
python scrapers/bigdataball/bigdataball_pbp.py --debug --data_type=latest_individual

# Test specific game download
python scrapers/bigdataball/bigdataball_pbp.py --debug --data_type=specific_game --game_id=0042400407

# Test with known game from discovery
python scrapers/bigdataball/bigdataball_pbp.py --debug --data_type=specific_game --teams="IND@OKC"
```

#### Validation Checks
- **Discovery**: File count > 0, valid game IDs extracted, correct date filtering
- **Download**: CSV processing successful, JSON export contains expected fields, play count matches expected range
- **Integration**: Discovery results can be used to drive download commands

### Integration with NBA Props Platform

#### Daily Operations Workflow
```bash
# 1. Morning discovery (fast check of overnight games)
python tools/fixtures/capture.py bigdataball_discovery --scope=recent --format=simple --group=prod

# 2. Extract game IDs programmatically and download targeted games
# (Python script processes discovery JSON and triggers downloads)

# 3. Process play-by-play data for prop bet analysis
# (Downstream processors consume the enhanced play-by-play JSON)

# 4. Update prop models with fresh BigDataBall data
# (Model training/updating based on new play-by-play insights)
```

#### Strategic Analysis Workflow
```bash
# 1. Historical game discovery
python tools/fixtures/capture.py bigdataball_discovery --date=2025-05-15 --format=simple --group=prod

# 2. Batch download for model training
python tools/fixtures/capture.py bigdataball_pbp --data_type=daily_individual --date=2025-05-15 --group=prod

# 3. Season-wide analysis (when needed)
python tools/fixtures/capture.py bigdataball_pbp --data_type=season_combined --group=prod
```

#### Automated Processing Pipeline
```python
# Example automation script
def process_daily_bigdataball_data(date_str):
    # 1. Fast discovery
    discovery_cmd = f"python tools/fixtures/capture.py bigdataball_discovery --date={date_str} --format=simple --group=prod"
    subprocess.run(discovery_cmd.split())
    
    # 2. Parse discovery results from GCS
    discovery_data = load_from_gcs(f"big-data-ball/discovery/{date_str}/")
    
    # 3. Download each game
    for game in discovery_data['results']['games']:
        game_id = game['game_id']
        teams = game['teams']
        
        download_cmd = f"python tools/fixtures/capture.py bigdataball_pbp --data_type=specific_game --game_id={game_id} --group=prod"
        subprocess.run(download_cmd.split())
        
        # 4. Trigger downstream prop analysis
        trigger_prop_analysis(game_id, teams)
```

### For Real-Time Props (During Season)
**Recommended**: Individual game files
- **Data Type**: `latest_individual`
- **Files**: `[YYYY-MM-DD]-GGGGGGGGGG-AAA@HHH.csv`
- **Update Frequency**: Every 2-3 hours after games
- **Use Case**: Daily prop bet analysis

### For Historical Analysis
**Recommended**: Daily combined files
- **Data Type**: `daily_combined` 
- **Files**: `[MM-DD-YYYY]-[MM-DD-YYYY]-combined-stats.csv`
- **Location**: `daily-archive/` folder
- **Use Case**: Multi-game analysis, specific date research

### For Model Training
**Recommended**: Season combined file
- **Data Type**: `season_combined`
- **File**: `[10-22-2024]-[06-22-2025]-combined-stats.csv`
- **Size**: 198.9 MB (617K plays)
- **Use Case**: Machine learning model training, backtesting

## Implementation Notes

### File Format
- **Type**: CSV (not Excel as documentation suggests)
- **Encoding**: UTF-8
- **Delimiter**: Comma
- **Headers**: First row contains column names

### Search Optimization
```python
# Individual games (exclude combined files)
query = "name contains '.csv' and not name contains 'combined-stats'"

# Daily combined (search in daily-archive folder)
query = f"name contains '[05-07-2025]-[05-07-2025]-combined-stats.csv'"

# Season combined (large date range)
query = "name contains '2024]-[' and name contains '2025]-combined-stats.csv'"
```

### Performance Considerations
- **Individual games**: Fast processing (~500-1000 plays)
- **Daily combined**: Moderate processing (~1000-3000 plays)
- **Season combined**: Heavy processing (617K+ plays, 200MB)

## Quality & Completeness

### Data Quality
- **Completeness**: Every play recorded
- **Accuracy**: Official NBA play-by-play enhanced with coordinates
- **Consistency**: Standardized format across all games
- **Validation**: Cross-referenced with official NBA data

### Enhanced Features vs Standard NBA Data
- **Player positions**: Real-time lineup tracking
- **Shot coordinates**: X/Y court positions
- **Enhanced events**: More granular event classification
- **Timing precision**: Sub-second timing accuracy
- **Context preservation**: Substitution and rotation tracking

## Use Cases for NBA Props Platform

### Daily Operations (During Season)
1. **Morning Analysis**: Get previous night's games via `latest_individual`
2. **Player Performance**: Extract scoring, assists, rebounds from play-by-play
3. **Trend Analysis**: Compare recent performance using daily files
4. **Model Updates**: Incorporate fresh data into prediction models

### Strategic Analysis
1. **Backtesting**: Use season combined file for model validation
2. **Player Evaluation**: Deep dive into specific player performance patterns
3. **Matchup Analysis**: Historical performance in similar game situations
4. **Injury Impact**: Before/after analysis using daily combined files

### Technical Implementation
1. **Real-time Processing**: 2-3 hour delay allows for same-day analysis
2. **Data Pipeline**: CSV → JSON transformation for downstream processing
3. **Storage Strategy**: GCS integration for cloud-native analytics
4. **API Integration**: RESTful access via Flask endpoints

---

*Last Updated: July 22, 2025*  
*Data Source: BigDataBall Enhanced Play-by-Play via Google Drive*  
*Season Coverage: 2024-25 NBA Season (Complete)*
