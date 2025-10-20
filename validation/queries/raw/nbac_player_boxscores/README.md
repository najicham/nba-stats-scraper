# NBA.com Player Boxscore Pipeline

Complete pipeline for scraping and processing NBA.com player boxscore data (via `leaguegamelog` API).

**Status:** ✅ Operational (Tested on 2024-10-29)  
**Last Updated:** October 19, 2025

---

## 📋 Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Data Flow](#data-flow)
- [Scraping Data](#scraping-data)
- [Processing Data](#processing-data)
- [Validation](#validation)
- [Troubleshooting](#troubleshooting)
- [Known Limitations](#known-limitations)

---

## Overview

This pipeline collects official NBA player statistics from NBA.com and loads them into BigQuery for analysis and prop bet validation.

### What It Does
- Scrapes player boxscore data from `stats.nba.com/stats/leaguegamelog`
- Saves raw JSON to Google Cloud Storage
- Transforms data into structured format
- Loads into BigQuery with deduplication

### What You Get
- **Official NBA statistics** (points, rebounds, assists, etc.)
- **Player identification** via official NBA player IDs
- **Game context** (date, opponent, home/away)
- **Historical data** (once backfilled)

---

## Quick Start

### Prerequisites
- Python virtual environment activated
- GCP credentials configured (`service-account-dev.json`)
- BigQuery table `nba_raw.nbac_player_boxscores` created

### Scrape Today's Games
```bash
# Scrape data for a specific date
python scrapers/nbacom/nbac_player_boxscore.py \
  --gamedate $(date +%Y%m%d) \
  --group gcs \
  --debug
```

### Process Scraped File
```bash
# Process the most recent file
python -m data_processors.raw.nbacom.nbac_player_boxscore_processor \
  --file gs://nba-scraped-data/nba-com/player-boxscores/2024-10-29/TIMESTAMP.json
```

### Verify Data
```bash
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as players, COUNT(DISTINCT game_id) as games
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date = CURRENT_DATE() - 1
GROUP BY game_date
'
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         1. SCRAPING                             │
│  stats.nba.com/stats/leaguegamelog                              │
│         ↓                                                        │
│  scrapers/nbacom/nbac_player_boxscore.py                        │
│         ↓                                                        │
│  gs://nba-scraped-data/nba-com/player-boxscores/YYYY-MM-DD/    │
│  └── HHMMSS.json (raw leaguegamelog format)                     │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                      2. PROCESSING                              │
│  data_processors/raw/nbacom/nbac_player_boxscore_processor.py   │
│         ↓                                                        │
│  Transform: leaguegamelog → player boxscore rows                │
│  Deduplicate: DELETE existing game_ids                          │
│         ↓                                                        │
│  BigQuery: nba_raw.nbac_player_boxscores                        │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                      3. VALIDATION                              │
│  validation/queries/raw/nbac_player_boxscores/*.sql             │
│  - Cross-validate with BDL                                      │
│  - Check completeness vs schedule                               │
│  - Monitor data quality                                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Scraping Data

### Basic Usage

```bash
# Scrape a specific date (YYYYMMDD format)
python scrapers/nbacom/nbac_player_boxscore.py \
  --gamedate 20241029 \
  --group gcs
```

### Parameters

| Parameter | Required | Description | Example |
|-----------|----------|-------------|---------|
| `--gamedate` | Yes | Game date to scrape | `20241029` or `2024-10-29` |
| `--group` | Yes | Export destination | `gcs` (production), `test` (local) |
| `--season` | No | NBA season (auto-detected) | `2024` |
| `--season_type` | No | Season type | `Regular Season` (default) |
| `--debug` | No | Enable debug logging | (flag) |

### Export Groups

| Group | Destination | Use Case |
|-------|-------------|----------|
| `gcs` | `gs://nba-scraped-data/nba-com/player-boxscores/` | Production |
| `test` | `/tmp/getnbacomplayerboxscore2.json` | Local testing |

### Examples

**Scrape yesterday's games:**
```bash
python scrapers/nbacom/nbac_player_boxscore.py \
  --gamedate $(date -d "yesterday" +%Y%m%d) \
  --group gcs
```

**Scrape and test locally:**
```bash
python scrapers/nbacom/nbac_player_boxscore.py \
  --gamedate 20241029 \
  --group test \
  --debug

# Inspect the file
cat /tmp/getnbacomplayerboxscore2.json | jq '.resultSets[0].rowSet | length'
```

**Scrape multiple dates (batch):**
```bash
for date in 20241026 20241027 20241028 20241029; do
  echo "Scraping $date..."
  python scrapers/nbacom/nbac_player_boxscore.py --gamedate $date --group gcs
  sleep 5  # Rate limiting
done
```

### Output Format

The scraper saves data in **leaguegamelog format**:

```json
{
  "resource": "leaguegamelog",
  "parameters": {...},
  "resultSets": [{
    "name": "LeagueGameLog",
    "headers": [
      "SEASON_ID", "PLAYER_ID", "PLAYER_NAME", "TEAM_ID",
      "TEAM_ABBREVIATION", "GAME_ID", "GAME_DATE", "MATCHUP",
      "MIN", "FGM", "FGA", "FG_PCT", "FG3M", "FG3A", "FG3_PCT",
      "FTM", "FTA", "FT_PCT", "OREB", "DREB", "REB",
      "AST", "STL", "BLK", "TOV", "PF", "PTS", "PLUS_MINUS", ...
    ],
    "rowSet": [
      ["22024", 1629627, "Zion Williamson", 1610612740, "NOP",
       "0022400116", "2024-10-29", "NOP @ GSW", 30, 12, 19, 0.632,
       1, 2, 0.5, 6, 8, 0.75, 2, 6, 8, 3, 0, 1, 7, 3, 31, -14, ...]
    ]
  }]
}
```

**Key fields:**
- `headers`: Column names (32 columns)
- `rowSet`: Array of player stat rows (each row = 1 player in 1 game)

---

## Processing Data

### Basic Usage

```bash
# Process a single file
python -m data_processors.raw.nbacom.nbac_player_boxscore_processor \
  --file gs://nba-scraped-data/nba-com/player-boxscores/2024-10-29/20251019_012417.json
```

### Parameters

| Parameter | Required | Description | Default |
|-----------|----------|-------------|---------|
| `--file` | Yes | GCS file path or full gs:// URI | - |
| `--bucket` | No | GCS bucket (if not in --file) | `nba-scraped-data` |
| `--project` | No | GCP project ID | `nba-props-platform` |

### Processing Strategy

The processor uses **MERGE_UPDATE** strategy:

1. **Extract game dates** from the data
2. **DELETE** existing rows for those game_ids and game_dates (deduplication)
3. **INSERT** new rows with latest data

**Why this works:**
- Handles re-runs gracefully (idempotent)
- Updates stats if data changes (e.g., stat corrections)
- Requires partition filter (game_date) for BigQuery

### Examples

**Process with full gs:// URI:**
```bash
python -m data_processors.raw.nbacom.nbac_player_boxscore_processor \
  --file gs://nba-scraped-data/nba-com/player-boxscores/2024-10-29/20251019_012417.json
```

**Process with bucket + path:**
```bash
python -m data_processors.raw.nbacom.nbac_player_boxscore_processor \
  --bucket nba-scraped-data \
  --file nba-com/player-boxscores/2024-10-29/20251019_012417.json
```

**Process all files for a date:**
```bash
# List files for date
gsutil ls gs://nba-scraped-data/nba-com/player-boxscores/2024-10-29/

# Process each one (or just process the latest)
python -m data_processors.raw.nbacom.nbac_player_boxscore_processor \
  --file gs://nba-scraped-data/nba-com/player-boxscores/2024-10-29/[LATEST].json
```

### Expected Output

**Success:**
```
INFO:processor_base:Loaded leaguegamelog data from GCS
INFO:root:Validated 88 player rows in leaguegamelog data
INFO:root:Transformed 88 player records from 4 games
INFO:root:Deleting existing records for 4 games on 1 dates
INFO:root:Inserting 88 rows into nba-props-platform.nba_raw.nbac_player_boxscores
INFO:root:Successfully loaded 88 rows for 4 games
INFO:processor_base:PROCESSOR_STEP Processor completed in 5.5s
```

**Key metrics:**
- `player records`: Number of player-game rows created
- `games`: Number of unique games processed
- `dates`: Number of unique dates

---

## Validation

### Quick Validation

**Check data loaded:**
```bash
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as players, COUNT(DISTINCT game_id) as games
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date >= "2024-10-22"
GROUP BY game_date
ORDER BY game_date DESC
'
```

**Check data quality:**
```bash
bq query --use_legacy_sql=false '
SELECT
  COUNT(*) as total,
  COUNT(DISTINCT nba_player_id) as unique_ids,
  COUNT(CASE WHEN nba_player_id IS NULL THEN 1 END) as missing_ids,
  COUNT(CASE WHEN points IS NULL THEN 1 END) as missing_points
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date = "2024-10-29"
'
```

### Full Validation Suite

All validation queries are in `validation/queries/raw/nbac_player_boxscores/`:

```bash
# Run a specific validation
bq query --use_legacy_sql=false < validation/queries/raw/nbac_player_boxscores/daily_check_yesterday.sql

# Run cross-validation with BDL
bq query --use_legacy_sql=false < validation/queries/raw/nbac_player_boxscores/cross_validate_with_bdl.sql

# Find missing games
bq query --use_legacy_sql=false < validation/queries/raw/nbac_player_boxscores/find_missing_games.sql
```

**See `VALIDATION_STATUS.md` for detailed validation status and plans.**

---

## Troubleshooting

### Scraper Issues

**Error: "No player rows in leaguegamelog JSON"**
- **Cause:** No games on that date or wrong season
- **Fix:** Verify date has games in schedule table, check season parameter

**Error: "argument of type 'NoneType' is not iterable"**
- **Cause:** Season parameter is None
- **Fix:** Updated scraper (Oct 19, 2025) fixes this automatically

**Warning: "No exporters matched group='dev'"**
- **Cause:** Wrong export group specified
- **Fix:** Use `--group gcs` for production or `--group test` for local

**Empty file uploaded (2 bytes, `{}`)**
- **Cause:** Export mode was `DATA` instead of `DECODED`
- **Fix:** Updated scraper uses `DECODED` mode

### Processor Issues

**Error: "Cannot query over table without filter over game_date"**
- **Cause:** DELETE query missing partition filter
- **Fix:** Updated processor includes `game_date IN (...)` filter

**Error: "AttributeError: 'NBATeamMapper' object has no attribute 'normalize_team_abbr'"**
- **Cause:** Wrong method name
- **Fix:** Updated processor uses `get_nba_tricode()` method

**Error: "No module named 'data_processors'"**
- **Cause:** Running processor as script instead of module
- **Fix:** Use `python -m data_processors.raw.nbacom.nbac_player_boxscore_processor` (note the `-m`)

**Error: "Missing 'resultSets' in data"**
- **Cause:** Invalid JSON or wrong data format
- **Fix:** Check scraped file with `gsutil cat [FILE] | jq .`

### Data Issues

**Fewer games than expected**
- **Check schedule:** Compare with `nbac_schedule` table
- **Check file:** Verify all games in scraped JSON
- **Check API:** Some dates may have fewer games

**Missing players**
- **Expected:** DNP players are NOT in leaguegamelog (by design)
- **Check:** Compare with official NBA boxscore
- **Note:** Only active players (played >0 minutes) appear

**Wrong season detected**
- **Cause:** Auto-detection uses game date month
- **Fix:** Manually specify `--season 2024` for 2024-25 season

---

## Known Limitations

### Data Source Limitations

The `leaguegamelog` API does NOT provide:
- ❌ Starter flag (set to NULL)
- ❌ Jersey numbers (set to NULL)
- ❌ Player positions (set to NULL)
- ❌ Enhanced metrics (TS%, Usage%, PIE - set to NULL)
- ❌ Quarter breakdowns (Q1-Q4 points - set to NULL)
- ❌ Technical/Flagrant fouls (set to NULL)
- ❌ Team scores (set to NULL)

**What IS available:**
- ✅ All basic stats (points, rebounds, assists, etc.)
- ✅ Shooting stats (FG%, 3P%, FT%)
- ✅ Plus/Minus
- ✅ Official NBA player IDs
- ✅ Minutes played

**Impact:** For **player points props**, this data is sufficient. Enhanced metrics would require different API endpoint.

### Coverage Limitations

**Current state:**
- ✅ Single date validated (2024-10-29)
- ⏳ Historical data: Not yet backfilled
- ⏳ Daily automation: Not yet set up

**See `VALIDATION_STATUS.md` for detailed coverage status.**

---

## File Locations

### Where to Save These Files

**This README:**
```bash
# Save in the validation queries directory
validation/queries/raw/nbac_player_boxscores/README.md
```

**Validation Status Doc:**
```bash
# Save alongside this README
validation/queries/raw/nbac_player_boxscores/VALIDATION_STATUS.md
```

**Or create a docs directory:**
```bash
mkdir -p docs/nbac_player_boxscores
# Save both files there
docs/nbac_player_boxscores/README.md
docs/nbac_player_boxscores/VALIDATION_STATUS.md
```

---

## Quick Reference Commands

### Daily Operations

**Scrape yesterday's games:**
```bash
python scrapers/nbacom/nbac_player_boxscore.py \
  --gamedate $(date -d "yesterday" +%Y%m%d) \
  --group gcs
```

**Process latest file:**
```bash
# Get latest file
LATEST=$(gsutil ls gs://nba-scraped-data/nba-com/player-boxscores/YYYY-MM-DD/ | tail -1)

# Process it
python -m data_processors.raw.nbacom.nbac_player_boxscore_processor --file $LATEST
```

**Validate yesterday:**
```bash
bq query --use_legacy_sql=false < validation/queries/raw/nbac_player_boxscores/daily_check_yesterday.sql
```

### Backfill Operations

**Scrape date range:**
```bash
# Generate date list
start_date="2024-10-22"
end_date="2024-10-31"

# Loop through dates
current_date=$start_date
while [ "$current_date" != "$end_date" ]; do
  formatted_date=$(date -d "$current_date" +%Y%m%d)
  echo "Scraping $formatted_date..."
  python scrapers/nbacom/nbac_player_boxscore.py --gamedate $formatted_date --group gcs
  sleep 5
  current_date=$(date -d "$current_date + 1 day" +%Y-%m-%d)
done
```

**Process all files for a date:**
```bash
DATE="2024-10-29"
for file in $(gsutil ls gs://nba-scraped-data/nba-com/player-boxscores/$DATE/); do
  echo "Processing $file"
  python -m data_processors.raw.nbacom.nbac_player_boxscore_processor --file "$file"
done
```

---

## Related Files

- **Scraper:** `scrapers/nbacom/nbac_player_boxscore.py`
- **Processor:** `data_processors/raw/nbacom/nbac_player_boxscore_processor.py`
- **Schema:** `schemas/bigquery/nbac_player_boxscore_tables.sql`
- **Validation Queries:** `validation/queries/raw/nbac_player_boxscores/*.sql`
- **Validation Status:** `VALIDATION_STATUS.md` (this directory)

---

## Support & Maintenance

**Last tested:** October 19, 2025  
**Test date:** 2024-10-29 (4 games, 88 players)  
**Status:** ✅ All tests passing

**For issues:**
1. Check `VALIDATION_STATUS.md` for known limitations
2. Review troubleshooting section above
3. Check processor logs in `/tmp/processor_debug_*.json`
4. Validate scraped JSON with `gsutil cat [FILE] | jq .`

---

**End of README**
