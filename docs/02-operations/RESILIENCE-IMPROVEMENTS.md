# System Resilience Improvements

**Purpose**: Prevent future production incidents like Session 33/34 critical failures
**Created**: 2026-01-26
**Status**: Proposed improvements based on real production incidents

---

## Overview

This document outlines systematic improvements to prevent the types of critical production failures encountered in Sessions 33-34, where multiple cascading issues brought down the prediction pipeline.

**Incident Summary**:
- Phase 4 service: 100% down (SQLAlchemy + import errors + MRO conflict)
- Phase 3 processors: 80% failing (dependency validation false positives)
- Business impact: Zero predictions for 7 scheduled games
- Recovery time: 4+ hours (3 deployment iterations)

**Root Causes**:
1. Optional dependency handled as required (SQLAlchemy)
2. Import path inconsistencies (orchestration.shared vs shared)
3. MRO conflict after refactoring (missed in testing)
4. Dependency validation logic edge case (MAX across date range)

---

## Priority 1: Pre-Deployment Validation

### 1.1 Smoke Test Framework

**Problem**: Services deployed successfully but crashed immediately on first request.

**Solution**: Automated smoke tests that run BEFORE deployment approval.

```python
# File: tests/smoke/test_service_imports.py
"""
Smoke tests that verify basic service functionality.
Run these in CI and as part of deployment validation.
"""

import pytest
import importlib


class TestPhase4ServiceImports:
    """Verify Phase 4 service can import all required modules."""

    def test_main_service_imports(self):
        """Test that main_precompute_service.py imports successfully."""
        # This would have caught the SQLAlchemy and MRO issues
        from data_processors.precompute import main_precompute_service
        assert main_precompute_service is not None

    def test_all_processors_instantiate(self):
        """Test that all processor classes can be instantiated."""
        from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor
        from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor
        # ... test all processors

        # This would have caught the MRO conflict
        processor = PlayerDailyCacheProcessor(
            project_id="test-project",
            backfill_mode=True
        )
        assert processor is not None


class TestPhase3ServiceImports:
    """Verify Phase 3 service can import all required modules."""

    def test_all_analytics_processors_instantiate(self):
        """Test that all analytics processor classes work."""
        from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
        # ... test all processors

        processor = PlayerGameSummaryProcessor(
            project_id="test-project",
            backfill_mode=True
        )
        assert processor is not None
```

**Implementation**:
1. Add smoke tests to CI pipeline (runs on every commit)
2. Add to deployment script (runs before Cloud Run deploy)
3. Fail fast if smoke tests fail

**Deployment Script Addition**:
```bash
# In deploy_precompute_processors.sh, BEFORE deployment:

echo "🧪 Running smoke tests..."
python -m pytest tests/smoke/test_service_imports.py -v

if [ $? -ne 0 ]; then
    echo "❌ Smoke tests failed! Aborting deployment."
    exit 1
fi

echo "✅ Smoke tests passed, proceeding with deployment..."
```

**Estimated Time**: 2 hours to implement
**Impact**: Would have caught ALL three Phase 4 issues before deployment

---

### 1.2 MRO Validation Check

**Problem**: Diamond inheritance after refactoring created MRO conflict.

**Solution**: Automated MRO validation for all processor classes.

```python
# File: tests/smoke/test_mro_validation.py
"""
Validate method resolution order (MRO) for all processor classes.
Catches diamond inheritance and circular dependency issues.
"""

import pytest
import inspect
from typing import List, Type


def get_all_processor_classes() -> List[Type]:
    """Discover all processor classes in the codebase."""
    from data_processors.analytics import analytics_base
    from data_processors.precompute.base import precompute_base
    from data_processors.raw import raw_processor_base

    processors = []

    # Scan analytics processors
    for name, obj in inspect.getmembers(analytics_base):
        if inspect.isclass(obj) and name.endswith('Processor'):
            processors.append(obj)

    # Scan precompute processors
    # ... similar for precompute and raw

    return processors


class TestProcessorMRO:
    """Validate MRO for all processor classes."""

    @pytest.mark.parametrize("processor_class", get_all_processor_classes())
    def test_processor_mro_valid(self, processor_class):
        """Test that each processor class has valid MRO."""
        try:
            # This will raise TypeError if MRO is invalid
            mro = processor_class.__mro__
            assert len(mro) > 0
        except TypeError as e:
            pytest.fail(f"Invalid MRO for {processor_class.__name__}: {e}")

    @pytest.mark.parametrize("processor_class", get_all_processor_classes())
    def test_no_duplicate_base_classes(self, processor_class):
        """Test that no mixin appears multiple times in inheritance chain."""
        bases = processor_class.__bases__
        all_bases = set()

        def collect_bases(cls):
            for base in cls.__bases__:
                if base != object:
                    if base in all_bases:
                        return base  # Duplicate found
                    all_bases.add(base)
                    duplicate = collect_bases(base)
                    if duplicate:
                        return duplicate
            return None

        duplicate = collect_bases(processor_class)
        if duplicate:
            pytest.fail(f"{processor_class.__name__} has duplicate base class: {duplicate.__name__}")
```

**CI Integration**:
```yaml
# .github/workflows/tests.yml
name: Tests
on: [push, pull_request]
jobs:
  smoke-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run MRO validation
        run: pytest tests/smoke/test_mro_validation.py -v
      - name: Run import smoke tests
        run: pytest tests/smoke/test_service_imports.py -v
```

**Estimated Time**: 1 hour to implement
**Impact**: Would have caught MRO issue immediately after refactoring

---

### 1.3 Import Path Linter

**Problem**: Mixed usage of `orchestration.shared.utils` and `shared.utils` in shared code.

**Solution**: Pre-commit hook that prevents incorrect import paths.

```python
# File: .pre-commit-hooks/check_import_paths.py
"""
Prevent shared code from importing from orchestration.shared.utils.
Shared code should only import from shared.utils.
"""

import re
import sys
from pathlib import Path


def check_file(filepath: Path) -> list:
    """Check a single file for incorrect import paths."""
    errors = []

    # Only check files in shared/ directory
    if not str(filepath).startswith('shared/'):
        return errors

    with open(filepath, 'r') as f:
        for line_num, line in enumerate(f, 1):
            # Check for: from orchestration.shared.utils import ...
            if re.search(r'from\s+orchestration\.shared\.', line):
                errors.append(
                    f"{filepath}:{line_num}: "
                    f"Shared code must not import from orchestration.shared.* "
                    f"(use shared.* instead)\n"
                    f"  Found: {line.strip()}"
                )

    return errors


def main():
    """Check all Python files in shared/ directory."""
    shared_dir = Path('shared')
    errors = []

    for py_file in shared_dir.rglob('*.py'):
        errors.extend(check_file(py_file))

    if errors:
        print("❌ Import path violations found:\n")
        for error in errors:
            print(error)
        print("\nFix: Change 'from orchestration.shared.utils.*' to 'from shared.utils.*'")
        sys.exit(1)

    print("✅ All import paths valid")
    sys.exit(0)


if __name__ == '__main__':
    main()
```

**Pre-Commit Hook Configuration**:
```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: check-import-paths
        name: Check import paths in shared code
        entry: python .pre-commit-hooks/check_import_paths.py
        language: system
        pass_filenames: false
        always_run: true
```

**Estimated Time**: 30 minutes to implement
**Impact**: Would have prevented all 4 import path issues

---

## Priority 2: Deployment Safety

### 2.1 Canary Deployments

**Problem**: Full rollout of broken code caused 100% service outage.

**Solution**: Deploy to 10% traffic first, verify health, then 100%.

```bash
# Modified deployment script with canary support

deploy_with_canary() {
    SERVICE_NAME=$1

    echo "📦 Deploying canary (10% traffic)..."
    gcloud run deploy $SERVICE_NAME \
        --source=. \
        --region=$REGION \
        --tag=canary \
        --no-traffic \
        # ... other flags

    echo "🔀 Routing 10% traffic to canary..."
    gcloud run services update-traffic $SERVICE_NAME \
        --region=$REGION \
        --to-revisions=canary=10

    echo "⏳ Monitoring canary for 2 minutes..."
    sleep 120

    # Check canary health
    ERROR_RATE=$(check_error_rate $SERVICE_NAME "canary")

    if [ $ERROR_RATE -gt 5 ]; then
        echo "❌ Canary showing errors ($ERROR_RATE%), rolling back..."
        gcloud run services update-traffic $SERVICE_NAME \
            --region=$REGION \
            --to-revisions=canary=0
        exit 1
    fi

    echo "✅ Canary healthy, promoting to 100%..."
    gcloud run services update-traffic $SERVICE_NAME \
        --region=$REGION \
        --to-latest
}
```

**Benefits**:
- Limits blast radius to 10% of traffic
- Provides early warning of issues
- Easy rollback if problems detected

**Estimated Time**: 2 hours to implement + test
**Impact**: Would have limited Phase 4 outage to 10% of requests

---

### 2.2 Health Check Enhancement

**Problem**: Health endpoint showed "True" but service was crashing on actual requests.

**Solution**: Multi-level health checks with actual module imports.

```python
# File: data_processors/precompute/main_precompute_service.py

@app.route('/health')
def health_check():
    """Enhanced health check that validates actual functionality."""
    checks = {
        'basic': False,
        'imports': False,
        'processors': False,
        'database': False,
    }

    try:
        # Level 1: Basic check
        checks['basic'] = True

        # Level 2: Import check
        from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor
        from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor
        checks['imports'] = True

        # Level 3: Processor instantiation check
        proc = PlayerDailyCacheProcessor(
            project_id=os.getenv('GCP_PROJECT_ID', 'nba-props-platform'),
            backfill_mode=True
        )
        checks['processors'] = True

        # Level 4: Database connectivity check
        from shared.clients.bigquery_pool import get_bigquery_client
        client = get_bigquery_client()
        # Simple query to verify connectivity
        list(client.query("SELECT 1").result())
        checks['database'] = True

        # All checks passed
        return jsonify({
            'status': 'healthy',
            'checks': checks,
            'version': os.getenv('COMMIT_SHA', 'unknown')
        }), 200

    except Exception as e:
        # Partial health - some checks failed
        return jsonify({
            'status': 'degraded',
            'checks': checks,
            'error': str(e),
            'version': os.getenv('COMMIT_SHA', 'unknown')
        }), 503
```

**Monitoring Integration**:
```yaml
# Cloud Run health check configuration
healthCheck:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 30
  failureThreshold: 3  # Fail after 3 consecutive failures
```

**Estimated Time**: 1 hour per service
**Impact**: Would have detected Phase 4 import failures in health checks

---

### 2.3 Staged Deployments

**Problem**: Direct production deployment with no intermediate testing.

**Solution**: dev → staging → production deployment pipeline.

```bash
# Deployment stages

# Stage 1: Deploy to dev environment
deploy_to_dev() {
    gcloud run deploy $SERVICE_NAME-dev \
        --source=. \
        --region=$REGION \
        --set-env-vars="ENVIRONMENT=dev" \
        # ... other flags

    echo "🧪 Running integration tests on dev..."
    run_integration_tests "dev"
}

# Stage 2: Deploy to staging (if dev passes)
deploy_to_staging() {
    gcloud run deploy $SERVICE_NAME-staging \
        --source=. \
        --region=$REGION \
        --set-env-vars="ENVIRONMENT=staging" \
        # ... other flags

    echo "🧪 Running smoke tests on staging..."
    run_smoke_tests "staging"
}

# Stage 3: Deploy to production (if staging passes)
deploy_to_production() {
    deploy_with_canary $SERVICE_NAME  # Use canary deployment
}

# Full pipeline
./deploy.sh --stage=dev && \
./deploy.sh --stage=staging && \
./deploy.sh --stage=production
```

**Benefits**:
- Catch issues in dev before they reach production
- Test with production-like data in staging
- Confidence before production deployment

**Estimated Time**: 4 hours to set up environments
**Impact**: Would have caught all issues in dev/staging

---

## Priority 3: Dependency Management

### 3.1 Conditional Dependency Pattern

**Problem**: SQLAlchemy treated as required but only needed in some services.

**Solution**: Standardize pattern for optional dependencies.

```python
# File: shared/utils/optional_imports.py
"""
Standard patterns for importing optional dependencies.
Use these helpers instead of direct imports for optional packages.
"""

from typing import Optional, Any


class OptionalImport:
    """Helper for optional imports that fail gracefully."""

    def __init__(self, module_name: str, package_name: str = None):
        self.module_name = module_name
        self.package_name = package_name or module_name
        self._module: Optional[Any] = None
        self._attempted = False

    @property
    def available(self) -> bool:
        """Check if the optional dependency is available."""
        if not self._attempted:
            try:
                self._module = __import__(self.module_name)
                self._attempted = True
            except ImportError:
                self._attempted = True
                self._module = None
        return self._module is not None

    def __getattr__(self, name: str):
        """Access module attributes if available."""
        if not self.available:
            raise ImportError(
                f"Optional dependency '{self.package_name}' is not installed. "
                f"Install with: pip install {self.package_name}"
            )
        return getattr(self._module, name)


# Define optional dependencies
sqlalchemy = OptionalImport('sqlalchemy')
selenium = OptionalImport('selenium')
playwright = OptionalImport('playwright')
```

**Usage in sentry_config.py**:
```python
# File: shared/utils/sentry_config.py

from shared.utils.optional_imports import sqlalchemy

def configure_sentry():
    integrations = [
        FlaskIntegration(transaction_style='endpoint'),
        LoggingIntegration(level=None, event_level=None),
    ]

    # Add SQLAlchemy integration if available
    if sqlalchemy.available:
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        integrations.append(SqlalchemyIntegration())

    sentry_sdk.init(
        # ...
        integrations=integrations
    )
```

**Benefits**:
- Clear pattern for all optional dependencies
- Self-documenting (shows package name in error)
- Consistent across codebase

**Estimated Time**: 2 hours to implement + refactor existing code
**Impact**: Prevents future optional dependency issues

---

### 3.2 Dependency Audit Tool

**Problem**: No visibility into which services need which dependencies.

**Solution**: Automated dependency audit script.

```python
# File: bin/maintenance/audit_dependencies.py
"""
Audit tool to verify dependencies are correctly declared.
Checks that all imports have corresponding requirements.txt entries.
"""

import ast
import sys
from pathlib import Path
from typing import Set, Dict


def extract_imports(file_path: Path) -> Set[str]:
    """Extract all imports from a Python file."""
    with open(file_path, 'r') as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split('.')[0])

    return imports


def get_requirements(requirements_file: Path) -> Set[str]:
    """Parse requirements.txt file."""
    if not requirements_file.exists():
        return set()

    requirements = set()
    with open(requirements_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                # Extract package name (before ==, >=, etc.)
                pkg = line.split('==')[0].split('>=')[0].split('<')[0]
                requirements.add(pkg.replace('-', '_').lower())

    return requirements


def audit_service(service_dir: Path) -> Dict[str, Set[str]]:
    """Audit a service directory for missing dependencies."""
    # Get all imports used in the service
    all_imports = set()
    for py_file in service_dir.rglob('*.py'):
        all_imports.update(extract_imports(py_file))

    # Get declared requirements
    req_file = service_dir / 'requirements.txt'
    requirements = get_requirements(req_file)

    # Standard library modules (don't need requirements)
    stdlib = {'os', 'sys', 'datetime', 'json', 're', 'logging', 'typing', 'pathlib', ...}

    # Internal modules (don't need requirements)
    internal = {'shared', 'data_processors', 'orchestration', 'tests'}

    # Find missing requirements
    external_imports = all_imports - stdlib - internal
    missing = external_imports - requirements

    return {
        'imports': all_imports,
        'requirements': requirements,
        'missing': missing
    }


# Run audit
services = [
    'data_processors/precompute',
    'data_processors/analytics',
    'data_processors/raw',
]

for service_path in services:
    service_dir = Path(service_path)
    result = audit_service(service_dir)

    if result['missing']:
        print(f"❌ {service_path}: Missing requirements:")
        for pkg in sorted(result['missing']):
            print(f"   - {pkg}")
    else:
        print(f"✅ {service_path}: All dependencies declared")
```

**CI Integration**:
```yaml
# Run in CI to catch missing dependencies
- name: Audit dependencies
  run: python bin/maintenance/audit_dependencies.py
```

**Estimated Time**: 3 hours to implement
**Impact**: Would have flagged SQLAlchemy usage without requirement

---

## Priority 4: Testing & Validation

### 4.1 Dependency Validation Unit Tests

**Problem**: Dependency freshness logic had edge case (MAX across date range).

**Solution**: Comprehensive unit tests for edge cases.

```python
# File: tests/unit/analytics/test_dependency_validation.py
"""
Unit tests for dependency freshness validation logic.
Tests edge cases like out-of-order data, backfills, and date ranges.
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch


class TestDependencyFreshnessValidation:
    """Test dependency freshness check edge cases."""

    def test_max_from_latest_date_not_entire_range(self):
        """
        Test that freshness uses MAX from latest date, not entire range.

        Regression test for Session 33 issue where:
        - Data exists for 2026-01-20 through 2026-01-26
        - Some data from 2026-01-22 was processed 96h ago
        - Latest data from 2026-01-26 was processed 13h ago
        - Should report 13h (latest), not 96h (max across range)
        """
        # Mock BigQuery results
        mock_result = [
            Mock(row_count=70, last_updated=datetime(2026, 1, 26, 6, 9, 50))
        ]

        with patch('shared.clients.bigquery_pool.get_bigquery_client') as mock_bq:
            mock_bq.return_value.query.return_value.result.return_value = mock_result

            from data_processors.analytics.mixins.dependency_mixin import DependencyMixin

            mixin = DependencyMixin()
            mixin.bq_client = mock_bq.return_value
            mixin.project_id = 'test-project'

            # Check dependency for date range
            exists, details = mixin._check_table_data(
                table_name='nba_raw.nbac_team_boxscore',
                config={
                    'check_type': 'date_range',
                    'max_age_hours_fail': 72
                },
                start_date='2026-01-20',
                end_date='2026-01-26'
            )

            # Verify freshness calculated from LATEST date only
            assert details['age_hours'] < 24  # 13h, not 96h
            assert exists is True

    def test_lookback_days_with_sparse_data(self):
        """Test lookback_days check with data gaps."""
        # Test that lookback_days handles missing intermediate dates
        pass

    def test_backfill_concurrent_with_daily_processing(self):
        """Test that backfill doesn't interfere with daily freshness checks."""
        pass
```

**Estimated Time**: 4 hours to write comprehensive tests
**Impact**: Would have caught dependency validation edge case

---

### 4.2 Integration Tests for Full Pipeline

**Problem**: Unit tests pass but integration fails.

**Solution**: End-to-end pipeline integration tests.

```python
# File: tests/integration/test_phase3_to_phase5_pipeline.py
"""
Integration tests that verify full pipeline flow.
Tests Phase 3 → Phase 4 → Phase 5 with real (test) data.
"""

import pytest
from datetime import date
from google.cloud import bigquery, firestore


@pytest.mark.integration
class TestPhase3ToPhase5Pipeline:
    """Test complete pipeline execution."""

    @pytest.fixture
    def test_date(self):
        """Use a fixed test date."""
        return date(2024, 11, 22)

    @pytest.fixture
    def setup_test_data(self, test_date):
        """Load minimal test data into test project."""
        # Load test schedule data
        # Load test boxscore data
        # Load test betting lines
        # etc.
        yield
        # Cleanup test data

    def test_phase3_completion_triggers_phase4(self, test_date, setup_test_data):
        """Test that Phase 3 completion triggers Phase 4."""
        # 1. Trigger Phase 3 processors
        # 2. Poll Firestore for completion
        # 3. Verify Phase 4 was triggered
        # 4. Verify ML features generated
        pass

    def test_stale_data_handling(self, test_date):
        """Test that pipeline handles stale data gracefully."""
        # Test with data that's 50h old (warn threshold)
        # Verify warning logged but processing continues
        pass

    def test_missing_optional_dependency_handling(self, test_date):
        """Test graceful degradation with missing optional data."""
        # Test with missing play-by-play data (optional)
        # Verify processing continues with degraded quality
        pass
```

**CI Integration**:
```yaml
# Run integration tests nightly (not on every commit)
# Uses test GCP project

name: Integration Tests
on:
  schedule:
    - cron: '0 2 * * *'  # 2 AM daily

jobs:
  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup test environment
        run: ./tests/integration/setup_test_env.sh
      - name: Run integration tests
        run: pytest tests/integration/ -v --test-project=nba-test-project
```

**Estimated Time**: 8 hours to implement
**Impact**: Catches integration issues before production

---

## Priority 5: Monitoring & Alerting

### 5.1 Proactive Error Detection

**Problem**: Issues discovered manually during health check, not automatically.

**Solution**: Cloud Monitoring alerts for error patterns.

```yaml
# File: monitoring/alert_policies.yaml
# Terraform/GCP configuration for monitoring alerts

alert_policies:
  - name: "Phase4 High Error Rate"
    conditions:
      - metric: "logging.googleapis.com/user/error_count"
        filter: 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase4-precompute-processors"'
        aggregation:
          alignmentPeriod: 300s  # 5 minutes
          perSeriesAligner: ALIGN_RATE
        comparison: COMPARISON_GT
        threshold_value: 5  # More than 5 errors/minute
        duration: 300s
    notification_channels:
      - email:nchammas@gmail.com
      - slack:#nba-alerts

  - name: "Phase3 Stale Dependency False Positives"
    conditions:
      - metric: "logging.googleapis.com/user/stale_dependency_errors"
        filter: 'textPayload=~"Stale dependencies.*FAIL threshold"'
        aggregation:
          alignmentPeriod: 600s  # 10 minutes
          perSeriesAligner: ALIGN_COUNT
        comparison: COMPARISON_GT
        threshold_value: 3  # More than 3 stale errors in 10 min
        duration: 600s
    notification_channels:
      - email:nchammas@gmail.com

  - name: "Service Import Failures"
    conditions:
      - metric: "logging.googleapis.com/user/module_not_found_errors"
        filter: 'textPayload=~"ModuleNotFoundError"'
        comparison: COMPARISON_GT
        threshold_value: 1  # ANY ModuleNotFoundError
        duration: 60s
    notification_channels:
      - email:nchammas@gmail.com
      - pagerduty:critical
```

**Implementation**:
```bash
# Deploy alert policies
gcloud alpha monitoring policies create --policy-from-file=monitoring/alert_policies.yaml
```

**Estimated Time**: 2 hours to set up alerts
**Impact**: Would have alerted immediately on Phase 4 failures

---

### 5.2 Deployment Health Dashboard

**Problem**: No visibility into deployment success/failure rates.

**Solution**: Real-time dashboard showing deployment metrics.

```sql
-- BigQuery view for deployment metrics
CREATE OR REPLACE VIEW nba_orchestration.deployment_health AS
SELECT
  service_name,
  DATE(deployment_time) as deployment_date,
  commit_sha,

  -- Deployment success rate
  COUNTIF(status = 'success') as successful_deployments,
  COUNTIF(status = 'failed') as failed_deployments,
  ROUND(100.0 * COUNTIF(status = 'success') / COUNT(*), 1) as success_rate_pct,

  -- Error rates post-deployment
  COUNTIF(errors_1h_post_deploy > 10) as deployments_with_errors,
  AVG(errors_1h_post_deploy) as avg_errors_post_deploy,

  -- Rollback rates
  COUNTIF(rolled_back = TRUE) as rollbacks,

  -- Health check pass rates
  ROUND(100.0 * COUNTIF(health_check_passed = TRUE) / COUNT(*), 1) as health_pass_rate_pct

FROM nba_orchestration.deployment_log
WHERE deployment_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY service_name, deployment_date, commit_sha
ORDER BY deployment_date DESC, service_name
```

**Dashboard in Looker/Data Studio**:
- Deployment success rate over time
- Error rate spikes correlated with deployments
- Rollback frequency
- Time to detect issues (deployment → first error)

**Estimated Time**: 4 hours to build dashboard
**Impact**: Visibility into deployment health trends

---

## Implementation Roadmap

### Phase 1: Quick Wins (1-2 days)
1. ✅ Import path linter (30 min)
2. ✅ MRO validation tests (1 hour)
3. ✅ Smoke test framework (2 hours)
4. ✅ Enhanced health checks (1 hour per service = 3 hours)

**Total**: ~7 hours
**Impact**: Catches most critical issues before deployment

### Phase 2: Deployment Safety (1 week)
1. Canary deployment pattern (2 hours)
2. Staged environments (dev/staging/prod) (4 hours)
3. Deployment health monitoring (4 hours)
4. Conditional dependency pattern (2 hours)

**Total**: ~12 hours
**Impact**: Limits blast radius, enables safe deployments

### Phase 3: Comprehensive Testing (2 weeks)
1. Dependency validation unit tests (4 hours)
2. Integration test framework (8 hours)
3. Dependency audit tool (3 hours)
4. CI/CD pipeline enhancements (4 hours)

**Total**: ~19 hours
**Impact**: Catches issues in CI before they reach production

### Phase 4: Proactive Monitoring (1 week)
1. Error detection alerts (2 hours)
2. Deployment health dashboard (4 hours)
3. Anomaly detection (4 hours)
4. Runbook automation (4 hours)

**Total**: ~14 hours
**Impact**: Faster detection and response to issues

---

## Success Metrics

### Deployment Reliability
- **Baseline**: 67% deployment success rate (2/3 Phase 4 deployments failed)
- **Target**: 95% deployment success rate
- **Measure**: `successful_deployments / total_deployments`

### Time to Detect Issues
- **Baseline**: 4+ hours (manual health check discovery)
- **Target**: <5 minutes (automated monitoring)
- **Measure**: `time(first_error) - time(deployment_complete)`

### Time to Recover
- **Baseline**: 4+ hours (3 deployment iterations)
- **Target**: <30 minutes (canary rollback)
- **Measure**: `time(service_restored) - time(issue_detected)`

### Test Coverage
- **Baseline**: Integration tests don't cover service imports
- **Target**: 100% of services have smoke tests
- **Measure**: `services_with_smoke_tests / total_services`

### False Positive Rate
- **Baseline**: Dependency validation had false positives
- **Target**: <1% false positive rate on dependency checks
- **Measure**: Manual review of dependency errors

---

## Maintenance

### Weekly Reviews
- Review deployment success rates
- Analyze any deployment failures
- Update runbooks based on incidents

### Monthly Reviews
- Review alert effectiveness (true positive rate)
- Update health check coverage
- Refine smoke tests based on failures

### Quarterly Reviews
- Major refactoring should trigger:
  - MRO validation review
  - Dependency audit
  - Integration test updates

---

## Conclusion

These improvements, if implemented, would have prevented or significantly mitigated the Session 33/34 incidents:

1. **Smoke tests**: Would have caught ALL three Phase 4 issues in CI
2. **MRO validation**: Would have caught diamond inheritance immediately
3. **Import linter**: Would have prevented incorrect import paths
4. **Canary deployments**: Would have limited outage to 10% of traffic
5. **Enhanced health checks**: Would have detected failures in deployment verification
6. **Proactive alerts**: Would have notified team immediately instead of 4+ hours later

**Estimated Total Implementation Time**: ~50 hours (2.5 weeks)
**Expected ROI**: Prevention of 4+ hour production outages

**Priority Order**:
1. Phase 1 (Quick Wins) - Implement ASAP
2. Phase 2 (Deployment Safety) - Implement before next major refactoring
3. Phase 3 (Testing) - Implement as part of ongoing development
4. Phase 4 (Monitoring) - Implement to reduce incident response time
