#!/usr/bin/env python3
"""
FILE: scripts/validate_tonight_data.py

Comprehensive validation script for tonight's game data.
Checks each stage of the pipeline and reports issues.

Run after 2 PM ET to verify tonight's predictions are ready.

Usage:
    python scripts/validate_tonight_data.py [--date YYYY-MM-DD]
"""

import sys
import os
import argparse
from datetime import date, datetime, timezone
from typing import Dict, List, Tuple
from collections import defaultdict

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from google.cloud import bigquery


class TonightDataValidator:
    """Validates all data required for tonight's predictions."""

    def __init__(self, target_date: date):
        self.target_date = target_date
        self.client = bigquery.Client()
        self.project = self.client.project
        self.issues: List[Dict] = []
        self.warnings: List[Dict] = []
        self.stats: Dict = {}

    def add_issue(self, stage: str, message: str, severity: str = "ERROR"):
        self.issues.append({
            'stage': stage,
            'message': message,
            'severity': severity
        })

    def add_warning(self, stage: str, message: str):
        self.warnings.append({
            'stage': stage,
            'message': message
        })

    def check_schedule(self) -> int:
        """Check that schedule data exists for target date."""
        query = f"""
        SELECT
            COUNT(*) as game_count,
            ARRAY_AGG(DISTINCT home_team_tricode) as home_teams,
            ARRAY_AGG(DISTINCT away_team_tricode) as away_teams
        FROM `{self.project}.nba_raw.nbac_schedule`
        WHERE game_date = '{self.target_date}'
        """
        result = list(self.client.query(query).result(timeout=60))[0]

        game_count = result.game_count
        self.stats['scheduled_games'] = game_count

        if game_count == 0:
            self.add_issue('schedule', f'No games scheduled for {self.target_date}')
            return 0

        # Collect all teams
        all_teams = set(result.home_teams or []) | set(result.away_teams or [])
        self.stats['scheduled_teams'] = sorted(all_teams)

        print(f"✓ Schedule: {game_count} games, {len(all_teams)} teams")
        return game_count

    def check_roster_freshness(self) -> bool:
        """Check that roster data is recent."""
        query = f"""
        SELECT
            MAX(roster_date) as latest_date,
            COUNT(DISTINCT team_abbr) as team_count
        FROM `{self.project}.nba_raw.espn_team_rosters`
        WHERE roster_date >= DATE_SUB('{self.target_date}', INTERVAL 7 DAY)
        """
        result = list(self.client.query(query).result(timeout=60))[0]

        latest_date = result.latest_date
        team_count = result.team_count

        self.stats['roster_date'] = str(latest_date) if latest_date else None
        self.stats['roster_teams'] = team_count

        if not latest_date:
            self.add_issue('roster', 'No roster data in last 7 days!')
            return False

        days_old = (self.target_date - latest_date).days
        if days_old > 1:
            self.add_warning('roster', f'Roster data is {days_old} days old')

        if team_count < 30:
            self.add_warning('roster', f'Only {team_count}/30 teams have roster data')

        print(f"✓ Roster: {team_count} teams, last updated {latest_date}")
        return True

    def check_game_context(self) -> Dict[str, List[str]]:
        """Check game context coverage for each game."""
        query = f"""
        SELECT
            s.game_id,
            s.home_team_tricode as expected_home,
            s.away_team_tricode as expected_away,
            ARRAY_AGG(DISTINCT gc.team_abbr IGNORE NULLS) as actual_teams,
            COUNT(DISTINCT gc.player_lookup) as player_count
        FROM `{self.project}.nba_raw.nbac_schedule` s
        LEFT JOIN `{self.project}.nba_analytics.upcoming_player_game_context` gc
            ON s.game_id = gc.game_id AND gc.game_date = '{self.target_date}'
        WHERE s.game_date = '{self.target_date}'
        GROUP BY s.game_id, s.home_team_tricode, s.away_team_tricode
        ORDER BY s.game_id
        """
        results = list(self.client.query(query).result(timeout=60))

        missing_teams_by_game = {}
        for row in results:
            expected = {row.expected_home, row.expected_away}
            actual = set(row.actual_teams or [])
            missing = expected - actual

            if missing:
                game = f"{row.expected_away}@{row.expected_home}"
                missing_teams_by_game[game] = list(missing)
                self.add_issue('game_context',
                    f'{game}: Missing teams {missing}, only have {actual}')

            if row.player_count == 0:
                game = f"{row.expected_away}@{row.expected_home}"
                self.add_issue('game_context',
                    f'{game}: No players in game_context!')

        total_players = sum(r.player_count for r in results)
        self.stats['game_context_players'] = total_players

        games_with_issues = len(missing_teams_by_game)
        if games_with_issues == 0:
            print(f"✓ Game Context: All games have both teams, {total_players} total players")
        else:
            print(f"✗ Game Context: {games_with_issues} games missing teams")

        return missing_teams_by_game

    def check_predictions(self) -> Tuple[int, int]:
        """Check predictions exist and aren't duplicated."""
        # Check for predictions
        query = f"""
        SELECT
            COUNT(*) as total_rows,
            COUNT(DISTINCT player_lookup) as unique_players,
            COUNT(DISTINCT game_id) as games
        FROM `{self.project}.nba_predictions.player_prop_predictions`
        WHERE game_date = '{self.target_date}'
          AND system_id = 'ensemble_v1'
          AND is_active = TRUE
        """
        result = list(self.client.query(query).result(timeout=60))[0]

        total_rows = result.total_rows
        unique_players = result.unique_players
        games = result.games

        self.stats['prediction_rows'] = total_rows
        self.stats['prediction_players'] = unique_players
        self.stats['prediction_games'] = games

        if total_rows == 0:
            self.add_issue('predictions', f'No predictions for {self.target_date}')
            return 0, 0

        # Check for duplicates
        if total_rows > unique_players:
            dup_ratio = total_rows / unique_players
            self.add_issue('predictions',
                f'Duplicate predictions: {total_rows} rows for {unique_players} players ({dup_ratio:.1f}x)')

        print(f"✓ Predictions: {unique_players} players, {games} games ({total_rows} rows)")
        return unique_players, total_rows

    def check_betting_data(self) -> Tuple[int, int]:
        """
        Check betting data from Odds API with timing awareness.

        Checks odds_api_player_points_props and odds_api_game_lines tables.
        Uses workflow timing to distinguish between "not started yet" and "failed".

        Returns:
            (props_count, lines_count) tuple
        """
        from datetime import datetime, timezone

        # Get game times for timing awareness
        game_times_query = f"""
        SELECT game_date_est
        FROM `{self.project}.nba_raw.nbac_schedule`
        WHERE game_date = '{self.target_date}'
        """
        try:
            game_results = list(self.client.query(game_times_query).result(timeout=30))
            game_times = [datetime.fromisoformat(str(r.game_date_est)) for r in game_results if r.game_date_est]
        except Exception as e:
            self.add_warning('betting_data', f'Could not get game times for workflow timing check: {e}')
            game_times = []

        # Check props data
        props_query = f"""
        SELECT
            COUNT(*) as total_props,
            COUNT(DISTINCT game_id) as games_with_props
        FROM `{self.project}.nba_raw.odds_api_player_points_props`
        WHERE game_date = '{self.target_date}'
        """
        props_result = list(self.client.query(props_query).result(timeout=60))[0]
        props_count = props_result.total_props
        props_games = props_result.games_with_props

        # Check lines data
        lines_query = f"""
        SELECT
            COUNT(*) as total_lines,
            COUNT(DISTINCT game_id) as games_with_lines
        FROM `{self.project}.nba_raw.odds_api_game_lines`
        WHERE game_date = '{self.target_date}'
        """
        lines_result = list(self.client.query(lines_query).result(timeout=60))[0]
        lines_count = lines_result.total_lines
        lines_games = lines_result.games_with_lines

        self.stats['betting_props_count'] = props_count
        self.stats['betting_props_games'] = props_games
        self.stats['betting_lines_count'] = lines_count
        self.stats['betting_lines_games'] = lines_games

        # Use workflow timing awareness
        if game_times:
            try:
                # Import timing utilities
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
                from orchestration.workflow_timing import get_workflow_status_message

                current_time = datetime.now(timezone.utc)

                # Check props status
                props_status, props_message = get_workflow_status_message(
                    'betting_lines',
                    current_time,
                    game_times,
                    props_count > 0
                )

                if props_status == 'TOO_EARLY':
                    print(f"ℹ️ Betting Props: {props_message}")
                elif props_status == 'WITHIN_LAG':
                    print(f"⏳ Betting Props: {props_message}")
                elif props_status == 'FAILURE':
                    self.add_issue('betting_data', f'Betting Props: {props_message}')
                    print(f"✗ Betting Props: No data found (workflow should have run)")
                else:  # DATA_FOUND or UNKNOWN
                    print(f"✓ Betting Props: {props_count} records, {props_games} games")

                # Check lines status
                lines_status, lines_message = get_workflow_status_message(
                    'betting_lines',
                    current_time,
                    game_times,
                    lines_count > 0
                )

                if lines_status == 'TOO_EARLY':
                    print(f"ℹ️ Betting Lines: {lines_message}")
                elif lines_status == 'WITHIN_LAG':
                    print(f"⏳ Betting Lines: {lines_message}")
                elif lines_status == 'FAILURE':
                    self.add_issue('betting_data', f'Betting Lines: {lines_message}')
                    print(f"✗ Betting Lines: No data found (workflow should have run)")
                else:  # DATA_FOUND or UNKNOWN
                    print(f"✓ Betting Lines: {lines_count} records, {lines_games} games")

            except Exception as e:
                # Fallback to simple check if timing utilities fail
                self.add_warning('betting_data', f'Could not check workflow timing: {e}')
                if props_count == 0:
                    self.add_warning('betting_data', 'No betting props data found')
                else:
                    print(f"✓ Betting Props: {props_count} records, {props_games} games")

                if lines_count == 0:
                    self.add_warning('betting_data', 'No betting lines data found')
                else:
                    print(f"✓ Betting Lines: {lines_count} records, {lines_games} games")
        else:
            # No game times available, simple check
            if props_count == 0:
                self.add_warning('betting_data', 'No betting props data found')
            else:
                print(f"✓ Betting Props: {props_count} records, {props_games} games")

            if lines_count == 0:
                self.add_warning('betting_data', 'No betting lines data found')
            else:
                print(f"✓ Betting Lines: {lines_count} records, {lines_games} games")

        return props_count, lines_count

    def check_prop_lines(self) -> int:
        """Check prop lines exist from BettingPros (legacy source)."""
        query = f"""
        SELECT
            COUNT(DISTINCT player_lookup) as players_with_lines
        FROM `{self.project}.nba_raw.bettingpros_player_points_props`
        WHERE game_date = '{self.target_date}'
          AND is_active = TRUE
        """
        result = list(self.client.query(query).result(timeout=60))[0]

        players = result.players_with_lines
        self.stats['players_with_lines'] = players

        if players == 0:
            self.add_warning('prop_lines', 'No prop lines from BettingPros (legacy source)')
        else:
            print(f"✓ Prop Lines (BettingPros): {players} players have betting lines")

        return players

    def check_tonight_api(self) -> bool:
        """Check tonight's API file exists and is fresh."""
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket('nba-props-platform-api')
        blob = bucket.blob('v1/tonight/all-players.json')

        if not blob.exists():
            self.add_issue('api_export', 'Tonight API file does not exist!')
            return False

        blob.reload()
        updated = blob.updated

        # Check if file is from today
        if updated.date() != self.target_date:
            self.add_warning('api_export',
                f'API file last updated {updated}, not today')

        # Parse and check content
        import json
        content = blob.download_as_text()
        data = json.loads(content)

        api_date = data.get('game_date')
        total_players = data.get('total_players', 0)
        games = len(data.get('games', []))

        self.stats['api_date'] = api_date
        self.stats['api_players'] = total_players
        self.stats['api_games'] = games

        if api_date != str(self.target_date):
            self.add_issue('api_export',
                f'API has wrong date: {api_date} (expected {self.target_date})')
            return False

        # Check for issues in API
        for game in data.get('games', []):
            if len(game.get('players', [])) == 0:
                matchup = f"{game.get('away_team')}@{game.get('home_team')}"
                self.add_issue('api_export', f'{matchup}: No players in export')

        print(f"✓ Tonight API: {total_players} players, {games} games, updated {updated}")
        return True

    def check_player_game_summary_quality(self) -> bool:
        """
        Check data quality in player_game_summary table.

        Validates:
        - minutes_played NULL rate <10%
        - usage_rate NULL rate <10% for active players
        - source_team_last_updated timestamp exists
        - Coverage comparison to previous day

        Added 2026-01-25 to prevent Nov 2025 data quality issues.
        """
        from datetime import timedelta

        # Check yesterday's data (today's data may not exist yet)
        check_date = self.target_date - timedelta(days=1)

        query = f"""
        WITH data_quality AS (
            SELECT
                COUNT(*) as total_records,
                COUNTIF(minutes_played IS NOT NULL) as has_minutes,
                COUNTIF(usage_rate IS NOT NULL) as has_usage_rate,
                COUNTIF(source_team_last_updated IS NOT NULL) as has_team_join,
                ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / NULLIF(COUNT(*), 0), 1) as minutes_pct,
                ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / NULLIF(COUNT(*), 0), 1) as usage_rate_pct,
                -- For active players only (minutes > 0)
                COUNTIF(minutes_played > 0) as active_players,
                COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) as active_with_usage,
                ROUND(100.0 * COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) / NULLIF(COUNTIF(minutes_played > 0), 0), 1) as active_usage_pct
            FROM `{self.project}.nba_analytics.player_game_summary`
            WHERE game_date = '{check_date}'
        )
        SELECT * FROM data_quality
        """

        try:
            result = list(self.client.query(query).result(timeout=60))[0]
        except Exception as e:
            self.add_issue('data_quality', f'Failed to check player_game_summary quality: {e}')
            return False

        total = result.total_records
        minutes_pct = result.minutes_pct or 0
        usage_rate_pct = result.usage_rate_pct or 0
        active_usage_pct = result.active_usage_pct or 0
        has_team_join = result.has_team_join or 0

        self.stats['pgs_date_checked'] = str(check_date)
        self.stats['pgs_total_records'] = total
        self.stats['pgs_minutes_pct'] = minutes_pct
        self.stats['pgs_usage_rate_pct'] = usage_rate_pct
        self.stats['pgs_active_usage_pct'] = active_usage_pct

        # Check if data exists
        if total == 0:
            self.add_warning('data_quality', f'No player_game_summary data for {check_date}')
            return False

        # Critical thresholds
        MINUTES_THRESHOLD = 90.0  # Alert if <90% have minutes_played
        USAGE_THRESHOLD = 90.0    # Alert if <90% of active players have usage_rate

        # Check minutes_played coverage
        if minutes_pct < MINUTES_THRESHOLD:
            self.add_issue('data_quality',
                f'minutes_played coverage is {minutes_pct}% (threshold: {MINUTES_THRESHOLD}%) for {check_date}',
                severity='CRITICAL')

        # Check usage_rate coverage for active players
        if active_usage_pct < USAGE_THRESHOLD:
            self.add_issue('data_quality',
                f'usage_rate coverage is {active_usage_pct}% for active players (threshold: {USAGE_THRESHOLD}%) for {check_date}',
                severity='CRITICAL')

        # Check team stats join
        if has_team_join == 0:
            self.add_warning('data_quality',
                f'No team stats join detected (source_team_last_updated all NULL) for {check_date}')

        # Print status
        status_icon = '✓' if minutes_pct >= MINUTES_THRESHOLD and active_usage_pct >= USAGE_THRESHOLD else '⚠️'
        print(f"{status_icon} Data Quality ({check_date}):")
        print(f"   - {total} player-game records")
        print(f"   - minutes_played: {minutes_pct}% coverage")
        print(f"   - usage_rate: {active_usage_pct}% for active players")
        print(f"   - Team stats joined: {'Yes' if has_team_join > 0 else 'No'}")

        return minutes_pct >= MINUTES_THRESHOLD and active_usage_pct >= USAGE_THRESHOLD

    def check_scraper_registry_vs_workflows(self) -> List[str]:
        """Check for scrapers in registry but not in workflows."""
        import yaml

        # Read workflows
        workflows_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'workflows.yaml')
        with open(workflows_path) as f:
            workflows = yaml.safe_load(f)

        # Get all scraper names from workflows
        workflow_scrapers = set()
        for scraper_name, config in workflows.get('scrapers', {}).items():
            workflow_scrapers.add(scraper_name)

        # Get all scrapers from registry
        registry_path = os.path.join(os.path.dirname(__file__), '..', 'scrapers', 'registry.py')
        with open(registry_path) as f:
            content = f.read()

        # Parse registry (simple extraction)
        import re
        registry_scrapers = set(re.findall(r'"(\w+)":\s*\(', content))

        # Find scrapers in registry but not workflows
        unscheduled = registry_scrapers - workflow_scrapers

        # Filter out known exceptions (scrapers that are intentionally not scheduled)
        known_exceptions = {'test_scraper', 'mock_scraper'}
        unscheduled = unscheduled - known_exceptions

        if unscheduled:
            for scraper in sorted(unscheduled):
                self.add_warning('scraper_config',
                    f'Scraper "{scraper}" in registry but not in workflows.yaml')

        return list(unscheduled)

    def run_spot_checks(self, sample_size: int = 5) -> bool:
        """
        Run spot checks on data accuracy.

        Samples random player-date combinations from recent days and verifies
        calculations are correct. This helps detect data quality issues early.

        Args:
            sample_size: Number of random samples to check (default: 5)

        Returns:
            True if accuracy is >= 95%, False otherwise
        """
        from datetime import timedelta

        # Import spot check functions
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        try:
            from spot_check_data_accuracy import (
                get_random_samples,
                run_spot_check
            )
        except ImportError as e:
            self.add_warning('spot_check', f'Could not import spot check module: {e}')
            return True  # Don't fail validation if spot check unavailable

        # Sample from last 7 days (excluding today)
        end_date = self.target_date - timedelta(days=1)
        start_date = end_date - timedelta(days=7)

        try:
            # Get random samples
            samples = get_random_samples(self.client, start_date, end_date, sample_size)

            if not samples:
                self.add_warning('spot_check', f'No data found for spot checking in range {start_date} to {end_date}')
                return True

            # Run spot checks with core checks only (faster)
            checks_to_run = ['rolling_avg', 'usage_rate']

            all_results = []
            for player_lookup, universal_player_id, game_date in samples:
                result = run_spot_check(
                    self.client,
                    player_lookup,
                    universal_player_id,
                    game_date,
                    checks_to_run,
                    verbose=False
                )
                all_results.append(result)

            # Calculate accuracy
            total_passed = sum(r['passed_count'] for r in all_results)
            total_failed = sum(r['failed_count'] for r in all_results)
            total_checks = total_passed + total_failed

            if total_checks == 0:
                self.add_warning('spot_check', 'No checks could be performed (insufficient data)')
                return True

            accuracy_pct = total_passed / total_checks * 100

            self.stats['spot_check_samples'] = len(samples)
            self.stats['spot_check_accuracy'] = f'{accuracy_pct:.1f}%'
            self.stats['spot_check_passed'] = total_passed
            self.stats['spot_check_failed'] = total_failed

            # Report results
            if accuracy_pct >= 95.0:
                print(f"✓ Spot Checks: {accuracy_pct:.1f}% accuracy ({total_passed}/{total_checks} checks passed)")
                return True
            else:
                print(f"⚠️ Spot Checks: {accuracy_pct:.1f}% accuracy ({total_passed}/{total_checks} checks passed)")
                self.add_warning('spot_check',
                    f'Spot check accuracy is {accuracy_pct:.1f}% (threshold: 95%)')

                # Report specific failures
                failures = [r for r in all_results if r['overall_status'] == 'FAIL']
                for result in failures[:3]:  # Show first 3 failures
                    failed_checks = [c['check_name'] for c in result['checks'] if c['status'] == 'FAIL']
                    self.add_warning('spot_check',
                        f'{result["player_lookup"]} ({result["game_date"]}): Failed {", ".join(failed_checks)}')

                return accuracy_pct >= 95.0

        except Exception as e:
            self.add_warning('spot_check', f'Spot check failed with error: {e}')
            return True  # Don't fail validation on spot check errors

    def run_all_checks(self) -> bool:
        """Run all validation checks."""
        print(f"\n{'='*60}")
        print(f"TONIGHT'S DATA VALIDATION - {self.target_date}")
        print(f"{'='*60}\n")

        # Run each check
        game_count = self.check_schedule()
        if game_count == 0:
            print("\n⚠️ No games today - skipping remaining checks")
            return True

        print()
        self.check_roster_freshness()
        print()
        self.check_betting_data()  # NEW: Check Odds API betting data with timing awareness
        print()
        self.check_game_context()
        print()
        self.check_player_game_summary_quality()
        print()
        self.check_predictions()
        print()
        self.check_prop_lines()
        print()
        self.check_tonight_api()
        print()
        self.check_scraper_registry_vs_workflows()
        print()
        self.run_spot_checks(sample_size=5)

        # Print summary
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")

        if self.issues:
            print(f"\n❌ {len(self.issues)} ISSUES FOUND:")
            for issue in self.issues:
                print(f"  [{issue['stage']}] {issue['message']}")

        if self.warnings:
            print(f"\n⚠️ {len(self.warnings)} WARNINGS:")
            for warning in self.warnings:
                print(f"  [{warning['stage']}] {warning['message']}")

        if not self.issues and not self.warnings:
            print("\n✅ All checks passed!")

        print(f"\n{'='*60}\n")

        return len(self.issues) == 0


def main():
    parser = argparse.ArgumentParser(description='Validate tonight\'s game data')
    parser.add_argument('--date', type=str, help='Target date (YYYY-MM-DD), default: today')
    args = parser.parse_args()

    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        target_date = date.today()

    validator = TonightDataValidator(target_date)
    success = validator.run_all_checks()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
