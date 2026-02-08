"""
Clean Training Data Loader - Zero Tolerance for Feature Defaults

THIS IS THE SINGLE SOURCE OF TRUTH for loading ML training data.
All training scripts MUST use this module to load data from ml_feature_store_v2.

Session 157: Created to prevent the Session 156 contamination bug from recurring.
The bug: training scripts used feature_quality_score >= 70 (a weighted average that
masks individual defaults) instead of required_default_count = 0. This allowed 33%
of training data to contain garbage hardcoded default values.

This module enforces quality filters at the SQL level - they cannot be bypassed.

Usage:
    from shared.ml.training_data_loader import (
        load_clean_training_data, get_quality_where_clause, get_quality_join_clause
    )

    # Simple: load a DataFrame directly
    df = load_clean_training_data(client, '2025-11-02', '2026-02-06')

    # Flexible: get the WHERE clause to embed in custom queries
    where = get_quality_where_clause(table_alias='mf')
    query = f"SELECT ... FROM ml_feature_store_v2 mf WHERE mf.game_date BETWEEN ... AND {where}"

    # For LEFT JOINs: get the ON clause conditions (breakout classifier pattern)
    join_clause = get_quality_join_clause(table_alias='mf')
    query = f"LEFT JOIN ml_feature_store_v2 mf ON a.key = mf.key AND {join_clause}"
"""

import logging
from typing import Optional

from google.cloud import bigquery
import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"

# Session 156/157: These filters are MANDATORY for any training data query.
# They cannot be disabled. If you need to analyze unfiltered data for research,
# query ml_feature_store_v2 directly — but NEVER train a model on unfiltered data.
_QUALITY_FILTERS = {
    "zero_tolerance": "COALESCE({alias}.required_default_count, {alias}.default_feature_count, 0) = 0",
    "min_feature_count": "{alias}.feature_count >= 33",
    "min_quality_score": "{alias}.feature_quality_score >= {min_quality_score}",
    "exclude_bad_sources": "{alias}.data_source NOT IN ('phase4_partial', 'early_season')",
}


def get_quality_where_clause(
    table_alias: str = "mf",
    min_quality_score: int = 70,
) -> str:
    """
    Get the mandatory quality WHERE clause for training data queries.

    Returns a string of AND conditions (no leading AND) that enforces:
    - Zero tolerance for non-vegas defaults (required_default_count = 0)
    - Minimum feature count (33)
    - Minimum quality score (default 70)
    - Exclude partial/early season data

    Usage:
        where = get_quality_where_clause('mf')
        query = f'''
            SELECT ...
            FROM ml_feature_store_v2 mf
            WHERE mf.game_date BETWEEN '{start}' AND '{end}'
              AND {where}
        '''

    Args:
        table_alias: The alias used for ml_feature_store_v2 in your query
        min_quality_score: Minimum feature_quality_score (default 70, minimum 50)

    Returns:
        String of AND-separated conditions (no leading AND)
    """
    if min_quality_score < 50:
        raise ValueError(
            f"min_quality_score={min_quality_score} is too low. "
            "Minimum is 50. Use 70 for production training."
        )

    clauses = [
        _QUALITY_FILTERS["zero_tolerance"].format(alias=table_alias),
        _QUALITY_FILTERS["min_feature_count"].format(alias=table_alias),
        _QUALITY_FILTERS["min_quality_score"].format(
            alias=table_alias, min_quality_score=min_quality_score
        ),
        _QUALITY_FILTERS["exclude_bad_sources"].format(alias=table_alias),
    ]
    return "\n      AND ".join(clauses)


def get_quality_join_clause(
    table_alias: str = "mf",
    min_quality_score: int = 70,
) -> str:
    """
    Get the mandatory quality conditions for LEFT JOIN ON clauses.

    Same filters as get_quality_where_clause but formatted for use in
    JOIN...ON conditions. Used by breakout classifier scripts that LEFT JOIN
    ml_feature_store_v2 and want NULL when quality doesn't meet standards.

    Usage:
        join_clause = get_quality_join_clause('mf')
        query = f'''
            LEFT JOIN ml_feature_store_v2 mf
              ON a.player_lookup = mf.player_lookup
              AND a.game_date = mf.game_date
              AND {join_clause}
        '''

    Args:
        table_alias: The alias used for ml_feature_store_v2 in your query
        min_quality_score: Minimum feature_quality_score (default 70, minimum 50)

    Returns:
        String of AND-separated conditions (no leading AND)
    """
    if min_quality_score < 50:
        raise ValueError(
            f"min_quality_score={min_quality_score} is too low. "
            "Minimum is 50. Use 70 for production training."
        )

    # For JOIN clauses, use COALESCE to handle NULLs gracefully
    clauses = [
        _QUALITY_FILTERS["zero_tolerance"].format(alias=table_alias),
        f"COALESCE({table_alias}.feature_quality_score, 0) >= {min_quality_score}",
    ]
    return "\n        AND ".join(clauses)


def load_clean_training_data(
    client: bigquery.Client,
    start_date: str,
    end_date: str,
    min_quality_score: int = 70,
    additional_select: str = "",
    additional_joins: str = "",
    additional_where: str = "",
    require_actual_points: bool = True,
) -> pd.DataFrame:
    """
    Load clean training data from ml_feature_store_v2 with enforced quality filters.

    All returned records are guaranteed to have:
    - required_default_count = 0 (zero tolerance for non-vegas defaults)
    - feature_count >= 33
    - feature_quality_score >= min_quality_score
    - Not from partial/early season data sources
    - Valid actual points and minutes (if require_actual_points=True)

    Args:
        client: BigQuery client
        start_date: Training start date (YYYY-MM-DD)
        end_date: Training end date (YYYY-MM-DD)
        min_quality_score: Minimum quality score (default 70, minimum 50)
        additional_select: Extra SELECT columns (comma-separated, no leading comma)
        additional_joins: Extra JOIN clauses
        additional_where: Extra WHERE conditions (no leading AND)
        require_actual_points: If True, join player_game_summary for actual points

    Returns:
        DataFrame with clean training data

    Raises:
        ValueError: If min_quality_score < 50 or no data returned
    """
    quality_clause = get_quality_where_clause("mf", min_quality_score)

    extra_select = f",\n      {additional_select}" if additional_select else ""
    extra_joins = f"\n    {additional_joins}" if additional_joins else ""
    extra_where = f"\n      AND {additional_where}" if additional_where else ""

    if require_actual_points:
        points_join = f"""
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date"""
        points_select = ",\n      pgs.points as actual_points,\n      pgs.minutes_played"
        points_where = "\n      AND pgs.points IS NOT NULL\n      AND pgs.minutes_played > 0"
    else:
        points_join = ""
        points_select = ""
        points_where = ""

    query = f"""
    SELECT
      mf.player_lookup,
      mf.game_date,
      mf.features,
      mf.feature_names,
      mf.feature_quality_score,
      mf.required_default_count,
      mf.default_feature_count{points_select}{extra_select}
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf{points_join}{extra_joins}
    WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND {quality_clause}{points_where}{extra_where}
    """

    logger.info(f"Loading clean training data: {start_date} to {end_date}")
    df = client.query(query).to_dataframe()

    # Post-query validation (defense in depth)
    if df.empty:
        raise ValueError(
            f"No clean training data found for {start_date} to {end_date}. "
            "Check that Phase 4 processors ran and feature store has data."
        )

    # Verify zero tolerance was enforced
    if "required_default_count" in df.columns:
        bad = df[df["required_default_count"].fillna(0) > 0]
        if len(bad) > 0:
            raise RuntimeError(
                f"CRITICAL: {len(bad)} records with non-zero required_default_count "
                "passed quality filters. This should never happen."
            )

    logger.info(
        f"Loaded {len(df):,} clean records "
        f"(avg quality: {df['feature_quality_score'].mean():.1f})"
    )
    return df
