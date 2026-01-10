"""
orchestration/master_controller.py

Master Workflow Controller - Decision Engine for Phase 1 Orchestration

This is the brain of the system. It evaluates ALL workflows hourly and decides
which should run based on:
- Game schedules
- Workflow history
- Time windows
- Discovery mode state
"""

import logging
import uuid
from datetime import datetime, timedelta, time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import pytz
import json

from orchestration.config_loader import WorkflowConfig
from shared.utils.schedule import NBAScheduleService, GameType
from shared.utils.bigquery_utils import execute_bigquery, insert_bigquery_rows

# Import orchestration config for schedule staleness settings
try:
    from shared.config.orchestration_config import get_orchestration_config
    _orchestration_config = get_orchestration_config()
except ImportError:
    _orchestration_config = None

logger = logging.getLogger(__name__)


class DecisionAction(str, Enum):
    """Workflow decision actions."""
    RUN = "RUN"
    SKIP = "SKIP"
    ABORT = "ABORT"


class AlertLevel(str, Enum):
    """Alert severity levels."""
    NONE = "NONE"
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class WorkflowDecision:
    """
    Standard decision object returned by all workflow evaluators.
    """
    action: DecisionAction
    reason: str
    workflow_name: str
    
    # Optional fields
    scrapers: List[str] = None
    context: Dict[str, Any] = None
    next_check_time: Optional[datetime] = None
    priority: str = "MEDIUM"
    alert_level: AlertLevel = AlertLevel.NONE
    target_games: List[str] = None
    
    def __post_init__(self):
        """Convert enums to strings if needed."""
        if isinstance(self.action, str):
            self.action = DecisionAction(self.action)
        if isinstance(self.alert_level, str):
            self.alert_level = AlertLevel(self.alert_level)
        
        # Initialize empty lists
        if self.scrapers is None:
            self.scrapers = []
        if self.target_games is None:
            self.target_games = []
        if self.context is None:
            self.context = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data['action'] = self.action.value
        data['alert_level'] = self.alert_level.value
        if self.next_check_time:
            data['next_check_time'] = self.next_check_time.isoformat()
        return data


class MasterWorkflowController:
    """
    Main controller that evaluates all workflows hourly.
    
    Makes intelligent decisions about what should run based on:
    - Game schedules
    - Workflow history
    - Time windows
    - Discovery mode state
    """
    
    # Controller version for tracking
    VERSION = "1.0"
    
    def __init__(self, config_path: str = "config/workflows.yaml"):
        """Initialize controller with config and services."""
        self.config = WorkflowConfig(config_path)
        self.schedule_service = NBAScheduleService()
        self.ET = pytz.timezone('America/New_York')
    
    def evaluate_all_workflows(self, current_time: Optional[datetime] = None) -> List[WorkflowDecision]:
        """
        Main entry point: Evaluate ALL workflows and decide RUN/SKIP/ABORT.
        
        Args:
            current_time: Optional override for testing (defaults to now ET)
        
        Returns:
            List of WorkflowDecision objects
        """
        if current_time is None:
            current_time = datetime.now(self.ET)
        
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("🎯 Master Controller: Evaluating all workflows")
        logger.info(f"   Time: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        decisions = []
        
        # STEP 1: Ensure schedule current (CRITICAL FOUNDATION)
        schedule_decision = self._ensure_schedule_current(current_time)
        
        if schedule_decision.action == DecisionAction.ABORT:
            # Schedule scraper failed - cannot proceed
            logger.error("❌ ABORT: Schedule check failed, cannot evaluate game-aware workflows")
            decisions.append(schedule_decision)
            self._log_decisions(decisions)
            return decisions
        
        if schedule_decision.action == DecisionAction.RUN:
            decisions.append(schedule_decision)
            logger.info("📋 Schedule needs refresh, will be included in workflow execution")
        
        # STEP 2: Load today's schedule for game-aware decisions
        today = current_time.date().strftime('%Y-%m-%d')
        games_today = self.schedule_service.get_games_for_date(today)
        
        logger.info(f"📅 Games today: {len(games_today)}")
        
        # STEP 3: Evaluate each enabled workflow
        enabled_workflows = self.config.get_enabled_workflows()
        logger.info(f"🔍 Evaluating {len(enabled_workflows)} enabled workflows")
        
        for workflow_name in enabled_workflows:
            try:
                workflow_config = self.config.get_workflow_config(workflow_name)
                decision_type = workflow_config['decision_type']
                
                logger.info(f"\n📊 Evaluating: {workflow_name} (type: {decision_type})")
                
                # Route to appropriate evaluator
                if decision_type == "self_aware":
                    decision = self._evaluate_self_aware(workflow_name, workflow_config, current_time)
                
                elif decision_type == "game_aware":
                    decision = self._evaluate_game_aware(workflow_name, workflow_config, current_time, games_today)
                
                elif decision_type == "game_aware_yesterday":
                    yesterday = (current_time.date() - timedelta(days=1)).strftime('%Y-%m-%d')
                    games_yesterday = self.schedule_service.get_games_for_date(yesterday)
                    decision = self._evaluate_post_game(workflow_name, workflow_config, current_time, games_yesterday)

                elif decision_type == "game_aware_early":
                    # For early game days (Christmas, MLK Day, etc.) - collect TODAY's games
                    today = current_time.date().strftime('%Y-%m-%d')
                    decision = self._evaluate_early_game(workflow_name, workflow_config, current_time, games_today, today)

                elif decision_type == "discovery":
                    decision = self._evaluate_discovery(workflow_name, workflow_config, current_time, games_today)
                
                else:
                    logger.warning(f"Unknown decision_type: {decision_type}, skipping")
                    continue
                
                decisions.append(decision)
                
                # Log decision
                icon = "🟢" if decision.action == DecisionAction.RUN else "⏭️"
                logger.info(f"{icon} Decision: {decision.action.value} - {decision.reason}")
                
            except Exception as e:
                logger.error(f"Error evaluating {workflow_name}: {e}", exc_info=True)
                # Create ABORT decision for this workflow
                decisions.append(WorkflowDecision(
                    action=DecisionAction.ABORT,
                    reason=f"Evaluation error: {str(e)}",
                    workflow_name=workflow_name,
                    alert_level=AlertLevel.CRITICAL
                ))
        
        # STEP 4: Log all decisions to BigQuery
        self._log_decisions(decisions)
        
        # STEP 5: Summary
        run_count = sum(1 for d in decisions if d.action == DecisionAction.RUN)
        skip_count = sum(1 for d in decisions if d.action == DecisionAction.SKIP)
        abort_count = sum(1 for d in decisions if d.action == DecisionAction.ABORT)
        
        logger.info("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"📊 Summary: {run_count} RUN, {skip_count} SKIP, {abort_count} ABORT")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        
        return decisions
    
    def _ensure_schedule_current(self, current_time: datetime) -> WorkflowDecision:
        """
        Ensure we have current schedule before evaluating game-aware workflows.

        Uses orchestration_config.py for staleness threshold and overrides.
        This allows manual override when NBA.com is down.

        Returns:
            WorkflowDecision to run schedule scraper, skip, or abort
        """
        today = current_time.date().strftime('%Y-%m-%d')

        # Get effective max stale hours from config (includes override logic)
        if _orchestration_config:
            max_stale_hours = _orchestration_config.schedule_staleness.get_effective_max_hours()
            logger.debug(f"Schedule staleness threshold: {max_stale_hours}h (from config)")
        else:
            max_stale_hours = 6  # Fallback default
            logger.debug("Using fallback schedule staleness threshold: 6h")

        # Check when schedule was last scraped
        query = """
            SELECT MAX(triggered_at) as last_scrape
            FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
            WHERE scraper_name = 'nbac_schedule_api'
              AND status = 'success'
              AND DATE(triggered_at) = CURRENT_DATE()
        """

        try:
            result = execute_bigquery(query)
            last_scrape = result[0]['last_scrape'] if result and result[0]['last_scrape'] else None

            if last_scrape:
                hours_since = (current_time - last_scrape).total_seconds() / 3600

                if hours_since < max_stale_hours:
                    # Schedule is fresh
                    return WorkflowDecision(
                        action=DecisionAction.SKIP,
                        reason=f"Schedule current (scraped {hours_since:.1f}h ago, threshold: {max_stale_hours}h)",
                        workflow_name="schedule_dependency",
                        priority="HIGH"
                    )

            # Schedule stale or never scraped
            return WorkflowDecision(
                action=DecisionAction.RUN,
                reason=f"Schedule needs refresh (>{max_stale_hours}h old or never scraped)",
                workflow_name="schedule_dependency",
                priority="CRITICAL",
                scrapers=["nbac_schedule_api"],
                alert_level=AlertLevel.INFO
            )

        except Exception as e:
            logger.error(f"Failed to check schedule status: {e}")
            return WorkflowDecision(
                action=DecisionAction.ABORT,
                reason=f"Cannot verify schedule status: {str(e)}",
                workflow_name="schedule_dependency",
                alert_level=AlertLevel.CRITICAL
            )
    
    def _evaluate_self_aware(self, workflow_name: str, config: Dict, current_time: datetime) -> WorkflowDecision:
        """
        Evaluate self-aware workflow (e.g., morning_operations).
        
        Logic:
        1. Check if already run successfully today
        2. Check if in ideal time window
        3. Decide RUN or SKIP
        """
        schedule = config['schedule']
        ideal_start = schedule['ideal_window']['start_hour']
        ideal_end = schedule['ideal_window']['end_hour']
        
        # Check if already run today
        query = f"""
            SELECT MAX(triggered_at) as last_run
            FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
            WHERE workflow = '{workflow_name}'
              AND status = 'success'
              AND DATE(triggered_at) = CURRENT_DATE()
        """
        
        result = execute_bigquery(query)
        last_run = result[0]['last_run'] if result and result[0]['last_run'] else None
        
        if last_run:
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason="Already completed successfully today",
                workflow_name=workflow_name,
                priority=config['priority'],
                context={'last_run': last_run.isoformat()},
                next_check_time=current_time + timedelta(days=1)
            )
        
        # Check timing
        current_hour = current_time.hour

        if current_hour < ideal_start:
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason=f"Too early (ideal window: {ideal_start}-{ideal_end} ET)",
                workflow_name=workflow_name,
                priority=config['priority'],
                next_check_time=current_time.replace(hour=ideal_start, minute=0)
            )

        if current_hour > ideal_end:
            # Too late - schedule for tomorrow morning
            tomorrow = current_time + timedelta(days=1)
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason=f"Too late (ideal window: {ideal_start}-{ideal_end} ET)",
                workflow_name=workflow_name,
                priority=config['priority'],
                next_check_time=tomorrow.replace(hour=ideal_start, minute=0)
            )

        # Extract scrapers from execution plan
        scrapers = self._extract_scrapers_from_plan(config['execution_plan'])
        
        # Decide RUN
        alert_level = AlertLevel.WARNING if current_hour > ideal_end else AlertLevel.NONE
        
        return WorkflowDecision(
            action=DecisionAction.RUN,
            reason=f"Ready to run (ideal window: {ideal_start}-{ideal_end} ET)",
            workflow_name=workflow_name,
            priority=config['priority'],
            scrapers=scrapers,
            alert_level=alert_level,
            context={
                'current_hour': current_hour,
                'ideal_window': f"{ideal_start}-{ideal_end}"
            }
        )
    
    def _evaluate_game_aware(self, workflow_name: str, config: Dict, current_time: datetime, games_today: list) -> WorkflowDecision:
        """
        Evaluate game-aware workflow (e.g., betting_lines).
        
        Logic:
        1. Check if games today
        2. Check if within optimal window before games
        3. Check business hours
        4. Check frequency (not run too recently)
        5. Decide RUN or SKIP
        """
        schedule = config['schedule']
        
        # Check 1: Games today?
        if not games_today:
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason="No games scheduled today",
                workflow_name=workflow_name,
                priority=config['priority'],
                context={'games_today': 0},
                next_check_time=current_time + timedelta(hours=6)
            )
        
        # Check 2: Within window before first game?
        first_game = min(games_today, key=lambda g: g.commence_time)
        commence_dt = datetime.fromisoformat(first_game.commence_time.replace("Z", "+00:00"))
        hours_until_game = (commence_dt - current_time).total_seconds() / 3600
        window_hours = schedule.get('window_before_game_hours', 6)
        
        if hours_until_game > window_hours:
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason=f"First game in {hours_until_game:.1f}h (window starts {window_hours}h before)",
                workflow_name=workflow_name,
                priority=config['priority'],
                context={
                    'games_today': len(games_today),
                    'first_game_time': first_game.commence_time,
                    'hours_until_game': round(hours_until_game, 1)
                },
                next_check_time=commence_dt - timedelta(hours=window_hours)
            )
        
        # Check 3: Business hours?
        business_start = schedule.get('business_hours', {}).get('start', 8)
        business_end = schedule.get('business_hours', {}).get('end', 20)
        
        if current_time.hour < business_start or current_time.hour >= business_end:
            next_check = current_time.replace(hour=business_start, minute=0, second=0)
            if current_time.hour >= business_end:
                next_check += timedelta(days=1)
            
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason=f"Outside business hours ({business_start}-{business_end} ET)",
                workflow_name=workflow_name,
                priority=config['priority'],
                next_check_time=next_check
            )
        
        # Check 4: Run frequency
        frequency_hours = schedule.get('frequency_hours', 2)
        
        query = f"""
            SELECT MAX(triggered_at) as last_run
            FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
            WHERE workflow = '{workflow_name}'
              AND DATE(triggered_at) = CURRENT_DATE()
        """
        
        result = execute_bigquery(query)
        last_run = result[0]['last_run'] if result and result[0]['last_run'] else None
        
        if last_run:
            hours_since = (current_time - last_run).total_seconds() / 3600
            
            if hours_since < frequency_hours:
                return WorkflowDecision(
                    action=DecisionAction.SKIP,
                    reason=f"Ran {hours_since:.1f}h ago (frequency: every {frequency_hours}h)",
                    workflow_name=workflow_name,
                    priority=config['priority'],
                    next_check_time=last_run + timedelta(hours=frequency_hours),
                    context={'hours_since_last_run': round(hours_since, 1)}
                )
        
        # All checks passed - RUN
        scrapers = self._extract_scrapers_from_plan(config['execution_plan'])
        
        return WorkflowDecision(
            action=DecisionAction.RUN,
            reason=f"Ready: {len(games_today)} games today, {hours_until_game:.1f}h until first game",
            workflow_name=workflow_name,
            priority=config['priority'],
            scrapers=scrapers,
            context={
                'games_today': len(games_today),
                'first_game_time': first_game.commence_time,
                'hours_until_game': round(hours_until_game, 1)
            }
        )
    
    def _evaluate_post_game(self, workflow_name: str, config: Dict, current_time: datetime, games_yesterday: list) -> WorkflowDecision:
        """
        Evaluate post-game collection workflow.
        
        Logic:
        1. Check if games yesterday
        2. Check if in time window for this collection
        3. Check which games still need collection
        4. Decide RUN or SKIP
        """
        schedule = config['schedule']
        
        # Check 1: Games yesterday?
        if not games_yesterday:
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason="No games yesterday",
                workflow_name=workflow_name,
                priority=config['priority'],
                context={'games_yesterday': 0},
                next_check_time=current_time + timedelta(hours=6)
            )
        
        # Check 2: Time window
        fixed_time_str = schedule.get('fixed_time')  # e.g., "22:00"
        tolerance_minutes = schedule.get('tolerance_minutes', 30)
        
        if fixed_time_str:
            hour, minute = map(int, fixed_time_str.split(':'))
            window_time = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            time_diff_minutes = abs((current_time - window_time).total_seconds() / 60)
            
            if time_diff_minutes > tolerance_minutes:
                return WorkflowDecision(
                    action=DecisionAction.SKIP,
                    reason=f"Not in time window ({fixed_time_str} ±{tolerance_minutes}min)",
                    workflow_name=workflow_name,
                    priority=config['priority'],
                    next_check_time=window_time,
                    context={'time_diff_minutes': int(time_diff_minutes)}
                )
        
        # Check 3: Which games need collection?
        yesterday = (current_time.date() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        # Get games already collected (have box scores in BigQuery)
        query = f"""
            SELECT DISTINCT game_id
            FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
            WHERE game_date = '{yesterday}'
        """
        
        try:
            collected = execute_bigquery(query)
            collected_game_ids = {row['game_id'] for row in collected}
            
            missing_games = [g for g in games_yesterday if g.game_id not in collected_game_ids]
            
            if not missing_games:
                return WorkflowDecision(
                    action=DecisionAction.SKIP,
                    reason=f"All {len(games_yesterday)} games already collected",
                    workflow_name=workflow_name,
                    priority=config['priority'],
                    context={
                        'games_yesterday': len(games_yesterday),
                        'collected': len(collected_game_ids),
                        'missing': 0
                    },
                    next_check_time=current_time + timedelta(days=1)
                )
            
            # Determine alert level based on window
            alert_level = AlertLevel.NONE
            if "window_3" in workflow_name and missing_games:
                alert_level = AlertLevel.CRITICAL  # Should have all by window 3
            elif "window_2" in workflow_name and len(missing_games) > len(games_yesterday) * 0.2:
                alert_level = AlertLevel.WARNING  # >20% missing in window 2
            
            # RUN
            scrapers = self._extract_scrapers_from_plan(config['execution_plan'])
            
            return WorkflowDecision(
                action=DecisionAction.RUN,
                reason=f"{len(missing_games)} games need collection (window: {fixed_time_str})",
                workflow_name=workflow_name,
                priority=config['priority'],
                scrapers=scrapers,
                target_games=[g.game_id for g in missing_games],
                alert_level=alert_level,
                context={
                    'games_yesterday': len(games_yesterday),
                    'collected': len(collected_game_ids),
                    'missing': len(missing_games)
                }
            )
            
        except Exception as e:
            logger.error(f"Error checking collected games: {e}")
            # Assume need to collect, better to retry than skip
            scrapers = self._extract_scrapers_from_plan(config['execution_plan'])
            
            return WorkflowDecision(
                action=DecisionAction.RUN,
                reason=f"Cannot verify collected games, attempting collection",
                workflow_name=workflow_name,
                priority=config['priority'],
                scrapers=scrapers,
                alert_level=AlertLevel.WARNING,
                context={
                    'games_yesterday': len(games_yesterday),
                    'error': str(e)
                }
            )

    def _evaluate_early_game(self, workflow_name: str, config: Dict, current_time: datetime, games_today: list, today_str: str) -> WorkflowDecision:
        """
        Evaluate early game collection workflow (Christmas Day, MLK Day, etc.).

        Logic:
        1. Check if today has early games (games starting before 7 PM ET)
        2. Check if in time window for this collection
        3. Check which early games are finished and need collection
        4. Decide RUN or SKIP
        """
        schedule = config['schedule']
        early_game_cutoff_hour = schedule.get('early_game_cutoff_hour', 19)  # 7 PM default

        # Check 1: Any early games today?
        # Early games = games starting before the cutoff hour (in ET)
        et_tz = pytz.timezone('America/New_York')
        early_games = []

        for game in games_today:
            # Get game start time - NBAGame uses 'commence_time' (UTC string or datetime)
            commence_time = getattr(game, 'commence_time', None)
            if commence_time:
                # Parse if string, convert to ET
                if isinstance(commence_time, str):
                    from datetime import datetime as dt
                    # Format: "2025-12-25T17:00:00Z"
                    commence_time = dt.fromisoformat(commence_time.replace('Z', '+00:00'))

                # Convert to ET
                if commence_time.tzinfo is None:
                    commence_time = pytz.utc.localize(commence_time)
                game_time_et = commence_time.astimezone(et_tz)
                game_hour = game_time_et.hour

                if game_hour < early_game_cutoff_hour:
                    # Store the ET time on the game object for later use
                    game._game_time_et = game_time_et
                    early_games.append(game)

        if not early_games:
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason=f"No early games today (before {early_game_cutoff_hour}:00 ET)",
                workflow_name=workflow_name,
                priority=config['priority'],
                context={'total_games': len(games_today), 'early_games': 0},
                next_check_time=current_time + timedelta(hours=12)
            )

        # Check 2: Time window
        fixed_time_str = schedule.get('fixed_time')  # e.g., "15:00"
        tolerance_minutes = schedule.get('tolerance_minutes', 30)

        if fixed_time_str:
            hour, minute = map(int, fixed_time_str.split(':'))
            window_time = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)

            time_diff_minutes = abs((current_time - window_time).total_seconds() / 60)

            if time_diff_minutes > tolerance_minutes:
                return WorkflowDecision(
                    action=DecisionAction.SKIP,
                    reason=f"Not in time window ({fixed_time_str} ±{tolerance_minutes}min)",
                    workflow_name=workflow_name,
                    priority=config['priority'],
                    next_check_time=window_time,
                    context={
                        'early_games': len(early_games),
                        'time_diff_minutes': int(time_diff_minutes)
                    }
                )

        # Check 3: Which early games need collection?
        # Only target games that have likely finished (started 3+ hours ago)
        collection_delay_hours = schedule.get('collection_delay_hours', 3)
        finished_games = []

        for game in early_games:
            # Use the _game_time_et we stored earlier, or parse commence_time again
            game_start = getattr(game, '_game_time_et', None)
            if not game_start:
                commence_time = getattr(game, 'commence_time', None)
                if commence_time:
                    if isinstance(commence_time, str):
                        from datetime import datetime as dt
                        commence_time = dt.fromisoformat(commence_time.replace('Z', '+00:00'))
                    if commence_time.tzinfo is None:
                        commence_time = pytz.utc.localize(commence_time)
                    game_start = commence_time.astimezone(et_tz)

            if game_start:
                hours_since_start = (current_time - game_start).total_seconds() / 3600
                if hours_since_start >= collection_delay_hours:
                    finished_games.append(game)

        if not finished_games:
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason=f"No early games finished yet ({len(early_games)} early games, waiting {collection_delay_hours}h after start)",
                workflow_name=workflow_name,
                priority=config['priority'],
                context={
                    'early_games': len(early_games),
                    'finished': 0,
                    'collection_delay_hours': collection_delay_hours
                },
                next_check_time=current_time + timedelta(hours=1)
            )

        # Check 4: Which finished games are already collected?
        query = f"""
            SELECT DISTINCT game_id
            FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
            WHERE game_date = '{today_str}'
        """

        try:
            collected = execute_bigquery(query)
            collected_game_ids = {row['game_id'] for row in collected}

            missing_games = [g for g in finished_games if g.game_id not in collected_game_ids]

            if not missing_games:
                return WorkflowDecision(
                    action=DecisionAction.SKIP,
                    reason=f"All {len(finished_games)} finished early games already collected",
                    workflow_name=workflow_name,
                    priority=config['priority'],
                    context={
                        'early_games': len(early_games),
                        'finished': len(finished_games),
                        'collected': len(collected_game_ids),
                        'missing': 0
                    },
                    next_check_time=current_time + timedelta(hours=2)
                )

            # RUN - collect missing games
            scrapers = self._extract_scrapers_from_plan(config['execution_plan'])

            return WorkflowDecision(
                action=DecisionAction.RUN,
                reason=f"{len(missing_games)} early games need collection (window: {fixed_time_str})",
                workflow_name=workflow_name,
                priority=config['priority'],
                scrapers=scrapers,
                target_games=[g.game_id for g in missing_games],
                context={
                    'early_games': len(early_games),
                    'finished': len(finished_games),
                    'collected': len(collected_game_ids),
                    'missing': len(missing_games)
                }
            )

        except Exception as e:
            logger.error(f"Error checking collected early games: {e}")
            scrapers = self._extract_scrapers_from_plan(config['execution_plan'])

            return WorkflowDecision(
                action=DecisionAction.RUN,
                reason=f"Cannot verify collected early games, attempting collection",
                workflow_name=workflow_name,
                priority=config['priority'],
                scrapers=scrapers,
                alert_level=AlertLevel.WARNING,
                context={
                    'early_games': len(early_games),
                    'error': str(e)
                }
            )

    def _evaluate_discovery(self, workflow_name: str, config: Dict, current_time: datetime, games_today: list) -> WorkflowDecision:
        """
        Evaluate discovery mode workflow.
        
        Logic:
        1. Check if already succeeded today
        2. Check if game day required
        3. Check recent attempts (retry interval)
        4. Check max attempts
        5. Check discovery duration
        6. Decide RUN or SKIP
        """
        schedule = config['schedule']
        scraper_name = config['execution_plan']['scraper']
        
        # Check 1: Already succeeded today?
        # CRITICAL FIX: Check game_date (data date) not triggered_at (execution date)
        # Prevents false positive where scraper runs on Jan 2 but finds Jan 1 data
        query = f"""
            SELECT MAX(triggered_at) as last_success
            FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
            WHERE scraper_name = '{scraper_name}'
              AND status = 'success'
              AND (
                -- NEW: Check if we found data for TODAY's date (prevents false positive)
                game_date = CURRENT_DATE()
                -- Backward compatibility: Fall back to execution date if game_date is NULL
                -- (for legacy runs or scrapers that don't use gamedate parameter)
                OR (game_date IS NULL AND DATE(triggered_at) = CURRENT_DATE())
              )
        """

        result = execute_bigquery(query)
        last_success = result[0]['last_success'] if result and result[0]['last_success'] else None

        if last_success:
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason="Already found data for today's date",
                workflow_name=workflow_name,
                priority=config['priority'],
                context={
                    'success_time': last_success.strftime('%H:%M')
                },
                next_check_time=current_time + timedelta(days=1)
            )
        
        # Check 2: Game day required?
        if schedule.get('requires_game_day', False) and not games_today:
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason="No games today (only run on game days)",
                workflow_name=workflow_name,
                priority=config['priority'],
                context={'games_today': 0},
                next_check_time=current_time + timedelta(hours=6)
            )
        
        # Check 3: Recent attempt?
        retry_interval = schedule.get('retry_interval_hours', 1)
        
        query = f"""
            SELECT MAX(triggered_at) as last_attempt
            FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
            WHERE scraper_name = '{scraper_name}'
              AND DATE(triggered_at) = CURRENT_DATE()
        """
        
        result = execute_bigquery(query)
        last_attempt = result[0]['last_attempt'] if result and result[0]['last_attempt'] else None
        
        if last_attempt:
            hours_since = (current_time - last_attempt).total_seconds() / 3600
            
            if hours_since < retry_interval:
                return WorkflowDecision(
                    action=DecisionAction.SKIP,
                    reason=f"Tried {hours_since:.1f}h ago (retry interval: {retry_interval}h)",
                    workflow_name=workflow_name,
                    priority=config['priority'],
                    next_check_time=last_attempt + timedelta(hours=retry_interval),
                    context={'hours_since_last_attempt': round(hours_since, 1)}
                )
        
        # Check 4: Max attempts today?
        max_attempts = schedule.get('max_attempts_per_day', 12)
        
        query = f"""
            SELECT COUNT(*) as attempts_today
            FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
            WHERE scraper_name = '{scraper_name}'
              AND DATE(triggered_at) = CURRENT_DATE()
        """
        
        result = execute_bigquery(query)
        attempts_today = result[0]['attempts_today'] if result else 0
        
        if attempts_today >= max_attempts:
            return WorkflowDecision(
                action=DecisionAction.SKIP,
                reason=f"Max attempts reached ({attempts_today}/{max_attempts})",
                workflow_name=workflow_name,
                priority=config['priority'],
                alert_level=AlertLevel.WARNING,
                context={'attempts_today': attempts_today, 'max_attempts': max_attempts},
                next_check_time=current_time + timedelta(days=1)
            )
        
        # All checks passed - RUN
        return WorkflowDecision(
            action=DecisionAction.RUN,
            reason=f"Discovery attempt {attempts_today + 1}/{max_attempts}",
            workflow_name=workflow_name,
            priority=config['priority'],
            scrapers=[scraper_name],
            context={
                'attempts_today': attempts_today,
                'max_attempts': max_attempts,
                'games_today': len(games_today) if games_today else 0
            }
        )
    
    def _extract_scrapers_from_plan(self, execution_plan: Dict) -> List[str]:
        """
        Extract list of scrapers from execution plan.
        
        Handles various plan structures:
        - Simple: {"type": "parallel", "scrapers": [...]}
        - Multi-step: {"step_1": {...}, "step_2": {...}}
        """
        scrapers = []
        
        # Simple case
        if 'scrapers' in execution_plan:
            scrapers.extend(execution_plan['scrapers'])
        
        # Single scraper
        if 'scraper' in execution_plan:
            scrapers.append(execution_plan['scraper'])
        
        # Multi-step
        for key, value in execution_plan.items():
            if isinstance(value, dict):
                if 'scrapers' in value:
                    scrapers.extend(value['scrapers'])
                if 'scraper' in value:
                    scrapers.append(value['scraper'])
        
        return scrapers
    
    def _log_decisions(self, decisions: List[WorkflowDecision]) -> None:
        """Log all decisions to BigQuery."""
        if not decisions:
            return
        
        records = []
        
        for decision in decisions:
            record = {
                'decision_id': str(uuid.uuid4()),
                'decision_time': datetime.utcnow().isoformat(),
                'workflow_name': decision.workflow_name,
                'action': decision.action.value,
                'reason': decision.reason,
                'context': json.dumps(decision.context) if decision.context else None,  # Must be JSON string for streaming insert
                'scrapers_triggered': decision.scrapers if decision.scrapers else [],
                'target_games': decision.target_games if decision.target_games else [],
                'next_check_time': decision.next_check_time.isoformat() if decision.next_check_time else None,
                'priority': decision.priority,
                'alert_level': decision.alert_level.value,
                'controller_version': self.VERSION,
                'environment': self.config.get_settings().get('environment', 'unknown'),
                'triggered_by': 'master_controller'
            }
            
            records.append(record)
        
        try:
            insert_bigquery_rows('nba_orchestration.workflow_decisions', records)
            logger.info(f"✅ Logged {len(records)} workflow decisions to BigQuery")
        except Exception as e:
            logger.error(f"Failed to log decisions to BigQuery: {e}")
