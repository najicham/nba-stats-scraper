"""
tests/orchestration/unit/test_parameter_resolver.py

Unit tests for ParameterResolver, especially the target date logic.

This tests the critical fix for Issue #165 (Session 165):
Post-game workflows like post_game_window_3 must target YESTERDAY's games,
not today's games, to correctly fetch gamebooks for finished games.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import pytz

from orchestration.parameter_resolver import (
    ParameterResolver,
    YESTERDAY_TARGET_WORKFLOWS
)


class TestTargetDateDetermination:
    """Tests for _determine_target_date() logic."""

    @pytest.fixture
    def resolver(self):
        """Create resolver with mocked schedule service."""
        with patch('orchestration.parameter_resolver.NBAScheduleService'):
            resolver = ParameterResolver()
            # Mock schedule service to return empty list (not testing game fetching here)
            resolver.schedule_service.get_games_for_date = Mock(return_value=[])
            return resolver

    def test_post_game_workflows_target_yesterday(self, resolver):
        """Post-game workflows should target yesterday's games."""
        ET = pytz.timezone('America/New_York')
        # Simulate running at 4 AM on Dec 25
        current_time = ET.localize(datetime(2025, 12, 25, 4, 0, 0))

        for workflow_name in YESTERDAY_TARGET_WORKFLOWS:
            target_date = resolver._determine_target_date(
                workflow_name=workflow_name,
                current_time=current_time
            )
            assert target_date == '2025-12-24', \
                f"{workflow_name} should target yesterday (2025-12-24), got {target_date}"

    def test_regular_workflows_target_today(self, resolver):
        """Regular workflows should target today's games."""
        ET = pytz.timezone('America/New_York')
        current_time = ET.localize(datetime(2025, 12, 25, 10, 0, 0))

        regular_workflows = [
            'betting_lines',
            'morning_operations',
            'early_game_window_1',
            'discovery_mode',
        ]

        for workflow_name in regular_workflows:
            target_date = resolver._determine_target_date(
                workflow_name=workflow_name,
                current_time=current_time
            )
            assert target_date == '2025-12-25', \
                f"{workflow_name} should target today (2025-12-25), got {target_date}"

    def test_explicit_date_overrides_workflow_pattern(self, resolver):
        """Explicit target_date should override workflow pattern."""
        ET = pytz.timezone('America/New_York')
        current_time = ET.localize(datetime(2025, 12, 25, 4, 0, 0))

        # Even for a post_game workflow, explicit date should be used
        target_date = resolver._determine_target_date(
            workflow_name='post_game_window_3',
            current_time=current_time,
            explicit_target_date='2025-12-20'  # Backfill to specific date
        )
        assert target_date == '2025-12-20', \
            f"Explicit date should be used, got {target_date}"


class TestBuildWorkflowContext:
    """Tests for build_workflow_context() with target date logic."""

    @pytest.fixture
    def resolver_with_games(self):
        """Create resolver with mocked schedule service that returns games."""
        with patch('orchestration.parameter_resolver.NBAScheduleService'):
            resolver = ParameterResolver()

            # Mock game objects
            mock_game = Mock()
            mock_game.game_id = '0022500001'
            mock_game.game_date = '2025-12-24'
            mock_game.home_team = 'NYK'
            mock_game.away_team = 'CLE'

            # Return games only for Dec 24
            def mock_get_games(date_str):
                if date_str == '2025-12-24':
                    return [mock_game]
                return []

            resolver.schedule_service.get_games_for_date = Mock(side_effect=mock_get_games)
            return resolver

    def test_post_game_context_has_yesterdays_games(self, resolver_with_games):
        """post_game_window_3 context should contain yesterday's games."""
        with patch('orchestration.parameter_resolver.datetime') as mock_dt:
            # Mock "now" to be 4 AM on Dec 25
            ET = pytz.timezone('America/New_York')
            mock_now = ET.localize(datetime(2025, 12, 25, 4, 0, 0))
            mock_dt.now.return_value = mock_now

            context = resolver_with_games.build_workflow_context(
                workflow_name='post_game_window_3'
            )

            assert context['execution_date'] == '2025-12-25'
            assert context['target_date'] == '2025-12-24'
            assert context['games_count'] == 1
            assert len(context['games_today']) == 1  # "games_today" is really games for target date

    def test_context_contains_target_date_field(self, resolver_with_games):
        """Context should always include target_date field."""
        with patch('orchestration.parameter_resolver.datetime') as mock_dt:
            ET = pytz.timezone('America/New_York')
            mock_now = ET.localize(datetime(2025, 12, 25, 10, 0, 0))
            mock_dt.now.return_value = mock_now

            context = resolver_with_games.build_workflow_context(
                workflow_name='betting_lines'
            )

            assert 'target_date' in context
            assert 'execution_date' in context
            # For regular workflow, target_date == execution_date
            assert context['target_date'] == context['execution_date']


class TestYesterdayTargetWorkflowsList:
    """Tests that the YESTERDAY_TARGET_WORKFLOWS list is correct."""

    def test_post_game_windows_are_included(self):
        """All post_game_window_* workflows should be in the list."""
        expected = [
            'post_game_window_1',
            'post_game_window_2',
            'post_game_window_3',
        ]
        for workflow in expected:
            assert workflow in YESTERDAY_TARGET_WORKFLOWS, \
                f"{workflow} should be in YESTERDAY_TARGET_WORKFLOWS"

    def test_late_games_is_included(self):
        """late_games workflow should be in the list."""
        assert 'late_games' in YESTERDAY_TARGET_WORKFLOWS

    def test_betting_lines_not_included(self):
        """betting_lines should NOT target yesterday."""
        assert 'betting_lines' not in YESTERDAY_TARGET_WORKFLOWS

    def test_early_game_windows_not_included(self):
        """early_game_window_* should NOT target yesterday."""
        early_windows = [
            'early_game_window_1',
            'early_game_window_2',
            'early_game_window_3',
        ]
        for workflow in early_windows:
            assert workflow not in YESTERDAY_TARGET_WORKFLOWS, \
                f"{workflow} should NOT be in YESTERDAY_TARGET_WORKFLOWS"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
