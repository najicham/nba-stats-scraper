"""
Subset Definitions Exporter for Phase 6 Publishing

Exports available subset groups with clean, non-revealing names.
Shows what prediction groups are available without exposing technical details.
"""

import logging
from typing import Dict, List, Any

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.config.model_codenames import get_model_codename
from shared.config.subset_public_names import get_public_name

logger = logging.getLogger(__name__)


class SubsetDefinitionsExporter(BaseExporter):
    """
    Export subset definitions with clean public names.

    Output file:
    - systems/subsets.json - List of available groups

    JSON structure (CLEAN - no technical details):
    {
        "generated_at": "2026-02-03T...",
        "model": "926A",
        "groups": [
            {
                "id": "1",
                "name": "Top Pick",
                "description": "Single best pick"
            },
            {
                "id": "2",
                "name": "Top 5",
                "description": "Top 5 picks"
            },
            ...
        ]
    }
    """

    def generate_json(self) -> Dict[str, Any]:
        """
        Generate subset definitions JSON.

        Returns:
            Dictionary ready for JSON serialization with clean public names
        """
        # Query active subsets from database
        subsets = self._query_active_subsets()

        # Build clean output without technical details
        clean_groups = []
        for subset in subsets:
            # Get public name mapping
            public = get_public_name(subset['subset_id'])

            # Get clean description (use subset_id for lookup)
            description = self._clean_description(subset['subset_id'])

            clean_groups.append({
                'id': public['id'],
                'name': public['name'],
                'description': description
            })

        # Sort by ID for consistent ordering
        clean_groups.sort(key=lambda x: int(x['id']))

        return {
            'generated_at': self.get_generated_at(),
            'model': get_model_codename('catboost_v9'),  # '926A'
            'groups': clean_groups
        }

    def _query_active_subsets(self) -> List[Dict[str, Any]]:
        """
        Query active subset definitions from BigQuery.

        Returns:
            List of subset dictionaries with internal details
        """
        query = """
        SELECT
          subset_id,
          subset_name,
          subset_description,
          system_id,
          is_active
        FROM `nba_predictions.dynamic_subset_definitions`
        WHERE is_active = TRUE
          AND system_id = 'catboost_v9'
        ORDER BY subset_id
        """

        return self.query_to_list(query)

    def _clean_description(self, subset_id: str) -> str:
        """
        Get clean description for a subset.

        Uses generic descriptions that don't reveal technical details.

        Args:
            subset_id: Internal subset ID

        Returns:
            Cleaned description suitable for public API
        """
        # Always use generic descriptions - never expose database descriptions
        # which may contain technical details like edge thresholds
        generic_descriptions = {
            'v9_high_edge_top1': 'Single best pick',
            'v9_high_edge_top3': 'Top 3 picks',
            'v9_high_edge_top5': 'Top 5 picks',
            'v9_high_edge_top10': 'Top 10 picks',
            'v9_high_edge_balanced': 'Best value picks',
            'v9_high_edge_any': 'All picks',
            'v9_premium_safe': 'Premium selection',
            'v9_high_edge_warning': 'Alternative picks',
            'v9_high_edge_top5_balanced': 'Best value top 5',
        }

        # Return generic description
        return generic_descriptions.get(subset_id, 'Curated selection')

    def export(self) -> str:
        """
        Generate and upload subset definitions to GCS.

        Returns:
            GCS path where file was uploaded
        """
        json_data = self.generate_json()

        # Upload to GCS (24 hour cache since definitions rarely change)
        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path='systems/subsets.json',
            cache_control='public, max-age=86400'  # 24 hours
        )

        logger.info(
            f"Exported {len(json_data.get('groups', []))} subset definitions "
            f"to {gcs_path}"
        )

        return gcs_path
