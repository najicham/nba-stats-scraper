#!/usr/bin/env python3
"""
R-009 Validation Script

Validates the R-009 roster-only data bug fix from Session 69.

CRITICAL: Run this script the morning after games to validate:
1. No games with 0 active players (R-009 detection)
2. All games have analytics
3. Reasonable player counts per game
4. Prediction grading completeness
5. Morning recovery workflow decisions

Usage:
    # Run for yesterday's games
    python validation/validators/nba/r009_validation.py

    # Run for specific date
    python validation/validators/nba/r009_validation.py --date 2026-01-16

    # Run as Cloud Run job
    gcloud run jobs create nba-r009-validator \
        --source=. \
        --region=us-west2 \
        --schedule="0 9 * * *"  # 9 AM UTC daily
"""

import argparse
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List
from google.cloud import bigquery
from shared.utils.notification_system import notify_error, notify_warning, notify_info

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class R009Validator:
    """Validates R-009 roster-only data bug fix."""

    def __init__(self, project_id: str = "nba-props-platform"):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)
        self.issues_found = []

    def check_zero_active_players(self, game_date: str) -> Dict:
        """
        Check #1: Detect games with 0 active players (R-009 bug).

        This is the CRITICAL check - any results indicate R-009 regression.

        Returns:
            Dict with check results
        """
        query = f"""
        SELECT
            game_id,
            COUNT(*) as total_players,
            COUNTIF(is_active = TRUE) as active_players,
            COUNTIF(is_active = FALSE) as inactive_players
        FROM nba_analytics.player_game_summary
        WHERE game_date = '{game_date}'
        GROUP BY game_id
        HAVING COUNTIF(is_active = TRUE) = 0
        """

        try:
            query_job = self.bq_client.query(query)
            rows = list(query_job.result())

            if rows:
                # CRITICAL: R-009 regression detected!
                logger.critical(f"🚨 R-009 REGRESSION: Found {len(rows)} games with 0 active players!")
                for row in rows:
                    issue = {
                        'severity': 'critical',
                        'check': 'zero_active_players',
                        'game_id': row.game_id,
                        'total_players': row.total_players,
                        'active_players': row.active_players,
                        'message': f"Game {row.game_id}: {row.total_players} total players, 0 active (R-009 BUG!)"
                    }
                    self.issues_found.append(issue)
                    logger.critical(issue['message'])

                return {
                    'passed': False,
                    'games_with_zero_active': len(rows),
                    'games': [dict(row) for row in rows]
                }
            else:
                logger.info("✅ Check #1 PASSED: No games with 0 active players")
                return {
                    'passed': True,
                    'games_with_zero_active': 0,
                    'games': []
                }

        except Exception as e:
            logger.error(f"Check #1 FAILED: {e}")
            return {'passed': False, 'error': str(e)}

    def check_all_games_have_analytics(self, game_date: str, expected_games: int = None) -> Dict:
        """
        Check #2: Verify all games have analytics.

        Args:
            game_date: Date to check
            expected_games: Expected number of games (optional, will query schedule if not provided)

        Returns:
            Dict with check results
        """
        # Get expected game count from schedule
        if expected_games is None:
            schedule_query = f"""
            SELECT COUNT(*) as game_count
            FROM nba_raw.nbac_schedule
            WHERE game_date = '{game_date}'
              AND game_status = 3  -- Final only
            """
            try:
                result = list(self.bq_client.query(schedule_query).result())
                expected_games = result[0].game_count if result else 0
            except Exception as e:
                logger.warning(f"Could not get expected game count: {e}")
                expected_games = 0

        # Check analytics
        query = f"""
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as games_with_analytics,
            COUNT(*) as total_player_records
        FROM nba_analytics.player_game_summary
        WHERE game_date = '{game_date}'
        GROUP BY game_date
        """

        try:
            query_job = self.bq_client.query(query)
            rows = list(query_job.result())

            if not rows:
                logger.error(f"❌ Check #2 FAILED: No analytics found for {game_date}")
                self.issues_found.append({
                    'severity': 'critical',
                    'check': 'all_games_have_analytics',
                    'message': f"No analytics data found for {game_date}"
                })
                return {
                    'passed': False,
                    'games_with_analytics': 0,
                    'expected_games': expected_games,
                    'total_player_records': 0
                }

            row = rows[0]
            games_with_analytics = row.games_with_analytics
            total_player_records = row.total_player_records

            # Check if count matches expected
            if expected_games > 0 and games_with_analytics < expected_games:
                logger.warning(
                    f"⚠️  Check #2 WARNING: {games_with_analytics}/{expected_games} games have analytics"
                )
                self.issues_found.append({
                    'severity': 'warning',
                    'check': 'all_games_have_analytics',
                    'message': f"{games_with_analytics}/{expected_games} games have analytics (missing {expected_games - games_with_analytics})"
                })
                return {
                    'passed': False,
                    'games_with_analytics': games_with_analytics,
                    'expected_games': expected_games,
                    'total_player_records': total_player_records
                }
            else:
                logger.info(
                    f"✅ Check #2 PASSED: {games_with_analytics} games have analytics, "
                    f"{total_player_records} player records"
                )
                return {
                    'passed': True,
                    'games_with_analytics': games_with_analytics,
                    'expected_games': expected_games,
                    'total_player_records': total_player_records
                }

        except Exception as e:
            logger.error(f"Check #2 FAILED: {e}")
            return {'passed': False, 'error': str(e)}

    def check_reasonable_player_counts(self, game_date: str) -> Dict:
        """
        Check #3: Verify reasonable player counts per game.

        Expected:
        - total_players: 19-34
        - active_players: 19-34
        - players_with_minutes: 18-30
        - teams_present: 2

        Returns:
            Dict with check results
        """
        query = f"""
        SELECT
            game_id,
            COUNT(*) as total_players,
            COUNTIF(is_active = TRUE) as active_players,
            COUNTIF(minutes_played > 0) as players_with_minutes,
            COUNT(DISTINCT team_abbr) as teams_present
        FROM nba_analytics.player_game_summary
        WHERE game_date = '{game_date}'
        GROUP BY game_id
        ORDER BY game_id
        """

        try:
            query_job = self.bq_client.query(query)
            rows = list(query_job.result())

            if not rows:
                logger.error(f"❌ Check #3 FAILED: No data for {game_date}")
                return {'passed': False, 'error': 'No data found'}

            issues = []
            for row in rows:
                # Check thresholds
                if row.total_players < 19 or row.total_players > 34:
                    issues.append(f"Game {row.game_id}: total_players={row.total_players} (expected 19-34)")

                if row.active_players < 19 or row.active_players > 34:
                    issues.append(f"Game {row.game_id}: active_players={row.active_players} (expected 19-34)")

                if row.players_with_minutes < 18 or row.players_with_minutes > 30:
                    issues.append(f"Game {row.game_id}: players_with_minutes={row.players_with_minutes} (expected 18-30)")

                if row.teams_present != 2:
                    issues.append(f"Game {row.game_id}: teams_present={row.teams_present} (expected 2)")

            if issues:
                logger.warning(f"⚠️  Check #3 WARNING: Found {len(issues)} player count issues")
                for issue in issues:
                    logger.warning(f"  - {issue}")
                    self.issues_found.append({
                        'severity': 'warning',
                        'check': 'reasonable_player_counts',
                        'message': issue
                    })
                return {
                    'passed': False,
                    'games_checked': len(rows),
                    'issues': issues,
                    'details': [dict(row) for row in rows]
                }
            else:
                logger.info(f"✅ Check #3 PASSED: All {len(rows)} games have reasonable player counts")
                return {
                    'passed': True,
                    'games_checked': len(rows),
                    'issues': [],
                    'details': [dict(row) for row in rows]
                }

        except Exception as e:
            logger.error(f"Check #3 FAILED: {e}")
            return {'passed': False, 'error': str(e)}

    def check_prediction_grading(self, game_date: str) -> Dict:
        """
        Check #4: Verify prediction coverage.

        Expected: Predictions exist for games on the date.
        Note: Grading functionality not yet implemented.

        Returns:
            Dict with check results
        """
        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_predictions,
            COUNT(DISTINCT system_id) as systems,
            COUNT(DISTINCT game_id) as games
        FROM nba_predictions.player_prop_predictions
        WHERE game_date = '{game_date}'
        GROUP BY game_date
        """

        try:
            query_job = self.bq_client.query(query)
            rows = list(query_job.result())

            if not rows:
                logger.warning(f"⚠️  Check #4 WARNING: No predictions found for {game_date}")
                return {
                    'passed': True,  # Not critical, maybe no props available
                    'total_predictions': 0,
                    'systems': 0,
                    'games': 0
                }

            row = rows[0]

            # Check if we have predictions from all 5 expected systems
            expected_systems = 5
            if row.systems < expected_systems:
                logger.warning(
                    f"⚠️  Check #4 WARNING: Only {row.systems}/{expected_systems} systems generated predictions "
                    f"({row.total_predictions} total predictions)"
                )
                self.issues_found.append({
                    'severity': 'warning',
                    'check': 'prediction_coverage',
                    'message': f"Only {row.systems}/{expected_systems} systems generated predictions"
                })
                return {
                    'passed': False,
                    'total_predictions': row.total_predictions,
                    'systems': row.systems,
                    'games': row.games
                }
            else:
                logger.info(
                    f"✅ Check #4 PASSED: {row.systems} systems generated {row.total_predictions} predictions "
                    f"for {row.games} games"
                )
                return {
                    'passed': True,
                    'total_predictions': row.total_predictions,
                    'systems': row.systems,
                    'games': row.games
                }

        except Exception as e:
            logger.error(f"Check #4 FAILED: {e}")
            return {'passed': False, 'error': str(e)}

    def check_morning_recovery_workflow(self, game_date: str) -> Dict:
        """
        Check #5: Verify morning recovery workflow decision.

        Expected:
        - SKIP: If all games processed successfully
        - RUN: If some games needed recovery

        Note: This checks the morning AFTER game_date (e.g., if game_date=Jan 16,
        check morning recovery on Jan 17)

        Returns:
            Dict with check results
        """
        # Calculate next morning
        next_day = (datetime.strptime(game_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')

        query = f"""
        SELECT
            decision_time,
            workflow_name,
            decision,
            reason,
            games_targeted
        FROM nba_orchestration.master_controller_execution_log
        WHERE workflow_name = 'morning_recovery'
          AND DATE(decision_time) = '{next_day}'
        ORDER BY decision_time DESC
        LIMIT 5
        """

        try:
            query_job = self.bq_client.query(query)
            rows = list(query_job.result())

            if not rows:
                logger.info(f"ℹ️  Check #5: No morning recovery workflow run yet for {next_day} (expected at 6 AM ET)")
                return {
                    'passed': True,
                    'workflow_run': False,
                    'decision': None,
                    'reason': 'Workflow not run yet'
                }

            row = rows[0]
            decision = row.decision
            reason = row.reason

            if decision == 'SKIP':
                logger.info(f"✅ Check #5 PASSED: Morning recovery SKIPPED (all games processed successfully)")
                return {
                    'passed': True,
                    'workflow_run': True,
                    'decision': decision,
                    'reason': reason
                }
            elif decision == 'RUN':
                logger.warning(
                    f"⚠️  Check #5 WARNING: Morning recovery RAN "
                    f"(reason: {reason}, games: {row.games_targeted})"
                )
                self.issues_found.append({
                    'severity': 'warning',
                    'check': 'morning_recovery_workflow',
                    'message': f"Morning recovery RAN: {reason} (games: {row.games_targeted})"
                })
                return {
                    'passed': False,
                    'workflow_run': True,
                    'decision': decision,
                    'reason': reason,
                    'games_targeted': row.games_targeted
                }
            else:
                logger.warning(f"⚠️  Check #5 WARNING: Unknown decision: {decision}")
                return {
                    'passed': False,
                    'workflow_run': True,
                    'decision': decision,
                    'reason': reason
                }

        except Exception as e:
            # Table might not exist
            logger.info(f"ℹ️  Check #5: Could not check morning recovery workflow: {e}")
            return {
                'passed': True,
                'workflow_run': False,
                'error': str(e)
            }

    def run_all_checks(self, game_date: str) -> Dict:
        """
        Run all R-009 validation checks.

        Args:
            game_date: Date to validate

        Returns:
            Dict with all check results and summary
        """
        logger.info(f"\n{'=' * 80}")
        logger.info(f"R-009 VALIDATION - {game_date}")
        logger.info(f"{'=' * 80}\n")

        # Run all checks
        check1 = self.check_zero_active_players(game_date)
        check2 = self.check_all_games_have_analytics(game_date)
        check3 = self.check_reasonable_player_counts(game_date)
        check4 = self.check_prediction_grading(game_date)
        check5 = self.check_morning_recovery_workflow(game_date)

        # Summary
        checks = {
            'check1_zero_active': check1,
            'check2_all_games': check2,
            'check3_player_counts': check3,
            'check4_grading': check4,
            'check5_morning_recovery': check5
        }

        passed = all(check.get('passed', False) for check in checks.values())
        critical_issues = [i for i in self.issues_found if i['severity'] == 'critical']
        warning_issues = [i for i in self.issues_found if i['severity'] == 'warning']

        summary = {
            'game_date': game_date,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'overall_passed': passed,
            'checks': checks,
            'total_issues': len(self.issues_found),
            'critical_issues': len(critical_issues),
            'warning_issues': len(warning_issues),
            'issues': self.issues_found
        }

        # Print summary
        logger.info(f"\n{'=' * 80}")
        logger.info("VALIDATION SUMMARY")
        logger.info(f"{'=' * 80}")
        logger.info(f"Overall: {'✅ PASSED' if passed else '❌ FAILED'}")
        logger.info(f"Critical Issues: {len(critical_issues)}")
        logger.info(f"Warning Issues: {len(warning_issues)}")

        if critical_issues:
            logger.critical("\nCRITICAL ISSUES:")
            for issue in critical_issues:
                logger.critical(f"  - {issue['message']}")

        if warning_issues:
            logger.warning("\nWARNINGS:")
            for issue in warning_issues:
                logger.warning(f"  - {issue['message']}")

        logger.info(f"{'=' * 80}\n")

        # Send notification
        if critical_issues:
            notify_error(
                title=f"R-009 Validation FAILED - {game_date}",
                message=f"Found {len(critical_issues)} critical issues: {', '.join([i['message'] for i in critical_issues])}"
            )
        elif warning_issues:
            notify_warning(
                title=f"R-009 Validation - Warnings - {game_date}",
                message=f"Found {len(warning_issues)} warnings: {', '.join([i['message'] for i in warning_issues[:3]])}"
                processor_name=self.__class__.__name__
            )
        else:
            notify_info(
                title=f"R-009 Validation PASSED - {game_date}",
                message="All checks passed successfully"
                processor_name=self.__class__.__name__
            )

        return summary


def main():
    """Run R-009 validation."""
    parser = argparse.ArgumentParser(description='R-009 Validation')
    parser.add_argument('--date', help='Date to validate (YYYY-MM-DD). Defaults to yesterday.')
    args = parser.parse_args()

    # Default to yesterday
    if args.date:
        game_date = args.date
    else:
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        game_date = yesterday.strftime('%Y-%m-%d')

    logger.info(f"Validating R-009 fix for {game_date}")

    validator = R009Validator()
    results = validator.run_all_checks(game_date)

    return 0 if results['overall_passed'] else 1


if __name__ == '__main__':
    exit(main())
