---
name: validate-historical
description: Validate historical data completeness and quality over date ranges
---

# /validate-historical - Historical Coverage Audit

Audit data quality across a date range to find coverage gaps and field completeness issues.

**Related skills**: See `/validate-daily` for current data validation.

## When to Use

- After deploying processor changes (verify no regression)
- After running backfills (verify completeness)
- Weekly data quality audit
- Before ML model retraining
- When investigating historical data issues

## Usage

```
/validate-historical [start_date] [end_date]
/validate-historical --season 2025-26
```

Examples:
- `/validate-historical` - Check last 30 days (default)
- `/validate-historical 2026-01-15` - From Jan 15 to today
- `/validate-historical 2026-01-15 2026-01-27` - Specific date range
- `/validate-historical --season 2025-26` - Entire 2025-26 season

## What This Skill Does

### Step 1: Parse Date Range

Determine start and end dates based on parameters:
- No params: Last 30 days
- One date: From that date to today
- Two dates: Explicit range
- `--season YYYY-YY`: Season start (Oct) to today

### Step 2: Query Coverage by Date

Run BigQuery query to get coverage metrics for each date:

```sql
SELECT
    game_date,
    COUNT(*) as total_records,
    COUNTIF(minutes_played > 0) as active_players,

    -- Field completeness (source fields)
    ROUND(100.0 * COUNTIF(minutes_played > 0 AND field_goals_attempted IS NOT NULL) /
          NULLIF(COUNTIF(minutes_played > 0), 0), 1) as fg_attempts_pct,
    ROUND(100.0 * COUNTIF(minutes_played > 0 AND free_throws_attempted IS NOT NULL) /
          NULLIF(COUNTIF(minutes_played > 0), 0), 1) as ft_attempts_pct,
    ROUND(100.0 * COUNTIF(minutes_played > 0 AND three_pointers_attempted IS NOT NULL) /
          NULLIF(COUNTIF(minutes_played > 0), 0), 1) as three_attempts_pct,

    -- Derived metric coverage
    ROUND(100.0 * COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) /
          NULLIF(COUNTIF(minutes_played > 0), 0), 1) as usage_rate_pct,
    ROUND(100.0 * COUNTIF(minutes_played > 0 AND defensive_rating IS NOT NULL) /
          NULLIF(COUNTIF(minutes_played > 0), 0), 1) as def_rating_pct,

    -- Data freshness
    MAX(source_team_last_updated) as latest_team_join,

    -- Status classification
    CASE
        WHEN COUNTIF(minutes_played > 0 AND field_goals_attempted IS NOT NULL) /
             NULLIF(COUNTIF(minutes_played > 0), 0) < 0.5 THEN 'CRITICAL'
        WHEN COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) /
             NULLIF(COUNTIF(minutes_played > 0), 0) < 0.9 THEN 'WARNING'
        ELSE 'OK'
    END as status
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN @start_date AND @end_date
GROUP BY game_date
ORDER BY game_date DESC
```

### Step 3: Identify Problem Dates

Flag dates where:
- **CRITICAL**: `fg_attempts_pct` < 50% (source field extraction failure)
- **WARNING**: `usage_rate_pct` < 90% (calculation issue or partial data)
- **OK**: All metrics meet thresholds

### Step 4: Generate Summary Report

```
=== HISTORICAL COVERAGE AUDIT ===
Period: 2026-01-15 to 2026-01-27
Project: nba-props-platform

SUMMARY:
- Total dates checked: 13
- Dates with OK status: 2
- Dates with warnings: 2
- Dates with critical issues: 9

CRITICAL DATES (Source field extraction failures):
| Date       | Active | fg_attempts | ft_attempts | usage_rate | Status   |
|------------|--------|-------------|-------------|------------|----------|
| 2026-01-15 |    205 |        0.0% |        0.0% |       0.0% | CRITICAL |
| 2026-01-16 |    198 |        0.0% |        0.0% |       0.0% | CRITICAL |
| 2026-01-17 |    212 |        0.0% |        0.0% |       0.0% | CRITICAL |
| 2026-01-18 |    198 |        0.0% |        0.0% |       0.0% | CRITICAL |
| 2026-01-19 |    206 |        0.0% |        0.0% |       0.0% | CRITICAL |
| 2026-01-20 |    189 |        0.0% |        0.0% |       0.0% | CRITICAL |
| 2026-01-21 |    201 |        0.0% |        0.0% |       0.0% | CRITICAL |
| 2026-01-22 |    198 |        0.0% |        0.0% |       0.0% | CRITICAL |
| 2026-01-23 |    204 |        0.0% |        0.0% |       0.0% | CRITICAL |

WARNING DATES (Calculation issues or partial data):
| Date       | Active | fg_attempts | ft_attempts | usage_rate | Status  |
|------------|--------|-------------|-------------|------------|---------|
| 2026-01-24 |    212 |       99.1% |       98.7% |      78.2% | WARNING |
| 2026-01-25 |    205 |       99.0% |       98.5% |      35.4% | WARNING |

OK DATES (All metrics good):
| Date       | Active | fg_attempts | ft_attempts | usage_rate | Status |
|------------|--------|-------------|-------------|------------|--------|
| 2026-01-26 |    198 |       99.5% |       99.0% |      98.5% | OK     |
| 2026-01-27 |    206 |       99.3% |       99.2% |      99.0% | OK     |

RECOMMENDED ACTIONS:
1. For CRITICAL dates (Jan 15-23):
   - Root cause: BDL field extraction returning NULL
   - Fix: Update processor SQL to extract actual BDL shooting stats
   - Verify: team_offense_game_summary exists for those dates
   - Backfill: Re-run player_game_summary processor after fix

2. For WARNING dates (Jan 24-25):
   - Root cause: Team stats missing or join failure
   - Check: Does team_offense_game_summary exist for these dates?
   - If missing: Backfill team stats first, then player stats
   - If exists: Check join logic in processor

3. Verification after backfill:
   - Re-run this validation to confirm fixes
   - Check downstream tables (composite_factors, predictions)
   - Run `/spot-check-cascade` for affected dates
```

## Thresholds

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| fg_attempts (active) | ≥95% | 50-94% | <50% |
| ft_attempts (active) | ≥95% | 50-94% | <50% |
| usage_rate (active) | ≥90% | 50-89% | <50% |
| defensive_rating (active) | ≥80% | 50-79% | <50% |

## Root Cause Diagnosis

### CRITICAL: fg_attempts < 50%

**Symptom**: Source fields are NULL or mostly missing.

**Possible causes**:
1. Processor SQL extracting fields as NULL (e.g., `NULL as field_goals_attempted`)
2. Raw data source changed schema
3. Join to raw data failing
4. Processor not running at all

**How to investigate**:
```sql
-- Check if raw data exists
SELECT COUNT(*) as count
FROM nba_raw.bdl_player_boxscores
WHERE game_date = '2026-01-15'
  AND field_goals_attempted IS NOT NULL;

-- If count > 0, processor SQL is the issue
-- If count = 0, raw data collection failed
```

### WARNING: usage_rate < 90%

**Symptom**: Source fields exist but derived metrics are NULL.

**Session 96 Context**: On Feb 2, 2026, usage_rate was 0% for ALL games because a global threshold (80%) blocked all calculations when 1 of 4 games was delayed. This was fixed by changing to per-game calculation.

**Possible causes**:
1. Team stats missing for specific games (can't calculate usage_rate without team stats)
2. Division by zero in calculation
3. Join to team_offense_game_summary failing
4. Calculation logic error
5. ~~Global threshold blocking~~ (FIXED in Session 96 - now per-game)

**How to investigate**:
```sql
-- Check if team stats exist
SELECT COUNT(DISTINCT game_date) as dates_with_team_stats
FROM nba_analytics.team_offense_game_summary
WHERE game_date BETWEEN '2026-01-24' AND '2026-01-25';

-- Check for join failures
SELECT
    p.game_date,
    COUNT(*) as players,
    COUNTIF(p.source_team_last_updated IS NULL) as missing_team_join
FROM nba_analytics.player_game_summary p
WHERE p.game_date BETWEEN '2026-01-24' AND '2026-01-25'
  AND p.minutes_played > 0
GROUP BY p.game_date;
```

## Integration with Other Skills

| Skill | When to Use |
|-------|-------------|
| `/validate-historical` | Find problem dates across range |
| `/validate-daily` | Check today/yesterday data |
| `/spot-check-gaps` | Find missing player records |
| `/spot-check-cascade` | Trace downstream impact |
| `/validate-lineage` | Verify cascade remediation |

### Step 5: Validate Phase 4 Coverage (Session 113+)

**NEW:** Check Phase 4 precompute tables have complete date coverage.

```sql
-- Verify Phase 4 tables exist for all game dates
WITH game_dates AS (
  SELECT DISTINCT game_date
  FROM nba_analytics.player_game_summary
  WHERE game_date BETWEEN @start_date AND @end_date
    AND game_status = 3  -- Final games only
),
cache_dates AS (
  SELECT DISTINCT cache_date as game_date
  FROM nba_precompute.player_daily_cache
  WHERE cache_date BETWEEN @start_date AND @end_date
),
shot_zone_dates AS (
  SELECT DISTINCT analysis_date as game_date
  FROM nba_precompute.player_shot_zone_analysis
  WHERE analysis_date BETWEEN @start_date AND @end_date
)
SELECT
  g.game_date,
  CASE WHEN c.game_date IS NOT NULL THEN 'YES' ELSE 'MISSING' END as has_cache,
  CASE WHEN s.game_date IS NOT NULL THEN 'YES' ELSE 'MISSING' END as has_shot_zone
FROM game_dates g
LEFT JOIN cache_dates c USING (game_date)
LEFT JOIN shot_zone_dates s USING (game_date)
WHERE c.game_date IS NULL OR s.game_date IS NULL
ORDER BY g.game_date DESC
```

**Expected:** All dates have cache AND shot_zone
**If MISSING:** HIGH - Phase 4 incomplete, affects ML feature quality

### Step 6: Cross-Reference Phase 3 vs Phase 4 (Session 113+)

**NEW:** Verify Phase 4 cache matches Phase 3 active players.

```sql
-- Check player coverage discrepancies
SELECT
  g.game_date,
  COUNT(DISTINCT g.player_lookup) as phase3_active_players,
  COALESCE(COUNT(DISTINCT c.player_lookup), 0) as phase4_cached_players,
  COUNT(DISTINCT g.player_lookup) - COALESCE(COUNT(DISTINCT c.player_lookup), 0) as missing_from_cache,
  COALESCE(COUNT(DISTINCT c.player_lookup), 0) - COUNT(DISTINCT g.player_lookup) as extra_in_cache
FROM nba_analytics.player_game_summary g
LEFT JOIN nba_precompute.player_daily_cache c
  ON g.player_lookup = c.player_lookup
  AND g.game_date = c.cache_date
WHERE g.game_date BETWEEN @start_date AND @end_date
  AND g.is_dnp = FALSE
  AND g.minutes_played > 0
GROUP BY g.game_date
HAVING missing_from_cache > 10 OR extra_in_cache > 10
ORDER BY g.game_date DESC
```

**Expected:** 0-5 discrepancy per date (minor edge cases)
**If > 10 missing:** HIGH - Major Phase 4 processing gap
**If > 10 extra:** MEDIUM - DNP players incorrectly cached

## Workflow: After Finding Issues

```
1. Run /validate-historical       → Identify problem dates
2. Investigate root cause         → Check raw data, processor SQL, Phase 4 coverage
3. Fix processor if needed        → Update extraction/calculation logic
4. Backfill affected dates        → Re-run processor for problem dates
5. Re-run /validate-historical    → Verify fixes worked (including Phase 4 checks)
6. Check downstream impact        → Run /spot-check-cascade
7. Reprocess downstream tables    → If cascade contamination found
8. Final verification            → Run /validate-lineage
```

## Implementation Notes

When implementing this skill:

1. **Date parsing**: Handle various input formats
   - `YYYY-MM-DD` format
   - `--season YYYY-YY` (Oct 1 YYYY to today)
   - Default to last 30 days if no params

2. **Query optimization**:
   - Use query parameters (`@start_date`, `@end_date`)
   - Consider limiting to dates with scheduled games
   - Cache results for large date ranges

3. **Output formatting**:
   - Show CRITICAL dates first (most urgent)
   - Limit output to reasonable size (e.g., first 10 of each category)
   - Provide summary statistics

4. **Actionable recommendations**:
   - Based on observed patterns, suggest specific fixes
   - Reference relevant documentation
   - Provide SQL queries for further investigation

## Example Session

```
user: /validate-historical 2026-01-15 2026-01-27

assistant: I'll audit data quality for dates 2026-01-15 to 2026-01-27.

[Runs query showing 9 CRITICAL dates with 0% field completeness]

Found 9 dates with CRITICAL issues where source fields are NULL:
- Jan 15-23: All shooting stats (FG, FT, 3PT) at 0%
- This indicates processor SQL is extracting NULL instead of actual values

Root cause: BDL extraction bug - processor has `NULL as field_goals_attempted`
instead of extracting from BDL's actual shooting stat fields.

Recommended fix:
1. Update processor SQL to extract BDL shooting stats
2. Re-run backfill for Jan 15-23
3. Verify with /validate-historical again

Would you like me to check the processor SQL?
```

## Success Criteria

After running this skill, you should know:
- [ ] Which dates have data quality issues
- [ ] Whether issues are source field extraction (CRITICAL) or calculation (WARNING)
- [ ] Specific metrics failing for each date
- [ ] Root cause diagnosis
- [ ] Recommended remediation steps
- [ ] Whether recent fixes worked (if re-running after backfill)

## Automated Monitoring (Session 96)

The following automated checks complement manual historical validation:

| Check | When | What |
|-------|------|------|
| `analytics-quality-check` Cloud Function | 7:30 AM ET daily | Checks yesterday's usage_rate/minutes coverage |
| Processor quality metrics | After each run | Emits DATA_QUALITY_OK/WARNING/CRITICAL logs |
| `data_quality_history` table | After each run | Stores metrics for trend analysis |

**Query historical quality metrics:**
```sql
SELECT
  check_date,
  processor,
  usage_rate_coverage_pct,
  minutes_coverage_pct,
  game_count,
  total_active_players
FROM nba_analytics.data_quality_history
WHERE check_date BETWEEN @start_date AND @end_date
ORDER BY check_date DESC
```

## Notes

- This skill is READ-ONLY - it identifies issues but doesn't fix them
- For automated validation after backfills, use `BackfillValidator` module
- Historical data before processor improvements may have lower quality
- Focus on CRITICAL issues first (source fields NULL) before WARNING issues
- See `docs/02-operations/runbooks/data-quality-runbook.md` for investigation procedures
