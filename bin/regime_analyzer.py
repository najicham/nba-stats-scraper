#!/usr/bin/env python3
"""
Calendar Regime Analyzer

Detects current calendar regime and reports tier x direction HR vs historical norms.
Integrates with daily operations for regime-aware decision making.

Session 395: Built from calendar regime analysis findings.

Usage:
    python bin/regime_analyzer.py --date 2026-03-03
    python bin/regime_analyzer.py --date 2026-02-10 --with-hr
    python bin/regime_analyzer.py --range 2026-01-01 2026-02-28
    python bin/regime_analyzer.py --json
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from shared.config.calendar_regime import (
    detect_regime,
    get_season_calendar,
    REGIME_HR_NORMS,
    TOXIC_TIER_DIRECTION_NORMS,
    EDGE_COMPRESSION_NORMS,
)


def fetch_live_hr(target_date: date, lookback_days: int = 14) -> dict:
    """Fetch actual HR from BQ for the lookback window ending at target_date."""
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project='nba-props-platform')
    except Exception as e:
        print(f"  [warn] Could not connect to BigQuery: {e}")
        return {}

    start = target_date - timedelta(days=lookback_days)
    query = f"""
    WITH graded AS (
        SELECT
            pa.game_date,
            pa.recommendation AS direction,
            CASE
                WHEN pa.line_value >= 25 THEN 'Star'
                WHEN pa.line_value >= 15 THEN 'Starter'
                WHEN pa.line_value >= 5 THEN 'Role'
                ELSE 'Bench'
            END AS tier,
            ABS(pa.predicted_points - pa.line_value) AS edge,
            pa.prediction_correct AS hit,
            pa.absolute_error
        FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
        WHERE pa.game_date BETWEEN '{start}' AND '{target_date}'
          AND ABS(pa.predicted_points - pa.line_value) >= 3.0
          AND pa.has_prop_line = TRUE
          AND pa.recommendation IN ('OVER', 'UNDER')
          AND pa.prediction_correct IS NOT NULL
    )
    SELECT
        tier,
        direction,
        COUNT(*) AS n,
        ROUND(AVG(CAST(hit AS INT64)) * 100, 1) AS hr,
        ROUND(AVG(edge), 2) AS avg_edge,
        ROUND(STDDEV(edge), 2) AS std_edge,
        ROUND(AVG(absolute_error), 2) AS mae
    FROM graded
    GROUP BY tier, direction
    ORDER BY tier, direction
    """
    try:
        rows = list(client.query(query).result())
        results = {}
        totals = {'n': 0, 'hits': 0, 'edge_sum': 0, 'edge_sq_sum': 0}
        for row in rows:
            key = (row.tier, row.direction)
            results[key] = {
                'n': row.n, 'hr': float(row.hr),
                'avg_edge': float(row.avg_edge),
                'std_edge': float(row.std_edge) if row.std_edge else 0,
                'mae': float(row.mae),
            }
            totals['n'] += row.n
            totals['hits'] += int(row.n * row.hr / 100)

        # Overall edge stats
        edge_query = f"""
        SELECT
            ROUND(AVG(ABS(predicted_points - line_value)), 2) AS avg_edge,
            ROUND(STDDEV(ABS(predicted_points - line_value)), 2) AS std_edge
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE game_date BETWEEN '{start}' AND '{target_date}'
          AND ABS(predicted_points - line_value) >= 3.0
          AND has_prop_line = TRUE
          AND recommendation IN ('OVER', 'UNDER')
          AND prediction_correct IS NOT NULL
        """
        edge_row = list(client.query(edge_query).result())[0]
        results['_overall'] = {
            'n': totals['n'],
            'hr': round(totals['hits'] / totals['n'] * 100, 1) if totals['n'] > 0 else 0,
            'avg_edge': float(edge_row.avg_edge) if edge_row.avg_edge else 0,
            'std_edge': float(edge_row.std_edge) if edge_row.std_edge else 0,
        }
        return results
    except Exception as e:
        print(f"  [warn] BQ query failed: {e}")
        return {}


def display_regime(target_date: date, with_hr: bool = False, as_json: bool = False):
    """Display regime info for a single date."""
    regime = detect_regime(target_date)
    cal = regime.season_calendar

    if as_json:
        data = {
            'date': str(target_date),
            'regime': regime.name,
            'label': regime.label,
            'is_toxic': regime.is_toxic,
            'days_into_regime': regime.days_into_regime,
            'days_until_next': regime.days_until_next,
        }
        if with_hr:
            data['live_hr'] = fetch_live_hr(target_date)
            data['norm_hr'] = REGIME_HR_NORMS.get(regime.name, {})
        print(json.dumps(data, indent=2, default=str))
        return data

    # Header
    toxic_marker = " *** TOXIC ***" if regime.is_toxic else ""
    print(f"\n{'='*60}")
    print(f"  Regime Report: {target_date}{toxic_marker}")
    print(f"{'='*60}")
    print(f"  Regime:  {regime.label} ({regime.name})")
    print(f"  Toxic:   {'YES' if regime.is_toxic else 'No'}")

    if regime.days_until_next is not None:
        if regime.is_toxic and regime.name == 'post_asb':
            print(f"  Recovery in: {regime.days_until_next} days")
        elif regime.is_toxic:
            print(f"  Days into toxic: {regime.days_into_regime}")
        else:
            print(f"  Days until toxic: {regime.days_until_next}")

    if cal:
        print(f"\n  Calendar ({cal.season_year}-{cal.season_year+1} season):")
        print(f"    Trade Deadline:  {cal.trade_deadline}")
        print(f"    ASB:             {cal.asb_start} → {cal.asb_end}")
        print(f"    Games Resume:    {cal.games_resume}")
        print(f"    Toxic Window:    {cal.toxic_start} → {cal.toxic_end}")

    # Historical norms for current regime
    norms = REGIME_HR_NORMS.get(regime.name)
    if norms and norms['hr'] is not None:
        print(f"\n  Historical Norms ({regime.name}):")
        print(f"    Overall HR:  {norms['hr']}%")
        if norms['over_hr']:
            print(f"    OVER HR:     {norms['over_hr']}%")
        if norms['under_hr']:
            print(f"    UNDER HR:    {norms['under_hr']}%")

    # Edge compression check
    if regime.is_toxic:
        normal_edge = EDGE_COMPRESSION_NORMS['normal']
        toxic_edge = EDGE_COMPRESSION_NORMS['toxic']
        print(f"\n  Edge Compression Warning:")
        print(f"    Normal std_edge: {normal_edge['std_edge']}")
        print(f"    Toxic std_edge:  {toxic_edge['std_edge']} ({toxic_edge['std_edge']/normal_edge['std_edge']*100:.0f}% of normal)")
        print(f"    Model loses ability to differentiate confidence levels.")

    # Tier x direction during toxic
    if regime.is_toxic:
        print(f"\n  Tier x Direction Impact (Normal → Toxic):")
        print(f"  {'Combo':<18} {'Normal':>8} {'Toxic':>8} {'Delta':>8}  Verdict")
        print(f"  {'-'*18} {'-'*8} {'-'*8} {'-'*8}  {'-'*16}")
        for (tier, direction), info in sorted(TOXIC_TIER_DIRECTION_NORMS.items(), key=lambda x: x[1]['delta']):
            verdict_color = info['verdict']
            print(f"  {tier+' '+direction:<18} {info['normal_hr']:>7.1f}% {info['toxic_hr']:>7.1f}% {info['delta']:>+7.1f}pp  {verdict_color}")

    # Live HR from BQ
    if with_hr:
        print(f"\n  Live HR (14-day lookback from {target_date}):")
        live = fetch_live_hr(target_date)
        if live:
            overall = live.get('_overall', {})
            if overall:
                print(f"    Overall: {overall.get('hr', '?')}% (N={overall.get('n', '?')}, avg_edge={overall.get('avg_edge', '?')}, std_edge={overall.get('std_edge', '?')})")

            print(f"\n    {'Combo':<18} {'Live HR':>8} {'N':>5} {'Norm HR':>8}  {'Delta':>8}")
            print(f"    {'-'*18} {'-'*8} {'-'*5} {'-'*8}  {'-'*8}")
            for (tier, direction) in sorted(TOXIC_TIER_DIRECTION_NORMS.keys()):
                live_data = live.get((tier, direction), {})
                if not live_data:
                    continue
                norm_key = regime.name if regime.is_toxic else 'normal'
                if regime.is_toxic:
                    norm_hr = TOXIC_TIER_DIRECTION_NORMS.get((tier, direction), {}).get('toxic_hr', '?')
                else:
                    norm_hr = TOXIC_TIER_DIRECTION_NORMS.get((tier, direction), {}).get('normal_hr', '?')
                delta = live_data['hr'] - norm_hr if isinstance(norm_hr, (int, float)) else '?'
                delta_str = f"{delta:>+7.1f}pp" if isinstance(delta, (int, float)) else f"{'?':>8}"
                print(f"    {tier+' '+direction:<18} {live_data['hr']:>7.1f}% {live_data['n']:>5} {norm_hr:>7}%  {delta_str}")

            # Edge compression flag
            if overall.get('std_edge'):
                normal_std = EDGE_COMPRESSION_NORMS['normal']['std_edge']
                live_std = overall['std_edge']
                if live_std < normal_std * 0.7:
                    print(f"\n    *** EDGE COMPRESSION DETECTED: std_edge={live_std:.2f} vs normal {normal_std:.2f} ***")
        else:
            print("    [No BQ data available]")

    print()
    return regime


def display_range(start_date: date, end_date: date, as_json: bool = False):
    """Show regime classification for a date range."""
    results = []
    current = start_date
    prev_regime = None

    while current <= end_date:
        regime = detect_regime(current)
        if regime.name != prev_regime:
            results.append({
                'start': str(current),
                'regime': regime.name,
                'label': regime.label,
                'is_toxic': regime.is_toxic,
            })
            prev_regime = regime.name
        current += timedelta(days=1)

    # Set end dates
    for i, r in enumerate(results):
        if i + 1 < len(results):
            end = datetime.strptime(results[i+1]['start'], '%Y-%m-%d').date() - timedelta(days=1)
            r['end'] = str(end)
        else:
            r['end'] = str(end_date)

    if as_json:
        print(json.dumps(results, indent=2))
        return results

    print(f"\n{'='*60}")
    print(f"  Regime Timeline: {start_date} → {end_date}")
    print(f"{'='*60}")
    print(f"  {'Start':<12} {'End':<12} {'Regime':<20} {'Toxic'}")
    print(f"  {'-'*12} {'-'*12} {'-'*20} {'-'*5}")
    for r in results:
        toxic = "YES" if r['is_toxic'] else ""
        print(f"  {r['start']:<12} {r['end']:<12} {r['label']:<20} {toxic}")
    print()
    return results


def main():
    parser = argparse.ArgumentParser(description='Calendar Regime Analyzer')
    parser.add_argument('--date', type=str, default=str(date.today()),
                        help='Date to analyze (YYYY-MM-DD)')
    parser.add_argument('--range', nargs=2, metavar=('START', 'END'),
                        help='Date range to show regime timeline')
    parser.add_argument('--with-hr', action='store_true',
                        help='Include live HR from BigQuery (14-day lookback)')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    args = parser.parse_args()

    if args.range:
        start = datetime.strptime(args.range[0], '%Y-%m-%d').date()
        end = datetime.strptime(args.range[1], '%Y-%m-%d').date()
        display_range(start, end, as_json=args.json)
    else:
        target = datetime.strptime(args.date, '%Y-%m-%d').date()
        display_regime(target, with_hr=args.with_hr, as_json=args.json)


if __name__ == '__main__':
    main()
