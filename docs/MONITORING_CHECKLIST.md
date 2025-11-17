# Service Rename Monitoring Checklist

**Task:** Monitor new phase-based services after deployment
**Start:** 2025-11-16 22:40 UTC
**Complete by:** 2025-11-17 22:40 UTC (24 hours)

---

## Monitoring Schedule

### Every 4-6 Hours (6 total checks)

- [ ] **Check 1:** 2025-11-16 ~23:00 UTC (Tonight before bed)
- [ ] **Check 2:** 2025-11-17 ~08:00 UTC (Morning)
- [ ] **Check 3:** 2025-11-17 ~13:00 UTC (Afternoon)
- [ ] **Check 4:** 2025-11-17 ~18:00 UTC (Evening)
- [ ] **Check 5:** 2025-11-17 ~22:00 UTC (Before cleanup)
- [ ] **Check 6:** 2025-11-18 ~08:00 UTC (Post-cleanup verification)

---

## Quick Health Check Commands

Copy/paste these commands for each check:

```bash
# 1. Check Phase 2 logs (last 20 lines)
gcloud run services logs read nba-phase2-raw-processors --region=us-west2 --limit=20

# 2. Check Phase 3 logs (last 20 lines)
gcloud run services logs read nba-phase3-analytics-processors --region=us-west2 --limit=20

# 3. Check for errors across all services
gcloud logging read 'resource.type="cloud_run_revision" severity>=ERROR' --limit=50 --format=json

# 4. Verify DLQs are empty (should output nothing or "0")
gcloud pubsub subscriptions describe nba-phase1-scrapers-complete-dlq-sub --format="value(numUndeliveredMessages)"
gcloud pubsub subscriptions describe nba-phase2-raw-complete-dlq-sub --format="value(numUndeliveredMessages)"
```

---

## What You're Looking For

### ✅ Good Signs

- HTTP 200 responses in logs
- "Processing complete" or similar success messages
- DLQ message counts = 0 or empty
- Services responding quickly (<5s)
- No crash loops or restart messages

### ⚠️ Warning Signs (Investigate)

- HTTP 4xx or 5xx errors
- Missing expected logs
- DLQ message count > 0
- Slow response times (>30s)
- Services restarting frequently

### 🚨 Critical Issues (Act Immediately)

- Continuous errors in logs
- DLQ filling up (>10 messages)
- Services not responding
- Data not flowing through pipeline
- **Action:** See rollback procedure in `docs/HANDOFF-2025-11-16-phase-rename-complete.md`

---

## Cleanup Steps (After 24h)

**Run after Check 5 (2025-11-17 22:00+ UTC):**

```bash
# Run automated cleanup script
./bin/infrastructure/cleanup_old_resources.sh
```

**Script will delete:**
- `nba-scrapers` (old Phase 1)
- `nba-processors` (old Phase 2)
- `nba-analytics-processors` (old Phase 3)

---

## Post-Cleanup Verification (Check 6)

**Run after cleanup completes:**

```bash
# Send test message
gcloud pubsub topics publish nba-phase1-scrapers-complete \
  --message='{"name":"post_cleanup_test","execution_id":"test-'$(date +%s)'","status":"success","gcs_path":"gs://test/cleanup-verification.json","record_count":1}'

# Wait 5 seconds
sleep 5

# Verify Phase 2 received it
gcloud run services logs read nba-phase2-raw-processors --region=us-west2 --limit=10 | grep post_cleanup_test
```

**Expected:** Should see "post_cleanup_test" in Phase 2 logs

---

## Completion

- [ ] All 6 checks completed without critical issues
- [ ] Old services cleaned up
- [ ] Post-cleanup test passed
- [ ] Delete this checklist or update status in handoff doc

---

**Full Details:** See `docs/HANDOFF-2025-11-16-phase-rename-complete.md`
**Rollback Procedure:** See `docs/HANDOFF-2025-11-16-phase-rename-complete.md` Section: Rollback Plan
