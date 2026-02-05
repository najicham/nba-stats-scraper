#!/usr/bin/env python3
"""
Unit tests for Phase 2 Quality Gate.

Tests validation of raw data quality before Phase 3 analytics processing.
"""

import sys
import os
from datetime import date
from unittest.mock import Mock, MagicMock
import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.validation.phase2_quality_gate import Phase2QualityGate, RawDataMetrics
from shared.validation.processing_gate import GateStatus


class TestPhase2QualityGate:
    """Test suite for Phase 2 quality gate."""

    def setup_method(self):
        """Set up test fixtures."""
        self.bq_client = Mock()
        self.project_id = 'test-project'
        self.gate = Phase2QualityGate(self.bq_client, self.project_id)

    def test_validate_metrics_all_pass(self):
        """Test validation when all metrics pass thresholds."""
        metrics = RawDataMetrics(
            game_count=5,
            player_records=150,  # 30 per game
            null_player_names=0,
            null_team_abbr=0,
            null_points=0,
            null_minutes=0,
            has_processed_at=False,
            avg_scrape_age_hours=None,
            max_scrape_age_hours=None
        )

        status, quality_score, issues = self.gate._validate_metrics(metrics, scheduled_games=5)

        assert status == GateStatus.PROCEED
        assert quality_score == 1.0
        assert len(issues) == 0

    def test_validate_metrics_missing_games(self):
        """Test validation when games are missing."""
        metrics = RawDataMetrics(
            game_count=3,
            player_records=90,
            null_player_names=0,
            null_team_abbr=0,
            null_points=0,
            null_minutes=0,
            has_processed_at=False,
            avg_scrape_age_hours=None,
            max_scrape_age_hours=None
        )

        status, quality_score, issues = self.gate._validate_metrics(metrics, scheduled_games=5)

        # Missing games (-0.3) + low player count (-0.2) = 0.5 score = FAIL
        assert status == GateStatus.FAIL
        assert abs(quality_score - 0.5) < 0.01  # Allow for floating point precision
        assert "Missing games: 3/5" in issues
        assert any("Low player record count" in issue for issue in issues)

    def test_validate_metrics_high_null_rate(self):
        """Test validation when NULL rate exceeds threshold."""
        metrics = RawDataMetrics(
            game_count=5,
            player_records=100,
            null_player_names=10,  # 10% NULL rate
            null_team_abbr=0,
            null_points=0,
            null_minutes=0,
            has_processed_at=False,
            avg_scrape_age_hours=None,
            max_scrape_age_hours=None
        )

        status, quality_score, issues = self.gate._validate_metrics(metrics, scheduled_games=5)

        # High NULL rate (-0.3) = 0.7 score = PROCEED_WITH_WARNING
        assert status == GateStatus.PROCEED_WITH_WARNING
        assert quality_score == 0.7
        assert any("NULL rate for player_name" in issue for issue in issues)

    def test_validate_metrics_low_player_count(self):
        """Test validation when player record count is too low."""
        metrics = RawDataMetrics(
            game_count=5,
            player_records=50,  # Only 10 per game, below 20 threshold
            null_player_names=0,
            null_team_abbr=0,
            null_points=0,
            null_minutes=0,
            has_processed_at=False,
            avg_scrape_age_hours=None,
            max_scrape_age_hours=None
        )

        status, quality_score, issues = self.gate._validate_metrics(metrics, scheduled_games=5)

        # Low player count (-0.2) = 0.8 score = PROCEED_WITH_WARNING
        assert status == GateStatus.PROCEED_WITH_WARNING
        assert quality_score == 0.8
        assert any("Low player record count" in issue for issue in issues)

    def test_validate_metrics_stale_data(self):
        """Test validation when data is stale."""
        metrics = RawDataMetrics(
            game_count=5,
            player_records=150,
            null_player_names=0,
            null_team_abbr=0,
            null_points=0,
            null_minutes=0,
            has_processed_at=True,
            avg_scrape_age_hours=15.0,  # Moderately stale
            max_scrape_age_hours=30.0   # Very stale
        )

        status, quality_score, issues = self.gate._validate_metrics(metrics, scheduled_games=5)

        assert status == GateStatus.PROCEED_WITH_WARNING
        assert any("Stale data" in issue for issue in issues)

    def test_validate_metrics_no_timestamp(self):
        """Test validation when no timestamp field is available."""
        metrics = RawDataMetrics(
            game_count=5,
            player_records=150,
            null_player_names=0,
            null_team_abbr=0,
            null_points=0,
            null_minutes=0,
            has_processed_at=False,
            avg_scrape_age_hours=None,
            max_scrape_age_hours=None
        )

        status, quality_score, issues = self.gate._validate_metrics(metrics, scheduled_games=5)

        # Should pass without checking freshness
        assert status == GateStatus.PROCEED
        assert quality_score == 1.0

    def test_build_message_proceed(self):
        """Test message building for PROCEED status."""
        metrics = RawDataMetrics(
            game_count=5,
            player_records=150,
            null_player_names=0,
            null_team_abbr=0,
            null_points=0,
            null_minutes=0,
            has_processed_at=False,
            avg_scrape_age_hours=None,
            max_scrape_age_hours=None
        )

        message = self.gate._build_message(GateStatus.PROCEED, metrics, 5, [])

        assert "Raw data quality passed" in message
        assert "5 games" in message
        assert "150 players" in message

    def test_build_message_fail(self):
        """Test message building for FAIL status."""
        metrics = RawDataMetrics(
            game_count=3,
            player_records=90,
            null_player_names=0,
            null_team_abbr=0,
            null_points=0,
            null_minutes=0,
            has_processed_at=False,
            avg_scrape_age_hours=None,
            max_scrape_age_hours=None
        )

        issues = ["Missing games: 3/5", "Low player count"]
        message = self.gate._build_message(GateStatus.FAIL, metrics, 5, issues)

        assert "Raw data quality insufficient" in message
        assert "3/5 games" in message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
