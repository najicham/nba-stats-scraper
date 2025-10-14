# NBA.com Player Movement - Validation Queries

## Overview

Validation queries for NBA.com Player Movement transactions (signings, waives, trades, contract conversions).

**Data Source:** NBA.com Player Movement API  
**Table:** `nba-props-platform.nba_raw.nbac_player_movement`  
**Coverage:** January 2021 - Present (4,457+ transactions)  
**Update Frequency:** Daily (cumulative file with 10 years of data)  
**Processing Strategy:** INSERT_NEW_ONLY (only new transactions inserted)

### Data Characteristics

- **Transaction Types:**
  - Signing: ~47% (2,115 records) - New contracts, re-signings
  - Waive: ~31% (1,362 records) - Player releases
  - Trade: ~20% (882 records) - Multi-team transactions with draft picks
  - ContractConverted: ~1.6% (73 records) - Two-way to standard
  - AwardOnWaivers: ~0.6% (25 records) - Waiver claims

- **Unique Challenges:**
  - Cumulative source (10 years in one JSON file)
  - Multi-part trades (2-8 transaction parts per trade)
  - Seasonal activity patterns (Free Agency vs Playoffs)
  - Non-player transactions (draft picks, cash considerations)

---

## Quick Start

### Using CLI Tool (Recommended)

```bash
# Run all checks with summary
validate-player-movement

# Individual checks
validate-player-movement completeness
validate-player-movement trades
validate-player-movement freshness
validate-player-movement quality

# Export to CSV
validate-player-movement completeness --csv

# Save to BigQuery table
validate-player-movement quality --table nba_validation.player_movement_quality_check
```

### Direct BigQuery Execution

```bash
# Season completeness
bq query --use_legacy_sql=false < validation/queries/raw/nbac_player_movement/season_completeness_check.sql

# Trade validation
bq query --use_legacy_sql=false < validation/queries/raw/nbac_player_movement/trade_validation.sql
```

---

## Query Descriptions

### 1. season_completeness_check.sql
**Purpose:** Season-by-season validation of transaction volumes by team  
**When to run:** After backfills or monthly  
**Expected results:**
- DIAGNOSTICS row shows 0 for null_season, null_team
- Each season: 600-1,100 total transactions
- All 30 teams appear each season
- Transaction distribution: ~47% Signing, ~31% Waive, ~20% Trade

**Status Indicators:**
- ✅ Normal range (500-1,200 transactions per season)
- ⚠️ Low volume (<500 transactions)
- ⚠️ High volume (>1,200 transactions)
- ❌ No transactions (team missing)

### 2. trade_validation.sql
**Purpose:** Validate multi-part trades are complete (no orphaned trade parts)  
**When to run:** After backfills or when investigating data quality  
**Expected results:**
- All trades have 2+ teams involved
- Most trades are 2-team (simple trades)
- 3+ team trades are rare but valid
- No single-team trades (orphaned parts)

**Status Indicators:**
- ✅ All trades complete (no orphaned parts)
- ⚠️ Has orphaned trades (investigate)
- ❌ Only 1 team - incomplete trade

**Trade Complexity:**
- 2 teams: ~80% of trades (simple player swaps)
- 3 teams: ~15% of trades (complex deals)
- 4+ teams: ~5% of trades (blockbuster trades)

### 3. team_activity_check.sql
**Purpose:** Verify all 30 teams have reasonable transaction activity  
**When to run:** Monthly or when investigating specific teams  
**Expected results:**
- All 30 teams present in current season
- Most teams: 10-40 transactions per season
- Active teams during Free Agency/Trade Deadline

**Status Indicators:**
- ✅ Active (10+ transactions)
- 🟡 Low (5-9 transactions)
- ⚠️ Very low (<5 transactions)
- ❌ No data (team missing entirely)

**Recency Notes:**
- Recent: Transaction within 90 days
- 90+ days old during active periods (July, August, February): ⚠️ Flag for investigation
- 180+ days old: Normal during off-season

### 4. data_quality_checks.sql
**Purpose:** Comprehensive data quality validation  
**When to run:** After backfills or when investigating data issues  
**Checks performed:**
1. **NULL Values:** Required fields should never be NULL
2. **Duplicates:** Primary key uniqueness (INSERT_NEW_ONLY should prevent)
3. **Player Flags:** `is_player_transaction` consistency with `player_id`
4. **Freshness:** Recent transaction activity

**Expected results:**
- ✅ No NULLs in required fields
- ✅ No duplicate primary keys
- ✅ Flag consistency (player transactions have player_id != 0)
- ✅ Recent activity (context-dependent)

### 5. recent_activity_check.sql
**Purpose:** View transaction activity in last 30 days  
**When to run:** Weekly or when monitoring current season  
**Seasonal context:**
- **Free Agency (July-August):** Expect daily activity, many signings
- **Trade Deadline (February):** Expect frequent updates, many trades
- **Playoffs (May-June):** Minimal activity is NORMAL
- **Regular Season:** Low activity is NORMAL

**Output sections:**
1. **CONTEXT:** Current period and activity summary
2. **DAILY:** Day-by-day breakdown of last 30 days
3. **TEAMS:** Team-by-team activity summary

### 6. scraper_freshness_check.sql ⭐ CRITICAL
**Purpose:** Monitor scraper health with seasonal awareness  
**When to run:** Daily (automated monitoring)  
**Unique challenge:** Cumulative source means "no new records" can be normal

**Freshness indicators tracked:**
- `most_recent_transaction_date`: Latest transaction in NBA data
- `most_recent_scrape_timestamp`: When NBA.com generated the file
- `most_recent_insert_timestamp`: When we last inserted records
- `inserts_last_24h/72h`: Processor activity

**Status interpretation:**
- ✅ Recent activity - Data fresh for this season
- ⚪ Normal quiet period - Expected during playoffs/regular season
- 🟡 Worth checking - Borderline based on season
- ⚠️ Old during active period - Investigate immediately
- ❌ CRITICAL - No updates during Free Agency/Trade Deadline
- 🔴 WARNING - Very stale data (>90 days)

**Alert thresholds (context-aware):**
- Free Agency (July-August): Alert if >3 days old
- Trade Deadline (February): Alert if >7 days old
- Other periods: Alert if >30 days old

### 7. transaction_type_distribution.sql
**Purpose:** Verify transaction type ratios match expectations  
**When to run:** Monthly to detect data quality issues  
**Expected distribution:**
- Signing: 47.5% (most common)
- Waive: 30.6% (releases)
- Trade: 19.8% (includes multi-part)
- ContractConverted: 1.6% (two-way conversions)
- AwardOnWaivers: 0.6% (waiver claims)

**Status indicators:**
- ✅ Normal (within ±5% of expected)
- 🟡 Slight variance (±5-10%)
- ⚠️ Significant variance (>10%)

---

## Common Validation Workflows

### Daily Morning Check (Automated)
```bash
# Check scraper health and recent activity
validate-player-movement freshness
validate-player-movement recent
```

**Expected during Free Agency (July-August):**
- ✅ Scraper ran in last 24h
- ✅ New transactions found yesterday
- Status: "Recent activity"

**Expected during Playoffs (May-June):**
- 🟡 No inserts in 24h (may be normal)
- ⚪ Normal quiet period
- Status: "Minimal activity is NORMAL"

### After Backfill Validation
```bash
# Run complete validation suite
validate-player-movement completeness
validate-player-movement trades
validate-player-movement quality
validate-player-movement distribution
```

**What to check:**
1. All seasons present (2021-2024+)
2. All 30 teams in each season
3. No orphaned trades
4. No duplicate primary keys
5. Transaction ratios match expectations

### Investigating Missing Data
```bash
# Check team activity for specific teams
validate-player-movement teams

# Validate trades for orphaned parts
validate-player-movement trades

# Check data quality issues
validate-player-movement quality
```

### Monthly Health Check
```bash
# Complete monthly validation
validate-player-movement completeness
validate-player-movement distribution
validate-player-movement teams
```

---

## Troubleshooting

### Issue: "No transactions in last 30 days"

**Context matters:**
- **During Free Agency (July-August):** 🔴 CRITICAL - Scraper likely broken
- **During Playoffs (May-June):** ⚪ NORMAL - Minimal activity expected
- **During Regular Season:** 🟡 May be normal, but worth checking

**Actions:**
1. Check `scraper_freshness_check.sql` for scraper health
2. Verify scraper is running: Check processor logs
3. If broken during active period: Immediate investigation needed

### Issue: "Orphaned trade parts detected"

**Likely causes:**
1. Multi-team trade not fully scraped
2. NBA.com API returned partial data
3. Processing error during trade parsing

**Actions:**
1. Run `trade_validation.sql` to identify specific trades
2. Check source JSON file for complete trade data
3. Re-run processor on affected dates
4. Verify trade parts in NBA.com official transaction log

### Issue: "Team has 0 transactions this season"

**Likely causes:**
1. Team abbreviation mismatch (rare)
2. Data not fully backfilled
3. Processor filtering error

**Actions:**
1. Check `team_activity_check.sql` for all missing teams
2. Verify team abbreviation mapping in processor
3. Check source data has transactions for this team
4. Re-run backfill for affected season

### Issue: "Duplicate primary keys detected"

**Critical issue:** INSERT_NEW_ONLY strategy failed

**Actions:**
1. Run `data_quality_checks.sql` to identify duplicates
2. Check processor logic for existing record detection
3. Verify BigQuery INSERT errors in logs
4. Deduplicate table if needed (manual cleanup)

### Issue: "Transaction distribution significantly off"

**Expected:** Signing 47%, Waive 31%, Trade 20%

**If significantly different:**
1. Check if filtering logic changed (e.g., only trades scraped)
2. Verify seasonal patterns (Free Agency = more signings)
3. Compare to historical distribution by season
4. Investigate source data completeness

---

## Data Quality Metrics

### Expected Coverage
- **Seasons:** 2021-22 through current (4+ seasons)
- **Teams:** All 30 NBA teams every season
- **Transactions per season:** 600-1,100 total
- **Players per season:** 400-580 unique players
- **Trade frequency:** ~140-200 trades per season

### Known Limitations
1. **Cumulative source:** Can't detect if scraper ran with 0 new data
2. **Seasonal patterns:** Activity varies dramatically by time of year
3. **Trade complexity:** Multi-team trades require careful validation
4. **Non-player transactions:** ~6% of records are draft picks/cash

### Data Quality Standards
- **NULL values:** 0% tolerance in required fields
- **Duplicate keys:** 0% tolerance (INSERT_NEW_ONLY)
- **Team coverage:** 100% (all 30 teams)
- **Trade completeness:** >99% (rare orphaned parts acceptable if trade cancelled)
- **Freshness (active period):** <3 days during Free Agency

---

## Related Tables

- **nba_raw.nbac_player_list_current** - Current player-team assignments
- **nba_raw.odds_api_player_points_props** - Historical prop betting context
- **nba_raw.nbac_gamebook_player_stats** - Game-by-game player team validation
- **nba_raw.bdl_player_boxscores** - Cross-validation of player performance

---

## Additional Resources

- **Processor Code:** `data_processors/raw/nbacom/nbac_player_movement_processor.py`
- **Scraper Code:** `scrapers/nba_com/nbac_player_movement.py`
- **Validation Master Guide:** `validation/NBA_DATA_VALIDATION_MASTER_GUIDE.md`
- **Processor Monitoring Ideas:** See processor monitoring architecture document

---

## Contact

For questions about validation queries or data quality issues, see the validation master guide or check existing processor documentation.

**Last Updated:** October 13, 2025  
**Pattern:** Pattern 3 (Single Event per Key) with unique trade grouping  
**Status:** Production Ready
