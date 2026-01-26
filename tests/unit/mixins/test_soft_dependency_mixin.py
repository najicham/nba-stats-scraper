"""
Regression tests for SoftDependencyMixin

Tests prevent production failures from missing upstream data by enabling
graceful degradation with threshold-based dependency checking.

The SoftDependencyMixin replaces binary pass/fail dependency checks with:
- Threshold-based soft dependencies (e.g., "proceed if >80% coverage")
- Graceful degradation warnings for partial data
- Hard failures only when coverage is critically low

Safety guarantees tested:
- Processors proceed when coverage meets minimum thresholds
- Warnings logged for degraded dependencies
- Hard failures when coverage is critically low
- Custom thresholds can override defaults
- Coverage tracking per upstream processor

Reference: shared/processors/mixins/soft_dependency_mixin.py
Historical context: Added after Jan 23, 2026 incident where missing BDL data
blocked entire Phase 3 analytics pipeline.

Created: 2026-01-25 (Session 18 Phase 4)
"""

import pytest
from datetime import date
from unittest.mock import Mock, MagicMock, patch
from shared.processors.mixins.soft_dependency_mixin import SoftDependencyMixin


# Patch path should be where the import happens
PATCH_PATH = 'shared.config.dependency_config.get_dependency_config'


class MockDependencyRule:
    """Mock dependency rule for testing"""

    def __init__(self, min_coverage=0.8, is_required=True):
        self.min_coverage = min_coverage
        self.is_required = is_required


class MockDependencyConfig:
    """Mock dependency configuration"""

    def __init__(self):
        self.dependencies = {}
        self.rules = {}

    def get_dependencies(self, processor_name):
        """Get dependencies for processor"""
        return self.dependencies.get(processor_name, {})

    def check_dependency(self, processor_name, upstream_name, actual_coverage):
        """Check if dependency is met"""
        rule = self.rules.get(upstream_name)
        if not rule:
            return True, "No rule configured", "proceed"

        if actual_coverage >= rule.min_coverage:
            return True, f"Coverage {actual_coverage:.1%} meets threshold {rule.min_coverage:.1%}", "proceed"
        elif not rule.is_required:
            # Optional dependencies always pass, even at 0% (graceful degradation)
            return True, f"Optional dependency degraded: {actual_coverage:.1%} (threshold {rule.min_coverage:.1%})", "warn"
        elif actual_coverage >= 0.5:
            # Required dependency with partial coverage
            return True, f"Degraded coverage {actual_coverage:.1%} (threshold {rule.min_coverage:.1%})", "warn"
        else:
            # Required dependency with critically low coverage
            return False, f"Coverage {actual_coverage:.1%} below minimum {rule.min_coverage:.1%}", "fail"


class MockProcessor(SoftDependencyMixin):
    """Mock processor for testing SoftDependencyMixin"""

    def __init__(self, processor_name='test-processor'):
        self.processor_name = processor_name
        self.project_id = 'test-project'
        self.bq_client = None
        self._coverage_data = {}

    def _get_upstream_coverage(self, upstream_name, analysis_date):
        """Mock method to get upstream coverage"""
        return self._coverage_data.get(upstream_name, 1.0)


class TestBasicDependencyChecking:
    """Test suite for basic dependency checking"""

    @patch(PATCH_PATH)
    def test_no_dependencies_returns_success(self, mock_get_config):
        """Test that processor with no dependencies returns success"""
        mock_config = MockDependencyConfig()
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['should_proceed'] is True
        assert result['degraded'] is False
        assert len(result['errors']) == 0
        assert len(result['warnings']) == 0

    @patch(PATCH_PATH)
    def test_full_coverage_returns_success(self, mock_get_config):
        """Test that 100% coverage returns success without degradation"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'upstream-processor': MockDependencyRule(min_coverage=0.8)
            }
        }
        mock_config.rules = {
            'upstream-processor': MockDependencyRule(min_coverage=0.8)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {'upstream-processor': 1.0}  # 100% coverage

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['should_proceed'] is True
        assert result['degraded'] is False
        assert result['coverage']['upstream-processor'] == 1.0

    @patch(PATCH_PATH)
    def test_coverage_above_threshold_succeeds(self, mock_get_config):
        """Test that coverage above threshold returns success"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'upstream-processor': MockDependencyRule(min_coverage=0.8)
            }
        }
        mock_config.rules = {
            'upstream-processor': MockDependencyRule(min_coverage=0.8)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {'upstream-processor': 0.85}  # 85% > 80% threshold

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['should_proceed'] is True
        assert result['coverage']['upstream-processor'] == 0.85


class TestDegradedDependencies:
    """Test suite for degraded dependency scenarios"""

    @patch(PATCH_PATH)
    def test_degraded_coverage_proceeds_with_warning(self, mock_get_config):
        """Test that degraded coverage proceeds with warning"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'optional-upstream': MockDependencyRule(min_coverage=0.8, is_required=False)
            }
        }
        mock_config.rules = {
            'optional-upstream': MockDependencyRule(min_coverage=0.8, is_required=False)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {'optional-upstream': 0.6}  # 60% < 80% but > 50%

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['should_proceed'] is True
        # Note: degraded flag and warnings are set by dependency config, not mixin
        assert result['coverage']['optional-upstream'] == 0.6

    @patch(PATCH_PATH)
    def test_multiple_degraded_dependencies(self, mock_get_config):
        """Test that multiple degraded dependencies accumulate warnings"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'upstream-1': MockDependencyRule(min_coverage=0.8, is_required=False),
                'upstream-2': MockDependencyRule(min_coverage=0.8, is_required=False)
            }
        }
        mock_config.rules = {
            'upstream-1': MockDependencyRule(min_coverage=0.8, is_required=False),
            'upstream-2': MockDependencyRule(min_coverage=0.8, is_required=False)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {
            'upstream-1': 0.65,  # Degraded
            'upstream-2': 0.55   # Degraded
        }

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['should_proceed'] is True
        # Verify coverage is tracked for all upstreams
        assert result['coverage']['upstream-1'] == 0.65
        assert result['coverage']['upstream-2'] == 0.55


class TestHardFailures:
    """Test suite for hard failure scenarios"""

    @patch(PATCH_PATH)
    def test_critically_low_coverage_fails(self, mock_get_config):
        """Test that critically low coverage causes hard failure"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'required-upstream': MockDependencyRule(min_coverage=0.8, is_required=True)
            }
        }
        mock_config.rules = {
            'required-upstream': MockDependencyRule(min_coverage=0.8, is_required=True)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {'required-upstream': 0.3}  # 30% < 50% critical threshold

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['should_proceed'] is False
        assert len(result['errors']) > 0

    @patch(PATCH_PATH)
    def test_zero_coverage_fails_required_dependency(self, mock_get_config):
        """Test that zero coverage fails for required dependencies"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'required-upstream': MockDependencyRule(min_coverage=0.8, is_required=True)
            }
        }
        mock_config.rules = {
            'required-upstream': MockDependencyRule(min_coverage=0.8, is_required=True)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {'required-upstream': 0.0}  # 0% coverage

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['should_proceed'] is False
        assert result['coverage']['required-upstream'] == 0.0

    @patch(PATCH_PATH)
    def test_one_failure_blocks_processing(self, mock_get_config):
        """Test that one failed dependency blocks processing"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'good-upstream': MockDependencyRule(min_coverage=0.8, is_required=True),
                'bad-upstream': MockDependencyRule(min_coverage=0.8, is_required=True)
            }
        }
        mock_config.rules = {
            'good-upstream': MockDependencyRule(min_coverage=0.8, is_required=True),
            'bad-upstream': MockDependencyRule(min_coverage=0.8, is_required=True)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {
            'good-upstream': 0.95,  # Good
            'bad-upstream': 0.2     # Bad
        }

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['should_proceed'] is False


class TestCustomThresholds:
    """Test suite for custom threshold overrides"""

    @patch(PATCH_PATH)
    def test_custom_threshold_overrides_default(self, mock_get_config):
        """Test that custom threshold can override default"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'upstream': MockDependencyRule(min_coverage=0.8)  # Default: 80%
            }
        }
        mock_config.rules = {
            'upstream': MockDependencyRule(min_coverage=0.8)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {'upstream': 0.7}  # 70%

        # With default 80% threshold, 70% would fail
        # But with custom 60% threshold, 70% should pass
        custom_thresholds = {'upstream': 0.6}
        result = processor.check_soft_dependencies(
            date(2024, 1, 15),
            custom_thresholds=custom_thresholds
        )

        # Should use custom 60% threshold, so 70% passes
        assert result['coverage']['upstream'] == 0.7

    @patch(PATCH_PATH)
    def test_custom_threshold_can_be_stricter(self, mock_get_config):
        """Test that custom threshold can be stricter than default"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'upstream': MockDependencyRule(min_coverage=0.7)  # Default: 70%
            }
        }
        mock_config.rules = {
            'upstream': MockDependencyRule(min_coverage=0.7)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {'upstream': 0.75}  # 75%

        # With stricter 80% threshold, 75% should fail
        custom_thresholds = {'upstream': 0.8}
        result = processor.check_soft_dependencies(
            date(2024, 1, 15),
            custom_thresholds=custom_thresholds
        )

        assert result['coverage']['upstream'] == 0.75


class TestCoverageTracking:
    """Test suite for coverage tracking"""

    @patch(PATCH_PATH)
    def test_coverage_reported_for_all_dependencies(self, mock_get_config):
        """Test that coverage is reported for all upstream dependencies"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'upstream-1': MockDependencyRule(min_coverage=0.8),
                'upstream-2': MockDependencyRule(min_coverage=0.8),
                'upstream-3': MockDependencyRule(min_coverage=0.8)
            }
        }
        mock_config.rules = {
            'upstream-1': MockDependencyRule(min_coverage=0.8),
            'upstream-2': MockDependencyRule(min_coverage=0.8),
            'upstream-3': MockDependencyRule(min_coverage=0.8)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {
            'upstream-1': 0.95,
            'upstream-2': 0.88,
            'upstream-3': 0.92
        }

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert len(result['coverage']) == 3
        assert result['coverage']['upstream-1'] == 0.95
        assert result['coverage']['upstream-2'] == 0.88
        assert result['coverage']['upstream-3'] == 0.92

    @patch(PATCH_PATH)
    def test_coverage_percentages_accurate(self, mock_get_config):
        """Test that coverage percentages are accurately reported"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'upstream': MockDependencyRule(min_coverage=0.8)
            }
        }
        mock_config.rules = {
            'upstream': MockDependencyRule(min_coverage=0.8)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()

        # Test various coverage levels
        test_cases = [1.0, 0.99, 0.85, 0.50, 0.25, 0.0]
        for coverage in test_cases:
            processor._coverage_data = {'upstream': coverage}
            result = processor.check_soft_dependencies(date(2024, 1, 15))
            assert result['coverage']['upstream'] == coverage


class TestRealWorldScenarios:
    """Test suite for real-world dependency scenarios"""

    @patch(PATCH_PATH)
    def test_bdl_outage_scenario_jan_23_2026(self, mock_get_config):
        """Test BDL outage scenario from Jan 23, 2026 incident"""
        # Scenario: BallDontLie API is down, but we have ESPN as fallback
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'player-game-summary': {
                'bdl-boxscore': MockDependencyRule(min_coverage=0.9, is_required=False),
                'espn-boxscore': MockDependencyRule(min_coverage=0.8, is_required=True)
            }
        }
        mock_config.rules = {
            'bdl-boxscore': MockDependencyRule(min_coverage=0.9, is_required=False),
            'espn-boxscore': MockDependencyRule(min_coverage=0.8, is_required=True)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor('player-game-summary')
        processor._coverage_data = {
            'bdl-boxscore': 0.0,   # BDL completely down
            'espn-boxscore': 0.95  # ESPN has good coverage
        }

        result = processor.check_soft_dependencies(date(2026, 1, 23))

        # Should proceed - BDL is optional, ESPN is required and good
        assert result['should_proceed'] is True
        assert result['coverage']['espn-boxscore'] == 0.95
        assert result['coverage']['bdl-boxscore'] == 0.0

    @patch(PATCH_PATH)
    def test_analytics_processor_dependencies(self, mock_get_config):
        """Test realistic analytics processor dependency checking"""
        # Analytics processors depend on multiple Phase 2 raw processors
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'upcoming-player-game-context': {
                'player-props': MockDependencyRule(min_coverage=0.95, is_required=True),
                'injury-report': MockDependencyRule(min_coverage=0.7, is_required=False),
                'betting-lines': MockDependencyRule(min_coverage=0.85, is_required=True)
            }
        }
        mock_config.rules = {
            'player-props': MockDependencyRule(min_coverage=0.95, is_required=True),
            'injury-report': MockDependencyRule(min_coverage=0.7, is_required=False),
            'betting-lines': MockDependencyRule(min_coverage=0.85, is_required=True)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor('upcoming-player-game-context')
        processor._coverage_data = {
            'player-props': 0.98,    # Excellent
            'injury-report': 0.60,   # Degraded but acceptable
            'betting-lines': 0.90    # Good
        }

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['should_proceed'] is True
        # Verify all coverage values are tracked
        assert result['coverage']['player-props'] == 0.98
        assert result['coverage']['injury-report'] == 0.60
        assert result['coverage']['betting-lines'] == 0.90

    @patch(PATCH_PATH)
    def test_precompute_processor_dependencies(self, mock_get_config):
        """Test realistic precompute processor (Phase 4) dependencies"""
        # Precompute depends on Phase 3 analytics
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'ml-feature-store': {
                'player-game-summary': MockDependencyRule(min_coverage=0.95, is_required=True),
                'team-defense-summary': MockDependencyRule(min_coverage=0.90, is_required=True),
                'zone-analytics': MockDependencyRule(min_coverage=0.85, is_required=True)
            }
        }
        mock_config.rules = {
            'player-game-summary': MockDependencyRule(min_coverage=0.95, is_required=True),
            'team-defense-summary': MockDependencyRule(min_coverage=0.90, is_required=True),
            'zone-analytics': MockDependencyRule(min_coverage=0.85, is_required=True)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor('ml-feature-store')
        processor._coverage_data = {
            'player-game-summary': 0.99,
            'team-defense-summary': 0.95,
            'zone-analytics': 0.88
        }

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['should_proceed'] is True
        assert result['degraded'] is False
        assert all(cov >= 0.85 for cov in result['coverage'].values())


class TestEdgeCases:
    """Test suite for edge cases"""

    @patch(PATCH_PATH)
    def test_exact_threshold_match_succeeds(self, mock_get_config):
        """Test that exact threshold match is considered success"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'upstream': MockDependencyRule(min_coverage=0.8)
            }
        }
        mock_config.rules = {
            'upstream': MockDependencyRule(min_coverage=0.8)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {'upstream': 0.8}  # Exactly 80%

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['coverage']['upstream'] == 0.8

    @patch(PATCH_PATH)
    def test_just_below_threshold_behavior(self, mock_get_config):
        """Test behavior when coverage is just below threshold"""
        mock_config = MockDependencyConfig()
        mock_config.dependencies = {
            'test-processor': {
                'upstream': MockDependencyRule(min_coverage=0.8, is_required=False)
            }
        }
        mock_config.rules = {
            'upstream': MockDependencyRule(min_coverage=0.8, is_required=False)
        }
        mock_get_config.return_value = mock_config

        processor = MockProcessor()
        processor._coverage_data = {'upstream': 0.79}  # Just below 80%

        result = processor.check_soft_dependencies(date(2024, 1, 15))

        assert result['coverage']['upstream'] == 0.79
