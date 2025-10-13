# BettingPros Player Props Validation

Complete validation suite for monitoring BettingPros player points props data quality across 4 NBA seasons.

## 📊 Data Overview

**Table**: `nba-props-platform.nba_raw.bettingpros_player_points_props`

**Coverage**:
- **Date Range**: October 19, 2021 → June 22, 2025 (839 dates)
- **Total Records**: 2,179,496 props across 4 complete seasons
- **Players**: 665 unique players with props
- **Bookmakers**: 20 active sportsbooks
- **Schedule Coverage**: 95.8% (632/660 scheduled dates)

**Unique Characteristics**:
- **Validation Confidence Scoring**: 0.95 (recent), 0.3 (medium), 0.1 (historical)
- **Multiple Bookmakers**: 20 sportsbooks including DraftKings, FanDuel, BetMGM, Caesars
- **Date-Based Joins**: No game_id field - joins on game_date + team
- **Variable Coverage**: 30-240+ props per game depending on bookmaker participation

## 🎯 Pattern Classification

**Pattern 1: Game-Based (Multiple Records per Game)**
- Multiple bookmakers × 2 bet sides (over/under) × variable players
- Similar to Odds API Game Lines structure
- Regular season: 3,500-8,000 records/day (multiple games)
- Playoffs: 700-850 records/game (focused coverage)

## 🚀 Quick Start

### Installation

```bash
# 1. Create validation directory
mkdir -p validation/queries/raw/bettingpros_player_props

# 2. Copy all SQL files to the directory
cp season_completeness_check.sql validation/queries/raw/bettingpros_player_props/
cp daily_check_yesterday.sql validation/queries/raw/bettingpros_player_props/
cp find_missing_games.sql validation/queries/raw/bettingpros_player_props/
cp confidence_score_monitoring.sql validation/queries/raw/bettingpros_player_props/
cp bookmaker_coverage_analysis.sql validation/queries/raw/bettingpros_player_props/
cp verify_playoff_completeness.sql validation/queries/raw/bettingpros_player_props/
cp weekly_check_last_7_days.sql validation/queries/raw/bettingpros_player_props/

# 3. Install CLI tool
cp validate-bettingpros scripts/
chmod +x scripts/validate-bettingpros

# 4. Verify installation
./scripts/validate-bettingpros list
```

### Daily Workflow (When Season Starts)

```bash
# Morning routine - Check yesterday's collection
./scripts/validate-bettingpros yesterday

# Weekly review - Monitor trends
./scripts/validate-bettingpros week

# Monitor confidence scores
./scripts/validate-bettingpros confidence
```

### Historical Validation (One-Time)

```bash
# Verify 4 complete seasons
./scripts/validate-bettingpros completeness

# Find any missing dates
./scripts/validate-bettingpros missing

# Check playoff coverage
./scripts/validate-bettingpros playoffs

# Analyze bookmaker participation
./scripts/validate-bettingpros bookmakers
```

## 📋 Available Queries

### 1. Season Completeness Check
**File**: `season_completeness_check.sql`  
**Alias**: `completeness`, `complete`, `full`, `season`

Validates team-by-team coverage across all 4 seasons with confidence tracking.

**Expected Results**:
- Each team should have 82+ regular season games with props
- Regular season: 30-60 props per game average
- Playoffs: 40-50 props per game average
- Confidence scores should match data recency

**Run**:
```bash
./scripts/validate-bettingpros completeness
./scripts/validate-bettingpros completeness --csv  # Save to CSV
```

### 2. Daily Check Yesterday
**File**: `daily_check_yesterday.sql`  
**Alias**: `yesterday`, `daily`

Morning validation to ensure yesterday's games were captured properly.

**Expected Results**:
- All scheduled games should have props data
- High-confidence records (≥0.7) should be present
- 15-20 active bookmakers
- 30-60 props per game in regular season

**Run**:
```bash
./scripts/validate-bettingpros yesterday
```

### 3. Find Missing Games
**File**: `find_missing_games.sql`  
**Alias**: `missing`, `gaps`, `dates`

Identifies specific dates with zero or suspiciously low props coverage.

**Expected Results**:
- Empty result = perfect coverage
- Lists dates needing rescraping
- Flags dates with <50 total records

**Run**:
```bash
./scripts/validate-bettingpros missing
```

**Note**: Edit the date range in the SQL file for specific seasons:
```sql
WHERE s.game_date BETWEEN '2024-10-22' AND '2025-06-20'  -- UPDATE THIS
```

### 4. Confidence Score Monitoring
**File**: `confidence_score_monitoring.sql`  
**Alias**: `confidence`, `conf`, `scores`

**NEW** - Unique to BettingPros! Monitors validation confidence distribution.

**Confidence Meanings**:
- **0.95**: Same-day games (maximum betting relevance)
- **0.70**: Games within 1 month (high relevance)
- **0.30**: Games within 1 year (trend analysis)
- **0.10**: Games >1 year old (historical only)

**Expected Results**:
- Recent dates: 80%+ records should be 0.95 confidence
- Historical dates: 0.1-0.3 confidence is normal
- Sudden drops indicate processing timing issues

**Run**:
```bash
./scripts/validate-bettingpros confidence
```

### 5. Bookmaker Coverage Analysis
**File**: `bookmaker_coverage_analysis.sql`  
**Alias**: `bookmakers`, `books`, `sportsbooks`

**NEW** - Unique to BettingPros! Analyzes which bookmakers are providing data.

**Expected Results**:
- 15-20 active bookmakers in recent data
- DraftKings, FanDuel, BetMGM, Caesars should be consistent
- Drops in coverage indicate API issues

**Run**:
```bash
./scripts/validate-bettingpros bookmakers
```

### 6. Verify Playoff Completeness
**File**: `verify_playoff_completeness.sql`  
**Alias**: `playoffs`, `playoff`

Validates all playoff games have complete props coverage.

**Expected Results**:
- All playoff games should have data
- Finals games: 50+ props per game
- Each round should be complete

**Run**:
```bash
./scripts/validate-bettingpros playoffs
```

### 7. Weekly Check Last 7 Days
**File**: `weekly_check_last_7_days.sql`  
**Alias**: `week`, `weekly`, `7days`

Reviews coverage trends over the last week.

**Expected Results**:
- Consistent coverage across game days
- 15-20 bookmakers per day
- High confidence percentage (80%+)

**Run**:
```bash
./scripts/validate-bettingpros week
```

## 🔍 Understanding Validation Results

### Diagnostic Checks (Season Completeness)

The query outputs three sections:

**1. DIAGNOSTICS Row**:
```
row_type: DIAGNOSTICS
info1: total_dates (should be ~839)
info2: null_playoff (should be 0 - means schedule join failed)
info3: avg_confidence (0.6-0.7 is normal across all history)
info4: unique_books (should be ~20)
```

**2. CONFIDENCE Distribution**:
```
Conf=0.95: 1,087,315 records (49.9%) - Recent data
Conf=0.30: 383,782 records (17.6%) - 2024-25 season
Conf=0.10: 708,399 records (32.5%) - Historical 2021-2023
```

**3. TEAM Stats**:
```
info1: reg_games (regular season games with props)
info2: reg_avg_props (average props per game)
info3: playoff_games (playoff games with props)
info4: playoff_avg_props (playoff props per game)
```

### Status Indicators

- ✅ **Complete/Good**: Data meets expectations
- 🟡 **WARNING**: Potential issue, review recommended
- 🔴 **CRITICAL**: Data missing or severely degraded

**Common Issues**:

| Status | Meaning | Action |
|--------|---------|--------|
| ❌ No games | Team has 0 props data | Check scraper for this team |
| 🟡 Low coverage | <30 props/game | Review bookmaker participation |
| 🔴 No high-confidence | All records are historical | Check processing timing |
| ⚠️ Low bookmaker coverage | <10 bookmakers | API issues or market changes |

## 📈 Expected Metrics by Season

### Regular Season
- **Games per team**: 82 games
- **Props per game**: 30-60 (varies by bookmaker coverage)
- **Players per game**: 100-240 unique players across all games that day
- **Bookmakers**: 15-20 active sportsbooks
- **Confidence**: 0.95 for same-day, 0.1-0.3 for historical

### Playoffs
- **Games per team**: 4-28 (varies by playoff run)
- **Props per game**: 40-50 (more focused coverage)
- **Players per game**: 15-20 per game (star players)
- **Bookmakers**: 15-20 active sportsbooks
- **Confidence**: Should be 0.95 for recent playoffs

## 🔧 CLI Tool Usage

### Basic Commands
```bash
# Show help
./scripts/validate-bettingpros help

# List all queries
./scripts/validate-bettingpros list

# Run completeness check
./scripts/validate-bettingpros completeness
```

### Output Options

**Terminal Output** (default):
```bash
./scripts/validate-bettingpros yesterday
```

**Save to CSV**:
```bash
./scripts/validate-bettingpros yesterday --csv
# Creates: validation_bettingpros_daily_check_yesterday_20251013_143022.csv
```

**Save to BigQuery Table**:
```bash
./scripts/validate-bettingpros completeness --table
# Creates: nba-props-platform:validation.bettingpros_season_completeness_check_20251013
```

## 🚨 Troubleshooting

### Query Returns Empty Results

**Problem**: No rows returned from validation query.

**Solutions**:
1. Check date range in SQL file matches your data
2. Verify table name: `nba-props-platform.nba_raw.bettingpros_player_points_props`
3. Run discovery query to confirm data exists:
```bash
bq query --use_legacy_sql=false '
SELECT MIN(game_date), MAX(game_date), COUNT(*) 
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
'
```

### High Percentage of Low Confidence

**Problem**: Most records show 0.1 or 0.3 confidence.

**Explanation**: This is NORMAL for historical data. BettingPros uses freshness-based confidence:
- Data >1 year old = 0.1 confidence (historical analysis only)
- Data within 1 year = 0.3 confidence (trend analysis)
- Recent/same-day = 0.7-0.95 confidence (betting relevance)

**Action**: Focus validation on high-confidence data (≥0.7) for daily operations.

### Missing Dates Detected

**Problem**: Season completeness shows games without props.

**Solutions**:
1. Run `find_missing_games.sql` to get specific dates
2. Check if scraper ran on those dates
3. Re-run scraper for missing dates
4. Verify in GCS: `gs://nba-scraped-data/bettingpros/player-props/points/`

### Low Bookmaker Coverage

**Problem**: Fewer than 10 bookmakers per day.

**Possible Causes**:
- API rate limits or throttling
- Bookmaker markets closed
- BettingPros source data issues
- Scraper configuration problems

**Action**: Run `bookmaker_coverage_analysis.sql` to see which books are missing.

## 📊 Cross-Validation with Other Sources

BettingPros data should be compared with:

### Odds API Player Props
```sql
-- Compare line coverage
SELECT 
  o.game_date,
  COUNT(DISTINCT o.player_lookup) as odds_api_players,
  COUNT(DISTINCT b.player_lookup) as bettingpros_players
FROM `nba-props-platform.nba_raw.odds_api_player_points_props` o
FULL OUTER JOIN `nba-props-platform.nba_raw.bettingpros_player_points_props` b
  ON o.game_date = b.game_date
WHERE o.game_date >= '2024-10-22'
GROUP BY o.game_date
ORDER BY o.game_date DESC;
```

### Expected Differences
- **Player Coverage**: BettingPros may have more players (20 bookmakers vs 2-3 in Odds API)
- **Lines**: Different bookmakers = different line values
- **Timing**: BettingPros captures ~2 hours before tipoff (single snapshot)

## 🔐 BigQuery Partition Requirements

**CRITICAL**: All queries MUST include game_date filter for partition elimination.

```sql
-- ✅ CORRECT
WHERE game_date >= '2024-10-22'

-- ❌ WRONG - Will be slow and expensive
WHERE player_lookup = 'lebronjames'
```

All validation queries already include proper partition filters.

## 📅 Maintenance Schedule

### Daily (During Season)
- Run `yesterday` check every morning
- Alert on ❌ or 🔴 status

### Weekly
- Run `week` check to monitor trends
- Review confidence scores
- Check bookmaker participation

### Monthly
- Run full `completeness` check
- Verify bookmaker coverage hasn't dropped
- Review any low-coverage games

### Post-Season
- Run `playoffs` verification
- Archive validation results
- Update date ranges for next season

## 🎓 Key Learnings from BettingPros Data

### Confidence Scoring is Business-Critical
- Don't treat all records equally
- Filter for high-confidence (≥0.7) in daily operations
- Historical low-confidence data is still valuable for analysis

### Bookmaker Coverage Varies
- Not all 20 bookmakers appear in every game
- Coverage increases for high-profile games
- Playoff games have more consistent coverage

### No Game ID Field
- Join on game_date + team matching
- Can't cross-validate individual games as precisely
- Date-level validation is sufficient

### Variable Record Counts
- Regular season: 3,500-8,000 records per day (multiple games)
- Playoffs: 700-850 records per game
- This is NORMAL - don't flag as missing

## 📞 Support

### Issues?
1. Check troubleshooting section above
2. Review query comments for expected results
3. Run discovery queries to understand your data
4. Verify date ranges match your backfill

### Extending Validation
To add new queries:
1. Create SQL file in `validation/queries/raw/bettingpros_player_props/`
2. Add command alias to `validate-bettingpros` CLI tool
3. Update this README with query documentation
4. Test with `--csv` output first

---

**Last Updated**: October 13, 2025  
**Data Coverage**: October 2021 - June 2025 (4 complete seasons)  
**Total Records**: 2,179,496 props across 839 dates  
**Status**: ✅ Production Ready