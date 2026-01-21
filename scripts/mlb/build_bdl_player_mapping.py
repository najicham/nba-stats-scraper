#!/usr/bin/env python3
"""
Build BDL Player ID Mapping

Maps MLB pitchers from our pitcher_game_summary table to Ball Don't Lie API player IDs.
Updates the mlb_players_registry with bdl_player_id.

Usage:
    python scripts/mlb/build_bdl_player_mapping.py [--dry-run] [--limit N]
"""

import os
import sys
import json
import time
import logging
import argparse
import unicodedata
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import requests
from google.cloud import bigquery


def strip_accents(text: str) -> str:
    """Remove accent characters from text (é -> e, ñ -> n, etc.)"""
    if not text:
        return text
    # Normalize to decomposed form (separate base char from accent)
    # Then filter out combining characters (accents)
    normalized = unicodedata.normalize('NFD', text)
    return ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# BDL API config
BDL_API_KEY = os.environ.get('BDL_API_KEY', '')
BDL_MLB_API_ROOT = 'https://api.balldontlie.io/mlb/v1'


def get_unique_pitchers(client: bigquery.Client, limit: Optional[int] = None) -> List[Dict]:
    """Get unique pitchers from pitcher_game_summary."""
    limit_clause = f"LIMIT {limit}" if limit else ""

    query = f"""
    SELECT DISTINCT
        player_lookup,
        player_full_name,
        team_abbr,
        -- Get most recent appearance info
        MAX(game_date) as last_game_date
    FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
    WHERE game_date >= '2024-01-01'
      AND player_lookup IS NOT NULL
      AND player_full_name IS NOT NULL
    GROUP BY player_lookup, player_full_name, team_abbr
    ORDER BY last_game_date DESC
    {limit_clause}
    """

    result = client.query(query).result()
    return [dict(row) for row in result]


def search_bdl_player(name: str, api_key: str) -> List[Dict]:
    """Search BDL API for players by name. Tries both accented and non-accented versions."""
    headers = {'Authorization': api_key}
    url = f"{BDL_MLB_API_ROOT}/players"

    def do_search(search_term: str) -> List[Dict]:
        try:
            resp = requests.get(
                url,
                headers=headers,
                params={'search': search_term},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get('data', [])
        except Exception as e:
            logger.warning(f"Search failed for '{search_term}': {e}")
            return []

    # Search by last name for better results
    parts = name.split()
    search_term = parts[-1] if parts else name  # Use last name

    # First try original name
    results = do_search(search_term)

    # If no results and name has accents, try without accents
    stripped = strip_accents(search_term)
    if not results and stripped != search_term:
        logger.info(f"  Retrying search without accents: '{search_term}' -> '{stripped}'")
        results = do_search(stripped)

    # If still no results, try first name
    if not results and len(parts) > 1:
        first_name = strip_accents(parts[0])
        logger.info(f"  Trying first name search: '{first_name}'")
        results = do_search(first_name)

    return results


def match_pitcher(
    player_full_name: str,
    bdl_players: List[Dict],
    team_abbr: Optional[str] = None
) -> Optional[Dict]:
    """Match our pitcher to BDL player results."""
    if not bdl_players:
        return None

    # Normalize names for comparison (including accent removal)
    def normalize(name: str) -> str:
        name = strip_accents(name)  # Remove accents first
        return name.lower().replace('.', '').replace('-', '').replace("'", "").strip()

    target_name = normalize(player_full_name)

    # First pass: exact match on active pitchers
    for player in bdl_players:
        bdl_name = normalize(player.get('full_name', ''))
        position = player.get('position', '').lower()
        is_active = player.get('active', False)

        # Must be a pitcher
        if 'pitcher' not in position:
            continue

        # Exact name match
        if bdl_name == target_name:
            # Prefer active players
            if is_active:
                return player

    # Second pass: exact match on any pitcher (including inactive)
    for player in bdl_players:
        bdl_name = normalize(player.get('full_name', ''))
        position = player.get('position', '').lower()

        if 'pitcher' not in position:
            continue

        if bdl_name == target_name:
            return player

    # Third pass: first+last name match (handles middle names, suffixes)
    target_parts = target_name.split()
    target_first = target_parts[0] if target_parts else ''
    target_last = target_parts[-1] if len(target_parts) > 1 else ''

    for player in bdl_players:
        first = normalize(player.get('first_name', ''))
        last = normalize(player.get('last_name', ''))
        position = player.get('position', '').lower()
        is_active = player.get('active', False)

        if 'pitcher' not in position:
            continue

        if first == target_first and last == target_last:
            if is_active:
                return player

    # Fourth pass: team match as tiebreaker
    if team_abbr and team_abbr != 'UNK':
        for player in bdl_players:
            position = player.get('position', '').lower()
            if 'pitcher' not in position:
                continue

            bdl_team = player.get('team', {}).get('abbreviation', '')
            if bdl_team == team_abbr:
                # Close enough name match
                bdl_name = normalize(player.get('full_name', ''))
                if target_parts[0] in bdl_name or target_parts[-1] in bdl_name:
                    return player

    return None


def update_registry(
    client: bigquery.Client,
    mappings: List[Dict],
    dry_run: bool = False
) -> int:
    """Update mlb_players_registry with BDL player IDs."""
    if not mappings:
        return 0

    if dry_run:
        logger.info(f"DRY RUN: Would update {len(mappings)} registry entries")
        return len(mappings)

    # Use MERGE statement to upsert
    # First, create temp table with mappings
    temp_table_id = f"nba-props-platform.mlb_reference._temp_bdl_mappings_{int(time.time())}"

    # Create schema for temp table
    schema = [
        bigquery.SchemaField("player_lookup", "STRING"),
        bigquery.SchemaField("bdl_player_id", "INT64"),
        bigquery.SchemaField("bdl_full_name", "STRING"),
        bigquery.SchemaField("bdl_position", "STRING"),
        bigquery.SchemaField("bdl_team_abbr", "STRING"),
    ]

    # Create temp table
    temp_table = bigquery.Table(temp_table_id, schema=schema)
    temp_table.expires = datetime.utcnow().replace(hour=datetime.utcnow().hour + 1)  # Expire in 1 hour

    try:
        client.create_table(temp_table, exists_ok=True)

        # Insert mappings into temp table
        rows = [
            {
                'player_lookup': m['player_lookup'],
                'bdl_player_id': m['bdl_player_id'],
                'bdl_full_name': m['bdl_full_name'],
                'bdl_position': m['bdl_position'],
                'bdl_team_abbr': m['bdl_team_abbr'],
            }
            for m in mappings
        ]

        errors = client.insert_rows_json(temp_table_id, rows)
        if errors:
            logger.error(f"Error inserting rows: {errors}")
            return 0

        # Wait for data to be available
        time.sleep(2)

        # Update registry using MERGE
        merge_query = f"""
        MERGE `nba-props-platform.mlb_reference.mlb_players_registry` T
        USING `{temp_table_id}` S
        ON T.player_lookup = S.player_lookup
        WHEN MATCHED THEN
            UPDATE SET
                bdl_player_id = S.bdl_player_id,
                processed_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
            INSERT (player_lookup, player_full_name, bdl_player_id, player_type, season_year, team_abbr, created_at, processed_at)
            VALUES (S.player_lookup, S.bdl_full_name, S.bdl_player_id, 'PITCHER', 2025, S.bdl_team_abbr, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
        """

        job = client.query(merge_query)
        job.result()

        logger.info(f"Successfully updated {len(mappings)} registry entries")
        return len(mappings)

    except Exception as e:
        logger.error(f"Error updating registry: {e}")
        return 0
    finally:
        # Clean up temp table
        try:
            client.delete_table(temp_table_id, not_found_ok=True)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description='Build BDL player ID mappings')
    parser.add_argument('--dry-run', action='store_true', help='Do not update database')
    parser.add_argument('--limit', type=int, help='Limit number of pitchers to process')
    parser.add_argument('--delay', type=float, default=0.1, help='Delay between API calls (seconds)')
    args = parser.parse_args()

    # Check API key
    api_key = os.environ.get('BDL_API_KEY', '')
    if not api_key:
        logger.error("BDL_API_KEY environment variable not set")
        sys.exit(1)

    logger.info("Starting BDL player ID mapping build")

    # Initialize BigQuery client
    client = bigquery.Client()

    # Get pitchers
    logger.info("Fetching unique pitchers from BigQuery...")
    pitchers = get_unique_pitchers(client, args.limit)
    logger.info(f"Found {len(pitchers)} unique pitchers")

    # Process each pitcher
    mappings = []
    not_found = []

    for i, pitcher in enumerate(pitchers):
        player_lookup = pitcher['player_lookup']
        player_full_name = pitcher['player_full_name']
        team_abbr = pitcher.get('team_abbr', 'UNK')

        if (i + 1) % 50 == 0:
            logger.info(f"Processing pitcher {i+1}/{len(pitchers)}: {player_full_name}")

        # Search BDL API
        bdl_players = search_bdl_player(player_full_name, api_key)

        # Match to our pitcher
        match = match_pitcher(player_full_name, bdl_players, team_abbr)

        if match:
            mappings.append({
                'player_lookup': player_lookup,
                'player_full_name': player_full_name,
                'bdl_player_id': match['id'],
                'bdl_full_name': match.get('full_name', ''),
                'bdl_position': match.get('position', ''),
                'bdl_team_abbr': match.get('team', {}).get('abbreviation', ''),
            })
        else:
            not_found.append({
                'player_lookup': player_lookup,
                'player_full_name': player_full_name,
                'team_abbr': team_abbr,
            })

        # Rate limiting
        time.sleep(args.delay)

    # Report results
    logger.info(f"\n=== RESULTS ===")
    logger.info(f"Matched: {len(mappings)}/{len(pitchers)} ({100*len(mappings)/len(pitchers):.1f}%)")
    logger.info(f"Not found: {len(not_found)}")

    if not_found:
        logger.info(f"\nSample not found (first 20):")
        for nf in not_found[:20]:
            logger.info(f"  - {nf['player_full_name']} ({nf['player_lookup']})")

    # Update registry
    if mappings:
        updated = update_registry(client, mappings, args.dry_run)
        logger.info(f"Registry updates: {updated}")

    # Save results to JSON for reference (save ALL mappings)
    results = {
        'timestamp': datetime.now().isoformat(),
        'total_pitchers': len(pitchers),
        'matched': len(mappings),
        'not_found_count': len(not_found),
        'match_rate': 100 * len(mappings) / len(pitchers) if pitchers else 0,
        'mappings': mappings,  # All mappings
        'not_found': not_found,  # All not found
    }

    output_path = 'scripts/mlb/bdl_mapping_results.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    logger.info(f"Results saved to {output_path}")


if __name__ == '__main__':
    main()
