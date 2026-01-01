"""
SQL Verification Tests for Bootstrap Period Implementation

These tests verify the database state after processors run.
Requires BigQuery access and historical data.
"""

import pytest
from datetime import date
from google.cloud import bigquery


@pytest.mark.integration
@pytest.mark.sql
class TestEarlySeasonSkipVerification:
    """Verify that processors correctly skipped early season in database."""

    @pytest.fixture
    def bq_client(self):
        """Create BigQuery client."""
        return bigquery.Client(project='nba-props-platform')

    def test_player_daily_cache_no_records_for_early_season(self, bq_client):
        """Verify player_daily_cache has NO records for days 0-6."""
        query = """
        SELECT COUNT(*) as record_count
        FROM `nba-props-platform.nba_precompute.player_daily_cache`
        WHERE cache_date BETWEEN '2023-10-24' AND '2023-10-30'
        """

        result = bq_client.query(query).result(timeout=60)
        row = next(result)

        # Should be 0 (processors skipped these dates)
        assert row.record_count == 0, \
            "player_daily_cache should have 0 records for days 0-6"

    def test_player_shot_zone_no_records_for_early_season(self, bq_client):
        """Verify player_shot_zone_analysis has NO records for days 0-6."""
        query = """
        SELECT COUNT(*) as record_count
        FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date BETWEEN '2023-10-24' AND '2023-10-30'
        """

        result = bq_client.query(query).result(timeout=60)
        row = next(result)

        assert row.record_count == 0, \
            "player_shot_zone_analysis should have 0 records for days 0-6"

    def test_team_defense_zone_no_records_for_early_season(self, bq_client):
        """Verify team_defense_zone_analysis has NO records for days 0-6."""
        query = """
        SELECT COUNT(*) as record_count
        FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date BETWEEN '2023-10-24' AND '2023-10-30'
        """

        result = bq_client.query(query).result(timeout=60)
        row = next(result)

        assert row.record_count == 0, \
            "team_defense_zone_analysis should have 0 records for days 0-6"

    def test_player_composite_factors_no_records_for_early_season(self, bq_client):
        """Verify player_composite_factors has NO records for days 0-6."""
        query = """
        SELECT COUNT(*) as record_count
        FROM `nba-props-platform.nba_precompute.player_composite_factors`
        WHERE analysis_date BETWEEN '2023-10-24' AND '2023-10-30'
        """

        result = bq_client.query(query).result(timeout=60)
        row = next(result)

        assert row.record_count == 0, \
            "player_composite_factors should have 0 records for days 0-6"


@pytest.mark.integration
@pytest.mark.sql
class TestMLFeatureStorePlaceholders:
    """Verify ML Feature Store creates placeholders for early season."""

    @pytest.fixture
    def bq_client(self):
        """Create BigQuery client."""
        return bigquery.Client(project='nba-props-platform')

    def test_ml_feature_store_has_placeholder_records(self, bq_client):
        """Verify ml_feature_store_v2 HAS placeholder records for days 0-6."""
        query = """
        SELECT
            COUNT(*) as player_count,
            AVG(feature_quality_score) as avg_quality,
            COUNT(CASE WHEN early_season_flag THEN 1 END) as early_season_count,
            COUNT(CASE WHEN is_production_ready THEN 1 END) as production_ready_count
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE game_date = '2023-10-24'  # Opening night
        """

        result = bq_client.query(query).result(timeout=60)
        row = next(result)

        # Should have ~450 players with placeholder records
        assert row.player_count > 400, \
            f"Should have ~450 placeholder records, got {row.player_count}"

        # All should have zero quality
        assert row.avg_quality == 0.0, \
            f"Placeholders should have 0.0 quality, got {row.avg_quality}"

        # All should be marked as early season
        assert row.early_season_count == row.player_count, \
            "All records should have early_season_flag=TRUE"

        # None should be production ready
        assert row.production_ready_count == 0, \
            "No records should be production ready during early season"

    def test_ml_feature_store_placeholder_features_are_null(self, bq_client):
        """Verify placeholder records have NULL features."""
        query = """
        SELECT features
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE game_date = '2023-10-24'
        LIMIT 5
        """

        result = bq_client.query(query).result(timeout=60)

        for row in result:
            # Features should be array of NULLs
            assert row.features is not None, "Features array should exist"
            assert len(row.features) == 25, "Should have 25 features"
            assert all(f is None for f in row.features), \
                "All features should be NULL in placeholders"


@pytest.mark.integration
@pytest.mark.sql
class TestRegularSeasonProcessing:
    """Verify processors process correctly after day 7."""

    @pytest.fixture
    def bq_client(self):
        """Create BigQuery client."""
        return bigquery.Client(project='nba-props-platform')

    def test_player_daily_cache_has_records_after_day_7(self, bq_client):
        """Verify player_daily_cache HAS records for day 7+."""
        query = """
        SELECT COUNT(*) as record_count
        FROM `nba-props-platform.nba_precompute.player_daily_cache`
        WHERE cache_date = '2023-10-31'  # Day 7
        """

        result = bq_client.query(query).result(timeout=60)
        row = next(result)

        # Should have ~450 player records
        assert row.record_count > 400, \
            f"Should have ~450 records on day 7, got {row.record_count}"

    def test_ml_feature_store_quality_improves_after_day_7(self, bq_client):
        """Verify ML Feature Store quality scores improve after day 7."""
        query = """
        SELECT
            game_date,
            COUNT(*) as players,
            AVG(feature_quality_score) as avg_quality,
            COUNT(CASE WHEN is_production_ready THEN 1 END) as production_ready
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE game_date IN ('2023-10-31', '2023-11-01', '2023-11-06')
        GROUP BY game_date
        ORDER BY game_date
        """

        result = bq_client.query(query).result(timeout=60)
        rows = list(result)

        # Should have data for all 3 dates
        assert len(rows) == 3

        for row in rows:
            # Quality should be > 70 (production threshold)
            assert row.avg_quality >= 70.0, \
                f"{row.game_date}: Quality should be >=70, got {row.avg_quality}"

            # Most should be production ready
            production_pct = row.production_ready / row.players if row.players > 0 else 0
            assert production_pct >= 0.90, \
                f"{row.game_date}: >=90% should be production ready, got {production_pct:.1%}"

    def test_feature_quality_progression(self, bq_client):
        """Verify feature quality improves over first month."""
        query = """
        SELECT
            game_date,
            AVG(feature_quality_score) as avg_quality
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE game_date BETWEEN '2023-10-31' AND '2023-11-30'
        GROUP BY game_date
        ORDER BY game_date
        LIMIT 10
        """

        result = bq_client.query(query).result(timeout=60)
        rows = list(result)

        qualities = [row.avg_quality for row in rows]

        # Quality should generally improve (allow for some variance)
        # First day should be lower than last day
        assert qualities[-1] >= qualities[0], \
            "Quality should improve from first day to later days"


@pytest.mark.integration
@pytest.mark.sql
class TestProcessorRunHistory:
    """Verify processor run history logging for early season skips."""

    @pytest.fixture
    def bq_client(self):
        """Create BigQuery client."""
        return bigquery.Client(project='nba-props-platform')

    def test_run_history_shows_skipped_early_season(self, bq_client):
        """Verify processor_run_history logs early season skips."""
        query = """
        SELECT
            processor_name,
            data_date,
            status,
            processing_decision_reason
        FROM `nba-props-platform.nba_reference.processor_run_history`
        WHERE data_date BETWEEN '2023-10-24' AND '2023-10-30'
          AND phase = 'phase_4_precompute'
          AND output_table IN (
              'player_daily_cache',
              'player_shot_zone_analysis',
              'team_defense_zone_analysis',
              'player_composite_factors'
          )
        ORDER BY data_date, processor_name
        """

        result = bq_client.query(query).result(timeout=60)
        rows = list(result)

        # Should have run history entries
        if len(rows) > 0:
            for row in rows:
                # Should show early season skip reason
                assert row.processing_decision_reason is not None
                assert 'bootstrap' in row.processing_decision_reason.lower() or \
                       'early_season' in row.processing_decision_reason.lower(), \
                       f"Should log bootstrap/early_season reason: {row.processing_decision_reason}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-m', 'integration'])
