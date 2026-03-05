#!/usr/bin/env python3
"""Prediction correlation analysis — find redundant models in the fleet.

Computes pairwise Pearson correlation between model predictions to identify
models that are near-identical (r > 0.95) vs genuinely diverse.

Usage:
    PYTHONPATH=. .venv/bin/python bin/analysis/model_correlation.py --days 14
    PYTHONPATH=. .venv/bin/python bin/analysis/model_correlation.py --days 14 --csv results/model_corr.csv
"""

import argparse
import csv
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

# ANSI colors
GREEN = '\033[32m'
RED = '\033[31m'
YELLOW = '\033[33m'
RESET = '\033[0m'


def color_corr(r):
    """Color correlation by redundancy risk."""
    if r >= 0.95:
        return f'{RED}{r:.4f}{RESET}'
    if r >= 0.90:
        return f'{YELLOW}{r:.4f}{RESET}'
    return f'{GREEN}{r:.4f}{RESET}'


def run_analysis(days: int, csv_path: str = None):
    from google.cloud import bigquery
    import numpy as np

    client = bigquery.Client(project='nba-props-platform')

    # Get recent predictions from all active models
    query = f"""
    SELECT
      player_lookup,
      game_date,
      system_id,
      predicted_points
    FROM `nba-props-platform.nba_predictions.player_prop_predictions`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
      AND is_active = TRUE
    ORDER BY game_date, player_lookup, system_id
    """

    print(f"Querying predictions from last {days} days...", flush=True)
    rows = list(client.query(query).result())
    print(f"  {len(rows)} prediction rows")

    if not rows:
        print("No data found.")
        return

    # Build player-date key → model → prediction pivot
    from collections import defaultdict
    pivot = defaultdict(dict)
    models = set()

    for r in rows:
        key = (r.player_lookup, str(r.game_date))
        pivot[key][r.system_id] = float(r.predicted_points)
        models.add(r.system_id)

    models = sorted(models)
    print(f"  {len(models)} models, {len(pivot)} player-date pairs\n")

    if len(models) < 2:
        print("Need at least 2 models for correlation analysis.")
        return

    # Build aligned arrays for each model pair
    n_models = len(models)
    corr_matrix = np.full((n_models, n_models), np.nan)
    overlap_matrix = np.zeros((n_models, n_models), dtype=int)

    for i in range(n_models):
        for j in range(i, n_models):
            m_i, m_j = models[i], models[j]

            # Find overlapping player-dates
            vals_i, vals_j = [], []
            for key, preds in pivot.items():
                if m_i in preds and m_j in preds:
                    vals_i.append(preds[m_i])
                    vals_j.append(preds[m_j])

            overlap = len(vals_i)
            overlap_matrix[i][j] = overlap
            overlap_matrix[j][i] = overlap

            if overlap < 10:
                continue

            arr_i = np.array(vals_i)
            arr_j = np.array(vals_j)

            r = np.corrcoef(arr_i, arr_j)[0, 1]
            corr_matrix[i][j] = r
            corr_matrix[j][i] = r

    # Print full correlation matrix
    print("=" * 80)
    print("  PAIRWISE CORRELATION MATRIX")
    print("=" * 80)

    # Truncate model names for display
    short_names = []
    for m in models:
        s = m.replace('catboost_', 'cb_').replace('xgboost_', 'xgb_').replace('lightgbm_', 'lgbm_')
        short_names.append(s[:25])

    # Header
    print(f"{'':>28}", end='')
    for j, name in enumerate(short_names):
        print(f" {j:>3}", end='')
    print()

    for i, name in enumerate(short_names):
        print(f"[{i:>2}] {name:>23}", end='')
        for j in range(n_models):
            r = corr_matrix[i][j]
            if i == j:
                print(f"   -", end='')
            elif np.isnan(r):
                print(f"   .", end='')
            else:
                if r >= 0.95:
                    print(f" {RED}{r:.2f}{RESET}", end='')
                elif r >= 0.90:
                    print(f" {YELLOW}{r:.2f}{RESET}", end='')
                else:
                    print(f" {r:.2f}", end='')
        print()

    # Print sorted pairs
    print(f"\n{'='*80}")
    print("  MODEL PAIRS BY CORRELATION (highest first)")
    print(f"{'='*80}")
    print(f"{'Model A':>30} | {'Model B':>30} | {'Corr':>8} | {'Overlap':>7} | {'Flag':>10}")
    print('-' * 95)

    pairs = []
    for i in range(n_models):
        for j in range(i + 1, n_models):
            r = corr_matrix[i][j]
            if np.isnan(r):
                continue
            pairs.append((models[i], models[j], r, overlap_matrix[i][j]))

    pairs.sort(key=lambda x: -x[2])

    for m_a, m_b, r, overlap in pairs:
        flag = ''
        if r >= 0.95:
            flag = f'{RED}REDUNDANT{RESET}'
        elif r >= 0.90:
            flag = f'{YELLOW}SIMILAR{RESET}'
        elif r < 0.70:
            flag = f'{GREEN}DIVERSE{RESET}'

        # Truncate names
        a = m_a[:30]
        b = m_b[:30]
        print(f"{a:>30} | {b:>30} | {color_corr(r):>17} | {overlap:>7} | {flag}")

    # Summary
    redundant = [(a, b, r) for a, b, r, _ in pairs if r >= 0.95]
    diverse = [(a, b, r) for a, b, r, _ in pairs if r < 0.70]
    print(f"\nSummary: {len(redundant)} redundant pairs (r>=0.95), "
          f"{len(diverse)} diverse pairs (r<0.70)")
    if redundant:
        print("\nRedundant pairs — consider decommissioning one from each:")
        for a, b, r in redundant:
            print(f"  {a} <-> {b} (r={r:.4f})")

    # CSV export
    if csv_path:
        csv_rows = [{'model_a': a, 'model_b': b, 'correlation': round(r, 5),
                      'overlap': o} for a, b, r, o in pairs]
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['model_a', 'model_b',
                                                    'correlation', 'overlap'])
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"\nCSV written to {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Model prediction correlation analysis — identify redundant models',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--days', type=int, default=14,
                        help='Look back N days (default: 14)')
    parser.add_argument('--csv', default=None, help='Export results to CSV')

    args = parser.parse_args()
    run_analysis(args.days, args.csv)


if __name__ == '__main__':
    main()
