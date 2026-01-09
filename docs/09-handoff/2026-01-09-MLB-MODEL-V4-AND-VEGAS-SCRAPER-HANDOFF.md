# MLB Model V4 Complete - Vegas Scraper Next

**Date:** 2026-01-09
**Session Focus:** MLB model improvements, Vegas scraper setup pending
**Status:** Model v4 deployed, Vegas scraper needs implementation

---

## Executive Summary

This session improved the MLB pitcher strikeouts model:

1. ✅ Fixed prediction script to use opponent-specific lineup features (not averaged)
2. ✅ Retrained model v2 with corrected features (MAE 1.538 → 1.469)
3. ✅ Ran hyperparameter tuning (confirmed v2 params near-optimal)
4. ✅ Added pitcher-vs-opponent history features (v4)
5. ✅ Final model v4 deployed (MAE 1.459, 24% better than baseline)
6. ⏳ **MLB Vegas scraper needs implementation** (scraper exists, processor doesn't)

---

## IMMEDIATE NEXT TASK: MLB Vegas Scraper

The scraper exists but data isn't being collected. Need to:

### 1. Create Raw Processor for Pitcher Props

**File to create:** `data_processors/raw/mlb/oddsa_pitcher_props_processor.py`

**Reference:**
- NBA equivalent: `data_processors/raw/oddsa_player_props_processor.py`
- Scraper output: `scrapers/mlb/oddsapi/mlb_pitcher_props.py`

**Target table:** `mlb_raw.oddsa_pitcher_k_lines`

**Key fields to extract:**
```sql
- game_date
- event_id
- pitcher_name
- pitcher_lookup (normalize name)
- team_abbr
- strikeouts_line (the over/under number)
- over_odds
- under_odds
- bookmaker
- processed_at
```

### 2. Set Up Orchestration

**File to create:** Cloud Function or orchestrator entry

**Pattern:** Similar to NBA odds collection
- Run daily ~2 hours before first game
- Fetch events list first (`mlb_events.py`)
- Then fetch pitcher props for each event

### 3. Deploy

- Deploy scraper as Cloud Run service or Cloud Function
- Add scheduler job for daily execution

---

## What Was Done This Session

### Model Evolution

| Version | Features | Test MAE | Historical MAE | Notes |
|---------|----------|----------|----------------|-------|
| v1 | 19 | - | 1.54 | Had UNK bug |
| v2 | 19 | 1.65 | 1.469 | Fixed opponent-specific |
| v4 | 21 | 1.66 | **1.459** | + pitcher vs opponent |

### Key Bug Fix: Opponent-Specific Features

**Problem:** The `team_abbr` field was "UNK" in the analytics table, causing bottom-up features to average BOTH teams' lineups instead of just the opponent's.

**Solution:**
- Pull `team_abbr` from raw `mlb_pitcher_stats` table (which was fixed)
- Filter lineup batters to only the opponent's team
- Added deduplication for raw data duplicates

**Files changed:**
- `scripts/mlb/train_pitcher_strikeouts.py` - Training query with opponent-specific CTEs
- `scripts/mlb/generate_historical_predictions.py` - Prediction query updated

### New Features Added (v4)

```python
# Pitcher vs opponent history
'f27_avg_k_vs_opponent',  # Ranked 8th importance (4.4%)
'f28_games_vs_opponent',  # Sample size
```

**CTE for calculating:**
```sql
pitcher_vs_opponent AS (
    SELECT
        pr1.player_lookup,
        pr1.game_date,
        pr1.opponent_team,
        AVG(pgs2.strikeouts) as avg_k_vs_opponent,
        COUNT(pgs2.strikeouts) as games_vs_opponent
    FROM pitcher_raw pr1
    LEFT JOIN pitcher_game_summary pgs2
        ON pr1.player_lookup = pgs2.player_lookup
        AND pgs2.game_date < pr1.game_date  -- Historical only
        AND pgs2.game_date >= DATE_SUB(pr1.game_date, INTERVAL 3 YEAR)
    LEFT JOIN pitcher_raw pr2
        ON pgs2.player_lookup = pr2.player_lookup
        AND pgs2.game_date = pr2.game_date
    WHERE pr2.opponent_team = pr1.opponent_team
    GROUP BY pr1.player_lookup, pr1.game_date, pr1.opponent_team
)
```

---

## Files to Know

| Purpose | Path |
|---------|------|
| **Training script** | `scripts/mlb/train_pitcher_strikeouts.py` |
| **Prediction script** | `scripts/mlb/generate_historical_predictions.py` |
| **Tuning scripts** | `scripts/mlb/tune_pitcher_strikeouts*.py` |
| **Current model** | `models/mlb/mlb_pitcher_strikeouts_v4_20260108.json` |
| **GCS model** | `gs://nba-scraped-data/models/mlb/mlb_pitcher_strikeouts_v4_20260108.json` |
| **Vegas scraper** | `scrapers/mlb/oddsapi/mlb_pitcher_props.py` |
| **NBA odds processor (reference)** | `data_processors/raw/oddsa_player_props_processor.py` |

---

## Model Comparison: NBA vs MLB

| Metric | NBA | MLB |
|--------|-----|-----|
| MAE | 3.40 | 1.46 |
| Target avg | ~20 pts | ~5 K |
| Relative error | **17%** | 29% |
| vs Baseline | **29% better** | 24% better |

NBA model is relatively stronger. MLB has room for improvement with Vegas lines.

---

## Current Data State

### BigQuery Tables

| Dataset | Table | Rows | Status |
|---------|-------|------|--------|
| `mlb_raw` | mlb_pitcher_stats | 42,125 | ✅ Fixed team_abbr |
| `mlb_raw` | mlb_game_lineups | 10,319 | ✅ Fixed |
| `mlb_raw` | mlb_lineup_batters | 185,418 | ✅ Fixed |
| `mlb_raw` | oddsa_pitcher_k_lines | **0** | ⚠️ Empty - needs processor |
| `mlb_analytics` | pitcher_game_summary | 9,793 | ⚠️ Still has UNK (not regenerated) |
| `mlb_predictions` | pitcher_strikeouts | 8,130 | ✅ Using v4 model |

---

## Vegas Lines: Expected Impact

Based on NBA experience where Vegas lines were a top feature:

**Expected new features:**
```python
'f30_vegas_strikeouts_line',  # Market consensus (PRIMARY)
'f31_vegas_opening_line',     # Where line opened
'f32_vegas_line_move',        # Movement = closing - opening
'f33_has_vegas_line',         # Coverage indicator
```

**Expected improvement:** 0.05-0.10 MAE reduction (from 1.46 to ~1.38)

---

## Quick Commands

```bash
# Train model
PYTHONPATH=. python scripts/mlb/train_pitcher_strikeouts.py

# Generate predictions
PYTHONPATH=. python scripts/mlb/generate_historical_predictions.py

# Test scraper locally
SPORT=mlb python scrapers/mlb/oddsapi/mlb_pitcher_props.py \
    --event_id <event_id> --game_date 2025-06-15 --group dev

# Check BigQuery data
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM mlb_raw.oddsa_pitcher_k_lines"
```

---

## Commits This Session

```
46a7fc9 feat(mlb): Add pitcher-vs-opponent history features to model v4
afb338d chore(mlb): Add hyperparameter tuning scripts for pitcher strikeouts model
cf24e0e feat(mlb): Train v2 model with opponent-specific lineup features
```

---

## Before MLB Season (March 2026)

1. ✅ Model v4 deployed with pitcher-vs-opponent features
2. ⏳ **Implement Vegas scraper processor** (NEXT)
3. ⏳ Deploy orchestrators
4. ⏳ Enable scheduler jobs
5. ⏳ Test with Spring Training games

---

## Context for Next Session

The MLB pitcher strikeouts model predicts how many strikeouts a starting pitcher will get. The "bottom-up" innovation sums individual batter K probabilities rather than just using pitcher averages.

Current model is solid at MAE 1.46 (24% better than baseline). Vegas lines would add significant signal - in NBA, the Vegas line is often the single most important feature.

The scraper infrastructure exists (`mlb_pitcher_props.py`), but no processor extracts the data into BigQuery. Reference the NBA implementation for patterns.
