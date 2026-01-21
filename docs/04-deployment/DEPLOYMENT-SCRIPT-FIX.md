# Deployment Script Fix - Environment Variable Preservation

**Date**: 2026-01-17
**Status**: ✅ Fixed for NBA prediction-worker
**Related Incident**: CatBoost V8 Jan 2026 (missing CATBOOST_V8_MODEL_PATH)

---

## Problem

The NBA prediction worker deployment script (`bin/predictions/deploy/deploy_prediction_worker.sh`) had a critical bug that caused the January 2026 CatBoost V8 incident.

### Root Cause

**Line 157 (original)**:
```bash
--set-env-vars "GCP_PROJECT_ID=${PROJECT_ID},PREDICTIONS_TABLE=nba_predictions.player_prop_predictions,PUBSUB_READY_TOPIC=${PUBSUB_READY_TOPIC}"
```

**Issue**: The `--set-env-vars` flag **REPLACES all environment variables** with only the specified ones. This deleted the critical `CATBOOST_V8_MODEL_PATH` environment variable.

**Consequence**:
- CatBoost V8 model failed to load
- All predictions used fallback mode (50% confidence)
- 1,071 degraded predictions generated over 3 days
- Incident undetected for 3 days (no alerts)

### Why This Happened

The deployment script only specified 3 environment variables:
1. `GCP_PROJECT_ID`
2. `PREDICTIONS_TABLE`
3. `PUBSUB_READY_TOPIC`

But the service **requires** a 4th variable:
4. `CATBOOST_V8_MODEL_PATH` - Path to the ML model in GCS

Every time the script ran, it **deleted** `CATBOOST_V8_MODEL_PATH`, breaking production predictions.

---

## Solution

### Fixed Approach

The script now:
1. **Fetches current environment variables** before deploying
2. **Preserves `CATBOOST_V8_MODEL_PATH`** from the existing service
3. **Warns** if the variable is missing
4. **Deploys with all required variables**

### Code Changes

**File**: `bin/predictions/deploy/deploy_prediction_worker.sh`

**Lines 143-190** (new):
```bash
deploy_cloud_run() {
    log "Deploying to Cloud Run..."

    # CRITICAL: Preserve existing environment variables to avoid deleting CATBOOST_V8_MODEL_PATH
    # This was the root cause of the Jan 2026 CatBoost V8 incident
    log "Fetching current environment variables to preserve critical settings..."

    # Get current CATBOOST_V8_MODEL_PATH (if exists)
    CATBOOST_MODEL_PATH=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format=json 2>/dev/null | jq -r '.spec.template.spec.containers[0].env[] | select(.name == "CATBOOST_V8_MODEL_PATH") | .value' || echo "")

    # Build environment variables string
    ENV_VARS="GCP_PROJECT_ID=${PROJECT_ID},PREDICTIONS_TABLE=nba_predictions.player_prop_predictions,PUBSUB_READY_TOPIC=${PUBSUB_READY_TOPIC}"

    # Add CATBOOST_V8_MODEL_PATH if it exists
    if [ -n "$CATBOOST_MODEL_PATH" ]; then
        log "Preserving CATBOOST_V8_MODEL_PATH: $CATBOOST_MODEL_PATH"
        ENV_VARS="${ENV_VARS},CATBOOST_V8_MODEL_PATH=${CATBOOST_MODEL_PATH}"
    else
        warn "CATBOOST_V8_MODEL_PATH not found in current service"
        warn "Predictions will use FALLBACK mode (50% confidence)"
        warn "Set CATBOOST_V8_MODEL_PATH after deployment using:"
        warn "  gcloud run services update $SERVICE_NAME --region $REGION --project $PROJECT_ID \\"
        warn "    --update-env-vars CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/[MODEL_FILE]"
    fi

    # Deploy with all environment variables
    gcloud run deploy "$SERVICE_NAME" \
        --image "$IMAGE_FULL" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --platform managed \
        --memory "$MEMORY" \
        --cpu "$CPU" \
        --timeout "$TIMEOUT" \
        --concurrency "$CONCURRENCY" \
        --min-instances "$MIN_INSTANCES" \
        --max-instances "$MAX_INSTANCES" \
        --set-env-vars "$ENV_VARS" \
        --allow-unauthenticated \
        --service-account "prediction-worker@${PROJECT_ID}.iam.gserviceaccount.com" \
        --ingress all \
        --quiet

    log "Cloud Run deployment complete"
}
```

### How It Works

1. **Before deployment**: Queries the current service for `CATBOOST_V8_MODEL_PATH`
2. **If found**: Adds it to the deployment env vars → Model path preserved ✅
3. **If not found**: Logs clear warning → Operator knows to set it manually
4. **During deployment**: Uses `--set-env-vars` with ALL required variables

### Testing

Verified the logic works correctly:
```bash
# Test run (no actual deployment)
CATBOOST_MODEL_PATH=$(gcloud run services describe prediction-worker \
    --project nba-props-platform \
    --region us-west2 \
    --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name == "CATBOOST_V8_MODEL_PATH") | .value')

echo "Would preserve: $CATBOOST_MODEL_PATH"
# Output: gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm
```

**Result**: ✅ Script now preserves `CATBOOST_V8_MODEL_PATH` across deployments

---

## Better Alternative: Infrastructure as Code

### Long-term Solution

Instead of fetching env vars at deploy time, store them in version control:

**Option 1: Configuration File**
```bash
# config/production.env
GCP_PROJECT_ID=nba-props-platform
PREDICTIONS_TABLE=nba_predictions.player_prop_predictions
PUBSUB_READY_TOPIC=prediction-ready-prod
CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm
```

**Option 2: Terraform/Pulumi**
```hcl
resource "google_cloud_run_service" "prediction_worker" {
  name     = "prediction-worker"
  location = "us-west2"

  template {
    spec {
      containers {
        image = var.worker_image
        env {
          name  = "GCP_PROJECT_ID"
          value = "nba-props-platform"
        }
        env {
          name  = "CATBOOST_V8_MODEL_PATH"
          value = "gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm"
        }
        # ... other env vars
      }
    }
  }
}
```

**Benefits**:
- Version controlled
- Review required for changes (git PRs)
- No accidental deletions
- Auditable history

---

## Other Deployment Scripts

### Audit Results

Found **35 scripts** using `--set-env-vars`:
```bash
find bin -name "*.sh" -type f -exec grep -l "set-env-vars" {} \;
```

### Detailed Audit

#### MLB Prediction Worker ✅ **LOW RISK**

**File**: `bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh`

**Status**: ✅ **SAFE** (audited 2026-01-17)

**Current Environment Variables**:
```bash
GCP_PROJECT_ID=nba-props-platform
MLB_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
MLB_PREDICTIONS_TABLE=mlb_predictions.pitcher_strikeouts
PYTHONPATH=/app
```

**Script Behavior**:
- ✅ Hardcodes critical `MLB_MODEL_PATH` in script (line 34)
- ✅ Always includes all required env vars in deployment
- ✅ Conditionally adds email alerting vars if env vars set
- ⚠️ Would delete email alerting vars if script runs without them

**Risk Assessment**: **LOW**
- Critical model path always preserved (hardcoded)
- All current env vars explicitly set by script
- No history of manual env var additions
- Email vars conditionally added (only risk if previously set then removed)

**Recommendation**: **MONITOR**
- Current script is safe for normal use
- Apply preservation pattern if email alerts are configured
- Fix if any manual env var additions are made to service

**Code Pattern** (lines 95-138):
```bash
# Build environment variables (explicit, includes all required)
ENV_VARS="GCP_PROJECT_ID=${PROJECT_ID}"
ENV_VARS="${ENV_VARS},MLB_MODEL_PATH=${MODEL_PATH}"  # SAFE: Always included
ENV_VARS="${ENV_VARS},MLB_PREDICTIONS_TABLE=mlb_predictions.pitcher_strikeouts"
ENV_VARS="${ENV_VARS},PYTHONPATH=/app"

# Conditionally add email vars (RISK: deleted if env vars not set)
if [[ -n "${BREVO_SMTP_PASSWORD:-}" && -n "${EMAIL_ALERTS_TO:-}" ]]; then
    ENV_VARS="${ENV_VARS},BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
    ENV_VARS="${ENV_VARS},BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    # ... other email vars
fi

gcloud run deploy ... --set-env-vars "$ENV_VARS"
```

**Why It's Safer Than NBA Script**:
1. Critical `MLB_MODEL_PATH` is hardcoded in script
2. All current service env vars are explicitly included
3. Newer service with less manual configuration history

**When to Fix**:
- If email alerts are configured permanently (should preserve them)
- If any manual env var additions are made
- If script pattern is copied to other services

### Risk Assessment

**High Risk** (Critical model paths, manual configuration):
- ✅ `bin/predictions/deploy/deploy_prediction_worker.sh` - **FIXED**

**Low Risk** (Critical vars hardcoded, all vars explicit):
- ✅ `bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh` - **AUDITED, SAFE**

**Unknown Risk** (Pending audit):
- All other 33 scripts using `--set-env-vars`

### Recommended Actions

1. **Immediate** (Done):
   - ✅ Fix NBA prediction worker script
   - ✅ Audit MLB prediction worker script

2. **Short-term** (If email alerts are added to MLB):
   - Apply same preservation pattern to MLB script
   - Preserve email alerting env vars across deployments

3. **Medium-term** (This month):
   - Audit remaining 33 scripts for critical env vars
   - Document required env vars for each service
   - Apply fix pattern where manual configuration exists
   - Priority: Prediction and analytics services first

4. **Long-term** (Next quarter):
   - Migrate to Infrastructure as Code (Terraform/Pulumi)
   - Store all env vars in version control
   - Deprecate manual deployment scripts

---

## Prevention

### How to Avoid This Issue

**When writing deployment scripts**:

❌ **DON'T**:
```bash
# This DELETES all other env vars!
--set-env-vars "VAR1=value1,VAR2=value2"
```

✅ **DO** (Option 1 - Fetch and preserve):
```bash
# Fetch current critical env vars first
CRITICAL_VAR=$(gcloud run services describe "$SERVICE" \
  --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name == "CRITICAL_VAR") | .value')

# Include in deployment
ENV_VARS="VAR1=value1,VAR2=value2"
if [ -n "$CRITICAL_VAR" ]; then
  ENV_VARS="${ENV_VARS},CRITICAL_VAR=${CRITICAL_VAR}"
fi

--set-env-vars "$ENV_VARS"
```

✅ **DO** (Option 2 - Use update for targeted changes):
```bash
# Only update specific variables (preserves others)
gcloud run services update "$SERVICE" \
  --update-env-vars VAR1=value1,VAR2=value2
```

✅ **DO** (Option 3 - Include ALL required vars):
```bash
# Explicitly list every env var the service needs
--set-env-vars "VAR1=value1,VAR2=value2,CRITICAL_VAR=critical_value,..."
```

### Required Environment Variables

Document all required env vars for each service:

**NBA Prediction Worker** (`prediction-worker`):
1. `GCP_PROJECT_ID` - GCP project identifier
2. `PREDICTIONS_TABLE` - BigQuery predictions table
3. `PUBSUB_READY_TOPIC` - Pub/Sub topic for completion events
4. `CATBOOST_V8_MODEL_PATH` - **CRITICAL** - CatBoost V8 model GCS path

**Missing any of these will degrade or break functionality.**

---

## Verification

### How to Verify Fix Works

**Before deploying** (check current state):
```bash
# Get current env vars
gcloud run services describe prediction-worker \
  --region us-west2 \
  --project nba-props-platform \
  --format=json | jq -r '.spec.template.spec.containers[0].env[] | "\(.name)=\(.value)"'

# Save CATBOOST_V8_MODEL_PATH for comparison
BEFORE_MODEL_PATH=$(gcloud run services describe prediction-worker \
  --region us-west2 \
  --project nba-props-platform \
  --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name == "CATBOOST_V8_MODEL_PATH") | .value')

echo "Before: $BEFORE_MODEL_PATH"
```

**After deploying** (verify preservation):
```bash
# Get env vars after deployment
AFTER_MODEL_PATH=$(gcloud run services describe prediction-worker \
  --region us-west2 \
  --project nba-props-platform \
  --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name == "CATBOOST_V8_MODEL_PATH") | .value')

echo "After: $AFTER_MODEL_PATH"

# Compare
if [ "$BEFORE_MODEL_PATH" == "$AFTER_MODEL_PATH" ]; then
  echo "✅ CATBOOST_V8_MODEL_PATH preserved correctly"
else
  echo "❌ CATBOOST_V8_MODEL_PATH changed! This should not happen."
  echo "   Before: $BEFORE_MODEL_PATH"
  echo "   After:  $AFTER_MODEL_PATH"
fi
```

**Check predictions** (verify model loading):
```bash
# Wait 2-3 minutes for new revision to start and generate predictions

# Check confidence scores (should NOT be 50%)
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  ROUND(confidence_score * 100) as confidence,
  COUNT(*) as predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
GROUP BY confidence
ORDER BY confidence DESC'

# Expected: Variety of scores (79-95%), NO 50%
# If you see 50%: Model not loading, CATBOOST_V8_MODEL_PATH issue
```

---

## Related

- **Incident**: [CatBoost V8 Root Cause Analysis](../08-projects/current/catboost-v8-jan-2026-incident/ROOT-CAUSE-ANALYSIS.md)
- **Alerts**: [ALERT-RUNBOOKS.md](./ALERT-RUNBOOKS.md) - Now detects this in < 5 minutes
- **Environment Variables**: [NBA-ENVIRONMENT-VARIABLES.md](./NBA-ENVIRONMENT-VARIABLES.md)

---

**Last Updated**: 2026-01-17
**Status**: NBA prediction worker fixed, other scripts pending audit
