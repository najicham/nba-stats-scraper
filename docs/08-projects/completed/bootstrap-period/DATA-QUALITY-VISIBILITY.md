# Data Quality Visibility - Viewing Processor Health by Season
**Purpose:** Guide to viewing data quality metrics for all dates in a season
**Created:** 2025-11-27
**Status:** ✅ Infrastructure Exists - Ready to Use!

---

## TL;DR

**Q:** "Can I easily see data quality for all dates in a season for a processor?"

**A:** **YES!** Three options, ordered by effort:

1. **SQL Queries (0 work)** - Run queries now, instant visibility ✅
2. **Grafana Dashboard (2-3 hours)** - Beautiful UI, already documented 📊
3. **Data Studio (1 hour)** - Simpler alternative to Grafana 🎨

---

## Option 1: SQL Queries (Instant - 0 Work)

### The Data Exists Now!

You already have a `processor_run_history` table tracking everything:

```sql
-- Location
nba-props-platform.nba_reference.processor_run_history
```

**Columns you care about:**
- `processor_name`, `data_date`, `status`
- `records_processed`, `duration_seconds`
- `dependency_check_passed`, `missing_dependencies`
- `feature_quality_score`, `completeness_percentage` (for Phase 4)

---

### Query 1: Season Overview Dashboard (Visual Grid)

```sql
-- See entire 2024 season at a glance for player_daily_cache
SELECT
    data_date,
    status,
    records_processed,
    duration_seconds,
    CASE
        WHEN status = 'skipped' THEN '🏁 Skipped'
        WHEN status = 'success' AND records_processed > 300 THEN '✅ Good'
        WHEN status = 'success' AND records_processed > 100 THEN '🟡 Low'
        WHEN status = 'failed' THEN '🔴 Failed'
        ELSE '⚪ Unknown'
    END as health_status
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE processor_name = 'player_daily_cache'
  AND data_date BETWEEN '2024-10-22' AND '2024-12-31'
ORDER BY data_date;
```

**Result:** Table showing every date with status

| data_date | status | records_processed | duration_seconds | health_status |
|-----------|--------|-------------------|------------------|---------------|
| 2024-10-22 | skipped | 0 | 0.5 | 🏁 Skipped |
| 2024-10-23 | skipped | 0 | 0.5 | 🏁 Skipped |
| ... | skipped | 0 | 0.5 | 🏁 Skipped |
| 2024-10-29 | success | 350 | 45.2 | ✅ Good |
| 2024-10-30 | success | 352 | 46.8 | ✅ Good |

---

### Query 2: Data Quality Metrics Over Season

```sql
-- Track quality improving over season (bootstrap period visible!)
WITH processor_data AS (
    SELECT
        data_date,
        records_processed,
        duration_seconds,
        DATE_DIFF(data_date, DATE '2024-10-22', DAY) as days_into_season
    FROM `nba-props-platform.nba_reference.processor_run_history`
    WHERE processor_name = 'player_daily_cache'
      AND data_date >= '2024-10-22'
      AND status = 'success'
),
quality_from_table AS (
    SELECT
        cache_date as data_date,
        AVG(feature_quality_score) as avg_quality,
        AVG(completeness_percentage) as avg_completeness,
        COUNT(DISTINCT player_lookup) as player_count
    FROM `nba-props-platform.nba_precompute.player_daily_cache`
    WHERE cache_date >= '2024-10-22'
    GROUP BY cache_date
)
SELECT
    p.data_date,
    p.days_into_season,
    p.records_processed,
    p.duration_seconds,
    q.avg_quality,
    q.avg_completeness,
    q.player_count,
    CASE
        WHEN p.days_into_season < 7 THEN '🏁 Bootstrap (Skipped)'
        WHEN q.avg_quality >= 90 THEN '✅ Excellent'
        WHEN q.avg_quality >= 80 THEN '🟢 Good'
        WHEN q.avg_quality >= 70 THEN '🟡 Fair'
        ELSE '🔴 Poor'
    END as quality_rating
FROM processor_data p
LEFT JOIN quality_from_table q ON p.data_date = q.data_date
ORDER BY p.data_date;
```

**Result:** Quality improving over season

| data_date | days_into_season | avg_quality | avg_completeness | quality_rating |
|-----------|------------------|-------------|------------------|----------------|
| 2024-10-29 | 7 | 72.5 | 70.0 | 🟡 Fair |
| 2024-10-30 | 8 | 74.8 | 73.3 | 🟡 Fair |
| 2024-11-05 | 14 | 85.2 | 86.7 | 🟢 Good |
| 2024-11-12 | 21 | 92.3 | 95.0 | ✅ Excellent |

---

### Query 3: Compare All 4 Seasons (Bootstrap Verification)

```sql
-- Verify bootstrap handling across all seasons
WITH season_starts AS (
    SELECT 2024 as season, DATE '2024-10-22' as start_date
    UNION ALL SELECT 2023, DATE '2023-10-24'
    UNION ALL SELECT 2022, DATE '2022-10-18'
    UNION ALL SELECT 2021, DATE '2021-10-19'
),
processor_runs AS (
    SELECT
        s.season,
        DATE_DIFF(h.data_date, s.start_date, DAY) as day_of_season,
        h.data_date,
        h.status,
        h.records_processed
    FROM season_starts s
    CROSS JOIN `nba-props-platform.nba_reference.processor_run_history` h
    WHERE h.processor_name = 'player_daily_cache'
      AND h.data_date >= s.start_date
      AND h.data_date < DATE_ADD(s.start_date, INTERVAL 30 DAY)
      AND s.season = EXTRACT(YEAR FROM h.data_date)
)
SELECT
    season,
    day_of_season,
    status,
    records_processed,
    CASE
        WHEN day_of_season < 7 AND status = 'skipped' THEN '✅ Correctly Skipped'
        WHEN day_of_season < 7 AND status != 'skipped' THEN '❌ Should Be Skipped!'
        WHEN day_of_season >= 7 AND status = 'success' THEN '✅ Processing'
        WHEN day_of_season >= 7 AND status = 'skipped' THEN '❌ Should Process!'
        ELSE '⚠️ Check'
    END as bootstrap_check
FROM processor_runs
WHERE day_of_season BETWEEN 0 AND 14  -- First 2 weeks
ORDER BY season DESC, day_of_season;
```

**Result:** Verify bootstrap behavior across seasons

| season | day_of_season | status | records_processed | bootstrap_check |
|--------|---------------|--------|-------------------|-----------------|
| 2024 | 0 | skipped | 0 | ✅ Correctly Skipped |
| 2024 | 1 | skipped | 0 | ✅ Correctly Skipped |
| 2024 | 7 | success | 350 | ✅ Processing |
| 2023 | 0 | skipped | 0 | ✅ Correctly Skipped |
| 2023 | 7 | success | 348 | ✅ Processing |

---

### Query 4: Missing Dates (Gap Detection)

```sql
-- Find gaps in processing for a season
WITH all_dates AS (
    SELECT date
    FROM UNNEST(GENERATE_DATE_ARRAY('2024-10-22', '2024-12-31', INTERVAL 1 DAY)) as date
),
processor_dates AS (
    SELECT DISTINCT data_date
    FROM `nba-props-platform.nba_reference.processor_run_history`
    WHERE processor_name = 'player_daily_cache'
      AND data_date >= '2024-10-22'
)
SELECT
    d.date as missing_date,
    DATE_DIFF(d.date, DATE '2024-10-22', DAY) as day_of_season,
    CASE
        WHEN DATE_DIFF(d.date, DATE '2024-10-22', DAY) < 7 THEN '🏁 Expected (Bootstrap)'
        ELSE '🔴 GAP - Should Investigate'
    END as gap_status
FROM all_dates d
LEFT JOIN processor_dates p ON d.date = p.data_date
WHERE p.data_date IS NULL
  AND d.date <= CURRENT_DATE()  -- Don't flag future dates
ORDER BY d.date;
```

---

## Option 2: Grafana Dashboard (2-3 Hours Setup)

### You Already Have Documentation! ✅

Location: `docs/07-monitoring/grafana/setup.md`

### Quick Grafana Panel for Processor Health

**Create a new panel in Grafana:**

**Panel Name:** "Player Daily Cache - Season Health"
**Visualization:** Time series or Heatmap
**Data Source:** NBA Props BigQuery
**Query:**

```sql
SELECT
    data_date as time,
    records_processed,
    duration_seconds,
    CASE
        WHEN status = 'skipped' THEN 0
        WHEN status = 'success' THEN records_processed
        ELSE -100  -- Show failures below baseline
    END as health_metric
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE processor_name = 'player_daily_cache'
  AND data_date >= $__timeFrom()
  AND data_date <= $__timeTo()
ORDER BY data_date
```

**Result:** Line graph showing records processed over time
- Early season: Flat at 0 (bootstrap skip)
- Day 7+: Ramps up to ~350 records/day

---

### Grafana Heatmap Calendar View

**Panel Name:** "Season Processing Calendar"
**Visualization:** Heatmap
**Query:**

```sql
SELECT
    data_date as time,
    'player_daily_cache' as processor,
    CASE
        WHEN status = 'skipped' THEN 0
        WHEN status = 'success' AND records_processed > 300 THEN 100
        WHEN status = 'success' THEN 75
        WHEN status = 'failed' THEN -100
    END as health_score
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE processor_name = 'player_daily_cache'
  AND data_date >= '2024-10-22'
ORDER BY data_date
```

**Result:** Calendar heatmap
- Dark (0): Bootstrap skip days
- Green (100): Healthy processing
- Yellow (75): Lower volume
- Red (-100): Failures

---

### Grafana Table View (Detailed)

**Panel Name:** "Processor Status Table"
**Visualization:** Table
**Query:**

```sql
SELECT
    data_date,
    DATE_DIFF(data_date, DATE '2024-10-22', DAY) as day,
    status,
    records_processed,
    ROUND(duration_seconds, 1) as duration,
    dependency_check_passed as deps_ok,
    skip_reason
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE processor_name = 'player_daily_cache'
  AND data_date >= $__timeFrom()
ORDER BY data_date DESC
LIMIT 100
```

**Table Settings:**
- Color "status" column:
  - `skipped` → Gray
  - `success` → Green
  - `failed` → Red
- Add sorting/filtering

---

## Option 3: Google Data Studio (1 Hour Setup)

### Simpler Alternative to Grafana

**Pros:**
- Free with Google Cloud account
- Easier to set up than Grafana
- Native BigQuery integration
- Can share dashboards with team

**Setup:**

1. **Go to:** https://datastudio.google.com
2. **Create Report** → Connect to BigQuery
3. **Select:** `nba-props-platform.nba_reference.processor_run_history`
4. **Add Charts:**

**Chart 1: Line Chart**
- X-axis: `data_date`
- Y-axis: `records_processed`
- Filter: `processor_name = 'player_daily_cache'`
- Date range: Season start to end

**Chart 2: Table**
- Dimensions: `data_date`, `status`, `records_processed`
- Metrics: `AVG(duration_seconds)`
- Sort: `data_date` descending

**Chart 3: Scorecard (Big Number)**
- Metric: `COUNT(DISTINCT data_date)`
- Filter: `status = 'success'` AND `data_date >= '2024-10-22'`
- Label: "Days Processed This Season"

---

## Comparison: Which Tool to Use?

| Tool | Setup Time | Learning Curve | Features | Best For |
|------|-----------|----------------|----------|----------|
| **SQL Queries** | 0 min | Low | Ad-hoc queries | Quick investigation, debugging |
| **Grafana** | 2-3 hours | Medium | Alerts, dashboards, sharing | Production monitoring, ops team |
| **Data Studio** | 1 hour | Low | Dashboards, sharing | Business users, simple viz |
| **BigQuery Console** | 0 min | Low | Saved queries | Data team, quick checks |

---

## Recommendation: Start with SQL, Add Grafana Later

### This Week (0 Work)

1. **Run SQL queries** to verify bootstrap implementation
2. **Save queries** in BigQuery for reuse
3. **Share results** via screenshots/tables

**Why:** Instant visibility, no setup needed!

### Next Week (2-3 Hours)

1. **Set up Grafana** using existing docs (`docs/07-monitoring/grafana/setup.md`)
2. **Create 1-2 key panels** (Season health line chart, status table)
3. **Set up alerts** for failures

**Why:** Long-term operational visibility

### Month 2 (Optional)

1. **Expand dashboards** for all Phase 4 processors
2. **Add quality score tracking** over time
3. **Create weekly review dashboard** for team

---

## Bootstrap Period Specific Queries

### Query: Bootstrap Impact Visualization

```sql
-- Show quality improving after bootstrap period
WITH quality_by_week AS (
    SELECT
        DATE_TRUNC(cache_date, WEEK) as week_start,
        AVG(feature_quality_score) as avg_quality,
        AVG(completeness_percentage) as avg_completeness,
        COUNT(DISTINCT player_lookup) as player_count
    FROM `nba-props-platform.nba_precompute.player_daily_cache`
    WHERE cache_date >= '2024-10-22'
    GROUP BY week_start
)
SELECT
    week_start,
    DATE_DIFF(week_start, DATE '2024-10-22', DAY) / 7 as weeks_into_season,
    avg_quality,
    avg_completeness,
    player_count,
    CASE
        WHEN weeks_into_season = 0 THEN 'Week 1 (Bootstrap)'
        WHEN weeks_into_season = 1 THEN 'Week 2 (Ramping)'
        WHEN weeks_into_season >= 3 THEN 'Steady State'
        ELSE 'Transitional'
    END as phase
FROM quality_by_week
ORDER BY week_start;
```

**Expected Result:**
| week_start | weeks_into_season | avg_quality | avg_completeness | phase |
|-----------|-------------------|-------------|------------------|-------|
| 2024-10-22 | 0 | 72.3 | 70.0 | Week 1 (Bootstrap) |
| 2024-10-29 | 1 | 78.5 | 78.0 | Week 2 (Ramping) |
| 2024-11-05 | 2 | 85.6 | 87.3 | Transitional |
| 2024-11-12 | 3 | 92.1 | 94.8 | Steady State |

---

### Query: Early Season Flag Prevalence

```sql
-- Track early_season_flag usage over time
SELECT
    cache_date,
    COUNT(*) as total_players,
    COUNTIF(early_season_flag = TRUE) as early_season_count,
    ROUND(COUNTIF(early_season_flag = TRUE) * 100.0 / COUNT(*), 1) as pct_early_season,
    AVG(feature_quality_score) as avg_quality
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN '2024-10-22' AND '2024-11-30'
GROUP BY cache_date
ORDER BY cache_date;
```

**Expected Result:**
| cache_date | total_players | early_season_count | pct_early_season | avg_quality |
|-----------|---------------|-------------------|------------------|-------------|
| 2024-10-29 | 350 | 0 | 0.0 | 72.3 |
| 2024-10-30 | 352 | 0 | 0.0 | 74.1 |

(early_season_flag should be FALSE after day 7!)

---

## Summary

### Zero Work - Use SQL Now ✅

```sql
-- Your go-to query for checking season health
SELECT
    data_date,
    DATE_DIFF(data_date, DATE '2024-10-22', DAY) as day,
    status,
    records_processed,
    duration_seconds
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE processor_name = 'player_daily_cache'
  AND data_date >= '2024-10-22'
ORDER BY data_date;
```

Run this anytime, see entire season at a glance!

### Low Effort - Grafana in 2-3 Hours 📊

Follow: `docs/07-monitoring/grafana/setup.md`
Create: 1-2 panels for season health
Benefit: Beautiful dashboards, alerts, sharing

### The Data is There! ✅

All the metrics you need are already being tracked:
- ✅ Run status and timing
- ✅ Record counts
- ✅ Dependency checks
- ✅ Quality scores (for Phase 4)
- ✅ Completeness percentages

**Just need to visualize it!**

---

**Recommendation:** Start with SQL queries today, add Grafana next week when you have 2-3 hours. The infrastructure is ready! 🚀
