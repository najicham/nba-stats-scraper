# Monitoring Improvements Project

**Started:** 2026-01-14 (Session 38-40)
**Status**: Active
**Priority:** High

---

## Overview

Enhance system monitoring and observability to prevent silent failures and reduce incident response time. This project consolidates monitoring improvements across Sessions 38-40.

---

## Problem Statement

1. **Auth failures went undetected** - OIDC misconfigurations caused widespread 401/403 errors
2. **Stuck processors accumulate** - No automated cleanup, manual intervention required
3. **West coast games missed** - UTC-based date logic caused data gaps
4. **No proactive alerting** - Issues discovered reactively via manual checks

---

## Completed Work

### Session 38: OIDC Auth Fixes
- Fixed 5 Pub/Sub subscriptions with missing OIDC
- Fixed 6 scheduler jobs with paths in audiences
- Created `setup_auth_error_alert.sh` for monitoring setup

### Session 39: Monitoring Tools
- Added OIDC validation to `system_health_check.py`
- Created `cleanup_stuck_processors.py` script
- Created log-based metric `cloud_run_auth_errors`
- Created `bdl-boxscores-yesterday-catchup` scheduler job

### Session 40: Follow-up & Bug Fix
- Fixed west coast date logic in `bdl_box_scores.py` (committed)
- Added `get_yesterday_eastern()` and `get_today_eastern()` utilities
- Cleaned 25 stuck processors
- Verified Phase 3 `/process-date-range` endpoint works
- Documented remaining work

---

## Remaining Work

See [TODO.md](./TODO.md) for detailed task list.

### High Priority
- [ ] Cloud Monitoring alert policy setup (manual)

### Medium Priority
- [ ] MLB scrapers date logic fix (5 files)
- [ ] Phase 3 404 investigation

### Nice to Have
- [ ] Proactive success rate alerts
- [ ] Automated DLQ monitoring alerts

---

## Key Files

| File | Description |
|------|-------------|
| `scripts/system_health_check.py` | Daily health check with OIDC validation |
| `scripts/cleanup_stuck_processors.py` | Stuck processor cleanup utility |
| `scripts/setup_auth_error_alert.sh` | Auth error monitoring setup |
| `scrapers/utils/date_utils.py` | Timezone-aware date utilities |

---

## Related Handoffs

- [Session 38: OIDC Auth Fixes](../../09-handoff/2026-01-14-SESSION-38-OIDC-AUTH-FIXES.md)
- [Session 39: Monitoring Improvements](../../09-handoff/2026-01-14-SESSION-39-MONITORING-IMPROVEMENTS.md)
- [Session 40: Monitoring Follow-up](../../09-handoff/2026-01-14-SESSION-40-MONITORING-FOLLOWUP.md)
