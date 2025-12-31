#!/usr/bin/env python3
"""
Pipeline Replay - Replay the NBA stats pipeline for a historical date.

This script runs the complete pipeline (Phases 2-6) against any historical date,
writing to test datasets to avoid affecting production.

Usage:
    # Replay yesterday's data
    python bin/testing/replay_pipeline.py

    # Replay specific date
    python bin/testing/replay_pipeline.py 2024-12-15

    # Replay with custom dataset prefix
    DATASET_PREFIX=dev_ python bin/testing/replay_pipeline.py 2024-12-15

    # Dry run (show what would happen)
    python bin/testing/replay_pipeline.py 2024-12-15 --dry-run

    # Skip specific phases
    python bin/testing/replay_pipeline.py 2024-12-15 --skip-phase=2,6

    # Start from specific phase
    python bin/testing/replay_pipeline.py 2024-12-15 --start-phase=4

Environment Variables:
    DATASET_PREFIX: Prefix for test datasets (default: test_)
    GCS_PREFIX: Prefix for GCS paths (default: test/)
    FIRESTORE_PREFIX: Prefix for Firestore collections (default: test_)

Created: 2025-12-31
Part of Pipeline Replay System
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from google.cloud import bigquery
    import requests
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip install google-cloud-bigquery requests")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Cloud Run service URLs
SERVICE_URLS = {
    'phase2_raw': os.environ.get(
        'PHASE2_URL',
        'https://nba-phase2-raw-processors-756957797294.us-west2.run.app'
    ),
    'phase3_analytics': os.environ.get(
        'PHASE3_URL',
        'https://nba-phase3-analytics-processors-756957797294.us-west2.run.app'
    ),
    'phase4_precompute': os.environ.get(
        'PHASE4_URL',
        'https://nba-phase4-precompute-processors-756957797294.us-west2.run.app'
    ),
    'phase5_predictions': os.environ.get(
        'PHASE5_URL',
        'https://prediction-coordinator-756957797294.us-west2.run.app'
    ),
    'phase6_export': os.environ.get(
        'PHASE6_URL',
        'https://phase6-export-756957797294.us-west2.run.app'
    ),
}

# Performance thresholds (seconds)
PHASE_THRESHOLDS = {
    'phase2': {'warn': 300, 'critical': 600},
    'phase3': {'warn': 600, 'critical': 1200},
    'phase4': {'warn': 600, 'critical': 1200},
    'phase5': {'warn': 900, 'critical': 1800},
    'phase6': {'warn': 300, 'critical': 600},
}


@dataclass
class PhaseResult:
    """Result of running a single phase."""
    phase: str
    success: bool
    duration_seconds: float
    records_processed: int = 0
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class ReplayReport:
    """Complete replay report."""
    replay_date: str
    dataset_prefix: str
    start_time: datetime
    end_time: Optional[datetime] = None
    phases: List[PhaseResult] = field(default_factory=list)
    overall_success: bool = True

    @property
    def total_duration(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return sum(p.duration_seconds for p in self.phases)

    def to_dict(self) -> Dict:
        return {
            'replay_date': self.replay_date,
            'dataset_prefix': self.dataset_prefix,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'total_duration_seconds': self.total_duration,
            'overall_success': self.overall_success,
            'phases': [
                {
                    'phase': p.phase,
                    'success': p.success,
                    'duration_seconds': p.duration_seconds,
                    'records_processed': p.records_processed,
                    'error': p.error,
                    'warnings': p.warnings,
                }
                for p in self.phases
            ]
        }


class PipelineReplay:
    """Orchestrates pipeline replay for a given date."""

    def __init__(
        self,
        replay_date: str,
        dataset_prefix: str = 'test_',
        gcs_prefix: str = 'test/',
        dry_run: bool = False,
        skip_phases: Optional[List[int]] = None,
        start_phase: int = 2,
    ):
        self.replay_date = replay_date
        self.dataset_prefix = dataset_prefix
        self.gcs_prefix = gcs_prefix
        self.dry_run = dry_run
        self.skip_phases = skip_phases or []
        self.start_phase = start_phase

        self.bq_client = bigquery.Client()
        self.report = ReplayReport(
            replay_date=replay_date,
            dataset_prefix=dataset_prefix,
            start_time=datetime.now()
        )

        # Set environment for processors
        os.environ['DATASET_PREFIX'] = dataset_prefix
        os.environ['GCS_PREFIX'] = gcs_prefix

    def get_auth_token(self, audience: str) -> str:
        """Get identity token for Cloud Run service."""
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token

            auth_req = google.auth.transport.requests.Request()
            return google.oauth2.id_token.fetch_id_token(auth_req, audience)
        except Exception as e:
            logger.warning(f"Could not get ID token: {e}")
            return ""

    def run_phase(
        self,
        phase_num: int,
        phase_name: str,
        run_func,
    ) -> PhaseResult:
        """Run a single phase with timing and error handling."""
        if phase_num in self.skip_phases:
            logger.info(f"⏭️  Skipping Phase {phase_num}: {phase_name}")
            return PhaseResult(
                phase=f"phase{phase_num}",
                success=True,
                duration_seconds=0,
                warnings=['Skipped by user request']
            )

        if phase_num < self.start_phase:
            logger.info(f"⏭️  Skipping Phase {phase_num}: {phase_name} (before start_phase)")
            return PhaseResult(
                phase=f"phase{phase_num}",
                success=True,
                duration_seconds=0,
                warnings=['Skipped - before start_phase']
            )

        logger.info(f"\n▶️  Phase {phase_num}: {phase_name}")
        logger.info("=" * 50)

        start_time = time.time()
        warnings = []

        try:
            if self.dry_run:
                logger.info(f"   [DRY RUN] Would execute Phase {phase_num}")
                result = PhaseResult(
                    phase=f"phase{phase_num}",
                    success=True,
                    duration_seconds=0,
                    warnings=['Dry run - not executed']
                )
            else:
                records = run_func()
                duration = time.time() - start_time

                # Check thresholds
                threshold = PHASE_THRESHOLDS.get(f'phase{phase_num}', {})
                if duration > threshold.get('critical', float('inf')):
                    warnings.append(f'CRITICAL: Duration {duration:.0f}s exceeds threshold')
                elif duration > threshold.get('warn', float('inf')):
                    warnings.append(f'WARNING: Duration {duration:.0f}s is high')

                result = PhaseResult(
                    phase=f"phase{phase_num}",
                    success=True,
                    duration_seconds=duration,
                    records_processed=records,
                    warnings=warnings
                )

            logger.info(f"✅ Phase {phase_num} complete: {result.duration_seconds:.1f}s")

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"❌ Phase {phase_num} failed: {e}")
            result = PhaseResult(
                phase=f"phase{phase_num}",
                success=False,
                duration_seconds=duration,
                error=str(e)
            )

        self.report.phases.append(result)
        return result

    def run_phase2_raw(self) -> int:
        """
        Run Phase 2: Raw data processing.

        For replay, we trigger reprocessing of existing GCS files for the date.
        This requires the GCS files to already exist from production scraping.
        """
        logger.info(f"Processing raw data for {self.replay_date}")

        # Note: Phase 2 is typically triggered by GCS file uploads.
        # For replay, we would need to either:
        # 1. List GCS files for the date and trigger processing
        # 2. Or skip if raw data already exists in test datasets

        # For now, log a warning - Phase 2 replay needs production GCS data
        logger.warning(
            "Phase 2 replay requires production GCS files to exist. "
            "If replaying a historical date, ensure scrapers ran on that date."
        )

        # Check if source tables have data
        query = f"""
        SELECT COUNT(*) as count
        FROM `{self.dataset_prefix}nba_source.bdl_player_boxscores`
        WHERE game_date = '{self.replay_date}'
        """
        try:
            result = self.bq_client.query(query).result()
            row = list(result)[0]
            logger.info(f"Found {row.count} raw boxscore records")
            return row.count
        except Exception as e:
            # Table may not exist in test dataset - that's okay for first run
            logger.info("No existing raw data found in test dataset")
            return 0

    def run_phase3_analytics(self) -> int:
        """Run Phase 3: Analytics processing via HTTP endpoint."""
        url = f"{SERVICE_URLS['phase3_analytics']}/process-date-range"
        token = self.get_auth_token(SERVICE_URLS['phase3_analytics'])

        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        payload = {
            'start_date': self.replay_date,
            'end_date': self.replay_date,
            'processors': [],  # Empty = all processors
            'backfill_mode': True,
            'dataset_prefix': self.dataset_prefix,
        }

        logger.info(f"Calling {url}")
        response = requests.post(url, json=payload, headers=headers, timeout=600)

        if response.status_code != 200:
            raise Exception(f"Phase 3 failed: {response.status_code} - {response.text[:500]}")

        result = response.json()
        records = result.get('total_records', 0)
        logger.info(f"Phase 3 processed {records} records")
        return records

    def run_phase4_precompute(self) -> int:
        """Run Phase 4: Precompute processing via HTTP endpoint."""
        url = f"{SERVICE_URLS['phase4_precompute']}/process-date"
        token = self.get_auth_token(SERVICE_URLS['phase4_precompute'])

        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        payload = {
            'analysis_date': self.replay_date,
            'processors': [],  # Empty = all processors
            'backfill_mode': True,
            'strict_mode': False,
            'skip_dependency_check': True,
            'dataset_prefix': self.dataset_prefix,
        }

        logger.info(f"Calling {url}")
        response = requests.post(url, json=payload, headers=headers, timeout=600)

        if response.status_code != 200:
            raise Exception(f"Phase 4 failed: {response.status_code} - {response.text[:500]}")

        result = response.json()
        records = result.get('total_records', 0)
        logger.info(f"Phase 4 processed {records} records")
        return records

    def run_phase5_predictions(self) -> int:
        """Run Phase 5: Generate predictions via coordinator."""
        url = f"{SERVICE_URLS['phase5_predictions']}/start"
        token = self.get_auth_token(SERVICE_URLS['phase5_predictions'])

        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        payload = {
            'game_date': self.replay_date,
            'correlation_id': f'replay-{self.replay_date}-{int(time.time())}',
            'trigger_source': 'pipeline_replay',
            'dataset_prefix': self.dataset_prefix,
        }

        logger.info(f"Calling {url}")
        response = requests.post(url, json=payload, headers=headers, timeout=1800)

        if response.status_code not in (200, 202):
            raise Exception(f"Phase 5 failed: {response.status_code} - {response.text[:500]}")

        # Wait for predictions to complete (poll for completion)
        # For now, assume it runs synchronously
        result = response.json()
        predictions = result.get('predictions_count', 0)
        logger.info(f"Phase 5 generated {predictions} predictions")
        return predictions

    def run_phase6_export(self) -> int:
        """Run Phase 6: Export to GCS."""
        url = f"{SERVICE_URLS['phase6_export']}/export"
        token = self.get_auth_token(SERVICE_URLS['phase6_export'])

        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        payload = {
            'target_date': self.replay_date,
            'export_types': ['tonight', 'predictions', 'best-bets'],
            'update_latest': False,  # Don't update latest for test runs
            'gcs_prefix': self.gcs_prefix,
            'dataset_prefix': self.dataset_prefix,
        }

        logger.info(f"Calling {url}")
        response = requests.post(url, json=payload, headers=headers, timeout=300)

        if response.status_code != 200:
            raise Exception(f"Phase 6 failed: {response.status_code} - {response.text[:500]}")

        result = response.json()
        files = result.get('files_exported', 0)
        logger.info(f"Phase 6 exported {files} files")
        return files

    def run(self) -> ReplayReport:
        """Run the complete pipeline replay."""
        logger.info("=" * 60)
        logger.info("  PIPELINE REPLAY")
        logger.info("=" * 60)
        logger.info(f"Date:           {self.replay_date}")
        logger.info(f"Dataset Prefix: {self.dataset_prefix}")
        logger.info(f"GCS Prefix:     {self.gcs_prefix}")
        logger.info(f"Dry Run:        {self.dry_run}")
        logger.info(f"Skip Phases:    {self.skip_phases or 'None'}")
        logger.info(f"Start Phase:    {self.start_phase}")
        logger.info("=" * 60)

        # Run each phase
        phases = [
            (2, "Raw Processing", self.run_phase2_raw),
            (3, "Analytics", self.run_phase3_analytics),
            (4, "Precompute", self.run_phase4_precompute),
            (5, "Predictions", self.run_phase5_predictions),
            (6, "Export", self.run_phase6_export),
        ]

        for phase_num, phase_name, run_func in phases:
            result = self.run_phase(phase_num, phase_name, run_func)
            if not result.success:
                self.report.overall_success = False
                logger.error(f"Pipeline failed at Phase {phase_num}")
                break

        self.report.end_time = datetime.now()

        # Print summary
        self.print_summary()

        return self.report

    def print_summary(self):
        """Print replay summary."""
        logger.info("\n")
        logger.info("=" * 60)
        logger.info("  REPLAY SUMMARY")
        logger.info("=" * 60)

        total = 0
        for phase in self.report.phases:
            status = "✅" if phase.success else "❌"
            logger.info(f"{status} {phase.phase}: {phase.duration_seconds:.1f}s")
            if phase.warnings:
                for w in phase.warnings:
                    logger.info(f"   ⚠️  {w}")
            if phase.error:
                logger.info(f"   ❌ {phase.error}")
            total += phase.duration_seconds

        logger.info("-" * 40)
        logger.info(f"Total: {total:.1f}s ({total/60:.1f}m)")
        logger.info(f"Status: {'PASSED ✅' if self.report.overall_success else 'FAILED ❌'}")
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Replay the NBA stats pipeline for a historical date',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bin/testing/replay_pipeline.py                    # Replay yesterday
  python bin/testing/replay_pipeline.py 2024-12-15         # Replay specific date
  python bin/testing/replay_pipeline.py 2024-12-15 --dry-run  # Preview only
  python bin/testing/replay_pipeline.py 2024-12-15 --skip-phase=2,6
  python bin/testing/replay_pipeline.py 2024-12-15 --start-phase=4
        """
    )

    parser.add_argument(
        'date',
        nargs='?',
        default=(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'),
        help='Date to replay (YYYY-MM-DD). Default: yesterday'
    )

    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Show what would be done without executing'
    )

    parser.add_argument(
        '--skip-phase',
        type=str,
        default='',
        help='Comma-separated list of phases to skip (e.g., 2,6)'
    )

    parser.add_argument(
        '--start-phase',
        type=int,
        default=2,
        help='Phase to start from (default: 2)'
    )

    parser.add_argument(
        '--dataset-prefix',
        type=str,
        default=os.environ.get('DATASET_PREFIX', 'test_'),
        help='Prefix for test datasets (default: test_)'
    )

    parser.add_argument(
        '--gcs-prefix',
        type=str,
        default=os.environ.get('GCS_PREFIX', 'test/'),
        help='Prefix for GCS paths (default: test/)'
    )

    parser.add_argument(
        '--output-json',
        type=str,
        help='Write report to JSON file'
    )

    args = parser.parse_args()

    # Parse skip phases
    skip_phases = []
    if args.skip_phase:
        skip_phases = [int(p.strip()) for p in args.skip_phase.split(',')]

    # Create and run replay
    replay = PipelineReplay(
        replay_date=args.date,
        dataset_prefix=args.dataset_prefix,
        gcs_prefix=args.gcs_prefix,
        dry_run=args.dry_run,
        skip_phases=skip_phases,
        start_phase=args.start_phase,
    )

    report = replay.run()

    # Write JSON report if requested
    if args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(report.to_dict(), f, indent=2)
        logger.info(f"Report written to {args.output_json}")

    # Exit with appropriate code
    sys.exit(0 if report.overall_success else 1)


if __name__ == '__main__':
    main()
