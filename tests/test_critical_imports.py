"""
Critical Import Validation Tests

Tests that all critical imports work correctly before deployment.
This prevents the Jan 16-20 ModuleNotFoundError incident.

Purpose:
- Validate all processor imports resolve correctly
- Check shared module imports
- Verify Cloud Run service dependencies
- Prevent deployment of broken imports

Run before every deployment:
    pytest tests/test_critical_imports.py -v

Created: 2026-01-21
"""

import pytest
import sys
import importlib
from pathlib import Path


class TestDataProcessorImports:
    """Test data_processors module imports."""

    def test_analytics_processors_import(self):
        """Test Phase 3 analytics processor imports."""
        from data_processors.analytics import (
            PlayerGameSummaryProcessor,
            TeamDefenseGameSummaryProcessor,
            TeamOffenseGameSummaryProcessor,
            UpcomingPlayerGameContextProcessor,
            UpcomingTeamGameContextProcessor,
        )
        assert PlayerGameSummaryProcessor is not None
        assert TeamDefenseGameSummaryProcessor is not None
        assert TeamOffenseGameSummaryProcessor is not None
        assert UpcomingPlayerGameContextProcessor is not None
        assert UpcomingTeamGameContextProcessor is not None

    def test_precompute_processors_import(self):
        """Test Phase 4 precompute processor imports."""
        from data_processors.precompute import (
            TeamDefenseZoneAnalysisProcessor,
            PlayerShotZoneAnalysisProcessor,
            PlayerCompositeFactorsProcessor,
            PlayerDailyCacheProcessor,
            MLFeatureStoreProcessor,
        )
        assert TeamDefenseZoneAnalysisProcessor is not None
        assert PlayerShotZoneAnalysisProcessor is not None
        assert PlayerCompositeFactorsProcessor is not None
        assert PlayerDailyCacheProcessor is not None
        assert MLFeatureStoreProcessor is not None

    def test_raw_processors_import(self):
        """Test Phase 2 raw data processor imports."""
        from data_processors.raw import (
            BdlPlayerBoxscoresProcessor,
            NbacScheduleProcessor,
            OddsApiGameLinesProcessor,
        )
        assert BdlPlayerBoxscoresProcessor is not None
        assert NbacScheduleProcessor is not None
        assert OddsApiGameLinesProcessor is not None

    def test_grading_processors_import(self):
        """Test Phase 5 grading processor imports."""
        from data_processors.grading import (
            PredictionGradingProcessor,
            LineValueAnalysisProcessor,
        )
        assert PredictionGradingProcessor is not None
        assert LineValueAnalysisProcessor is not None

    def test_publishing_processors_import(self):
        """Test Phase 6 publishing processor imports."""
        from data_processors.publishing import (
            PublishingProcessor,
        )
        assert PublishingProcessor is not None


class TestSharedModuleImports:
    """Test shared module imports."""

    def test_config_imports(self):
        """Test orchestration config imports."""
        from shared.config.orchestration_config import (
            get_orchestration_config,
            OrchestrationConfig,
            PhaseTransitionConfig,
        )
        assert get_orchestration_config is not None
        assert OrchestrationConfig is not None
        assert PhaseTransitionConfig is not None

    def test_bigquery_client_imports(self):
        """Test BigQuery client imports."""
        from shared.clients.bigquery_pool import get_bigquery_client
        assert get_bigquery_client is not None

    def test_firestore_client_imports(self):
        """Test Firestore client imports."""
        from google.cloud import firestore
        assert firestore.Client is not None

    def test_pubsub_client_imports(self):
        """Test Pub/Sub client imports."""
        from google.cloud import pubsub_v1
        assert pubsub_v1.PublisherClient is not None
        assert pubsub_v1.SubscriberClient is not None

    def test_slack_utils_imports(self):
        """Test Slack utility imports."""
        from shared.utils.slack_retry import send_slack_webhook_with_retry
        assert send_slack_webhook_with_retry is not None


class TestOrchestratorImports:
    """Test orchestrator function imports."""

    def test_phase2_to_phase3_imports(self):
        """Test Phase 2→3 orchestrator imports."""
        # Add orchestration directory to path
        sys.path.insert(0, str(Path(__file__).parent.parent / "orchestration" / "cloud_functions" / "phase2_to_phase3"))
        try:
            import main as phase2_main
            assert hasattr(phase2_main, 'orchestrate_phase2_to_phase3')
        finally:
            sys.path.pop(0)

    def test_phase3_to_phase4_imports(self):
        """Test Phase 3→4 orchestrator imports."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "orchestration" / "cloud_functions" / "phase3_to_phase4"))
        try:
            import main as phase3_main
            assert hasattr(phase3_main, 'orchestrate_phase3_to_phase4')
        finally:
            sys.path.pop(0)

    def test_phase4_to_phase5_imports(self):
        """Test Phase 4→5 orchestrator imports."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "orchestration" / "cloud_functions" / "phase4_to_phase5"))
        try:
            import main as phase4_main
            assert hasattr(phase4_main, 'orchestrate_phase4_to_phase5')
        finally:
            sys.path.pop(0)

    def test_phase5_to_phase6_imports(self):
        """Test Phase 5→6 orchestrator imports."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "orchestration" / "cloud_functions" / "phase5_to_phase6"))
        try:
            import main as phase5_main
            assert hasattr(phase5_main, 'orchestrate_phase5_to_phase6')
        finally:
            sys.path.pop(0)


class TestPredictionSystemImports:
    """Test prediction system imports."""

    def test_prediction_coordinator_imports(self):
        """Test prediction coordinator imports."""
        from predictions.coordinator.prediction_coordinator import PredictionCoordinator
        assert PredictionCoordinator is not None

    def test_prediction_worker_imports(self):
        """Test prediction worker imports."""
        from predictions.worker.prediction_worker import PredictionWorker
        assert PredictionWorker is not None


class TestValidationSystemImports:
    """Test validation system imports."""

    def test_validator_imports(self):
        """Test validator imports."""
        from validation.validators.analytics.player_game_summary_validator import PlayerGameSummaryValidator
        assert PlayerGameSummaryValidator is not None


def test_all_imports_comprehensive():
    """
    Comprehensive import test - fails if ANY critical import fails.

    This is the main gate for deployment - if this passes, imports are safe.
    """
    import_tests = [
        # Data processors
        "data_processors.analytics",
        "data_processors.precompute",
        "data_processors.raw",
        "data_processors.grading",
        "data_processors.publishing",

        # Shared modules
        "shared.config.orchestration_config",
        "shared.clients.bigquery_pool",
        "shared.utils.slack_retry",

        # Cloud clients
        "google.cloud.firestore",
        "google.cloud.pubsub_v1",
        "google.cloud.bigquery",

        # Predictions
        "predictions.coordinator.prediction_coordinator",
        "predictions.worker.prediction_worker",
    ]

    failed_imports = []

    for module_name in import_tests:
        try:
            importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError) as e:
            failed_imports.append(f"{module_name}: {e}")

    if failed_imports:
        pytest.fail(f"❌ DEPLOYMENT BLOCKED: Failed imports:\n" + "\n".join(failed_imports))
    else:
        print(f"✅ All {len(import_tests)} critical imports validated successfully")


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
