# Comprehensive Environment Variable Fix - Todo List

**Created**: 2026-01-17
**Incident**: CatBoost V8 missing CATBOOST_V8_MODEL_PATH
**Priority**: HIGH - Prevent similar incidents

---

## 🔴 CRITICAL - Fix Immediately (Today)

### 1. Fix Broken MLB Prediction Worker
**Issue**: mlb-prediction-worker missing multi-system configuration
**Impact**: HIGH - MLB predictions may be broken
**Evidence**: Agent audit found only single model path set

```bash
# Check current status
gcloud run services describe mlb-prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format=json | jq '.spec.template.spec.containers[0].env'

# Fix by redeploying with correct config
cd /home/naji/code/nba-stats-scraper
./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh

# Verify after deployment
gcloud run services describe mlb-prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format=json | jq '.spec.template.spec.containers[0].env'

# Expected: MLB_ACTIVE_SYSTEMS, MLB_V1_MODEL_PATH, MLB_V1_6_MODEL_PATH
```

**Files**:
- `/home/naji/code/nba-stats-scraper/bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh`
- `/home/naji/code/nba-stats-scraper/predictions/mlb/config.py`

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 2. Fix NBA Monitoring Alerts Service
**Issue**: SLACK_WEBHOOK_URL is empty string
**Impact**: HIGH - No alerts being sent
**Evidence**: Agent audit found `SLACK_WEBHOOK_URL: ""`

```bash
# Fix with correct webhook URL
gcloud run services update nba-monitoring-alerts \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars=SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR_WORKSPACE/YOUR_CHANNEL/YOUR_TOKEN

# Verify
gcloud run services describe nba-monitoring-alerts \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(spec.template.spec.containers[0].env[?name=='SLACK_WEBHOOK_URL'].value)"
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 3. Document Required Environment Variables
**Issue**: No centralized documentation of required env vars per service
**Impact**: HIGH - Prevents future incidents
**Evidence**: CatBoost incident caused by undocumented requirement

**Create**: `/home/naji/code/nba-stats-scraper/docs/04-deployment/ENVIRONMENT-VARIABLES.md`

**Template**:
```markdown
# Environment Variables Registry

## prediction-worker (NBA)
### Required
- `GCP_PROJECT_ID`: GCP project ID (default: nba-props-platform)
- `CATBOOST_V8_MODEL_PATH`: GCS path to CatBoost V8 model
  - Example: gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm
  - **CRITICAL**: Service falls back to 50% confidence if missing

### Optional
- `PREDICTIONS_TABLE`: BigQuery table for predictions (default: nba_predictions.player_prop_predictions)
- `PUBSUB_READY_TOPIC`: Pub/Sub topic for completion events (default: prediction-ready-prod)
- `BREVO_SMTP_PASSWORD`: Email alerts (if not set, alerting disabled)

## mlb-prediction-worker
### Required
- `GCP_PROJECT_ID`: GCP project ID
- `MLB_ACTIVE_SYSTEMS`: Comma-separated list of active systems (default: v1_baseline)
- `MLB_V1_MODEL_PATH`: GCS path to V1 model
- `MLB_V1_6_MODEL_PATH`: GCS path to V1.6 model

[... continue for all 43 services ...]
```

**Source Data**:
- Agent audit results in Session 81 findings
- `/home/naji/code/nba-stats-scraper/predictions/*/config.py`
- `/home/naji/code/nba-stats-scraper/bin/predictions/deploy/*`

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

## 🟡 HIGH PRIORITY - Fix This Week

### 4. Add Pre-Deployment Validation to Deployment Scripts
**Issue**: No validation that required env vars are set before deployment
**Impact**: MEDIUM - Prevents silent failures
**Evidence**: CatBoost V8 deployed without CATBOOST_V8_MODEL_PATH, no error

**Implementation**:

Create: `/home/naji/code/nba-stats-scraper/bin/shared/validate_env_vars.sh`

```bash
#!/bin/bash
# Environment variable validation for deployments

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

Create required vars files:
- `/home/naji/code/nba-stats-scraper/docs/04-deployment/required-vars/prediction-worker.txt`
- `/home/naji/code/nba-stats-scraper/docs/04-deployment/required-vars/mlb-prediction-worker.txt`
- `/home/naji/code/nba-stats-scraper/docs/04-deployment/required-vars/prediction-coordinator.txt`

**Update All Deployment Scripts**:

```bash
# Add to bin/predictions/deploy/deploy_prediction_worker.sh
source "$(dirname "$0")/../../shared/validate_env_vars.sh"

# Before gcloud run deploy
validate_required_env_vars \
    "prediction-worker" \
    "$ENV_VARS" \
    "docs/04-deployment/required-vars/prediction-worker.txt"

if [ $? -ne 0 ]; then
    echo "❌ Validation failed. Aborting deployment."
    exit 1
fi
```

**Files to Update** (36+ scripts):
- All scripts in `/home/naji/code/nba-stats-scraper/bin/predictions/deploy/`
- All scripts in `/home/naji/code/nba-stats-scraper/bin/scrapers/deploy/`
- All scripts in `/home/naji/code/nba-stats-scraper/bin/raw/deploy/`

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 5. Update Model Deployment Scripts to Use --update-env-vars
**Issue**: Scripts use --set-env-vars which DELETES other env vars
**Impact**: HIGH - Risk of losing unrelated env vars during model updates
**Evidence**: Deployment analysis shows all scripts use --set-env-vars

**Scripts to Update**:

1. `/home/naji/code/nba-stats-scraper/scripts/deploy_mlb_multi_model.sh`
   ```bash
   # BEFORE (DANGEROUS):
   gcloud run deploy mlb-prediction-worker \
     --set-env-vars="MLB_V1_MODEL_PATH=$V1_PATH,MLB_V1_6_MODEL_PATH=$V1_6_PATH"

   # AFTER (SAFE):
   gcloud run services update mlb-prediction-worker \
     --update-env-vars="MLB_V1_MODEL_PATH=$V1_PATH,MLB_V1_6_MODEL_PATH=$V1_6_PATH"
   ```

2. Create new script: `/home/naji/code/nba-stats-scraper/scripts/update_catboost_v8_model.sh`
   ```bash
   #!/bin/bash
   # Update CatBoost V8 model without affecting other env vars

   MODEL_PATH="$1"

   if [[ -z "$MODEL_PATH" ]]; then
       echo "Usage: $0 <GCS_MODEL_PATH>"
       exit 1
   fi

   gcloud run services update prediction-worker \
     --region=us-west2 \
     --project=nba-props-platform \
     --update-env-vars="CATBOOST_V8_MODEL_PATH=$MODEL_PATH"

   echo "✅ Updated CATBOOST_V8_MODEL_PATH to: $MODEL_PATH"
   ```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 6. Add GCP_PROJECT to Services with Only LOG_EXECUTION_ID
**Issue**: 3 services missing project ID env var
**Impact**: MEDIUM - May fail to access BigQuery/GCS
**Evidence**: Agent audit found missing GCP_PROJECT

**Services to Fix**:
1. `realtime-completeness-checker`
2. `self-heal-predictions`
3. `upcoming-tables-cleanup`

```bash
# Fix all three
for service in realtime-completeness-checker self-heal-predictions upcoming-tables-cleanup; do
    echo "Fixing $service..."
    gcloud run services update $service \
      --region=us-west2 \
      --project=nba-props-platform \
      --update-env-vars=GCP_PROJECT=nba-props-platform
done
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 7. Standardize Project ID Environment Variable Name
**Issue**: 3 different variable names used (GCP_PROJECT, GCP_PROJECT_ID, PROJECT_ID)
**Impact**: MEDIUM - Confusing, error-prone
**Evidence**: Agent audit found 19 services use GCP_PROJECT, 16 use GCP_PROJECT_ID, 2 use PROJECT_ID

**Decision**: Standardize on **GCP_PROJECT_ID** (most modern, matches Google Cloud naming)

**Services to Update** (19 services using GCP_PROJECT):
- backfill-trigger
- daily-health-summary
- dlq-monitor
- enrichment-trigger
- grading-delay-alert
- grading-readiness-monitor
- mlb-alert-forwarder
- phase2-to-phase3-orchestrator
- phase3-to-phase4-orchestrator
- phase4-timeout-check
- phase4-to-phase5
- phase4-to-phase5-orchestrator
- phase5-to-phase6
- phase5-to-phase6-orchestrator
- phase5b-grading
- phase6-export
- pipeline-health-summary
- pipeline-reconciliation
- prediction-health-alert
- self-heal-check
- shadow-performance-report
- stale-running-cleanup
- transition-monitor

**Services to Update** (2 services using PROJECT_ID):
- bigquery-backup
- nba-reference-service

**Migration Script**: `/home/naji/code/nba-stats-scraper/scripts/standardize_project_id_var.sh`

```bash
#!/bin/bash
# Migrate all services to use GCP_PROJECT_ID

SERVICES_GCP_PROJECT=(
    "backfill-trigger"
    "daily-health-summary"
    # ... all 19 services
)

SERVICES_PROJECT_ID=(
    "bigquery-backup"
    "nba-reference-service"
)

for service in "${SERVICES_GCP_PROJECT[@]}"; do
    echo "Migrating $service: GCP_PROJECT -> GCP_PROJECT_ID"

    # Get current value
    current_value=$(gcloud run services describe "$service" \
        --region=us-west2 \
        --project=nba-props-platform \
        --format="value(spec.template.spec.containers[0].env[?name=='GCP_PROJECT'].value)")

    # Set new variable
    gcloud run services update "$service" \
        --region=us-west2 \
        --project=nba-props-platform \
        --update-env-vars="GCP_PROJECT_ID=$current_value"

    # Remove old variable (if needed - check code first!)
    # gcloud run services update "$service" \
    #     --region=us-west2 \
    #     --remove-env-vars=GCP_PROJECT
done
```

**Code Changes Required**:
- Update all code reading `os.environ.get('GCP_PROJECT')` to use `GCP_PROJECT_ID`
- Update all code reading `os.environ.get('PROJECT_ID')` to use `GCP_PROJECT_ID`
- Update fallback chains to support both during transition

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 8. Fix MLB Phase 1 Scrapers Security Issue
**Issue**: API keys stored as plain text env vars instead of Secret Manager
**Impact**: HIGH - Security risk
**Evidence**: Agent audit found BDL_API_KEY and ODDS_API_KEY in plain text

**Current** (INSECURE):
```json
{
  "BDL_API_KEY": "REDACTED",
  "ODDS_API_KEY": "REDACTED"
}
```

**Target** (SECURE - like NBA scrapers):
```json
{
  "BDL_API_KEY": {"secretKeyRef": {"key": "latest", "name": "BDL_API_KEY"}},
  "ODDS_API_KEY": {"secretKeyRef": {"key": "latest", "name": "ODDS_API_KEY"}}
}
```

**Steps**:
1. Store keys in Secret Manager:
   ```bash
   echo -n "REDACTED" | \
     gcloud secrets create BDL_API_KEY --data-file=-

   echo -n "REDACTED" | \
     gcloud secrets create ODDS_API_KEY --data-file=-
   ```

2. Grant service account access:
   ```bash
   gcloud secrets add-iam-policy-binding BDL_API_KEY \
     --member="serviceAccount:mlb-phase1-scrapers@nba-props-platform.iam.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"

   gcloud secrets add-iam-policy-binding ODDS_API_KEY \
     --member="serviceAccount:mlb-phase1-scrapers@nba-props-platform.iam.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"
   ```

3. Update deployment script to use Secret Manager references (see NBA scraper deploy script for example)

4. Redeploy service

5. Delete old secrets from plain text env vars

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 9. Add Email Alerting to MLB Phase 3 Analytics
**Issue**: mlb-phase3-analytics-processors missing email alerting config
**Impact**: MEDIUM - No alerts on failures
**Evidence**: NBA phase 3 has full Brevo config, MLB doesn't

**Add to mlb-phase3-analytics-processors**:
```bash
gcloud run services update mlb-phase3-analytics-processors \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars="\
BREVO_SMTP_HOST=smtp-relay.brevo.com,\
BREVO_SMTP_PORT=587,\
BREVO_SMTP_USERNAME=YOUR_EMAIL@smtp-brevo.com,\
BREVO_SMTP_PASSWORD=xsmtpsib-...,\
BREVO_FROM_EMAIL=alert@989.ninja,\
BREVO_FROM_NAME=MLB Analytics,\
EMAIL_ALERTS_TO=nchammas@gmail.com,\
EMAIL_CRITICAL_TO=nchammas@gmail.com,\
EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=50,\
EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=90.0,\
EMAIL_ALERT_MAX_PROCESSING_TIME=30"
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

## 🟢 MEDIUM PRIORITY - Fix This Sprint

### 10. Add Deployment Metadata to All Services
**Issue**: Inconsistent metadata (COMMIT_SHA, GIT_BRANCH, DEPLOY_TIMESTAMP)
**Impact**: LOW - Harder to debug production issues
**Evidence**: Some services have it, some don't

**Standardize**:
All deployment scripts should set:
- `COMMIT_SHA`: Short git commit hash
- `COMMIT_SHA_FULL`: Full git commit hash
- `GIT_BRANCH`: Current git branch
- `DEPLOY_TIMESTAMP`: ISO 8601 timestamp

**Update**: `/home/naji/code/nba-stats-scraper/bin/shared/deploy_common.sh`

Add function:
```bash
get_deployment_metadata() {
    local commit_sha=$(git rev-parse --short HEAD)
    local commit_sha_full=$(git rev-parse HEAD)
    local git_branch=$(git rev-parse --abbrev-ref HEAD)
    local deploy_timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    echo "COMMIT_SHA=$commit_sha,COMMIT_SHA_FULL=$commit_sha_full,GIT_BRANCH=$git_branch,DEPLOY_TIMESTAMP=$deploy_timestamp"
}
```

Use in all deployment scripts:
```bash
METADATA=$(get_deployment_metadata)
ENV_VARS="$ENV_VARS,$METADATA"
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 11. Create Dockerfile Environment Variable Comments
**Issue**: Dockerfiles don't document which env vars are required at runtime
**Impact**: MEDIUM - Unclear what to set during deployment
**Evidence**: Dockerfile analysis shows minimal ENV documentation

**Example Update**: `/home/naji/code/nba-stats-scraper/docker/predictions-worker.Dockerfile`

```dockerfile
# Environment variables
# PYTHONPATH: Ensures imports work correctly
# PYTHONUNBUFFERED: Ensures logs appear immediately (not buffered)
# PORT: Default port for Cloud Run (overridden by Cloud Run at runtime)
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# REQUIRED at deployment (set via gcloud run deploy --set-env-vars):
# - GCP_PROJECT_ID: GCP project ID (required at startup)
# - CATBOOST_V8_MODEL_PATH: GCS path to CatBoost V8 model (gs://...)
#   * CRITICAL: Service falls back to 50% confidence predictions if missing
#
# OPTIONAL at deployment:
# - PREDICTIONS_TABLE: BigQuery table for predictions
#   * Default: nba_predictions.player_prop_predictions
# - PUBSUB_READY_TOPIC: Pub/Sub topic for completion events
#   * Default: prediction-ready-prod
# - BREVO_SMTP_PASSWORD: Enable email alerts (requires other BREVO_* vars)
```

**Files to Update**:
- All Dockerfiles in `/home/naji/code/nba-stats-scraper/docker/`
- All Dockerfiles in `/home/naji/code/nba-stats-scraper/predictions/*/Dockerfile`

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 12. Add Startup Validation for Critical Env Vars
**Issue**: Services start successfully even when critical env vars are missing
**Impact**: MEDIUM - Silent failures, delayed detection
**Evidence**: CatBoost V8 started without model path, ran for 3 days with fallback

**Implementation**:

Update: `/home/naji/code/nba-stats-scraper/predictions/worker/worker.py`

Add at startup (before Flask app starts):
```python
def validate_critical_env_vars():
    """Validate critical environment variables at startup"""
    required_vars = {
        'GCP_PROJECT_ID': 'GCP project ID',
        'CATBOOST_V8_MODEL_PATH': 'CatBoost V8 model GCS path',
    }

    missing_vars = []
    for var_name, description in required_vars.items():
        value = os.environ.get(var_name)
        if not value:
            missing_vars.append(f"{var_name} ({description})")

    if missing_vars:
        logger.error("=" * 80)
        logger.error("CRITICAL: Missing required environment variables!")
        logger.error("=" * 80)
        for var in missing_vars:
            logger.error(f"  ❌ {var}")
        logger.error("=" * 80)
        logger.error("Service will start but may not function correctly.")
        logger.error("Set missing variables and redeploy.")
        logger.error("=" * 80)

        # Option 1: Fail startup (strict)
        # raise RuntimeError("Missing required environment variables")

        # Option 2: Start but log critical error (current)
        pass

# Call at module level (before app starts)
validate_critical_env_vars()
```

**Files to Update**:
- `/home/naji/code/nba-stats-scraper/predictions/worker/worker.py`
- `/home/naji/code/nba-stats-scraper/predictions/mlb/worker.py`
- `/home/naji/code/nba-stats-scraper/predictions/coordinator/coordinator.py`
- All processor main files

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 13. Enable and Configure Terraform for Cloud Run
**Issue**: Terraform config exists but is disabled
**Impact**: MEDIUM - No infrastructure-as-code, manual drift
**Evidence**: `/home/naji/code/nba-stats-scraper/infra/cloud_run.tf` has all resources commented out

**Steps**:

1. Uncomment and update Terraform configs:
   - `/home/naji/code/nba-stats-scraper/infra/cloud_run.tf`
   - `/home/naji/code/nba-stats-scraper/infra/variables.tf`
   - `/home/naji/code/nba-stats-scraper/infra/terraform.tfvars`

2. Import existing Cloud Run services:
   ```bash
   cd /home/naji/code/nba-stats-scraper/infra

   terraform import google_cloud_run_service.prediction_worker \
     projects/nba-props-platform/locations/us-west2/services/prediction-worker

   # Repeat for all 43 services
   ```

3. Create environment variable definitions:
   ```terraform
   # infra/env_vars.tf
   locals {
     prediction_worker_env_vars = [
       {
         name  = "GCP_PROJECT_ID"
         value = var.project_id
       },
       {
         name  = "CATBOOST_V8_MODEL_PATH"
         value = var.catboost_v8_model_path
       },
       # ... all env vars
     ]
   }
   ```

4. Test with `terraform plan` to verify no changes
5. Enable in CI/CD for automated deployments

**Benefits**:
- Version controlled environment variables
- Pull request reviews for all config changes
- Automated drift detection
- Declarative infrastructure
- Audit trail in git history

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 14. Create Deep Health Check Endpoints
**Issue**: Health checks don't verify model loading or critical dependencies
**Impact**: MEDIUM - Service appears healthy but predictions fail
**Evidence**: CatBoost V8 passed health checks but used fallback predictions

**Implementation**:

Update: `/home/naji/code/nba-stats-scraper/predictions/worker/worker.py`

```python
@app.route('/health/deep', methods=['GET'])
def deep_health_check():
    """Deep health check that validates critical dependencies"""
    results = {
        'status': 'healthy',
        'checks': {},
        'timestamp': datetime.utcnow().isoformat()
    }

    # Check 1: Environment variables
    required_vars = ['GCP_PROJECT_ID', 'CATBOOST_V8_MODEL_PATH']
    missing_vars = [v for v in required_vars if not os.environ.get(v)]
    results['checks']['env_vars'] = {
        'status': 'ok' if not missing_vars else 'failed',
        'missing': missing_vars
    }

    # Check 2: Model loading
    try:
        catboost_system = get_catboost_v8_system()
        if catboost_system.model is None:
            results['checks']['model_loading'] = {
                'status': 'failed',
                'error': 'CatBoost V8 model not loaded'
            }
            results['status'] = 'unhealthy'
        else:
            results['checks']['model_loading'] = {
                'status': 'ok',
                'model_info': catboost_system.get_model_info()
            }
    except Exception as e:
        results['checks']['model_loading'] = {
            'status': 'failed',
            'error': str(e)
        }
        results['status'] = 'unhealthy'

    # Check 3: GCS access
    try:
        from google.cloud import storage
        client = storage.Client()
        model_path = os.environ.get('CATBOOST_V8_MODEL_PATH', '')
        if model_path.startswith('gs://'):
            parts = model_path.replace('gs://', '').split('/', 1)
            bucket_name = parts[0]
            blob_path = parts[1]

            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            blob.exists()  # Test read access

            results['checks']['gcs_access'] = {'status': 'ok'}
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
        client.query("SELECT 1").result()  # Test query
        results['checks']['bigquery_access'] = {'status': 'ok'}
    except Exception as e:
        results['checks']['bigquery_access'] = {
            'status': 'failed',
            'error': str(e)
        }
        results['status'] = 'unhealthy'

    status_code = 200 if results['status'] == 'healthy' else 503
    return jsonify(results), status_code
```

**Add to Cloud Run service config**:
```yaml
# In Terraform or gcloud deploy
livenessProbe:
  httpGet:
    path: /health
    port: 8080
startupProbe:
  httpGet:
    path: /health/deep
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
  failureThreshold: 3
```

**Files to Update**:
- All worker and coordinator services

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 15. Create Monitoring Alerts for Model Loading
**Issue**: No alerts when models fail to load
**Impact**: MEDIUM - Delayed detection of issues
**Evidence**: CatBoost V8 ran for 3 days without alert

**Implementation**:

1. **Log-based Metric** for model loading failures:
   ```bash
   gcloud logging metrics create model_load_failures \
     --description="Count of model loading failures" \
     --log-filter='resource.type="cloud_run_revision"
       AND (textPayload=~"model FAILED to load" OR textPayload=~"Model not loaded")'
   ```

2. **Alert Policy** for high failure rate:
   ```bash
   gcloud alpha monitoring policies create \
     --notification-channels=CHANNEL_ID \
     --display-name="Model Loading Failures" \
     --condition-display-name="Model load failure rate > 10%" \
     --condition-threshold-value=0.1 \
     --condition-threshold-duration=300s \
     --aggregation-alignment-period=60s \
     --condition-threshold-filter='metric.type="logging.googleapis.com/user/model_load_failures"'
   ```

3. **Log-based Metric** for fallback predictions:
   ```bash
   gcloud logging metrics create fallback_predictions \
     --description="Count of fallback predictions (50% confidence)" \
     --log-filter='resource.type="cloud_run_revision"
       AND textPayload=~"FALLBACK_PREDICTION"'
   ```

4. **Alert Policy** for high fallback rate:
   ```bash
   gcloud alpha monitoring policies create \
     --notification-channels=CHANNEL_ID \
     --display-name="High Fallback Prediction Rate" \
     --condition-display-name="Fallback rate > 10%" \
     --condition-threshold-value=0.1 \
     --condition-threshold-duration=300s
   ```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

## 🔵 LOW PRIORITY - Nice to Have

### 16. Create Deployment Verification Tests
**Issue**: No automated verification after deployment
**Impact**: LOW - Manual verification required

**Implementation**: E2E test script

Create: `/home/naji/code/nba-stats-scraper/scripts/verify_deployment.sh`

```bash
#!/bin/bash
# Post-deployment verification tests

SERVICE_NAME="$1"
REGION="${2:-us-west2}"
PROJECT="${3:-nba-props-platform}"

echo "🔍 Verifying deployment of $SERVICE_NAME..."

# Test 1: Service is healthy
echo "Test 1: Health check..."
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT" \
    --format="value(status.url)")

if curl -sf "$SERVICE_URL/health" > /dev/null; then
    echo "✅ Health check passed"
else
    echo "❌ Health check failed"
    exit 1
fi

# Test 2: Deep health check
echo "Test 2: Deep health check..."
if curl -sf "$SERVICE_URL/health/deep" > /dev/null; then
    echo "✅ Deep health check passed"
else
    echo "⚠️  Deep health check failed (may be expected)"
fi

# Test 3: Environment variables
echo "Test 3: Required env vars..."
ENV_VARS=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT" \
    --format=json | jq -r '.spec.template.spec.containers[0].env')

# Check for critical vars
if echo "$ENV_VARS" | jq -e '.[] | select(.name=="GCP_PROJECT_ID")' > /dev/null; then
    echo "✅ GCP_PROJECT_ID set"
else
    echo "❌ GCP_PROJECT_ID missing"
    exit 1
fi

echo "✅ All verification tests passed"
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 17. GitOps Workflow Implementation
**Issue**: No CI/CD pipeline for deployments
**Impact**: LOW - Manual deployments work but are error-prone

**Implementation**: GitHub Actions workflow

Create: `.github/workflows/deploy-cloud-run.yml`

```yaml
name: Deploy Cloud Run Services

on:
  push:
    branches:
      - main
    paths:
      - 'infra/**'
      - 'predictions/**'
      - 'data_processors/**'

jobs:
  terraform-plan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v2

      - name: Terraform Init
        run: terraform init
        working-directory: infra

      - name: Terraform Plan
        run: terraform plan -out=tfplan
        working-directory: infra

      - name: Upload Plan
        uses: actions/upload-artifact@v3
        with:
          name: tfplan
          path: infra/tfplan

  terraform-apply:
    needs: terraform-plan
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    environment: production
    steps:
      - uses: actions/checkout@v3

      - name: Download Plan
        uses: actions/download-artifact@v3
        with:
          name: tfplan
          path: infra

      - name: Terraform Apply
        run: terraform apply tfplan
        working-directory: infra

      - name: Verify Deployment
        run: ./scripts/verify_deployment.sh prediction-worker
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

### 18. Configuration Drift Detection
**Issue**: No automated detection of manual changes
**Impact**: LOW - Manual audit required

**Implementation**: Scheduled Cloud Function

```python
def detect_drift(event, context):
    """Detect environment variable drift from Terraform state"""

    # Load expected state from Terraform
    expected_state = load_terraform_state()

    # Get actual state from Cloud Run
    actual_state = get_cloud_run_state()

    # Compare
    drifts = compare_states(expected_state, actual_state)

    if drifts:
        send_alert(f"Configuration drift detected: {drifts}")
```

**Owner**: TBD
**Status**: ❌ NOT STARTED

---

## 📊 TRACKING SUMMARY

### By Priority

| Priority | Total Tasks | Completed | In Progress | Not Started |
|----------|-------------|-----------|-------------|-------------|
| 🔴 CRITICAL | 3 | 0 | 0 | 3 |
| 🟡 HIGH | 6 | 0 | 0 | 6 |
| 🟢 MEDIUM | 6 | 0 | 0 | 6 |
| 🔵 LOW | 3 | 0 | 0 | 3 |
| **TOTAL** | **18** | **0** | **0** | **18** |

### By Category

| Category | Tasks | Notes |
|----------|-------|-------|
| **Broken Services** | 2 | MLB worker, NBA alerts |
| **Documentation** | 1 | Environment variables registry |
| **Deployment Safety** | 4 | Validation, safe scripts, Terraform |
| **Environment Variables** | 4 | Standardization, security, consistency |
| **Monitoring & Alerts** | 2 | Model loading, fallback detection |
| **Health Checks** | 1 | Deep health endpoints |
| **Metadata & Tracking** | 1 | Deployment metadata |
| **Testing & Verification** | 1 | Post-deployment tests |
| **CI/CD & GitOps** | 2 | GitHub Actions, drift detection |

---

## 🎯 RECOMMENDED ORDER OF EXECUTION

### Week 1 (Immediate Fixes)
1. ✅ Fix mlb-prediction-worker (Task 1)
2. ✅ Fix nba-monitoring-alerts (Task 2)
3. ✅ Document environment variables (Task 3)
4. ✅ Add pre-deployment validation (Task 4)

### Week 2 (High Priority)
5. ✅ Update model deployment scripts (Task 5)
6. ✅ Add GCP_PROJECT to minimal services (Task 6)
7. ✅ Standardize project ID variable (Task 7)
8. ✅ Fix MLB API keys security (Task 8)
9. ✅ Add MLB email alerting (Task 9)

### Week 3 (Medium Priority - Infrastructure)
10. ✅ Add deployment metadata (Task 10)
11. ✅ Document Dockerfile env vars (Task 11)
12. ✅ Add startup validation (Task 12)
13. ✅ Enable Terraform (Task 13)

### Week 4 (Medium Priority - Monitoring)
14. ✅ Create deep health checks (Task 14)
15. ✅ Create monitoring alerts (Task 15)

### Future Sprints (Low Priority)
16. ✅ Deployment verification tests (Task 16)
17. ✅ GitOps workflow (Task 17)
18. ✅ Drift detection (Task 18)

---

## 📁 RELATED DOCUMENTS

- `/home/naji/code/nba-stats-scraper/docs/08-projects/current/catboost-v8-jan-2026-incident/ROOT-CAUSE-ANALYSIS.md`
- Agent Investigation Results (Session 81)
- `/home/naji/code/nba-stats-scraper/docs/09-handoff/SESSION-81-QUICK-START.md`

---

## ✅ SUCCESS CRITERIA

This todo list is complete when:
1. ✅ All 43 Cloud Run services have documented environment variables
2. ✅ All deployment scripts validate required env vars before deploying
3. ✅ No deployment script uses `--set-env-vars` for model updates
4. ✅ All services use consistent project ID variable name
5. ✅ All API keys stored in Secret Manager (no plain text)
6. ✅ Model loading failures trigger alerts within 5 minutes
7. ✅ Deep health checks verify critical dependencies
8. ✅ Terraform manages all Cloud Run configurations
9. ✅ No service is broken or missing critical env vars

---

**Last Updated**: 2026-01-17
**Next Review**: After completing Week 1 tasks
