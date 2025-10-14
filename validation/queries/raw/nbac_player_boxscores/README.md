# NBA.com Player Boxscores Validation Queries

**Status:** ✅ Production Deployed (Awaiting Season Data)  
**Processor:** NbacPlayerBoxscoreProcessor  
**Table:** `nba-props-platform.nba_raw.nbac_player_boxscores`  
**Pattern:** Pattern 3 (Game-Based Single Event) - Similar to BDL Boxscores

## ⚠️ Important: Table is Currently Empty

This validation suite is **production-ready** and waiting for NBA season data. The processor is deployed and validated, but the scraper only runs during actual NBA games. All queries are designed to:
- Handle empty table gracefully (no errors)
- Work immediately once season starts
- Provide "no data yet" messaging

## Overview

NBA.com Player Boxscores provide **official NBA statistics** for all active players in each game. This is the authoritative source of truth for player performance data and serves as the primary validation source for other box score data (BDL, ESPN).

### Key Features

**Official NBA Data:**
- Authoritative `nba_player_id` for cross-source linking
- Enhanced metrics (True Shooting %, Usage Rate, etc.) - *coming soon*
- Quarter-by-quarter breakdowns - *coming soon*
- Plus/minus ratings
- Flagrant and technical foul tracking

**Active Players Only:**
- ~30-35 players per game
- No DNP (Did Not Play) records
- No inactive players
- Starter flag for rotation analysis

**Critical Cross-Validation:**
- Primary comparison source: Ball Don't Lie (BDL) boxscores
- Should match BDL stats closely (points, rebounds, assists)
- NBA.com is source of truth when discrepancies exist

## Data Characteristics

### Expected Metrics (Once Data Arrives)

| Metric | Expected Value |
|--------|----------------|
| **Games per season** | ~1,230 (regular season) + ~250 (playoffs) |
| **Players per game** | ~30-35 active players |
| **Starters per game** | ~10 (5 per team) |
| **Coverage vs BDL** | Should match 95%+ of games |
| **Core stats accuracy** | 99%+ match with BDL points/assists/rebounds |

### Key Differences from BDL

| Feature | NBA.com | BDL |
|---------|---------|-----|
| **Source** | Official NBA | Third-party API |
| **Player ID** | `nba_player_id` (official) | `bdl_player_id` |
| **Enhanced metrics** | TS%, Usage%, PIE (planned) | Basic stats only |
| **Quarter breakdowns** | Q1-Q4, OT (planned) | Not available |
| **Plus/minus** | ✅ Available | ❌ Not available |
| **Flagrant/Technical fouls** | ✅ Available | ❌ Not available |
| **Starter flag** | ✅ Available | ❌ Not available |

## Validation Queries

### 1. season_completeness_check.sql
**Purpose:** Comprehensive season validation across all teams  
**When to run:** After backfills, weekly during season  
**What it checks:**
- Game coverage by season/team
- Player counts per game
- Starter counts (should be ~10 per game)
- Schedule join success
- NBA player ID completeness

**Expected output:**
```
DIAGNOSTICS row: Shows 0 for null values (good)
TEAM rows: ~82 regular season games per team
Status: "✅ Complete" when all checks pass
```

### 2. find_missing_games.sql
**Purpose:** Identify specific games without player boxscore data  
**When to run:** When completeness check shows missing games  
**What it checks:**
- Games in schedule but not in boxscores
- Games with suspiciously low player counts (<20)
- Direct game_id join (formats match!)

**Key advantage:** NBA.com uses same game_id format as schedule (YYYYMMDD_AWAY_HOME)

### 3. cross_validate_with_bdl.sql ⭐ **CRITICAL**
**Purpose:** Compare NBA.com official stats against BDL  
**When to run:** Daily/weekly during season  
**What it checks:**
- Points discrepancies (CRITICAL for props)
- Assists/rebounds discrepancies
- Field goals, three-pointers, free throws
- Players in one source but not the other

**Priority:**
- 🔴 **CRITICAL:** Point discrepancies >2 points
- ⚠️ **WARNING:** Any point discrepancy, major stat differences
- ✅ **Match:** All stats within acceptable range

**Important:** NBA.com is source of truth when discrepancies exist!

### 4. daily_check_yesterday.sql
**Purpose:** Morning validation that yesterday's games were captured  
**When to run:** Daily at ~9 AM (after overnight processing)  
**What it checks:**
- All scheduled games have data
- Player counts reasonable (~30-35 per game)
- Starter counts normal (~10 per game)
- Consistency with BDL

**Alerting thresholds:**
- ❌ CRITICAL: No data when games scheduled
- ⚠️ WARNING: Missing games or unusual player/starter counts

### 5. data_quality_checks.sql
**Purpose:** Validate enhanced metrics and data quality  
**When to run:** Weekly  
**What it checks:**

**Feature Availability:**
- Enhanced metrics (TS%, Usage Rate, etc.) - *currently 0%, planned*
- Quarter breakdowns - *currently 0%, planned*
- Plus/minus availability
- Technical/flagrant foul tracking

**Quality Checks:**
- NBA player ID completeness
- Starter counts per game
- Field goal percentage calculations
- Data integrity

### 6. verify_playoff_completeness.sql
**Purpose:** Ensure all playoff games captured  
**When to run:** After playoffs, or during playoffs weekly  
**What it checks:**
- Each playoff team has expected game count
- Player counts reasonable
- Starter counts normal
- Consistency with BDL playoff data

### 7. weekly_check_last_7_days.sql
**Purpose:** Weekly trends and pattern detection  
**When to run:** Monday mornings  
**What it checks:**
- Daily coverage for past week
- Day-of-week patterns
- Consistency with BDL across the week

**Use cases:**
- Spot recurring issues (e.g., Saturday games always missing)
- Verify scraper runs consistently
- Monitor week-over-week trends

## CLI Usage

```bash
# Run all validation queries
./validate-nbac-boxscores

# Run specific query
./validate-nbac-boxscores season-completeness
./validate-nbac-boxscores cross-validate-bdl
./validate-nbac-boxscores daily-check

# CSV output (for analysis)
./validate-nbac-boxscores season-completeness --csv > results.csv

# BigQuery table output (for tracking)
./validate-nbac-boxscores daily-check --table nba_processing.nbac_boxscore_validation
```

## Current Status & Timeline

### Now (Pre-Season)
- ✅ Processor deployed and validated
- ✅ All validation queries created and tested
- ⚪ Table empty (awaiting season start)
- ⚪ All queries return "No data yet" messages

### Season Start (Expected October 2024)
- 🔄 Scraper begins collecting data
- 🔄 First games processed
- 🔄 Validation queries start reporting real results
- 🔄 Daily monitoring begins

### Expected Backfill Scope
Once season starts and historical data becomes available:
- **2024-25 season:** ~1,230 regular season + playoffs
- **Historical seasons:** Potentially 2021-2025 (4 seasons)
- **Total records:** ~165,000 player-game records (matching BDL)
- **Processing time:** 90-120 minutes for full backfill

## Enhanced Features Coming Soon

Currently **NULL** but planned for future implementation:

### Advanced Metrics
- `true_shooting_pct` - True Shooting Percentage
- `effective_fg_pct` - Effective Field Goal Percentage  
- `usage_rate` - Usage Rate
- `offensive_rating` - Offensive Rating
- `defensive_rating` - Defensive Rating
- `pace` - Pace
- `pie` - Player Impact Estimate

### Quarter Breakdowns
- `points_q1` through `points_q4` - Quarter-by-quarter scoring
- `points_ot` - Overtime points

**Monitoring:** Run `data_quality_checks.sql` weekly to track when these features become available.

## Cross-Source Validation Strategy

### Primary Validation: NBA.com vs BDL

**Both sources should show:**
- Same games covered (95%+ overlap)
- Same players per game (within 1-2 players)
- Identical core stats (points, assists, rebounds)

**When discrepancies occur:**
1. NBA.com is official source of truth
2. Document discrepancy in validation log
3. Investigate if discrepancy >2 points (CRITICAL)
4. Update BDL if NBA.com data is correct

### Validation Hierarchy
1. **NBA.com** (this source) - Official, authoritative
2. **BDL** - Primary comparison, usually matches
3. **ESPN** - Backup validation when needed

## Alert Thresholds

### Critical (Immediate Action Required)
- ❌ No data for scheduled games
- 🔴 Point discrepancies >2 points vs BDL
- ❌ Multiple games missing from daily check

### Warning (Investigate Within 24 Hours)
- ⚠️ Any point discrepancy vs BDL
- ⚠️ Missing games (1-2)
- ⚠️ Unusual player/starter counts
- ⚠️ Major stat discrepancies vs BDL

### Info (Monitor)
- 🟡 Minor differences in rebounds/assists
- 🟡 Players in NBA.com but not BDL (expected)
- ⚪ Enhanced metrics not yet available

## Troubleshooting

### Query returns "No data yet"
✅ **This is normal before season starts!** Queries are designed to handle empty table gracefully.

### After season starts, still no data
1. Check scraper logs: Is it running during games?
2. Check processor logs: Are files being processed?
3. Verify GCS paths: `gs://nba-scraped-data/nba-com/player-boxscores/`
4. Run `daily_check_yesterday.sql` for detailed status

### Discrepancies with BDL
1. Run `cross_validate_with_bdl.sql`
2. NBA.com is source of truth - BDL may have errors
3. Document discrepancies >2 points
4. Investigate if pattern emerges (specific team, date range)

### Missing games
1. Run `find_missing_games.sql` for specifics
2. Check scraper logs for those dates
3. Verify games actually occurred (check schedule)
4. Create backfill plan if needed

## Related Documentation

- **Processor:** `data_processors/raw/nbacom/nbac_player_boxscore_processor.py`
- **Master Validation Guide:** `validation/NBA_DATA_VALIDATION_MASTER_GUIDE.md`
- **BDL Boxscores:** `validation/queries/raw/bdl_boxscores/` (similar pattern)
- **Pattern 3 Reference:** See Master Guide for game-based single event pattern

## Revenue Impact

**Status:** ✅ HIGH - Official NBA source for prop validation

**Business Value:**
- Authoritative prop bet settlement data
- Cross-validation for BDL accuracy
- Enhanced metrics for advanced modeling (when available)
- Official NBA player IDs for data linking

**Critical for:**
- Accurate prop outcome determination
- Detecting data quality issues in other sources
- Building trust through official NBA data
- Future multi-stat props (rebounds, assists)

---

**Last Updated:** October 13, 2025  
**Status:** Production Deployed - Awaiting Season Data  
**Maintainer:** NBA Props Data Engineering Team
