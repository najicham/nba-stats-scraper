#!/usr/bin/env python3
"""
File: analytics_processors/player_game_summary/player_game_summary_processor.py

Complete Historical Game Data Processor for NBA Props Platform.
Transforms raw gamebook, box scores, and props data into analytics tables.

Features:
- NBA.com → BDL fallback with data quality tracking
- Proper minutes parsing ("40:11" → 40.18)
- Travel distance integration 
- Prop outcome calculation with margin analysis
- Cross-source validation and error handling
- Team aggregation for offense/defense summaries
"""

import logging
import pandas as pd
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from analytics_processors.analytics_base import AnalyticsProcessorBase
from analytics_processors.utils.travel_utils import quick_distance_lookup, get_game_travel_context

logger = logging.getLogger(__name__)


class PlayerGameSummaryProcessor(AnalyticsProcessorBase):
    """Process player game summary analytics from raw data tables."""
    
    def __init__(self):
        super().__init__()
        self.table_name = 'player_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'
        
    def parse_minutes_to_decimal(self, minutes_str: str) -> Optional[float]:
        """Parse minutes string to decimal format."""
        if not minutes_str or minutes_str == '-':
            return None
            
        try:
            # Handle "40:11" format
            if ':' in minutes_str:
                parts = minutes_str.split(':')
                if len(parts) == 2:
                    mins = int(parts[0])
                    secs = int(parts[1])
                    return round(mins + (secs / 60), 2)
            
            # Handle simple integer format "40"
            return float(minutes_str)
            
        except (ValueError, TypeError):
            logger.warning(f"Could not parse minutes: {minutes_str}")
            return None
    
    def parse_plus_minus(self, plus_minus_str: str) -> Optional[int]:
        """Parse plus/minus string to integer."""
        if not plus_minus_str or plus_minus_str == '-':
            return None
            
        try:
            # Handle "+7" or "-14" format
            cleaned = plus_minus_str.replace('+', '')
            return int(cleaned)
        except (ValueError, TypeError):
            logger.warning(f"Could not parse plus/minus: {plus_minus_str}")
            return None
    
    def extract_raw_data(self) -> None:
        """Query raw BigQuery tables with NBA.com → BDL fallback logic."""
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']
        
        query = f"""
        WITH nba_com_data AS (
            SELECT 
                game_id,
                game_date,
                season_year,
                player_lookup,
                player_name as player_full_name,
                team_abbr,
                player_status,
                
                -- Core stats
                points,
                assists, 
                total_rebounds,
                offensive_rebounds,
                defensive_rebounds,
                steals,
                blocks,
                turnovers,
                personal_fouls,
                
                -- Shooting stats
                field_goals_made,
                field_goals_attempted,
                three_pointers_made,
                three_pointers_attempted,
                free_throws_made,
                free_throws_attempted,
                
                -- Game context
                minutes,
                plus_minus,
                
                -- Data quality
                'nbac_gamebook' as primary_source,
                TRUE as has_nba_com_data,
                FALSE as has_bdl_data
                
            FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND player_status = 'active'
        ),
        
        bdl_data AS (
            SELECT 
                game_id,
                game_date,
                season_year,
                player_lookup,
                player_full_name,
                team_abbr,
                'active' as player_status,
                
                -- Core stats  
                points,
                assists,
                rebounds as total_rebounds,
                NULL as offensive_rebounds,
                NULL as defensive_rebounds,
                steals,
                blocks,
                turnovers,
                personal_fouls,
                
                -- Shooting stats
                field_goals_made,
                NULL as field_goals_attempted,  -- Not available in BDL
                three_pointers_made,
                NULL as three_pointers_attempted,
                free_throws_made,
                NULL as free_throws_attempted,
                
                -- Game context
                minutes,
                NULL as plus_minus,  -- Not available in BDL
                
                -- Data quality
                'bdl_boxscores' as primary_source,
                FALSE as has_nba_com_data,
                TRUE as has_bdl_data
                
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`  
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),
        
        -- Combine with NBA.com priority
        combined_data AS (
            SELECT * FROM nba_com_data
            
            UNION ALL
            
            SELECT * FROM bdl_data
            WHERE game_id NOT IN (SELECT DISTINCT game_id FROM nba_com_data)
        ),
        
        -- Add props context
        with_props AS (
            SELECT 
                c.*,
                p.points_line,
                p.over_price_american,
                p.under_price_american,
                p.bookmaker as points_line_source
            FROM combined_data c
            LEFT JOIN `{self.project_id}.nba_raw.odds_api_player_points_props` p
                ON c.game_id = p.game_id 
                AND c.player_lookup = p.player_lookup
        ),
        
        -- Add opponent context
        games_context AS (
            SELECT DISTINCT
                game_id,
                game_date,
                CASE 
                    WHEN game_id LIKE '%_%_%' THEN
                        SPLIT(game_id, '_')[OFFSET(1)]  -- Away team (middle)
                    ELSE NULL
                END as away_team_abbr,
                CASE 
                    WHEN game_id LIKE '%_%_%' THEN  
                        SPLIT(game_id, '_')[OFFSET(2)]  -- Home team (last)
                    ELSE NULL
                END as home_team_abbr
            FROM combined_data
        )
        
        SELECT 
            wp.*,
            gc.away_team_abbr,
            gc.home_team_abbr,
            CASE 
                WHEN wp.team_abbr = gc.home_team_abbr THEN gc.away_team_abbr
                ELSE gc.home_team_abbr  
            END as opponent_team_abbr,
            CASE 
                WHEN wp.team_abbr = gc.home_team_abbr THEN TRUE
                ELSE FALSE
            END as home_game
            
        FROM with_props wp
        LEFT JOIN games_context gc ON wp.game_id = gc.game_id
        ORDER BY wp.game_date DESC, wp.game_id, wp.player_lookup
        """
        
        logger.info(f"Extracting data for {start_date} to {end_date}")
        self.raw_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.raw_data)} player-game records")
        
        # Log data source breakdown
        if not self.raw_data.empty:
            source_counts = self.raw_data['primary_source'].value_counts()
            logger.info(f"Data sources: {dict(source_counts)}")
    
    def validate_extracted_data(self) -> None:
        """Enhanced validation with cross-source quality checks."""
        super().validate_extracted_data()
        
        if self.raw_data.empty:
            raise ValueError("No data extracted for date range")
        
        # Check for missing critical fields
        critical_fields = ['game_id', 'player_lookup', 'points']
        missing_critical = []
        
        for field in critical_fields:
            null_count = self.raw_data[field].isnull().sum()
            if null_count > 0:
                missing_critical.append(f"{field}: {null_count} nulls")
        
        if missing_critical:
            self.log_quality_issue(
                issue_type='missing_critical_data',
                severity='high',
                identifier=f"date_range_{self.opts['start_date']}_{self.opts['end_date']}",
                details={'missing_fields': missing_critical}
            )
        
        # Log data quality summary
        total_records = len(self.raw_data)
        nba_com_records = (self.raw_data['primary_source'] == 'nbac_gamebook').sum()
        bdl_records = (self.raw_data['primary_source'] == 'bdl_boxscores').sum()
        
        logger.info(f"Data quality: {nba_com_records}/{total_records} from NBA.com "
                   f"({nba_com_records/total_records*100:.1f}%)")
    
    def get_team_last_game_location(self, team_abbr: str, current_game_date: str) -> Optional[str]:
        """Get team's previous game location for travel calculation."""
        try:
            # Query for team's previous game
            query = f"""
            SELECT opponent_team_abbr, home_game
            FROM `{self.project_id}.nba_analytics.{self.table_name}`
            WHERE team_abbr = '{team_abbr}' 
                AND game_date < '{current_game_date}'
            ORDER BY game_date DESC
            LIMIT 1
            """
            
            result = self.bq_client.query(query).to_dataframe()
            if not result.empty:
                row = result.iloc[0]
                # If they were home, they were at their own location
                if row['home_game']:
                    return team_abbr
                else:
                    return row['opponent_team_abbr']
                    
        except Exception as e:
            logger.warning(f"Could not get last game location for {team_abbr}: {e}")
            
        return None
    
    def calculate_analytics(self) -> None:
        """Calculate analytics metrics with travel integration."""
        records = []
        
        for _, row in self.raw_data.iterrows():
            try:
                # Parse minutes to decimal
                minutes_decimal = self.parse_minutes_to_decimal(row['minutes'])
                
                # Parse plus/minus  
                plus_minus_int = self.parse_plus_minus(str(row['plus_minus']))
                
                # Calculate prop outcome
                over_under_result = None
                margin = None
                if pd.notna(row['points']) and pd.notna(row['points_line']):
                    if row['points'] > row['points_line']:
                        over_under_result = 'OVER'
                    else:
                        over_under_result = 'UNDER'
                    margin = float(row['points']) - float(row['points_line'])
                
                # Calculate travel distance
                travel_miles = 0
                time_zone_changes = 0
                if pd.notna(row['away_team_abbr']) and pd.notna(row['home_team_abbr']):
                    # For away team, calculate travel from last game
                    if not row['home_game']:  # Player is on away team
                        last_location = self.get_team_last_game_location(
                            row['team_abbr'], row['game_date']
                        )
                        if last_location:
                            travel_miles = quick_distance_lookup(last_location, row['home_team_abbr'])
                            # Simplified time zone calculation (could be enhanced)
                            time_zone_changes = max(0, travel_miles // 1000)  # Rough estimate
                
                # Enhanced efficiency calculations
                ts_pct = None
                efg_pct = None  
                usage_rate = None  # Complex calculation, defer for now
                
                if (pd.notna(row['field_goals_attempted']) and 
                    pd.notna(row['three_pointers_made']) and 
                    pd.notna(row['free_throws_attempted'])):
                    
                    fga = row['field_goals_attempted'] 
                    threes = row['three_pointers_made'] or 0
                    fta = row['free_throws_attempted']
                    
                    if fga > 0:
                        # Effective Field Goal %
                        efg_pct = (row['field_goals_made'] + 0.5 * threes) / fga
                        
                        # True Shooting % (approximation)  
                        total_shots = fga + 0.44 * fta
                        if total_shots > 0:
                            ts_pct = row['points'] / (2 * total_shots)
                
                # Build analytics record
                record = {
                    # Core identifiers
                    'player_lookup': row['player_lookup'],
                    'player_full_name': row['player_full_name'],
                    'game_id': row['game_id'],
                    'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                    'team_abbr': row['team_abbr'], 
                    'opponent_team_abbr': row['opponent_team_abbr'],
                    'season_year': int(row['season_year']) if pd.notna(row['season_year']) else None,
                    
                    # Basic performance stats
                    'points': int(row['points']) if pd.notna(row['points']) else None,
                    'minutes_played': minutes_decimal,
                    'assists': int(row['assists']) if pd.notna(row['assists']) else None,
                    'offensive_rebounds': int(row['offensive_rebounds']) if pd.notna(row['offensive_rebounds']) else None,
                    'defensive_rebounds': int(row['defensive_rebounds']) if pd.notna(row['defensive_rebounds']) else None,
                    'steals': int(row['steals']) if pd.notna(row['steals']) else None,
                    'blocks': int(row['blocks']) if pd.notna(row['blocks']) else None,
                    'turnovers': int(row['turnovers']) if pd.notna(row['turnovers']) else None,
                    'personal_fouls': int(row['personal_fouls']) if pd.notna(row['personal_fouls']) else None,
                    'plus_minus': plus_minus_int,
                    
                    # Shooting stats
                    'fg_attempts': int(row['field_goals_attempted']) if pd.notna(row['field_goals_attempted']) else None,
                    'fg_makes': int(row['field_goals_made']) if pd.notna(row['field_goals_made']) else None,
                    'three_pt_attempts': int(row['three_pointers_attempted']) if pd.notna(row['three_pointers_attempted']) else None,
                    'three_pt_makes': int(row['three_pointers_made']) if pd.notna(row['three_pointers_made']) else None,
                    'ft_attempts': int(row['free_throws_attempted']) if pd.notna(row['free_throws_attempted']) else None,
                    'ft_makes': int(row['free_throws_made']) if pd.notna(row['free_throws_made']) else None,
                    
                    # Shot zone performance - defer for now
                    'paint_attempts': None,
                    'paint_makes': None, 
                    'mid_range_attempts': None,
                    'mid_range_makes': None,
                    'paint_blocks': None,
                    'mid_range_blocks': None,
                    'three_pt_blocks': None,
                    'and1_count': None,
                    
                    # Shot creation analysis - defer
                    'assisted_fg_makes': None,
                    'unassisted_fg_makes': None,
                    
                    # Advanced efficiency
                    'usage_rate': usage_rate,
                    'ts_pct': round(ts_pct, 3) if ts_pct else None,
                    'efg_pct': round(efg_pct, 3) if efg_pct else None,
                    'starter_flag': minutes_decimal and minutes_decimal > 20,  # Rough estimate
                    'win_flag': None,  # Need game results to determine
                    
                    # Prop betting results
                    'points_line': float(row['points_line']) if pd.notna(row['points_line']) else None,
                    'over_under_result': over_under_result,
                    'margin': round(margin, 2) if margin is not None else None,
                    'opening_line': None,  # Need historical props data
                    'line_movement': None,
                    'points_line_source': row['points_line_source'],
                    'opening_line_source': None,
                    
                    # Player availability
                    'is_active': row['player_status'] == 'active',
                    'player_status': row['player_status'],
                    
                    # Travel context  
                    'travel_miles': travel_miles,
                    'time_zone_changes': time_zone_changes,
                    
                    # Data quality
                    'data_quality_tier': 'high' if row['primary_source'] == 'nbac_gamebook' else 'medium',
                    'primary_source_used': row['primary_source'],
                    'processed_with_issues': False,  # Enhanced later
                    
                    # Processing metadata
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                
                records.append(record)
                
            except Exception as e:
                logger.error(f"Error processing record {row['game_id']}_{row['player_lookup']}: {e}")
                self.log_quality_issue(
                    issue_type='processing_error',
                    severity='medium',
                    identifier=f"{row['game_id']}_{row['player_lookup']}",
                    details={'error': str(e)}
                )
                continue
        
        self.transformed_data = records
        logger.info(f"Calculated analytics for {len(records)} player-game records")
    
    def get_analytics_stats(self) -> Dict:
        """Return analytics-specific stats."""
        if not self.transformed_data:
            return {}
            
        stats = {
            'records_processed': len(self.transformed_data),
            'active_players': sum(1 for r in self.transformed_data if r['is_active']),
            'games_with_props': sum(1 for r in self.transformed_data if r['points_line'] is not None),
            'prop_overs': sum(1 for r in self.transformed_data if r['over_under_result'] == 'OVER'),
            'prop_unders': sum(1 for r in self.transformed_data if r['over_under_result'] == 'UNDER'),
            'high_quality_records': sum(1 for r in self.transformed_data if r['data_quality_tier'] == 'high'),
            'avg_points': round(sum(r['points'] for r in self.transformed_data if r['points']) / 
                              len([r for r in self.transformed_data if r['points']]), 1) if any(r['points'] for r in self.transformed_data) else 0,
            'travel_games': sum(1 for r in self.transformed_data if r['travel_miles'] and r['travel_miles'] > 0)
        }
        
        return stats