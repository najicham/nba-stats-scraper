#!/usr/bin/env python3
"""
Phase A Analysis: Compare blacklist threshold, rolling window, and cadence sweeps.

Loads 16 experiment JSON files + 4 baselines and produces comparison tables.
"""

import json
import os
from collections import defaultdict
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"

# ── File definitions ──────────────────────────────────────────────────────────

BLACKLIST_SWEEP = {
    "BL35": {"2526": "replay_2526_bl35.json", "2425": "replay_2425_bl35.json"},
    "BL45": {"2526": None, "2425": "replay_2425_bl45.json"},
    "BL50": {"2526": None, "2425": "replay_2425_bl50.json"},
}

BLACKLIST_BASELINES = {
    "BL40 (baseline)": {"2526": "replay_2526_blacklist40.json", "2425": "replay_2425_blacklist40.json"},
}

ROLLING_SWEEP = {
    "Roll42": {"2526": "replay_2526_roll42_bl40.json", "2425": "replay_2425_roll42_bl40.json"},
    "Roll70": {"2526": "replay_2526_roll70_bl40.json", "2425": "replay_2425_roll70_bl40.json"},
    "Roll84": {"2526": "replay_2526_roll84_bl40.json", "2425": "replay_2425_roll84_bl40.json"},
}

ROLLING_BASELINES = {
    "Roll56+BL40 (baseline)": {"2526": "replay_2526_blacklist40.json", "2425": "replay_2425_blacklist40.json"},
    "Roll56 no-BL (baseline)": {"2526": "replay_2526_rolling56_v2.json", "2425": "replay_2425_rolling56_v2.json"},
}

CADENCE_SWEEP = {
    "Cad7": {"2526": "replay_2526_cad7_bl40.json", "2425": "replay_2425_cad7_bl40.json"},
    "Cad10": {"2526": "replay_2526_cad10_bl40.json", "2425": "replay_2425_cad10_bl40.json"},
    "Cad21": {"2526": "replay_2526_cad21_bl40.json", "2425": "replay_2425_cad21_bl40.json"},
}

CADENCE_BASELINES = {
    "Cad14+BL40 (baseline)": {"2526": "replay_2526_blacklist40.json", "2425": "replay_2425_blacklist40.json"},
}

# Key subsets to track
KEY_SUBSETS = ["xm_consensus_3plus", "xm_diverse_agreement", "q43_under_all"]

MODEL_DISPLAY = {
    "v9": "V9",
    "v12_noveg": "V12",
    "v9_q43": "V9Q43",
    "v9_q45": "V9Q45",
    "v12_noveg_q43": "V12Q43",
    "v12_noveg_q45": "V12Q45",
}


def load_result(filename):
    """Load a result JSON file and return parsed data."""
    path = RESULTS_DIR / filename
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def extract_metrics(data):
    """Extract key metrics from a result file."""
    if data is None:
        return None

    # Per-model aggregates from model_cycles
    model_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pushes": 0, "picks": 0, "pnl": 0})
    for cycle in data["model_cycles"]:
        mk = cycle["model_key"]
        model_stats[mk]["wins"] += cycle["wins"]
        model_stats[mk]["losses"] += cycle["losses"]
        model_stats[mk]["pushes"] += cycle.get("pushes", 0)
        model_stats[mk]["picks"] += cycle["picks"]
        model_stats[mk]["pnl"] += cycle["pnl"]

    # Compute HR per model
    for mk, stats in model_stats.items():
        total = stats["wins"] + stats["losses"]
        stats["hr"] = round(100.0 * stats["wins"] / total, 1) if total > 0 else 0.0

    # Total across all models
    total_wins = sum(s["wins"] for s in model_stats.values())
    total_losses = sum(s["losses"] for s in model_stats.values())
    total_picks = sum(s["picks"] for s in model_stats.values())
    total_pnl = sum(s["pnl"] for s in model_stats.values())
    total_decided = total_wins + total_losses
    total_hr = round(100.0 * total_wins / total_decided, 1) if total_decided > 0 else 0.0

    # Best model by HR (minimum 20 picks)
    best_model_hr = 0.0
    best_model_name = ""
    for mk, stats in model_stats.items():
        if stats["picks"] >= 20 and stats["hr"] > best_model_hr:
            best_model_hr = stats["hr"]
            best_model_name = MODEL_DISPLAY.get(mk, mk)

    # Subset metrics
    subset_metrics = {}
    for subset_name in KEY_SUBSETS:
        sr = data.get("subset_results", {}).get(subset_name)
        if sr:
            subset_metrics[subset_name] = {
                "hr": sr.get("total_hr", 0),
                "picks": sr.get("total_picks", 0),
                "pnl": sr.get("total_pnl", 0),
            }
        else:
            subset_metrics[subset_name] = {"hr": None, "picks": 0, "pnl": 0}

    # Top 5 subsets by P&L
    all_subsets = []
    for sname, sdata in data.get("subset_results", {}).items():
        all_subsets.append({
            "name": sname,
            "hr": sdata.get("total_hr", 0),
            "picks": sdata.get("total_picks", 0),
            "pnl": sdata.get("total_pnl", 0),
        })
    top5_subsets = sorted(all_subsets, key=lambda x: x["pnl"] or 0, reverse=True)[:5]

    # Config info
    config = data.get("config", {})

    return {
        "total_hr": total_hr,
        "total_n": total_picks,
        "total_pnl": total_pnl,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "model_stats": dict(model_stats),
        "best_model_hr": best_model_hr,
        "best_model_name": best_model_name,
        "subset_metrics": subset_metrics,
        "top5_subsets": top5_subsets,
        "config": config,
        "blacklist_skipped": config.get("filter_stats", {}).get("blacklist_skipped", 0),
    }


def fmt_hr(hr):
    """Format hit rate."""
    if hr is None:
        return "  N/A "
    return f"{hr:5.1f}%"


def fmt_pnl(pnl):
    """Format P&L."""
    if pnl is None:
        return "    N/A"
    return f"{pnl:+7.0f}"


def fmt_n(n):
    if n is None:
        return "  N/A"
    return f"{n:5d}"


def print_separator(width=130):
    print("=" * width)


def print_table(title, headers, rows, col_widths=None):
    """Print a formatted table."""
    print()
    print_separator()
    print(f"  {title}")
    print_separator()

    if col_widths is None:
        col_widths = [max(len(str(h)), max(len(str(r[i])) for r in rows) if rows else 0) + 2
                      for i, h in enumerate(headers)]

    # Header
    header_line = " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("-+-".join("-" * w for w in col_widths))

    # Rows
    for row in rows:
        row_line = " | ".join(str(row[i]).ljust(col_widths[i]) for i, _ in enumerate(headers))
        print(row_line)


def build_sweep_rows(sweep_dict, baselines_dict=None):
    """Build rows for a sweep table, loading data for both seasons."""
    all_entries = {}
    if baselines_dict:
        all_entries.update(baselines_dict)
    all_entries.update(sweep_dict)

    rows = []
    for variant_name, files in all_entries.items():
        for season_key in ["2526", "2425"]:
            filename = files.get(season_key)
            if filename is None:
                continue

            data = load_result(filename)
            if data is None:
                print(f"  WARNING: Missing file {filename}")
                continue

            metrics = extract_metrics(data)
            if metrics is None:
                continue

            season_label = "2025-26" if season_key == "2526" else "2024-25"
            xm3_hr = metrics["subset_metrics"]["xm_consensus_3plus"]["hr"]
            xm3_n = metrics["subset_metrics"]["xm_consensus_3plus"]["picks"]
            xm_div_hr = metrics["subset_metrics"]["xm_diverse_agreement"]["hr"]
            xm_div_n = metrics["subset_metrics"]["xm_diverse_agreement"]["picks"]
            q43_hr = metrics["subset_metrics"]["q43_under_all"]["hr"]
            q43_n = metrics["subset_metrics"]["q43_under_all"]["picks"]

            is_baseline = "baseline" in variant_name.lower()
            marker = " *" if is_baseline else ""

            rows.append({
                "variant": variant_name + marker,
                "season": season_label,
                "total_hr": fmt_hr(metrics["total_hr"]),
                "total_n": fmt_n(metrics["total_n"]),
                "total_pnl": fmt_pnl(metrics["total_pnl"]),
                "xm3_hr": f"{fmt_hr(xm3_hr)} (n={xm3_n})",
                "xm_div_hr": f"{fmt_hr(xm_div_hr)} (n={xm_div_n})",
                "q43_hr": f"{fmt_hr(q43_hr)} (n={q43_n})",
                "best_model": f"{metrics['best_model_name']} {fmt_hr(metrics['best_model_hr'])}",
                "bl_skipped": metrics["blacklist_skipped"],
                "_metrics": metrics,
                "_season_key": season_key,
                "_variant": variant_name,
            })

    return rows


def print_sweep_table(title, rows):
    """Print a sweep comparison table."""
    print()
    print_separator(160)
    print(f"  {title}")
    print_separator(160)

    headers = [
        "Variant", "Season", "Total HR", "Total N", "Total P&L",
        "xm_consensus_3plus", "xm_diverse_agree", "q43_under_all",
        "Best Model", "BL Skip"
    ]
    widths = [25, 8, 8, 7, 9, 18, 18, 18, 16, 8]

    header_line = " | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("-+-".join("-" * w for w in widths))

    for row in rows:
        vals = [
            row["variant"], row["season"], row["total_hr"], row["total_n"],
            row["total_pnl"], row["xm3_hr"], row["xm_div_hr"], row["q43_hr"],
            row["best_model"], str(row["bl_skipped"]),
        ]
        line = " | ".join(str(v).ljust(widths[i]) for i, v in enumerate(vals))
        print(line)


def print_combined_table(all_rows_by_table):
    """Print combined P&L table across both seasons."""
    print()
    print_separator(120)
    print("  TABLE 4: Combined P&L (Both Seasons)")
    print_separator(120)

    headers = ["Variant", "2025-26 P&L", "2025-26 HR", "2024-25 P&L", "2024-25 HR",
               "Combined P&L", "Combined HR", "Combined N"]
    widths = [28, 12, 10, 12, 10, 13, 12, 10]

    header_line = " | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("-+-".join("-" * w for w in widths))

    # Collect all variants across all tables
    variant_data = defaultdict(lambda: {"2526": None, "2425": None})

    for table_name, rows in all_rows_by_table.items():
        for row in rows:
            vname = row["_variant"]
            skey = row["_season_key"]
            variant_data[vname][skey] = row["_metrics"]

    # Sort variants
    for vname, seasons in sorted(variant_data.items()):
        pnl_2526 = seasons["2526"]["total_pnl"] if seasons["2526"] else None
        hr_2526 = seasons["2526"]["total_hr"] if seasons["2526"] else None
        n_2526 = seasons["2526"]["total_n"] if seasons["2526"] else 0
        w_2526 = seasons["2526"]["total_wins"] if seasons["2526"] else 0
        l_2526 = seasons["2526"]["total_losses"] if seasons["2526"] else 0

        pnl_2425 = seasons["2425"]["total_pnl"] if seasons["2425"] else None
        hr_2425 = seasons["2425"]["total_hr"] if seasons["2425"] else None
        n_2425 = seasons["2425"]["total_n"] if seasons["2425"] else 0
        w_2425 = seasons["2425"]["total_wins"] if seasons["2425"] else 0
        l_2425 = seasons["2425"]["total_losses"] if seasons["2425"] else 0

        combined_pnl = (pnl_2526 or 0) + (pnl_2425 or 0)
        combined_n = n_2526 + n_2425
        combined_w = w_2526 + w_2425
        combined_l = l_2526 + l_2425
        combined_decided = combined_w + combined_l
        combined_hr = round(100.0 * combined_w / combined_decided, 1) if combined_decided > 0 else 0.0

        vals = [
            vname,
            fmt_pnl(pnl_2526) if pnl_2526 is not None else "   N/A",
            fmt_hr(hr_2526) if hr_2526 is not None else " N/A",
            fmt_pnl(pnl_2425) if pnl_2425 is not None else "   N/A",
            fmt_hr(hr_2425) if hr_2425 is not None else " N/A",
            fmt_pnl(combined_pnl),
            fmt_hr(combined_hr),
            fmt_n(combined_n),
        ]
        line = " | ".join(str(v).ljust(widths[i]) for i, v in enumerate(vals))
        print(line)


def print_top_subsets(all_rows_by_table):
    """Print top subsets across all experiments."""
    print()
    print_separator(120)
    print("  TOP 5 SUBSETS PER EXPERIMENT")
    print_separator(120)

    for table_name, rows in all_rows_by_table.items():
        print(f"\n  --- {table_name} ---")
        for row in rows:
            m = row["_metrics"]
            vname = row["_variant"]
            season = row["season"]
            print(f"\n  {vname} ({season})  [Total P&L: {fmt_pnl(m['total_pnl'])}, HR: {fmt_hr(m['total_hr'])}]")
            for s in m["top5_subsets"]:
                print(f"    {s['name']:30s}  HR={fmt_hr(s['hr'])}  N={s['picks']:4d}  P&L={fmt_pnl(s['pnl'])}")


def print_per_model_summary(all_rows_by_table):
    """Print per-model HR comparison for key variants."""
    print()
    print_separator(140)
    print("  PER-MODEL BREAKDOWN (HR% / N picks)")
    print_separator(140)

    model_order = ["v9", "v12_noveg", "v9_q43", "v9_q45", "v12_noveg_q43", "v12_noveg_q45"]
    headers = ["Variant", "Season"] + [MODEL_DISPLAY[m] for m in model_order]
    widths = [28, 8] + [14] * 6

    header_line = " | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("-+-".join("-" * w for w in widths))

    for table_name, rows in all_rows_by_table.items():
        for row in rows:
            m = row["_metrics"]
            vals = [row["_variant"], row["season"]]
            for mk in model_order:
                ms = m["model_stats"].get(mk)
                if ms and ms["picks"] > 0:
                    vals.append(f"{ms['hr']:5.1f}% / {ms['picks']}")
                else:
                    vals.append("N/A")
            line = " | ".join(str(v).ljust(widths[i]) for i, v in enumerate(vals))
            print(line)


def main():
    print("\n" + "=" * 80)
    print("  PHASE A ANALYSIS: Season Replay Parameter Sweeps")
    print("=" * 80)

    # ── TABLE 1: Blacklist Threshold Sweep ────────────────────────────────
    bl_rows = build_sweep_rows(BLACKLIST_SWEEP, BLACKLIST_BASELINES)
    print_sweep_table("TABLE 1: Blacklist Threshold Sweep (BL35 / BL40* / BL45 / BL50)", bl_rows)

    # ── TABLE 2: Rolling Window Sweep ─────────────────────────────────────
    roll_rows = build_sweep_rows(ROLLING_SWEEP, ROLLING_BASELINES)
    print_sweep_table("TABLE 2: Rolling Window Sweep (Roll42 / Roll56* / Roll70 / Roll84)", roll_rows)

    # ── TABLE 3: Cadence Sweep ────────────────────────────────────────────
    cad_rows = build_sweep_rows(CADENCE_SWEEP, CADENCE_BASELINES)
    print_sweep_table("TABLE 3: Cadence Sweep (Cad7 / Cad10 / Cad14* / Cad21)", cad_rows)

    # ── TABLE 4: Combined P&L ─────────────────────────────────────────────
    all_tables = {
        "Blacklist": bl_rows,
        "Rolling": roll_rows,
        "Cadence": cad_rows,
    }
    print_combined_table(all_tables)

    # ── Top Subsets ───────────────────────────────────────────────────────
    print_top_subsets(all_tables)

    # ── Per-Model Breakdown ───────────────────────────────────────────────
    print_per_model_summary(all_tables)

    # ── Summary / Best Parameters ─────────────────────────────────────────
    print()
    print_separator(80)
    print("  SUMMARY: Best Parameters by Combined P&L")
    print_separator(80)

    # Collect combined P&L for each variant
    variant_combined = defaultdict(lambda: {"pnl": 0, "wins": 0, "losses": 0, "n": 0, "category": ""})
    categories = {"Blacklist": bl_rows, "Rolling": roll_rows, "Cadence": cad_rows}
    for cat, rows in categories.items():
        for row in rows:
            m = row["_metrics"]
            vname = row["_variant"]
            variant_combined[vname]["pnl"] += m["total_pnl"]
            variant_combined[vname]["wins"] += m["total_wins"]
            variant_combined[vname]["losses"] += m["total_losses"]
            variant_combined[vname]["n"] += m["total_n"]
            variant_combined[vname]["category"] = cat

    ranked = sorted(variant_combined.items(), key=lambda x: x[1]["pnl"], reverse=True)
    print(f"\n  {'Rank':<5} {'Variant':<28} {'Category':<12} {'Combined P&L':>12} {'Combined HR':>12} {'N':>6}")
    print(f"  {'-'*5} {'-'*28} {'-'*12} {'-'*12} {'-'*12} {'-'*6}")
    for i, (vname, stats) in enumerate(ranked, 1):
        decided = stats["wins"] + stats["losses"]
        hr = round(100.0 * stats["wins"] / decided, 1) if decided > 0 else 0.0
        print(f"  {i:<5} {vname:<28} {stats['category']:<12} {stats['pnl']:>+12.0f} {hr:>11.1f}% {stats['n']:>6}")

    print()


if __name__ == "__main__":
    main()
