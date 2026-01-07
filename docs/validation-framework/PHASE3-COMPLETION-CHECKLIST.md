# Phase 3 Analytics - Completion Checklist
**Purpose**: Ensure ALL Phase 3 tables are complete before declaring "DONE"
**Date**: _______________
**Operator**: _______________

---

## CRITICAL: All 5 Tables Required

Phase 3 has **EXACTLY 5 TABLES**. All must be ≥95% complete.

Missing even 1 table will break Phase 4 and ML training.

---

## Required Tables (5/5 must be checked)

### 1. player_game_summary
- [ ] **Coverage ≥95%**
  ```bash
  python bin/backfill/verify_phase3_for_phase4.py \
    --start-date 2021-10-19 \
    --end-date 2025-06-22 \
    --verbose
  ```
  Expected: ✅ player_game_summary: >95% coverage

- [ ] **Critical fields non-NULL**
  ```sql
  SELECT
    COUNTIF(minutes_played IS NULL) * 100.0 / COUNT(*) as minutes_null_pct,
    COUNTIF(usage_rate IS NULL) * 100.0 / COUNT(*) as usage_null_pct,
    COUNTIF(points IS NULL) * 100.0 / COUNT(*) as points_null_pct
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-19'
    AND game_date <= '2025-06-22'
    AND minutes_played > 0;
  ```
  Expected: minutes_null_pct <10%, usage_null_pct <55%, points_null_pct <1%

- [ ] **No duplicates**
  ```sql
  SELECT COUNT(*) as duplicate_count
  FROM (
    SELECT game_id, game_date, player_lookup, COUNT(*) as cnt
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= '2021-10-19'
    GROUP BY game_id, game_date, player_lookup
    HAVING COUNT(*) > 1
  );
  ```
  Expected: duplicate_count = 0

---

### 2. team_defense_game_summary ⚠️ PREVIOUSLY MISSED
- [ ] **Coverage ≥95%**
  ```sql
  WITH expected AS (
    SELECT COUNT(DISTINCT game_date) as expected_dates
    FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
    WHERE game_date >= '2021-10-19'
      AND game_date <= '2025-06-22'
  ),
  actual AS (
    SELECT COUNT(DISTINCT game_date) as actual_dates
    FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
    WHERE game_date >= '2021-10-19'
      AND game_date <= '2025-06-22'
  )
  SELECT
    expected_dates,
    actual_dates,
    ROUND(actual_dates * 100.0 / expected_dates, 1) as coverage_pct
  FROM expected, actual;
  ```
  Expected: coverage_pct ≥95.0

- [ ] **Team count correct**
  ```sql
  SELECT game_date, COUNT(DISTINCT team_abbr) as team_count
  FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
  WHERE game_date >= '2021-10-19'
    AND game_date <= '2025-06-22'
  GROUP BY game_date
  HAVING COUNT(DISTINCT team_abbr) < 20  -- Should have ~20-30 teams per game day
  LIMIT 10;
  ```
  Expected: 0 rows (all dates should have proper team counts)

- [ ] **Critical fields present**
  ```sql
  SELECT
    COUNTIF(defensive_rating IS NULL) as def_rating_nulls,
    COUNTIF(opponent_fg_pct IS NULL) as opp_fg_nulls,
    COUNTIF(turnovers_forced IS NULL) as to_forced_nulls
  FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
  WHERE game_date >= '2021-10-19'
    AND game_date <= '2025-06-22';
  ```
  Expected: All NULL counts <5% of total rows

---

### 3. team_offense_game_summary
- [ ] **Coverage ≥95%**
  ```sql
  WITH expected AS (
    SELECT COUNT(DISTINCT game_date) as expected_dates
    FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
    WHERE game_date >= '2021-10-19'
      AND game_date <= '2025-06-22'
  ),
  actual AS (
    SELECT COUNT(DISTINCT game_date) as actual_dates
    FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
    WHERE game_date >= '2021-10-19'
      AND game_date <= '2025-06-22'
  )
  SELECT
    expected_dates,
    actual_dates,
    ROUND(actual_dates * 100.0 / expected_dates, 1) as coverage_pct
  FROM expected, actual;
  ```
  Expected: coverage_pct ≥95.0

- [ ] **Team pace calculated**
  ```sql
  SELECT
    COUNTIF(team_pace IS NULL) * 100.0 / COUNT(*) as pace_null_pct,
    COUNTIF(offensive_rating IS NULL) * 100.0 / COUNT(*) as off_rating_null_pct
  FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
  WHERE game_date >= '2021-10-19'
    AND game_date <= '2025-06-22';
  ```
  Expected: Both <5%

- [ ] **No duplicates**
  ```sql
  SELECT COUNT(*) as duplicate_count
  FROM (
    SELECT game_id, game_date, team_abbr, COUNT(*) as cnt
    FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
    WHERE game_date >= '2021-10-19'
    GROUP BY game_id, game_date, team_abbr
    HAVING COUNT(*) > 1
  );
  ```
  Expected: duplicate_count = 0

---

### 4. upcoming_player_game_context ⚠️ PREVIOUSLY MISSED
- [ ] **Coverage ≥95%**
  ```sql
  WITH expected AS (
    SELECT COUNT(DISTINCT game_date) as expected_dates
    FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
    WHERE game_date >= '2021-10-19'
      AND game_date <= '2025-06-22'
  ),
  actual AS (
    SELECT COUNT(DISTINCT game_date) as actual_dates
    FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
    WHERE game_date >= '2021-10-19'
      AND game_date <= '2025-06-22'
  )
  SELECT
    expected_dates,
    actual_dates,
    ROUND(actual_dates * 100.0 / expected_dates, 1) as coverage_pct
  FROM expected, actual;
  ```
  Expected: coverage_pct ≥95.0

- [ ] **Player count reasonable**
  ```sql
  SELECT game_date, COUNT(DISTINCT player_lookup) as player_count
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date >= '2021-10-19'
    AND game_date <= '2025-06-22'
  GROUP BY game_date
  HAVING COUNT(DISTINCT player_lookup) < 100  -- Should have ~200-300 players per game day
  ORDER BY game_date DESC
  LIMIT 10;
  ```
  Expected: Very few rows (only early season dates might be low)

- [ ] **Prop line coverage tracked**
  ```sql
  SELECT
    COUNTIF(has_prop_line IS TRUE) as with_props,
    COUNTIF(has_prop_line IS FALSE OR has_prop_line IS NULL) as without_props,
    ROUND(COUNTIF(has_prop_line IS TRUE) * 100.0 / COUNT(*), 1) as prop_coverage_pct
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date >= '2021-10-19'
    AND game_date <= '2025-06-22';
  ```
  Expected: prop_coverage_pct ≥40% (BettingPros provides ~99% coverage as fallback)

---

### 5. upcoming_team_game_context ⚠️ PREVIOUSLY MISSED
- [ ] **Coverage ≥95%**
  ```sql
  WITH expected AS (
    SELECT COUNT(DISTINCT game_date) as expected_dates
    FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
    WHERE game_date >= '2021-10-19'
      AND game_date <= '2025-06-22'
  ),
  actual AS (
    SELECT COUNT(DISTINCT game_date) as actual_dates
    FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
    WHERE game_date >= '2021-10-19'
      AND game_date <= '2025-06-22'
  )
  SELECT
    expected_dates,
    actual_dates,
    ROUND(actual_dates * 100.0 / expected_dates, 1) as coverage_pct
  FROM expected, actual;
  ```
  Expected: coverage_pct ≥95.0

- [ ] **Betting lines present**
  ```sql
  SELECT
    COUNTIF(spread IS NOT NULL) as spread_count,
    COUNTIF(total IS NOT NULL) as total_count,
    COUNT(*) as total_rows,
    ROUND(COUNTIF(spread IS NOT NULL) * 100.0 / COUNT(*), 1) as spread_coverage_pct
  FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
  WHERE game_date >= '2021-10-19'
    AND game_date <= '2025-06-22';
  ```
  Expected: spread_coverage_pct ≥70% (not all games have betting lines)

- [ ] **Team count correct**
  ```sql
  SELECT game_date, COUNT(DISTINCT team_abbr) as team_count
  FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
  WHERE game_date >= '2021-10-19'
    AND game_date <= '2025-06-22'
  GROUP BY game_date
  HAVING COUNT(DISTINCT team_abbr) < 20
  LIMIT 10;
  ```
  Expected: 0 rows

---

## Automated Validation

### Run Comprehensive Validation
- [ ] **Pre-flight check (should PASS)**
  ```bash
  python bin/backfill/preflight_comprehensive.py \
    --target-phase 4 \
    --start-date 2021-10-19 \
    --end-date 2025-06-22
  ```
  Expected output:
  ```
  ✅ PRE-FLIGHT PASSED - SAFE TO PROCEED

  All checks passed. Ready to start Phase 4.
  ```

- [ ] **Post-flight validation report**
  ```bash
  python bin/backfill/postflight_comprehensive.py \
    --phase 3 \
    --start-date 2021-10-19 \
    --end-date 2025-06-22 \
    --report logs/phase3_final_validation.json
  ```
  Expected: All 5 tables show "COMPLETE" status

- [ ] **Review validation report**
  ```bash
  jq '.results[] | {table: .table_name, status: .status, coverage: .coverage_pct}' \
    logs/phase3_final_validation.json
  ```
  Expected: All tables show status="COMPLETE", coverage ≥95.0

---

## Data Quality Summary

Run this comprehensive quality check:

```sql
-- Phase 3 Quality Summary
WITH quality_metrics AS (
  SELECT
    'player_game_summary' as table_name,
    COUNT(DISTINCT game_date) as dates,
    COUNT(*) as rows,
    ROUND(AVG(quality_score), 1) as avg_quality,
    COUNTIF(minutes_played IS NULL) * 100.0 / COUNT(*) as minutes_null_pct
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-19' AND game_date <= '2025-06-22'

  UNION ALL

  SELECT
    'team_defense_game_summary' as table_name,
    COUNT(DISTINCT game_date) as dates,
    COUNT(*) as rows,
    ROUND(AVG(quality_score), 1) as avg_quality,
    0.0 as minutes_null_pct  -- N/A for team tables
  FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
  WHERE game_date >= '2021-10-19' AND game_date <= '2025-06-22'

  UNION ALL

  SELECT
    'team_offense_game_summary' as table_name,
    COUNT(DISTINCT game_date) as dates,
    COUNT(*) as rows,
    ROUND(AVG(quality_score), 1) as avg_quality,
    0.0 as minutes_null_pct
  FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
  WHERE game_date >= '2021-10-19' AND game_date <= '2025-06-22'

  UNION ALL

  SELECT
    'upcoming_player_game_context' as table_name,
    COUNT(DISTINCT game_date) as dates,
    COUNT(*) as rows,
    ROUND(AVG(quality_score), 1) as avg_quality,
    0.0 as minutes_null_pct
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date >= '2021-10-19' AND game_date <= '2025-06-22'

  UNION ALL

  SELECT
    'upcoming_team_game_context' as table_name,
    COUNT(DISTINCT game_date) as dates,
    COUNT(*) as rows,
    ROUND(AVG(quality_score), 1) as avg_quality,
    0.0 as minutes_null_pct
  FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
  WHERE game_date >= '2021-10-19' AND game_date <= '2025-06-22'
)
SELECT
  table_name,
  dates,
  rows,
  avg_quality,
  minutes_null_pct,
  CASE
    WHEN dates >= 1250 AND avg_quality >= 75.0 THEN '✅ COMPLETE'
    WHEN dates >= 1000 THEN '⚠️ PARTIAL'
    ELSE '❌ INCOMPLETE'
  END as status
FROM quality_metrics
ORDER BY table_name;
```

Expected output:
```
table_name                      | dates | rows   | avg_quality | status
--------------------------------|-------|--------|-------------|-------------
player_game_summary             | 1300  | 650000 | 85.2        | ✅ COMPLETE
team_defense_game_summary       | 1300  | 52000  | 88.5        | ✅ COMPLETE
team_offense_game_summary       | 1300  | 52000  | 89.1        | ✅ COMPLETE
upcoming_player_game_context    | 1300  | 780000 | 82.3        | ✅ COMPLETE
upcoming_team_game_context      | 1300  | 52000  | 86.7        | ✅ COMPLETE
```

---

## Dependencies Validation

### Verify Phase 4 Can Run
- [ ] **Test Phase 4 pre-flight**
  ```bash
  python bin/backfill/preflight_comprehensive.py \
    --target-phase 4 \
    --start-date 2024-01-01 \
    --end-date 2024-01-31 \
    --strict
  ```
  Expected: PASS (Phase 3 tables complete)

- [ ] **Sample Phase 4 backfill succeeds**
  ```bash
  # Test 1 date
  PYTHONPATH=. python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2024-01-15 \
    --end-date 2024-01-15
  ```
  Expected: No errors, records written

---

## Sign-Off

**I certify that:**
- [ ] All 5 Phase 3 tables are ≥95% complete
- [ ] All data quality checks passed
- [ ] No duplicates exist
- [ ] Phase 4 pre-flight validation passed
- [ ] Validation report saved and reviewed

**Sign-Off:**
- **Date**: _______________
- **Operator**: _______________
- **Validation Report**: `logs/phase3_final_validation.json`
- **Status**: ✅ PHASE 3 COMPLETE - Ready for Phase 4

---

## Troubleshooting

### If Coverage <95%

1. **Identify missing dates:**
   ```sql
   WITH expected_dates AS (
     SELECT DISTINCT game_date
     FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
     WHERE game_date >= '2021-10-19'
       AND game_date <= '2025-06-22'
   ),
   actual_dates AS (
     SELECT DISTINCT game_date
     FROM `nba-props-platform.nba_analytics.player_game_summary`
     WHERE game_date >= '2021-10-19'
       AND game_date <= '2025-06-22'
   )
   SELECT e.game_date as missing_date
   FROM expected_dates e
   LEFT JOIN actual_dates a ON e.game_date = a.game_date
   WHERE a.game_date IS NULL
   ORDER BY e.game_date
   LIMIT 50;
   ```

2. **Run incremental backfill for missing dates**
3. **Re-run validation**

### If Duplicates Found

1. **Identify duplicates:**
   ```sql
   SELECT game_id, game_date, player_lookup, COUNT(*) as dup_count
   FROM `nba-props-platform.nba_analytics.player_game_summary`
   GROUP BY game_id, game_date, player_lookup
   HAVING COUNT(*) > 1
   LIMIT 10;
   ```

2. **Run deduplication script**
3. **Re-run validation**

### If Phase 4 Pre-flight Fails

1. Check which Phase 3 table is incomplete
2. Backfill missing table
3. Re-run Phase 3 validation
4. Re-run Phase 4 pre-flight

---

**DO NOT declare Phase 3 "COMPLETE" until ALL items are checked! ✅**
