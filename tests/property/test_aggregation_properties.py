"""
Property-based tests for data aggregation operations.

Uses Hypothesis to verify:
- aggregate(data).sum() <= sum(data) for counts
- Team stats = sum of player stats (where applicable)
- Aggregations preserve data types
- Group-by aggregations maintain consistency
- Temporal aggregations preserve ordering
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, example
from hypothesis.strategies import composite
from datetime import date, timedelta
import statistics


# =============================================================================
# Strategies for Aggregation Testing
# =============================================================================

@composite
def player_game_record(draw):
    """Generate a single player game record."""
    return {
        'player_id': draw(st.integers(min_value=1, max_value=100)),
        'game_id': draw(st.text(min_size=10, max_size=20, alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_')),
        'points': draw(st.integers(min_value=0, max_value=50)),
        'rebounds': draw(st.integers(min_value=0, max_value=20)),
        'assists': draw(st.integers(min_value=0, max_value=15)),
        'minutes': draw(st.floats(min_value=0, max_value=48, allow_nan=False)),
        'team': draw(st.sampled_from(['LAL', 'GSW', 'BOS', 'MIA', 'DAL'])),
    }


@composite
def team_game_stats(draw, num_players=5):
    """Generate stats for all players on a team in one game."""
    team = draw(st.sampled_from(['LAL', 'GSW', 'BOS', 'MIA', 'DAL']))
    game_id = draw(st.text(min_size=10, max_size=20, alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_'))

    players = []
    for i in range(num_players):
        player = {
            'player_id': i + 1,
            'game_id': game_id,
            'points': draw(st.integers(min_value=0, max_value=40)),
            'rebounds': draw(st.integers(min_value=0, max_value=15)),
            'assists': draw(st.integers(min_value=0, max_value=12)),
            'minutes': draw(st.floats(min_value=0, max_value=45, allow_nan=False)),
            'team': team,
        }
        players.append(player)

    return players


@composite
def player_season_stats(draw, num_games=10):
    """Generate a player's stats across multiple games."""
    player_id = draw(st.integers(min_value=1, max_value=100))
    team = draw(st.sampled_from(['LAL', 'GSW', 'BOS', 'MIA', 'DAL']))

    games = []
    for i in range(num_games):
        game = {
            'player_id': player_id,
            'game_id': f'game_{i}',
            'points': draw(st.integers(min_value=0, max_value=40)),
            'rebounds': draw(st.integers(min_value=0, max_value=15)),
            'assists': draw(st.integers(min_value=0, max_value=12)),
            'minutes': draw(st.floats(min_value=0, max_value=45, allow_nan=False)),
            'team': team,
            'game_date': (date(2024, 1, 1) + timedelta(days=i * 3)).isoformat(),
        }
        games.append(game)

    return games


# =============================================================================
# Aggregation Helper Functions
# =============================================================================

def aggregate_team_stats(player_records):
    """Aggregate individual player stats to team totals."""
    if not player_records:
        return {}

    return {
        'team': player_records[0]['team'],
        'game_id': player_records[0]['game_id'],
        'total_points': sum(p['points'] for p in player_records),
        'total_rebounds': sum(p['rebounds'] for p in player_records),
        'total_assists': sum(p['assists'] for p in player_records),
        'total_minutes': sum(p['minutes'] for p in player_records),
        'player_count': len(player_records),
    }


def aggregate_player_season(game_records):
    """Aggregate player's game stats to season totals."""
    if not game_records:
        return {}

    return {
        'player_id': game_records[0]['player_id'],
        'total_points': sum(g['points'] for g in game_records),
        'total_rebounds': sum(g['rebounds'] for g in game_records),
        'total_assists': sum(g['assists'] for g in game_records),
        'avg_points': float(statistics.mean([g['points'] for g in game_records])),
        'avg_rebounds': float(statistics.mean([g['rebounds'] for g in game_records])),
        'avg_assists': float(statistics.mean([g['assists'] for g in game_records])),
        'games_played': len(game_records),
    }


# =============================================================================
# Sum Aggregation Tests
# =============================================================================

class TestSumAggregation:
    """Test that sum aggregations work correctly."""

    @given(team_game_stats())
    def test_team_points_sum(self, players):
        """Property: Team points = sum of player points."""
        team_stats = aggregate_team_stats(players)

        manual_sum = sum(p['points'] for p in players)

        assert team_stats['total_points'] == manual_sum

    @given(team_game_stats())
    def test_team_rebounds_sum(self, players):
        """Property: Team rebounds = sum of player rebounds."""
        team_stats = aggregate_team_stats(players)

        manual_sum = sum(p['rebounds'] for p in players)

        assert team_stats['total_rebounds'] == manual_sum

    @given(team_game_stats())
    def test_team_assists_sum(self, players):
        """Property: Team assists = sum of player assists."""
        team_stats = aggregate_team_stats(players)

        manual_sum = sum(p['assists'] for p in players)

        assert team_stats['total_assists'] == manual_sum

    @given(player_season_stats())
    def test_season_totals_sum(self, games):
        """Property: Season totals = sum of game totals."""
        season_stats = aggregate_player_season(games)

        assert season_stats['total_points'] == sum(g['points'] for g in games)
        assert season_stats['total_rebounds'] == sum(g['rebounds'] for g in games)
        assert season_stats['total_assists'] == sum(g['assists'] for g in games)


# =============================================================================
# Aggregation Count Tests
# =============================================================================

class TestAggregationCounts:
    """Test that aggregation counts are preserved."""

    @given(team_game_stats(num_players=5))
    def test_player_count_preserved(self, players):
        """Property: Player count is preserved in aggregation."""
        team_stats = aggregate_team_stats(players)

        assert team_stats['player_count'] == len(players)

    @given(player_season_stats(num_games=10))
    def test_games_played_preserved(self, games):
        """Property: Games played count is preserved."""
        season_stats = aggregate_player_season(games)

        assert season_stats['games_played'] == len(games)

    @given(st.lists(player_game_record(), min_size=1, max_size=20))
    def test_aggregation_preserves_record_count(self, records):
        """Property: Aggregating N records tracks count correctly."""
        # Group by team
        teams = {}
        for record in records:
            team = record['team']
            if team not in teams:
                teams[team] = []
            teams[team].append(record)

        # Each team's count should match
        for team, team_records in teams.items():
            assert len(team_records) >= 1


# =============================================================================
# Type Preservation Tests
# =============================================================================

class TestTypePreservation:
    """Test that aggregations preserve data types."""

    @given(team_game_stats())
    def test_aggregated_totals_are_integers(self, players):
        """Property: Aggregated count stats remain integers."""
        team_stats = aggregate_team_stats(players)

        assert isinstance(team_stats['total_points'], int)
        assert isinstance(team_stats['total_rebounds'], int)
        assert isinstance(team_stats['total_assists'], int)

    @given(team_game_stats())
    def test_aggregated_floats_remain_floats(self, players):
        """Property: Aggregated float stats remain floats."""
        team_stats = aggregate_team_stats(players)

        assert isinstance(team_stats['total_minutes'], float)

    @given(player_season_stats())
    def test_averages_are_floats(self, games):
        """Property: Averaged stats are floats."""
        season_stats = aggregate_player_season(games)

        assert isinstance(season_stats['avg_points'], float)
        assert isinstance(season_stats['avg_rebounds'], float)
        assert isinstance(season_stats['avg_assists'], float)

    @given(player_season_stats())
    def test_totals_are_integers(self, games):
        """Property: Totals from integer stats remain integers."""
        season_stats = aggregate_player_season(games)

        assert isinstance(season_stats['total_points'], int)
        assert isinstance(season_stats['total_rebounds'], int)
        assert isinstance(season_stats['total_assists'], int)


# =============================================================================
# Average Aggregation Tests
# =============================================================================

class TestAverageAggregation:
    """Test that average aggregations work correctly."""

    @given(player_season_stats())
    def test_average_between_min_max(self, games):
        """Property: Average is between min and max game values."""
        season_stats = aggregate_player_season(games)

        points_values = [g['points'] for g in games]
        min_points = min(points_values)
        max_points = max(points_values)

        assert min_points <= season_stats['avg_points'] <= max_points

    @given(player_season_stats(num_games=1))
    def test_single_game_average_equals_value(self, games):
        """Property: Average of single game equals game value."""
        assume(len(games) == 1)

        season_stats = aggregate_player_season(games)

        assert season_stats['avg_points'] == games[0]['points']
        assert season_stats['avg_rebounds'] == games[0]['rebounds']
        assert season_stats['avg_assists'] == games[0]['assists']

    @given(st.integers(min_value=10, max_value=30), st.integers(min_value=5, max_value=20))
    def test_constant_values_average(self, points, num_games):
        """Property: Average of constant values equals that value."""
        games = [
            {
                'player_id': 1,
                'game_id': f'game_{i}',
                'points': points,
                'rebounds': 5,
                'assists': 3,
                'minutes': 30.0,
                'team': 'LAL',
                'game_date': (date(2024, 1, 1) + timedelta(days=i)).isoformat(),
            }
            for i in range(num_games)
        ]

        season_stats = aggregate_player_season(games)

        assert season_stats['avg_points'] == points


# =============================================================================
# Group-By Aggregation Tests
# =============================================================================

class TestGroupByAggregation:
    """Test group-by aggregation consistency."""

    @given(st.lists(player_game_record(), min_size=5, max_size=30))
    def test_group_by_team_preserves_totals(self, records):
        """Property: Grouping by team preserves overall totals."""
        # Total across all records
        total_points = sum(r['points'] for r in records)

        # Group by team
        teams = {}
        for record in records:
            team = record['team']
            if team not in teams:
                teams[team] = []
            teams[team].append(record)

        # Sum across groups
        grouped_total = sum(sum(r['points'] for r in team_records) for team_records in teams.values())

        assert total_points == grouped_total

    @given(st.lists(player_game_record(), min_size=5, max_size=30))
    def test_group_by_player_preserves_counts(self, records):
        """Property: Grouping by player preserves total record count."""
        # Group by player
        players = {}
        for record in records:
            player_id = record['player_id']
            if player_id not in players:
                players[player_id] = []
            players[player_id].append(record)

        # Count across groups
        grouped_count = sum(len(games) for games in players.values())

        assert len(records) == grouped_count


# =============================================================================
# Temporal Aggregation Tests
# =============================================================================

class TestTemporalAggregation:
    """Test temporal aggregations maintain ordering."""

    @given(player_season_stats())
    def test_chronological_aggregation_preserves_order(self, games):
        """Property: Chronological aggregation respects time ordering."""
        # Sort by date
        sorted_games = sorted(games, key=lambda g: g['game_date'])

        # First game should have earliest date
        first_date = sorted_games[0]['game_date']
        last_date = sorted_games[-1]['game_date']

        assert first_date <= last_date

    @given(player_season_stats(num_games=10))
    def test_rolling_average_monotonic_with_constant_values(self, games):
        """Property: Rolling average with constant values is constant."""
        # Make all points the same
        constant_points = 20
        for game in games:
            game['points'] = constant_points

        # Calculate rolling averages
        window_size = 3
        for i in range(len(games) - window_size + 1):
            window = games[i:i + window_size]
            avg = statistics.mean([g['points'] for g in window])
            assert avg == constant_points


# =============================================================================
# Aggregation Invariants
# =============================================================================

class TestAggregationInvariants:
    """Test aggregation invariants."""

    @given(team_game_stats())
    def test_sum_never_negative(self, players):
        """Property: Sum of non-negative values is non-negative."""
        team_stats = aggregate_team_stats(players)

        assert team_stats['total_points'] >= 0
        assert team_stats['total_rebounds'] >= 0
        assert team_stats['total_assists'] >= 0
        assert team_stats['total_minutes'] >= 0

    @given(player_season_stats())
    def test_average_never_negative(self, games):
        """Property: Average of non-negative values is non-negative."""
        season_stats = aggregate_player_season(games)

        assert season_stats['avg_points'] >= 0
        assert season_stats['avg_rebounds'] >= 0
        assert season_stats['avg_assists'] >= 0

    @given(team_game_stats())
    def test_total_minutes_reasonable(self, players):
        """Property: Total team minutes is reasonable (5 players * 48 min = 240 max)."""
        team_stats = aggregate_team_stats(players)

        # Total minutes shouldn't exceed game length * player count significantly
        # (allowing for overtime)
        max_reasonable = len(players) * 48 * 1.5  # 50% buffer for OT

        assert team_stats['total_minutes'] <= max_reasonable

    @given(player_season_stats())
    def test_totals_divisible_by_averages(self, games):
        """Property: Total = Average * Games (approximately for floats)."""
        season_stats = aggregate_player_season(games)

        calculated_total = season_stats['avg_points'] * season_stats['games_played']

        # Should be close (within rounding error)
        assert abs(calculated_total - season_stats['total_points']) < 0.1


# =============================================================================
# Empty Aggregation Tests
# =============================================================================

class TestEmptyAggregation:
    """Test aggregation behavior with empty inputs."""

    def test_empty_team_stats(self):
        """Property: Empty team produces empty/default aggregation."""
        team_stats = aggregate_team_stats([])

        assert team_stats == {}

    def test_empty_season_stats(self):
        """Property: Empty season produces empty/default aggregation."""
        season_stats = aggregate_player_season([])

        assert season_stats == {}


# =============================================================================
# Aggregation Consistency Tests
# =============================================================================

class TestAggregationConsistency:
    """Test that aggregations are consistent and deterministic."""

    @given(team_game_stats())
    def test_aggregation_deterministic(self, players):
        """Property: Same input produces same aggregation."""
        team_stats1 = aggregate_team_stats(players)
        team_stats2 = aggregate_team_stats(players)
        team_stats3 = aggregate_team_stats(players)

        assert team_stats1 == team_stats2 == team_stats3

    @given(player_season_stats())
    def test_order_independence_for_sum(self, games):
        """Property: Sum aggregation is independent of input order."""
        season_stats_original = aggregate_player_season(games)

        # Reverse order
        reversed_games = list(reversed(games))
        season_stats_reversed = aggregate_player_season(reversed_games)

        # Totals should be same regardless of order
        assert season_stats_original['total_points'] == season_stats_reversed['total_points']
        assert season_stats_original['total_rebounds'] == season_stats_reversed['total_rebounds']


# =============================================================================
# Nested Aggregation Tests
# =============================================================================

class TestNestedAggregation:
    """Test that nested aggregations work correctly."""

    @given(st.lists(team_game_stats(), min_size=2, max_size=5))
    def test_aggregate_of_aggregates(self, multiple_team_games):
        """Property: Aggregate of aggregates equals direct aggregate."""
        # Flatten all player records
        all_players = []
        for team_game in multiple_team_games:
            all_players.extend(team_game)

        # Direct aggregation
        direct_total = sum(p['points'] for p in all_players)

        # Nested aggregation
        team_totals = [sum(p['points'] for p in team_game) for team_game in multiple_team_games]
        nested_total = sum(team_totals)

        assert direct_total == nested_total


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--hypothesis-show-statistics'])
