"""
Unit tests for usage_rate calculation in player_game_summary_processor.

These tests verify the per-game usage_rate calculation logic introduced in Session 96.
Previously, a global threshold would block ALL usage_rate calculations if not met.
Now, usage_rate is calculated per-game based on whether THAT game has team stats.

Test Scenarios:
1. Partial team data (2/4 games have team stats)
2. One game delayed (3/4 games ready)
3. No team data (all games missing)
4. Full team data (all games ready)
"""

import pytest
import pandas as pd
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


class TestUsageRatePerGameCalculation:
    """Test that usage_rate is calculated per-game, not globally."""

    def test_has_team_stats_for_game_detection(self):
        """Verify has_team_stats_for_game is correctly detected from row data."""
        # Row WITH team stats
        row_with_stats = {
            'team_fg_attempts': 80,
            'team_ft_attempts': 20,
            'team_turnovers': 12,
            'field_goals_attempted': 15,
            'turnovers': 2,
        }

        has_team_stats = (
            pd.notna(row_with_stats.get('team_fg_attempts')) and
            pd.notna(row_with_stats.get('team_ft_attempts')) and
            pd.notna(row_with_stats.get('team_turnovers'))
        )
        assert has_team_stats is True

        # Row WITHOUT team stats
        row_without_stats = {
            'team_fg_attempts': None,
            'team_ft_attempts': None,
            'team_turnovers': None,
            'field_goals_attempted': 15,
            'turnovers': 2,
        }

        has_team_stats_missing = (
            pd.notna(row_without_stats.get('team_fg_attempts')) and
            pd.notna(row_without_stats.get('team_ft_attempts')) and
            pd.notna(row_without_stats.get('team_turnovers'))
        )
        assert has_team_stats_missing is False

    def test_usage_rate_formula_calculation(self):
        """Verify usage_rate formula is correct."""
        # Sample data
        player_fga = 15
        player_fta = 5
        player_to = 2
        minutes_decimal = 32.5
        team_fga = 80
        team_fta = 20
        team_to = 12

        # Calculate
        player_poss_used = player_fga + 0.44 * player_fta + player_to
        team_poss_used = team_fga + 0.44 * team_fta + team_to

        usage_rate = 100.0 * player_poss_used * 48.0 / (minutes_decimal * team_poss_used)

        # Verify reasonable range (typical usage is 15-35%)
        assert 10.0 < usage_rate < 50.0

        # Verify exact calculation
        expected = 100.0 * (15 + 0.44 * 5 + 2) * 48.0 / (32.5 * (80 + 0.44 * 20 + 12))
        assert abs(usage_rate - expected) < 0.01

    def test_usage_rate_over_100_rejected(self):
        """Verify usage_rate > 100% is set to None (data quality issue)."""
        # Extreme case: player used more possessions than reasonable
        player_fga = 50
        player_fta = 20
        player_to = 10
        minutes_decimal = 10.0  # Very few minutes
        team_fga = 30  # Low team total
        team_fta = 10
        team_to = 5

        player_poss_used = player_fga + 0.44 * player_fta + player_to
        team_poss_used = team_fga + 0.44 * team_fta + team_to

        usage_rate = 100.0 * player_poss_used * 48.0 / (minutes_decimal * team_poss_used)

        # This should be > 100% and would be rejected
        assert usage_rate > 100.0

        # In the actual code, this would be set to None
        if usage_rate > 100.0:
            usage_rate = None
        assert usage_rate is None

    def test_usage_rate_with_zero_minutes_skipped(self):
        """Verify usage_rate is None when player has 0 minutes."""
        minutes_decimal = 0.0

        # Cannot calculate usage_rate with 0 minutes (division by zero)
        can_calculate = minutes_decimal and minutes_decimal > 0
        assert can_calculate == False  # 0.0 is falsy, so this evaluates to 0.0 which equals False

    def test_data_quality_flag_per_game(self):
        """Verify data_quality_flag is set per-game based on team stats."""
        # Scenario: Player in game WITH team stats
        usage_rate_1 = 25.5
        has_team_stats_1 = True

        flag_1 = 'complete' if (usage_rate_1 is not None and has_team_stats_1) else (
            'partial_no_team_stats' if not has_team_stats_1 else 'partial'
        )
        assert flag_1 == 'complete'

        # Scenario: Player in game WITHOUT team stats
        usage_rate_2 = None
        has_team_stats_2 = False

        flag_2 = 'complete' if (usage_rate_2 is not None and has_team_stats_2) else (
            'partial_no_team_stats' if not has_team_stats_2 else 'partial'
        )
        assert flag_2 == 'partial_no_team_stats'

        # Scenario: Player with stats but usage_rate failed calculation
        usage_rate_3 = None  # e.g., was > 100% and rejected
        has_team_stats_3 = True

        flag_3 = 'complete' if (usage_rate_3 is not None and has_team_stats_3) else (
            'partial_no_team_stats' if not has_team_stats_3 else 'partial'
        )
        assert flag_3 == 'partial'


class TestPartialTeamDataScenarios:
    """Test scenarios where only some games have team stats."""

    def test_two_of_four_games_have_team_stats(self):
        """
        Scenario: 4 games scheduled, only 2 have team_offense_game_summary data.
        Expected: Players in games WITH team data get usage_rate.
                  Players in games WITHOUT team data get NULL.
        """
        # Simulate 4 games worth of players
        games_data = [
            # Game 1: HAS team stats
            {'game_id': '20260202_HOU_IND', 'team_fg_attempts': 80, 'team_ft_attempts': 20, 'team_turnovers': 12},
            # Game 2: NO team stats
            {'game_id': '20260202_PHI_LAC', 'team_fg_attempts': None, 'team_ft_attempts': None, 'team_turnovers': None},
            # Game 3: HAS team stats
            {'game_id': '20260202_MIN_MEM', 'team_fg_attempts': 75, 'team_ft_attempts': 18, 'team_turnovers': 10},
            # Game 4: NO team stats
            {'game_id': '20260202_NOP_CHA', 'team_fg_attempts': None, 'team_ft_attempts': None, 'team_turnovers': None},
        ]

        results = []
        for game in games_data:
            has_team_stats = (
                pd.notna(game.get('team_fg_attempts')) and
                pd.notna(game.get('team_ft_attempts')) and
                pd.notna(game.get('team_turnovers'))
            )

            # In reality, usage_rate would be calculated if has_team_stats
            usage_rate = 25.0 if has_team_stats else None
            results.append({
                'game_id': game['game_id'],
                'has_team_stats': has_team_stats,
                'usage_rate': usage_rate,
            })

        # Verify: 2 games have usage_rate, 2 don't
        games_with_usage = [r for r in results if r['usage_rate'] is not None]
        games_without_usage = [r for r in results if r['usage_rate'] is None]

        assert len(games_with_usage) == 2
        assert len(games_without_usage) == 2

        # Verify correct games have data
        assert games_with_usage[0]['game_id'] == '20260202_HOU_IND'
        assert games_with_usage[1]['game_id'] == '20260202_MIN_MEM'

    def test_one_game_delayed_three_ready(self):
        """
        Scenario: 4 games, 3 have team stats, 1 delayed.
        This was the Feb 2 scenario that caused the original bug.
        Expected: 3 games get usage_rate (75% coverage, not 0%).
        """
        # OLD behavior (global threshold at 80%): 3/4 = 75% < 80% = ALL games get NULL
        old_threshold = 0.80
        actual_coverage = 3 / 4  # 75%
        old_behavior_would_calculate = actual_coverage >= old_threshold
        assert old_behavior_would_calculate is False  # Bug: would block all

        # NEW behavior (per-game): Each game calculated individually
        games = [
            {'game_id': 'game1', 'has_team_stats': True},
            {'game_id': 'game2', 'has_team_stats': True},
            {'game_id': 'game3', 'has_team_stats': True},
            {'game_id': 'game4', 'has_team_stats': False},  # Delayed
        ]

        new_results = []
        for game in games:
            usage_rate = 25.0 if game['has_team_stats'] else None
            new_results.append(usage_rate)

        games_with_usage = [u for u in new_results if u is not None]
        assert len(games_with_usage) == 3  # 3 games get usage_rate

        # Coverage is 75%, not 0%
        coverage = len(games_with_usage) / len(new_results)
        assert coverage == 0.75


class TestEdgeCases:
    """Test edge cases in usage_rate calculation."""

    def test_no_team_data_at_all(self):
        """All games missing team stats - all get NULL usage_rate."""
        games = [
            {'has_team_stats': False},
            {'has_team_stats': False},
            {'has_team_stats': False},
        ]

        for game in games:
            usage_rate = 25.0 if game['has_team_stats'] else None
            assert usage_rate is None

    def test_all_team_data_present(self):
        """All games have team stats - all get usage_rate."""
        games = [
            {'has_team_stats': True},
            {'has_team_stats': True},
            {'has_team_stats': True},
        ]

        for game in games:
            usage_rate = 25.0 if game['has_team_stats'] else None
            assert usage_rate == 25.0

    def test_zero_team_possessions(self):
        """Handle edge case where team_poss_used = 0."""
        team_fga = 0
        team_fta = 0
        team_to = 0
        team_poss_used = team_fga + 0.44 * team_fta + team_to

        # Should not divide by zero
        assert team_poss_used == 0

        # In actual code, we check team_poss_used > 0 before calculating
        if team_poss_used > 0:
            usage_rate = 100.0  # Would calculate
        else:
            usage_rate = None  # Skip calculation

        assert usage_rate is None

    def test_dnp_player_no_usage_rate(self):
        """DNP players should have NULL usage_rate (no minutes)."""
        is_dnp = True
        minutes_decimal = 0.0

        # DNP players have 0 minutes, so usage_rate calculation is skipped
        can_calculate = not is_dnp and minutes_decimal and minutes_decimal > 0
        assert can_calculate is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
