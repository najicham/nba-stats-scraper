"""
File: analytics_processors/player_game_summary/player_game_summary_processor.py

Analytics processor for player game summary data.
Combines gamebook, box scores, props, and injury data into analytics table.
"""

import logging
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List
from analytics_processors.analytics_base import AnalyticsProcessorBase

logger = logging.getLogger(__name__)


class PlayerGameSummaryProcessor(AnalyticsProcessorBase):
    """Process player game summary analytics from raw data tables."""
    
    def __init__(self):
        super().__init__()
        self.table_name = 'player_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'
        
    def extract_raw_data(self) -> None:
        """Query raw BigQuery tables for player performance data."""
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']
        
        query = f"""
        SELECT 
            g.game_id,
            g.game_date,
            g.season_year,
            g.player_lookup,
            g.player_full_name,
            g.team_abbr,
            g.player_status,
            g.points,
            g.assists,
            g.total_rebounds as rebounds,
            g.minutes,
            
            -- Cross-validation from BDL
            b.points as bdl_points,
            
            -- Props context
            p.points_line,
            p.over_under_result,
            
            -- Injury context
            i.injury_status,
            
            -- Game context from scoreboard
            s.home_team_abbr,
            s.away_team_abbr,
            s.home_score,
            s.away_score,
            ABS(s.home_score - s.away_score) as margin_of_victory,
            
            -- Team context
            CASE WHEN g.team_abbr = s.home_team_abbr THEN TRUE ELSE FALSE END as home_game
            
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats` g
        LEFT JOIN `{self.project_id}.nba_raw.bdl_player_boxscores` b 
            ON g.game_id = b.game_id AND g.player_lookup = b.player_lookup
        LEFT JOIN `{self.project_id}.nba_raw.odds_api_player_points_props` p
            ON g.game_id = p.game_id AND g.player_lookup = p.player_lookup  
        LEFT JOIN `{self.project_id}.nba_raw.nbac_injury_report` i
            ON g.player_lookup = i.player_lookup AND g.game_date = DATE(i.game_date)
        LEFT JOIN `{self.project_id}.nba_raw.nbac_scoreboard_v2` s
            ON g.game_id = s.game_id
        WHERE g.game_date BETWEEN '{start_date}' AND '{end_date}'
            AND g.player_status = 'active'
        ORDER BY g.game_date, g.game_id, g.player_lookup
        """
        
        logger.info(f"Extracting data for {start_date} to {end_date}")
        self.raw_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.raw_data)} player-game records")
    
    def validate_extracted_data(self) -> None:
        """Validate extracted data and log quality issues."""
        super().validate_extracted_data()
        
        # Check for data mismatches
        mismatches = self.raw_data[
            (self.raw_data['points'].notna()) & 
            (self.raw_data['bdl_points'].notna()) & 
            (abs(self.raw_data['points'] - self.raw_data['bdl_points']) > 1)
        ]
        
        if not mismatches.empty:
            for _, row in mismatches.iterrows():
                self.log_quality_issue(
                    issue_type='cross_source_mismatch',
                    severity='warning',
                    identifier=f"{row['game_id']}_{row['player_lookup']}",
                    details={
                        'gamebook_points': int(row['points']),
                        'bdl_points': int(row['bdl_points']),
                        'difference': int(abs(row['points'] - row['bdl_points']))
                    }
                )
    
    def calculate_blowout_level(self, margin: int) -> int:
        """Calculate blowout level: 1=Close Game, 2=Solid Win, 3=Comfortable, 4=Clear Blowout, 5=Massive"""
        margin = abs(margin) if margin else 0
        if margin <= 5: return 1
        elif margin <= 10: return 2  
        elif margin <= 17: return 3
        elif margin <= 25: return 4
        else: return 5
    
    def calculate_analytics(self) -> None:
        """Calculate analytics metrics and transform to output format."""
        records = []
        
        for _, row in self.raw_data.iterrows():
            # Calculate analytics
            blowout_level = self.calculate_blowout_level(row.get('margin_of_victory', 0))
            
            # Determine prop outcome
            over_under_result = None
            margin = None
            if pd.notna(row['points']) and pd.notna(row['points_line']):
                if row['points'] > row['points_line']:
                    over_under_result = 'OVER'
                else:
                    over_under_result = 'UNDER'
                margin = row['points'] - row['points_line']
            
            record = {
                # Core identifiers
                'player_lookup': row['player_lookup'],
                'player_full_name': row['player_full_name'],
                'game_id': row['game_id'],
                'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                'season_year': int(row['season_year']) if pd.notna(row['season_year']) else None,
                'team_abbr': row['team_abbr'],
                'opponent_team_abbr': row['away_team_abbr'] if row['home_game'] else row['home_team_abbr'],
                
                # Performance metrics
                'points': int(row['points']) if pd.notna(row['points']) else None,
                'assists': int(row['assists']) if pd.notna(row['assists']) else None,
                'rebounds': int(row['rebounds']) if pd.notna(row['rebounds']) else None,
                'minutes_string': row['minutes'],
                
                # Game context
                'home_game': bool(row['home_game']) if pd.notna(row['home_game']) else None,
                'margin_of_victory': int(row['margin_of_victory']) if pd.notna(row['margin_of_victory']) else None,
                'blowout_level': blowout_level,
                'blowout_description': self.get_blowout_description(blowout_level),
                
                # Prop betting data
                'points_line': float(row['points_line']) if pd.notna(row['points_line']) else None,
                'over_under_result': over_under_result,
                'margin': float(margin) if margin is not None else None,
                
                # Player status
                'player_status': row['player_status'],
                'injury_status': row['injury_status'],
                'is_active': row['player_status'] == 'active',
                
                # Data quality
                'validation_bdl_points_match': (
                    abs(row['points'] - row['bdl_points']) <= 1 
                    if pd.notna(row['bdl_points']) and pd.notna(row['points']) else None
                ),
                
                # Processing metadata
                'processed_at': datetime.now(timezone.utc).isoformat()
            }
            
            records.append(record)
        
        self.transformed_data = records
        logger.info(f"Calculated analytics for {len(records)} player-game records")
    
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
        """Return analytics-specific stats."""
        if not self.transformed_data:
            return {}
            
        stats = {
            'records_processed': len(self.transformed_data),
            'active_players': sum(1 for r in self.transformed_data if r['is_active']),
            'games_with_props': sum(1 for r in self.transformed_data if r['points_line'] is not None),
            'blowout_games': sum(1 for r in self.transformed_data if r['blowout_level'] >= 4)
        }
        
        return stats