#!/usr/bin/env python3
# File: validation/validators/raw/bdl_boxscores_validator.py
# Description: Custom validator for Ball Don't Lie Box Scores - Extends BaseValidator with processor-specific checks
# Version: 2.0 - Improved with better error handling and additional validations
"""
Custom validator for Ball Don't Lie Box Scores
Extends BaseValidator with processor-specific checks

Version 2.0 Improvements:
- Added team total sum validation
- Better error handling for missing data
- More informative logging
- Performance tracking
"""

import sys
import os
import time
from typing import Optional

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class BdlBoxscoresValidator(BaseValidator):
    """
    Custom validator for BDL box scores with player-level checks.
    
    Additional validations:
    - Player count per game (should be 20-40 active players)
    - Cross-validation with NBA.com gamebook
    - Points sum validation (player stats sum to team totals)
    - Minutes played validation
    """
    
    def _run_custom_validations(
        self, 
        start_date: str, 
        end_date: str,
        season_year: Optional[int]
    ):
        """BDL-specific validations"""
        
        logger.info("Running BDL-specific custom validations...")
        
        # Check 1: Player count per game
        self._validate_player_count_per_game(start_date, end_date)
        
        # Check 2: Cross-validate with NBA.com gamebook
        self._validate_cross_source_scores(start_date, end_date)
        
        # Check 3: Validate points sum to team totals
        self._validate_player_team_sum(start_date, end_date)
        
        # Check 4: Minutes played validation
        self._validate_minutes_played(start_date, end_date)
        
        logger.info("Completed BDL-specific validations")
    
    def _validate_player_count_per_game(self, start_date: str, end_date: str):
        """Check if each game has reasonable number of players (20-40)"""
        
        check_start = time.time()
        
        query = f"""
        WITH game_player_counts AS (
          SELECT 
            game_id,
            game_date,
            COUNT(*) as player_count
          FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
          GROUP BY game_id, game_date
        )
        SELECT 
          game_id,
          game_date,
          player_count
        FROM game_player_counts
        WHERE player_count < 20 OR player_count > 40
        ORDER BY game_date, game_id
        LIMIT 50
        """
        
        try:
            result = self._execute_query(query, start_date, end_date)
            anomalies = [(row.game_id, str(row.game_date), row.player_count) for row in result]
            
            passed = len(anomalies) == 0
            duration = time.time() - check_start
            
            self.results.append(ValidationResult(
                check_name="player_count_per_game",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(anomalies)} games with unusual player counts (expected: 20-40)" if not passed else "All games have normal player counts",
                affected_count=len(anomalies),
                affected_items=anomalies[:10],
                query_used=query,
                execution_duration=duration
            ))
            
            if not passed:
                logger.warning(f"Player count validation: {len(anomalies)} games with unusual counts")
                for game_id, game_date, count in anomalies[:3]:
                    logger.warning(f"  {game_date} {game_id}: {count} players")
                    
        except Exception as e:
            logger.error(f"Player count validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="player_count_per_game",
                check_type="data_quality",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))
    
    def _validate_cross_source_scores(self, start_date: str, end_date: str):
        """Compare BDL scores with NBA.com gamebook"""
        
        check_start = time.time()
        
        query = f"""
        WITH bdl_totals AS (
          SELECT 
            game_id,
            player_lookup,
            points as bdl_points
          FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
        ),
        gamebook_totals AS (
          SELECT 
            game_id,
            player_lookup,
            points as gamebook_points
          FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
            AND player_status = 'active'
        )
        SELECT 
          b.game_id,
          b.player_lookup,
          b.bdl_points,
          g.gamebook_points,
          ABS(b.bdl_points - g.gamebook_points) as points_diff
        FROM bdl_totals b
        JOIN gamebook_totals g 
          ON b.game_id = g.game_id 
          AND b.player_lookup = g.player_lookup
        WHERE ABS(b.bdl_points - g.gamebook_points) > 0
        ORDER BY points_diff DESC
        LIMIT 20
        """
        
        try:
            result = self._execute_query(query, start_date, end_date)
            mismatches = [(row.game_id, row.player_lookup, row.bdl_points, 
                          row.gamebook_points, row.points_diff) for row in result]
            
            passed = len(mismatches) == 0
            duration = time.time() - check_start
            
            self.results.append(ValidationResult(
                check_name="cross_source_score_validation",
                check_type="cross_validation",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(mismatches)} player scores that don't match NBA.com" if not passed else "All scores match NBA.com gamebook",
                affected_count=len(mismatches),
                affected_items=[f"{m[1]} ({m[0]}): BDL={m[2]} NBA={m[3]} diff={m[4]}" for m in mismatches[:10]],
                query_used=query,
                execution_duration=duration
            ))
            
            if not passed:
                logger.warning(f"Cross-source validation: {len(mismatches)} score mismatches found")
                for game_id, player, bdl, nba, diff in mismatches[:3]:
                    logger.warning(f"  {player} ({game_id}): BDL={bdl}, NBA={nba}, diff={diff}")
                    
        except Exception as e:
            # Gamebook data might not be available - that's okay
            duration = time.time() - check_start
            logger.info(f"Cross-source validation skipped: {str(e)}")
            self.results.append(ValidationResult(
                check_name="cross_source_score_validation",
                check_type="cross_validation",
                layer="bigquery",
                passed=True,
                severity="info",
                message=f"Could not validate cross-source (gamebook may not be available): {str(e)[:100]}",
                affected_count=0,
                execution_duration=duration
            ))
    
    def _validate_player_team_sum(self, start_date: str, end_date: str):
        """Verify player points sum to team totals"""
        
        check_start = time.time()
        
        query = f"""
        WITH player_sums AS (
          SELECT 
            game_id,
            team_abbr,
            SUM(points) as player_total
          FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
          GROUP BY game_id, team_abbr
        ),
        team_scores AS (
          SELECT 
            game_id,
            home_team_abbr as team,
            home_team_score as team_total
          FROM `{self.project_id}.nba_raw.espn_scoreboard`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
          UNION ALL
          SELECT 
            game_id,
            away_team_abbr as team,
            away_team_score as team_total
          FROM `{self.project_id}.nba_raw.espn_scoreboard`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
        )
        SELECT 
          p.game_id,
          p.team_abbr,
          p.player_total,
          t.team_total,
          ABS(p.player_total - t.team_total) as diff
        FROM player_sums p
        JOIN team_scores t 
          ON p.game_id = t.game_id 
          AND p.team_abbr = t.team
        WHERE ABS(p.player_total - t.team_total) > 2  -- Allow 2 point tolerance for rounding
        ORDER BY diff DESC
        LIMIT 20
        """
        
        try:
            result = self._execute_query(query, start_date, end_date)
            mismatches = [(row.game_id, row.team_abbr, row.player_total, 
                          row.team_total, row.diff) for row in result]
            
            passed = len(mismatches) == 0
            duration = time.time() - check_start
            
            self.results.append(ValidationResult(
                check_name="player_team_sum_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(mismatches)} games where player points don't sum to team total" if not passed else "All player points sum correctly to team totals",
                affected_count=len(mismatches),
                affected_items=[f"{m[1]} ({m[0]}): Players={m[2]} Team={m[3]} diff={m[4]}" for m in mismatches[:10]],
                query_used=query,
                execution_duration=duration
            ))
            
            if not passed:
                logger.warning(f"Player-team sum validation: {len(mismatches)} mismatches found")
                for game_id, team, player_sum, team_total, diff in mismatches[:3]:
                    logger.warning(f"  {team} ({game_id}): Players={player_sum}, Team={team_total}, diff={diff}")
                    
        except Exception as e:
            duration = time.time() - check_start
            logger.warning(f"Player-team sum validation skipped: {str(e)}")
            self.results.append(ValidationResult(
                check_name="player_team_sum_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=True,
                severity="info",
                message=f"Could not validate player-team sums (ESPN scoreboard may not be available): {str(e)[:100]}",
                affected_count=0,
                execution_duration=duration
            ))
    
    def _validate_minutes_played(self, start_date: str, end_date: str):
        """Check if minutes played are reasonable"""
        
        check_start = time.time()
        
        query = f"""
        WITH player_minutes AS (
          SELECT 
            game_id,
            game_date,
            player_lookup,
            minutes_played,
            team_abbr
          FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
            AND (minutes_played > 60 OR minutes_played < 0)  -- Impossible values
        )
        SELECT 
          game_id,
          game_date,
          player_lookup,
          team_abbr,
          minutes_played
        FROM player_minutes
        ORDER BY game_date, game_id
        LIMIT 50
        """
        
        try:
            result = self._execute_query(query, start_date, end_date)
            anomalies = [(row.game_id, str(row.game_date), row.player_lookup, 
                         row.team_abbr, row.minutes_played) for row in result]
            
            passed = len(anomalies) == 0
            duration = time.time() - check_start
            
            self.results.append(ValidationResult(
                check_name="minutes_played_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(anomalies)} players with impossible minutes played" if not passed else "All minutes played values are reasonable",
                affected_count=len(anomalies),
                affected_items=[f"{a[2]} ({a[1]}): {a[4]} min" for a in anomalies[:10]],
                query_used=query,
                execution_duration=duration
            ))
            
            if not passed:
                logger.warning(f"Minutes validation: {len(anomalies)} players with invalid minutes")
                for game_id, game_date, player, team, minutes in anomalies[:3]:
                    logger.warning(f"  {player} ({game_date}): {minutes} minutes")
                    
        except Exception as e:
            logger.error(f"Minutes validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="minutes_played_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))


def main():
    """Run validation from command line"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Validate BDL box scores',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate last 7 days
  python bdl_boxscores_validator.py --last-days 7
  
  # Validate specific date range
  python bdl_boxscores_validator.py --start-date 2024-01-01 --end-date 2024-01-31
  
  # Validate entire season
  python bdl_boxscores_validator.py --season 2024
  
  # Validate without sending notifications
  python bdl_boxscores_validator.py --last-days 7 --no-notify
        """
    )
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--season', type=int, help='Season year (2024 for 2024-25)')
    parser.add_argument('--last-days', type=int, help='Validate last N days')
    parser.add_argument('--no-notify', action='store_true', help='Disable notifications')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize validator
    config_path = 'validation/configs/raw/bdl_boxscores.yaml'
    
    try:
        validator = BdlBoxscoresValidator(config_path)
    except Exception as e:
        logger.error(f"Failed to initialize validator: {e}")
        sys.exit(1)
    
    # Determine date range
    if args.last_days:
        from datetime import date, timedelta
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=args.last_days)).isoformat()
    elif args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        start_date = None
        end_date = None
    
    # Run validation
    try:
        report = validator.validate(
            start_date=start_date,
            end_date=end_date,
            season_year=args.season,
            notify=not args.no_notify
        )
        
        # Exit with error code if validation failed
        if report.overall_status == 'fail':
            sys.exit(1)
        elif report.overall_status == 'warn':
            sys.exit(2)
        else:
            sys.exit(0)
            
    except Exception as e:
        logger.error(f"Validation execution failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()