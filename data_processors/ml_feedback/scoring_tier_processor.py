"""
Scoring Tier Adjustments Processor

Phase 5C ML Feedback: Computes bias adjustments by scoring tier to correct
systematic prediction errors.

IMPORTANT (Session 124 fix): Tier classification now uses season_avg from
ml_feature_store_v2 instead of actual_points. This ensures consistency between
how adjustments are computed (by season_avg tier) and how they are applied
(by season_avg tier). Previous approach computed by actual_points but applied
by season_avg, causing adjustments to make predictions WORSE by +0.089 MAE.

Usage:
    processor = ScoringTierProcessor()
    result = processor.process('2022-01-07')  # Compute adjustments as of this date
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Tier definitions
SCORING_TIERS = {
    'STAR_30PLUS': {'min': 30, 'max': None},
    'STARTER_20_29': {'min': 20, 'max': 30},
    'ROTATION_10_19': {'min': 10, 'max': 20},
    'BENCH_0_9': {'min': 0, 'max': 10},
}


class ScoringTierProcessor:
    """Processes prediction_accuracy data to compute scoring tier adjustments."""

    def __init__(self, lookback_days: int = 30, min_sample_size: int = 20):
        """
        Initialize the processor.

        Args:
            lookback_days: Number of days of historical data to analyze (default 30)
            min_sample_size: Minimum predictions per tier to compute adjustment (default 20)
        """
        self.client = bigquery.Client()
        self.lookback_days = lookback_days
        self.min_sample_size = min_sample_size
        self.table_id = 'nba-props-platform.nba_predictions.scoring_tier_adjustments'

    def process(self, as_of_date: str, system_id: str = 'ensemble_v1') -> dict:
        """
        Compute scoring tier adjustments as of a specific date.

        Args:
            as_of_date: Date to compute adjustments for (YYYY-MM-DD)
            system_id: Prediction system to analyze (default: ensemble_v1)

        Returns:
            dict with status and metrics
        """
        logger.info(f"Computing scoring tier adjustments for {as_of_date}")

        # Compute tier metrics from prediction_accuracy
        tier_metrics = self._compute_tier_metrics(as_of_date, system_id)

        if not tier_metrics:
            logger.warning(f"No prediction data found for {as_of_date}")
            return {'status': 'skipped', 'reason': 'no_data'}

        # Build rows to insert
        rows = []
        for tier_name, metrics in tier_metrics.items():
            tier_def = SCORING_TIERS[tier_name]

            # Compute recommended adjustment (negate the bias to correct it)
            # If bias is -12.6 (under-predict), adjustment should be +12.6
            recommended_adjustment = -metrics['avg_signed_error']

            # Confidence based on sample size and std deviation
            adjustment_confidence = self._compute_confidence(
                metrics['sample_size'],
                metrics.get('std_signed_error', 5.0)
            )

            rows.append({
                'system_id': system_id,
                'scoring_tier': tier_name,
                'as_of_date': as_of_date,
                'sample_size': metrics['sample_size'],
                'lookback_days': self.lookback_days,
                'avg_signed_error': round(metrics['avg_signed_error'], 2),
                'avg_absolute_error': round(metrics['avg_absolute_error'], 2),
                'std_signed_error': round(metrics.get('std_signed_error', 0), 2),
                'recommended_adjustment': round(recommended_adjustment, 2),
                'adjustment_confidence': round(adjustment_confidence, 3),
                'current_win_rate': round(metrics['win_rate'], 3),
                'projected_win_rate': None,  # TODO: Simulate with adjustment
                'tier_min_points': tier_def['min'],
                'tier_max_points': tier_def['max'],
                'computed_at': datetime.utcnow().isoformat(),
                'model_version': 'v1.0',
            })

        # Delete existing rows for this date/system
        self._delete_existing(as_of_date, system_id)

        # Insert new rows using BATCH LOADING (not streaming inserts)
        # This avoids the 90-minute streaming buffer that blocks DML operations
        # See: docs/05-development/guides/bigquery-best-practices.md
        table_ref = self.client.get_table(self.table_id)
        job_config = bigquery.LoadJobConfig(
            schema=table_ref.schema,
            autodetect=False,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            ignore_unknown_values=True
        )

        load_job = self.client.load_table_from_json(
            rows,
            self.table_id,
            job_config=job_config
        )
        load_job.result()  # Wait for completion

        if load_job.errors:
            logger.error(f"Failed to insert rows: {load_job.errors}")
            return {'status': 'failed', 'errors': load_job.errors}

        logger.info(f"  ✓ Inserted {len(rows)} tier adjustments for {as_of_date}")

        # Log summary
        for row in rows:
            logger.info(
                f"    {row['scoring_tier']}: bias={row['avg_signed_error']:+.1f}, "
                f"adj={row['recommended_adjustment']:+.1f}, n={row['sample_size']}"
            )

        return {
            'status': 'success',
            'as_of_date': as_of_date,
            'tiers_computed': len(rows),
            'adjustments': {r['scoring_tier']: r['recommended_adjustment'] for r in rows},
        }

    def _compute_tier_metrics(self, as_of_date: str, system_id: str) -> dict:
        """
        Query prediction_accuracy to compute metrics by tier.

        IMPORTANT: Tier classification uses season_avg (from ml_feature_store_v2)
        instead of actual_points. This ensures consistency between how adjustments
        are computed and how they are applied (both use season_avg).

        Session 123 fix: Previously classified by actual_points which caused a
        mismatch - adjustments were computed for "players who scored X" but applied
        to "players who average X", making predictions worse by +0.089 MAE.
        """
        query = f"""
        WITH player_season_avg AS (
          -- Get season average from ML feature store (features[2] = points_avg_season)
          SELECT
            player_lookup,
            game_date,
            features[OFFSET(2)] as season_avg
          FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
          WHERE game_date > DATE_SUB('{as_of_date}', INTERVAL {self.lookback_days} DAY)
            AND game_date <= '{as_of_date}'
        )
        SELECT
          -- Classify by season_avg to match how adjustments are applied
          CASE
            WHEN psa.season_avg >= 30 THEN 'STAR_30PLUS'
            WHEN psa.season_avg >= 20 THEN 'STARTER_20_29'
            WHEN psa.season_avg >= 10 THEN 'ROTATION_10_19'
            ELSE 'BENCH_0_9'
          END as scoring_tier,
          COUNT(*) as sample_size,
          AVG(pa.signed_error) as avg_signed_error,
          AVG(pa.absolute_error) as avg_absolute_error,
          STDDEV(pa.signed_error) as std_signed_error,
          AVG(CASE WHEN pa.prediction_correct THEN 1 ELSE 0 END) as win_rate
        FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
        JOIN player_season_avg psa
          ON pa.player_lookup = psa.player_lookup
          AND pa.game_date = psa.game_date
        WHERE pa.system_id = '{system_id}'
          AND pa.game_date > DATE_SUB('{as_of_date}', INTERVAL {self.lookback_days} DAY)
          AND pa.game_date <= '{as_of_date}'
        GROUP BY 1
        HAVING COUNT(*) >= {self.min_sample_size}
        ORDER BY 1
        """

        results = {}
        for row in self.client.query(query).result():
            results[row.scoring_tier] = {
                'sample_size': row.sample_size,
                'avg_signed_error': float(row.avg_signed_error or 0),
                'avg_absolute_error': float(row.avg_absolute_error or 0),
                'std_signed_error': float(row.std_signed_error or 0),
                'win_rate': float(row.win_rate or 0),
            }

        return results

    def _compute_confidence(self, sample_size: int, std_error: float) -> float:
        """
        Compute confidence in the adjustment based on sample size and variability.

        Higher sample size and lower std deviation = higher confidence.
        """
        # Sample size factor: 0.5 at min_sample_size, approaches 1.0 asymptotically
        sample_factor = min(1.0, sample_size / (self.min_sample_size * 5))

        # Std factor: 1.0 for low std, decreases for high std
        std_factor = max(0.3, 1.0 - (std_error / 20.0))

        return sample_factor * std_factor

    def _delete_existing(self, as_of_date: str, system_id: str):
        """Delete existing rows for this date/system."""
        query = f"""
        DELETE FROM `{self.table_id}`
        WHERE as_of_date = '{as_of_date}' AND system_id = '{system_id}'
        """
        try:
            self.client.query(query).result()
        except Exception as e:
            # Table might not exist yet
            logger.debug(f"Delete failed (table may not exist): {e}")

    def validate_adjustments_improve_mae(
        self,
        start_date: str,
        end_date: str,
        system_id: str = 'ensemble_v1'
    ) -> dict:
        """
        Validate that tier adjustments are actually improving MAE.

        This is a safeguard added in Session 124 after discovering that
        adjustments were making predictions WORSE due to a computation bug.

        Args:
            start_date: Start of date range to validate
            end_date: End of date range to validate
            system_id: Prediction system to validate

        Returns:
            dict with validation results including mae_raw, mae_adjusted,
            mae_change, and is_improving flag

        Raises:
            ValueError: If adjustments are making MAE worse by > 0.1 points
        """
        query = f"""
        WITH predictions_with_actuals AS (
          SELECT
            p.predicted_points,
            p.adjusted_points,
            pa.actual_points
          FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
          JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
            ON p.player_lookup = pa.player_lookup
            AND p.game_date = pa.game_date
            AND p.system_id = pa.system_id
          WHERE p.system_id = '{system_id}'
            AND p.scoring_tier IS NOT NULL
            AND p.game_date BETWEEN '{start_date}' AND '{end_date}'
        )
        SELECT
          COUNT(*) as n,
          AVG(ABS(predicted_points - actual_points)) as mae_raw,
          AVG(ABS(adjusted_points - actual_points)) as mae_adjusted
        FROM predictions_with_actuals
        """

        result = list(self.client.query(query).result())[0]

        mae_raw = float(result.mae_raw or 0)
        mae_adjusted = float(result.mae_adjusted or 0)
        mae_change = mae_adjusted - mae_raw
        is_improving = mae_change < 0

        validation_result = {
            'n': result.n,
            'mae_raw': round(mae_raw, 4),
            'mae_adjusted': round(mae_adjusted, 4),
            'mae_change': round(mae_change, 4),
            'is_improving': is_improving,
            'date_range': f'{start_date} to {end_date}',
            'system_id': system_id,
        }

        if mae_change > 0.1:
            logger.error(
                f"VALIDATION FAILED: Tier adjustments making MAE WORSE by {mae_change:.3f} points! "
                f"Raw MAE: {mae_raw:.3f}, Adjusted MAE: {mae_adjusted:.3f}"
            )
            raise ValueError(
                f"Tier adjustments are making predictions worse (MAE +{mae_change:.3f}). "
                f"Check that adjustments are computed using the same classification basis "
                f"(season_avg) as they are applied. See Session 124 handoff for details."
            )

        if is_improving:
            logger.info(
                f"Validation PASSED: Adjustments improve MAE by {-mae_change:.3f} points "
                f"(Raw: {mae_raw:.3f} -> Adjusted: {mae_adjusted:.3f})"
            )
        else:
            logger.warning(
                f"Validation WARNING: Adjustments not improving MAE "
                f"(change: {mae_change:+.3f} points)"
            )

        return validation_result

    def get_adjustment(self, scoring_tier: str, as_of_date: str = None,
                       system_id: str = 'ensemble_v1') -> float:
        """
        Get the recommended adjustment for a scoring tier.

        Args:
            scoring_tier: One of STAR_30PLUS, STARTER_20_29, ROTATION_10_19, BENCH_0_9
            as_of_date: Date to get adjustment for (default: latest)
            system_id: Prediction system

        Returns:
            Recommended adjustment in points
        """
        # Use <= to find the most recent adjustment at or before the query date
        date_filter = f"as_of_date <= '{as_of_date}'" if as_of_date else "TRUE"

        query = f"""
        SELECT recommended_adjustment, adjustment_confidence
        FROM `{self.table_id}`
        WHERE scoring_tier = '{scoring_tier}'
          AND system_id = '{system_id}'
          AND {date_filter}
        ORDER BY as_of_date DESC
        LIMIT 1
        """

        result = list(self.client.query(query).result())
        if result:
            return float(result[0].recommended_adjustment)
        return 0.0

    def classify_tier(self, predicted_points: float) -> str:
        """
        Classify a predicted points value into a scoring tier.

        Note: Uses predicted points (not actual) since we don't know actuals
        at prediction time. A player predicted at 28 points is treated as
        STARTER_20_29, even though they might actually score 32.
        """
        if predicted_points >= 25:  # Lower threshold since we under-predict stars
            return 'STAR_30PLUS'
        elif predicted_points >= 18:
            return 'STARTER_20_29'
        elif predicted_points >= 8:
            return 'ROTATION_10_19'
        else:
            return 'BENCH_0_9'


class ScoringTierAdjuster:
    """
    Applies scoring tier adjustments to predictions.

    This class wraps the ScoringTierProcessor and provides a simple interface
    for adjusting predictions based on historical bias patterns.

    Key Finding from Session 117:
    - STAR players (30+ points) are under-predicted by ~12-13 points
    - Applying 50% adjustment reduces MAE by up to 47% for stars

    Recommended adjustment factors (validated in Session 117):
    - BENCH_0_9: 50% (bias is small, 50% works well)
    - ROTATION_10_19: 50% (moderate bias, 50% works well)
    - STARTER_20_29: 75% (significant bias, needs stronger correction)
    - STAR_30PLUS: 100% (extreme bias, full correction needed)

    Usage:
        adjuster = ScoringTierAdjuster()
        adjusted_pts = adjuster.apply_adjustment(predicted_pts=22.5, as_of_date='2022-01-07')
    """

    # Tier-specific adjustment factors (validated in Session 117)
    DEFAULT_ADJUSTMENT_FACTORS = {
        'BENCH_0_9': 0.5,
        'ROTATION_10_19': 0.5,
        'STARTER_20_29': 0.75,
        'STAR_30PLUS': 1.0,  # Full adjustment for stars
    }

    def __init__(
        self,
        adjustment_factors: dict = None,
        processor: ScoringTierProcessor = None,
        cache_adjustments: bool = True
    ):
        """
        Initialize the adjuster.

        Args:
            adjustment_factors: Custom tier-specific factors (0.0 to 1.0)
            processor: Existing ScoringTierProcessor instance (creates new if None)
            cache_adjustments: Whether to cache adjustment lookups
        """
        self.adjustment_factors = adjustment_factors or self.DEFAULT_ADJUSTMENT_FACTORS.copy()
        self._processor = processor
        self._cache_adjustments = cache_adjustments
        self._adjustment_cache = {}  # (tier, as_of_date, system_id) -> adjustment

    @property
    def processor(self) -> ScoringTierProcessor:
        """Lazy-load processor."""
        if self._processor is None:
            self._processor = ScoringTierProcessor()
        return self._processor

    def classify_tier(self, predicted_points: float) -> str:
        """
        Classify predicted points into a scoring tier.

        Args:
            predicted_points: Raw predicted points value

        Returns:
            Tier name (STAR_30PLUS, STARTER_20_29, ROTATION_10_19, BENCH_0_9)
        """
        return self.processor.classify_tier(predicted_points)

    def classify_tier_by_season_avg(self, season_avg: float) -> str:
        """
        Classify tier based on player's historical season average.

        This is the CORRECT method to use for tier-based adjustments.
        Using season average (historical scoring pattern) instead of
        predicted points ensures adjustments are applied to the correct tier.

        Bug fixed in Session 121: Previously used predicted_points which caused
        adjustments to make predictions WORSE because a 5-point prediction for
        a star player would get BENCH adjustments instead of STAR adjustments.

        Args:
            season_avg: Player's points_avg_season from ML feature store

        Returns:
            Tier name based on historical scoring level
        """
        if season_avg is None or season_avg <= 0:
            return 'BENCH_0_9'  # Default for missing data

        # Tier boundaries MUST match tier names exactly!
        # Session 121 bug: Using >=25 for STAR_30PLUS caused 25-29 ppg players
        # to get massive adjustments meant for 30+ scorers, hurting MAE by +5.77
        if season_avg >= 30:
            return 'STAR_30PLUS'
        elif season_avg >= 20:
            return 'STARTER_20_29'
        elif season_avg >= 10:
            return 'ROTATION_10_19'
        else:
            return 'BENCH_0_9'

    def get_adjustment_for_tier(
        self,
        tier: str,
        as_of_date: str = None,
        system_id: str = 'ensemble_v1'
    ) -> float:
        """
        Get scaled adjustment for a specific tier.

        Use with classify_tier_by_season_avg() for correct tier adjustments:
            tier = adjuster.classify_tier_by_season_avg(season_ppg)
            adjustment = adjuster.get_adjustment_for_tier(tier, as_of_date)

        Args:
            tier: Tier name (STAR_30PLUS, STARTER_20_29, etc.)
            as_of_date: Date for adjustment lookup
            system_id: Prediction system

        Returns:
            Scaled adjustment (raw_adjustment * tier_factor)
        """
        raw_adj = self.get_raw_adjustment(tier, as_of_date, system_id)
        factor = self.adjustment_factors.get(tier, 0.5)
        return raw_adj * factor

    def get_raw_adjustment(
        self,
        tier: str,
        as_of_date: str = None,
        system_id: str = 'ensemble_v1'
    ) -> float:
        """
        Get raw adjustment from scoring_tier_adjustments table.

        Args:
            tier: Scoring tier name
            as_of_date: Date for adjustment lookup (default: latest)
            system_id: Prediction system

        Returns:
            Raw recommended adjustment in points
        """
        cache_key = (tier, as_of_date, system_id)

        if self._cache_adjustments and cache_key in self._adjustment_cache:
            return self._adjustment_cache[cache_key]

        adjustment = self.processor.get_adjustment(tier, as_of_date, system_id)

        if self._cache_adjustments:
            self._adjustment_cache[cache_key] = adjustment

        return adjustment

    def get_scaled_adjustment(
        self,
        predicted_points: float,
        as_of_date: str = None,
        system_id: str = 'ensemble_v1'
    ) -> float:
        """
        Get tier-specific scaled adjustment for a prediction.

        Args:
            predicted_points: Raw predicted points value
            as_of_date: Date for adjustment lookup
            system_id: Prediction system

        Returns:
            Scaled adjustment (raw_adjustment * tier_factor)
        """
        tier = self.classify_tier(predicted_points)
        raw_adj = self.get_raw_adjustment(tier, as_of_date, system_id)
        factor = self.adjustment_factors.get(tier, 0.5)
        return raw_adj * factor

    def apply_adjustment(
        self,
        predicted_points: float,
        as_of_date: str = None,
        system_id: str = 'ensemble_v1'
    ) -> float:
        """
        Apply scoring tier adjustment to a prediction.

        Args:
            predicted_points: Raw predicted points value
            as_of_date: Date for adjustment lookup
            system_id: Prediction system

        Returns:
            Adjusted prediction
        """
        scaled_adj = self.get_scaled_adjustment(predicted_points, as_of_date, system_id)
        return predicted_points + scaled_adj

    def apply_adjustment_with_details(
        self,
        predicted_points: float,
        as_of_date: str = None,
        system_id: str = 'ensemble_v1'
    ) -> dict:
        """
        Apply adjustment and return details for transparency.

        Args:
            predicted_points: Raw predicted points value
            as_of_date: Date for adjustment lookup
            system_id: Prediction system

        Returns:
            Dict with raw_prediction, adjusted_prediction, tier, raw_adjustment,
            adjustment_factor, and scaled_adjustment
        """
        tier = self.classify_tier(predicted_points)
        raw_adj = self.get_raw_adjustment(tier, as_of_date, system_id)
        factor = self.adjustment_factors.get(tier, 0.5)
        scaled_adj = raw_adj * factor
        adjusted_pts = predicted_points + scaled_adj

        return {
            'raw_prediction': predicted_points,
            'adjusted_prediction': adjusted_pts,
            'tier': tier,
            'raw_adjustment': raw_adj,
            'adjustment_factor': factor,
            'scaled_adjustment': scaled_adj,
        }

    def clear_cache(self):
        """Clear the adjustment cache."""
        self._adjustment_cache = {}
