# Backfill Execution Plan Review

**Reviewed:** 2025-11-28 9:45 PM PST
**Document:** BACKFILL-EXECUTION-PLAN.md
**Reviewer:** Claude (Opus 4.5)
**Status:** Review Complete - Critical Issues Identified

---

## Review Summary

The backfill execution plan is comprehensive and well-structured, covering all 5 phases with detailed scripts and verification procedures. However, several critical issues must be addressed before production execution to prevent data loss, silent failures, and inability to recover from interruptions.

**Verdict:** Needs fixes before execution

| Category | Count |
|----------|-------|
| Critical Issues | 5 |
| Important Issues | 5 |
| Script Bugs | 6 |
| Missing Steps | 5 |
| Optimizations | 4 |
| Verification Enhancements | 4 |
| Questions Needing Answers | 6 |

---

## Part 1: Critical Issues (Must Fix)

### Critical Issue 1: Missing Error Handling When Date Fetch Returns Empty

**Location:** `backfill_historical_phases1_2.sh` line 301

**Problem:** If `get_game_dates_for_season` returns empty (network error, bad query, wrong season format), the script continues with an empty `game_dates` array, logging "Found 0 game dates" but not stopping.

**Impact:** Script completes "successfully" with no data processed. User thinks backfill is done.

**Fix:**
```bash
mapfile -t game_dates < <(get_game_dates_for_season "$season")

if [ ${#game_dates[@]} -eq 0 ]; then
  log_error "No game dates found for ${season}. Check nba_schedule table."
  exit 1
fi

log_info "Found ${#game_dates[@]} game dates for ${season}"
```

---

### Critical Issue 2: The 85% Threshold in Phase 2 Wait is Dangerous

**Location:** `backfill_historical_phases1_2.sh` line 269

**Problem:** `if [ "$completed" -ge 18 ]; then` allows 3 processors to fail silently. These failed processors will never be retried.

**Impact:**
- 15% of raw data systematically missing for all dates
- Phase 3 starts with incomplete data
- Data quality issues compound through pipeline

**What happens to the 15%?** They're lost. The script continues to next batch, orchestrator never gets their completion, Phase 3 runs with partial data.

**Fix:** Either:
1. Require 100% completion (21/21)
2. Track and retry failed processors before moving on
3. At minimum, create a `failed_processors.log` file for manual retry

```bash
if [ "$completed" -lt 21 ]; then
  # Log which processors failed for later retry
  echo "${game_date}" >> failed_dates_phase2.log
  log_warn "Phase 2 incomplete: ${completed}/21 for ${game_date}"
fi
```

---

### Critical Issue 3: No Signal Handling (Ctrl+C)

**Location:** All scripts

**Problem:** If you Ctrl+C during execution, background processes continue running. `wait` is killed but spawned curls keep going.

**Impact:**
- Orphaned HTTP requests continue hitting APIs
- Partial state left in Firestore
- Unclear what was completed

**Fix:**
```bash
# Add at top of each script
cleanup() {
  log_warn "Caught interrupt, stopping..."
  # Kill all background jobs from this script
  jobs -p | xargs -r kill 2>/dev/null
  exit 1
}

trap cleanup INT TERM
```

---

### Critical Issue 4: No Resume Capability

**Location:** All scripts

**Problem:** If the script crashes at batch 25 of 50, you must start from scratch. There's no checkpoint or progress file.

**Impact:**
- Re-processing already-completed dates (wasted time/cost)
- Risk of hitting API rate limits more aggressively
- Cannot safely stop and resume overnight

**Fix:** Add checkpoint file tracking:
```bash
CHECKPOINT_FILE="/tmp/backfill_phase1_2_checkpoint.txt"

# After each batch
echo "${season}:${batch_end}" > "$CHECKPOINT_FILE"

# At start, check for checkpoint
if [ -f "$CHECKPOINT_FILE" ]; then
  read checkpoint < "$CHECKPOINT_FILE"
  log_info "Resuming from checkpoint: $checkpoint"
  # Parse and skip completed seasons/batches
fi
```

---

### Critical Issue 5: `--max_rows=1000` Limit May Truncate Silently

**Location:** `backfill_historical_phases1_2.sh` line 210, `backfill_phase3.sh` line 544, `backfill_phase4.sh` line 830

**Problem:** The BigQuery queries use `--max_rows=1000`. While 4 seasons (~500 dates) fits within this limit now, this is a latent bug for larger date ranges.

**Impact:** Silent truncation of dates - you'd process only the first 1000 dates and think you're done.

**Fix:**
```bash
# Increase to safe limit
--max_rows=2000
```

---

## Part 2: Important Issues (Should Fix)

### Important Issue 1: Current Season Script Has Incomplete Scraper List

**Location:** `backfill_current_season.sh` line 1133-1139

**Problem:** Script shows only 4 scrapers with `# ... (all 21 scrapers)` comment. If someone copies this script, they get incomplete list.

**Impact:** Current season backfill would only run 4 scrapers instead of 21.

**Fix:** Include full scraper list or reference a shared file.

---

### Important Issue 2: No Rate Limiting for API Calls

**Location:** All scraper triggering loops

**Problem:** The script fires 210 concurrent HTTP requests (10 dates × 21 scrapers) instantly. This may overwhelm:
- NBA.com APIs (rate limits)
- Cloud Run autoscaling (cold starts)
- Pub/Sub message handling

**Impact:**
- API rate limit errors
- Cloud Run 503s during cold start surge
- Potential for cascading failures

**Fix:** Add staggered starting or small sleep between batches:
```bash
# Add 100ms between each scraper trigger
sleep 0.1
```

Or use progressive ramp-up for first batch.

---

### Important Issue 3: `wait` Without Error Collection

**Location:** All scripts after parallel execution

**Problem:** `wait` exits with status of last background job. If 20 curls succeed and 1 fails, you only see the last one's status.

**Impact:** Script may continue even if some scrapers failed silently.

**Fix:**
```bash
# Collect background job PIDs and check each
pids=()
for scraper in "${SCRAPERS[@]}"; do
  trigger_scraper "$scraper" "$date" &
  pids+=($!)
done

failed=0
for pid in "${pids[@]}"; do
  wait $pid || ((failed++))
done

if [ $failed -gt 0 ]; then
  log_warn "$failed scrapers failed in this batch"
fi
```

---

### Important Issue 4: Phase 4 Wait Time May Be Too Short

**Location:** `backfill_phase4.sh` line 903

**Problem:** 40 minutes timeout for Phase 4 with 10 dates. Phase 4 has complex 3-level dependencies and is described as "heavier processing." The ml_feature_store processor alone could take 20+ minutes per date.

**Impact:** Premature timeout leading to incomplete processing.

**Fix:** Consider 60-90 minutes or make timeout proportional to batch size:
```bash
local max_wait_seconds=$((PARALLEL_DATES * 6 * 60))  # 6 min per date
```

---

### Important Issue 5: No Cost Tracking During Backfill

**Location:** All scripts

**Problem:** Estimated cost is $80-150 but there's no monitoring during execution to verify this.

**Impact:** Could significantly overrun budget without warning.

**Fix:** Add BigQuery cost query every 10 batches:
```bash
bq query --use_legacy_sql=false "
SELECT ROUND(SUM(total_bytes_billed)/1e12 * 5, 2) as cost_usd
FROM \`nba-props-platform.region-us-west2.INFORMATION_SCHEMA.JOBS_BY_PROJECT\`
WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
"
```

---

## Part 3: Script Bugs (Actual Errors)

### Bug 1: Bash Integer Comparison with Potentially Empty Variable

**Location:** `backfill_historical_phases1_2.sh` line 269

**Problem:**
```bash
if [ "$completed" -ge 18 ]; then
```

If the BigQuery query fails or returns empty, `$completed` is empty string, causing `[: -ge: unary operator expected`.

**Fix:**
```bash
if [ "${completed:-0}" -ge 18 ]; then
```

---

### Bug 2: `curl` Silent Failure Mode

**Location:** All curl calls, e.g., line 241-244

**Problem:**
```bash
curl -X POST "${SCRAPER_URL}/scrape" \
  -H "Content-Type: application/json" \
  -d "${payload}" \
  -s -o /dev/null -w "%{http_code}" 2>&1
```

If the server is completely unreachable (DNS failure, network down), curl returns empty string, not an error code.

**Impact:** Script sees empty http_code, neither 200 nor non-200 check matches, no output logged.

**Fix:**
```bash
http_code=$(curl -X POST ... --connect-timeout 10 --max-time 60 \
  -s -o /dev/null -w "%{http_code}" 2>&1) || http_code="000"
```

---

### Bug 3: Array Index -1 Requires Bash 4.3+

**Location:** `backfill_historical_phases1_2.sh` line 321

**Problem:**
```bash
log_info "Dates: ${batch_dates[0]} to ${batch_dates[-1]}"
```

`${array[-1]}` syntax requires Bash 4.3+. May fail on older Bash versions.

**Impact:** Script crash on systems with Bash < 4.3.

**Fix:**
```bash
local last_idx=$((${#batch_dates[@]} - 1))
log_info "Dates: ${batch_dates[0]} to ${batch_dates[$last_idx]}"
```

---

### Bug 4: `nameref` (-n) Requires Bash 4.3+

**Location:** `backfill_phase3.sh` line 600, `backfill_phase4.sh` line 901

**Problem:**
```bash
local -n dates_ref=$1
```

Name references (`-n`) require Bash 4.3+.

**Impact:** Script fails on older Bash with `local: -n: invalid option`.

**Fix:** Either document Bash 4.3+ requirement or use different pattern:
```bash
# Pass array elements directly
wait_for_phase3_batch "${batch_dates[@]}"

# In function
wait_for_phase3_batch() {
  local dates=("$@")
  ...
}
```

---

### Bug 5: Missing Timeout on curl Commands

**Location:** All curl calls

**Problem:** No `--max-time` or `--connect-timeout` set. A hanging connection could block the script indefinitely.

**Fix:**
```bash
curl --connect-timeout 10 --max-time 120 ...
```

---

### Bug 6: Variable Scope in Background Subshells

**Location:** `backfill_historical_phases1_2.sh` lines 329-339

**Problem:**
```bash
for scraper in "${SCRAPERS[@]}"; do
  {
    http_code=$(trigger_scraper "$scraper" "$date" true)
    # echo inside subshell goes to stdout, not captured
  } &
done
```

The `echo` output from background jobs intermingles and can't be properly tracked.

**Impact:** Messy output, can't reliably tell which scrapers succeeded.

**Fix:** Write results to temp file or use job control more carefully.

---

## Part 4: Missing Steps (Gaps in Plan)

### Missing Step 1: Pre-Flight Validation Script

**What's missing:** No script verifies prerequisites before starting backfill:
- Is nba_schedule table populated?
- Do all required BigQuery tables exist?
- Are Cloud Run services deployed and healthy?
- Is there sufficient quota?

**Why it matters:** Discovering missing prerequisites 2 hours into backfill wastes time.

**What to add:**
```bash
#!/bin/bash
# bin/backfill/preflight_check.sh

# Check schedule exists
schedule_count=$(bq query --format=csv "SELECT COUNT(*) FROM nba_reference.nba_schedule" | tail -1)
if [ "$schedule_count" -lt 1000 ]; then
  echo "ERROR: nba_schedule appears empty or underpopulated"
  exit 1
fi

# Check Cloud Run services healthy
for service in nba-phase1-scrapers nba-phase3-analytics-processors; do
  status=$(gcloud run services describe $service --format='value(status.conditions[0].status)' 2>/dev/null)
  if [ "$status" != "True" ]; then
    echo "ERROR: Service $service not healthy"
    exit 1
  fi
done

echo "✅ All preflight checks passed"
```

---

### Missing Step 2: Progress Logging to File

**What's missing:** All output goes to stdout. If terminal disconnects, progress is lost.

**Why it matters:** Multi-day backfill needs persistent logs.

**What to add:**
```bash
# At top of script
exec > >(tee -a backfill_$(date +%Y%m%d_%H%M%S).log) 2>&1
```

---

### Missing Step 3: Cleanup of Firestore State Before Backfill

**What's missing:** No mention of clearing Firestore orchestrator state before backfill.

**Why it matters:** Stale orchestrator state from previous runs could cause issues (e.g., orchestrator thinks Phase 2 already complete for a date).

**What to add:**
```bash
# Before starting backfill, clear orchestrator state
# Option 1: Delete all completion documents
# Option 2: Use --force flag that ignores existing state
```

---

### Missing Step 4: Failed Date/Processor Tracking

**What's missing:** No mechanism to track which specific dates/processors failed for later retry.

**Why it matters:** With 10,500 scraper runs, some will fail. Need to know exactly which ones.

**What to add:**
```bash
# Create failed tracking file
FAILED_LOG="backfill_failed_$(date +%Y%m%d).log"

# On failure
echo "${date},${scraper},${http_code}" >> "$FAILED_LOG"

# At end, report
if [ -f "$FAILED_LOG" ]; then
  log_warn "Some operations failed. See: $FAILED_LOG"
  log_warn "Failed count: $(wc -l < $FAILED_LOG)"
fi
```

---

### Missing Step 5: Rollback Procedure

**What's missing:** What if backfill completes but data is wrong? No documented rollback.

**Why it matters:** Need ability to delete and re-run.

**What to add:** Document DELETE queries for each phase:
```sql
-- Rollback Phase 2 for a season
DELETE FROM nba_raw.* WHERE season = '2023-24';

-- Rollback Phase 3
DELETE FROM nba_analytics.player_game_summary WHERE season = '2023-24';
-- etc.
```

---

## Part 5: Optimization Opportunities

### Optimization 1: Progressive Parallelism Ramp-Up

**Current:** Fixed 10 dates throughout

**Better:** Start with 5 dates (cold start), increase to 20 after warm-up:
```bash
if [ $batch_num -le 3 ]; then
  EFFECTIVE_PARALLEL=5  # Warm-up
elif [ $batch_num -le 10 ]; then
  EFFECTIVE_PARALLEL=10  # Normal
else
  EFFECTIVE_PARALLEL=20  # Full speed
fi
```

**Expected Improvement:** 30-40% faster for Phase 1-2 (after initial batches)

---

### Optimization 2: Skip Already-Processed Dates at Script Start

**Current:** Script processes all dates, relying on processor deduplication

**Better:** Query processor_run_history at start, filter out completed dates:
```bash
# Get already-completed dates
bq query "SELECT DISTINCT data_date FROM processor_run_history
WHERE phase = 'phase_2_raw' AND status = 'success'" > completed_dates.txt

# Filter from processing list
```

**Expected Improvement:** Saves time on resume, avoids redundant API calls

---

### Optimization 3: Overlap Phase 3-4 Execution

**Current:** Phase 3 completes 100%, then Phase 4 starts

**Better:** Phase 4 can start once Phase 3 has processed enough dates for rolling averages (typically D-7 through D)

**Expected Improvement:** 2-3 hours saved

---

### Optimization 4: Reduce Per-Date Verification Queries

**Current:** Verification query after every date in batch

**Better:** Verify once at end of batch with a single query for all dates:
```sql
SELECT game_date, COUNT(DISTINCT processor_name) as completed
FROM processor_run_history
WHERE game_date IN ('2024-01-01', '2024-01-02', ...)
GROUP BY game_date
```

**Expected Improvement:** Fewer BigQuery queries, faster per-batch completion

---

## Part 6: Verification Enhancements

### Enhancement 1: Cross-Phase Player Count Consistency

**Add query to verify player counts match across phases:**
```sql
WITH phase_counts AS (
  SELECT
    game_date,
    (SELECT COUNT(DISTINCT player_id) FROM nba_raw.nbac_player_boxscore WHERE game_date = d.game_date) as phase2,
    (SELECT COUNT(DISTINCT player_lookup) FROM nba_analytics.player_game_summary WHERE game_date = d.game_date) as phase3,
    (SELECT COUNT(DISTINCT player_lookup) FROM nba_precompute.ml_feature_store_v2 WHERE game_date = d.game_date) as phase4
  FROM (SELECT DISTINCT game_date FROM nba_raw.bdl_games WHERE season = '2023-24') d
)
SELECT * FROM phase_counts
WHERE phase4 < phase2 * 0.90  -- Flag >10% drop
```

---

### Enhancement 2: Data Distribution Sanity Check

**Add stats distribution validation:**
```sql
SELECT
  season,
  AVG(points) as avg_points,
  STDDEV(points) as stddev_points,
  MIN(points) as min_points,
  MAX(points) as max_points
FROM nba_analytics.player_game_summary
GROUP BY season
ORDER BY season
```

If average points is 0 or 500, something is wrong.

---

### Enhancement 3: Null Field Percentage Check

**Add null detection:**
```sql
SELECT
  'player_game_summary' as table_name,
  ROUND(100 * COUNTIF(points IS NULL) / COUNT(*), 2) as pct_null_points,
  ROUND(100 * COUNTIF(player_lookup IS NULL) / COUNT(*), 2) as pct_null_player,
  COUNT(*) as total_rows
FROM nba_analytics.player_game_summary
WHERE season IN ('2020-21', '2021-22', '2022-23', '2023-24')
```

---

### Enhancement 4: Year-over-Year Comparison

**Compare seasons to catch systemic issues:**
```sql
SELECT
  season,
  COUNT(DISTINCT game_date) as game_dates,
  COUNT(DISTINCT player_lookup) as unique_players,
  AVG(points) as avg_points
FROM nba_analytics.player_game_summary
GROUP BY season
ORDER BY season
```

2023-24 should look similar to 2022-23. Major deviations suggest data issues.

---

## Part 7: Questions & Clarifications

### Question 1: NBA API Rate Limits

**Question:** Do NBA.com APIs have rate limits? The plan calls for 210 concurrent API calls.

**Options:**
- A) No rate limits - proceed as planned
- B) Rate limits exist but are high (>1000/min) - add small delays
- C) Rate limits are strict - need significant throttling

**Recommendation:** Test with 5 concurrent dates first, monitor for 429 responses.

---

### Question 2: Phase 3 Processor Dependencies

**Question:** Do all 5 Phase 3 processors need all 21 Phase 2 tables? Or do some only need specific tables?

**Impact:** Could start Phase 3 earlier if some processors only need subset.

**Recommendation:** Document Phase 3 dependencies explicitly.

---

### Question 3: Rolling Average Date Dependencies

**Question:** Phase 3 analytics for date D - does it need data from D-1, D-2, etc. (for rolling averages)?

**Impact:** If yes, must process dates in chronological order, not parallel.

**Recommendation:** Verify rolling average window requirements before parallel processing.

---

### Question 4: Current Season Sequential Requirement

**Question:** Why is current season (Phase 5) processed sequentially? Is this for validation or technical requirement?

**Options:**
- A) Validation only - can parallelize after first few dates succeed
- B) Technical requirement - must be sequential
- C) Conservative choice - parallelize if comfortable

**Recommendation:** Try parallel after first 5 dates validate successfully.

**Potential Time Savings:** 2-3 hours → 30-45 minutes

---

### Question 5: Overnight Execution Environment

**Question:** Will this run overnight unattended? What happens if laptop sleeps or network drops?

**Options:**
- A) Run in tmux/screen session on a VM
- B) Run from Cloud Shell (persistent)
- C) Convert to Cloud Workflow (fully managed)

**Recommendation:** Use tmux on a persistent VM or Cloud Shell for multi-day execution.

---

### Question 6: What Bash Version is Required?

**Question:** Scripts use Bash 4.3+ features (`${array[-1]}`, `local -n`). Is this documented?

**Recommendation:** Add version check at top of scripts:
```bash
if ((BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 3))); then
  echo "ERROR: Bash 4.3+ required"
  exit 1
fi
```

---

## Action Items Summary

### Before Execution (Critical)

| # | Issue | Fix |
|---|-------|-----|
| 1 | Empty date list not caught | Add check + exit |
| 2 | 85% threshold loses data | Require 100% or track failures |
| 3 | No Ctrl+C handling | Add trap cleanup |
| 4 | No resume capability | Add checkpoint file |
| 5 | Integer comparison with empty var | Use `${var:-0}` |

### Before Execution (Important)

| # | Issue | Fix |
|---|-------|-----|
| 1 | Incomplete scraper list | Add all 21 scrapers |
| 2 | No rate limiting | Add sleep between calls |
| 3 | Silent curl failures | Add timeout + error handling |
| 4 | Phase 4 timeout too short | Increase to 60+ minutes |
| 5 | Missing preflight check | Create preflight script |

### Nice to Have

| # | Improvement | Benefit |
|---|-------------|---------|
| 1 | Progressive parallelism | 30-40% faster |
| 2 | Skip completed dates | Faster resume |
| 3 | Cost tracking | Budget monitoring |
| 4 | Cross-phase verification | Data quality assurance |

---

## Conclusion

The backfill execution plan is well-designed and comprehensive. With the critical fixes applied, it should execute reliably over the 3-4 day period. The most important fixes are:

1. **Error handling for empty dates** - prevents silent "success" with no data
2. **100% completion requirement** - prevents systematic data loss
3. **Signal handling** - clean shutdown on interrupt
4. **Resume capability** - essential for multi-day execution

Once these are addressed, the plan is ready for production execution.

---

**Review Complete:** 2025-11-28 9:45 PM PST

---
---

# Addendum: Secondary Review

**Reviewer:** Claude (Opus 4.5) - Different Chat Session
**Date:** 2025-11-28 ~10:30 PM PST
**Purpose:** Independent verification and additions to primary review

---

## Agreement with Primary Review

The primary review is **comprehensive and high-quality**. I agree with virtually all findings:

- All 5 critical issues are valid and correctly prioritized
- All 6 script bugs are technically accurate
- All 5 missing steps are valuable additions
- The optimization opportunities are sound

The most important findings that must be addressed:
1. **85% threshold** - Will cause systematic 15% data loss
2. **No resume capability** - Essential for 3-day execution
3. **Signal handling** - Prevents orphaned processes
4. **Empty date list handling** - Prevents silent "success" with no data

---

## Additional Findings

### Additional Critical Issue: Rolling Average Date Dependencies

**Location:** Phase 3 parallel processing (20 dates simultaneously)

**Problem:** If Phase 3 analytics compute rolling averages (e.g., "average points over last 5 games"), then processing date D requires dates D-1, D-2, D-3, D-4, D-5 to already be complete in the analytics tables.

**Impact:** If dates are processed in parallel, rolling calculations may use incomplete or missing historical data, resulting in incorrect analytics that cascade to Phase 4 and predictions.

**Example:**
```
Batch processes: 2024-01-10, 2024-01-11, 2024-01-12, 2024-01-13 in parallel
2024-01-13's "last 5 games" rolling average needs 01-08 through 01-12
But 01-12's analytics are being computed simultaneously → race condition
Rolling average uses stale/missing data → incorrect result
```

**Clarification Needed:** Do Phase 3 analytics:
- A) Only read from Phase 2 raw tables (safe for parallel)
- B) Read from their own Phase 3 output tables for rolling windows (NOT safe for parallel)

**Fix (if B):** Either:
1. Process dates strictly chronologically (sequential, not parallel)
2. Process in chronological waves with buffer: all dates before Jan 1 first, then Jan 1-10, then Jan 11-20, etc.
3. Ensure rolling calculations only use Phase 2 raw data, not Phase 3 outputs

**Priority:** Must clarify before Phase 3 execution - could cause systematic data quality issues.

---

### Additional Script Bug: Interactive `read` Breaks Unattended Execution

**Location:** `backfill_current_season.sh` line 1316

**Problem:**
```bash
read -p "Continue with next date? (y/n) " -n 1 -r
```

This interactive prompt will hang indefinitely if running in:
- tmux/screen without attached terminal
- Background job (`./script.sh &`)
- nohup execution
- Cloud Shell that disconnects

**Impact:** Script appears frozen, no progress, requires manual intervention.

**Fix:**
```bash
# Add timeout with default action
if [ -t 0 ]; then
    # Interactive terminal available
    read -t 60 -p "Continue with next date? (y/n, defaults to y in 60s) " -n 1 -r || REPLY="y"
    echo
else
    # Non-interactive, auto-continue
    log_warn "Non-interactive mode: auto-continuing after failure"
    REPLY="y"
fi

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_error "Stopping backfill"
    exit 1
fi
```

---

### Additional Missing Step: Tmux/Screen Wrapper Script

**What's missing:** No script to start backfill in detached session that survives disconnects.

**Why it matters:** 3-day backfill requires persistent execution. Laptop sleep, SSH timeout, or network drop will kill the process.

**What to add:**
```bash
#!/bin/bash
# bin/backfill/run_backfill_detached.sh
#
# Start backfill in detached tmux session

set -euo pipefail

SESSION_NAME="backfill_$(date +%Y%m%d)"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

# Check if session already exists
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "Session $SESSION_NAME already exists!"
    echo "Attach with: tmux attach -t $SESSION_NAME"
    exit 1
fi

# Start detached session
tmux new-session -d -s "$SESSION_NAME" -n "phase1_2" \
    "./bin/backfill/backfill_historical_phases1_2.sh 2>&1 | tee ${LOG_DIR}/phase1_2_$(date +%Y%m%d_%H%M%S).log; echo 'Phase 1-2 complete. Run Phase 3 manually.'; exec bash"

echo "========================================"
echo "Backfill started in detached session"
echo "========================================"
echo "Session name: $SESSION_NAME"
echo "Log file: ${LOG_DIR}/phase1_2_*.log"
echo ""
echo "Commands:"
echo "  Attach:  tmux attach -t $SESSION_NAME"
echo "  Detach:  Ctrl+B then D"
echo "  Kill:    tmux kill-session -t $SESSION_NAME"
echo ""
echo "Monitor progress:"
echo "  tail -f ${LOG_DIR}/phase1_2_*.log"
```

---

### Additional Important Issue: BigQuery Slot Contention

**Problem:** Running 210 concurrent BigQuery operations (10 dates × 21 processors) may exhaust available BigQuery slots in the on-demand pricing tier.

**Impact:**
- Queries queue instead of running immediately
- Wait times increase unpredictably
- Timeout thresholds may trigger incorrectly
- Overall backfill takes longer than estimated

**Symptoms:**
- Phase 2 wait times much longer than expected
- BigQuery console shows many "PENDING" jobs
- Inconsistent batch completion times

**Monitoring to Add:**
```bash
# Add to monitor_progress.sh
echo "BigQuery Job Queue:"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  state,
  COUNT(*) as job_count,
  AVG(TIMESTAMP_DIFF(COALESCE(start_time, CURRENT_TIMESTAMP()), creation_time, SECOND)) as avg_queue_seconds
FROM \`region-us-west2.INFORMATION_SCHEMA.JOBS_BY_PROJECT\`
WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY state
"
```

**Mitigation:** If slot contention observed, reduce `PARALLEL_DATES` from 10 to 5.

---

### Minor Correction: Bug 6 Reassessment

**Original finding:** "Variable Scope in Background Subshells" labeled as bug

**Reassessment:** The interleaved stdout output from background jobs is intentional for user feedback, not a bug. The code works correctly - each background job's `echo` goes to stdout as designed.

**However:** The review's underlying concern is valid - the interleaved output makes it impossible to programmatically determine which specific scrapers succeeded or failed. This is a **design limitation** rather than a bug.

**Recommendation:** Keep the current behavior for visual feedback, but add the failed tracking log (Missing Step 4) for programmatic analysis.

---

## Updated Action Items

### Before Execution (Critical) - Updated

| # | Issue | Source | Fix |
|---|-------|--------|-----|
| 1 | Empty date list not caught | Primary | Add check + exit |
| 2 | 85% threshold loses data | Primary | Require 100% or track failures |
| 3 | No Ctrl+C handling | Primary | Add trap cleanup |
| 4 | No resume capability | Primary | Add checkpoint file |
| 5 | Integer comparison with empty var | Primary | Use `${var:-0}` |
| 6 | **Rolling average date dependencies** | Secondary | **Clarify before Phase 3** |

### Before Execution (Important) - Updated

| # | Issue | Source | Fix |
|---|-------|--------|-----|
| 1 | Incomplete scraper list | Primary | Add all 21 scrapers |
| 2 | No rate limiting | Primary | Add sleep between calls |
| 3 | Silent curl failures | Primary | Add timeout + error handling |
| 4 | Phase 4 timeout too short | Primary | Increase to 60+ minutes |
| 5 | Missing preflight check | Primary | Create preflight script |
| 6 | **Interactive read in current season** | Secondary | Add timeout/non-interactive mode |
| 7 | **No detached execution wrapper** | Secondary | Add tmux wrapper script |
| 8 | **BigQuery slot contention** | Secondary | Add monitoring, reduce parallelism if needed |

---

## Conclusion

The primary review is thorough and ready for use. The critical issues it identifies must be fixed before execution.

My additions focus on:
1. **Date dependency ordering** - Potentially critical if Phase 3 uses rolling windows
2. **Unattended execution robustness** - Interactive prompts and session persistence
3. **Resource contention** - BigQuery slots under high parallelism

**Recommendation:** Before running Phase 3, verify whether analytics processors read from their own output tables for rolling calculations. If yes, parallel processing is unsafe.

---

**Secondary Review Complete:** 2025-11-28 ~10:30 PM PST
