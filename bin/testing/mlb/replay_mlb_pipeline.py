#!/usr/bin/env python3
"""
MLB Pipeline Replay - End-to-end test of the MLB prediction pipeline.

Replays a historical game day through all pipeline phases:
  Phase 1: Verify raw data exists (schedule, lineups, props, stats)
  Phase 2: Verify analytics data exists (pitcher_game_summary)
  Phase 3: Run predictions (V1.4 and V1.6)
  Phase 4: Grade predictions against actual results
  Phase 5: Generate comparison report

This tests the complete orchestration without affecting production.

Usage:
    # Replay a specific date
    PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-07-15

    # Dry run (show what would happen)
    PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-07-15 --dry-run

    # Find good dates for testing
    PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --find-dates

    # Skip specific phases
    PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-07-15 --skip-phase=1,2

    # Start from specific phase
    PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-07-15 --start-phase=3

    # Output JSON report
    PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-07-15 --output-json report.json

Created: 2026-01-15
Part of MLB E2E Test System
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

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
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# Cloud Run service URLs
SERVICE_URLS = {
    'prediction_worker': os.environ.get(
        'MLB_PREDICTION_WORKER_URL',
        'https://mlb-prediction-worker-756957797294.us-west2.run.app'
    ),
    'grading_service': os.environ.get(
        'MLB_GRADING_SERVICE_URL',
        'https://mlb-grading-service-756957797294.us-west2.run.app'
    ),
}

# Performance thresholds (seconds)
PHASE_THRESHOLDS = {
    'phase1': {'warn': 30, 'critical': 60},     # Data verification
    'phase2': {'warn': 30, 'critical': 60},     # Analytics verification
    'phase3': {'warn': 300, 'critical': 600},   # Predictions
    'phase4': {'warn': 60, 'critical': 120},    # Grading
    'phase5': {'warn': 10, 'critical': 30},     # Report generation
}

# Minimum data thresholds
DATA_THRESHOLDS = {
    'pitchers': 10,        # Min pitchers per game day
    'with_lines': 5,       # Min pitchers with betting lines
    'with_results': 5,     # Min pitchers with actual results
}


@dataclass
class PhaseResult:
    """Result of running a single phase."""
    phase: str
    phase_name: str
    success: bool
    duration_seconds: float
    records_processed: int = 0
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    details: Dict = field(default_factory=dict)


@dataclass
class ReplayReport:
    """Complete replay report."""
    replay_date: str
    start_time: datetime
    end_time: Optional[datetime] = None
    phases: List[PhaseResult] = field(default_factory=list)
    overall_success: bool = True

    # Summary stats
    total_pitchers: int = 0
    pitchers_with_lines: int = 0
    pitchers_with_results: int = 0
    v1_4_predictions: int = 0
    v1_6_predictions: int = 0
    v1_4_accuracy: float = 0.0
    v1_6_accuracy: float = 0.0

    @property
    def total_duration(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return sum(p.duration_seconds for p in self.phases)

    def to_dict(self) -> Dict:
        return {
            'replay_date': self.replay_date,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'total_duration_seconds': self.total_duration,
            'overall_success': self.overall_success,
            'summary': {
                'total_pitchers': self.total_pitchers,
                'pitchers_with_lines': self.pitchers_with_lines,
                'pitchers_with_results': self.pitchers_with_results,
                'v1_4_predictions': self.v1_4_predictions,
                'v1_6_predictions': self.v1_6_predictions,
                'v1_4_accuracy': self.v1_4_accuracy,
                'v1_6_accuracy': self.v1_6_accuracy,
            },
            'phases': [
                {
                    'phase': p.phase,
                    'phase_name': p.phase_name,
                    'success': p.success,
                    'duration_seconds': p.duration_seconds,
                    'records_processed': p.records_processed,
                    'error': p.error,
                    'warnings': p.warnings,
                    'details': p.details,
                }
                for p in self.phases
            ]
        }


class MLBPipelineReplay:
    """Orchestrates MLB pipeline replay for a given date."""

    def __init__(
        self,
        replay_date: str,
        dry_run: bool = False,
        skip_phases: Optional[List[int]] = None,
        start_phase: int = 1,
        use_cloud_run: bool = False,
    ):
        self.replay_date = replay_date
        self.game_date = date.fromisoformat(replay_date)
        self.dry_run = dry_run
        self.skip_phases = skip_phases or []
        self.start_phase = start_phase
        self.use_cloud_run = use_cloud_run

        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.report = ReplayReport(
            replay_date=replay_date,
            start_time=datetime.now()
        )

        # Lazy-loaded predictors
        self._v1_4_predictor = None
        self._v1_6_predictor = None

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
            logger.info(f"  Skipping Phase {phase_num}: {phase_name}")
            return PhaseResult(
                phase=f"phase{phase_num}",
                phase_name=phase_name,
                success=True,
                duration_seconds=0,
                warnings=['Skipped by user request']
            )

        if phase_num < self.start_phase:
            logger.info(f"  Skipping Phase {phase_num}: {phase_name} (before start_phase)")
            return PhaseResult(
                phase=f"phase{phase_num}",
                phase_name=phase_name,
                success=True,
                duration_seconds=0,
                warnings=['Skipped - before start_phase']
            )

        logger.info(f"\nPhase {phase_num}: {phase_name}")
        logger.info("-" * 50)

        start_time = time.time()
        warnings = []

        try:
            if self.dry_run:
                logger.info(f"   [DRY RUN] Would execute Phase {phase_num}")
                result = PhaseResult(
                    phase=f"phase{phase_num}",
                    phase_name=phase_name,
                    success=True,
                    duration_seconds=0,
                    warnings=['Dry run - not executed']
                )
            else:
                records, details = run_func()
                duration = time.time() - start_time

                # Check thresholds
                threshold = PHASE_THRESHOLDS.get(f'phase{phase_num}', {})
                if duration > threshold.get('critical', float('inf')):
                    warnings.append(f'CRITICAL: Duration {duration:.0f}s exceeds threshold')
                elif duration > threshold.get('warn', float('inf')):
                    warnings.append(f'WARNING: Duration {duration:.0f}s is high')

                result = PhaseResult(
                    phase=f"phase{phase_num}",
                    phase_name=phase_name,
                    success=True,
                    duration_seconds=duration,
                    records_processed=records,
                    warnings=warnings,
                    details=details
                )

            logger.info(f"Phase {phase_num} complete: {result.duration_seconds:.1f}s, {result.records_processed} records")

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Phase {phase_num} failed: {e}")
            result = PhaseResult(
                phase=f"phase{phase_num}",
                phase_name=phase_name,
                success=False,
                duration_seconds=duration,
                error=str(e)
            )

        self.report.phases.append(result)
        return result

    def phase1_verify_raw_data(self) -> tuple:
        """
        Phase 1: Verify raw data exists for the replay date.

        Checks:
        - MLB schedule exists
        - Pitcher stats exist
        - Betting props exist
        """
        logger.info(f"Verifying raw data for {self.replay_date}")
        details = {}

        # Check schedule (optional - may not have schedule data)
        try:
            schedule_query = f"""
            SELECT COUNT(DISTINCT game_pk) as games
            FROM `{PROJECT_ID}.mlb_raw.mlb_schedule`
            WHERE game_date = '{self.replay_date}'
            """
            result = self.bq_client.query(schedule_query).result()
            games = list(result)[0].games
            details['games_scheduled'] = games
            logger.info(f"  Games scheduled: {games}")
        except Exception:
            details['games_scheduled'] = 'N/A'
            logger.info(f"  Games scheduled: N/A (schedule table may be empty)")

        # Check pitcher stats
        stats_query = f"""
        SELECT COUNT(DISTINCT player_lookup) as pitchers
        FROM `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats`
        WHERE game_date = '{self.replay_date}' AND is_starter = TRUE
        """
        result = self.bq_client.query(stats_query).result()
        pitchers = list(result)[0].pitchers
        details['pitchers_with_stats'] = pitchers
        self.report.pitchers_with_results = pitchers
        logger.info(f"  Pitchers with stats: {pitchers}")

        # Check props (odds API)
        props_query = f"""
        SELECT COUNT(DISTINCT player_lookup) as pitchers
        FROM `{PROJECT_ID}.mlb_raw.oddsa_pitcher_props`
        WHERE game_date = '{self.replay_date}' AND market_key = 'pitcher_strikeouts'
        """
        result = self.bq_client.query(props_query).result()
        pitchers_props = list(result)[0].pitchers
        details['pitchers_with_props'] = pitchers_props
        self.report.pitchers_with_lines = pitchers_props
        logger.info(f"  Pitchers with props: {pitchers_props}")

        # Must have at least pitcher stats to proceed
        if pitchers < DATA_THRESHOLDS['with_results']:
            raise Exception(f"Not enough pitcher stats ({pitchers} < {DATA_THRESHOLDS['with_results']})")

        return pitchers, details

    def phase2_verify_analytics(self) -> tuple:
        """
        Phase 2: Verify analytics data exists.

        Checks:
        - pitcher_game_summary has data
        - Rolling stats are populated
        """
        logger.info(f"Verifying analytics data for {self.replay_date}")
        details = {}

        # Check pitcher_game_summary
        summary_query = f"""
        SELECT
            COUNT(DISTINCT player_lookup) as pitchers,
            AVG(k_avg_last_5) as avg_k_avg,
            COUNT(CASE WHEN k_avg_last_5 IS NOT NULL THEN 1 END) as with_rolling
        FROM `{PROJECT_ID}.mlb_analytics.pitcher_game_summary`
        WHERE game_date = '{self.replay_date}'
        """
        result = self.bq_client.query(summary_query).result()
        row = list(result)[0]

        pitchers = row.pitchers
        details['pitchers_in_summary'] = pitchers
        details['pitchers_with_rolling_stats'] = row.with_rolling
        details['avg_k_avg_last_5'] = round(row.avg_k_avg, 2) if row.avg_k_avg else None

        self.report.total_pitchers = pitchers
        logger.info(f"  Pitchers in summary: {pitchers}")
        logger.info(f"  With rolling stats: {row.with_rolling}")

        if pitchers < DATA_THRESHOLDS['pitchers']:
            raise Exception(f"Not enough pitchers ({pitchers} < {DATA_THRESHOLDS['pitchers']})")

        return pitchers, details

    def phase3_run_predictions(self) -> tuple:
        """
        Phase 3: Run predictions using local predictors.

        Runs both V1.4 and V1.6 models against the historical data.
        """
        logger.info(f"Running predictions for {self.replay_date}")
        details = {'predictions': []}

        # Import predictors
        from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor

        # Load V1.4 model
        if self._v1_4_predictor is None:
            self._v1_4_predictor = PitcherStrikeoutsPredictor(
                model_path='gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json'
            )
            self._v1_4_predictor.load_model()

        # Load V1.6 model
        if self._v1_6_predictor is None:
            self._v1_6_predictor = PitcherStrikeoutsPredictor(
                model_path='gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json'
            )
            self._v1_6_predictor.load_model()

        # Get pitchers for the date
        query = f"""
        SELECT
            pgs.player_lookup,
            pgs.player_full_name,
            pgs.team_abbr,
            odds.point as line,
            stats.strikeouts as actual
        FROM `{PROJECT_ID}.mlb_analytics.pitcher_game_summary` pgs
        LEFT JOIN (
            SELECT player_lookup, point,
                ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY last_update DESC) as rn
            FROM `{PROJECT_ID}.mlb_raw.oddsa_pitcher_props`
            WHERE game_date = '{self.replay_date}' AND market_key = 'pitcher_strikeouts'
        ) odds ON REPLACE(pgs.player_lookup, '_', '') = odds.player_lookup AND odds.rn = 1
        LEFT JOIN `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats` stats
            ON pgs.player_lookup = stats.player_lookup
            AND pgs.game_date = stats.game_date
            AND stats.is_starter = TRUE
        WHERE pgs.game_date = '{self.replay_date}'
        """

        pitchers = list(self.bq_client.query(query).result())

        v1_4_picks = 0
        v1_4_correct = 0
        v1_6_picks = 0
        v1_6_correct = 0

        for pitcher in pitchers:
            try:
                # Load features
                features = self._v1_4_predictor.load_pitcher_features(
                    pitcher.player_lookup,
                    self.game_date
                )

                if not features:
                    continue

                line = pitcher.line
                actual = pitcher.actual

                # V1.4 prediction
                pred_1_4 = self._v1_4_predictor.predict(
                    pitcher_lookup=pitcher.player_lookup,
                    features=features,
                    strikeouts_line=line
                )

                # V1.6 prediction
                pred_1_6 = self._v1_6_predictor.predict(
                    pitcher_lookup=pitcher.player_lookup,
                    features=features,
                    strikeouts_line=line
                )

                # Grade if we have line and actual
                if line is not None and actual is not None:
                    rec_1_4 = pred_1_4.get('recommendation')
                    rec_1_6 = pred_1_6.get('recommendation')

                    if rec_1_4 in ('OVER', 'UNDER'):
                        v1_4_picks += 1
                        if (rec_1_4 == 'OVER' and actual > line) or (rec_1_4 == 'UNDER' and actual < line):
                            v1_4_correct += 1

                    if rec_1_6 in ('OVER', 'UNDER'):
                        v1_6_picks += 1
                        if (rec_1_6 == 'OVER' and actual > line) or (rec_1_6 == 'UNDER' and actual < line):
                            v1_6_correct += 1

                    details['predictions'].append({
                        'pitcher': pitcher.player_lookup,
                        'line': line,
                        'actual': actual,
                        'v1_4_pred': pred_1_4.get('predicted_strikeouts'),
                        'v1_4_rec': rec_1_4,
                        'v1_6_pred': pred_1_6.get('predicted_strikeouts'),
                        'v1_6_rec': rec_1_6,
                    })

            except Exception as e:
                logger.warning(f"Error predicting {pitcher.player_lookup}: {e}")

        # Calculate accuracy
        self.report.v1_4_predictions = v1_4_picks
        self.report.v1_6_predictions = v1_6_picks
        self.report.v1_4_accuracy = (v1_4_correct / v1_4_picks * 100) if v1_4_picks > 0 else 0
        self.report.v1_6_accuracy = (v1_6_correct / v1_6_picks * 100) if v1_6_picks > 0 else 0

        details['v1_4_picks'] = v1_4_picks
        details['v1_4_correct'] = v1_4_correct
        details['v1_6_picks'] = v1_6_picks
        details['v1_6_correct'] = v1_6_correct

        logger.info(f"  V1.4: {v1_4_picks} picks, {v1_4_correct} correct ({self.report.v1_4_accuracy:.1f}%)")
        logger.info(f"  V1.6: {v1_6_picks} picks, {v1_6_correct} correct ({self.report.v1_6_accuracy:.1f}%)")

        total_predictions = len(details['predictions'])
        return total_predictions, details

    def phase4_verify_grading(self) -> tuple:
        """
        Phase 4: Verify grading would work.

        Checks that we have all data needed for grading.
        """
        logger.info(f"Verifying grading data for {self.replay_date}")
        details = {}

        # Count pitchers with all required data
        query = f"""
        SELECT
            COUNT(DISTINCT pgs.player_lookup) as total,
            COUNT(DISTINCT CASE WHEN stats.strikeouts IS NOT NULL THEN pgs.player_lookup END) as with_results,
            COUNT(DISTINCT CASE WHEN odds.point IS NOT NULL THEN pgs.player_lookup END) as with_lines
        FROM `{PROJECT_ID}.mlb_analytics.pitcher_game_summary` pgs
        LEFT JOIN `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats` stats
            ON pgs.player_lookup = stats.player_lookup
            AND pgs.game_date = stats.game_date
            AND stats.is_starter = TRUE
        LEFT JOIN (
            SELECT player_lookup, point,
                ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY last_update DESC) as rn
            FROM `{PROJECT_ID}.mlb_raw.oddsa_pitcher_props`
            WHERE game_date = '{self.replay_date}' AND market_key = 'pitcher_strikeouts'
        ) odds ON REPLACE(pgs.player_lookup, '_', '') = odds.player_lookup AND odds.rn = 1
        WHERE pgs.game_date = '{self.replay_date}'
        """

        result = self.bq_client.query(query).result()
        row = list(result)[0]

        details['total_pitchers'] = row.total
        details['with_results'] = row.with_results
        details['with_lines'] = row.with_lines
        details['gradeable'] = min(row.with_results, row.with_lines)

        logger.info(f"  Total pitchers: {row.total}")
        logger.info(f"  With results: {row.with_results}")
        logger.info(f"  With lines: {row.with_lines}")
        logger.info(f"  Gradeable: {details['gradeable']}")

        return details['gradeable'], details

    def phase5_generate_report(self) -> tuple:
        """
        Phase 5: Generate summary report.
        """
        logger.info("Generating summary report")
        details = {
            'date': self.replay_date,
            'total_pitchers': self.report.total_pitchers,
            'v1_4_accuracy': f"{self.report.v1_4_accuracy:.1f}%",
            'v1_6_accuracy': f"{self.report.v1_6_accuracy:.1f}%",
            'overall_success': self.report.overall_success,
        }

        return 1, details

    def find_dates_with_data(self, limit: int = 20) -> List[Dict]:
        """Find historical dates with good data coverage."""
        query = f"""
        SELECT
            pgs.game_date,
            COUNT(DISTINCT pgs.player_lookup) as pitchers,
            COUNT(DISTINCT stats.player_lookup) as with_results
        FROM `{PROJECT_ID}.mlb_analytics.pitcher_game_summary` pgs
        LEFT JOIN `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats` stats
            ON pgs.player_lookup = stats.player_lookup
            AND pgs.game_date = stats.game_date
            AND stats.is_starter = TRUE
        WHERE pgs.game_date >= '2024-04-01'
            AND pgs.game_date < '2025-10-01'
        GROUP BY pgs.game_date
        HAVING COUNT(DISTINCT pgs.player_lookup) >= {DATA_THRESHOLDS['pitchers']}
            AND COUNT(DISTINCT stats.player_lookup) >= {DATA_THRESHOLDS['with_results']}
        ORDER BY game_date DESC
        LIMIT {limit}
        """

        result = self.bq_client.query(query).result()
        return [dict(row) for row in result]

    def run(self) -> ReplayReport:
        """Run the complete pipeline replay."""
        logger.info("=" * 60)
        logger.info("  MLB PIPELINE REPLAY - E2E TEST")
        logger.info("=" * 60)
        logger.info(f"Date:        {self.replay_date}")
        logger.info(f"Dry Run:     {self.dry_run}")
        logger.info(f"Skip Phases: {self.skip_phases or 'None'}")
        logger.info(f"Start Phase: {self.start_phase}")
        logger.info("=" * 60)

        # Run each phase
        phases = [
            (1, "Verify Raw Data", self.phase1_verify_raw_data),
            (2, "Verify Analytics", self.phase2_verify_analytics),
            (3, "Run Predictions", self.phase3_run_predictions),
            (4, "Verify Grading", self.phase4_verify_grading),
            (5, "Generate Report", self.phase5_generate_report),
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
            status = "PASS" if phase.success else "FAIL"
            logger.info(f"[{status}] {phase.phase}: {phase.phase_name} ({phase.duration_seconds:.1f}s)")
            if phase.warnings:
                for w in phase.warnings:
                    logger.info(f"       WARNING: {w}")
            if phase.error:
                logger.info(f"       ERROR: {phase.error}")
            total += phase.duration_seconds

        logger.info("-" * 40)
        logger.info(f"Total Duration: {total:.1f}s ({total/60:.1f}m)")
        logger.info(f"")
        logger.info(f"Data Coverage:")
        logger.info(f"  Pitchers:     {self.report.total_pitchers}")
        logger.info(f"  With Lines:   {self.report.pitchers_with_lines}")
        logger.info(f"  With Results: {self.report.pitchers_with_results}")
        logger.info(f"")
        logger.info(f"Prediction Results:")
        logger.info(f"  V1.4: {self.report.v1_4_predictions} picks, {self.report.v1_4_accuracy:.1f}% accuracy")
        logger.info(f"  V1.6: {self.report.v1_6_predictions} picks, {self.report.v1_6_accuracy:.1f}% accuracy")
        logger.info(f"")
        logger.info(f"Status: {'PASSED' if self.report.overall_success else 'FAILED'}")
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Replay the MLB pipeline for a historical date (E2E test)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-07-15
  python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-07-15 --dry-run
  python bin/testing/mlb/replay_mlb_pipeline.py --find-dates
  python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-07-15 --skip-phase=1,2
  python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-07-15 --output-json report.json
        """
    )

    parser.add_argument(
        '--date', '-d',
        help='Date to replay (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--find-dates',
        action='store_true',
        help='Find dates with good data coverage'
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
        help='Comma-separated list of phases to skip (e.g., 1,2)'
    )

    parser.add_argument(
        '--start-phase',
        type=int,
        default=1,
        help='Phase to start from (default: 1)'
    )

    parser.add_argument(
        '--output-json',
        type=str,
        help='Write report to JSON file'
    )

    args = parser.parse_args()

    # Handle find-dates
    if args.find_dates:
        logger.info("Searching for dates with good data coverage...")
        replay = MLBPipelineReplay(
            replay_date=(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'),
            dry_run=True
        )
        dates = replay.find_dates_with_data()

        print(f"\n{'Date':<12} {'Pitchers':<10} {'With Results':<12}")
        print("-" * 40)
        for d in dates:
            print(f"{d['game_date']}   {d['pitchers']:<10} {d['with_results']:<12}")

        if dates:
            print(f"\nExample: python bin/testing/mlb/replay_mlb_pipeline.py --date {dates[0]['game_date']}")
        return

    # Require date if not finding dates
    if not args.date:
        parser.print_help()
        print("\nError: --date is required (or use --find-dates)")
        sys.exit(1)

    # Parse skip phases
    skip_phases = []
    if args.skip_phase:
        skip_phases = [int(p.strip()) for p in args.skip_phase.split(',')]

    # Create and run replay
    replay = MLBPipelineReplay(
        replay_date=args.date,
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
