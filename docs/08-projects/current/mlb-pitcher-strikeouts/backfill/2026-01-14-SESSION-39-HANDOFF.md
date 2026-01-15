# Session 39 Handoff: MLB Historical Backfill & BettingPros Scraper
**Date:** 2026-01-14
**Status:** ACTIVE - Backfill processes running

## Quick Status Summary

| Component | Status | Progress |
|-----------|--------|----------|
| Pitcher Props (GCS) | 97% | 342/352 dates |
| Batter Props (GCS) | ~15% | 51/352 dates |
| BigQuery Loading | 71% | 251/352 dates |
| Prediction Coverage | 62.6% | 5,092/8,130 matchable |

## Active Background Processes

### 1. Pitcher Props Scrapers (4 workers finishing)
```bash
# Check status
for log in $(ls -t logs/worker*_*.log | head -4); do tail -3 "$log"; done
```

### 2. Batter Props Scrapers (4 workers running)
```bash
# Started at ~10:08 today
for log in $(ls -t logs/batter_worker*_*.log | head -4); do tail -3 "$log"; done
```

### 3. BigQuery Batch Loader (may need restart)
```bash
# Check if running
ps aux | grep batch_load | grep -v grep

# If not running, restart:
python scripts/mlb/historical_odds_backfill/batch_load_to_bigquery.py
```

## Key Files Created This Session

### Scripts
| Script | Purpose |
|--------|---------|
| `scripts/mlb/historical_odds_backfill/backfill_parallel.py` | Parallel pitcher props (not used - split workers work better) |
| `scripts/mlb/historical_odds_backfill/batch_load_to_bigquery.py` | 40x faster BQ loading with batch NDJSON |
| `scripts/mlb/historical_odds_backfill/backfill_batter_props.py` | Batter props backfill from Odds API |
| `scripts/mlb/historical_odds_backfill/check_backfill_progress.py` | Progress dashboard |
| `scripts/mlb/historical_odds_backfill/run_phases_2_to_5.py` | Runs all phases after scraping done |

### Scrapers
| Scraper | Purpose | Status |
|---------|---------|--------|
| `scrapers/bettingpros/bp_mlb_player_props.py` | BettingPros MLB props | PARTIAL - needs market IDs |

## What Was Done This Session

### 1. Parallelized Phase 1 Scraping
- Split date ranges across multiple workers (up to 9 at peak)
- Speed: 8x-12x faster than sequential
- Pitcher props: 97% complete

### 2. Created Batch BigQuery Loader
- Old: 0.8 dates/min (each file individually)
- New: 33.4 dates/min (batch NDJSON)
- Improvement: **40x faster**

### 3. Added Batter Props Backfill
- Created `backfill_batter_props.py`
- 4 parallel workers running
- Scrapes: batter_hits, batter_home_runs, batter_rbis, batter_total_bases, batter_runs_scored, batter_stolen_bases, **batter_strikeouts**

### 4. Started MLB BettingPros Scraper
- Created `bp_mlb_player_props.py` (inherits from NBA scraper)
- **INCOMPLETE**: Needs MLB market IDs discovered
- User noted BettingPros showing CORS errors (possibly off-season)

## TODO for Next Session

### Priority 1: Complete Backfill
```bash
# Check pitcher props completion
python scripts/mlb/historical_odds_backfill/check_backfill_progress.py

# When pitcher props at 100%, run phases 2-5:
python scripts/mlb/historical_odds_backfill/run_phases_2_to_5.py
```

### Priority 2: Sync BigQuery with GCS
```bash
# Load any new data
python scripts/mlb/historical_odds_backfill/batch_load_to_bigquery.py
```

### Priority 3: Complete BettingPros MLB Scraper
The scraper skeleton exists at `scrapers/bettingpros/bp_mlb_player_props.py` but:
1. **Market IDs are placeholder** - Need to discover real MLB market IDs
2. **No MLB events fetcher** - Need to create `bp_mlb_events.py`
3. **CORS issue** - User reported BettingPros showing CORS errors (off-season?)

To discover market IDs:
```bash
# When MLB season active, inspect API:
curl "https://api.bettingpros.com/v3/offers?sport=MLB" | jq '.markets'
```

### Priority 4: Add Batter Props to BigQuery
```bash
# Create processor for batter props data
# Similar to mlb_pitcher_props_processor.py
```

## Commands Reference

### Check All Progress
```bash
python scripts/mlb/historical_odds_backfill/check_backfill_progress.py
```

### Check Active Workers
```bash
ps aux | grep -E "backfill" | grep python | grep -v grep
```

### View Worker Logs
```bash
# Pitcher workers
for log in $(ls -t logs/worker*_*.log | head -4); do echo "=== $log ==="; tail -5 "$log"; done

# Batter workers
for log in $(ls -t logs/batter_worker*_*.log | head -4); do echo "=== $log ==="; tail -5 "$log"; done
```

### Run Full Pipeline After Scraping Done
```bash
python scripts/mlb/historical_odds_backfill/run_phases_2_to_5.py
```

### Manual Phase Execution
```bash
# Phase 2: GCS → BigQuery
python scripts/mlb/historical_odds_backfill/batch_load_to_bigquery.py

# Phase 3: Match lines to predictions
python scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py

# Phase 4: Grade predictions
python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py

# Phase 5: Calculate hit rate
python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py
```

## GCS Bucket Structure

```
gs://nba-scraped-data/mlb-odds-api/
├── pitcher-props-history/     # Pitcher props (strikeouts, outs, etc.)
│   ├── 2024-04-09/
│   │   └── {event_id}-{teams}/
│   │       └── *.json
│   └── ...
└── batter-props-history/      # Batter props (hits, HRs, RBIs, etc.)
    ├── 2024-04-09/
    │   └── {event_id}-{teams}/
    │       └── *.json
    └── ...
```

## BigQuery Tables

| Table | Purpose |
|-------|---------|
| `mlb_raw.oddsa_pitcher_props` | Pitcher prop betting lines |
| `mlb_raw.oddsa_batter_props` | Batter prop betting lines (needs processor) |
| `mlb_predictions.pitcher_strikeouts` | Model predictions |
| `mlb_predictions.pitcher_strikeouts_graded` | Predictions with outcomes |

## Speed Optimizations Made

| Component | Before | After | Improvement |
|-----------|--------|-------|-------------|
| Phase 1 (scraping) | ~8 dates/hr | ~96 dates/hr | 12x |
| Phase 2 (BQ load) | 0.8 dates/min | 33.4 dates/min | 40x |
| Overall backfill | ~40 hours | ~4 hours | 10x |

## Architecture Diagram

```
                    PHASE 1 (Scraping)
                    ┌─────────────────┐
                    │  Worker 1-4     │
Odds API ──────────►│  (Pitcher)      │────► GCS pitcher-props-history/
                    └─────────────────┘
                    ┌─────────────────┐
                    │  Worker B1-B4   │
Odds API ──────────►│  (Batter)       │────► GCS batter-props-history/
                    └─────────────────┘

                    PHASE 2 (Loading)
                    ┌─────────────────┐
GCS ───────────────►│  batch_load_to  │────► BigQuery mlb_raw.oddsa_*
                    │  _bigquery.py   │
                    └─────────────────┘

                    PHASES 3-5 (Analysis)
                    ┌─────────────────┐
BigQuery ──────────►│  run_phases_    │────► Hit Rate Result
                    │  2_to_5.py      │
                    └─────────────────┘
```

## Expected Final Results

Once complete:
- **8,130 predictions** with betting lines matched
- **Real hit rate** (expected 60-70%, synthetic was 78%)
- **Profitability analysis** (breakeven is 52.4%)

## Questions for User

1. When MLB season starts, test BettingPros API with proxy?
2. Should batter props have their own BigQuery processor?
3. Want automatic scheduling for incremental updates?
