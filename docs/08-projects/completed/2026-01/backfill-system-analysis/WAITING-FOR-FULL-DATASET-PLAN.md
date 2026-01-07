# Waiting for Full Dataset - Monitoring Plan
**Date**: January 4, 2026
**Decision**: Wait for orchestrator to complete for best ML model performance
**ETA**: ~8:00 PM PST (1 hour remaining)

---

## ORCHESTRATOR STATUS

**Current Progress** (as of 6:52 PM):
- **Completed**: 1,275/1,537 days (83.0%)
- **Remaining**: 262 days
- **Success Rate**: 99.0%
- **Records**: 12,022 team-game records
- **Elapsed**: 5h 0m 47s

**Performance**:
- Processing Rate: 4.25 days/minute
- Time per Day: 0.24 minutes (~14 seconds/day)
- **Very consistent** - no signs of slowdown

**ETA Estimates**:
- **Best Case**: 7:45 PM PST (if rate increases slightly)
- **Most Likely**: **8:00 PM PST** (current rate maintained)
- **Worst Case**: 8:30 PM PST (if rate decreases)

**Log Location**: `/home/naji/code/nba-stats-scraper/logs/orchestrator_20260103_134700.log`

---

## MONITORING COMMANDS

### Check Progress (Every 10-15 Minutes)

```bash
# Quick progress check
tail -5 /home/naji/code/nba-stats-scraper/logs/orchestrator_20260103_134700.log

# Detailed status
tail -20 /home/naji/code/nba-stats-scraper/logs/orchestrator_20260103_134700.log | grep Progress
```

### Live Monitoring (Optional)

```bash
# Watch log in real-time
tail -f /home/naji/code/nba-stats-scraper/logs/orchestrator_20260103_134700.log

# Monitor with auto-refresh every 30 seconds
watch -n 30 'tail -5 /home/naji/code/nba-stats-scraper/logs/orchestrator_20260103_134700.log'
```

### Calculate Remaining Time

```bash
# Extract latest progress and calculate ETA
python3 << 'CALC'
import re
from datetime import datetime, timedelta

log_file = "/home/naji/code/nba-stats-scraper/logs/orchestrator_20260103_134700.log"
with open(log_file) as f:
    lines = f.readlines()
    for line in reversed(lines):
        if "Progress:" in line:
            match = re.search(r'Progress: (\d+)/(\d+) days', line)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                remaining = total - current
                pct = 100 * current / total

                # Estimate based on 4.25 days/min rate
                eta_minutes = remaining / 4.25
                eta_hours = eta_minutes / 60

                print(f"Progress: {current}/{total} ({pct:.1f}%)")
                print(f"Remaining: {remaining} days")
                print(f"ETA: {eta_minutes:.0f} minutes (~{eta_hours:.1f} hours)")
                break
CALC
```

---

## WHAT HAPPENS WHEN ORCHESTRATOR COMPLETES

### Phase 1: team_offense_game_summary Backfill ✅

**When Complete**:
- All 1,537 days processed
- ~14,000+ team-game records (estimate)
- 99%+ success rate
- Covers full 2021-2024 range

**Validation**:
Orchestrator will automatically run validation query to check:
- Expected vs actual record counts
- Date coverage
- Data quality

**If Validation Passes** → Auto-triggers Phase 2
**If Validation Fails** → Logs error, stops

---

### Phase 2: player_game_summary Re-backfill (Auto-Triggered)

**Purpose**: Recalculate usage_rate with complete team_offense data

**Process**:
- Start Date: 2021-10-19
- End Date: 2026-01-03
- Mode: Parallel (15 workers)
- Expected Duration: **30-40 minutes**
- Expected Records: ~80,000+

**Progress Indicators**:
```
Look for in orchestrator log:
[TIME] ========================================
[TIME] PHASE 2: player_game_summary Analytics
[TIME] ========================================
[TIME] Starting parallel backfill...
[TIME] Worker 1/15 processing dates...
[TIME] Worker 2/15 processing dates...
...
```

**When Phase 2 Completes**:
- **Validation runs automatically**
- Checks usage_rate coverage (should reach 90%+)
- If passes → Orchestrator marks complete

---

## TOTAL TIMELINE

**Current Time**: ~6:52 PM PST

**Phase 1 Remaining**: ~1 hour (ETA 8:00 PM)
**Phase 2 Duration**: ~30-40 minutes
**Total Completion**: **~8:30-8:40 PM PST**

**Then**:
- Validation: 15 minutes
- ML Training Setup: 5 minutes
- ML Training: 2-3 hours
- **Model v5 ready**: **~11:00-11:30 PM PST**

---

## WHEN TO START ML TRAINING

### Trigger Condition: Orchestrator Shows "COMPLETE"

**Look for in log**:
```
[TIME] ========================================
[TIME] ALL PHASES COMPLETE
[TIME] ========================================
[TIME] Phase 1: SUCCESS (team_offense_game_summary)
[TIME] Phase 2: SUCCESS (player_game_summary)
[TIME] Validation: PASSED
[TIME] Total Duration: X hours
[TIME] Orchestrator complete.
```

**OR check process completion**:
```bash
# If this returns nothing, orchestrator finished
ps aux | grep -E "orchestrator|backfill" | grep -v grep
```

---

### Pre-Training Validation

**Step 1: Verify team_offense Coverage**

```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT game_id) as total_games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest,
  COUNT(*) as team_records
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date BETWEEN '2021-10-19' AND '2024-06-30'
"
```

**Expected**:
- total_games: ~1,900+ (should match player_game_summary)
- team_records: ~14,000+ (2 teams × ~1,900 games)

---

**Step 2: Verify usage_rate Coverage**

```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_players,
  COUNTIF(usage_rate IS NOT NULL) as with_usage,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2021-10-19' AND '2024-06-30'
  AND minutes_played IS NOT NULL
"
```

**Expected**:
- total_players: ~84,000+
- with_usage: ~75,000+ (90%+)
- usage_pct: **90%+** (was 47.7%, should double)

---

**Step 3: Run Validation Script**

```bash
cd /home/naji/code/nba-stats-scraper
./scripts/validation/validate_player_summary.sh 2021-10-01 2024-05-01
```

**Expected**:
```
✅ VALIDATION PASSED
Record Count: 83,644+ (PASS)
minutes_played: 99.8% (PASS)
usage_rate: 90%+ (PASS) ← Should now PASS
Shot Zones: 88.1% (PASS)
Quality Score: 99.9+ (PASS)
```

**Exit Code**: 0 (success)

**If validation PASSES** → Proceed to training
**If validation FAILS** → Investigate issue before training

---

### Start ML Training

**Once validation passes**, execute:

```bash
cd /home/naji/code/nba-stats-scraper

# Set environment
export PYTHONPATH=.
export GCP_PROJECT_ID=nba-props-platform

# Verify auth
gcloud auth application-default print-access-token > /dev/null

# Create log file with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/tmp/training_full_dataset_${TIMESTAMP}.log"

# Start training
echo "Training started at $(date)" | tee $LOG_FILE
python ml/train_real_xgboost.py 2>&1 | tee -a $LOG_FILE
```

**Monitor in separate terminal**:
```bash
tail -f /tmp/training_full_dataset_*.log | grep -E "(Extracting|Iteration|MAE)"
```

---

## EXPECTED TRAINING RESULTS (Full Dataset)

### Dataset Size

**Before** (current state):
- ML-ready records: 36,650
- usage_rate coverage: 47.7%

**After** (post-orchestrator):
- ML-ready records: **~75,000-80,000** (2x increase)
- usage_rate coverage: **90%+**

### Model Performance Expectations

**With Full Dataset** (80,000 records):

**Expected**:
- **Test MAE**: 3.8-4.0 (15-20% better than 4.27 baseline)
- **Confidence**: HIGH (90%)

**Breakdown**:
- Best Case: 3.7-3.9 MAE (20-25% improvement)
- **Most Likely**: **3.8-4.0 MAE** (15-20% improvement)
- Worst Case: 4.0-4.15 MAE (10-15% improvement)

**Why Better Performance?**:
1. ✅ 2x more training data (80k vs 36k)
2. ✅ usage_rate coverage doubles (90%+ vs 47%)
3. ✅ More diverse scenarios
4. ✅ Better feature representation

**Comparison to Partial Dataset**:
- Partial (36k): Expected MAE 4.0-4.2
- Full (80k): Expected MAE 3.8-4.0
- **Improvement**: ~0.1-0.2 MAE reduction (worth the wait!)

---

## RISK ASSESSMENT

### Risks of Waiting

**Risk 1: Orchestrator Failure** (LOW)
- Current success rate: 99.0%
- No signs of issues in logs
- If fails: Can resume from checkpoint
- **Mitigation**: Monitor logs, have resume command ready

**Risk 2: Phase 2 Failure** (MEDIUM)
- player_game_summary backfill has run successfully many times
- Parallel execution might have resource issues
- If fails: Can run manually
- **Mitigation**: Monitor closely, have manual backup plan

**Risk 3: Time Overrun** (LOW)
- Current rate very consistent
- 83% complete, only 1 hour remaining
- Worst case: 8:30 PM vs 8:00 PM (30 min delay)
- **Mitigation**: Already factored into timeline

**Overall Risk**: **LOW** - Worth waiting for 2x dataset size

---

## CONTINGENCY PLANS

### If Orchestrator Fails During Phase 1

**Identify Issue**:
```bash
# Check for errors
grep -i "error\|fail\|exception" logs/orchestrator_20260103_134700.log | tail -20

# Check process status
ps aux | grep orchestrator
```

**Resume from Checkpoint**:
```bash
# Orchestrator should auto-resume, but if needed:
# Find last successful date
LAST_DATE=$(grep "Processing date:" logs/orchestrator_20260103_134700.log | tail -1 | grep -oP '\d{4}-\d{2}-\d{2}')

# Resume backfill manually
.venv/bin/python backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py \
  --start-date "$LAST_DATE" --end-date 2024-06-30
```

---

### If Phase 2 Fails

**Manual Execution**:
```bash
# Run player_game_summary backfill manually
.venv/bin/python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  --parallel \
  --workers 15 \
  --no-resume
```

**Monitor Progress**:
```bash
tail -f logs/backfill_parallel_*.log
```

---

### If Validation Still Fails After Full Backfill

**Investigate**:
```bash
# Check usage_rate coverage by date range
bq query --use_legacy_sql=false "
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as total,
  COUNTIF(usage_rate IS NOT NULL) as with_usage,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as pct
FROM nba_analytics.player_game_summary
WHERE minutes_played IS NOT NULL
GROUP BY year
ORDER BY year
"
```

**Possible Issues**:
1. team_offense still incomplete for some dates
2. Code regression
3. Data quality issue

**Resolution**:
- Review investigation findings
- Consult ML Training Playbook troubleshooting section
- Consider training on partial data anyway if coverage > 75%

---

## ALTERNATIVE: CHANGE YOUR MIND AND TRAIN NOW

**If you decide NOT to wait**, you can still train on current dataset:

**Current State**:
- Records: 36,650 (73% of ideal)
- Expected MAE: 4.0-4.2
- Time to results: 2-3 hours (faster than waiting)

**Trade-off**:
- Slightly worse expected performance (4.0-4.2 vs 3.8-4.0)
- But results ~4 hours sooner
- Can always retrain v6 later with full data

**Command** (if changing mind):
```bash
cd /home/naji/code/nba-stats-scraper
export PYTHONPATH=. && export GCP_PROJECT_ID=nba-props-platform
python ml/train_real_xgboost.py 2>&1 | tee /tmp/training_$(date +%Y%m%d_%H%M%S).log
```

---

## RECOMMENDED ACTIONS WHILE WAITING

### 1. Set Up Monitoring (5 minutes)

```bash
# Create alert script
cat > /tmp/check_orchestrator.sh << 'EOF'
#!/bin/bash
while true; do
    LAST_LINE=$(tail -1 /home/naji/code/nba-stats-scraper/logs/orchestrator_20260103_134700.log)

    if echo "$LAST_LINE" | grep -q "ALL PHASES COMPLETE"; then
        echo "✅ ORCHESTRATOR COMPLETE at $(date)"
        echo "Ready for ML training!"
        # Could add notification here (email, slack, etc.)
        break
    elif echo "$LAST_LINE" | grep -qi "error\|fail"; then
        echo "❌ ERROR DETECTED at $(date)"
        echo "Check logs: tail -50 logs/orchestrator_20260103_134700.log"
        break
    fi

    sleep 300  # Check every 5 minutes
done
EOF

chmod +x /tmp/check_orchestrator.sh
/tmp/check_orchestrator.sh &
echo "Monitoring running in background (PID: $!)"
```

---

### 2. Prepare Training Environment (5 minutes)

```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Test GCP authentication
gcloud auth application-default print-access-token > /dev/null && \
  echo "✅ GCP auth valid" || \
  echo "⚠️ Need to re-authenticate: gcloud auth application-default login"

# Verify training script
ls -lh ml/train_real_xgboost.py && echo "✅ Training script found"

# Check disk space
df -h . | grep -v Filesystem && echo "✅ Disk space OK"

# Pre-create log directory
mkdir -p /tmp/ml_training_logs/

echo "✅ Environment ready for training"
```

---

### 3. Review Documentation (Optional)

While waiting, familiarize yourself with:

**Training Guide**:
```bash
less /home/naji/code/nba-stats-scraper/docs/playbooks/ML-TRAINING-PLAYBOOK.md
```

**Recent Changes**:
```bash
less /home/naji/code/nba-stats-scraper/docs/lessons-learned/DATA-QUALITY-JOURNEY-JAN-2026.md
```

**Audit Report**:
```bash
less /home/naji/code/nba-stats-scraper/COMPREHENSIVE-PIPELINE-AUDIT-2026-01-04.md
```

---

## TIMELINE SUMMARY

**Current Time**: ~6:52 PM PST

| Time | Event | Status |
|------|-------|--------|
| 6:52 PM | Current orchestrator status (83%) | ⏳ IN PROGRESS |
| ~8:00 PM | Phase 1 complete (team_offense) | ⏳ PENDING |
| ~8:00-8:40 PM | Phase 2 runs (player_game_summary) | ⏳ PENDING |
| ~8:45 PM | Validation completes | ⏳ PENDING |
| ~8:50 PM | ML training starts | ⏳ PENDING |
| ~10:50-11:50 PM | Training completes | ⏳ PENDING |
| ~11:00 PM | Model v5 ready | ⏳ PENDING |

**Total Wait Time**: ~4 hours from now
**ML Training Ready**: ~8:50 PM PST
**Results Available**: ~11:00 PM PST (late night)

---

## SUCCESS CRITERIA

### For Orchestrator

- ✅ Phase 1 completes successfully (1537/1537 days)
- ✅ Phase 2 completes successfully
- ✅ Validation passes
- ✅ No critical errors in logs
- ✅ team_offense records: 14,000+
- ✅ player_game_summary records: 80,000+

### For Data Quality

- ✅ usage_rate coverage: 90%+ (up from 47.7%)
- ✅ ML-ready records: 75,000+ (up from 36,650)
- ✅ Validation script passes all thresholds
- ✅ No regressions in other features

### For ML Training

- ✅ Training completes without errors
- ✅ Test MAE < 4.0 (beats 4.27 baseline by 15%+)
- ✅ Train/Val/Test within 10% (no overfitting)
- ✅ usage_rate in top 10 feature importance

---

## QUICK REFERENCE

**Check Progress**:
```bash
tail -5 logs/orchestrator_20260103_134700.log
```

**Check Completion**:
```bash
grep "ALL PHASES COMPLETE" logs/orchestrator_20260103_134700.log
```

**Check if Still Running**:
```bash
ps aux | grep orchestrator | grep -v grep
```

**Start Training** (when ready):
```bash
export PYTHONPATH=. && export GCP_PROJECT_ID=nba-props-platform
python ml/train_real_xgboost.py 2>&1 | tee /tmp/training_full_$(date +%Y%m%d_%H%M%S).log
```

---

**Waiting Strategy**: PATIENCE PAYS OFF

**Expected Outcome**: Model v5 with MAE 3.8-4.0 (15-20% better than baseline)

**Worth the Wait**: ✅ YES (0.1-0.2 MAE improvement over training now)

---

**End of Monitoring Plan**

**Next Update**: Check back at 8:00 PM PST for orchestrator completion
