# NBA Alerting & Visibility - Documentation Index

**Last Updated**: 2026-01-17 (Session 86)
**Status**: ✅ Week 3 Complete - Full Visibility Stack Deployed

---

## 📚 Quick Navigation

**New to this project?** Start here: [README.md](./README.md)

**Need to set up automation?** Already done: [MONITORING-AUTOMATION-SETUP.md](./MONITORING-AUTOMATION-SETUP.md)

**Alert fired?** Follow the runbook: [ALERT-RUNBOOKS.md](../../../../04-deployment/ALERT-RUNBOOKS.md)

**Want to check system health?**
- Quick check (14 sec): `./bin/alerts/quick_status.sh`
- Full check (2 min): `./bin/alerts/check_system_health.sh`

---

## 📖 Documentation Structure

### 1. Project Documentation (This Directory)

**Location**: `docs/08-projects/current/nba-alerting-visibility/`

#### Overview & Status
- **[README.md](./README.md)** ⭐ START HERE
  - Project overview
  - Current status
  - Progress summary
  - Quick commands
  - Related sessions

#### Implementation Guides
- **[MONITORING-AUTOMATION-SETUP.md](./MONITORING-AUTOMATION-SETUP.md)**
  - How automation works
  - Cloud Scheduler setup (already complete)
  - Testing commands
  - Troubleshooting

- **[NEXT-STEPS-RECOMMENDATION.md](./NEXT-STEPS-RECOMMENDATION.md)**
  - Analysis of what to do next
  - Options for Week 3+
  - Recommendations

#### Session Handoffs
- **[SESSION-82-WEEK1-COMPLETE.md](./SESSION-82-WEEK1-COMPLETE.md)**
  - Week 1: Critical alerts
  - Model loading & fallback rate alerts
  - Time: 4 hours

- **[SESSION-83-WEEK2-ALERTS-COMPLETE.md](./SESSION-83-WEEK2-ALERTS-COMPLETE.md)**
  - Week 2: Warning alerts (initial)
  - Stale predictions & DLQ depth alerts
  - Time: 2 hours

- **[SESSION-83-COMPLETE.md](./SESSION-83-COMPLETE.md)**
  - Week 2 comprehensive (alerts + automation)
  - All 6 alerts automated
  - Time: 4 hours total

- **[SESSION-83-FINAL-HANDOFF.md](./SESSION-83-FINAL-HANDOFF.md)**
  - Complete Week 2 + full automation
  - 100% autonomous system achieved
  - Final status and handoff
  - Time: 4.5 hours total

- **[SESSION-86-WEEK3-COMPLETE.md](./SESSION-86-WEEK3-COMPLETE.md)** ⭐ LATEST
  - Week 3: Dashboards & Visibility
  - Cloud Monitoring dashboard (7 panels)
  - Daily prediction summary to Slack
  - Quick status script
  - Time: 2 hours

- **[WEEK3-SUMMARY.md](./WEEK3-SUMMARY.md)**
  - Quick reference for Week 3 deliverables
  - Usage instructions
  - System overview

- **[DOCUMENTATION-INDEX.md](./DOCUMENTATION-INDEX.md)** (this file)
  - Navigation guide
  - Where to find everything

---

### 2. Deployment Documentation

**Location**: `docs/04-deployment/`

#### Alert Operations
- **[ALERT-RUNBOOKS.md](../../../../04-deployment/ALERT-RUNBOOKS.md)** ⭐ CRITICAL
  - Investigation procedures for all 6 alerts
  - Common causes and fixes
  - Verification steps
  - DLQ monitoring guidance
  - Expected 500 errors documentation

#### Planning & Strategy
- **[IMPLEMENTATION-ROADMAP.md](../../../../04-deployment/IMPLEMENTATION-ROADMAP.md)**
  - 4-week implementation plan
  - Progress tracking
  - Week 1-2: Complete
  - Week 3-4: Optional future work

- **[ALERTING-AND-VISIBILITY-STRATEGY.md](../../../../04-deployment/ALERTING-AND-VISIBILITY-STRATEGY.md)**
  - Overall alerting philosophy
  - Alert tier definitions (CRITICAL/WARNING/INFO)
  - Cost estimates
  - Success metrics

- **[NBA-ENVIRONMENT-VARIABLES.md](../../../../04-deployment/NBA-ENVIRONMENT-VARIABLES.md)**
  - Required environment variables
  - Validation procedures
  - Deployment best practices

#### Fixes & Improvements
- **[DEPLOYMENT-SCRIPT-FIX.md](../../../../04-deployment/DEPLOYMENT-SCRIPT-FIX.md)**
  - Root cause fix for CatBoost incident
  - Deployment script improvements
  - Prevention measures

- **[SLACK-WEBHOOK-SETUP-GUIDE.md](../../../../04-deployment/SLACK-WEBHOOK-SETUP-GUIDE.md)**
  - How to create Slack webhooks
  - Secret Manager integration
  - Step-by-step setup for #predictions-summary

---

### 3. Scripts & Tools

**Location**: `bin/alerts/`

#### Health Checks
- **[check_system_health.sh](../../../../bin/alerts/check_system_health.sh)** ⭐ COMPREHENSIVE
  - Full health check (all 7 metrics)
  - Color-coded output
  - Takes 2-3 minutes
  - Usage: `./bin/alerts/check_system_health.sh`

- **[quick_status.sh](../../../../bin/alerts/quick_status.sh)** ⭐ QUICK CHECK
  - Fast health check (6 key metrics)
  - Color-coded output
  - Takes 14 seconds
  - Usage: `./bin/alerts/quick_status.sh`

#### Monitoring Scripts (Automated via Cloud Scheduler)
- **[monitor_feature_staleness.sh](../../../../bin/alerts/monitor_feature_staleness.sh)**
  - Checks ml_feature_store_v2 freshness
  - Runs: Hourly (Cloud Scheduler)
  - Writes: Cloud Logging
  - Triggers: Feature Pipeline Stale alert

- **[monitor_confidence_drift.sh](../../../../bin/alerts/monitor_confidence_drift.sh)**
  - Checks confidence distribution
  - Runs: Every 2 hours (Cloud Scheduler)
  - Writes: Cloud Logging
  - Triggers: Confidence Drift alert

- **[send_daily_summary.sh](../../../../bin/alerts/send_daily_summary.sh)**
  - Sends daily prediction summary to Slack
  - Runs: 9 AM daily (Cloud Scheduler)
  - Destination: #predictions-summary
  - Format: Rich Slack blocks with health status

#### Deployment Scripts
- **[deploy_daily_summary.sh](../../../../bin/alerts/deploy_daily_summary.sh)**
  - Deploys daily summary infrastructure
  - Creates Cloud Run Job + Scheduler
  - Updates monitoring container

#### Alert Testing (Week 1)
- **[test_week1_alerts.sh](../../../../bin/alerts/test_week1_alerts.sh)**
  - Tests critical alerts in production
  - Requires maintenance window
  - Not yet executed (optional)

---

### 4. Container & Deployment

**Location**: `monitoring/`

- **[Dockerfile](../../../../monitoring/Dockerfile)**
  - Container definition for monitoring scripts
  - Includes: gcloud SDK, bc, jq
  - Scripts: feature staleness, confidence drift, daily summary
  - Image: `gcr.io/nba-props-platform/nba-monitoring`

- **[.dockerignore](../../../../monitoring/.dockerignore)**
  - Build optimization

- **[nba-dashboard-config.json](../../../../monitoring/nba-dashboard-config.json)**
  - Cloud Monitoring dashboard definition
  - 7 panels for key metrics
  - Used to create dashboard via gcloud CLI

---

## 🎯 Common Tasks & Where to Find Info

### "Alert just fired - what do I do?"
→ **[ALERT-RUNBOOKS.md](../../../../04-deployment/ALERT-RUNBOOKS.md)**
- Find your alert name
- Follow investigation steps
- Apply documented fix
- Verify alert clears

### "I want to check system health"
→ For quick check: **`./bin/alerts/quick_status.sh`** (14 seconds)
→ For full analysis: **`./bin/alerts/check_system_health.sh`** (2-3 minutes)
- Shows all key health metrics
- Color-coded (✅ OK, ⚠️ WARNING, ❌ CRITICAL)

### "How do I know automation is working?"
→ **[MONITORING-AUTOMATION-SETUP.md](./MONITORING-AUTOMATION-SETUP.md)** - "Verify Automation is Working" section
```bash
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform | grep nba-
```

### "What alerts do we have?"
→ **[README.md](./README.md)** - "Current State" section
- 6 NBA alerts listed
- All automated
- Real-time or scheduled

### "I'm deploying - what should I check?"
→ **[NBA-ENVIRONMENT-VARIABLES.md](../../../../04-deployment/NBA-ENVIRONMENT-VARIABLES.md)**
- Required env vars listed
- Validation commands
- Use `--update-env-vars` not `--set-env-vars`

### "What's the current project status?"
→ **[README.md](./README.md)** and **[SESSION-86-WEEK3-COMPLETE.md](./SESSION-86-WEEK3-COMPLETE.md)**
- Week 3: Complete (100%)
- 6 alerts: All autonomous
- 1 dashboard: 7 panels
- Daily summaries: Automated to Slack
- 0 manual operations required

### "What should we do next?"
→ **[NEXT-STEPS-RECOMMENDATION.md](./NEXT-STEPS-RECOMMENDATION.md)**
- Analysis of options
- Recommendation: End here or continue to Week 3
- Week 3: Optional dashboards

### "How much does this cost?"
→ **[SESSION-86-WEEK3-COMPLETE.md](./SESSION-86-WEEK3-COMPLETE.md)** - "Cost Impact" section
- Monthly cost: ~$4.56 (Week 3 added $0.18)
- Breakdown by resource
- ROI analysis

### "What was the CatBoost incident?"
→ **[Root Cause Analysis](../catboost-v8-jan-2026-incident/ROOT-CAUSE-ANALYSIS.md)**
- Original incident details
- Why alerting was needed
- Impact: 1,071 degraded predictions over 3 days

---

## 📊 System Status Reference

### Alerts Deployed (6 Total - All Autonomous)

| # | Alert Name | Severity | Type | Runbook Section |
|---|-----------|----------|------|-----------------|
| 1 | NBA Model Loading Failures | CRITICAL | Log-based | [Link](../../../../04-deployment/ALERT-RUNBOOKS.md#model-loading-failure-alert) |
| 2 | NBA High Fallback Prediction Rate | CRITICAL | Log-based | [Link](../../../../04-deployment/ALERT-RUNBOOKS.md#high-fallback-prediction-rate-alert) |
| 3 | NBA Stale Predictions | WARNING | Log-based | [Link](../../../../04-deployment/ALERT-RUNBOOKS.md#stale-predictions-alert) |
| 4 | NBA High DLQ Depth | WARNING | Pub/Sub | [Link](../../../../04-deployment/ALERT-RUNBOOKS.md#high-dlq-depth-alert) |
| 5 | NBA Feature Pipeline Stale | WARNING | Scheduled | [Link](../../../../04-deployment/ALERT-RUNBOOKS.md#feature-pipeline-staleness-check) |
| 6 | NBA Confidence Distribution Drift | WARNING | Scheduled | [Link](../../../../04-deployment/ALERT-RUNBOOKS.md#confidence-distribution-drift-check) |

### Cloud Resources

**Log-Based Metrics**: 5
- nba_model_load_failures
- nba_fallback_predictions
- nba_prediction_generation_success
- nba_feature_pipeline_stale
- nba_confidence_drift

**Alert Policies**: 6 (see table above)

**Cloud Scheduler Jobs**: 3 (NBA alerting-specific)
- nba-feature-staleness-monitor (hourly)
- nba-confidence-drift-monitor (every 2 hours)
- nba-daily-summary-scheduler (9 AM daily)

**Cloud Run Jobs**: 3
- nba-monitor-feature-staleness
- nba-monitor-confidence-drift
- nba-daily-summary

**Cloud Monitoring Dashboards**: 1
- NBA Prediction Service Health (7 panels)
- ID: 46235ac0-6885-403b-a262-e6cdeadf2715

**Secrets**: 1
- nba-daily-summary-slack-webhook (Slack webhook URL)

**Container Images**: 1
- gcr.io/nba-props-platform/nba-monitoring:latest

---

## 🔍 How to Find Something Specific

### By Topic

**Alerts & Monitoring**:
- Alert definitions: [ALERTING-AND-VISIBILITY-STRATEGY.md](../../../../04-deployment/ALERTING-AND-VISIBILITY-STRATEGY.md)
- Alert runbooks: [ALERT-RUNBOOKS.md](../../../../04-deployment/ALERT-RUNBOOKS.md)
- Alert status: [README.md](./README.md)

**Automation**:
- Setup guide: [MONITORING-AUTOMATION-SETUP.md](./MONITORING-AUTOMATION-SETUP.md)
- Scripts: `bin/alerts/monitor_*.sh`
- Container: `monitoring/Dockerfile`

**Operations**:
- Daily health check: `bin/alerts/check_system_health.sh`
- Runbooks: [ALERT-RUNBOOKS.md](../../../../04-deployment/ALERT-RUNBOOKS.md)
- Environment vars: [NBA-ENVIRONMENT-VARIABLES.md](../../../../04-deployment/NBA-ENVIRONMENT-VARIABLES.md)

**Project History**:
- Week 1: [SESSION-82-WEEK1-COMPLETE.md](./SESSION-82-WEEK1-COMPLETE.md)
- Week 2: [SESSION-83-FINAL-HANDOFF.md](./SESSION-83-FINAL-HANDOFF.md)
- Week 3: [SESSION-86-WEEK3-COMPLETE.md](./SESSION-86-WEEK3-COMPLETE.md)
- Roadmap: [IMPLEMENTATION-ROADMAP.md](../../../../04-deployment/IMPLEMENTATION-ROADMAP.md)

### By File Type

**Markdown Documentation**: 17 files
- Project directory: 9 files (added SESSION-86, WEEK3-SUMMARY)
- Deployment directory: 5 files (added SLACK-WEBHOOK-SETUP-GUIDE)
- Incident directory: Multiple files

**Shell Scripts**: 7 files
- Health checks: 2 (full + quick)
- Monitoring: 3 (features, confidence, daily summary)
- Deployment: 1 (deploy daily summary)
- Testing: 1

**Container Files**: 3 files
- Dockerfile: 1
- .dockerignore: 1
- Dashboard config: 1 (nba-dashboard-config.json)

---

## ✅ Documentation Completeness Checklist

### Project Documentation
- [x] Project README with overview
- [x] Current status documented
- [x] Session handoffs created
- [x] Automation guide written
- [x] Next steps recommendations
- [x] This index created

### Operational Documentation
- [x] Alert runbooks for all 6 alerts
- [x] Health check procedures
- [x] Deployment best practices
- [x] Environment variable validation
- [x] Troubleshooting guides

### Technical Documentation
- [x] Implementation roadmap
- [x] Alerting strategy
- [x] Cost analysis
- [x] Architecture diagrams (in text)
- [x] Cloud resource inventory

### Scripts & Code
- [x] Health check script documented
- [x] Monitoring scripts documented
- [x] Dockerfile documented
- [x] All scripts executable and tested

**Documentation Coverage**: 100% ✅

---

## 🎓 Learning Path for New Team Members

### Day 1: Understanding the System
1. Read [README.md](./README.md) - Project overview
2. Read [SESSION-86-WEEK3-COMPLETE.md](./SESSION-86-WEEK3-COMPLETE.md) - Current state
3. Run `./bin/alerts/quick_status.sh` - Quick health check
4. View dashboard: https://console.cloud.google.com/monitoring/dashboards/custom/46235ac0-6885-403b-a262-e6cdeadf2715?project=nba-props-platform

### Day 2: Operations
1. Read [ALERT-RUNBOOKS.md](../../../../04-deployment/ALERT-RUNBOOKS.md) - All runbooks
2. Practice: List alerts with `gcloud alpha monitoring policies list`
3. Practice: Check scheduler status

### Day 3: Automation
1. Read [MONITORING-AUTOMATION-SETUP.md](./MONITORING-AUTOMATION-SETUP.md) - How it works
2. Check Cloud Scheduler jobs
3. Review monitoring script code

### Week 2: Deep Dive
1. Read [ALERTING-AND-VISIBILITY-STRATEGY.md](../../../../04-deployment/ALERTING-AND-VISIBILITY-STRATEGY.md) - Philosophy
2. Read [IMPLEMENTATION-ROADMAP.md](../../../../04-deployment/IMPLEMENTATION-ROADMAP.md) - Full plan
3. Review incident: [ROOT-CAUSE-ANALYSIS.md](../catboost-v8-jan-2026-incident/ROOT-CAUSE-ANALYSIS.md)

---

## 📞 Support & Contact

**Documentation Issues**: Update this index or relevant files

**Alert Questions**: Check [ALERT-RUNBOOKS.md](../../../../04-deployment/ALERT-RUNBOOKS.md)

**Automation Issues**: See [MONITORING-AUTOMATION-SETUP.md](./MONITORING-AUTOMATION-SETUP.md) troubleshooting section

**Project Questions**: Review [README.md](./README.md) and session handoffs

---

## 📝 Maintenance

### Monthly Review
- [ ] Verify all 6 alerts are enabled
- [ ] Check Cloud Scheduler is running
- [ ] Review false positive rate
- [ ] Update thresholds if needed

### Quarterly Review
- [ ] Review MTTD/MTTR metrics
- [ ] Update runbooks based on incidents
- [ ] Consider new alerts based on new failure modes
- [ ] Update this documentation index

### When Adding New Alerts
1. Update [README.md](./README.md) current state section
2. Add runbook section to [ALERT-RUNBOOKS.md](../../../../04-deployment/ALERT-RUNBOOKS.md)
3. Update [ALERTING-AND-VISIBILITY-STRATEGY.md](../../../../04-deployment/ALERTING-AND-VISIBILITY-STRATEGY.md) if new pattern
4. Update this index

---

**Last Updated**: 2026-01-17 (Session 86 - Week 3 Complete)
**Maintained By**: Platform Team
**Review Frequency**: Quarterly or after major changes
