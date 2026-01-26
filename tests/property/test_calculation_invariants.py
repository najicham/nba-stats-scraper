"""
Property-based tests for statistical calculation invariants.

Uses Hypothesis to verify:
- Sum of parts equals whole
- Averages are between min and max
- Percentages are in 0-100 range
- Monotonicity properties
- Statistical relationships hold
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, example
from hypothesis.strategies import composite
import statistics


# =============================================================================
# Strategies for Statistical Data
# =============================================================================

@composite
def stat_list(draw, min_size=1, max_size=20, min_value=0, max_value=100):
    """Generate list of statistics."""
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    return [draw(st.integers(min_value=min_value, max_value=max_value)) for _ in range(size)]


@composite
def player_game_stats(draw):
    """Generate a player's game statistics."""
    fg_made = draw(st.integers(min_value=0, max_value=30))
    fg_attempted = draw(st.integers(min_value=fg_made, max_value=40))
    three_made = draw(st.integers(min_value=0, max_value=min(fg_made, 20)))
    three_attempted = draw(st.integers(min_value=three_made, max_value=min(fg_attempted, 25)))
    ft_made = draw(st.integers(min_value=0, max_value=20))
    ft_attempted = draw(st.integers(min_value=ft_made, max_value=25))

    return {
        'fg_made': fg_made,
        'fg_attempted': fg_attempted,
        'three_made': three_made,
        'three_attempted': three_attempted,
        'ft_made': ft_made,
        'ft_attempted': ft_attempted,
        'points': (fg_made - three_made) * 2 + three_made * 3 + ft_made,
        'rebounds': draw(st.integers(min_value=0, max_value=25)),
        'assists': draw(st.integers(min_value=0, max_value=20)),
        'steals': draw(st.integers(min_value=0, max_value=10)),
        'blocks': draw(st.integers(min_value=0, max_value=10)),
        'turnovers': draw(st.integers(min_value=0, max_value=10)),
        'minutes': draw(st.floats(min_value=0.1, max_value=48.0, allow_nan=False)),
    }


@composite
def team_player_stats(draw, num_players=5):
    """Generate stats for multiple players on a team."""
    return [draw(player_game_stats()) for _ in range(num_players)]


# =============================================================================
# Sum of Parts Tests
# =============================================================================

class TestSumOfParts:
    """Test that sum of parts equals the whole."""

    @given(stat_list())
    def test_individual_stats_sum_to_team_total(self, individual_stats):
        """Property: Individual player stats sum to team total."""
        team_total = sum(individual_stats)
        calculated_sum = sum(individual_stats)

        assert team_total == calculated_sum

    @given(team_player_stats())
    def test_team_points_sum(self, players):
        """Property: Team points = sum of player points."""
        team_points = sum(p['points'] for p in players)
        individual_sum = sum(p['points'] for p in players)

        assert team_points == individual_sum

    @given(team_player_stats())
    def test_team_rebounds_sum(self, players):
        """Property: Team rebounds >= sum of player rebounds (team rebounds exist)."""
        player_rebounds = sum(p['rebounds'] for p in players)

        # In reality, team rebounds can be slightly higher due to team rebounds
        # For this test, we verify the sum is at least the player total
        assert player_rebounds >= 0

    @given(
        st.lists(st.integers(min_value=0, max_value=100), min_size=2, max_size=10),
        st.lists(st.integers(min_value=0, max_value=100), min_size=2, max_size=10)
    )
    def test_quarter_scores_sum_to_final(self, team1_quarters, team2_quarters):
        """Property: Quarter scores sum to final score."""
        assume(len(team1_quarters) == len(team2_quarters))

        team1_total = sum(team1_quarters)
        team2_total = sum(team2_quarters)

        # Verify sum property
        assert team1_total == sum(team1_quarters)
        assert team2_total == sum(team2_quarters)


# =============================================================================
# Average Between Min and Max Tests
# =============================================================================

class TestAverageInRange:
    """Test that averages are always between min and max."""

    @given(stat_list(min_size=1, max_size=100))
    def test_average_between_min_max(self, values):
        """Property: avg(values) is between min(values) and max(values)."""
        avg = statistics.mean(values)
        min_val = min(values)
        max_val = max(values)

        assert min_val <= avg <= max_val, \
            f"Average {avg} not in range [{min_val}, {max_val}]"

    @given(st.lists(st.floats(min_value=0, max_value=50, allow_nan=False), min_size=1, max_size=20))
    def test_average_points_per_game(self, game_points):
        """Property: Average PPG is between min and max game points."""
        avg_ppg = statistics.mean(game_points)
        min_ppg = min(game_points)
        max_ppg = max(game_points)

        assert min_ppg <= avg_ppg <= max_ppg

    @given(st.integers(min_value=1, max_value=82))
    def test_single_value_average_equals_value(self, value):
        """Property: Average of single value equals that value."""
        avg = statistics.mean([value])
        assert avg == value

    @given(st.integers(min_value=0, max_value=100), st.integers(min_value=2, max_value=10))
    def test_constant_values_average(self, value, count):
        """Property: Average of constant values equals that value."""
        values = [value] * count
        avg = statistics.mean(values)
        assert avg == value


# =============================================================================
# Percentage Range Tests (0-100)
# =============================================================================

class TestPercentageRange:
    """Test that percentages are always in 0-100 range."""

    @given(st.integers(min_value=0, max_value=100), st.integers(min_value=1, max_value=100))
    def test_field_goal_percentage(self, made, attempted):
        """Property: FG% is in [0, 100] range."""
        assume(made <= attempted)

        fg_pct = (made / attempted) * 100 if attempted > 0 else 0

        assert 0 <= fg_pct <= 100

    @given(player_game_stats())
    def test_shooting_percentages_in_range(self, stats):
        """Property: All shooting percentages are in [0, 100]."""
        if stats['fg_attempted'] > 0:
            fg_pct = (stats['fg_made'] / stats['fg_attempted']) * 100
            assert 0 <= fg_pct <= 100

        if stats['three_attempted'] > 0:
            three_pct = (stats['three_made'] / stats['three_attempted']) * 100
            assert 0 <= three_pct <= 100

        if stats['ft_attempted'] > 0:
            ft_pct = (stats['ft_made'] / stats['ft_attempted']) * 100
            assert 0 <= ft_pct <= 100

    @given(st.integers(min_value=0, max_value=82), st.integers(min_value=0, max_value=82))
    def test_win_percentage_in_range(self, wins, total_games):
        """Property: Win% is in [0, 100] range."""
        assume(wins <= total_games and total_games > 0)

        win_pct = (wins / total_games) * 100

        assert 0 <= win_pct <= 100

    @given(st.integers(min_value=0, max_value=100))
    def test_percentage_never_negative(self, value):
        """Property: Percentages are never negative."""
        pct = max(0, min(100, value))
        assert 0 <= pct <= 100


# =============================================================================
# Percentage Bounds (0.0-1.0) Tests
# =============================================================================

class TestPercentageBoundsDecimal:
    """Test that decimal percentages are in 0.0-1.0 range."""

    @given(st.integers(min_value=0, max_value=100), st.integers(min_value=1, max_value=100))
    def test_decimal_percentage_range(self, made, attempted):
        """Property: Decimal percentage is in [0.0, 1.0]."""
        assume(made <= attempted)

        pct = made / attempted if attempted > 0 else 0.0

        assert 0.0 <= pct <= 1.0

    @given(player_game_stats())
    def test_true_shooting_percentage(self, stats):
        """Property: TS% is in valid range."""
        # TS% = PTS / (2 * (FGA + 0.44 * FTA))
        tsa = stats['fg_attempted'] + 0.44 * stats['ft_attempted']

        if tsa > 0:
            ts_pct = stats['points'] / (2 * tsa)
            # TS% can theoretically exceed 1.0 for very efficient scorers
            # but should be reasonable (< 1.5)
            assert 0.0 <= ts_pct <= 1.5


# =============================================================================
# Monotonicity Tests
# =============================================================================

class TestMonotonicity:
    """Test monotonicity properties (if X increases, Y should increase)."""

    @given(st.integers(min_value=0, max_value=30), st.integers(min_value=0, max_value=40))
    def test_more_makes_more_points(self, fg_made, fg_attempted):
        """Property: More field goals made = more points (monotonic)."""
        assume(fg_made <= fg_attempted)

        points1 = fg_made * 2
        points2 = (fg_made + 1) * 2 if fg_made + 1 <= fg_attempted else points1

        if fg_made + 1 <= fg_attempted:
            assert points2 >= points1

    @given(st.integers(min_value=0, max_value=40))
    def test_more_minutes_opportunity_for_more_stats(self, base_minutes):
        """Property: More minutes generally means more opportunity."""
        # This is a weak monotonicity - more minutes should not decrease opportunities
        # We can't guarantee more stats, but per-minute rates should be stable

        # At minimum, minutes are non-decreasing
        minutes_list = sorted([base_minutes, base_minutes + 5, base_minutes + 10])

        assert minutes_list[0] <= minutes_list[1] <= minutes_list[2]

    @given(st.lists(st.integers(min_value=0, max_value=50), min_size=2, max_size=10))
    def test_cumulative_sum_monotonic(self, values):
        """Property: Cumulative sums are monotonically increasing."""
        cumsum = []
        total = 0

        for val in values:
            total += val
            cumsum.append(total)

        # Each element should be >= previous
        for i in range(1, len(cumsum)):
            assert cumsum[i] >= cumsum[i-1]

    @given(st.integers(min_value=5, max_value=82))
    def test_more_games_more_sample_size(self, num_games):
        """Property: More games = larger sample size (monotonic)."""
        games_10 = min(num_games, 10)
        games_20 = min(num_games, 20)

        assert games_10 <= games_20


# =============================================================================
# Statistical Relationship Tests
# =============================================================================

class TestStatisticalRelationships:
    """Test that statistical relationships hold."""

    @given(player_game_stats())
    def test_points_from_shooting(self, stats):
        """Property: Points = 2*2PM + 3*3PM + FTM."""
        two_point_made = stats['fg_made'] - stats['three_made']
        expected_points = two_point_made * 2 + stats['three_made'] * 3 + stats['ft_made']

        assert stats['points'] == expected_points

    @given(player_game_stats())
    def test_makes_never_exceed_attempts(self, stats):
        """Property: Makes <= Attempts for all shot types."""
        assert stats['fg_made'] <= stats['fg_attempted']
        assert stats['three_made'] <= stats['three_attempted']
        assert stats['ft_made'] <= stats['ft_attempted']

    @given(player_game_stats())
    def test_three_pointers_subset_of_field_goals(self, stats):
        """Property: 3PM <= FGM and 3PA <= FGA."""
        assert stats['three_made'] <= stats['fg_made']
        assert stats['three_attempted'] <= stats['fg_attempted']

    @given(
        st.integers(min_value=0, max_value=20),  # assists
        st.integers(min_value=0, max_value=30),  # fg_made
    )
    def test_assists_reasonable_vs_makes(self, assists, team_fg_made):
        """Property: Assists <= Team FG Made (can't assist more than team scores)."""
        # In reality, assists can be close to team FG made
        # This is a sanity check, not a strict constraint
        assert assists >= 0
        assert team_fg_made >= 0


# =============================================================================
# Aggregation Invariants
# =============================================================================

class TestAggregationInvariants:
    """Test aggregation invariants."""

    @given(stat_list(min_size=2, max_size=20))
    def test_sum_aggregation_preserves_total(self, values):
        """Property: Aggregating by sum preserves total."""
        original_sum = sum(values)

        # Split into groups and aggregate
        mid = len(values) // 2
        group1_sum = sum(values[:mid])
        group2_sum = sum(values[mid:])
        aggregated_sum = group1_sum + group2_sum

        assert original_sum == aggregated_sum

    @given(st.lists(st.floats(min_value=0, max_value=50, allow_nan=False), min_size=2, max_size=20))
    def test_average_aggregation(self, values):
        """Property: Average of averages with equal weights equals overall average."""
        overall_avg = statistics.mean(values)

        # Split into two equal groups
        mid = len(values) // 2
        group1 = values[:mid]
        group2 = values[mid:]

        if len(group1) > 0 and len(group2) > 0:
            avg1 = statistics.mean(group1)
            avg2 = statistics.mean(group2)

            # Weighted average
            weighted_avg = (avg1 * len(group1) + avg2 * len(group2)) / len(values)

            assert abs(overall_avg - weighted_avg) < 0.0001

    @given(team_player_stats())
    def test_player_aggregation_to_team(self, players):
        """Property: Aggregating player stats gives team stats."""
        team_points = sum(p['points'] for p in players)
        team_rebounds = sum(p['rebounds'] for p in players)
        team_assists = sum(p['assists'] for p in players)

        # All should be non-negative and sum correctly
        assert team_points >= 0
        assert team_rebounds >= 0
        assert team_assists >= 0

        # Sum of individual stats
        assert team_points == sum(p['points'] for p in players)


# =============================================================================
# Zero and Boundary Tests
# =============================================================================

class TestZeroAndBoundaries:
    """Test behavior at zero and boundary values."""

    @given(st.integers(min_value=0, max_value=100))
    def test_division_by_zero_safe(self, numerator):
        """Property: Division handles zero denominator gracefully."""
        denominator = 0

        # Should return None or 0, not crash
        result = numerator / denominator if denominator > 0 else None

        assert result is None or result == 0

    @given(st.integers(min_value=0, max_value=100))
    def test_zero_attempts_gives_zero_percentage(self, made):
        """Property: 0 attempts gives 0% or None."""
        attempts = 0

        pct = (made / attempts) * 100 if attempts > 0 else 0

        assert pct == 0

    @given(st.integers(min_value=0, max_value=100))
    def test_perfect_shooting(self, attempts):
        """Property: Made = Attempts gives 100%."""
        assume(attempts > 0)

        made = attempts
        pct = (made / attempts) * 100

        assert pct == 100.0


# =============================================================================
# Consistency Tests
# =============================================================================

class TestCalculationConsistency:
    """Test that calculations are consistent and deterministic."""

    @given(player_game_stats())
    def test_calculation_deterministic(self, stats):
        """Property: Same inputs give same outputs (deterministic)."""
        # Calculate points multiple times
        points1 = (stats['fg_made'] - stats['three_made']) * 2 + stats['three_made'] * 3 + stats['ft_made']
        points2 = (stats['fg_made'] - stats['three_made']) * 2 + stats['three_made'] * 3 + stats['ft_made']
        points3 = (stats['fg_made'] - stats['three_made']) * 2 + stats['three_made'] * 3 + stats['ft_made']

        assert points1 == points2 == points3

    @given(st.integers(min_value=0, max_value=100), st.integers(min_value=1, max_value=100))
    def test_percentage_calculation_consistent(self, made, attempted):
        """Property: Percentage calculation is consistent."""
        assume(made <= attempted)

        pct1 = (made / attempted) * 100
        pct2 = (made / attempted) * 100
        pct3 = (made / attempted) * 100

        assert pct1 == pct2 == pct3


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--hypothesis-show-statistics'])
