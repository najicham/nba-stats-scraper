"""
orchestration/workflow_executor.py

Workflow Executor - Executes workflows by calling scraper endpoints via HTTP

Phase 1 Implementation:
- Reads RUN decisions from BigQuery
- Resolves parameters for each scraper
- Calls scraper service via HTTP
- Tracks execution status
- Logs to workflow_executions table

Version 1.1: Added deduplication check to prevent duplicate executions

Path: orchestration/workflow_executor.py
"""

import logging
import uuid
import os
import time
import random
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from orchestration.parameter_resolver import ParameterResolver
from orchestration.config_loader import WorkflowConfig
from shared.utils.bigquery_utils import execute_bigquery, insert_bigquery_rows
from orchestration.shared.utils.circuit_breaker import (
    CircuitBreakerManager,
    CircuitBreakerConfig,
    CircuitBreakerOpenError
)
from shared.clients.http_pool import get_http_session

logger = logging.getLogger(__name__)

# Global config instance for timeout settings
_workflow_config = WorkflowConfig()


@dataclass
class ScraperExecution:
    """Result of a single scraper execution."""
    scraper_name: str
    status: str  # 'success', 'failed', 'no_data'
    execution_id: Optional[str] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    record_count: Optional[int] = None
    data_summary: Optional[Dict[str, Any]] = None  # Full stats from scraper (includes event_ids, etc.)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class WorkflowExecution:
    """Result of a complete workflow execution."""
    execution_id: str
    workflow_name: str
    decision_id: Optional[str]
    execution_time: datetime
    status: str  # 'started', 'in_progress', 'completed', 'failed'
    scrapers_requested: List[str]
    scrapers_triggered: int
    scrapers_succeeded: int
    scrapers_failed: int
    scraper_executions: List[ScraperExecution]
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for BigQuery insertion."""
        return {
            'execution_id': self.execution_id,
            'workflow_name': self.workflow_name,
            'decision_id': self.decision_id,
            'execution_time': self.execution_time.isoformat(),
            'status': self.status,
            'scrapers_requested': self.scrapers_requested,
            'scrapers_triggered': self.scrapers_triggered,
            'scrapers_succeeded': self.scrapers_succeeded,
            'scrapers_failed': self.scrapers_failed,
            'scraper_execution_ids': [s.execution_id for s in self.scraper_executions if s.execution_id],
            'duration_seconds': self.duration_seconds,
            'error_message': self.error_message
        }


class WorkflowExecutor:
    """
    Executes workflows by calling scraper service endpoints via HTTP.
    
    Architecture:
        1. Read RUN decisions from workflow_decisions table
        2. For each decision, resolve parameters for each scraper
        3. Call scraper service via POST /scrape
        4. Track execution status
        5. Log to workflow_executions table
    
    Design Principles:
        - HTTP-based (not direct Python imports)
        - Synchronous execution for Phase 1 (async in Phase 3)
        - Continue on error (attempt all scrapers)
        - Comprehensive logging for debugging
        - Deduplication: Skip decisions that were already executed
    """
    
    # Service URL for calling scrapers
    # Default to localhost for same-service calls, override via env var
    SERVICE_URL = os.getenv("SERVICE_URL", "http://localhost:8080")

    # Default timeouts (can be overridden via config/workflows.yaml settings.scraper_timeouts)
    DEFAULT_SCRAPER_TIMEOUT = 180  # 3 minutes
    DEFAULT_FUTURE_OVERHEAD = 10   # Extra time for ThreadPoolExecutor overhead

    def __init__(self):
        """Initialize executor with parameter resolver."""
        self.parameter_resolver = ParameterResolver()

        # Circuit breaker manager for handling flaky scrapers
        self.circuit_breaker_enabled = os.getenv("ENABLE_CIRCUIT_BREAKER", "true").lower() == "true"

        if self.circuit_breaker_enabled:
            self.circuit_breaker_manager = CircuitBreakerManager(
                config=CircuitBreakerConfig(
                    max_failures=5,        # Open circuit after 5 failures
                    timeout_seconds=300,   # Test recovery after 5 minutes
                    half_open_attempts=3,  # Need 3 successes to close
                    failure_threshold_window=60  # Count failures in 60s window
                )
            )
            logger.info("✅ Circuit breaker enabled for scrapers")
        else:
            self.circuit_breaker_manager = None
            logger.warning("⚠️  Circuit breaker DISABLED")

    def _get_scraper_timeout(self, scraper_name: str) -> int:
        """
        Get the timeout for a specific scraper from config.

        Checks in order:
        1. Per-scraper override in settings.scraper_timeouts.overrides
        2. Default timeout in settings.scraper_timeouts.default
        3. Class default (DEFAULT_SCRAPER_TIMEOUT)

        Args:
            scraper_name: Name of the scraper

        Returns:
            Timeout in seconds
        """
        try:
            settings = _workflow_config.get_settings()
            timeout_config = settings.get('scraper_timeouts', {})

            # Check for per-scraper override
            overrides = timeout_config.get('overrides', {})
            if scraper_name in overrides:
                return overrides[scraper_name]

            # Use default from config or class default
            return timeout_config.get('default', self.DEFAULT_SCRAPER_TIMEOUT)

        except Exception as e:
            logger.warning(f"Failed to load timeout config: {e}, using default")
            return self.DEFAULT_SCRAPER_TIMEOUT

    def _get_future_timeout(self, scraper_name: str) -> int:
        """
        Get the future timeout for parallel execution.

        This is the scraper timeout plus overhead for ThreadPoolExecutor.

        Args:
            scraper_name: Name of the scraper

        Returns:
            Future timeout in seconds
        """
        scraper_timeout = self._get_scraper_timeout(scraper_name)

        try:
            settings = _workflow_config.get_settings()
            timeout_config = settings.get('scraper_timeouts', {})
            overhead = timeout_config.get('future_overhead', self.DEFAULT_FUTURE_OVERHEAD)
        except Exception:
            overhead = self.DEFAULT_FUTURE_OVERHEAD

        return scraper_timeout + overhead

    @staticmethod
    def _calculate_jittered_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 30.0) -> float:
        """
        Calculate exponential backoff with jitter to prevent thundering herd.

        Uses decorrelated jitter algorithm (AWS recommended):
        delay = base * (2 ** attempt) * random.uniform(0.5, 1.5)

        Args:
            attempt: Current retry attempt number (1-based)
            base_delay: Base delay in seconds
            max_delay: Maximum delay cap

        Returns:
            Delay in seconds with jitter applied
        """
        # Exponential component: 2^attempt
        exponential = base_delay * (2 ** (attempt - 1))

        # Add jitter: random factor between 0.5 and 1.5
        # This spreads retries across time instead of synchronized bursts
        jittered = exponential * random.uniform(0.5, 1.5)

        # Cap at max_delay
        return min(jittered, max_delay)

    def execute_pending_workflows(self) -> Dict[str, Any]:
        """
        Main entry point: Execute all pending RUN decisions.
        
        Reads workflow_decisions table for unexecuted RUN decisions,
        executes each workflow, and returns summary.
        
        CRITICAL: Uses LEFT JOIN to skip decisions that already have executions.
        This prevents duplicate execution when called multiple times.
        
        Returns:
            Dict with execution summary
        """
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("🚀 Workflow Executor: Executing pending workflows")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        start_time = datetime.now(timezone.utc)
        
        # Query for unexecuted RUN decisions from the last hour
        # CRITICAL: LEFT JOIN prevents duplicate executions
        # Week 1: Added DATE() filter for partition pruning (cost optimization)
        query = """
            SELECT
                d.decision_id,
                d.workflow_name,
                d.scrapers_triggered,
                d.target_games,
                d.decision_time
            FROM `nba-props-platform.nba_orchestration.workflow_decisions` d
            LEFT JOIN `nba-props-platform.nba_orchestration.workflow_executions` e
                ON d.decision_id = e.decision_id
            WHERE d.action = 'RUN'
              AND DATE(d.decision_time) = CURRENT_DATE()
              AND d.decision_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
              AND e.execution_id IS NULL
            ORDER BY d.decision_time DESC
        """
        
        try:
            decisions = execute_bigquery(query)
            
            if not decisions:
                logger.info("📭 No pending workflows to execute")
                return {
                    'status': 'success',
                    'workflows_executed': 0,
                    'duration_seconds': 0
                }
            
            logger.info(f"📋 Found {len(decisions)} workflow(s) to execute")
            
            executions = []
            
            for decision in decisions:
                workflow_name = decision['workflow_name']
                scrapers = decision['scrapers_triggered'] or []
                target_games = decision.get('target_games', [])
                decision_id = decision['decision_id']
                
                logger.info(f"\n▶️  Executing: {workflow_name} ({len(scrapers)} scrapers)")
                
                try:
                    execution = self.execute_workflow(
                        workflow_name=workflow_name,
                        scrapers=scrapers,
                        decision_id=decision_id,
                        target_games=target_games
                    )
                    executions.append(execution)
                    
                except Exception as e:
                    logger.error(f"❌ Workflow {workflow_name} failed: {e}", exc_info=True)
                    # Log failed execution
                    failed_execution = WorkflowExecution(
                        execution_id=str(uuid.uuid4()),
                        workflow_name=workflow_name,
                        decision_id=decision_id,
                        execution_time=datetime.now(timezone.utc),
                        status='failed',
                        scrapers_requested=scrapers,
                        scrapers_triggered=0,
                        scrapers_succeeded=0,
                        scrapers_failed=0,
                        scraper_executions=[],
                        error_message=str(e)
                    )
                    executions.append(failed_execution)
                    self._log_workflow_execution(failed_execution)
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            # Summary
            total_succeeded = sum(1 for e in executions if e.status == 'completed')
            total_failed = sum(1 for e in executions if e.status == 'failed')
            
            logger.info("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"✅ Execution Complete")
            logger.info(f"   Workflows: {len(executions)}")
            logger.info(f"   Succeeded: {total_succeeded}")
            logger.info(f"   Failed: {total_failed}")
            logger.info(f"   Duration: {duration:.1f}s")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
            
            return {
                'status': 'success',
                'workflows_executed': len(executions),
                'succeeded': total_succeeded,
                'failed': total_failed,
                'duration_seconds': duration,
                'executions': [e.to_dict() for e in executions]
            }
            
        except Exception as e:
            logger.error(f"Failed to execute pending workflows: {e}", exc_info=True)
            return {
                'status': 'error',
                'error': str(e),
                'workflows_executed': 0
            }
    
    def _execute_single_scraper(
        self,
        scraper_name: str,
        context: Dict[str, Any],
        workflow_name: str
    ) -> List[ScraperExecution]:
        """
        Execute a single scraper (helper for parallel execution).

        Args:
            scraper_name: Name of scraper to execute
            context: Workflow context for parameter resolution
            workflow_name: Name of the workflow

        Returns:
            List of ScraperExecution results (list because multi-entity scrapers return multiple)
        """
        executions = []

        try:
            logger.info(f"\n🔧 Executing scraper: {scraper_name}")

            # Resolve parameters for this scraper
            parameters = self.parameter_resolver.resolve_parameters(
                scraper_name=scraper_name,
                workflow_context=context
            )

            # Handle multi-entity scrapers (returns list of parameter sets)
            if isinstance(parameters, list):
                if not parameters:
                    logger.warning(f"   Skipping {scraper_name} - empty parameter list")
                    return executions

                logger.info(f"   Multi-entity scraper: {len(parameters)} entities")

                # Execute scraper for each parameter set
                for idx, params in enumerate(parameters, 1):
                    logger.info(f"   [{idx}/{len(parameters)}] Parameters: {params}")

                    execution = self._call_scraper(
                        scraper_name=scraper_name,
                        parameters=params,
                        workflow_name=workflow_name
                    )

                    executions.append(execution)

                    if execution.status == 'success':
                        logger.info(f"      ✅ SUCCESS")
                    elif execution.status == 'no_data':
                        logger.info(f"      ⚠️  NO DATA")
                    else:
                        logger.error(f"      ❌ FAILED - {execution.error_message}")

            else:
                # Single parameter set
                logger.info(f"   Parameters: {parameters}")

                # Call scraper via HTTP
                execution = self._call_scraper(
                    scraper_name=scraper_name,
                    parameters=parameters,
                    workflow_name=workflow_name
                )

                executions.append(execution)

                if execution.status == 'success':
                    logger.info(f"✅ {scraper_name}: SUCCESS")
                elif execution.status == 'no_data':
                    logger.info(f"⚠️  {scraper_name}: NO DATA")
                else:
                    logger.error(f"❌ {scraper_name}: FAILED - {execution.error_message}")

        except Exception as e:
            logger.error(f"❌ {scraper_name}: EXCEPTION - {e}", exc_info=True)
            executions.append(ScraperExecution(
                scraper_name=scraper_name,
                status='failed',
                error_message=str(e)
            ))

        return executions

    def execute_workflow(
        self,
        workflow_name: str,
        scrapers: List[str],
        decision_id: Optional[str] = None,
        target_games: Optional[List[str]] = None,
        target_date: Optional[str] = None
    ) -> WorkflowExecution:
        """
        Execute a single workflow by calling its scrapers.

        Args:
            workflow_name: Workflow identifier
            scrapers: List of scraper names to execute
            decision_id: Optional decision ID that triggered this execution
            target_games: Optional list of game IDs to process
            target_date: Optional explicit target date (YYYY-MM-DD) for game fetching.
                         If not provided, inferred from workflow_name:
                         - post_game_* workflows → yesterday
                         - Other workflows → today

        Returns:
            WorkflowExecution with results
        """
        execution_id = str(uuid.uuid4())
        start_time = datetime.now(timezone.utc)

        # Week 1: Use config to detect if this workflow should run in parallel
        from shared.config.orchestration_config import get_orchestration_config
        orch_config = get_orchestration_config()
        use_parallel = orch_config.workflow_execution.is_parallel(workflow_name)
        max_workers = orch_config.workflow_execution.max_workers

        logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"▶️  Executing Workflow: {workflow_name}")
        logger.info(f"   Execution ID: {execution_id}")
        logger.info(f"   Decision ID: {decision_id or 'manual'}")
        logger.info(f"   Scrapers: {len(scrapers)}")
        logger.info(f"   Execution Mode: {'🚀 PARALLEL' if use_parallel else 'Sequential'}")
        if use_parallel:
            logger.info(f"   Max Workers: {max_workers}")
        if target_games:
            logger.info(f"   Target Games: {len(target_games)}")
        if target_date:
            logger.info(f"   Target Date: {target_date}")
        logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Build workflow context for parameter resolution
        # Note: target_date may be None - the parameter resolver will infer
        # the correct date based on workflow_name (yesterday for post_game_*)
        context = self.parameter_resolver.build_workflow_context(
            workflow_name=workflow_name,
            target_games=target_games,
            target_date=target_date
        )

        scraper_executions = []

        # Execute scrapers (parallel or sequential)
        if use_parallel:
            # Week 1: PARALLEL EXECUTION (now config-driven!)
            actual_workers = min(max_workers, len(scrapers))
            logger.info(f"🚀 Running {len(scrapers)} scrapers in PARALLEL (max_workers={actual_workers})")

            with ThreadPoolExecutor(max_workers=actual_workers) as executor:
                # Submit all scrapers for parallel execution
                futures = {
                    executor.submit(self._execute_single_scraper, scraper_name, context, workflow_name): scraper_name
                    for scraper_name in scrapers
                }

                # Collect results as they complete
                for future in as_completed(futures):
                    scraper_name = futures[future]
                    future_timeout = self._get_future_timeout(scraper_name)
                    try:
                        results = future.result(timeout=future_timeout)  # Configurable per-scraper timeout
                        scraper_executions.extend(results)
                    except TimeoutError:
                        logger.error(f"⏱️ Scraper {scraper_name} timed out after {future_timeout}s")
                        scraper_executions.append(ScraperExecution(
                            scraper_name=scraper_name,
                            status='failed',
                            error_message=f'Timeout after {future_timeout}s'
                        ))
                    except Exception as e:
                        logger.error(f"❌ Failed to get result from {scraper_name}: {e}")
                        scraper_executions.append(ScraperExecution(
                            scraper_name=scraper_name,
                            status='failed',
                            error_message=str(e)
                        ))

        else:
            # SEQUENTIAL EXECUTION (original behavior)
            for scraper_name in scrapers:
                try:
                    logger.info(f"\n🔧 Executing scraper: {scraper_name}")

                    # Resolve parameters for this scraper
                    parameters = self.parameter_resolver.resolve_parameters(
                        scraper_name=scraper_name,
                        workflow_context=context
                    )

                    # Handle multi-entity scrapers (returns list of parameter sets)
                    if isinstance(parameters, list):
                        if not parameters:
                            logger.warning(f"   Skipping {scraper_name} - empty parameter list")
                            continue

                        logger.info(f"   Multi-entity scraper: {len(parameters)} entities")

                        # Execute scraper for each parameter set
                        for idx, params in enumerate(parameters, 1):
                            logger.info(f"   [{idx}/{len(parameters)}] Parameters: {params}")

                            execution = self._call_scraper(
                                scraper_name=scraper_name,
                                parameters=params,
                                workflow_name=workflow_name
                            )

                            scraper_executions.append(execution)

                            if execution.status == 'success':
                                logger.info(f"      ✅ SUCCESS")
                            elif execution.status == 'no_data':
                                logger.info(f"      ⚠️  NO DATA")
                            else:
                                logger.error(f"      ❌ FAILED - {execution.error_message}")

                    else:
                        # Single parameter set
                        logger.info(f"   Parameters: {parameters}")

                        # Call scraper via HTTP
                        execution = self._call_scraper(
                            scraper_name=scraper_name,
                            parameters=parameters,
                            workflow_name=workflow_name
                        )

                        scraper_executions.append(execution)

                        if execution.status == 'success':
                            logger.info(f"✅ {scraper_name}: SUCCESS")

                            # SPECIAL: Capture event_ids from oddsa_events for downstream scrapers
                            if scraper_name == 'oddsa_events':
                                event_ids = self._extract_event_ids_from_execution(execution)
                                if event_ids:
                                    context['event_ids'] = event_ids
                                    logger.info(f"   📋 Captured {len(event_ids)} event_ids for downstream scrapers")

                        elif execution.status == 'no_data':
                            logger.info(f"⚠️  {scraper_name}: NO DATA")
                        else:
                            logger.error(f"❌ {scraper_name}: FAILED - {execution.error_message}")

                except Exception as e:
                    logger.error(f"❌ {scraper_name}: EXCEPTION - {e}", exc_info=True)
                    scraper_executions.append(ScraperExecution(
                        scraper_name=scraper_name,
                        status='failed',
                        error_message=str(e)
                ))
        
        # Calculate statistics
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        succeeded = sum(1 for s in scraper_executions if s.status in ['success', 'no_data'])
        failed = sum(1 for s in scraper_executions if s.status == 'failed')

        # Aggregate error messages from failed scrapers for debugging
        error_messages = []
        for s in scraper_executions:
            if s.status == 'failed' and s.error_message:
                error_messages.append(f"{s.scraper_name}: {s.error_message}")

        workflow_error_message = None
        if error_messages:
            # Combine all errors (truncate if too long for BigQuery STRING limit)
            combined_errors = " | ".join(error_messages)
            workflow_error_message = combined_errors[:1000]  # BigQuery STRING field limit

        # Determine overall workflow status
        if failed == 0:
            status = 'completed'
        elif succeeded > 0:
            status = 'completed'  # Partial success
        else:
            status = 'failed'

        workflow_execution = WorkflowExecution(
            execution_id=execution_id,
            workflow_name=workflow_name,
            decision_id=decision_id,
            execution_time=start_time,
            status=status,
            scrapers_requested=scrapers,
            scrapers_triggered=len(scraper_executions),
            scrapers_succeeded=succeeded,
            scrapers_failed=failed,
            scraper_executions=scraper_executions,
            duration_seconds=duration,
            error_message=workflow_error_message
        )
        
        # Log to BigQuery
        self._log_workflow_execution(workflow_execution)
        
        logger.info(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"✅ Workflow Complete: {workflow_name}")
        logger.info(f"   Duration: {duration:.1f}s")
        logger.info(f"   Success: {succeeded}/{len(scrapers)}")
        logger.info(f"   Failed: {failed}/{len(scrapers)}")
        logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        
        return workflow_execution
    
    def _call_scraper(
        self,
        scraper_name: str,
        parameters: Dict[str, Any],
        workflow_name: str,
        max_retries: int = 3
    ) -> ScraperExecution:
        """
        Call a scraper endpoint via HTTP with automatic retry on transient errors.

        Includes circuit breaker protection to fail fast on consistently failing scrapers.

        Retries on:
        - HTTP 429 (rate limit)
        - HTTP 5xx (server errors)
        - Timeouts
        - Connection errors

        Does NOT retry on:
        - HTTP 4xx (except 429) - client errors
        - HTTP 200 with no_data - expected response
        - Circuit breaker open (fails immediately)

        Args:
            scraper_name: Name of scraper to call
            parameters: Parameters to pass to scraper
            workflow_name: Workflow name for logging
            max_retries: Maximum retry attempts (default: 3)

        Returns:
            ScraperExecution with result
        """
        # Check circuit breaker before attempting
        if self.circuit_breaker_enabled and self.circuit_breaker_manager:
            breaker = self.circuit_breaker_manager.get_breaker(scraper_name)

            try:
                # Use circuit breaker to protect scraper call
                return breaker.call(
                    self._call_scraper_internal,
                    scraper_name,
                    parameters,
                    workflow_name,
                    max_retries
                )
            except CircuitBreakerOpenError as e:
                logger.warning(f"⚡ {e}")
                # Return failed execution without attempting scraper
                return ScraperExecution(
                    scraper_name=scraper_name,
                    status='circuit_open',
                    duration_seconds=0,
                    error_message=f"Circuit breaker open: {str(e)}"
                )
        else:
            # No circuit breaker - call directly
            return self._call_scraper_internal(
                scraper_name,
                parameters,
                workflow_name,
                max_retries
            )

    def _call_scraper_internal(
        self,
        scraper_name: str,
        parameters: Dict[str, Any],
        workflow_name: str,
        max_retries: int = 3
    ) -> ScraperExecution:
        """
        Internal method that performs actual scraper HTTP call.

        Separated from _call_scraper() to allow circuit breaker wrapping.

        Args:
            scraper_name: Name of scraper to call
            parameters: Parameters to pass to scraper
            workflow_name: Workflow name for logging
            max_retries: Maximum retry attempts

        Returns:
            ScraperExecution with result
        """
        start_time = datetime.now(timezone.utc)

        # Add workflow context to parameters
        parameters['workflow'] = workflow_name
        parameters['source'] = 'CONTROLLER'
        parameters['scraper'] = scraper_name

        last_error_msg = None

        # Get configurable timeout for this scraper (before loop so it's available in except blocks)
        scraper_timeout = self._get_scraper_timeout(scraper_name)

        for attempt in range(1, max_retries + 1):
            try:
                # Call scraper service via POST /scrape
                url = f"{self.SERVICE_URL}/scrape"

                if attempt > 1:
                    logger.info(f"   🔄 Retry attempt {attempt}/{max_retries} for {scraper_name}")

                logger.debug(f"Calling scraper service: POST {url}")
                logger.debug(f"Payload: {json.dumps(parameters, indent=2)}")

                # Use pooled HTTP session with per-scraper configurable timeout
                session = get_http_session(timeout=scraper_timeout)
                response = session.post(url, json=parameters)

                duration = (datetime.now(timezone.utc) - start_time).total_seconds()

                # SUCCESS - Parse response
                if response.status_code == 200:
                    result = response.json()

                    # Extract execution info
                    execution_id = result.get('run_id')

                    # Determine status from response
                    # Scraper returns status in data_summary
                    data_summary = result.get('data_summary', {})
                    record_count = data_summary.get('rowCount', 0)

                    if record_count > 0:
                        status = 'success'
                    else:
                        status = 'no_data'

                    if attempt > 1:
                        logger.info(f"   ✅ Retry successful after {attempt} attempts")

                    return ScraperExecution(
                        scraper_name=scraper_name,
                        status=status,
                        execution_id=execution_id,
                        duration_seconds=duration,
                        record_count=record_count,
                        data_summary=data_summary  # Store full stats for downstream use
                    )

                # CLIENT ERROR (4xx except 429) - Don't retry
                elif 400 <= response.status_code < 500 and response.status_code != 429:
                    error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.error(f"Client error (not retrying): {error_msg}")

                    return ScraperExecution(
                        scraper_name=scraper_name,
                        status='failed',
                        duration_seconds=duration,
                        error_message=error_msg
                    )

                # RETRYABLE ERROR - 429, 5xx
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                    last_error_msg = error_msg
                    logger.warning(f"Retryable error: {error_msg}")

                    if attempt < max_retries:
                        # Exponential backoff with jitter (prevents thundering herd)
                        wait_time = self._calculate_jittered_backoff(attempt)
                        logger.info(f"   ⏳ Waiting {wait_time:.2f}s before retry...")
                        time.sleep(wait_time)
                        continue
                    else:
                        # Max retries exceeded
                        final_msg = f"{error_msg} (failed after {max_retries} retries)"
                        logger.error(f"Max retries exceeded: {final_msg}")
                        return ScraperExecution(
                            scraper_name=scraper_name,
                            status='failed',
                            duration_seconds=duration,
                            error_message=final_msg
                        )

            except requests.Timeout:
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                error_msg = f"Timeout after {scraper_timeout}s"
                last_error_msg = error_msg
                logger.warning(f"Timeout: {error_msg}")

                if attempt < max_retries:
                    wait_time = self._calculate_jittered_backoff(attempt)
                    logger.info(f"   ⏳ Waiting {wait_time:.2f}s before retry...")
                    time.sleep(wait_time)
                    continue
                else:
                    final_msg = f"{error_msg} (failed after {max_retries} retries)"
                    logger.error(f"Max retries exceeded: {final_msg}")
                    return ScraperExecution(
                        scraper_name=scraper_name,
                        status='failed',
                        duration_seconds=duration,
                        error_message=final_msg
                    )

            except Exception as e:
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                error_msg = str(e)
                last_error_msg = error_msg
                logger.warning(f"Exception: {error_msg}")

                if attempt < max_retries:
                    wait_time = self._calculate_jittered_backoff(attempt)
                    logger.info(f"   ⏳ Waiting {wait_time:.2f}s before retry...")
                    time.sleep(wait_time)
                    continue
                else:
                    final_msg = f"{error_msg} (failed after {max_retries} retries)"
                    logger.error(f"Max retries exceeded: {final_msg}")
                    return ScraperExecution(
                        scraper_name=scraper_name,
                        status='failed',
                        duration_seconds=duration,
                        error_message=final_msg
                    )

        # Should never reach here, but just in case
        return ScraperExecution(
            scraper_name=scraper_name,
            status='failed',
            error_message=f"Unknown error after {max_retries} retries: {last_error_msg}"
        )

    def _extract_event_ids_from_execution(self, execution: ScraperExecution) -> List[str]:
        """
        Extract event_ids from oddsa_events scraper execution.

        The oddsa_events scraper includes event_ids in its data_summary for downstream
        scrapers (oddsa_player_props, oddsa_game_lines) to use.

        Args:
            execution: ScraperExecution from oddsa_events call

        Returns:
            List of event IDs (strings), or empty list if not available
        """
        if not execution.data_summary:
            logger.warning("No data_summary in execution - cannot extract event_ids")
            return []

        event_ids = execution.data_summary.get('event_ids', [])

        if not event_ids:
            logger.warning("No event_ids found in data_summary")
            return []

        logger.debug(f"Extracted {len(event_ids)} event_ids: {event_ids}")
        return event_ids

    def _log_workflow_execution(self, execution: WorkflowExecution) -> None:
        """Log workflow execution to BigQuery."""
        try:
            record = execution.to_dict()
            insert_bigquery_rows('nba_orchestration.workflow_executions', [record])
            logger.debug(f"✅ Logged workflow execution to BigQuery: {execution.execution_id}")
        except Exception as e:
            logger.error(f"Failed to log workflow execution: {e}")
            # Don't fail the workflow if logging fails - execution already completed
            # TODO: Add monitoring/alerting for logging failures to detect BigQuery issues
            # Metric: workflow_execution_logging_errors_total