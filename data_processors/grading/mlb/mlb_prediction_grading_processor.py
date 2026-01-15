"""
MLB Prediction Grading Processor

Grades MLB pitcher strikeout predictions against actual game results.
Calculates accuracy metrics and updates prediction records.

Target Table: mlb_predictions.pitcher_strikeouts (updates is_correct, actual_strikeouts)
"""

import logging
from datetime import date, datetime, timezone
from typing import Dict, List, Any, Optional
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class MlbPredictionGradingProcessor:
    """Grade MLB pitcher strikeout predictions."""

    def __init__(self):
        self.bq_client = bigquery.Client()
        self.project_id = "nba-props-platform"
        self.stats = {
            "predictions_graded": 0,
            "correct": 0,
            "incorrect": 0,
            "push": 0,
            "no_result": 0,
        }

    def run(self, opts: Dict[str, Any]) -> bool:
        """
        Grade predictions for a given date.

        Args:
            opts: Dict with 'game_date' (str or date)

        Returns:
            True if grading succeeded, False otherwise
        """
        try:
            game_date = opts.get('game_date')
            if isinstance(game_date, date):
                game_date = game_date.isoformat()

            logger.info(f"Grading MLB predictions for {game_date}")

            # 1. Get predictions for this date
            predictions = self._get_predictions(game_date)
            if not predictions:
                logger.info(f"No predictions found for {game_date}")
                return True

            # 2. Get actual results
            actuals = self._get_actuals(game_date)
            if not actuals:
                logger.warning(f"No actual results found for {game_date}, skipping grading")
                self.stats["no_result"] = len(predictions)
                return True

            # 3. Grade each prediction
            updates = []
            for pred in predictions:
                pitcher_lookup = pred.get('pitcher_lookup')
                predicted_k = pred.get('predicted_strikeouts')
                line = pred.get('strikeouts_line')
                recommendation = pred.get('recommendation')

                actual = actuals.get(pitcher_lookup)
                if actual is None:
                    logger.debug(f"No actual result for {pitcher_lookup}")
                    self.stats["no_result"] += 1
                    continue

                actual_k = actual.get('strikeouts', 0)

                # Determine if prediction was correct
                is_correct = None
                if recommendation == 'OVER':
                    if actual_k > line:
                        is_correct = True
                        self.stats["correct"] += 1
                    elif actual_k < line:
                        is_correct = False
                        self.stats["incorrect"] += 1
                    else:
                        self.stats["push"] += 1
                elif recommendation == 'UNDER':
                    if actual_k < line:
                        is_correct = True
                        self.stats["correct"] += 1
                    elif actual_k > line:
                        is_correct = False
                        self.stats["incorrect"] += 1
                    else:
                        self.stats["push"] += 1
                else:
                    # PASS or unknown
                    self.stats["no_result"] += 1
                    continue

                updates.append({
                    "prediction_id": pred.get('prediction_id'),
                    "actual_strikeouts": actual_k,
                    "is_correct": is_correct,
                    "graded_at": datetime.now(timezone.utc).isoformat(),
                })

                self.stats["predictions_graded"] += 1

            # 4. Update predictions with grades
            if updates:
                self._update_predictions(updates)

            logger.info(f"Grading complete for {game_date}: {self.stats}")
            return True

        except Exception as e:
            logger.error(f"Error grading predictions: {e}", exc_info=True)
            return False

    def _get_predictions(self, game_date: str) -> List[Dict]:
        """Get predictions for a game date."""
        query = f"""
        SELECT
            prediction_id,
            pitcher_lookup,
            predicted_strikeouts,
            strikeouts_line,
            recommendation
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date = '{game_date}'
        """
        try:
            return [dict(row) for row in self.bq_client.query(query).result()]
        except Exception as e:
            logger.error(f"Error getting predictions: {e}")
            return []

    def _get_actuals(self, game_date: str) -> Dict[str, Dict]:
        """Get actual pitcher strikeouts for a game date."""
        query = f"""
        SELECT
            player_lookup,
            strikeouts,
            innings_pitched
        FROM `{self.project_id}.mlb_raw.mlb_pitcher_stats`
        WHERE game_date = '{game_date}'
          AND is_starter = TRUE
        """
        try:
            results = {}
            for row in self.bq_client.query(query).result():
                results[row.player_lookup] = {
                    "strikeouts": row.strikeouts,
                    "innings_pitched": row.innings_pitched,
                }
            return results
        except Exception as e:
            logger.error(f"Error getting actuals: {e}")
            return {}

    def _update_predictions(self, updates: List[Dict]):
        """Update predictions with grading results."""
        for update in updates:
            query = f"""
            UPDATE `{self.project_id}.mlb_predictions.pitcher_strikeouts`
            SET actual_strikeouts = {update['actual_strikeouts']},
                is_correct = {str(update['is_correct']).upper() if update['is_correct'] is not None else 'NULL'},
                graded_at = TIMESTAMP('{update['graded_at']}')
            WHERE prediction_id = '{update['prediction_id']}'
            """
            try:
                self.bq_client.query(query).result()
            except Exception as e:
                logger.warning(f"Error updating prediction {update['prediction_id']}: {e}")

    def get_grading_stats(self) -> Dict:
        """Get grading statistics."""
        return self.stats.copy()

    def analyze_timing(self, game_date: str) -> Dict:
        """
        Analyze prediction accuracy by line timing buckets.

        v3.6 feature: Compare accuracy for VERY_EARLY, EARLY, and CLOSING lines.

        Args:
            game_date: Game date to analyze

        Returns:
            Dict with accuracy by timing bucket
        """
        query = f"""
        SELECT
            CASE
                WHEN line_minutes_before_game > 240 THEN 'VERY_EARLY'
                WHEN line_minutes_before_game > 60 THEN 'EARLY'
                WHEN line_minutes_before_game > 0 THEN 'CLOSING'
                ELSE 'UNKNOWN'
            END as timing_bucket,
            COUNT(*) as predictions,
            COUNTIF(is_correct = TRUE) as correct,
            COUNTIF(is_correct = FALSE) as incorrect,
            COUNTIF(is_correct IS NULL AND recommendation IN ('OVER', 'UNDER')) as push,
            ROUND(
                COUNTIF(is_correct = TRUE) * 100.0 /
                NULLIF(COUNTIF(is_correct IS NOT NULL), 0),
                1
            ) as accuracy_pct,
            AVG(line_minutes_before_game) as avg_minutes_before
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date = '{game_date}'
          AND is_correct IS NOT NULL
          AND line_minutes_before_game IS NOT NULL
        GROUP BY timing_bucket
        ORDER BY avg_minutes_before DESC
        """
        try:
            results = {}
            for row in self.bq_client.query(query).result():
                results[row.timing_bucket] = {
                    'predictions': row.predictions,
                    'correct': row.correct,
                    'incorrect': row.incorrect,
                    'push': row.push,
                    'accuracy_pct': row.accuracy_pct,
                    'avg_minutes_before': row.avg_minutes_before,
                }
            return results
        except Exception as e:
            logger.error(f"Error analyzing timing: {e}")
            return {}

    def get_timing_summary(self, days: int = 30) -> Dict:
        """
        Get timing analysis summary over multiple days.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with aggregated timing analysis
        """
        query = f"""
        SELECT
            CASE
                WHEN line_minutes_before_game > 240 THEN 'VERY_EARLY'
                WHEN line_minutes_before_game > 60 THEN 'EARLY'
                WHEN line_minutes_before_game > 0 THEN 'CLOSING'
                ELSE 'UNKNOWN'
            END as timing_bucket,
            COUNT(*) as predictions,
            COUNTIF(is_correct = TRUE) as correct,
            ROUND(
                COUNTIF(is_correct = TRUE) * 100.0 /
                NULLIF(COUNTIF(is_correct IS NOT NULL), 0),
                1
            ) as accuracy_pct,
            AVG(line_minutes_before_game) as avg_minutes_before,
            MIN(line_minutes_before_game) as min_minutes,
            MAX(line_minutes_before_game) as max_minutes
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND is_correct IS NOT NULL
          AND line_minutes_before_game IS NOT NULL
        GROUP BY timing_bucket
        ORDER BY avg_minutes_before DESC
        """
        try:
            results = {}
            for row in self.bq_client.query(query).result():
                results[row.timing_bucket] = {
                    'predictions': row.predictions,
                    'correct': row.correct,
                    'accuracy_pct': row.accuracy_pct,
                    'avg_minutes_before': row.avg_minutes_before,
                    'min_minutes': row.min_minutes,
                    'max_minutes': row.max_minutes,
                }
            return results
        except Exception as e:
            logger.error(f"Error getting timing summary: {e}")
            return {}
