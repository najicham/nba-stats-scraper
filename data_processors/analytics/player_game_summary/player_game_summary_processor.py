#!/usr/bin/env python3
"""
File: analytics_processors/player_game_summary/player_game_summary_processor.py

Complete Historical Game Data Processor for NBA Props Platform.
Transforms raw gamebook, box scores, and props data into analytics tables.

Features:
- NBA.com → BDL fallback with data quality tracking
- Proper minutes parsing ("40:11" → 40.18) and conversion to integer
- Data type cleaning to prevent validation errors
- Prop outcome calculation with margin analysis
- Cross-source validation and error handling
- Schema-compliant output for BigQuery insertion
- Multi-channel notifications for critical failures and data quality issues
"""

import logging
import pandas as pd
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from data_processors.analytics.analytics_base import AnalyticsProcessorBase
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

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
        
        try:
            self.raw_data = self.bq_client.query(query).to_dataframe()
            logger.info(f"Extracted {len(self.raw_data)} player-game records")
            
            # Log data source breakdown
            if not self.raw_data.empty:
                source_counts = self.raw_data['primary_source'].value_counts()
                logger.info(f"Data sources: {dict(source_counts)}")
            else:
                # Notify if no data extracted
                logger.warning(f"No data extracted for date range {start_date} to {end_date}")
                try:
                    notify_warning(
                        title="Player Game Summary: No Data Extracted",
                        message=f"No player-game records found for {start_date} to {end_date}",
                        details={
                            'processor': 'player_game_summary',
                            'start_date': start_date,
                            'end_date': end_date,
                            'possible_causes': ['no games scheduled', 'upstream scraper failure', 'data not yet available']
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                    
        except Exception as e:
            logger.error(f"BigQuery extraction failed: {e}")
            try:
                notify_error(
                    title="Player Game Summary: Data Extraction Failed",
                    message=f"Failed to extract player-game data from BigQuery: {str(e)}",
                    details={
                        'processor': 'player_game_summary',
                        'start_date': start_date,
                        'end_date': end_date,
                        'error_type': type(e).__name__
                    },
                    processor_name="Player Game Summary Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    def clean_numeric_columns(self) -> None:
        """Ensure numeric columns have consistent data types before validation."""
        numeric_columns = [
            'points', 'assists', 'minutes', 'field_goals_made', 'field_goals_attempted',
            'three_pointers_made', 'three_pointers_attempted', 'free_throws_made', 
            'free_throws_attempted', 'steals', 'blocks', 'turnovers', 'personal_fouls',
            'total_rebounds', 'offensive_rebounds', 'defensive_rebounds', 'season_year'
        ]
        
        for col in numeric_columns:
            if col in self.raw_data.columns:
                # Convert to numeric, errors='coerce' turns invalid values to NaN
                self.raw_data[col] = pd.to_numeric(self.raw_data[col], errors='coerce')
        
        # Handle plus_minus separately (can have '+' prefix)
        if 'plus_minus' in self.raw_data.columns:
            # Remove '+' prefix and convert to numeric
            self.raw_data['plus_minus'] = self.raw_data['plus_minus'].astype(str).str.replace('+', '')
            self.raw_data['plus_minus'] = pd.to_numeric(self.raw_data['plus_minus'], errors='coerce')
        
        logger.info("Cleaned numeric column data types")
    
    def validate_extracted_data(self) -> None:
        """Enhanced validation with cross-source quality checks."""
        super().validate_extracted_data()
        
        if self.raw_data.empty:
            error_msg = "No data extracted for date range"
            logger.error(error_msg)
            try:
                notify_error(
                    title="Player Game Summary: Validation Failed",
                    message=error_msg,
                    details={
                        'processor': 'player_game_summary',
                        'start_date': self.opts['start_date'],
                        'end_date': self.opts['end_date']
                    },
                    processor_name="Player Game Summary Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise ValueError(error_msg)
        
        # Clean data types before validation to prevent comparison errors
        self.clean_numeric_columns()
        
        # Run comprehensive validation suite
        self.validate_critical_fields()
        self.validate_player_data()
        self.validate_statistical_integrity()
        self.cross_validate_data_sources()
        self.validate_team_assignments()
        
        # Summary validation report
        self.generate_validation_summary()
        
        # Check if we have high severity issues and notify
        high_severity_issues = sum(1 for issue in getattr(self, 'quality_issues', []) 
                                   if issue.get('severity') == 'high')
        
        if high_severity_issues > 0:
            try:
                notify_warning(
                    title="Player Game Summary: Data Quality Issues Detected",
                    message=f"Found {high_severity_issues} high-severity data quality issues during validation",
                    details={
                        'processor': 'player_game_summary',
                        'high_severity_count': high_severity_issues,
                        'total_records': len(self.raw_data),
                        'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                        'action': 'Check logs for detailed validation results'
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

    def validate_critical_fields(self) -> None:
        """Check for missing critical fields that would break processing."""
        critical_fields = ['game_id', 'player_lookup', 'points', 'team_abbr']
        validation_issues = []
        
        for field in critical_fields:
            null_count = self.raw_data[field].isnull().sum()
            if null_count > 0:
                issue_details = {
                    'field': field,
                    'null_count': null_count,
                    'total_records': len(self.raw_data),
                    'null_percentage': round(null_count / len(self.raw_data) * 100, 2)
                }
                
                severity = 'high' if null_count > len(self.raw_data) * 0.1 else 'medium'
                
                self.log_quality_issue(
                    issue_type='missing_critical_data',
                    severity=severity,
                    identifier=f"{field}_nulls_{self.opts['start_date']}",
                    details=issue_details
                )
                validation_issues.append(f"{field}: {null_count} nulls ({issue_details['null_percentage']}%)")
        
        if validation_issues:
            logger.warning(f"Critical field issues: {'; '.join(validation_issues)}")

    def validate_player_data(self) -> None:
        """Validate player names, lookups, and identify problematic records."""
        
        # Check for very short player lookups (likely incomplete names)
        short_lookups = self.raw_data[
            (self.raw_data['player_lookup'].str.len() < 5) & 
            (self.raw_data['player_lookup'].notna())
        ]
        
        if not short_lookups.empty:
            for _, row in short_lookups.iterrows():
                self.log_quality_issue(
                    issue_type='incomplete_player_name',
                    severity='medium',
                    identifier=f"{row['game_id']}_{row['player_lookup']}",
                    details={
                        'player_lookup': row['player_lookup'],
                        'player_name': row.get('player_full_name', 'N/A'),
                        'team': row['team_abbr'],
                        'game_id': row['game_id'],
                        'likely_cause': 'injured_player_partial_name'
                    }
                )
            
            logger.warning(f"Found {len(short_lookups)} players with suspiciously short names")
        
        # Check for duplicate player-game combinations (shouldn't happen)
        duplicates = self.raw_data.groupby(['game_id', 'player_lookup', 'primary_source']).size()
        duplicate_records = duplicates[duplicates > 1]
        
        if not duplicate_records.empty:
            for (game_id, player_lookup, source), count in duplicate_records.items():
                self.log_quality_issue(
                    issue_type='duplicate_player_game',
                    severity='high',
                    identifier=f"{game_id}_{player_lookup}_{source}",
                    details={
                        'game_id': game_id,
                        'player_lookup': player_lookup,
                        'source': source,
                        'duplicate_count': count
                    }
                )

    def validate_statistical_integrity(self) -> None:
        """Check for statistical anomalies and impossible values."""
        anomalies = []
        
        # Check for impossible negative stats
        stat_columns = ['points', 'assists', 'minutes', 'field_goals_made', 'field_goals_attempted']
        for col in stat_columns:
            if col in self.raw_data.columns:
                # Use notna() to exclude NaN values from comparison
                valid_data = self.raw_data[self.raw_data[col].notna()]
                if not valid_data.empty:
                    negative_stats = valid_data[valid_data[col] < 0]
                    if not negative_stats.empty:
                        anomalies.append(f"{col}: {len(negative_stats)} negative values")
                        
                        for _, row in negative_stats.iterrows():
                            self.log_quality_issue(
                                issue_type='impossible_statistic',
                                severity='high',
                                identifier=f"{row['game_id']}_{row['player_lookup']}_{col}",
                                details={
                                    'statistic': col,
                                    'value': row[col],
                                    'player': row['player_lookup'],
                                    'game_id': row['game_id']
                                }
                            )
        
        # Check for statistical impossibilities (FGM > FGA, etc.) - with null safety
        if 'field_goals_made' in self.raw_data.columns and 'field_goals_attempted' in self.raw_data.columns:
            valid_fg_data = self.raw_data[
                (self.raw_data['field_goals_made'].notna()) &
                (self.raw_data['field_goals_attempted'].notna())
            ]
            
            if not valid_fg_data.empty:
                impossible_fg = valid_fg_data[
                    valid_fg_data['field_goals_made'] > valid_fg_data['field_goals_attempted']
                ]
                
                if not impossible_fg.empty:
                    anomalies.append(f"FGM > FGA: {len(impossible_fg)} cases")
                    for _, row in impossible_fg.iterrows():
                        self.log_quality_issue(
                            issue_type='statistical_impossibility',
                            severity='high',
                            identifier=f"{row['game_id']}_{row['player_lookup']}_fg_impossible",
                            details={
                                'fg_made': row['field_goals_made'],
                                'fg_attempted': row['field_goals_attempted'],
                                'player': row['player_lookup'],
                                'game_id': row['game_id']
                            }
                        )
        
        # Check for extreme outliers (points > 100, minutes > 60, etc.) - with null safety
        valid_outlier_data = self.raw_data[
            (self.raw_data['points'].notna()) | 
            (self.raw_data['minutes'].notna())
        ]
        
        if not valid_outlier_data.empty:
            extreme_outliers = valid_outlier_data[
                (valid_outlier_data['points'] > 100) |
                (valid_outlier_data['minutes'] > 60)
            ]
            
            if not extreme_outliers.empty:
                for _, row in extreme_outliers.iterrows():
                    self.log_quality_issue(
                        issue_type='extreme_outlier',
                        severity='medium',
                        identifier=f"{row['game_id']}_{row['player_lookup']}_outlier",
                        details={
                            'points': row['points'],
                            'minutes': row.get('minutes', 'N/A'),
                            'player': row['player_lookup'],
                            'game_id': row['game_id'],
                            'note': 'May be legitimate but worth review'
                        }
                    )
        
        if anomalies:
            logger.warning(f"Statistical anomalies found: {'; '.join(anomalies)}")

    def cross_validate_data_sources(self) -> None:
        """Compare NBA.com and BDL data for overlapping games."""
        
        # Find games that exist in both sources
        nba_games = set(self.raw_data[self.raw_data['primary_source'] == 'nbac_gamebook']['game_id'])
        bdl_games = set(self.raw_data[self.raw_data['primary_source'] == 'bdl_boxscores']['game_id'])
        overlapping_games = nba_games.intersection(bdl_games)
        
        if overlapping_games:
            logger.info(f"Found {len(overlapping_games)} games with both NBA.com and BDL data")
            
            # For overlapping games, compare key stats
            for game_id in list(overlapping_games)[:5]:  # Sample first 5 for validation
                nba_data = self.raw_data[
                    (self.raw_data['game_id'] == game_id) & 
                    (self.raw_data['primary_source'] == 'nbac_gamebook')
                ]
                bdl_data = self.raw_data[
                    (self.raw_data['game_id'] == game_id) & 
                    (self.raw_data['primary_source'] == 'bdl_boxscores')
                ]
                
                # Compare player counts
                nba_players = set(nba_data['player_lookup'])
                bdl_players = set(bdl_data['player_lookup'])
                
                missing_in_bdl = nba_players - bdl_players
                missing_in_nba = bdl_players - nba_players
                
                if missing_in_bdl or missing_in_nba:
                    self.log_quality_issue(
                        issue_type='source_coverage_difference',
                        severity='low',
                        identifier=f"{game_id}_coverage_diff",
                        details={
                            'game_id': game_id,
                            'nba_player_count': len(nba_players),
                            'bdl_player_count': len(bdl_players),
                            'missing_in_bdl': list(missing_in_bdl),
                            'missing_in_nba': list(missing_in_nba)
                        }
                    )

    def validate_team_assignments(self) -> None:
        """Validate player-team assignments against expected rosters."""
        
        # Check for obviously wrong team assignments (could expand with roster data)
        team_player_counts = self.raw_data.groupby(['game_id', 'team_abbr'])['player_lookup'].nunique()
        
        # Teams should have 8-15 active players per game typically
        unusual_roster_sizes = team_player_counts[(team_player_counts < 5) | (team_player_counts > 20)]
        
        if not unusual_roster_sizes.empty:
            for (game_id, team), player_count in unusual_roster_sizes.items():
                self.log_quality_issue(
                    issue_type='unusual_roster_size',
                    severity='medium',
                    identifier=f"{game_id}_{team}_roster_size",
                    details={
                        'game_id': game_id,
                        'team': team,
                        'active_player_count': player_count,
                        'expected_range': '8-15 players'
                    }
                )
        
        # Check for unknown team abbreviations
        known_teams = {
            'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
            'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
            'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
        }
        
        unknown_teams = set(self.raw_data['team_abbr']) - known_teams
        if unknown_teams:
            for team in unknown_teams:
                self.log_quality_issue(
                    issue_type='unknown_team_abbreviation',
                    severity='medium',
                    identifier=f"unknown_team_{team}",
                    details={
                        'team_abbreviation': team,
                        'record_count': len(self.raw_data[self.raw_data['team_abbr'] == team]),
                        'possible_causes': ['typo', 'historical_team', 'data_corruption']
                    }
                )

    def generate_validation_summary(self) -> None:
        """Generate comprehensive validation summary."""
        total_records = len(self.raw_data)
        nba_com_records = (self.raw_data['primary_source'] == 'nbac_gamebook').sum()
        bdl_records = (self.raw_data['primary_source'] == 'bdl_boxscores').sum()
        
        validation_summary = {
            'total_records': total_records,
            'nba_com_coverage': f"{nba_com_records}/{total_records} ({nba_com_records/total_records*100:.1f}%)",
            'bdl_coverage': f"{bdl_records}/{total_records} ({bdl_records/total_records*100:.1f}%)",
            'unique_games': self.raw_data['game_id'].nunique(),
            'unique_players': self.raw_data['player_lookup'].nunique(),
            'date_range': f"{self.raw_data['game_date'].min()} to {self.raw_data['game_date'].max()}"
        }
        
        logger.info(f"Validation Summary: {validation_summary}")
        
        # Store validation summary for monitoring
        self.stats['validation_summary'] = validation_summary

    def handle_data_quality_issues(self) -> None:
        """Apply automatic fixes for certain types of data quality issues."""
        
        # Auto-fix: Remove records with null critical fields
        critical_nulls = self.raw_data[
            self.raw_data[['game_id', 'player_lookup', 'points']].isnull().any(axis=1)
        ]
        
        if not critical_nulls.empty:
            logger.warning(f"Removing {len(critical_nulls)} records with null critical fields")
            self.raw_data = self.raw_data.dropna(subset=['game_id', 'player_lookup', 'points'])
            
            self.log_quality_issue(
                issue_type='auto_removed_critical_nulls',
                severity='medium',
                identifier=f"auto_fix_{self.opts['start_date']}",
                details={
                    'removed_count': len(critical_nulls),
                    'action': 'automatically_removed',
                    'remaining_records': len(self.raw_data)
                }
            )
        
        # Auto-fix: Cap extreme minutes values
        if 'minutes' in self.raw_data.columns:
            extreme_minutes = self.raw_data['minutes'] > 60
            if extreme_minutes.any():
                original_values = self.raw_data.loc[extreme_minutes, 'minutes'].copy()
                self.raw_data.loc[extreme_minutes, 'minutes'] = 60
                
                logger.warning(f"Capped {extreme_minutes.sum()} extreme minutes values to 60")
                
                self.log_quality_issue(
                    issue_type='auto_capped_extreme_minutes',
                    severity='low',
                    identifier=f"minutes_cap_{self.opts['start_date']}",
                    details={
                        'affected_records': extreme_minutes.sum(),
                        'action': 'capped_to_60_minutes',
                        'original_max': original_values.max()
                    }
                )
    
    def calculate_analytics(self) -> None:
        """Calculate analytics metrics with schema-compliant output."""
        records = []
        processing_errors = []
        
        for _, row in self.raw_data.iterrows():
            try:
                # Parse minutes to decimal, then convert to integer for schema compliance
                minutes_decimal = self.parse_minutes_to_decimal(row['minutes'])
                minutes_int = int(round(minutes_decimal)) if minutes_decimal else None
                
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
                
                # Build analytics record - schema compliant
                record = {
                    # Core identifiers (all required fields)
                    'player_lookup': row['player_lookup'],
                    'player_full_name': row['player_full_name'],
                    'game_id': row['game_id'],
                    'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                    'team_abbr': row['team_abbr'], 
                    'opponent_team_abbr': row['opponent_team_abbr'],
                    'season_year': int(row['season_year']) if pd.notna(row['season_year']) else None,
                    
                    # Basic performance stats
                    'points': int(row['points']) if pd.notna(row['points']) else None,
                    'minutes_played': minutes_int,  # FIXED: Now integer instead of decimal
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
                    
                    # Shot zone performance - defer for now (all set to None to match schema)
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
                    
                    # FIXED: Ensure boolean flags are always boolean, never null
                    'starter_flag': bool(minutes_decimal and minutes_decimal > 20) if minutes_decimal else False,
                    'win_flag': False,  # FIXED: Default to False instead of None (can enhance later with game results)
                    
                    # Prop betting results
                    'points_line': float(row['points_line']) if pd.notna(row['points_line']) else None,
                    'over_under_result': over_under_result,
                    'margin': round(margin, 2) if margin is not None else None,
                    'opening_line': None,  # Need historical props data
                    'line_movement': None,
                    'points_line_source': row['points_line_source'],
                    'opening_line_source': None,
                    
                    # Player availability (is_active is required boolean)
                    'is_active': bool(row['player_status'] == 'active'),
                    'player_status': row['player_status'],
                    
                    # Data quality
                    'data_quality_tier': 'high' if row['primary_source'] == 'nbac_gamebook' else 'medium',
                    'primary_source_used': row['primary_source'],
                    'processed_with_issues': False,  # Enhanced later
                    
                    # Processing metadata
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                
                records.append(record)
                
            except Exception as e:
                error_info = {
                    'game_id': row['game_id'],
                    'player_lookup': row['player_lookup'],
                    'error': str(e),
                    'error_type': type(e).__name__
                }
                processing_errors.append(error_info)
                
                logger.error(f"Error processing record {row['game_id']}_{row['player_lookup']}: {e}")
                self.log_quality_issue(
                    issue_type='processing_error',
                    severity='medium',
                    identifier=f"{row['game_id']}_{row['player_lookup']}",
                    details=error_info
                )
                continue
        
        self.transformed_data = records
        logger.info(f"Calculated analytics for {len(records)} player-game records")
        
        # Notify if processing errors exceed threshold
        if len(processing_errors) > 0:
            error_rate = len(processing_errors) / len(self.raw_data) * 100
            
            if error_rate > 5:  # More than 5% error rate
                try:
                    notify_warning(
                        title="Player Game Summary: High Processing Error Rate",
                        message=f"Failed to process {len(processing_errors)} records ({error_rate:.1f}% error rate)",
                        details={
                            'processor': 'player_game_summary',
                            'total_input_records': len(self.raw_data),
                            'processing_errors': len(processing_errors),
                            'error_rate_pct': round(error_rate, 2),
                            'successful_records': len(records),
                            'sample_errors': processing_errors[:5]
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
    
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
        }
        
        return stats
    
    def process(self) -> None:
        """Main processing method with success notification."""
        try:
            # Run the standard processing pipeline
            super().process()
            
            # Send success notification with stats
            analytics_stats = self.get_analytics_stats()
            
            try:
                notify_info(
                    title="Player Game Summary: Processing Complete",
                    message=f"Successfully processed {analytics_stats.get('records_processed', 0)} player-game records",
                    details={
                        'processor': 'player_game_summary',
                        'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                        'records_processed': analytics_stats.get('records_processed', 0),
                        'active_players': analytics_stats.get('active_players', 0),
                        'games_with_props': analytics_stats.get('games_with_props', 0),
                        'prop_outcomes': {
                            'overs': analytics_stats.get('prop_overs', 0),
                            'unders': analytics_stats.get('prop_unders', 0)
                        },
                        'data_quality': {
                            'high_quality_records': analytics_stats.get('high_quality_records', 0),
                            'avg_points': analytics_stats.get('avg_points', 0)
                        }
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send success notification: {notify_ex}")
                
        except Exception as e:
            logger.error(f"Processing failed: {e}")
            try:
                notify_error(
                    title="Player Game Summary: Processing Failed",
                    message=f"Analytics processing failed: {str(e)}",
                    details={
                        'processor': 'player_game_summary',
                        'start_date': self.opts.get('start_date'),
                        'end_date': self.opts.get('end_date'),
                        'error_type': type(e).__name__,
                        'stage': 'process_pipeline'
                    },
                    processor_name="Player Game Summary Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send error notification: {notify_ex}")
            raise