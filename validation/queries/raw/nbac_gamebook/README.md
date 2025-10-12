# NBA.com Gamebook Player Stats Validation Queries

**Comprehensive validation suite for gamebook data quality and completeness**

---

## 📁 Query Files

### Historical Validation

#### 1. `season_completeness_check.sql`
**Purpose:** Comprehensive season-by-season validation  
**Key Metrics:**
- Games per team (target: 82 regular season)
- Total players per game (expected: 30-35)
- Name resolution rate (target: ≥98.5%)
- Player status breakdown (active/inactive/dnp)

**When to Run:** After backfills, quarterly health checks

---

#### 2. `find_missing_regular_season_games.sql`
**Purpose:** Identify specific games missing from gamebook data  
**Output:** List of completely missing games and incomplete games (<25 players)

**When to Run:** When season completeness shows gaps

**Follow-up Actions:**
- Create backfill dates list
- Re-run scraper for missing dates
- Re-run processor for incomplete games

---

#### 3. `name_resolution_quality.sql`
**Purpose:** Analyze name resolution system performance  
**Key Metrics:**
- Resolution rate by season (target: 98.92%)
- Resolution methods used (auto_exact, injury_database, etc.)
- Summary of problem cases
- Confidence score distribution

**When to Run:** Weekly monitoring, after backfills, investigating quality issues

**Target:** 98.92% resolution rate (industry-leading accuracy)

---

#### 4. `name_resolution_problem_cases.sql`
**Purpose:** Detailed investigation of specific resolution failures  
**Output:** 
- Individual problem cases with full context
- Confidence scores for each case
- Issue descriptions and investigation context

**When to Run:** When resolution rate drops, investigating specific failures

**Use Case:** Export to CSV for manual review and pattern analysis

---

#### 5. `player_status_validation.sql`
**Purpose:** Validate player status logic and data integrity  
**Validates:**
- Active players have stats (points, minutes > 0)
- Inactive players do NOT have stats (all NULL)
- DNP players do NOT have playing time
- Player counts per game are reasonable (25-45)

**When to Run:** Monthly health checks, investigating data quality

---

### Daily Monitoring

#### 6. `daily_check_yesterday.sql`
**Purpose:** Morning check to verify yesterday's games processed correctly  
**Automated:** Yes (recommended cron job at 9 AM)

**Output:**
- ✅ Complete - All games processed, resolution ≥98%
- ⚠️ WARNING - Some games missing or incomplete
- ❌ CRITICAL - No gamebook data (scraper failure)

---

#### 7. `weekly_check_last_7_days.sql`
**Purpose:** Weekly trend analysis across last 7 days  
**When to Run:** Monday mornings (manual or automated)

**Detects:**
- Patterns of missing games
- Declining resolution rates
- Unusual player counts
- Specific problematic dates

---

#### 8. `realtime_scraper_check.sql`
**Purpose:** Monitor today's game processing in real-time  
**When to Run:** Hourly after games complete

**Shows:**
- Games processed vs pending
- Games that should be ready but aren't
- Time since game completion

---

## 🚀 Quick Start

### Using the CLI Tool (Recommended)

```bash
# Make script executable (one-time)
chmod +x scripts/validate-gamebook

# Run queries easily
validate-gamebook completeness      # Full season check
validate-gamebook yesterday         # Daily check
validate-gamebook resolution        # Name resolution quality
```

**See:** `scripts/VALIDATE_GAMEBOOK_CLI.md` for full guide

---

### Running Queries Directly

```bash
# Run from BigQuery command line
bq query --use_legacy_sql=false < validation/queries/raw/nbac_gamebook/season_completeness_check.sql

# Save to CSV
bq query --use_legacy_sql=false --format=csv < validation/queries/raw/nbac_gamebook/daily_check_yesterday.sql > yesterday_check.csv

# Save to BigQuery table
bq query --use_legacy_sql=false --destination_table=nba-props-platform:validation.gamebook_completeness < validation/queries/raw/nbac_gamebook/season_completeness_check.sql
```

---

## 📊 Understanding Results

### Season Completeness Output

```
row_type    | season  | team            | games | total_players | resolution_rate | notes
DIAGNOSTICS | ...     | DIAGNOSTICS     | 0     | 0             | 99.1%          | All should be 0
TEAM        | 2021-22 | Boston Celtics  | 82    | 2756          | 98.8%          |
TEAM        | 2021-22 | Lakers          | 81    | 2720          | 98.5%          | ⚠️ Missing games
```

**Key Indicators:**
- ✅ **DIAGNOSTICS = 0**: No join failures with schedule
- ✅ **Games = 82**: Complete regular season
- ✅ **Total players ≈ 2750**: Proper player counts (82 × ~33.5)
- ✅ **Resolution ≥98.5%**: Target met

---

### Name Resolution Output

```
report_type         | season  | total_inactive | resolved | resolution_rate | status
SEASON RESOLUTION   | 2024-25 | 1384          | 1370     | 99.0%          | ✅ Excellent
RESOLUTION METHOD   | auto_exact             | 5243     | 99.1%          | 95.3% confidence
PROBLEM CASES       | 14                     | See detailed list below
```

**Resolution Rate Thresholds:**
- 98.9%+ = ✅ Excellent
- 98.5-98.9% = ✅ Good
- 98.0-98.5% = ⚠️ Acceptable
- <98.0% = 🔴 Below Target

---

### Yesterday Check Output

```
check_date | scheduled_games | gamebook_games | resolution_rate | status
2025-10-11 | 12              | 12             | 98.2%           | ✅ Complete
```

**Status Values:**
- `✅ Complete` = All good
- `⚠️ WARNING: X games missing` = Investigate
- `❌ CRITICAL` = Scraper/processor failure

---

## 🔍 Validation Workflow

### After Running Backfills

```bash
# 1. Check overall completeness
validate-gamebook completeness

# 2. If gaps found, identify specific games
validate-gamebook missing --csv

# 3. Verify name resolution quality
validate-gamebook resolution

# 4. Check player status logic
validate-gamebook status
```

---

### Daily Monitoring (Automated)

```bash
# Add to crontab
0 9 * * * cd ~/code/nba-stats-scraper && ./scripts/validate-gamebook yesterday

# Manual weekly review
validate-gamebook week
```

---

### Investigating Issues

**Scenario 1: Missing Games**
```bash
validate-gamebook missing --csv
# Review CSV → Create backfill list → Re-run scraper
```

**Scenario 2: Low Resolution Rate**
```bash
validate-gamebook resolution --csv
# Review problem cases → Identify patterns → Update resolution system if needed
```

**Scenario 3: Player Status Issues**
```bash
validate-gamebook status --csv
# Review quality issues → Cross-check with ESPN/BDL → Fix data source if needed
```

---

## 🎯 Key Metrics

### Data Completeness
- **Games per team:** 82 regular season, playoffs vary
- **Players per game:** 30-35 (active + DNP + inactive)
- **Active players per game:** ~10-13 per team (20-26 total)
- **Inactive players per game:** Varies by injuries (typically 3-8)

### Name Resolution
- **Target rate:** 98.92% (industry-leading)
- **Acceptable rate:** ≥98.5%
- **Warning threshold:** <98.0%
- **Expected failures:** G-League, trades, two-way contracts (~1.08%)

### Data Quality
- **Active players:** Must have minutes > 0, should have points
- **Inactive players:** Should have NO stats (all NULL)
- **DNP players:** Should have NO playing time
- **Processing time:** <5 minutes per date after games complete

---

## 🔗 Related Files

- **CLI Tool:** `scripts/validate-gamebook`
- **CLI Guide:** `scripts/VALIDATE_GAMEBOOK_CLI.md`
- **Validator:** `validation/validators/raw/nbac_gamebook_validator.py`
- **Config:** `validation/configs/raw/nbac_gamebook.yaml`

---

## 📞 Quick Reference

```bash
# Daily monitoring
validate-gamebook yesterday          # Check yesterday's games

# Weekly health check  
validate-gamebook week               # Last 7 days trends
validate-gamebook resolution         # Name resolution quality
validate-gamebook problems --csv     # Export problem cases

# After backfills
validate-gamebook completeness       # Full validation
validate-gamebook missing            # Find gaps
validate-gamebook status             # Data quality

# Real-time monitoring
validate-gamebook today              # Current game processing
```

---

## 🎓 Understanding the Data

### Player Statuses

**Active** - Played in the game
- Has minutes, points, and full stats
- Typically 10-13 players per team (20-26 per game)

**Inactive** - On injury report, did not play
- Only last name in source data (requires name resolution)
- Should have NO stats (all NULL)
- Typically 3-8 per game depending on injuries

**DNP** - Did Not Play (coach's decision)
- Full name available in source
- Should have NO playing time
- Includes "Not With Team", "G League", etc.

---

### Name Resolution System

**Challenge:** Inactive players appear with last name only (e.g., "James")

**Solution:** Multi-source resolution system:
1. **Injury Database** - Exact match on game/team/date (99%+ success)
2. **Basketball Reference** - Roster cache fallback (covers edge cases)
3. **Data-driven disambiguation** - Handles multiple matches intelligently

**Result:** 98.92% resolution rate (effectively 100% for business purposes)

**Expected Failures:** G-League assignments, trade-pending players, "Not With Team" status - these are legitimate exclusions who cannot receive prop bets.

---

**Last Updated:** October 12, 2025  
**Query Count:** 8  
**Target Resolution Rate:** 98.92%