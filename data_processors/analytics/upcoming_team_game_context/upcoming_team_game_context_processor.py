#!/usr/bin/env python3
"""
File: data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py

Upcoming Team Game Context Processor - FIXED VERSION WITH DEBUG LOGGING
Calculates pregame team-level context for upcoming games including betting lines,
fatigue metrics, personnel status, momentum, and forward-looking schedule psychology.

CRITICAL FIXES APPLIED:
1. Extended date range for window functions (LAG/LEAD now work correctly)
2. Enhanced debug logging for betting lines extraction
3. Better error handling and validation

DATA SOURCES:
- nba_raw.nbac_schedule: Schedule + historical scores (81.4% coverage)
- nba_raw.odds_api_game_lines: Betting lines (timezone corrected)
- nba_raw.nbac_injury_report: Player injury status
- nba_enriched.travel_distances: Travel calculations
- nba_raw.espn_scoreboard: Fallback for game results
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery
import pandas as pd

from data_processors.analytics.analytics_base import AnalyticsProcessorBase
from data_processors.analytics.utils.travel_utils import NBATravel

logger = logging.getLogger(__name__)


class UpcomingTeamGameContextProcessor(AnalyticsProcessorBase):
    """Process upcoming team game context analytics."""
    
    # Team name to abbreviation mapping for betting lines
    TEAM_NAME_MAP = {
        'Atlanta Hawks': 'ATL',
        'Boston Celtics': 'BOS',
        'Brooklyn Nets': 'BKN',
        'Charlotte Hornets': 'CHA',
        'Chicago Bulls': 'CHI',
        'Cleveland Cavaliers': 'CLE',
        'Dallas Mavericks': 'DAL',
        'Denver Nuggets': 'DEN',
        'Detroit Pistons': 'DET',
        'Golden State Warriors': 'GSW',
        'Houston Rockets': 'HOU',
        'Indiana Pacers': 'IND',
        'LA Clippers': 'LAC',
        'Los Angeles Clippers': 'LAC',
        'Los Angeles Lakers': 'LAL',
        'Memphis Grizzlies': 'MEM',
        'Miami Heat': 'MIA',
        'Milwaukee Bucks': 'MIL',
        'Minnesota Timberwolves': 'MIN',
        'New Orleans Pelicans': 'NOP',
        'New York Knicks': 'NYK',
        'Oklahoma City Thunder': 'OKC',
        'Orlando Magic': 'ORL',
        'Philadelphia 76ers': 'PHI',
        'Phoenix Suns': 'PHX',
        'Portland Trail Blazers': 'POR',
        'Sacramento Kings': 'SAC',
        'San Antonio Spurs': 'SAS',
        'Toronto Raptors': 'TOR',
        'Utah Jazz': 'UTA',
        'Washington Wizards': 'WAS',
    }
    
    def __init__(self):
        super().__init__()
        self.table_name = 'upcoming_team_game_context'
        self.processing_strategy = 'MERGE_UPDATE'
        
        # CRITICAL: Initialize BigQuery client
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # Initialize travel utility
        self.travel = NBATravel(project_id=self.project_id)
        
        # Data storage
        self.raw_data = None
        self.schedule_data = None
        self.betting_lines = None
        self.game_results = None
        self.injury_data = None
        self.transformed_data = None
    
    def extract_raw_data(self) -> None:
        """Extract all necessary data for team game context calculation."""
        logger.info("Extracting raw data for team game context...")
        
        try:
            # Get target date range (upcoming games) from opts
            start_date = self.opts.get('start_date')
            end_date = self.opts.get('end_date')
            
            logger.info(f"Processing team context for games from {start_date} to {end_date}")
            
            # 1. Extract schedule data (both teams per game) - FIXED with extended window
            self._extract_schedule_data(start_date, end_date)
            
            # 2. Extract betting lines
            self._extract_betting_lines(start_date, end_date)
            
            # 3. Extract historical game results (for streaks/momentum)
            self._extract_game_results(start_date)
            
            # 4. Extract injury data
            self._extract_injury_data(start_date, end_date)
            
            logger.info(f"Extracted data: {len(self.schedule_data)} team-game records")
            
        except Exception as e:
            logger.error(f"Error extracting raw data: {e}")
            raise
    
    def _extract_schedule_data(self, start_date, end_date) -> None:
        """
        Extract schedule with forward-looking context.
        
        CRITICAL FIX: Extended date range for window functions to work correctly.
        Window functions (LAG/LEAD) need to see games outside the target date range
        to calculate days_rest and next_game_days_rest properly.
        """
        # Calculate extended date range for window functions
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        # Extend window: 30 days before (for LAG) and 7 days after (for LEAD)
        extended_start = (start_dt - timedelta(days=30)).strftime('%Y-%m-%d')
        extended_end = (end_dt + timedelta(days=7)).strftime('%Y-%m-%d')
        
        logger.info(f"Schedule query window: {extended_start} to {extended_end} (extended)")
        logger.info(f"Target date range: {start_date} to {end_date} (filtered)")
        
        query = f"""
        WITH all_team_games AS (
          -- Get ALL games in EXTENDED window for LAG/LEAD calculations
          -- HOME TEAM PERSPECTIVE
          SELECT 
            game_date,
            game_id,
            home_team_tricode as team_abbr,
            away_team_tricode as opponent_team_abbr,
            TRUE as home_game,
            season_year,
            home_team_tricode,  -- Keep for betting lines join
            away_team_tricode   -- Keep for betting lines join
          FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date BETWEEN '{extended_start}' AND '{extended_end}'
          
          UNION ALL
          
          -- AWAY TEAM PERSPECTIVE
          SELECT 
            game_date,
            game_id,
            away_team_tricode as team_abbr,
            home_team_tricode as opponent_team_abbr,
            FALSE as home_game,
            season_year,
            home_team_tricode,  -- Keep for betting lines join
            away_team_tricode   -- Keep for betting lines join
          FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date BETWEEN '{extended_start}' AND '{extended_end}'
        ),
        
        team_schedule_with_context AS (
          SELECT 
            *,
            -- Forward-looking schedule context (LEAD sees future games now)
            LEAD(game_date) OVER (PARTITION BY team_abbr ORDER BY game_date) as next_game_date,
            LEAD(opponent_team_abbr) OVER (PARTITION BY team_abbr ORDER BY game_date) as next_opponent,
            
            -- Backward-looking context (LAG sees past games now)
            LAG(game_date) OVER (PARTITION BY team_abbr ORDER BY game_date) as last_game_date,
            LAG(opponent_team_abbr) OVER (PARTITION BY team_abbr ORDER BY game_date) as last_opponent,
            LAG(home_game) OVER (PARTITION BY team_abbr ORDER BY game_date) as last_game_home
          FROM all_team_games
        )
        
        SELECT 
          *,
          -- Calculate days rest (should work now!)
          DATE_DIFF(game_date, last_game_date, DAY) as team_days_rest,
          DATE_DIFF(next_game_date, game_date, DAY) as team_next_game_days_rest,
          
          -- Back-to-back flag
          CASE WHEN DATE_DIFF(game_date, last_game_date, DAY) = 1 THEN TRUE ELSE FALSE END as team_back_to_back
          
        FROM team_schedule_with_context
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'  -- Filter to target dates
        ORDER BY game_date, team_abbr
        """
        
        self.schedule_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.schedule_data)} team-game schedule records")
        
        # DEBUG: Check if days_rest is populated
        if len(self.schedule_data) > 0:
            null_rest = self.schedule_data['team_days_rest'].isna().sum()
            if null_rest > 0:
                logger.warning(f"⚠️  {null_rest}/{len(self.schedule_data)} records have NULL team_days_rest")
                logger.warning("This suggests window functions not seeing previous games")
            else:
                rest_values = self.schedule_data['team_days_rest'].value_counts().sort_index()
                logger.info(f"✓ team_days_rest distribution: {dict(rest_values)}")
    
    def _extract_betting_lines(self, start_date, end_date) -> None:
        """
        Extract betting lines (spreads and totals) from odds API.
        
        ENHANCED WITH DEBUG LOGGING to diagnose spread extraction issues.
        """
        query = f"""
        WITH latest_lines AS (
          SELECT 
            game_date,
            home_team_abbr,
            away_team_abbr,
            bookmaker_key,
            market_key,
            outcome_name,
            outcome_point,
            outcome_price,
            snapshot_timestamp,
            ROW_NUMBER() OVER (
              PARTITION BY game_date, home_team_abbr, away_team_abbr, bookmaker_key, market_key, outcome_name 
              ORDER BY snapshot_timestamp DESC
            ) as rn
          FROM `{self.project_id}.nba_raw.odds_api_game_lines`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        ),
        
        opening_lines AS (
          SELECT 
            game_date,
            home_team_abbr,
            away_team_abbr,
            bookmaker_key,
            market_key,
            outcome_name,
            outcome_point,
            outcome_price,
            snapshot_timestamp,
            ROW_NUMBER() OVER (
              PARTITION BY game_date, home_team_abbr, away_team_abbr, bookmaker_key, market_key, outcome_name 
              ORDER BY snapshot_timestamp ASC
            ) as rn
          FROM `{self.project_id}.nba_raw.odds_api_game_lines`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        )
        
        SELECT 
          l.game_date,
          l.home_team_abbr,
          l.away_team_abbr,
          l.bookmaker_key,
          l.market_key,
          l.outcome_name,
          l.outcome_point as current_line,
          l.outcome_price as current_price,
          o.outcome_point as opening_line,
          o.outcome_price as opening_price
        FROM latest_lines l
        LEFT JOIN opening_lines o 
          ON l.game_date = o.game_date
          AND l.home_team_abbr = o.home_team_abbr
          AND l.away_team_abbr = o.away_team_abbr
          AND l.bookmaker_key = o.bookmaker_key
          AND l.market_key = o.market_key
          AND l.outcome_name = o.outcome_name
          AND o.rn = 1
        WHERE l.rn = 1
        ORDER BY l.game_date, l.home_team_abbr, l.market_key, l.outcome_name
        """
        
        self.betting_lines = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.betting_lines)} betting line records")
        
        # DEBUG: Show what betting lines look like
        if len(self.betting_lines) > 0:
            # Count by market
            market_counts = self.betting_lines['market_key'].value_counts()
            logger.info(f"Market breakdown: {dict(market_counts)}")
            
            # Count by bookmaker
            bookmaker_counts = self.betting_lines['bookmaker_key'].value_counts()
            logger.info(f"Bookmaker breakdown: {dict(bookmaker_counts)}")
            
            # Show sample spread lines
            spread_sample = self.betting_lines[
                (self.betting_lines['market_key'] == 'spreads') &
                (self.betting_lines['bookmaker_key'] == 'draftkings')
            ].head(5)
            
            if len(spread_sample) > 0:
                logger.info("Sample DraftKings spreads:")
                for _, line in spread_sample.iterrows():
                    logger.info(f"  {line['game_date']} {line['home_team_abbr']} vs {line['away_team_abbr']}: "
                               f"outcome_name='{line['outcome_name']}', point={line['current_line']}")
            else:
                logger.warning("⚠️  No DraftKings spreads found in sample!")
                
            # Check unique outcome_name values for spreads
            if 'spreads' in market_counts.index:
                spread_outcomes = self.betting_lines[
                    self.betting_lines['market_key'] == 'spreads'
                ]['outcome_name'].unique()
                logger.info(f"Unique spread outcome_name values: {list(spread_outcomes)[:10]}")
        else:
            logger.warning("⚠️  No betting lines extracted!")
    
    def _extract_game_results(self, start_date) -> None:
        """
        Extract historical game results for momentum/streak calculations.
        
        Uses dual-source strategy with automatic fallback.
        """
        # Get last 30 days of results before target date
        lookback_date = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d')
        
        logger.info(f"Extracting game results from {lookback_date} to {start_date}")
        
        # PRIMARY: Try nbac_schedule first
        schedule_query = f"""
        SELECT 
          game_date,
          game_id,
          home_team_tricode as home_team_abbr,
          away_team_tricode as away_team_abbr,
          home_team_score as home_score,
          away_team_score as away_score,
          winning_team_tricode as winning_team_abbr,
          'nbac_schedule' as source
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date >= '{lookback_date}' 
          AND game_date < '{start_date}'
          AND home_team_score IS NOT NULL  -- Only completed games
          AND game_status = 3  -- Status 3 = Final
        ORDER BY game_date DESC
        """
        
        self.game_results = self.bq_client.query(schedule_query).to_dataframe()
        schedule_count = len(self.game_results)
        logger.info(f"Extracted {schedule_count} game results from nbac_schedule")
        
        # FALLBACK: Check espn_scoreboard for any missing dates
        if schedule_count > 0:
            espn_query = f"""
            SELECT 
              e.game_date,
              e.game_id,
              e.home_team_abbr,
              e.away_team_abbr,
              e.home_team_score as home_score,
              e.away_team_score as away_score,
              CASE 
                WHEN e.home_team_winner THEN e.home_team_abbr
                WHEN e.away_team_winner THEN e.away_team_abbr
                ELSE NULL
              END as winning_team_abbr,
              'espn_scoreboard' as source
            FROM `{self.project_id}.nba_raw.espn_scoreboard` e
            WHERE e.game_date >= '{lookback_date}' 
              AND e.game_date < '{start_date}'
              AND e.is_completed = true
              AND e.game_status = 'final'
              -- Only get games NOT already in schedule results
              AND NOT EXISTS (
                SELECT 1 
                FROM `{self.project_id}.nba_raw.nbac_schedule` s
                WHERE s.game_date = e.game_date
                  AND s.home_team_tricode = e.home_team_abbr
                  AND s.away_team_tricode = e.away_team_abbr
                  AND s.home_team_score IS NOT NULL
              )
            """
            
            try:
                espn_results = self.bq_client.query(espn_query).to_dataframe()
                if len(espn_results) > 0:
                    self.game_results = pd.concat([self.game_results, espn_results], ignore_index=True)
                    logger.info(f"Added {len(espn_results)} additional games from espn_scoreboard (fallback)")
            except Exception as e:
                logger.warning(f"Could not fetch espn_scoreboard fallback data: {e}")
        else:
            logger.warning("No data from nbac_schedule, trying espn_scoreboard as primary")
            espn_query = f"""
            SELECT 
              game_date,
              game_id,
              home_team_abbr,
              away_team_abbr,
              home_team_score as home_score,
              away_team_score as away_score,
              CASE 
                WHEN home_team_winner THEN home_team_abbr
                WHEN away_team_winner THEN away_team_abbr
                ELSE NULL
              END as winning_team_abbr,
              'espn_scoreboard' as source
            FROM `{self.project_id}.nba_raw.espn_scoreboard`
            WHERE game_date >= '{lookback_date}' 
              AND game_date < '{start_date}'
              AND is_completed = true
              AND game_status = 'final'
            ORDER BY game_date DESC
            """
            
            try:
                self.game_results = self.bq_client.query(espn_query).to_dataframe()
                logger.info(f"Extracted {len(self.game_results)} game results from espn_scoreboard (primary)")
            except Exception as e:
                logger.error(f"Could not fetch from either source: {e}")
                self.game_results = pd.DataFrame()
        
        total_results = len(self.game_results)
        if total_results > 0:
            sources = self.game_results['source'].value_counts().to_dict()
            logger.info(f"Total game results: {total_results}, Sources: {sources}")
        else:
            logger.warning("No game results found from any source")
    
    def _extract_injury_data(self, start_date, end_date) -> None:
        """Extract injury report data for personnel context."""
        query = f"""
        WITH latest_injury_status AS (
          SELECT 
            game_date,
            team,
            player_lookup,
            injury_status,
            reason_category,
            ROW_NUMBER() OVER (
              PARTITION BY game_date, team, player_lookup 
              ORDER BY report_date DESC, report_hour DESC
            ) as rn
          FROM `{self.project_id}.nba_raw.nbac_injury_report`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        )
        
        SELECT 
          game_date,
          team,
          COUNT(CASE WHEN injury_status = 'out' THEN 1 END) as players_out,
          COUNT(CASE WHEN injury_status IN ('questionable', 'doubtful') THEN 1 END) as questionable_players
        FROM latest_injury_status
        WHERE rn = 1
        GROUP BY game_date, team
        """
        
        self.injury_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.injury_data)} injury summary records")
    
    def validate_extracted_data(self) -> None:
        """Validate the extracted data quality."""
        issues = []
        
        # Check schedule data
        if self.schedule_data is None or len(self.schedule_data) == 0:
            issues.append("No schedule data extracted")
        
        # Check for missing game_ids
        if self.schedule_data is not None:
            null_game_ids = self.schedule_data['game_id'].isna().sum()
            if null_game_ids > 0:
                issues.append(f"{null_game_ids} records missing game_id")
        
        # Check for missing team abbreviations
        if self.schedule_data is not None:
            null_teams = self.schedule_data['team_abbr'].isna().sum()
            if null_teams > 0:
                issues.append(f"{null_teams} records missing team_abbr")
        
        # CRITICAL: Check if days_rest is NULL (window function failure)
        if self.schedule_data is not None:
            null_rest = self.schedule_data['team_days_rest'].isna().sum()
            if null_rest > 0:
                issues.append(f"⚠️  CRITICAL: {null_rest} records missing team_days_rest (window function issue)")
        
        # Log validation results
        if issues:
            logger.warning(f"Data quality issues found: {'; '.join(issues)}")
            for issue in issues:
                self.log_quality_issue(
                    issue_type='missing_data',
                    description=issue,
                    affected_records=0
                )
        else:
            logger.info("Data validation passed - no critical issues found")
    
    def calculate_analytics(self) -> None:
        """Calculate all team game context analytics."""
        logger.info("Calculating team game context analytics...")
        
        records = []
        
        for _, game in self.schedule_data.iterrows():
            try:
                record = self._calculate_team_game_context(game)
                records.append(record)
            except Exception as e:
                logger.error(f"Error calculating context for {game.get('game_id')} - {game.get('team_abbr')}: {e}")
                continue
        
        self.transformed_data = records
        logger.info(f"Calculated context for {len(records)} team-game records")
    
    def _calculate_team_game_context(self, game: pd.Series) -> Dict:
        """Calculate complete context for a single team-game."""
        
        # Core identifiers
        record = {
            'team_abbr': game['team_abbr'],
            'game_id': game['game_id'],
            'game_date': game['game_date'].isoformat() if pd.notna(game['game_date']) else None,
            'opponent_team_abbr': game['opponent_team_abbr'],
            'season_year': int(game['season_year']) if pd.notna(game['season_year']) else None,
        }
        
        # Betting context (with debug logging)
        record.update(self._calculate_betting_context(game))
        
        # Fatigue metrics
        record.update(self._calculate_fatigue_metrics(game))
        
        # Personnel context
        record.update(self._calculate_personnel_context(game))
        
        # Momentum context
        record.update(self._calculate_momentum_context(game))
        
        # Basic game context
        record.update(self._calculate_basic_context(game))
        
        # Forward-looking schedule
        record.update(self._calculate_forward_schedule(game))
        
        # Opponent asymmetry
        record.update(self._calculate_opponent_asymmetry(game))
        
        # Market context (closing lines - will be NULL for upcoming games)
        record.update(self._calculate_market_context(game))
        
        # Referee integration
        record.update(self._calculate_referee_context(game))
        
        # Data quality tracking
        record.update({
            'data_quality_tier': 'high',
            'primary_source_used': 'nba_schedule',
            'processed_with_issues': False,
            'context_version': 1,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat()
        })
        
        return record
    
    def _calculate_betting_context(self, game: pd.Series) -> Dict:
        """
        Calculate betting lines context (spreads and totals).
        ENHANCED WITH DEBUG LOGGING.
        """
        context = {
            'game_spread': None, 
            'opening_spread': None, 
            'spread_movement': None,
            'game_spread_source': None, 
            'spread_public_betting_pct': None,
            'game_total': None, 
            'opening_total': None, 
            'total_movement': None,
            'game_total_source': None, 
            'total_public_betting_pct': None,
        }
        
        if self.betting_lines is None or len(self.betting_lines) == 0:
            return context
        
        # Match betting lines using game_date + teams
        game_date = game['game_date']
        home_team = game['home_team_tricode']
        away_team = game['away_team_tricode']
        team_abbr = game['team_abbr']
        
        game_lines = self.betting_lines[
            (self.betting_lines['game_date'] == game_date) &
            (self.betting_lines['home_team_abbr'] == home_team) &
            (self.betting_lines['away_team_abbr'] == away_team)
        ]
        
        if len(game_lines) == 0:
            logger.debug(f"No betting lines found for {game_date} {home_team} vs {away_team}")
            return context
        
        # DEBUG: Log what we found
        logger.debug(f"Found {len(game_lines)} lines for {game_date} {home_team} vs {away_team}")
        
        # Get spread lines (prioritize DraftKings)
        spread_lines = game_lines[game_lines['market_key'] == 'spreads']
        dk_spreads = spread_lines[spread_lines['bookmaker_key'] == 'draftkings']
        
        logger.debug(f"  Spread lines available: {len(spread_lines)} total, {len(dk_spreads)} from DraftKings")
        
        if len(dk_spreads) > 0:
            # DEBUG: Show what outcome_name values we have
            unique_outcomes = dk_spreads['outcome_name'].unique()
            logger.debug(f"  DraftKings spread outcome_name values: {list(unique_outcomes)}")
            
            # Find the spread for this team using reverse mapping
            team_spread = None
            
            # Strategy 1: Direct lookup using outcome_name (full team name)
            # Find which full name in the outcomes corresponds to our team_abbr
            target_full_name = None
            for outcome in unique_outcomes:
                if outcome in self.TEAM_NAME_MAP and self.TEAM_NAME_MAP[outcome] == team_abbr:
                    target_full_name = outcome
                    break
            
            if target_full_name:
                team_spread = dk_spreads[dk_spreads['outcome_name'] == target_full_name]
                if len(team_spread) > 0:
                    logger.debug(f"  ✓ Matched spread using team name mapping: {team_abbr} → '{target_full_name}'")
            
            # Strategy 2 (fallback): Try exact abbreviation match
            if team_spread is None or len(team_spread) == 0:
                team_spread = dk_spreads[dk_spreads['outcome_name'] == team_abbr]
                if len(team_spread) > 0:
                    logger.debug(f"  ✓ Matched spread using exact team_abbr: {team_abbr}")
            
            # Strategy 3 (fallback): Contains team_abbr (case insensitive)
            if team_spread is None or len(team_spread) == 0:
                team_spread = dk_spreads[dk_spreads['outcome_name'].str.contains(team_abbr, na=False, case=False)]
                if len(team_spread) > 0:
                    logger.debug(f"  ✓ Matched spread using contains: {team_abbr}")
            
            # Strategy 4 (last resort): Home/Away designation
            if team_spread is None or len(team_spread) == 0:
                is_home = game['home_game']
                if is_home:
                    team_spread = dk_spreads[dk_spreads['outcome_name'].str.lower().isin(['home', home_team.lower()])]
                    if len(team_spread) > 0:
                        logger.debug(f"  ✓ Matched spread using 'home' designation")
                else:
                    team_spread = dk_spreads[dk_spreads['outcome_name'].str.lower().isin(['away', away_team.lower()])]
                    if len(team_spread) > 0:
                        logger.debug(f"  ✓ Matched spread using 'away' designation")
            
            # If we found a match
            if team_spread is not None and len(team_spread) > 0:
                current = team_spread.iloc[0]['current_line']
                opening = team_spread.iloc[0]['opening_line']
                context['game_spread'] = float(current) if pd.notna(current) else None
                context['opening_spread'] = float(opening) if pd.notna(opening) else None
                
                if pd.notna(current) and pd.notna(opening):
                    context['spread_movement'] = float(current - opening)
                
                context['game_spread_source'] = 'draftkings'
                logger.debug(f"  ✓ Spread extracted: {context['game_spread']} (opened: {context['opening_spread']})")
            else:
                logger.warning(f"  ✗ Could not match spread for team {team_abbr} in outcome_name values: {list(unique_outcomes)}")
                logger.warning(f"     Consider adding '{team_abbr}' mapping if outcome uses full team name")
        else:
            logger.debug(f"  No DraftKings spreads available")
        
        # Get total lines
        total_lines = game_lines[game_lines['market_key'] == 'totals']
        dk_totals = total_lines[total_lines['bookmaker_key'] == 'draftkings']
        
        if len(dk_totals) > 0:
            over_line = dk_totals[dk_totals['outcome_name'] == 'Over']
            if len(over_line) > 0:
                current = over_line.iloc[0]['current_line']
                opening = over_line.iloc[0]['opening_line']
                context['game_total'] = float(current) if pd.notna(current) else None
                context['opening_total'] = float(opening) if pd.notna(opening) else None
                
                if pd.notna(current) and pd.notna(opening):
                    context['total_movement'] = float(current - opening)
                
                context['game_total_source'] = 'draftkings'
                logger.debug(f"  ✓ Total extracted: {context['game_total']} (opened: {context['opening_total']})")
        
        return context
    
    def _calculate_fatigue_metrics(self, game: pd.Series) -> Dict:
        """Calculate team fatigue metrics."""
        team_abbr = game['team_abbr']
        game_date = game['game_date']
        
        # Get days rest from schedule data (already calculated in query with FIXED window)
        days_rest = game.get('team_days_rest')
        back_to_back = game.get('team_back_to_back')
        
        # Calculate games in last 7 and 14 days
        if self.game_results is not None:
            # Get team's recent games
            recent_games = self.game_results[
                (self.game_results['home_team_abbr'] == team_abbr) | 
                (self.game_results['away_team_abbr'] == team_abbr)
            ]
            
            if len(recent_games) > 0:
                # Games in last 7 days
                seven_days_ago = game_date - pd.Timedelta(days=7)
                games_last_7 = len(recent_games[recent_games['game_date'] >= seven_days_ago])
                
                # Games in last 14 days
                fourteen_days_ago = game_date - pd.Timedelta(days=14)
                games_last_14 = len(recent_games[recent_games['game_date'] >= fourteen_days_ago])
                
                # Count back-to-backs in last 14 days
                recent_dates = sorted(recent_games[recent_games['game_date'] >= fourteen_days_ago]['game_date'].unique())
                b2b_count = sum(1 for i in range(len(recent_dates)-1) if (recent_dates[i+1] - recent_dates[i]).days == 1)
            else:
                games_last_7 = 0
                games_last_14 = 0
                b2b_count = 0
        else:
            games_last_7 = 0
            games_last_14 = 0
            b2b_count = 0
        
        # Consecutive road games (simplified - would need full schedule context)
        consecutive_road = 0  # TODO: Calculate from full schedule
        
        return {
            'team_days_rest': int(days_rest) if pd.notna(days_rest) else None,
            'team_back_to_back': bool(back_to_back) if pd.notna(back_to_back) else False,
            'games_in_last_7_days': games_last_7,
            'games_in_last_14_days': games_last_14,
            'back_to_backs_last_14_days': b2b_count,
            'consecutive_road_games': consecutive_road
        }
    
    def _calculate_personnel_context(self, game: pd.Series) -> Dict:
        """Calculate personnel/injury context."""
        team_abbr = game['team_abbr']
        game_date = game['game_date']
        
        if self.injury_data is None or len(self.injury_data) == 0:
            return {
                'starters_out_count': 0,
                'star_players_out_count': 0,
                'questionable_players_count': 0
            }
        
        # Get injury data for this team/date
        team_injuries = self.injury_data[
            (self.injury_data['team'] == team_abbr) & 
            (self.injury_data['game_date'] == game_date)
        ]
        
        if len(team_injuries) > 0:
            players_out = int(team_injuries.iloc[0]['players_out'])
            questionable = int(team_injuries.iloc[0]['questionable_players'])
        else:
            players_out = 0
            questionable = 0
        
        return {
            'starters_out_count': players_out,  # Simplified
            'star_players_out_count': 0,  # Not available
            'questionable_players_count': questionable
        }
    
    def _calculate_momentum_context(self, game: pd.Series) -> Dict:
        """Calculate team momentum/streaks."""
        team_abbr = game['team_abbr']
        game_date = game['game_date']
        
        if self.game_results is None or len(self.game_results) == 0:
            return {
                'team_win_streak_entering': 0,
                'team_loss_streak_entering': 0,
                'last_game_margin': None,
                'ats_cover_streak': 0,
                'ats_fail_streak': 0,
                'over_streak': 0,
                'under_streak': 0,
                'ats_record_last_10': '0-0'
            }
        
        # Get team's recent games (before target date)
        team_games = self.game_results[
            ((self.game_results['home_team_abbr'] == team_abbr) | 
             (self.game_results['away_team_abbr'] == team_abbr)) &
            (self.game_results['game_date'] < game_date)
        ].sort_values('game_date', ascending=False)
        
        if len(team_games) == 0:
            return {
                'team_win_streak_entering': 0,
                'team_loss_streak_entering': 0,
                'last_game_margin': None,
                'ats_cover_streak': 0,
                'ats_fail_streak': 0,
                'over_streak': 0,
                'under_streak': 0,
                'ats_record_last_10': '0-0'
            }
        
        # Win/loss streak
        win_streak = 0
        loss_streak = 0
        for _, g in team_games.iterrows():
            if g['winning_team_abbr'] == team_abbr:
                if loss_streak == 0:
                    win_streak += 1
                else:
                    break
            else:
                if win_streak == 0:
                    loss_streak += 1
                else:
                    break
        
        # Last game margin
        last_game = team_games.iloc[0]
        if last_game['home_team_abbr'] == team_abbr:
            margin = last_game['home_score'] - last_game['away_score']
        else:
            margin = last_game['away_score'] - last_game['home_score']
        
        return {
            'team_win_streak_entering': win_streak,
            'team_loss_streak_entering': loss_streak,
            'last_game_margin': int(margin) if pd.notna(margin) else None,
            'ats_cover_streak': 0,  # TODO
            'ats_fail_streak': 0,  # TODO
            'over_streak': 0,  # TODO
            'under_streak': 0,  # TODO
            'ats_record_last_10': '0-0'  # TODO
        }
    
    def _calculate_basic_context(self, game: pd.Series) -> Dict:
        """Calculate basic game context (home/away, travel)."""
        home_game = game['home_game']
        
        # Travel distance
        travel_miles = 0
        if not home_game:
            # Away game - calculate travel from last game location
            last_opponent = game.get('last_opponent')
            opponent = game['opponent_team_abbr']
            if pd.notna(last_opponent):
                try:
                    travel_info = self.travel.get_travel_distance(last_opponent, opponent)
                    if travel_info:
                        travel_miles = travel_info['distance_miles']
                except Exception as e:
                    logger.debug(f"Could not calculate travel for {game['team_abbr']}: {e}")
        
        return {
            'home_game': bool(home_game) if pd.notna(home_game) else None,
            'travel_miles': travel_miles
        }
    
    def _calculate_forward_schedule(self, game: pd.Series) -> Dict:
        """Calculate forward-looking schedule context."""
        # Already calculated in schedule query (FIXED with extended window)
        next_game_days_rest = game.get('team_next_game_days_rest')
        
        return {
            'team_next_game_days_rest': int(next_game_days_rest) if pd.notna(next_game_days_rest) else None,
            'team_games_in_next_7_days': 0,  # TODO
            'next_opponent_win_pct': None,  # TODO
            'next_game_is_primetime': False  # TODO
        }
    
    def _calculate_opponent_asymmetry(self, game: pd.Series) -> Dict:
        """Calculate opponent schedule asymmetry."""
        opponent_abbr = game['opponent_team_abbr']
        
        # Find opponent's record for this same game
        opponent_game = self.schedule_data[
            (self.schedule_data['game_id'] == game['game_id']) &
            (self.schedule_data['team_abbr'] == opponent_abbr)
        ]
        
        if len(opponent_game) > 0:
            opp = opponent_game.iloc[0]
            return {
                'opponent_days_rest': int(opp.get('team_days_rest')) if pd.notna(opp.get('team_days_rest')) else None,
                'opponent_games_in_next_7_days': 0,  # TODO
                'opponent_next_game_days_rest': int(opp.get('team_next_game_days_rest')) if pd.notna(opp.get('team_next_game_days_rest')) else None
            }
        
        return {
            'opponent_days_rest': None,
            'opponent_games_in_next_7_days': 0,
            'opponent_next_game_days_rest': None
        }
    
    def _calculate_market_context(self, game: pd.Series) -> Dict:
        """Calculate closing market context (NULL for upcoming games)."""
        return {
            'closing_spread': None,
            'closing_total': None,
            'team_implied_total': None,
            'opp_implied_total': None
        }
    
    def _calculate_referee_context(self, game: pd.Series) -> Dict:
        """Get referee crew assignment."""
        return {
            'referee_crew_id': None  # TODO
        }
    
    def get_analytics_stats(self) -> Dict:
        """Return statistics about the analytics calculation."""
        if not self.transformed_data:
            return {'records_processed': 0}
        
        start_date = self.opts.get('start_date', 'unknown')
        end_date = self.opts.get('end_date', 'unknown')
        
        return {
            'records_processed': len(self.transformed_data),
            'date_range': f"{start_date} to {end_date}",
            'unique_teams': len(set(r['team_abbr'] for r in self.transformed_data)),
            'unique_games': len(set(r['game_id'] for r in self.transformed_data))
        }
    
    def post_process(self) -> None:
        """Send success notification with stats."""
        stats = self.get_analytics_stats()
        
        logger.info(f"Team game context processing complete: {stats['records_processed']} records processed")
        logger.info(f"Date range: {stats['date_range']}, {stats['unique_teams']} teams, {stats['unique_games']} games")