# File: validation/queries/raw/nbac_play_by_play/BACKFILL_OPPORTUNITY.md
# NBA.com Play-by-Play Backfill Opportunity

## Executive Summary

**Current Coverage**: 2 games (0.04% of available data)  
**Available Data**: 5,400+ games from October 2021 onwards  
**Business Impact**: HIGH - Official NBA play-by-play for advanced prop analysis  
**Processing Time**: ~18-24 seconds per game = ~27-36 hours for full backfill  

## Coverage Analysis

### Current State (October 2025)

| Metric | Current | Potential | Gap |
|--------|---------|-----------|-----|
| **Games** | 2 | 5,400+ | 5,398 games |
| **Events** | 1,043 | ~2.7M | 99.96% missing |
| **Players** | 35 | 500+ | Limited coverage |
| **Seasons** | Partial 2024-25 | 4 complete seasons | 3.75 seasons |

### Games by Season

Based on typical NBA schedule:

| Season | Regular Season | Playoffs | Total | Status |
|--------|---------------|----------|-------|---------|
| 2021-22 | ~1,230 | ~80 | 1,310 | ❌ Not collected |
| 2022-23 | ~1,230 | ~80 | 1,310 | ❌ Not collected |
| 2023-24 | ~1,230 | ~80 | 1,310 | ❌ Not collected |
| 2024-25 | ~1,230 | ~80 | 1,310 | ⚪ 2 games only |
| **TOTAL** | **~4,920** | **~320** | **~5,240** | **0.04% coverage** |

## Why Backfill Now?

### Business Benefits

1. **Advanced Prop Analysis**
   - Shot location data for player tendencies
   - Lineup impact on player performance
   - Game flow patterns for live betting
   - Historical context for prop lines

2. **Cross-Source Validation**
   - Validate BigDataBall play-by-play
   - Confirm Ball Don't Lie box scores
   - Authoritative NBA source

3. **Player Development Tracking**
   - Multi-season player progression
   - Team defensive schemes
   - Matchup-specific performance

4. **Model Training Data**
   - 2.7M+ events for ML models
   - Rich feature engineering
   - Temporal patterns

### Technical Advantages

✅ **Processor Proven**: 100% success rate on test games  
✅ **Infrastructure Ready**: BigQuery tables configured  
✅ **Data Available**: NBA.com has historical play-by-play  
✅ **Fast Processing**: 18-24 seconds per game  

## Backfill Strategy

### Phase 1: Current Season (Priority)

**Target**: 2024-25 season games  
**Reasoning**: Most valuable for current operations  
**Timeline**: 1-2 days  

```bash
# Current season dates (adjust as needed)
START_DATE="2024-10-22"  # Season start
END_DATE="2025-04-15"    # Regular season end

# Process current season
python scrapers/nba_com/nbac_play_by_play.py \
  --start-date $START_DATE \
  --end-date $END_DATE
```

**Expected Results**:
- ~1,200 games
- ~600,000 events
- Processing time: ~6-8 hours

### Phase 2: Recent Historical (High Value)

**Target**: 2023-24 and 2022-23 seasons  
**Reasoning**: Recent data for model training  
**Timeline**: 3-4 days  

```bash
# 2023-24 season
START_DATE="2023-10-24"
END_DATE="2024-06-17"  # Finals

# 2022-23 season  
START_DATE="2022-10-18"
END_DATE="2023-06-12"  # Finals

# Process each season separately
for season in "2023-24" "2022-23"; do
  python scrapers/nba_com/nbac_play_by_play.py \
    --start-date $START_DATE \
    --end-date $END_DATE
done
```

**Expected Results**:
- ~2,600 games
- ~1.3M events
- Processing time: ~13-16 hours

### Phase 3: Complete Historical (Full Coverage)

**Target**: 2021-22 season  
**Reasoning**: Complete 4-season dataset  
**Timeline**: 2-3 days  

```bash
# 2021-22 season
START_DATE="2021-10-19"
END_DATE="2022-06-16"  # Finals

python scrapers/nba_com/nbac_play_by_play.py \
  --start-date $START_DATE \
  --end-date $END_DATE
```

**Expected Results**:
- ~1,300 games
- ~650,000 events
- Processing time: ~6-8 hours

## Resource Requirements

### Processing Time

| Phase | Games | Events | Time (Est.) | Parallelization |
|-------|-------|--------|-------------|-----------------|
| Phase 1 | 1,200 | 600K | 6-8 hours | 3-4 parallel jobs |
| Phase 2 | 2,600 | 1.3M | 13-16 hours | 3-4 parallel jobs |
| Phase 3 | 1,300 | 650K | 6-8 hours | 3-4 parallel jobs |
| **TOTAL** | **5,100** | **2.55M** | **25-32 hours** | **Reduce to 8-10 hours** |

### Cloud Run Configuration

**Recommended Settings**:
```yaml
Memory: 8Gi
CPU: 4 cores
Timeout: 6 hours
Concurrency: 1
Max Instances: 4  # Run 4 seasons in parallel
```

**Cost Estimate**:
- Processing: ~$2-3 per 1,000 games
- BigQuery Storage: ~$0.02/GB/month
- Total One-Time Cost: ~$10-15
- Ongoing Storage: ~$0.50/month

### BigQuery Storage

**Expected Table Size**:
- Events: 2.55M rows
- Size: ~500-800 MB compressed
- Monthly cost: ~$0.01-0.02

## Validation During Backfill

### Pre-Backfill Checks

```bash
# Baseline current state
validate-nbac-pbp games --csv > pre_backfill_$(date +%Y%m%d).csv

# Document missing games
validate-nbac-pbp missing --csv > missing_games_$(date +%Y%m%d).csv
```

### During Backfill (Run After Each Phase)

```bash
# Check phase completion
validate-nbac-pbp games

# Verify event counts
validate-nbac-pbp events

# Cross-validate with box scores
validate-nbac-pbp players

# Check score integrity
validate-nbac-pbp scores
```

### Post-Backfill Validation

```bash
# Complete validation
validate-nbac-pbp all --csv > post_backfill_$(date +%Y%m%d).csv

# Compare coverage
diff pre_backfill_*.csv post_backfill_*.csv

# Verify expected metrics
bq query --use_legacy_sql=false "
SELECT 
  EXTRACT(YEAR FROM game_date) as season,
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as total_events,
  COUNT(DISTINCT player_1_id) as unique_players,
  ROUND(AVG(events_per_game), 0) as avg_events
FROM (
  SELECT 
    game_date,
    game_id,
    player_1_id,
    COUNT(*) OVER (PARTITION BY game_id) as events_per_game
  FROM \`nba-props-platform.nba_raw.nbac_play_by_play\`
  WHERE game_date >= '2021-10-01'
)
GROUP BY season
ORDER BY season DESC
"
```

## Risk Mitigation

### Data Quality Risks

**Risk**: Older games may have different data formats  
**Mitigation**: Process most recent season first, validate thoroughly  
**Rollback**: Keep pre-backfill snapshot

**Risk**: Scraper rate limits from NBA.com  
**Mitigation**: Implement delays between requests  
**Monitoring**: Track HTTP errors

**Risk**: BigQuery streaming buffer conflicts  
**Mitigation**: MERGE_UPDATE strategy handles duplicates  
**Validation**: Row count verification after each phase

### Processing Risks

**Risk**: Cloud Run timeouts on large batches  
**Mitigation**: Process month-by-month, not full season  
**Recovery**: Resume from last successful date

**Risk**: Out of memory errors  
**Mitigation**: 8Gi memory allocation  
**Alternative**: Process games individually if needed

## Success Criteria

### Phase Completion Metrics

✅ **Phase 1 Success**:
- 1,200+ games processed (2024-25)
- <5% missing games vs schedule
- Average 500-550 events per game
- All final scores match box scores

✅ **Phase 2 Success**:
- 2,600+ games processed (2022-24)
- <5% missing games vs schedule
- Event distribution matches current season
- Cross-validation with BigDataBall passes

✅ **Phase 3 Success**:
- 1,300+ games processed (2021-22)
- >95% schedule coverage
- Complete 4-season dataset
- All validation queries pass

### Overall Success

✅ **Complete Backfill**:
- 5,000+ total games
- 2.5M+ events
- 4 complete NBA seasons
- <5% missing games overall
- Zero critical data quality issues

## Execution Plan

### Week 1: Phase 1 (Current Season)

**Monday**: Setup and testing
- Verify scraper configuration
- Test on small date range
- Validate processing pipeline

**Tuesday-Wednesday**: Current season backfill
- Process 2024-25 regular season
- Monitor progress continuously
- Run validation after each month

**Thursday**: Validation and fixes
- Complete validation suite
- Address any issues found
- Document lessons learned

### Week 2: Phase 2 (Recent Historical)

**Monday-Tuesday**: 2023-24 season
- Process full season including playoffs
- Parallel processing with 4 jobs
- Continuous validation

**Wednesday-Thursday**: 2022-23 season
- Process full season including playoffs
- Cross-validate with existing data
- Performance optimization

### Week 3: Phase 3 (Complete Historical)

**Monday-Tuesday**: 2021-22 season
- Process full season including playoffs
- Complete validation suite
- Final data quality checks

**Wednesday**: Final validation
- Run all validation queries
- Generate complete coverage report
- Document backfill completion

**Thursday-Friday**: Documentation and handoff
- Update README with coverage stats
- Document any data quality notes
- Training on querying complete dataset

## Post-Backfill Activities

### Data Quality Report

Generate comprehensive report:

```bash
# Coverage by season
validate-nbac-pbp games --csv > coverage_report.csv

# Event type analysis
validate-nbac-pbp events --csv > event_analysis.csv

# Cross-validation results
validate-nbac-pbp players --csv > player_validation.csv

# Score integrity check
validate-nbac-pbp scores --csv > score_validation.csv
```

### Performance Optimization

1. **Clustering Review**: Adjust BigQuery clustering based on query patterns
2. **Partition Pruning**: Optimize queries for cost efficiency
3. **View Creation**: Create materialized views for common queries
4. **Index Analysis**: Add indexes if query performance is slow

### Business Enablement

1. **Model Training**: Make dataset available to data science team
2. **Dashboard Creation**: Build visualization dashboards
3. **API Integration**: Enable play-by-play data in prop analysis APIs
4. **Documentation**: Update system documentation with new capabilities

## Questions for Planning

1. **Priority**: Which season should we backfill first?
2. **Timeline**: Do we have 2-3 weeks for complete backfill?
3. **Resources**: Can we run 4 parallel Cloud Run jobs?
4. **Storage**: BigQuery quota sufficient for 2.5M+ rows?
5. **Monitoring**: Who monitors backfill progress?

## Next Steps

1. **Review this plan** with team
2. **Get approval** for Cloud Run resources
3. **Schedule backfill** window
4. **Assign monitoring** responsibilities
5. **Run Phase 1** test on small date range
6. **Begin full backfill** when validated

---

**Recommendation**: Start with Phase 1 (current season) to provide immediate business value, then proceed with historical data if successful.

**Timeline**: 3 weeks total with proper validation and monitoring.

**Cost**: ~$15 one-time + $0.50/month ongoing.

**Risk**: LOW - Processor proven, data available, infrastructure ready.
