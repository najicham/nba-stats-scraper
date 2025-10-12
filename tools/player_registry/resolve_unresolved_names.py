#!/usr/bin/env python3
"""
File: tools/player_registry/resolve_unresolved_names.py

CLI tool for reviewing and resolving unresolved player names.

Usage:
    # Interactive mode (recommended)
    python -m tools.player_registry.resolve_unresolved_names
    
    # List pending names
    python -m tools.player_registry.resolve_unresolved_names list
    
    # Search registry
    python -m tools.player_registry.resolve_unresolved_names search "lebron"
    
    # Show statistics
    python -m tools.player_registry.resolve_unresolved_names stats

Shell alias (add to .bashrc/.zshrc):
    alias resolve='python -m tools.player_registry.resolve_unresolved_names'
"""

import argparse
import sys
import os
import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import pandas as pd
from google.cloud import bigquery

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Try to import universal player ID resolver, use fallback if not available
try:
    from shared.utils.universal_player_id_resolver import resolve_or_create_universal_id
    HAS_RESOLVER = True
except ImportError:
    HAS_RESOLVER = False
    def resolve_or_create_universal_id(player_lookup: str) -> str:
        """Fallback function if resolver not available."""
        return f"{player_lookup}_001"

logger = logging.getLogger(__name__)


class ActionLogger:
    """Logs resolution actions to both local file and BigQuery."""
    
    def __init__(self, project_id: str, local_log_path: str = None):
        self.project_id = project_id
        
        # Default to /tmp if no path specified
        if local_log_path is None:
            local_log_path = "/tmp/unresolved_resolutions.log"
        
        self.local_log_path = Path(local_log_path)
        self.bq_client = bigquery.Client(project=project_id)
        self.log_table = f"{project_id}.nba_reference.unresolved_resolution_log"
        
        # Ensure local log directory exists
        self.local_log_path.parent.mkdir(parents=True, exist_ok=True)
        
    def log_action(self, action: str, normalized_lookup: str, original_name: str,
                   team_abbr: str, season: str, resolution_details: Dict,
                   reviewed_by: str, notes: str = None):
        """Log action to both local file and BigQuery."""
        
        timestamp = datetime.now()
        
        # Local log - simple pipe-delimited format
        details_str = json.dumps(resolution_details, separators=(',', ':'))
        local_entry = (
            f"{timestamp.isoformat()} | {action} | {normalized_lookup} | {original_name} | "
            f"{team_abbr} | {season} | {details_str} | {reviewed_by}\n"
        )
        
        try:
            with open(self.local_log_path, 'a') as f:
                f.write(local_entry)
        except Exception as e:
            logger.warning(f"Failed to write local log: {e}")
        
        # Cloud log - structured BigQuery record
        cloud_record = {
            'timestamp': timestamp,
            'action': action,
            'normalized_lookup': normalized_lookup,
            'original_name': original_name,
            'resolution_details': json.dumps(resolution_details),
            'team_abbr': team_abbr,
            'season': season,
            'reviewed_by': reviewed_by,
            'notes': notes
        }
        
        try:
            errors = self.bq_client.insert_rows_json(self.log_table, [cloud_record])
            if errors:
                logger.warning(f"Failed to write cloud log: {errors}")
        except Exception as e:
            logger.warning(f"Failed to write cloud log: {e}")


class UnresolvedNameResolver:
    """Tool for resolving unresolved player names."""
    
    def __init__(self, project_id: str = None, test_mode: bool = False):
        self.bq_client = bigquery.Client()
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        if test_mode:
            self.unresolved_table = 'nba_reference.unresolved_player_names_test'
            self.alias_table = 'nba_reference.player_aliases_test'
            self.registry_table = 'nba_reference.nba_players_registry_test'
        else:
            self.unresolved_table = 'nba_reference.unresolved_player_names'
            self.alias_table = 'nba_reference.player_aliases'
            self.registry_table = 'nba_reference.nba_players_registry'
        
        self.reviewer = os.environ.get('USER', 'unknown')
        self.action_logger = ActionLogger(self.project_id)
        
        # Warn if resolver not available
        if not HAS_RESOLVER and not test_mode:
            logger.warning("Universal player ID resolver not found - using fallback pattern {player_lookup}_001")
        
    # =========================================================================
    # QUERY OPERATIONS
    # =========================================================================
    
    def list_pending_unresolved(self, limit: int = 100, source: str = None,
                                min_occurrences: int = 1) -> pd.DataFrame:
        """List pending unresolved names, excluding snoozed until their date."""
        
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
            snooze_until,
            notes
        FROM `{self.project_id}.{self.unresolved_table}`
        WHERE (status = 'pending' 
               OR (status = 'snoozed' AND (snooze_until IS NULL OR snooze_until <= CURRENT_DATE())))
          AND occurrences >= @min_occurrences
        """
        
        params = [
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
    
    def search_registry(self, search_term: str, season: str = None, 
                       team_abbr: str = None) -> pd.DataFrame:
        """Search registry for similar names."""
        
        search_pattern = f"%{search_term.lower()}%"
        
        query = f"""
        SELECT 
            player_lookup,
            player_name,
            team_abbr,
            season,
            games_played,
            jersey_number,
            position,
            universal_player_id
        FROM `{self.project_id}.{self.registry_table}`
        WHERE LOWER(player_lookup) LIKE @search_pattern
           OR LOWER(player_name) LIKE @search_pattern
        """
        
        params = [
            bigquery.ScalarQueryParameter("search_pattern", "STRING", search_pattern)
        ]
        
        if season:
            query += " AND season = @season"
            params.append(bigquery.ScalarQueryParameter("season", "STRING", season))
        
        if team_abbr:
            query += " AND team_abbr = @team"
            params.append(bigquery.ScalarQueryParameter("team", "STRING", team_abbr))
        
        query += " ORDER BY season DESC, games_played DESC LIMIT 20"
        
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        results = self.bq_client.query(query, job_config=job_config).to_dataframe()
        
        return results
    
    def get_team_roster(self, team_abbr: str, season: str) -> pd.DataFrame:
        """Get team roster for context."""
        
        query = f"""
        SELECT 
            player_name,
            player_lookup,
            jersey_number,
            position,
            games_played
        FROM `{self.project_id}.{self.registry_table}`
        WHERE team_abbr = @team
          AND season = @season
        ORDER BY player_name
        LIMIT 50
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("team", "STRING", team_abbr),
            bigquery.ScalarQueryParameter("season", "STRING", season)
        ])
        
        results = self.bq_client.query(query, job_config=job_config).to_dataframe()
        return results
    
    def get_existing_aliases(self, base_name: str) -> pd.DataFrame:
        """Get existing aliases for similar names."""
        
        search_pattern = f"%{base_name[:6]}%"
        
        query = f"""
        SELECT 
            alias_lookup,
            nba_canonical_lookup,
            alias_display,
            nba_canonical_display,
            alias_type,
            is_active
        FROM `{self.project_id}.{self.alias_table}`
        WHERE LOWER(alias_lookup) LIKE @search_pattern
           OR LOWER(nba_canonical_lookup) LIKE @search_pattern
        LIMIT 20
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("search_pattern", "STRING", search_pattern)
        ])
        
        results = self.bq_client.query(query, job_config=job_config).to_dataframe()
        return results
    
    def check_existing_alias(self, alias_lookup: str) -> Optional[Dict]:
        """Check if alias already exists."""
        
        query = f"""
        SELECT 
            nba_canonical_lookup,
            nba_canonical_display,
            is_active
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
        
        return results.iloc[0].to_dict()
    
    # =========================================================================
    # RESOLUTION OPERATIONS
    # =========================================================================
    
    def create_alias(self, alias_lookup: str, canonical_lookup: str,
                    alias_display: str, canonical_display: str,
                    alias_type: str = 'manual_resolution',
                    notes: str = None) -> bool:
        """Create alias mapping."""
        
        # Validation: Check if alias already exists
        existing = self.check_existing_alias(alias_lookup)
        if existing:
            print(f"\nWarning: Alias already exists")
            print(f"  {alias_lookup} -> {existing['nba_canonical_lookup']} "
                  f"({'active' if existing['is_active'] else 'inactive'})")
            return False
        
        # Validation: Check canonical exists in registry
        canonical_check = self.search_registry(canonical_lookup)
        if canonical_check.empty:
            print(f"\nError: Canonical name '{canonical_lookup}' not found in registry")
            print("  Create registry entry first or verify spelling")
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
            'notes': notes or f'Created by {self.reviewer}',
            'created_by': self.reviewer,
            'created_at': datetime.now(),
            'processed_at': datetime.now()
        }
        
        # Insert alias
        table_id = f"{self.project_id}.{self.alias_table}"
        errors = self.bq_client.insert_rows_json(table_id, [alias_record])
        
        if errors:
            print(f"\nError creating alias: {errors}")
            return False
        
        return True
    
    def create_registry_entry(self, player_name: str, player_lookup: str,
                            team_abbr: str, season: str,
                            jersey_number: int = None, position: str = None) -> bool:
        """Create new registry entry for player."""
        
        # Validation: Check if already exists
        existing = self.search_registry(player_lookup, season=season, team_abbr=team_abbr)
        if not existing.empty:
            print(f"\nWarning: Player already exists in registry")
            print(f"  {existing.iloc[0]['player_name']} - {team_abbr} {season}")
            confirm = input("  Create anyway? (y/n): ").strip().lower()
            if confirm != 'y':
                return False
        
        # Get universal player ID
        try:
            universal_player_id = resolve_or_create_universal_id(player_lookup)
            if not HAS_RESOLVER:
                print(f"  Note: Using fallback ID pattern (resolver not available)")
        except Exception as e:
            print(f"\nError resolving universal ID: {e}")
            universal_player_id = f"{player_lookup}_001"
            print(f"  Using fallback: {universal_player_id}")
        
        # Create registry record (roster-only player, no games yet)
        registry_record = {
            'universal_player_id': universal_player_id,
            'player_name': player_name,
            'player_lookup': player_lookup,
            'team_abbr': team_abbr,
            'season': season,
            
            # No game data yet
            'first_game_date': None,
            'last_game_date': None,
            'games_played': 0,
            'total_appearances': 0,
            'inactive_appearances': 0,
            'dnp_appearances': 0,
            
            # Roster info
            'jersey_number': jersey_number,
            'position': position,
            
            # Source tracking
            'source_priority': 'manual_cli',
            'confidence_score': 0.5,  # Low confidence for manual entries
            'last_processor': 'cli',
            'last_roster_update': datetime.now(),
            'last_roster_activity_date': date.today(),
            'roster_update_count': 1,
            
            # Metadata
            'created_by': f'cli_{self.reviewer}',
            'created_at': datetime.now(),
            'processed_at': datetime.now()
        }
        
        # Insert registry record
        table_id = f"{self.project_id}.{self.registry_table}"
        errors = self.bq_client.insert_rows_json(table_id, [registry_record])
        
        if errors:
            print(f"\nError creating registry entry: {errors}")
            return False
        
        return True
    
    def mark_as_resolved(self, normalized_lookup: str, team_abbr: str,
                        resolution_type: str, resolved_to_name: str = None) -> bool:
        """Mark unresolved name as resolved."""
        
        update_query = f"""
        UPDATE `{self.project_id}.{self.unresolved_table}`
        SET 
            status = 'resolved',
            resolution_type = @resolution_type,
            resolved_to_name = @resolved_name,
            reviewed_by = @reviewer,
            reviewed_at = CURRENT_TIMESTAMP(),
            processed_at = CURRENT_TIMESTAMP()
        WHERE normalized_lookup = @lookup
          AND team_abbr = @team
          AND status IN ('pending', 'snoozed')
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("lookup", "STRING", normalized_lookup),
            bigquery.ScalarQueryParameter("team", "STRING", team_abbr),
            bigquery.ScalarQueryParameter("resolution_type", "STRING", resolution_type),
            bigquery.ScalarQueryParameter("resolved_name", "STRING", resolved_to_name or ''),
            bigquery.ScalarQueryParameter("reviewer", "STRING", self.reviewer)
        ])
        
        try:
            self.bq_client.query(update_query, job_config=job_config).result()
            return True
        except Exception as e:
            print(f"\nError marking as resolved: {e}")
            return False
    
    def mark_as_invalid(self, normalized_lookup: str, team_abbr: str,
                       reason: str = None) -> bool:
        """Mark unresolved name as invalid."""
        
        return self._update_status(
            normalized_lookup, team_abbr,
            status='invalid',
            resolution_type='typo',
            notes=reason or f'Invalid entry (typo/error) - {self.reviewer}'
        )
    
    def mark_as_ignored(self, normalized_lookup: str, team_abbr: str,
                       reason: str = None) -> bool:
        """Mark unresolved name as ignored."""
        
        return self._update_status(
            normalized_lookup, team_abbr,
            status='ignored',
            notes=reason or f'Ignored (too minor) - {self.reviewer}'
        )
    
    def mark_under_review(self, normalized_lookup: str, team_abbr: str,
                         notes: str = None) -> bool:
        """Mark unresolved name as under review."""
        
        return self._update_status(
            normalized_lookup, team_abbr,
            status='under_review',
            notes=notes or f'Needs more research - {self.reviewer}'
        )
    
    def snooze(self, normalized_lookup: str, team_abbr: str,
              days: int = 7, notes: str = None) -> bool:
        """Snooze unresolved name for specified days."""
        
        snooze_until = date.today() + timedelta(days=days)
        
        update_query = f"""
        UPDATE `{self.project_id}.{self.unresolved_table}`
        SET 
            status = 'snoozed',
            snooze_until = @snooze_date,
            notes = @notes,
            reviewed_by = @reviewer,
            reviewed_at = CURRENT_TIMESTAMP(),
            processed_at = CURRENT_TIMESTAMP()
        WHERE normalized_lookup = @lookup
          AND team_abbr = @team
          AND status = 'pending'
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("lookup", "STRING", normalized_lookup),
            bigquery.ScalarQueryParameter("team", "STRING", team_abbr),
            bigquery.ScalarQueryParameter("snooze_date", "DATE", snooze_until),
            bigquery.ScalarQueryParameter("notes", "STRING", 
                notes or f'Snoozed until {snooze_until} by {self.reviewer}'),
            bigquery.ScalarQueryParameter("reviewer", "STRING", self.reviewer)
        ])
        
        try:
            self.bq_client.query(update_query, job_config=job_config).result()
            return True
        except Exception as e:
            print(f"\nError snoozing: {e}")
            return False
    
    def _update_status(self, normalized_lookup: str, team_abbr: str,
                      status: str, resolution_type: str = None,
                      notes: str = None) -> bool:
        """Update unresolved name status."""
        
        update_parts = [
            "status = @status",
            "reviewed_by = @reviewer",
            "reviewed_at = CURRENT_TIMESTAMP()",
            "processed_at = CURRENT_TIMESTAMP()"
        ]
        
        params = [
            bigquery.ScalarQueryParameter("lookup", "STRING", normalized_lookup),
            bigquery.ScalarQueryParameter("team", "STRING", team_abbr),
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("reviewer", "STRING", self.reviewer)
        ]
        
        if resolution_type:
            update_parts.append("resolution_type = @resolution_type")
            params.append(bigquery.ScalarQueryParameter("resolution_type", "STRING", resolution_type))
        
        if notes:
            update_parts.append("notes = @notes")
            params.append(bigquery.ScalarQueryParameter("notes", "STRING", notes))
        
        update_query = f"""
        UPDATE `{self.project_id}.{self.unresolved_table}`
        SET {', '.join(update_parts)}
        WHERE normalized_lookup = @lookup
          AND team_abbr = @team
          AND status IN ('pending', 'snoozed')
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        
        try:
            self.bq_client.query(update_query, job_config=job_config).result()
            return True
        except Exception as e:
            print(f"\nError updating status: {e}")
            return False
    
    # =========================================================================
    # INTERACTIVE MODE
    # =========================================================================
    
    def interactive_resolve(self, limit: int = 100):
        """Interactive mode for resolving unresolved names."""
        
        print("\n" + "="*80)
        print("UNRESOLVED PLAYER NAMES - Interactive Resolution")
        print("="*80)
        
        pending = self.list_pending_unresolved(limit=limit)
        
        if pending.empty:
            print("\nNo pending unresolved names!")
            return
        
        print(f"\nFound {len(pending)} pending names")
        print(f"Reviewer: {self.reviewer}")
        print(f"Session started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Logs: /tmp/unresolved_resolutions.log")
        
        actions_taken = []
        
        for idx, row in pending.iterrows():
            print("\n" + "="*80)
            print(f"[{idx+1}/{len(pending)}] {row['original_name']} ({row['normalized_lookup']})")
            print(f"    Source: {row['source']} | Team: {row['team_abbr']} | Season: {row['season']}")
            print(f"    Occurrences: {row['occurrences']}")
            
            if pd.notna(row['notes']):
                print(f"    Notes: {row['notes']}")
            
            # Show context
            print("\n    Context:")
            
            # 1. Similar names in registry
            similar = self.search_registry(row['normalized_lookup'][:8], season=row['season'])
            if not similar.empty:
                print(f"    1. Similar names in registry ({len(similar)} found):")
                for i, match in similar.head(5).iterrows():
                    jersey = f"#{match['jersey_number']}" if pd.notna(match['jersey_number']) else ""
                    pos = f"({match['position']})" if pd.notna(match['position']) else ""
                    print(f"       - {match['player_name']} ({match['player_lookup']}) "
                          f"- {match['team_abbr']} {match['season']} - {match['games_played']} games "
                          f"{jersey} {pos}")
            else:
                print("    1. No similar names found in registry")
            
            # 2. Team roster
            roster = self.get_team_roster(row['team_abbr'], row['season'])
            if not roster.empty:
                print(f"\n    2. Current {row['team_abbr']} roster ({row['season']}):")
                for i, player in roster.head(10).iterrows():
                    jersey = f"#{player['jersey_number']}" if pd.notna(player['jersey_number']) else ""
                    pos = f"({player['position']})" if pd.notna(player['position']) else ""
                    print(f"       - {player['player_name']} {jersey} {pos}")
                if len(roster) > 10:
                    print(f"       ... and {len(roster) - 10} more players")
            
            # 3. Existing aliases
            aliases = self.get_existing_aliases(row['normalized_lookup'][:8])
            if not aliases.empty:
                print(f"\n    3. Existing aliases for similar names ({len(aliases)} found):")
                for i, alias in aliases.head(5).iterrows():
                    status = "active" if alias['is_active'] else "inactive"
                    print(f"       - {alias['alias_display']} -> {alias['nba_canonical_display']} "
                          f"({alias['alias_type']}, {status})")
            else:
                print("\n    3. No existing aliases for similar names")
            
            # Action prompt
            print("\n    Actions:")
            print("      [a]lias   - Create alias to existing player")
            print("      [n]ew     - Create new registry entry")
            print("      [i]nvalid - Mark as invalid (typo/error)")
            print("      [g]ignore - Mark as ignored (too minor)")
            print("      [r]eview  - Mark under review (needs research)")
            print("      [z]snooze - Snooze for 7 days")
            print("      [s]kip    - Skip to next")
            print("      [q]uit    - Exit session")
            
            choice = input("\n    Choice: ").strip().lower()
            
            if choice == 'q':
                print("\nExiting session...")
                break
            
            elif choice == 's':
                continue
            
            elif choice == 'a':
                if self._handle_create_alias(row):
                    actions_taken.append(('alias', row['original_name']))
            
            elif choice == 'n':
                if self._handle_create_new_player(row):
                    actions_taken.append(('new_player', row['original_name']))
            
            elif choice == 'i':
                reason = input("    Reason (optional): ").strip()
                if self.mark_as_invalid(row['normalized_lookup'], row['team_abbr'], reason):
                    print("    Marked as invalid")
                    self.action_logger.log_action(
                        action='MARKED_INVALID',
                        normalized_lookup=row['normalized_lookup'],
                        original_name=row['original_name'],
                        team_abbr=row['team_abbr'],
                        season=row['season'],
                        resolution_details={'reason': reason or 'typo/error'},
                        reviewed_by=self.reviewer,
                        notes=reason
                    )
                    actions_taken.append(('invalid', row['original_name']))
            
            elif choice == 'g':
                reason = input("    Reason (optional): ").strip()
                if self.mark_as_ignored(row['normalized_lookup'], row['team_abbr'], reason):
                    print("    Marked as ignored")
                    self.action_logger.log_action(
                        action='MARKED_IGNORED',
                        normalized_lookup=row['normalized_lookup'],
                        original_name=row['original_name'],
                        team_abbr=row['team_abbr'],
                        season=row['season'],
                        resolution_details={'reason': reason or 'too minor'},
                        reviewed_by=self.reviewer,
                        notes=reason
                    )
                    actions_taken.append(('ignored', row['original_name']))
            
            elif choice == 'r':
                notes = input("    Research notes (optional): ").strip()
                if self.mark_under_review(row['normalized_lookup'], row['team_abbr'], notes):
                    print("    Marked under review")
                    self.action_logger.log_action(
                        action='MARKED_UNDER_REVIEW',
                        normalized_lookup=row['normalized_lookup'],
                        original_name=row['original_name'],
                        team_abbr=row['team_abbr'],
                        season=row['season'],
                        resolution_details={'notes': notes or 'needs research'},
                        reviewed_by=self.reviewer,
                        notes=notes
                    )
                    actions_taken.append(('under_review', row['original_name']))
            
            elif choice == 'z':
                days_input = input("    Days to snooze (default 7): ").strip()
                days = int(days_input) if days_input.isdigit() else 7
                
                if self.snooze(row['normalized_lookup'], row['team_abbr'], days):
                    print(f"    Snoozed for {days} days")
                    self.action_logger.log_action(
                        action='SNOOZED',
                        normalized_lookup=row['normalized_lookup'],
                        original_name=row['original_name'],
                        team_abbr=row['team_abbr'],
                        season=row['season'],
                        resolution_details={'days': days},
                        reviewed_by=self.reviewer,
                        notes=f'Snoozed for {days} days'
                    )
                    actions_taken.append(('snoozed', row['original_name']))
            
            else:
                print("    Invalid choice, skipping...")
        
        # Session summary
        print("\n" + "="*80)
        print("SESSION SUMMARY")
        print("="*80)
        print(f"Total reviewed: {idx+1}/{len(pending)}")
        print(f"Actions taken: {len(actions_taken)}")
        
        if actions_taken:
            action_counts = {}
            for action, name in actions_taken:
                action_counts[action] = action_counts.get(action, 0) + 1
            
            for action, count in action_counts.items():
                print(f"  {action}: {count}")
        
        print(f"\nLogs saved to: /tmp/unresolved_resolutions.log")
        print("="*80 + "\n")
    
    def _handle_create_alias(self, unresolved_row) -> bool:
        """Interactive helper for creating alias."""
        
        print("\n    Creating alias...")
        canonical_lookup = input("    Canonical player_lookup: ").strip().lower()
        
        if not canonical_lookup:
            print("    Cancelled")
            return False
        
        # Search for canonical
        matches = self.search_registry(canonical_lookup, season=unresolved_row['season'])
        
        if matches.empty:
            print(f"    Error: '{canonical_lookup}' not found in registry")
            return False
        
        # Show matches
        print(f"\n    Found {len(matches)} matches:")
        for i, match in matches.head(5).iterrows():
            print(f"      {i+1}. {match['player_name']} ({match['player_lookup']}) "
                  f"- {match['team_abbr']} {match['season']} - {match['games_played']} games")
        
        if len(matches) > 1:
            choice = input("\n    Use match number (1-5, or 0 to cancel): ").strip()
            if not choice.isdigit() or int(choice) < 1 or int(choice) > len(matches):
                print("    Cancelled")
                return False
            match_idx = int(choice) - 1
        else:
            confirm = input("\n    Use this match? (y/n): ").strip().lower()
            if confirm != 'y':
                print("    Cancelled")
                return False
            match_idx = 0
        
        canonical_row = matches.iloc[match_idx]
        
        # Get alias type
        print("\n    Alias types:")
        print("      1 - suffix_difference")
        print("      2 - nickname")
        print("      3 - typo")
        print("      4 - source_variation")
        
        type_choice = input("    Type (1-4): ").strip()
        alias_types = {
            '1': 'suffix_difference',
            '2': 'nickname',
            '3': 'typo',
            '4': 'source_variation'
        }
        alias_type = alias_types.get(type_choice, 'manual_resolution')
        
        # Create alias
        if self.create_alias(
            alias_lookup=unresolved_row['normalized_lookup'],
            canonical_lookup=canonical_row['player_lookup'],
            alias_display=unresolved_row['original_name'],
            canonical_display=canonical_row['player_name'],
            alias_type=alias_type
        ):
            # Mark as resolved
            self.mark_as_resolved(
                unresolved_row['normalized_lookup'],
                unresolved_row['team_abbr'],
                resolution_type='create_alias',
                resolved_to_name=canonical_row['player_name']
            )
            
            print(f"    Created alias: {unresolved_row['normalized_lookup']} -> {canonical_row['player_lookup']}")
            
            # Log action
            self.action_logger.log_action(
                action='ALIAS_CREATED',
                normalized_lookup=unresolved_row['normalized_lookup'],
                original_name=unresolved_row['original_name'],
                team_abbr=unresolved_row['team_abbr'],
                season=unresolved_row['season'],
                resolution_details={
                    'canonical_lookup': canonical_row['player_lookup'],
                    'canonical_name': canonical_row['player_name'],
                    'alias_type': alias_type
                },
                reviewed_by=self.reviewer
            )
            
            return True
        
        return False
    
    def _handle_create_new_player(self, unresolved_row) -> bool:
        """Interactive helper for creating new player."""
        
        print("\n    Creating new player...")
        player_name = input(f"    Official name [{unresolved_row['original_name']}]: ").strip()
        if not player_name:
            player_name = unresolved_row['original_name']
        
        jersey_input = input("    Jersey number (optional): ").strip()
        jersey_number = int(jersey_input) if jersey_input.isdigit() else None
        
        position = input("    Position (optional): ").strip() or None
        
        if self.create_registry_entry(
            player_name=player_name,
            player_lookup=unresolved_row['normalized_lookup'],
            team_abbr=unresolved_row['team_abbr'],
            season=unresolved_row['season'],
            jersey_number=jersey_number,
            position=position
        ):
            # Mark as resolved
            self.mark_as_resolved(
                unresolved_row['normalized_lookup'],
                unresolved_row['team_abbr'],
                resolution_type='add_to_registry',
                resolved_to_name=player_name
            )
            
            print(f"    Created registry entry: {player_name}")
            
            # Log action
            self.action_logger.log_action(
                action='NEW_PLAYER_CREATED',
                normalized_lookup=unresolved_row['normalized_lookup'],
                original_name=unresolved_row['original_name'],
                team_abbr=unresolved_row['team_abbr'],
                season=unresolved_row['season'],
                resolution_details={
                    'player_name': player_name,
                    'jersey_number': jersey_number,
                    'position': position
                },
                reviewed_by=self.reviewer
            )
            
            return True
        
        return False
    
    # =========================================================================
    # UTILITY COMMANDS
    # =========================================================================
    
    def show_stats(self):
        """Show system statistics."""
        
        query = f"""
        SELECT 
            'Total Unresolved' as metric,
            COUNT(*) as value
        FROM `{self.project_id}.{self.unresolved_table}`
        
        UNION ALL
        
        SELECT 
            'Pending' as metric,
            COUNT(*) as value
        FROM `{self.project_id}.{self.unresolved_table}`
        WHERE status = 'pending'
        
        UNION ALL
        
        SELECT 
            'Snoozed' as metric,
            COUNT(*) as value
        FROM `{self.project_id}.{self.unresolved_table}`
        WHERE status = 'snoozed'
        
        UNION ALL
        
        SELECT 
            'Under Review' as metric,
            COUNT(*) as value
        FROM `{self.project_id}.{self.unresolved_table}`
        WHERE status = 'under_review'
        
        UNION ALL
        
        SELECT 
            'Resolved' as metric,
            COUNT(*) as value
        FROM `{self.project_id}.{self.unresolved_table}`
        WHERE status = 'resolved'
        
        UNION ALL
        
        SELECT 
            'Total Aliases' as metric,
            COUNT(*) as value
        FROM `{self.project_id}.{self.alias_table}`
        WHERE is_active = TRUE
        
        UNION ALL
        
        SELECT 
            'Registry Players' as metric,
            COUNT(DISTINCT player_lookup) as value
        FROM `{self.project_id}.{self.registry_table}`
        
        ORDER BY metric
        """
        
        stats = self.bq_client.query(query).to_dataframe()
        
        print("\nSYSTEM STATISTICS")
        print("="*40)
        for _, row in stats.iterrows():
            print(f"{row['metric']:25s}: {row['value']:>8,}")
        print("="*40 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Resolve unresolved player names",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (default)
  python -m tools.player_registry.resolve_unresolved_names
  
  # List pending names
  python -m tools.player_registry.resolve_unresolved_names list
  
  # Search registry
  python -m tools.player_registry.resolve_unresolved_names search "lebron"
  
  # Show statistics
  python -m tools.player_registry.resolve_unresolved_names stats

Shell alias recommendation:
  alias resolve='python -m tools.player_registry.resolve_unresolved_names'
        """
    )
    
    parser.add_argument('command', nargs='?', default='interactive',
                       choices=['interactive', 'list', 'search', 'stats'],
                       help='Command to run (default: interactive)')
    parser.add_argument('args', nargs='*', help='Command arguments')
    parser.add_argument('--limit', type=int, default=100,
                       help='Limit for list/interactive commands')
    parser.add_argument('--source', help='Filter by source')
    parser.add_argument('--test', action='store_true',
                       help='Use test tables')
    
    args = parser.parse_args()
    
    resolver = UnresolvedNameResolver(test_mode=args.test)
    
    try:
        if args.command == 'interactive':
            resolver.interactive_resolve(limit=args.limit)
        
        elif args.command == 'list':
            results = resolver.list_pending_unresolved(
                limit=args.limit,
                source=args.source
            )
            
            if results.empty:
                print("\nNo pending unresolved names")
            else:
                print(f"\nFound {len(results)} pending unresolved names:\n")
                from tabulate import tabulate
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
                from tabulate import tabulate
                print(tabulate(results, headers='keys', tablefmt='simple'))
        
        elif args.command == 'stats':
            resolver.show_stats()
    
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()