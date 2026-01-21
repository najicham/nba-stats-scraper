# Week 1 Deployment Guide - Simplified

**Date**: 2026-01-21
**Status**: Ready for Immediate Deployment
**Risk Level**: LOW (all features feature-flagged)
**Branch**: `week-1-improvements`

---

## ⚠️ CRITICAL: ArrayUnion at 800/1000 Limit

The `completed_players` array in Firestore is at **800/1000 elements**.
System will **BREAK completely** when limit is reached (could happen on next busy game day with 450+ players).

**Action Required**: Deploy dual-write mode **TODAY**.

---

## 🚀 Quick Start (Deploy Everything Safely)

### Step 1: Deploy to Staging (30 minutes)

```bash
# 1. Checkout branch
cd /home/naji/code/nba-stats-scraper
git checkout week-1-improvements
git pull origin week-1-improvements

# 2. Verify you're on the right commit
git log --oneline -1
# Should show: 3dab838f docs: Add comprehensive Week 1 deployment handoff

# 3. Deploy to staging with ALL flags disabled (zero behavior change)
gcloud run deploy nba-orchestrator \
  --source . \
  --region us-west2 \
  --platform managed \
  --update-env-vars \
ENABLE_PHASE2_COMPLETION_DEADLINE=false,\
ENABLE_SUBCOLLECTION_COMPLETIONS=false,\
ENABLE_QUERY_CACHING=false,\
ENABLE_IDEMPOTENCY_KEYS=false,\
ENABLE_STRUCTURED_LOGGING=false

# 4. Verify health checks
curl https://nba-orchestrator-<STAGING-URL>.run.app/health
# Should return: {"status": "healthy", ...}

# 5. Monitor for 2-4 hours
gcloud logging read "resource.type=cloud_run_revision \
  severity>=ERROR \
  timestamp>\"$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')\"" \
  --limit 50
# Should show zero errors from new deployment
```

### Step 2: Deploy to Production (30 minutes)

```bash
# Same as staging, but use production service names
gcloud run deploy nba-orchestrator \
  --source . \
  --region us-west2 \
  --platform managed \
  --update-env-vars \
ENABLE_PHASE2_COMPLETION_DEADLINE=false,\
ENABLE_SUBCOLLECTION_COMPLETIONS=false,\
ENABLE_QUERY_CACHING=false,\
ENABLE_IDEMPOTENCY_KEYS=false,\
ENABLE_STRUCTURED_LOGGING=false

# Also deploy prediction services (coordinator, worker, phase processors)
gcloud run deploy prediction-coordinator --source=predictions/coordinator --region=us-west2
gcloud run deploy prediction-worker --source=predictions/worker --region=us-west2
gcloud run deploy nba-phase2-raw-processors --source=data_processors/raw --region=us-west2
gcloud run deploy nba-phase3-analytics-processors --source=data_processors/analytics --region=us-west2
gcloud run deploy nba-phase4-precompute-processors --source=data_processors/precompute --region=us-west2
```

### Step 3: Enable ArrayUnion Dual-Write (CRITICAL - 5 minutes)

```bash
# Enable subcollection dual-write IMMEDIATELY
gcloud run services update prediction-coordinator \
  --region us-west2 \
  --update-env-vars \
ENABLE_SUBCOLLECTION_COMPLETIONS=true,\
DUAL_WRITE_MODE=true,\
USE_SUBCOLLECTION_READS=false

# Verify deployment
gcloud run services describe prediction-coordinator --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)"

# Should show:
# ENABLE_SUBCOLLECTION_COMPLETIONS=true
# DUAL_WRITE_MODE=true
# USE_SUBCOLLECTION_READS=false
```

### Step 4: Monitor Dual-Write (7 days)

```bash
# Check for consistency issues (run daily)
gcloud logging read "resource.type=cloud_run_revision \
  severity=WARNING \
  'CONSISTENCY MISMATCH'" \
  --limit 50 \
  --format json

# Expected: ZERO mismatches
# If mismatches found, investigate immediately

# Check subcollection writes are happening
gcloud firestore databases export gs://YOUR_BUCKET/firestore-export \
  --collection-ids=prediction_batches

# Verify structure:
# prediction_batches/{batch_id}/completions/{player_id}
```

### Step 5: Switch Reads to Subcollection (Day 8)

```bash
# After 7 days of successful dual-write with zero mismatches
gcloud run services update prediction-coordinator \
  --region us-west2 \
  --update-env-vars \
USE_SUBCOLLECTION_READS=true

# Monitor for 24 hours
# Check batch completions still working
# Check for errors
```

### Step 6: Stop Dual-Write (Day 15)

```bash
# After 7 more days of successful subcollection reads
gcloud run services update prediction-coordinator \
  --region us-west2 \
  --update-env-vars \
DUAL_WRITE_MODE=false

# Migration complete!
# System now scales to unlimited players
```

---

## 📋 Other Week 1 Features (Enable After Dual-Write Stable)

### BigQuery Query Caching (Day 3-4) - $60-90/month savings

```bash
gcloud run services update nba-orchestrator \
  --region us-west2 \
  --update-env-vars \
ENABLE_QUERY_CACHING=true,\
QUERY_CACHE_TTL_SECONDS=3600

# Monitor cache hit rates
gcloud logging read "resource.type=cloud_run_revision \
  'BigQuery cache HIT'" \
  --limit 50

# Expected: 50%+ cache hit rate after 24-hour warmup

# Validate cost savings after 48 hours
# https://console.cloud.google.com/bigquery/analytics
```

### Idempotency Keys (Day 5-6)

```bash
gcloud run services update prediction-coordinator \
  --region us-west2 \
  --update-env-vars \
ENABLE_IDEMPOTENCY_KEYS=true,\
DEDUP_TTL_DAYS=7

# Monitor deduplication
gcloud logging read "resource.type=cloud_run_revision \
  'Duplicate message detected'" \
  --limit 50

# Verify deduplication collection exists
gcloud firestore collections list | grep pubsub_deduplication
```

### Phase 2 Completion Deadline (Day 7-8)

```bash
gcloud run services update phase2-to-phase3 \
  --region us-west2 \
  --update-env-vars \
ENABLE_PHASE2_COMPLETION_DEADLINE=true,\
PHASE2_COMPLETION_TIMEOUT_MINUTES=30

# Monitor for deadline alerts
gcloud logging read "resource.type=cloud_run_revision \
  'DEADLINE EXCEEDED'" \
  --limit 50

# Should be rare - only when processors genuinely slow/failed
```

### Structured Logging (Day 9-10)

```bash
gcloud run services update nba-orchestrator \
  --region us-west2 \
  --update-env-vars \
ENABLE_STRUCTURED_LOGGING=true

# Test Cloud Logging queries
# Example: jsonPayload.batch_id="batch_2026-01-21_123"
# Example: jsonPayload.workflow_name="morning_operations"
# Example: jsonPayload.correlation_id="abc-123"
```

---

## 🔍 Monitoring & Validation

### Daily Checks (run for 14 days)

```bash
# 1. Error rates (should be zero from Week 1 changes)
gcloud logging read "resource.type=cloud_run_revision \
  severity>=ERROR \
  timestamp>\"$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')\"" \
  --limit 50

# 2. Batch completion rates
gcloud logging read "resource.type=cloud_run_revision \
  'Batch complete'" \
  --limit 20

# 3. Health check status
curl https://nba-orchestrator-XXX.run.app/health/metrics

# 4. Subcollection consistency (during dual-write phase)
gcloud logging read "resource.type=cloud_run_revision \
  'CONSISTENCY MISMATCH'" \
  --limit 50
# Expected: ZERO
```

### Success Criteria (After 2 weeks)

- ✅ Reliability: 99.5%+ (up from 80-85%)
- ✅ Cost: $730/month (down from $800)
- ✅ Player limit: Unlimited (was 800/1000)
- ✅ Idempotency: 100% (no duplicates)
- ✅ Incidents: 0 from Week 1 changes

---

## 🚨 Emergency Rollback Procedures

### Quick Rollback (< 2 minutes)

```bash
# Disable ALL Week 1 features immediately
gcloud run services update nba-orchestrator \
  --region us-west2 \
  --update-env-vars \
ENABLE_PHASE2_COMPLETION_DEADLINE=false,\
ENABLE_QUERY_CACHING=false,\
ENABLE_STRUCTURED_LOGGING=false

gcloud run services update prediction-coordinator \
  --region us-west2 \
  --update-env-vars \
ENABLE_SUBCOLLECTION_COMPLETIONS=false,\
ENABLE_IDEMPOTENCY_KEYS=false

gcloud run services update phase2-to-phase3 \
  --region us-west2 \
  --update-env-vars \
ENABLE_PHASE2_COMPLETION_DEADLINE=false
```

### Selective Rollback

**Disable subcollection reads (keep dual-write):**
```bash
gcloud run services update prediction-coordinator \
  --region us-west2 \
  --update-env-vars \
USE_SUBCOLLECTION_READS=false
```

**Disable subcollection completely:**
```bash
gcloud run services update prediction-coordinator \
  --region us-west2 \
  --update-env-vars \
ENABLE_SUBCOLLECTION_COMPLETIONS=false
```

**Disable BigQuery caching:**
```bash
gcloud run services update nba-orchestrator \
  --region us-west2 \
  --update-env-vars \
ENABLE_QUERY_CACHING=false
```

---

## 📊 Deployment Timeline

| Day | Action | Duration | Risk |
|-----|--------|----------|------|
| 0 | Deploy to staging (flags disabled) | 30 min | None |
| 0 | Deploy to production (flags disabled) | 30 min | None |
| 0 | Enable ArrayUnion dual-write | 5 min | **CRITICAL** |
| 1-7 | Monitor dual-write consistency | Daily 10 min | Low |
| 3-4 | Enable BigQuery caching | 5 min | Low |
| 5-6 | Enable idempotency keys | 5 min | Low |
| 7-8 | Enable Phase 2 deadline | 5 min | Low |
| 8 | Switch reads to subcollection | 5 min | Medium |
| 9-10 | Enable structured logging | 5 min | Low |
| 15 | Stop dual-write (migration complete) | 5 min | Low |

**Total Active Time**: ~2 hours over 15 days
**Monitoring Time**: ~10-15 min/day for 15 days

---

## ✅ Pre-Deployment Checklist

- [ ] Verify on `week-1-improvements` branch
- [ ] Confirm commit `3dab838f` or later
- [ ] Review rollback procedures
- [ ] Backup current Firestore data
- [ ] Notify team of deployment window
- [ ] Clear calendar for monitoring (2-4 hours)

---

## 📞 Support & Resources

**Documentation**:
- Full handoff: `docs/09-handoff/2026-01-21-WEEK-1-DEPLOYMENT-HANDOFF.md`
- Week 1 completion: `docs/08-projects/current/week-1-improvements/WEEK-1-COMPLETE.md`
- Strategic plan: `docs/10-week-1/STRATEGIC-PLAN.md`

**Monitoring**:
- Cloud Console: https://console.cloud.google.com/run
- BigQuery Analytics: https://console.cloud.google.com/bigquery/analytics
- Firestore Console: https://console.cloud.google.com/firestore

**Key Files Modified** (for reference):
- `predictions/coordinator/batch_state_manager.py` (subcollection)
- `shared/utils/bigquery_utils.py` (caching)
- `predictions/coordinator/coordinator.py` (idempotency)
- `orchestration/cloud_functions/phase2_to_phase3/main.py` (deadline)
- `shared/config/timeout_config.py` (centralized config)
- `shared/utils/structured_logging.py` (logging)

---

**Created**: 2026-01-21
**Author**: Week 2 Analysis Session
**Status**: Ready for deployment - ArrayUnion dual-write is URGENT!
