#!/usr/bin/env python3
"""Season replay: per-model pipeline vs old single-pipeline.

Replays the full BB pipeline for each game date using the new per-model
architecture, grades against actuals, and compares to the old system's
actual picks stored in signal_best_bets_picks.

Usage:
    PYTHONPATH=. python bin/replay_per_model_pipeline.py
    PYTHONPATH=. python bin/replay_per_model_pipeline.py --start 2026-02-01 --end 2026-03-07
    PYTHONPATH=. python bin/replay_per_model_pipeline.py --write-candidates  # Write to model_bb_candidates BQ table
"""

import argparse
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from google.cloud import bigquery

from ml.signals.per_model_pipeline import run_all_model_pipelines
from ml.signals.pipeline_merger import merge_model_pipelines

logger = logging.getLogger(__name__)

# Replay constants
DEFAULT_START = '2026-01-09'
DEFAULT_END = '2026-03-07'
PNL_WIN = 1.0       # Profit on a win at -110
PNL_LOSS = -1.1     # Loss on a loss at -110


@dataclass
class DayResult:
    """Result for a single game day."""
    game_date: str
    # New system (per-model pipeline)
    new_picks: List[Dict] = field(default_factory=list)
    new_wins: int = 0
    new_losses: int = 0
    new_ungraded: int = 0
    new_pnl: float = 0.0
    new_models_contributing: int = 0
    new_total_candidates: int = 0
    # Old system (from signal_best_bets_picks)
    old_picks: List[Dict] = field(default_factory=list)
    old_wins: int = 0
    old_losses: int = 0
    old_pnl: float = 0.0
    # Per-model pipeline breakdown
    per_model_candidates: Dict[str, int] = field(default_factory=dict)
    per_model_selected: Dict[str, int] = field(default_factory=dict)
    # Overlap analysis
    overlap_count: int = 0    # Picks in both old and new
    new_only_count: int = 0   # Picks in new but not old
    old_only_count: int = 0   # Picks in old but not new
    # Timing
    duration_sec: float = 0.0
    # All candidates for BQ write
    all_candidates: List[Dict] = field(default_factory=list)


@dataclass
class ReplayResult:
    """Aggregate results across all dates."""
    days: List[DayResult] = field(default_factory=list)

    @property
    def new_total(self) -> int:
        return sum(d.new_wins + d.new_losses for d in self.days)

    @property
    def new_wins(self) -> int:
        return sum(d.new_wins for d in self.days)

    @property
    def new_hr(self) -> float:
        t = self.new_total
        return self.new_wins / t * 100 if t > 0 else 0.0

    @property
    def new_pnl(self) -> float:
        return sum(d.new_pnl for d in self.days)

    @property
    def old_total(self) -> int:
        return sum(d.old_wins + d.old_losses for d in self.days)

    @property
    def old_wins(self) -> int:
        return sum(d.old_wins for d in self.days)

    @property
    def old_hr(self) -> float:
        t = self.old_total
        return self.old_wins / t * 100 if t > 0 else 0.0

    @property
    def old_pnl(self) -> float:
        return sum(d.old_pnl for d in self.days)


def get_game_dates(bq_client: bigquery.Client, start: str, end: str) -> List[str]:
    """Get dates that have graded predictions (games were played and graded)."""
    query = f"""
    SELECT DISTINCT game_date
    FROM nba_predictions.prediction_accuracy
    WHERE game_date >= '{start}'
      AND game_date <= '{end}'
      AND has_prop_line = TRUE
      AND recommendation IN ('OVER', 'UNDER')
      AND prediction_correct IS NOT NULL
    ORDER BY game_date
    """
    rows = list(bq_client.query(query).result())
    return [str(row.game_date) for row in rows]


def get_old_system_picks(bq_client: bigquery.Client, game_date: str) -> List[Dict]:
    """Fetch the old system's actual BB picks for comparison."""
    query = f"""
    SELECT
      bb.player_lookup,
      bb.game_id,
      bb.system_id,
      bb.recommendation,
      bb.edge,
      bb.composite_score,
      bb.signal_count,
      bb.real_signal_count,
      bb.signal_rescued,
      bb.source_model_id,
      bb.source_model_family,
      pa.prediction_correct,
      pa.predicted_points,
      pa.line_value,
      pa.actual_points
    FROM nba_predictions.signal_best_bets_picks bb
    LEFT JOIN nba_predictions.prediction_accuracy pa
      ON bb.player_lookup = pa.player_lookup
      AND bb.game_date = pa.game_date
      AND bb.system_id = pa.system_id
      AND pa.has_prop_line = TRUE
      AND pa.recommendation IN ('OVER', 'UNDER')
    WHERE bb.game_date = '{game_date}'
    """
    rows = list(bq_client.query(query).result())
    return [dict(row) for row in rows]


def grade_new_picks(
    bq_client: bigquery.Client,
    picks: List[Dict],
    game_date: str,
) -> List[Dict]:
    """Grade new system picks against prediction_accuracy."""
    if not picks:
        return []

    player_lookups = list({p['player_lookup'] for p in picks})
    # Build lookup strings for SQL IN clause
    lookup_str = ', '.join(f"'{pl}'" for pl in player_lookups)

    query = f"""
    SELECT
      player_lookup,
      game_id,
      system_id,
      recommendation,
      prediction_correct,
      predicted_points,
      line_value,
      actual_points
    FROM nba_predictions.prediction_accuracy
    WHERE game_date = '{game_date}'
      AND player_lookup IN ({lookup_str})
      AND has_prop_line = TRUE
      AND recommendation IN ('OVER', 'UNDER')
      AND prediction_correct IS NOT NULL
    """
    rows = list(bq_client.query(query).result())

    # Build outcome lookup: (player_lookup, system_id, recommendation) → prediction_correct
    outcomes = {}
    for row in rows:
        key = (row.player_lookup, row.system_id, row.recommendation)
        outcomes[key] = {
            'prediction_correct': row.prediction_correct,
            'actual_points': row.actual_points,
            'predicted_points': row.predicted_points,
            'line_value': row.line_value,
        }

    # Grade each pick
    graded = []
    for pick in picks:
        key = (
            pick['player_lookup'],
            pick.get('system_id', pick.get('source_pipeline', '')),
            pick['recommendation'],
        )
        outcome = outcomes.get(key, {})
        pick['prediction_correct'] = outcome.get('prediction_correct')
        pick['actual_points'] = outcome.get('actual_points')
        graded.append(pick)

    return graded


def replay_date(
    bq_client: bigquery.Client,
    game_date: str,
    combo_registry: Optional[Dict] = None,
) -> DayResult:
    """Replay one date through per-model pipeline and compare to old system."""
    start_time = time.time()
    result = DayResult(game_date=game_date)

    # --- Run new per-model pipeline ---
    try:
        model_results, shared_ctx = run_all_model_pipelines(
            bq_client, game_date,
            include_disabled=True,
        )
    except Exception as e:
        logger.error(f"[{game_date}] Pipeline failed: {e}")
        return result

    if not model_results:
        logger.warning(f"[{game_date}] No model results")
        return result

    # Extract candidates per model — tag source_pipeline BEFORE merge
    # (BUG FIX: merger reads source_pipeline for pipeline agreement)
    model_candidates = {}
    for system_id, pr in model_results.items():
        for cand in pr.candidates:
            cand['source_pipeline'] = system_id
            cand['game_date'] = game_date
        model_candidates[system_id] = pr.candidates
        result.per_model_candidates[system_id] = len(pr.candidates)

    # Merge
    merged_picks, merge_summary = merge_model_pipelines(model_candidates)
    result.new_picks = merged_picks
    result.new_models_contributing = merge_summary.get('models_contributing', 0)
    result.new_total_candidates = merge_summary.get('total_candidates', 0)

    # Track per-model selected
    for pick in merged_picks:
        src = pick.get('source_pipeline', 'unknown')
        result.per_model_selected[src] = result.per_model_selected.get(src, 0) + 1

    # Collect ALL candidates (selected + rejected) for BQ write
    for system_id, pr in model_results.items():
        result.all_candidates.extend(pr.candidates)
    # Also tag merge metadata on all candidates
    selected_players = {p['player_lookup'] for p in merged_picks}
    for cand in result.all_candidates:
        if cand['player_lookup'] in selected_players:
            # Find the matching merged pick for metadata
            for mp in merged_picks:
                if mp['player_lookup'] == cand['player_lookup'] and mp.get('source_pipeline') == cand.get('source_pipeline'):
                    cand['was_selected'] = True
                    cand['merge_rank'] = mp.get('merge_rank')
                    cand['selection_reason'] = 'selected'
                    break
            else:
                cand['was_selected'] = False
                cand['selection_reason'] = 'player_dedup'
        else:
            cand.setdefault('was_selected', False)
            cand.setdefault('selection_reason', 'not_selected')

    # Grade new picks
    graded_new = grade_new_picks(bq_client, merged_picks, game_date)
    for pick in graded_new:
        if pick.get('prediction_correct') is True:
            result.new_wins += 1
            result.new_pnl += PNL_WIN
        elif pick.get('prediction_correct') is False:
            result.new_losses += 1
            result.new_pnl += PNL_LOSS
        else:
            result.new_ungraded += 1

    # --- Fetch old system picks ---
    old_picks = get_old_system_picks(bq_client, game_date)
    result.old_picks = old_picks
    for pick in old_picks:
        if pick.get('prediction_correct') is True:
            result.old_wins += 1
            result.old_pnl += PNL_WIN
        elif pick.get('prediction_correct') is False:
            result.old_losses += 1
            result.old_pnl += PNL_LOSS

    # --- Overlap analysis ---
    new_player_set = {(p['player_lookup'], p['recommendation']) for p in merged_picks}
    old_player_set = {(p['player_lookup'], p['recommendation']) for p in old_picks}
    result.overlap_count = len(new_player_set & old_player_set)
    result.new_only_count = len(new_player_set - old_player_set)
    result.old_only_count = len(old_player_set - new_player_set)

    result.duration_sec = time.time() - start_time
    return result


def write_candidates_to_bq(
    bq_client: bigquery.Client,
    all_candidates: List[Dict],
    game_date: str,
):
    """Write all candidates to model_bb_candidates BQ table."""
    table_id = 'nba-props-platform.nba_predictions.model_bb_candidates'

    # Delete existing rows for this date
    delete_query = f"""
    DELETE FROM `{table_id}`
    WHERE game_date = '{game_date}'
    """
    bq_client.query(delete_query).result()

    if not all_candidates:
        return

    rows = []
    for cand in all_candidates:
        row = {
            'game_date': game_date,
            'player_lookup': cand.get('player_lookup', ''),
            'game_id': cand.get('game_id', ''),
            'system_id': cand.get('system_id', cand.get('source_pipeline', '')),
            'source_pipeline': cand.get('source_pipeline', ''),
            'source_model_family': cand.get('source_model_family', ''),
            'recommendation': cand.get('recommendation', ''),
            'predicted_points': cand.get('predicted_points'),
            'line_value': cand.get('line_value'),
            'edge': cand.get('edge'),
            'confidence_score': cand.get('confidence_score'),
            'composite_score': cand.get('composite_score'),
            'signal_count': cand.get('signal_count'),
            'real_signal_count': cand.get('real_signal_count'),
            'signal_tags': cand.get('signal_tags', []),
            'signal_rescued': cand.get('signal_rescued', False),
            'rescue_signal': cand.get('rescue_signal'),
            'was_selected': cand.get('was_selected', False),
            'selection_reason': cand.get('selection_reason', ''),
            'merge_rank': cand.get('merge_rank'),
            'pipeline_agreement_count': cand.get('pipeline_agreement_count'),
            'algorithm_version': 'v443_per_model_pipelines',
            'created_at': datetime.utcnow().isoformat(),
        }
        rows.append(row)

    errors = bq_client.insert_rows_json(table_id, rows)
    if errors:
        logger.error(f"[{game_date}] BQ write errors: {errors[:3]}")
    else:
        logger.info(f"[{game_date}] Wrote {len(rows)} candidates to model_bb_candidates")


def print_day_summary(day: DayResult):
    """Print single-day result."""
    new_total = day.new_wins + day.new_losses
    old_total = day.old_wins + day.old_losses
    new_hr = day.new_wins / new_total * 100 if new_total > 0 else 0
    old_hr = day.old_wins / old_total * 100 if old_total > 0 else 0
    delta_hr = new_hr - old_hr

    new_over = sum(1 for p in day.new_picks if p.get('recommendation') == 'OVER')
    new_under = len(day.new_picks) - new_over

    print(f"  {day.game_date}: "
          f"NEW {day.new_wins}-{day.new_losses} ({new_hr:.0f}%) "
          f"OLD {day.old_wins}-{day.old_losses} ({old_hr:.0f}%) "
          f"Δ{delta_hr:+.0f}pp | "
          f"picks={len(day.new_picks)} (O:{new_over}/U:{new_under}) "
          f"models={day.new_models_contributing} "
          f"cands={day.new_total_candidates} "
          f"overlap={day.overlap_count} "
          f"[{day.duration_sec:.1f}s]")


def print_full_report(replay: ReplayResult):
    """Print comprehensive comparison report."""
    print("\n" + "=" * 80)
    print("SEASON REPLAY: Per-Model Pipeline vs Old Single Pipeline")
    print("=" * 80)

    # --- Headline numbers ---
    print(f"\n{'Metric':<30} {'NEW (per-model)':<25} {'OLD (single)':<25} {'Delta':<15}")
    print("-" * 95)
    print(f"{'Total picks':<30} {replay.new_total:<25} {replay.old_total:<25} {replay.new_total - replay.old_total:+d}")
    print(f"{'Wins':<30} {replay.new_wins:<25} {replay.old_wins:<25} {replay.new_wins - replay.old_wins:+d}")
    print(f"{'Hit Rate':<30} {replay.new_hr:<24.1f}% {replay.old_hr:<24.1f}% {replay.new_hr - replay.old_hr:+.1f}pp")
    print(f"{'P&L (units)':<30} {replay.new_pnl:<24.1f}  {replay.old_pnl:<24.1f}  {replay.new_pnl - replay.old_pnl:+.1f}")

    # --- Direction breakdown ---
    print(f"\n--- Direction Breakdown ---")
    for direction in ['OVER', 'UNDER']:
        new_dir = [d for day in replay.days for d in day.new_picks
                    if d.get('recommendation') == direction and d.get('prediction_correct') is not None]
        old_dir = [d for day in replay.days for d in day.old_picks
                    if d.get('recommendation') == direction and d.get('prediction_correct') is not None]
        new_w = sum(1 for p in new_dir if p.get('prediction_correct'))
        old_w = sum(1 for p in old_dir if p.get('prediction_correct'))
        new_t = len(new_dir)
        old_t = len(old_dir)
        new_hr = new_w / new_t * 100 if new_t > 0 else 0
        old_hr = old_w / old_t * 100 if old_t > 0 else 0
        print(f"  {direction:<10} NEW: {new_w}-{new_t - new_w} ({new_hr:.1f}%)  "
              f"OLD: {old_w}-{old_t - old_w} ({old_hr:.1f}%)  "
              f"Δ{new_hr - old_hr:+.1f}pp")

    # --- Edge tier breakdown ---
    print(f"\n--- Edge Tier Breakdown ---")
    edge_tiers = [('3-4', 3, 4), ('4-6', 4, 6), ('6+', 6, 100)]
    all_new_graded = [p for day in replay.days for p in day.new_picks if p.get('prediction_correct') is not None]
    all_old_graded = [p for day in replay.days for p in day.old_picks if p.get('prediction_correct') is not None]
    print(f"  {'Tier':<8} {'NEW W-L (HR)':<22} {'OLD W-L (HR)':<22} {'Delta':<10}")
    for label, lo, hi in edge_tiers:
        new_t = [p for p in all_new_graded if lo <= abs(p.get('edge', 0)) < hi]
        old_t = [p for p in all_old_graded if lo <= abs(p.get('edge', 0)) < hi]
        nw = sum(1 for p in new_t if p['prediction_correct'])
        ow = sum(1 for p in old_t if p['prediction_correct'])
        nhr = nw / len(new_t) * 100 if new_t else 0
        ohr = ow / len(old_t) * 100 if old_t else 0
        print(f"  {label:<8} {nw}-{len(new_t)-nw} ({nhr:.0f}%){'':<10} "
              f"{ow}-{len(old_t)-ow} ({ohr:.0f}%){'':<10} "
              f"Δ{nhr - ohr:+.0f}pp")

    # --- Line tier breakdown ---
    print(f"\n--- Line Tier × Direction ---")
    line_tiers = [('bench', 0, 12), ('role', 12, 18), ('starter', 18, 25), ('star', 25, 100)]
    print(f"  {'Tier':<10} {'Dir':<6} {'NEW W-L (HR)':<20} {'OLD W-L (HR)':<20}")
    for tier_label, lo, hi in line_tiers:
        for direction in ['OVER', 'UNDER']:
            new_t = [p for p in all_new_graded
                     if lo <= (p.get('line_value') or 0) < hi and p.get('recommendation') == direction]
            old_t = [p for p in all_old_graded
                     if lo <= (p.get('line_value') or 0) < hi and p.get('recommendation') == direction]
            if not new_t and not old_t:
                continue
            nw = sum(1 for p in new_t if p['prediction_correct'])
            ow = sum(1 for p in old_t if p['prediction_correct'])
            nhr = nw / len(new_t) * 100 if new_t else 0
            ohr = ow / len(old_t) * 100 if old_t else 0
            print(f"  {tier_label:<10} {direction:<6} "
                  f"{nw}-{len(new_t)-nw} ({nhr:.0f}%){'':<8} "
                  f"{ow}-{len(old_t)-ow} ({ohr:.0f}%)")

    # --- Per-model pipeline contribution ---
    print(f"\n--- Per-Model Pipeline Contribution ---")
    model_wins = defaultdict(int)
    model_losses = defaultdict(int)
    model_candidates_total = defaultdict(int)
    for day in replay.days:
        for cand_model, count in day.per_model_candidates.items():
            model_candidates_total[cand_model] += count
        for pick in day.new_picks:
            src = pick.get('source_pipeline', 'unknown')
            if pick.get('prediction_correct') is True:
                model_wins[src] += 1
            elif pick.get('prediction_correct') is False:
                model_losses[src] += 1

    all_models = set(model_wins.keys()) | set(model_losses.keys())
    print(f"  {'Model':<50} {'Cands':<8} {'Sel':<6} {'W':<5} {'L':<5} {'HR':<8}")
    print(f"  {'-' * 82}")
    for model in sorted(all_models, key=lambda m: model_wins[m] + model_losses[m], reverse=True):
        w = model_wins[model]
        l = model_losses[model]
        t = w + l
        hr = w / t * 100 if t > 0 else 0
        cands = model_candidates_total.get(model, 0)
        sel = w + l
        print(f"  {model[:50]:<50} {cands:<8} {sel:<6} {w:<5} {l:<5} {hr:<7.1f}%")

    # --- Overlap analysis ---
    print(f"\n--- Pick Overlap Analysis ---")
    total_overlap = sum(d.overlap_count for d in replay.days)
    total_new_only = sum(d.new_only_count for d in replay.days)
    total_old_only = sum(d.old_only_count for d in replay.days)
    print(f"  Picks in BOTH systems: {total_overlap}")
    print(f"  NEW only (added):      {total_new_only}")
    print(f"  OLD only (dropped):    {total_old_only}")

    # Grade the overlap vs new-only vs old-only
    overlap_wins = 0
    overlap_total = 0
    new_only_wins = 0
    new_only_total = 0
    old_only_wins = 0
    old_only_total = 0

    for day in replay.days:
        old_set = {(p['player_lookup'], p['recommendation']) for p in day.old_picks}
        for pick in day.new_picks:
            key = (pick['player_lookup'], pick['recommendation'])
            correct = pick.get('prediction_correct')
            if correct is None:
                continue
            if key in old_set:
                overlap_total += 1
                if correct:
                    overlap_wins += 1
            else:
                new_only_total += 1
                if correct:
                    new_only_wins += 1

        new_set = {(p['player_lookup'], p['recommendation']) for p in day.new_picks}
        for pick in day.old_picks:
            key = (pick['player_lookup'], pick['recommendation'])
            correct = pick.get('prediction_correct')
            if correct is None:
                continue
            if key not in new_set:
                old_only_total += 1
                if correct:
                    old_only_wins += 1

    if overlap_total:
        print(f"  Overlap HR:     {overlap_wins}/{overlap_total} = {overlap_wins/overlap_total*100:.1f}%")
    if new_only_total:
        print(f"  NEW-only HR:    {new_only_wins}/{new_only_total} = {new_only_wins/new_only_total*100:.1f}%")
    if old_only_total:
        print(f"  OLD-only HR:    {old_only_wins}/{old_only_total} = {old_only_wins/old_only_total*100:.1f}%")

    # --- Winning/losing day comparison ---
    print(f"\n--- Day-Level Comparison ---")
    new_better = 0
    old_better = 0
    tied = 0
    for day in replay.days:
        new_t = day.new_wins + day.new_losses
        old_t = day.old_wins + day.old_losses
        if new_t == 0 and old_t == 0:
            continue
        new_hr = day.new_wins / new_t if new_t > 0 else 0
        old_hr = day.old_wins / old_t if old_t > 0 else 0
        if new_hr > old_hr:
            new_better += 1
        elif old_hr > new_hr:
            old_better += 1
        else:
            tied += 1
    print(f"  Days NEW better:  {new_better}")
    print(f"  Days OLD better:  {old_better}")
    print(f"  Days tied:        {tied}")

    # --- Pipeline agreement analysis ---
    print(f"\n--- Pipeline Agreement Analysis ---")
    agreement_buckets = defaultdict(lambda: {'wins': 0, 'total': 0})
    for day in replay.days:
        for pick in day.new_picks:
            agree = pick.get('pipeline_agreement_count', 1)
            correct = pick.get('prediction_correct')
            if correct is None:
                continue
            bucket = min(agree, 5)  # Cap at 5+
            agreement_buckets[bucket]['total'] += 1
            if correct:
                agreement_buckets[bucket]['wins'] += 1

    print(f"  {'Models Agree':<15} {'Picks':<8} {'Wins':<8} {'HR':<8}")
    for k in sorted(agreement_buckets.keys()):
        b = agreement_buckets[k]
        label = f"{k}+" if k == 5 else str(k)
        hr = b['wins'] / b['total'] * 100 if b['total'] > 0 else 0
        print(f"  {label:<15} {b['total']:<8} {b['wins']:<8} {hr:<7.1f}%")

    # --- Rescued picks analysis (by direction) ---
    print(f"\n--- Rescue Analysis (by Direction) ---")
    for category, is_rescued in [('Rescued', True), ('Organic', False)]:
        for direction in ['OVER', 'UNDER']:
            picks = [p for day in replay.days for p in day.new_picks
                     if bool(p.get('signal_rescued')) == is_rescued
                     and p.get('recommendation') == direction
                     and p.get('prediction_correct') is not None]
            if not picks:
                continue
            w = sum(1 for p in picks if p['prediction_correct'])
            t = len(picks)
            print(f"  {category} {direction}:  {w}/{t} = {w/t*100:.1f}%")

    # --- Timing ---
    total_time = sum(d.duration_sec for d in replay.days)
    print(f"\n--- Performance ---")
    print(f"  Total time:  {total_time:.0f}s ({total_time/60:.1f}min)")
    print(f"  Avg per day: {total_time/len(replay.days):.1f}s")
    print(f"  Dates:       {len(replay.days)}")

    print("\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(description='Replay per-model pipeline over season')
    parser.add_argument('--start', default=DEFAULT_START, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', default=DEFAULT_END, help='End date (YYYY-MM-DD)')
    parser.add_argument('--write-candidates', action='store_true',
                        help='Write candidates to model_bb_candidates BQ table')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose day-by-day output')
    parser.add_argument('--limit', type=int, default=0, help='Limit to N dates (for testing)')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    bq_client = bigquery.Client(project='nba-props-platform')

    print(f"Fetching game dates {args.start} to {args.end}...")
    game_dates = get_game_dates(bq_client, args.start, args.end)
    if args.limit:
        game_dates = game_dates[:args.limit]
    print(f"Found {len(game_dates)} game dates to replay\n")

    if not game_dates:
        print("No game dates found. Exiting.")
        return

    replay = ReplayResult()

    for i, game_date in enumerate(game_dates):
        print(f"[{i+1}/{len(game_dates)}] Replaying {game_date}...", end=' ', flush=True)

        day_result = replay_date(bq_client, game_date)
        replay.days.append(day_result)

        # Write candidates to BQ if requested
        if args.write_candidates and day_result.all_candidates:
            write_candidates_to_bq(bq_client, day_result.all_candidates, game_date)

        # Print day summary
        print_day_summary(day_result)

        # Running totals every 10 dates
        if (i + 1) % 10 == 0:
            running_new_t = sum(d.new_wins + d.new_losses for d in replay.days)
            running_new_w = sum(d.new_wins for d in replay.days)
            running_old_t = sum(d.old_wins + d.old_losses for d in replay.days)
            running_old_w = sum(d.old_wins for d in replay.days)
            running_new_hr = running_new_w / running_new_t * 100 if running_new_t > 0 else 0
            running_old_hr = running_old_w / running_old_t * 100 if running_old_t > 0 else 0
            print(f"  --- Running: NEW {running_new_w}-{running_new_t - running_new_w} "
                  f"({running_new_hr:.1f}%) vs OLD {running_old_w}-{running_old_t - running_old_w} "
                  f"({running_old_hr:.1f}%) ---")

    # Full report
    print_full_report(replay)


if __name__ == '__main__':
    main()
