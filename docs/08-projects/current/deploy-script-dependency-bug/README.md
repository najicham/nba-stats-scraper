# Deploy Script Dependency Test Bug

**Discovered**: Session 86 (2026-02-02)
**Severity**: P5 (Cosmetic - blocks deployments but doesn't affect running services)
**Status**: Documented, needs fix

---

## Problem

The `bin/deploy-service.sh` dependency test uses incorrect module names for Phase 3 and Phase 4 processors, causing deployments to fail even though the services work fine in production.

## Error Details

### Phase 3 Analytics Processors

**Dependency test expects**: `analytics_main`
**Actual module name**: `main_analytics_service`

```
❌ CRITICAL: analytics_main import failed: No module named 'analytics_main'
```

### Phase 4 Precompute Processors

**Dependency test expects**: `precompute_main`
**Actual module name**: `main_precompute_service`

```
❌ CRITICAL: precompute_main import failed: No module named 'precompute_main'
```

## Root Cause

The dependency test in `bin/deploy-service.sh` derives module names incorrectly. It appears to use a pattern like `{service}_main` instead of reading the actual module name from the Dockerfile's CMD.

### Actual Dockerfile Commands

**Phase 3** (`data_processors/analytics/Dockerfile`):
```dockerfile
CMD exec gunicorn \
  --bind :${PORT:-8080} \
  --workers 1 \
  --threads 4 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  main_analytics_service:app
```

**Phase 4** (`data_processors/precompute/Dockerfile`):
```dockerfile
CMD exec gunicorn \
  --bind :${PORT:-8080} \
  --workers 1 \
  --threads 4 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  main_precompute_service:app
```

## Impact

**Current Impact**: Cannot deploy Phase 3/4 processors via deploy script

**Production Impact**: None - services are running fine with correct code

**Workaround**: Manual deployment via gcloud (bypassing dependency test)

## Fix Required

Update `bin/deploy-service.sh` to use correct module names for dependency testing.

### Option 1: Hardcode Correct Names

```bash
case "$SERVICE_NAME" in
  nba-phase3-analytics-processors)
    MAIN_MODULE="main_analytics_service"
    ;;
  nba-phase4-precompute-processors)
    MAIN_MODULE="main_precompute_service"
    ;;
  # ... other services
esac
```

### Option 2: Parse from Dockerfile

Extract the actual module name from the Dockerfile's CMD:

```bash
MAIN_MODULE=$(grep "CMD exec gunicorn" "$DOCKERFILE" | \
  sed -E 's/.*gunicorn.*\s+([^:]+):app.*/\1/')
```

### Option 3: Skip Main Module Test for These Services

If the main module test isn't critical for these services (since critical dependencies are tested separately), could skip it:

```bash
if [[ "$SERVICE_NAME" =~ phase3-analytics|phase4-precompute ]]; then
  echo "Skipping main module test (tested via gunicorn startup)"
else
  test_main_module "$MAIN_MODULE"
fi
```

## Testing

After fixing, verify:

```bash
# Should succeed
./bin/deploy-service.sh nba-phase3-analytics-processors

# Should succeed
./bin/deploy-service.sh nba-phase4-precompute-processors
```

## Related

- **Session 86**: Attempted deployment to clear docs-only drift, blocked by this bug
- **Session 80**: Dependency test was added to prevent missing dependencies (38hr outage)
- The dependency test is valuable! Just needs correct module names.

---

**Priority**: Fix in next session when making code changes to Phase 3/4 processors
