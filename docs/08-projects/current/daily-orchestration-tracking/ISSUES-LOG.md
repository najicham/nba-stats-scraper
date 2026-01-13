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
