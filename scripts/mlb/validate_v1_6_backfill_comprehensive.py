#!/usr/bin/env python3
"""
Comprehensive Validation of V1.6 MLB Prediction Backfill

Validates that:
1. Predictions exist for all historical games (past 4 seasons)
2. All predictions were graded with actual results
3. Data quality and coverage metrics
4. Model performance analysis
5. Feature completeness
6. Temporal coverage (no gaps)

Usage:
    PYTHONPATH=. python scripts/mlb/validate_v1_6_backfill_comprehensive.py
    PYTHONPATH=. python scripts/mlb/validate_v1_6_backfill_comprehensive.py --seasons 2024,2025
    PYTHONPATH=. python scripts/mlb/validate_v1_6_backfill_comprehensive.py --verbose
"""

import argparse
from collections import defaultdict
from datetime import datetime, date
from typing import Dict, List, Tuple
import sys

import pandas as pd
from google.cloud import bigquery
from tabulate import tabulate


PROJECT_ID = "nba-props-platform"
MODEL_VERSION_V16 = "mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149"

# MLB seasons typically run from early April to late September/October
MLB_SEASON_DATES = {
    2022: ('2022-04-07', '2022-10-05'),
    2023: ('2023-03-30', '2023-10-01'),
    2024: ('2024-03-20', '2024-09-29'),
    2025: ('2025-03-27', '2025-09-28'),  # Approximate
}


class ValidationReport:
    """Accumulates validation results"""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []
        self.metrics = {}

    def error(self, msg: str):
        self.errors.append(msg)
        print(f"❌ ERROR: {msg}")

    def warning(self, msg: str):
        self.warnings.append(msg)
        print(f"⚠️  WARNING: {msg}")

    def info(self, msg: str):
        self.info.append(msg)
        print(f"✅ {msg}")

    def add_metric(self, name: str, value):
        self.metrics[name] = value

    def summary(self):
        print("\n" + "=" * 80)
        print(" VALIDATION SUMMARY")
        print("=" * 80)
        print(f"Errors: {len(self.errors)}")
        print(f"Warnings: {len(self.warnings)}")
        print(f"Info: {len(self.info)}")

        if self.errors:
            print("\n🔴 VALIDATION FAILED")
            print("\nErrors:")
            for err in self.errors:
                print(f"  - {err}")
        else:
            print("\n🟢 VALIDATION PASSED")

        if self.warnings:
            print("\nWarnings:")
            for warn in self.warnings:
                print(f"  - {warn}")

        return len(self.errors) == 0


class V16BackfillValidator:
    """Comprehensive validation of v1.6 backfill"""

    def __init__(self, seasons: List[int], verbose: bool = False):
        self.client = bigquery.Client(project=PROJECT_ID)
        self.seasons = seasons
        self.verbose = verbose
        self.report = ValidationReport()

    def validate_all(self) -> bool:
        """Run all validation checks"""
        print("=" * 80)
        print(" V1.6 BACKFILL COMPREHENSIVE VALIDATION")
        print("=" * 80)
        print(f"Seasons: {', '.join(map(str, self.seasons))}")
        print(f"Model: {MODEL_VERSION_V16}")
        print()

        # 1. Check prediction existence
        print("\n1️⃣  CHECKING PREDICTION EXISTENCE")
        print("-" * 80)
        self.check_prediction_existence()

        # 2. Check grading completeness
        print("\n2️⃣  CHECKING GRADING COMPLETENESS")
        print("-" * 80)
        self.check_grading_completeness()

        # 3. Check temporal coverage (no gaps)
        print("\n3️⃣  CHECKING TEMPORAL COVERAGE")
        print("-" * 80)
        self.check_temporal_coverage()

        # 4. Check feature completeness
        print("\n4️⃣  CHECKING FEATURE COMPLETENESS")
        print("-" * 80)
        self.check_feature_completeness()

        # 5. Validate model performance
        print("\n5️⃣  VALIDATING MODEL PERFORMANCE")
        print("-" * 80)
        self.validate_model_performance()

        # 6. Check data quality
        print("\n6️⃣  CHECKING DATA QUALITY")
        print("-" * 80)
        self.check_data_quality()

        # 7. Verify v1.6 specific features
        print("\n7️⃣  VERIFYING V1.6 FEATURES")
        print("-" * 80)
        self.verify_v16_features()

        # 8. Cross-reference with raw data
        print("\n8️⃣  CROSS-REFERENCING WITH RAW DATA")
        print("-" * 80)
        self.cross_reference_raw_data()

        return self.report.summary()

    def check_prediction_existence(self):
        """Check that predictions exist for historical games"""
        for season in self.seasons:
            start_date, end_date = MLB_SEASON_DATES[season]

            # Get count of games with starting pitchers
            games_query = f"""
            SELECT
                COUNT(DISTINCT CONCAT(game_date, '|', player_lookup)) as game_count
            FROM `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND is_starter = TRUE
              AND innings_pitched >= 3.0
            """

            # Get count of v1.6 predictions
            preds_query = f"""
            SELECT
                COUNT(*) as prediction_count,
                COUNT(DISTINCT game_date) as unique_dates
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND model_version LIKE '%v1_6%'
            """

            games_result = list(self.client.query(games_query).result())[0]
            preds_result = list(self.client.query(preds_query).result())[0]

            games_count = games_result.game_count
            preds_count = preds_result.prediction_count
            unique_dates = preds_result.unique_dates

            coverage_pct = (preds_count / games_count * 100) if games_count > 0 else 0

            self.report.add_metric(f"season_{season}_games", games_count)
            self.report.add_metric(f"season_{season}_predictions", preds_count)
            self.report.add_metric(f"season_{season}_coverage_pct", coverage_pct)

            if coverage_pct >= 95:
                self.report.info(f"Season {season}: {preds_count:,} predictions for {games_count:,} games ({coverage_pct:.1f}% coverage)")
            elif coverage_pct >= 80:
                self.report.warning(f"Season {season}: Only {coverage_pct:.1f}% coverage ({preds_count:,}/{games_count:,})")
            else:
                self.report.error(f"Season {season}: Low coverage {coverage_pct:.1f}% ({preds_count:,}/{games_count:,})")

            if self.verbose:
                print(f"  Season {season}: {unique_dates} unique game dates")

    def check_grading_completeness(self):
        """Check that all predictions were graded"""
        for season in self.seasons:
            start_date, end_date = MLB_SEASON_DATES[season]

            query = f"""
            SELECT
                COUNT(*) as total_predictions,
                COUNTIF(is_correct IS NOT NULL) as graded,
                COUNTIF(actual_strikeouts IS NOT NULL) as has_actuals,
                COUNTIF(is_correct IS NULL AND recommendation IN ('OVER', 'UNDER')) as needs_grading
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND model_version LIKE '%v1_6%'
            """

            result = list(self.client.query(query).result())[0]

            total = result.total_predictions
            graded = result.graded
            has_actuals = result.has_actuals
            needs_grading = result.needs_grading

            grading_pct = (graded / total * 100) if total > 0 else 0
            actuals_pct = (has_actuals / total * 100) if total > 0 else 0

            self.report.add_metric(f"season_{season}_grading_pct", grading_pct)

            if grading_pct >= 95 and needs_grading == 0:
                self.report.info(f"Season {season}: {graded:,}/{total:,} predictions graded ({grading_pct:.1f}%)")
            elif needs_grading > 0:
                self.report.warning(f"Season {season}: {needs_grading:,} predictions need grading")
            else:
                self.report.error(f"Season {season}: Only {grading_pct:.1f}% graded")

            if actuals_pct < 95:
                self.report.warning(f"Season {season}: Only {actuals_pct:.1f}% have actual_strikeouts populated")

    def check_temporal_coverage(self):
        """Check for date gaps in predictions"""
        for season in self.seasons:
            start_date, end_date = MLB_SEASON_DATES[season]

            # Get all dates with games
            games_dates_query = f"""
            SELECT DISTINCT game_date
            FROM `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND is_starter = TRUE
            ORDER BY game_date
            """

            # Get all dates with predictions
            pred_dates_query = f"""
            SELECT DISTINCT game_date
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND model_version LIKE '%v1_6%'
            ORDER BY game_date
            """

            game_dates = {row.game_date for row in self.client.query(games_dates_query).result()}
            pred_dates = {row.game_date for row in self.client.query(pred_dates_query).result()}

            missing_dates = sorted(game_dates - pred_dates)

            if not missing_dates:
                self.report.info(f"Season {season}: No date gaps ({len(pred_dates)} days covered)")
            elif len(missing_dates) <= 5:
                self.report.warning(f"Season {season}: {len(missing_dates)} dates missing predictions: {missing_dates}")
            else:
                self.report.error(f"Season {season}: {len(missing_dates)} dates missing predictions")
                if self.verbose:
                    print(f"  Missing dates (first 10): {missing_dates[:10]}")

    def check_feature_completeness(self):
        """Check that predictions have necessary features/fields populated"""
        for season in self.seasons:
            start_date, end_date = MLB_SEASON_DATES[season]

            query = f"""
            SELECT
                COUNT(*) as total,
                COUNTIF(predicted_strikeouts IS NOT NULL) as has_prediction,
                COUNTIF(confidence IS NOT NULL) as has_confidence,
                COUNTIF(strikeouts_line IS NOT NULL) as has_line,
                COUNTIF(recommendation IS NOT NULL) as has_recommendation,
                COUNTIF(pitcher_lookup IS NOT NULL) as has_pitcher,
                COUNTIF(game_date IS NOT NULL) as has_date,
                AVG(confidence) as avg_confidence,
                AVG(CASE WHEN strikeouts_line IS NOT NULL THEN predicted_strikeouts - strikeouts_line END) as avg_edge
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND model_version LIKE '%v1_6%'
            """

            result = list(self.client.query(query).result())[0]

            total = result.total
            completeness_checks = [
                ('prediction', result.has_prediction),
                ('confidence', result.has_confidence),
                ('line', result.has_line),
                ('recommendation', result.has_recommendation),
            ]

            all_complete = True
            for field, count in completeness_checks:
                pct = (count / total * 100) if total > 0 else 0
                if pct < 95:
                    self.report.warning(f"Season {season}: {field} only {pct:.1f}% populated")
                    all_complete = False

            if all_complete:
                self.report.info(f"Season {season}: All essential fields populated (avg confidence: {result.avg_confidence:.2f})")

            if result.has_line > 0:
                line_coverage = (result.has_line / total * 100)
                if self.verbose:
                    print(f"  Line coverage: {line_coverage:.1f}%, avg edge: {result.avg_edge:.2f}K")

    def validate_model_performance(self):
        """Validate model accuracy metrics"""
        for season in self.seasons:
            start_date, end_date = MLB_SEASON_DATES[season]

            query = f"""
            WITH predictions AS (
                SELECT
                    predicted_strikeouts,
                    actual_strikeouts,
                    strikeouts_line,
                    is_correct,
                    recommendation
                FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
                WHERE game_date >= '{start_date}'
                  AND game_date <= '{end_date}'
                  AND model_version LIKE '%v1_6%'
                  AND actual_strikeouts IS NOT NULL
            )
            SELECT
                COUNT(*) as total,
                AVG(ABS(predicted_strikeouts - actual_strikeouts)) as mae,
                SQRT(AVG(POW(predicted_strikeouts - actual_strikeouts, 2))) as rmse,
                COUNTIF(is_correct = TRUE) as correct,
                COUNTIF(is_correct = FALSE) as incorrect,
                COUNTIF(is_correct IS NULL AND recommendation IN ('OVER', 'UNDER')) as push,
                COUNTIF(recommendation = 'OVER') as over_bets,
                COUNTIF(recommendation = 'UNDER') as under_bets,
                COUNTIF(recommendation = 'PASS') as pass_bets
            FROM predictions
            """

            result = list(self.client.query(query).result())[0]

            total = result.total
            mae = result.mae
            rmse = result.rmse
            correct = result.correct
            incorrect = result.incorrect

            if total == 0:
                self.report.warning(f"Season {season}: No graded predictions found")
                continue

            win_rate = (correct / (correct + incorrect) * 100) if (correct + incorrect) > 0 else 0

            self.report.add_metric(f"season_{season}_mae", mae)
            self.report.add_metric(f"season_{season}_win_rate", win_rate)

            # Expected MAE for pitcher strikeouts is typically 1.5-2.5
            if mae <= 2.0:
                self.report.info(f"Season {season}: MAE {mae:.2f}, RMSE {rmse:.2f} - Good accuracy")
            elif mae <= 3.0:
                self.report.warning(f"Season {season}: MAE {mae:.2f} - Acceptable but could be better")
            else:
                self.report.error(f"Season {season}: MAE {mae:.2f} - Poor accuracy")

            # Win rate should be >50% for a profitable model
            if win_rate >= 55:
                self.report.info(f"Season {season}: Win rate {win_rate:.1f}% ({correct}/{correct+incorrect}) - Profitable")
            elif win_rate >= 50:
                self.report.warning(f"Season {season}: Win rate {win_rate:.1f}% - Break-even")
            else:
                self.report.error(f"Season {season}: Win rate {win_rate:.1f}% - Unprofitable")

            if self.verbose:
                print(f"  Over bets: {result.over_bets}, Under bets: {result.under_bets}, Pass: {result.pass_bets}, Push: {result.push}")

    def check_data_quality(self):
        """Check for data anomalies and quality issues"""
        for season in self.seasons:
            start_date, end_date = MLB_SEASON_DATES[season]

            query = f"""
            SELECT
                COUNT(*) as total,
                COUNTIF(predicted_strikeouts < 0) as negative_predictions,
                COUNTIF(predicted_strikeouts > 20) as extreme_predictions,
                COUNTIF(confidence < 0 OR confidence > 100) as invalid_confidence,
                COUNTIF(actual_strikeouts < 0) as negative_actuals,
                COUNTIF(ABS(predicted_strikeouts - actual_strikeouts) > 10) as large_errors,
                MIN(predicted_strikeouts) as min_pred,
                MAX(predicted_strikeouts) as max_pred,
                AVG(predicted_strikeouts) as avg_pred,
                AVG(actual_strikeouts) as avg_actual
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND model_version LIKE '%v1_6%'
            """

            result = list(self.client.query(query).result())[0]

            issues = []
            if result.negative_predictions > 0:
                issues.append(f"{result.negative_predictions} negative predictions")
            if result.extreme_predictions > 0:
                issues.append(f"{result.extreme_predictions} predictions >20K")
            if result.invalid_confidence > 0:
                issues.append(f"{result.invalid_confidence} invalid confidence scores")
            if result.negative_actuals > 0:
                issues.append(f"{result.negative_actuals} negative actuals")
            if result.large_errors > 0:
                issues.append(f"{result.large_errors} errors >10K")

            if not issues:
                self.report.info(f"Season {season}: No data quality issues detected".format(season=season))
            else:
                for issue in issues:
                    self.report.warning(f"Season {season}: {issue}")

            if self.verbose:
                print(f"  Prediction range: {result.min_pred:.1f} - {result.max_pred:.1f} (avg: {result.avg_pred:.1f})")
                print(f"  Actual range: avg: {result.avg_actual:.1f}")

    def verify_v16_features(self):
        """Verify v1.6 specific features (rolling statcast)"""
        # V1.6 introduced rolling statcast features:
        # - f50_swstr_pct_last_3
        # - f51_fb_velocity_last_3
        # - f52_swstr_trend
        # - f53_velocity_change

        # These should be in pitcher_rolling_statcast table
        for season in self.seasons:
            start_date, end_date = MLB_SEASON_DATES[season]

            query = f"""
            SELECT
                COUNT(DISTINCT player_lookup) as pitchers,
                COUNT(*) as total_records,
                COUNTIF(swstr_pct_last_3 IS NOT NULL) as has_swstr_last_3,
                COUNTIF(fb_velocity_last_3 IS NOT NULL) as has_velocity_last_3,
                AVG(swstr_pct_last_3) as avg_swstr,
                AVG(fb_velocity_last_3) as avg_velocity
            FROM `{PROJECT_ID}.mlb_analytics.pitcher_rolling_statcast`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
            """

            result = list(self.client.query(query).result())[0]

            if result.total_records == 0:
                self.report.error(f"Season {season}: No rolling statcast data found")
                continue

            swstr_coverage = (result.has_swstr_last_3 / result.total_records * 100) if result.total_records > 0 else 0
            velocity_coverage = (result.has_velocity_last_3 / result.total_records * 100) if result.total_records > 0 else 0

            if swstr_coverage >= 80 and velocity_coverage >= 80:
                self.report.info(f"Season {season}: V1.6 features available for {result.pitchers} pitchers (SwStr: {swstr_coverage:.1f}%, Vel: {velocity_coverage:.1f}%)")
            else:
                self.report.warning(f"Season {season}: Low V1.6 feature coverage (SwStr: {swstr_coverage:.1f}%, Vel: {velocity_coverage:.1f}%)")

            if self.verbose and result.avg_swstr:
                print(f"  Avg SwStr%: {result.avg_swstr:.1%}, Avg Velocity: {result.avg_velocity:.1f} mph")

    def cross_reference_raw_data(self):
        """Cross-reference predictions with raw game data"""
        for season in self.seasons:
            start_date, end_date = MLB_SEASON_DATES[season]

            # Check that all predictions match actual games
            query = f"""
            SELECT
                COUNT(DISTINCT p.game_date) as pred_dates,
                COUNT(DISTINCT r.game_date) as raw_dates,
                COUNT(DISTINCT p.pitcher_lookup) as pred_pitchers,
                COUNT(DISTINCT r.player_lookup) as raw_pitchers
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts` p
            FULL OUTER JOIN `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats` r
                ON p.pitcher_lookup = r.player_lookup
                AND p.game_date = r.game_date
                AND r.is_starter = TRUE
            WHERE p.game_date >= '{start_date}'
              AND p.game_date <= '{end_date}'
              AND p.model_version LIKE '%v1_6%'
            """

            result = list(self.client.query(query).result())[0]

            if result.pred_dates and result.raw_dates:
                date_match = min(result.pred_dates, result.raw_dates) / max(result.pred_dates, result.raw_dates) * 100
                if date_match >= 95:
                    self.report.info(f"Season {season}: Good alignment with raw data ({result.pred_pitchers} pitchers)")
                else:
                    self.report.warning(f"Season {season}: Date alignment {date_match:.1f}%")


def main():
    parser = argparse.ArgumentParser(description='Comprehensive V1.6 backfill validation')
    parser.add_argument('--seasons', default='2022,2023,2024,2025', help='Comma-separated list of seasons')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    seasons = [int(s.strip()) for s in args.seasons.split(',')]

    validator = V16BackfillValidator(seasons=seasons, verbose=args.verbose)
    success = validator.validate_all()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
