#!/usr/bin/env python3
"""
Comprehensive database verification script
Checks data completeness and quality across all NBA tables
"""

import os
import sys
from datetime import datetime, date
from typing import Dict, List, Any
import pandas as pd
from google.cloud import bigquery

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.utils.bigquery_client import BigQueryClient


def print_section(title: str):
    """Print formatted section header"""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")


def execute_query(client: bigquery.Client, query: str, description: str) -> pd.DataFrame:
    """Execute query and return results"""
    print(f"\n--- {description} ---")
    print(f"Query: {query}\n")

    try:
        query_job = client.query(query)
        df = query_job.to_dataframe()
        print(df.to_string(index=False))
        return df
    except Exception as e:
        print(f"ERROR: {e}")
        return pd.DataFrame()


class DatabaseVerifier:
    """Verifies database completeness and quality across all NBA tables."""

    def __init__(self, project_id: str, target_dates: List[str]):
        """
        Initialize the DatabaseVerifier.

        Args:
            project_id: GCP project ID
            target_dates: List of date strings to verify (format: 'YYYY-MM-DD')
        """
        self.client = bigquery.Client(project=project_id)
        self.project_id = project_id
        self.target_dates = target_dates

        # Store results for summary generation
        self.df_raw_player = None
        self.df_raw_games = None
        self.df_analytics_player = None
        self.df_predictions = None

    def verify_record_counts(self):
        """Section 1: Exact record counts by date."""
        print_section("SECTION 1: EXACT RECORD COUNTS BY DATE")

        # 1.1 - nba_raw.bdl_player_boxscores
        query = f"""
        SELECT
            DATE(game_date) as game_date,
            COUNT(*) as record_count,
            COUNT(DISTINCT game_id) as unique_games,
            COUNT(DISTINCT player_id) as unique_players
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE DATE(game_date) IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY DATE(game_date)
        ORDER BY game_date
        """
        self.df_raw_player = execute_query(self.client, query, "1.1 - nba_raw.bdl_player_boxscores")

        # 1.2 - nba_raw.bdl_team_boxscores
        query = f"""
        SELECT
            DATE(game_date) as game_date,
            COUNT(*) as record_count,
            COUNT(DISTINCT game_id) as unique_games,
            COUNT(DISTINCT team_id) as unique_teams
        FROM `{self.project_id}.nba_raw.bdl_team_boxscores`
        WHERE DATE(game_date) IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY DATE(game_date)
        ORDER BY game_date
        """
        execute_query(self.client, query, "1.2 - nba_raw.bdl_team_boxscores")

        # 1.3 - nba_raw.bdl_games (or game info table)
        query = f"""
        SELECT
            DATE(game_date) as game_date,
            COUNT(*) as record_count,
            COUNT(DISTINCT game_id) as unique_games,
            SUM(CASE WHEN status = 'Final' THEN 1 ELSE 0 END) as final_games,
            SUM(CASE WHEN status != 'Final' THEN 1 ELSE 0 END) as non_final_games
        FROM `{self.project_id}.nba_raw.bdl_games`
        WHERE DATE(game_date) IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY DATE(game_date)
        ORDER BY game_date
        """
        self.df_raw_games = execute_query(self.client, query, "1.3 - nba_raw.bdl_games")

        # 1.4 - nba_analytics.player_game_summary
        query = f"""
        SELECT
            DATE(game_date) as game_date,
            COUNT(*) as record_count,
            COUNT(DISTINCT game_id) as unique_games,
            COUNT(DISTINCT player_id) as unique_players
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE DATE(game_date) IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY DATE(game_date)
        ORDER BY game_date
        """
        self.df_analytics_player = execute_query(self.client, query, "1.4 - nba_analytics.player_game_summary")

        # 1.5 - nba_analytics.team_game_summary (check if exists)
        query = f"""
        SELECT
            DATE(game_date) as game_date,
            COUNT(*) as record_count,
            COUNT(DISTINCT game_id) as unique_games,
            COUNT(DISTINCT team_id) as unique_teams
        FROM `{self.project_id}.nba_analytics.team_game_summary`
        WHERE DATE(game_date) IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY DATE(game_date)
        ORDER BY game_date
        """
        execute_query(self.client, query, "1.5 - nba_analytics.team_game_summary")

        # 1.6 - nba_precompute.player_daily_cache
        query = f"""
        SELECT
            computation_date,
            COUNT(*) as record_count,
            COUNT(DISTINCT player_id) as unique_players
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE computation_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY computation_date
        ORDER BY computation_date
        """
        execute_query(self.client, query, "1.6 - nba_precompute.player_daily_cache")

        # 1.7 - nba_predictions.player_prop_predictions
        query = f"""
        SELECT
            prediction_date,
            COUNT(*) as record_count,
            COUNT(DISTINCT game_id) as unique_games,
            COUNT(DISTINCT player_id) as unique_players,
            COUNT(DISTINCT prop_type) as unique_prop_types
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE prediction_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY prediction_date
        ORDER BY prediction_date
        """
        self.df_predictions = execute_query(self.client, query, "1.7 - nba_predictions.player_prop_predictions")

        # 1.8 - nba_predictions.team_predictions (check if exists)
        query = f"""
        SELECT
            prediction_date,
            COUNT(*) as record_count,
            COUNT(DISTINCT game_id) as unique_games,
            COUNT(DISTINCT team_id) as unique_teams
        FROM `{self.project_id}.nba_predictions.team_predictions`
        WHERE prediction_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY prediction_date
        ORDER BY prediction_date
        """
        execute_query(self.client, query, "1.8 - nba_predictions.team_predictions")

        # 1.9 - Check for grading/results tables
        query = f"""
        SELECT
            grading_date,
            COUNT(*) as record_count,
            COUNT(DISTINCT prediction_id) as unique_predictions,
            SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN result = 'push' THEN 1 ELSE 0 END) as pushes
        FROM `{self.project_id}.nba_predictions.player_prop_results`
        WHERE grading_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY grading_date
        ORDER BY grading_date
        """
        execute_query(self.client, query, "1.9 - nba_predictions.player_prop_results")

    def check_quality_issues(self):
        """Section 2: Data quality issues."""
        print_section("SECTION 2: DATA QUALITY ISSUES")

        # 2.1 - NULL values in critical fields (raw player boxscores)
        query = f"""
        SELECT
            DATE(game_date) as game_date,
            COUNT(*) as total_records,
            SUM(CASE WHEN player_id IS NULL THEN 1 ELSE 0 END) as null_player_id,
            SUM(CASE WHEN game_id IS NULL THEN 1 ELSE 0 END) as null_game_id,
            SUM(CASE WHEN team_id IS NULL THEN 1 ELSE 0 END) as null_team_id,
            SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) as null_minutes,
            SUM(CASE WHEN pts IS NULL THEN 1 ELSE 0 END) as null_points
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE DATE(game_date) IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY DATE(game_date)
        ORDER BY game_date
        """
        execute_query(self.client, query, "2.1 - NULL values in nba_raw.bdl_player_boxscores")

        # 2.2 - Duplicate records check
        query = f"""
        SELECT
            DATE(game_date) as game_date,
            game_id,
            player_id,
            COUNT(*) as duplicate_count
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE DATE(game_date) IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY DATE(game_date), game_id, player_id
        HAVING COUNT(*) > 1
        ORDER BY game_date, duplicate_count DESC
        LIMIT 50
        """
        execute_query(self.client, query, "2.2 - Duplicate records in raw player boxscores")

        # 2.3 - Data timestamp mismatches
        query = f"""
        SELECT
            DATE(game_date) as game_date,
            MIN(created_at) as earliest_created,
            MAX(created_at) as latest_created,
            TIMESTAMP_DIFF(MAX(created_at), MIN(created_at), HOUR) as hours_spread
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE DATE(game_date) IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY DATE(game_date)
        ORDER BY game_date
        """
        execute_query(self.client, query, "2.3 - Timestamp spread for raw player data")

        # 2.4 - Players with zero or NULL minutes (DNP/bench)
        query = f"""
        SELECT
            DATE(game_date) as game_date,
            COUNT(*) as total_records,
            SUM(CASE WHEN minutes = '0:00' OR minutes IS NULL THEN 1 ELSE 0 END) as zero_minutes,
            SUM(CASE WHEN minutes != '0:00' AND minutes IS NOT NULL THEN 1 ELSE 0 END) as played_minutes
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE DATE(game_date) IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY DATE(game_date)
        ORDER BY game_date
        """
        execute_query(self.client, query, "2.4 - Players with zero/NULL minutes (DNP)")

    def analyze_discrepancies(self):
        """Section 3: Discrepancy analysis."""
        print_section("SECTION 3: DISCREPANCY ANALYSIS")

        # 3.1 - Jan 19: 281 raw vs 227 analytics
        query = f"""
        WITH raw_players AS (
            SELECT DISTINCT game_id, player_id
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE DATE(game_date) = '2026-01-19'
        ),
        analytics_players AS (
            SELECT DISTINCT game_id, player_id
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE DATE(game_date) = '2026-01-19'
        )
        SELECT
            'In Raw Only' as status,
            COUNT(*) as count
        FROM raw_players r
        LEFT JOIN analytics_players a
            ON r.game_id = a.game_id AND r.player_id = a.player_id
        WHERE a.player_id IS NULL

        UNION ALL

        SELECT
            'In Analytics Only' as status,
            COUNT(*) as count
        FROM analytics_players a
        LEFT JOIN raw_players r
            ON a.game_id = r.game_id AND a.player_id = r.player_id
        WHERE r.player_id IS NULL

        UNION ALL

        SELECT
            'In Both' as status,
            COUNT(*) as count
        FROM raw_players r
        INNER JOIN analytics_players a
            ON r.game_id = a.game_id AND r.player_id = a.player_id
        """
        execute_query(self.client, query, "3.1 - Jan 19: Raw vs Analytics discrepancy")

        # 3.2 - Detailed look at missing players (Jan 19)
        query = f"""
        SELECT
            r.game_id,
            r.player_id,
            r.minutes,
            r.pts,
            r.reb,
            r.ast
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores` r
        LEFT JOIN `{self.project_id}.nba_analytics.player_game_summary` a
            ON r.game_id = a.game_id
            AND r.player_id = a.player_id
            AND DATE(a.game_date) = '2026-01-19'
        WHERE DATE(r.game_date) = '2026-01-19'
            AND a.player_id IS NULL
        ORDER BY r.game_id, r.player_id
        LIMIT 100
        """
        execute_query(self.client, query, "3.2 - Players in raw but NOT in analytics (Jan 19)")

        # 3.3 - Jan 20: 885 predictions but only 4 games and no Phase 3 data
        query = f"""
        SELECT
            game_id,
            COUNT(DISTINCT player_id) as unique_players,
            COUNT(DISTINCT prop_type) as unique_prop_types,
            COUNT(*) as total_predictions
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE prediction_date = '2026-01-20'
        GROUP BY game_id
        ORDER BY game_id
        """
        execute_query(self.client, query, "3.3 - Jan 20: Predictions breakdown by game")

        # 3.4 - Prop types for Jan 20 predictions
        query = f"""
        SELECT
            prop_type,
            COUNT(*) as prediction_count,
            COUNT(DISTINCT game_id) as games,
            COUNT(DISTINCT player_id) as players
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE prediction_date = '2026-01-20'
        GROUP BY prop_type
        ORDER BY prediction_count DESC
        """
        execute_query(self.client, query, "3.4 - Jan 20: Predictions by prop type")

    def check_historical_range(self):
        """Section 4: Historical data range."""
        print_section("SECTION 4: HISTORICAL DATA RANGE")

        # 4.1 - Date range for each table
        query = f"""
        SELECT
            'nba_raw.bdl_player_boxscores' as table_name,
            MIN(DATE(game_date)) as earliest_date,
            MAX(DATE(game_date)) as latest_date,
            COUNT(*) as total_records,
            COUNT(DISTINCT DATE(game_date)) as unique_dates
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`

        UNION ALL

        SELECT
            'nba_raw.bdl_team_boxscores' as table_name,
            MIN(DATE(game_date)) as earliest_date,
            MAX(DATE(game_date)) as latest_date,
            COUNT(*) as total_records,
            COUNT(DISTINCT DATE(game_date)) as unique_dates
        FROM `{self.project_id}.nba_raw.bdl_team_boxscores`

        UNION ALL

        SELECT
            'nba_raw.bdl_games' as table_name,
            MIN(DATE(game_date)) as earliest_date,
            MAX(DATE(game_date)) as latest_date,
            COUNT(*) as total_records,
            COUNT(DISTINCT DATE(game_date)) as unique_dates
        FROM `{self.project_id}.nba_raw.bdl_games`

        UNION ALL

        SELECT
            'nba_analytics.player_game_summary' as table_name,
            MIN(DATE(game_date)) as earliest_date,
            MAX(DATE(game_date)) as latest_date,
            COUNT(*) as total_records,
            COUNT(DISTINCT DATE(game_date)) as unique_dates
        FROM `{self.project_id}.nba_analytics.player_game_summary`

        UNION ALL

        SELECT
            'nba_precompute.player_daily_cache' as table_name,
            MIN(computation_date) as earliest_date,
            MAX(computation_date) as latest_date,
            COUNT(*) as total_records,
            COUNT(DISTINCT computation_date) as unique_dates
        FROM `{self.project_id}.nba_precompute.player_daily_cache`

        UNION ALL

        SELECT
            'nba_predictions.player_prop_predictions' as table_name,
            MIN(prediction_date) as earliest_date,
            MAX(prediction_date) as latest_date,
            COUNT(*) as total_records,
            COUNT(DISTINCT prediction_date) as unique_dates
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        """
        execute_query(self.client, query, "4.1 - Date range and total records for all tables")

        # 4.2 - Check for date gaps in recent data (last 30 days)
        query = f"""
        WITH date_series AS (
            SELECT DATE_SUB(CURRENT_DATE(), INTERVAL day DAY) as check_date
            FROM UNNEST(GENERATE_ARRAY(0, 30)) as day
        ),
        games_by_date AS (
            SELECT
                DATE(game_date) as game_date,
                COUNT(*) as game_count
            FROM `{self.project_id}.nba_raw.bdl_games`
            WHERE DATE(game_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            GROUP BY DATE(game_date)
        )
        SELECT
            ds.check_date,
            COALESCE(gbd.game_count, 0) as games_scheduled,
            CASE
                WHEN COALESCE(gbd.game_count, 0) = 0 THEN 'NO GAMES'
                ELSE 'HAS GAMES'
            END as status
        FROM date_series ds
        LEFT JOIN games_by_date gbd ON ds.check_date = gbd.game_date
        ORDER BY ds.check_date DESC
        """
        execute_query(self.client, query, "4.2 - Date gaps in last 30 days")

    def verify_game_schedule(self):
        """Section 5: Game schedule verification."""
        print_section("SECTION 5: GAME SCHEDULE VERIFICATION")

        # 5.1 - Actual games on Jan 20, 2026
        query = f"""
        SELECT
            game_id,
            DATE(game_date) as game_date,
            home_team_id,
            visitor_team_id,
            status,
            home_team_score,
            visitor_team_score
        FROM `{self.project_id}.nba_raw.bdl_games`
        WHERE DATE(game_date) = '2026-01-20'
        ORDER BY game_id
        """
        execute_query(self.client, query, "5.1 - Games scheduled on Jan 20, 2026")

        # 5.2 - Game statuses for target dates
        query = f"""
        SELECT
            DATE(game_date) as game_date,
            status,
            COUNT(*) as game_count
        FROM `{self.project_id}.nba_raw.bdl_games`
        WHERE DATE(game_date) IN ('2026-01-19', '2026-01-20', '2026-01-21')
        GROUP BY DATE(game_date), status
        ORDER BY game_date, status
        """
        execute_query(self.client, query, "5.2 - Game statuses by date")

        # 5.3 - Postponed or cancelled games
        query = f"""
        SELECT
            game_id,
            DATE(game_date) as game_date,
            home_team_id,
            visitor_team_id,
            status
        FROM `{self.project_id}.nba_raw.bdl_games`
        WHERE DATE(game_date) IN ('2026-01-19', '2026-01-20', '2026-01-21')
            AND status NOT IN ('Final', 'Scheduled')
        ORDER BY game_date, game_id
        """
        execute_query(self.client, query, "5.3 - Postponed or cancelled games")

    def generate_summary(self):
        """Section 6: Summary comparison."""
        print_section("SECTION 6: SUMMARY COMPARISON")

        # Create comparison summary
        print("\n--- Summary Table Comparison ---\n")

        summary_data = {
            'Date': self.target_dates,
            'Raw_Player_Records': [],
            'Analytics_Player_Records': [],
            'Raw_Games': [],
            'Predictions': []
        }

        for target_date in self.target_dates:
            # Get counts for this date
            raw_count = self.df_raw_player[self.df_raw_player['game_date'] == target_date]['record_count'].values
            analytics_count = self.df_analytics_player[self.df_analytics_player['game_date'] == target_date]['record_count'].values
            games_count = self.df_raw_games[self.df_raw_games['game_date'] == target_date]['record_count'].values
            pred_count = self.df_predictions[self.df_predictions['prediction_date'] == target_date]['record_count'].values

            summary_data['Raw_Player_Records'].append(raw_count[0] if len(raw_count) > 0 else 0)
            summary_data['Analytics_Player_Records'].append(analytics_count[0] if len(analytics_count) > 0 else 0)
            summary_data['Raw_Games'].append(games_count[0] if len(games_count) > 0 else 0)
            summary_data['Predictions'].append(pred_count[0] if len(pred_count) > 0 else 0)

        summary_df = pd.DataFrame(summary_data)
        summary_df['Discrepancy'] = summary_df['Raw_Player_Records'] - summary_df['Analytics_Player_Records']

        print(summary_df.to_string(index=False))

        print_section("VERIFICATION COMPLETE")

    def run_all_checks(self):
        """Run all verification checks."""
        print_section("DATABASE DATA COMPLETENESS AND QUALITY VERIFICATION")
        print(f"Project: {self.project_id}")
        print(f"Target Dates: {', '.join(self.target_dates)}")
        print(f"Execution Time: {datetime.now()}")

        self.verify_record_counts()
        self.check_quality_issues()
        self.analyze_discrepancies()
        self.check_historical_range()
        self.verify_game_schedule()
        self.generate_summary()


def main():
    # Get project ID from gcloud config or environment
    try:
        import subprocess
        result = subprocess.run(['gcloud', 'config', 'get-value', 'project'],
                              capture_output=True, text=True, check=True)
        project_id = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        # CalledProcessError: gcloud command failed
        # FileNotFoundError: gcloud not installed
        # OSError: other OS-level errors
        project_id = os.getenv('GCP_PROJECT_ID', 'nba-props-platform')

    # Target dates for verification
    target_dates = ['2026-01-19', '2026-01-20', '2026-01-21']

    verifier = DatabaseVerifier(project_id, target_dates)
    verifier.run_all_checks()


if __name__ == "__main__":
    main()
