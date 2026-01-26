"""
Registry Operations

Handles CRUD operations for roster registry data:
- Querying existing registry players
- Inserting aliases
- Inserting/updating unresolved names
- Creating unvalidated player records
"""

import logging
from datetime import date, datetime
from typing import Dict, List, Set

import pandas as pd
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError

from shared.utils.notification_system import notify_error

logger = logging.getLogger(__name__)


class RegistryOperations:
    """
    CRUD operations for roster registry data.

    Handles database interactions for:
    - Player registry queries
    - Alias management
    - Unresolved name tracking
    """

    def __init__(
        self,
        bq_client: bigquery.Client,
        project_id: str,
        table_name: str,
        alias_table_name: str,
        unresolved_table_name: str,
        calculate_season_string_fn
    ):
        """
        Initialize registry operations handler.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
            table_name: Main registry table name
            alias_table_name: Player aliases table name
            unresolved_table_name: Unresolved names table name
            calculate_season_string_fn: Function to calculate season string from year
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.table_name = table_name
        self.alias_table_name = alias_table_name
        self.unresolved_table_name = unresolved_table_name
        self.calculate_season_string = calculate_season_string_fn

    def get_existing_registry_players(self, season: str) -> Set[str]:
        """
        Get players already in registry for current season.

        Args:
            season: Season string (e.g., "2024-2025")

        Returns:
            Set of player_lookup values
        """
        query = """
        SELECT DISTINCT player_lookup
        FROM `{project}.{table_name}`
        WHERE season = @season
        """.format(project=self.project_id, table_name=self.table_name)

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season", "STRING", season)
        ])

        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            existing_players = set(results['player_lookup'].unique()) if not results.empty else set()
            logger.info(f"Found {len(existing_players)} existing players in registry for {season}")
            return existing_players
        except GoogleAPIError as e:
            logger.warning(f"Error querying existing registry players: {e}")
            try:
                notify_error(
                    title="Registry Query Failed",
                    message=f"Failed to query existing registry players: {str(e)}",
                    details={
                        'season': season,
                        'error_type': type(e).__name__,
                        'processor': 'roster_registry'
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return set()

    def create_unvalidated_records(self, unvalidated_players: List[Dict], season_year: int) -> None:
        """
        Create unresolved records for players not in NBA.com canonical set.

        Args:
            unvalidated_players: List of player dicts with source, display_name, player_lookup, team_abbr
            season_year: NBA season starting year
        """
        unresolved_records = []

        source_map = {
            'espn_rosters': 'espn',
            'basketball_reference': 'br',
            'nba_player_list': 'nba_com'
        }

        for player in unvalidated_players:
            source_name = source_map.get(player['source'], player['source'])

            unresolved_records.append({
                'source': source_name,
                'original_name': player['display_name'],
                'normalized_lookup': player['player_lookup'],
                'first_seen_date': date.today(),
                'last_seen_date': date.today(),
                'team_abbr': player['team_abbr'],
                'season': self.calculate_season_string(season_year),
                'occurrences': 1,
                'example_games': [],
                'status': 'pending',
                'resolution_type': None,
                'resolved_to_name': None,
                'notes': f"Found in {player['source']} but not in NBA.com canonical set",
                'reviewed_by': None,
                'reviewed_at': None,
                'created_at': datetime.now(),
                'processed_at': datetime.now()
            })

        if unresolved_records:
            try:
                self.insert_unresolved_names(unresolved_records)
                logger.info(f"Created {len(unresolved_records)} unresolved records")
            except Exception as e:
                logger.error(f"Failed to create unvalidated player records: {e}")

    def insert_aliases(self, alias_records: List[Dict], convert_pandas_types_fn) -> None:
        """
        Insert alias records into player_aliases table.

        Args:
            alias_records: List of alias record dicts
            convert_pandas_types_fn: Function to convert pandas types for JSON
        """
        if not alias_records:
            return

        table_id = f"{self.project_id}.{self.alias_table_name}"

        try:
            existing_query = f"""
            SELECT alias_lookup
            FROM `{table_id}`
            WHERE alias_lookup IN UNNEST(@alias_lookups)
            """

            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ArrayQueryParameter("alias_lookups", "STRING",
                    [r['alias_lookup'] for r in alias_records])
            ])

            existing_df = self.bq_client.query(existing_query, job_config=job_config).to_dataframe()
            existing_aliases = set(existing_df['alias_lookup']) if not existing_df.empty else set()

            new_aliases = [r for r in alias_records if r['alias_lookup'] not in existing_aliases]

            if not new_aliases:
                return

            processed_aliases = []
            for r in new_aliases:
                converted = convert_pandas_types_fn(r)
                if 'is_active' in converted:
                    converted['is_active'] = bool(converted['is_active'])
                processed_aliases.append(converted)

            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            # Use batch loading instead of streaming inserts
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See: docs/05-development/guides/bigquery-best-practices.md
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(processed_aliases, table_id, job_config=job_config)
            load_job.result(timeout=60)

            if load_job.errors:
                logger.error(f"Aliases load had errors: {load_job.errors[:3]}")
            else:
                logger.info(f"Successfully inserted {len(new_aliases)} new aliases")

        except Exception as e:
            logger.error(f"Failed to insert aliases: {e}")

    def insert_unresolved_names(self, unresolved_records: List[Dict], convert_pandas_types_fn=None) -> None:
        """
        Insert unresolved player name records.

        Args:
            unresolved_records: List of unresolved player record dicts
            convert_pandas_types_fn: Optional function to convert pandas types for JSON
        """
        if not unresolved_records:
            return

        if not isinstance(unresolved_records, list):
            unresolved_records = list(unresolved_records)

        table_id = f"{self.project_id}.{self.unresolved_table_name}"

        try:
            existing_query = f"""
            SELECT normalized_lookup, team_abbr, season, occurrences
            FROM `{table_id}`
            WHERE normalized_lookup IN UNNEST(@lookups)
            AND status = 'pending'
            """

            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ArrayQueryParameter("lookups", "STRING",
                    [r['normalized_lookup'] for r in unresolved_records])
            ])

            existing_df = self.bq_client.query(existing_query, job_config=job_config).to_dataframe()

            existing_map = {}
            if len(existing_df) > 0:
                for _, row in existing_df.iterrows():
                    key = (row['normalized_lookup'], row['team_abbr'], row['season'])
                    existing_map[key] = row['occurrences']

            new_unresolved = []
            updates_needed = []

            for r in unresolved_records:
                key = (r['normalized_lookup'], r['team_abbr'], r['season'])

                if key in existing_map:
                    updates_needed.append({
                        'normalized_lookup': r['normalized_lookup'],
                        'team_abbr': r['team_abbr'],
                        'season': r['season'],
                        'new_occurrences': existing_map[key] + 1,
                        'last_seen_date': r['last_seen_date']
                    })
                else:
                    new_unresolved.append(r)

            if len(new_unresolved) > 0:
                processed_unresolved = []
                for r in new_unresolved:
                    if convert_pandas_types_fn:
                        converted = convert_pandas_types_fn(r)
                    else:
                        converted = r.copy()

                    if 'example_games' in converted:
                        eg = converted['example_games']
                        if eg is None:
                            converted['example_games'] = []
                        elif not isinstance(eg, list):
                            converted['example_games'] = list(eg) if hasattr(eg, '__iter__') else []
                    processed_unresolved.append(converted)

                # Get table reference for schema
                table_ref = self.bq_client.get_table(table_id)

                # Use batch loading instead of streaming inserts
                # This avoids the 90-minute streaming buffer that blocks DML operations
                # See: docs/05-development/guides/bigquery-best-practices.md
                job_config = bigquery.LoadJobConfig(
                    schema=table_ref.schema,
                    autodetect=False,
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    ignore_unknown_values=True
                )

                load_job = self.bq_client.load_table_from_json(processed_unresolved, table_id, job_config=job_config)
                load_job.result(timeout=60)

                if load_job.errors:
                    logger.error(f"Unresolved names load had errors: {load_job.errors[:3]}")
                else:
                    logger.info(f"Inserted {len(new_unresolved)} new unresolved records")

            if len(updates_needed) > 0:
                successful_updates = 0
                for update in updates_needed:
                    update_query = f"""
                    UPDATE `{table_id}`
                    SET
                        occurrences = @new_occurrences,
                        last_seen_date = @last_seen_date,
                        processed_at = CURRENT_TIMESTAMP()
                    WHERE normalized_lookup = @normalized_lookup
                    AND team_abbr = @team_abbr
                    AND season = @season
                    AND status = 'pending'
                    """

                    job_config = bigquery.QueryJobConfig(query_parameters=[
                        bigquery.ScalarQueryParameter("normalized_lookup", "STRING", update['normalized_lookup']),
                        bigquery.ScalarQueryParameter("team_abbr", "STRING", update['team_abbr']),
                        bigquery.ScalarQueryParameter("season", "STRING", update['season']),
                        bigquery.ScalarQueryParameter("new_occurrences", "INT64", update['new_occurrences']),
                        bigquery.ScalarQueryParameter("last_seen_date", "DATE", update['last_seen_date'])
                    ])

                    try:
                        self.bq_client.query(update_query, job_config=job_config).result(timeout=60)
                        successful_updates += 1
                    except Exception as e:
                        if 'streaming buffer' in str(e).lower():
                            logger.debug(f"Skipping UPDATE for {update['normalized_lookup']} - streaming buffer")
                        else:
                            logger.warning(f"Failed to update {update['normalized_lookup']}: {e}")

                if successful_updates > 0:
                    logger.info(f"Updated {successful_updates} existing unresolved records")

        except Exception as e:
            logger.error(f"Failed to insert/update unresolved: {e}")
