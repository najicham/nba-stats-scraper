#!/usr/bin/env python3
"""
File: analytics_processors/team_defense_game_summary/team_defense_game_summary_processor.py

Team Defense Game Summary Processor for NBA Props Platform Analytics.
Calculates team defensive metrics by analyzing opponent offensive performance.

Depends on team_offense_game_summary being populated first.
Processes defensive stats, opponent performance allowed, and defensive actions.
"""

import logging
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List
from data_processors.analytics.analytics_base import AnalyticsProcessorBase

logger = logging.getLogger(__name__)


class TeamDefenseGameSummaryProcessor(AnalyticsProcessorBase):
    """Process team defensive game summary analytics from opponent offensive stats."""
    
    def __init__(self):
        super().__init__()
        self.table_name = 'team_defense_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'
    
    def extract_raw_data(self) -> None:
        """Extract team defensive data by looking at opponent offensive performance."""
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']
        
        query = f"""
        WITH opponent_offense AS (
            -- Get what each team allowed their opponents to score
            SELECT 
                game_id,
                game_date,
                season_year,
                opponent_team_abbr as defending_team_abbr,  -- Team playing defense
                team_abbr as opponent_team_abbr,            -- Team they defended against
                
                -- Defensive stats = opponent's offensive performance
                points_scored as points_allowed,
                fg_makes as opp_fg_makes,
                fg_attempts as opp_fg_attempts,
                three_pt_makes as opp_three_pt_makes,
                three_pt_attempts as opp_three_pt_attempts,
                ft_makes as opp_ft_makes,
                ft_attempts as opp_ft_attempts,
                rebounds as opp_rebounds,
                assists as opp_assists,
                turnovers,  -- Team defense forced these turnovers
                personal_fouls as fouls_committed,  -- Defense committed these fouls
                
                -- Game context from defensive team perspective
                NOT home_game as home_game,  -- Flip perspective
                NOT COALESCE(win_flag, FALSE) as win_flag,    -- Flip perspective
                -COALESCE(margin_of_victory, 0) as margin_of_victory,  -- Flip sign
                overtime_periods,
                
                -- Advanced metrics (opponent's offensive efficiency = defensive efficiency allowed)
                offensive_rating as defensive_rating_allowed,
                pace as opponent_pace,
                ts_pct as opponent_ts_pct,
                possessions,
                
                -- Quality tracking
                data_quality_tier,
                primary_source_used
                
            FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),
        
        -- Add defensive actions from individual player stats
        defensive_actions AS (
            SELECT 
                game_id,
                opponent_team_abbr as defending_team_abbr,
                SUM(CASE WHEN is_active THEN steals ELSE 0 END) as steals,
                SUM(CASE WHEN is_active THEN blocks ELSE 0 END) as total_blocks,
                SUM(CASE WHEN is_active THEN defensive_rebounds ELSE 0 END) as defensive_rebounds,
                
                -- Placeholder for shot zone blocks (would need play-by-play)
                0 as blocks_paint,
                0 as blocks_mid_range,
                0 as blocks_three_pt
                
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND is_active = TRUE
            GROUP BY game_id, opponent_team_abbr
        )
        
        SELECT 
            oo.*,
            -- Add defensive actions
            COALESCE(da.steals, 0) as steals,
            COALESCE(da.total_blocks, 0) as blocks_total,
            COALESCE(da.defensive_rebounds, 0) as defensive_rebounds,
            COALESCE(da.blocks_paint, 0) as blocks_paint,
            COALESCE(da.blocks_mid_range, 0) as blocks_mid_range, 
            COALESCE(da.blocks_three_pt, 0) as blocks_three_pt,
            
            -- Calculate defensive rating (lower is better)
            CASE 
                WHEN oo.defensive_rating_allowed IS NOT NULL THEN 
                    ROUND(oo.defensive_rating_allowed, 2)
                ELSE NULL
            END as defensive_rating,
            
            -- Shot zone defense metrics (deferred)
            NULL as opp_paint_attempts,
            NULL as opp_paint_makes,
            NULL as opp_mid_range_attempts,
            NULL as opp_mid_range_makes,
            NULL as points_in_paint_allowed,
            NULL as second_chance_points_allowed,
            
            -- Team situation (would need injury data)
            0 as players_inactive,
            0 as starters_inactive,
            
            -- Referee context
            NULL as referee_crew_id
            
        FROM opponent_offense oo
        LEFT JOIN defensive_actions da
            ON oo.game_id = da.game_id 
            AND oo.defending_team_abbr = da.defending_team_abbr
        ORDER BY game_date DESC, game_id
        """
        
        logger.info(f"Extracting team defensive data for {start_date} to {end_date}")
        self.raw_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.raw_data)} team-game defensive records")
    
    def validate_extracted_data(self) -> None:
        """Enhanced validation for team defensive data."""
        super().validate_extracted_data()
        
        if self.raw_data.empty:
            raise ValueError("No team defensive data extracted for date range")
        
        # Check for unrealistic defensive performance
        unrealistic_defense = self.raw_data[
            (self.raw_data['points_allowed'].notna()) & 
            ((self.raw_data['points_allowed'] < 50) | (self.raw_data['points_allowed'] > 200))
        ]
        
        if not unrealistic_defense.empty:
            for _, row in unrealistic_defense.iterrows():
                self.log_quality_issue(
                    issue_type='unrealistic_points_allowed',
                    severity='high',
                    identifier=f"{row['game_id']}_{row['defending_team_abbr']}",
                    details={
                        'points_allowed': int(row['points_allowed']),
                        'opponent': row['opponent_team_abbr']
                    }
                )
        
        # Check for missing defensive actions data
        missing_actions = self.raw_data[
            (self.raw_data['steals'].isnull()) | (self.raw_data['blocks_total'].isnull())
        ]
        
        if not missing_actions.empty:
            logger.warning(f"Found {len(missing_actions)} records with missing defensive actions data")
    
    def calculate_analytics(self) -> None:
        """Transform defensive data to final analytics format."""
        records = []
        
        for _, row in self.raw_data.iterrows():
            try:
                # Calculate turnovers forced (opponent turnovers = defense forced them)
                turnovers_forced = int(row['turnovers']) if pd.notna(row['turnovers']) else 0
                
                record = {
                    # Core identifiers
                    'game_id': row['game_id'],
                    'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                    'defending_team_abbr': row['defending_team_abbr'],
                    'opponent_team_abbr': row['opponent_team_abbr'],
                    'season_year': int(row['season_year']) if pd.notna(row['season_year']) else None,
                    
                    # Defensive stats (opponent performance allowed)
                    'points_allowed': int(row['points_allowed']) if pd.notna(row['points_allowed']) else None,
                    'opp_fg_attempts': int(row['opp_fg_attempts']) if pd.notna(row['opp_fg_attempts']) else None,
                    'opp_fg_makes': int(row['opp_fg_makes']) if pd.notna(row['opp_fg_makes']) else None,
                    'opp_three_pt_attempts': int(row['opp_three_pt_attempts']) if pd.notna(row['opp_three_pt_attempts']) else None,
                    'opp_three_pt_makes': int(row['opp_three_pt_makes']) if pd.notna(row['opp_three_pt_makes']) else None,
                    'opp_ft_attempts': int(row['opp_ft_attempts']) if pd.notna(row['opp_ft_attempts']) else None,
                    'opp_ft_makes': int(row['opp_ft_makes']) if pd.notna(row['opp_ft_makes']) else None,
                    'opp_rebounds': int(row['opp_rebounds']) if pd.notna(row['opp_rebounds']) else None,
                    'opp_assists': int(row['opp_assists']) if pd.notna(row['opp_assists']) else None,
                    'turnovers_forced': turnovers_forced,
                    'fouls_committed': int(row['fouls_committed']) if pd.notna(row['fouls_committed']) else None,
                    
                    # Defensive shot zone performance (deferred)
                    'opp_paint_attempts': None,
                    'opp_paint_makes': None,
                    'opp_mid_range_attempts': None,
                    'opp_mid_range_makes': None,
                    'points_in_paint_allowed': None,
                    'second_chance_points_allowed': None,
                    
                    # Defensive actions
                    'blocks_paint': int(row['blocks_paint']) if pd.notna(row['blocks_paint']) else 0,
                    'blocks_mid_range': int(row['blocks_mid_range']) if pd.notna(row['blocks_mid_range']) else 0,
                    'blocks_three_pt': int(row['blocks_three_pt']) if pd.notna(row['blocks_three_pt']) else 0,
                    'steals': int(row['steals']) if pd.notna(row['steals']) else None,
                    'defensive_rebounds': int(row['defensive_rebounds']) if pd.notna(row['defensive_rebounds']) else None,
                    
                    # Advanced defensive metrics
                    'defensive_rating': float(row['defensive_rating']) if pd.notna(row['defensive_rating']) else None,
                    'opponent_pace': float(row['opponent_pace']) if pd.notna(row['opponent_pace']) else None,
                    'opponent_ts_pct': float(row['opponent_ts_pct']) if pd.notna(row['opponent_ts_pct']) else None,
                    
                    # Game context
                    'home_game': bool(row['home_game']) if pd.notna(row['home_game']) else False,
                    'win_flag': bool(row['win_flag']) if pd.notna(row['win_flag']) else None,
                    'margin_of_victory': int(row['margin_of_victory']) if pd.notna(row['margin_of_victory']) else None,
                    'overtime_periods': int(row['overtime_periods']) if pd.notna(row['overtime_periods']) else 0,
                    
                    # Team situation context
                    'players_inactive': int(row['players_inactive']) if pd.notna(row['players_inactive']) else 0,
                    'starters_inactive': int(row['starters_inactive']) if pd.notna(row['starters_inactive']) else 0,
                    
                    # Referee integration
                    'referee_crew_id': row['referee_crew_id'],
                    
                    # Data quality tracking
                    'data_quality_tier': row['data_quality_tier'],
                    'primary_source_used': row['primary_source_used'],
                    'processed_with_issues': False,
                    
                    # Processing metadata
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                
                records.append(record)
                
            except Exception as e:
                logger.error(f"Error processing team defensive record {row['game_id']}_{row['defending_team_abbr']}: {e}")
                self.log_quality_issue(
                    issue_type='processing_error',
                    severity='medium',
                    identifier=f"{row['game_id']}_{row['defending_team_abbr']}",
                    details={'error': str(e)}
                )
                continue
        
        self.transformed_data = records
        logger.info(f"Calculated team defensive analytics for {len(records)} team-game records")
    
    def get_analytics_stats(self) -> Dict:
        """Return team defensive analytics stats."""
        if not self.transformed_data:
            return {}
            
        stats = {
            'records_processed': len(self.transformed_data),
            'avg_points_allowed': round(sum(r['points_allowed'] for r in self.transformed_data if r['points_allowed']) / 
                                       len([r for r in self.transformed_data if r['points_allowed']]), 1) if any(r['points_allowed'] for r in self.transformed_data) else 0,
            'total_steals': sum(r['steals'] for r in self.transformed_data if r['steals']),
            'total_blocks': sum(r['blocks_paint'] + r['blocks_mid_range'] + r['blocks_three_pt'] 
                               for r in self.transformed_data),
            'total_turnovers_forced': sum(r['turnovers_forced'] for r in self.transformed_data if r['turnovers_forced']),
            'home_games': sum(1 for r in self.transformed_data if r['home_game']),
            'road_games': sum(1 for r in self.transformed_data if not r['home_game']),
            'high_quality_records': sum(1 for r in self.transformed_data if r['data_quality_tier'] == 'high')
        }
        
        return stats