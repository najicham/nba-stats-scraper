#!/usr/bin/env python3
"""
Cross-Source Data Validator

Compares player box score data across multiple sources to ensure data quality.
Stores discrepancies in BigQuery and sends Slack alerts for significant issues.

Sources compared:
- NBA.com Gamebook (primary/authoritative)
- Basketball Reference (backup)
- BDL API (disabled but monitored)

Usage:
    python bin/monitoring/cross_source_validator.py [--date YYYY-MM-DD] [--dry-run]

Created: 2026-01-28
Purpose: Ensure data integrity across multiple sources
"""

import argparse
import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Thresholds for alerting
MINUTES_DIFF_THRESHOLD = 3  # Alert if minutes differ by more than 3
POINTS_DIFF_THRESHOLD = 2   # Alert if points differ by more than 2
COVERAGE_THRESHOLD = 90     # Alert if backup source has <90% coverage


class CrossSourceValidator:
    """
    Validates data consistency across multiple NBA data sources.
    """

    def __init__(self, project_id: str = None):
        self.project_id = project_id or os.environ.get('GCP_PROJECT', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        self.discrepancies = []
        self.stats = {
            'players_compared': 0,
            'exact_matches': 0,
            'minor_discrepancies': 0,
            'major_discrepancies': 0,
            'missing_in_backup': 0
        }

    def compare_sources(self, game_date: str) -> Dict:
        """
        Compare all sources for a given date.

        Returns dict with comparison results and discrepancies.
        """
        logger.info(f"Comparing sources for {game_date}")

        # Get data from each source
        primary_data = self._get_primary_data(game_date)
        bref_data = self._get_bref_data(game_date)
        bdl_data = self._get_bdl_data(game_date)
        nba_api_data = self._get_nba_api_data(game_date)

        if not primary_data:
            logger.warning(f"No primary data found for {game_date}")
            return {'error': 'No primary data', 'game_date': game_date}

        # Compare primary vs each backup
        bref_comparison = self._compare_datasets(
            primary_data, bref_data, 'basketball_reference', game_date
        )
        bdl_comparison = self._compare_datasets(
            primary_data, bdl_data, 'bdl', game_date
        )
        nba_api_comparison = self._compare_datasets(
            primary_data, nba_api_data, 'nba_api', game_date
        )

        return {
            'game_date': game_date,
            'primary_count': len(primary_data),
            'bref_comparison': bref_comparison,
            'bdl_comparison': bdl_comparison,
            'nba_api_comparison': nba_api_comparison,
            'discrepancies': self.discrepancies,
            'stats': self.stats
        }

    def _get_primary_data(self, game_date: str) -> Dict[str, Dict]:
        """Get primary source data (NBA.com gamebook) keyed by player_lookup."""
        query = f"""
        SELECT
            player_lookup,
            player_name,
            SAFE_CAST(REGEXP_EXTRACT(minutes, r'^([0-9]+)') AS INT64) as minutes_played,
            points,
            assists,
            COALESCE(offensive_rebounds, 0) + COALESCE(defensive_rebounds, 0) as total_rebounds,
            steals,
            blocks,
            turnovers,
            field_goals_made as fg_made,
            field_goals_attempted as fg_attempted,
            three_pointers_made as three_pt_made,
            three_pointers_attempted as three_pt_attempted,
            free_throws_made as ft_made,
            free_throws_attempted as ft_attempted
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date = '{game_date}'
          AND player_status = 'active'
        """
        return self._query_to_dict(query)

    def _get_bref_data(self, game_date: str) -> Dict[str, Dict]:
        """Get Basketball Reference data keyed by player_lookup."""
        query = f"""
        SELECT
            player_lookup,
            player_name,
            minutes_played,
            points,
            assists,
            total_rebounds,
            steals,
            blocks,
            turnovers,
            fg_made,
            fg_attempted,
            three_pt_made,
            three_pt_attempted,
            ft_made,
            ft_attempted
        FROM `{self.project_id}.nba_raw.bref_player_boxscores`
        WHERE game_date = '{game_date}'
        """
        return self._query_to_dict(query)

    def _get_bdl_data(self, game_date: str) -> Dict[str, Dict]:
        """Get BDL data keyed by player_lookup."""
        query = f"""
        SELECT
            player_lookup,
            player_full_name as player_name,
            SAFE_CAST(minutes AS INT64) as minutes_played,
            points,
            assists,
            rebounds as total_rebounds,
            steals,
            blocks,
            turnovers,
            field_goals_made as fg_made,
            field_goals_attempted as fg_attempted,
            three_pointers_made as three_pt_made,
            three_pointers_attempted as three_pt_attempted,
            free_throws_made as ft_made,
            free_throws_attempted as ft_attempted
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE game_date = '{game_date}'
        """
        return self._query_to_dict(query)

    def _get_nba_api_data(self, game_date: str) -> Dict[str, Dict]:
        """Get NBA API BoxScoreTraditionalV3 data keyed by player_lookup."""
        query = f"""
        SELECT
            player_lookup,
            player_name,
            minutes_played,
            points,
            assists,
            total_rebounds,
            steals,
            blocks,
            turnovers,
            fg_made,
            fg_attempted,
            three_pt_made,
            three_pt_attempted,
            ft_made,
            ft_attempted
        FROM `{self.project_id}.nba_raw.nba_api_player_boxscores`
        WHERE game_date = '{game_date}'
        """
        return self._query_to_dict(query)

    def _query_to_dict(self, query: str) -> Dict[str, Dict]:
        """Execute query and return results keyed by player_lookup."""
        try:
            result = self.bq_client.query(query).result()
            return {row['player_lookup']: dict(row) for row in result}
        except Exception as e:
            logger.warning(f"Query failed: {e}")
            return {}

    def _compare_datasets(
        self,
        primary: Dict[str, Dict],
        backup: Dict[str, Dict],
        backup_name: str,
        game_date: str
    ) -> Dict:
        """Compare primary dataset against a backup source."""

        if not backup:
            return {
                'source': backup_name,
                'coverage': 0,
                'coverage_pct': 0,
                'exact_matches': 0,
                'discrepancies': 0,
                'status': 'NO_DATA'
            }

        exact_matches = 0
        discrepancies_found = 0
        covered = 0

        for player_lookup, primary_player in primary.items():
            self.stats['players_compared'] += 1

            # Skip DNP players
            if not primary_player.get('minutes_played') or primary_player['minutes_played'] == 0:
                continue

            backup_player = backup.get(player_lookup)

            if not backup_player:
                self.stats['missing_in_backup'] += 1
                continue

            covered += 1

            # Compare key stats
            discrepancy = self._check_discrepancy(
                primary_player, backup_player, backup_name, game_date
            )

            if discrepancy:
                discrepancies_found += 1
                self.discrepancies.append(discrepancy)

                if discrepancy['severity'] == 'major':
                    self.stats['major_discrepancies'] += 1
                else:
                    self.stats['minor_discrepancies'] += 1
            else:
                exact_matches += 1
                self.stats['exact_matches'] += 1

        active_players = sum(
            1 for p in primary.values()
            if p.get('minutes_played') and p['minutes_played'] > 0
        )

        coverage_pct = round(100 * covered / active_players, 1) if active_players > 0 else 0

        return {
            'source': backup_name,
            'coverage': covered,
            'coverage_pct': coverage_pct,
            'active_players': active_players,
            'exact_matches': exact_matches,
            'discrepancies': discrepancies_found,
            'status': 'OK' if coverage_pct >= COVERAGE_THRESHOLD else 'LOW_COVERAGE'
        }

    def _check_discrepancy(
        self,
        primary: Dict,
        backup: Dict,
        source: str,
        game_date: str
    ) -> Optional[Dict]:
        """Check for discrepancies between primary and backup data."""

        diffs = {}

        # Check minutes
        p_min = primary.get('minutes_played') or 0
        b_min = backup.get('minutes_played') or 0
        if abs(p_min - b_min) > 0:
            diffs['minutes'] = {'primary': p_min, 'backup': b_min, 'diff': abs(p_min - b_min)}

        # Check points
        p_pts = primary.get('points') or 0
        b_pts = backup.get('points') or 0
        if abs(p_pts - b_pts) > 0:
            diffs['points'] = {'primary': p_pts, 'backup': b_pts, 'diff': abs(p_pts - b_pts)}

        # Check other stats
        for stat in ['assists', 'total_rebounds', 'steals', 'blocks']:
            p_val = primary.get(stat) or 0
            b_val = backup.get(stat) or 0
            if abs(p_val - b_val) > 0:
                diffs[stat] = {'primary': p_val, 'backup': b_val, 'diff': abs(p_val - b_val)}

        if not diffs:
            return None

        # Determine severity
        minutes_diff = diffs.get('minutes', {}).get('diff', 0)
        points_diff = diffs.get('points', {}).get('diff', 0)

        if minutes_diff > MINUTES_DIFF_THRESHOLD or points_diff > POINTS_DIFF_THRESHOLD:
            severity = 'major'
        else:
            severity = 'minor'

        return {
            'game_date': game_date,
            'player_lookup': primary.get('player_lookup'),
            'player_name': primary.get('player_name'),
            'backup_source': source,
            'severity': severity,
            'discrepancies': diffs,
            'detected_at': datetime.utcnow().isoformat()
        }

    def save_discrepancies(self) -> bool:
        """Save discrepancies to BigQuery for tracking."""
        if not self.discrepancies:
            logger.info("No discrepancies to save")
            return True

        table_id = f"{self.project_id}.nba_orchestration.source_discrepancies"

        # Flatten discrepancies for BigQuery
        rows = []
        for d in self.discrepancies:
            rows.append({
                'game_date': d['game_date'],
                'player_lookup': d['player_lookup'],
                'player_name': d['player_name'],
                'backup_source': d['backup_source'],
                'severity': d['severity'],
                'discrepancies_json': json.dumps(d['discrepancies']),
                'detected_at': d['detected_at']
            })

        try:
            errors = self.bq_client.insert_rows_json(table_id, rows)
            if errors:
                logger.error(f"Failed to save discrepancies: {errors[:3]}")
                return False
            logger.info(f"Saved {len(rows)} discrepancies to BigQuery")
            return True
        except Exception as e:
            logger.error(f"Error saving discrepancies: {e}")
            return False

    def send_alert(self, results: Dict) -> bool:
        """Send Slack alert if there are significant issues."""
        webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
        if not webhook_url:
            logger.warning("SLACK_WEBHOOK_URL not set, skipping alert")
            return False

        # Determine if we need to alert
        major_count = self.stats.get('major_discrepancies', 0)
        bref_status = results.get('bref_comparison', {}).get('status', 'UNKNOWN')

        if major_count == 0 and bref_status == 'OK':
            logger.info("No issues to alert on")
            return False

        # Build alert
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": ":mag: Source Data Validation Alert"}
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Date:* {results['game_date']}\n*Primary records:* {results['primary_count']}"
                }
            }
        ]

        # Add Basketball Reference status
        bref = results.get('bref_comparison', {})
        if bref:
            status_emoji = ":white_check_mark:" if bref.get('status') == 'OK' else ":warning:"
            blocks.append({
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Basketball Reference:*\n{status_emoji} {bref.get('status', 'N/A')}"},
                    {"type": "mrkdwn", "text": f"*Coverage:*\n{bref.get('coverage_pct', 0)}%"},
                    {"type": "mrkdwn", "text": f"*Exact Matches:*\n{bref.get('exact_matches', 0)}"},
                    {"type": "mrkdwn", "text": f"*Discrepancies:*\n{bref.get('discrepancies', 0)}"}
                ]
            })

        # Add major discrepancy details
        if major_count > 0:
            major_examples = [d for d in self.discrepancies if d['severity'] == 'major'][:3]
            examples_text = "\n".join([
                f"• {d['player_name']}: {', '.join(f'{k}={v}' for k,v in d['discrepancies'].items())}"
                for d in major_examples
            ])
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Major Discrepancies ({major_count} total):*\n{examples_text}"}
            })

        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": ":information_source: Primary source (NBA.com) is authoritative. Discrepancies are logged for investigation."
            }]
        })

        payload = {"attachments": [{"color": "#FF9900" if major_count > 0 else "#36A64F", "blocks": blocks}]}

        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Alert sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description='Cross-source data validator')
    parser.add_argument('--date', type=str, help='Date to validate (default: yesterday)')
    parser.add_argument('--dry-run', action='store_true', help='Do not save or alert')
    parser.add_argument('--no-alert', action='store_true', help='Do not send Slack alert')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    check_date = args.date or (date.today() - timedelta(days=1)).isoformat()

    validator = CrossSourceValidator()
    results = validator.compare_sources(check_date)

    print(f"\n{'='*60}")
    print(f"Cross-Source Validation Report - {check_date}")
    print(f"{'='*60}")
    print(f"\nPrimary records: {results.get('primary_count', 0)}")

    for source in ['bref_comparison', 'nba_api_comparison', 'bdl_comparison']:
        comp = results.get(source, {})
        if comp:
            print(f"\n{comp.get('source', 'Unknown').upper()}:")
            print(f"  Status: {comp.get('status', 'N/A')}")
            print(f"  Coverage: {comp.get('coverage', 0)}/{comp.get('active_players', 0)} ({comp.get('coverage_pct', 0)}%)")
            print(f"  Exact matches: {comp.get('exact_matches', 0)}")
            print(f"  Discrepancies: {comp.get('discrepancies', 0)}")

    print(f"\nStats: {validator.stats}")

    if not args.dry_run:
        validator.save_discrepancies()
        if not args.no_alert:
            validator.send_alert(results)
    else:
        print("\n[DRY RUN] Would save discrepancies and send alerts")


if __name__ == '__main__':
    main()
