#!/usr/bin/env python3
"""
Analyze Season Replay Results — Executive Summary

Reads the JSON output from season_replay_full.py and produces a 7-section
executive summary with actionable recommendations.

Usage:
    PYTHONPATH=. python ml/experiments/analyze_replay_results.py \
        ml/experiments/results/replay_20260217.json

    # Save report to file
    PYTHONPATH=. python ml/experiments/analyze_replay_results.py \
        ml/experiments/results/replay_20260217.json \
        --save ml/experiments/results/analysis_report.txt

Session 280 - Full Season Replay Analysis
"""

import argparse
import json
import sys
from typing import Optional

STAKE = 110
WIN_PAYOUT = 100
BREAKEVEN_HR = 52.4


def load_results(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def hr(wins, losses):
    graded = wins + losses
    if graded == 0:
        return None
    return round(wins / graded * 100, 1)


def roi(pnl, wins, losses):
    risked = (wins + losses) * STAKE
    if risked == 0:
        return None
    return round(pnl / risked * 100, 1)


def fmt_hr(val):
    return f"{val:.1f}%" if val is not None else "N/A"


def fmt_roi(val):
    return f"{val:+.1f}%" if val is not None else "N/A"


def fmt_pnl(val):
    return f"${val:+,.0f}"


# =============================================================================
# Section 1: Subset Rankings
# =============================================================================

def section_subset_rankings(data: dict, out):
    out.append("=" * 85)
    out.append("1. SUBSET RANKINGS — Sorted by P&L")
    out.append("=" * 85)
    out.append("")

    subsets = data.get('subset_results', {})
    if not subsets:
        out.append("  No subset data found.")
        return

    ranked = sorted(subsets.items(), key=lambda x: x[1].get('total_pnl', 0), reverse=True)

    header = f"{'Rank':>4} {'Subset':<28} {'Picks':>5} {'W-L':>9} {'HR%':>7} {'P&L':>9} {'ROI':>7}  Flag"
    out.append(header)
    out.append("-" * len(header))

    prioritize = []
    remove = []

    for i, (name, s) in enumerate(ranked, 1):
        picks = s.get('total_picks', 0)
        if picks == 0:
            continue
        w = s.get('total_wins', 0)
        l = s.get('total_losses', 0)
        h = hr(w, l)
        r = roi(s.get('total_pnl', 0), w, l)
        pnl_val = s.get('total_pnl', 0)

        flag = ""
        if h is not None:
            if h >= 60:
                flag = "PRIORITIZE"
                prioritize.append(name)
            elif h < BREAKEVEN_HR:
                flag = "REMOVE"
                remove.append(name)

        wl = f"{w}-{l}"
        out.append(f"{i:>4} {name:<28} {picks:>5} {wl:>9} {fmt_hr(h):>7} {fmt_pnl(pnl_val):>9} {fmt_roi(r):>7}  {flag}")

    out.append("")
    out.append(f"  PRIORITIZE ({len(prioritize)}): {', '.join(prioritize)}")
    out.append(f"  REMOVE ({len(remove)}): {', '.join(remove)}")
    out.append("")


# =============================================================================
# Section 2: Model Comparison
# =============================================================================

def section_model_comparison(data: dict, out):
    out.append("=" * 85)
    out.append("2. MODEL COMPARISON — Overall Performance")
    out.append("=" * 85)
    out.append("")

    cycles = data.get('model_cycles', [])
    if not cycles:
        out.append("  No model cycle data found.")
        return

    models = {}
    for c in cycles:
        if c.get('skipped'):
            continue
        mk = c['model_key']
        if mk not in models:
            models[mk] = {'name': c['model_name'], 'picks': 0, 'wins': 0,
                          'losses': 0, 'pushes': 0, 'pnl': 0.0, 'maes': [],
                          'cycles': 0}
        m = models[mk]
        m['picks'] += c['picks']
        m['wins'] += c['wins']
        m['losses'] += c['losses']
        m['pushes'] += c.get('pushes', 0)
        m['pnl'] += c['pnl']
        m['cycles'] += 1
        if c.get('mae') is not None:
            m['maes'].append(c['mae'])

    header = f"{'Model':<18} {'Picks':>5} {'W-L':>9} {'HR%':>7} {'P&L':>9} {'ROI':>7} {'MAE':>6} {'Cycles':>6}"
    out.append(header)
    out.append("-" * len(header))

    for mk, m in sorted(models.items(), key=lambda x: x[1]['pnl'], reverse=True):
        h = hr(m['wins'], m['losses'])
        r = roi(m['pnl'], m['wins'], m['losses'])
        avg_mae = round(sum(m['maes']) / len(m['maes']), 2) if m['maes'] else None
        mae_str = f"{avg_mae:.2f}" if avg_mae else "N/A"
        wl = f"{m['wins']}-{m['losses']}"
        out.append(f"{m['name']:<18} {m['picks']:>5} {wl:>9} {fmt_hr(h):>7} "
                   f"{fmt_pnl(m['pnl']):>9} {fmt_roi(r):>7} {mae_str:>6} {m['cycles']:>6}")

    out.append("")

    # Key insights
    best_hr_model = max(models.items(), key=lambda x: hr(x[1]['wins'], x[1]['losses']) or 0)
    best_pnl_model = max(models.items(), key=lambda x: x[1]['pnl'])
    most_picks = max(models.items(), key=lambda x: x[1]['picks'])

    out.append(f"  Best HR: {best_hr_model[1]['name']} ({fmt_hr(hr(best_hr_model[1]['wins'], best_hr_model[1]['losses']))})")
    out.append(f"  Best P&L: {best_pnl_model[1]['name']} ({fmt_pnl(best_pnl_model[1]['pnl'])})")
    out.append(f"  Most volume: {most_picks[1]['name']} ({most_picks[1]['picks']} picks)")
    out.append("")


# =============================================================================
# Section 3: Decay Analysis
# =============================================================================

def section_decay_analysis(data: dict, out):
    out.append("=" * 85)
    out.append("3. DECAY ANALYSIS — HR by Model Age Bucket")
    out.append("=" * 85)
    out.append("")

    cycles = data.get('model_cycles', [])
    if not cycles:
        out.append("  No cycle data.")
        return

    from datetime import date

    age_buckets = [
        ("0-7d", 0, 7),
        ("8-14d", 8, 14),
        ("15-21d", 15, 21),
        ("22-28d", 22, 28),
        ("29+d", 29, 999),
    ]

    # Aggregate across all models
    bucket_data = {b[0]: {"wins": 0, "graded": 0} for b in age_buckets}

    for c in cycles:
        if c.get('skipped') or c['picks'] == 0:
            continue
        train_end = date.fromisoformat(c['train_end'])
        eval_start = date.fromisoformat(c['eval_start'])
        eval_end = date.fromisoformat(c['eval_end'])
        avg_eval = eval_start + (eval_end - eval_start) / 2
        model_age = (avg_eval - train_end).days

        for bname, bmin, bmax in age_buckets:
            if bmin <= model_age <= bmax:
                bucket_data[bname]["wins"] += c['wins']
                bucket_data[bname]["graded"] += c['wins'] + c['losses']
                break

    header = " | ".join(f"{b[0]:>14}" for b in age_buckets)
    out.append(f"{'All Models':16} | {header}")
    out.append("-" * 100)

    parts = []
    for bname, _, _ in age_buckets:
        bd = bucket_data[bname]
        if bd["graded"] > 0:
            h = bd["wins"] / bd["graded"] * 100
            parts.append(f"{h:>6.1f}% (N={bd['graded']:>4})")
        else:
            parts.append(f"{'--':>14}")
    out.append(f"{'':16} | " + " | ".join(parts))

    out.append("")
    out.append(f"  Breakeven: {BREAKEVEN_HR}%")

    # Check if 14-day cadence holds
    week1 = bucket_data.get("0-7d", {"graded": 0})
    week2 = bucket_data.get("8-14d", {"graded": 0})
    if week1["graded"] > 0 and week2["graded"] > 0:
        w1_hr = week1["wins"] / week1["graded"] * 100
        w2_hr = week2["wins"] / week2["graded"] * 100
        decay = w1_hr - w2_hr
        out.append(f"  Week 1 -> Week 2 decay: {decay:+.1f}pp")
        if w2_hr >= BREAKEVEN_HR:
            out.append(f"  14-day cadence HOLDS: Week 2 at {w2_hr:.1f}% (above breakeven)")
        else:
            out.append(f"  14-day cadence FAILS: Week 2 at {w2_hr:.1f}% (below breakeven)")
    elif week1["graded"] > 0:
        w1_hr = week1["wins"] / week1["graded"] * 100
        out.append(f"  Only Week 1 data available: {w1_hr:.1f}%")
        out.append(f"  Note: All cycles have avg model age in 0-7d bucket (short eval windows)")
    out.append("")


# =============================================================================
# Section 4: Signal Simulation
# =============================================================================

def section_signal_simulation(data: dict, out):
    out.append("=" * 85)
    out.append("4. SIGNAL SIMULATION — Which signals beat breakeven?")
    out.append("=" * 85)
    out.append("")

    dims = data.get('dimensions', {})
    if not dims:
        out.append("  No dimensional data.")
        return

    # Extract Signal Simulation entries
    signals = {}
    for key, d in dims.items():
        if d.get('dimension') == 'Signal Simulation':
            cat = d['category']
            if cat not in signals:
                signals[cat] = {'wins': 0, 'losses': 0, 'pushes': 0, 'pnl': 0.0}
            s = signals[cat]
            s['wins'] += d['wins']
            s['losses'] += d['losses']
            s['pushes'] += d.get('pushes', 0)
            s['pnl'] += d['pnl']

    if not signals:
        out.append("  No signal simulation data found.")
        return

    # Sort by HR descending
    signal_list = []
    for name, s in signals.items():
        h = hr(s['wins'], s['losses'])
        graded = s['wins'] + s['losses']
        r = roi(s['pnl'], s['wins'], s['losses'])
        signal_list.append((name, graded, h, s['pnl'], r))

    signal_list.sort(key=lambda x: (x[2] or 0), reverse=True)

    header = f"{'Signal':<26} {'N':>5} {'HR%':>7} {'P&L':>9} {'ROI':>7}  Verdict"
    out.append(header)
    out.append("-" * len(header))

    above_be = []
    below_be = []

    for name, n, h, pnl_val, r in signal_list:
        if n == 0:
            continue
        verdict = ""
        if h is not None:
            if h >= 60:
                verdict = "STRONG"
                above_be.append(name)
            elif h >= BREAKEVEN_HR:
                verdict = "viable"
                above_be.append(name)
            else:
                verdict = "REMOVE"
                below_be.append(name)
        out.append(f"{name:<26} {n:>5} {fmt_hr(h):>7} {fmt_pnl(pnl_val):>9} {fmt_roi(r):>7}  {verdict}")

    out.append("")
    out.append(f"  Above breakeven ({len(above_be)}): {', '.join(above_be)}")
    out.append(f"  Below breakeven ({len(below_be)}): {', '.join(below_be)}")
    out.append("")


# =============================================================================
# Section 5: Cross-Model Consensus
# =============================================================================

def section_cross_model(data: dict, out):
    out.append("=" * 85)
    out.append("5. CROSS-MODEL CONSENSUS — Is consensus worth the complexity?")
    out.append("=" * 85)
    out.append("")

    subsets = data.get('subset_results', {})
    xm_subsets = {k: v for k, v in subsets.items() if k.startswith('xm_')}

    if not xm_subsets:
        out.append("  No cross-model subset data found.")
        return

    header = f"{'Subset':<32} {'Picks':>5} {'W-L':>9} {'HR%':>7} {'P&L':>9} {'ROI':>7}"
    out.append(header)
    out.append("-" * len(header))

    for name, s in sorted(xm_subsets.items(), key=lambda x: x[1].get('total_pnl', 0), reverse=True):
        picks = s.get('total_picks', 0)
        if picks == 0:
            continue
        w = s.get('total_wins', 0)
        l = s.get('total_losses', 0)
        h = hr(w, l)
        r = roi(s.get('total_pnl', 0), w, l)
        pnl_val = s.get('total_pnl', 0)
        wl = f"{w}-{l}"
        out.append(f"{name:<32} {picks:>5} {wl:>9} {fmt_hr(h):>7} {fmt_pnl(pnl_val):>9} {fmt_roi(r):>7}")

    out.append("")

    # Compare top xm subset vs best single-model subset
    best_xm = max(xm_subsets.items(), key=lambda x: x[1].get('total_pnl', 0))
    best_xm_hr = hr(best_xm[1].get('total_wins', 0), best_xm[1].get('total_losses', 0))

    single_model_subsets = {k: v for k, v in subsets.items()
                           if not k.startswith('xm_') and not k.endswith('_all_picks')}
    if single_model_subsets:
        best_single = max(single_model_subsets.items(), key=lambda x: x[1].get('total_pnl', 0))
        best_single_hr = hr(best_single[1].get('total_wins', 0), best_single[1].get('total_losses', 0))

        out.append(f"  Best xm: {best_xm[0]} — {fmt_hr(best_xm_hr)} HR, {fmt_pnl(best_xm[1].get('total_pnl', 0))}")
        out.append(f"  Best single-model: {best_single[0]} — {fmt_hr(best_single_hr)} HR, {fmt_pnl(best_single[1].get('total_pnl', 0))}")
        out.append("")

        xm_pnl = best_xm[1].get('total_pnl', 0)
        single_pnl = best_single[1].get('total_pnl', 0)
        if xm_pnl > single_pnl:
            out.append(f"  Verdict: Cross-model consensus adds value (+{fmt_pnl(xm_pnl - single_pnl)} over best single)")
        else:
            out.append(f"  Verdict: Single-model subsets outperform ({fmt_pnl(single_pnl - xm_pnl)} advantage)")
    out.append("")


# =============================================================================
# Section 6: Dimensional Deep Dives
# =============================================================================

def section_dimensions(data: dict, out):
    out.append("=" * 85)
    out.append("6. DIMENSIONAL DEEP DIVES")
    out.append("=" * 85)
    out.append("")

    dims = data.get('dimensions', {})
    if not dims:
        out.append("  No dimensional data.")
        return

    # Group by dimension, aggregate across models
    dim_agg = {}  # dim -> cat -> {wins, losses, pnl}
    for key, d in dims.items():
        dn = d['dimension']
        cn = d['category']
        if dn == 'Signal Simulation':
            continue  # Covered in section 4
        if dn not in dim_agg:
            dim_agg[dn] = {}
        if cn not in dim_agg[dn]:
            dim_agg[dn][cn] = {'wins': 0, 'losses': 0, 'pushes': 0, 'pnl': 0.0}
        a = dim_agg[dn][cn]
        a['wins'] += d['wins']
        a['losses'] += d['losses']
        a['pushes'] += d.get('pushes', 0)
        a['pnl'] += d['pnl']

    for dim_name in ['Player Tier', 'Direction', 'Tier x Direction', 'Line Range', 'Edge Bucket']:
        if dim_name not in dim_agg:
            continue

        out.append(f"  --- {dim_name} ---")
        header = f"  {'Category':<24} {'N':>5} {'HR%':>7} {'P&L':>9} {'ROI':>7}"
        out.append(header)

        cats = dim_agg[dim_name]
        for cn, a in sorted(cats.items(), key=lambda x: x[1]['pnl'], reverse=True):
            graded = a['wins'] + a['losses']
            if graded == 0:
                continue
            h = hr(a['wins'], a['losses'])
            r = roi(a['pnl'], a['wins'], a['losses'])
            out.append(f"  {cn:<24} {graded:>5} {fmt_hr(h):>7} {fmt_pnl(a['pnl']):>9} {fmt_roi(r):>7}")
        out.append("")

    # Key pattern callouts
    out.append("  Key Patterns:")

    # Check Bench UNDER
    tier_dir = dim_agg.get('Tier x Direction', {})
    bench_under = tier_dir.get('Bench UNDER', {})
    bench_over = tier_dir.get('Bench OVER', {})
    if bench_under.get('wins', 0) + bench_under.get('losses', 0) > 0:
        bu_hr = hr(bench_under['wins'], bench_under['losses'])
        bo_hr = hr(bench_over['wins'], bench_over['losses']) if bench_over.get('wins', 0) + bench_over.get('losses', 0) > 0 else None
        out.append(f"  - Bench UNDER: {fmt_hr(bu_hr)} HR, {fmt_pnl(bench_under['pnl'])}")
        if bo_hr:
            out.append(f"  - Bench OVER:  {fmt_hr(bo_hr)} HR, {fmt_pnl(bench_over['pnl'])} (compare)")

    # Check 20-24.5 dead zone
    line_range = dim_agg.get('Line Range', {})
    dead_zone = line_range.get('20-24.5', {})
    if dead_zone.get('wins', 0) + dead_zone.get('losses', 0) > 0:
        dz_hr = hr(dead_zone['wins'], dead_zone['losses'])
        out.append(f"  - 20-24.5 line range: {fmt_hr(dz_hr)} HR, {fmt_pnl(dead_zone['pnl'])} {'(dead zone confirmed)' if dz_hr and dz_hr < BREAKEVEN_HR else '(not a dead zone)'}")

    # Check 25-29.5
    mid_star = line_range.get('25-29.5', {})
    if mid_star.get('wins', 0) + mid_star.get('losses', 0) > 0:
        ms_hr = hr(mid_star['wins'], mid_star['losses'])
        out.append(f"  - 25-29.5 line range: {fmt_hr(ms_hr)} HR, {fmt_pnl(mid_star['pnl'])}")

    # Direction analysis
    direction = dim_agg.get('Direction', {})
    over_d = direction.get('OVER', {})
    under_d = direction.get('UNDER', {})
    if over_d and under_d:
        over_hr = hr(over_d.get('wins', 0), over_d.get('losses', 0))
        under_hr = hr(under_d.get('wins', 0), under_d.get('losses', 0))
        out.append(f"  - OVER: {fmt_hr(over_hr)} HR, {fmt_pnl(over_d['pnl'])} (N={over_d['wins'] + over_d['losses']})")
        out.append(f"  - UNDER: {fmt_hr(under_hr)} HR, {fmt_pnl(under_d['pnl'])} (N={under_d['wins'] + under_d['losses']})")

    out.append("")


# =============================================================================
# Section 7: Actionable Recommendations
# =============================================================================

def section_recommendations(data: dict, out):
    out.append("=" * 85)
    out.append("7. ACTIONABLE RECOMMENDATIONS")
    out.append("=" * 85)
    out.append("")

    subsets = data.get('subset_results', {})
    dims = data.get('dimensions', {})
    cycles = data.get('model_cycles', [])

    recommendations = []

    # --- Subset recommendations ---
    for name, s in subsets.items():
        w = s.get('total_wins', 0)
        l = s.get('total_losses', 0)
        h = hr(w, l)
        picks = s.get('total_picks', 0)
        pnl_val = s.get('total_pnl', 0)

        if picks < 10:
            continue

        if h is not None and h >= 65 and picks >= 20:
            recommendations.append(
                f"PROMOTE: '{name}' — {fmt_hr(h)} HR, {fmt_pnl(pnl_val)}, N={picks}. "
                f"Consider promoting to production subset."
            )
        elif h is not None and h < 50 and picks >= 20:
            recommendations.append(
                f"REMOVE: '{name}' — {fmt_hr(h)} HR, {fmt_pnl(pnl_val)}, N={picks}. "
                f"Losing money, consider disabling."
            )

    # --- Model recommendations ---
    models = {}
    for c in cycles:
        if c.get('skipped'):
            continue
        mk = c['model_key']
        if mk not in models:
            models[mk] = {'name': c['model_name'], 'wins': 0, 'losses': 0, 'pnl': 0.0}
        models[mk]['wins'] += c['wins']
        models[mk]['losses'] += c['losses']
        models[mk]['pnl'] += c['pnl']

    best_model = max(models.items(), key=lambda x: x[1]['pnl'])
    worst_model = min(models.items(), key=lambda x: x[1]['pnl'])
    worst_hr = hr(worst_model[1]['wins'], worst_model[1]['losses'])
    if worst_hr is not None and worst_hr < BREAKEVEN_HR:
        recommendations.append(
            f"WARN: Model '{worst_model[1]['name']}' is below breakeven "
            f"({fmt_hr(worst_hr)} HR, {fmt_pnl(worst_model[1]['pnl'])}). "
            f"Consider reducing its weight in consensus or removing from production."
        )

    recommendations.append(
        f"CHAMPION: '{best_model[1]['name']}' has highest P&L "
        f"({fmt_pnl(best_model[1]['pnl'])}). Prioritize this model family."
    )

    # --- Cross-model recommendations ---
    xm_subsets = {k: v for k, v in subsets.items() if k.startswith('xm_')}
    profitable_xm = []
    for name, s in xm_subsets.items():
        w = s.get('total_wins', 0)
        l = s.get('total_losses', 0)
        h_val = hr(w, l)
        if h_val and h_val >= 60 and s.get('total_picks', 0) >= 15:
            profitable_xm.append((name, h_val, s.get('total_pnl', 0)))
    if profitable_xm:
        for name, h_val, pnl_val in profitable_xm:
            recommendations.append(
                f"CONSENSUS: '{name}' delivers {fmt_hr(h_val)} HR, {fmt_pnl(pnl_val)}. "
                f"Worth keeping in production."
            )

    # --- Dimensional recommendations ---
    dim_agg = {}
    for key, d in dims.items():
        dn = d['dimension']
        cn = d['category']
        if dn not in dim_agg:
            dim_agg[dn] = {}
        if cn not in dim_agg[dn]:
            dim_agg[dn][cn] = {'wins': 0, 'losses': 0, 'pnl': 0.0}
        a = dim_agg[dn][cn]
        a['wins'] += d['wins']
        a['losses'] += d['losses']
        a['pnl'] += d['pnl']

    # Check direction imbalance
    direction = dim_agg.get('Direction', {})
    over_d = direction.get('OVER', {})
    under_d = direction.get('UNDER', {})
    if over_d and under_d:
        over_hr_val = hr(over_d.get('wins', 0), over_d.get('losses', 0))
        under_hr_val = hr(under_d.get('wins', 0), under_d.get('losses', 0))
        if over_hr_val and under_hr_val:
            diff = over_hr_val - under_hr_val
            if abs(diff) > 10:
                better = "OVER" if diff > 0 else "UNDER"
                recommendations.append(
                    f"DIRECTION: {better} significantly outperforms "
                    f"(OVER {fmt_hr(over_hr_val)} vs UNDER {fmt_hr(under_hr_val)}, "
                    f"delta {abs(diff):.1f}pp). Consider directional weighting."
                )

    # Check line range dead zones
    lr = dim_agg.get('Line Range', {})
    for range_name, a in lr.items():
        graded = a['wins'] + a['losses']
        if graded < 50:
            continue
        h_val = hr(a['wins'], a['losses'])
        if h_val and h_val < 51:
            recommendations.append(
                f"DEAD ZONE: Line range {range_name} at {fmt_hr(h_val)} HR (N={graded}). "
                f"Consider adding as a smart filter to block these picks."
            )

    # Print all recommendations
    for i, rec in enumerate(recommendations, 1):
        out.append(f"  {i}. {rec}")

    out.append("")
    out.append(f"  Total recommendations: {len(recommendations)}")
    out.append("")


# =============================================================================
# Main
# =============================================================================

def generate_report(data: dict) -> str:
    out = []
    config = data.get('config', {})

    out.append("=" * 85)
    out.append("SEASON REPLAY EXECUTIVE SUMMARY")
    out.append(f"Season: {config.get('season_start', '?')} to {config.get('season_end', '?')}")
    out.append(f"Cadence: {config.get('cadence_days', '?')} days")
    out.append(f"Models: {', '.join(config.get('models', []))}")
    out.append(f"Min Edge: {config.get('min_edge', 3.0)}")
    out.append("=" * 85)
    out.append("")

    section_subset_rankings(data, out)
    section_model_comparison(data, out)
    section_decay_analysis(data, out)
    section_signal_simulation(data, out)
    section_cross_model(data, out)
    section_dimensions(data, out)
    section_recommendations(data, out)

    return "\n".join(out)


# =============================================================================
# Cross-Season Comparison Mode
# =============================================================================

def compare_model_stability(data1: dict, data2: dict, out):
    """Section 1: Model stability across two seasons."""
    out.append("=" * 95)
    out.append("COMPARISON 1: MODEL STABILITY")
    out.append("=" * 95)
    out.append("")

    def _agg_models(data):
        models = {}
        for c in data.get('model_cycles', []):
            if c.get('skipped'):
                continue
            mk = c['model_key']
            if mk not in models:
                models[mk] = {'name': c['model_name'], 'wins': 0, 'losses': 0, 'pnl': 0.0}
            models[mk]['wins'] += c['wins']
            models[mk]['losses'] += c['losses']
            models[mk]['pnl'] += c['pnl']
        return models

    m1 = _agg_models(data1)
    m2 = _agg_models(data2)
    all_keys = sorted(set(m1.keys()) | set(m2.keys()))

    s1 = data1.get('config', {})
    s2 = data2.get('config', {})
    label1 = f"{s1.get('season_start', '?')[:4]}-{s1.get('season_end', '?')[:4]}"
    label2 = f"{s2.get('season_start', '?')[:4]}-{s2.get('season_end', '?')[:4]}"

    header = (f"{'Model':<16} | {label1 + ' HR':>10} {label1 + ' P&L':>12} | "
              f"{label2 + ' HR':>10} {label2 + ' P&L':>12} | {'Stable?':>8}")
    out.append(header)
    out.append("-" * len(header))

    for mk in all_keys:
        d1 = m1.get(mk, {})
        d2 = m2.get(mk, {})
        hr1 = hr(d1.get('wins', 0), d1.get('losses', 0))
        hr2 = hr(d2.get('wins', 0), d2.get('losses', 0))
        pnl1 = d1.get('pnl', 0)
        pnl2 = d2.get('pnl', 0)
        name = d1.get('name', d2.get('name', mk))

        stable = "YES" if (hr1 and hr2 and hr1 >= BREAKEVEN_HR and hr2 >= BREAKEVEN_HR
                           and abs(hr1 - hr2) < 10) else "NO"
        out.append(f"{name:<16} | {fmt_hr(hr1):>10} {fmt_pnl(pnl1):>12} | "
                   f"{fmt_hr(hr2):>10} {fmt_pnl(pnl2):>12} | {stable:>8}")

    out.append("")


def compare_subset_survival(data1: dict, data2: dict, out):
    """Section 2: Which subsets are profitable in BOTH seasons?"""
    out.append("=" * 95)
    out.append("COMPARISON 2: SUBSET SURVIVAL (profitable in BOTH seasons?)")
    out.append("=" * 95)
    out.append("")

    s1 = data1.get('subset_results', {})
    s2 = data2.get('subset_results', {})
    all_names = sorted(set(s1.keys()) | set(s2.keys()))

    survivors = []
    one_season = []
    neither = []

    header = (f"{'Subset':<28} | {'S1 HR':>7} {'S1 P&L':>9} {'S1 N':>5} | "
              f"{'S2 HR':>7} {'S2 P&L':>9} {'S2 N':>5} | {'Verdict':>10}")
    out.append(header)
    out.append("-" * len(header))

    for name in all_names:
        d1 = s1.get(name, {})
        d2 = s2.get(name, {})
        w1, l1 = d1.get('total_wins', 0), d1.get('total_losses', 0)
        w2, l2 = d2.get('total_wins', 0), d2.get('total_losses', 0)
        hr1 = hr(w1, l1)
        hr2 = hr(w2, l2)
        pnl1 = d1.get('total_pnl', 0)
        pnl2 = d2.get('total_pnl', 0)
        n1 = w1 + l1
        n2 = w2 + l2

        if n1 < 5 and n2 < 5:
            continue

        both_above = (hr1 and hr1 >= BREAKEVEN_HR and hr2 and hr2 >= BREAKEVEN_HR)
        verdict = "SURVIVOR" if both_above else "1-season" if (
            (hr1 and hr1 >= BREAKEVEN_HR) or (hr2 and hr2 >= BREAKEVEN_HR)
        ) else "NEITHER"

        if both_above:
            survivors.append(name)
        elif verdict == "1-season":
            one_season.append(name)
        else:
            neither.append(name)

        out.append(f"{name:<28} | {fmt_hr(hr1):>7} {fmt_pnl(pnl1):>9} {n1:>5} | "
                   f"{fmt_hr(hr2):>7} {fmt_pnl(pnl2):>9} {n2:>5} | {verdict:>10}")

    out.append("")
    out.append(f"  Survivors ({len(survivors)}): {', '.join(survivors)}")
    out.append(f"  One-season ({len(one_season)}): {', '.join(one_season)}")
    out.append(f"  Neither ({len(neither)}): {', '.join(neither)}")
    out.append("")


def compare_direction_stability(data1: dict, data2: dict, out):
    """Section 3: OVER/UNDER HR side by side."""
    out.append("=" * 95)
    out.append("COMPARISON 3: DIRECTION STABILITY")
    out.append("=" * 95)
    out.append("")

    def _get_direction(data):
        dims = data.get('dimensions', {})
        result = {}
        for key, d in dims.items():
            if d.get('dimension') == 'Direction':
                cat = d['category']
                if cat not in result:
                    result[cat] = {'wins': 0, 'losses': 0, 'pnl': 0.0}
                result[cat]['wins'] += d['wins']
                result[cat]['losses'] += d['losses']
                result[cat]['pnl'] += d['pnl']
        return result

    dir1 = _get_direction(data1)
    dir2 = _get_direction(data2)

    s1 = data1.get('config', {})
    s2 = data2.get('config', {})
    label1 = f"{s1.get('season_start', '?')[:4]}-{s1.get('season_end', '?')[:4]}"
    label2 = f"{s2.get('season_start', '?')[:4]}-{s2.get('season_end', '?')[:4]}"

    header = f"{'Direction':<10} | {label1:>12} {'N':>5} | {label2:>12} {'N':>5} | {'Delta':>7} {'Stable?':>8}"
    out.append(header)
    out.append("-" * len(header))

    for d in ['OVER', 'UNDER']:
        d1 = dir1.get(d, {})
        d2 = dir2.get(d, {})
        hr1 = hr(d1.get('wins', 0), d1.get('losses', 0))
        hr2 = hr(d2.get('wins', 0), d2.get('losses', 0))
        n1 = d1.get('wins', 0) + d1.get('losses', 0)
        n2 = d2.get('wins', 0) + d2.get('losses', 0)
        delta = f"{hr1 - hr2:+.1f}pp" if hr1 and hr2 else "N/A"
        stable = "YES" if (hr1 and hr2 and abs(hr1 - hr2) < 10) else "NO"
        out.append(f"{d:<10} | {fmt_hr(hr1):>12} {n1:>5} | {fmt_hr(hr2):>12} {n2:>5} | "
                   f"{delta:>7} {stable:>8}")

    out.append("")


def compare_line_range_stability(data1: dict, data2: dict, out):
    """Section 4: Line range HR side by side."""
    out.append("=" * 95)
    out.append("COMPARISON 4: LINE RANGE STABILITY")
    out.append("=" * 95)
    out.append("")

    def _get_line_range(data):
        dims = data.get('dimensions', {})
        result = {}
        for key, d in dims.items():
            if d.get('dimension') == 'Line Range':
                cat = d['category']
                if cat not in result:
                    result[cat] = {'wins': 0, 'losses': 0, 'pnl': 0.0}
                result[cat]['wins'] += d['wins']
                result[cat]['losses'] += d['losses']
                result[cat]['pnl'] += d['pnl']
        return result

    lr1 = _get_line_range(data1)
    lr2 = _get_line_range(data2)
    all_ranges = ['5-9.5', '10-14.5', '15-19.5', '20-24.5', '25-29.5', '30+']

    header = f"{'Line Range':<12} | {'S1 HR':>7} {'S1 N':>5} | {'S2 HR':>7} {'S2 N':>5} | {'Delta':>8} {'Stable?':>8}"
    out.append(header)
    out.append("-" * len(header))

    for rng in all_ranges:
        d1 = lr1.get(rng, {})
        d2 = lr2.get(rng, {})
        hr1 = hr(d1.get('wins', 0), d1.get('losses', 0))
        hr2 = hr(d2.get('wins', 0), d2.get('losses', 0))
        n1 = d1.get('wins', 0) + d1.get('losses', 0)
        n2 = d2.get('wins', 0) + d2.get('losses', 0)
        delta = f"{hr1 - hr2:+.1f}pp" if hr1 and hr2 else "N/A"
        stable = "YES" if (hr1 and hr2 and abs(hr1 - hr2) < 10
                           and hr1 >= BREAKEVEN_HR and hr2 >= BREAKEVEN_HR) else "NO"
        out.append(f"{rng:<12} | {fmt_hr(hr1):>7} {n1:>5} | {fmt_hr(hr2):>7} {n2:>5} | "
                   f"{delta:>8} {stable:>8}")

    out.append("")


def compare_adaptive_vs_fixed(data1: dict, data2: dict, out):
    """Section 5: If both runs have adaptive data, show the delta."""
    out.append("=" * 95)
    out.append("COMPARISON 5: ADAPTIVE vs FIXED ANALYSIS")
    out.append("=" * 95)
    out.append("")

    cfg1 = data1.get('config', {})
    cfg2 = data2.get('config', {})

    out.append(f"  File 1: adaptive={cfg1.get('adaptive', False)}, "
               f"rolling_train={cfg1.get('rolling_train_days', 'expanding')}, "
               f"lookback={cfg1.get('lookback_days', 28)}d")
    out.append(f"  File 2: adaptive={cfg2.get('adaptive', False)}, "
               f"rolling_train={cfg2.get('rolling_train_days', 'expanding')}, "
               f"lookback={cfg2.get('lookback_days', 28)}d")
    out.append("")

    # Compare adaptive logs if present
    for label, data in [("File 1", data1), ("File 2", data2)]:
        alog = data.get('adaptive_log', {})
        if alog:
            out.append(f"  {label} adaptive decisions:")
            for cycle_key, d in sorted(alog.items(), key=lambda x: int(x[0])):
                decisions = []
                if not d.get('include_over', True):
                    decisions.append("SUPPRESS OVER")
                if not d.get('include_under', True):
                    decisions.append("SUPPRESS UNDER")
                if d.get('disable_rel_edge_filter', False):
                    decisions.append("DISABLE rel_edge filter")
                halved = [k for k, v in d.get('model_weights', {}).items() if v < 1.0]
                if halved:
                    decisions.append(f"HALVE models: {', '.join(halved)}")
                if decisions:
                    out.append(f"    Cycle {cycle_key}: {'; '.join(decisions)}")
            out.append("")

    # Compare total P&L
    def _total_pnl(data):
        total = 0
        for c in data.get('model_cycles', []):
            if not c.get('skipped'):
                total += c.get('pnl', 0)
        return total

    pnl1 = _total_pnl(data1)
    pnl2 = _total_pnl(data2)
    out.append(f"  Total P&L: File 1 = {fmt_pnl(pnl1)}, File 2 = {fmt_pnl(pnl2)}")
    out.append(f"  Delta: {fmt_pnl(pnl1 - pnl2)} (File 1 - File 2)")
    out.append("")


def generate_comparison_report(data1: dict, data2: dict) -> str:
    """Generate cross-season comparison report."""
    out = []

    cfg1 = data1.get('config', {})
    cfg2 = data2.get('config', {})

    out.append("=" * 95)
    out.append("CROSS-SEASON COMPARISON REPORT")
    out.append(f"File 1: {cfg1.get('season_start', '?')} to {cfg1.get('season_end', '?')}"
               f" (adaptive={cfg1.get('adaptive', False)}, "
               f"rolling_train={cfg1.get('rolling_train_days', 'expanding')})")
    out.append(f"File 2: {cfg2.get('season_start', '?')} to {cfg2.get('season_end', '?')}"
               f" (adaptive={cfg2.get('adaptive', False)}, "
               f"rolling_train={cfg2.get('rolling_train_days', 'expanding')})")
    out.append("=" * 95)
    out.append("")

    compare_model_stability(data1, data2, out)
    compare_subset_survival(data1, data2, out)
    compare_direction_stability(data1, data2, out)
    compare_line_range_stability(data1, data2, out)
    compare_adaptive_vs_fixed(data1, data2, out)

    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze season replay results",
    )
    parser.add_argument("json_file", help="Path to replay JSON results")
    parser.add_argument("--save", default=None, help="Save report to file")
    parser.add_argument("--compare", default=None,
                        help="Second JSON file for cross-season comparison")
    args = parser.parse_args()

    data = load_results(args.json_file)

    if args.compare:
        data2 = load_results(args.compare)
        report = generate_comparison_report(data, data2)
    else:
        report = generate_report(data)

    print(report)

    if args.save:
        with open(args.save, 'w') as f:
            f.write(report)
        print(f"\nReport saved to {args.save}")


if __name__ == "__main__":
    main()
