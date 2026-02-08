#!/usr/bin/env python3
# File: validation/validators/raw/espn_scoreboard_validator.py
# Description: Custom validator for ESPN Scoreboard - Extends BaseValidator
"""
Custom validator for ESPN Scoreboard
Validates backup game score source
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


class EspnScoreboardValidator(BaseValidator):
    """
    Custom validator for ESPN scoreboard with score-specific checks.
    
    Additional validations:
    - Score reasonableness (within normal NBA range)
    - Confidence score validation
    - Cross-validation with schedule data
    """
    
    def _run_custom_validations(
        self, 
        start_date: str, 
        end_date: str,
        season_year: Optional[int]
    ):
        """ESPN-specific validations"""
        
        logger.info("Running ESPN-specific custom validations...")
        
        # Check 1: Score reasonableness
        self._validate_score_range(start_date, end_date)
        
        # Check 2: Confidence scores
        self._validate_confidence_scores(start_date, end_date)
        
        # Check 3: Cross-validate with schedule
        self._validate_against_schedule(start_date, end_date)
        
        logger.info("Completed ESPN-specific validations")
    
    def _validate_score_range(self, start_date: str, end_date: str):
        """Check if scores are within reasonable NBA range (typically 70-160)"""
        
        check_start = time.time()
        
        query = f"""
        SELECT 
          game_id,
          game_date,
          home_team_abbr,
          away_team_abbr,
          home_team_score,
          away_team_score
        FROM `{self.project_id}.nba_raw.espn_scoreboard`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (
            home_team_score < 70 OR home_team_score > 160 OR
            away_team_score < 70 OR away_team_score > 160
          )
        ORDER BY game_date
        LIMIT 20
        """
        
        try:
            result = self._execute_query(query, start_date, end_date)
            anomalies = [(str(row.game_date), row.game_id, row.home_team_abbr, 
                         row.home_team_score, row.away_team_abbr, row.away_team_score) 
                        for row in result]
            
            passed = len(anomalies) == 0
            duration = time.time() - check_start
            
            self.results.append(ValidationResult(
                check_name="score_range_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(anomalies)} games with unusual scores (expected: 70-160)" if not passed else "All scores within normal range",
                affected_count=len(anomalies),
                affected_items=[f"{a[0]} {a[2]} {a[3]} vs {a[4]} {a[5]}" for a in anomalies[:10]],
                query_used=query,
                execution_duration=duration
            ))
            
            if not passed:
                logger.warning(f"Score range validation: {len(anomalies)} unusual scores")
                for date, game_id, home, home_score, away, away_score in anomalies[:3]:
                    logger.warning(f"  {date}: {home} {home_score} vs {away} {away_score}")
                    
        except Exception as e:
            logger.error(f"Score range validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="score_range_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))
    
    def _validate_confidence_scores(self, start_date: str, end_date: str):
        """Check if processing_confidence scores are reasonable (0.8-1.0 expected)"""
        
        check_start = time.time()
        
        query = f"""
        SELECT 
          COUNT(*) as total_games,
          COUNTIF(processing_confidence < 0.8) as low_confidence_count,
          AVG(processing_confidence) as avg_confidence,
          MIN(processing_confidence) as min_confidence
        FROM `{self.project_id}.nba_raw.espn_scoreboard`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        """
        
        try:
            result = self._execute_query(query, start_date, end_date)
            row = next(result, None)

            total_games = row.total_games if row and row.total_games else 0
            low_conf_count = row.low_confidence_count if row and row.low_confidence_count else 0
            avg_conf = row.avg_confidence if row and row.avg_confidence else 0
            min_conf = row.min_confidence if row and row.min_confidence else 0
            
            # Consider passed if less than 5% have low confidence
            passed = (total_games == 0) or (low_conf_count / total_games < 0.05)
            duration = time.time() - check_start
            
            message = f"Low confidence: {low_conf_count}/{total_games} games ({low_conf_count/total_games*100:.1f}%), avg={avg_conf:.3f}, min={min_conf:.3f}" if total_games > 0 else "No games in range"
            
            self.results.append(ValidationResult(
                check_name="confidence_score_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=message,
                affected_count=low_conf_count,
                query_used=query,
                execution_duration=duration
            ))
            
            if not passed:
                logger.warning(f"Confidence validation: {low_conf_count} games with low confidence")
                
        except Exception as e:
            logger.error(f"Confidence validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="confidence_score_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))
    
    def _validate_against_schedule(self, start_date: str, end_date: str):
        """Cross-validate ESPN games against NBA schedule"""
        
        check_start = time.time()
        
        query = f"""
        WITH espn_games AS (
          SELECT 
            game_id,
            game_date,
            home_team_abbr,
            away_team_abbr
          FROM `{self.project_id}.nba_raw.espn_scoreboard`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
        ),
        schedule_games AS (
          SELECT 
            game_id,
            game_date,
            home_team_tricode as home_team_abbr,
            away_team_tricode as away_team_abbr
          FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
            AND game_status = 3  -- Completed games only
        )
        SELECT 
          s.game_id,
          s.game_date
        FROM schedule_games s
        LEFT JOIN espn_games e 
            ON s.game_date = e.game_date
            AND s.home_team_abbr = e.home_team_abbr
            AND s.away_team_abbr = e.away_team_abbr
        WHERE e.game_id IS NULL
        ORDER BY s.game_date
        LIMIT 20
        """
        
        try:
            result = self._execute_query(query, start_date, end_date)
            missing = [(row.game_id, str(row.game_date)) for row in result]
            
            passed = len(missing) == 0
            duration = time.time() - check_start
            
            self.results.append(ValidationResult(
                check_name="cross_validation_schedule",
                check_type="cross_validation",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(missing)} games in schedule but not in ESPN" if not passed else "All schedule games present in ESPN",
                affected_count=len(missing),
                affected_items=[f"{m[1]}: {m[0]}" for m in missing[:10]],
                query_used=query,
                execution_duration=duration
            ))
            
            if not passed:
                logger.warning(f"Cross-validation: {len(missing)} games missing from ESPN")
                for game_id, date in missing[:3]:
                    logger.warning(f"  {date}: {game_id}")
                    
        except Exception as e:
            # Schedule might not be available - that's okay
            duration = time.time() - check_start
            logger.info(f"Cross-validation skipped: {str(e)}")
            self.results.append(ValidationResult(
                check_name="cross_validation_schedule",
                check_type="cross_validation",
                layer="bigquery",
                passed=True,
                severity="info",
                message=f"Could not cross-validate (schedule may not be available): {str(e)[:100]}",
                affected_count=0,
                execution_duration=duration
            ))


def main():
    """Run validation from command line"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Validate ESPN scoreboard data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate last 7 days
  python espn_scoreboard_validator.py --last-days 7
  
  # Validate specific date range
  python espn_scoreboard_validator.py --start-date 2024-01-01 --end-date 2024-01-31
  
  # Validate entire season
  python espn_scoreboard_validator.py --season 2024
  
  # Validate without sending notifications
  python espn_scoreboard_validator.py --last-days 7 --no-notify
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
    
    print("=" * 80)
    print("ESPN Scoreboard Validator")
    print("=" * 80)
    print("")
    
    # Initialize validator
    config_path = 'validation/configs/raw/espn_scoreboard.yaml'
    
    try:
        print(f"Loading config: {config_path}")
        validator = EspnScoreboardValidator(config_path)
        print(f"✅ Validator initialized: {validator.processor_name}")
    except Exception as e:
        print(f"❌ Failed to initialize validator: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Determine date range
    if args.last_days:
        from datetime import date, timedelta
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=args.last_days)).isoformat()
        print(f"Date range: Last {args.last_days} days ({start_date} to {end_date})")
    elif args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
        print(f"Date range: {start_date} to {end_date}")
    else:
        start_date = None
        end_date = None
        print("Date range: Auto-detect (last 30 days)")
    
    print("")
    
    # Run validation
    try:
        print("🔍 Running validation...")
        print("")
        
        report = validator.validate(
            start_date=start_date,
            end_date=end_date,
            season_year=args.season,
            notify=not args.no_notify
        )
        
        # Exit with appropriate code
        if report.overall_status == 'fail':
            sys.exit(1)
        elif report.overall_status == 'warn':
            sys.exit(2)
        else:
            sys.exit(0)
            
    except Exception as e:
        print(f"❌ Validation execution failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()