"""
BigQuery Service for Admin Dashboard

Queries BigQuery for pipeline status, game details, and historical data.
Supports both NBA and MLB sports via sport parameter.
"""

import os
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# Sport-specific dataset mappings
SPORT_DATASETS = {
    'nba': {
        'raw': 'nba_raw',
        'analytics': 'nba_analytics',
        'predictions': 'nba_predictions',
        'precompute': 'nba_precompute',
        'orchestration': 'nba_orchestration',
        'reference': 'nba_reference',
    },
    'mlb': {
        'raw': 'mlb_raw',
        'analytics': 'mlb_analytics',
        'predictions': 'mlb_predictions',
        'precompute': 'mlb_precompute',
        'orchestration': 'mlb_orchestration',
        'reference': 'mlb_reference',
    }
}


class BigQueryService:
    """Service for querying BigQuery pipeline data."""

    def __init__(self, sport: str = 'nba'):
        """
        Initialize BigQuery service for a specific sport.

        Args:
            sport: 'nba' or 'mlb' (default: 'nba')
        """
        self.client = bigquery.Client(project=PROJECT_ID)
        self.sport = sport.lower()
        self.datasets = SPORT_DATASETS.get(self.sport, SPORT_DATASETS['nba'])

    def get_daily_status(self, target_date: date) -> Optional[Dict]:
        """
        Get pipeline status for a specific date.

        Returns dict with:
        - games_scheduled: Number of games
        - phase3_context: Player context records
        - phase4_features: ML feature records
        - predictions: Active prediction count
        - pipeline_status: Overall status (COMPLETE, PHASE_X_PENDING, etc.)
        """
        query = f"""
        SELECT
            game_date,
            games_scheduled,
            phase3_context,
            phase4_features,
            predictions,
            players_with_predictions,
            pipeline_status
        FROM `{PROJECT_ID}.nba_orchestration.daily_phase_status`
        WHERE game_date = '{target_date.isoformat()}'
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            if result:
                row = result[0]
                return {
                    'game_date': str(row.game_date),
                    'games_scheduled': row.games_scheduled,
                    'phase3_context': row.phase3_context,
                    'phase4_features': row.phase4_features,
                    'predictions': row.predictions,
                    'players_with_predictions': row.players_with_predictions,
                    'pipeline_status': row.pipeline_status
                }
            else:
                # No data for this date
                return {
                    'game_date': target_date.isoformat(),
                    'games_scheduled': 0,
                    'phase3_context': 0,
                    'phase4_features': 0,
                    'predictions': 0,
                    'players_with_predictions': 0,
                    'pipeline_status': 'NO_DATA'
                }
        except Exception as e:
            logger.error(f"Error querying daily status: {e}")
            raise

    def get_games_detail(self, target_date: date) -> List[Dict]:
        """
        Get detailed status per game for a specific date.

        Returns list of games with context/feature/prediction counts.
        """
        query = f"""
        WITH games AS (
            SELECT
                game_id,
                game_date,
                home_team_name,
                away_team_name,
                home_team_tricode,
                away_team_tricode,
                game_status_text
            FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
            WHERE game_date = '{target_date.isoformat()}'
        ),
        context AS (
            SELECT game_id, COUNT(*) as context_count
            FROM `{PROJECT_ID}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = '{target_date.isoformat()}'
            GROUP BY game_id
        ),
        features AS (
            SELECT game_id, COUNT(*) as feature_count
            FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
            WHERE game_date = '{target_date.isoformat()}'
            GROUP BY game_id
        ),
        predictions AS (
            SELECT game_id, COUNT(*) as prediction_count
            FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
            WHERE game_date = '{target_date.isoformat()}'
              AND is_active = TRUE
            GROUP BY game_id
        )
        SELECT
            g.game_id,
            g.home_team_name,
            g.away_team_name,
            g.home_team_tricode,
            g.away_team_tricode,
            g.game_status_text,
            COALESCE(c.context_count, 0) as context_count,
            COALESCE(f.feature_count, 0) as feature_count,
            COALESCE(p.prediction_count, 0) as prediction_count,
            CASE
                WHEN COALESCE(p.prediction_count, 0) > 0 THEN 'COMPLETE'
                WHEN COALESCE(f.feature_count, 0) > 0 THEN 'PHASE_5_PENDING'
                WHEN COALESCE(c.context_count, 0) > 0 THEN 'PHASE_4_PENDING'
                ELSE 'PHASE_3_PENDING'
            END as game_status
        FROM games g
        LEFT JOIN context c ON g.game_id = c.game_id
        LEFT JOIN features f ON g.game_id = f.game_id
        LEFT JOIN predictions p ON g.game_id = p.game_id
        ORDER BY g.game_id
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'game_id': row.game_id,
                    'home_team': row.home_team_name,
                    'away_team': row.away_team_name,
                    'home_abbr': row.home_team_tricode,
                    'away_abbr': row.away_team_tricode,
                    'game_status_text': row.game_status_text,
                    'context_count': row.context_count,
                    'feature_count': row.feature_count,
                    'prediction_count': row.prediction_count,
                    'pipeline_status': row.game_status
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying game details: {e}")
            raise

    def get_pipeline_history(self, days: int = 7) -> List[Dict]:
        """
        Get pipeline status for the last N days.

        Returns list of daily status records.
        """
        query = f"""
        SELECT
            game_date,
            games_scheduled,
            phase3_context,
            phase4_features,
            predictions,
            players_with_predictions,
            pipeline_status
        FROM `{PROJECT_ID}.nba_orchestration.daily_phase_status`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND game_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY)
        ORDER BY game_date DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'game_date': str(row.game_date),
                    'games_scheduled': row.games_scheduled,
                    'phase3_context': row.phase3_context,
                    'phase4_features': row.phase4_features,
                    'predictions': row.predictions,
                    'players_with_predictions': row.players_with_predictions,
                    'pipeline_status': row.pipeline_status
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying pipeline history: {e}")
            raise

    def get_processor_stats(self, target_date: date, processor_name: str) -> Optional[Dict]:
        """Get stats for a specific processor run."""
        # This could query run_history collection or a dedicated stats table
        # For now, return None - to be implemented
        return None

    def get_processor_failures(self, hours: int = 24) -> List[Dict]:
        """
        Get recent processor failures from processor_run_history.

        Args:
            hours: How many hours back to look (default 24)

        Returns:
            List of failed processor runs with details
        """
        query = f"""
        SELECT
            processor_name,
            data_date,
            run_id,
            status,
            error_message,
            started_at,
            processed_at,
            duration_seconds,
            records_processed,
            phase
        FROM `{PROJECT_ID}.nba_reference.processor_run_history`
        WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
          AND status IN ('failed', 'error')
        ORDER BY started_at DESC
        LIMIT 50
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'processor_name': row.processor_name,
                    'data_date': str(row.data_date) if row.data_date else None,
                    'run_id': row.run_id,
                    'status': row.status,
                    'error_message': row.error_message[:500] if row.error_message else None,
                    'started_at': row.started_at.isoformat() if row.started_at else None,
                    'processed_at': row.processed_at.isoformat() if row.processed_at else None,
                    'duration_seconds': row.duration_seconds,
                    'records_processed': row.records_processed,
                    'phase': row.phase
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying processor failures: {e}")
            return []

    def get_player_game_summary_coverage(self, days: int = 7) -> List[Dict]:
        """
        Get player_game_summary coverage for recent days.

        Shows row counts vs game counts to identify missing data.
        """
        query = f"""
        WITH game_counts AS (
            SELECT
                game_date,
                COUNT(DISTINCT game_id) as games_final
            FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
              AND game_status_text = 'Final'
            GROUP BY game_date
        ),
        summary_counts AS (
            SELECT
                game_date,
                COUNT(*) as summary_rows,
                COUNT(DISTINCT game_id) as games_with_data
            FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
            GROUP BY game_date
        )
        SELECT
            g.game_date,
            g.games_final,
            COALESCE(s.summary_rows, 0) as summary_rows,
            COALESCE(s.games_with_data, 0) as games_with_data,
            CASE
                WHEN g.games_final = 0 THEN 'NO_GAMES'
                WHEN COALESCE(s.summary_rows, 0) = 0 THEN 'MISSING'
                WHEN s.games_with_data < g.games_final THEN 'PARTIAL'
                ELSE 'COMPLETE'
            END as coverage_status
        FROM game_counts g
        LEFT JOIN summary_counts s ON g.game_date = s.game_date
        ORDER BY g.game_date DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'game_date': str(row.game_date),
                    'games_final': row.games_final,
                    'summary_rows': row.summary_rows,
                    'games_with_data': row.games_with_data,
                    'coverage_status': row.coverage_status
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying coverage: {e}")
            return []

    def get_grading_status(self, days: int = 7) -> List[Dict]:
        """
        Get grading status for recent days.

        Shows prediction counts vs graded counts with accuracy metrics.
        Updated to use prediction_grades table (Session 85).
        """
        query = f"""
        WITH predictions AS (
            SELECT
                game_date,
                COUNT(*) as prediction_count
            FROM `{PROJECT_ID}.{self.datasets['predictions']}.player_prop_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
              AND is_active = TRUE
            GROUP BY game_date
        ),
        graded AS (
            SELECT
                game_date,
                COUNT(*) as graded_count,
                ROUND(AVG(margin_of_error), 2) as mae,
                COUNTIF(prediction_correct) as correct,
                COUNTIF(NOT prediction_correct) as incorrect,
                ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 1) as accuracy_pct
            FROM `{PROJECT_ID}.{self.datasets['predictions']}.prediction_grades`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
            GROUP BY game_date
        )
        SELECT
            p.game_date,
            p.prediction_count,
            COALESCE(g.graded_count, 0) as graded_count,
            g.mae,
            g.accuracy_pct,
            CASE
                WHEN COALESCE(g.graded_count, 0) = 0 THEN 'NOT_GRADED'
                WHEN g.graded_count < p.prediction_count * 0.8 THEN 'PARTIAL'
                ELSE 'COMPLETE'
            END as grading_status
        FROM predictions p
        LEFT JOIN graded g ON p.game_date = g.game_date
        ORDER BY p.game_date DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'game_date': str(row.game_date),
                    'prediction_count': row.prediction_count,
                    'graded_count': row.graded_count,
                    'mae': row.mae,
                    'accuracy_pct': row.accuracy_pct,
                    'grading_status': row.grading_status
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying grading status: {e}")
            return []

    def get_grading_by_system(self, days: int = 7) -> List[Dict]:
        """
        Get grading breakdown by prediction system.

        Returns accuracy metrics for each system over the last N days.
        Uses prediction_accuracy_summary view (Session 85).
        """
        query = f"""
        SELECT
            system_id,
            SUM(total_predictions) as total_predictions,
            SUM(correct_predictions) as correct_predictions,
            SUM(incorrect_predictions) as incorrect_predictions,
            ROUND(100.0 * SUM(correct_predictions) / NULLIF(SUM(correct_predictions) + SUM(incorrect_predictions), 0), 1) as accuracy_pct,
            ROUND(AVG(avg_margin_of_error), 1) as avg_margin_of_error,
            ROUND(AVG(avg_confidence), 1) as avg_confidence,
            COUNT(DISTINCT game_date) as days_with_data
        FROM `{PROJECT_ID}.{self.datasets['predictions']}.prediction_accuracy_summary`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND game_date < CURRENT_DATE()
        GROUP BY system_id
        ORDER BY accuracy_pct DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'system_id': row.system_id,
                    'total_predictions': row.total_predictions,
                    'correct_predictions': row.correct_predictions,
                    'incorrect_predictions': row.incorrect_predictions,
                    'accuracy_pct': row.accuracy_pct,
                    'avg_margin_of_error': row.avg_margin_of_error,
                    'avg_confidence': row.avg_confidence,
                    'days_with_data': row.days_with_data
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying grading by system: {e}")
            return []

    def get_calibration_data(self, days: int = 7) -> List[Dict]:
        """
        Get confidence calibration data for prediction systems.

        Returns calibration metrics showing how well confidence scores
        match actual accuracy. Positive calibration_error = overconfident.
        """
        query = f"""
        SELECT
            system_id,
            confidence_bucket,
            total_predictions,
            correct_predictions,
            actual_accuracy_pct,
            avg_confidence,
            calibration_error,
            avg_margin_of_error,
            first_prediction_date,
            last_prediction_date
        FROM `{PROJECT_ID}.{self.datasets['predictions']}.confidence_calibration`
        WHERE last_prediction_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY system_id, confidence_bucket DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'system_id': row.system_id,
                    'confidence_bucket': row.confidence_bucket,
                    'total_predictions': row.total_predictions,
                    'correct_predictions': row.correct_predictions,
                    'actual_accuracy_pct': row.actual_accuracy_pct,
                    'avg_confidence': row.avg_confidence,
                    'calibration_error': row.calibration_error,
                    'avg_margin_of_error': row.avg_margin_of_error,
                    'first_prediction_date': str(row.first_prediction_date),
                    'last_prediction_date': str(row.last_prediction_date)
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying calibration data: {e}")
            return []

    def get_calibration_summary(self, days: int = 7) -> List[Dict]:
        """
        Get summary of calibration health by system.

        Returns systems with average calibration error and flags
        for poor calibration (>15 point error).
        """
        query = f"""
        SELECT
            system_id,
            COUNT(DISTINCT confidence_bucket) as confidence_buckets,
            SUM(total_predictions) as total_predictions,
            ROUND(AVG(ABS(calibration_error)), 2) as avg_abs_calibration_error,
            ROUND(MAX(ABS(calibration_error)), 2) as max_abs_calibration_error,
            ROUND(AVG(calibration_error), 2) as avg_calibration_error,
            CASE
                WHEN AVG(ABS(calibration_error)) > 15 THEN 'POOR'
                WHEN AVG(ABS(calibration_error)) > 10 THEN 'FAIR'
                WHEN AVG(ABS(calibration_error)) > 5 THEN 'GOOD'
                ELSE 'EXCELLENT'
            END as calibration_health
        FROM `{PROJECT_ID}.{self.datasets['predictions']}.confidence_calibration`
        WHERE last_prediction_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND confidence_bucket >= 65  -- Focus on high-confidence predictions
        GROUP BY system_id
        ORDER BY avg_abs_calibration_error DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'system_id': row.system_id,
                    'confidence_buckets': row.confidence_buckets,
                    'total_predictions': row.total_predictions,
                    'avg_abs_calibration_error': row.avg_abs_calibration_error,
                    'max_abs_calibration_error': row.max_abs_calibration_error,
                    'avg_calibration_error': row.avg_calibration_error,
                    'calibration_health': row.calibration_health
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying calibration summary: {e}")
            return []

    def get_roi_summary(self, days: int = 7) -> List[Dict]:
        """
        Get ROI summary by system with flat betting and confidence-based strategies.

        Returns aggregated ROI metrics for all systems with betting simulations.
        """
        query = f"""
        SELECT *
        FROM `{PROJECT_ID}.{self.datasets['predictions']}.roi_summary`
        WHERE last_game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY flat_betting_roi_pct DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'system_id': row.system_id,
                    'total_bets': row.total_bets,
                    'total_wins': row.total_wins,
                    'total_losses': row.total_losses,
                    'win_rate_pct': row.win_rate_pct,
                    'flat_betting_total_profit': row.flat_betting_total_profit,
                    'flat_betting_roi_pct': row.flat_betting_roi_pct,
                    'flat_betting_ev_per_bet': row.flat_betting_ev_per_bet,
                    'high_conf_bets': row.high_conf_bets,
                    'high_conf_wins': row.high_conf_wins,
                    'high_conf_losses': row.high_conf_losses,
                    'high_conf_win_rate_pct': row.high_conf_win_rate_pct,
                    'high_conf_roi_pct': row.high_conf_roi_pct,
                    'high_conf_ev_per_bet': row.high_conf_ev_per_bet,
                    'very_high_conf_bets': row.very_high_conf_bets,
                    'very_high_conf_wins': row.very_high_conf_wins,
                    'very_high_conf_losses': row.very_high_conf_losses,
                    'very_high_conf_win_rate_pct': row.very_high_conf_win_rate_pct,
                    'very_high_conf_roi_pct': row.very_high_conf_roi_pct,
                    'very_high_conf_ev_per_bet': row.very_high_conf_ev_per_bet,
                    'first_game_date': row.first_game_date.isoformat() if row.first_game_date else None,
                    'last_game_date': row.last_game_date.isoformat() if row.last_game_date else None,
                    'days_of_data': row.days_of_data
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying ROI summary: {e}")
            return []

    def get_roi_daily_breakdown(self, days: int = 7) -> List[Dict]:
        """
        Get daily ROI breakdown by system.

        Returns per-day ROI metrics for trend analysis.
        """
        query = f"""
        SELECT *
        FROM `{PROJECT_ID}.{self.datasets['predictions']}.roi_simulation`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY game_date DESC, flat_betting_roi_pct DESC
        LIMIT 500
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'system_id': row.system_id,
                    'game_date': row.game_date.isoformat() if row.game_date else None,
                    'total_bets': row.total_bets,
                    'wins': row.wins,
                    'losses': row.losses,
                    'win_rate_pct': row.win_rate_pct,
                    'flat_betting_profit': row.flat_betting_profit,
                    'flat_betting_roi_pct': row.flat_betting_roi_pct,
                    'flat_betting_ev': row.flat_betting_ev,
                    'high_conf_bets': row.high_conf_bets,
                    'high_conf_roi_pct': row.high_conf_roi_pct,
                    'very_high_conf_bets': row.very_high_conf_bets,
                    'very_high_conf_roi_pct': row.very_high_conf_roi_pct
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying ROI daily breakdown: {e}")
            return []

    def get_player_insights(self, limit_top: int = 10, limit_bottom: int = 10) -> Dict:
        """
        Get most and least predictable players.

        Returns dict with 'most_predictable' and 'least_predictable' lists.
        """
        query_top = f"""
        SELECT *
        FROM `{PROJECT_ID}.{self.datasets['predictions']}.player_insights_summary`
        ORDER BY avg_accuracy_pct DESC
        LIMIT {limit_top}
        """

        query_bottom = f"""
        SELECT *
        FROM `{PROJECT_ID}.{self.datasets['predictions']}.player_insights_summary`
        ORDER BY avg_accuracy_pct ASC
        LIMIT {limit_bottom}
        """

        try:
            most_predictable = list(self.client.query(query_top).result(timeout=60))
            least_predictable = list(self.client.query(query_bottom).result(timeout=60))

            return {
                'most_predictable': [
                    {
                        'player_lookup': row.player_lookup,
                        'systems_tracking': row.systems_tracking,
                        'total_predictions': row.total_predictions,
                        'total_correct': row.total_correct,
                        'total_incorrect': row.total_incorrect,
                        'avg_accuracy_pct': row.avg_accuracy_pct,
                        'avg_margin_of_error': row.avg_margin_of_error,
                        'over_predictions': row.over_predictions,
                        'under_predictions': row.under_predictions,
                        'best_system': row.best_system,
                        'best_system_accuracy': row.best_system_accuracy
                    }
                    for row in most_predictable
                ],
                'least_predictable': [
                    {
                        'player_lookup': row.player_lookup,
                        'systems_tracking': row.systems_tracking,
                        'total_predictions': row.total_predictions,
                        'total_correct': row.total_correct,
                        'total_incorrect': row.total_incorrect,
                        'avg_accuracy_pct': row.avg_accuracy_pct,
                        'avg_margin_of_error': row.avg_margin_of_error,
                        'over_predictions': row.over_predictions,
                        'under_predictions': row.under_predictions,
                        'best_system': row.best_system,
                        'best_system_accuracy': row.best_system_accuracy
                    }
                    for row in least_predictable
                ]
            }
        except Exception as e:
            logger.error(f"Error querying player insights: {e}")
            return {'most_predictable': [], 'least_predictable': []}

    # =========================================================================
    # MLB-specific methods
    # =========================================================================

    def get_mlb_daily_status(self, target_date: date) -> Optional[Dict]:
        """
        Get MLB pipeline status for a specific date.

        Returns dict with:
        - games_scheduled: Number of games
        - analytics_pitchers: Pitcher summary records
        - precompute_features: ML feature records
        - predictions: Prediction count
        - pipeline_status: Overall status
        """
        # Get game count
        games_query = f"""
        SELECT COUNT(DISTINCT game_pk) as games
        FROM `{PROJECT_ID}.mlb_raw.mlb_schedule`
        WHERE game_date = '{target_date.isoformat()}'
        """

        # Get analytics count
        analytics_query = f"""
        SELECT COUNT(*) as cnt
        FROM `{PROJECT_ID}.mlb_analytics.pitcher_game_summary`
        WHERE game_date = '{target_date.isoformat()}'
        """

        # Get precompute count
        precompute_query = f"""
        SELECT COUNT(*) as cnt
        FROM `{PROJECT_ID}.mlb_precompute.pitcher_ml_features`
        WHERE game_date = '{target_date.isoformat()}'
        """

        # Get predictions count
        predictions_query = f"""
        SELECT COUNT(*) as predictions, COUNT(DISTINCT pitcher_lookup) as pitchers
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date = '{target_date.isoformat()}'
        """

        try:
            games = list(self.client.query(games_query).result(timeout=30))
            analytics = list(self.client.query(analytics_query).result(timeout=30))
            precompute = list(self.client.query(precompute_query).result(timeout=30))
            predictions = list(self.client.query(predictions_query).result(timeout=30))

            games_count = games[0].games if games else 0
            analytics_count = analytics[0].cnt if analytics else 0
            precompute_count = precompute[0].cnt if precompute else 0
            predictions_count = predictions[0].predictions if predictions else 0
            pitchers_count = predictions[0].pitchers if predictions else 0

            # Determine status
            if predictions_count > 0:
                status = 'COMPLETE'
            elif precompute_count > 0:
                status = 'PHASE_5_PENDING'
            elif analytics_count > 0:
                status = 'PHASE_4_PENDING'
            elif games_count > 0:
                status = 'PHASE_3_PENDING'
            else:
                status = 'NO_GAMES'

            return {
                'game_date': target_date.isoformat(),
                'games_scheduled': games_count,
                'analytics_pitchers': analytics_count,
                'precompute_features': precompute_count,
                'predictions': predictions_count,
                'pitchers_with_predictions': pitchers_count,
                'pipeline_status': status
            }

        except Exception as e:
            logger.error(f"Error querying MLB daily status: {e}")
            return {
                'game_date': target_date.isoformat(),
                'games_scheduled': 0,
                'analytics_pitchers': 0,
                'precompute_features': 0,
                'predictions': 0,
                'pitchers_with_predictions': 0,
                'pipeline_status': 'ERROR'
            }

    def get_mlb_games_detail(self, target_date: date) -> List[Dict]:
        """
        Get MLB games detail for a specific date.

        Returns list of games with pitcher matchups and prediction status.
        """
        query = f"""
        WITH schedule AS (
            SELECT
                game_pk,
                game_date,
                home_team_abbr,
                away_team_abbr,
                home_probable_pitcher,
                away_probable_pitcher,
                game_status
            FROM `{PROJECT_ID}.mlb_raw.mlb_schedule`
            WHERE game_date = '{target_date.isoformat()}'
        ),
        predictions AS (
            SELECT
                game_id,
                COUNT(*) as prediction_count,
                STRING_AGG(pitcher_lookup, ', ') as pitchers
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date = '{target_date.isoformat()}'
            GROUP BY game_id
        )
        SELECT
            CAST(s.game_pk AS STRING) as game_id,
            s.home_team_abbr,
            s.away_team_abbr,
            s.home_probable_pitcher,
            s.away_probable_pitcher,
            s.game_status,
            COALESCE(p.prediction_count, 0) as prediction_count,
            p.pitchers,
            CASE
                WHEN COALESCE(p.prediction_count, 0) >= 2 THEN 'COMPLETE'
                WHEN COALESCE(p.prediction_count, 0) = 1 THEN 'PARTIAL'
                ELSE 'PENDING'
            END as pipeline_status
        FROM schedule s
        LEFT JOIN predictions p ON CAST(s.game_pk AS STRING) = p.game_id
        ORDER BY s.game_pk
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'game_id': row.game_id,
                    'home_team': row.home_team_abbr,
                    'away_team': row.away_team_abbr,
                    'home_pitcher': row.home_probable_pitcher,
                    'away_pitcher': row.away_probable_pitcher,
                    'game_status': row.game_status,
                    'prediction_count': row.prediction_count,
                    'pitchers': row.pitchers,
                    'pipeline_status': row.pipeline_status
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying MLB game details: {e}")
            return []

    def get_mlb_pipeline_history(self, days: int = 7) -> List[Dict]:
        """
        Get MLB pipeline status for the last N days.
        """
        query = f"""
        WITH dates AS (
            SELECT DATE_SUB(CURRENT_DATE(), INTERVAL day DAY) as game_date
            FROM UNNEST(GENERATE_ARRAY(0, {days})) as day
        ),
        games AS (
            SELECT game_date, COUNT(DISTINCT game_pk) as games
            FROM `{PROJECT_ID}.mlb_raw.mlb_schedule`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            GROUP BY game_date
        ),
        analytics AS (
            SELECT game_date, COUNT(*) as cnt
            FROM `{PROJECT_ID}.mlb_analytics.pitcher_game_summary`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            GROUP BY game_date
        ),
        predictions AS (
            SELECT game_date, COUNT(*) as cnt, COUNT(DISTINCT pitcher_lookup) as pitchers
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            GROUP BY game_date
        )
        SELECT
            d.game_date,
            COALESCE(g.games, 0) as games_scheduled,
            COALESCE(a.cnt, 0) as analytics_count,
            COALESCE(p.cnt, 0) as predictions,
            COALESCE(p.pitchers, 0) as pitchers_count,
            CASE
                WHEN COALESCE(p.cnt, 0) > 0 THEN 'COMPLETE'
                WHEN COALESCE(a.cnt, 0) > 0 THEN 'PENDING'
                WHEN COALESCE(g.games, 0) > 0 THEN 'NO_PREDICTIONS'
                ELSE 'NO_GAMES'
            END as pipeline_status
        FROM dates d
        LEFT JOIN games g ON d.game_date = g.game_date
        LEFT JOIN analytics a ON d.game_date = a.game_date
        LEFT JOIN predictions p ON d.game_date = p.game_date
        ORDER BY d.game_date DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'game_date': str(row.game_date),
                    'games_scheduled': row.games_scheduled,
                    'analytics_count': row.analytics_count,
                    'predictions': row.predictions,
                    'pitchers_count': row.pitchers_count,
                    'pipeline_status': row.pipeline_status
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying MLB pipeline history: {e}")
            return []

    def get_mlb_grading_status(self, days: int = 7) -> List[Dict]:
        """
        Get MLB grading status for recent days.
        """
        query = f"""
        WITH predictions AS (
            SELECT
                game_date,
                COUNT(*) as prediction_count,
                COUNTIF(graded_at IS NOT NULL) as graded_count,
                COUNTIF(is_correct = TRUE) as correct,
                COUNTIF(is_correct = FALSE) as incorrect
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
            GROUP BY game_date
        )
        SELECT
            game_date,
            prediction_count,
            graded_count,
            correct,
            incorrect,
            CASE
                WHEN graded_count = 0 THEN 'NOT_GRADED'
                WHEN graded_count < prediction_count THEN 'PARTIAL'
                ELSE 'COMPLETE'
            END as grading_status,
            ROUND(100.0 * correct / NULLIF(graded_count, 0), 1) as accuracy_pct
        FROM predictions
        ORDER BY game_date DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'game_date': str(row.game_date),
                    'prediction_count': row.prediction_count,
                    'graded_count': row.graded_count,
                    'correct': row.correct,
                    'incorrect': row.incorrect,
                    'grading_status': row.grading_status,
                    'accuracy_pct': row.accuracy_pct
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying MLB grading status: {e}")
            return []

    # =========================================================================
    # Extended History Methods (7d, 14d, 30d, 90d support)
    # =========================================================================

    def get_pipeline_history_extended(self, days: int = 7) -> List[Dict]:
        """
        Get pipeline status for the last N days (supports 7, 14, 30, 90 days).

        Returns list of daily status records with pipeline health indicators.
        """
        # Clamp days to reasonable bounds
        days = max(1, min(90, days))

        query = f"""
        SELECT
            game_date,
            games_scheduled,
            phase3_context,
            phase4_features,
            predictions,
            players_with_predictions,
            pipeline_status,
            CASE
                WHEN games_scheduled = 0 THEN NULL
                ELSE ROUND(100.0 * LEAST(1.0,
                    COALESCE(predictions, 0) / NULLIF(games_scheduled * 15, 0)
                ), 1)
            END as prediction_coverage_pct
        FROM `{PROJECT_ID}.nba_orchestration.daily_phase_status`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND game_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY)
        ORDER BY game_date DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'game_date': str(row.game_date),
                    'games_scheduled': row.games_scheduled,
                    'phase3_context': row.phase3_context,
                    'phase4_features': row.phase4_features,
                    'predictions': row.predictions,
                    'players_with_predictions': row.players_with_predictions,
                    'pipeline_status': row.pipeline_status,
                    'prediction_coverage_pct': row.prediction_coverage_pct
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying extended pipeline history: {e}")
            raise

    def get_weekly_aggregates(self, weeks: int = 4) -> List[Dict]:
        """
        Get weekly aggregated pipeline metrics.

        Args:
            weeks: Number of weeks to look back (default 4, max 13)

        Returns:
            List of weekly aggregate records with totals and averages.
        """
        weeks = max(1, min(13, weeks))

        query = f"""
        WITH daily_data AS (
            SELECT
                game_date,
                DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
                games_scheduled,
                phase3_context,
                phase4_features,
                predictions,
                players_with_predictions,
                pipeline_status
            FROM `{PROJECT_ID}.nba_orchestration.daily_phase_status`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks} WEEK)
              AND game_date < CURRENT_DATE()
        )
        SELECT
            week_start,
            MAX(DATE_ADD(week_start, INTERVAL 6 DAY)) as week_end,
            COUNT(DISTINCT game_date) as days_with_data,
            SUM(games_scheduled) as total_games,
            SUM(predictions) as total_predictions,
            SUM(players_with_predictions) as total_players_with_predictions,
            ROUND(AVG(games_scheduled), 1) as avg_games_per_day,
            ROUND(AVG(predictions), 1) as avg_predictions_per_day,
            COUNTIF(pipeline_status = 'COMPLETE') as days_complete,
            COUNTIF(pipeline_status != 'COMPLETE' AND games_scheduled > 0) as days_incomplete,
            ROUND(100.0 * COUNTIF(pipeline_status = 'COMPLETE') /
                NULLIF(COUNTIF(games_scheduled > 0), 0), 1) as completion_rate_pct
        FROM daily_data
        GROUP BY week_start
        ORDER BY week_start DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'week_start': str(row.week_start),
                    'week_end': str(row.week_end),
                    'days_with_data': row.days_with_data,
                    'total_games': row.total_games,
                    'total_predictions': row.total_predictions,
                    'total_players_with_predictions': row.total_players_with_predictions,
                    'avg_games_per_day': row.avg_games_per_day,
                    'avg_predictions_per_day': row.avg_predictions_per_day,
                    'days_complete': row.days_complete,
                    'days_incomplete': row.days_incomplete,
                    'completion_rate_pct': row.completion_rate_pct
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying weekly aggregates: {e}")
            return []

    def get_monthly_aggregates(self, months: int = 3) -> List[Dict]:
        """
        Get monthly aggregated pipeline metrics.

        Args:
            months: Number of months to look back (default 3, max 6)

        Returns:
            List of monthly aggregate records.
        """
        months = max(1, min(6, months))

        query = f"""
        WITH daily_data AS (
            SELECT
                game_date,
                DATE_TRUNC(game_date, MONTH) as month_start,
                games_scheduled,
                phase3_context,
                phase4_features,
                predictions,
                players_with_predictions,
                pipeline_status
            FROM `{PROJECT_ID}.nba_orchestration.daily_phase_status`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {months} MONTH)
              AND game_date < CURRENT_DATE()
        )
        SELECT
            month_start,
            LAST_DAY(month_start) as month_end,
            COUNT(DISTINCT game_date) as days_with_data,
            SUM(games_scheduled) as total_games,
            SUM(predictions) as total_predictions,
            SUM(players_with_predictions) as total_players_with_predictions,
            ROUND(AVG(games_scheduled), 1) as avg_games_per_day,
            ROUND(AVG(predictions), 1) as avg_predictions_per_day,
            COUNTIF(pipeline_status = 'COMPLETE') as days_complete,
            COUNTIF(pipeline_status != 'COMPLETE' AND games_scheduled > 0) as days_incomplete,
            ROUND(100.0 * COUNTIF(pipeline_status = 'COMPLETE') /
                NULLIF(COUNTIF(games_scheduled > 0), 0), 1) as completion_rate_pct
        FROM daily_data
        GROUP BY month_start
        ORDER BY month_start DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'month_start': str(row.month_start),
                    'month_end': str(row.month_end),
                    'days_with_data': row.days_with_data,
                    'total_games': row.total_games,
                    'total_predictions': row.total_predictions,
                    'total_players_with_predictions': row.total_players_with_predictions,
                    'avg_games_per_day': row.avg_games_per_day,
                    'avg_predictions_per_day': row.avg_predictions_per_day,
                    'days_complete': row.days_complete,
                    'days_incomplete': row.days_incomplete,
                    'completion_rate_pct': row.completion_rate_pct
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying monthly aggregates: {e}")
            return []

    def get_historical_comparison(self, days: int = 7) -> Dict:
        """
        Get historical comparison: current period vs previous period.

        Args:
            days: Number of days for each period

        Returns:
            Dict with current_period, previous_period, and comparison metrics.
        """
        days = max(1, min(45, days))

        query = f"""
        WITH current_period AS (
            SELECT
                'current' as period,
                MIN(game_date) as period_start,
                MAX(game_date) as period_end,
                COUNT(DISTINCT game_date) as days_with_data,
                SUM(games_scheduled) as total_games,
                SUM(predictions) as total_predictions,
                SUM(players_with_predictions) as total_players,
                ROUND(AVG(predictions), 1) as avg_predictions_per_day,
                COUNTIF(pipeline_status = 'COMPLETE') as days_complete,
                ROUND(100.0 * COUNTIF(pipeline_status = 'COMPLETE') /
                    NULLIF(COUNTIF(games_scheduled > 0), 0), 1) as completion_rate_pct
            FROM `{PROJECT_ID}.nba_orchestration.daily_phase_status`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
        ),
        previous_period AS (
            SELECT
                'previous' as period,
                MIN(game_date) as period_start,
                MAX(game_date) as period_end,
                COUNT(DISTINCT game_date) as days_with_data,
                SUM(games_scheduled) as total_games,
                SUM(predictions) as total_predictions,
                SUM(players_with_predictions) as total_players,
                ROUND(AVG(predictions), 1) as avg_predictions_per_day,
                COUNTIF(pipeline_status = 'COMPLETE') as days_complete,
                ROUND(100.0 * COUNTIF(pipeline_status = 'COMPLETE') /
                    NULLIF(COUNTIF(games_scheduled > 0), 0), 1) as completion_rate_pct
            FROM `{PROJECT_ID}.nba_orchestration.daily_phase_status`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days * 2} DAY)
              AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        )
        SELECT * FROM current_period
        UNION ALL
        SELECT * FROM previous_period
        """

        try:
            result = list(self.client.query(query).result(timeout=60))

            current = None
            previous = None

            for row in result:
                data = {
                    'period_start': str(row.period_start) if row.period_start else None,
                    'period_end': str(row.period_end) if row.period_end else None,
                    'days_with_data': row.days_with_data,
                    'total_games': row.total_games,
                    'total_predictions': row.total_predictions,
                    'total_players': row.total_players,
                    'avg_predictions_per_day': row.avg_predictions_per_day,
                    'days_complete': row.days_complete,
                    'completion_rate_pct': row.completion_rate_pct
                }
                if row.period == 'current':
                    current = data
                else:
                    previous = data

            # Compute change percentages
            comparison = {}
            if current and previous:
                def pct_change(curr, prev):
                    if prev is None or prev == 0:
                        return None
                    return round(100.0 * (curr - prev) / prev, 1) if curr else None

                comparison = {
                    'total_games_change_pct': pct_change(
                        current.get('total_games'), previous.get('total_games')),
                    'total_predictions_change_pct': pct_change(
                        current.get('total_predictions'), previous.get('total_predictions')),
                    'avg_predictions_change_pct': pct_change(
                        current.get('avg_predictions_per_day'),
                        previous.get('avg_predictions_per_day')),
                    'completion_rate_change': round(
                        (current.get('completion_rate_pct') or 0) -
                        (previous.get('completion_rate_pct') or 0), 1)
                }

            return {
                'current_period': current,
                'previous_period': previous,
                'comparison': comparison,
                'period_days': days
            }
        except Exception as e:
            logger.error(f"Error querying historical comparison: {e}")
            return {
                'current_period': None,
                'previous_period': None,
                'comparison': {},
                'period_days': days
            }

    def get_grading_history_extended(self, days: int = 7) -> List[Dict]:
        """
        Get extended grading history for the last N days.

        Returns grading metrics with accuracy trends.
        """
        days = max(1, min(90, days))

        query = f"""
        WITH predictions AS (
            SELECT
                game_date,
                COUNT(*) as prediction_count
            FROM `{PROJECT_ID}.{self.datasets['predictions']}.player_prop_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
              AND is_active = TRUE
            GROUP BY game_date
        ),
        graded AS (
            SELECT
                game_date,
                COUNT(*) as graded_count,
                ROUND(AVG(margin_of_error), 2) as mae,
                COUNTIF(prediction_correct) as correct,
                COUNTIF(NOT prediction_correct) as incorrect,
                ROUND(100.0 * COUNTIF(prediction_correct) /
                    NULLIF(COUNT(*), 0), 1) as accuracy_pct
            FROM `{PROJECT_ID}.{self.datasets['predictions']}.prediction_grades`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
            GROUP BY game_date
        )
        SELECT
            p.game_date,
            p.prediction_count,
            COALESCE(g.graded_count, 0) as graded_count,
            COALESCE(g.correct, 0) as correct,
            COALESCE(g.incorrect, 0) as incorrect,
            g.mae,
            g.accuracy_pct,
            CASE
                WHEN COALESCE(g.graded_count, 0) = 0 THEN 'NOT_GRADED'
                WHEN g.graded_count < p.prediction_count * 0.8 THEN 'PARTIAL'
                ELSE 'COMPLETE'
            END as grading_status
        FROM predictions p
        LEFT JOIN graded g ON p.game_date = g.game_date
        ORDER BY p.game_date DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'game_date': str(row.game_date),
                    'prediction_count': row.prediction_count,
                    'graded_count': row.graded_count,
                    'correct': row.correct,
                    'incorrect': row.incorrect,
                    'mae': row.mae,
                    'accuracy_pct': row.accuracy_pct,
                    'grading_status': row.grading_status
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying extended grading history: {e}")
            return []

    def get_weekly_grading_summary(self, weeks: int = 4) -> List[Dict]:
        """
        Get weekly grading summary with accuracy trends.

        Args:
            weeks: Number of weeks to look back

        Returns:
            List of weekly grading summaries.
        """
        weeks = max(1, min(13, weeks))

        query = f"""
        WITH daily_grading AS (
            SELECT
                game_date,
                DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
                margin_of_error,
                prediction_correct
            FROM `{PROJECT_ID}.{self.datasets['predictions']}.prediction_grades`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks} WEEK)
              AND game_date < CURRENT_DATE()
        )
        SELECT
            week_start,
            MAX(DATE_ADD(week_start, INTERVAL 6 DAY)) as week_end,
            COUNT(*) as total_graded,
            COUNTIF(prediction_correct) as correct,
            COUNTIF(NOT prediction_correct) as incorrect,
            ROUND(100.0 * COUNTIF(prediction_correct) /
                NULLIF(COUNT(*), 0), 1) as accuracy_pct,
            ROUND(AVG(margin_of_error), 2) as avg_mae,
            COUNT(DISTINCT game_date) as days_with_grading
        FROM daily_grading
        GROUP BY week_start
        ORDER BY week_start DESC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'week_start': str(row.week_start),
                    'week_end': str(row.week_end),
                    'total_graded': row.total_graded,
                    'correct': row.correct,
                    'incorrect': row.incorrect,
                    'accuracy_pct': row.accuracy_pct,
                    'avg_mae': row.avg_mae,
                    'days_with_grading': row.days_with_grading
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying weekly grading summary: {e}")
            return []

    def get_accuracy_comparison(self, days: int = 7) -> Dict:
        """
        Get accuracy comparison between current and previous periods.

        Args:
            days: Number of days for each comparison period

        Returns:
            Dict with current and previous period accuracy and changes.
        """
        days = max(1, min(45, days))

        query = f"""
        WITH current_period AS (
            SELECT
                'current' as period,
                COUNT(*) as total_graded,
                COUNTIF(prediction_correct) as correct,
                ROUND(100.0 * COUNTIF(prediction_correct) /
                    NULLIF(COUNT(*), 0), 1) as accuracy_pct,
                ROUND(AVG(margin_of_error), 2) as avg_mae
            FROM `{PROJECT_ID}.{self.datasets['predictions']}.prediction_grades`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
        ),
        previous_period AS (
            SELECT
                'previous' as period,
                COUNT(*) as total_graded,
                COUNTIF(prediction_correct) as correct,
                ROUND(100.0 * COUNTIF(prediction_correct) /
                    NULLIF(COUNT(*), 0), 1) as accuracy_pct,
                ROUND(AVG(margin_of_error), 2) as avg_mae
            FROM `{PROJECT_ID}.{self.datasets['predictions']}.prediction_grades`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days * 2} DAY)
              AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        )
        SELECT * FROM current_period
        UNION ALL
        SELECT * FROM previous_period
        """

        try:
            result = list(self.client.query(query).result(timeout=60))

            current = None
            previous = None

            for row in result:
                data = {
                    'total_graded': row.total_graded,
                    'correct': row.correct,
                    'accuracy_pct': row.accuracy_pct,
                    'avg_mae': row.avg_mae
                }
                if row.period == 'current':
                    current = data
                else:
                    previous = data

            # Compute changes
            comparison = {}
            if current and previous:
                prev_graded = previous.get('total_graded') or 1
                comparison = {
                    'accuracy_change': round(
                        (current.get('accuracy_pct') or 0) -
                        (previous.get('accuracy_pct') or 0), 1),
                    'mae_change': round(
                        (current.get('avg_mae') or 0) -
                        (previous.get('avg_mae') or 0), 2),
                    'volume_change_pct': round(
                        100.0 * ((current.get('total_graded') or 0) -
                        (previous.get('total_graded') or 0)) / prev_graded, 1)
                }

            return {
                'current_period': current,
                'previous_period': previous,
                'comparison': comparison,
                'period_days': days
            }
        except Exception as e:
            logger.error(f"Error querying accuracy comparison: {e}")
            return {
                'current_period': None,
                'previous_period': None,
                'comparison': {},
                'period_days': days
            }

    # =========================================================================
    # Trend Chart Data Methods
    # =========================================================================

    def get_prediction_accuracy_trend(self, days: int = 30) -> List[Dict]:
        """
        Get daily prediction accuracy trend across all systems.

        Returns time-series data suitable for charting:
        - date, overall accuracy, high-conf accuracy, predictions count
        """
        days = max(1, min(90, days))

        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_predictions,
            COUNTIF(prediction_correct = TRUE) as correct,
            COUNTIF(prediction_correct = FALSE) as incorrect,
            ROUND(SAFE_DIVIDE(
                COUNTIF(prediction_correct = TRUE),
                COUNTIF(recommendation IN ('OVER', 'UNDER'))
            ) * 100, 2) as accuracy_pct,
            COUNTIF(confidence_score >= 0.70) as high_conf_total,
            COUNTIF(confidence_score >= 0.70 AND prediction_correct = TRUE) as high_conf_correct,
            ROUND(SAFE_DIVIDE(
                COUNTIF(confidence_score >= 0.70 AND prediction_correct = TRUE),
                COUNTIF(confidence_score >= 0.70 AND recommendation IN ('OVER', 'UNDER'))
            ) * 100, 2) as high_conf_accuracy_pct,
            ROUND(AVG(absolute_error), 2) as mae
        FROM `{PROJECT_ID}.{self.datasets['predictions']}.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND game_date < CURRENT_DATE()
          AND is_voided = FALSE
        GROUP BY game_date
        ORDER BY game_date ASC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'date': str(row.game_date),
                    'total_predictions': row.total_predictions,
                    'correct': row.correct,
                    'incorrect': row.incorrect,
                    'accuracy_pct': float(row.accuracy_pct) if row.accuracy_pct else 0,
                    'high_conf_total': row.high_conf_total,
                    'high_conf_correct': row.high_conf_correct,
                    'high_conf_accuracy_pct': float(row.high_conf_accuracy_pct) if row.high_conf_accuracy_pct else 0,
                    'mae': float(row.mae) if row.mae else 0
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying prediction accuracy trend: {e}")
            return []

    def get_pipeline_latency_trend(self, days: int = 30) -> List[Dict]:
        """
        Get daily pipeline processing latency trends.

        Returns average processor durations by phase over time.
        """
        days = max(1, min(90, days))

        query = f"""
        SELECT
            DATE(started_at) as run_date,
            phase,
            COUNT(*) as processor_runs,
            ROUND(AVG(duration_seconds), 1) as avg_duration_sec,
            ROUND(MAX(duration_seconds), 1) as max_duration_sec,
            SUM(records_processed) as total_records
        FROM `{PROJECT_ID}.nba_reference.processor_run_history`
        WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
          AND status = 'completed'
          AND duration_seconds IS NOT NULL
        GROUP BY run_date, phase
        ORDER BY run_date ASC, phase
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'date': str(row.run_date),
                    'phase': row.phase,
                    'processor_runs': row.processor_runs,
                    'avg_duration_sec': float(row.avg_duration_sec) if row.avg_duration_sec else 0,
                    'max_duration_sec': float(row.max_duration_sec) if row.max_duration_sec else 0,
                    'total_records': row.total_records or 0
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying pipeline latency trend: {e}")
            return []

    def get_error_rate_trend(self, days: int = 30) -> List[Dict]:
        """
        Get daily error rate trends from processor run history.

        Returns daily counts of successful vs failed processor runs.
        """
        days = max(1, min(90, days))

        query = f"""
        SELECT
            DATE(started_at) as run_date,
            COUNT(*) as total_runs,
            COUNTIF(status = 'completed') as successful_runs,
            COUNTIF(status IN ('failed', 'error')) as failed_runs,
            COUNTIF(status = 'timeout') as timeout_runs,
            ROUND(SAFE_DIVIDE(COUNTIF(status IN ('failed', 'error', 'timeout')), COUNT(*)) * 100, 2) as error_rate_pct,
            COUNT(DISTINCT processor_name) as unique_processors
        FROM `{PROJECT_ID}.nba_reference.processor_run_history`
        WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        GROUP BY run_date
        ORDER BY run_date ASC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'date': str(row.run_date),
                    'total_runs': row.total_runs,
                    'successful_runs': row.successful_runs,
                    'failed_runs': row.failed_runs,
                    'timeout_runs': row.timeout_runs,
                    'error_rate_pct': float(row.error_rate_pct) if row.error_rate_pct else 0,
                    'unique_processors': row.unique_processors
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying error rate trend: {e}")
            return []

    def get_data_volume_trend(self, days: int = 30) -> List[Dict]:
        """
        Get daily data volume trends.

        Returns counts of games, predictions, and graded predictions over time.
        """
        days = max(1, min(90, days))

        query = f"""
        WITH daily_games AS (
            SELECT
                game_date,
                COUNT(DISTINCT game_id) as games_count
            FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
            GROUP BY game_date
        ),
        daily_predictions AS (
            SELECT
                game_date,
                COUNT(*) as predictions_count,
                COUNT(DISTINCT player_lookup) as players_count,
                COUNT(DISTINCT system_id) as systems_count
            FROM `{PROJECT_ID}.{self.datasets['predictions']}.player_prop_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
              AND is_active = TRUE
            GROUP BY game_date
        ),
        daily_graded AS (
            SELECT
                game_date,
                COUNT(*) as graded_count,
                COUNTIF(prediction_correct = TRUE) as correct_count
            FROM `{PROJECT_ID}.{self.datasets['predictions']}.prediction_grades`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
            GROUP BY game_date
        )
        SELECT
            g.game_date as date,
            COALESCE(g.games_count, 0) as games,
            COALESCE(p.predictions_count, 0) as predictions,
            COALESCE(p.players_count, 0) as players,
            COALESCE(p.systems_count, 0) as systems,
            COALESCE(gr.graded_count, 0) as graded,
            COALESCE(gr.correct_count, 0) as correct
        FROM daily_games g
        LEFT JOIN daily_predictions p ON g.game_date = p.game_date
        LEFT JOIN daily_graded gr ON g.game_date = gr.game_date
        ORDER BY g.game_date ASC
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'date': str(row.date),
                    'games': row.games,
                    'predictions': row.predictions,
                    'players': row.players,
                    'systems': row.systems,
                    'graded': row.graded,
                    'correct': row.correct
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying data volume trend: {e}")
            return []

    def get_accuracy_by_system_trend(self, days: int = 30) -> List[Dict]:
        """
        Get daily accuracy trend broken down by prediction system.

        Returns time-series data for each system separately.
        """
        days = max(1, min(90, days))

        query = f"""
        SELECT
            game_date,
            system_id,
            COUNT(*) as total_predictions,
            COUNTIF(prediction_correct = TRUE) as correct,
            ROUND(SAFE_DIVIDE(
                COUNTIF(prediction_correct = TRUE),
                COUNTIF(recommendation IN ('OVER', 'UNDER'))
            ) * 100, 2) as accuracy_pct
        FROM `{PROJECT_ID}.{self.datasets['predictions']}.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND game_date < CURRENT_DATE()
          AND is_voided = FALSE
        GROUP BY game_date, system_id
        ORDER BY game_date ASC, system_id
        """

        try:
            result = list(self.client.query(query).result(timeout=60))
            return [
                {
                    'date': str(row.game_date),
                    'system_id': row.system_id,
                    'total_predictions': row.total_predictions,
                    'correct': row.correct,
                    'accuracy_pct': float(row.accuracy_pct) if row.accuracy_pct else 0
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying accuracy by system trend: {e}")
            return []
