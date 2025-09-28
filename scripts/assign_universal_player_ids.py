#!/usr/bin/env python3
"""
File: scripts/assign_universal_player_ids.py

Universal Player ID Assignment Script

This script assigns universal_player_id to all existing records in the NBA players registry.
It handles name changes via the player aliases system to ensure one ID per real player.

Usage:
    python assign_universal_player_ids.py --mode=assign [--dry-run] [--backup-file=ids_backup.json]
    python assign_universal_player_ids.py --mode=restore --backup-file=ids_backup.json
"""

import json
import logging
import os
import argparse
from datetime import datetime
from typing import Dict, List, Set, Tuple
from collections import defaultdict
import pandas as pd
from google.cloud import bigquery

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class UniversalPlayerIDAssigner:
    """Assigns universal player IDs to the NBA players registry."""
    
    def __init__(self, project_id: str = None):
        self.bq_client = bigquery.Client()
        self.project_id = project_id or self.bq_client.project
        
        # Always use production tables
        self.registry_table = 'nba_reference.nba_players_registry'
        self.aliases_table = 'nba_reference.player_aliases'
        logger.info(f"Using registry table: {self.registry_table}")
    
    def get_all_registry_records(self) -> pd.DataFrame:
        """Get all current registry records."""
        query = f"""
        SELECT 
            player_lookup,
            player_name,
            team_abbr,
            season,
            universal_player_id
        FROM `{self.project_id}.{self.registry_table}`
        ORDER BY player_lookup, season, team_abbr
        """
        
        logger.info("Fetching all registry records...")
        results = self.bq_client.query(query).to_dataframe()
        logger.info(f"Retrieved {len(results)} registry records")
        return results
    
    def get_player_aliases(self) -> pd.DataFrame:
        """Get all active player aliases for name change resolution."""
        query = f"""
        SELECT 
            alias_lookup,
            nba_canonical_lookup,
            alias_display,
            nba_canonical_display,
            alias_type,
            alias_source
        FROM `{self.project_id}.{self.aliases_table}`
        WHERE is_active = TRUE
        ORDER BY alias_lookup
        """
        
        logger.info("Fetching player aliases for name change resolution...")
        try:
            results = self.bq_client.query(query).to_dataframe()
            logger.info(f"Retrieved {len(results)} active aliases")
            
            # Log some examples to verify name change detection
            name_changes = results[results['alias_lookup'] != results['nba_canonical_lookup']]
            if not name_changes.empty:
                logger.info(f"Found {len(name_changes)} name change aliases:")
                for _, row in name_changes.head(5).iterrows():
                    logger.info(f"  {row['alias_lookup']} → {row['nba_canonical_lookup']} ({row['alias_type']})")
                if len(name_changes) > 5:
                    logger.info(f"  ... and {len(name_changes) - 5} more")
            else:
                logger.info("No name change aliases found in aliases table")
            
            return results
        except Exception as e:
            logger.warning(f"Could not fetch aliases: {e}")
            logger.info("Proceeding without aliases (will use direct player_lookup)")
            return pd.DataFrame(columns=['alias_lookup', 'nba_canonical_lookup', 'alias_display', 'nba_canonical_display', 'alias_type', 'alias_source'])
    
    def build_canonical_mapping(self, aliases_df: pd.DataFrame) -> Dict[str, str]:
        """Build mapping from any player name to their canonical name."""
        canonical_map = {}
        name_change_count = 0
        
        # Add alias mappings
        for _, row in aliases_df.iterrows():
            alias_lookup = row['alias_lookup']
            canonical_lookup = row['nba_canonical_lookup']
            canonical_map[alias_lookup] = canonical_lookup
            
            # Track name changes specifically
            if alias_lookup != canonical_lookup:
                name_change_count += 1
                alias_type = row.get('alias_type', 'unknown')
                logger.info(f"NAME CHANGE: {alias_lookup} → {canonical_lookup} (type: {alias_type})")
            
            # Also ensure canonical names map to themselves
            canonical_map[canonical_lookup] = canonical_lookup
        
        logger.info(f"Built canonical mapping with {len(canonical_map)} entries")
        logger.info(f"Detected {name_change_count} name changes in aliases table")
        
        if name_change_count == 0:
            logger.warning("No name changes detected! Verify that player_aliases table contains name change records")
            logger.info("Expected entries like: kjmartin → kenyonmartinjr")
        
        return canonical_map
    
    def group_players_by_canonical_identity(self, registry_df: pd.DataFrame, canonical_map: Dict[str, str]) -> Dict[str, List[Dict]]:
        """Group all registry records by canonical player identity."""
        canonical_groups = defaultdict(list)
        
        for _, row in registry_df.iterrows():
            player_lookup = row['player_lookup']
            
            # Resolve to canonical name (or use original if no alias)
            canonical_name = canonical_map.get(player_lookup, player_lookup)
            
            # Add this record to the canonical player's group
            record = {
                'player_lookup': player_lookup,
                'player_name': row['player_name'],
                'team_abbr': row['team_abbr'],
                'season': row['season'],
                'current_universal_id': row.get('universal_player_id')
            }
            canonical_groups[canonical_name].append(record)
        
        logger.info(f"Grouped {len(registry_df)} records into {len(canonical_groups)} canonical players")
        
        # Log examples for verification
        for canonical_name, records in list(canonical_groups.items())[:5]:
            player_lookups = list(set(r['player_lookup'] for r in records))
            logger.info(f"  {canonical_name}: {len(records)} records across names {player_lookups}")
        
        return dict(canonical_groups)
    
    def assign_universal_ids(self, canonical_groups: Dict[str, List[Dict]]) -> Tuple[Dict[str, str], Dict]:
        """Assign universal IDs to each canonical player."""
        id_assignments = {}  # (player_lookup, team_abbr, season) -> universal_player_id
        backup_data = {}     # For JSON backup
        uid_counter = defaultdict(int)
        
        for canonical_name, records in canonical_groups.items():
            # Check if any records already have a universal ID
            existing_ids = [r['current_universal_id'] for r in records if r['current_universal_id']]
            
            if existing_ids:
                # Use existing ID (take the first non-null one)
                universal_id = existing_ids[0]
                logger.info(f"Using existing ID for {canonical_name}: {universal_id}")
                
                # Warn if there are multiple different existing IDs (shouldn't happen)
                unique_existing = list(set(existing_ids))
                if len(unique_existing) > 1:
                    logger.warning(f"Multiple existing IDs for {canonical_name}: {unique_existing} - using {universal_id}")
            else:
                # Generate new ID
                uid_counter[canonical_name] += 1
                universal_id = f"{canonical_name}_{uid_counter[canonical_name]:03d}"
                logger.info(f"Generated new ID for {canonical_name}: {universal_id}")
            
            # Assign this ID to all records for this canonical player
            for record in records:
                key = (record['player_lookup'], record['team_abbr'], record['season'])
                id_assignments[key] = universal_id
            
            # Build backup data
            backup_data[universal_id] = {
                'canonical_name': canonical_name,
                'player_lookups': list(set(r['player_lookup'] for r in records)),
                'sample_display_name': records[0]['player_name'],
                'seasons': sorted(list(set(r['season'] for r in records))),
                'teams': sorted(list(set(r['team_abbr'] for r in records))),
                'total_records': len(records)
            }
        
        logger.info(f"Assigned {len(set(id_assignments.values()))} universal IDs to {len(id_assignments)} records")
        return id_assignments, backup_data
    
    def save_backup(self, backup_data: Dict, backup_file: str):
        """Save ID assignments to JSON backup file."""
        backup_info = {
            'created_at': datetime.now().isoformat(),
            'total_players': len(backup_data),
            'total_records': sum(data['total_records'] for data in backup_data.values()),
            'assignments': backup_data
        }
        
        with open(backup_file, 'w') as f:
            json.dump(backup_info, f, indent=2)
        
        logger.info(f"Saved backup to {backup_file}")
        logger.info(f"Backup contains {backup_info['total_players']} players covering {backup_info['total_records']} records")
    
    def update_registry_with_ids(self, id_assignments: Dict, dry_run: bool = False) -> Dict:
        """Update the registry with universal player IDs."""
        if dry_run:
            logger.info("DRY RUN: Would update registry with universal IDs")
            return {'updated_records': len(id_assignments), 'dry_run': True}
        
        logger.info(f"Updating {len(id_assignments)} registry records with universal IDs...")
        
        # Build update cases for SQL
        update_cases = []
        for (player_lookup, team_abbr, season), universal_id in id_assignments.items():
            update_cases.append(f"WHEN player_lookup = '{player_lookup}' AND team_abbr = '{team_abbr}' AND season = '{season}' THEN '{universal_id}'")
        
        # Execute batch update
        update_query = f"""
        UPDATE `{self.project_id}.{self.registry_table}`
        SET universal_player_id = CASE 
            {chr(10).join(update_cases)}
        END,
        processed_at = CURRENT_TIMESTAMP()
        WHERE (player_lookup, team_abbr, season) IN (
            {', '.join(f"('{lookup}', '{team}', '{season}')" for (lookup, team, season), _ in id_assignments.items())}
        )
        """
        
        update_job = self.bq_client.query(update_query)
        result = update_job.result()
        
        updated_rows = update_job.num_dml_affected_rows or 0
        logger.info(f"Updated {updated_rows} registry records with universal IDs")
        
        return {'updated_records': updated_rows, 'dry_run': False}
    
    def verify_assignments(self) -> Dict:
        """Verify the universal ID assignments."""
        logger.info("Verifying universal ID assignments...")
        
        query = f"""
        SELECT 
            universal_player_id,
            COUNT(*) as record_count,
            COUNT(DISTINCT player_lookup) as unique_lookups,
            COUNT(DISTINCT season) as seasons_covered,
            STRING_AGG(DISTINCT player_lookup, ', ' ORDER BY player_lookup) as player_lookups,
            STRING_AGG(DISTINCT player_name, ', ' ORDER BY player_name) as player_names
        FROM `{self.project_id}.{self.registry_table}`
        WHERE universal_player_id IS NOT NULL
        GROUP BY universal_player_id
        HAVING COUNT(DISTINCT player_lookup) > 1  -- Show cases where ID spans multiple lookups
        ORDER BY record_count DESC
        LIMIT 10
        """
        
        results = self.bq_client.query(query).to_dataframe()
        
        logger.info("Verification complete:")
        logger.info(f"Found {len(results)} players with multiple player_lookups (name changes)")
        
        for _, row in results.iterrows():
            logger.info(f"  {row['universal_player_id']}: {row['unique_lookups']} names, {row['record_count']} records")
            logger.info(f"    Names: {row['player_lookups']}")
        
        # Overall statistics
        stats_query = f"""
        SELECT 
            COUNT(*) as total_records,
            COUNT(DISTINCT universal_player_id) as unique_players,
            COUNT(DISTINCT player_lookup) as unique_lookups,
            COUNT(CASE WHEN universal_player_id IS NULL THEN 1 END) as missing_ids
        FROM `{self.project_id}.{self.registry_table}`
        """
        
        stats = self.bq_client.query(stats_query).to_dataframe().iloc[0]
        
        verification_result = {
            'total_records': int(stats['total_records']),
            'unique_players': int(stats['unique_players']),
            'unique_lookups': int(stats['unique_lookups']),
            'missing_ids': int(stats['missing_ids']),
            'name_change_cases': len(results)
        }
        
        logger.info(f"Registry statistics:")
        logger.info(f"  Total records: {verification_result['total_records']}")
        logger.info(f"  Unique players: {verification_result['unique_players']}")
        logger.info(f"  Unique lookups: {verification_result['unique_lookups']}")
        logger.info(f"  Missing IDs: {verification_result['missing_ids']}")
        logger.info(f"  Name change cases: {verification_result['name_change_cases']}")
        
        return verification_result
    
    def run_assignment(self, dry_run: bool = False, backup_file: str = None, output_file: str = None) -> Dict:
        """Run the complete universal ID assignment process."""
        logger.info("Starting universal player ID assignment...")
        
        # Step 1: Get data
        registry_df = self.get_all_registry_records()
        aliases_df = self.get_player_aliases()
        
        # Step 2: Build canonical mapping
        canonical_map = self.build_canonical_mapping(aliases_df)
        
        # Step 3: Group players by canonical identity
        canonical_groups = self.group_players_by_canonical_identity(registry_df, canonical_map)
        
        # Step 4: Assign universal IDs
        id_assignments, backup_data = self.assign_universal_ids(canonical_groups)
        
        # Step 5: Handle output modes
        if output_file:
            # JSON output mode - save assignments to file instead of updating DB
            logger.info(f"JSON OUTPUT MODE: Saving assignments to {output_file}")
            self.save_assignments_to_json(id_assignments, backup_data, canonical_groups, output_file)
            
            return {
                'mode': 'json_output',
                'canonical_players_found': len(canonical_groups),
                'id_assignments_created': len(id_assignments),
                'output_file': output_file,
                'summary': {
                    'total_records': len(id_assignments),
                    'unique_players': len(set(id_assignments.values())),
                    'name_changes_detected': len([g for g in canonical_groups.values() if len(set(r['player_lookup'] for r in g)) > 1])
                }
            }
        else:
            # Database update mode
            # Step 5: Save backup
            if backup_file:
                self.save_backup(backup_data, backup_file)
            
            # Step 6: Update registry
            update_result = self.update_registry_with_ids(id_assignments, dry_run=dry_run)
            
            # Step 7: Verify (only if not dry run)
            verification_result = {}
            if not dry_run:
                verification_result = self.verify_assignments()
            
            return {
                'mode': 'database_update',
                'canonical_players_found': len(canonical_groups),
                'id_assignments_created': len(id_assignments),
                'update_result': update_result,
                'verification': verification_result,
                'backup_file': backup_file
            }

    def save_assignments_to_json(self, id_assignments: Dict, backup_data: Dict, canonical_groups: Dict, output_file: str):
        """Save ID assignments to JSON file for review."""
        # Build detailed output for analysis
        output_data = {
            'metadata': {
                'created_at': datetime.now().isoformat(),
                'total_records': len(id_assignments),
                'unique_players': len(backup_data),
                'table_name': self.registry_table
            },
            'summary': {
                'name_changes_detected': len([g for g in canonical_groups.values() if len(set(r['player_lookup'] for r in g)) > 1]),
                'new_ids_to_create': len([data for data in backup_data.values() if len(data['player_lookups']) > 0])
            },
            'player_details': {},
            'assignments_by_record': {}
        }
        
        # Add detailed player information
        for universal_id, player_data in backup_data.items():
            output_data['player_details'][universal_id] = {
                'canonical_name': player_data['canonical_name'],
                'all_player_lookups': player_data['player_lookups'],
                'sample_display_name': player_data['sample_display_name'],
                'seasons': player_data['seasons'],
                'teams': player_data['teams'],
                'total_records': player_data['total_records'],
                'has_name_changes': len(player_data['player_lookups']) > 1
            }
        
        # Add record-level assignments for verification
        for (player_lookup, team_abbr, season), universal_id in id_assignments.items():
            key = f"{player_lookup}|{team_abbr}|{season}"
            output_data['assignments_by_record'][key] = {
                'player_lookup': player_lookup,
                'team_abbr': team_abbr,
                'season': season,
                'universal_player_id': universal_id
            }
        
        # Save to file
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        logger.info(f"Saved detailed assignments to {output_file}")
        logger.info(f"File contains {len(backup_data)} unique players across {len(id_assignments)} records")
        
        # Log name change examples
        name_change_players = [data for data in backup_data.values() if len(data['player_lookups']) > 1]
        if name_change_players:
            logger.info(f"Name change examples found:")
            for player_data in name_change_players[:3]:
                logger.info(f"  {player_data['canonical_name']}: {' + '.join(player_data['player_lookups'])}")
        else:
            logger.warning("No name changes detected in output - verify aliases table is populated")


def main():
    parser = argparse.ArgumentParser(description='Assign universal player IDs to NBA registry')
    parser.add_argument('--mode', choices=['assign', 'restore'], required=True,
                       help='Assignment mode: assign new IDs or restore from backup')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    parser.add_argument('--backup-file', default=f'player_ids_backup_{datetime.now().strftime("%Y%m%d_%H%M")}.json',
                       help='Backup file path')
    parser.add_argument('--output-file', 
                       help='Save assignments to JSON file instead of updating database (for testing)')
    parser.add_argument('--project-id', help='GCP project ID (defaults to client default)')
    
    args = parser.parse_args()
    
    # Validate argument combinations
    if args.output_file and not args.mode == 'assign':
        parser.error("--output-file can only be used with --mode=assign")
    
    if args.output_file and not args.dry_run:
        logger.info("--output-file specified: automatically enabling dry-run mode for database operations")
    
    # Initialize assigner
    assigner = UniversalPlayerIDAssigner(project_id=args.project_id)
    
    if args.mode == 'assign':
        # Run ID assignment
        logger.info("=" * 60)
        logger.info("UNIVERSAL PLAYER ID ASSIGNMENT")
        if args.output_file:
            logger.info("Mode: JSON OUTPUT (testing mode)")
            logger.info(f"Output file: {args.output_file}")
        else:
            logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE UPDATE'}")
            logger.info(f"Backup file: {args.backup_file}")
        logger.info("=" * 60)
        
        result = assigner.run_assignment(
            dry_run=args.dry_run or bool(args.output_file),  # Force dry-run for JSON output
            backup_file=args.backup_file if not args.output_file else None,
            output_file=args.output_file
        )
        
        logger.info("=" * 60)
        logger.info("ASSIGNMENT COMPLETE")
        logger.info(f"Mode: {result['mode']}")
        logger.info(f"Canonical players: {result['canonical_players_found']}")
        logger.info(f"ID assignments: {result['id_assignments_created']}")
        
        if result['mode'] == 'json_output':
            logger.info(f"Output saved to: {result['output_file']}")
            logger.info(f"Name changes detected: {result['summary']['name_changes_detected']}")
            logger.info("Review the JSON file before running database update")
        else:
            logger.info(f"Records updated: {result['update_result']['updated_records']}")
            if result['verification']:
                logger.info(f"Unique players: {result['verification']['unique_players']}")
                logger.info(f"Name changes: {result['verification']['name_change_cases']}")
        logger.info("=" * 60)
        
    elif args.mode == 'restore':
        logger.error("Restore mode not yet implemented")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
    