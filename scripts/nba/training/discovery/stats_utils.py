"""Statistical utilities for signal discovery.

Provides:
- Binomial test against baseline HR
- Benjamini-Hochberg FDR correction
- Block bootstrap by game-date (handles same-game clustering)
- Cross-season consistency check
- Effect size classification

Session 466: Initial implementation.
"""

import numpy as np
from scipy import stats
from typing import Dict, List, Optional, Tuple


# Walk-forward baseline HR at edge 3+ (from 30K graded predictions)
BASELINE_HR = 0.515

# Minimum samples
MIN_N_PER_SEASON = 30
MIN_N_TOTAL = 100
MIN_SEASONS_CONSISTENT = 3  # out of 4 complete seasons

# Effect size thresholds (pp above/below baseline)
EFFECT_SHADOW = 0.02   # 2pp — shadow/accumulate data
EFFECT_ACCEPT = 0.02   # 2pp — accept as candidate
EFFECT_PROMOTE = 0.03  # 3pp — promote to production


def binomial_test_vs_baseline(
    wins: int,
    total: int,
    baseline: float = BASELINE_HR,
    alternative: str = 'two-sided',
) -> float:
    """Binomial test p-value against baseline HR.

    For signal candidates: alternative='greater' (HR > baseline)
    For filter candidates: alternative='less' (HR < baseline)
    """
    if total == 0:
        return 1.0
    return stats.binomtest(wins, total, baseline, alternative=alternative).pvalue


def benjamini_hochberg(p_values: np.ndarray, alpha: float = 0.05) -> Tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg FDR correction.

    Returns:
        (rejected, adjusted_pvalues) — boolean array of rejections and adjusted p-values
    """
    n = len(p_values)
    if n == 0:
        return np.array([], dtype=bool), np.array([])

    sorted_idx = np.argsort(p_values)
    sorted_pvals = p_values[sorted_idx]

    # BH adjusted p-values
    adjusted = np.zeros(n)
    adjusted[sorted_idx[-1]] = sorted_pvals[-1]
    for i in range(n - 2, -1, -1):
        rank = i + 1
        bh_val = sorted_pvals[i] * n / rank
        adjusted[sorted_idx[i]] = min(bh_val, adjusted[sorted_idx[i + 1]])

    rejected = adjusted <= alpha
    return rejected, adjusted


def block_bootstrap_hr(
    wins_per_block: List[int],
    total_per_block: List[int],
    n_bootstrap: int = 5000,
    ci_level: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Block bootstrap HR confidence interval.

    Blocks are game-dates (handles within-date correlation).
    Returns: (hr_mean, ci_lower, ci_upper)
    """
    rng = np.random.RandomState(seed)
    wins_arr = np.array(wins_per_block)
    total_arr = np.array(total_per_block)
    n_blocks = len(wins_arr)

    if n_blocks == 0 or total_arr.sum() == 0:
        return 0.0, 0.0, 0.0

    boot_hrs = np.zeros(n_bootstrap)
    for i in range(n_bootstrap):
        idx = rng.randint(0, n_blocks, size=n_blocks)
        boot_wins = wins_arr[idx].sum()
        boot_total = total_arr[idx].sum()
        boot_hrs[i] = boot_wins / boot_total if boot_total > 0 else 0.0

    alpha = (1 - ci_level) / 2
    ci_lower = np.percentile(boot_hrs, alpha * 100)
    ci_upper = np.percentile(boot_hrs, (1 - alpha) * 100)
    return float(boot_hrs.mean()), float(ci_lower), float(ci_upper)


def cross_season_consistency(
    season_hrs: Dict[str, float],
    season_ns: Dict[str, int],
    baseline: float = BASELINE_HR,
    min_n: int = MIN_N_PER_SEASON,
    direction: str = 'above',
) -> Dict:
    """Check cross-season consistency of a signal/filter.

    Args:
        season_hrs: {season_label: hit_rate}
        season_ns: {season_label: sample_size}
        baseline: threshold to compare against
        direction: 'above' for signals, 'below' for filters
        min_n: minimum N per season to count

    Returns:
        Dict with seasons_consistent, seasons_valid, cv, verdict
    """
    valid_seasons = {s: hr for s, hr in season_hrs.items()
                     if season_ns.get(s, 0) >= min_n}

    if len(valid_seasons) < 2:
        return {
            'seasons_consistent': 0,
            'seasons_valid': len(valid_seasons),
            'cv': None,
            'pass': False,
        }

    hrs = list(valid_seasons.values())
    mean_hr = np.mean(hrs)
    std_hr = np.std(hrs)
    cv = std_hr / mean_hr if mean_hr > 0 else float('inf')

    if direction == 'above':
        consistent = sum(1 for hr in hrs if hr > baseline)
    else:
        consistent = sum(1 for hr in hrs if hr < baseline)

    return {
        'seasons_consistent': consistent,
        'seasons_valid': len(valid_seasons),
        'cv': round(cv, 4),
        'mean_hr': round(mean_hr, 4),
        'std_hr': round(std_hr, 4),
        'pass': consistent >= MIN_SEASONS_CONSISTENT and cv < 0.15,
        'per_season': {s: {'hr': round(hr, 4), 'n': season_ns[s]}
                       for s, hr in valid_seasons.items()},
    }


def classify_effect(hr: float, baseline: float = BASELINE_HR) -> str:
    """Classify effect size relative to baseline."""
    diff = hr - baseline
    abs_diff = abs(diff)

    if abs_diff < EFFECT_SHADOW:
        return 'NOISE'
    elif diff > 0:
        if abs_diff >= EFFECT_PROMOTE:
            return 'SIGNAL_STRONG'
        else:
            return 'SIGNAL_WEAK'
    else:
        if abs_diff >= EFFECT_PROMOTE:
            return 'FILTER_STRONG'
        else:
            return 'FILTER_WEAK'


def compute_hypothesis_stats(
    df_subset,
    correct_col: str = 'correct',
    date_col: str = 'game_date',
    season_col: str = 'season',
    baseline: float = BASELINE_HR,
) -> Optional[Dict]:
    """Compute full stats for a hypothesis subset.

    Args:
        df_subset: DataFrame filtered to rows where hypothesis fires
        correct_col: column with 1/0 for correct prediction
        date_col: column with game date (for block bootstrap)
        season_col: column with season label

    Returns:
        Dict with all stats, or None if insufficient data
    """
    if len(df_subset) < MIN_N_TOTAL:
        return None

    total = len(df_subset)
    wins = int(df_subset[correct_col].sum())
    hr = wins / total

    # Per-season breakdown
    season_hrs = {}
    season_ns = {}
    for season, grp in df_subset.groupby(season_col):
        n = len(grp)
        w = int(grp[correct_col].sum())
        season_hrs[str(season)] = w / n if n > 0 else 0.0
        season_ns[str(season)] = n

    # Determine test direction
    is_filter = hr < baseline
    alt = 'less' if is_filter else 'greater'
    consistency_dir = 'below' if is_filter else 'above'

    # Binomial test
    p_value = binomial_test_vs_baseline(wins, total, baseline, alternative=alt)

    # Cross-season consistency
    consistency = cross_season_consistency(
        season_hrs, season_ns, baseline, direction=consistency_dir
    )

    # Block bootstrap by game-date
    date_stats = df_subset.groupby(date_col)[correct_col].agg(['sum', 'count'])
    boot_mean, boot_lo, boot_hi = block_bootstrap_hr(
        date_stats['sum'].tolist(),
        date_stats['count'].tolist(),
    )

    # Effect classification
    effect = classify_effect(hr, baseline)

    return {
        'total_n': total,
        'wins': wins,
        'hr': round(hr, 4),
        'effect_pp': round((hr - baseline) * 100, 1),
        'effect_class': effect,
        'p_value': round(p_value, 6),
        'bootstrap_hr': round(boot_mean, 4),
        'bootstrap_ci_lo': round(boot_lo, 4),
        'bootstrap_ci_hi': round(boot_hi, 4),
        'ci_excludes_baseline': boot_lo > baseline if not is_filter else boot_hi < baseline,
        'consistency': consistency,
    }
