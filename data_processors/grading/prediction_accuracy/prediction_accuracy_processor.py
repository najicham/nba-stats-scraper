"""
Prediction Accuracy Processor (Phase 5B - Grading)

Grades predictions against actual game results for ML training.
Compares predictions from all 5 systems to actual points scored.

Reads from:
- nba_predictions.player_prop_predictions (Phase 5A)
- nba_analytics.player_game_summary (Phase 3) for actual points
- nba_raw.nbac_injury_report (for DNP/injury correlation)

Writes to:
- nba_predictions.prediction_accuracy

Key Features:
- Grades all 5 prediction systems separately
- Computes absolute_error, signed_error (bias direction)
- Evaluates OVER/UNDER recommendation correctness
- Tracks threshold accuracy (within_3_points, within_5_points)
- Computes margin analysis for betting evaluation
- Tracks line source (has_prop_line, line_source) for no-line player analysis
- DNP/Injury voiding (v4): Marks DNP players as voided like sportsbooks void bets
"""

import logging
from datetime import datetime, date, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


class PredictionAccuracyProcessor:
    """
    Processor to grade predictions against actual results.

    For each prediction, computes:
    - absolute_error: |predicted - actual|
    - signed_error: predicted - actual (positive = over-predicted)
    - prediction_correct: Whether OVER/UNDER recommendation was right
    - predicted_margin: predicted_points - line_value
    - actual_margin: actual_points - line_value
    - within_3_points: abs(predicted - actual) <= 3
    - within_5_points: abs(predicted - actual) <= 5
    """

    def __init__(self, project_id: str = PROJECT_ID, dataset_prefix: str = ''):
        import math
        self._math = math
        self.project_id = project_id
        self.dataset_prefix = dataset_prefix
        self.bq_client = bigquery.Client(project=project_id)

        # Construct table names with optional prefix
        predictions_dataset = f"{dataset_prefix}_nba_predictions" if dataset_prefix else "nba_predictions"
        analytics_dataset = f"{dataset_prefix}_nba_analytics" if dataset_prefix else "nba_analytics"
        raw_dataset = f"{dataset_prefix}_nba_raw" if dataset_prefix else "nba_raw"

        self.predictions_table = f'{project_id}.{predictions_dataset}.player_prop_predictions'
        self.actuals_table = f'{project_id}.{analytics_dataset}.player_game_summary'
        self.accuracy_table = f'{project_id}.{predictions_dataset}.prediction_accuracy'
        self.injury_table = f'{project_id}.{raw_dataset}.nbac_injury_report'

        # Cache for injury status lookups (populated per-date)
        self._injury_cache: Dict[str, Dict] = {}

        logger.info(f"Initialized PredictionAccuracyProcessor (dataset_prefix: {dataset_prefix or 'production'})")

    def _is_nan(self, value) -> bool:
        """Check if value is NaN (handles float, numpy, pandas)."""
        if value is None:
            return False
        try:
            return self._math.isnan(float(value))
        except (TypeError, ValueError):
            return False

    def _safe_float(self, value) -> Optional[float]:
        """Convert to float, returning None for NaN or invalid values."""
        if value is None:
            return None
        try:
            f = float(value)
            if self._math.isnan(f) or self._math.isinf(f):
                return None
            return f
        except (TypeError, ValueError):
            return None

    def _safe_string(self, value) -> Optional[str]:
        """Sanitize string for JSON compatibility.

        Removes control characters that break JSON parsing and ensures
        proper encoding for BigQuery load_table_from_json.
        """
        if value is None:
            return None
        try:
            s = str(value)
            # Remove ALL control characters including tab/newline
            # BigQuery load_table_from_json can't handle these in strings
            import re
            s = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', s)
            # Also remove any backslash-quote sequences that might cause issues
            s = s.replace('\\"', '"').replace('\\', '')
            # Remove any stray quotes that could break JSON
            s = s.replace('"', "'")
            # Limit length to prevent oversized values
            return s[:500] if len(s) > 500 else s
        except (TypeError, ValueError):
            return None

    def load_injury_status_for_date(self, game_date: date) -> Dict[str, Dict]:
        """
        Load injury status for all players on a game date.

        Returns dict mapping player_lookup -> {
            'injury_status': 'OUT', 'DOUBTFUL', 'QUESTIONABLE', etc.
            'reason': injury reason text
        }

        Uses the latest report for each player on the game date.
        """
        query = f"""
        SELECT
            player_lookup,
            injury_status,
            reason
        FROM (
            SELECT
                player_lookup,
                UPPER(injury_status) as injury_status,
                reason,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup, game_id
                    ORDER BY report_date DESC, report_hour DESC
                ) as rn
            FROM `{self.injury_table}`
            WHERE game_date = '{game_date}'
        )
        WHERE rn = 1
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            injury_map = {}
            for _, row in result.iterrows():
                injury_map[row['player_lookup']] = {
                    'injury_status': row['injury_status'],
                    'reason': row['reason']
                }
            logger.info(f"  Loaded {len(injury_map)} injury reports for {game_date}")
            return injury_map
        except Exception as e:
            logger.warning(f"Error loading injury status for {game_date}: {e}")
            return {}

    def get_injury_status(self, player_lookup: str, game_date: date) -> Optional[Dict]:
        """
        Get injury status for a player on a game date.

        Returns:
            Dict with 'injury_status' and 'reason', or None if no injury report
        """
        cache_key = game_date.isoformat()
        if cache_key not in self._injury_cache:
            self._injury_cache[cache_key] = self.load_injury_status_for_date(game_date)

        return self._injury_cache.get(cache_key, {}).get(player_lookup)

    def detect_dnp_voiding(
        self,
        actual_points: int,
        minutes_played: Optional[float],
        player_lookup: str,
        game_date: date
    ) -> Dict:
        """
        Detect if a prediction should be voided due to DNP (Did Not Play).

        Like sportsbooks, we void bets when a player doesn't play.
        This prevents DNP games from counting against prediction accuracy.

        Args:
            actual_points: Points scored (0 for DNP)
            minutes_played: Minutes played (0 or None for DNP)
            player_lookup: Player identifier
            game_date: Game date for injury lookup

        Returns:
            Dict with voiding fields:
            - is_voided: True if should be excluded from accuracy metrics
            - void_reason: 'dnp_injury_confirmed', 'dnp_late_scratch', 'dnp_unknown'
            - pre_game_injury_flag: True if injury was known pre-game
            - pre_game_injury_status: The injury status if flagged
            - injury_confirmed_postgame: True if DNP matches injury report
        """
        # Default: not voided
        result = {
            'is_voided': False,
            'void_reason': None,
            'pre_game_injury_flag': False,
            'pre_game_injury_status': None,
            'injury_confirmed_postgame': False
        }

        # Check for DNP: 0 points AND (0 minutes or no minutes data)
        is_dnp = (actual_points == 0) and (minutes_played is None or minutes_played == 0)

        if not is_dnp:
            return result

        # Player DNP'd - check injury report
        injury_info = self.get_injury_status(player_lookup, game_date)

        result['is_voided'] = True

        if injury_info:
            injury_status = injury_info.get('injury_status', '').upper()
            result['pre_game_injury_status'] = injury_status

            if injury_status in ('OUT', 'DOUBTFUL'):
                # Injury was flagged pre-game
                result['void_reason'] = 'dnp_injury_confirmed'
                result['pre_game_injury_flag'] = True
                result['injury_confirmed_postgame'] = True
            elif injury_status in ('QUESTIONABLE', 'PROBABLE'):
                # Player was questionable but ended up not playing
                result['void_reason'] = 'dnp_late_scratch'
                result['pre_game_injury_flag'] = True
                result['injury_confirmed_postgame'] = True
            else:
                # Injury report exists but status was available/unknown
                result['void_reason'] = 'dnp_unknown'
                result['injury_confirmed_postgame'] = False
        else:
            # No injury report - unexpected DNP (late scratch, coach decision, etc.)
            result['void_reason'] = 'dnp_unknown'

        return result

    def get_predictions_for_date(self, game_date: date) -> List[Dict]:
        """
        Load all predictions for a specific game date.

        Returns predictions from all 5 systems:
        - moving_average_baseline_v1
        - zone_matchup_v1
        - similarity_balanced_v1
        - xgboost_v1
        - ensemble_v1
        """
        query = f"""
        SELECT
            player_lookup,
            game_id,
            game_date,
            system_id,
            predicted_points,
            confidence_score,
            recommendation,
            current_points_line as line_value,
            pace_adjustment,
            similar_games_count as similarity_sample_size,
            model_version,
            -- Line source tracking (for no-line player analysis)
            COALESCE(has_prop_line, TRUE) as has_prop_line,
            COALESCE(line_source, 'ACTUAL_PROP') as line_source,
            estimated_line_value,
            -- Confidence tier filtering (v3.4 - shadow tracking)
            COALESCE(is_actionable, TRUE) as is_actionable,
            filter_reason
        FROM `{self.predictions_table}`
        WHERE game_date = '{game_date}'
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            return result.to_dict('records')
        except Exception as e:
            logger.error(f"Error loading predictions for {game_date}: {e}")
            return []

    def get_actuals_for_date(self, game_date: date) -> Dict[str, Dict]:
        """
        Load actual game data for all players on a game date.

        Returns dict mapping player_lookup -> {actual_points, team_abbr, opponent_team_abbr, minutes_played}
        """
        query = f"""
        SELECT
            player_lookup,
            points as actual_points,
            team_abbr,
            opponent_team_abbr,
            minutes_played
        FROM `{self.actuals_table}`
        WHERE game_date = '{game_date}'
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            # Return dict of dicts with all player context
            return {
                row['player_lookup']: {
                    'actual_points': int(row['actual_points']) if row['actual_points'] is not None else None,
                    'team_abbr': row['team_abbr'],
                    'opponent_team_abbr': row['opponent_team_abbr'],
                    'minutes_played': self._safe_float(row['minutes_played'])
                }
                for _, row in result.iterrows()
            }
        except Exception as e:
            logger.error(f"Error loading actuals for {game_date}: {e}")
            return {}

    def compute_prediction_correct(
        self,
        recommendation: str,
        line_value: Optional[float],
        actual_points: int
    ) -> Optional[bool]:
        """
        Determine if OVER/UNDER recommendation was correct.

        Args:
            recommendation: 'OVER', 'UNDER', 'PASS', 'HOLD', or 'NO_LINE'
            line_value: The betting line
            actual_points: Actual points scored

        Returns:
            True if correct, False if wrong, None if can't be evaluated
            (PASS/HOLD/NO_LINE recommendations or missing line)
        """
        # Can't evaluate PASS, HOLD, or NO_LINE recommendations
        # NO_LINE means there was no real prop line - can't evaluate betting performance
        if recommendation in ('PASS', 'HOLD', 'NO_LINE', None):
            return None

        # Need a line to evaluate against
        if line_value is None:
            return None

        # Exactly hitting the line is a push (neither correct nor incorrect)
        if actual_points == line_value:
            return None

        went_over = actual_points > line_value
        recommended_over = recommendation == 'OVER'

        return bool(went_over == recommended_over)  # Ensure Python bool

    def compute_confidence_decile(self, confidence_score: Optional[float]) -> Optional[int]:
        """
        Compute confidence decile (1-10) for calibration curves.

        Args:
            confidence_score: 0.0-1.0 confidence value

        Returns:
            Integer 1-10 representing the decile bucket, or None if no score
        """
        if confidence_score is None:
            return None
        # Bucket: 0.00-0.09 → 1, 0.10-0.19 → 2, ..., 0.90-1.00 → 10
        return min(10, int(float(confidence_score) * 10) + 1)

    def grade_prediction(
        self,
        prediction: Dict,
        actual_data: Dict,
        game_date: date
    ) -> Dict:
        """
        Grade a single prediction against actual results.

        Args:
            prediction: Dict with predicted_points, confidence_score, etc.
            actual_data: Dict with actual_points, team_abbr, opponent_team_abbr, minutes_played
            game_date: Game date for injury lookup

        Returns:
            Dict ready for insertion into prediction_accuracy table
        """
        actual_points = actual_data['actual_points']
        predicted_points = prediction.get('predicted_points')
        line_value = prediction.get('line_value')
        recommendation = prediction.get('recommendation')
        confidence_score = prediction.get('confidence_score')
        minutes_played = actual_data.get('minutes_played')
        player_lookup = prediction['player_lookup']

        # Detect DNP voiding (v4)
        voiding_info = self.detect_dnp_voiding(
            actual_points=actual_points,
            minutes_played=minutes_played,
            player_lookup=player_lookup,
            game_date=game_date
        )

        # Compute errors
        if predicted_points is not None:
            absolute_error = abs(float(predicted_points) - int(actual_points))
            signed_error = float(predicted_points) - int(actual_points)  # positive = over-predicted
            within_3 = bool(absolute_error <= 3.0)  # Ensure Python bool, not numpy bool
            within_5 = bool(absolute_error <= 5.0)
        else:
            absolute_error = None
            signed_error = None
            within_3 = None
            within_5 = None

        # Compute margins
        if predicted_points is not None and line_value is not None:
            predicted_margin = predicted_points - line_value
        else:
            predicted_margin = None

        if line_value is not None:
            actual_margin = actual_points - line_value
        else:
            actual_margin = None

        # Evaluate recommendation correctness
        prediction_correct = self.compute_prediction_correct(
            recommendation, line_value, actual_points
        )

        # Helper to round floats for BigQuery NUMERIC compatibility
        def round_numeric(val, decimals=4):
            if val is None:
                return None
            return round(float(val), decimals)

        # Normalize confidence_score to 0-1 range
        # CatBoost V8 uses 0-100 percentage format, other systems use 0-1
        normalized_confidence = confidence_score
        if confidence_score is not None and confidence_score > 1:
            normalized_confidence = confidence_score / 100.0

        return {
            'player_lookup': self._safe_string(prediction['player_lookup']),
            'game_id': self._safe_string(prediction['game_id']),
            'game_date': prediction['game_date'].isoformat() if hasattr(prediction['game_date'], 'isoformat') else str(prediction['game_date']),
            'system_id': self._safe_string(prediction['system_id']),

            # Team context (new in v3)
            'team_abbr': self._safe_string(actual_data.get('team_abbr')),
            'opponent_team_abbr': self._safe_string(actual_data.get('opponent_team_abbr')),

            # Prediction snapshot - round for NUMERIC compatibility
            'predicted_points': round_numeric(predicted_points, 2),
            'confidence_score': round_numeric(normalized_confidence, 4),  # Normalized to 0-1 range
            'confidence_decile': self.compute_confidence_decile(normalized_confidence),  # new in v3
            'recommendation': self._safe_string(recommendation),
            'line_value': round_numeric(line_value, 2),

            # Feature inputs (for ML analysis)
            'referee_adjustment': None,  # Not stored in predictions table
            'pace_adjustment': round_numeric(self._safe_float(prediction.get('pace_adjustment')), 4),
            'similarity_sample_size': int(prediction.get('similarity_sample_size')) if prediction.get('similarity_sample_size') is not None and not self._is_nan(prediction.get('similarity_sample_size')) else None,

            # Actual result
            'actual_points': int(actual_points),
            'minutes_played': self._safe_float(actual_data.get('minutes_played')),  # new in v3

            # Core accuracy metrics - round for NUMERIC compatibility
            'absolute_error': round_numeric(absolute_error, 2),
            'signed_error': round_numeric(signed_error, 2),
            'prediction_correct': prediction_correct,

            # Margin analysis - round for NUMERIC compatibility
            'predicted_margin': round_numeric(predicted_margin, 2),
            'actual_margin': round_numeric(actual_margin, 2),

            # Threshold accuracy
            'within_3_points': within_3,
            'within_5_points': within_5,

            # Line source tracking (for no-line player analysis)
            # Enables segmented accuracy analysis by whether player had real betting line
            'has_prop_line': bool(prediction.get('has_prop_line', True)),
            'line_source': self._safe_string(prediction.get('line_source', 'ACTUAL_PROP')),
            'estimated_line_value': round_numeric(self._safe_float(prediction.get('estimated_line_value')), 1),

            # Confidence tier filtering (v3.4 - shadow tracking)
            # Enables tracking of filtered picks' actual performance
            'is_actionable': bool(prediction.get('is_actionable', True)),
            'filter_reason': self._safe_string(prediction.get('filter_reason')),

            # DNP/Injury Voiding (v4) - Treat DNP like sportsbook voided bets
            'is_voided': voiding_info['is_voided'],
            'void_reason': voiding_info['void_reason'],
            'pre_game_injury_flag': voiding_info['pre_game_injury_flag'],
            'pre_game_injury_status': voiding_info['pre_game_injury_status'],
            'injury_confirmed_postgame': voiding_info['injury_confirmed_postgame'],

            # Metadata
            'model_version': self._safe_string(prediction.get('model_version')),
            'graded_at': datetime.now(timezone.utc).isoformat()
        }

    def _sanitize_record(self, record: Dict) -> Dict:
        """Sanitize a single record for JSON compatibility.

        Handles NaN, Inf, and other non-JSON-serializable values.
        """
        import json
        sanitized = {}
        for key, value in record.items():
            if value is None:
                sanitized[key] = None
            elif isinstance(value, float):
                if self._math.isnan(value) or self._math.isinf(value):
                    sanitized[key] = None
                else:
                    sanitized[key] = value
            elif isinstance(value, bool):
                sanitized[key] = value  # Keep as bool, not int
            elif isinstance(value, (int, str)):
                sanitized[key] = value
            else:
                # Try to convert to string for safety
                try:
                    sanitized[key] = str(value)
                except Exception as e:
                    logger.debug(f"Failed to convert {key}={value} to string: {e}")
                    sanitized[key] = None
        return sanitized

    def write_graded_results(
        self,
        graded_results: List[Dict],
        game_date: date
    ) -> int:
        """
        Write graded results to BigQuery with idempotency.

        Deletes existing records for the date before inserting,
        allowing safe re-runs without duplicates.
        """
        if not graded_results:
            return 0

        # Sanitize all records to ensure JSON compatibility
        import json
        sanitized_results = []
        for i, record in enumerate(graded_results):
            try:
                sanitized = self._sanitize_record(record)
                # Validate JSON serialization
                json.dumps(sanitized)
                sanitized_results.append(sanitized)
            except (TypeError, ValueError) as e:
                logger.warning(f"Skipping record {i} due to JSON error: {e}, player={record.get('player_lookup')}")
                continue

        if not sanitized_results:
            logger.error("No valid records after sanitization")
            return 0

        graded_results = sanitized_results

        try:
            # IDEMPOTENCY: Delete existing records for this date first
            delete_query = f"""
            DELETE FROM `{self.accuracy_table}`
            WHERE game_date = '{game_date}'
            """
            delete_job = self.bq_client.query(delete_query)
            delete_job.result(timeout=60)
            deleted_count = delete_job.num_dml_affected_rows or 0
            if deleted_count > 0:
                logger.info(f"  Deleted {deleted_count} existing graded records for {game_date}")

            # Insert new records using BATCH LOADING (not streaming inserts)
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See: docs/05-development/guides/bigquery-best-practices.md
            table_ref = self.bq_client.get_table(self.accuracy_table)
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(
                graded_results,
                self.accuracy_table,
                job_config=job_config
            )
            load_job.result(timeout=60)  # Wait for completion

            if load_job.errors:
                logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")
                return load_job.output_rows or 0

            return load_job.output_rows or len(graded_results)

        except Exception as e:
            logger.error(f"Error writing graded results: {e}")
            return 0

    def process_date(self, game_date: date) -> Dict:
        """
        Grade all predictions for a specific date.

        Args:
            game_date: Date to process

        Returns:
            Dict with status and statistics
        """
        logger.info(f"Grading predictions for {game_date}")

        # Load predictions
        predictions = self.get_predictions_for_date(game_date)
        if not predictions:
            return {
                'status': 'no_predictions',
                'date': game_date.isoformat(),
                'predictions_found': 0,
                'graded': 0
            }

        # Load actual results
        actuals = self.get_actuals_for_date(game_date)
        if not actuals:
            return {
                'status': 'no_actuals',
                'date': game_date.isoformat(),
                'predictions_found': len(predictions),
                'graded': 0
            }

        # Grade each prediction
        graded_results = []
        missing_actuals = 0

        for pred in predictions:
            player_lookup = pred['player_lookup']
            actual_data = actuals.get(player_lookup)

            if actual_data is None:
                missing_actuals += 1
                continue

            graded = self.grade_prediction(pred, actual_data, game_date)
            graded_results.append(graded)

        # Write to BigQuery
        written = self.write_graded_results(graded_results, game_date)

        # Compute summary statistics
        if graded_results:
            # Overall stats (including voided)
            errors = [r['absolute_error'] for r in graded_results if r['absolute_error'] is not None]
            mae = sum(errors) / len(errors) if errors else None

            signed_errors = [r['signed_error'] for r in graded_results if r['signed_error'] is not None]
            bias = sum(signed_errors) / len(signed_errors) if signed_errors else None

            correct_count = sum(1 for r in graded_results if r['prediction_correct'] is True)
            incorrect_count = sum(1 for r in graded_results if r['prediction_correct'] is False)
            accuracy = correct_count / (correct_count + incorrect_count) if (correct_count + incorrect_count) > 0 else None

            # Voiding stats (v4)
            voided_count = sum(1 for r in graded_results if r.get('is_voided', False))
            voided_injury = sum(1 for r in graded_results if r.get('void_reason') == 'dnp_injury_confirmed')
            voided_scratch = sum(1 for r in graded_results if r.get('void_reason') == 'dnp_late_scratch')
            voided_unknown = sum(1 for r in graded_results if r.get('void_reason') == 'dnp_unknown')

            # Net accuracy (excluding voided) - this is the "real" accuracy like sportsbooks
            non_voided = [r for r in graded_results if not r.get('is_voided', False)]
            net_correct = sum(1 for r in non_voided if r['prediction_correct'] is True)
            net_incorrect = sum(1 for r in non_voided if r['prediction_correct'] is False)
            net_accuracy = net_correct / (net_correct + net_incorrect) if (net_correct + net_incorrect) > 0 else None

            if voided_count > 0:
                logger.info(f"  Voided {voided_count} predictions (injury: {voided_injury}, scratch: {voided_scratch}, unknown: {voided_unknown})")
        else:
            mae = None
            bias = None
            accuracy = None
            voided_count = 0
            voided_injury = 0
            voided_scratch = 0
            voided_unknown = 0
            net_accuracy = None

        return {
            'status': 'success' if written > 0 else 'failed',
            'date': game_date.isoformat(),
            'predictions_found': len(predictions),
            'actuals_found': len(actuals),
            'missing_actuals': missing_actuals,
            'graded': written,
            'mae': round(mae, 2) if mae is not None else None,
            'bias': round(bias, 2) if bias is not None else None,
            'recommendation_accuracy': round(accuracy * 100, 1) if accuracy is not None else None,
            # Voiding stats (v4)
            'voided_count': voided_count,
            'voided_injury': voided_injury,
            'voided_scratch': voided_scratch,
            'voided_unknown': voided_unknown,
            'net_accuracy': round(net_accuracy * 100, 1) if net_accuracy is not None else None
        }

    def check_predictions_exist(self, game_date: date) -> Dict:
        """Check if predictions exist for a date."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNT(DISTINCT player_lookup) as players,
            COUNT(DISTINCT system_id) as systems
        FROM `{self.predictions_table}`
        WHERE game_date = '{game_date}'
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            row = result.iloc[0]
            return {
                'exists': int(row['total']) > 0,
                'total_predictions': int(row['total']),
                'unique_players': int(row['players']),
                'systems': int(row['systems'])
            }
        except Exception as e:
            logger.error(f"Error checking predictions: {e}")
            return {'exists': False, 'error': str(e)}

    def check_actuals_exist(self, game_date: date) -> Dict:
        """Check if actual results exist for a date."""
        query = f"""
        SELECT COUNT(*) as players
        FROM `{self.actuals_table}`
        WHERE game_date = '{game_date}'
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            count = int(result['players'].iloc[0])
            return {
                'exists': count > 0,
                'players': count
            }
        except Exception as e:
            logger.error(f"Error checking actuals: {e}")
            return {'exists': False, 'error': str(e)}
