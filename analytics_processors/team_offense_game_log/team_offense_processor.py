#!/usr/bin/env python3
"""
File: analytics_processors/team_offense_game_log/team_offense_processor.py

Analytics processor for team offense game log data.
Combines team performance data into analytics table.
"""

import logging
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List
from analytics_processors.analytics_base import AnalyticsProcessorBase

logger = logging.getLogger(__name__)


class TeamOffenseProcessor(AnalyticsProcessorBase):
    """Process team offense analytics from raw data tables."""
    
    def __init__(self):
        super().__init__()
        self.table_name = 'team_offense_game_log'
        self.processing_strategy = 'MERGE_UPDATE'
        
    def extract_raw_data(self) -> None:
        """Query raw BigQuery tables for team offensive data."""
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']
        
        query = f"""
        SELECT 
            b.game_id,
            b.game_date,
            b.season_year,
            b.team_abbr,
            
            -- Calculate opponent from game context
            CASE 
                WHEN b.team_abbr = b.home_team_abbr THEN b.away_team_abbr 
                ELSE b.home_team_abbr 
            END as opponent_team_abbr,
            
            -- Aggregate team stats from player box scores
            SUM(b.points) as team_points,
            SUM(b.assists) as team_assists,
            SUM(b.field_goals_made) as team_fg_makes,
            SUM(b.field_goals_attempted) as team_fg_attempts,
            SUM(b.three_pointers_made) as team_3pt_makes,
            SUM(b.three_pointers_attempted) as team_3pt_attempts,
            SUM(b.free_throws_made) as team_ft_makes,
            SUM(b.free_throws_attempted) as team_ft_attempts,
            SUM(b.offensive_rebounds) as team_offensive_rebounds,
            SUM(b.turnovers) as team_turnovers,
            
            -- Game context
            b.home_team_abbr,
            b.away_team_abbr,
            b.home_team_score,
            b.away_team_score,
            ABS(b.home_team_score - b.away_team_score) as margin_of_victory,
            CASE WHEN b.team_abbr = b.home_team_abbr THEN TRUE ELSE FALSE END as home_game,
            CASE 
                WHEN b.team_abbr = b.home_team_abbr AND b.home_team_score > b.away_team_score THEN TRUE
                WHEN b.team_abbr = b.away_team_abbr AND b.away_team_score > b.home_team_score THEN TRUE
                ELSE FALSE
            END as win_flag
            
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores` b
        WHERE b.game_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY 
            b.game_id, b.game_date, b.season_year, b.team_abbr,
            b.home_team_abbr, b.away_team_abbr, b.home_team_score, b.away_team_score
        ORDER BY b.game_date, b.game_id, b.team_abbr
        """
        
        logger.info(f"Extracting team offense data for {start_date} to {end_date}")
        self.raw_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.raw_data)} team-game records")
    
    def calculate_blowout_level(self, margin: int) -> int:
        """Calculate blowout level: 1=Close Game, 2=Solid Win, 3=Comfortable, 4=Clear Blowout, 5=Massive"""
        margin = abs(margin) if margin else 0
        if margin <= 5: return 1
        elif margin <= 10: return 2  
        elif margin <= 17: return 3
        elif margin <= 25: return 4
        else: return 5
    
    def calculate_analytics(self) -> None:
        """Calculate team offense analytics metrics."""
        records = []
        
        for _, row in self.raw_data.iterrows():
            # Calculate analytics
            blowout_level = self.calculate_blowout_level(row.get('margin_of_victory', 0))
            
            # Calculate advanced metrics
            fg_attempts = row['team_fg_attempts'] if pd.notna(row['team_fg_attempts']) else 0
            fg_makes = row['team_fg_makes'] if pd.notna(row['team_fg_makes']) else 0
            three_pt_makes = row['team_3pt_makes'] if pd.notna(row['team_3pt_makes']) else 0
            ft_attempts = row['team_ft_attempts'] if pd.notna(row['team_ft_attempts']) else 0
            
            # Effective FG%
            off_efg_pct = None
            if fg_attempts > 0:
                off_efg_pct = (fg_makes + 0.5 * three_pt_makes) / fg_attempts
            
            # True Shooting %
            ts_pct = None
            if fg_attempts > 0:
                ts_attempts = 2 * (fg_attempts + 0.44 * ft_attempts)
                if ts_attempts > 0:
                    ts_pct = row['team_points'] / ts_attempts
            
            # Free throw rate
            off_ft_rate = None
            if fg_attempts > 0:
                off_ft_rate = ft_attempts / fg_attempts
            
            # Three-point rate
            three_point_rate = None
            if fg_attempts > 0:
                three_point_rate = row['team_3pt_attempts'] / fg_attempts
            
            record = {
                # Core identifiers
                'game_id': row['game_id'],
                'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                'season_year': int(row['season_year']) if pd.notna(row['season_year']) else None,
                'team_abbr': row['team_abbr'],
                'opponent_team_abbr': row['opponent_team_abbr'],
                
                # Team shooting stats
                'team_fg_attempts': int(fg_attempts),
                'team_fg_makes': int(fg_makes),
                'team_three_pt_attempts': int(row['team_3pt_attempts']) if pd.notna(row['team_3pt_attempts']) else 0,
                'team_three_pt_makes': int(three_pt_makes),
                'team_ft_attempts': int(ft_attempts),
                'team_ft_makes': int(row['team_ft_makes']) if pd.notna(row['team_ft_makes']) else 0,
                
                # Team stats
                'points_scored': int(row['team_points']) if pd.notna(row['team_points']) else 0,
                'assists': int(row['team_assists']) if pd.notna(row['team_assists']) else 0,
                'offensive_rebounds': int(row['team_offensive_rebounds']) if pd.notna(row['team_offensive_rebounds']) else 0,
                'turnovers': int(row['team_turnovers']) if pd.notna(row['team_turnovers']) else 0,
                
                # Advanced metrics
                'off_efg_pct': round(off_efg_pct, 3) if off_efg_pct is not None else None,
                'ts_pct': round(ts_pct, 3) if ts_pct is not None else None,
                'off_ft_rate': round(off_ft_rate, 3) if off_ft_rate is not None else None,
                'three_point_rate': round(three_point_rate, 3) if three_point_rate is not None else None,
                
                # Game context
                'home_game': bool(row['home_game']) if pd.notna(row['home_game']) else None,
                'win_flag': bool(row['win_flag']) if pd.notna(row['win_flag']) else None,
                'margin_of_victory': int(row['margin_of_victory']) if pd.notna(row['margin_of_victory']) else None,
                'final_score_team': int(row['home_team_score']) if row['home_game'] else int(row['away_team_score']),
                'final_score_opponent': int(row['away_team_score']) if row['home_game'] else int(row['home_team_score']),
                
                # Blowout analysis
                'blowout_level': blowout_level,
                'blowout_description': self.get_blowout_description(blowout_level),
                
                # Processing metadata
                'processed_at': datetime.now(timezone.utc).isoformat()
            }
            
            records.append(record)
        
        self.transformed_data = records
        logger.info(f"Calculated team offense analytics for {len(records)} team-game records")
    
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
        """Return team offense specific stats."""
        if not self.transformed_data:
            return {}
            
        stats = {
            'team_games_processed': len(self.transformed_data),
            'unique_teams': len(set(r['team_abbr'] for r in self.transformed_data)),
            'home_games': sum(1 for r in self.transformed_data if r['home_game']),
            'wins': sum(1 for r in self.transformed_data if r['win_flag']),
            'blowout_games': sum(1 for r in self.transformed_data if r['blowout_level'] >= 4)
        }
        
        return stats