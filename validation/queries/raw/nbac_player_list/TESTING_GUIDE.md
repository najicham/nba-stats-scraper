# NBA.com Player List Validation - Testing Guide

**File:** `validation/queries/raw/nbac_player_list/TESTING_GUIDE.md`

Step-by-step guide for testing the validation queries.

## Prerequisites

Before testing:
- [ ] All query files saved in `validation/queries/raw/nbac_player_list/`
- [ ] CLI tool installed and executable
- [ ] BigQuery access working (`bq ls` succeeds)
- [ ] `jq` installed for CLI tool

## Testing Phase 1: Discovery (MANDATORY FIRST STEP!)

### Test 1.1: Date Range & Volume

**Purpose:** Understand what data exists in the table

```bash
cd ~/code/nba-stats-scraper
bq query --use_legacy_sql=false < validation/queries/raw/nbac_player_list/discovery_date_range.sql
```

**Expected Results:**
```
earliest_seen:       2024-XX-XX (or earlier)
latest_seen:         2025-10-13 (today or yesterday)
last_processed_timestamp: Recent timestamp
total_records:       ~600
unique_players:      ~600
unique_teams:        30
active_players:      ~390-550
null_teams:          0
```

**Red Flags:**
- ❌ `latest_seen` more than 2 days old → Data not updating!
- ❌ `unique_teams` ≠ 30 → Missing teams
- ❌ `null_teams` > 0 → Data quality issue
- ❌ `active_players` < 300 or > 700 → Unusual

**Action if failing:** Stop and investigate data source before continuing

---

### Test 1.2: Team Distribution

**Purpose:** Verify all 30 teams with reasonable player counts

```bash
bq query --use_legacy_sql=false < validation/queries/raw/nbac_player_list/discovery_team_distribution.sql
```

**Expected Results:**
- 30 rows (one per team)
- Each team: 13-17 total_players (typical)
- Each team: 13-17 active_players
- Recent `newest_update` dates (last 24 hours)

**Red Flags:**
- ❌ < 30 teams → Missing teams!
- ❌ Any team with < 10 or > 20 players → Investigate
- ❌ Old `newest_update` → Specific team not updating

---

### Test 1.3: Duplicate Detection

**Purpose:** Check for primary key violations

```bash
bq query --use_legacy_sql=false < validation/queries/raw/nbac_player_list/discovery_duplicates.sql
```

**Expected Results:**
```
(Zero rows returned)
```

**If you see ANY rows:**
- 🚨 **CRITICAL**: Primary key violation!
- Must be fixed before proceeding
- Check processor deduplication logic

---

## Testing Phase 2: Validation Queries

### Test 2.1: Data Freshness Check

```bash
./scripts/validate-player-list freshness
```

**Expected Output:**
```
✅ Fresh              - Updated within 24 hours
✅ All teams present  - 30 of 30 teams
✅ Normal range       - 390-550 active players
✅ No NULL teams      - 0 NULL teams
```

**What it checks:**
- Data updated in last 24 hours
- All 30 teams present
- Active player count reasonable
- No NULL team assignments

**Pass criteria:**
- All checks show ✅
- hours_since_update < 24
- unique_teams = 30

---

### Test 2.2: Team Completeness Check

```bash
./scripts/validate-player-list teams
```

**Expected Output:**
```
=== LEAGUE SUMMARY ===
Teams Found          30        Expected: 30    ✅ Complete
Active Players       456       Avg: 15.2       

=== TEAM DETAILS ===
ATL    15 active    1 inactive    5 positions    ✅ Normal
BOS    16 active    2 inactive    5 positions    ✅ Normal
[... all 30 teams ...]
```

**What it checks:**
- All 30 teams present
- Each team has 13-17 players (typical)
- Position distribution reasonable

**Pass criteria:**
- 30 teams found
- All teams show ✅ Normal
- No teams with < 10 or > 20 players

---

### Test 2.3: Data Quality Check

```bash
./scripts/validate-player-list quality
```

**Expected Output:**
```
=== PRIMARY KEY VALIDATION ===
Duplicate player_lookup    0    ✅ Pass
Duplicate player_id        0    ✅ Pass

=== NULL FIELD CHECKS ===
NULL player_lookup         0    ✅ Pass
NULL team_abbr            0    ✅ Pass
NULL is_active            0    ✅ Pass

=== DATA VALIDATION ===
Invalid team_abbr         0    ✅ Pass
Invalid season_year       0    ✅ Pass
Future dates              0    ✅ Pass

=== SUMMARY ===
Overall Status                 ✅ All checks passed
```

**What it checks:**
- No duplicate player_lookup (primary key)
- No NULL critical fields
- Valid team abbreviations
- Reasonable dates and values

**Pass criteria:**
- All checks show 0 issues
- Overall status: ✅ All checks passed

**If failures:**
- Any duplicates → CRITICAL - fix immediately
- NULL fields → Investigate data quality
- Invalid values → Check processor logic

---

### Test 2.4: Cross-Validation with BDL

```bash
./scripts/validate-player-list bdl-comparison
```

**Expected Output:**
```
=== VALIDATION SUMMARY ===
Total Unique Players       650
In Both Sources           420    64.6%    ✅ Good overlap
NBA.com Only              150    23.1%    ✅ Expected
BDL Only                   80    12.3%    ✅ Expected

=== TEAM MATCHING ===
Teams Match               380    90.5%    ✅ Excellent
Team Mismatches            40     9.5%    ✅ Normal
```

**What it checks:**
- Overlap between NBA.com and Ball Don't Lie
- Team assignment consistency
- Identifies recent trades/roster moves

**Pass criteria:**
- 60-70% in both sources (good overlap)
- 90%+ teams match among shared players
- 5-10% team mismatches normal

**Expected patterns:**
- NBA.com has more comprehensive data
- BDL may have timing differences
- Team mismatches often indicate trades

---

### Test 2.5: Daily Check

```bash
./scripts/validate-player-list daily
```

**Expected Output:**
```
=== UPDATE STATUS ===
Last Update           2025-10-13    0 days ago    ✅ Updated
Last Processed        3 hours ago

=== DATA COMPLETENESS ===
Teams                 30 of 30                    ✅ All teams present
Active Players        456           ~390-550      ✅ Normal range

=== OVERALL STATUS ===
Daily Check Result                               ✅ All systems operational
```

**What it checks:**
- Quick health check for daily monitoring
- Data freshness, teams, player counts

**Pass criteria:**
- Last update < 24 hours
- 30 teams
- Active players in range

---

### Test 2.6: Player Distribution

```bash
./scripts/validate-player-list distribution
```

**Expected Output:**
```
=== POSITION DISTRIBUTION ===
G          180    30.0%
F          150    25.0%
C           90    15.0%
[etc...]

=== EXPERIENCE DISTRIBUTION ===
Rookies (0 years)      60    10.0%
Young (1-3 years)     180    30.0%
Mid (4-7 years)       180    30.0%
Veteran (8-12 years)  120    20.0%
Senior (13+ years)     60    10.0%
```

**What it checks:**
- Position distribution reasonable
- Experience levels balanced
- Draft year distribution

**Pass criteria:**
- No single position > 40%
- Balanced experience distribution
- Multiple draft years represented

---

## Testing Phase 3: CLI Tool Features

### Test 3.1: CSV Output

```bash
./scripts/validate-player-list teams --csv > teams_check.csv
cat teams_check.csv
```

**Expected:** CSV formatted output suitable for Excel/Google Sheets

---

### Test 3.2: BigQuery Table Output

```bash
./scripts/validate-player-list quality --table nba_processing.player_list_quality_test
```

**Expected:** 
- Results saved to BigQuery table
- Message: "✓ Results written to nba_processing.player_list_quality_test"

**Verify:**
```bash
bq query "SELECT * FROM nba_processing.player_list_quality_test LIMIT 10"
```

---

### Test 3.3: Complete Validation Suite

```bash
./scripts/validate-player-list all
```

**Expected:** Runs all validation queries in sequence
- daily
- freshness
- teams
- quality
- bdl-comparison

**Time:** ~2-3 minutes total

---

## Testing Phase 4: Error Handling

### Test 4.1: Invalid Command

```bash
./scripts/validate-player-list invalidcommand
```

**Expected:**
```
✗ Unknown command: invalidcommand
[Shows usage information]
```

---

### Test 4.2: Missing Query File

Temporarily rename a query file and run:
```bash
mv validation/queries/raw/nbac_player_list/daily_check_yesterday.sql validation/queries/raw/nbac_player_list/daily_check_yesterday.sql.bak
./scripts/validate-player-list daily
```

**Expected:**
```
✗ Query file not found: daily_check_yesterday.sql
```

**Cleanup:**
```bash
mv validation/queries/raw/nbac_player_list/daily_check_yesterday.sql.bak validation/queries/raw/nbac_player_list/daily_check_yesterday.sql
```

---

## Testing Checklist

### Discovery Phase
- [ ] discovery_date_range.sql executed successfully
- [ ] ~600 unique players, 30 teams, recent dates
- [ ] discovery_team_distribution.sql shows all 30 teams
- [ ] Each team has 13-17 players (typical)
- [ ] discovery_duplicates.sql returns 0 rows

### Validation Queries
- [ ] data_freshness_check.sql passes
- [ ] team_completeness_check.sql shows 30 teams
- [ ] data_quality_check.sql all checks ✅
- [ ] cross_validate_with_bdl.sql shows 60-70% overlap
- [ ] daily_check_yesterday.sql completes
- [ ] player_distribution_check.sql reasonable distributions

### CLI Tool
- [ ] Help text displays (`--help`)
- [ ] All commands work (freshness, teams, quality, etc.)
- [ ] CSV output works (`--csv`)
- [ ] BigQuery table output works (`--table`)
- [ ] Color-coded terminal output works
- [ ] Error handling works (invalid commands)
- [ ] `all` command runs complete suite

### Output Verification
- [ ] Status symbols display correctly (✅ 🔴 🟡)
- [ ] Tables formatted nicely in terminal
- [ ] CSV export opens in Excel/Sheets
- [ ] BigQuery tables queryable

---

## Success Criteria

All tests should pass with:
- ✅ No CRITICAL errors
- ✅ All 30 teams present
- ✅ Data updated within 24 hours
- ✅ 0 duplicates on player_lookup
- ✅ CLI tool functional

---

## Troubleshooting Common Issues

### "jq: command not found"
```bash
brew install jq  # Mac
sudo apt-get install jq  # Linux
```

### "Query file not found"
```bash
# Make sure you're in the right directory
pwd  # Should show nba-stats-scraper root
ls -la validation/queries/raw/nbac_player_list/
```

### "Permission denied"
```bash
chmod +x scripts/validate-player-list
```

### No color output
Terminal might not support ANSI colors. Use `--csv` instead:
```bash
./scripts/validate-player-list daily --csv
```

### BigQuery authentication issues
```bash
gcloud auth login
gcloud config set project nba-props-platform
bq ls  # Test connection
```

---

## Next Steps After Testing

1. ✅ **All tests pass** → Set up daily monitoring
2. ⚠️ **Some warnings** → Investigate and document
3. ❌ **Critical errors** → Fix data source issues first

## Daily Monitoring Setup

After successful testing:
```bash
# Add to crontab (runs at 9 AM daily)
crontab -e

# Add this line:
0 9 * * * cd /path/to/nba-stats-scraper && ./scripts/validate-player-list daily >> /var/log/player_list_validation.log 2>&1
```

Last Updated: October 13, 2025