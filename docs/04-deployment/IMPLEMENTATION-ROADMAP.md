# NBA Alerting & Visibility - Implementation Roadmap

**Created**: 2026-01-17
**Timeline**: 4 weeks
**Estimated Effort**: ~40 hours total
**Priority**: HIGH - Prevent repeat of CatBoost V8 incident

---

## 📅 WEEK-BY-WEEK PLAN

### Week 1: Critical Alerts & Documentation (14 hours)

**Goal**: Detect model loading and prediction quality issues within 5 minutes

#### Day 1: Monday (4 hours)
- ✅ **DONE**: Fix nba-monitoring-alerts Slack webhook
- ✅ **DONE**: Create NBA-ENVIRONMENT-VARIABLES.md
- ✅ **DONE**: Create ALERTING-AND-VISIBILITY-STRATEGY.md

#### Day 2: Tuesday (3 hours)
- [ ] **Create Model Loading Failure Alert**
  - Create log-based metric
  - Create alert policy
  - Test with intentional failure
  - Document in runbook

- [ ] **Create Fallback Prediction Alert**
  - Create log-based metric
  - Create alert policy
  - Test threshold (10%)

#### Day 3: Wednesday (3 hours)
- [ ] **Add Startup Validation to prediction-worker**
  - Implement `validate_critical_env_vars()` function
  - Add logging for missing vars
  - Deploy to staging
  - Test with missing env vars
  - Deploy to production

#### Day 4: Thursday (2 hours)
- [ ] **Create Confidence Distribution Anomaly Check**
  - Create BigQuery scheduled query
  - Set up Pub/Sub topic
  - Create Cloud Function for Slack notification
  - Test with historical data

#### Day 5: Friday (2 hours)
- [ ] **Test All Week 1 Alerts**
  - Simulate model loading failure
  - Simulate high fallback rate
  - Simulate missing env vars
  - Verify all alerts fire correctly
  - Document response times

**Deliverables**:
- ✅ 2 critical alerts operational
- ✅ Startup validation in production
- ✅ Confidence anomaly detection active
- ✅ Documentation complete

---

### Week 2: Warning Alerts & Health Checks (12 hours)

**Goal**: Detect configuration changes and GCS access issues

#### Day 1: Monday (4 hours)
- [ ] **Environment Variable Change Alert**
  - Create log-based metric on Cloud Audit Logs
  - Create alert policy
  - Format Slack message with details
  - Test with env var update

#### Day 2: Tuesday (4 hours)
- [ ] **Deep Health Check Endpoint**
  - Implement `/health/deep` endpoint
  - Test environment variables
  - Test model loading
  - Test GCS access
  - Test BigQuery access
  - Deploy to production

#### Day 3: Wednesday (2 hours)
- [ ] **Deep Health Check Monitoring**
  - Create uptime check (5-min interval)
  - Create alert for failures
  - Test with broken configuration

#### Day 4: Thursday (2 hours)
- [ ] **Documentation & Testing**
  - Update runbooks for new alerts
  - Test all Week 2 alerts
  - Create incident response flowchart

**Deliverables**:
- ✅ Environment change alerts active
- ✅ Deep health checks deployed
- ✅ 2 warning-level alerts operational

---

### Week 3: Dashboards & Visibility (10 hours)

**Goal**: Proactive visibility into service health

#### Day 1: Monday (4 hours)
- [ ] **Cloud Monitoring Dashboard**
  - Create custom dashboard
  - Add model loading success rate panel
  - Add fallback prediction rate panel
  - Add confidence distribution panel
  - Add predictions generated panel
  - Add service uptime panel

#### Day 2: Tuesday (3 hours)
- [ ] **Daily Prediction Summary**
  - Create BigQuery scheduled query (9 AM daily)
  - Set up Pub/Sub topic
  - Create Cloud Function for formatting
  - Send to Slack #predictions-summary
  - Test manually

#### Day 3: Wednesday (3 hours)
- [ ] **Configuration Audit Dashboard**
  - Create simple web page or Looker dashboard
  - Show required env vars status (✅/❌)
  - Show model file accessibility
  - Show recent deployments
  - Auto-refresh every 5 minutes

**Deliverables**:
- ✅ Monitoring dashboard operational
- ✅ Daily summaries being sent
- ✅ Configuration audit available

---

### Week 4: Info Alerts & Polish (4 hours)

**Goal**: Complete visibility and deployment tracking

#### Day 1: Monday (2 hours)
- [ ] **Deployment Notifications**
  - Create log sink for deployments
  - Create Cloud Function for formatting
  - Send to Slack #deployments
  - Include: service, revision, user, timestamp
  - Test with deployment

#### Day 2: Tuesday (1 hour)
- [ ] **Alert Routing Configuration**
  - Set up Slack channels (#alerts-critical, #alerts-warning)
  - Route alerts to correct channels
  - Test routing

#### Day 3: Wednesday (1 hour)
- [ ] **Documentation & Handoff**
  - Update all runbooks
  - Create quick reference guide
  - Record demo video (optional)
  - Hand off to operations team

**Deliverables**:
- ✅ All alerts operational
- ✅ All dashboards live
- ✅ Documentation complete
- ✅ Team trained

---

## 📊 PROGRESS TRACKING

### Overall Progress

| Week | Focus | Hours | Status | Completion |
|------|-------|-------|--------|------------|
| 1 | Critical Alerts | 14 | 🟡 In Progress | 21% (3/14h) |
| 2 | Warning Alerts | 12 | ⚪ Not Started | 0% |
| 3 | Dashboards | 10 | ⚪ Not Started | 0% |
| 4 | Info & Polish | 4 | ⚪ Not Started | 0% |
| **TOTAL** | **All** | **40** | **🟡** | **8%** |

### Tasks Completed (Session 81)

✅ **Day 1 Tasks**:
1. ✅ Fixed nba-monitoring-alerts (5 min)
2. ✅ Created NBA-ENVIRONMENT-VARIABLES.md (1.5 hours)
3. ✅ Created ALERTING-AND-VISIBILITY-STRATEGY.md (1 hour)
4. ✅ Created IMPLEMENTATION-ROADMAP.md (30 min)

**Total Time**: 3 hours
**Remaining**: 37 hours

---

## 🎯 SUCCESS CRITERIA

### After Week 1
- [ ] Model loading failures detected in < 5 minutes
- [ ] Fallback prediction rate monitored continuously
- [ ] Confidence distribution anomalies detected daily
- [ ] Startup validation prevents silent failures

### After Week 2
- [ ] Environment variable changes trigger alerts
- [ ] Deep health checks validate configuration
- [ ] All alerts have documented runbooks
- [ ] False positive rate < 5%

### After Week 3
- [ ] Dashboard shows real-time service health
- [ ] Daily summaries sent automatically
- [ ] Configuration state visible at a glance
- [ ] Historical trends tracked

### After Week 4
- [ ] All deployments logged and visible
- [ ] Alerts routed to correct channels
- [ ] Operations team trained
- [ ] Mean Time to Detection < 5 minutes

### Long-Term (3 months)
- [ ] Zero incidents like CatBoost V8 (3-day undetected degradation)
- [ ] Mean Time to Detection < 5 minutes (maintained)
- [ ] Mean Time to Resolution < 30 minutes
- [ ] Alert accuracy > 95%

---

## 💰 COST ESTIMATE

### Google Cloud Resources

| Resource | Monthly Cost | Notes |
|----------|-------------|-------|
| Log-based Metrics | ~$5 | 5 metrics × $0.50/metric |
| Cloud Monitoring Alerts | ~$2 | 8 alert policies × $0.25/policy |
| BigQuery Scheduled Queries | ~$1 | Daily queries, minimal data |
| Cloud Functions | ~$3 | Pub/Sub triggers, low volume |
| Uptime Checks | ~$1 | 1 check × 5-min interval |
| Dashboard Hosting | $0 | Cloud Monitoring (free) |
| **TOTAL** | **~$12/month** | Very affordable |

**ROI**: Preventing a single 3-day incident saves days of engineering time (>> $12)

---

## 🚀 QUICK START

Want to implement the most critical alert today?

### 5-Minute Quick Start: Model Loading Alert

```bash
# 1. Create log-based metric (1 min)
gcloud logging metrics create nba_model_load_failures \
  --project=nba-props-platform \
  --description="NBA model loading failures" \
  --log-filter='resource.type="cloud_run_revision"
    AND resource.labels.service_name="prediction-worker"
    AND severity>=ERROR
    AND textPayload=~"model FAILED to load"'

# 2. Get Slack notification channel ID (1 min)
CHANNEL_ID=$(gcloud alpha monitoring channels list \
  --project=nba-props-platform \
  --filter="displayName:Slack" \
  --format="value(name)" | head -1)

echo "Slack Channel ID: $CHANNEL_ID"

# 3. Create alert policy (2 min)
gcloud alpha monitoring policies create \
  --project=nba-props-platform \
  --notification-channels="$CHANNEL_ID" \
  --display-name="[CRITICAL] NBA Model Loading Failures" \
  --condition-display-name="Model failed to load" \
  --condition-threshold-value=1 \
  --condition-threshold-duration=300s \
  --aggregation-alignment-period=60s \
  --condition-threshold-filter='metric.type="logging.googleapis.com/user/nba_model_load_failures"'

# 4. Test it (1 min)
# Deploy prediction-worker without CATBOOST_V8_MODEL_PATH
# Alert should fire within 5 minutes
```

**Done!** You now have protection against the CatBoost V8 incident type.

---

## 📞 SUPPORT & QUESTIONS

### During Implementation

**Questions?** Ask in Slack #platform-team

**Issues?** Create ticket in Jira/GitHub

**Blocker?** Escalate to platform lead

### After Implementation

**Alert Firing?** Check runbook in ALERTING-AND-VISIBILITY-STRATEGY.md

**False Positive?** Adjust threshold, document in this file

**New Alert Needed?** Follow pattern in strategy doc

---

## 📚 RELATED DOCUMENTS

1. **Environment Variables**: `docs/04-deployment/NBA-ENVIRONMENT-VARIABLES.md`
2. **Alerting Strategy**: `docs/04-deployment/ALERTING-AND-VISIBILITY-STRATEGY.md`
3. **NBA Fix Todo**: `docs/08-projects/current/catboost-v8-jan-2026-incident/NBA-FOCUSED-FIX-TODO-LIST.md`
4. **Root Cause Analysis**: `docs/08-projects/current/catboost-v8-jan-2026-incident/ROOT-CAUSE-ANALYSIS.md`

---

## ✅ WEEKLY CHECKLIST

Copy this for each week's work:

### Week 1 Checklist
- [ ] Create model loading failure alert
- [ ] Create fallback prediction alert
- [ ] Add startup validation
- [ ] Create confidence anomaly check
- [ ] Test all alerts
- [ ] Update progress in this doc

### Week 2 Checklist
- [ ] Create env var change alert
- [ ] Implement deep health check
- [ ] Create uptime monitoring
- [ ] Update runbooks
- [ ] Update progress in this doc

### Week 3 Checklist
- [ ] Create Cloud Monitoring dashboard
- [ ] Set up daily summary
- [ ] Create config audit dashboard
- [ ] Update progress in this doc

### Week 4 Checklist
- [ ] Set up deployment notifications
- [ ] Configure alert routing
- [ ] Complete documentation
- [ ] Train operations team
- [ ] Mark project COMPLETE

---

**Last Updated**: 2026-01-17 (Session 81)
**Next Update**: After Week 1 completion
**Owner**: Platform Team
