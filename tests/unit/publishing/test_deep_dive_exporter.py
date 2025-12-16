"""
Unit Tests for DeepDiveExporter

Tests cover:
1. Monthly topic rotation
2. Hero stat generation (focus-specific queries)
3. Teaser text generation
4. Slug generation
5. Empty data handling
6. Mock BigQuery responses
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

from data_processors.publishing.deep_dive_exporter import DeepDiveExporter


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


class TestDeepDiveExporterInit:
    """Test suite for initialization"""

    def test_initialization_monthly_topics(self):
        """Test that monthly topics are defined"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = DeepDiveExporter()

                assert len(exporter.MONTHLY_TOPICS) > 0
                assert 1 in exporter.MONTHLY_TOPICS
                assert 12 in exporter.MONTHLY_TOPICS


class TestMonthlyTopicRotation:
    """Test suite for monthly topic rotation"""

    def test_january_topic(self):
        """Test January topic selection"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-01-15')

                assert result['title'] == 'The January Effect'
                assert 'January' in result['month']

    def test_february_topic(self):
        """Test February topic selection"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-02-15')

                assert result['title'] == 'All-Star Break Impact'

    def test_december_topic(self):
        """Test December topic selection"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-12-15')

                assert result['title'] == 'December Deep Dive'
                assert result['subtitle'] == 'Rest patterns and holiday performance'

    def test_default_topic_for_undefined_month(self):
        """Test that undefined months default to December topic"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                # May (5) is not defined in MONTHLY_TOPICS
                result = exporter.generate_json('2024-05-15')

                # Should default to December topic
                assert result['title'] == 'December Deep Dive'


class TestHeroStatGeneration:
    """Test suite for hero stat generation"""

    def test_rest_impact_hero_stat(self):
        """Test hero stat for rest impact focus"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                # Mock rest impact query results
                rest_data = [
                    {
                        'rested_over_pct': 52.5,
                        'b2b_over_pct': 47.8
                    }
                ]

                mock_client.set_results(rest_data)
                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                hero_stat = exporter._get_hero_stat('rest_impact', '2024-12-15')

                assert hero_stat['value'] == '52%' or hero_stat['value'] == '53%'  # Rounded
                assert 'OVER rate' in hero_stat['label']
                assert '2+ rest' in hero_stat['label']
                assert 'back-to-backs' in hero_stat['context']

    def test_hero_stat_with_empty_data(self):
        """Test hero stat fallback when no data available"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                hero_stat = exporter._get_hero_stat('rest_impact', '2024-12-15')

                # Should fall back to default
                assert hero_stat['value'] == '54%'
                assert 'League-wide' in hero_stat['label']

    def test_hero_stat_for_schedule_density(self):
        """Test hero stat fallback for other focus areas"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = DeepDiveExporter()

                hero_stat = exporter._get_hero_stat('schedule_density', '2024-01-15')

                # Should use default since no specific query
                assert 'value' in hero_stat
                assert 'label' in hero_stat
                assert 'context' in hero_stat


class TestTeaserGeneration:
    """Test suite for teaser text generation"""

    def test_rest_impact_teaser(self):
        """Test teaser for rest impact focus"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = DeepDiveExporter()

                teaser = exporter._get_teaser('rest_impact')

                assert len(teaser) > 0
                assert 'rest patterns' in teaser.lower()

    def test_schedule_density_teaser(self):
        """Test teaser for schedule density focus"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = DeepDiveExporter()

                teaser = exporter._get_teaser('schedule_density')

                assert 'January' in teaser

    def test_all_star_break_teaser(self):
        """Test teaser for all-star break focus"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = DeepDiveExporter()

                teaser = exporter._get_teaser('all_star_break')

                assert 'All-Star' in teaser

    def test_playoff_race_teaser(self):
        """Test teaser for playoff race focus"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = DeepDiveExporter()

                teaser = exporter._get_teaser('playoff_race')

                assert 'playoff' in teaser.lower()

    def test_season_end_teaser(self):
        """Test teaser for season end focus"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = DeepDiveExporter()

                teaser = exporter._get_teaser('season_end')

                assert 'final weeks' in teaser.lower() or 'load management' in teaser.lower()

    def test_unknown_focus_teaser(self):
        """Test teaser for unknown focus area"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                exporter = DeepDiveExporter()

                teaser = exporter._get_teaser('unknown_focus')

                # Should return generic teaser
                assert len(teaser) > 0
                assert 'analysis' in teaser.lower()


class TestSlugGeneration:
    """Test suite for slug generation"""

    def test_slug_format(self):
        """Test slug formatting"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-12-15')

                # Slug should be focus-date format
                assert 'rest-impact' in result['slug']
                assert 'december-2024' in result['slug']

    def test_slug_underscore_replacement(self):
        """Test that underscores are replaced with hyphens in slug"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-01-15')

                # schedule_density should become schedule-density
                assert '_' not in result['slug']
                assert '-' in result['slug']


class TestGenerateJson:
    """Test suite for generate_json method"""

    def test_generate_json_structure(self):
        """Test complete JSON structure"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-12-15')

                assert 'generated_at' in result
                assert 'month' in result
                assert 'title' in result
                assert 'subtitle' in result
                assert 'hero_stat' in result
                assert 'teaser' in result
                assert 'slug' in result
                assert 'cta' in result

    def test_hero_stat_structure(self):
        """Test hero stat nested structure"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-12-15')

                hero_stat = result['hero_stat']
                assert 'value' in hero_stat
                assert 'label' in hero_stat
                assert 'context' in hero_stat

    def test_month_formatting(self):
        """Test month name formatting"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-12-15')

                # Should be "December 2024"
                assert result['month'] == 'December 2024'

    def test_cta_text(self):
        """Test CTA text is present"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-12-15')

                assert result['cta'] == 'Read the full analysis'

    def test_generate_json_defaults(self):
        """Test default parameter usage"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json(as_of_date='2024-12-15')

                assert 'December 2024' in result['month']


class TestMultipleMonths:
    """Test suite for multiple month scenarios"""

    def test_different_months_different_topics(self):
        """Test that different months get different topics"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                jan_result = exporter.generate_json('2024-01-15')
                dec_result = exporter.generate_json('2024-12-15')

                # Should have different titles
                assert jan_result['title'] != dec_result['title']
                assert jan_result['subtitle'] != dec_result['subtitle']

    def test_october_topic(self):
        """Test October season opener topic"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-10-15')

                assert result['title'] == 'Season Opener Insights'

    def test_november_topic(self):
        """Test November early season topic"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-11-15')

                assert result['title'] == 'November Grind'


class TestEmptyDataHandling:
    """Test suite for empty data scenarios"""

    def test_rest_impact_query_no_results(self):
        """Test rest impact query with no results"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()
                mock_client.set_results([])

                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-12-15')

                # Should still have complete structure with defaults
                assert result['hero_stat']['value'] == '54%'

    def test_rest_impact_query_null_values(self):
        """Test rest impact query with null values in results"""
        with patch('data_processors.publishing.base_exporter.bigquery.Client') as mock_bq:
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                mock_client = MockBigQueryClient()

                rest_data = [
                    {
                        'rested_over_pct': None,
                        'b2b_over_pct': None
                    }
                ]

                mock_client.set_results(rest_data)
                mock_bq.return_value = mock_client
                exporter = DeepDiveExporter()

                result = exporter.generate_json('2024-12-15')

                # Should fall back to default
                assert result['hero_stat']['value'] == '54%'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
