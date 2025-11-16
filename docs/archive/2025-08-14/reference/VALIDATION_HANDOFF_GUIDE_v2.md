# NBA Data Validation - Complete Handoff Guide

**Version:** 2.0  
**Last Updated:** October 12, 2025  
**Status:** Production-Ready Pattern

---

## 📋 Overview

This guide helps you create validation queries for new NBA data sources (boxscores, player stats, injury reports, etc.) by following proven patterns established across multiple successful implementations.

**Use this guide to:**
- Validate data completeness across multiple seasons
- Detect missing games, dates, or records
- Monitor data quality and scraper health
- Create user-friendly CLI tools for validation
- Build automated monitoring systems

---

## 🎯 Reference Implementations

We have **TWO proven validation patterns** based on data structure:

### Pattern 1: Game-Based Data 
**Source:** Odds API Game Lines Validation  
**Chat ID:** `a1f3eedd-f4e3-4f29-956e-3ff0232daee9`

**Use for:** Boxscores, player stats, team stats, play-by-play  
**Characteristics:**
- One snapshot per game (or per player-game, per team-game)
- Binary completeness: data exists or it doesn't
- Every scheduled game should have data
- Cross-validate against schedule for every game

**Example:** Odds data has 8 rows per game (2 bookmakers × 2 markets × 2 outcomes)

**Key Queries:**
- `season_completeness_check.sql` - Compare to schedule by season/team
- `find_missing_regular_season_games.sql` - List specific missing games
- `verify_playoff_completeness.sql` - Ensure playoffs complete
- `daily_check_yesterday.sql` - Morning validation routine

**CLI Tool:** `validate-odds`

---

### Pattern 2: Time-Series Data
**Source:** NBA.com Injury Report Validation  
**Chat ID:** `7550cbf9-8ac3-47f4-8529-5f56d76d4a59`

**Use for:** Hourly/daily snapshots, real-time feeds, status tracking  
**Characteristics:**
- Multiple snapshots per day (e.g., 24 hourly snapshots)
- Empty periods are often NORMAL (60-70% empty is typical)
- Peak hours/times are critical (e.g., 5 PM, 8 PM for injury reports)
- Confidence scores track data quality
- Status change tracking for business intelligence

**Example:** Injury reports have 24 hourly snapshots per day, but only 5-10 have actual data

**Key Queries:**
- `hourly_snapshot_completeness.sql` - Check snapshot coverage by date
- `peak_hour_validation.sql` - Ensure critical times have data
- `status_change_detection.sql` - Track intraday changes
- `confidence_score_monitoring.sql` - Track data quality
- `daily_check_yesterday.sql` - Morning validation routine

**CLI Tool:** `validate-injuries`

---

## 🤔 Which Pattern Should I Use?

### Decision Tree

**Step 1:** How many times is the same "thing" recorded?
- **Once per game** → Game-Based Pattern
- **Multiple times per day/period** → Time-Series Pattern

**Step 2:** Is empty/sparse data normal?
- **No, every game must have data** → Game-Based Pattern
- **Yes, many hours/periods are empty** → Time-Series Pattern

**Step 3:** What's the grain of data?
- **One record per [game, player-game, team-game, possession]** → Game-Based
- **Multiple snapshots of same thing over time** → Time-Series

**Step 4:** Is there a "peak time" that's most important?
- **No, game time is the only time** → Game-Based
- **Yes, specific hours/times are critical** → Time-Series

### Examples by Data Type

| Data Type | Pattern | Records Per Game | Notes |
|-----------|---------|------------------|-------|
| Boxscores | Game-Based | 2 (home + away) | One per team per game |
| Player Stats | Game-Based | ~26 (13 per team) | Active players only |
| Play-by-Play | Game-Based | ~400-600 | Many events, but game is the unit |
| Injury Reports | Time-Series | 24 snapshots/day | Hourly updates, sparse is normal |
| Live Odds | Time-Series | Updates every min | Real-time feed |
| Team Standings | Time-Series | 30 per day | Daily aggregate |
| Shot Charts | Game-Based | ~100-150 | Per team per game |

---

## 🔍 CRITICAL: Discovery Phase (Step 0)

### ⚠️ DO THIS FIRST - NEVER SKIP!

**Lesson Learned:** In the injury report validation, we initially assumed only 3 months of data existed (Jan-Apr 2025). Discovery queries revealed 4 complete seasons (Oct 2021 - Jun 2025) - we almost created a backfill plan for 1.9M "missing" records that actually existed!

**ALWAYS run discovery queries before creating validation queries!**

---

### Discovery Query 1: Actual Date Range

**Purpose:** Find what data actually exists in the table

```sql
-- What dates do we ACTUALLY have?
SELECT 
  MIN(date_field) as earliest_date,
  MAX(date_field) as latest_date,
  COUNT(DISTINCT date_field) as total_dates_with_data,
  COUNT(*) as total_records
FROM `nba-props-platform.[dataset].[table]`;
```

**What to look for:**
- Min/max dates define actual coverage
- Compare to assumed coverage
- Check if data is older than expected

---

### Discovery Query 2: Missing Game Days

**Purpose:** Find ALL missing dates by cross-checking against schedule

```sql
-- Cross-check ALL scheduled games vs actual data
WITH all_scheduled_games AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2021-10-01' AND '2025-12-31'
    AND is_playoffs = FALSE
),
actual_data_dates AS (
  SELECT DISTINCT date_field as game_date
  FROM `nba-props-platform.[dataset].[table]`
)
SELECT 
  g.game_date,
  FORMAT_DATE('%A', g.game_date) as day_of_week
FROM all_scheduled_games g
LEFT JOIN actual_data_dates a ON g.game_date = a.game_date
WHERE a.game_date IS NULL
ORDER BY g.game_date;
```

**What to look for:**
- How many missing dates total?
- Any patterns? (All-Star weekends, specific months)
- Are they truly missing or expected gaps?

---

### Discovery Query 3: Date Continuity Gaps

**Purpose:** Find large gaps in date coverage

```sql
-- Find gaps larger than expected
WITH date_series AS (
  SELECT DISTINCT date_field
  FROM `nba-props-platform.[dataset].[table]`
  ORDER BY date_field
),
with_next_date AS (
  SELECT 
    date_field,
    LEAD(date_field) OVER (ORDER BY date_field) as next_date,
    DATE_DIFF(LEAD(date_field) OVER (ORDER BY date_field), date_field, DAY) as days_gap
  FROM date_series
)
SELECT 
  date_field,
  next_date,
  days_gap,
  CASE
    WHEN days_gap > 90 THEN '🔴 OFF-SEASON GAP (normal)'
    WHEN days_gap > 7 THEN '⚠️  LARGE GAP (investigate)'
    WHEN days_gap > 3 THEN '⚪ MEDIUM GAP (likely All-Star or off day)'
    ELSE '✅ Normal'
  END as status
FROM with_next_date
WHERE days_gap > 1
ORDER BY date_field;
```

**What to look for:**
- Large gaps (124-134 days) = Off-season (June-October) = NORMAL
- Medium gaps (6-7 days) = All-Star break = EXPECTED
- Unexpected gaps = Data quality issue

---

### Discovery Query 4: Record Volume Check

**Purpose:** Verify record counts match expectations

```sql
-- Check record counts by date (game-based data)
WITH daily_counts AS (
  SELECT 
    date_field,
    COUNT(*) as record_count,
    COUNT(DISTINCT team_field) as unique_teams,
    -- Add other relevant counts
  FROM `nba-props-platform.[dataset].[table]`
  WHERE date_field BETWEEN '2024-10-01' AND '2025-04-30'
  GROUP BY date_field
)
SELECT 
  date_field,
  record_count,
  unique_teams,
  CASE
    WHEN record_count < 10 THEN '⚠️  VERY LOW'
    WHEN record_count < 100 THEN '⚪ LOW (verify expected)'
    ELSE '✅ Normal'
  END as status
FROM daily_counts
WHERE record_count < 100  -- Adjust threshold based on expected volume
ORDER BY date_field DESC
LIMIT 50;
```

**What to look for:**
- Do record counts match expectations?
- Any dates with suspiciously low counts?
- Consistent volume across dates?

---

### Discovery Phase Output

After running all 4 discovery queries, you should know:

1. **Actual date range** in your table
2. **Specific missing dates** (if any)
3. **Patterns in gaps** (All-Star weekends, off-season)
4. **Data volume consistency**

**THEN and ONLY THEN** should you create validation queries with correct date ranges!

---

## 📂 Files to Request from User

When starting a new validation system, ask for:

### 1. Schema Files (CRITICAL)

**Request:** "Please share the BigQuery schema for `[dataset].[table]`"

**Look for:**
- **Primary key** or unique identifier field(s)
- **Date/timestamp fields** (for partitioning)
- **Team identifier fields** (abbreviations vs full names)
- **Foreign key relationships** to schedule table
- **Completeness indicators** (status, is_final, confidence_score)
- **Partition settings** (does table require partition filters?)

**Example questions to ask:**
- What field uniquely identifies a record?
- How are teams referenced? (full name, city, abbreviation?)
- What date field should I use for filtering?
- Does this table require partition filters?

---

### 2. Schedule Table Schema

**Request:** "What's the schema for `nba_raw.nbac_schedule`?"

**Key fields needed:**
- `game_date` - For joining with your data
- `game_id` - Unique game identifier
- `home_team_tricode`, `away_team_tricode` - Team abbreviations (e.g., 'GSW', 'BOS')
- `is_playoffs` - Regular season vs playoffs flag
- `is_all_star` - Exclude exhibition games

**Why:** Most validators should cross-check against the official schedule to detect missing games or data.

---

### 3. Reference Implementation Files

**For Game-Based Data, request:**
```
validation/queries/raw/odds_game_lines/
  - season_completeness_check.sql
  - find_missing_regular_season_games.sql
  - verify_playoff_completeness.sql
  - daily_check_yesterday.sql

scripts/
  - validate-odds (CLI tool)
  - VALIDATE_ODDS_CLI.md (quick-start guide)
```

**For Time-Series Data, request:**
```
validation/queries/raw/nbac_injury_report/
  - hourly_snapshot_completeness.sql
  - peak_hour_validation.sql
  - status_change_detection.sql
  - confidence_score_monitoring.sql
  - daily_check_yesterday.sql

scripts/
  - validate-injuries (CLI tool)
  - VALIDATE_INJURIES_CLI.md (quick-start guide)
  - discover-injury-gaps.sh (discovery queries)
```

**Why:** These serve as templates that you'll adapt for the new data source.

---

### 4. Data Expectations

**Ask the user:**

**For Game-Based Data:**
- How many records per game? (e.g., "2 per game - one per team")
- What constitutes "complete" data? (e.g., "both home and away stats present")
- Are there multiple data providers? (e.g., "Stats from NBA.com OR ESPN")
- Any teams/games to exclude? (All-Star games, exhibitions?)

**For Time-Series Data:**
- How many snapshots per day? (e.g., "24 hourly snapshots")
- Are empty periods normal? (e.g., "Yes, 60% of hours are empty")
- What times are most critical? (e.g., "5 PM and 8 PM ET")
- How is data quality tracked? (confidence scores, status flags?)

---

### 5. Known Issues & Gaps

**Ask the user:**
- Are there known missing dates? (All-Star breaks, COVID postponements)
- What's the historical backfill status? (Data starts when?)
- Any ongoing data quality issues?
- Expected gaps or sparse periods?

---

## 🔧 Step-by-Step Process

### Step 0: Discovery Phase ⚠️ MANDATORY

**Before creating any validation queries:**

1. Run Discovery Query 1 - Get actual min/max dates
2. Run Discovery Query 2 - Find missing game days
3. Run Discovery Query 3 - Check date continuity
4. Run Discovery Query 4 - Verify record volumes

**Document findings:**
- Actual date range: `[min_date]` to `[max_date]`
- Missing dates: `[count]` dates missing
- Patterns identified: `[All-Star weekends, etc.]`
- Coverage assessment: `[X%]` complete

**Set correct date ranges for validation queries based on actual data!**

---

### Step 1: Understand the Data Structure

**Create a reference table for the data source:**

```
Data Source: [name]
Table: nba-props-platform.[dataset].[table]
Pattern: [Game-Based OR Time-Series]

Unique Key: [field] or [field1 + field2 + field3]
Date Field: [date_field_name]
Partition: [partition_field_name]
Partition Required: [YES/NO]

Team Identifier: [how teams are referenced]
Team Field Type: [abbreviation, full name, city+name]

Expected Records: [X per game, or X per day, etc.]
Completeness Definition: [what makes data "complete"]
```

**Example for Boxscores:**
```
Data Source: NBA.com Boxscores
Table: nba-props-platform.nba_raw.nbac_boxscores
Pattern: Game-Based

Unique Key: game_id + team_tricode
Date Field: game_date
Partition: game_date
Partition Required: YES

Team Identifier: team_tricode (abbreviation)
Team Field Type: abbreviation (GSW, BOS, LAL)

Expected Records: 2 per game (home + away)
Completeness Definition: Both teams present for scheduled game
```

---

### Step 2: Create Season Completeness Query

**Purpose:** Validate data completeness by season, team, and playoff status

**Template for Game-Based Data:**

```sql
-- ============================================================================
-- Season Completeness Check
-- Purpose: Verify complete data coverage across all seasons and teams
-- ============================================================================

WITH 
-- Join data with schedule using team abbreviations
data_with_season AS (
  SELECT 
    d.[date_field],
    d.[unique_id],
    d.[team_abbr_field],
    s.is_playoffs,
    -- Assign season based on date ranges
    CASE 
      WHEN d.[date_field] BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN d.[date_field] BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN d.[date_field] BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN d.[date_field] BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
    END as season
  FROM `nba-props-platform.[dataset].[table]` d
  LEFT JOIN `nba-props-platform.nba_raw.nbac_schedule` s 
    ON d.[date_field] = s.game_date 
    AND d.[team_abbr_field] = s.home_team_tricode  -- USE ABBREVIATIONS!
  WHERE d.[date_field] BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.game_date BETWEEN '2021-10-19' AND '2025-06-20'  -- Partition filter
),

-- Diagnostic checks for data quality
diagnostics AS (
  SELECT 
    'DIAGNOSTICS' as row_type,
    COUNT(DISTINCT [unique_id]) as total_records,
    COUNT(DISTINCT CASE WHEN is_playoffs IS NULL THEN [unique_id] END) as null_playoff_flag,
    COUNT(DISTINCT CASE WHEN season IS NULL THEN [unique_id] END) as null_season,
    NULL as season,
    NULL as team,
    NULL as is_playoffs,
    NULL as regular_season,
    NULL as playoffs,
    NULL as total
  FROM data_with_season
),

-- Count by team/season
team_stats AS (
  SELECT 
    'DATA' as row_type,
    season,
    [team_abbr_field] as team,
    COALESCE(is_playoffs, FALSE) as is_playoffs,
    COUNT(DISTINCT [unique_id]) as record_count
  FROM data_with_season
  WHERE season IS NOT NULL
  GROUP BY season, [team_abbr_field], is_playoffs
)

-- Combine diagnostics and data
SELECT 
  row_type,
  season,
  team,
  CAST(SUM(CASE WHEN is_playoffs = FALSE THEN record_count ELSE 0 END) AS STRING) as regular_season,
  CAST(SUM(CASE WHEN is_playoffs = TRUE THEN record_count ELSE 0 END) AS STRING) as playoffs,
  CAST(SUM(record_count) AS STRING) as total
FROM team_stats
GROUP BY row_type, season, team
ORDER BY season, playoffs DESC, team;
```

**Key Adaptations:**
- Replace `[date_field]`, `[unique_id]`, `[team_abbr_field]` with actual column names
- Adjust expected counts based on data type (not always 82 games)
- Update season date ranges to match NBA season schedule
- Add data-source-specific checks in diagnostics

**For Time-Series Data:**
Adapt to check hourly/daily snapshot counts instead of game counts.

---

### Step 3: Create Missing Data Detection Query

**Purpose:** List specific missing games or dates

**Template for Game-Based Data:**

```sql
-- ============================================================================
-- Find Missing Records
-- Purpose: Identify specific games/dates with missing data
-- ============================================================================

WITH 
-- Get all expected records from schedule
expected_from_schedule AS (
  SELECT DISTINCT
    s.game_date,
    s.game_id,
    s.home_team_tricode,
    s.away_team_tricode,
    CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode) as matchup
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  WHERE s.game_date BETWEEN '2021-10-19' AND '2025-04-30'  -- UPDATE: from discovery
    AND s.is_playoffs = FALSE
    AND s.is_all_star = FALSE  -- Exclude All-Star games
    AND s.game_date BETWEEN '2021-10-19' AND '2025-04-30'  -- Partition filter
),

-- Get actual records from your table
actual_records AS (
  SELECT DISTINCT
    [date_field] as game_date,
    [team_abbr_field] as team_abbr
  FROM `nba-props-platform.[dataset].[table]`
  WHERE [date_field] BETWEEN '2021-10-19' AND '2025-04-30'
)

-- Find gaps (games that should have data but don't)
SELECT 
  e.game_date,
  FORMAT_DATE('%A', e.game_date) as day_of_week,
  e.matchup,
  '❌ MISSING' as status
FROM expected_from_schedule e
WHERE NOT EXISTS (
  SELECT 1 
  FROM actual_records a
  WHERE a.game_date = e.game_date
    AND (a.team_abbr = e.home_team_tricode OR a.team_abbr = e.away_team_tricode)
)
ORDER BY e.game_date;
```

**Key Adaptations:**
- Update date range based on discovery findings
- Adjust WHERE conditions for data-specific logic
- Add team-specific or other dimensional checks

**For Time-Series Data:**
Check for missing hourly snapshots or peak hours instead of games.

---

### Step 4: Create Data Quality Checks

**Purpose:** Validate data quality beyond just presence/absence

**Examples:**

**For Game-Based (Boxscores):**
```sql
-- Check for incomplete boxscores (missing home or away)
SELECT 
  game_date,
  game_id,
  COUNT(DISTINCT team_tricode) as teams_present,
  STRING_AGG(team_tricode) as teams_list
FROM `nba-props-platform.[dataset].[table]`
WHERE game_date BETWEEN '2024-10-01' AND '2025-04-30'
GROUP BY game_date, game_id
HAVING COUNT(DISTINCT team_tricode) != 2
ORDER BY game_date DESC;
```

**For Time-Series (Injury Reports):**
```sql
-- Check confidence scores
SELECT 
  report_date,
  AVG(confidence_score) as avg_confidence,
  MIN(confidence_score) as min_confidence,
  COUNTIF(confidence_score < 0.7) as low_confidence_count
FROM `nba-props-platform.[dataset].[table]`
WHERE report_date BETWEEN '2024-10-01' AND '2025-04-30'
GROUP BY report_date
HAVING AVG(confidence_score) < 0.8
ORDER BY report_date DESC;
```

---

### Step 5: Create Daily Monitoring Queries

**Three queries needed:**

#### 5a. Check Yesterday

**Purpose:** Morning check - did yesterday's data get captured?

```sql
-- Daily check: Did we get yesterday's data?
WITH 
yesterday_schedule AS (
  SELECT COUNT(*) as expected_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND is_playoffs = FALSE
    AND game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)  -- Partition
),
yesterday_data AS (
  SELECT COUNT(DISTINCT [unique_id]) as actual_records
  FROM `nba-props-platform.[dataset].[table]`
  WHERE [date_field] = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)
SELECT 
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  s.expected_games,
  d.actual_records,
  CASE
    WHEN s.expected_games = 0 AND d.actual_records = 0 THEN '⚪ No games scheduled'
    WHEN s.expected_games > 0 AND d.actual_records = 0 THEN '🔴 CRITICAL: No data'
    WHEN d.actual_records < s.expected_games * [expected_per_game] THEN '⚠️  WARNING: Incomplete'
    ELSE '✅ Complete'
  END as status
FROM yesterday_schedule s
CROSS JOIN yesterday_data d;
```

#### 5b. Last 7 Days Trend

**Purpose:** Weekly health check

```sql
-- Check last 7 days for trends
SELECT 
  [date_field],
  COUNT(DISTINCT [unique_id]) as record_count,
  COUNT(DISTINCT [team_abbr]) as unique_teams
FROM `nba-props-platform.[dataset].[table]`
WHERE [date_field] BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND CURRENT_DATE()
GROUP BY [date_field]
ORDER BY [date_field] DESC;
```

#### 5c. Real-Time Scraper Check (Optional)

**Purpose:** Is the scraper running right now?

```sql
-- Check if data is being captured today (for real-time feeds)
SELECT 
  MAX([timestamp_field]) as last_update,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX([timestamp_field]), MINUTE) as minutes_since_last
FROM `nba-props-platform.[dataset].[table]`
WHERE [date_field] = CURRENT_DATE();
```

---

### Step 6: Create CLI Tool

**Steps:**

1. **Copy reference CLI script as template**
   - For game-based: copy `scripts/validate-odds`
   - For time-series: copy `scripts/validate-injuries`

2. **Update key variables:**
   ```bash
   QUERIES_DIR="$PROJECT_ROOT/validation/queries/raw/[new_data_source]"
   ```

3. **Update command names:**
   ```bash
   # Change from:
   validate-odds completeness
   
   # To:
   validate-boxscores completeness
   ```

4. **Update help text:**
   - Describe what this validates
   - Update example commands
   - Add data-specific context

5. **Update query mappings:**
   ```bash
   case $command in
       completeness|complete)
           run_query "season_completeness_check.sql" "$output_format"
           ;;
       missing|gaps)
           run_query "find_missing_games.sql" "$output_format"
           ;;
       # Add all query commands
   esac
   ```

6. **Test all commands:**
   ```bash
   ./scripts/validate-[name] help
   ./scripts/validate-[name] list
   ./scripts/validate-[name] completeness
   ./scripts/validate-[name] yesterday
   ```

---

### Step 7: Create Documentation

**Two documents needed:**

#### Document 1: Quick-Start CLI Guide

**File:** `scripts/VALIDATE_[NAME]_CLI.md`

**Sections:**
- Installation (chmod +x, create alias)
- Quick start (5 common commands)
- Command reference (all commands with examples)
- Understanding output (what to look for)
- Common workflows (morning routine, weekly check)
- Troubleshooting

**Example structure:**
```markdown
# [Data Source] Validation CLI - Quick Start

## Installation
[installation steps]

## Quick Start
[5 most common commands]

## Daily Routine
[morning check workflow]

## Understanding Output
[what each status means]

## Common Issues
[troubleshooting guide]
```

#### Document 2: Comprehensive Validation Guide

**File:** `validation/docs/[data_source]_validation_guide.md`

**Sections:**
- Overview (what this validates)
- Data structure explanation
- All query details (purpose, usage, expected results)
- Validation schedule (when to run each query)
- Alert priorities (P0, P1, P2)
- Known issues and patterns
- References and support

---

## 🎯 Validation Design Principles

### 1. Use Schedule as Source of Truth

**DO:**
- Cross-validate every game against `nbac_schedule`
- Detect missing games by comparing to schedule
- Get expected game counts dynamically from schedule

**DON'T:**
- Hardcode expected game counts (82 games)
- Assume all teams play same number of games
- Skip schedule validation

**Example:**
```sql
-- GOOD: Dynamic from schedule
SELECT team, COUNT(*) as expected_games
FROM schedule 
WHERE is_playoffs = FALSE
GROUP BY team

-- BAD: Hardcoded
SELECT 'BOS' as team, 82 as expected_games
```

---

### 2. Use Team Abbreviations for Joins

**Why:** Schedule uses tricodes ('GSW', 'BOS', 'LAL'), but your data might use full names.

**DO:**
- Join on abbreviations: `data.team_abbr = schedule.home_team_tricode`
- Convert full names to abbrs if needed
- Use consistent abbreviation format

**DON'T:**
- Join on full team names (will fail for variations)
- Mix abbreviation formats (GSW vs GS)

**Example:**
```sql
-- GOOD: Using abbreviations
FROM boxscores b
JOIN schedule s ON b.team_abbr = s.home_team_tricode

-- BAD: Using full names (will fail)
FROM boxscores b
JOIN schedule s ON b.team_name = s.home_team_name
-- Fails because "LA Clippers" vs "Los Angeles Clippers"
```

---

### 3. Handle Partition Filters Correctly

**Rule:** If a table has `require_partition_filter = TRUE`, BOTH tables in a join need partition filters.

**DO:**
```sql
FROM table1 t1
JOIN table2 t2 ON ...
WHERE t1.date_field BETWEEN '2024-10-01' AND '2025-04-30'
  AND t2.date_field BETWEEN '2024-10-01' AND '2025-04-30'
```

**DON'T:**
```sql
-- BAD: Only filtering one table
FROM table1 t1
JOIN table2 t2 ON ...
WHERE t1.date_field BETWEEN '2024-10-01' AND '2025-04-30'
-- Will fail if table2 requires partition filter!
```

---

### 4. Create Diagnostic Checks

**Add diagnostics to catch common issues:**

- **NULL playoff flags** → Schedule join failed
- **NULL team abbreviations** → Data quality issue  
- **Unexpected record counts** → Scraper issue
- **Failed joins** → Team name mismatch

**Example:**
```sql
diagnostics AS (
  SELECT 
    COUNT(*) as total_records,
    COUNT(CASE WHEN is_playoffs IS NULL THEN 1 END) as null_playoff_flag,
    COUNT(CASE WHEN season IS NULL THEN 1 END) as null_season,
    COUNT(CASE WHEN team_abbr IS NULL THEN 1 END) as null_team
  FROM data_with_season
)
```

---

### 5. Support Multiple Output Formats

**CLI should support:**
- **Terminal** (default) - Colored, readable output
- **CSV** (`--csv`) - For spreadsheets, further analysis
- **BigQuery table** (`--table`) - For historical tracking

**Example:**
```bash
validate-boxscores completeness           # Terminal
validate-boxscores completeness --csv     # Save to CSV
validate-boxscores completeness --table   # Save to BigQuery
```

---

### 6. Base Date Ranges on Discovery Results

**CRITICAL:** Don't assume date ranges!

**DO:**
1. Run discovery queries first
2. Find actual min/max dates
3. Use those dates in validation queries

**DON'T:**
1. Assume data starts in 2024
2. Hardcode date ranges without verification
3. Create validation queries before discovery

---

## 🚨 Common Pitfalls to Avoid

### ❌ Pitfall 1: Skipping Discovery Phase

**Problem:**
```
Assumed: Data exists from Oct 2024 onward
Reality: Data exists from Oct 2021 - 4 complete seasons!
Impact: Almost created backfill plan for 1.9M "missing" records
```

**Solution:**
- ALWAYS run discovery queries first
- Verify actual min/max dates
- Base validation date ranges on actual coverage

---

### ❌ Pitfall 2: Hardcoding Expected Counts

**Problem:**
```sql
-- BAD: Hardcoded expectations
SELECT 
  team,
  CASE WHEN games = 82 THEN '✅' ELSE '❌' END
FROM team_stats
```

**Issues:**
- Teams may not play 82 games (trades, COVID, etc.)
- Playoffs have different counts
- Historical seasons varied

**Solution:**
```sql
-- GOOD: Dynamic from schedule
WITH expected AS (
  SELECT team, COUNT(*) as expected_games
  FROM schedule GROUP BY team
)
SELECT t.team, t.games, e.expected_games
FROM team_stats t
JOIN expected e ON t.team = e.team
```

---

### ❌ Pitfall 3: Using Team Full Names in Joins

**Problem:**
```sql
-- BAD: Will fail
ON data.team_name = schedule.home_team_name
-- Fails: "LA Clippers" vs "Los Angeles Clippers"
```

**Solution:**
```sql
-- GOOD: Use abbreviations
ON data.team_abbr = schedule.home_team_tricode
-- Always works: "LAC" = "LAC"
```

---

### ❌ Pitfall 4: Forgetting Partition Filters

**Problem:**
```sql
-- BAD: Missing partition filter on second table
FROM table1 
JOIN table2 ON ...
WHERE table1.date BETWEEN '2024-10-01' AND '2025-04-30'
-- ERROR if table2 requires partition filter!
```

**Solution:**
```sql
-- GOOD: Filter both tables
FROM table1 
JOIN table2 ON ...
WHERE table1.date BETWEEN '2024-10-01' AND '2025-04-30'
  AND table2.date BETWEEN '2024-10-01' AND '2025-04-30'
```

---

### ❌ Pitfall 5: Using UNION Instead of UNION ALL

**Problem:**
```sql
-- BAD: UNION removes duplicates (slow, may lose data)
SELECT home_team FROM games
UNION
SELECT away_team FROM games
```

**Solution:**
```sql
-- GOOD: UNION ALL is faster and preserves data
SELECT DISTINCT team FROM (
  SELECT home_team as team FROM games
  UNION ALL
  SELECT away_team as team FROM games
)
```

---

### ❌ Pitfall 6: Not Understanding "Empty is Normal"

**Problem:** Treating sparse data as a failure

**For Time-Series Data:**
- 60-70% of hours may be empty - THIS IS NORMAL
- Only peak hours reliably have data
- Off days will be sparse

**Solution:**
- Build "expected empty" logic into queries
- Flag only unexpected gaps
- Distinguish game days from off days

**Example:**
```sql
CASE
  WHEN games = 0 AND snapshots = 0 THEN '⚪ Expected: Off day'
  WHEN games > 0 AND snapshots = 0 THEN '🔴 CRITICAL: Game day missing'
  ELSE '✅ Complete'
END
```

---

## 📋 Validation Checklist

### Discovery Phase ✅
- [ ] Ran Query 1: Actual date range
- [ ] Ran Query 2: Missing game days  
- [ ] Ran Query 3: Date continuity gaps
- [ ] Ran Query 4: Record volume check
- [ ] Documented findings
- [ ] Set correct date ranges for validation queries

### Query Files (5-7 queries) ✅
- [ ] Season completeness (uses schedule, team abbrs)
- [ ] Missing data detection (specific games/dates)
- [ ] Data quality check (custom to data type)
- [ ] Daily check yesterday
- [ ] Weekly check (last 7 days)
- [ ] Real-time health check (optional)
- [ ] Additional data-specific queries

### CLI Tool ✅
- [ ] Copied reference CLI script
- [ ] Updated QUERIES_DIR path
- [ ] Updated command names
- [ ] Updated help text
- [ ] Tested all commands
- [ ] CSV output works
- [ ] BigQuery table output works
- [ ] Color-coded output works

### Documentation ✅
- [ ] Quick-start CLI guide created
- [ ] Comprehensive validation guide created
- [ ] Installation steps documented
- [ ] Common workflows documented
- [ ] Troubleshooting guide included
- [ ] Example outputs shown

### Testing ✅
- [ ] All queries run without errors
- [ ] Team abbreviation joins work
- [ ] Partition filters correct
- [ ] CLI commands work as expected
- [ ] Output is clear and actionable
- [ ] Date ranges based on discovery results

---

## 📊 Common Data Patterns & Validations

### Pattern: Game-Level Data
**Examples:** Boxscores, team stats, game logs  
**Grain:** One record per game (or per team per game)  
**Validation:** Every scheduled game has exactly X records  
**Reference:** `odds_game_lines`

**Key Queries:**
- Season completeness by team
- Missing games list
- Game count verification

---

### Pattern: Player-Game Data
**Examples:** Player stats, minutes played, shots taken  
**Grain:** One record per player per game  
**Validation:** Every active player has 1 record per game  
**Reference:** `odds_game_lines` (adapted)

**Key Queries:**
- Player participation verification
- Missing player-game records
- Active roster cross-check

---

### Pattern: Time-Series Data
**Examples:** Injury reports, live odds, real-time feeds  
**Grain:** Multiple snapshots per day  
**Validation:** Peak times exist, understand empty is normal  
**Reference:** `injury_report`

**Key Queries:**
- Hourly/daily snapshot completeness
- Peak hour validation
- Status change tracking
- Confidence score monitoring

---

### Pattern: Play-by-Play Data
**Examples:** Shot charts, possession data, play descriptions  
**Grain:** Many events per game  
**Validation:** Every game has N events, continuous sequence  
**Reference:** `odds_game_lines` (adapted)

**Key Queries:**
- Event sequence validation
- Game completeness (has plays for all 4 quarters)
- Timeline continuity

---

### Pattern: Aggregate/Daily Data
**Examples:** Daily standings, season averages, cumulative stats  
**Grain:** One record per team per day  
**Validation:** Daily records present, monotonic increases  
**Reference:** `injury_report` (time-series)

**Key Queries:**
- Daily record presence
- Monotonic increase check (cumulative stats)
- Gap detection

---

## 💡 Quick Start Template for New Chat

**Copy/paste this into a new chat:**

```
I want to create validation queries for [TABLE_NAME] in BigQuery.

STEP 1: Discovery Phase
First, help me run discovery queries to understand what data actually exists:
1. Actual min/max date range in the table
2. Missing game days (cross-check vs nbac_schedule)
3. Date continuity gaps
4. Record volume by date

STEP 2: Choose Pattern
Based on the data structure, help me choose:
- Game-Based Pattern (like odds_game_lines) - for per-game data
- Time-Series Pattern (like injury_report) - for hourly/daily snapshots

STEP 3: Request Files
Please request these files from me:
1. Schema for [TABLE_NAME] (show me CREATE TABLE or DESCRIBE)
2. Schema for nba_raw.nbac_schedule
3. Reference validation queries from [odds OR injury]
4. Discovery script template

STEP 4: Create Validation System
Then help me create:
1. Discovery queries (verify actual coverage)
2. Season completeness query (uses schedule as source of truth)
3. Missing data detection query (specific gaps)
4. Data quality checks (custom to data type)
5. Daily monitoring queries (yesterday, last 7 days)
6. CLI tool: validate-[name]
7. Documentation (quick-start + comprehensive guide)

Key Requirements:
- Run discovery BEFORE creating validation queries
- Use team abbreviations for joins (not full names)
- Use nbac_schedule as source of truth
- Include partition filters on all tables
- Support CSV and BigQuery table output
- Follow proven patterns from odds or injury validation

Data Details:
- Table: nba-props-platform.[dataset].[table_name]
- Expected records per [game/day]: [X]
- Date field: [field_name]
- Team field: [field_name]
- Unique identifier: [field_name]
```

---

## 🔗 Reference Materials

### Chat Sessions
- **Odds Validation (Game-Based):** `a1f3eedd-f4e3-4f29-956e-3ff0232daee9`
- **Injury Validation (Time-Series):** `7550cbf9-8ac3-47f4-8529-5f56d76d4a59`

### Key Files by Pattern

**Game-Based (Odds):**
```
validation/queries/raw/odds_game_lines/
  - season_completeness_check.sql
  - find_missing_regular_season_games.sql
  - verify_playoff_completeness.sql

scripts/
  - validate-odds
  - VALIDATE_ODDS_CLI.md
```

**Time-Series (Injury):**
```
validation/queries/raw/nbac_injury_report/
  - hourly_snapshot_completeness.sql
  - peak_hour_validation.sql
  - status_change_detection.sql
  - confidence_score_monitoring.sql

scripts/
  - validate-injuries
  - VALIDATE_INJURIES_CLI.md
  - discover-injury-gaps.sh
```

### Schedule Schema
```
nba_raw.nbac_schedule
  - game_date (DATE)
  - game_id (STRING)
  - home_team_tricode (STRING)  # 'GSW', 'BOS', 'LAL'
  - away_team_tricode (STRING)
  - is_playoffs (BOOLEAN)
  - is_all_star (BOOLEAN)
```

---

## 📞 Support

**Questions?**
- Review reference implementations in the chat sessions listed above
- Check existing CLI guides: `VALIDATE_ODDS_CLI.md`, `VALIDATE_INJURIES_CLI.md`
- Examine example queries in `validation/queries/raw/`
- Follow the pattern that matches your data structure

**Remember:**
1. Always start with discovery queries
2. Choose the right pattern (game-based or time-series)
3. Use schedule as source of truth
4. Join on team abbreviations
5. Include partition filters
6. Test thoroughly before production

---

**Last Updated:** October 12, 2025  
**Version:** 2.0  
**Status:** Production-Ready  
**Patterns:** 2 (Game-Based + Time-Series)  
**Proven Coverage:** 8 NBA seasons validated (4 seasons × 2 implementations)
