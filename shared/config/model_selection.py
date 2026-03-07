"""Model selection configuration.

Allows overriding which model drives best bets via the BEST_BETS_MODEL_ID
environment variable, while keeping the champion model ID stable for
baseline comparisons and grading queries.

Created: 2026-02-15 (Session 260)
Session 429: Champion model now queried from model_registry (is_production=TRUE).
"""

import logging
import os
import time

logger = logging.getLogger(__name__)

# Fallback if registry query fails
_DEFAULT_CHAMPION = 'catboost_v12'

# Cache to avoid hitting BQ on every call
_champion_cache = {'model_id': None, 'expires': 0}
_CACHE_TTL_SECONDS = 3600  # 1 hour

# Per-model configuration for best bets filtering.
# V12 confidence 0.87 tier has 41.7% HR (below 52.4% breakeven).
# V12 confidence 0.90+ has 60.5% HR. Clean boundary — only 4 discrete values.
MODEL_CONFIG = {
    'catboost_v12': {
        'min_confidence': 0.90,
    },
}


# Backwards compatibility — code that references CHAMPION_MODEL_ID directly
CHAMPION_MODEL_ID = _DEFAULT_CHAMPION


def get_best_bets_model_id() -> str:
    """Return the model ID to use for best bets and signal evaluation.

    Reads BEST_BETS_MODEL_ID env var. Falls back to champion model from registry.
    """
    return os.environ.get('BEST_BETS_MODEL_ID', get_champion_model_id())


def get_model_config(model_id: str) -> dict:
    """Return model-specific config dict. Empty dict if no config."""
    return MODEL_CONFIG.get(model_id, {})


def get_min_confidence(model_id: str) -> float:
    """Return minimum confidence score for best bets filtering.

    Returns 0.0 (no filter) if model has no confidence floor configured.
    """
    return get_model_config(model_id).get('min_confidence', 0.0)


def get_champion_model_id() -> str:
    """Return the champion model ID from model_registry (is_production=TRUE).

    Queries BQ with 1-hour cache. Falls back to _DEFAULT_CHAMPION on failure.
    Champion changes are now a BQ UPDATE instead of a code change + deploy.
    """
    now = time.time()
    if _champion_cache['model_id'] and now < _champion_cache['expires']:
        return _champion_cache['model_id']

    try:
        from google.cloud import bigquery
        project = os.environ.get('GCP_PROJECT_ID', os.environ.get('GCP_PROJECT', 'nba-props-platform'))
        client = bigquery.Client(project=project)
        query = f"""
        SELECT model_id FROM `{project}.nba_predictions.model_registry`
        WHERE is_production = TRUE AND enabled = TRUE
        LIMIT 1
        """
        rows = list(client.query(query).result())
        if rows:
            champion = rows[0].model_id
            _champion_cache['model_id'] = champion
            _champion_cache['expires'] = now + _CACHE_TTL_SECONDS
            return champion
    except Exception as e:
        logger.warning(f"Failed to query champion from registry, using default: {e}")

    return _DEFAULT_CHAMPION
