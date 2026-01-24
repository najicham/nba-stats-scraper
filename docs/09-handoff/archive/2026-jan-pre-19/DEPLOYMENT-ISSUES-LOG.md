# Deployment Issues Log
**Date**: 2026-01-20
**Session**: Evening Continuation

---

## ❌ **self-heal-predictions Deployment Failure**

### Issue
Cloud Function deployment consistently fails with:
```
Container Healthcheck failed. The user-provided container failed to start
and listen on the port defined provided by the PORT=8080 environment variable
```

### Attempted Fixes
1. ✅ Fixed import order (moved logger initialization before retry imports)
2. ✅ Inlined retry logic to avoid shared directory dependency
3. ❌ Still failing - suggests deeper runtime issue

### Current Status
- **Code**: Committed to branch with inline retry logic
- **Deployment**: FAILED (revision: self-heal-predictions-00008-but)
- **Logs URL**: Check Cloud Console for detailed error logs

### Next Steps (For Future Session)
1. Check Cloud Run logs for detailed error:
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=self-heal-predictions" --limit=50
   ```

2. Possible issues to investigate:
   - Syntax error in retry decorator
   - Missing dependency in requirements.txt
   - Runtime error during function initialization
   - Healthcheck timeout too short

3. Alternative approach:
   - Test retry logic locally first
   - Deploy without retry logic to verify basic deployment works
   - Add retry logic incrementally

### Workaround
- Self-heal code with retry logic is committed but not deployed
- Current self-heal function (without retry) is still active
- Not critical since main ROOT CAUSE fix (Pub/Sub ACK) is deployed

---

## ✅ **Successful Deployments**

### Scheduler Timeouts Fixed
- ✅ same-day-phase4-tomorrow: 180s → 600s
- ✅ same-day-predictions-tomorrow: 320s → 600s

**Impact**: Prevents timeout failures (same issue that caused 5-day PDC failure)

### Pub/Sub ACK Verification Deployed
- ✅ phase3-to-phase4-orchestrator (revision 00007)
- ✅ phase4-to-phase5-orchestrator (revision updated)

**Impact**: ROOT CAUSE fix - eliminates silent multi-day failures

---

## 📊 **Current Production Status**

### ACTIVE and WORKING ✅
1. BDL Scraper with retry logic
2. Phase 3→4 validation gate with ACK fix
3. Phase 4→5 circuit breaker with ACK fix
4. Scheduler jobs with corrected timeouts

### BLOCKED ❌
1. self-heal-predictions deployment (code ready, deployment failing)

### PENDING 🟡
1. Dashboard deployment (API compatibility issue)
2. Slack retry application (decorator ready, not applied)
3. Circuit breaker testing (not started)

---

**Last Updated**: 2026-01-20 21:30 UTC
**Branch**: week-0-security-fixes
**Next Action**: Investigate self-heal logs, proceed with other tasks
