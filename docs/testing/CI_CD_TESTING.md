# CI/CD Testing Guide

Comprehensive guide to testing workflows in GitHub Actions and deployment pipelines.

## Table of Contents

1. [Overview](#overview)
2. [GitHub Actions Workflows](#github-actions-workflows)
3. [Deployment Gates](#deployment-gates)
4. [Pre-Deployment Validation](#pre-deployment-validation)
5. [Adding Tests to CI/CD](#adding-tests-to-cicd)
6. [Troubleshooting CI/CD Issues](#troubleshooting-cicd-issues)

---

## Overview

### CI/CD Testing Strategy

The project uses GitHub Actions for automated testing at multiple stages:

```
Code Push → PR Tests → Deployment Validation → Deploy → Post-Deploy Checks
```

### Testing Stages

| Stage | When | What Runs | Pass Required |
|-------|------|-----------|---------------|
| **PR Tests** | On pull request | Unit tests, linting | Yes |
| **Deployment Validation** | Before deploy | Orchestrator tests, pre-deploy checks | Yes |
| **Post-Deploy** | After deploy | Smoke tests, validation tests | Monitored |

### Workflow Files

```
.github/workflows/
├── test.yml                      # Unit tests and linting
├── deployment-validation.yml     # Pre-deployment gates
├── validate-docs-structure.yml   # Documentation validation
├── check-shared-sync.yml         # Shared directory sync
└── archive-handoffs.yml          # Documentation archival
```

---

## GitHub Actions Workflows

### 1. Unit Tests and Linting (`test.yml`)

**Triggers:**
- Pull requests to `main`
- Pushes to `main`
- Changes to `**.py` or `requirements*.txt`

**Jobs:**

#### Job: Run Unit Tests

```yaml
name: Run Unit Tests
runs-on: ubuntu-latest

steps:
  - Checkout code
  - Set up Python 3.12
  - Install dependencies
  - Run unit tests with coverage
  - Upload coverage to Codecov
  - Run shared module tests
```

**Commands:**
```bash
# Unit tests
python -m pytest tests/unit/ -v --tb=short -q \
  --ignore=tests/unit/scrapers/ \
  --ignore=tests/unit/services/ \
  --timeout=60 \
  --cov=. --cov-report=xml --cov-report=term

# Shared module tests
python -m pytest tests/unit/shared/ -v --tb=short -q -x --timeout=60
```

**Pass Criteria:**
- All unit tests pass
- No timeouts (60 second limit per test)
- Coverage report generated

#### Job: Lint Check

```yaml
name: Lint Check
runs-on: ubuntu-latest

steps:
  - Checkout code
  - Set up Python 3.12
  - Install ruff
  - Run ruff check
```

**Commands:**
```bash
ruff check --select=E9,F63,F7,F82 --output-format=github .
```

**Pass Criteria:**
- No critical errors (E9, F63, F7, F82)
- SyntaxError, undefined names, type errors

**What's Checked:**
- `E9`: SyntaxError
- `F63`: Invalid syntax
- `F7`: Syntax error in type annotation
- `F82`: Undefined name

### 2. Deployment Validation (`deployment-validation.yml`)

**Triggers:**
- Pull requests to `main` affecting orchestration/shared code
- Pushes to `main`

**Jobs:**

#### Job: Pre-Deployment Check

```yaml
name: Pre-Deployment Validation
runs-on: ubuntu-latest

steps:
  - Checkout code
  - Set up Python 3.12
  - Install dependencies
  - Authenticate to Google Cloud (optional)
  - Run pre-deployment validation
```

**Commands:**
```bash
python bin/validation/pre_deployment_check.py
```

**What's Validated:**
- Processor registry syntax
- Import validation for all processors
- Cloud Function requirements.txt files
- Orchestrator configuration
- Environment variable consistency

**Pass Criteria:**
- No syntax errors
- All imports successful
- All requirements files valid
- Configuration consistent

**Exit Codes:**
- `0`: All checks passed
- `1`: Critical errors (fails build)
- `2`: Warnings only (passes build)

#### Job: Orchestrator Tests

```yaml
name: Cloud Function Orchestrator Tests
runs-on: ubuntu-latest

steps:
  - Checkout code
  - Set up Python 3.12
  - Install test dependencies
  - Run orchestrator integration tests
  - Upload coverage
```

**Commands:**
```bash
python -m pytest tests/integration/test_orchestrator_transitions.py -v \
  --tb=short \
  --timeout=120 \
  --cov=orchestration \
  --cov-report=xml \
  --cov-report=term
```

**Pass Criteria:**
- All 24 orchestrator tests pass
- Phase transitions validated
- No timeouts (120 second limit)

**What's Tested:**
- Phase 2 → Phase 3 transitions
- Phase 3 → Phase 4 transitions
- Phase 4 → Phase 5 transitions
- Phase 5 → Phase 6 transitions
- Auto-backfill orchestration
- Self-healing triggers
- Error handling
- Retry logic

#### Job: Integration Tests

```yaml
name: Integration Tests
runs-on: ubuntu-latest

steps:
  - Checkout code
  - Set up Python 3.12
  - Install test dependencies
  - Run integration tests
```

**Commands:**
```bash
python -m pytest tests/integration/ -v \
  --tb=short \
  --timeout=120 \
  -x
```

**Pass Criteria:**
- Integration tests pass (or continue-on-error)
- No critical failures

#### Job: Deployment Gate

```yaml
name: Deployment Gate
runs-on: ubuntu-latest
needs: [pre-deployment-check, orchestrator-tests]

steps:
  - Check all validations passed
  - Report status
```

**Pass Criteria:**
- Pre-deployment check passed
- All 24 orchestrator tests passed
- Safe to merge and deploy

---

## Deployment Gates

### Gate Levels

```
┌─────────────────────────────────────┐
│  Level 1: PR Gates (Required)      │
│  - Unit tests pass                  │
│  - Linting passes                   │
│  - Code review approved             │
└─────────────────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│  Level 2: Deployment Gates          │
│  (Required)                         │
│  - Pre-deployment validation        │
│  - Orchestrator tests (24/24)       │
│  - Integration tests                │
└─────────────────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│  Level 3: Post-Deploy Validation    │
│  (Monitored)                        │
│  - Smoke tests                      │
│  - Data validation                  │
│  - Health checks                    │
└─────────────────────────────────────┘
```

### Required vs. Optional Gates

**Required (Blocking):**
- Unit tests
- Orchestrator tests (24/24)
- Pre-deployment validation
- Linting (critical errors only)

**Optional (Non-Blocking):**
- Integration tests (some may fail in CI)
- Coverage upload
- Shared module tests
- Documentation validation

### Gate Bypass (Emergency Only)

In emergencies, gates can be bypassed:

```yaml
# Add to workflow step:
continue-on-error: true
```

**When to Bypass:**
- Critical production issue
- Hotfix deployment
- Infrastructure emergency

**Process:**
1. Document reason for bypass
2. Create follow-up ticket
3. Fix tests ASAP
4. Re-enable gate

---

## Pre-Deployment Validation

### What Gets Validated

#### 1. Processor Registry

**File:** `docs/processor-registry.yaml`

**Checks:**
- YAML syntax valid
- All required fields present
- Processor classes exist and importable
- Dependencies correctly specified

**Example:**
```yaml
phase3_processors:
  - name: player_game_summary
    class: PlayerGameSummaryProcessor
    module: data_processors.analytics.player_game_summary.player_game_summary_processor
    dependencies:
      - nbac_boxscore_traditional
      - nbac_boxscore_advanced
```

#### 2. Import Validation

**Checks:**
- All processors can be imported
- No circular dependencies
- All required modules available
- No syntax errors

**Test Command:**
```python
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
# If this fails, deployment blocked
```

#### 3. Requirements Files

**Checks:**
- All Cloud Function requirements.txt files exist
- Shared dependencies consistent
- No conflicting versions
- Required packages present

**Checked Files:**
```
orchestration/cloud_functions/*/requirements.txt
data_processors/*/requirements.txt
shared/requirements.txt
```

#### 4. Configuration Consistency

**Checks:**
- Environment variables documented
- Configuration files valid
- Secrets not committed
- No hardcoded credentials

### Running Pre-Deployment Check Locally

```bash
# Run full validation
python bin/validation/pre_deployment_check.py

# Exit codes:
# 0 = All passed
# 1 = Critical errors (deployment blocked)
# 2 = Warnings only (deployment allowed)
```

**Sample Output:**
```
Pre-Deployment Validation
========================

✓ Processor Registry: Valid YAML syntax
✓ Import Validation: All processors importable
✓ Requirements Files: All present and valid
✓ Configuration: Consistent and valid

RESULT: ✅ All checks passed - Safe to deploy
```

**With Errors:**
```
Pre-Deployment Validation
========================

✓ Processor Registry: Valid YAML syntax
✗ Import Validation: Failed to import PlayerGameSummaryProcessor
  Error: ModuleNotFoundError: No module named 'pandas'
✓ Requirements Files: All present and valid
⚠ Configuration: Missing environment variable: BQ_DATASET

RESULT: ❌ Critical errors found - Deployment blocked

Errors:
  - Fix PlayerGameSummaryProcessor import
  - Add pandas to requirements.txt
```

---

## Adding Tests to CI/CD

### Adding a New Test to Unit Test Suite

**Step 1:** Write the test in appropriate directory

```python
# tests/unit/my_module/test_my_feature.py
import pytest

def test_my_feature():
    """Test my new feature"""
    result = my_function()
    assert result is True
```

**Step 2:** Verify test runs locally

```bash
pytest tests/unit/my_module/test_my_feature.py -v
```

**Step 3:** Push to PR - test runs automatically

The test will run in GitHub Actions via `test.yml` workflow.

### Adding a New Integration Test

**Step 1:** Create test in `tests/integration/`

```python
# tests/integration/test_my_workflow.py
import pytest

@pytest.mark.integration
def test_my_workflow():
    """Test complete workflow"""
    # ... test code ...
    pass
```

**Step 2:** Update `deployment-validation.yml` if needed

```yaml
# Only if you want it in pre-deployment gate
- name: Run my workflow tests
  run: |
    python -m pytest tests/integration/test_my_workflow.py -v
```

**Step 3:** Test locally first

```bash
pytest tests/integration/test_my_workflow.py -v --timeout=120
```

### Adding a New Orchestrator Test

**Step 1:** Add to `tests/integration/test_orchestrator_transitions.py`

```python
class TestPhase4ToPhase5:
    """Test Phase 4 to Phase 5 transition"""

    def test_my_new_transition_scenario(self):
        """Test new transition scenario"""
        # ... test code ...
        pass
```

**Step 2:** Verify orchestrator test count

```bash
pytest tests/integration/test_orchestrator_transitions.py -v --collect-only | grep "test session starts" -A 100
```

**Step 3:** Update deployment gate if count changed

```yaml
# .github/workflows/deployment-validation.yml
- name: Test result summary
  run: |
    echo "::notice::All 25 orchestrator tests passed ✅"  # Updated from 24
```

### Adding Custom Workflow

**Step 1:** Create workflow file

```yaml
# .github/workflows/my-custom-tests.yml
name: My Custom Tests

on:
  pull_request:
    branches: [main]
    paths:
      - 'my_module/**'

jobs:
  custom-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: pip install pytest
      - name: Run custom tests
        run: pytest tests/my_custom/ -v
```

**Step 2:** Test workflow locally (optional)

```bash
# Using act (GitHub Actions local runner)
act pull_request -W .github/workflows/my-custom-tests.yml
```

**Step 3:** Push and verify in GitHub Actions UI

---

## Troubleshooting CI/CD Issues

### Common Issues

#### 1. Tests Pass Locally But Fail in CI

**Problem:**
```
Tests pass on local machine
Tests fail in GitHub Actions
```

**Causes:**
- Missing dependencies in CI
- Different Python version
- Environment variables not set
- Timezone differences
- File path differences (absolute vs relative)

**Solutions:**

```yaml
# Ensure consistent Python version
- uses: actions/setup-python@v5
  with:
    python-version: '3.12'  # Match local version

# Set environment variables
env:
  PYTHONPATH: ${{ github.workspace }}
  TZ: 'America/New_York'

# Install all dependencies
- name: Install dependencies
  run: |
    pip install -r requirements.txt
    pip install -r requirements-test.txt
```

#### 2. Timeout Errors

**Problem:**
```
ERROR: Timeout after 60 seconds
```

**Solutions:**

```yaml
# Increase timeout in workflow
- name: Run tests with longer timeout
  run: pytest tests/ --timeout=120

# Or in pytest.ini
[pytest]
timeout = 120
```

#### 3. Import Errors in CI

**Problem:**
```
ModuleNotFoundError: No module named 'my_module'
```

**Solutions:**

```yaml
# Set PYTHONPATH correctly
env:
  PYTHONPATH: ${{ github.workspace }}

# Or use python -m pytest
- name: Run tests
  run: python -m pytest tests/unit/ -v

# Or install package in editable mode
- name: Install package
  run: pip install -e .
```

#### 4. Coverage Upload Fails

**Problem:**
```
Error uploading coverage to Codecov
```

**Solutions:**

```yaml
# Add continue-on-error
- name: Upload coverage
  uses: codecov/codecov-action@v4
  with:
    file: ./coverage.xml
  continue-on-error: true  # Don't fail build if upload fails
```

#### 5. GCP Authentication Fails

**Problem:**
```
403 Permission denied: BigQuery
```

**Solutions:**

```yaml
# Make GCP auth optional
- name: Authenticate to Google Cloud
  uses: google-github-actions/auth@v2
  with:
    credentials_json: ${{ secrets.GCP_SA_KEY }}
  continue-on-error: true

# Skip tests requiring GCP
- name: Run tests
  run: |
    pytest tests/unit/ -v --ignore=tests/validation/
```

#### 6. Flaky Tests

**Problem:**
```
Tests pass sometimes, fail other times
```

**Solutions:**

```python
# Add retries for flaky tests
@pytest.mark.flaky(reruns=3, reruns_delay=2)
def test_sometimes_fails():
    # ... test code ...
    pass

# Or use better mocking
def test_with_deterministic_mock():
    with patch('random.random', return_value=0.5):
        # Now test is deterministic
        result = my_function()
        assert result is not None
```

#### 7. Workflow Not Triggering

**Problem:**
```
Push to PR but workflow doesn't run
```

**Checks:**

```yaml
# Verify trigger paths match changed files
on:
  pull_request:
    paths:
      - '**.py'              # Triggers on any .py file
      - 'requirements*.txt'  # Triggers on requirements files

# Check branch name matches
on:
  pull_request:
    branches: [main]  # Only triggers for PRs to main
```

### Debug GitHub Actions

#### Enable Debug Logging

**Step 1:** Enable in workflow

```yaml
- name: Run tests with debug
  run: pytest tests/unit/ -vv -s
  env:
    ACTIONS_STEP_DEBUG: true
```

**Step 2:** Or enable in repository settings

- Go to Settings → Secrets → Actions
- Add secret: `ACTIONS_STEP_DEBUG = true`

#### Check Workflow Logs

1. Go to Actions tab in GitHub
2. Click on failed workflow run
3. Click on failed job
4. Expand failed step
5. Review logs

#### Download Artifacts

```yaml
# Add artifact upload to workflow
- name: Upload test results
  if: failure()
  uses: actions/upload-artifact@v3
  with:
    name: test-results
    path: |
      test-results/
      htmlcov/
```

Then download from Actions UI.

---

## Best Practices

### 1. Keep CI Fast

```yaml
# Use caching
- uses: actions/setup-python@v5
  with:
    python-version: '3.12'
    cache: 'pip'  # Cache pip dependencies

# Run tests in parallel
- name: Run tests
  run: pytest tests/unit/ -n auto
```

### 2. Fail Fast

```yaml
# Stop at first failure
- name: Run tests
  run: pytest tests/unit/ -x

# Use dependencies between jobs
jobs:
  lint:
    runs-on: ubuntu-latest
    steps: [...]

  test:
    needs: lint  # Don't run tests if lint fails
    runs-on: ubuntu-latest
    steps: [...]
```

### 3. Clear Error Messages

```yaml
- name: Test result summary
  if: always()
  run: |
    if [ $? -eq 0 ]; then
      echo "::notice::✅ All tests passed"
    else
      echo "::error::❌ Tests failed - check logs above"
      exit 1
    fi
```

### 4. Matrix Testing (Optional)

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.11', '3.12']
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pytest tests/unit/ -v
```

---

## Summary

### CI/CD Testing Checklist

- [ ] Unit tests run on every PR
- [ ] Orchestrator tests run before deployment
- [ ] Pre-deployment validation passes
- [ ] Linting checks critical errors
- [ ] Coverage reports uploaded
- [ ] Deployment gate requires all checks
- [ ] Tests run in < 5 minutes
- [ ] Flaky tests identified and fixed
- [ ] Error messages are clear

### Workflow Overview

| Workflow | Trigger | Duration | Required |
|----------|---------|----------|----------|
| test.yml | PR, Push | ~2 min | Yes |
| deployment-validation.yml | Pre-deploy | ~3 min | Yes |
| validate-docs-structure.yml | Doc changes | ~1 min | No |
| check-shared-sync.yml | Shared changes | ~1 min | No |

### Resources

- **GitHub Actions Docs:** https://docs.github.com/en/actions
- **pytest Docs:** https://docs.pytest.org/
- **Workflows:** `.github/workflows/`
- **Pre-Deploy Check:** `bin/validation/pre_deployment_check.py`

---

**Related Documentation:**
- [Testing Strategy](./TESTING_STRATEGY.md)
- [Test README](../../tests/README.md)
- [Test Utilities](./TEST_UTILITIES.md)

**Last Updated:** January 2025
**Status:** Active
