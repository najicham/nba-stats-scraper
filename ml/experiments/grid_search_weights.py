#!/usr/bin/env python3
"""Grid Search Weights — systematic experiment matrix using quick_retrain.py.

Runs a cross-product of experiment parameters, parses results, and displays
a summary table ranked by key metrics.

Built-in templates:
  tier_weight_sweep:    12 tier-weight combos
  recency_tier:         Best tier weights x recency half-lives (8 combos)
  feature_set_shootout: V12/V13/V15/V16 all with vegas=0.25 (4 combos)

Usage:
    # Template-based sweep
    PYTHONPATH=. python ml/experiments/grid_search_weights.py \\
        --template tier_weight_sweep \\
        --train-start 2025-12-01 --train-end 2026-02-15 \\
        --eval-start 2026-02-16 --eval-end 2026-02-27

    # Custom grid
    PYTHONPATH=. python ml/experiments/grid_search_weights.py \\
        --base-args "--feature-set v12_noveg --category-weight vegas=0.25" \\
        --grid "tier-weight=star=2.0:starter=1.2:bench=0.5,star=3.0:starter=1.5:bench=0.3" \\
        --grid "recency-weight=14,21" \\
        --train-start 2025-12-01 --train-end 2026-02-15

    # Dry run
    PYTHONPATH=. python ml/experiments/grid_search_weights.py \\
        --template feature_set_shootout \\
        --train-start 2025-12-01 --train-end 2026-02-15 --dry-run

Created: 2026-02-28 (Session 366)
"""

import argparse
import csv
import itertools
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# Template definitions
TEMPLATES = {
    'tier_weight_sweep': {
        'description': '12 tier-weight combos with vegas=0.25',
        'base_args': '--feature-set v12_noveg --category-weight vegas=0.25 --no-vegas',
        'grid': {
            'tier-weight': [
                'star=2.0,starter=1.2,role=1.0,bench=0.5',
                'star=2.0,starter=1.2,role=0.8,bench=0.3',
                'star=3.0,starter=1.5,role=1.0,bench=0.5',
                'star=3.0,starter=1.5,role=0.8,bench=0.3',
                'star=2.5,starter=1.3,role=1.0,bench=0.5',
                'star=2.5,starter=1.3,role=0.8,bench=0.3',
                'star=1.5,starter=1.0,role=0.8,bench=0.5',
                'star=1.5,starter=1.0,role=0.6,bench=0.3',
                'star=4.0,starter=2.0,role=1.0,bench=0.5',
                'star=4.0,starter=2.0,role=0.8,bench=0.3',
                'star=2.0,starter=1.5,role=1.0,bench=0.8',
                'star=3.0,starter=1.0,role=0.8,bench=0.5',
            ],
        },
    },
    'recency_tier': {
        'description': 'Best tier weights x recency half-lives (8 combos)',
        'base_args': '--feature-set v12_noveg --category-weight vegas=0.25 --no-vegas',
        'grid': {
            'tier-weight': [
                'star=2.0,starter=1.2,role=1.0,bench=0.5',
                'star=2.0,starter=1.2,role=0.8,bench=0.3',
            ],
            'recency-weight': ['7', '14', '21', '30'],
        },
    },
    'feature_set_shootout': {
        'description': 'V12/V13/V15/V16 all with vegas=0.25',
        'base_args': '--no-vegas --category-weight vegas=0.25',
        'grid': {
            'feature-set': ['v12_noveg', 'v13', 'v15', 'v16_noveg'],
        },
    },
}


def parse_grid_spec(grid_specs: List[str]) -> Dict[str, List[str]]:
    """Parse --grid "param=val1,val2" specs into a dict."""
    grid = {}
    for spec in grid_specs:
        if '=' not in spec:
            raise ValueError(f"Grid spec must be param=val1,val2: {spec}")
        param, values = spec.split('=', 1)
        grid[param] = values.split(',')
    return grid


def generate_combinations(grid: Dict[str, List[str]]) -> List[Dict[str, str]]:
    """Generate cross-product of all grid values."""
    if not grid:
        return [{}]

    keys = list(grid.keys())
    value_lists = [grid[k] for k in keys]

    combos = []
    for values in itertools.product(*value_lists):
        combo = dict(zip(keys, values))
        combos.append(combo)

    return combos


def build_command(base_args: str, combo: Dict[str, str],
                  train_start: str, train_end: str,
                  eval_start: str, eval_end: str,
                  combo_idx: int, output_dir: str) -> Tuple[List[str], str]:
    """Build the quick_retrain.py command for one combination."""
    machine_output = os.path.join(output_dir, f"result_{combo_idx:03d}.json")

    cmd_parts = [
        sys.executable, 'ml/experiments/quick_retrain.py',
        '--name', f'grid_{combo_idx:03d}',
        '--train-start', train_start,
        '--train-end', train_end,
        '--eval-start', eval_start,
        '--eval-end', eval_end,
        '--skip-register',
        '--force',
        '--machine-output', machine_output,
    ]

    # Add base args
    if base_args:
        cmd_parts.extend(base_args.split())

    # Add grid parameters
    for param, value in combo.items():
        cmd_parts.extend([f'--{param}', value])

    return cmd_parts, machine_output


def run_experiment(cmd: List[str], machine_output: str,
                   combo_idx: int, total: int) -> Optional[Dict]:
    """Run a single experiment and parse results."""
    logger.info(f"[{combo_idx + 1}/{total}] Running: {' '.join(cmd[-6:])}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800,
            env={**os.environ, 'PYTHONPATH': '.'},
        )

        if os.path.exists(machine_output):
            with open(machine_output) as f:
                return json.load(f)
        else:
            # Fallback: parse stdout for key metrics
            logger.warning(f"  No machine output file, parsing stdout...")
            parsed = _parse_stdout(result.stdout)
            if parsed is None:
                # Log failure details so user can diagnose
                stderr_tail = result.stderr.strip().split('\n')[-5:] if result.stderr else []
                stdout_tail = result.stdout.strip().split('\n')[-5:] if result.stdout else []
                if stderr_tail:
                    logger.error(f"  stderr (last 5 lines):")
                    for line in stderr_tail:
                        logger.error(f"    {line}")
                if stdout_tail:
                    logger.error(f"  stdout (last 5 lines):")
                    for line in stdout_tail:
                        logger.error(f"    {line}")
                if result.returncode != 0:
                    logger.error(f"  Exit code: {result.returncode}")
            return parsed

    except subprocess.TimeoutExpired:
        logger.error(f"  TIMEOUT after 30 min")
        return None
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        return None


def _parse_stdout(stdout: str) -> Optional[Dict]:
    """Fallback: extract key metrics from stdout text."""
    result = {}

    # MAE
    m = re.search(r'MAE \(w/lines\):\s+([\d.]+)', stdout)
    if m:
        result['mae'] = float(m.group(1))

    # HR edge 3+
    m = re.search(r'Hit rate \(3\+\).*?(\d+\.\d+)%.*?n=(\d+)', stdout)
    if m:
        result['hr_edge3'] = float(m.group(1))
        result['n_edge3'] = int(m.group(2))

    # HR edge 5+
    m = re.search(r'Hit rate \(5\+\).*?(\d+\.\d+)%.*?n=(\d+)', stdout)
    if m:
        result['hr_edge5'] = float(m.group(1))
        result['n_edge5'] = int(m.group(2))

    # Gates
    result['all_gates_passed'] = 'ALL GATES PASSED' in stdout

    # OVER/UNDER
    m = re.search(r'OVER:\s+([\d.]+)%.*?(\d+) graded', stdout)
    if m:
        result['directional'] = result.get('directional', {})
        result['directional']['over_hr'] = float(m.group(1))
        result['directional']['over_n'] = int(m.group(2))
    m = re.search(r'UNDER:\s+([\d.]+)%.*?(\d+) graded', stdout)
    if m:
        result['directional'] = result.get('directional', {})
        result['directional']['under_hr'] = float(m.group(1))
        result['directional']['under_n'] = int(m.group(2))

    return result if result else None


def display_results(combos: List[Dict[str, str]], results: List[Optional[Dict]],
                    csv_file: Optional[str] = None):
    """Display ranked results table."""
    rows = []
    for i, (combo, result) in enumerate(zip(combos, results)):
        if result is None:
            continue
        combo_str = ', '.join(f"{k}={v}" for k, v in combo.items())
        if len(combo_str) > 45:
            combo_str = combo_str[:42] + '...'

        dir_data = result.get('directional', {})
        rows.append({
            'idx': i,
            'combo': combo_str,
            'hr3': result.get('hr_edge3'),
            'n3': result.get('n_edge3', 0),
            'hr5': result.get('hr_edge5'),
            'over_hr': dir_data.get('over_hr'),
            'under_hr': dir_data.get('under_hr'),
            'mae': result.get('mae'),
            'gates': result.get('all_gates_passed', False),
        })

    # Sort by HR edge 3+ descending
    rows.sort(key=lambda r: r.get('hr3') or 0, reverse=True)

    print(f"\n{'='*110}")
    print(f" GRID SEARCH RESULTS ({len(rows)}/{len(combos)} completed)")
    print(f"{'='*110}")
    print(f"{'#':>3s} {'Combo':<47s} {'HR 3+':>7s} {'N':>5s} {'HR 5+':>7s} {'OVER':>7s} {'UNDER':>7s} {'MAE':>7s} {'Gates':>6s}")
    print("-" * 110)

    for rank, r in enumerate(rows, 1):
        hr3 = f"{r['hr3']:.1f}%" if r['hr3'] is not None else 'N/A'
        hr5 = f"{r['hr5']:.1f}%" if r['hr5'] is not None else 'N/A'
        over = f"{r['over_hr']:.1f}%" if r['over_hr'] is not None else 'N/A'
        under = f"{r['under_hr']:.1f}%" if r['under_hr'] is not None else 'N/A'
        mae = f"{r['mae']:.4f}" if r['mae'] is not None else 'N/A'
        gates = 'PASS' if r['gates'] else 'FAIL'
        print(f"{rank:>3d} {r['combo']:<47s} {hr3:>7s} {r['n3']:>5d} {hr5:>7s} {over:>7s} {under:>7s} {mae:>7s} {gates:>6s}")

    # Best model summary
    if rows:
        best = rows[0]
        print(f"\nBest: #{best['idx']} -- {best['combo']}")
        print(f"  HR 3+: {best.get('hr3')}% (N={best.get('n3')}), "
              f"OVER: {best.get('over_hr')}%, UNDER: {best.get('under_hr')}%")

    # Write CSV
    if csv_file and rows:
        with open(csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nCSV written to: {csv_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Grid search over quick_retrain.py parameters'
    )
    parser.add_argument('--template', choices=list(TEMPLATES.keys()),
                        help='Built-in template name')
    parser.add_argument('--base-args', default='',
                        help='Base arguments passed to every experiment')
    parser.add_argument('--grid', action='append', default=[],
                        help='Grid spec: "param=val1,val2" (repeatable)')
    parser.add_argument('--train-start', required=True)
    parser.add_argument('--train-end', required=True)
    parser.add_argument('--eval-start', default=None)
    parser.add_argument('--eval-end', default=None)
    parser.add_argument('--dry-run', action='store_true',
                        help='Show planned experiments without running')
    parser.add_argument('--csv', default=None, help='Write results to CSV file')
    args = parser.parse_args()

    # Resolve template
    if args.template:
        tmpl = TEMPLATES[args.template]
        base_args = tmpl['base_args']
        if args.base_args:
            base_args += ' ' + args.base_args
        grid = tmpl['grid']
        print(f"Template: {args.template} -- {tmpl['description']}")
    elif args.grid:
        base_args = args.base_args
        grid = parse_grid_spec(args.grid)
    else:
        parser.error('Provide --template or --grid')

    # Default eval dates if not provided
    eval_start = args.eval_start
    eval_end = args.eval_end
    if not eval_start:
        train_end_dt = datetime.strptime(args.train_end, '%Y-%m-%d')
        eval_start = (train_end_dt + timedelta(days=1)).strftime('%Y-%m-%d')
    if not eval_end:
        eval_end = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

    combos = generate_combinations(grid)
    print(f"Grid: {len(combos)} combinations")
    print(f"Training: {args.train_start} to {args.train_end}")
    print(f"Eval: {eval_start} to {eval_end}")
    print()

    if args.dry_run:
        print("DRY RUN -- planned experiments:")
        for i, combo in enumerate(combos):
            combo_str = ' '.join(f"--{k} {v}" for k, v in combo.items())
            print(f"  [{i+1:>3d}] {base_args} {combo_str}")
        print(f"\nTotal: {len(combos)} experiments")
        return

    # Run experiments
    output_dir = tempfile.mkdtemp(prefix='grid_search_')
    print(f"Output dir: {output_dir}")

    results = []
    for i, combo in enumerate(combos):
        cmd, machine_output = build_command(
            base_args, combo,
            args.train_start, args.train_end,
            eval_start, eval_end,
            i, output_dir,
        )
        result = run_experiment(cmd, machine_output, i, len(combos))
        results.append(result)

    display_results(combos, results, csv_file=args.csv)


if __name__ == '__main__':
    main()
