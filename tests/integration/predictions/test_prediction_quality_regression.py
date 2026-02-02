"""
Integration tests for prediction quality regression detection.

These tests verify that model performance doesn't degrade below acceptable thresholds.
Critical for detecting issues like:
- Session 66: V8 84% hit rate (fake due to data leakage)
- Session 64: 50.4% hit rate (stale code deployed)
- Feature degradation causing prediction quality drops

Thresholds based on V9 production performance (Session 68+):
- Premium picks (92+ conf, 3+ edge): 55-58% hit rate
- High edge picks (5+ edge): 72%+ hit rate
- Overall MAE: <5.0 points
"""

import pytest
from datetime import datetime, timedelta, date
from google.cloud import bigquery
from typing import Dict, List


@pytest.fixture
def bq_client():
    """BigQuery client for integration tests."""
    return bigquery.Client()


@pytest.mark.integration
@pytest.mark.smoke
def test_premium_picks_hit_rate_above_threshold(bq_client):
    """
    CRITICAL: Premium picks (92+ conf, 3+ edge) must maintain 55%+ hit rate.

    Lower hit rate indicates:
    - Feature degradation
    - Model deployment issue
    - Data quality regression
    """
    # Check last 7 days (need sample size)
    query = """
    SELECT
      COUNT(*) as total_bets,
      ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
      ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
    FROM nba_predictions.prediction_accuracy
    WHERE system_id = 'catboost_v9'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND game_date < CURRENT_DATE()
      AND confidence_score >= 0.92
      AND ABS(predicted_points - line_value) >= 3
      AND prediction_correct IS NOT NULL
    """

    result = list(bq_client.query(query).result())

    if len(result) == 0 or result[0].total_bets == 0:
        pytest.skip("No premium picks in last 7 days to validate")

    row = result[0]
    hit_rate = row.hit_rate
    total_bets = row.total_bets
    mae = row.mae

    # Need minimum sample size for statistical significance
    if total_bets < 20:
        pytest.skip(
            f"Insufficient sample size for premium picks: {total_bets} bets. "
            f"Need at least 20 for valid test. This is normal after grading service "
            f"deployments or during low game volume periods."
        )

    # Hit rate must be above threshold
    assert hit_rate >= 55.0, (
        f"Premium picks hit rate BELOW THRESHOLD: {hit_rate}% ({total_bets} bets)\n"
        f"Expected: ≥55.0%\n"
        f"MAE: {mae} points\n\n"
        f"This indicates model performance degradation. Possible causes:\n"
        f"  1. Feature quality issue (check feature store)\n"
        f"  2. Stale model deployed (check build_commit_sha)\n"
        f"  3. Data pipeline regression\n"
        f"  4. Model drift (need retraining)\n\n"
        f"Check:\n"
        f"  bq query \"SELECT game_date, COUNT(*) as bets, "
        f"ROUND(100.0*COUNTIF(prediction_correct)/COUNT(*),1) as hit_rate "
        f"FROM nba_predictions.prediction_accuracy "
        f"WHERE system_id='catboost_v9' AND confidence_score>=0.92 "
        f"AND ABS(predicted_points-line_value)>=3 AND game_date>=CURRENT_DATE()-7 "
        f"GROUP BY 1 ORDER BY 1 DESC\""
    )


@pytest.mark.integration
def test_high_edge_picks_hit_rate(bq_client):
    """
    High edge picks (5+ points) should maintain 72%+ hit rate.

    These are the model's highest conviction picks.
    """
    query = """
    SELECT
      COUNT(*) as total_bets,
      ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
    FROM nba_predictions.prediction_accuracy
    WHERE system_id = 'catboost_v9'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND game_date < CURRENT_DATE()
      AND ABS(predicted_points - line_value) >= 5
      AND prediction_correct IS NOT NULL
    """

    result = list(bq_client.query(query).result())

    if len(result) == 0 or result[0].total_bets == 0:
        pytest.skip("No high-edge picks in last 7 days")

    row = result[0]
    hit_rate = row.hit_rate
    total_bets = row.total_bets

    assert total_bets >= 30, f"Insufficient high-edge sample: {total_bets} bets"

    assert hit_rate >= 72.0, (
        f"High-edge picks hit rate BELOW THRESHOLD: {hit_rate}% ({total_bets} bets)\n"
        f"Expected: ≥72.0%\n"
        f"High-edge picks should be the model's most accurate predictions."
    )


@pytest.mark.integration
def test_overall_mae_below_threshold(bq_client):
    """
    Overall Mean Absolute Error should be <5.0 points.

    MAE measures prediction accuracy. Higher MAE indicates:
    - Feature degradation
    - Model drift
    - Data quality issues
    """
    query = """
    SELECT
      ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
      COUNT(*) as predictions
    FROM nba_predictions.prediction_accuracy
    WHERE system_id = 'catboost_v9'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND game_date < CURRENT_DATE()
      AND actual_points IS NOT NULL
    """

    result = list(bq_client.query(query).result())

    if len(result) == 0:
        pytest.skip("No predictions to calculate MAE")

    row = result[0]
    mae = row.mae
    count = row.predictions

    assert count >= 100, f"Insufficient sample for MAE: {count} predictions"

    assert mae < 5.0, (
        f"Mean Absolute Error ABOVE THRESHOLD: {mae} points ({count} predictions)\n"
        f"Expected: <5.0 points\n"
        f"Higher MAE indicates prediction quality degradation."
    )


@pytest.mark.integration
def test_no_extreme_performance_variation(bq_client):
    """
    Daily hit rate variation should be within reasonable bounds.

    Large day-to-day swings indicate instability.
    """
    query = """
    SELECT
      game_date,
      COUNT(*) as bets,
      ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
    FROM nba_predictions.prediction_accuracy
    WHERE system_id = 'catboost_v9'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND game_date < CURRENT_DATE()
      AND confidence_score >= 0.92
      AND ABS(predicted_points - line_value) >= 3
      AND prediction_correct IS NOT NULL
    GROUP BY game_date
    HAVING bets >= 10  -- Need minimum sample per day
    ORDER BY game_date DESC
    """

    results = list(bq_client.query(query).result())

    if len(results) < 3:
        pytest.skip("Need at least 3 days of data to check variation")

    # Calculate standard deviation
    hit_rates = [row.hit_rate for row in results]
    mean_hit_rate = sum(hit_rates) / len(hit_rates)
    variance = sum((x - mean_hit_rate) ** 2 for x in hit_rates) / len(hit_rates)
    std_dev = variance ** 0.5

    # Standard deviation should be <15 percentage points
    assert std_dev < 15.0, (
        f"Hit rate variation too high: std_dev={std_dev:.1f}%\n"
        f"Daily hit rates: {[f'{r:.1f}%' for r in hit_rates]}\n"
        f"Mean: {mean_hit_rate:.1f}%\n\n"
        f"Large variation indicates instability. Check:\n"
        f"  - Feature consistency across days\n"
        f"  - Data quality issues\n"
        f"  - Scheduler timing problems"
    )


@pytest.mark.integration
def test_grading_completeness_for_recent_predictions(bq_client):
    """
    Verify predictions are being graded properly.

    Incomplete grading leads to false conclusions about model performance.
    Session 68 lesson: Used 94 graded predictions instead of 6,665 total.
    """
    query = """
    SELECT
      COUNT(*) as predictions,
      (SELECT COUNT(*)
       FROM nba_predictions.prediction_accuracy pa
       WHERE pa.system_id = p.system_id
         AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
         AND pa.game_date < CURRENT_DATE()) as graded
    FROM nba_predictions.player_prop_predictions p
    WHERE system_id = 'catboost_v9'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
      AND game_date < CURRENT_DATE()
    GROUP BY system_id
    """

    result = list(bq_client.query(query).result())

    if len(result) == 0:
        pytest.skip("No recent predictions to check grading")

    row = result[0]
    predictions = row.predictions
    graded = row.graded

    if predictions == 0:
        pytest.skip("No predictions generated in last 3 days")

    grading_pct = (graded / predictions * 100) if predictions > 0 else 0

    assert grading_pct >= 80.0, (
        f"Grading completeness BELOW THRESHOLD: {grading_pct:.1f}%\n"
        f"Predictions: {predictions}\n"
        f"Graded: {graded}\n\n"
        f"Incomplete grading leads to incorrect performance metrics.\n"
        f"Check nba-grading-service and prediction_accuracy table."
    )


@pytest.mark.integration
def test_no_data_leakage_in_recent_predictions(bq_client):
    """
    Verify predictions don't have suspiciously high accuracy (>80%).

    Session 66: V8 had 84% hit rate due to data leakage.
    Unrealistically high accuracy indicates the model is "cheating".
    """
    query = """
    SELECT
      COUNT(*) as total_bets,
      ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
    FROM nba_predictions.prediction_accuracy
    WHERE system_id = 'catboost_v9'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND game_date < CURRENT_DATE()
      AND prediction_correct IS NOT NULL
    """

    result = list(bq_client.query(query).result())

    if len(result) == 0 or result[0].total_bets == 0:
        pytest.skip("No predictions to check for data leakage")

    row = result[0]
    hit_rate = row.hit_rate
    total_bets = row.total_bets

    # Overall hit rate should NOT be above 80% (too good to be true)
    assert hit_rate <= 80.0, (
        f"Hit rate SUSPICIOUSLY HIGH: {hit_rate}% ({total_bets} bets)\n"
        f"This indicates possible DATA LEAKAGE.\n\n"
        f"Session 66 lesson: V8 had 84% hit rate due to feature leakage.\n"
        f"Check:\n"
        f"  1. Feature generation uses only pre-game data\n"
        f"  2. No game results in features\n"
        f"  3. Training data doesn't include test dates\n"
        f"  4. Feature store integrity"
    )


@pytest.mark.integration
def test_model_beats_vegas_rate(bq_client):
    """
    Model should beat Vegas line (be closer to actual) at least 40% of time.

    Lower rate indicates model isn't adding value over Vegas baseline.
    """
    query = """
    SELECT
      COUNT(*) as predictions,
      COUNTIF(ABS(predicted_points - actual_points) < ABS(line_value - actual_points)) as model_closer,
      ROUND(100.0 * COUNTIF(ABS(predicted_points - actual_points) < ABS(line_value - actual_points)) / COUNT(*), 1) as model_beats_vegas_pct
    FROM nba_predictions.prediction_accuracy
    WHERE system_id = 'catboost_v9'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND game_date < CURRENT_DATE()
      AND actual_points IS NOT NULL
      AND line_value IS NOT NULL
    """

    result = list(bq_client.query(query).result())

    if len(result) == 0:
        pytest.skip("No predictions to compare against Vegas")

    row = result[0]
    beat_vegas_pct = row.model_beats_vegas_pct
    predictions = row.predictions

    assert predictions >= 100, f"Insufficient sample: {predictions}"

    # Model should beat Vegas at least 40% of time
    # (Not same as hit rate - this measures accuracy, not OVER/UNDER correctness)
    assert beat_vegas_pct >= 40.0, (
        f"Model beats Vegas rate BELOW THRESHOLD: {beat_vegas_pct}% ({predictions} predictions)\n"
        f"Expected: ≥40.0%\n\n"
        f"Model should be more accurate than Vegas baseline.\n"
        f"Lower rate indicates model isn't adding predictive value."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
