"""
Unit tests for PostponementDetector.

Tests detection methods with mock BigQuery data without requiring actual DB connection.
"""

import pytest
from datetime import date
from unittest.mock import Mock, MagicMock, patch

from shared.utils.postponement_detector import (
    PostponementDetector,
    get_affected_predictions
)


class MockQueryResult:
    """Mock BigQuery query result row."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class TestPostponementDetector:
    """Test PostponementDetector class."""

    @pytest.fixture
    def mock_bq_client(self):
        """Create mock BigQuery client."""
        client = Mock()
        client.project = 'test-project'
        return client

    @pytest.fixture
    def detector(self, mock_bq_client):
        """Create detector with mock client."""
        return PostponementDetector(sport="NBA", bq_client=mock_bq_client)

    # ================================================================
    # Initialization Tests
    # ================================================================

    def test_init_defaults(self, mock_bq_client):
        """Test default initialization."""
        detector = PostponementDetector(bq_client=mock_bq_client)

        assert detector.sport == "NBA"
        assert detector.client == mock_bq_client
        assert detector.anomalies == []

    def test_init_custom_sport(self, mock_bq_client):
        """Test initialization with custom sport."""
        detector = PostponementDetector(sport="MLB", bq_client=mock_bq_client)

        assert detector.sport == "MLB"

    def test_postponement_keywords(self):
        """Test that expected keywords are defined."""
        expected_keywords = ['postpone', 'postponed', 'cancel', 'reschedule', 'delay']

        for keyword in expected_keywords:
            assert keyword in PostponementDetector.POSTPONEMENT_KEYWORDS

    # ================================================================
    # FINAL_WITHOUT_SCORES Detection Tests
    # ================================================================

    def test_detect_final_without_scores_finds_anomaly(self, detector):
        """Test detection of Final games with NULL scores."""
        # Mock query result
        mock_row = MockQueryResult(
            game_id='0022500644',
            game_date=date(2026, 1, 24),
            game_status=3,
            game_status_text='Final',
            home_team_tricode='MIN',
            away_team_tricode='GSW',
            home_team_score=None,
            away_team_score=None
        )

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]
        detector.client.query.return_value = mock_job

        # Run detection
        with patch('shared.utils.postponement_detector.get_affected_predictions', return_value=55):
            detector._detect_final_without_scores(date(2026, 1, 24))

        # Verify anomaly was created
        assert len(detector.anomalies) == 1
        anomaly = detector.anomalies[0]

        assert anomaly['type'] == 'FINAL_WITHOUT_SCORES'
        assert anomaly['severity'] == 'CRITICAL'
        assert anomaly['game_id'] == '0022500644'
        assert anomaly['teams'] == 'GSW@MIN'
        assert anomaly['detection_source'] == 'schedule_anomaly'

    def test_detect_final_without_scores_no_results(self, detector):
        """Test no anomalies when all Final games have scores."""
        mock_job = Mock()
        mock_job.result.return_value = []
        detector.client.query.return_value = mock_job

        detector._detect_final_without_scores(date(2026, 1, 24))

        assert len(detector.anomalies) == 0

    def test_detect_final_without_scores_query_error(self, detector):
        """Test graceful handling of query errors."""
        detector.client.query.side_effect = Exception("Query failed")

        # Should not raise, just log and return
        detector._detect_final_without_scores(date(2026, 1, 24))

        assert len(detector.anomalies) == 0

    # ================================================================
    # GAME_RESCHEDULED Detection Tests
    # ================================================================

    def test_detect_rescheduled_games_finds_anomaly(self, detector):
        """Test detection of games appearing on multiple dates."""
        mock_row = MockQueryResult(
            game_id='0022500644',
            dates=[date(2026, 1, 24), date(2026, 1, 25)],
            statuses=['Postponed', 'Scheduled'],
            home_team='MIN',
            away_team='GSW'
        )

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]
        detector.client.query.return_value = mock_job

        with patch('shared.utils.postponement_detector.get_affected_predictions', return_value=55):
            detector._detect_rescheduled_games(date(2026, 1, 24))

        assert len(detector.anomalies) == 1
        anomaly = detector.anomalies[0]

        assert anomaly['type'] == 'GAME_RESCHEDULED'
        assert anomaly['severity'] == 'HIGH'
        assert anomaly['original_date'] == '2026-01-24'
        assert anomaly['new_date'] == '2026-01-25'
        assert anomaly['teams'] == 'GSW@MIN'
        assert anomaly['detection_source'] == 'schedule_duplicate'

    def test_detect_rescheduled_games_multiple_reschedules(self, detector):
        """Test detection of multiple rescheduled games."""
        mock_rows = [
            MockQueryResult(
                game_id='0022500644',
                dates=[date(2026, 1, 24), date(2026, 1, 25)],
                statuses=['Postponed', 'Scheduled'],
                home_team='MIN',
                away_team='GSW'
            ),
            MockQueryResult(
                game_id='0022500692',
                dates=[date(2026, 1, 30), date(2026, 1, 31)],
                statuses=['Scheduled', 'Scheduled'],
                home_team='MIA',
                away_team='CHI'
            )
        ]

        mock_job = Mock()
        mock_job.result.return_value = mock_rows
        detector.client.query.return_value = mock_job

        with patch('shared.utils.postponement_detector.get_affected_predictions', return_value=0):
            detector._detect_rescheduled_games(date(2026, 1, 24))

        assert len(detector.anomalies) == 2

        # Verify both games detected
        game_ids = [a['game_id'] for a in detector.anomalies]
        assert '0022500644' in game_ids
        assert '0022500692' in game_ids

    def test_detect_rescheduled_games_no_results(self, detector):
        """Test no anomalies when no games are rescheduled."""
        mock_job = Mock()
        mock_job.result.return_value = []
        detector.client.query.return_value = mock_job

        detector._detect_rescheduled_games(date(2026, 1, 24))

        assert len(detector.anomalies) == 0

    # ================================================================
    # FINAL_NO_BOXSCORES Detection Tests
    # ================================================================

    def test_detect_final_without_boxscores_finds_anomaly(self, detector):
        """Test detection of Final games missing boxscore data."""
        mock_row = MockQueryResult(
            game_id='0022500644',
            home_team_tricode='MIN',
            away_team_tricode='GSW',
            has_bdl=False,
            has_gamebook=False
        )

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]
        detector.client.query.return_value = mock_job

        detector._detect_final_without_boxscores(date(2026, 1, 24))

        assert len(detector.anomalies) == 1
        anomaly = detector.anomalies[0]

        assert anomaly['type'] == 'FINAL_NO_BOXSCORES'
        assert anomaly['severity'] == 'HIGH'
        assert anomaly['teams'] == 'GSW@MIN'
        assert anomaly['has_bdl'] is False
        assert anomaly['has_gamebook'] is False
        assert anomaly['detection_source'] == 'cross_validation'

    def test_detect_final_without_boxscores_skips_existing_anomaly(self, detector):
        """Test that existing anomalies are enriched, not duplicated."""
        # Pre-populate with an existing anomaly for same game
        detector.anomalies.append({
            'type': 'FINAL_WITHOUT_SCORES',
            'severity': 'CRITICAL',
            'game_id': '0022500644',
            'teams': 'GSW@MIN'
        })

        mock_row = MockQueryResult(
            game_id='0022500644',
            home_team_tricode='MIN',
            away_team_tricode='GSW',
            has_bdl=False,
            has_gamebook=False
        )

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]
        detector.client.query.return_value = mock_job

        detector._detect_final_without_boxscores(date(2026, 1, 24))

        # Should still be only 1 anomaly (existing one enriched)
        assert len(detector.anomalies) == 1
        assert detector.anomalies[0]['has_boxscores'] is False

    # ================================================================
    # NEWS_POSTPONEMENT_MENTIONED Detection Tests
    # ================================================================

    def test_detect_news_postponements_finds_articles(self, detector):
        """Test detection of news articles mentioning postponements."""
        mock_rows = [
            MockQueryResult(
                article_id='article1',
                title='Warriors-Timberwolves game postponed due to tragedy',
                summary='The NBA has postponed tonight\'s game...',
                published_at='2026-01-24 18:00:00',
                source='ESPN'
            ),
            MockQueryResult(
                article_id='article2',
                title='GSW at MIN rescheduled to tomorrow',
                summary='Following the postponement...',
                published_at='2026-01-24 19:00:00',
                source='NBA.com'
            )
        ]

        mock_job = Mock()
        mock_job.result.return_value = mock_rows
        detector.client.query.return_value = mock_job

        detector._detect_news_postponements(date(2026, 1, 24))

        assert len(detector.anomalies) == 1
        anomaly = detector.anomalies[0]

        assert anomaly['type'] == 'NEWS_POSTPONEMENT_MENTIONED'
        assert anomaly['severity'] == 'MEDIUM'
        assert anomaly['article_count'] == 2
        assert len(anomaly['article_ids']) == 2
        assert anomaly['detection_source'] == 'news_scan'

    def test_detect_news_postponements_no_articles(self, detector):
        """Test no anomalies when no relevant news found."""
        mock_job = Mock()
        mock_job.result.return_value = []
        detector.client.query.return_value = mock_job

        detector._detect_news_postponements(date(2026, 1, 24))

        assert len(detector.anomalies) == 0

    # ================================================================
    # detect_all Integration Tests
    # ================================================================

    def test_detect_all_runs_all_methods(self, detector):
        """Test that detect_all runs all detection methods."""
        mock_job = Mock()
        mock_job.result.return_value = []
        detector.client.query.return_value = mock_job

        result = detector.detect_all(date(2026, 1, 24))

        # Should have called query 5 times:
        # 1 for handled game IDs check + 4 for detection methods
        assert detector.client.query.call_count == 5
        assert result == []

    def test_detect_all_clears_previous_anomalies(self, detector):
        """Test that detect_all clears anomalies from previous runs."""
        # Pre-populate with old anomalies
        detector.anomalies = [{'type': 'OLD_ANOMALY'}]

        mock_job = Mock()
        mock_job.result.return_value = []
        detector.client.query.return_value = mock_job

        result = detector.detect_all(date(2026, 1, 24))

        # Old anomalies should be cleared
        assert {'type': 'OLD_ANOMALY'} not in result

    # ================================================================
    # get_summary Tests
    # ================================================================

    def test_get_summary_empty(self, detector):
        """Test summary with no anomalies."""
        summary = detector.get_summary()

        assert summary['total'] == 0
        assert summary['has_critical'] is False
        assert summary['has_high'] is False
        assert summary['by_severity'] == {}
        assert summary['by_type'] == {}

    def test_get_summary_with_anomalies(self, detector):
        """Test summary with mixed anomalies."""
        detector.anomalies = [
            {'type': 'FINAL_WITHOUT_SCORES', 'severity': 'CRITICAL'},
            {'type': 'GAME_RESCHEDULED', 'severity': 'HIGH'},
            {'type': 'GAME_RESCHEDULED', 'severity': 'HIGH'},
            {'type': 'NEWS_POSTPONEMENT_MENTIONED', 'severity': 'MEDIUM'},
        ]

        summary = detector.get_summary()

        assert summary['total'] == 4
        assert summary['has_critical'] is True
        assert summary['has_high'] is True
        assert summary['by_severity']['CRITICAL'] == 1
        assert summary['by_severity']['HIGH'] == 2
        assert summary['by_severity']['MEDIUM'] == 1
        assert summary['by_type']['FINAL_WITHOUT_SCORES'] == 1
        assert summary['by_type']['GAME_RESCHEDULED'] == 2

    # ================================================================
    # log_to_bigquery Tests
    # ================================================================

    def test_log_to_bigquery_success(self, detector):
        """Test successful logging to BigQuery."""
        anomaly = {
            'type': 'GAME_RESCHEDULED',
            'severity': 'HIGH',
            'game_id': '0022500644',
            'original_date': '2026-01-24',
            'new_date': '2026-01-25',
            'teams': 'GSW@MIN',
            'predictions_affected': 55,
            'detection_source': 'schedule_duplicate',
            'details': 'Game rescheduled'
        }

        mock_job = Mock()
        mock_job.result.return_value = None
        detector.client.query.return_value = mock_job

        result = detector.log_to_bigquery(anomaly)

        assert result == '0022500644'
        detector.client.query.assert_called_once()

    def test_log_to_bigquery_no_game_id(self, detector):
        """Test logging anomaly without game_id (news article)."""
        anomaly = {
            'type': 'NEWS_POSTPONEMENT_MENTIONED',
            'severity': 'MEDIUM',
            'game_date': '2026-01-24',
            'article_count': 5,
            'detection_source': 'news_scan',
            'details': 'Found news articles'
        }

        mock_job = Mock()
        mock_job.result.return_value = None
        detector.client.query.return_value = mock_job

        result = detector.log_to_bigquery(anomaly)

        # Should generate game_id from date
        assert result == 'NEWS_2026-01-24'

    def test_log_to_bigquery_failure(self, detector):
        """Test handling of BigQuery write failure."""
        anomaly = {
            'type': 'GAME_RESCHEDULED',
            'game_id': '0022500644',
            'detection_source': 'schedule_duplicate'
        }

        detector.client.query.side_effect = Exception("Write failed")

        result = detector.log_to_bigquery(anomaly)

        assert result is None


class TestGetAffectedPredictions:
    """Test get_affected_predictions helper function."""

    @pytest.fixture
    def mock_bq_client(self):
        """Create mock BigQuery client."""
        return Mock()

    def test_get_affected_predictions_with_teams(self, mock_bq_client):
        """Test counting predictions for specific game."""
        mock_job = Mock()
        mock_job.result.return_value = [MockQueryResult(count=55)]
        mock_bq_client.query.return_value = mock_job

        count = get_affected_predictions(
            date(2026, 1, 24),
            teams="GSW@MIN",
            bq_client=mock_bq_client
        )

        assert count == 55

    def test_get_affected_predictions_without_teams(self, mock_bq_client):
        """Test counting all predictions for a date."""
        mock_job = Mock()
        mock_job.result.return_value = [MockQueryResult(count=200)]
        mock_bq_client.query.return_value = mock_job

        count = get_affected_predictions(
            date(2026, 1, 24),
            bq_client=mock_bq_client
        )

        assert count == 200

    def test_get_affected_predictions_empty_result(self, mock_bq_client):
        """Test handling of no predictions found."""
        mock_job = Mock()
        mock_job.result.return_value = []
        mock_bq_client.query.return_value = mock_job

        count = get_affected_predictions(
            date(2026, 1, 24),
            teams="GSW@MIN",
            bq_client=mock_bq_client
        )

        assert count == 0

    def test_get_affected_predictions_query_error(self, mock_bq_client):
        """Test handling of query error."""
        mock_bq_client.query.side_effect = Exception("Query failed")

        count = get_affected_predictions(
            date(2026, 1, 24),
            teams="GSW@MIN",
            bq_client=mock_bq_client
        )

        assert count == 0


class TestSeverityClassification:
    """Test that anomaly types have correct severity."""

    @pytest.fixture
    def mock_bq_client(self):
        return Mock()

    def test_final_without_scores_is_critical(self, mock_bq_client):
        """FINAL_WITHOUT_SCORES should be CRITICAL severity."""
        detector = PostponementDetector(bq_client=mock_bq_client)

        mock_row = MockQueryResult(
            game_id='0022500644',
            game_date=date(2026, 1, 24),
            game_status=3,
            game_status_text='Final',
            home_team_tricode='MIN',
            away_team_tricode='GSW',
            home_team_score=None,
            away_team_score=None
        )

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]
        mock_bq_client.query.return_value = mock_job

        with patch('shared.utils.postponement_detector.get_affected_predictions', return_value=0):
            detector._detect_final_without_scores(date(2026, 1, 24))

        assert detector.anomalies[0]['severity'] == 'CRITICAL'

    def test_game_rescheduled_is_high(self, mock_bq_client):
        """GAME_RESCHEDULED should be HIGH severity."""
        detector = PostponementDetector(bq_client=mock_bq_client)

        mock_row = MockQueryResult(
            game_id='0022500644',
            dates=[date(2026, 1, 24), date(2026, 1, 25)],
            statuses=['Postponed', 'Scheduled'],
            home_team='MIN',
            away_team='GSW'
        )

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]
        mock_bq_client.query.return_value = mock_job

        with patch('shared.utils.postponement_detector.get_affected_predictions', return_value=0):
            detector._detect_rescheduled_games(date(2026, 1, 24))

        assert detector.anomalies[0]['severity'] == 'HIGH'

    def test_news_mention_is_medium(self, mock_bq_client):
        """NEWS_POSTPONEMENT_MENTIONED should be MEDIUM severity."""
        detector = PostponementDetector(bq_client=mock_bq_client)

        mock_row = MockQueryResult(
            article_id='article1',
            title='Game postponed',
            summary='The game was postponed...',
            published_at='2026-01-24 18:00:00',
            source='ESPN'
        )

        mock_job = Mock()
        mock_job.result.return_value = [mock_row]
        mock_bq_client.query.return_value = mock_job

        detector._detect_news_postponements(date(2026, 1, 24))

        assert detector.anomalies[0]['severity'] == 'MEDIUM'
