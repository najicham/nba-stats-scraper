#!/usr/bin/env python3
"""
Pitcher-Level Hit Rate Analysis

Analyzes betting performance by individual pitcher to identify:
- Which pitchers we predict best/worst
- Profitable vs unprofitable pitchers
- Recommended bet/avoid lists

This helps optimize betting strategy by filtering to high-performing pitchers.

Usage:
    python scripts/mlb/historical_odds_backfill/analyze_by_pitcher.py

    # Minimum bets per pitcher (default 10)
    python scripts/mlb/historical_odds_backfill/analyze_by_pitcher.py --min-bets 20

    # Output as JSON
    python scripts/mlb/historical_odds_backfill/analyze_by_pitcher.py --json
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


def calculate_wilson_ci(wins: int, n: int, confidence: float = 0.95) -> tuple:
    """Calculate Wilson score confidence interval."""
    if n == 0:
        return (0.0, 0.0)

    z = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}.get(confidence, 1.96)
    p = wins / n

    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denominator

    lower = max(0, center - spread) * 100
    upper = min(1, center + spread) * 100

    return (round(lower, 2), round(upper, 2))


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


class PitcherAnalyzer:
    """Analyzes betting performance by individual pitcher."""

    def __init__(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        min_bets: int = 10,
    ):
        self.start_date = start_date or '2024-04-09'
        self.end_date = end_date or '2025-09-28'
        self.min_bets = min_bets
        self.bq_client = bigquery.Client(project=PROJECT_ID)

    def get_pitcher_stats(self) -> List[Dict]:
        """Get hit rate statistics by pitcher."""
        query = f"""
        SELECT
            pitcher_lookup,
            pitcher_name,
            team_abbr,
            COUNT(*) as total_bets,
            SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN is_correct = FALSE THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN recommendation = 'OVER' THEN 1 ELSE 0 END) as over_bets,
            SUM(CASE WHEN recommendation = 'UNDER' THEN 1 ELSE 0 END) as under_bets,
            SUM(CASE WHEN recommendation = 'OVER' AND is_correct = TRUE THEN 1 ELSE 0 END) as over_wins,
            SUM(CASE WHEN recommendation = 'UNDER' AND is_correct = TRUE THEN 1 ELSE 0 END) as under_wins,
            AVG(ABS(predicted_strikeouts - strikeouts_line)) as avg_edge,
            AVG(predicted_strikeouts) as avg_predicted,
            AVG(actual_strikeouts) as avg_actual,
            AVG(strikeouts_line) as avg_line
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND line_source = 'historical_odds_api'
          AND recommendation IN ('OVER', 'UNDER')
          AND is_correct IS NOT NULL
        GROUP BY pitcher_lookup, pitcher_name, team_abbr
        HAVING COUNT(*) >= {self.min_bets}
        ORDER BY COUNT(*) DESC
        """

        results = list(self.bq_client.query(query).result())
        pitchers = []

        for row in results:
            total = row.wins + row.losses
            hit_rate = row.wins / total * 100 if total > 0 else 0
            hit_rate_decimal = row.wins / total if total > 0 else 0

            over_hit = row.over_wins / row.over_bets * 100 if row.over_bets > 0 else 0
            under_hit = row.under_wins / row.under_bets * 100 if row.under_bets > 0 else 0

            ci = calculate_wilson_ci(row.wins, total)
            roi = calculate_roi(hit_rate_decimal, STANDARD_JUICE)

            pitchers.append({
                'pitcher_lookup': row.pitcher_lookup,
                'pitcher_name': row.pitcher_name,
                'team': row.team_abbr,
                'total_bets': total,
                'wins': row.wins,
                'losses': row.losses,
                'hit_rate': round(hit_rate, 2),
                'confidence_interval': ci,
                'roi_pct': roi,
                'over_bets': row.over_bets,
                'over_hit_rate': round(over_hit, 2),
                'under_bets': row.under_bets,
                'under_hit_rate': round(under_hit, 2),
                'avg_edge': round(row.avg_edge, 3) if row.avg_edge else 0,
                'avg_predicted': round(row.avg_predicted, 2) if row.avg_predicted else 0,
                'avg_actual': round(row.avg_actual, 2) if row.avg_actual else 0,
                'avg_line': round(row.avg_line, 2) if row.avg_line else 0,
                # Derived metrics
                'is_profitable': hit_rate > BREAKEVEN_RATE,
                'ci_above_breakeven': ci[0] > BREAKEVEN_RATE,
                'prediction_bias': round((row.avg_predicted or 0) - (row.avg_actual or 0), 2),
            })

        return pitchers

    def categorize_pitchers(self, pitchers: List[Dict]) -> Dict:
        """Categorize pitchers into bet/avoid lists."""
        # Sort by various criteria
        by_hit_rate = sorted(pitchers, key=lambda x: x['hit_rate'], reverse=True)
        by_roi = sorted(pitchers, key=lambda x: x['roi_pct'], reverse=True)
        by_volume = sorted(pitchers, key=lambda x: x['total_bets'], reverse=True)

        # Statistically significant winners (CI lower bound > breakeven)
        significant_winners = [p for p in pitchers if p['ci_above_breakeven']]
        significant_winners = sorted(significant_winners, key=lambda x: x['hit_rate'], reverse=True)

        # Consistent losers (upper CI < breakeven)
        consistent_losers = [p for p in pitchers if p['confidence_interval'][1] < BREAKEVEN_RATE]
        consistent_losers = sorted(consistent_losers, key=lambda x: x['hit_rate'])

        # High volume profitable
        high_volume_profitable = [p for p in pitchers if p['total_bets'] >= 20 and p['is_profitable']]
        high_volume_profitable = sorted(high_volume_profitable, key=lambda x: x['total_bets'], reverse=True)

        # OVER specialists (much better at OVER than UNDER)
        over_specialists = [
            p for p in pitchers
            if p['over_bets'] >= 5 and p['over_hit_rate'] > 60 and p['over_hit_rate'] > p['under_hit_rate'] + 10
        ]

        # UNDER specialists
        under_specialists = [
            p for p in pitchers
            if p['under_bets'] >= 5 and p['under_hit_rate'] > 60 and p['under_hit_rate'] > p['over_hit_rate'] + 10
        ]

        return {
            'top_10_by_hit_rate': by_hit_rate[:10],
            'bottom_10_by_hit_rate': by_hit_rate[-10:][::-1],
            'top_10_by_roi': by_roi[:10],
            'top_10_by_volume': by_volume[:10],
            'significant_winners': significant_winners[:10],
            'consistent_losers': consistent_losers[:10],
            'high_volume_profitable': high_volume_profitable[:10],
            'over_specialists': over_specialists[:5],
            'under_specialists': under_specialists[:5],
        }

    def generate_recommendations(self, categories: Dict) -> Dict:
        """Generate actionable betting recommendations."""
        recommendations = {
            'always_bet': [],
            'consider_betting': [],
            'avoid': [],
            'over_only': [],
            'under_only': [],
        }

        # Always bet: statistically significant winners with good volume
        for p in categories['significant_winners']:
            if p['total_bets'] >= 15:
                recommendations['always_bet'].append({
                    'pitcher': p['pitcher_name'],
                    'team': p['team'],
                    'hit_rate': p['hit_rate'],
                    'roi': p['roi_pct'],
                    'bets': p['total_bets'],
                    'reason': f"CI [{p['confidence_interval'][0]}%, {p['confidence_interval'][1]}%] above breakeven"
                })

        # Consider betting: profitable but not statistically significant yet
        for p in categories['high_volume_profitable']:
            if p not in [r['pitcher'] for r in recommendations['always_bet']]:
                if not p['ci_above_breakeven']:
                    recommendations['consider_betting'].append({
                        'pitcher': p['pitcher_name'],
                        'team': p['team'],
                        'hit_rate': p['hit_rate'],
                        'roi': p['roi_pct'],
                        'bets': p['total_bets'],
                        'reason': f"Profitable but needs more data (CI includes breakeven)"
                    })

        # Avoid: consistent losers
        for p in categories['consistent_losers']:
            recommendations['avoid'].append({
                'pitcher': p['pitcher_name'],
                'team': p['team'],
                'hit_rate': p['hit_rate'],
                'roi': p['roi_pct'],
                'bets': p['total_bets'],
                'reason': f"CI [{p['confidence_interval'][0]}%, {p['confidence_interval'][1]}%] entirely below breakeven"
            })

        # Direction specialists
        for p in categories['over_specialists']:
            recommendations['over_only'].append({
                'pitcher': p['pitcher_name'],
                'team': p['team'],
                'over_hit_rate': p['over_hit_rate'],
                'under_hit_rate': p['under_hit_rate'],
                'reason': f"OVER: {p['over_hit_rate']}% vs UNDER: {p['under_hit_rate']}%"
            })

        for p in categories['under_specialists']:
            recommendations['under_only'].append({
                'pitcher': p['pitcher_name'],
                'team': p['team'],
                'over_hit_rate': p['over_hit_rate'],
                'under_hit_rate': p['under_hit_rate'],
                'reason': f"UNDER: {p['under_hit_rate']}% vs OVER: {p['over_hit_rate']}%"
            })

        return recommendations

    def calculate_filtered_performance(self, pitchers: List[Dict], categories: Dict) -> Dict:
        """Calculate what performance would be if we filtered to recommended pitchers."""
        all_bets = sum(p['total_bets'] for p in pitchers)
        all_wins = sum(p['wins'] for p in pitchers)
        all_hit_rate = all_wins / all_bets * 100 if all_bets > 0 else 0

        # If we only bet on significant winners
        sig_win_bets = sum(p['total_bets'] for p in categories['significant_winners'])
        sig_win_wins = sum(p['wins'] for p in categories['significant_winners'])
        sig_win_hit_rate = sig_win_wins / sig_win_bets * 100 if sig_win_bets > 0 else 0

        # If we avoided consistent losers
        losers_lookup = {p['pitcher_lookup'] for p in categories['consistent_losers']}
        filtered_bets = sum(p['total_bets'] for p in pitchers if p['pitcher_lookup'] not in losers_lookup)
        filtered_wins = sum(p['wins'] for p in pitchers if p['pitcher_lookup'] not in losers_lookup)
        filtered_hit_rate = filtered_wins / filtered_bets * 100 if filtered_bets > 0 else 0

        return {
            'baseline': {
                'bets': all_bets,
                'wins': all_wins,
                'hit_rate': round(all_hit_rate, 2),
                'roi': calculate_roi(all_wins / all_bets if all_bets > 0 else 0, STANDARD_JUICE),
            },
            'significant_winners_only': {
                'bets': sig_win_bets,
                'wins': sig_win_wins,
                'hit_rate': round(sig_win_hit_rate, 2),
                'roi': calculate_roi(sig_win_wins / sig_win_bets if sig_win_bets > 0 else 0, STANDARD_JUICE),
                'bets_reduction': round((all_bets - sig_win_bets) / all_bets * 100, 1) if all_bets > 0 else 0,
            },
            'exclude_losers': {
                'bets': filtered_bets,
                'wins': filtered_wins,
                'hit_rate': round(filtered_hit_rate, 2),
                'roi': calculate_roi(filtered_wins / filtered_bets if filtered_bets > 0 else 0, STANDARD_JUICE),
                'bets_reduction': round((all_bets - filtered_bets) / all_bets * 100, 1) if all_bets > 0 else 0,
            }
        }

    def run(self, output_json: bool = False) -> Dict:
        """Run the full pitcher analysis."""
        logger.info("=" * 70)
        logger.info("PITCHER-LEVEL HIT RATE ANALYSIS")
        logger.info("=" * 70)
        logger.info(f"Date range: {self.start_date} to {self.end_date}")
        logger.info(f"Minimum bets per pitcher: {self.min_bets}")
        logger.info("")

        # Get pitcher stats
        pitchers = self.get_pitcher_stats()
        logger.info(f"Found {len(pitchers)} pitchers with >= {self.min_bets} bets")

        if not pitchers:
            logger.warning("No pitchers found meeting criteria!")
            return {}

        # Categorize
        categories = self.categorize_pitchers(pitchers)

        # Generate recommendations
        recommendations = self.generate_recommendations(categories)

        # Calculate filtered performance
        filtered_perf = self.calculate_filtered_performance(pitchers, categories)

        results = {
            'date_range': {'start': self.start_date, 'end': self.end_date},
            'analysis_timestamp': datetime.now().isoformat(),
            'min_bets_threshold': self.min_bets,
            'total_pitchers_analyzed': len(pitchers),
            'categories': categories,
            'recommendations': recommendations,
            'filtered_performance': filtered_perf,
            'all_pitchers': pitchers,
        }

        if output_json:
            print(json.dumps(results, indent=2, default=str))
            return results

        # Pretty print
        logger.info("\n" + "=" * 70)
        logger.info("TOP 10 PITCHERS BY HIT RATE")
        logger.info("=" * 70)
        for i, p in enumerate(categories['top_10_by_hit_rate'], 1):
            ci = p['confidence_interval']
            logger.info(
                f"  {i:2}. {p['pitcher_name']:<25} {p['hit_rate']:5.1f}% "
                f"[{ci[0]:.1f}%-{ci[1]:.1f}%] ({p['wins']}/{p['total_bets']} bets) "
                f"ROI: {p['roi_pct']:+.1f}%"
            )

        logger.info("\n" + "-" * 70)
        logger.info("BOTTOM 10 PITCHERS BY HIT RATE")
        logger.info("-" * 70)
        for i, p in enumerate(categories['bottom_10_by_hit_rate'], 1):
            ci = p['confidence_interval']
            logger.info(
                f"  {i:2}. {p['pitcher_name']:<25} {p['hit_rate']:5.1f}% "
                f"[{ci[0]:.1f}%-{ci[1]:.1f}%] ({p['wins']}/{p['total_bets']} bets) "
                f"ROI: {p['roi_pct']:+.1f}%"
            )

        logger.info("\n" + "=" * 70)
        logger.info("STATISTICALLY SIGNIFICANT WINNERS")
        logger.info("(CI lower bound > 52.38% breakeven)")
        logger.info("=" * 70)
        if categories['significant_winners']:
            for p in categories['significant_winners'][:10]:
                logger.info(
                    f"  ✓ {p['pitcher_name']:<25} {p['hit_rate']:5.1f}% "
                    f"CI: [{p['confidence_interval'][0]:.1f}%, {p['confidence_interval'][1]:.1f}%]"
                )
        else:
            logger.info("  None found (need more data or better performance)")

        logger.info("\n" + "-" * 70)
        logger.info("CONSISTENT LOSERS (CI upper bound < breakeven)")
        logger.info("-" * 70)
        if categories['consistent_losers']:
            for p in categories['consistent_losers'][:10]:
                logger.info(
                    f"  ✗ {p['pitcher_name']:<25} {p['hit_rate']:5.1f}% "
                    f"CI: [{p['confidence_interval'][0]:.1f}%, {p['confidence_interval'][1]:.1f}%]"
                )
        else:
            logger.info("  None found")

        # Recommendations
        logger.info("\n" + "=" * 70)
        logger.info("BETTING RECOMMENDATIONS")
        logger.info("=" * 70)

        logger.info("\n✓ ALWAYS BET (statistically verified):")
        if recommendations['always_bet']:
            for r in recommendations['always_bet'][:5]:
                logger.info(f"    {r['pitcher']:<25} {r['hit_rate']:.1f}% | {r['bets']} bets | ROI: {r['roi']:+.1f}%")
        else:
            logger.info("    None meet strict criteria yet")

        logger.info("\n⚠ CONSIDER BETTING (profitable, needs more data):")
        if recommendations['consider_betting']:
            for r in recommendations['consider_betting'][:5]:
                logger.info(f"    {r['pitcher']:<25} {r['hit_rate']:.1f}% | {r['bets']} bets | ROI: {r['roi']:+.1f}%")
        else:
            logger.info("    None")

        logger.info("\n✗ AVOID (consistent underperformers):")
        if recommendations['avoid']:
            for r in recommendations['avoid'][:5]:
                logger.info(f"    {r['pitcher']:<25} {r['hit_rate']:.1f}% | {r['bets']} bets | ROI: {r['roi']:+.1f}%")
        else:
            logger.info("    None meet strict criteria")

        # Filtered performance impact
        logger.info("\n" + "=" * 70)
        logger.info("PERFORMANCE IMPACT OF FILTERING")
        logger.info("=" * 70)
        fp = filtered_perf

        logger.info(f"\n  BASELINE (all pitchers):")
        logger.info(f"    Bets: {fp['baseline']['bets']:,}")
        logger.info(f"    Hit Rate: {fp['baseline']['hit_rate']:.2f}%")
        logger.info(f"    ROI: {fp['baseline']['roi']:+.2f}%")

        logger.info(f"\n  IF ONLY BETTING SIGNIFICANT WINNERS:")
        logger.info(f"    Bets: {fp['significant_winners_only']['bets']:,} ({fp['significant_winners_only']['bets_reduction']:.0f}% reduction)")
        logger.info(f"    Hit Rate: {fp['significant_winners_only']['hit_rate']:.2f}%")
        logger.info(f"    ROI: {fp['significant_winners_only']['roi']:+.2f}%")

        logger.info(f"\n  IF EXCLUDING CONSISTENT LOSERS:")
        logger.info(f"    Bets: {fp['exclude_losers']['bets']:,} ({fp['exclude_losers']['bets_reduction']:.0f}% reduction)")
        logger.info(f"    Hit Rate: {fp['exclude_losers']['hit_rate']:.2f}%")
        logger.info(f"    ROI: {fp['exclude_losers']['roi']:+.2f}%")

        # Save results
        output_dir = PROJECT_ROOT / 'docs/08-projects/current/mlb-pitcher-strikeouts'
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / 'PITCHER-ANALYSIS-RESULTS.json'
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"\nResults saved to: {output_file}")

        return results


def main():
    parser = argparse.ArgumentParser(
        description='Analyze hit rate by individual pitcher',
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
        '--min-bets',
        type=int,
        default=10,
        help='Minimum bets per pitcher to include (default: 10)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON'
    )

    args = parser.parse_args()

    analyzer = PitcherAnalyzer(
        start_date=args.start_date,
        end_date=args.end_date,
        min_bets=args.min_bets,
    )

    try:
        analyzer.run(output_json=args.json)
    except Exception as e:
        logger.exception(f"Analysis failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
