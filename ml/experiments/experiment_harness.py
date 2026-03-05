#!/usr/bin/env python3
"""Experiment Harness — multi-seed experiment runner with aggregation and auto-verdict.

Runs N seeds of an experiment + N baseline seeds, aggregates metrics,
computes statistical significance (two-proportion z-test), and classifies
the experiment outcome.

Usage:
    # Run experiment with baseline comparison
    PYTHONPATH=. python ml/experiments/experiment_harness.py \
        --name pace_v1 \
        --hypothesis "TeamRankings pace adds signal" \
        --experiment-features pace_v1

    # Skip baseline (if you already have one)
    PYTHONPATH=. python ml/experiments/experiment_harness.py \
        --name pace_v1 \
        --experiment-features pace_v1 \
        --no-baseline

    # Custom seeds and training window
    PYTHONPATH=. python ml/experiments/experiment_harness.py \
        --name tracking_v1 \
        --experiment-features tracking_v1 \
        --seeds 42,123,456,789,999,1234 \
        --train-days 56

    # Pass extra args to quick_retrain.py
    PYTHONPATH=. python ml/experiments/experiment_harness.py \
        --name v16_test \
        --extra-args "--feature-set v16_noveg"

    # Dry run
    PYTHONPATH=. python ml/experiments/experiment_harness.py \
        --name pace_v1 --experiment-features pace_v1 --dry-run

Created: 2026-03-04 (Session 409)
"""

import argparse
import json
import logging
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_SEEDS = [42, 123, 456, 789, 999]

# Verdict thresholds (matches EXPERIMENT-GRID.md criteria)
DEAD_END_THRESHOLD = 1.0    # delta < 1pp
NOISE_THRESHOLD = 2.0       # 1-2pp delta
PROMISING_THRESHOLD = 3.0   # 2-3pp delta with N >= 50
# >= 3pp confirmed = PROMOTE


def parse_args():
    parser = argparse.ArgumentParser(
        description='Multi-seed experiment runner with aggregation and auto-verdict'
    )
    parser.add_argument('--name', required=True, help='Experiment name (e.g., pace_v1)')
    parser.add_argument('--hypothesis', default='', help='Why we are testing this')
    parser.add_argument('--experiment-features', default=None, metavar='EXPERIMENT_ID',
                        help='Experiment feature ID from backfill table')
    parser.add_argument('--feature-set', default='v12_noveg',
                        help='Feature set (default: v12_noveg)')
    parser.add_argument('--seeds', default=','.join(str(s) for s in DEFAULT_SEEDS),
                        help='Comma-separated seeds (default: 42,123,456,789,999)')
    parser.add_argument('--train-days', type=int, default=56,
                        help='Training window in days (default: 56)')
    parser.add_argument('--eval-days', type=int, default=14,
                        help='Eval window in days (default: 14)')
    parser.add_argument('--baseline-train-days', type=int, default=56,
                        help='Training window for baseline runs (default: 56)')
    parser.add_argument('--no-baseline', action='store_true',
                        help='Skip baseline runs')
    parser.add_argument('--extra-args', default='',
                        help='Extra args passed to quick_retrain.py')
    parser.add_argument('--results-dir', default=None,
                        help='Directory for JSON results (default: results/experiments/<name>)')
    parser.add_argument('--persist', action='store_true',
                        help='Write results to BigQuery experiment_grid_results table')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show plan without running')
    return parser.parse_args()


def run_single_seed(name: str, seed: int, is_baseline: bool,
                    feature_set: str, train_days: int, eval_days: int,
                    baseline_train_days: int,
                    experiment_features: Optional[str],
                    extra_args: str, results_dir: str) -> Optional[Dict]:
    """Run quick_retrain.py for one seed and return parsed JSON result."""
    label = 'baseline' if is_baseline else 'experiment'
    run_name = f"{name}_{label}_s{seed}"
    machine_output = os.path.join(results_dir, f"{run_name}.json")

    # Baseline uses default train_days; experiment uses specified train_days
    effective_train_days = baseline_train_days if is_baseline else train_days

    cmd = [
        sys.executable, 'ml/experiments/quick_retrain.py',
        '--name', run_name,
        '--feature-set', feature_set,
        '--train-days', str(effective_train_days),
        '--eval-days', str(eval_days),
        '--random-seed', str(seed),
        '--skip-register',
        '--force',
        '--machine-output', machine_output,
    ]

    # Add experiment-only args (not applied to baseline)
    if not is_baseline:
        if experiment_features:
            cmd.extend(['--experiment-features', experiment_features])
        if extra_args:
            cmd.extend(extra_args.split())

    logger.info(f"  [{label}] seed={seed}: {run_name}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800,
            env={**os.environ, 'PYTHONPATH': '.'},
        )

        if os.path.exists(machine_output):
            with open(machine_output) as f:
                data = json.load(f)
            hr3 = data.get('hr_edge3')
            mae = data.get('mae')
            logger.info(f"    HR(3+)={hr3}%, MAE={mae}")
            return data
        else:
            stderr_tail = result.stderr.strip().split('\n')[-5:] if result.stderr else []
            logger.error(f"    FAILED — no machine output")
            for line in stderr_tail:
                logger.error(f"      {line}")
            return None

    except subprocess.TimeoutExpired:
        logger.error(f"    TIMEOUT after 30 min")
        return None
    except Exception as e:
        logger.error(f"    ERROR: {e}")
        return None


def aggregate(results: List[Dict]) -> Dict:
    """Compute mean/std of key metrics across seeds."""
    metrics = {
        'hr_edge3': [], 'hr_edge5': [], 'hr_all': [],
        'mae': [], 'n_edge3': [], 'n_edge5': [],
    }

    for r in results:
        for key in metrics:
            val = r.get(key)
            if val is not None:
                metrics[key].append(float(val))

    agg = {}
    for key, vals in metrics.items():
        if vals:
            mean = sum(vals) / len(vals)
            variance = sum((v - mean) ** 2 for v in vals) / len(vals) if len(vals) > 1 else 0
            agg[key] = {
                'mean': round(mean, 4),
                'std': round(math.sqrt(variance), 4),
                'n_seeds': len(vals),
                'values': [round(v, 4) for v in vals],
            }

    return agg


def two_proportion_z_test(p1: float, n1: int, p2: float, n2: int) -> float:
    """Two-proportion pooled z-test. Returns z-score.

    p1, p2 are proportions (e.g., 0.65 for 65%).
    Positive z means p1 > p2.
    """
    if n1 == 0 or n2 == 0:
        return 0.0

    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    if p_pool == 0 or p_pool == 1:
        return 0.0

    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0

    return (p1 - p2) / se


def compare(exp_agg: Dict, base_agg: Dict) -> Dict:
    """Compare experiment vs baseline aggregates."""
    comparison = {}

    for metric in ['hr_edge3', 'hr_edge5', 'mae']:
        if metric in exp_agg and metric in base_agg:
            exp_mean = exp_agg[metric]['mean']
            base_mean = base_agg[metric]['mean']
            delta = exp_mean - base_mean

            comp = {
                'experiment': exp_mean,
                'baseline': base_mean,
                'delta': round(delta, 4),
            }

            # Z-test for hit rates
            if metric.startswith('hr_'):
                n_metric = metric.replace('hr_', 'n_')
                exp_n = int(exp_agg.get(n_metric, {}).get('mean', 0))
                base_n = int(base_agg.get(n_metric, {}).get('mean', 0))
                if exp_n > 0 and base_n > 0:
                    z = two_proportion_z_test(
                        exp_mean / 100.0, exp_n,
                        base_mean / 100.0, base_n
                    )
                    comp['z_score'] = round(z, 3)
                    comp['significant_95'] = abs(z) >= 1.96
                    comp['significant_90'] = abs(z) >= 1.645

            # MAE: negative delta is improvement
            if metric == 'mae':
                comp['improved'] = delta < 0

            comparison[metric] = comp

    return comparison


def determine_verdict(comparison: Dict, exp_agg: Dict) -> Tuple[str, str]:
    """Auto-classify experiment result.

    Returns (verdict, reason).
    """
    hr3_comp = comparison.get('hr_edge3', {})
    delta = hr3_comp.get('delta', 0)
    n_edge3 = int(exp_agg.get('n_edge3', {}).get('mean', 0))

    if delta <= 0:
        return 'DEAD_END', f"Negative delta: {delta:+.1f}pp"

    if delta < DEAD_END_THRESHOLD:
        return 'DEAD_END', f"Delta {delta:+.1f}pp < {DEAD_END_THRESHOLD}pp threshold"

    if delta < NOISE_THRESHOLD:
        return 'NOISE', f"Delta {delta:+.1f}pp — within noise range ({DEAD_END_THRESHOLD}-{NOISE_THRESHOLD}pp)"

    if delta < PROMISING_THRESHOLD:
        if n_edge3 >= 50:
            return 'PROMISING', f"Delta {delta:+.1f}pp with N={n_edge3} — needs confirmation"
        else:
            return 'NOISE', f"Delta {delta:+.1f}pp but N={n_edge3} < 50 — insufficient sample"

    # >= 3pp
    sig_95 = hr3_comp.get('significant_95', False)
    if sig_95:
        return 'PROMOTE', f"Delta {delta:+.1f}pp, z={hr3_comp.get('z_score', 0):.2f} (p<0.05)"
    elif n_edge3 >= 50:
        return 'PROMISING', f"Delta {delta:+.1f}pp, N={n_edge3} but not significant at p<0.05"
    else:
        return 'NOISE', f"Delta {delta:+.1f}pp but N={n_edge3} too small for significance"


def print_summary(name: str, hypothesis: str,
                  exp_results: List[Dict], base_results: List[Dict],
                  exp_agg: Dict, base_agg: Dict,
                  comparison: Dict, verdict: str, verdict_reason: str):
    """Print formatted summary table."""
    print(f"\n{'='*90}")
    print(f" EXPERIMENT: {name}")
    if hypothesis:
        print(f" HYPOTHESIS: {hypothesis}")
    print(f"{'='*90}")

    # Seed-level results
    print(f"\n{'─'*90}")
    print(f" SEED RESULTS")
    print(f"{'─'*90}")
    print(f"{'Seed':>6s} {'Type':<12s} {'HR(3+)':>8s} {'N(3+)':>6s} {'HR(5+)':>8s} {'MAE':>8s} {'Gates':>6s}")
    print(f"{'-'*60}")

    for r in base_results:
        seed = r.get('experiment_id', '?').split('_s')[-1] if 'experiment_id' in r else '?'
        hr3 = f"{r.get('hr_edge3', 0):.1f}%" if r.get('hr_edge3') is not None else 'N/A'
        hr5 = f"{r.get('hr_edge5', 0):.1f}%" if r.get('hr_edge5') is not None else 'N/A'
        mae = f"{r.get('mae', 0):.4f}" if r.get('mae') is not None else 'N/A'
        gates = 'PASS' if r.get('all_gates_passed') else 'FAIL'
        n3 = r.get('n_edge3', 0) or 0
        print(f"{seed:>6s} {'baseline':<12s} {hr3:>8s} {n3:>6d} {hr5:>8s} {mae:>8s} {gates:>6s}")

    for r in exp_results:
        seed = r.get('experiment_id', '?').split('_s')[-1] if 'experiment_id' in r else '?'
        hr3 = f"{r.get('hr_edge3', 0):.1f}%" if r.get('hr_edge3') is not None else 'N/A'
        hr5 = f"{r.get('hr_edge5', 0):.1f}%" if r.get('hr_edge5') is not None else 'N/A'
        mae = f"{r.get('mae', 0):.4f}" if r.get('mae') is not None else 'N/A'
        gates = 'PASS' if r.get('all_gates_passed') else 'FAIL'
        n3 = r.get('n_edge3', 0) or 0
        print(f"{seed:>6s} {'experiment':<12s} {hr3:>8s} {n3:>6d} {hr5:>8s} {mae:>8s} {gates:>6s}")

    # Aggregate comparison
    print(f"\n{'─'*90}")
    print(f" AGGREGATE COMPARISON")
    print(f"{'─'*90}")
    print(f"{'Metric':<12s} {'Baseline':>14s} {'Experiment':>14s} {'Delta':>10s} {'z-score':>9s} {'Sig(95%)':>10s}")
    print(f"{'-'*72}")

    for metric in ['hr_edge3', 'hr_edge5', 'mae']:
        comp = comparison.get(metric, {})
        if not comp:
            continue

        base_val = comp.get('baseline', 0)
        exp_val = comp.get('experiment', 0)
        delta = comp.get('delta', 0)

        if metric.startswith('hr_'):
            base_str = f"{base_val:.1f}%"
            exp_str = f"{exp_val:.1f}%"
            delta_str = f"{delta:+.1f}pp"
        else:
            base_str = f"{base_val:.4f}"
            exp_str = f"{exp_val:.4f}"
            delta_str = f"{delta:+.4f}"

        z_str = f"{comp.get('z_score', 0):.2f}" if 'z_score' in comp else '—'
        sig_str = 'YES' if comp.get('significant_95') else ('no' if 'significant_95' in comp else '—')

        label = {'hr_edge3': 'HR(3+)', 'hr_edge5': 'HR(5+)', 'mae': 'MAE'}[metric]
        print(f"{label:<12s} {base_str:>14s} {exp_str:>14s} {delta_str:>10s} {z_str:>9s} {sig_str:>10s}")

    # Verdict
    verdict_emoji = {
        'DEAD_END': '💀', 'NOISE': '🔇', 'PROMISING': '🔍', 'PROMOTE': '🚀'
    }.get(verdict, '❓')

    print(f"\n{'─'*90}")
    print(f" VERDICT: {verdict_emoji} {verdict}")
    print(f" REASON:  {verdict_reason}")
    print(f"{'='*90}\n")


def persist_to_bq(name: str, hypothesis: str, config: Dict,
                  exp_results: List[Dict], base_results: List[Dict],
                  exp_agg: Dict, base_agg: Dict,
                  comparison: Dict, verdict: str, verdict_reason: str):
    """Write experiment results to BigQuery."""
    try:
        from google.cloud import bigquery

        project_id = 'nba-props-platform'
        table_id = f'{project_id}.nba_predictions.experiment_grid_results'
        bq = bigquery.Client(project=project_id)

        # Get git commit
        try:
            git_commit = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                text=True, timeout=5
            ).strip()
        except Exception:
            git_commit = 'unknown'

        row = {
            'experiment_id': f"{name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            'name': name,
            'hypothesis': hypothesis,
            'config': json.dumps(config),
            'seed_results': json.dumps([_safe_serialize(r) for r in exp_results]),
            'baseline_results': json.dumps([_safe_serialize(r) for r in base_results]),
            'aggregate': json.dumps(exp_agg),
            'baseline_aggregate': json.dumps(base_agg),
            'comparison': json.dumps(comparison),
            'verdict': verdict,
            'verdict_reason': verdict_reason,
            'git_commit': git_commit,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }

        errors = bq.insert_rows_json(table_id, [row])
        if errors:
            logger.warning(f"BQ insert errors: {errors}")
        else:
            logger.info(f"Results persisted to {table_id}")

    except Exception as e:
        logger.warning(f"Failed to persist to BQ (non-fatal): {e}")


def _safe_serialize(obj):
    """Make object JSON-serializable."""
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def main():
    args = parse_args()

    seeds = [int(s) for s in args.seeds.split(',')]
    results_dir = args.results_dir or f"results/experiments/{args.name}"

    config = {
        'feature_set': args.feature_set,
        'train_days': args.train_days,
        'baseline_train_days': args.baseline_train_days,
        'eval_days': args.eval_days,
        'experiment_features': args.experiment_features,
        'seeds': seeds,
        'extra_args': args.extra_args,
    }

    print(f"\nExperiment Harness: {args.name}")
    print(f"  Hypothesis: {args.hypothesis or '(none)'}")
    print(f"  Feature set: {args.feature_set}")
    print(f"  Experiment features: {args.experiment_features or '(none)'}")
    print(f"  Train days: {args.train_days} (baseline: {args.baseline_train_days})")
    print(f"  Eval days: {args.eval_days}")
    print(f"  Extra args: {args.extra_args or '(none)'}")
    print(f"  Seeds: {seeds}")
    print(f"  Baseline: {'skip' if args.no_baseline else 'yes'}")
    print(f"  Results dir: {results_dir}")

    total_runs = len(seeds) * (1 if args.no_baseline else 2)
    print(f"  Total runs: {total_runs}")

    if args.dry_run:
        print("\n[DRY RUN] Would run:")
        for seed in seeds:
            if not args.no_baseline:
                print(f"  baseline seed={seed}")
            print(f"  experiment seed={seed}")
        return

    os.makedirs(results_dir, exist_ok=True)

    # Run baselines
    base_results = []
    if not args.no_baseline:
        print(f"\n{'─'*60}")
        print(f" BASELINE RUNS ({len(seeds)} seeds)")
        print(f"{'─'*60}")
        for seed in seeds:
            result = run_single_seed(
                args.name, seed, is_baseline=True,
                feature_set=args.feature_set, train_days=args.train_days,
                eval_days=args.eval_days,
                baseline_train_days=args.baseline_train_days,
                experiment_features=args.experiment_features,
                extra_args=args.extra_args, results_dir=results_dir,
            )
            if result:
                base_results.append(result)

        if not base_results:
            logger.error("All baseline runs failed — aborting")
            sys.exit(1)

    # Run experiments
    print(f"\n{'─'*60}")
    print(f" EXPERIMENT RUNS ({len(seeds)} seeds)")
    print(f"{'─'*60}")
    exp_results = []
    for seed in seeds:
        result = run_single_seed(
            args.name, seed, is_baseline=False,
            feature_set=args.feature_set, train_days=args.train_days,
            eval_days=args.eval_days,
            baseline_train_days=args.baseline_train_days,
            experiment_features=args.experiment_features,
            extra_args=args.extra_args, results_dir=results_dir,
        )
        if result:
            exp_results.append(result)

    if not exp_results:
        logger.error("All experiment runs failed — aborting")
        sys.exit(1)

    # Aggregate
    exp_agg = aggregate(exp_results)
    base_agg = aggregate(base_results) if base_results else {}

    # Compare
    if base_agg:
        comp = compare(exp_agg, base_agg)
        verdict, verdict_reason = determine_verdict(comp, exp_agg)
    else:
        comp = {}
        verdict = 'NO_BASELINE'
        verdict_reason = 'No baseline to compare against'

    # Print summary
    print_summary(
        args.name, args.hypothesis,
        exp_results, base_results,
        exp_agg, base_agg,
        comp, verdict, verdict_reason,
    )

    # Save aggregated results
    summary_path = os.path.join(results_dir, f"{args.name}_summary.json")
    summary = {
        'name': args.name,
        'hypothesis': args.hypothesis,
        'config': config,
        'experiment_aggregate': exp_agg,
        'baseline_aggregate': base_agg,
        'comparison': comp,
        'verdict': verdict,
        'verdict_reason': verdict_reason,
        'n_experiment_seeds': len(exp_results),
        'n_baseline_seeds': len(base_results),
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info(f"Summary written to: {summary_path}")

    # Persist to BQ if requested
    if args.persist:
        persist_to_bq(
            args.name, args.hypothesis, config,
            exp_results, base_results,
            exp_agg, base_agg,
            comp, verdict, verdict_reason,
        )

    # Exit code based on verdict
    if verdict == 'PROMOTE':
        sys.exit(0)
    elif verdict in ('DEAD_END', 'NOISE'):
        sys.exit(0)  # Normal exit — expected outcomes
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
