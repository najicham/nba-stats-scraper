"""
orchestration/schedule_locker.py

Daily Schedule Locking - Generate expected workflow schedule for monitoring

Purpose: Let Grafana know what SHOULD happen today so it can distinguish:
  ✅ Correctly skipped (no games, no need to run)
  ❌ Failed to run (should have run but didn't)

Called at 5 AM ET daily (before any workflows run).
Creates BigQuery records showing what SHOULD run today.
"""

import logging
import uuid
from datetime import datetime, timedelta, time
from typing import List, Dict, Any
import pytz

from orchestration.config_loader import WorkflowConfig
from shared.utils.schedule import NBAScheduleService, GameType
from shared.utils.bigquery_utils import insert_bigquery_rows

logger = logging.getLogger(__name__)


class DailyScheduleLocker:
    """
    Generates expected workflow schedule for the day.
    
    Called at 5 AM ET daily (before any workflows run).
    Creates BigQuery records showing what SHOULD run today.
    Grafana uses this to detect missing executions.
    """
    
    VERSION = "1.0"
    
    def __init__(self, config_path: str = "config/workflows.yaml"):
        """Initialize schedule locker."""
        self.config = WorkflowConfig(config_path)
        self.schedule_service = NBAScheduleService()
        self.ET = pytz.timezone('America/New_York')
    
    def generate_daily_schedule(self, target_date: datetime = None) -> Dict[str, Any]:
        """
        Generate expected schedule for a specific date.
        
        Args:
            target_date: Date to generate schedule for (defaults to today ET)
        
        Returns:
            Dict with generation summary
        """
        if target_date is None:
            target_date = datetime.now(self.ET)
        
        date_str = target_date.date().strftime('%Y-%m-%d')
        
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("📅 Daily Schedule Lock: Generating expected schedule")
        logger.info(f"   Date: {date_str}")
        logger.info(f"   Time: {target_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        # Load game schedule for today
        games_today = self.schedule_service.get_games_for_date(date_str)
        logger.info(f"📊 Games scheduled: {len(games_today)}")
        
        # Generate expected runs for each workflow
        schedule_records = []
        enabled_workflows = self.config.get_enabled_workflows()
        
        for workflow_name in enabled_workflows:
            try:
                workflow_config = self.config.get_workflow_config(workflow_name)
                
                expected_runs = self._calculate_expected_runs(
                    workflow_name,
                    workflow_config,
                    games_today,
                    target_date
                )
                
                schedule_records.extend(expected_runs)
                
                logger.info(f"   {workflow_name}: {len(expected_runs)} expected runs")
                
            except Exception as e:
                logger.error(f"Error generating schedule for {workflow_name}: {e}")
        
        # Write to BigQuery
        if schedule_records:
            self._write_schedule(schedule_records)
            logger.info(f"✅ Wrote {len(schedule_records)} expected runs to BigQuery")
        else:
            logger.warning("⚠️  No expected runs generated")
        
        summary = {
            'date': date_str,
            'games_scheduled': len(games_today),
            'workflows_evaluated': len(enabled_workflows),
            'expected_runs': len(schedule_records),
            'locked_at': datetime.utcnow().isoformat()
        }
        
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"✅ Schedule locked: {len(schedule_records)} expected runs")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        return summary
    
    def _calculate_expected_runs(
        self,
        workflow_name: str,
        config: Dict[str, Any],
        games_today: list,
        date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Calculate when workflow should run based on config and game schedule.
        
        Returns:
            List of expected run records
        """
        decision_type = config['decision_type']
        expected = []
        
        if decision_type == "self_aware":
            # Morning operations: once between ideal window
            schedule = config['schedule']
            start_hour = schedule['ideal_window']['start_hour']
            
            expected.append({
                'date': date.date(),
                'locked_at': datetime.utcnow(),
                'workflow_name': workflow_name,
                'expected_run_time': datetime.combine(
                    date.date(),
                    time(start_hour + 1, 0)  # Target middle of window
                ).replace(tzinfo=self.ET),
                'reason': 'Daily foundation data',
                'scrapers': self._extract_scrapers(config['execution_plan']),
                'games_today': len(games_today),
                'priority': config['priority'],
                'schedule_version': self.VERSION,
                'generated_by': 'schedule_locker'
            })
        
        elif decision_type == "game_aware":
            # Betting lines: only if games, every N hours in window
            if not games_today:
                # No games = no expected runs
                return []
            
            schedule = config['schedule']
            first_game = min(games_today, key=lambda g: g.commence_time)
            
            # Start window hours before first game
            window_hours = schedule.get('window_before_game_hours', 6)
            start_time = first_game.commence_time - timedelta(hours=window_hours)
            
            # Generate runs every frequency_hours
            frequency_hours = schedule.get('frequency_hours', 2)
            business_start = schedule.get('business_hours', {}).get('start', 8)
            business_end = schedule.get('business_hours', {}).get('end', 20)
            
            current_time = start_time
            while current_time < first_game.commence_time:
                # Only business hours
                if business_start <= current_time.hour < business_end:
                    expected.append({
                        'date': date.date(),
                        'locked_at': datetime.utcnow(),
                        'workflow_name': workflow_name,
                        'expected_run_time': current_time,
                        'reason': f'Pre-game betting lines ({len(games_today)} games)',
                        'scrapers': self._extract_scrapers(config['execution_plan']),
                        'games_today': len(games_today),
                        'priority': config['priority'],
                        'schedule_version': self.VERSION,
                        'generated_by': 'schedule_locker'
                    })
                
                current_time += timedelta(hours=frequency_hours)
        
        elif decision_type == "game_aware_yesterday":
            # Post-game: fixed time if games yesterday
            # For simplicity, check if TODAY is day after games
            yesterday = (date.date() - timedelta(days=1)).strftime('%Y-%m-%d')
            games_yesterday = self.schedule_service.get_games_for_date(yesterday)
            
            if not games_yesterday:
                return []
            
            schedule = config['schedule']
            fixed_time_str = schedule.get('fixed_time')  # e.g., "22:00"
            
            if fixed_time_str:
                hour, minute = map(int, fixed_time_str.split(':'))
                
                expected.append({
                    'date': date.date(),
                    'locked_at': datetime.utcnow(),
                    'workflow_name': workflow_name,
                    'expected_run_time': datetime.combine(
                        date.date(),
                        time(hour, minute)
                    ).replace(tzinfo=self.ET),
                    'reason': f'Post-game collection ({len(games_yesterday)} games yesterday)',
                    'scrapers': self._extract_scrapers(config['execution_plan']),
                    'games_today': len(games_yesterday),  # Games from yesterday
                    'priority': config['priority'],
                    'schedule_version': self.VERSION,
                    'generated_by': 'schedule_locker'
                })
        
        elif decision_type == "discovery":
            # Discovery mode: up to max_attempts per day
            if not games_today and config['schedule'].get('requires_game_day', False):
                return []
            
            max_attempts = config['schedule'].get('max_attempts_per_day', 12)
            retry_interval = config['schedule'].get('retry_interval_hours', 1)
            
            # Generate expected attempts (optimistic: assume all attempts needed)
            for attempt in range(max_attempts):
                hour = 8 + (attempt * retry_interval)  # Start at 8 AM, every N hours
                
                if hour >= 24:
                    break
                
                expected.append({
                    'date': date.date(),
                    'locked_at': datetime.utcnow(),
                    'workflow_name': workflow_name,
                    'expected_run_time': datetime.combine(
                        date.date(),
                        time(hour, 0)
                    ).replace(tzinfo=self.ET),
                    'reason': f'Discovery attempt {attempt + 1}/{max_attempts}',
                    'scrapers': [config['execution_plan']['scraper']],
                    'games_today': len(games_today) if games_today else 0,
                    'priority': config['priority'],
                    'schedule_version': self.VERSION,
                    'generated_by': 'schedule_locker'
                })
        
        return expected
    
    def _extract_scrapers(self, execution_plan: Dict) -> List[str]:
        """Extract scraper list from execution plan."""
        scrapers = []
        
        if 'scrapers' in execution_plan:
            scrapers.extend(execution_plan['scrapers'])
        
        if 'scraper' in execution_plan:
            scrapers.append(execution_plan['scraper'])
        
        # Multi-step plans
        for key, value in execution_plan.items():
            if isinstance(value, dict):
                if 'scrapers' in value:
                    scrapers.extend(value['scrapers'])
                if 'scraper' in value:
                    scrapers.append(value['scraper'])
        
        return scrapers
    
    def _write_schedule(self, records: List[Dict]) -> None:
        """Write schedule records to BigQuery."""
        try:
            insert_bigquery_rows('nba_orchestration', 'daily_expected_schedule', records)
        except Exception as e:
            logger.error(f"Failed to write schedule to BigQuery: {e}")
            raise
