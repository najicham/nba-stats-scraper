#!/usr/bin/env python3
"""
NBA Bankroll Management & Bet-Sizing Simulation
================================================
Ports the MLB staking harness (scripts/mlb/bankroll_simulation.py) to NBA player
points props, run against the 5-season walk-forward backtest cache in
results/bb_simulator/ (loaded via the discovery DataLoader).

WHAT THIS ANSWERS
-----------------
Point accuracy is dead (held-out residual R2 ~= 0). The lever that sizing can
actually pull is DRAWDOWN / VARIANCE reduction (surviving a March-2026-type
collapse) plus a modest ROI uplift -- NOT a big hit-rate jump. This sim frames
results honestly on that basis: flat 1u vs capped fractional Kelly (1/4, 1/2) vs
edge-proportional vs ultra-tier, compared on terminal bankroll, ROI, Sharpe,
and (above all) MAX DRAWDOWN + a Monte-Carlo drawdown distribution.

REAL ODDS (not fictional -110)
------------------------------
NBA points props run -115..-125 (vig 4-9%), not -110. We reuse the payout logic
from real_odds_reckoning.py: profit-per-1u = decimal-1 from American odds.
  * OVER picks: real per-pick `over_odds_median` from BettingPros multibook,
    clipped to the sane range [-400, 400], fallback to the -115 median.
  * UNDER picks: the local cache has NO under-side quote (only over_odds_median).
    We therefore price UNDER at the empirical real-vig median (-115), matching
    the true juice environment. This is an approximation -- flagged below.

WIN-PROBABILITY FOR KELLY (empirical-HR proxy)
----------------------------------------------
Kelly needs p_win. A separate agent is producing a calibrated isotonic
edge->p_win map; do NOT depend on it. Here p_win is derived, leak-free, from the
empirical HR of each (edge-bucket x direction) cell computed ONLY on the TRAINING
portion of each walk-forward split, then applied to the TEST split. This is a
self-contained proxy that should later be swapped for the isotonic calibrator.
Any single-bet Kelly fraction is CAPPED (default 2.5% of bankroll) -- raw Kelly
on 60%+ HR cells is wildly over-aggressive under correlated same-day outcomes.

ANOMALY HANDLING
----------------
OVER edge is a 2025-26 scoring-environment anomaly; UNDER is durable
cross-season. Headline comparison is reported on the NON-anomaly seasons
(2023-24 + 2024-25); 2025-26 is reported SEPARATELY so Kelly's apparent ROI
isn't inflated by the anomaly. Pooled is also shown.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Make the repo root importable so `scripts.nba...` resolves when run directly.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.nba.training.discovery.data_loader import DiscoveryDataset  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
STARTING_BANKROLL = 100.0          # units
MIN_EDGE = 3.0                     # NBA best-bets baseline edge floor
KELLY_CAP = 0.025                  # max single-bet fraction of bankroll (2.5%)
FALLBACK_ODDS = -115               # real-vig median for missing/insane / UNDER
SANE_ODDS_LO, SANE_ODDS_HI = -400, 400

NON_ANOMALY_SEASONS = ['2023-24', '2024-25']
ANOMALY_SEASON = '2025-26'
ALL_SEASONS = ['2021-22', '2022-23', '2023-24', '2024-25', '2025-26']

# Edge buckets for the empirical-HR p_win proxy.
EDGE_BINS = [3.0, 4.0, 5.0, 6.0, 7.0, 9.0, 100.0]
EDGE_LABELS = ['3-4', '4-5', '5-6', '6-7', '7-9', '9+']


# ---------------------------------------------------------------------------
# Odds / payout utilities (mirrors real_odds_reckoning.py + MLB harness)
# ---------------------------------------------------------------------------
def american_to_decimal(odds: float) -> float:
    if odds > 0:
        return 1.0 + odds / 100.0
    return 1.0 + 100.0 / abs(odds)


def profit_per_unit(odds: float) -> float:
    """Profit on a 1u winning bet at given American odds (decimal - 1)."""
    return american_to_decimal(odds) - 1.0


def pnl_for_bet(won: bool, stake: float, odds: float) -> float:
    return stake * profit_per_unit(odds) if won else -stake


def breakeven_hr(odds: float) -> float:
    return 1.0 / american_to_decimal(odds)


def kelly_fraction(prob: float, odds: float) -> float:
    """Raw Kelly fraction of bankroll (>= 0)."""
    b = american_to_decimal(odds) - 1.0
    q = 1.0 - prob
    if b <= 0:
        return 0.0
    return max((b * prob - q) / b, 0.0)


def clean_over_odds(x: float) -> float:
    """Clip real over odds to a sane props range; fallback to -115."""
    if pd.isna(x) or not (SANE_ODDS_LO <= x <= SANE_ODDS_HI):
        return float(FALLBACK_ODDS)
    return float(x)


# ---------------------------------------------------------------------------
# Data loading + real-odds attachment
# ---------------------------------------------------------------------------
def load_data(min_edge: float = MIN_EDGE) -> pd.DataFrame:
    """Load the 5-season NBA cache, attach real per-pick odds, edge buckets."""
    df = DiscoveryDataset(min_edge=0.0).df.copy()

    # Canonical fields
    df['game_date'] = pd.to_datetime(df['game_date'])
    df['correct'] = pd.to_numeric(df['correct'], errors='coerce')
    df = df[df['correct'].notna()].copy()
    df['correct'] = df['correct'].astype(int)
    df['direction'] = df['direction'].str.upper()
    df['abs_edge'] = df['edge'].abs()

    # Real odds for the picked side.
    #   OVER  -> real over_odds_median (clipped, fallback -115)
    #   UNDER -> real-vig median (-115); cache has no under quote.
    over_real = df.get('over_odds_median')
    if over_real is None:
        over_real = pd.Series(np.nan, index=df.index)
    df['side_odds'] = np.where(
        df['direction'] == 'OVER',
        over_real.map(clean_over_odds),
        float(FALLBACK_ODDS),
    )

    # Edge bucket (for empirical-HR p_win proxy)
    df['edge_bucket'] = pd.cut(df['abs_edge'], bins=EDGE_BINS,
                               labels=EDGE_LABELS, right=False)

    # Apply the best-bets edge floor and OVER/UNDER-only.
    df = df[(df['abs_edge'] >= min_edge) &
            (df['direction'].isin(['OVER', 'UNDER']))].copy()
    df = df.sort_values('game_date').reset_index(drop=True)
    return df


def build_pwin_map(train_df: pd.DataFrame) -> Dict[Tuple[str, str], Tuple[float, int]]:
    """Empirical HR per (edge_bucket, direction) from the TRAIN split only.

    Leak-free proxy for Kelly's p_win. Returns {(bucket, dir): (hr, n)}.
    Cells with < 30 graded picks fall back to the direction-level HR.
    """
    out: Dict[Tuple[str, str], Tuple[float, int]] = {}
    dir_hr = train_df.groupby('direction')['correct'].mean().to_dict()
    for (bucket, direction), g in train_df.groupby(['edge_bucket', 'direction'],
                                                   observed=True):
        n = len(g)
        hr = g['correct'].mean() if n >= 30 else dir_hr.get(direction, 0.5)
        out[(str(bucket), direction)] = (float(hr), int(n))
    return out


def pwin_for_row(row, pwin_map, dir_hr_fallback: Dict[str, float]) -> float:
    key = (str(row['edge_bucket']), row['direction'])
    if key in pwin_map:
        return pwin_map[key][0]
    return dir_hr_fallback.get(row['direction'], 0.5)


# ---------------------------------------------------------------------------
# Simulation engine
# ---------------------------------------------------------------------------
class BankrollSimulator:
    """Sequential bankroll walk over a set of picks with real per-pick odds.

    picks_df must carry: game_date, correct, side_odds, abs_edge, direction,
    and (for Kelly) p_win.
    """

    def __init__(self, picks_df: pd.DataFrame, starting_bankroll: float = STARTING_BANKROLL):
        self.picks = picks_df.sort_values('game_date').reset_index(drop=True)
        self.starting_bankroll = starting_bankroll

    # --- staking strategies -------------------------------------------------
    def simulate_flat(self, units_per_bet: float = 1.0) -> dict:
        return self._run(lambda row, br: units_per_bet)

    def simulate_kelly(self, fraction: float = 0.25, cap: float = KELLY_CAP) -> dict:
        """Fractional Kelly, capped at `cap` fraction of current bankroll.

        Stake is expressed in units where 1u == 1% of the STARTING bankroll,
        so it is directly comparable to flat 1u. Kelly fraction is applied to
        CURRENT bankroll (compounding), then capped.
        """
        def stake_fn(row, br):
            p = float(row['p_win'])
            f = kelly_fraction(p, row['side_odds']) * fraction
            f = min(f, cap)                       # cap fraction of bankroll
            stake_units = f * br                  # br is in the same unit scale
            return max(stake_units, 0.0)
        return self._run(stake_fn, allow_ruin=True)

    def simulate_edge_proportional(self, base_unit: float = 1.0,
                                   floor: float = 0.5, cap: float = 3.0,
                                   pivot: float = 5.0) -> dict:
        """Stake scales with edge above the floor. edge=5 -> 1u; capped [0.5,3]."""
        def stake_fn(row, br):
            stake = (row['abs_edge'] / pivot) * base_unit
            return float(np.clip(stake, floor, cap))
        return self._run(stake_fn)

    def simulate_ultra_tier(self, standard_units: float = 1.0,
                            ultra_units: float = 2.0) -> dict:
        """Higher stake on high-confidence (ultra) picks.

        Ultra = edge >= 6 (the durable UNDER money zone / OVER floor) AND a
        validated p_win >= 0.60. Everything else gets the standard unit.
        """
        def stake_fn(row, br):
            is_ultra = (row['abs_edge'] >= 6.0) and (float(row.get('p_win', 0)) >= 0.60)
            return ultra_units if is_ultra else standard_units
        return self._run(stake_fn)

    # --- engine -------------------------------------------------------------
    def _run(self, stake_fn, allow_ruin: bool = False) -> dict:
        bankroll = self.starting_bankroll
        history = [bankroll]
        bet_log = []
        for _, row in self.picks.iterrows():
            stake = stake_fn(row, bankroll)
            if stake > bankroll:
                stake = bankroll
            if stake <= 0:
                continue
            pl = pnl_for_bet(bool(row['correct']), stake, row['side_odds'])
            bankroll += pl
            history.append(bankroll)
            bet_log.append({
                'date': row['game_date'],
                'won': bool(row['correct']),
                'stake': stake,
                'pnl': pl,
                'bankroll': bankroll,
            })
            if allow_ruin and bankroll <= 0:
                break
        return self._metrics(history, bet_log)

    @staticmethod
    def _metrics(history: list, bet_log: list) -> dict:
        if not bet_log:
            return {'total_bets': 0, 'final_bankroll': history[0] if history else 0.0,
                    'roi': 0.0, 'total_pnl': 0.0, 'max_drawdown_pct': 0.0,
                    'sharpe': 0.0, 'hr': 0.0, 'total_wagered': 0.0,
                    'max_loss_streak': 0}
        bl = pd.DataFrame(bet_log)
        h = np.array(history)

        total_bets = len(bl)
        wins = int(bl['won'].sum())
        hr = wins / total_bets
        total_wagered = bl['stake'].sum()
        total_pnl = bl['pnl'].sum()
        roi = total_pnl / total_wagered if total_wagered > 0 else 0.0

        # Sharpe on per-bet returns (pnl / stake), annualization-agnostic.
        per_bet_ret = (bl['pnl'] / bl['stake']).replace([np.inf, -np.inf], np.nan).dropna()
        sharpe = (per_bet_ret.mean() / per_bet_ret.std()
                  if per_bet_ret.std() > 0 else 0.0)

        # Max drawdown (% of running peak)
        peak = h[0]
        max_dd = 0.0
        for v in h[1:]:
            peak = max(peak, v)
            if peak > 0:
                max_dd = max(max_dd, (peak - v) / peak)

        # Max losing streak
        max_loss_streak = cur = 0
        for won in bl['won']:
            if not won:
                cur += 1
                max_loss_streak = max(max_loss_streak, cur)
            else:
                cur = 0

        # Worst 30-bet rolling window (proxy for a cold month)
        worst_30 = (bl['pnl'].rolling(30).sum().min()
                    if len(bl) >= 30 else bl['pnl'].sum())

        return {
            'total_bets': total_bets,
            'wins': wins,
            'hr': hr,
            'total_wagered': total_wagered,
            'total_pnl': total_pnl,
            'roi': roi,
            'final_bankroll': h[-1],
            'sharpe': sharpe,
            'max_drawdown_pct': max_dd,
            'max_loss_streak': max_loss_streak,
            'worst_30bet': worst_30,
            'history': h,
        }


# ---------------------------------------------------------------------------
# Walk-forward driver
# ---------------------------------------------------------------------------
def attach_pwin_walkforward(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a leak-free p_win to every row using a season walk-forward.

    For each TEST season S, TRAIN = all rows from strictly-earlier seasons.
    p_win comes from the (edge_bucket x direction) empirical HR on TRAIN only.
    The earliest season (2021-22) has no prior -- its p_win is filled from the
    global direction HR of ALL OTHER seasons (still excludes its own rows).
    """
    df = df.copy()
    df['p_win'] = np.nan
    season_order = [s for s in ALL_SEASONS if s in df['season'].unique()]

    for i, season in enumerate(season_order):
        test_mask = df['season'] == season
        prior = df[df['season'].isin(season_order[:i])]
        if len(prior) >= 200:
            pwin_map = build_pwin_map(prior)
            dir_fb = prior.groupby('direction')['correct'].mean().to_dict()
        else:
            # No usable prior (first season): use all OTHER seasons' direction HR.
            other = df[df['season'] != season]
            pwin_map = build_pwin_map(other) if len(other) else {}
            dir_fb = other.groupby('direction')['correct'].mean().to_dict()

        sub = df[test_mask]
        df.loc[test_mask, 'p_win'] = sub.apply(
            lambda r: pwin_for_row(r, pwin_map, dir_fb), axis=1)

    df['p_win'] = df['p_win'].fillna(0.5)
    return df


def run_strategies(picks: pd.DataFrame) -> Dict[str, dict]:
    sim = BankrollSimulator(picks, STARTING_BANKROLL)
    return {
        'Flat 1u':          sim.simulate_flat(1.0),
        '1/4-Kelly (cap)':  sim.simulate_kelly(fraction=0.25),
        '1/2-Kelly (cap)':  sim.simulate_kelly(fraction=0.50),
        'Edge-Proportional': sim.simulate_edge_proportional(1.0),
        'Ultra-Tier (2u)':  sim.simulate_ultra_tier(1.0, 2.0),
    }


def monte_carlo_drawdown(picks: pd.DataFrame, strategy: str = 'flat',
                         n_sims: int = 5000, seed: int = 42) -> dict:
    """Bootstrap-resample the pick SEQUENCE and re-run the strategy to get a
    distribution of max drawdown + terminal ROI. Preserves the real per-pick
    odds/edge/p_win by resampling whole rows with replacement.
    """
    rng = np.random.default_rng(seed)
    rows = picks.reset_index(drop=True)
    n = len(rows)
    if n == 0:
        return {}
    dds, rois, finals = [], [], []
    idx_all = np.arange(n)
    for _ in range(n_sims):
        order = rng.choice(idx_all, size=n, replace=True)
        shuffled = rows.iloc[order].reset_index(drop=True)
        # Preserve a monotone date so the engine's sort is a no-op.
        shuffled = shuffled.assign(game_date=pd.date_range('2000-01-01', periods=n, freq='D'))
        sim = BankrollSimulator(shuffled, STARTING_BANKROLL)
        if strategy == 'flat':
            r = sim.simulate_flat(1.0)
        elif strategy == 'quarter_kelly':
            r = sim.simulate_kelly(fraction=0.25)
        elif strategy == 'half_kelly':
            r = sim.simulate_kelly(fraction=0.50)
        else:
            r = sim.simulate_flat(1.0)
        dds.append(r['max_drawdown_pct'])
        rois.append(r['roi'])
        finals.append(r['final_bankroll'])
    dds, rois, finals = map(np.array, (dds, rois, finals))
    return {
        'median_max_dd': np.median(dds),
        'p95_max_dd': np.percentile(dds, 95),
        'p99_max_dd': np.percentile(dds, 99),
        'median_roi': np.median(rois),
        'p5_roi': np.percentile(rois, 5),
        'p95_roi': np.percentile(rois, 95),
        'prob_positive': float((rois > 0).mean()),
        'prob_ruin_50': float((finals < STARTING_BANKROLL * 0.5).mean()),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_strategy_table(title: str, picks: pd.DataFrame):
    print(f"\n{title}")
    print(f"  picks={len(picks)}  HR={picks['correct'].mean():.1%}  "
          f"avg_edge={picks['abs_edge'].mean():.2f}  "
          f"median_odds={picks['side_odds'].median():.0f}")
    results = run_strategies(picks)
    header = (f"  {'Strategy':<19} {'Bets':>5} {'HR':>6} {'AvgStake':>9} "
              f"{'P&L':>9} {'ROI':>7} {'FinalBR':>9} {'Sharpe':>7} "
              f"{'MaxDD':>7} {'MaxL':>5}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, r in results.items():
        if r['total_bets'] == 0:
            print(f"  {name:<19} {'N/A':>5}")
            continue
        avg_stake = r['total_wagered'] / r['total_bets']
        print(f"  {name:<19} {r['total_bets']:>5} {r['hr']:>5.1%} "
              f"{avg_stake:>8.2f}u {r['total_pnl']:>+8.1f}u {r['roi']:>6.1%} "
              f"{r['final_bankroll']:>8.1f}u {r['sharpe']:>7.3f} "
              f"{r['max_drawdown_pct']:>6.1%} {r['max_loss_streak']:>5}")
    return results


def report_block(df: pd.DataFrame, seasons: List[str], label: str,
                 under_only: bool = False):
    sub = df[df['season'].isin(seasons)].copy()
    if under_only:
        sub = sub[sub['direction'] == 'UNDER']
    tag = f"{label}" + (" [UNDER-only]" if under_only else " [OVER+UNDER]")
    return print_strategy_table(f"### {tag}  seasons={seasons}", sub), sub


def verdict(flat: dict, qk: dict, label: str) -> str:
    if flat['total_bets'] == 0 or qk['total_bets'] == 0:
        return f"  {label}: insufficient data"
    roi_better = qk['roi'] >= flat['roi']
    dd_better = qk['max_drawdown_pct'] <= flat['max_drawdown_pct']
    # risk-adjusted = ROI per unit of max drawdown
    ra_flat = flat['roi'] / flat['max_drawdown_pct'] if flat['max_drawdown_pct'] > 0 else np.inf
    ra_qk = qk['roi'] / qk['max_drawdown_pct'] if qk['max_drawdown_pct'] > 0 else np.inf
    ra_better = ra_qk >= ra_flat
    v = ("BEATS flat" if (dd_better and roi_better) else
         "MIXED (see components)" if ra_better else
         "does NOT beat flat")
    return (f"  {label}: 1/4-Kelly {v} risk-adjusted | "
            f"ROI {qk['roi']:+.1%} vs {flat['roi']:+.1%} "
            f"({'+' if roi_better else '-'}) | "
            f"MaxDD {qk['max_drawdown_pct']:.1%} vs {flat['max_drawdown_pct']:.1%} "
            f"({'lower' if dd_better else 'higher'}) | "
            f"ROI/DD {ra_qk:.2f} vs {ra_flat:.2f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-edge', type=float, default=MIN_EDGE)
    ap.add_argument('--mc-sims', type=int, default=5000)
    args = ap.parse_args()

    print("=" * 92)
    print("NBA BANKROLL MANAGEMENT & BET-SIZING SIMULATION")
    print("Real odds (OVER: BettingPros median, clipped; UNDER: -115 real-vig proxy)")
    print("p_win = empirical HR of (edge-bucket x direction) on TRAIN split "
          "[PROXY -> swap for isotonic]")
    print("=" * 92)

    df = load_data(min_edge=args.min_edge)
    df = attach_pwin_walkforward(df)

    print(f"\nLoaded {len(df)} graded picks (edge>={args.min_edge}), "
          f"{df['season'].nunique()} seasons.")
    print(f"OVER {int((df['direction']=='OVER').sum())} / "
          f"UNDER {int((df['direction']=='UNDER').sum())}. "
          f"Overall HR {df['correct'].mean():.1%}.")
    print("\np_win proxy sanity (walk-forward, per season x direction mean):")
    print(df.groupby(['season', 'direction'])['p_win'].mean().round(3).to_string())

    # ------------------------------------------------------------------ blocks
    print("\n" + "=" * 92)
    print("HEADLINE: NON-ANOMALY SEASONS (2023-24 + 2024-25)")
    print("=" * 92)
    na_all, na_df = report_block(df, NON_ANOMALY_SEASONS, "NON-ANOMALY")
    na_under, _ = report_block(df, NON_ANOMALY_SEASONS, "NON-ANOMALY", under_only=True)

    print("\n" + "=" * 92)
    print(f"ANOMALY SEASON (reported separately): {ANOMALY_SEASON}")
    print("=" * 92)
    an_all, _ = report_block(df, [ANOMALY_SEASON], "ANOMALY-2025-26")
    an_under, _ = report_block(df, [ANOMALY_SEASON], "ANOMALY-2025-26", under_only=True)

    print("\n" + "=" * 92)
    print("POOLED (all 5 seasons)")
    print("=" * 92)
    pool_all, pool_df = report_block(df, ALL_SEASONS, "POOLED")
    pool_under, pool_under_df = report_block(df, ALL_SEASONS, "POOLED", under_only=True)

    # ------------------------------------------------------- Monte Carlo (DD)
    print("\n" + "=" * 92)
    print(f"MONTE-CARLO DRAWDOWN DISTRIBUTION ({args.mc_sims} bootstrap resamples)")
    print("Non-anomaly UNDER-only pick pool (the durable, bettable edge)")
    print("=" * 92)
    na_under_df = df[(df['season'].isin(NON_ANOMALY_SEASONS)) &
                     (df['direction'] == 'UNDER')].copy()
    print(f"\n  {'Strategy':<16} {'medDD':>7} {'p95DD':>7} {'p99DD':>7} "
          f"{'medROI':>8} {'p5ROI':>8} {'p95ROI':>8} {'P(+)':>6} {'P(ruin50)':>10}")
    print("  " + "-" * 82)
    for strat, key in [('Flat 1u', 'flat'), ('1/4-Kelly', 'quarter_kelly'),
                       ('1/2-Kelly', 'half_kelly')]:
        mc = monte_carlo_drawdown(na_under_df, key, n_sims=args.mc_sims)
        if not mc:
            print(f"  {strat:<16} N/A")
            continue
        print(f"  {strat:<16} {mc['median_max_dd']:>6.1%} {mc['p95_max_dd']:>6.1%} "
              f"{mc['p99_max_dd']:>6.1%} {mc['median_roi']:>7.1%} "
              f"{mc['p5_roi']:>7.1%} {mc['p95_roi']:>7.1%} "
              f"{mc['prob_positive']:>5.1%} {mc['prob_ruin_50']:>9.1%}")

    # ------------------------------------------------------------- verdicts
    print("\n" + "=" * 92)
    print("VERDICT: does 1/4-Kelly beat flat on RISK-ADJUSTED terms?")
    print("=" * 92)
    print(verdict(na_all['Flat 1u'], na_all['1/4-Kelly (cap)'],
                  "Non-anomaly, OVER+UNDER"))
    print(verdict(na_under['Flat 1u'], na_under['1/4-Kelly (cap)'],
                  "Non-anomaly, UNDER-only "))
    print(verdict(an_all['Flat 1u'], an_all['1/4-Kelly (cap)'],
                  "Anomaly 25-26, OVER+UNDER"))
    print(verdict(pool_all['Flat 1u'], pool_all['1/4-Kelly (cap)'],
                  "Pooled, OVER+UNDER      "))
    print(verdict(pool_under['Flat 1u'], pool_under['1/4-Kelly (cap)'],
                  "Pooled, UNDER-only      "))

    print("\nCAVEATS:")
    print("  * p_win is an EMPIRICAL-HR PROXY (train-split, edge-bucket x direction).")
    print("    Swap for the isotonic edge->p_win calibrator when available.")
    print("  * UNDER odds are priced at -115 (real-vig median); the local cache has")
    print("    no under-side quote. OVER uses real per-pick BettingPros odds.")
    print("  * Sizing's value here is DRAWDOWN/VARIANCE control, not a HR jump.")
    print("  * OVER edge is a 2025-26 anomaly -- trust the non-anomaly + UNDER rows.")
    print("=" * 92)


if __name__ == '__main__':
    main()
