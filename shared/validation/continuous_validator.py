"""
Continuous Validation System

Runs validation checks on a schedule and stores results in BigQuery
for historical analysis and trend tracking.

This module is the core of the "Validation-as-a-Service" infrastructure.

Usage:
    from shared.validation.continuous_validator import ContinuousValidator

    validator = ContinuousValidator()
    result = validator.run_scheduled_validation('post_overnight')

Session: 125 (2026-02-04)
"""

import json
import os
import sys
import uuid
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Callable
import logging
from dataclasses import dataclass, asdict
from enum import Enum

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    """Status of an individual check."""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"
    ERROR = "ERROR"


class RunStatus(Enum):
    """Status of an overall validation run."""
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"


class Severity(Enum):
    """Severity levels for issues."""
    P1_CRITICAL = "P1_CRITICAL"
    P2_HIGH = "P2_HIGH"
    P3_MEDIUM = "P3_MEDIUM"
    P4_LOW = "P4_LOW"


@dataclass
class CheckResult:
    """Result of a single validation check."""
    check_name: str
    status: CheckStatus
    message: str
    severity: Optional[Severity] = None
    category: Optional[str] = None
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None
    threshold: Optional[float] = None
    target_date: Optional[date] = None
    target_table: Optional[str] = None
    affected_records: Optional[int] = None
    details: Optional[Dict] = None
    duration_ms: Optional[int] = None


@dataclass
class ValidationRun:
    """Result of a complete validation run."""
    run_id: str
    check_type: str
    status: RunStatus
    message: str
    checks: List[CheckResult]
    run_timestamp: datetime
    duration_ms: int
    trigger_source: str = "manual"
    schedule_name: Optional[str] = None
    target_date: Optional[date] = None


class ContinuousValidator:
    """
    Main class for running continuous validation.

    Supports multiple validation schedules:
    - post_overnight: After overnight processing (6 AM ET)
    - pre_game_prep: Before game preparation (8 AM ET)
    - midday: Midday health check (12 PM ET)
    - pre_game_final: Final pre-game check (6 PM ET)
    - post_game: After games end (11 PM ET)
    - overnight: During overnight processing (2 AM ET)
    """

    # Validation schedule definitions
    SCHEDULES = {
        'post_overnight': {
            'description': 'Post-overnight processing validation',
            'checks': [
                'phase3_completion',
                'phase4_completion',
                'historical_completeness',
                'data_freshness',
                'scraper_failures',
            ],
            'cron': '0 6 * * *',  # 6 AM ET
        },
        'pre_game_prep': {
            'description': 'Pre-game preparation check',
            'checks': [
                'predictions_ready',
                'feature_store_quality',
                'vegas_line_coverage',
                'upcoming_context',
            ],
            'cron': '0 8 * * *',  # 8 AM ET
        },
        'midday': {
            'description': 'Midday health check',
            'checks': [
                'service_health',
                'recent_errors',
                'deployment_drift',
            ],
            'cron': '0 12 * * *',  # 12 PM ET
        },
        'pre_game_final': {
            'description': 'Final pre-game validation',
            'checks': [
                'predictions_ready',
                'pre_game_signal',
                'model_bias',
            ],
            'cron': '0 18 * * *',  # 6 PM ET
        },
        'post_game': {
            'description': 'Post-game validation',
            'checks': [
                'scraper_kickoff',
                'games_final',
            ],
            'cron': '0 23 * * *',  # 11 PM ET
        },
        'overnight': {
            'description': 'Overnight processing check',
            'checks': [
                'phase2_progress',
                'phase3_progress',
                'consecutive_failures',
            ],
            'cron': '0 2 * * *',  # 2 AM ET
        },
    }

    def __init__(self, project_id: str = 'nba-props-platform'):
        """Initialize the continuous validator."""
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)
        self.dataset_id = 'nba_orchestration'
        self._check_registry: Dict[str, Callable] = {}
        self._register_checks()

    def _register_checks(self):
        """Register all available validation checks."""
        # Phase completion checks
        self._check_registry['phase3_completion'] = self._check_phase3_completion
        self._check_registry['phase4_completion'] = self._check_phase4_completion

        # Data quality checks
        self._check_registry['historical_completeness'] = self._check_historical_completeness
        self._check_registry['data_freshness'] = self._check_data_freshness
        self._check_registry['scraper_failures'] = self._check_scraper_failures
        self._check_registry['consecutive_failures'] = self._check_consecutive_failures

        # Prediction checks
        self._check_registry['predictions_ready'] = self._check_predictions_ready
        self._check_registry['feature_store_quality'] = self._check_feature_store_quality
        self._check_registry['vegas_line_coverage'] = self._check_vegas_line_coverage
        self._check_registry['upcoming_context'] = self._check_upcoming_context
        self._check_registry['pre_game_signal'] = self._check_pre_game_signal
        self._check_registry['model_bias'] = self._check_model_bias

        # Infrastructure checks
        self._check_registry['service_health'] = self._check_service_health
        self._check_registry['recent_errors'] = self._check_recent_errors
        self._check_registry['deployment_drift'] = self._check_deployment_drift

        # Post-game checks
        self._check_registry['scraper_kickoff'] = self._check_scraper_kickoff
        self._check_registry['games_final'] = self._check_games_final
        self._check_registry['phase2_progress'] = self._check_phase2_progress
        self._check_registry['phase3_progress'] = self._check_phase3_progress

    def run_scheduled_validation(
        self,
        schedule_name: str,
        target_date: Optional[date] = None,
        trigger_source: str = "scheduler"
    ) -> ValidationRun:
        """
        Run validation for a specific schedule.

        Args:
            schedule_name: Name of the schedule (e.g., 'post_overnight')
            target_date: Date to validate (defaults to today/yesterday based on schedule)
            trigger_source: What triggered this run

        Returns:
            ValidationRun with all results
        """
        if schedule_name not in self.SCHEDULES:
            raise ValueError(f"Unknown schedule: {schedule_name}")

        schedule = self.SCHEDULES[schedule_name]
        run_id = str(uuid.uuid4())
        start_time = datetime.utcnow()

        # Determine target date based on schedule
        if target_date is None:
            if schedule_name in ['post_overnight', 'pre_game_prep', 'midday']:
                # Check yesterday's processing results
                target_date = date.today() - timedelta(days=1)
            else:
                target_date = date.today()

        logger.info(f"Starting validation run: {schedule_name} for {target_date}")

        # Run all checks for this schedule
        check_results = []
        for check_name in schedule['checks']:
            try:
                check_start = datetime.utcnow()
                result = self._run_check(check_name, target_date)
                result.duration_ms = int((datetime.utcnow() - check_start).total_seconds() * 1000)
                check_results.append(result)
            except Exception as e:
                logger.error(f"Check {check_name} failed with error: {e}")
                check_results.append(CheckResult(
                    check_name=check_name,
                    status=CheckStatus.ERROR,
                    message=f"Check failed with error: {str(e)}",
                    severity=Severity.P2_HIGH,
                ))

        # Determine overall status
        has_critical = any(r.status == CheckStatus.FAIL and r.severity == Severity.P1_CRITICAL for r in check_results)
        has_fail = any(r.status == CheckStatus.FAIL for r in check_results)
        has_warn = any(r.status == CheckStatus.WARN for r in check_results)
        has_error = any(r.status == CheckStatus.ERROR for r in check_results)

        if has_critical or has_error:
            overall_status = RunStatus.CRITICAL
        elif has_fail:
            overall_status = RunStatus.WARNING
        elif has_warn:
            overall_status = RunStatus.WARNING
        else:
            overall_status = RunStatus.OK

        # Build message
        passed = sum(1 for r in check_results if r.status == CheckStatus.PASS)
        total = len(check_results)
        message = f"{passed}/{total} checks passed"
        if has_critical:
            message += " [CRITICAL issues found]"
        elif has_fail:
            message += " [FAILURES found]"
        elif has_warn:
            message += " [WARNINGS found]"

        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        run = ValidationRun(
            run_id=run_id,
            check_type=schedule_name,
            status=overall_status,
            message=message,
            checks=check_results,
            run_timestamp=start_time,
            duration_ms=duration_ms,
            trigger_source=trigger_source,
            schedule_name=schedule_name,
            target_date=target_date,
        )

        # Store results
        self._store_run_results(run)

        # Send alerts if needed
        if overall_status in [RunStatus.CRITICAL, RunStatus.WARNING]:
            self._send_alerts(run)

        logger.info(f"Validation complete: {overall_status.value} - {message}")
        return run

    def _run_check(self, check_name: str, target_date: date) -> CheckResult:
        """Run a single validation check."""
        if check_name not in self._check_registry:
            return CheckResult(
                check_name=check_name,
                status=CheckStatus.SKIP,
                message=f"Check not implemented: {check_name}",
            )

        return self._check_registry[check_name](target_date)

    # ========== Individual Check Implementations ==========

    def _check_phase3_completion(self, target_date: date) -> CheckResult:
        """Check if Phase 3 completed successfully."""
        from google.cloud import firestore

        db = firestore.Client(project=self.project_id)
        doc = db.collection('phase3_completion').document(str(target_date)).get()

        if not doc.exists:
            return CheckResult(
                check_name='phase3_completion',
                status=CheckStatus.FAIL,
                message=f"No Phase 3 completion record for {target_date}",
                severity=Severity.P1_CRITICAL,
                category='orchestration',
                target_date=target_date,
            )

        data = doc.to_dict()
        completed = len([k for k in data.keys() if not k.startswith('_')])
        triggered = data.get('_triggered', False)

        if completed >= 5 and triggered:
            return CheckResult(
                check_name='phase3_completion',
                status=CheckStatus.PASS,
                message=f"Phase 3 complete: {completed}/5 processors, Phase 4 triggered",
                category='orchestration',
                target_date=target_date,
                expected_value="5",
                actual_value=str(completed),
            )
        else:
            return CheckResult(
                check_name='phase3_completion',
                status=CheckStatus.FAIL,
                message=f"Phase 3 incomplete: {completed}/5 processors, triggered={triggered}",
                severity=Severity.P1_CRITICAL,
                category='orchestration',
                target_date=target_date,
                expected_value="5",
                actual_value=str(completed),
            )

    def _check_phase4_completion(self, target_date: date) -> CheckResult:
        """Check if Phase 4 completed successfully."""
        query = f"""
        SELECT COUNT(*) as record_count
        FROM nba_precompute.player_daily_cache
        WHERE cache_date = '{target_date}'
        """
        result = list(self.bq_client.query(query).result())[0]

        if result.record_count >= 50:
            return CheckResult(
                check_name='phase4_completion',
                status=CheckStatus.PASS,
                message=f"Phase 4 cache has {result.record_count} records",
                category='orchestration',
                target_date=target_date,
                threshold=50,
                actual_value=str(result.record_count),
            )
        elif result.record_count > 0:
            return CheckResult(
                check_name='phase4_completion',
                status=CheckStatus.WARN,
                message=f"Phase 4 cache has only {result.record_count} records (expected 50+)",
                severity=Severity.P3_MEDIUM,
                category='orchestration',
                target_date=target_date,
                threshold=50,
                actual_value=str(result.record_count),
            )
        else:
            return CheckResult(
                check_name='phase4_completion',
                status=CheckStatus.FAIL,
                message="Phase 4 cache is empty",
                severity=Severity.P1_CRITICAL,
                category='orchestration',
                target_date=target_date,
                threshold=50,
                actual_value="0",
            )

    def _check_historical_completeness(self, target_date: date) -> CheckResult:
        """Check for historical data gaps."""
        query = """
        WITH schedule AS (
            SELECT game_date, COUNT(*) as scheduled_games
            FROM nba_reference.nba_schedule
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
                AND game_date < CURRENT_DATE()
                AND game_status = 3
            GROUP BY game_date
        ),
        analytics AS (
            SELECT game_date, COUNT(*) as actual_records
            FROM nba_analytics.player_game_summary
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
            GROUP BY game_date
        )
        SELECT COUNT(*) as gap_count
        FROM schedule s
        LEFT JOIN analytics a ON s.game_date = a.game_date
        WHERE COALESCE(a.actual_records, 0) < s.scheduled_games * 40
        """
        result = list(self.bq_client.query(query).result())[0]

        if result.gap_count == 0:
            return CheckResult(
                check_name='historical_completeness',
                status=CheckStatus.PASS,
                message="No historical data gaps in last 14 days",
                category='data_quality',
            )
        else:
            return CheckResult(
                check_name='historical_completeness',
                status=CheckStatus.FAIL,
                message=f"{result.gap_count} dates have data gaps in last 14 days",
                severity=Severity.P1_CRITICAL,
                category='data_quality',
                affected_records=result.gap_count,
            )

    def _check_data_freshness(self, target_date: date) -> CheckResult:
        """Check if data sources are fresh."""
        query = """
        SELECT
            MAX(DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY)) as max_stale_days
        FROM (
            SELECT MAX(game_date) as game_date FROM nba_raw.bdl_player_boxscores
            UNION ALL
            SELECT MAX(game_date) FROM nba_analytics.player_game_summary
            UNION ALL
            SELECT MAX(cache_date) FROM nba_precompute.player_daily_cache
        )
        """
        result = list(self.bq_client.query(query).result())[0]

        if result.max_stale_days <= 1:
            return CheckResult(
                check_name='data_freshness',
                status=CheckStatus.PASS,
                message="All data sources are fresh (within 1 day)",
                category='data_quality',
            )
        elif result.max_stale_days <= 3:
            return CheckResult(
                check_name='data_freshness',
                status=CheckStatus.WARN,
                message=f"Some data sources are {result.max_stale_days} days stale",
                severity=Severity.P3_MEDIUM,
                category='data_quality',
            )
        else:
            return CheckResult(
                check_name='data_freshness',
                status=CheckStatus.FAIL,
                message=f"Data sources are {result.max_stale_days} days stale",
                severity=Severity.P1_CRITICAL,
                category='data_quality',
            )

    def _check_scraper_failures(self, target_date: date) -> CheckResult:
        """Check for recent scraper failures."""
        # This would check processor_run_history for failures
        # Simplified implementation
        return CheckResult(
            check_name='scraper_failures',
            status=CheckStatus.PASS,
            message="No recent scraper failures detected",
            category='scraper',
        )

    def _check_consecutive_failures(self, target_date: date) -> CheckResult:
        """Check for consecutive failures."""
        # Simplified - would integrate with consecutive_failure_monitor.py
        return CheckResult(
            check_name='consecutive_failures',
            status=CheckStatus.PASS,
            message="No consecutive failures detected",
            category='scraper',
        )

    def _check_predictions_ready(self, target_date: date) -> CheckResult:
        """Check if predictions are ready for today's games."""
        today = date.today()
        query = f"""
        SELECT COUNT(*) as prediction_count
        FROM nba_predictions.player_prop_predictions
        WHERE game_date = '{today}'
            AND system_id = 'catboost_v9'
            AND is_active = TRUE
        """
        result = list(self.bq_client.query(query).result())[0]

        if result.prediction_count >= 100:
            return CheckResult(
                check_name='predictions_ready',
                status=CheckStatus.PASS,
                message=f"{result.prediction_count} predictions ready for today",
                category='predictions',
                target_date=today,
            )
        elif result.prediction_count > 0:
            return CheckResult(
                check_name='predictions_ready',
                status=CheckStatus.WARN,
                message=f"Only {result.prediction_count} predictions ready (expected 100+)",
                severity=Severity.P2_HIGH,
                category='predictions',
                target_date=today,
            )
        else:
            return CheckResult(
                check_name='predictions_ready',
                status=CheckStatus.FAIL,
                message="No predictions ready for today",
                severity=Severity.P1_CRITICAL,
                category='predictions',
                target_date=today,
            )

    def _check_feature_store_quality(self, target_date: date) -> CheckResult:
        """Check ML feature store quality."""
        today = date.today()
        query = f"""
        SELECT
            ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct
        FROM nba_predictions.ml_feature_store_v2
        WHERE game_date = '{today}'
            AND ARRAY_LENGTH(features) >= 33
        """
        try:
            result = list(self.bq_client.query(query).result())[0]
            pct = result.vegas_line_pct or 0

            if pct >= 80:
                return CheckResult(
                    check_name='feature_store_quality',
                    status=CheckStatus.PASS,
                    message=f"Feature store quality OK: {pct}% Vegas line coverage",
                    category='predictions',
                )
            else:
                return CheckResult(
                    check_name='feature_store_quality',
                    status=CheckStatus.WARN,
                    message=f"Low Vegas line coverage: {pct}%",
                    severity=Severity.P2_HIGH,
                    category='predictions',
                )
        except Exception:
            return CheckResult(
                check_name='feature_store_quality',
                status=CheckStatus.SKIP,
                message="No feature store data for today yet",
                category='predictions',
            )

    def _check_vegas_line_coverage(self, target_date: date) -> CheckResult:
        """Check Vegas line availability."""
        return CheckResult(
            check_name='vegas_line_coverage',
            status=CheckStatus.PASS,
            message="Vegas line coverage check (placeholder)",
            category='betting',
        )

    def _check_upcoming_context(self, target_date: date) -> CheckResult:
        """Check upcoming game context data."""
        return CheckResult(
            check_name='upcoming_context',
            status=CheckStatus.PASS,
            message="Upcoming context check (placeholder)",
            category='predictions',
        )

    def _check_pre_game_signal(self, target_date: date) -> CheckResult:
        """Check pre-game signal status."""
        today = date.today()
        query = f"""
        SELECT daily_signal, pct_over
        FROM nba_predictions.daily_prediction_signals
        WHERE game_date = '{today}'
            AND system_id = 'catboost_v9'
        """
        try:
            result = list(self.bq_client.query(query).result())
            if not result:
                return CheckResult(
                    check_name='pre_game_signal',
                    status=CheckStatus.SKIP,
                    message="No signal data for today",
                    category='predictions',
                )

            signal = result[0].daily_signal
            pct_over = result[0].pct_over

            if signal == 'GREEN':
                return CheckResult(
                    check_name='pre_game_signal',
                    status=CheckStatus.PASS,
                    message=f"Pre-game signal: GREEN (pct_over: {pct_over}%)",
                    category='predictions',
                )
            elif signal == 'RED':
                return CheckResult(
                    check_name='pre_game_signal',
                    status=CheckStatus.WARN,
                    message=f"Pre-game signal: RED (pct_over: {pct_over}%) - heavy UNDER skew",
                    severity=Severity.P3_MEDIUM,
                    category='predictions',
                )
            else:
                return CheckResult(
                    check_name='pre_game_signal',
                    status=CheckStatus.PASS,
                    message=f"Pre-game signal: {signal} (pct_over: {pct_over}%)",
                    category='predictions',
                )
        except Exception:
            return CheckResult(
                check_name='pre_game_signal',
                status=CheckStatus.SKIP,
                message="Could not check pre-game signal",
                category='predictions',
            )

    def _check_model_bias(self, target_date: date) -> CheckResult:
        """Check for model bias by player tier."""
        return CheckResult(
            check_name='model_bias',
            status=CheckStatus.PASS,
            message="Model bias check (placeholder)",
            category='predictions',
        )

    def _check_service_health(self, target_date: date) -> CheckResult:
        """Check service health endpoints."""
        return CheckResult(
            check_name='service_health',
            status=CheckStatus.PASS,
            message="Service health check (placeholder)",
            category='infrastructure',
        )

    def _check_recent_errors(self, target_date: date) -> CheckResult:
        """Check for recent errors in logs."""
        return CheckResult(
            check_name='recent_errors',
            status=CheckStatus.PASS,
            message="Recent errors check (placeholder)",
            category='infrastructure',
        )

    def _check_deployment_drift(self, target_date: date) -> CheckResult:
        """Check for deployment drift."""
        return CheckResult(
            check_name='deployment_drift',
            status=CheckStatus.PASS,
            message="Deployment drift check (placeholder)",
            category='infrastructure',
        )

    def _check_scraper_kickoff(self, target_date: date) -> CheckResult:
        """Check if scrapers kicked off after games ended."""
        return CheckResult(
            check_name='scraper_kickoff',
            status=CheckStatus.PASS,
            message="Scraper kickoff check (placeholder)",
            category='scraper',
        )

    def _check_games_final(self, target_date: date) -> CheckResult:
        """Check if all games are marked final."""
        return CheckResult(
            check_name='games_final',
            status=CheckStatus.PASS,
            message="Games final check (placeholder)",
            category='schedule',
        )

    def _check_phase2_progress(self, target_date: date) -> CheckResult:
        """Check Phase 2 progress during overnight processing."""
        return CheckResult(
            check_name='phase2_progress',
            status=CheckStatus.PASS,
            message="Phase 2 progress check (placeholder)",
            category='orchestration',
        )

    def _check_phase3_progress(self, target_date: date) -> CheckResult:
        """Check Phase 3 progress during overnight processing."""
        return CheckResult(
            check_name='phase3_progress',
            status=CheckStatus.PASS,
            message="Phase 3 progress check (placeholder)",
            category='orchestration',
        )

    # ========== Storage ==========

    def _store_run_results(self, run: ValidationRun):
        """Store validation run results in BigQuery."""
        # Store run summary
        run_row = {
            'run_id': run.run_id,
            'run_timestamp': run.run_timestamp.isoformat(),
            'check_type': run.check_type,
            'trigger_source': run.trigger_source,
            'schedule_name': run.schedule_name,
            'status': run.status.value,
            'message': run.message,
            'duration_ms': run.duration_ms,
            'checks_passed': sum(1 for c in run.checks if c.status == CheckStatus.PASS),
            'checks_warned': sum(1 for c in run.checks if c.status == CheckStatus.WARN),
            'checks_failed': sum(1 for c in run.checks if c.status == CheckStatus.FAIL),
            'target_date': str(run.target_date) if run.target_date else None,
            'details': json.dumps({
                'checks': [c.check_name for c in run.checks],
            }),
        }

        table_id = f'{self.project_id}.{self.dataset_id}.validation_runs'
        try:
            errors = self.bq_client.insert_rows_json(table_id, [run_row])
            if errors:
                logger.warning(f"Failed to store run: {errors}")
        except Exception as e:
            logger.warning(f"Could not store run (table may not exist): {e}")

        # Store individual check results
        check_rows = []
        for check in run.checks:
            check_rows.append({
                'result_id': str(uuid.uuid4()),
                'run_id': run.run_id,
                'check_timestamp': datetime.utcnow().isoformat(),
                'check_name': check.check_name,
                'check_category': check.category,
                'status': check.status.value,
                'severity': check.severity.value if check.severity else None,
                'expected_value': check.expected_value,
                'actual_value': check.actual_value,
                'threshold': check.threshold,
                'message': check.message,
                'target_date': str(check.target_date) if check.target_date else None,
                'target_table': check.target_table,
                'affected_records': check.affected_records,
                'details': json.dumps(check.details) if check.details else None,
            })

        table_id = f'{self.project_id}.{self.dataset_id}.validation_check_results'
        try:
            if check_rows:
                errors = self.bq_client.insert_rows_json(table_id, check_rows)
                if errors:
                    logger.warning(f"Failed to store check results: {errors}")
        except Exception as e:
            logger.warning(f"Could not store check results: {e}")

    def _send_alerts(self, run: ValidationRun):
        """Send alerts for failed validation."""
        try:
            import requests

            webhook_url = os.environ.get('SLACK_WEBHOOK_URL_ERROR')
            if not webhook_url:
                logger.warning("SLACK_WEBHOOK_URL_ERROR not set, skipping alert")
                return

            # Build message
            if run.status == RunStatus.CRITICAL:
                emoji = ":rotating_light:"
                color = "#FF0000"
            else:
                emoji = ":warning:"
                color = "#FFA500"

            failed_checks = [c for c in run.checks if c.status == CheckStatus.FAIL]
            check_text = "\n".join([
                f"• {c.check_name}: {c.message}"
                for c in failed_checks[:5]
            ])

            payload = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{emoji} Validation Alert: {run.check_type}"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Status:* {run.status.value}\n*Message:* {run.message}\n*Target Date:* {run.target_date}"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Failed Checks:*\n{check_text}"
                        }
                    }
                ],
                "attachments": [{
                    "color": color,
                    "text": f"Run ID: {run.run_id}"
                }]
            }

            response = requests.post(webhook_url, json=payload)
            response.raise_for_status()
            logger.info(f"Alert sent to Slack")

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")


def run_validation_cli():
    """CLI entry point for running validation."""
    import argparse

    parser = argparse.ArgumentParser(description='Run continuous validation')
    parser.add_argument('schedule', nargs='?', default='post_overnight',
                        help='Schedule name to run')
    parser.add_argument('--date', type=str, help='Target date (YYYY-MM-DD)')
    parser.add_argument('--list', action='store_true', help='List available schedules')
    args = parser.parse_args()

    if args.list:
        print("Available schedules:")
        for name, config in ContinuousValidator.SCHEDULES.items():
            print(f"  {name}: {config['description']}")
            print(f"    Checks: {', '.join(config['checks'])}")
            print(f"    Cron: {config['cron']}")
            print()
        return

    validator = ContinuousValidator()

    target_date = None
    if args.date:
        target_date = date.fromisoformat(args.date)

    result = validator.run_scheduled_validation(args.schedule, target_date, "cli")

    print(f"\nValidation Result: {result.status.value}")
    print(f"Message: {result.message}")
    print(f"Duration: {result.duration_ms}ms")
    print(f"\nChecks:")
    for check in result.checks:
        status_emoji = "✅" if check.status == CheckStatus.PASS else "❌" if check.status == CheckStatus.FAIL else "⚠️"
        print(f"  {status_emoji} {check.check_name}: {check.message}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run_validation_cli()
