#!/usr/bin/env python3
"""
MLB Historical Backfill Progress Dashboard

Quick visibility into all phases of the backfill process.

Usage:
    python scripts/mlb/historical_odds_backfill/check_backfill_progress.py
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google.cloud import bigquery, storage

PROJECT_ID = 'nba-props-platform'
BUCKET_NAME = 'nba-scraped-data'
GCS_PREFIX = 'mlb-odds-api/pitcher-props-history'


def check_gcs_progress():
    """Check how many dates have been scraped to GCS."""
    # Use gsutil for reliable folder listing
    try:
        result = subprocess.run(
            ['gsutil', 'ls', f'gs://{BUCKET_NAME}/{GCS_PREFIX}/'],
            capture_output=True, text=True, timeout=60
        )
        dates = set()
        for line in result.stdout.strip().split('\n'):
            if line:
                # Extract date from path like 'gs://bucket/prefix/2024-04-09/'
                parts = line.rstrip('/').split('/')
                if parts:
                    date_str = parts[-1]
                    if len(date_str) == 10 and date_str[4] == '-':
                        dates.add(date_str)
        return sorted(dates)
    except Exception as e:
        print(f"  Warning: Could not list GCS ({e})")
        return []


def check_bigquery_progress():
    """Check what's been loaded to BigQuery."""
    client = bigquery.Client(project=PROJECT_ID)

    query = """
    SELECT
        COUNT(*) as total_rows,
        COUNT(DISTINCT game_date) as unique_dates,
        MIN(game_date) as min_date,
        MAX(game_date) as max_date,
        SUM(CASE WHEN market_key = 'pitcher_strikeouts' THEN 1 ELSE 0 END) as strikeout_lines,
        COUNT(DISTINCT CASE WHEN market_key = 'pitcher_strikeouts' THEN game_date END) as strikeout_dates
    FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props`
    WHERE source_file_path LIKE '%pitcher-props-history%'
    """

    result = list(client.query(query).result())[0]
    return {
        'total_rows': result.total_rows,
        'unique_dates': result.unique_dates,
        'min_date': str(result.min_date) if result.min_date else None,
        'max_date': str(result.max_date) if result.max_date else None,
        'strikeout_lines': result.strikeout_lines,
        'strikeout_dates': result.strikeout_dates,
    }


def check_prediction_coverage():
    """Check how many predictions can be matched."""
    client = bigquery.Client(project=PROJECT_ID)

    query = """
    WITH predictions AS (
        SELECT
            game_date,
            pitcher_lookup,
            LOWER(TRANSLATE(
                REPLACE(REPLACE(pitcher_lookup, '_', ''), '-', ''),
                'áàâäãåéèêëíìîïóòôöõúùûüñç',
                'aaaaaaeeeeiiiiooooouuuunc'
            )) as normalized_lookup,
            strikeouts_line,
            actual_strikeouts
        FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    ),
    odds AS (
        SELECT DISTINCT
            game_date,
            LOWER(TRANSLATE(
                REPLACE(REPLACE(player_lookup, '_', ''), '-', ''),
                'áàâäãåéèêëíìîïóòôöõúùûüñç',
                'aaaaaaeeeeiiiiooooouuuunc'
            )) as normalized_lookup
        FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props`
        WHERE market_key = 'pitcher_strikeouts'
          AND source_file_path LIKE '%pitcher-props-history%'
    )
    SELECT
        COUNT(*) as total_predictions,
        352 as total_dates_expected,
        COUNT(DISTINCT p.game_date) as prediction_dates,
        SUM(CASE WHEN p.strikeouts_line IS NOT NULL THEN 1 ELSE 0 END) as already_has_line,
        SUM(CASE WHEN o.normalized_lookup IS NOT NULL THEN 1 ELSE 0 END) as matchable,
        COUNT(DISTINCT o.game_date) as odds_dates_available
    FROM predictions p
    LEFT JOIN odds o
        ON p.game_date = o.game_date
        AND p.normalized_lookup = o.normalized_lookup
    """

    result = list(client.query(query).result())[0]
    return {
        'total_predictions': result.total_predictions,
        'total_dates_expected': result.total_dates_expected,
        'prediction_dates': result.prediction_dates,
        'already_has_line': result.already_has_line,
        'matchable': result.matchable,
        'odds_dates_available': result.odds_dates_available,
    }


def main():
    print("=" * 70)
    print("MLB HISTORICAL BACKFILL PROGRESS DASHBOARD")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Phase 1: GCS Progress
    print("\n📁 PHASE 1: GCS Scraping Progress")
    print("-" * 50)
    gcs_dates = check_gcs_progress()
    print(f"  Dates scraped to GCS: {len(gcs_dates)}/352")
    print(f"  Progress: {len(gcs_dates)/352*100:.1f}%")
    if gcs_dates:
        print(f"  Date range: {min(gcs_dates)} → {max(gcs_dates)}")

    # Phase 2: BigQuery Progress
    print("\n📊 PHASE 2: BigQuery Loading Progress")
    print("-" * 50)
    bq_stats = check_bigquery_progress()
    print(f"  Total rows loaded: {bq_stats['total_rows']:,}")
    print(f"  Unique dates loaded: {bq_stats['unique_dates']}/352")
    print(f"  Progress: {(bq_stats['unique_dates'] or 0)/352*100:.1f}%")
    print(f"  Strikeout lines: {bq_stats['strikeout_lines']:,}")
    print(f"  Strikeout dates: {bq_stats['strikeout_dates']}")
    if bq_stats['min_date']:
        print(f"  Date range: {bq_stats['min_date']} → {bq_stats['max_date']}")

    # Prediction Coverage
    print("\n🎯 PREDICTION MATCHING STATUS")
    print("-" * 50)
    pred_stats = check_prediction_coverage()
    print(f"  Total predictions: {pred_stats['total_predictions']:,}")
    print(f"  Already has line: {pred_stats['already_has_line']:,}")
    print(f"  Currently matchable: {pred_stats['matchable']:,}")
    coverage = pred_stats['matchable'] / pred_stats['total_predictions'] * 100 if pred_stats['total_predictions'] > 0 else 0
    print(f"  Current coverage: {coverage:.1f}%")
    print(f"  Odds dates in BQ: {pred_stats['odds_dates_available']}")

    # Overall Status
    print("\n" + "=" * 70)
    print("📈 OVERALL STATUS")
    print("=" * 70)

    phase1_pct = len(gcs_dates) / 352 * 100
    phase2_pct = (bq_stats['unique_dates'] or 0) / 352 * 100

    if phase1_pct < 100:
        print(f"  ⏳ Phase 1 (GCS scraping): {phase1_pct:.0f}% complete")
        remaining = 352 - len(gcs_dates)
        print(f"     {remaining} dates remaining")
    else:
        print(f"  ✅ Phase 1 (GCS scraping): COMPLETE")

    if phase2_pct < 100:
        print(f"  ⏳ Phase 2 (BQ loading): {phase2_pct:.0f}% complete")
    else:
        print(f"  ✅ Phase 2 (BQ loading): COMPLETE")

    if coverage < 50:
        print(f"  ⏳ Phases 3-5: WAITING (need more data)")
    elif coverage >= 70:
        print(f"  🚀 Phases 3-5: READY TO RUN ({coverage:.0f}% matchable)")
    else:
        print(f"  ⚠️  Phases 3-5: CAN RUN ({coverage:.0f}% matchable)")

    print("\n" + "-" * 70)
    print("NEXT STEPS:")
    if phase1_pct < 100:
        print("  1. Wait for Phase 1 to complete (GCS scraping)")
    if phase2_pct < phase1_pct:
        print("  2. Phase 2 is catching up (GCS → BigQuery)")
    if phase1_pct >= 100 and phase2_pct >= 100:
        print("  1. Run Phase 3: python scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py")
        print("  2. Run Phase 4: python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py")
        print("  3. Run Phase 5: python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py")
    print("-" * 70)


if __name__ == "__main__":
    main()
