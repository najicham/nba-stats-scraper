# MLB Historical Backfill

This directory contains documentation for the MLB pitcher strikeouts historical betting lines backfill process.

## Purpose

Backfill historical betting lines from The Odds API to calculate the **true hit rate** of our MLB pitcher strikeout prediction model against actual betting lines (not synthetic/estimated lines).

## 5-Phase Architecture

| Phase | Script | Description | Time |
|-------|--------|-------------|------|
| 1 | `backfill_historical_betting_lines.py` | Scrape historical odds → GCS | ~2 hours (parallel) |
| 2 | `batch_load_to_bigquery.py` | Load GCS → BigQuery | ~5 min |
| 3 | `match_lines_to_predictions.py` | Match lines to predictions | ~2 min |
| 4 | `grade_historical_predictions.py` | Grade predictions (win/loss) | ~3 min |
| 5 | `calculate_hit_rate.py` | Calculate final hit rate | ~1 min |

## Quick Start

### Check Progress
```bash
python scripts/mlb/historical_odds_backfill/check_backfill_progress.py
```

### Run All Phases (after Phase 1 completes)
```bash
python scripts/mlb/historical_odds_backfill/run_phases_2_to_5.py
```

## Scripts Reference

All scripts located in: `scripts/mlb/historical_odds_backfill/`

| Script | Purpose |
|--------|---------|
| `backfill_historical_betting_lines.py` | Sequential scraper (original) |
| `backfill_parallel.py` | Parallel scraper (faster) |
| `batch_load_to_bigquery.py` | Batch loader - 40x faster than individual loads |
| `match_lines_to_predictions.py` | Match betting lines to predictions |
| `grade_historical_predictions.py` | Determine win/loss for each prediction |
| `calculate_hit_rate.py` | Calculate overall hit rate |
| `check_backfill_progress.py` | Dashboard showing all phase progress |
| `run_phases_2_to_5.py` | Run phases 2-5 in sequence |

## Data Flow

```
The Odds API (Historical)
         ↓
    GCS (JSON files)
    gs://nba-scraped-data/mlb-odds-api/pitcher-props-history/{date}/{event}/
         ↓
    BigQuery (mlb_raw.oddsa_pitcher_props)
         ↓
    Match to Predictions (mlb_predictions.pitcher_strikeouts)
         ↓
    Grade Predictions (is_correct field)
         ↓
    Calculate Hit Rate
```

## Key Tables

| Table | Purpose |
|-------|---------|
| `mlb_raw.oddsa_pitcher_props` | Raw betting lines from Odds API |
| `mlb_predictions.pitcher_strikeouts` | Model predictions with matched lines |

## Performance Optimizations

### Parallel Scraping (Session 39)
- Original sequential: ~8 dates/hour
- Parallel (9 workers): ~100+ dates/hour
- **12x speedup**

### Batch Loading (Session 39)
- Original per-file loading: ~0.8 dates/min
- Batch NDJSON loading: ~33 dates/min
- **40x speedup**

## Success Criteria

| Hit Rate | Interpretation |
|----------|----------------|
| >70% | EXCEPTIONAL - Deploy immediately |
| 60-70% | STRONG - Deploy with monitoring |
| 54-60% | MARGINAL - Tune model first |
| <54% | NOT PROFITABLE - Rework model |
| 52.4% | Breakeven threshold |

## Related Documentation

- [BACKFILL-STRATEGY-2026-01-07.md](../BACKFILL-STRATEGY-2026-01-07.md) - Original strategy
- [HIT-RATE-MEASUREMENT-SOLUTION-2026-01-13.md](../HIT-RATE-MEASUREMENT-SOLUTION-2026-01-13.md) - Measurement approach
- [EXECUTION-PLAN-PHASES-2-5.md](../EXECUTION-PLAN-PHASES-2-5.md) - Phase execution details
