# Data Quality Improvement Plan

**Created:** 2026-02-04 (Session 122)
**Status:** PLANNED - Ready for Implementation
**Owner:** Engineering Team
**Timeline:** 3 phases over 8-12 weeks

---

## Quick Links

- **Full Plan:** See Session 122 handoff investigation output (Agent adbac8c)
- **Session Handoff:** [docs/09-handoff/2026-02-04-SESSION-122-VALIDATION-INVESTIGATION.md](../../09-handoff/2026-02-04-SESSION-122-VALIDATION-INVESTIGATION.md)
- **Implementation Tracking:** This directory (to be created as work progresses)

---

## Executive Summary

143-hour, 3-phase roadmap to improve data quality from 85% → 95%+ with automated detection and remediation.

**ROI:** 4-month payback ($14,300 investment, $42,000/year savings)

**Key Metrics:**
- Issue detection: 24h → 1h
- Auto-remediation: 0% → 80%
- MTTR: 6h → 30min
- Deployment drift: 24h → <6h

---

## Phase 1: Critical Detection & Remediation

**Timeline:** 3-4 weeks
**Effort:** 49 hours
**Status:** Not Started

### Components

1. **Hourly Health Checks** (4h) - P0
   - Detect issues within 1 hour instead of 24 hours
   - File: `bin/monitoring/hourly_health_check.sh`
   - Cloud Scheduler: Every hour

2. **Pre-Processing Quality Gates** (6h) - P0
   - Block processing when upstream data insufficient
   - Extend Session 119 dependency validation pattern
   - Files: Phase 4 processor files

3. **Auto-Backfill Queue** (10h) - P0
   - 80% auto-remediation rate
   - File: `shared/utils/auto_backfill_orchestrator.py`
   - Safety: max 3 backfills/day, human approval >7 days

4. **Self-Healing Phase 3 Completion** (3h) - P0
   - 100% completion tracking accuracy
   - Extend: `bin/maintenance/reconcile_phase3_completion.py`
   - Cloud Scheduler: Every 6 hours

5. **Extend validate-daily Skill** (8h) - P0
   - Add 5 new quality checks
   - File: `shared/validation/daily_quality_checker.py`
   - Checks: DNP pollution, usage rate anomalies, deployment drift, Phase 3 accuracy, spot checks

6. **BigQuery Metrics Dashboard** (8h) - P0
   - Real-time visibility into data quality
   - Views: `data_quality_summary_last_7d`, `quality_trend_analysis`
   - Cloud Monitoring integration

7. **Tiered Slack Alerting** (4h) - P0
   - Route alerts by severity
   - Channels: #nba-data-quality-critical, -warnings, -info

8. **Pre-Deployment Health Check** (6h) - P0
   - Validate deployments before production
   - Extend: `bin/validation/pre_deployment_check.py`
   - Checks: Golden dataset, regression tests, schema compatibility

---

## Phase 2: Monitoring & Prevention

**Timeline:** 2-3 weeks
**Effort:** 38 hours
**Status:** Not Started

### Components

1. **Real-Time Anomaly Detection** (8h) - P1
   - Statistical anomaly detection (<5 min detection)
   - File: `shared/validation/anomaly_detector.py`
   - 2-3σ deviation = WARNING, >3σ = CRITICAL

2. **Automatic Deployment Sync** (6h) - P1
   - Auto-deploy on drift detection
   - File: `bin/maintenance/auto_deploy_on_drift.sh`
   - Safety: only 2-6 AM ET, tests must pass

3. **Pre-Write Validation Expansion** (6h) - P1
   - Extend Session 120 validators to zone tables
   - File: `shared/validation/pre_write_validator.py`
   - Tables: player_shot_zone_analysis, team_defense_zone_analysis

4. **Email Digest System** (6h) - P1
   - Daily (8 AM ET) and weekly (Monday 9 AM ET) summaries
   - File: `bin/monitoring/send_quality_digest.py`
   - Format: HTML email with trends

5. **Canary Deployment System** (12h) - P1
   - Deploy to 10%, validate, then 100%
   - File: `bin/deployment/canary_deploy.sh`
   - Duration: 60 min canary validation

---

## Phase 3: Testing & Resilience

**Timeline:** 3-4 weeks
**Effort:** 56 hours
**Status:** Not Started

### Components

1. **Schema Drift Detection** (4h) - P2
   - Detect schema changes that break processors
   - File: `shared/validation/schema_validator.py`
   - Runtime validation before writes

2. **Golden Dataset Expansion** (12h) - P2
   - 5 → 50+ records across scenarios
   - File: Extend `scripts/maintenance/populate_golden_dataset.py`
   - Scenarios: high/low usage, DNP, blowouts, OT, B2B, early season

3. **Regression Test Suite** (16h) - P2
   - 80% coverage, prevent known bugs
   - Directory: `tests/regression/`
   - Tests: DNP pollution, usage rate, completion tracking, deployment drift

4. **PagerDuty Integration** (8h) - P2
   - Escalate CRITICAL issues >1 hour unresolved
   - File: `shared/utils/pagerduty_integration.py`
   - MTTA <15 min, MTTR <1 hour

5. **Chaos Engineering Tests** (16h) - P3
   - Test system resilience to failures
   - Directory: `tests/chaos/`
   - Tests: BigQuery write failure, Firestore unavailable, schema mismatch

---

## Implementation Priority

### Week 1 (22 hours)
1. Hourly Health Checks (4h)
2. Extend validate-daily (8h)
3. Auto-Backfill Queue (10h)

### Week 2 (27 hours)
1. Pre-Processing Quality Gates (6h)
2. Self-Healing Phase 3 (3h)
3. BigQuery Dashboard (8h)
4. Tiered Slack Alerting (4h)
5. Pre-Deployment Check (6h)

### Week 3-4 (38 hours - Phase 2)
All Phase 2 components

### Week 5-8 (56 hours - Phase 3)
All Phase 3 components

---

## Success Metrics

### Target State (3 months)

| Metric | Baseline | Target |
|--------|----------|--------|
| DNP Pollution Rate | 30.5% | <5% |
| Usage Rate Anomalies | 1228% max | <100% max |
| Spot Check Accuracy | 90% | >95% |
| Issue Detection Time | 24 hours | <1 hour |
| MTTR | 6+ hours | <30 min |
| Auto-Remediation Rate | 0% | >80% |
| Deployment Drift | 24+ hours | <6 hours |
| Regression Test Coverage | 0% | >80% |
| Golden Dataset Size | 5 records | 50+ records |
| System Resilience | Unknown | >95% |

---

## Cost Analysis

### Infrastructure Costs (Monthly)

| Component | Cost |
|-----------|------|
| Hourly Health Checks | $5 |
| Auto-Backfill Worker | $20 |
| BigQuery Queries | $15 |
| Cloud Scheduler Jobs | $10 |
| PagerDuty | $29 |
| Email Digests (SES) | $5 |
| **Total** | **$84/month** |

### Engineering Time Investment

| Phase | Effort | Cost (@ $100/hr) |
|-------|--------|------------------|
| Phase 1 | 49 hours | $4,900 |
| Phase 2 | 38 hours | $3,800 |
| Phase 3 | 56 hours | $5,600 |
| **Total** | **143 hours** | **$14,300** |

### ROI Calculation

- **Current incidents:** ~8/month @ $500/incident = $4,000/month
- **With this system:** ~1/month = $500/month
- **Savings:** $3,500/month = $42,000/year
- **Payback period:** 4 months

---

## Critical Files for Implementation

### Top 5 Priority Files

1. **`shared/validation/daily_quality_checker.py`** (existing)
   - Extend with 5 new quality checks
   - Integration points for alerting and backfill queueing

2. **`shared/utils/auto_backfill_orchestrator.py`** (NEW)
   - Central orchestration for automated remediation
   - Safety constraints and decision matrix

3. **`bin/monitoring/hourly_health_check.sh`** (NEW)
   - Extends existing phase3_health_check.sh
   - Runs every hour via Cloud Scheduler

4. **`shared/validation/pre_write_validator.py`** (existing)
   - Extend with zone analysis rules (Session 120 Gap 2)
   - Pattern established in Sessions 118-121

5. **`data_processors/precompute/player_daily_cache/processor.py`** (existing)
   - Add upstream quality validation pattern (Session 119)
   - Blocks processing when Phase 3 quality insufficient

---

## Dependencies

### Existing Infrastructure (Built)

- ✅ `data_quality_metrics` table (Session 120)
- ✅ `data_quality_events` table (Session 120)
- ✅ `DailyQualityChecker` class (Session 120)
- ✅ `PreWriteValidator` class (Session 120)
- ✅ `notification_system.py` (existing)
- ✅ `phase3_health_check.sh` (Session 118)
- ✅ `reconcile_phase3_completion.py` (Session 117)
- ✅ Distributed locking (Session 118)
- ✅ BigQueryBatchWriter (existing)

### To Be Built

- ❌ Auto-backfill orchestrator
- ❌ Hourly health check script
- ❌ Anomaly detector
- ❌ Canary deployment system
- ❌ PagerDuty integration
- ❌ Chaos engineering tests
- ❌ Expanded golden dataset (5→50 records)
- ❌ Regression test suite

---

## Risk Mitigation

### Implementation Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| False Positives | HIGH | Start with WARNING only, tune thresholds, rate limiting |
| Auto-Remediation Cascade | HIGH | Safety constraints, circuit breaker, human approval >7 days |
| Complexity Increase | MEDIUM | Documentation, runbooks, training |
| Cost Overrun | LOW | Monitor daily, budget alerts, optimize queries |

### Rollback Plan

Each phase can be independently disabled:
```bash
# Disable auto-remediation
gcloud scheduler jobs pause auto-backfill-orchestrator

# Disable hourly checks
gcloud scheduler jobs pause hourly-health-check

# Disable alerts
export ENABLE_QUALITY_ALERTS=false
```

---

## Session 122 Context

**Discovery:** This plan was created during Session 122 validation investigation when usage rate anomaly (1228%) was discovered.

**Findings that motivated this plan:**
- DNP pollution concerns (false alarm but revealed monitoring gap)
- Phase 3 completion confusion (date interpretation issue)
- Usage rate data corruption (isolated incident)
- Spot check accuracy 90% (below 95% threshold)
- Deployment drift (2 services stale)

**Agent Investigation:**
- 4 parallel agents investigated different issues
- Total investigation time: ~2 hours
- Tool uses: 150+ across agents
- Created comprehensive 143-hour improvement roadmap

---

## Next Steps

1. **Immediate (Session 122):** Fix usage rate anomaly for Feb 3
2. **Week 1:** Start Phase 1 implementation (22 hours)
3. **Week 2:** Complete Phase 1 (27 hours)
4. **Week 3-4:** Implement Phase 2 (38 hours)
5. **Week 5-8:** Implement Phase 3 (56 hours)

**Target Completion:** Mid-April 2026

---

## Documentation

- **Session Handoff:** [docs/09-handoff/2026-02-04-SESSION-122-VALIDATION-INVESTIGATION.md](../../09-handoff/2026-02-04-SESSION-122-VALIDATION-INVESTIGATION.md)
- **Validation Infrastructure:** docs/08-projects/current/validation-infrastructure-sessions-118-120.md
- **Phase 3 Orchestration:** docs/08-projects/current/prevention-and-monitoring/phase3-orchestration-reliability/
- **System Features:** docs/02-operations/system-features.md
