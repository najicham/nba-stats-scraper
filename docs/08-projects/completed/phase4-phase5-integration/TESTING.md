# Phase 4→5 Integration - Testing Guide

**For complete test plan, see full spec Section 15.6 "Testing Checklist"**

This document provides test procedures.

---

## Pre-Deployment Testing

### Unit Tests

**Coordinator helpers:**
```bash
pytest tests/predictions/test_coordinator.py::test_validate_phase4_ready -v
pytest tests/predictions/test_coordinator.py::test_get_batch_status -v
pytest tests/predictions/test_coordinator.py::test_wait_for_phase4 -v
```

**Phase 4 publishing:**
```bash
pytest tests/precompute/test_ml_feature_store.py::test_publish_completion -v
```

---

## Integration Tests

### Test 1: Pub/Sub End-to-End

**Manually publish Phase 4 completion event:**
```bash
gcloud pubsub topics publish nba-phase4-precompute-complete \
    --message='{
        "event_type": "phase4_complete",
        "game_date": "2025-11-28",
        "players_ready": 100,
        "players_total": 450
    }'
```

**Verify:**
- Coordinator logs show `/trigger` endpoint called
- Predictions generated for test date
- No errors in logs

---

### Test 2: Scheduler Backup Path

**Manually trigger scheduler:**
```bash
curl -X POST "https://phase5-coordinator-HASH.run.app/start" \
    -H "X-CloudScheduler: true" \
    -d '{"game_date": "2025-11-28"}'
```

**Verify:**
- Coordinator validates Phase 4 first
- If data ready → processes
- If not ready → waits up to 30 minutes
- Logs show correct path taken

---

### Test 3: Deduplication

**Run coordinator twice for same date:**
```bash
# First run
curl -X POST "https://phase5-coordinator-HASH.run.app/start" \
    -d '{"game_date": "2025-11-28"}'

# Second run (should detect completion)
curl -X POST "https://phase5-coordinator-HASH.run.app/start" \
    -d '{"game_date": "2025-11-28"}'
```

**Verify:**
- Second run returns 200 "already_complete"
- No duplicate predictions created
- Logs show deduplication check passed

---

### Test 4: Partial Completion Retry

**Simulate partial batch:**
1. Clear 10 players from predictions table
2. Trigger `/retry` endpoint

```bash
curl -X POST "https://phase5-coordinator-HASH.run.app/retry" \
    -d '{"game_date": "2025-11-28"}'
```

**Verify:**
- Only missing 10 players processed
- Already-complete players skipped
- Total predictions = 450 after retry

---

## Staging Validation (3-5 Days)

### Day 1-3: Automated Monitoring
- [ ] Staging runs nightly with production data copy
- [ ] Check logs each morning (15 minutes)
- [ ] Verify predictions generated
- [ ] Check for any errors or warnings

### Day 4-5: Extended Validation
- [ ] Review latency trends
- [ ] Verify alert delivery (Email + Slack)
- [ ] Test manual intervention procedures
- [ ] Document any issues found

---

## Production Smoke Tests (Day 1)

**After production deployment:**

```bash
# 1. Health check
curl https://phase5-coordinator-HASH.run.app/health

# 2. Status check
curl https://phase5-coordinator-HASH.run.app/status

# 3. Verify Pub/Sub subscription
gcloud pubsub subscriptions describe nba-phase5-trigger-sub

# 4. Verify Cloud Scheduler jobs
gcloud scheduler jobs list --location=us-west2 | grep phase5
```

---

## Success Criteria

- [ ] All unit tests passing (100% coverage on new code)
- [ ] Pub/Sub trigger test successful
- [ ] Scheduler backup test successful
- [ ] Deduplication test successful
- [ ] Retry test successful
- [ ] 3+ successful staging runs
- [ ] Zero critical errors in staging
- [ ] Alerts delivered correctly
- [ ] Rollback procedure tested

---

**For complete test cases, see full spec Section 15.6.**
