"""
Smoke Test: Service Import and Instantiation

Validates that all services can import and instantiate without errors.
These tests would have caught the SQLAlchemy, MRO, and import issues from Session 34.

Purpose:
- Test Phase 3 analytics service imports (main_analytics_service.py)
- Test Phase 4 precompute service imports (main_precompute_service.py)
- Test all processor classes can be instantiated
- Test critical dependencies are importable (BigQuery, Firestore, Sentry)
- Make tests fast (<30 seconds total)

Success Criteria:
- All tests pass in under 30 seconds
- Would catch: ModuleNotFoundError, ImportError, MRO issues, missing dependencies

Run before every deployment:
    pytest tests/smoke/test_service_imports.py -v --tb=short

Created: 2026-01-26
"""

import pytest
import importlib
import os
from typing import List, Tuple
from unittest.mock import Mock, patch


class TestPhase3AnalyticsService:
    """Test Phase 3 analytics service can import without errors."""

    def test_analytics_service_imports(self):
        """
        Test main_analytics_service.py imports successfully.

        This would have caught: ModuleNotFoundError, ImportError, SQLAlchemy issues
        """
        from data_processors.analytics import main_analytics_service
        assert main_analytics_service is not None

    def test_analytics_processor_imports(self):
        """Test all analytics processors referenced in service can import."""
        from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
        from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import TeamDefenseGameSummaryProcessor
        from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import TeamOffenseGameSummaryProcessor
        from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
        from data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor import UpcomingTeamGameContextProcessor

        assert PlayerGameSummaryProcessor is not None
        assert TeamDefenseGameSummaryProcessor is not None
        assert TeamOffenseGameSummaryProcessor is not None
        assert UpcomingPlayerGameContextProcessor is not None
        assert UpcomingTeamGameContextProcessor is not None

    def test_analytics_base_import(self):
        """Test analytics base processor imports."""
        from data_processors.analytics.analytics_base import AnalyticsProcessorBase
        assert AnalyticsProcessorBase is not None


class TestPhase4PrecomputeService:
    """Test Phase 4 precompute service can import without errors."""

    def test_precompute_service_imports(self):
        """
        Test main_precompute_service.py imports successfully.

        This would have caught: ModuleNotFoundError, ImportError, MRO issues
        """
        from data_processors.precompute import main_precompute_service
        assert main_precompute_service is not None

    def test_precompute_processor_imports(self):
        """Test all precompute processors referenced in service can import."""
        from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import TeamDefenseZoneAnalysisProcessor
        from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
        from data_processors.precompute.player_composite_factors.player_composite_factors_processor import PlayerCompositeFactorsProcessor
        from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor
        from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor
        assert TeamDefenseZoneAnalysisProcessor is not None
        assert PlayerShotZoneAnalysisProcessor is not None
        assert PlayerCompositeFactorsProcessor is not None
        assert PlayerDailyCacheProcessor is not None
        assert MLFeatureStoreProcessor is not None

    def test_precompute_base_import(self):
        """Test precompute base processor imports."""
        from data_processors.precompute.base.precompute_base import PrecomputeProcessorBase
        assert PrecomputeProcessorBase is not None


class TestProcessorInstantiation:
    """Test that key processors can be instantiated (validates MRO and __init__)."""

    @patch('shared.clients.bigquery_pool.get_bigquery_client')
    @patch.dict(os.environ, {'GCP_PROJECT_ID': 'test-project'})
    def test_player_daily_cache_instantiates(self, mock_bq):
        """
        Test PlayerDailyCacheProcessor can be instantiated (MRO validation).

        This would have caught the MRO issue from Session 34 where
        BackfillModeMixin was inherited twice.
        """
        mock_bq.return_value = Mock()

        from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor

        # Should instantiate without MRO errors
        processor = PlayerDailyCacheProcessor()
        assert processor is not None
        assert hasattr(processor, 'run')

    @patch('shared.clients.bigquery_pool.get_bigquery_client')
    @patch.dict(os.environ, {'GCP_PROJECT_ID': 'test-project'})
    def test_upcoming_player_game_context_instantiates(self, mock_bq):
        """Test UpcomingPlayerGameContextProcessor can be instantiated."""
        mock_bq.return_value = Mock()

        from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor

        processor = UpcomingPlayerGameContextProcessor()
        assert processor is not None
        assert hasattr(processor, 'run')

    @patch('shared.clients.bigquery_pool.get_bigquery_client')
    @patch.dict(os.environ, {'GCP_PROJECT_ID': 'test-project'})
    def test_team_offense_game_summary_instantiates(self, mock_bq):
        """Test TeamOffenseGameSummaryProcessor can be instantiated."""
        mock_bq.return_value = Mock()

        from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import TeamOffenseGameSummaryProcessor

        processor = TeamOffenseGameSummaryProcessor()
        assert processor is not None
        assert hasattr(processor, 'run')

    @patch('shared.clients.bigquery_pool.get_bigquery_client')
    @patch.dict(os.environ, {'GCP_PROJECT_ID': 'test-project'})
    def test_all_phase4_processors_instantiate(self, mock_bq):
        """Test all Phase 4 precompute processors can be instantiated."""
        mock_bq.return_value = Mock()

        processors = [
            ('TeamDefenseZoneAnalysisProcessor',
             'data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor'),
            ('PlayerShotZoneAnalysisProcessor',
             'data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor'),
            ('PlayerDailyCacheProcessor',
             'data_processors.precompute.player_daily_cache.player_daily_cache_processor'),
            ('PlayerCompositeFactorsProcessor',
             'data_processors.precompute.player_composite_factors.player_composite_factors_processor'),
            ('MLFeatureStoreProcessor',
             'data_processors.precompute.ml_feature_store.ml_feature_store_processor'),
        ]

        for processor_name, module_path in processors:
            module = importlib.import_module(module_path)
            processor_class = getattr(module, processor_name)

            # Should instantiate without errors
            processor = processor_class()
            assert processor is not None, f"{processor_name} instantiation failed"
            assert hasattr(processor, 'run'), f"{processor_name} missing run() method"


class TestCriticalDependencies:
    """Test that critical dependencies are importable."""

    def test_bigquery_imports(self):
        """Test BigQuery client can be imported."""
        from google.cloud import bigquery
        assert bigquery.Client is not None

    def test_firestore_imports(self):
        """Test Firestore client can be imported."""
        from google.cloud import firestore
        assert firestore.Client is not None

    def test_pubsub_imports(self):
        """Test Pub/Sub client can be imported."""
        from google.cloud import pubsub_v1
        assert pubsub_v1.PublisherClient is not None
        assert pubsub_v1.SubscriberClient is not None

    def test_sentry_imports(self):
        """Test Sentry SDK can be imported."""
        import sentry_sdk
        assert sentry_sdk is not None

    def test_pandas_imports(self):
        """Test pandas can be imported."""
        import pandas as pd
        assert pd is not None

    def test_numpy_imports(self):
        """Test numpy can be imported."""
        import numpy as np
        assert np is not None


class TestSharedDependencyImports:
    """Test shared module dependencies."""

    def test_bigquery_pool_imports(self):
        """Test BigQuery connection pooling imports."""
        from shared.clients.bigquery_pool import get_bigquery_client
        assert get_bigquery_client is not None

    def test_config_imports(self):
        """Test orchestration config imports."""
        from shared.config.orchestration_config import get_orchestration_config
        assert get_orchestration_config is not None

    def test_sentry_config_imports(self):
        """Test Sentry configuration imports."""
        from shared.utils.sentry_config import configure_sentry
        assert configure_sentry is not None

    def test_validation_utils_imports(self):
        """Test validation utilities import."""
        from shared.utils.validation import validate_game_date, validate_project_id
        assert validate_game_date is not None
        assert validate_project_id is not None

    def test_health_endpoints_imports(self):
        """Test health check endpoints import."""
        from shared.endpoints.health import create_health_blueprint, HealthChecker
        assert create_health_blueprint is not None
        assert HealthChecker is not None

    def test_slack_utils_imports(self):
        """Test Slack utility imports."""
        from shared.utils.slack_retry import send_slack_webhook_with_retry
        assert send_slack_webhook_with_retry is not None


class TestMixinImports:
    """Test that mixins can be imported."""

    def test_smart_idempotency_mixin_imports(self):
        """Test SmartIdempotencyMixin imports."""
        from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
        assert SmartIdempotencyMixin is not None

    def test_backfill_mode_mixin_imports(self):
        """Test BackfillModeMixin imports."""
        from data_processors.precompute.mixins.backfill_mode_mixin import BackfillModeMixin
        assert BackfillModeMixin is not None

    def test_pattern_mixins_import(self):
        """Test pattern mixins import."""
        from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin
        assert SmartSkipMixin is not None
        assert EarlyExitMixin is not None
        assert CircuitBreakerMixin is not None


class TestCriticalPathImports:
    """Test critical path imports for all services."""

    @pytest.mark.parametrize("module_name", [
        # Analytics service dependencies
        "data_processors.analytics",
        "data_processors.analytics.analytics_base",

        # Precompute service dependencies
        "data_processors.precompute",
        "data_processors.precompute.precompute_base",

        # Shared dependencies
        "shared.config.orchestration_config",
        "shared.clients.bigquery_pool",
        "shared.utils.slack_retry",

        # GCP client libraries
        "google.cloud.firestore",
        "google.cloud.bigquery",
    ])
    def test_critical_module_imports(self, module_name: str):
        """Test that critical modules can be imported without errors."""
        try:
            importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError) as e:
            pytest.fail(
                f"DEPLOYMENT BLOCKED: Failed to import {module_name}\n"
                f"Error: {e}\n"
                f"Fix import errors before deploying to production."
            )


class TestRegressionChecks:
    """Regression tests for known issues from Session 34."""

    def test_no_sqlalchemy_import_errors(self):
        """
        Regression: Verify no SQLAlchemy import errors.

        Session 34 had "cannot import name 'URL' from 'sqlalchemy.engine'"
        because sqlalchemy wasn't pinned in requirements.txt
        """
        try:
            from sqlalchemy.engine import URL
            assert URL is not None
        except ImportError as e:
            pytest.fail(
                f"SQLAlchemy import failed: {e}\n"
                f"This is the same issue from Session 34.\n"
                f"Check requirements.txt has sqlalchemy~=1.4.0"
            )

    @patch('shared.clients.bigquery_pool.get_bigquery_client')
    @patch.dict(os.environ, {'GCP_PROJECT_ID': 'test-project'})
    def test_no_mro_errors_in_player_daily_cache(self, mock_bq):
        """
        Regression: Verify PlayerDailyCacheProcessor has valid MRO.

        Session 34 had "TypeError: Cannot create a consistent method resolution order"
        because BackfillModeMixin was inherited twice.
        """
        mock_bq.return_value = Mock()

        try:
            from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor

            # Check MRO is valid
            mro = PlayerDailyCacheProcessor.__mro__
            assert len(mro) > 0

            # Instantiate to verify no __init__ conflicts
            processor = PlayerDailyCacheProcessor()
            assert processor is not None

        except TypeError as e:
            pytest.fail(
                f"PlayerDailyCacheProcessor MRO error: {e}\n"
                f"This is the same issue from Session 34.\n"
                f"Check for duplicate base class in inheritance chain."
            )

    def test_no_missing_module_errors(self):
        """
        Regression: Verify no missing module errors.

        Session 34 had issues importing modules that should exist.
        """
        critical_modules = [
            'data_processors.analytics.main_analytics_service',
            'data_processors.precompute.main_precompute_service',
            'data_processors.precompute.player_daily_cache.player_daily_cache_processor',
            'shared.clients.bigquery_pool',
            'shared.config.orchestration_config',
        ]

        failed_imports = []
        for module_name in critical_modules:
            try:
                importlib.import_module(module_name)
            except ModuleNotFoundError as e:
                failed_imports.append(f"{module_name}: {e}")

        if failed_imports:
            pytest.fail(
                f"Critical modules missing:\n" + "\n".join(failed_imports) + "\n"
                f"This is the same issue from Session 34."
            )


def test_all_service_imports_gate():
    """
    Comprehensive service import gate - deployment blocker.

    If this test fails, deployment should be blocked.
    This is the primary gate used by CI/CD scripts.
    """
    analytics_modules = [
        "data_processors.analytics.player_game_summary.player_game_summary_processor",
        "data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor",
        "data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor",
        "data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor",
        "data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor",
    ]

    precompute_modules = [
        "data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor",
        "data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor",
        "data_processors.precompute.player_composite_factors.player_composite_factors_processor",
        "data_processors.precompute.player_daily_cache.player_daily_cache_processor",
        "data_processors.precompute.ml_feature_store.ml_feature_store_processor",
    ]

    shared_modules = [
        "shared.config.orchestration_config",
        "shared.clients.bigquery_pool",
        "shared.utils.slack_retry",
        "google.cloud.firestore",
        "google.cloud.bigquery",
    ]

    all_modules = analytics_modules + precompute_modules + shared_modules
    failed_imports: List[Tuple[str, str]] = []

    for module_name in all_modules:
        try:
            importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError) as e:
            failed_imports.append((module_name, str(e)))

    if failed_imports:
        error_msg = "DEPLOYMENT BLOCKED: Service import validation failed\n\n"
        error_msg += "Failed imports:\n"
        for module, error in failed_imports:
            error_msg += f"  - {module}\n    Error: {error}\n"
        error_msg += "\nFix all import errors before deploying to production."
        pytest.fail(error_msg)
    else:
        print(f"\n{'='*60}")
        print(f"Service Import Validation: PASSED")
        print(f"{'='*60}")
        print(f"Validated {len(all_modules)} critical modules:")
        print(f"  Analytics processors: {len(analytics_modules)}")
        print(f"  Precompute processors: {len(precompute_modules)}")
        print(f"  Shared dependencies: {len(shared_modules)}")
        print(f"{'='*60}")


if __name__ == "__main__":
    # Run with verbose output and timing
    pytest.main([__file__, "-v", "--tb=short", "--durations=10"])
