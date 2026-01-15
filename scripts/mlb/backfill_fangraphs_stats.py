#!/usr/bin/env python3
"""
Backfill FanGraphs Pitcher Season Stats
========================================
Fetches season-level pitching stats from FanGraphs via pybaseball
and loads them into BigQuery.

Key metrics for K prediction:
- SwStr% (Swinging Strike %): Leading indicator of K ability
- CSW% (Called Strike + Whiff %): Overall strike effectiveness

Usage:
    # Backfill 2024-2025 seasons
    PYTHONPATH=. python scripts/mlb/backfill_fangraphs_stats.py --seasons 2024 2025

    # Backfill single season
    PYTHONPATH=. python scripts/mlb/backfill_fangraphs_stats.py --season 2025

    # Include non-qualified pitchers (more rows)
    PYTHONPATH=. python scripts/mlb/backfill_fangraphs_stats.py --season 2025 --qual 0
"""

import argparse
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from google.cloud import bigquery

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import pybaseball
try:
    from pybaseball import pitching_stats, cache
    cache.enable()
except ImportError:
    logger.error("pybaseball not installed. Run: pip install pybaseball")
    sys.exit(1)


# BigQuery config
PROJECT_ID = "nba-props-platform"
DATASET = "mlb_raw"
TABLE = "fangraphs_pitcher_season_stats"
FULL_TABLE_ID = f"{PROJECT_ID}.{DATASET}.{TABLE}"


def normalize_player_name(name: str) -> str:
    """Normalize player name to lowercase, no spaces/punctuation."""
    if not name:
        return ""
    # Remove Jr., Sr., III, etc.
    name = re.sub(r'\s+(jr\.?|sr\.?|ii+|iv|v)$', '', name, flags=re.IGNORECASE)
    # Remove punctuation and spaces
    name = re.sub(r'[^a-zA-Z]', '', name)
    return name.lower()


def fetch_fangraphs_data(season: int, qual: int = 1) -> Optional[pd.DataFrame]:
    """
    Fetch FanGraphs pitching stats for a season.

    Args:
        season: Year to fetch
        qual: Minimum innings qualifier (1=qualified, 0=all pitchers)

    Returns:
        DataFrame with pitching stats or None if error
    """
    logger.info(f"Fetching FanGraphs pitching stats for {season} (qual={qual})...")

    try:
        df = pitching_stats(season, qual=qual)

        if df is None or df.empty:
            logger.warning(f"No data returned for {season}")
            return None

        logger.info(f"Retrieved {len(df)} pitchers for {season}")

        # Log available columns for debugging
        swstr_cols = [c for c in df.columns if 'sw' in c.lower() or 'whiff' in c.lower()]
        logger.info(f"SwStr-related columns: {swstr_cols}")

        return df

    except Exception as e:
        logger.error(f"Error fetching FanGraphs data: {e}")
        return None


def transform_data(df: pd.DataFrame, season: int) -> pd.DataFrame:
    """
    Transform FanGraphs data to match BigQuery schema.
    """
    logger.info("Transforming data...")

    # Column mapping (FanGraphs name -> BigQuery name)
    column_mapping = {
        'IDfg': 'fangraphs_id',
        'Name': 'player_name',
        'Team': 'team',
        'Age': 'age',
        'G': 'games',
        'GS': 'games_started',
        'W': 'wins',
        'L': 'losses',
        'SV': 'saves',
        'IP': 'innings_pitched',
        'SO': 'strikeouts',
        'K/9': 'k_per_9',
        'K%': 'k_pct',
        'BB/9': 'bb_per_9',
        'BB%': 'bb_pct',
        'K/BB': 'k_bb_ratio',
        'SwStr%': 'swstr_pct',
        'CSW%': 'csw_pct',
        'O-Swing%': 'o_swing_pct',
        'Z-Swing%': 'z_swing_pct',
        'Swing%': 'swing_pct',
        'Contact%': 'contact_pct',
        'Z-Contact%': 'z_contact_pct',
        'O-Contact%': 'o_contact_pct',
        'ERA': 'era',
        'WHIP': 'whip',
        'FIP': 'fip',
        'xFIP': 'xfip',
        'GB%': 'gb_pct',
        'FB%': 'fb_pct',
        'LD%': 'ld_pct',
        'HR/FB': 'hr_per_fb',
        'WAR': 'war',
    }

    # Create output dataframe
    output = pd.DataFrame()

    for fg_col, bq_col in column_mapping.items():
        if fg_col in df.columns:
            output[bq_col] = df[fg_col]
        else:
            output[bq_col] = None

    # Add derived columns
    output['player_lookup'] = output['player_name'].apply(normalize_player_name)
    output['season_year'] = season
    output['snapshot_date'] = datetime.now(timezone.utc).date().isoformat()
    output['created_at'] = datetime.now(timezone.utc).isoformat()
    output['processed_at'] = datetime.now(timezone.utc).isoformat()

    # Convert percentage columns (FanGraphs returns as decimals like 0.12 for 12%)
    pct_columns = [
        'k_pct', 'bb_pct', 'swstr_pct', 'csw_pct',
        'o_swing_pct', 'z_swing_pct', 'swing_pct',
        'contact_pct', 'z_contact_pct', 'o_contact_pct',
        'gb_pct', 'fb_pct', 'ld_pct', 'hr_per_fb'
    ]
    for col in pct_columns:
        if col in output.columns and output[col] is not None:
            # FanGraphs already returns as decimals (0.12), no need to divide
            output[col] = pd.to_numeric(output[col], errors='coerce')

    # Clean up any NaN values
    output = output.replace({float('nan'): None})

    logger.info(f"Transformed {len(output)} rows")

    # Log sample SwStr% values
    if 'swstr_pct' in output.columns:
        valid_swstr = output['swstr_pct'].dropna()
        if len(valid_swstr) > 0:
            logger.info(f"SwStr% range: {valid_swstr.min():.3f} - {valid_swstr.max():.3f}")
            logger.info(f"SwStr% mean: {valid_swstr.mean():.3f}")

    return output


def load_to_bigquery(df: pd.DataFrame, project_id: str = PROJECT_ID) -> int:
    """
    Load data to BigQuery.

    Returns:
        Number of rows loaded
    """
    logger.info(f"Loading {len(df)} rows to {FULL_TABLE_ID}...")

    client = bigquery.Client(project=project_id)

    # Configure job
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema_update_options=[
            bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION,
        ],
    )

    # Load data
    job = client.load_table_from_dataframe(df, FULL_TABLE_ID, job_config=job_config)
    job.result()  # Wait for completion

    logger.info(f"Loaded {job.output_rows} rows to BigQuery")
    return job.output_rows


def main():
    parser = argparse.ArgumentParser(description='Backfill FanGraphs pitcher stats')
    parser.add_argument('--season', type=int, help='Single season to fetch')
    parser.add_argument('--seasons', type=int, nargs='+', help='Multiple seasons to fetch')
    parser.add_argument('--qual', type=int, default=1,
                       help='Minimum IP qualifier (1=qualified, 0=all)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Fetch and transform but do not load to BigQuery')

    args = parser.parse_args()

    # Determine which seasons to process
    if args.seasons:
        seasons = args.seasons
    elif args.season:
        seasons = [args.season]
    else:
        # Default: 2024 and 2025
        seasons = [2024, 2025]

    logger.info(f"Processing seasons: {seasons}")

    total_rows = 0

    for season in seasons:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {season}")
        logger.info('='*60)

        # Fetch data
        df = fetch_fangraphs_data(season, qual=args.qual)
        if df is None:
            continue

        # Transform
        df_transformed = transform_data(df, season)

        # Sample output
        if 'swstr_pct' in df_transformed.columns:
            sample = df_transformed[['player_name', 'team', 'swstr_pct', 'k_per_9', 'strikeouts']].head(10)
            logger.info(f"\nSample data:\n{sample.to_string()}")

        if args.dry_run:
            logger.info("DRY RUN - not loading to BigQuery")
            logger.info(f"Would load {len(df_transformed)} rows")
        else:
            # Load to BigQuery
            rows = load_to_bigquery(df_transformed)
            total_rows += rows

    logger.info(f"\n{'='*60}")
    logger.info(f"COMPLETE: Loaded {total_rows} total rows")
    logger.info('='*60)


if __name__ == '__main__':
    main()
