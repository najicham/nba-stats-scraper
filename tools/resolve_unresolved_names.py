#!/usr/bin/env python3
"""
File: tools/player_registry/resolve_unresolved_names.py

CLI tool for reviewing and resolving unresolved player names.

Usage:
    # Interactive mode (recommended)
    python -m tools.player_registry.resolve_unresolved_names
    
    # List pending names
    python -m tools.player_registry.resolve_unresolved_names list --status pending
    
    # Resolve specific player
    python -m tools.player_registry.resolve_unresolved_names resolve bronnyjames
"""

import argparse
import sys
import os
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
import pandas as pd
from google.cloud import bigquery
from tabulate import tabulate


class UnresolvedNameResolver:
    """Tool for resolving unresolved player names."""
    
    def __init__(self, project_id: str = None, test_mode: bool = False):
        self.bq_client = bigquery.Client()
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        if test_mode:
            self.unresolved_table = 'nba_reference.unresolved_player_names_test_FIXED2'
            self.alias_table = 'nba_reference.player_aliases_test_FIXED2'
            self.registry_table = 'nba_reference.nba_players_registry_test_FIXED2'
        else:
            self.unresolved_table = 'nba_reference.unresolved_player_names'
            self.alias_table = 'nba_reference.player_aliases'
            self.registry_table = 'nba_reference.nba_players_registry'
        
        self.reviewer = os.environ.get('USER', 'unknown')
    
    # =========================================================================
    # LIST & QUERY OPERATIONS
    # =========================================================================
    
    def list_unresolved(self, status: str = 'pending', source: str = None, 
                       min_occurrences: int = 1, limit: int = 50) -> pd.DataFrame:
        """List unresolved names with filters."""
        
        query = f"""
        SELECT 
            normalized_lookup,
            original_name,
            source,
            team_abbr,
            season,
            occurrences,
            first_seen_date,
            last_seen_date,
            status,
            notes
        FROM `{self.project_id}.{self.unresolved_table}`
        WHERE status = @status
          AND occurrences >= @min_occurrences
        """
        
        params = [
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("min_occurrences", "INT64", min_occurrences)
        ]
        
        if source:
            query += " AND source = @source"
            params.append(bigquery.ScalarQueryParameter("source", "STRING", source))
        
        query += """
        ORDER BY occurrences DESC, last_seen_date DESC
        LIMIT @limit
        """
        params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))
        
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        
        results = self.bq_client.query(query, job_config=job_config).to_dataframe()
        return results
    
    def get_unresolved_detail(self, normalized_lookup: str, team_abbr: str = None) -> Dict:
        """Get full details for an unresolved name."""
        
        query = f"""
        SELECT *
        FROM `{self.project_id}.{self.unresolved_table}`
        WHERE normalized_lookup = @lookup
        """
        
        params = [bigquery.ScalarQueryParameter("lookup", "STRING", normalized_lookup)]
        
        if team_abbr:
            query += " AND team_abbr = @team"
            params.append(bigquery.ScalarQueryParameter("team", "STRING", team_abbr))
        
        query += " LIMIT 1"
        
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        results = self.bq_client.query(query, job_config=job_config).to_dataframe()
        
        if results.empty:
            return None
        
        return results.iloc[0].to_dict()
    
    def search_registry(self, search_term: str, season: str = None) -> pd.DataFrame:
        """Search registry for potential matches."""
        
        query = f"""
        SELECT 
            player_lookup,
            player_name,
            team_abbr,
            season,
            games_played,
            jersey_number,
            position,
            source_priority
        FROM `{self.project_id}.{self.registry_table}`
        WHERE player_lookup LIKE @search_pattern
           OR LOWER(player_name) LIKE @search_pattern
        """
        
        params = [
            bigquery.ScalarQueryParameter("search_pattern", "STRING", f"%{search_term.lower()}%")
        ]
        
        if season:
            query += " AND season = @season"
            params.append(bigquery.ScalarQueryParameter("season", "STRING", season))
        
        query += " ORDER BY season DESC, games_played DESC LIMIT 20"
        
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        results = self.bq_client.query(query, job_config=job_config).to_dataframe()
        
        return results
    
    def check_existing_alias(self, alias_lookup: str) -> Optional[str]:
        """Check if alias already exists."""
        
        query = f"""
        SELECT nba_canonical_lookup, is_active
        FROM `{self.project_id}.{self.alias_table}`
        WHERE alias_lookup = @alias
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("alias", "STRING", alias_lookup)
        ])
        
        results = self.bq_client.query(query, job_config=job_config).to_dataframe()
        
        if results.empty:
            return None
        
        canonical = results.iloc[0]['nba_canonical_lookup']
        is_active = results.iloc[0]['is_active']
        
        return f"{canonical} ({'active' if is_active else 'inactive'})"
    
    # =========================================================================
    # RESOLUTION OPERATIONS
    # =========================================================================
    
    def resolve_as_alias(self, alias_lookup: str, canonical_lookup: str,
                        alias_display: str, canonical_display: str,
                        alias_type: str = 'manual_resolution',
                        notes: str = None) -> bool:
        """
        Resolve unresolved name by creating alias mapping.
        
        Args:
            alias_lookup: The unresolved normalized name
            canonical_lookup: The canonical normalized name to map to
            alias_display: Original display name (from unresolved)
            canonical_display: Canonical display name (from registry)
            alias_type: Type of alias (suffix_difference, nickname, typo, manual_resolution)
            notes: Additional notes
            
        Returns:
            True if successful
        """
        
        # Check if alias already exists
        existing = self.check_existing_alias(alias_lookup)
        if existing:
            print(f"⚠️  Alias already exists: {alias_lookup} → {existing}")
            return False
        
        # Check if canonical exists in registry
        registry_check = self.search_registry(canonical_lookup)
        if registry_check.empty:
            print(f"⚠️  Canonical name '{canonical_lookup}' not found in registry")
            print("   Create registry entry first or check spelling")
            return False
        
        # Create alias record
        alias_record = {
            'alias_lookup': alias_lookup,
            'nba_canonical_lookup': canonical_lookup,
            'alias_display': alias_display,
            'nba_canonical_display': canonical_display,
            'alias_type': alias_type,
            'alias_source': 'manual_resolution',
            'is_active': True,
            'notes': notes or f'Resolved by {self.reviewer}',
            'created_by': self.reviewer,
            'created_at': datetime.now(),
            'processed_at': datetime.now()
        }
        
        # Insert alias
        table_id = f"{self.project_id}.{self.alias_table}"
        errors = self.bq_client.insert_rows_json(table_id, [alias_record])
        
        if errors:
            print(f"❌ Failed to create alias: {errors}")
            return False
        
        # Mark unresolved as resolved
        self._mark_resolved(
            alias_lookup,
            resolution_type='create_alias',
            resolved_to_name=canonical_display
        )
        
        print(f"✅ Created alias: {alias_lookup} → {canonical_lookup}")
        return True
    
    def resolve_as_invalid(self, normalized_lookup: str, reason: str = None) -> bool:
        """Mark unresolved name as invalid (typo, data error, etc.)."""
        
        return self._update_unresolved_status(
            normalized_lookup,
            status='invalid',
            resolution_type='typo',
            notes=reason or f'Marked invalid by {self.reviewer}'
        )
    
    def resolve_as_ignored(self, normalized_lookup: str, reason: str = None) -> bool:
        """Mark unresolved name as ignored (minor variation, not worth aliasing)."""
        
        return self._update_unresolved_status(
            normalized_lookup,
            status='ignored',
            resolution_type=None,
            notes=reason or f'Ignored by {self.reviewer}'
        )
    
    def mark_under_review(self, normalized_lookup: str, notes: str = None) -> bool:
        """Mark unresolved name as under review."""
        
        return self._update_unresolved_status(
            normalized_lookup,
            status='under_review',
            notes=notes or f'Under review by {self.reviewer}'
        )
    
    def _mark_resolved(self, normalized_lookup: str, resolution_type: str, 
                      resolved_to_name: str) -> bool:
        """Mark unresolved name as resolved."""
        
        return self._update_unresolved_status(
            normalized_lookup,
            status='resolved',
            resolution_type=resolution_type,
            resolved_to_name=resolved_to_name
        )
    
    def _update_unresolved_status(self, normalized_lookup: str, status: str,
                                 resolution_type: str = None, 
                                 resolved_to_name: str = None,
                                 notes: str = None) -> bool:
        """Update unresolved name record status."""
        
        update_fields = [
            "status = @status",
            "reviewed_by = @reviewer",
            "reviewed_at = CURRENT_TIMESTAMP()",
            "processed_at = CURRENT_TIMESTAMP()"
        ]
        
        params = [
            bigquery.ScalarQueryParameter("lookup", "STRING", normalized_lookup),
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("reviewer", "STRING", self.reviewer)
        ]
        
        if resolution_type:
            update_fields.append("resolution_type = @resolution_type")
            params.append(bigquery.ScalarQueryParameter("resolution_type", "STRING", resolution_type))
        
        if resolved_to_name:
            update_fields.append("resolved_to_name = @resolved_name")
            params.append(bigquery.ScalarQueryParameter("resolved_name", "STRING", resolved_to_name))
        
        if notes:
            update_fields.append("notes = @notes")
            params.append(bigquery.ScalarQueryParameter("notes", "STRING", notes))
        
        query = f"""
        UPDATE `{self.project_id}.{self.unresolved_table}`
        SET {', '.join(update_fields)}
        WHERE normalized_lookup = @lookup
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        
        try:
            self.bq_client.query(query, job_config=job_config).result()
            return True
        except Exception as e:
            print(f"❌ Failed to update status: {e}")
            return False
    
    # =========================================================================
    # INTERACTIVE MODE
    # =========================================================================
    
    def interactive_resolve(self, limit: int = 10):
        """Interactive mode for resolving unresolved names."""
        
        print("\n" + "="*80)
        print("UNRESOLVED PLAYER NAMES - Interactive Resolution")
        print("="*80)
        
        # Get pending unresolved names
        pending = self.list_unresolved(status='pending', limit=limit)
        
        if pending.empty:
            print("\n✅ No pending unresolved names!")
            return
        
        print(f"\nFound {len(pending)} pending unresolved names (showing top {limit})")
        print(f"Reviewer: {self.reviewer}")
        print()
        
        # Display table
        display_df = pending[['normalized_lookup', 'original_name', 'source', 
                             'team_abbr', 'season', 'occurrences']]
        print(tabulate(display_df, headers='keys', tablefmt='simple', showindex=True))
        
        print("\n" + "-"*80)
        
        # Process each record
        for idx, row in pending.iterrows():
            print(f"\n[{idx+1}/{len(pending)}] {row['original_name']} ({row['normalized_lookup']})")
            print(f"    Source: {row['source']}")
            print(f"    Team: {row['team_abbr']} | Season: {row['season']}")
            print(f"    Occurrences: {row['occurrences']}")
            if pd.notna(row['notes']):
                print(f"    Notes: {row['notes']}")
            
            # Check if alias exists
            existing_alias = self.check_existing_alias(row['normalized_lookup'])
            if existing_alias:
                print(f"\n    ⚠️  Alias exists: {existing_alias}")
            
            # Search for similar names in registry
            print("\n    Searching registry for similar names...")
            similar = self.search_registry(row['normalized_lookup'], season=row['season'])
            
            if not similar.empty:
                print(f"    Found {len(similar)} potential matches:")
                for i, match in similar.head(5).iterrows():
                    print(f"      {i+1}. {match['player_name']} ({match['player_lookup']}) "
                          f"- {match['team_abbr']} - Games: {match['games_played']}")
            else:
                print("    No similar names found in registry")
            
            print("\n    Options:")
            print("      a - Create alias (map to existing player)")
            print("      i - Mark as invalid (typo/data error)")
            print("      g - Mark as ignored (not worth aliasing)")
            print("      r - Mark under review (need more research)")
            print("      s - Skip to next")
            print("      q - Quit")
            
            choice = input("\n    Choice: ").strip().lower()
            
            if choice == 'q':
                print("\n👋 Exiting...")
                break
            elif choice == 's':
                continue
            elif choice == 'a':
                self._interactive_create_alias(row)
            elif choice == 'i':
                reason = input("    Reason (optional): ").strip()
                if self.resolve_as_invalid(row['normalized_lookup'], reason):
                    print("    ✅ Marked as invalid")
            elif choice == 'g':
                reason = input("    Reason (optional): ").strip()
                if self.resolve_as_ignored(row['normalized_lookup'], reason):
                    print("    ✅ Marked as ignored")
            elif choice == 'r':
                notes = input("    Research notes (optional): ").strip()
                if self.mark_under_review(row['normalized_lookup'], notes):
                    print("    ✅ Marked under review")
            else:
                print("    ⚠️  Invalid choice, skipping...")
        
        print("\n" + "="*80)
        print("Session complete!")
        print("="*80 + "\n")
    
    def _interactive_create_alias(self, unresolved_row):
        """Interactive helper for creating alias."""
        
        print(f"\n    Creating alias for: {unresolved_row['original_name']}")
        
        # Get canonical name
        canonical_lookup = input("    Canonical player_lookup: ").strip().lower()
        
        if not canonical_lookup:
            print("    ⚠️  Cancelled")
            return
        
        # Verify canonical exists
        registry_match = self.search_registry(canonical_lookup)
        
        if registry_match.empty:
            print(f"    ⚠️  '{canonical_lookup}' not found in registry")
            return
        
        # Show matches and let user confirm
        print(f"\n    Found {len(registry_match)} matches:")
        for i, match in registry_match.head(5).iterrows():
            print(f"      {i+1}. {match['player_name']} ({match['player_lookup']}) "
                  f"- {match['team_abbr']} - Games: {match['games_played']}")
        
        confirm = input("\n    Use first match? (y/n): ").strip().lower()
        
        if confirm != 'y':
            print("    ⚠️  Cancelled")
            return
        
        canonical_display = registry_match.iloc[0]['player_name']
        
        # Get alias type
        print("\n    Alias types:")
        print("      1 - suffix_difference (e.g., Jr vs Jr.)")
        print("      2 - nickname (e.g., KJ vs Kenyon)")
        print("      3 - typo")
        print("      4 - source_variation")
        
        alias_type_choice = input("    Type (1-4): ").strip()
        
        alias_types = {
            '1': 'suffix_difference',
            '2': 'nickname',
            '3': 'typo',
            '4': 'source_variation'
        }
        
        alias_type = alias_types.get(alias_type_choice, 'manual_resolution')
        
        # Create alias
        success = self.resolve_as_alias(
            alias_lookup=unresolved_row['normalized_lookup'],
            canonical_lookup=canonical_lookup,
            alias_display=unresolved_row['original_name'],
            canonical_display=canonical_display,
            alias_type=alias_type
        )
        
        if not success:
            print("    ❌ Failed to create alias")


def main():
    parser = argparse.ArgumentParser(
        description="Resolve unresolved player names",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (recommended)
  python -m tools.player_registry.resolve_unresolved_names
  
  # List pending names
  python -m tools.player_registry.resolve_unresolved_names list --status pending
  
  # List by source
  python -m tools.player_registry.resolve_unresolved_names list --source espn
  
  # Search registry
  python -m tools.player_registry.resolve_unresolved_names search "lebron"
  
  # Get details on specific unresolved name
  python -m tools.player_registry.resolve_unresolved_names detail bronnyjames
  
  # Create alias manually
  python -m tools.player_registry.resolve_unresolved_names alias kjmartin kenyonmartinjr
        """
    )
    
    parser.add_argument('command', nargs='?', default='interactive',
                       choices=['interactive', 'list', 'search', 'detail', 'alias'],
                       help='Command to run')
    parser.add_argument('args', nargs='*', help='Command arguments')
    parser.add_argument('--status', default='pending', 
                       help='Status filter for list command')
    parser.add_argument('--source', help='Source filter for list command')
    parser.add_argument('--limit', type=int, default=50, 
                       help='Limit for list command')
    parser.add_argument('--test', action='store_true', 
                       help='Use test tables')
    
    args = parser.parse_args()
    
    resolver = UnresolvedNameResolver(test_mode=args.test)
    
    if args.command == 'interactive':
        resolver.interactive_resolve(limit=args.limit)
    
    elif args.command == 'list':
        results = resolver.list_unresolved(
            status=args.status,
            source=args.source,
            limit=args.limit
        )
        
        if results.empty:
            print(f"\nNo unresolved names with status '{args.status}'")
        else:
            print(f"\nFound {len(results)} unresolved names:\n")
            display_df = results[['normalized_lookup', 'original_name', 'source', 
                                 'team_abbr', 'season', 'occurrences']]
            print(tabulate(display_df, headers='keys', tablefmt='simple'))
    
    elif args.command == 'search':
        if not args.args:
            print("Error: search requires a search term")
            sys.exit(1)
        
        search_term = args.args[0]
        results = resolver.search_registry(search_term)
        
        if results.empty:
            print(f"\nNo registry matches for '{search_term}'")
        else:
            print(f"\nFound {len(results)} registry matches:\n")
            print(tabulate(results, headers='keys', tablefmt='simple'))
    
    elif args.command == 'detail':
        if not args.args:
            print("Error: detail requires normalized_lookup")
            sys.exit(1)
        
        detail = resolver.get_unresolved_detail(args.args[0])
        
        if not detail:
            print(f"\nNo unresolved record found for '{args.args[0]}'")
        else:
            print("\nUnresolved Name Details:")
            print("="*60)
            for key, value in detail.items():
                if pd.notna(value):
                    print(f"{key:25s}: {value}")
    
    elif args.command == 'alias':
        if len(args.args) < 2:
            print("Error: alias requires alias_lookup and canonical_lookup")
            sys.exit(1)
        
        alias_lookup = args.args[0]
        canonical_lookup = args.args[1]
        
        # Get unresolved details
        unresolved = resolver.get_unresolved_detail(alias_lookup)
        if not unresolved:
            print(f"Error: '{alias_lookup}' not found in unresolved names")
            sys.exit(1)
        
        # Get canonical details
        registry = resolver.search_registry(canonical_lookup)
        if registry.empty:
            print(f"Error: '{canonical_lookup}' not found in registry")
            sys.exit(1)
        
        # Create alias
        success = resolver.resolve_as_alias(
            alias_lookup=alias_lookup,
            canonical_lookup=canonical_lookup,
            alias_display=unresolved['original_name'],
            canonical_display=registry.iloc[0]['player_name'],
            alias_type='manual_resolution'
        )
        
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main()
