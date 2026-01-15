#!/usr/bin/env python3
"""
Re-map Failed Players

Re-runs BDL player ID mapping for only the players that previously failed,
using improved accent character handling.

Usage:
    source .env && python scripts/mlb/remap_failed_players.py
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from google.cloud import bigquery

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from build_bdl_player_mapping import (
    search_bdl_player,
    match_pitcher,
    update_registry,
    strip_accents
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    # Check API key
    api_key = os.environ.get('BDL_API_KEY', '')
    if not api_key:
        logger.error("BDL_API_KEY environment variable not set")
        sys.exit(1)

    # Load previous results
    with open('scripts/mlb/bdl_mapping_results.json', 'r') as f:
        previous = json.load(f)

    not_found = previous.get('not_found', [])
    logger.info(f"Re-mapping {len(not_found)} previously failed players")

    client = bigquery.Client()

    # Process each failed player
    new_mappings = []
    still_failed = []

    for i, player in enumerate(not_found):
        player_lookup = player['player_lookup']
        player_full_name = player['player_full_name']
        team_abbr = player.get('team_abbr', 'UNK')

        logger.info(f"[{i+1}/{len(not_found)}] Processing: {player_full_name}")

        # Search BDL API (with improved accent handling)
        bdl_players = search_bdl_player(player_full_name, api_key)

        # Match to our pitcher
        match = match_pitcher(player_full_name, bdl_players, team_abbr)

        if match:
            logger.info(f"  ✅ MATCHED -> {match['full_name']} (ID: {match['id']})")
            new_mappings.append({
                'player_lookup': player_lookup,
                'player_full_name': player_full_name,
                'bdl_player_id': match['id'],
                'bdl_full_name': match.get('full_name', ''),
                'bdl_position': match.get('position', ''),
                'bdl_team_abbr': match.get('team', {}).get('abbreviation', ''),
            })
        else:
            logger.info(f"  ❌ Still not found")
            still_failed.append(player)

        # Rate limiting
        time.sleep(0.3)

    # Report results
    logger.info(f"\n{'='*60}")
    logger.info(f"RESULTS")
    logger.info(f"{'='*60}")
    logger.info(f"Previously failed: {len(not_found)}")
    logger.info(f"Now matched: {len(new_mappings)}")
    logger.info(f"Still failed: {len(still_failed)}")
    logger.info(f"Success rate: {100*len(new_mappings)/len(not_found):.1f}%")

    if new_mappings:
        logger.info(f"\nNew matches:")
        for m in new_mappings:
            logger.info(f"  {m['player_full_name']} -> {m['bdl_full_name']} (ID: {m['bdl_player_id']})")

    if still_failed:
        logger.info(f"\nStill failed ({len(still_failed)}):")
        for p in still_failed:
            logger.info(f"  {p['player_full_name']}")

    # Update registry with new mappings
    if new_mappings:
        logger.info(f"\nUpdating registry...")
        updated = update_registry(client, new_mappings, dry_run=False)
        logger.info(f"Registry updates: {updated}")

    # Save updated results
    results = {
        'timestamp': datetime.now().isoformat(),
        'original_failed': len(not_found),
        'newly_matched': len(new_mappings),
        'still_failed': len(still_failed),
        'new_mappings': new_mappings,
        'still_failed_list': still_failed,
    }

    output_path = 'scripts/mlb/remap_results.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    logger.info(f"Results saved to {output_path}")


if __name__ == '__main__':
    main()
