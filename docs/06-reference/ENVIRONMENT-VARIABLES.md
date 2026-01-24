# Environment Variables Reference

**Last Updated:** 2026-01-24

---

## Overview

This document lists all environment variables used by the NBA Props Platform, organized by category.

---

## Required Variables

### GCP Configuration

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `GCP_PROJECT_ID` | GCP project ID | `nba-props-platform` | Yes |
| `GCP_PROJECT` | Alias for GCP_PROJECT_ID | - | No |
| `GCP_PROJECT_NUMBER` | GCP project number | `756957797294` | No |
| `GCP_REGION` | Default GCP region | `us-west2` | No |
| `GCS_BUCKET` | Override default GCS bucket | - | No |
| `GOOGLE_CLOUD_PROJECT` | Auto-set by Cloud Run | - | No |
| `GOOGLE_APPLICATION_CREDENTIALS` | Service account key path | - | Local only |

### Authentication

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `VALID_API_KEYS` | Comma-separated API keys for authentication | - | Production |
| `ADMIN_DASHBOARD_API_KEY` | Admin dashboard API key | - | Production |
| `COORDINATOR_API_KEY` | Prediction coordinator API key | - | Production |

### Environment

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `ENVIRONMENT` | Environment name | `production` | No |
| `SPORT` | Sport configuration (`nba` or `mlb`) | `nba` | No |

---

## Alerting & Notifications

### Slack

| Variable | Description | Default |
|----------|-------------|---------|
| `SLACK_WEBHOOK_URL` | General Slack webhook | - |
| `SLACK_WEBHOOK_URL_PREDICTIONS` | Predictions channel webhook | - |
| `SLACK_WEBHOOK_URL_INFO` | Info channel webhook | - |
| `SLACK_WEBHOOK_URL_WARNING` | Warning channel webhook | - |
| `SLACK_WEBHOOK_URL_ERROR` | Error channel webhook | - |

### Email (Brevo/SMTP)

| Variable | Description | Default |
|----------|-------------|---------|
| `BREVO_SMTP_HOST` | SMTP server host | `smtp-relay.brevo.com` |
| `BREVO_SMTP_PORT` | SMTP server port | `587` |
| `BREVO_SMTP_USERNAME` | SMTP username | - |
| `BREVO_SMTP_PASSWORD` | SMTP password | - |
| `BREVO_FROM_EMAIL` | Sender email address | - |
| `BREVO_FROM_NAME` | Sender display name | `NBA Registry System` |

### Email (AWS SES)

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_SES_REGION` | AWS SES region | `us-west-2` |
| `AWS_SES_ACCESS_KEY_ID` | AWS access key | - |
| `AWS_SES_SECRET_ACCESS_KEY` | AWS secret key | - |
| `AWS_SES_FROM_EMAIL` | Sender email | `alert@989.ninja` |
| `AWS_SES_FROM_NAME` | Sender name | `NBA Registry System` |

### Email Recipients

| Variable | Description | Default |
|----------|-------------|---------|
| `EMAIL_ALERTS_TO` | Alert recipients (comma-separated) | - |
| `EMAIL_CRITICAL_TO` | Critical alert recipients | - |
| `ALERT_FROM_EMAIL` | Alert sender address | - |
| `ALERT_RECIPIENTS` | Alert recipients | - |

### Email Thresholds

| Variable | Description | Default |
|----------|-------------|---------|
| `EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD` | Max unresolved players | `50` |
| `EMAIL_ALERT_SUCCESS_RATE_THRESHOLD` | Min success rate % | `90.0` |
| `EMAIL_ALERT_MAX_PROCESSING_TIME` | Max processing time (min) | `30` |

### Rate Limiting (Notifications)

| Variable | Description | Default |
|----------|-------------|---------|
| `NOTIFICATION_RATE_LIMIT_PER_HOUR` | Max notifications/hour | `5` |
| `NOTIFICATION_COOLDOWN_MINUTES` | Cooldown period | `60` |
| `NOTIFICATION_AGGREGATE_THRESHOLD` | Aggregate threshold | `3` |
| `NOTIFICATION_RATE_LIMITING_ENABLED` | Enable rate limiting | `true` |

---

## Monitoring & Observability

### Sentry

| Variable | Description | Default |
|----------|-------------|---------|
| `SENTRY_DSN` | Sentry DSN | - |
| `SENTRY_RELEASE` | Release version | `unknown` |

### Logging

| Variable | Description | Default |
|----------|-------------|---------|
| `ENABLE_STRUCTURED_LOGGING` | Enable JSON logging | `false` |
| `LOG_LEVEL` | Logging level | `INFO` |

### Execution Tracking

| Variable | Description | Default |
|----------|-------------|---------|
| `ORCHESTRATION_DATASET` | Orchestration dataset | `nba_orchestration` |
| `PHASE_EXECUTION_LOG_TABLE` | Execution log table | `phase_execution_log` |

---

## Timeouts

All timeout values are in seconds unless noted.

### HTTP & Network

| Variable | Description | Default |
|----------|-------------|---------|
| `TIMEOUT_HTTP_REQUEST` | General HTTP timeout | `30` |
| `TIMEOUT_SCRAPER_HTTP` | Scraper HTTP timeout | `60` |
| `TIMEOUT_HEALTH_CHECK` | Health check timeout | `10` |
| `TIMEOUT_SLACK_WEBHOOK` | Slack webhook timeout | `10` |

### BigQuery

| Variable | Description | Default |
|----------|-------------|---------|
| `TIMEOUT_BIGQUERY_QUERY` | Query timeout | `120` |
| `TIMEOUT_BIGQUERY_LARGE_QUERY` | Large query timeout | `300` |
| `TIMEOUT_BIGQUERY_LOAD` | Load job timeout | `180` |

### Firestore

| Variable | Description | Default |
|----------|-------------|---------|
| `TIMEOUT_FIRESTORE_READ` | Read timeout | `30` |
| `TIMEOUT_FIRESTORE_WRITE` | Write timeout | `30` |
| `TIMEOUT_FIRESTORE_TRANSACTION` | Transaction timeout | `60` |

### Pub/Sub & Workflows

| Variable | Description | Default |
|----------|-------------|---------|
| `TIMEOUT_PUBSUB_PUBLISH` | Publish timeout | `30` |
| `TIMEOUT_WORKFLOW_EXECUTION` | Workflow timeout | `3600` |
| `TIMEOUT_SCHEDULER_JOB` | Scheduler job timeout | `540` |

### ML & Batch

| Variable | Description | Default |
|----------|-------------|---------|
| `TIMEOUT_ML_INFERENCE` | Inference timeout | `60` |
| `TIMEOUT_ML_TRAINING` | Training timeout | `7200` |
| `TIMEOUT_BATCH_CONSOLIDATION` | Batch consolidation | `300` |
| `TIMEOUT_DATA_LOADER_BATCH` | Data loader batch | `120` |
| `TIMEOUT_STALL_DETECTION` | Stall detection | `1800` |

---

## Rate Limiting (API)

| Variable | Description | Default |
|----------|-------------|---------|
| `RATE_LIMIT_ENABLED` | Enable rate limiting | `true` |
| `RATE_LIMIT_DEFAULT_RPM` | Default requests/minute | `60` |
| `RATE_LIMIT_BACKOFF_THRESHOLD` | Backoff threshold | `0.8` |
| `RATE_LIMIT_{SOURCE}_RPM` | Per-source rate limit | - |

---

## Caching

| Variable | Description | Default |
|----------|-------------|---------|
| `ENABLE_QUERY_CACHING` | Enable BigQuery cache | `true` |
| `QUERY_CACHE_TTL_SECONDS` | Cache TTL | `3600` |

---

## Proxies

| Variable | Description | Default |
|----------|-------------|---------|
| `PROXYFUEL_CREDENTIALS` | ProxyFuel credentials | - |
| `DECODO_PROXY_CREDENTIALS` | Decodo credentials | - |
| `BRIGHTDATA_CREDENTIALS` | BrightData credentials | - |

---

## External APIs

| Variable | Description | Default |
|----------|-------------|---------|
| `BETTINGPROS_API_KEY` | BettingPros API key | - |
| `ODDS_API_KEY` | The Odds API key | - |
| `SENDGRID_API_KEY` | SendGrid API key | - |

---

## Feature Flags

Feature flags are configured via environment variables with the pattern:
```
FEATURE_{FLAG_NAME}=true|false
```

See `shared/config/feature_flags.py` for available flags.

---

## Cloud Run Auto-Set Variables

These are automatically set by Cloud Run:

| Variable | Description |
|----------|-------------|
| `K_SERVICE` | Service name |
| `K_REVISION` | Revision ID |
| `HOSTNAME` | Container hostname |
| `PORT` | Server port (usually 8080) |

---

## Example .env File

```bash
# Required
GCP_PROJECT_ID=nba-props-platform
ENVIRONMENT=development

# Authentication
VALID_API_KEYS=key1,key2
ADMIN_DASHBOARD_API_KEY=admin-key

# Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx

# Email (Brevo)
BREVO_SMTP_USERNAME=user@example.com
BREVO_SMTP_PASSWORD=password
BREVO_FROM_EMAIL=alerts@example.com
EMAIL_ALERTS_TO=team@example.com

# Sentry
SENTRY_DSN=https://xxx@sentry.io/xxx

# Optional overrides
TIMEOUT_BIGQUERY_QUERY=180
ENABLE_QUERY_CACHING=true
RATE_LIMIT_DEFAULT_RPM=100
```

---

## Related Documentation

- [Deployment Guide](../04-deployment/)
- [Service URLs Configuration](../../shared/config/service_urls.py)
- [Timeout Configuration](../../shared/config/timeout_config.py)
