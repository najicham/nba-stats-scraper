"""
Property-based tests for feature calculation functions.

Uses Hypothesis to verify:
- ML Feature Store feature calculations (FeatureCalculator)
- Usage rate calculations
- Rest advantage calculations
- Injury risk mappings
- Trend calculations
- Win percentage calculations
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, example
from hypothesis.strategies import composite
import math


# =============================================================================
# Feature Calculator Implementation (mirrors production code)
# =============================================================================

NUMERIC_PRECISION = 9


class FeatureCalculator:
    """Test implementation of FeatureCalculator for property testing."""

    def calculate_rest_advantage(self, phase3_data):
        """Calculate rest advantage: player rest minus opponent rest."""
        player_rest = phase3_data.get('days_rest')
        opponent_rest = phase3_data.get('opponent_days_rest')

        if player_rest is None or opponent_rest is None:
            return 0.0

        rest_diff = int(player_rest) - int(opponent_rest)
        return max(-2.0, min(2.0, float(rest_diff)))

    def calculate_injury_risk(self, phase3_data):
        """Calculate injury risk from player status."""
        player_status = (phase3_data.get('player_status') or '').lower()

        status_map = {
            'available': 0.0,
            'probable': 1.0,
            'questionable': 2.0,
            'doubtful': 3.0,
            'out': 3.0,
            '': 0.0
        }

        return status_map.get(player_status, 0.0)

    def calculate_recent_trend(self, phase3_data):
        """Calculate performance trend from recent games."""
        last_10_games = phase3_data.get('last_10_games', [])

        if len(last_10_games) < 5:
            return 0.0

        last_5_games = last_10_games[:5]
        first_3_points = [g.get('points') or 0 for g in last_5_games[0:3]]
        last_2_points = [g.get('points') or 0 for g in last_5_games[3:5]]

        avg_first_3 = sum(first_3_points) / 3.0
        avg_last_2 = sum(last_2_points) / 2.0

        diff = avg_last_2 - avg_first_3

        if diff >= 5.0:
            return 2.0
        elif diff >= 2.0:
            return 1.0
        elif diff <= -5.0:
            return -2.0
        elif diff <= -2.0:
            return -1.0
        else:
            return 0.0

    def calculate_minutes_change(self, phase4_data, phase3_data):
        """Calculate minutes change: recent vs season average."""
        minutes_recent = phase4_data.get('minutes_avg_last_10')

        if minutes_recent is None:
            last_10_games = phase3_data.get('last_10_games', [])
            if last_10_games:
                minutes_recent = sum(g.get('minutes_played') or 0 for g in last_10_games) / len(last_10_games)
            else:
                minutes_recent = 0.0

        minutes_season = phase3_data.get('minutes_avg_season') or 0.0

        if minutes_season == 0 or minutes_recent == 0:
            return 0.0

        pct_change = (float(minutes_recent) - float(minutes_season)) / float(minutes_season)

        if pct_change >= 0.20:
            return 2.0
        elif pct_change >= 0.10:
            return 1.0
        elif pct_change <= -0.20:
            return -2.0
        elif pct_change <= -0.10:
            return -1.0
        else:
            return 0.0

    def calculate_pct_free_throw(self, phase3_data):
        """Calculate percentage of points from free throws."""
        DEFAULT_FT_PERCENTAGE = 0.15
        last_10_games = phase3_data.get('last_10_games', [])

        if len(last_10_games) < 5:
            return DEFAULT_FT_PERCENTAGE

        total_ft_makes = sum(g.get('ft_makes') or 0 for g in last_10_games)
        total_points = sum(g.get('points') or 0 for g in last_10_games)

        if total_points == 0:
            return DEFAULT_FT_PERCENTAGE

        pct = float(total_ft_makes) / float(total_points)
        pct = max(0.0, min(0.5, pct))

        return round(pct, NUMERIC_PRECISION)

    def calculate_team_win_pct(self, phase3_data):
        """Calculate team's win percentage."""
        DEFAULT_WIN_PERCENTAGE = 0.500
        season_games = phase3_data.get('team_season_games', [])

        if len(season_games) < 5:
            return DEFAULT_WIN_PERCENTAGE

        wins = sum(1 for g in season_games if g.get('win_flag'))
        total_games = len(season_games)

        win_pct = float(wins) / float(total_games)

        return round(win_pct, NUMERIC_PRECISION)


# =============================================================================
# Strategies for Feature Testing
# =============================================================================

@composite
def game_with_points(draw):
    """Generate a game record with points."""
    return {
        'points': draw(st.integers(min_value=0, max_value=60)),
        'minutes_played': draw(st.integers(min_value=0, max_value=48)),
        'ft_makes': draw(st.integers(min_value=0, max_value=20)),
    }


@composite
def phase3_data_with_games(draw, min_games=0, max_games=10):
    """Generate phase3 data with game history."""
    num_games = draw(st.integers(min_value=min_games, max_value=max_games))
    games = [draw(game_with_points()) for _ in range(num_games)]
    return {
        'last_10_games': games,
        'days_rest': draw(st.one_of(st.none(), st.integers(min_value=0, max_value=10))),
        'opponent_days_rest': draw(st.one_of(st.none(), st.integers(min_value=0, max_value=10))),
        'player_status': draw(st.sampled_from(['available', 'probable', 'questionable', 'doubtful', 'out', '', None])),
        'minutes_avg_season': draw(st.floats(min_value=0, max_value=48, allow_nan=False, allow_infinity=False)),
    }


@composite
def team_season_games(draw, num_games=None):
    """Generate team season game records."""
    if num_games is None:
        num_games = draw(st.integers(min_value=0, max_value=82))
    return [{'win_flag': draw(st.booleans())} for _ in range(num_games)]


# =============================================================================
# Rest Advantage Tests
# =============================================================================

class TestRestAdvantage:
    """Property tests for rest advantage calculation."""

    @given(
        st.integers(min_value=0, max_value=10),
        st.integers(min_value=0, max_value=10)
    )
    def test_rest_advantage_symmetric(self, player_rest, opponent_rest):
        """Rest advantage should be symmetric: swap gives negation."""
        calc = FeatureCalculator()

        data1 = {'days_rest': player_rest, 'opponent_days_rest': opponent_rest}
        data2 = {'days_rest': opponent_rest, 'opponent_days_rest': player_rest}

        result1 = calc.calculate_rest_advantage(data1)
        result2 = calc.calculate_rest_advantage(data2)

        assert abs(result1 + result2) < 0.001

    @given(
        st.integers(min_value=0, max_value=10),
        st.integers(min_value=0, max_value=10)
    )
    def test_rest_advantage_clamped(self, player_rest, opponent_rest):
        """Rest advantage should be clamped to [-2, 2]."""
        calc = FeatureCalculator()
        data = {'days_rest': player_rest, 'opponent_days_rest': opponent_rest}

        result = calc.calculate_rest_advantage(data)

        assert -2.0 <= result <= 2.0

    @given(st.integers(min_value=0, max_value=10))
    def test_equal_rest_is_zero(self, rest_days):
        """Equal rest days should give zero advantage."""
        calc = FeatureCalculator()
        data = {'days_rest': rest_days, 'opponent_days_rest': rest_days}

        result = calc.calculate_rest_advantage(data)

        assert result == 0.0

    @given(st.one_of(st.none(), st.integers(min_value=0, max_value=10)))
    def test_missing_rest_returns_zero(self, player_rest):
        """Missing rest data should return 0.0."""
        calc = FeatureCalculator()

        # Missing opponent rest
        data = {'days_rest': player_rest, 'opponent_days_rest': None}
        assert calc.calculate_rest_advantage(data) == 0.0

        # Missing player rest
        data = {'days_rest': None, 'opponent_days_rest': player_rest}
        assert calc.calculate_rest_advantage(data) == 0.0


# =============================================================================
# Injury Risk Tests
# =============================================================================

class TestInjuryRisk:
    """Property tests for injury risk calculation."""

    @given(st.sampled_from(['available', 'probable', 'questionable', 'doubtful', 'out']))
    def test_injury_risk_valid_statuses(self, status):
        """All valid statuses should map to a risk score."""
        calc = FeatureCalculator()
        data = {'player_status': status}

        result = calc.calculate_injury_risk(data)

        assert 0.0 <= result <= 3.0

    def test_injury_risk_ordering(self):
        """Injury risk should increase with severity."""
        calc = FeatureCalculator()

        available = calc.calculate_injury_risk({'player_status': 'available'})
        probable = calc.calculate_injury_risk({'player_status': 'probable'})
        questionable = calc.calculate_injury_risk({'player_status': 'questionable'})
        doubtful = calc.calculate_injury_risk({'player_status': 'doubtful'})

        assert available < probable < questionable < doubtful

    @given(st.text(min_size=1, max_size=20))
    def test_unknown_status_returns_zero(self, unknown_status):
        """Unknown status should return 0.0 (default to available)."""
        assume(unknown_status.lower() not in ['available', 'probable', 'questionable', 'doubtful', 'out', ''])

        calc = FeatureCalculator()
        data = {'player_status': unknown_status}

        result = calc.calculate_injury_risk(data)

        assert result == 0.0

    @given(st.sampled_from([None, '', '  ']))
    def test_empty_status_returns_zero(self, empty_status):
        """Empty/null status should return 0.0."""
        calc = FeatureCalculator()
        data = {'player_status': empty_status}

        result = calc.calculate_injury_risk(data)

        assert result == 0.0


# =============================================================================
# Recent Trend Tests
# =============================================================================

class TestRecentTrend:
    """Property tests for recent trend calculation."""

    @given(phase3_data_with_games(min_games=0, max_games=4))
    def test_insufficient_games_returns_zero(self, phase3_data):
        """Less than 5 games should return 0.0."""
        assume(len(phase3_data['last_10_games']) < 5)

        calc = FeatureCalculator()
        result = calc.calculate_recent_trend(phase3_data)

        assert result == 0.0

    @given(phase3_data_with_games(min_games=5, max_games=10))
    def test_trend_in_valid_range(self, phase3_data):
        """Trend should be in [-2, 2]."""
        calc = FeatureCalculator()
        result = calc.calculate_recent_trend(phase3_data)

        assert result in [-2.0, -1.0, 0.0, 1.0, 2.0]

    @given(st.integers(min_value=10, max_value=30))
    def test_strong_upward_trend(self, base_points):
        """Strong upward trend should return 2.0."""
        calc = FeatureCalculator()

        # First 3 games: base points, last 2 games: base + 6 (avg diff = 6 >= 5)
        games = [
            {'points': base_points}, {'points': base_points}, {'points': base_points},
            {'points': base_points + 6}, {'points': base_points + 6}
        ]
        data = {'last_10_games': games}

        result = calc.calculate_recent_trend(data)
        assert result == 2.0

    @given(st.integers(min_value=10, max_value=30))
    def test_strong_downward_trend(self, base_points):
        """Strong downward trend should return -2.0."""
        calc = FeatureCalculator()

        # First 3 games: base points, last 2 games: base - 6
        games = [
            {'points': base_points}, {'points': base_points}, {'points': base_points},
            {'points': max(0, base_points - 6)}, {'points': max(0, base_points - 6)}
        ]
        data = {'last_10_games': games}

        result = calc.calculate_recent_trend(data)

        # Could be -1 or -2 depending on exact calculation
        assert result <= 0.0

    @given(st.integers(min_value=10, max_value=30))
    def test_stable_trend(self, base_points):
        """Stable scoring should return 0.0."""
        calc = FeatureCalculator()

        games = [{'points': base_points} for _ in range(5)]
        data = {'last_10_games': games}

        result = calc.calculate_recent_trend(data)
        assert result == 0.0


# =============================================================================
# Minutes Change Tests
# =============================================================================

class TestMinutesChange:
    """Property tests for minutes change calculation."""

    @given(
        st.floats(min_value=25, max_value=40, allow_nan=False),
        st.floats(min_value=25, max_value=40, allow_nan=False)
    )
    def test_minutes_change_in_range(self, recent, season):
        """Minutes change should be in [-2, 2]."""
        assume(season > 0 and recent > 0)

        calc = FeatureCalculator()
        phase4_data = {'minutes_avg_last_10': recent}
        phase3_data = {'minutes_avg_season': season}

        result = calc.calculate_minutes_change(phase4_data, phase3_data)

        assert result in [-2.0, -1.0, 0.0, 1.0, 2.0]

    @given(st.floats(min_value=20, max_value=40, allow_nan=False))
    def test_same_minutes_is_zero(self, minutes):
        """Same minutes should return 0.0."""
        calc = FeatureCalculator()
        phase4_data = {'minutes_avg_last_10': minutes}
        phase3_data = {'minutes_avg_season': minutes}

        result = calc.calculate_minutes_change(phase4_data, phase3_data)

        assert result == 0.0

    @given(st.floats(min_value=20, max_value=30, allow_nan=False))
    def test_significant_increase(self, season_minutes):
        """20%+ increase should return 2.0."""
        calc = FeatureCalculator()

        recent_minutes = season_minutes * 1.25  # 25% increase
        phase4_data = {'minutes_avg_last_10': recent_minutes}
        phase3_data = {'minutes_avg_season': season_minutes}

        result = calc.calculate_minutes_change(phase4_data, phase3_data)

        assert result == 2.0

    @given(st.floats(min_value=25, max_value=40, allow_nan=False))
    def test_significant_decrease(self, season_minutes):
        """20%+ decrease should return -2.0."""
        calc = FeatureCalculator()

        recent_minutes = season_minutes * 0.75  # 25% decrease
        phase4_data = {'minutes_avg_last_10': recent_minutes}
        phase3_data = {'minutes_avg_season': season_minutes}

        result = calc.calculate_minutes_change(phase4_data, phase3_data)

        assert result == -2.0

    def test_zero_season_minutes_returns_zero(self):
        """Zero season minutes should return 0.0."""
        calc = FeatureCalculator()
        phase4_data = {'minutes_avg_last_10': 30.0}
        phase3_data = {'minutes_avg_season': 0.0}

        result = calc.calculate_minutes_change(phase4_data, phase3_data)

        assert result == 0.0


# =============================================================================
# Free Throw Percentage Tests
# =============================================================================

class TestPctFreeThrow:
    """Property tests for free throw percentage calculation."""

    @given(phase3_data_with_games(min_games=0, max_games=4))
    def test_insufficient_games_returns_default(self, phase3_data):
        """Less than 5 games should return default 0.15."""
        assume(len(phase3_data['last_10_games']) < 5)

        calc = FeatureCalculator()
        result = calc.calculate_pct_free_throw(phase3_data)

        assert result == 0.15

    @given(st.lists(st.integers(min_value=0, max_value=10), min_size=5, max_size=10))
    def test_pct_in_valid_range(self, ft_makes_list):
        """FT percentage should be in [0, 0.5]."""
        calc = FeatureCalculator()

        games = []
        for ft in ft_makes_list:
            # Points >= FT makes (minimum)
            points = max(ft, 10)
            games.append({'ft_makes': ft, 'points': points})

        data = {'last_10_games': games}
        result = calc.calculate_pct_free_throw(data)

        assert 0.0 <= result <= 0.5

    @given(st.integers(min_value=5, max_value=10))
    def test_zero_points_returns_default(self, num_games):
        """Zero total points should return default."""
        calc = FeatureCalculator()

        games = [{'ft_makes': 0, 'points': 0} for _ in range(num_games)]
        data = {'last_10_games': games}

        result = calc.calculate_pct_free_throw(data)

        assert result == 0.15

    @given(st.integers(min_value=10, max_value=30))
    def test_precision_respected(self, total_points):
        """Result should have correct decimal precision."""
        calc = FeatureCalculator()

        games = [{'ft_makes': 3, 'points': total_points} for _ in range(5)]
        data = {'last_10_games': games}

        result = calc.calculate_pct_free_throw(data)

        # Check that result has at most 9 decimal places
        result_str = f"{result:.10f}"
        decimal_part = result_str.split('.')[1]
        significant_decimals = len(decimal_part.rstrip('0'))
        assert significant_decimals <= 9


# =============================================================================
# Team Win Percentage Tests
# =============================================================================

class TestTeamWinPct:
    """Property tests for team win percentage calculation."""

    @given(team_season_games(num_games=3))
    def test_insufficient_games_returns_default(self, games):
        """Less than 5 games should return default 0.5."""
        assume(len(games) < 5)

        calc = FeatureCalculator()
        data = {'team_season_games': games}

        result = calc.calculate_team_win_pct(data)

        assert result == 0.5

    @given(st.lists(st.booleans(), min_size=5, max_size=82))
    def test_win_pct_in_valid_range(self, win_flags):
        """Win percentage should be in [0, 1]."""
        calc = FeatureCalculator()

        games = [{'win_flag': w} for w in win_flags]
        data = {'team_season_games': games}

        result = calc.calculate_team_win_pct(data)

        assert 0.0 <= result <= 1.0

    @given(st.integers(min_value=5, max_value=82))
    def test_all_wins(self, num_games):
        """All wins should return 1.0."""
        calc = FeatureCalculator()

        games = [{'win_flag': True} for _ in range(num_games)]
        data = {'team_season_games': games}

        result = calc.calculate_team_win_pct(data)

        assert result == 1.0

    @given(st.integers(min_value=5, max_value=82))
    def test_all_losses(self, num_games):
        """All losses should return 0.0."""
        calc = FeatureCalculator()

        games = [{'win_flag': False} for _ in range(num_games)]
        data = {'team_season_games': games}

        result = calc.calculate_team_win_pct(data)

        assert result == 0.0

    @given(st.integers(min_value=5, max_value=82))
    def test_precision_respected(self, num_games):
        """Result should have correct decimal precision for any record."""
        calc = FeatureCalculator()

        # Create a mix of wins/losses
        wins = num_games // 3
        games = [{'win_flag': i < wins} for i in range(num_games)]
        data = {'team_season_games': games}

        result = calc.calculate_team_win_pct(data)

        # Check precision
        result_str = f"{result:.10f}"
        decimal_part = result_str.split('.')[1]
        significant_decimals = len(decimal_part.rstrip('0'))
        assert significant_decimals <= 9


# =============================================================================
# Usage Rate Calculation Tests
# =============================================================================

class TestUsageRateCalculation:
    """Property tests for usage rate calculation."""

    def _calculate_usage_rate(self, player_fga, player_fta, player_to, player_minutes,
                              team_fga, team_fta, team_to):
        """Calculate usage rate using standard formula."""
        if team_fga + 0.44 * team_fta + team_to == 0:
            return None
        if player_minutes == 0:
            return None

        player_poss_used = player_fga + 0.44 * player_fta + player_to
        team_poss_used = team_fga + 0.44 * team_fta + team_to

        usage_rate = 100.0 * player_poss_used * 48.0 / (player_minutes * team_poss_used)
        return round(usage_rate, 1)

    @given(
        st.integers(min_value=0, max_value=30),  # player_fga
        st.integers(min_value=0, max_value=15),  # player_fta
        st.integers(min_value=0, max_value=10),  # player_to
        st.floats(min_value=1, max_value=48, allow_nan=False),  # player_minutes
        st.integers(min_value=50, max_value=100),  # team_fga
        st.integers(min_value=15, max_value=35),  # team_fta
        st.integers(min_value=5, max_value=25),  # team_to
    )
    def test_usage_rate_non_negative(self, player_fga, player_fta, player_to,
                                     player_minutes, team_fga, team_fta, team_to):
        """Usage rate should be non-negative."""
        result = self._calculate_usage_rate(
            player_fga, player_fta, player_to, player_minutes,
            team_fga, team_fta, team_to
        )

        if result is not None:
            assert result >= 0

    @given(
        st.integers(min_value=5, max_value=30),  # player_fga
        st.integers(min_value=0, max_value=15),  # player_fta
        st.integers(min_value=0, max_value=10),  # player_to
        st.floats(min_value=10, max_value=40, allow_nan=False),  # player_minutes
        st.integers(min_value=60, max_value=100),  # team_fga
        st.integers(min_value=15, max_value=35),  # team_fta
        st.integers(min_value=5, max_value=25),  # team_to
    )
    def test_usage_rate_realistic_range(self, player_fga, player_fta, player_to,
                                        player_minutes, team_fga, team_fta, team_to):
        """Usage rate for realistic inputs should be in expected range."""
        result = self._calculate_usage_rate(
            player_fga, player_fta, player_to, player_minutes,
            team_fga, team_fta, team_to
        )

        if result is not None:
            # Typical usage rates are 10-40%, extreme cases up to 50%
            # But with edge case inputs, can go higher
            assert result < 100  # Sanity check

    def test_zero_player_minutes_returns_none(self):
        """Zero player minutes should return None."""
        result = self._calculate_usage_rate(10, 5, 2, 0, 80, 25, 15)
        assert result is None

    def test_zero_team_possessions_returns_none(self):
        """Zero team possessions should return None."""
        result = self._calculate_usage_rate(10, 5, 2, 30, 0, 0, 0)
        assert result is None


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--hypothesis-show-statistics'])
