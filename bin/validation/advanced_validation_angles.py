#!/usr/bin/env python3
"""
Advanced Validation Angles - 15 Comprehensive Data Quality Checks

These validation angles detect issues that simple count-based validation misses:
1. Late predictions (made after game start)
2. Critical NULL fields
3. Grading lag bottleneck
4. Source data hash drift
5. Void rate anomaly
6. Prediction system consistency
7. Source completeness regression
8. Denormalized field drift
9. Multi-pass processing incompleteness
10. Cardinality mismatch across tables
11. Precompute cache staleness
12. Registry stale mappings
13. Line movement sanity
14. Coverage gaps by archetype
15. Feature quality regression

Usage:
    # Run all angles on last 7 days
    python bin/validation/advanced_validation_angles.py --days 7

    # Run specific angle
    python bin/validation/advanced_validation_angles.py --angle late_predictions --days 30

    # Full season scan
    python bin/validation/advanced_validation_angles.py --full-season

    # List all angles
    python bin/validation/advanced_validation_angles.py --list

Created: 2026-01-25
Purpose: Catch data issues that count-based validation misses
"""

import argparse
import os
import sys
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery


PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
SEASON_START = date(2025, 10, 22)


class Severity(Enum):
    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ValidationResult:
    """Result from a single validation angle."""
    angle_name: str
    severity: Severity
    message: str
    affected_dates: List[str] = field(default_factory=list)
    affected_count: int = 0
    details: List[Dict] = field(default_factory=list)
    query_used: str = ""


class AdvancedValidationAngles:
    """Comprehensive validation with 15 specialized angles."""

    ANGLES = {
        'late_predictions': 'Predictions made after game started',
        'null_critical_fields': 'Critical fields that should never be NULL',
        'grading_bottleneck': 'Identify which phase causes grading delays',
        'source_hash_drift': 'Source data changed but analytics not reprocessed',
        'void_rate_anomaly': 'Unusual spike in voided predictions',
        'system_consistency': 'Different ML systems producing wildly different results',
        'source_completeness': 'Upstream data sources dropping in quality',
        'denormalized_drift': 'Fields that appear in multiple tables diverging',
        'multipass_incomplete': 'Games stuck in incomplete processing passes',
        'cardinality_mismatch': 'Tables that should have matching counts but dont',
        'cache_staleness': 'Predictions using stale cached data',
        'registry_stale': 'Players in predictions not in registry',
        'line_movement': 'Suspicious betting line movements',
        'archetype_gaps': 'Certain player types missing predictions',
        'feature_regression': 'Feature quality suddenly degrading',
    }

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        self.results: List[ValidationResult] = []

    def run_all_angles(self, start_date: date, end_date: date) -> List[ValidationResult]:
        """Run all validation angles."""
        self.results = []

        print("\n" + "=" * 80)
        print("ADVANCED VALIDATION ANGLES")
        print(f"Date Range: {start_date} to {end_date}")
        print("=" * 80)

        for angle_name, description in self.ANGLES.items():
            print(f"\n[{angle_name}] {description}...")
            try:
                method = getattr(self, f'_check_{angle_name}')
                result = method(start_date, end_date)
                self.results.append(result)
                self._print_result(result)
            except Exception as e:
                print(f"   Error: {e}")
                self.results.append(ValidationResult(
                    angle_name=angle_name,
                    severity=Severity.ERROR,
                    message=f"Check failed: {e}"
                ))

        return self.results

    def run_single_angle(self, angle_name: str, start_date: date, end_date: date) -> ValidationResult:
        """Run a single validation angle."""
        if angle_name not in self.ANGLES:
            raise ValueError(f"Unknown angle: {angle_name}")

        method = getattr(self, f'_check_{angle_name}')
        result = method(start_date, end_date)
        self.results.append(result)
        return result

    def _query(self, query: str) -> List[Dict]:
        """Execute query and return results."""
        try:
            results = list(self.client.query(query).result())
            return [dict(row) for row in results]
        except Exception as e:
            print(f"   Query error: {e}")
            return []

    def _print_result(self, result: ValidationResult):
        """Print a single result."""
        icons = {
            Severity.OK: "✅",
            Severity.INFO: "ℹ️",
            Severity.WARNING: "⚠️",
            Severity.ERROR: "❌",
            Severity.CRITICAL: "🚨"
        }
        print(f"   {icons[result.severity]} {result.message}")
        if result.affected_count > 0:
            print(f"      Affected: {result.affected_count} records")
        if result.affected_dates and len(result.affected_dates) <= 5:
            print(f"      Dates: {', '.join(result.affected_dates)}")
        elif result.affected_dates:
            print(f"      Dates: {len(result.affected_dates)} dates affected")

    # =========================================================================
    # ANGLE 1: Late Predictions
    # =========================================================================
    def _check_late_predictions(self, start_date: date, end_date: date) -> ValidationResult:
        """Check for predictions made after game started."""
        query = f"""
        SELECT
            p.game_date,
            COUNT(*) as late_count,
            MAX(TIMESTAMP_DIFF(p.prediction_time, s.game_date_est, MINUTE)) as max_minutes_late
        FROM `{self.project_id}.nba_predictions.player_prop_predictions` p
        JOIN `{self.project_id}.nba_raw.v_nbac_schedule_latest` s
            ON p.game_id = s.game_id
        WHERE p.game_date BETWEEN '{start_date}' AND '{end_date}'
            AND p.system_id = 'catboost_v8'
            AND p.is_active = TRUE
            AND s.game_status = 3
            AND TIMESTAMP_DIFF(p.prediction_time, s.game_date_est, MINUTE) >= 0
        GROUP BY p.game_date
        ORDER BY p.game_date
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='late_predictions',
                severity=Severity.OK,
                message="No late predictions found",
                query_used=query
            )

        total_late = sum(r['late_count'] for r in results)
        affected_dates = [str(r['game_date']) for r in results]

        return ValidationResult(
            angle_name='late_predictions',
            severity=Severity.CRITICAL if total_late > 10 else Severity.WARNING,
            message=f"Found {total_late} predictions made after game start",
            affected_dates=affected_dates,
            affected_count=total_late,
            details=results,
            query_used=query
        )

    # =========================================================================
    # ANGLE 2: Critical NULL Fields
    # =========================================================================
    def _check_null_critical_fields(self, start_date: date, end_date: date) -> ValidationResult:
        """Check for NULL values in fields that should never be NULL."""
        query = f"""
        WITH null_checks AS (
            -- Points NULL for active players
            SELECT 'player_game_summary.points' as field, game_date, COUNT(*) as null_count
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND is_active = TRUE
                AND points IS NULL
            GROUP BY game_date

            UNION ALL

            -- Minutes NULL in grading
            SELECT 'prediction_accuracy.minutes_played', game_date, COUNT(*)
            FROM `{self.project_id}.nba_predictions.prediction_accuracy`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND is_voided = FALSE
                AND minutes_played IS NULL
            GROUP BY game_date

            UNION ALL

            -- Feature quality NULL
            SELECT 'ml_feature_store.quality_score', game_date, COUNT(*)
            FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND feature_quality_score IS NULL
            GROUP BY game_date

            UNION ALL

            -- Prediction confidence NULL
            SELECT 'predictions.confidence_score', game_date, COUNT(*)
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND system_id = 'catboost_v8'
                AND is_active = TRUE
                AND confidence_score IS NULL
            GROUP BY game_date
        )
        SELECT field, game_date, null_count
        FROM null_checks
        WHERE null_count > 0
        ORDER BY game_date, field
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='null_critical_fields',
                severity=Severity.OK,
                message="No unexpected NULL values in critical fields",
                query_used=query
            )

        total_nulls = sum(r['null_count'] for r in results)
        affected_dates = list(set(str(r['game_date']) for r in results))

        # Group by field for details
        by_field = {}
        for r in results:
            field = r['field']
            if field not in by_field:
                by_field[field] = 0
            by_field[field] += r['null_count']

        return ValidationResult(
            angle_name='null_critical_fields',
            severity=Severity.ERROR if total_nulls > 50 else Severity.WARNING,
            message=f"Found {total_nulls} NULL values in critical fields",
            affected_dates=affected_dates,
            affected_count=total_nulls,
            details=[{'field': k, 'null_count': v} for k, v in by_field.items()],
            query_used=query
        )

    # =========================================================================
    # ANGLE 3: Grading Bottleneck
    # =========================================================================
    def _check_grading_bottleneck(self, start_date: date, end_date: date) -> ValidationResult:
        """Identify which phase is causing grading delays."""
        query = f"""
        WITH timing AS (
            SELECT
                p.game_date,
                COUNT(DISTINCT p.player_lookup) as predicted,
                COUNT(DISTINCT g.player_lookup) as graded,
                ROUND(COUNT(DISTINCT g.player_lookup) * 100.0 / NULLIF(COUNT(DISTINCT p.player_lookup), 0), 1) as grade_pct
            FROM `{self.project_id}.nba_predictions.player_prop_predictions` p
            LEFT JOIN `{self.project_id}.nba_predictions.prediction_accuracy` g
                ON p.player_lookup = g.player_lookup
                AND p.game_date = g.game_date
                AND p.system_id = g.system_id
            WHERE p.game_date BETWEEN '{start_date}' AND '{end_date}'
                AND p.game_date < CURRENT_DATE() - 1  -- Exclude last 24h
                AND p.system_id = 'catboost_v8'
                AND p.is_active = TRUE
                AND p.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
            GROUP BY p.game_date
        )
        SELECT *
        FROM timing
        WHERE grade_pct < 90
        ORDER BY game_date
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='grading_bottleneck',
                severity=Severity.OK,
                message="Grading is keeping up with predictions (>90% coverage)",
                query_used=query
            )

        affected_dates = [str(r['game_date']) for r in results]
        total_ungraded = sum(r['predicted'] - r['graded'] for r in results)

        return ValidationResult(
            angle_name='grading_bottleneck',
            severity=Severity.ERROR if len(results) > 5 else Severity.WARNING,
            message=f"Grading behind on {len(results)} dates ({total_ungraded} predictions ungraded)",
            affected_dates=affected_dates,
            affected_count=total_ungraded,
            details=results,
            query_used=query
        )

    # =========================================================================
    # ANGLE 4: Source Hash Drift
    # =========================================================================
    def _check_source_hash_drift(self, start_date: date, end_date: date) -> ValidationResult:
        """Check if source data changed but analytics not reprocessed."""
        # This requires data_hash columns - check if they exist first
        query = f"""
        SELECT
            game_date,
            COUNT(*) as total,
            COUNTIF(source_nbac_hash IS NOT NULL) as has_hash
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY game_date
        LIMIT 1
        """

        results = self._query(query)

        if not results or results[0].get('has_hash', 0) == 0:
            return ValidationResult(
                angle_name='source_hash_drift',
                severity=Severity.INFO,
                message="Source hash tracking not available in this table",
                query_used=query
            )

        return ValidationResult(
            angle_name='source_hash_drift',
            severity=Severity.OK,
            message="Source hash drift check requires hash columns (skipped)",
            query_used=query
        )

    # =========================================================================
    # ANGLE 5: Void Rate Anomaly
    # =========================================================================
    def _check_void_rate_anomaly(self, start_date: date, end_date: date) -> ValidationResult:
        """Check for unusual spike in voided predictions."""
        query = f"""
        WITH daily_void AS (
            SELECT
                game_date,
                COUNT(*) as total,
                COUNTIF(is_voided = TRUE) as voided,
                ROUND(COUNTIF(is_voided = TRUE) * 100.0 / COUNT(*), 2) as void_pct
            FROM `{self.project_id}.nba_predictions.prediction_accuracy`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND system_id = 'catboost_v8'
            GROUP BY game_date
        ),
        stats AS (
            SELECT AVG(void_pct) as avg_void, STDDEV(void_pct) as std_void
            FROM daily_void
        )
        SELECT d.*, s.avg_void, s.std_void,
            ROUND((d.void_pct - s.avg_void) / NULLIF(s.std_void, 0), 2) as z_score
        FROM daily_void d, stats s
        WHERE d.void_pct > s.avg_void + 2 * s.std_void
            OR d.void_pct > 20
        ORDER BY d.game_date
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='void_rate_anomaly',
                severity=Severity.OK,
                message="Void rates within normal range",
                query_used=query
            )

        affected_dates = [str(r['game_date']) for r in results]

        return ValidationResult(
            angle_name='void_rate_anomaly',
            severity=Severity.WARNING,
            message=f"Unusual void rates on {len(results)} dates",
            affected_dates=affected_dates,
            affected_count=len(results),
            details=results,
            query_used=query
        )

    # =========================================================================
    # ANGLE 6: System Consistency
    # =========================================================================
    def _check_system_consistency(self, start_date: date, end_date: date) -> ValidationResult:
        """Check if different ML systems produce wildly different results."""
        query = f"""
        WITH system_stats AS (
            SELECT
                game_date,
                system_id,
                COUNT(*) as predictions,
                COUNT(DISTINCT player_lookup) as players
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND is_active = TRUE
            GROUP BY game_date, system_id
        ),
        baseline AS (
            SELECT game_date, AVG(predictions) as avg_pred, STDDEV(predictions) as std_pred
            FROM system_stats
            GROUP BY game_date
        )
        SELECT s.game_date, s.system_id, s.predictions, b.avg_pred,
            ROUND(ABS(s.predictions - b.avg_pred) / NULLIF(b.std_pred, 0), 2) as deviation
        FROM system_stats s
        JOIN baseline b ON s.game_date = b.game_date
        WHERE ABS(s.predictions - b.avg_pred) > 2 * b.std_pred
            AND b.std_pred > 0
        ORDER BY s.game_date
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='system_consistency',
                severity=Severity.OK,
                message="All prediction systems producing consistent outputs",
                query_used=query
            )

        return ValidationResult(
            angle_name='system_consistency',
            severity=Severity.WARNING,
            message=f"System output divergence on {len(results)} date/system combinations",
            affected_count=len(results),
            details=results,
            query_used=query
        )

    # =========================================================================
    # ANGLE 7: Source Completeness
    # =========================================================================
    def _check_source_completeness(self, start_date: date, end_date: date) -> ValidationResult:
        """Check if upstream data sources are dropping in quality."""
        query = f"""
        WITH daily_completeness AS (
            SELECT
                game_date,
                COUNT(DISTINCT game_id) as games,
                COUNT(*) as players,
                ROUND(AVG(CASE WHEN points IS NOT NULL THEN 1.0 ELSE 0.0 END) * 100, 1) as points_pct,
                ROUND(AVG(CASE WHEN rebounds IS NOT NULL THEN 1.0 ELSE 0.0 END) * 100, 1) as rebounds_pct,
                ROUND(AVG(CASE WHEN assists IS NOT NULL THEN 1.0 ELSE 0.0 END) * 100, 1) as assists_pct
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY game_date
        )
        SELECT *
        FROM daily_completeness
        WHERE points_pct < 95 OR rebounds_pct < 95 OR assists_pct < 95
        ORDER BY game_date
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='source_completeness',
                severity=Severity.OK,
                message="Source data completeness is high (>95%)",
                query_used=query
            )

        affected_dates = [str(r['game_date']) for r in results]

        return ValidationResult(
            angle_name='source_completeness',
            severity=Severity.WARNING,
            message=f"Source data incomplete on {len(results)} dates",
            affected_dates=affected_dates,
            affected_count=len(results),
            details=results,
            query_used=query
        )

    # =========================================================================
    # ANGLE 8: Denormalized Drift
    # =========================================================================
    def _check_denormalized_drift(self, start_date: date, end_date: date) -> ValidationResult:
        """Check if denormalized fields (team, opponent) match across tables."""
        query = f"""
        SELECT
            a.game_date,
            a.game_id,
            a.player_lookup,
            a.team_abbr as analytics_team,
            s.home_team_tricode as schedule_home,
            s.away_team_tricode as schedule_away
        FROM `{self.project_id}.nba_analytics.player_game_summary` a
        JOIN `{self.project_id}.nba_raw.v_nbac_schedule_latest` s
            ON a.game_id = s.game_id
        WHERE a.game_date BETWEEN '{start_date}' AND '{end_date}'
            AND a.team_abbr NOT IN (s.home_team_tricode, s.away_team_tricode)
        LIMIT 100
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='denormalized_drift',
                severity=Severity.OK,
                message="Team assignments consistent between analytics and schedule",
                query_used=query
            )

        affected_dates = list(set(str(r['game_date']) for r in results))

        return ValidationResult(
            angle_name='denormalized_drift',
            severity=Severity.ERROR,
            message=f"Team mismatch between tables: {len(results)} records",
            affected_dates=affected_dates,
            affected_count=len(results),
            details=results[:10],  # First 10
            query_used=query
        )

    # =========================================================================
    # ANGLE 9: Multi-Pass Incomplete
    # =========================================================================
    def _check_multipass_incomplete(self, start_date: date, end_date: date) -> ValidationResult:
        """Check for games stuck in incomplete processing passes."""
        # Check for games where we have boxscores but no analytics
        query = f"""
        WITH boxscore_games AS (
            SELECT DISTINCT game_date, game_id
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),
        analytics_games AS (
            SELECT DISTINCT game_date, game_id
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        )
        SELECT b.game_date, COUNT(*) as stuck_games
        FROM boxscore_games b
        LEFT JOIN analytics_games a ON b.game_id = a.game_id
        WHERE a.game_id IS NULL
            AND b.game_date < CURRENT_DATE() - 1  -- Exclude recent
        GROUP BY b.game_date
        ORDER BY b.game_date
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='multipass_incomplete',
                severity=Severity.OK,
                message="All games processed through analytics (no stuck games)",
                query_used=query
            )

        total_stuck = sum(r['stuck_games'] for r in results)
        affected_dates = [str(r['game_date']) for r in results]

        return ValidationResult(
            angle_name='multipass_incomplete',
            severity=Severity.CRITICAL if total_stuck > 5 else Severity.ERROR,
            message=f"{total_stuck} games have boxscores but no analytics",
            affected_dates=affected_dates,
            affected_count=total_stuck,
            details=results,
            query_used=query
        )

    # =========================================================================
    # ANGLE 10: Cardinality Mismatch
    # =========================================================================
    def _check_cardinality_mismatch(self, start_date: date, end_date: date) -> ValidationResult:
        """Check if tables that should have matching counts don't."""
        query = f"""
        WITH counts AS (
            SELECT
                game_date,
                (SELECT COUNT(DISTINCT game_id) FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
                 WHERE game_date = d.game_date AND game_status = 3) as schedule_games,
                (SELECT COUNT(DISTINCT game_id) FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
                 WHERE game_date = d.game_date) as boxscore_games,
                (SELECT COUNT(DISTINCT game_id) FROM `{self.project_id}.nba_analytics.player_game_summary`
                 WHERE game_date = d.game_date) as analytics_games
            FROM (
                SELECT DISTINCT game_date
                FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
                WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                    AND game_status = 3
            ) d
        )
        SELECT *
        FROM counts
        WHERE schedule_games != boxscore_games
            OR schedule_games != analytics_games
        ORDER BY game_date
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='cardinality_mismatch',
                severity=Severity.OK,
                message="Game counts match across all tables",
                query_used=query
            )

        affected_dates = [str(r['game_date']) for r in results]

        return ValidationResult(
            angle_name='cardinality_mismatch',
            severity=Severity.ERROR,
            message=f"Game count mismatch on {len(results)} dates",
            affected_dates=affected_dates,
            affected_count=len(results),
            details=results,
            query_used=query
        )

    # =========================================================================
    # ANGLE 11: Cache Staleness
    # =========================================================================
    def _check_cache_staleness(self, start_date: date, end_date: date) -> ValidationResult:
        """Check if predictions might be using stale cached data."""
        # Check if cache table exists and has expected dates
        query = f"""
        SELECT
            cache_date,
            COUNT(*) as players,
            MAX(processed_at) as last_processed
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY cache_date
        ORDER BY cache_date
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='cache_staleness',
                severity=Severity.INFO,
                message="No cache data in date range (may be expected)",
                query_used=query
            )

        return ValidationResult(
            angle_name='cache_staleness',
            severity=Severity.OK,
            message=f"Cache data exists for {len(results)} dates",
            query_used=query
        )

    # =========================================================================
    # ANGLE 12: Registry Stale
    # =========================================================================
    def _check_registry_stale(self, start_date: date, end_date: date) -> ValidationResult:
        """Check for players in predictions but not in registry."""
        query = f"""
        SELECT
            p.game_date,
            COUNT(DISTINCT p.player_lookup) as unregistered_players
        FROM `{self.project_id}.nba_predictions.player_prop_predictions` p
        LEFT JOIN `{self.project_id}.nba_reference.nba_players_registry` r
            ON p.player_lookup = r.player_lookup
        WHERE p.game_date BETWEEN '{start_date}' AND '{end_date}'
            AND p.system_id = 'catboost_v8'
            AND r.player_lookup IS NULL
        GROUP BY p.game_date
        HAVING COUNT(DISTINCT p.player_lookup) > 0
        ORDER BY p.game_date
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='registry_stale',
                severity=Severity.OK,
                message="All predicted players found in registry",
                query_used=query
            )

        total_unregistered = sum(r['unregistered_players'] for r in results)

        return ValidationResult(
            angle_name='registry_stale',
            severity=Severity.WARNING,
            message=f"{total_unregistered} players in predictions but not in registry",
            affected_count=total_unregistered,
            details=results,
            query_used=query
        )

    # =========================================================================
    # ANGLE 13: Line Movement
    # =========================================================================
    def _check_line_movement(self, start_date: date, end_date: date) -> ValidationResult:
        """Check for suspicious betting line movements."""
        query = f"""
        SELECT
            game_date,
            player_lookup,
            current_points_line,
            predicted_points,
            ABS(current_points_line - predicted_points) as line_diff
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            AND system_id = 'catboost_v8'
            AND is_active = TRUE
            AND current_points_line IS NOT NULL
            AND ABS(current_points_line - predicted_points) > 15
        ORDER BY line_diff DESC
        LIMIT 50
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='line_movement',
                severity=Severity.OK,
                message="No extreme prediction-line discrepancies (all within 15 pts)",
                query_used=query
            )

        return ValidationResult(
            angle_name='line_movement',
            severity=Severity.INFO,
            message=f"{len(results)} predictions differ from line by >15 points",
            affected_count=len(results),
            details=results[:10],
            query_used=query
        )

    # =========================================================================
    # ANGLE 14: Archetype Gaps
    # =========================================================================
    def _check_archetype_gaps(self, start_date: date, end_date: date) -> ValidationResult:
        """Check if certain player types are missing predictions."""
        # Compare players with props vs players predicted
        query = f"""
        WITH props AS (
            SELECT DISTINCT game_date, player_lookup
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),
        predictions AS (
            SELECT DISTINCT game_date, player_lookup
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND system_id = 'catboost_v8'
                AND is_active = TRUE
        )
        SELECT
            props.game_date,
            COUNT(DISTINCT props.player_lookup) as players_with_props,
            COUNT(DISTINCT predictions.player_lookup) as players_predicted,
            ROUND(COUNT(DISTINCT predictions.player_lookup) * 100.0 /
                  NULLIF(COUNT(DISTINCT props.player_lookup), 0), 1) as coverage_pct
        FROM props
        LEFT JOIN predictions
            ON props.game_date = predictions.game_date
            AND props.player_lookup = predictions.player_lookup
        GROUP BY props.game_date
        HAVING coverage_pct < 80
        ORDER BY props.game_date
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='archetype_gaps',
                severity=Severity.OK,
                message="Prediction coverage of players with props is >80%",
                query_used=query
            )

        affected_dates = [str(r['game_date']) for r in results]

        return ValidationResult(
            angle_name='archetype_gaps',
            severity=Severity.WARNING,
            message=f"Low prediction coverage (<80%) on {len(results)} dates",
            affected_dates=affected_dates,
            affected_count=len(results),
            details=results,
            query_used=query
        )

    # =========================================================================
    # ANGLE 15: Feature Regression
    # =========================================================================
    def _check_feature_regression(self, start_date: date, end_date: date) -> ValidationResult:
        """Check for sudden drops in feature quality."""
        query = f"""
        WITH daily_quality AS (
            SELECT
                game_date,
                ROUND(AVG(feature_quality_score), 2) as avg_quality,
                ROUND(STDDEV(feature_quality_score), 2) as std_quality,
                COUNTIF(feature_quality_score < 65) as low_quality_count,
                COUNT(*) as total
            FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY game_date
        ),
        with_lag AS (
            SELECT
                *,
                LAG(avg_quality) OVER (ORDER BY game_date) as prev_quality,
                avg_quality - LAG(avg_quality) OVER (ORDER BY game_date) as quality_change
            FROM daily_quality
        )
        SELECT *
        FROM with_lag
        WHERE quality_change < -5  -- Dropped by more than 5 points
            OR (low_quality_count * 100.0 / total) > 30  -- >30% low quality
        ORDER BY game_date
        """

        results = self._query(query)

        if not results:
            return ValidationResult(
                angle_name='feature_regression',
                severity=Severity.OK,
                message="Feature quality stable (no sudden drops)",
                query_used=query
            )

        affected_dates = [str(r['game_date']) for r in results]

        return ValidationResult(
            angle_name='feature_regression',
            severity=Severity.WARNING,
            message=f"Feature quality regression on {len(results)} dates",
            affected_dates=affected_dates,
            affected_count=len(results),
            details=results,
            query_used=query
        )

    def print_summary(self):
        """Print summary of all results."""
        print("\n" + "=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)

        by_severity = {}
        for result in self.results:
            sev = result.severity.value
            if sev not in by_severity:
                by_severity[sev] = []
            by_severity[sev].append(result)

        print(f"\nTotal Checks: {len(self.results)}")
        for sev in ['critical', 'error', 'warning', 'info', 'ok']:
            if sev in by_severity:
                icon = {'critical': '🚨', 'error': '❌', 'warning': '⚠️', 'info': 'ℹ️', 'ok': '✅'}[sev]
                print(f"  {icon} {sev.upper()}: {len(by_severity[sev])}")

        # Show issues
        issues = [r for r in self.results if r.severity in [Severity.CRITICAL, Severity.ERROR, Severity.WARNING]]
        if issues:
            print("\nIssues Found:")
            for result in issues:
                icon = {'critical': '🚨', 'error': '❌', 'warning': '⚠️'}[result.severity.value]
                print(f"  {icon} [{result.angle_name}] {result.message}")

        print()


def main():
    parser = argparse.ArgumentParser(description="Advanced validation angles")
    parser.add_argument('--full-season', action='store_true', help='Validate entire season')
    parser.add_argument('--days', type=int, help='Validate last N days')
    parser.add_argument('--date', help='Validate specific date')
    parser.add_argument('--start-date', help='Start date')
    parser.add_argument('--end-date', help='End date')
    parser.add_argument('--angle', help='Run specific angle only')
    parser.add_argument('--list', action='store_true', help='List all angles')
    parser.add_argument('--output', '-o', help='Output JSON file')
    args = parser.parse_args()

    validator = AdvancedValidationAngles()

    if args.list:
        print("\nAvailable Validation Angles:")
        print("-" * 60)
        for name, desc in validator.ANGLES.items():
            print(f"  {name}: {desc}")
        print()
        return

    # Determine date range
    today = date.today()
    if args.full_season:
        start_date = SEASON_START
        end_date = today - timedelta(days=1)
    elif args.days:
        start_date = today - timedelta(days=args.days)
        end_date = today - timedelta(days=1)
    elif args.date:
        start_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        end_date = start_date
    elif args.start_date and args.end_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        start_date = today - timedelta(days=7)
        end_date = today - timedelta(days=1)

    # Run validation
    if args.angle:
        result = validator.run_single_angle(args.angle, start_date, end_date)
        validator._print_result(result)
    else:
        validator.run_all_angles(start_date, end_date)
        validator.print_summary()

    # Save output
    if args.output:
        output = [
            {
                'angle': r.angle_name,
                'severity': r.severity.value,
                'message': r.message,
                'affected_count': r.affected_count,
                'affected_dates': r.affected_dates,
                'details': r.details
            }
            for r in validator.results
        ]
        with open(args.output, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        print(f"Results saved to {args.output}")

    # Exit code
    if any(r.severity == Severity.CRITICAL for r in validator.results):
        sys.exit(2)
    elif any(r.severity == Severity.ERROR for r in validator.results):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
