# Data Completeness Validation

**File:** `docs/monitoring/05-data-completeness-validation.md`
**Created:** 2025-11-18
**Last Updated:** 2025-11-18
**Purpose:** Validate data completeness for daily operations and backfills
**Status:** Current
**Audience:** Engineers running backfills, on-call engineers validating daily pipeline

---

## 🎯 Overview

**This document covers:**
- ✅ Daily completeness validation (is today's data complete?)
- ✅ Backfill completeness validation (did historical backfill complete?)
- ✅ Progressive validation (Phase 1→2→3→4→5 per date)
- ✅ Partial backfill detection (Phase 1-3 done, Phase 4-5 missing)
- ✅ Cross-phase reconciliation (row counts match?)
- ✅ Recovery procedures

---

## 📊 Use Cases

### Use Case 1: Daily Completeness Check
**Scenario:** Morning health check - is yesterday's data complete?

**Questions:**
- Did Phase 1 scrapers run for yesterday?
- Did Phase 2-5 processors complete?
- Are row counts as expected?
- Any missing entities (players, teams, games)?

---

### Use Case 2: Historical Backfill Validation
**Scenario:** Backfilled 2023-24 season (Oct 2023 - Apr 2024), verify complete

**Questions:**
- Did ALL dates in range complete ALL phases?
- Any gaps in the date range?
- Row counts match expected for each date?
- Which dates need re-processing?

---

### Use Case 3: Gap Fill Validation
**Scenario:** Nov 8-14 data was missing, backfilled those 7 days

**Questions:**
- Did all 7 dates complete?
- Did ALL phases run for those 7 dates?
- Any dates only partially processed?

---

### Use Case 4: Re-Processing After Manual Fix
**Scenario:** Scraped data had error, manually fixed, need to re-run processors

**Questions:**
- Did processors re-run successfully?
- Did downstream phases pick up the updated data?
- New processed_at timestamps reflect the re-run?

---

## 🔍 Validation Queries

### Query 1: Daily Completeness (Single Date)

**Purpose:** Verify today's data is complete across all phases

```sql
-- Daily Completeness Check for 2025-11-18
WITH target_date AS (
  SELECT DATE('2025-11-18') as game_date
),

-- Phase 1: Scraper Execution
phase1_status AS (
  SELECT
    'Phase 1: Scrapers' as phase,
    COUNT(DISTINCT scraper_name) as scrapers_run,
    COUNTIF(status IN ('success', 'no_data')) as scrapers_succeeded,
    COUNTIF(status = 'failed') as scrapers_failed,
    MAX(triggered_at) as last_run,
    CASE
      WHEN COUNTIF(status = 'failed') = 0 THEN '✅ Complete'
      WHEN COUNTIF(status = 'failed') < 5 THEN '⚠️ Partial'
      ELSE '❌ Failed'
    END as status
  FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
  CROSS JOIN target_date
  WHERE DATE(triggered_at, 'America/New_York') = target_date.game_date
),

-- Phase 2: Raw Data
phase2_status AS (
  SELECT
    'Phase 2: Raw Tables' as phase,
    SUM(table_count) as tables_with_data,
    SUM(total_rows) as total_rows,
    MAX(last_update) as last_run,
    CASE
      WHEN SUM(table_count) >= 10 THEN '✅ Complete'
      WHEN SUM(table_count) >= 5 THEN '⚠️ Partial'
      ELSE '❌ Incomplete'
    END as status
  FROM (
    SELECT 1 as table_count, COUNT(*) as total_rows, MAX(created_at) as last_update
    FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
    CROSS JOIN target_date
    WHERE game_date = target_date.game_date

    UNION ALL

    SELECT 1, COUNT(*), MAX(created_at)
    FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
    CROSS JOIN target_date
    WHERE game_date = target_date.game_date

    UNION ALL

    SELECT 1, COUNT(*), MAX(created_at)
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    CROSS JOIN target_date
    WHERE game_date = target_date.game_date

    -- Add more raw tables as needed
  )
),

-- Phase 3: Analytics Tables
phase3_status AS (
  SELECT
    'Phase 3: Analytics' as phase,
    SUM(table_count) as tables_with_data,
    SUM(total_rows) as total_rows,
    MAX(last_update) as last_run,
    CASE
      WHEN SUM(table_count) >= 5 THEN '✅ Complete'
      WHEN SUM(table_count) >= 3 THEN '⚠️ Partial'
      ELSE '❌ Incomplete'
    END as status
  FROM (
    SELECT 1 as table_count, COUNT(*) as total_rows, MAX(processed_at) as last_update
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    CROSS JOIN target_date
    WHERE game_date = target_date.game_date

    UNION ALL

    SELECT 1, COUNT(*), MAX(processed_at)
    FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
    CROSS JOIN target_date
    WHERE game_date = target_date.game_date

    -- Add more analytics tables
  )
),

-- Phase 4: Precompute Tables
phase4_status AS (
  SELECT
    'Phase 4: Precompute' as phase,
    SUM(table_count) as tables_with_data,
    SUM(total_rows) as total_rows,
    MAX(last_update) as last_run,
    CASE
      WHEN SUM(table_count) >= 3 THEN '✅ Complete'
      WHEN SUM(table_count) >= 2 THEN '⚠️ Partial'
      ELSE '❌ Incomplete'
    END as status
  FROM (
    SELECT 1 as table_count, COUNT(*) as total_rows, MAX(processed_at) as last_update
    FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
    CROSS JOIN target_date
    WHERE analysis_date = target_date.game_date

    UNION ALL

    SELECT 1, COUNT(*), MAX(processed_at)
    FROM `nba-props-platform.nba_precompute.player_composite_factors`
    CROSS JOIN target_date
    WHERE game_date = target_date.game_date

    -- Add more precompute tables
  )
),

-- Phase 5: Predictions
phase5_status AS (
  SELECT
    'Phase 5: Predictions' as phase,
    COUNT(*) as tables_with_data,
    COUNT(*) as total_rows,
    MAX(created_at) as last_run,
    CASE
      WHEN COUNT(*) >= 100 THEN '✅ Complete'
      WHEN COUNT(*) >= 50 THEN '⚠️ Partial'
      ELSE '❌ Incomplete'
    END as status
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  CROSS JOIN target_date
  WHERE game_date = target_date.game_date
)

-- Combine all phases
SELECT * FROM phase1_status
UNION ALL SELECT * FROM phase2_status
UNION ALL SELECT * FROM phase3_status
UNION ALL SELECT * FROM phase4_status
UNION ALL SELECT * FROM phase5_status
ORDER BY phase;
```

**Expected Output (Healthy Day):**
```
phase                 | tables_with_data | total_rows | last_run            | status
----------------------|------------------|------------|---------------------|------------
Phase 1: Scrapers     | 45               | N/A        | 2025-11-18 03:15:22 | ✅ Complete
Phase 2: Raw Tables   | 12               | 1850       | 2025-11-18 03:45:18 | ✅ Complete
Phase 3: Analytics    | 5                | 980        | 2025-11-18 04:12:35 | ✅ Complete
Phase 4: Precompute   | 4                | 520        | 2025-11-18 23:45:10 | ✅ Complete
Phase 5: Predictions  | 1                | 435        | 2025-11-18 00:15:42 | ✅ Complete
```

---

### Query 2: Backfill Range Completeness

**Purpose:** Verify all dates in a range completed all phases

```sql
-- Backfill Completeness for Date Range
-- Check: Oct 22, 2024 - Nov 18, 2024
DECLARE start_date DATE DEFAULT '2024-10-22';
DECLARE end_date DATE DEFAULT '2024-11-18';

WITH date_range AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY(start_date, end_date)) AS date
),

-- Check Phase 2 (raw tables)
phase2_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date BETWEEN start_date AND end_date
),

-- Check Phase 3 (analytics)
phase3_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN start_date AND end_date
),

-- Check Phase 4 (precompute)
phase4_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN start_date AND end_date
),

-- Check Phase 5 (predictions)
phase5_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date BETWEEN start_date AND end_date
)

-- Find gaps
SELECT
  d.date,
  CASE WHEN p2.game_date IS NOT NULL THEN '✅' ELSE '❌' END as phase2,
  CASE WHEN p3.game_date IS NOT NULL THEN '✅' ELSE '❌' END as phase3,
  CASE WHEN p4.game_date IS NOT NULL THEN '✅' ELSE '❌' END as phase4,
  CASE WHEN p5.game_date IS NOT NULL THEN '✅' ELSE '❌' END as phase5,
  CASE
    WHEN p2.game_date IS NULL THEN '❌ No Phase 2 data'
    WHEN p3.game_date IS NULL THEN '⚠️ Phase 2 complete, Phase 3 missing'
    WHEN p4.game_date IS NULL THEN '⚠️ Phase 3 complete, Phase 4 missing'
    WHEN p5.game_date IS NULL THEN '⚠️ Phase 4 complete, Phase 5 missing'
    ELSE '✅ Complete'
  END as status
FROM date_range d
LEFT JOIN phase2_dates p2 ON d.date = p2.game_date
LEFT JOIN phase3_dates p3 ON d.date = p3.game_date
LEFT JOIN phase4_dates p4 ON d.date = p4.game_date
LEFT JOIN phase5_dates p5 ON d.date = p5.game_date
ORDER BY d.date DESC;
```

**Example Output (Partial Backfill):**
```
date       | phase2 | phase3 | phase4 | phase5 | status
-----------|--------|--------|--------|--------|---------------------------
2024-11-18 | ✅     | ✅     | ✅     | ✅     | ✅ Complete
2024-11-17 | ✅     | ✅     | ✅     | ✅     | ✅ Complete
2024-11-16 | ✅     | ✅     | ✅     | ❌     | ⚠️ Phase 4 complete, Phase 5 missing
2024-11-15 | ✅     | ✅     | ❌     | ❌     | ⚠️ Phase 3 complete, Phase 4 missing
2024-11-14 | ✅     | ❌     | ❌     | ❌     | ⚠️ Phase 2 complete, Phase 3 missing
2024-11-13 | ❌     | ❌     | ❌     | ❌     | ❌ No Phase 2 data
```

**Interpretation:**
- Nov 18-17: Fully complete ✅
- Nov 16: Need to run Phase 5 only
- Nov 15: Need to run Phase 4-5
- Nov 14: Need to run Phase 3-4-5
- Nov 13: Need to run Phase 2-3-4-5 (complete backfill)

---

### Query 3: Row Count Reconciliation

**Purpose:** Verify row counts match expectations across phases

```sql
-- Row Count Reconciliation for 2025-11-18
WITH target_date AS (
  SELECT DATE('2025-11-18') as game_date
),

-- Expected counts (based on scheduled games)
expected_counts AS (
  SELECT
    game_date,
    COUNT(*) as scheduled_games,
    COUNT(*) * 2 as expected_teams,
    COUNT(*) * 30 as expected_players  -- ~15 players per team × 2 teams
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  CROSS JOIN target_date
  WHERE game_date = target_date.game_date
  GROUP BY game_date
),

-- Actual counts
actual_counts AS (
  SELECT
    game_date,
    -- Phase 2 counts
    (SELECT COUNT(*) FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
     WHERE game_date = target_date.game_date) as phase2_players,
    (SELECT COUNT(*) FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
     WHERE game_date = target_date.game_date) as phase2_teams,

    -- Phase 3 counts
    (SELECT COUNT(*) FROM `nba-props-platform.nba_analytics.player_game_summary`
     WHERE game_date = target_date.game_date) as phase3_players,
    (SELECT COUNT(*) FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
     WHERE game_date = target_date.game_date) as phase3_teams,

    -- Phase 4 counts
    (SELECT COUNT(*) FROM `nba-props-platform.nba_precompute.player_composite_factors`
     WHERE game_date = target_date.game_date) as phase4_players
  FROM target_date
)

SELECT
  e.scheduled_games,
  e.expected_teams,
  e.expected_players,
  a.phase2_teams,
  a.phase2_players,
  a.phase3_teams,
  a.phase3_players,
  a.phase4_players,
  -- Reconciliation checks
  CASE
    WHEN a.phase2_teams = e.expected_teams THEN '✅'
    WHEN a.phase2_teams >= e.expected_teams * 0.9 THEN '⚠️'
    ELSE '❌'
  END as phase2_teams_check,
  CASE
    WHEN a.phase2_players >= e.expected_players * 0.8 THEN '✅'  -- Allow 20% variance
    WHEN a.phase2_players >= e.expected_players * 0.6 THEN '⚠️'
    ELSE '❌'
  END as phase2_players_check,
  CASE
    WHEN a.phase3_players = a.phase2_players THEN '✅'
    WHEN a.phase3_players >= a.phase2_players * 0.95 THEN '⚠️'
    ELSE '❌'
  END as phase2_to_phase3_reconciliation
FROM expected_counts e
CROSS JOIN actual_counts a;
```

**Example Output:**
```
scheduled_games | expected_teams | expected_players | phase2_teams | phase2_players | phase3_players | phase2_teams_check | phase2_to_phase3_reconciliation
----------------|----------------|------------------|--------------|----------------|----------------|--------------------|---------------------------------
14              | 28             | 420              | 28           | 445            | 442            | ✅                 | ⚠️ (3 missing)
```

**Interpretation:**
- ✅ Phase 2 teams: All 28 teams processed
- ✅ Phase 2 players: 445 players (more than expected 420, includes bench)
- ⚠️ Phase 3 players: 442 players (3 missing from Phase 2, investigate)

---

### Query 4: Missing Entities Detection

**Purpose:** Find which specific entities are missing

```sql
-- Find Missing Players (Phase 2 → Phase 3)
WITH phase2_players AS (
  SELECT DISTINCT player_id, player_name
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date = '2025-11-18'
),
phase3_players AS (
  SELECT DISTINCT player_id
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date = '2025-11-18'
)

SELECT
  p2.player_id,
  p2.player_name,
  'Missing in Phase 3' as issue
FROM phase2_players p2
LEFT JOIN phase3_players p3 ON p2.player_id = p3.player_id
WHERE p3.player_id IS NULL
ORDER BY p2.player_name;
```

**Example Output:**
```
player_id | player_name      | issue
----------|------------------|--------------------
player123 | LeBron James     | Missing in Phase 3
player456 | Stephen Curry    | Missing in Phase 3
player789 | Kevin Durant     | Missing in Phase 3
```

**Action:** Investigate why these 3 players didn't process in Phase 3

---

## 📋 Validation Procedures

### Procedure 1: Daily Morning Check

**Run this every morning to verify yesterday's data:**

```bash
# Step 1: Quick health check
./bin/orchestration/quick_health_check.sh

# Step 2: Detailed completeness check (use Query 1 above)
bq query --use_legacy_sql=false --format=pretty "$(cat docs/monitoring/queries/daily_completeness.sql)"

# Step 3: If incomplete, check missing entities (use Query 4)
bq query --use_legacy_sql=false "$(cat docs/monitoring/queries/missing_entities.sql)"

# Step 4: Check row count reconciliation (use Query 3)
bq query --use_legacy_sql=false "$(cat docs/monitoring/queries/row_count_reconciliation.sql)"
```

**Decision Matrix:**
- ✅ All phases complete → No action
- ⚠️ Phase 1-3 complete, Phase 4-5 missing → Trigger Phase 4-5 manually
- ❌ Phase 2 missing → Check scraper failures, re-run scrapers
- ❌ Missing entities → Investigate specific failures

---

### Procedure 2: Backfill Validation

**Run this after completing a backfill:**

```bash
# Step 1: Define date range
START_DATE="2024-10-22"
END_DATE="2024-11-18"

# Step 2: Check range completeness (use Query 2)
bq query --use_legacy_sql=false \
  --parameter=start_date:DATE:$START_DATE \
  --parameter=end_date:DATE:$END_DATE \
  "$(cat docs/monitoring/queries/backfill_range_completeness.sql)"

# Step 3: Count incomplete dates
INCOMPLETE_DATES=$(bq query --use_legacy_sql=false --format=csv \
  --parameter=start_date:DATE:$START_DATE \
  --parameter=end_date:DATE:$END_DATE \
  "$(cat docs/monitoring/queries/backfill_range_completeness.sql)" \
  | grep -c "❌")

echo "Incomplete dates: $INCOMPLETE_DATES"

# Step 4: If incomplete, get list of dates needing work
if [ $INCOMPLETE_DATES -gt 0 ]; then
  echo "Dates needing backfill:"
  bq query --use_legacy_sql=false --format=csv \
    --parameter=start_date:DATE:$START_DATE \
    --parameter=end_date:DATE:$END_DATE \
    "$(cat docs/monitoring/queries/backfill_range_completeness.sql)" \
    | grep "❌"
fi
```

---

### Procedure 3: Progressive Phase Validation

**After running each phase of backfill, validate before proceeding:**

```bash
# Example: After Phase 2 backfill, before starting Phase 3
START_DATE="2024-10-22"
END_DATE="2024-11-18"

# Validate Phase 2 complete for ALL dates
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_dates,
  COUNT(DISTINCT game_date) as dates_with_phase2
FROM UNNEST(GENERATE_DATE_ARRAY(DATE('$START_DATE'), DATE('$END_DATE'))) AS date
LEFT JOIN \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\` p2
  ON date = p2.game_date
"

# Expected: total_dates = dates_with_phase2
# If not equal, some dates missing Phase 2 data
```

**Validation Checklist Before Next Phase:**
- [ ] Row count >= expected minimum
- [ ] No missing dates in range
- [ ] No suspicious gaps (weekends with 0 games = OK, weekday with 0 = suspicious)
- [ ] processed_at timestamps within expected range

---

## 🚨 Common Issues & Recovery

### Issue 1: Partial Phase Completion

**Symptom:** Phase 2 complete, Phase 3 only has 60% of expected rows

**Diagnosis:**
```sql
-- Check which dates Phase 3 is missing
SELECT
  p2.game_date,
  COUNT(DISTINCT p2.player_id) as phase2_players,
  COUNT(DISTINCT p3.player_id) as phase3_players,
  COUNT(DISTINCT p2.player_id) - COUNT(DISTINCT p3.player_id) as missing_players
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats` p2
LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` p3
  ON p2.player_id = p3.player_id AND p2.game_date = p3.game_date
WHERE p2.game_date BETWEEN '2024-10-22' AND '2024-11-18'
GROUP BY p2.game_date
HAVING missing_players > 0
ORDER BY p2.game_date;
```

**Recovery:**
```bash
# Re-run Phase 3 for dates with missing players
for date in $(bq query --use_legacy_sql=false --format=csv "..." | tail -n +2); do
  gcloud run jobs execute phase3-player-game-summary \
    --region us-central1 \
    --set-env-vars "START_DATE=$date,END_DATE=$date"
done
```

---

### Issue 2: Date Range Gaps

**Symptom:** Nov 8-14 completely missing from all phases

**Diagnosis:**
```sql
-- Find gaps in date range
WITH date_range AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY(DATE('2024-10-22'), DATE('2024-11-18'))) AS date
),
actual_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
)

SELECT d.date as missing_date
FROM date_range d
LEFT JOIN actual_dates a ON d.date = a.game_date
WHERE a.game_date IS NULL
ORDER BY d.date;
```

**Recovery:**
```bash
# Run complete backfill for missing dates
./bin/backfill/run_all_phases.sh \
  --start-date=2024-11-08 \
  --end-date=2024-11-14
```

---

### Issue 3: Row Count Mismatch

**Symptom:** Phase 2 has 450 players, Phase 3 has 300 players

**Diagnosis:**
```sql
-- Find players in Phase 2 but not Phase 3
SELECT
  p2.player_id,
  p2.player_name,
  p2.team,
  COUNT(DISTINCT p2.game_date) as games_in_phase2,
  COUNT(DISTINCT p3.game_date) as games_in_phase3
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats` p2
LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` p3
  ON p2.player_id = p3.player_id AND p2.game_date = p3.game_date
WHERE p2.game_date BETWEEN '2024-10-22' AND '2024-11-18'
GROUP BY p2.player_id, p2.player_name, p2.team
HAVING games_in_phase3 = 0
ORDER BY games_in_phase2 DESC;
```

**Possible Causes:**
- Phase 3 processor filtering out players (e.g., minutes played < 5)
- Phase 3 processor failed midway
- Data quality issues (NULL player_id)

**Recovery:**
- If filtering: Expected behavior, document thresholds
- If failed: Re-run Phase 3
- If data quality: Fix Phase 2 data, re-run Phase 3

---

## 📊 Completeness Dashboards

### Grafana Dashboard: Backfill Progress

**Panel 1: Date Range Completeness**
```sql
-- Visualize backfill progress over time
WITH date_range AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY(DATE('2024-10-22'), CURRENT_DATE())) AS date
),
completeness AS (
  SELECT
    d.date,
    CASE WHEN p2.game_date IS NOT NULL THEN 1 ELSE 0 END as phase2_complete,
    CASE WHEN p3.game_date IS NOT NULL THEN 1 ELSE 0 END as phase3_complete,
    CASE WHEN p4.game_date IS NOT NULL THEN 1 ELSE 0 END as phase4_complete,
    CASE WHEN p5.game_date IS NOT NULL THEN 1 ELSE 0 END as phase5_complete
  FROM date_range d
  LEFT JOIN (SELECT DISTINCT game_date FROM nba_raw.nbac_gamebook_player_stats) p2
    ON d.date = p2.game_date
  LEFT JOIN (SELECT DISTINCT game_date FROM nba_analytics.player_game_summary) p3
    ON d.date = p3.game_date
  LEFT JOIN (SELECT DISTINCT game_date FROM nba_precompute.player_composite_factors) p4
    ON d.date = p4.game_date
  LEFT JOIN (SELECT DISTINCT game_date FROM nba_predictions.ml_feature_store_v2) p5
    ON d.date = p5.game_date
)
SELECT
  date,
  (phase2_complete + phase3_complete + phase4_complete + phase5_complete) as completeness_score
FROM completeness
ORDER BY date;
```

**Visualization:** Line graph showing completeness score (0-4) over time

---

**Panel 2: Row Count Trends**
```sql
-- Track row counts per phase over time
SELECT
  game_date,
  'Phase 2' as phase,
  COUNT(*) as row_count
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date

UNION ALL

SELECT game_date, 'Phase 3', COUNT(*)
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date

ORDER BY game_date, phase;
```

**Visualization:** Stacked area chart showing row counts per phase

---

## 🔗 Related Documentation

**Backfill Operations:**
- `docs/operations/01-backfill-operations-guide.md` - How to run backfills
- `docs/01-architecture/cross-date-dependencies.md` - Cross-date dependencies

**Monitoring:**
- `docs/monitoring/01-grafana-monitoring-guide.md` - Comprehensive monitoring
- `docs/monitoring/02-grafana-daily-health-check.md` - Quick daily check
- `docs/monitoring/04-observability-gaps-and-improvement-plan.md` - What's missing

**Troubleshooting:**
- `docs/processors/04-phase3-troubleshooting.md` - Phase 3 failures
- `docs/processors/07-phase4-troubleshooting.md` - Phase 4 failures

---

## 📝 Quick Reference

### Morning Checklist
- [ ] Run daily completeness query (Query 1)
- [ ] Check for ❌ or ⚠️ statuses
- [ ] If incomplete, run missing entities query (Query 4)
- [ ] If row counts off, run reconciliation query (Query 3)
- [ ] Take action based on findings

### Backfill Checklist
- [ ] Run range completeness query (Query 2)
- [ ] Count incomplete dates
- [ ] Validate each phase before starting next
- [ ] Run row count reconciliation per date
- [ ] Document any anomalies

### Alert Thresholds
- **Critical:** 0 rows in any phase for current day
- **High:** <80% expected row count
- **Medium:** Missing entities <5%
- **Low:** Row count variance 5-10%

---

**Created:** 2025-11-18
**Next Review:** After first historical backfill
**Status:** ✅ Ready to use
