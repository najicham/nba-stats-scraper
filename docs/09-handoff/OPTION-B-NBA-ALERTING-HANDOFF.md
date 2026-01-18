# Option B: NBA Alerting & Visibility - Week 2-4 Implementation Handoff

**Created**: 2026-01-17
**Status**: Ready for Implementation (Week 1 Complete)
**Estimated Duration**: 26 hours (12h Week 2, 10h Week 3, 4h Week 4)
**Priority**: High (Operational Excellence)

---

## Executive Summary

Complete the 4-week NBA Alerting & Visibility Initiative by implementing environment variable monitoring (Week 2), dashboards and visibility tools (Week 3), and alert routing with documentation (Week 4). Week 1 (critical alerts) was completed on 2026-01-17, achieving 864x faster incident detection (5 minutes vs. 3 days).

### What Gets Better
- **Environment changes detected within 5 minutes** (prevents CatBoost V8 incident)
- **Deep health checks** validate all dependencies (GCS, BigQuery, models)
- **Cloud Monitoring dashboard** provides real-time visibility
- **Daily Slack summaries** keep team informed proactively
- **Complete alert routing** ensures right people notified

---

## Current State (As of 2026-01-17)

### Week 1 Status: ✅ COMPLETE

**Implemented** (Session 82 - Jan 17, 2026):
1. ✅ Model loading failure alert (`nba_model_load_failures`)
   - Fires when `CATBOOST_V8_MODEL_PATH` missing or model fails to load
   - Uses fallback prediction as detection signal
   - Log-based metric in Cloud Monitoring

2. ✅ High fallback prediction rate alert (`nba_fallback_predictions`)
   - Fires when >10% fallback rate over 10 minutes
   - Catches degraded model performance
   - Prevents multi-day silent failures

3. ✅ Startup validation in prediction worker
   - File: `/predictions/worker/worker.py` (lines 1-50)
   - Validates all model paths at service startup
   - Crashes service if models missing (fast failure)
   - Logs structured errors for monitoring

4. ✅ Deployment script fix
   - File: `/bin/predictions/deploy/deploy_prediction_worker.sh`
   - Changed `--set-env-vars` → `--update-env-vars`
   - Prevents accidental env var deletion
   - Preserves existing configuration

**Testing Status**: ⏳ Pending
- Alert testing script ready: `/bin/alerts/test_week1_alerts.sh`
- Requires 15-minute production window
- Will validate both alerts fire correctly
- Scheduled after this handoff implementation

### What's Next

**Week 2** (12 hours): Warning-level alerts
- Environment variable change detection
- Deep health check endpoint
- Health check monitoring

**Week 3** (10 hours): Dashboards & visibility
- Cloud Monitoring dashboard
- Daily prediction summaries to Slack
- Configuration audit dashboard

**Week 4** (4 hours): Info alerts & polish
- Deployment notification alerts
- Alert routing configuration
- Documentation and team training

---

## Week 2 Objectives & Success Criteria (12 hours)

### Objective 1: Environment Variable Change Detection
**Goal**: Detect when critical env vars change or disappear

**Success Criteria**:
- [ ] All 5 critical env vars monitored (model paths + active systems)
- [ ] Alert fires within 5 minutes of unexpected change
- [ ] Change details included in alert (old value → new value)
- [ ] Deployment-initiated changes don't trigger false alarms

### Objective 2: Deep Health Check Endpoint
**Goal**: Validate all dependencies, not just HTTP 200

**Success Criteria**:
- [ ] `/health/deep` endpoint validates:
  - [ ] GCS access (read test file from each model bucket)
  - [ ] BigQuery access (test query to nba_predictions table)
  - [ ] All 3 models loadable (XGBoost, CatBoost V8, ensemble logic)
  - [ ] Configuration valid (all env vars parseable)
- [ ] Response time <3 seconds (parallel checks)
- [ ] Detailed JSON response with per-check status

### Objective 3: Health Check Monitoring
**Goal**: Continuously monitor service health

**Success Criteria**:
- [ ] Cloud Monitoring uptime check calls `/health/deep` every 5 minutes
- [ ] Alert fires if 2 consecutive failures
- [ ] Alert includes which dependency failed
- [ ] Dashboard shows health check history

---

## Week 2 Detailed Implementation Plan

### Step 1: Environment Variable Change Detection (4 hours)

**1.1 Create Environment Snapshot Service**

Create: `/predictions/worker/env_monitor.py`

```python
"""
Environment variable monitoring service.

Tracks critical env vars and detects unexpected changes.
"""

import os
import json
import logging
from typing import Dict, Optional, Set
from datetime import datetime, timedelta
from google.cloud import storage
import hashlib

logger = logging.getLogger(__name__)

# Critical env vars to monitor
CRITICAL_ENV_VARS = {
    "XGBOOST_V1_MODEL_PATH",
    "CATBOOST_V8_MODEL_PATH",
    "NBA_ACTIVE_SYSTEMS",
    "NBA_MIN_CONFIDENCE",
    "NBA_MIN_EDGE"
}

class EnvVarMonitor:
    """Monitors environment variables for unexpected changes."""

    def __init__(self, bucket_name: str = "nba-scraped-data"):
        self.bucket_name = bucket_name
        self.snapshot_path = "env-snapshots/nba-prediction-worker-env.json"
        self.storage_client = storage.Client()
        self.deployment_window_minutes = 30  # Grace period for deployments

    def get_current_env_snapshot(self) -> Dict[str, str]:
        """Get current values of critical env vars."""
        return {
            var: os.getenv(var, "")
            for var in CRITICAL_ENV_VARS
        }

    def compute_env_hash(self, env_snapshot: Dict[str, str]) -> str:
        """Compute hash of env var values for change detection."""
        # Sort for deterministic hash
        sorted_items = sorted(env_snapshot.items())
        env_string = json.dumps(sorted_items, sort_keys=True)
        return hashlib.sha256(env_string.encode()).hexdigest()[:12]

    def load_baseline_snapshot(self) -> Optional[Dict]:
        """Load baseline env snapshot from GCS."""
        try:
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(self.snapshot_path)

            if not blob.exists():
                logger.info("No baseline snapshot found, will create")
                return None

            content = blob.download_as_text()
            return json.loads(content)
        except Exception as e:
            logger.error(f"Failed to load baseline snapshot: {e}")
            return None

    def save_baseline_snapshot(self, env_snapshot: Dict[str, str], reason: str = ""):
        """Save current env snapshot as new baseline."""
        try:
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(self.snapshot_path)

            snapshot_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "env_vars": env_snapshot,
                "env_hash": self.compute_env_hash(env_snapshot),
                "reason": reason
            }

            blob.upload_from_string(
                json.dumps(snapshot_data, indent=2),
                content_type="application/json"
            )

            logger.info(
                f"Saved baseline snapshot",
                extra={
                    "env_hash": snapshot_data["env_hash"],
                    "reason": reason,
                    "timestamp": snapshot_data["timestamp"]
                }
            )
        except Exception as e:
            logger.error(f"Failed to save baseline snapshot: {e}")

    def check_for_changes(self) -> Dict:
        """
        Check if env vars changed since baseline.

        Returns:
            Dict with:
                - changed: bool
                - changes: Dict[var_name, (old_value, new_value)]
                - in_deployment_window: bool
                - alert_needed: bool
        """
        current_env = self.get_current_env_snapshot()
        baseline = self.load_baseline_snapshot()

        result = {
            "changed": False,
            "changes": {},
            "in_deployment_window": False,
            "alert_needed": False,
            "current_env": current_env,
            "baseline_env": baseline.get("env_vars", {}) if baseline else {}
        }

        if not baseline:
            # No baseline, create one
            self.save_baseline_snapshot(current_env, reason="Initial baseline")
            return result

        baseline_env = baseline["env_vars"]
        baseline_timestamp = datetime.fromisoformat(baseline["timestamp"])

        # Check for differences
        for var in CRITICAL_ENV_VARS:
            old_value = baseline_env.get(var, "")
            new_value = current_env.get(var, "")

            if old_value != new_value:
                result["changed"] = True
                result["changes"][var] = {
                    "old": old_value,
                    "new": new_value,
                    "deleted": (old_value != "" and new_value == ""),
                    "added": (old_value == "" and new_value != "")
                }

        # Check if we're in deployment window
        time_since_baseline = datetime.utcnow() - baseline_timestamp
        result["in_deployment_window"] = (
            time_since_baseline < timedelta(minutes=self.deployment_window_minutes)
        )

        # Alert needed if: changed AND NOT in deployment window
        result["alert_needed"] = result["changed"] and not result["in_deployment_window"]

        return result

    def update_baseline_if_deployment(self, deployment_metadata: Dict = None):
        """
        Update baseline snapshot during planned deployment.

        Call this from deployment endpoint to prevent false alarms.
        """
        current_env = self.get_current_env_snapshot()
        reason = "Planned deployment"

        if deployment_metadata:
            reason = f"Deployment: {deployment_metadata.get('version', 'unknown')}"

        self.save_baseline_snapshot(current_env, reason=reason)
        logger.info("Baseline updated for deployment", extra=deployment_metadata or {})


# Global instance
env_monitor = EnvVarMonitor()
```

**1.2 Add Periodic Check Endpoint**

File: `/predictions/worker/worker.py`

```python
from env_monitor import env_monitor

@app.route('/internal/check-env', methods=['POST'])
def check_environment_variables():
    """
    Periodically called by Cloud Scheduler to detect env var changes.

    Expected to be called every 5 minutes.
    """
    try:
        result = env_monitor.check_for_changes()

        if result["alert_needed"]:
            # Log structured alert
            logger.error(
                "ALERT: Critical environment variables changed unexpectedly",
                extra={
                    "alert_type": "env_var_change",
                    "changes": result["changes"],
                    "changed_vars": list(result["changes"].keys()),
                    "change_count": len(result["changes"]),
                    "baseline_age_minutes": result.get("baseline_age_minutes", 0)
                }
            )

        return jsonify({
            "status": "alert" if result["alert_needed"] else "ok",
            "changed": result["changed"],
            "in_deployment_window": result["in_deployment_window"],
            "changes": result["changes"]
        }), 200

    except Exception as e:
        logger.error(f"Env check failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/internal/deployment-started', methods=['POST'])
def notify_deployment_started():
    """
    Called by deployment script to update baseline and prevent false alarms.

    Request body:
    {
      "version": "v2.1.0",
      "deployer": "user@example.com",
      "timestamp": "2026-01-17T10:00:00Z"
    }
    """
    try:
        deployment_info = request.get_json() or {}
        env_monitor.update_baseline_if_deployment(deployment_info)

        return jsonify({
            "status": "baseline_updated",
            "deployment_window_minutes": env_monitor.deployment_window_minutes
        }), 200

    except Exception as e:
        logger.error(f"Deployment notification failed: {e}")
        return jsonify({"error": str(e)}), 500
```

**1.3 Create Cloud Scheduler Job**

Create: `/bin/alerts/setup_env_monitoring.sh`

```bash
#!/bin/bash
set -e

PROJECT_ID="nba-data-warehouse-422817"
REGION="us-central1"
SERVICE_URL="https://nba-prediction-worker-756957797294.us-central1.run.app"

echo "Setting up environment variable monitoring..."

# Create Cloud Scheduler job to check env vars every 5 minutes
gcloud scheduler jobs create http nba-env-var-check \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="*/5 * * * *" \
  --uri="${SERVICE_URL}/internal/check-env" \
  --http-method=POST \
  --oidc-service-account-email="nba-scrapers@${PROJECT_ID}.iam.gserviceaccount.com" \
  --attempt-deadline=30s \
  --time-zone="America/New_York" \
  --description="Check for unexpected env var changes" \
  || echo "Job already exists, updating..."

gcloud scheduler jobs update http nba-env-var-check \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="*/5 * * * *" \
  --uri="${SERVICE_URL}/internal/check-env"

echo "✓ Cloud Scheduler job created/updated"

# Create log-based metric
gcloud logging metrics create nba_env_var_changes \
  --project="$PROJECT_ID" \
  --description="Count of unexpected env var changes" \
  --log-filter='resource.type="cloud_run_revision"
resource.labels.service_name="nba-prediction-worker"
jsonPayload.alert_type="env_var_change"
severity="ERROR"' \
  || echo "Metric already exists"

echo "✓ Log-based metric created"

# Create alert policy
cat > /tmp/env_var_alert_policy.yaml <<'EOF'
displayName: "NBA Prediction Worker - Environment Variable Changes"
conditions:
  - displayName: "Critical env vars changed unexpectedly"
    conditionThreshold:
      filter: 'resource.type="cloud_run_revision" AND metric.type="logging.googleapis.com/user/nba_env_var_changes"'
      comparison: COMPARISON_GT
      thresholdValue: 0
      duration: 60s
      aggregations:
        - alignmentPeriod: 60s
          perSeriesAligner: ALIGN_RATE
notificationChannels: []  # Add Slack channel ID
alertStrategy:
  autoClose: 3600s
documentation:
  content: |
    ## Environment Variable Change Detected

    Critical environment variables for the NBA prediction worker changed unexpectedly.

    **Possible Causes:**
    1. Deployment script used --set-env-vars instead of --update-env-vars
    2. Manual configuration change in Cloud Run console
    3. Automated tooling modified service config

    **Investigation Steps:**
    1. Check Cloud Logging for details:
       ```
       gcloud logging read 'jsonPayload.alert_type="env_var_change"' --limit 5
       ```
    2. Review recent deployments in Cloud Run console
    3. Compare current env vars to baseline in GCS:
       ```
       gsutil cat gs://nba-scraped-data/env-snapshots/nba-prediction-worker-env.json
       ```

    **Remediation:**
    1. If unintended: Redeploy with correct env vars using deployment script
    2. If intended: Update baseline via /internal/deployment-started endpoint
    3. Verify models load correctly with new configuration

    See: /docs/04-deployment/ALERT-RUNBOOKS.md#env-var-changes
EOF

gcloud alpha monitoring policies create --policy-from-file=/tmp/env_var_alert_policy.yaml \
  --project="$PROJECT_ID" \
  || echo "Alert policy already exists"

echo "✓ Alert policy created"
echo ""
echo "Setup complete! Env var monitoring active."
```

**1.4 Update Deployment Script**

File: `/bin/predictions/deploy/deploy_prediction_worker.sh`

Add after successful deployment:

```bash
# Notify service of deployment (prevents false alarms)
echo "Notifying service of deployment..."
curl -X POST "${SERVICE_URL}/internal/deployment-started" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d "{
    \"version\": \"${VERSION}\",
    \"deployer\": \"$(gcloud config get-value account)\",
    \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }" || echo "Warning: Could not notify deployment"
```

**1.5 Testing**
```bash
# Setup monitoring
./bin/alerts/setup_env_monitoring.sh

# Test 1: Manual env var check (should show no changes)
curl -X POST https://nba-prediction-worker-756957797294.us-central1.run.app/internal/check-env \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Test 2: Simulate deployment notification
curl -X POST https://nba-prediction-worker-756957797294.us-central1.run.app/internal/deployment-started \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"version": "test", "deployer": "test@example.com"}'

# Test 3: Wait 35 minutes, check again (should detect if vars changed)
sleep 2100
curl -X POST .../internal/check-env

# Test 4: Verify baseline snapshot in GCS
gsutil cat gs://nba-scraped-data/env-snapshots/nba-prediction-worker-env.json | jq .
```

---

### Step 2: Deep Health Check Endpoint (4 hours)

**2.1 Create Health Check Module**

Create: `/predictions/worker/health_checks.py`

```python
"""
Deep health checks for NBA prediction worker.

Validates all critical dependencies.
"""

import logging
import time
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import storage, bigquery
import xgboost as xgb
import os

logger = logging.getLogger(__name__)

class HealthChecker:
    """Performs deep health checks on all dependencies."""

    def __init__(self):
        self.storage_client = storage.Client()
        self.bq_client = bigquery.Client()
        self.timeout_seconds = 2.5  # Per-check timeout

    def check_gcs_access(self) -> Dict:
        """Verify GCS bucket access and model files exist."""
        start = time.time()
        checks = []

        model_paths = {
            "xgboost_v1": os.getenv("XGBOOST_V1_MODEL_PATH", ""),
            "catboost_v8": os.getenv("CATBOOST_V8_MODEL_PATH", "")
        }

        for model_name, gcs_path in model_paths.items():
            if not gcs_path:
                checks.append({
                    "model": model_name,
                    "status": "ERROR",
                    "error": "Path not configured"
                })
                continue

            try:
                # Parse gs://bucket/path
                if not gcs_path.startswith("gs://"):
                    raise ValueError(f"Invalid GCS path: {gcs_path}")

                parts = gcs_path[5:].split("/", 1)
                bucket_name = parts[0]
                blob_path = parts[1] if len(parts) > 1 else ""

                bucket = self.storage_client.bucket(bucket_name)
                blob = bucket.blob(blob_path)

                if blob.exists():
                    checks.append({
                        "model": model_name,
                        "status": "OK",
                        "path": gcs_path,
                        "size_mb": round(blob.size / 1024 / 1024, 2)
                    })
                else:
                    checks.append({
                        "model": model_name,
                        "status": "ERROR",
                        "error": "File not found",
                        "path": gcs_path
                    })

            except Exception as e:
                checks.append({
                    "model": model_name,
                    "status": "ERROR",
                    "error": str(e),
                    "path": gcs_path
                })

        elapsed = time.time() - start
        all_ok = all(c["status"] == "OK" for c in checks)

        return {
            "status": "OK" if all_ok else "ERROR",
            "checks": checks,
            "elapsed_seconds": round(elapsed, 3)
        }

    def check_bigquery_access(self) -> Dict:
        """Verify BigQuery access with test query."""
        start = time.time()

        try:
            # Simple test query
            query = """
            SELECT COUNT(*) as count
            FROM `nba-data-warehouse-422817.nba_predictions.player_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
            LIMIT 1
            """

            job_config = bigquery.QueryJobConfig(
                use_query_cache=True,
                timeout_ms=int(self.timeout_seconds * 1000)
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            row = next(result)
            count = row["count"]

            elapsed = time.time() - start

            return {
                "status": "OK",
                "recent_predictions_count": count,
                "elapsed_seconds": round(elapsed, 3)
            }

        except Exception as e:
            elapsed = time.time() - start
            return {
                "status": "ERROR",
                "error": str(e),
                "error_type": type(e).__name__,
                "elapsed_seconds": round(elapsed, 3)
            }

    def check_model_loading(self) -> Dict:
        """Verify models can be loaded from GCS."""
        start = time.time()
        checks = []

        model_paths = {
            "xgboost_v1": os.getenv("XGBOOST_V1_MODEL_PATH", ""),
            "catboost_v8": os.getenv("CATBOOST_V8_MODEL_PATH", "")
        }

        for model_name, gcs_path in model_paths.items():
            if not gcs_path:
                checks.append({
                    "model": model_name,
                    "status": "ERROR",
                    "error": "Path not configured"
                })
                continue

            try:
                # For XGBoost, try to load model
                if model_name.startswith("xgboost"):
                    model = xgb.Booster()
                    model.load_model(gcs_path)

                    checks.append({
                        "model": model_name,
                        "status": "OK",
                        "num_features": model.num_features() if hasattr(model, 'num_features') else None
                    })
                else:
                    # For CatBoost, just check file exists (already done in GCS check)
                    checks.append({
                        "model": model_name,
                        "status": "OK",
                        "note": "Lazy-loaded, validated via GCS check"
                    })

            except Exception as e:
                checks.append({
                    "model": model_name,
                    "status": "ERROR",
                    "error": str(e),
                    "error_type": type(e).__name__
                })

        elapsed = time.time() - start
        all_ok = all(c["status"] == "OK" for c in checks)

        return {
            "status": "OK" if all_ok else "ERROR",
            "checks": checks,
            "elapsed_seconds": round(elapsed, 3)
        }

    def check_configuration(self) -> Dict:
        """Verify all critical env vars are set and valid."""
        start = time.time()
        checks = []

        required_vars = {
            "XGBOOST_V1_MODEL_PATH": str,
            "CATBOOST_V8_MODEL_PATH": str,
            "NBA_ACTIVE_SYSTEMS": str,
            "NBA_MIN_CONFIDENCE": float,
            "NBA_MIN_EDGE": float
        }

        for var_name, var_type in required_vars.items():
            value = os.getenv(var_name)

            if value is None:
                checks.append({
                    "var": var_name,
                    "status": "ERROR",
                    "error": "Not set"
                })
                continue

            try:
                # Try to parse as expected type
                if var_type == float:
                    parsed = float(value)
                    checks.append({
                        "var": var_name,
                        "status": "OK",
                        "value": parsed
                    })
                elif var_type == int:
                    parsed = int(value)
                    checks.append({
                        "var": var_name,
                        "status": "OK",
                        "value": parsed
                    })
                else:
                    checks.append({
                        "var": var_name,
                        "status": "OK",
                        "value": value[:50] + "..." if len(value) > 50 else value
                    })

            except Exception as e:
                checks.append({
                    "var": var_name,
                    "status": "ERROR",
                    "error": f"Invalid {var_type.__name__}: {e}"
                })

        elapsed = time.time() - start
        all_ok = all(c["status"] == "OK" for c in checks)

        return {
            "status": "OK" if all_ok else "ERROR",
            "checks": checks,
            "elapsed_seconds": round(elapsed, 3)
        }

    def run_all_checks(self, parallel: bool = True) -> Dict:
        """
        Run all health checks.

        Args:
            parallel: Run checks concurrently (faster but more resource intensive)

        Returns:
            Dict with overall status and individual check results
        """
        start_time = time.time()
        results = {}

        if parallel:
            # Run checks in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {
                    executor.submit(self.check_gcs_access): "gcs",
                    executor.submit(self.check_bigquery_access): "bigquery",
                    executor.submit(self.check_model_loading): "models",
                    executor.submit(self.check_configuration): "configuration"
                }

                for future in as_completed(futures):
                    check_name = futures[future]
                    try:
                        results[check_name] = future.result(timeout=self.timeout_seconds)
                    except Exception as e:
                        results[check_name] = {
                            "status": "ERROR",
                            "error": f"Check failed: {e}",
                            "error_type": type(e).__name__
                        }
        else:
            # Run sequentially
            results["gcs"] = self.check_gcs_access()
            results["bigquery"] = self.check_bigquery_access()
            results["models"] = self.check_model_loading()
            results["configuration"] = self.check_configuration()

        elapsed = time.time() - start_time

        # Determine overall status
        all_ok = all(
            result.get("status") == "OK"
            for result in results.values()
        )

        return {
            "status": "healthy" if all_ok else "unhealthy",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "checks": results,
            "elapsed_seconds": round(elapsed, 3)
        }


# Global instance
health_checker = HealthChecker()
```

**2.2 Add Deep Health Endpoint**

File: `/predictions/worker/worker.py`

```python
from health_checks import health_checker

@app.route('/health/deep', methods=['GET'])
def deep_health_check():
    """
    Deep health check validating all dependencies.

    Returns 200 if healthy, 503 if unhealthy.
    """
    try:
        result = health_checker.run_all_checks(parallel=True)

        status_code = 200 if result["status"] == "healthy" else 503

        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"Deep health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }), 503
```

**2.3 Create Health Check Monitoring**

Create: `/bin/alerts/setup_health_monitoring.sh`

```bash
#!/bin/bash
set -e

PROJECT_ID="nba-data-warehouse-422817"
REGION="us-central1"
SERVICE_URL="https://nba-prediction-worker-756957797294.us-central1.run.app"

echo "Setting up deep health check monitoring..."

# Create uptime check
gcloud monitoring uptime create nba-worker-deep-health \
  --project="$PROJECT_ID" \
  --display-name="NBA Prediction Worker - Deep Health" \
  --resource-type=uptime-url \
  --http-check-path="/health/deep" \
  --monitored-resource="${SERVICE_URL}" \
  --period=300 \
  --timeout=10s \
  --checker-region=us-central1 \
  || echo "Uptime check already exists"

# Create alert policy for failed health checks
cat > /tmp/health_check_alert_policy.yaml <<'EOF'
displayName: "NBA Prediction Worker - Health Check Failures"
conditions:
  - displayName: "Deep health check failing"
    conditionThreshold:
      filter: 'resource.type="uptime_url" AND metric.type="monitoring.googleapis.com/uptime_check/check_passed"'
      comparison: COMPARISON_LT
      thresholdValue: 1
      duration: 300s
      aggregations:
        - alignmentPeriod: 300s
          perSeriesAligner: ALIGN_FRACTION_TRUE
notificationChannels: []
alertStrategy:
  autoClose: 1800s
documentation:
  content: |
    ## Health Check Failures Detected

    The deep health check endpoint is failing, indicating dependency issues.

    **Investigation Steps:**
    1. Check health endpoint manually:
       ```
       curl https://nba-prediction-worker-756957797294.us-central1.run.app/health/deep | jq .
       ```
    2. Review which checks are failing:
       - gcs: Model files not accessible
       - bigquery: Query failures or permissions
       - models: Model loading errors
       - configuration: Invalid env vars

    **Common Issues:**
    - GCS: Check bucket permissions, verify model paths
    - BigQuery: Verify service account has dataViewer role
    - Models: Check XGBOOST_V1_MODEL_PATH and CATBOOST_V8_MODEL_PATH
    - Config: Check all NBA_* env vars are set correctly

    See: /docs/04-deployment/ALERT-RUNBOOKS.md#health-check-failures
EOF

gcloud alpha monitoring policies create --policy-from-file=/tmp/health_check_alert_policy.yaml \
  --project="$PROJECT_ID" \
  || echo "Alert policy already exists"

echo "✓ Health check monitoring configured"
```

**2.4 Testing**
```bash
# Test deep health check
curl https://nba-prediction-worker-756957797294.us-central1.run.app/health/deep | jq .

# Expected output:
# {
#   "status": "healthy",
#   "timestamp": "2026-01-17T...",
#   "checks": {
#     "gcs": {"status": "OK", "checks": [...]},
#     "bigquery": {"status": "OK", ...},
#     "models": {"status": "OK", ...},
#     "configuration": {"status": "OK", ...}
#   },
#   "elapsed_seconds": 2.3
# }

# Setup monitoring
./bin/alerts/setup_health_monitoring.sh

# Verify uptime check created
gcloud monitoring uptime list --project=nba-data-warehouse-422817 | grep nba-worker
```

---

### Step 3: Update Alert Runbooks (1 hour)

File: `/docs/04-deployment/ALERT-RUNBOOKS.md`

Add sections for Week 2 alerts:

```markdown
## Environment Variable Changes

**Alert**: `NBA Prediction Worker - Environment Variable Changes`
**Severity**: WARNING
**Detection Time**: 5 minutes

### Symptoms
- Alert fires when critical env vars change unexpectedly
- Not within 30-minute deployment window

### Investigation

1. Check what changed:
   ```bash
   gcloud logging read 'jsonPayload.alert_type="env_var_change"' --limit 1 --format=json
   ```

2. Compare to baseline:
   ```bash
   gsutil cat gs://nba-scraped-data/env-snapshots/nba-prediction-worker-env.json | jq .
   ```

3. Check current service config:
   ```bash
   gcloud run services describe nba-prediction-worker \
     --region us-central1 \
     --format="value(spec.template.spec.containers[0].env)"
   ```

### Common Causes
- Deployment script used `--set-env-vars` instead of `--update-env-vars`
- Manual configuration change in Cloud Run console
- Automated tooling (Terraform, etc.) modified service

### Remediation

**If Unintended:**
```bash
# Redeploy with correct env vars
./bin/predictions/deploy/deploy_prediction_worker.sh
```

**If Intended (e.g., model upgrade):**
```bash
# Update baseline to prevent continued alerts
curl -X POST https://nba-prediction-worker-756957797294.us-central1.run.app/internal/deployment-started \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"version": "manual-fix", "deployer": "your-email"}'
```

---

## Health Check Failures

**Alert**: `NBA Prediction Worker - Health Check Failures`
**Severity**: WARNING
**Detection Time**: 10 minutes (2 consecutive 5-min checks)

### Symptoms
- Deep health check endpoint returns 503
- Uptime check failing in Cloud Monitoring

### Investigation

1. Check health endpoint:
   ```bash
   curl https://nba-prediction-worker-756957797294.us-central1.run.app/health/deep | jq .
   ```

2. Identify which check failed:
   - `gcs.status != "OK"`: GCS access issues
   - `bigquery.status != "OK"`: BigQuery access issues
   - `models.status != "OK"`: Model loading failures
   - `configuration.status != "OK"`: Invalid env vars

### Common Issues & Fixes

**GCS Access Failure:**
```bash
# Check if model files exist
gsutil ls $(gcloud run services describe nba-prediction-worker \
  --region us-central1 \
  --format="value(spec.template.spec.containers[0].env[?(@.name=='XGBOOST_V1_MODEL_PATH')].value)")

# Verify service account permissions
gcloud projects get-iam-policy nba-data-warehouse-422817 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:nba-prediction-worker"
```

**BigQuery Access Failure:**
```bash
# Test query manually
bq query --use_legacy_sql=false '
SELECT COUNT(*) FROM `nba_predictions.player_predictions`
WHERE game_date >= CURRENT_DATE() - 1'

# Check service account has BigQuery Data Viewer role
```

**Model Loading Failure:**
- Check XGBOOST_V1_MODEL_PATH and CATBOOST_V8_MODEL_PATH env vars
- Verify model files are valid (not corrupted)
- Check Cloud Run service has enough memory (2 Gi+)

**Configuration Invalid:**
- Review all NBA_* environment variables
- Check for typos or wrong data types
- Redeploy with correct configuration
```

**2.5 Deploy & Test**
```bash
# Deploy updated worker with health checks
./bin/predictions/deploy/deploy_prediction_worker.sh

# Setup monitoring
./bin/alerts/setup_env_monitoring.sh
./bin/alerts/setup_health_monitoring.sh

# Validate
curl .../health/deep | jq .
curl .../internal/check-env
```

---

## Week 3 Objectives & Success Criteria (10 hours)

### Objective 1: Cloud Monitoring Dashboard
**Goal**: Visual dashboard for real-time service monitoring

**Success Criteria**:
- [ ] Dashboard shows:
  - [ ] Prediction volume (requests/minute)
  - [ ] Fallback prediction rate
  - [ ] Model loading success rate
  - [ ] Response latency (p50, p95, p99)
  - [ ] Error rate
  - [ ] Active alerts
- [ ] Auto-refreshes every 1 minute
- [ ] Shareable link for team

### Objective 2: Daily Prediction Summaries
**Goal**: Proactive Slack notifications with prediction stats

**Success Criteria**:
- [ ] Sends to Slack daily at 9 AM ET
- [ ] Includes:
  - [ ] Yesterday's prediction count
  - [ ] Top players by confidence
  - [ ] System performance (fallback rate, errors)
  - [ ] Model health status
- [ ] Links to dashboard and logs

### Objective 3: Configuration Audit Dashboard
**Goal**: Track configuration changes over time

**Success Criteria**:
- [ ] BigQuery table tracks env var history
- [ ] Dashboard shows changes timeline
- [ ] Alerts when unexpected changes occur
- [ ] Exportable audit report

---

## Week 3 Implementation Plan

### Step 1: Cloud Monitoring Dashboard (4 hours)

**1.1 Create Dashboard JSON**

Create: `/bin/alerts/nba_monitoring_dashboard.json`

```json
{
  "displayName": "NBA Prediction Worker - Operational Dashboard",
  "mosaicLayout": {
    "columns": 12,
    "tiles": [
      {
        "width": 6,
        "height": 4,
        "widget": {
          "title": "Prediction Request Rate",
          "xyChart": {
            "dataSets": [
              {
                "timeSeriesQuery": {
                  "timeSeriesFilter": {
                    "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"nba-prediction-worker\" AND metric.type=\"run.googleapis.com/request_count\"",
                    "aggregation": {
                      "alignmentPeriod": "60s",
                      "perSeriesAligner": "ALIGN_RATE"
                    }
                  }
                },
                "plotType": "LINE"
              }
            ]
          }
        }
      },
      {
        "xPos": 6,
        "width": 6,
        "height": 4,
        "widget": {
          "title": "Response Latency (P95)",
          "xyChart": {
            "dataSets": [
              {
                "timeSeriesQuery": {
                  "timeSeriesFilter": {
                    "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"nba-prediction-worker\" AND metric.type=\"run.googleapis.com/request_latencies\"",
                    "aggregation": {
                      "alignmentPeriod": "60s",
                      "perSeriesAligner": "ALIGN_DELTA",
                      "crossSeriesReducer": "REDUCE_PERCENTILE_95"
                    }
                  }
                },
                "plotType": "LINE"
              }
            ]
          }
        }
      },
      {
        "yPos": 4,
        "width": 6,
        "height": 4,
        "widget": {
          "title": "Fallback Prediction Rate",
          "xyChart": {
            "dataSets": [
              {
                "timeSeriesQuery": {
                  "timeSeriesFilter": {
                    "filter": "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/nba_fallback_predictions\"",
                    "aggregation": {
                      "alignmentPeriod": "300s",
                      "perSeriesAligner": "ALIGN_RATE"
                    }
                  }
                },
                "plotType": "LINE",
                "targetAxis": "Y1"
              }
            ],
            "thresholds": [
              {
                "value": 0.1,
                "label": "Alert Threshold (10%)"
              }
            ]
          }
        }
      },
      {
        "xPos": 6,
        "yPos": 4,
        "width": 6,
        "height": 4,
        "widget": {
          "title": "Model Loading Failures",
          "xyChart": {
            "dataSets": [
              {
                "timeSeriesQuery": {
                  "timeSeriesFilter": {
                    "filter": "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/nba_model_load_failures\"",
                    "aggregation": {
                      "alignmentPeriod": "60s",
                      "perSeriesAligner": "ALIGN_RATE"
                    }
                  }
                },
                "plotType": "STACKED_BAR"
              }
            ]
          }
        }
      },
      {
        "yPos": 8,
        "width": 12,
        "height": 4,
        "widget": {
          "title": "Active Alerts",
          "incidentList": {
            "monitoredResources": [
              {
                "type": "cloud_run_revision",
                "labels": {
                  "service_name": "nba-prediction-worker"
                }
              }
            ]
          }
        }
      }
    ]
  }
}
```

**1.2 Deploy Dashboard**

Create: `/bin/alerts/create_monitoring_dashboard.sh`

```bash
#!/bin/bash
set -e

PROJECT_ID="nba-data-warehouse-422817"

echo "Creating Cloud Monitoring dashboard..."

gcloud monitoring dashboards create --config-from-file=bin/alerts/nba_monitoring_dashboard.json \
  --project="$PROJECT_ID" \
  || echo "Dashboard may already exist, updating..."

# Get dashboard URL
DASHBOARD_ID=$(gcloud monitoring dashboards list \
  --project="$PROJECT_ID" \
  --filter='displayName:"NBA Prediction Worker - Operational Dashboard"' \
  --format='value(name)' \
  | head -1)

echo ""
echo "✓ Dashboard created/updated"
echo "URL: https://console.cloud.google.com/monitoring/dashboards/custom/${DASHBOARD_ID}?project=${PROJECT_ID}"
```

---

### Step 2: Daily Slack Summaries (4 hours)

**2.1 Create Summary Generator**

Create: `/bin/alerts/daily_summary.py`

```python
#!/usr/bin/env python3
"""
Generate daily prediction summary and send to Slack.

Scheduled to run daily at 9 AM ET via Cloud Scheduler.
"""

import os
import sys
from datetime import date, timedelta
from google.cloud import bigquery
import requests
import json

def get_yesterday_stats():
    """Query BigQuery for yesterday's prediction stats."""
    client = bigquery.Client()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    query = f"""
    WITH predictions_summary AS (
      SELECT
        COUNT(*) as total_predictions,
        COUNTIF(confidence >= 70) as high_confidence_predictions,
        COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable_predictions,
        COUNTIF(recommendation = 'PASS') as pass_predictions,
        ROUND(AVG(confidence), 1) as avg_confidence,
        ROUND(MAX(confidence), 1) as max_confidence,
        COUNTIF(ARRAY_LENGTH(red_flags) > 0) as predictions_with_red_flags
      FROM `nba-data-warehouse-422817.nba_predictions.player_predictions`
      WHERE game_date = '{yesterday}'
    ),
    top_picks AS (
      SELECT
        player_name,
        predicted_points,
        points_line,
        confidence,
        recommendation
      FROM `nba-data-warehouse-422817.nba_predictions.player_predictions`
      WHERE game_date = '{yesterday}'
        AND recommendation IN ('OVER', 'UNDER')
      ORDER BY confidence DESC
      LIMIT 5
    ),
    system_health AS (
      SELECT
        COUNTIF(jsonPayload.alert_type = 'model_load_failure') as model_failures,
        COUNTIF(jsonPayload.fallback_used = true) as fallback_count
      FROM `nba-data-warehouse-422817._Default._AllLogs`
      WHERE timestamp >= TIMESTAMP('{yesterday}')
        AND timestamp < TIMESTAMP(DATE_ADD(TIMESTAMP('{yesterday}'), INTERVAL 1 DAY))
        AND resource.type = 'cloud_run_revision'
        AND resource.labels.service_name = 'nba-prediction-worker'
    )
    SELECT
      (SELECT AS STRUCT * FROM predictions_summary) as summary,
      ARRAY_AGG(STRUCT(player_name, predicted_points, points_line, confidence, recommendation)) as top_picks,
      (SELECT AS STRUCT * FROM system_health) as health
    FROM top_picks
    """

    result = client.query(query).result()
    row = next(result)

    return {
        "summary": dict(row["summary"]),
        "top_picks": [dict(pick) for pick in row["top_picks"]],
        "health": dict(row["health"])
    }

def format_slack_message(stats, yesterday_date):
    """Format stats as Slack message blocks."""
    summary = stats["summary"]
    top_picks = stats["top_picks"]
    health = stats["health"]

    fallback_rate = (health["fallback_count"] / summary["total_predictions"] * 100) if summary["total_predictions"] > 0 else 0

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📊 NBA Predictions Daily Summary - {yesterday_date}"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Total Predictions:*\n{summary['total_predictions']}"},
                {"type": "mrkdwn", "text": f"*Actionable (OVER/UNDER):*\n{summary['actionable_predictions']}"},
                {"type": "mrkdwn", "text": f"*Avg Confidence:*\n{summary['avg_confidence']}%"},
                {"type": "mrkdwn", "text": f"*High Confidence (≥70%):*\n{summary['high_confidence_predictions']}"}
            ]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Top 5 Picks (by confidence):*"
            }
        }
    ]

    for i, pick in enumerate(top_picks, 1):
        rec_emoji = "📈" if pick["recommendation"] == "OVER" else "📉"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{i}. {rec_emoji} *{pick['player_name']}* - {pick['recommendation']} {pick['points_line']}\n"
                        f"   Predicted: {pick['predicted_points']:.1f} | Confidence: {pick['confidence']:.1f}%"
            }
        })

    blocks.extend([
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*System Health:*"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Model Load Failures:*\n{health['model_failures']}"},
                {"type": "mrkdwn", "text": f"*Fallback Rate:*\n{fallback_rate:.1f}%"},
                {"type": "mrkdwn", "text": f"*Predictions with Red Flags:*\n{summary['predictions_with_red_flags']}"}
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "View <https://console.cloud.google.com/monitoring/dashboards|Dashboard> | <https://console.cloud.google.com/logs|Logs>"
                }
            ]
        }
    ])

    return {"blocks": blocks}

def send_to_slack(message):
    """Send message to Slack webhook."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("SLACK_WEBHOOK_URL not set, skipping Slack notification")
        print("Would have sent:", json.dumps(message, indent=2))
        return

    response = requests.post(webhook_url, json=message)
    response.raise_for_status()
    print(f"Sent to Slack: {response.status_code}")

def main():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    print(f"Generating summary for {yesterday}...")

    stats = get_yesterday_stats()
    message = format_slack_message(stats, yesterday)

    send_to_slack(message)
    print("✓ Daily summary sent")

if __name__ == "__main__":
    main()
```

**2.2 Deploy as Cloud Function**

Create: `/bin/alerts/deploy_daily_summary.sh`

```bash
#!/bin/bash
set -e

PROJECT_ID="nba-data-warehouse-422817"
REGION="us-central1"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"  # Set this env var

echo "Deploying daily summary Cloud Function..."

# Deploy function
gcloud functions deploy nba-daily-summary \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --runtime=python311 \
  --entry-point=main \
  --source=bin/alerts \
  --trigger-http \
  --allow-unauthenticated=false \
  --service-account=nba-scrapers@${PROJECT_ID}.iam.gserviceaccount.com \
  --set-env-vars="SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}" \
  --timeout=60s \
  --memory=256MB

# Create Cloud Scheduler job (daily at 9 AM ET = 2 PM UTC)
gcloud scheduler jobs create http nba-daily-summary \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="0 14 * * *" \
  --time-zone="America/New_York" \
  --uri="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/nba-daily-summary" \
  --http-method=POST \
  --oidc-service-account-email="nba-scrapers@${PROJECT_ID}.iam.gserviceaccount.com" \
  --attempt-deadline=60s \
  || echo "Scheduler job exists, updating..."

echo "✓ Daily summary deployed and scheduled for 9 AM ET"
```

---

### Step 3: Configuration Audit Dashboard (2 hours)

**3.1 Create Audit Log Table**

```sql
-- Create table to track env var changes
CREATE OR REPLACE TABLE `nba-data-warehouse-422817.nba_orchestration.env_var_audit` (
  timestamp TIMESTAMP,
  service_name STRING,
  change_type STRING,  -- 'deployment', 'manual', 'automated'
  changed_vars ARRAY<STRUCT<
    var_name STRING,
    old_value STRING,
    new_value STRING
  >>,
  env_hash STRING,
  deployer STRING,
  reason STRING,
  baseline_snapshot_path STRING
)
PARTITION BY DATE(timestamp)
OPTIONS(
  description="Audit log of environment variable changes for NBA prediction worker"
);

-- Create view for recent changes
CREATE OR REPLACE VIEW `nba-data-warehouse-422817.nba_orchestration.recent_env_changes` AS
SELECT
  timestamp,
  change_type,
  deployer,
  ARRAY_LENGTH(changed_vars) as num_changes,
  changed_vars
FROM `nba-data-warehouse-422817.nba_orchestration.env_var_audit`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
ORDER BY timestamp DESC;
```

**3.2 Update Env Monitor to Log Changes**

File: `/predictions/worker/env_monitor.py`

Add method:
```python
def log_change_to_bigquery(self, change_info: Dict):
    """Log env var change to BigQuery audit table."""
    from google.cloud import bigquery

    client = bigquery.Client()
    table_id = "nba-data-warehouse-422817.nba_orchestration.env_var_audit"

    rows = [{
        "timestamp": datetime.utcnow().isoformat(),
        "service_name": "nba-prediction-worker",
        "change_type": change_info.get("change_type", "unknown"),
        "changed_vars": [
            {
                "var_name": var,
                "old_value": details["old"],
                "new_value": details["new"]
            }
            for var, details in change_info.get("changes", {}).items()
        ],
        "env_hash": change_info.get("env_hash", ""),
        "deployer": change_info.get("deployer", ""),
        "reason": change_info.get("reason", ""),
        "baseline_snapshot_path": f"gs://{self.bucket_name}/{self.snapshot_path}"
    }]

    errors = client.insert_rows_json(table_id, rows)
    if errors:
        logger.error(f"Failed to log change to BigQuery: {errors}")
    else:
        logger.info("Change logged to BigQuery audit table")
```

---

## Week 4 Implementation (4 hours)

### Deployment Notifications

Create Slack alert when deployments complete:

```bash
# In deployment script, add at end:
curl -X POST "$SLACK_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d "{
    \"text\": \"✅ NBA Prediction Worker deployed\",
    \"blocks\": [
      {
        \"type\": \"section\",
        \"text\": {
          \"type\": \"mrkdwn\",
          \"text\": \"*NBA Prediction Worker* deployed successfully\n*Version:* ${VERSION}\n*Deployer:* $(gcloud config get-value account)\n*Image:* ${IMAGE_TAG}\"
        }
      }
    ]
  }"
```

### Alert Routing

Configure notification channels for different alert severities:
- **CRITICAL**: Page on-call, send to Slack
- **WARNING**: Slack only, no pages
- **INFO**: Log only, daily summary

### Documentation

Create team training materials and update handoff docs.

---

## Testing & Validation

See detailed testing procedures in each step above.

Key validation points:
- [ ] Week 2 alerts fire correctly
- [ ] Dashboard displays real-time data
- [ ] Daily summaries arrive in Slack
- [ ] Audit trail captures all changes

---

## References

- Implementation Roadmap: `/docs/04-deployment/IMPLEMENTATION-ROADMAP.md`
- Alert Runbooks: `/docs/04-deployment/ALERT-RUNBOOKS.md`
- Week 1 Session: `/docs/09-handoff/SESSION-82-IMPLEMENTATION-COMPLETE.md`
- NBA Env Vars: `/docs/04-deployment/NBA-ENVIRONMENT-VARIABLES.md`

---

**End of Handoff Document**
