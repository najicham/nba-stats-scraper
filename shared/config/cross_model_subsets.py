"""Cross-model observation subset definitions.

Defines 5 meta-subsets that observe cross-model agreement patterns.
These are observation-only subsets written to current_subset_picks
with system_id='cross_model'. The existing SubsetGradingProcessor
handles grading automatically (grades by subset_id, agnostic to system_id).

Session 277: Initial creation.
Session 296: Dynamic model discovery — replaces hardcoded system_ids
  with pattern-based classification so cross-model analysis works
  regardless of retrained model names.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model family definitions (pattern-based, not exact system_id)
# ---------------------------------------------------------------------------

# IMPORTANT: Order matters for classify_system_id() — more specific patterns
# must come BEFORE broader patterns within the same prefix family.
# e.g. v12_q43 ('catboost_v12_noveg_q43_') before v12_mae ('catboost_v12')
MODEL_FAMILIES = {
    # V9 family — exact match for champion, prefix for variants
    'v9_mae': {
        'pattern': 'catboost_v9',
        'exact': True,
        'feature_set': 'v9',
        'loss': 'mae',
    },
    'v9_q43': {
        'pattern': 'catboost_v9_q43_',
        'exact': False,
        'feature_set': 'v9',
        'loss': 'quantile',
    },
    'v9_q45': {
        'pattern': 'catboost_v9_q45_',
        'exact': False,
        'feature_set': 'v9',
        'loss': 'quantile',
    },
    'v9_low_vegas': {
        'pattern': 'catboost_v9_low_vegas_',
        'exact': False,
        'feature_set': 'v9',
        'loss': 'mae',
    },
    # V12 family — quantile patterns FIRST (more specific), then broad v12_mae.
    # Session 324: Added v12_vegas_q43/q45 for V12+vegas quantile models.
    # Order: noveg quantile → vegas quantile → broad v12_mae catch-all.
    'v12_q43': {
        'pattern': 'catboost_v12_noveg_q43_',
        'exact': False,
        'feature_set': 'v12_noveg',
        'loss': 'quantile',
    },
    'v12_q45': {
        'pattern': 'catboost_v12_noveg_q45_',
        'exact': False,
        'feature_set': 'v12_noveg',
        'loss': 'quantile',
    },
    # Session 343: Q55 quantile — counteracts UNDER bias by predicting 55th percentile
    'v12_noveg_q55': {
        'pattern': 'catboost_v12_noveg_q55_',
        'exact': False,
        'feature_set': 'v12_noveg',
        'loss': 'quantile',
    },
    'v12_vegas_q43': {
        'pattern': 'catboost_v12_q43_',
        'alt_pattern': 'catboost_v12_vegas_q43_',
        'exact': False,
        'feature_set': 'v12',
        'loss': 'quantile',
    },
    'v12_vegas_q45': {
        'pattern': 'catboost_v12_q45_',
        'alt_pattern': 'catboost_v12_vegas_q45_',
        'exact': False,
        'feature_set': 'v12',
        'loss': 'quantile',
    },
    'v12_mae': {
        'pattern': 'catboost_v12',
        'exact': False,  # Prefix match: catches 'catboost_v12', 'catboost_v12_noveg_train*',
                          # and 'catboost_v12_train*' (V12+vegas MAE)
        'feature_set': 'v12',
        'loss': 'mae',
    },
}


def classify_system_id(system_id: str) -> Optional[str]:
    """Classify a system_id into a model family.

    Args:
        system_id: e.g. 'catboost_v9', 'catboost_v9_q43_train1102_0131'

    Returns:
        Family key (e.g. 'v9_mae', 'v9_q43') or None if unrecognized.
    """
    for family_key, info in MODEL_FAMILIES.items():
        if info['exact']:
            if system_id == info['pattern']:
                return family_key
        else:
            if system_id.startswith(info['pattern']):
                return family_key
            if 'alt_pattern' in info and system_id.startswith(info['alt_pattern']):
                return family_key
    # Fallback: V9 MAE catch-all for registry names like
    # 'catboost_v9_33f_train...' that don't match specific V9 variants
    if system_id.startswith('catboost_v9'):
        return 'v9_mae'
    return None


# ---------------------------------------------------------------------------
# SQL WHERE clause for discovering all known model families
# ---------------------------------------------------------------------------

def build_system_id_sql_filter(alias: str = '') -> str:
    """Build a SQL OR clause matching all known model families.

    Returns something like:
        (system_id = 'catboost_v9' OR system_id = 'catboost_v12'
         OR system_id LIKE 'catboost_v9_q43_%' OR ...)
    """
    prefix = f"{alias}." if alias else ""
    clauses = []
    for info in MODEL_FAMILIES.values():
        col = f"{prefix}system_id"
        if info['exact']:
            clauses.append(f"{col} = '{info['pattern']}'")
        else:
            clauses.append(f"{col} LIKE '{info['pattern']}%'")
            if 'alt_pattern' in info:
                clauses.append(f"{col} LIKE '{info['alt_pattern']}%'")
    return '(' + ' OR '.join(clauses) + ')'


def build_noveg_mae_sql_filter(alias: str = '') -> str:
    """Build SQL filter for V12 noveg MAE models (excludes quantile).

    Matches system_ids like 'catboost_v12_noveg_train*' but NOT
    'catboost_v12_noveg_q43_*' or 'catboost_v12_noveg_q45_*'.

    Session 335: Extracted from hardcoded pattern in supplemental_data.py.
    """
    prefix = f"{alias}." if alias else ""
    col = f"{prefix}system_id"
    return f"({col} LIKE 'catboost_v12_noveg%' AND {col} NOT LIKE '%_q4%')"


# ---------------------------------------------------------------------------
# DiscoveredModels — runtime result of querying BQ for actual system_ids
# ---------------------------------------------------------------------------

@dataclass
class DiscoveredModels:
    """Result of discovering which models are active for a game date."""

    # All discovered system_ids
    all_system_ids: List[str] = field(default_factory=list)

    # Mapping: family_key → system_id (e.g. 'v9_mae' → 'catboost_v9')
    family_to_id: Dict[str, str] = field(default_factory=dict)

    # Reverse: system_id → family_key
    id_to_family: Dict[str, str] = field(default_factory=dict)

    @property
    def mae_ids(self) -> Set[str]:
        """System IDs of MAE-loss models."""
        return {
            sid for sid, fam in self.id_to_family.items()
            if MODEL_FAMILIES.get(fam, {}).get('loss') == 'mae'
        }

    @property
    def quantile_ids(self) -> Set[str]:
        """System IDs of quantile-loss models."""
        return {
            sid for sid, fam in self.id_to_family.items()
            if MODEL_FAMILIES.get(fam, {}).get('loss') == 'quantile'
        }

    @property
    def v9_ids(self) -> Set[str]:
        """System IDs using V9 feature set."""
        return {
            sid for sid, fam in self.id_to_family.items()
            if MODEL_FAMILIES.get(fam, {}).get('feature_set') == 'v9'
        }

    @property
    def v12_ids(self) -> Set[str]:
        """System IDs using V12 feature set."""
        return {
            sid for sid, fam in self.id_to_family.items()
            if MODEL_FAMILIES.get(fam, {}).get('feature_set') == 'v12'
        }

    @property
    def family_count(self) -> int:
        return len(self.family_to_id)

    def has_family(self, family_key: str) -> bool:
        return family_key in self.family_to_id

    def get_id(self, family_key: str) -> Optional[str]:
        return self.family_to_id.get(family_key)


def discover_models(bq_client, game_date: str,
                    project_id: str = 'nba-props-platform') -> DiscoveredModels:
    """Query BQ for active system_ids on a game date and classify them.

    Args:
        bq_client: BigQuery client.
        game_date: YYYY-MM-DD date string.
        project_id: GCP project.

    Returns:
        DiscoveredModels with classified system IDs.
    """
    from google.cloud import bigquery as bq

    sql_filter = build_system_id_sql_filter()
    query = f"""
    SELECT DISTINCT system_id
    FROM `{project_id}.nba_predictions.player_prop_predictions`
    WHERE game_date = @game_date
      AND is_active = TRUE
      AND recommendation IN ('OVER', 'UNDER')
      AND {sql_filter}
    """

    job_config = bq.QueryJobConfig(
        query_parameters=[
            bq.ScalarQueryParameter('game_date', 'DATE', game_date),
        ]
    )

    result = DiscoveredModels()

    try:
        rows = bq_client.query(query, job_config=job_config).result(timeout=30)
        for row in rows:
            sid = row['system_id']
            family = classify_system_id(sid)
            if family:
                result.all_system_ids.append(sid)
                result.family_to_id[family] = sid
                result.id_to_family[sid] = family
            else:
                logger.warning(f"Unclassified system_id in predictions: {sid}")
    except Exception as e:
        logger.error(f"Model discovery query failed: {e}", exc_info=True)

    logger.info(
        f"Discovered {result.family_count} model families for {game_date}: "
        f"{sorted(result.family_to_id.keys())}"
    )
    return result


# ---------------------------------------------------------------------------
# Cross-model subset definitions
# ---------------------------------------------------------------------------

CROSS_MODEL_SUBSETS = {
    'xm_consensus_3plus': {
        'description': '3+ models agree on direction, all with edge >= 3',
        'min_agreeing_models': 3,
        'min_edge': 3.0,
        'direction': None,  # ANY direction
        'top_n': None,      # No limit
    },
    'xm_consensus_4plus': {
        'description': '4+ models agree on direction, all with edge >= 3',
        'min_agreeing_models': 4,
        'min_edge': 3.0,
        'direction': None,
        'top_n': None,  # Natural sizing (Session 298)
    },
    'xm_quantile_agreement_under': {
        'description': 'All available quantile models agree UNDER, edge >= 3',
        'min_agreeing_models': 2,  # At least 2 quantile models must agree
        'min_edge': 3.0,
        'direction': 'UNDER',
        'require_all_quantile': True,  # All discovered quantile models must agree
        'top_n': None,
    },
    'xm_mae_plus_quantile_over': {
        'description': 'MAE model says OVER + any quantile confirms OVER',
        'min_agreeing_models': 2,
        'min_edge': 3.0,
        'direction': 'OVER',
        'require_mae_and_quantile': True,
        'top_n': None,
    },
    'xm_diverse_agreement': {
        'description': 'V9 + V12 (different feature sets) agree, both edge >= 3',
        'min_agreeing_models': 2,
        'min_edge': 3.0,
        'direction': None,
        'require_feature_diversity': True,
        'top_n': None,
    },
}
