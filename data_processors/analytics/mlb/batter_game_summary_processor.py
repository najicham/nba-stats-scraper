#!/usr/bin/env python3
"""
MLB Batter Game Summary Analytics Processor

Transforms raw batter stats into analytics features with rolling K rates.
CRITICAL for bottom-up strikeout prediction model.

Source: mlb_raw.bdl_batter_stats
Target: mlb_analytics.batter_game_summary

Bottom-Up Model Insight:
    Pitcher K's ~ Sum of individual batter K probabilities
    If batter K lines don't sum to pitcher K line -> market inefficiency

Key Features Generated:
- k_rate_last_5, k_rate_last_10 (rolling K/AB rates)
- k_avg_last_5, k_avg_last_10 (rolling K averages)
- k_std_last_10 (strikeout volatility)
- season_k_rate (baseline K tendency)

Processing Strategy: MERGE_UPDATE per game_date

Created: 2026-01-06
"""

import logging
import os
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client

from data_processors.analytics.analytics_base import AnalyticsProcessorBase
from shared.utils.notification_system import notify_error, notify_warning, notify_info
from shared.config.sport_config import get_analytics_dataset, get_raw_dataset

logger = logging.getLogger(__name__)


class MlbBatterGameSummaryProcessor(AnalyticsProcessorBase):
    """
    MLB Batter Game Summary Analytics Processor

    Calculates rolling strikeout stats for each batter.
    Critical for bottom-up model - sum batter K rates to predict pitcher totals.

    Processing Flow:
    1. Query raw batter stats for target date
    2. Calculate rolling K rates using window functions
    3. Join with game context (opponent, lineup position, etc.)
    4. Write to analytics table

    Target Table: mlb_analytics.batter_game_summary
    """

    def __init__(self):
        self.raw_dataset = get_raw_dataset()  # mlb_raw
        self.analytics_dataset = get_analytics_dataset()  # mlb_analytics
        super().__init__()
        self.table_name = 'batter_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = get_bigquery_client(project_id=self.project_id)

    def process_date(self, target_date: date) -> Dict:
        """Process batter game summary for a specific date."""
        logger.info(f"Processing MLB batter game summary for {target_date}")

        try:
            # Build and execute the analytics query
            query = self._build_analytics_query(target_date)
            rows = self._execute_query(query)

            if not rows:
                logger.info(f"No batter data found for {target_date}")
                return {'rows_processed': 0, 'date': str(target_date)}

            # Save to BigQuery
            self._save_to_bigquery(rows, target_date)

            logger.info(f"Processed {len(rows)} batter game summaries for {target_date}")

            # Send notification with bottom-up model stats
            try:
                total_ks = sum(r.get('strikeouts', 0) or 0 for r in rows)
                total_abs = sum(r.get('at_bats', 0) or 0 for r in rows)
                k_rate = total_ks / total_abs if total_abs > 0 else 0

                notify_info(
                    title="MLB Batter Game Summary Complete",
                    message=f"Processed {len(rows)} batters for {target_date}",
                    details={
                        'date': str(target_date),
                        'batters_processed': len(rows),
                        'total_strikeouts': total_ks,
                        'total_at_bats': total_abs,
                        'overall_k_rate': round(k_rate, 3),
                        'processor': 'MlbBatterGameSummaryProcessor'
                    }
                )
            except Exception as notify_e:
                logger.debug(f"Failed to send success notification: {notify_e}")

            return {'rows_processed': len(rows), 'date': str(target_date)}

        except Exception as e:
            logger.error(f"Error processing {target_date}: {e}")
            notify_error(
                title="MLB Batter Game Summary Failed",
                message=f"Error processing {target_date}: {str(e)[:200]}",
                details={
                    'date': str(target_date),
                    'error': str(e),
                    'processor': 'MlbBatterGameSummaryProcessor'
                },
                processor_name="MlbBatterGameSummaryProcessor"
            )
            raise

    def _build_analytics_query(self, target_date: date) -> str:
        """Build SQL query for batter analytics with rolling K stats."""
        date_str = target_date.isoformat()

        query = f"""
        WITH batter_history AS (
            -- Get all batter stats with game ordering
            SELECT
                player_lookup,
                player_full_name,
                game_id,
                game_date,
                team_abbr,
                home_team_abbr,
                away_team_abbr,
                CASE WHEN team_abbr = home_team_abbr THEN away_team_abbr ELSE home_team_abbr END as opponent_team_abbr,
                CASE WHEN team_abbr = home_team_abbr THEN TRUE ELSE FALSE END as is_home,
                season_year,
                is_postseason,
                venue,
                game_status,
                position,
                batting_order,

                -- Actual performance
                strikeouts,
                at_bats,
                hits,
                walks,
                home_runs,
                rbi,
                runs,
                doubles,
                triples,
                stolen_bases,

                -- Previous game date for days rest
                LAG(game_date) OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date, game_id
                ) as prev_game_date

            FROM `{self.project_id}.{self.raw_dataset}.bdl_batter_stats`
            WHERE game_date <= '{date_str}'
              AND at_bats > 0  -- Filter to batters who had at-bats
              AND game_status IN ('STATUS_FINAL', 'STATUS_F')  -- Both formats
        ),

        rolling_stats AS (
            -- Calculate rolling K stats for each game
            SELECT
                h.*,

                -- Rolling K rates (K/AB) - CRITICAL FOR BOTTOM-UP MODEL
                SAFE_DIVIDE(
                    SUM(strikeouts) OVER (
                        PARTITION BY player_lookup
                        ORDER BY game_date, game_id
                        ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                    ),
                    SUM(at_bats) OVER (
                        PARTITION BY player_lookup
                        ORDER BY game_date, game_id
                        ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                    )
                ) as k_rate_last_5,

                SAFE_DIVIDE(
                    SUM(strikeouts) OVER (
                        PARTITION BY player_lookup
                        ORDER BY game_date, game_id
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    ),
                    SUM(at_bats) OVER (
                        PARTITION BY player_lookup
                        ORDER BY game_date, game_id
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    )
                ) as k_rate_last_10,

                -- Rolling K averages per game
                AVG(strikeouts) OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                ) as k_avg_last_5,

                AVG(strikeouts) OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                ) as k_avg_last_10,

                -- K volatility
                STDDEV(strikeouts) OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                ) as k_std_last_10,

                -- Rolling AB averages (playing time indicator)
                AVG(at_bats) OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                ) as ab_avg_last_5,

                AVG(at_bats) OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                ) as ab_avg_last_10,

                -- Games in last 30 days (approximated by recent rows)
                COUNT(*) OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
                ) as games_last_30_days,

                -- Season totals (prior to this game)
                SUM(strikeouts) OVER (
                    PARTITION BY player_lookup, season_year
                    ORDER BY game_date, game_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) as season_strikeouts_prior,

                SUM(at_bats) OVER (
                    PARTITION BY player_lookup, season_year
                    ORDER BY game_date, game_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) as season_at_bats_prior,

                SUM(hits) OVER (
                    PARTITION BY player_lookup, season_year
                    ORDER BY game_date, game_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) as season_hits_prior,

                COUNT(*) OVER (
                    PARTITION BY player_lookup, season_year
                    ORDER BY game_date, game_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) as season_games_prior,

                -- Rolling stats games count
                COUNT(*) OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date, game_id
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                ) as rolling_stats_games

            FROM batter_history h
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
            batting_order,
            position,

            -- Actual performance (TARGET!)
            strikeouts,
            at_bats,
            hits,
            walks,
            home_runs,
            rbi,
            runs,
            doubles,
            triples,
            stolen_bases,

            -- Rolling K stats (CRITICAL FOR BOTTOM-UP MODEL!)
            ROUND(k_rate_last_5, 3) as k_rate_last_5,
            ROUND(k_rate_last_10, 3) as k_rate_last_10,
            ROUND(k_avg_last_5, 2) as k_avg_last_5,
            ROUND(k_avg_last_10, 2) as k_avg_last_10,
            ROUND(k_std_last_10, 2) as k_std_last_10,
            ROUND(ab_avg_last_5, 2) as ab_avg_last_5,
            ROUND(ab_avg_last_10, 2) as ab_avg_last_10,
            games_last_30_days,

            -- Season stats
            COALESCE(season_strikeouts_prior, 0) as season_strikeouts,
            COALESCE(season_at_bats_prior, 0) as season_at_bats,
            ROUND(SAFE_DIVIDE(season_strikeouts_prior, season_at_bats_prior), 3) as season_k_rate,
            ROUND(SAFE_DIVIDE(season_hits_prior, season_at_bats_prior), 3) as season_batting_avg,
            COALESCE(season_games_prior, 0) as season_games,

            -- Days rest
            DATE_DIFF(game_date, prev_game_date, DAY) as days_since_last_game,

            -- Data quality
            'bdl' as stats_source,
            rolling_stats_games,
            CASE WHEN season_games_prior = 0 OR season_games_prior IS NULL THEN TRUE ELSE FALSE END as is_first_game_season,
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
        ORDER BY team_abbr, batting_order, player_full_name
        """

        return query

    def _execute_query(self, query: str) -> List[Dict]:
        """Execute query and return results as list of dicts."""
        job = self.bq_client.query(query)
        results = job.result()

        rows = []
        for row in results:
            row_dict = dict(row)
            # Convert date/datetime objects to strings for JSON serialization
            for key, value in row_dict.items():
                if isinstance(value, (date, datetime)):
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

    parser = argparse.ArgumentParser(description='Process MLB batter game summaries')
    parser.add_argument('--date', help='Target date (YYYY-MM-DD)')
    parser.add_argument('--start-date', help='Start date for range')
    parser.add_argument('--end-date', help='End date for range')

    args = parser.parse_args()

    processor = MlbBatterGameSummaryProcessor()

    opts = {}
    if args.date:
        opts['date'] = args.date
    elif args.start_date and args.end_date:
        opts['start_date'] = args.start_date
        opts['end_date'] = args.end_date

    success = processor.run(opts)
    print(f"Processing {'succeeded' if success else 'failed'}")
