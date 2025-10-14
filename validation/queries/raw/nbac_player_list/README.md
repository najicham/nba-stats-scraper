# NBA.com Player List Validation

**File:** `validation/queries/raw/nbac_player_list/README.md`

Validation queries for `nba_raw.nbac_player_list_current` - the current-state player roster table.

## Table Characteristics

**Type:** Current-state only (no historical data)
**Strategy:** MERGE_UPDATE (replaces all data daily)
**Update Frequency:** Daily + Real-time (every 2 hours during season)
**Expected Volume:** ~600 players across 30 teams

## Important: Current-State Table

⚠️ **This table does NOT contain historical data.** It only stores the current roster as of the last scraper run. Each day it gets completely replaced with the latest data.

For historical roster validation, use:
- `nba_raw.br_rosters_current` - 4 seasons of historical rosters
- `nba_raw.nbac_gamebook_player_stats` - Player-team assignments by game

## Validation Queries

### 1. Discovery Queries (Run First)

**Purpose:** Understand what data actually exists before validating

```bash
# Run these first to understand the data
bq query < discovery_date_range.sql
bq query < discovery_team_distribution.sql
bq query < discovery_duplicates.sql
```

### 2. Core Validation Queries

#### `data_freshness_check.sql`
**Purpose:** Verify player list is being updated regularly
**Schedule:** Daily at 9 AM
**Critical Checks:**
- Last update within 24 hours
- All 30 teams present
- ~390-550 active players
- No NULL team assignments

**Expected Results:**
```
✅ Fresh          - Updated within 24 hours
✅ All teams      - 30 of 30 teams
✅ Normal range   - 390-550 active players
```

#### `team_completeness_check.sql`
**Purpose:** Verify all teams present with reasonable player counts
**Schedule:** Daily or weekly
**Critical Checks:**
- All 30 teams present
- Each team has 13-17 active players (typical)
- No teams with <10 or >20 players

**Expected Results:**
```
✅ Complete       - 30 teams found
✅ Normal         - 13-17 players per team
```

#### `data_quality_check.sql`
**Purpose:** Comprehensive data integrity validation
**Schedule:** Daily
**Critical Checks:**
- No duplicate player_lookup (primary key)
- No NULL critical fields
- Valid team abbreviations (3 letters)
- Reasonable dates and values

**Expected Results:**
```
✅ Pass          - All quality checks passed
0                - Duplicate player_lookup
0                - NULL critical fields
```

#### `cross_validate_with_bdl.sql`
**Purpose:** Compare against Ball Don't Lie active players
**Schedule:** Weekly
**Critical Checks:**
- ~60-70% overlap between sources (expected)
- Team assignments match ~90%
- Identify recent trades/roster moves

**Expected Results:**
```
✅ Good overlap   - 60-70% in both sources
✅ Excellent      - 90%+ teams match
✅ Normal         - 5-10% team mismatches
```

#### `daily_check_yesterday.sql`
**Purpose:** Quick daily health check
**Schedule:** Every morning at 9 AM
**Critical Checks:**
- Data updated in last 24 hours
- All teams present
- Player counts reasonable

**Expected Results:**
```
✅ Updated                      - Last update < 24 hours
✅ All systems operational     - No critical issues
```

#### `player_distribution_check.sql`
**Purpose:** Analyze roster composition and distributions
**Schedule:** Weekly
**Insights:**
- Position distribution (PG, SG, SF, PF, C)
- Experience level distribution (rookies to veterans)
- Draft year distribution
- Roster status categories

## Quick Start

### Daily Monitoring
```bash
# Run every morning at 9 AM
bq query < daily_check_yesterday.sql

# If issues detected, run detailed checks
bq query < data_freshness_check.sql
bq query < team_completeness_check.sql
bq query < data_quality_check.sql
```

### Weekly Review
```bash
# Full validation suite
bq query < data_freshness_check.sql
bq query < team_completeness_check.sql
bq query < data_quality_check.sql
bq query < cross_validate_with_bdl.sql
bq query < player_distribution_check.sql
```

## Alert Thresholds

### Critical (Immediate Action)
- ❌ Last update > 36 hours
- ❌ Missing teams (< 30)
- ❌ Duplicate player_lookup values
- ❌ NULL critical fields

### Warning (Investigation Needed)
- ⚠️ Last update 24-36 hours
- ⚠️ Active players < 390 or > 550
- ⚠️ Team with < 10 or > 20 players
- ⚠️ BDL overlap < 50%

## Expected Data Patterns

### Normal Ranges
- **Total unique players:** ~600
- **Active players:** ~390-550
- **Players per team:** 13-17 (typical)
- **Update frequency:** Every 24 hours minimum
- **BDL overlap:** 60-70%
- **Team assignment matches:** 90%+

### Position Distribution
- Each position: ~15-20% of roster
- Most common: G, F (combo positions)

### Experience Distribution
- Rookies: ~10-15%
- Young (1-3 years): ~25-30%
- Mid (4-7 years): ~25-30%
- Veterans (8+): ~25-35%

## Troubleshooting

### Data Not Updating
1. Check scraper logs: `nba_com/nbac_player_list.py`
2. Check processor status: `NbacPlayerListProcessor`
3. Verify Pub/Sub integration working
4. Check GCS bucket for recent files

### Missing Teams
1. Run `team_completeness_check.sql` to identify which teams
2. Check if team abbreviations changed (rare)
3. Verify scraper collected all teams
4. Check processor team mapping logic

### Duplicate player_lookup
1. Run `data_quality_check.sql` to find duplicates
2. Check source data from scraper
3. Investigate name normalization logic
4. Critical: Fix immediately (primary key violation)

### Low BDL Overlap
1. Check BDL data freshness (may be stale)
2. Verify both scrapers running
3. Team mismatches may indicate recent trades
4. 60-70% overlap is normal, <50% investigate

## Related Tables

- `nba_raw.bdl_active_players_current` - Cross-validation source
- `nba_raw.br_rosters_current` - Historical roster data
- `nba_raw.odds_api_player_points_props` - Props requiring player lookups
- `nba_raw.nbac_gamebook_player_stats` - Game-by-game player data

## Notes

- This is a **current-state** table - no historical seasons to validate
- MERGE_UPDATE means entire table replaced daily
- Focus on **freshness** and **quality**, not completeness across seasons
- Cross-validation with BDL is important for data integrity
- Expected ~60-70% overlap with BDL (both sources have timing differences)

## Last Updated
October 13, 2025