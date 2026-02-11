# Orchestrator IAM Permission Check - Unit Tests

## Overview

Comprehensive unit tests for the IAM validation logic added in Session 205 that ensures all 4 orchestrators have the required `roles/run.invoker` permission for Pub/Sub to invoke them.

## Background

**Session 205 Root Cause**: All 4 orchestrators lacked `roles/run.invoker` permission, causing 7+ days of silent failures. Pub/Sub published messages but Cloud Run rejected invocations due to missing permissions. Orchestrators tracked completions in Firestore but never set `_triggered=True`, blocking the pipeline.

## Test Coverage

### Success Scenarios
- ✅ **test_all_orchestrators_have_correct_permissions**: All 4 orchestrators have correct IAM permissions
  - Verifies exit code 0
  - Verifies success messages for all orchestrators
  - Verifies no critical alerts

### Failure Scenarios
- ✅ **test_single_orchestrator_missing_permission**: One orchestrator missing IAM permission
  - Verifies exit code 1
  - Verifies P0 CRITICAL alert
  - Verifies affected orchestrator identified
  - Verifies actionable fix command provided

- ✅ **test_all_orchestrators_missing_permissions**: All orchestrators missing IAM permissions
  - Simulates the actual Session 205 bug
  - Verifies all 4 orchestrators identified
  - Verifies fix commands for all orchestrators

- ✅ **test_gcloud_command_fails**: gcloud command returns non-zero exit code
  - Simulates service not found, auth issues, or network problems
  - Verifies error reported for affected orchestrator
  - Verifies other orchestrators still checked

- ✅ **test_timeout_error**: gcloud command times out
  - Verifies timeout exception caught and reported
  - Verifies orchestrator marked as missing permission

- ✅ **test_wrong_service_account_has_permission**: roles/run.invoker exists but for wrong service account
  - Verifies both role AND service account must match
  - Verifies orchestrator marked as missing permission

- ✅ **test_mixed_permissions**: Mix of orchestrators with/without permissions
  - Real-world scenario where some orchestrators were fixed but others weren't
  - Verifies only affected orchestrators in missing list
  - Verifies fix commands only for affected orchestrators

- ✅ **test_json_parsing_error**: gcloud returns malformed JSON
  - Verifies error caught and reported
  - Verifies orchestrator marked as missing permission

### Command Structure Tests
- ✅ **test_gcloud_command_structure**: Verifies correct gcloud command parameters
  - Verifies all required flags present
  - Verifies correct project and region
  - Verifies JSON output format

### Error Message Quality Tests
- ✅ **test_error_message_includes_impact_and_fix**: Verifies error messages are helpful and actionable
  - Verifies clear severity (P0 CRITICAL)
  - Verifies impact description
  - Verifies symptoms
  - Verifies actionable fix command
  - Verifies correct service account in fix command

### Integration Tests
- ⏭️ **test_real_gcloud_command** (skipped by default)
  - Integration test with real gcloud commands
  - Requires authentication
  - Run with: `pytest -m integration`

## Running the Tests

```bash
# Run all unit tests
PYTHONPATH=. pytest tests/unit/validation/test_orchestrator_iam_check.py -v

# Run with coverage
PYTHONPATH=. pytest tests/unit/validation/test_orchestrator_iam_check.py -v --cov=.claude/skills/validate-daily --cov-report=term

# Run integration tests (requires gcloud auth)
PYTHONPATH=. pytest tests/unit/validation/test_orchestrator_iam_check.py -v -m integration
```

## Test Results

**All 10 unit tests pass** ✅
**1 integration test skipped** (requires gcloud auth)

Total execution time: ~4.36 seconds

## Key Implementation Details

### Test Approach
The tests use a `run_validation_logic()` helper method that:
1. Accepts a mocked `subprocess.run` function
2. Executes the actual validation logic
3. Captures stdout output
4. Returns (exit_code, output) tuple

This approach allows comprehensive testing without requiring real gcloud access or executing the script as a subprocess.

### Mock Data Helpers
- `mock_iam_policy_success()`: Generates valid IAM policy with correct permissions
- `mock_iam_policy_missing_permission()`: Generates IAM policy without run.invoker
- `mock_iam_policy_wrong_service_account()`: Generates IAM policy with wrong service account
- `mock_iam_policy_empty()`: Generates empty IAM policy
- `create_subprocess_result()`: Creates mock subprocess.CompletedProcess objects

## Validation Script Location

The actual validation logic is in:
- **Skill**: `.claude/skills/validate-daily/SKILL.md` - Check 5: Orchestrator IAM Permissions
- **Production**: Runs as part of `/validate-daily` skill

## Orchestrators Validated

1. **phase2-to-phase3-orchestrator** (monitoring-only)
2. **phase3-to-phase4-orchestrator** (functional)
3. **phase4-to-phase5-orchestrator** (functional)
4. **phase5-to-phase6-orchestrator** (functional)

## Required IAM Permission

**Role**: `roles/run.invoker`
**Service Account**: `756957797294-compute@developer.gserviceaccount.com`
**Project**: `nba-props-platform`
**Region**: `us-west2`

## Prevention Mechanism

Session 205 added:
1. Daily validation via `/validate-daily` skill
2. Auto-set IAM permissions in deployment scripts
3. Unit tests to catch regressions (this file)

## Reference

- **Session 205 Handoff**: `docs/09-handoff/2026-02-12-SESSION-205-HANDOFF.md`
- **Session 205 IAM Investigation**: Root cause analysis of the 7-day silent failure
- **Session 206 Start Prompt**: Unit test creation task (this work)
