"""
Performance Diagnostics - Unified Analysis for Model Performance Issues

Combines Vegas sharpness monitoring, model drift detection, and data quality checks
into a single diagnostic system with root cause attribution.

Key Capabilities:
1. Vegas Sharpness Analysis - Detect when Vegas lines get sharper
2. Model Drift Detection - Track rolling accuracy metrics
3. Data Quality Assessment - Shot zone completeness, feature quality
4. Root Cause Attribution - Determine why performance is degrading
5. Alert Generation - CRITICAL/WARNING/INFO based on thresholds

Root Cause Categories:
- VEGAS_SHARP: Vegas lines are unusually accurate, reducing edge opportunities
- MODEL_DRIFT: Model performance degrading independent of Vegas/data quality
- DATA_QUALITY: Missing shot zones, incomplete features affecting predictions
- NORMAL_VARIANCE: Performance within expected statistical variance

Usage:
    from shared.utils.performance_diagnostics import PerformanceDiagnostics
    from datetime import date

    # Run full analysis
    diagnostics = PerformanceDiagnostics(game_date=date.today())
    results = diagnostics.run_full_analysis()

    # Get root cause
    cause, confidence, factors = diagnostics.determine_root_cause(results)
    print(f"Root cause: {cause} (confidence: {confidence:.0%})")

    # Generate alert
    alert = diagnostics.generate_alert()
    if alert['level'] == 'CRITICAL':
        # Send urgent notification

    # Persist for tracking
    diagnostics.persist_results()

Version: 1.0
Created: 2026-01-31
Part of: Performance Monitoring System
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import BigQuery, but allow graceful fallback for testing
try:
    from google.cloud import bigquery
    HAS_BIGQUERY = True
except ImportError:
    HAS_BIGQUERY = False
    bigquery = None

# Constants
PROJECT_ID = "nba-props-platform"
SYSTEM_ID = "catboost_v8"


class RootCause(Enum):
    """Root cause categories for performance issues."""
    VEGAS_SHARP = "VEGAS_SHARP"
    MODEL_DRIFT = "MODEL_DRIFT"
    DATA_QUALITY = "DATA_QUALITY"
    NORMAL_VARIANCE = "NORMAL_VARIANCE"


class AlertLevel(Enum):
    """Alert severity levels."""
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"
    OK = "OK"


@dataclass
class DiagnosticsResult:
    """Container for full diagnostics results."""
    game_date: date
    run_timestamp: datetime
    vegas_metrics: Dict[str, Any]
    drift_metrics: Dict[str, Any]
    data_quality_metrics: Dict[str, Any]
    baselines: Dict[str, Any]
    root_cause: str
    root_cause_confidence: float
    contributing_factors: List[str]
    alert_level: str
    alert_message: str
    recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for BigQuery insert."""
        return {
            'game_date': str(self.game_date),
            'run_timestamp': self.run_timestamp.isoformat(),
            'vegas_metrics': json.dumps(self.vegas_metrics),
            'drift_metrics': json.dumps(self.drift_metrics),
            'data_quality_metrics': json.dumps(self.data_quality_metrics),
            'baselines': json.dumps(self.baselines),
            'root_cause': self.root_cause,
            'root_cause_confidence': self.root_cause_confidence,
            'contributing_factors': json.dumps(self.contributing_factors),
            'alert_level': self.alert_level,
            'alert_message': self.alert_message,
            'recommendations': json.dumps(self.recommendations),
        }


class PerformanceDiagnostics:
    """
    Unified performance diagnostics system.

    Combines multiple monitoring signals to determine root cause of
    performance issues and generate actionable alerts.
    """

    # BigQuery table for persisting results
    TABLE_ID = "nba_orchestration.performance_diagnostics"

    # Thresholds for alerts
    THRESHOLDS = {
        # Vegas sharpness
        'vegas_sharp_critical': 42.0,  # model_beats_vegas below this = sharp
        'vegas_sharp_warning': 45.0,
        'vegas_normal': 50.0,

        # Hit rate thresholds
        'hit_rate_critical': 50.0,  # Below this with sharp Vegas = CRITICAL
        'hit_rate_warning': 52.4,   # Breakeven

        # Drift score thresholds
        'drift_warning': 40.0,

        # Data quality thresholds
        'shot_zone_completeness_warning': 70.0,  # % of records with complete zones
        'shot_zone_completeness_critical': 50.0,

        # MAE thresholds
        'mae_warning': 5.5,
        'mae_critical': 6.5,
    }

    def __init__(
        self,
        game_date: Optional[date] = None,
        lookback_days: int = 30,
        project_id: str = PROJECT_ID,
        bq_client: Optional[Any] = None
    ):
        """
        Initialize performance diagnostics.

        Args:
            game_date: Date for analysis (defaults to today)
            lookback_days: Days to look back for baselines
            project_id: GCP project ID
            bq_client: Optional BigQuery client (for testing)
        """
        self.game_date = game_date or date.today()
        self.lookback_days = lookback_days
        self.project_id = project_id

        if bq_client:
            self.bq_client = bq_client
        elif HAS_BIGQUERY:
            try:
                self.bq_client = bigquery.Client(project=project_id)
            except Exception as e:
                logger.warning(f"Failed to initialize BigQuery client: {e}")
                self.bq_client = None
        else:
            self.bq_client = None

        # Cache for results
        self._cached_results: Optional[DiagnosticsResult] = None

    def calculate_vegas_sharpness(self) -> Dict[str, Any]:
        """
        Calculate Vegas line sharpness metrics.

        Returns dict with:
            - overall_model_beats_vegas: Weighted average across tiers
            - vegas_mae: Overall Vegas MAE
            - model_mae: Overall model MAE
            - by_tier: Per-tier breakdown
            - sharpness_status: VERY_SHARP, SHARP, NORMAL, or SOFT
        """
        if not self.bq_client:
            logger.warning("No BigQuery client available for Vegas sharpness")
            return self._empty_vegas_metrics()

        query = f"""
        WITH player_tiers AS (
          SELECT
            player_lookup,
            CASE
              WHEN AVG(points) >= 22 THEN 'Star'
              WHEN AVG(points) >= 14 THEN 'Starter'
              WHEN AVG(points) >= 6 THEN 'Rotation'
              ELSE 'Bench'
            END as tier
          FROM nba_analytics.player_game_summary
          WHERE game_date >= DATE_SUB('{self.game_date}', INTERVAL 90 DAY)
            AND minutes_played > 10
          GROUP BY 1
        ),
        recent_data AS (
          SELECT
            pt.tier,
            COUNT(*) as games,
            ROUND(AVG(ABS(pa.line_value - pa.actual_points)), 2) as vegas_mae,
            ROUND(AVG(pa.absolute_error), 2) as model_mae,
            ROUND(100.0 * COUNTIF(pa.absolute_error < ABS(pa.line_value - pa.actual_points)) / COUNT(*), 1) as model_beats_vegas_pct,
            ROUND(100.0 * COUNTIF(ABS(pa.line_value - pa.actual_points) <= 3) / COUNT(*), 1) as vegas_within_3pts,
            ROUND(100.0 * COUNTIF(ABS(pa.predicted_points - pa.line_value) >= 3) / COUNT(*), 1) as pct_3plus_edge
          FROM nba_predictions.prediction_accuracy pa
          LEFT JOIN player_tiers pt ON pa.player_lookup = pt.player_lookup
          WHERE pa.system_id = '{SYSTEM_ID}'
            AND pa.line_value IS NOT NULL
            AND pa.game_date >= DATE_SUB('{self.game_date}', INTERVAL 14 DAY)
            AND pa.game_date <= '{self.game_date}'
          GROUP BY 1
        )
        SELECT
          tier,
          games,
          vegas_mae,
          model_mae,
          model_beats_vegas_pct,
          vegas_within_3pts,
          pct_3plus_edge
        FROM recent_data
        ORDER BY CASE tier WHEN 'Star' THEN 1 WHEN 'Starter' THEN 2 WHEN 'Rotation' THEN 3 ELSE 4 END
        """

        try:
            results = list(self.bq_client.query(query).result())

            tier_data = {}
            total_games = 0
            weighted_model_beats = 0.0
            weighted_vegas_mae = 0.0
            weighted_model_mae = 0.0

            for row in results:
                if row.tier is None:
                    continue
                games = int(row.games)
                tier_data[row.tier] = {
                    "games": games,
                    "vegas_mae": float(row.vegas_mae),
                    "model_mae": float(row.model_mae),
                    "model_beats_vegas_pct": float(row.model_beats_vegas_pct),
                    "vegas_within_3pts": float(row.vegas_within_3pts),
                    "pct_3plus_edge": float(row.pct_3plus_edge),
                }
                total_games += games
                weighted_model_beats += float(row.model_beats_vegas_pct) * games
                weighted_vegas_mae += float(row.vegas_mae) * games
                weighted_model_mae += float(row.model_mae) * games

            if total_games == 0:
                return self._empty_vegas_metrics()

            overall_model_beats = weighted_model_beats / total_games
            overall_vegas_mae = weighted_vegas_mae / total_games
            overall_model_mae = weighted_model_mae / total_games

            # Determine sharpness status
            if overall_model_beats < self.THRESHOLDS['vegas_sharp_critical']:
                sharpness_status = "VERY_SHARP"
            elif overall_model_beats < self.THRESHOLDS['vegas_sharp_warning']:
                sharpness_status = "SHARP"
            elif overall_model_beats < 55.0:
                sharpness_status = "NORMAL"
            else:
                sharpness_status = "SOFT"

            return {
                "overall_model_beats_vegas": round(overall_model_beats, 1),
                "vegas_mae": round(overall_vegas_mae, 2),
                "model_mae": round(overall_model_mae, 2),
                "total_games": total_games,
                "by_tier": tier_data,
                "sharpness_status": sharpness_status,
            }

        except Exception as e:
            logger.error(f"Failed to calculate Vegas sharpness: {e}")
            return self._empty_vegas_metrics()

    def calculate_model_drift(self) -> Dict[str, Any]:
        """
        Calculate model drift metrics.

        Returns dict with:
            - hit_rate_7d: 7-day rolling hit rate
            - hit_rate_14d: 14-day rolling hit rate
            - hit_rate_30d: 30-day rolling hit rate
            - mae_14d: 14-day MAE
            - mean_error: Prediction bias (positive = overpredicting)
            - drift_score: Overall drift severity (0-100)
            - drift_status: LOW, MEDIUM, HIGH, CRITICAL
        """
        if not self.bq_client:
            logger.warning("No BigQuery client available for drift detection")
            return self._empty_drift_metrics()

        query = f"""
        WITH daily_stats AS (
          SELECT
            game_date,
            COUNT(*) as total_bets,
            COUNTIF(prediction_correct) as correct_bets,
            AVG(predicted_points - actual_points) as mean_error,
            AVG(ABS(predicted_points - actual_points)) as mae
          FROM nba_predictions.prediction_accuracy
          WHERE system_id = '{SYSTEM_ID}'
            AND ABS(predicted_points - line_value) >= 3
            AND game_date >= DATE_SUB('{self.game_date}', INTERVAL 30 DAY)
            AND game_date <= '{self.game_date}'
          GROUP BY game_date
        ),
        rolling_stats AS (
          SELECT
            (SELECT ROUND(100.0 * SUM(correct_bets) / NULLIF(SUM(total_bets), 0), 1)
             FROM daily_stats
             WHERE game_date >= DATE_SUB('{self.game_date}', INTERVAL 7 DAY)) as hit_rate_7d,
            (SELECT SUM(total_bets)
             FROM daily_stats
             WHERE game_date >= DATE_SUB('{self.game_date}', INTERVAL 7 DAY)) as bets_7d,

            (SELECT ROUND(100.0 * SUM(correct_bets) / NULLIF(SUM(total_bets), 0), 1)
             FROM daily_stats
             WHERE game_date >= DATE_SUB('{self.game_date}', INTERVAL 14 DAY)) as hit_rate_14d,
            (SELECT SUM(total_bets)
             FROM daily_stats
             WHERE game_date >= DATE_SUB('{self.game_date}', INTERVAL 14 DAY)) as bets_14d,

            (SELECT ROUND(100.0 * SUM(correct_bets) / NULLIF(SUM(total_bets), 0), 1)
             FROM daily_stats
             WHERE game_date >= DATE_SUB('{self.game_date}', INTERVAL 30 DAY)) as hit_rate_30d,
            (SELECT SUM(total_bets)
             FROM daily_stats
             WHERE game_date >= DATE_SUB('{self.game_date}', INTERVAL 30 DAY)) as bets_30d,

            (SELECT ROUND(AVG(mae), 2)
             FROM daily_stats
             WHERE game_date >= DATE_SUB('{self.game_date}', INTERVAL 14 DAY)) as mae_14d,

            (SELECT ROUND(AVG(mean_error), 2)
             FROM daily_stats
             WHERE game_date >= DATE_SUB('{self.game_date}', INTERVAL 14 DAY)) as mean_error_14d
        )
        SELECT * FROM rolling_stats
        """

        try:
            result = list(self.bq_client.query(query).result())[0]

            hit_rate_7d = float(result.hit_rate_7d) if result.hit_rate_7d else None
            hit_rate_14d = float(result.hit_rate_14d) if result.hit_rate_14d else None
            hit_rate_30d = float(result.hit_rate_30d) if result.hit_rate_30d else None
            mae_14d = float(result.mae_14d) if result.mae_14d else None
            mean_error = float(result.mean_error_14d) if result.mean_error_14d else 0.0

            # Calculate drift score (0-100)
            # Based on multiple signals: hit rate vs breakeven, MAE increase, bias
            drift_signals = 0
            total_signals = 0

            breakeven = self.THRESHOLDS['hit_rate_warning']

            if hit_rate_7d is not None:
                if hit_rate_7d < breakeven:
                    drift_signals += 1
                total_signals += 1

            if hit_rate_14d is not None:
                if hit_rate_14d < breakeven:
                    drift_signals += 1
                total_signals += 1

            if mae_14d is not None:
                if mae_14d > self.THRESHOLDS['mae_warning']:
                    drift_signals += 1
                total_signals += 1

            if abs(mean_error) > 1.0:
                drift_signals += 1
            total_signals += 1

            drift_score = round((drift_signals / total_signals) * 100, 1) if total_signals > 0 else 0.0

            # Determine drift status
            if drift_score >= 60:
                drift_status = "CRITICAL"
            elif drift_score >= 40:
                drift_status = "HIGH"
            elif drift_score >= 20:
                drift_status = "MEDIUM"
            else:
                drift_status = "LOW"

            return {
                "hit_rate_7d": hit_rate_7d,
                "hit_rate_14d": hit_rate_14d,
                "hit_rate_30d": hit_rate_30d,
                "bets_7d": int(result.bets_7d or 0),
                "bets_14d": int(result.bets_14d or 0),
                "bets_30d": int(result.bets_30d or 0),
                "mae_14d": mae_14d,
                "mean_error": mean_error,
                "bias_direction": "OVER" if mean_error > 0.5 else "UNDER" if mean_error < -0.5 else "NEUTRAL",
                "drift_score": drift_score,
                "drift_status": drift_status,
                "breakeven_threshold": breakeven,
            }

        except Exception as e:
            logger.error(f"Failed to calculate model drift: {e}")
            return self._empty_drift_metrics()

    def calculate_data_quality(self) -> Dict[str, Any]:
        """
        Calculate data quality metrics.

        Returns dict with:
            - shot_zone_completeness: % of records with complete shot zones
            - avg_paint_rate: Average paint attempt rate (sanity check)
            - players_with_data: Number of players with data
            - feature_quality_score: Overall feature quality (0-100)
            - quality_status: OK, WARNING, or CRITICAL
        """
        if not self.bq_client:
            logger.warning("No BigQuery client available for data quality")
            return self._empty_quality_metrics()

        query = f"""
        SELECT
          COUNT(*) as total_records,
          COUNTIF(has_complete_shot_zones = TRUE) as complete_shot_zones,
          ROUND(100.0 * COUNTIF(has_complete_shot_zones = TRUE) / NULLIF(COUNT(*), 0), 1) as pct_complete_shot_zones,
          ROUND(AVG(CASE
            WHEN has_complete_shot_zones = TRUE
            THEN SAFE_DIVIDE(paint_attempts * 100.0,
                 paint_attempts + mid_range_attempts + three_attempts_pbp)
            END), 1) as avg_paint_rate,
          ROUND(AVG(CASE
            WHEN has_complete_shot_zones = TRUE
            THEN SAFE_DIVIDE(three_attempts_pbp * 100.0,
                 paint_attempts + mid_range_attempts + three_attempts_pbp)
            END), 1) as avg_three_rate,
          COUNT(DISTINCT player_lookup) as players_with_data
        FROM nba_analytics.player_game_summary
        WHERE game_date >= DATE_SUB('{self.game_date}', INTERVAL 7 DAY)
          AND game_date <= '{self.game_date}'
          AND minutes_played > 0
        """

        try:
            result = list(self.bq_client.query(query).result())[0]

            total_records = int(result.total_records or 0)
            complete_shot_zones = int(result.complete_shot_zones or 0)
            pct_complete = float(result.pct_complete_shot_zones) if result.pct_complete_shot_zones else 0.0
            avg_paint_rate = float(result.avg_paint_rate) if result.avg_paint_rate else None
            avg_three_rate = float(result.avg_three_rate) if result.avg_three_rate else None
            players_with_data = int(result.players_with_data or 0)

            # Calculate feature quality score
            quality_signals = 0
            total_signals = 0

            # Shot zone completeness
            if pct_complete >= self.THRESHOLDS['shot_zone_completeness_warning']:
                quality_signals += 1
            total_signals += 1

            # Paint rate sanity check (expect 30-50%)
            if avg_paint_rate is not None and 25.0 <= avg_paint_rate <= 55.0:
                quality_signals += 1
            total_signals += 1

            # Three rate sanity check (expect 30-50%)
            if avg_three_rate is not None and 25.0 <= avg_three_rate <= 55.0:
                quality_signals += 1
            total_signals += 1

            feature_quality_score = round((quality_signals / total_signals) * 100, 1) if total_signals > 0 else 0.0

            # Determine quality status
            if pct_complete < self.THRESHOLDS['shot_zone_completeness_critical']:
                quality_status = "CRITICAL"
            elif pct_complete < self.THRESHOLDS['shot_zone_completeness_warning']:
                quality_status = "WARNING"
            else:
                quality_status = "OK"

            return {
                "total_records": total_records,
                "shot_zone_completeness": pct_complete,
                "avg_paint_rate": avg_paint_rate,
                "avg_three_rate": avg_three_rate,
                "players_with_data": players_with_data,
                "feature_quality_score": feature_quality_score,
                "quality_status": quality_status,
            }

        except Exception as e:
            logger.error(f"Failed to calculate data quality: {e}")
            return self._empty_quality_metrics()

    def calculate_baselines(self) -> Dict[str, Any]:
        """
        Calculate 30-day rolling baselines for comparison.

        Returns dict with:
            - baseline_model_beats_vegas: Historical average
            - baseline_hit_rate: Historical hit rate
            - baseline_mae: Historical MAE
            - baseline_shot_zone_completeness: Historical completeness
        """
        if not self.bq_client:
            logger.warning("No BigQuery client available for baselines")
            return self._empty_baselines()

        query = f"""
        WITH baseline_period AS (
          SELECT
            ROUND(100.0 * COUNTIF(absolute_error < ABS(line_value - actual_points)) /
                  NULLIF(COUNT(*), 0), 1) as model_beats_vegas,
            ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0), 1) as hit_rate,
            ROUND(AVG(absolute_error), 2) as mae
          FROM nba_predictions.prediction_accuracy
          WHERE system_id = '{SYSTEM_ID}'
            AND line_value IS NOT NULL
            AND ABS(predicted_points - line_value) >= 3
            AND game_date >= DATE_SUB('{self.game_date}', INTERVAL {self.lookback_days} DAY)
            AND game_date <= '{self.game_date}'
        ),
        quality_baseline AS (
          SELECT
            ROUND(100.0 * COUNTIF(has_complete_shot_zones = TRUE) / NULLIF(COUNT(*), 0), 1) as shot_zone_completeness
          FROM nba_analytics.player_game_summary
          WHERE game_date >= DATE_SUB('{self.game_date}', INTERVAL {self.lookback_days} DAY)
            AND game_date <= '{self.game_date}'
            AND minutes_played > 0
        )
        SELECT
          b.model_beats_vegas,
          b.hit_rate,
          b.mae,
          q.shot_zone_completeness
        FROM baseline_period b, quality_baseline q
        """

        try:
            result = list(self.bq_client.query(query).result())[0]

            return {
                "baseline_model_beats_vegas": float(result.model_beats_vegas) if result.model_beats_vegas else 50.0,
                "baseline_hit_rate": float(result.hit_rate) if result.hit_rate else 52.4,
                "baseline_mae": float(result.mae) if result.mae else 5.0,
                "baseline_shot_zone_completeness": float(result.shot_zone_completeness) if result.shot_zone_completeness else 70.0,
                "lookback_days": self.lookback_days,
            }

        except Exception as e:
            logger.error(f"Failed to calculate baselines: {e}")
            return self._empty_baselines()

    def determine_root_cause(
        self,
        metrics: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, float, List[str]]:
        """
        Determine the most likely root cause of performance issues.

        Args:
            metrics: Combined metrics dict (if not provided, will calculate)

        Returns:
            Tuple of:
                - root_cause: One of VEGAS_SHARP, MODEL_DRIFT, DATA_QUALITY, NORMAL_VARIANCE
                - confidence: 0.0 to 1.0
                - contributing_factors: List of specific issues found
        """
        if metrics is None:
            metrics = {
                'vegas': self.calculate_vegas_sharpness(),
                'drift': self.calculate_model_drift(),
                'quality': self.calculate_data_quality(),
                'baselines': self.calculate_baselines(),
            }

        vegas = metrics.get('vegas', {})
        drift = metrics.get('drift', {})
        quality = metrics.get('quality', {})
        baselines = metrics.get('baselines', {})

        contributing_factors = []
        cause_scores = {
            RootCause.VEGAS_SHARP: 0.0,
            RootCause.MODEL_DRIFT: 0.0,
            RootCause.DATA_QUALITY: 0.0,
            RootCause.NORMAL_VARIANCE: 0.0,
        }

        # Check Vegas sharpness
        model_beats_vegas = vegas.get('overall_model_beats_vegas', 50.0)
        baseline_mbv = baselines.get('baseline_model_beats_vegas', 50.0)
        mbv_drop = baseline_mbv - model_beats_vegas

        if model_beats_vegas < self.THRESHOLDS['vegas_sharp_critical']:
            cause_scores[RootCause.VEGAS_SHARP] += 0.5
            contributing_factors.append(f"Model beats Vegas at {model_beats_vegas}% (critical threshold: {self.THRESHOLDS['vegas_sharp_critical']}%)")
        elif model_beats_vegas < self.THRESHOLDS['vegas_sharp_warning']:
            cause_scores[RootCause.VEGAS_SHARP] += 0.3
            contributing_factors.append(f"Model beats Vegas at {model_beats_vegas}% (below warning threshold)")

        if mbv_drop > 5.0:
            cause_scores[RootCause.VEGAS_SHARP] += 0.2
            contributing_factors.append(f"Model beats Vegas dropped {mbv_drop:.1f}% from baseline")

        # Check model drift
        drift_score = drift.get('drift_score', 0.0)
        hit_rate_7d = drift.get('hit_rate_7d')
        mae_14d = drift.get('mae_14d')

        if drift_score >= self.THRESHOLDS['drift_warning']:
            cause_scores[RootCause.MODEL_DRIFT] += 0.4
            contributing_factors.append(f"Drift score at {drift_score}% (threshold: {self.THRESHOLDS['drift_warning']}%)")

        if hit_rate_7d is not None and hit_rate_7d < self.THRESHOLDS['hit_rate_critical']:
            cause_scores[RootCause.MODEL_DRIFT] += 0.2
            contributing_factors.append(f"7-day hit rate at {hit_rate_7d}% (below {self.THRESHOLDS['hit_rate_critical']}%)")

        if mae_14d is not None and mae_14d > self.THRESHOLDS['mae_warning']:
            cause_scores[RootCause.MODEL_DRIFT] += 0.2
            contributing_factors.append(f"14-day MAE at {mae_14d} (above {self.THRESHOLDS['mae_warning']})")

        # Check data quality
        shot_zone_completeness = quality.get('shot_zone_completeness', 100.0)
        quality_status = quality.get('quality_status', 'OK')

        if shot_zone_completeness < self.THRESHOLDS['shot_zone_completeness_critical']:
            cause_scores[RootCause.DATA_QUALITY] += 0.5
            contributing_factors.append(f"Shot zone completeness at {shot_zone_completeness}% (critical)")
        elif shot_zone_completeness < self.THRESHOLDS['shot_zone_completeness_warning']:
            cause_scores[RootCause.DATA_QUALITY] += 0.3
            contributing_factors.append(f"Shot zone completeness at {shot_zone_completeness}% (warning)")

        # Check for rate sanity (indicates corrupt data)
        avg_paint_rate = quality.get('avg_paint_rate')
        if avg_paint_rate is not None and (avg_paint_rate < 20.0 or avg_paint_rate > 60.0):
            cause_scores[RootCause.DATA_QUALITY] += 0.2
            contributing_factors.append(f"Paint rate at {avg_paint_rate}% (outside normal range 20-60%)")

        # Default to normal variance if no significant signals
        max_score = max(cause_scores.values())
        if max_score < 0.3:
            cause_scores[RootCause.NORMAL_VARIANCE] = 0.5
            if not contributing_factors:
                contributing_factors.append("All metrics within normal ranges")

        # Determine winner
        root_cause = max(cause_scores, key=cause_scores.get)
        confidence = min(cause_scores[root_cause], 1.0)

        # Adjust confidence based on number of signals
        if len(contributing_factors) > 3:
            confidence = min(confidence + 0.1, 1.0)

        logger.info(
            f"Root cause determination: {root_cause.value} "
            f"(confidence: {confidence:.0%}, factors: {len(contributing_factors)})"
        )

        return root_cause.value, round(confidence, 2), contributing_factors

    def run_full_analysis(self) -> Dict[str, Any]:
        """
        Run complete diagnostics analysis.

        Returns combined results dict with all metrics and root cause.
        """
        logger.info(f"Running full performance diagnostics for {self.game_date}")

        vegas_metrics = self.calculate_vegas_sharpness()
        drift_metrics = self.calculate_model_drift()
        quality_metrics = self.calculate_data_quality()
        baselines = self.calculate_baselines()

        metrics = {
            'vegas': vegas_metrics,
            'drift': drift_metrics,
            'quality': quality_metrics,
            'baselines': baselines,
        }

        root_cause, confidence, factors = self.determine_root_cause(metrics)
        alert = self.generate_alert(metrics)

        # Create result object
        self._cached_results = DiagnosticsResult(
            game_date=self.game_date,
            run_timestamp=datetime.now(timezone.utc),
            vegas_metrics=vegas_metrics,
            drift_metrics=drift_metrics,
            data_quality_metrics=quality_metrics,
            baselines=baselines,
            root_cause=root_cause,
            root_cause_confidence=confidence,
            contributing_factors=factors,
            alert_level=alert['level'],
            alert_message=alert['message'],
            recommendations=alert['recommendations'],
        )

        return {
            'game_date': str(self.game_date),
            'vegas': vegas_metrics,
            'drift': drift_metrics,
            'quality': quality_metrics,
            'baselines': baselines,
            'root_cause': root_cause,
            'root_cause_confidence': confidence,
            'contributing_factors': factors,
            'alert': alert,
        }

    def generate_alert(
        self,
        metrics: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate alert based on metrics.

        Args:
            metrics: Combined metrics dict (if not provided, will calculate)

        Returns:
            Dict with:
                - level: CRITICAL, WARNING, INFO, or OK
                - message: Human-readable alert message
                - recommendations: List of action items
        """
        if metrics is None:
            metrics = {
                'vegas': self.calculate_vegas_sharpness(),
                'drift': self.calculate_model_drift(),
                'quality': self.calculate_data_quality(),
                'baselines': self.calculate_baselines(),
            }

        vegas = metrics.get('vegas', {})
        drift = metrics.get('drift', {})
        quality = metrics.get('quality', {})

        model_beats_vegas = vegas.get('overall_model_beats_vegas', 50.0)
        hit_rate_7d = drift.get('hit_rate_7d')
        drift_score = drift.get('drift_score', 0.0)
        shot_zone_completeness = quality.get('shot_zone_completeness', 100.0)

        recommendations = []

        # CRITICAL: Sharp Vegas AND low hit rate
        if (model_beats_vegas < self.THRESHOLDS['vegas_sharp_critical'] and
                hit_rate_7d is not None and hit_rate_7d < self.THRESHOLDS['hit_rate_critical']):
            level = AlertLevel.CRITICAL.value
            message = (
                f"CRITICAL: Model performance severely degraded. "
                f"Model beats Vegas at {model_beats_vegas}%, hit rate at {hit_rate_7d}%. "
                f"Consider pausing predictions until root cause identified."
            )
            recommendations = [
                "Pause predictions or raise confidence threshold",
                "Investigate Vegas line accuracy by tier",
                "Check for external factors (injuries, schedule changes)",
                "Review recent model changes",
            ]

        # WARNING: Sharp Vegas OR high drift
        elif (model_beats_vegas < self.THRESHOLDS['vegas_sharp_warning'] or
              drift_score >= self.THRESHOLDS['drift_warning']):
            level = AlertLevel.WARNING.value
            issues = []
            if model_beats_vegas < self.THRESHOLDS['vegas_sharp_warning']:
                issues.append(f"Vegas sharpening ({model_beats_vegas}% model beats)")
            if drift_score >= self.THRESHOLDS['drift_warning']:
                issues.append(f"Model drift detected ({drift_score}% drift score)")
            message = f"WARNING: {', '.join(issues)}. Monitor closely."
            recommendations = [
                "Increase edge threshold to 5+ points",
                "Focus on Rotation/Bench players where Vegas is softer",
                "Monitor daily for trend continuation",
            ]

        # WARNING: Data quality issues
        elif shot_zone_completeness < self.THRESHOLDS['shot_zone_completeness_warning']:
            level = AlertLevel.WARNING.value
            message = (
                f"WARNING: Data quality concerns. "
                f"Shot zone completeness at {shot_zone_completeness}% (target: 70%+). "
                f"May affect prediction accuracy."
            )
            recommendations = [
                "Check BDB data source availability",
                "Filter predictions to players with complete shot zones",
                "Run backfill for missing shot zone data",
            ]

        # INFO: Minor deviations
        elif (model_beats_vegas < self.THRESHOLDS['vegas_normal'] or
              (hit_rate_7d is not None and hit_rate_7d < self.THRESHOLDS['hit_rate_warning'])):
            level = AlertLevel.INFO.value
            message = (
                f"INFO: Minor performance deviations detected. "
                f"Model beats Vegas: {model_beats_vegas}%, "
                f"7-day hit rate: {hit_rate_7d}%. "
                f"Within acceptable variance but worth monitoring."
            )
            recommendations = [
                "No immediate action required",
                "Continue daily monitoring",
                "Review in 2-3 days if trend continues",
            ]

        # OK: All systems normal
        else:
            level = AlertLevel.OK.value
            message = (
                f"OK: Performance within normal parameters. "
                f"Model beats Vegas: {model_beats_vegas}%, "
                f"Hit rate: {hit_rate_7d}%."
            )
            recommendations = [
                "Continue standard operations",
            ]

        return {
            'level': level,
            'message': message,
            'recommendations': recommendations,
            'generated_at': datetime.now(timezone.utc).isoformat(),
        }

    def persist_results(self) -> bool:
        """
        Write diagnostics results to BigQuery for historical tracking.

        Returns:
            True if successful, False otherwise
        """
        if not self.bq_client:
            logger.warning("No BigQuery client available for persisting results")
            return False

        if self._cached_results is None:
            logger.warning("No results to persist. Run run_full_analysis() first.")
            return False

        try:
            full_table_id = f"{self.project_id}.{self.TABLE_ID}"
            errors = self.bq_client.insert_rows_json(
                full_table_id,
                [self._cached_results.to_dict()]
            )

            if errors:
                logger.error(f"Failed to persist diagnostics results: {errors}")
                return False

            logger.info(f"Persisted diagnostics results for {self.game_date}")
            return True

        except Exception as e:
            logger.error(f"Failed to persist diagnostics results: {e}")
            return False

    # Helper methods for empty metrics

    def _empty_vegas_metrics(self) -> Dict[str, Any]:
        """Return empty Vegas metrics structure."""
        return {
            "overall_model_beats_vegas": 50.0,  # Neutral default
            "vegas_mae": 5.0,  # Reasonable default
            "model_mae": 5.0,  # Reasonable default
            "total_games": 0,
            "by_tier": {},
            "sharpness_status": "NO_DATA",
        }

    def _empty_drift_metrics(self) -> Dict[str, Any]:
        """Return empty drift metrics structure."""
        return {
            "hit_rate_7d": None,
            "hit_rate_14d": None,
            "hit_rate_30d": None,
            "bets_7d": 0,
            "bets_14d": 0,
            "bets_30d": 0,
            "mae_14d": None,
            "mean_error": 0.0,
            "bias_direction": "UNKNOWN",
            "drift_score": 0.0,
            "drift_status": "NO_DATA",
            "breakeven_threshold": 52.4,
        }

    def _empty_quality_metrics(self) -> Dict[str, Any]:
        """Return empty quality metrics structure."""
        return {
            "total_records": 0,
            "shot_zone_completeness": 0.0,
            "avg_paint_rate": None,
            "avg_three_rate": None,
            "players_with_data": 0,
            "feature_quality_score": 0.0,
            "quality_status": "NO_DATA",
        }

    def _empty_baselines(self) -> Dict[str, Any]:
        """Return empty baselines structure."""
        return {
            "baseline_model_beats_vegas": 50.0,
            "baseline_hit_rate": 52.4,
            "baseline_mae": 5.0,
            "baseline_shot_zone_completeness": 70.0,
            "lookback_days": self.lookback_days,
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def run_diagnostics(
    game_date: Optional[date] = None,
    lookback_days: int = 30,
    persist: bool = False
) -> Dict[str, Any]:
    """
    Convenience function to run full diagnostics.

    Args:
        game_date: Date for analysis (defaults to today)
        lookback_days: Days to look back for baselines
        persist: Whether to persist results to BigQuery

    Returns:
        Full diagnostics results dict
    """
    diagnostics = PerformanceDiagnostics(
        game_date=game_date,
        lookback_days=lookback_days
    )
    results = diagnostics.run_full_analysis()

    if persist:
        diagnostics.persist_results()

    return results


def get_root_cause(game_date: Optional[date] = None) -> Tuple[str, float, List[str]]:
    """
    Convenience function to get root cause only.

    Args:
        game_date: Date for analysis (defaults to today)

    Returns:
        Tuple of (root_cause, confidence, contributing_factors)
    """
    diagnostics = PerformanceDiagnostics(game_date=game_date)
    return diagnostics.determine_root_cause()


def get_alert(game_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Convenience function to get alert only.

    Args:
        game_date: Date for analysis (defaults to today)

    Returns:
        Alert dict with level, message, and recommendations
    """
    diagnostics = PerformanceDiagnostics(game_date=game_date)
    return diagnostics.generate_alert()
