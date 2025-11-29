# Phase 4→5 Integration - Action Plan

**Created:** 2025-11-28
**Status:** Ready to Execute
**Timeline:** 3-4 days development + 3-5 days validation = **1-2 weeks to production**

---

## Quick Summary

**What:** Add event-driven trigger from Phase 4 to Phase 5 with scheduler backup
**Why:** Predictions 6+ hours faster, automatic failure recovery, comprehensive alerting
**How:** Pub/Sub + Cloud Scheduler hybrid + retry logic
**Cost:** ~$5/month additional
**Effort:** ~10-12 hours development + testing

---

## Critical Pre-Work: Timezone Decision

⚠️ **MUST RESOLVE BEFORE STARTING:**

**Current State:**
- Deployment script: 6:00 AM **PT** (Pacific Time)
- Documentation claims: 7:00 AM **ET** (Eastern Time) SLA
- **These are incompatible** (6:00 AM PT = 9:00 AM ET)

**Choose One:**

### Option A: Realistic SLA (Recommended)
- **SLA:** Predictions ready by **10:00 AM ET / 7:00 AM PT**
- **Impact:** Matches current scheduler, no code changes needed
- **Tradeoff:** 3 hours later than documented SLA
- **Action:** Update all docs to reflect 7:00 AM PT / 10:00 AM ET

### Option B: Aggressive SLA
- **SLA:** Predictions ready by **7:00 AM ET / 4:00 AM PT**
- **Impact:** Must move scheduler to 3:00 AM PT (gives 1-hour buffer)
- **Tradeoff:** Higher risk if Phase 4 runs late
- **Action:** Change scheduler times + retry times

**Decision Required:** [ ] Option A  [ ] Option B

---

## Implementation Phases

### Phase 1: Core Integration (Day 1-2, ~6-8 hours)

**Goal:** Event-driven triggering with basic validation

**Tasks:**
1. [ ] Add `_validate_phase4_ready()` to coordinator (1 hr)
2. [ ] Add `_get_batch_status()` deduplication (1 hr)
3. [ ] Add `_wait_for_phase4()` with 30-min timeout (30 min)
4. [ ] Add `/trigger` endpoint for Pub/Sub (1 hr)
5. [ ] Update `/start` endpoint with validation (1 hr)
6. [ ] Add `_publish_phase4_completion()` to ml_feature_store_processor.py (1 hr)
7. [ ] Unit tests for all new functions (2 hrs)

**Deliverable:** Code ready for deployment, unit tests passing

**Files Changed:**
- `predictions/coordinator/coordinator.py` (+200 lines)
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` (+50 lines)
- `tests/predictions/test_coordinator.py` (new tests)

---

### Phase 2: Infrastructure (Day 2, ~2 hours)

**Goal:** Deploy Pub/Sub and Cloud Scheduler infrastructure

**Tasks:**
1. [ ] Create Pub/Sub topic: `nba-phase4-precompute-complete` (5 min)
2. [ ] Create push subscription to coordinator `/trigger` (10 min)
3. [ ] Update Cloud Scheduler (6:00 AM PT backup) (10 min)
4. [ ] Create retry schedulers (6:15 AM, 6:30 AM PT) (15 min)
5. [ ] Create status check scheduler (7:00 AM PT) (10 min)
6. [ ] Verify infrastructure (10 min)
7. [ ] Deploy updated coordinator to Cloud Run (30 min)
8. [ ] Deploy updated ml_feature_store processor (30 min)

**Deliverable:** All infrastructure deployed and configured

**Script:** `bin/phase5/deploy_pubsub_infrastructure.sh` (create this)

---

### Phase 3: Retry & Alerting (Day 2-3, ~4 hours)

**Goal:** Automatic retry and comprehensive alerting

**Tasks:**
1. [ ] Add `/retry` endpoint to coordinator (1 hr)
2. [ ] Add `_get_players_needing_retry()` helper (30 min)
3. [ ] Add `_process_retry_batch()` logic (1 hr)
4. [ ] Integrate alerting system (30 min)
5. [ ] Configure Email alerts (15 min)
6. [ ] Configure Slack alerts (15 min)
7. [ ] Test alert delivery (30 min)

**Deliverable:** Retry logic working, alerts configured

---

### Phase 4: Testing & Validation (Day 3-5, ~8 hours)

**Goal:** Comprehensive testing before production

#### Day 3: Unit & Integration Tests
- [ ] Run all unit tests (30 min)
- [ ] Manual Pub/Sub trigger test (30 min)
- [ ] Scheduler backup test (30 min)
- [ ] Deduplication test (30 min)
- [ ] Partial completion test (1 hr)
- [ ] Phase 4 late scenario test (1 hr)

#### Day 4: Staging Deployment
- [ ] Deploy to staging environment (1 hr)
- [ ] Run overnight with production data copy (automated)
- [ ] Monitor logs next morning (30 min)
- [ ] Verify predictions generated correctly (30 min)

#### Day 5: Extended Staging Validation
- [ ] 2nd night of staging runs (automated)
- [ ] Check for any errors or warnings (30 min)
- [ ] Validate latency metrics (30 min)
- [ ] Review alert delivery (30 min)

**Deliverable:** 3 successful staging runs, zero critical issues

---

### Phase 5: Production Deployment (Day 6, ~4 hours)

**Goal:** Safe production deployment with rollback plan

**Morning (9 AM - 12 PM):**
- [ ] Review staging results (30 min)
- [ ] Go/No-Go decision meeting (30 min)
- [ ] Deploy to production (1 hr)
- [ ] Verify health endpoints (15 min)
- [ ] Run smoke tests (30 min)
- [ ] Monitor for 2 hours (passive observation)

**Evening (Next Day 6 AM):**
- [ ] Monitor overnight Phase 4→5 flow (passive)
- [ ] Review logs next morning (30 min)
- [ ] Verify predictions generated (15 min)
- [ ] Check latency metrics (15 min)

**Deliverable:** Production deployment complete, first overnight run successful

---

### Phase 6: Monitoring & Hardening (Day 7-14, ongoing)

**Goal:** Establish baselines and operational excellence

**Week 1 (Day 7-10):**
- [ ] Create Grafana dashboards (2 hrs)
- [ ] Set up daily health check query (30 min)
- [ ] Document baseline metrics (1 hr)
- [ ] Run daily manual checks (15 min/day)

**Week 2 (Day 11-14):**
- [ ] Review 7 days of metrics (1 hr)
- [ ] Adjust alert thresholds based on data (1 hr)
- [ ] Document lessons learned (1 hr)
- [ ] Update operational runbook (1 hr)
- [ ] Final sign-off (30 min)

**Deliverable:** Production-stable for 2 weeks, dashboards operational

---

## Rollback Plan

**If event-driven path fails:**
```bash
# Delete Pub/Sub subscription (stops auto-triggering)
gcloud pubsub subscriptions delete nba-phase5-trigger-sub --project=nba-props-platform

# Result: Falls back to 6 AM scheduler (original behavior)
```

**If retry jobs cause issues:**
```bash
# Delete retry schedulers
gcloud scheduler jobs delete phase5-retry-1 --location=us-west2
gcloud scheduler jobs delete phase5-retry-2 --location=us-west2

# Result: Only 6 AM backup runs
```

**If coordinator completely broken:**
```bash
# Revert to previous Cloud Run revision
gcloud run services update-traffic prediction-coordinator \
    --to-revisions=prediction-coordinator-00003=100 \
    --region=us-west2

# Manual trigger if needed
curl -X POST "https://[COORDINATOR-URL]/start" \
    -H "Content-Type: application/json" \
    -d '{"game_date": "2025-11-28", "force": true}'
```

---

## Pre-Deployment Checklist

### Infrastructure
- [ ] Pub/Sub topic created: `nba-phase4-precompute-complete`
- [ ] Push subscription created with correct endpoint
- [ ] Cloud Scheduler jobs created (3 retry + 1 status check)
- [ ] DLQ topic exists and monitored
- [ ] Service accounts have required permissions

### Code
- [ ] Phase 4 publishing code deployed and tested
- [ ] Coordinator `/trigger` endpoint working
- [ ] Coordinator `/retry` endpoint working
- [ ] Coordinator `/status` endpoint working
- [ ] Alert integration tested (Email + Slack)
- [ ] All unit tests passing (100% coverage on new code)

### Monitoring
- [ ] Daily health check query saved
- [ ] Dashboard panels created in Grafana
- [ ] Alert rules configured in monitoring system
- [ ] On-call rotation notified of new service
- [ ] Runbook published and accessible

### Testing
- [ ] Manual Pub/Sub message test passed
- [ ] Scheduler trigger test passed
- [ ] Deduplication test passed
- [ ] Partial completion retry test passed
- [ ] 3+ successful staging runs completed

### Documentation
- [ ] README.md published in project folder
- [ ] IMPLEMENTATION.md complete with all code snippets
- [ ] OPERATIONS.md complete with troubleshooting
- [ ] MONITORING.md complete with queries
- [ ] TESTING.md complete with test cases

---

## Success Criteria

### Day 1 (After First Production Run)
- ✅ Phase 5 triggered automatically (via Pub/Sub OR scheduler)
- ✅ All predictions generated successfully
- ✅ Zero critical alerts
- ✅ Latency < 10 minutes (Phase 4 completion → Phase 5 start)

### Week 1 (Days 1-7)
- ✅ 7 consecutive successful runs
- ✅ Average latency < 5 minutes (event-driven path working)
- ✅ Prediction completion rate > 95%
- ✅ Zero manual interventions required

### Week 2 (Days 8-14)
- ✅ Metrics baseline established
- ✅ Dashboards operational
- ✅ Team trained on runbook
- ✅ Ready for sign-off

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Pub/Sub messages lost | Low | High | Scheduler backup at 6 AM |
| Phase 4 >30 min late | Medium | Medium | Alert immediately, manual trigger |
| Coordinator crash mid-batch | Low | Medium | Deduplication prevents double-processing |
| Alert system down | Low | High | Multiple channels (Email + Slack) |
| Wrong timezone deployed | High | Critical | **Resolve before coding** |

---

## Cost Impact

| Component | Monthly Cost |
|-----------|--------------|
| Pub/Sub topic + subscription | ~$0.40 |
| Cloud Scheduler jobs (4 total) | ~$0.40 |
| Additional Cloud Run time | ~$2-5 |
| BigQuery queries | ~$1-2 |
| **Total Additional Cost** | **~$5/month** |

**ROI:** Negligible cost for major operational improvement

---

## Next Steps

**Immediate (Today):**
1. [ ] Review this action plan
2. [ ] **CRITICAL:** Make timezone SLA decision (Option A or B)
3. [ ] Review all 5 documentation files in this project
4. [ ] Approve implementation approach

**Day 1 (Tomorrow):**
1. [ ] Start Phase 1: Core Integration (6-8 hours)
2. [ ] Daily standup: Share progress

**Day 2:**
1. [ ] Complete Phase 1 if needed
2. [ ] Start Phase 2: Infrastructure (2 hours)
3. [ ] Start Phase 3: Retry & Alerting (4 hours)

**Day 3-5:**
1. [ ] Phase 4: Testing & Validation
2. [ ] Staging deployment and monitoring

**Day 6:**
1. [ ] Go/No-Go decision
2. [ ] Production deployment

**Day 7-14:**
1. [ ] Monitor and harden
2. [ ] Create dashboards
3. [ ] Final sign-off

---

## Team Communication

**Stakeholder Updates:**
- Daily: Slack #nba-engineering (progress updates)
- Weekly: Email digest (metrics + status)
- Critical: Immediate alert for any production issues

**Escalation Path:**
1. Developer (first response)
2. On-call engineer (if developer unavailable)
3. Project lead (critical failures only)

---

## Questions & Decisions Log

| Date | Question | Decision | Rationale |
|------|----------|----------|-----------|
| 2025-11-28 | Timezone for SLA | [ PENDING ] | Waiting on user input |
| 2025-11-28 | Wait timeout duration | 30 minutes | Balance reliability vs. delay |
| 2025-11-28 | Alert threshold | 5% OR 20 players | Percentage-based scales better |
| 2025-11-28 | Retry schedule | 6:15 AM, 6:30 AM PT | Multiple chances before SLA |

---

**Document Status:** Ready for Review
**Next Action:** Timezone decision + implementation start
