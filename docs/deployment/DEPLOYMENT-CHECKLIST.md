# Deployment Checklist

## Purpose
Prevent deployment failures like the Jan 16-20 ModuleNotFoundError incident.

## Pre-Deployment Requirements

### 1. Run Pre-Deployment Check Script

**REQUIRED before every deployment**

```bash
# Standard check
./bin/pre_deploy_check.sh

# Strict mode (fail on warnings)
./bin/pre_deploy_check.sh --strict
```

This script validates:
- ✅ Python syntax errors
- ✅ Critical imports (data_processors, shared modules, etc.)
- ✅ requirements.txt consistency
- ✅ Orchestration config loads correctly
- ✅ Processor name consistency (br_rosters_current, not br_roster)
- ✅ Cloud Function entry points exist

**DO NOT deploy if this script fails!**

### 2. Run Import Validation Tests

```bash
# Test all critical imports
pytest tests/test_critical_imports.py -v

# Test specific modules
pytest tests/test_critical_imports.py::TestDataProcessorImports -v
pytest tests/test_critical_imports.py::TestSharedModuleImports -v
```

### 3. Verify Container Builds Successfully

For Cloud Run services:

```bash
# Test build locally (replace with your service)
cd services/nba-phase3-analytics
docker build -t test-build .

# Verify imports in container
docker run --rm test-build python -c "from data_processors.analytics import PlayerGameSummaryProcessor"
```

### 4. Check Requirements.txt is Up-to-Date

```bash
# Generate current requirements
pip freeze > requirements_current.txt

# Compare with committed requirements
diff requirements.txt requirements_current.txt

# If different, update requirements.txt
cp requirements_current.txt requirements.txt
```

## Deployment Steps by Service Type

### Cloud Functions (Orchestrators)

```bash
# 1. Run pre-deployment checks
./bin/pre_deploy_check.sh

# 2. Deploy with specific entry point
gcloud functions deploy phase3-to-phase4-orchestrator \
  --region=us-west2 \
  --entry-point=orchestrate_phase3_to_phase4 \
  --runtime=python312 \
  --trigger-topic=nba-phase3-analytics-complete \
  --project=nba-props-platform

# 3. Verify deployment
gcloud functions describe phase3-to-phase4-orchestrator \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(status,versionId)"

# 4. Test with a sample event (optional)
gcloud functions call phase3-to-phase4-orchestrator \
  --region=us-west2 \
  --data='{"game_date":"2026-01-21","processor_name":"test"}' \
  --project=nba-props-platform
```

### Cloud Run Services (Processors)

```bash
# 1. Run pre-deployment checks
./bin/pre_deploy_check.sh

# 2. Build and push container
gcloud builds submit \
  --tag gcr.io/nba-props-platform/nba-phase3-analytics:latest \
  --project=nba-props-platform

# 3. Deploy to Cloud Run
gcloud run deploy nba-phase3-analytics \
  --image gcr.io/nba-props-platform/nba-phase3-analytics:latest \
  --region=us-west2 \
  --project=nba-props-platform

# 4. Verify deployment
gcloud run services describe nba-phase3-analytics \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(status.url,status.latestReadyRevisionName)"

# 5. Test health endpoint
curl https://nba-phase3-analytics-xyz.run.app/health
curl https://nba-phase3-analytics-xyz.run.app/ready
```

## Post-Deployment Verification

### 1. Check Service Health

```bash
# Cloud Function
gcloud functions describe <function-name> \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(status)"

# Cloud Run
curl https://<service-url>/health
curl https://<service-url>/ready
```

### 2. Monitor Logs for Errors

```bash
# Cloud Function logs (first 5 minutes)
gcloud logging read "resource.type=cloud_function
  AND resource.labels.function_name=<function-name>
  AND severity>=ERROR
  AND timestamp>='$(date -u -d '5 minutes ago' --iso-8601=seconds)'" \
  --limit=50 \
  --project=nba-props-platform

# Cloud Run logs
gcloud logging read "resource.type=cloud_run_revision
  AND resource.labels.service_name=<service-name>
  AND severity>=ERROR
  AND timestamp>='$(date -u -d '5 minutes ago' --iso-8601=seconds)'" \
  --limit=50 \
  --project=nba-props-platform
```

### 3. Check for Import Errors

```bash
# Look for ModuleNotFoundError
gcloud logging read "resource.labels.service_name=<service-name>
  AND textPayload=~'ModuleNotFoundError'
  AND timestamp>='$(date -u -d '10 minutes ago' --iso-8601=seconds)'" \
  --limit=10 \
  --project=nba-props-platform
```

### 4. Verify Service Can Process Requests

```bash
# Trigger a test job
curl -X POST https://<service-url>/process \
  -H "Content-Type: application/json" \
  -d '{"game_date":"2026-01-21","test_mode":true}'

# Check for successful processing
gcloud logging read "resource.labels.service_name=<service-name>
  AND textPayload=~'success'
  AND timestamp>='$(date -u -d '2 minutes ago' --iso-8601=seconds)'" \
  --limit=5 \
  --project=nba-props-platform
```

## Rollback Procedure

If deployment fails or causes issues:

### Cloud Functions

```bash
# List recent versions
gcloud functions describe <function-name> \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(versionId,updateTime)"

# Rollback to previous version (manual redeploy of last known good)
# Cloud Functions don't support direct rollback, must redeploy
git checkout <previous-commit>
./bin/pre_deploy_check.sh
gcloud functions deploy <function-name> --region=us-west2 ...
```

### Cloud Run

```bash
# List recent revisions
gcloud run revisions list \
  --service=<service-name> \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="table(metadata.name,status.conditions[0].status,metadata.creationTimestamp)"

# Rollback to previous revision
gcloud run services update-traffic <service-name> \
  --to-revisions=<previous-revision>=100 \
  --region=us-west2 \
  --project=nba-props-platform

# Verify rollback
gcloud run services describe <service-name> \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(status.traffic)"
```

## Common Deployment Issues and Fixes

### Issue: ModuleNotFoundError

**Symptoms:**
- Service crashes on startup
- Logs show "ModuleNotFoundError: No module named 'X'"

**Root Causes:**
1. Missing package in requirements.txt
2. Import path changed
3. Module not copied to container

**Fixes:**
```bash
# 1. Verify package is in requirements.txt
grep "package-name" requirements.txt

# 2. Test import locally
python -c "import package_name"

# 3. Rebuild container and verify
docker build -t test .
docker run --rm test python -c "import package_name"

# 4. Update requirements.txt if needed
pip freeze | grep package-name >> requirements.txt
```

### Issue: Entry Point Not Found

**Symptoms:**
- Cloud Function fails to deploy
- Error: "Entry point X not found"

**Root Causes:**
1. Function renamed
2. Wrong entry point specified
3. main.py syntax error

**Fixes:**
```bash
# 1. Verify function exists in main.py
grep "def <entry-point>" main.py

# 2. Check for syntax errors
python -m py_compile main.py

# 3. Deploy with correct entry point
gcloud functions deploy <name> \
  --entry-point=<correct-function-name> \
  --region=us-west2
```

### Issue: Container Build Fails

**Symptoms:**
- gcloud builds submit fails
- Docker build fails

**Root Causes:**
1. Dockerfile syntax error
2. Missing files in .dockerignore
3. Build context too large

**Fixes:**
```bash
# 1. Test Docker build locally
docker build -t test .

# 2. Check Dockerfile syntax
docker build --no-cache -t test .

# 3. Reduce build context (add to .dockerignore)
echo ".git/" >> .dockerignore
echo ".venv/" >> .dockerignore
echo "__pycache__/" >> .dockerignore
```

## Integration with CI/CD

### GitHub Actions (Example)

```yaml
name: Pre-Deployment Validation

on:
  push:
    branches: [main, staging]
  pull_request:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest

      - name: Run pre-deployment checks
        run: ./bin/pre_deploy_check.sh --strict

      - name: Run import tests
        run: pytest tests/test_critical_imports.py -v

      - name: Block deployment on failure
        if: failure()
        run: |
          echo "❌ Pre-deployment checks failed!"
          echo "DO NOT merge until all checks pass"
          exit 1
```

## Success Criteria

✅ Pre-deployment script passes all checks
✅ Import validation tests pass
✅ Container builds successfully
✅ Service health checks pass post-deployment
✅ No import errors in logs (first 10 minutes)
✅ Test request processes successfully
✅ Rollback plan tested and documented

## Related Documentation

- [Pre-Deployment Check Script](../../bin/pre_deploy_check.sh)
- [Import Validation Tests](../../tests/test_critical_imports.py)
- [Phase 2 Completion Deadline Deployment](./PHASE2-COMPLETION-DEADLINE-DEPLOYMENT.md)
- [Incident Report: Jan 16-20 ModuleNotFoundError](../../docs/08-projects/current/week-1-improvements/SYSTEM-VALIDATION-JAN-21-2026.md)

## Version History

- **v1.0** (2026-01-21): Initial deployment checklist with import validation
