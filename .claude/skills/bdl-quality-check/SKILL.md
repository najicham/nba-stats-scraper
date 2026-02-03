# BDL Data Quality Check Skill

<command-name>/bdl-quality</command-name>

## Purpose

Check BDL (Ball Don't Lie) API data quality by comparing boxscore data against NBA.com (nbac) source data for specific dates or date ranges.

## Usage

```
/bdl-quality                     # Check yesterday's data
/bdl-quality 2026-01-15          # Check specific date
/bdl-quality 2026-01-01 2026-01-15  # Check date range
```

## What This Skill Does

1. **Compares BDL vs NBAC data** for the same players and games
2. **Calculates accuracy metrics**:
   - Exact match rate (minutes)
   - Major error rate (>5 min off)
   - Points accuracy
   - Coverage percentage
3. **Identifies problematic records** with large discrepancies
4. **Reports readiness status** for potential re-enablement

## Instructions

When the user runs `/bdl-quality`, execute the following queries and provide analysis:

### Step 1: Check Date Coverage

```sql
SELECT
  game_date,
  COUNT(*) as bdl_records,
  (SELECT COUNT(*) FROM nba_raw.nbac_player_boxscores WHERE game_date = b.game_date) as nbac_records
FROM nba_raw.bdl_player_boxscores b
WHERE game_date = @check_date
  OR (game_date BETWEEN @start_date AND @end_date)
GROUP BY 1
ORDER BY 1 DESC
```

### Step 2: Compare Player Stats (Minutes Focus)

```sql
WITH comparison AS (
  SELECT
    b.game_date,
    b.player_lookup,
    b.player_full_name,
    b.team_abbr,
    -- BDL data
    SAFE_CAST(REPLACE(b.minutes, ':', '.') AS FLOAT64) as bdl_minutes,
    b.points as bdl_points,
    -- NBAC data
    n.minutes as nbac_minutes,
    n.points as nbac_points,
    -- Differences
    ABS(SAFE_CAST(REPLACE(b.minutes, ':', '.') AS FLOAT64) - SAFE_CAST(n.minutes AS FLOAT64)) as minutes_diff
  FROM nba_raw.bdl_player_boxscores b
  LEFT JOIN nba_raw.nbac_player_boxscores n
    ON b.player_lookup = n.player_lookup
    AND b.game_date = n.game_date
  WHERE b.game_date = @check_date
    AND n.player_lookup IS NOT NULL  -- Only compare matched players
)
SELECT
  game_date,
  COUNT(*) as total_players,
  ROUND(100.0 * COUNTIF(minutes_diff <= 1) / COUNT(*), 1) as exact_match_pct,
  ROUND(100.0 * COUNTIF(minutes_diff > 5) / COUNT(*), 1) as major_error_pct,
  ROUND(AVG(minutes_diff), 1) as avg_minutes_diff,
  MAX(minutes_diff) as max_minutes_diff
FROM comparison
GROUP BY 1
```

### Step 3: Identify Worst Discrepancies

```sql
-- Show top 10 largest discrepancies
WITH comparison AS (
  SELECT
    b.game_date,
    b.player_full_name,
    b.team_abbr,
    SAFE_CAST(REPLACE(b.minutes, ':', '.') AS FLOAT64) as bdl_minutes,
    SAFE_CAST(n.minutes AS FLOAT64) as nbac_minutes,
    b.points as bdl_points,
    n.points as nbac_points,
    ABS(SAFE_CAST(REPLACE(b.minutes, ':', '.') AS FLOAT64) - SAFE_CAST(n.minutes AS FLOAT64)) as minutes_diff
  FROM nba_raw.bdl_player_boxscores b
  JOIN nba_raw.nbac_player_boxscores n
    ON b.player_lookup = n.player_lookup AND b.game_date = n.game_date
  WHERE b.game_date = @check_date
)
SELECT * FROM comparison
ORDER BY minutes_diff DESC
LIMIT 10
```

### Step 4: Determine Readiness Status

Based on the metrics:
- **READY_TO_ENABLE**: Exact match >= 90%, Major errors < 5%, 7+ consecutive good days
- **NOT_READY**: Exact match < 70% OR Major errors > 15%
- **MONITORING**: Between the thresholds

## Output Format

Provide a summary like:

```
## BDL Data Quality Report: [DATE or DATE RANGE]

### Summary Metrics
| Metric | Value | Status |
|--------|-------|--------|
| Exact Match Rate | X.X% | GOOD/POOR |
| Major Error Rate | X.X% | GOOD/POOR |
| Avg Minutes Diff | X.X min | - |
| Coverage | X.X% | - |

### Readiness: [READY_TO_ENABLE / NOT_READY / MONITORING]

### Worst Discrepancies
[Table of top 10 issues]

### Recommendation
[Brief recommendation based on findings]
```

## Background

BDL API was disabled on 2026-01-28 due to persistent data quality issues:
- ~33% exact match rate on minutes
- ~28% major errors (>5 min off)
- Systematic underreporting pattern

The API continues running for monitoring purposes. Re-enablement requires 7+ consecutive days of good quality data.

## Injury Data Quality Check (Session 105 - NEW)

BDL also provides injury data via `bdl_injuries` table. Compare against NBA.com `nbac_injury_report`.

### Check Injury Data Coverage

```sql
-- Compare injury sources for today
SELECT
  'bdl_injuries' as source,
  COUNT(*) as records,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT team_abbr) as teams
FROM nba_raw.bdl_injuries
WHERE scrape_date = CURRENT_DATE()

UNION ALL

SELECT
  'nbac_injury_report',
  COUNT(*),
  COUNT(DISTINCT player_lookup),
  COUNT(DISTINCT team)
FROM nba_raw.nbac_injury_report
WHERE report_date = CURRENT_DATE()
```

### Compare Injury Status

```sql
-- Check for mismatches between BDL and NBAC injury status
WITH bdl AS (
  SELECT player_lookup, injury_status_normalized as bdl_status, team_abbr
  FROM nba_raw.bdl_injuries
  WHERE scrape_date = CURRENT_DATE()
),
nbac AS (
  SELECT player_lookup, LOWER(status) as nbac_status, team
  FROM nba_raw.nbac_injury_report
  WHERE report_date = CURRENT_DATE()
)
SELECT
  COALESCE(b.player_lookup, n.player_lookup) as player,
  b.bdl_status,
  n.nbac_status,
  CASE
    WHEN b.player_lookup IS NULL THEN 'BDL_MISSING'
    WHEN n.player_lookup IS NULL THEN 'NBAC_MISSING'
    WHEN b.bdl_status = n.nbac_status THEN 'MATCH'
    ELSE 'STATUS_DIFF'
  END as comparison
FROM bdl b
FULL OUTER JOIN nbac n ON b.player_lookup = n.player_lookup
WHERE b.bdl_status IS NULL OR n.nbac_status IS NULL OR b.bdl_status != n.nbac_status
ORDER BY comparison, player
```

### Injury Quality Thresholds

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Status Match Rate | >= 80% | 60-79% | < 60% |
| Coverage (vs NBAC) | >= 90% | 70-89% | < 70% |
| Missing in BDL | < 10% | 10-20% | > 20% |

**Note**: BDL injury data was enabled in Session 105. Monitor quality before using for predictions.

## Related Files

- Quality monitoring: `bin/monitoring/check_bdl_data_quality.py`
- Processor disable flag: `data_processors/analytics/player_game_summary/player_game_summary_processor.py` (line 90: `USE_BDL_DATA = False`)
- Quality trend view: `nba_orchestration.bdl_quality_trend`
- Injury scheduler: `bdl-injuries-hourly` (runs every 4 hours)
