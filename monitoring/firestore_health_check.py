#!/usr/bin/env python3
"""
Firestore Health Check for Pipeline Orchestration.

Monitors the health of Firestore, which is a critical dependency for all
phase orchestrators (Phase 3→4→5→6). If Firestore goes down, the entire
pipeline halts with no fallback.

Checks:
1. Firestore connectivity (can read/write test document)
2. Stuck processors (running state > 30 minutes)
3. Phase completion staleness (phases not completing)
4. Write latency (detect slowdowns before outages)

Usage:
    # Run health check locally
    python monitoring/firestore_health_check.py

    # Output as JSON
    python monitoring/firestore_health_check.py --json

    # Run as Cloud Function (triggered by scheduler)
    gcloud scheduler jobs run firestore-health-check --location us-west2

Created: 2025-12-30
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
ALERT_TOPIC = 'nba-infrastructure-alerts'


class FirestoreHealthMonitor:
    """
    Monitor Firestore health and detect issues before they impact the pipeline.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self._db = None
        self._publisher = None

    @property
    def db(self):
        """Lazy-load Firestore client."""
        if self._db is None:
            from google.cloud import firestore
            self._db = firestore.Client(project=self.project_id)
        return self._db

    @property
    def publisher(self):
        """Lazy-load Pub/Sub publisher."""
        if self._publisher is None:
            from google.cloud import pubsub_v1
            self._publisher = pubsub_v1.PublisherClient()
        return self._publisher

    def check_connectivity(self) -> Dict:
        """
        Check basic Firestore connectivity by reading and writing a test document.

        This is the most critical check - if this fails, orchestrators will fail.

        Returns:
            Dict with status and latency metrics
        """
        try:
            # Test read/write to a health check document
            test_doc_ref = self.db.collection('_health_check').document('connectivity')

            # Write test
            write_start = time.time()
            test_doc_ref.set({
                'last_check': datetime.now(timezone.utc),
                'check_type': 'connectivity',
                'project_id': self.project_id
            })
            write_latency_ms = (time.time() - write_start) * 1000

            # Read test
            read_start = time.time()
            doc = test_doc_ref.get()
            read_latency_ms = (time.time() - read_start) * 1000

            if not doc.exists:
                return {
                    'status': 'CRITICAL',
                    'error': 'Write succeeded but read returned empty',
                    'write_latency_ms': round(write_latency_ms, 1),
                    'read_latency_ms': round(read_latency_ms, 1)
                }

            # Check latency thresholds
            total_latency = write_latency_ms + read_latency_ms
            if total_latency > 5000:  # 5 seconds total is very slow
                status = 'WARNING'
            elif total_latency > 1000:  # 1 second is concerning
                status = 'OK'  # But log it
                logger.info(f"Firestore latency elevated: {total_latency:.0f}ms")
            else:
                status = 'OK'

            return {
                'status': status,
                'write_latency_ms': round(write_latency_ms, 1),
                'read_latency_ms': round(read_latency_ms, 1),
                'total_latency_ms': round(total_latency, 1)
            }

        except Exception as e:
            logger.error(f"Firestore connectivity check FAILED: {e}")
            return {
                'status': 'CRITICAL',
                'error': str(e),
                'error_type': type(e).__name__
            }

    def check_stuck_processors(self, stuck_threshold_minutes: int = 30) -> Dict:
        """
        Check for processors stuck in 'running' state.

        Processors stuck for too long indicate either:
        1. The processor crashed without updating Firestore
        2. Firestore is having issues
        3. A legitimate long-running operation

        Args:
            stuck_threshold_minutes: Minutes after which running = stuck

        Returns:
            Dict with stuck processor details
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=stuck_threshold_minutes)

            # Query run_history for stuck entries
            stuck_query = (
                self.db.collection('run_history')
                .where('status', '==', 'running')
                .stream()
            )

            stuck_processors = []
            for doc in stuck_query:
                data = doc.to_dict()
                started_at = data.get('started_at')

                # Check if started_at is a timestamp we can compare
                if started_at is None:
                    continue

                # Convert to datetime if needed
                if hasattr(started_at, 'timestamp'):
                    started_dt = datetime.fromtimestamp(started_at.timestamp(), tz=timezone.utc)
                else:
                    started_dt = started_at

                if started_dt < cutoff:
                    minutes_stuck = (datetime.now(timezone.utc) - started_dt).total_seconds() / 60
                    stuck_processors.append({
                        'doc_id': doc.id,
                        'processor_name': data.get('processor_name', 'unknown'),
                        'started_at': started_dt.isoformat(),
                        'minutes_stuck': round(minutes_stuck, 1),
                        'game_date': data.get('game_date')
                    })

            if len(stuck_processors) > 5:
                status = 'CRITICAL'  # Many stuck processors = systemic issue
            elif len(stuck_processors) > 0:
                status = 'WARNING'
            else:
                status = 'OK'

            return {
                'status': status,
                'stuck_count': len(stuck_processors),
                'threshold_minutes': stuck_threshold_minutes,
                'stuck_processors': stuck_processors[:10]  # Limit to first 10
            }

        except Exception as e:
            logger.error(f"Error checking stuck processors: {e}")
            return {
                'status': 'ERROR',
                'error': str(e)
            }

    def check_phase_completion_freshness(self, max_hours_stale: int = 24) -> Dict:
        """
        Check if phase completion documents are being updated.

        If phase3_completion or phase4_completion haven't been updated recently
        when games were played, it may indicate orchestration issues.

        Args:
            max_hours_stale: Hours after which lack of updates is concerning

        Returns:
            Dict with phase completion freshness
        """
        try:
            results = {}

            # Check today and yesterday's documents (no index required)
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
            dates_to_check = [today, yesterday]

            for phase in ['phase3_completion', 'phase4_completion', 'phase5_completion']:
                # Check recent dates directly (no ordering = no index needed)
                most_recent = None
                for date_str in dates_to_check:
                    doc = self.db.collection(phase).document(date_str).get()
                    if doc.exists:
                        most_recent = (date_str, doc.to_dict())
                        break

                if not most_recent:
                    results[phase] = {
                        'status': 'WARNING',
                        'message': 'No completion documents found for today/yesterday',
                        'most_recent': None
                    }
                    continue

                doc_date, data = most_recent

                # Check if triggered recently
                triggered_at = data.get('_triggered_at')
                if triggered_at:
                    if hasattr(triggered_at, 'timestamp'):
                        triggered_dt = datetime.fromtimestamp(triggered_at.timestamp(), tz=timezone.utc)
                    else:
                        triggered_dt = triggered_at

                    hours_ago = (datetime.now(timezone.utc) - triggered_dt).total_seconds() / 3600

                    results[phase] = {
                        'status': 'OK' if hours_ago < max_hours_stale else 'WARNING',
                        'most_recent_date': doc_date,
                        'triggered_at': triggered_dt.isoformat(),
                        'hours_ago': round(hours_ago, 1),
                        'completed_count': data.get('_completed_count', 0)
                    }
                else:
                    results[phase] = {
                        'status': 'WARNING',
                        'most_recent_date': doc_date,
                        'message': 'Document exists but not triggered',
                        'completed_count': data.get('_completed_count', 0)
                    }

            # Determine overall status
            statuses = [r['status'] for r in results.values()]
            if 'CRITICAL' in statuses:
                overall = 'CRITICAL'
            elif 'WARNING' in statuses:
                overall = 'WARNING'
            else:
                overall = 'OK'

            return {
                'status': overall,
                'max_hours_stale': max_hours_stale,
                'phases': results
            }

        except Exception as e:
            logger.error(f"Error checking phase freshness: {e}")
            return {
                'status': 'ERROR',
                'error': str(e)
            }

    def run_full_health_check(self) -> Dict:
        """
        Run all health checks and return comprehensive results.

        Returns:
            Dict with all health check results
        """
        logger.info("Running Firestore health check...")
        start_time = time.time()

        results = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'project_id': self.project_id,
            'checks': {
                'connectivity': self.check_connectivity(),
                'stuck_processors': self.check_stuck_processors(),
                'phase_freshness': self.check_phase_completion_freshness()
            }
        }

        # Calculate overall status
        statuses = [
            results['checks']['connectivity']['status'],
            results['checks']['stuck_processors']['status'],
            results['checks']['phase_freshness']['status']
        ]

        if 'CRITICAL' in statuses:
            results['overall_status'] = 'CRITICAL'
        elif 'ERROR' in statuses:
            results['overall_status'] = 'ERROR'
        elif 'WARNING' in statuses:
            results['overall_status'] = 'WARNING'
        else:
            results['overall_status'] = 'OK'

        results['duration_seconds'] = round(time.time() - start_time, 2)

        # Publish alert if not healthy
        if results['overall_status'] in ('CRITICAL', 'ERROR'):
            self._publish_alert(results)

        return results

    def _publish_alert(self, health_results: Dict) -> Optional[str]:
        """
        Publish alert to Pub/Sub for critical/error status.

        Note: Alert publishing is optional - if topic doesn't exist, we just log.
        Create the topic with:
            gcloud pubsub topics create nba-infrastructure-alerts

        Args:
            health_results: Full health check results

        Returns:
            Message ID if published, None if failed or topic doesn't exist
        """
        try:
            # First check if the topic exists
            from google.cloud import pubsub_v1
            from google.api_core import exceptions

            topic_path = self.publisher.topic_path(self.project_id, ALERT_TOPIC)

            alert_message = {
                'alert_type': 'firestore_health',
                'severity': health_results['overall_status'],
                'timestamp': health_results['timestamp'],
                'summary': self._generate_alert_summary(health_results),
                'details': health_results
            }

            future = self.publisher.publish(
                topic_path,
                data=json.dumps(alert_message).encode('utf-8')
            )
            message_id = future.result(timeout=10.0)

            logger.warning(f"Published Firestore health alert: {message_id}")
            return message_id

        except Exception as e:
            # Don't log as error if topic just doesn't exist
            if 'not found' in str(e).lower() or '404' in str(e):
                logger.debug(f"Alert topic not configured (optional): {e}")
            else:
                logger.error(f"Failed to publish health alert: {e}")
            return None

    def _generate_alert_summary(self, results: Dict) -> str:
        """Generate a human-readable alert summary."""
        issues = []

        conn = results['checks'].get('connectivity', {})
        if conn.get('status') in ('CRITICAL', 'ERROR'):
            issues.append(f"Firestore connectivity FAILED: {conn.get('error', 'unknown')}")

        stuck = results['checks'].get('stuck_processors', {})
        if stuck.get('stuck_count', 0) > 0:
            issues.append(f"{stuck['stuck_count']} processors stuck in running state")

        freshness = results['checks'].get('phase_freshness', {})
        if freshness.get('status') in ('CRITICAL', 'WARNING'):
            stale_phases = [
                p for p, d in freshness.get('phases', {}).items()
                if d.get('status') != 'OK'
            ]
            if stale_phases:
                issues.append(f"Stale phase completions: {', '.join(stale_phases)}")

        return '; '.join(issues) if issues else 'Unknown issue'

    def print_report(self, results: Dict):
        """Print human-readable health report."""
        print("\n" + "=" * 70)
        print("FIRESTORE HEALTH CHECK")
        print("=" * 70)
        print(f"Timestamp: {results['timestamp']}")
        print(f"Project: {results['project_id']}")
        print(f"Duration: {results['duration_seconds']}s")
        print(f"Overall Status: {results['overall_status']}")
        print()

        # Connectivity
        conn = results['checks']['connectivity']
        print(f"[{conn['status']}] Connectivity")
        if conn['status'] == 'OK' or conn['status'] == 'WARNING':
            print(f"  - Write latency: {conn.get('write_latency_ms', 'N/A')}ms")
            print(f"  - Read latency: {conn.get('read_latency_ms', 'N/A')}ms")
            print(f"  - Total latency: {conn.get('total_latency_ms', 'N/A')}ms")
        else:
            print(f"  - Error: {conn.get('error', 'Unknown')}")
        print()

        # Stuck Processors
        stuck = results['checks']['stuck_processors']
        print(f"[{stuck['status']}] Stuck Processors")
        print(f"  - Count: {stuck.get('stuck_count', 0)}")
        print(f"  - Threshold: {stuck.get('threshold_minutes', 30)} minutes")
        if stuck.get('stuck_processors'):
            print("  - Examples:")
            for p in stuck['stuck_processors'][:3]:
                print(f"    - {p['processor_name']}: {p['minutes_stuck']}min (date: {p.get('game_date', 'N/A')})")
        print()

        # Phase Freshness
        freshness = results['checks']['phase_freshness']
        print(f"[{freshness['status']}] Phase Completion Freshness")
        for phase, data in freshness.get('phases', {}).items():
            status_icon = '✓' if data['status'] == 'OK' else '⚠'
            if 'most_recent_date' in data:
                print(f"  {status_icon} {phase}: {data['most_recent_date']} ({data.get('hours_ago', 'N/A')}h ago)")
            else:
                print(f"  {status_icon} {phase}: {data.get('message', 'No data')}")
        print()

        print("=" * 70)

        # Recommendations
        if results['overall_status'] != 'OK':
            print("\nRECOMMENDATIONS:")
            if conn['status'] != 'OK':
                print("  - CRITICAL: Check GCP console for Firestore service status")
                print("  - Verify network connectivity and IAM permissions")
            if stuck.get('stuck_count', 0) > 0:
                print("  - Clear stuck run_history entries:")
                print("    curl https://self-heal-f7p3g7f6ya-wl.a.run.app")
            print()


def main():
    parser = argparse.ArgumentParser(
        description="Check Firestore health for pipeline orchestration"
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON instead of human-readable report'
    )

    args = parser.parse_args()

    monitor = FirestoreHealthMonitor()
    results = monitor.run_full_health_check()

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        monitor.print_report(results)

    # Exit with appropriate code
    if results['overall_status'] == 'CRITICAL':
        sys.exit(2)
    elif results['overall_status'] in ('WARNING', 'ERROR'):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
