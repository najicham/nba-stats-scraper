#!/usr/bin/env python3
"""
Historical Season Validation

Validates all game dates from Oct 2024 → present across all pipeline layers.

Usage:
    # Full season validation
    python scripts/validate_historical_season.py

    # Specific date range
    python scripts/validate_historical_season.py --start 2024-11-01 --end 2024-12-31

    # Generate report only (no output)
    python scripts/validate_historical_season.py --report-only

Output:
    - CSV report with all findings
    - Summary statistics
    - Prioritized backfill recommendations
"""

import argparse
import csv
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"


class HistoricalValidator:
    """Validates historical data across all pipeline layers."""

    def __init__(self, project_id: str = PROJECT_ID):
        self.bq_client = bigquery.Client(project=project_id)
        self.project_id = project_id
        self.results = []

    def get_all_game_dates(self, start_date: str = None, end_date: str = None) -> List[str]:
        """Get all game dates from schedule."""
        # NOTE: nbac_schedule is partitioned and requires date filter
        # Default to past 18 months if no dates specified
        if not start_date and not end_date:
            # Default: 18 months ago to today
            where_clause = "WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 18 MONTH)"
        elif start_date and end_date:
            where_clause = f"WHERE game_date BETWEEN '{start_date}' AND '{end_date}'"
        elif start_date:
            where_clause = f"WHERE game_date >= '{start_date}'"
        elif end_date:
            where_clause = f"WHERE game_date <= '{end_date}'"

        query = f"""
        SELECT DISTINCT game_date
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        {where_clause}
        ORDER BY game_date
        """

        results = self.bq_client.query(query).result()
        return [row.game_date.strftime('%Y-%m-%d') for row in results]

    def validate_phase2_scrapers(self, game_date: str) -> Dict:
        """Validate Phase 2 scraper completeness."""
        # Check key scraper tables
        scrapers = {
            'bdl_box_scores': f"SELECT COUNT(DISTINCT game_id) FROM `{self.project_id}.nba_raw.bdl_player_boxscores` WHERE game_date = '{game_date}'",
            'nbac_gamebook': f"SELECT COUNT(DISTINCT game_id) FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats` WHERE game_date = '{game_date}'",
            'bettingpros_props': f"SELECT COUNT(DISTINCT player_name) FROM `{self.project_id}.nba_raw.bettingpros_player_points_props` WHERE game_date = '{game_date}'"
        }

        # Get scheduled games
        scheduled_query = f"SELECT COUNT(DISTINCT game_id) as games FROM `{self.project_id}.nba_raw.nbac_schedule` WHERE game_date = '{game_date}'"
        scheduled_result = list(self.bq_client.query(scheduled_query).result())
        scheduled_games = scheduled_result[0].games if scheduled_result else 0

        results = {'scheduled_games': scheduled_games}

        for scraper_name, query in scrapers.items():
            try:
                result = list(self.bq_client.query(query).result())
                count = result[0][0] if result else 0
                results[scraper_name] = count
            except Exception as e:
                logger.warning(f"Error checking {scraper_name} for {game_date}: {e}")
                results[scraper_name] = -1  # Error marker

        return results

    def validate_phase3_analytics(self, game_date: str) -> Dict:
        """Validate Phase 3 analytics completeness."""
        tables = {
            'player_game_summary': f"SELECT COUNT(*) FROM `{self.project_id}.nba_analytics.player_game_summary` WHERE game_date = '{game_date}'",
            'team_defense': f"SELECT COUNT(*) FROM `{self.project_id}.nba_analytics.team_defense_game_summary` WHERE game_date = '{game_date}'",
            'upcoming_context': f"SELECT COUNT(*) FROM `{self.project_id}.nba_analytics.upcoming_player_game_context` WHERE game_date = '{game_date}'"
        }

        results = {}
        for table_name, query in tables.items():
            try:
                result = list(self.bq_client.query(query).result())
                count = result[0][0] if result else 0
                results[table_name] = count
            except Exception as e:
                logger.warning(f"Error checking {table_name} for {game_date}: {e}")
                results[table_name] = -1

        return results

    def validate_phase4_processors(self, game_date: str) -> Dict:
        """Validate Phase 4 processor completeness."""
        processors = {
            'PDC': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_daily_cache` WHERE cache_date = '{game_date}'",
            'PSZA': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis` WHERE analysis_date = '{game_date}'",
            'PCF': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_composite_factors` WHERE game_date = '{game_date}'",
            # 'MLFS': removed - table ml_feature_store_v2 doesn't exist
            'TDZA': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis` WHERE analysis_date = '{game_date}'"
        }

        results = {}
        for proc_name, query in processors.items():
            try:
                result = list(self.bq_client.query(query).result())
                count = result[0][0] if result else 0
                results[proc_name] = count
            except Exception as e:
                logger.warning(f"Error checking {proc_name} for {game_date}: {e}")
                results[proc_name] = -1

        # Calculate completion
        completed = sum(1 for v in results.values() if v > 0)
        results['completed_count'] = completed
        results['total_count'] = len(processors)

        return results

    def validate_phase5_predictions(self, game_date: str) -> Dict:
        """Validate Phase 5 predictions completeness."""
        query = f"""
        SELECT
          COUNT(*) as total_predictions,
          COUNT(DISTINCT player_lookup) as unique_players,
          COUNT(DISTINCT system_id) as unique_systems
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date = '{game_date}'
        """

        try:
            result = list(self.bq_client.query(query).result())
            if result:
                row = result[0]
                return {
                    'total_predictions': row.total_predictions,
                    'unique_players': row.unique_players,
                    'unique_systems': row.unique_systems
                }
        except Exception as e:
            logger.warning(f"Error checking predictions for {game_date}: {e}")

        return {'total_predictions': 0, 'unique_players': 0, 'unique_systems': 0}

    def validate_phase6_grading(self, game_date: str) -> Dict:
        """Validate Phase 6 grading completeness."""
        query = f"""
        SELECT
          COUNT(*) as total_graded,
          COUNT(DISTINCT player_lookup) as unique_players_graded,
          ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / NULLIF(COUNT(*), 0), 1) as win_rate
        FROM `{self.project_id}.nba_predictions.prediction_grades`
        WHERE game_date = '{game_date}'
        """

        try:
            result = list(self.bq_client.query(query).result())
            if result:
                row = result[0]
                return {
                    'total_graded': row.total_graded,
                    'unique_players_graded': row.unique_players_graded,
                    'win_rate': row.win_rate
                }
        except Exception as e:
            logger.warning(f"Error checking grading for {game_date}: {e}")

        return {'total_graded': 0, 'unique_players_graded': 0, 'win_rate': None}

    def validate_single_date(self, game_date: str) -> Dict:
        """Validate all layers for a single date."""
        logger.info(f"Validating {game_date}...")

        result = {
            'game_date': game_date,
            'phase2': self.validate_phase2_scrapers(game_date),
            'phase3': self.validate_phase3_analytics(game_date),
            'phase4': self.validate_phase4_processors(game_date),
            'phase5': self.validate_phase5_predictions(game_date),
            'phase6': self.validate_phase6_grading(game_date)
        }

        # Calculate overall health score
        result['health_score'] = self.calculate_health_score(result)

        self.results.append(result)
        return result

    def calculate_health_score(self, validation: Dict) -> float:
        """Calculate overall health score (0-100), ignoring validation errors (-1)."""
        scores = []

        # Phase 2: Box score coverage (use best available scraper, ignore -1)
        scheduled = validation['phase2'].get('scheduled_games', 0)
        if scheduled > 0:
            bdl = validation['phase2'].get('bdl_box_scores', 0)
            gamebook = validation['phase2'].get('nbac_gamebook', 0)

            # Only calculate if we have valid data (not -1)
            valid_scrapers = [s for s in [bdl, gamebook] if s >= 0]
            if valid_scrapers:
                best_coverage = max(valid_scrapers) / scheduled
                scores.append(best_coverage * 100)

        # Phase 3: Analytics completion (ignore -1 values)
        phase3_valid = [v for v in validation['phase3'].values() if v >= 0]
        if phase3_valid:
            completed = sum(1 for v in phase3_valid if v > 0)
            scores.append((completed / len(phase3_valid)) * 100)

        # Phase 4: Processor completion (ignore -1 values)
        phase4_valid = {k: v for k, v in validation['phase4'].items()
                        if k not in ['completed_count', 'total_count'] and v >= 0}
        if phase4_valid:
            completed = sum(1 for v in phase4_valid.values() if v > 0)
            scores.append((completed / len(phase4_valid)) * 100)

        # Phase 5: Predictions exist
        if validation['phase5']['total_predictions'] > 0:
            scores.append(100)
        elif validation['phase5']['total_predictions'] == 0:
            scores.append(0)
        # If -1, skip (validation error)

        # Phase 6: Grading coverage
        predictions = validation['phase5']['total_predictions']
        graded = validation['phase6']['total_graded']
        if predictions > 0 and graded >= 0:  # Valid data
            grading_coverage = (graded / predictions) * 100
            scores.append(grading_coverage)
        elif predictions == 0:
            scores.append(0)  # No predictions to grade
        # If graded == -1, skip (validation error)

        return sum(scores) / len(scores) if scores else 0

    def validate_date_range(self, start_date: str = None, end_date: str = None):
        """Validate entire date range."""
        dates = self.get_all_game_dates(start_date, end_date)

        logger.info(f"Validating {len(dates)} dates from {dates[0]} to {dates[-1]}")

        for i, game_date in enumerate(dates, 1):
            self.validate_single_date(game_date)
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(dates)} dates validated ({i/len(dates)*100:.1f}%)")

        logger.info("Validation complete!")

    def generate_report(self, output_file: str = 'historical_validation_report.csv'):
        """Generate CSV report of all findings."""
        if not self.results:
            logger.error("No validation results to report")
            return

        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'game_date', 'health_score',
                'scheduled_games', 'bdl_box_scores', 'nbac_gamebook',
                'player_game_summary', 'team_defense', 'upcoming_context',
                'pdc', 'psza', 'pcf', 'mlfs', 'tdza', 'phase4_completion',
                'total_predictions', 'unique_players', 'unique_systems',
                'total_graded', 'grading_coverage_pct', 'win_rate'
            ])

            # Data rows
            for r in self.results:
                predictions = r['phase5']['total_predictions']
                graded = r['phase6']['total_graded']
                grading_pct = (graded / predictions * 100) if predictions > 0 else 0

                writer.writerow([
                    r['game_date'],
                    f"{r['health_score']:.1f}",
                    r['phase2']['scheduled_games'],
                    r['phase2'].get('bdl_box_scores', 0),
                    r['phase2'].get('nbac_gamebook', 0),
                    r['phase3'].get('player_game_summary', 0),
                    r['phase3'].get('team_defense', 0),
                    r['phase3'].get('upcoming_context', 0),
                    r['phase4'].get('PDC', 0),
                    r['phase4'].get('PSZA', 0),
                    r['phase4'].get('PCF', 0),
                    r['phase4'].get('MLFS', 0),
                    r['phase4'].get('TDZA', 0),
                    f"{r['phase4']['completed_count']}/{r['phase4']['total_count']}",
                    predictions,
                    r['phase5']['unique_players'],
                    r['phase5']['unique_systems'],
                    graded,
                    f"{grading_pct:.1f}",
                    r['phase6']['win_rate'] if r['phase6']['win_rate'] is not None else 'N/A'
                ])

        logger.info(f"✅ Report saved to {output_file}")

    def print_summary(self):
        """Print summary statistics."""
        if not self.results:
            return

        print("\n" + "="*80)
        print("HISTORICAL VALIDATION SUMMARY")
        print("="*80)

        total_dates = len(self.results)
        avg_health = sum(r['health_score'] for r in self.results) / total_dates

        print(f"\nDates Validated: {total_dates}")
        print(f"Average Health Score: {avg_health:.1f}%")

        # Health distribution
        excellent = sum(1 for r in self.results if r['health_score'] >= 90)
        good = sum(1 for r in self.results if 70 <= r['health_score'] < 90)
        fair = sum(1 for r in self.results if 50 <= r['health_score'] < 70)
        poor = sum(1 for r in self.results if r['health_score'] < 50)

        print(f"\nHealth Distribution:")
        print(f"  Excellent (≥90%): {excellent:3d} dates ({excellent/total_dates*100:5.1f}%)")
        print(f"  Good (70-89%):    {good:3d} dates ({good/total_dates*100:5.1f}%)")
        print(f"  Fair (50-69%):    {fair:3d} dates ({fair/total_dates*100:5.1f}%)")
        print(f"  Poor (<50%):      {poor:3d} dates ({poor/total_dates*100:5.1f}%)")

        # Top issues
        print(f"\nTop Issues:")

        # Box score gaps
        box_score_gaps = sum(1 for r in self.results if r['phase2'].get('bdl_box_scores', 0) < r['phase2']['scheduled_games'])
        print(f"  Missing box scores: {box_score_gaps} dates")

        # Phase 4 failures
        phase4_failures = sum(1 for r in self.results if r['phase4']['completed_count'] < 3)
        print(f"  Phase 4 failures (<3/5): {phase4_failures} dates")

        # Ungraded predictions
        ungraded = sum(1 for r in self.results if r['phase5']['total_predictions'] > 0 and r['phase6']['total_graded'] == 0)
        print(f"  Ungraded predictions: {ungraded} dates")

        # Worst dates
        print(f"\nWorst 10 Dates (Lowest Health Score):")
        sorted_results = sorted(self.results, key=lambda x: x['health_score'])
        for i, r in enumerate(sorted_results[:10], 1):
            print(f"  {i}. {r['game_date']}: {r['health_score']:.1f}% health")

        print("\n" + "="*80)
        print(f"✅ Full report saved to CSV")
        print("="*80 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Validate historical season data')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    parser.add_argument('--report-only', action='store_true', help='Generate report without printing summary')
    parser.add_argument('--output', default='historical_validation_report.csv', help='Output file path')

    args = parser.parse_args()

    validator = HistoricalValidator()
    validator.validate_date_range(args.start, args.end)
    validator.generate_report(args.output)

    if not args.report_only:
        validator.print_summary()


if __name__ == '__main__':
    main()
