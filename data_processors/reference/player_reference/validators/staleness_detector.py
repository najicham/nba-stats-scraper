"""
Staleness Detector

Checks if NBA.com canonical data is stale and should be skipped for validation.
Uses 1-day staleness threshold - if data is >1 day old, validation is skipped.
"""

import logging
from datetime import date
from typing import Dict, Set, Tuple

import pandas as pd
from google.cloud import bigquery

from shared.utils.notification_system import notify_warning

logger = logging.getLogger(__name__)


class StalenessDetector:
    """
    Detects staleness in NBA.com source data.

    Staleness Threshold: 1 day
    - If NBA.com data is >1 day old, skip validation and process ESPN-only
    - Fresh data (<= 1 day) enables full validation
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str, table_name: str):
        """
        Initialize staleness detector.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
            table_name: Registry table name
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.table_name = table_name

    def get_canonical_set_with_staleness_check(
        self,
        season_year: int,
        data_date: date,
        season_str: str
    ) -> Tuple[Set[Tuple[str, str]], Dict]:
        """
        Get canonical (player, team) combinations from NBA.com with staleness checking.

        Args:
            season_year: NBA season starting year
            data_date: Date being processed
            season_str: Season string (e.g., "2024-2025")

        Returns:
            Tuple of (canonical_set, validation_info_dict)
            - canonical_set: Set of (player_lookup, team_abbr) tuples
            - validation_info: Dict with validation mode and staleness details
        """
        canonical_combos = set()
        nba_players_found = False

        # Get NBA.com players with freshness check
        nba_query = """
        SELECT DISTINCT
            player_lookup,
            team_abbr,
            player_full_name as display_name,
            MAX(source_file_date) as latest_scrape_date
        FROM `{project}.nba_raw.nbac_player_list_current`
        WHERE is_active = TRUE
        AND season_year = @season_year
        GROUP BY player_lookup, team_abbr, player_full_name
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])

        latest_scrape_date = None
        staleness_days = None

        try:
            nba_current = self.bq_client.query(nba_query, job_config=job_config).to_dataframe()

            if not nba_current.empty:
                latest_scrape_date = pd.to_datetime(nba_current['latest_scrape_date']).max()
                if isinstance(latest_scrape_date, pd.Timestamp):
                    latest_scrape_date = latest_scrape_date.date()

                staleness_days = (data_date - latest_scrape_date).days

                logger.info(f"NBA.com data latest scrape: {latest_scrape_date} ({staleness_days} days old)")

                # STALENESS CHECK: Threshold is 1 day
                if staleness_days > 1:
                    logger.warning(f"⚠️ NBA.com data is {staleness_days} days stale - SKIPPING VALIDATION")

                    try:
                        notify_warning(
                            title="Stale NBA.com Canonical Data",
                            message=f"NBA.com data is {staleness_days} days old ({latest_scrape_date})",
                            details={
                                'latest_scrape_date': str(latest_scrape_date),
                                'data_date': str(data_date),
                                'staleness_days': staleness_days,
                                'threshold_days': 1,
                                'action': 'Skipping validation - processing ESPN-only',
                                'recommendation': 'Check NBA.com scraper status',
                                'processor': 'roster_registry'
                            },
                            processor_name=self.__class__.__name__
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send notification: {e}")

                    return set(), {
                        'validation_mode': 'none',
                        'validation_skipped_reason': 'nbacom_stale',
                        'source_data_freshness_days': staleness_days
                    }

                # Fresh data
                for _, row in nba_current.iterrows():
                    canonical_combos.add((row['player_lookup'], row['team_abbr']))
                nba_players_found = True
                logger.info(f"Loaded {len(canonical_combos)} player-team combinations from NBA.com (fresh data)")

            else:
                logger.warning("NBA.com current scrape returned no players")

        except Exception as e:
            logger.warning(f"Error loading NBA.com current players: {e}")

        # Get from existing registry
        registry_nba_query = """
        SELECT DISTINCT
            player_lookup,
            team_abbr,
            player_name as display_name
        FROM `{project}.{table_name}`
        WHERE season = @season
        AND source_priority = 'roster_nba_com'
        """.format(project=self.project_id, table_name=self.table_name)

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season", "STRING", season_str)
        ])

        try:
            registry_nba = self.bq_client.query(registry_nba_query, job_config=job_config).to_dataframe()
            if not registry_nba.empty:
                original_count = len(canonical_combos)
                for _, row in registry_nba.iterrows():
                    canonical_combos.add((row['player_lookup'], row['team_abbr']))
                nba_players_found = True
                logger.info(f"Added {len(canonical_combos) - original_count} from registry (total: {len(canonical_combos)})")
        except Exception as e:
            logger.warning(f"Error loading registry NBA.com players: {e}")

        # FALLBACK
        if not nba_players_found or len(canonical_combos) == 0:
            logger.warning("⚠️ NBA.com data unavailable - falling back to existing registry (all sources)")

            fallback_query = """
            SELECT DISTINCT
                player_lookup,
                team_abbr
            FROM `{project}.{table_name}`
            WHERE season = @season
            """.format(project=self.project_id, table_name=self.table_name)

            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("season", "STRING", season_str)
            ])

            try:
                all_registry = self.bq_client.query(fallback_query, job_config=job_config).to_dataframe()
                if not all_registry.empty:
                    for _, row in all_registry.iterrows():
                        canonical_combos.add((row['player_lookup'], row['team_abbr']))
                    logger.warning(f"Using fallback: {len(canonical_combos)} player-team combinations from all sources")

                    try:
                        notify_warning(
                            title="Roster Processor Using Fallback Mode",
                            message=f"NBA.com unavailable - using registry as canonical ({len(canonical_combos)} combinations)",
                            details={
                                'season': season_str,
                                'canonical_combos_count': len(canonical_combos),
                                'fallback_mode': True,
                                'processor': 'roster_registry'
                            },
                            processor_name=self.__class__.__name__
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send notification: {e}")

                    return canonical_combos, {
                        'validation_mode': 'partial',
                        'validation_skipped_reason': 'nbacom_unavailable',
                        'source_data_freshness_days': None
                    }
            except Exception as e:
                logger.error(f"Error loading fallback registry data: {e}")

        return canonical_combos, {
            'validation_mode': 'full',
            'validation_skipped_reason': None,
            'source_data_freshness_days': staleness_days
        }
