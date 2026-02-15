#!/usr/bin/env python3
"""
Phase 6 Daily Export Job

Exports prediction data to GCS as JSON for website consumption.
Can be run for a single date or backfill a range.

Usage:
    # Export single date (all exporters)
    python daily_export.py --date 2021-11-10

    # Export yesterday (default)
    python daily_export.py

    # Backfill all dates with graded predictions
    python daily_export.py --backfill-all

    # Export only specific types
    python daily_export.py --date 2021-11-10 --only results,best-bets

    # Export tonight's data for website homepage
    python daily_export.py --date 2024-12-11 --only tonight,tonight-players

    # Export player profiles
    python daily_export.py --players

    # Export player profiles with minimum games threshold
    python daily_export.py --players --min-games 10

Export Types:
    results         - Daily prediction results
    performance     - System performance metrics
    best-bets       - Top ranked picks
    predictions     - All predictions grouped by game
    tonight         - All players for tonight's games (website homepage)
    tonight-players - Individual player detail for tonight tab
"""

import argparse
import logging
import sys
import os
from datetime import datetime, timedelta
from typing import List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery
from data_processors.publishing.results_exporter import ResultsExporter
from data_processors.publishing.system_performance_exporter import SystemPerformanceExporter
from data_processors.publishing.best_bets_exporter import BestBetsExporter
from data_processors.publishing.predictions_exporter import PredictionsExporter
from data_processors.publishing.player_profile_exporter import PlayerProfileExporter
from data_processors.publishing.tonight_all_players_exporter import TonightAllPlayersExporter
from data_processors.publishing.tonight_player_exporter import TonightPlayerExporter
from data_processors.publishing.streaks_exporter import StreaksExporter
# Trends v2 exporters
from data_processors.publishing.whos_hot_cold_exporter import WhosHotColdExporter
from data_processors.publishing.bounce_back_exporter import BounceBackExporter
from data_processors.publishing.what_matters_exporter import WhatMattersExporter
from data_processors.publishing.team_tendencies_exporter import TeamTendenciesExporter
from data_processors.publishing.quick_hits_exporter import QuickHitsExporter
from data_processors.publishing.deep_dive_exporter import DeepDiveExporter
# Frontend API Backend exporters (Session 143)
from data_processors.publishing.player_season_exporter import PlayerSeasonExporter
from data_processors.publishing.player_game_report_exporter import PlayerGameReportExporter
from data_processors.publishing.tonight_trend_plays_exporter import TonightTrendPlaysExporter
# Live scoring for Challenge System
from data_processors.publishing.live_scores_exporter import LiveScoresExporter
from data_processors.publishing.live_grading_exporter import LiveGradingExporter
# Phase 6 Subset Exports (Session 90)
from data_processors.publishing.subset_definitions_exporter import SubsetDefinitionsExporter
from data_processors.publishing.daily_signals_exporter import DailySignalsExporter
from data_processors.publishing.subset_performance_exporter import SubsetPerformanceExporter
from data_processors.publishing.all_subsets_picks_exporter import AllSubsetsPicksExporter
from data_processors.publishing.subset_materializer import SubsetMaterializer
# Season subset picks (Session 158)
from data_processors.publishing.season_subset_picks_exporter import SeasonSubsetPicksExporter
# Calendar widget (Sprint 3)
from data_processors.publishing.calendar_exporter import CalendarExporter
# Season game counts for calendar and break detection
from data_processors.publishing.season_game_counts_exporter import SeasonGameCountsExporter
# Consolidated trends tonight (Session 226)
from data_processors.publishing.trends_tonight_exporter import TrendsTonightExporter
# Signal best bets (Session 254)
from data_processors.publishing.signal_best_bets_exporter import SignalBestBetsExporter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'

# Available export types
EXPORT_TYPES = [
    'results', 'performance', 'best-bets', 'predictions',
    'tonight', 'tonight-players', 'streaks',
    'calendar',  # Sprint 3 - Date navigation
    'season-game-counts',  # Full season game counts for calendar and break detection
    # Trends v2
    'trends-hot-cold', 'trends-bounce-back', 'trends-what-matters',
    'trends-team', 'trends-quick-hits', 'trends-deep-dive',
    # Frontend API Backend (Session 143)
    'tonight-trend-plays',
    # Live scoring for Challenge System
    'live', 'live-grading',
    # Phase 6 Subset Exports (Session 90)
    'subset-picks', 'daily-signals', 'subset-performance', 'subset-definitions', 'season-subsets',
    # Signal best bets (Session 254)
    'signal-best-bets',
    # Consolidated trends
    'trends-tonight',
    # Shorthand groups
    'trends-daily', 'trends-weekly', 'trends-all'
]


def get_dates_with_predictions() -> List[str]:
    """Get all dates that have graded predictions."""
    client = bigquery.Client(project=PROJECT_ID)
    query = """
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    ORDER BY game_date
    """
    results = client.query(query).result(timeout=60)
    return [row['game_date'].strftime('%Y-%m-%d') for row in results]


def export_date(
    target_date: str,
    update_latest: bool = True,
    export_types: Optional[List[str]] = None
) -> dict:
    """
    Export data for a single date.

    Args:
        target_date: Date string in YYYY-MM-DD format
        update_latest: Whether to update latest.json files
        export_types: List of types to export (default: all)

    Returns:
        Dict with export status and paths
    """
    if export_types is None:
        export_types = EXPORT_TYPES

    result = {
        'date': target_date,
        'status': 'success',
        'paths': {},
        'errors': []
    }

    # === FAST EXPORTS FIRST ===
    # Run quick single-query exports before the slow tonight-players exporter
    # (which processes 200+ individual player files and can take 8+ minutes).
    # This ensures subset-picks, daily-signals, and other critical exports
    # complete even if the function approaches its timeout.

    # Results exporter
    if 'results' in export_types:
        try:
            exporter = ResultsExporter()
            path = exporter.export(target_date, update_latest=update_latest)
            result['paths']['results'] = path
            logger.info(f"  Results: {path}")
        except Exception as e:
            result['errors'].append(f"results: {e}")
            logger.error(f"  Results error: {e}")

    # Performance exporter
    if 'performance' in export_types:
        try:
            exporter = SystemPerformanceExporter()
            path = exporter.export(target_date)
            result['paths']['performance'] = path
            logger.info(f"  Performance: {path}")
        except Exception as e:
            result['errors'].append(f"performance: {e}")
            logger.error(f"  Performance error: {e}")

    # Best bets exporter
    if 'best-bets' in export_types:
        try:
            exporter = BestBetsExporter()
            path = exporter.export(target_date, update_latest=update_latest)
            result['paths']['best_bets'] = path
            logger.info(f"  Best Bets: {path}")
        except Exception as e:
            result['errors'].append(f"best-bets: {e}")
            logger.error(f"  Best Bets error: {e}")

    # Predictions exporter
    if 'predictions' in export_types:
        try:
            exporter = PredictionsExporter()
            path = exporter.export(target_date, update_today=update_latest)
            result['paths']['predictions'] = path
            logger.info(f"  Predictions: {path}")
        except Exception as e:
            result['errors'].append(f"predictions: {e}")
            logger.error(f"  Predictions error: {e}")

    # Tonight all players exporter (website homepage)
    if 'tonight' in export_types:
        try:
            exporter = TonightAllPlayersExporter()
            path = exporter.export(target_date)
            result['paths']['tonight'] = path
            logger.info(f"  Tonight All Players: {path}")
        except Exception as e:
            result['errors'].append(f"tonight: {e}")
            logger.error(f"  Tonight All Players error: {e}")

    # Streaks exporter (players on OVER/UNDER streaks)
    if 'streaks' in export_types:
        try:
            exporter = StreaksExporter(min_streak_length=4)
            path = exporter.export(target_date)
            result['paths']['streaks'] = path
            logger.info(f"  Streaks: {path}")
        except Exception as e:
            result['errors'].append(f"streaks: {e}")
            logger.error(f"  Streaks error: {e}")

    # Calendar game counts (Sprint 3 - Date navigation)
    if 'calendar' in export_types:
        try:
            exporter = CalendarExporter()
            path = exporter.export(days_back=30)
            result['paths']['calendar'] = path
            logger.info(f"  Calendar: {path}")
        except Exception as e:
            result['errors'].append(f"calendar: {e}")
            logger.error(f"  Calendar error: {e}")

    # Season game counts (full season for calendar and break detection)
    if 'season-game-counts' in export_types:
        try:
            exporter = SeasonGameCountsExporter()
            path = exporter.export(season_start="2025-10-01")
            result['paths']['season_game_counts'] = path
            logger.info(f"  Season Game Counts: {path}")
        except Exception as e:
            result['errors'].append(f"season-game-counts: {e}")
            logger.error(f"  Season Game Counts error: {e}")

    # === PHASE 6 SUBSET EXPORTS (Session 90) ===
    # Moved before tonight-players to ensure these fast, critical exports
    # complete before the slow per-player exporter consumes remaining time.

    # Subset picks exporter (all groups in one file)
    # Session 153: Materialize subsets to BigQuery first, then export to GCS
    if 'subset-picks' in export_types:
        try:
            # Step 1: Materialize subsets to BigQuery (creates queryable entity)
            materializer = SubsetMaterializer()
            mat_result = materializer.materialize(target_date, trigger_source='export')
            logger.info(
                f"  Subset Materialization: {mat_result.get('total_picks', 0)} picks "
                f"across {len(mat_result.get('subsets', {}))} subsets "
                f"(version={mat_result.get('version_id')})"
            )
        except Exception as e:
            # Non-fatal: if materialization fails, export will use fallback
            logger.warning(f"  Subset Materialization failed (export will use fallback): {e}")

        try:
            # Step 2: Export to GCS (reads from materialized table or falls back)
            exporter = AllSubsetsPicksExporter()
            path = exporter.export(target_date)
            result['paths']['subset_picks'] = path
            logger.info(f"  Subset Picks: {path}")
        except Exception as e:
            result['errors'].append(f"subset-picks: {e}")
            logger.error(f"  Subset Picks error: {e}")

    # Daily signals exporter
    if 'daily-signals' in export_types:
        try:
            exporter = DailySignalsExporter()
            path = exporter.export(target_date)
            result['paths']['daily_signals'] = path
            logger.info(f"  Daily Signals: {path}")
        except Exception as e:
            result['errors'].append(f"daily-signals: {e}")
            logger.error(f"  Daily Signals error: {e}")

    # Subset performance exporter
    if 'subset-performance' in export_types:
        try:
            exporter = SubsetPerformanceExporter()
            path = exporter.export()
            result['paths']['subset_performance'] = path
            logger.info(f"  Subset Performance: {path}")
        except Exception as e:
            result['errors'].append(f"subset-performance: {e}")
            logger.error(f"  Subset Performance error: {e}")

    # Subset definitions exporter
    if 'subset-definitions' in export_types:
        try:
            exporter = SubsetDefinitionsExporter()
            path = exporter.export()
            result['paths']['subset_definitions'] = path
            logger.info(f"  Subset Definitions: {path}")
        except Exception as e:
            result['errors'].append(f"subset-definitions: {e}")
            logger.error(f"  Subset Definitions error: {e}")

    # Season subset picks exporter (Session 158 - full season in one file)
    if 'season-subsets' in export_types:
        try:
            exporter = SeasonSubsetPicksExporter()
            path = exporter.export()
            result['paths']['season_subsets'] = path
            logger.info(f"  Season Subsets: {path}")
        except Exception as e:
            result['errors'].append(f"season-subsets: {e}")
            logger.error(f"  Season Subsets error: {e}")

    # Signal best bets exporter (Session 254 - curated picks via Signal Framework)
    if 'signal-best-bets' in export_types:
        try:
            exporter = SignalBestBetsExporter()
            path = exporter.export(target_date)
            result['paths']['signal_best_bets'] = path
            logger.info(f"  Signal Best Bets: {path}")
        except Exception as e:
            result['errors'].append(f"signal-best-bets: {e}")
            logger.error(f"  Signal Best Bets error: {e}")

    # === SLOW EXPORTS (tonight-players processes 200+ individual files) ===

    # Tonight individual player exporters (website player detail)
    # WARNING: This is the slowest exporter — processes each player individually
    # with a separate BQ query + GCS upload (~2-3s per player, 200+ players).
    # Must run AFTER all critical exports to avoid timeout starvation.
    if 'tonight-players' in export_types:
        try:
            exporter = TonightPlayerExporter()
            paths = exporter.export_all_for_date(target_date)
            result['paths']['tonight_players'] = paths
            logger.info(f"  Tonight Players: {len(paths)} exported")
        except Exception as e:
            result['errors'].append(f"tonight-players: {e}")
            logger.error(f"  Tonight Players error: {e}")

    # === TRENDS V2 EXPORTERS ===

    # Expand shorthand groups
    if 'trends-daily' in export_types:
        export_types.extend(['trends-hot-cold', 'trends-bounce-back', 'tonight-trend-plays', 'trends-tonight'])
    if 'trends-weekly' in export_types:
        export_types.extend(['trends-what-matters', 'trends-team', 'trends-quick-hits'])
    if 'trends-all' in export_types:
        export_types.extend([
            'trends-hot-cold', 'trends-bounce-back', 'trends-what-matters',
            'trends-team', 'trends-quick-hits', 'trends-deep-dive', 'tonight-trend-plays',
            'trends-tonight'
        ])

    # Who's Hot/Cold (daily)
    if 'trends-hot-cold' in export_types:
        try:
            exporter = WhosHotColdExporter()
            path = exporter.export(target_date)
            result['paths']['trends_hot_cold'] = path
            logger.info(f"  Trends Hot/Cold: {path}")
        except Exception as e:
            result['errors'].append(f"trends-hot-cold: {e}")
            logger.error(f"  Trends Hot/Cold error: {e}")

    # Bounce-Back Watch (daily)
    if 'trends-bounce-back' in export_types:
        try:
            exporter = BounceBackExporter()
            path = exporter.export(target_date)
            result['paths']['trends_bounce_back'] = path
            logger.info(f"  Trends Bounce-Back: {path}")
        except Exception as e:
            result['errors'].append(f"trends-bounce-back: {e}")
            logger.error(f"  Trends Bounce-Back error: {e}")

    # What Matters Most (weekly)
    if 'trends-what-matters' in export_types:
        try:
            exporter = WhatMattersExporter()
            path = exporter.export(target_date)
            result['paths']['trends_what_matters'] = path
            logger.info(f"  Trends What Matters: {path}")
        except Exception as e:
            result['errors'].append(f"trends-what-matters: {e}")
            logger.error(f"  Trends What Matters error: {e}")

    # Team Tendencies (bi-weekly)
    if 'trends-team' in export_types:
        try:
            exporter = TeamTendenciesExporter()
            path = exporter.export(target_date)
            result['paths']['trends_team'] = path
            logger.info(f"  Trends Team: {path}")
        except Exception as e:
            result['errors'].append(f"trends-team: {e}")
            logger.error(f"  Trends Team error: {e}")

    # Quick Hits (weekly)
    if 'trends-quick-hits' in export_types:
        try:
            exporter = QuickHitsExporter()
            path = exporter.export(target_date)
            result['paths']['trends_quick_hits'] = path
            logger.info(f"  Trends Quick Hits: {path}")
        except Exception as e:
            result['errors'].append(f"trends-quick-hits: {e}")
            logger.error(f"  Trends Quick Hits error: {e}")

    # Deep Dive (monthly)
    if 'trends-deep-dive' in export_types:
        try:
            exporter = DeepDiveExporter()
            path = exporter.export(target_date)
            result['paths']['trends_deep_dive'] = path
            logger.info(f"  Trends Deep Dive: {path}")
        except Exception as e:
            result['errors'].append(f"trends-deep-dive: {e}")
            logger.error(f"  Trends Deep Dive error: {e}")

    # Consolidated Trends Tonight (Session 226 - single endpoint for Trends page)
    if 'trends-tonight' in export_types:
        try:
            exporter = TrendsTonightExporter()
            path = exporter.export(target_date)
            result['paths']['trends_tonight'] = path
            logger.info(f"  Trends Tonight: {path}")
        except Exception as e:
            result['errors'].append(f"trends-tonight: {e}")
            logger.error(f"  Trends Tonight error: {e}")

    # === FRONTEND API BACKEND EXPORTERS (Session 143) ===

    # Tonight's Trend Plays (hourly on game days)
    if 'tonight-trend-plays' in export_types:
        try:
            exporter = TonightTrendPlaysExporter()
            path = exporter.export(game_date=target_date)
            result['paths']['tonight_trend_plays'] = path
            logger.info(f"  Tonight Trend Plays: {path}")
        except Exception as e:
            result['errors'].append(f"tonight-trend-plays: {e}")
            logger.error(f"  Tonight Trend Plays error: {e}")

    # === LIVE SCORING FOR CHALLENGE SYSTEM ===

    # Live scores (every 2-5 minutes during game windows)
    if 'live' in export_types:
        try:
            exporter = LiveScoresExporter()
            path = exporter.export(target_date, update_latest=update_latest)
            result['paths']['live'] = path
            logger.info(f"  Live Scores: {path}")
        except Exception as e:
            result['errors'].append(f"live: {e}")
            logger.error(f"  Live Scores error: {e}")

    # Live grading (every 2-5 minutes during game windows)
    if 'live-grading' in export_types:
        try:
            exporter = LiveGradingExporter()
            path = exporter.export(target_date, update_latest=update_latest)
            result['paths']['live_grading'] = path
            logger.info(f"  Live Grading: {path}")
        except Exception as e:
            result['errors'].append(f"live-grading: {e}")
            logger.error(f"  Live Grading error: {e}")

    if result['errors']:
        result['status'] = 'partial' if result['paths'] else 'failed'

    return result


def export_players(min_games: int = 5) -> dict:
    """
    Export all player profiles.

    Args:
        min_games: Minimum games to include player

    Returns:
        Dict with export status
    """
    logger.info(f"Exporting player profiles (min_games={min_games})")

    exporter = PlayerProfileExporter()

    result = {
        'status': 'success',
        'paths': []
    }

    try:
        paths = exporter.export_all_players(min_games=min_games)
        result['paths'] = paths
        result['count'] = len(paths)
        logger.info(f"Exported {len(paths)} player profiles")
    except Exception as e:
        result['status'] = 'failed'
        result['error'] = str(e)
        logger.error(f"Player export error: {e}")

    return result


def run_backfill(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    backfill_all: bool = False,
    export_types: Optional[List[str]] = None
):
    """
    Backfill exports for a date range.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        backfill_all: If True, export all dates with predictions
        export_types: List of types to export (default: all)
    """
    # Get dates to process
    if backfill_all:
        dates = get_dates_with_predictions()
        logger.info(f"Backfilling all {len(dates)} dates with predictions")
    else:
        # Generate date range
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        logger.info(f"Backfilling {len(dates)} dates from {start_date} to {end_date}")

    if export_types:
        logger.info(f"Export types: {export_types}")

    # Process each date
    successful = 0
    partial = 0
    failed = 0

    for i, target_date in enumerate(dates):
        logger.info(f"[{i+1}/{len(dates)}] Exporting {target_date}")

        # Only update latest.json for the most recent date
        update_latest = (target_date == dates[-1])
        result = export_date(target_date, update_latest=update_latest, export_types=export_types)

        if result['status'] == 'success':
            successful += 1
        elif result['status'] == 'partial':
            partial += 1
        else:
            failed += 1

    # Summary
    logger.info("=" * 60)
    logger.info("BACKFILL COMPLETE")
    logger.info(f"  Successful: {successful}")
    logger.info(f"  Partial: {partial}")
    logger.info(f"  Failed: {failed}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Phase 6 Daily Export - Export predictions to GCS JSON'
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Single date to export (YYYY-MM-DD). Default: yesterday'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date for backfill (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date for backfill (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--backfill-all',
        action='store_true',
        help='Backfill all dates with graded predictions'
    )
    parser.add_argument(
        '--only',
        type=str,
        help=f'Comma-separated list of export types: {",".join(EXPORT_TYPES)}'
    )
    parser.add_argument(
        '--players',
        action='store_true',
        help='Export player profiles instead of daily data'
    )
    parser.add_argument(
        '--min-games',
        type=int,
        default=5,
        help='Minimum games for player profiles (default: 5)'
    )

    args = parser.parse_args()

    # Parse export types
    export_types = None
    if args.only:
        export_types = [t.strip() for t in args.only.split(',')]
        invalid = [t for t in export_types if t not in EXPORT_TYPES]
        if invalid:
            logger.error(f"Invalid export types: {invalid}. Valid: {EXPORT_TYPES}")
            sys.exit(1)

    # Handle player profiles separately
    if args.players:
        result = export_players(min_games=args.min_games)
        if result['status'] == 'success':
            logger.info(f"Player export complete: {result['count']} profiles")
        else:
            logger.error(f"Player export failed: {result.get('error')}")
            sys.exit(1)
        return

    # Determine mode
    if args.backfill_all:
        run_backfill(backfill_all=True, export_types=export_types)
    elif args.start_date and args.end_date:
        run_backfill(start_date=args.start_date, end_date=args.end_date, export_types=export_types)
    elif args.date:
        result = export_date(args.date, export_types=export_types)
        if result['status'] == 'success':
            logger.info(f"Export complete: {result['paths']}")
        elif result['status'] == 'partial':
            logger.warning(f"Export partial: {result['paths']}, errors: {result['errors']}")
        else:
            logger.error(f"Export failed: {result.get('errors')}")
            sys.exit(1)
    else:
        # Default: yesterday
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        logger.info(f"No date specified, exporting yesterday: {yesterday}")
        result = export_date(yesterday, export_types=export_types)
        if result['status'] == 'success':
            logger.info(f"Export complete: {result['paths']}")
        elif result['status'] == 'partial':
            logger.warning(f"Export partial: {result['paths']}, errors: {result['errors']}")
        else:
            logger.error(f"Export failed: {result.get('errors')}")
            sys.exit(1)


if __name__ == '__main__':
    main()
