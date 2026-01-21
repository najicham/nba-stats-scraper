"""
MLB Shadow Mode Grading Processor

Grades shadow mode predictions (V1.4 vs V1.6) against actual game results.
Updates shadow_mode_predictions table with accuracy for both models.

Target Table: mlb_predictions.shadow_mode_predictions
"""

import logging
from datetime import date, datetime, timezone
from typing import Dict, List, Any, Optional
from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client

logger = logging.getLogger(__name__)


class MlbShadowModeGradingProcessor:
    """Grade MLB shadow mode predictions comparing V1.4 vs V1.6."""

    def __init__(self):
        self.project_id = "nba-props-platform"
        self.bq_client = get_bigquery_client(project_id=self.project_id)
        self.stats = {
            "predictions_graded": 0,
            "v1_4_correct": 0,
            "v1_4_incorrect": 0,
            "v1_6_correct": 0,
            "v1_6_incorrect": 0,
            "v1_6_closer": 0,
            "v1_4_closer": 0,
            "ties": 0,
            "no_result": 0,
        }

    def run(self, opts: Dict[str, Any]) -> bool:
        """
        Grade shadow predictions for a given date.

        Args:
            opts: Dict with 'game_date' (str or date), optional 'dry_run' (bool)

        Returns:
            True if grading succeeded, False otherwise
        """
        try:
            game_date = opts.get('game_date')
            if isinstance(game_date, date):
                game_date = game_date.isoformat()

            dry_run = opts.get('dry_run', False)

            logger.info(f"Grading shadow mode predictions for {game_date} (dry_run={dry_run})")

            # 1. Get shadow predictions for this date
            predictions = self._get_shadow_predictions(game_date)
            if not predictions:
                logger.info(f"No shadow predictions found for {game_date}")
                return True

            logger.info(f"Found {len(predictions)} shadow predictions to grade")

            # 2. Get actual results
            actuals = self._get_actuals(game_date)
            if not actuals:
                logger.warning(f"No actual results found for {game_date}, skipping grading")
                self.stats["no_result"] = len(predictions)
                return True

            logger.info(f"Found {len(actuals)} actual pitcher results")

            # 3. Grade each prediction
            updates = []
            for pred in predictions:
                pitcher_lookup = pred.get('pitcher_lookup')
                line = pred.get('strikeouts_line')

                actual = actuals.get(pitcher_lookup)
                if actual is None:
                    logger.debug(f"No actual result for {pitcher_lookup}")
                    self.stats["no_result"] += 1
                    continue

                actual_k = actual.get('strikeouts', 0)

                # Grade V1.4
                v1_4_correct = self._grade_recommendation(
                    pred.get('v1_4_recommendation'), actual_k, line
                )

                # Grade V1.6
                v1_6_correct = self._grade_recommendation(
                    pred.get('v1_6_recommendation'), actual_k, line
                )

                # Calculate errors
                v1_4_predicted = pred.get('v1_4_predicted') or 0
                v1_6_predicted = pred.get('v1_6_predicted') or 0
                v1_4_error = v1_4_predicted - actual_k
                v1_6_error = v1_6_predicted - actual_k

                # Determine which prediction was closer
                v1_4_abs_error = abs(v1_4_error)
                v1_6_abs_error = abs(v1_6_error)
                if v1_4_abs_error < v1_6_abs_error:
                    closer_prediction = 'v1_4'
                    self.stats["v1_4_closer"] += 1
                elif v1_6_abs_error < v1_4_abs_error:
                    closer_prediction = 'v1_6'
                    self.stats["v1_6_closer"] += 1
                else:
                    closer_prediction = 'tie'
                    self.stats["ties"] += 1

                # Track correct/incorrect stats
                if v1_4_correct is True:
                    self.stats["v1_4_correct"] += 1
                elif v1_4_correct is False:
                    self.stats["v1_4_incorrect"] += 1

                if v1_6_correct is True:
                    self.stats["v1_6_correct"] += 1
                elif v1_6_correct is False:
                    self.stats["v1_6_incorrect"] += 1

                updates.append({
                    "pitcher_lookup": pitcher_lookup,
                    "game_date": game_date,
                    "actual_strikeouts": actual_k,
                    "v1_4_error": v1_4_error,
                    "v1_6_error": v1_6_error,
                    "v1_4_correct": v1_4_correct,
                    "v1_6_correct": v1_6_correct,
                    "closer_prediction": closer_prediction,
                    "graded_at": datetime.now(timezone.utc).isoformat(),
                })

                self.stats["predictions_graded"] += 1

            # 4. Update predictions with grades
            if updates:
                if dry_run:
                    logger.info(f"DRY RUN: Would update {len(updates)} predictions")
                    self._print_sample_updates(updates[:5])
                else:
                    self._update_predictions(updates, game_date)

            # Log summary
            self._log_summary(game_date)
            return True

        except Exception as e:
            logger.error(f"Error grading shadow predictions: {e}", exc_info=True)
            return False

    def _grade_recommendation(
        self, recommendation: Optional[str], actual_k: int, line: float
    ) -> Optional[bool]:
        """
        Grade a single recommendation against actual result.

        Returns:
            True if correct, False if incorrect, None if push/PASS
        """
        if not recommendation or recommendation == 'PASS':
            return None

        if recommendation == 'OVER':
            if actual_k > line:
                return True
            elif actual_k < line:
                return False
            else:
                return None  # Push
        elif recommendation == 'UNDER':
            if actual_k < line:
                return True
            elif actual_k > line:
                return False
            else:
                return None  # Push

        return None

    def _get_shadow_predictions(self, game_date: str) -> List[Dict]:
        """Get shadow predictions for a game date."""
        query = f"""
        SELECT
            pitcher_lookup,
            strikeouts_line,
            v1_4_predicted,
            v1_4_recommendation,
            v1_6_predicted,
            v1_6_recommendation
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE game_date = '{game_date}'
          AND actual_strikeouts IS NULL
        """
        try:
            return [dict(row) for row in self.bq_client.query(query).result()]
        except Exception as e:
            logger.error(f"Error getting shadow predictions: {e}")
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

    def _update_predictions(self, updates: List[Dict], game_date: str):
        """Update shadow predictions with grading results using batch UPDATE."""
        # Build CASE statements for batch update
        cases_actual = []
        cases_v1_4_error = []
        cases_v1_6_error = []
        cases_v1_4_correct = []
        cases_v1_6_correct = []
        cases_closer = []
        pitchers = []

        for u in updates:
            pitcher = u['pitcher_lookup']
            pitchers.append(f"'{pitcher}'")

            cases_actual.append(
                f"WHEN pitcher_lookup = '{pitcher}' THEN {u['actual_strikeouts']}"
            )
            cases_v1_4_error.append(
                f"WHEN pitcher_lookup = '{pitcher}' THEN {u['v1_4_error']}"
            )
            cases_v1_6_error.append(
                f"WHEN pitcher_lookup = '{pitcher}' THEN {u['v1_6_error']}"
            )

            v1_4_val = 'TRUE' if u['v1_4_correct'] is True else ('FALSE' if u['v1_4_correct'] is False else 'CAST(NULL AS BOOL)')
            v1_6_val = 'TRUE' if u['v1_6_correct'] is True else ('FALSE' if u['v1_6_correct'] is False else 'CAST(NULL AS BOOL)')

            cases_v1_4_correct.append(
                f"WHEN pitcher_lookup = '{pitcher}' THEN {v1_4_val}"
            )
            cases_v1_6_correct.append(
                f"WHEN pitcher_lookup = '{pitcher}' THEN {v1_6_val}"
            )
            cases_closer.append(
                f"WHEN pitcher_lookup = '{pitcher}' THEN '{u['closer_prediction']}'"
            )

        graded_at = updates[0]['graded_at']

        query = f"""
        UPDATE `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        SET
            actual_strikeouts = CASE {' '.join(cases_actual)} END,
            v1_4_error = CASE {' '.join(cases_v1_4_error)} END,
            v1_6_error = CASE {' '.join(cases_v1_6_error)} END,
            v1_4_correct = CASE {' '.join(cases_v1_4_correct)} END,
            v1_6_correct = CASE {' '.join(cases_v1_6_correct)} END,
            closer_prediction = CASE {' '.join(cases_closer)} END,
            graded_at = TIMESTAMP('{graded_at}')
        WHERE game_date = '{game_date}'
          AND pitcher_lookup IN ({', '.join(pitchers)})
        """

        try:
            result = self.bq_client.query(query).result()
            logger.info(f"Updated {len(updates)} shadow predictions for {game_date}")
        except Exception as e:
            logger.error(f"Error batch updating predictions: {e}")
            # Fall back to individual updates
            self._update_predictions_individual(updates)

    def _update_predictions_individual(self, updates: List[Dict]):
        """Fallback: Update predictions one at a time."""
        for u in updates:
            v1_4_val = 'TRUE' if u['v1_4_correct'] is True else ('FALSE' if u['v1_4_correct'] is False else 'CAST(NULL AS BOOL)')
            v1_6_val = 'TRUE' if u['v1_6_correct'] is True else ('FALSE' if u['v1_6_correct'] is False else 'CAST(NULL AS BOOL)')

            query = f"""
            UPDATE `{self.project_id}.mlb_predictions.shadow_mode_predictions`
            SET
                actual_strikeouts = {u['actual_strikeouts']},
                v1_4_error = {u['v1_4_error']},
                v1_6_error = {u['v1_6_error']},
                v1_4_correct = {v1_4_val},
                v1_6_correct = {v1_6_val},
                closer_prediction = '{u['closer_prediction']}',
                graded_at = TIMESTAMP('{u['graded_at']}')
            WHERE game_date = '{u['game_date']}'
              AND pitcher_lookup = '{u['pitcher_lookup']}'
            """
            try:
                self.bq_client.query(query).result()
            except Exception as e:
                logger.warning(f"Error updating {u['pitcher_lookup']}: {e}")

    def _print_sample_updates(self, updates: List[Dict]):
        """Print sample updates for dry run."""
        logger.info("Sample updates:")
        for u in updates:
            logger.info(
                f"  {u['pitcher_lookup']}: actual={u['actual_strikeouts']}, "
                f"v1_4_correct={u['v1_4_correct']}, v1_6_correct={u['v1_6_correct']}, "
                f"closer={u['closer_prediction']}"
            )

    def _log_summary(self, game_date: str):
        """Log grading summary."""
        v1_4_total = self.stats['v1_4_correct'] + self.stats['v1_4_incorrect']
        v1_6_total = self.stats['v1_6_correct'] + self.stats['v1_6_incorrect']

        v1_4_pct = (self.stats['v1_4_correct'] / v1_4_total * 100) if v1_4_total > 0 else 0
        v1_6_pct = (self.stats['v1_6_correct'] / v1_6_total * 100) if v1_6_total > 0 else 0

        logger.info(f"\n{'='*60}")
        logger.info(f"Shadow Mode Grading Summary for {game_date}")
        logger.info(f"{'='*60}")
        logger.info(f"Predictions graded: {self.stats['predictions_graded']}")
        logger.info(f"No result/skipped:  {self.stats['no_result']}")
        logger.info(f"")
        logger.info(f"V1.4 (Champion):  {self.stats['v1_4_correct']}/{v1_4_total} = {v1_4_pct:.1f}%")
        logger.info(f"V1.6 (Challenger): {self.stats['v1_6_correct']}/{v1_6_total} = {v1_6_pct:.1f}%")
        logger.info(f"")
        logger.info(f"Closer prediction: V1.4={self.stats['v1_4_closer']}, V1.6={self.stats['v1_6_closer']}, Tie={self.stats['ties']}")
        logger.info(f"{'='*60}\n")

    def get_grading_stats(self) -> Dict:
        """Get grading statistics."""
        return self.stats.copy()

    def grade_pending(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Grade all pending shadow predictions (games that have completed).

        Returns:
            Dict with dates graded and aggregate stats
        """
        # Find dates with pending predictions
        query = f"""
        SELECT DISTINCT game_date
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE actual_strikeouts IS NULL
          AND game_date < CURRENT_DATE()
        ORDER BY game_date
        """

        try:
            dates = [row.game_date for row in self.bq_client.query(query).result()]
        except Exception as e:
            logger.error(f"Error finding pending dates: {e}")
            return {"error": str(e)}

        if not dates:
            logger.info("No pending shadow predictions to grade")
            return {"dates_graded": 0}

        logger.info(f"Found {len(dates)} dates with pending shadow predictions")

        results = {"dates_graded": 0, "dates": []}
        for game_date in dates:
            date_str = game_date.isoformat() if isinstance(game_date, date) else str(game_date)
            logger.info(f"Grading {date_str}...")

            # Reset stats for each date
            self.stats = {
                "predictions_graded": 0,
                "v1_4_correct": 0,
                "v1_4_incorrect": 0,
                "v1_6_correct": 0,
                "v1_6_incorrect": 0,
                "v1_6_closer": 0,
                "v1_4_closer": 0,
                "ties": 0,
                "no_result": 0,
            }

            success = self.run({"game_date": date_str, "dry_run": dry_run})
            if success:
                results["dates_graded"] += 1
                results["dates"].append({
                    "date": date_str,
                    "stats": self.stats.copy()
                })

        return results


# CLI interface
if __name__ == "__main__":
    import argparse
    from datetime import datetime

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    parser = argparse.ArgumentParser(description="Grade MLB shadow mode predictions")
    parser.add_argument(
        "--date",
        type=str,
        help="Game date to grade (YYYY-MM-DD). If not specified, grades all pending."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes"
    )

    args = parser.parse_args()

    processor = MlbShadowModeGradingProcessor()

    if args.date:
        # Grade specific date
        processor.run({"game_date": args.date, "dry_run": args.dry_run})
    else:
        # Grade all pending
        results = processor.grade_pending(dry_run=args.dry_run)
        print(f"\nGraded {results.get('dates_graded', 0)} dates")
