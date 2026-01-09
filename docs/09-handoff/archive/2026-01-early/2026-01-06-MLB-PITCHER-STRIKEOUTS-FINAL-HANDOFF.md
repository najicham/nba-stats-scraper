# MLB Pitcher Strikeouts - Complete Implementation Handoff

**Date**: 2026-01-06
**Status**: Layers 1-4 COMPLETE, Layer 5 (Model Training) remaining
**Project Goal**: Predict pitcher strikeout over/under using bottom-up batter K rates

---

## Executive Summary

We've built a complete MLB data pipeline for pitcher strikeout predictions. The unique approach is a **bottom-up model** that sums individual batter K probabilities to predict pitcher totals.

```
KEY INSIGHT:
Pitcher Ks ≈ Σ(batter_k_rate × expected_ABs)

If batter K lines don't sum to pitcher K line → market inefficiency → betting edge
```

---

## Architecture Overview (5 Layers)

```
LAYER 1: SCRAPERS ────────────────► LAYER 2: RAW PROCESSORS ──────► mlb_raw.*
===================                 ========================        ==========

MLB Stats API (WHO is playing - CRITICAL):
  mlb_schedule.py ─────────────────► mlb_schedule_processor ────────► mlb_schedule ✅
                                     (probable pitchers!)
  mlb_lineups.py ──────────────────► mlb_lineups_processor ─────────► mlb_game_lineups ✅
                                                                      mlb_lineup_batters ✅
                                     (9 batters for bottom-up)

Ball Don't Lie API (Historical stats):
  mlb_pitcher_stats.py ────────────► mlb_pitcher_stats_processor ───► bdl_pitcher_stats ✅
  mlb_batter_stats.py ─────────────► mlb_batter_stats_processor ────► bdl_batter_stats ✅

Odds API (Betting lines):
  mlb_events.py ───────────────────► mlb_events_processor ──────────► oddsa_events ✅
  mlb_game_lines.py ───────────────► mlb_game_lines_processor ──────► oddsa_game_lines ✅
  mlb_pitcher_props.py ────────────► mlb_pitcher_props_processor ───► oddsa_pitcher_props ✅
  mlb_batter_props.py ─────────────► mlb_batter_props_processor ────► oddsa_batter_props ✅


LAYER 3: ANALYTICS ───────────────────────────────────────────────► mlb_analytics.*
==================                                                   ================

bdl_pitcher_stats ───► pitcher_game_summary_processor ──────────────► pitcher_game_summary ✅
                       (rolling K averages: k_avg_last_3/5/10)

bdl_batter_stats ────► batter_game_summary_processor ───────────────► batter_game_summary ✅
                       (rolling K rates for bottom-up model)


LAYER 4: FEATURE STORE ───────────────────────────────────────────► mlb_precompute.*
======================                                               =================

pitcher_game_summary + batter_game_summary ──► pitcher_features_processor ✅
+ schedule + lineups                           (25-feature vector)
                                               INCLUDES bottom_up_k_expected!


LAYER 5: MODEL TRAINING ──────────────────────────────────────────► models/
=======================                                              =======

pitcher_ml_features ───► train_pitcher_strikeouts_xgboost.py ❌ (NEXT!)
```

---

## Complete File Inventory

### Scrapers (17 total)

| Source | File | Location | Purpose |
|--------|------|----------|---------|
| MLB Stats API | `mlb_schedule.py` | `scrapers/mlb/mlbstatsapi/` | Schedule with probable pitchers |
| MLB Stats API | `mlb_lineups.py` | `scrapers/mlb/mlbstatsapi/` | Batting lineups (9 batters) |
| BDL | `mlb_pitcher_stats.py` | `scrapers/mlb/balldontlie/` | Per-game pitcher stats |
| BDL | `mlb_batter_stats.py` | `scrapers/mlb/balldontlie/` | Per-game batter stats |
| BDL | `mlb_games.py` | `scrapers/mlb/balldontlie/` | Game schedule/scores |
| BDL | `mlb_active_players.py` | `scrapers/mlb/balldontlie/` | Active player roster |
| BDL | `mlb_injuries.py` | `scrapers/mlb/balldontlie/` | Injury reports |
| BDL | `mlb_season_stats.py` | `scrapers/mlb/balldontlie/` | Season aggregates |
| BDL | `mlb_player_splits.py` | `scrapers/mlb/balldontlie/` | Home/away, day/night splits |
| OddsAPI | `mlb_events.py` | `scrapers/mlb/oddsapi/` | Event IDs for joining |
| OddsAPI | `mlb_game_lines.py` | `scrapers/mlb/oddsapi/` | Moneyline/spread/totals |
| OddsAPI | `mlb_pitcher_props.py` | `scrapers/mlb/oddsapi/` | Pitcher K lines |
| OddsAPI | `mlb_batter_props.py` | `scrapers/mlb/oddsapi/` | Batter K lines |
| OddsAPI | `mlb_events_his.py` | `scrapers/mlb/oddsapi/` | Historical events |
| OddsAPI | `mlb_game_lines_his.py` | `scrapers/mlb/oddsapi/` | Historical game lines |
| OddsAPI | `mlb_pitcher_props_his.py` | `scrapers/mlb/oddsapi/` | Historical pitcher props |
| OddsAPI | `mlb_batter_props_his.py` | `scrapers/mlb/oddsapi/` | Historical batter props |

### Processors (11 total)

| Layer | File | Location | Status |
|-------|------|----------|--------|
| Raw | `mlb_schedule_processor.py` | `data_processors/raw/mlb/` | ✅ |
| Raw | `mlb_lineups_processor.py` | `data_processors/raw/mlb/` | ✅ |
| Raw | `mlb_pitcher_stats_processor.py` | `data_processors/raw/mlb/` | ✅ |
| Raw | `mlb_batter_stats_processor.py` | `data_processors/raw/mlb/` | ✅ |
| Raw | `mlb_events_processor.py` | `data_processors/raw/mlb/` | ✅ |
| Raw | `mlb_game_lines_processor.py` | `data_processors/raw/mlb/` | ✅ |
| Raw | `mlb_pitcher_props_processor.py` | `data_processors/raw/mlb/` | ✅ |
| Raw | `mlb_batter_props_processor.py` | `data_processors/raw/mlb/` | ✅ |
| Analytics | `pitcher_game_summary_processor.py` | `data_processors/analytics/mlb/` | ✅ |
| Analytics | `batter_game_summary_processor.py` | `data_processors/analytics/mlb/` | ✅ |
| Precompute | `pitcher_features_processor.py` | `data_processors/precompute/mlb/` | ✅ |

### BigQuery Schemas

| Dataset | File | Tables |
|---------|------|--------|
| mlb_raw | `mlb_schedule_tables.sql` | mlb_schedule |
| mlb_raw | `mlb_lineups_tables.sql` | mlb_game_lineups, mlb_lineup_batters |
| mlb_raw | `bdl_pitcher_stats_tables.sql` | bdl_pitcher_stats |
| mlb_raw | `bdl_batter_stats_tables.sql` | bdl_batter_stats |
| mlb_raw | `oddsa_tables.sql` | oddsa_events, oddsa_game_lines, oddsa_pitcher_props, oddsa_batter_props |
| mlb_analytics | `pitcher_game_summary_tables.sql` | pitcher_game_summary |
| mlb_analytics | `batter_game_summary_tables.sql` | batter_game_summary |
| mlb_precompute | `ml_feature_store_tables.sql` | pitcher_ml_features |
| mlb_reference | `mlb_players_registry_table.sql` | mlb_players_registry |

---

## Feature Vector (25 dimensions)

The `pitcher_features_processor.py` computes these features:

```python
# Recent Performance (0-4)
f00_k_avg_last_3      # Strikeouts avg last 3 games
f01_k_avg_last_5      # Strikeouts avg last 5 games
f02_k_avg_last_10     # Strikeouts avg last 10 games
f03_k_std_last_10     # Strikeouts std dev (consistency)
f04_ip_avg_last_5     # Innings avg (workload proxy)

# Season Baseline (5-9)
f05_season_k_per_9    # Season K/9 rate
f06_season_era        # Season ERA
f07_season_whip       # Season WHIP
f08_season_games      # Games started this season
f09_season_k_total    # Season total strikeouts

# Split Adjustments (10-14)
f10_is_home           # 1.0 = home, 0.0 = away
f11_home_away_k_diff  # Home K/9 minus Away K/9
f12_is_day_game       # 1.0 = day, 0.0 = night
f13_day_night_k_diff  # Day K/9 minus Night K/9
f14_vs_opponent_k_rate # Historical K rate vs this opponent

# Matchup Context (15-19) - BOTTOM-UP MODEL
f15_opponent_team_k_rate  # How often opponent Ks
f16_opponent_obp          # Opponent on-base percentage
f17_ballpark_k_factor     # Ballpark effect on Ks
f18_game_total_line       # Vegas game total
f19_team_implied_runs     # Team implied runs

# Workload/Fatigue (20-24)
f20_days_rest         # Days since last start
f21_games_last_30_days # Workload indicator
f22_pitch_count_avg   # Average pitch count
f23_season_ip_total   # Season workload
f24_is_postseason     # 1.0 = postseason

# BONUS: Bottom-up calculation
bottom_up_k_expected  # Σ(batter_k_rate × expected_ABs)
```

---

## Bottom-Up Model Implementation

The key innovation is in `pitcher_features_processor.py`:

```python
def _calculate_bottom_up_k(self, opponent_batters, batter_stats):
    """
    Pitcher Ks ≈ Σ (individual batter K probabilities × ABs)
    """
    total_expected_k = 0.0
    for batter in opponent_batters:
        k_rate = batter_stats[batter]['k_rate_last_10'] or 0.20
        expected_abs = self._estimate_abs_by_order(batting_order)
        total_expected_k += k_rate * expected_abs
    return total_expected_k

def _estimate_abs_by_order(self, batting_order):
    # Leadoff gets ~4.5 ABs, 9th hitter gets ~3.5 ABs
    ab_by_order = {1: 4.5, 2: 4.3, 3: 4.2, 4: 4.0, 5: 3.9,
                   6: 3.8, 7: 3.7, 8: 3.6, 9: 3.5}
    return ab_by_order.get(batting_order, 3.8)
```

---

## Verification Commands

```bash
# Verify all MLB components import
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
# Scrapers
from scrapers.mlb.mlbstatsapi import MlbScheduleScraper, MlbLineupsScraper
from scrapers.mlb.balldontlie import MlbPitcherStatsScraper, MlbBatterStatsScraper
from scrapers.mlb.oddsapi import MlbPitcherPropsScraper, MlbBatterPropsScraper

# Raw Processors
from data_processors.raw.mlb import (
    MlbScheduleProcessor, MlbLineupsProcessor,
    MlbPitcherStatsProcessor, MlbBatterStatsProcessor,
    MlbPitcherPropsProcessor, MlbBatterPropsProcessor,
    MlbEventsProcessor, MlbGameLinesProcessor
)

# Analytics Processors
from data_processors.analytics.mlb import (
    MlbPitcherGameSummaryProcessor, MlbBatterGameSummaryProcessor
)

# Feature Store
from data_processors.precompute.mlb import MlbPitcherFeaturesProcessor

print('✅ All MLB components import successfully!')
"

# Check BigQuery schemas exist
ls schemas/bigquery/mlb_raw/
ls schemas/bigquery/mlb_analytics/
ls schemas/bigquery/mlb_precompute/
ls schemas/bigquery/mlb_reference/
```

---

## What's Next (Priority Order)

### 1. Create BigQuery Tables (Required First)
```bash
# Run all schema SQL files to create tables
bq query --use_legacy_sql=false < schemas/bigquery/mlb_raw/mlb_schedule_tables.sql
bq query --use_legacy_sql=false < schemas/bigquery/mlb_raw/mlb_lineups_tables.sql
bq query --use_legacy_sql=false < schemas/bigquery/mlb_raw/bdl_batter_stats_tables.sql
bq query --use_legacy_sql=false < schemas/bigquery/mlb_analytics/batter_game_summary_tables.sql
bq query --use_legacy_sql=false < schemas/bigquery/mlb_reference/mlb_players_registry_table.sql
```

### 2. Create XGBoost Training Script
```
Location: ml/train_pitcher_strikeouts_xgboost.py
Template: ml/train_real_xgboost.py (NBA version)

Key differences from NBA:
- Feature vector is 25 dimensions (pitcher-specific)
- Target is strikeouts (integer, not points)
- Include bottom_up_k_expected as a feature
- Train on historical pitcher props data
```

### 3. Backfill Historical Data
```bash
# Need to run historical scrapers to get training data
# OddsAPI historical scrapers can fetch up to 6 months back

# Then run processors to load into BigQuery
# Then run analytics to compute rolling stats
# Then run feature processor to build training set
```

### 4. Test End-to-End Pipeline
```
1. Scrape today's schedule → Get probable pitchers
2. Scrape lineups (1-2 hours before game) → Get 9 batters
3. Run analytics → Get rolling K stats
4. Run feature processor → Build 25-feature vector
5. Run XGBoost model → Get prediction
6. Compare to betting line → Find edge
```

---

## Key Patterns & Conventions

### Name Normalization
```python
from shared.utils.player_name_normalizer import normalize_name_for_lookup
normalize_name_for_lookup("Gerrit Cole")  # → "gerritcole"
normalize_name_for_lookup("José Ramírez") # → "joseramirez"
```

### Processing Strategies
| Data Type | Strategy | Reason |
|-----------|----------|--------|
| Stats | `MERGE_UPDATE` | One record per game |
| Props | `APPEND_ALWAYS` | Track line movements |

### GCS Paths
```python
# In scrapers/utils/gcs_path_builder.py
"mlb_schedule": "mlb-stats-api/schedule/%(date)s/%(timestamp)s.json"
"mlb_lineups": "mlb-stats-api/lineups/%(date)s/%(timestamp)s.json"
"mlb_batter_stats": "mlb-ball-dont-lie/batter-stats/%(date)s/%(timestamp)s.json"
```

---

## Data Sources

| Source | API | Auth Required | Rate Limits |
|--------|-----|---------------|-------------|
| MLB Stats API | statsapi.mlb.com | No | None |
| Ball Don't Lie | api.balldontlie.io/mlb/v1 | Yes (API key) | 60/min |
| Odds API | api.the-odds-api.com | Yes (API key) | Usage-based |

---

## Copy-Paste Prompt for New Chat

```
Continue the MLB pitcher strikeouts project.

Read the handoff: docs/09-handoff/2026-01-06-MLB-PITCHER-STRIKEOUTS-FINAL-HANDOFF.md

STATUS:
- Layers 1-4 COMPLETE (Scrapers, Raw, Analytics, Feature Store)
- Layer 5 (Model Training) is NEXT

WHAT'S BUILT:
- 17 scrapers (MLB Stats API, BDL, OddsAPI)
- 11 processors (8 raw, 2 analytics, 1 precompute)
- All BigQuery schemas
- 25-feature vector with bottom_up_k_expected calculation

NEXT STEPS:
1. Run BigQuery schema SQL to create tables
2. Create ml/train_pitcher_strikeouts_xgboost.py (use NBA version as template)
3. Backfill historical data for training
4. Test end-to-end prediction pipeline

KEY FILES:
- Feature processor: data_processors/precompute/mlb/pitcher_features_processor.py
- Schema: schemas/bigquery/mlb_precompute/ml_feature_store_tables.sql
- NBA training template: ml/train_real_xgboost.py

VERIFY IMPORTS:
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
from data_processors.precompute.mlb import MlbPitcherFeaturesProcessor
from data_processors.analytics.mlb import MlbPitcherGameSummaryProcessor
print('✅ All MLB components import!')
"
```

---

## Project Documentation

```
docs/08-projects/current/mlb-pitcher-strikeouts/
├── PROJECT-PLAN.md          # Overall project plan
├── DATA-SOURCES.md          # API documentation
├── BDL-MLB-API-ANALYSIS.md  # Ball Don't Lie API details
├── ODDS-DATA-STRATEGY.md    # OddsAPI integration
└── PROGRESS-LOG.md          # Development history
```

---

**Last Updated**: 2026-01-06
**Author**: Claude Code Session
