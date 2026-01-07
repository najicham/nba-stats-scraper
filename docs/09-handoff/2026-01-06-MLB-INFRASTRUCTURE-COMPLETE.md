# MLB Pitcher Strikeouts - Infrastructure Complete

**Date**: 2026-01-06
**Status**: Infrastructure verified and tables created

---

## Session Summary

This session focused on verifying and completing the MLB infrastructure:

1. **Verified all 28 scrapers** work correctly
2. **Created 5 missing BigQuery tables**:
   - `mlb_raw.bdl_batter_stats`
   - `mlb_raw.mlb_schedule`
   - `mlb_raw.mlb_game_lineups`
   - `mlb_raw.mlb_lineup_batters`
   - `mlb_analytics.batter_game_summary`
3. **Verified all processors** (8 raw + 2 analytics)
4. **Updated documentation**

---

## Current Infrastructure Status

### Complete (Ready to Use)

| Component | Count | Details |
|-----------|-------|---------|
| Scrapers | 28 | BDL(13), MLB API(3), Odds(8), Statcast(1), External(3) |
| Raw Tables | 14 | All created, partitioned, clustered |
| Analytics Tables | 2 | pitcher_game_summary, batter_game_summary |
| Raw Processors | 8 | All tested and working |
| Analytics Processors | 2 | All tested and working |
| Precompute Tables | 1 | pitcher_ml_features |

### Partial/Pending

| Component | Status | Notes |
|-----------|--------|-------|
| Feature Processor | 12/25 features | 13 TODOs remain |
| Training Script | Not started | Need data first |
| Prediction Workers | Not started | Need model first |

### Data Status

**All tables are EMPTY** - This is the critical blocker.

```
mlb_raw.bdl_pitcher_stats: 15 rows (test data only)
mlb_raw.bdl_batter_stats: 0 rows
mlb_analytics.pitcher_game_summary: 0 rows
mlb_precompute.pitcher_ml_features: 0 rows
```

---

## What the Next Session Should Do

### Option A: Create More Schemas (Low Risk)

Create BigQuery schemas for the 11 new scrapers added in previous session:

```bash
# Scrapers needing schemas:
- mlb_standings
- mlb_box_scores
- mlb_live_box_scores
- mlb_team_season_stats
- mlb_player_versus
- mlb_teams
- mlb_game_feed
- mlb_statcast_pitcher
- mlb_umpire_stats
- mlb_ballpark_factors
- mlb_weather
```

### Option B: Run Sample Backfill (Medium Risk)

Test the pipeline end-to-end with a few days of historical data:

```bash
# Example backfill commands
SPORT=mlb PYTHONPATH=. .venv/bin/python \
  scrapers/mlb/balldontlie/mlb_pitcher_stats.py --date 2024-06-15

SPORT=mlb PYTHONPATH=. .venv/bin/python \
  scrapers/mlb/balldontlie/mlb_batter_stats.py --date 2024-06-15
```

### Option C: Complete Feature Processor (Medium Risk)

Wire up the 13 TODO features in `pitcher_features_processor.py`:

- f11: home_away_k_diff (from splits)
- f13: day_night_k_diff (from splits)
- f14: vs_opponent_k_rate (from history)
- f16: opponent_obp (from batter stats)
- f17: ballpark_k_factor (from static data)
- f18: game_total_line (from game lines)
- f19: team_implied_runs (from odds)
- f22: pitch_count_avg (from stats)
- f23: season_ip_total (from stats)

---

## Quick Reference

### Verify Infrastructure

```bash
# Scrapers
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
import scrapers.mlb as m; print(f'{len(m.__all__)} scrapers')
"

# Raw processors
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
import data_processors.raw.mlb as m
import inspect
print(len([n for n,o in inspect.getmembers(m) if 'Processor' in n]))
"

# Tables
bq ls nba-props-platform:mlb_raw | grep TABLE | wc -l
bq ls nba-props-platform:mlb_analytics | grep TABLE | wc -l
```

### Key Files

```
docs/08-projects/current/mlb-pitcher-strikeouts/
├── CURRENT-STATUS.md      <- Comprehensive status
├── PROGRESS-LOG.md        <- Session history
├── SCRAPERS-INVENTORY.md  <- All 28 scrapers documented
└── PROJECT-PLAN.md        <- Full implementation plan

schemas/bigquery/
├── mlb_raw/               <- 10 schema files
├── mlb_analytics/         <- 2 schema files
└── mlb_precompute/        <- 1 schema file
```

---

## Copy-Paste for Next Session

```
Continue the MLB pitcher strikeouts project.

Read: docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md

COMPLETED THIS SESSION:
- Verified all 28 scrapers work
- Created 5 missing BigQuery tables
- Verified 8 raw + 2 analytics processors
- Updated all documentation

INFRASTRUCTURE STATUS:
- Scrapers: 28/28 complete
- Raw Tables: 14/14 complete
- Analytics Tables: 2/2 complete
- Processors: 10/10 complete
- Feature Processor: 12/25 features (partial)

BLOCKER: Tables are empty - need historical data

SUGGESTED NEXT STEPS:
1. Create schemas for 11 new scrapers (standings, box_scores, etc.)
2. OR run sample historical backfill to test pipeline
3. OR complete feature processor gaps (13 TODOs)
```
