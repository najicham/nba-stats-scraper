"""
Unit tests for the validation system.

Tests cover:
- Chain config loading and structures
- Chain validation logic
- Time awareness calculations
- Output formatting
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import pytz

# Import validation modules
import sys
import os
_current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_current_dir, '..', '..'))

from shared.validation.chain_config import (
    load_chain_configs,
    get_chain_configs,
    SourceConfig,
    ChainConfig,
    SourceValidation,
    ChainValidation,
    GCS_PATH_MAPPING,
)
from shared.validation.time_awareness import (
    get_time_context,
    TimeContext,
    PhaseExpectation,
)
from shared.validation.config import (
    QualityTier,
    QUALITY_TIERS,
    PHASE3_TABLES,
    PHASE4_TABLES,
)


class TestChainConfig:
    """Tests for chain_config.py"""

    def test_load_chain_configs(self):
        """Test that chain configs load successfully."""
        chains = get_chain_configs()

        assert chains is not None
        assert len(chains) > 0

    def test_expected_chains_exist(self):
        """Test that expected chains are defined."""
        chains = get_chain_configs()
        expected_chains = [
            'player_boxscores',
            'team_boxscores',
            'player_props',
            'game_schedule',
            'game_lines',
            'shot_zones',
            'injury_reports',
        ]

        for chain_name in expected_chains:
            assert chain_name in chains, f"Missing chain: {chain_name}"

    def test_chain_has_sources(self):
        """Test that all chains have sources defined."""
        chains = get_chain_configs()

        for chain_name, chain in chains.items():
            assert len(chain.sources) > 0, f"Chain {chain_name} has no sources"

    def test_chain_has_primary_source(self):
        """Test that each chain has at least one primary source."""
        chains = get_chain_configs()

        for chain_name, chain in chains.items():
            primary_found = any(src.is_primary for src in chain.sources)
            assert primary_found, f"Chain {chain_name} has no primary source"

    def test_chain_severities(self):
        """Test that chain severities are valid."""
        chains = get_chain_configs()
        valid_severities = {'critical', 'warning', 'info'}

        for chain_name, chain in chains.items():
            assert chain.severity in valid_severities, f"Invalid severity for {chain_name}"

    def test_source_quality_tiers(self):
        """Test that source quality tiers are valid."""
        chains = get_chain_configs()
        valid_tiers = {'gold', 'silver', 'bronze'}

        for chain_name, chain in chains.items():
            for src in chain.sources:
                assert src.quality_tier in valid_tiers, f"Invalid tier for {src.name}"

    def test_gcs_path_mapping_exists(self):
        """Test that GCS path mapping has entries for expected sources."""
        expected_sources = [
            'nbac_gamebook_player_stats',
            'bdl_player_boxscores',
            'nbac_team_boxscore',
        ]

        for source in expected_sources:
            assert source in GCS_PATH_MAPPING, f"Missing GCS path for {source}"

    def test_source_config_dataclass(self):
        """Test SourceConfig dataclass creation."""
        source = SourceConfig(
            name='test_source',
            description='Test source',
            table='test_table',
            dataset='test_dataset',
            is_primary=True,
            is_virtual=False,
            quality_tier='gold',
            quality_score=100,
        )

        assert source.name == 'test_source'
        assert source.is_primary is True
        assert source.quality_tier == 'gold'

    def test_chain_config_dataclass(self):
        """Test ChainConfig dataclass creation."""
        source = SourceConfig(
            name='test_source',
            description='Test source',
            table='test_table',
            dataset='test_dataset',
            is_primary=True,
            is_virtual=False,
            quality_tier='gold',
            quality_score=100,
        )

        chain = ChainConfig(
            name='test_chain',
            description='Test chain',
            severity='critical',
            sources=[source],
            on_all_fail_action='skip',
            on_all_fail_message='Test message',
        )

        assert chain.name == 'test_chain'
        assert chain.severity == 'critical'
        assert len(chain.sources) == 1

    def test_source_validation_dataclass(self):
        """Test SourceValidation dataclass."""
        source = SourceConfig(
            name='test_source',
            description='Test',
            table='test',
            dataset='test',
            is_primary=True,
            is_virtual=False,
            quality_tier='gold',
            quality_score=100,
        )

        sv = SourceValidation(
            source=source,
            gcs_file_count=5,
            bq_record_count=100,
            status='primary',
        )

        assert sv.gcs_file_count == 5
        assert sv.bq_record_count == 100
        assert sv.status == 'primary'

    def test_chain_validation_dataclass(self):
        """Test ChainValidation dataclass."""
        source = SourceConfig(
            name='test_source',
            description='Test',
            table='test',
            dataset='test',
            is_primary=True,
            is_virtual=False,
            quality_tier='gold',
            quality_score=100,
        )

        chain = ChainConfig(
            name='test_chain',
            description='Test',
            severity='critical',
            sources=[source],
            on_all_fail_action='skip',
            on_all_fail_message='Test',
        )

        cv = ChainValidation(
            chain=chain,
            sources=[],
            status='complete',
            primary_available=True,
            fallback_used=False,
        )

        assert cv.status == 'complete'
        assert cv.primary_available is True


class TestTimeAwareness:
    """Tests for time_awareness.py"""

    def test_historical_date_context(self):
        """Test time context for a historical date."""
        historical_date = date(2021, 10, 19)
        ctx = get_time_context(historical_date)

        assert ctx.is_historical is True
        assert ctx.is_today is False
        assert ctx.is_yesterday is False

    def test_expectations_for_historical_date(self):
        """Test phase expectations for historical date."""
        historical_date = date(2021, 10, 19)
        ctx = get_time_context(historical_date)

        # Historical dates should expect all phases complete
        for phase in [2, 3, 4, 5]:
            if phase in ctx.phase_expectations:
                exp = ctx.phase_expectations[phase]
                assert exp.expected_status == 'complete'


class TestQualityConfig:
    """Tests for config.py quality settings"""

    def test_quality_tiers_defined(self):
        """Test that all quality tiers are defined."""
        expected_tiers = ['gold', 'silver', 'bronze', 'poor', 'unusable']

        for tier in expected_tiers:
            assert tier in QUALITY_TIERS

    def test_quality_tier_scores(self):
        """Test that quality tier scores are properly ordered."""
        # Gold should have highest min score
        assert QUALITY_TIERS['gold']['min_score'] > QUALITY_TIERS['silver']['min_score']
        assert QUALITY_TIERS['silver']['min_score'] > QUALITY_TIERS['bronze']['min_score']
        assert QUALITY_TIERS['bronze']['min_score'] > QUALITY_TIERS['poor']['min_score']
        assert QUALITY_TIERS['poor']['min_score'] > QUALITY_TIERS['unusable']['min_score']

    def test_production_ready_flags(self):
        """Test production ready flags are set correctly."""
        # Gold, silver, bronze should be production ready
        assert QUALITY_TIERS['gold']['production_ready'] is True
        assert QUALITY_TIERS['silver']['production_ready'] is True
        assert QUALITY_TIERS['bronze']['production_ready'] is True

        # Poor and unusable should not be production ready
        assert QUALITY_TIERS['poor']['production_ready'] is False
        assert QUALITY_TIERS['unusable']['production_ready'] is False


class TestPhase3Config:
    """Tests for Phase 3 table configuration"""

    def test_phase3_tables_defined(self):
        """Test that expected Phase 3 tables are defined."""
        expected_tables = [
            'player_game_summary',
            'team_defense_game_summary',
            'team_offense_game_summary',
            'upcoming_player_game_context',
            'upcoming_team_game_context',
        ]

        for table in expected_tables:
            assert table in PHASE3_TABLES

    def test_phase3_expected_scopes(self):
        """Test that expected scopes are valid."""
        valid_scopes = ['all_rostered', 'active_only', 'teams']

        for table_name, table in PHASE3_TABLES.items():
            assert table.expected_scope in valid_scopes, f"Invalid scope for {table_name}"


class TestPhase4Config:
    """Tests for Phase 4 table configuration"""

    def test_phase4_tables_defined(self):
        """Test that expected Phase 4 tables are defined."""
        expected_tables = [
            'team_defense_zone_analysis',
            'player_shot_zone_analysis',
            'player_composite_factors',
            'player_daily_cache',
            'ml_feature_store_v2',
        ]

        for table in expected_tables:
            assert table in PHASE4_TABLES

    def test_phase4_skips_bootstrap(self):
        """Test that Phase 4 tables skip bootstrap by default."""
        for table_name, table in PHASE4_TABLES.items():
            assert table.skips_bootstrap is True, f"{table_name} should skip bootstrap"


class TestOutputFormatting:
    """Tests for terminal.py output formatting"""

    def test_quality_tier_colors_defined(self):
        """Test that quality tier colors are defined."""
        from shared.validation.output.terminal import QUALITY_TIER_COLORS

        expected_tiers = ['gold', 'silver', 'bronze']

        for tier in expected_tiers:
            assert tier in QUALITY_TIER_COLORS, f"Missing color for {tier}"

    def test_quality_tier_colors_are_ansi(self):
        """Test that quality tier colors are ANSI escape codes."""
        from shared.validation.output.terminal import QUALITY_TIER_COLORS

        for tier, color in QUALITY_TIER_COLORS.items():
            assert color.startswith('\033['), f"Color for {tier} is not ANSI"

    def test_source_status_symbols_defined(self):
        """Test that source status symbols are defined."""
        from shared.validation.output.terminal import SOURCE_STATUS_SYMBOLS

        expected_statuses = ['primary', 'fallback', 'available', 'missing', 'virtual']

        for status in expected_statuses:
            assert status in SOURCE_STATUS_SYMBOLS


class TestChainValidationLogic:
    """Tests for chain validation logic in chain_validator.py"""

    def test_impact_message_for_missing_chain(self):
        """Test that impact message is generated for missing chains."""
        from shared.validation.validators.chain_validator import _build_impact_message

        chain = ChainConfig(
            name='test_chain',
            description='Test',
            severity='critical',
            sources=[],
            on_all_fail_action='skip',
            on_all_fail_message='No data available',
            quality_impact=-20,
        )

        message = _build_impact_message(
            chain_config=chain,
            chain_status='missing',
            fallback_used=False,
            first_available_source=None,
        )

        assert message is not None
        assert 'No data available' in message
        assert '-20' in message

    def test_impact_message_for_fallback_used(self):
        """Test that impact message is generated when fallback is used."""
        from shared.validation.validators.chain_validator import _build_impact_message

        source = SourceConfig(
            name='fallback_source',
            description='Fallback',
            table='test',
            dataset='test',
            is_primary=False,
            is_virtual=False,
            quality_tier='silver',
            quality_score=85,
        )

        chain = ChainConfig(
            name='test_chain',
            description='Test',
            severity='critical',
            sources=[source],
            on_all_fail_action='skip',
            on_all_fail_message='Test',
        )

        message = _build_impact_message(
            chain_config=chain,
            chain_status='complete',
            fallback_used=True,
            first_available_source=source,
        )

        assert message is not None
        assert 'fallback_source' in message
        assert 'silver' in message

    def test_impact_message_none_for_complete_primary(self):
        """Test that no impact message when primary is available."""
        from shared.validation.validators.chain_validator import _build_impact_message

        source = SourceConfig(
            name='primary_source',
            description='Primary',
            table='test',
            dataset='test',
            is_primary=True,
            is_virtual=False,
            quality_tier='gold',
            quality_score=100,
        )

        chain = ChainConfig(
            name='test_chain',
            description='Test',
            severity='critical',
            sources=[source],
            on_all_fail_action='skip',
            on_all_fail_message='Test',
        )

        message = _build_impact_message(
            chain_config=chain,
            chain_status='complete',
            fallback_used=False,
            first_available_source=source,
        )

        assert message is None

    def test_get_date_column_defaults_to_game_date(self):
        """Test that default date column is game_date."""
        from shared.validation.validators.chain_validator import _get_date_column

        assert _get_date_column('some_table') == 'game_date'
        assert _get_date_column('nbac_gamebook_player_stats') == 'game_date'

    def test_get_date_column_special_cases(self):
        """Test special date column mappings."""
        from shared.validation.validators.chain_validator import _get_date_column

        assert _get_date_column('player_shot_zone_analysis') == 'analysis_date'
        assert _get_date_column('team_defense_zone_analysis') == 'analysis_date'
        assert _get_date_column('player_daily_cache') == 'cache_date'
        assert _get_date_column('bdl_injuries') == 'scrape_date'

    def test_chain_summary_calculation(self):
        """Test chain summary helper."""
        from shared.validation.validators.chain_validator import get_chain_summary

        source = SourceConfig(
            name='test',
            description='Test',
            table='test',
            dataset='test',
            is_primary=True,
            is_virtual=False,
            quality_tier='gold',
            quality_score=100,
        )

        chain = ChainConfig(
            name='test',
            description='Test',
            severity='critical',
            sources=[source],
            on_all_fail_action='skip',
            on_all_fail_message='Test',
        )

        chain_validations = {
            'chain1': ChainValidation(chain=chain, status='complete'),
            'chain2': ChainValidation(chain=chain, status='partial'),
            'chain3': ChainValidation(chain=chain, status='missing'),
            'chain4': ChainValidation(chain=chain, status='complete'),
        }

        summary = get_chain_summary(chain_validations)

        assert summary['complete'] == 2
        assert summary['partial'] == 1
        assert summary['missing'] == 1


class TestGCSPathMapping:
    """Tests for GCS path mapping completeness."""

    def test_espn_boxscores_has_path(self):
        """Test that espn_boxscores has a GCS path mapping."""
        assert 'espn_boxscores' in GCS_PATH_MAPPING
        assert GCS_PATH_MAPPING['espn_boxscores'] == 'espn/boxscores'

    def test_all_chain_sources_have_paths_or_are_virtual(self):
        """Test that non-virtual sources in chains have GCS paths or are roster tables."""
        chains = get_chain_configs()
        missing_paths = []

        # Sources that don't need GCS paths (roster tables are current-state, not date-partitioned)
        roster_sources = {'nbac_player_list_current', 'bdl_active_players_current', 'br_rosters_current'}

        for chain_name, chain in chains.items():
            for source in chain.sources:
                if source.is_virtual:
                    continue
                if source.name in roster_sources:
                    continue
                if source.name not in GCS_PATH_MAPPING:
                    missing_paths.append(f"{chain_name}/{source.name}")

        assert len(missing_paths) == 0, f"Missing GCS paths for: {missing_paths}"


class TestJSONOutput:
    """Tests for json_output.py"""

    def test_format_chain_validation_json(self):
        """Test chain validation JSON formatting."""
        from shared.validation.output.json_output import format_chain_validation_json
        import json

        # Create mock chain validation
        source = SourceConfig(
            name='test_source',
            description='Test',
            table='test_table',
            dataset='test_dataset',
            is_primary=True,
            is_virtual=False,
            quality_tier='gold',
            quality_score=100,
        )

        chain = ChainConfig(
            name='test_chain',
            description='Test chain',
            severity='critical',
            sources=[source],
            on_all_fail_action='skip',
            on_all_fail_message='Test',
        )

        source_val = SourceValidation(
            source=source,
            gcs_file_count=5,
            bq_record_count=100,
            status='primary',
        )

        chain_val = ChainValidation(
            chain=chain,
            sources=[source_val],
            status='complete',
            primary_available=True,
            fallback_used=False,
        )

        chain_validations = {'test_chain': chain_val}

        result = format_chain_validation_json(chain_validations, pretty=False)
        parsed = json.loads(result)

        assert 'chains' in parsed
        assert 'test_chain' in parsed['chains']
        assert parsed['chains']['test_chain']['status'] == 'complete'
        assert parsed['summary']['complete'] == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
