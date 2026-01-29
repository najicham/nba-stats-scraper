#!/usr/bin/env python3
"""
Additional Data Quality Validation for January 2026

This script provides complementary validation approaches beyond the standard
pipeline validation. It checks data quality from different perspectives:

1. Temporal Consistency - Verify data exists for all expected dates
2. Volume Analysis - Check for anomalies in record counts
3. Completeness Ratios - Verify player coverage vs schedule
4. Cross-Phase Consistency - Ensure data flows through all phases
5. Statistical Anomalies - Detect outliers in metrics
6. Missing Data Patterns - Identify systematic gaps

Usage:
    python3 bin/validation/validate_data_quality_january.py
    python3 bin/validation/validate_data_quality_january.py --start-date 2026-01-01
    python3 bin/validation/validate_data_quality_january.py --detailed
"""

import sys
import os
import argparse
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple
from collections import defaultdict

from google.cloud import bigquery
import pandas as pd

# Add project root to path using relative path from this file
_current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_current_dir, '..', '..'))

from shared.validation.config import PROJECT_ID

# ANSI color codes
GREEN = '\033[0;32m'
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color


def print_header(text: str):
    """Print a formatted header"""
    print(f"\n{BLUE}{'=' * 70}{NC}")
    print(f"{BLUE}  {text}{NC}")
    print(f"{BLUE}{'=' * 70}{NC}\n")


def print_section(text: str):
    """Print a formatted section header"""
    print(f"\n{BLUE}{text}{NC}")
    print(f"{'-' * len(text)}")


def print_success(text: str):
    """Print success message"""
    print(f"{GREEN}✓ {text}{NC}")


def print_warning(text: str):
    """Print warning message"""
    print(f"{YELLOW}⚠ {text}{NC}")


def print_error(text: str):
    """Print error message"""
    print(f"{RED}✗ {text}{NC}")


class DataQualityValidator:
    """Comprehensive data quality validator for January 2026"""

    def __init__(self, start_date: date, end_date: date, detailed: bool = False):
        self.start_date = start_date
        self.end_date = end_date
        self.detailed = detailed
        self.client = bigquery.Client(project=PROJECT_ID)
        self.issues = []

    def validate_all(self):
        """Run all validation checks"""
        print_header("Data Quality Validation for January 2026")

        # Check 1: Temporal consistency
        self.check_temporal_consistency()

        # Check 2: Volume analysis
        self.check_volume_anomalies()

        # Check 3: Completeness ratios
        self.check_completeness_ratios()

        # Check 4: Cross-phase consistency
        self.check_cross_phase_consistency()

        # Check 5: Statistical anomalies
        self.check_statistical_anomalies()

        # Check 6: Missing data patterns
        self.check_missing_data_patterns()

        # Final summary
        self.print_summary()

    def check_temporal_consistency(self):
        """Check if data exists for all expected dates"""
        print_section("1. Temporal Consistency Check")

        # Get distinct dates from schedule
        query = f"""
        SELECT DISTINCT game_date
        FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
        ORDER BY game_date
        """

        schedule_dates = set()
        for row in self.client.query(query):
            schedule_dates.add(row.game_date)

        print(f"Schedule has data for {len(schedule_dates)} distinct dates")

        # Check each phase for each date
        phases = {
            'Phase 2 (Raw)': 'nba_raw.nbac_player_boxscores',
            'Phase 3 (Analytics)': 'nba_analytics.player_game_summary',
            'Phase 4 (Precompute)': 'nba_precompute.ml_feature_store',
            'Phase 5 (Predictions)': 'nba_predictions.daily_predictions_catboost_v8',
        }

        missing_by_phase = defaultdict(list)

        for phase_name, table in phases.items():
            query = f"""
            SELECT DISTINCT game_date
            FROM `{PROJECT_ID}.{table}`
            WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            """

            phase_dates = set()
            for row in self.client.query(query):
                phase_dates.add(row.game_date)

            missing = schedule_dates - phase_dates
            if missing:
                missing_by_phase[phase_name] = sorted(missing)
                print_warning(f"{phase_name}: Missing {len(missing)} dates")
                if self.detailed:
                    for missing_date in sorted(missing):
                        print(f"  - {missing_date}")
            else:
                print_success(f"{phase_name}: All dates present")

        if missing_by_phase:
            self.issues.append(f"Temporal consistency: {len(missing_by_phase)} phases have missing dates")

    def check_volume_anomalies(self):
        """Check for anomalies in record counts per day"""
        print_section("2. Volume Analysis (Anomaly Detection)")

        # Check player boxscore volumes
        query = f"""
        SELECT
            game_date,
            COUNT(*) as player_count,
            COUNT(DISTINCT game_id) as game_count
        FROM `{PROJECT_ID}.nba_raw.nbac_player_boxscores`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
        GROUP BY game_date
        ORDER BY game_date
        """

        df = self.client.query(query).to_dataframe()

        if df.empty:
            print_error("No player boxscore data found!")
            self.issues.append("Volume analysis: No data found")
            return

        # Calculate statistics
        avg_players = df['player_count'].mean()
        std_players = df['player_count'].std()
        avg_games = df['game_count'].mean()

        print(f"Average players per day: {avg_players:.1f} (±{std_players:.1f})")
        print(f"Average games per day: {avg_games:.1f}")

        # Detect anomalies (more than 2 std deviations from mean)
        threshold_low = avg_players - (2 * std_players)
        threshold_high = avg_players + (2 * std_players)

        anomalies = df[
            (df['player_count'] < threshold_low) | (df['player_count'] > threshold_high)
        ]

        if not anomalies.empty:
            print_warning(f"Found {len(anomalies)} days with anomalous player counts:")
            for _, row in anomalies.iterrows():
                print(f"  - {row['game_date']}: {row['player_count']} players ({row['game_count']} games)")
            self.issues.append(f"Volume anomalies: {len(anomalies)} days outside normal range")
        else:
            print_success("No volume anomalies detected")

    def check_completeness_ratios(self):
        """Check player coverage vs expected from schedule"""
        print_section("3. Completeness Ratios")

        # For each day, compare actual vs expected players
        query = f"""
        WITH expected AS (
            SELECT
                game_date,
                COUNT(DISTINCT game_id) as game_count,
                -- Expect ~13 players per team, 2 teams per game
                COUNT(DISTINCT game_id) * 26 as expected_players
            FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
            WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            GROUP BY game_date
        ),
        actual AS (
            SELECT
                game_date,
                COUNT(*) as actual_players
            FROM `{PROJECT_ID}.nba_raw.nbac_player_boxscores`
            WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            GROUP BY game_date
        )
        SELECT
            e.game_date,
            e.game_count,
            e.expected_players,
            COALESCE(a.actual_players, 0) as actual_players,
            ROUND(COALESCE(a.actual_players, 0) / e.expected_players * 100, 1) as completeness_pct
        FROM expected e
        LEFT JOIN actual a ON e.game_date = a.game_date
        ORDER BY e.game_date
        """

        df = self.client.query(query).to_dataframe()

        avg_completeness = df['completeness_pct'].mean()
        print(f"Average completeness: {avg_completeness:.1f}%")

        # Flag days below 80% completeness
        incomplete = df[df['completeness_pct'] < 80.0]
        if not incomplete.empty:
            print_warning(f"Found {len(incomplete)} days with <80% completeness:")
            for _, row in incomplete.iterrows():
                print(
                    f"  - {row['game_date']}: {row['completeness_pct']:.1f}% "
                    f"({row['actual_players']}/{row['expected_players']} players)"
                )
            self.issues.append(f"Completeness: {len(incomplete)} days below 80%")
        else:
            print_success("All days have ≥80% completeness")

    def check_cross_phase_consistency(self):
        """Ensure data flows consistently through all phases"""
        print_section("4. Cross-Phase Consistency")

        # For each date, check player counts across phases
        query = f"""
        WITH phase2 AS (
            SELECT game_date, COUNT(DISTINCT player_lookup) as p2_players
            FROM `{PROJECT_ID}.nba_raw.nbac_player_boxscores`
            WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            GROUP BY game_date
        ),
        phase3 AS (
            SELECT game_date, COUNT(DISTINCT player_lookup) as p3_players
            FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
            WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            GROUP BY game_date
        ),
        phase4 AS (
            SELECT game_date, COUNT(DISTINCT player_lookup) as p4_players
            FROM `{PROJECT_ID}.nba_precompute.player_daily_cache`
            WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            GROUP BY game_date
        )
        SELECT
            p2.game_date,
            p2.p2_players,
            COALESCE(p3.p3_players, 0) as p3_players,
            COALESCE(p4.p4_players, 0) as p4_players,
            -- Check if each phase has at least 90% of previous phase
            CASE
                WHEN COALESCE(p3.p3_players, 0) < p2.p2_players * 0.9 THEN 'P2→P3 drop'
                WHEN COALESCE(p4.p4_players, 0) < COALESCE(p3.p3_players, 0) * 0.9 THEN 'P3→P4 drop'
                ELSE 'OK'
            END as status
        FROM phase2 p2
        LEFT JOIN phase3 p3 ON p2.game_date = p3.game_date
        LEFT JOIN phase4 p4 ON p2.game_date = p4.game_date
        ORDER BY p2.game_date
        """

        df = self.client.query(query).to_dataframe()

        consistency_issues = df[df['status'] != 'OK']
        if not consistency_issues.empty:
            print_warning(f"Found {len(consistency_issues)} days with >10% player drop between phases:")
            for _, row in consistency_issues.iterrows():
                print(
                    f"  - {row['game_date']}: {row['status']} "
                    f"(P2:{row['p2_players']} → P3:{row['p3_players']} → P4:{row['p4_players']})"
                )
            self.issues.append(f"Cross-phase consistency: {len(consistency_issues)} days with data loss")
        else:
            print_success("All days have consistent player counts across phases")

    def check_statistical_anomalies(self):
        """Check for statistical outliers in key metrics"""
        print_section("5. Statistical Anomalies in Metrics")

        # Check for unrealistic values in player stats
        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_players,
            COUNTIF(points < 0) as negative_points,
            COUNTIF(points > 100) as extreme_points,
            COUNTIF(minutes > 60) as extreme_minutes,
            COUNTIF(fgm > fga) as fgm_gt_fga,
            COUNTIF(ftm > fta) as ftm_gt_fta
        FROM `{PROJECT_ID}.nba_raw.nbac_player_boxscores`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
        GROUP BY game_date
        HAVING
            negative_points > 0 OR
            extreme_points > 0 OR
            extreme_minutes > 0 OR
            fgm_gt_fga > 0 OR
            ftm_gt_fta > 0
        ORDER BY game_date
        """

        df = self.client.query(query).to_dataframe()

        if not df.empty:
            print_warning(f"Found {len(df)} days with statistical anomalies:")
            for _, row in df.iterrows():
                anomalies = []
                if row['negative_points'] > 0:
                    anomalies.append(f"{row['negative_points']} negative points")
                if row['extreme_points'] > 0:
                    anomalies.append(f"{row['extreme_points']} extreme points (>100)")
                if row['extreme_minutes'] > 0:
                    anomalies.append(f"{row['extreme_minutes']} extreme minutes (>60)")
                if row['fgm_gt_fga'] > 0:
                    anomalies.append(f"{row['fgm_gt_fga']} FGM>FGA")
                if row['ftm_gt_fta'] > 0:
                    anomalies.append(f"{row['ftm_gt_fta']} FTM>FTA")

                print(f"  - {row['game_date']}: {', '.join(anomalies)}")
            self.issues.append(f"Statistical anomalies: {len(df)} days with unrealistic values")
        else:
            print_success("No statistical anomalies detected")

    def check_missing_data_patterns(self):
        """Identify systematic gaps in data"""
        print_section("6. Missing Data Patterns")

        # Check for missing key columns
        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_records,
            COUNTIF(player_lookup IS NULL) as missing_player_lookup,
            COUNTIF(team IS NULL) as missing_team,
            COUNTIF(minutes IS NULL) as missing_minutes,
            COUNTIF(points IS NULL) as missing_points
        FROM `{PROJECT_ID}.nba_raw.nbac_player_boxscores`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
        GROUP BY game_date
        HAVING
            missing_player_lookup > 0 OR
            missing_team > 0 OR
            missing_minutes > 0 OR
            missing_points > 0
        ORDER BY game_date
        """

        df = self.client.query(query).to_dataframe()

        if not df.empty:
            print_warning(f"Found {len(df)} days with NULL values in key columns:")
            for _, row in df.iterrows():
                missing = []
                if row['missing_player_lookup'] > 0:
                    missing.append(f"{row['missing_player_lookup']} player_lookup")
                if row['missing_team'] > 0:
                    missing.append(f"{row['missing_team']} team")
                if row['missing_minutes'] > 0:
                    missing.append(f"{row['missing_minutes']} minutes")
                if row['missing_points'] > 0:
                    missing.append(f"{row['missing_points']} points")

                print(f"  - {row['game_date']}: {', '.join(missing)}")
            self.issues.append(f"Missing data: {len(df)} days with NULL values")
        else:
            print_success("No NULL values detected in key columns")

    def print_summary(self):
        """Print final summary"""
        print_header("Validation Summary")

        if not self.issues:
            print_success("✓ All data quality checks passed!")
            print("No issues detected for January 2026.")
        else:
            print_error(f"Found {len(self.issues)} issue categories:")
            for i, issue in enumerate(self.issues, 1):
                print(f"  {i}. {issue}")

        print()


def main():
    parser = argparse.ArgumentParser(description="Data quality validation for January 2026")
    parser.add_argument(
        '--start-date',
        type=str,
        default='2026-01-01',
        help='Start date (YYYY-MM-DD)',
    )
    parser.add_argument(
        '--end-date',
        type=str,
        default='2026-01-21',
        help='End date (YYYY-MM-DD)',
    )
    parser.add_argument(
        '--detailed',
        action='store_true',
        help='Show detailed output for each issue',
    )

    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

    validator = DataQualityValidator(start_date, end_date, args.detailed)
    validator.validate_all()


if __name__ == '__main__':
    main()
