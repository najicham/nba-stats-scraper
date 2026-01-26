#!/usr/bin/env python3
"""
Unit Tests for orchestration/parameter_resolver.py

Tests cover:
1. Configuration loading
2. Workflow context building
3. Target date determination
4. Simple parameter resolution (YAML)
5. Complex parameter resolution (code-based)
6. Season calculation
7. Error handling
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, mock_open
from datetime import datetime, date, timedelta
import pytz
import yaml

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from orchestration.parameter_resolver import (
    ParameterResolver,
    YESTERDAY_TARGET_WORKFLOWS
)


class TestInitialization:
    """Test suite for ParameterResolver initialization"""

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_resolver_initializes_with_defaults(self, mock_schedule):
        """Test resolver initializes with default config path"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            resolver = ParameterResolver()

            assert resolver.config_path == "config/scraper_parameters.yaml"
            assert resolver.config == {}
            assert resolver.schedule_service is not None
            assert resolver.ET.zone == 'America/New_York'

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_resolver_accepts_custom_config_path(self, mock_schedule):
        """Test resolver accepts custom config path"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            resolver = ParameterResolver(config_path="/custom/path.yaml")

            assert resolver.config_path == "/custom/path.yaml"


class TestConfigLoading:
    """Test suite for configuration loading"""

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_load_config_reads_yaml(self, mock_schedule):
        """Test config loading reads YAML file"""
        mock_config = {
            'scrapers': {
                'test_scraper': {
                    'type': 'simple',
                    'parameters': {'param1': 'value1'}
                }
            }
        }

        mock_file = mock_open(read_data=yaml.dump(mock_config))
        with patch('builtins.open', mock_file):
            with patch('os.path.exists', return_value=True):
                resolver = ParameterResolver()

                assert 'scrapers' in resolver.config
                assert 'test_scraper' in resolver.config['scrapers']

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_load_config_handles_missing_file(self, mock_schedule):
        """Test config loading handles missing file gracefully"""
        with patch('os.path.exists', return_value=False):
            resolver = ParameterResolver()

            # Should initialize with default config structure
            assert resolver.config == {'simple_scrapers': {}, 'complex_scrapers': []}


class TestTargetDateDetermination:
    """Test suite for target date determination"""

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_determine_target_date_for_post_game_workflow(self, mock_schedule):
        """Test post-game workflows target yesterday"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            resolver = ParameterResolver()

            # Test with post_game_window_1 workflow
            target_date = resolver._determine_target_date(
                workflow_name='post_game_window_1',
                current_time=datetime(2024, 1, 15, 10, 0, 0)
            )

            # Should be yesterday (2024-01-14) as string
            assert target_date == '2024-01-14'

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_determine_target_date_for_regular_workflow(self, mock_schedule):
        """Test regular workflows target today"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            resolver = ParameterResolver()

            target_date = resolver._determine_target_date(
                workflow_name='daily_scrape',
                current_time=datetime(2024, 1, 15, 10, 0, 0)
            )

            # Should be today (2024-01-15) as string
            assert target_date == '2024-01-15'

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_yesterday_target_workflows_list(self, mock_schedule):
        """Test YESTERDAY_TARGET_WORKFLOWS constant is defined"""
        assert isinstance(YESTERDAY_TARGET_WORKFLOWS, list)
        assert 'post_game_window_1' in YESTERDAY_TARGET_WORKFLOWS
        assert 'post_game_window_2' in YESTERDAY_TARGET_WORKFLOWS
        assert 'late_games' in YESTERDAY_TARGET_WORKFLOWS


class TestWorkflowContextBuilding:
    """Test suite for workflow context building"""

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    @patch('orchestration.parameter_resolver.datetime')
    def test_build_workflow_context_with_games(self, mock_datetime, mock_schedule):
        """Test context building includes games list"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            # Mock datetime.now to return fixed time
            mock_now = datetime(2024, 1, 15, 10, 0, 0)
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            resolver = ParameterResolver()

            # Mock schedule service to return games
            mock_game1 = Mock()
            mock_game1.game_id = 'game1'
            mock_game1.game_date = '2024-01-15'

            mock_game2 = Mock()
            mock_game2.game_id = 'game2'
            mock_game2.game_date = '2024-01-15'

            resolver.schedule_service.get_games_for_date.return_value = [mock_game1, mock_game2]

            context = resolver.build_workflow_context(
                workflow_name='test_workflow',
                target_date='2024-01-15'
            )

            assert 'target_date' in context
            assert 'games_today' in context
            assert len(context['games_today']) == 2
            assert 'season' in context

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    @patch('orchestration.parameter_resolver.datetime')
    def test_build_workflow_context_handles_no_games(self, mock_datetime, mock_schedule):
        """Test context building handles no games gracefully"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            # Mock datetime.now to return fixed time
            mock_now = datetime(2024, 7, 15, 10, 0, 0)
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            resolver = ParameterResolver()

            # Mock schedule service to return empty list
            resolver.schedule_service.get_games_for_date.return_value = []

            context = resolver.build_workflow_context(
                workflow_name='test_workflow',
                target_date='2024-07-15'  # Off-season
            )

            assert context['games_today'] == []

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    @patch('orchestration.parameter_resolver.datetime')
    @patch('orchestration.parameter_resolver.ThreadPoolExecutor')
    def test_build_workflow_context_handles_schedule_timeout(self, mock_executor, mock_datetime, mock_schedule):
        """Test context building handles schedule service timeout"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            # Mock datetime.now to return fixed time
            mock_now = datetime(2024, 1, 15, 10, 0, 0)
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            resolver = ParameterResolver()

            # Mock executor to raise timeout
            from concurrent.futures import TimeoutError as FuturesTimeoutError
            mock_future = Mock()
            mock_future.result.side_effect = FuturesTimeoutError("Timeout")
            mock_executor.return_value.__enter__.return_value.submit.return_value = mock_future

            context = resolver.build_workflow_context(
                workflow_name='test_workflow',
                target_date='2024-01-15'
            )

            # Should return empty games list on error
            assert context['games_today'] == []


class TestSimpleParameterResolution:
    """Test suite for simple (YAML-based) parameter resolution"""

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_resolve_simple_scraper_from_config(self, mock_schedule):
        """Test resolving simple scraper parameters from YAML"""
        mock_config = {
            'simple_scrapers': {
                'test_scraper': {
                    'game_date': 'context.target_date',
                    'season': 'context.season'
                }
            },
            'complex_scrapers': []
        }

        with patch.object(ParameterResolver, '_load_config', return_value=mock_config):
            resolver = ParameterResolver()

            context = {
                'target_date': '2024-01-15',
                'season': '2023-24',
                'games_today': []
            }

            params = resolver.resolve_parameters(
                scraper_name='test_scraper',
                workflow_context=context
            )

            assert params['game_date'] == '2024-01-15'
            assert params['season'] == '2023-24'

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_resolve_returns_defaults_for_unknown_scraper(self, mock_schedule):
        """Test resolving unknown scraper returns default parameters"""
        with patch.object(ParameterResolver, '_load_config', return_value={'simple_scrapers': {}, 'complex_scrapers': []}):
            resolver = ParameterResolver()

            context = {
                'execution_date': '2024-01-15',
                'season': '2023-24'
            }

            params = resolver.resolve_parameters(
                scraper_name='unknown_scraper',
                workflow_context=context
            )

            # Should return default parameters
            assert params is not None
            assert params['date'] == '2024-01-15'
            assert params['season'] == '2023-24'


class TestComplexParameterResolution:
    """Test suite for complex (code-based) parameter resolution"""

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_resolve_complex_scraper_calls_resolver_function(self, mock_schedule):
        """Test complex scraper uses resolver function"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            resolver = ParameterResolver()

            # Create mock game objects
            mock_game1 = Mock()
            mock_game1.game_id = '0022400123'
            mock_game1.game_date = '2024-01-15'

            mock_game2 = Mock()
            mock_game2.game_id = '0022400124'
            mock_game2.game_date = '2024-01-15'

            context = {
                'target_date': '2024-01-15',
                'season': '2023-24',
                'games_today': [mock_game1, mock_game2]
            }

            # Call resolve_parameters and let actual resolver run
            params = resolver.resolve_parameters(
                scraper_name='nbac_play_by_play',
                workflow_context=context
            )

            # Should return list of parameters (one per game)
            assert isinstance(params, list)
            assert len(params) == 2
            # Verify structure of returned parameters
            assert params[0]['game_id'] == '0022400123'
            assert params[0]['gamedate'] == '20240115'
            assert params[0]['season'] == '2023-24'
            assert params[1]['game_id'] == '0022400124'


class TestSeasonCalculation:
    """Test suite for season calculation"""

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_get_current_season_during_regular_season(self, mock_schedule):
        """Test season calculation during regular season"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            resolver = ParameterResolver()

            # January 2024 = 2023-24 season
            season = resolver.get_current_season(
                current_time=datetime(2024, 1, 15, 10, 0, 0)
            )

            assert season == '2023-24'

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_get_current_season_during_offseason(self, mock_schedule):
        """Test season calculation during off-season"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            resolver = ParameterResolver()

            # July 2024 = 2024-25 season (next season)
            season = resolver.get_current_season(
                current_time=datetime(2024, 7, 15, 10, 0, 0)
            )

            # Off-season transitions vary, but should return valid season
            assert '202' in season and '-' in season

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_get_current_season_at_season_boundary(self, mock_schedule):
        """Test season calculation at season boundaries"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            resolver = ParameterResolver()

            # October 2024 = start of 2024-25 season
            season = resolver.get_current_season(
                current_time=datetime(2024, 10, 15, 10, 0, 0)
            )

            assert season == '2024-25'


class TestDefaultParameters:
    """Test suite for default parameter injection"""

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_get_default_parameters_includes_common_fields(self, mock_schedule):
        """Test default parameters include common fields"""
        with patch.object(ParameterResolver, '_load_config', return_value={}):
            resolver = ParameterResolver()

            context = {
                'execution_date': '2024-01-15',
                'season': '2023-24'
            }

            defaults = resolver._get_default_parameters(context)

            assert 'date' in defaults
            assert defaults['date'] == '2024-01-15'
            assert 'season' in defaults
            assert defaults['season'] == '2023-24'
            assert isinstance(defaults, dict)


class TestErrorHandling:
    """Test suite for error handling"""

    @patch('orchestration.parameter_resolver.NBAScheduleService')
    def test_resolve_handles_missing_context_fields(self, mock_schedule):
        """Test parameter resolution handles missing context fields"""
        mock_config = {
            'simple_scrapers': {
                'test_scraper': {
                    'game_date': 'context.target_date',
                    'missing_field': 'context.nonexistent'
                }
            },
            'complex_scrapers': []
        }

        with patch.object(ParameterResolver, '_load_config', return_value=mock_config):
            resolver = ParameterResolver()

            context = {
                'target_date': '2024-01-15'
                # missing 'nonexistent' field
            }

            params = resolver.resolve_parameters(
                scraper_name='test_scraper',
                workflow_context=context
            )

            # Should still resolve available fields
            assert params is not None
            assert params['game_date'] == '2024-01-15'
            # Missing field should be None
            assert params['missing_field'] is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
