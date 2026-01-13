# Root Cause Analysis: Partial Backfill Failure (Jan 6, 2026)
**Date:** 2026-01-12
**Incident:** PCF backfill only processed 1 player for 2023-02-23 and 68 for 2023-02-24
**Status:** ✅ Resolved - All players now processed (187 and 175 respectively)

---

## Executive Summary

### What Happened
On January 6, 2026, a PCF backfill ran for historical dates (2023-02-23 and 2023-02-24) but only processed a tiny fraction of expected players:
- 2023-02-23: **1 of 187 players** (0.5% coverage)
- 2023-02-24: **68 of 175 players** (39% coverage)

The partial results were saved to BigQuery instead of being rolled back, creating a data gap that persisted for 6 days until discovered during validation.

### Root Cause
**The PCF processor has a design flaw in its fallback logic:**

1. For historical backfills, PCF should use `player_game_summary` (actual players who played)
2. Instead, it queries `upcoming_player_game_context` (players expected to play, populated before games)
3. If `upcoming_player_game_context` has **ANY** records, it uses them (even if incomplete)
4. Only if `upcoming_player_game_context` is **EMPTY** does it fall back to synthetic context from `player_game_summary`

**The trap:** `upcoming_player_game_context` had partial/stale data for these historical dates (likely from a previous incomplete run), so the processor thought it had all the data it needed.

---

## Detailed Timeline

### Background: How PCF Works

```python
# From player_composite_factors_processor.py line 670
SELECT ... FROM `upcoming_player_game_context` WHERE game_date = '{analysis_date}'

# Fallback logic (line 678):
if self.player_context_df.empty and self.is_backfill_mode:
    logger.warning("No upcoming_player_game_context, generating synthetic context from PGS")
    self._generate_synthetic_player_context(analysis_date)
```

**The Issue:**
- Condition: `self.player_context_df.empty` → Must be COMPLETELY EMPTY
- Reality: Had 1 record for 2023-02-23, 68 for 2023-02-24
- Result: Fallback never triggered

---

## Reconstruction of Jan 6 Event

### Jan 6, 2026 - 19:37:00 UTC

**Backfill Started**
```bash
PYTHONPATH=. python backfill_jobs/precompute/player_composite_factors/...
--start-date 2023-02-23 --end-date 2023-02-XX
```

**19:37:09 - Processing 2023-02-23**
1. Query `upcoming_player_game_context` WHERE game_date = '2023-02-23'
2. Found: **1 record** (reggiejackson only)
3. Logic: `player_context_df.empty` = FALSE → Use these records
4. Processed: 1 player
5. MERGE completed: 1 row affected
6. ✅ Marked as SUCCESS

**Why Only 1 Record?**
- `upcoming_player_game_context` is meant for UPCOMING games (future dates)
- For historical dates (2023-02-23), this table should either:
  - Be empty (triggering synthetic fallback)
  - Have ALL 187 players (from when the game was actually upcoming in 2023)
- Instead: Had only 1 player (partial/stale data from unknown earlier process)

**19:37:51 - Processing 2023-02-24**
1. Query `upcoming_player_game_context` WHERE game_date = '2023-02-24'
2. Found: **68 records**
3. Logic: `player_context_df.empty` = FALSE → Use these records
4. Processed: 68 players
5. MERGE completed: 68 rows affected
6. ✅ Marked as SUCCESS

**19:38:00+ - Processing Continued**
- Subsequent dates had empty `upcoming_player_game_context`
- Fallback triggered correctly → Full coverage resumed

---

## Why This Went Undetected

### 1. No Failure Logging
The processor completed "successfully":
- Exit code: 0
- Status: SUCCESS
- No errors in logs
- No records written to `precompute_failures` table

**Why?** The processor did exactly what it was designed to do - process whatever players it found in `upcoming_player_game_context`. It had no way to know that table was incomplete.

### 2. No Coverage Validation
The backfill script doesn't validate that the number of players processed matches expectations:
- No comparison against `player_game_summary`
- No alert when coverage < 90%
- No post-backfill verification

### 3. MERGE Silently Succeeded
BigQuery MERGE operations don't distinguish between:
- "Processed 1 player because that's all there is" (correct)
- "Processed 1 player because that's all I found" (incorrect)

The operation succeeded, data was committed, checkpoint marked as complete.

---

## Resolution Process

### Today's Investigation & Fix

**Step 1: Identified the Pattern**
```sql
SELECT analysis_date, COUNT(*), MIN(created_at)
FROM player_composite_factors
WHERE analysis_date IN ('2023-02-23', '2023-02-24')
-- Result: Both created 2026-01-06 19:37 ← smoking gun
```

**Step 2: Verified Upstream Data Complete**
```sql
SELECT COUNT(*) FROM player_game_summary WHERE game_date = '2023-02-23'
-- Result: 187 ← Full data exists upstream
```

**Step 3: Discovered the Trap**
```sql
SELECT COUNT(*) FROM upcoming_player_game_context WHERE game_date = '2023-02-23'
-- Result: 1 ← Partial stale data blocking fallback
```

**Step 4: Cleared the Trap**
```sql
DELETE FROM upcoming_player_game_context WHERE game_date IN ('2023-02-23', '2023-02-24')
-- Deleted 69 rows (1 + 68)
```

**Step 5: Re-ran Backfill**
```bash
PYTHONPATH=. python backfill_jobs/.../player_composite_factors_precompute_backfill.py \
  --start-date 2023-02-23 --end-date 2023-02-24 --parallel
```

**Result:**
- 2023-02-23: 187 players ✅ (used synthetic context from PGS)
- 2023-02-24: 175 players ✅ (used synthetic context from PGS)
- Coverage: 100% for both dates

---

## Root Causes (5 Whys Analysis)

### Why did the backfill only process 1 player for 2023-02-23?
→ Because `upcoming_player_game_context` only had 1 player record

### Why didn't it use `player_game_summary` instead?
→ Because the fallback is only triggered when `upcoming_player_game_context` is EMPTY

### Why is the fallback condition checking for empty instead of incomplete?
→ Because the processor was designed for upcoming games, not historical backfills

### Why use `upcoming_player_game_context` for historical dates at all?
→ Because there's no flag/logic to distinguish "backfilling historical" vs "processing upcoming"

### Why was there partial data in `upcoming_player_game_context` for historical dates?
→ Unknown - likely from a previous incomplete run that left stale records

---

## Contributing Factors

### Design Factors
1. **Single-source dependency:** PCF assumes `upcoming_player_game_context` is authoritative
2. **Binary fallback:** Either use UPCG fully or PGS fully, no validation of completeness
3. **No historical vs. upcoming mode:** Same code path for both use cases

### Process Factors
1. **No pre-backfill validation:** Doesn't check if upstream sources are complete
2. **No post-backfill validation:** Doesn't verify expected vs actual coverage
3. **Optimistic checkpointing:** Marks dates as "done" based on execution, not verification

### Data Quality Factors
1. **Stale data in UPCG:** Historical dates shouldn't have records in "upcoming" table
2. **No TTL/cleanup:** Old records persist indefinitely
3. **No data provenance:** Can't trace why those 69 records existed

---

## Similar Past Incidents?

**Evidence of Pattern:**
From validation results, we found MLFS had similar issues in 2021-22 season (Nov 2-26):
- 25 dates with calculation errors
- 3,968 player-games missing
- Self-resolved in subsequent seasons

**Hypothesis:** Same root cause - partial/stale upstream data causing incomplete processing.

---

## Impact Assessment

### Data Impact
- **Affected dates:** 2 dates
- **Missing records:** ~293 player-game composite factors (initially)
- **Duration:** 6 days (Jan 6 - Jan 12)
- **Downstream:** Any predictions for these players would have failed/been skipped

### Business Impact
- **Historical data only:** No real-time predictions affected
- **ML Training:** Training data had gaps for these dates
- **Analytics:** Dashboard numbers incorrect for these dates
- **Trust:** Data quality perception impacted

### Detection & Response
- **Time to detect:** 6 days
- **Detection method:** Manual validation (not automated monitoring)
- **Time to resolve:** 1 hour (once root cause identified)
- **False hypotheses:** Spent time investigating game_id format (was not the issue)

---

## Lessons Learned

### What Went Well ✅
1. Comprehensive validation caught the issue across 4 seasons
2. Investigation process systematically eliminated hypotheses
3. Timestamp analysis quickly identified the backfill run
4. Synthetic context fallback worked perfectly once triggered
5. Fix was simple and executed cleanly

### What Went Wrong ❌
1. **Silent failure:** Processor completed successfully despite processing < 1% of expected data
2. **No validation gates:** Backfill didn't verify coverage before checkpointing
3. **Stale data trap:** Partial upstream data blocked the fallback logic
4. **No alerting:** 6-day gap went undetected until manual validation
5. **False hypothesis:** Initially suspected game_id format issue (wasted investigation time)

### What We Got Lucky With 🍀
1. Issue affected only 2 dates (not widespread)
2. All upstream data was intact (easy to backfill)
3. Synthetic fallback mechanism already existed (didn't need new code)
4. Historical data only (not production predictions)

---

## Recommendations

See `BACKFILL-IMPROVEMENTS-PLAN-2026-01-12.md` for detailed implementation plan.

### Immediate (This Week)
1. ✅ **DONE:** Re-run backfill for affected dates
2. **TODO:** Add coverage validation to backfill script
3. **TODO:** Clear stale `upcoming_player_game_context` records for all historical dates
4. **TODO:** Add pre-flight check: Compare UPCG count vs PGS count

### Short Term (Next 2 Weeks)
1. **Defensive logging:** Log expected vs actual player counts
2. **Coverage gates:** Block checkpoint if coverage < 90%
3. **Fallback improvement:** Trigger synthetic fallback if UPCG count << PGS count
4. **Alerting:** Slack notification if any date processes < 50% expected players

### Long Term (Next Month)
1. **Separate code paths:** Different logic for historical backfill vs upcoming processing
2. **Data cleanup:** TTL policy for `upcoming_player_game_context` (delete after game completes)
3. **Validation framework:** Automated post-backfill verification
4. **Observability:** Dashboard showing backfill coverage in real-time

---

## Appendix: Technical Details

### Fallback Logic (Current)
```python
# player_composite_factors_processor.py:678-680
if self.player_context_df.empty and self.is_backfill_mode:
    logger.warning(f"No upcoming_player_game_context for {analysis_date}, "
                  "generating synthetic context from PGS (backfill mode)")
    self._generate_synthetic_player_context(analysis_date)
```

### Proposed Improvement
```python
# Check if count is substantially lower than expected
expected_count = self._get_expected_player_count(analysis_date)
actual_count = len(self.player_context_df)

if self.is_backfill_mode and actual_count < expected_count * 0.9:
    logger.warning(f"UPCG has only {actual_count}/{expected_count} players "
                  f"({actual_count/expected_count*100:.1f}%), "
                  "falling back to synthetic context from PGS")
    self._generate_synthetic_player_context(analysis_date)
```

### Data Cleanup Query
```sql
-- Clear historical dates from upcoming_player_game_context
-- (these should only contain truly upcoming games)
DELETE FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date < CURRENT_DATE() - INTERVAL 7 DAY;
```

---

**Analysis Complete:** 2026-01-12
**Status:** Root cause identified, resolved, and documented
**Next Action:** Implement prevention measures
