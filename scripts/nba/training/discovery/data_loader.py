"""Shared data loader for signal discovery tools.

Loads and joins the 6 enrichment CSVs from results/bb_simulator/
into a single enriched DataFrame with 200+ columns.

Reuses the same join logic as bb_enriched_simulator.py but
extracted for reuse across discovery tools.

Session 466: Initial implementation.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

DATA_DIR = Path('results/bb_simulator')

# Season date ranges (Oct start → Apr end)
SEASON_RANGES = {
    '2021-22': ('2021-10-19', '2022-06-30'),
    '2022-23': ('2022-10-18', '2023-06-30'),
    '2023-24': ('2023-10-24', '2024-06-30'),
    '2024-25': ('2024-10-22', '2025-06-30'),
    '2025-26': ('2025-10-28', '2026-06-30'),
}


def assign_season(game_date: str) -> str:
    """Map game_date to season label."""
    for season, (start, end) in SEASON_RANGES.items():
        if start <= game_date <= end:
            return season
    return 'unknown'


class DiscoveryDataset:
    """Loads and joins all enrichment CSVs into a single DataFrame."""

    def __init__(self, data_dir: Optional[Path] = None, min_edge: float = 0.0):
        self.data_dir = data_dir or DATA_DIR
        self.min_edge = min_edge
        self._df = None

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            self._df = self._load_and_enrich()
        return self._df

    def _load_and_enrich(self) -> pd.DataFrame:
        """Load all CSVs and join into enriched DataFrame."""
        logger.info("Loading discovery dataset...")

        # 1. Predictions — combine walk-forward (2023-25) + current season (2025-26)
        pred_frames = []

        # Walk-forward predictions (2023-24, 2024-25) — clean, no leakage
        wf_paths = [
            Path('results/nba_walkforward_clean/predictions_w56_r7.csv'),
            Path('results/nba_walkforward/predictions_w56_r7.csv'),
        ]
        for wf_path in wf_paths:
            if wf_path.exists():
                wf = pd.read_csv(wf_path)
                logger.info(f"  Walk-forward predictions: {len(wf)} rows from {wf_path}")
                pred_frames.append(wf)
                break

        # Current season multi-model predictions (2025-26)
        current_path = self.data_dir / 'predictions_2025_26_all_models.csv'
        if current_path.exists():
            current = pd.read_csv(current_path)
            logger.info(f"  Current season predictions: {len(current)} rows")
            pred_frames.append(current)

        if not pred_frames:
            raise FileNotFoundError("No prediction files found")

        preds = pd.concat(pred_frames, ignore_index=True)
        logger.info(f"  Combined predictions: {len(preds)} rows")

        # Deduplicate: keep highest-edge prediction per player-game
        preds['abs_edge'] = preds['edge'].abs()
        preds = preds.sort_values('abs_edge', ascending=False)
        preds = preds.drop_duplicates(subset=['game_date', 'player_lookup'], keep='first')
        preds = preds.drop(columns=['abs_edge'])
        logger.info(f"  After dedup: {len(preds)} rows")

        # 2. Feature store enrichment
        fs = pd.read_csv(self.data_dir / 'feature_store_enrichment.csv')
        logger.info(f"  Feature store: {len(fs)} rows, {len(fs.columns)} cols")

        # 3. Feature store extra
        fs_extra = pd.read_csv(self.data_dir / 'feature_store_extra.csv')
        logger.info(f"  Feature store extra: {len(fs_extra)} rows, {len(fs_extra.columns)} cols")

        # 4. Player game summary
        pgs = pd.read_csv(self.data_dir / 'player_game_summary_enrichment.csv')
        logger.info(f"  Player game summary: {len(pgs)} rows, {len(pgs.columns)} cols")

        # 5. BettingPros multibook
        bp = pd.read_csv(self.data_dir / 'bettingpros_multibook.csv')
        logger.info(f"  BettingPros: {len(bp)} rows")

        # 6. Schedule
        sched = pd.read_csv(self.data_dir / 'schedule_enrichment.csv')
        logger.info(f"  Schedule: {len(sched)} rows")

        # --- Joins ---
        join_keys = ['game_date', 'player_lookup']

        # Merge feature store (deduplicate extra columns)
        fs_extra_cols = [c for c in fs_extra.columns
                         if c not in fs.columns or c in join_keys]
        df = preds.merge(fs[fs.columns], on=join_keys, how='left')
        df = df.merge(fs_extra[fs_extra_cols], on=join_keys, how='left',
                       suffixes=('', '_extra'))

        # Merge PGS (avoid column collisions)
        pgs_cols = [c for c in pgs.columns
                    if c not in df.columns or c in join_keys]
        df = df.merge(pgs[pgs_cols], on=join_keys, how='left',
                       suffixes=('', '_pgs'))

        # Merge BettingPros
        bp_cols = [c for c in bp.columns
                   if c not in df.columns or c in join_keys]
        df = df.merge(bp[bp_cols], on=join_keys, how='left',
                       suffixes=('', '_bp'))

        logger.info(f"  After joins: {len(df)} rows, {len(df.columns)} cols")

        # --- Derived features ---
        # Season assignment
        df['season'] = df['game_date'].apply(assign_season)

        # Direction as string
        if 'direction' not in df.columns and 'edge' in df.columns:
            df['direction'] = 'UNKNOWN'
        # Ensure direction is uppercase
        df['direction'] = df['direction'].str.upper()

        # Correct column (ensure numeric)
        if 'correct' in df.columns:
            df['correct'] = pd.to_numeric(df['correct'], errors='coerce').fillna(0).astype(int)

        # Edge (absolute value)
        if 'edge' in df.columns:
            df['abs_edge'] = df['edge'].abs()

        # Shooting deviation features (pre-game safe: uses last_3 vs season)
        if 'fg_pct_last_3' in df.columns and 'fg_pct_season' in df.columns:
            df['fg_pct_diff'] = df['fg_pct_last_3'] - df['fg_pct_season']
        if 'three_pct_last_3' in df.columns and 'three_pct_season' in df.columns:
            df['three_pct_diff'] = df['three_pct_last_3'] - df['three_pct_season']

        # Neg PM streak
        if all(c in df.columns for c in ['prev_pm_1', 'prev_pm_2', 'prev_pm_3']):
            df['neg_pm_streak'] = (
                (df['prev_pm_1'] < 0).astype(int) +
                (df['prev_pm_2'] < 0).astype(int) +
                (df['prev_pm_3'] < 0).astype(int)
            )

        # Is home flag
        if 'home_away' in df.columns:
            df['is_home'] = (df['home_away'] >= 0.5).astype(int)

        # Edge buckets
        if 'abs_edge' in df.columns:
            df['edge_bucket'] = pd.cut(
                df['abs_edge'],
                bins=[0, 3, 5, 7, 10, 100],
                labels=['0-3', '3-5', '5-7', '7-10', '10+'],
                right=False,
            )

        # Day of week
        df['day_of_week'] = pd.to_datetime(df['game_date']).dt.dayofweek

        # Back-to-back flag (from feature store, already available)
        if 'back_to_back' in df.columns:
            df['is_b2b'] = (df['back_to_back'] >= 0.5).astype(int)

        # Apply minimum edge filter
        if self.min_edge > 0 and 'abs_edge' in df.columns:
            before = len(df)
            df = df[df['abs_edge'] >= self.min_edge]
            logger.info(f"  Edge >= {self.min_edge} filter: {before} -> {len(df)}")

        # Filter to graded only
        if 'correct' in df.columns:
            before = len(df)
            df = df[df['correct'].notna()]
            logger.info(f"  Graded filter: {before} -> {len(df)}")

        # Drop unknown seasons
        df = df[df['season'] != 'unknown']

        logger.info(f"  Final dataset: {len(df)} rows, {len(df.columns)} cols, "
                     f"seasons: {sorted(df['season'].unique())}")

        return df

    def get_seasons(self, exclude_current: bool = True) -> list:
        """Get list of complete seasons for cross-validation."""
        seasons = sorted(self.df['season'].unique())
        if exclude_current and '2025-26' in seasons:
            seasons.remove('2025-26')
        return seasons

    def season_split(self, season: str) -> pd.DataFrame:
        """Get data for a specific season."""
        return self.df[self.df['season'] == season]

    def summary(self) -> dict:
        """Quick summary of the dataset."""
        df = self.df
        return {
            'total_rows': len(df),
            'columns': len(df.columns),
            'seasons': {s: len(g) for s, g in df.groupby('season')},
            'directions': {d: len(g) for d, g in df.groupby('direction')},
            'baseline_hr': round(df['correct'].mean(), 4),
            'edge_3plus_hr': round(
                df[df['abs_edge'] >= 3]['correct'].mean(), 4
            ) if 'abs_edge' in df.columns else None,
        }
