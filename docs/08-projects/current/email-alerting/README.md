# Email Alerting System Enhancement Project

**Created:** 2025-11-30
**Status:** IN PROGRESS
**Priority:** High

---

## Overview

Migrate email alerting from Brevo to AWS SES and implement comprehensive email notifications across all pipeline phases. This provides operational visibility through proactive alerts rather than only error notifications.

## Background

Previous state:
- Email alerts only sent on errors (reactive)
- Using Brevo SMTP (limited scalability)
- No daily health summaries
- No prediction completion notifications
- No backfill progress visibility

New capabilities:
- AWS SES integration (50,000 emails/day capacity)
- 10 distinct email types with unique emoji identifiers
- Proactive daily health summaries
- Prediction completion reports
- Backfill progress tracking

---

## Email Types Summary

| Emoji | Method | Type | Trigger |
|-------|--------|------|---------|
| 🚨 | `send_error_alert()` | CRITICAL | Processor exception |
| ⚠️ | `send_unresolved_players_alert()` | WARNING | Unresolved count > threshold |
| 📊 | `send_daily_summary()` | INFO | Daily stats summary |
| 🆕 | `send_new_players_discovery_alert()` | INFO | New players found |
| ✅ | `send_pipeline_health_summary()` | INFO | Daily health check |
| 🏀 | `send_prediction_completion_summary()` | INFO | Phase 5 complete |
| ⏳ | `send_dependency_stall_alert()` | WARNING | Phase waiting > 30 min |
| 📦 | `send_backfill_progress_report()` | INFO | Backfill milestones |
| 📉 | `send_data_quality_alert()` | WARNING | Quality degradation |
| 🕐 | `send_stale_data_warning()` | WARNING | Upstream data > 24h old |

---

## Deliverables

### Phase 1: AWS SES Setup (COMPLETE)
- [x] AWS SES domain verification (989.ninja)
- [x] IAM credentials configured
- [x] `email_alerting_ses.py` module created
- [x] `notification_system.py` updated for SES-first fallback
- [x] boto3 added to requirements.txt
- [x] Test script created (`tests/test_ses_email.py`)

### Phase 2: New Email Types (COMPLETE)
- [x] Pipeline Health Summary (✅)
- [x] Prediction Completion Summary (🏀)
- [x] Dependency Stall Alert (⏳)
- [x] Backfill Progress Report (📦)
- [x] Data Quality Alert (📉)
- [x] Stale Data Warning (🕐)

### Phase 3: Integration (COMPLETE)
- [x] Daily Pipeline Health - Cloud Function + Cloud Scheduler
- [x] Prediction Completion - Phase 5 coordinator integration
- [x] Dependency Stall - Separate Cloud Function for periodic checking
- [x] Backfill Progress - BackfillProgressTracker context manager
- [x] Data Quality - QualityMixin.check_quality_degradation() method
- [x] Stale Data - DataFreshnessChecker utility

### Phase 4: Documentation
- [ ] Integration guide
- [ ] Operational runbook
- [ ] Alert response procedures

---

## Files

### Core Implementation
| File | Purpose |
|------|---------|
| `shared/utils/email_alerting_ses.py` | AWS SES email sender (10 methods) |
| `shared/utils/notification_system.py` | Multi-channel router (SES/Brevo/Slack) |
| `shared/alerts/alert_manager.py` | Backfill-aware rate limiting |
| `tests/test_ses_email.py` | SES connectivity test |

### Integration Points
| File | Purpose |
|------|---------|
| `monitoring/health_summary/main.py` | Daily health summary Cloud Function |
| `monitoring/stall_detection/main.py` | Pipeline stall detection Cloud Function |
| `predictions/coordinator/coordinator.py` | Prediction completion email (integrated) |
| `shared/alerts/backfill_progress_tracker.py` | Backfill progress tracking context manager |
| `shared/processors/patterns/quality_mixin.py` | Quality degradation detection (integrated) |
| `shared/utils/data_freshness_checker.py` | Stale data detection utility |

### Deployment Scripts
| File | Purpose |
|------|---------|
| `bin/monitoring/deploy/deploy_health_summary.sh` | Deploy health summary function |

### Configuration

#### AWS SES (Email)
| Variable | Value | Purpose |
|----------|-------|---------|
| `AWS_SES_ACCESS_KEY_ID` | AKIAU4MLE2... | AWS credentials |
| `AWS_SES_SECRET_ACCESS_KEY` | (secret) | AWS credentials |
| `AWS_SES_REGION` | us-west-2 | SES region |
| `AWS_SES_FROM_EMAIL` | alert@989.ninja | Sender address |
| `EMAIL_ALERTS_TO` | nchammas@gmail.com | Alert recipients |
| `EMAIL_CRITICAL_TO` | nchammas@gmail.com | Critical recipients |

#### Slack Webhooks (5 Channels)
| Variable | Channel | Purpose |
|----------|---------|---------|
| `SLACK_WEBHOOK_URL_INFO` | #nba-pipeline-health | ✅ Health, 📦 Backfill |
| `SLACK_WEBHOOK_URL_PREDICTIONS` | #nba-predictions | 🏀 Predictions |
| `SLACK_WEBHOOK_URL_WARNING` | #nba-alerts | ⏳ Stalls, 📉 Quality, 🕐 Stale |
| `SLACK_WEBHOOK_URL_ERROR` | #app-error-alerts | 🚨 Errors |
| `SLACK_WEBHOOK_URL_CRITICAL` | #app-error-alerts | 🚨 Critical |
| `SLACK_ALERTS_ENABLED` | true | Enable Slack |

---

## Integration Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     EMAIL TRIGGER POINTS                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Cloud Scheduler (6 AM PT)                                      │
│       │                                                         │
│       └──► ✅ Pipeline Health Summary                           │
│                                                                 │
│  Phase 5 Coordinator (on completion)                            │
│       │                                                         │
│       └──► 🏀 Prediction Completion Summary                     │
│                                                                 │
│  Orchestrators (Phase 2→3, 3→4)                                 │
│       │                                                         │
│       ├──► ⏳ Dependency Stall Alert (if waiting > 30 min)      │
│       └──► 🕐 Stale Data Warning (if upstream > 24h old)        │
│                                                                 │
│  Backfill Jobs (every 25% progress)                             │
│       │                                                         │
│       └──► 📦 Backfill Progress Report                          │
│                                                                 │
│  Quality Mixin (on quality change)                              │
│       │                                                         │
│       └──► 📉 Data Quality Alert                                │
│                                                                 │
│  All Processors (on exception)                                  │
│       │                                                         │
│       └──► 🚨 Critical Error Alert                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Session Log

### 2025-11-30 (Session 1)
- AWS SES domain verified with DKIM
- Created `email_alerting_ses.py` with 4 initial methods
- Updated `notification_system.py` for SES-first routing
- Added boto3 to requirements
- Fixed HTML alignment (removed centered styling)
- Tested email delivery successfully

### 2025-11-30 (Session 2)
- Added 6 new email methods (✅🏀⏳📦📉🕐)
- Created project documentation (README, INTEGRATION-PLAN, EMAIL-REFERENCE)
- Created Cloud Functions for health summary and stall detection
- Integrated emails into coordinator, quality mixin, freshness checker
- Created BackfillProgressTracker context manager
- Set up 5 Slack channels with webhooks
- Created `shared/utils/slack_channels.py` for multi-channel routing
- Deployed `pipeline-health-summary` Cloud Function
- Created Cloud Scheduler job for daily 6 AM PT trigger
- Stored AWS SES credentials in Secret Manager

**Deployed:**
- Cloud Function: `pipeline-health-summary`
- Cloud Scheduler: `daily-pipeline-health-summary`
- Secrets: `aws-ses-access-key-id`, `aws-ses-secret-access-key`

**Slack Channels Configured:**
| Channel | Webhook Var | Purpose |
|---------|-------------|---------|
| #nba-pipeline-health | SLACK_WEBHOOK_URL_INFO | ✅ Health, 📦 Backfill |
| #nba-predictions | SLACK_WEBHOOK_URL_PREDICTIONS | 🏀 Predictions |
| #nba-alerts | SLACK_WEBHOOK_URL_WARNING | ⏳📉🕐 Warnings |
| #app-error-alerts | SLACK_WEBHOOK_URL_ERROR/CRITICAL | 🚨 Errors |

**Next Session:**
- Verify health summary function is sending emails/Slack
- Deploy stall detection function
- Add Slack env vars to other Cloud Run services
- Test end-to-end with real pipeline run
