"""Subset Membership Lookup — finds which Level 1/2 subsets each player-game qualified for.

Queries current_subset_picks AFTER SubsetMaterializer + CrossModelSubsetMaterializer
have run, so the aggregator can see which subsets a pick already belongs to.

Session 279: Initial creation (Pick Provenance).
"""

import logging
from typing import Any, Dict, List

from google.cloud import bigquery

logger = logging.getLogger(__name__)


def lookup_qualifying_subsets(
    bq_client: bigquery.Client,
    game_date: str,
    version_id: str,
    project_id: str = 'nba-props-platform',
) -> Dict[str, List[Dict[str, Any]]]:
    """Query which Level 1/2 subsets each player-game already appears in.

    Called AFTER SubsetMaterializer + CrossModelSubsetMaterializer have written
    to current_subset_picks, so we can look up subset membership for the
    aggregator to attach as provenance.

    Args:
        bq_client: BigQuery client.
        game_date: Target date (YYYY-MM-DD).
        version_id: Version from SubsetMaterializer (ensures we only see
                     subsets from the current materialization batch).
        project_id: GCP project ID.

    Returns:
        Dict mapping "player_lookup::game_id" to list of qualifying subsets:
        [{"subset_id": str, "system_id": str, "rank_in_subset": int}, ...]
    """
    query = f"""
    SELECT player_lookup, game_id, subset_id, system_id, rank_in_subset
    FROM `{project_id}.nba_predictions.current_subset_picks`
    WHERE game_date = @game_date
      AND version_id = @version_id
      AND subset_id != 'best_bets'
    ORDER BY player_lookup, game_id, subset_id
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
            bigquery.ScalarQueryParameter('version_id', 'STRING', version_id),
        ]
    )

    try:
        result = bq_client.query(query, job_config=job_config).result(timeout=60)
    except Exception as e:
        logger.error(f"Qualifying subsets lookup failed: {e}", exc_info=True)
        return {}

    # Group by player_lookup::game_id
    membership: Dict[str, List[Dict[str, Any]]] = {}
    for row in result:
        key = f"{row['player_lookup']}::{row['game_id']}"
        if key not in membership:
            membership[key] = []
        membership[key].append({
            'subset_id': row['subset_id'],
            'system_id': row['system_id'],
            'rank_in_subset': row['rank_in_subset'],
        })

    if membership:
        total_entries = sum(len(v) for v in membership.values())
        logger.info(
            f"Qualifying subsets lookup: {len(membership)} player-games, "
            f"{total_entries} total subset memberships"
        )

    return membership
