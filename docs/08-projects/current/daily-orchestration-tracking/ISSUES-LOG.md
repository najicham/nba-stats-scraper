# Daily Orchestration Issues Log

Track issues found during daily orchestration checks. Add new entries at the top.

---

## Issue Template

```markdown
### [DATE] - Brief Title

**Found by:** Session N
**Severity:** P0/P1/P2/P3
**Status:** Open / Investigating / Fixed / Won't Fix

**Symptoms:**
- What you observed

**Root Cause:**
- Why it happened (if known)

**Resolution:**
- How it was fixed (if fixed)

**Prevention:**
- What we did to prevent recurrence

**Related:** Link to project doc if created
```

---

## Issues

### 2026-01-13 - Massive False Positive Crisis: 93% of Zero-Record Alerts Invalid

**Found by:** Session 32-33
**Severity:** P0 (Critical - Monitoring Unreliable)
**Status:** Fixed in code (commit d22c4d8), pending deployment in Session 34

**Symptoms:**
- 2,346 "zero-record" runs reported in processor_run_history (Oct-Jan)
- Monitoring showing constant data loss alerts
- Operators investigating alerts finding data exists in BigQuery
- Trust in monitoring system destroyed ("boy who cried wolf")
- Real data loss potentially masked by false positives

**Root Cause:**
- 24 processors with custom `save_data()` methods not setting `self.stats['rows_inserted']`
- ProcessorBase.run() relies on this stat being set for tracking
- When not set, defaults to 0 in run_history even when data successfully loaded
- Systematic violation of ProcessorBase documentation requirements

**Resolution:**
- **Session 32:** Discovered bug in BdlBoxscoresProcessor, validated fix (140 records instead of 0)
- **Session 33:**
  - Fixed all 24 affected processors across 8 data sources
  - Added tracking to ALL code paths (success, error, empty, skip)
  - Cross-validated 57 dates: 53 have data (93% false positive rate)
  - Projected: 2,180 of 2,346 runs are false positives
  - Real data loss: Only ~166 dates (7%)

**Prevention:**
- Explicit tracking in all save_data() methods
- Cross-validation before bulk reprocessing
- Monitor zero-record runs with new script: `scripts/monitor_zero_record_runs.py`
- Need enforcement: runtime checks, linting rules, code review checklist

**Impact Assessment:**
- Before: 93% false positive rate → monitoring unreliable
- After: Expected <1% false positive rate → monitoring trustworthy
- Avoided: 40+ hours of unnecessary reprocessing (2,180 dates)
- Enabled: Targeted recovery of 166 real data loss dates

**Related:**
- Session 32 handoff: `docs/09-handoff/2026-01-14-SESSION-32-COMPREHENSIVE-HANDOFF.md`
- Session 33 handoff: `docs/09-handoff/2026-01-14-SESSION-33-COMPLETE-HANDOFF.md`
- Processor audit: `docs/08-projects/current/historical-backfill-audit/PROCESSOR-TRACKING-BUG-AUDIT.md`
- Data loss inventory: `docs/08-projects/current/historical-backfill-audit/DATA-LOSS-INVENTORY-2026-01-14.md`
- Session 34 plan: `docs/08-projects/current/daily-orchestration-tracking/SESSION-34-PLAN.md`

---

### 2026-01-12 - BettingPros Player Props Failing All Day

**Found by:** Session 27
**Severity:** P1
**Status:** Fixed (pending deployment)

**Symptoms:**
- All 3 scheduled betting_lines runs failed (1 PM, 4 PM, 7 PM ET)
- Error: "No events found for date: 2026-01-12"
- No player props in BigQuery for Jan 12

**Root Cause:**
- Proxy timeouts (502 Bad Gateway, read timeout)
- 20-second HTTP timeout too short for slow proxy
- No retry logic around internal events fetch

**Resolution:**
- Manually triggered all 6 market types to recover data
- Implemented 4-layer fix: timeout increase, retry logic, recovery script, monitoring

**Prevention:**
- Increased timeout to 45s
- Added 3-retry with exponential backoff (15s, 30s, 60s)
- Created `scripts/betting_props_recovery.py` for auto-recovery
- Added BettingPros check to `scripts/check_data_completeness.py`

**Related:** `docs/08-projects/current/bettingpros-reliability/`

---

### 2026-01-09 - ESPN Roster Scraper Only Got 2 Teams

**Found by:** Session 26
**Severity:** P1
**Status:** Fixed (revision 00100)

**Symptoms:**
- ESPN rosters only scraped 2-3 teams instead of 30
- Blocking prediction pipeline

**Root Cause:**
- Completeness threshold too low (25/30 = 83%)
- No adaptive rate limiting for 429 responses

**Resolution:**
- Raised threshold to 29/30 (97%)
- Added 429 detection with adaptive delay
- Added batch processor validation

**Related:** Session 26 handoff

---

*Add new issues above this line*
