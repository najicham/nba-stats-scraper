# Environment Variables Reference

Comprehensive documentation of all environment variables used in the NBA Props Platform.

## Table of Contents

- [GCP Configuration](#gcp-configuration)
- [API Keys and Secrets](#api-keys-and-secrets)
- [Email Configuration](#email-configuration)
- [Slack Configuration](#slack-configuration)
- [Feature Flags](#feature-flags)
- [Timeout Configuration](#timeout-configuration)
- [Circuit Breaker Configuration](#circuit-breaker-configuration)
- [Orchestration Configuration](#orchestration-configuration)
- [Service URLs](#service-urls)
- [Testing Configuration](#testing-configuration)
- [ML/Prediction Configuration](#mlprediction-configuration)
- [Monitoring Configuration](#monitoring-configuration)
- [Local Development](#local-development)

---

## GCP Configuration

Core Google Cloud Platform settings.

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `GCP_PROJECT_ID` | Primary GCP project identifier | No | `nba-props-platform` | All services, processors, orchestration |
| `GCP_PROJECT` | Legacy project ID (backward compatibility) | No | Falls back to `GCP_PROJECT_ID` | Legacy code paths |
| `GCP_PROJECT_NUMBER` | GCP project number for Cloud Run URLs | No | `756957797294` | `shared/config/service_urls.py` |
| `GCP_REGION` | Primary GCP region | No | `us-west2` | `shared/config/gcp_config.py` |
| `GCS_BUCKET` | Override GCS bucket name | No | Sport-specific default | `shared/config/gcp_config.py` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON | No | Auto-detected | All GCP clients |
| `GOOGLE_CLOUD_PROJECT` | Alternative project ID env var | No | - | Authentication utilities |

### BigQuery Datasets

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `BIGQUERY_DATASET` | Default BigQuery dataset | No | `nba_analytics` | Data processors |
| `DATASET_PREFIX` | Prefix for test datasets | No | `test_` | Testing/replay pipelines |
| `PREDICTIONS_TABLE` | Full table path for predictions | No | `nba_predictions.player_prop_predictions` | Prediction services |
| `FEATURE_STORE_TABLE` | Full table path for feature store | No | `nba_predictions.ml_feature_store_v2` | ML feature loading |

### GCS Buckets

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `GCS_BUCKET_RAW` | Bucket for raw scraped data | No | `nba-scraped-data` | Scrapers, processors |
| `GCS_BUCKET_PROCESSED` | Bucket for processed data | No | `nba-analytics-processed-data` | Analytics processors |
| `GCS_RAW_DATA_BUCKET` | Alternative raw data bucket | No | `nba-raw-data` | Freshness monitoring |
| `GCS_PREFIX` | Prefix for test GCS paths | No | `test/` | Testing/replay pipelines |

---

## API Keys and Secrets

All secrets should be stored in GCP Secret Manager. Environment variables serve as local fallbacks.

| Variable | Description | Required | Default | Secret Manager Key |
|----------|-------------|----------|---------|-------------------|
| `ODDS_API_KEY` | The Odds API key | Yes (for odds scraping) | - | `odds-api-key` |
| `BDL_API_KEY` | Ball Don't Lie API key | Yes (for BDL scraping) | - | `bdl-api-key` |
| `BETTINGPROS_API_KEY` | BettingPros API key | No | - | `bettingpros-api-key` |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key | No | - | `anthropic-api-key` |
| `SENDGRID_API_KEY` | SendGrid API key (legacy) | No | - | - |
| `COORDINATOR_API_KEY` | API key for coordinator service auth | Yes (production) | - | `coordinator-api-key` |
| `SENTRY_DSN` | Sentry error tracking DSN | No | - | `sentry-dsn` |
| `SENTRY_RELEASE` | Sentry release version tag | No | `unknown` | Sentry integration |

---

## Email Configuration

### AWS SES (Primary)

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `AWS_SES_ACCESS_KEY_ID` | AWS access key for SES | Yes (for email) | - | Email alerting |
| `AWS_SES_SECRET_ACCESS_KEY` | AWS secret key for SES | Yes (for email) | - | Email alerting |
| `AWS_SES_REGION` | AWS region for SES | No | `us-west-2` | Email alerting |
| `AWS_SES_FROM_EMAIL` | Sender email address | No | `alert@989.ninja` | Email alerting |
| `AWS_SES_FROM_NAME` | Sender display name | No | `NBA Registry System` | Email alerting |

### Brevo SMTP (Fallback)

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `BREVO_SMTP_HOST` | Brevo SMTP server | No | `smtp-relay.brevo.com` | Email alerting fallback |
| `BREVO_SMTP_PORT` | Brevo SMTP port | No | `587` | Email alerting fallback |
| `BREVO_SMTP_USERNAME` | Brevo SMTP username | No | - | Email alerting fallback |
| `BREVO_SMTP_PASSWORD` | Brevo SMTP password | No | - | Email alerting fallback |
| `BREVO_FROM_EMAIL` | Brevo sender email | No | `alert@989.ninja` | Email alerting fallback |
| `BREVO_FROM_NAME` | Brevo sender name | No | `NBA System` | Email alerting fallback |

### Generic SMTP

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `SMTP_HOST` | Generic SMTP host | No | - | Processor alerting |
| `SMTP_PORT` | Generic SMTP port | No | `587` | Processor alerting |
| `SMTP_USER` | Generic SMTP username | No | - | Processor alerting |

### Email Recipients

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `EMAIL_ALERTS_TO` | Comma-separated alert recipients | Yes (for alerts) | - | All email alerting |
| `EMAIL_CRITICAL_TO` | Comma-separated critical alert recipients | No | Same as `EMAIL_ALERTS_TO` | Critical alerts |
| `ALERT_FROM_EMAIL` | Alert sender email | No | `nba-processors@nba-props-platform.com` | Processor alerting |
| `ALERT_RECIPIENTS` | Alternative alert recipients | No | - | Processor alerting |
| `EMAIL_ALERTS_ENABLED` | Enable/disable email alerts | No | `true` | Notification system |

### Email Thresholds

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD` | Trigger alert after N unresolved players | No | `50` | Player registry |
| `EMAIL_ALERT_SUCCESS_RATE_THRESHOLD` | Minimum success rate percentage | No | `90.0` | Email alerting |
| `EMAIL_ALERT_MAX_PROCESSING_TIME` | Maximum processing time (minutes) | No | `30` | Email alerting |

---

## Slack Configuration

### Webhook URLs

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `SLACK_WEBHOOK_URL` | Default Slack webhook | No | - | All Slack notifications |
| `SLACK_WEBHOOK_URL_INFO` | Info-level webhook | No | Falls back to default | Notification system |
| `SLACK_WEBHOOK_URL_WARNING` | Warning-level webhook | No | Falls back to default | Notification system |
| `SLACK_WEBHOOK_URL_ERROR` | Error-level webhook | No | Falls back to default | Critical alerts |
| `SLACK_WEBHOOK_URL_CRITICAL` | Critical-level webhook | No | Falls back to default | Critical alerts |
| `SLACK_WEBHOOK_URL_PREDICTIONS` | Predictions channel webhook | No | - | Prediction notifications |
| `SLACK_WEBHOOK_URL_CONSISTENCY` | Consistency monitoring webhook | No | - | Batch state manager |
| `SLACK_WEBHOOK_URL_REMINDERS` | Reminders channel webhook | No | - | Scheduled reminders |

### Slack Settings

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `SLACK_ALERTS_ENABLED` | Enable/disable Slack alerts | No | `false` | Notification system |
| `SLACK_CHANNEL` | Default Slack channel | No | `#nba-alerts` | Processor alerting |

---

## Feature Flags

Enable/disable features for gradual rollout. All default to `false` unless noted.

### Week 1 Features

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `ENABLE_PHASE2_COMPLETION_DEADLINE` | Enable Phase 2 completion deadlines | No | `false` | Feature flags |
| `PHASE2_COMPLETION_TIMEOUT_MINUTES` | Phase 2 completion timeout | No | `30` | Feature flags |
| `ENABLE_SUBCOLLECTION_COMPLETIONS` | Enable Firestore subcollection writes | No | `false` | Batch state manager |
| `DUAL_WRITE_MODE` | Write to both old and new structures | No | `true` | Batch state manager |
| `USE_SUBCOLLECTION_READS` | Read from new Firestore structure | No | `false` | Batch state manager |
| `ENABLE_QUERY_CACHING` | Enable BigQuery query caching | No | `false` | Feature flags |
| `QUERY_CACHE_TTL_SECONDS` | Query cache TTL | No | `3600` | Feature flags |
| `ENABLE_IDEMPOTENCY_KEYS` | Enable idempotency for deduplication | No | `false` | Coordinator |
| `DEDUP_TTL_DAYS` | Deduplication TTL in days | No | `7` | Coordinator |
| `ENABLE_PARALLEL_CONFIG` | Enable parallel configuration loading | No | `false` | Feature flags |
| `ENABLE_CENTRALIZED_TIMEOUTS` | Use centralized timeout config | No | `false` | Feature flags |
| `ENABLE_STRUCTURED_LOGGING` | Enable structured JSON logging | No | `false` | Feature flags |
| `ENABLE_HEALTH_CHECK_METRICS` | Enable health check metrics | No | `false` | Feature flags |

### Week 2-3 Features

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `ENABLE_PROMETHEUS_METRICS` | Enable Prometheus metrics export | No | `false` | Feature flags |
| `ENABLE_UNIVERSAL_RETRY` | Enable universal retry logic | No | `false` | Feature flags |
| `ENABLE_ASYNC_PHASE1` | Enable async Phase 1 processing | No | `false` | Feature flags |
| `ENABLE_ASYNC_COMPLETE` | Enable full async processing | No | `false` | Feature flags |
| `ENABLE_INTEGRATION_TESTS` | Enable integration test suite | No | `false` | Feature flags |

---

## Timeout Configuration

All timeout values are in seconds unless noted. Override via `TIMEOUT_*` prefix.

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `TIMEOUT_HTTP_REQUEST` | Standard HTTP request timeout | No | `30` | HTTP clients |
| `TIMEOUT_SCRAPER_HTTP` | Scraper HTTP timeout | No | `180` | Scrapers |
| `TIMEOUT_HEALTH_CHECK` | Health check timeout | No | `10` | Service health checks |
| `TIMEOUT_SLACK_WEBHOOK` | Slack webhook timeout | No | `10` | Slack notifications |
| `TIMEOUT_BIGQUERY_QUERY` | Standard BigQuery query timeout | No | `60` | BigQuery operations |
| `TIMEOUT_BIGQUERY_LARGE_QUERY` | Large BigQuery query timeout | No | `300` | Batch BigQuery operations |
| `TIMEOUT_BIGQUERY_LOAD` | BigQuery load job timeout | No | `60` | Data loading |
| `TIMEOUT_FIRESTORE_READ` | Firestore read timeout | No | `10` | Firestore operations |
| `TIMEOUT_FIRESTORE_WRITE` | Firestore write timeout | No | `10` | Firestore operations |
| `TIMEOUT_FIRESTORE_TRANSACTION` | Firestore transaction timeout | No | `30` | Firestore transactions |
| `TIMEOUT_PUBSUB_PUBLISH` | Pub/Sub publish timeout | No | `60` | Pub/Sub publishers |
| `TIMEOUT_WORKFLOW_EXECUTION` | Workflow execution timeout | No | `600` | Workflow executor |
| `TIMEOUT_SCHEDULER_JOB` | Cloud Scheduler job timeout | No | `600` | Scheduler jobs |
| `TIMEOUT_ML_INFERENCE` | ML model inference timeout | No | `30` | Prediction workers |
| `TIMEOUT_ML_TRAINING` | ML model training timeout | No | `3600` | Model training |
| `TIMEOUT_BATCH_CONSOLIDATION` | Batch consolidation timeout | No | `300` | Batch processors |
| `TIMEOUT_DATA_LOADER_BATCH` | Data loader batch timeout | No | `120` | Data loaders |
| `TIMEOUT_STALL_DETECTION` | Stall detection threshold | No | `600` | Monitoring |

---

## Circuit Breaker Configuration

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `CIRCUIT_BREAKER_THRESHOLD` | Failures before circuit opens | No | `5` | All processors |
| `CIRCUIT_BREAKER_TIMEOUT_MINUTES` | Minutes to stay open | No | `30` | All processors |
| `CIRCUIT_BREAKER_ENTITY_LOCKOUT_HOURS` | Entity-specific lockout duration | No | - | Orchestration config |
| `CIRCUIT_BREAKER_AUTO_RESET` | Auto-reset circuit breakers | No | - | Orchestration config |

---

## Orchestration Configuration

### Processing Modes

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `PROCESSING_MODE` | Processing mode (game-day/backfill/off-day) | No | Auto-detected | All processors |
| `PREDICTION_MODE` | Prediction generation mode | No | - | Prediction coordinator |
| `SPORT` | Current sport context (nba/mlb) | No | `nba` | Sport configuration |
| `ENVIRONMENT` | Deployment environment | No | `production` | All services |

### Pub/Sub Topics

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `PREDICTION_REQUEST_TOPIC` | Topic for prediction requests | No | `prediction-request-prod` | Coordinator |
| `PREDICTION_READY_TOPIC` | Topic for ready predictions | No | `prediction-ready-prod` | Coordinator |
| `BATCH_SUMMARY_TOPIC` | Topic for batch summaries | No | `prediction-batch-complete` | Coordinator |

### Worker Configuration

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `WORKER_MAX_INSTANCES` | Maximum worker instances | No | - | Orchestration config |
| `WORKER_CONCURRENCY` | Worker concurrency level | No | - | Orchestration config |
| `WORKER_EMERGENCY_MODE` | Enable emergency mode | No | - | Orchestration config |

### Self-Healing Configuration

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `SELF_HEALING_DML_BACKOFF_ENABLED` | Enable DML backoff | No | - | Orchestration config |
| `SELF_HEALING_DML_MAX_RETRIES` | Maximum DML retries | No | - | Orchestration config |
| `SELF_HEALING_ALERT_ON_DML_LIMIT` | Alert when DML limit reached | No | - | Orchestration config |
| `SELF_HEALING_AUTO_REDUCE_CONCURRENCY` | Auto-reduce concurrency on errors | No | - | Orchestration config |

### Schedule Staleness

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `SCHEDULE_STALENESS_OVERRIDE_HOURS` | Override staleness threshold | No | - | Orchestration config |
| `SCHEDULE_STALENESS_OVERRIDE_EXPIRES` | Override expiration time | No | - | Orchestration config |
| `SCHEDULE_MIN_GAME_DATES` | Minimum game dates threshold | No | `50` | Schedule API |
| `SCHEDULE_MIN_GAMES` | Minimum games threshold | No | `100` | Schedule API |

---

## Service URLs

Override Cloud Run service URLs for local development or alternate deployments.

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `SERVICE_URL` | Generic service URL override | No | `http://localhost:8080` | Workflow executor |
| `PHASE1_SCRAPERS_URL` | Phase 1 scrapers service URL | No | Auto-generated | Service URLs |
| `PHASE2_PROCESSORS_URL` | Phase 2 processors service URL | No | Auto-generated | Service URLs |
| `PHASE3_ANALYTICS_URL` | Phase 3 analytics service URL | No | Auto-generated | Service URLs |
| `ANALYTICS_PROCESSOR_URL` | Analytics processor URL | No | - | Phase 3 to 4 orchestration |
| `PHASE4_PRECOMPUTE_URL` | Phase 4 precompute service URL | No | Auto-generated | Service URLs |
| `PRECOMPUTE_PROCESSOR_URL` | Precompute processor URL | No | - | Phase 3 to 4 orchestration |
| `PREDICTION_COORDINATOR_URL` | Prediction coordinator URL | No | Auto-generated | Service URLs |
| `PREDICTION_WORKER_URL` | Prediction worker URL | No | Auto-generated | Service URLs |
| `COORDINATOR_URL` | Alternative coordinator URL | No | - | Various services |
| `WORKER_URL` | Alternative worker URL | No | - | Various services |
| `PHASE6_EXPORT_URL` | Phase 6 export service URL | No | Auto-generated | Service URLs |
| `MLB_PREDICTION_WORKER_URL` | MLB prediction worker URL | No | Auto-generated | Service URLs |
| `MLB_GRADING_SERVICE_URL` | MLB grading service URL | No | Auto-generated | Service URLs |

---

## Testing Configuration

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `DATASET_PREFIX` | Prefix for test BigQuery datasets | No | `test_` | Testing pipelines |
| `GCS_PREFIX` | Prefix for test GCS paths | No | `test/` | Testing pipelines |
| `REQUIRED_ENV_VARS` | Comma-separated required env vars | No | - | Environment validation |

---

## ML/Prediction Configuration

### NBA Models

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `CATBOOST_V8_MODEL_PATH` | Path to CatBoost v8 model | No | - | CatBoost predictor |
| `PREDICTION_MIN_QUALITY_THRESHOLD` | Minimum prediction quality score | No | `70.0` | Data loaders |
| `USE_MULTIPLE_LINES_DEFAULT` | Use multiple betting lines | No | - | Orchestration config |

### MLB Models

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `MLB_ACTIVE_SYSTEMS` | Comma-separated active prediction systems | No | `v1_baseline` | MLB config |
| `MLB_V1_MODEL_PATH` | Path to MLB v1 baseline model | No | GCS default path | MLB predictor |
| `MLB_V1_6_MODEL_PATH` | Path to MLB v1.6 rolling model | No | GCS default path | MLB predictor |
| `MLB_PITCHER_STRIKEOUTS_MODEL_PATH` | Path to pitcher strikeouts model | No | GCS default path | MLB predictor |
| `MLB_ENSEMBLE_V1_WEIGHT` | Weight for v1 model in ensemble | No | `0.3` | MLB ensemble |
| `MLB_ENSEMBLE_V1_6_WEIGHT` | Weight for v1.6 model in ensemble | No | `0.5` | MLB ensemble |
| `BACKFILL_MODE` | Enable backfill mode for predictions | No | `false` | MLB worker |

### AI Resolution

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `AI_RESOLUTION_MODEL` | Claude model for AI name resolution | No | `claude-3-haiku-20240307` | AI resolver |
| `AI_HIGH_CONFIDENCE_THRESHOLD` | High confidence threshold | No | `0.9` | AI resolver |
| `AI_LOW_CONFIDENCE_THRESHOLD` | Low confidence threshold | No | `0.7` | AI resolver |

---

## Monitoring Configuration

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `STALL_THRESHOLD_MINUTES` | Minutes before stall alert | No | `30` | Stall detection |
| `TRANSITION_LOOKBACK_DAYS` | Days to look back for transitions | No | `7` | Transition monitor |
| `SEND_DAILY_SUMMARY` | Send daily performance summary | No | `true` | System performance |
| `HEALTH_CHECK_ENABLED` | Enable health checks | No | `true` | Phase 3 to 4 |
| `HEALTH_CHECK_TIMEOUT` | Health check timeout | No | `5` | Phase 3 to 4 |
| `MODE_AWARE_ENABLED` | Enable mode-aware processing | No | `true` | Phase 3 to 4 |

---

## Notification Rate Limiting

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `NOTIFICATION_RATE_LIMIT_PER_HOUR` | Max notifications per hour | No | `5` | Rate limiter |
| `NOTIFICATION_COOLDOWN_MINUTES` | Cooldown between notifications | No | `60` | Rate limiter |
| `NOTIFICATION_AGGREGATE_THRESHOLD` | Threshold for aggregating alerts | No | `3` | Rate limiter |
| `NOTIFICATION_RATE_LIMITING_ENABLED` | Enable rate limiting | No | `true` | Rate limiter |

---

## Discord Configuration

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `DISCORD_ALERTS_ENABLED` | Enable Discord notifications | No | `false` | Notification system |
| `DISCORD_WEBHOOK_URL_INFO` | Info-level Discord webhook | No | - | Notification system |
| `DISCORD_WEBHOOK_URL_WARNING` | Warning-level Discord webhook | No | - | Notification system |
| `DISCORD_WEBHOOK_URL_CRITICAL` | Critical-level Discord webhook | No | - | Notification system |

---

## Local Development

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `LOCAL_DEV` | Enable local development mode | No | `false` | All services |
| `PORT` | Service port | No | `8080` | All services |
| `PYTHONPATH` | Python module path | No | - | Docker containers |

### Database (Local Development)

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `POSTGRES_DB` | PostgreSQL database name | No | `nba_dev` | Local PostgreSQL |
| `POSTGRES_USER` | PostgreSQL username | No | `postgres` | Local PostgreSQL |
| `POSTGRES_PASSWORD` | PostgreSQL password | No | `postgres` | Local PostgreSQL |
| `POSTGRES_HOST` | PostgreSQL host | No | `localhost` | Local PostgreSQL |
| `POSTGRES_PORT` | PostgreSQL port | No | `5432` | Local PostgreSQL |

### Redis (Local Development)

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `REDIS_HOST` | Redis host | No | `localhost` | Local Redis |
| `REDIS_PORT` | Redis port | No | `6379` | Local Redis |

### MinIO (Local Development)

| Variable | Description | Required | Default | Used In |
|----------|-------------|----------|---------|---------|
| `MINIO_ROOT_USER` | MinIO root user | No | `minioadmin` | Local MinIO |
| `MINIO_ROOT_PASSWORD` | MinIO root password | No | `minioadmin` | Local MinIO |
| `MINIO_HOST` | MinIO host | No | `localhost` | Local MinIO |
| `MINIO_PORT` | MinIO port | No | `9000` | Local MinIO |

---

## Cloud Run Environment Variables

These are automatically set by Cloud Run and can be read but should not be set manually.

| Variable | Description | Used In |
|----------|-------------|---------|
| `K_SERVICE` | Cloud Run service name | Logging, metrics |
| `K_REVISION` | Cloud Run revision ID | Logging, metrics |
| `HOSTNAME` | Container hostname | Logging |
| `PROJECT_ID` | Alternative project ID | Authentication |
| `TRIGGERED_BY` | Trigger source identifier | Run history |
| `CLOUD_RUN_REVISION` | Alternative revision ID | Execution logging |

---

## Quick Start

### Minimum Required for Local Development

```bash
# .env file for local development
PROJECT_ID=nba-props-platform
LOCAL_DEV=true
LOG_LEVEL=INFO

# API Keys (get from GCP Secret Manager or your admin)
ODDS_API_KEY=your-key-here
BDL_API_KEY=your-key-here
```

### Minimum Required for Production

The following are required for production deployment:

1. **GCP Configuration**: `GCP_PROJECT_ID` (or defaults will be used)
2. **API Keys**: All API keys in GCP Secret Manager
3. **Email Alerting**: `AWS_SES_ACCESS_KEY_ID`, `AWS_SES_SECRET_ACCESS_KEY`, `EMAIL_ALERTS_TO`
4. **Slack Alerting** (optional): `SLACK_WEBHOOK_URL`, `SLACK_ALERTS_ENABLED=true`

---

## Related Documentation

- [Architecture Overview](/docs/01-architecture/README.md)
- [Operations Guide](/docs/02-operations/README.md)
- [Deployment Guide](/docs/04-deployment/README.md)
- [Feature Flags Configuration](/shared/config/feature_flags.py)
- [Timeout Configuration](/shared/config/timeout_config.py)
- [GCP Configuration](/shared/config/gcp_config.py)

---

*Last Updated: 2026-01-23*
