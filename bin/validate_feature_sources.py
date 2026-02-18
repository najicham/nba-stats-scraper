#!/usr/bin/env python3
"""
Feature Source Validation Tool

For each NULL feature in ml_feature_store_v2, checks whether the upstream
source data exists. Distinguishes:
  - LEGIT NULL: source data doesn't exist (bench player without prop line, etc.)
  - BUG: source data exists but feature is NULL (extraction failure)

Usage:
    # Validate current season
    PYTHONPATH=. python bin/validate_feature_sources.py --start-date 2025-11-04 --end-date 2026-02-17

    # Validate last season
    PYTHONPATH=. python bin/validate_feature_sources.py --start-date 2024-11-01 --end-date 2025-04-13

    # Quick spot check (last 7 days)
    PYTHONPATH=. python bin/validate_feature_sources.py --days 7

    # Single feature deep dive
    PYTHONPATH=. python bin/validate_feature_sources.py --days 30 --feature 18

    # JSON output for programmatic use
    PYTHONPATH=. python bin/validate_feature_sources.py --days 7 --format json
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'

# Feature groups with their source tables and validation logic
# For each group: which features, what source to check, join conditions
FEATURE_GROUPS = {
    'player_daily_cache': {
        'features': [0, 1, 2, 3, 4, 22, 23, 31, 32],
        'names': {
            0: 'points_avg_last_5', 1: 'points_avg_last_10', 2: 'points_avg_season',
            3: 'points_std_last_10', 4: 'games_in_last_7_days',
            22: 'team_pace', 23: 'team_off_rating',
            31: 'minutes_avg_last_10', 32: 'ppm_avg_last_10'
        },
        'source_table': 'nba_precompute.player_daily_cache',
        'description': 'Player rolling stats from daily cache (exact date match)',
        'validation_sql': """
            SELECT
                fs.game_date,
                '{feature_idx}' as feature_idx,
                '{feature_name}' as feature_name,
                COUNT(*) as null_features,
                COUNTIF(pdc.player_lookup IS NOT NULL) as source_exists,
                COUNTIF(pdc.player_lookup IS NULL) as source_missing,
                ROUND(100.0 * COUNTIF(pdc.player_lookup IS NOT NULL) / COUNT(*), 1) as bug_pct
            FROM `{project}.nba_predictions.ml_feature_store_v2` fs
            LEFT JOIN (
                SELECT DISTINCT player_lookup, cache_date
                FROM `{project}.nba_precompute.player_daily_cache`
                WHERE cache_date >= '{start_date}'
            ) pdc
            ON fs.player_lookup = pdc.player_lookup
                AND pdc.cache_date = fs.game_date
            WHERE fs.game_date BETWEEN '{start_date}' AND '{end_date}'
                AND fs.feature_{feature_idx}_value IS NULL
            GROUP BY 1
        """
    },
    'composite_factors': {
        'features': [5, 6, 7, 8],
        'names': {
            5: 'fatigue_score', 6: 'shot_zone_mismatch_score',
            7: 'pace_score', 8: 'usage_spike_score'
        },
        'source_table': 'nba_precompute.player_composite_factors',
        'description': 'Player composite factors (exact date match required)',
        'validation_sql': """
            SELECT
                fs.game_date,
                '{feature_idx}' as feature_idx,
                '{feature_name}' as feature_name,
                COUNT(*) as null_features,
                COUNTIF(pcf.player_lookup IS NOT NULL) as source_exists,
                COUNTIF(pcf.player_lookup IS NULL) as source_missing,
                ROUND(100.0 * COUNTIF(pcf.player_lookup IS NOT NULL) / COUNT(*), 1) as bug_pct
            FROM `{project}.nba_predictions.ml_feature_store_v2` fs
            LEFT JOIN (
                SELECT DISTINCT player_lookup, game_date
                FROM `{project}.nba_precompute.player_composite_factors`
                WHERE game_date >= '{start_date}'
            ) pcf
            ON fs.player_lookup = pcf.player_lookup AND fs.game_date = pcf.game_date
            WHERE fs.game_date BETWEEN '{start_date}' AND '{end_date}'
                AND fs.feature_{feature_idx}_value IS NULL
            GROUP BY 1
        """
    },
    'calculated_always': {
        'features': [9, 10, 11, 12, 15, 16, 17, 21, 24, 28, 29, 30],
        'names': {
            9: 'rest_advantage', 10: 'injury_risk', 11: 'recent_trend',
            12: 'minutes_change', 15: 'home_away', 16: 'back_to_back',
            17: 'playoff_game', 21: 'pct_free_throw', 24: 'team_win_pct',
            28: 'has_vegas_line', 29: 'avg_points_vs_opponent', 30: 'games_vs_opponent'
        },
        'source_table': 'calculated (should always have value)',
        'description': 'Calculated features that should NEVER be NULL',
        'validation_sql': """
            SELECT
                fs.game_date,
                '{feature_idx}' as feature_idx,
                '{feature_name}' as feature_name,
                COUNT(*) as null_features,
                COUNT(*) as source_exists,
                0 as source_missing,
                100.0 as bug_pct
            FROM `{project}.nba_predictions.ml_feature_store_v2` fs
            WHERE fs.game_date BETWEEN '{start_date}' AND '{end_date}'
                AND fs.feature_{feature_idx}_value IS NULL
            GROUP BY 1
        """
    },
    'team_defense_zone': {
        'features': [13, 14],
        'names': {13: 'opponent_def_rating', 14: 'opponent_pace'},
        'source_table': 'nba_precompute.team_defense_zone_analysis',
        'description': 'Opponent defense stats (exact date match)',
        'validation_sql': """
            SELECT
                fs.game_date,
                '{feature_idx}' as feature_idx,
                '{feature_name}' as feature_name,
                COUNT(*) as null_features,
                COUNTIF(tdz.team_abbr IS NOT NULL) as source_exists,
                COUNTIF(tdz.team_abbr IS NULL) as source_missing,
                ROUND(100.0 * COUNTIF(tdz.team_abbr IS NOT NULL) / COUNT(*), 1) as bug_pct
            FROM `{project}.nba_predictions.ml_feature_store_v2` fs
            LEFT JOIN `{project}.nba_analytics.upcoming_player_game_context` upcg
                ON fs.player_lookup = upcg.player_lookup AND fs.game_date = upcg.game_date
            LEFT JOIN (
                SELECT DISTINCT team_abbr, analysis_date
                FROM `{project}.nba_precompute.team_defense_zone_analysis`
                WHERE analysis_date >= '{start_date}'
            ) tdz
                ON upcg.opponent_team_abbr = tdz.team_abbr
                AND tdz.analysis_date = fs.game_date
            WHERE fs.game_date BETWEEN '{start_date}' AND '{end_date}'
                AND fs.feature_{feature_idx}_value IS NULL
            GROUP BY 1
        """
    },
    'shot_zone': {
        'features': [18, 19, 20],
        'names': {18: 'pct_paint', 19: 'pct_mid_range', 20: 'pct_three'},
        'source_table': 'nba_precompute.player_shot_zone_analysis',
        'description': 'Shot zone distribution (exact date match, non-NULL values)',
        'validation_sql': """
            SELECT
                fs.game_date,
                '{feature_idx}' as feature_idx,
                '{feature_name}' as feature_name,
                COUNT(*) as null_features,
                COUNTIF(psz.player_lookup IS NOT NULL) as source_exists,
                COUNTIF(psz.player_lookup IS NULL) as source_missing,
                ROUND(100.0 * COUNTIF(psz.player_lookup IS NOT NULL) / COUNT(*), 1) as bug_pct
            FROM `{project}.nba_predictions.ml_feature_store_v2` fs
            LEFT JOIN (
                SELECT DISTINCT player_lookup, analysis_date
                FROM `{project}.nba_precompute.player_shot_zone_analysis`
                WHERE analysis_date >= '{start_date}'
                    AND paint_rate_last_10 IS NOT NULL
            ) psz
                ON fs.player_lookup = psz.player_lookup
                AND psz.analysis_date = fs.game_date
            WHERE fs.game_date BETWEEN '{start_date}' AND '{end_date}'
                AND fs.feature_{feature_idx}_value IS NULL
            GROUP BY 1
        """
    },
    'vegas_lines': {
        'features': [25, 26, 27],
        'names': {25: 'vegas_points_line', 26: 'vegas_opening_line', 27: 'vegas_line_move'},
        'source_table': 'nba_raw.odds_api_player_points_props + bettingpros fallback',
        'description': 'Vegas prop lines (NULL for bench players without lines)',
        'validation_sql': """
            SELECT
                fs.game_date,
                '{feature_idx}' as feature_idx,
                '{feature_name}' as feature_name,
                COUNT(*) as null_features,
                COUNTIF(oa.player_name IS NOT NULL OR bp.player_name IS NOT NULL) as source_exists,
                COUNTIF(oa.player_name IS NULL AND bp.player_name IS NULL) as source_missing,
                ROUND(100.0 * COUNTIF(oa.player_name IS NOT NULL OR bp.player_name IS NOT NULL) / COUNT(*), 1) as bug_pct
            FROM `{project}.nba_predictions.ml_feature_store_v2` fs
            LEFT JOIN (
                SELECT DISTINCT LOWER(REGEXP_REPLACE(player_name, r'[^a-z]', '')) as player_lookup, DATE(game_date) as game_date, player_name
                FROM `{project}.nba_raw.odds_api_player_points_props`
                WHERE game_date >= '{start_date}'
            ) oa
                ON fs.player_lookup = oa.player_lookup AND fs.game_date = oa.game_date
            LEFT JOIN (
                SELECT DISTINCT LOWER(REGEXP_REPLACE(player_name, r'[^a-z]', '')) as player_lookup, DATE(game_date) as game_date, player_name
                FROM `{project}.nba_raw.bettingpros_player_points_props`
                WHERE game_date >= '{start_date}'
            ) bp
                ON fs.player_lookup = bp.player_lookup AND fs.game_date = bp.game_date
            WHERE fs.game_date BETWEEN '{start_date}' AND '{end_date}'
                AND fs.feature_{feature_idx}_value IS NULL
            GROUP BY 1
        """
    }
}


def run_validation(client: bigquery.Client, start_date: str, end_date: str,
                   feature_filter: Optional[int] = None, sample_days: int = 0) -> Dict:
    """Run feature source validation across all groups."""
    results = {}

    for group_name, group_config in FEATURE_GROUPS.items():
        features = group_config['features']
        if feature_filter is not None and feature_filter not in features:
            continue

        features_to_check = [feature_filter] if feature_filter is not None else features
        group_results = []

        for fidx in features_to_check:
            fname = group_config['names'][fidx]
            logger.info(f"  Checking f{fidx} ({fname}) against {group_config['source_table']}...")

            sql = group_config['validation_sql'].format(
                project=PROJECT_ID,
                start_date=start_date,
                end_date=end_date,
                feature_idx=fidx,
                feature_name=fname
            )

            try:
                rows = list(client.query(sql).result())
                if not rows:
                    group_results.append({
                        'feature_idx': fidx,
                        'feature_name': fname,
                        'status': 'ALL_POPULATED',
                        'null_count': 0,
                        'bug_count': 0,
                        'legit_null_count': 0,
                        'bug_pct': 0.0,
                        'daily_breakdown': []
                    })
                else:
                    total_nulls = sum(r.null_features for r in rows)
                    total_bugs = sum(r.source_exists for r in rows)
                    total_legit = sum(r.source_missing for r in rows)
                    overall_bug_pct = round(100.0 * total_bugs / total_nulls, 1) if total_nulls > 0 else 0

                    daily = []
                    for r in sorted(rows, key=lambda x: x.game_date):
                        daily.append({
                            'date': r.game_date.isoformat() if hasattr(r.game_date, 'isoformat') else str(r.game_date),
                            'nulls': r.null_features,
                            'source_exists': r.source_exists,
                            'source_missing': r.source_missing,
                            'bug_pct': float(r.bug_pct) if r.bug_pct else 0.0
                        })

                    status = 'CLEAN' if total_bugs == 0 else ('MINOR_BUGS' if overall_bug_pct < 10 else 'BUGS_DETECTED')

                    group_results.append({
                        'feature_idx': fidx,
                        'feature_name': fname,
                        'status': status,
                        'null_count': total_nulls,
                        'bug_count': total_bugs,
                        'legit_null_count': total_legit,
                        'bug_pct': overall_bug_pct,
                        'daily_breakdown': daily if sample_days == 0 else daily[-sample_days:]
                    })
            except Exception as e:
                logger.error(f"  Error checking f{fidx}: {e}")
                group_results.append({
                    'feature_idx': fidx,
                    'feature_name': fname,
                    'status': 'ERROR',
                    'error': str(e)
                })

        if group_results:
            results[group_name] = {
                'description': group_config['description'],
                'source_table': group_config['source_table'],
                'features': group_results
            }

    return results


def get_coverage_summary(client: bigquery.Client, start_date: str, end_date: str) -> List[Dict]:
    """Get overall feature population rates for context."""
    sql = f"""
    SELECT
        FORMAT_DATE('%Y-%m', game_date) as month,
        COUNT(*) as total_rows,
        {', '.join(f"ROUND(100.0 * COUNTIF(feature_{i}_value IS NOT NULL) / COUNT(*), 1) as f{i}" for i in range(33))}
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY 1 ORDER BY 1
    """
    rows = list(client.query(sql).result())
    return [dict(r) for r in rows]


def print_report(results: Dict, coverage: List[Dict], start_date: str, end_date: str):
    """Print human-readable validation report."""
    print(f"\n{'='*70}")
    print(f"FEATURE SOURCE VALIDATION REPORT")
    print(f"Date range: {start_date} to {end_date}")
    print(f"{'='*70}")

    # Coverage summary
    print(f"\n--- COVERAGE SUMMARY (V9 features f0-f32) ---\n")
    print(f"{'Month':<10} {'Rows':>7}  ", end='')
    low_features = set()
    for i in range(33):
        print(f"f{i:>2}", end=' ')
    print()

    for row in coverage:
        month = row['month']
        total = row['total_rows']
        print(f"{month:<10} {total:>7}  ", end='')
        for i in range(33):
            val = row.get(f'f{i}', 0)
            if val is not None and val < 80:
                low_features.add(i)
                print(f"\033[91m{val:>3.0f}\033[0m", end=' ')
            elif val is not None and val < 95:
                print(f"\033[93m{val:>3.0f}\033[0m", end=' ')
            else:
                v = val if val is not None else 0
                print(f"{v:>3.0f}", end=' ')
        print()

    if low_features:
        print(f"\n  \033[91mRED\033[0m = <80%  \033[93mYELLOW\033[0m = <95%")
        print(f"  Low features: {', '.join(f'f{i}' for i in sorted(low_features))}")

    # Validation results
    print(f"\n--- SOURCE VALIDATION (NULL = legit or bug?) ---\n")

    bugs_found = []
    clean_count = 0
    legit_null_count = 0

    for group_name, group_data in results.items():
        print(f"\n  [{group_name}] {group_data['description']}")
        print(f"  Source: {group_data['source_table']}")

        for feat in group_data['features']:
            fidx = feat.get('feature_idx', '?')
            fname = feat.get('feature_name', '?')
            status = feat.get('status', 'UNKNOWN')

            if status == 'ALL_POPULATED':
                print(f"    f{fidx} ({fname}): ALL POPULATED — no NULLs found")
                clean_count += 1
            elif status == 'ERROR':
                print(f"    f{fidx} ({fname}): ERROR — {feat.get('error', 'unknown')}")
            elif status == 'CLEAN':
                nulls = feat['null_count']
                legit = feat['legit_null_count']
                print(f"    f{fidx} ({fname}): CLEAN — {nulls:,} NULLs, all legitimate (source missing)")
                legit_null_count += nulls
                clean_count += 1
            else:
                nulls = feat['null_count']
                bugs = feat['bug_count']
                legit = feat['legit_null_count']
                pct = feat['bug_pct']
                marker = '!!!' if pct > 10 else '!'
                print(f"    f{fidx} ({fname}): {marker} {bugs:,} BUGS ({pct}%) — source exists but feature NULL")
                print(f"      Total NULLs: {nulls:,} | Legit: {legit:,} | Bugs: {bugs:,}")
                bugs_found.append(feat)

    # Summary
    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"  Features checked: {sum(len(g['features']) for g in results.values())}")
    print(f"  Clean (no bugs): {clean_count}")
    print(f"  With bugs: {len(bugs_found)}")
    if bugs_found:
        print(f"\n  TOP BUGS (source exists but feature NULL):")
        for feat in sorted(bugs_found, key=lambda x: x.get('bug_count', 0), reverse=True)[:10]:
            print(f"    f{feat['feature_idx']} ({feat['feature_name']}): {feat['bug_count']:,} bugs ({feat['bug_pct']}%)")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description='Validate ML feature sources')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, help='Last N days (alternative to date range)')
    parser.add_argument('--feature', type=int, help='Single feature index to deep-dive')
    parser.add_argument('--format', choices=['text', 'json'], default='text', help='Output format')
    parser.add_argument('--sample-days', type=int, default=10, help='Max daily breakdown rows (0=all)')
    args = parser.parse_args()

    if args.days:
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=args.days)
    elif args.start_date and args.end_date:
        start_dt = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_dt = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        print("Error: provide --days or --start-date/--end-date")
        sys.exit(1)

    start_date = start_dt.isoformat()
    end_date = end_dt.isoformat()

    logger.info(f"Validating features: {start_date} to {end_date}")
    client = bigquery.Client(project=PROJECT_ID)

    # Get coverage context
    logger.info("Getting coverage summary...")
    coverage = get_coverage_summary(client, start_date, end_date)

    # Run validation
    logger.info("Running source validation...")
    results = run_validation(client, start_date, end_date,
                             feature_filter=args.feature,
                             sample_days=args.sample_days)

    if args.format == 'json':
        output = {
            'start_date': start_date,
            'end_date': end_date,
            'coverage': coverage,
            'validation': results
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print_report(results, coverage, start_date, end_date)


if __name__ == '__main__':
    main()
