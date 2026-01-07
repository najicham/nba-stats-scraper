# MLB Pitcher Strikeouts - Comprehensive Handoff

**Date**: 2026-01-06 (Final Update)
**Session**: Complete Data Infrastructure Implementation
**Status**: Full Pipeline Ready - Raw, Analytics, Schedule, Lineups Complete

---

## Project Goal

Build a **pitcher strikeout prediction model** for MLB that:
1. Predicts pitcher K over/under outcomes
2. Uses a **bottom-up model**: Sum of individual batter K probabilities ≈ Pitcher K total
3. Incorporates game context (moneyline, totals, spreads) for correlation analysis

**Key Insight**:
```
Pitcher K's ≈ Σ (individual batter K probabilities)

If batter K lines don't sum to pitcher K line → market inefficiency → edge
```

---

## What Was Completed This Session

### NEW: Schedule Infrastructure (MLB Stats API) ✅ CRITICAL

| File | Location | Purpose |
|------|----------|---------|
| `mlb_schedule.py` | `scrapers/mlb/mlbstatsapi/` | Fetch schedule with probable pitchers |
| `mlb_lineups.py` | `scrapers/mlb/mlbstatsapi/` | Fetch batting lineups (for bottom-up model) |
| `mlb_schedule_processor.py` | `data_processors/raw/mlb/` | Process schedule to BigQuery |
| `mlb_lineups_processor.py` | `data_processors/raw/mlb/` | Process lineups to BigQuery |
| `mlb_schedule_tables.sql` | `schemas/bigquery/mlb_raw/` | Schedule schema (with probable pitchers) |
| `mlb_lineups_tables.sql` | `schemas/bigquery/mlb_raw/` | Lineups schema (2 tables) |

**Why This Is Critical:**
- Schedule tells us WHO is pitching (prediction target)
- Lineups tell us which 9 batters face the pitcher (bottom-up model)
- Without these, predictions are impossible!

### NEW: Analytics Layer (Rolling Stats for ML Features) ✅

| File | Location | Purpose |
|------|----------|---------|
| `pitcher_game_summary_processor.py` | `data_processors/analytics/mlb/` | Rolling K averages for pitchers |
| `batter_game_summary_processor.py` | `data_processors/analytics/mlb/` | Rolling K rates for batters (bottom-up model) |
| `pitcher_game_summary_tables.sql` | `schemas/bigquery/mlb_analytics/` | Pitcher analytics schema (existed) |
| `batter_game_summary_tables.sql` | `schemas/bigquery/mlb_analytics/` | Batter analytics schema |
| `mlb_players_registry_table.sql` | `schemas/bigquery/mlb_reference/` | Player registry schema |

### Previous: BDL Batter Stats (Critical for Bottom-Up Model) ✅

| File | Location | Purpose |
|------|----------|---------|
| `mlb_batter_stats.py` | `scrapers/mlb/balldontlie/` | Fetch per-game batter stats (strikeouts, AB, hits) |
| `mlb_batter_stats_processor.py` | `data_processors/raw/mlb/` | Load batter stats to BigQuery |
| `bdl_batter_stats_tables.sql` | `schemas/bigquery/mlb_raw/` | BigQuery table schema |

### Previous: Odds Processors (4 files) ✅

| File | Location | Purpose |
|------|----------|---------|
| `mlb_pitcher_props_processor.py` | `data_processors/raw/mlb/` | Load pitcher K lines to BigQuery |
| `mlb_batter_props_processor.py` | `data_processors/raw/mlb/` | Load batter K lines (bottom-up model) |
| `mlb_events_processor.py` | `data_processors/raw/mlb/` | Load event IDs for joins |
| `mlb_game_lines_processor.py` | `data_processors/raw/mlb/` | Load moneyline/spread/totals |

### Previous: Historical Scrapers (4 files) ✅

| File | Location | Purpose |
|------|----------|---------|
| `mlb_events_his.py` | `scrapers/mlb/oddsapi/` | Historical event IDs at snapshot |
| `mlb_game_lines_his.py` | `scrapers/mlb/oddsapi/` | Historical game lines at snapshot |
| `mlb_pitcher_props_his.py` | `scrapers/mlb/oddsapi/` | Historical pitcher props (for training) |
| `mlb_batter_props_his.py` | `scrapers/mlb/oddsapi/` | Historical batter props (for training) |

### Also Updated
- `data_processors/raw/mlb/__init__.py` - Exports all 6 processors
- `scrapers/mlb/balldontlie/__init__.py` - Exports all BDL scrapers including batter stats
- `scrapers/utils/gcs_path_builder.py` - Added mlb_batter_stats GCS path

---

## Current MLB Implementation Status

### Scrapers (14 total)

| Source | Scraper | Current | Historical | Status |
|--------|---------|---------|------------|--------|
| OddsAPI | Events | `mlb_events.py` | `mlb_events_his.py` | ✅ Complete |
| OddsAPI | Game Lines | `mlb_game_lines.py` | `mlb_game_lines_his.py` | ✅ Complete |
| OddsAPI | Pitcher Props | `mlb_pitcher_props.py` | `mlb_pitcher_props_his.py` | ✅ Complete |
| OddsAPI | Batter Props | `mlb_batter_props.py` | `mlb_batter_props_his.py` | ✅ Complete |
| BDL | Games | `mlb_games.py` | - | ✅ Complete |
| BDL | Pitcher Stats | `mlb_pitcher_stats.py` | - | ✅ Complete |
| BDL | Batter Stats | `mlb_batter_stats.py` | - | ✅ Complete |
| BDL | Active Players | `mlb_active_players.py` | - | ✅ Complete |
| BDL | Injuries | `mlb_injuries.py` | - | ✅ Complete |
| BDL | Season Stats | `mlb_season_stats.py` | - | ✅ Complete |
| BDL | Player Splits | `mlb_player_splits.py` | - | ✅ Complete |

### Processors (6 of 10+ needed)

| Processor | Status | Priority |
|-----------|--------|----------|
| `mlb_pitcher_stats_processor.py` | ✅ Complete | - |
| `mlb_batter_stats_processor.py` | ✅ Complete | - |
| `mlb_pitcher_props_processor.py` | ✅ Complete | - |
| `mlb_batter_props_processor.py` | ✅ Complete | - |
| `mlb_events_processor.py` | ✅ Complete | - |
| `mlb_game_lines_processor.py` | ✅ Complete | - |
| `mlb_games_processor.py` | ❌ Missing | P2 |
| `mlb_injuries_processor.py` | ❌ Missing | P2 |
| `mlb_season_stats_processor.py` | ❌ Missing | P2 |
| `mlb_player_splits_processor.py` | ❌ Missing | P2 |
| `mlb_active_players_processor.py` | ❌ Missing | P3 |

### BigQuery Tables

| Dataset | Table | Status |
|---------|-------|--------|
| `mlb_raw` | `bdl_pitcher_stats` | ✅ Schema exists |
| `mlb_raw` | `bdl_batter_stats` | ✅ Schema exists (run SQL to create) |
| `mlb_raw` | `oddsa_events` | ✅ Schema exists |
| `mlb_raw` | `oddsa_game_lines` | ✅ Schema exists |
| `mlb_raw` | `oddsa_pitcher_props` | ✅ Schema exists |
| `mlb_raw` | `oddsa_batter_props` | ✅ Schema exists |
| `mlb_reference` | `mlb_players_registry` | ❌ Needs creation |

---

## Priority Todo List

### P1: BDL Batter Stats (Critical for Bottom-Up Model) ✅ COMPLETE

```
[x] 1. Create mlb_batter_stats.py scraper
    - Fetch per-game batter stats from BDL API
    - Include: at_bats, hits, strikeouts (K), walks
    - Use existing mlb_pitcher_stats.py as template
    - Location: scrapers/mlb/balldontlie/

[x] 2. Create bdl_batter_stats_tables.sql schema
    - Partition by game_date
    - Cluster by player_lookup, team_abbr
    - Key fields: strikeouts, at_bats, hits, walks
    - Location: schemas/bigquery/mlb_raw/

[x] 3. Create mlb_batter_stats_processor.py
    - Load batter stats from GCS to mlb_raw.bdl_batter_stats
    - Use mlb_pitcher_stats_processor.py as template
    - Location: data_processors/raw/mlb/
```

### P1: MLB Player Registry

```
[ ] 4. Create mlb_players_registry table schema
    - Similar to nba_players_registry
    - Key fields: player_lookup, bdl_player_id, team_abbr, position
    - Location: schemas/bigquery/mlb_reference/

[ ] 5. Create mlb_player_aliases table (or share with NBA)
    - Maps variations to canonical names
    - Example: "José Ramírez" → "joseramirez"
```

### P2: Supporting BDL Processors

```
[ ] 6. Create mlb_games_processor.py
[ ] 7. Create mlb_injuries_processor.py
[ ] 8. Create mlb_season_stats_processor.py
[ ] 9. Create mlb_player_splits_processor.py
[ ] 10. Create mlb_active_players_processor.py
```

### P2: Analytics Layer

```
[ ] 11. Create pitcher_game_summary_processor.py
     - Rolling K averages (last 5, 10, season)
     - Location: data_processors/analytics/mlb/

[ ] 12. Create batter_game_summary_processor.py
     - Rolling K rates per batter
```

### P2: Feature Store

```
[ ] 13. Create pitcher_strikeout_features_processor.py
     - 25-feature vector per pitcher per game
     - Location: data_processors/precompute/mlb/
```

### P3: Model Training

```
[ ] 14. Create train_pitcher_strikeouts_xgboost.py
     - Follow NBA pattern from train_real_xgboost.py
     - Location: ml/
```

---

## Key Documentation to Study

```bash
# Main project docs
cat docs/08-projects/current/mlb-pitcher-strikeouts/PROJECT-PLAN.md
cat docs/08-projects/current/mlb-pitcher-strikeouts/PROGRESS-LOG.md
cat docs/08-projects/current/mlb-pitcher-strikeouts/DATA-SOURCES.md
cat docs/08-projects/current/mlb-pitcher-strikeouts/ODDS-DATA-STRATEGY.md
cat docs/08-projects/current/mlb-pitcher-strikeouts/BDL-MLB-API-ANALYSIS.md

# Previous handoff
cat docs/09-handoff/2026-01-06-MLB-ODDS-SCRAPERS-COMPLETE.md
```

---

## Key Code to Study

### Existing MLB Processors (Templates)

```bash
cat data_processors/raw/mlb/mlb_pitcher_stats_processor.py
cat data_processors/raw/mlb/mlb_pitcher_props_processor.py
cat data_processors/raw/mlb/mlb_batter_props_processor.py
```

### Existing MLB Scrapers (Templates)

```bash
cat scrapers/mlb/balldontlie/mlb_pitcher_stats.py
cat scrapers/mlb/oddsapi/mlb_pitcher_props.py
cat scrapers/mlb/oddsapi/mlb_pitcher_props_his.py
```

### NBA Equivalents (Patterns to Follow)

```bash
# Player name normalization (sport-agnostic, reuse as-is)
cat shared/utils/player_name_normalizer.py

# Player registry system
cat shared/utils/player_name_resolver.py

# NBA props processor (pattern)
cat data_processors/raw/oddsapi/odds_api_props_processor.py

# NBA registry schemas
cat schemas/bigquery/nba_reference/nba_players_registry_table.sql
```

### BigQuery Schemas

```bash
cat schemas/bigquery/mlb_raw/oddsa_tables.sql
```

---

## Key Architecture Decisions

### 1. Name Normalization (Reuse NBA)

```python
from shared.utils.player_name_normalizer import normalize_name_for_lookup

normalize_name_for_lookup("José Ramírez")  # → "joseramirez"
normalize_name_for_lookup("P.J. Tucker")   # → "pjtucker"
```

### 2. Processing Strategies

| Data Type | Strategy | Reason |
|-----------|----------|--------|
| Props | `APPEND_ALWAYS` | Track line movements |
| Stats | `MERGE_UPDATE` | One record per game |

### 3. Player Lookup Key

All tables use `player_lookup` as normalized join key:
- Lowercase, no spaces/punctuation/diacritics
- Example: "Gerrit Cole" → "gerritcole"

---

## Verification Commands

```bash
# Verify scrapers import
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
from scrapers.mlb.oddsapi import (
    MlbEventsOddsScraper, MlbGameLinesScraper,
    MlbPitcherPropsScraper, MlbBatterPropsScraper,
    MlbEventsHistoricalScraper, MlbGameLinesHistoricalScraper,
    MlbPitcherPropsHistoricalScraper, MlbBatterPropsHistoricalScraper,
)
print('✅ All MLB Odds scrapers import successfully!')
"

# Verify processors import
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
from data_processors.raw.mlb import (
    MlbPitcherStatsProcessor, MlbBatterStatsProcessor, MlbPitcherPropsProcessor,
    MlbBatterPropsProcessor, MlbEventsProcessor, MlbGameLinesProcessor,
)
print('✅ All MLB processors import successfully!')
"

# Verify BDL scrapers import
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
from scrapers.mlb.balldontlie import MlbPitcherStatsScraper, MlbBatterStatsScraper
print('✅ BDL scrapers import successfully!')
"

# Verify BigQuery tables
bq ls --project_id=nba-props-platform mlb_raw
```

---

## Copy-Paste Prompt for New Chat

```
Continue the MLB pitcher strikeouts project.

Read the handoff: docs/09-handoff/2026-01-06-MLB-PITCHER-STRIKEOUTS-HANDOFF.md

SUMMARY:
- SCHEDULE INFRASTRUCTURE COMPLETE: mlb_schedule + mlb_lineups scrapers/processors
- RAW LAYER COMPLETE: 8 processors, all scrapers (BDL, OddsAPI, MLB Stats API)
- ANALYTICS LAYER COMPLETE: pitcher_game_summary, batter_game_summary with rolling K stats
- ALL SCHEMAS COMPLETE: Raw, analytics, lineups, schedule, player registry

WHAT'S READY (Full Data Pipeline):
- Schedule with probable pitchers (WHO is pitching)
- Lineups with batting order (which 9 batters to sum)
- Pitcher rolling K averages (k_avg_last_3/5/10, k_per_9_rolling_10)
- Batter rolling K rates (k_rate_last_5/10, k_avg_last_10)
- Bottom-up model data: Sum batter K rates → Predicted pitcher Ks

NEXT PRIORITY:
1. Run BigQuery schema SQL to create all tables
2. Create train_pitcher_strikeouts_xgboost.py model training
3. Backfill historical data for training
4. Test end-to-end prediction pipeline

FEATURE STORE COMPLETE:
- data_processors/precompute/mlb/pitcher_features_processor.py
- 25-feature vector with bottom_up_k_expected calculation

VERIFICATION COMMANDS:
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
from scrapers.mlb.mlbstatsapi import MlbScheduleScraper, MlbLineupsScraper
from data_processors.raw.mlb import MlbScheduleProcessor, MlbLineupsProcessor
from data_processors.analytics.mlb import MlbPitcherGameSummaryProcessor, MlbBatterGameSummaryProcessor
print('✅ All MLB components import successfully!')
"

NEW FILES THIS SESSION:
- scrapers/mlb/mlbstatsapi/mlb_schedule.py
- scrapers/mlb/mlbstatsapi/mlb_lineups.py
- data_processors/raw/mlb/mlb_schedule_processor.py
- data_processors/raw/mlb/mlb_lineups_processor.py
- schemas/bigquery/mlb_raw/mlb_schedule_tables.sql
- schemas/bigquery/mlb_raw/mlb_lineups_tables.sql
- data_processors/analytics/mlb/pitcher_game_summary_processor.py
- data_processors/analytics/mlb/batter_game_summary_processor.py
- data_processors/precompute/mlb/pitcher_features_processor.py (25-feature vector with bottom-up K!)
```

---

## Architecture Diagram

```
LAYER 1: SCRAPERS ──────────────────► LAYER 2: RAW PROCESSORS ───────────► mlb_raw.*
====================                  ========================            ==========

MLB Stats API (CRITICAL - tells us WHO is playing):
──► mlb_schedule.py ────────────────► mlb_schedule_processor ─────────► mlb_schedule ✅
                                      (probable pitchers!)
──► mlb_lineups.py ─────────────────► mlb_lineups_processor ──────────► mlb_game_lineups ✅
                                                                        mlb_lineup_batters ✅
                                      (9 batters for bottom-up)

BDL API (Historical stats):
──► mlb_pitcher_stats.py ───────────► mlb_pitcher_stats_processor ────► bdl_pitcher_stats ✅
──► mlb_batter_stats.py ────────────► mlb_batter_stats_processor ─────► bdl_batter_stats ✅

Odds API (Betting lines):
──► mlb_events.py ──────────────────► mlb_events_processor ───────────► oddsa_events ✅
──► mlb_game_lines.py ──────────────► mlb_game_lines_processor ───────► oddsa_game_lines ✅
──► mlb_pitcher_props.py ───────────► mlb_pitcher_props_processor ────► oddsa_pitcher_props ✅
──► mlb_batter_props.py ────────────► mlb_batter_props_processor ─────► oddsa_batter_props ✅


LAYER 3: ANALYTICS PROCESSORS ───────────────────────────────────────► mlb_analytics.*
==============================                                        ================

bdl_pitcher_stats ──► pitcher_game_summary_processor ─────────────────► pitcher_game_summary ✅
                      (rolling K averages: k_avg_last_3/5/10)

bdl_batter_stats ───► batter_game_summary_processor ──────────────────► batter_game_summary ✅
                      (rolling K rates for bottom-up model)


PREDICTION DAY FLOW (New capability!):
======================================

mlb_schedule           "Gerrit Cole starts vs BOS"
     │                         │
     ▼                         ▼
mlb_lineup_batters ──► [Devers, Turner, Yoshida, ...] ◄── batter_game_summary
     │                         │                               (K rates)
     ▼                         ▼
Bottom-Up Calc:  Σ(batter_k_rate × expected_ABs) = ~5.8 expected Ks
                                │
                                ▼
Compare to:      Cole's K line O/U 6.5 ──► UNDER prediction


LAYER 4: FEATURE STORE ──────────────────────────────────────────────► mlb_precompute.*
======================                                                =================

pitcher_game_summary + batter_game_summary ──► pitcher_features_processor ✅
+ schedule + lineups                           (25-feature vector)
                                               INCLUDES bottom_up_k_expected!


LAYER 5: MODEL TRAINING ─────────────────────────────────────────────► models/
=======================

pitcher_strikeout_features ──► train_pitcher_strikeouts_xgboost.py ❌


✅ = Complete    ❌ = Next Priority
```
