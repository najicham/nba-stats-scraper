# Pre-Flight Verification Script - Implementation Complete

**Date:** 2025-11-30
**Session Focus:** Create automated pre-flight verification before backfill execution
**Status:** ✅ Complete and tested
**Related:** BACKFILL-PLANNING-SESSION-COMPLETE.md, BACKFILL-MONITOR-COMPLETE.md

---

## Summary

Created comprehensive automated pre-flight verification script that validates all infrastructure, data readiness, and backfill jobs before starting 4-year historical backfill.

---

## What Was Created

### Pre-Flight Verification Script

**Location:** `bin/backfill/preflight_verification.sh`

**Features:**
- ✅ 14 comprehensive checks (infrastructure, data, jobs)
- ✅ Color-coded output (pass/fail/warn)
- ✅ Quick mode (skip dry-runs for fast validation)
- ✅ Full mode (includes dry-run tests)
- ✅ Exit codes (0=ready, 1=critical failures, 2=warnings)
- ✅ Helpful error messages with manual commands
- ✅ Progress counters (passed/failed/warnings)

**Checks Performed:**

1. **GCP Authentication & Project** - Verify authenticated and using nba-props-platform
2. **Python Dependencies** - Check google-cloud-bigquery available
3. **BigQuery Datasets** - Verify nba_raw, nba_analytics, nba_precompute, nba_reference exist
4. **Pub/Sub Topics** - Check phase2-complete, phase3-complete, phase4-trigger exist
5. **Cloud Run Services** - Verify all 6 services deployed (Phase 1-4 + 2 orchestrators)
6. **Phase 2 Completeness** - Validate 675/675 dates (100%)
7. **Phase 3 Current State** - Capture starting state (~348 dates)
8. **Phase 4 Current State** - Capture starting state (~0 dates)
9. **Phase 3 Backfill Jobs** - Verify all 5 job files exist
10. **Phase 4 Backfill Jobs** - Verify all 5 job files exist
11. **BettingPros Fallback** - Check if fallback implemented
12. **Backfill Monitor** - Verify monitoring tool exists
13. **Phase 3 Dry-Run Test** - Actually run player_game_summary dry-run
14. **Phase 4 Dry-Run Test** - Actually run player_shot_zone_analysis dry-run

---

## Usage

### Quick Check (30 seconds)
```bash
./bin/backfill/preflight_verification.sh --quick
```
Skips dry-run tests (checks 1-12 only).

### Full Check (60 seconds)
```bash
./bin/backfill/preflight_verification.sh
```
Includes dry-run tests (all 14 checks).

### Exit Codes
- `0` - All checks passed, ready for backfill
- `1` - Critical failures, do not proceed
- `2` - Warnings, proceed with caution

---

## Current Test Results

✅ **All 14 checks PASSED**

```
========================================
PRE-FLIGHT VERIFICATION SUMMARY
========================================
Passed:   14
Failed:   0
Warnings: 0

🎉 ALL CHECKS PASSED - READY FOR BACKFILL
```

### Detailed Results:

**Infrastructure (Checks 1-5):**
- ✅ Authenticated with nba-props-platform
- ✅ Python dependencies available
- ✅ All 4 BigQuery datasets exist
- ✅ All 3 Pub/Sub topics exist
- ✅ All 6 Cloud Run services deployed

**Data State (Checks 6-8):**
- ✅ Phase 2: 675/675 dates (100%)
- ✅ Phase 3: 348 dates captured
- ✅ Phase 4: 0 dates captured

**Backfill Jobs (Checks 9-12):**
- ✅ All 5 Phase 3 backfill jobs exist
- ✅ All 5 Phase 4 backfill jobs exist
- ✅ BettingPros fallback implemented
- ✅ Backfill monitor available

**Functional Tests (Checks 13-14):**
- ✅ Phase 3 dry-run successful (player_game_summary)
- ✅ Phase 4 dry-run successful (player_shot_zone_analysis)

---

## Example Output

```bash
$ ./bin/backfill/preflight_verification.sh

========================================
NBA BACKFILL PRE-FLIGHT VERIFICATION
========================================

This script will verify that all infrastructure and jobs are ready
for the 4-year historical backfill (2021-2024, 675 game dates).

Target date range: 2021-10-01 to 2024-11-29


✓ Checking: GCP Authentication & Project
  ✅ PASS: Authenticated and using correct project: nba-props-platform

✓ Checking: Python Dependencies
  ✅ PASS: Python dependencies available

✓ Checking: BigQuery Datasets Exist
  ℹ️  ✓ nba_raw exists
  ℹ️  ✓ nba_analytics exists
  ℹ️  ✓ nba_precompute exists
  ℹ️  ✓ nba_reference exists
  ✅ PASS: All required BigQuery datasets exist

...

✓ Checking: Test Phase 3 Backfill Job (Dry-Run)
  ℹ️  Running dry-run for player_game_summary (this may take 10-20 seconds)...
  ✅ PASS: Phase 3 dry-run successful

✓ Checking: Test Phase 4 Backfill Job (Dry-Run)
  ℹ️  Running dry-run for player_shot_zone_analysis (this may take 10-20 seconds)...
  ✅ PASS: Phase 4 dry-run successful

========================================
PRE-FLIGHT VERIFICATION SUMMARY
========================================
Passed:   14
Failed:   0
Warnings: 0

🎉 ALL CHECKS PASSED - READY FOR BACKFILL
```

---

## Integration with Backfill Workflow

### Stage 0: Pre-Flight (BEFORE starting backfill)

**Recommended:** Run full check before starting backfill
```bash
./bin/backfill/preflight_verification.sh
```

If all checks pass → Proceed to Stage 1 (Phase 3 backfill)

If any checks fail → Fix issues before proceeding

### Quick Health Checks

During backfill planning or troubleshooting:
```bash
# Fast check (30s)
./bin/backfill/preflight_verification.sh --quick

# Check exit code programmatically
if ./bin/backfill/preflight_verification.sh --quick; then
    echo "Ready to go!"
else
    echo "Issues found, check output above"
fi
```

---

## Technical Implementation Notes

### Issue #1: PYTHONPATH for Dry-Run Tests

**Problem:** Backfill jobs need PYTHONPATH set to import data_processors
**Solution:** Added `PYTHONPATH="$(pwd)"` before python3 commands
```bash
PYTHONPATH="$(pwd)" timeout 30 python3 "$test_job" --dry-run --dates 2023-11-15
```
**Impact:** Both Phase 3 and Phase 4 dry-runs now work correctly

### Issue #2: set -e vs Comprehensive Checking

**Problem:** `set -e` exits on first error, preventing later checks
**Solution:** Disabled `set -e`, track failures with counters, exit based on summary
```bash
# set -e  # Disabled: We want to see all check results
```
**Impact:** All checks run even if some fail, better visibility

### Design Decisions

**Why 14 checks?**
- Cover all critical infrastructure (datasets, topics, services)
- Verify current data state for baseline
- Validate backfill jobs exist and work
- Test actual execution with dry-runs

**Why --quick mode?**
- Dry-runs take ~40 seconds (20s each × 2)
- Quick mode useful for rapid iteration
- Full mode for final verification before backfill

**Why specific test date (2023-11-15)?**
- Mid-season date (not bootstrap period)
- Should have all Phase 2 dependencies
- Recent enough to be representative
- Not current date (avoids special cases)

---

## What This Validates

### Critical for Backfill Success

✅ **Infrastructure exists:**
- Cloud Run services deployed and reachable
- Pub/Sub topics configured
- BigQuery datasets created

✅ **Data foundation ready:**
- Phase 2 has 100% coverage (675 dates)
- Starting state documented

✅ **Jobs functional:**
- All 10 backfill scripts exist
- Dry-runs execute successfully
- No import errors or configuration issues

✅ **Enhancements implemented:**
- BettingPros fallback (40% → 99.7% coverage)
- Backfill monitor available

### What It Doesn't Validate

⚠️ **Not checked (but documented elsewhere):**
- Orchestrator Pub/Sub subscriptions (assumed from service deployment)
- Firestore collections (assumed from orchestrator deployment)
- Actual data quality in Phase 2 (checked: count only)
- Schema compatibility (assumed from production deployment)
- GCS bucket permissions (only needed for Phase 1/2)

These are assumed working from successful v1.0 deployment.

---

## Troubleshooting

### "Phase 2 incomplete" Warning

**If Phase 2 shows <100%:**
```bash
# Check which dates are missing
bq query --use_legacy_sql=false "
SELECT game_date
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_status = 3
  AND game_date BETWEEN '2021-10-01' AND '2024-11-29'
  AND game_date NOT IN (
    SELECT DISTINCT game_date
    FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
  )
ORDER BY game_date
"
```

### "Dry-run failed" Error

**If Phase 3 or Phase 4 dry-run fails:**
```bash
# Run manually to see full error
PYTHONPATH=$(pwd) python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --dry-run --dates 2023-11-15

# Check for:
# - Import errors (missing dependencies)
# - BigQuery access issues (permissions)
# - Invalid date (no data for that date)
```

### "BettingPros fallback not implemented" Warning

**This is non-critical but reduces coverage:**
- With fallback: 99.7% historical coverage
- Without fallback: 40% historical coverage

Fix by implementing task in:
`docs/09-handoff/2025-11-30-BETTINGPROS-FALLBACK-FIX-TASK.md`

---

## Success Criteria

### ✅ All Met

1. **Script runs without errors**
   - Tested in both --quick and full modes
   - All BigQuery queries execute successfully
   - All gcloud commands work

2. **All 14 checks pass**
   - Infrastructure: 5/5 ✅
   - Data State: 3/3 ✅
   - Backfill Jobs: 4/4 ✅
   - Functional Tests: 2/2 ✅

3. **Provides actionable information**
   - Clear pass/fail/warn status
   - Helpful error messages
   - Manual commands provided for failed checks

4. **Integrated with workflow**
   - Documented in runbook as Stage 0
   - Exit codes usable in scripts
   - Quick mode for iteration

5. **Production ready**
   - Tested on actual infrastructure
   - No false positives
   - Catches real issues

---

## Next Steps

### Before Backfill Execution

1. ✅ Run pre-flight verification (this script)
2. Review output, ensure all checks pass
3. If failures: Fix issues, re-run verification
4. Document starting state (script captures automatically)

### During Backfill

Pre-flight verification is Stage 0 (pre-execution).
After verification passes, proceed to:
- **Stage 1:** Phase 3 backfill (use monitor + execution log)
- **Stage 2:** Phase 4 backfill (use monitor + execution log)
- **Stage 3:** Final validation

### Future Enhancements (Optional)

- Add --json output mode for programmatic use
- Check Firestore collections explicitly
- Validate orchestrator subscriptions
- Test Pub/Sub publishing
- Save results to file with timestamp
- Compare against previous run

---

## Files Created

1. **bin/backfill/preflight_verification.sh** (450 lines)
   - Main verification script
   - Executable bash script
   - Colored output
   - Exit code handling

2. **docs/09-handoff/2025-11-30-PREFLIGHT-VERIFICATION-COMPLETE.md** (this file)
   - Implementation summary
   - Usage guide
   - Test results
   - Troubleshooting

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| BACKFILL-RUNBOOK.md | Overall execution guide (Stage 0 references this) |
| BACKFILL-PRE-EXECUTION-HANDOFF.md | Original pre-execution checklist |
| BACKFILL-MONITOR-COMPLETE.md | Progress monitoring tool |
| BACKFILL-PLANNING-SESSION-COMPLETE.md | Full backfill planning context |

---

## Lessons Learned

1. **Dry-runs need PYTHONPATH** - Backfill jobs require project root in PYTHONPATH
2. **Don't use set -e for checks** - Want to see all failures, not exit early
3. **Color-coded output is valuable** - Makes pass/fail obvious at a glance
4. **Exit codes matter** - Enables scripting and automation
5. **Quick mode is essential** - 30s vs 60s makes big difference for iteration
6. **Specific test dates matter** - Mid-season dates more reliable than edge cases
7. **Helpful failure messages are key** - Include manual commands to reproduce

---

**Status:** ✅ COMPLETE - Ready for use before backfill execution
**Created:** 2025-11-30
**Session:** Backfill preparation (3rd deliverable)
**Outcome:** Automated pre-flight verification catches issues before 10+ hour backfill starts

---

## Quick Reference

```bash
# Before starting backfill (Stage 0)
./bin/backfill/preflight_verification.sh

# Expected output
🎉 ALL CHECKS PASSED - READY FOR BACKFILL

# If all checks pass
→ Proceed to Stage 1: Phase 3 backfill

# If any checks fail
→ Fix issues and re-run
→ Do NOT start backfill until all pass
```
