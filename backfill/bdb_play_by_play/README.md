# BigDataBall 2024-25 Season Enhanced Play-by-Play Backfill

Complete enhanced play-by-play data collection for NBA 2024-25 season from BigDataBall via Google Drive.

## Overview

This backfill job collects all missing BigDataBall enhanced play-by-play data for the 2024-25 NBA season and saves it to the existing GCS structure:

```
gs://nba-scraped-data/big-data-ball/2024-25/
├── 2024-10-15/
│   ├── game_0022500001/
│   │   └── [2024-10-15]-0022500001-LAL@GSW.csv
│   └── game_0022500002/
│       └── [2024-10-15]-0022500002-BOS@NYK.csv
└── 2024-10-16/
    └── ...
```

## Architecture

The backfill uses your existing scrapers:
- **Discovery**: `bigdataball_discovery.py` - finds available games by date
- **Download**: `bigdataball_pbp.py` - downloads individual game CSV files
- **Orchestration**: Cloud Run job coordinates the entire process

**Follows established patterns**: Matches the same deployment and monitoring approach as `bp_props`, `nbac_gamebook`, and other backfill jobs.

## Setup Instructions

### 1. Deploy the Job
```bash
# Run from project root
./backfill/bdb_play_by_play/deploy_bdb_play_by_play_backfill.sh
```

### 2. Environment Setup
The deployment script automatically configures:
- `SCRAPER_SERVICE_URL`: Points to your NBA scrapers service
- BigDataBall service account credentials (must be set up in GCP)

## Usage

### ⚠️ CRITICAL: Correct Args Syntax

**The gcloud args parsing is very specific. Use these EXACT patterns:**

```bash
# ✅ CORRECT: Using = syntax with no spaces or quotes
gcloud run jobs execute bdb-play-by-play-backfill \
    --region=us-west2 \
    --args=--start_date=2024-12-01,--end_date=2024-12-01

# ✅ CORRECT: For dry run
gcloud run jobs execute bdb-play-by-play-backfill \
    --region=us-west2 \
    --args=--dry-run

# ❌ WRONG: These will ALL fail with "cannot be specified multiple times" error
--args="--start_date","2024-12-01","--end_date","2024-12-01"  # Quotes create multiple args
--args='--start_date,2024-12-01,--end_date,2024-12-01'        # Commas split incorrectly
--args=--start_date,2024-12-01,--end_date,2024-12-01          # Without = syntax fails
```

### Complete Season Backfill
```bash
# Default: entire 2024-25 season (Oct 2024 - Aug 2025)
gcloud run jobs execute bdb-play-by-play-backfill --region=us-west2
```

### Custom Date Range
```bash
# Specific date range (USE THIS EXACT SYNTAX)
gcloud run jobs execute bdb-play-by-play-backfill \
    --region=us-west2 \
    --args=--start_date=2024-10-01,--end_date=2025-06-30
```

### Testing & Development
```bash
# Test with single day first (RECOMMENDED)
gcloud run jobs execute bdb-play-by-play-backfill \
    --region=us-west2 \
    --args=--start_date=2024-12-01,--end_date=2024-12-01

# Test with 1 month
gcloud run jobs execute bdb-play-by-play-backfill \
    --region=us-west2 \
    --args=--start_date=2024-10-01,--end_date=2024-11-01

# Dry run (see what would be processed)
gcloud run jobs execute bdb-play-by-play-backfill \
    --region=us-west2 \
    --args=--dry-run
```

## Implementation Details

### Discovery Response Structure

The `bigdataball_discovery` scraper returns games in this format:

```json
{
  "data_summary": {
    "games": [
      {
        "game_id": "0022400305",
        "date": "2024-12-01",
        "teams": "ORL@BKN",
        "home_team": "BKN",
        "away_team": "ORL",
        "file_id": "1GAVfgC-TkU4iOSIWvarUYHkBn_CJ1NMV",
        "file_name": "[2024-12-01]-0022400305-ORL@BKN.csv",
        "size_bytes": 173176
      }
    ],
    "totalGames": 10
  }
}
```

### Key Code Components

The backfill job extracts games from discovery responses:

```python
def _extract_games_from_discovery_response(self, discovery_data: Dict, date_str: str) -> List[Dict]:
    """Extract games from discovery scraper response."""
    try:
        data_summary = discovery_data.get('data_summary', {})
        
        if isinstance(data_summary, dict):
            # Get the actual games list from the summary
            games = data_summary.get('games', [])
            
            if games:
                logger.debug("Found %d games for %s", len(games), date_str)
                return games
            
        logger.debug("No games found in discovery response for %s", date_str)
        return []
        
    except Exception as e:
        logger.warning("Error extracting games from discovery response for %s: %s", date_str, e)
        return []
```

## Monitoring

### Use the Monitoring Script
```bash
# Create monitoring script
./bin/backfill/bdb_play_by_play_monitor.sh
```

### Manual Monitoring
```bash
# View recent executions
gcloud run jobs executions list --job=bdb-play-by-play-backfill --region=us-west2 --limit=5

# Follow live logs
gcloud logging tail "resource.type=cloud_run_job AND resource.labels.job_name=bdb-play-by-play-backfill" --format="value(textPayload)"

# Check execution status
gcloud run jobs executions describe [EXECUTION_ID] --region=us-west2
```

## Data Validation

### Check GCS Structure
```bash
# Verify 2024-25 season directory exists
gcloud storage ls gs://nba-scraped-data/big-data-ball/2024-25/

# Count total games collected
gcloud storage ls -r gs://nba-scraped-data/big-data-ball/2024-25/*/game_*/ | wc -l

# Check specific date (e.g., December 1st has 10 games)
gcloud storage ls gs://nba-scraped-data/big-data-ball/2024-25/2024-12-01/

# Validate game file content
gcloud storage cat gs://nba-scraped-data/big-data-ball/2024-25/2024-12-01/game_*/\*.csv | head -10
```

### Data Quality Checks
```bash
# Check file sizes (should be ~2-5MB for enhanced PBP)
gcloud storage du gs://nba-scraped-data/big-data-ball/2024-25/ | tail -10

# Compare with existing seasons
for season in "2021-22" "2022-23" "2023-24"; do
  count=$(gcloud storage ls -r gs://nba-scraped-data/big-data-ball/${season}/*/game_*/ | wc -l)
  echo "${season}: ${count} games"
done
```

## Expected Results

### Timeline
- **Discovery Phase**: 30-60 minutes (depends on season scope)
- **Download Phase**: 4-8 hours (depends on number of games)
- **Total Duration**: 5-9 hours for complete season

### Data Volume
- **Games per Season**: ~1,300 regular season + ~90 playoff games
- **File Size per Game**: 2-5 MB (enhanced play-by-play)
- **Total Season Size**: 3-7 GB
- **Records per Game**: 500-800 play-by-play events with 40+ fields each

### Success Metrics
- **Coverage**: 95%+ of available games
- **Data Quality**: All CSV files contain enhanced play-by-play data
- **Structure**: Matches existing 2021-2023 season organization
- **Resume Logic**: Job can be safely restarted and will skip existing games

## Troubleshooting

### Common Issues

**Args Parsing Errors**
```
ERROR: argument --args: "2024-12-01" cannot be specified multiple times
```
- **Solution**: Use the EXACT syntax shown above with `=` and no spaces/quotes
- **Rule**: `--args=--param1=value1,--param2=value2` (all one string, no spaces)

**Service Account Access**
- Verify BigDataBall service account has Google Drive access
- Check that credentials are properly configured in GCP

**Discovery Failures**
- Ensure `bigdataball_discovery` scraper is deployed and accessible
- Check `SCRAPER_SERVICE_URL` environment variable
- Verify Google Drive API quotas

**Download Failures**
- Monitor individual game download timeouts (2 minutes each)
- Check Cloud Run job logs for specific error messages
- Verify GCS write permissions

### Recovery Commands
```bash
# Test discovery for specific date
curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
     -H "Content-Type: application/json" \
     -d '{"scraper": "bigdataball_discovery", "date": "2024-12-01"}'

# Test specific game download
curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
     -H "Content-Type: application/json" \
     -d '{"scraper": "bigdataball_pbp", "game_id": "0022400305", "export_groups": "dev"}'

# Restart from specific date (after fixing issues)
gcloud run jobs execute bdb-play-by-play-backfill \
    --region=us-west2 \
    --args=--start_date=2025-01-15,--end_date=2025-08-19
```

### Job Configuration
- **Timeout**: 8 hours (sufficient for full season)
- **Memory**: 2GB
- **CPU**: 1 core
- **Max Retries**: 1
- **Rate Limiting**: 2 seconds between downloads

## Integration

### Complete 4-Season Dataset
Once backfill completes, you'll have:
- **2021-22**: ✅ Complete (existing)
- **2022-23**: ✅ Complete (existing)  
- **2023-24**: ✅ Complete (existing)
- **2024-25**: ✅ Complete (new)

### Next Steps
1. **Validate Data Quality**: Run validation scripts on complete dataset
2. **Update Documentation**: Mark 2024-25 as complete in backfill summary
3. **Analytics Integration**: Begin using 4-season enhanced play-by-play data
4. **Model Training**: Train prop prediction models with complete historical data
5. **Real-time Pipeline**: Integrate with ongoing 2024-25 season collection

### Dependencies
- Existing `bigdataball_discovery` and `bigdataball_pbp` scrapers
- BigDataBall Google Drive service account access
- GCS path builder: `"bigdataball_pbp": "big-data-ball/%(nba_season)s/%(date)s/game_%(game_id)s/%(filename)s.csv"`

## Key Learnings & Best Practices

### 1. GCloud Args Parsing
- **Always use `=` syntax**: `--args=--param=value,--param2=value2`
- **Never use quotes or spaces** in the args string
- **Commas are argument separators**, not value delimiters
- Test with simple cases before complex date ranges

### 2. Discovery Scraper Pattern
- Discovery scrapers return small metadata (game lists)
- The "data" IS the summary for discovery scrapers
- No need to minimize - 200 bytes/game is negligible

### 3. Testing Strategy
- Always test with a single day first (e.g., 2024-12-01)
- Verify discovery response structure with curl
- Monitor logs in real-time during first run
- Check GCS structure after each test

---

**Deployment**: `./backfill/bdb_play_by_play/deploy_bdb_play_by_play_backfill.sh`  
**Monitoring**: `./bin/backfill/bdb_play_by_play_monitor.sh`  
**Pattern**: Follows established backfill conventions (matches `bp_props`, `nbac_gamebook`)  
**Completion Target**: Complete 2024-25 enhanced play-by-play dataset
