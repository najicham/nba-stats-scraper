"""
Subset Definitions Exporter for Phase 6 Publishing

Exports available subset groups with clean, non-revealing names.
Shows what prediction groups are available without exposing technical details.

Session 188: Multi-model support — model_groups structure.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Any

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.config.model_codenames import get_model_codename, get_model_display_info, CHAMPION_CODENAME
from shared.config.subset_public_names import get_public_name

logger = logging.getLogger(__name__)


class SubsetDefinitionsExporter(BaseExporter):
    """
    Export subset definitions with clean public names.

    Output file:
    - systems/subsets.json - List of available groups

    Session 188: model_groups structure with subsets per model.

    JSON structure (v2):
    {
        "generated_at": "2026-02-10T...",
        "version": 2,
        "model_groups": [
            {
                "model_id": "926A",
                "model_name": "V9 Champion",
                "model_type": "standard",
                "description": "Primary prediction model",
                "subsets": [
                    {"id": "1", "name": "Top Pick", "description": "Single best pick"},
                    ...
                ]
            }
        ]
    }
    """

    def generate_json(self) -> Dict[str, Any]:
        """
        Generate subset definitions JSON grouped by model.

        Returns:
            Dictionary ready for JSON serialization with clean public names
        """
        subsets = self._query_active_subsets()

        # Group by system_id
        subsets_by_model = defaultdict(list)
        for subset in subsets:
            subsets_by_model[subset['system_id']].append(subset)

        model_groups = []
        for system_id, model_subsets in subsets_by_model.items():
            display = get_model_display_info(system_id)

            clean_subsets = []
            for subset in model_subsets:
                public = get_public_name(subset['subset_id'])
                description = self._clean_description(subset['subset_id'])

                clean_subsets.append({
                    'id': public['id'],
                    'name': public['name'],
                    'description': description,
                })

            clean_subsets.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 999)

            model_groups.append({
                'model_id': display['codename'],
                'model_name': display['display_name'],
                'model_type': display['model_type'],
                'description': display['description'],
                'subsets': clean_subsets,
            })

        # Sort: champion first, then by codename
        model_groups.sort(key=lambda x: (0 if x['model_id'] == CHAMPION_CODENAME else 1, x['model_id']))

        return {
            'generated_at': self.get_generated_at(),
            'version': 2,
            'model_groups': model_groups,
        }

    def _query_active_subsets(self) -> List[Dict[str, Any]]:
        """
        Query active subset definitions from BigQuery (all models).

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
        ORDER BY system_id, subset_id
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
        generic_descriptions = {
            # Champion V9 subsets
            'v9_high_edge_top1': 'Single best pick',
            'v9_high_edge_top3': 'Top 3 picks',
            'v9_high_edge_top5': 'Top 5 picks',
            'v9_high_edge_top10': 'Top 10 picks',
            'v9_high_edge_balanced': 'Best value picks',
            'v9_high_edge_any': 'All picks',
            'v9_premium_safe': 'Premium selection',
            'v9_high_edge_warning': 'Alternative picks',
            'v9_high_edge_top5_balanced': 'Best value top 5',
            # QUANT Q43 subsets (Session 188)
            'q43_under_top3': 'Top 3 UNDER picks',
            'q43_under_all': 'All UNDER picks',
            'q43_all_picks': 'All picks',
            # QUANT Q45 subsets (Session 188)
            'q45_under_top3': 'Top 3 UNDER picks',
            'q45_all_picks': 'All picks',
        }

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

        total_subsets = sum(
            len(mg.get('subsets', []))
            for mg in json_data.get('model_groups', [])
        )
        logger.info(
            f"Exported {total_subsets} subset definitions across "
            f"{len(json_data.get('model_groups', []))} models to {gcs_path}"
        )

        return gcs_path
