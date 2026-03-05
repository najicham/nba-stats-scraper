#!/usr/bin/env python3
"""
Backfill Experiment Features

Populates nba_predictions.ml_feature_store_experiment with candidate features
from raw scraper tables. Long/narrow schema: one row per (player, game_date,
experiment_id, feature_name).

Experiments:
  tracking_v1      - NBA tracking stats (touches, drives, usage, etc.)
  pace_v1          - TeamRankings team pace and efficiency
  dvp_v1           - Hashtag Basketball defense-vs-position
  projections_v1   - NumberFire + Dimers projected points
  sharp_money_v1   - VSiN betting splits (public %, money %)
  derived_v1       - Player volatility & consistency (from player_game_summary)
  interactions_v1  - Cross-feature interactions (from ml_feature_store_v2)
  line_history_v1  - Line-based derived features (from ml_feature_store_v2)

Usage:
  PYTHONPATH=. python bin/backfill_experiment_features.py --experiment tracking_v1
  PYTHONPATH=. python bin/backfill_experiment_features.py --experiment all
  PYTHONPATH=. python bin/backfill_experiment_features.py --experiment tracking_v1 --start 2026-01-01 --end 2026-03-04
  PYTHONPATH=. python bin/backfill_experiment_features.py --list
  PYTHONPATH=. python bin/backfill_experiment_features.py --experiment tracking_v1 --dry-run

Session 407 - Experiment Feature Infrastructure
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from datetime import date, timedelta
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"
EXPERIMENT_TABLE = f"{PROJECT_ID}.nba_predictions.ml_feature_store_experiment"


def normalize_lookup(name):
    """Normalize player_lookup to feature store format (no hyphens, lowercase)."""
    if not name:
        return name
    return name.replace('-', '').replace(' ', '').lower()

EXPERIMENTS = {
    "tracking_v1": {
        "description": "NBA tracking stats (touches, drives, usage, catch-and-shoot, etc.)",
        "type": "static",
        "source_table": "nba_raw.nba_tracking_stats",
        "features": [
            "tracking_touches",
            "tracking_drives",
            "tracking_catch_shoot_pct",
            "tracking_pull_up_pct",
            "tracking_paint_touches",
            "tracking_usage_pct",
        ],
    },
    "pace_v1": {
        "description": "TeamRankings team pace and efficiency ratings",
        "type": "static",
        "source_table": "nba_raw.teamrankings_team_stats",
        "features": [
            "team_pace_tr",
            "opp_pace_tr",
            "pace_ratio_tr",
            "opp_off_eff_tr",
            "opp_def_eff_tr",
        ],
    },
    "dvp_v1": {
        "description": "Hashtag Basketball defense-vs-position points allowed",
        "type": "daily",
        "source_table": "nba_raw.hashtagbasketball_dvp",
        "features": [
            "dvp_points_rank_norm",
            "dvp_points_allowed",
        ],
    },
    "projections_v1": {
        "description": "Projection consensus (NumberFire + Dimers projected points)",
        "type": "daily",
        "source_table": "nba_raw.numberfire_projections",
        "features": [
            "projection_consensus_pts",
            "projection_consensus_delta",
            "projection_n_sources",
        ],
    },
    "sharp_money_v1": {
        "description": "VSiN public betting splits (ticket % vs money %)",
        "type": "daily",
        "source_table": "nba_raw.vsin_betting_splits",
        "features": [
            "sharp_money_divergence",
            "over_ticket_pct",
            "over_money_pct",
        ],
    },
    "derived_v1": {
        "description": "Player volatility & consistency (from player_game_summary)",
        "type": "derived",
        "source_table": "nba_analytics.player_game_summary",
        "features": [
            "pts_std_last_5",
            "pts_std_last_10",
            "form_ratio",
            "over_rate_weighted",
        ],
    },
    "interactions_v1": {
        "description": "Cross-feature interactions (from ml_feature_store_v2)",
        "type": "derived",
        "source_table": "nba_predictions.ml_feature_store_v2",
        "features": [
            "fatigue_x_minutes",
            "pace_x_usage",
            "rest_x_b2b",
            "spread_x_home",
        ],
    },
    "line_history_v1": {
        "description": "Line-based derived features (from ml_feature_store_v2)",
        "type": "derived",
        "source_table": "nba_predictions.ml_feature_store_v2",
        "features": [
            "line_vs_avg",
            "opening_vs_current",
            "line_range",
        ],
    },
}


def get_client():
    return bigquery.Client(project=PROJECT_ID)


def clear_experiment(client, experiment_id, start_date, end_date):
    """Delete existing rows for an experiment in the date range."""
    query = f"""
    DELETE FROM `{EXPERIMENT_TABLE}`
    WHERE experiment_id = '{experiment_id}'
      AND game_date BETWEEN '{start_date}' AND '{end_date}'
    """
    result = client.query(query).result()
    print(f"  Cleared existing {experiment_id} rows for {start_date} to {end_date}")


def backfill_tracking_v1(client, start_date, end_date, dry_run=False):
    """Backfill tracking stats — static features replicated across game dates."""
    # Get the most recent tracking stats scrape
    scrape_query = f"""
    SELECT player_lookup, touches, drives, catch_shoot_fg_pct, pull_up_fg_pct,
           paint_touches, usage_pct
    FROM `{PROJECT_ID}.nba_raw.nba_tracking_stats`
    WHERE game_date = (
        SELECT MAX(game_date) FROM `{PROJECT_ID}.nba_raw.nba_tracking_stats`
        WHERE game_date <= '{end_date}'
    )
      AND player_lookup IS NOT NULL
      AND touches IS NOT NULL
    """
    tracking_df = client.query(scrape_query).to_dataframe()
    if tracking_df.empty:
        print("  WARNING: No tracking stats data found")
        return 0

    print(f"  Tracking stats: {len(tracking_df)} players from latest scrape")

    # Normalize tracking player_lookups to feature store format (no hyphens)
    tracking_df['player_lookup_fs'] = tracking_df['player_lookup'].apply(normalize_lookup)

    # Get all game dates where these players appear in the feature store
    players_str = ", ".join(f"'{p}'" for p in tracking_df['player_lookup_fs'].unique())
    games_query = f"""
    SELECT DISTINCT player_lookup, game_date
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND player_lookup IN ({players_str})
    """
    games_df = client.query(games_query).to_dataframe()
    if games_df.empty:
        print("  WARNING: No matching game dates in feature store")
        return 0

    print(f"  Game dates: {len(games_df)} player-game rows to populate")

    # Build lookup from tracking data (keyed by feature store format)
    tracking_lookup = {}
    for _, row in tracking_df.iterrows():
        tracking_lookup[row['player_lookup_fs']] = {
            'tracking_touches': row['touches'],
            'tracking_drives': row['drives'],
            'tracking_catch_shoot_pct': row['catch_shoot_fg_pct'],
            'tracking_pull_up_pct': row['pull_up_fg_pct'],
            'tracking_paint_touches': row['paint_touches'],
            'tracking_usage_pct': row['usage_pct'],
        }

    # Generate rows
    rows = []
    for _, game_row in games_df.iterrows():
        player = game_row['player_lookup']
        game_date = game_row['game_date']
        stats = tracking_lookup.get(player)
        if stats is None:
            continue
        for feature_name, feature_value in stats.items():
            if feature_value is not None:
                rows.append({
                    'player_lookup': player,
                    'game_date': str(game_date),
                    'experiment_id': 'tracking_v1',
                    'feature_name': feature_name,
                    'feature_value': float(feature_value),
                })

    if dry_run:
        print(f"  DRY RUN: Would insert {len(rows)} rows")
        if rows:
            sample = rows[:3]
            for r in sample:
                print(f"    {r['player_lookup']} | {r['game_date']} | {r['feature_name']} = {r['feature_value']:.3f}")
        return len(rows)

    return _write_rows(client, rows)


def backfill_pace_v1(client, start_date, end_date, dry_run=False):
    """Backfill pace features — static, replicated across game dates."""
    # Get latest pace data
    # Prefer rows with efficiency data (latest scrape has it, older scrapes don't)
    pace_query = f"""
    SELECT team,
           ANY_VALUE(pace) as pace,
           MAX(offensive_efficiency) as offensive_efficiency,
           MAX(defensive_efficiency) as defensive_efficiency
    FROM `{PROJECT_ID}.nba_raw.teamrankings_team_stats`
    WHERE game_date = (
        SELECT MAX(game_date) FROM `{PROJECT_ID}.nba_raw.teamrankings_team_stats`
        WHERE game_date <= '{end_date}'
    )
      AND team IS NOT NULL
    GROUP BY team
    """
    pace_df = client.query(pace_query).to_dataframe()
    if pace_df.empty:
        print("  WARNING: No TeamRankings pace data found")
        return 0

    print(f"  Pace data: {len(pace_df)} teams from latest scrape")

    # Build team pace lookup
    pace_lookup = {}
    for _, row in pace_df.iterrows():
        pace_lookup[row['team']] = {
            'pace': row['pace'],
            'off_eff': row['offensive_efficiency'],
            'def_eff': row['defensive_efficiency'],
        }

    # Get player-game-team mapping from schedule + feature store
    games_query = f"""
    SELECT DISTINCT
        mf.player_lookup,
        mf.game_date,
        s.home_team_tricode,
        s.away_team_tricode,
        pgs.team_abbr
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
        ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    JOIN `{PROJECT_ID}.nba_reference.nba_schedule` s
        ON mf.game_date = s.game_date
        AND (pgs.team_abbr = s.home_team_tricode OR pgs.team_abbr = s.away_team_tricode)
    WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
    """
    games_df = client.query(games_query).to_dataframe()
    if games_df.empty:
        print("  WARNING: No matching game dates")
        return 0

    print(f"  Player-games: {len(games_df)} rows to populate")

    rows = []
    for _, game_row in games_df.iterrows():
        player = game_row['player_lookup']
        game_date = str(game_row['game_date'])
        team = game_row['team_abbr']
        home = game_row['home_team_tricode']
        away = game_row['away_team_tricode']
        opp_team = away if team == home else home

        team_pace = pace_lookup.get(team, {}).get('pace')
        opp_pace = pace_lookup.get(opp_team, {}).get('pace')
        opp_off = pace_lookup.get(opp_team, {}).get('off_eff')
        opp_def = pace_lookup.get(opp_team, {}).get('def_eff')

        if team_pace is not None:
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'pace_v1', 'feature_name': 'team_pace_tr',
                        'feature_value': float(team_pace)})
        if opp_pace is not None:
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'pace_v1', 'feature_name': 'opp_pace_tr',
                        'feature_value': float(opp_pace)})
        if team_pace is not None and opp_pace is not None and opp_pace > 0:
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'pace_v1', 'feature_name': 'pace_ratio_tr',
                        'feature_value': float(team_pace / opp_pace)})
        if opp_off is not None:
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'pace_v1', 'feature_name': 'opp_off_eff_tr',
                        'feature_value': float(opp_off)})
        if opp_def is not None:
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'pace_v1', 'feature_name': 'opp_def_eff_tr',
                        'feature_value': float(opp_def)})

    if dry_run:
        print(f"  DRY RUN: Would insert {len(rows)} rows")
        return len(rows)

    return _write_rows(client, rows)


def backfill_dvp_v1(client, start_date, end_date, dry_run=False):
    """Backfill DVP features — daily-varying, only dates with data."""
    # Get DVP data for the date range
    dvp_query = f"""
    SELECT game_date, team, position, points_allowed, rank
    FROM `{PROJECT_ID}.nba_raw.hashtagbasketball_dvp`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND team IS NOT NULL
      AND position = 'PG'  -- points scoring position for DVP
    """
    dvp_df = client.query(dvp_query).to_dataframe()
    if dvp_df.empty:
        print("  WARNING: No DVP data found in date range")
        return 0

    print(f"  DVP data: {len(dvp_df)} team-date rows")

    # Normalize rank to 0-1 (rank 1 = hardest = 0.0, rank 30 = easiest = 1.0)
    max_rank = 30

    # Get player-game-opponent mapping
    dvp_dates = dvp_df['game_date'].unique()
    dates_str = ", ".join(f"'{d}'" for d in dvp_dates)
    games_query = f"""
    SELECT DISTINCT
        mf.player_lookup,
        mf.game_date,
        pgs.team_abbr,
        s.home_team_tricode,
        s.away_team_tricode
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
        ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    JOIN `{PROJECT_ID}.nba_reference.nba_schedule` s
        ON mf.game_date = s.game_date
        AND (pgs.team_abbr = s.home_team_tricode OR pgs.team_abbr = s.away_team_tricode)
    WHERE mf.game_date IN ({dates_str})
    """
    games_df = client.query(games_query).to_dataframe()
    if games_df.empty:
        print("  WARNING: No matching games")
        return 0

    # Build DVP lookup: (game_date, team) -> (rank, points_allowed)
    dvp_lookup = {}
    for _, row in dvp_df.iterrows():
        dvp_lookup[(str(row['game_date']), row['team'])] = {
            'rank': row['rank'],
            'points_allowed': row['points_allowed'],
        }

    rows = []
    for _, game_row in games_df.iterrows():
        player = game_row['player_lookup']
        game_date = str(game_row['game_date'])
        team = game_row['team_abbr']
        home = game_row['home_team_tricode']
        away = game_row['away_team_tricode']
        opp_team = away if team == home else home

        dvp = dvp_lookup.get((game_date, opp_team))
        if dvp is None:
            continue

        # Normalized rank: 1→0.0 (hardest), 30→1.0 (easiest)
        rank_norm = (dvp['rank'] - 1) / (max_rank - 1) if dvp['rank'] else None
        if rank_norm is not None:
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'dvp_v1', 'feature_name': 'dvp_points_rank_norm',
                        'feature_value': float(rank_norm)})
        if dvp['points_allowed'] is not None:
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'dvp_v1', 'feature_name': 'dvp_points_allowed',
                        'feature_value': float(dvp['points_allowed'])})

    if dry_run:
        print(f"  DRY RUN: Would insert {len(rows)} rows")
        return len(rows)

    return _write_rows(client, rows)


def backfill_projections_v1(client, start_date, end_date, dry_run=False):
    """Backfill projection consensus — daily-varying, only dates with data."""
    # Get NumberFire projections
    nf_query = f"""
    SELECT game_date, player_lookup, projected_points
    FROM `{PROJECT_ID}.nba_raw.numberfire_projections`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND player_lookup IS NOT NULL
      AND projected_points IS NOT NULL
    """
    nf_df = client.query(nf_query).to_dataframe()

    # Get Dimers projections
    dimers_query = f"""
    SELECT game_date, player_lookup, projected_points
    FROM `{PROJECT_ID}.nba_raw.dimers_projections`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND player_lookup IS NOT NULL
      AND projected_points IS NOT NULL
    """
    dimers_df = client.query(dimers_query).to_dataframe()

    nf_count = len(nf_df)
    dimers_count = len(dimers_df)
    print(f"  NumberFire: {nf_count} rows, Dimers: {dimers_count} rows")

    if nf_count == 0 and dimers_count == 0:
        print("  WARNING: No projection data found")
        return 0

    # Build per-player-date consensus
    # Key: (player_lookup_fs, game_date) -> list of projected_points
    # Normalize to feature store format (no hyphens)
    projections = {}
    for _, row in nf_df.iterrows():
        key = (normalize_lookup(row['player_lookup']), str(row['game_date']))
        projections.setdefault(key, []).append(float(row['projected_points']))
    for _, row in dimers_df.iterrows():
        key = (normalize_lookup(row['player_lookup']), str(row['game_date']))
        projections.setdefault(key, []).append(float(row['projected_points']))

    # Get prop lines for delta computation
    players_dates = list(projections.keys())
    if not players_dates:
        return 0

    unique_dates = list(set(d for _, d in players_dates))
    dates_str = ", ".join(f"'{d}'" for d in unique_dates)
    lines_query = f"""
    SELECT player_lookup, game_date, feature_25_value as prop_line
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
    WHERE game_date IN ({dates_str})
      AND feature_25_value IS NOT NULL
    """
    lines_df = client.query(lines_query).to_dataframe()
    lines_lookup = {}
    for _, row in lines_df.iterrows():
        lines_lookup[(row['player_lookup'], str(row['game_date']))] = float(row['prop_line'])

    rows = []
    for (player, game_date), pts_list in projections.items():
        consensus_pts = sum(pts_list) / len(pts_list)
        n_sources = len(pts_list)

        rows.append({'player_lookup': player, 'game_date': game_date,
                    'experiment_id': 'projections_v1', 'feature_name': 'projection_consensus_pts',
                    'feature_value': consensus_pts})
        rows.append({'player_lookup': player, 'game_date': game_date,
                    'experiment_id': 'projections_v1', 'feature_name': 'projection_n_sources',
                    'feature_value': float(n_sources)})

        # Delta = consensus - prop_line
        prop_line = lines_lookup.get((player, game_date))
        if prop_line is not None and prop_line > 0:
            delta = consensus_pts - prop_line
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'projections_v1', 'feature_name': 'projection_consensus_delta',
                        'feature_value': delta})

    if dry_run:
        print(f"  DRY RUN: Would insert {len(rows)} rows")
        return len(rows)

    return _write_rows(client, rows)


def backfill_sharp_money_v1(client, start_date, end_date, dry_run=False):
    """Backfill sharp money features — daily-varying, team-level joined to players."""
    # Get VSiN data
    vsin_query = f"""
    SELECT game_date, home_team, away_team,
           over_ticket_pct, over_money_pct, under_ticket_pct, under_money_pct
    FROM `{PROJECT_ID}.nba_raw.vsin_betting_splits`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND over_ticket_pct IS NOT NULL
    """
    vsin_df = client.query(vsin_query).to_dataframe()
    if vsin_df.empty:
        print("  WARNING: No VSiN data found in date range")
        return 0

    print(f"  VSiN data: {len(vsin_df)} game-date rows")

    # Build lookup: (game_date, home_team, away_team) -> splits
    vsin_lookup = {}
    for _, row in vsin_df.iterrows():
        key = (str(row['game_date']), row['home_team'], row['away_team'])
        vsin_lookup[key] = {
            'over_ticket_pct': row['over_ticket_pct'],
            'over_money_pct': row['over_money_pct'],
        }

    # Get player-game-team mapping
    vsin_dates = vsin_df['game_date'].unique()
    dates_str = ", ".join(f"'{d}'" for d in vsin_dates)
    games_query = f"""
    SELECT DISTINCT
        mf.player_lookup,
        mf.game_date,
        pgs.team_abbr,
        s.home_team_tricode,
        s.away_team_tricode
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
        ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    JOIN `{PROJECT_ID}.nba_reference.nba_schedule` s
        ON mf.game_date = s.game_date
        AND (pgs.team_abbr = s.home_team_tricode OR pgs.team_abbr = s.away_team_tricode)
    WHERE mf.game_date IN ({dates_str})
    """
    games_df = client.query(games_query).to_dataframe()
    if games_df.empty:
        print("  WARNING: No matching games")
        return 0

    rows = []
    for _, game_row in games_df.iterrows():
        player = game_row['player_lookup']
        game_date = str(game_row['game_date'])
        home = game_row['home_team_tricode']
        away = game_row['away_team_tricode']

        splits = vsin_lookup.get((game_date, home, away))
        if splits is None:
            continue

        over_ticket = splits['over_ticket_pct']
        over_money = splits['over_money_pct']

        if over_ticket is not None:
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'sharp_money_v1', 'feature_name': 'over_ticket_pct',
                        'feature_value': float(over_ticket)})
        if over_money is not None:
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'sharp_money_v1', 'feature_name': 'over_money_pct',
                        'feature_value': float(over_money)})
        # Sharp money divergence = money% - ticket% (positive = sharp on over)
        if over_ticket is not None and over_money is not None:
            divergence = over_money - over_ticket
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'sharp_money_v1', 'feature_name': 'sharp_money_divergence',
                        'feature_value': float(divergence)})

    if dry_run:
        print(f"  DRY RUN: Would insert {len(rows)} rows")
        return len(rows)

    return _write_rows(client, rows)


def backfill_derived_v1(client, start_date, end_date, dry_run=False):
    """Backfill player volatility & consistency features from player_game_summary.

    Uses rolling window stats computed via SQL window functions.
    Full season data available — no external scraper dependency.
    """
    import math as _math

    # CRITICAL: Use 1 PRECEDING to exclude target game (avoid data leakage)
    query = f"""
    WITH player_games AS (
        SELECT
            pgs.player_lookup,
            pgs.game_date,
            pgs.points,
            -- Rolling stats EXCLUDING current game (1 PRECEDING = prior games only)
            AVG(pgs.points) OVER (
                PARTITION BY pgs.player_lookup ORDER BY pgs.game_date
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) as avg_last_5,
            AVG(pgs.points) OVER (
                PARTITION BY pgs.player_lookup ORDER BY pgs.game_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ) as avg_last_10,
            AVG(pgs.points) OVER (
                PARTITION BY pgs.player_lookup ORDER BY pgs.game_date
                ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
            ) as avg_last_3,
            -- Std dev EXCLUDING current game
            STDDEV_SAMP(pgs.points) OVER (
                PARTITION BY pgs.player_lookup ORDER BY pgs.game_date
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) as std_last_5,
            STDDEV_SAMP(pgs.points) OVER (
                PARTITION BY pgs.player_lookup ORDER BY pgs.game_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ) as std_last_10,
            -- Count for minimum games filter (excluding current)
            COUNT(*) OVER (
                PARTITION BY pgs.player_lookup ORDER BY pgs.game_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ) as games_last_10
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
        WHERE pgs.game_date BETWEEN DATE_SUB(DATE('{start_date}'), INTERVAL 30 DAY) AND '{end_date}'
          AND pgs.points IS NOT NULL
          AND pgs.player_lookup IS NOT NULL
    )
    SELECT pg.player_lookup, pg.game_date, pg.std_last_5, pg.std_last_10,
           pg.avg_last_3, pg.avg_last_10, pg.games_last_10
    FROM player_games pg
    JOIN `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
        ON pg.player_lookup = mf.player_lookup AND pg.game_date = mf.game_date
    WHERE pg.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND pg.games_last_10 >= 5
    """
    df = client.query(query).to_dataframe()
    if df.empty:
        print("  WARNING: No derived data found")
        return 0

    print(f"  Derived data: {len(df)} player-game rows")

    # Over rate weighted: for each target game, compute over-hit rate from
    # the 10 prior games (excluding target), with recent 5 weighted 2x.
    # Uses a self-join to get prior games per target date.
    over_query = f"""
    WITH graded AS (
        SELECT player_lookup, game_date, actual_points, line_value,
               CASE WHEN actual_points > line_value THEN 1 ELSE 0 END as went_over
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date BETWEEN DATE_SUB(DATE('{start_date}'), INTERVAL 60 DAY) AND '{end_date}'
          AND has_prop_line = TRUE
          AND actual_points IS NOT NULL
          AND line_value IS NOT NULL
    ),
    with_prior AS (
        SELECT
            target.player_lookup,
            target.game_date as target_date,
            prior.went_over,
            ROW_NUMBER() OVER (
                PARTITION BY target.player_lookup, target.game_date
                ORDER BY prior.game_date DESC
            ) as recency_rank
        FROM graded target
        JOIN graded prior
            ON target.player_lookup = prior.player_lookup
            AND prior.game_date < target.game_date
        WHERE target.game_date BETWEEN '{start_date}' AND '{end_date}'
    )
    SELECT player_lookup, target_date as game_date,
           SUM(went_over * CASE WHEN recency_rank <= 5 THEN 2.0 ELSE 1.0 END)
           / SUM(CASE WHEN recency_rank <= 5 THEN 2.0 ELSE 1.0 END) as over_rate_weighted
    FROM with_prior
    WHERE recency_rank <= 10
    GROUP BY player_lookup, target_date
    HAVING COUNT(*) >= 5
    """
    over_df = client.query(over_query).to_dataframe()
    over_lookup = {}
    if not over_df.empty:
        for _, row in over_df.iterrows():
            over_lookup[(row['player_lookup'], str(row['game_date']))] = float(row['over_rate_weighted'])
        print(f"  Over rate data: {len(over_df)} player-game rows")

    rows = []
    for _, row in df.iterrows():
        player = row['player_lookup']
        game_date = str(row['game_date'])

        if row['std_last_5'] is not None and not _math.isnan(row['std_last_5']):
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'derived_v1', 'feature_name': 'pts_std_last_5',
                        'feature_value': float(row['std_last_5'])})

        if row['std_last_10'] is not None and not _math.isnan(row['std_last_10']):
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'derived_v1', 'feature_name': 'pts_std_last_10',
                        'feature_value': float(row['std_last_10'])})

        # form_ratio = avg_last_3 / avg_last_10 (momentum indicator)
        avg3 = row['avg_last_3']
        avg10 = row['avg_last_10']
        if avg3 is not None and avg10 is not None and avg10 > 0:
            if not _math.isnan(avg3) and not _math.isnan(avg10):
                rows.append({'player_lookup': player, 'game_date': game_date,
                            'experiment_id': 'derived_v1', 'feature_name': 'form_ratio',
                            'feature_value': float(avg3 / avg10)})

        # over_rate_weighted
        over_rate = over_lookup.get((player, game_date))
        if over_rate is not None:
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'derived_v1', 'feature_name': 'over_rate_weighted',
                        'feature_value': over_rate})

    if dry_run:
        print(f"  DRY RUN: Would insert {len(rows)} rows")
        return len(rows)

    return _write_rows(client, rows)


def backfill_interactions_v1(client, start_date, end_date, dry_run=False):
    """Backfill cross-feature interaction terms from ml_feature_store_v2.

    Computes products of existing feature pairs that may capture nonlinear effects.
    Full season data available.
    """
    import math as _math

    # Feature indices: f5=fatigue_score, f44=minutes_load_last_7d,
    # f6=pace_score, f32=points_per_minute, f9=rest_advantage, f39=days_rest,
    # f42=spread_magnitude, f15=home_away
    query = f"""
    SELECT player_lookup, game_date,
           feature_5_value as fatigue,
           feature_44_value as minutes_load,
           feature_6_value as pace,
           feature_32_value as ppm,
           feature_9_value as rest_adv,
           feature_39_value as days_rest,
           feature_42_value as spread_mag,
           feature_15_value as home_away
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    """
    df = client.query(query).to_dataframe()
    if df.empty:
        print("  WARNING: No feature store data found")
        return 0

    print(f"  Feature store data: {len(df)} rows")

    rows = []
    for _, row in df.iterrows():
        player = row['player_lookup']
        game_date = str(row['game_date'])

        def safe_mult(a, b, name):
            if a is not None and b is not None:
                try:
                    fa, fb = float(a), float(b)
                    if not (_math.isnan(fa) or _math.isnan(fb)):
                        rows.append({'player_lookup': player, 'game_date': game_date,
                                    'experiment_id': 'interactions_v1', 'feature_name': name,
                                    'feature_value': fa * fb})
                except (ValueError, TypeError):
                    pass

        safe_mult(row['fatigue'], row['minutes_load'], 'fatigue_x_minutes')
        safe_mult(row['pace'], row['ppm'], 'pace_x_usage')
        safe_mult(row['rest_adv'], row['days_rest'], 'rest_x_b2b')
        safe_mult(row['spread_mag'], row['home_away'], 'spread_x_home')

    if dry_run:
        print(f"  DRY RUN: Would insert {len(rows)} rows")
        return len(rows)

    return _write_rows(client, rows)


def backfill_line_history_v1(client, start_date, end_date, dry_run=False):
    """Backfill line-based derived features from ml_feature_store_v2.

    Features:
    - line_vs_avg: vegas line - recent avg points (feature_25 - feature_0)
    - opening_vs_current: opening line - current line (feature_26 - feature_25) = early CLV proxy
    - line_range: normalized position of line in player's recent range
    """
    import math as _math

    # f0=avg_points_recent, f25=vegas_points_line, f26=opening_line, f4=points_std
    query = f"""
    SELECT player_lookup, game_date,
           feature_0_value as avg_pts,
           feature_25_value as vegas_line,
           feature_26_value as opening_line,
           feature_4_value as pts_std
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    """
    df = client.query(query).to_dataframe()
    if df.empty:
        print("  WARNING: No feature store data found")
        return 0

    print(f"  Feature store data: {len(df)} rows")

    rows = []
    for _, row in df.iterrows():
        player = row['player_lookup']
        game_date = str(row['game_date'])

        avg_pts = row['avg_pts']
        vegas_line = row['vegas_line']
        opening_line = row['opening_line']
        pts_std = row['pts_std']

        def is_valid(v):
            return v is not None and not (isinstance(v, float) and _math.isnan(v))

        # line_vs_avg: vegas line - recent average (how far line is from player's norm)
        if is_valid(vegas_line) and is_valid(avg_pts):
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'line_history_v1', 'feature_name': 'line_vs_avg',
                        'feature_value': float(vegas_line) - float(avg_pts)})

        # opening_vs_current: opening - current (positive = line moved down, negative = up)
        if is_valid(opening_line) and is_valid(vegas_line):
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'line_history_v1', 'feature_name': 'opening_vs_current',
                        'feature_value': float(opening_line) - float(vegas_line)})

        # line_range: (vegas_line - avg_pts) / pts_std — how many std devs from avg
        if is_valid(vegas_line) and is_valid(avg_pts) and is_valid(pts_std) and float(pts_std) > 0:
            rows.append({'player_lookup': player, 'game_date': game_date,
                        'experiment_id': 'line_history_v1', 'feature_name': 'line_range',
                        'feature_value': (float(vegas_line) - float(avg_pts)) / float(pts_std)})

    if dry_run:
        print(f"  DRY RUN: Would insert {len(rows)} rows")
        return len(rows)

    return _write_rows(client, rows)


def _write_rows(client, rows):
    """Write rows to experiment table using streaming insert."""
    if not rows:
        return 0

    # Filter out rows with NaN feature values (pandas NULL → NaN, not None)
    import math
    rows = [r for r in rows if not (isinstance(r['feature_value'], float) and math.isnan(r['feature_value']))]
    if not rows:
        return 0

    # Convert game_date strings to date objects for BQ
    for row in rows:
        if isinstance(row['game_date'], str):
            from datetime import datetime as dt
            row['game_date'] = dt.strptime(row['game_date'], '%Y-%m-%d').date()

    table_ref = client.dataset('nba_predictions').table('ml_feature_store_experiment')

    # Batch insert in chunks of 500
    batch_size = 500
    total_inserted = 0
    errors_all = []
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        errors = client.insert_rows_json(
            table_ref,
            [{k: str(v) if isinstance(v, date) else v for k, v in row.items()} for row in batch],
        )
        if errors:
            errors_all.extend(errors)
        else:
            total_inserted += len(batch)

    if errors_all:
        print(f"  WARNING: {len(errors_all)} insert errors: {errors_all[:3]}")

    print(f"  Inserted {total_inserted} rows")
    return total_inserted


BACKFILL_FUNCTIONS = {
    'tracking_v1': backfill_tracking_v1,
    'pace_v1': backfill_pace_v1,
    'dvp_v1': backfill_dvp_v1,
    'projections_v1': backfill_projections_v1,
    'sharp_money_v1': backfill_sharp_money_v1,
    'derived_v1': backfill_derived_v1,
    'interactions_v1': backfill_interactions_v1,
    'line_history_v1': backfill_line_history_v1,
}


def main():
    parser = argparse.ArgumentParser(description='Backfill experiment features')
    parser.add_argument('--experiment', type=str, help='Experiment ID (or "all")')
    parser.add_argument('--start', type=str, default=None, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default=None, help='End date (YYYY-MM-DD)')
    parser.add_argument('--list', action='store_true', help='List available experiments')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be written')
    parser.add_argument('--no-clear', action='store_true', help='Skip clearing existing rows (use when streaming buffer blocks DELETE)')
    args = parser.parse_args()

    if args.list:
        print("\nAvailable experiments:")
        print("-" * 80)
        for exp_id, info in EXPERIMENTS.items():
            print(f"  {exp_id:20s} [{info['type']:6s}] {info['description']}")
            print(f"  {'':20s} Features: {', '.join(info['features'])}")
            print(f"  {'':20s} Source: {info['source_table']}")
            print()
        return

    if not args.experiment:
        parser.error("--experiment is required (or use --list)")

    # Default date range: last 60 days
    end_date = args.end or str(date.today())
    start_date = args.start or str(date.today() - timedelta(days=60))

    experiments_to_run = list(EXPERIMENTS.keys()) if args.experiment == 'all' else [args.experiment]

    for exp_id in experiments_to_run:
        if exp_id not in BACKFILL_FUNCTIONS:
            print(f"ERROR: Unknown experiment '{exp_id}'. Use --list to see available.")
            continue

        print(f"\n{'='*60}")
        print(f"Backfilling: {exp_id}")
        print(f"  Type: {EXPERIMENTS[exp_id]['type']}")
        print(f"  Date range: {start_date} to {end_date}")
        print(f"  Features: {', '.join(EXPERIMENTS[exp_id]['features'])}")
        if args.dry_run:
            print(f"  Mode: DRY RUN")
        print(f"{'='*60}")

        client = get_client()

        if not args.dry_run and not args.no_clear:
            clear_experiment(client, exp_id, start_date, end_date)

        backfill_fn = BACKFILL_FUNCTIONS[exp_id]
        n_rows = backfill_fn(client, start_date, end_date, dry_run=args.dry_run)
        print(f"  Total: {n_rows} rows {'(would be written)' if args.dry_run else 'written'}")

    print("\nDone.")


if __name__ == '__main__':
    main()
