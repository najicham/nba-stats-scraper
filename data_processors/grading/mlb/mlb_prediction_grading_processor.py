"""
MLB Prediction Grading Processor

Grades MLB pitcher strikeout predictions against actual game results.
Writes graded records to mlb_predictions.prediction_accuracy and updates
the source prediction table.

Void Logic:
- Rain-shortened: pitcher IP < 4.0 (sportsbooks void props)
- Postponed: game_status indicates postponement
- Suspended: game suspended before completion

Innings Pitched Conversion:
- MLB uses string notation: "6.1" = 6 1/3 IP, "6.2" = 6 2/3 IP
- Must convert before float comparison

Target Tables:
- mlb_predictions.prediction_accuracy (INSERT graded records)
- mlb_predictions.pitcher_strikeouts (UPDATE is_correct, actual_strikeouts)
"""

import logging
from datetime import date, datetime, timezone
from typing import Dict, List, Any, Optional
from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client

logger = logging.getLogger(__name__)

# Game statuses that indicate incomplete games
POSTPONED_STATUSES = frozenset(['Postponed', 'Cancelled', 'postponed', 'cancelled'])
SUSPENDED_STATUSES = frozenset(['Suspended', 'suspended'])

# Minimum innings pitched for a valid prop (sportsbooks void if pitcher
# doesn't complete enough innings — typically ~4 IP for K props)
MIN_IP_FOR_VALID_PROP = 4.0


def parse_mlb_innings_pitched(ip_str) -> Optional[float]:
    """Convert MLB innings pitched notation to decimal.

    MLB notation: "6.1" = 6 and 1/3 IP, "6.2" = 6 and 2/3 IP
    NOT standard decimal — the fractional part represents thirds.

    Args:
        ip_str: Innings pitched as string, float, or int

    Returns:
        float: Decimal innings pitched, or None if invalid
    """
    if ip_str is None:
        return None
    try:
        ip_str = str(ip_str)
        if '.' in ip_str:
            whole, frac = ip_str.split('.', 1)
            whole = int(whole)
            frac = int(frac[0]) if frac else 0
            # In MLB notation, .1 = 1/3, .2 = 2/3
            return whole + (frac / 3.0)
        return float(ip_str)
    except (ValueError, TypeError):
        return None


class MlbPredictionGradingProcessor:
    """Grade MLB pitcher strikeout predictions with void logic."""

    def __init__(self):
        self.project_id = "nba-props-platform"
        self.bq_client = get_bigquery_client(project_id=self.project_id)
        self.stats = {
            "predictions_graded": 0,
            "correct": 0,
            "incorrect": 0,
            "push": 0,
            "voided": 0,
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
            elif isinstance(game_date, str):
                if game_date.upper() == 'TODAY':
                    game_date = date.today().isoformat()
                elif game_date.upper() == 'YESTERDAY':
                    from datetime import timedelta
                    game_date = (date.today() - timedelta(days=1)).isoformat()

            logger.info(f"Grading MLB predictions for {game_date}")

            # 1. Get predictions for this date
            predictions = self._get_predictions(game_date)
            if not predictions:
                logger.info(f"No predictions found for {game_date}")
                return True

            # 2. Get actual results (includes game status for void detection)
            actuals = self._get_actuals(game_date)

            # 3. Get game statuses for void detection
            game_statuses = self._get_game_statuses(game_date)

            # 4. Grade each prediction
            graded_records = []
            source_updates = []

            for pred in predictions:
                grade = self._grade_prediction(pred, actuals, game_statuses)
                if grade is None:
                    continue

                graded_records.append(grade)
                source_updates.append({
                    "prediction_id": pred.get('prediction_id'),
                    "actual_strikeouts": grade.get('actual_strikeouts'),
                    "is_correct": grade.get('prediction_correct'),
                })

            # 5. Batch write graded records to prediction_accuracy
            if graded_records:
                self._batch_insert_accuracy(graded_records, game_date)

            # 6. Batch update source prediction table
            if source_updates:
                self._batch_update_predictions(source_updates, game_date)

            # 7. Propagate actuals to signal_best_bets_picks (skipped until now —
            # columns existed but were never populated, forcing every consumer to
            # JOIN with prediction_accuracy). No-op when no best bets exist.
            if graded_records:
                self._batch_update_best_bets(graded_records, game_date)

            logger.info(f"Grading complete for {game_date}: {self.stats}")
            return True

        except Exception as e:
            logger.error(f"Error grading predictions: {e}", exc_info=True)
            return False

    def _grade_prediction(
        self,
        pred: Dict,
        actuals: Dict[str, Dict],
        game_statuses: Dict[str, str],
    ) -> Optional[Dict]:
        """Grade a single prediction with void logic."""
        pitcher_lookup = pred.get('pitcher_lookup')
        predicted_k = pred.get('predicted_strikeouts')
        line = pred.get('strikeouts_line')
        recommendation = pred.get('recommendation')
        game_pk = pred.get('game_pk')

        # Skip non-actionable predictions
        if recommendation not in ('OVER', 'UNDER'):
            self.stats["no_result"] += 1
            return None

        # Check for postponed/suspended game
        game_status = game_statuses.get(game_pk, '')
        if game_status in POSTPONED_STATUSES:
            self.stats["voided"] += 1
            return self._build_voided_record(pred, 'postponed')
        if game_status in SUSPENDED_STATUSES:
            self.stats["voided"] += 1
            return self._build_voided_record(pred, 'suspended')

        # Look up actual result — exact match first, then fuzzy fallback
        # Fuzzy fallback handles "j_t_ginn" (box scores API with periods) vs
        # "jt_ginn" (schedule API without periods). Strip underscores for comparison.
        actual = actuals.get(pitcher_lookup)
        if actual is None and pitcher_lookup:
            stripped = pitcher_lookup.replace('_', '')
            actual = next(
                (v for k, v in actuals.items() if k.replace('_', '') == stripped),
                None,
            )
            if actual is not None:
                logger.debug(
                    f"Fuzzy match: {pitcher_lookup!r} matched via stripped lookup"
                )
        if actual is None:
            self.stats["no_result"] += 1
            return None

        actual_k = actual.get('strikeouts', 0)
        ip_raw = actual.get('innings_pitched')
        ip_decimal = parse_mlb_innings_pitched(ip_raw)

        # Void check: pitcher didn't pitch enough innings
        # (rain-shortened, early pull, injury exit)
        if ip_decimal is not None and ip_decimal < MIN_IP_FOR_VALID_PROP:
            self.stats["voided"] += 1
            void_reason = 'short_start'
            if ip_decimal == 0:
                void_reason = 'scratched'
            return self._build_graded_record(
                pred, actual_k, ip_decimal,
                is_voided=True, void_reason=void_reason,
            )

        # Grade the prediction
        prediction_correct = None
        if recommendation == 'OVER':
            if actual_k > line:
                prediction_correct = True
                self.stats["correct"] += 1
            elif actual_k < line:
                prediction_correct = False
                self.stats["incorrect"] += 1
            else:
                self.stats["push"] += 1
        elif recommendation == 'UNDER':
            if actual_k < line:
                prediction_correct = True
                self.stats["correct"] += 1
            elif actual_k > line:
                prediction_correct = False
                self.stats["incorrect"] += 1
            else:
                self.stats["push"] += 1

        self.stats["predictions_graded"] += 1

        return self._build_graded_record(
            pred, actual_k, ip_decimal,
            prediction_correct=prediction_correct,
        )

    def _build_graded_record(
        self,
        pred: Dict,
        actual_k: int,
        ip_decimal: Optional[float],
        prediction_correct: Optional[bool] = None,
        is_voided: bool = False,
        void_reason: Optional[str] = None,
    ) -> Dict:
        """Build a graded record for prediction_accuracy table."""
        predicted_k = pred.get('predicted_strikeouts')
        line = pred.get('strikeouts_line')

        absolute_error = abs(predicted_k - actual_k) if predicted_k is not None else None
        signed_error = (predicted_k - actual_k) if predicted_k is not None else None
        edge = (predicted_k - line) if (predicted_k is not None and line is not None) else None

        return {
            "pitcher_lookup": pred.get('pitcher_lookup'),
            "game_pk": pred.get('game_pk'),
            "game_date": pred.get('game_date'),
            "system_id": pred.get('system_id', 'unknown'),
            "team_abbr": pred.get('team_abbr'),
            "opponent_team_abbr": pred.get('opponent_team_abbr'),
            "predicted_strikeouts": predicted_k,
            "confidence_score": pred.get('confidence'),
            "recommendation": pred.get('recommendation'),
            "line_value": line,
            "edge": round(edge, 1) if edge is not None else None,
            "actual_strikeouts": actual_k,
            "innings_pitched": round(ip_decimal, 1) if ip_decimal is not None else None,
            "absolute_error": round(absolute_error, 1) if absolute_error is not None else None,
            "signed_error": round(signed_error, 1) if signed_error is not None else None,
            "prediction_correct": prediction_correct,
            "predicted_margin": round(predicted_k - line, 1) if (predicted_k and line) else None,
            "actual_margin": round(actual_k - line, 1) if line else None,
            "within_1_strikeout": absolute_error is not None and absolute_error <= 1,
            "within_2_strikeouts": absolute_error is not None and absolute_error <= 2,
            "has_prop_line": line is not None,
            "is_voided": is_voided,
            "void_reason": void_reason,
            "feature_quality_score": pred.get('feature_coverage_pct'),
            "model_version": pred.get('model_version'),
            "graded_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_voided_record(self, pred: Dict, void_reason: str) -> Dict:
        """Build a voided record (no actual data)."""
        return self._build_graded_record(
            pred, actual_k=0, ip_decimal=None,
            is_voided=True, void_reason=void_reason,
        )

    def _get_predictions(self, game_date: str) -> List[Dict]:
        """Get predictions for a game date."""
        query = f"""
        SELECT
            prediction_id,
            pitcher_lookup,
            game_id AS game_pk,
            predicted_strikeouts,
            strikeouts_line,
            recommendation,
            system_id,
            confidence,
            team_abbr,
            opponent_team_abbr,
            model_version,
            feature_coverage_pct
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date = '{game_date}'
        """
        try:
            rows = [dict(row) for row in self.bq_client.query(query).result()]
            # Add game_date to each row for downstream use
            for row in rows:
                row['game_date'] = game_date
            return rows
        except Exception as e:
            logger.error(f"Error getting predictions: {e}")
            return []

    def _get_actuals(self, game_date: str) -> Dict[str, Dict]:
        """Get actual pitcher strikeouts for a game date.

        Tries mlbapi_pitcher_stats first (new source), falls back to
        mlb_pitcher_stats (legacy BDL).
        """
        # Try new MLBAPI source first
        for table in ['mlbapi_pitcher_stats', 'mlb_pitcher_stats']:
            query = f"""
            SELECT
                player_lookup,
                strikeouts,
                innings_pitched,
                game_pk
            FROM `{self.project_id}.mlb_raw.{table}`
            WHERE game_date = '{game_date}'
              AND is_starter = TRUE
            """
            try:
                results = {}
                for row in self.bq_client.query(query).result():
                    results[row.player_lookup] = {
                        "strikeouts": row.strikeouts,
                        "innings_pitched": row.innings_pitched,
                        "game_pk": getattr(row, 'game_pk', None),
                    }
                if results:
                    logger.info(f"Got {len(results)} actuals from {table}")
                    return results
            except Exception as e:
                logger.debug(f"Table {table} not available: {e}")
                continue
        return {}

    def _get_game_statuses(self, game_date: str) -> Dict[str, str]:
        """Get game statuses for void detection (postponed/suspended).

        Returns dict keyed by game_pk as STRING to match pitcher_strikeouts.game_id
        (which is CAST(game_pk AS STRING) from pitcher_game_summary).
        """
        query = f"""
        SELECT CAST(game_pk AS STRING) AS game_pk, status_detailed AS game_status
        FROM `{self.project_id}.mlb_raw.mlb_schedule`
        WHERE game_date = '{game_date}'
        """
        try:
            return {
                row.game_pk: row.game_status
                for row in self.bq_client.query(query).result()
            }
        except Exception as e:
            logger.debug(f"Could not get game statuses: {e}")
            return {}

    def _batch_insert_accuracy(self, records: List[Dict], game_date: str):
        """Batch insert graded records to prediction_accuracy table.

        Uses DELETE + INSERT pattern (same as NBA) to avoid DML locks.
        """
        table_id = f"{self.project_id}.mlb_predictions.prediction_accuracy"

        # Delete existing records for this date first (idempotent re-grading)
        delete_query = f"""
        DELETE FROM `{table_id}`
        WHERE game_date = '{game_date}'
        """
        try:
            self.bq_client.query(delete_query).result()
        except Exception as e:
            logger.warning(f"Delete before insert failed (table may not exist yet): {e}")

        # Build rows for insertion
        rows = []
        for r in records:
            rows.append({
                "pitcher_lookup": r["pitcher_lookup"],
                "game_pk": r.get("game_pk"),
                "game_date": game_date,
                "system_id": r.get("system_id", "unknown"),
                "team_abbr": r.get("team_abbr"),
                "opponent_team_abbr": r.get("opponent_team_abbr"),
                "predicted_strikeouts": r.get("predicted_strikeouts"),
                "confidence_score": r.get("confidence_score"),
                "recommendation": r.get("recommendation"),
                "line_value": r.get("line_value"),
                "edge": r.get("edge"),
                "actual_strikeouts": r.get("actual_strikeouts"),
                "innings_pitched": r.get("innings_pitched"),
                "absolute_error": r.get("absolute_error"),
                "signed_error": r.get("signed_error"),
                "prediction_correct": r.get("prediction_correct"),
                "predicted_margin": r.get("predicted_margin"),
                "actual_margin": r.get("actual_margin"),
                "within_1_strikeout": r.get("within_1_strikeout"),
                "within_2_strikeouts": r.get("within_2_strikeouts"),
                "has_prop_line": r.get("has_prop_line"),
                "is_voided": r.get("is_voided", False),
                "void_reason": r.get("void_reason"),
                "feature_quality_score": r.get("feature_quality_score"),
                "model_version": r.get("model_version"),
                "graded_at": r.get("graded_at"),
            })

        if not rows:
            return

        # Strip None values — BQ load_table_from_json treats missing keys as NULL
        # but explicit None on integer fields causes schema errors.
        rows = [{k: v for k, v in row.items() if v is not None} for row in rows]

        try:
            # Use batch load (not streaming insert) so rows are immediately visible
            # to the preceding DELETE statement. Streaming inserts go to a buffer
            # that is invisible to DML for up to 90 minutes, causing duplicates on
            # re-grading runs.
            table = self.bq_client.get_table(table_id)
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                schema=table.schema,
            )
            load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result()
            logger.info(f"Inserted {len(rows)} graded records to prediction_accuracy")
        except Exception as e:
            logger.error(f"Batch insert to prediction_accuracy failed: {e}")

    def _batch_update_predictions(self, updates: List[Dict], game_date: str):
        """Batch update source predictions table using a single MERGE statement.

        Avoids row-by-row UPDATEs that cause DML locks during catch-up.
        """
        if not updates:
            return

        # Build a MERGE using an UNNEST of struct array
        struct_rows = []
        for u in updates:
            is_correct_str = 'NULL'
            if u['is_correct'] is True:
                is_correct_str = 'TRUE'
            elif u['is_correct'] is False:
                is_correct_str = 'FALSE'

            actual_k = u.get('actual_strikeouts', 0) or 0

            struct_rows.append(
                f"STRUCT('{u['prediction_id']}' AS prediction_id, "
                f"{actual_k} AS actual_strikeouts, "
                f"{is_correct_str} AS is_correct)"
            )

        # Batch in groups of 500 to stay under query size limits
        batch_size = 500
        for i in range(0, len(struct_rows), batch_size):
            batch = struct_rows[i:i + batch_size]
            values_str = ",\n        ".join(batch)

            query = f"""
            MERGE `{self.project_id}.mlb_predictions.pitcher_strikeouts` T
            USING (
                SELECT * FROM UNNEST([
                    {values_str}
                ])
            ) S
            ON T.prediction_id = S.prediction_id
            WHEN MATCHED THEN UPDATE SET
                T.actual_strikeouts = S.actual_strikeouts,
                T.is_correct = S.is_correct,
                T.graded_at = CURRENT_TIMESTAMP()
            """
            try:
                self.bq_client.query(query).result()
                logger.info(f"Batch updated {len(batch)} predictions")
            except Exception as e:
                logger.error(f"Batch MERGE failed: {e}")

    def _batch_update_best_bets(self, graded_records: List[Dict], game_date: str):
        """Propagate grading outcomes into signal_best_bets_picks.

        Matches on (pitcher_lookup, game_date, system_id) — the natural key in
        best bets. No-op for graded predictions that weren't picked as best bets.
        Uses MERGE in batches of 500 to avoid DML locks during catch-up.
        """
        if not graded_records:
            return

        # Escape single quotes in system_ids (e.g., 'catboost_v2_...') defensively.
        struct_rows = []
        for g in graded_records:
            pitcher_lookup = g.get('pitcher_lookup', '').replace("'", "\\'")
            system_id = g.get('system_id', '').replace("'", "\\'")
            actual_k = g.get('actual_strikeouts')
            correct = g.get('prediction_correct')

            if actual_k is None:
                actual_k_str = 'NULL'
            else:
                actual_k_str = str(int(actual_k))

            if correct is True:
                correct_str = 'TRUE'
            elif correct is False:
                correct_str = 'FALSE'
            else:
                correct_str = 'NULL'

            struct_rows.append(
                f"STRUCT('{pitcher_lookup}' AS pitcher_lookup, "
                f"DATE('{game_date}') AS game_date, "
                f"'{system_id}' AS system_id, "
                f"{actual_k_str} AS actual_strikeouts, "
                f"{correct_str} AS prediction_correct)"
            )

        batch_size = 500
        for i in range(0, len(struct_rows), batch_size):
            batch = struct_rows[i:i + batch_size]
            values_str = ",\n        ".join(batch)

            query = f"""
            MERGE `{self.project_id}.mlb_predictions.signal_best_bets_picks` T
            USING (
                SELECT * FROM UNNEST([
                    {values_str}
                ])
            ) S
            ON T.pitcher_lookup = S.pitcher_lookup
               AND T.game_date = S.game_date
               AND T.system_id = S.system_id
            WHEN MATCHED THEN UPDATE SET
                T.actual_strikeouts = S.actual_strikeouts,
                T.prediction_correct = S.prediction_correct
            """
            try:
                result = self.bq_client.query(query).result()
                # Only log when there's actually something to update (most
                # graded predictions are not best bets — MERGE is cheap but
                # noisy in logs otherwise).
                logger.debug(f"MERGE into signal_best_bets_picks: batch of {len(batch)}")
            except Exception as e:
                # Non-fatal: signal_best_bets_picks grading is supplementary —
                # consumers still have prediction_accuracy as the source of truth.
                logger.warning(f"signal_best_bets_picks MERGE failed (non-fatal): {e}")

    def get_grading_stats(self) -> Dict:
        """Get grading statistics."""
        return self.stats.copy()

    def analyze_timing(self, game_date: str) -> Dict:
        """Analyze prediction accuracy by line timing buckets."""
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
        """Get timing analysis summary over multiple days."""
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
