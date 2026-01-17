#!/usr/bin/env python3
"""
Statistical Analysis of V1.6 Predictions and Grading

Different validation angles:
1. Daily prediction volume analysis
2. Model version consistency
3. Statistical distribution analysis
4. Edge value analysis
5. Confidence calibration
6. Pitcher coverage analysis
7. Team coverage analysis
8. Temporal trend analysis

Usage:
    PYTHONPATH=. python scripts/mlb/validate_v1_6_statistical_analysis.py
    PYTHONPATH=. python scripts/mlb/validate_v1_6_statistical_analysis.py --export-csv
"""

import argparse
from datetime import datetime, timedelta
import sys

import pandas as pd
import numpy as np
from google.cloud import bigquery
from tabulate import tabulate


PROJECT_ID = "nba-props-platform"


class StatisticalValidator:
    """Statistical analysis of v1.6 predictions"""

    def __init__(self, export_csv: bool = False):
        self.client = bigquery.Client(project=PROJECT_ID)
        self.export_csv = export_csv
        self.results = {}

    def run_all_analyses(self):
        """Run all statistical analyses"""
        print("=" * 80)
        print(" V1.6 STATISTICAL VALIDATION & ANALYSIS")
        print("=" * 80)
        print()

        # 1. Daily volume analysis
        print("\n1️⃣  DAILY PREDICTION VOLUME ANALYSIS")
        print("-" * 80)
        self.analyze_daily_volume()

        # 2. Model version tracking
        print("\n2️⃣  MODEL VERSION ANALYSIS")
        print("-" * 80)
        self.analyze_model_versions()

        # 3. Statistical distributions
        print("\n3️⃣  STATISTICAL DISTRIBUTIONS")
        print("-" * 80)
        self.analyze_distributions()

        # 4. Edge value analysis
        print("\n4️⃣  EDGE VALUE ANALYSIS")
        print("-" * 80)
        self.analyze_edge_values()

        # 5. Confidence calibration
        print("\n5️⃣  CONFIDENCE CALIBRATION")
        print("-" * 80)
        self.analyze_confidence_calibration()

        # 6. Pitcher coverage
        print("\n6️⃣  PITCHER COVERAGE ANALYSIS")
        print("-" * 80)
        self.analyze_pitcher_coverage()

        # 7. Team coverage
        print("\n7️⃣  TEAM COVERAGE ANALYSIS")
        print("-" * 80)
        self.analyze_team_coverage()

        # 8. Temporal trends
        print("\n8️⃣  TEMPORAL TREND ANALYSIS")
        print("-" * 80)
        self.analyze_temporal_trends()

        # 9. Grading lag analysis
        print("\n9️⃣  GRADING LAG ANALYSIS")
        print("-" * 80)
        self.analyze_grading_lag()

        # Summary
        self.print_summary()

    def analyze_daily_volume(self):
        """Analyze daily prediction volumes"""
        query = f"""
        SELECT
            game_date,
            COUNT(*) as predictions,
            COUNT(DISTINCT pitcher_lookup) as unique_pitchers,
            COUNTIF(is_correct IS NOT NULL) as graded,
            AVG(predicted_strikeouts) as avg_prediction,
            AVG(CASE WHEN actual_strikeouts IS NOT NULL THEN actual_strikeouts END) as avg_actual
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE model_version LIKE '%v1_6%'
          AND game_date >= '2022-01-01'
        GROUP BY game_date
        ORDER BY game_date DESC
        """

        df = self.client.query(query).to_dataframe()
        self.results['daily_volume'] = df

        if len(df) == 0:
            print("❌ No predictions found")
            return

        print(f"📊 Total days with predictions: {len(df)}")
        print(f"📊 Date range: {df['game_date'].min()} to {df['game_date'].max()}")
        print(f"📊 Avg predictions per day: {df['predictions'].mean():.1f}")
        print(f"📊 Median predictions per day: {df['predictions'].median():.1f}")
        print(f"📊 Min/Max predictions per day: {df['predictions'].min()}/{df['predictions'].max()}")

        # Check for days with unusually low volume
        low_volume_days = df[df['predictions'] < 5]
        if len(low_volume_days) > 0:
            print(f"\n⚠️  {len(low_volume_days)} days with <5 predictions:")
            for _, row in low_volume_days.head(10).iterrows():
                print(f"  {row['game_date']}: {row['predictions']} predictions")

        # Check for gaps in coverage
        df['game_date'] = pd.to_datetime(df['game_date'])
        df = df.sort_values('game_date')
        df['days_since_last'] = df['game_date'].diff().dt.days

        gaps = df[df['days_since_last'] > 7]  # More than 1 week gap
        if len(gaps) > 0:
            print(f"\n⚠️  {len(gaps)} gaps >7 days between predictions:")
            for _, row in gaps.iterrows():
                print(f"  {row['game_date']}: {row['days_since_last']} days since last prediction")

        if self.export_csv:
            df.to_csv('v1_6_daily_volume.csv', index=False)
            print("\n💾 Exported to v1_6_daily_volume.csv")

    def analyze_model_versions(self):
        """Check model version consistency"""
        query = f"""
        SELECT
            model_version,
            COUNT(*) as predictions,
            MIN(game_date) as first_date,
            MAX(game_date) as last_date,
            COUNTIF(is_correct IS NOT NULL) as graded,
            AVG(CASE WHEN is_correct IS NOT NULL THEN
                CASE WHEN is_correct THEN 1.0 ELSE 0.0 END
            END) as win_rate
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '2022-01-01'
        GROUP BY model_version
        ORDER BY first_date DESC
        """

        df = self.client.query(query).to_dataframe()

        print("📋 Model versions found:")
        print(tabulate(df, headers='keys', tablefmt='simple', showindex=False))

        v16_versions = df[df['model_version'].str.contains('v1_6', na=False)]
        if len(v16_versions) == 0:
            print("\n❌ No v1.6 versions found")
        else:
            print(f"\n✅ {len(v16_versions)} v1.6 version(s) found")
            total_v16 = v16_versions['predictions'].sum()
            print(f"✅ Total v1.6 predictions: {total_v16:,}")

    def analyze_distributions(self):
        """Analyze statistical distributions"""
        query = f"""
        SELECT
            predicted_strikeouts,
            actual_strikeouts,
            confidence,
            strikeouts_line,
            ABS(predicted_strikeouts - actual_strikeouts) as error
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE model_version LIKE '%v1_6%'
          AND actual_strikeouts IS NOT NULL
          AND game_date >= '2022-01-01'
        """

        df = self.client.query(query).to_dataframe()

        if len(df) == 0:
            print("❌ No graded predictions found")
            return

        print(f"📊 Prediction distribution:")
        print(f"  Mean: {df['predicted_strikeouts'].mean():.2f}")
        print(f"  Median: {df['predicted_strikeouts'].median():.2f}")
        print(f"  Std Dev: {df['predicted_strikeouts'].std():.2f}")
        print(f"  Min/Max: {df['predicted_strikeouts'].min():.2f}/{df['predicted_strikeouts'].max():.2f}")
        print(f"  25th/75th percentile: {df['predicted_strikeouts'].quantile(0.25):.2f}/{df['predicted_strikeouts'].quantile(0.75):.2f}")

        print(f"\n📊 Actual strikeouts distribution:")
        print(f"  Mean: {df['actual_strikeouts'].mean():.2f}")
        print(f"  Median: {df['actual_strikeouts'].median():.2f}")
        print(f"  Std Dev: {df['actual_strikeouts'].std():.2f}")

        print(f"\n📊 Error distribution (MAE):")
        print(f"  Mean: {df['error'].mean():.2f}")
        print(f"  Median: {df['error'].median():.2f}")
        print(f"  90th percentile: {df['error'].quantile(0.9):.2f}")

        # Check if predictions are biased
        bias = df['predicted_strikeouts'].mean() - df['actual_strikeouts'].mean()
        print(f"\n📊 Prediction bias: {bias:+.2f} (positive = over-predicting)")
        if abs(bias) < 0.3:
            print("  ✅ Low bias - predictions well-calibrated")
        elif abs(bias) < 0.7:
            print("  ⚠️  Moderate bias detected")
        else:
            print("  ❌ High bias - systematic over/under prediction")

    def analyze_edge_values(self):
        """Analyze edge values and betting recommendations"""
        query = f"""
        SELECT
            recommendation,
            COUNT(*) as bets,
            AVG(predicted_strikeouts - strikeouts_line) as avg_edge,
            AVG(confidence) as avg_confidence,
            COUNTIF(is_correct = TRUE) as wins,
            COUNTIF(is_correct = FALSE) as losses,
            COUNTIF(is_correct IS NULL AND recommendation IN ('OVER', 'UNDER')) as pushes
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE model_version LIKE '%v1_6%'
          AND strikeouts_line IS NOT NULL
          AND game_date >= '2022-01-01'
        GROUP BY recommendation
        ORDER BY bets DESC
        """

        df = self.client.query(query).to_dataframe()

        if len(df) == 0:
            print("❌ No predictions with betting lines found")
            return

        df['win_rate'] = (df['wins'] / (df['wins'] + df['losses']) * 100).round(1)

        print("📊 Recommendation breakdown:")
        print(tabulate(df, headers='keys', tablefmt='simple', showindex=False))

        # Analyze edge buckets
        edge_query = f"""
        SELECT
            CASE
                WHEN ABS(predicted_strikeouts - strikeouts_line) < 0.5 THEN 'Small (<0.5)'
                WHEN ABS(predicted_strikeouts - strikeouts_line) < 1.0 THEN 'Medium (0.5-1.0)'
                WHEN ABS(predicted_strikeouts - strikeouts_line) < 1.5 THEN 'Large (1.0-1.5)'
                ELSE 'Very Large (>1.5)'
            END as edge_bucket,
            COUNT(*) as bets,
            COUNTIF(is_correct = TRUE) as wins,
            COUNTIF(is_correct = FALSE) as losses,
            AVG(confidence) as avg_confidence
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE model_version LIKE '%v1_6%'
          AND strikeouts_line IS NOT NULL
          AND recommendation IN ('OVER', 'UNDER')
          AND is_correct IS NOT NULL
          AND game_date >= '2022-01-01'
        GROUP BY edge_bucket
        ORDER BY
            CASE edge_bucket
                WHEN 'Small (<0.5)' THEN 1
                WHEN 'Medium (0.5-1.0)' THEN 2
                WHEN 'Large (1.0-1.5)' THEN 3
                ELSE 4
            END
        """

        edge_df = self.client.query(edge_query).to_dataframe()
        if len(edge_df) > 0:
            edge_df['win_rate'] = (edge_df['wins'] / (edge_df['wins'] + edge_df['losses']) * 100).round(1)
            print("\n📊 Win rate by edge size:")
            print(tabulate(edge_df, headers='keys', tablefmt='simple', showindex=False))

    def analyze_confidence_calibration(self):
        """Check if confidence scores are calibrated"""
        query = f"""
        SELECT
            CASE
                WHEN confidence < 60 THEN '50-60'
                WHEN confidence < 70 THEN '60-70'
                WHEN confidence < 80 THEN '70-80'
                WHEN confidence < 90 THEN '80-90'
                ELSE '90-100'
            END as confidence_bucket,
            COUNT(*) as bets,
            COUNTIF(is_correct = TRUE) as wins,
            COUNTIF(is_correct = FALSE) as losses,
            AVG(confidence) as avg_confidence
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE model_version LIKE '%v1_6%'
          AND recommendation IN ('OVER', 'UNDER')
          AND is_correct IS NOT NULL
          AND game_date >= '2022-01-01'
        GROUP BY confidence_bucket
        ORDER BY avg_confidence
        """

        df = self.client.query(query).to_dataframe()

        if len(df) == 0:
            print("❌ No graded bets found")
            return

        df['win_rate'] = (df['wins'] / (df['wins'] + df['losses']) * 100).round(1)

        print("📊 Win rate by confidence level:")
        print(tabulate(df, headers='keys', tablefmt='simple', showindex=False))

        # Check if higher confidence = higher win rate
        if len(df) > 1:
            correlation = np.corrcoef(df['avg_confidence'], df['win_rate'])[0, 1]
            print(f"\n📊 Confidence-WinRate correlation: {correlation:.3f}")
            if correlation > 0.5:
                print("  ✅ Strong positive correlation - well calibrated")
            elif correlation > 0:
                print("  ⚠️  Weak positive correlation")
            else:
                print("  ❌ Negative or no correlation - poorly calibrated")

    def analyze_pitcher_coverage(self):
        """Analyze which pitchers have predictions"""
        query = f"""
        SELECT
            COUNT(DISTINCT pitcher_lookup) as unique_pitchers,
            COUNT(*) as total_predictions,
            AVG(predictions_per_pitcher) as avg_per_pitcher,
            MIN(predictions_per_pitcher) as min_per_pitcher,
            MAX(predictions_per_pitcher) as max_per_pitcher
        FROM (
            SELECT
                pitcher_lookup,
                COUNT(*) as predictions_per_pitcher
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
            WHERE model_version LIKE '%v1_6%'
              AND game_date >= '2022-01-01'
            GROUP BY pitcher_lookup
        )
        """

        result = list(self.client.query(query).result())[0]

        print(f"📊 Pitcher coverage:")
        print(f"  Unique pitchers: {result.unique_pitchers:,}")
        print(f"  Total predictions: {result.total_predictions:,}")
        print(f"  Avg predictions per pitcher: {result.avg_per_pitcher:.1f}")
        print(f"  Range: {result.min_per_pitcher}-{result.max_per_pitcher}")

        # Find top pitchers by prediction count
        top_query = f"""
        SELECT
            pitcher_lookup,
            COUNT(*) as predictions,
            COUNTIF(is_correct = TRUE) as wins,
            COUNTIF(is_correct = FALSE) as losses
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE model_version LIKE '%v1_6%'
          AND game_date >= '2022-01-01'
        GROUP BY pitcher_lookup
        ORDER BY predictions DESC
        LIMIT 10
        """

        top_df = self.client.query(top_query).to_dataframe()
        if len(top_df) > 0:
            top_df['win_rate'] = (top_df['wins'] / (top_df['wins'] + top_df['losses']) * 100).round(1)
            print("\n📊 Top 10 pitchers by prediction count:")
            print(tabulate(top_df, headers='keys', tablefmt='simple', showindex=False, maxcolwidths=30))

    def analyze_team_coverage(self):
        """Analyze team coverage"""
        query = f"""
        SELECT
            team_abbr,
            COUNT(*) as predictions,
            COUNTIF(is_correct = TRUE) as wins,
            COUNTIF(is_correct = FALSE) as losses
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE model_version LIKE '%v1_6%'
          AND game_date >= '2022-01-01'
          AND team_abbr IS NOT NULL
        GROUP BY team_abbr
        ORDER BY predictions DESC
        """

        df = self.client.query(query).to_dataframe()

        if len(df) == 0:
            print("❌ No team data found")
            return

        df['win_rate'] = (df['wins'] / (df['wins'] + df['losses']) * 100).round(1)

        print(f"📊 Team coverage: {len(df)} teams")
        print(f"  Avg predictions per team: {df['predictions'].mean():.1f}")
        print(f"  Min/Max: {df['predictions'].min()}/{df['predictions'].max()}")

        # Show teams with highest/lowest win rates
        if len(df) >= 5:
            print("\n📊 Top 5 teams by win rate:")
            top5 = df.nlargest(5, 'win_rate')
            print(tabulate(top5[['team_abbr', 'predictions', 'win_rate']], headers='keys', tablefmt='simple', showindex=False))

            print("\n📊 Bottom 5 teams by win rate:")
            bottom5 = df.nsmallest(5, 'win_rate')
            print(tabulate(bottom5[['team_abbr', 'predictions', 'win_rate']], headers='keys', tablefmt='simple', showindex=False))

    def analyze_temporal_trends(self):
        """Analyze performance trends over time"""
        query = f"""
        SELECT
            EXTRACT(YEAR FROM game_date) as year,
            EXTRACT(MONTH FROM game_date) as month,
            COUNT(*) as predictions,
            COUNTIF(is_correct = TRUE) as wins,
            COUNTIF(is_correct = FALSE) as losses,
            AVG(predicted_strikeouts - actual_strikeouts) as avg_error
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE model_version LIKE '%v1_6%'
          AND game_date >= '2022-01-01'
          AND is_correct IS NOT NULL
        GROUP BY year, month
        ORDER BY year DESC, month DESC
        """

        df = self.client.query(query).to_dataframe()

        if len(df) == 0:
            print("❌ No temporal data found")
            return

        df['win_rate'] = (df['wins'] / (df['wins'] + df['losses']) * 100).round(1)
        df['year_month'] = df['year'].astype(str) + '-' + df['month'].astype(str).str.zfill(2)

        print("📊 Monthly performance (last 12 months):")
        recent = df.head(12)
        print(tabulate(recent[['year_month', 'predictions', 'wins', 'losses', 'win_rate', 'avg_error']],
                      headers='keys', tablefmt='simple', showindex=False))

        # Check for performance degradation over time
        if len(df) >= 6:
            recent_6mo = df.head(6)['win_rate'].mean()
            older_6mo = df.tail(6)['win_rate'].mean()
            print(f"\n📊 Recent 6mo win rate: {recent_6mo:.1f}%")
            print(f"📊 Older 6mo win rate: {older_6mo:.1f}%")

            if recent_6mo > older_6mo + 2:
                print("  ✅ Improving performance over time")
            elif recent_6mo < older_6mo - 2:
                print("  ⚠️  Performance degrading over time")
            else:
                print("  ✅ Stable performance")

    def analyze_grading_lag(self):
        """Analyze delay between game and grading"""
        query = f"""
        SELECT
            game_date,
            graded_at,
            TIMESTAMP_DIFF(graded_at, TIMESTAMP(game_date), HOUR) as hours_to_grade
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE model_version LIKE '%v1_6%'
          AND graded_at IS NOT NULL
          AND game_date >= '2022-01-01'
        """

        df = self.client.query(query).to_dataframe()

        if len(df) == 0:
            print("❌ No graded predictions with timestamps found")
            return

        print(f"📊 Grading lag analysis:")
        print(f"  Median lag: {df['hours_to_grade'].median():.1f} hours")
        print(f"  Mean lag: {df['hours_to_grade'].mean():.1f} hours")
        print(f"  90th percentile: {df['hours_to_grade'].quantile(0.9):.1f} hours")
        print(f"  Max lag: {df['hours_to_grade'].max():.1f} hours")

        # Check for ungraded recent predictions
        ungraded_query = f"""
        SELECT COUNT(*) as ungraded_count
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE model_version LIKE '%v1_6%'
          AND is_correct IS NULL
          AND recommendation IN ('OVER', 'UNDER')
          AND game_date < CURRENT_DATE() - 2
          AND game_date >= '2022-01-01'
        """

        ungraded = list(self.client.query(ungraded_query).result())[0].ungraded_count
        if ungraded > 0:
            print(f"\n⚠️  {ungraded} predictions from >2 days ago still ungraded")

    def print_summary(self):
        """Print overall summary"""
        print("\n" + "=" * 80)
        print(" SUMMARY")
        print("=" * 80)

        if 'daily_volume' in self.results and len(self.results['daily_volume']) > 0:
            df = self.results['daily_volume']
            print(f"✅ {len(df)} days with v1.6 predictions")
            print(f"✅ Date range: {df['game_date'].min()} to {df['game_date'].max()}")
            print(f"✅ Total predictions: {df['predictions'].sum():,}")
            grading_pct = (df['graded'].sum() / df['predictions'].sum() * 100)
            print(f"✅ Grading completeness: {grading_pct:.1f}%")


def main():
    parser = argparse.ArgumentParser(description='Statistical validation of v1.6 predictions')
    parser.add_argument('--export-csv', action='store_true', help='Export results to CSV')
    args = parser.parse_args()

    validator = StatisticalValidator(export_csv=args.export_csv)
    validator.run_all_analyses()


if __name__ == '__main__':
    main()
