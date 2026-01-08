# MLB Pipeline Full Deployment Plan

**Created:** 2026-01-07
**Status:** Planning
**Goal:** Deploy full 6-phase MLB pipeline matching NBA architecture

---

## Executive Summary

Deploy the complete MLB data pipeline with all 6 phases, reusing existing code and NBA patterns. The code already exists - this is primarily a deployment and orchestration task.

**Timeline Estimate:** 2-3 days for full deployment

---

## Current State Inventory

### Code Assets (All Exist)

| Component | Count | Location | Status |
|-----------|-------|----------|--------|
| **Scrapers** | 28 | `scrapers/mlb/` | Code complete |
| **Raw Processors** | 8 | `data_processors/raw/mlb/` | Code complete |
| **Analytics Processors** | 2 | `data_processors/analytics/mlb/` | Code complete, tested |
| **Precompute Processors** | 2 | `data_processors/precompute/mlb/` | Code complete |
| **ML Model** | 1 | `gs://nba-scraped-data/ml-models/mlb/` | Trained, deployed |
| **Prediction Worker** | 0 | Need to create | Not started |

### BigQuery Datasets (All Exist)

| Dataset | Tables | Status |
|---------|--------|--------|
| `mlb_raw` | 17 tables | Populated |
| `mlb_analytics` | 6 tables/views | Populated (9,793 rows) |
| `mlb_precompute` | 8 tables/views | Partially populated |
| `mlb_predictions` | 0 tables | Empty - need schema |
| `mlb_orchestration` | 0 tables | Empty - need schema |
| `mlb_reference` | Exists | Need to populate |

### Infrastructure Needed

| Component | NBA Has | MLB Has | Action |
|-----------|---------|---------|--------|
| Cloud Run Services | 16 | 0 | Create 6 services |
| Pub/Sub Topics | 17 | 0 | Create ~10 topics |
| Orchestrators | 4 | 0 | Create 4 orchestrators |
| Scheduler Jobs | 29 | 0 | Create ~15 jobs |
| Deploy Scripts | Many | 0 | Create deploy scripts |

---

## Detailed Scraper Inventory (28 Total)

### Ball Don't Lie API (13 scrapers)
```
mlb_active_players.py    - Player roster data
mlb_batter_stats.py      - Batter game stats
mlb_box_scores.py        - Game box scores
mlb_games.py             - Game schedule/results
mlb_injuries.py          - Injury reports
mlb_live_box_scores.py   - Live game data
mlb_pitcher_stats.py     - Pitcher game stats
mlb_player_splits.py     - Player splits (vs L/R)
mlb_player_versus.py     - Head-to-head stats
mlb_season_stats.py      - Season totals
mlb_standings.py         - Team standings
mlb_team_season_stats.py - Team season stats
mlb_teams.py             - Team info
```

### Odds API (8 scrapers)
```
mlb_events.py            - Today's games
mlb_events_his.py        - Historical events
mlb_game_lines.py        - Moneyline/totals
mlb_game_lines_his.py    - Historical lines
mlb_pitcher_props.py     - Pitcher prop lines (strikeouts!)
mlb_pitcher_props_his.py - Historical pitcher props
mlb_batter_props.py      - Batter prop lines
mlb_batter_props_his.py  - Historical batter props
```

### MLB Stats API (3 scrapers)
```
mlb_lineups.py           - Starting lineups
mlb_schedule.py          - Game schedule
mlb_game_feed.py         - Live game feed
```

### External Sources (3 scrapers)
```
mlb_weather.py           - Game weather
mlb_ballpark_factors.py  - Park factors
mlb_umpire_stats.py      - Umpire tendencies
```

### Statcast (1 scraper)
```
mlb_statcast_pitcher.py  - Pitch-level data
```

---

## Phase-by-Phase Implementation

### Phase 1: MLB Scrapers Service

**Cloud Run Service:** `mlb-phase1-scrapers`

**Pub/Sub Topic:** `mlb-phase1-scrapers-complete`

**Scrapers to Deploy (Priority Order):**
1. Core (Required for predictions):
   - `mlb_schedule.py` - What games today
   - `mlb_lineups.py` - Starting pitchers
   - `mlb_pitcher_props.py` - Strikeout lines
   - `mlb_games.py` - Game results
   - `mlb_live_box_scores.py` - Live scores

2. Analytics (For model features):
   - `mlb_pitcher_stats.py` - Pitcher history
   - `mlb_batter_stats.py` - Batter K rates
   - `mlb_player_splits.py` - L/R splits
   - `mlb_injuries.py` - Who's out

3. Enhancement (Nice to have):
   - `mlb_weather.py`
   - `mlb_ballpark_factors.py`
   - `mlb_umpire_stats.py`

**Deploy Script:** `bin/scrapers/deploy/deploy_mlb_scrapers.sh`

**Scheduler Jobs:**
| Job | Schedule (ET) | Purpose |
|-----|--------------|---------|
| `mlb-schedule-daily` | 6:00 AM | Get today's games |
| `mlb-lineups-morning` | 10:00 AM | Get starting lineups |
| `mlb-lineups-pregame` | 12:00 PM | Refresh lineups |
| `mlb-props-morning` | 10:30 AM | Get strikeout lines |
| `mlb-props-pregame` | 12:30 PM | Refresh lines |
| `mlb-live-evening` | */5 13-23 | Live box scores |
| `mlb-overnight-boxscores` | 2:00 AM | Final box scores |

---

### Phase 2: MLB Raw Processors Service

**Cloud Run Service:** `mlb-phase2-raw-processors`

**Pub/Sub Topic:** `mlb-phase2-raw-complete`

**Processors (8):**
```
mlb_schedule_processor.py      → mlb_raw.mlb_schedule
mlb_lineups_processor.py       → mlb_raw.mlb_game_lineups
mlb_pitcher_stats_processor.py → mlb_raw.mlb_pitcher_stats
mlb_batter_stats_processor.py  → mlb_raw.mlb_batter_stats
mlb_pitcher_props_processor.py → mlb_raw.mlb_pitcher_props
mlb_batter_props_processor.py  → mlb_raw.mlb_batter_props
mlb_game_lines_processor.py    → mlb_raw.mlb_game_lines
mlb_events_processor.py        → mlb_raw.mlb_events
```

**Trigger:** GCS notifications from Phase 1 uploads

**Deploy Script:** `bin/raw/deploy/deploy_mlb_raw_processors.sh`

---

### Phase 3: MLB Analytics Processors Service

**Cloud Run Service:** `mlb-phase3-analytics-processors`

**Pub/Sub Topic:** `mlb-phase3-analytics-complete`

**Processors (2):**
```
pitcher_game_summary_processor.py → mlb_analytics.pitcher_game_summary
batter_game_summary_processor.py  → mlb_analytics.batter_game_summary
```

**Dependencies:**
- `mlb_raw.mlb_pitcher_stats`
- `mlb_raw.mlb_game_lineups`

**Deploy Script:** `bin/analytics/deploy/deploy_mlb_analytics.sh`

---

### Phase 4: MLB Precompute Processors Service

**Cloud Run Service:** `mlb-phase4-precompute-processors`

**Pub/Sub Topic:** `mlb-phase4-precompute-complete`

**Processors (2):**
```
pitcher_features_processor.py    → mlb_precompute.pitcher_ml_features
lineup_k_analysis_processor.py   → mlb_precompute.lineup_k_analysis
```

**Dependencies:**
- `mlb_analytics.pitcher_game_summary`
- `mlb_analytics.batter_game_summary`

**Deploy Script:** `bin/precompute/deploy/deploy_mlb_precompute.sh`

---

### Phase 5: MLB Prediction Worker

**Cloud Run Service:** `mlb-prediction-worker`

**Pub/Sub Topic:** `mlb-phase5-predictions-complete`

**New Code Needed:**
```
predictions/mlb/
├── __init__.py
├── pitcher_strikeouts_predictor.py  # Load model, make predictions
├── prediction_writer.py              # Write to BigQuery
└── worker.py                         # Flask app
```

**BigQuery Tables:**
```sql
-- mlb_predictions.pitcher_strikeouts
CREATE TABLE mlb_predictions.pitcher_strikeouts (
  prediction_id STRING,
  game_date DATE,
  game_id STRING,
  pitcher_lookup STRING,
  pitcher_name STRING,
  team_abbr STRING,
  opponent_team_abbr STRING,

  -- Prediction
  predicted_strikeouts FLOAT64,
  confidence FLOAT64,
  model_version STRING,

  -- Line info
  strikeouts_line FLOAT64,
  over_odds INT64,
  under_odds INT64,

  -- Recommendation
  recommendation STRING,  -- 'OVER', 'UNDER', 'PASS'
  edge FLOAT64,

  -- Metadata
  created_at TIMESTAMP,
  model_features JSON
)
PARTITION BY game_date
CLUSTER BY pitcher_lookup, team_abbr;
```

**Deploy Script:** `bin/predictions/deploy/deploy_mlb_prediction_worker.sh`

---

### Phase 6: MLB Export/Publishing

**Cloud Run Service:** `mlb-phase6-export`

**Pub/Sub Topic:** `mlb-phase6-export-complete`

**Exports:**
```
gs://nba-scraped-data/exports/mlb/
├── daily/
│   └── {date}/
│       ├── pitcher_strikeouts.json    # Today's predictions
│       └── games.json                  # Today's schedule
├── historical/
│   └── predictions_history.json        # Track record
└── latest/
    └── todays_picks.json               # Current picks
```

---

## Orchestration Architecture

### Pub/Sub Topics to Create

```bash
# Phase completion topics
mlb-phase1-scrapers-complete
mlb-phase2-raw-complete
mlb-phase3-analytics-complete
mlb-phase4-precompute-complete
mlb-phase5-predictions-complete
mlb-phase6-export-complete

# Trigger topics
mlb-phase3-trigger
mlb-phase4-trigger
mlb-phase5-trigger
mlb-phase6-trigger

# DLQ topics
mlb-phase1-scrapers-complete-dlq
mlb-phase2-raw-complete-dlq
```

### Orchestrators to Create

```
bin/orchestrators/mlb/
├── deploy_mlb_phase2_to_phase3.sh
├── deploy_mlb_phase3_to_phase4.sh
├── deploy_mlb_phase4_to_phase5.sh
└── deploy_mlb_phase5_to_phase6.sh
```

Each orchestrator:
1. Listens for completion events
2. Tracks processor completions
3. Triggers next phase when all complete

---

## Implementation Order

### Day 1: Foundation
1. Create Pub/Sub topics (15 min)
2. Create BigQuery tables for predictions/orchestration (30 min)
3. Deploy Phase 1 scrapers to Cloud Run (1-2 hours)
4. Test scraper endpoints manually

### Day 2: Processing Pipeline
5. Deploy Phase 2 raw processors (1 hour)
6. Deploy Phase 3 analytics processors (30 min)
7. Deploy Phase 4 precompute processors (30 min)
8. Create orchestrators (1-2 hours)
9. Test Phase 1→4 flow

### Day 3: Predictions & Automation
10. Create MLB prediction worker code (2-3 hours)
11. Deploy prediction worker (30 min)
12. Create Phase 6 export (1 hour)
13. Create scheduler jobs (1 hour)
14. End-to-end test

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| BDL API unauthorized | HIGH | HIGH | Use MLB Stats API as primary |
| Scraper errors | MEDIUM | MEDIUM | Existing retry logic |
| Model accuracy | LOW | MEDIUM | Already validated (MAE 1.71) |
| Quota limits | LOW | LOW | Implement rate limiting |

**Note:** Ball Don't Lie MLB API returned 401 Unauthorized during testing. May need to rely on MLB Stats API + Odds API instead.

---

## Success Criteria

1. **Scrapers:** All 28 scrapers deployed and scheduled
2. **Processing:** Full Phase 1→4 pipeline automated
3. **Predictions:** Daily pitcher strikeout predictions generated
4. **Accuracy:** Model maintains MAE < 1.8 in production
5. **Latency:** Predictions available by 12:00 PM ET daily

---

## Files to Create

### Deploy Scripts
```
bin/scrapers/deploy/deploy_mlb_scrapers.sh
bin/raw/deploy/deploy_mlb_raw_processors.sh
bin/analytics/deploy/deploy_mlb_analytics.sh
bin/precompute/deploy/deploy_mlb_precompute.sh
bin/predictions/deploy/deploy_mlb_prediction_worker.sh
bin/orchestrators/mlb/deploy_all_mlb_orchestrators.sh
bin/schedulers/mlb/setup_mlb_schedulers.sh
```

### Prediction Code
```
predictions/mlb/__init__.py
predictions/mlb/pitcher_strikeouts_predictor.py
predictions/mlb/worker.py
```

### Orchestrator Code
```
orchestrators/mlb/phase2_to_phase3.py
orchestrators/mlb/phase3_to_phase4.py
orchestrators/mlb/phase4_to_phase5.py
orchestrators/mlb/phase5_to_phase6.py
```

### Docker Files
```
docker/mlb-scrapers.Dockerfile
docker/mlb-processors.Dockerfile
docker/mlb-predictions.Dockerfile
```

---

## Quick Start Commands

```bash
# 1. Create Pub/Sub topics
./bin/infrastructure/mlb/create_pubsub_topics.sh

# 2. Create BigQuery tables
bq mk --table mlb_predictions.pitcher_strikeouts schemas/bigquery/mlb/pitcher_strikeouts.sql

# 3. Deploy scrapers
./bin/scrapers/deploy/deploy_mlb_scrapers.sh

# 4. Deploy processors
./bin/raw/deploy/deploy_mlb_raw_processors.sh
./bin/analytics/deploy/deploy_mlb_analytics.sh
./bin/precompute/deploy/deploy_mlb_precompute.sh

# 5. Deploy predictions
./bin/predictions/deploy/deploy_mlb_prediction_worker.sh

# 6. Setup schedulers
./bin/schedulers/mlb/setup_mlb_schedulers.sh

# 7. Test
curl https://mlb-phase1-scrapers-xxx.run.app/health
```
