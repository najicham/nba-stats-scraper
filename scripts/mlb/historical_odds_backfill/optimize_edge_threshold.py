#!/usr/bin/env python3
"""
Edge Threshold Optimizer

Analyzes hit rate at different edge thresholds to find the optimal
minimum edge for betting. Helps answer: "Should we only bet when
our predicted edge is > 0.5K, > 1.0K, etc.?"

Output:
- Hit rate by edge threshold
- ROI by edge threshold
- Optimal threshold recommendation
- Trade-off analysis (volume vs accuracy)

Usage:
    python scripts/mlb/historical_odds_backfill/optimize_edge_threshold.py

    # Output as JSON
    python scripts/mlb/historical_odds_backfill/optimize_edge_threshold.py --json
"""

import argparse
import json
import logging
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
BREAKEVEN_RATE = 52.38
STANDARD_JUICE = -110

# Edge thresholds to test (in strikeouts)
EDGE_THRESHOLDS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]


def calculate_roi(hit_rate: float, odds: int = -110) -> float:
    """Calculate ROI at given odds."""
    if odds < 0:
        risk = abs(odds)
        win_amount = 100
    else:
        risk = 100
        win_amount = odds

    ev_per_bet = (hit_rate * win_amount) - ((1 - hit_rate) * risk)
    roi = ev_per_bet / risk * 100

    return round(roi, 2)


def calculate_wilson_ci(wins: int, n: int) -> tuple:
    """Calculate Wilson score 95% CI."""
    if n == 0:
        return (0.0, 0.0)

    z = 1.96
    p = wins / n

    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denominator

    lower = max(0, center - spread) * 100
    upper = min(1, center + spread) * 100

    return (round(lower, 2), round(upper, 2))


class EdgeThresholdOptimizer:
    """Optimizes edge threshold for betting."""

    def __init__(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        self.start_date = start_date or '2024-04-09'
        self.end_date = end_date or '2025-09-28'
        self.bq_client = bigquery.Client(project=PROJECT_ID)

    def get_bets_by_edge(self) -> List[Dict]:
        """Get all bet outcomes with edge calculation."""
        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
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
        ORDER BY ABS(predicted_strikeouts - strikeouts_line) DESC
        """

        results = list(self.bq_client.query(query).result())
        return [dict(row) for row in results]

    def analyze_threshold(self, bets: List[Dict], min_edge: float) -> Dict:
        """Analyze performance at a specific edge threshold."""
        filtered = [b for b in bets if b['edge'] >= min_edge]

        if not filtered:
            return {
                'threshold': min_edge,
                'bets': 0,
                'wins': 0,
                'hit_rate': 0,
                'roi': 0,
                'ci': (0, 0),
            }

        wins = sum(1 for b in filtered if b['is_correct'])
        total = len(filtered)
        hit_rate = wins / total * 100
        hit_rate_decimal = wins / total

        ci = calculate_wilson_ci(wins, total)
        roi = calculate_roi(hit_rate_decimal, STANDARD_JUICE)

        return {
            'threshold': min_edge,
            'bets': total,
            'wins': wins,
            'losses': total - wins,
            'hit_rate': round(hit_rate, 2),
            'hit_rate_decimal': round(hit_rate_decimal, 4),
            'roi': roi,
            'ci': ci,
            'ci_above_breakeven': ci[0] > BREAKEVEN_RATE,
            'pct_of_total_bets': round(total / len(bets) * 100, 1) if bets else 0,
        }

    def find_optimal_threshold(self, results: List[Dict]) -> Dict:
        """Find the optimal edge threshold based on different criteria."""
        # Criterion 1: Maximum ROI
        valid = [r for r in results if r['bets'] >= 50]  # Need minimum sample
        if valid:
            max_roi = max(valid, key=lambda x: x['roi'])
        else:
            max_roi = results[0] if results else None

        # Criterion 2: Maximum hit rate (with min volume)
        valid_100 = [r for r in results if r['bets'] >= 100]
        if valid_100:
            max_hr = max(valid_100, key=lambda x: x['hit_rate'])
        else:
            max_hr = max(valid, key=lambda x: x['hit_rate']) if valid else None

        # Criterion 3: Statistically significant (CI above breakeven)
        sig = [r for r in results if r['ci_above_breakeven'] and r['bets'] >= 50]
        best_sig = sig[0] if sig else None  # First one has lowest threshold meeting criteria

        # Criterion 4: Best risk-adjusted (highest hit rate with reasonable volume)
        # Score = hit_rate * log(bets)
        scored = []
        for r in results:
            if r['bets'] >= 30:
                score = r['hit_rate'] * math.log(r['bets'])
                scored.append((r, score))
        if scored:
            best_risk_adj = max(scored, key=lambda x: x[1])[0]
        else:
            best_risk_adj = None

        return {
            'max_roi': max_roi,
            'max_hit_rate': max_hr,
            'first_significant': best_sig,
            'best_risk_adjusted': best_risk_adj,
        }

    def run(self, output_json: bool = False) -> Dict:
        """Run the edge threshold optimization."""
        logger.info("=" * 70)
        logger.info("EDGE THRESHOLD OPTIMIZATION")
        logger.info("=" * 70)
        logger.info(f"Date range: {self.start_date} to {self.end_date}")
        logger.info("")

        # Get all bets
        bets = self.get_bets_by_edge()
        logger.info(f"Total bets: {len(bets)}")

        if not bets:
            logger.warning("No bets found!")
            return {}

        # Analyze each threshold
        results = []
        for threshold in EDGE_THRESHOLDS:
            result = self.analyze_threshold(bets, threshold)
            results.append(result)

        # Find optimal
        optimal = self.find_optimal_threshold(results)

        output = {
            'date_range': {'start': self.start_date, 'end': self.end_date},
            'analysis_timestamp': datetime.now().isoformat(),
            'total_bets': len(bets),
            'thresholds_analyzed': results,
            'optimal_thresholds': optimal,
        }

        if output_json:
            print(json.dumps(output, indent=2, default=str))
            return output

        # Pretty print results
        logger.info("\n" + "=" * 70)
        logger.info("PERFORMANCE BY EDGE THRESHOLD")
        logger.info("=" * 70)
        logger.info("")
        logger.info(f"{'Edge >=':>8} | {'Bets':>6} | {'Hit Rate':>10} | {'ROI':>8} | {'95% CI':>18} | {'% Total':>8}")
        logger.info("-" * 70)

        for r in results:
            ci_str = f"[{r['ci'][0]:.1f}%-{r['ci'][1]:.1f}%]"
            sig = "★" if r['ci_above_breakeven'] else " "
            logger.info(
                f"{r['threshold']:>7.2f}K | {r['bets']:>6} | {r['hit_rate']:>9.2f}% | "
                f"{r['roi']:>+7.2f}% | {ci_str:>17} {sig}| {r['pct_of_total_bets']:>7.1f}%"
            )

        # Optimal recommendations
        logger.info("\n" + "=" * 70)
        logger.info("OPTIMAL THRESHOLD RECOMMENDATIONS")
        logger.info("=" * 70)

        if optimal['max_roi']:
            r = optimal['max_roi']
            logger.info(f"\n  Maximum ROI:")
            logger.info(f"    Threshold: >= {r['threshold']:.2f}K")
            logger.info(f"    ROI: {r['roi']:+.2f}%")
            logger.info(f"    Hit Rate: {r['hit_rate']:.2f}%")
            logger.info(f"    Bets: {r['bets']}")

        if optimal['max_hit_rate']:
            r = optimal['max_hit_rate']
            logger.info(f"\n  Maximum Hit Rate (min 100 bets):")
            logger.info(f"    Threshold: >= {r['threshold']:.2f}K")
            logger.info(f"    Hit Rate: {r['hit_rate']:.2f}%")
            logger.info(f"    ROI: {r['roi']:+.2f}%")
            logger.info(f"    Bets: {r['bets']}")

        if optimal['first_significant']:
            r = optimal['first_significant']
            logger.info(f"\n  First Statistically Significant (CI above breakeven):")
            logger.info(f"    Threshold: >= {r['threshold']:.2f}K")
            logger.info(f"    Hit Rate: {r['hit_rate']:.2f}%")
            logger.info(f"    CI: [{r['ci'][0]:.2f}%, {r['ci'][1]:.2f}%]")
            logger.info(f"    Bets: {r['bets']}")
        else:
            logger.info(f"\n  First Statistically Significant: None found")
            logger.info(f"    (No threshold has CI lower bound > {BREAKEVEN_RATE}%)")

        if optimal['best_risk_adjusted']:
            r = optimal['best_risk_adjusted']
            logger.info(f"\n  Best Risk-Adjusted (hit rate × volume):")
            logger.info(f"    Threshold: >= {r['threshold']:.2f}K")
            logger.info(f"    Hit Rate: {r['hit_rate']:.2f}%")
            logger.info(f"    Bets: {r['bets']}")

        # Trade-off analysis
        logger.info("\n" + "=" * 70)
        logger.info("TRADE-OFF ANALYSIS")
        logger.info("=" * 70)

        base = results[0]  # No threshold
        for r in results[1:]:
            if r['bets'] > 0 and base['bets'] > 0:
                volume_loss = (base['bets'] - r['bets']) / base['bets'] * 100
                hr_gain = r['hit_rate'] - base['hit_rate']
                roi_gain = r['roi'] - base['roi']

                if hr_gain > 0:
                    logger.info(
                        f"\n  Edge >= {r['threshold']:.2f}K vs No Threshold:"
                    )
                    logger.info(
                        f"    Volume: -{volume_loss:.1f}% ({base['bets']} → {r['bets']} bets)"
                    )
                    logger.info(
                        f"    Hit Rate: +{hr_gain:.2f}% ({base['hit_rate']:.2f}% → {r['hit_rate']:.2f}%)"
                    )
                    logger.info(
                        f"    ROI: {roi_gain:+.2f}% ({base['roi']:+.2f}% → {r['roi']:+.2f}%)"
                    )

        # Final recommendation
        logger.info("\n" + "=" * 70)
        logger.info("RECOMMENDATION")
        logger.info("=" * 70)

        # Determine best overall recommendation
        if optimal['first_significant']:
            rec = optimal['first_significant']
            logger.info(f"\n  ★ RECOMMENDED: Use edge threshold >= {rec['threshold']:.2f}K")
            logger.info(f"    This is the lowest threshold with statistically significant profitability.")
            logger.info(f"    Expected performance: {rec['hit_rate']:.2f}% hit rate, {rec['roi']:+.2f}% ROI")
        elif optimal['best_risk_adjusted']:
            rec = optimal['best_risk_adjusted']
            logger.info(f"\n  ★ RECOMMENDED: Use edge threshold >= {rec['threshold']:.2f}K")
            logger.info(f"    Best balance of hit rate and volume.")
            logger.info(f"    Expected performance: {rec['hit_rate']:.2f}% hit rate, {rec['roi']:+.2f}% ROI")
        else:
            logger.info(f"\n  ⚠ No clear recommendation - need more data or better model performance")

        # Save results
        output_dir = PROJECT_ROOT / 'docs/08-projects/current/mlb-pitcher-strikeouts'
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / 'EDGE-THRESHOLD-OPTIMIZATION.json'
        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        logger.info(f"\nResults saved to: {output_file}")

        return output


def main():
    parser = argparse.ArgumentParser(
        description='Optimize edge threshold for betting',
        formatter_class=argparse.RawDescriptionHelpFormatter,
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

    args = parser.parse_args()

    optimizer = EdgeThresholdOptimizer(
        start_date=args.start_date,
        end_date=args.end_date,
    )

    try:
        optimizer.run(output_json=args.json)
    except Exception as e:
        logger.exception(f"Optimization failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
