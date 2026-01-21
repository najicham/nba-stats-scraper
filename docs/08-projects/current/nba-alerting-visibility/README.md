# NBA Alerting & Visibility Implementation

**Project Status**: 🟢 **WEEK 3 COMPLETE** - Full Visibility Stack
**Started**: 2026-01-17 (Session 81)
**Latest**: 2026-01-17 (Session 86) - Week 3 Dashboards & Visibility
**Priority**: HIGH
**Owner**: Platform Team

---

## Overview

Comprehensive alerting and visibility system for the NBA prediction platform to prevent incidents like the CatBoost V8 degradation (Jan 14-17, 2026).

**Goal**: Reduce detection time from 3 days to < 5 minutes for critical issues.

---

## Problem Statement

The [CatBoost V8 incident](../catboost-v8-jan-2026-incident/ROOT-CAUSE-ANALYSIS.md) exposed critical gaps in monitoring:
- Missing `CATBOOST_V8_MODEL_PATH` environment variable
- Service appeared healthy but predictions degraded for 3 days
- 1,071 failed predictions (50% confidence fallback)
- **No alerts triggered** - detected only through manual investigation

---

## Implementation Timeline

### Week 1: Critical Alerts ✅ **COMPLETE** (Session 81-82)
**Time**: 4 hours (vs 14 estimated)

**Alerts Deployed**:
1. `[CRITICAL] NBA Model Loading Failures` - Detects model loading errors
2. `[CRITICAL] NBA High Fallback Prediction Rate` - Detects > 10% fallback predictions

**Bonus**:
- Fixed deployment script root cause
- Added startup validation to prediction-worker

**Session Docs**:
- [Session 81 Handoff](./SESSION-81-WEEK1-STRATEGY.md)
- [Session 82 Complete](./SESSION-82-WEEK1-COMPLETE.md)

---

### Week 2: Warning Alerts + Full Automation ✅ **COMPLETE** (Session 83)
**Time**: 4 hours total (vs 12 estimated)

**Alerts Deployed** (all automated):
1. `[WARNING] NBA Stale Predictions` - Detects when predictions stop (2+ hours)
2. `[WARNING] NBA High DLQ Depth` - Detects message accumulation (> 50 messages)
3. `[WARNING] NBA Feature Pipeline Stale` - Detects stale features (> 4 hours) - **AUTOMATED**
4. `[WARNING] NBA Confidence Distribution Drift` - Detects unusual patterns (> 30% drift) - **AUTOMATED**

**Automation Infrastructure**:
- Cloud Run Jobs for monitoring scripts
- Cloud Scheduler running hourly and every 2 hours
- Log-based metrics triggering alerts
- 100% autonomous operation

**Session Docs**:
- [Session 83 Week 2 Alerts](./SESSION-83-WEEK2-ALERTS-COMPLETE.md)
- [Session 83 Full Complete](./SESSION-83-COMPLETE.md)

---

### Week 3: Dashboards & Visibility ✅ **COMPLETE** (Session 86)
**Time**: 2 hours (vs 10 estimated)

**Deployed**:
1. ✅ Cloud Monitoring Dashboard (7 panels)
2. ✅ Daily Prediction Summary to Slack (automated 9 AM daily)
3. ✅ Quick Status Script (14-second health check)
4. ✅ Cloud Run Job + Scheduler for daily summaries
5. ✅ Slack webhook setup guide

**Session Docs**:
- [Session 86 Week 3 Complete](./SESSION-86-WEEK3-COMPLETE.md)

---

### Week 4: Info Alerts & Polish ⏳ **PENDING**
**Estimated**: 4 hours (likely ~1 actual)

**Planned**:
1. Deployment notifications to Slack
2. Alert routing to separate channels
3. Final documentation and handoff

---

## Progress Summary

| Week | Focus | Est. Hours | Actual Hours | Status | Efficiency |
|------|-------|-----------|--------------|--------|------------|
| 1 | Critical Alerts | 14 | 4 | ✅ Complete | 71% saved |
| 2 | Warning Alerts + Automation | 12 | 4 | ✅ Complete | 67% saved |
| 3 | Dashboards & Visibility | 10 | 2 | ✅ Complete | 80% saved |
| 4 | Polish | 4 | - | ⏳ Optional | - |
| **TOTAL** | | **40** | **10** | 🟢 **75% Done** | **72% saved** |

---

## Current State (2026-01-17)

### Alerts Deployed: 6 (All Automated)

**Critical (Week 1)**:
- ✅ Model Loading Failures
- ✅ High Fallback Prediction Rate

**Warning (Week 2)**:
- ✅ Stale Predictions
- ✅ High DLQ Depth
- ✅ Feature Pipeline Stale (Cloud Scheduler - hourly)
- ✅ Confidence Distribution Drift (Cloud Scheduler - every 2 hours)

### Automation Infrastructure
- ✅ Cloud Run Jobs for monitoring scripts
- ✅ Cloud Scheduler running on schedule
- ✅ Log-based metrics triggering alerts
- ✅ 100% autonomous operation

### System Health
- ✅ All 6 alerts enabled and firing autonomously
- ✅ Slack notifications configured
- ✅ Comprehensive runbooks available
- ✅ Health check script for daily operations
- ✅ System validated and tested

---

## Key Documents

### Strategy & Planning
- [Alerting Strategy](../../../../04-deployment/ALERTING-AND-VISIBILITY-STRATEGY.md)
- [Implementation Roadmap](../../../../04-deployment/IMPLEMENTATION-ROADMAP.md)
- [Environment Variables](../../../../04-deployment/NBA-ENVIRONMENT-VARIABLES.md)

### Runbooks
- [Alert Runbooks](../../../../04-deployment/ALERT-RUNBOOKS.md) - Investigation & fix procedures

### Session Handoffs
- [Session 82 - Week 1 Complete](./SESSION-82-WEEK1-COMPLETE.md)
- [Session 83 - Week 2 Complete](./SESSION-83-WEEK2-ALERTS-COMPLETE.md)

### Scripts
- [Test Week 1 Alerts](../../../../bin/alerts/test_week1_alerts.sh)
- Health Check Script (coming in Week 3)

---

## Impact Metrics

### Detection Time Improvement

**Before (CatBoost V8 Incident)**:
- Detection: 3 days (manual)
- Impact: 1,071 degraded predictions

**After (With Weeks 1-2 Alerts)**:
- Detection: < 1 minute (automated)
- Improvement: **4,320x faster**

### Alert Coverage

| Issue Type | Before | After | Detection Time |
|------------|--------|-------|----------------|
| Model loading failure | ❌ None | ✅ CRITICAL | < 5 minutes |
| High fallback rate | ❌ None | ✅ CRITICAL | < 10 minutes |
| Stale predictions | ❌ None | ✅ WARNING | < 2 hours |
| DLQ accumulation | ❌ None | ✅ WARNING | < 30 minutes |
| Feature staleness | ❌ None | ⏳ Manual | Daily check |
| Confidence drift | ❌ None | ⏳ Manual | Weekly check |

---

## Cloud Resources

### Log-Based Metrics
- `nba_model_load_failures`
- `nba_fallback_predictions`
- `nba_prediction_generation_success`

### Alert Policies
- `[CRITICAL] NBA Model Loading Failures` (Policy: 8541589381414081516)
- `[CRITICAL] NBA High Fallback Prediction Rate`
- `[WARNING] NBA Stale Predictions` (Policy: 8541589381414081516)
- `[WARNING] NBA High DLQ Depth` (Policy: 16941161207807257955)

### Notification Channels
- Slack: `projects/nba-props-platform/notificationChannels/13444328261517403081`

---

## Quick Commands

### Check System Health
```bash
# Prediction freshness
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT MAX(created_at) as last_prediction,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), MINUTE) as minutes_ago
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"'

# DLQ depth
gcloud pubsub subscriptions describe prediction-request-dlq-sub \
  --project=nba-props-platform --format="value(numUndeliveredMessages)"

# Feature freshness
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT MAX(created_at) as last_feature,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_ago
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE()'
```

### List All Alerts
```bash
gcloud alpha monitoring policies list \
  --project=nba-props-platform \
  --format="table(displayName,enabled,conditions[0].displayName)"
```

---

## Related Projects

- [CatBoost V8 Incident](../catboost-v8-jan-2026-incident/) - Root cause that triggered this project
- [Monitoring Improvements](../monitoring-improvements/) - General monitoring work
- [Silent Failure Prevention](../silent-failure-prevention/) - Related reliability work

---

## Next Steps

### Immediate (Week 3)
1. ✅ Create unified health check script
2. ⏳ Automate Feature Pipeline Staleness alert
3. ⏳ Automate Confidence Distribution Drift alert
4. ⏳ Create Cloud Monitoring dashboard
5. ⏳ Set up daily summary to Slack

### Future (Week 4+)
1. Deployment notifications
2. Alert routing to separate channels
3. Full alert testing in production
4. Team training and handoff

---

**Last Updated**: 2026-01-17 (Session 83)
**Status**: Week 2 complete, Week 3 in progress
