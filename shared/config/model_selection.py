"""Model selection configuration.

Allows overriding which model drives best bets via the BEST_BETS_MODEL_ID
environment variable, while keeping the champion model ID stable for
baseline comparisons and grading queries.

Created: 2026-02-15 (Session 260)
"""

import os

CHAMPION_MODEL_ID = 'catboost_v9'

# Per-model configuration for best bets filtering.
# V12 confidence 0.87 tier has 41.7% HR (below 52.4% breakeven).
# V12 confidence 0.90+ has 60.5% HR. Clean boundary — only 4 discrete values.
MODEL_CONFIG = {
    'catboost_v12': {
        'min_confidence': 0.90,
    },
}


def get_best_bets_model_id() -> str:
    """Return the model ID to use for best bets and signal evaluation.

    Reads BEST_BETS_MODEL_ID env var. Falls back to champion model.
    """
    return os.environ.get('BEST_BETS_MODEL_ID', CHAMPION_MODEL_ID)


def get_model_config(model_id: str) -> dict:
    """Return model-specific config dict. Empty dict if no config."""
    return MODEL_CONFIG.get(model_id, {})


def get_min_confidence(model_id: str) -> float:
    """Return minimum confidence score for best bets filtering.

    Returns 0.0 (no filter) if model has no confidence floor configured.
    """
    return get_model_config(model_id).get('min_confidence', 0.0)


def get_champion_model_id() -> str:
    """Return the champion model ID (always catboost_v9).

    Use this for baseline comparisons and grading queries that
    should always reference the champion regardless of which model
    drives best bets.
    """
    return CHAMPION_MODEL_ID
