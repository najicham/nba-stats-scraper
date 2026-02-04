# Environment Variable Management Runbook

**Last Updated:** 2026-02-03 (Session 108)

## Overview

This runbook provides safe patterns for managing environment variables in Cloud Run services. Following these patterns prevents critical incidents like Session 106/107 where env var drift caused production outages.

---

## Critical Warning

**NEVER use `--set-env-vars` - it REPLACES all environment variables**

**ALWAYS use `--update-env-vars` - it MERGES with existing variables**

### Real Incident: Session 106/107

**What happened:**
1. Session 106 needed to fix `CATBOOST_V8_MODEL_PATH`
2. Used `gcloud run services update --set-env-vars="CATBOOST_V8_MODEL_PATH=..."`
3. This **wiped out** all other env vars (GCP_PROJECT_ID, CATBOOST_V9_MODEL_PATH, PUBSUB_READY_TOPIC)
4. Worker crashed at startup with missing GCP_PROJECT_ID
5. Health checks failed, uptime alerts triggered
6. Session 107 had to manually restore all missing vars

**Impact:** 1+ hour of downtime, failed health checks, manual recovery required

---

## Flag Comparison

| Flag | Behavior | Use Case | Risk Level |
|------|----------|----------|------------|
| `--update-env-vars` | Adds or updates specific vars, preserves others | ✅ **Normal operations** | **SAFE** |
| `--remove-env-vars` | Removes specific vars, preserves others | Cleaning up obsolete vars | Low |
| `--clear-env-vars` | Removes ALL env vars | Starting fresh (rare) | Medium |
| `--set-env-vars` | **REPLACES ALL vars** | ❌ **NEVER USE** | **CRITICAL** |

---

## Safe Patterns

### 1. View Current Environment Variables

```bash
# Method 1: JSON format (parseable)
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --format="json" | jq '.spec.template.spec.containers[0].env'

# Method 2: YAML format (readable)
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --format="yaml(spec.template.spec.containers[0].env)"

# Method 3: List just names and values
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --format="yaml(spec.template.spec.containers[0].env)" | grep -E "name:|value:"
```

### 2. Add or Update Variables (SAFE)

```bash
# Update one variable
gcloud run services update prediction-worker \
  --region=us-west2 \
  --update-env-vars="GCP_PROJECT_ID=nba-props-platform"

# Update multiple variables
gcloud run services update prediction-worker \
  --region=us-west2 \
  --update-env-vars="GCP_PROJECT_ID=nba-props-platform,CATBOOST_V9_MODEL_PATH=gs://path/to/model.cbm,PUBSUB_READY_TOPIC=prediction-ready-prod"

# Update with build metadata
BUILD_COMMIT=$(git rev-parse --short HEAD)
BUILD_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

gcloud run services update prediction-worker \
  --region=us-west2 \
  --update-env-vars="BUILD_COMMIT=$BUILD_COMMIT,BUILD_TIMESTAMP=$BUILD_TIMESTAMP"
```

### 3. Remove Specific Variables

```bash
# Remove one variable
gcloud run services update prediction-worker \
  --region=us-west2 \
  --remove-env-vars="OBSOLETE_VAR"

# Remove multiple variables
gcloud run services update prediction-worker \
  --region=us-west2 \
  --remove-env-vars="OLD_VAR1,OLD_VAR2,OLD_VAR3"
```

### 4. Combine Update and Remove

```bash
# Update some vars and remove others in one command
gcloud run services update prediction-worker \
  --region=us-west2 \
  --update-env-vars="NEW_VAR=value,UPDATED_VAR=new_value" \
  --remove-env-vars="OLD_VAR1,OLD_VAR2"
```

---

## Service-Specific Requirements

### prediction-worker

**Required Environment Variables:**
- `GCP_PROJECT_ID` - Project identifier (required by env_validation.py)
- `CATBOOST_V8_MODEL_PATH` - V8 model GCS path
- `CATBOOST_V9_MODEL_PATH` - V9 model GCS path (production)
- `PUBSUB_READY_TOPIC` - Pub/Sub topic for prediction-ready events
- `BUILD_COMMIT` - Git commit hash (for tracking)
- `BUILD_TIMESTAMP` - Build time (for tracking)

**Optional Variables:**
- `PREDICTIONS_TABLE` - Override default table (defaults to `nba_predictions.player_prop_predictions`)
- `SENTRY_DSN` - Set via secret, not env var

**Validation:**

```bash
# Check all required vars are present
REQUIRED_VARS=("GCP_PROJECT_ID" "CATBOOST_V8_MODEL_PATH" "CATBOOST_V9_MODEL_PATH" "PUBSUB_READY_TOPIC")

ENV_JSON=$(gcloud run services describe prediction-worker \
  --region=us-west2 \
  --format="json" | jq -r '.spec.template.spec.containers[0].env')

for VAR in "${REQUIRED_VARS[@]}"; do
  VAL=$(echo "$ENV_JSON" | jq -r ".[] | select(.name==\"$VAR\") | .value // empty")
  if [ -z "$VAL" ]; then
    echo "❌ MISSING: $VAR"
  else
    echo "✅ $VAR = ${VAL:0:50}..."
  fi
done
```

### prediction-coordinator

**Required Environment Variables:**
- `GCP_PROJECT_ID`
- `BUILD_COMMIT`
- `BUILD_TIMESTAMP`

### All Services

**Standard Variables:**
- `GCP_PROJECT_ID` - Always required
- `BUILD_COMMIT` - Deployment tracking
- `BUILD_TIMESTAMP` - Deployment tracking

---

## Recovery Procedures

### If Environment Variables Get Wiped

**Symptoms:**
- Service crashes at startup
- Health checks return 503
- Logs show `KeyError: 'VARIABLE_NAME'`
- Multiple env vars missing

**Step 1: Verify the Damage**

```bash
# Check what vars remain
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --format="json" | jq '.spec.template.spec.containers[0].env'
```

**Step 2: Check Git History for Previous Values**

```bash
# Check deploy-service.sh for defaults
cat bin/deploy-service.sh | grep -A 5 "prediction-worker"

# Check recent handoffs for env var values
cat docs/09-handoff/*HANDOFF.md | grep -A 10 "Environment Variables"
```

**Step 3: Restore Required Variables**

```bash
# prediction-worker full restoration
gcloud run services update prediction-worker \
  --region=us-west2 \
  --update-env-vars="GCP_PROJECT_ID=nba-props-platform,CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm,CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm,PUBSUB_READY_TOPIC=prediction-ready-prod,BUILD_COMMIT=$(git rev-parse --short HEAD),BUILD_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

**Step 4: Verify Health**

```bash
# Check health endpoint
curl -s "https://prediction-worker-756957797294.us-west2.run.app/health/deep" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq '.status'

# Should return: "healthy"
```

**Step 5: Document the Incident**

Create a handoff documenting:
- What caused the env var loss
- What vars were affected
- How it was recovered
- Prevention mechanisms added

---

## Audit Trail

### Check What Changed

```bash
# Get revision history
gcloud run revisions list \
  --service=prediction-worker \
  --region=us-west2 \
  --limit=5

# Compare two revisions
REV1="prediction-worker-00105"
REV2="prediction-worker-00106"

# Get env vars from revision 1
gcloud run revisions describe $REV1 --region=us-west2 \
  --format="json" | jq -r '.spec.containers[0].env | sort_by(.name)'

# Get env vars from revision 2
gcloud run revisions describe $REV2 --region=us-west2 \
  --format="json" | jq -r '.spec.containers[0].env | sort_by(.name)'
```

### Find Who Changed It

```bash
# Check Cloud Logging for service updates
gcloud logging read \
  'protoPayload.methodName="google.cloud.run.v1.Services.ReplaceService"
   AND protoPayload.resourceName=~"prediction-worker"' \
  --limit=10 \
  --format='table(timestamp,protoPayload.authenticationInfo.principalEmail,protoPayload.request.spec.template.spec.containers[0].env)'
```

---

## Prevention

### 1. Always Use deploy-service.sh

The deploy script automatically preserves env vars for prediction-worker:

```bash
# CORRECT (uses deploy script)
./bin/deploy-service.sh prediction-worker

# WRONG (manual gcloud bypasses safety checks)
gcloud run deploy prediction-worker --source .
```

### 2. Pre-Deployment Checklist

Before any manual env var change:

- [ ] Check current env vars
- [ ] Document what you're changing and why
- [ ] Use `--update-env-vars`, never `--set-env-vars`
- [ ] Test health endpoint after change
- [ ] Document in handoff

### 3. Post-Deployment Verification

```bash
# Run after any env var change
./bin/check-deployment-drift.sh --verbose

# Verify health
curl -s SERVICE_URL/health/deep \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq
```

---

## Quick Reference Card

### ✅ DO

```bash
# Add/update variables
gcloud run services update SERVICE --update-env-vars="VAR=value"

# Remove specific variables
gcloud run services update SERVICE --remove-env-vars="VAR"

# Use deploy script
./bin/deploy-service.sh SERVICE
```

### ❌ DON'T

```bash
# NEVER use --set-env-vars (destructive)
gcloud run services update SERVICE --set-env-vars="VAR=value"  # ❌

# Don't bypass deploy script
gcloud run deploy SERVICE --source .  # ❌ (for prediction-worker)
```

---

## Related Documentation

- [DEPLOYMENT-TROUBLESHOOTING.md](../DEPLOYMENT-TROUBLESHOOTING.md) - General deployment issues
- [environment-variables.md](../../04-deployment/environment-variables.md) - Full env var reference
- [Session 106 Handoff](../../09-handoff/2026-02-03-SESSION-106-HANDOFF.md) - Model path fix incident
- [Session 107 Handoff](../../09-handoff/2026-02-03-SESSION-107-HANDOFF.md) - Env var drift recovery

---

## Session History

| Session | Date | Change | Outcome |
|---------|------|--------|---------|
| 106 | 2026-02-03 | Used `--set-env-vars` to fix V8 model path | Wiped all other env vars, worker crashed |
| 107 | 2026-02-03 | Manually restored all missing env vars | Health checks restored, service recovered |
| 108 | 2026-02-03 | Created this runbook | Prevention documentation |
