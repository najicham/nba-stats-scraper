#!/usr/bin/env python3
"""Bootstrap confidence intervals and significance tests for hit rate comparisons.

Usage:
    # Compare two hit rates
    python bin/bootstrap_hr.py --a-wins 26 --a-total 32 --b-wins 52 --b-total 82

    # Single HR confidence interval
    python bin/bootstrap_hr.py --a-wins 26 --a-total 32

    # Custom confidence level and iterations
    python bin/bootstrap_hr.py --a-wins 26 --a-total 32 --b-wins 52 --b-total 82 --ci 0.90 --n-bootstrap 50000

    # Power analysis: minimum sample size to detect a given effect
    python bin/bootstrap_hr.py --power --baseline-hr 0.55 --target-hr 0.65
"""

import argparse
import sys
import numpy as np
from scipy import stats


def bootstrap_hr_ci(wins: int, total: int, n_bootstrap: int = 10000,
                    ci_level: float = 0.95, seed: int = 42) -> dict:
    """Compute bootstrap confidence interval for a hit rate."""
    rng = np.random.RandomState(seed)
    hr = wins / total

    # Create binary outcomes array
    outcomes = np.array([1] * wins + [0] * (total - wins))

    # Bootstrap
    bootstrap_hrs = np.array([
        rng.choice(outcomes, size=total, replace=True).mean()
        for _ in range(n_bootstrap)
    ])

    alpha = 1 - ci_level
    ci_lower = np.percentile(bootstrap_hrs, 100 * alpha / 2)
    ci_upper = np.percentile(bootstrap_hrs, 100 * (1 - alpha / 2))

    return {
        'hr': hr,
        'ci_lower': ci_lower,
        'ci_upper': ci_upper,
        'ci_width': ci_upper - ci_lower,
        'n': total,
        'wins': wins,
        'std': bootstrap_hrs.std(),
    }


def two_proportion_z_test(wins_a: int, total_a: int,
                          wins_b: int, total_b: int) -> dict:
    """Two-proportion z-test for comparing two hit rates."""
    p_a = wins_a / total_a
    p_b = wins_b / total_b
    diff = p_a - p_b

    # Pooled proportion under H0
    p_pool = (wins_a + wins_b) / (total_a + total_b)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / total_a + 1 / total_b))

    if se == 0:
        return {'z_stat': 0, 'p_value': 1.0, 'diff': diff, 'se': 0}

    z = diff / se
    p_value = 2 * (1 - stats.norm.cdf(abs(z)))  # two-tailed

    return {
        'z_stat': z,
        'p_value': p_value,
        'diff': diff,
        'se': se,
    }


def bootstrap_hr_diff(wins_a: int, total_a: int, wins_b: int, total_b: int,
                       n_bootstrap: int = 10000, ci_level: float = 0.95,
                       seed: int = 42) -> dict:
    """Bootstrap confidence interval for the difference in hit rates (A - B)."""
    rng = np.random.RandomState(seed)

    outcomes_a = np.array([1] * wins_a + [0] * (total_a - wins_a))
    outcomes_b = np.array([1] * wins_b + [0] * (total_b - wins_b))

    diffs = np.array([
        rng.choice(outcomes_a, size=total_a, replace=True).mean() -
        rng.choice(outcomes_b, size=total_b, replace=True).mean()
        for _ in range(n_bootstrap)
    ])

    alpha = 1 - ci_level
    ci_lower = np.percentile(diffs, 100 * alpha / 2)
    ci_upper = np.percentile(diffs, 100 * (1 - alpha / 2))

    # P-value: proportion of bootstrap samples where diff <= 0
    # (one-sided: is A better than B?)
    p_value_one_sided = np.mean(diffs <= 0)
    p_value_two_sided = 2 * min(p_value_one_sided, 1 - p_value_one_sided)

    return {
        'mean_diff': diffs.mean(),
        'ci_lower': ci_lower,
        'ci_upper': ci_upper,
        'p_value_two_sided': p_value_two_sided,
        'p_value_one_sided': p_value_one_sided,
        'zero_in_ci': ci_lower <= 0 <= ci_upper,
    }


def power_analysis(baseline_hr: float, target_hr: float,
                   alpha: float = 0.05, power: float = 0.80) -> int:
    """Minimum sample size per group to detect a given HR difference.

    Uses the formula for two-proportion z-test power.
    """
    p1 = baseline_hr
    p2 = target_hr
    diff = abs(p2 - p1)

    if diff == 0:
        return float('inf')

    # z-values
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    z_beta = stats.norm.ppf(power)

    # Sample size formula
    p_bar = (p1 + p2) / 2
    n = ((z_alpha * np.sqrt(2 * p_bar * (1 - p_bar)) +
          z_beta * np.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) / diff) ** 2

    return int(np.ceil(n))


def format_pct(val: float) -> str:
    return f"{val * 100:.1f}%"


def main():
    parser = argparse.ArgumentParser(
        description='Bootstrap HR confidence intervals and significance tests',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--a-wins', type=int, help='Wins for group A')
    parser.add_argument('--a-total', type=int, help='Total for group A')
    parser.add_argument('--b-wins', type=int, help='Wins for group B (optional)')
    parser.add_argument('--b-total', type=int, help='Total for group B (optional)')
    parser.add_argument('--ci', type=float, default=0.95, help='Confidence level (default: 0.95)')
    parser.add_argument('--n-bootstrap', type=int, default=10000, help='Bootstrap iterations (default: 10000)')
    parser.add_argument('--seed', type=int, default=42, help='Random seed (default: 42)')

    # Power analysis mode
    parser.add_argument('--power', action='store_true', help='Run power analysis')
    parser.add_argument('--baseline-hr', type=float, help='Baseline hit rate for power analysis')
    parser.add_argument('--target-hr', type=float, help='Target hit rate for power analysis')

    args = parser.parse_args()

    # Power analysis mode
    if args.power:
        if not args.baseline_hr or not args.target_hr:
            parser.error('--power requires --baseline-hr and --target-hr')

        n = power_analysis(args.baseline_hr, args.target_hr)
        diff = abs(args.target_hr - args.baseline_hr)

        print(f"\n{'='*60}")
        print(f"  POWER ANALYSIS")
        print(f"{'='*60}")
        print(f"  Baseline HR:  {format_pct(args.baseline_hr)}")
        print(f"  Target HR:    {format_pct(args.target_hr)}")
        print(f"  Effect size:  {format_pct(diff)}")
        print(f"  Alpha:        0.05 (two-sided)")
        print(f"  Power:        0.80")
        print(f"{'='*60}")
        print(f"  Min sample per group: {n}")
        print(f"  Total samples needed: {n * 2}")
        print(f"{'='*60}\n")
        return

    # HR analysis mode
    if args.a_wins is None or args.a_total is None:
        parser.error('--a-wins and --a-total are required')

    # Single HR CI
    ci_a = bootstrap_hr_ci(args.a_wins, args.a_total, args.n_bootstrap, args.ci, args.seed)

    print(f"\n{'='*60}")
    print(f"  GROUP A: {args.a_wins}/{args.a_total} = {format_pct(ci_a['hr'])}")
    print(f"  {args.ci*100:.0f}% CI: [{format_pct(ci_a['ci_lower'])}, {format_pct(ci_a['ci_upper'])}]")
    print(f"  CI width: {format_pct(ci_a['ci_width'])}")
    print(f"{'='*60}")

    # Two-group comparison
    if args.b_wins is not None and args.b_total is not None:
        ci_b = bootstrap_hr_ci(args.b_wins, args.b_total, args.n_bootstrap, args.ci, args.seed)

        print(f"  GROUP B: {args.b_wins}/{args.b_total} = {format_pct(ci_b['hr'])}")
        print(f"  {args.ci*100:.0f}% CI: [{format_pct(ci_b['ci_lower'])}, {format_pct(ci_b['ci_upper'])}]")
        print(f"  CI width: {format_pct(ci_b['ci_width'])}")
        print(f"{'='*60}")

        # Z-test
        z_result = two_proportion_z_test(args.a_wins, args.a_total, args.b_wins, args.b_total)
        diff_result = bootstrap_hr_diff(
            args.a_wins, args.a_total, args.b_wins, args.b_total,
            args.n_bootstrap, args.ci, args.seed
        )

        print(f"\n  COMPARISON (A - B)")
        print(f"  {'─'*56}")
        print(f"  Observed diff:    {format_pct(z_result['diff'])} ({'+' if z_result['diff'] >= 0 else ''}{z_result['diff']*100:.1f}pp)")
        print(f"  Bootstrap diff:   {format_pct(diff_result['mean_diff'])}")
        print(f"  {args.ci*100:.0f}% CI of diff:  [{format_pct(diff_result['ci_lower'])}, {format_pct(diff_result['ci_upper'])}]")
        print(f"  Zero in CI:       {'YES — NOT significant' if diff_result['zero_in_ci'] else 'NO — SIGNIFICANT'}")
        print(f"  {'─'*56}")
        print(f"  Z-test p-value:   {z_result['p_value']:.4f}")
        print(f"  Bootstrap p:      {diff_result['p_value_two_sided']:.4f}")
        print(f"  {'─'*56}")

        # Verdict
        if z_result['p_value'] < 0.05:
            winner = 'A' if z_result['diff'] > 0 else 'B'
            print(f"  VERDICT: Statistically significant (p < 0.05). Group {winner} is better.")
        elif z_result['p_value'] < 0.10:
            print(f"  VERDICT: Marginally significant (p < 0.10). Suggestive but not conclusive.")
        else:
            print(f"  VERDICT: NOT significant (p = {z_result['p_value']:.3f}). Cannot distinguish A from B.")

        # Power analysis for this comparison
        n_needed = power_analysis(ci_b['hr'], ci_a['hr'] if ci_a['hr'] > ci_b['hr'] else ci_b['hr'] + abs(z_result['diff']))
        print(f"  Samples needed to detect this diff: {n_needed} per group")
        print(f"{'='*60}\n")
    else:
        print()


if __name__ == '__main__':
    main()
