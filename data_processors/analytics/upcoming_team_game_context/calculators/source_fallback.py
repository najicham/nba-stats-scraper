"""
Source Fallback - Dual-Source Fallback Logic

Handles fallback from primary source (nbac_schedule) to secondary source (espn_scoreboard).

Extracted from upcoming_team_game_context_processor.py for maintainability.
"""

import logging
import pandas as pd
from datetime import date, timedelta
from typing import List, Optional
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class SourceFallback:
    """
    Fallback handler for schedule data sources.

    Primary: nbac_schedule
    Fallback: espn_scoreboard
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize the source fallback handler.

        Args:
            bq_client: BigQuery client
            project_id: GCP project ID
        """
        self.bq_client = bq_client
        self.project_id = project_id

    def extract_schedule_data(
        self,
        start_date: date,
        end_date: date,
        log_quality_issue_fn
    ) -> Optional[pd.DataFrame]:
        """
        Extract schedule data with extended lookback window.

        Strategy:
        1. Try primary source (nbac_schedule)
        2. If gaps found, backfill from ESPN scoreboard
        3. Use extended window (30 days before, 7 days after)

        Args:
            start_date: Start of target date range
            end_date: End of target date range
            log_quality_issue_fn: Function to log quality issues

        Returns:
            DataFrame with schedule data or None if extraction fails
        """

        # Ensure dates are date objects, not strings (defensive conversion)
        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)

        # Extended window for context calculations
        extended_start = start_date - timedelta(days=30)  # 30-day lookback
        extended_end = end_date + timedelta(days=7)       # 7-day lookahead

        logger.info(f"Extracting schedule: {extended_start} to {extended_end}")

        # Primary source: nbac_schedule
        query = f"""
        SELECT
            game_id,
            game_date,
            season_year,
            home_team_tricode as home_team_abbr,
            away_team_tricode as away_team_abbr,
            game_status,
            home_team_score,
            away_team_score,
            winning_team_tricode as winning_team_abbr,
            data_source,
            processed_at
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date BETWEEN '{extended_start}' AND '{extended_end}'
          AND game_status IN (1, 3)  -- Scheduled or Final
        ORDER BY game_date, game_id
        """

        try:
            schedule_df = self.bq_client.query(query).to_dataframe()

            if len(schedule_df) == 0:
                logger.warning("nbac_schedule returned 0 rows")
                return None

            logger.info(f"Primary source (nbac_schedule): {len(schedule_df)} games")

            # Ensure game_date is datetime type for .dt accessor
            # Force conversion regardless of dtype (BQ can return various types)
            schedule_df['game_date'] = pd.to_datetime(schedule_df['game_date'])

            # Check for gaps in target date range
            dates_found = set(schedule_df['game_date'].dt.date.unique())
            dates_needed = set(pd.date_range(start_date, end_date).date)
            missing_dates = dates_needed - dates_found

            if missing_dates:
                logger.warning(f"Found {len(missing_dates)} missing dates in schedule")
                logger.info(f"Missing dates: {sorted(missing_dates)}")

                # Attempt ESPN fallback
                espn_df = self.extract_espn_fallback(list(missing_dates))

                if espn_df is not None and len(espn_df) > 0:
                    logger.info(f"ESPN fallback: {len(espn_df)} games")
                    schedule_df = pd.concat([schedule_df, espn_df], ignore_index=True)
                    logger.info(f"Combined total: {len(schedule_df)} games")

            return schedule_df

        except Exception as e:
            logger.error(f"Error extracting schedule data: {e}")
            log_quality_issue_fn(
                severity='ERROR',
                category='EXTRACTION_FAILED',
                message=f"Schedule extraction failed: {str(e)}",
                details={'error_type': type(e).__name__}
            )
            return None

    def extract_espn_fallback(self, missing_dates: List[date]) -> Optional[pd.DataFrame]:
        """
        Fallback to ESPN scoreboard for missing schedule dates.

        Args:
            missing_dates: List of dates missing from nbac_schedule

        Returns:
            DataFrame with ESPN data or None if unavailable
        """

        if not missing_dates:
            return None

        logger.info(f"Attempting ESPN fallback for {len(missing_dates)} dates")

        # Format dates for SQL IN clause
        date_list = "', '".join([d.isoformat() for d in missing_dates])

        query = f"""
        SELECT
            game_id,
            game_date,
            season_year,
            home_team_abbr,
            away_team_abbr,
            3 as game_status,  -- Final (ESPN only has completed games)
            home_team_score,
            away_team_score,
            CASE
                WHEN home_team_winner THEN home_team_abbr
                WHEN away_team_winner THEN away_team_abbr
            END as winning_team_abbr,
            'espn_scoreboard' as data_source,
            processed_at
        FROM `{self.project_id}.nba_raw.espn_scoreboard`
        WHERE game_date IN ('{date_list}')
          AND is_completed = TRUE
          AND game_status = 'final'
        """

        try:
            espn_df = self.bq_client.query(query).to_dataframe()

            if len(espn_df) > 0:
                logger.info(f"✓ ESPN fallback found {len(espn_df)} games")
            else:
                logger.warning("ESPN fallback returned 0 rows")

            return espn_df

        except Exception as e:
            logger.warning(f"ESPN fallback failed: {e}")
            return None

    def extract_betting_lines(
        self,
        start_date: date,
        end_date: date,
        log_quality_issue_fn
    ) -> Optional[pd.DataFrame]:
        """
        Extract latest betting lines for target date range.

        Strategy:
        - Get latest snapshot per game per bookmaker per market
        - Focus on target dates (no extended window needed)

        Args:
            start_date: Start of target date range
            end_date: End of target date range
            log_quality_issue_fn: Function to log quality issues

        Returns:
            DataFrame with betting lines or None if unavailable
        """

        logger.info(f"Extracting betting lines: {start_date} to {end_date}")

        query = f"""
        WITH latest_lines AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY game_date, game_id, bookmaker_key, market_key, outcome_name
              ORDER BY snapshot_timestamp DESC
            ) as rn
          FROM `{self.project_id}.nba_raw.odds_api_game_lines`
          WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        )
        SELECT
            game_date,
            game_id,
            home_team_abbr,
            away_team_abbr,
            bookmaker_key,
            market_key,
            outcome_name,
            outcome_point,
            outcome_price,
            snapshot_timestamp
        FROM latest_lines
        WHERE rn = 1
        ORDER BY game_date, game_id, market_key
        """

        try:
            lines_df = self.bq_client.query(query).to_dataframe()

            if len(lines_df) == 0:
                logger.warning("No betting lines found for date range")
                return None

            return lines_df

        except Exception as e:
            logger.warning(f"Error extracting betting lines: {e}")
            log_quality_issue_fn(
                severity='WARNING',
                category='EXTRACTION_FAILED',
                message=f"Betting lines extraction failed: {str(e)}",
                details={'error_type': type(e).__name__}
            )
            return None

    def extract_injury_data(
        self,
        start_date: date,
        end_date: date,
        log_quality_issue_fn
    ) -> Optional[pd.DataFrame]:
        """
        Extract latest injury reports for target date range.

        Strategy:
        - Get latest report per player per game
        - Focus on target dates

        Args:
            start_date: Start of target date range
            end_date: End of target date range
            log_quality_issue_fn: Function to log quality issues

        Returns:
            DataFrame with injury data or None if unavailable
        """

        logger.info(f"Extracting injury data: {start_date} to {end_date}")

        query = f"""
        WITH latest_status AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY game_date, player_lookup
              ORDER BY report_date DESC, report_hour DESC
            ) as rn
          FROM `{self.project_id}.nba_raw.nbac_injury_report`
          WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        )
        SELECT
            game_date,
            team,
            player_lookup,
            injury_status,
            reason_category,
            confidence_score
        FROM latest_status
        WHERE rn = 1
          AND confidence_score >= 0.8  -- Only use high-confidence records
        """

        try:
            injury_df = self.bq_client.query(query).to_dataframe()

            if len(injury_df) == 0:
                logger.warning("No injury data found for date range")
                return None

            return injury_df

        except Exception as e:
            logger.warning(f"Error extracting injury data: {e}")
            log_quality_issue_fn(
                severity='WARNING',
                category='EXTRACTION_FAILED',
                message=f"Injury data extraction failed: {str(e)}",
                details={'error_type': type(e).__name__}
            )
            return None

    def load_travel_distances(self) -> dict:
        """
        Load travel distance mappings from static table.

        Returns:
            Dict mapping "FROM_TO" → distance_miles
        """

        query = f"""
        SELECT
            from_team,
            to_team,
            distance_miles
        FROM `{self.project_id}.nba_static.travel_distances`
        """

        try:
            df = self.bq_client.query(query).to_dataframe()

            # Build lookup dict
            distances = {}
            for _, row in df.iterrows():
                key = f"{row['from_team']}_{row['to_team']}"
                distances[key] = row['distance_miles']

            return distances

        except Exception as e:
            logger.warning(f"Error loading travel distances: {e}")
            return {}
