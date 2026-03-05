#!/usr/bin/env python3
"""Edge calibration analysis — HR by edge band, model framework, and direction.

Answers: Does edge actually predict hit rate? Is calibration different for
CatBoost vs XGBoost vs LightGBM? Does OVER vs UNDER calibrate differently?

Usage:
    PYTHONPATH=. .venv/bin/python bin/analysis/edge_calibration.py --start 2026-02-01
    PYTHONPATH=. .venv/bin/python bin/analysis/edge_calibration.py --start 2025-11-01 --csv results/edge_cal.csv
    PYTHONPATH=. .venv/bin/python bin/analysis/edge_calibration.py --start 2026-02-01 --best-bets
"""

import argparse
import csv
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))


EDGE_BANDS = [
    ('0-1', 0, 1),
    ('1-2', 1, 2),
    ('2-3', 2, 3),
    ('3-4', 3, 4),
    ('4-5', 4, 5),
    ('5-7', 5, 7),
    ('7+', 7, 100),
]

# ANSI colors
GREEN = '\033[32m'
RED = '\033[31m'
YELLOW = '\033[33m'
RESET = '\033[0m'


def color_hr(hr, n):
    """Color HR based on profitability threshold."""
    if n < 10:
        return f'{YELLOW}{hr:5.1f}%{RESET}'
    if hr >= 55:
        return f'{GREEN}{hr:5.1f}%{RESET}'
    if hr < 52.4:
        return f'{RED}{hr:5.1f}%{RESET}'
    return f'{hr:5.1f}%'


def classify_framework(system_id: str) -> str:
    """Classify model system_id into framework family."""
    sid = system_id.lower()
    if 'xgb' in sid or 'xgboost' in sid:
        return 'XGBoost'
    if 'lgbm' in sid or 'lightgbm' in sid:
        return 'LightGBM'
    return 'CatBoost'


def run_analysis(start_date: str, end_date: str = None, best_bets: bool = False,
                 csv_path: str = None):
    from google.cloud import bigquery
    client = bigquery.Client(project='nba-props-platform')

    end_filter = f"AND pa.game_date <= '{end_date}'" if end_date else ""

    if best_bets:
        # Join with signal_best_bets_picks to filter to actual best bets
        source_join = """
        JOIN `nba-props-platform.nba_predictions.signal_best_bets_picks` bb
          ON pa.player_lookup = bb.player_lookup
          AND pa.game_date = bb.game_date
          AND pa.system_id = bb.system_id
        """
        source_label = "BEST BETS"
    else:
        source_join = ""
        source_label = "ALL PREDICTIONS"

    query = f"""
    SELECT
      pa.system_id,
      pa.recommendation,
      ABS(pa.predicted_points - pa.line_value) AS edge,
      pa.prediction_correct
    FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
    {source_join}
    WHERE pa.game_date >= '{start_date}'
      {end_filter}
      AND pa.has_prop_line = TRUE
      AND pa.recommendation IN ('OVER', 'UNDER')
      AND pa.prediction_correct IS NOT NULL
    """

    print(f"Querying {source_label} from {start_date}...", flush=True)
    rows = list(client.query(query).result())
    print(f"  {len(rows)} graded predictions\n")

    if not rows:
        print("No data found.")
        return

    # Aggregate by framework × direction × edge_band
    from collections import defaultdict
    agg = defaultdict(lambda: {'wins': 0, 'total': 0})

    for r in rows:
        framework = classify_framework(r.system_id)
        direction = r.recommendation
        edge = float(r.edge) if r.edge is not None else 0

        for label, lo, hi in EDGE_BANDS:
            if lo <= edge < hi:
                edge_band = label
                break
        else:
            edge_band = '7+'

        agg[(framework, direction, edge_band)]['total'] += 1
        if r.prediction_correct:
            agg[(framework, direction, edge_band)]['wins'] += 1

        # Also aggregate "ALL" framework
        agg[('ALL', direction, edge_band)]['total'] += 1
        if r.prediction_correct:
            agg[('ALL', direction, edge_band)]['wins'] += 1

        # And "BOTH" direction
        agg[(framework, 'BOTH', edge_band)]['total'] += 1
        if r.prediction_correct:
            agg[(framework, 'BOTH', edge_band)]['wins'] += 1

        agg[('ALL', 'BOTH', edge_band)]['total'] += 1
        if r.prediction_correct:
            agg[('ALL', 'BOTH', edge_band)]['wins'] += 1

    # Print results
    frameworks = sorted(set(r.system_id for r in rows))
    fw_families = sorted(set(classify_framework(s) for s in frameworks))
    fw_families = ['ALL'] + fw_families

    for direction in ['BOTH', 'OVER', 'UNDER']:
        print(f"{'='*80}")
        print(f"  {source_label} — Direction: {direction}")
        print(f"{'='*80}")

        # Header
        header = f"{'Edge':>6}"
        for fw in fw_families:
            header += f" | {fw:>18}"
        print(header)
        print('-' * len(header))

        for label, _, _ in EDGE_BANDS:
            line = f"{label:>6}"
            for fw in fw_families:
                stats = agg.get((fw, direction, label), {'wins': 0, 'total': 0})
                n = stats['total']
                if n == 0:
                    line += f" | {'':>18}"
                else:
                    hr = 100.0 * stats['wins'] / n
                    line += f" | {color_hr(hr, n)} (N={n:>4})"
            print(line)

        print()

    # CSV export
    if csv_path:
        csv_rows = []
        for (fw, direction, edge_band), stats in sorted(agg.items()):
            n = stats['total']
            if n == 0:
                continue
            hr = round(100.0 * stats['wins'] / n, 2)
            csv_rows.append({
                'framework': fw,
                'direction': direction,
                'edge_band': edge_band,
                'hr': hr,
                'wins': stats['wins'],
                'losses': n - stats['wins'],
                'n': n,
            })

        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['framework', 'direction', 'edge_band',
                                                    'hr', 'wins', 'losses', 'n'])
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"CSV written to {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Edge calibration analysis — HR by edge band, framework, direction',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', default=None, help='End date (YYYY-MM-DD)')
    parser.add_argument('--best-bets', action='store_true',
                        help='Filter to signal best bets picks only')
    parser.add_argument('--csv', default=None, help='Export results to CSV')

    args = parser.parse_args()
    run_analysis(args.start, args.end, args.best_bets, args.csv)


if __name__ == '__main__':
    main()
