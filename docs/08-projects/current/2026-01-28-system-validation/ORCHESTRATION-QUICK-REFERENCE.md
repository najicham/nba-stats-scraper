# Orchestration Resilience - Quick Reference

**Date**: 2026-01-28
**Session**: Session 8 - Workstream 2

## What We Fixed

| Problem | Solution | Status |
|---------|----------|--------|
| Firestore writes had no retry | Added `@retry_with_jitter` decorator | ✅ Fixed |
| Return values ignored | Added validation in all 3 orchestrators | ✅ Fixed |
| No error alerting | Added Slack alerts on exceptions | ✅ Fixed |
| BigQuery MERGE had no retry | Added `@retry_with_jitter` decorator | ✅ Fixed |
| No Cloud Function drift detection | Created script + GitHub workflow | ✅ Fixed |
| Circuit breaker too slow | Reduced from 60s to 30s | ✅ Fixed |

## Files Changed

### Core Utilities
- `shared/utils/completion_tracker.py` - Added retry logic, faster circuit breaker

### Orchestrators
- `orchestration/cloud_functions/phase2_to_phase3/main.py` - Return checking + Slack alerts
- `orchestration/cloud_functions/phase3_to_phase4/main.py` - Return checking + Slack alerts
- `orchestration/cloud_functions/phase4_to_phase5/main.py` - Return checking + Slack alerts

### Automation
- `bin/check-cloud-function-drift.sh` - NEW: Detect stale Cloud Functions
- `.github/workflows/check-cloud-function-drift.yml` - NEW: Daily drift check

## Key Improvements

### 1. Retry Logic
```python
# Before: Failed immediately on transient errors
firestore_client.collection(...).set(...)

# After: Retries 3 times with exponential backoff
@retry_with_jitter(max_attempts=3, base_delay=1.0, max_delay=10.0)
def _write_to_firestore(...):
    firestore_client.collection(...).set(...)
```

### 2. Return Value Checking
```python
# Before: Silent failure
tracker.record_completion(...)

# After: Visibility into failures
fs_ok, bq_ok = tracker.record_completion(...)
if not fs_ok and not bq_ok:
    logger.error("CRITICAL: Both Firestore and BigQuery writes failed")
```

### 3. Error Alerting
```python
# Before: Just logged
except Exception as e:
    logger.error(f"Error: {e}")

# After: Slack alert sent
except Exception as e:
    logger.error(f"Error: {e}")
    send_orchestration_error_alert(function_name, error=e, game_date, correlation_id)
```

## Usage

### Check Cloud Function Drift
```bash
# Basic check
./bin/check-cloud-function-drift.sh

# Verbose with commit history
./bin/check-cloud-function-drift.sh --verbose
```

### Check Cloud Run Drift
```bash
# Existing script for Cloud Run services
./bin/check-deployment-drift.sh --verbose
```

### View Slack Alerts
- Channel: `#app-error-alerts`
- Alerts include: function name, error type, stack trace, correlation ID

### Monitor Dual-Write Health
```bash
# Check recent logs for warnings
gcloud logging read 'resource.type="cloud_function" AND
  (jsonPayload.message=~"CRITICAL.*writes failed" OR
   jsonPayload.message=~"BigQuery backup write failed")' \
  --limit=20 --format=json
```

## Testing

### Test Firestore Retry
1. Temporarily block Firestore in Cloud Function
2. Trigger orchestrator
3. Should see 3 retry attempts in logs
4. Should fall back to BigQuery

### Test Return Value Checking
1. Check logs after orchestrator runs
2. Look for: "Firestore write failed" or "BigQuery backup write failed"
3. Should see appropriate WARNING or CRITICAL logs

### Test Slack Alerting
1. Force an exception in orchestrator (e.g., invalid game_date)
2. Check #app-error-alerts channel
3. Should see alert with full context

### Test Drift Detection
1. Make code change to a Cloud Function
2. Wait 25+ hours (or modify script for testing)
3. Run `./bin/check-cloud-function-drift.sh`
4. Should flag as STALE DEPLOYMENT

## Monitoring Checklist

### Daily
- [ ] Check #app-error-alerts for orchestration errors
- [ ] Review GitHub issues labeled `cloud-function-drift`
- [ ] Run `/validate-daily` skill

### Weekly
- [ ] Check deployment drift for both Cloud Functions and Cloud Run
- [ ] Review dual-write failure rate (search logs for "backup write failed")
- [ ] Verify all orchestrators have health endpoints returning 200

### Monthly
- [ ] Audit Cloud Function deployments (ensure none >7 days behind)
- [ ] Review Firestore circuit breaker trip rate
- [ ] Verify Slack webhook is working (test alerts)

## Rollback Plan

If issues arise:

### Revert Retry Logic
```bash
git revert <commit_hash>  # Revert completion_tracker.py changes
```

### Disable Slack Alerts
Comment out in orchestrators:
```python
# send_orchestration_error_alert(...)  # Temporarily disabled
```

### Disable Drift Detection
```yaml
# .github/workflows/check-cloud-function-drift.yml
on:
  # schedule:  # Commented out
  workflow_dispatch:  # Keep manual trigger
```

## Success Metrics

### Before Improvements
- Firestore retry: 0 attempts
- Return value checking: 0%
- Error alerts: 0 (logs only)
- Drift detection: Manual only
- Circuit breaker interval: 60s

### After Improvements
- Firestore retry: 3 attempts with exponential backoff
- Return value checking: 100% (all 3 orchestrators)
- Error alerts: Active Slack notifications
- Drift detection: Automated daily
- Circuit breaker interval: 30s

## Related Documentation

- Full details: `ORCHESTRATION-RESILIENCE-IMPROVEMENTS.md`
- Handoff doc: `docs/09-handoff/2026-01-28-SESSION-8-WORKSTREAM-2-ORCHESTRATION.md`
- Retry utility: `shared/utils/retry_with_jitter.py`
- Health endpoints: `shared/endpoints/health.py`
