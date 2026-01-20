# Deployment Checklist

**Purpose**: Ensure all deployments are complete and verified before marking as done.

**Last Updated**: 2026-01-20
**Status**: Living document - update after each deployment

---

## Pre-Deployment

### Planning

- [ ] **Deployment plan documented** - Create deployment runbook in `/docs/09-handoff/`
- [ ] **Rollback plan defined** - Document how to revert if deployment fails
- [ ] **Dependencies identified** - List all services that depend on changes
- [ ] **Impact assessment complete** - Identify user-facing and data impacts

### Code Quality

- [ ] **Code reviewed** - At least one reviewer approved changes
- [ ] **Tests passing** - All unit and integration tests pass
- [ ] **Linting clean** - No linting errors or warnings
- [ ] **Documentation updated** - README, API docs, runbooks updated

### Infrastructure

- [ ] **APIs enabled** - All required GCP APIs are enabled
- [ ] **Permissions granted** - Service accounts have necessary roles
- [ ] **Quotas checked** - Verify quotas won't be exceeded
- [ ] **Secrets configured** - All secrets in Secret Manager

---

## Deployment Steps

### Cloud Functions

- [ ] **Function deployed** - `gcloud functions deploy` completed successfully
- [ ] **Function accessible** - HTTP endpoint returns 200 OK
- [ ] **Environment variables set** - Verify all env vars configured
- [ ] **Memory/timeout configured** - Appropriate limits set
- [ ] **Logs enabled** - Cloud Logging capturing function logs

### Cloud Run

- [ ] **Service deployed** - `gcloud run deploy` completed
- [ ] **Service healthy** - `/health` endpoint returns 200 OK
- [ ] **Traffic routed** - 100% traffic to new revision
- [ ] **Concurrency set** - Appropriate concurrency limits
- [ ] **Min/max instances configured** - Autoscaling parameters set

### Cloud Schedulers

- [ ] **Scheduler created** - `gcloud scheduler jobs create` completed
- [ ] **Schedule verified** - Cron expression is correct
- [ ] **Timezone set** - Correct timezone configured
- [ ] **Target verified** - Points to correct Pub/Sub topic or HTTP endpoint
- [ ] **Scheduler enabled** - State = ENABLED
- [ ] **Test trigger successful** - Manual trigger works

**CRITICAL VERIFICATION FOR SCHEDULERS**:
```bash
# List all schedulers in all regions
for region in us-west1 us-central1 us-east1; do
  echo "=== $region ==="
  gcloud scheduler jobs list --location=$region
done

# Expected: See all critical schedulers:
# - grading-daily-6am (Primary grading)
# - grading-daily-10am-backup (Backup grading)
# - grading-readiness-monitor-schedule (Monitor)
# - Any other critical schedulers
```

### BigQuery

- [ ] **Tables created** - All required tables exist
- [ ] **Schemas match** - Table schemas match code expectations
- [ ] **Partitioning configured** - Partitioned by date if applicable
- [ ] **Clustering configured** - Clustered on query fields
- [ ] **Scheduled queries created** - (if applicable)
- [ ] **Data Transfer API enabled** - Required for scheduled queries

**CRITICAL FOR SCHEDULED QUERIES**:
```bash
# Verify BigQuery Data Transfer API is enabled
gcloud services list --enabled | grep bigquerydatatransfer

# List all scheduled queries
bq ls --transfer_config --transfer_location=us --project_id=nba-props-platform
```

### Pub/Sub

- [ ] **Topics created** - All required topics exist
- [ ] **Subscriptions created** - All subscribers configured
- [ ] **Dead letter topics** - Configured for failed messages
- [ ] **Message retention** - Appropriate retention period set

### Firestore

- [ ] **Collections created** - All required collections exist
- [ ] **Indexes created** - Composite indexes configured
- [ ] **Security rules deployed** - Firestore rules updated
- [ ] **TTL configured** - Data cleanup policies set

---

## Post-Deployment Verification

### Smoke Tests

- [ ] **Manual trigger test** - Manually trigger the deployed service
- [ ] **End-to-end test** - Run full workflow end-to-end
- [ ] **Data validation** - Verify output data is correct
- [ ] **Error handling** - Test error scenarios work

### Monitoring

- [ ] **Logs visible** - Cloud Logging shows recent logs
- [ ] **Metrics visible** - Cloud Monitoring shows metrics
- [ ] **Alerts configured** - Error alerts are active
- [ ] **Dashboards updated** - Monitoring dashboards show new service

### Integration

- [ ] **Upstream services work** - Services calling this one still work
- [ ] **Downstream services work** - This service calls downstream correctly
- [ ] **Cross-service validation** - Full pipeline works end-to-end

---

## Critical Validations (Jan 19, 2026 Lessons Learned)

### Grading System Deployment

When deploying grading infrastructure, MUST verify:

1. **BigQuery Data Transfer API Enabled**:
```bash
gcloud services enable bigquerydatatransfer.googleapis.com
```

2. **Cloud Schedulers Created**:
```bash
# Primary grading (6 AM PT)
gcloud scheduler jobs list --location=us-central1 | grep grading-daily-6am

# Backup grading (10 AM PT)
gcloud scheduler jobs list --location=us-central1 | grep grading-daily-10am-backup

# Readiness monitor (every 15 min overnight)
gcloud scheduler jobs list --location=us-central1 | grep grading-readiness-monitor
```

3. **Grading Cloud Function Deployed**:
```bash
gcloud functions list | grep phase5b-grading
```

4. **Pub/Sub Topics Exist**:
```bash
gcloud pubsub topics list | grep -E "grading-trigger|grading-complete"
```

5. **Test Manual Grading**:
```bash
# Trigger grading for a recent date
gcloud pubsub topics publish nba-grading-trigger \
  --message='{"target_date":"yesterday","trigger_source":"manual-test"}'

# Wait 2 minutes, then verify grading completed
bq query --use_legacy_sql=false "
SELECT COUNT(*) as graded_count
FROM \`nba-props-platform.nba_predictions.prediction_grades\`
WHERE graded_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
"
```

### Data Pipeline Deployment

When deploying Phase 4 processors, MUST verify:

1. **Pre-flight Validation Added**:
```bash
# Verify Phase 3 completeness before triggering Phase 4
grep -r "validate.*phase3.*completeness" orchestration/
```

2. **Circuit Breaker Added**:
```bash
# Verify minimum processor coverage required
grep -r "minimum.*processor.*coverage" orchestration/
```

3. **Processor Completion Logging**:
```bash
# Verify which processors completed
gcloud logging read "resource.labels.service_name=nba-phase4-precompute-processors" \
  --limit=10 | grep "completed"
```

### Scraper Deployment

When deploying scrapers, MUST verify:

1. **Retry Logic Exists**:
```bash
# Verify retry decorators or retry loops
grep -r "@retry\|retry_count\|should_retry" scrapers/
```

2. **Completeness Validation**:
```bash
# Verify scraper checks if all expected data was collected
grep -r "completeness\|coverage.*pct\|expected.*actual" scrapers/
```

3. **Alerting Configured**:
```bash
# Verify alerts for missing data
grep -r "slack.*alert\|send.*notification\|coverage.*warning" scrapers/
```

---

## Rollback Procedures

### Cloud Functions

```bash
# List recent revisions
gcloud functions describe <function-name> --gen2 --region=us-west1

# Rollback to previous revision
gcloud functions deploy <function-name> --gen2 --region=us-west1 \
  --source=<previous-source> --entry-point=<entry-point>
```

### Cloud Run

```bash
# List revisions
gcloud run revisions list --service=<service-name> --region=us-west1

# Route traffic to previous revision
gcloud run services update-traffic <service-name> \
  --to-revisions=<previous-revision>=100 \
  --region=us-west1
```

### Cloud Scheduler

```bash
# Disable scheduler
gcloud scheduler jobs pause <job-name> --location=us-central1

# Delete scheduler
gcloud scheduler jobs delete <job-name> --location=us-central1
```

### BigQuery Scheduled Queries

```bash
# List scheduled queries
bq ls --transfer_config --transfer_location=us

# Delete scheduled query
bq rm --transfer_config <config-id>
```

---

## Documentation Requirements

After deployment, update:

1. **Runbooks** - `/docs/02-operations/`
   - Add operational procedures
   - Update troubleshooting guides

2. **Architecture Docs** - `/docs/00-orchestration/`
   - Update service diagrams
   - Document new dependencies

3. **Handoff Docs** - `/docs/09-handoff/`
   - Create session summary
   - Document deployment decisions

4. **README Files** - Service-specific READMEs
   - Update setup instructions
   - Add new environment variables

---

## Deployment Sign-off

**Deployment Name**: _______________________
**Deployed By**: _______________________
**Date**: _______________________

### Verification Sign-off

- [ ] All pre-deployment checks complete
- [ ] Deployment executed successfully
- [ ] Post-deployment verification passed
- [ ] Monitoring and alerts working
- [ ] Documentation updated
- [ ] Rollback procedure tested (if applicable)

**Verified By**: _______________________
**Date**: _______________________

---

## Lessons Learned (Jan 19, 2026 Incident)

### What Went Wrong

1. ❌ **APIs not enabled** - BigQuery Data Transfer API was disabled
2. ❌ **Schedulers not created** - Zero Cloud Schedulers in the project
3. ❌ **No verification** - Deployment marked complete without testing
4. ❌ **Code bugs deployed** - Table name bug in production
5. ❌ **No monitoring** - Failures went undetected for 3+ days

### What This Checklist Prevents

1. ✅ **API enablement verification** - Explicit check for required APIs
2. ✅ **Scheduler verification** - Explicit check that schedulers exist
3. ✅ **Post-deployment testing** - Smoke tests required before sign-off
4. ✅ **Code review** - Bugs caught before production
5. ✅ **Monitoring deployment** - Alerts configured as part of deployment

### Key Principle

> **"Deployment is not complete until it's verified to work in production."**

Don't check the box until you've:
1. Manually triggered the service
2. Verified output is correct
3. Confirmed monitoring is working
4. Documented the changes

---

**Document Status**: ✅ COMPLETE
**Last Updated**: 2026-01-20
**Owner**: Data Pipeline Team
