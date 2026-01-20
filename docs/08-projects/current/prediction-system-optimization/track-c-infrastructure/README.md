# Track C: Phase 5 Infrastructure Monitoring & Alerts

**Status:** 📋 Planned
**Priority:** MEDIUM
**Estimated Time:** 10-12 hours
**Target Completion:** 2026-01-30

---

## 🎯 Objective

Build robust monitoring and alerting infrastructure for the Phase 5 prediction system to:
1. Detect performance degradation early
2. Prevent silent failures
3. Enable proactive incident response
4. Maintain operational excellence

---

## 📊 Monitoring Scope

### Models (6 systems)
- XGBoost V1
- CatBoost V8
- Ensemble V1
- Moving Average Baseline
- Similarity V1
- Zone Matchup V1

### Infrastructure
- Prediction Worker (Cloud Run)
- Prediction Coordinator (Cloud Run)
- Circuit Breaker System
- Feature Store Quality
- Pub/Sub Triggers

### Data Quality
- Prediction completeness
- Feature availability
- Grading coverage
- Vegas line coverage

---

## 📋 Task Breakdown

### Component 1: Model Performance Alerts (3 hours)

**1.1 Performance Degradation Alerts**
- [ ] MAE exceeds baseline by >20% for 3+ days
- [ ] Win rate drops below 50% for 7+ days
- [ ] Confidence calibration breaks (>10% deviation)
- [ ] Prediction volume drops >50%

**1.2 Quality Alerts**
- [ ] Placeholder predictions appear (should be 0)
- [ ] Predictions outside valid range [0, 60]
- [ ] NULL model_version or confidence_score
- [ ] Duplicate predictions for same player-game

**1.3 Model-Specific Alerts**
- [ ] XGBoost V1: MAE > 4.2 for 3 days
- [ ] CatBoost V8: MAE > 3.9 for 3 days
- [ ] Ensemble V1: MAE > 3.7 for 3 days

**Deliverable:** `model-alerts-config.yaml`

---

### Component 2: Infrastructure Health Alerts (3 hours)

**2.1 Service Health**
- [ ] Prediction Worker crashes/restarts
- [ ] Coordinator timeouts (>5 minutes)
- [ ] High error rates (>5% of requests)
- [ ] Memory/CPU threshold breaches

**2.2 Circuit Breaker Monitoring**
- [ ] Circuit opens for any prediction system
- [ ] Circuit trips repeatedly (3+ times in 24h)
- [ ] Manual circuit override (alert team)

**2.3 Batch Loading Performance**
- [ ] Coordinator batch loading > 10s (Session 102 fix)
- [ ] Batch loading fails/fallback to sequential
- [ ] Player load counts drop significantly

**Deliverable:** `infrastructure-alerts-config.yaml`

---

### Component 3: Data Quality Alerts (2 hours)

**3.1 Feature Store Quality**
- [ ] Missing features (>5% NULL values)
- [ ] Feature staleness (no updates >24h)
- [ ] Feature value anomalies (out of range)

**3.2 Grading Coverage** (Already implemented!)
- ✅ Coverage <70% alert (Session 102)
- [ ] Coverage trend degrading
- [ ] Grading delays >36h

**3.3 Vegas Line Coverage**
- [ ] Vegas line coverage <60%
- [ ] Vegas line quality degrading
- [ ] Line movement anomalies

**Deliverable:** `data-quality-alerts-config.yaml`

---

### Component 4: Dashboards (2 hours)

**4.1 Real-Time Operations Dashboard**
- [ ] Service health status
- [ ] Recent prediction volume (24h)
- [ ] Latest MAE by model
- [ ] Circuit breaker states
- [ ] Current alert status

**4.2 Model Performance Dashboard**
- [ ] 7-day MAE trends
- [ ] Win rate by model
- [ ] Head-to-head comparisons
- [ ] Confidence calibration curves
- [ ] Feature importance stability

**4.3 Data Quality Dashboard**
- [ ] Feature completeness
- [ ] Grading coverage trends
- [ ] Vegas line availability
- [ ] Anomaly detection

**Deliverable:** Dashboard JSON configs + screenshots

---

### Component 5: Runbooks (2 hours)

**5.1 Performance Degradation Runbook**
- [ ] Symptoms: MAE spike, win rate drop
- [ ] Investigation steps
- [ ] Remediation actions
- [ ] Escalation path

**5.2 Infrastructure Failure Runbook**
- [ ] Symptoms: Service errors, timeouts
- [ ] Health check procedures
- [ ] Restart/rollback procedures
- [ ] Emergency contacts

**5.3 Circuit Breaker Response Runbook**
- [ ] When circuit opens
- [ ] Root cause analysis steps
- [ ] Model bypass procedures
- [ ] Circuit reset criteria

**5.4 Data Quality Issues Runbook**
- [ ] Missing features
- [ ] Stale data
- [ ] Grading delays
- [ ] Recovery procedures

**Deliverable:** `runbooks/*.md` (4 runbooks)

---

## 🛠️ Technical Implementation

### Alert Mechanisms

**Option 1: Cloud Monitoring Alerts** (Recommended)
- Native GCP integration
- Log-based metrics
- Email/Slack notifications
- Incident management integration

**Option 2: BigQuery Scheduled Queries**
- Custom metric computation
- Flexible analysis
- Export to monitoring
- Cost-effective

**Option 3: Cloud Functions**
- Complex logic support
- Custom integrations
- Event-driven
- Serverless

**Recommended Approach:** Hybrid
- Simple threshold alerts → Cloud Monitoring
- Complex analysis → Scheduled Queries + Cloud Functions
- Critical alerts → Multiple channels (email + Slack)

---

### Dashboard Platforms

**Option 1: Looker Studio** (Free, Recommended for MVP)
- Easy BigQuery integration
- Share with stakeholders
- Sufficient for Phase 5 needs

**Option 2: Grafana**
- More powerful
- Better real-time support
- Requires hosting

**Option 3: Custom Dashboard**
- Full control
- High maintenance
- Overkill for current needs

**Recommended:** Start with Looker Studio, migrate to Grafana if needed

---

## 📈 Alert Configuration Examples

### Model Performance Alert
```yaml
# model-mae-alert.yaml
name: "XGBoost V1 MAE Spike"
condition: |
  SELECT
    CASE
      WHEN AVG(absolute_error) > 4.2 THEN 'CRITICAL'
      WHEN AVG(absolute_error) > 4.0 THEN 'WARNING'
      ELSE 'OK'
    END as status
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id = 'xgboost_v1'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
duration: "3d"
notification_channels:
  - email: engineering@company.com
  - slack: #ml-alerts
severity: CRITICAL
documentation: "runbooks/performance-degradation.md"
```

### Infrastructure Health Alert
```yaml
# coordinator-timeout-alert.yaml
name: "Prediction Coordinator Timeout"
log_filter: |
  resource.type="cloud_run_revision"
  resource.labels.service_name="prediction-coordinator"
  severity="ERROR"
  textPayload=~"timeout|TimeoutError"
threshold: 5  # 5 errors in window
window: "15m"
notification_channels:
  - pagerduty: oncall
  - slack: #incidents
severity: CRITICAL
runbook: "runbooks/infrastructure-failure.md"
```

### Circuit Breaker Alert
```yaml
# circuit-breaker-alert.yaml
name: "Circuit Breaker Opened"
condition: |
  SELECT
    system_id,
    circuit_state,
    failure_count
  FROM `nba-props-platform.nba_predictions.prediction_circuit_breaker_state`
  WHERE circuit_state = 'OPEN'
notification_channels:
  - slack: #ml-alerts
  - email: ml-team@company.com
severity: WARNING
documentation: "runbooks/circuit-breaker-response.md"
auto_resolve: true
resolve_condition: "circuit_state = 'CLOSED'"
```

---

## 📊 Success Metrics

### Coverage
- ✅ All 6 models monitored
- ✅ All critical infrastructure components covered
- ✅ Data quality checks active
- ✅ 4 comprehensive runbooks created

### Response Time
- ✅ Mean time to detection (MTTD): <30 minutes
- ✅ Mean time to acknowledge (MTTA): <15 minutes
- ✅ Mean time to resolve (MTTR): <2 hours (non-critical)

### Reliability
- ✅ Zero false positives per day
- ✅ Zero missed incidents (silent failures)
- ✅ 100% alert delivery rate
- ✅ Clear escalation paths documented

---

## 🚀 Implementation Phases

### Phase 1: Critical Alerts (Week 1)
**Priority:** HIGH
- Model MAE spike alerts
- Service crash/timeout alerts
- Circuit breaker alerts
- Basic health dashboard

### Phase 2: Quality Alerts (Week 2)
**Priority:** MEDIUM
- Feature quality alerts
- Grading coverage enhancements
- Data freshness monitoring
- Model comparison dashboard

### Phase 3: Advanced Monitoring (Week 3)
**Priority:** LOW
- Confidence calibration drift
- Feature importance stability
- Prediction latency monitoring
- Comprehensive performance dashboard

### Phase 4: Operational Excellence (Week 4)
**Priority:** LOW
- Runbook refinement
- Team training
- Incident response drills
- Documentation updates

---

## 📝 Deliverables Checklist

### Configurations
- [ ] `model-alerts-config.yaml`
- [ ] `infrastructure-alerts-config.yaml`
- [ ] `data-quality-alerts-config.yaml`
- [ ] `alert-deployment-script.sh`

### Dashboards
- [ ] `operations-dashboard.json` (Looker Studio)
- [ ] `model-performance-dashboard.json`
- [ ] `data-quality-dashboard.json`
- [ ] Dashboard screenshots and links

### Runbooks
- [ ] `runbooks/performance-degradation.md`
- [ ] `runbooks/infrastructure-failure.md`
- [ ] `runbooks/circuit-breaker-response.md`
- [ ] `runbooks/data-quality-issues.md`

### Documentation
- [ ] `alert-catalog.md` (all alerts documented)
- [ ] `monitoring-architecture.md`
- [ ] `team-training-guide.md`

---

## 🔗 Related Documentation

- [Coordinator Optimization](../../coordinator-deployment-session-102.md) - Batch loading fix
- [Grading Coverage Alert](../../grading-coverage-alert-deployment.md) - Already implemented
- [Master Plan](../MASTER-PLAN.md)
- [Track A: Monitoring](../track-a-monitoring/README.md) - Model-specific monitoring

---

## 💡 Best Practices

### Alert Design
- **Actionable:** Every alert should have clear next steps
- **Relevant:** Focus on what matters, avoid alert fatigue
- **Documented:** Link to runbook in every alert
- **Tested:** Simulate alerts to verify they work

### Runbook Quality
- **Clear symptoms:** How to recognize the issue
- **Investigation steps:** Ordered list of diagnostic actions
- **Remediation:** Step-by-step fix procedures
- **Escalation:** When and how to escalate

### Dashboard Design
- **Glanceable:** Key metrics visible at a glance
- **Drill-down:** Ability to investigate deeper
- **Context:** Compare to baselines and targets
- **Fresh:** Real-time or near real-time updates

---

**Track Owner:** Engineering Team
**Created:** 2026-01-18
**Status:** Ready to Start
**Next Step:** Define critical alert specifications in `alert-specifications.md`
