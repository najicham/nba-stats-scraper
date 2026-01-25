# Health Check Module - Usage Examples

This document provides examples of using the improved shared health check module.

## Table of Contents
1. [Basic Usage](#basic-usage)
2. [Custom BigQuery Checks](#custom-bigquery-checks)
3. [Model Availability Checks](#model-availability-checks)
4. [Custom Health Checks](#custom-health-checks)
5. [Enhanced Logging](#enhanced-logging)

---

## Basic Usage

### Simple Health Check (Default)

```python
from shared.endpoints.health import HealthChecker, create_health_blueprint

# Create basic health checker
checker = HealthChecker(
    project_id="nba-props-platform",
    service_name="my-service",
    check_bigquery=True  # Uses default SELECT 1 query
)

# Register with Flask app
app.register_blueprint(create_health_blueprint(checker))
```

**Endpoints:**
- `GET /health` - Basic liveness probe (always returns 200)
- `GET /ready` - Readiness probe with deep health checks
- `GET /health/deep` - Alias for `/ready`

---

## Custom BigQuery Checks

### Option 1: Custom Query

Execute a specific SQL query for validation:

```python
checker = HealthChecker(
    project_id="nba-props-platform",
    service_name="my-service",
    check_bigquery=True,
    bigquery_test_query="SELECT COUNT(*) FROM `my-project.my_dataset.my_table` LIMIT 1"
)
```

### Option 2: Table Check (NBA Worker Pattern)

Automatically checks for recent data in a table:

```python
checker = HealthChecker(
    project_id="nba-props-platform",
    service_name="nba-predictions-worker",
    check_bigquery=True,
    bigquery_test_table="nba_predictions.player_prop_predictions"
)
```

This will execute:
```sql
SELECT COUNT(*) as count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= CURRENT_DATE()
LIMIT 1
```

**Response includes row count:**
```json
{
  "check": "bigquery",
  "status": "pass",
  "service": "nba-predictions-worker",
  "details": {
    "query_type": "table_check",
    "table": "nba_predictions.player_prop_predictions",
    "connection": "successful",
    "row_count": 450
  },
  "duration_ms": 245
}
```

---

## Model Availability Checks

### Simple Model Check (GCS)

Check if a model file exists in Google Cloud Storage:

```python
from shared.endpoints.health import HealthChecker

# Create model check
model_check = HealthChecker.create_model_check(
    model_paths=['gs://nba-models/catboost_v8_33features_20260115.cbm']
)

# Create health checker with model check
checker = HealthChecker(
    project_id="nba-props-platform",
    service_name="nba-predictions-worker",
    check_bigquery=True,
    custom_checks={"model_availability": model_check}
)
```

### Local Model Check

Check if a local model file exists:

```python
model_check = HealthChecker.create_model_check(
    model_paths=['/models/catboost_v8.cbm']
)

checker = HealthChecker(
    project_id="nba-props-platform",
    service_name="my-service",
    custom_checks={"model_availability": model_check}
)
```

### Model Check with Fallback Directory

Primary model in GCS, fallback to local directory if needed:

```python
model_check = HealthChecker.create_model_check(
    model_paths=['gs://nba-models/catboost_v8_33features_20260115.cbm'],
    fallback_dir='/models'  # Will search for *.cbm and *.json files
)

checker = HealthChecker(
    project_id="nba-props-platform",
    service_name="nba-predictions-worker",
    custom_checks={"model_availability": model_check}
)
```

**Response:**
```json
{
  "check": "model_availability",
  "status": "pass",
  "details": {
    "model": {
      "status": "pass",
      "path": "gs://nba-models/catboost_v8_33features_20260115.cbm",
      "format_valid": true,
      "note": "Model loading deferred to first use (lazy load)"
    }
  },
  "duration_ms": 50
}
```

### Multiple Models Check

Check availability of multiple models:

```python
model_check = HealthChecker.create_model_check(
    model_paths=[
        'gs://nba-models/catboost_v8.cbm',
        'gs://nba-models/xgboost_v1.json',
        '/models/ensemble_v1.cbm'
    ]
)

checker = HealthChecker(
    project_id="nba-props-platform",
    service_name="nba-predictions-worker",
    custom_checks={"model_availability": model_check}
)
```

---

## Custom Health Checks

### Simple Custom Check

Create a custom check for any service dependency:

```python
from typing import Dict, Any

def check_redis_cache() -> Dict[str, Any]:
    """Check Redis cache connectivity."""
    import time
    start = time.time()

    try:
        # Your check logic here
        redis_client.ping()

        return {
            "check": "redis_cache",
            "status": "pass",
            "details": {"connected": True},
            "duration_ms": int((time.time() - start) * 1000)
        }
    except Exception as e:
        return {
            "check": "redis_cache",
            "status": "fail",
            "error": str(e),
            "duration_ms": int((time.time() - start) * 1000)
        }

# Add to health checker
checker = HealthChecker(
    project_id="nba-props-platform",
    service_name="my-service",
    custom_checks={"redis": check_redis_cache}
)
```

### Multiple Custom Checks

Combine multiple custom checks:

```python
def check_external_api() -> Dict[str, Any]:
    """Check external API availability."""
    import time
    import requests
    start = time.time()

    try:
        response = requests.get("https://api.example.com/health", timeout=2)
        response.raise_for_status()

        return {
            "check": "external_api",
            "status": "pass",
            "details": {"api_status": "healthy"},
            "duration_ms": int((time.time() - start) * 1000)
        }
    except Exception as e:
        return {
            "check": "external_api",
            "status": "fail",
            "error": str(e),
            "duration_ms": int((time.time() - start) * 1000)
        }

# Create model check
model_check = HealthChecker.create_model_check(
    model_paths=['gs://bucket/model.cbm'],
    fallback_dir='/models'
)

# Combine all checks
checker = HealthChecker(
    project_id="nba-props-platform",
    service_name="my-service",
    check_bigquery=True,
    check_gcs=True,
    gcs_buckets=["nba-scraped-data"],
    custom_checks={
        "model_availability": model_check,
        "redis": check_redis_cache,
        "external_api": check_external_api
    }
)
```

---

## Enhanced Logging

### Automatic Logging

The health checker now logs automatically:

```python
checker = HealthChecker(
    project_id="nba-props-platform",
    service_name="nba-predictions-worker",
    check_bigquery=True,
    bigquery_test_table="nba_predictions.player_prop_predictions"
)

result = checker.run_all_checks(parallel=True)
```

**Log Output:**
```
2026-01-18 10:30:15,123 - shared.endpoints.health - INFO - Starting health check execution for service: nba-predictions-worker
2026-01-18 10:30:15,456 - shared.endpoints.health - INFO - Health check execution completed for service: nba-predictions-worker | Status: healthy | Duration: 0.33s | Passed: 2/2 | Failed: 0 | Skipped: 0
```

### Slow Check Warnings

If a check takes >2 seconds:

```
2026-01-18 10:30:15,789 - shared.endpoints.health - WARNING - Health check 'bigquery' took 2.45s (threshold: 2.0s) - consider optimizing this check
```

### Total Duration Warnings

If total execution takes >4 seconds:

```
2026-01-18 10:30:18,123 - shared.endpoints.health - WARNING - Total health check duration 4.56s exceeded threshold (4.0s) - consider running checks in parallel or optimizing slow checks
```

### Error Logging with Stack Traces

Errors are logged with full exception info:

```
2026-01-18 10:30:15,789 - shared.endpoints.health - ERROR - BigQuery health check failed: Connection timeout
Traceback (most recent call last):
  File "/app/shared/endpoints/health.py", line 167, in check_bigquery_connectivity
    query_job = self.bq_client.query(query)
  ...
```

---

## Complete Real-World Example

### NBA Predictions Worker

```python
from flask import Flask
from shared.endpoints.health import HealthChecker, create_health_blueprint

app = Flask(__name__)

# Create model availability check
model_check = HealthChecker.create_model_check(
    model_paths=[os.environ.get('CATBOOST_V8_MODEL_PATH', '')],
    fallback_dir='/models'
)

# Create health checker with all features
checker = HealthChecker(
    project_id="nba-props-platform",
    service_name="nba-predictions-worker",
    check_bigquery=True,
    bigquery_test_table="nba_predictions.player_prop_predictions",  # Check recent predictions
    check_gcs=True,
    gcs_buckets=["nba-scraped-data"],
    required_env_vars=['GCP_PROJECT_ID', 'CATBOOST_V8_MODEL_PATH'],
    optional_env_vars=['PUBSUB_READY_TOPIC', 'PREDICTIONS_TABLE'],
    custom_checks={"model_availability": model_check}
)

# Register health endpoints
app.register_blueprint(create_health_blueprint(checker))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

**Health Check Response:**
```json
{
  "status": "healthy",
  "service": "nba-predictions-worker",
  "total_duration_ms": 456,
  "checks_run": 5,
  "checks_passed": 5,
  "checks_failed": 0,
  "checks_skipped": 0,
  "checks": [
    {
      "check": "environment",
      "status": "pass",
      "service": "nba-predictions-worker",
      "details": {
        "GCP_PROJECT_ID": {"status": "pass", "set": true},
        "CATBOOST_V8_MODEL_PATH": {"status": "pass", "set": true},
        "PUBSUB_READY_TOPIC": {"status": "pass", "set": true, "note": "configured"},
        "PREDICTIONS_TABLE": {"status": "pass", "set": true, "note": "configured"}
      },
      "duration_ms": 2
    },
    {
      "check": "bigquery",
      "status": "pass",
      "service": "nba-predictions-worker",
      "details": {
        "query_type": "table_check",
        "table": "nba_predictions.player_prop_predictions",
        "connection": "successful",
        "row_count": 450
      },
      "duration_ms": 245
    },
    {
      "check": "gcs",
      "status": "pass",
      "service": "nba-predictions-worker",
      "details": {
        "nba-scraped-data": {"status": "accessible"}
      },
      "duration_ms": 156
    },
    {
      "check": "model_availability",
      "status": "pass",
      "details": {
        "model": {
          "status": "pass",
          "path": "gs://nba-models/catboost_v8_33features_20260115.cbm",
          "format_valid": true,
          "note": "Model loading deferred to first use (lazy load)"
        }
      },
      "duration_ms": 50
    }
  ]
}
```

---

## Service Name in All Responses

All check responses now include the service name for better observability:

```json
{
  "check": "bigquery",
  "status": "pass",
  "service": "nba-predictions-worker",  // <-- Service name always included
  "details": {...},
  "duration_ms": 245
}
```

This makes it easier to:
- Track which service reported the issue in aggregated logs
- Debug health check failures across multiple services
- Monitor service-specific health metrics
