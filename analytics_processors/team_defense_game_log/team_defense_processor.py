#!/usr/bin/env python3
"""
File: analytics_processors/team_defense_game_log/team_defense_processor.py

Analytics processor for team defense game log data.
Combines team defensive performance data into analytics table.
"""

import logging
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List
from analytics_processors.analytics_base import AnalyticsProcessorBase

logger = logging.getLogger(__name__)


class TeamDefenseProcessor(AnalyticsProcessorBase):
    """Process team defense analytics from raw data tables."""
    
    def __init__(self):
        super().__init__()
        self.table_name = 'team_defense_game_log'
        self.processing_strategy = 'MERGE_UPDATE'
        
    def extract_raw_data(self) -> None:
        """Query raw BigQuery tables for team defensive data."""
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']
        
        query = f"""
        SELECT 
            b.game_id,
            b.game_date,
            b.season_year,
            
            -- Defending team perspective: aggregate opponent stats
            CASE 
                WHEN b.team_abbr = b.home_team_abbr THEN b.away_team_abbr 
                ELSE b.home_team_abbr 
            END as defending_team_abbr,
            
            b.team_abbr as opponent_team_abbr,
            
            -- Opponent stats (what defense allowed)
            SUM(b.points) as opp_points,
            SUM(b.field_goals_made) as opp_fg_makes,
            SUM(b.field_goals_attempted) as opp_fg_attempts,
            SUM(b.three_pointers_made) as opp_3pt_makes,
            SUM(b.three_pointers_attempted) as opp_3pt_attempts,
            SUM(b.free_throws_made) as opp_ft_makes,
            SUM(b.free_throws_attempted) as opp_ft_attempts,
            SUM(b.offensive_rebounds) as opp_offensive_rebounds,
            SUM(b.defensive_rebounds) as team_defensive_rebounds,
            SUM(b.turnovers) as turnovers_forced,
            SUM(b.steals) as steals,
            SUM(b.blocks) as total_blocks,
            
            -- Game context
            b.home_team_abbr,
            b.away_team_abbr,
            b.home_team_score,
            b.away_team_score,
            ABS(b.home_team_score - b.away_team_score) as margin_of_victory,
            
            -- Determine home/away for defending team
            CASE 
                WHEN b.team_abbr = b.home_team_abbr THEN FALSE  -- Opponent is home, defense is away
                ELSE TRUE  -- Opponent is away, defense is home
            END as home_game,
            
            -- Win flag for defending team
            CASE 
                WHEN b.team_abbr = b.home_team_abbr AND b.away_team_score > b.home_team_score THEN TRUE  -- Defense won (opponent lost)
                WHEN b.team_abbr = b.away_team_abbr AND b.home_team_score > b.away_team_score THEN TRUE  -- Defense won (opponent lost)
                ELSE FALSE
            END as win_flag
            
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores` b
        WHERE b.game_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY 
            b.game_id, b.game_date, b.season_year, b.team_abbr,
            b.home_team_abbr, b.away_team_abbr, b.home_team_score, b.away_team_score
        ORDER BY b.game_date, b.game_id
        """
        
        logger.info(f"Extracting team defense data for {start_date} to {end_date}")
        self.raw_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.raw_data)} team defensive records")
    
    def calculate_blowout_level(self, margin: int) -> int:
        """Calculate blowout level: 1=Close Game, 2=Solid Win, 3=Comfortable, 4=Clear Blowout, 5=Massive"""
        margin = abs(margin) if margin else 0
        if margin <= 5: return 1
        elif margin <= 10: return 2  
        elif margin <= 17: return 3
        elif margin <= 25: return 4
        else: return 5
    
    def calculate_analytics(self) -> None:
        """Calculate team defense analytics metrics."""
        records = []
        
        for _, row in self.raw_data.iterrows():
            # Calculate analytics
            blowout_level = self.calculate_blowout_level(row.get('margin_of_victory', 0))
            
            # Calculate defensive advanced metrics
            opp_fg_attempts = row['opp_fg_attempts'] if pd.notna(row['opp_fg_attempts']) else 0
            opp_fg_makes = row['opp_fg_makes'] if pd.notna(row['opp_fg_makes']) else 0
            opp_3pt_makes = row['opp_3pt_makes'] if pd.notna(row['opp_3pt_makes']) else 0
            opp_ft_attempts = row['opp_ft_attempts'] if pd.notna(row['opp_ft_attempts']) else 0
            
            # Defensive Effective FG% allowed
            def_efg_allowed = None
            if opp_fg_attempts > 0:
                def_efg_allowed = (opp_fg_makes + 0.5 * opp_3pt_makes) / opp_fg_attempts
            
            # Free throw rate allowed
            def_ft_rate_allowed = None
            if opp_fg_attempts > 0:
                def_ft_rate_allowed = opp_ft_attempts / opp_fg_attempts
            
            # Defensive rebound percentage
            def_drb_pct = None
            team_drb = row['team_defensive_rebounds'] if pd.notna(row['team_defensive_rebounds']) else 0
            opp_orb = row['opp_offensive_rebounds'] if pd.notna(row['opp_offensive_rebounds']) else 0
            if (team_drb + opp_orb) > 0:
                def_drb_pct = team_drb / (team_drb + opp_orb)
            
            record = {
                # Core identifiers
                'game_id': row['game_id'],
                'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                'season_year': int(row['season_year']) if pd.notna(row['season_year']) else None,
                'defending_team_abbr': row['defending_team_abbr'],
                'opponent_team_abbr': row['opponent_team_abbr'],
                
                # Opponent shooting allowed
                'opp_fg_attempts': int(opp_fg_attempts),
                'opp_fg_makes': int(opp_fg_makes),
                'opp_three_pt_attempts': int(row['opp_3pt_attempts']) if pd.notna(row['opp_3pt_attempts']) else 0,
                'opp_three_pt_makes': int(opp_3pt_makes),
                'opp_ft_attempts': int(opp_ft_attempts),
                'opp_ft_makes': int(row['opp_ft_makes']) if pd.notna(row['opp_ft_makes']) else 0,
                
                # Points and rebounds
                'points_allowed': int(row['opp_points']) if pd.notna(row['opp_points']) else 0,
                'team_defensive_rebounds': int(team_drb),
                'opp_offensive_rebounds': int(opp_orb),
                
                # Defensive stats generated
                'total_blocks': int(row['total_blocks']) if pd.notna(row['total_blocks']) else 0,
                'steals': int(row['steals']) if pd.notna(row['steals']) else 0,
                'turnovers_forced': int(row['turnovers_forced']) if pd.notna(row['turnovers_forced']) else 0,
                
                # Advanced defensive metrics
                'def_efg_allowed': round(def_efg_allowed, 3) if def_efg_allowed is not None else None,
                'def_ft_rate_allowed': round(def_ft_rate_allowed, 3) if def_ft_rate_allowed is not None else None,
                'def_drb_pct': round(def_drb_pct, 3) if def_drb_pct is not None else None,
                
                # Game context
                'home_game': bool(row['home_game']) if pd.notna(row['home_game']) else None,
                'win_flag': bool(row['win_flag']) if pd.notna(row['win_flag']) else None,
                'margin_of_victory': int(row['margin_of_victory']) if pd.notna(row['margin_of_victory']) else None,
                
                # Final scores (from defensive team perspective)
                'final_score_defense': int(row['home_team_score']) if row['home_game'] else int(row['away_team_score']),
                'final_score_opponent': int(row['away_team_score']) if row['home_game'] else int(row['home_team_score']),
                
                # Blowout analysis
                'blowout_level': blowout_level,
                'blowout_description': self.get_blowout_description(blowout_level),
                
                # Processing metadata
                'processed_at': datetime.now(timezone.utc).isoformat()
            }
            
            records.append(record)
        
        self.transformed_data = records
        logger.info(f"Calculated team defense analytics for {len(records)} team defensive records")
    
    def get_blowout_description(self, level: int) -> str:
        """Get descriptive text for blowout level."""
        descriptions = {
            1: "Close Game",
            2: "Solid Win", 
            3: "Comfortable Win",
            4: "Clear Blowout",
            5: "Massive Blowout"
        }
        return descriptions.get(level, "Unknown")
    
    def get_analytics_stats(self) -> Dict:
        """Return team defense specific stats."""
        if not self.transformed_data:
            return {}
            
        stats = {
            'defensive_games_processed': len(self.transformed_data),
            'unique_defensive_teams': len(set(r['defending_team_abbr'] for r in self.transformed_data)),
            'home_defensive_games': sum(1 for r in self.transformed_data if r['home_game']),
            'defensive_wins': sum(1 for r in self.transformed_data if r['win_flag']),
            'games_held_under_100': sum(1 for r in self.transformed_data if r['points_allowed'] < 100)
        }
        
        return stats