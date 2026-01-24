"""
Unit Tests for NewsExporter

Tests cover:
1. Initialization with sport parameter
2. Impact level mapping
3. Critical news detection
4. Headline creation/truncation
5. Tonight summary generation
6. Player JSON generation
7. Timestamp formatting
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone


class TestNewsExporterInit:
    """Test suite for NewsExporter initialization"""

    def test_initialization_with_nba_sport(self):
        """Test that exporter initializes with NBA sport"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                assert exporter.sport == 'nba'

    def test_initialization_with_mlb_sport(self):
        """Test that exporter initializes with MLB sport"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='mlb')

                assert exporter.sport == 'mlb'


class TestImpactLevelMapping:
    """Test suite for category to impact level mapping"""

    def test_high_impact_categories(self):
        """Test that injury, trade, suspension are high impact"""
        from data_processors.publishing.news_exporter import CATEGORY_IMPACT

        assert CATEGORY_IMPACT.get('injury') == 'high'
        assert CATEGORY_IMPACT.get('trade') == 'high'
        assert CATEGORY_IMPACT.get('suspension') == 'high'

    def test_medium_impact_categories(self):
        """Test that signing, lineup are medium impact"""
        from data_processors.publishing.news_exporter import CATEGORY_IMPACT

        assert CATEGORY_IMPACT.get('signing') == 'medium'
        assert CATEGORY_IMPACT.get('lineup') == 'medium'

    def test_low_impact_categories(self):
        """Test that performance, preview, recap are low impact"""
        from data_processors.publishing.news_exporter import CATEGORY_IMPACT

        assert CATEGORY_IMPACT.get('performance') == 'low'
        assert CATEGORY_IMPACT.get('preview') == 'low'
        assert CATEGORY_IMPACT.get('recap') == 'low'


class TestCriticalNewsDetection:
    """Test suite for critical news detection"""

    def test_critical_categories_defined(self):
        """Test that critical categories include injury, trade, suspension"""
        from data_processors.publishing.news_exporter import CRITICAL_CATEGORIES

        assert 'injury' in CRITICAL_CATEGORIES
        assert 'trade' in CRITICAL_CATEGORIES
        assert 'suspension' in CRITICAL_CATEGORIES
        assert 'preview' not in CRITICAL_CATEGORIES


class TestHeadlineCreation:
    """Test suite for headline creation and truncation"""

    def test_short_title_not_truncated(self):
        """Test that short titles are not truncated"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                short_title = "LeBron James out tonight"
                headline = exporter._create_headline(short_title)

                assert headline == short_title

    def test_long_title_truncated_at_word_boundary(self):
        """Test that long titles are truncated at word boundary"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                long_title = "This is a very long title that exceeds fifty characters and should be truncated properly"
                headline = exporter._create_headline(long_title)

                assert len(headline) <= 50
                assert headline.endswith('...')

    def test_empty_title_returns_empty(self):
        """Test that empty title returns empty string"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                headline = exporter._create_headline('')

                assert headline == ''

    def test_none_title_returns_empty(self):
        """Test that None title returns empty string"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                headline = exporter._create_headline(None)

                assert headline == ''


class TestTimestampFormatting:
    """Test suite for timestamp formatting"""

    def test_format_datetime_object(self):
        """Test formatting datetime object to ISO string"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                dt = datetime(2025, 12, 15, 10, 30, 0, tzinfo=timezone.utc)
                result = exporter._format_timestamp(dt)

                assert '2025-12-15' in result
                assert '10:30' in result

    def test_format_none_timestamp(self):
        """Test that None timestamp returns None"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                result = exporter._format_timestamp(None)

                assert result is None


class TestPlayerJsonGeneration:
    """Test suite for player JSON generation"""

    def test_player_json_has_required_fields(self):
        """Test that player JSON has required fields"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                # Mock query methods
                exporter._query_player_articles = Mock(return_value=[])
                exporter._get_player_info = Mock(return_value={
                    'player_full_name': 'LeBron James',
                    'team_abbr': 'LAL'
                })

                result = exporter.generate_player_json('lebronjames')

                assert 'player_lookup' in result
                assert 'player_name' in result
                assert 'team_abbr' in result
                assert 'sport' in result
                assert 'updated_at' in result
                assert 'has_critical_news' in result
                assert 'news_count' in result
                assert 'articles' in result

    def test_critical_news_flag_set(self):
        """Test that critical news flag is set correctly"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                # Mock with injury article
                exporter._query_player_articles = Mock(return_value=[
                    {
                        'article_id': '123',
                        'title': 'Injury Report',
                        'category': 'injury',
                        'source': 'espn_nba',
                        'published_at': datetime.now(timezone.utc)
                    }
                ])
                exporter._get_player_info = Mock(return_value={
                    'player_full_name': 'Player Name',
                    'team_abbr': 'LAL'
                })

                result = exporter.generate_player_json('testplayer')

                assert result['has_critical_news'] is True
                assert result['critical_category'] == 'injury'


class TestTonightSummary:
    """Test suite for tonight summary generation"""

    def test_tonight_summary_structure(self):
        """Test tonight summary has required structure"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                # Mock query method
                exporter._query_news_summaries = Mock(return_value=[
                    {
                        'player_lookup': 'lebronjames',
                        'article_count': 3,
                        'categories': ['injury', 'preview']
                    }
                ])

                result = exporter.generate_tonight_summary()

                assert 'updated_at' in result
                assert 'sport' in result
                assert 'total_players' in result
                assert 'players' in result
                assert len(result['players']) == 1

    def test_tonight_summary_critical_detection(self):
        """Test that tonight summary detects critical news"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                exporter._query_news_summaries = Mock(return_value=[
                    {
                        'player_lookup': 'player1',
                        'article_count': 2,
                        'categories': ['trade', 'preview']
                    }
                ])

                result = exporter.generate_tonight_summary()

                assert result['players'][0]['has_critical_news'] is True
                assert result['players'][0]['critical_category'] == 'trade'


class TestSafeFloat:
    """Test suite for safe float conversion"""

    def test_safe_float_with_valid_number(self):
        """Test safe float with valid number"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                assert exporter._safe_float(5.5) == 5.5
                assert exporter._safe_float(10) == 10.0

    def test_safe_float_with_none(self):
        """Test safe float with None returns default"""
        with patch('google.cloud.bigquery.Client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.news_exporter import NewsExporter
                exporter = NewsExporter(sport='nba')

                assert exporter._safe_float(None) == 0.0
                assert exporter._safe_float(None, 5.0) == 5.0
