#!/usr/bin/env python3
"""
Pipeline Health Check Script

A comprehensive health check that validates the entire NBA prediction pipeline.
Run this to quickly diagnose pipeline issues.

Usage:
    python tools/monitoring/check_pipeline_health.py
    python tools/monitoring/check_pipeline_health.py --date 2026-01-11
    python tools/monitoring/check_pipeline_health.py --verbose
"""

import argparse
import json
import requests
from datetime import datetime, timedelta
from google.cloud import bigquery
from typing import Dict, List, Tuple, Optional


def get_dates() -> Tuple[str, str, str]:
    """Get today, yesterday, and tomorrow dates in YYYY-MM-DD format."""
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    return (
        today.strftime('%Y-%m-%d'),
        yesterday.strftime('%Y-%m-%d'),
        tomorrow.strftime('%Y-%m-%d')
    )


def check_with_emoji(passed: bool) -> str:
    """Return emoji based on check result."""
    return "OK" if passed else "FAIL"


class PipelineHealthChecker:
    def __init__(self, verbose: bool = False):
        self.client = bigquery.Client()
        self.verbose = verbose
        self.issues: List[str] = []

    def run_query(self, query: str) -> List[Dict]:
        """Run a BigQuery query and return results as list of dicts."""
        try:
            result = self.client.query(query).result(timeout=60)
            return [dict(row) for row in result]
        except Exception as e:
            if self.verbose:
                print(f"  Query error: {e}")
            return []

    def check_schedule(self, date: str) -> Dict:
        """Check schedule status for a date."""
        query = f"""
        SELECT
            COUNT(*) as total_games,
            COUNTIF(game_status_text = 'Final') as final_games,
            COUNTIF(game_status_text != 'Final') as pending_games
        FROM `nba_raw.v_nbac_schedule_latest`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        if results:
            return results[0]
        return {'total_games': 0, 'final_games': 0, 'pending_games': 0}

    def check_player_game_summary(self, date: str) -> int:
        """Check player_game_summary records for a date."""
        query = f"""
        SELECT COUNT(*) as records
        FROM `nba_analytics.player_game_summary`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        return results[0]['records'] if results else 0

    def check_prediction_accuracy(self, date: str) -> Dict:
        """Check grading records for a date."""
        query = f"""
        SELECT
            COUNT(*) as total_records,
            COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable,
            COUNTIF(prediction_correct = TRUE) as correct
        FROM `nba_predictions.prediction_accuracy`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        if results:
            r = results[0]
            r['win_rate'] = round(r['correct'] / r['actionable'] * 100, 1) if r['actionable'] > 0 else 0
            return r
        return {'total_records': 0, 'actionable': 0, 'correct': 0, 'win_rate': 0}

    def check_predictions(self, date: str) -> Dict:
        """Check predictions for a date."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNT(DISTINCT player_lookup) as players,
            COUNT(DISTINCT system_id) as systems
        FROM `nba_predictions.player_prop_predictions`
        WHERE game_date = '{date}' AND is_active = TRUE
        """
        results = self.run_query(query)
        return results[0] if results else {'total': 0, 'players': 0, 'systems': 0}

    def check_phase4_tables(self, date: str) -> Dict:
        """Check Phase 4 precompute tables for a date."""
        tables = {
            'team_defense_zone_analysis': f"SELECT COUNT(*) as cnt FROM `nba_precompute.team_defense_zone_analysis` WHERE analysis_date = '{date}'",
            'player_shot_zone_analysis': f"SELECT COUNT(*) as cnt FROM `nba_precompute.player_shot_zone_analysis` WHERE analysis_date = '{date}'",
            'player_composite_factors': f"SELECT COUNT(*) as cnt FROM `nba_precompute.player_composite_factors` WHERE game_date = '{date}'",
            'player_daily_cache': f"SELECT COUNT(*) as cnt FROM `nba_precompute.player_daily_cache` WHERE cache_date = '{date}'",
            'ml_feature_store_v2': f"SELECT COUNT(*) as cnt FROM `nba_predictions.ml_feature_store_v2` WHERE game_date = '{date}'",
        }

        results = {}
        for table, query in tables.items():
            r = self.run_query(query)
            results[table] = r[0]['cnt'] if r else 0
        return results

    def check_live_export(self) -> Dict:
        """Check live export freshness."""
        try:
            response = requests.get(
                "https://storage.googleapis.com/nba-props-platform-api/v1/live/today.json",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                updated_at = data.get('updated_at', '')
                if updated_at:
                    # Parse ISO format
                    dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                    age_hours = (datetime.now(dt.tzinfo) - dt).total_seconds() / 3600
                    return {
                        'updated_at': updated_at,
                        'age_hours': round(age_hours, 1),
                        'total_games': data.get('total_games', 0),
                        'status': 'fresh' if age_hours < 4 else 'stale'
                    }
        except Exception as e:
            if self.verbose:
                print(f"  Live export check error: {e}")
        return {'updated_at': 'unknown', 'age_hours': -1, 'status': 'error'}

    def check_circuit_breakers(self) -> List[Dict]:
        """Check for open circuit breakers."""
        query = """
        SELECT processor_name, state, failure_count, last_failure, last_success
        FROM `nba_orchestration.circuit_breaker_state`
        WHERE state = 'OPEN'
        ORDER BY last_failure DESC
        LIMIT 10
        """
        return self.run_query(query)

    def run_health_check(self, target_date: Optional[str] = None) -> Dict:
        """Run comprehensive health check."""
        today, yesterday, tomorrow = get_dates()
        check_date = target_date or yesterday  # Default to yesterday for complete data

        print(f"\nPipeline Health Check - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        print(f"Checking date: {check_date}")
        print(f"Today: {today}, Yesterday: {yesterday}, Tomorrow: {tomorrow}")
        print("-" * 60)

        results = {
            'timestamp': datetime.now().isoformat(),
            'check_date': check_date,
            'checks': {},
            'issues': [],
            'status': 'HEALTHY'
        }

        # 1. Schedule Check (yesterday should be all Final)
        print("\n1. SCHEDULE STATUS")
        schedule_yesterday = self.check_schedule(yesterday)
        schedule_today = self.check_schedule(today)

        yesterday_ok = schedule_yesterday['final_games'] == schedule_yesterday['total_games']
        print(f"   [{check_with_emoji(yesterday_ok)}] Yesterday ({yesterday}): {schedule_yesterday['final_games']}/{schedule_yesterday['total_games']} games Final")
        print(f"   [INFO] Today ({today}): {schedule_today['total_games']} games ({schedule_today['pending_games']} pending)")

        if not yesterday_ok and schedule_yesterday['total_games'] > 0:
            self.issues.append(f"Yesterday has {schedule_yesterday['pending_games']} non-Final games")

        results['checks']['schedule'] = {
            'yesterday': schedule_yesterday,
            'today': schedule_today
        }

        # 2. Player Game Summary (Phase 3)
        print("\n2. PLAYER GAME SUMMARY (Phase 3)")
        pgs_yesterday = self.check_player_game_summary(yesterday)
        pgs_ok = pgs_yesterday > 0
        print(f"   [{check_with_emoji(pgs_ok)}] Yesterday: {pgs_yesterday} records")

        if not pgs_ok and schedule_yesterday['total_games'] > 0:
            self.issues.append("No player_game_summary records for yesterday")

        results['checks']['player_game_summary'] = pgs_yesterday

        # 3. Phase 4 Tables (Precompute)
        print("\n3. PHASE 4 PRECOMPUTE TABLES")
        phase4_today = self.check_phase4_tables(today)
        for table, count in phase4_today.items():
            status = count > 0
            print(f"   [{check_with_emoji(status)}] {table}: {count} records (today)")
            if not status and schedule_today['total_games'] > 0:
                self.issues.append(f"Phase 4 table {table} empty for today")

        results['checks']['phase4_tables'] = phase4_today

        # 4. Predictions
        print("\n4. PREDICTIONS")
        pred_today = self.check_predictions(today)
        pred_tomorrow = self.check_predictions(tomorrow)

        today_ok = pred_today['total'] > 0 or schedule_today['total_games'] == 0
        print(f"   [{check_with_emoji(today_ok)}] Today: {pred_today['total']} predictions for {pred_today['players']} players")
        print(f"   [INFO] Tomorrow: {pred_tomorrow['total']} predictions for {pred_tomorrow['players']} players")

        if not today_ok:
            self.issues.append(f"No predictions for today ({schedule_today['total_games']} games scheduled)")

        results['checks']['predictions'] = {
            'today': pred_today,
            'tomorrow': pred_tomorrow
        }

        # 5. Grading (Prediction Accuracy)
        print("\n5. GRADING (Prediction Accuracy)")
        grading = self.check_prediction_accuracy(yesterday)
        grading_ok = grading['total_records'] > 0 or schedule_yesterday['total_games'] == 0
        print(f"   [{check_with_emoji(grading_ok)}] Yesterday: {grading['total_records']} records, {grading['actionable']} actionable, {grading['win_rate']}% win rate")

        if not grading_ok:
            self.issues.append("No grading records for yesterday")

        results['checks']['grading'] = grading

        # 6. Live Export
        print("\n6. LIVE EXPORT")
        live_export = self.check_live_export()
        export_ok = live_export['status'] == 'fresh' or schedule_today['total_games'] == 0
        print(f"   [{check_with_emoji(export_ok)}] Status: {live_export['status']} ({live_export['age_hours']} hours old)")
        print(f"   [INFO] Updated at: {live_export['updated_at']}")

        if live_export['status'] == 'stale':
            self.issues.append(f"Live export is {live_export['age_hours']} hours old")

        results['checks']['live_export'] = live_export

        # 7. Circuit Breakers
        print("\n7. CIRCUIT BREAKERS")
        open_breakers = self.check_circuit_breakers()
        breakers_ok = len(open_breakers) == 0
        print(f"   [{check_with_emoji(breakers_ok)}] Open circuit breakers: {len(open_breakers)}")
        for breaker in open_breakers:
            print(f"       - {breaker['processor_name']}: {breaker['failure_count']} failures")
            self.issues.append(f"Circuit breaker OPEN: {breaker['processor_name']}")

        results['checks']['circuit_breakers'] = open_breakers

        # Summary
        print("\n" + "=" * 60)
        if self.issues:
            results['status'] = 'UNHEALTHY'
            print(f"STATUS: UNHEALTHY - {len(self.issues)} issue(s) found")
            print("\nISSUES:")
            for i, issue in enumerate(self.issues, 1):
                print(f"  {i}. {issue}")
        else:
            print("STATUS: HEALTHY - All checks passed")

        results['issues'] = self.issues
        print("=" * 60)

        return results


def main():
    parser = argparse.ArgumentParser(description='Check pipeline health')
    parser.add_argument('--date', type=str, help='Specific date to check (YYYY-MM-DD)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    checker = PipelineHealthChecker(verbose=args.verbose)
    results = checker.run_health_check(target_date=args.date)

    if args.json:
        print(json.dumps(results, indent=2, default=str))


if __name__ == '__main__':
    main()
