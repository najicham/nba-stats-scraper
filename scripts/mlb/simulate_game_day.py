#!/usr/bin/env python3
"""
MLB Game Day Simulator

Replays a historical game day through the full prediction pipeline.
Useful for testing orchestration, validating models, and backtesting.

Usage:
    # Simulate a specific date
    PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2024-07-15

    # Simulate with custom thresholds
    MLB_MIN_EDGE=0.75 PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2024-07-15

    # Dry run (no BigQuery writes)
    PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2024-07-15 --dry-run

    # Compare V1 vs V2 thresholds
    PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2024-07-15 --compare-thresholds

    # Find dates with good data coverage
    PYTHONPATH=. python scripts/mlb/simulate_game_day.py --find-dates

Created: 2026-01-15
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from google.cloud import bigquery

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from predictions.mlb.config import get_config, reset_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')


@dataclass
class SimulationResult:
    """Results from simulating a single pitcher."""
    pitcher_lookup: str
    pitcher_name: str
    team: str
    opponent: str
    strikeouts_line: Optional[float]
    actual_strikeouts: Optional[int]

    # V1.4 prediction
    v1_4_predicted: Optional[float] = None
    v1_4_confidence: Optional[float] = None
    v1_4_recommendation: Optional[str] = None
    v1_4_correct: Optional[bool] = None
    v1_4_error: Optional[float] = None

    # V1.6 prediction
    v1_6_predicted: Optional[float] = None
    v1_6_confidence: Optional[float] = None
    v1_6_recommendation: Optional[str] = None
    v1_6_correct: Optional[bool] = None
    v1_6_error: Optional[float] = None

    # Which was closer
    closer_model: Optional[str] = None

    # Errors
    error: Optional[str] = None


@dataclass
class SimulationSummary:
    """Summary of simulation results."""
    game_date: str
    total_pitchers: int = 0
    pitchers_with_lines: int = 0
    pitchers_with_results: int = 0

    # V1.4 stats
    v1_4_predictions: int = 0
    v1_4_correct: int = 0
    v1_4_incorrect: int = 0
    v1_4_pass: int = 0
    v1_4_mae: float = 0.0
    v1_4_accuracy: float = 0.0

    # V1.6 stats
    v1_6_predictions: int = 0
    v1_6_correct: int = 0
    v1_6_incorrect: int = 0
    v1_6_pass: int = 0
    v1_6_mae: float = 0.0
    v1_6_accuracy: float = 0.0

    # Head-to-head
    v1_4_closer: int = 0
    v1_6_closer: int = 0
    ties: int = 0

    errors: int = 0
    results: List[SimulationResult] = field(default_factory=list)


class GameDaySimulator:
    """Simulate a full game day through the prediction pipeline."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self._v1_4_predictor = None
        self._v1_6_predictor = None

    def get_v1_4_predictor(self):
        """Lazy load V1.4 predictor."""
        if self._v1_4_predictor is None:
            from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor
            self._v1_4_predictor = PitcherStrikeoutsPredictor(
                model_path='gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json'
            )
            self._v1_4_predictor.load_model()
            logger.info(f"Loaded V1.4 model")
        return self._v1_4_predictor

    def get_v1_6_predictor(self):
        """Lazy load V1.6 predictor."""
        if self._v1_6_predictor is None:
            from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor
            self._v1_6_predictor = PitcherStrikeoutsPredictor(
                model_path='gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json'
            )
            self._v1_6_predictor.load_model()
            logger.info(f"Loaded V1.6 model")
        return self._v1_6_predictor

    def find_dates_with_data(self, min_pitchers: int = 5, limit: int = 20) -> List[Dict]:
        """Find historical dates with good data coverage."""
        # First get dates with pitchers and results
        query = f"""
        SELECT
            pgs.game_date,
            COUNT(DISTINCT pgs.player_lookup) as pitchers,
            COUNT(DISTINCT stats.player_lookup) as with_results
        FROM `{PROJECT_ID}.mlb_analytics.pitcher_game_summary` pgs
        LEFT JOIN `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats` stats
            ON pgs.player_lookup = stats.player_lookup
            AND pgs.game_date = stats.game_date
            AND stats.is_starter = TRUE
        WHERE pgs.game_date >= '2024-04-01'
            AND pgs.game_date < '2025-10-01'
        GROUP BY pgs.game_date
        HAVING COUNT(DISTINCT pgs.player_lookup) >= {min_pitchers}
            AND COUNT(DISTINCT stats.player_lookup) >= {min_pitchers - 2}
        ORDER BY game_date DESC
        LIMIT {limit}
        """

        result = self.bq_client.query(query).result()
        return [dict(row) for row in result]

    def load_game_day_data(self, game_date: date) -> List[Dict]:
        """Load all pitcher data for a game day."""
        # Load base pitcher data with odds
        query = f"""
        SELECT
            pgs.player_lookup as pitcher_lookup,
            pgs.player_full_name as pitcher_name,
            pgs.team_abbr as team,
            pgs.opponent_team_abbr as opponent,
            pgs.is_home,
            pgs.k_avg_last_3,
            pgs.k_avg_last_5,
            pgs.k_avg_last_10,
            pgs.k_std_last_10,
            pgs.ip_avg_last_5,
            pgs.season_k_per_9,
            pgs.season_era,
            pgs.season_whip,
            pgs.season_games_started,
            pgs.season_strikeouts,
            pgs.days_rest,
            pgs.games_last_30_days,
            pgs.rolling_stats_games,
            odds.point as strikeouts_line,
            odds.over_price as over_odds,
            odds.under_price as under_odds
        FROM `{PROJECT_ID}.mlb_analytics.pitcher_game_summary` pgs
        LEFT JOIN (
            SELECT player_lookup, point, over_price, under_price,
                ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY last_update DESC) as rn
            FROM `{PROJECT_ID}.mlb_raw.oddsa_pitcher_props`
            WHERE game_date = @game_date
              AND market_key = 'pitcher_strikeouts'
        ) odds ON REPLACE(pgs.player_lookup, '_', '') = odds.player_lookup AND odds.rn = 1
        WHERE pgs.game_date = @game_date
        ORDER BY pgs.team_abbr
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat())
            ]
        )

        pitchers = [dict(row) for row in self.bq_client.query(query, job_config=job_config).result()]

        # Load actual results separately
        stats_query = f"""
        SELECT player_lookup, strikeouts, innings_pitched
        FROM `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats`
        WHERE game_date = @game_date AND is_starter = TRUE
        """
        stats_result = self.bq_client.query(stats_query, job_config=job_config).result()
        stats_map = {row.player_lookup: dict(row) for row in stats_result}

        # Merge results
        for p in pitchers:
            stats = stats_map.get(p['pitcher_lookup'], {})
            p['actual_strikeouts'] = stats.get('strikeouts')
            p['actual_ip'] = stats.get('innings_pitched')

        return pitchers

    def simulate_pitcher(
        self,
        pitcher_data: Dict,
        game_date: date
    ) -> SimulationResult:
        """Run simulation for a single pitcher."""
        result = SimulationResult(
            pitcher_lookup=pitcher_data['pitcher_lookup'],
            pitcher_name=pitcher_data.get('pitcher_name', 'Unknown'),
            team=pitcher_data.get('team', ''),
            opponent=pitcher_data.get('opponent', ''),
            strikeouts_line=pitcher_data.get('strikeouts_line'),
            actual_strikeouts=pitcher_data.get('actual_strikeouts')
        )

        try:
            # Get predictors
            v1_4 = self.get_v1_4_predictor()
            v1_6 = self.get_v1_6_predictor()

            # Load features for this pitcher
            features = v1_4.load_pitcher_features(
                pitcher_data['pitcher_lookup'],
                game_date
            )

            if not features:
                # Use data from query as fallback features
                features = {
                    'k_avg_last_3': pitcher_data.get('k_avg_last_3'),
                    'k_avg_last_5': pitcher_data.get('k_avg_last_5'),
                    'k_avg_last_10': pitcher_data.get('k_avg_last_10'),
                    'k_std_last_10': pitcher_data.get('k_std_last_10'),
                    'ip_avg_last_5': pitcher_data.get('ip_avg_last_5'),
                    'season_k_per_9': pitcher_data.get('season_k_per_9'),
                    'season_era': pitcher_data.get('season_era'),
                    'season_whip': pitcher_data.get('season_whip'),
                    'season_games_started': pitcher_data.get('season_games_started'),
                    'is_home': pitcher_data.get('is_home', False),
                    'days_rest': pitcher_data.get('days_rest'),
                    'games_last_30_days': pitcher_data.get('games_last_30_days'),
                    'rolling_stats_games': pitcher_data.get('rolling_stats_games'),
                }

            line = pitcher_data.get('strikeouts_line')

            # V1.4 prediction
            pred_1_4 = v1_4.predict(
                pitcher_lookup=pitcher_data['pitcher_lookup'],
                features=features,
                strikeouts_line=line
            )
            result.v1_4_predicted = pred_1_4.get('predicted_strikeouts')
            result.v1_4_confidence = pred_1_4.get('confidence')
            result.v1_4_recommendation = pred_1_4.get('recommendation')

            # V1.6 prediction
            pred_1_6 = v1_6.predict(
                pitcher_lookup=pitcher_data['pitcher_lookup'],
                features=features,
                strikeouts_line=line
            )
            result.v1_6_predicted = pred_1_6.get('predicted_strikeouts')
            result.v1_6_confidence = pred_1_6.get('confidence')
            result.v1_6_recommendation = pred_1_6.get('recommendation')

            # Grade if we have actual results
            actual = pitcher_data.get('actual_strikeouts')
            if actual is not None and line is not None:
                # V1.4 grading
                if result.v1_4_predicted:
                    result.v1_4_error = result.v1_4_predicted - actual
                    if result.v1_4_recommendation == 'OVER':
                        result.v1_4_correct = actual > line
                    elif result.v1_4_recommendation == 'UNDER':
                        result.v1_4_correct = actual < line

                # V1.6 grading
                if result.v1_6_predicted:
                    result.v1_6_error = result.v1_6_predicted - actual
                    if result.v1_6_recommendation == 'OVER':
                        result.v1_6_correct = actual > line
                    elif result.v1_6_recommendation == 'UNDER':
                        result.v1_6_correct = actual < line

                # Which was closer?
                if result.v1_4_error is not None and result.v1_6_error is not None:
                    if abs(result.v1_4_error) < abs(result.v1_6_error):
                        result.closer_model = 'v1_4'
                    elif abs(result.v1_6_error) < abs(result.v1_4_error):
                        result.closer_model = 'v1_6'
                    else:
                        result.closer_model = 'tie'

        except Exception as e:
            result.error = str(e)
            logger.warning(f"Error simulating {pitcher_data['pitcher_lookup']}: {e}")

        return result

    def run_simulation(self, game_date: date) -> SimulationSummary:
        """Run full simulation for a game day."""
        logger.info(f"{'='*60}")
        logger.info(f"SIMULATING GAME DAY: {game_date}")
        logger.info(f"{'='*60}")

        summary = SimulationSummary(game_date=game_date.isoformat())

        # Load game day data
        logger.info("Loading game day data...")
        pitchers = self.load_game_day_data(game_date)
        summary.total_pitchers = len(pitchers)
        logger.info(f"Found {len(pitchers)} starting pitchers")

        if not pitchers:
            logger.warning("No pitchers found for this date")
            return summary

        # Count data availability
        summary.pitchers_with_lines = sum(1 for p in pitchers if p.get('strikeouts_line'))
        summary.pitchers_with_results = sum(1 for p in pitchers if p.get('actual_strikeouts') is not None)

        logger.info(f"  With betting lines: {summary.pitchers_with_lines}")
        logger.info(f"  With actual results: {summary.pitchers_with_results}")

        # Run simulations
        logger.info("\nRunning predictions...")
        for pitcher in pitchers:
            result = self.simulate_pitcher(pitcher, game_date)
            summary.results.append(result)

            if result.error:
                summary.errors += 1
                continue

            # Count V1.4 stats
            if result.v1_4_recommendation:
                if result.v1_4_recommendation in ('OVER', 'UNDER'):
                    summary.v1_4_predictions += 1
                    if result.v1_4_correct is True:
                        summary.v1_4_correct += 1
                    elif result.v1_4_correct is False:
                        summary.v1_4_incorrect += 1
                else:
                    summary.v1_4_pass += 1

            # Count V1.6 stats
            if result.v1_6_recommendation:
                if result.v1_6_recommendation in ('OVER', 'UNDER'):
                    summary.v1_6_predictions += 1
                    if result.v1_6_correct is True:
                        summary.v1_6_correct += 1
                    elif result.v1_6_correct is False:
                        summary.v1_6_incorrect += 1
                else:
                    summary.v1_6_pass += 1

            # Head-to-head
            if result.closer_model == 'v1_4':
                summary.v1_4_closer += 1
            elif result.closer_model == 'v1_6':
                summary.v1_6_closer += 1
            elif result.closer_model == 'tie':
                summary.ties += 1

        # Calculate MAE
        v1_4_errors = [abs(r.v1_4_error) for r in summary.results if r.v1_4_error is not None]
        v1_6_errors = [abs(r.v1_6_error) for r in summary.results if r.v1_6_error is not None]

        if v1_4_errors:
            summary.v1_4_mae = sum(v1_4_errors) / len(v1_4_errors)
        if v1_6_errors:
            summary.v1_6_mae = sum(v1_6_errors) / len(v1_6_errors)

        # Calculate accuracy
        if summary.v1_4_correct + summary.v1_4_incorrect > 0:
            summary.v1_4_accuracy = summary.v1_4_correct / (summary.v1_4_correct + summary.v1_4_incorrect) * 100
        if summary.v1_6_correct + summary.v1_6_incorrect > 0:
            summary.v1_6_accuracy = summary.v1_6_correct / (summary.v1_6_correct + summary.v1_6_incorrect) * 100

        return summary


def print_summary(summary: SimulationSummary):
    """Print simulation summary."""
    print("\n" + "=" * 70)
    print(f"SIMULATION RESULTS: {summary.game_date}")
    print("=" * 70)

    print(f"\nData Coverage:")
    print(f"  Total pitchers:     {summary.total_pitchers}")
    print(f"  With betting lines: {summary.pitchers_with_lines}")
    print(f"  With results:       {summary.pitchers_with_results}")
    print(f"  Errors:             {summary.errors}")

    print(f"\n{'Model':<10} {'Picks':<8} {'Correct':<10} {'Wrong':<8} {'Accuracy':<10} {'MAE':<8} {'PASS':<6}")
    print("-" * 70)

    print(f"{'V1.4':<10} {summary.v1_4_predictions:<8} {summary.v1_4_correct:<10} "
          f"{summary.v1_4_incorrect:<8} {summary.v1_4_accuracy:>6.1f}%    {summary.v1_4_mae:<8.2f} {summary.v1_4_pass:<6}")

    print(f"{'V1.6':<10} {summary.v1_6_predictions:<8} {summary.v1_6_correct:<10} "
          f"{summary.v1_6_incorrect:<8} {summary.v1_6_accuracy:>6.1f}%    {summary.v1_6_mae:<8.2f} {summary.v1_6_pass:<6}")

    print(f"\nHead-to-Head (which prediction was closer to actual):")
    total_h2h = summary.v1_4_closer + summary.v1_6_closer + summary.ties
    if total_h2h > 0:
        print(f"  V1.4 closer: {summary.v1_4_closer} ({summary.v1_4_closer/total_h2h*100:.1f}%)")
        print(f"  V1.6 closer: {summary.v1_6_closer} ({summary.v1_6_closer/total_h2h*100:.1f}%)")
        print(f"  Ties:        {summary.ties} ({summary.ties/total_h2h*100:.1f}%)")

    # Show individual results
    print(f"\n{'Pitcher':<20} {'Team':<6} {'Line':<6} {'Actual':<8} {'V1.4':<8} {'V1.6':<8} {'Winner':<8}")
    print("-" * 70)

    for r in sorted(summary.results, key=lambda x: x.team):
        if r.error:
            print(f"{r.pitcher_lookup[:20]:<20} {r.team:<6} {'ERR':<6} {'-':<8} {'-':<8} {'-':<8} {r.error[:15]}")
        else:
            line = f"{r.strikeouts_line:.1f}" if r.strikeouts_line else "-"
            actual = str(r.actual_strikeouts) if r.actual_strikeouts is not None else "-"
            v1_4 = f"{r.v1_4_predicted:.1f}" if r.v1_4_predicted else "-"
            v1_6 = f"{r.v1_6_predicted:.1f}" if r.v1_6_predicted else "-"
            winner = r.closer_model or "-"

            # Add recommendation indicator
            v1_4_rec = ""
            if r.v1_4_recommendation == 'OVER':
                v1_4_rec = " O" + ("+" if r.v1_4_correct else "-" if r.v1_4_correct is False else "")
            elif r.v1_4_recommendation == 'UNDER':
                v1_4_rec = " U" + ("+" if r.v1_4_correct else "-" if r.v1_4_correct is False else "")

            v1_6_rec = ""
            if r.v1_6_recommendation == 'OVER':
                v1_6_rec = " O" + ("+" if r.v1_6_correct else "-" if r.v1_6_correct is False else "")
            elif r.v1_6_recommendation == 'UNDER':
                v1_6_rec = " U" + ("+" if r.v1_6_correct else "-" if r.v1_6_correct is False else "")

            print(f"{r.pitcher_lookup[:20]:<20} {r.team:<6} {line:<6} {actual:<8} "
                  f"{v1_4 + v1_4_rec:<8} {v1_6 + v1_6_rec:<8} {winner:<8}")

    print("\n" + "=" * 70)
    print("Legend: O=OVER, U=UNDER, +=correct, -=incorrect")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Simulate MLB game day through prediction pipeline"
    )
    parser.add_argument(
        "--date", "-d",
        help="Date to simulate (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--find-dates",
        action="store_true",
        help="Find dates with good data coverage"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write to BigQuery"
    )
    parser.add_argument(
        "--compare-thresholds",
        action="store_true",
        help="Run simulation with different threshold settings"
    )
    args = parser.parse_args()

    simulator = GameDaySimulator(dry_run=args.dry_run)

    if args.find_dates:
        print("\nSearching for dates with good data coverage...")
        dates = simulator.find_dates_with_data()

        print(f"\n{'Date':<12} {'Pitchers':<10} {'With Results':<12}")
        print("-" * 40)
        for d in dates:
            print(f"{d['game_date']}   {d['pitchers']:<10} {d['with_results']:<12}")

        if dates:
            print(f"\nExample: python scripts/mlb/simulate_game_day.py --date {dates[0]['game_date']}")
        return

    if not args.date:
        parser.print_help()
        print("\nError: --date is required (or use --find-dates to discover available dates)")
        return

    game_date = date.fromisoformat(args.date)

    if args.compare_thresholds:
        # Run with different thresholds
        thresholds = [
            {"name": "Default (0.5)", "MLB_MIN_EDGE": "0.5"},
            {"name": "Aggressive (0.3)", "MLB_MIN_EDGE": "0.3"},
            {"name": "Conservative (0.75)", "MLB_MIN_EDGE": "0.75"},
            {"name": "V2-style (1.0)", "MLB_MIN_EDGE": "1.0"},
        ]

        results = []
        for thresh in thresholds:
            os.environ['MLB_MIN_EDGE'] = thresh['MLB_MIN_EDGE']
            reset_config()  # Reload config with new env

            print(f"\n>>> Testing threshold: {thresh['name']}")
            summary = simulator.run_simulation(game_date)
            results.append((thresh['name'], summary))

        # Comparison summary
        print("\n" + "=" * 70)
        print("THRESHOLD COMPARISON")
        print("=" * 70)
        print(f"\n{'Threshold':<20} {'V1.4 Acc':<12} {'V1.6 Acc':<12} {'V1.4 Picks':<12} {'V1.6 Picks':<12}")
        print("-" * 70)
        for name, s in results:
            print(f"{name:<20} {s.v1_4_accuracy:>6.1f}%      {s.v1_6_accuracy:>6.1f}%      "
                  f"{s.v1_4_predictions:<12} {s.v1_6_predictions:<12}")
    else:
        # Single simulation
        summary = simulator.run_simulation(game_date)
        print_summary(summary)


if __name__ == "__main__":
    main()
