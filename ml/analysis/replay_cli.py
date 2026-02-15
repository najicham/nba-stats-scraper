"""Replay CLI — command-line interface for the replay engine.

Usage:
    # Last 30 days with threshold strategy
    PYTHONPATH=. python ml/analysis/replay_cli.py \
        --start 2026-01-15 --end 2026-02-12 \
        --models catboost_v9,catboost_v12

    # Compare strategies
    PYTHONPATH=. python ml/analysis/replay_cli.py \
        --start 2025-11-15 --end 2026-02-12 \
        --models catboost_v9,catboost_v12 \
        --compare

    # Full season
    PYTHONPATH=. python ml/analysis/replay_cli.py \
        --start 2025-11-02 --end 2026-02-12 \
        --models catboost_v9,catboost_v12,catboost_v9_q43

Created: 2026-02-15 (Session 262)
"""

import argparse
import json
import logging
import os
from datetime import date, timedelta

from google.cloud import bigquery

from ml.analysis.replay_engine import ReplayEngine
from ml.analysis.replay_strategies import (
    BestOfNStrategy,
    ConservativeStrategy,
    OracleStrategy,
    ThresholdStrategy,
)

logger = logging.getLogger(__name__)

DEFAULT_MODELS = ['catboost_v9', 'catboost_v12']


def build_strategy(name: str, champion: str, challengers: list,
                   **kwargs):
    """Build a strategy by name."""
    if name == 'threshold':
        return ThresholdStrategy(
            champion_id=champion,
            challenger_ids=challengers,
            watch_threshold=kwargs.get('watch', 58.0),
            alert_threshold=kwargs.get('alert', 55.0),
            block_threshold=kwargs.get('block', 52.4),
            min_sample=kwargs.get('min_sample', 20),
        )
    elif name == 'best_of_n':
        return BestOfNStrategy(min_sample=kwargs.get('min_sample', 20))
    elif name == 'conservative':
        return ConservativeStrategy(
            champion_id=champion,
            consecutive_days=kwargs.get('consecutive_days', 5),
            threshold=kwargs.get('threshold', 55.0),
            min_sample=kwargs.get('min_sample', 20),
        )
    elif name == 'oracle':
        return OracleStrategy()
    else:
        raise ValueError(f"Unknown strategy: {name}")


def print_summary(summary: dict):
    """Pretty-print a strategy summary."""
    print(f"\n{'='*60}")
    print(f"STRATEGY: {summary['strategy']}")
    print(f"{'='*60}")
    print(f"Period: {summary['date_range']}")
    print(f"Game Days: {summary['game_days']}")
    print(f"Total Picks: {summary['total_picks']}")
    print(f"Wins/Losses: {summary['total_wins']}/{summary['total_losses']}")
    print(f"Hit Rate: {summary['hit_rate']}%")
    print(f"Cumulative P&L: ${summary['cumulative_pnl']:,.2f}")
    print(f"ROI: {summary['roi']}%")
    print(f"Model Switches: {summary['switches']}")
    print(f"Blocked Days: {summary['blocked_days']}")
    print(f"Models Used: {', '.join(summary['models_used'])}")
    print()


def print_decisions(decisions: list, show_all: bool = False):
    """Print decision timeline (actions only unless show_all)."""
    print(f"\n{'='*60}")
    print("DECISION TIMELINE")
    print(f"{'='*60}")

    for d in decisions:
        if not show_all and d['action'] == 'NO_CHANGE':
            continue
        state_icon = {
            'HEALTHY': '+',
            'WATCH': '!',
            'DEGRADING': '!!',
            'BLOCKED': 'X',
            'INSUFFICIENT_DATA': '?',
        }.get(d['state'], ' ')
        print(f"  [{state_icon}] {d['date']}: {d['action']} — {d['reason']}")

    print()


def print_daily_pnl(daily_pnl: list):
    """Print daily P&L summary."""
    print(f"\n{'='*60}")
    print(f"{'Date':<12} {'Model':<18} {'Picks':>5} {'W/L':>6} "
          f"{'HR':>6} {'Day P&L':>9} {'Cum P&L':>10}")
    print(f"{'-'*12} {'-'*18} {'-'*5} {'-'*6} {'-'*6} {'-'*9} {'-'*10}")

    for d in daily_pnl:
        if d['picks'] == 0:
            continue
        model = (d['selected_model'] or 'BLOCKED')[:18]
        wl = f"{d['wins']}/{d['losses']}"
        print(f"{d['date']:<12} {model:<18} {d['picks']:>5} {wl:>6} "
              f"{d['daily_hr']:>5.1f}% ${d['daily_pnl_dollars']:>8,.2f} "
              f"${d['cumulative_pnl']:>9,.2f}")

    print()


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description='NBA Replay Engine CLI')
    parser.add_argument('--start', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--models', type=str, default=','.join(DEFAULT_MODELS),
                        help='Comma-separated model IDs')
    parser.add_argument('--strategy', type=str, default='threshold',
                        choices=['threshold', 'best_of_n', 'conservative', 'oracle'],
                        help='Strategy to use (default: threshold)')
    parser.add_argument('--champion', type=str, default='catboost_v9',
                        help='Champion model ID (default: catboost_v9)')
    parser.add_argument('--watch', type=float, default=58.0, help='Watch threshold %%')
    parser.add_argument('--alert', type=float, default=55.0, help='Alert threshold %%')
    parser.add_argument('--block', type=float, default=52.4, help='Block threshold %%')
    parser.add_argument('--min-sample', type=int, default=20, help='Minimum sample size')
    parser.add_argument('--compare', action='store_true',
                        help='Compare all strategies side-by-side')
    parser.add_argument('--verbose', action='store_true',
                        help='Show all daily decisions (not just actions)')
    parser.add_argument('--output', type=str, help='Output directory for JSON results')
    parser.add_argument('--max-picks', type=int, default=5,
                        help='Max picks per day (default: 5)')

    args = parser.parse_args()
    model_ids = [m.strip() for m in args.models.split(',')]
    challengers = [m for m in model_ids if m != args.champion]

    bq_client = bigquery.Client(project='nba-props-platform')
    engine = ReplayEngine(bq_client)

    if args.compare:
        # Compare all strategies
        strategies = [
            build_strategy('threshold', args.champion, challengers,
                           watch=args.watch, alert=args.alert, block=args.block,
                           min_sample=args.min_sample),
            build_strategy('best_of_n', args.champion, challengers,
                           min_sample=args.min_sample),
            build_strategy('conservative', args.champion, challengers,
                           min_sample=args.min_sample),
            build_strategy('oracle', args.champion, challengers),
        ]

        print(f"\nCOMPARING {len(strategies)} STRATEGIES")
        print(f"Models: {', '.join(model_ids)}")
        print(f"Period: {args.start} to {args.end}")

        summaries = engine.compare_strategies(
            strategies, args.start, args.end, model_ids)

        for s in summaries:
            print_summary(s)

        # Comparison table
        print(f"\n{'Strategy':<45} {'HR':>6} {'ROI':>7} {'P&L':>10} {'Switches':>8}")
        print(f"{'-'*45} {'-'*6} {'-'*7} {'-'*10} {'-'*8}")
        for s in summaries:
            print(f"{s['strategy']:<45} {s['hit_rate']:>5.1f}% "
                  f"{s['roi']:>6.1f}% ${s['cumulative_pnl']:>9,.2f} "
                  f"{s['switches']:>8}")

        if args.output:
            os.makedirs(args.output, exist_ok=True)
            with open(os.path.join(args.output, 'strategy_comparison.json'), 'w') as f:
                json.dump(summaries, f, indent=2)
            print(f"\nResults saved to {args.output}/strategy_comparison.json")
    else:
        # Single strategy
        strategy = build_strategy(args.strategy, args.champion, challengers,
                                  watch=args.watch, alert=args.alert, block=args.block,
                                  min_sample=args.min_sample)

        result = engine.run(strategy, args.start, args.end, model_ids,
                            max_picks_per_day=args.max_picks)

        print_summary(result['summary'])
        print_decisions(result['decisions'], show_all=args.verbose)
        print_daily_pnl(result['daily_pnl'])

        if args.output:
            os.makedirs(args.output, exist_ok=True)
            with open(os.path.join(args.output, 'replay_results.json'), 'w') as f:
                json.dump(result, f, indent=2, default=str)
            print(f"\nResults saved to {args.output}/replay_results.json")


if __name__ == '__main__':
    main()
