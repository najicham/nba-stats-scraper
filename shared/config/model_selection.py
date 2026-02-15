"""Model selection configuration.

Allows overriding which model drives best bets via the BEST_BETS_MODEL_ID
environment variable, while keeping the champion model ID stable for
baseline comparisons and grading queries.

Created: 2026-02-15 (Session 260)
"""

import os

CHAMPION_MODEL_ID = 'catboost_v9'


def get_best_bets_model_id() -> str:
    """Return the model ID to use for best bets and signal evaluation.

    Reads BEST_BETS_MODEL_ID env var. Falls back to champion model.
    """
    return os.environ.get('BEST_BETS_MODEL_ID', CHAMPION_MODEL_ID)


def get_champion_model_id() -> str:
    """Return the champion model ID (always catboost_v9).

    Use this for baseline comparisons and grading queries that
    should always reference the champion regardless of which model
    drives best bets.
    """
    return CHAMPION_MODEL_ID
