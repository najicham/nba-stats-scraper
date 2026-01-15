#!/usr/bin/env python3
"""
Phase 5: Calculate TRUE Hit Rate (Enhanced with Statistical Analysis)

Calculates comprehensive hit rate statistics for MLB pitcher strikeout
predictions graded against real historical betting lines.

Reports:
- Overall hit rate with confidence intervals
- Statistical significance vs breakeven
- ROI and profit simulation
- Bankroll simulation with drawdown analysis
- Hit rate by edge bucket
- Hit rate by season
- Hit rate by recommendation type (OVER/UNDER)
- Kelly criterion optimal bet sizing

Usage:
    python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py

    # Output as JSON
    python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py --json

    # Specific date range
    python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py \
        --start-date 2024-06-01 --end-date 2024-09-30

    # Skip bankroll simulation (faster)
    python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py --skip-simulation
"""

import argparse
import json
import logging
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import random

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google.cloud import bigquery

# Optional: numpy for faster calculations (falls back to pure Python)
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
BREAKEVEN_RATE = 52.38  # Exact breakeven at -110 odds (100/190.91)
STANDARD_JUICE = -110  # Standard American odds


# =============================================================================
# STATISTICAL HELPER FUNCTIONS
# =============================================================================

def calculate_wilson_ci(wins: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Calculate Wilson score confidence interval for a proportion.

    Better than normal approximation for proportions, especially near 0 or 1.

    Args:
        wins: Number of successes
        n: Total trials
        confidence: Confidence level (default 0.95 for 95% CI)

    Returns:
        (lower_bound, upper_bound) as percentages
    """
    if n == 0:
        return (0.0, 0.0)

    # Z-score for confidence level
    z = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}.get(confidence, 1.96)

    p = wins / n

    # Wilson score interval formula
    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denominator

    lower = max(0, center - spread) * 100
    upper = min(1, center + spread) * 100

    return (round(lower, 2), round(upper, 2))


def calculate_bootstrap_ci(
    outcomes: List[bool],
    n_bootstrap: int = 10000,
    confidence: float = 0.95
) -> Tuple[float, float]:
    """
    Calculate bootstrap confidence interval for hit rate.

    More robust for small samples or non-normal distributions.

    Args:
        outcomes: List of True (win) / False (loss) outcomes
        n_bootstrap: Number of bootstrap iterations
        confidence: Confidence level

    Returns:
        (lower_bound, upper_bound) as percentages
    """
    if not outcomes:
        return (0.0, 0.0)

    n = len(outcomes)
    bootstrap_rates = []

    random.seed(42)  # Reproducibility

    for _ in range(n_bootstrap):
        # Sample with replacement
        sample = [outcomes[random.randint(0, n - 1)] for _ in range(n)]
        rate = sum(sample) / n * 100
        bootstrap_rates.append(rate)

    # Sort and get percentiles
    bootstrap_rates.sort()
    alpha = (1 - confidence) / 2
    lower_idx = int(alpha * n_bootstrap)
    upper_idx = int((1 - alpha) * n_bootstrap) - 1

    return (round(bootstrap_rates[lower_idx], 2), round(bootstrap_rates[upper_idx], 2))


def calculate_z_test(
    observed_rate: float,
    null_rate: float,
    n: int
) -> Dict[str, float]:
    """
    One-proportion z-test against a null hypothesis.

    Tests if observed hit rate is significantly different from breakeven.

    Args:
        observed_rate: Observed proportion (0-1)
        null_rate: Null hypothesis proportion (0-1)
        n: Sample size

    Returns:
        Dictionary with z-statistic, p-value, and significance
    """
    if n == 0:
        return {'z_statistic': 0, 'p_value': 1.0, 'significant_95': False, 'significant_99': False}

    # Standard error under null hypothesis
    se = math.sqrt(null_rate * (1 - null_rate) / n)

    if se == 0:
        return {'z_statistic': 0, 'p_value': 1.0, 'significant_95': False, 'significant_99': False}

    # Z-statistic
    z = (observed_rate - null_rate) / se

    # One-tailed p-value (testing if rate > breakeven)
    # Using approximation for standard normal CDF
    p_value = 0.5 * (1 + math.erf(-z / math.sqrt(2)))

    return {
        'z_statistic': round(z, 3),
        'p_value': round(p_value, 6),
        'significant_95': p_value < 0.05,
        'significant_99': p_value < 0.01,
    }


def calculate_roi(hit_rate: float, odds: int = -110) -> Dict[str, float]:
    """
    Calculate ROI and expected value at given odds.

    Args:
        hit_rate: Win rate as proportion (0-1)
        odds: American odds (e.g., -110)

    Returns:
        Dictionary with ROI, EV per bet, and related metrics
    """
    # Convert American odds to decimal
    if odds < 0:
        decimal_odds = 1 + (100 / abs(odds))
        risk = abs(odds)
        win_amount = 100
    else:
        decimal_odds = 1 + (odds / 100)
        risk = 100
        win_amount = odds

    # Expected value per unit risked
    ev_per_bet = (hit_rate * win_amount) - ((1 - hit_rate) * risk)
    roi = ev_per_bet / risk * 100

    # Profit per 100 bets
    profit_per_100 = ev_per_bet * 100 / risk * 100

    return {
        'roi_pct': round(roi, 2),
        'ev_per_bet': round(ev_per_bet, 2),
        'profit_per_100_bets': round(profit_per_100, 2),
        'decimal_odds': round(decimal_odds, 4),
        'implied_probability': round(1 / decimal_odds * 100, 2),
    }


def calculate_kelly_criterion(hit_rate: float, odds: int = -110) -> Dict[str, float]:
    """
    Calculate Kelly Criterion optimal bet sizing.

    Kelly % = (bp - q) / b
    Where: b = decimal odds - 1, p = win prob, q = loss prob

    Args:
        hit_rate: Win rate as proportion (0-1)
        odds: American odds

    Returns:
        Dictionary with Kelly percentage and fractional Kelly recommendations
    """
    # Convert to decimal odds
    if odds < 0:
        decimal_odds = 1 + (100 / abs(odds))
    else:
        decimal_odds = 1 + (odds / 100)

    b = decimal_odds - 1
    p = hit_rate
    q = 1 - p

    # Kelly formula
    kelly = (b * p - q) / b

    # Cap at 0 (no bet) if negative edge
    kelly = max(0, kelly)

    return {
        'full_kelly_pct': round(kelly * 100, 2),
        'half_kelly_pct': round(kelly * 50, 2),
        'quarter_kelly_pct': round(kelly * 25, 2),
        'recommended_pct': round(kelly * 25, 2),  # Quarter Kelly is conservative
    }


def simulate_bankroll(
    outcomes: List[bool],
    starting_bankroll: float = 10000,
    bet_size: float = 100,
    odds: int = -110
) -> Dict[str, float]:
    """
    Simulate bankroll over time with flat betting.

    Args:
        outcomes: List of True (win) / False (loss) outcomes in chronological order
        starting_bankroll: Starting bankroll amount
        bet_size: Flat bet size per bet
        odds: American odds

    Returns:
        Dictionary with bankroll metrics
    """
    if not outcomes:
        return {
            'final_bankroll': starting_bankroll,
            'total_profit': 0,
            'max_drawdown_pct': 0,
            'peak_bankroll': starting_bankroll,
            'lowest_bankroll': starting_bankroll,
        }

    # Calculate win/loss amounts
    if odds < 0:
        win_amount = 100 / abs(odds) * bet_size
        loss_amount = bet_size
    else:
        win_amount = odds / 100 * bet_size
        loss_amount = bet_size

    bankroll = starting_bankroll
    peak = starting_bankroll
    lowest = starting_bankroll
    max_drawdown = 0
    bankroll_history = [starting_bankroll]

    for won in outcomes:
        if won:
            bankroll += win_amount
        else:
            bankroll -= loss_amount

        bankroll_history.append(bankroll)

        # Track peak and drawdown
        if bankroll > peak:
            peak = bankroll

        if bankroll < lowest:
            lowest = bankroll

        current_drawdown = (peak - bankroll) / peak * 100
        if current_drawdown > max_drawdown:
            max_drawdown = current_drawdown

    # Calculate longest losing streak
    max_losing_streak = 0
    current_streak = 0
    for won in outcomes:
        if not won:
            current_streak += 1
            max_losing_streak = max(max_losing_streak, current_streak)
        else:
            current_streak = 0

    # Calculate longest winning streak
    max_winning_streak = 0
    current_streak = 0
    for won in outcomes:
        if won:
            current_streak += 1
            max_winning_streak = max(max_winning_streak, current_streak)
        else:
            current_streak = 0

    return {
        'starting_bankroll': starting_bankroll,
        'final_bankroll': round(bankroll, 2),
        'total_profit': round(bankroll - starting_bankroll, 2),
        'total_return_pct': round((bankroll - starting_bankroll) / starting_bankroll * 100, 2),
        'max_drawdown_pct': round(max_drawdown, 2),
        'peak_bankroll': round(peak, 2),
        'lowest_bankroll': round(lowest, 2),
        'max_winning_streak': max_winning_streak,
        'max_losing_streak': max_losing_streak,
        'total_bets': len(outcomes),
        'bet_size': bet_size,
    }


class HitRateCalculator:
    """Calculates comprehensive hit rate statistics with statistical rigor."""

    def __init__(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        skip_simulation: bool = False,
    ):
        self.start_date = start_date or '2024-04-09'
        self.end_date = end_date or '2025-09-28'
        self.skip_simulation = skip_simulation
        self.bq_client = bigquery.Client(project=PROJECT_ID)

        # Cache for individual bet outcomes (for simulation)
        self._bet_outcomes: Optional[List[Dict]] = None

    def get_individual_bets(self) -> List[Dict]:
        """Get individual bet outcomes for detailed analysis and simulation."""
        if self._bet_outcomes is not None:
            return self._bet_outcomes

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            pitcher_name,
            recommendation,
            predicted_strikeouts,
            strikeouts_line,
            actual_strikeouts,
            is_correct,
            ABS(predicted_strikeouts - strikeouts_line) as edge
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND line_source = 'historical_odds_api'
          AND recommendation IN ('OVER', 'UNDER')
          AND is_correct IS NOT NULL
        ORDER BY game_date, pitcher_lookup
        """

        results = list(self.bq_client.query(query).result())
        self._bet_outcomes = [dict(row) for row in results]

        logger.info(f"Loaded {len(self._bet_outcomes)} individual bet outcomes")
        return self._bet_outcomes

    def get_overall_stats(self) -> Dict:
        """Get overall hit rate statistics with statistical analysis."""
        query = f"""
        SELECT
            COUNT(*) as total_predictions,
            SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN is_correct = FALSE THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN actual_strikeouts = strikeouts_line THEN 1 ELSE 0 END) as pushes,
            SUM(CASE WHEN recommendation = 'PASS' THEN 1 ELSE 0 END) as passes,
            SUM(CASE WHEN is_correct IS NULL AND recommendation != 'PASS' THEN 1 ELSE 0 END) as no_result
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND line_source = 'historical_odds_api'
        """

        result = list(self.bq_client.query(query).result())[0]

        total_bets = result.wins + result.losses
        hit_rate = (result.wins / total_bets * 100) if total_bets > 0 else 0.0
        hit_rate_decimal = result.wins / total_bets if total_bets > 0 else 0.0
        edge_vs_breakeven = hit_rate - BREAKEVEN_RATE

        # Statistical analysis
        wilson_ci = calculate_wilson_ci(result.wins, total_bets)
        z_test = calculate_z_test(hit_rate_decimal, BREAKEVEN_RATE / 100, total_bets)
        roi = calculate_roi(hit_rate_decimal, STANDARD_JUICE)
        kelly = calculate_kelly_criterion(hit_rate_decimal, STANDARD_JUICE)

        # Bootstrap CI (optional - takes a moment)
        bootstrap_ci = None
        if not self.skip_simulation and total_bets > 0:
            bets = self.get_individual_bets()
            outcomes = [b['is_correct'] for b in bets]
            bootstrap_ci = calculate_bootstrap_ci(outcomes)

        return {
            'total_predictions': result.total_predictions,
            'bets_placed': total_bets,
            'wins': result.wins,
            'losses': result.losses,
            'pushes': result.pushes,
            'passes': result.passes,
            'no_result': result.no_result,
            'hit_rate': round(hit_rate, 2),
            'breakeven': BREAKEVEN_RATE,
            'edge_vs_breakeven': round(edge_vs_breakeven, 2),
            'is_profitable': hit_rate > BREAKEVEN_RATE,
            # New statistical fields
            'confidence_interval_95': wilson_ci,
            'bootstrap_ci_95': bootstrap_ci,
            'statistical_test': z_test,
            'roi': roi,
            'kelly_criterion': kelly,
        }

    def get_by_recommendation(self) -> Dict:
        """Get hit rate by recommendation type."""
        query = f"""
        SELECT
            recommendation,
            COUNT(*) as total,
            SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN is_correct = FALSE THEN 1 ELSE 0 END) as losses
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND line_source = 'historical_odds_api'
          AND recommendation IN ('OVER', 'UNDER')
        GROUP BY recommendation
        ORDER BY recommendation
        """

        results = {}
        for row in self.bq_client.query(query).result():
            total_bets = row.wins + row.losses
            hit_rate = (row.wins / total_bets * 100) if total_bets > 0 else 0.0
            results[row.recommendation] = {
                'bets': total_bets,
                'wins': row.wins,
                'losses': row.losses,
                'hit_rate': round(hit_rate, 2),
            }

        return results

    def get_by_edge_bucket(self) -> Dict:
        """Get hit rate by edge size."""
        query = f"""
        SELECT
            CASE
                WHEN ABS(predicted_strikeouts - strikeouts_line) < 0.5 THEN '0.0-0.5'
                WHEN ABS(predicted_strikeouts - strikeouts_line) < 1.0 THEN '0.5-1.0'
                WHEN ABS(predicted_strikeouts - strikeouts_line) < 1.5 THEN '1.0-1.5'
                WHEN ABS(predicted_strikeouts - strikeouts_line) < 2.0 THEN '1.5-2.0'
                ELSE '2.0+'
            END as edge_bucket,
            COUNT(*) as total,
            SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN is_correct = FALSE THEN 1 ELSE 0 END) as losses
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND line_source = 'historical_odds_api'
          AND recommendation IN ('OVER', 'UNDER')
          AND is_correct IS NOT NULL
        GROUP BY edge_bucket
        ORDER BY edge_bucket
        """

        results = {}
        for row in self.bq_client.query(query).result():
            total_bets = row.wins + row.losses
            hit_rate = (row.wins / total_bets * 100) if total_bets > 0 else 0.0
            results[row.edge_bucket] = {
                'bets': total_bets,
                'wins': row.wins,
                'losses': row.losses,
                'hit_rate': round(hit_rate, 2),
            }

        return results

    def get_by_season(self) -> Dict:
        """Get hit rate by season (year)."""
        query = f"""
        SELECT
            EXTRACT(YEAR FROM game_date) as season,
            COUNT(*) as total,
            SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN is_correct = FALSE THEN 1 ELSE 0 END) as losses
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND line_source = 'historical_odds_api'
          AND recommendation IN ('OVER', 'UNDER')
          AND is_correct IS NOT NULL
        GROUP BY season
        ORDER BY season
        """

        results = {}
        for row in self.bq_client.query(query).result():
            total_bets = row.wins + row.losses
            hit_rate = (row.wins / total_bets * 100) if total_bets > 0 else 0.0
            results[str(row.season)] = {
                'bets': total_bets,
                'wins': row.wins,
                'losses': row.losses,
                'hit_rate': round(hit_rate, 2),
            }

        return results

    def get_by_month(self) -> Dict:
        """Get hit rate by month."""
        query = f"""
        SELECT
            FORMAT_DATE('%Y-%m', game_date) as month,
            COUNT(*) as total,
            SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN is_correct = FALSE THEN 1 ELSE 0 END) as losses
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND line_source = 'historical_odds_api'
          AND recommendation IN ('OVER', 'UNDER')
          AND is_correct IS NOT NULL
        GROUP BY month
        ORDER BY month
        """

        results = {}
        for row in self.bq_client.query(query).result():
            total_bets = row.wins + row.losses
            hit_rate = (row.wins / total_bets * 100) if total_bets > 0 else 0.0
            results[row.month] = {
                'bets': total_bets,
                'wins': row.wins,
                'losses': row.losses,
                'hit_rate': round(hit_rate, 2),
            }

        return results

    def get_bankroll_simulation(self) -> Optional[Dict]:
        """Run bankroll simulation using actual bet sequence."""
        if self.skip_simulation:
            return None

        bets = self.get_individual_bets()
        if not bets:
            return None

        # Convert to outcomes list (chronological order)
        outcomes = [b['is_correct'] for b in bets]

        # Simulate with $10,000 bankroll, $100 flat bets at -110
        simulation = simulate_bankroll(
            outcomes=outcomes,
            starting_bankroll=10000,
            bet_size=100,
            odds=STANDARD_JUICE
        )

        return simulation

    def run(self, output_json: bool = False) -> Dict:
        """Calculate and report all hit rate statistics with statistical analysis."""
        logger.info("=" * 70)
        logger.info("PHASE 5: TRUE HIT RATE CALCULATION (Enhanced)")
        logger.info("=" * 70)
        logger.info(f"Date range: {self.start_date} to {self.end_date}")
        logger.info("")

        # Gather all stats
        overall = self.get_overall_stats()
        by_rec = self.get_by_recommendation()
        by_edge = self.get_by_edge_bucket()
        by_season = self.get_by_season()
        by_month = self.get_by_month()
        bankroll_sim = self.get_bankroll_simulation()

        results = {
            'date_range': {
                'start': self.start_date,
                'end': self.end_date,
            },
            'analysis_timestamp': datetime.now().isoformat(),
            'overall': overall,
            'by_recommendation': by_rec,
            'by_edge_bucket': by_edge,
            'by_season': by_season,
            'by_month': by_month,
            'bankroll_simulation': bankroll_sim,
        }

        if output_json:
            print(json.dumps(results, indent=2, default=str))
            return results

        # Pretty print report
        logger.info("=" * 70)
        logger.info("OVERALL RESULTS")
        logger.info("=" * 70)
        logger.info(f"Total Predictions: {overall['total_predictions']:,}")
        logger.info(f"Bets Placed (OVER/UNDER): {overall['bets_placed']:,}")
        logger.info(f"Wins: {overall['wins']:,}")
        logger.info(f"Losses: {overall['losses']:,}")
        logger.info(f"Pushes: {overall['pushes']:,}")
        logger.info(f"Passes: {overall['passes']:,}")
        logger.info("")

        # Main hit rate with CI
        ci = overall['confidence_interval_95']
        logger.info(f"★ HIT RATE: {overall['hit_rate']:.2f}%")
        logger.info(f"  95% Confidence Interval: [{ci[0]:.2f}%, {ci[1]:.2f}%]")
        if overall.get('bootstrap_ci_95'):
            bci = overall['bootstrap_ci_95']
            logger.info(f"  Bootstrap CI (10k samples): [{bci[0]:.2f}%, {bci[1]:.2f}%]")

        logger.info("")
        logger.info(f"  Breakeven: {overall['breakeven']:.2f}%")
        logger.info(f"  Edge vs Breakeven: {overall['edge_vs_breakeven']:+.2f}%")
        logger.info(f"  Profitable: {'YES ✓' if overall['is_profitable'] else 'NO ✗'}")

        # Statistical significance
        logger.info("\n" + "-" * 70)
        logger.info("STATISTICAL SIGNIFICANCE")
        logger.info("-" * 70)
        z_test = overall['statistical_test']
        logger.info(f"  H0: Hit rate = {overall['breakeven']:.2f}% (breakeven)")
        logger.info(f"  H1: Hit rate > {overall['breakeven']:.2f}%")
        logger.info(f"  Z-statistic: {z_test['z_statistic']:.3f}")
        logger.info(f"  P-value: {z_test['p_value']:.6f}")
        if z_test['significant_99']:
            logger.info(f"  Result: HIGHLY SIGNIFICANT (p < 0.01) ✓✓")
        elif z_test['significant_95']:
            logger.info(f"  Result: SIGNIFICANT (p < 0.05) ✓")
        else:
            logger.info(f"  Result: NOT SIGNIFICANT (p >= 0.05) ✗")

        # ROI Analysis
        logger.info("\n" + "-" * 70)
        logger.info("ROI & PROFIT ANALYSIS")
        logger.info("-" * 70)
        roi = overall['roi']
        logger.info(f"  At -110 odds:")
        logger.info(f"    ROI: {roi['roi_pct']:+.2f}%")
        logger.info(f"    Expected Value: ${roi['ev_per_bet']:+.2f} per $110 bet")
        logger.info(f"    Profit per 100 bets: ${roi['profit_per_100_bets']:+.2f}")

        # Kelly Criterion
        kelly = overall['kelly_criterion']
        logger.info("\n  Kelly Criterion Bet Sizing:")
        logger.info(f"    Full Kelly: {kelly['full_kelly_pct']:.2f}% of bankroll")
        logger.info(f"    Half Kelly: {kelly['half_kelly_pct']:.2f}% of bankroll")
        logger.info(f"    Quarter Kelly (recommended): {kelly['quarter_kelly_pct']:.2f}% of bankroll")

        # Bankroll Simulation
        if bankroll_sim:
            logger.info("\n" + "-" * 70)
            logger.info("BANKROLL SIMULATION ($10K start, $100 flat bets)")
            logger.info("-" * 70)
            logger.info(f"  Starting Bankroll: ${bankroll_sim['starting_bankroll']:,.2f}")
            logger.info(f"  Final Bankroll: ${bankroll_sim['final_bankroll']:,.2f}")
            logger.info(f"  Total Profit: ${bankroll_sim['total_profit']:+,.2f}")
            logger.info(f"  Total Return: {bankroll_sim['total_return_pct']:+.2f}%")
            logger.info(f"  Max Drawdown: {bankroll_sim['max_drawdown_pct']:.2f}%")
            logger.info(f"  Peak Bankroll: ${bankroll_sim['peak_bankroll']:,.2f}")
            logger.info(f"  Lowest Point: ${bankroll_sim['lowest_bankroll']:,.2f}")
            logger.info(f"  Longest Win Streak: {bankroll_sim['max_winning_streak']} bets")
            logger.info(f"  Longest Lose Streak: {bankroll_sim['max_losing_streak']} bets")

        logger.info("\n" + "-" * 70)
        logger.info("BY RECOMMENDATION TYPE")
        logger.info("-" * 70)
        for rec, stats in by_rec.items():
            logger.info(f"  {rec}: {stats['hit_rate']:.1f}% ({stats['wins']}/{stats['bets']} bets)")

        logger.info("\n" + "-" * 70)
        logger.info("BY EDGE BUCKET")
        logger.info("-" * 70)
        for bucket, stats in sorted(by_edge.items()):
            bar = '█' * int(stats['hit_rate'] / 5)
            logger.info(f"  {bucket:>8}: {stats['hit_rate']:>5.1f}% {bar} ({stats['bets']:>4} bets)")

        logger.info("\n" + "-" * 70)
        logger.info("BY SEASON")
        logger.info("-" * 70)
        for season, stats in by_season.items():
            logger.info(f"  {season}: {stats['hit_rate']:.1f}% ({stats['wins']}/{stats['bets']} bets)")

        logger.info("\n" + "-" * 70)
        logger.info("BY MONTH (last 6)")
        logger.info("-" * 70)
        months = list(by_month.items())[-6:]
        for month, stats in months:
            logger.info(f"  {month}: {stats['hit_rate']:.1f}% ({stats['bets']} bets)")

        # Final assessment with statistical backing
        logger.info("\n" + "=" * 70)
        logger.info("FINAL ASSESSMENT")
        logger.info("=" * 70)

        # Determine assessment level
        is_significant = z_test['significant_95']
        ci_above_breakeven = ci[0] > overall['breakeven']
        hit_rate = overall['hit_rate']

        if hit_rate >= 58 and is_significant and ci_above_breakeven:
            logger.info("★★★ EXCEPTIONAL - Statistically verified profitable!")
            logger.info(f"    Hit rate {hit_rate:.1f}% with CI entirely above breakeven.")
            logger.info("    Ready for production deployment.")
            assessment = "EXCEPTIONAL"
        elif hit_rate >= 55 and is_significant:
            logger.info("★★☆ STRONG - Statistically significant profit.")
            logger.info(f"    Hit rate {hit_rate:.1f}% significantly above breakeven (p<0.05).")
            logger.info("    Ready for deployment with monitoring.")
            assessment = "STRONG"
        elif hit_rate > overall['breakeven'] and is_significant:
            logger.info("★☆☆ MARGINAL - Profitable but modest edge.")
            logger.info(f"    Hit rate {hit_rate:.1f}% above breakeven, but edge is thin.")
            logger.info("    Deploy with caution, consider tuning.")
            assessment = "MARGINAL"
        elif hit_rate > overall['breakeven']:
            logger.info("⚠ INCONCLUSIVE - Above breakeven but NOT statistically significant.")
            logger.info(f"    Hit rate {hit_rate:.1f}% may be due to variance.")
            logger.info("    Need more data before confident deployment.")
            assessment = "INCONCLUSIVE"
        else:
            logger.info("☆☆☆ NOT PROFITABLE - Below breakeven.")
            logger.info("    Review model logic and edge calculation.")
            assessment = "NOT_PROFITABLE"

        results['assessment'] = assessment

        # Save results to file
        output_dir = PROJECT_ROOT / 'docs/08-projects/current/mlb-pitcher-strikeouts'
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / 'TRUE-HIT-RATE-RESULTS.json'
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"\nResults saved to: {output_file}")

        return results


def main():
    parser = argparse.ArgumentParser(
        description='Calculate hit rate statistics with statistical analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full analysis with bankroll simulation
  python calculate_hit_rate.py

  # Quick analysis (skip simulation)
  python calculate_hit_rate.py --skip-simulation

  # Output as JSON
  python calculate_hit_rate.py --json

  # Specific date range
  python calculate_hit_rate.py --start-date 2024-06-01 --end-date 2024-09-30
        """
    )

    parser.add_argument(
        '--start-date',
        help='Start date (YYYY-MM-DD). Default: 2024-04-09'
    )
    parser.add_argument(
        '--end-date',
        help='End date (YYYY-MM-DD). Default: 2025-09-28'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON'
    )
    parser.add_argument(
        '--skip-simulation',
        action='store_true',
        help='Skip bankroll simulation and bootstrap CI (faster)'
    )

    args = parser.parse_args()

    calculator = HitRateCalculator(
        start_date=args.start_date,
        end_date=args.end_date,
        skip_simulation=args.skip_simulation,
    )

    try:
        calculator.run(output_json=args.json)
    except Exception as e:
        logger.exception(f"Calculation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
