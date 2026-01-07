# 🚨 CRITICAL: Phase 4 Backfill Restart Required - January 3, 2026

**Created**: January 3, 2026, 8:00 PM PST
**For**: Backfill chat session
**Priority**: P0 - BLOCKS ML TRAINING
**Action Required**: Restart Phase 4 backfill at 9:45 PM after player re-backfill completes
**Estimated Time**: 5 minutes to read, then wait until 9:45 PM to execute

---

## 🎯 MISSION (2 minutes to read)

**CRITICAL DISCOVERY**: Phase 4 backfill was running and calculating rolling averages from **incomplete Phase 3 data** (only 47% of records had usage_rate populated).

**ACTION TAKEN**: Stopped Phase 4 backfill (PID 3103456) at ~8:00 PM to prevent data quality issues.

**YOUR TASK**:
1. Wait for player re-backfill to complete (~9:45 PM)
2. Validate usage_rate is >95% populated
3. Restart Phase 4 backfill with clean data
4. Monitor completion (~5:45 AM Sunday)
5. Proceed with ML training

---

## ⚡ QUICK CONTEXT (30 seconds)

**What Happened**:
- Phase 4 backfill started at 3:54 PM (PID 3103456)
- It was calculating rolling averages while Phase 3 data still had bugs
- Only 47.7% of player records had usage_rate populated (should be >95%)
- Orchestration monitoring discovered the issue at ~7:45 PM
- Stopped Phase 4 at 8:00 PM to prevent training on dirty data

**Current State**:
- ❌ Phase 4 backfill: STOPPED (PID 3103456 terminated)
- ✅ Bug fix backfill: RUNNING (PID 3142833, ETA 9:15 PM)
- ✅ Team offense Phase 1: RUNNING (PID 3022978, ETA 2:00 AM)
- ✅ Orchestrator: RUNNING (PID 3029954)

**Next Steps**:
- Wait for bug fix to complete
- Wait for player re-backfill to complete
- Restart Phase 4 from scratch with clean data

---

## 📊 DATA QUALITY ISSUE DISCOVERED

### The Problem

```
Season          usage_rate Coverage   Expected   Status
2022-2023       47.9% populated       >95%       ❌ INCOMPLETE
2023-2024       47.7% populated       >95%       ❌ INCOMPLETE
2025-2026        0.0% populated       >95%       ❌ BROKEN
```

**Root Cause**: game_id format mismatch bug (discovered yesterday)
- Team offense data had wrong game_id format
- Player analytics couldn't join to team data
- usage_rate calculation failed
- Bug fix running now to correct team_offense data

### Why Phase 4 Needs Restart

Phase 4 (`player_composite_factors`) calculates these features:
- `avg_usage_rate_last_7_games` - 7-game rolling average
- `projected_usage_rate` - Forward projection
- `usage_spike_score` - Change detection
- `usage_context_json` - Contextual metadata

**Impact of running on 47% data**:
- Rolling averages calculated from only 3-4 games instead of 7
- Inconsistent feature quality across records
- ML model learns from unreliable patterns
- Poor prediction accuracy

**Phase 4 status when stopped**:
```
Progress:     234/917 dates (25.5% complete)
Records:      118,423 player_composite_factors created
Last date:    2022-11-06
Runtime:      2h 30min
```

**All 118,423 records have incorrect rolling averages** ❌ - must be recalculated

---

## 📅 REVISED TIMELINE

### Original Plan (FLAWED)
```
4:28 PM  Bug fix backfill starts
3:54 PM  Phase 4 starts (WRONG - running on dirty data!)
9:15 PM  Bug fix completes
9:45 PM  Player re-backfill completes
2:00 AM  Phase 4 completes (WRONG - averages from 47% data!)
2:30 AM  ML training (WRONG - training on bad features!)
```

### New Plan (CORRECT)
```
✅ 4:28 PM  Bug fix backfill starts (PID 3142833)
✅ 8:00 PM  Phase 4 STOPPED (orchestration discovered issue)
⏰ 9:15 PM  Bug fix completes
⏰ 9:45 PM  Player re-backfill completes (usage_rate fixed)
⏰ 9:45 PM  Validate usage_rate >95%
🚀 9:45 PM  RESTART Phase 4 backfill (clean data)
⏰ 5:45 AM  Phase 4 completes (all 917 dates)
⏰ 6:00 AM  Validate Phase 4 data quality
✅ 6:30 AM  ML training with clean features
```

---

## ✅ EXECUTION PLAN

### Step 1: Wait for Bug Fix Completion (~9:15 PM)

**Monitor bug fix backfill**:
```bash
# Check if still running
ps -p 3142833 -o pid,etime,%cpu,stat,cmd

# Check progress
tail -50 logs/team_offense_bug_fix.log

# Look for completion message
grep -i "complete\|summary\|finished" logs/team_offense_bug_fix.log | tail -5
```

**Expected completion**: ~9:15 PM (may vary ±15 minutes)

### Step 2: Wait for Player Re-Backfill (~9:15-9:45 PM)

**The bug fix backfill should trigger a player_game_summary re-backfill automatically.**

**Monitor for player re-backfill starting**:
```bash
# Check for new player backfill process
ps aux | grep "player_game_summary" | grep -v grep

# Check for player backfill logs
ls -lt logs/ | grep player | head -10

# If you see it starting, monitor progress
tail -f logs/player_game_summary_*.log
```

**Expected duration**: ~30 minutes

**If player re-backfill doesn't auto-start by 9:30 PM**:
```bash
# Manually trigger it
python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 \
  --end-date 2024-05-01 \
  --no-resume
```

### Step 3: Validate usage_rate Population (~9:45 PM)

**CRITICAL VALIDATION** - Don't restart Phase 4 until this passes!

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(*) as total_records,
  COUNTIF(usage_rate IS NOT NULL) as with_usage_rate,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as pct_populated
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2021-10-01'
  AND minutes_played > 0
"
```

**Expected result**:
```
total_records: ~83,000
with_usage_rate: ~79,000+
pct_populated: >95.0%
```

**Current (broken) result**:
```
total_records: 92,822
with_usage_rate: 39,632
pct_populated: 42.7%
```

**If validation fails** (pct_populated <95%):
1. DO NOT restart Phase 4
2. Check player re-backfill logs for errors
3. Check if player re-backfill actually completed
4. Check team_offense data was actually fixed
5. Debug and fix before proceeding

**If validation passes** (pct_populated >95%):
✅ Proceed to Step 4

### Step 4: Restart Phase 4 Backfill (~9:45 PM)

**Delete incomplete Phase 4 data** (optional but recommended):
```bash
# Only delete dates that were processed with dirty data
bq query --use_legacy_sql=false --format=pretty "
DELETE FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date >= '2021-10-19' AND game_date <= '2022-11-07'
"
```

**Restart Phase 4 backfill**:
```bash
cd /home/naji/code/nba-stats-scraper

nohup python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-02 \
  --skip-preflight \
  > logs/phase4_pcf_backfill_20260103_restart.log 2>&1 &

# Save the PID
echo $!
```

**Important**:
- Use `--skip-preflight` to bypass Phase 3 validation (we just validated manually)
- Save the PID for monitoring
- Log to new file to track restart separately

**Expected**:
- Process starts immediately
- Begins with 2021-10-19 (or first date after deletion)
- Processes ~30 seconds per date
- Total time: ~8 hours for 917 dates

### Step 5: Monitor Phase 4 Progress

**Initial check** (5 minutes after start):
```bash
# Check process is running
NEW_PID=<PID from echo $!>
ps -p $NEW_PID -o pid,etime,%cpu,%mem,stat

# Check log shows progress
tail -50 logs/phase4_pcf_backfill_20260103_restart.log

# Should see lines like:
# "Processing game date 1/917: 2021-10-19"
# "✓ Success: 134 players"
```

**Periodic checks** (every 2-3 hours):
```bash
# Check progress
tail -50 logs/phase4_pcf_backfill_20260103_restart.log | grep "Processing game date"

# Count successful dates
grep -c "✓ Success:" logs/phase4_pcf_backfill_20260103_restart.log

# Calculate ETA
COMPLETED=$(grep -c "✓ Success:" logs/phase4_pcf_backfill_20260103_restart.log)
TOTAL=917
REMAINING=$((TOTAL - COMPLETED))
echo "Progress: $COMPLETED/$TOTAL ($((COMPLETED * 100 / TOTAL))%)"
echo "Remaining: $REMAINING dates"
```

**Check for errors**:
```bash
grep -i "error\|failed\|exception" logs/phase4_pcf_backfill_20260103_restart.log | tail -20
```

### Step 6: Validate Phase 4 Completion (~5:45 AM Sunday)

**Check backfill completed successfully**:
```bash
# Check process finished
ps -p $NEW_PID  # Should show "No such process"

# Check log for completion
tail -100 logs/phase4_pcf_backfill_20260103_restart.log | grep -i "complete\|summary"

# Count successful vs failed
grep -c "✓ Success:" logs/phase4_pcf_backfill_20260103_restart.log
grep -c "✗ Failed:" logs/phase4_pcf_backfill_20260103_restart.log
```

**Validate data in BigQuery**:
```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(DISTINCT game_date) as unique_dates,
  COUNT(*) as total_records,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date >= '2021-10-19'
"
```

**Expected results**:
```
unique_dates: 903-905 (917 minus ~14 bootstrap skips)
total_records: 165,000-175,000
earliest: 2021-10-19
latest: 2026-01-02
```

**Validate rolling averages have data**:
```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(*) as total,
  COUNTIF(avg_usage_rate_last_7_games IS NOT NULL) as with_avg_usage,
  ROUND(100.0 * COUNTIF(avg_usage_rate_last_7_games IS NOT NULL) / COUNT(*), 1) as pct
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date >= '2021-10-19'
  AND game_date > '2021-11-01'  -- Skip early bootstrap period
"
```

**Expected**: >90% (some nulls expected for players with <7 games history)

### Step 7: Proceed with ML Training (~6:30 AM Sunday)

**Final validation before training**:
```bash
# Check Phase 3 usage_rate still good
bq query --use_legacy_sql=false "
SELECT ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2021-10-01' AND minutes_played > 0"

# Expected: >95%

# Check Phase 4 rolling averages populated
bq query --use_legacy_sql=false "
SELECT ROUND(100.0 * COUNTIF(avg_usage_rate_last_7_games IS NOT NULL) / COUNT(*), 1) as pct
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date >= '2021-11-01'"

# Expected: >90%
```

**If both validations pass**:
✅ Proceed with ML training - data is clean and ready!

**Training command**:
```bash
cd /home/naji/code/nba-stats-scraper

PYTHONPATH=. python3 ml/train_real_xgboost.py
```

---

## 🚨 TROUBLESHOOTING

### Player Re-Backfill Doesn't Start

**Symptoms**: Bug fix completes but player backfill doesn't auto-start by 9:30 PM

**Solution**: Manually trigger it
```bash
python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 \
  --end-date 2024-05-01 \
  --no-resume
```

### usage_rate Validation Fails

**Symptoms**: Query shows <95% populated

**Debug steps**:
```bash
# Check by season
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN game_date >= '2024-10-01' THEN '2024-25'
    WHEN game_date >= '2023-10-01' THEN '2023-24'
    WHEN game_date >= '2022-10-01' THEN '2022-23'
    ELSE 'Older'
  END as season,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2021-10-01' AND minutes_played > 0
GROUP BY season
ORDER BY season DESC"

# Check specific date range
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records,
  COUNTIF(usage_rate IS NOT NULL) as populated
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2024-04-01' AND '2024-05-01'
GROUP BY game_date
ORDER BY game_date"
```

**Possible causes**:
- Player re-backfill didn't complete
- Bug fix didn't actually fix team_offense data
- Different bug causing usage_rate failures

**Action**: Don't proceed until >95%. Debug and fix first.

### Phase 4 Backfill Fails on Specific Dates

**Symptoms**: Seeing "✗ Failed:" messages in log

**Check error details**:
```bash
grep -A 5 "✗ Failed:" logs/phase4_pcf_backfill_20260103_restart.log
```

**Common issues**:
- No games on that date (expected - will skip)
- Missing Phase 3 dependencies (check team_defense_zone_analysis, player_shot_zone_analysis exist)
- BigQuery quota issues (wait and retry)

**Solution**: Most failures are OK if they're "No games scheduled" or bootstrap skips. Real errors need investigation.

### Phase 4 Takes Longer Than Expected

**Expected**: ~30 sec/date average = ~8 hours total

**If slower** (>1 min/date):
- Check BigQuery quota usage
- Check system CPU/memory (other processes competing?)
- Check network latency to BigQuery

**If much slower**:
- Consider stopping and debugging performance issue
- May need to adjust worker concurrency or batch sizes

---

## 📋 CURRENT BACKFILL STATUS

### Active Processes (as of 8:00 PM)

| PID | Job | Status | Progress | ETA |
|-----|-----|--------|----------|-----|
| 3142833 | Team Offense Bug Fix ⭐ | ✅ Running | ~60-70% | 9:15 PM |
| 3022978 | Team Offense Phase 1 | ✅ Running | ~850/1537 dates | 2:00 AM |
| 3029954 | Orchestrator (monitoring) | ✅ Running | - | - |
| ~~3103456~~ | ~~Player Composite Factors~~ | ❌ **STOPPED** | Was 25% | Restart 9:45 PM |

⭐ = Critical path for tonight's work

### Stopped Process Details

**PID 3103456** - Player Composite Factors (STOPPED at 8:00 PM):
- Start time: 3:54 PM (15:54)
- Stop time: 8:00 PM (20:00)
- Runtime: ~2h 30min before stop
- Progress: 234/917 dates (25.5%)
- Last date: 2022-11-06
- Records created: 118,423 (all with incorrect averages)

**Why stopped**: Calculating rolling averages from incomplete data (47% usage_rate instead of >95%)

**Action**: Will restart at 9:45 PM after player re-backfill validates usage_rate >95%

---

## 📚 REFERENCE DOCUMENTS

**Full orchestration analysis**:
- `/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-03-ORCHESTRATION-STATUS-AND-DATA-DEPENDENCY-ISSUE.md`

**Original backfill plan**:
- `/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-03-SESSION-COMPLETE-SUMMARY.md`

**Bug fix details**:
- `/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-04-GAME-ID-BUG-FIX-AND-BACKFILL.md`

**Phase 4 backfill code**:
- `/home/naji/code/nba-stats-scraper/backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py`

---

## ✅ SUCCESS CRITERIA

You're done when ALL of these are true:

1. ✅ usage_rate >95% populated in player_game_summary
2. ✅ Phase 4 backfill completed all 917 dates
3. ✅ Phase 4 has 903-905 unique dates (accounting for bootstrap skips)
4. ✅ avg_usage_rate_last_7_games is >90% populated in player_composite_factors
5. ✅ No errors in Phase 4 backfill log (except expected skips)
6. ✅ ML training command runs without data quality errors

---

## 🎯 KEY TAKEAWAYS

1. **Phase 4 was stopped** because it was calculating from incomplete Phase 3 data
2. **Wait until 9:45 PM** for player re-backfill to fix usage_rate
3. **Validate usage_rate >95%** before restarting Phase 4
4. **Phase 4 will take ~8 hours** to complete full backfill
5. **ML training Sunday morning** after Phase 4 validation passes

---

**Document Version**: 1.0
**Created**: January 3, 2026, 8:00 PM PST
**For**: Backfill chat session resuming work
**Next Action**: Wait until 9:45 PM, then execute Step 3 validation

**CRITICAL**: Do not skip the validation steps. Training on inconsistent features will produce poor model performance.
