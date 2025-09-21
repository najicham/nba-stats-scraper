# NBA.com Gamebook Processor

## Overview
Processes NBA.com gamebook data (box scores with DNP/inactive players) from GCS to BigQuery.

## Data Volume
- **Seasons**: 2021-22 through 2024-25
- **Games per season**: ~1,230 regular season + ~100 playoff games
- **Players per game**: ~30-35 (active + inactive)
- **Total records**: ~175,000 player-game records

## Quick Start

### Test with sample file
```bash
python scripts/test_nbac_gamebook_processor.py \
  --gcs-file gs://nba-scraped-data/nba-com/gamebooks-data/2021-10-19/20211019-BKNMIL.json