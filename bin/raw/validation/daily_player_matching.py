#!/usr/bin/env python3
# bin/processors/validation/daily_player_matching.py

import pandas as pd
import logging
from datetime import datetime, date, timedelta
from google.cloud import bigquery
from difflib import SequenceMatcher
import argparse
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DailyPlayerMatcher:
    def __init__(self):
        self.bq_client = bigquery.Client()
        
    def normalize_name(self, name):
        """Normalize player name for comparison."""
        if not name:
            return ""
        
        # Remove common suffixes and standardize
        normalized = name.lower().strip()
        
        # Remove generational suffixes
        suffixes_to_remove = [' jr.', ' jr', ' sr.', ' sr', ' ii', ' iii', ' iv']
        for suffix in suffixes_to_remove:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
        
        # Remove apostrophes and periods
        normalized = normalized.replace("'", "").replace(".", "")
        
        return normalized
    
    def get_game_data_for_date(self, game_date):
        """Get all NBA.com and BDL data for a specific date."""
        
        # NBA.com gamebook data (exclude injured players)
        nba_query = f"""
        SELECT DISTINCT
            game_id,
            game_date,
            home_team_abbr,
            away_team_abbr,
            player_name as player_full_name,
            player_lookup,
            points,
            assists,
            total_rebounds as rebounds,
            minutes,
            player_status,
            dnp_reason
        FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date = '{game_date}'
            AND (dnp_reason IS NULL 
                 OR (dnp_reason NOT LIKE '%Injury%' AND dnp_reason NOT LIKE '%Illness%'))
        ORDER BY game_id, player_name
        """
        
        # BDL boxscore data  
        bdl_query = f"""
        SELECT DISTINCT
            game_id,
            game_date,
            home_team_abbr,
            away_team_abbr,
            player_full_name,
            player_lookup,
            points,
            assists,
            rebounds,
            minutes
        FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
        WHERE game_date = '{game_date}'
        ORDER BY game_id, player_full_name
        """
        
        logger.info(f"Loading NBA.com data for {game_date}...")
        nba_df = self.bq_client.query(nba_query).to_dataframe()
        
        logger.info(f"Loading BDL data for {game_date}...")
        bdl_df = self.bq_client.query(bdl_query).to_dataframe()
        
        return nba_df, bdl_df
    
    def match_players_by_game(self, nba_df, bdl_df):
        """Match players within the same game using name similarity."""
        results = []
        
        # Group by game_id for precise matching
        nba_games = nba_df.groupby('game_id')
        bdl_games = bdl_df.groupby('game_id')
        
        all_game_ids = set(nba_df['game_id'].unique()) | set(bdl_df['game_id'].unique())
        
        for game_id in all_game_ids:
            logger.info(f"Processing game: {game_id}")
            
            # Get players for this specific game
            nba_players = nba_games.get_group(game_id) if game_id in nba_games.groups else pd.DataFrame()
            bdl_players = bdl_games.get_group(game_id) if game_id in bdl_games.groups else pd.DataFrame()
            
            # Track matched players to avoid duplicates
            matched_bdl = set()
            matched_nba = set()
            
            # Attempt exact player_lookup matches first
            for nba_idx, nba_player in nba_players.iterrows():
                nba_lookup = nba_player['player_lookup'].lower().strip() if nba_player['player_lookup'] else ""
                
                for bdl_idx, bdl_player in bdl_players.iterrows():
                    if bdl_idx in matched_bdl:
                        continue
                        
                    bdl_lookup = bdl_player['player_lookup'].lower().strip() if bdl_player['player_lookup'] else ""
                    
                    # Check for exact player_lookup match
                    if nba_lookup and bdl_lookup and nba_lookup == bdl_lookup:
                        # Handle NaN values properly
                        nba_pts = 0 if pd.isna(nba_player['points']) else nba_player['points']
                        bdl_pts = 0 if pd.isna(bdl_player['points']) else bdl_player['points']
                        
                        results.append({
                            'game_id': game_id,
                            'match_type': 'EXACT',
                            'nba_name': nba_player['player_full_name'],
                            'bdl_name': bdl_player['player_full_name'],
                            'nba_lookup': nba_player['player_lookup'],
                            'bdl_lookup': bdl_player['player_lookup'],
                            'nba_status': nba_player.get('player_status', 'unknown'),
                            'nba_points': nba_pts,
                            'bdl_points': bdl_pts,
                            'points_diff': abs(nba_pts - bdl_pts),
                            'similarity': 1.0
                        })
                        matched_nba.add(nba_idx)
                        matched_bdl.add(bdl_idx)
                        break
            
            # Then attempt fuzzy player_lookup matches for unmatched players
            unmatched_nba = nba_players[~nba_players.index.isin(matched_nba)]
            unmatched_bdl = bdl_players[~bdl_players.index.isin(matched_bdl)]
            
            for nba_idx, nba_player in unmatched_nba.iterrows():
                nba_lookup = nba_player['player_lookup'].lower().strip() if nba_player['player_lookup'] else ""
                best_match = None
                best_match_idx = None
                best_similarity = 0.0
                
                for bdl_idx, bdl_player in unmatched_bdl.iterrows():
                    if bdl_idx in matched_bdl:
                        continue
                        
                    bdl_lookup = bdl_player['player_lookup'].lower().strip() if bdl_player['player_lookup'] else ""
                    
                    if nba_lookup and bdl_lookup:
                        similarity = SequenceMatcher(None, nba_lookup, bdl_lookup).ratio()
                        
                        # Only consider high-confidence fuzzy matches
                        if similarity > 0.85 and similarity > best_similarity:
                            # Additional validation: check if stats are reasonably close
                            nba_pts = 0 if pd.isna(nba_player['points']) else nba_player['points']
                            bdl_pts = 0 if pd.isna(bdl_player['points']) else bdl_player['points']
                            points_diff = abs(nba_pts - bdl_pts)
                            if points_diff <= 10:  # Allow some differences for dnp vs active
                                best_similarity = similarity
                                best_match = bdl_player
                                best_match_idx = bdl_idx
                
                if best_match is not None:
                    nba_pts = 0 if pd.isna(nba_player['points']) else nba_player['points']
                    bdl_pts = 0 if pd.isna(best_match['points']) else best_match['points']
                    
                    results.append({
                        'game_id': game_id,
                        'match_type': 'FUZZY',
                        'nba_name': nba_player['player_full_name'],
                        'bdl_name': best_match['player_full_name'],
                        'nba_lookup': nba_player['player_lookup'],
                        'bdl_lookup': best_match['player_lookup'],
                        'nba_status': nba_player.get('player_status', 'unknown'),
                        'nba_points': nba_pts,
                        'bdl_points': bdl_pts,
                        'points_diff': abs(nba_pts - bdl_pts),
                        'similarity': best_similarity
                    })
                    matched_nba.add(nba_idx)
                    matched_bdl.add(best_match_idx)
            
            # Record unmatched players
            final_unmatched_nba = nba_players[~nba_players.index.isin(matched_nba)]
            final_unmatched_bdl = bdl_players[~bdl_players.index.isin(matched_bdl)]
            
            for nba_idx, player in final_unmatched_nba.iterrows():
                nba_pts = 0 if pd.isna(player['points']) else player['points']
                
                results.append({
                    'game_id': game_id,
                    'match_type': 'NBA_ONLY',
                    'nba_name': player['player_full_name'],
                    'bdl_name': None,
                    'nba_lookup': player['player_lookup'],
                    'bdl_lookup': None,
                    'nba_status': player.get('player_status', 'unknown'),
                    'nba_points': nba_pts,
                    'bdl_points': None,
                    'points_diff': None,
                    'similarity': None
                })
            
            for bdl_idx, player in final_unmatched_bdl.iterrows():
                bdl_pts = 0 if pd.isna(player['points']) else player['points']
                
                results.append({
                    'game_id': game_id,
                    'match_type': 'BDL_ONLY',
                    'nba_name': None,
                    'bdl_name': player['player_full_name'],
                    'nba_lookup': None,
                    'bdl_lookup': player['player_lookup'],
                    'nba_status': None,
                    'nba_points': None,
                    'bdl_points': bdl_pts,
                    'points_diff': None,
                    'similarity': None
                })
        
        return pd.DataFrame(results)
    
    def generate_daily_report(self, results_df, game_date):
        """Generate comprehensive daily matching report."""
        
        print(f"\n{'='*80}")
        print(f"DAILY PLAYER MATCHING REPORT - {game_date}")
        print(f"{'='*80}")
        
        # Overall statistics
        total_matches = len(results_df)
        exact_matches = len(results_df[results_df['match_type'] == 'EXACT'])
        fuzzy_matches = len(results_df[results_df['match_type'] == 'FUZZY'])
        nba_only = len(results_df[results_df['match_type'] == 'NBA_ONLY'])
        bdl_only = len(results_df[results_df['match_type'] == 'BDL_ONLY'])
        
        print(f"\nOVERALL STATISTICS:")
        print(f"Total Records: {total_matches}")
        print(f"Exact Matches: {exact_matches} ({exact_matches/total_matches*100:.1f}%)")
        print(f"Fuzzy Matches: {fuzzy_matches} ({fuzzy_matches/total_matches*100:.1f}%)")
        print(f"NBA.com Only: {nba_only} ({nba_only/total_matches*100:.1f}%)")
        print(f"BDL Only: {bdl_only} ({bdl_only/total_matches*100:.1f}%)")
        
        # Game-by-game breakdown
        print(f"\nGAME-BY-GAME BREAKDOWN:")
        game_summary = results_df.groupby('game_id').agg({
            'match_type': ['count', lambda x: (x == 'EXACT').sum(), lambda x: (x == 'NBA_ONLY').sum(), lambda x: (x == 'BDL_ONLY').sum()]
        }).round(1)
        
        for game_id in results_df['game_id'].unique():
            if pd.isna(game_id):
                continue
            game_data = results_df[results_df['game_id'] == game_id]
            exact = len(game_data[game_data['match_type'] == 'EXACT'])
            fuzzy = len(game_data[game_data['match_type'] == 'FUZZY'])
            nba_only = len(game_data[game_data['match_type'] == 'NBA_ONLY'])
            bdl_only = len(game_data[game_data['match_type'] == 'BDL_ONLY'])
            
            print(f"  {game_id}: {exact} exact, {fuzzy} fuzzy, {nba_only} NBA-only, {bdl_only} BDL-only")
        
        # Show problematic cases
        if nba_only > 0:
            print(f"\nNBA.COM ONLY PLAYERS (potential missing from BDL):")
            nba_only_players = results_df[results_df['match_type'] == 'NBA_ONLY']
            for _, player in nba_only_players.iterrows():
                status = f" [{player['nba_status']}]" if player['nba_status'] else ""
                print(f"  {player['game_id']}: {player['nba_name']}{status} ({player['nba_points']} pts) | lookup: {player['nba_lookup']}")
        
        if bdl_only > 0:
            print(f"\nBDL ONLY PLAYERS (potential missing from NBA.com):")
            bdl_only_players = results_df[results_df['match_type'] == 'BDL_ONLY']
            for _, player in bdl_only_players.iterrows():
                print(f"  {player['game_id']}: {player['bdl_name']} ({player['bdl_points']} pts) | lookup: {player['bdl_lookup']}")
        
        if fuzzy_matches > 0:
            print(f"\nFUZZY MATCHES (verify these are correct):")
            fuzzy_players = results_df[results_df['match_type'] == 'FUZZY']
            for _, player in fuzzy_players.iterrows():
                status = f" [{player['nba_status']}]" if player['nba_status'] else ""
                print(f"  {player['game_id']}: '{player['nba_name']}'{status} ↔ '{player['bdl_name']}' (similarity: {player['similarity']:.3f})")
                print(f"    NBA lookup: '{player['nba_lookup']}' | BDL lookup: '{player['bdl_lookup']}'")
        
        # Show some exact matches for verification
        if exact_matches > 0:
            print(f"\nSAMPLE EXACT MATCHES (first 5):")
            exact_players = results_df[results_df['match_type'] == 'EXACT'].head(5)
            for _, player in exact_players.iterrows():
                status = f" [{player['nba_status']}]" if player['nba_status'] else ""
                print(f"  {player['game_id']}: {player['nba_name']}{status} ↔ {player['bdl_name']} | lookup: {player['nba_lookup']}")
        
        print(f"\n{'='*80}")
        
        return results_df
    
    def validate_date(self, target_date):
        """Validate a single date."""
        logger.info(f"Starting daily player matching validation for {target_date}")
        
        nba_df, bdl_df = self.get_game_data_for_date(target_date)
        
        if len(nba_df) == 0 and len(bdl_df) == 0:
            print(f"No games found for {target_date}")
            return None
        
        logger.info(f"NBA.com records: {len(nba_df)}, BDL records: {len(bdl_df)}")
        
        results_df = self.match_players_by_game(nba_df, bdl_df)
        report = self.generate_daily_report(results_df, target_date)
        
        # Export detailed results
        filename = f"daily_matching_{target_date}.csv"
        results_df.to_csv(filename, index=False)
        logger.info(f"Detailed results exported to {filename}")
        
        return results_df

def main():
    parser = argparse.ArgumentParser(description='Daily player matching validation')
    parser.add_argument('--date', type=str, help='Date to validate (YYYY-MM-DD)', required=True)
    
    args = parser.parse_args()
    
    try:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    except ValueError:
        logger.error("Invalid date format. Use YYYY-MM-DD")
        return
    
    matcher = DailyPlayerMatcher()
    matcher.validate_date(target_date)

if __name__ == "__main__":
    main()