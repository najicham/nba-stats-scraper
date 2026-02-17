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
    # Nova (V12) subsets (Session 232)
    'nova_top_pick': {'id': '14', 'name': 'Nova Top Pick'},
    'nova_top_3': {'id': '15', 'name': 'Nova Top 3'},
    'nova_top_5': {'id': '16', 'name': 'Nova Top 5'},
    'nova_high_edge_over': {'id': '17', 'name': 'Nova High Edge OVER'},
    'nova_high_edge_all': {'id': '18', 'name': 'Nova High Edge All'},
    'nova_ultra_high_edge': {'id': '19', 'name': 'Nova Ultra High Edge'},
    'nova_green_light': {'id': '20', 'name': 'Nova Green Light'},
    'nova_all_picks': {'id': '21', 'name': 'Nova All Picks'},
    # "All Predictions" subsets — unfiltered, no quality gate (Session 242)
    'v9_all_predictions': {'id': '22', 'name': 'All Predictions'},
    'q43_all_predictions': {'id': '23', 'name': 'All Predictions'},
    'q45_all_predictions': {'id': '24', 'name': 'All Predictions'},
    'nova_all_predictions': {'id': '25', 'name': 'All Predictions'},
    # Best Bets — curated by Signal Discovery Framework (Session 254-255)
    'best_bets': {'id': '26', 'name': 'Best Bets'},
    # V12-Quantile subsets (Session 277)
    'v12q43_under_top3': {'id': '27', 'name': 'V12 Q43 UNDER Top 3'},
    'v12q43_all_picks': {'id': '28', 'name': 'V12 Q43 All Picks'},
    'v12q45_under_top3': {'id': '29', 'name': 'V12 Q45 UNDER Top 3'},
    'v12q45_all_picks': {'id': '30', 'name': 'V12 Q45 All Picks'},
    # Cross-model observation subsets (Session 277)
    'xm_consensus_3plus': {'id': '31', 'name': 'Cross-Model 3+ Agree'},
    'xm_consensus_5plus': {'id': '32', 'name': 'Cross-Model 5+ Agree'},
    'xm_quantile_agreement_under': {'id': '33', 'name': 'Quantile Consensus UNDER'},
    'xm_mae_plus_quantile_over': {'id': '34', 'name': 'MAE + Quantile OVER'},
    'xm_diverse_agreement': {'id': '35', 'name': 'V9 + V12 Diverse Agree'},
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
