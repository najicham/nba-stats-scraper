# Orchestrator Deployment Integration Tests

## Overview

Integration tests for orchestrator deployment IAM permissions (Session 206).

These tests verify that deployment scripts correctly set IAM permissions to allow Pub/Sub to invoke Cloud Functions (Cloud Run Gen2).

## Context (Session 205)

**Problem:** All 4 orchestrators lacked `roles/run.invoker` permission, preventing Pub/Sub from invoking them. This caused 7+ days of silent failures where orchestrators tracked completion in Firestore but never set `_triggered=True`.

**Root Cause:** `gcloud functions deploy` does not preserve IAM policies on redeployment.

**Fix:** All orchestrator deployment scripts now include IAM binding step after deployment.

**Prevention:** These integration tests ensure deployment scripts maintain IAM configuration.

## Test File

**Location:** `tests/integration/test_orchestrator_deployment.py`

**Coverage:** 19 tests across 6 test classes

## Test Classes

### 1. TestOrchestratorIAMDeployment (5 tests)
Tests that deployment scripts set IAM permissions correctly:
- Deployment calls `gcloud run services add-iam-policy-binding`
- Uses correct service account (756957797294-compute@developer.gserviceaccount.com)
- Grants `roles/run.invoker` role
- All 3 functional orchestrators covered (phase3→4, phase4→5, phase5→6)
- Targets correct region (us-west2)

### 2. TestIAMBindingFailureHandling (3 tests)
Tests deployment handles IAM binding failures gracefully:
- IAM binding failure raises error
- Timeout handling
- Non-existent orchestrator fails appropriately

### 3. TestIAMPersistence (2 tests)
Tests IAM permissions persist after deployment:
- Permissions readable after deployment
- Redeployment preserves IAM (Session 205 fix)

### 4. TestDeploymentScriptValidation (3 tests)
Tests deployment scripts include IAM binding step:
- Scripts contain `add-iam-policy-binding` command
- IAM binding happens AFTER `gcloud functions deploy`
- Scripts have error handling (`set -e`)

### 5. TestIAMValidationCommands (3 tests)
Tests IAM validation commands work correctly:
- Check IAM permissions command
- Missing IAM permissions detection
- Validate all orchestrators at once

### 6. TestSession205Regression (3 tests)
Regression tests for Session 205 IAM issue:
- Session 205 scenario (missing IAM) now prevented
- Pub/Sub can invoke after deployment
- Silent failure prevented by IAM validation

## Running Tests

### Run All Tests
```bash
pytest tests/integration/test_orchestrator_deployment.py -v
```

### Run Specific Test Class
```bash
pytest tests/integration/test_orchestrator_deployment.py::TestOrchestratorIAMDeployment -v
pytest tests/integration/test_orchestrator_deployment.py::TestSession205Regression -v
```

### Run Specific Test
```bash
pytest tests/integration/test_orchestrator_deployment.py::TestOrchestratorIAMDeployment::test_deployment_sets_iam_permissions -v
```

### Run with Coverage
```bash
pytest tests/integration/test_orchestrator_deployment.py --cov=bin/orchestrators --cov-report=term
```

### List All Tests
```bash
pytest tests/integration/test_orchestrator_deployment.py --collect-only -q
```

## Expected Results

All 19 tests should pass:
```
============================= test session starts ==============================
...
collected 19 items

tests/integration/test_orchestrator_deployment.py::TestOrchestratorIAMDeployment::test_deployment_sets_iam_permissions PASSED [  5%]
tests/integration/test_orchestrator_deployment.py::TestOrchestratorIAMDeployment::test_iam_binding_uses_correct_service_account PASSED [ 10%]
...
============================= 19 passed in 21.29s ==============================
```

## Key Test Cases

### 1. IAM Permissions Set During Deployment
Tests that deployment scripts call IAM binding command:
```python
def test_deployment_sets_iam_permissions(self, mock_subprocess, orchestrator_configs, expected_service_account):
    """Test deployment script calls gcloud run services add-iam-policy-binding"""
```

### 2. Correct Service Account
Tests that correct compute service account is used:
```python
def test_iam_binding_uses_correct_service_account(self, mock_subprocess, expected_service_account):
    """Test IAM binding uses correct compute service account"""
```

### 3. All Orchestrators Covered
Tests that all functional orchestrators have IAM configuration:
```python
def test_all_orchestrators_covered(self, orchestrator_configs):
    """Test all 4 functional orchestrators have IAM configuration"""
```

### 4. Session 205 Scenario Prevented
Regression test for Session 205 IAM issue:
```python
def test_session_205_scenario_prevented(self, mock_subprocess):
    """Test Session 205 scenario (missing IAM) is now prevented"""
```

## Test Fixtures

### mock_subprocess
Mocks `subprocess.run` for gcloud commands. Default behavior: all commands succeed.

### orchestrator_configs
Configuration for all 3 functional orchestrators:
- phase3-to-phase4-orchestrator
- phase4-to-phase5-orchestrator
- phase5-to-phase6-orchestrator

Note: phase2-to-phase3-orchestrator excluded (monitoring-only per Session 204)

### expected_service_account
Expected service account for IAM binding: `756957797294-compute@developer.gserviceaccount.com`

## Orchestrators Covered

| Orchestrator | Status | IAM Required |
|--------------|--------|--------------|
| phase3-to-phase4-orchestrator | FUNCTIONAL | ✅ Yes |
| phase4-to-phase5-orchestrator | FUNCTIONAL | ✅ Yes |
| phase5-to-phase6-orchestrator | FUNCTIONAL | ✅ Yes |
| phase2-to-phase3-orchestrator | MONITORING-ONLY (Session 204) | ⚠️ Optional |

## IAM Command Template

```bash
gcloud run services add-iam-policy-binding <orchestrator-name> \
  --region=us-west2 \
  --member='serviceAccount:756957797294-compute@developer.gserviceaccount.com' \
  --role='roles/run.invoker' \
  --project=nba-props-platform
```

## Deployment Scripts Tested

- `bin/orchestrators/deploy_phase3_to_phase4.sh`
- `bin/orchestrators/deploy_phase4_to_phase5.sh`
- `bin/orchestrators/deploy_phase5_to_phase6.sh`

## References

- **Session 205 Handoff:** `docs/09-handoff/2026-02-12-SESSION-205-HANDOFF.md`
- **Session 205 Start Prompt:** `docs/09-handoff/2026-02-12-SESSION-205-START-PROMPT.md`
- **Deployment Scripts:** `bin/orchestrators/deploy_phase*.sh`
- **CLAUDE.md:** Troubleshooting entry for "Orchestrator not triggering"

## CI/CD Integration

These tests should be run:
- Before any deployment script changes
- As part of pre-commit hooks
- In CI/CD pipeline before deployment
- After Cloud Build deployments (validation)

## Troubleshooting

### Test Failures

If tests fail, check:
1. Deployment scripts still contain IAM binding step
2. IAM binding is AFTER `gcloud functions deploy`
3. Correct service account is used
4. Correct role (`roles/run.invoker`) is granted
5. Scripts have `set -e` error handling

### Real Deployment Failures

If real deployments fail IAM validation:
1. Check orchestrator logs (should have no execution logs if IAM missing)
2. Manually set IAM permissions using template above
3. Verify IAM with `gcloud run services get-iam-policy <orchestrator> --region us-west2`
4. Update deployment scripts if IAM step is missing

## Maintenance

When adding new orchestrators:
1. Add orchestrator config to `orchestrator_configs` fixture
2. Ensure deployment script includes IAM binding step
3. Run tests to verify coverage
4. Update this README with new orchestrator

## Success Criteria

✅ All 19 tests pass
✅ Deployment scripts include IAM binding step
✅ IAM binding happens AFTER deployment
✅ Correct service account and role used
✅ All functional orchestrators covered
✅ Session 205 regression prevented

---

**Created:** 2026-02-12 (Session 206 - IAM Permission Testing)
**Last Updated:** 2026-02-12
**Status:** Active - All tests passing
