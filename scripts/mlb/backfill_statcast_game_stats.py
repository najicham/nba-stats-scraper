#!/usr/bin/env python3
"""
Backfill Statcast Pitcher Game Stats
=====================================
Fetches per-game pitch-level stats from Baseball Savant via pybaseball.

Usage:
    # Backfill specific date range
    python scripts/mlb/backfill_statcast_game_stats.py --start 2024-04-01 --end 2024-04-30

    # Backfill full season
    python scripts/mlb/backfill_statcast_game_stats.py --season 2024

    # Dry run (no upload)
    python scripts/mlb/backfill_statcast_game_stats.py --season 2024 --dry-run
"""

import argparse
import logging
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def normalize_name(name: str) -> str:
    """Convert player name to normalized format: firstname_lastname

    Handles both formats:
    - 'Clayton Kershaw' -> 'clayton_kershaw'
    - 'Kershaw, Clayton' -> 'clayton_kershaw' (pybaseball format)
    """
    if not name:
        return ''
    name = name.strip()
    # Check for 'Lastname, Firstname' format (pybaseball returns this)
    if ', ' in name:
        parts = name.split(', ')
        if len(parts) == 2:
            name = f'{parts[1]} {parts[0]}'  # Flip to Firstname Lastname
    return re.sub(r'[^a-z]', '_', name.lower()).strip('_')


def classify_pitch_type(pitch_type) -> str:
    """Classify pitch into category"""
    if pitch_type is None or (isinstance(pitch_type, float) and pd.isna(pitch_type)):
        return 'unknown'
    if not isinstance(pitch_type, str):
        return 'unknown'
    pitch_type = pitch_type.upper()

    fastballs = ['FF', 'SI', 'FC', 'FA']  # 4-seam, sinker, cutter, generic fastball
    breaking = ['SL', 'CU', 'KC', 'CS', 'SV', 'ST']  # slider, curve, knuckle curve, sweeper
    offspeed = ['CH', 'FS', 'FO', 'SC']  # changeup, splitter, forkball, screwball

    if pitch_type in fastballs:
        return 'fastball'
    elif pitch_type in breaking:
        return 'breaking'
    elif pitch_type in offspeed:
        return 'offspeed'
    return 'other'


def is_swinging_strike(description) -> bool:
    """Check if pitch result is swinging strike"""
    if description is None or (isinstance(description, float) and pd.isna(description)):
        return False
    if not isinstance(description, str):
        return False
    desc_lower = description.lower()
    return 'swinging_strike' in desc_lower or 'missed_bunt' in desc_lower


def is_swing(description) -> bool:
    """Check if batter swung (foul, in play, or whiff)"""
    if description is None or (isinstance(description, float) and pd.isna(description)):
        return False
    if not isinstance(description, str):
        return False
    desc_lower = description.lower()
    swing_outcomes = ['swinging_strike', 'foul', 'in_play', 'hit_into_play', 'missed_bunt']
    return any(outcome in desc_lower for outcome in swing_outcomes)


def is_called_strike(description) -> bool:
    """Check if pitch was called strike"""
    if description is None or (isinstance(description, float) and pd.isna(description)):
        return False
    if not isinstance(description, str):
        return False
    return 'called_strike' in description.lower()


def fetch_statcast_data(start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch statcast pitch data from Baseball Savant via pybaseball."""
    from pybaseball import statcast

    logger.info(f"Fetching statcast data: {start_date} to {end_date}")

    try:
        # pybaseball handles chunking for large date ranges
        df = statcast(start_dt=start_date, end_dt=end_date)

        if df is None or len(df) == 0:
            logger.warning(f"No data returned for {start_date} to {end_date}")
            return pd.DataFrame()

        logger.info(f"Fetched {len(df):,} pitches")
        return df

    except Exception as e:
        logger.error(f"Failed to fetch statcast data: {e}")
        return pd.DataFrame()


def aggregate_pitcher_game_stats(pitches_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate pitch-level data to per-game per-pitcher stats."""

    if pitches_df.empty:
        return pd.DataFrame()

    logger.info("Aggregating to pitcher-game level...")

    # Ensure required columns exist
    required_cols = ['game_date', 'game_pk', 'pitcher', 'player_name', 'description',
                     'release_speed', 'pitch_type', 'home_team', 'away_team', 'inning_topbot']

    missing = [col for col in required_cols if col not in pitches_df.columns]
    if missing:
        logger.warning(f"Missing columns: {missing}")

    # Add derived columns
    pitches_df['is_swinging_strike'] = pitches_df['description'].apply(is_swinging_strike)
    pitches_df['is_swing'] = pitches_df['description'].apply(is_swing)
    pitches_df['is_called_strike'] = pitches_df['description'].apply(is_called_strike)
    pitches_df['pitch_category'] = pitches_df['pitch_type'].apply(classify_pitch_type)
    pitches_df['is_fastball'] = pitches_df['pitch_category'] == 'fastball'

    # Group by game + pitcher
    grouped = pitches_df.groupby(['game_date', 'game_pk', 'pitcher', 'player_name'])

    # Basic aggregation
    agg_stats = grouped.agg(
        total_pitches=('description', 'count'),
        total_swings=('is_swing', 'sum'),
        swinging_strikes=('is_swinging_strike', 'sum'),
        called_strikes=('is_called_strike', 'sum'),
        fb_pitch_count=('is_fastball', 'sum'),
        all_pitch_velocity_avg=('release_speed', 'mean'),

        # Use first row for team info (same for all pitches in game)
        home_team=('home_team', 'first'),
        away_team=('away_team', 'first'),
        inning_topbot=('inning_topbot', 'first'),  # Top = away pitching, Bot = home pitching
    ).reset_index()

    # Calculate fastball velocity separately (filter to fastballs only)
    fb_only = pitches_df[pitches_df['is_fastball'] == True]
    if not fb_only.empty:
        fb_velo = fb_only.groupby(['game_date', 'game_pk', 'pitcher']).agg(
            fb_velocity_avg=('release_speed', 'mean'),
            fb_velocity_max=('release_speed', 'max'),
            fb_velocity_min=('release_speed', 'min'),
        ).reset_index()
        agg_stats = agg_stats.merge(
            fb_velo,
            on=['game_date', 'game_pk', 'pitcher'],
            how='left'
        )
    else:
        agg_stats['fb_velocity_avg'] = None
        agg_stats['fb_velocity_max'] = None
        agg_stats['fb_velocity_min'] = None

    # Calculate derived metrics
    agg_stats['swstr_pct'] = agg_stats['swinging_strikes'] / agg_stats['total_pitches']
    agg_stats['whiff_pct'] = agg_stats.apply(
        lambda x: x['swinging_strikes'] / x['total_swings'] if x['total_swings'] > 0 else 0,
        axis=1
    )
    agg_stats['csw_count'] = agg_stats['called_strikes'] + agg_stats['swinging_strikes']
    agg_stats['csw_pct'] = agg_stats['csw_count'] / agg_stats['total_pitches']

    # Determine if home pitcher
    agg_stats['is_home'] = agg_stats['inning_topbot'].apply(lambda x: x == 'Bot' if x else None)
    agg_stats['team_abbr'] = agg_stats.apply(
        lambda x: x['home_team'] if x['is_home'] else x['away_team'], axis=1
    )
    agg_stats['opponent_abbr'] = agg_stats.apply(
        lambda x: x['away_team'] if x['is_home'] else x['home_team'], axis=1
    )

    # Add metadata
    agg_stats['pitcher_id'] = agg_stats['pitcher']
    agg_stats['pitcher_name'] = agg_stats['player_name']
    agg_stats['player_lookup'] = agg_stats['player_name'].apply(normalize_name)
    agg_stats['season_year'] = pd.to_datetime(agg_stats['game_date']).dt.year

    # Calculate pitch mix from original data
    pitch_mix = pitches_df.groupby(['game_date', 'game_pk', 'pitcher']).apply(
        lambda x: pd.Series({
            'fastball_pct': (x['pitch_category'] == 'fastball').mean(),
            'breaking_pct': (x['pitch_category'] == 'breaking').mean(),
            'offspeed_pct': (x['pitch_category'] == 'offspeed').mean(),
        })
    ).reset_index()

    # Merge pitch mix
    agg_stats = agg_stats.merge(
        pitch_mix,
        on=['game_date', 'game_pk', 'pitcher'],
        how='left'
    )

    # Select final columns
    final_cols = [
        'game_date', 'game_pk', 'pitcher_id', 'pitcher_name', 'player_lookup',
        'team_abbr', 'opponent_abbr', 'is_home',
        'total_pitches', 'total_swings', 'swinging_strikes',
        'swstr_pct', 'whiff_pct',
        'called_strikes', 'csw_count', 'csw_pct',
        'fb_velocity_avg', 'fb_velocity_max', 'fb_velocity_min', 'fb_pitch_count',
        'all_pitch_velocity_avg',
        'fastball_pct', 'breaking_pct', 'offspeed_pct',
        'season_year'
    ]

    result = agg_stats[[col for col in final_cols if col in agg_stats.columns]]

    logger.info(f"Aggregated to {len(result):,} pitcher-game records")
    return result


def load_to_bigquery(df: pd.DataFrame, project_id: str = 'nba-props-platform') -> int:
    """Load aggregated stats to BigQuery."""

    if df.empty:
        return 0

    client = bigquery.Client(project=project_id)
    table_id = f'{project_id}.mlb_raw.statcast_pitcher_game_stats'

    # Convert date column
    df['game_date'] = pd.to_datetime(df['game_date']).dt.date

    # Add metadata
    df['source_file_path'] = 'pybaseball_statcast'
    df['created_at'] = datetime.utcnow()
    df['processed_at'] = datetime.utcnow()

    # Handle NaN values
    df = df.where(pd.notnull(df), None)

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
    )

    try:
        job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
        job.result()
        logger.info(f"Loaded {len(df):,} rows to {table_id}")
        return len(df)
    except Exception as e:
        logger.error(f"Failed to load to BigQuery: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description='Backfill Statcast pitcher game stats')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--season', type=int, help='Season year to backfill')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no upload)')
    args = parser.parse_args()

    # Determine date range
    if args.season:
        start_date = f'{args.season}-03-28'  # Spring training/opening day
        end_date = f'{args.season}-10-01'    # End of regular season
    elif args.start and args.end:
        start_date = args.start
        end_date = args.end
    else:
        print("Error: Specify --season or --start/--end")
        sys.exit(1)

    logger.info(f"Backfilling statcast data: {start_date} to {end_date}")

    # Process in monthly chunks to avoid memory issues
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    total_rows = 0
    current = start

    while current < end:
        chunk_end = min(current + timedelta(days=30), end)

        chunk_start_str = current.strftime('%Y-%m-%d')
        chunk_end_str = chunk_end.strftime('%Y-%m-%d')

        logger.info(f"\n{'='*60}")
        logger.info(f"Processing chunk: {chunk_start_str} to {chunk_end_str}")

        # Fetch data
        pitches_df = fetch_statcast_data(chunk_start_str, chunk_end_str)

        if pitches_df.empty:
            logger.warning(f"No data for chunk, skipping")
            current = chunk_end + timedelta(days=1)
            continue

        # Aggregate
        game_stats_df = aggregate_pitcher_game_stats(pitches_df)

        if game_stats_df.empty:
            logger.warning(f"No aggregated data, skipping")
            current = chunk_end + timedelta(days=1)
            continue

        # Preview
        logger.info(f"\nSample data:")
        sample = game_stats_df.head(3)
        for _, row in sample.iterrows():
            logger.info(f"  {row['pitcher_name']}: {row['total_pitches']} pitches, "
                       f"SwStr%={row['swstr_pct']:.1%}, FB velo={row.get('fb_velocity_avg', 0):.1f}")

        # Load to BigQuery
        if not args.dry_run:
            rows = load_to_bigquery(game_stats_df)
            total_rows += rows
        else:
            logger.info(f"[DRY RUN] Would load {len(game_stats_df):,} rows")
            total_rows += len(game_stats_df)

        current = chunk_end + timedelta(days=1)

    logger.info(f"\n{'='*60}")
    logger.info(f"COMPLETE: Processed {total_rows:,} total pitcher-game records")


if __name__ == '__main__':
    main()
