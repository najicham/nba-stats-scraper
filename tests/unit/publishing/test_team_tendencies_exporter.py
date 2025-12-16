"""
Unit Tests for TeamTendenciesExporter

Tests cover:
1. Pace tendencies (fastest/slowest teams)
2. Defense by zone (paint, perimeter)
3. Home/away splits
4. Back-to-back impact
5. Empty data handling
6. Mock BigQuery responses
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.team_tendencies_exporter import TeamTendenciesExporter


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


class TestTeamTendenciesExporterInit:
    """Test suite for initialization"""

    def test_initialization_defaults(self):
        """Test that exporter initializes correctly"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TeamTendenciesExporter()

                assert exporter.project_id == 'nba-props-platform'


class TestPaceTendencies:
    """Test suite for pace tendency analysis"""

    def test_pace_kings_identified(self):
        """Test that fastest pace teams are identified"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                pace_data = [
                    {'team_abbr': 'SAC', 'avg_pace': 104.5, 'games': 10, 'avg_points': 118.5, 'vs_league': 5.3},
                    {'team_abbr': 'IND', 'avg_pace': 103.2, 'games': 10, 'avg_points': 116.2, 'vs_league': 4.0},
                    {'team_abbr': 'BOS', 'avg_pace': 102.1, 'games': 10, 'avg_points': 115.8, 'vs_league': 2.9},
                    {'team_abbr': 'GSW', 'avg_pace': 101.5, 'games': 10, 'avg_points': 114.3, 'vs_league': 2.3},
                    {'team_abbr': 'MEM', 'avg_pace': 100.8, 'games': 10, 'avg_points': 113.1, 'vs_league': 1.6},
                    # Middle teams...
                    {'team_abbr': 'NYK', 'avg_pace': 94.2, 'games': 10, 'avg_points': 105.3, 'vs_league': -4.8},
                    {'team_abbr': 'MIA', 'avg_pace': 93.5, 'games': 10, 'avg_points': 104.2, 'vs_league': -5.5},
                ]

                mock_client.set_results(pace_data)
                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_pace_tendencies('2024-12-15')

                # Should have top 5 kings (fastest)
                assert len(result['kings']) == 5
                assert result['kings'][0]['team'] == 'SAC'
                assert result['kings'][0]['pace'] == 104.5
                assert result['kings'][0]['vs_league'] == 5.3

    def test_pace_grinders_identified(self):
        """Test that slowest pace teams are identified"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                pace_data = [
                    {'team_abbr': 'SAC', 'avg_pace': 104.5, 'games': 10, 'avg_points': 118.5, 'vs_league': 5.3},
                    # Middle teams...
                    {'team_abbr': 'CLE', 'avg_pace': 95.1, 'games': 10, 'avg_points': 106.8, 'vs_league': -4.1},
                    {'team_abbr': 'NYK', 'avg_pace': 94.2, 'games': 10, 'avg_points': 105.3, 'vs_league': -4.8},
                    {'team_abbr': 'MIA', 'avg_pace': 93.5, 'games': 10, 'avg_points': 104.2, 'vs_league': -5.5},
                    {'team_abbr': 'ORL', 'avg_pace': 92.8, 'games': 10, 'avg_points': 103.1, 'vs_league': -6.2},
                    {'team_abbr': 'DET', 'avg_pace': 91.5, 'games': 10, 'avg_points': 101.9, 'vs_league': -7.5},
                ]

                mock_client.set_results(pace_data)
                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_pace_tendencies('2024-12-15')

                # Should have bottom 5 grinders (slowest)
                assert len(result['grinders']) == 5
                assert result['grinders'][0]['team'] == 'DET'  # Slowest first
                assert result['grinders'][0]['pace'] == 91.5

    def test_pace_league_average_calculated(self):
        """Test that league average pace is calculated"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                pace_data = [
                    {'team_abbr': 'TEAM1', 'avg_pace': 100.0, 'games': 10, 'avg_points': 110.0, 'vs_league': 1.0},
                    {'team_abbr': 'TEAM2', 'avg_pace': 98.0, 'games': 10, 'avg_points': 108.0, 'vs_league': -1.0},
                ]

                mock_client.set_results(pace_data)
                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_pace_tendencies('2024-12-15')

                assert result['league_average'] == 99.0  # (100 + 98) / 2

    def test_pace_empty_data(self):
        """Test pace query with no data"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_pace_tendencies('2024-12-15')

                assert result['kings'] == []
                assert result['grinders'] == []


class TestDefenseByZone:
    """Test suite for defense by zone analysis"""

    def test_paint_defense_best(self):
        """Test identification of best paint defenses"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                defense_data = [
                    {
                        'team_abbr': 'BOS',
                        'paint_dfg': 0.485,  # Best (lowest)
                        'three_dfg': 0.355,
                        'mid_dfg': 0.410,
                        'opp_ppg': 105.2,
                        'games': 10
                    },
                    {
                        'team_abbr': 'MIA',
                        'paint_dfg': 0.492,
                        'three_dfg': 0.360,
                        'mid_dfg': 0.415,
                        'opp_ppg': 106.5,
                        'games': 10
                    },
                    {
                        'team_abbr': 'DET',
                        'paint_dfg': 0.595,  # Worst (highest)
                        'three_dfg': 0.385,
                        'mid_dfg': 0.455,
                        'opp_ppg': 118.3,
                        'games': 10
                    }
                ]

                mock_client.set_results(defense_data)
                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_defense_by_zone('2024-12-15')

                # Best paint defense should be BOS
                assert result['paint']['best'][0]['team'] == 'BOS'
                assert result['paint']['best'][0]['dfg_pct'] == 48.5  # Converted to percentage

    def test_paint_defense_worst(self):
        """Test identification of worst paint defenses"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                defense_data = [
                    {'team_abbr': 'BOS', 'paint_dfg': 0.485, 'three_dfg': 0.355, 'mid_dfg': 0.410, 'opp_ppg': 105.2, 'games': 10},
                    {'team_abbr': 'DET', 'paint_dfg': 0.595, 'three_dfg': 0.385, 'mid_dfg': 0.455, 'opp_ppg': 118.3, 'games': 10}
                ]

                mock_client.set_results(defense_data)
                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_defense_by_zone('2024-12-15')

                # Worst paint defense should be DET
                assert result['paint']['worst'][0]['team'] == 'DET'

    def test_perimeter_defense_best(self):
        """Test identification of best perimeter defenses"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                defense_data = [
                    {'team_abbr': 'CLE', 'paint_dfg': 0.510, 'three_dfg': 0.330, 'mid_dfg': 0.405, 'opp_ppg': 104.1, 'games': 10},
                    {'team_abbr': 'MEM', 'paint_dfg': 0.505, 'three_dfg': 0.335, 'mid_dfg': 0.410, 'opp_ppg': 105.8, 'games': 10}
                ]

                mock_client.set_results(defense_data)
                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_defense_by_zone('2024-12-15')

                # Best perimeter defense (lowest 3PT%)
                assert result['perimeter']['best'][0]['team'] == 'CLE'
                assert result['perimeter']['best'][0]['dfg_pct'] == 33.0

    def test_defense_empty_data(self):
        """Test defense query with no data"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_defense_by_zone('2024-12-15')

                assert result['paint']['best'] == []
                assert result['paint']['worst'] == []
                assert result['perimeter']['best'] == []
                assert result['perimeter']['worst'] == []


class TestHomeAwaySplits:
    """Test suite for home/away splits analysis"""

    def test_home_dominant_teams(self):
        """Test identification of home-dominant teams"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                splits_data = [
                    {
                        'team_abbr': 'UTA',
                        'home_ppg': 118.5,
                        'away_ppg': 107.2,
                        'home_diff': 11.3,  # Large home advantage
                        'home_games': 10,
                        'away_games': 10
                    },
                    {
                        'team_abbr': 'DEN',
                        'home_ppg': 116.8,
                        'away_ppg': 108.5,
                        'home_diff': 8.3,
                        'home_games': 10,
                        'away_games': 10
                    }
                ]

                mock_client.set_results(splits_data)
                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_home_away_splits('2024-12-15')

                assert len(result['home_dominant']) > 0
                assert result['home_dominant'][0]['team'] == 'UTA'
                assert result['home_dominant'][0]['differential'] == 11.3

    def test_road_warriors_teams(self):
        """Test identification of road warrior teams"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                splits_data = [
                    {
                        'team_abbr': 'MIL',
                        'home_ppg': 115.2,
                        'away_ppg': 114.8,
                        'home_diff': 0.4,  # Minimal home advantage
                        'home_games': 10,
                        'away_games': 10
                    },
                    {
                        'team_abbr': 'LAC',
                        'home_ppg': 113.5,
                        'away_ppg': 114.2,
                        'home_diff': -0.7,  # Actually better on road
                        'home_games': 10,
                        'away_games': 10
                    }
                ]

                mock_client.set_results(splits_data)
                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_home_away_splits('2024-12-15')

                # Road warriors should include LAC (negative or small differential)
                assert len(result['road_warriors']) > 0

    def test_home_away_empty_data(self):
        """Test home/away query with no data"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_home_away_splits('2024-12-15')

                assert result['home_dominant'] == []
                assert result['road_warriors'] == []


class TestBackToBackImpact:
    """Test suite for back-to-back impact analysis"""

    def test_b2b_vulnerable_teams(self):
        """Test identification of teams vulnerable on B2B"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                b2b_data = [
                    {
                        'team_abbr': 'LAL',
                        'b2b_ppg': 105.2,
                        'rested_ppg': 115.8,
                        'b2b_impact': -10.6,  # Large negative impact
                        'b2b_games': 5,
                        'rested_games': 15
                    },
                    {
                        'team_abbr': 'PHI',
                        'b2b_ppg': 108.5,
                        'rested_ppg': 116.2,
                        'b2b_impact': -7.7,
                        'b2b_games': 4,
                        'rested_games': 12
                    }
                ]

                mock_client.set_results(b2b_data)
                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_b2b_impact('2024-12-15')

                assert len(result['vulnerable']) > 0
                assert result['vulnerable'][0]['team'] == 'LAL'
                assert result['vulnerable'][0]['impact'] == -10.6

    def test_b2b_resilient_teams(self):
        """Test identification of teams resilient on B2B"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                b2b_data = [
                    {
                        'team_abbr': 'MIA',
                        'b2b_ppg': 114.5,
                        'rested_ppg': 113.2,
                        'b2b_impact': 1.3,  # Positive impact (better on B2B!)
                        'b2b_games': 6,
                        'rested_games': 14
                    },
                    {
                        'team_abbr': 'BOS',
                        'b2b_ppg': 115.8,
                        'rested_ppg': 116.1,
                        'b2b_impact': -0.3,  # Minimal impact
                        'b2b_games': 5,
                        'rested_games': 15
                    }
                ]

                mock_client.set_results(b2b_data)
                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_b2b_impact('2024-12-15')

                # Resilient teams should be those with best B2B performance
                assert len(result['resilient']) > 0

    def test_b2b_empty_data(self):
        """Test B2B query with no data"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter._query_b2b_impact('2024-12-15')

                assert result['vulnerable'] == []
                assert result['resilient'] == []


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_structure(self):
        """Test complete JSON structure"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter.generate_json('2024-12-15')

                assert 'generated_at' in result
                assert result['as_of_date'] == '2024-12-15'
                assert 'pace' in result
                assert 'defense_by_zone' in result
                assert 'home_away' in result
                assert 'back_to_back' in result

    def test_generate_json_defaults(self):
        """Test default parameter usage"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = TeamTendenciesExporter()

                result = exporter.generate_json(as_of_date='2024-12-15')

                assert result['as_of_date'] == '2024-12-15'


class TestSafeFloat:
    """Test suite for _safe_float utility method"""

    def test_safe_float_rounding(self):
        """Test float rounding to 2 decimal places"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TeamTendenciesExporter()

                assert exporter._safe_float(104.567) == 104.57
                assert exporter._safe_float(98.123) == 98.12

    def test_safe_float_none(self):
        """Test None handling"""
        with patch('data_processors.publishing.team_tendencies_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = TeamTendenciesExporter()

                assert exporter._safe_float(None) is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
