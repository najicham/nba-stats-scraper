"""
Unit Tests for WhatMattersExporter

Tests cover:
1. Archetype classification thresholds (star >= 22, scorer >= 15, rotation >= 8, role_player < 8)
2. Factor impact analysis (rest, home/away)
3. Empty data handling
4. Insight generation logic
5. Mock BigQuery responses
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.what_matters_exporter import WhatMattersExporter


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


class TestWhatMattersExporterInit:
    """Test suite for initialization"""

    def test_initialization_archetypes(self):
        """Test that archetype definitions are correct"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhatMattersExporter()

                assert exporter.ARCHETYPES['star']['min_ppg'] == 22
                assert exporter.ARCHETYPES['scorer']['min_ppg'] == 15
                assert exporter.ARCHETYPES['scorer']['max_ppg'] == 22
                assert exporter.ARCHETYPES['rotation']['min_ppg'] == 8
                assert exporter.ARCHETYPES['rotation']['max_ppg'] == 15
                assert exporter.ARCHETYPES['role_player']['max_ppg'] == 8


class TestArchetypeClassification:
    """Test suite for archetype classification thresholds"""

    def test_star_classification(self):
        """Test that 22+ PPG players are classified as stars"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Mock returns for all three queries (totals, rest, home_away)
                totals = [
                    {
                        'archetype': 'star',
                        'player_count': 35,
                        'total_games': 1200,
                        'overall_over_pct': 52.5
                    }
                ]

                call_count = [0]

                def mock_query(sql, job_config=None):
                    result = Mock()
                    if call_count[0] == 0:
                        result.result.return_value = totals
                    else:
                        result.result.return_value = []
                    call_count[0] += 1
                    return result

                mock_client.query = mock_query
                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter._query_archetype_factors('2024-12-15')

                assert 'star' in result
                assert result['star']['player_count'] == 35
                assert result['star']['overall_over_pct'] == 52.5

    def test_scorer_classification(self):
        """Test that 15-22 PPG players are classified as scorers"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                totals = [
                    {
                        'archetype': 'scorer',
                        'player_count': 65,
                        'total_games': 2200,
                        'overall_over_pct': 49.8
                    }
                ]

                call_count = [0]

                def mock_query(sql, job_config=None):
                    result = Mock()
                    if call_count[0] == 0:
                        result.result.return_value = totals
                    else:
                        result.result.return_value = []
                    call_count[0] += 1
                    return result

                mock_client.query = mock_query
                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter._query_archetype_factors('2024-12-15')

                assert result['scorer']['player_count'] == 65

    def test_rotation_classification(self):
        """Test that 8-15 PPG players are classified as rotation"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                totals = [
                    {
                        'archetype': 'rotation',
                        'player_count': 120,
                        'total_games': 4500,
                        'overall_over_pct': 48.2
                    }
                ]

                call_count = [0]

                def mock_query(sql, job_config=None):
                    result = Mock()
                    if call_count[0] == 0:
                        result.result.return_value = totals
                    else:
                        result.result.return_value = []
                    call_count[0] += 1
                    return result

                mock_client.query = mock_query
                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter._query_archetype_factors('2024-12-15')

                assert result['rotation']['player_count'] == 120

    def test_role_player_classification(self):
        """Test that <8 PPG players are classified as role_player"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                totals = [
                    {
                        'archetype': 'role_player',
                        'player_count': 200,
                        'total_games': 5000,
                        'overall_over_pct': 39.7
                    }
                ]

                call_count = [0]

                def mock_query(sql, job_config=None):
                    result = Mock()
                    if call_count[0] == 0:
                        result.result.return_value = totals
                    else:
                        result.result.return_value = []
                    call_count[0] += 1
                    return result

                mock_client.query = mock_query
                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter._query_archetype_factors('2024-12-15')

                assert result['role_player']['player_count'] == 200
                assert result['role_player']['overall_over_pct'] == 39.7


class TestRestFactors:
    """Test suite for rest factor analysis"""

    def test_back_to_back_factor(self):
        """Test back-to-back (0 rest days) factor"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                rest_data = [
                    {
                        'archetype': 'star',
                        'rest_category': 'b2b',
                        'games': 150,
                        'over_pct': 50.8
                    }
                ]

                call_count = [0]

                def mock_query(sql, job_config=None):
                    result = Mock()
                    if call_count[0] == 0:
                        result.result.return_value = []
                    elif call_count[0] == 1:
                        result.result.return_value = rest_data
                    else:
                        result.result.return_value = []
                    call_count[0] += 1
                    return result

                mock_client.query = mock_query
                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter._query_archetype_factors('2024-12-15')

                assert 'b2b' in result['star']['factors']['rest']
                assert result['star']['factors']['rest']['b2b']['games'] == 150
                assert result['star']['factors']['rest']['b2b']['over_pct'] == 50.8

    def test_one_day_rest_factor(self):
        """Test one day rest factor"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                rest_data = [
                    {
                        'archetype': 'scorer',
                        'rest_category': 'one_day',
                        'games': 500,
                        'over_pct': 49.5
                    }
                ]

                call_count = [0]

                def mock_query(sql, job_config=None):
                    result = Mock()
                    if call_count[0] == 0:
                        result.result.return_value = []
                    elif call_count[0] == 1:
                        result.result.return_value = rest_data
                    else:
                        result.result.return_value = []
                    call_count[0] += 1
                    return result

                mock_client.query = mock_query
                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter._query_archetype_factors('2024-12-15')

                assert 'one_day' in result['scorer']['factors']['rest']

    def test_rested_factor(self):
        """Test 2+ days rest factor"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                rest_data = [
                    {
                        'archetype': 'star',
                        'rest_category': 'rested',
                        'games': 200,
                        'over_pct': 48.6
                    }
                ]

                call_count = [0]

                def mock_query(sql, job_config=None):
                    result = Mock()
                    if call_count[0] == 0:
                        result.result.return_value = []
                    elif call_count[0] == 1:
                        result.result.return_value = rest_data
                    else:
                        result.result.return_value = []
                    call_count[0] += 1
                    return result

                mock_client.query = mock_query
                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter._query_archetype_factors('2024-12-15')

                assert 'rested' in result['star']['factors']['rest']


class TestHomeAwayFactors:
    """Test suite for home/away factor analysis"""

    def test_home_factor(self):
        """Test home game factor"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                home_away_data = [
                    {
                        'archetype': 'rotation',
                        'location': 'home',
                        'games': 600,
                        'over_pct': 52.3
                    }
                ]

                call_count = [0]

                def mock_query(sql, job_config=None):
                    result = Mock()
                    if call_count[0] <= 1:
                        result.result.return_value = []
                    elif call_count[0] == 2:
                        result.result.return_value = home_away_data
                    else:
                        result.result.return_value = []
                    call_count[0] += 1
                    return result

                mock_client.query = mock_query
                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter._query_archetype_factors('2024-12-15')

                assert 'home' in result['rotation']['factors']['home_away']
                assert result['rotation']['factors']['home_away']['home']['over_pct'] == 52.3

    def test_away_factor(self):
        """Test away game factor"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                home_away_data = [
                    {
                        'archetype': 'star',
                        'location': 'away',
                        'games': 400,
                        'over_pct': 48.9
                    }
                ]

                call_count = [0]

                def mock_query(sql, job_config=None):
                    result = Mock()
                    if call_count[0] <= 1:
                        result.result.return_value = []
                    elif call_count[0] == 2:
                        result.result.return_value = home_away_data
                    else:
                        result.result.return_value = []
                    call_count[0] += 1
                    return result

                mock_client.query = mock_query
                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter._query_archetype_factors('2024-12-15')

                assert 'away' in result['star']['factors']['home_away']


class TestInsightGeneration:
    """Test suite for insight generation logic"""

    def test_insight_archetype_comparison(self):
        """Test insight comparing star vs role player performance"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhatMattersExporter()

                archetypes = {
                    'star': {
                        'overall_over_pct': 52.5,
                        'factors': {'rest': {}, 'home_away': {}}
                    },
                    'role_player': {
                        'overall_over_pct': 39.7,
                        'factors': {'rest': {}, 'home_away': {}}
                    }
                }

                insights = exporter._generate_insights(archetypes)

                # Should generate insight about star outperforming role players
                assert len(insights) > 0
                star_insight = [i for i in insights if '52.5' in i and '39.7' in i]
                assert len(star_insight) > 0

    def test_insight_back_to_back_impact(self):
        """Test insight for B2B vs rested performance"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhatMattersExporter()

                archetypes = {
                    'star': {
                        'overall_over_pct': 50.0,
                        'factors': {
                            'rest': {
                                'b2b': {'over_pct': 50.8, 'games': 150},
                                'rested': {'over_pct': 48.6, 'games': 200}
                            },
                            'home_away': {}
                        }
                    }
                }

                insights = exporter._generate_insights(archetypes)

                # Should mention B2B performance
                b2b_insights = [i for i in insights if 'B2B' in i or 'back-to-back' in i.lower()]
                assert len(b2b_insights) > 0

    def test_insight_home_away_split(self):
        """Test insight for significant home/away differences"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhatMattersExporter()

                archetypes = {
                    'rotation': {
                        'overall_over_pct': 50.0,
                        'factors': {
                            'rest': {},
                            'home_away': {
                                'home': {'over_pct': 54.0, 'games': 600},
                                'away': {'over_pct': 46.0, 'games': 600}
                            }
                        }
                    }
                }

                insights = exporter._generate_insights(archetypes)

                # Should mention home/away performance
                home_insights = [i for i in insights if 'home' in i.lower() or 'road' in i.lower()]
                assert len(home_insights) > 0

    def test_insight_limit_to_five(self):
        """Test that insights are limited to 5"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhatMattersExporter()

                # Create archetypes that would generate many insights
                archetypes = {
                    'star': {
                        'overall_over_pct': 55.0,
                        'factors': {
                            'rest': {
                                'b2b': {'over_pct': 60.0, 'games': 150},
                                'rested': {'over_pct': 52.0, 'games': 200}
                            },
                            'home_away': {
                                'home': {'over_pct': 58.0, 'games': 400},
                                'away': {'over_pct': 52.0, 'games': 400}
                            }
                        }
                    },
                    'scorer': {
                        'overall_over_pct': 50.0,
                        'factors': {
                            'rest': {},
                            'home_away': {
                                'home': {'over_pct': 55.0, 'games': 600},
                                'away': {'over_pct': 45.0, 'games': 600}
                            }
                        }
                    },
                    'role_player': {
                        'overall_over_pct': 40.0,
                        'factors': {'rest': {}, 'home_away': {}}
                    }
                }

                insights = exporter._generate_insights(archetypes)

                # Should be limited to 5
                assert len(insights) <= 5

    def test_default_insight_when_no_patterns(self):
        """Test that default insight is provided when no significant patterns"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhatMattersExporter()

                archetypes = {
                    'star': {
                        'overall_over_pct': 50.0,
                        'factors': {'rest': {}, 'home_away': {}}
                    }
                }

                insights = exporter._generate_insights(archetypes)

                assert len(insights) > 0
                assert 'No significant' in insights[0] or insights[0] != ''


class TestEmptyDataHandling:
    """Test suite for empty data scenarios"""

    def test_empty_archetype_data(self):
        """Test handling when no archetype data available"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter._query_archetype_factors('2024-12-15')

                # Should return structure with all archetypes but no data
                assert 'star' in result
                assert 'scorer' in result
                assert 'rotation' in result
                assert 'role_player' in result
                assert result['star']['player_count'] == 0


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_structure(self):
        """Test complete JSON structure"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Mock all queries to return empty
                mock_client.set_results([])
                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter.generate_json('2024-12-15')

                assert 'generated_at' in result
                assert result['as_of_date'] == '2024-12-15'
                assert 'archetypes' in result
                assert 'key_insights' in result
                assert isinstance(result['archetypes'], dict)
                assert isinstance(result['key_insights'], list)

    def test_generate_json_defaults(self):
        """Test default parameter usage"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = WhatMattersExporter()

                result = exporter.generate_json(as_of_date='2024-12-15')

                assert result['as_of_date'] == '2024-12-15'


class TestSafeFloat:
    """Test suite for _safe_float utility method"""

    def test_safe_float_rounding(self):
        """Test that values are rounded to 1 decimal place"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhatMattersExporter()

                assert exporter._safe_float(52.456) == 52.5
                assert exporter._safe_float(48.123) == 48.1

    def test_safe_float_none(self):
        """Test None handling"""
        with patch('data_processors.publishing.what_matters_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = WhatMattersExporter()

                assert exporter._safe_float(None) is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
