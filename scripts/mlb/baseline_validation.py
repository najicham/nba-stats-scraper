#!/usr/bin/env python3
"""
MLB Pitcher Strikeouts - Baseline Validation Script

This script validates the bottom-up K formula by:
1. Fetching historical game data from MLB Stats API (FREE)
2. Getting batter K rates from pybaseball/FanGraphs
3. Calculating expected Ks using the bottom-up formula
4. Comparing to actual Ks and measuring accuracy

Usage:
    python scripts/mlb/baseline_validation.py --start-date 2024-08-01 --end-date 2024-08-07
    python scripts/mlb/baseline_validation.py --single-date 2024-08-01  # Quick test
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import time

import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MLB Stats API endpoints (FREE, no auth required)
MLB_SCHEDULE_API = "https://statsapi.mlb.com/api/v1/schedule"
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"


@dataclass
class BatterInLineup:
    """A batter in the starting lineup."""
    player_id: int
    player_name: str
    batting_order: int  # 1-9
    position: str
    k_rate: Optional[float] = None  # Will be filled from FanGraphs data


@dataclass
class PitcherStart:
    """A starting pitcher's game data."""
    game_pk: int
    game_date: str
    pitcher_id: int
    pitcher_name: str
    pitcher_hand: str  # 'R' or 'L'
    team: str
    opponent: str
    is_home: bool
    actual_strikeouts: int
    actual_innings: float
    opposing_lineup: List[BatterInLineup]
    expected_strikeouts: Optional[float] = None  # Calculated later


class MLBDataCollector:
    """Collects game data from MLB Stats API."""

    def __init__(self, rate_limit_delay: float = 0.5):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'mlb-baseline-validation/1.0'
        })
        self.rate_limit_delay = rate_limit_delay

    def get_games_for_date(self, date: str) -> List[int]:
        """Get all game IDs for a given date."""
        url = f"{MLB_SCHEDULE_API}?sportId=1&date={date}&gameTypes=R,P"

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            game_pks = []
            for date_entry in data.get('dates', []):
                for game in date_entry.get('games', []):
                    game_pk = game.get('gamePk')
                    status = game.get('status', {}).get('abstractGameCode')
                    # Only include completed games (F = Final)
                    if game_pk and status == 'F':
                        game_pks.append(game_pk)

            return game_pks
        except Exception as e:
            logger.error(f"Error fetching schedule for {date}: {e}")
            return []

    def get_game_data(self, game_pk: int) -> Optional[Dict]:
        """Get full game data including lineups and pitcher stats."""
        url = MLB_GAME_API.format(game_pk=game_pk)

        try:
            time.sleep(self.rate_limit_delay)  # Rate limiting
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching game {game_pk}: {e}")
            return None

    def extract_pitcher_starts(self, game_data: Dict) -> List[PitcherStart]:
        """Extract starting pitcher data from a game."""
        starts = []

        try:
            game_pk = game_data.get('gameData', {}).get('game', {}).get('pk')
            game_date = game_data.get('gameData', {}).get('datetime', {}).get('originalDate')

            boxscore = game_data.get('liveData', {}).get('boxscore', {})
            teams = boxscore.get('teams', {})

            for side in ['away', 'home']:
                team_data = teams.get(side, {})
                team_name = team_data.get('team', {}).get('abbreviation', 'UNK')

                # Get opposing team name
                opp_side = 'home' if side == 'away' else 'away'
                opp_team = teams.get(opp_side, {}).get('team', {}).get('abbreviation', 'UNK')

                # Get starting pitcher (first in pitchers list)
                pitchers = team_data.get('pitchers', [])
                if not pitchers:
                    continue

                starter_id = pitchers[0]
                players = team_data.get('players', {})
                starter_key = f'ID{starter_id}'
                starter_data = players.get(starter_key, {})

                if not starter_data:
                    continue

                person = starter_data.get('person', {})
                stats = starter_data.get('stats', {}).get('pitching', {})

                # Parse innings pitched (e.g., "6.1" -> 6.33)
                ip_str = stats.get('inningsPitched', '0')
                try:
                    if '.' in str(ip_str):
                        whole, frac = str(ip_str).split('.')
                        ip = int(whole) + int(frac) / 3
                    else:
                        ip = float(ip_str)
                except:
                    ip = 0.0

                # Get pitcher handedness from game data
                all_players = game_data.get('gameData', {}).get('players', {})
                pitcher_hand = 'R'  # Default
                pitcher_full_key = f'ID{starter_id}'
                if pitcher_full_key in all_players:
                    pitcher_hand = all_players[pitcher_full_key].get('pitchHand', {}).get('code', 'R')

                # Get opposing lineup
                opp_team_data = teams.get(opp_side, {})
                lineup = self._extract_lineup(opp_team_data)

                start = PitcherStart(
                    game_pk=game_pk,
                    game_date=game_date,
                    pitcher_id=person.get('id'),
                    pitcher_name=person.get('fullName', 'Unknown'),
                    pitcher_hand=pitcher_hand,
                    team=team_name,
                    opponent=opp_team,
                    is_home=(side == 'home'),
                    actual_strikeouts=stats.get('strikeOuts', 0),
                    actual_innings=ip,
                    opposing_lineup=lineup
                )
                starts.append(start)

        except Exception as e:
            logger.error(f"Error extracting pitcher starts: {e}")

        return starts

    def _extract_lineup(self, team_data: Dict) -> List[BatterInLineup]:
        """Extract the starting lineup (batting order 1-9)."""
        lineup = []
        batters = team_data.get('batters', [])
        players = team_data.get('players', {})

        for player_id in batters:
            player_key = f'ID{player_id}'
            player_data = players.get(player_key, {})

            batting_order_raw = player_data.get('battingOrder')
            if not batting_order_raw:
                continue

            # Convert batting order (100 = 1, 200 = 2, etc.)
            order = int(batting_order_raw) // 100
            if order < 1 or order > 9:
                continue

            person = player_data.get('person', {})
            position = player_data.get('position', {})

            batter = BatterInLineup(
                player_id=person.get('id'),
                player_name=person.get('fullName', 'Unknown'),
                batting_order=order,
                position=position.get('abbreviation', 'UNK')
            )
            lineup.append(batter)

        # Sort by batting order and keep only positions 1-9
        lineup.sort(key=lambda x: x.batting_order)
        seen_orders = set()
        unique_lineup = []
        for b in lineup:
            if b.batting_order not in seen_orders and b.batting_order <= 9:
                seen_orders.add(b.batting_order)
                unique_lineup.append(b)

        return unique_lineup[:9]


class BatterKRateProvider:
    """Provides batter K rates from pybaseball/FanGraphs."""

    def __init__(self, season: int = 2024):
        self.season = season
        self.k_rates: Dict[str, float] = {}  # player_name -> K%
        self.k_rates_by_id: Dict[int, float] = {}  # player_id -> K%
        self.league_avg_k_rate = 0.23  # League average fallback
        self._loaded = False

    def load_k_rates(self) -> None:
        """Load batter K rates from FanGraphs via pybaseball."""
        if self._loaded:
            return

        try:
            from pybaseball import batting_stats

            logger.info(f"Loading {self.season} batter K rates from FanGraphs...")
            batters = batting_stats(self.season, qual=1)  # qual=1 to get more batters

            for _, row in batters.iterrows():
                name = row.get('Name', '')
                k_pct = row.get('K%', 0)

                # K% is already a decimal (0.25 = 25%)
                if isinstance(k_pct, str):
                    k_pct = float(k_pct.replace('%', '')) / 100

                if name and k_pct > 0:
                    self.k_rates[name.lower()] = k_pct

            logger.info(f"Loaded K rates for {len(self.k_rates)} batters")
            self._loaded = True

        except Exception as e:
            logger.error(f"Error loading K rates: {e}")
            logger.warning("Using league average K rate for all batters")

    def get_k_rate(self, player_name: str, player_id: int = None) -> float:
        """Get K rate for a batter, with fallback to league average."""
        if not self._loaded:
            self.load_k_rates()

        # Try exact name match
        name_lower = player_name.lower().strip()
        if name_lower in self.k_rates:
            return self.k_rates[name_lower]

        # Try partial name match (last name)
        last_name = name_lower.split()[-1] if name_lower else ''
        for stored_name, k_rate in self.k_rates.items():
            if last_name and last_name in stored_name:
                return k_rate

        # Fallback to league average
        return self.league_avg_k_rate


class BottomUpKCalculator:
    """Calculates expected strikeouts using the bottom-up formula."""

    # Expected plate appearances by lineup position (based on historical data)
    # Position 1 gets ~4.5 PA, position 9 gets ~3.5 PA in a 9-inning game
    EXPECTED_PA_BY_POSITION = {
        1: 4.5, 2: 4.3, 3: 4.1, 4: 3.9, 5: 3.7,
        6: 3.5, 7: 3.4, 8: 3.3, 9: 3.2
    }

    def __init__(self, k_rate_provider: BatterKRateProvider):
        self.k_rate_provider = k_rate_provider

    def calculate_expected_ks(self, start: PitcherStart) -> float:
        """
        Calculate expected strikeouts using the bottom-up formula.

        Formula: Expected Ks = SUM(batter_K_rate * expected_PAs) for each batter

        We also adjust for expected innings pitched (starter usually goes 5-6 IP).
        """
        if not start.opposing_lineup:
            return 0.0

        # First, fill in K rates for each batter
        for batter in start.opposing_lineup:
            if batter.k_rate is None:
                batter.k_rate = self.k_rate_provider.get_k_rate(
                    batter.player_name,
                    batter.player_id
                )

        # Calculate raw expected Ks (assuming full 9 innings)
        raw_expected = 0.0
        for batter in start.opposing_lineup:
            expected_pa = self.EXPECTED_PA_BY_POSITION.get(batter.batting_order, 3.5)
            expected_ks_for_batter = batter.k_rate * expected_pa
            raw_expected += expected_ks_for_batter

        # Adjust for typical starter innings (assume 6 IP average for starters)
        # The PA numbers above assume 9 innings, so scale by 6/9 = 0.67
        innings_factor = 6.0 / 9.0
        expected_ks = raw_expected * innings_factor

        return round(expected_ks, 2)


class BaselineValidator:
    """Runs the full baseline validation pipeline."""

    def __init__(self):
        self.collector = MLBDataCollector()
        self.k_rate_provider = BatterKRateProvider(season=2024)
        self.calculator = BottomUpKCalculator(self.k_rate_provider)
        self.starts: List[PitcherStart] = []

    def collect_data(self, start_date: str, end_date: str) -> None:
        """Collect game data for a date range."""
        logger.info(f"Collecting games from {start_date} to {end_date}")

        # Parse dates
        current = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')

        while current <= end:
            date_str = current.strftime('%Y-%m-%d')
            logger.info(f"Processing {date_str}...")

            game_pks = self.collector.get_games_for_date(date_str)
            logger.info(f"  Found {len(game_pks)} completed games")

            for game_pk in game_pks:
                game_data = self.collector.get_game_data(game_pk)
                if game_data:
                    starts = self.collector.extract_pitcher_starts(game_data)
                    self.starts.extend(starts)
                    logger.info(f"  Game {game_pk}: {len(starts)} starters extracted")

            current += timedelta(days=1)

        logger.info(f"Total pitcher starts collected: {len(self.starts)}")

    def calculate_predictions(self) -> None:
        """Calculate expected Ks for all collected starts."""
        logger.info("Loading batter K rates...")
        self.k_rate_provider.load_k_rates()

        logger.info("Calculating expected strikeouts...")
        for start in self.starts:
            start.expected_strikeouts = self.calculator.calculate_expected_ks(start)

    def evaluate_accuracy(self) -> Dict:
        """Evaluate prediction accuracy."""
        if not self.starts:
            return {}

        # Filter to starts with predictions
        valid_starts = [s for s in self.starts if s.expected_strikeouts is not None]

        if not valid_starts:
            return {}

        # Calculate metrics
        errors = []
        within_1 = 0
        within_2 = 0
        within_3 = 0

        for start in valid_starts:
            error = abs(start.actual_strikeouts - start.expected_strikeouts)
            errors.append(error)

            if error <= 1:
                within_1 += 1
            if error <= 2:
                within_2 += 1
            if error <= 3:
                within_3 += 1

        n = len(valid_starts)
        mae = sum(errors) / n
        rmse = (sum(e**2 for e in errors) / n) ** 0.5

        # Calculate actual vs predicted averages
        avg_actual = sum(s.actual_strikeouts for s in valid_starts) / n
        avg_predicted = sum(s.expected_strikeouts for s in valid_starts) / n

        return {
            'total_starts': n,
            'mae': round(mae, 3),
            'rmse': round(rmse, 3),
            'within_1_k': round(within_1 / n * 100, 1),
            'within_2_k': round(within_2 / n * 100, 1),
            'within_3_k': round(within_3 / n * 100, 1),
            'avg_actual_k': round(avg_actual, 2),
            'avg_predicted_k': round(avg_predicted, 2),
            'bias': round(avg_predicted - avg_actual, 2)  # Positive = over-predicting
        }

    def print_results(self) -> None:
        """Print detailed results."""
        metrics = self.evaluate_accuracy()

        print("\n" + "="*60)
        print("MLB PITCHER STRIKEOUTS - BASELINE VALIDATION RESULTS")
        print("="*60)

        if not metrics:
            print("No valid predictions to evaluate.")
            return

        print(f"\nSample Size: {metrics['total_starts']} pitcher starts")
        print(f"\nActual Avg Ks:    {metrics['avg_actual_k']}")
        print(f"Predicted Avg Ks: {metrics['avg_predicted_k']}")
        print(f"Bias:             {metrics['bias']:+.2f} (positive = over-predicting)")

        print(f"\n--- Accuracy Metrics ---")
        print(f"MAE:       {metrics['mae']:.2f} strikeouts")
        print(f"RMSE:      {metrics['rmse']:.2f} strikeouts")
        print(f"Within 1K: {metrics['within_1_k']:.1f}%")
        print(f"Within 2K: {metrics['within_2_k']:.1f}%")
        print(f"Within 3K: {metrics['within_3_k']:.1f}%")

        print(f"\n--- Interpretation ---")
        if metrics['mae'] < 1.5:
            print("EXCELLENT: MAE < 1.5 - Bottom-up formula is strong!")
            print("ML training will likely provide marginal improvement.")
        elif metrics['mae'] < 2.0:
            print("GOOD: MAE 1.5-2.0 - Formula is decent, ML will help.")
            print("Recommend proceeding with ML training.")
        else:
            print("NEEDS WORK: MAE > 2.0 - Formula needs debugging.")
            print("Check: platoon splits, innings adjustment, lineup quality.")

        print("\n--- Sample Predictions ---")
        for start in self.starts[:10]:
            if start.expected_strikeouts is not None:
                error = start.actual_strikeouts - start.expected_strikeouts
                print(f"  {start.pitcher_name:20} vs {start.opponent}: "
                      f"Predicted {start.expected_strikeouts:.1f}, "
                      f"Actual {start.actual_strikeouts}, "
                      f"Error {error:+.1f}")

    def save_results(self, output_path: str) -> None:
        """Save detailed results to JSON."""
        results = {
            'metrics': self.evaluate_accuracy(),
            'starts': [
                {
                    'game_pk': s.game_pk,
                    'game_date': s.game_date,
                    'pitcher_name': s.pitcher_name,
                    'pitcher_hand': s.pitcher_hand,
                    'team': s.team,
                    'opponent': s.opponent,
                    'actual_ks': s.actual_strikeouts,
                    'expected_ks': s.expected_strikeouts,
                    'actual_ip': s.actual_innings,
                    'lineup': [asdict(b) for b in s.opposing_lineup]
                }
                for s in self.starts
            ]
        }

        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)

        logger.info(f"Results saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='MLB Pitcher Strikeouts Baseline Validation')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--single-date', help='Single date for quick test')
    parser.add_argument('--output', default='/tmp/mlb_baseline_results.json',
                        help='Output JSON file path')

    args = parser.parse_args()

    # Determine date range
    if args.single_date:
        start_date = end_date = args.single_date
    elif args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        # Default to 1 week in August 2024
        start_date = '2024-08-01'
        end_date = '2024-08-07'

    # Run validation
    validator = BaselineValidator()
    validator.collect_data(start_date, end_date)
    validator.calculate_predictions()
    validator.print_results()
    validator.save_results(args.output)


if __name__ == '__main__':
    main()
