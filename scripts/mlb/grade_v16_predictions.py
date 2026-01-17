#!/usr/bin/env python3
"""
Grade V1.6 MLB Pitcher Strikeout Predictions

Grades V1.6 predictions against actual game results. Populates is_correct
and actual_strikeouts fields for V1.6 predictions only.

This script processes all V1.6 predictions in the specified date range.
It does NOT touch V1 predictions (different model_version).

Usage:
    PYTHONPATH=. python scripts/mlb/grade_v16_predictions.py
    PYTHONPATH=. python scripts/mlb/grade_v16_predictions.py --start-date 2024-04-09 --end-date 2025-09-28
    PYTHONPATH=. python scripts/mlb/grade_v16_predictions.py --model-version-filter v1_6
"""

import argparse
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"
PREDICTIONS_TABLE = "mlb_predictions.pitcher_strikeouts"


class V16PredictionGrader:
    """Grade V1.6 MLB pitcher strikeout predictions."""

    def __init__(self, model_version_filter: str = "v1_6"):
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.model_version_filter = model_version_filter
        self.stats = {
            "predictions_checked": 0,
            "predictions_graded": 0,
            "already_graded": 0,
            "correct": 0,
            "incorrect": 0,
            "push": 0,
            "no_result": 0,
            "no_recommendation": 0,
        }

    def grade_date_range(self, start_date: str, end_date: str) -> Dict:
        """
        Grade all V1.6 predictions in date range.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Dict with grading statistics
        """
        logger.info(f"Grading V1.6 predictions from {start_date} to {end_date}")

        # Get all ungraded V1.6 predictions
        predictions = self._get_predictions(start_date, end_date)
        logger.info(f"Found {len(predictions)} V1.6 predictions to grade")

        if not predictions:
            logger.info("No ungraded V1.6 predictions found")
            return self.stats

        # Get all actual results for date range
        actuals = self._get_actuals(start_date, end_date)
        logger.info(f"Retrieved actual results for {len(actuals)} pitcher games")

        # Grade each prediction
        updates = []
        for i, pred in enumerate(predictions):
            if (i + 1) % 500 == 0:
                logger.info(f"Processed {i + 1}/{len(predictions)} predictions...")

            self.stats["predictions_checked"] += 1

            pitcher_lookup = pred.get('pitcher_lookup')
            game_date = pred.get('game_date')
            line = pred.get('strikeouts_line')
            recommendation = pred.get('recommendation')

            # Create unique key for lookup
            key = (game_date, pitcher_lookup)
            actual = actuals.get(key)

            if actual is None:
                logger.debug(f"No actual result for {pitcher_lookup} on {game_date}")
                self.stats["no_result"] += 1
                continue

            actual_k = actual.get('strikeouts', 0)

            # Determine if prediction was correct
            is_correct = None
            if recommendation == 'OVER':
                if line is None:
                    logger.debug(f"OVER recommendation but no line for {pitcher_lookup}")
                    self.stats["no_recommendation"] += 1
                    continue
                if actual_k > line:
                    is_correct = True
                    self.stats["correct"] += 1
                elif actual_k < line:
                    is_correct = False
                    self.stats["incorrect"] += 1
                else:
                    # Push (tie)
                    self.stats["push"] += 1
                    # Store push as NULL is_correct
                    is_correct = None
            elif recommendation == 'UNDER':
                if line is None:
                    logger.debug(f"UNDER recommendation but no line for {pitcher_lookup}")
                    self.stats["no_recommendation"] += 1
                    continue
                if actual_k < line:
                    is_correct = True
                    self.stats["correct"] += 1
                elif actual_k > line:
                    is_correct = False
                    self.stats["incorrect"] += 1
                else:
                    # Push (tie)
                    self.stats["push"] += 1
                    is_correct = None
            else:
                # PASS, NO_LINE, or other
                self.stats["no_recommendation"] += 1
                # Still record actual strikeouts even if we don't grade
                updates.append({
                    "prediction_id": pred.get('prediction_id'),
                    "actual_strikeouts": actual_k,
                    "is_correct": None,
                    "graded_at": datetime.now(timezone.utc).isoformat(),
                })
                continue

            updates.append({
                "prediction_id": pred.get('prediction_id'),
                "actual_strikeouts": actual_k,
                "is_correct": is_correct,
                "graded_at": datetime.now(timezone.utc).isoformat(),
            })

            self.stats["predictions_graded"] += 1

        # Update predictions in batches
        if updates:
            logger.info(f"Updating {len(updates)} predictions in BigQuery...")
            self._update_predictions_batch(updates)
            logger.info("Updates complete")

        return self.stats

    def _get_predictions(self, start_date: str, end_date: str) -> List[Dict]:
        """Get ungraded V1.6 predictions for date range."""
        query = f"""
        SELECT
            prediction_id,
            game_date,
            pitcher_lookup,
            predicted_strikeouts,
            strikeouts_line,
            recommendation,
            model_version
        FROM `{PROJECT_ID}.{PREDICTIONS_TABLE}`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND model_version LIKE '%{self.model_version_filter}%'
          AND is_correct IS NULL  -- Only ungraded
        ORDER BY game_date, pitcher_lookup
        """
        try:
            results = []
            for row in self.bq_client.query(query).result():
                results.append({
                    'prediction_id': row.prediction_id,
                    'game_date': row.game_date.isoformat() if hasattr(row.game_date, 'isoformat') else str(row.game_date),
                    'pitcher_lookup': row.pitcher_lookup,
                    'predicted_strikeouts': row.predicted_strikeouts,
                    'strikeouts_line': row.strikeouts_line,
                    'recommendation': row.recommendation,
                    'model_version': row.model_version,
                })
            return results
        except Exception as e:
            logger.error(f"Error getting predictions: {e}", exc_info=True)
            return []

    def _get_actuals(self, start_date: str, end_date: str) -> Dict[tuple, Dict]:
        """Get actual pitcher strikeouts for date range."""
        query = f"""
        SELECT
            game_date,
            player_lookup,
            strikeouts,
            innings_pitched
        FROM `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND is_starter = TRUE
          AND strikeouts IS NOT NULL
        """
        try:
            results = {}
            for row in self.bq_client.query(query).result():
                game_date = row.game_date.isoformat() if hasattr(row.game_date, 'isoformat') else str(row.game_date)
                key = (game_date, row.player_lookup)
                results[key] = {
                    "strikeouts": row.strikeouts,
                    "innings_pitched": row.innings_pitched,
                }
            return results
        except Exception as e:
            logger.error(f"Error getting actuals: {e}", exc_info=True)
            return {}

    def _update_predictions_batch(self, updates: List[Dict]):
        """Update predictions with grading results using batch UPDATE."""
        # BigQuery doesn't support batch UPDATE well, so we'll do individual UPDATEs
        # but collect them for better error handling

        success_count = 0
        error_count = 0

        for i, update in enumerate(updates):
            if (i + 1) % 100 == 0:
                logger.info(f"Updated {i + 1}/{len(updates)} records...")

            is_correct_str = 'NULL'
            if update['is_correct'] is True:
                is_correct_str = 'TRUE'
            elif update['is_correct'] is False:
                is_correct_str = 'FALSE'

            query = f"""
            UPDATE `{PROJECT_ID}.{PREDICTIONS_TABLE}`
            SET actual_strikeouts = {update['actual_strikeouts']},
                is_correct = {is_correct_str},
                graded_at = TIMESTAMP('{update['graded_at']}')
            WHERE prediction_id = '{update['prediction_id']}'
            """
            try:
                self.bq_client.query(query).result()
                success_count += 1
            except Exception as e:
                logger.warning(f"Error updating prediction {update['prediction_id']}: {e}")
                error_count += 1

        logger.info(f"Batch update complete: {success_count} successful, {error_count} errors")

    def get_stats(self) -> Dict:
        """Get grading statistics."""
        return self.stats.copy()


def print_summary(stats: Dict):
    """Print grading summary."""
    print()
    print("=" * 80)
    print(" V1.6 GRADING SUMMARY")
    print("=" * 80)
    print(f"Predictions checked: {stats['predictions_checked']}")
    print(f"Predictions graded: {stats['predictions_graded']}")
    print(f"Already graded: {stats['already_graded']}")
    print()
    print(f"Results:")
    print(f"  Correct: {stats['correct']}")
    print(f"  Incorrect: {stats['incorrect']}")
    print(f"  Push (tie): {stats['push']}")
    print(f"  No result: {stats['no_result']}")
    print(f"  No recommendation: {stats['no_recommendation']}")
    print()

    if stats['predictions_graded'] > 0:
        graded = stats['correct'] + stats['incorrect']
        if graded > 0:
            win_rate = stats['correct'] / graded * 100
            print(f"Win Rate: {win_rate:.1f}% ({stats['correct']}/{graded})")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description='Grade V1.6 MLB predictions')
    parser.add_argument('--start-date', default='2024-04-09', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', default='2025-09-28', help='End date (YYYY-MM-DD)')
    parser.add_argument('--model-version-filter', default='v1_6', help='Model version filter')
    args = parser.parse_args()

    print("=" * 80)
    print(" GRADE V1.6 MLB PREDICTIONS")
    print("=" * 80)
    print(f"Date range: {args.start_date} to {args.end_date}")
    print(f"Model filter: {args.model_version_filter}")
    print()

    # Create grader and run
    grader = V16PredictionGrader(model_version_filter=args.model_version_filter)
    stats = grader.grade_date_range(args.start_date, args.end_date)

    # Print summary
    print_summary(stats)

    print()
    print("Next steps:")
    print("  1. Verify V1 unchanged: PYTHONPATH=. python scripts/mlb/verify_v1_unchanged.py")
    print("  2. Compare V1 vs V1.6: PYTHONPATH=. python scripts/mlb/compare_v1_vs_v16_head_to_head.py")
    print()


if __name__ == '__main__':
    main()
