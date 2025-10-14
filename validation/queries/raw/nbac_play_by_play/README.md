# File: validation/queries/raw/nbac_play_by_play/README.md
# NBA.com Play-by-Play Validation

Official NBA play-by-play events validation for advanced analytics and prop betting analysis.

## Quick Start

```bash
# Check all validation metrics
./scripts/validate-nbac-pbp all

# Check yesterday's games
./scripts/validate-nbac-pbp yesterday

# Find missing games
./scripts/validate-nbac-pbp missing
```

## Current Status

**Table**: `nba_raw.nbac_play_by_play`  
**Pattern**: Pattern 3 (Single Event)  
**Coverage**: 2 games (LAL vs TOR, PHI vs NYK)  
**Backfill Opportunity**: 5,400+ games available

### Data Characteristics

- **Events Per Game**: 500-550 (current average: 522)
- **Players Per Game**: 17-18 total (8-9 per team)
- **Event Types**: 16+ categories
- **Periods**: 4 regular quarters, 5+ for OT

## Validation Queries

| Query | Purpose | Expected Output |
|-------|---------|-----------------|
| `game_level_completeness` | Event counts & player coverage | 450-600 events, 15-20 players per game |
| `find_missing_games` | Games without play-by-play | All scheduled games except 2 test games |
| `event_type_distribution` | Event coverage analysis | 2pt, 3pt, rebounds, fouls present |
| `player_coverage_validation` | Cross-check with box scores | All active players have events |
| `score_progression_validation` | Score integrity checks | Scores increase monotonically |
| `daily_check_yesterday` | Yesterday's collection status | 0 processed (scraper not running) |
| `weekly_check_last_7_days` | 7-day collection trend | Limited data currently |

## Expected Metrics

### Healthy Game Indicators

✅ **Event Volume**:
- Regulation: 450-600 events
- Overtime: 500-700+ events

✅ **Player Coverage**:
- Total: 15-20 unique players
- Per Team: 7-10 players
- Starters: 20+ events each

✅ **Event Distribution**:
- 2pt shots: 80-120
- 3pt shots: 60-90
- Free throws: 30-50
- Rebounds: 80-120
- Fouls: 40-60

### Red Flags

🔴 **Critical Issues**:
- Event count <400 (incomplete game)
- Players <15 (missing player data)
- Scores decrease (corruption)
- Final scores ≠ box scores

⚠️ **Warnings**:
- Event count 400-450 (low but possible)
- Players 15-16 (tight rotation)
- Active players with <5 events

## CLI Tool Usage

### Basic Commands

```bash
# Game-level completeness
validate-nbac-pbp games

# Find missing games
validate-nbac-pbp missing

# Event type analysis
validate-nbac-pbp events

# Player coverage
validate-nbac-pbp players

# Score validation
validate-nbac-pbp scores

# Quick yesterday check
validate-nbac-pbp yesterday

# 7-day trend
validate-nbac-pbp week

# Run everything
validate-nbac-pbp all
```

### Output Options

```bash
# CSV format
validate-nbac-pbp games --csv > results.csv

# Save to BigQuery
validate-nbac-pbp games --table

# Both
validate-nbac-pbp games --csv --table
```

## Cross-Validation

**Schedule** (`nba_raw.nbac_schedule`):
- Game existence verification
- Home/away team determination
- Completion status

**Box Scores** (`nba_raw.bdl_player_boxscores`):
- Player participation confirmation
- Final score validation
- Points scoring verification

**BigDataBall** (`nba_raw.bigdataball_play_by_play`):
- Alternative play-by-play source
- Event coverage comparison
- Data quality cross-check

## Known Issues & Limitations

### Limited Coverage
**Issue**: Only 2 games currently processed  
**Cause**: Scraper runs during Late Night Recovery + Early Morning Final Check workflows  
**Solution**: Normal - will expand during NBA season

### Home/Away Accuracy
**Issue**: Requires schedule cross-reference  
**Status**: ✅ Working correctly  
**Validation**: game_id format is YYYYMMDD_AWAY_HOME

### Missing Historical Data
**Issue**: No 2021-2024 data yet  
**Opportunity**: 5,400+ games available for backfill  
**Action**: Run scraper on historical dates when needed

## Future Enhancements

### Phase 1: Historical Backfill
- Current season (2024-25): ~1,200 games
- Recent seasons (2022-24): ~3,200 games
- Earlier seasons (2021-22): ~1,000 games

### Phase 2: Advanced Validations
- Season completeness metrics
- Lineup tracking validation
- Shot chart accuracy checks
- Cross-source comparison dashboards

### Phase 3: Real-Time Monitoring
- Slack alerts for missing games
- Daily email summaries
- Grafana dashboards

## Troubleshooting

### No Data Available
**Problem**: Queries return empty results  
**Solution**: Expected - scraper only runs during NBA season workflows

### Score Mismatch with Box Scores
**Problem**: Final scores don't match  
**Debug**: Run `score_progression_validation.sql` to find anomalies  
**Action**: Investigate event_sequence around score issues

### Player Missing from Play-by-Play
**Problem**: Player in box scores but not in play-by-play  
**Cause**: Player was DNP or inactive  
**Solution**: Expected behavior - only active players appear

### Home/Away Teams Seem Wrong
**Problem**: Team assignments don't match expectations  
**Validation**: Cross-check with `nbac_schedule` table  
**Note**: game_id format is AWAY_HOME (away team first)

## Data Quality Checks

Run these queries regularly:

```bash
# Morning routine (after games complete)
validate-nbac-pbp yesterday

# Weekly review
validate-nbac-pbp week
validate-nbac-pbp missing

# Before backfill
validate-nbac-pbp games --csv > pre_backfill.csv

# After backfill
validate-nbac-pbp games --csv > post_backfill.csv
diff pre_backfill.csv post_backfill.csv
```

## Production Checklist

Before using play-by-play data for revenue operations:

- [ ] Verify event counts in expected range (450-600)
- [ ] Confirm player coverage >15 per game
- [ ] Validate final scores match box scores
- [ ] Check score progression has no anomalies
- [ ] Cross-reference with schedule for accuracy
- [ ] Test player lookup joins with props data
- [ ] Verify overtime games handled correctly

## Support

**Documentation**: See `NBA_DATA_VALIDATION_MASTER_GUIDE.md`  
**Pattern Reference**: Pattern 3 (Single Event)  
**Chat History**: See chat a12b4e63-6577-4370-8f98-8a73f9bee8ac (BDL box scores - similar pattern)

## Last Updated

**Date**: October 13, 2025  
**Version**: 1.0  
**Status**: Production Ready  
**Next Review**: When NBA season starts
