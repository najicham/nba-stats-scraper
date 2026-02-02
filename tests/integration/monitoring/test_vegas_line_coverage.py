"""
Integration tests for Vegas line coverage monitoring.

These tests verify:
1. Vegas line coverage stays above critical thresholds (35%+)
2. Feature store has correct data for recent games
3. BettingPros data pipeline is working
4. VegasLineSummaryProcessor output is complete

IMPORTANT: 35-50% coverage is NORMAL and expected.
Sportsbooks only offer props for starters and key rotation players,
not all roster players. Historical data shows 37-50% is healthy.

Critical for preventing pipeline breaks (e.g., <20% coverage).
"""

import pytest
from datetime import datetime, timedelta
from google.cloud import bigquery
from typing import Dict, Any


@pytest.fixture
def bq_client():
    """BigQuery client for integration tests."""
    return bigquery.Client()


@pytest.mark.integration
@pytest.mark.smoke
def test_vegas_line_coverage_above_threshold(bq_client):
    """
    CRITICAL: Vegas line coverage must be ≥35% for recent games.

    Historical data shows 37-50% is normal (sportsbooks only offer
    props for starters/key players). This test catches pipeline breaks
    (e.g., <20% coverage indicates scraper or processor failure).
    """
    # Check last 3 days
    query = """
    SELECT
      game_date,
      ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as coverage_pct,
      COUNT(*) as total_records,
      COUNTIF(features[OFFSET(25)] > 0) as with_vegas_lines
    FROM nba_predictions.ml_feature_store_v2
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
      AND game_date < CURRENT_DATE()
      AND ARRAY_LENGTH(features) >= 33
    GROUP BY game_date
    ORDER BY game_date DESC
    """

    results = list(bq_client.query(query).result())

    # Must have data for recent games
    assert len(results) > 0, "No recent feature store data found (last 3 days)"

    # Check each day
    failing_days = []
    for row in results:
        coverage = row.coverage_pct
        game_date = row.game_date
        total = row.total_records
        with_lines = row.with_vegas_lines

        if coverage < 35.0:
            failing_days.append({
                'date': game_date,
                'coverage': coverage,
                'total': total,
                'with_lines': with_lines
            })

    # Assert coverage is above threshold
    assert len(failing_days) == 0, (
        f"Vegas line coverage below 35% threshold:\n" +
        "\n".join([
            f"  {d['date']}: {d['coverage']}% ({d['with_lines']}/{d['total']} records)"
            for d in failing_days
        ]) +
        "\n\nThis indicates a regression in the Vegas line pipeline. "
        "Check:\n"
        "  1. BettingPros scraper: bin/monitoring/check_vegas_line_coverage.sh\n"
        "  2. VegasLineSummaryProcessor logs\n"
        "  3. bettingpros_player_points_props table"
    )


@pytest.mark.integration
def test_bettingpros_data_freshness(bq_client):
    """
    Verify BettingPros scraper is running and data is fresh.

    Stale data (>24 hours old) indicates scraper failure.
    """
    query = """
    SELECT
      game_date,
      COUNT(*) as line_count,
      MAX(processed_at) as latest_processed
    FROM nba_raw.bettingpros_player_points_props
    WHERE game_date >= CURRENT_DATE() - 1
      AND game_date <= CURRENT_DATE()
    GROUP BY game_date
    ORDER BY game_date DESC
    """

    results = list(bq_client.query(query).result())

    # Should have lines for today or yesterday
    assert len(results) > 0, (
        "No BettingPros data for today or yesterday. "
        "Scraper may not be running. Check nba-scrapers service."
    )

    # Check freshness (processed within last 24 hours)
    latest = results[0]
    now = datetime.utcnow()
    age = now - latest.latest_processed.replace(tzinfo=None)

    assert age.total_seconds() < 86400, (
        f"BettingPros data is stale (last processed: {latest.latest_processed}). "
        f"Age: {age.total_seconds()/3600:.1f} hours. "
        "Check nba-scrapers service and scheduler."
    )


@pytest.mark.integration
def test_vegas_line_summary_completeness(bq_client):
    """
    Verify VegasLineSummaryProcessor is creating complete records.

    Each player should have:
    - line_source = 'ACTUAL_PROP' (if line exists)
    - current_points_line > 0
    - processed_at recent
    """
    query = """
    SELECT
      game_date,
      COUNT(*) as total_players,
      COUNTIF(line_source = 'ACTUAL_PROP') as with_actual_lines,
      COUNTIF(line_source = 'NO_PROP_LINE') as no_lines,
      ROUND(100.0 * COUNTIF(line_source = 'ACTUAL_PROP') / COUNT(*), 1) as actual_line_pct,
      MAX(processed_at) as latest_processed
    FROM nba_predictions.vegas_line_summary
    WHERE game_date >= CURRENT_DATE() - 1
      AND game_date <= CURRENT_DATE()
    GROUP BY game_date
    ORDER BY game_date DESC
    """

    results = list(bq_client.query(query).result())

    assert len(results) > 0, (
        "No vegas_line_summary data for recent games. "
        "VegasLineSummaryProcessor may not be running."
    )

    # Check actual line percentage is reasonable (should be 90%+)
    for row in results:
        actual_pct = row.actual_line_pct
        game_date = row.game_date

        # Warning if below 90%, critical if below 50%
        if actual_pct < 90.0:
            pytest.fail(
                f"Vegas line summary has low ACTUAL_PROP percentage on {game_date}: "
                f"{actual_pct}% ({row.with_actual_lines}/{row.total_players}). "
                f"Expected ≥90%. This indicates Phase 4 processor issue."
            )


@pytest.mark.integration
def test_feature_store_structure(bq_client):
    """
    Verify ml_feature_store_v2 has correct structure.

    Features array should have 33+ elements with Vegas line at index 25.
    """
    query = """
    SELECT
      ARRAY_LENGTH(features) as feature_count,
      COUNT(*) as record_count
    FROM nba_predictions.ml_feature_store_v2
    WHERE game_date = CURRENT_DATE() - 1
    GROUP BY feature_count
    ORDER BY record_count DESC
    LIMIT 5
    """

    results = list(bq_client.query(query).result())

    assert len(results) > 0, (
        "No feature store data for yesterday. "
        "Phase 3/4 processors may not be running."
    )

    # Most common feature count should be 33
    most_common = results[0]
    assert most_common.feature_count == 33, (
        f"Feature store has unexpected feature count: {most_common.feature_count}. "
        f"Expected 33 features. Schema may have changed."
    )


@pytest.mark.integration
def test_end_to_end_vegas_pipeline(bq_client):
    """
    End-to-end test: BettingPros → vegas_line_summary → feature store.

    Verifies the complete pipeline for a recent game date.
    """
    # Get a recent game date with completed games
    game_date_query = """
    SELECT game_date
    FROM nba_reference.nba_schedule
    WHERE game_date >= CURRENT_DATE() - 3
      AND game_date < CURRENT_DATE()
      AND game_status = 3  -- Final
    ORDER BY game_date DESC
    LIMIT 1
    """

    game_dates = list(bq_client.query(game_date_query).result())

    if len(game_dates) == 0:
        pytest.skip("No completed games in last 3 days to test pipeline")

    test_date = game_dates[0].game_date

    # 1. Check BettingPros has lines for this date
    bp_query = f"""
    SELECT COUNT(DISTINCT player_lookup) as player_count
    FROM nba_raw.bettingpros_player_points_props
    WHERE game_date = DATE('{test_date}')
      AND points_line IS NOT NULL
    """
    bp_result = list(bq_client.query(bp_query).result())[0]
    bp_players = bp_result.player_count

    assert bp_players > 0, f"No BettingPros lines found for {test_date}"

    # 2. Check vegas_line_summary processed this date
    vls_query = f"""
    SELECT
      COUNT(DISTINCT player_lookup) as player_count,
      COUNTIF(line_source = 'ACTUAL_PROP') as with_lines
    FROM nba_predictions.vegas_line_summary
    WHERE game_date = DATE('{test_date}')
    """
    vls_result = list(bq_client.query(vls_query).result())[0]
    vls_players = vls_result.player_count
    vls_with_lines = vls_result.with_lines

    assert vls_players > 0, f"VegasLineSummary not processed for {test_date}"

    # 3. Check feature store has Vegas lines
    fs_query = f"""
    SELECT
      COUNT(*) as total,
      COUNTIF(features[OFFSET(25)] > 0) as with_vegas
    FROM nba_predictions.ml_feature_store_v2
    WHERE game_date = DATE('{test_date}')
      AND ARRAY_LENGTH(features) >= 33
    """
    fs_result = list(bq_client.query(fs_query).result())[0]
    fs_total = fs_result.total
    fs_with_vegas = fs_result.with_vegas

    assert fs_total > 0, f"Feature store empty for {test_date}"

    # Calculate pipeline efficiency
    coverage = (fs_with_vegas / fs_total * 100) if fs_total > 0 else 0

    assert coverage >= 90.0, (
        f"End-to-end Vegas pipeline degraded for {test_date}:\n"
        f"  BettingPros: {bp_players} players\n"
        f"  VegasLineSummary: {vls_with_lines}/{vls_players} with lines\n"
        f"  Feature Store: {fs_with_vegas}/{fs_total} with Vegas ({coverage:.1f}%)\n"
        f"  Expected: ≥90% coverage\n\n"
        f"Pipeline may have data loss between stages."
    )


@pytest.mark.integration
def test_vegas_coverage_monitoring_script(bq_client):
    """
    Verify the monitoring script itself works correctly.

    This is a meta-test to ensure our monitoring is reliable.
    """
    import subprocess

    # Run the monitoring script
    result = subprocess.run(
        ['bash', 'bin/monitoring/check_vegas_line_coverage.sh', '--days', '1'],
        capture_output=True,
        text=True,
        timeout=30
    )

    # Script should not crash
    assert result.returncode in [0, 1, 2], (
        f"Vegas coverage monitoring script failed unexpectedly:\n{result.stderr}"
    )

    # Output should contain coverage percentage
    assert "coverage" in result.stdout.lower() or "%" in result.stdout, (
        "Monitoring script output doesn't contain coverage information"
    )


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v", "-s"])
