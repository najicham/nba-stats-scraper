# NBA Props Platform - Backfill Scrapers Reference

**Document Version:** 1.0  
**Date:** August 4, 2025  
**Purpose:** Quick reference for scrapers used in historical data collection (backfill)

## Overview

The NBA Props Platform backfill process uses specific scrapers to collect 4+ seasons of historical NBA data. This document focuses exclusively on scrapers used for **backfill workflows** and historical data collection.

## Phase 1: Schedule Foundation ✅ COMPLETE

### `nbac_schedule_api.py` ✅ ACTIVE
**Purpose:** Collect NBA game schedules for historical seasons  
**Data:** Game IDs, dates, teams, basic game info  
**Backfill Usage:**
- **Workflow:** `collect-nba-historical-schedules`
- **Seasons:** 2021-22, 2022-23, 2023-24, 2024-25
- **Output:** 5,583 games across 4 seasons

**Execution Pattern:**
```yaml
# Workflow calls scraper for each season
- call: http.post
  args:
    body:
      scraper: "nbac_schedule_api"
      season: 2021  # Then 2022, 2023, 2024
      group: "prod"
```

**Storage:** `gs://nba-scraped-data/nba-com/schedule/SEASON/timestamp.json`

**Key Success:** Provides game ID foundation for all subsequent backfill phases

## Phase 2: Box Score Collection 📋 PLANNED

### `nbac_player_boxscore.py` 📋 PRIMARY
**Purpose:** Collect detailed player statistics for historical games  
**Data:** Points, rebounds, assists, shooting stats per player per game  
**Backfill Usage:**
- **Workflow:** `collect-nba-historical-boxscores` (planned)
- **Input:** Game IDs from Phase 1 schedule data
- **Scope:** ~140,000 player performances (5,583 games × ~25 players)

**Execution Strategy:**
```python
# Planned workflow approach
for season in ['2021-22', '2022-23', '2023-24', '2024-25']:
    games = load_schedule_data(season)
    for game_batch in chunk_games(games, batch_size=50):
        collect_box_scores_parallel(game_batch)
        rate_limit_pause()
```

**Storage:** `gs://nba-scraped-data/nba-com/box-scores/SEASON/GAME_ID/timestamp.json`

**Rate Limiting:** 50-100 games per batch with pauses

### `bdl_box_scores.py` 📋 SUPPLEMENTAL
**Purpose:** Alternative box score data source for validation/enrichment  
**Data:** Player and team statistics from Ball Don't Lie API  
**Backfill Usage:**
- **Workflow:** Extension of Phase 2 box score collection
- **Role:** Data validation and gap filling

**Benefits:**
- Cross-validation with NBA.com data
- Backup data source for missing games
- Additional statistical categories

## Phase 3: Enhanced Player Data 📋 PLANNED

### `bdl_player_averages.py` 📋 PLANNED
**Purpose:** Historical season and career player averages  
**Data:** Aggregated statistics, performance trends  
**Backfill Usage:**
- **Workflow:** `collect-nba-historical-player-baselines` (planned)
- **Scope:** Player performance baselines for each historical season
- **Purpose:** Provide context for individual game performances

**Use Case:** Compare individual game stats to season averages for outlier detection

### `bdl_active_players.py` 📋 SUPPORTING
**Purpose:** Historical player database and metadata  
**Data:** Player IDs, names, team history  
**Backfill Usage:**
- **Workflow:** Player ID mapping for historical data
- **Purpose:** Link players across different data sources

## Phase 4: Enhanced Play-by-Play 📋 PLANNED

### `bigdataball_pbp.py` 📋 ADVANCED
**Purpose:** Enhanced play-by-play data for historical games  
**Data:** Shot locations, defensive matchups, advanced play types  
**Key Advantage:** 2+ hour processing delay irrelevant for historical data

**Backfill Usage:**
- **Workflow:** `collect-nba-historical-enhanced-pbp` (planned)
- **Scope:** Advanced analytics for all historical games
- **Strategic Value:** Shot location and defensive matchup data

**Historical Collection Benefits:**
- No timing constraints (vs live data 2+ hour delay)
- Complete dataset available
- Enhanced analytics capabilities

**Storage:** `gs://nba-scraped-data/big-data-ball/enhanced-pbp/SEASON/GAME_ID/timestamp.json`

## Phase 5: Historical Props Data 📋 PLANNED

### `oddsa_player_props_his.py` 📋 PLANNED
**Purpose:** Historical player prop bet odds and lines  
**Data:** Past betting lines, market movement, closing odds  
**Backfill Usage:**
- **Workflow:** `collect-nba-historical-props` (planned)
- **Scope:** Historical prop data for model training targets
- **Constraints:** Limited data retention, API costs

**Implementation Strategy:**
- Focus on major sportsbooks and primary markets
- Start with player points over/under props
- Link to player performance data from earlier phases

**Storage:** `gs://nba-scraped-data/odds-api/props-historical/SEASON/timestamp.json`

## Backfill Workflow Architecture

### Execution Order
```
Phase 1: nbac_schedule_api.py → Game foundation
    ↓
Phase 2: nbac_player_boxscore.py → Player performance data
    ↓  
Phase 3: bdl_player_averages.py → Performance baselines
    ↓
Phase 4: bigdataball_pbp.py → Enhanced analytics
    ↓
Phase 5: oddsa_player_props_his.py → Historical betting targets
```

### Workflow Patterns
All backfill workflows follow consistent patterns:

```yaml
# Template structure
- Season-by-season collection (2021-22 → 2024-25)
- Batch processing with rate limiting
- Individual season error handling  
- Season-based GCS storage paths
- Status monitoring integration
- Restart capability for failed executions
```

### Data Dependencies
- **Phase 2-5** require game IDs from Phase 1
- **Phase 3** enhances Phase 2 player data
- **Phase 4** provides advanced context for Phases 2-3
- **Phase 5** provides target variables for prediction models

## Rate Limiting & Execution Strategy

### API Constraints by Source
- **NBA.com:** Moderate limits, batch 50-100 requests
- **Ball Don't Lie:** Subscription limits, smaller batches
- **Big Data Ball:** Processing delays, not rate limits  
- **The Odds API:** Cost per request, careful usage

### Batch Processing Strategy
```python
# Typical batch approach
games_per_batch = 50  # Configurable by API source
pause_between_batches = 30  # seconds
exponential_backoff = True  # For rate limit errors
```

### Timeline Estimates
- **Phase 1:** ✅ Complete (117 seconds)
- **Phase 2:** 2-3 days (140k requests with rate limiting)
- **Phase 3:** 1 day (player aggregates)  
- **Phase 4:** 3-5 days (enhanced PBP for 5,583 games)
- **Phase 5:** 1-2 days (limited historical props)

## Storage Organization

All backfill scrapers use season-based storage:
```
gs://nba-scraped-data/
├── nba-com/
│   ├── schedule/
│   │   ├── 2021-22/...json     ✅ Complete
│   │   ├── 2022-23/...json     ✅ Complete  
│   │   ├── 2023-24/...json     ✅ Complete
│   │   └── 2024-25/...json     ✅ Complete
│   └── box-scores/
│       ├── 2021-22/...json     📋 Phase 2
│       ├── 2022-23/...json     📋 Phase 2
│       ├── 2023-24/...json     📋 Phase 2
│       └── 2024-25/...json     📋 Phase 2
├── ball-dont-lie/
│   └── player-averages/        📋 Phase 3
├── big-data-ball/
│   └── enhanced-pbp/           📋 Phase 4
└── odds-api/
    └── props-historical/       📋 Phase 5
```

## Success Metrics

### Data Coverage Targets
- **Schedule Data:** ✅ 100% (5,583/5,583 games)
- **Box Score Data:** 📋 Target 95%+ (expected API gaps)
- **Enhanced PBP:** 📋 Target 80%+ (processing limitations)
- **Historical Props:** 📋 Target 60%+ (data availability)

### Technical Performance
- **Workflow Reliability:** 95%+ success rate per phase
- **Data Quality:** Cross-validation between sources
- **Storage Efficiency:** Season-based organization
- **Cost Management:** Stay within API subscription limits

## Testing & Validation

### Local Testing
```bash
# Test individual scrapers before workflow execution
python scrapers/nbacom/nbac_player_boxscore.py --game-id "0022100001" --debug
python scrapers/balldontlie/bdl_box_scores.py --game-id "123456" --debug
```

### Workflow Testing
```bash
# Test workflows with small samples before full execution
gcloud workflows run collect-nba-historical-boxscores --location=us-west2 \
  --data='{"season": "2021-22", "game_limit": 10}'
```

### Data Validation
- Cross-reference game counts between phases
- Validate player performance ranges
- Check data completeness by season

---

**Current Status:** Phase 1 complete, Phase 2 ready for implementation  
**Next Implementation:** Box score collection workflow using `nbac_player_boxscore.py`
