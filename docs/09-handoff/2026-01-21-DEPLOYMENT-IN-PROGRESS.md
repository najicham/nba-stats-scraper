# Week 1 Deployment - In Progress

**Date**: 2026-01-21
**Status**: 🟡 **DEPLOYMENT IN PROGRESS**
**Priority**: 🚨 **CRITICAL** (ArrayUnion at 800/1000 limit)

---

## Deployment Overview

### Phase 1: Dark Deployment (IN PROGRESS)
**Status**: Building and deploying...
**Started**: 2026-01-21 17:15 PST
**Service**: `prediction-coordinator`
**Region**: `us-west2`

**Command Executed**:
```bash
gcloud run deploy prediction-coordinator \
  --source . \
  --region us-west2 \
  --platform managed \
  --timeout 300 \
  --set-env-vars="
    SERVICE=coordinator,
    ENVIRONMENT=production,
    GCP_PROJECT_ID=nba-props-platform,
    PREDICTION_REQUEST_TOPIC=prediction-request-prod,
    PREDICTION_READY_TOPIC=prediction-ready-prod,
    BATCH_SUMMARY_TOPIC=batch-summary-prod,
    ENABLE_SUBCOLLECTION_COMPLETIONS=false,
    ENABLE_IDEMPOTENCY_KEYS=false,
    ENABLE_PHASE2_COMPLETION_DEADLINE=false,
    ENABLE_QUERY_CACHING=false,
    ENABLE_STRUCTURED_LOGGING=false
  " \
  --no-allow-unauthenticated
```

**What This Does**:
- Deploys Week 1 code to production
- All feature flags DISABLED (zero behavior change)
- Creates new revision with updated code
- Safe dark deployment - no production impact

---

### Phase 2: Enable ArrayUnion Dual-Write (NEXT)
**Status**: ⏳ Pending (will execute after Phase 1 completes)

**Command to Execute**:
```bash
gcloud run services update prediction-coordinator \
  --region us-west2 \
  --update-env-vars \
ENABLE_SUBCOLLECTION_COMPLETIONS=true,\
DUAL_WRITE_MODE=true,\
USE_SUBCOLLECTION_READS=false
```

**What This Does**:
- Enables ArrayUnion → Subcollection dual-write
- Writes to BOTH old array AND new subcollection
- Reads from old array (safe)
- Validates consistency (10% sampling)

**Expected Impact**:
- Fixes 800/1000 ArrayUnion limit
- Enables unlimited player scalability
- Zero downtime
- Backward compatible

---

## Pre-Deployment Validation

### ✅ January 2026 Backfill Validated
- **Coverage**: 95% predictions, 90% analytics
- **Quality**: Gold/Silver tier
- **Status**: APPROVED (Grade: A-)
- **Report**: `docs/09-handoff/2026-01-21-JANUARY-VALIDATION-FINDINGS.md`

### ✅ Code Ready
- **Branch**: `week-1-improvements`
- **Commits**: 8 commits with Week 1 features
- **Features**: All 8 features implemented and feature-flagged
- **Testing**: Feature flags verified, defaults to disabled

### ✅ Deployment Safety
- **Feature Flags**: All disabled for dark deployment
- **Rollback**: Instant (disable ENABLE_SUBCOLLECTION_COMPLETIONS)
- **Risk**: Low (feature-flagged, gradual rollout)

---

## Post-Deployment Monitoring Plan

### Immediate (First Hour)
**Check after deployment completes**:

1. **Service Health**:
   ```bash
   curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/health
   ```
   Expected: 200 OK

2. **Revision Status**:
   ```bash
   gcloud run services describe prediction-coordinator --region=us-west2 \
     --format="value(status.latestReadyRevisionName,status.url)"
   ```

3. **Environment Variables**:
   ```bash
   gcloud run services describe prediction-coordinator --region=us-west2 \
     --format="yaml(spec.template.spec.containers[0].env)" | grep ENABLE
   ```

### First 24 Hours (After Enabling Dual-Write)
**Monitor for consistency**:

1. **Dual-Write Consistency Logs** (Every 4 hours):
   ```bash
   gcloud logging read "
     resource.type=cloud_run_revision
     severity=WARNING
     'CONSISTENCY MISMATCH'
   " \
     --limit 50 \
     --format="table(timestamp,jsonPayload.message)"
   ```
   **Expected**: ZERO mismatches

2. **Subcollection Write Errors** (Every 4 hours):
   ```bash
   gcloud logging read "
     resource.type=cloud_run_revision
     severity>=ERROR
     'subcollection'
   " \
     --limit 50
   ```
   **Expected**: ZERO errors

3. **Batch Completion Metrics** (Daily):
   - Check batch completion counts
   - Verify counter increments correctly
   - Confirm no duplicate player entries

### Days 2-7 (Continued Monitoring)
**Daily checks**:
- Review consistency mismatch logs (expect zero)
- Check error rates (should remain stable)
- Monitor batch completion performance
- Track completed_count vs array length

---

## Success Criteria

### Phase 1: Dark Deployment
- ✅ Deployment completes without errors
- ✅ Service health check passes
- ✅ New revision is serving traffic
- ✅ No increase in error rates
- ✅ All feature flags confirmed disabled

### Phase 2: Dual-Write Enabled
- ✅ Environment variables updated successfully
- ✅ Service restarts without errors
- ✅ Dual-write executes on next batch
- ✅ Zero consistency mismatches (first 100 operations)
- ✅ completed_count matches array length

### Phase 3: 24-Hour Validation
- ✅ Zero consistency mismatches over 24 hours
- ✅ No errors in subcollection writes
- ✅ Performance stable (no degradation)
- ✅ completed_count accuracy: 100%

---

## Rollback Procedures

### Immediate Rollback (< 2 minutes)
**If critical issues detected**:

```bash
# Disable dual-write immediately
gcloud run services update prediction-coordinator \
  --region us-west2 \
  --update-env-vars \
ENABLE_SUBCOLLECTION_COMPLETIONS=false

# Verify rollback
gcloud run services describe prediction-coordinator --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env[?(@.name=='ENABLE_SUBCOLLECTION_COMPLETIONS')].value)"
```

**Expected**: Service reverts to array-only mode

### Full Rollback (< 5 minutes)
**If dark deployment causes issues**:

```bash
# Rollback to previous revision
PREVIOUS_REVISION=$(gcloud run revisions list \
  --service prediction-coordinator \
  --region us-west2 \
  --format="value(name)" \
  --limit 2 | tail -1)

gcloud run services update-traffic prediction-coordinator \
  --region us-west2 \
  --to-revisions $PREVIOUS_REVISION=100
```

---

## Risk Assessment

### Low Risk ✅
- Dark deployment with all flags disabled
- Feature-flagged changes (instant enable/disable)
- Dual-write pattern (backward compatible)
- 10% consistency sampling (low overhead)
- Instant rollback capability

### Medium Risk ⚠️
- New Firestore write pattern (dual-write)
- Increased Firestore write operations (2x)
- Subcollection structure (new data model)

### Mitigations
- ✅ Gradual rollout (enable one feature at a time)
- ✅ Comprehensive monitoring (consistency checks)
- ✅ Automatic validation (10% sampling)
- ✅ Instant rollback (feature flag disable)
- ✅ 7-day validation period before switching reads

---

## Timeline

| Time | Phase | Action | Status |
|------|-------|--------|--------|
| **17:15** | Phase 1 | Start dark deployment | 🟡 In Progress |
| **17:20** | Phase 1 | Verify deployment success | ⏳ Pending |
| **17:25** | Phase 2 | Enable dual-write | ⏳ Pending |
| **17:30** | Phase 2 | Verify dual-write functioning | ⏳ Pending |
| **17:35** | Phase 2 | First consistency check | ⏳ Pending |
| **21:00** | Phase 2 | 4-hour consistency check | ⏳ Pending |
| **Jan 22** | Phase 3 | 24-hour validation | ⏳ Pending |
| **Jan 23-28** | Phase 3 | Continued monitoring | ⏳ Pending |
| **Jan 29** | Phase 4 | Switch to subcollection reads | ⏳ Planned |

---

## Deployment Artifacts

### Code Artifacts
- **Branch**: `week-1-improvements`
- **Latest Commit**: `27893e85` - Validation findings
- **Week 1 Commits**: 8 commits with features

### Documentation
- `docs/09-handoff/2026-01-21-JANUARY-VALIDATION-FINDINGS.md` - Validation results
- `docs/08-projects/current/week-2-improvements/WEEK-1-DEPLOYMENT-GUIDE.md` - Full deployment guide
- `docs/09-handoff/2026-01-21-WEEK-2-SESSION-HANDOFF.md` - Session handoff

### Monitoring Queries
```bash
# Quick health check
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/health

# Check dual-write logs
gcloud logging read "
  resource.type=cloud_run_revision
  resource.labels.service_name=prediction-coordinator
  severity>=WARNING
  timestamp>=\"$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')\"
" --limit 100 --format json

# Get batch metrics from Firestore
# (requires firestore query via console or SDK)
```

---

## Next Steps (After Deployment Completes)

1. **Immediate** (within 5 minutes):
   - Verify deployment succeeded
   - Check service health
   - Enable dual-write
   - Monitor first 10 operations

2. **First Hour**:
   - Check for consistency mismatches
   - Verify no errors in logs
   - Confirm batch completions working

3. **First 24 Hours**:
   - Review logs every 4 hours
   - Track consistency metrics
   - Document any issues

4. **Days 2-7**:
   - Daily log reviews
   - Performance monitoring
   - Prepare for read switchover

---

**Deployment Lead**: Claude Code Assistant
**Session**: Week 2 Analysis - Deployment Phase
**Contact**: See handoff documents for details

**Last Updated**: 2026-01-21 17:18 PST
**Next Update**: After deployment completes
