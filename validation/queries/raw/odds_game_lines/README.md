# Odds Game Lines Validation Queries

**Location:** `validation/queries/raw/odds_game_lines/`  
**Purpose:** SQL queries for validating NBA odds data completeness and quality

---

## Quick Start

```bash
# Navigate to project root
cd ~/code/nba-stats-scraper

# Run a query
bq query --use_legacy_sql=false < validation/queries/raw/odds_game_lines/season_completeness_check.sql

# Save results to CSV
bq query --use_legacy_sql=false --format=csv \
  < validation/queries/raw/odds_game_lines/daily_check_yesterday.sql \
  > yesterday_results.csv
```

---

## Query Files Overview

### Historical Validation (Run After Backfills)

#### 1. `season_completeness_check.sql`
**Purpose:** Comprehensive validation of all 4 seasons with diagnostics  
**When to Run:** After backfills, quarterly health checks, season end  
**Expected Runtime:** ~10-15 seconds  
**Output:** 
- 1 diagnostic row (check for data quality issues)
- 120 team rows (30 teams × 4 seasons)

**Success Criteria:**
- Diagnostic row shows all 0s (no join failures)
- All teams have 82/82 regular season games
- Playoff counts match actual results

**Example:**
```bash
bq query --use_legacy_sql=false \
  < validation/queries/raw/odds_game_lines/season_completeness_check.sql
```

---

#### 2. `find_missing_regular_season_games.sql`
**Purpose:** Identify specific games to backfill  
**When to Run:** When season_completeness_check shows incomplete data  
**Expected Runtime:** ~5 seconds  
**Output:** List of missing games with dates and matchups

**Before Running:**
- Update date ranges in query for the season you're checking
- Regular season only (exclude playoffs)

**Success Criteria:**
- Empty result set = complete data
- Any results = create backfill list from output

**Example:**
```bash
# Edit dates in file first, then run:
bq query --use_legacy_sql=false \
  < validation/queries/raw/odds_game_lines/find_missing_regular_season_games.sql
```

---

#### 3. `find_market_discrepancies.sql`
**Purpose:** Find games with only spreads or only totals  
**When to Run:** Investigating data quality, monthly health checks  
**Expected Runtime:** ~5 seconds  
**Output:** Games missing one market type

**Important Notes:**
- Small numbers (<1% of games) are **NORMAL**
- Bookmakers occasionally don't offer certain markets
- Only investigate if systematic (many games on same date)

**Success Criteria:**
- <10 results per season = acceptable
- >50 results = investigate scraper or API issue

**Example:**
```bash
bq query --use_legacy_sql=false \
  < validation/queries/raw/odds_game_lines/find_market_discrepancies.sql
```

---

#### 4. `verify_playoff_completeness.sql`
**Purpose:** Verify playoff games match expected counts  
**When to Run:** After playoffs end, during playoff backfills  
**Expected Runtime:** ~5 seconds  
**Output:** Expected vs actual playoff games per team

**Before Running:**
- Update `expected_playoff_games` CTE with actual playoff results
- Update date ranges for playoff period (include play-in)

**Success Criteria:**
- All teams show "✅ Complete" status
- Missing games show "⚠️ Incomplete" or "❌ All Missing"

**Example:**
```bash
# Edit expected games in file first, then run:
bq query --use_legacy_sql=false \
  < validation/queries/raw/odds_game_lines/verify_playoff_completeness.sql
```

---

### Daily Monitoring (Run During Season)

#### 5. `daily_check_yesterday.sql`
**Purpose:** Verify yesterday's games were captured  
**When to Run:** Every morning at 9 AM (automated)  
**Expected Runtime:** <2 seconds  
**Output:** Single row summary of yesterday's coverage

**No Configuration Needed:**
- Automatically checks DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
- No parameters to update

**Success Criteria:**
- status = "✅ Complete" or "✅ No games scheduled"
- Alert on "❌ CRITICAL" or "⚠️ WARNING"

**Automation:**
```bash
# Add to crontab (run at 9 AM daily)
0 9 * * * cd /path/to/project && bq query --use_legacy_sql=false \
  < validation/queries/raw/odds_game_lines/daily_check_yesterday.sql \
  | mail -s "Daily Odds Check" your-email@example.com
```

---

#### 6. `weekly_check_last_7_days.sql`
**Purpose:** Weekly health check showing daily trends  
**When to Run:** Monday mornings (automated weekly)  
**Expected Runtime:** ~3 seconds  
**Output:** 7 rows (one per day)

**No Configuration Needed:**
- Automatically checks last 7 days
- No parameters to update

**Success Criteria:**
- Each day shows "✅ Complete" or "⚪ No games"
- Multiple incomplete days = investigate scraper

**Example:**
```bash
bq query --use_legacy_sql=false \
  < validation/queries/raw/odds_game_lines/weekly_check_last_7_days.sql
```

---

#### 7. `realtime_scraper_check.sql`
**Purpose:** Real-time scraper health monitoring  
**When to Run:** Hourly during game days, when investigating issues  
**Expected Runtime:** <2 seconds  
**Output:** Single row with scraper status

**No Configuration Needed:**
- Automatically checks CURRENT_DATE()
- No parameters to update

**Success Criteria:**
- status = "✅ Scraper healthy"
- minutes_since_last_snapshot < 120
- Alert if scraper appears stale

**Automation:**
```bash
# Add to crontab (run hourly during season)
0 * * * * cd /path/to/project && bq query --use_legacy_sql=false \
  < validation/queries/raw/odds_game_lines/realtime_scraper_check.sql
```

---

## Recommended Workflow

### Historical Validation (One-Time or Post-Backfill)

1. **Run Season Completeness Check**
   ```bash
   bq query --use_legacy_sql=false \
     < season_completeness_check.sql
   ```
   - Check diagnostic row for 0s
   - Note any teams with <82 regular season games

2. **Find Missing Games (if needed)**
   ```bash
   # Update dates in file for problem season
   bq query --use_legacy_sql=false \
     < find_missing_regular_season_games.sql > missing_games.txt
   ```

3. **Check Playoff Data (optional)**
   ```bash
   # Update expected games in file
   bq query --use_legacy_sql=false \
     < verify_playoff_completeness.sql
   ```

4. **Review Market Discrepancies (optional)**
   ```bash
   bq query --use_legacy_sql=false \
     < find_market_discrepancies.sql
   ```

---

### Daily Monitoring (Automated During Season)

**Morning Routine (9 AM):**
```bash
# Check yesterday's games
bq query --use_legacy_sql=false \
  < daily_check_yesterday.sql
```

**Hourly During Games:**
```bash
# Check scraper health
bq query --use_legacy_sql=false \
  < realtime_scraper_check.sql
```

**Weekly (Monday 9 AM):**
```bash
# Review last week's coverage
bq query --use_legacy_sql=false \
  < weekly_check_last_7_days.sql
```

---

## Alert Thresholds

### Critical Alerts (Immediate Action Required)

From `daily_check_yesterday.sql`:
- status = "❌ CRITICAL: No odds data"
- → Scraper failed completely

From `realtime_scraper_check.sql`:
- status = "❌ CRITICAL: No odds captured yet"
- → Scraper hasn't run today

**Actions:**
1. Check scraper logs
2. Verify Cloud Scheduler is running
3. Check Odds API quota/status
4. Manual re-run: `python -m scrapers.odds_api_scraper`

---

### Warning Alerts (Investigate Same Day)

From `daily_check_yesterday.sql`:
- status = "⚠️ WARNING: X games missing"
- → Some games failed to scrape

From `realtime_scraper_check.sql`:
- status = "⚠️ WARNING: Scraper may be stale"
- → Scraper hasn't updated in >2 hours

**Actions:**
1. Run `find_missing_regular_season_games.sql` for yesterday
2. Check which games are missing
3. Re-run scraper for specific date if needed

---

### Info Alerts (Monitor Trends)

From `weekly_check_last_7_days.sql`:
- Multiple days with "⚠️ Incomplete"
- → Pattern suggests systematic issue

**Actions:**
1. Review scraper schedule
2. Check API rate limits
3. Verify processor is running after scraper

---

## Troubleshooting

### Query Returns No Results

**Problem:** Query runs but returns empty result set

**Possible Causes:**
1. No data in date range
2. Wrong date ranges in query
3. Table names incorrect

**Solution:**
```bash
# Verify table exists and has data
bq query --use_legacy_sql=false "
SELECT 
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,
  COUNT(*) as total_rows
FROM \`nba-props-platform.nba_raw.odds_api_game_lines\`
"
```

---

### Query Times Out

**Problem:** Query exceeds BigQuery timeout

**Possible Causes:**
1. Date range too large
2. No partition filter (requires partition filter = true)

**Solution:**
- Reduce date range in query
- Ensure WHERE clause includes `game_date BETWEEN`

---

### Diagnostic Row Shows Non-Zero Values

**Problem:** `season_completeness_check.sql` shows failed_joins > 0

**Possible Causes:**
1. Team abbreviation mismatch
2. Schedule data incomplete

**Solution:**
```bash
# Check abbreviation matching
bq query --use_legacy_sql=false "
SELECT DISTINCT 
  o.home_team,
  o.home_team_abbr,
  s.home_team_name,
  s.home_team_tricode
FROM \`nba-props-platform.nba_raw.odds_api_game_lines\` o
LEFT JOIN \`nba-props-platform.nba_raw.nbac_schedule\` s
  ON o.game_date = s.game_date
  AND o.home_team_abbr = s.home_team_tricode
WHERE o.game_date BETWEEN '2024-10-01' AND '2024-10-31'
  AND s.home_team_tricode IS NULL
LIMIT 10
"
```

---

## File Maintenance

### When to Update Queries

**Season Completeness Check (`season_completeness_check.sql`):**
- Add new season to CASE statement when season starts
- Update date ranges annually

**Missing Games Finder (`find_missing_regular_season_games.sql`):**
- Update date ranges for each season you're checking
- Regular season only (before playoffs)

**Playoff Verification (`verify_playoff_completeness.sql`):**
- Update expected games after playoffs end
- Update date ranges to include play-in through Finals

**Daily/Weekly/Realtime Checks:**
- No updates needed (use dynamic dates)

---

## Integration with Validation System

These queries complement the automated validator:

**Validator (`odds_game_lines_validator.py`):**
- Runs automatically via Cloud Functions
- Saves results to `validation.validation_results` table
- Sends Slack/email notifications

**These Queries:**
- Manual investigation tools
- Historical analysis
- Custom date ranges
- Ad-hoc validation

**Recommended Usage:**
1. Let validator run automatically
2. Use these queries when validator reports issues
3. Run historical queries after backfills
4. Use for documentation/reporting

---

## Additional Resources

- **Full Validation Guide:** `validation/docs/odds_game_lines_validation_guide.md`
- **Validator Code:** `validation/validators/raw/odds_game_lines_validator.py`
- **Config File:** `validation/configs/raw/odds_game_lines.yaml`
- **Scraper:** `scrapers/odds_api/odds_api_game_lines_scraper.py`

---

## Support

**Questions?** Check the main validation guide or review query comments.  
**Found a bug?** Update the query and document changes in git commit.  
**Need a new query?** Use the template in the validation guide.