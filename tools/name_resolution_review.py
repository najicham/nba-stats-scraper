#!/usr/bin/env python3
"""
File: tools/name_resolution_review.py

Manual Review CLI Tool for NBA Player Name Resolution

Command-line interface for reviewing and resolving unresolved player names.
Provides an interactive workflow for manual name resolution with batch processing
and research assistance.

Usage Examples:
    # Review pending names interactively
    python tools/name_resolution_review.py review

    # List pending names without interaction
    python tools/name_resolution_review.py list --limit 20

    # Review names from specific source
    python tools/name_resolution_review.py review --source bdl

    # Create alias mapping directly
    python tools/name_resolution_review.py create-alias "Kenyon Martin Jr." "KJ Martin" --type source_variation --source bdl

    # Add player to registry
    python tools/name_resolution_review.py add-player "New Player" --team LAL --season 2024-25
"""

import argparse
import sys
import os
from typing import Dict, List, Optional
import pandas as pd

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from shared.utils.player_name_resolver import PlayerNameResolver
from shared.utils.player_name_normalizer import normalize_name_for_lookup


class NameResolutionReviewCLI:
    """Interactive CLI for manual name resolution review."""
    
    def __init__(self):
        self.resolver = PlayerNameResolver()
        self.current_session = []  # Track resolutions in this session
    
    def list_pending_names(self, limit: int = 50, source: str = None) -> pd.DataFrame:
        """List pending unresolved names."""
        df = self.resolver.get_unresolved_names(limit=limit, source=source)
        
        if df.empty:
            print("✅ No pending names to review!")
            return df
        
        print(f"\n📋 Found {len(df)} pending names for review")
        print("=" * 80)
        
        for idx, row in df.iterrows():
            print(f"{idx+1:3d}. {row['original_name']} ({row['source']})")
            print(f"     Team: {row['team_abbr']}, Season: {row['season']}")
            print(f"     Occurrences: {row['occurrences']}, First seen: {row['first_seen_date']}")
            print(f"     Normalized: {row['normalized_lookup']}")
            if row['example_games']:
                games = row['example_games'][:2]  # Show first 2 game examples
                print(f"     Example games: {', '.join(games)}")
            print()
        
        return df
    
    def search_registry_for_similar(self, normalized_name: str, team: str = None) -> List[Dict]:
        """Search registry for similar player names to help with resolution."""
        try:
            # Search for partial matches in the registry
            query = f"""
                SELECT DISTINCT
                    player_name,
                    player_lookup,
                    team_abbr,
                    season,
                    games_played
                FROM `{self.resolver.project_id}.nba_reference.nba_players_registry`
                WHERE (
                    CONTAINS_SUBSTR(player_lookup, '{normalized_name[:6]}') OR
                    CONTAINS_SUBSTR('{normalized_name}', player_lookup) OR
                    LEVENSHTEIN(player_lookup, '{normalized_name}') <= 3
                )
            """
            
            if team:
                query += f" AND team_abbr = '{team}'"
            
            query += " ORDER BY team_abbr, season DESC LIMIT 10"
            
            results = self.resolver.bq_client.query(query).to_dataframe()
            return results.to_dict('records') if not results.empty else []
            
        except Exception as e:
            print(f"⚠️  Error searching registry: {e}")
            return []
    
    def research_player(self, original_name: str, team: str, season: str) -> Dict:
        """Provide research context for a player name."""
        normalized = normalize_name_for_lookup(original_name)
        
        print(f"\n🔍 Research for: {original_name}")
        print(f"    Normalized: {normalized}")
        print(f"    Team: {team}, Season: {season}")
        
        # Search for similar names in registry
        similar = self.search_registry_for_similar(normalized, team)
        
        if similar:
            print(f"\n📊 Found {len(similar)} similar players in registry:")
            for i, player in enumerate(similar, 1):
                print(f"  {i}. {player['player_name']} ({player['team_abbr']}, {player['season']})")
                print(f"     Lookup: {player['player_lookup']}, Games: {player.get('games_played', 'N/A')}")
        else:
            print("   No similar players found in registry")
        
        # Search current team roster
        try:
            team_query = f"""
                SELECT player_name, player_lookup, position, jersey_number
                FROM `{self.resolver.project_id}.nba_reference.nba_players_registry`
                WHERE team_abbr = '{team}' AND season = '{season}'
                ORDER BY player_name
            """
            
            team_roster = self.resolver.bq_client.query(team_query).to_dataframe()
            
            if not team_roster.empty:
                print(f"\n👥 {team} roster for {season} ({len(team_roster)} players):")
                for _, player in team_roster.iterrows():
                    jersey = f"#{player['jersey_number']}" if player['jersey_number'] else ""
                    position = f"({player['position']})" if player['position'] else ""
                    print(f"   {player['player_name']} {jersey} {position}")
                    print(f"     Lookup: {player['player_lookup']}")
            
        except Exception as e:
            print(f"⚠️  Could not load team roster: {e}")
        
        return {
            'similar_players': similar,
            'research_complete': True
        }
    
    def interactive_review(self, df: pd.DataFrame):
        """Interactive review session for unresolved names."""
        if df.empty:
            print("No names to review!")
            return
        
        print(f"\n🎯 Starting interactive review session ({len(df)} names)")
        print("Commands: (r)esolve, (s)kip, (i)gnore, (a)dd to registry, (q)uit, (h)elp")
        
        for idx, row in df.iterrows():
            print("\n" + "="*80)
            print(f"📝 Reviewing {idx+1}/{len(df)}: {row['original_name']}")
            print(f"   Source: {row['source']}")
            print(f"   Team: {row['team_abbr']}, Season: {row['season']}")
            print(f"   Occurrences: {row['occurrences']}")
            print(f"   Normalized: {row['normalized_lookup']}")
            
            # Auto-research
            research = self.research_player(row['original_name'], row['team_abbr'], row['season'])
            
            # Safety guard: prevent infinite input loops (100 invalid commands max)
            max_input_attempts = 100
            input_attempt = 0
            while True:
                input_attempt += 1
                if input_attempt > max_input_attempts:
                    print(f"Too many invalid inputs ({max_input_attempts}), skipping this name")
                    break

                try:
                    cmd = input(f"\n➤ Action for '{row['original_name']}': ").lower().strip()

                    if cmd in ['q', 'quit']:
                        print("Exiting review session...")
                        return
                    
                    elif cmd in ['s', 'skip']:
                        print("⏭️  Skipped")
                        break
                    
                    elif cmd in ['h', 'help']:
                        print("\nCommands:")
                        print("  r/resolve - Create alias mapping to existing player")
                        print("  a/add - Add new player to registry")
                        print("  i/ignore - Mark as invalid/typo")
                        print("  s/skip - Skip for now")
                        print("  q/quit - Exit review")
                        continue
                    
                    elif cmd in ['r', 'resolve']:
                        # Create alias mapping
                        canonical_name = input("NBA canonical name: ").strip()
                        if not canonical_name:
                            print("❌ Canonical name required")
                            continue
                        
                        alias_type = input("Alias type (suffix_difference/nickname/source_variation): ").strip()
                        if alias_type not in ['suffix_difference', 'nickname', 'source_variation']:
                            alias_type = 'source_variation'
                        
                        notes = input("Notes (optional): ").strip()
                        
                        # Create the alias
                        success = self.resolver.create_alias_mapping(
                            alias_name=row['original_name'],
                            canonical_name=canonical_name,
                            alias_type=alias_type,
                            alias_source=row['source'],
                            notes=notes,
                            created_by='manual_cli'
                        )
                        
                        if success:
                            # Mark as resolved
                            self.resolver.mark_unresolved_as_resolved(
                                source=row['source'],
                                original_name=row['original_name'],
                                resolved_to=canonical_name,
                                resolution_type='create_alias',
                                notes=f"Alias type: {alias_type}. {notes}",
                                reviewed_by='manual_cli'
                            )
                            print(f"✅ Created alias: '{row['original_name']}' -> '{canonical_name}'")
                            self.current_session.append({
                                'action': 'alias_created',
                                'original': row['original_name'],
                                'resolved_to': canonical_name
                            })
                        else:
                            print("❌ Failed to create alias")
                            continue
                        break
                    
                    elif cmd in ['a', 'add']:
                        # Add to registry
                        player_name = input(f"Official player name [{row['original_name']}]: ").strip()
                        if not player_name:
                            player_name = row['original_name']
                        
                        jersey = input("Jersey number (optional): ").strip()
                        jersey_num = int(jersey) if jersey.isdigit() else None
                        
                        position = input("Position (optional): ").strip() or None
                        
                        success = self.resolver.add_player_to_registry(
                            player_name=player_name,
                            team_abbr=row['team_abbr'],
                            season=row['season'],
                            jersey_number=jersey_num,
                            position=position,
                            created_by='manual_cli'
                        )
                        
                        if success:
                            # Mark as resolved
                            self.resolver.mark_unresolved_as_resolved(
                                source=row['source'],
                                original_name=row['original_name'],
                                resolved_to=player_name,
                                resolution_type='add_to_registry',
                                notes=f"Added to registry with jersey #{jersey_num}, position {position}",
                                reviewed_by='manual_cli'
                            )
                            print(f"✅ Added to registry: {player_name}")
                            self.current_session.append({
                                'action': 'added_to_registry',
                                'original': row['original_name'],
                                'resolved_to': player_name
                            })
                        else:
                            print("❌ Failed to add to registry")
                            continue
                        break
                    
                    elif cmd in ['i', 'ignore']:
                        # Mark as invalid
                        reason = input("Reason (typo/invalid/duplicate): ").strip()
                        notes = input("Additional notes: ").strip()
                        
                        success = self.resolver.mark_unresolved_as_resolved(
                            source=row['source'],
                            original_name=row['original_name'],
                            resolved_to='',
                            resolution_type=reason or 'invalid',
                            notes=notes,
                            reviewed_by='manual_cli'
                        )
                        
                        if success:
                            print(f"✅ Marked as {reason or 'invalid'}")
                            self.current_session.append({
                                'action': 'marked_invalid',
                                'original': row['original_name'],
                                'reason': reason
                            })
                        else:
                            print("❌ Failed to mark as invalid")
                            continue
                        break
                    
                    else:
                        print(f"❌ Unknown command: {cmd}")
                        continue
                        
                except KeyboardInterrupt:
                    print("\n⚠️  Interrupted by user")
                    return
                except Exception as e:
                    print(f"❌ Error: {e}")
                    continue
        
        print(f"\n🎉 Review session complete! Processed {len(df)} names")
        self.print_session_summary()
    
    def print_session_summary(self):
        """Print summary of current session."""
        if not self.current_session:
            print("No actions taken in this session")
            return
        
        print("\n📊 Session Summary:")
        actions = {}
        for item in self.current_session:
            action = item['action']
            actions[action] = actions.get(action, 0) + 1
        
        for action, count in actions.items():
            print(f"  {action}: {count}")
        
        print(f"\nTotal actions: {len(self.current_session)}")
    
    def create_alias_directly(self, alias_name: str, canonical_name: str, 
                            alias_type: str, alias_source: str, notes: str = None):
        """Create alias mapping directly from command line."""
        success = self.resolver.create_alias_mapping(
            alias_name=alias_name,
            canonical_name=canonical_name,
            alias_type=alias_type,
            alias_source=alias_source,
            notes=notes,
            created_by='manual_cli'
        )
        
        if success:
            print(f"✅ Created alias: '{alias_name}' -> '{canonical_name}'")
        else:
            print(f"❌ Failed to create alias")
        
        return success
    
    def add_player_directly(self, player_name: str, team: str, season: str,
                          jersey: int = None, position: str = None):
        """Add player to registry directly from command line."""
        success = self.resolver.add_player_to_registry(
            player_name=player_name,
            team_abbr=team,
            season=season,
            jersey_number=jersey,
            position=position,
            created_by='manual_cli'
        )
        
        if success:
            print(f"✅ Added player: {player_name} ({team}, {season})")
        else:
            print(f"❌ Failed to add player")
        
        return success


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description='NBA Player Name Resolution Manual Review Tool')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List pending unresolved names')
    list_parser.add_argument('--limit', type=int, default=50, help='Maximum number of names to show')
    list_parser.add_argument('--source', type=str, help='Filter by source (bdl, espn, etc.)')
    
    # Review command
    review_parser = subparsers.add_parser('review', help='Interactive review session')
    review_parser.add_argument('--limit', type=int, default=20, help='Maximum number of names to review')
    review_parser.add_argument('--source', type=str, help='Filter by source (bdl, espn, etc.)')
    
    # Create alias command
    alias_parser = subparsers.add_parser('create-alias', help='Create alias mapping directly')
    alias_parser.add_argument('alias_name', help='Alias/variation name')
    alias_parser.add_argument('canonical_name', help='NBA canonical name')
    alias_parser.add_argument('--type', choices=['suffix_difference', 'nickname', 'source_variation'], 
                            default='source_variation', help='Type of alias')
    alias_parser.add_argument('--source', required=True, help='Source of alias (bdl, espn, etc.)')
    alias_parser.add_argument('--notes', help='Optional notes')
    
    # Add player command
    player_parser = subparsers.add_parser('add-player', help='Add player to registry directly')
    player_parser.add_argument('player_name', help='Official player name')
    player_parser.add_argument('--team', required=True, help='Team abbreviation')
    player_parser.add_argument('--season', required=True, help='Season (e.g., 2024-25)')
    player_parser.add_argument('--jersey', type=int, help='Jersey number')
    player_parser.add_argument('--position', help='Position')
    
    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show resolution statistics')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    cli = NameResolutionReviewCLI()
    
    try:
        if args.command == 'list':
            df = cli.list_pending_names(limit=args.limit, source=args.source)
            
        elif args.command == 'review':
            df = cli.resolver.get_unresolved_names(limit=args.limit, source=args.source)
            cli.interactive_review(df)
            
        elif args.command == 'create-alias':
            cli.create_alias_directly(
                alias_name=args.alias_name,
                canonical_name=args.canonical_name,
                alias_type=args.type,
                alias_source=args.source,
                notes=args.notes
            )
            
        elif args.command == 'add-player':
            cli.add_player_directly(
                player_name=args.player_name,
                team=args.team,
                season=args.season,
                jersey=args.jersey,
                position=args.position
            )
            
        elif args.command == 'stats':
            # Show statistics
            query = f"""
                SELECT 
                    'Total Aliases' as metric,
                    COUNT(*) as value
                FROM `{cli.resolver.project_id}.nba_reference.player_aliases`
                WHERE is_active = TRUE
                
                UNION ALL
                
                SELECT 
                    'Registry Players' as metric,
                    COUNT(DISTINCT player_lookup) as value
                FROM `{cli.resolver.project_id}.nba_reference.nba_players_registry`
                
                UNION ALL
                
                SELECT 
                    'Pending Review' as metric,
                    COUNT(*) as value
                FROM `{cli.resolver.project_id}.nba_reference.unresolved_player_names`
                WHERE status = 'pending'
            """
            
            stats = cli.resolver.bq_client.query(query).to_dataframe()
            
            print("\n📊 Name Resolution System Statistics")
            print("=" * 40)
            for _, row in stats.iterrows():
                print(f"{row['metric']}: {row['value']}")
        
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())