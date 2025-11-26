# NBA Props Platform - Backfill Strategy

**Document Version:** 1.0  
**Date:** August 4, 2025  
**Status:** Phase 1 Complete, Phase 2-4 Planning

## Executive Summary

The NBA Props Platform backfill strategy provides 4+ seasons of historical NBA data to power predictive models for player prop betting. The strategy leverages multiple data sources and is executed in phases to build a comprehensive foundation while managing API rate limits and data quality.

**Current Status:** ✅ Phase 1 Complete (Schedule Foundation)  
**Data Collected:** 5,583 games across 4 seasons (2021-2025)  
**Storage:** Season-organized GCS structure ready for analytics

## Overall Backfill Architecture

### Data Sources & Timing Strategy

| Source | Purpose | Timing | Rate Limits |
|--------|---------|--------|-------------|
| NBA.com | Schedule foundation, box scores | Any time | Moderate |
| Ball Don't Lie API | Player stats, game data | Any time | Subscription limits |
| Big Data Ball | Enhanced play-by-play | 2+ hours post-game | Processing delays |
| The Odds API | Historical prop odds | Any time | Subscription limits |

### Storage Organization
```
gs://nba-scraped-data/
├── nba-com/
│   ├── schedule/2021-22/ → 2024-25/    ✅ Complete
│   └── box-scores/2021-22/ → 2024-25/  📋 Phase 2
├── ball-dont-lie/
│   └── player-stats/2021-22/ → 2024-25/ 📋 Phase 3  
├── big-data-ball/
│   └── enhanced-pbp/2021-22/ → 2024-25/ 📋 Phase 4
└── odds-api/
    └── props-historical/2021-22/ → 2024-25/ 📋 Phase 4
```

## Phase 1: NBA.com Schedule Foundation ✅ COMPLETE

### Objective
Establish the foundational game inventory across 4 seasons to drive all subsequent data collection.

### Implementation
- **Scraper:** `nbac_schedule_api.py` 
- **Workflow:** `collect-nba-historical-schedules`
- **Execution:** Single workflow run collecting all seasons
- **Output:** Season-organized schedule files with game IDs

### Results Achieved
- **5,583 games** collected across 2021-22 through 2024-25 seasons
- **Season-based GCS organization** for easy analytics access
- **Game ID inventory** ready for box score collection
- **Robust workflow** with status monitoring and error handling

### Key Success Factors
- Season-based storage paths (`actual_season_nba_format`)
- Parallel season collection with individual error handling
- Status writing to operational monitoring bucket
- Cloud Run service integration for reliable data collection

## Phase 2: NBA.com Box Score Collection 📋 PLANNED

### Objective
Collect detailed box scores for all games identified in Phase 1, providing player performance data for each game.

### Proposed Implementation
- **Base Scraper:** `nbac_player_boxscore.py` (existing)
- **New Workflow:** `collect-nba-historical-boxscores`  
- **Execution Strategy:** Season-by-season, chunked by date ranges
- **Input:** Game IDs from Phase 1 schedule data
- **Output:** Player box scores organized by season and game

### Technical Approach
```python
# Workflow pseudocode
for season in ['2021-22', '2022-23', '2023-24', '2024-25']:
    games = load_schedule_data(season)
    for game_batch in chunk_games(games, batch_size=50):
        collect_box_scores_parallel(game_batch)
        rate_limit_pause()
```

### Estimated Scope
- **5,583 games** × **~25 players per game** = ~140,000 player performances
- **Rate limiting:** 50-100 games per batch with pauses
- **Timeline:** 2-3 days execution with proper rate limiting

## Phase 3: Ball Don't Lie API Enhancement 📋 PLANNED

### Objective
Supplement NBA.com data with Ball Don't Lie API for player averages, injury data, and alternative statistics.

### Big Data Ball (BDB) Strategy
**Challenge:** BDB enhanced play-by-play data has 2+ hour processing delays after games end.

**Backfill Advantage:** For historical data, this delay is irrelevant - all games are fully processed.

**Implementation Strategy:**
- **Historical Collection:** No timing constraints, collect all available enhanced PBP
- **Operational Integration:** Design workflows to handle 2+ hour delays for live games
- **Data Enrichment:** Enhanced PBP provides shot locations, defensive matchups, play types

### Proposed Scrapers
- **Existing:** `bdl_active_players.py`, `bdl_box_scores.py`, `bdl_player_averages.py`
- **New:** `bigdataball_historical_pbp.py` for enhanced play-by-play
- **Timeline:** Run after Phase 2 to supplement box score data

## Phase 4: Historical Props & Odds Data 📋 PLANNED

### Objective
Collect historical prop bet odds and lines to understand betting market trends and create target variables for predictions.

### Implementation Challenges
- **Data Availability:** Historical props data may have limited retention
- **API Costs:** The Odds API charges for historical data access
- **Market Coverage:** Focus on major sportsbooks and primary markets (points, rebounds, assists)

### Proposed Approach
- **Scraper:** Extend `oddsa_player_props_his.py` for historical collection
- **Scope:** Focus on current season + 1 prior season initially
- **Markets:** Player points over/under as primary target
- **Integration:** Link to player performance data from Phases 2-3

## Backfill Workflow Architecture

### Workflow Design Patterns
All backfill workflows follow consistent patterns established in Phase 1:

```yaml
# Workflow template structure
- Season-by-season collection with individual error handling
- Cloud Run service integration for data processing  
- Season-based GCS storage paths
- Status monitoring integration
- Parallel processing with rate limiting
- Robust error recovery and partial success handling
```

### Execution Strategy
- **Sequential phases** to manage API load and validate data quality
- **Season chunking** for manageable execution times and debugging
- **Restart capability** for workflows that fail mid-execution
- **Data validation** at each phase before proceeding

## Risk Mitigation

### API Rate Limiting
- **Chunk processing** with configurable batch sizes
- **Exponential backoff** for rate limit responses
- **Multi-day execution** acceptable for historical data
- **Graceful degradation** with partial success tracking

### Data Quality
- **Validation checks** at each collection point
- **Cross-reference validation** between data sources
- **Sample verification** before full execution
- **Rollback capability** for corrupted data

### Operational Impact
- **Off-peak execution** to avoid impacting operational workflows
- **Resource isolation** using separate Cloud Run instances if needed
- **Monitoring integration** to track progress and failures

## Success Metrics

### Data Coverage Targets
- **Schedule Data:** ✅ 100% (5,583/5,583 games)
- **Box Score Data:** 📋 Target 95%+ (expected API gaps)
- **Enhanced PBP:** 📋 Target 80%+ (BDB processing limitations)
- **Historical Props:** 📋 Target 60%+ (data availability constraints)

### Technical Performance
- **Workflow Reliability:** Target 95%+ success rate
- **Data Freshness:** Complete backfill within 2 weeks
- **Storage Efficiency:** Season-based organization for 10x faster analytics queries
- **Cost Management:** Stay within API subscription limits

## Next Steps

### Immediate (Week 1)
1. **Design Phase 2 workflow** for NBA.com box score collection
2. **Create game ID extraction utility** from Phase 1 schedule data
3. **Test batch processing** with small game samples

### Short Term (Weeks 2-3)  
1. **Execute Phase 2** box score collection
2. **Validate data quality** and coverage
3. **Design Phase 3** Ball Don't Lie integration

### Medium Term (Month 1)
1. **Complete historical data foundation** (Phases 2-3)
2. **Begin Phase 4** historical props collection
3. **Analytics validation** with complete dataset

## Data Pipeline Integration

The backfill strategy directly supports the operational data pipeline:

**Backfill Foundation** → **Current Season Operations** → **Predictive Models**

- Historical data trains models
- Current operations provide live data  
- Predictions power prop bet recommendations

**Storage paths align** between backfill and operational workflows for seamless analytics integration.

---

**Document Owner:** Development Team  
**Related Systems:** Cloud Run Services, Google Cloud Workflows, GCS Storage  
**Dependencies:** NBA.com API, Ball Don't Lie API, Big Data Ball, The Odds API