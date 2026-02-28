#!/usr/bin/env python3
"""
Comprehensive Pipeline Health Check

This script validates the pipeline from multiple angles, focusing on
QUALITY not just COUNTS. It catches issues that simpler validations miss.

Validation Angles:
1. Workflow Decision Health - Is the master controller running?
2. Feature Quality Health - Are features degraded?
3. Prediction Funnel Health - Where are players being filtered?
4. Rolling Window Completeness - Are historical aggregations complete?
5. Grading Lag Health - Is grading keeping up?
6. Cross-Phase Consistency - Do phase outputs match?
7. Props Coverage Health - Are we using available props?

Usage:
    python bin/validation/comprehensive_health_check.py
    python bin/validation/comprehensive_health_check.py --date 2026-01-24
    python bin/validation/comprehensive_health_check.py --alert  # Send Slack alerts
    python bin/validation/comprehensive_health_check.py --json   # JSON output

Created: 2026-01-25
Part of: Pipeline Resilience Improvements
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
from enum import Enum

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')


class Severity(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class HealthCheck:
    """Result of a single health check."""
    name: str
    category: str
    severity: Severity
    message: str
    details: Dict[str, Any]

    def to_dict(self):
        d = asdict(self)
        d['severity'] = self.severity.value
        return d


class ComprehensiveHealthChecker:
    """
    Validates pipeline health from multiple angles.

    Key insight: Count-based validation misses quality degradation.
    This checker focuses on QUALITY metrics in addition to counts.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        self.checks: List[HealthCheck] = []

    def run_all_checks(self, check_date: date) -> List[HealthCheck]:
        """Run all health checks for a given date."""
        self.checks = []

        # 1. Workflow Decision Health
        self._check_workflow_decisions()

        # 2. Feature Quality Health
        self._check_feature_quality(check_date)

        # 3. Prediction Funnel Health
        self._check_prediction_funnel(check_date)

        # 4. Rolling Window Completeness
        self._check_rolling_window_completeness(check_date)

        # 5. Grading Lag Health
        self._check_grading_lag(check_date)

        # 6. Cross-Phase Consistency
        self._check_cross_phase_consistency(check_date)

        # 7. Props Coverage Health
        self._check_props_coverage(check_date)

        # 8. Schedule Freshness
        self._check_schedule_freshness()

        # 9. has_prop_line Consistency
        self._check_prop_line_consistency(check_date)

        # 10. CatBoost Model Status (Session 40)
        self._check_model_status(check_date)

        return self.checks

    def _query(self, sql: str) -> List[Dict]:
        """Execute a query and return results as dicts."""
        try:
            results = list(self.client.query(sql).result())
            return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    def _add_check(self, name: str, category: str, severity: Severity,
                   message: str, details: Dict[str, Any]):
        """Add a health check result."""
        self.checks.append(HealthCheck(
            name=name,
            category=category,
            severity=severity,
            message=message,
            details=details
        ))

    def _check_workflow_decisions(self):
        """Check for gaps in workflow decisions (master controller health)."""
        query = f"""
        WITH decisions_with_gaps AS (
          SELECT
            decision_time,
            LAG(decision_time) OVER (ORDER BY decision_time) as prev_decision,
            TIMESTAMP_DIFF(decision_time, LAG(decision_time) OVER (ORDER BY decision_time), MINUTE) as gap_minutes
          FROM `{self.project_id}.nba_orchestration.workflow_decisions`
          WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
        )
        SELECT
          MAX(gap_minutes) as max_gap_minutes,
          MAX(decision_time) as last_decision,
          TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(decision_time), MINUTE) as minutes_since_last
        FROM decisions_with_gaps
        """

        results = self._query(query)
        if not results or results[0].get('last_decision') is None:
            self._add_check(
                name="workflow_decisions",
                category="orchestration",
                severity=Severity.CRITICAL,
                message="No workflow decisions found in last 48 hours!",
                details={"status": "no_data"}
            )
            return

        row = results[0]
        max_gap = row.get('max_gap_minutes') or 0
        minutes_since = row.get('minutes_since_last') or 0

        if minutes_since > 120:
            severity = Severity.CRITICAL
            message = f"Master controller not running! Last decision {minutes_since} min ago"
        elif max_gap > 180:
            severity = Severity.ERROR
            message = f"Large gap in decisions: {max_gap} min in last 48h"
        elif max_gap > 120:
            severity = Severity.WARNING
            message = f"Gap in decisions: {max_gap} min (threshold: 120)"
        else:
            severity = Severity.OK
            message = f"Workflow decisions healthy (max gap: {max_gap} min)"

        self._add_check(
            name="workflow_decisions",
            category="orchestration",
            severity=severity,
            message=message,
            details={
                "max_gap_minutes": max_gap,
                "minutes_since_last": minutes_since,
                "threshold_minutes": 120
            }
        )

    def _check_feature_quality(self, check_date: date):
        """Check feature quality scores (not just counts)."""
        query = f"""
        SELECT
          COUNT(*) as total_features,
          ROUND(AVG(feature_quality_score), 2) as avg_quality,
          COUNTIF(feature_quality_score < 65) as low_quality_count,
          ROUND(COUNTIF(feature_quality_score < 65) * 100.0 / COUNT(*), 1) as low_quality_pct
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = '{check_date}'
        """

        results = self._query(query)
        if not results or results[0].get('total_features') == 0:
            self._add_check(
                name="feature_quality",
                category="features",
                severity=Severity.ERROR,
                message=f"No features found for {check_date}",
                details={"status": "no_data"}
            )
            return

        row = results[0]
        avg_quality = row.get('avg_quality') or 0
        low_pct = row.get('low_quality_pct') or 0
        total = row.get('total_features') or 0

        if avg_quality < 65:
            severity = Severity.CRITICAL
            message = f"Feature quality critically low: {avg_quality} avg (threshold: 65)"
        elif avg_quality < 70:
            severity = Severity.ERROR
            message = f"Feature quality degraded: {avg_quality} avg (target: 75+)"
        elif low_pct > 30:
            severity = Severity.WARNING
            message = f"{low_pct}% of features are low quality"
        else:
            severity = Severity.OK
            message = f"Feature quality healthy: {avg_quality} avg, {low_pct}% low"

        self._add_check(
            name="feature_quality",
            category="features",
            severity=severity,
            message=message,
            details={
                "total_features": total,
                "avg_quality": avg_quality,
                "low_quality_pct": low_pct,
                "threshold_avg": 70,
                "threshold_low_pct": 30
            }
        )

    def _check_prediction_funnel(self, check_date: date):
        """Check prediction funnel - where are players being filtered?"""
        query = f"""
        WITH boxscores AS (
          SELECT COUNT(DISTINCT player_lookup) as players
          FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
          WHERE game_date = '{check_date}'
        ),
        features AS (
          SELECT
            COUNT(DISTINCT player_lookup) as players,
            COUNTIF(feature_quality_score >= 65) as high_quality
          FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
          WHERE game_date = '{check_date}'
        ),
        props AS (
          SELECT COUNT(DISTINCT player_lookup) as players
          FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
          WHERE game_date = '{check_date}'
        ),
        predictions AS (
          SELECT COUNT(DISTINCT player_lookup) as players
          FROM `{self.project_id}.nba_predictions.player_prop_predictions`
          WHERE game_date = '{check_date}'
            AND system_id = 'catboost_v8' AND is_active = TRUE
        )
        SELECT
          b.players as boxscore_players,
          f.players as feature_players,
          f.high_quality as high_quality_features,
          pr.players as props_players,
          p.players as predicted_players
        FROM boxscores b, features f, props pr, predictions p
        """

        results = self._query(query)
        if not results:
            self._add_check(
                name="prediction_funnel",
                category="predictions",
                severity=Severity.ERROR,
                message=f"Could not analyze prediction funnel for {check_date}",
                details={"status": "query_failed"}
            )
            return

        row = results[0]
        boxscore = row.get('boxscore_players') or 0
        features = row.get('feature_players') or 0
        high_quality = row.get('high_quality_features') or 0
        props = row.get('props_players') or 0
        predicted = row.get('predicted_players') or 0

        # Calculate conversion rates
        feature_rate = (features / boxscore * 100) if boxscore > 0 else 0
        quality_rate = (high_quality / features * 100) if features > 0 else 0

        # Determine severity
        issues = []
        severity = Severity.OK

        if feature_rate < 90:
            issues.append(f"Low feature coverage: {feature_rate:.0f}%")
            severity = Severity.WARNING

        if quality_rate < 70:
            issues.append(f"Low quality rate: {quality_rate:.0f}%")
            severity = Severity.ERROR if quality_rate < 50 else Severity.WARNING

        if predicted == 0 and props > 0:
            issues.append("Zero predictions despite available props!")
            severity = Severity.CRITICAL

        if issues:
            message = "; ".join(issues)
        else:
            message = f"Funnel healthy: {boxscore}→{features}→{high_quality}→{predicted}"

        self._add_check(
            name="prediction_funnel",
            category="predictions",
            severity=severity,
            message=message,
            details={
                "boxscore_players": boxscore,
                "feature_players": features,
                "high_quality_features": high_quality,
                "props_players": props,
                "predicted_players": predicted,
                "feature_coverage_pct": round(feature_rate, 1),
                "quality_rate_pct": round(quality_rate, 1)
            }
        )

    def _check_rolling_window_completeness(self, check_date: date):
        """Check that rolling window calculations are complete."""
        query = f"""
        SELECT
          ROUND(AVG(l7d_completeness_pct), 1) as avg_l7d_completeness,
          ROUND(AVG(l14d_completeness_pct), 1) as avg_l14d_completeness,
          COUNTIF(is_production_ready = FALSE) as not_ready_count,
          COUNT(*) as total_count
        FROM `{self.project_id}.nba_analytics.upcoming_team_game_context`
        WHERE game_date = '{check_date}'
        """

        results = self._query(query)
        if not results or results[0].get('total_count') == 0:
            # May be a future date or no games
            self._add_check(
                name="rolling_window_completeness",
                category="features",
                severity=Severity.OK,
                message=f"No team context data for {check_date} (may be future/no games)",
                details={"status": "no_data"}
            )
            return

        row = results[0]
        l7d = row.get('avg_l7d_completeness') or 0
        l14d = row.get('avg_l14d_completeness') or 0
        not_ready = row.get('not_ready_count') or 0
        total = row.get('total_count') or 0

        if l7d < 50 or l14d < 50:
            severity = Severity.CRITICAL
            message = f"Rolling windows severely incomplete: L7D={l7d}%, L14D={l14d}%"
        elif l7d < 70 or l14d < 70:
            severity = Severity.ERROR
            message = f"Rolling windows incomplete: L7D={l7d}%, L14D={l14d}%"
        elif not_ready > total * 0.3:
            severity = Severity.WARNING
            message = f"{not_ready}/{total} teams not production ready"
        else:
            severity = Severity.OK
            message = f"Rolling windows healthy: L7D={l7d}%, L14D={l14d}%"

        self._add_check(
            name="rolling_window_completeness",
            category="features",
            severity=severity,
            message=message,
            details={
                "avg_l7d_completeness": l7d,
                "avg_l14d_completeness": l14d,
                "not_production_ready": not_ready,
                "total_teams": total,
                "threshold_pct": 70
            }
        )

    def _check_grading_lag(self, check_date: date):
        """Check if grading is keeping up with predictions."""
        # Only check dates > 24h old (grading needs actuals)
        if check_date >= date.today():
            self._add_check(
                name="grading_lag",
                category="grading",
                severity=Severity.OK,
                message=f"Skipping grading check - {check_date} is today/future",
                details={"status": "skipped_recent"}
            )
            return

        query = f"""
        WITH predictions AS (
          SELECT COUNT(*) as pred_count
          FROM `{self.project_id}.nba_predictions.player_prop_predictions`
          WHERE game_date = '{check_date}'
            AND system_id = 'catboost_v8' AND is_active = TRUE
            AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')  -- v4.1: Use line_source instead of buggy has_prop_line
        ),
        graded AS (
          SELECT COUNT(*) as graded_count
          FROM `{self.project_id}.nba_predictions.prediction_accuracy`
          WHERE game_date = '{check_date}'
            AND system_id = 'catboost_v8'
        )
        SELECT
          p.pred_count,
          g.graded_count,
          ROUND(g.graded_count * 100.0 / NULLIF(p.pred_count, 0), 1) as grading_pct
        FROM predictions p, graded g
        """

        results = self._query(query)
        if not results:
            return

        row = results[0]
        predictions = row.get('pred_count') or 0
        graded = row.get('graded_count') or 0
        grading_pct = row.get('grading_pct') or 0

        if predictions == 0:
            severity = Severity.WARNING
            message = f"No predictions to grade for {check_date}"
        elif grading_pct < 50:
            severity = Severity.CRITICAL
            message = f"Grading severely behind: {grading_pct}% ({graded}/{predictions})"
        elif grading_pct < 80:
            severity = Severity.ERROR
            message = f"Grading behind: {grading_pct}% ({graded}/{predictions})"
        elif grading_pct < 95:
            severity = Severity.WARNING
            message = f"Grading slightly behind: {grading_pct}%"
        else:
            severity = Severity.OK
            message = f"Grading complete: {grading_pct}% ({graded}/{predictions})"

        self._add_check(
            name="grading_lag",
            category="grading",
            severity=severity,
            message=message,
            details={
                "predictions": predictions,
                "graded": graded,
                "grading_pct": grading_pct,
                "threshold_pct": 80
            }
        )

    def _check_cross_phase_consistency(self, check_date: date):
        """Check that phase outputs are consistent.

        NOTE: game_id formats differ between tables:
          - nba_reference.nba_schedule: NBA numeric IDs (e.g., 0022500852)
          - nba_analytics.player_game_summary: date_away_home (e.g., 20260226_MIA_PHI)
          - nba_raw.bdl_player_boxscores: YYYYMMDD_AWAY_HOME format

        Session 363 fix: Join schedule→analytics using constructed game_id
        (YYYYMMDD_AWAY_HOME) to bridge the format mismatch. Previously the
        analytics CTE counted games independently, which worked for counts
        but couldn't detect per-game gaps.
        """
        check_date_str = str(check_date)
        check_date_compact = check_date_str.replace('-', '')
        query = f"""
        WITH schedule AS (
          SELECT
            game_id,
            away_team_tricode,
            home_team_tricode,
            -- Construct analytics-format game_id for cross-phase join
            CONCAT('{check_date_compact}', '_', away_team_tricode, '_', home_team_tricode) as analytics_game_id
          FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
          WHERE game_date = '{check_date}' AND game_status = 3
        ),
        analytics AS (
          SELECT DISTINCT game_id
          FROM `{self.project_id}.nba_analytics.player_game_summary`
          WHERE game_date = '{check_date}'
        ),
        -- Cross-check: schedule games matched to analytics (using constructed game_id)
        schedule_with_analytics AS (
          SELECT COUNT(DISTINCT s.game_id) as matched_games
          FROM schedule s
          INNER JOIN analytics a ON s.analytics_game_id = a.game_id
        )
        SELECT
          (SELECT COUNT(*) FROM schedule) as schedule_games,
          (SELECT COUNT(*) FROM analytics) as analytics_games,
          sa.matched_games as schedule_analytics_matched
        FROM schedule_with_analytics sa
        """

        results = self._query(query)
        if not results:
            return

        row = results[0]
        schedule = row.get('schedule_games') or 0
        analytics = row.get('analytics_games') or 0
        matched = row.get('schedule_analytics_matched') or 0

        issues = []
        severity = Severity.OK

        # Use matched count (constructed game_id join) for accurate comparison
        if schedule > 0 and matched < schedule:
            missing = schedule - matched
            issues.append(f"Missing analytics: {matched}/{schedule} schedule games have analytics ({missing} missing)")
            severity = Severity.ERROR if matched == 0 else Severity.WARNING

        if issues:
            message = "; ".join(issues)
        else:
            if schedule == 0:
                message = f"No final games for {check_date}"
                severity = Severity.OK
            else:
                message = f"Phases consistent: {schedule} scheduled → {analytics} analytics ({matched} matched)"

        self._add_check(
            name="cross_phase_consistency",
            category="pipeline",
            severity=severity,
            message=message,
            details={
                "schedule_games": schedule,
                "analytics_games": analytics,
                "schedule_analytics_matched": matched
            }
        )

    def _check_props_coverage(self, check_date: date):
        """Check if we're making predictions for available props."""
        query = f"""
        WITH props AS (
          SELECT COUNT(DISTINCT player_lookup) as players
          FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
          WHERE game_date = '{check_date}'
        ),
        predictions_with_props AS (
          SELECT COUNT(DISTINCT player_lookup) as players
          FROM `{self.project_id}.nba_predictions.player_prop_predictions`
          WHERE game_date = '{check_date}'
            AND system_id = 'catboost_v8' AND is_active = TRUE
            AND line_source = 'ACTUAL_PROP'
        )
        SELECT
          p.players as props_players,
          pr.players as predicted_with_props,
          ROUND(pr.players * 100.0 / NULLIF(p.players, 0), 1) as coverage_pct
        FROM props p, predictions_with_props pr
        """

        results = self._query(query)
        if not results:
            return

        row = results[0]
        props = row.get('props_players') or 0
        predicted = row.get('predicted_with_props') or 0
        coverage = row.get('coverage_pct') or 0

        if props == 0:
            severity = Severity.OK
            message = f"No props available for {check_date} (normal for future/early dates)"
        elif coverage < 50:
            severity = Severity.ERROR
            message = f"Low props coverage: {coverage}% ({predicted}/{props})"
        elif coverage < 70:
            severity = Severity.WARNING
            message = f"Props coverage below target: {coverage}%"
        else:
            severity = Severity.OK
            message = f"Props coverage good: {coverage}% ({predicted}/{props})"

        self._add_check(
            name="props_coverage",
            category="predictions",
            severity=severity,
            message=message,
            details={
                "props_players": props,
                "predicted_with_props": predicted,
                "coverage_pct": coverage,
                "target_pct": 70
            }
        )

    def _check_schedule_freshness(self):
        """Check if schedule data is fresh."""
        # Check the raw schedule table for last update time
        query = f"""
        SELECT
          MAX(processed_at) as last_update,
          TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_stale
        FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
        WHERE game_date >= CURRENT_DATE() - 1
        """

        results = self._query(query)
        if not results or results[0].get('last_update') is None:
            # Fallback: check if we have recent game data
            fallback_query = f"""
            SELECT
              MAX(game_date) as last_game_date,
              DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
            FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
            WHERE game_status = 3
            """
            fallback_results = self._query(fallback_query)
            if fallback_results and fallback_results[0].get('last_game_date'):
                days_stale = fallback_results[0].get('days_stale') or 0
                if days_stale > 2:
                    severity = Severity.WARNING
                    message = f"Schedule may be stale - last final game {days_stale} days ago"
                else:
                    severity = Severity.OK
                    message = f"Schedule appears current (last final game {days_stale} days ago)"
                self._add_check(
                    name="schedule_freshness",
                    category="data",
                    severity=severity,
                    message=message,
                    details={"days_since_last_final": days_stale}
                )
            else:
                self._add_check(
                    name="schedule_freshness",
                    category="data",
                    severity=Severity.WARNING,
                    message="Could not determine schedule freshness",
                    details={"status": "no_data"}
                )
            return

        hours_stale = results[0].get('hours_stale') or 0

        if hours_stale > 12:
            severity = Severity.ERROR
            message = f"Schedule very stale: {hours_stale}h old"
        elif hours_stale > 6:
            severity = Severity.WARNING
            message = f"Schedule stale: {hours_stale}h old"
        else:
            severity = Severity.OK
            message = f"Schedule fresh: {hours_stale}h old"

        self._add_check(
            name="schedule_freshness",
            category="data",
            severity=severity,
            message=message,
            details={
                "hours_stale": hours_stale,
                "threshold_hours": 6
            }
        )


    def _check_prop_line_consistency(self, check_date: date):
        """Check for has_prop_line data bug (line_source=ACTUAL_PROP but has_prop_line=false)."""
        query = f"""
        SELECT
          COUNTIF(line_source = 'ACTUAL_PROP' AND has_prop_line = FALSE) as inconsistent,
          COUNTIF(line_source = 'ACTUAL_PROP' AND has_prop_line = TRUE) as consistent,
          COUNTIF(line_source = 'ACTUAL_PROP') as total_actual_prop
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date = '{check_date}'
          AND system_id = 'catboost_v8' AND is_active = TRUE
        """

        results = self._query(query)
        if not results:
            return

        row = results[0]
        inconsistent = row.get('inconsistent') or 0
        consistent = row.get('consistent') or 0
        total = row.get('total_actual_prop') or 0

        if total == 0:
            severity = Severity.OK
            message = "No ACTUAL_PROP predictions to check"
        elif inconsistent > 0:
            pct = round(inconsistent * 100.0 / total, 1)
            if pct > 50:
                severity = Severity.CRITICAL
                message = f"DATA BUG: {inconsistent}/{total} ({pct}%) have line_source=ACTUAL_PROP but has_prop_line=false"
            else:
                severity = Severity.ERROR
                message = f"Data inconsistency: {inconsistent} predictions with wrong has_prop_line flag"
        else:
            severity = Severity.OK
            message = f"Prop line flags consistent ({total} ACTUAL_PROP predictions)"

        self._add_check(
            name="prop_line_consistency",
            category="data_quality",
            severity=severity,
            message=message,
            details={
                "inconsistent_count": inconsistent,
                "consistent_count": consistent,
                "total_actual_prop": total
            }
        )

    def _check_model_status(self, check_date: date):
        """
        Check CatBoost model status - detect fallback mode (Session 40).

        Fallback mode indicators:
        1. All catboost_v8 predictions have confidence_score = 50.0 (weighted average)
        2. model_type = 'fallback' in predictions
        3. prediction_error_code = 'MODEL_NOT_LOADED'

        This is a CRITICAL issue - fallback mode should never happen in production.
        """
        query = f"""
        SELECT
          COUNT(*) as total_predictions,
          COUNTIF(confidence_score = 50.0) as fallback_confidence_count,
          COUNTIF(model_type = 'fallback') as explicit_fallback_count,
          COUNTIF(prediction_error_code IS NOT NULL) as error_code_count,
          COUNTIF(prediction_error_code = 'MODEL_NOT_LOADED') as model_not_loaded_count,
          COUNTIF(prediction_error_code = 'FEATURE_PREPARATION_FAILED') as feature_failed_count,
          COUNTIF(prediction_error_code = 'MODEL_PREDICTION_FAILED') as prediction_failed_count,
          AVG(confidence_score) as avg_confidence,
          MIN(confidence_score) as min_confidence,
          MAX(confidence_score) as max_confidence
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date = '{check_date}'
          AND system_id = 'catboost_v8'
          AND is_active = TRUE
        """

        results = self._query(query)
        if not results:
            self._add_check(
                name="model_status",
                category="model",
                severity=Severity.WARNING,
                message="No CatBoost V8 predictions found for date",
                details={"game_date": str(check_date)}
            )
            return

        row = results[0]
        total = row.get('total_predictions') or 0
        fallback_conf = row.get('fallback_confidence_count') or 0
        explicit_fallback = row.get('explicit_fallback_count') or 0
        model_not_loaded = row.get('model_not_loaded_count') or 0
        feature_failed = row.get('feature_failed_count') or 0
        prediction_failed = row.get('prediction_failed_count') or 0
        avg_conf = row.get('avg_confidence') or 0
        min_conf = row.get('min_confidence') or 0
        max_conf = row.get('max_confidence') or 0

        if total == 0:
            severity = Severity.WARNING
            message = "No CatBoost V8 predictions found"
        elif model_not_loaded > 0:
            # CRITICAL: Model not loaded should NEVER happen after Session 40 fix
            severity = Severity.CRITICAL
            message = (
                f"MODEL NOT LOADED: {model_not_loaded}/{total} predictions have MODEL_NOT_LOADED error. "
                f"This should never happen - check CATBOOST_V8_MODEL_PATH and redeploy worker."
            )
        elif fallback_conf == total and total > 10:
            # All predictions have exactly 50% confidence - strong fallback indicator
            severity = Severity.CRITICAL
            message = (
                f"FALLBACK MODE DETECTED: All {total} predictions have 50% confidence. "
                f"Model is likely not loaded. Check worker logs for ModelLoadError."
            )
        elif explicit_fallback > total * 0.1:
            # More than 10% explicit fallbacks
            pct = round(explicit_fallback * 100.0 / total, 1)
            severity = Severity.ERROR
            message = f"High fallback rate: {explicit_fallback}/{total} ({pct}%) predictions in fallback mode"
        elif feature_failed + prediction_failed > total * 0.05:
            # More than 5% feature/prediction failures
            error_count = feature_failed + prediction_failed
            pct = round(error_count * 100.0 / total, 1)
            severity = Severity.WARNING
            message = f"Prediction errors: {error_count}/{total} ({pct}%) had feature or prediction failures"
        elif avg_conf < 55:
            # Low average confidence might indicate issues
            severity = Severity.WARNING
            message = f"Low average confidence: {avg_conf:.1f}% (expected 60-80%)"
        else:
            severity = Severity.OK
            message = f"Model healthy: {total} predictions, avg confidence {avg_conf:.1f}%"

        self._add_check(
            name="model_status",
            category="model",
            severity=severity,
            message=message,
            details={
                "total_predictions": total,
                "fallback_confidence_count": fallback_conf,
                "explicit_fallback_count": explicit_fallback,
                "model_not_loaded_count": model_not_loaded,
                "feature_failed_count": feature_failed,
                "prediction_failed_count": prediction_failed,
                "avg_confidence": round(avg_conf, 2) if avg_conf else None,
                "min_confidence": round(min_conf, 2) if min_conf else None,
                "max_confidence": round(max_conf, 2) if max_conf else None,
            }
        )


def print_report(checks: List[HealthCheck], check_date: date):
    """Print a formatted health report."""
    print(f"\n{'='*80}")
    print(f"COMPREHENSIVE HEALTH CHECK: {check_date}")
    print(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}")

    # Count by severity
    by_severity = {}
    for check in checks:
        sev = check.severity.value
        by_severity[sev] = by_severity.get(sev, 0) + 1

    # Summary
    print(f"\nSummary: {len(checks)} checks")
    for sev in ['critical', 'error', 'warning', 'ok']:
        count = by_severity.get(sev, 0)
        if count > 0:
            emoji = {'critical': '🔴', 'error': '🟠', 'warning': '🟡', 'ok': '🟢'}[sev]
            print(f"  {emoji} {sev.upper()}: {count}")

    # Group by category
    by_category = {}
    for check in checks:
        cat = check.category
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(check)

    # Print details
    for category, cat_checks in sorted(by_category.items()):
        print(f"\n{'-'*40}")
        print(f"{category.upper()}")
        print(f"{'-'*40}")

        for check in cat_checks:
            emoji = {
                Severity.CRITICAL: '🔴',
                Severity.ERROR: '🟠',
                Severity.WARNING: '🟡',
                Severity.OK: '🟢'
            }[check.severity]

            print(f"\n{emoji} {check.name}")
            print(f"   {check.message}")

            if check.severity != Severity.OK:
                for key, value in check.details.items():
                    if key not in ['status']:
                        print(f"   - {key}: {value}")

    print(f"\n{'='*80}")

    # Return exit code based on worst severity
    if by_severity.get('critical', 0) > 0:
        return 2
    elif by_severity.get('error', 0) > 0:
        return 1
    else:
        return 0


def send_slack_alert(checks: List[HealthCheck], check_date: date):
    """Send Slack alert for issues."""
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set, skipping alert")
        return

    import requests

    issues = [c for c in checks if c.severity in [Severity.CRITICAL, Severity.ERROR]]

    if not issues:
        return  # No alert needed

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🚨 Pipeline Health Alert - {check_date}",
                "emoji": True
            }
        }
    ]

    for check in issues:
        emoji = '🔴' if check.severity == Severity.CRITICAL else '🟠'
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{check.name}*: {check.message}"
            }
        })

    try:
        response = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
        response.raise_for_status()
        logger.info("Slack alert sent")
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")


def main():
    parser = argparse.ArgumentParser(description="Comprehensive pipeline health check")
    parser.add_argument('--date', type=str, help='Date to check (YYYY-MM-DD), default: yesterday')
    parser.add_argument('--alert', action='store_true', help='Send Slack alert on issues')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    if args.date:
        check_date = date.fromisoformat(args.date)
    else:
        check_date = date.today() - timedelta(days=1)

    logger.info(f"Running comprehensive health check for {check_date}")

    checker = ComprehensiveHealthChecker()
    checks = checker.run_all_checks(check_date)

    if args.json:
        output = {
            "check_date": str(check_date),
            "run_time": datetime.now().isoformat(),
            "checks": [c.to_dict() for c in checks]
        }
        print(json.dumps(output, indent=2))
        exit_code = 0
    else:
        exit_code = print_report(checks, check_date)

    if args.alert:
        send_slack_alert(checks, check_date)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
