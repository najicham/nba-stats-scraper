# Daily Orchestration Improvements Project

**Project Start Date:** January 18, 2026
**Status:** 🟡 In Progress
**Owner:** Engineering Team
**Priority:** P0 - Critical Infrastructure

---

## 📋 Overview

This project addresses critical brittleness in the daily orchestration system that coordinates the 5-phase NBA data pipeline. The orchestration currently runs with 99.4% reliability but requires manual intervention for recovery (MTTR: 2-4 hours). This project aims to achieve 99.9% reliability with automated self-healing (MTTR: <5 minutes).

**System Health Score:** 5.2/10 → **Target:** 8.5/10

---

## 🚨 Critical Issues Being Addressed

### 1. All-or-Nothing Orchestration Blocking Pipeline
**Impact:** HIGH - Pipeline completely blocked on Jan 18, 2026
**Root Cause:** Phase 3→4 orchestrator requires ALL 5 processors, but same-day mode only triggers 1-2
**Solution:** Mode-aware processor expectations + graceful degradation

### 2. Fixed Timing Without Dependency Validation
**Impact:** HIGH - Race conditions causing incomplete data (Jan 17: 1 record instead of 156)
**Root Cause:** Schedulers run at fixed times without checking upstream data availability
**Solution:** Pre-flight health checks + data freshness validation

### 3. Missing Overnight Analytics Schedulers
**Impact:** MEDIUM - Manual intervention required for grading (Dec 29 incident)
**Root Cause:** Only same-day schedulers exist, no overnight processing automation
**Solution:** Add 6 AM and 7 AM overnight schedulers

### 4. Data Completeness Not Validated Until Too Late
**Impact:** MEDIUM - Silent failures logged as "success" (gamebook: 3/9 games)
**Root Cause:** No validation of expected vs actual data volume
**Solution:** Game completeness health checks

---

## 🎯 Project Goals

### Primary Objectives
1. **Eliminate Pipeline Blocking**: No single processor failure should block entire pipeline
2. **Proactive Validation**: Detect data issues before triggering downstream phases
3. **Automated Recovery**: Self-healing for common failure modes
4. **Complete Automation**: Eliminate manual daily checks and interventions

### Success Metrics
- **Reliability**: 99.4% → 99.9%
- **MTTR**: 2-4 hours → <5 minutes
- **Detection Lag**: <2 minutes (already achieved, maintain)
- **Manual Interventions**: 3-4/week → <1/month
- **Deployment Failure Rate**: 15% → <1%

---

## 📅 Implementation Phases

### Phase 1: Critical Fixes (Week 1 - 16 hours)
**Status:** ✅ Complete & Deployed
**Completed:** January 19, 2026

**Tasks:**
- [x] Deploy health endpoints to production (all 6 services)
- [x] Add pre-flight health checks to Phase 3→4 orchestrator
- [x] Add pre-flight health checks to Phase 4→5 orchestrator
- [x] Implement mode-aware orchestration (overnight vs same-day)
- [x] Create automated daily health check scheduler (8 AM ET)

**Deliverables:**
- ✅ Production health endpoints responding on all services
- ✅ Orchestrators validate downstream service health before triggering
- ✅ Mode detection logic deployed
- ✅ Daily automated health summary in Slack

**Documentation:**
- `docs/09-handoff/SESSION-117-PHASE1-COMPLETE.md` - Session 117 handoff
- `PHASE-1-CRITICAL-FIXES.md` - Implementation details
- `HEALTH-ENDPOINT-INTEGRATION.md` - Health check patterns

---

### Phase 2: Data Validation (Week 2 - 16 hours)
**Status:** ✅ Implementation Complete - ⏳ Awaiting Deployment
**Completed:** January 19, 2026 (same day!)

**Tasks:**
- [x] Add data freshness validation to Phase 2→3 orchestrator (R-007)
- [x] Add data freshness validation to Phase 3→4 orchestrator (R-008)
- [x] Implement game completeness health check (R-009)
- [x] Create overnight analytics scheduler (6:00 AM ET)
- [x] Create overnight Phase 4 scheduler (7:00 AM ET)

**Deliverables:**
- ✅ BigQuery timestamp validation before all phase transitions (R-007, R-008)
- ✅ Game completeness check integrated into daily health check (R-009)
- ✅ Overnight schedulers created and enabled
- ⏳ Awaiting production deployment of 3 Cloud Functions

**Documentation:**
- `docs/09-handoff/SESSION-118-PHASE2-IMPLEMENTATION-COMPLETE.md` - Session 118 handoff
- Code changes: commits 36a08e23, 24ee6bc0

**Deployment Status:**
- ⏳ Phase 2→3 orchestrator v2.1 - Ready to deploy
- ⏳ Phase 3→4 orchestrator v1.3 - Ready to deploy
- ⏳ Daily health check v1.1 - Ready to deploy

---

### Phase 3: Retry & Connection Pooling (Weeks 3-4 - 32 hours)
**Status:** ⚪ Not Started
**Deadline:** February 15, 2026

**Tasks:**
- [ ] Complete jitter adoption in data_processors/ (20 files)
- [ ] Complete jitter adoption in orchestration/ (5 files)
- [ ] Integrate BigQuery connection pooling (30 files)
- [ ] Integrate HTTP connection pooling (20 files)
- [ ] Performance testing with pooling enabled

**Deliverables:**
- 100% retry jitter adoption (up from 30-40%)
- Connection pooling active across all services
- Documented performance improvements
- Reduced "too many connections" errors to zero

**Documentation:**
- `PHASE-3-RETRY-POOLING.md` - Implementation guide
- `JITTER-ADOPTION-TRACKING.md` - File-by-file progress
- `CONNECTION-POOL-INTEGRATION.md` - Pooling patterns

---

### Phase 4: Graceful Degradation (Weeks 5-6 - 24 hours)
**Status:** ⚪ Not Started
**Deadline:** March 1, 2026

**Tasks:**
- [ ] Define critical vs optional processors for each phase
- [ ] Implement processor priority system in orchestration_config
- [ ] Update Phase 3→4 orchestrator with priority-based triggering
- [ ] Update Phase 4→5 orchestrator with priority-based triggering
- [ ] Add adaptive timeout calculation based on historical durations
- [ ] Create automated stalled batch recovery scheduler

**Deliverables:**
- Critical path processors identified and documented
- Majority voting implemented (trigger at 80% completion)
- Adaptive timeouts replacing hardcoded 4-hour limit
- Automated stalled batch cleanup every 30 minutes

**Documentation:**
- `PHASE-4-GRACEFUL-DEGRADATION.md` - Design and implementation
- `PROCESSOR-PRIORITIES.md` - Critical vs optional classification
- `ADAPTIVE-TIMEOUTS.md` - Timeout calculation logic

---

### Phase 5: Observability (Months 2-3 - 80 hours)
**Status:** ⚪ Not Started
**Deadline:** April 15, 2026

**Tasks:**
- [ ] Add structured phase transition metrics logging
- [ ] Create Cloud Monitoring dashboards for pipeline flow
- [ ] Define SLOs for each phase transition
- [ ] Implement SLO violation alerting
- [ ] Add phase duration anomaly detection
- [ ] Create event-driven data availability signals
- [ ] Implement load testing framework

**Deliverables:**
- Grafana dashboards showing real-time pipeline flow
- SLO definitions and automated monitoring
- Alerts on phase transitions >2x historical average
- Load testing reports for BigQuery DML and Pub/Sub limits
- Event-driven triggers replacing fixed schedules

**Documentation:**
- `PHASE-5-OBSERVABILITY.md` - Monitoring architecture
- `SLO-DEFINITIONS.md` - Service level objectives
- `EVENT-DRIVEN-DESIGN.md` - Availability signal architecture
- `LOAD-TESTING-GUIDE.md` - Testing framework

---

## 🗂️ Project Structure

```
daily-orchestration-improvements/
├── README.md (this file)
├── PHASE-1-CRITICAL-FIXES.md
├── PHASE-2-DATA-VALIDATION.md
├── PHASE-3-RETRY-POOLING.md
├── PHASE-4-GRACEFUL-DEGRADATION.md
├── PHASE-5-OBSERVABILITY.md
├── IMPLEMENTATION-TRACKING.md
├── HEALTH-ENDPOINT-INTEGRATION.md
├── OVERNIGHT-SCHEDULERS.md
├── PROCESSOR-PRIORITIES.md
├── ADAPTIVE-TIMEOUTS.md
├── SLO-DEFINITIONS.md
├── EVENT-DRIVEN-DESIGN.md
└── incidents/
    └── (incident reports related to orchestration)
```

---

## 🔗 Related Projects

### Dependencies
- **Health Endpoints Implementation** (`health-endpoints-implementation/`)
  - Status: 40% complete, deployment pending
  - Provides `/health` and `/ready` endpoints for pre-flight checks

- **Pipeline Reliability Improvements** (`pipeline-reliability-improvements/`)
  - Status: Multiple phases in progress
  - Provides broader context and architectural improvements

### Complementary Projects
- **Orchestration Optimization** (`orchestration-optimization/`)
  - Earlier validation improvements
  - Patterns can be adopted

- **Daily Orchestration Tracking** (`daily-orchestration-tracking/`)
  - Incident history and patterns
  - Informs improvement priorities

---

## 📊 Current Architecture

### Phase Flow
```
Phase 1 (Scraping)
  ↓ Pub/Sub: nba-phase2-raw-complete
Phase 2 (Raw Processing)
  ↓ Orchestrator: phase2_to_phase3 (monitoring only)
Phase 3 (Analytics) - 5 processors
  ↓ Orchestrator: phase3_to_phase4 (requires ALL 5) ← PROBLEM
Phase 4 (Precompute) - 5 processors
  ↓ Orchestrator: phase4_to_phase5 (4-hour timeout)
Phase 5 (Predictions)
  ↓ Coordinator: batch processing
Phase 6 (Export)
```

### Orchestration Components

**Cloud Functions:**
- `orchestration/cloud_functions/phase2_to_phase3/` - Monitoring only
- `orchestration/cloud_functions/phase3_to_phase4/` - **Requires modification**
- `orchestration/cloud_functions/phase4_to_phase5/` - **Requires modification**
- `orchestration/cloud_functions/self_heal/` - **Requires enhancement**

**Coordinator Service:**
- `predictions/coordinator/coordinator.py` - Phase 5 orchestrator
- Batch state management via Firestore
- Worker consolidation

**Configuration:**
- `config/workflows.yaml` - Phase 1 workflow definitions
- `predictions/coordinator/shared/config/orchestration_config.py` - Phase 2-5 config

---

## 🛠️ Key Files to Modify

### Orchestrators (Add health checks, mode-aware logic)
```
orchestration/cloud_functions/phase3_to_phase4/main.py
orchestration/cloud_functions/phase4_to_phase5/main.py
orchestration/cloud_functions/phase2_to_phase3/main.py (add validation)
orchestration/cloud_functions/self_heal/main.py (enhance checks)
```

### Configuration (Enable mode-aware processing)
```
predictions/coordinator/shared/config/orchestration_config.py
```

### Health Integration (Deploy to all services)
```
Services to deploy with health endpoints:
1. prediction-coordinator
2. mlb-prediction-worker
3. prediction-worker (NBA)
4. nba-admin-dashboard
5. analytics-processor
6. precompute-processor
```

### New Schedulers (Add missing overnight jobs)
```
Cloud Scheduler jobs to create:
1. yesterday-analytics (6:00 AM ET)
2. yesterday-phase4 (7:00 AM ET)
3. daily-health-check (8:00 AM ET)
4. stalled-batch-recovery (every 30 min)
```

---

## 📈 Progress Tracking

**Overall Progress:** 10/28 tasks complete (36%)

**Phase Breakdown:**
- Phase 1: 5/5 tasks (100%) ✅ Complete & Deployed
- Phase 2: 5/5 tasks (100%) ✅ Complete - Awaiting Deployment
- Phase 3: 0/5 tasks (0%) ⚪ Not Started
- Phase 4: 0/6 tasks (0%) ⚪ Not Started
- Phase 5: 0/7 tasks (0%) ⚪ Not Started

**Latest Updates:**
- **Jan 19, 2026:** Phase 2 implementation complete (Session 118) - Ready for deployment
- **Jan 19, 2026:** Phase 1 deployed to production (Session 117)

---

## 🔍 Testing Strategy

### Unit Tests
- Orchestrator mode detection logic
- Health check integration
- Data freshness validation
- Processor priority calculation

### Integration Tests
- End-to-end pipeline with health checks
- Mode switching (overnight ↔ same-day)
- Graceful degradation scenarios
- Stalled batch recovery

### Load Tests
- BigQuery DML concurrent operations (20 query limit)
- Pub/Sub message publishing throughput
- Worker scaling under load
- Emergency mode capacity validation

---

## 📞 Escalation & Monitoring

### Daily Monitoring
- **8:00 AM ET**: Automated health check summary (Slack)
- **Manual Review**: First week of each phase implementation
- **Incident Response**: <15 minutes acknowledgment

### Alerting Thresholds
- Health endpoint failures: Immediate (PagerDuty)
- Phase transition >2x historical avg: Warning (Slack)
- Pipeline stalled >2 hours: Critical (PagerDuty)
- Data completeness <95%: Warning (Slack)

### On-Call Rotation
- Primary: Engineering lead
- Backup: Platform team
- Escalation: CTO (after 2 hours unresolved)

---

## 🎓 Lessons Learned (To Be Updated)

*This section will be populated as we implement each phase*

### Week 1 (Phase 1)
- TBD

### Week 2 (Phase 2)
- TBD

---

## 📚 References

### Internal Documentation
- `docs/01-architecture/orchestration/orchestrators.md` - Orchestration architecture
- `docs/08-projects/current/pipeline-reliability-improvements/RECURRING-ISSUES.md` - Issue patterns
- `docs/08-projects/current/health-endpoints-implementation/MASTER-TODO.md` - Health endpoint status
- `docs/09-handoff/SESSION-114-ALL-SERVICES-DEPLOYED-TO-STAGING.md` - Latest deployment

### External Resources
- [Cloud Run Health Checks](https://cloud.google.com/run/docs/configuring/healthchecks)
- [Pub/Sub Best Practices](https://cloud.google.com/pubsub/docs/best-practices)
- [BigQuery DML Quotas](https://cloud.google.com/bigquery/quotas#standard_tables)

---

**Last Updated:** January 18, 2026
**Next Review:** January 25, 2026 (end of Phase 1)
