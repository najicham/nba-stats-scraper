#!/usr/bin/env python3
"""
NBA Retry Storm Detector

Monitors processor execution patterns and alerts on potential retry storms.

CRITICAL THRESHOLDS:
- Processor runs >50/hour: WARNING
- Processor runs >200/hour: CRITICAL
- System health <50%: CRITICAL
- Circuit breaker open: WARNING

Usage:
    # Run manually
    python monitoring/nba/retry_storm_detector.py

    # Deploy as Cloud Run job (hourly)
    gcloud run jobs create nba-retry-storm-detector \
        --source=. \
        --region=us-west2 \
        --execute-now
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List
from google.cloud import bigquery
from shared.utils.notification_system import notify_error, notify_warning, notify_info

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Thresholds
RUNS_PER_HOUR_WARNING = 50
RUNS_PER_HOUR_CRITICAL = 200
SYSTEM_HEALTH_CRITICAL = 50  # %
FAILURE_RATE_WARNING = 30  # %
FAILURE_RATE_CRITICAL = 70  # %


class RetryStormDetector:
    """Detects retry storm patterns in processor execution logs."""

    def __init__(self, project_id: str = "nba-props-platform"):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

    def check_processor_rates(self, lookback_hours: int = 1) -> Dict:
        """
        Check processor execution rates for retry storm patterns.

        Args:
            lookback_hours: How many hours to look back

        Returns:
            Dict with processor statistics and alerts
        """
        query = f"""
        SELECT
            processor_name,
            COUNT(*) as total_runs,
            COUNTIF(status = 'failed') as failures,
            COUNTIF(status = 'success') as successes,
            ROUND(100.0 * COUNTIF(status = 'failed') / COUNT(*), 1) as failure_pct,
            MIN(started_at) as first_run,
            MAX(started_at) as last_run
        FROM nba_reference.processor_run_history
        WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_hours} HOUR)
        GROUP BY processor_name
        HAVING total_runs > 10  -- Only show active processors
        ORDER BY total_runs DESC
        """

        results = []
        alerts = []

        try:
            query_job = self.bq_client.query(query)
            rows = list(query_job.result())

            for row in rows:
                processor_stats = {
                    'processor_name': row.processor_name,
                    'total_runs': row.total_runs,
                    'failures': row.failures,
                    'successes': row.successes,
                    'failure_pct': row.failure_pct,
                    'first_run': row.first_run,
                    'last_run': row.last_run
                }
                results.append(processor_stats)

                # Check thresholds
                if row.total_runs >= RUNS_PER_HOUR_CRITICAL:
                    alerts.append({
                        'severity': 'critical',
                        'processor': row.processor_name,
                        'message': f"CRITICAL: {row.processor_name} has {row.total_runs} runs in {lookback_hours}h (>{RUNS_PER_HOUR_CRITICAL}/h threshold)",
                        'runs': row.total_runs,
                        'failure_pct': row.failure_pct
                    })
                elif row.total_runs >= RUNS_PER_HOUR_WARNING:
                    alerts.append({
                        'severity': 'warning',
                        'processor': row.processor_name,
                        'message': f"WARNING: {row.processor_name} has {row.total_runs} runs in {lookback_hours}h (>{RUNS_PER_HOUR_WARNING}/h threshold)",
                        'runs': row.total_runs,
                        'failure_pct': row.failure_pct
                    })

                # Check failure rate
                if row.failure_pct >= FAILURE_RATE_CRITICAL:
                    alerts.append({
                        'severity': 'critical',
                        'processor': row.processor_name,
                        'message': f"CRITICAL: {row.processor_name} failure rate {row.failure_pct}% (>{FAILURE_RATE_CRITICAL}% threshold)",
                        'runs': row.total_runs,
                        'failure_pct': row.failure_pct
                    })
                elif row.failure_pct >= FAILURE_RATE_WARNING:
                    alerts.append({
                        'severity': 'warning',
                        'processor': row.processor_name,
                        'message': f"WARNING: {row.processor_name} failure rate {row.failure_pct}% (>{FAILURE_RATE_WARNING}% threshold)",
                        'runs': row.total_runs,
                        'failure_pct': row.failure_pct
                    })

        except Exception as e:
            logger.error(f"Failed to check processor rates: {e}")
            return {'error': str(e), 'results': [], 'alerts': []}

        return {
            'results': results,
            'alerts': alerts,
            'lookback_hours': lookback_hours
        }

    def check_system_health(self, lookback_hours: int = 1) -> Dict:
        """
        Check overall system health.

        Returns:
            Dict with system health metrics
        """
        query = f"""
        SELECT
            COUNT(*) as total_runs,
            COUNTIF(status = 'success') as successes,
            COUNTIF(status = 'failed') as failures,
            COUNTIF(status = 'running') as still_running,
            ROUND(100.0 * COUNTIF(status = 'success') / COUNT(*), 1) as success_pct
        FROM nba_reference.processor_run_history
        WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_hours} HOUR)
        """

        try:
            query_job = self.bq_client.query(query)
            rows = list(query_job.result())

            if not rows:
                return {'error': 'No data', 'healthy': True}

            row = rows[0]
            health = {
                'total_runs': row.total_runs,
                'successes': row.successes,
                'failures': row.failures,
                'still_running': row.still_running,
                'success_pct': row.success_pct,
                'healthy': row.success_pct >= SYSTEM_HEALTH_CRITICAL
            }

            # Alert if unhealthy
            if not health['healthy']:
                logger.critical(
                    f"SYSTEM HEALTH CRITICAL: {row.success_pct}% success rate "
                    f"(threshold: {SYSTEM_HEALTH_CRITICAL}%)"
                )

            return health

        except Exception as e:
            logger.error(f"Failed to check system health: {e}")
            return {'error': str(e), 'healthy': True}

    def check_circuit_breakers(self) -> Dict:
        """
        Check circuit breaker states.

        Returns:
            Dict with circuit breaker status
        """
        query = """
        SELECT
            processor_name,
            state,
            failure_count,
            updated_at,
            last_error_message
        FROM nba_orchestration.circuit_breaker_state
        WHERE state = 'OPEN'
          AND updated_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
        ORDER BY updated_at DESC
        """

        try:
            query_job = self.bq_client.query(query)
            rows = list(query_job.result())

            open_circuits = []
            for row in rows:
                open_circuits.append({
                    'processor_name': row.processor_name,
                    'state': row.state,
                    'failure_count': row.failure_count,
                    'updated_at': row.updated_at,
                    'last_error': row.last_error_message[:200] if row.last_error_message else None
                })

            if open_circuits:
                logger.warning(f"Found {len(open_circuits)} open circuit breakers")

            return {
                'open_circuits': open_circuits,
                'count': len(open_circuits)
            }

        except Exception as e:
            logger.error(f"Failed to check circuit breakers: {e}")
            return {'error': str(e), 'open_circuits': [], 'count': 0}

    def run_checks(self) -> Dict:
        """
        Run all checks and aggregate results.

        Returns:
            Dict with all check results and summary
        """
        logger.info("Running retry storm detection checks...")

        # Run checks
        processor_check = self.check_processor_rates(lookback_hours=1)
        system_health = self.check_system_health(lookback_hours=1)
        circuit_breakers = self.check_circuit_breakers()

        # Aggregate alerts
        all_alerts = processor_check.get('alerts', [])

        # Add system health alert if needed
        if not system_health.get('healthy', True):
            all_alerts.append({
                'severity': 'critical',
                'processor': 'SYSTEM',
                'message': f"SYSTEM HEALTH CRITICAL: {system_health.get('success_pct', 0)}% success rate",
                'success_pct': system_health.get('success_pct', 0)
            })

        # Add circuit breaker alerts
        if circuit_breakers.get('count', 0) > 0:
            for circuit in circuit_breakers['open_circuits']:
                all_alerts.append({
                    'severity': 'warning',
                    'processor': circuit['processor_name'],
                    'message': f"Circuit breaker OPEN for {circuit['processor_name']} ({circuit['failure_count']} failures)",
                    'failure_count': circuit['failure_count']
                })

        # Send notifications
        self._send_alerts(all_alerts)

        # Summary
        summary = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'system_health': system_health,
            'processor_check': processor_check,
            'circuit_breakers': circuit_breakers,
            'total_alerts': len(all_alerts),
            'critical_alerts': len([a for a in all_alerts if a['severity'] == 'critical']),
            'warning_alerts': len([a for a in all_alerts if a['severity'] == 'warning'])
        }

        logger.info(f"Check complete: {summary['total_alerts']} alerts ({summary['critical_alerts']} critical)")

        return summary

    def _send_alerts(self, alerts: List[Dict]):
        """Send alerts via notification system."""
        for alert in alerts:
            severity = alert['severity']
            message = alert['message']

            if severity == 'critical':
                notify_error(
                    title="NBA Retry Storm Alert - CRITICAL",
                    message=message,
                    context=alert
                )
            elif severity == 'warning':
                notify_warning(
                    title="NBA Retry Storm Alert - WARNING",
                    message=message,
                    context=alert
                )


def main():
    """Run retry storm detection."""
    detector = RetryStormDetector()
    results = detector.run_checks()

    # Print summary
    print("\n" + "=" * 80)
    print("RETRY STORM DETECTION SUMMARY")
    print("=" * 80)
    print(f"Timestamp: {results['timestamp']}")
    print(f"\nSystem Health: {results['system_health']['success_pct']}% success rate")
    print(f"Total Alerts: {results['total_alerts']} ({results['critical_alerts']} critical, {results['warning_alerts']} warning)")

    if results['processor_check']['alerts']:
        print("\nProcessor Alerts:")
        for alert in results['processor_check']['alerts']:
            print(f"  [{alert['severity'].upper()}] {alert['message']}")

    if results['circuit_breakers']['open_circuits']:
        print(f"\nOpen Circuit Breakers: {results['circuit_breakers']['count']}")
        for circuit in results['circuit_breakers']['open_circuits']:
            print(f"  - {circuit['processor_name']}: {circuit['failure_count']} failures")

    if results['total_alerts'] == 0:
        print("\n✅ No alerts - system healthy")

    print("=" * 80)

    return 0 if results['total_alerts'] == 0 else 1


if __name__ == '__main__':
    exit(main())
