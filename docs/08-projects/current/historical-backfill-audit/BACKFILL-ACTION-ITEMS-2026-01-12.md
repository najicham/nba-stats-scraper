# Backfill Validation - Action Items
**Date:** 2026-01-12
**Status:** ✅ Investigation Complete - Ready for Backfill Execution
**Full Report:** `BACKFILL-VALIDATION-REPORT-2026-01-12.md`
**Investigation:** `GAME-ID-FORMAT-INVESTIGATION-2026-01-12.md`

---

## 🎯 Quick Summary

**CORRECTED FINDING:**
- ❌ ~~Game_id format mismatch causing gaps~~ (this was incorrect)
- ✅ **Partial backfill on 2026-01-06 only processed some players**

**ACTUAL ISSUE:**
- A backfill run on Jan 6, 2026 crashed/failed mid-execution
- Partial results were saved (1 player for 2023-02-23, 68 for 2023-02-24)
- ~293 player-game records missing from PCF

**FIX:**
- Re-run PCF backfill for 2023-02-23 and 2023-02-24
- Verify upstream dependencies exist
- Add logging to prevent future silent failures

---

## Critical Issues Requiring Action

### ✅ RESOLVED: Game ID Format (NOT AN ISSUE)

**Original Hypothesis:** Game_id format mismatch causing missing data
**Investigation Result:** Game_id format is **BY DESIGN** and working correctly

**Findings:**
- Two game_id formats exist intentionally:
  - Schedule table: NBA official format `0022200886` (from NBA.com API)
  - Player tables: Custom format `20230223_DEN_CLE` (constructed in Phase 2)
- Custom format is used **consistently** across entire player data pipeline
- No data is missing due to format mismatch

**Conclusion:** No action needed. Format is intentional architecture decision.

**See:** `docs/09-handoff/GAME-ID-FORMAT-INVESTIGATION-2026-01-12.md` for full analysis

---

### 🔴 PRIORITY 1: Partial Backfill Execution (ACTUAL ISSUE)

**Problem:**
A backfill run on **2026-01-06** only partially processed 2 dates, writing incomplete results to BigQuery.

**Evidence:**
```sql
-- All PCF records for these dates created on 2026-01-06
Date         Expected  Actual  Coverage  Created
2023-02-23   187       1       0.5%      2026-01-06 19:37:09
2023-02-24   175       68      39%       2026-01-06 19:37:51
2023-02-25   218       218     100%      2026-01-06 19:38:34
```

**Impact:**
- **2023-02-23:** 186 missing player records (only reggiejackson processed)
- **2023-02-24:** 107 missing player records (only 68/175 processed)
- **Total:** ~293 player-game records missing

**Root Cause Theories:**
1. **Processor crash/timeout** (MOST LIKELY) - Partial progress saved before failure
2. **Data quality issue** - Something about these dates caused silent failures
3. **BigQuery rate limiting** - Processing throttled mid-execution
4. **Orchestration bug** - Player filtering logic error

**Investigation Steps:**
1. Check Cloud Function logs for 2026-01-06 19:35-19:40
   ```bash
   gcloud logging read "timestamp>='2026-01-06T19:30:00Z' AND timestamp<='2026-01-06T19:45:00Z'" \
     --limit 500
   ```
2. Check for timeout, memory, or exception errors
3. Verify upstream dependencies (TDZA, PSZA) have data for these dates
4. Review backfill script code used on 2026-01-06

**Resolution:**
1. ✅ Investigate logs to confirm root cause
2. ✅ Re-run PCF backfill for affected dates:
   ```bash
   PYTHONPATH=. python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
     --start-date 2023-02-23 --end-date 2023-02-24
   ```
3. ✅ Verify 100% coverage after re-run
4. ✅ Add defensive logging to prevent future silent failures

---

### 🟡 PRIORITY 2: Missing Failure Tracking

**Problem:**
Mid-season dates with incomplete PCF coverage show NO records in `nba_processing.precompute_failures` table.

**Evidence:**
- 2023-02-23: 8 games missing, 0 failure records
- 2023-02-24: 2 games missing, 0 failure records
- 2024-02-22: 8 games missing, 0 failure records

**Why This Matters:**
Without failure records, we can't distinguish between:
- Games that failed processing (need retry)
- Games that were never attempted (orchestration gap)
- Games that were skipped intentionally (business logic)

**Investigation Steps:**
1. Check orchestration logs for these specific dates
2. Verify if PCF processor was triggered for these games
3. Review failure logging logic in PCF processor code
4. Check if failures are logged elsewhere (different table/logs)

**Resolution:**
1. Add defensive logging for games that are scheduled but not attempted
2. Implement "not_attempted" status category in failures table
3. Add pre-processing validation: log all game_ids from schedule before processing
4. Set up alerting for games missing from both output AND failures table

---

### 🟡 PRIORITY 3: MLFS Calculation Errors in 2021-22 (Historical)

**Problem:**
ML Feature Store processor has calculation errors for 25 dates in Nov 2021 (2021-22 season only).

**Evidence:**
```
2021-11-02: 108 players with calculation_error
2021-11-03: 230 players with calculation_error
...
Total: 3,968 player-game records missing MLFS features
```

**Impact:**
- Missing ML features for early 2021-22 season
- All other processors (PCF, PDC, PSZA, TDZA) have complete data
- Issue resolved in all subsequent seasons (2022-23 onward are clean)

**Analysis:**
- Likely early-season bootstrap issue or dependency problem
- MLFS features are supplementary (not required for core predictions)
- Self-resolved before 2022-23 season started

**Action Decision:**
- **Low Priority** - Historical data, non-critical feature set
- Can backfill if ML model training requires complete 2021-22 features
- Otherwise, document as "known limitation" for that season

**See:** `PHASE4-VALIDATION-SUMMARY-2026-01-12.md` for full details

---

### 🟢 PRIORITY 4: PSZA Delayed Start (Documentation)

**Problem:**
Player Shot Zone Analysis (PSZA) consistently starts 2-3 days later than other Phase 4 processors.

**Evidence:**
| Season | PCF Start | PSZA Start | Delay |
|--------|-----------|------------|-------|
| 2021-22 | Nov 2, 2021 | Nov 5, 2021 | 3 days |
| 2022-23 | Nov 1, 2022 | Nov 4, 2022 | 3 days |
| 2023-24 | Nov 8, 2023 | Nov 10, 2023 | 2 days |
| 2024-25 | Nov 6, 2024 | Nov 8, 2024 | 2 days |

**Analysis:**
- This is likely **expected behavior** - PSZA needs shot zone data history
- Delay is improving (3 days → 2 days in recent seasons)
- No data quality issues, just coverage timing difference

**Action Items:**
1. ✅ Confirm with system design docs if this delay is intentional
2. ✅ Document in backfill guide as expected behavior
3. ✅ Update validation thresholds to account for PSZA delay
4. ⚠️ Consider: Can PSZA start earlier if history available?

**Impact:** Low - Does not affect prediction quality, just coverage window

---

## Expected Behavior (No Action Needed)

### ✅ Season Bootstrap Period (14 days)

**What It Is:**
Every season has ~14-day gap at start where Phase 4 processors produce no data.

**Why:**
Phase 4 processors require historical data accumulation before generating features:
- Need player game history (last N games)
- Need team performance trends
- Need opponent defense metrics
- Need rolling averages to stabilize

**Affected Dates:**
- 2021-22: Oct 19 - Nov 1 (14 days, 69 games)
- 2022-23: Oct 18 - Oct 31 (14 days, 62 games)
- 2023-24: Oct 24 - Nov 6 (14 days, 68 games)
- 2024-25: Oct 22 - Nov 4 (14 days, 87 games)

**Total:** 62 bootstrap dates across 4 seasons = 286 games

**No backfill needed** - this is by design and documented.

---

## Summary Statistics

### Gaps Breakdown
| Category | Count | Games Affected | Action Required |
|----------|-------|----------------|-----------------|
| 🟢 Bootstrap period (expected) | 62 dates | ~286 games | None - documented |
| 🟢 PSZA delayed start (expected) | 8-12 dates | N/A | Documentation only |
| 🔴 Game ID format issue | 3 dates | ~18 games | **CRITICAL - Investigate & backfill** |
| 🟡 Untracked failures | 3 dates | ~18 games | **HIGH - Add logging** |

### Coverage Summary
| Season | L1 Raw | L3 Analytics | L4 Precompute | Status |
|--------|--------|--------------|---------------|--------|
| 2021-22 | 100% | 100% | 92.9% | ⚠️ 3-5 dates to fix |
| 2022-23 | 100% | 100% | 90.9% | ⚠️ 2 critical dates |
| 2023-24 | 100% | 100% | 90.9% | ⚠️ 1 date to investigate |
| 2024-25 | 100% | 100% | 81.2% | ✅ Healthy (bootstrap expected) |

---

## Next Steps

### Immediate (This Week)
1. 🔍 **Investigate game_id format issue**
   - Review PCF processor code
   - Identify root cause of format discrepancy
   - Determine fix approach (Option A, B, or C)

2. 🔍 **Verify missing game counts**
   - Confirm exactly which games are missing for each date
   - Check if other processors (PDC, PSZA) have same games

3. 📋 **Create detailed backfill plan**
   - Once root cause identified, plan step-by-step backfill
   - Estimate time/resources required
   - Identify dependencies and blockers

### Short Term (Next 2 Weeks)
1. 🔧 **Implement game_id format fix**
   - Apply fix to PCF processor
   - Test on single date to verify
   - Deploy to production

2. 🔄 **Execute backfills**
   - Backfill 2023-02-23 (9 games)
   - Backfill 2023-02-24 (8 games)
   - Backfill 2024-02-22 (12 games)
   - Verify all downstream impacts (Phase 5 predictions)

3. 📊 **Enhance failure tracking**
   - Add "not_attempted" status
   - Implement pre-processing game logging
   - Set up alerting for untracked failures

### Long Term (Next Month)
1. 📚 **Documentation updates**
   - Document bootstrap period as expected
   - Document PSZA delay as expected
   - Update backfill guide with game_id format standards

2. 🔍 **Complete player-level validations**
   - Wait for 2021-24 validation scripts to complete
   - Review any additional issues found
   - Update action items as needed

3. 🤖 **Automation improvements**
   - Add daily Phase 4 completeness validation
   - Alert on any gaps outside bootstrap period
   - Track coverage percentage trends over time

---

## Files Referenced

### Reports
- `docs/09-handoff/BACKFILL-VALIDATION-REPORT-2026-01-12.md` - Full detailed report

### Scripts Used
- `scripts/validation/validate_pipeline_completeness.py`
- `scripts/check_data_completeness.py`
- `scripts/validate_backfill_coverage.py`

### Tables Investigated
- `nba_raw.nbac_schedule` - Game schedule (source of truth)
- `nba_precompute.player_composite_factors` - Phase 4 PCF data
- `nba_precompute.player_daily_cache` - Phase 4 PDC data
- `nba_precompute.player_shot_zone_analysis` - Phase 4 PSZA data
- `nba_processing.precompute_failures` - Failure tracking

---

## Questions for Planning Discussion

1. **Game ID Format:**
   - Is there a business reason for using different game_id formats?
   - Are there downstream systems that depend on the current format?
   - What's the migration path if we standardize formats?

2. **Backfill Priority:**
   - How critical are these 18 missing games for historical predictions?
   - Do we need to backfill Phase 5 predictions after Phase 4 fix?
   - Should we prioritize recent season (2024) over older seasons (2023)?

3. **Failure Tracking:**
   - Where else are processing logs stored beyond `precompute_failures`?
   - Who monitors failure alerts currently?
   - What's the SLA for addressing data gaps?

4. **Bootstrap Period:**
   - Can we reduce the 14-day bootstrap period with synthetic data?
   - Should we document the exact number of games needed for bootstrap?
   - Are there player-specific bootstrap requirements?

---

**Status:** Ready for investigation phase
**Blocking Issues:** None - can proceed with investigation immediately
**Estimated Investigation Time:** 2-4 hours
**Estimated Fix + Backfill Time:** 4-8 hours (after investigation)
