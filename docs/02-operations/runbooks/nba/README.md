# NBA Deployment Runbooks

**Purpose**: Service-specific deployment procedures for NBA prediction and data processing infrastructure.

**Created**: Session 79 (Week 2 of Prevention & Monitoring System)

---

## Available Runbooks

| Runbook | Service | Criticality | Use When |
|---------|---------|-------------|----------|
| [Prediction Worker](./deployment-prediction-worker.md) | `prediction-worker` | **CRITICAL** | Deploying ML model or prediction logic changes |
| [Prediction Coordinator](./deployment-prediction-coordinator.md) | `prediction-coordinator` | High | Deploying batch orchestration changes |
| [Phase 4 Processors](./deployment-phase4-processors.md) | `nba-phase4-precompute-processors` | **CRITICAL** | Deploying feature/line aggregation changes |
| [Phase 3 Processors](./deployment-phase3-processors.md) | `nba-phase3-analytics-processors` | High | Deploying analytics processing changes |

---

## Quick Reference

### Standard Deployment Flow

```bash
# 1. Verify current state
gcloud run services describe <service-name> --region=us-west2

# 2. Deploy using automated script
./bin/deploy-service.sh <service-name>

# 3. Post-deployment validation runs automatically
# Script validates:
# - Service identity
# - Heartbeat code
# - Service-specific health checks
# - Recent error rate

# 4. Monitor for 24 hours
./bin/monitoring/unified-health-check.sh --verbose
```

### Emergency Rollback

```bash
# List revisions
gcloud run revisions list --service=<service-name> --region=us-west2 --limit=5

# Rollback to previous
gcloud run services update-traffic <service-name> \
  --region=us-west2 \
  --to-revisions=<previous-revision>=100
```

---

## When to Use Each Runbook

### Before ANY Deployment

1. Read the service-specific runbook
2. Complete pre-deployment checklist
3. Document rollback plan
4. Run automated deploy script
5. Verify post-deployment health

### Prediction Worker

**Use when**:
- Changing ML model version (V8 → V9)
- Updating prediction logic
- Modifying feature usage
- Changing data loaders

**Critical metrics**:
- Prediction volume (should match schedule)
- Hit rate (55-58% for premium picks)
- Error rate (<1%)

### Prediction Coordinator

**Use when**:
- Changing batch orchestration
- Updating player loading logic
- Modifying scheduler integration
- Changing REAL_LINES_ONLY mode

**Critical metrics**:
- Batch completion rate (100%)
- Player loading count (matches expected)
- Worker call success rate (>95%)

### Phase 4 Processors

**Use when**:
- Changing `VegasLineSummaryProcessor`
- Updating line aggregation logic
- Modifying precompute features

**Critical metrics**:
- **Vegas line coverage (90%+)** - MOST IMPORTANT
- Processor completion rate (100%)
- Data freshness (available by 7 AM ET)

### Phase 3 Processors

**Use when**:
- Changing `PlayerGameSummaryProcessor`
- Updating shot zone logic
- Modifying evening processing (boxscore fallback)
- Changing analytics calculations

**Critical metrics**:
- Phase 3 completion rate (100%)
- Shot zone completeness (50-90%)
- Heartbeat health (one doc per processor)

---

## Common Issues Across All Services

### Issue: Service Identity Mismatch

**Detection**: Deploy script reports mismatch
**Fix**: Check Dockerfile CMD, rebuild if needed

### Issue: Heartbeat Document Proliferation

**Detection**: Firestore has >100 docs (should be ~30)
**Fix**: Run `python bin/cleanup-heartbeat-docs.py`

### Issue: Silent BigQuery Write Failure

**Detection**: Processor completes but table has 0 records
**Fix**: Check logs for 404 errors, verify table references

### Issue: Quota Exceeded

**Detection**: "Too many partition modifications" error
**Fix**: Use `BigQueryBatchWriter` instead of single-row writes

---

## Post-Deployment Monitoring

**First 24 hours** after ANY deployment:

```bash
# Automated health check (runs every 6 hours)
gcloud scheduler jobs describe trigger-health-check --location=us-west2

# Manual validation
/validate-daily

# Service-specific logs
gcloud logging read \
  'resource.labels.service_name="<service-name>"
   AND severity>=ERROR' \
  --limit=50
```

---

## Success Criteria

Deployment is successful when:

- ✅ Service responds to `/health` endpoint
- ✅ Service identity matches expected
- ✅ No errors in logs (10 min window)
- ✅ Service-specific validation passes
- ✅ Critical metrics maintained or improved
- ✅ 24-hour monitoring shows stability

---

## Related Documentation

- [Deployment Guide](../../DEPLOYMENT-GUIDE.md) - General deployment procedures
- [Deployment Troubleshooting](../../DEPLOYMENT-TROUBLESHOOTING.md) - Common issues
- [Monitoring Quick Reference](../../MONITORING-QUICK-REFERENCE.md) - Monitoring commands
- [Prevention & Monitoring System](../../../08-projects/current/prevention-and-monitoring/) - Project home

---

## Feedback & Updates

These runbooks are living documents. If you:
- Encounter an issue not documented here
- Find a better procedure
- Discover new common failure modes

**Update the relevant runbook** and document in handoff.

---

## Change Log

| Date | Changes | Session |
|------|---------|---------|
| 2026-02-02 | Initial runbooks created for all critical services | Session 79 |
