# Emergency Runbooks Index

**Created:** 2026-01-03 (Session 6)
**Purpose:** Quick access to emergency procedures and disaster recovery

---

## 🚨 EMERGENCY - START HERE

**If you're here during an emergency, use this quick triage:**

### 1. Identify the Problem
- [ ] **Complete system down** → Use [Complete Outage](#complete-system-outage)
- [ ] **Data missing/corrupted** → Use [Data Loss](#data-loss-scenarios)
- [ ] **Service failures** → Use [Service Failures](#service-failures)
- [ ] **Security incident** → Use [Security Incident](#security-incident)

### 2. Get Help
```
On-Call Engineer:    [PHONE] [EMAIL]
Team Lead:           [PHONE] [EMAIL]
Engineering Manager: [PHONE] [EMAIL]
Slack:               #nba-incidents
```

### 3. Quick Commands
```bash
# System status
./bin/operations/ops_dashboard.sh quick

# Stop all data ingestion (EMERGENCY)
sched-pause-all  # or source bin/operations/ops_aliases.sh first

# View recent errors
nba-errors
```

---

## 📚 EMERGENCY RUNBOOKS

### Disaster Recovery

| Runbook | Severity | Recovery Time | Use When |
|---------|----------|---------------|----------|
| [DR Quick Reference](DR-QUICK-REFERENCE.md) | P0-P2 | 1-8 hours | Any disaster scenario |
| [Complete DR Runbook](../../disaster-recovery-runbook.md) | P0-P2 | 1-8 hours | Detailed recovery procedures |

**Disaster Scenarios Covered:**
1. BigQuery dataset loss (2-4 hours)
2. GCS bucket corruption (1-2 hours)
3. Firestore state loss (30-60 min)
4. Complete system outage (4-8 hours)
5. Phase processor failures (1-3 hours)

### System Failures

| Issue | Runbook | First Steps |
|-------|---------|-------------|
| **Complete Outage** | [DR Runbook](../../disaster-recovery-runbook.md#dr-scenario-4-complete-system-outage) | Assess scope, redeploy infrastructure |
| **Pipeline Stuck** | [Troubleshooting Guide](../../troubleshooting.md) | Check ops dashboard, review logs |
| **Workflow Failures** | [Orchestrator Monitoring](../../orchestrator-monitoring.md) | Check workflow status, review Firestore state |
| **Data Not Flowing** | [Troubleshooting Matrix](../../troubleshooting-matrix.md) | Verify pub/sub, check processors |

### Data Loss Scenarios

| Data Lost | Recovery Method | Runbook Section |
|-----------|----------------|-----------------|
| **BigQuery tables** | Restore from backups or rebuild from GCS | [DR Scenario 1](../../disaster-recovery-runbook.md#dr-scenario-1-bigquery-dataset-loss) |
| **GCS files** | Restore from versioning or backup bucket | [DR Scenario 2](../../disaster-recovery-runbook.md#dr-scenario-2-gcs-bucket-corruption) |
| **Firestore state** | Rebuild from BigQuery/logs | [DR Scenario 3](../../disaster-recovery-runbook.md#dr-scenario-3-firestore-state-loss) |
| **Specific dates** | Re-run processors for those dates | [DR Scenario 5](../../disaster-recovery-runbook.md#dr-scenario-5-phase-processor-failures) |

### Service Failures

| Service | Troubleshooting Steps | Related Runbooks |
|---------|----------------------|------------------|
| **Cloud Run services** | Check logs, verify IAM, check quotas | [Troubleshooting Guide](../../troubleshooting.md) |
| **Cloud Functions** | Check logs, verify triggers, check code | [Orchestrator Monitoring](../../orchestrator-monitoring.md) |
| **Cloud Scheduler** | Verify enabled, check IAM, test manually | [Troubleshooting Matrix](../../troubleshooting-matrix.md) |
| **Pub/Sub** | Check subscriptions, verify DLQ, check quotas | [PubSub Operations](../../pubsub-operations.md) |
| **BigQuery** | Check quotas, verify IAM, check table existence | [DR Runbook](../../disaster-recovery-runbook.md) |

### Security Incident

| Incident Type | Response | Runbook |
|---------------|----------|---------|
| **Unauthorized access** | Disable account, review logs, notify team | [Security Quick Ref](../../../07-security/security-compliance-quick-reference.md#security-incidents) |
| **Data breach** | Stop pipeline, assess damage, contain, notify | [Security Quick Ref](../../../07-security/security-compliance-quick-reference.md#security-incidents) |
| **Compromised credentials** | Rotate secrets, audit access, redeploy | [Security Quick Ref](../../../07-security/security-compliance-quick-reference.md#secrets-management) |
| **Suspicious activity** | Review audit logs, check IAM changes | [Security Quick Ref](../../../07-security/security-compliance-quick-reference.md#security-monitoring) |

---

## 🔧 OPERATIONAL RUNBOOKS

### Daily Operations

| Runbook | Purpose | Frequency |
|---------|---------|-----------|
| [Daily Operations](../../daily-operations-runbook.md) | Morning health checks, routine tasks | Daily |
| [Daily Monitoring](../../daily-monitoring.md) | Data quality checks, pipeline health | Daily |
| [Daily Validation](../../daily-validation-checklist.md) | Validation procedures | Daily |

### Incident Response

| Runbook | Use When |
|---------|----------|
| [Incident Response Guide](../../incident-response.md) | Any production incident |
| [DLQ Recovery](../../dlq-recovery.md) | Dead letter queue processing |
| [Orchestrator Monitoring](../../orchestrator-monitoring.md) | Phase transition issues |

### Backfill Operations

| Runbook | Use When |
|---------|----------|
| [Backfill Operations](../backfill/) | Historical data backfill needed |
| [Phase 4 Precompute Backfill](../backfill/) | Phase 4 specific backfill |
| [Completeness Runbook](../completeness/) | Data completeness validation |

### Prediction Pipeline

| Runbook | Use When |
|---------|----------|
| [Prediction Pipeline](../prediction-pipeline.md) | Prediction issues or deployment |
| [Trends Export](../trends-export.md) | Export and publishing issues |

---

## ⚡ QUICK REFERENCE CARDS

**One-page emergency cards for common scenarios:**

1. **[DR Quick Reference](DR-QUICK-REFERENCE.md)** - Disaster recovery commands
2. **[Security Quick Ref](../../../07-security/security-compliance-quick-reference.md)** - Security procedures
3. **[Ops Aliases](../../../../bin/operations/ops_aliases.sh)** - Command shortcuts

---

## 🎯 DECISION TREE

**Use this flowchart to find the right runbook:**

```
START: Is there an emergency?
│
├─ YES → What's affected?
│  │
│  ├─ Data Loss
│  │  ├─ BigQuery → DR Scenario 1
│  │  ├─ GCS → DR Scenario 2
│  │  └─ Firestore → DR Scenario 3
│  │
│  ├─ System Down
│  │  ├─ Complete outage → DR Scenario 4
│  │  ├─ Specific service → Troubleshooting Guide
│  │  └─ Pipeline stuck → Orchestrator Monitoring
│  │
│  ├─ Security Issue
│  │  ├─ Breach/unauthorized → Security Incident Response
│  │  └─ Suspicious activity → Security Monitoring
│  │
│  └─ Data Quality Issue
│     ├─ Missing data → DR Scenario 5
│     ├─ Bad data → Daily Validation
│     └─ Stale data → Troubleshooting Matrix
│
└─ NO → What do you need?
   │
   ├─ Daily Tasks → Daily Operations Runbook
   ├─ Backfill Data → Backfill Operations
   ├─ Monitor System → Daily Monitoring
   └─ Deploy Changes → (See deployment docs)
```

---

## 📞 CONTACT INFORMATION

### Escalation Path

| Level | Contact | Response Time | When to Escalate |
|-------|---------|---------------|------------------|
| **L1** | On-call Engineer | Immediate | First contact for any incident |
| **L2** | Team Lead | <15 min | L1 needs help or P1/P0 incident |
| **L3** | Engineering Manager | <30 min | Data loss, security breach, multiple failures |
| **L4** | VP Engineering | <1 hour | Complete outage, customer impact, legal issues |

### Communication Channels

```
Primary:   Slack #nba-incidents
Secondary: Email distribution list
Emergency: Phone tree (see contact list)
```

### External Support

```
GCP Support:     https://console.cloud.google.com/support
                 Phone: 1-877-355-5787 (P1 incidents)

Security:        security@company.com
Legal:          legal@company.com
```

---

## 🔍 FINDING THE RIGHT RUNBOOK

### By Symptom

| Symptom | Likely Cause | Runbook |
|---------|--------------|---------|
| No data in BigQuery | Dataset deleted, table dropped | DR Scenario 1 |
| GCS files missing | Bucket corruption, accidental deletion | DR Scenario 2 |
| Pipeline not progressing | Firestore state corrupted, orchestrator failure | DR Scenario 3, Orchestrator Monitoring |
| All services down | Infrastructure failure, GCP outage | DR Scenario 4 |
| Data gaps for specific dates | Processor failure, scraper issues | DR Scenario 5 |
| Alerts firing | Check ops dashboard, review logs | Daily Monitoring |
| High error rate | Service degradation, API issues | Troubleshooting Guide |

### By Severity

| Severity | Response Time | Examples | Runbooks |
|----------|---------------|----------|----------|
| **P0 - Critical** | Immediate | Complete outage, data loss, security breach | All DR scenarios |
| **P1 - High** | <15 min | Partial outage, major data corruption | DR Scenarios, Incident Response |
| **P2 - Medium** | <1 hour | Single service failure, data gaps | Troubleshooting, Orchestrator Monitoring |
| **P3 - Low** | <4 hours | Non-critical warnings, performance issues | Daily Operations, Monitoring |

### By Component

| Component | Runbooks |
|-----------|----------|
| **Phase 1-2 (Scrapers/Raw)** | Troubleshooting Matrix, DLQ Recovery |
| **Phase 3 (Analytics)** | Daily Validation, DR Scenario 5 |
| **Phase 4 (Precompute)** | Backfill Operations, DR Scenario 5 |
| **Phase 5 (Predictions)** | Prediction Pipeline Runbook |
| **Orchestration** | Orchestrator Monitoring, PubSub Operations |
| **Infrastructure** | DR Scenario 4, Troubleshooting Guide |

---

## 📋 RUNBOOK CHECKLIST

**Before using any emergency runbook:**

- [ ] Identify severity level (P0-P3)
- [ ] Notify team via #nba-incidents
- [ ] Run ops dashboard for current state: `./bin/operations/ops_dashboard.sh`
- [ ] Document incident start time
- [ ] Follow runbook procedures step-by-step
- [ ] Document all actions taken
- [ ] Create post-mortem after resolution

**After using emergency runbook:**

- [ ] Verify system recovery: `nba-status`
- [ ] Run validation: `nba-dash`
- [ ] Monitor for 24 hours
- [ ] Create incident report in `docs/incidents/`
- [ ] Update runbook if gaps found
- [ ] Schedule team debrief

---

## 🔄 RUNBOOK MAINTENANCE

### Review Schedule

- **Weekly:** Quick scan of emergency runbooks for accuracy
- **Monthly:** Test one runbook procedure
- **Quarterly:** Full runbook review and updates
- **After incidents:** Update based on lessons learned

### Improvement Process

1. **Identify gap:** During incident or drill
2. **Document issue:** In runbook comments or GitHub issue
3. **Propose fix:** Update runbook draft
4. **Test update:** Validate with team
5. **Merge update:** Update runbook and notify team
6. **Track version:** Update version history in runbook

### Version Control

All runbooks are version-controlled in git. See version history in each runbook's footer.

---

## 📚 ADDITIONAL RESOURCES

### Core Documentation

- **Architecture:** `docs/01-architecture/`
- **Operations:** `docs/02-operations/`
- **Monitoring:** `docs/07-monitoring/`
- **Security:** `docs/07-security/`

### Tools & Dashboards

- **Ops Dashboard:** `./bin/operations/ops_dashboard.sh`
- **Monitoring CLI:** `python3 monitoring/scripts/nba-monitor`
- **BigQuery Queries:** `bin/operations/monitoring_queries.sql`
- **Shell Aliases:** `source bin/operations/ops_aliases.sh`

### Training & Drills

- **DR Drill Schedule:** Quarterly (see Production Readiness Assessment)
- **Incident Response Training:** (To be scheduled)
- **Runbook Certification:** (To be implemented)

---

## 🆘 REMEMBER

**During emergencies:**
1. ⏸️ **STOP** - Take a breath, don't panic
2. 🔍 **ASSESS** - Run ops dashboard, understand scope
3. 📞 **NOTIFY** - Alert team via #nba-incidents
4. 📖 **FOLLOW** - Use runbook procedures step-by-step
5. 📝 **DOCUMENT** - Record all actions taken
6. ✅ **VERIFY** - Validate recovery before declaring resolved
7. 📊 **LEARN** - Post-mortem and runbook updates

**Emergency mantra:** "Slow is smooth, smooth is fast"

---

**Last Updated:** 2026-01-03 (Session 6)
**Next Review:** 2026-02-03 (30 days)
**Owner:** Operations Team
