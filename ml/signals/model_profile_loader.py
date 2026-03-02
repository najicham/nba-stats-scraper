"""Model Profile Store — loads per-model profile data for filtering decisions.

Provides O(1) lookups for model+dimension+value blocking and HR retrieval.
Used by the aggregator to check if a specific model should be blocked for a
given direction, tier, home/away, edge band, or signal.

Fallback chain: model-level → affinity-group-level → default (52.4%).

Created: 2026-03-01 (Session 384)
"""

import logging
from datetime import date
from typing import Dict, Optional, Set, Tuple

from google.cloud import bigquery

logger = logging.getLogger(__name__)

DEFAULT_HR = 52.4  # Breakeven at -110 odds


class ModelProfileStore:
    """In-memory store for per-model profile data.

    Loaded once per export run. Provides O(1) blocking checks and HR lookups.
    """

    def __init__(self):
        # (model_id, dimension, dimension_value) -> {hr, n, is_blocked, block_reason}
        self._profiles: Dict[Tuple[str, str, str], dict] = {}
        # (affinity_group, dimension, dimension_value) -> {hr, n}
        self._group_profiles: Dict[Tuple[str, str, str], dict] = {}
        # Set of blocked (model_id, dimension, dimension_value) for fast lookup
        self._blocked: Set[Tuple[str, str, str]] = set()
        # model_id -> affinity_group mapping
        self._model_groups: Dict[str, str] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def total_profiles(self) -> int:
        return len(self._profiles)

    @property
    def blocked_count(self) -> int:
        return len(self._blocked)

    def is_blocked(self, model_id: str, dimension: str, value: str) -> bool:
        """Check if a model is blocked for a specific dimension slice.

        Args:
            model_id: System ID (e.g. 'catboost_v12_noveg_train1222_0214').
            dimension: Dimension name ('direction', 'tier', 'home_away', etc.).
            value: Dimension value ('OVER', 'starter', 'HOME', etc.).

        Returns:
            True if the model is blocked for this slice.
        """
        return (model_id, dimension, value) in self._blocked

    def get_block_reason(self, model_id: str, dimension: str, value: str) -> Optional[str]:
        """Get the block reason for a model+dimension+value combo."""
        key = (model_id, dimension, value)
        profile = self._profiles.get(key)
        if profile and profile.get('is_blocked'):
            return profile.get('block_reason')
        return None

    def get_hr(self, model_id: str, dimension: str, value: str) -> Optional[float]:
        """Get 14d HR for a specific model+dimension+value.

        Returns None if no data exists for this combo.
        """
        key = (model_id, dimension, value)
        profile = self._profiles.get(key)
        if profile:
            return profile.get('hr')
        return None

    def get_hr_with_fallback(
        self, model_id: str, dimension: str, value: str,
        affinity_group: Optional[str] = None,
    ) -> float:
        """Get HR with fallback chain: model → affinity group → default.

        Args:
            model_id: System ID.
            dimension: Dimension name.
            value: Dimension value.
            affinity_group: Optional override. If None, uses stored mapping.

        Returns:
            HR value (never None).
        """
        # Try model-level first
        hr = self.get_hr(model_id, dimension, value)
        if hr is not None:
            return hr

        # Fallback to affinity group
        group = affinity_group or self._model_groups.get(model_id)
        if group:
            group_key = (group, dimension, value)
            group_profile = self._group_profiles.get(group_key)
            if group_profile:
                return group_profile.get('hr', DEFAULT_HR)

        return DEFAULT_HR

    def get_all_blocks_for_model(self, model_id: str) -> list:
        """Get all blocked slices for a specific model.

        Returns list of {dimension, value, hr, n, reason} dicts.
        """
        blocks = []
        for key in self._blocked:
            if key[0] == model_id:
                profile = self._profiles.get(key, {})
                blocks.append({
                    'dimension': key[1],
                    'value': key[2],
                    'hr': profile.get('hr'),
                    'n': profile.get('n'),
                    'reason': profile.get('block_reason'),
                })
        return blocks

    def get_stats(self) -> dict:
        """Get summary statistics for logging."""
        models = set(k[0] for k in self._profiles)
        blocked_models = set(k[0] for k in self._blocked)
        return {
            'total_profiles': len(self._profiles),
            'total_models': len(models),
            'blocked_slices': len(self._blocked),
            'models_with_blocks': len(blocked_models),
            'loaded': self._loaded,
        }


def load_model_profiles(
    bq_client: bigquery.Client,
    target_date,
    project_id: str = 'nba-props-platform',
) -> ModelProfileStore:
    """Load model profiles from BQ for a target date.

    Queries the most recent profile data up to target_date. If no data exists
    for that exact date, looks back up to 3 days.

    Args:
        bq_client: BigQuery client.
        target_date: Date string (YYYY-MM-DD) or date object.
        project_id: GCP project ID.

    Returns:
        Populated ModelProfileStore (empty store on failure).
    """
    store = ModelProfileStore()

    try:
        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)

        query = f"""
        SELECT
            model_id, affinity_group, dimension, dimension_value,
            hr_14d, n_14d, is_blocked, block_reason
        FROM `{project_id}.nba_predictions.model_profile_daily`
        WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL 3 DAY) AND @target_date
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY model_id, dimension, dimension_value
            ORDER BY game_date DESC
        ) = 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            ]
        )

        rows = list(bq_client.query(query, job_config=job_config).result(timeout=60))

        if not rows:
            logger.warning(f"No model profiles found for {target_date} (looked back 3 days)")
            return store

        # Build per-model profiles
        from collections import defaultdict
        group_accum = defaultdict(lambda: {'wins': 0, 'losses': 0})

        for row in rows:
            key = (row.model_id, row.dimension, row.dimension_value)
            profile = {
                'hr': float(row.hr_14d) if row.hr_14d is not None else None,
                'n': row.n_14d or 0,
                'is_blocked': row.is_blocked or False,
                'block_reason': row.block_reason,
            }
            store._profiles[key] = profile

            if row.is_blocked:
                store._blocked.add(key)

            if row.affinity_group:
                store._model_groups[row.model_id] = row.affinity_group

        # Build affinity group aggregates for fallback
        # Re-aggregate from individual model rows
        for key, profile in store._profiles.items():
            model_id, dimension, dim_value = key
            group = store._model_groups.get(model_id)
            if group and profile['hr'] is not None and profile['n'] > 0:
                group_key = (group, dimension, dim_value)
                # Approximate: use hr * n to recover wins
                wins = round(profile['hr'] / 100.0 * profile['n'])
                losses = profile['n'] - wins
                group_accum[group_key]['wins'] += wins
                group_accum[group_key]['losses'] += losses

        for group_key, vals in group_accum.items():
            total = vals['wins'] + vals['losses']
            if total > 0:
                store._group_profiles[group_key] = {
                    'hr': round(100.0 * vals['wins'] / total, 1),
                    'n': total,
                }

        store._loaded = True
        stats = store.get_stats()
        logger.info(
            f"Loaded model profiles for {target_date}: "
            f"{stats['total_profiles']} profiles across {stats['total_models']} models, "
            f"{stats['blocked_slices']} blocked slices"
        )

        return store

    except Exception as e:
        logger.warning(f"Failed to load model profiles (non-fatal): {e}")
        return store
