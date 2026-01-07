# COMPLETE BACKFILL EXECUTION PLAN
**Created**: January 5, 2026, 1:37 PM PST
**Target**: 100% pipeline backfill (Phases 3-6)
**Date Range**: 2021-10-19 to 2026-01-03 (918 dates)

---

## 🎯 EXECUTION OVERVIEW

**Total Time**: ~42 hours (Sunday 1:37 PM → Tuesday 7 AM)

**Phases to Complete**:
- Phase 3: 1 table remaining (13 hours)
- Phase 4: 5 tables (21 hours)
- Phase 5: 5 tables (6.5 hours)
- Phase 6: JSON exports (1 hour)

---

## 📋 STEP-BY-STEP EXECUTION PLAN

### ✅ STEP 0: CURRENT STATUS (In Progress)
**Status**: upcoming_player backfill running with optimization
**PID**: 3893319
**ETA**: Monday 2:00 AM PST

**Monitor Command**:
```bash
# Check status every hour
tail -100 /tmp/upcoming_player_parallel_optimized_20260105_131051.log | grep -E "PROGRESS:|Processing|Rate:"

# Check if still running
ps -p 3893319 -o pid,etime,%cpu,cmd
```

**What to Watch For**:
- Process should complete around Monday 2 AM
- If it crashes, restart with same command (has checkpoint)

---

### ✅ STEP 1: VALIDATE PHASE 3 COMPLETE
**When**: Monday 2:00 AM PST (after upcoming_player completes)
**Time**: 5 minutes

**Commands**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

# Run Phase 3 validation
python3 bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  --verbose

# Check exit code (MUST be 0)
echo "Exit code: $?"
```

**Expected Output**:
```
✅ ALL PHASE 3 TABLES READY FOR PHASE 4
Exit code: 0
```

**If Validation Fails**:
- Check which table is incomplete
- Re-run that specific table's backfill
- Re-validate before proceeding

---

### 🔄 STEP 2: PHASE 4 GROUP 1 (Parallel)
**When**: Monday 2:30 AM PST
**Duration**: 5 hours
**Tables**: team_defense_zone_analysis + player_shot_zone_analysis

**Terminal 1 - Team Defense Zone Analysis**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

nohup python3 backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  > /tmp/phase4_tdza_$(date +%Y%m%d_%H%M%S).log 2>&1 &

echo "TDZA PID: $!"
```

**Terminal 2 - Player Shot Zone Analysis**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

nohup python3 backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  > /tmp/phase4_psza_$(date +%Y%m%d_%H%M%S).log 2>&1 &

echo "PSZA PID: $!"
```

**Monitor**:
```bash
# Check both processes
ps aux | grep -E "team_defense_zone|player_shot_zone" | grep -v grep

# Watch logs
tail -f /tmp/phase4_tdza_*.log
tail -f /tmp/phase4_psza_*.log
```

**Wait for BOTH to complete** before proceeding.

---

### 🔄 STEP 3: PHASE 4 GROUP 2 (Sequential)
**When**: Monday 7:30 AM PST (after Group 1 completes)
**Duration**: 10 hours
**Table**: player_composite_factors (SLOWEST processor)

**Command**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

nohup python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  > /tmp/phase4_pcf_$(date +%Y%m%d_%H%M%S).log 2>&1 &

echo "PCF PID: $!"
```

**Monitor**:
```bash
tail -f /tmp/phase4_pcf_*.log | grep -E "Processing date|✓|✗"
```

**Note**: This is the longest-running Phase 4 processor. Be patient.

---

### 🔄 STEP 4: PHASE 4 GROUP 3 (Sequential)
**When**: Monday 5:30 PM PST (after Group 2 completes)
**Duration**: 3 hours
**Table**: player_daily_cache

**Command**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

nohup python3 backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  > /tmp/phase4_pdc_$(date +%Y%m%d_%H%M%S).log 2>&1 &

echo "PDC PID: $!"
```

---

### 🔄 STEP 5: PHASE 4 GROUP 4 (Sequential - FINAL)
**When**: Monday 8:30 PM PST (after Group 3 completes)
**Duration**: 3 hours
**Table**: ml_feature_store_v2

**Command**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

nohup python3 backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  > /tmp/phase4_mlfs_$(date +%Y%m%d_%H%M%S).log 2>&1 &

echo "MLFS PID: $!"
```

---

### ✅ STEP 6: VALIDATE PHASE 4 COMPLETE
**When**: Monday 11:30 PM PST (after all Phase 4 completes)
**Time**: 5 minutes

**Commands**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

# Validate Phase 4 coverage
bq query --use_legacy_sql=false "
SELECT 
  'team_defense_zone_analysis' as table,
  COUNT(DISTINCT analysis_date) as dates
FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date >= '2021-10-19'
UNION ALL
SELECT 'player_shot_zone_analysis', COUNT(DISTINCT analysis_date)
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date >= '2021-10-19'
UNION ALL
SELECT 'player_composite_factors', COUNT(DISTINCT analysis_date)
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE analysis_date >= '2021-10-19'
UNION ALL
SELECT 'player_daily_cache', COUNT(DISTINCT cache_date)
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= '2021-10-19'
UNION ALL
SELECT 'ml_feature_store_v2', COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date >= '2021-10-19'
ORDER BY table
"
```

**Expected**: All tables should have ~848-918 dates (accounting for bootstrap periods)

---

### 🔄 STEP 7: PHASE 5A - PREDICTIONS BACKFILL
**When**: Tuesday 12:00 AM PST (after Phase 4 validated)
**Duration**: 5 hours
**Table**: player_prop_predictions

**Command**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

nohup python3 backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  > /tmp/phase5a_predictions_$(date +%Y%m%d_%H%M%S).log 2>&1 &

echo "Predictions PID: $!"
```

**Monitor**:
```bash
tail -f /tmp/phase5a_predictions_*.log | grep -E "Processing date|systems|✓|✗"
```

**Note**: Generates predictions using all 5 ML systems for 498 missing dates.

---

### 🔄 STEP 8: PHASE 5B - GRADING BACKFILL
**When**: Tuesday 5:00 AM PST (after Phase 5A completes)
**Duration**: 30 minutes
**Tables**: prediction_accuracy, system_daily_performance, prediction_performance_summary

**Command**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

# Grade predictions against actual results
nohup python3 backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  > /tmp/phase5b_grading_$(date +%Y%m%d_%H%M%S).log 2>&1 &

echo "Grading PID: $!"
```

**Note**: This also triggers system_daily_performance and prediction_performance_summary aggregations.

---

### 🔄 STEP 9: PHASE 5C - ML FEEDBACK BACKFILL
**When**: Tuesday 5:30 AM PST (after Phase 5B completes)
**Duration**: 30 minutes
**Table**: scoring_tier_adjustments

**Command**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

nohup python3 backfill_jobs/ml_feedback/scoring_tier_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  > /tmp/phase5c_feedback_$(date +%Y%m%d_%H%M%S).log 2>&1 &

echo "ML Feedback PID: $!"
```

---

### 🔄 STEP 10: PHASE 6 - PUBLISHING EXPORTS
**When**: Tuesday 6:00 AM PST (after Phase 5 completes)
**Duration**: 1 hour
**Output**: JSON files to GCS

**Command**:
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=.

# Export all dates with graded predictions to GCS
nohup python3 backfill_jobs/publishing/daily_export.py \
  --backfill-all \
  > /tmp/phase6_exports_$(date +%Y%m%d_%H%M%S).log 2>&1 &

echo "Exports PID: $!"
```

**Monitor**:
```bash
tail -f /tmp/phase6_exports_*.log
```

**Verify**:
```bash
# Check exported files
gsutil ls gs://nba-props-platform-api/v1/results/ | wc -l
# Should be ~918 files
```

---

### ✅ STEP 11: FINAL VALIDATION
**When**: Tuesday 7:00 AM PST
**Duration**: 10 minutes

**Check All Tables**:
```bash
# Phase 3
bq query --use_legacy_sql=false "
SELECT 'Phase 3' as phase, 'player_game_summary' as table, COUNT(DISTINCT game_date) as dates FROM \`nba-props-platform.nba_analytics.player_game_summary\` WHERE game_date >= '2021-10-19'
UNION ALL SELECT 'Phase 3', 'team_offense', COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\` WHERE game_date >= '2021-10-19'
UNION ALL SELECT 'Phase 3', 'team_defense', COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\` WHERE game_date >= '2021-10-19'
UNION ALL SELECT 'Phase 3', 'upcoming_player', COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\` WHERE game_date >= '2021-10-19'
UNION ALL SELECT 'Phase 3', 'upcoming_team', COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\` WHERE game_date >= '2021-10-19'
UNION ALL SELECT 'Phase 4', 'tdza', COUNT(DISTINCT analysis_date) FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\` WHERE analysis_date >= '2021-10-19'
UNION ALL SELECT 'Phase 4', 'psza', COUNT(DISTINCT analysis_date) FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\` WHERE analysis_date >= '2021-10-19'
UNION ALL SELECT 'Phase 4', 'pcf', COUNT(DISTINCT analysis_date) FROM \`nba-props-platform.nba_precompute.player_composite_factors\` WHERE analysis_date >= '2021-10-19'
UNION ALL SELECT 'Phase 4', 'pdc', COUNT(DISTINCT cache_date) FROM \`nba-props-platform.nba_precompute.player_daily_cache\` WHERE cache_date >= '2021-10-19'
UNION ALL SELECT 'Phase 4', 'mlfs', COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\` WHERE game_date >= '2021-10-19'
UNION ALL SELECT 'Phase 5', 'predictions', COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` WHERE game_date >= '2021-10-19'
UNION ALL SELECT 'Phase 5', 'accuracy', COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` WHERE game_date >= '2021-10-19'
ORDER BY phase, table
"
```

**Expected Results**:
- Phase 3: All 5 tables with 918 dates
- Phase 4: All 5 tables with ~848-918 dates (bootstrap exclusions normal)
- Phase 5: All tables with ~848-918 dates

---

## 🚨 CRITICAL NOTES

### Dependencies - DO NOT SKIP PHASES
1. **Phase 4 requires Phase 3 to be 100% complete**
2. **Phase 5 requires Phase 4 to be 100% complete**
3. **Phase 6 requires Phase 5B (grading) to be complete**

### Within Phase 4 - STRICT ORDERING
1. Group 1 (parallel) → Group 2 → Group 3 → Group 4
2. **DO NOT start Group 2 until BOTH Group 1 processors finish**
3. Each group depends on previous groups

### If Something Fails
- All backfill scripts have checkpoint support
- Simply re-run the same command - it will resume from checkpoint
- Check logs for errors before re-running

### Monitoring Commands
```bash
# Check all running backfills
ps aux | grep -E "backfill|player_composite|ml_feature" | grep -v grep

# Check CPU/memory usage
top -u naji

# Disk space check
df -h /home/naji/code/nba-stats-scraper
```

---

## ✅ SUCCESS CRITERIA

**100% Complete Pipeline** means:
- ✅ All Phase 3 tables: ≥918 dates
- ✅ All Phase 4 tables: ≥848 dates (accounting for bootstrap)
- ✅ All Phase 5 tables: ≥848 dates
- ✅ Phase 6: ~918 JSON files exported to GCS
- ✅ All backfill logs show "COMPLETE" with 0 critical failures

**ETA: Tuesday, January 7, 2026 at 7:00 AM PST**

---

## 📞 QUICK REFERENCE

**Date Range**: 2021-10-19 to 2026-01-03
**Total Dates**: 918
**Project ID**: nba-props-platform
**Working Dir**: /home/naji/code/nba-stats-scraper
**Log Dir**: /tmp/

**Current Running Backfill**:
- Process: upcoming_player (Phase 3)
- PID: 3893319
- Log: /tmp/upcoming_player_parallel_optimized_20260105_131051.log
- ETA: Monday 2 AM PST
