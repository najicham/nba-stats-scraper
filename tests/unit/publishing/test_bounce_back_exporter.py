"""
Unit Tests for BounceBackExporter

Tests cover:
1. Bounce-back rate calculation
2. Shortfall detection (10+ points below average)
3. Significance classification (high >= 70% with 10+ samples, medium >= 60% with 5+ samples)
4. Empty data handling
5. Mock BigQuery responses
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.bounce_back_exporter import BounceBackExporter


class MockBigQueryClient:
    """Mock BigQuery client for testing"""

    def __init__(self):
        self.query_results = []
        self.query_calls = []

    def query(self, sql, job_config=None):
        """Mock query execution"""
        self.query_calls.append({'sql': sql, 'config': job_config})
        mock_result = Mock()
        mock_result.result.return_value = self.query_results
        return mock_result

    def set_results(self, results):
        """Set results to return from next query"""
        self.query_results = results


class TestBounceBackExporterInit:
    """Test suite for initialization"""

    def test_initialization_defaults(self):
        """Test that exporter initializes with defaults"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BounceBackExporter()

                assert exporter.DEFAULT_SHORTFALL_THRESHOLD == 10
                assert exporter.MIN_BOUNCE_BACK_SAMPLE == 3


class TestBounceBackRateCalculation:
    """Test suite for bounce-back rate calculation"""

    def test_high_bounce_back_rate(self):
        """Test player with high historical bounce-back rate"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Player who bounces back 11 out of 14 bad games
                mock_client.set_results([
                    {
                        'player_lookup': 'curry',
                        'player_name': 'Stephen Curry',
                        'team': 'GSW',
                        'last_game_date': date(2024, 12, 14),
                        'last_game_points': 12,
                        'last_game_opponent': 'LAL',
                        'season_average': 26.5,
                        'shortfall': 14.5,
                        'bounce_back_rate': 0.786,  # 11/14 = 78.6%
                        'bounce_back_sample': 14,
                        'significance': 'high'  # >= 70% with 10+ samples
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter._query_bounce_back_candidates('2024-12-15', 10)

                assert len(result) == 1
                assert result[0]['bounce_back_rate'] == 0.786
                assert result[0]['bounce_back_sample'] == 14
                assert result[0]['significance'] == 'high'

    def test_medium_bounce_back_rate(self):
        """Test player with medium significance bounce-back rate"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Player with 60% bounce-back rate on 5 samples
                mock_client.set_results([
                    {
                        'player_lookup': 'player',
                        'player_name': 'Player Name',
                        'team': 'BOS',
                        'last_game_date': date(2024, 12, 14),
                        'last_game_points': 8,
                        'last_game_opponent': 'MIA',
                        'season_average': 18.5,
                        'shortfall': 10.5,
                        'bounce_back_rate': 0.600,  # 3/5
                        'bounce_back_sample': 5,
                        'significance': 'medium'  # >= 60% with 5+ samples
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter._query_bounce_back_candidates('2024-12-15', 10)

                assert result[0]['significance'] == 'medium'
                assert result[0]['bounce_back_rate'] == 0.600
                assert result[0]['bounce_back_sample'] == 5

    def test_low_bounce_back_rate(self):
        """Test player with low significance bounce-back rate"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Player with insufficient sample or low rate
                mock_client.set_results([
                    {
                        'player_lookup': 'rookie',
                        'player_name': 'Rookie Player',
                        'team': 'ORL',
                        'last_game_date': date(2024, 12, 14),
                        'last_game_points': 5,
                        'last_game_opponent': 'ATL',
                        'season_average': 15.5,
                        'shortfall': 10.5,
                        'bounce_back_rate': 0.333,  # 1/3
                        'bounce_back_sample': 3,
                        'significance': 'low'  # < 60% or < 5 samples
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter._query_bounce_back_candidates('2024-12-15', 10)

                assert result[0]['significance'] == 'low'

    def test_default_bounce_back_rate_when_no_history(self):
        """Test that players with no history get 0.5 default rate"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Player with no historical bounce-back data
                mock_client.set_results([
                    {
                        'player_lookup': 'new',
                        'player_name': 'New Player',
                        'team': 'CHA',
                        'last_game_date': date(2024, 12, 14),
                        'last_game_points': 2,
                        'last_game_opponent': 'NYK',
                        'season_average': 12.0,
                        'shortfall': 10.0,
                        'bounce_back_rate': 0.5,  # Default when no history
                        'bounce_back_sample': 0,
                        'significance': 'low'
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter._query_bounce_back_candidates('2024-12-15', 10)

                assert result[0]['bounce_back_rate'] == 0.5
                assert result[0]['bounce_back_sample'] == 0


class TestShortfallDetection:
    """Test suite for shortfall threshold detection"""

    def test_exact_threshold_shortfall(self):
        """Test player with exactly 10 point shortfall"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'player',
                        'player_name': 'Player',
                        'team': 'DEN',
                        'last_game_date': date(2024, 12, 14),
                        'last_game_points': 15,
                        'last_game_opponent': 'LAC',
                        'season_average': 25.0,
                        'shortfall': 10.0,  # Exactly at threshold
                        'bounce_back_rate': 0.7,
                        'bounce_back_sample': 10,
                        'significance': 'high'
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter._query_bounce_back_candidates('2024-12-15', 10)

                assert result[0]['shortfall'] == 10.0

    def test_large_shortfall(self):
        """Test player with very large shortfall"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'bad_game',
                        'player_name': 'Bad Game Player',
                        'team': 'PHX',
                        'last_game_date': date(2024, 12, 14),
                        'last_game_points': 5,
                        'last_game_opponent': 'DAL',
                        'season_average': 28.0,
                        'shortfall': 23.0,  # Very bad game
                        'bounce_back_rate': 0.8,
                        'bounce_back_sample': 5,
                        'significance': 'medium'
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter._query_bounce_back_candidates('2024-12-15', 10)

                assert result[0]['shortfall'] == 23.0

    def test_custom_shortfall_threshold(self):
        """Test using custom shortfall threshold"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'player',
                        'player_name': 'Player',
                        'team': 'MIL',
                        'last_game_date': date(2024, 12, 14),
                        'last_game_points': 15,
                        'last_game_opponent': 'IND',
                        'season_average': 20.0,
                        'shortfall': 5.0,  # Below 10 but above custom threshold of 5
                        'bounce_back_rate': 0.65,
                        'bounce_back_sample': 8,
                        'significance': 'medium'
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                # Query with custom threshold of 5
                result = exporter._query_bounce_back_candidates('2024-12-15', 5)

                assert result[0]['shortfall'] == 5.0


class TestLeagueBaseline:
    """Test suite for league baseline calculation"""

    def test_league_baseline_calculated(self):
        """Test that league-wide baseline is calculated correctly"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # League-wide stats: 770 bounced back out of 1234 bad games
                mock_client.set_results([
                    {
                        'total_bad_games': 1234,
                        'bounced_back': 770,
                        'avg_bounce_back_rate': 0.624  # 770/1234 = 62.4%
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter._query_league_baseline('2024-12-15', 10)

                assert result['avg_bounce_back_rate'] == 0.624
                assert result['sample_size'] == 1234

    def test_league_baseline_empty_data(self):
        """Test league baseline with no data"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter._query_league_baseline('2024-12-15', 10)

                assert result['avg_bounce_back_rate'] is None
                assert result['sample_size'] == 0


class TestEmptyDataHandling:
    """Test suite for empty data scenarios"""

    def test_empty_candidates_list(self):
        """Test that empty results are handled gracefully"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter.generate_json('2024-12-15')

                assert result['total_candidates'] == 0
                assert result['bounce_back_candidates'] == []


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_complete(self):
        """Test complete JSON generation"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Set up multiple calls for candidates and baseline
                candidates = [
                    {
                        'player_lookup': 'player1',
                        'player_name': 'Player One',
                        'team': 'LAL',
                        'last_game_date': date(2024, 12, 14),
                        'last_game_points': 10,
                        'last_game_opponent': 'BOS',
                        'season_average': 25.0,
                        'shortfall': 15.0,
                        'bounce_back_rate': 0.8,
                        'bounce_back_sample': 15,
                        'significance': 'high'
                    },
                    {
                        'player_lookup': 'player2',
                        'player_name': 'Player Two',
                        'team': 'MIA',
                        'last_game_date': date(2024, 12, 14),
                        'last_game_points': 8,
                        'last_game_opponent': 'NYK',
                        'season_average': 20.0,
                        'shortfall': 12.0,
                        'bounce_back_rate': 0.65,
                        'bounce_back_sample': 8,
                        'significance': 'medium'
                    }
                ]

                baseline = {
                    'avg_bounce_back_rate': 0.62,
                    'sample_size': 1200
                }

                # Mock will be called twice (candidates then baseline)
                call_count = [0]

                def mock_query(sql, job_config=None):
                    result = Mock()
                    if call_count[0] == 0:
                        result.result.return_value = candidates
                    else:
                        result.result.return_value = [
                            {
                                'total_bad_games': baseline['sample_size'],
                                'bounced_back': int(baseline['sample_size'] * baseline['avg_bounce_back_rate']),
                                'avg_bounce_back_rate': baseline['avg_bounce_back_rate']
                            }
                        ]
                    call_count[0] += 1
                    return result

                mock_client.query = mock_query
                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter.generate_json('2024-12-15')

                assert result['as_of_date'] == '2024-12-15'
                assert result['total_candidates'] == 2
                assert len(result['bounce_back_candidates']) == 2
                assert result['bounce_back_candidates'][0]['rank'] == 1
                assert result['bounce_back_candidates'][1]['rank'] == 2
                assert result['league_baseline']['avg_bounce_back_rate'] == 0.62

    def test_generate_json_defaults(self):
        """Test default parameter usage"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter.generate_json(as_of_date='2024-12-15')

                assert result['as_of_date'] == '2024-12-15'
                assert result['shortfall_threshold'] == 10


class TestLastGameStructure:
    """Test suite for last_game nested structure"""

    def test_last_game_format(self):
        """Test that last_game is properly formatted as nested dict"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                mock_client.set_results([
                    {
                        'player_lookup': 'test',
                        'player_name': 'Test Player',
                        'team': 'TOR',
                        'last_game_date': date(2024, 12, 14),
                        'last_game_points': 15,
                        'last_game_opponent': 'BKN',
                        'season_average': 25.5,
                        'shortfall': 10.5,
                        'bounce_back_rate': 0.7,
                        'bounce_back_sample': 10,
                        'significance': 'high'
                    }
                ])

                mock_bq.return_value = mock_client
                exporter = BounceBackExporter()

                result = exporter._query_bounce_back_candidates('2024-12-15', 10)

                # Check new field names
                assert result[0]['player_full_name'] == 'Test Player'
                assert result[0]['team_abbr'] == 'TOR'

                last_game = result[0]['last_game']
                assert isinstance(last_game, dict)
                assert last_game['date'] == '2024-12-14'
                assert last_game['result'] == 15  # renamed from 'points'
                assert last_game['opponent'] == 'BKN'
                assert last_game['margin'] == -10.5  # negative shortfall


class TestSafeFloat:
    """Test suite for _safe_float utility method"""

    def test_safe_float_valid(self):
        """Test valid float conversion"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BounceBackExporter()

                assert exporter._safe_float(0.12345) == 0.123
                assert exporter._safe_float(25.5) == 25.5

    def test_safe_float_none(self):
        """Test None handling"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BounceBackExporter()

                assert exporter._safe_float(None) is None


class TestTonightGameEnrichment:
    """Test suite for playing_tonight enrichment"""

    def test_enrich_with_tonight_playing(self):
        """Test player whose team is playing tonight"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BounceBackExporter()

                candidate = {
                    'player_lookup': 'lebron',
                    'player_full_name': 'LeBron James',
                    'team_abbr': 'LAL',
                    'shortfall': 12.0
                }

                tonight_games = {
                    'LAL': {'opponent': 'GSW', 'game_time': '7:30 PM ET', 'home': True},
                    'GSW': {'opponent': 'LAL', 'game_time': '7:30 PM ET', 'home': False}
                }

                exporter._enrich_with_tonight(candidate, tonight_games)

                assert candidate['playing_tonight'] is True
                assert candidate['tonight']['opponent'] == 'GSW'
                assert candidate['tonight']['game_time'] == '7:30 PM ET'
                assert candidate['tonight']['home'] is True

    def test_enrich_with_tonight_not_playing(self):
        """Test player whose team is not playing tonight"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BounceBackExporter()

                candidate = {
                    'player_lookup': 'curry',
                    'player_full_name': 'Stephen Curry',
                    'team_abbr': 'GSW',
                    'shortfall': 15.0
                }

                tonight_games = {
                    'LAL': {'opponent': 'BOS', 'game_time': '8:00 PM ET', 'home': True},
                    'BOS': {'opponent': 'LAL', 'game_time': '8:00 PM ET', 'home': False}
                }

                exporter._enrich_with_tonight(candidate, tonight_games)

                assert candidate['playing_tonight'] is False
                assert candidate['tonight'] is None


class TestFormatGameTime:
    """Test suite for _format_game_time utility method"""

    def test_format_game_time_valid(self):
        """Test valid ISO time formatting"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BounceBackExporter()

                # Test ISO format with timezone
                result = exporter._format_game_time('2024-12-15T19:30:00-05:00')
                assert result == '7:30 PM ET'

    def test_format_game_time_none(self):
        """Test None handling"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BounceBackExporter()

                assert exporter._format_game_time(None) is None

    def test_format_game_time_invalid(self):
        """Test invalid format returns None"""
        with patch('data_processors.publishing.bounce_back_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = BounceBackExporter()

                assert exporter._format_game_time('not a date') is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
