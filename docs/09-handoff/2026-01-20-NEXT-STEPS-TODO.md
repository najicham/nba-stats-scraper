# Next Steps & TODO List - Post Robustness Deployment

**Date**: 2026-01-20
**Session**: Robustness Improvements Deployed
**Revision**: `prediction-coordinator-00076-dsv`
**Status**: ✅ All improvements deployed and verified

---

## ✅ What Was Just Completed

### Deployment Summary
- ✅ **5 commits pushed** to `week-1-improvements` branch
- ✅ **Deployed to production** - Revision 00076-dsv
- ✅ **Service health verified** - 200 OK
- ✅ **Slack integration tested** - Alerts working
- ✅ **Monitoring baseline established** - 0 errors, 0 mismatches

### Improvements Now Active
1. ✅ Slack alerts for consistency mismatches → #week-1-consistency-monitoring
2. ✅ BigQuery insert for unresolved MLB players → mlb_reference.unresolved_players
3. ✅ Standardized logging (15 print→logger conversions)
4. ✅ AlertManager integration for Pub/Sub failures

---

## 📋 Immediate Next Steps (This Week)

### Priority 1: Monitor Week 1 Deployment (CRITICAL)

**Timeline**: Day 0 (Jan 20) → Day 1 starts Jan 21

**Daily Tasks** (10-15 min/day):
- [ ] Run monitoring checks every morning
  ```bash
  # 1. Health check
  curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    https://prediction-coordinator-756957797294.us-west2.run.app/health

  # 2. Consistency mismatches (expect 0)
  gcloud logging read "severity=WARNING 'CONSISTENCY MISMATCH'" \
    --limit 50 --freshness=24h

  # 3. Subcollection errors (expect 0)
  gcloud logging read "severity>=ERROR 'subcollection'" \
    --limit 50 --freshness=24h
  ```

- [ ] Check #week-1-consistency-monitoring for any alerts
- [ ] Document daily status in monitoring log
- [ ] If any issues found → investigate immediately (see runbook)

**Monitoring Log Location**: Create `docs/09-handoff/week-1-monitoring-log.md`

**Resources**:
- Runbook: `docs/02-operations/robustness-improvements-runbook.md`
- Week 1 Plan: `docs/09-handoff/2026-01-21-WEEK-1-DEPLOYMENT-HANDOFF.md`

---

### Priority 2: Apply Same Improvements to Worker (Optional)

**Why**: Worker also has unified_pubsub_publisher.py with same TODO

**Tasks**:
- [ ] Review worker codebase for similar patterns
- [ ] Apply AlertManager integration to worker Pub/Sub publisher
- [ ] Convert any print() statements to logger calls
- [ ] Test and deploy worker improvements

**Estimated Time**: 1-2 hours

**Files to Review**:
- `predictions/worker/shared/publishers/unified_pubsub_publisher.py`
- Any worker files with print() statements

---

### Priority 3: Verify BigQuery Unresolved Players (When MLB Season Starts)

**Timeline**: Next MLB prediction run

**Tasks**:
- [ ] Monitor first MLB prediction execution
- [ ] Check if unresolved players are encountered
- [ ] Verify BigQuery inserts working:
  ```sql
  SELECT * FROM `nba-props-platform.mlb_reference.unresolved_players`
  WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  ORDER BY occurrence_count DESC
  ```
- [ ] Review unresolved players and add to registry
- [ ] Document resolution workflow

---

## 🎯 Short-Term Goals (Next 1-2 Weeks)

### Week 1 Migration Timeline

| Day | Date | Milestone | Action |
|-----|------|-----------|--------|
| 0 | Jan 20 | ✅ Deployed | Improvements active, baseline established |
| 1-6 | Jan 21-26 | ⏳ Monitor dual-write | Daily checks, 0 mismatches expected |
| 7 | Jan 27 | 📋 Prepare switchover | Review logs, plan Day 8 switch |
| 8 | Jan 28 | 🔀 Switch to subcollection reads | Update `USE_SUBCOLLECTION_READS=true` |
| 9-14 | Jan 29-Feb 3 | ⏳ Monitor reads | Verify subcollection reads working |
| 15 | Feb 4 | 🎉 Stop dual-write | Update `DUAL_WRITE_MODE=false` |
| 16+ | Feb 5+ | ✅ Migration complete | Archive #week-1-consistency-monitoring |

### Testing & Quality Improvements

**Integration Tests** (2-3 hours):
- [ ] Add test for dual-write consistency validation
- [ ] Add test for Slack alert delivery (mocked)
- [ ] Add test for BigQuery insert for unresolved players
- [ ] Add test for AlertManager integration

**Test Coverage Analysis** (1 hour):
- [ ] Run pytest with coverage: `pytest --cov=predictions/coordinator`
- [ ] Identify critical paths without tests
- [ ] Prioritize test gaps

**CI/CD Integration** (1-2 hours):
- [ ] Add test execution to Cloud Build
- [ ] Add coverage reporting
- [ ] Set minimum coverage threshold
- [ ] Add pre-commit hooks

---

## 💡 Medium-Term Opportunities (Week 2-4)

### Week 2-3 Features (From Agent Analysis)

**Priority Order**:

1. **Prometheus Metrics Export** (1-2 hours, HIGH impact)
   - Add /metrics endpoint
   - Export key metrics (requests, errors, latency)
   - Integrate with Grafana

2. **Universal Retry Mechanism** (2-3 hours, HIGH impact)
   - Centralized retry logic with exponential backoff
   - Configurable retry policies
   - Better reliability

3. **Integration Test Suite** (6-8 hours, MEDIUM impact)
   - End-to-end pipeline tests
   - Smoke tests for all scrapers (120+)
   - Automated validation

4. **CLI Tool for Operations** (4-6 hours, MEDIUM impact)
   - Manual player registry management
   - Data quality checks
   - Configuration management

5. **Async/Await Migration** (4-6 hours, MEDIUM impact)
   - Convert synchronous operations to async
   - 5.6x performance improvement potential
   - Phase 1 async processing

### Documentation Gaps

**High Priority**:
- [ ] Cloud Functions reference (32 functions)
- [ ] Grafana dashboards guide (7 dashboards)
- [ ] Alert system setup guide
- [ ] Validation scripts catalog

**Medium Priority**:
- [ ] Architecture diagrams
- [ ] Onboarding guide improvements
- [ ] Troubleshooting playbook expansion

### Cost Optimization

**Quick Wins**:
- [ ] Cloud Run right-sizing (50% savings on validators)
- [ ] SELECT * → explicit columns (10-20% per query)
- [ ] Firestore batch operations (20-30% savings)

**Analysis Required**:
- [ ] Audit BigQuery query patterns
- [ ] Review cache hit rates
- [ ] Analyze Cloud Run CPU/memory utilization

---

## 🔍 Known Issues & Technical Debt

### From Agent Analysis

**Critical** (Should fix soon):
1. ~~Slack alerts for consistency mismatches~~ ✅ FIXED
2. ~~BigQuery insert for unresolved MLB players~~ ✅ FIXED
3. Stale prediction detection (Phase 6 blocker) - stubbed out

**Medium**:
4. 40+ bare pass statements (reviewed - mostly acceptable)
5. AlertManager integration incomplete in some areas
6. Broad Exception catches in 5+ locations

**Low**:
7. Global singleton pattern (makes testing harder)
8. sys.exit() in library code
9. Some unimplemented abstract methods

---

## 📊 Success Metrics to Track

### Robustness Improvements Impact

**Week 1** (Track daily):
- Consistency mismatches detected: Target = 0
- Service uptime: Target = 100%
- Alert delivery time: Target < 1 min
- Unresolved players tracked: All persisted to BigQuery

**Week 2-4** (Track weekly):
- MTTR (Mean Time To Resolution): Expect 50% reduction
- Silent failures: Expect 0 (all alerted)
- Data loss incidents: Expect 0 (all tracked)
- Debug time per issue: Expect 30% reduction

### Week 1 Migration Success

**By Feb 5**:
- Dual-write consistency: 100% (0 mismatches)
- Subcollection reads working: 100%
- Zero downtime: ✅
- Zero data loss: ✅
- Scalability: Unlimited (was 800/1000)

---

## 🚨 Risk Areas to Watch

### Week 1 Monitoring Period

**Potential Issues**:
1. **Firestore transaction timeouts** → Consistency mismatches
2. **Network issues** → Missed writes to subcollection
3. **Race conditions** → Duplicate writes despite lock
4. **High load** → Timeout on consistency checks

**Mitigation**:
- Daily monitoring with immediate alerts
- Runbook ready for common scenarios
- Rollback procedure tested and documented
- #week-1-consistency-monitoring channel monitored

### Production Stability

**Watch For**:
- Any increase in error rates
- Performance degradation
- Memory/CPU spikes
- Unusual log patterns

**Response**:
- Check structured logs in Cloud Logging
- Review AlertManager notifications
- Consult robustness runbook
- Consider rollback if critical

---

## 📚 Key Documentation

### Must Read
1. **Robustness Improvements Runbook** ⭐⭐⭐
   - `docs/02-operations/robustness-improvements-runbook.md`
   - Troubleshooting scenarios
   - Monitoring commands
   - Configuration reference

2. **Session Handoff** ⭐⭐
   - `docs/09-handoff/2026-01-20-ROBUSTNESS-IMPROVEMENTS-SESSION.md`
   - What was deployed
   - Testing procedures
   - Deployment checklist

3. **Week 1 Deployment Guide** ⭐⭐
   - `docs/09-handoff/2026-01-21-WEEK-1-DEPLOYMENT-HANDOFF.md`
   - Complete Week 1 overview
   - Timeline and milestones
   - Emergency procedures

### Reference
4. BigQuery Schema: `schemas/bigquery/mlb_reference/unresolved_players_table.sql`
5. Slack Channels Guide: `orchestration/cloud_functions/self_heal/shared/utils/slack_channels.py`
6. AlertManager: `shared/alerts/rate_limiter.py`

---

## 🎓 Quick Commands Reference

### Daily Monitoring
```bash
# Service health
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://prediction-coordinator-756957797294.us-west2.run.app/health

# Consistency checks
gcloud logging read "severity=WARNING 'CONSISTENCY MISMATCH'" \
  --limit 50 --freshness=24h

# Recent errors
gcloud logging read "severity>=ERROR resource.labels.service_name=prediction-coordinator" \
  --limit 50 --freshness=24h
```

### BigQuery Queries
```sql
-- Check unresolved MLB players
SELECT
  player_lookup,
  player_type,
  COUNT(*) as reports,
  SUM(occurrence_count) as total_occurrences
FROM `nba-props-platform.mlb_reference.unresolved_players`
WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY player_lookup, player_type
ORDER BY total_occurrences DESC;
```

### Service Management
```bash
# Current revision
gcloud run services describe prediction-coordinator --region=us-west2 \
  --format="value(status.latestReadyRevisionName)"

# Environment variables
gcloud run services describe prediction-coordinator --region=us-west2 \
  --format="yaml(spec.template.spec.containers[0].env)"

# Recent logs
gcloud logging read "resource.labels.service_name=prediction-coordinator" \
  --limit 50 --format="table(timestamp,severity,textPayload)"
```

---

## ✅ Session Completion Checklist

**Before Ending This Session**:
- [x] All improvements deployed
- [x] Service health verified
- [x] Slack integration tested
- [x] Monitoring baseline established
- [x] Documentation created
- [x] Commits pushed to remote
- [x] Next steps documented

**For Next Session**:
- [ ] Run Day 1 monitoring checks
- [ ] Check Slack channel for any overnight alerts
- [ ] Document monitoring results
- [ ] Continue with Priority 1 tasks above

---

## 🎯 Overall Goal

**Build a robust, self-healing system** where:
- Failures are caught early (alerting)
- Data is never lost (persistence)
- Debugging is fast (observability)
- Recovery is automated (resilience)

**Progress So Far**: ✅ 4/4 robustness improvements deployed
**Next Focus**: Monitor Week 1 migration success
**Timeline**: 15 days to complete migration (Jan 21 - Feb 5)

---

**Created**: 2026-01-20
**Author**: Claude Code
**Status**: Active - Use for next session planning
**Priority**: Monitor Week 1 daily, then execute short-term goals

🚀 **Great work! The system is now more robust and observable.** 🚀
