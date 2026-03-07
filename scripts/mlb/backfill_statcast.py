#!/usr/bin/env python3
"""Backfill MLB Statcast daily pitcher data directly to BigQuery.

One-time script to fill the Jul 1 - Sep 28, 2025 gap.
Uses pybaseball.statcast() and writes directly to BQ, bypassing GCS/Pub/Sub.

Usage:
    PYTHONPATH=. python scripts/mlb/backfill_statcast.py --start 2025-07-01 --end 2025-09-28
    PYTHONPATH=. python scripts/mlb/backfill_statcast.py --start 2025-07-01 --end 2025-07-07 --dry-run
"""

import argparse
import hashlib
import json
import logging
import math
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery
from pybaseball import statcast, cache

cache.enable()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
TABLE_ID = f'{PROJECT_ID}.mlb_raw.statcast_pitcher_daily'

SWINGING_STRIKE_DESCRIPTIONS = frozenset(["swinging_strike", "swinging_strike_blocked"])
CALLED_STRIKE_DESCRIPTIONS = frozenset(["called_strike"])
FOUL_DESCRIPTIONS = frozenset(["foul", "foul_tip"])
BALL_DESCRIPTIONS = frozenset(["ball", "blocked_ball", "hit_by_pitch"])
IN_PLAY_DESCRIPTIONS = frozenset(["hit_into_play", "hit_into_play_no_out", "hit_into_play_score"])
SWING_DESCRIPTIONS = SWINGING_STRIKE_DESCRIPTIONS | FOUL_DESCRIPTIONS | IN_PLAY_DESCRIPTIONS
FASTBALL_TYPES = frozenset(["FF", "SI", "FC"])


def safe_round(value: Any, decimals: int = 1) -> Optional[float]:
    if value is None:
        return None
    try:
        if math.isnan(value) or math.isinf(value):
            return None
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return None


def safe_div(num: int, denom: int, scale: float = 100.0) -> Optional[float]:
    if denom == 0:
        return None
    return safe_round(num / denom * scale)


def normalize_name(name: str) -> str:
    if not name:
        return ""
    if ',' in name:
        parts = name.split(',', 1)
        name = f"{parts[1].strip()} {parts[0].strip()}"
    return re.sub(r'[^a-z0-9]', '', name.lower())


def compute_hash(row: Dict) -> str:
    fields = [str(row.get(f, '')) for f in
              ['pitcher_id', 'game_date', 'total_pitches', 'swstr_pct', 'csw_pct', 'whiff_rate', 'avg_velocity']]
    return hashlib.md5('|'.join(fields).encode()).hexdigest()


def aggregate_pitcher(df, pitcher_id, game_pk) -> Optional[Dict]:
    """Aggregate pitch-level data for one pitcher outing."""
    import pandas as pd

    total_pitches = len(df)
    if total_pitches == 0:
        return None

    pitcher_name = None
    if "player_name" in df.columns:
        names = df["player_name"].dropna()
        if not names.empty:
            pitcher_name = str(names.iloc[0])

    game_date = None
    if "game_date" in df.columns:
        dates = df["game_date"].dropna()
        if not dates.empty:
            game_date = str(dates.iloc[0])[:10]

    # Velocity
    avg_velocity = max_velocity = None
    if "release_speed" in df.columns:
        max_velocity = safe_round(df["release_speed"].max())
        if "pitch_type" in df.columns:
            fb = df[df["pitch_type"].isin(FASTBALL_TYPES)]
            if not fb.empty:
                avg_velocity = safe_round(fb["release_speed"].mean())

    # Spin
    avg_spin_rate = None
    if "release_spin_rate" in df.columns:
        avg_spin_rate = safe_round(df["release_spin_rate"].mean(), 0)

    # Pitch outcomes
    desc = df["description"] if "description" in df.columns else pd.Series(dtype=str)
    ss = int(desc.isin(SWINGING_STRIKE_DESCRIPTIONS).sum())
    cs = int(desc.isin(CALLED_STRIKE_DESCRIPTIONS).sum())
    fouls = int(desc.isin(FOUL_DESCRIPTIONS).sum())
    balls = int(desc.isin(BALL_DESCRIPTIONS).sum())
    ip = int(desc.isin(IN_PLAY_DESCRIPTIONS).sum())

    swstr_pct = safe_div(ss, total_pitches)
    csw_pct = safe_div(cs + ss, total_pitches)
    total_swings = ss + fouls + ip
    whiff_rate = safe_div(ss, total_swings)

    # Zone
    zone_pct = chase_rate = None
    zone_pitches = chase_swings = out_of_zone = 0
    if "zone" in df.columns:
        zs = pd.to_numeric(df["zone"], errors="coerce")
        zone_pitches = int(zs.between(1, 9).sum())
        zone_pct = safe_div(zone_pitches, total_pitches)
        ooz_mask = zs > 9
        out_of_zone = int(ooz_mask.sum())
        if out_of_zone > 0 and "description" in df.columns:
            chase_swings = int(df[ooz_mask]["description"].isin(SWING_DESCRIPTIONS).sum())
            chase_rate = safe_div(chase_swings, out_of_zone)

    # Pitch types
    pitch_types = {}
    if "pitch_type" in df.columns:
        counts = df["pitch_type"].value_counts()
        pitch_types = {str(k): int(v) for k, v in counts.items() if pd.notna(k)}

    row = {
        'game_date': game_date,
        'game_pk': int(game_pk) if game_pk is not None else None,
        'pitcher_id': int(pitcher_id),
        'pitcher_name': pitcher_name,
        'player_lookup': normalize_name(pitcher_name or ''),
        'total_pitches': total_pitches,
        'swinging_strikes': ss,
        'called_strikes': cs,
        'fouls': fouls,
        'balls': balls,
        'in_play': ip,
        'avg_velocity': avg_velocity,
        'max_velocity': max_velocity,
        'avg_spin_rate': avg_spin_rate,
        'swstr_pct': swstr_pct,
        'csw_pct': csw_pct,
        'whiff_rate': whiff_rate,
        'zone_pct': zone_pct,
        'chase_rate': chase_rate,
        'pitch_types': json.dumps(pitch_types) if pitch_types else None,
        'source_file_path': 'backfill_statcast.py',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'processed_at': datetime.now(timezone.utc).isoformat(),
    }
    row['data_hash'] = compute_hash(row)
    return row


def fetch_and_aggregate(target_date: str) -> List[Dict]:
    """Fetch Statcast for a date and return BQ-ready rows."""
    import pandas as pd

    try:
        df = statcast(start_dt=target_date, end_dt=target_date)
    except Exception as e:
        logger.error(f"Failed to fetch {target_date}: {e}")
        return []

    if df is None or df.empty:
        return []

    rows = []
    group_cols = ["pitcher"]
    if "game_pk" in df.columns:
        group_cols.append("game_pk")

    for group_key, pitcher_df in df.groupby(group_cols):
        if len(group_cols) == 2:
            pid, gpk = group_key
        else:
            pid, gpk = group_key, None
        row = aggregate_pitcher(pitcher_df, pid, gpk)
        if row:
            rows.append(row)

    return rows


def write_to_bq(bq_client: bigquery.Client, rows: List[Dict], game_date: str) -> int:
    """Write rows to BQ with deduplication delete."""
    if not rows:
        return 0

    # Delete existing for this date
    pitcher_ids = [r['pitcher_id'] for r in rows]
    ids_str = ', '.join(str(p) for p in pitcher_ids)
    try:
        bq_client.query(
            f"DELETE FROM `{TABLE_ID}` WHERE game_date = '{game_date}' AND pitcher_id IN ({ids_str})"
        ).result(timeout=60)
    except Exception as e:
        if 'not found' not in str(e).lower():
            logger.warning(f"Delete failed for {game_date}: {e}")

    # Load
    table = bq_client.get_table(TABLE_ID)
    job_config = bigquery.LoadJobConfig(
        schema=table.schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = bq_client.load_table_from_json(rows, TABLE_ID, job_config=job_config)
    job.result(timeout=120)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description='Backfill MLB Statcast data to BQ')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Fetch but do not write')
    parser.add_argument('--sleep', type=float, default=3.0, help='Seconds between dates')
    args = parser.parse_args()

    start = datetime.strptime(args.start, '%Y-%m-%d').date()
    end = datetime.strptime(args.end, '%Y-%m-%d').date()
    total_days = (end - start).days + 1

    logger.info(f"Backfill: {args.start} to {args.end} ({total_days} days)")

    bq_client = None if args.dry_run else bigquery.Client(project=PROJECT_ID)
    total_rows = 0
    days_with_data = 0
    errors = 0

    d = start
    day_num = 0
    while d <= end:
        day_num += 1
        ds = d.strftime('%Y-%m-%d')

        try:
            rows = fetch_and_aggregate(ds)
            if rows:
                if not args.dry_run:
                    n = write_to_bq(bq_client, rows, ds)
                    total_rows += n
                else:
                    total_rows += len(rows)
                days_with_data += 1
                logger.info(f"[{day_num}/{total_days}] {ds}: {len(rows)} pitchers")
            else:
                logger.info(f"[{day_num}/{total_days}] {ds}: no games")
        except Exception as e:
            logger.error(f"[{day_num}/{total_days}] {ds}: ERROR - {e}")
            errors += 1

        d += timedelta(days=1)
        if d <= end:
            time.sleep(args.sleep)

    mode = "DRY RUN" if args.dry_run else "WRITTEN"
    logger.info(
        f"\nBackfill complete ({mode}): {total_rows} pitcher records "
        f"across {days_with_data} game days, {errors} errors"
    )


if __name__ == '__main__':
    main()
