# File: validation/queries/raw/nbac_play_by_play/VALIDATION_GUIDE.md
# NBA.com Play-by-Play Validation - Complete Guide

## Overview

**Data Source**: NBA.com Official Play-by-Play  
**Table**: `nba_raw.nbac_play_by_play`  
**Pattern**: Pattern 3 (Single Event per Unique Key)  
**Current Coverage**: 2 games (LAL vs TOR, PHI vs NYK)  
**Future Potential**: 5,400+ games available for backfill  

## Current Status

**Production Ready**: ✅ YES (100% processing success)  
**Revenue Impact**: HIGH (Official NBA play-by-play for advanced prop analysis)  
**Data Quality**: Excellent event detail with player-team resolution  

### Coverage Stats
- **Games Processed**: 2 complete games
- **Total Events**: 1,043 play-by-play actions
- **Players Identified**: 35 unique players across both games
- **Event Types**: 16+ categories (shots, rebounds, fouls, etc.)

### Known Characteristics
- **Events Per Game**: 500-550 expected (both games within range)
- **Players Per Game**: 17-18 total (8-9 per team)
- **Periods**: 4 quarters regular, 5+ for overtime
- **Home/Away**: Accurate determination via schedule cross-reference

## Validation Queries

### 1. Game-Level Completeness Check

**Purpose**: Verify each game has reasonable event counts and player coverage

**File**: `game_level_completeness.sql`

```sql
-- ============================================================================
-- Game-Level Completeness Check
-- Purpose: Verify play-by-play games have expected event volume and player coverage
-- Pattern: Pattern 3 - Variable events per game, validate reasonable ranges
-- ============================================================================

WITH game_summary AS (
  SELECT 
    game_date,
    game_id,
    nba_game_id,
    home_team_abbr,
    away_team_abbr,
    COUNT(*) as total_events,
    COUNT(DISTINCT player_1_id) as unique_players,
    COUNT(DISTINCT CASE WHEN player_1_team_abbr = home_team_abbr THEN player_1_lookup END) as home_players,
    COUNT(DISTINCT CASE WHEN player_1_team_abbr = away_team_abbr THEN player_1_lookup END) as away_players,
    COUNT(DISTINCT period) as periods_played,
    MAX(score_home) as final_home_score,
    MAX(score_away) as final_away_score,
    COUNT(CASE WHEN shot_made IS NOT NULL THEN 1 END) as shot_events,
    COUNT(CASE WHEN event_type = 'foul' THEN 1 END) as foul_events,
    COUNT(CASE WHEN event_type = 'rebound' THEN 1 END) as rebound_events,
    MIN(event_sequence) as first_event,
    MAX(event_sequence) as last_event
  FROM `nba-props-platform.nba_raw.nbac_play_by_play`
  WHERE game_date >= '2024-01-01'  -- Partition filter required
  GROUP BY game_date, game_id, nba_game_id, home_team_abbr, away_team_abbr
)

SELECT 
  game_date,
  game_id,
  home_team_abbr || ' vs ' || away_team_abbr as matchup,
  total_events,
  unique_players,
  home_players,
  away_players,
  periods_played,
  final_home_score,
  final_away_score,
  shot_events,
  -- Validation flags
  CASE 
    WHEN total_events < 400 THEN '🔴 CRITICAL: Too few events (<400)'
    WHEN total_events < 450 THEN '⚠️ WARNING: Low event count (<450)'
    WHEN total_events > 700 THEN '⚠️ WARNING: High event count (>700, verify OT)'
    ELSE '✅ Good'
  END as event_count_status,
  CASE 
    WHEN unique_players < 15 THEN '🔴 CRITICAL: Too few players (<15)'
    WHEN unique_players < 16 THEN '⚠️ WARNING: Low player count (<16)'
    WHEN unique_players > 25 THEN '⚠️ INFO: Many players (>25, lots of rotation)'
    ELSE '✅ Good'
  END as player_coverage_status,
  CASE
    WHEN home_players < 7 THEN '⚠️ WARNING: Low home player count'
    WHEN away_players < 7 THEN '⚠️ WARNING: Low away player count'
    ELSE '✅ Good'
  END as team_coverage_status,
  CASE
    WHEN periods_played > 4 THEN '🏀 Overtime Game'
    WHEN periods_played < 4 THEN '🔴 CRITICAL: Incomplete game (<4 periods)'
    ELSE '✅ Regulation'
  END as period_status
FROM game_summary
ORDER BY game_date DESC;
```

**Expected Results**:
- **Event Count**: 450-600 for regulation, 500-700+ for OT games
- **Players**: 15-20 unique players (7-10 per team)
- **Periods**: 4 for regulation, 5+ for overtime
- **Shots**: ~200-250 shot attempts per game

---

### 2. Missing Games Detection

**Purpose**: Find scheduled games without play-by-play data

**File**: `find_missing_games.sql`

```sql
-- ============================================================================
-- Find Missing Play-by-Play Games
-- Purpose: Identify scheduled games that lack play-by-play data
-- Cross-validates against schedule to find collection gaps
-- ============================================================================

WITH scheduled_games AS (
  SELECT DISTINCT
    s.game_id as schedule_game_id,
    s.game_date,
    s.home_team_tricode,
    s.away_team_tricode,
    s.game_status_text
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  WHERE s.game_date >= '2024-01-01'  -- Partition filter
    AND s.is_playoffs = FALSE
    AND s.is_all_star = FALSE
    AND s.game_status_text IN ('Final', 'Completed')  -- Only completed games
),

pbp_games AS (
  SELECT DISTINCT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr,
    COUNT(*) as event_count
  FROM `nba-props-platform.nba_raw.nbac_play_by_play`
  WHERE game_date >= '2024-01-01'
  GROUP BY game_date, game_id, home_team_abbr, away_team_abbr
)

SELECT 
  s.game_date,
  FORMAT_DATE('%A', s.game_date) as day_of_week,
  s.schedule_game_id,
  s.away_team_tricode || ' @ ' || s.home_team_tricode as matchup,
  '❌ MISSING' as status
FROM scheduled_games s
LEFT JOIN pbp_games p
  ON s.game_date = p.game_date
  AND s.home_team_tricode = p.home_team_abbr
  AND s.away_team_tricode = p.away_team_abbr
WHERE p.game_id IS NULL
ORDER BY s.game_date DESC
LIMIT 100;  -- Show most recent 100 missing games
```

**What to Look For**:
- Recent missing games indicate scraper not running
- Historical gaps show backfill opportunities
- ALL games missing except your 2 test games is expected currently

---

### 3. Event Type Distribution Analysis

**Purpose**: Validate event type completeness and detect anomalies

**File**: `event_type_distribution.sql`

```sql
-- ============================================================================
-- Event Type Distribution Analysis
-- Purpose: Monitor event type coverage and detect data quality issues
-- Validates all expected event types are being captured
-- ============================================================================

WITH event_stats AS (
  SELECT 
    game_date,
    game_id,
    event_type,
    event_action_type,
    COUNT(*) as event_count,
    COUNT(CASE WHEN player_1_id IS NOT NULL THEN 1 END) as events_with_player,
    COUNT(CASE WHEN shot_made = true THEN 1 END) as shots_made,
    COUNT(CASE WHEN shot_made = false THEN 1 END) as shots_missed
  FROM `nba-props-platform.nba_raw.nbac_play_by_play`
  WHERE game_date >= '2024-01-01'
  GROUP BY game_date, game_id, event_type, event_action_type
)

SELECT 
  event_type,
  event_action_type,
  SUM(event_count) as total_events,
  COUNT(DISTINCT game_id) as games_with_event,
  ROUND(AVG(event_count), 1) as avg_per_game,
  SUM(events_with_player) as events_with_player,
  SUM(shots_made) as total_made,
  SUM(shots_missed) as total_missed,
  -- Calculate shooting percentage for shot events
  CASE 
    WHEN event_type IN ('2pt', '3pt', 'freethrow') AND (SUM(shots_made) + SUM(shots_missed)) > 0 
    THEN ROUND(100.0 * SUM(shots_made) / (SUM(shots_made) + SUM(shots_missed)), 1)
    ELSE NULL
  END as shot_pct
FROM event_stats
GROUP BY event_type, event_action_type
ORDER BY total_events DESC;
```

**Expected Event Types**:
- **Shots**: 2pt (Layup, Jump Shot, DUNK, Hook), 3pt (Jump Shot), freethrow
- **Rebounds**: offensive, defensive
- **Fouls**: personal, offensive, technical
- **Turnovers**: bad pass, lost ball, traveling, out-of-bounds
- **Administrative**: period (start/end), timeout, substitution

**Red Flags**:
- Missing core event types (2pt, 3pt, foul, rebound)
- 0% shooting accuracy (indicates shot_made parsing issue)
- Events without player_1_id for player-dependent events

---

### 4. Player Coverage Validation

**Purpose**: Verify all active players are captured in play-by-play

**File**: `player_coverage_validation.sql`

```sql
-- ============================================================================
-- Player Coverage Validation
-- Purpose: Cross-validate play-by-play players against box scores and rosters
-- Ensures all participating players have play-by-play representation
-- ============================================================================

WITH pbp_players AS (
  SELECT DISTINCT
    p.game_date,
    p.game_id,
    p.player_1_lookup,
    p.player_1_team_abbr,
    COUNT(*) as pbp_events
  FROM `nba-props-platform.nba_raw.nbac_play_by_play` p
  WHERE p.game_date >= '2024-01-01'
    AND p.player_1_id IS NOT NULL
  GROUP BY p.game_date, p.game_id, p.player_1_lookup, p.player_1_team_abbr
),

boxscore_players AS (
  SELECT DISTINCT
    b.game_date,
    b.game_id,
    b.player_lookup,
    b.team_abbr,
    b.points as actual_points
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores` b
  WHERE b.game_date >= '2024-01-01'
)

SELECT 
  b.game_date,
  b.game_id,
  b.team_abbr,
  b.player_lookup,
  b.actual_points,
  p.pbp_events,
  CASE 
    WHEN p.player_1_lookup IS NULL THEN '🔴 MISSING: No play-by-play events'
    WHEN p.pbp_events < 5 THEN '⚠️ WARNING: Very few events (<5)'
    WHEN p.pbp_events < 10 THEN '⚪ Low events (bench player likely)'
    ELSE '✅ Good coverage'
  END as coverage_status
FROM boxscore_players b
LEFT JOIN pbp_players p
  ON b.game_date = p.game_date
  AND b.game_id = p.game_id
  AND b.player_lookup = p.player_1_lookup
WHERE b.game_date >= '2024-01-01'
ORDER BY b.game_date DESC, b.team_abbr, b.actual_points DESC;
```

**What to Look For**:
- Players with 0 play-by-play events but have box score stats
- Starters should have 20+ events
- Bench players may have <10 events (normal)
- DNP players won't appear in play-by-play (expected)

---

### 5. Score Progression Validation

**Purpose**: Verify scores increase monotonically and match final results

**File**: `score_progression_validation.sql`

```sql
-- ============================================================================
-- Score Progression Validation
-- Purpose: Detect score anomalies and validate final scores match box scores
-- Ensures scoring events are processed correctly
-- ============================================================================

WITH score_progression AS (
  SELECT 
    game_date,
    game_id,
    event_sequence,
    period,
    score_home,
    score_away,
    LAG(score_home) OVER (PARTITION BY game_id ORDER BY event_sequence) as prev_home_score,
    LAG(score_away) OVER (PARTITION BY game_id ORDER BY event_sequence) as prev_away_score
  FROM `nba-props-platform.nba_raw.nbac_play_by_play`
  WHERE game_date >= '2024-01-01'
),

score_issues AS (
  SELECT 
    game_date,
    game_id,
    event_sequence,
    period,
    score_home,
    score_away,
    prev_home_score,
    prev_away_score,
    CASE 
      WHEN score_home < prev_home_score THEN '🔴 Home score decreased'
      WHEN score_away < prev_away_score THEN '🔴 Away score decreased'
      WHEN (score_home - prev_home_score) > 3 THEN '⚠️ Home score jumped >3'
      WHEN (score_away - prev_away_score) > 3 THEN '⚠️ Away score jumped >3'
      ELSE NULL
    END as issue
  FROM score_progression
  WHERE prev_home_score IS NOT NULL
),

final_scores AS (
  SELECT 
    p.game_date,
    p.game_id,
    p.home_team_abbr,
    p.away_team_abbr,
    MAX(p.score_home) as pbp_final_home,
    MAX(p.score_away) as pbp_final_away,
    b.home_team_score as box_final_home,
    b.away_team_score as box_final_away
  FROM `nba-props-platform.nba_raw.nbac_play_by_play` p
  LEFT JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
    ON p.game_id = b.game_id
    AND p.game_date = b.game_date
  WHERE p.game_date >= '2024-01-01'
  GROUP BY p.game_date, p.game_id, p.home_team_abbr, p.away_team_abbr, 
           b.home_team_score, b.away_team_score
)

-- Report score progression issues
SELECT 
  'SCORE ANOMALIES' as report_type,
  game_date,
  game_id,
  event_sequence,
  period,
  score_home,
  score_away,
  issue
FROM score_issues
WHERE issue IS NOT NULL

UNION ALL

-- Report final score mismatches
SELECT 
  'FINAL SCORE VALIDATION' as report_type,
  game_date,
  game_id,
  NULL as event_sequence,
  NULL as period,
  pbp_final_home as score_home,
  pbp_final_away as score_away,
  CASE 
    WHEN box_final_home IS NULL THEN '⚪ No box score to compare'
    WHEN pbp_final_home != box_final_home OR pbp_final_away != box_final_away 
    THEN '🔴 CRITICAL: Final scores do not match box scores'
    ELSE '✅ Final scores match'
  END as issue
FROM final_scores

ORDER BY report_type, game_date DESC, event_sequence;
```

**Critical Checks**:
- Scores should never decrease (except period transitions, but those reset)
- No score jumps >3 points (would indicate missing events)
- Final play-by-play scores must match box score totals

---

### 6. Daily Check - Yesterday's Games

**Purpose**: Quick validation of most recent data collection

**File**: `daily_check_yesterday.sql`

```sql
-- ============================================================================
-- Daily Check - Yesterday's Play-by-Play
-- Purpose: Quick validation for most recent games processed
-- Run every morning to verify yesterday's collection
-- ============================================================================

WITH yesterday_schedule AS (
  SELECT 
    COUNT(*) as scheduled_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND game_status_text IN ('Final', 'Completed')
    AND is_playoffs = FALSE
),

yesterday_pbp AS (
  SELECT 
    COUNT(DISTINCT game_id) as processed_games,
    SUM(CASE WHEN total_events >= 450 THEN 1 ELSE 0 END) as games_with_good_count,
    SUM(CASE WHEN unique_players >= 15 THEN 1 ELSE 0 END) as games_with_good_coverage
  FROM (
    SELECT 
      game_id,
      COUNT(*) as total_events,
      COUNT(DISTINCT player_1_id) as unique_players
    FROM `nba-props-platform.nba_raw.nbac_play_by_play`
    WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    GROUP BY game_id
  )
)

SELECT 
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  s.scheduled_games,
  COALESCE(p.processed_games, 0) as processed_games,
  COALESCE(p.games_with_good_count, 0) as games_with_good_count,
  COALESCE(p.games_with_good_coverage, 0) as games_with_good_coverage,
  CASE
    WHEN s.scheduled_games = 0 THEN '⚪ No games scheduled'
    WHEN COALESCE(p.processed_games, 0) = 0 THEN '🔴 CRITICAL: No play-by-play data'
    WHEN COALESCE(p.processed_games, 0) < s.scheduled_games THEN '⚠️ WARNING: Missing games'
    WHEN COALESCE(p.games_with_good_count, 0) < p.processed_games THEN '⚠️ WARNING: Some games have low event counts'
    ELSE '✅ Complete'
  END as status
FROM yesterday_schedule s
CROSS JOIN yesterday_pbp p;
```

**Expected Output**:
- **Current State**: 0 scheduled games = 0 processed (scraper not running)
- **Future State**: When scraper runs, should show scheduled = processed
- **Alert if**: Processed < Scheduled (missing games)

---

### 7. Weekly Trend Check

**Purpose**: Monitor play-by-play collection trends over past 7 days

**File**: `weekly_check_last_7_days.sql`

```sql
-- ============================================================================
-- Weekly Trend Check
-- Purpose: Monitor play-by-play data collection over past 7 days
-- Tracks daily collection consistency and identifies gaps
-- ============================================================================

SELECT 
  game_date,
  FORMAT_DATE('%A', game_date) as day_of_week,
  COUNT(DISTINCT game_id) as games_collected,
  SUM(event_count) as total_events,
  ROUND(AVG(event_count), 0) as avg_events_per_game,
  ROUND(AVG(unique_players), 1) as avg_players_per_game,
  ROUND(AVG(shot_events), 0) as avg_shots_per_game
FROM (
  SELECT 
    game_date,
    game_id,
    COUNT(*) as event_count,
    COUNT(DISTINCT player_1_id) as unique_players,
    COUNT(CASE WHEN shot_made IS NOT NULL THEN 1 END) as shot_events
  FROM `nba-props-platform.nba_raw.nbac_play_by_play`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date, game_id
)
GROUP BY game_date
ORDER BY game_date DESC;
```

**Expected Patterns**:
- Consistent collection across all game days
- 450-550 events per game average
- 17-18 players per game average
- ~220 shots per game average

---

## CLI Tool

**File**: `validate-nbac-pbp`

```bash
#!/bin/bash
# NBA.com Play-by-Play Validation CLI
# Usage: ./validate-nbac-pbp [command] [options]

set -e

QUERIES_DIR="validation/queries/raw/nbac_play_by_play"
PROJECT_ID="nba-props-platform"

# Color codes
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================================${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}🔴 $1${NC}"
}

run_query() {
    local query_file=$1
    local output_format=${2:-"pretty"}
    
    if [ ! -f "$QUERIES_DIR/$query_file" ]; then
        print_error "Query file not found: $query_file"
        exit 1
    fi
    
    if [ "$output_format" = "csv" ]; then
        bq query --use_legacy_sql=false --format=csv < "$QUERIES_DIR/$query_file"
    else
        bq query --use_legacy_sql=false --format=pretty < "$QUERIES_DIR/$query_file"
    fi
}

save_to_table() {
    local query_file=$1
    local dest_table=$2
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local table_name="${dest_table}_${timestamp}"
    
    print_header "Saving results to: ${PROJECT_ID}.nba_validation.${table_name}"
    
    bq query \
        --use_legacy_sql=false \
        --destination_table="${PROJECT_ID}.nba_validation.${table_name}" \
        --replace \
        < "$QUERIES_DIR/$query_file"
    
    print_success "Results saved to nba_validation.${table_name}"
}

# Command handlers
cmd_games() {
    print_header "NBA.com Play-by-Play: Game-Level Completeness"
    run_query "game_level_completeness.sql" "$1"
}

cmd_missing() {
    print_header "NBA.com Play-by-Play: Missing Games"
    run_query "find_missing_games.sql" "$1"
}

cmd_events() {
    print_header "NBA.com Play-by-Play: Event Type Distribution"
    run_query "event_type_distribution.sql" "$1"
}

cmd_players() {
    print_header "NBA.com Play-by-Play: Player Coverage"
    run_query "player_coverage_validation.sql" "$1"
}

cmd_scores() {
    print_header "NBA.com Play-by-Play: Score Progression"
    run_query "score_progression_validation.sql" "$1"
}

cmd_yesterday() {
    print_header "NBA.com Play-by-Play: Yesterday's Check"
    run_query "daily_check_yesterday.sql" "$1"
}

cmd_week() {
    print_header "NBA.com Play-by-Play: Last 7 Days"
    run_query "weekly_check_last_7_days.sql" "$1"
}

cmd_all() {
    print_header "NBA.com Play-by-Play: Running All Validation Checks"
    echo ""
    
    cmd_games
    echo ""
    cmd_missing
    echo ""
    cmd_events
    echo ""
    cmd_players
    echo ""
    cmd_scores
    echo ""
    cmd_yesterday
    echo ""
    cmd_week
    
    print_success "All validation checks complete!"
}

# Help text
show_help() {
    cat << EOF
NBA.com Play-by-Play Validation Tool

USAGE:
    validate-nbac-pbp <command> [options]

COMMANDS:
    games       Game-level completeness (event counts, player coverage)
    missing     Find scheduled games without play-by-play data
    events      Event type distribution analysis
    players     Player coverage validation (cross-check with box scores)
    scores      Score progression and final score validation
    yesterday   Quick check for yesterday's games
    week        7-day collection trend
    all         Run all validation checks

OPTIONS:
    --csv       Output in CSV format
    --table     Save results to BigQuery table (nba_validation dataset)

EXAMPLES:
    # Check game completeness
    validate-nbac-pbp games
    
    # Find missing games in CSV format
    validate-nbac-pbp missing --csv
    
    # Save yesterday's validation to table
    validate-nbac-pbp yesterday --table
    
    # Run all checks
    validate-nbac-pbp all

NOTES:
    - All queries require partition filter (game_date >= date)
    - Current coverage: 2 games (more coming when scraper runs)
    - Expected: 450-600 events per game, 15-20 players
    - Cross-validates against: schedule, box scores

EOF
}

# Main command dispatcher
case "${1:-help}" in
    games)      cmd_games "$2" ;;
    missing)    cmd_missing "$2" ;;
    events)     cmd_events "$2" ;;
    players)    cmd_players "$2" ;;
    scores)     cmd_scores "$2" ;;
    yesterday)  cmd_yesterday "$2" ;;
    week)       cmd_week "$2" ;;
    all)        cmd_all "$2" ;;
    help|--help|-h) show_help ;;
    *)          
        print_error "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
```

**Installation**:
```bash
chmod +x scripts/validate-nbac-pbp
```

---

## Expected Metrics

### Healthy Data Indicators

**Game-Level**:
- ✅ 450-600 events per regulation game
- ✅ 500-700+ events for overtime games
- ✅ 15-20 unique players per game
- ✅ 7-10 players per team
- ✅ 200-250 shot attempts
- ✅ 4 periods (regulation) or 5+ (OT)

**Event Distribution**:
- ✅ 2pt shots: 80-120 per game
- ✅ 3pt shots: 60-90 per game
- ✅ Free throws: 30-50 per game
- ✅ Rebounds: 80-120 per game
- ✅ Fouls: 40-60 per game

**Player Coverage**:
- ✅ Starters: 20+ events each
- ✅ Bench: 5-20 events each
- ✅ DNP: 0 events (expected)

### Red Flags

**Critical Issues** (🔴):
- Event count <400 (incomplete game)
- Players <15 (missing player data)
- Scores decrease (data corruption)
- Final scores mismatch box scores
- Scheduled games with 0 play-by-play

**Warnings** (⚠️):
- Event count 400-450 (low but possible)
- Players 15-16 (tight rotation)
- Few events for active players (<5)
- Score jumps >3 points (possible missing events)

---

## Future Enhancements

### Backfill Priority

**High Value** (5,400+ games available):
1. Current season (2024-25): ~1,200 games
2. Recent historical (2022-24): ~3,200 games  
3. Earlier seasons (2021-22): ~1,000 games

### Enhanced Validations

When more data available:
1. **Season completeness** - % of scheduled games collected
2. **Home/away accuracy** - Validate team assignments
3. **Lineup tracking** - Expected 5-man units on court
4. **Shot chart validation** - Coordinate accuracy checks
5. **Cross-source comparison** - NBA.com vs BigDataBall

### Real-Time Monitoring

- Alert when yesterday's games missing
- Slack notifications for data quality issues
- Dashboard for collection health

---

## Related Tables

**Cross-Validation Sources**:
- `nba_raw.nbac_schedule` - Game existence and home/away
- `nba_raw.bdl_player_boxscores` - Player participation and final scores
- `nba_raw.bigdataball_play_by_play` - Alternative play-by-play source
- `nba_raw.odds_api_player_points_props` - Player prop context

---

## Troubleshooting

### Issue: No data in play-by-play table
**Cause**: Scraper only runs during Late Night Recovery + Early Morning Final Check workflows  
**Solution**: Run scraper during NBA season or wait for scheduled workflows

### Issue: Home/away teams seem swapped
**Cause**: game_id format is YYYYMMDD_AWAY_HOME (away team first)  
**Solution**: Verify against schedule table - schedule has definitive home_team_tricode

### Issue: Player missing from play-by-play but in box scores
**Cause**: Player was inactive or DNP  
**Solution**: Expected - only active players appear in play-by-play

### Issue: Score progression shows decrease
**Cause**: Data corruption or period boundary event  
**Solution**: Investigate event_sequence around the issue, verify period transitions

---

## Last Updated
**Date**: October 13, 2025  
**Version**: 1.0  
**Status**: Production Ready  
**Coverage**: 2 games (LAL vs TOR, PHI vs NYK)  
**Pattern**: Pattern 3 (Single Event)
