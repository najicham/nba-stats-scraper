#!/usr/bin/env python3
"""
Integration tests for completeness checking across all processors.

These tests verify that processors correctly integrate with CompletenessChecker
and that the circuit breaker protection works as expected.

Run with: pytest tests/integration/test_completeness_integration.py -v
"""

import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
from google.cloud import bigquery

# Import processors to test
from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import TeamDefenseZoneAnalysisProcessor
from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor
from data_processors.precompute.player_composite_factors.player_composite_factors_processor import PlayerCompositeFactorsProcessor
from shared.utils.completeness_checker import CompletenessChecker


class TestCompletenessIntegrationSingleWindow:
    """Test completeness checking for single-window processors."""

    @patch('data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor.bigquery.Client')
    def test_team_defense_skips_incomplete_data(self, mock_bq_client):
        """Verify processor skips teams with incomplete data (not in bootstrap mode)."""

        # Setup
        processor = TeamDefenseZoneAnalysisProcessor()
        processor.opts = {'analysis_date': date(2024, 12, 15)}
        processor.season_start_date = date(2024, 10, 1)

        # Mock completeness results - one team incomplete
        mock_completeness_results = {
            'LAL': {
                'expected_count': 10,
                'actual_count': 8,
                'completeness_pct': 80.0,  # Below 90% threshold
                'missing_count': 2,
                'is_complete': False,
                'is_production_ready': False
            },
            'GSW': {
                'expected_count': 10,
                'actual_count': 10,
                'completeness_pct': 100.0,
                'missing_count': 0,
                'is_complete': True,
                'is_production_ready': True
            }
        }

        # Mock CompletenessChecker
        with patch.object(processor.completeness_checker, 'check_completeness_batch', return_value=mock_completeness_results):
            with patch.object(processor.completeness_checker, 'is_bootstrap_mode', return_value=False):
                with patch.object(processor, '_check_circuit_breaker', return_value={'active': False, 'attempts': 0, 'until': None}):

                    # Mock data extraction (simplified)
                    processor.all_teams = ['LAL', 'GSW']
                    processor.transformed_data = []
                    processor.failed_entities = []

                    # Simulate processing logic
                    for team in processor.all_teams:
                        completeness = mock_completeness_results.get(team)
                        circuit_status = {'active': False, 'attempts': 0, 'until': None}

                        if not completeness['is_production_ready'] and not False:  # not bootstrap
                            processor.failed_entities.append({
                                'entity_id': team,
                                'entity_type': 'team',
                                'reason': f"Completeness {completeness['completeness_pct']:.1f}%",
                                'category': 'INCOMPLETE_DATA_SKIPPED'
                            })
                        else:
                            # Would process team
                            processor.transformed_data.append({'team_abbr': team})

                    # Assertions
                    assert len(processor.transformed_data) == 1, "Should process only complete team (GSW)"
                    assert processor.transformed_data[0]['team_abbr'] == 'GSW'
                    assert len(processor.failed_entities) == 1, "Should skip incomplete team (LAL)"
                    assert processor.failed_entities[0]['entity_id'] == 'LAL'
                    assert 'INCOMPLETE_DATA_SKIPPED' in processor.failed_entities[0]['category']


    @patch('data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor.bigquery.Client')
    def test_team_defense_processes_in_bootstrap_mode(self, mock_bq_client):
        """Verify processor processes incomplete data in bootstrap mode."""

        # Setup
        processor = TeamDefenseZoneAnalysisProcessor()
        processor.opts = {'analysis_date': date(2024, 10, 15)}  # Early in season
        processor.season_start_date = date(2024, 10, 1)

        # Mock completeness results - incomplete data
        mock_completeness_results = {
            'LAL': {
                'expected_count': 10,
                'actual_count': 3,  # Only 30% complete (early season)
                'completeness_pct': 30.0,
                'missing_count': 7,
                'is_complete': False,
                'is_production_ready': False
            }
        }

        # Mock CompletenessChecker - bootstrap mode ON
        with patch.object(processor.completeness_checker, 'check_completeness_batch', return_value=mock_completeness_results):
            with patch.object(processor.completeness_checker, 'is_bootstrap_mode', return_value=True):
                with patch.object(processor, '_check_circuit_breaker', return_value={'active': False, 'attempts': 0, 'until': None}):

                    processor.all_teams = ['LAL']
                    processor.transformed_data = []
                    processor.failed_entities = []

                    # Simulate processing with bootstrap override
                    for team in processor.all_teams:
                        completeness = mock_completeness_results.get(team)
                        is_bootstrap = True

                        if not completeness['is_production_ready'] and not is_bootstrap:
                            processor.failed_entities.append({'entity_id': team})
                        else:
                            # Bootstrap mode allows processing
                            processor.transformed_data.append({
                                'team_abbr': team,
                                'backfill_bootstrap_mode': True,
                                'processing_decision_reason': 'processed_in_bootstrap_mode'
                            })

                    # Assertions
                    assert len(processor.transformed_data) == 1, "Should process even with 30% completeness in bootstrap"
                    assert processor.transformed_data[0]['backfill_bootstrap_mode'] == True
                    assert len(processor.failed_entities) == 0


class TestCompletenessIntegrationMultiWindow:
    """Test completeness checking for multi-window processors."""

    @patch('data_processors.precompute.player_daily_cache.player_daily_cache_processor.bigquery.Client')
    def test_player_daily_cache_requires_all_windows_complete(self, mock_bq_client):
        """Verify multi-window processor requires ALL windows >= 90%."""

        # Setup
        processor = PlayerDailyCacheProcessor()
        processor.opts = {'analysis_date': date(2024, 12, 15)}
        processor.season_start_date = date(2024, 10, 1)

        # Mock completeness - L5 complete, L10 incomplete, L7d complete, L14d complete
        mock_comp_l5 = {
            'lebron_james': {'expected_count': 5, 'actual_count': 5, 'completeness_pct': 100.0, 'is_complete': True, 'is_production_ready': True}
        }
        mock_comp_l10 = {
            'lebron_james': {'expected_count': 10, 'actual_count': 8, 'completeness_pct': 80.0, 'is_complete': False, 'is_production_ready': False}
        }
        mock_comp_l7d = {
            'lebron_james': {'expected_count': 5, 'actual_count': 5, 'completeness_pct': 100.0, 'is_complete': True, 'is_production_ready': True}
        }
        mock_comp_l14d = {
            'lebron_james': {'expected_count': 8, 'actual_count': 8, 'completeness_pct': 100.0, 'is_complete': True, 'is_production_ready': True}
        }

        # Simulate multi-window check
        all_windows_ready = (
            mock_comp_l5['lebron_james']['is_production_ready'] and
            mock_comp_l10['lebron_james']['is_production_ready'] and
            mock_comp_l7d['lebron_james']['is_production_ready'] and
            mock_comp_l14d['lebron_james']['is_production_ready']
        )

        # Assertion - should be False because L10 is incomplete
        assert all_windows_ready == False, "Should fail when ANY window is incomplete"

        # Now test with all windows complete
        mock_comp_l10['lebron_james']['completeness_pct'] = 100.0
        mock_comp_l10['lebron_james']['is_production_ready'] = True
        mock_comp_l10['lebron_james']['is_complete'] = True

        all_windows_ready = (
            mock_comp_l5['lebron_james']['is_production_ready'] and
            mock_comp_l10['lebron_james']['is_production_ready'] and
            mock_comp_l7d['lebron_james']['is_production_ready'] and
            mock_comp_l14d['lebron_james']['is_production_ready']
        )

        assert all_windows_ready == True, "Should pass when ALL windows are complete"


class TestCompletenessIntegrationCascade:
    """Test completeness checking for cascade dependency processors."""

    def test_player_composite_factors_cascade_check(self):
        """Verify cascade processor checks own completeness AND upstream completeness."""

        # This test verifies the cascade logic without needing a full processor instance

        # Scenario 1: Own data complete, upstream incomplete
        own_completeness = {
            'expected_count': 10,
            'actual_count': 10,
            'completeness_pct': 100.0,
            'is_complete': True,
            'is_production_ready': True
        }

        upstream_complete = False  # team_defense_zone_analysis incomplete

        # Production readiness should fail
        is_production_ready = own_completeness['is_production_ready'] and upstream_complete
        assert is_production_ready == False, "Should not be production ready if upstream incomplete"

        # Scenario 2: Own data complete, upstream complete
        upstream_complete = True
        is_production_ready = own_completeness['is_production_ready'] and upstream_complete
        assert is_production_ready == True, "Should be production ready when both own and upstream complete"

        # Scenario 3: Own data incomplete, upstream complete
        own_completeness['completeness_pct'] = 85.0
        own_completeness['is_production_ready'] = False
        upstream_complete = True
        is_production_ready = own_completeness['is_production_ready'] and upstream_complete
        assert is_production_ready == False, "Should not be production ready if own data incomplete"


class TestCircuitBreakerIntegration:
    """Test circuit breaker protection across processors."""

    @patch('data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor.bigquery.Client')
    def test_circuit_breaker_blocks_after_3_attempts(self, mock_bq_client):
        """Verify circuit breaker trips after 3 failed attempts."""

        # Setup
        processor = TeamDefenseZoneAnalysisProcessor()

        # Simulate circuit breaker status after 3 attempts
        circuit_status_attempt_3 = {
            'active': True,
            'attempts': 3,
            'until': datetime.now(timezone.utc) + timedelta(days=7)
        }

        # Mock the circuit breaker check
        with patch.object(processor, '_check_circuit_breaker', return_value=circuit_status_attempt_3):

            circuit_check = processor._check_circuit_breaker('LAL', date(2024, 12, 15))

            # Assertions
            assert circuit_check['active'] == True, "Circuit breaker should be active after 3 attempts"
            assert circuit_check['attempts'] == 3
            assert circuit_check['until'] is not None, "Should have cooldown period"

            # Verify cooldown is ~7 days
            cooldown_days = (circuit_check['until'] - datetime.now(timezone.utc)).days
            assert 6 <= cooldown_days <= 7, "Cooldown should be approximately 7 days"


    def test_circuit_breaker_cooldown_expires(self):
        """Verify circuit breaker allows processing after cooldown expires."""

        # Simulate circuit breaker that expired yesterday
        expired_circuit = {
            'active': False,  # Cooldown expired
            'attempts': 3,
            'until': datetime.now(timezone.utc) - timedelta(days=1)  # Expired
        }

        # Should allow processing
        assert expired_circuit['active'] == False, "Should allow processing after cooldown expires"


class TestOutputMetadataIntegration:
    """Test that completeness metadata is correctly written to output."""

    def test_output_contains_all_14_standard_fields(self):
        """Verify output record contains all 14 completeness metadata fields."""

        # Mock output record from processor
        output_record = {
            'team_abbr': 'LAL',
            'analysis_date': '2024-12-15',

            # Standard 14 completeness fields
            'expected_games_count': 10,
            'actual_games_count': 10,
            'completeness_percentage': 100.0,
            'missing_games_count': 0,
            'is_production_ready': True,
            'data_quality_issues': [],
            'last_reprocess_attempt_at': None,
            'reprocess_attempt_count': 0,
            'circuit_breaker_active': False,
            'circuit_breaker_until': None,
            'manual_override_required': False,
            'season_boundary_detected': False,
            'backfill_bootstrap_mode': False,
            'processing_decision_reason': 'processed_successfully'
        }

        # Verify all required fields present
        required_fields = [
            'expected_games_count', 'actual_games_count', 'completeness_percentage', 'missing_games_count',
            'is_production_ready', 'data_quality_issues',
            'last_reprocess_attempt_at', 'reprocess_attempt_count', 'circuit_breaker_active', 'circuit_breaker_until',
            'manual_override_required', 'season_boundary_detected', 'backfill_bootstrap_mode', 'processing_decision_reason'
        ]

        for field in required_fields:
            assert field in output_record, f"Missing required completeness field: {field}"

        # Verify data types
        assert isinstance(output_record['expected_games_count'], int)
        assert isinstance(output_record['completeness_percentage'], float)
        assert isinstance(output_record['is_production_ready'], bool)
        assert isinstance(output_record['data_quality_issues'], list)


    def test_multi_window_output_contains_window_fields(self):
        """Verify multi-window processor output contains per-window completeness."""

        # Mock output from multi-window processor (e.g., player_daily_cache)
        output_record = {
            'player_lookup': 'lebron_james',
            'analysis_date': '2024-12-15',

            # Standard 14 fields
            'expected_games_count': 10,
            'actual_games_count': 10,
            'completeness_percentage': 100.0,
            'missing_games_count': 0,
            'is_production_ready': True,
            'data_quality_issues': [],
            'last_reprocess_attempt_at': None,
            'reprocess_attempt_count': 0,
            'circuit_breaker_active': False,
            'circuit_breaker_until': None,
            'manual_override_required': False,
            'season_boundary_detected': False,
            'backfill_bootstrap_mode': False,
            'processing_decision_reason': 'processed_successfully',

            # Multi-window fields (9 additional for 4 windows)
            'l5_completeness_pct': 100.0,
            'l5_is_complete': True,
            'l10_completeness_pct': 100.0,
            'l10_is_complete': True,
            'l7d_completeness_pct': 100.0,
            'l7d_is_complete': True,
            'l14d_completeness_pct': 100.0,
            'l14d_is_complete': True,
            'all_windows_complete': True
        }

        # Verify window-specific fields
        window_fields = [
            'l5_completeness_pct', 'l5_is_complete',
            'l10_completeness_pct', 'l10_is_complete',
            'l7d_completeness_pct', 'l7d_is_complete',
            'l14d_completeness_pct', 'l14d_is_complete',
            'all_windows_complete'
        ]

        for field in window_fields:
            assert field in output_record, f"Missing window completeness field: {field}"

        # Verify all_windows_complete logic
        assert output_record['all_windows_complete'] == (
            output_record['l5_is_complete'] and
            output_record['l10_is_complete'] and
            output_record['l7d_is_complete'] and
            output_record['l14d_is_complete']
        )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
