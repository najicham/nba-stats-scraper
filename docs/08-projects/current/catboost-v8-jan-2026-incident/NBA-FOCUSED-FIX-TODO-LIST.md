# NBA-Focused Environment Variable Fix - Todo List

**Created**: 2026-01-17
**Incident**: CatBoost V8 missing CATBOOST_V8_MODEL_PATH
**Scope**: NBA services only (MLB issues documented separately)
**Priority**: HIGH - Prevent similar incidents

---

## 🎯 NBA-SPECIFIC FOCUS

This document focuses ONLY on NBA prediction services and infrastructure. MLB-specific issues are documented in `MLB-ENVIRONMENT-ISSUES-HANDOFF.md` for the MLB team.

**NBA Services in Scope**:
- prediction-worker (NBA)
- prediction-coordinator
- nba-phase1-scrapers
- nba-phase2-raw-processors
- nba-phase3-analytics-processors
- nba-phase4-precompute-processors
- nba-monitoring-alerts
- nba-admin-dashboard
- nba-reference-service

---

## ✅ ALREADY COMPLETED (Session 81)

### 1. CatBoost V8 Environment Variable Restored
**Status**: ✅ COMPLETE
**Date**: 2026-01-17 18:38 UTC

```bash
# Already executed:
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars=CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm

# Result:
# - New revision: prediction-worker-00051-5xx
# - CATBOOST_V8_MODEL_PATH now set
# - Service serving 100% traffic
```

### 2. Broken Historical Data Cleaned
**Status**: ✅ COMPLETE
**Date**: 2026-01-17

```sql
-- Already executed:
DELETE FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-14'
  AND game_date <= '2026-01-17'
  AND confidence_score = 0.50

-- Result: 1,071 broken predictions deleted
-- Preserved: 13 model-based predictions from Jan 17
```

### 3. Root Cause Documented
**Status**: ✅ COMPLETE
**File**: `docs/08-projects/current/catboost-v8-jan-2026-incident/ROOT-CAUSE-ANALYSIS.md`

### 4. Coordinator Verified
**Status**: ✅ COMPLETE
**Finding**: Already using Docker builds, no issues found

---

## 🔴 CRITICAL - Fix Immediately (Today)

### 1. Fix NBA Monitoring Alerts Service
**Issue**: SLACK_WEBHOOK_URL is empty string
**Impact**: HIGH - No alerts being sent
**Time**: 5 minutes

**Current State**:
```json
{
  "SLACK_WEBHOOK_URL": "",
  "LOG_EXECUTION_ID": "true"
}
```

**Fix**:
```bash
gcloud run services update nba-monitoring-alerts \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars=SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR_WORKSPACE/YOUR_CHANNEL/YOUR_TOKEN_WORKSPACE/YOUR_CHANNEL/YOUR_WEBHOOK_TOKENbpkyh2Z8D9TLk50v1CHB8u
```

**Verify**:
```bash
gcloud run services describe nba-monitoring-alerts \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(spec.template.spec.containers[0].env[?name=='SLACK_WEBHOOK_URL'].value)"
```

**Expected**: Should return the webhook URL (not empty)

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 2. Document NBA Required Environment Variables
**Issue**: No centralized documentation
**Impact**: HIGH - Prevents future incidents
**Time**: 2 hours

**Create**: `/home/naji/code/nba-stats-scraper/docs/04-deployment/NBA-ENVIRONMENT-VARIABLES.md`

**Template**:
```markdown
# NBA Environment Variables Reference

Last Updated: 2026-01-17

## prediction-worker

### Required (Will Fail Without)
- `GCP_PROJECT_ID`: GCP project identifier
  - Default: 'nba-props-platform'
  - Example: `GCP_PROJECT_ID=nba-props-platform`
  - Impact if missing: Service fails to initialize

- `CATBOOST_V8_MODEL_PATH`: GCS path to CatBoost V8 model
  - No default (MUST be set)
  - Example: `CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm`
  - Impact if missing: ⚠️ **CRITICAL** - Falls back to 50% confidence predictions
  - Incident: Jan 14-17, 2026 - 1,071 failed predictions due to missing variable

### Optional (Has Defaults)
- `PREDICTIONS_TABLE`: BigQuery table for predictions
  - Default: 'nba_predictions.player_prop_predictions'
  - Example: `PREDICTIONS_TABLE=nba_predictions.player_prop_predictions`
  - Impact if missing: Uses default (usually correct)

- `PUBSUB_READY_TOPIC`: Pub/Sub topic for completion events
  - Default: 'prediction-ready-prod'
  - Example: `PUBSUB_READY_TOPIC=prediction-ready-prod`
  - Impact if missing: Uses default

### Email Alerting (Optional - All or None)
If email alerts desired, ALL must be set:
- `BREVO_SMTP_HOST`: Brevo SMTP server (default: smtp-relay.brevo.com)
- `BREVO_SMTP_PORT`: SMTP port (default: 587)
- `BREVO_SMTP_USERNAME`: Brevo username
- `BREVO_SMTP_PASSWORD`: Brevo password (from Secret Manager recommended)
- `BREVO_FROM_EMAIL`: Alert sender email
- `BREVO_FROM_NAME`: Alert sender name
- `EMAIL_ALERTS_TO`: Alert recipient email
- `EMAIL_CRITICAL_TO`: Critical alert recipient email

If any are missing, email alerts are silently disabled.

## prediction-coordinator

### Required
- `GCP_PROJECT_ID`: GCP project identifier
  - Default: 'nba-props-platform'
  - Validated at startup (line 136-139 of coordinator.py)

### Optional (Has Defaults)
- `PREDICTION_REQUEST_TOPIC`: Pub/Sub topic for worker requests
  - Default: 'prediction-request-prod'
- `PREDICTION_READY_TOPIC`: Pub/Sub topic for completion events
  - Default: 'prediction-ready-prod'
- `BATCH_SUMMARY_TOPIC`: Pub/Sub topic for batch summaries
  - Default: 'prediction-batch-complete'

[... continue for all NBA services ...]
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

## 🟡 HIGH PRIORITY - Fix This Week

### 3. Add Pre-Deployment Validation to NBA Deployment Scripts
**Issue**: No validation before deployment
**Impact**: MEDIUM - Prevents silent failures
**Time**: 3 hours

**Files to Create**:

1. **Validation Function**: `/home/naji/code/nba-stats-scraper/bin/shared/validate_env_vars.sh`

```bash
#!/bin/bash
# Environment variable validation for NBA deployments

validate_required_env_vars() {
    local service_name="$1"
    local env_vars="$2"  # Comma-separated KEY=VALUE pairs
    local required_vars_file="$3"  # Path to required vars list

    echo "🔍 Validating environment variables for $service_name..."

    # Check each required var
    local missing_vars=()
    while IFS= read -r var_name; do
        # Skip comments and empty lines
        [[ "$var_name" =~ ^#.*$ ]] && continue
        [[ -z "$var_name" ]] && continue

        # Check if var is in env_vars string
        if ! echo "$env_vars" | grep -q "$var_name="; then
            missing_vars+=("$var_name")
        fi
    done < "$required_vars_file"

    # Report results
    if [ ${#missing_vars[@]} -gt 0 ]; then
        echo "❌ ERROR: Missing required environment variables:"
        for var in "${missing_vars[@]}"; do
            echo "   - $var"
        done
        echo ""
        echo "Add these to your deployment script or use --update-env-vars"
        return 1
    fi

    echo "✅ All required environment variables present"
    return 0
}

export -f validate_required_env_vars
```

2. **Required Variables Files**:

`/home/naji/code/nba-stats-scraper/docs/04-deployment/required-vars/prediction-worker.txt`:
```
# Required environment variables for prediction-worker
GCP_PROJECT_ID
CATBOOST_V8_MODEL_PATH
```

`/home/naji/code/nba-stats-scraper/docs/04-deployment/required-vars/prediction-coordinator.txt`:
```
# Required environment variables for prediction-coordinator
GCP_PROJECT_ID
```

`/home/naji/code/nba-stats-scraper/docs/04-deployment/required-vars/nba-phase3-analytics-processors.txt`:
```
# Required environment variables for nba-phase3-analytics-processors
GCP_PROJECT_ID
```

3. **Update Deployment Scripts**:

Update `/home/naji/code/nba-stats-scraper/bin/predictions/deploy/deploy_prediction_worker.sh`:

```bash
# Add near top of file
source "$(dirname "$0")/../../shared/validate_env_vars.sh"

# Before gcloud run deploy
echo ""
echo "Validating environment variables..."
validate_required_env_vars \
    "prediction-worker" \
    "$ENV_VARS" \
    "$(dirname "$0")/../../../docs/04-deployment/required-vars/prediction-worker.txt"

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Validation failed. Aborting deployment."
    echo "Fix missing environment variables and try again."
    exit 1
fi
echo ""
```

**NBA Deployment Scripts to Update**:
- `/home/naji/code/nba-stats-scraper/bin/predictions/deploy/deploy_prediction_worker.sh`
- `/home/naji/code/nba-stats-scraper/bin/predictions/deploy/deploy_prediction_coordinator.sh`
- `/home/naji/code/nba-stats-scraper/bin/scrapers/deploy/deploy_scrapers_simple.sh` (NBA scrapers)
- `/home/naji/code/nba-stats-scraper/bin/analytics/deploy/deploy_analytics.sh` (if exists)

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 4. Create Safe NBA Model Update Script
**Issue**: No safe way to update model paths
**Impact**: MEDIUM - Risk during model updates
**Time**: 30 minutes

**Create**: `/home/naji/code/nba-stats-scraper/scripts/update_catboost_v8_model.sh`

```bash
#!/bin/bash
# Safely update CatBoost V8 model path without affecting other env vars

set -e

MODEL_PATH="$1"

if [[ -z "$MODEL_PATH" ]]; then
    echo "Usage: $0 <GCS_MODEL_PATH>"
    echo ""
    echo "Example:"
    echo "  $0 gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm"
    exit 1
fi

# Validate GCS path format
if [[ ! "$MODEL_PATH" =~ ^gs:// ]]; then
    echo "❌ ERROR: Model path must start with gs://"
    exit 1
fi

# Validate model file exists
if ! gsutil ls "$MODEL_PATH" > /dev/null 2>&1; then
    echo "❌ ERROR: Model file not found in GCS: $MODEL_PATH"
    exit 1
fi

echo "🔄 Updating CatBoost V8 model path..."
echo "   Old: (will be replaced)"
echo "   New: $MODEL_PATH"
echo ""

# Get current value for comparison
CURRENT_PATH=$(gcloud run services describe prediction-worker \
    --region=us-west2 \
    --project=nba-props-platform \
    --format="value(spec.template.spec.containers[0].env[?name=='CATBOOST_V8_MODEL_PATH'].value)" 2>/dev/null || echo "NOT SET")

echo "   Current: $CURRENT_PATH"
echo ""

# Confirm
read -p "Continue with update? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Update using --update-env-vars (safe, preserves other vars)
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars="CATBOOST_V8_MODEL_PATH=$MODEL_PATH"

echo ""
echo "✅ Updated CATBOOST_V8_MODEL_PATH to: $MODEL_PATH"
echo ""
echo "Verify new revision:"
gcloud run revisions list --service=prediction-worker --region=us-west2 --limit=3
echo ""
echo "Check logs for model loading:"
echo "  gcloud logging read 'resource.labels.service_name=prediction-worker AND textPayload=~\"CatBoost\"' --limit=10"
```

Make executable:
```bash
chmod +x /home/naji/code/nba-stats-scraper/scripts/update_catboost_v8_model.sh
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 5. Add Startup Validation to NBA Prediction Worker
**Issue**: Service starts without critical env vars
**Impact**: MEDIUM - Silent failures
**Time**: 1 hour

**Update**: `/home/naji/code/nba-stats-scraper/predictions/worker/worker.py`

Add near top of file (before Flask app initialization):

```python
import os
import logging

logger = logging.getLogger(__name__)

def validate_critical_env_vars():
    """Validate critical environment variables at startup"""

    critical_vars = {
        'GCP_PROJECT_ID': {
            'description': 'GCP project identifier',
            'required': True,
            'default': 'nba-props-platform'
        },
        'CATBOOST_V8_MODEL_PATH': {
            'description': 'CatBoost V8 model GCS path',
            'required': True,  # No default - MUST be set
            'default': None
        },
    }

    optional_vars = {
        'PREDICTIONS_TABLE': {
            'description': 'BigQuery predictions table',
            'default': 'nba_predictions.player_prop_predictions'
        },
        'PUBSUB_READY_TOPIC': {
            'description': 'Pub/Sub completion topic',
            'default': 'prediction-ready-prod'
        },
    }

    # Check critical variables
    missing_critical = []
    for var_name, var_info in critical_vars.items():
        value = os.environ.get(var_name)
        if not value and var_info['required'] and not var_info['default']:
            missing_critical.append(f"{var_name} ({var_info['description']})")
        elif value:
            logger.info(f"✓ {var_name}: {value[:50]}{'...' if len(value) > 50 else ''}")
        elif var_info['default']:
            logger.warning(f"⚠ {var_name}: Using default '{var_info['default']}'")

    # Log optional variables
    for var_name, var_info in optional_vars.items():
        value = os.environ.get(var_name)
        if value:
            logger.info(f"✓ {var_name}: {value}")
        else:
            logger.info(f"○ {var_name}: Using default '{var_info['default']}'")

    # Handle missing critical vars
    if missing_critical:
        logger.error("=" * 80)
        logger.error("❌ CRITICAL: Missing required environment variables!")
        logger.error("=" * 80)
        for var in missing_critical:
            logger.error(f"   {var}")
        logger.error("=" * 80)
        logger.error("⚠️  Service will start but predictions will use FALLBACK mode")
        logger.error("⚠️  This means:")
        logger.error("     - Confidence scores will be 50% (not actual model predictions)")
        logger.error("     - Recommendations will be 'PASS' (conservative)")
        logger.error("     - Prediction quality will be degraded")
        logger.error("=" * 80)
        logger.error("ACTION REQUIRED:")
        logger.error("  1. Set missing environment variables")
        logger.error("  2. Redeploy the service")
        logger.error("  3. Verify predictions have variable confidence (79-95%)")
        logger.error("=" * 80)

        # Option 1: Fail startup (strict mode - uncomment to enable)
        # raise RuntimeError(f"Missing required environment variables: {', '.join(missing_critical)}")

        # Option 2: Start anyway but log critical error (current behavior)
        # Service will run in fallback mode
    else:
        logger.info("=" * 80)
        logger.info("✅ All critical environment variables validated")
        logger.info("=" * 80)

# Call validation at module level (before app starts)
validate_critical_env_vars()
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 6. Add Deep Health Check to NBA Prediction Worker
**Issue**: Health checks don't verify model loading
**Impact**: MEDIUM - Service appears healthy but broken
**Time**: 1 hour

**Update**: `/home/naji/code/nba-stats-scraper/predictions/worker/worker.py`

Add new endpoint:

```python
@app.route('/health/deep', methods=['GET'])
def deep_health_check():
    """
    Deep health check that validates critical dependencies

    Checks:
    - Environment variables are set
    - CatBoost V8 model is loaded
    - GCS access works
    - BigQuery access works

    Returns:
        200: All checks passed
        503: One or more checks failed
    """
    from datetime import datetime
    import os

    results = {
        'status': 'healthy',
        'checks': {},
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'prediction-worker',
        'version': os.environ.get('K_REVISION', 'unknown')
    }

    # Check 1: Critical environment variables
    required_vars = ['GCP_PROJECT_ID', 'CATBOOST_V8_MODEL_PATH']
    missing_vars = [v for v in required_vars if not os.environ.get(v)]

    results['checks']['environment_variables'] = {
        'status': 'ok' if not missing_vars else 'failed',
        'required': required_vars,
        'missing': missing_vars
    }

    if missing_vars:
        results['status'] = 'unhealthy'

    # Check 2: CatBoost V8 model loading
    try:
        from prediction_systems.catboost_v8 import CatBoostV8

        # Get or create CatBoost system
        catboost_system = CatBoostV8()

        if catboost_system.model is None:
            results['checks']['model_loading'] = {
                'status': 'failed',
                'error': 'CatBoost V8 model not loaded - using fallback',
                'impact': 'Predictions will have 50% confidence (degraded quality)'
            }
            results['status'] = 'unhealthy'
        else:
            model_info = {
                'status': 'ok',
                'system_id': catboost_system.system_id,
                'model_version': catboost_system.model_version,
            }

            # Try to get model metadata if available
            if hasattr(catboost_system, 'metadata') and catboost_system.metadata:
                model_info['metadata'] = catboost_system.metadata

            results['checks']['model_loading'] = model_info
    except Exception as e:
        results['checks']['model_loading'] = {
            'status': 'failed',
            'error': str(e)
        }
        results['status'] = 'unhealthy'

    # Check 3: GCS access (verify model file accessible)
    try:
        from google.cloud import storage

        model_path = os.environ.get('CATBOOST_V8_MODEL_PATH', '')
        if model_path.startswith('gs://'):
            parts = model_path.replace('gs://', '').split('/', 1)
            bucket_name = parts[0]
            blob_path = parts[1] if len(parts) > 1 else ''

            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)

            # Test read access
            exists = blob.exists()

            results['checks']['gcs_access'] = {
                'status': 'ok' if exists else 'failed',
                'model_path': model_path,
                'exists': exists
            }

            if not exists:
                results['status'] = 'unhealthy'
        else:
            results['checks']['gcs_access'] = {
                'status': 'skipped',
                'reason': 'CATBOOST_V8_MODEL_PATH not a GCS path'
            }
    except Exception as e:
        results['checks']['gcs_access'] = {
            'status': 'failed',
            'error': str(e)
        }
        results['status'] = 'unhealthy'

    # Check 4: BigQuery access
    try:
        from google.cloud import bigquery

        client = bigquery.Client()
        # Simple test query
        query = "SELECT 1 as test"
        client.query(query).result()

        results['checks']['bigquery_access'] = {
            'status': 'ok'
        }
    except Exception as e:
        results['checks']['bigquery_access'] = {
            'status': 'failed',
            'error': str(e)
        }
        results['status'] = 'unhealthy'

    # Determine HTTP status code
    status_code = 200 if results['status'] == 'healthy' else 503

    return jsonify(results), status_code
```

**Test**:
```bash
# After deploying, test the endpoint
SERVICE_URL=$(gcloud run services describe prediction-worker \
    --region=us-west2 \
    --project=nba-props-platform \
    --format="value(status.url)")

curl -s "$SERVICE_URL/health/deep" | jq .
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

## 🟢 MEDIUM PRIORITY - Fix This Sprint

### 7. Create NBA Model Loading Alert
**Issue**: No alert when model fails to load
**Impact**: MEDIUM - Delayed detection
**Time**: 30 minutes

**Create Log-Based Metric**:
```bash
gcloud logging metrics create nba_model_load_failures \
  --project=nba-props-platform \
  --description="NBA prediction worker model loading failures" \
  --log-filter='resource.type="cloud_run_revision"
    AND resource.labels.service_name="prediction-worker"
    AND (textPayload=~"model FAILED to load" OR textPayload=~"FALLBACK_PREDICTION")'
```

**Create Alert Policy**:
```bash
# Get notification channel ID
CHANNEL_ID=$(gcloud alpha monitoring channels list \
  --project=nba-props-platform \
  --filter="displayName:Slack" \
  --format="value(name)")

# Create alert
gcloud alpha monitoring policies create \
  --project=nba-props-platform \
  --notification-channels="$CHANNEL_ID" \
  --display-name="NBA Model Loading Failures" \
  --condition-display-name="Model load failure rate > 10%" \
  --condition-threshold-value=0.1 \
  --condition-threshold-duration=300s \
  --aggregation-alignment-period=60s \
  --condition-threshold-filter='metric.type="logging.googleapis.com/user/nba_model_load_failures"
    resource.type="cloud_run_revision"'
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 8. Create NBA Fallback Prediction Alert
**Issue**: No alert when predictions use fallback (50% confidence)
**Impact**: MEDIUM - Silent degradation
**Time**: 30 minutes

**Create Log-Based Metric**:
```bash
gcloud logging metrics create nba_fallback_predictions \
  --project=nba-props-platform \
  --description="NBA predictions using fallback mode" \
  --log-filter='resource.type="cloud_run_revision"
    AND resource.labels.service_name="prediction-worker"
    AND textPayload=~"FALLBACK_PREDICTION"'
```

**Create Alert Policy**:
```bash
gcloud alpha monitoring policies create \
  --project=nba-props-platform \
  --notification-channels="$CHANNEL_ID" \
  --display-name="NBA High Fallback Prediction Rate" \
  --condition-display-name="Fallback rate > 10%" \
  --condition-threshold-value=0.1 \
  --condition-threshold-duration=300s \
  --aggregation-alignment-period=60s \
  --condition-threshold-filter='metric.type="logging.googleapis.com/user/nba_fallback_predictions"
    resource.type="cloud_run_revision"'
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 9. Update NBA Dockerfile Documentation
**Issue**: Dockerfile doesn't document runtime requirements
**Impact**: LOW - Unclear requirements
**Time**: 30 minutes

**Update**: `/home/naji/code/nba-stats-scraper/predictions/worker/Dockerfile`

Add comprehensive comments:

```dockerfile
# predictions/worker/Dockerfile
# NBA Phase 5 Prediction Worker - Cloud Run Deployment
#
# IMPORTANT: This Dockerfile sets build-time defaults.
# Several environment variables MUST be set at deployment time via Cloud Run.
#
# Build from repository root to include shared/ module:
#   docker build -f predictions/worker/Dockerfile -t worker .

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy shared module from repository root (relative to build context)
COPY shared/ ./shared/

# Copy worker code and dependencies
COPY predictions/worker/ ./predictions/worker/

# Set working directory to worker for running the service
WORKDIR /app/predictions/worker

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set Python path to include /app for shared module imports
ENV PYTHONPATH=/app:$PYTHONPATH

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# ============================================================================
# ENVIRONMENT VARIABLES REQUIRED AT DEPLOYMENT
# ============================================================================
#
# CRITICAL (Service degrades if missing):
#
# CATBOOST_V8_MODEL_PATH (NO DEFAULT - MUST SET)
#   - GCS path to CatBoost V8 model file
#   - Example: gs://nba-props-platform-models/catboost/v8/catboost_v8_*.cbm
#   - Impact if missing: Predictions fall back to 50% confidence
#   - Incident: Jan 14-17, 2026 - Service ran for 3 days without model
#
# GCP_PROJECT_ID (Default: 'nba-props-platform')
#   - GCP project identifier for BigQuery/GCS access
#   - Usually correct with default, but should be explicit
#
# OPTIONAL (Has sensible defaults):
#
# PREDICTIONS_TABLE (Default: 'nba_predictions.player_prop_predictions')
#   - BigQuery table for writing predictions
#
# PUBSUB_READY_TOPIC (Default: 'prediction-ready-prod')
#   - Pub/Sub topic for completion events
#
# EMAIL ALERTING (All or none):
#   BREVO_SMTP_HOST, BREVO_SMTP_PORT, BREVO_SMTP_USERNAME,
#   BREVO_SMTP_PASSWORD, BREVO_FROM_EMAIL, BREVO_FROM_NAME,
#   EMAIL_ALERTS_TO, EMAIL_CRITICAL_TO
#
# Deployment command example:
#   gcloud run deploy prediction-worker \
#     --image gcr.io/nba-props-platform/prediction-worker:latest \
#     --update-env-vars="CATBOOST_V8_MODEL_PATH=gs://path/to/model.cbm"
#
# ============================================================================

# Run worker with gunicorn
CMD exec gunicorn \
  --bind :${PORT:-8080} \
  --workers 1 \
  --threads 5 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  worker:app
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

## 📊 TRACKING SUMMARY

### By Priority

| Priority | Total Tasks | Completed | In Progress | Not Started |
|----------|-------------|-----------|-------------|-------------|
| ✅ **ALREADY DONE** | 4 | 4 | 0 | 0 |
| 🔴 **CRITICAL** | 2 | 0 | 0 | 2 |
| 🟡 **HIGH** | 4 | 0 | 0 | 4 |
| 🟢 **MEDIUM** | 3 | 0 | 0 | 3 |
| **TOTAL** | **13** | **4** | **0** | **9** |

### NBA Services Status

| Service | Critical Issues | Status |
|---------|----------------|--------|
| prediction-worker | ✅ Fixed (CATBOOST_V8_MODEL_PATH restored) | HEALTHY |
| prediction-coordinator | ✅ Verified working | HEALTHY |
| nba-monitoring-alerts | ❌ Empty webhook URL | BROKEN |
| nba-phase1-scrapers | ✅ Using Secret Manager | HEALTHY |
| nba-phase2-raw-processors | ✅ Good config | HEALTHY |
| nba-phase3-analytics-processors | ✅ Email alerts configured | HEALTHY |
| nba-phase4-precompute-processors | ✅ Minimal but working | HEALTHY |
| nba-admin-dashboard | ⚠️ Not audited | UNKNOWN |
| nba-reference-service | ⚠️ Uses PROJECT_ID (non-standard) | OK |

---

## 🎯 RECOMMENDED EXECUTION ORDER

### Day 1 (Today - 2 hours)
1. ✅ Fix nba-monitoring-alerts Slack webhook (5 min)
2. ✅ Create environment variables documentation (2 hours)

### Day 2 (3 hours)
3. ✅ Add pre-deployment validation (2 hours)
4. ✅ Create safe model update script (30 min)
5. ✅ Add startup validation (30 min)

### Day 3 (2 hours)
6. ✅ Add deep health check (1 hour)
7. ✅ Create model loading alerts (30 min)
8. ✅ Create fallback prediction alerts (30 min)

### Day 4 (30 min)
9. ✅ Update Dockerfile documentation (30 min)

**Total Time**: ~7.5 hours over 4 days

---

## ✅ SUCCESS CRITERIA

This NBA-focused todo list is complete when:

1. ✅ nba-monitoring-alerts webhook URL fixed and verified
2. ✅ All NBA services have documented required environment variables
3. ✅ All NBA deployment scripts validate env vars before deploying
4. ✅ Safe model update script exists and is tested
5. ✅ prediction-worker validates critical env vars at startup
6. ✅ Deep health check endpoint works and is monitored
7. ✅ Alerts trigger within 5 minutes of model loading failure
8. ✅ Dockerfile clearly documents runtime requirements
9. ✅ No NBA service has critical configuration issues

---

## 📁 RELATED DOCUMENTS

**NBA-Specific**:
- `docs/08-projects/current/catboost-v8-jan-2026-incident/ROOT-CAUSE-ANALYSIS.md`
- `docs/08-projects/current/catboost-v8-jan-2026-incident/NBA-FOCUSED-FIX-TODO-LIST.md` (this file)

**MLB-Specific** (for MLB team):
- `docs/08-projects/current/catboost-v8-jan-2026-incident/MLB-ENVIRONMENT-ISSUES-HANDOFF.md`

**Comprehensive** (all services):
- `docs/08-projects/current/catboost-v8-jan-2026-incident/COMPREHENSIVE-FIX-TODO-LIST.md`

---

**Document Created**: 2026-01-17
**Scope**: NBA services only
**Next Review**: After completing Day 1 tasks
