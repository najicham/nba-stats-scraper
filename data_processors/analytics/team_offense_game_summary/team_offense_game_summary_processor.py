#!/usr/bin/env python3
"""
File: analytics_processors/team_offense_game_summary/team_offense_game_summary_processor.py

Team Offense Game Summary Processor for NBA Props Platform Analytics.
Aggregates player performance data into team-level offensive metrics.

Depends on player_game_summary being populated first.
Processes team offensive stats, advanced metrics, and game context.
"""

import logging
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List
from data_processors.analytics.analytics_base import AnalyticsProcessorBase

logger = logging.getLogger(__name__)


class TeamOffenseGameSummaryProcessor(AnalyticsProcessorBase):
    """Process team offensive game summary analytics from player game summaries."""
    
    def __init__(self):
        super().__init__()
        self.table_name = 'team_offense_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'
    
    def extract_raw_data(self) -> None:
        """Extract team offensive data by aggregating player summaries."""
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']
        
        query = f"""
        WITH team_aggregates AS (
            SELECT 
                game_id,
                game_date,
                season_year,
                team_abbr,
                opponent_team_abbr,
                
                -- Aggregate team offensive stats
                SUM(CASE WHEN is_active THEN points ELSE 0 END) as points_scored,
                SUM(CASE WHEN is_active THEN fg_makes ELSE 0 END) as fg_makes,
                SUM(CASE WHEN is_active THEN fg_attempts ELSE 0 END) as fg_attempts,
                SUM(CASE WHEN is_active THEN three_pt_makes ELSE 0 END) as three_pt_makes,
                SUM(CASE WHEN is_active THEN three_pt_attempts ELSE 0 END) as three_pt_attempts,
                SUM(CASE WHEN is_active THEN ft_makes ELSE 0 END) as ft_makes,
                SUM(CASE WHEN is_active THEN ft_attempts ELSE 0 END) as ft_attempts,
                SUM(CASE WHEN is_active THEN offensive_rebounds ELSE 0 END) as offensive_rebounds,
                SUM(CASE WHEN is_active THEN defensive_rebounds ELSE 0 END) as defensive_rebounds,
                SUM(CASE WHEN is_active THEN assists ELSE 0 END) as assists,
                SUM(CASE WHEN is_active THEN turnovers ELSE 0 END) as turnovers,
                SUM(CASE WHEN is_active THEN personal_fouls ELSE 0 END) as personal_fouls,
                
                -- Game context - determine if team was home
                MAX(CASE WHEN team_abbr = SPLIT(game_id, '_')[OFFSET(2)] THEN TRUE ELSE FALSE END) as home_game,
                
                -- Data quality tracking
                COUNT(CASE WHEN is_active THEN 1 END) as active_players_count,
                COUNT(CASE WHEN data_quality_tier = 'high' THEN 1 END) as high_quality_players,
                STRING_AGG(DISTINCT primary_source_used) as sources_used
                
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND is_active = TRUE
            GROUP BY game_id, game_date, season_year, team_abbr, opponent_team_abbr
        ),
        
        -- Add game context and enhanced metrics
        with_game_results AS (
            SELECT 
                ta.*,
                -- Placeholder for win/loss - would need actual game scores
                NULL as margin_of_victory,
                NULL as win_flag,
                0 as overtime_periods,  -- Default
                
                -- Team situation context (would need injury data integration)
                0 as players_inactive,
                0 as starters_inactive,
                
                -- Enhanced efficiency calculations
                CASE 
                    WHEN ta.fg_attempts > 0 THEN 
                        ROUND((ta.fg_makes + 0.5 * ta.three_pt_makes) / ta.fg_attempts, 3)
                    ELSE NULL 
                END as efg_pct,
                
                CASE 
                    WHEN (ta.fg_attempts + 0.44 * ta.ft_attempts) > 0 THEN
                        ROUND(ta.points_scored / (2 * (ta.fg_attempts + 0.44 * ta.ft_attempts)), 3)
                    ELSE NULL
                END as ts_pct,
                
                -- Estimated possessions (simplified formula)
                GREATEST(0, ta.fg_attempts + 0.44 * ta.ft_attempts + ta.turnovers - COALESCE(ta.offensive_rebounds, 0)) as possessions,
                
                -- Total rebounds calculation
                COALESCE(ta.offensive_rebounds, 0) + COALESCE(ta.defensive_rebounds, 0) as rebounds
                
            FROM team_aggregates ta
        )
        
        SELECT 
            wgr.*,
            -- Advanced team metrics
            CASE 
                WHEN possessions > 0 THEN ROUND(points_scored * 100.0 / possessions, 2)
                ELSE NULL
            END as offensive_rating,
            
            -- Pace estimation (simplified - would be more accurate with actual game time)
            ROUND(possessions * 48.0 / 48.0, 1) as pace,  -- Placeholder for now
            
            -- Shot zone metrics (deferred for now)
            NULL as team_paint_attempts,
            NULL as team_paint_makes,
            NULL as team_mid_range_attempts, 
            NULL as team_mid_range_makes,
            NULL as points_in_paint_scored,
            NULL as second_chance_points_scored,
            
            -- Referee context (would need separate integration)
            NULL as referee_crew_id
            
        FROM with_game_results wgr
        ORDER BY game_date DESC, game_id
        """
        
        logger.info(f"Extracting team offensive data for {start_date} to {end_date}")
        self.raw_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.raw_data)} team-game offensive records")
    
    def validate_extracted_data(self) -> None:
        """Enhanced validation for team offensive data."""
        super().validate_extracted_data()
        
        if self.raw_data.empty:
            raise ValueError("No team offensive data extracted for date range")
        
        # Check for reasonable team totals
        unrealistic_scores = self.raw_data[
            (self.raw_data['points_scored'].notna()) & 
            ((self.raw_data['points_scored'] < 50) | (self.raw_data['points_scored'] > 200))
        ]
        
        if not unrealistic_scores.empty:
            for _, row in unrealistic_scores.iterrows():
                self.log_quality_issue(
                    issue_type='unrealistic_team_score',
                    severity='high',
                    identifier=f"{row['game_id']}_{row['team_abbr']}",
                    details={
                        'points_scored': int(row['points_scored']),
                        'active_players': int(row['active_players_count'])
                    }
                )
    
    def calculate_analytics(self) -> None:
        """Transform team aggregates to final analytics format."""
        records = []
        
        for _, row in self.raw_data.iterrows():
            try:
                record = {
                    # Core identifiers
                    'game_id': row['game_id'],
                    'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                    'team_abbr': row['team_abbr'],
                    'opponent_team_abbr': row['opponent_team_abbr'],
                    'season_year': int(row['season_year']) if pd.notna(row['season_year']) else None,
                    
                    # Basic offensive stats
                    'points_scored': int(row['points_scored']) if pd.notna(row['points_scored']) else None,
                    'fg_attempts': int(row['fg_attempts']) if pd.notna(row['fg_attempts']) else None,
                    'fg_makes': int(row['fg_makes']) if pd.notna(row['fg_makes']) else None,
                    'three_pt_attempts': int(row['three_pt_attempts']) if pd.notna(row['three_pt_attempts']) else None,
                    'three_pt_makes': int(row['three_pt_makes']) if pd.notna(row['three_pt_makes']) else None,
                    'ft_attempts': int(row['ft_attempts']) if pd.notna(row['ft_attempts']) else None,
                    'ft_makes': int(row['ft_makes']) if pd.notna(row['ft_makes']) else None,
                    'rebounds': int(row['rebounds']) if pd.notna(row['rebounds']) else None,
                    'assists': int(row['assists']) if pd.notna(row['assists']) else None,
                    'turnovers': int(row['turnovers']) if pd.notna(row['turnovers']) else None,
                    'personal_fouls': int(row['personal_fouls']) if pd.notna(row['personal_fouls']) else None,
                    
                    # Team shot zone performance (deferred)
                    'team_paint_attempts': None,
                    'team_paint_makes': None,
                    'team_mid_range_attempts': None,
                    'team_mid_range_makes': None,
                    'points_in_paint_scored': None,
                    'second_chance_points_scored': None,
                    
                    # Advanced offensive metrics
                    'offensive_rating': float(row['offensive_rating']) if pd.notna(row['offensive_rating']) else None,
                    'pace': float(row['pace']) if pd.notna(row['pace']) else None,
                    'possessions': int(row['possessions']) if pd.notna(row['possessions']) else None,
                    'ts_pct': float(row['ts_pct']) if pd.notna(row['ts_pct']) else None,
                    
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
                    'data_quality_tier': 'high' if row['high_quality_players'] >= row['active_players_count'] * 0.8 else 'medium',
                    'primary_source_used': row['sources_used'],
                    'processed_with_issues': False,
                    
                    # Processing metadata
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                
                records.append(record)
                
            except Exception as e:
                logger.error(f"Error processing team offensive record {row['game_id']}_{row['team_abbr']}: {e}")
                self.log_quality_issue(
                    issue_type='processing_error',
                    severity='medium',
                    identifier=f"{row['game_id']}_{row['team_abbr']}",
                    details={'error': str(e)}
                )
                continue
        
        self.transformed_data = records
        logger.info(f"Calculated team offensive analytics for {len(records)} team-game records")
    
    def get_analytics_stats(self) -> Dict:
        """Return team offensive analytics stats."""
        if not self.transformed_data:
            return {}
            
        stats = {
            'records_processed': len(self.transformed_data),
            'avg_team_points': round(sum(r['points_scored'] for r in self.transformed_data if r['points_scored']) / 
                                   len([r for r in self.transformed_data if r['points_scored']]), 1) if any(r['points_scored'] for r in self.transformed_data) else 0,
            'total_assists': sum(r['assists'] for r in self.transformed_data if r['assists']),
            'total_turnovers': sum(r['turnovers'] for r in self.transformed_data if r['turnovers']),
            'home_games': sum(1 for r in self.transformed_data if r['home_game']),
            'road_games': sum(1 for r in self.transformed_data if not r['home_game']),
            'high_quality_records': sum(1 for r in self.transformed_data if r['data_quality_tier'] == 'high')
        }
        
        return stats