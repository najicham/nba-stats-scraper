#!/usr/bin/env python3
"""
MLB Prediction Raw Accuracy Analysis

Analyzes prediction accuracy WITHOUT betting lines.
Measures fundamental model quality independent of betting context.

This is Layer 1 of our hit rate measurement framework.

Usage:
    python scripts/mlb/historical_odds_backfill/analyze_raw_accuracy.py

Outputs:
    - docs/08-projects/current/mlb-pitcher-strikeouts/RAW-ACCURACY-REPORT.md
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


class RawAccuracyAnalyzer:
    """Analyze prediction accuracy without betting context."""

    def __init__(self):
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.results = {}

    def get_predictions_with_actuals(self) -> List[Dict[str, Any]]:
        """Get all predictions matched with actual results."""
        query = """
        SELECT
            p.game_date,
            p.pitcher_lookup,
            p.pitcher_name,
            p.team_abbr,
            p.opponent_team_abbr,
            p.is_home,
            p.predicted_strikeouts,
            p.confidence,
            p.model_version,

            -- Actual results
            a.strikeouts as actual_strikeouts,
            a.innings_pitched as actual_innings_pitched,

            -- Calculate error
            ABS(p.predicted_strikeouts - a.strikeouts) as absolute_error,
            p.predicted_strikeouts - a.strikeouts as signed_error

        FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts` p
        INNER JOIN `nba-props-platform.mlb_raw.mlb_pitcher_stats` a
          ON p.pitcher_lookup = a.player_lookup
          AND p.game_date = a.game_date
          AND a.is_starter = TRUE
        WHERE p.game_date >= '2024-04-01' AND p.game_date <= '2025-10-01'
        ORDER BY p.game_date, p.pitcher_lookup
        """

        logger.info("Fetching predictions with actuals...")
        results = self.bq_client.query(query).result()
        data = [dict(row) for row in results]
        logger.info(f"Found {len(data)} predictions with actual results")

        return data

    def calculate_overall_metrics(self, data: List[Dict]) -> Dict[str, float]:
        """Calculate overall accuracy metrics."""
        logger.info("\n" + "="*80)
        logger.info("OVERALL ACCURACY METRICS")
        logger.info("="*80)

        errors = [row['absolute_error'] for row in data]
        signed_errors = [row['signed_error'] for row in data]
        predicted = [row['predicted_strikeouts'] for row in data]
        actual = [row['actual_strikeouts'] for row in data]

        mae = np.mean(errors)
        mae_std = np.std(errors)
        rmse = np.sqrt(np.mean([e**2 for e in signed_errors]))
        bias = np.mean(signed_errors)

        # Directional accuracy
        directional_correct = sum(
            1 for i in range(len(data))
            if (predicted[i] > 5.0 and actual[i] > 5.0) or
               (predicted[i] < 5.0 and actual[i] < 5.0)
        )
        directional_accuracy = directional_correct / len(data) * 100

        # Within-K metrics
        within_1k = sum(1 for e in errors if e <= 1.0) / len(errors) * 100
        within_2k = sum(1 for e in errors if e <= 2.0) / len(errors) * 100
        within_3k = sum(1 for e in errors if e <= 3.0) / len(errors) * 100

        metrics = {
            'total_predictions': len(data),
            'mae': round(mae, 3),
            'mae_std': round(mae_std, 3),
            'rmse': round(rmse, 3),
            'bias': round(bias, 3),
            'directional_accuracy_pct': round(directional_accuracy, 1),
            'within_1k_pct': round(within_1k, 1),
            'within_2k_pct': round(within_2k, 1),
            'within_3k_pct': round(within_3k, 1),
            'avg_predicted': round(np.mean(predicted), 2),
            'avg_actual': round(np.mean(actual), 2),
        }

        logger.info(f"\nTotal Predictions: {metrics['total_predictions']}")
        logger.info(f"MAE: {metrics['mae']} ± {metrics['mae_std']}")
        logger.info(f"RMSE: {metrics['rmse']}")
        logger.info(f"Bias: {metrics['bias']} ({'over' if bias > 0 else 'under'}-predicting)")
        logger.info(f"Directional Accuracy: {metrics['directional_accuracy_pct']}%")
        logger.info(f"\nWithin 1K: {metrics['within_1k_pct']}%")
        logger.info(f"Within 2K: {metrics['within_2k_pct']}%")
        logger.info(f"Within 3K: {metrics['within_3k_pct']}%")
        logger.info(f"\nAvg Predicted: {metrics['avg_predicted']}")
        logger.info(f"Avg Actual: {metrics['avg_actual']}")

        return metrics

    def analyze_by_confidence(self, data: List[Dict]) -> Dict[str, Any]:
        """Analyze accuracy by confidence tier."""
        logger.info("\n" + "="*80)
        logger.info("ACCURACY BY CONFIDENCE TIER")
        logger.info("="*80)

        tiers = {
            '85%+': [],
            '75-85%': [],
            '65-75%': [],
            '<65%': []
        }

        for row in data:
            conf = row['confidence']
            if conf >= 0.85:
                tier = '85%+'
            elif conf >= 0.75:
                tier = '75-85%'
            elif conf >= 0.65:
                tier = '65-75%'
            else:
                tier = '<65%'

            tiers[tier].append(row)

        tier_metrics = {}
        for tier_name, tier_data in tiers.items():
            if not tier_data:
                continue

            errors = [row['absolute_error'] for row in tier_data]
            mae = np.mean(errors)
            mae_std = np.std(errors) if len(errors) > 1 else 0

            tier_metrics[tier_name] = {
                'predictions': len(tier_data),
                'mae': round(mae, 3),
                'mae_std': round(mae_std, 3),
                'avg_confidence': round(np.mean([r['confidence'] for r in tier_data]), 3)
            }

            logger.info(f"\n{tier_name}:")
            logger.info(f"  Predictions: {tier_metrics[tier_name]['predictions']}")
            logger.info(f"  MAE: {tier_metrics[tier_name]['mae']} ± {tier_metrics[tier_name]['mae_std']}")
            logger.info(f"  Avg Confidence: {tier_metrics[tier_name]['avg_confidence']}")

        # Check calibration
        logger.info("\n" + "-"*80)
        logger.info("CALIBRATION CHECK")
        logger.info("-"*80)

        is_calibrated = True
        if tier_metrics.get('85%+', {}).get('mae', 999) > tier_metrics.get('75-85%', {}).get('mae', 0):
            logger.info("⚠️  WARNING: High confidence predictions have WORSE MAE than medium confidence")
            logger.info("   This suggests model is NOT well calibrated")
            is_calibrated = False
        else:
            logger.info("✅ High confidence predictions have better MAE (model appears calibrated)")

        return {
            'tier_metrics': tier_metrics,
            'is_calibrated': is_calibrated
        }

    def analyze_by_context(self, data: List[Dict]) -> Dict[str, Any]:
        """Analyze accuracy by game context."""
        logger.info("\n" + "="*80)
        logger.info("ACCURACY BY CONTEXT")
        logger.info("="*80)

        # Home vs Away
        home_data = [r for r in data if r['is_home']]
        away_data = [r for r in data if not r['is_home']]

        home_mae = np.mean([r['absolute_error'] for r in home_data]) if home_data else 0
        away_mae = np.mean([r['absolute_error'] for r in away_data]) if away_data else 0

        logger.info(f"\nHome Games:")
        logger.info(f"  Predictions: {len(home_data)}")
        logger.info(f"  MAE: {round(home_mae, 3)}")

        logger.info(f"\nAway Games:")
        logger.info(f"  Predictions: {len(away_data)}")
        logger.info(f"  MAE: {round(away_mae, 3)}")

        # By season
        season_data = defaultdict(list)
        for row in data:
            year = row['game_date'].year
            season_data[year].append(row)

        logger.info(f"\nBy Season:")
        season_metrics = {}
        for year in sorted(season_data.keys()):
            season_rows = season_data[year]
            mae = np.mean([r['absolute_error'] for r in season_rows])
            season_metrics[str(year)] = {
                'predictions': len(season_rows),
                'mae': round(mae, 3)
            }
            logger.info(f"  {year}: {len(season_rows)} predictions, MAE {round(mae, 3)}")

        return {
            'home_away': {
                'home_predictions': len(home_data),
                'home_mae': round(home_mae, 3),
                'away_predictions': len(away_data),
                'away_mae': round(away_mae, 3)
            },
            'by_season': season_metrics
        }

    def generate_verdict(self, overall_metrics: Dict, confidence_analysis: Dict) -> Dict[str, Any]:
        """Generate overall model verdict."""
        logger.info("\n" + "="*80)
        logger.info("MODEL VERDICT")
        logger.info("="*80)

        mae = overall_metrics['mae']
        bias = overall_metrics['bias']
        is_calibrated = confidence_analysis['is_calibrated']

        # Determine verdict
        if mae < 1.5 and is_calibrated:
            verdict = "EXCELLENT"
            recommendation = "Model ready for betting deployment"
            confidence_level = "HIGH"
        elif mae < 1.8 and is_calibrated:
            verdict = "GOOD"
            recommendation = "Model suitable for betting with forward validation"
            confidence_level = "MEDIUM-HIGH"
        elif mae < 2.0:
            verdict = "MARGINAL"
            recommendation = "Forward validation required before betting deployment"
            confidence_level = "MEDIUM"
        else:
            verdict = "POOR"
            recommendation = "Model needs retraining before betting deployment"
            confidence_level = "LOW"

        # Check for issues
        issues = []
        if abs(bias) > 0.5:
            issues.append(f"Significant bias: {'over' if bias > 0 else 'under'}-predicting by {abs(bias):.2f} K")
        if not is_calibrated:
            issues.append("Model confidence scores not well calibrated")
        if mae > overall_metrics.get('training_mae', 1.71):
            issues.append(f"Production MAE ({mae}) worse than training MAE (1.71)")

        result = {
            'verdict': verdict,
            'recommendation': recommendation,
            'confidence_level': confidence_level,
            'issues': issues if issues else ['None detected']
        }

        logger.info(f"\nVerdict: {verdict}")
        logger.info(f"Recommendation: {recommendation}")
        logger.info(f"Confidence Level: {confidence_level}")
        logger.info(f"\nIssues Detected:")
        for issue in result['issues']:
            logger.info(f"  - {issue}")

        return result

    def generate_markdown_report(self, results: Dict) -> str:
        """Generate markdown report."""
        report = f"""# MLB Strikeout Predictions - Raw Accuracy Analysis

**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Analysis Type**: Layer 1 - Raw Prediction Accuracy
**Data Period**: 2024-04-09 to 2025-09-28

---

## Executive Summary

**Verdict**: {results['verdict']['verdict']}
**Recommendation**: {results['verdict']['recommendation']}

### Key Metrics
- **Total Predictions**: {results['overall']['total_predictions']:,}
- **Mean Absolute Error (MAE)**: {results['overall']['mae']}
- **Prediction Bias**: {results['overall']['bias']:+.3f} K ({'over' if results['overall']['bias'] > 0 else 'under'}-predicting)
- **Within 2K**: {results['overall']['within_2k_pct']}%

---

## Overall Accuracy Metrics

| Metric | Value |
|--------|-------|
| Total Predictions | {results['overall']['total_predictions']:,} |
| MAE | {results['overall']['mae']} ± {results['overall']['mae_std']} |
| RMSE | {results['overall']['rmse']} |
| Bias | {results['overall']['bias']:+.3f} K |
| Directional Accuracy | {results['overall']['directional_accuracy_pct']}% |
| Within 1K | {results['overall']['within_1k_pct']}% |
| Within 2K | {results['overall']['within_2k_pct']}% |
| Within 3K | {results['overall']['within_3k_pct']}% |
| Avg Predicted | {results['overall']['avg_predicted']} K |
| Avg Actual | {results['overall']['avg_actual']} K |

### Interpretation

**MAE Benchmarks**:
- < 1.5: Excellent
- 1.5-2.0: Good
- 2.0-2.5: Marginal
- > 2.5: Poor

**Baseline Comparison**:
- Training MAE: 1.71
- Production MAE: {results['overall']['mae']}
- Delta: {results['overall']['mae'] - 1.71:+.3f}

---

## Accuracy by Confidence Tier

"""
        # Confidence tiers table
        if 'confidence' in results:
            report += "| Confidence Tier | Predictions | MAE | Avg Confidence |\n"
            report += "|-----------------|-------------|-----|----------------|\n"
            for tier_name in ['85%+', '75-85%', '65-75%', '<65%']:
                tier = results['confidence']['tier_metrics'].get(tier_name)
                if tier:
                    report += f"| {tier_name} | {tier['predictions']:,} | {tier['mae']} | {tier['avg_confidence']} |\n"

            report += f"\n**Calibration Status**: {'✅ Calibrated' if results['confidence']['is_calibrated'] else '⚠️ NOT Calibrated'}\n\n"

        # Context analysis
        if 'context' in results:
            report += """---

## Accuracy by Context

### Home vs Away

"""
            ha = results['context']['home_away']
            report += f"- **Home Games**: {ha['home_predictions']:,} predictions, MAE {ha['home_mae']}\n"
            report += f"- **Away Games**: {ha['away_predictions']:,} predictions, MAE {ha['away_mae']}\n\n"

            report += "### By Season\n\n"
            for year, metrics in results['context']['by_season'].items():
                report += f"- **{year}**: {metrics['predictions']:,} predictions, MAE {metrics['mae']}\n"

        # Verdict
        report += f"""

---

## Model Verdict

**Overall Assessment**: {results['verdict']['verdict']}

**Recommendation**: {results['verdict']['recommendation']}

**Confidence Level**: {results['verdict']['confidence_level']}

### Issues Detected

"""
        for issue in results['verdict']['issues']:
            report += f"- {issue}\n"

        report += """

---

## Next Steps

Based on this analysis:

"""
        if results['verdict']['verdict'] in ['EXCELLENT', 'GOOD']:
            report += """1. ✅ Proceed with forward validation
2. ✅ Start collecting betting lines daily
3. ✅ Build 50+ prediction track record
4. ✅ Measure true hit rate with real betting context
5. ✅ Deploy to production after validation
"""
        elif results['verdict']['verdict'] == 'MARGINAL':
            report += """1. ⚠️ Forward validation REQUIRED before betting
2. ⚠️ Start with small sample (10-20 predictions)
3. ⚠️ Monitor performance closely
4. ⚠️ Consider model improvements in parallel
5. ⚠️ Make go/no-go decision after 50 predictions
"""
        else:
            report += """1. ❌ DO NOT deploy for betting yet
2. ❌ Retrain model with focus on identified issues
3. ❌ Re-run this analysis on new model
4. ❌ Only proceed to forward validation after MAE < 2.0
"""

        report += """

---

**Analysis Script**: `scripts/mlb/historical_odds_backfill/analyze_raw_accuracy.py`
**Data Source**: `mlb_predictions.pitcher_strikeouts` × `mlb_raw.mlb_pitcher_stats`
"""
        return report

    def run_analysis(self) -> Dict:
        """Run complete analysis."""
        logger.info("="*80)
        logger.info("MLB RAW ACCURACY ANALYSIS")
        logger.info("="*80)

        # Get data
        data = self.get_predictions_with_actuals()

        if not data:
            logger.error("No predictions with actuals found!")
            return {}

        # Run analyses
        overall_metrics = self.calculate_overall_metrics(data)
        confidence_analysis = self.analyze_by_confidence(data)
        context_analysis = self.analyze_by_context(data)
        verdict = self.generate_verdict(overall_metrics, confidence_analysis)

        # Compile results
        results = {
            'overall': overall_metrics,
            'confidence': confidence_analysis,
            'context': context_analysis,
            'verdict': verdict,
            'analysis_date': datetime.now().isoformat(),
            'data_count': len(data)
        }

        # Generate report
        report = self.generate_markdown_report(results)

        # Save outputs
        output_dir = 'docs/08-projects/current/mlb-pitcher-strikeouts'
        os.makedirs(output_dir, exist_ok=True)

        # Save markdown
        md_path = os.path.join(output_dir, 'RAW-ACCURACY-REPORT.md')
        with open(md_path, 'w') as f:
            f.write(report)
        logger.info(f"\n✅ Report saved to: {md_path}")

        # Save JSON
        json_path = os.path.join(output_dir, 'raw-accuracy-results.json')
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"✅ Results saved to: {json_path}")

        return results


def main():
    """Main entry point."""
    try:
        analyzer = RawAccuracyAnalyzer()
        results = analyzer.run_analysis()

        if not results:
            logger.error("Analysis failed")
            sys.exit(1)

        # Exit code based on verdict
        verdict = results.get('verdict', {}).get('verdict', 'UNKNOWN')
        if verdict == 'EXCELLENT':
            sys.exit(0)
        elif verdict == 'GOOD':
            sys.exit(0)
        elif verdict == 'MARGINAL':
            sys.exit(1)
        else:
            sys.exit(2)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(3)


if __name__ == '__main__':
    main()
