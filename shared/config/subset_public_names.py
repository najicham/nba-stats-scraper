"""
Subset public name mappings for clean API.

Maps internal subset IDs to user-facing names and IDs that don't reveal
technical details or strategy.

Session 154: Redesigned from 18 overlapping subsets to 8 clean, distinct subsets
based on full-season performance data. Key dimensions: edge, direction, signal.
"""

# Subset public name mapping
# IDs ordered by conviction: highest first
SUBSET_PUBLIC_NAMES = {
    'top_pick': {'id': '1', 'name': 'Top Pick'},
    'top_3': {'id': '2', 'name': 'Top 3'},
    'top_5': {'id': '3', 'name': 'Top 5'},
    'high_edge_over': {'id': '4', 'name': 'High Edge OVER'},
    'high_edge_all': {'id': '5', 'name': 'High Edge All'},
    'ultra_high_edge': {'id': '6', 'name': 'Ultra High Edge'},
    'green_light': {'id': '7', 'name': 'Green Light'},
    'all_picks': {'id': '8', 'name': 'All Picks'},
    # QUANT Q43 subsets (Session 188)
    'q43_under_top3': {'id': '9', 'name': 'UNDER Top 3'},
    'q43_under_all': {'id': '10', 'name': 'UNDER All'},
    'q43_all_picks': {'id': '11', 'name': 'Q43 All Picks'},
    # QUANT Q45 subsets (Session 188)
    'q45_under_top3': {'id': '12', 'name': 'Q45 UNDER Top 3'},
    'q45_all_picks': {'id': '13', 'name': 'Q45 All Picks'},
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
