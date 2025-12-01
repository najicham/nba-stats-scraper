"""
Tests for the Quality Column System

These tests ensure consistency across:
- YAML config and Python constants
- Quality tier implementations
- Production ready logic
- Column builders

Run with: pytest tests/test_quality_system.py -v
"""

import pytest
from typing import List


class TestQualityTierConsistency:
    """Test that YAML config and Python constants are consistent."""

    def test_tier_thresholds_match(self):
        """Ensure YAML config tier thresholds match Python constants."""
        from shared.config.data_sources import DataSourceConfig
        from shared.config.source_coverage import QUALITY_THRESHOLDS

        config = DataSourceConfig()

        # Check gold threshold
        gold_tier = config.get_tier('gold')
        assert gold_tier.score_min == QUALITY_THRESHOLDS['gold_min'], \
            f"Gold min mismatch: YAML={gold_tier.score_min}, Python={QUALITY_THRESHOLDS['gold_min']}"

        # Check silver threshold
        silver_tier = config.get_tier('silver')
        assert silver_tier.score_min == QUALITY_THRESHOLDS['silver_min'], \
            f"Silver min mismatch: YAML={silver_tier.score_min}, Python={QUALITY_THRESHOLDS['silver_min']}"

        # Check bronze threshold
        bronze_tier = config.get_tier('bronze')
        assert bronze_tier.score_min == QUALITY_THRESHOLDS['bronze_min'], \
            f"Bronze min mismatch: YAML={bronze_tier.score_min}, Python={QUALITY_THRESHOLDS['bronze_min']}"

        # Check poor threshold
        poor_tier = config.get_tier('poor')
        assert poor_tier.score_min == QUALITY_THRESHOLDS['poor_min'], \
            f"Poor min mismatch: YAML={poor_tier.score_min}, Python={QUALITY_THRESHOLDS['poor_min']}"

    def test_tier_score_conversion_consistent(self):
        """Ensure both get_tier_from_score implementations agree."""
        from shared.config.data_sources import DataSourceConfig
        from shared.config.source_coverage import get_tier_from_score

        config = DataSourceConfig()

        # Test scores at various points
        test_scores = [100, 95, 94, 75, 74, 50, 49, 25, 24, 0]

        for score in test_scores:
            yaml_tier = config.get_tier_from_score(score)
            python_tier = get_tier_from_score(score).value
            assert yaml_tier == python_tier, \
                f"Tier mismatch at score {score}: YAML={yaml_tier}, Python={python_tier}"

    def test_confidence_ceilings_match(self):
        """Ensure confidence ceilings are consistent."""
        from shared.config.data_sources import DataSourceConfig
        from shared.config.source_coverage import QUALITY_CONFIDENCE_CEILING

        config = DataSourceConfig()

        for tier_name in ['gold', 'silver', 'bronze', 'poor', 'unusable']:
            yaml_ceiling = config.get_tier(tier_name).confidence_ceiling
            python_ceiling = QUALITY_CONFIDENCE_CEILING[tier_name]
            assert yaml_ceiling == python_ceiling, \
                f"Confidence ceiling mismatch for {tier_name}: YAML={yaml_ceiling}, Python={python_ceiling}"


class TestQualityColumnBuilders:
    """Test the quality column builder functions."""

    def test_build_standard_quality_columns(self):
        """Test standard quality column output."""
        from shared.processors.patterns.quality_columns import build_standard_quality_columns

        result = build_standard_quality_columns(
            tier='silver',
            score=85.0,
            issues=['backup_source_used'],
            sources=['bdl_player_boxscores'],
        )

        assert result['quality_tier'] == 'silver'
        assert result['quality_score'] == 85.0
        assert result['quality_issues'] == ['backup_source_used']
        assert result['data_sources'] == ['bdl_player_boxscores']
        assert result['is_production_ready'] == True  # silver, 85, no blockers

    def test_build_standard_quality_columns_defaults(self):
        """Test defaults for optional parameters."""
        from shared.processors.patterns.quality_columns import build_standard_quality_columns

        result = build_standard_quality_columns(
            tier='gold',
            score=100.0,
        )

        assert result['quality_tier'] == 'gold'
        assert result['quality_score'] == 100.0
        assert result['quality_issues'] == []
        assert result['data_sources'] == []
        assert result['is_production_ready'] == True

    def test_build_quality_columns_with_legacy(self):
        """Test legacy column inclusion."""
        from shared.processors.patterns.quality_columns import build_quality_columns_with_legacy

        result = build_quality_columns_with_legacy(
            tier='bronze',
            score=60.0,
            issues=['thin_sample'],
            sources=['reconstructed_team_from_players'],
        )

        # Standard columns
        assert result['quality_tier'] == 'bronze'
        assert result['quality_score'] == 60.0
        assert result['quality_issues'] == ['thin_sample']
        assert result['data_sources'] == ['reconstructed_team_from_players']
        assert result['is_production_ready'] == True

        # Legacy columns
        assert result['data_quality_tier'] == 'bronze'
        assert result['data_quality_issues'] == ['thin_sample']

    def test_build_completeness_columns(self):
        """Test completeness column output."""
        from shared.processors.patterns.quality_columns import build_completeness_columns

        result = build_completeness_columns(expected=10, actual=7)

        assert result['expected_games_count'] == 10
        assert result['actual_games_count'] == 7
        assert result['completeness_percentage'] == 70.0
        assert result['missing_games_count'] == 3

    def test_build_completeness_columns_zero_expected(self):
        """Test completeness with zero expected (edge case)."""
        from shared.processors.patterns.quality_columns import build_completeness_columns

        result = build_completeness_columns(expected=0, actual=0)

        assert result['expected_games_count'] == 0
        assert result['actual_games_count'] == 0
        assert result['completeness_percentage'] == 0.0
        assert result['missing_games_count'] == 0


class TestProductionReadyLogic:
    """Test the production ready determination logic."""

    def test_production_ready_gold_tier(self):
        """Gold tier with high score is production ready."""
        from shared.processors.patterns.quality_columns import determine_production_ready

        assert determine_production_ready('gold', 100.0, []) == True
        assert determine_production_ready('gold', 95.0, []) == True
        assert determine_production_ready('gold', 95.0, ['backup_source_used']) == True

    def test_production_ready_silver_tier(self):
        """Silver tier with decent score is production ready."""
        from shared.processors.patterns.quality_columns import determine_production_ready

        assert determine_production_ready('silver', 85.0, []) == True
        assert determine_production_ready('silver', 75.0, []) == True
        assert determine_production_ready('silver', 50.0, []) == True

    def test_production_ready_bronze_tier(self):
        """Bronze tier with >= 50 score is production ready."""
        from shared.processors.patterns.quality_columns import determine_production_ready

        assert determine_production_ready('bronze', 60.0, []) == True
        assert determine_production_ready('bronze', 50.0, []) == True

    def test_not_production_ready_poor_tier(self):
        """Poor tier is NOT production ready."""
        from shared.processors.patterns.quality_columns import determine_production_ready

        assert determine_production_ready('poor', 40.0, []) == False
        assert determine_production_ready('poor', 25.0, []) == False

    def test_not_production_ready_unusable_tier(self):
        """Unusable tier is NOT production ready."""
        from shared.processors.patterns.quality_columns import determine_production_ready

        assert determine_production_ready('unusable', 10.0, []) == False
        assert determine_production_ready('unusable', 0.0, []) == False

    def test_not_production_ready_low_score(self):
        """Score below 50 is NOT production ready even with good tier."""
        from shared.processors.patterns.quality_columns import determine_production_ready

        assert determine_production_ready('silver', 49.0, []) == False
        assert determine_production_ready('bronze', 40.0, []) == False

    def test_not_production_ready_blocking_issues(self):
        """Blocking issues make data NOT production ready."""
        from shared.processors.patterns.quality_columns import determine_production_ready

        # all_sources_failed blocks
        assert determine_production_ready('silver', 85.0, ['all_sources_failed']) == False

        # missing_required blocks
        assert determine_production_ready('gold', 95.0, ['missing_required']) == False

        # placeholder_created blocks
        assert determine_production_ready('silver', 80.0, ['placeholder_created']) == False

    def test_non_blocking_issues_allowed(self):
        """Non-blocking issues do NOT block production readiness."""
        from shared.processors.patterns.quality_columns import determine_production_ready

        # These issues are warnings, not blockers
        assert determine_production_ready('silver', 85.0, ['backup_source_used']) == True
        assert determine_production_ready('silver', 80.0, ['reconstructed']) == True
        assert determine_production_ready('bronze', 60.0, ['thin_sample:3/10']) == True
        assert determine_production_ready('silver', 75.0, ['stale_data']) == True


class TestFallbackChainConfig:
    """Test fallback chain configuration."""

    def test_all_chain_sources_exist(self):
        """Verify all sources referenced in chains actually exist."""
        from shared.config.data_sources import DataSourceConfig

        config = DataSourceConfig()
        errors = config.validate()

        assert len(errors) == 0, f"Config validation errors: {errors}"

    def test_fallback_chain_structure(self):
        """Test that fallback chains have expected structure."""
        from shared.config.data_sources import DataSourceConfig

        config = DataSourceConfig()

        # Test team_boxscores chain
        chain = config.get_fallback_chain('team_boxscores')
        assert len(chain.sources) >= 2, "team_boxscores should have at least 2 fallback sources"
        assert chain.on_all_fail_action in ['skip', 'placeholder', 'fail', 'continue_without']

        # Test player_boxscores chain
        chain = config.get_fallback_chain('player_boxscores')
        assert len(chain.sources) >= 2
        assert 'nbac_gamebook_player_stats' in chain.sources

    def test_critical_chains_exist(self):
        """Ensure critical fallback chains are defined."""
        from shared.config.data_sources import DataSourceConfig

        config = DataSourceConfig()

        required_chains = [
            'player_boxscores',
            'team_boxscores',
            'player_props',
            'game_schedule',
        ]

        for chain_name in required_chains:
            chain = config.get_fallback_chain_safe(chain_name)
            assert chain is not None, f"Missing critical fallback chain: {chain_name}"


class TestIssueFormatting:
    """Test quality issue formatting helpers."""

    def test_format_issue_with_detail(self):
        """Test issue formatting with detail."""
        from shared.processors.patterns.quality_columns import format_issue_with_detail

        assert format_issue_with_detail('thin_sample', '3/10') == 'thin_sample:3/10'
        assert format_issue_with_detail('high_null_rate', '50%') == 'high_null_rate:50%'

    def test_format_issue_without_detail(self):
        """Test issue formatting without detail."""
        from shared.processors.patterns.quality_columns import format_issue_with_detail

        assert format_issue_with_detail('backup_source_used', None) == 'backup_source_used'
        assert format_issue_with_detail('reconstructed', '') == 'reconstructed'

    def test_issue_constants_defined(self):
        """Test that standard issue constants are defined."""
        from shared.processors.patterns.quality_columns import (
            ISSUE_BACKUP_SOURCE_USED,
            ISSUE_RECONSTRUCTED,
            ISSUE_ALL_SOURCES_FAILED,
            ISSUE_PLACEHOLDER_CREATED,
            ISSUE_MISSING_REQUIRED,
        )

        assert ISSUE_BACKUP_SOURCE_USED == 'backup_source_used'
        assert ISSUE_RECONSTRUCTED == 'reconstructed'
        assert ISSUE_ALL_SOURCES_FAILED == 'all_sources_failed'
        assert ISSUE_PLACEHOLDER_CREATED == 'placeholder_created'
        assert ISSUE_MISSING_REQUIRED == 'missing_required'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
