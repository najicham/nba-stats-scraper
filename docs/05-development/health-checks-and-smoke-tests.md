# Health Checks and Smoke Tests

**Created:** Session 129 (Feb 5, 2026)
**Purpose:** Prevent silent service failures through defense-in-depth validation

---

## Overview

This document describes the health check and smoke test patterns implemented to prevent silent service failures like the Feb 4-5 grading service outage (39 hours down, undetected).

## The Problem

**What happened (Feb 4-5, 2026):**
- Grading service deployed with missing `predictions/` module
- Service container started successfully (basic health check passed)
- **Every grading request crashed** with `ModuleNotFoundError`
- Outage lasted 39 hours before detection
- Required manual regrade of 48 predictions

**Root cause:** Shallow health checks don't validate actual functionality

---

## Defense-in-Depth Strategy

We implement **5 layers of defense** to catch issues at different stages:

```
Layer 1: Build       - Dockerfile validation (future)
Layer 2: Test        - Dependency verification (existing)
Layer 3: Deploy      - Smoke tests (NEW - this doc)
Layer 4: Monitor     - Deep health checks (NEW - this doc)
Layer 5: Recover     - Auto-backfill (future)
```

---

## Layer 3: Deployment Smoke Tests

**Location:** `bin/deploy-service.sh` (Step 6.5/8)

**Purpose:** Verify service actually works before declaring deployment successful

### Smoke Test Pattern

Smoke tests run **immediately after deployment** and **before validation completes**.

**For each service:**
1. Test actual functionality (not just "is it running?")
2. Fail fast if tests don't pass
3. Provide clear rollback instructions

### Implementation

#### Grading Service Smoke Tests

```bash
# Test 1: Deep health check (validates critical imports)
DEEP_HEALTH=$(curl -s "$SERVICE_URL/health/deep")
DEEP_STATUS=$(echo "$DEEP_HEALTH" | jq -r '.status')

if [ "$DEEP_STATUS" != "healthy" ]; then
    echo "❌ CRITICAL: Deep health check FAILED"
    echo "Service deployed but cannot function correctly!"
    exit 1  # Fail deployment
fi

# Test 2: Basic service response
HEALTH_STATUS=$(curl -s "$SERVICE_URL/health" -w '%{http_code}')

if [ "$HEALTH_STATUS" != "200" ]; then
    echo "❌ CRITICAL: Health check failed"
    exit 1
fi
```

#### Adding Smoke Tests for New Services

To add smoke tests for a new service, edit `bin/deploy-service.sh`:

```bash
case "$SERVICE" in
  your-service-name)
    echo "Testing your service functionality..."

    # Test 1: Critical functionality
    echo "  [1/2] Testing critical feature..."
    RESPONSE=$(curl -s "$SERVICE_URL/your-critical-endpoint")
    # Validate response...

    # Test 2: Dependencies
    echo "  [2/2] Testing dependencies..."
    # Test database connectivity, external APIs, etc.
    ;;
esac
```

**Guidelines:**
- Keep tests fast (< 30 seconds total)
- Test actual functionality, not just availability
- Fail loudly with clear error messages
- Provide rollback instructions on failure

---

## Layer 4: Deep Health Checks

**Location:** Service code (e.g., `data_processors/grading/nba/main_nba_grading_service.py`)

**Purpose:** Continuous validation that service can perform its function

### Deep Health Check Pattern

Deep health checks validate **critical functionality**, not just process status.

**Standard checks:**
1. ✅ Critical module imports
2. ✅ Database connectivity
3. ✅ External service connectivity
4. ✅ Required environment variables

### Implementation

#### Example: Grading Service

```python
@app.route('/health/deep', methods=['GET'])
def health_check_deep():
    """
    Deep health check - validates critical functionality.

    Checks:
    1. Critical module imports (predictions, shared)
    2. BigQuery connectivity
    3. Firestore connectivity (for distributed locks)

    Returns 200 if all checks pass, 503 if any fail.
    """
    checks = {}
    all_healthy = True

    # Check 1: Critical imports
    try:
        from predictions.shared.distributed_lock import DistributedLock
        from shared.clients.bigquery_pool import get_bigquery_client
        checks['imports'] = {'status': 'ok'}
    except ImportError as e:
        checks['imports'] = {'status': 'failed', 'error': str(e)}
        all_healthy = False

    # Check 2: BigQuery connectivity
    try:
        client = get_bigquery_client()
        result = client.query("SELECT 1 as test").result()
        checks['bigquery'] = {'status': 'ok'}
    except Exception as e:
        checks['bigquery'] = {'status': 'failed', 'error': str(e)}
        all_healthy = False

    # Check 3: Firestore connectivity
    try:
        from google.cloud import firestore
        db = firestore.Client()
        collections = list(db.collections(max_results=1))
        checks['firestore'] = {'status': 'ok'}
    except Exception as e:
        checks['firestore'] = {'status': 'failed', 'error': str(e)}
        all_healthy = False

    status_code = 200 if all_healthy else 503
    return jsonify({
        "status": "healthy" if all_healthy else "unhealthy",
        "checks": checks
    }), status_code
```

#### Adding Deep Health Checks to Services

**Steps:**
1. Add `/health/deep` endpoint to your service
2. Test all critical imports
3. Test all external dependencies (databases, APIs)
4. Return 503 if ANY check fails
5. Return detailed check results in JSON

**Template:**

```python
@app.route('/health/deep', methods=['GET'])
def health_check_deep():
    checks = {}
    all_healthy = True

    # Check 1: Your critical imports
    try:
        import your_critical_module
        checks['imports'] = {'status': 'ok'}
    except ImportError as e:
        checks['imports'] = {'status': 'failed', 'error': str(e)}
        all_healthy = False

    # Check 2: Your critical dependency
    try:
        # Test database, API, etc.
        checks['dependency'] = {'status': 'ok'}
    except Exception as e:
        checks['dependency'] = {'status': 'failed', 'error': str(e)}
        all_healthy = False

    status_code = 200 if all_healthy else 503
    return jsonify({
        "status": "healthy" if all_healthy else "unhealthy",
        "checks": checks
    }), status_code
```

---

## Testing Your Implementation

### Test Deep Health Check Locally

```bash
# Start your service locally
python main_service.py

# Test deep health check
curl http://localhost:8080/health/deep | jq

# Expected (healthy):
{
  "status": "healthy",
  "checks": {
    "imports": {"status": "ok"},
    "bigquery": {"status": "ok"},
    "firestore": {"status": "ok"}
  }
}

# Expected (unhealthy - missing module):
{
  "status": "unhealthy",
  "checks": {
    "imports": {
      "status": "failed",
      "error": "No module named 'predictions'"
    }
  }
}
```

### Test Smoke Tests in Deployment

```bash
# Deploy with smoke tests enabled (default)
./bin/deploy-service.sh nba-grading-service

# Smoke tests run automatically at step [6.5/8]
# If tests fail, deployment will exit with error code 1
```

### Simulate a Failure

To test that smoke tests catch issues:

```bash
# Temporarily break the service
# (e.g., remove a module from Dockerfile)

# Deploy
./bin/deploy-service.sh nba-grading-service

# Expected: Deployment fails at smoke test step
# Output:
# ❌ SMOKE TESTS FAILED
# Service deployed but smoke tests failed!
# To rollback: ...
```

---

## Monitoring and Alerting

### Continuous Monitoring

Deep health checks should be monitored continuously:

```bash
# Add to Cloud Monitoring
# Alert if /health/deep returns 503 for > 2 minutes

# Uptime check configuration
gcloud monitoring uptime-checks create https \
    --display-name="grading-deep-health" \
    --resource-type="uptime-url" \
    --monitored-resource="https://nba-grading-service-*.run.app/health/deep" \
    --check-interval=60s
```

### Alerting Strategy

**Basic health check (`/health`):**
- Checked by Cloud Run
- Alert: Service is down (container crash)

**Deep health check (`/health/deep`):**
- Checked by uptime monitoring
- Alert: Service is up but cannot function

**Smoke tests:**
- Run during deployment
- Alert: Deployment succeeded but service broken
- Action: Auto-rollback (future) or manual rollback

---

## Best Practices

### Do's ✅

- **Test actual functionality**, not just process status
- **Fail fast** - return 503 if ANY critical check fails
- **Be specific** - include error details in unhealthy responses
- **Keep it fast** - deep health checks should complete in < 5 seconds
- **Test on every request** - for lightweight checks (imports)
- **Cache results** - for expensive checks (database queries)

### Don'ts ❌

- **Don't just check if the process is running** - that's what basic health does
- **Don't ignore failures** - if a check fails, the service is unhealthy
- **Don't test non-critical features** - focus on core functionality
- **Don't make it slow** - keep total check time under 5 seconds
- **Don't hide errors** - surface issues clearly in response

---

## Troubleshooting

### Smoke Tests Fail After Deployment

**Symptoms:**
```
❌ SMOKE TESTS FAILED
Deep health check failed
```

**Diagnosis:**
1. Check what specific check failed:
   ```bash
   curl https://SERVICE-URL/health/deep | jq
   ```
2. Look at the error message in the `checks` object
3. Common issues:
   - Missing module (Dockerfile COPY missing)
   - Missing environment variable
   - Database connectivity issue

**Fix:**
1. Fix the root cause (e.g., add missing COPY to Dockerfile)
2. Redeploy:
   ```bash
   ./bin/deploy-service.sh SERVICE_NAME
   ```

### Deep Health Check Always Returns Unhealthy

**Symptoms:**
- `/health/deep` returns 503
- `/health` returns 200

**Diagnosis:**
1. Check which specific check is failing:
   ```bash
   curl SERVICE_URL/health/deep | jq '.checks'
   ```
2. Look at service logs:
   ```bash
   gcloud logging read 'resource.labels.service_name="SERVICE"' --limit=20
   ```

**Common causes:**
- Import error (missing module in Dockerfile)
- Database credentials issue
- Network connectivity issue
- Firestore permissions

---

## Future Enhancements

### Layer 1: Dockerfile Validation (Planned)

Validate Dockerfiles before building:

```bash
# bin/validate-dockerfile-dependencies.sh
# Checks that all Python imports have corresponding COPY commands
```

**Status:** Designed (Session 129), not yet implemented

### Layer 5: Auto-Recovery (Planned)

Automatic backfill for failed operations:

```python
# Auto-detect and regrade ungraded predictions
@app.route('/auto-backfill')
def auto_backfill():
    # Find recent ungraded predictions
    # Trigger regrade automatically
```

**Status:** Designed (Session 129), not yet implemented

---

## Related Documentation

- **Session 129 Handoff:** `docs/09-handoff/2026-02-05-SESSION-129-HANDOFF.md`
- **Deployment Guide:** `docs/05-development/deployment.md`
- **System Features:** `docs/02-operations/system-features.md`
- **Troubleshooting:** `docs/02-operations/troubleshooting-matrix.md`

---

## Changelog

**2026-02-05 (Session 129):**
- Created initial documentation
- Implemented deep health checks for grading service
- Implemented smoke tests in deploy script
- Documented patterns and best practices
