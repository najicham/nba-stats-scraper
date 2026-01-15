#!/usr/bin/env python3
"""
MLB Prediction Synthetic Hit Rate Analysis

Analyzes betting performance using SYNTHETIC betting lines (pitcher rolling averages).
Estimates what hit rate WOULD have been if we had bet against rolling averages.

This is Layer 2 of our hit rate measurement framework.

IMPORTANT: This uses synthetic lines, not real betting lines. Results are directional
indicators, not guarantees of real betting performance.

Usage:
    python scripts/mlb/historical_odds_backfill/analyze_synthetic_hit_rate.py

Outputs:
    - docs/08-projects/current/mlb-pitcher-strikeouts/SYNTHETIC-HIT-RATE-REPORT.md
    - JSON results file for programmatic access
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Any
from collections import defaultdict

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from google.cloud import bigquery
import numpy as np

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = 'nba-props-platform'
EDGE_THRESHOLD = 0.5  # Minimum edge to make a bet
BREAKEVEN_HIT_RATE = 52.4  # At -110 odds


class SyntheticHitRateAnalyzer:
    """Analyze betting performance using synthetic betting lines."""

    def __init__(self):
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.results = {}

    def get_predictions_with_synthetic_lines(self) -> List[Dict[str, Any]]:
        """Get predictions with synthetic betting lines (rolling averages)."""
        query = """
        WITH pitcher_rolling_stats AS (
            -- Get rolling averages for each pitcher on each game date
            SELECT
                player_lookup,
                game_date,
                k_avg_last_5,
                k_avg_last_10,
                season_k_per_9,
                is_home,
                opponent_team_abbr,
                strikeouts as actual_strikeouts
            FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
            WHERE game_date >= '2024-04-01' AND game_date <= '2025-10-01'
        )

        SELECT
            p.game_date,
            p.pitcher_lookup,
            p.pitcher_name,
            p.team_abbr,
            p.opponent_team_abbr,
            p.is_home,
            p.predicted_strikeouts,
            p.confidence,

            -- Synthetic betting lines (Method A: Rolling averages)
            prs.k_avg_last_10 as synthetic_line_simple,
            prs.k_avg_last_5 as synthetic_line_recent,

            -- Method B: Context-adjusted line
            CASE
                WHEN p.is_home THEN prs.k_avg_last_10 * 1.05  -- Home boost
                ELSE prs.k_avg_last_10 * 0.95  -- Away penalty
            END as synthetic_line_adjusted,

            -- Actual result
            prs.actual_strikeouts,

            -- Calculate edge (prediction vs synthetic line)
            p.predicted_strikeouts - prs.k_avg_last_10 as edge_simple,
            p.predicted_strikeouts - CASE
                WHEN p.is_home THEN prs.k_avg_last_10 * 1.05
                ELSE prs.k_avg_last_10 * 0.95
            END as edge_adjusted,

            -- Additional context
            prs.k_avg_last_5,
            prs.season_k_per_9

        FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts` p
        INNER JOIN pitcher_rolling_stats prs
          ON p.pitcher_lookup = prs.player_lookup
          AND p.game_date = prs.game_date
        WHERE p.game_date >= '2024-04-01' AND p.game_date <= '2025-10-01'
          AND prs.k_avg_last_10 IS NOT NULL  -- Only include if we have rolling stats
        ORDER BY p.game_date, p.pitcher_lookup
        """

        logger.info("Fetching predictions with synthetic betting lines...")
        results = self.bq_client.query(query).result()
        data = [dict(row) for row in results]
        logger.info(f"Found {len(data)} predictions with synthetic lines")

        return data

    def calculate_bets_and_outcomes(self, data: List[Dict],
                                   line_method: str = 'simple') -> List[Dict]:
        """
        Calculate which bets we would make and their outcomes.

        Args:
            data: Predictions with synthetic lines
            line_method: 'simple' or 'adjusted'
        """
        logger.info(f"\nCalculating bets using {line_method} line method...")

        bets = []
        for row in data:
            # Select line method
            if line_method == 'simple':
                synthetic_line = row['synthetic_line_simple']
                edge = row['edge_simple']
            else:
                synthetic_line = row['synthetic_line_adjusted']
                edge = row['edge_adjusted']

            # Skip if no edge or edge too small
            if abs(edge) < EDGE_THRESHOLD:
                continue

            # Determine recommendation
            recommendation = 'OVER' if edge > 0 else 'UNDER'

            # Calculate outcome
            actual = row['actual_strikeouts']
            if recommendation == 'OVER':
                won = actual > synthetic_line
            else:  # UNDER
                won = actual < synthetic_line

            # Push (tie) handling - count as loss for conservative estimate
            if actual == synthetic_line:
                won = False

            bets.append({
                'game_date': row['game_date'],
                'pitcher_name': row['pitcher_name'],
                'predicted': row['predicted_strikeouts'],
                'synthetic_line': synthetic_line,
                'actual': actual,
                'edge': edge,
                'recommendation': recommendation,
                'won': won,
                'confidence': row['confidence'],
                'is_home': row['is_home']
            })

        logger.info(f"Generated {len(bets)} bets from {len(data)} predictions")
        logger.info(f"Betting ratio: {len(bets)/len(data)*100:.1f}%")

        return bets

    def calculate_hit_rate_metrics(self, bets: List[Dict], method_name: str) -> Dict[str, Any]:
        """Calculate hit rate metrics for a set of bets."""
        logger.info("\n" + "="*80)
        logger.info(f"HIT RATE METRICS - {method_name.upper()}")
        logger.info("="*80)

        if not bets:
            logger.warning("No bets to analyze!")
            return {}

        # Overall metrics
        total_bets = len(bets)
        wins = sum(1 for b in bets if b['won'])
        losses = total_bets - wins
        hit_rate = wins / total_bets * 100

        # By recommendation
        over_bets = [b for b in bets if b['recommendation'] == 'OVER']
        under_bets = [b for b in bets if b['recommendation'] == 'UNDER']

        over_wins = sum(1 for b in over_bets if b['won'])
        under_wins = sum(1 for b in under_bets if b['won'])

        over_hit_rate = over_wins / len(over_bets) * 100 if over_bets else 0
        under_hit_rate = under_wins / len(under_bets) * 100 if under_bets else 0

        # Edge analysis
        avg_edge_all = np.mean([abs(b['edge']) for b in bets])
        avg_edge_wins = np.mean([abs(b['edge']) for b in bets if b['won']]) if wins > 0 else 0
        avg_edge_losses = np.mean([abs(b['edge']) for b in bets if not b['won']]) if losses > 0 else 0

        metrics = {
            'total_bets': total_bets,
            'wins': wins,
            'losses': losses,
            'hit_rate': round(hit_rate, 2),
            'edge_vs_breakeven': round(hit_rate - BREAKEVEN_HIT_RATE, 2),
            'over_bets': len(over_bets),
            'over_wins': over_wins,
            'over_hit_rate': round(over_hit_rate, 2),
            'under_bets': len(under_bets),
            'under_wins': under_wins,
            'under_hit_rate': round(under_hit_rate, 2),
            'avg_edge': round(avg_edge_all, 3),
            'avg_edge_wins': round(avg_edge_wins, 3),
            'avg_edge_losses': round(avg_edge_losses, 3),
        }

        # Logging
        logger.info(f"\nOverall Hit Rate: {metrics['hit_rate']}%")
        logger.info(f"Total Bets: {total_bets} ({wins}W / {losses}L)")
        logger.info(f"vs Breakeven (52.4%): {metrics['edge_vs_breakeven']:+.2f}%")

        logger.info(f"\nOVER Bets: {over_hit_rate:.1f}% ({over_wins}/{len(over_bets)})")
        logger.info(f"UNDER Bets: {under_hit_rate:.1f}% ({under_wins}/{len(under_bets)})")

        logger.info(f"\nEdge Analysis:")
        logger.info(f"  Avg Edge (All): {avg_edge_all:.3f} K")
        logger.info(f"  Avg Edge (Wins): {avg_edge_wins:.3f} K")
        logger.info(f"  Avg Edge (Losses): {avg_edge_losses:.3f} K")

        return metrics

    def analyze_by_edge_size(self, bets: List[Dict]) -> Dict[str, Any]:
        """Analyze hit rate by edge size buckets."""
        logger.info("\n" + "="*80)
        logger.info("HIT RATE BY EDGE SIZE")
        logger.info("="*80)

        buckets = {
            '0.5-1.0': [],
            '1.0-1.5': [],
            '1.5-2.0': [],
            '2.0+': []
        }

        for bet in bets:
            edge = abs(bet['edge'])
            if edge < 1.0:
                bucket = '0.5-1.0'
            elif edge < 1.5:
                bucket = '1.0-1.5'
            elif edge < 2.0:
                bucket = '1.5-2.0'
            else:
                bucket = '2.0+'

            buckets[bucket].append(bet)

        bucket_metrics = {}
        for bucket_name, bucket_bets in buckets.items():
            if not bucket_bets:
                continue

            wins = sum(1 for b in bucket_bets if b['won'])
            hit_rate = wins / len(bucket_bets) * 100

            bucket_metrics[bucket_name] = {
                'bets': len(bucket_bets),
                'wins': wins,
                'hit_rate': round(hit_rate, 2),
                'edge_vs_breakeven': round(hit_rate - BREAKEVEN_HIT_RATE, 2)
            }

            logger.info(f"\nEdge {bucket_name} K:")
            logger.info(f"  Bets: {len(bucket_bets)}")
            logger.info(f"  Hit Rate: {hit_rate:.1f}%")
            logger.info(f"  vs Breakeven: {hit_rate - BREAKEVEN_HIT_RATE:+.1f}%")

        return bucket_metrics

    def analyze_by_confidence(self, bets: List[Dict]) -> Dict[str, Any]:
        """Analyze hit rate by confidence tier."""
        logger.info("\n" + "="*80)
        logger.info("HIT RATE BY CONFIDENCE TIER")
        logger.info("="*80)

        tiers = {
            '85%+': [],
            '75-85%': [],
            '65-75%': [],
            '<65%': []
        }

        for bet in bets:
            conf = bet['confidence']
            if conf >= 0.85:
                tier = '85%+'
            elif conf >= 0.75:
                tier = '75-85%'
            elif conf >= 0.65:
                tier = '65-75%'
            else:
                tier = '<65%'

            tiers[tier].append(bet)

        tier_metrics = {}
        for tier_name, tier_bets in tiers.items():
            if not tier_bets:
                continue

            wins = sum(1 for b in tier_bets if b['won'])
            hit_rate = wins / len(tier_bets) * 100

            tier_metrics[tier_name] = {
                'bets': len(tier_bets),
                'wins': wins,
                'hit_rate': round(hit_rate, 2),
                'avg_confidence': round(np.mean([b['confidence'] for b in tier_bets]), 3)
            }

            logger.info(f"\n{tier_name}:")
            logger.info(f"  Bets: {len(tier_bets)}")
            logger.info(f"  Hit Rate: {hit_rate:.1f}%")
            logger.info(f"  Avg Confidence: {tier_metrics[tier_name]['avg_confidence']}")

        return tier_metrics

    def analyze_by_context(self, bets: List[Dict]) -> Dict[str, Any]:
        """Analyze hit rate by context (home/away, season)."""
        logger.info("\n" + "="*80)
        logger.info("HIT RATE BY CONTEXT")
        logger.info("="*80)

        # Home vs Away
        home_bets = [b for b in bets if b['is_home']]
        away_bets = [b for b in bets if not b['is_home']]

        home_wins = sum(1 for b in home_bets if b['won'])
        away_wins = sum(1 for b in away_bets if b['won'])

        home_hit_rate = home_wins / len(home_bets) * 100 if home_bets else 0
        away_hit_rate = away_wins / len(away_bets) * 100 if away_bets else 0

        logger.info(f"\nHome Games:")
        logger.info(f"  Bets: {len(home_bets)}")
        logger.info(f"  Hit Rate: {home_hit_rate:.1f}%")

        logger.info(f"\nAway Games:")
        logger.info(f"  Bets: {len(away_bets)}")
        logger.info(f"  Hit Rate: {away_hit_rate:.1f}%")

        # By season
        season_data = defaultdict(list)
        for bet in bets:
            year = bet['game_date'].year
            season_data[year].append(bet)

        logger.info(f"\nBy Season:")
        season_metrics = {}
        for year in sorted(season_data.keys()):
            season_bets = season_data[year]
            season_wins = sum(1 for b in season_bets if b['won'])
            season_hit_rate = season_wins / len(season_bets) * 100

            season_metrics[str(year)] = {
                'bets': len(season_bets),
                'wins': season_wins,
                'hit_rate': round(season_hit_rate, 2)
            }
            logger.info(f"  {year}: {len(season_bets)} bets, {season_hit_rate:.1f}% hit rate")

        return {
            'home_away': {
                'home_bets': len(home_bets),
                'home_wins': home_wins,
                'home_hit_rate': round(home_hit_rate, 2),
                'away_bets': len(away_bets),
                'away_wins': away_wins,
                'away_hit_rate': round(away_hit_rate, 2)
            },
            'by_season': season_metrics
        }

    def generate_verdict(self, simple_metrics: Dict, adjusted_metrics: Dict) -> Dict[str, Any]:
        """Generate overall verdict on synthetic hit rate."""
        logger.info("\n" + "="*80)
        logger.info("SYNTHETIC HIT RATE VERDICT")
        logger.info("="*80)

        # Use simple method for primary verdict
        hit_rate = simple_metrics.get('hit_rate', 0)
        edge_vs_breakeven = simple_metrics.get('edge_vs_breakeven', 0)

        # Determine verdict
        if hit_rate >= 54.0:
            verdict = "PROMISING"
            recommendation = "Model shows strong value detection. Proceed with forward validation."
            confidence_level = "MEDIUM-HIGH"
        elif hit_rate >= 52.0:
            verdict = "MARGINAL"
            recommendation = "Model shows some value. Forward validation required with caution."
            confidence_level = "MEDIUM"
        elif hit_rate >= 50.0:
            verdict = "WEAK"
            recommendation = "Minimal value detected. Consider model improvements before forward validation."
            confidence_level = "LOW"
        else:
            verdict = "POOR"
            recommendation = "No value detected. Do not proceed without model retraining."
            confidence_level = "VERY LOW"

        # Caveats
        caveats = [
            "Synthetic lines may differ significantly from real betting lines",
            "Real markets incorporate information not in our features",
            "This is a directional indicator, not a profitability guarantee",
            "Forward validation with real lines is essential"
        ]

        result = {
            'verdict': verdict,
            'recommendation': recommendation,
            'confidence_level': confidence_level,
            'hit_rate': hit_rate,
            'edge_vs_breakeven': edge_vs_breakeven,
            'caveats': caveats
        }

        logger.info(f"\nVerdict: {verdict}")
        logger.info(f"Hit Rate: {hit_rate}%")
        logger.info(f"vs Breakeven: {edge_vs_breakeven:+.2f}%")
        logger.info(f"\nRecommendation: {recommendation}")
        logger.info(f"Confidence Level: {confidence_level}")

        return result

    def generate_markdown_report(self, results: Dict) -> str:
        """Generate markdown report."""
        report = f"""# MLB Strikeout Predictions - Synthetic Hit Rate Analysis

**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Analysis Type**: Layer 2 - Synthetic Betting Performance
**Data Period**: 2024-04-09 to 2025-09-28
**Methodology**: Rolling average synthetic betting lines

---

## Executive Summary

**Verdict**: {results['verdict']['verdict']}
**Recommendation**: {results['verdict']['recommendation']}

### Key Metrics (Simple Method)
- **Total Bets**: {results['simple_method']['overall']['total_bets']:,}
- **Hit Rate**: {results['simple_method']['overall']['hit_rate']}%
- **vs Breakeven (52.4%)**: {results['simple_method']['overall']['edge_vs_breakeven']:+.2f}%
- **Avg Edge**: {results['simple_method']['overall']['avg_edge']} K

---

## Methodology

### Synthetic Betting Lines

**Method A - Simple (Primary)**:
- Synthetic Line = Pitcher's 10-game rolling average strikeouts
- Bet when |predicted - synthetic_line| > 0.5 K
- OVER when predicted > line, UNDER when predicted < line

**Method B - Context Adjusted**:
- Adjusts rolling average for home/away context
- Home: +5% boost, Away: -5% penalty
- Otherwise same as Method A

### Important Caveats

"""
        for caveat in results['verdict']['caveats']:
            report += f"- {caveat}\n"

        report += f"""

---

## Results: Simple Method (Primary)

### Overall Hit Rate

| Metric | Value |
|--------|-------|
| Total Bets | {results['simple_method']['overall']['total_bets']:,} |
| Wins | {results['simple_method']['overall']['wins']:,} |
| Losses | {results['simple_method']['overall']['losses']:,} |
| Hit Rate | {results['simple_method']['overall']['hit_rate']}% |
| vs Breakeven | {results['simple_method']['overall']['edge_vs_breakeven']:+.2f}% |

### By Recommendation Type

| Type | Bets | Wins | Hit Rate |
|------|------|------|----------|
| OVER | {results['simple_method']['overall']['over_bets']:,} | {results['simple_method']['overall']['over_wins']:,} | {results['simple_method']['overall']['over_hit_rate']}% |
| UNDER | {results['simple_method']['overall']['under_bets']:,} | {results['simple_method']['overall']['under_wins']:,} | {results['simple_method']['overall']['under_hit_rate']}% |

### Edge Analysis

| Metric | Value |
|--------|-------|
| Avg Edge (All Bets) | {results['simple_method']['overall']['avg_edge']} K |
| Avg Edge (Wins) | {results['simple_method']['overall']['avg_edge_wins']} K |
| Avg Edge (Losses) | {results['simple_method']['overall']['avg_edge_losses']} K |

**Interpretation**: {"Wins have higher edge ✅" if results['simple_method']['overall']['avg_edge_wins'] > results['simple_method']['overall']['avg_edge_losses'] else "Losses have higher edge ⚠️"}

---

## Hit Rate by Edge Size

"""
        if 'by_edge_size' in results['simple_method']:
            report += "| Edge Size (K) | Bets | Hit Rate | vs Breakeven |\n"
            report += "|---------------|------|----------|-------------|\n"
            for bucket_name in ['0.5-1.0', '1.0-1.5', '1.5-2.0', '2.0+']:
                bucket = results['simple_method']['by_edge_size'].get(bucket_name)
                if bucket:
                    report += f"| {bucket_name} | {bucket['bets']:,} | {bucket['hit_rate']}% | {bucket['edge_vs_breakeven']:+.2f}% |\n"

        report += """

**Interpretation**: Hit rate should generally increase with edge size. If not, model may not be well calibrated for betting.

---

## Hit Rate by Confidence Tier

"""
        if 'by_confidence' in results['simple_method']:
            report += "| Confidence Tier | Bets | Hit Rate | Avg Confidence |\n"
            report += "|-----------------|------|----------|----------------|\n"
            for tier_name in ['85%+', '75-85%', '65-75%', '<65%']:
                tier = results['simple_method']['by_confidence'].get(tier_name)
                if tier:
                    report += f"| {tier_name} | {tier['bets']:,} | {tier['hit_rate']}% | {tier['avg_confidence']} |\n"

        report += """

---

## Hit Rate by Context

### Home vs Away

"""
        ha = results['simple_method']['context']['home_away']
        report += f"- **Home Games**: {ha['home_bets']:,} bets, {ha['home_hit_rate']}% hit rate\n"
        report += f"- **Away Games**: {ha['away_bets']:,} bets, {ha['away_hit_rate']}% hit rate\n\n"

        report += "### By Season\n\n"
        for year, metrics in results['simple_method']['context']['by_season'].items():
            report += f"- **{year}**: {metrics['bets']:,} bets, {metrics['hit_rate']}% hit rate\n"

        # Adjusted method comparison
        report += f"""

---

## Comparison: Simple vs Adjusted Method

| Method | Hit Rate | Bets | Edge vs Breakeven |
|--------|----------|------|-------------------|
| Simple (10-game avg) | {results['simple_method']['overall']['hit_rate']}% | {results['simple_method']['overall']['total_bets']:,} | {results['simple_method']['overall']['edge_vs_breakeven']:+.2f}% |
| Adjusted (home/away) | {results['adjusted_method']['overall']['hit_rate']}% | {results['adjusted_method']['overall']['total_bets']:,} | {results['adjusted_method']['overall']['edge_vs_breakeven']:+.2f}% |

**Recommendation**: Use {results['verdict'].get('best_method', 'simple')} method for forward validation.

---

## Overall Verdict

**Assessment**: {results['verdict']['verdict']}

**Hit Rate**: {results['verdict']['hit_rate']}%

**Edge vs Breakeven**: {results['verdict']['edge_vs_breakeven']:+.2f}%

**Confidence Level**: {results['verdict']['confidence_level']}

### Recommendation

{results['verdict']['recommendation']}

### Next Steps

"""
        if results['verdict']['verdict'] == 'PROMISING':
            report += """1. ✅ HIGH PRIORITY: Implement forward validation pipeline
2. ✅ Start collecting real betting lines daily
3. ✅ Run predictions with real lines
4. ✅ Build 50+ prediction track record
5. ✅ Compare real hit rate to synthetic estimates
6. ✅ Deploy to production if real hit rate validates
"""
        elif results['verdict']['verdict'] == 'MARGINAL':
            report += """1. ⚠️ Proceed cautiously with forward validation
2. ⚠️ Collect real betting lines daily
3. ⚠️ Start with small sample (20-30 predictions)
4. ⚠️ Monitor closely vs synthetic estimates
5. ⚠️ Consider model improvements in parallel
6. ⚠️ Make go/no-go decision after 50 predictions
"""
        elif results['verdict']['verdict'] == 'WEAK':
            report += """1. ⚠️ Consider model improvements before forward validation
2. ⚠️ If proceeding: start with very small sample (10-15 predictions)
3. ⚠️ Investigate why hit rate is low (feature engineering? calibration?)
4. ⚠️ Parallel path: retrain model with focus on betting value
5. ⚠️ Only scale up if real performance exceeds synthetic
"""
        else:
            report += """1. ❌ DO NOT proceed with forward validation yet
2. ❌ Model not detecting betting value
3. ❌ Investigate root causes (features? training data? market inefficiency?)
4. ❌ Retrain model with focus on identifying edges
5. ❌ Re-run synthetic analysis on improved model
6. ❌ Only proceed when hit rate > 50%
"""

        report += """

---

## Limitations & Disclaimers

### Why Synthetic Lines May Differ from Real Lines

1. **Information Asymmetry**: Real betting lines incorporate sharp bettor action, injury news, weather, and other factors not in our model
2. **Market Efficiency**: Professional bookmakers are sophisticated - they may price lines better than simple rolling averages
3. **Sample Bias**: We only bet when we see edge - real markets may not offer edge on these same games
4. **Vig/Juice**: Real betting has -110 odds (52.4% breakeven), synthetic analysis doesn't model this perfectly
5. **Line Movement**: Real lines move based on betting action - we're using static synthetic lines

### Confidence in Results

"""
        confidence = results['verdict']['confidence_level']
        if confidence in ['HIGH', 'MEDIUM-HIGH']:
            report += "✅ Synthetic hit rate is strong enough that even with real-world inefficiencies, model likely profitable\n"
        elif confidence == 'MEDIUM':
            report += "⚠️ Synthetic hit rate is marginal - real-world performance could go either way\n"
        else:
            report += "❌ Synthetic hit rate too low - unlikely to be profitable with real betting lines\n"

        report += """

**Forward validation with real betting lines is ESSENTIAL before any production deployment.**

---

**Analysis Script**: `scripts/mlb/historical_odds_backfill/analyze_synthetic_hit_rate.py`
**Data Sources**:
- Predictions: `mlb_predictions.pitcher_strikeouts`
- Synthetic Lines: `mlb_analytics.pitcher_game_summary` (k_avg_last_10)
- Actuals: `mlb_analytics.pitcher_game_summary` (actual_strikeouts)
"""
        return report

    def run_analysis(self) -> Dict:
        """Run complete synthetic hit rate analysis."""
        logger.info("="*80)
        logger.info("MLB SYNTHETIC HIT RATE ANALYSIS")
        logger.info("="*80)

        # Get data
        data = self.get_predictions_with_synthetic_lines()

        if not data:
            logger.error("No predictions with synthetic lines found!")
            return {}

        # Calculate bets for both methods
        simple_bets = self.calculate_bets_and_outcomes(data, line_method='simple')
        adjusted_bets = self.calculate_bets_and_outcomes(data, line_method='adjusted')

        if not simple_bets:
            logger.error("No bets generated!")
            return {}

        # Analyze simple method (primary)
        logger.info("\n" + "#"*80)
        logger.info("ANALYZING SIMPLE METHOD (PRIMARY)")
        logger.info("#"*80)

        simple_overall = self.calculate_hit_rate_metrics(simple_bets, 'Simple Method')
        simple_edge = self.analyze_by_edge_size(simple_bets)
        simple_confidence = self.analyze_by_confidence(simple_bets)
        simple_context = self.analyze_by_context(simple_bets)

        # Analyze adjusted method (comparison)
        logger.info("\n" + "#"*80)
        logger.info("ANALYZING ADJUSTED METHOD (COMPARISON)")
        logger.info("#"*80)

        adjusted_overall = self.calculate_hit_rate_metrics(adjusted_bets, 'Adjusted Method')
        adjusted_context = self.analyze_by_context(adjusted_bets)

        # Generate verdict
        verdict = self.generate_verdict(simple_overall, adjusted_overall)

        # Determine best method
        if adjusted_overall.get('hit_rate', 0) > simple_overall.get('hit_rate', 0) + 1.0:
            verdict['best_method'] = 'adjusted'
        else:
            verdict['best_method'] = 'simple'

        # Compile results
        results = {
            'simple_method': {
                'overall': simple_overall,
                'by_edge_size': simple_edge,
                'by_confidence': simple_confidence,
                'context': simple_context
            },
            'adjusted_method': {
                'overall': adjusted_overall,
                'context': adjusted_context
            },
            'verdict': verdict,
            'analysis_date': datetime.now().isoformat(),
            'total_predictions': len(data),
            'edge_threshold': EDGE_THRESHOLD,
            'breakeven_hit_rate': BREAKEVEN_HIT_RATE
        }

        # Generate report
        report = self.generate_markdown_report(results)

        # Save outputs
        output_dir = 'docs/08-projects/current/mlb-pitcher-strikeouts'
        os.makedirs(output_dir, exist_ok=True)

        # Save markdown
        md_path = os.path.join(output_dir, 'SYNTHETIC-HIT-RATE-REPORT.md')
        with open(md_path, 'w') as f:
            f.write(report)
        logger.info(f"\n✅ Report saved to: {md_path}")

        # Save JSON
        json_path = os.path.join(output_dir, 'synthetic-hit-rate-results.json')
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"✅ Results saved to: {json_path}")

        return results


def main():
    """Main entry point."""
    try:
        analyzer = SyntheticHitRateAnalyzer()
        results = analyzer.run_analysis()

        if not results:
            logger.error("Analysis failed")
            sys.exit(1)

        # Exit code based on verdict
        verdict = results.get('verdict', {}).get('verdict', 'UNKNOWN')
        if verdict == 'PROMISING':
            sys.exit(0)
        elif verdict == 'MARGINAL':
            sys.exit(1)
        elif verdict == 'WEAK':
            sys.exit(2)
        else:
            sys.exit(3)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(4)


if __name__ == '__main__':
    main()
