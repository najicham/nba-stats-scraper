#!/usr/bin/env python3
"""Comprehensive model evaluation grid — analyze HR across all dimensions.

Queries prediction_accuracy directly (already graded, fast) and produces
cross-tabulated HR breakdowns across models, directions, edge bands,
time periods, tiers, and home/away.

Usage:
    # Full evaluation of all models
    python bin/model_eval_grid.py --start-date 2026-01-01 --end-date 2026-02-28

    # Focus on specific model patterns
    python bin/model_eval_grid.py --models "catboost_v12_noveg%,lgbm%" \
        --start-date 2026-01-01

    # Sweep edge floors to find optimal threshold
    python bin/model_eval_grid.py --sweep-edge 2.5,3.0,3.5,4.0,5.0 \
        --start-date 2026-01-01

    # Cross-tab by model × direction × edge band
    python bin/model_eval_grid.py --by model,direction,edge_band \
        --start-date 2026-01-01

    # Compare best bets vs raw predictions
    python bin/model_eval_grid.py --best-bets --start-date 2026-01-01

    # Weekly rolling HR for specific models
    python bin/model_eval_grid.py --by model,week --models "catboost_v12_noveg%" \
        --start-date 2026-01-01

    # Export to CSV
    python bin/model_eval_grid.py --start-date 2026-01-01 --csv results.csv

Created: Session 395
"""

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from google.cloud import bigquery

sys.path.insert(0, '.')
from shared.clients.bigquery_pool import get_bigquery_client
from shared.config.gcp_config import get_project_id

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

PROJECT_ID = get_project_id()


# ── Dimension Definitions ──────────────────────────────────────────────

def edge_band(edge: float) -> str:
    """Classify edge into bands."""
    edge = abs(edge)
    if edge >= 10:
        return '10+'
    elif edge >= 7:
        return '7-10'
    elif edge >= 5:
        return '5-7'
    elif edge >= 3:
        return '3-5'
    else:
        return '<3'


def tier_from_line(line: float) -> str:
    """Classify player tier from prop line."""
    if line is None:
        return 'unknown'
    if line >= 25:
        return 'star'
    elif line >= 15:
        return 'starter'
    elif line >= 5:
        return 'role'
    else:
        return 'bench'


def is_home(game_id: str, team_abbr: str) -> str:
    """Determine home/away from game_id format: 20260101_AWAY_HOME."""
    if not game_id or not team_abbr:
        return 'unknown'
    parts = game_id.split('_')
    if len(parts) >= 3 and parts[2] == team_abbr:
        return 'HOME'
    return 'AWAY'


def week_label(game_date) -> str:
    """ISO week label."""
    if hasattr(game_date, 'isocalendar'):
        iso = game_date.isocalendar()
        return f"W{iso[1]:02d}"
    return 'unknown'


def month_label(game_date) -> str:
    """Month label."""
    if hasattr(game_date, 'strftime'):
        return game_date.strftime('%Y-%m')
    return 'unknown'


def model_family(system_id: str) -> str:
    """Extract model family from system_id for grouping."""
    if not system_id:
        return 'unknown'

    # Remove training date suffixes to get family
    # catboost_v12_noveg_train0103_0227 -> catboost_v12_noveg
    # lgbm_v12_noveg_train0103_0227 -> lgbm_v12_noveg
    parts = system_id.split('_train')
    if len(parts) > 1:
        return parts[0]

    # Exact match models like catboost_v9, catboost_v12
    return system_id


# ── Data Fetching ──────────────────────────────────────────────────────

def fetch_predictions(
    bq_client: bigquery.Client,
    start_date: str,
    end_date: str,
    model_patterns: Optional[List[str]] = None,
    min_edge: float = 0.0,
    quality_floor: float = 0.0,
    actionable_only: bool = False,
) -> List[Dict]:
    """Fetch graded predictions from prediction_accuracy."""

    # Build model filter
    if model_patterns:
        model_clauses = []
        for pat in model_patterns:
            if '%' in pat:
                model_clauses.append(f"system_id LIKE '{pat}'")
            else:
                model_clauses.append(f"system_id = '{pat}'")
        model_filter = f"AND ({' OR '.join(model_clauses)})"
    else:
        model_filter = ""

    quality_filter = ""
    if quality_floor > 0:
        quality_filter = f"AND COALESCE(feature_quality_score, 0) >= {quality_floor}"

    actionable_filter = ""
    if actionable_only:
        actionable_filter = "AND is_actionable = TRUE"

    query = f"""
    SELECT
        system_id,
        game_date,
        game_id,
        player_lookup,
        team_abbr,
        opponent_team_abbr,
        recommendation,
        CAST(predicted_points AS FLOAT64) AS predicted_points,
        CAST(line_value AS FLOAT64) AS line_value,
        CAST(predicted_points - line_value AS FLOAT64) AS edge,
        prediction_correct,
        CAST(confidence_score AS FLOAT64) AS confidence_score,
        COALESCE(CAST(feature_quality_score AS FLOAT64), 0) AS feature_quality_score,
        CAST(actual_points AS FLOAT64) AS actual_points,
        CAST(absolute_error AS FLOAT64) AS absolute_error,
        has_prop_line,
        line_source,
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date >= '{start_date}'
      AND game_date <= '{end_date}'
      AND prediction_correct IS NOT NULL
      AND has_prop_line = TRUE
      AND recommendation IN ('OVER', 'UNDER')
      {model_filter}
      {quality_filter}
      {actionable_filter}
    ORDER BY game_date, system_id, player_lookup
    """

    rows = list(bq_client.query(query).result())
    return [dict(r) for r in rows]


def fetch_best_bets_picks(
    bq_client: bigquery.Client,
    start_date: str,
    end_date: str,
) -> Set[Tuple[str, str, str]]:
    """Fetch set of (player_lookup, game_date, recommendation) from signal_best_bets_picks."""
    query = f"""
    SELECT player_lookup, CAST(game_date AS STRING) as game_date, recommendation
    FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks`
    WHERE game_date >= '{start_date}'
      AND game_date <= '{end_date}'
    """
    rows = list(bq_client.query(query).result())
    return {(r['player_lookup'], r['game_date'], r['recommendation']) for r in rows}


# ── Aggregation Engine ─────────────────────────────────────────────────

class EvalGrid:
    """Aggregates predictions into multi-dimensional HR grid."""

    VALID_DIMENSIONS = {
        'model', 'family', 'direction', 'edge_band', 'tier',
        'home_away', 'month', 'week', 'opponent', 'best_bets',
    }

    def __init__(self, predictions: List[Dict], best_bets: Optional[Set] = None):
        self.predictions = predictions
        self.best_bets = best_bets or set()

        # Pre-compute dimensions for each prediction
        for pred in self.predictions:
            edge = pred.get('edge', 0) or 0
            pred['_edge_band'] = edge_band(edge)
            pred['_tier'] = tier_from_line(pred.get('line_value'))
            pred['_home_away'] = is_home(
                pred.get('game_id', ''),
                pred.get('team_abbr', '')
            )
            pred['_month'] = month_label(pred['game_date'])
            pred['_week'] = week_label(pred['game_date'])
            pred['_family'] = model_family(pred.get('system_id', ''))

            # Check if in best bets
            gd = str(pred['game_date'])
            bb_key = (pred.get('player_lookup', ''), gd, pred.get('recommendation', ''))
            pred['_best_bets'] = 'BB' if bb_key in self.best_bets else 'raw'

    def _get_dim_value(self, pred: Dict, dim: str) -> str:
        """Get dimension value for a prediction."""
        dim_map = {
            'model': lambda p: p.get('system_id', 'unknown'),
            'family': lambda p: p['_family'],
            'direction': lambda p: p.get('recommendation', 'unknown'),
            'edge_band': lambda p: p['_edge_band'],
            'tier': lambda p: p['_tier'],
            'home_away': lambda p: p['_home_away'],
            'month': lambda p: p['_month'],
            'week': lambda p: p['_week'],
            'opponent': lambda p: p.get('opponent_team_abbr', 'unknown'),
            'best_bets': lambda p: p['_best_bets'],
        }
        return dim_map.get(dim, lambda p: 'unknown')(pred)

    def aggregate(
        self,
        dimensions: List[str],
        min_edge: float = 0.0,
        min_n: int = 1,
    ) -> List[Dict]:
        """Aggregate HR across given dimensions.

        Returns list of dicts with dimension values + stats.
        """
        # Validate dimensions
        for dim in dimensions:
            if dim not in self.VALID_DIMENSIONS:
                raise ValueError(f"Unknown dimension: {dim}. Valid: {self.VALID_DIMENSIONS}")

        # Group predictions by dimension keys
        groups = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_mae': 0.0})

        for pred in self.predictions:
            edge = abs(pred.get('edge', 0) or 0)
            if edge < min_edge:
                continue

            key = tuple(self._get_dim_value(pred, dim) for dim in dimensions)
            g = groups[key]

            if pred.get('prediction_correct'):
                g['wins'] += 1
            else:
                g['losses'] += 1

            mae = pred.get('absolute_error')
            if mae is not None:
                g['total_mae'] += float(mae)

        # Build result rows
        results = []
        for key, g in groups.items():
            total = g['wins'] + g['losses']
            if total < min_n:
                continue

            row = {}
            for i, dim in enumerate(dimensions):
                row[dim] = key[i]

            row['n'] = total
            row['wins'] = g['wins']
            row['losses'] = g['losses']
            row['hr'] = round(g['wins'] / total * 100, 1)
            row['pnl'] = round(g['wins'] * 1.0 - g['losses'] * 1.1, 2)
            row['mae'] = round(g['total_mae'] / total, 2) if total > 0 else 0

            results.append(row)

        # Sort by first dimension, then by N descending
        results.sort(key=lambda r: (
            tuple(r.get(dim, '') for dim in dimensions[:-1]) if len(dimensions) > 1 else (),
            -r['n']
        ))

        return results

    def sweep_edge_floors(
        self,
        edge_floors: List[float],
        dimensions: List[str] = None,
        min_n: int = 5,
    ) -> List[Dict]:
        """Sweep across edge floor values to find optimal threshold."""
        if dimensions is None:
            dimensions = ['direction']

        results = []
        for floor in edge_floors:
            agg = self.aggregate(dimensions, min_edge=floor, min_n=min_n)
            for row in agg:
                row['edge_floor'] = floor
            results.extend(agg)

        return results

    def model_summary(self, min_edge: float = 3.0, min_n: int = 10) -> List[Dict]:
        """One-row-per-model summary with key metrics."""
        # Get per-model stats
        model_stats = self.aggregate(['model'], min_edge=min_edge, min_n=min_n)

        # Get per-model direction stats
        dir_stats = self.aggregate(['model', 'direction'], min_edge=min_edge, min_n=1)
        dir_lookup = {}
        for r in dir_stats:
            dir_lookup[(r['model'], r['direction'])] = r

        # Enrich
        for row in model_stats:
            model = row['model']
            over = dir_lookup.get((model, 'OVER'), {})
            under = dir_lookup.get((model, 'UNDER'), {})
            row['over_n'] = over.get('n', 0)
            row['over_hr'] = over.get('hr', 0)
            row['under_n'] = under.get('n', 0)
            row['under_hr'] = under.get('hr', 0)
            row['family'] = model_family(model)

        model_stats.sort(key=lambda r: -r['hr'])
        return model_stats


# ── Display Functions ──────────────────────────────────────────────────

def print_summary(results: List[Dict], title: str = "MODEL SUMMARY"):
    """Print model summary table."""
    if not results:
        print("No results to display.")
        return

    print(f"\n{'='*120}")
    print(f"  {title}")
    print(f"{'='*120}")
    print(f"  {'Model':<52s} {'N':>5s} {'HR%':>6s} {'P&L':>8s} {'MAE':>6s} "
          f"{'OVER':>10s} {'UNDER':>10s}")
    print(f"  {'-'*115}")

    for r in results:
        over_str = f"{r.get('over_hr', 0):.0f}% n={r.get('over_n', 0)}"
        under_str = f"{r.get('under_hr', 0):.0f}% n={r.get('under_n', 0)}"
        model_name = r['model'][:50]

        # Color-code HR
        hr = r['hr']
        hr_str = f"{hr:.1f}%"
        if hr >= 60:
            hr_str = f"\033[32m{hr_str}\033[0m"  # green
        elif hr < 52:
            hr_str = f"\033[31m{hr_str}\033[0m"  # red

        print(f"  {model_name:<52s} {r['n']:>5d} {hr_str:>15s} {r['pnl']:>+8.2f} "
              f"{r['mae']:>6.2f} {over_str:>10s} {under_str:>10s}")

    print(f"{'='*120}")


def print_crosstab(results: List[Dict], dimensions: List[str], title: str = ""):
    """Print cross-tabulated results."""
    if not results:
        print("No results to display.")
        return

    # Build header from dimensions
    dim_widths = {}
    for dim in dimensions:
        max_val_len = max(len(str(r.get(dim, ''))) for r in results)
        dim_widths[dim] = max(len(dim), max_val_len, 8)

    title_str = title or f"CROSS-TAB: {' × '.join(dimensions)}"
    total_width = sum(dim_widths.values()) + len(dimensions) * 3 + 50
    print(f"\n{'='*total_width}")
    print(f"  {title_str}")
    print(f"{'='*total_width}")

    # Header
    header_parts = []
    for dim in dimensions:
        header_parts.append(f"{dim:<{dim_widths[dim]}s}")
    header = "  ".join(header_parts)
    print(f"  {header}  {'N':>5s} {'HR%':>6s} {'P&L':>8s} {'W-L':>7s}")
    print(f"  {'-'*(total_width-4)}")

    # Rows
    for r in results:
        parts = []
        for dim in dimensions:
            val = str(r.get(dim, ''))[:dim_widths[dim]]
            parts.append(f"{val:<{dim_widths[dim]}s}")
        line = "  ".join(parts)

        hr = r['hr']
        hr_str = f"{hr:.1f}%"
        if hr >= 60:
            hr_str = f"\033[32m{hr_str}\033[0m"
        elif hr < 52:
            hr_str = f"\033[31m{hr_str}\033[0m"

        wl = f"{r['wins']}-{r['losses']}"
        print(f"  {line}  {r['n']:>5d} {hr_str:>15s} {r['pnl']:>+8.2f} {wl:>7s}")

    print(f"{'='*total_width}")


def print_edge_sweep(results: List[Dict]):
    """Print edge floor sweep results."""
    if not results:
        print("No results.")
        return

    # Group by edge_floor
    by_floor = defaultdict(list)
    for r in results:
        by_floor[r['edge_floor']].append(r)

    print(f"\n{'='*90}")
    print(f"  EDGE FLOOR SWEEP")
    print(f"{'='*90}")
    print(f"  {'Floor':>6s}  {'Direction':<10s}  {'N':>5s}  {'HR%':>6s}  {'P&L':>8s}  {'$/pick':>8s}")
    print(f"  {'-'*85}")

    for floor in sorted(by_floor.keys()):
        rows = by_floor[floor]
        # Also compute total
        total_n = sum(r['n'] for r in rows)
        total_wins = sum(r['wins'] for r in rows)
        total_hr = round(total_wins / total_n * 100, 1) if total_n > 0 else 0
        total_pnl = round(total_wins * 1.0 - (total_n - total_wins) * 1.1, 2)

        for r in sorted(rows, key=lambda x: x.get('direction', '')):
            ppl = r['pnl'] / r['n'] if r['n'] > 0 else 0
            print(f"  {floor:>6.1f}  {r.get('direction', 'ALL'):<10s}  "
                  f"{r['n']:>5d}  {r['hr']:>5.1f}%  {r['pnl']:>+8.2f}  {ppl:>+8.3f}")

        ppl_total = total_pnl / total_n if total_n > 0 else 0
        print(f"  {floor:>6.1f}  {'TOTAL':<10s}  "
              f"{total_n:>5d}  {total_hr:>5.1f}%  {total_pnl:>+8.2f}  {ppl_total:>+8.3f}")
        print(f"  {'-'*85}")

    print(f"{'='*90}")


def write_csv(results: List[Dict], filepath: str, dimensions: List[str]):
    """Write results to CSV."""
    if not results:
        return

    fieldnames = dimensions + ['n', 'wins', 'losses', 'hr', 'pnl', 'mae']
    # Add any extra keys
    for key in results[0]:
        if key not in fieldnames:
            fieldnames.append(key)

    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)
    print(f"\nCSV written to: {filepath}")


# ── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Comprehensive model evaluation grid',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', default=None, help='End date (YYYY-MM-DD, default: yesterday)')
    parser.add_argument('--models', default=None,
                        help='Comma-separated model patterns (supports %% wildcard)')
    parser.add_argument('--by', default=None,
                        help='Comma-separated dimensions for cross-tab '
                        '(model, family, direction, edge_band, tier, home_away, '
                        'month, week, opponent, best_bets)')
    parser.add_argument('--min-edge', type=float, default=3.0,
                        help='Minimum edge filter (default: 3.0)')
    parser.add_argument('--min-n', type=int, default=5,
                        help='Minimum N per cell (default: 5)')
    parser.add_argument('--quality-floor', type=float, default=0.0,
                        help='Minimum feature quality score')
    parser.add_argument('--sweep-edge', default=None,
                        help='Comma-separated edge floors to sweep (e.g., 2.0,3.0,4.0,5.0)')
    parser.add_argument('--best-bets', action='store_true',
                        help='Include best_bets dimension (join with signal_best_bets_picks)')
    parser.add_argument('--bb-only', action='store_true',
                        help='Only show predictions that were in best bets')
    parser.add_argument('--family', action='store_true',
                        help='Group models by family instead of exact system_id')
    parser.add_argument('--csv', default=None, help='Write results to CSV file')
    parser.add_argument('--json', default=None, help='Write results to JSON file')
    parser.add_argument('--verbose', '-v', action='store_true')

    args = parser.parse_args()

    end_date = args.end_date or (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    model_patterns = [p.strip() for p in args.models.split(',')] if args.models else None

    bq_client = get_bigquery_client(project_id=PROJECT_ID)

    # Fetch predictions
    print(f"Fetching predictions ({args.start_date} to {end_date})...")
    predictions = fetch_predictions(
        bq_client, args.start_date, end_date,
        model_patterns=model_patterns,
        quality_floor=args.quality_floor,
    )
    print(f"  {len(predictions)} graded predictions loaded")

    if not predictions:
        print("No predictions found. Check date range and model patterns.")
        return

    # Optionally fetch best bets
    best_bets = set()
    if args.best_bets or args.bb_only:
        print("Fetching best bets picks...")
        best_bets = fetch_best_bets_picks(bq_client, args.start_date, end_date)
        print(f"  {len(best_bets)} best bets picks loaded")

    # Filter to BB-only if requested
    if args.bb_only:
        bb_preds = []
        for pred in predictions:
            gd = str(pred['game_date'])
            key = (pred.get('player_lookup', ''), gd, pred.get('recommendation', ''))
            if key in best_bets:
                bb_preds.append(pred)
        print(f"  Filtered to {len(bb_preds)} best bets predictions")
        predictions = bb_preds

    # Build evaluation grid
    grid = EvalGrid(predictions, best_bets)

    # Determine what to display
    if args.sweep_edge:
        # Edge floor sweep
        floors = [float(f) for f in args.sweep_edge.split(',')]
        results = grid.sweep_edge_floors(floors, min_n=args.min_n)
        print_edge_sweep(results)
        if args.csv:
            write_csv(results, args.csv, ['edge_floor', 'direction'])

    elif args.by:
        # Cross-tab mode
        dimensions = [d.strip() for d in args.by.split(',')]

        # Auto-replace 'model' with 'family' if --family flag
        if args.family and 'model' in dimensions:
            dimensions = ['family' if d == 'model' else d for d in dimensions]

        results = grid.aggregate(dimensions, min_edge=args.min_edge, min_n=args.min_n)
        print_crosstab(results, dimensions)
        if args.csv:
            write_csv(results, args.csv, dimensions)

    else:
        # Default: model summary
        if args.family:
            # Group by family
            results = grid.aggregate(
                ['family'], min_edge=args.min_edge, min_n=args.min_n
            )
            # Get direction breakdown per family
            dir_results = grid.aggregate(
                ['family', 'direction'], min_edge=args.min_edge, min_n=1
            )
            dir_lookup = {}
            for r in dir_results:
                dir_lookup[(r['family'], r['direction'])] = r

            for row in results:
                fam = row['family']
                over = dir_lookup.get((fam, 'OVER'), {})
                under = dir_lookup.get((fam, 'UNDER'), {})
                row['over_n'] = over.get('n', 0)
                row['over_hr'] = over.get('hr', 0)
                row['under_n'] = under.get('n', 0)
                row['under_hr'] = under.get('hr', 0)
                row['model'] = fam  # For display
            results.sort(key=lambda r: -r['hr'])
            print_summary(results, title="MODEL FAMILY SUMMARY")
        else:
            results = grid.model_summary(min_edge=args.min_edge, min_n=args.min_n)
            print_summary(results)

        if args.csv:
            write_csv(results, args.csv, ['model'])

    # Write JSON if requested
    if args.json:
        with open(args.json, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"JSON written to: {args.json}")

    # Print quick stats
    total_n = sum(r['n'] for r in grid.aggregate(['direction'], min_edge=args.min_edge))
    over_stats = next((r for r in grid.aggregate(['direction'], min_edge=args.min_edge)
                       if r.get('direction') == 'OVER'), {})
    under_stats = next((r for r in grid.aggregate(['direction'], min_edge=args.min_edge)
                        if r.get('direction') == 'UNDER'), {})

    total_wins = over_stats.get('wins', 0) + under_stats.get('wins', 0)
    total_hr = round(total_wins / total_n * 100, 1) if total_n > 0 else 0

    print(f"\n  Quick stats (edge >= {args.min_edge}):")
    print(f"    Total: {total_wins}/{total_n} ({total_hr}%)")
    print(f"    OVER:  {over_stats.get('wins', 0)}/{over_stats.get('n', 0)} ({over_stats.get('hr', 0)}%)")
    print(f"    UNDER: {under_stats.get('wins', 0)}/{under_stats.get('n', 0)} ({under_stats.get('hr', 0)}%)")


if __name__ == '__main__':
    main()
