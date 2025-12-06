# Cloud Run Deployment Checklist

**Purpose:** Comprehensive checklist for deploying parallelized processors to Cloud Run production
**Created:** 2025-12-04 (Session 35)
**Status:** 📋 READY FOR FUTURE DEPLOYMENT

---

## Prerequisites

### ✅ Pre-Deployment Validation

- [ ] All Priority 1 processors tested locally (PCF, MLFS, PGS)
- [ ] Runtime tests show expected speedups (~200x+)
- [ ] Feature flag `ENABLE_PLAYER_PARALLELIZATION=true` tested
- [ ] Thread safety validated (zero errors in parallel runs)
- [ ] All code committed and pushed to main branch
- [ ] Latest handoff docs created

### 🔧 Environment Setup

- [ ] `.env` file configured with:
  - `BREVO_SMTP_PASSWORD` (email alerts)
  - `BREVO_SMTP_USERNAME`
  - `BREVO_FROM_EMAIL`
  - `EMAIL_ALERTS_TO`
  - `EMAIL_CRITICAL_TO`
- [ ] Worker count configuration (see [ENVIRONMENT-VARIABLES.md](./ENVIRONMENT-VARIABLES.md)):
  - `PARALLELIZATION_WORKERS` (global default, recommended: 4-8 for Cloud Run)
  - Processor-specific overrides (optional):
    - `PCF_WORKERS`, `MLFS_WORKERS`, `PGS_WORKERS`, `PDC_WORKERS`
    - `PSZA_WORKERS`, `TDZA_WORKERS`, `UPGC_WORKERS`
- [ ] GCP project set: `gcloud config set project nba-props-platform`
- [ ] GCP region confirmed: `us-west2`
- [ ] Authenticated: `gcloud auth login` (if needed)

---

## Phase 1: Capture Baseline Metrics

### 📊 Before Deployment

**Capture current performance from production:**

```bash
# Get recent Cloud Run logs for baseline
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 \
  --limit=100 \
  --format=json > /tmp/baseline_phase3_logs.json

gcloud run services logs read nba-phase4-precompute-processors \
  --region=us-west2 \
  --limit=100 \
  --format=json > /tmp/baseline_phase4_logs.json

# Get current resource usage
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format=json > /tmp/baseline_phase3_config.json

gcloud run services describe nba-phase4-precompute-processors \
  --region=us-west2 \
  --format=json > /tmp/baseline_phase4_config.json
```

**Document baseline:**
- [ ] Average processing time per processor
- [ ] Memory usage patterns
- [ ] CPU utilization
- [ ] Error rates (if any)
- [ ] Typical BigQuery costs per run

---

## Phase 2: Deploy Phase 4 (Precompute) - PCF & MLFS

### 🚀 Deployment Steps

**Step 1: Review deployment script**

```bash
# Verify script exists and is executable
ls -lh ./bin/precompute/deploy/deploy_precompute_processors.sh
cat ./bin/precompute/deploy/deploy_precompute_processors.sh | head -50
```

**Step 2: Deploy to Cloud Run**

```bash
# From project root
./bin/precompute/deploy/deploy_precompute_processors.sh
```

**Expected output:**
- ✅ Setup: Copy Dockerfile (~1s)
- ✅ Deployment: Build & deploy to Cloud Run (~3-5 min)
- ✅ Cleanup: Remove temporary Dockerfile (~1s)
- ✅ Health check: Test `/health` endpoint

**Step 3: Verify deployment**

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe nba-phase4-precompute-processors \
  --region=us-west2 \
  --format="value(status.url)")

echo "Service URL: $SERVICE_URL"

# Test health endpoint
curl -s -X GET "$SERVICE_URL/health" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq '.'

# Expected response:
# {
#   "status": "healthy",
#   "service": "nba-phase4-precompute-processors",
#   ...
# }
```

**Step 4: Configure worker counts (recommended for Cloud Run)**

Based on Cloud Run memory allocation, configure worker counts to avoid OOM errors:

```bash
# For 4-8GB Cloud Run instances (recommended starting point)
gcloud run services update nba-phase4-precompute-processors \
  --region=us-west2 \
  --set-env-vars="PARALLELIZATION_WORKERS=4,MLFS_WORKERS=2,PDC_WORKERS=3"

# For 8GB+ instances (if testing shows capacity)
# gcloud run services update nba-phase4-precompute-processors \
#   --region=us-west2 \
#   --set-env-vars="PARALLELIZATION_WORKERS=6,MLFS_WORKERS=4,PDC_WORKERS=5"
```

See [ENVIRONMENT-VARIABLES.md](./ENVIRONMENT-VARIABLES.md) for detailed tuning guidance.

**Step 5: Verify all environment variables**

```bash
gcloud run services describe nba-phase4-precompute-processors \
  --region=us-west2 \
  --format="get(spec.template.spec.containers[0].env)"

# Confirm these are set:
# - GCP_PROJECT_ID=nba-props-platform
# - ENABLE_PLAYER_PARALLELIZATION=true (if using feature flag)
# - PARALLELIZATION_WORKERS=4 (or your chosen value)
# - MLFS_WORKERS=2 (or your chosen value)
# - Email config (BREVO_* vars)
```

### 🧪 Canary Testing - Single Processor Test

**Test PCF processor:**

```bash
# Test with a recent date that has data
TEST_DATE="2024-12-04"  # Adjust to current date

curl -X POST "$SERVICE_URL/process-precompute" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d "{
    \"processor\": \"player_composite_factors\",
    \"analysis_date\": \"$TEST_DATE\"
  }" | jq '.'
```

**Expected behavior:**
- ⏱️ **Processing time**: <60 seconds (vs 111+ min baseline)
- 💾 **Memory**: 4-7 GiB peak (within 8 GiB limit)
- 🔥 **CPU**: 60-80% average
- ✅ **Success**: HTTP 200, records written to BigQuery
- 📧 **Alerts**: No error emails

**Monitor logs:**

```bash
# Watch logs in real-time
gcloud run services logs tail nba-phase4-precompute-processors \
  --region=us-west2 \
  --format="value(textPayload)"

# Look for:
# - "Processing 2024-12-04..."
# - "Parallel processing: 369 players with 8 workers"
# - "✅ Successfully wrote X records"
# - NO errors or exceptions
```

**Verify BigQuery output:**

```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as record_count,
  COUNT(DISTINCT player_lookup) as player_count
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE analysis_date = '$TEST_DATE'
"
```

**Test MLFS processor:**

```bash
curl -X POST "$SERVICE_URL/process-precompute" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d "{
    \"processor\": \"ml_feature_store\",
    \"analysis_date\": \"$TEST_DATE\"
  }" | jq '.'
```

**Expected behavior:**
- ⏱️ **Processing time**: <60 seconds
- Same memory/CPU patterns as PCF
- BigQuery records written successfully

### 📈 Canary Success Criteria

Phase 4 canary is successful if:

- [x] Both processors complete in <60s (vs 111+ min baseline)
- [x] Memory stays under 7 GiB (8 GiB limit)
- [x] CPU utilization 60-80%
- [x] No errors in logs
- [x] BigQuery data validated (correct record counts)
- [x] No error emails sent
- [x] Service responds to health checks

**If canary fails:**

```bash
# Immediate rollback to previous revision
gcloud run services update-traffic nba-phase4-precompute-processors \
  --region=us-west2 \
  --to-revisions=PREVIOUS_REVISION=100

# Or disable parallelization via environment variable
gcloud run services update nba-phase4-precompute-processors \
  --region=us-west2 \
  --set-env-vars="ENABLE_PLAYER_PARALLELIZATION=false"
```

---

## Phase 3: Deploy Phase 3 (Analytics) - PGS

### 🚀 Deployment Steps

**Step 1: Review deployment script**

```bash
# Verify script
ls -lh ./bin/analytics/deploy/deploy_analytics_processors.sh
```

**Step 2: Deploy to Cloud Run**

```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
```

**Step 3: Configure worker counts**

```bash
# For 4-8GB Cloud Run instances
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --set-env-vars="PARALLELIZATION_WORKERS=6,PGS_WORKERS=8,UPGC_WORKERS=4"
```

**Step 4: Verify deployment**

```bash
SERVICE_URL=$(gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(status.url)")

echo "Analytics Service URL: $SERVICE_URL"

curl -s -X GET "$SERVICE_URL/health" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq '.'
```

### 🧪 Canary Testing - PGS Processor

**Test PGS processor:**

```bash
TEST_START_DATE="2024-12-01"
TEST_END_DATE="2024-12-03"

curl -X POST "$SERVICE_URL/process-analytics" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d "{
    \"processor\": \"player_game_summary\",
    \"start_date\": \"$TEST_START_DATE\",
    \"end_date\": \"$TEST_END_DATE\"
  }" | jq '.'
```

**Expected behavior:**
- ⏱️ **Processing time**: <10 seconds for 3 days (vs minutes baseline)
- 💾 **Memory**: 4-6 GiB
- 🔥 **CPU**: 60-80%
- ✅ **Success**: Records written to `nba_analytics.player_game_summary`

**Verify BigQuery output:**

```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as record_count
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '$TEST_START_DATE' AND '$TEST_END_DATE'
GROUP BY game_date
ORDER BY game_date
"
```

---

## Phase 4: Monitoring & Validation (24-48 hours)

### 📊 Monitoring Queries

**1. Check Cloud Run metrics**

```bash
# View recent invocations
gcloud run services logs read nba-phase4-precompute-processors \
  --region=us-west2 \
  --limit=50 \
  --format=json | jq '[.[] | {
    timestamp: .timestamp,
    severity: .severity,
    message: .textPayload
  }]'

# Check for errors
gcloud run services logs read nba-phase4-precompute-processors \
  --region=us-west2 \
  --limit=100 \
  --format=json | jq '[.[] | select(.severity == "ERROR")]'
```

**2. BigQuery cost analysis**

```bash
# Compare BigQuery costs before/after
bq query --use_legacy_sql=false "
SELECT
  DATE(creation_time) as date,
  user_email,
  COUNT(*) as query_count,
  SUM(total_bytes_processed) / POW(10, 12) as tb_processed,
  SUM(total_bytes_processed) / POW(10, 12) * 5 as estimated_cost_usd
FROM \`nba-props-platform.region-us-west2\`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE DATE(creation_time) >= CURRENT_DATE() - 7
  AND job_type = 'QUERY'
  AND state = 'DONE'
GROUP BY date, user_email
ORDER BY date DESC, tb_processed DESC
"
```

**3. Processor run history**

```bash
bq query --use_legacy_sql=false "
SELECT
  processor_name,
  phase,
  data_date,
  status,
  processing_duration_seconds,
  rows_processed,
  alert_sent,
  created_at
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND processor_name IN ('player_composite_factors', 'ml_feature_store', 'player_game_summary')
ORDER BY created_at DESC
LIMIT 50
"
```

### 🎯 Success Metrics (24-48h)

- [ ] **Performance**: 95%+ of runs complete in <60s
- [ ] **Reliability**: 99%+ success rate (errors < 1%)
- [ ] **Resource usage**: Memory < 7 GiB, CPU 60-80%
- [ ] **Cost**: BigQuery costs reduced by ~98%
- [ ] **Alerts**: Zero error emails
- [ ] **Data quality**: All expected records in BigQuery

---

## Phase 5: Gradual Rollout (if using traffic splitting)

**Note:** Cloud Run traffic splitting is only needed if you deploy multiple revisions simultaneously. For feature flag approach, skip this section.

### Wave 1: 25% Traffic (Day 4-5)

```bash
# Get revision IDs
gcloud run revisions list \
  --service=nba-phase4-precompute-processors \
  --region=us-west2

# Split traffic
gcloud run services update-traffic nba-phase4-precompute-processors \
  --region=us-west2 \
  --to-revisions=NEW_REVISION=25,OLD_REVISION=75
```

**Monitor for 24h, then proceed if successful.**

### Wave 2: 50% Traffic (Day 5-6)

```bash
gcloud run services update-traffic nba-phase4-precompute-processors \
  --region=us-west2 \
  --to-revisions=NEW_REVISION=50,OLD_REVISION=50
```

### Wave 3: 100% Traffic (Day 7)

```bash
gcloud run services update-traffic nba-phase4-precompute-processors \
  --region=us-west2 \
  --to-revisions=NEW_REVISION=100
```

---

## Rollback Procedures

### Emergency Rollback (if critical issues)

**Option 1: Rollback to previous revision**

```bash
# List revisions
gcloud run revisions list \
  --service=nba-phase4-precompute-processors \
  --region=us-west2

# Rollback (replace PREVIOUS_REVISION with actual revision name)
gcloud run services update-traffic nba-phase4-precompute-processors \
  --region=us-west2 \
  --to-revisions=PREVIOUS_REVISION=100
```

**Option 2: Disable parallelization (if using feature flag)**

```bash
gcloud run services update nba-phase4-precompute-processors \
  --region=us-west2 \
  --set-env-vars="ENABLE_PLAYER_PARALLELIZATION=false"

# Wait for new revision to deploy (~30s)
# Test immediately
```

**Option 3: Full redeploy of old code**

```bash
# Checkout previous commit
git checkout <PREVIOUS_COMMIT_SHA>

# Redeploy
./bin/precompute/deploy/deploy_precompute_processors.sh

# Return to main when ready
git checkout main
```

### Validation After Rollback

```bash
# Verify service is working
curl -s -X GET "$SERVICE_URL/health" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq '.'

# Test with safe date
curl -X POST "$SERVICE_URL/process-precompute" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"processor": "player_composite_factors", "analysis_date": "2024-12-04"}' | jq '.'

# Check logs for errors
gcloud run services logs tail nba-phase4-precompute-processors \
  --region=us-west2 \
  --format="value(textPayload)"
```

---

## Post-Deployment Documentation

### 📝 Update Handoff Doc

After successful deployment, create handoff document:

```markdown
# Session XX: Cloud Run Production Deployment

**Date:** YYYY-MM-DD
**Status:** ✅ DEPLOYED TO PRODUCTION

## Deployment Summary

- **Phase 3 (Analytics)**: nba-phase3-analytics-processors
  - PGS: 6560 records/sec (~10000x speedup)

- **Phase 4 (Precompute)**: nba-phase4-precompute-processors
  - PCF: 621 players/sec (~1000x speedup)
  - MLFS: 12.5 players/sec (~200x speedup)

## Performance Results

| Metric          | Before      | After   | Improvement |
|-----------------|-------------|---------|-------------|
| Processing Time | 111-115 min | ~31 sec | -99.5%      |
| Memory Usage    | X GiB       | Y GiB   | Z%          |
| Cost per Run    | $X          | $Y      | -Z%         |

## Monitoring

- Service URLs: [list URLs]
- Monitoring dashboard: [link if exists]
- Alert configuration: [email addresses]

## Next Steps

1. Monitor for 1 week
2. Deploy remaining Priority 2 processors
3. Update documentation
```

### 🔗 Update README

Add deployment status to main README:

```markdown
## Deployment Status

| Service                          | Region    | Status     | Last Updated |
|----------------------------------|-----------|------------|--------------|
| nba-phase3-analytics-processors  | us-west2  | ✅ Active  | YYYY-MM-DD   |
| nba-phase4-precompute-processors | us-west2  | ✅ Active  | YYYY-MM-DD   |

**Features:**
- ✅ ThreadPoolExecutor parallelization (Priority 1 processors)
- ✅ Feature flag support (ENABLE_PLAYER_PARALLELIZATION)
- ✅ 200x+ performance improvement
```

---

## Troubleshooting

### Issue: Deployment fails

```bash
# Check Cloud Build logs
gcloud builds list --limit=5

# View specific build
gcloud builds log <BUILD_ID>
```

**Common causes:**
- Docker build errors → Check Dockerfile syntax
- Missing dependencies → Verify `requirements.txt`
- Permission issues → Check service account roles

### Issue: Health check fails

```bash
# Check service status
gcloud run services describe nba-phase4-precompute-processors \
  --region=us-west2

# Check recent logs
gcloud run services logs read nba-phase4-precompute-processors \
  --region=us-west2 \
  --limit=50
```

**Common causes:**
- Service not ready → Wait 30s after deployment
- Authentication issue → Regenerate identity token
- Firewall/network → Check VPC settings

### Issue: Processor times out

```bash
# Check current timeout
gcloud run services describe nba-phase4-precompute-processors \
  --region=us-west2 \
  --format="value(spec.template.spec.timeoutSeconds)"

# Increase timeout if needed (max 3600s)
gcloud run services update nba-phase4-precompute-processors \
  --region=us-west2 \
  --timeout=3600
```

### Issue: Out of memory

```bash
# Check memory limit
gcloud run services describe nba-phase4-precompute-processors \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].resources.limits.memory)"

# Increase memory (max 32Gi)
gcloud run services update nba-phase4-precompute-processors \
  --region=us-west2 \
  --memory=16Gi
```

### Issue: BigQuery quota exceeded

```bash
# Check quota usage
gcloud compute project-info describe \
  --project=nba-props-platform \
  --format="value(quotas.filter(metric:bigquery))"

# Request quota increase via GCP Console if needed
```

---

## Contact & Support

**For issues:**
1. Check logs: `gcloud run services logs read <SERVICE_NAME> --region=us-west2`
2. Review processor run history in BigQuery
3. Check email alerts for detailed error context
4. Rollback if critical (see Rollback Procedures above)

**Service accounts:**
- Cloud Run: `<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`
- BigQuery: Default service account

**Monitoring:**
- Cloud Run Console: https://console.cloud.google.com/run?project=nba-props-platform
- BigQuery Console: https://console.cloud.google.com/bigquery?project=nba-props-platform
- Logs: https://console.cloud.google.com/logs?project=nba-props-platform

---

## Checklist Summary

### Pre-Deployment
- [ ] Code tested locally
- [ ] Environment variables configured
- [ ] Baseline metrics captured

### Phase 4 Deployment (Precompute)
- [ ] Deployed to Cloud Run
- [ ] Health check passed
- [ ] PCF canary test successful
- [ ] MLFS canary test successful
- [ ] BigQuery data validated

### Phase 3 Deployment (Analytics)
- [ ] Deployed to Cloud Run
- [ ] Health check passed
- [ ] PGS canary test successful
- [ ] BigQuery data validated

### Monitoring (24-48h)
- [ ] No errors in logs
- [ ] Performance metrics met
- [ ] Cost savings confirmed
- [ ] Email alerts working

### Post-Deployment
- [ ] Handoff doc created
- [ ] README updated
- [ ] Team notified

---

**Deployment Status:** 📋 READY (not yet executed)
**Last Updated:** 2025-12-04 (Session 35)
