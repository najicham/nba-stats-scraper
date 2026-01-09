# MLB Pitcher Strikeouts - Handoff Document

**Date**: 2026-01-06
**Session**: MLB Odds API Scrapers Implementation
**Status**: Scrapers Complete, Processors Pending

---

## Quick Start for New Chat

```bash
# Read the project documentation first:
cat docs/08-projects/current/mlb-pitcher-strikeouts/PROGRESS-LOG.md
cat docs/08-projects/current/mlb-pitcher-strikeouts/ODDS-DATA-STRATEGY.md

# Verify scrapers work:
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
from scrapers.mlb.oddsapi import (
    MlbEventsOddsScraper,
    MlbGameLinesScraper,
    MlbPitcherPropsScraper,
    MlbBatterPropsScraper
)
print('All MLB Odds scrapers import successfully!')
"
```

---

## Project Overview

### Goal
Build a **pitcher strikeout prediction model** for MLB that:
1. Predicts pitcher K over/under outcomes
2. Uses a **bottom-up model**: Sum of individual batter K probabilities ≈ Pitcher K total
3. Incorporates game context (moneyline, totals, spreads) for correlation analysis

### Key Insight
```
Pitcher K's ≈ Σ (individual batter K probabilities)

If batter K lines don't sum to pitcher K line → market inefficiency → edge
```

---

## What Was Completed This Session

### 1. MLB Pitcher Stats Processor (End-to-End Working)
- **File**: `data_processors/raw/mlb/mlb_pitcher_stats_processor.py`
- **Tested**: World Series Game 5 data successfully processed
- **Result**: 20 rows, 53 strikeouts, Gerrit Cole 6 K's

### 2. MLB Odds API Scrapers (4 New Files)

| Scraper | File | Markets |
|---------|------|---------|
| Events | `scrapers/mlb/oddsapi/mlb_events.py` | Get event IDs |
| Game Lines | `scrapers/mlb/oddsapi/mlb_game_lines.py` | h2h, spreads, totals |
| Pitcher Props | `scrapers/mlb/oddsapi/mlb_pitcher_props.py` | pitcher_strikeouts, pitcher_outs, etc. |
| Batter Props | `scrapers/mlb/oddsapi/mlb_batter_props.py` | batter_strikeouts, batter_hits, etc. |

### 3. BigQuery Tables Created

| Table | Purpose |
|-------|---------|
| `mlb_raw.oddsa_events` | Event ID mapping |
| `mlb_raw.oddsa_game_lines` | ML, spread, totals |
| `mlb_raw.oddsa_pitcher_props` | Pitcher K lines |
| `mlb_raw.oddsa_batter_props` | Batter K lines |

### 4. Views Created
- `oddsa_pitcher_k_lines` - Latest pitcher strikeout lines
- `oddsa_batter_k_lines` - Latest batter strikeout lines
- `oddsa_lineup_expected_ks` - Sum of batter K lines per team
- `oddsa_games_today` - Today's games with odds

### 5. GCS Paths Added
- `mlb_odds_api_events`
- `mlb_odds_api_game_lines`
- `mlb_odds_api_pitcher_props`
- `mlb_odds_api_batter_props`

---

## Files Created This Session

```
scrapers/mlb/oddsapi/
├── __init__.py                     ✅ NEW
├── mlb_events.py                   ✅ NEW
├── mlb_game_lines.py               ✅ NEW
├── mlb_pitcher_props.py            ✅ NEW
└── mlb_batter_props.py             ✅ NEW

data_processors/raw/mlb/
├── __init__.py                     ✅ NEW
└── mlb_pitcher_stats_processor.py  ✅ NEW

schemas/bigquery/mlb_raw/
└── oddsa_tables.sql                ✅ NEW

docs/08-projects/current/mlb-pitcher-strikeouts/
└── ODDS-DATA-STRATEGY.md           ✅ NEW

scrapers/utils/gcs_path_builder.py  ✅ UPDATED (added MLB paths)
```

---

## Testing Status

### Scrapers Tested
| Scraper | Result | Notes |
|---------|--------|-------|
| `mlb_events.py` | ✅ Works | Returns 0 in off-season (expected) |
| `mlb_game_lines.py` | ✅ Works | Returns 0 in off-season (expected) |
| `mlb_pitcher_props.py` | ✅ Works | Correctly rejects invalid event IDs |
| `mlb_batter_props.py` | ✅ Works | Correctly rejects invalid event IDs |

### API Verification
- ✅ Odds API Key working
- ✅ NBA props test confirmed endpoint structure works
- ✅ MLB endpoints ready (just no games in January)

### MLB Season Note
- MLB runs **April - October**
- January = off-season, no games available
- All scrapers handle empty responses gracefully

---

## What Still Needs To Be Done

### Priority 1: Create Odds Processors (4 files)

These processors take scraped data from GCS and load to BigQuery:

```
data_processors/raw/mlb/
├── mlb_events_processor.py         ❌ NEEDED
├── mlb_game_lines_processor.py     ❌ NEEDED
├── mlb_pitcher_props_processor.py  ❌ NEEDED
└── mlb_batter_props_processor.py   ❌ NEEDED
```

**Pattern to follow**: Copy from `mlb_pitcher_stats_processor.py` or NBA equivalents

### Priority 2: Create BDL Batter Stats (scraper + processor)

For historical batter K rates:
```
scrapers/mlb/balldontlie/
└── mlb_batter_stats.py             ❌ NEEDED

data_processors/raw/mlb/
└── mlb_batter_stats_processor.py   ❌ NEEDED

schemas/bigquery/mlb_raw/
└── bdl_batter_stats_tables.sql     ❌ NEEDED
```

### Priority 3: Create Analytics Processors

```
data_processors/analytics/mlb/
├── pitcher_game_summary_processor.py    ❌ NEEDED
└── batter_game_summary_processor.py     ❌ NEEDED
```

### Priority 4: Create ML Feature Store

```
data_processors/precompute/mlb/
└── pitcher_strikeout_features_processor.py  ❌ NEEDED
```

### Priority 5: Model Training

```
ml/
└── train_pitcher_strikeouts_xgboost.py  ❌ NEEDED
```

---

## Comprehensive Todo List

### Phase 1: Complete Raw Layer (Next Session)

```
[ ] 1. Create mlb_events_processor.py
    - Load events from GCS to mlb_raw.oddsa_events
    - Extract event_id, game_date, teams, commence_time

[ ] 2. Create mlb_game_lines_processor.py
    - Load game lines from GCS to mlb_raw.oddsa_game_lines
    - Parse h2h, spreads, totals for each bookmaker
    - Calculate implied probabilities

[ ] 3. Create mlb_pitcher_props_processor.py
    - Load pitcher props from GCS to mlb_raw.oddsa_pitcher_props
    - Extract strikeout lines (point, over_price, under_price)
    - Calculate implied probabilities
    - Normalize player names for joins

[ ] 4. Create mlb_batter_props_processor.py
    - Load batter props from GCS to mlb_raw.oddsa_batter_props
    - Extract strikeout lines for each batter
    - Calculate expected K's per batter
    - Normalize player names for joins
```

### Phase 2: Complete BDL Layer

```
[ ] 5. Create mlb_batter_stats.py scraper
    - Fetch batter game stats from BDL API
    - Include: at_bats, hits, k (strikeouts), walks

[ ] 6. Create bdl_batter_stats_tables.sql schema
    - Partition by game_date
    - Cluster by player_lookup, team_abbr

[ ] 7. Create mlb_batter_stats_processor.py
    - Load batter stats from GCS to mlb_raw.bdl_batter_stats
```

### Phase 3: Analytics Layer

```
[ ] 8. Create pitcher_game_summary_processor.py
    - Rolling K averages (last 5, 10, season)
    - K/9 rate, K% trends
    - Home/away splits

[ ] 9. Create batter_game_summary_processor.py
    - Rolling K rates per batter
    - Contact rate, walk rate
    - Splits by pitcher handedness
```

### Phase 4: Feature Store

```
[ ] 10. Create pitcher_strikeout_features_processor.py
     - 25-feature vector per pitcher per game
     - Include opponent lineup K rates
     - Include game context (totals, spread)
```

### Phase 5: Model Training

```
[ ] 11. Create train_pitcher_strikeouts_xgboost.py
     - Follow NBA pattern from train_real_xgboost.py
     - Train on 2+ seasons of historical data
     - Target MAE < 1.5 strikeouts
```

### Phase 6: Prediction Pipeline

```
[ ] 12. Create prediction coordinator for MLB
[ ] 13. Create prediction worker for MLB
[ ] 14. Create grading processor for MLB
```

---

## Key Documentation Files

```
docs/08-projects/current/mlb-pitcher-strikeouts/
├── PROJECT-PLAN.md           # Full implementation plan
├── PROGRESS-LOG.md           # Session-by-session progress
├── DATA-SOURCES.md           # Data source analysis
├── ODDS-DATA-STRATEGY.md     # Odds collection strategy (NEW)
├── QUICK-REFERENCE.md        # Quick reference card
└── BDL-MLB-API-ANALYSIS.md   # BDL API field analysis
```

---

## Test Commands

### Verify Scrapers
```bash
# Test events (off-season = 0 events, but code runs)
SPORT=mlb PYTHONPATH=. .venv/bin/python scrapers/mlb/oddsapi/mlb_events.py \
    --game_date 2026-01-07 --group dev

# Test game lines
SPORT=mlb PYTHONPATH=. .venv/bin/python scrapers/mlb/oddsapi/mlb_game_lines.py \
    --game_date 2026-01-07 --group dev
```

### Verify BigQuery Tables
```bash
bq ls --project_id=nba-props-platform mlb_raw | grep oddsa
```

### Verify Pitcher Stats Work
```bash
bq query --use_legacy_sql=false "
SELECT game_date, player_full_name, strikeouts, innings_pitched
FROM mlb_raw.bdl_pitcher_stats
WHERE game_date >= '2024-10-01'
ORDER BY strikeouts DESC
LIMIT 5
"
```

---

## Architecture Diagram

```
                    SCRAPERS                          PROCESSORS                    BIGQUERY
                    ========                          ==========                    ========

BDL API ──────► mlb_pitcher_stats.py ──► GCS ──► mlb_pitcher_stats_processor ──► bdl_pitcher_stats ✅
            └─► mlb_batter_stats.py ───► GCS ──► mlb_batter_stats_processor ───► bdl_batter_stats ❌

Odds API ──► mlb_events.py ─────────► GCS ──► mlb_events_processor ────────────► oddsa_events ❌
         ├─► mlb_game_lines.py ─────► GCS ──► mlb_game_lines_processor ────────► oddsa_game_lines ❌
         ├─► mlb_pitcher_props.py ──► GCS ──► mlb_pitcher_props_processor ─────► oddsa_pitcher_props ❌
         └─► mlb_batter_props.py ───► GCS ──► mlb_batter_props_processor ──────► oddsa_batter_props ❌

✅ = Complete    ❌ = Needs Implementation
```

---

## Environment Setup

```bash
# Required environment variables
export SPORT=mlb
export ODDS_API_KEY=<your_key>  # Or in .env file
export PYTHONPATH=/home/naji/code/nba-stats-scraper

# GCS bucket
gs://mlb-scraped-data  # Already created

# BigQuery datasets
mlb_raw        # Already exists with tables
mlb_analytics  # Exists (empty)
mlb_precompute # Exists (empty)
mlb_predictions # Exists (empty)
```

---

## Session Summary

**This session accomplished**:
1. ✅ Created 4 MLB Odds API scrapers (events, game_lines, pitcher_props, batter_props)
2. ✅ Created BigQuery schemas for odds tables (4 tables + 4 views)
3. ✅ Updated GCS path builder with MLB odds paths
4. ✅ Tested all scrapers (work correctly, just no MLB games in off-season)
5. ✅ Created comprehensive odds data strategy documentation

**Next session should focus on**:
1. Creating the 4 odds processors
2. Testing end-to-end with NBA data to verify processor pattern
3. Creating batter stats scraper/processor

---

## Copy-Paste Prompt for New Chat

```
Continue the MLB pitcher strikeouts project.

Read the handoff: docs/09-handoff/2026-01-06-MLB-ODDS-SCRAPERS-COMPLETE.md

Summary:
- 4 MLB Odds API scrapers DONE (events, game_lines, pitcher_props, batter_props)
- BigQuery tables DONE (oddsa_events, oddsa_game_lines, oddsa_pitcher_props, oddsa_batter_props)
- Scrapers tested and working (MLB is off-season so returns 0 events, but code works)

Next priority:
1. Create odds processors (4 files in data_processors/raw/mlb/)
2. Follow pattern from mlb_pitcher_stats_processor.py
3. Test with NBA data first (NBA is active) to verify processor pattern works

Key files:
- Project docs: docs/08-projects/current/mlb-pitcher-strikeouts/
- Odds strategy: docs/08-projects/current/mlb-pitcher-strikeouts/ODDS-DATA-STRATEGY.md
- Reference processor: data_processors/raw/mlb/mlb_pitcher_stats_processor.py
```
