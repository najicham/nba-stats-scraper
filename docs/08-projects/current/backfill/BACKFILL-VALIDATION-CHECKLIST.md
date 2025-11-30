# Backfill Validation Checklist

**Created:** 2025-11-29
**Purpose:** Quality gates and validation procedures for backfill execution
**Related:** BACKFILL-MASTER-EXECUTION-GUIDE.md

---

## 📋 Table of Contents

1. [Pre-Backfill Validation](#pre-backfill-validation)
2. [Stage 1 Validation](#stage-1-validation)
3. [Stage 2 Validation](#stage-2-validation)
4. [Stage 3 Validation](#stage-3-validation)
5. [Final Sign-Off](#final-sign-off)

---

## 🔍 Pre-Backfill Validation (Gate 0) {#pre-backfill-validation}

**Must complete BEFORE starting Stage 1**

### Infrastructure Checks

- [ ] **Schemas Verified**
  ```bash
  ./bin/verify_schemas.sh
  ```
  Expected: `✅ All schemas verified`

- [ ] **v1.0 Deployed and Active**
  ```bash
  gcloud functions describe phase2-to-phase3-orchestrator --region=us-west2 --gen2
  gcloud functions describe phase3-to-phase4-orchestrator --region=us-west2 --gen2
  gcloud run services describe prediction-coordinator --region=us-west2
  ```
  Expected: All show `ACTIVE` or `Ready`

- [ ] **Backfill Scripts Exist**
  ```bash
  ./bin/run_backfill.sh --list | grep analytics
  ```
  Expected: Shows all 5 analytics processors

- [ ] **Alert Suppression Verified**
  ```bash
  grep -n "backfill_mode" shared/utils/notification_system.py
  ```
  Expected: Function exists with backfill_mode parameter

### Data State Checks

- [ ] **Phase 2 Completeness: 100%**
  ```sql
  -- Run Query #13 from BACKFILL-GAP-ANALYSIS.md
  ```
  Expected: `gate_status = '✅ READY TO START'`

  **If fails:** STOP - Cannot proceed with incomplete Phase 2

- [ ] **Phase 3 Gaps Identified**
  ```bash
  bq query --use_legacy_sql=false --format=csv --max_rows=1000 \
    "SELECT s.game_date FROM ..." > phase3_missing_dates.csv
  wc -l phase3_missing_dates.csv
  ```
  Expected: ~328 lines (327 dates + header)

- [ ] **No Active Backfills Running**
  ```bash
  ps aux | grep backfill
  ```
  Expected: No other backfill processes

### Test Run

- [ ] **Single Date Test Successful**
  ```bash
  TEST_DATE="2023-11-01"
  ./bin/run_backfill.sh analytics/player_game_summary \
    --start-date=$TEST_DATE \
    --end-date=$TEST_DATE \
    --skip-downstream-trigger=true
  ```
  Expected: Completes successfully

- [ ] **Test Data Verified**
  ```sql
  SELECT COUNT(*) as row_count
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date = '2023-11-01'
  ```
  Expected: row_count > 0

### Documentation Prepared

- [ ] **Execution log started**
  ```bash
  cat > docs/09-handoff/2025-11-XX-backfill-execution-log.md <<EOF
  # Backfill Execution Log
  Started: $(date)
  EOF
  ```

- [ ] **Terminal multiplexer ready** (tmux or screen)
  ```bash
  tmux new -s backfill
  ```

### Pre-Backfill Sign-Off

**Date:** ___________
**Completed by:** ___________
**All checks passed:** [ ] YES / [ ] NO

**If NO, list issues:**
_______________________________________

**If YES, proceed to Stage 1**

---

## ✅ Stage 1 Validation (Gate 1 - Phase 3 Complete) {#stage-1-validation}

**Must complete BEFORE starting Stage 2**

### Completion Verification

- [ ] **Phase 3 Completeness: 100%**
  ```sql
  -- Run Query #14 from BACKFILL-GAP-ANALYSIS.md
  WITH schedule AS (
    SELECT COUNT(DISTINCT game_date) as total_dates
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE game_status = 3
      AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
  ),
  phase3 AS (
    SELECT COUNT(DISTINCT game_date) as phase3_dates
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
  )
  SELECT
    s.total_dates,
    p3.phase3_dates,
    s.total_dates - p3.phase3_dates as missing_dates,
    ROUND(100.0 * p3.phase3_dates / s.total_dates, 1) as completeness_pct,
    CASE
      WHEN p3.phase3_dates = s.total_dates THEN '✅ READY FOR STAGE 2'
      ELSE '⚠️ STAGE 1 INCOMPLETE'
    END as gate_status
  FROM schedule s, phase3 p3
  ```

  **Expected Results:**
  - `total_dates = 638`
  - `phase3_dates = 638`
  - `missing_dates = 0`
  - `completeness_pct = 100.0`
  - `gate_status = '✅ READY FOR STAGE 2'`

  **If fails:** Review BACKFILL-FAILURE-RECOVERY.md

- [ ] **All Phase 3 Tables Complete**
  ```sql
  -- Run Query #16 from BACKFILL-GAP-ANALYSIS.md
  ```
  Expected: All 5 tables show 100% completeness

### Success Rate Verification

- [ ] **All Processors > 99% Success Rate**
  ```sql
  SELECT
    processor_name,
    COUNT(*) as total_runs,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed,
    ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE phase = 'phase_3_analytics'
    AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  GROUP BY processor_name
  ORDER BY processor_name
  ```

  **Expected:** All processors show `success_rate >= 99.0`

- [ ] **No Unresolved Failures**
  ```sql
  -- Run Query #9 from BACKFILL-GAP-ANALYSIS.md
  ```
  Expected: Returns 0 rows (no unresolved failures)

### Data Quality Spot Checks

- [ ] **Row Count Sanity Check**
  ```sql
  SELECT
    EXTRACT(YEAR FROM game_date) as year,
    COUNT(*) as total_rows,
    COUNT(DISTINCT game_date) as unique_dates,
    COUNT(DISTINCT player_lookup) as unique_players,
    ROUND(AVG(points), 1) as avg_points
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
  GROUP BY year
  ORDER BY year
  ```

  **Sanity checks:**
  - unique_dates matches expected for each year
  - avg_points between 8-12 (reasonable average)
  - unique_players > 300 per year

- [ ] **Random Date Spot Check**
  ```sql
  -- Pick 3 random dates and verify data looks good
  SELECT *
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date IN ('2021-11-15', '2022-03-20', '2023-12-10')
  ORDER BY game_date, player_lookup
  LIMIT 20
  ```

  **Check for:**
  - No NULL values in critical fields
  - Data looks reasonable
  - Player names resolved correctly

- [ ] **No Duplicate Records**
  ```sql
  SELECT
    game_date,
    player_lookup,
    COUNT(*) as duplicate_count
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
  GROUP BY game_date, player_lookup
  HAVING COUNT(*) > 1
  ORDER BY duplicate_count DESC
  LIMIT 10
  ```

  Expected: Returns 0 rows (no duplicates)

### Stage 1 Sign-Off

**Date:** ___________
**Completed by:** ___________
**Phase 3 backfill complete:** [ ] YES / [ ] NO

**Metrics:**
- Total dates: _____ / 638
- Success rate: _____%
- Failures: _____

**If all checks passed, proceed to Stage 2**

---

## ✅ Stage 2 Validation (Gate 2 - Phase 4 Complete) {#stage-2-validation}

**Must complete BEFORE starting Stage 3**

### Completion Verification

- [ ] **Phase 4 Completeness: 100%**
  ```sql
  -- Run Query #15 from BACKFILL-GAP-ANALYSIS.md
  WITH schedule AS (
    SELECT COUNT(DISTINCT game_date) as total_dates
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE game_status = 3
      AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
  ),
  phase4 AS (
    SELECT COUNT(DISTINCT game_date) as phase4_dates
    FROM `nba-props-platform.nba_precompute.player_composite_factors`
    WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
  )
  SELECT
    s.total_dates,
    p4.phase4_dates,
    s.total_dates - p4.phase4_dates as missing_dates,
    ROUND(100.0 * p4.phase4_dates / s.total_dates, 1) as completeness_pct,
    CASE
      WHEN p4.phase4_dates = s.total_dates THEN '✅ READY FOR STAGE 3'
      ELSE '⚠️ STAGE 2 INCOMPLETE'
    END as gate_status
  FROM schedule s, phase4 p4
  ```

  **Expected Results:**
  - `total_dates = 638`
  - `phase4_dates = 638`
  - `missing_dates = 0`
  - `completeness_pct = 100.0`
  - `gate_status = '✅ READY FOR STAGE 3'`

- [ ] **All Phase 4 Tables Complete**
  ```sql
  WITH schedule AS (
    SELECT COUNT(DISTINCT game_date) as total_dates
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE game_status = 3
      AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
  )
  SELECT
    'player_composite_factors' as table_name,
    COUNT(DISTINCT game_date) as dates,
    (SELECT total_dates FROM schedule) as expected,
    ROUND(100.0 * COUNT(DISTINCT game_date) / (SELECT total_dates FROM schedule), 1) as pct
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"

  UNION ALL

  SELECT
    'player_daily_cache' as table_name,
    COUNT(DISTINCT cache_date) as dates,
    (SELECT total_dates FROM schedule) as expected,
    ROUND(100.0 * COUNT(DISTINCT cache_date) / (SELECT total_dates FROM schedule), 1) as pct
  FROM `nba-props-platform.nba_precompute.player_daily_cache`
  WHERE cache_date BETWEEN "2020-10-01" AND "2024-06-30"

  UNION ALL

  SELECT
    'player_shot_zone_analysis' as table_name,
    COUNT(DISTINCT analysis_date) as dates,
    (SELECT total_dates FROM schedule) as expected,
    ROUND(100.0 * COUNT(DISTINCT analysis_date) / (SELECT total_dates FROM schedule), 1) as pct
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date BETWEEN "2020-10-01" AND "2024-06-30"

  UNION ALL

  SELECT
    'team_defense_zone_analysis' as table_name,
    COUNT(DISTINCT analysis_date) as dates,
    (SELECT total_dates FROM schedule) as expected,
    ROUND(100.0 * COUNT(DISTINCT analysis_date) / (SELECT total_dates FROM schedule), 1) as pct
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date BETWEEN "2020-10-01" AND "2024-06-30"

  ORDER BY table_name
  ```

  Expected: All tables show 100% (or close to it)

### Success Rate Verification

- [ ] **Phase 4 Processors > 99% Success Rate**
  ```sql
  SELECT
    processor_name,
    COUNT(*) as total_runs,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed,
    ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE phase = 'phase_4_precompute'
    AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
  GROUP BY processor_name
  ORDER BY processor_name
  ```

  Expected: All processors show `success_rate >= 99.0`

### Data Quality Spot Checks

- [ ] **Composite Factors Range Check**
  ```sql
  SELECT
    MIN(fatigue_adjustment) as min_fatigue,
    MAX(fatigue_adjustment) as max_fatigue,
    AVG(fatigue_adjustment) as avg_fatigue,
    MIN(shot_zone_adjustment) as min_shot_zone,
    MAX(shot_zone_adjustment) as max_shot_zone,
    AVG(shot_zone_adjustment) as avg_shot_zone
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"
  ```

  **Sanity checks:**
  - Adjustments within reasonable ranges (e.g., -2.0 to +2.0)
  - No extreme outliers

- [ ] **Player Daily Cache Freshness**
  ```sql
  SELECT
    cache_date,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(*) as total_records
  FROM `nba-props-platform.nba_precompute.player_daily_cache`
  WHERE cache_date BETWEEN "2020-10-01" AND "2024-06-30"
  GROUP BY cache_date
  ORDER BY cache_date DESC
  LIMIT 10
  ```

  **Check:**
  - Recent dates have 400-500 unique players (active players)
  - Older dates may have fewer (retired players)

### Stage 2 Sign-Off

**Date:** ___________
**Completed by:** ___________
**Phase 4 backfill complete:** [ ] YES / [ ] NO

**Metrics:**
- Total dates: _____ / 638
- Success rate: _____%
- Failures: _____

**If all checks passed, proceed to Stage 3**

---

## ✅ Stage 3 Validation (Gate 3 - End-to-End) {#stage-3-validation}

**Final validation before declaring backfill complete**

### Current Season Validation

- [ ] **Current Season Data Up-to-Date**
  ```sql
  WITH schedule AS (
    SELECT COUNT(DISTINCT game_date) as total_dates
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE game_status = 3
      AND game_date >= '2024-10-01'
  ),
  phase3 AS (
    SELECT COUNT(DISTINCT game_date) as phase3_dates
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= '2024-10-01'
  ),
  phase4 AS (
    SELECT COUNT(DISTINCT game_date) as phase4_dates
    FROM `nba-props-platform.nba_precompute.player_composite_factors`
    WHERE game_date >= '2024-10-01'
  )
  SELECT
    s.total_dates,
    p3.phase3_dates,
    p4.phase4_dates,
    CASE
      WHEN p3.phase3_dates >= s.total_dates - 2 AND p4.phase4_dates >= s.total_dates - 2
      THEN '✅ Current season ready'
      ELSE '⚠️ Current season incomplete'
    END as status
  FROM schedule s, phase3 p3, phase4 p4
  ```

  Expected: `status = '✅ Current season ready'`

### Orchestrator Validation

- [ ] **Phase 2→3 Orchestrator Functioning**
  ```bash
  gcloud functions logs read phase2-to-phase3-orchestrator \
    --region=us-west2 \
    --limit=10
  ```

  Check: Recent successful orchestrations

- [ ] **Phase 3→4 Orchestrator Functioning**
  ```bash
  gcloud functions logs read phase3-to-phase4-orchestrator \
    --region=us-west2 \
    --limit=10
  ```

  Check: Recent successful orchestrations

### End-to-End Test

- [ ] **Test Phase 2→3→4 Cascade**
  ```bash
  # Pick recent test date
  TEST_DATE="2024-11-28"

  # Verify Phase 2 exists
  bq query --use_legacy_sql=false "
  SELECT COUNT(*) as count
  FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
  WHERE game_date = '$TEST_DATE'
  "

  # Delete Phase 3 & 4 for test date
  bq query --use_legacy_sql=false "
  DELETE FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date = '$TEST_DATE'
  "
  bq query --use_legacy_sql=false "
  DELETE FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
  WHERE game_date = '$TEST_DATE'
  "

  # Trigger Phase 3 (without skip_downstream_trigger - let orchestrator work)
  ./bin/run_backfill.sh analytics/player_game_summary \
    --start-date=$TEST_DATE \
    --end-date=$TEST_DATE

  # Wait 5 minutes for Phase 4 to auto-trigger
  sleep 300

  # Verify Phase 3 exists
  bq query --use_legacy_sql=false "
  SELECT COUNT(*) as count
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date = '$TEST_DATE'
  "
  # Expected: count > 0

  # Verify Phase 4 exists (auto-triggered)
  bq query --use_legacy_sql=false "
  SELECT COUNT(*) as count
  FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
  WHERE game_date = '$TEST_DATE'
  "
  # Expected: count > 0
  ```

  **Result:** [ ] Phase 3→4 cascade working

### Final Completeness Summary

- [ ] **Overall System Completeness**
  ```sql
  WITH schedule AS (
    SELECT COUNT(DISTINCT game_date) as total
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE game_status = 3
      AND game_date BETWEEN "2020-10-01" AND "2024-06-30"
  )
  SELECT
    'Phase 2 (Raw)' as phase,
    COUNT(DISTINCT game_date) as complete,
    (SELECT total FROM schedule) as expected,
    ROUND(100.0 * COUNT(DISTINCT game_date) / (SELECT total FROM schedule), 1) as pct
  FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"

  UNION ALL

  SELECT
    'Phase 3 (Analytics)' as phase,
    COUNT(DISTINCT game_date) as complete,
    (SELECT total FROM schedule) as expected,
    ROUND(100.0 * COUNT(DISTINCT game_date) / (SELECT total FROM schedule), 1) as pct
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"

  UNION ALL

  SELECT
    'Phase 4 (Precompute)' as phase,
    COUNT(DISTINCT game_date) as complete,
    (SELECT total FROM schedule) as expected,
    ROUND(100.0 * COUNT(DISTINCT game_date) / (SELECT total FROM schedule), 1) as pct
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN "2020-10-01" AND "2024-06-30"

  ORDER BY phase
  ```

  **Expected:**
  ```
  phase                 | complete | expected | pct
  ----------------------|----------|----------|------
  Phase 2 (Raw)         | 638      | 638      | 100.0
  Phase 3 (Analytics)   | 638      | 638      | 100.0
  Phase 4 (Precompute)  | 638      | 638      | 100.0
  ```

### Stage 3 Sign-Off

**Date:** ___________
**Completed by:** ___________
**End-to-end validation passed:** [ ] YES / [ ] NO

**If all checks passed, proceed to Final Sign-Off**

---

## 🎉 Final Sign-Off {#final-sign-off}

### Backfill Completion Declaration

**I certify that:**

- [ ] All 638 game dates from 2020-10-01 to 2024-06-30 have been backfilled
- [ ] Phase 3 analytics: 100% complete (638/638 dates)
- [ ] Phase 4 precompute: 100% complete (638/638 dates)
- [ ] All quality gates passed
- [ ] No unresolved failures
- [ ] Current season (2024-25) up-to-date
- [ ] Orchestrators functioning correctly
- [ ] End-to-end cascade tested and working
- [ ] Data quality spot checks passed
- [ ] Execution documented

**Backfill Statistics:**
- Start date: ___________
- End date: ___________
- Total duration: ___________ hours
- Stage 1 duration: ___________ hours
- Stage 2 duration: ___________ hours
- Total failures encountered: ___________
- Total failures resolved: ___________
- Final success rate: ___________%

**Signed:** ___________
**Date:** ___________

### Post-Backfill Actions

- [ ] **Archive execution logs**
  ```bash
  cp backfill_phase3_*.log docs/09-handoff/archive/
  ```

- [ ] **Create completion handoff document**
  ```bash
  # File: docs/09-handoff/2025-11-XX-backfill-complete.md
  ```

- [ ] **Update system documentation**
  - Mark backfill as complete in project status docs
  - Update data coverage documentation
  - Note any lessons learned

- [ ] **Enable daily production processing**
  - Orchestrators already enabled
  - Monitor for next few days
  - Ensure new dates process automatically

- [ ] **Schedule follow-up review**
  - Review in 1 week
  - Verify no issues with historical data
  - Check predictions using historical context

---

**BACKFILL COMPLETE! 🎉**

---

**Document Version:** 1.0
**Last Updated:** 2025-11-29
**Related Docs:**
- BACKFILL-MASTER-EXECUTION-GUIDE.md
- BACKFILL-GAP-ANALYSIS.md
- BACKFILL-FAILURE-RECOVERY.md
