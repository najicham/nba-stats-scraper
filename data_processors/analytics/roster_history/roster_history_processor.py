#!/usr/bin/env python3
"""
Roster History Processor - Tracks roster changes over time.

This processor creates a historical record of roster changes by:
1. Comparing current roster snapshots with previous day's roster
2. Detecting additions, removals, and status changes
3. Integrating with player movement data for transaction context
4. Maintaining a queryable history for analysis

Output Table: nba_analytics.roster_history
- Records each roster change with date, player, team, change type
- Links to player movement transactions where applicable
- Enables time-series analysis of roster stability

Usage:
    python data_processors/analytics/roster_history/roster_history_processor.py \\
        --date 2026-01-23 \\
        --debug
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client

logger = logging.getLogger(__name__)


class RosterChangeType(Enum):
    """Types of roster changes detected."""
    ADDED = "added"           # New player on roster
    REMOVED = "removed"       # Player no longer on roster
    STATUS_CHANGE = "status_change"  # Status changed (e.g., active -> injured)
    TEAM_CHANGE = "team_change"      # Player traded to different team
    JERSEY_CHANGE = "jersey_change"  # Jersey number changed


@dataclass
class DetectedRosterChange:
    """A detected roster change."""
    change_date: date
    player_lookup: str
    player_full_name: str
    team_abbr: str
    change_type: str
    previous_value: Optional[str]
    new_value: Optional[str]
    from_team: Optional[str] = None
    to_team: Optional[str] = None
    transaction_type: Optional[str] = None
    transaction_description: Optional[str] = None
    season_year: int = 0


class RosterHistoryProcessor:
    """
    Processor that tracks roster changes over time.

    Compares daily roster snapshots to detect:
    - Players added to roster
    - Players removed from roster
    - Status changes (active <-> injured)
    - Team changes (trades)
    """

    def __init__(
        self,
        project_id: str = "nba-props-platform",
        dataset_id: str = "nba_analytics"
    ):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.table_name = "roster_history"
        self.bq_client = get_bigquery_client(project_id)

        # Stats tracking
        self.changes_detected = 0
        self.changes_saved = 0

    def process(self, process_date: date) -> Dict:
        """
        Process roster changes for a specific date.

        Args:
            process_date: Date to process roster changes for

        Returns:
            Dict with processing stats
        """
        logger.info(f"Processing roster history for {process_date}")

        # Get current roster state
        current_roster = self._get_roster_snapshot(process_date)
        logger.info(f"Current roster: {len(current_roster)} players")

        # Get previous day's roster state
        previous_date = process_date - timedelta(days=1)
        previous_roster = self._get_roster_snapshot(previous_date)
        logger.info(f"Previous roster: {len(previous_roster)} players")

        # Detect changes
        changes = self._detect_changes(
            previous_roster,
            current_roster,
            process_date
        )
        logger.info(f"Detected {len(changes)} roster changes")

        # Enrich with transaction data
        enriched_changes = self._enrich_with_transactions(changes, process_date)

        # Save changes
        if enriched_changes:
            self._save_changes(enriched_changes)

        return {
            "process_date": str(process_date),
            "current_roster_size": len(current_roster),
            "previous_roster_size": len(previous_roster),
            "changes_detected": len(changes),
            "changes_saved": len(enriched_changes)
        }

    def _get_roster_snapshot(self, snapshot_date: date) -> Dict[str, Dict]:
        """
        Get roster snapshot for a specific date.

        Returns dict mapping player_lookup to player details.
        """
        query = """
        WITH latest_roster AS (
            SELECT
                player_lookup,
                player_full_name,
                team_abbr,
                jersey_number,
                position,
                status,
                roster_status,
                season_year,
                roster_date,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup, team_abbr
                    ORDER BY roster_date DESC, scrape_hour DESC
                ) as rn
            FROM `{project}.nba_raw.espn_team_rosters`
            WHERE roster_date = @snapshot_date
        )
        SELECT
            player_lookup,
            player_full_name,
            team_abbr,
            jersey_number,
            position,
            status,
            roster_status,
            season_year
        FROM latest_roster
        WHERE rn = 1
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("snapshot_date", "DATE", snapshot_date)
        ])

        try:
            result = self.bq_client.query(query, job_config=job_config).result()

            roster = {}
            for row in result:
                key = f"{row.player_lookup}_{row.team_abbr}"
                roster[key] = {
                    'player_lookup': row.player_lookup,
                    'player_full_name': row.player_full_name,
                    'team_abbr': row.team_abbr,
                    'jersey_number': row.jersey_number,
                    'position': row.position,
                    'status': row.status,
                    'roster_status': row.roster_status,
                    'season_year': row.season_year
                }

            return roster

        except Exception as e:
            logger.error(f"Error fetching roster snapshot for {snapshot_date}: {e}")
            return {}

    def _detect_changes(
        self,
        previous: Dict[str, Dict],
        current: Dict[str, Dict],
        change_date: date
    ) -> List[DetectedRosterChange]:
        """
        Detect changes between two roster snapshots.
        """
        changes = []

        previous_keys = set(previous.keys())
        current_keys = set(current.keys())

        # Players added (in current but not in previous)
        added_keys = current_keys - previous_keys
        for key in added_keys:
            player = current[key]

            # Check if player was on different team yesterday
            # (this would be a trade/team change)
            player_lookup = player['player_lookup']
            prev_team = None
            for pk, pv in previous.items():
                if pv['player_lookup'] == player_lookup:
                    prev_team = pv['team_abbr']
                    break

            if prev_team and prev_team != player['team_abbr']:
                # Team change (trade)
                changes.append(DetectedRosterChange(
                    change_date=change_date,
                    player_lookup=player['player_lookup'],
                    player_full_name=player['player_full_name'],
                    team_abbr=player['team_abbr'],
                    change_type=RosterChangeType.TEAM_CHANGE.value,
                    previous_value=prev_team,
                    new_value=player['team_abbr'],
                    from_team=prev_team,
                    to_team=player['team_abbr'],
                    season_year=player.get('season_year', 0)
                ))
            else:
                # New addition
                changes.append(DetectedRosterChange(
                    change_date=change_date,
                    player_lookup=player['player_lookup'],
                    player_full_name=player['player_full_name'],
                    team_abbr=player['team_abbr'],
                    change_type=RosterChangeType.ADDED.value,
                    previous_value=None,
                    new_value=player['team_abbr'],
                    to_team=player['team_abbr'],
                    season_year=player.get('season_year', 0)
                ))

        # Players removed (in previous but not in current)
        removed_keys = previous_keys - current_keys
        for key in removed_keys:
            player = previous[key]

            # Check if player moved to different team
            player_lookup = player['player_lookup']
            new_team = None
            for ck, cv in current.items():
                if cv['player_lookup'] == player_lookup:
                    new_team = cv['team_abbr']
                    break

            if not new_team:
                # Player completely removed (waived, released, etc.)
                changes.append(DetectedRosterChange(
                    change_date=change_date,
                    player_lookup=player['player_lookup'],
                    player_full_name=player['player_full_name'],
                    team_abbr=player['team_abbr'],
                    change_type=RosterChangeType.REMOVED.value,
                    previous_value=player['team_abbr'],
                    new_value=None,
                    from_team=player['team_abbr'],
                    season_year=player.get('season_year', 0)
                ))

        # Check for status changes (players on both days)
        common_keys = previous_keys & current_keys
        for key in common_keys:
            prev_player = previous[key]
            curr_player = current[key]

            # Status change
            if prev_player.get('status') != curr_player.get('status'):
                changes.append(DetectedRosterChange(
                    change_date=change_date,
                    player_lookup=curr_player['player_lookup'],
                    player_full_name=curr_player['player_full_name'],
                    team_abbr=curr_player['team_abbr'],
                    change_type=RosterChangeType.STATUS_CHANGE.value,
                    previous_value=prev_player.get('status'),
                    new_value=curr_player.get('status'),
                    season_year=curr_player.get('season_year', 0)
                ))

            # Jersey number change
            if (prev_player.get('jersey_number') != curr_player.get('jersey_number')
                    and prev_player.get('jersey_number')
                    and curr_player.get('jersey_number')):
                changes.append(DetectedRosterChange(
                    change_date=change_date,
                    player_lookup=curr_player['player_lookup'],
                    player_full_name=curr_player['player_full_name'],
                    team_abbr=curr_player['team_abbr'],
                    change_type=RosterChangeType.JERSEY_CHANGE.value,
                    previous_value=prev_player.get('jersey_number'),
                    new_value=curr_player.get('jersey_number'),
                    season_year=curr_player.get('season_year', 0)
                ))

        self.changes_detected = len(changes)
        return changes

    def _enrich_with_transactions(
        self,
        changes: List[DetectedRosterChange],
        process_date: date
    ) -> List[DetectedRosterChange]:
        """
        Enrich detected changes with transaction data from player movement.
        """
        if not changes:
            return []

        # Get player lookups for changes
        player_lookups = list(set(c.player_lookup for c in changes))

        # Query recent transactions
        query = """
        SELECT
            player_lookup,
            transaction_type,
            transaction_description,
            team_abbr
        FROM `{project}.nba_raw.nbac_player_movement`
        WHERE player_lookup IN UNNEST(@player_lookups)
          AND transaction_date BETWEEN DATE_SUB(@process_date, INTERVAL 3 DAY) AND @process_date
          AND is_player_transaction = TRUE
        ORDER BY transaction_date DESC
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
            bigquery.ScalarQueryParameter("process_date", "DATE", process_date)
        ])

        try:
            result = self.bq_client.query(query, job_config=job_config).result()

            # Build transaction lookup
            transactions = {}
            for row in result:
                key = row.player_lookup
                if key not in transactions:
                    transactions[key] = {
                        'transaction_type': row.transaction_type,
                        'transaction_description': row.transaction_description
                    }

            # Enrich changes
            for change in changes:
                tx = transactions.get(change.player_lookup)
                if tx:
                    change.transaction_type = tx['transaction_type']
                    change.transaction_description = tx['transaction_description']

            return changes

        except Exception as e:
            logger.warning(f"Error enriching with transactions: {e}")
            return changes

    def _save_changes(self, changes: List[DetectedRosterChange]) -> None:
        """Save detected changes to BigQuery."""
        if not changes:
            return

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"

        # Convert to dicts
        rows = []
        for change in changes:
            row = {
                'change_date': change.change_date.isoformat(),
                'player_lookup': change.player_lookup,
                'player_full_name': change.player_full_name,
                'team_abbr': change.team_abbr,
                'change_type': change.change_type,
                'previous_value': change.previous_value,
                'new_value': change.new_value,
                'from_team': change.from_team,
                'to_team': change.to_team,
                'transaction_type': change.transaction_type,
                'transaction_description': change.transaction_description,
                'season_year': change.season_year,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            rows.append(row)

        try:
            # Use batch loading
            job_config = bigquery.LoadJobConfig(
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                schema=[
                    bigquery.SchemaField("change_date", "DATE"),
                    bigquery.SchemaField("player_lookup", "STRING"),
                    bigquery.SchemaField("player_full_name", "STRING"),
                    bigquery.SchemaField("team_abbr", "STRING"),
                    bigquery.SchemaField("change_type", "STRING"),
                    bigquery.SchemaField("previous_value", "STRING"),
                    bigquery.SchemaField("new_value", "STRING"),
                    bigquery.SchemaField("from_team", "STRING"),
                    bigquery.SchemaField("to_team", "STRING"),
                    bigquery.SchemaField("transaction_type", "STRING"),
                    bigquery.SchemaField("transaction_description", "STRING"),
                    bigquery.SchemaField("season_year", "INTEGER"),
                    bigquery.SchemaField("created_at", "TIMESTAMP"),
                ]
            )

            load_job = self.bq_client.load_table_from_json(
                rows, table_id, job_config=job_config
            )
            load_job.result(timeout=60)

            self.changes_saved = len(rows)
            logger.info(f"Saved {len(rows)} roster changes to {table_id}")

        except Exception as e:
            logger.error(f"Error saving roster changes: {e}")
            raise

    def get_roster_history(
        self,
        player_lookup: Optional[str] = None,
        team_abbr: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        change_types: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Query roster history with optional filters.

        Args:
            player_lookup: Filter by player
            team_abbr: Filter by team
            start_date: Start of date range
            end_date: End of date range
            change_types: Filter by change type(s)

        Returns:
            List of roster change records
        """
        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"

        query = f"SELECT * FROM `{table_id}` WHERE 1=1"
        params = []

        if player_lookup:
            query += " AND player_lookup = @player_lookup"
            params.append(bigquery.ScalarQueryParameter(
                "player_lookup", "STRING", player_lookup
            ))

        if team_abbr:
            query += " AND (team_abbr = @team_abbr OR from_team = @team_abbr OR to_team = @team_abbr)"
            params.append(bigquery.ScalarQueryParameter(
                "team_abbr", "STRING", team_abbr
            ))

        if start_date:
            query += " AND change_date >= @start_date"
            params.append(bigquery.ScalarQueryParameter(
                "start_date", "DATE", start_date
            ))

        if end_date:
            query += " AND change_date <= @end_date"
            params.append(bigquery.ScalarQueryParameter(
                "end_date", "DATE", end_date
            ))

        if change_types:
            query += " AND change_type IN UNNEST(@change_types)"
            params.append(bigquery.ArrayQueryParameter(
                "change_types", "STRING", change_types
            ))

        query += " ORDER BY change_date DESC"

        job_config = bigquery.QueryJobConfig(query_parameters=params)

        try:
            result = self.bq_client.query(query, job_config=job_config).result()
            return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Error querying roster history: {e}")
            return []


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Process roster history and track changes"
    )
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="Date to process (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--project-id",
        default="nba-props-platform",
        help="GCP project ID"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Parse date
    process_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    # Process
    processor = RosterHistoryProcessor(project_id=args.project_id)
    stats = processor.process(process_date)

    print(f"\n{'='*60}")
    print("Roster History Processing Complete")
    print(f"{'='*60}")
    print(f"Date: {stats['process_date']}")
    print(f"Current roster size: {stats['current_roster_size']}")
    print(f"Previous roster size: {stats['previous_roster_size']}")
    print(f"Changes detected: {stats['changes_detected']}")
    print(f"Changes saved: {stats['changes_saved']}")
    print(f"{'='*60}")
