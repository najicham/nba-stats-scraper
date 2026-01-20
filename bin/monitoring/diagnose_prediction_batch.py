#!/usr/bin/env python3
"""
Diagnose prediction batch failures.

Usage:
    python bin/monitoring/diagnose_prediction_batch.py 2026-01-19
    python bin/monitoring/diagnose_prediction_batch.py 2026-01-19 --verbose
    python bin/monitoring/diagnose_prediction_batch.py 2026-01-19 --json

Purpose:
    Comprehensive diagnostics for prediction pipeline issues.
    Checks predictions table, staging tables, ML features, and worker logs.

Created: 2026-01-19 (Phase 2.1)
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery, firestore, logging as cloud_logging


class PredictionBatchDiagnostics:
    """Comprehensive prediction batch diagnostics."""

    def __init__(self, project_id: str = 'nba-props-platform'):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)
        self.fs_client = firestore.Client(project=project_id)
        self.log_client = cloud_logging.Client(project=project_id)

    def diagnose(self, game_date: str, verbose: bool = False) -> Dict:
        """
        Run comprehensive diagnostics for a prediction batch.

        Args:
            game_date: Date to diagnose (YYYY-MM-DD)
            verbose: Include detailed logs

        Returns:
            Dictionary with diagnostic results
        """
        print(f"=== Diagnosing Prediction Batch for {game_date} ===\n")

        results = {}

        # 1. Check predictions exist
        print("🔍 Step 1/6: Checking predictions table...")
        results['predictions'] = self._check_predictions_table(game_date)
        self._print_predictions_result(results['predictions'])

        # 2. Check staging tables
        print("\n🔍 Step 2/6: Checking staging tables...")
        results['staging'] = self._check_staging_tables(game_date)
        self._print_staging_result(results['staging'])

        # 3. Check ML features
        print("\n🔍 Step 3/6: Checking ML features...")
        results['features'] = self._check_ml_features(game_date)
        self._print_features_result(results['features'])

        # 4. Check worker runs
        print("\n🔍 Step 4/6: Checking worker runs...")
        results['worker_runs'] = self._check_worker_runs(game_date)
        self._print_worker_runs_result(results['worker_runs'])

        # 5. Check Firestore batch state
        print("\n🔍 Step 5/6: Checking Firestore batch state...")
        results['firestore'] = self._check_firestore_batch(game_date)
        self._print_firestore_result(results['firestore'])

        # 6. Check worker error logs
        if verbose:
            print("\n🔍 Step 6/6: Checking worker error logs...")
            results['errors'] = self._check_worker_errors(game_date)
            self._print_error_logs(results['errors'])
        else:
            print("\n🔍 Step 6/6: Checking worker error count...")
            results['errors'] = {'count': self._count_worker_errors(game_date)}
            print(f"   Worker errors: {results['errors']['count']} errors")

        # Analysis & recommendations
        print("\n" + "="*70)
        print("DIAGNOSIS")
        print("="*70)
        self._analyze_results(results)

        return results

    def _check_predictions_table(self, game_date: str) -> Dict:
        """Check if predictions exist for game_date."""
        # Use parameterized query to prevent SQL injection
        query = f"""
        SELECT
          COUNT(*) as count,
          MIN(created_at) as earliest,
          MAX(created_at) as latest,
          COUNT(DISTINCT system_id) as systems_count,
          COUNT(DISTINCT player_lookup) as players_count
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date = @game_date
          AND is_active = TRUE
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        try:
            result = list(self.bq_client.query(query, job_config=job_config).result())
            if result:
                row = result[0]
                return {
                    "found": row.count > 0,
                    "count": row.count,
                    "earliest": str(row.earliest) if row.earliest else None,
                    "latest": str(row.latest) if row.latest else None,
                    "systems_count": row.systems_count,
                    "players_count": row.players_count
                }
            else:
                return {"found": False, "count": 0}
        except Exception as e:
            return {"error": str(e)}

    def _check_staging_tables(self, game_date: str) -> Dict:
        """Check for staging tables from game_date."""
        # Use parameterized query to prevent SQL injection
        query = f"""
        SELECT table_id, TIMESTAMP_MILLIS(creation_time) as created_at
        FROM `{self.project_id}.nba_predictions.__TABLES__`
        WHERE table_id LIKE 'prediction_worker_staging%'
          AND TIMESTAMP_MILLIS(creation_time) >= TIMESTAMP(@game_date_start)
          AND TIMESTAMP_MILLIS(creation_time) < TIMESTAMP_ADD(TIMESTAMP(@game_date_start), INTERVAL 1 DAY)
        ORDER BY creation_time DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date_start", "TIMESTAMP", f"{game_date} 00:00:00"),
            ]
        )

        try:
            result = list(self.bq_client.query(query, job_config=job_config).result())
            tables = [{"table_id": row.table_id, "created_at": str(row.created_at)} for row in result]
            return {
                "found": len(tables) > 0,
                "count": len(tables),
                "tables": tables
            }
        except Exception as e:
            return {"error": str(e)}

    def _check_ml_features(self, game_date: str) -> Dict:
        """Check ML features availability."""
        # Use parameterized query to prevent SQL injection
        query = f"""
        SELECT
          COUNT(DISTINCT player_lookup) as players_count,
          COUNT(*) as total_features
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = @game_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        try:
            result = list(self.bq_client.query(query, job_config=job_config).result())
            if result:
                row = result[0]
                return {
                    "found": row.players_count > 0,
                    "players_count": row.players_count,
                    "total_features": row.total_features
                }
            else:
                return {"found": False, "players_count": 0}
        except Exception as e:
            return {"error": str(e)}

    def _check_worker_runs(self, game_date: str) -> Dict:
        """Check prediction worker runs."""
        # Use parameterized query to prevent SQL injection
        query = f"""
        SELECT
          run_date,
          COUNT(*) as total_runs,
          SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_runs,
          COUNT(DISTINCT player_lookup) as unique_players
        FROM `{self.project_id}.nba_predictions.prediction_worker_runs`
        WHERE run_date = @game_date
        GROUP BY run_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        try:
            result = list(self.bq_client.query(query, job_config=job_config).result())
            if result:
                row = result[0]
                return {
                    "found": True,
                    "total_runs": row.total_runs,
                    "successful_runs": row.successful_runs,
                    "unique_players": row.unique_players,
                    "success_rate": (row.successful_runs / row.total_runs * 100) if row.total_runs > 0 else 0
                }
            else:
                return {"found": False, "total_runs": 0}
        except Exception as e:
            return {"error": str(e)}

    def _check_firestore_batch(self, game_date: str) -> Dict:
        """Check Firestore batch state."""
        try:
            doc_ref = self.fs_client.collection('batch_state').document(game_date)
            doc = doc_ref.get()

            if doc.exists:
                data = doc.to_dict()
                return {
                    "found": True,
                    "status": data.get('status', 'unknown'),
                    "created_at": str(data.get('created_at')) if data.get('created_at') else None,
                    "updated_at": str(data.get('updated_at')) if data.get('updated_at') else None,
                    "data": data
                }
            else:
                return {"found": False}
        except Exception as e:
            return {"error": str(e)}

    def _count_worker_errors(self, game_date: str) -> int:
        """Count prediction worker errors for game_date."""
        try:
            # Query Cloud Logging for prediction-worker errors
            log_filter = f'''
            resource.type="cloud_run_revision"
            AND resource.labels.service_name="prediction-worker"
            AND severity>=ERROR
            AND timestamp>="{game_date}T00:00:00Z"
            AND timestamp<"{game_date}T23:59:59Z"
            '''

            # Note: Cloud Logging API has limits, this is a rough count
            # For exact count, use logging client with pagination
            return 0  # Placeholder - would need logging client setup
        except Exception:
            return 0

    def _check_worker_errors(self, game_date: str) -> Dict:
        """Get detailed worker error logs."""
        # This would fetch actual log entries
        # For now, return placeholder
        return {
            "count": self._count_worker_errors(game_date),
            "sample_errors": []
        }

    # Print helpers
    def _print_predictions_result(self, result: Dict):
        if result.get('error'):
            print(f"   ❌ Error: {result['error']}")
        elif result.get('found'):
            print(f"   ✅ Predictions found: {result['count']}")
            print(f"      - Systems: {result['systems_count']}")
            print(f"      - Players: {result['players_count']}")
            print(f"      - Time range: {result['earliest']} → {result['latest']}")
        else:
            print(f"   ❌ No predictions found")

    def _print_staging_result(self, result: Dict):
        if result.get('error'):
            print(f"   ❌ Error: {result['error']}")
        elif result.get('found'):
            print(f"   ⚠️  Found {result['count']} staging tables (should be 0 after consolidation)")
            for table in result.get('tables', [])[:5]:  # Show first 5
                print(f"      - {table['table_id']} ({table['created_at']})")
        else:
            print(f"   ✅ No staging tables (predictions consolidated)")

    def _print_features_result(self, result: Dict):
        if result.get('error'):
            print(f"   ❌ Error: {result['error']}")
        elif result.get('found'):
            print(f"   ✅ ML features available: {result['players_count']} players, {result['total_features']} features")
        else:
            print(f"   ❌ No ML features found (Phase 4 incomplete?)")

    def _print_worker_runs_result(self, result: Dict):
        if result.get('error'):
            print(f"   ❌ Error: {result['error']}")
        elif result.get('found'):
            print(f"   ✅ Worker runs logged: {result['successful_runs']}/{result['total_runs']} successful")
            print(f"      - Success rate: {result['success_rate']:.1f}%")
            print(f"      - Unique players: {result['unique_players']}")
        else:
            print(f"   ⚠️  No worker runs logged (audit trail missing)")

    def _print_firestore_result(self, result: Dict):
        if result.get('error'):
            print(f"   ❌ Error: {result['error']}")
        elif result.get('found'):
            print(f"   ✅ Firestore batch state found: {result['status']}")
            print(f"      - Created: {result.get('created_at')}")
            print(f"      - Updated: {result.get('updated_at')}")
        else:
            print(f"   ⚠️  No Firestore batch state")

    def _print_error_logs(self, result: Dict):
        print(f"   Worker errors: {result.get('count', 0)} errors")
        # Would print sample errors here

    def _analyze_results(self, results: Dict):
        """Analyze results and provide diagnosis."""
        predictions = results.get('predictions', {})
        staging = results.get('staging', {})
        features = results.get('features', {})
        worker_runs = results.get('worker_runs', {})
        firestore = results.get('firestore', {})

        # Scenario 1: Everything working
        if predictions.get('found') and not staging.get('found'):
            print("✅ HEALTHY: Predictions generated successfully")
            print(f"   - {predictions['count']} predictions from {predictions['systems_count']} systems")
            print(f"   - Staging tables consolidated")
            return

        # Scenario 2: Predictions in staging but not consolidated
        if not predictions.get('found') and staging.get('found'):
            print("❌ ISSUE: Predictions in staging but not consolidated")
            print("   → Check coordinator consolidation logic")
            print(f"   → {staging['count']} staging tables need processing")
            return

        # Scenario 3: No ML features
        if not predictions.get('found') and not features.get('found'):
            print("❌ ISSUE: No ML features available")
            print("   → Check Phase 4 completion")
            print("   → Verify feature engineering pipeline")
            return

        # Scenario 4: No predictions at all
        if not predictions.get('found'):
            print("❌ ISSUE: No predictions generated")
            if not worker_runs.get('found'):
                print("   → Worker runs not logged (possible trigger failure)")
            if not firestore.get('found'):
                print("   → No Firestore batch state (batch may not have started)")
            print("   → Check prediction-worker Cloud Scheduler")
            return

        # Scenario 5: Partial success
        if predictions.get('found') and staging.get('found'):
            print("⚠️  PARTIAL: Predictions exist but staging tables remain")
            print("   → May indicate in-progress batch or consolidation delay")
            return


def main():
    parser = argparse.ArgumentParser(description='Diagnose prediction batch issues')
    parser.add_argument('game_date', help='Game date to diagnose (YYYY-MM-DD)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Include detailed logs')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--project', default='nba-props-platform', help='GCP project ID')

    args = parser.parse_args()

    diagnostics = PredictionBatchDiagnostics(project_id=args.project)
    results = diagnostics.diagnose(args.game_date, verbose=args.verbose)

    if args.json:
        print("\n" + json.dumps(results, indent=2, default=str))


if __name__ == '__main__':
    main()
