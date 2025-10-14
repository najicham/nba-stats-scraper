# Ball Don't Lie Active Players Validation

**File:** `validation/queries/raw/bdl_active_players/README.md`

Validation queries for `nba_raw.bdl_active_players_current` - the current-state active players table with built-in cross-validation.

## Table Characteristics

**Type:** Current-state only (no historical data)
**Strategy:** MERGE_UPDATE (replaces all data on each run)
**Update Frequency:** Variable (depends on scraper schedule)
**Expected Volume:** ~550-600 players across 30 teams
**NOT PARTITIONED:** No partition filters required (unlike nbac_player_list)

## Unique Feature: Built-In Validation Intelligence

⭐ **This table is special** - it contains built-in cross-validation against NBA.com during processing:

- `validation_status`: 'validated', 'missing_nba_com', 'team_mismatch', 'data_quality_issue'
- `has_validation_issues`: BOOLEAN flag
- `validation_details`: JSON string with specific issue details
- `nba_com_team_abbr`: For team comparison

**Expected validation distribution:**
- ~60% validated (both sources agree perfectly)
- ~25% missing_nba_com (G-League, two-way contracts, timing)
- ~15% team_mismatch (recent trades, roster updates)
- <5% data_quality_issue (requires investigation)

## Critical Differences from NBA.com Player List

| Feature | BDL Active Players | NBA.com Player List |
|---------|-------------------|---------------------|
| Partitioned | ❌ NO | ✅ YES (by season_year) |
| Partition Filter | ❌ Not needed | ✅ Required WHERE season_year >= 2024 |
| Validation Status | ✅ Has built-in validation | ❌ No validation fields |
| Cross-Validation | ✅ Compares with NBA.com | ❌ No comparison |
| Expected Validation Rate | 55-65% (not 100%!) | N/A |

## Validation Queries

### 1. Core Validation Queries

#### `player_count_check.sql`
**Purpose:** Verify expected player counts across teams and validation status
**Schedule:** Daily
**Critical Checks:**
- ~550-600 total players
- All 30 teams present
- 13-20 players per team (typical)
- 55-65% validation rate (healthy)

**Expected Results:**
```
✅ Expected range     - 550-600 players
✅ Complete          - 30 of 30 teams
✅ Healthy range     - 55-65% validated
```

#### `validation_status_summary.sql` ⭐ UNIQUE TO BDL
**Purpose:** Analyze validation_status distribution (BDL's special feature)
**Schedule:** Daily
**Critical Checks:**
- ~60% validated (both sources agree)
- ~25% missing_nba_com (expected - G-League, two-way)
- ~15% team_mismatch (expected - trade timing)
- <5% data_quality_issue (investigate if higher)

**Expected Results:**
```
✅ Healthy          - 55-65% validated
✅ Expected         - 20-30% missing_nba_com
✅ Normal           - 10-20% team_mismatch
✅ Minimal issues   - <5% data_quality_issue
```

#### `data_quality_check.sql`
**Purpose:** Comprehensive data integrity validation
**Schedule:** Daily
**Critical Checks:**
- No duplicate player_lookup (primary key)
- No duplicate bdl_player_id (unique constraint)
- No NULL required fields
- Valid validation_status values
- Validation logic consistency

**Expected Results:**
```
✅ Pass             - All quality checks passed
0                   - Duplicate player_lookup
0                   - Duplicate bdl_player_id
0                   - Invalid validation_status
```

#### `daily_freshness_check.sql`
**Purpose:** Daily morning health check
**Schedule:** Every morning at 9 AM
**Critical Checks:**
- Data updated in last 48 hours
- All teams present
- Player counts reasonable
- Validation rate healthy

**Expected Results:**
```
✅ Updated                      - Last update < 48 hours
✅ All systems operational     - No critical issues
```

#### `cross_validate_with_nba_com.sql`
**Purpose:** Compare BDL against NBA.com player list
**Schedule:** Weekly
**Critical Checks:**
- ~60-70% overlap between sources (expected)
- Team assignments match ~80%
- Identify players only in BDL (G-League)
- Identify players only in NBA.com (BDL delayed)

**Expected Results:**
```
✅ Good overlap      - 60-70% in both sources
✅ Excellent         - 80%+ teams match
✅ Expected          - 20-30% BDL only (G-League)
```

#### `team_mismatch_analysis.sql`
**Purpose:** Deep dive into team_mismatch cases
**Schedule:** When mismatch rate > 20%
**Insights:**
- Which teams have most mismatches
- Common trade pairs (BDL team → NBA.com team)
- Recent trade activity vs data errors

#### `missing_players_analysis.sql`
**Purpose:** Deep dive into missing_nba_com cases
**Schedule:** When missing rate > 30%
**Insights:**
- Which teams have most missing players
- Position distribution of missing players
- G-League vs truly missing players

## Quick Start

### Daily Monitoring
```bash
# Run every morning at 9 AM using CLI tool
validate-bdl-active-players daily

# If issues detected, run detailed checks
validate-bdl-active-players validation-status
validate-bdl-active-players quality
validate-bdl-active-players count
```

### Weekly Review
```bash
# Full validation suite
validate-bdl-active-players all

# OR run individual queries
validate-bdl-active-players count
validate-bdl-active-players validation-status
validate-bdl-active-players quality
validate-bdl-active-players cross-validate
```

### Investigating Issues
```bash
# High team mismatch rate (>20%)
validate-bdl-active-players team-mismatches

# High missing rate (>30%)
validate-bdl-active-players missing-players
```

## Alert Thresholds

### Critical (Immediate Action) 🔴
- ❌ Last update > 96 hours (4 days)
- ❌ Missing teams (< 30)
- ❌ Player count < 500 or > 650
- ❌ Duplicate player_lookup or bdl_player_id values
- ❌ NULL required fields
- ❌ Validation rate < 45%

### Warning (Investigation Needed) 🟡
- ⚠️ Last update 48-96 hours
- ⚠️ Player count 500-550 or 600-650
- ⚠️ Team with < 13 or > 20 players
- ⚠️ Validation rate 45-55% or 65-75%
- ⚠️ Missing from NBA.com > 40%
- ⚠️ Team mismatch rate > 30%

## Expected Data Patterns

### Normal Ranges
- **Total players:** 550-600
- **Players per team:** 13-20 (typical ~19)
- **Update frequency:** Variable (check last_seen_date)
- **Validation rate:** 55-65% (NOT 100% - this is healthy!)

### Validation Status Distribution (Healthy)
- **validated:** 55-65% (both sources agree perfectly)
- **missing_nba_com:** 20-30% (G-League, two-way, recent signings)
- **team_mismatch:** 10-20% (trades, roster timing differences)
- **data_quality_issue:** <5% (should be minimal)

### Why Validation Rate Is Not 100%

This is **EXPECTED and HEALTHY**:

1. **G-League Players (missing_nba_com)**: BDL tracks active players including G-League assignments. NBA.com may not list them if on G-League roster.

2. **Two-Way Contracts (missing_nba_com)**: Players can move between NBA and G-League. Timing differences between source updates.

3. **Trade Timing (team_mismatch)**: When a trade happens, BDL and NBA.com may update at different times (hours or days apart).

4. **Recent Signings (missing_nba_com)**: BDL may pick up new signings faster than NBA.com.

**60% validation rate = 60% of players have perfect agreement between both sources**
**40% with "issues" = Expected variance, not actual problems**

## Troubleshooting

### Data Not Updating
1. Check scraper logs: `ball_dont_lie/bdl_active_players.py`
2. Check processor status: `BdlActivePlayersProcessor`
3. Verify Pub/Sub integration working
4. Check GCS bucket for recent files

### Low Validation Rate (<45%)
1. Run `validation_status_summary.sql` to see distribution
2. Check if NBA.com player list is stale
3. Run `cross_validate_with_nba_com.sql` for details
4. Verify both scrapers are running

### High Team Mismatch Rate (>30%)
1. Run `team_mismatch_analysis.sql` for details
2. Check for recent trade deadline activity
3. Verify both sources are updating
4. Review specific team pairs with high mismatches

### High Missing Rate (>40%)
1. Run `missing_players_analysis.sql` for details
2. Check if NBA.com scraper is working
3. Review teams with most missing players
4. Look for G-League assignments vs truly missing

### Duplicate player_lookup
1. Run `data_quality_check.sql` to find duplicates
2. Check source data from scraper
3. Investigate name normalization logic
4. Critical: Fix immediately (primary key violation)

## Related Tables

- `nba_raw.nbac_player_list_current` - Cross-validation source
- `nba_raw.bdl_player_boxscores` - BDL game-by-game player data
- `nba_raw.odds_api_player_points_props` - Props requiring player lookups

## CLI Tool

See `scripts/validate-bdl-active-players` for easy command-line validation:

```bash
# Show all commands
validate-bdl-active-players --help

# Quick daily check
validate-bdl-active-players daily

# Export to CSV
validate-bdl-active-players count --csv > player_counts.csv

# Save to BigQuery table
validate-bdl-active-players quality --table nba_processing.bdl_quality_check
```

## Notes

- This is a **current-state** table - no historical data
- **NOT partitioned** - do not add partition filters to queries
- MERGE_UPDATE means entire table replaced on each run
- **Expected ~60% validation rate is HEALTHY** (not a problem!)
- Team mismatches ~15% are normal due to trade timing
- Focus on **data quality** and **freshness**, not 100% validation

## Last Updated
October 13, 2025
