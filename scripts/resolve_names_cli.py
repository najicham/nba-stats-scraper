#!/usr/bin/env python3
"""
File: scripts/resolve_names_cli.py
Interactive CLI tool for reviewing and resolving uncertain player names.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from google.cloud import bigquery
import json
from datetime import datetime

class NameResolutionReviewer:
    def __init__(self):
        self.bq_client = bigquery.Client()
        self.project_id = "nba-props-platform"
        
    def get_cases_to_review(self, limit=10, case_type="all"):
        """Get cases that need manual review, prioritized by impact."""
        
        if case_type == "multiple_matches":
            condition = "name_resolution_confidence = 0.6"
        elif case_type == "not_found":
            condition = "name_resolution_confidence = 0.0"
        else:
            condition = "name_resolution_confidence < 0.8"
        
        query = f"""
        SELECT 
            player_name_original,
            team_abbr,
            season_year,
            name_resolution_confidence,
            name_resolution_method,
            COUNT(*) as game_occurrences,
            STRING_AGG(DISTINCT game_id ORDER BY game_id LIMIT 3) as sample_games,
            STRING_AGG(DISTINCT dnp_reason LIMIT 2) as sample_reasons
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE {condition}
          AND player_status IN ('inactive', 'dnp')
        GROUP BY player_name_original, team_abbr, season_year, name_resolution_confidence, name_resolution_method
        ORDER BY game_occurrences DESC, season_year DESC
        LIMIT {limit}
        """
        
        return self.bq_client.query(query).to_dataframe()
    
    def get_roster_context(self, team_abbr, season_year, search_term=""):
        """Get Basketball Reference roster context for decision making."""
        query = f"""
        SELECT 
            player_full_name,
            player_last_name,
            team_abbrev,
            season_year
        FROM `{self.project_id}.nba_raw.br_rosters_current`
        WHERE team_abbrev = '{team_abbr}'
          AND season_year = {season_year}
          AND LOWER(player_full_name) LIKE '%{search_term.lower()}%'
        ORDER BY player_last_name
        """
        
        try:
            return self.bq_client.query(query).to_dataframe()
        except Exception as e:
            print(f"Could not get roster context: {e}")
            return None
    
    def update_resolution(self, original_name, team_abbr, season_year, resolved_name, confidence):
        """Update all records for this name case."""
        
        if resolved_name.lower() == original_name.lower():
            # Same name - just update confidence
            method = "manual_confirmed"
        else:
            # Different name - resolution found
            method = "manual_resolved"
            
        update_query = f"""
        UPDATE `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        SET 
            player_name = '{resolved_name}',
            name_resolution_confidence = {confidence},
            name_resolution_method = '{method}',
            name_last_validated = CURRENT_TIMESTAMP()
        WHERE player_name_original = '{original_name}'
          AND team_abbr = '{team_abbr}'
          AND season_year = {season_year}
          AND player_status IN ('inactive', 'dnp')
        """
        
        result = self.bq_client.query(update_query)
        return result.num_dml_affected_rows
    
    def review_session(self, case_type="multiple_matches", batch_size=10):
        """Interactive review session."""
        print(f"\n=== Name Resolution Review Session ===")
        print(f"Case Type: {case_type}")
        print(f"Commands: (s)kip, (r)esolve NAME, (c)onfirm, (q)uit\n")
        
        cases = self.get_cases_to_review(batch_size, case_type)
        
        for i, case in cases.iterrows():
            print(f"\n--- Case {i+1}/{len(cases)} ---")
            print(f"Original Name: {case['player_name_original']}")
            print(f"Team: {case['team_abbr']} ({case['season_year']} season)")
            print(f"Confidence: {case['name_resolution_confidence']}")
            print(f"Occurrences: {case['game_occurrences']} games")
            print(f"Sample Games: {case['sample_games']}")
            if case['sample_reasons']:
                print(f"Sample Reasons: {case['sample_reasons']}")
            
            # Show roster context for decision making
            roster = self.get_roster_context(case['team_abbr'], case['season_year'], case['player_name_original'])
            if roster is not None and len(roster) > 0:
                print(f"\nPossible roster matches:")
                for _, player in roster.iterrows():
                    print(f"  - {player['player_full_name']}")
            else:
                print(f"\nNo roster matches found for '{case['player_name_original']}'")
            
            # Get user input
            while True:
                action = input(f"\nAction for '{case['player_name_original']}': ").strip().lower()
                
                if action == 's':
                    print("Skipped.")
                    break
                elif action == 'q':
                    print("Quitting review session.")
                    return
                elif action == 'c':
                    # Confirm as-is with high confidence
                    affected = self.update_resolution(
                        case['player_name_original'], 
                        case['team_abbr'], 
                        case['season_year'],
                        case['player_name_original'],  # Keep same name
                        1.0  # High confidence
                    )
                    print(f"Confirmed '{case['player_name_original']}' - updated {affected} records")
                    break
                elif action.startswith('r '):
                    # Resolve to specific name
                    resolved_name = action[2:].strip()
                    if resolved_name:
                        affected = self.update_resolution(
                            case['player_name_original'],
                            case['team_abbr'],
                            case['season_year'], 
                            resolved_name,
                            1.0  # High confidence resolution
                        )
                        print(f"Resolved '{case['player_name_original']}' → '{resolved_name}' - updated {affected} records")
                        break
                    else:
                        print("Please provide a name after 'r'. Example: r John Smith")
                else:
                    print("Commands: (s)kip, (r)esolve NAME, (c)onfirm, (q)uit")

if __name__ == "__main__":
    reviewer = NameResolutionReviewer()
    
    # Start with multiple matches (easier to resolve)
    print("Starting with multiple matches cases (easier to resolve)...")
    reviewer.review_session("multiple_matches", 20)
    
    print("\nWould you like to review 'not found' cases? (y/n)")
    if input().lower() == 'y':
        reviewer.review_session("not_found", 20)
    
    print("\nReview session complete!")