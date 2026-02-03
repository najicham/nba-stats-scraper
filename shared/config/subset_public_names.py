"""
Subset public name mappings for clean API.

Maps internal subset IDs to user-facing names and IDs that don't reveal
technical details or strategy.
"""

# Subset public name mapping
# IDs ordered logically: Top 1-10, Best Value variants, Premium, Alternative
SUBSET_PUBLIC_NAMES = {
    'v9_high_edge_top1': {'id': '1', 'name': 'Top Pick'},
    'v9_high_edge_top3': {'id': '2', 'name': 'Top 3'},
    'v9_high_edge_top5': {'id': '3', 'name': 'Top 5'},
    'v9_high_edge_top10': {'id': '4', 'name': 'Top 10'},
    'v9_high_edge_balanced': {'id': '5', 'name': 'Best Value'},
    'v9_high_edge_top5_balanced': {'id': '6', 'name': 'Best Value Top 5'},
    'v9_high_edge_any': {'id': '7', 'name': 'All Picks'},
    'v9_premium_safe': {'id': '8', 'name': 'Premium'},
    'v9_high_edge_warning': {'id': '9', 'name': 'Alternative'},
}

# Reverse lookup
PUBLIC_ID_TO_SUBSET = {v['id']: k for k, v in SUBSET_PUBLIC_NAMES.items()}


def get_public_name(subset_id: str) -> dict:
    """Get public name and ID for a subset_id."""
    if subset_id in SUBSET_PUBLIC_NAMES:
        return SUBSET_PUBLIC_NAMES[subset_id]

    # Log warning and return generic placeholder (don't expose internal ID)
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Unknown subset_id '{subset_id}' not in SUBSET_PUBLIC_NAMES - using generic placeholder")
    return {
        'id': 'unknown',
        'name': 'Other'
    }


def get_subset_from_public_id(public_id: str) -> str:
    """Get subset_id from public ID."""
    return PUBLIC_ID_TO_SUBSET.get(public_id, public_id)
