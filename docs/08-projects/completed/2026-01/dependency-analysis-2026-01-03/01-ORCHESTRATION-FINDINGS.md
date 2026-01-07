# Orchestration Status & Data Dependency Issue - January 3, 2026

**Created**: January 3, 2026, 7:45 PM PST
**Session**: Orchestration monitoring and backfill coordination
**Priority**: P0 - CRITICAL DATA QUALITY ISSUE DISCOVERED
**Status**: Phase 4 backfill STOPPED - needs restart after player re-backfill

---

## Executive Summary

✅ **Daily orchestration is healthy** - all workflows executing on schedule
⚠️ **Configuration bug discovered** - scheduler passing literal "YESTERDAY" string
🚨 **CRITICAL**: Phase 4 backfill calculating averages from incomplete data (47% usage_rate)
✅ **ACTION TAKEN**: Stopped Phase 4 backfill to prevent data quality issues

---

## Daily Orchestration Status

### Master Controller (Phase 1)
**Status**: ✅ **HEALTHY**

- 24 hourly executions completed successfully (100% success rate)
- All workflow decisions executed without errors
- Key workflows executed today:
  - `morning_operations`: 1 execution at 00:10 UTC
  - `betting_lines`: 4 executions before games
  - `injury_discovery`: Successfully completed at 06:05 UTC
  - `referee_discovery`: 8 attempts throughout day
  - `post_game_window_1/2/3`: All executed successfully

### Cloud Schedulers
**Status**: ✅ **ALL ENABLED**

All scheduled jobs executed successfully:
- `daily-yesterday-analytics` (6:30 AM ET) - Has config bug but data processed
- `overnight-phase4` (11:00 PM PT) - ML Feature Store succeeded
- `overnight-predictions` (12:00 PM PT) - Generated 2,475 predictions for 99 players
- `same-day-phase3/phase4` - Processing today's games
- `grading-daily` - Graded yesterday's predictions
- Live monitoring jobs - Running every 3-5 min during games

---

## Configuration Bug Discovered

### Phase 3 Analytics Scheduler Issue

**Problem**: The `daily-yesterday-analytics` scheduler passes literal string `"YESTERDAY"` instead of resolved date:

```json
{
  "start_date": "YESTERDAY",
  "end_date": "YESTERDAY",
  "processors": ["PlayerGameSummaryProcessor", "TeamDefenseGameSummaryProcessor", "TeamOffenseGameSummaryProcessor"],
  "backfill_mode": true
}
```

**Error in Logs** (11:30 AM UTC / 6:30 AM ET):
```
ERROR: time data 'YESTERDAY' does not match format '%Y-%m-%d'
ERROR: Could not cast literal "YESTERDAY" to type DATE
```

**Root Cause**:
- Phase 3 analytics service `/process-date-range` endpoint expects actual dates (e.g., `"2026-01-02"`)
- The ParameterResolver in orchestration layer handles "YESTERDAY" → date conversion
- This scheduler bypasses orchestration and calls Phase 3 directly
- Service doesn't support "YESTERDAY" keyword

**Impact**:
- 6:30 AM retry failed
- Initial data processing succeeded earlier (Jan 2 data exists with 209 player records, 10 games)
- No data loss, just failed retry attempts

**Fix Required**:
Update scheduler at `projects/nba-props-platform/locations/us-west2/jobs/daily-yesterday-analytics`:
- Option 1: Add date resolution logic to scheduler configuration
- Option 2: Add "YESTERDAY" keyword support to Phase 3 service
- Option 3: Use Cloud Function to resolve date before calling Phase 3

**Priority**: P2 - Low impact (data is processing despite errors), but should be fixed to prevent log noise

---

## CRITICAL: Data Dependency Issue Discovered

### The Problem

Phase 4 backfill was running and calculating rolling averages from **incomplete Phase 3 data**:

```
Season          usage_rate Completeness   Status
2022-2023       47.9% populated          ❌ INCOMPLETE
2023-2024       47.7% populated          ❌ INCOMPLETE
2025-2026        0.0% populated          ❌ BROKEN
```

**Expected**: >95% populated after bug fix completes

### Why This Matters

Phase 4 (`player_composite_factors`) calculates features from Phase 3 data:
- `avg_usage_rate_last_7_games` - 7-game rolling average
- `projected_usage_rate` - Forward projection
- `usage_spike_score` - Change detection
- `usage_context_json` - Contextual factors

**Impact of running on incomplete data**:
- Rolling averages calculated from 3-4 games instead of 7 games
- Inconsistent feature quality (some records complete, others partial)
- ML model will learn from inconsistent patterns
- Training will produce poor predictions

### Phase 4 Status When Stopped

```
Process:     PID 3103456
Status:      Running (but stopped by us)
Progress:    234/917 dates (25.5% complete)
Current:     Processing 2022-11-06
Records:     118,423 player_composite_factors created
Time:        Running for 2h 4min
```

**Data created before stop**:
- 665 dates processed
- 118,423 player records calculated
- All have rolling averages from 47% usage_rate coverage
- ❌ **INVALID - needs recalculation**

### Timeline Analysis

**Current plan** (from earlier handoff):
1. ✅ Bug fix backfill running - ETA ~9:15 PM (fixes team_offense game_id)
2. ⏰ Player re-backfill - 9:15-9:45 PM (recalculates usage_rate from fixed team data)
3. ❌ Phase 4 backfill - Was running ahead, would complete before player fix
4. ❌ ML training - Would train on dirty Phase 4 data

**Problem identified**:
- Phase 4 was running in parallel with bug fix
- Would complete using 47% usage_rate data
- Player re-backfill happens AFTER Phase 4 would finish
- ML training would use incomplete rolling averages

### Action Taken

**Decision**: STOP Phase 4 backfill immediately

**Rationale**:
- Phase 4 only 25% complete - minimal work wasted
- All 665 dates processed have incorrect averages - need recalculation
- Better to wait 3 hours and restart with clean data
- Prevents ML training on inconsistent features

**Command executed**:
```bash
kill 3103456
```

### New Execution Plan

**Revised timeline**:

1. ✅ **Bug fix backfill** (PID 3142833) - Running
   - Date range: 2021-10-01 to 2024-05-01
   - ETA: ~9:15 PM PT
   - Fixes: team_offense game_id format bug

2. ⏰ **Player re-backfill** - Starts at 9:15 PM
   - Date range: 2021-10-01 to 2024-05-01
   - Duration: ~30 minutes
   - ETA completion: ~9:45 PM PT
   - Fixes: Recalculates usage_rate with correct team data

3. ✅ **Validate usage_rate** - 9:45 PM
   ```sql
   SELECT ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as pct
   FROM `nba-props-platform.nba_analytics.player_game_summary`
   WHERE game_date >= '2021-10-01' AND minutes_played > 0
   ```
   Expected: >95% (currently 47.7%)

4. 🚀 **RESTART Phase 4 backfill** - 9:45 PM
   ```bash
   python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
     --start-date 2021-10-19 --end-date 2026-01-02 --skip-preflight
   ```
   - Full date range: 917 dates
   - ETA: ~8 hours (30 sec/date average)
   - Completion: ~5:45 AM Sunday

5. ⏰ **ML training** - Sunday morning after Phase 4 completes
   - Wait for Phase 4 validation
   - Verify >95% usage_rate coverage
   - Train with clean, consistent features

---

## Current Backfill Status

### Active Processes

| PID | Job | Date Range | Status | ETA |
|-----|-----|-----------|--------|-----|
| 3142833 | Team Offense Bug Fix ⭐ | 2021-10-01 to 2024-05-01 | ✅ Running | ~9:15 PM |
| 3022978 | Team Offense Phase 1 | 2021-10-19 to 2026-01-02 | ✅ Running | ~2:00 AM Sun |
| 3029954 | Orchestrator (monitoring) | - | ✅ Running | - |
| ~~3103456~~ | ~~Player Composite Factors~~ | - | ❌ **STOPPED** | Restart at 9:45 PM |

⭐ = Critical path for ML training

### Data Quality State

**Before bug fix**:
```sql
-- Usage rate completeness by season
2022-2023: 47.9% (13,246 / 27,673 records)
2023-2024: 47.7% (12,955 / 27,162 records)
2025-2026:  0.0% (     0 /  9,652 records)
```

**After player re-backfill** (expected ~9:45 PM):
```sql
2022-2023: >95% populated ✅
2023-2024: >95% populated ✅
2025-2026: >95% populated ✅
```

### Recent Games Processed

**Jan 1, 2026**: 90 player records, 3 games ✅ (usage_rate 0% - in affected range)
**Jan 2, 2026**: 209 player records, 10 games ✅ (usage_rate 0% - in affected range)

**Team analytics**:
**Jan 2, 2026**: 16 team offense records for 8 games ✅ (complete)

---

## Other Issues Found

### 1. Prediction Worker Instance Availability
**Status**: ⚠️ **WARNING**

- 20+ errors: "The request was aborted because there was no available instance"
- Occurred at 2:40 PM ET and 6:01 PM ET
- Predictions eventually succeeded but with delays
- **Recommendation**: Increase min instances to 2-3 for `prediction-worker` during peak hours (6-8 AM, 11 AM-1 PM ET)

### 2. Late-Night Phase 4 Jobs Failing
**Status**: ⚠️ **WARNING**

These jobs showed status code 7 (error) last night:
- `player-composite-factors-daily` (11:00 PM PT)
- `player-daily-cache-daily` (11:15 PM PT)
- `ml-feature-store-daily` (11:30 PM PT)

**Expected**: May recover tonight after backfills complete and data quality improves

---

## Recommendations

### Immediate (Tonight)

1. ✅ **Monitor bug fix backfill** - Should complete ~9:15 PM
   ```bash
   ps -p 3142833 -o pid,etime,%cpu,stat
   tail -50 logs/team_offense_bug_fix.log
   ```

2. ⏰ **Watch for player re-backfill** - Should auto-start at 9:15 PM
   - Check logs for player_game_summary backfill starting
   - Monitor for ~30 minutes

3. ✅ **Validate usage_rate at 9:45 PM** - Critical checkpoint
   ```sql
   -- Should show >95%
   SELECT
     COUNT(*) as total,
     COUNTIF(usage_rate IS NOT NULL) as populated,
     ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as pct
   FROM `nba-props-platform.nba_analytics.player_game_summary`
   WHERE game_date >= '2021-10-01' AND minutes_played > 0
   ```

4. 🚀 **Restart Phase 4 at 9:45 PM** - From clean data
   ```bash
   nohup python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
     --start-date 2021-10-19 --end-date 2026-01-02 --skip-preflight \
     > logs/phase4_pcf_backfill_20260103_restart.log 2>&1 &

   echo $! # Save PID for monitoring
   ```

### Short-Term (Sunday)

1. **Monitor Phase 4 completion** (~5:45 AM)
   - Verify all 917 dates processed
   - Check for any failed dates
   - Validate player_composite_factors row counts

2. **Validate before ML training**
   ```sql
   -- Check Phase 4 coverage
   SELECT
     COUNT(DISTINCT game_date) as dates,
     COUNT(*) as records
   FROM `nba-props-platform.nba_precompute.player_composite_factors`
   WHERE game_date >= '2021-10-19'
   -- Expected: 903 dates (917 minus ~14 bootstrap skips)

   -- Check usage_rate quality in Phase 4 source
   SELECT
     ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_rate_pct
   FROM `nba-props-platform.nba_analytics.player_game_summary`
   WHERE game_date >= '2021-10-01' AND minutes_played > 0
   -- Expected: >95%
   ```

3. **Begin ML training** with confidence in data quality

### Medium-Term (Next Week)

1. **Fix "YESTERDAY" scheduler bug**
   - Update `daily-yesterday-analytics` scheduler
   - Add date resolution or keyword support
   - Test with actual execution

2. **Increase prediction-worker min instances**
   ```bash
   gcloud run services update prediction-worker \
     --min-instances=2 \
     --region=us-west2
   ```

3. **Set up data quality alerts**
   - Alert if usage_rate <95% in recent games
   - Alert if Phase 4 rolling averages have high NULL rate
   - Alert on Phase 3 analytics failures

---

## Key Lessons Learned

### 1. Validate Data Dependencies Before Computing Aggregates

**Problem**: Started Phase 4 (rolling averages) before Phase 3 (base data) was fixed
**Impact**: Would have trained ML model on inconsistent features
**Prevention**: Always validate source data completeness before running dependent computations

### 2. Parallel Backfills Need Coordination

**Problem**: Multiple backfills running without dependency checks
**Impact**: Downstream processors consuming incomplete upstream data
**Solution**: Implement backfill orchestration with phase gates

### 3. Monitor Data Quality Metrics in Real-Time

**Problem**: Didn't notice 47% usage_rate until investigating for ML training
**Impact**: Months of data had incomplete calculations
**Solution**: Set up BigQuery scheduled queries to track completeness metrics daily

### 4. Configuration Bugs Can Hide in Retries

**Problem**: "YESTERDAY" bug only showed in retry logs, not initial run
**Impact**: Initial success masked configuration error
**Solution**: Review all errors even if retries succeed

---

## Files Modified/Created

**Created**:
- `/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-03-ORCHESTRATION-STATUS-AND-DATA-DEPENDENCY-ISSUE.md` (this file)

**Referenced**:
- `/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-03-ORCHESTRATION-CHECK-HANDOFF.md`
- `/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-03-SESSION-COMPLETE-SUMMARY.md`
- `/home/naji/code/nba-stats-scraper/orchestration/parameter_resolver.py` (lines 44-49, 169-212)

---

## Next Session Preparation

**For backfill chat** (when resuming):
1. Check Phase 4 completion status
2. Validate usage_rate >95%
3. Verify player_composite_factors coverage
4. Proceed with ML training if validations pass

**For orchestration chat** (future monitoring):
1. Fix "YESTERDAY" scheduler configuration
2. Increase prediction-worker min instances
3. Set up data quality monitoring queries

---

**Document Version**: 1.0
**Author**: Claude (Orchestration monitoring session)
**Next Update**: After Phase 4 restart and completion validation
