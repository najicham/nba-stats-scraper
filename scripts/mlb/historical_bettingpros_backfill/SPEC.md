# MLB BettingPros Historical Props Backfill - Technical Specification

**Created**: 2026-01-14
**Status**: Implementation Ready
**Author**: Claude Code

---

## 1. Overview

### 1.1 Purpose
Collect 4 seasons (2022-2025) of historical MLB player prop betting data from the BettingPros API, including actual outcomes for model training and validation.

### 1.2 Key Advantages Over Odds API
| Feature | BettingPros | Odds API |
|---------|-------------|----------|
| Historical window | 2022+ (4 years) | 6 months |
| Actual outcomes | ✅ Included | ❌ Requires join |
| Projections | ✅ Included | ❌ Not available |
| Performance trends | ✅ Included | ❌ Not available |
| API cost | Free | Paid (usage-based) |

### 1.3 Data Volume Summary
- **Seasons**: 4 (2022-2025)
- **Game days**: ~740
- **Markets**: 11 (2 pitcher, 9 batter)
- **Total prop records**: ~1,140,000
- **API calls**: ~28,120
- **Estimated runtime**: 2-4 hours (1 hour with parallelization)

---

## 2. API Specification

### 2.1 Endpoint
```
GET https://api.bettingpros.com/v3/props
```

### 2.2 Required Headers
```http
Origin: https://www.fantasypros.com
Referer: https://www.fantasypros.com/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
Accept: application/json
```

### 2.3 Query Parameters
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| sport | string | Yes | "MLB" |
| market_id | int | Yes | Market ID (see section 2.4) |
| date | string | Yes | Date in YYYY-MM-DD format |
| limit | int | No | Results per page (max 50, default 25) |
| page | int | No | Page number for pagination |
| include_events | bool | No | Include event details |

### 2.4 Market IDs
```python
MLB_MARKETS = {
    # Pitcher Props (2)
    285: 'pitcher-strikeouts',
    290: 'pitcher-earned-runs-allowed',

    # Batter Props (9)
    287: 'batter-hits',
    288: 'batter-runs',
    289: 'batter-rbis',
    291: 'batter-doubles',
    292: 'batter-triples',
    293: 'batter-total-bases',
    294: 'batter-stolen-bases',
    295: 'batter-singles',
    299: 'batter-home-runs',
}

# Groupings for parallel processing
PITCHER_MARKETS = [285, 290]
BATTER_MARKETS = [287, 288, 289, 291, 292, 293, 294, 295, 299]
```

### 2.5 Response Structure
```json
{
  "_parameters": { ... },
  "_pagination": {
    "page": 1,
    "limit": 50,
    "total_pages": 4,
    "total_items": 180,
    "next": "/v3/props?...&page=2"
  },
  "label": "MLB strikeouts props for June 15th, 2024",
  "props": [
    {
      "sport": "MLB",
      "market_id": 285,
      "event_id": 93082,
      "participant": {
        "id": "46837",
        "name": "Spencer Arrighetti",
        "player": {
          "short_name": "S. Arrighetti",
          "first_name": "Spencer",
          "last_name": "Arrighetti",
          "slug": "spencer-arrighetti",
          "position": "SP",
          "team": "HOU",
          "jersey_number": 41
        }
      },
      "over": {
        "line": 5.5,
        "odds": -154,
        "book": 10,
        "consensus_line": 5.5,
        "consensus_odds": -154,
        "probability": 0.378,
        "expected_value": -0.185,
        "bet_rating": 1
      },
      "under": {
        "line": 6.5,
        "odds": -145,
        "book": 12,
        "consensus_line": 5.5,
        "consensus_odds": -145,
        "probability": 0.621,
        "expected_value": 0.049,
        "bet_rating": 3
      },
      "projection": {
        "recommended_side": "under",
        "value": 4.97,
        "probability": 0.621,
        "expected_value": 0.049,
        "bet_rating": 3,
        "diff": -1.53
      },
      "extra": {
        "lineup_set": true,
        "opposing_pitcher": "Flaherty",
        "in_lineup": true,
        "opposition_rank": { "rank": 23, "value": 0.2 }
      },
      "scoring": {
        "is_scored": true,
        "is_push": false,
        "push_reason": null,
        "actual": 2
      },
      "performance": {
        "last_1": { "over": 1, "under": 0, "push": 0 },
        "last_5": { "over": 3, "under": 2, "push": 0 },
        "last_10": { "over": 7, "under": 3, "push": 0 },
        "last_15": { "over": 10, "under": 5, "push": 0 },
        "last_20": { "over": 12, "under": 8, "push": 0 },
        "season": { "over": 16, "under": 12, "push": 0 },
        "prior_season": { "over": 0, "under": 0, "push": 0 },
        "h2h": { "over": 0, "under": 0, "push": 0 }
      }
    }
  ]
}
```

### 2.6 Rate Limiting
- No documented rate limits, but be respectful
- Recommended: 0.3-0.5 seconds between requests
- With 4 parallel workers: 0.5s delay each

---

## 3. File Structure

```
nba-stats-scraper/
├── scrapers/bettingpros/
│   ├── bp_mlb_player_props.py           # EXISTS - live day scraper
│   └── bp_mlb_props_historical.py       # NEW - historical scraper
│
├── scripts/mlb/historical_bettingpros_backfill/
│   ├── SPEC.md                          # This document
│   ├── backfill_all_props.py            # NEW - master orchestrator
│   ├── backfill_pitcher_props.py        # NEW - pitcher-only backfill
│   ├── backfill_batter_props.py         # NEW - batter-only backfill
│   └── check_progress.py                # NEW - progress monitoring
│
└── data_processors/raw/mlb/
    └── mlb_bp_props_processor.py        # NEW - GCS → BigQuery
```

---

## 4. Component Specifications

### 4.1 Core Scraper: `bp_mlb_props_historical.py`

#### Purpose
Fetch historical props for a single market and date, handling pagination automatically.

#### Class Design
```python
class BettingProsMLBHistoricalProps(ScraperBase, ScraperFlaskMixin):
    """
    BettingPros MLB Historical Props Scraper.

    Fetches historical player prop data with outcomes for any market/date.
    Handles pagination automatically to get all props for a day.
    """

    scraper_name = "bp_mlb_props_historical"

    required_params = ["market_id", "date"]
    optional_params = {
        "limit": 50,           # Max per page
        "include_events": True,
        "page": None,          # For manual pagination
    }
```

#### Key Methods
```python
def set_url(self) -> None:
    """Build API URL with market_id and date."""

def fetch_all_pages(self) -> List[Dict]:
    """Fetch all pages for a market/date, handling pagination."""

def transform_data(self) -> None:
    """Transform raw API response to standardized format."""

def should_save_data(self) -> bool:
    """Return True if we have props to save."""
```

#### Output Format (GCS JSON)
```json
{
  "meta": {
    "sport": "MLB",
    "market_id": 285,
    "market_name": "pitcher-strikeouts",
    "date": "2024-06-15",
    "total_props": 21,
    "total_pages": 1,
    "scraped_at": "2026-01-14T12:00:00Z"
  },
  "props": [
    {
      "event_id": 93082,
      "player_id": "46837",
      "player_name": "Spencer Arrighetti",
      "team": "HOU",
      "position": "SP",
      "over_line": 5.5,
      "over_odds": -154,
      "over_book_id": 10,
      "under_line": 5.5,
      "under_odds": -145,
      "under_book_id": 12,
      "consensus_line": 5.5,
      "projection_value": 4.97,
      "projection_side": "under",
      "projection_ev": 0.049,
      "bet_rating": 3,
      "actual_value": 2,
      "is_scored": true,
      "is_push": false,
      "perf_last_5_over": 3,
      "perf_last_5_under": 2,
      "perf_last_10_over": 7,
      "perf_last_10_under": 3,
      "perf_season_over": 16,
      "perf_season_under": 12,
      "opposing_pitcher": "Flaherty",
      "opposition_rank": 23
    }
  ]
}
```

#### GCS Path Structure
```
gs://nba-scraped-data/bettingpros-mlb/historical/
├── pitcher-strikeouts/
│   ├── 2022-04-07/props.json
│   ├── 2022-04-08/props.json
│   └── ...
├── pitcher-earned-runs-allowed/
│   └── ...
├── batter-hits/
│   └── ...
└── ... (other markets)
```

#### CLI Usage
```bash
# Single market/date
python scrapers/bettingpros/bp_mlb_props_historical.py \
    --market_id 285 --date 2024-06-15 --group dev

# With market name
python scrapers/bettingpros/bp_mlb_props_historical.py \
    --market_type pitcher-strikeouts --date 2024-06-15 --group gcs
```

---

### 4.2 Backfill Orchestrator: `backfill_all_props.py`

#### Purpose
Orchestrate the complete backfill of all markets across all seasons with:
- Parallel execution (configurable workers)
- Resume capability (skip existing GCS files)
- Progress tracking and logging
- Rate limiting

#### Class Design
```python
class MLBBettingProsBackfill:
    """
    Master orchestrator for BettingPros historical backfill.

    Supports:
    - All 11 markets or specific market selection
    - Date range filtering
    - Parallel execution with configurable workers
    - Resume from GCS (skip existing files)
    - Progress tracking and ETA
    """

    def __init__(
        self,
        markets: List[int] = None,      # None = all markets
        start_date: str = "2022-04-07",
        end_date: str = "2025-09-28",
        workers: int = 4,
        delay: float = 0.5,
        resume: bool = True,
        dry_run: bool = False,
    ):
        pass
```

#### Execution Strategy
```python
# Parallel strategy: Each worker handles different markets
# Worker 1: pitcher-strikeouts (285), batter-hits (287), batter-total-bases (293)
# Worker 2: pitcher-era (290), batter-runs (288), batter-stolen-bases (294)
# Worker 3: batter-rbis (289), batter-doubles (291), batter-singles (295)
# Worker 4: batter-triples (292), batter-home-runs (299)

# Each worker processes all dates for its assigned markets
# This distributes load evenly (mix of high/low volume markets per worker)
```

#### CLI Usage
```bash
# Full backfill (all markets, all seasons)
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py

# Pitcher props only
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py \
    --markets pitcher

# Specific date range
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py \
    --start-date 2024-06-01 --end-date 2024-06-30

# Dry run
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --dry-run

# Resume (default)
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --resume

# Force re-scrape
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --no-resume

# Single worker (for debugging)
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --workers 1
```

#### Progress Output
```
================================================================================
MLB BETTINGPROS HISTORICAL BACKFILL
================================================================================

Configuration:
  Markets: 11 (2 pitcher, 9 batter)
  Date range: 2022-04-07 to 2025-09-28
  Total days: 740
  Workers: 4
  Delay: 0.5s
  Resume: True

Scanning GCS for existing files...
  Found 1,234 existing files (will skip)

Starting backfill...

[Worker 1] pitcher-strikeouts 2022-04-07: 11 props
[Worker 2] pitcher-era 2022-04-07: 10 props
[Worker 3] batter-rbis 2022-04-07: 145 props
[Worker 4] batter-triples 2022-04-07: 160 props
...

Progress: 2,500/8,140 API calls (30.7%) | 125,000 props | ETA: 45 min

================================================================================
BACKFILL COMPLETE
================================================================================
Total time: 1h 23m
Markets processed: 11
Days processed: 740
Props collected: 1,142,567
API calls: 28,120
Files created: 8,140
```

---

### 4.3 Progress Monitor: `check_progress.py`

#### Purpose
Check backfill progress by scanning GCS for completed files.

#### Output
```
================================================================================
MLB BETTINGPROS BACKFILL PROGRESS
================================================================================

Market                      | Days Complete | Props    | Status
----------------------------|---------------|----------|--------
pitcher-strikeouts (285)    | 740/740      | 29,600   | DONE
pitcher-era (290)           | 740/740      | 28,400   | DONE
batter-hits (287)           | 523/740      | 94,140   | 70.7%
batter-runs (288)           | 523/740      | 94,140   | 70.7%
batter-rbis (289)           | 412/740      | 61,800   | 55.7%
...

Overall: 5,234/8,140 files (64.3%)
Estimated remaining time: 35 min (at current rate)
```

---

### 4.4 BigQuery Processor: `mlb_bp_props_processor.py`

#### Purpose
Load GCS JSON files into BigQuery tables for analysis.

#### Tables Created
```sql
-- Pitcher props table
CREATE TABLE `nba-props-platform.mlb_raw.bp_pitcher_props` (
  game_date DATE NOT NULL,
  event_id INT64,
  player_id STRING NOT NULL,
  player_name STRING,
  team STRING,
  position STRING,
  market_id INT64 NOT NULL,
  market_name STRING,

  -- Lines
  over_line FLOAT64,
  over_odds INT64,
  over_book_id INT64,
  under_line FLOAT64,
  under_odds INT64,
  under_book_id INT64,
  consensus_line FLOAT64,

  -- Projections
  projection_value FLOAT64,
  projection_side STRING,
  projection_ev FLOAT64,
  bet_rating INT64,

  -- Outcomes (KEY!)
  actual_value INT64,
  is_scored BOOL,
  is_push BOOL,

  -- Performance trends
  perf_last_5_over INT64,
  perf_last_5_under INT64,
  perf_last_10_over INT64,
  perf_last_10_under INT64,
  perf_season_over INT64,
  perf_season_under INT64,

  -- Context
  opposing_pitcher STRING,
  opposition_rank INT64,

  -- Metadata
  scraped_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY market_id, player_id;

-- Batter props table (same schema)
CREATE TABLE `nba-props-platform.mlb_raw.bp_batter_props` (
  -- Same columns as pitcher props
);
```

---

## 5. Season Date Ranges

```python
MLB_SEASONS = {
    2022: {
        'start': '2022-04-07',
        'end': '2022-10-05',
        'days': 183,
    },
    2023: {
        'start': '2023-03-30',
        'end': '2023-10-01',
        'days': 186,
    },
    2024: {
        'start': '2024-03-28',
        'end': '2024-09-29',
        'days': 186,
    },
    2025: {
        'start': '2025-03-27',
        'end': '2025-09-28',
        'days': 185,
    },
}

# Total: ~740 game days
```

---

## 6. Error Handling

### 6.1 API Errors
| Error | Handling |
|-------|----------|
| 429 (Rate Limited) | Exponential backoff (5s, 10s, 20s), max 3 retries |
| 404 (No Data) | Log warning, save empty file to mark complete |
| 500 (Server Error) | Retry 3 times, then skip and log |
| Timeout | Retry with increased timeout (30s, 60s, 120s) |

### 6.2 Data Validation
- Verify `total_items` matches props count
- Check `is_scored` = true for historical data
- Log warning if `actual_value` is null for scored props

### 6.3 Resume Logic
```python
def should_skip_file(market_id: int, date: str) -> bool:
    """Check if GCS file exists and is valid."""
    gcs_path = f"bettingpros-mlb/historical/{market_name}/{date}/props.json"

    # Check existence
    blob = bucket.blob(gcs_path)
    if not blob.exists():
        return False

    # Optionally verify content
    if verify_content:
        data = json.loads(blob.download_as_string())
        return data.get('meta', {}).get('total_props', 0) > 0

    return True
```

---

## 7. Testing Plan

### 7.1 Unit Tests
- Test URL construction with different market IDs
- Test pagination logic
- Test data transformation
- Test GCS path generation

### 7.2 Integration Tests
```bash
# Test single market/date
python scrapers/bettingpros/bp_mlb_props_historical.py \
    --market_id 285 --date 2024-06-15 --group dev

# Verify output
cat /tmp/bp_mlb_props_285_2024-06-15.json | python -m json.tool | head -50

# Test pagination (batter props have many pages)
python scrapers/bettingpros/bp_mlb_props_historical.py \
    --market_id 287 --date 2024-06-15 --group dev
```

### 7.3 Backfill Test
```bash
# Test 1 week of data
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py \
    --start-date 2024-06-15 --end-date 2024-06-21 \
    --workers 1 --dry-run
```

---

## 8. Implementation Order

1. **Phase 1**: Core Scraper (`bp_mlb_props_historical.py`)
   - API integration
   - Pagination handling
   - Data transformation
   - GCS export

2. **Phase 2**: Backfill Orchestrator (`backfill_all_props.py`)
   - Date range generation
   - Parallel execution
   - Resume capability
   - Progress tracking

3. **Phase 3**: Supporting Scripts
   - `check_progress.py` - Progress monitoring
   - `backfill_pitcher_props.py` - Pitcher-only convenience script
   - `backfill_batter_props.py` - Batter-only convenience script

4. **Phase 4**: BigQuery Processor (`mlb_bp_props_processor.py`)
   - GCS file discovery
   - Schema creation
   - Batch loading

5. **Phase 5**: Execute Backfill
   - Run full backfill (2022-2025)
   - Monitor progress
   - Verify data quality

---

## 9. Success Criteria

- [ ] All 11 markets backfilled for 2022-2025
- [ ] ~1,140,000 prop records collected
- [ ] All records have `actual_value` populated
- [ ] Data loaded to BigQuery tables
- [ ] Query verification: match counts with expected volumes
