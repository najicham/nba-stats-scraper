#!/usr/bin/env python3
"""
Compare Results Across Experiments

Reads all experiment results from the results/ directory and displays
a comparison table to help decide which model performs best.

Usage:
    PYTHONPATH=. python ml/experiments/compare_results.py

    # Filter by experiment prefix
    PYTHONPATH=. python ml/experiments/compare_results.py --filter A

    # Export to CSV
    PYTHONPATH=. python ml/experiments/compare_results.py --csv results_comparison.csv
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json
from datetime import datetime

RESULTS_DIR = Path(__file__).parent / "results"

# Thresholds for highlighting
BREAKEVEN_HIT_RATE = 52.4  # Standard -110 odds
GOOD_HIT_RATE = 55.0
EXCELLENT_HIT_RATE = 60.0


def load_results() -> list[dict]:
    """Load all experiment results from JSON files"""
    results = []
    for path in RESULTS_DIR.glob("*_results.json"):
        try:
            with open(path) as f:
                data = json.load(f)
                data['_file'] = path.name
                results.append(data)
        except Exception as e:
            print(f"Warning: Could not load {path}: {e}")
    return results


def format_table(results: list[dict], filter_prefix: str = None) -> str:
    """Format results as a comparison table"""
    if filter_prefix:
        results = [r for r in results if r.get('experiment_id', '').startswith(filter_prefix)]

    if not results:
        return "No results found."

    # Sort by experiment ID
    results = sorted(results, key=lambda x: x.get('experiment_id', ''))

    lines = []
    lines.append("=" * 110)
    lines.append(" EXPERIMENT COMPARISON")
    lines.append("=" * 110)
    lines.append("")

    # Header
    header = f"{'Exp':<8} {'Train Period':<23} {'Eval Period':<23} {'Samples':>8} {'MAE':>7} {'Hit%':>7} {'ROI%':>7} {'Bets':>6}"
    lines.append(header)
    lines.append("-" * 110)

    for r in results:
        exp_id = r.get('experiment_id', 'unknown')

        # Training period
        train = r.get('train_period', {})
        train_str = f"{train.get('start', '?')[:10]} - {train.get('end', '?')[:10]}"

        # Eval period
        eval_p = r.get('eval_period', {})
        eval_str = f"{eval_p.get('start', '?')[:10]} - {eval_p.get('end', '?')[:10]}"
        samples = eval_p.get('samples', 0)

        # Results
        res = r.get('results', {})
        mae = res.get('mae', 0)

        betting = res.get('betting', {})
        hit_rate = betting.get('hit_rate_pct')
        roi = betting.get('roi_pct')
        bets = betting.get('bets_graded', 0)

        # Format with indicators
        hit_str = f"{hit_rate:.1f}" if hit_rate else "N/A"
        if hit_rate:
            if hit_rate >= EXCELLENT_HIT_RATE:
                hit_str += " **"
            elif hit_rate >= GOOD_HIT_RATE:
                hit_str += " *"
            elif hit_rate < BREAKEVEN_HIT_RATE:
                hit_str += " !"

        roi_str = f"{roi:.1f}" if roi else "N/A"
        if roi and roi > 0:
            roi_str = f"+{roi:.1f}"

        line = f"{exp_id:<8} {train_str:<23} {eval_str:<23} {samples:>8,} {mae:>7.3f} {hit_str:>7} {roi_str:>7} {bets:>6,}"
        lines.append(line)

    lines.append("-" * 110)
    lines.append("")
    lines.append("Legend: ** = excellent (60%+), * = good (55%+), ! = below breakeven (52.4%)")
    lines.append("")

    # Best performers
    valid_results = [r for r in results if r.get('results', {}).get('betting', {}).get('hit_rate_pct')]
    if valid_results:
        best_hit = max(valid_results, key=lambda x: x['results']['betting']['hit_rate_pct'])
        best_mae = min(valid_results, key=lambda x: x['results']['mae'])

        lines.append("Best Performers:")
        lines.append(f"  Highest Hit Rate: {best_hit['experiment_id']} ({best_hit['results']['betting']['hit_rate_pct']:.1f}%)")
        lines.append(f"  Lowest MAE:       {best_mae['experiment_id']} ({best_mae['results']['mae']:.3f})")

    return "\n".join(lines)


def export_csv(results: list[dict], output_path: str):
    """Export results to CSV"""
    import csv

    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'experiment_id', 'train_start', 'train_end', 'train_samples',
            'eval_start', 'eval_end', 'eval_samples',
            'mae', 'hit_rate_pct', 'roi_pct', 'hits', 'misses', 'bets_graded',
            'evaluated_at'
        ])

        for r in sorted(results, key=lambda x: x.get('experiment_id', '')):
            train = r.get('train_period', {})
            eval_p = r.get('eval_period', {})
            res = r.get('results', {})
            betting = res.get('betting', {})

            writer.writerow([
                r.get('experiment_id', ''),
                train.get('start', ''),
                train.get('end', ''),
                train.get('samples', ''),
                eval_p.get('start', ''),
                eval_p.get('end', ''),
                eval_p.get('samples', ''),
                res.get('mae', ''),
                betting.get('hit_rate_pct', ''),
                betting.get('roi_pct', ''),
                betting.get('hits', ''),
                betting.get('misses', ''),
                betting.get('bets_graded', ''),
                r.get('evaluated_at', ''),
            ])

    print(f"Exported to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Compare experiment results")
    parser.add_argument("--filter", help="Filter experiments by ID prefix (e.g., 'A' for A1, A2, A3)")
    parser.add_argument("--csv", help="Export results to CSV file")
    parser.add_argument("--json", help="Export results to JSON file")
    args = parser.parse_args()

    results = load_results()

    if not results:
        print("No experiment results found in", RESULTS_DIR)
        print("\nRun experiments with:")
        print("  PYTHONPATH=. python ml/experiments/run_experiment.py --help")
        return 1

    # Display comparison table
    print(format_table(results, args.filter))

    # Export if requested
    if args.csv:
        export_csv(results, args.csv)

    if args.json:
        with open(args.json, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Exported to {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
