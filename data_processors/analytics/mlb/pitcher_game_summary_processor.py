#!/usr/bin/env python3
"""
MLB Pitcher Game Summary Analytics Processor

Transforms raw pitcher stats into analytics features with rolling averages.
Key output: Strikeout prediction features for ML model.

Source: mlb_raw.bdl_pitcher_stats
Target: mlb_analytics.pitcher_game_summary

Key Features Generated:
- k_avg_last_3, k_avg_last_5, k_avg_last_10 (rolling K averages)
- k_std_last_10 (strikeout volatility)
- ip_avg_last_5, ip_avg_last_10 (innings trends)
- k_per_9_rolling_10 (rolling K/9 rate)
- days_rest (recovery time)

Processing Strategy: MERGE_UPDATE per game_date
- Processes one date at a time
- Uses SQL window functions for rolling stats
- Supports backfill via date range

Created: 2026-01-06
"""

import logging
import os
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client

from data_processors.analytics.analytics_base import AnalyticsProcessorBase
from shared.processors.patterns import CircuitBreakerMixin
from shared.utils.notification_system import notify_error, notify_warning, notify_info
from shared.config.sport_config import get_analytics_dataset, get_raw_dataset

logger = logging.getLogger(__name__)


class MlbPitcherGameSummaryProcessor(CircuitBreakerMixin, AnalyticsProcessorBase):
    """
    MLB Pitcher Game Summary Analytics Processor

    Calculates rolling strikeout stats and game context for ML features.

    Processing Flow:
    1. Query raw pitcher stats for target date
    2. Calculate rolling averages using window functions
    3. Join with game context (home/away, opponent, etc.)
    4. Write to analytics table

    Target Table: mlb_analytics.pitcher_game_summary
    """

    def __init__(self):
        self.raw_dataset = get_raw_dataset()  # mlb_raw
        self.analytics_dataset = get_analytics_dataset()  # mlb_analytics
        super().__init__()
        self.table_name = 'pitcher_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = get_bigquery_client(project_id=self.project_id)

    def get_upstream_data_check_query(self, start_date: str, end_date: str) -> Optional[str]:
        """
        Check if upstream data is available for circuit breaker auto-reset.

        Prevents retry storms by checking if MLB pitcher stats exist for the date range.

        Args:
            start_date: Start of date range (YYYY-MM-DD)
            end_date: End of date range (YYYY-MM-DD)

        Returns:
            SQL query that returns {data_available: boolean}
        """
        return f"""
        SELECT
            COUNT(*) > 0 AS data_available
        FROM `{self.project_id}.{self.raw_dataset}.mlb_pitcher_stats`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        """

    def process_date(self, target_date: date) -> Dict:
        """Process pitcher game summary for a specific date."""
        logger.info(f"Processing MLB pitcher game summary for {target_date}")

        try:
            # Build and execute the analytics query
            query = self._build_analytics_query(target_date)
            rows = self._execute_query(query)

            if not rows:
                logger.info(f"No pitcher data found for {target_date}")
                return {'rows_processed': 0, 'date': str(target_date)}

            # Save to BigQuery
            self._save_to_bigquery(rows, target_date)

            logger.info(f"Processed {len(rows)} pitcher game summaries for {target_date}")

            # Send notification
            try:
                total_ks = sum(r.get('strikeouts', 0) or 0 for r in rows)
                notify_info(
                    title="MLB Pitcher Game Summary Complete",
                    message=f"Processed {len(rows)} pitchers for {target_date}",
                    details={
                        'date': str(target_date),
                        'pitchers_processed': len(rows),
                        'total_strikeouts': total_ks,
                        'processor': 'MlbPitcherGameSummaryProcessor'
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_e:
                logger.debug(f"Failed to send success notification: {notify_e}")

            return {'rows_processed': len(rows), 'date': str(target_date)}

        except Exception as e:
            logger.error(f"Error processing {target_date}: {e}")
            notify_error(
                title="MLB Pitcher Game Summary Failed",
                message=f"Error processing {target_date}: {str(e)[:200]}",
                details={
                    'date': str(target_date),
                    'error': str(e),
                    'processor': 'MlbPitcherGameSummaryProcessor'
                },
                processor_name="MlbPitcherGameSummaryProcessor"
            )
            raise

    def _build_analytics_query(self, target_date: date) -> str:
        """Build SQL query for analytics with rolling stats."""
        date_str = target_date.isoformat()

        # Query calculates rolling averages using window functions
        query = f"""
        WITH pitcher_history AS (
            -- Get all pitcher stats with game ordering
            -- Updated to use mlb_pitcher_stats from MLB Stats API
            SELECT
                player_lookup,
                player_name as player_full_name,
                game_id,
                game_date,
                team_abbr,
                -- Derive home/away team abbrs from game_id format: YYYY-MM-DD_AWAY_HOME
                SPLIT(game_id, '_')[SAFE_OFFSET(2)] as home_team_abbr,
                SPLIT(game_id, '_')[SAFE_OFFSET(1)] as away_team_abbr,
                opponent_team_abbr,
                is_home,
                season_year,
                FALSE as is_postseason,  -- Not tracked in mlb_pitcher_stats
                venue,
                game_status,
                NULL as win,  -- Not tracked in mlb_pitcher_stats

                -- Actual performance
                strikeouts,
                innings_pitched,
                pitch_count,
                0 as strikes,  -- Not tracked
                COALESCE(walks_allowed, 0) as walks_allowed,
                hits_allowed,
                earned_runs,
                SAFE_DIVIDE(earned_runs * 9, innings_pitched) as era,

                -- Row number for ordering
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date DESC, game_id DESC
                ) as game_recency,

                -- Previous game date for days_rest calculation
                LAG(game_date) OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date, game_id
                ) as prev_game_date

            FROM `{self.project_id}.{self.raw_dataset}.mlb_pitcher_stats`
            WHERE game_date <= '{date_str}'
              AND innings_pitched >= 1.0  -- Filter to meaningful appearances
              AND is_starter = TRUE  -- Only starting pitchers
        ),

        -- FanGraphs season stats for SwStr% (leading indicator)
        fangraphs_stats AS (
            SELECT DISTINCT
                player_lookup,
                season_year,
                swstr_pct,
                csw_pct,
                o_swing_pct as chase_pct,
                k_pct as fg_k_pct,
                contact_pct
            FROM `{self.project_id}.{self.raw_dataset}.fangraphs_pitcher_season_stats`
            WHERE snapshot_date = (
                SELECT MAX(snapshot_date)
                FROM `{self.project_id}.{self.raw_dataset}.fangraphs_pitcher_season_stats`
            )
        ),

        rolling_stats AS (
            -- Calculate rolling averages for each game
            SELECT
                h.*,

                -- FanGraphs season-level SwStr% (join by player + season)
                fg.swstr_pct as season_swstr_pct,
                fg.csw_pct as season_csw_pct,
                fg.chase_pct as season_chase_pct,
                fg.fg_k_pct as season_fg_k_pct,
                fg.contact_pct as season_contact_pct,

                -- Rolling K averages
                AVG(strikeouts) OVER (
                    PARTITION BY h.player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
                ) as k_avg_last_3,

                AVG(strikeouts) OVER (
                    PARTITION BY h.player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                ) as k_avg_last_5,

                AVG(strikeouts) OVER (
                    PARTITION BY h.player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                ) as k_avg_last_10,

                -- K volatility (std dev)
                STDDEV(strikeouts) OVER (
                    PARTITION BY h.player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                ) as k_std_last_10,

                -- Rolling IP averages
                AVG(innings_pitched) OVER (
                    PARTITION BY h.player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                ) as ip_avg_last_5,

                AVG(innings_pitched) OVER (
                    PARTITION BY h.player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                ) as ip_avg_last_10,

                -- Rolling pitch count
                AVG(pitch_count) OVER (
                    PARTITION BY h.player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                ) as pitch_count_avg_last_5,

                -- Rolling ERA and WHIP
                SAFE_DIVIDE(
                    SUM(earned_runs) OVER (
                        PARTITION BY h.player_lookup
                        ORDER BY game_date, game_id
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    ) * 9,
                    SUM(innings_pitched) OVER (
                        PARTITION BY h.player_lookup
                        ORDER BY game_date, game_id
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    )
                ) as era_rolling_10,

                SAFE_DIVIDE(
                    SUM(walks_allowed + hits_allowed) OVER (
                        PARTITION BY h.player_lookup
                        ORDER BY game_date, game_id
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    ),
                    SUM(innings_pitched) OVER (
                        PARTITION BY h.player_lookup
                        ORDER BY game_date, game_id
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    )
                ) as whip_rolling_10,

                -- Rolling K/9
                SAFE_DIVIDE(
                    SUM(strikeouts) OVER (
                        PARTITION BY h.player_lookup
                        ORDER BY game_date, game_id
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    ) * 9,
                    SUM(innings_pitched) OVER (
                        PARTITION BY h.player_lookup
                        ORDER BY game_date, game_id
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    )
                ) as k_per_9_rolling_10,

                -- Games in last 30 days (workload)
                COUNT(*) OVER (
                    PARTITION BY h.player_lookup
                    ORDER BY UNIX_DATE(game_date)
                    RANGE BETWEEN 30 PRECEDING AND 1 PRECEDING
                ) as games_last_30_days,

                -- Season totals
                SUM(strikeouts) OVER (
                    PARTITION BY h.player_lookup, h.season_year
                    ORDER BY game_date, game_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) as season_strikeouts_prior,

                SUM(innings_pitched) OVER (
                    PARTITION BY h.player_lookup, h.season_year
                    ORDER BY game_date, game_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) as season_innings_prior,

                COUNT(*) OVER (
                    PARTITION BY h.player_lookup, h.season_year
                    ORDER BY game_date, game_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) as season_games_prior,

                -- Count of rolling stats games available
                COUNT(*) OVER (
                    PARTITION BY h.player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                ) as rolling_stats_games

            FROM pitcher_history h
            LEFT JOIN fangraphs_stats fg
                ON REPLACE(h.player_lookup, '_', '') = fg.player_lookup
                AND h.season_year = fg.season_year
        )

        SELECT
            player_lookup,
            player_full_name,
            game_id,
            game_date,
            team_abbr,
            opponent_team_abbr,
            season_year,

            -- Game context
            is_home,
            is_postseason,
            venue,
            game_status,
            win as win_flag,

            -- Actual performance (TARGET!)
            strikeouts,
            innings_pitched,
            pitch_count,
            strikes,
            walks_allowed,
            hits_allowed,
            earned_runs,
            era as era_game,
            CASE WHEN innings_pitched >= 6.0 AND earned_runs <= 3 THEN TRUE ELSE FALSE END as quality_start,

            -- Rolling stats (ML FEATURES!)
            ROUND(k_avg_last_3, 2) as k_avg_last_3,
            ROUND(k_avg_last_5, 2) as k_avg_last_5,
            ROUND(k_avg_last_10, 2) as k_avg_last_10,
            ROUND(k_std_last_10, 2) as k_std_last_10,
            ROUND(ip_avg_last_5, 2) as ip_avg_last_5,
            ROUND(ip_avg_last_10, 2) as ip_avg_last_10,
            ROUND(pitch_count_avg_last_5, 1) as pitch_count_avg_last_5,
            ROUND(era_rolling_10, 2) as era_rolling_10,
            ROUND(whip_rolling_10, 2) as whip_rolling_10,
            ROUND(k_per_9_rolling_10, 2) as k_per_9_rolling_10,
            games_last_30_days,

            -- Days rest
            DATE_DIFF(game_date, prev_game_date, DAY) as days_rest,

            -- Season stats
            COALESCE(season_strikeouts_prior, 0) as season_strikeouts,
            COALESCE(season_innings_prior, 0) as season_innings,
            ROUND(SAFE_DIVIDE(season_strikeouts_prior * 9, season_innings_prior), 2) as season_k_per_9,
            COALESCE(season_games_prior, 0) as season_games_started,

            -- FanGraphs SwStr% metrics (LEADING INDICATORS!)
            ROUND(season_swstr_pct, 4) as season_swstr_pct,
            ROUND(season_csw_pct, 4) as season_csw_pct,
            ROUND(season_chase_pct, 4) as season_chase_pct,
            ROUND(season_contact_pct, 4) as season_contact_pct,

            -- Data quality
            'bdl' as stats_source,
            rolling_stats_games,
            CASE WHEN season_games_prior = 0 OR season_games_prior IS NULL THEN TRUE ELSE FALSE END as is_first_start,
            CASE
                WHEN rolling_stats_games >= 10 THEN 1.0
                WHEN rolling_stats_games >= 5 THEN 0.8
                WHEN rolling_stats_games >= 3 THEN 0.6
                ELSE 0.4
            END as data_completeness_score,

            -- Metadata
            CURRENT_TIMESTAMP() as created_at,
            CURRENT_TIMESTAMP() as processed_at

        FROM rolling_stats
        WHERE game_date = '{date_str}'
        ORDER BY team_abbr, player_full_name
        """

        return query

    def _execute_query(self, query: str) -> List[Dict]:
        """Execute query and return results as list of dicts."""
        from datetime import date as date_type, datetime as datetime_type

        job = self.bq_client.query(query)
        results = job.result()

        rows = []
        for row in results:
            row_dict = dict(row)
            # Convert date/datetime to string for JSON serialization
            for key, value in row_dict.items():
                if isinstance(value, date_type):
                    row_dict[key] = value.isoformat()
                elif isinstance(value, datetime_type):
                    row_dict[key] = value.isoformat()
            rows.append(row_dict)

        return rows

    def _save_to_bigquery(self, rows: List[Dict], target_date: date) -> None:
        """Save processed rows to BigQuery."""
        table_id = f"{self.project_id}.{self.analytics_dataset}.{self.table_name}"
        date_str = target_date.isoformat()

        # Delete existing data for this date
        delete_query = f"""
        DELETE FROM `{table_id}`
        WHERE game_date = '{date_str}'
        """

        try:
            self.bq_client.query(delete_query).result(timeout=60)
        except Exception as e:
            if 'not found' in str(e).lower():
                logger.info(f"Table {table_id} doesn't exist yet, will be created")
            else:
                logger.warning(f"Delete failed: {e}")

        # Insert new data
        try:
            # Get table for schema
            table = self.bq_client.get_table(table_id)

            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND
            )

            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config
            )
            load_job.result(timeout=120)

            logger.info(f"Saved {len(rows)} rows to {table_id}")

        except Exception as e:
            logger.error(f"Error saving to BigQuery: {e}")
            raise

    def run(self, opts: Dict = None) -> bool:
        """Run the processor for specified date(s)."""
        opts = opts or {}

        # Determine target date(s)
        if 'start_date' in opts and 'end_date' in opts:
            # Date range mode
            start = datetime.strptime(opts['start_date'], '%Y-%m-%d').date()
            end = datetime.strptime(opts['end_date'], '%Y-%m-%d').date()
            current = start
            total_rows = 0

            while current <= end:
                result = self.process_date(current)
                total_rows += result.get('rows_processed', 0)
                current += timedelta(days=1)

            logger.info(f"Processed {total_rows} total rows from {start} to {end}")
            return True

        elif 'date' in opts:
            # Single date mode
            target_date = datetime.strptime(opts['date'], '%Y-%m-%d').date()
            self.process_date(target_date)
            return True

        else:
            # Default: yesterday
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
            self.process_date(yesterday)
            return True


# CLI entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Process MLB pitcher game summaries')
    parser.add_argument('--date', help='Target date (YYYY-MM-DD)')
    parser.add_argument('--start-date', help='Start date for range')
    parser.add_argument('--end-date', help='End date for range')

    args = parser.parse_args()

    processor = MlbPitcherGameSummaryProcessor()

    opts = {}
    if args.date:
        opts['date'] = args.date
    elif args.start_date and args.end_date:
        opts['start_date'] = args.start_date
        opts['end_date'] = args.end_date

    success = processor.run(opts)
    print(f"Processing {'succeeded' if success else 'failed'}")
