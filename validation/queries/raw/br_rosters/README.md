# Basketball Reference Season Rosters Validation Queries

**Location:** `validation/queries/raw/br_rosters/`  
**Purpose:** SQL queries for validating Basketball Reference roster data completeness and quality  
**Data Pattern:** Season-level snapshots (not game-by-game)

---

## Quick Start

```bash
# Navigate to project root
cd ~/code/nba-stats-scraper

# Run a query
bq query --use_legacy_sql=false < validation/queries/raw/br_rosters/season_completeness_check.sql

# Save results to CSV
bq query --use_legacy_sql=false --format=csv \
  < validation/queries/raw/br_rosters/daily_check_yesterday.sql \
  > yesterday_results.csv
```

---

## Query Files Overview

### Historical Validation (Run After Backfills)

#### 1. `season_completeness_check.sql`
**Purpose:** Comprehensive validation of all 4 seasons with team-level breakdown  
**When to Run:** After backfills, quarterly health checks, season end  
**Expected Runtime:** ~5-10 seconds  
**Output:**
- Diagnostic rows (data quality checks)
- Season summaries (30 teams × 4 seasons)
- Individual team statistics

**Success Criteria:**
- Diagnostic nulls = 0
- 30 teams present per season (120 total team-season combinations)
- Player counts reasonable (13-25 per team typical)
- Multi-team players tracked (70-80+ per season is NORMAL)

**Example:**
```bash
bq query --use_legacy_sql=false \
  < validation/queries/raw/br_rosters/season_completeness_check.sql
```

---

#### 2. `find_missing_teams.sql`
**Purpose:** Identify specific team-season combinations to backfill  
**When to Run:** When season_completeness_check shows incomplete data  
**Expected Runtime:** ~3 seconds  
**Output:** List of missing team-season combos or suspiciously small rosters

**Success Criteria:**
- Empty result set = complete data (120 team-seasons present)
- Any results = specific teams to scrape from Basketball Reference

**Example:**
```bash
bq query --use_legacy_sql=false \
  < validation/queries/raw/br_rosters/find_missing_teams.sql
```

---

#### 3. `player_distribution_check.sql`
**Purpose:** Analyze player counts and identify multi-team scenarios  
**When to Run:** Investigating roster patterns, understanding normal ranges  
**Expected Runtime:** ~5 seconds  
**Output:**
- Season summaries with avg/min/max players per team
- Multi-team player counts (trades)
- Teams with unusual roster sizes

**Important Notes:**
- **Multi-team players are NORMAL** - 70-80+ per season expected (trades)
- Player counts vary (trades, injuries, roster moves)
- This is informational, not strict pass/fail validation

**Success Criteria:**
- Average 15-25 players per team
- Multi-team players match expected trade activity
- No teams with <10 players (likely incomplete data)

**Example:**
```bash
bq query --use_legacy_sql=false \
  < validation/queries/raw/br_rosters/player_distribution_check.sql
```

---

#### 4. `data_quality_check.sql`
**Purpose:** Validate field completeness and name normalization  
**When to Run:** After backfills, investigating data quality issues  
**Expected Runtime:** ~5-8 seconds  
**Output:**
- Completeness metrics for all fields
- Name normalization quality checks
- Position distribution
- Experience year distribution

**Success Criteria:**
- Critical fields (season, team, player_name, player_lookup) = 0 nulls
- Name normalization = 100% (no bad lookups, no spaces, all lowercase)
- Position field >95% populated
- Experience distribution looks reasonable

**Example:**
```bash
bq query --use_legacy_sql=false \
  < validation/queries/raw/br_rosters/data_quality_check.sql
```

---

### Daily Monitoring (Run During Season)

#### 5. `daily_check_yesterday.sql`
**Purpose:** Detect new roster additions from yesterday's scrape  
**When to Run:** Every morning at 9 AM (automated) during season  
**Expected Runtime:** <2 seconds  
**Output:** Summary of yesterday's updates + list of new players

**No Configuration Needed:**
- Automatically checks DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
- Focuses on current season (2024-25)

**Success Criteria:**
- status = "✅ No roster changes" (most days)
- status = "✅ Normal changes" (1-5 new players = trades/signings)
- Alert on "⚠️ Multiple changes" (>5 players = investigate)

**Automation:**
```bash
# Add to crontab (run at 9 AM daily during season)
0 9 * * * cd /path/to/project && bq query --use_legacy_sql=false \
  < validation/queries/raw/br_rosters/daily_check_yesterday.sql \
  | mail -s "Daily Roster Check" your-email@example.com
```

---

#### 6. `weekly_check_last_7_days.sql`
**Purpose:** Weekly trend analysis of roster activity  
**When to Run:** Monday mornings (automated weekly)  
**Expected Runtime:** ~3 seconds  
**Output:** 7 rows (one per day) showing scraper runs and changes

**No Configuration Needed:**
- Automatically checks last 7 days
- No parameters to update

**Success Criteria:**
- Scraper runs daily during season
- Most days show 0 new players
- Trade deadline shows spike in activity (EXPECTED)

**Example:**
```bash
bq query --use_legacy_sql=false \
  < validation/queries/raw/br_rosters/weekly_check_last_7_days.sql
```

---

#### 7. `realtime_scraper_check.sql`
**Purpose:** Real-time scraper health monitoring  
**When to Run:** When investigating scraper issues, during season  
**Expected Runtime:** <2 seconds  
**Output:** Single row with scraper status and freshness

**No Configuration Needed:**
- Automatically checks CURRENT_DATE()
- Season-aware (knows offseason is normal)

**Success Criteria:**
- During season: status = "✅ Scraper healthy"
- During offseason: status = "⚪ Offseason - scraper idle" (EXPECTED)
- Alert on "❌ CRITICAL" during season

**Example:**
```bash
bq query --use_legacy_sql=false \
  < validation/queries/raw/br_rosters/realtime_scraper_check.sql
```

---

## Recommended Workflow

### Historical Validation (One-Time or Post-Backfill)

1. **Run Season Completeness Check**
   ```bash
   bq query --use_legacy_sql=false \
     < season_completeness_check.sql
   ```
   - Verify diagnostic rows show 0 nulls
   - Confirm 30 teams per season (120 total)
   - Note any teams with unusual player counts

2. **Find Missing Teams (if needed)**
   ```bash
   bq query --use_legacy_sql=false \
     < find_missing_teams.sql > missing_teams.txt
   ```
   - Review missing team-season combinations
   - Scrape from Basketball Reference website

3. **Check Player Distribution**
   ```bash
   bq query --use_legacy_sql=false \
     < player_distribution_check.sql
   ```
   - Understand normal roster sizes
   - Verify multi-team players match trade activity

4. **Review Data Quality**
   ```bash
   bq query --use_legacy_sql=false \
     < data_quality_check.sql
   ```
   - Verify name normalization is clean
   - Check field completeness

---

### Daily Monitoring (Automated During Season)

**Morning Routine (9 AM):**
```bash
# Check yesterday's roster changes
bq query --use_legacy_sql=false \
  < daily_check_yesterday.sql
```

**When Investigating Issues:**
```bash
# Check scraper health
bq query --use_legacy_sql=false \
  < realtime_scraper_check.sql
```

**Weekly (Monday 9 AM):**
```bash
# Review last week's roster activity
bq query --use_legacy_sql=false \
  < weekly_check_last_7_days.sql
```

---

## Alert Thresholds

### Critical Alerts (Immediate Action Required)

From `realtime_scraper_check.sql`:
- status = "❌ CRITICAL: Scraper down during season"
- days_since_scrape > 7 during season (Oct-Jun)
- → Scraper completely failed

**Actions:**
1. Check scraper logs
2. Verify Cloud Scheduler is running
3. Check Basketball Reference website accessibility
4. Manual re-run: `python -m scrapers.basketball_reference.br_season_roster`

---

### Warning Alerts (Investigate Same Day)

From `daily_check_yesterday.sql`:
- status = "⚠️ Multiple changes - review below"
- new_players > 5
- → Trade deadline or unusual roster activity

From `realtime_scraper_check.sql`:
- status = "⚠️ Scraper stale (check logs)"
- days_since_scrape = 2-7 during season
- → Scraper hasn't run recently

**Actions:**
1. Review new player list from daily check
2. Verify trades on ESPN/NBA.com match roster changes
3. Re-run scraper if needed

---

### Info Alerts (Monitor Trends)

From `weekly_check_last_7_days.sql`:
- Multiple days with "⚪ No scraper run"
- → Pattern suggests scheduling issue

**Actions:**
1. Review scraper schedule configuration
2. Check Cloud Scheduler execution history
3. Verify processor is running after scraper

---

## Understanding Roster Data

### Multi-Team Players (NORMAL)

Players appear on multiple teams when:
- **Traded mid-season** (most common)
- **Waived and signed by another team**
- **10-day contracts** with multiple teams
- **Two-way contracts** between NBA and G-League

**Example from 2024-25:**
- 570 unique players
- 655 roster spots (players × teams)
- 79 players on multiple teams (trades)
- Difference: 655 - 570 = 85 extra roster spots due to movement

**This is EXPECTED and NORMAL** - don't treat as data quality issue!

---

### Season Roster Concept

Basketball Reference rosters are **end-of-season snapshots**:
- Contains every player who appeared for that team during the season
- NOT current rosters - historical view
- Does NOT indicate which team a player currently plays for
- Team-centric view: "Who played for LAL in 2023-24?"

**For current rosters, use:**
- `nba_raw.nbac_player_list_current` (NBA.com current state)
- `nba_raw.bdl_active_players_current` (Ball Don't Lie current state)

---

### Player Count Variations

**Typical ranges:**
- **Small rosters:** 13-15 players (injuries, minimal movement)
- **Average rosters:** 18-22 players (normal activity)
- **Large rosters:** 23-25 players (active trade deadline, two-way players)

**Investigate if:**
- < 10 players = Likely incomplete scrape
- > 32 players = Verify data quality (possible duplicates)

**Note:** Teams with 26-32 players are NORMAL (injuries, 10-day contracts, trade deadline activity)

---

## Troubleshooting

### Query Returns No Results

**Problem:** Query runs but returns empty result set

**Possible Causes:**
1. No data for those seasons
2. Wrong season_year filter
3. Table name incorrect

**Solution:**
```bash
# Verify table exists and has data
bq query --use_legacy_sql=false "
SELECT
  MIN(season_year) as earliest_season,
  MAX(season_year) as latest_season,
  COUNT(*) as total_records,
  COUNT(DISTINCT team_abbrev) as unique_teams
FROM \`nba-props-platform.nba_raw.br_rosters_current\`
"
```

---

### Missing Team-Season Combinations

**Problem:** `find_missing_teams.sql` shows gaps

**Possible Causes:**
1. Scraper didn't run for those team-seasons
2. Basketball Reference website issue during scrape
3. Team abbreviation changed (rare)

**Solution:**
```bash
# Manually scrape missing teams
python -m scrapers.basketball_reference.br_season_roster \
  --season 2023 \
  --teams LAL BOS
```

---

### Diagnostic Row Shows Nulls

**Problem:** `season_completeness_check.sql` shows null counts > 0

**Possible Causes:**
1. Incomplete processor run
2. Source JSON missing fields
3. Parser error in processor

**Solution:**
```bash
# Identify which records have nulls
bq query --use_legacy_sql=false "
SELECT
  season_year,
  team_abbrev,
  player_full_name,
  CASE WHEN player_lookup IS NULL THEN 'NULL_LOOKUP' END as issue,
  CASE WHEN position IS NULL THEN 'NULL_POSITION' END as issue2
FROM \`nba-props-platform.nba_raw.br_rosters_current\`
WHERE player_lookup IS NULL OR position IS NULL
LIMIT 20
"
```

---

### Name Normalization Issues

**Problem:** `data_quality_check.sql` shows bad lookups

**Possible Causes:**
1. Special characters not handled in processor
2. International names with accents
3. Jr/Sr/II/III suffixes not stripped

**Solution:**
- Review processor normalization logic
- Check specific player names causing issues
- Update `shared/utils/name_normalizer.py` if needed

---

## File Maintenance

### When to Update Queries

**Season Completeness Check (`season_completeness_check.sql`):**
- Update `current_season` CTE when new season starts
- Add new season_year to expected range (2021-2025, etc.)

**Daily Check (`daily_check_yesterday.sql`):**
- Update `current_season` CTE annually (2024 → 2025)

**Weekly Check (`weekly_check_last_7_days.sql`):**
- Update `current_season` CTE annually

**Realtime Check (`realtime_scraper_check.sql`):**
- Update `current_season` CTE annually
- Adjust month ranges if NBA schedule changes

**Other Queries:**
- No regular updates needed

---

## Integration with Validation System

These queries complement other roster data sources:

**Primary Roster Sources:**
1. **BR Rosters** (this data) - Historical, end-of-season view
2. **NBA.com Player List** - Current state only
3. **Ball Don't Lie Active Players** - Current state with validation

**Cross-Validation Opportunities:**
- Compare BR historical rosters with gamebook player appearances
- Validate name normalization across all sources
- Detect roster changes by comparing seasons

**Recommended Usage:**
1. Use BR rosters for historical "who played for X team" queries
2. Use NBA.com for current team assignments
3. Cross-validate player names across all sources

---

## Additional Resources

- **Processor Documentation:** `docs/processors/basketball_reference_rosters.md`
- **Scraper Code:** `scrapers/basketball_reference/br_season_roster.py`
- **Processor Code:** `processors/basketball_reference/br_rosters_processor.py`
- **Schema Definition:** See processor documentation

---

## Support

**Questions?** Review query comments or processor documentation  
**Found a bug?** Update the query and document changes in git commit  
**Need a new query?** Follow the template from existing queries

---

## Key Differences from Other Validations

**Unlike game-based data (odds, box scores):**
- ✅ No "missing games" concept - rosters are complete or incomplete per team-season
- ✅ Multi-team players are NORMAL - not a data quality issue
- ✅ Variable player counts are EXPECTED - teams vary widely
- ✅ Season-level granularity - not daily/game-level
- ✅ Static snapshots - end-of-season view, not real-time

**This means:**
- Don't expect exactly 82 "games" - it's 30 teams per season
- Don't alert on multi-team players - they're trades
- Don't expect uniform player counts - variation is normal
- Don't expect daily changes - roster updates happen sporadically during season

---

Last Updated: October 2025  
Data Coverage: 2021-22 through 2024-25 NBA seasons  
Total Expected Records: ~2,600 (650 per season × 4 seasons)