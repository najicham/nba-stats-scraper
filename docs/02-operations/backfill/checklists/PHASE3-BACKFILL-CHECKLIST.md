# Phase 3 Backfill Execution Checklist

**Purpose**: Quick reference for executing Option B (Complete Phase 3 First)
**Time Required**: 2-3 hours
**Status**: Ready to execute

---

## PRE-FLIGHT CHECKLIST

### Environment Setup
- [ ] In working directory: `/home/naji/code/nba-stats-scraper`
- [ ] Virtual environment activated: `source .venv/bin/activate`
- [ ] GCP auth verified: `gcloud auth application-default print-access-token`
- [ ] BigQuery access confirmed: `bq ls -p nba-props-platform`

### System Resources
- [ ] Disk space available: `df -h . | grep -v Filesystem` (need >10GB)
- [ ] No conflicting processes: `ps aux | grep backfill | grep -v grep`
- [ ] Log directory exists: `ls logs/` or `mkdir -p logs`

---

## EXECUTION CHECKLIST

### Step 1: Launch Parallel Backfills (5 min)

**Terminal 1: team_defense (CRITICAL)**
```bash
cd /home/naji/code/nba-stats-scraper
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

nohup PYTHONPATH=. python3 backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-02 \
  > logs/team_defense_backfill_${TIMESTAMP}.log 2>&1 &

echo $! > /tmp/team_defense_backfill.pid
echo "✅ team_defense started (PID: $(cat /tmp/team_defense_backfill.pid))"
```
- [ ] Process started successfully
- [ ] PID saved to `/tmp/team_defense_backfill.pid`
- [ ] Log file created in `logs/`

**Terminal 2: upcoming_player**
```bash
cd /home/naji/code/nba-stats-scraper
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

nohup PYTHONPATH=. python3 backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-02 \
  > logs/upcoming_player_backfill_${TIMESTAMP}.log 2>&1 &

echo $! > /tmp/upcoming_player_backfill.pid
echo "✅ upcoming_player started (PID: $(cat /tmp/upcoming_player_backfill.pid))"
```
- [ ] Process started successfully
- [ ] PID saved to `/tmp/upcoming_player_backfill.pid`
- [ ] Log file created in `logs/`

**Terminal 3: upcoming_team**
```bash
cd /home/naji/code/nba-stats-scraper
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

nohup PYTHONPATH=. python3 backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_backfill_job.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-02 \
  > logs/upcoming_team_backfill_${TIMESTAMP}.log 2>&1 &

echo $! > /tmp/upcoming_team_backfill.pid
echo "✅ upcoming_team started (PID: $(cat /tmp/upcoming_team_backfill.pid))"
```
- [ ] Process started successfully
- [ ] PID saved to `/tmp/upcoming_team_backfill.pid`
- [ ] Log file created in `logs/`

**Verify All Running**
```bash
ps aux | grep -E "team_defense|upcoming_player|upcoming_team" | grep backfill | grep -v grep
```
- [ ] 3 processes shown (one for each backfill)

---

### Step 2: Monitor Progress (Ongoing)

**Setup Monitoring**
```bash
# Create monitoring script
cat > /tmp/monitor_phase3.sh << 'EOF'
#!/bin/bash
while true; do
  clear
  echo "=== PHASE 3 BACKFILL PROGRESS ==="
  echo "$(date)"
  echo ""

  echo "1. TEAM DEFENSE (CRITICAL):"
  if ls logs/team_defense_backfill_*.log 1> /dev/null 2>&1; then
    LATEST_TEAM_DEF=$(ls -t logs/team_defense_backfill_*.log | head -1)
    tail -5 "$LATEST_TEAM_DEF" | grep -E "Processing day|Progress|Success|Complete" | tail -3 || echo "  [Starting or no recent output...]"
  else
    echo "  [No log file found]"
  fi
  echo ""

  echo "2. UPCOMING PLAYER:"
  if ls logs/upcoming_player_backfill_*.log 1> /dev/null 2>&1; then
    LATEST_PLAYER=$(ls -t logs/upcoming_player_backfill_*.log | head -1)
    tail -5 "$LATEST_PLAYER" | grep -E "Processing date|Success|Complete" | tail -3 || echo "  [Starting or no recent output...]"
  else
    echo "  [No log file found]"
  fi
  echo ""

  echo "3. UPCOMING TEAM:"
  if ls logs/upcoming_team_backfill_*.log 1> /dev/null 2>&1; then
    LATEST_TEAM=$(ls -t logs/upcoming_team_backfill_*.log | head -1)
    tail -5 "$LATEST_TEAM" | grep -E "Processing date|Success|Complete" | tail -3 || echo "  [Starting or no recent output...]"
  else
    echo "  [No log file found]"
  fi
  echo ""

  # Check if processes still running
  TEAM_DEF_RUNNING=$(ps -p $(cat /tmp/team_defense_backfill.pid 2>/dev/null) -o pid= 2>/dev/null | wc -l)
  PLAYER_RUNNING=$(ps -p $(cat /tmp/upcoming_player_backfill.pid 2>/dev/null) -o pid= 2>/dev/null | wc -l)
  TEAM_RUNNING=$(ps -p $(cat /tmp/upcoming_team_backfill.pid 2>/dev/null) -o pid= 2>/dev/null | wc -l)

  echo "=== PROCESS STATUS ==="
  echo "team_defense: $([ $TEAM_DEF_RUNNING -eq 1 ] && echo '✅ RUNNING' || echo '⏸️  STOPPED')"
  echo "upcoming_player: $([ $PLAYER_RUNNING -eq 1 ] && echo '✅ RUNNING' || echo '⏸️  STOPPED')"
  echo "upcoming_team: $([ $TEAM_RUNNING -eq 1 ] && echo '✅ RUNNING' || echo '⏸️  STOPPED')"
  echo ""

  if [ $TEAM_DEF_RUNNING -eq 0 ] && [ $PLAYER_RUNNING -eq 0 ] && [ $TEAM_RUNNING -eq 0 ]; then
    echo "✅ ALL PROCESSES COMPLETE"
    break
  fi

  echo "Press Ctrl+C to exit monitoring (processes continue in background)"
  sleep 60
done
EOF

chmod +x /tmp/monitor_phase3.sh
```
- [ ] Monitoring script created

**Run Monitoring**
```bash
/tmp/monitor_phase3.sh
```
- [ ] Monitoring shows all 3 processes running
- [ ] Progress updates visible every 60 seconds

**Manual Progress Checks**
```bash
# Quick status
ps aux | grep -E "team_defense|upcoming_player|upcoming_team" | grep backfill | grep -v grep

# Check log tail
tail -20 logs/team_defense_backfill_*.log
tail -20 logs/upcoming_player_backfill_*.log
tail -20 logs/upcoming_team_backfill_*.log

# Count success records
grep -c "Success:" logs/team_defense_backfill_*.log
grep -c "Success:" logs/upcoming_player_backfill_*.log
grep -c "Success:" logs/upcoming_team_backfill_*.log
```

---

### Step 3: Wait for Completion (2-3 hours)

**Expected Timeline**:
- upcoming_team: ~1-1.5 hours (fastest)
- upcoming_player: ~1.5-2 hours (medium)
- team_defense: ~2-3 hours (slowest, CRITICAL)

**Check Completion**:
```bash
# All processes should exit naturally
# Monitor script will show "ALL PROCESSES COMPLETE"

# Or manually check
ps -p $(cat /tmp/team_defense_backfill.pid) -o pid= || echo "team_defense: COMPLETE"
ps -p $(cat /tmp/upcoming_player_backfill.pid) -o pid= || echo "upcoming_player: COMPLETE"
ps -p $(cat /tmp/upcoming_team_backfill.pid) -o pid= || echo "upcoming_team: COMPLETE"
```
- [ ] team_defense process exited
- [ ] upcoming_player process exited
- [ ] upcoming_team process exited

**Check for Errors**:
```bash
# Check exit codes in logs
tail -50 logs/team_defense_backfill_*.log | grep -E "ERROR|FAIL|Exception"
tail -50 logs/upcoming_player_backfill_*.log | grep -E "ERROR|FAIL|Exception"
tail -50 logs/upcoming_team_backfill_*.log | grep -E "ERROR|FAIL|Exception"
```
- [ ] No critical errors found
- [ ] Or errors documented and acceptable

---

### Step 4: Validate Results (10 min)

**Check BigQuery Coverage**
```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'team_defense_game_summary' as table_name,
  COUNT(DISTINCT game_date) as dates,
  ROUND(COUNT(DISTINCT game_date) * 100.0 / 917, 1) as pct
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
WHERE game_date >= '2021-10-19' AND game_date <= '2026-01-02'
UNION ALL
SELECT
  'upcoming_player_game_context',
  COUNT(DISTINCT game_date),
  ROUND(COUNT(DISTINCT game_date) * 100.0 / 917, 1)
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date >= '2021-10-19' AND game_date <= '2026-01-02'
UNION ALL
SELECT
  'upcoming_team_game_context',
  COUNT(DISTINCT game_date),
  ROUND(COUNT(DISTINCT game_date) * 100.0 / 917, 1)
FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\`
WHERE game_date >= '2021-10-19' AND game_date <= '2026-01-02'
ORDER BY table_name
"
```

**Expected Results**:
- [ ] team_defense: ≥915 dates (99.8%+) ← CRITICAL
- [ ] upcoming_player: ≥550 dates (60%+)
- [ ] upcoming_team: ≥550 dates (60%+)

**Run Automated Pre-flight Check**
```bash
python /home/naji/code/nba-stats-scraper/bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-02 \
  --verbose
```
- [ ] Pre-flight check PASSES
- [ ] All thresholds met
- [ ] No blocking errors

**Detailed Validation**
```bash
# Check record counts
bq query --use_legacy_sql=false "
SELECT
  'team_defense' as table_name,
  COUNT(*) as total_records,
  COUNT(DISTINCT game_date) as dates,
  COUNT(DISTINCT team_id) as teams
FROM nba_analytics.team_defense_game_summary
WHERE game_date >= '2021-10-19' AND game_date <= '2026-01-02'
"
```
- [ ] team_defense: ~15,000+ records
- [ ] upcoming_player: ~80,000+ records
- [ ] upcoming_team: ~10,000+ records

**Check Data Quality**
```bash
# Verify no NULL critical fields
bq query --use_legacy_sql=false "
SELECT COUNT(*) as records_with_nulls
FROM nba_analytics.team_defense_game_summary
WHERE game_date >= '2021-10-19' AND game_date <= '2026-01-02'
  AND (team_id IS NULL OR opponent_id IS NULL OR game_date IS NULL)
"
```
- [ ] records_with_nulls = 0 (or very low)

---

### Step 5: Cleanup & Prepare for Phase 4 (5 min)

**Document Results**
```bash
# Save summary to file
cat > /tmp/phase3_backfill_summary.txt << EOF
Phase 3 Backfill Completion Summary
====================================
Date: $(date)

Coverage Results:
$(bq query --use_legacy_sql=false --format=csv "
SELECT 'team_defense' as table, COUNT(DISTINCT game_date) as dates
FROM nba_analytics.team_defense_game_summary
WHERE game_date >= '2021-10-19' AND game_date <= '2026-01-02'
UNION ALL
SELECT 'upcoming_player', COUNT(DISTINCT game_date)
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= '2021-10-19' AND game_date <= '2026-01-02'
UNION ALL
SELECT 'upcoming_team', COUNT(DISTINCT game_date)
FROM nba_analytics.upcoming_team_game_context
WHERE game_date >= '2021-10-19' AND game_date <= '2026-01-02'
")

Backfill Logs:
$(ls -lh logs/*_backfill_*.log)

Pre-flight Check:
$(python bin/backfill/verify_phase3_for_phase4.py --start-date 2021-10-19 --end-date 2026-01-02 2>&1 | tail -10)
EOF

cat /tmp/phase3_backfill_summary.txt
```
- [ ] Summary saved and reviewed

**Clean Up Temporary Files**
```bash
# Keep PIDs for reference
# Remove temporary monitoring script if desired
# rm /tmp/monitor_phase3.sh
```

**Prepare Phase 4 Launch**
```bash
# Verify Phase 4 scripts exist
ls -lh backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py
ls -lh backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py
ls -lh backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py
ls -lh backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py
```
- [ ] All Phase 4 scripts exist
- [ ] Ready to proceed to Phase 4

---

## SUCCESS CRITERIA

### Phase 3 Backfill Complete When:
- ✅ All 3 backfill processes exited successfully
- ✅ team_defense: ≥915 dates (99.8%+)
- ✅ upcoming_player: ≥550 dates (60%+)
- ✅ upcoming_team: ≥550 dates (60%+)
- ✅ Pre-flight check passes
- ✅ No critical errors in logs

### Ready for Phase 4 When:
- ✅ All Phase 3 success criteria met
- ✅ Phase 4 scripts verified
- ✅ System resources available
- ✅ Time scheduled for 8-10 hour Phase 4 backfill

---

## TROUBLESHOOTING

### Process Failed to Start
**Symptoms**: Process exits immediately, no PID saved
**Check**:
```bash
# Check syntax
python3 backfill_jobs/analytics/[SCRIPT_NAME].py --help

# Check environment
echo $PYTHONPATH
which python3
```
**Fix**: Verify environment setup, check script syntax

---

### Process Stalled/Hung
**Symptoms**: No log output for >15 minutes, process still running
**Check**:
```bash
# Check process state
ps -p [PID] -o pid,stat,wchan:20

# Check for BigQuery errors
tail -100 logs/[LOG_FILE] | grep -i "error\|timeout\|quota"
```
**Fix**:
- BigQuery quota: Wait 1 hour, process auto-resumes
- Network timeout: Kill and restart (checkpoint preserved)
- Memory: Check `free -h`, restart with lower parallelization

---

### Low Coverage After Completion
**Symptoms**: team_defense <99%, upcoming tables <55%
**Check**:
```bash
# Check failed dates
grep "Failed" logs/[LOG_FILE] | head -20

# Check error patterns
grep "ERROR" logs/[LOG_FILE] | sort | uniq -c | sort -rn | head -10
```
**Fix**:
- Retry failed dates: Use `--dates` flag
- Check upstream data availability (Phase 2)
- For upcoming tables: <60% expected for historical dates (betting data limited)

---

### Pre-flight Check Fails
**Symptoms**: verify_phase3_for_phase4.py returns error
**Check**:
```bash
# Run verbose check
python bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 --end-date 2026-01-02 --verbose

# Identify specific gaps
bq query --use_legacy_sql=false "
SELECT game_date
FROM (SELECT DISTINCT game_date FROM nba_analytics.player_game_summary WHERE game_date >= '2021-10-19')
WHERE game_date NOT IN (
  SELECT game_date FROM nba_analytics.team_defense_game_summary
)
ORDER BY game_date
LIMIT 20
"
```
**Fix**: Re-run backfill for missing dates

---

## NEXT STEPS

### After Phase 3 Completion:
1. ✅ Review this checklist (all items checked)
2. ✅ Validate results (coverage ≥thresholds)
3. → Proceed to Phase 4 backfill
4. → See: `/home/naji/code/nba-stats-scraper/docs/08-projects/current/backfill-system-analysis/PHASE4-OPERATIONAL-RUNBOOK.md`

### Phase 4 Quick Start:
```bash
# See PHASE4-OPERATIONAL-RUNBOOK.md for complete execution plan

# Quick reference:
# 1. team_defense_zone_analysis (2-3 hours)
# 2. player_shot_zone_analysis (3-4 hours)
# 3. player_composite_factors (7-8 hours with --parallel)
# 4. ml_feature_store (2-3 hours)
```

---

## REFERENCE

**Related Documents**:
- Complete Analysis: `/home/naji/code/nba-stats-scraper/PHASE4-STRATEGIC-ANALYSIS-2026-01-05.md`
- Dependency Map: `/home/naji/code/nba-stats-scraper/PHASE3-TO-PHASE5-DEPENDENCY-MAP.md`
- Decision Summary: `/home/naji/code/nba-stats-scraper/EXECUTIVE-DECISION-SUMMARY.md`
- Phase 4 Guide: `/home/naji/code/nba-stats-scraper/docs/08-projects/current/backfill-system-analysis/PHASE4-OPERATIONAL-RUNBOOK.md`

**Quick Commands**:
```bash
# Check process status
ps aux | grep backfill | grep -v grep

# Monitor logs
tail -f logs/*_backfill_*.log

# Check coverage
bq query --use_legacy_sql=false "SELECT COUNT(DISTINCT game_date) FROM nba_analytics.[TABLE] WHERE game_date >= '2021-10-19'"

# Validate Phase 3
python bin/backfill/verify_phase3_for_phase4.py --start-date 2021-10-19 --end-date 2026-01-02
```

---

**Document Version**: 1.0
**Created**: January 5, 2026
**Purpose**: Execution checklist for Phase 3 backfill
**Estimated Time**: 2-3 hours total
