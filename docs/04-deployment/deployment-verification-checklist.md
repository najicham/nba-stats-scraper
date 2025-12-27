# Deployment Verification Checklist

**Created:** 2025-12-27
**Purpose:** Post-deployment verification steps to ensure services are properly deployed
**Use:** After any Cloud Run deployment to verify the service is working correctly

---

## Quick Verification (2 min)

```bash
# Set service name
SERVICE="nba-phase1-scrapers"  # or nba-phase2-raw-processors, etc.

# 1. Check deployment succeeded
gcloud run services describe $SERVICE --region=us-west2 --format="value(status.url)"

# 2. Check health endpoint
curl -s "$(gcloud run services describe $SERVICE --region=us-west2 --format='value(status.url)')/health" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq

# 3. Verify latest revision is active
gcloud run revisions list --service=$SERVICE --region=us-west2 --limit=3
```

---

## Full Verification Checklist

### 1. Service Deployment Status

```bash
# Check service is deployed and running
gcloud run services describe $SERVICE --region=us-west2 --format="yaml(status)"
```

**Expected:** `status.conditions` should show `Ready: True`

### 2. Health Endpoint Check

```bash
# Get service URL and check health
SERVICE_URL=$(gcloud run services describe $SERVICE --region=us-west2 --format='value(status.url)')
curl -s "$SERVICE_URL/health" -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq
```

**Expected Response:**
```json
{
  "status": "healthy",
  "service": "nba-phase1-scrapers",
  "version": "1.0.0"
}
```

### 3. Environment Variable Verification

**Critical environment variables to check:**

| Phase | Required Env Vars |
|-------|-------------------|
| Phase 1 | `GCP_PROJECT_ID`, `GCS_BUCKET`, `PUBSUB_TOPIC` |
| Phase 2 | `GCP_PROJECT_ID`, `BQ_DATASET`, `PUBSUB_TOPIC` |
| Phase 3 | `GCP_PROJECT_ID`, `BQ_DATASET_ANALYTICS` |
| Phase 4 | `GCP_PROJECT_ID`, `BQ_DATASET_PRECOMPUTE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| Phase 5 | `GCP_PROJECT_ID`, `WORKER_URL` |

```bash
# Get all env vars for the latest revision
LATEST_REV=$(gcloud run revisions list --service=$SERVICE --region=us-west2 --limit=1 --format="value(name)")
gcloud run revisions describe $LATEST_REV --region=us-west2 --format="yaml(spec.template.spec.containers[0].env)"
```

**Check for missing vars:**
```bash
# This should return the expected values, not empty
gcloud run revisions describe $LATEST_REV --region=us-west2 \
  --format="get(spec.template.spec.containers[0].env[name=GCP_PROJECT_ID].value)"
```

### 4. Docker Image Verification

```bash
# Check which image is deployed
gcloud run services describe $SERVICE --region=us-west2 \
  --format="value(spec.template.spec.containers[0].image)"

# Should show latest digest like:
# us-west2-docker.pkg.dev/nba-props-platform/nba-processors/phase1-scrapers@sha256:abc123...
```

**Verify correct image:**
- Phase 1: `phase1-scrapers` or `scrapers.Dockerfile`
- Phase 2: `phase2-raw-processors` or `raw-processor.Dockerfile`
- Phase 3: `phase3-analytics` or `analytics-processor.Dockerfile`
- Phase 4: `phase4-precompute` or `precompute-processor.Dockerfile`
- Phase 5: `prediction-coordinator`, `prediction-worker`

**Common Issue:** Phase 3 deployed with Phase 4 image (Session 170 incident)

### 5. Cloud Logs Verification

```bash
# Check for startup errors (last 10 minutes)
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="'$SERVICE'" AND severity>=ERROR' \
  --limit=10 --format="table(timestamp,textPayload)" --freshness=10m
```

**Expected:** No errors, or only transient startup logs

### 6. End-to-End Test (Optional)

**Phase 1 (Scrapers):**
```bash
curl -X POST "$SERVICE_URL/run-scraper" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "GetNbaComSchedule", "test_mode": true}'
```

**Phase 2 (Raw Processors):**
```bash
curl -X POST "$SERVICE_URL/health" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

**Phase 4 (Precompute):**
```bash
curl -X POST "$SERVICE_URL/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2025-12-26", "processors": ["MLFeatureStoreProcessor"], "dry_run": true}'
```

---

## AWS SES Configuration

### Required for Email Alerts

**Services needing AWS SES:**
- Phase 1 Scrapers (error alerts)
- Phase 2 Raw Processors (error alerts)
- Phase 4 Precompute (error alerts)
- Pipeline Health Summary (daily summary)

### Environment Variables

| Variable | Description |
|----------|-------------|
| `AWS_ACCESS_KEY_ID` | AWS IAM access key |
| `AWS_SECRET_ACCESS_KEY` | AWS IAM secret key |
| `AWS_REGION` | AWS region (e.g., `us-east-1`) |
| `EMAIL_SENDER` | Verified SES sender email |
| `CRITICAL_RECIPIENTS` | Comma-separated list of alert recipients |

### Adding AWS SES to a Service

```bash
# Example: Add AWS SES to Phase 4
gcloud run services update nba-phase4-precompute-processors \
  --region=us-west2 \
  --update-env-vars="AWS_ACCESS_KEY_ID=AKIA...,AWS_SECRET_ACCESS_KEY=...,AWS_REGION=us-east-1,EMAIL_SENDER=alerts@yourdomain.com,CRITICAL_RECIPIENTS=you@example.com"
```

### Verification

```bash
# Check AWS env vars are set
gcloud run revisions describe $LATEST_REV --region=us-west2 \
  --format="yaml(spec.template.spec.containers[0].env)" | grep -E "AWS_|EMAIL_|CRITICAL_"
```

---

## Troubleshooting

### Health Check Fails

```bash
# Check container logs for startup errors
gcloud logging read 'resource.labels.service_name="'$SERVICE'"' \
  --limit=50 --format="table(timestamp,textPayload)" --freshness=5m
```

**Common causes:**
1. Missing environment variables
2. Wrong Docker image
3. Dependency import errors
4. Port configuration issues

### Environment Variables Not Set

**Issue:** Deploy script shows "ENABLED" but env vars are missing

**Fix:** Verify the `--set-env-vars` flag is included in the deploy command:
```bash
gcloud run deploy $SERVICE \
  --set-env-vars="VAR1=value1,VAR2=value2"  # This line must be present
```

### Wrong Docker Image

**Issue:** Service runs wrong phase code (e.g., Phase 3 running Phase 4)

**Diagnosis:**
```bash
# Check current image
gcloud run services describe $SERVICE --region=us-west2 \
  --format="value(spec.template.spec.containers[0].image)"
```

**Fix:** Redeploy with correct Dockerfile:
```bash
gcloud builds submit --tag us-west2-docker.pkg.dev/nba-props-platform/nba-processors/$SERVICE \
  -f docker/correct-dockerfile.Dockerfile

gcloud run deploy $SERVICE --region=us-west2 \
  --image us-west2-docker.pkg.dev/nba-props-platform/nba-processors/$SERVICE
```

---

## All Services Quick Check

```bash
# Check all pipeline services at once
for svc in nba-phase1-scrapers nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-coordinator prediction-worker; do
  echo "=== $svc ==="
  URL=$(gcloud run services describe $svc --region=us-west2 --format='value(status.url)' 2>/dev/null)
  if [ -n "$URL" ]; then
    STATUS=$(curl -s "$URL/health" -H "Authorization: Bearer $(gcloud auth print-identity-token)" 2>/dev/null | jq -r '.status // "error"')
    echo "  Health: $STATUS"
    echo "  URL: $URL"
  else
    echo "  ERROR: Service not found"
  fi
done
```

---

## Related Documentation

- [v1.0 Deployment Guide](./v1.0-deployment-guide.md)
- [Troubleshooting Guide](../02-operations/troubleshooting.md)
- [Daily Monitoring](../02-operations/daily-monitoring.md)

---

**Last Updated:** 2025-12-27
