"""
File: analytics_processors/main_analytics_service.py

Main analytics service for Cloud Run
Handles Pub/Sub messages when raw data processing completes
"""

import os
import sys
import json
import logging
from functools import wraps
from flask import Flask, request, jsonify

# Add project root to path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Initialize Sentry first (before other imports that might error)
from shared.utils.sentry_config import configure_sentry
configure_sentry()

# Startup verification - MUST be early to detect wrong code deployment
try:
    from shared.utils.startup_verification import verify_startup
    verify_startup(
        expected_module="analytics-processor",
        service_name="nba-phase3-analytics-processors"
    )
except ImportError:
    # Shared module not available (local dev without full setup)
    logging.warning("startup_verification not available - running without verification")

from shared.endpoints.health import create_health_blueprint, HealthChecker
from shared.utils.validation import validate_game_date, validate_project_id, ValidationError
from shared.config.gcp_config import get_project_id
from datetime import datetime, timezone, date, timedelta
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import analytics processors
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import TeamOffenseGameSummaryProcessor
from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import TeamDefenseGameSummaryProcessor
from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
from data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor import UpcomingTeamGameContextProcessor

# Import async orchestration utilities for improved concurrency
from data_processors.analytics.async_orchestration import (
    run_processor_with_async_support,
    run_processors_concurrently,
)

# Import BigQuery client for completeness checks
from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# RACE CONDITION PREVENTION (Session 124 - Tier 1)
# ============================================================================

class DependencyFailureError(Exception):
    """Raised when a critical dependency processor fails."""
    pass

# Feature flag for rollback capability
SEQUENTIAL_EXECUTION_ENABLED = os.environ.get(
    'SEQUENTIAL_EXECUTION_ENABLED', 'true'
).lower() == 'true'

# Group-level timeouts (minutes)
GROUP_TIMEOUT_MINUTES = {
    1: 30,  # Level 1 (team processors): 30 minutes
    2: 20,  # Level 2 (player processors): 20 minutes
}

class DependencyGate:
    """
    Check if processor dependencies are satisfied before execution (Fix 1.2).

    Prevents wasted compute by validating dependencies BEFORE launching processors.
    Returns 500 if dependencies missing, triggering Pub/Sub retry with exponential backoff.
    """

    def __init__(self, bq_client, project_id):
        self.bq_client = bq_client
        self.project_id = project_id
        self.logger = logging.getLogger(__name__)

    def check_dependencies(self, processor_class, game_date: str) -> tuple:
        """
        Verify all dependencies are ready for processing.

        Args:
            processor_class: The processor class to check dependencies for
            game_date: The game date being processed (YYYY-MM-DD)

        Returns:
            (can_run: bool, missing_deps: list, details: dict)
        """
        # Get processor's dependency requirements
        if not hasattr(processor_class, 'get_dependencies'):
            # No dependencies declared - can run
            return True, [], {}

        # Instantiate processor to call get_dependencies()
        try:
            processor = processor_class(
                bq_client=self.bq_client,
                project_id=self.project_id,
                dataset_id='nba_analytics'
            )
            dependencies = processor.get_dependencies()
        except Exception as e:
            self.logger.warning(
                f"Could not check dependencies for {processor_class.__name__}: {e}. "
                f"Proceeding without dependency check."
            )
            return True, [], {}

        if not dependencies:
            return True, [], {}

        missing = []
        details = {}

        for dep_table, dep_config in dependencies.items():
            # Check if table has data for this game_date
            date_field = dep_config.get('date_field', 'game_date')
            expected_min = dep_config.get('expected_count_min', 1)

            query = f"""
            SELECT COUNT(*) as record_count
            FROM `{self.project_id}.{dep_table}`
            WHERE {date_field} = '{game_date}'
            """

            try:
                result = self.bq_client.query(query).result()
                count = list(result)[0].record_count

                if count < expected_min:
                    missing.append(dep_table)
                    details[dep_table] = {
                        'found': count,
                        'expected_min': expected_min,
                        'status': 'insufficient_data'
                    }
                else:
                    details[dep_table] = {
                        'found': count,
                        'expected_min': expected_min,
                        'status': 'ready'
                    }
            except Exception as e:
                self.logger.error(f"Error checking dependency {dep_table}: {e}")
                missing.append(dep_table)
                details[dep_table] = {
                    'error': str(e),
                    'status': 'check_failed'
                }

        can_run = len(missing) == 0
        return can_run, missing, details

# ============================================================================
# AUTHENTICATION (Issue #9: Add Authentication)
# ============================================================================

def require_auth(f):
    """
    Decorator to require authentication via API key OR GCP identity token.

    Validates requests against:
    1. VALID_API_KEYS environment variable (X-API-Key header)
    2. GCP identity token (Authorization: Bearer header)

    GCP identity tokens are validated by checking if request came from
    authenticated GCP service (Cloud Scheduler, Cloud Run, etc.).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check API key first
        api_key = request.headers.get('X-API-Key')
        valid_keys_str = os.getenv('VALID_API_KEYS', '')
        valid_keys = [k.strip() for k in valid_keys_str.split(',') if k.strip()]

        if api_key and api_key in valid_keys:
            return f(*args, **kwargs)

        # Check for GCP identity token (Bearer token)
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            # Token present - Cloud Run validates tokens automatically
            # If we got here, the request passed Cloud Run's IAM check
            # Just verify it's not empty
            token = auth_header[7:]
            if token and len(token) > 50:  # Valid tokens are much longer
                return f(*args, **kwargs)

        logger.warning(
            f"Unauthorized access attempt to {request.path} "
            f"(no valid API key or identity token)"
        )
        return jsonify({"error": "Unauthorized"}), 401

    return decorated_function

# Health check endpoints (Phase 1 - Task 1.1: Add Health Endpoints)
# Note: HealthChecker simplified in Week 1 to only require service_name
app.register_blueprint(create_health_blueprint('analytics-processor'))
logger.info("Health check endpoints registered: /health, /ready, /health/deep")

# ============================================================================
# BOXSCORE COMPLETENESS CHECK (Phase 1.2)
# ============================================================================

def verify_boxscore_completeness(game_date: str, project_id: str) -> dict:
    """
    Phase 1.2: Verify all scheduled games have final boxscores before triggering Phase 3.

    This prevents incomplete analytics when some games haven't been scraped yet.

    Args:
        game_date: The date to verify (YYYY-MM-DD)
        project_id: GCP project ID

    Returns:
        dict with keys:
            - complete: bool (all games have boxscores)
            - coverage_pct: float (percentage of games with boxscores)
            - expected_games: int (scheduled games)
            - actual_games: int (games with boxscores)
            - missing_games: list of dicts (games without boxscores)
    """
    # Input validation (Issue #4: Input Validation)
    try:
        game_date = validate_game_date(game_date)
        project_id = validate_project_id(project_id)
    except ValidationError as e:
        logger.error(f"Input validation failed: {e}")
        return {
            "complete": False,
            "error": f"Invalid input: {e}",
            "coverage_pct": 0.0,
            "expected_games": 0,
            "actual_games": 0,
            "missing_games": []
        }

    try:
        bq_client = get_bigquery_client(project_id)

        # Q1: How many games scheduled and completed?
        # Use parameterized query to prevent SQL injection
        scheduled_query = f"""
        SELECT
            game_id,
            home_team_tricode,
            away_team_tricode
        FROM `{project_id}.nba_raw.nbac_schedule`
        WHERE game_date = @game_date
          AND game_status_text = 'Final'
        """

        job_config_scheduled = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        scheduled_result = list(bq_client.query(scheduled_query, job_config=job_config_scheduled).result())
        scheduled_games = {row.game_id: (row.home_team_tricode, row.away_team_tricode) for row in scheduled_result}
        expected_count = len(scheduled_games)

        # Q2: How many games have boxscores? (Use BDL format: YYYYMMDD_AWAY_HOME)
        # Note: BDL uses different game ID format than NBA.com schedule
        # Use parameterized query to prevent SQL injection
        boxscore_query = f"""
        SELECT DISTINCT game_id
        FROM `{project_id}.nba_raw.bdl_player_boxscores`
        WHERE game_date = @game_date
        """

        job_config_boxscore = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        boxscore_result = list(bq_client.query(boxscore_query, job_config=job_config_boxscore).result())
        boxscore_game_ids = {row.game_id for row in boxscore_result}
        actual_count = len(boxscore_game_ids)

        # Q3: Which games are missing?
        # Convert NBA.com game IDs to expected BDL format for comparison
        # BDL format: YYYYMMDD_AWAY_HOME (e.g., 20260118_BKN_CHI)
        missing_games = []
        date_part = game_date.replace('-', '')  # 2026-01-18 -> 20260118

        for nba_game_id, (home, away) in scheduled_games.items():
            bdl_game_id = f"{date_part}_{away}_{home}"
            if bdl_game_id not in boxscore_game_ids:
                missing_games.append({
                    "game_id_nba": nba_game_id,
                    "game_id_bdl": bdl_game_id,
                    "home_team": home,
                    "away_team": away
                })

        # Calculate coverage
        coverage = (actual_count / expected_count * 100) if expected_count > 0 else 100

        is_complete = len(missing_games) == 0

        result = {
            "complete": is_complete,
            "coverage_pct": coverage,
            "expected_games": expected_count,
            "actual_games": actual_count,
            "missing_games": missing_games
        }

        if is_complete:
            logger.info(f"✅ Boxscore completeness check PASSED for {game_date}: {actual_count}/{expected_count} games")
        else:
            logger.warning(
                f"⚠️ Boxscore completeness check FAILED for {game_date}: {actual_count}/{expected_count} games "
                f"({coverage:.1f}% coverage). Missing: {len(missing_games)} games"
            )

        return result

    except Exception as e:
        logger.error(f"Boxscore completeness check failed: {e}", exc_info=True)

        # Issue #3: Fail-closed by default to prevent processing with incomplete data
        # Degraded mode escape hatch: set ALLOW_DEGRADED_MODE=true to bypass
        allow_degraded = os.getenv('ALLOW_DEGRADED_MODE', 'false').lower() == 'true'

        if allow_degraded:
            logger.warning(
                "⚠️ DEGRADED MODE: Allowing analytics to proceed despite completeness check failure"
            )
            return {
                "complete": True,
                "coverage_pct": 0,
                "expected_games": 0,
                "actual_games": 0,
                "missing_games": [],
                "error": str(e),
                "degraded_mode": True
            }
        else:
            # Fail-closed: mark as incomplete to block analytics processing
            return {
                "complete": False,
                "coverage_pct": 0,
                "expected_games": 0,
                "actual_games": 0,
                "missing_games": [],
                "error": str(e),
                "is_error_state": True
            }


def trigger_missing_boxscore_scrapes(missing_games: list, game_date: str) -> int:
    """
    Trigger BDL boxscore scraper for the entire date (will catch all missing games).

    Note: BDL box_scores scraper operates on full dates, not individual games.
    This is simpler and ensures we don't miss any games.

    Args:
        missing_games: List of missing game dictionaries
        game_date: Date to re-scrape (YYYY-MM-DD)

    Returns:
        Number of scrape requests triggered (always 1 for date-based scraping)
    """
    try:
        from shared.clients import get_pubsub_publisher
        from shared.config.gcp_config import get_project_id
        publisher = get_pubsub_publisher()
        topic_path = publisher.topic_path(get_project_id(), 'nba-scraper-trigger')

        # Trigger BDL box scores scraper for the entire date
        message_data = {
            "scraper_name": "bdl_box_scores",
            "date": game_date,
            "retry_count": 0,
            "reason": "incomplete_boxscore_coverage_detected",
            "missing_count": len(missing_games)
        }

        future = publisher.publish(
            topic_path,
            json.dumps(message_data).encode('utf-8')
        )
        message_id = future.result(timeout=10)

        logger.info(
            f"🔄 Triggered BDL box scores re-scrape for {game_date} "
            f"(missing {len(missing_games)} games, message_id={message_id})"
        )

        return 1

    except Exception as e:
        logger.error(f"Failed to trigger missing boxscore scrapes: {e}", exc_info=True)
        return 0

def run_single_analytics_processor(processor_class, opts, prefer_async=None):
    """
    Run a single analytics processor (for parallel execution).

    Supports async processors for improved concurrency when enabled.

    Args:
        processor_class: Processor class to instantiate
        opts: Options dict for processor.run()
        prefer_async: If True, use async version when available.
                      Defaults to ENABLE_ASYNC_PROCESSORS env var.

    Returns:
        Dict with processor results
    """
    # Check if async processors are enabled
    if prefer_async is None:
        prefer_async = os.environ.get('ENABLE_ASYNC_PROCESSORS', 'true').lower() == 'true'

    if prefer_async:
        # Use async orchestration which handles async/sync detection
        return run_processor_with_async_support(processor_class, opts, prefer_async=True)

    # Original sync implementation
    try:
        logger.info(f"Running {processor_class.__name__} for {opts.get('start_date')}")

        processor = processor_class()
        success = processor.run(opts)

        if success:
            stats = processor.get_analytics_stats()
            logger.info(f"Successfully ran {processor_class.__name__}: {stats}")
            return {
                "processor": processor_class.__name__,
                "status": "success",
                "stats": stats
            }
        else:
            error_msg = "Unknown error (processor.run() returned False)"
            if hasattr(processor, 'stats') and isinstance(processor.stats, dict):
                error_msg = processor.stats.get('error', error_msg)
            if hasattr(processor, 'last_error'):
                error_msg = str(processor.last_error)
            logger.error(f"Failed to run {processor_class.__name__}: {error_msg}")
            return {
                "processor": processor_class.__name__,
                "status": "error",
                "error": error_msg
            }
    except Exception as e:
        logger.error(f"Analytics processor {processor_class.__name__} failed: {e}", exc_info=True)
        return {
            "processor": processor_class.__name__,
            "status": "exception",
            "error": str(e)
        }

def run_processors_sequential(processor_groups, opts):
    """
    Execute processor groups in dependency order (Session 124 Tier 1).

    Within each group: parallel execution (performance)
    Between groups: sequential execution (correctness)

    Args:
        processor_groups: List of group dicts with keys:
            - level: int (execution order)
            - processors: list of processor classes
            - parallel: bool (run processors in parallel within group)
            - dependencies: list of processor names (specific dependencies)
            - description: str (human-readable description)
        opts: Options dict for processor.run()

    Returns:
        List of result dicts from all processors

    Raises:
        DependencyFailureError: If a critical dependency processor fails
    """
    all_results = []
    completed_processors = set()  # Track which processors completed successfully

    # Sort groups by level to ensure correct execution order
    sorted_groups = sorted(processor_groups, key=lambda g: g.get('level', 1))

    for group in sorted_groups:
        level = group.get('level', 1)
        processors = group.get('processors', [])
        parallel = group.get('parallel', True)
        dependencies = group.get('dependencies', [])
        description = group.get('description', f'Level {level} processors')

        logger.info(
            f"📋 Level {level}: Running {len(processors)} processors - {description}"
        )

        # Check if dependencies are satisfied
        missing_deps = [dep for dep in dependencies if dep not in completed_processors]
        if missing_deps:
            logger.error(
                f"❌ Cannot run Level {level}: missing dependencies {missing_deps}"
            )
            raise DependencyFailureError(
                f"Level {level} blocked by missing dependencies: {missing_deps}"
            )

        # Get timeout for this level (default to 20 minutes)
        timeout_seconds = GROUP_TIMEOUT_MINUTES.get(level, 20) * 60

        # Execute processors in this group
        if parallel and len(processors) > 1:
            # Parallel execution within group
            logger.info(f"🚀 Level {level}: Parallel execution of {len(processors)} processors")
            with ThreadPoolExecutor(max_workers=len(processors)) as executor:
                futures = {
                    executor.submit(run_single_analytics_processor, proc, opts): proc
                    for proc in processors
                }

                # Collect results with timeout
                group_results = []
                group_failures = []
                for future in as_completed(futures, timeout=timeout_seconds):
                    proc_class = futures[future]
                    try:
                        result = future.result(timeout=600)  # 10 min per processor
                        group_results.append(result)
                        if result.get('status') == 'success':
                            completed_processors.add(proc_class.__name__)
                            logger.info(f"✅ {proc_class.__name__} completed")
                        else:
                            group_failures.append(proc_class.__name__)
                            logger.error(f"❌ {proc_class.__name__} failed: {result.get('status')}")
                    except TimeoutError:
                        logger.error(f"⏱️ {proc_class.__name__} timed out after 10 minutes")
                        group_results.append({
                            "processor": proc_class.__name__,
                            "status": "timeout"
                        })
                        group_failures.append(proc_class.__name__)
                    except Exception as e:
                        logger.error(f"❌ {proc_class.__name__} exception: {e}")
                        group_results.append({
                            "processor": proc_class.__name__,
                            "status": "exception",
                            "error": str(e)
                        })
                        group_failures.append(proc_class.__name__)

                all_results.extend(group_results)

                # Check if critical dependencies failed
                # If this is Level 1 and any processor failed, block Level 2
                if level == 1 and group_failures:
                    # Check if any failed processor is a dependency for later levels
                    failed_critical = []
                    for later_group in sorted_groups:
                        if later_group.get('level', 1) > level:
                            group_deps = later_group.get('dependencies', [])
                            failed_critical.extend([f for f in group_failures if f in group_deps])

                    if failed_critical:
                        raise DependencyFailureError(
                            f"Level {level} critical processors failed: {failed_critical} - "
                            f"cannot proceed to dependent processors"
                        )
        else:
            # Sequential execution (or single processor)
            logger.info(f"🔄 Level {level}: Sequential execution of {len(processors)} processors")
            for proc in processors:
                try:
                    result = run_single_analytics_processor(proc, opts)
                    all_results.append(result)
                    if result.get('status') == 'success':
                        completed_processors.add(proc.__name__)
                        logger.info(f"✅ {proc.__name__} completed")
                    else:
                        logger.error(f"❌ {proc.__name__} failed: {result.get('status')}")
                        # Check if this processor is a critical dependency
                        if proc.__name__ in dependencies:
                            raise DependencyFailureError(
                                f"Critical dependency {proc.__name__} failed"
                            )
                except Exception as e:
                    logger.error(f"❌ {proc.__name__} exception: {e}")
                    all_results.append({
                        "processor": proc.__name__,
                        "status": "exception",
                        "error": str(e)
                    })
                    # Check if this processor is a critical dependency
                    if proc.__name__ in dependencies:
                        raise DependencyFailureError(
                            f"Critical dependency {proc.__name__} failed with exception: {e}"
                        )

        logger.info(f"✅ Level {level} complete - proceeding to next level")

    logger.info(f"✅ All {len(sorted_groups)} levels complete - {len(all_results)} processors executed")
    return all_results

def run_processors_parallel(processors, opts):
    """
    Execute processors in parallel (legacy mode for rollback).

    This is the original parallel execution logic, preserved for the
    SEQUENTIAL_EXECUTION_ENABLED=false rollback path.

    Args:
        processors: List of processor classes
        opts: Options dict for processor.run()

    Returns:
        List of result dicts from all processors
    """
    logger.info(f"🚀 Running {len(processors)} analytics processors in PARALLEL (legacy mode)")
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Submit all processors for parallel execution
        futures = {
            executor.submit(run_single_analytics_processor, processor_class, opts): processor_class
            for processor_class in processors
        }

        # Collect results as they complete
        for future in as_completed(futures):
            processor_class = futures[future]
            try:
                result = future.result(timeout=600)  # 10 min timeout per processor
                results.append(result)
            except TimeoutError:
                logger.error(f"⏱️ Processor {processor_class.__name__} timed out after 10 minutes")
                results.append({
                    "processor": processor_class.__name__,
                    "status": "timeout"
                })
            except Exception as e:
                logger.error(f"❌ Failed to get result from {processor_class.__name__}: {e}")
                results.append({
                    "processor": processor_class.__name__,
                    "status": "exception",
                    "error": str(e)
                })

    return results

# Analytics processor registry - maps source tables to dependent analytics processors
# IMPORTANT: All 5 Phase 3 processors must have at least one trigger path for
# Firestore completion tracking to work correctly. The Phase 3->4 orchestrator
# expects completion messages from all 5 processors.
#
# Session 124: Migrated to ANALYTICS_TRIGGER_GROUPS for dependency-aware execution.
# Critical triggers (nbac_gamebook_player_stats) use sequential groups to prevent
# race conditions. Other triggers maintain simple list format for backward compatibility.
ANALYTICS_TRIGGER_GROUPS = {
    # CRITICAL: Sequential execution to prevent race condition (Session 123)
    # PlayerGameSummaryProcessor depends on TeamOffenseGameSummaryProcessor
    # Feb 3 incident: Player ran 92 min BEFORE team, causing 1228% usage_rate
    'nbac_gamebook_player_stats': [
        {
            'level': 1,
            'processors': [
                TeamOffenseGameSummaryProcessor,
                TeamDefenseGameSummaryProcessor
            ],
            'parallel': True,  # Can run in parallel within group
            'dependencies': [],  # Level 1 has no dependencies
            'description': 'Team stats - foundation for player calculations'
        },
        {
            'level': 2,
            'processors': [
                PlayerGameSummaryProcessor
            ],
            'parallel': False,  # Only one processor
            'dependencies': ['TeamOffenseGameSummaryProcessor'],  # SPECIFIC dependency (not TeamDefense)
            'description': 'Player stats - requires team possessions from offense stats'
        }
    ],
    # Simple list format for triggers that don't need sequential execution
    # These will be auto-converted to single-level groups
    'nbac_scoreboard_v2': [TeamOffenseGameSummaryProcessor, TeamDefenseGameSummaryProcessor, UpcomingTeamGameContextProcessor],
    'nbac_team_boxscore': [TeamDefenseGameSummaryProcessor, TeamOffenseGameSummaryProcessor],
    'nbac_schedule': [UpcomingTeamGameContextProcessor],
    'bdl_standings': [],
    'nbac_injury_report': [PlayerGameSummaryProcessor],
    'odds_api_player_points_props': [UpcomingPlayerGameContextProcessor],
}

# Backward compatibility: Convert simple lists to single-level groups
def normalize_trigger_config(trigger_value):
    """
    Convert simple list format to group format for consistent processing.

    Examples:
        [ProcessorA, ProcessorB] -> [{'level': 1, 'processors': [ProcessorA, ProcessorB], ...}]
        [{'level': 1, ...}, {'level': 2, ...}] -> unchanged
    """
    if not trigger_value:
        return []

    # Already in group format?
    if isinstance(trigger_value, list) and len(trigger_value) > 0 and isinstance(trigger_value[0], dict):
        return trigger_value

    # Convert simple list to single-level group
    return [{
        'level': 1,
        'processors': trigger_value,
        'parallel': True,
        'dependencies': [],
        'description': 'Single-level execution (no dependencies)'
    }]

def validate_processor_groups():
    """
    Validate no processor appears in multiple groups within same trigger.
    Prevents accidental duplicate execution.
    """
    total_processors = 0

    for source_table, trigger_config in ANALYTICS_TRIGGER_GROUPS.items():
        # Skip empty configs
        if not trigger_config:
            continue

        # Normalize to group format
        groups = normalize_trigger_config(trigger_config)

        # Track processors seen in this source_table
        all_processors = []
        for group in groups:
            for proc in group.get('processors', []):
                if proc in all_processors:
                    raise ValueError(
                        f"Duplicate processor {proc.__name__} in multiple groups "
                        f"for source_table={source_table}"
                    )
                all_processors.append(proc)
                total_processors += 1

    logger.info(f"✅ Validated processor groups: no duplicates found ({total_processors} processor assignments)")

# Validate on startup
validate_processor_groups()

@app.route('/', methods=['GET'])
def index():
    """Root endpoint - service info."""
    return jsonify({
        "status": "healthy",
        "service": "analytics_processors",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200

@app.route('/process', methods=['POST'])
def process_analytics():
    """
    Handle Pub/Sub messages for analytics processing.
    Triggered when raw data processing completes.

    Expected message format (from Phase 2 UnifiedPubSubPublisher):
    {
        "processor_name": "BdlBoxscoresProcessor",
        "phase": "phase_2_raw",
        "output_table": "nba_raw.bdl_player_boxscores",
        "output_dataset": "nba_raw",
        "game_date": "2024-01-15",
        "status": "success",
        "record_count": 150
    }

    Also supports legacy format with 'source_table' for backward compatibility.
    """
    envelope = request.get_json()
    
    if not envelope:
        return jsonify({"error": "No Pub/Sub message received"}), 400
    
    # Decode Pub/Sub message
    if 'message' not in envelope:
        return jsonify({"error": "Invalid Pub/Sub message format"}), 400
    
    try:
        # Decode the message
        pubsub_message = envelope['message']
        
        if 'data' in pubsub_message:
            data = base64.b64decode(pubsub_message['data']).decode('utf-8')
            message = json.loads(data)
        else:
            return jsonify({"error": "No data in Pub/Sub message"}), 400
        
        # Extract trigger info
        # Phase 2 processors publish 'output_table' (e.g., "nba_raw.bdl_player_boxscores")
        # For backward compatibility, also check 'source_table'
        raw_table = message.get('output_table') or message.get('source_table')
        game_date = message.get('game_date')
        status = message.get('status', 'success')
        success = message.get('success', status == 'success')

        if not success or status == 'failed':
            logger.info(f"Raw processing failed for {raw_table}, skipping analytics")
            return jsonify({"status": "skipped", "reason": "Raw processing failed"}), 200

        if not raw_table:
            logger.warning(f"Missing output_table/source_table in message: {list(message.keys())}")
            return jsonify({"error": "Missing output_table in message"}), 400

        # Strip dataset prefix if present: "nba_raw.bdl_player_boxscores" -> "bdl_player_boxscores"
        source_table = raw_table.split('.')[-1] if '.' in raw_table else raw_table

        logger.info(f"Processing analytics for {source_table} (from {raw_table}), date: {game_date}")

        # Determine which analytics processors to run (Session 124: migrated to group-based execution)
        trigger_config = ANALYTICS_TRIGGER_GROUPS.get(source_table, [])

        if not trigger_config:
            logger.info(f"No analytics processors configured for {source_table}")
            return jsonify({"status": "no_processors", "source_table": source_table}), 200

        # Normalize trigger config to group format (handles both list and dict formats)
        processor_groups = normalize_trigger_config(trigger_config)
        
        # Process analytics for date range (single day or small range)
        start_date = game_date
        end_date = game_date

        # Build options dict for all processors
        opts = {
            'start_date': start_date,
            'end_date': end_date,
            'project_id': get_project_id(),
            'triggered_by': source_table,
            'backfill_mode': message.get('backfill_mode', False)  # Support backfill mode from Pub/Sub
        }

        # Log backfill mode status
        if opts.get('backfill_mode'):
            logger.info(f"🔄 BACKFILL MODE enabled for {game_date} - skipping completeness and freshness checks")

        # Phase 1.2: Boxscore completeness pre-flight check
        # Only run this check when triggered by bdl_player_boxscores completion
        # This ensures all scheduled games have boxscores before analytics run
        # Skip this check in backfill mode (data is historical, incompleteness is expected)
        if source_table == 'bdl_player_boxscores' and game_date and not opts.get('backfill_mode', False):
            logger.info(f"🔍 Running boxscore completeness check for {game_date}")
            completeness = verify_boxscore_completeness(game_date, opts['project_id'])

            if not completeness.get("complete"):
                # Issue #3: Check if this is an error state (fail-closed)
                if completeness.get("is_error_state"):
                    # Completeness check itself failed (BigQuery error, etc.)
                    logger.error(
                        f"❌ Boxscore completeness check ERROR for {game_date}: {completeness.get('error')} "
                        f"(Set ALLOW_DEGRADED_MODE=true to bypass)"
                    )
                    return jsonify({
                        "status": "error",
                        "reason": "completeness_check_failed",
                        "game_date": game_date,
                        "error": completeness.get("error"),
                        "action": "Fix underlying issue or set ALLOW_DEGRADED_MODE=true to bypass"
                    }), 500

                # Not all games have boxscores yet (normal incompleteness)
                missing_count = len(completeness.get("missing_games", []))
                coverage_pct = completeness.get("coverage_pct", 0)

                logger.warning(
                    f"⚠️ Boxscore completeness check FAILED for {game_date}: "
                    f"{completeness['actual_games']}/{completeness['expected_games']} games "
                    f"({coverage_pct:.1f}% coverage). Missing: {missing_count} games"
                )

                # Trigger missing boxscore scrapes
                trigger_missing_boxscore_scrapes(completeness["missing_games"], game_date)

                # Return 500 to trigger Pub/Sub retry
                # When missing scrapes complete, they'll republish and retry analytics
                return jsonify({
                    "status": "delayed",
                    "reason": "incomplete_boxscores",
                    "message": f"Processing delayed for {game_date} - incomplete boxscores ({completeness['actual_games']}/{completeness['expected_games']} games available)",
                    "game_date": game_date,
                    "completeness": {
                        "expected": completeness["expected_games"],
                        "actual": completeness["actual_games"],
                        "coverage_pct": coverage_pct,
                        "missing_count": missing_count
                    },
                    "action": "Triggered re-scrape and will retry analytics when complete"
                }), 500  # 500 triggers Pub/Sub retry
            else:
                logger.info(
                    f"✅ Boxscore completeness check PASSED for {game_date}: "
                    f"{completeness['actual_games']}/{completeness['expected_games']} games"
                )

        # Fix 1.2: Pre-flight dependency check (Session 125 - Tier 1 completion)
        # Check dependencies BEFORE launching processors to prevent wasted compute
        gate = DependencyGate(get_bigquery_client(), opts['project_id'])

        for group in processor_groups:
            for processor_class in group.get('processors', []):
                can_run, missing_deps, dep_details = gate.check_dependencies(
                    processor_class, game_date
                )

                if not can_run:
                    logger.warning(
                        f"❌ Cannot run {processor_class.__name__}: "
                        f"missing dependencies {missing_deps}"
                    )
                    logger.info(f"Dependency details: {dep_details}")

                    # Return 500 to trigger Pub/Sub retry
                    # Dependencies might resolve on retry (e.g., upstream processing delayed)
                    return jsonify({
                        "status": "dependency_not_ready",
                        "processor": processor_class.__name__,
                        "missing_dependencies": missing_deps,
                        "details": dep_details,
                        "retry_after": "5 minutes",
                        "source_table": source_table,
                        "game_date": game_date
                    }), 500

                logger.info(
                    f"✅ {processor_class.__name__} dependencies satisfied: "
                    f"{list(dep_details.keys()) if dep_details else 'none required'}"
                )

        # Execute processors (Session 124: Sequential execution to prevent race conditions)
        # Feature flag allows rollback to parallel execution if needed
        total_processors = sum(len(g.get('processors', [])) for g in processor_groups)

        if SEQUENTIAL_EXECUTION_ENABLED:
            # NEW: Sequential execution with dependency ordering
            logger.info(
                f"🔄 Running {total_processors} analytics processors in SEQUENTIAL GROUPS "
                f"({len(processor_groups)} levels) for {game_date}"
            )
            try:
                results = run_processors_sequential(processor_groups, opts)
            except DependencyFailureError as e:
                logger.error(f"❌ Dependency failure: {e}")
                # Return 500 to trigger Pub/Sub retry
                # Dependencies might resolve on retry (e.g., if team processors were delayed)
                return jsonify({
                    "status": "dependency_failure",
                    "message": str(e),
                    "source_table": source_table,
                    "game_date": game_date
                }), 500
        else:
            # LEGACY: Parallel execution (for rollback)
            # Extract all processors from groups into flat list
            all_processors = []
            for group in processor_groups:
                all_processors.extend(group.get('processors', []))

            logger.warning(
                f"⚠️ SEQUENTIAL_EXECUTION_ENABLED=false - using LEGACY parallel execution. "
                f"This mode is vulnerable to race conditions (Feb 3 incident)."
            )
            results = run_processors_parallel(all_processors, opts)

        # R-002 FIX: Check for failures and return appropriate status code
        # Previously always returned 200, even when processors failed
        failures = [r for r in results if r.get('status') in ('error', 'exception', 'timeout')]
        successes = [r for r in results if r.get('status') == 'success']

        total_processors = len(results)

        if not successes and failures:
            # All processors failed - return 500 to trigger Pub/Sub retry
            logger.error(
                f"❌ ALL {len(failures)} analytics processors failed for {game_date} "
                f"(source={source_table}) - returning 500 to trigger retry"
            )
            return jsonify({
                "status": "failed",
                "message": f"Failed to process analytics for {game_date} (0/{total_processors} processors completed)",
                "source_table": source_table,
                "game_date": game_date,
                "processors_run": total_processors,
                "processors_succeeded": 0,
                "failures": len(failures),
                "results": results
            }), 500

        if failures:
            # Partial failure - log warning but return 200 to ACK
            # (retrying won't help if some processors succeeded)
            logger.warning(
                f"⚠️ PARTIAL FAILURE: {len(failures)}/{total_processors} analytics processors failed "
                f"for {game_date} (source={source_table})"
            )
            return jsonify({
                "status": "partial_failure",
                "message": f"Partially processed analytics for {game_date} ({len(successes)}/{total_processors} processors completed, {len(failures)} failed)",
                "source_table": source_table,
                "game_date": game_date,
                "processors_run": total_processors,
                "processors_succeeded": len(successes),
                "successes": len(successes),
                "failures": len(failures),
                "results": results
            }), 200  # ACK to prevent infinite retries, but status indicates partial

        # All succeeded
        return jsonify({
            "status": "completed",
            "message": f"Successfully processed analytics for {game_date} ({total_processors}/{total_processors} processors completed)",
            "source_table": source_table,
            "game_date": game_date,
            "processors_run": total_processors,
            "processors_succeeded": total_processors,
            "results": results
        }), 200

    except Exception as e:
        logger.error(f"Error processing analytics message: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/process-date-range', methods=['POST'])
@require_auth
def process_date_range():
    """
    Process analytics for a date range (manual trigger).
    Requires X-API-Key header for authentication.

    POST body: {
        "start_date": "2024-01-01",
        "end_date": "2024-01-07",
        "processors": ["PlayerGameSummaryProcessor"],
        "backfill_mode": true,  // Optional: bypass dependency checks AND skip downstream triggers
        "skip_downstream_trigger": false  // Optional: override skip behavior (default: same as backfill_mode)
    }

    Note on completion tracking:
    - backfill_mode=true sets skip_downstream_trigger=true by default
    - This means Phase 4 won't auto-trigger and Firestore completion won't be updated
    - To update completion tracking during a manual retry, set skip_downstream_trigger=false explicitly
    """
    try:
        data = request.get_json()

        start_date = data.get('start_date')
        end_date = data.get('end_date')
        processor_names = data.get('processors', [])
        backfill_mode = data.get('backfill_mode', False)
        dataset_prefix = data.get('dataset_prefix', '')

        if not start_date or not end_date:
            return jsonify({"error": "start_date and end_date required"}), 400

        # Handle special date values (TODAY/TOMORROW/YESTERDAY = relative to ET timezone)
        from zoneinfo import ZoneInfo
        from datetime import timedelta
        et_now = datetime.now(ZoneInfo('America/New_York'))
        today_et = et_now.date().strftime('%Y-%m-%d')
        yesterday_et = (et_now.date() - timedelta(days=1)).strftime('%Y-%m-%d')
        tomorrow_et = (et_now.date() + timedelta(days=1)).strftime('%Y-%m-%d')

        if start_date == "TODAY":
            start_date = today_et
            logger.info(f"TODAY start_date resolved to: {start_date}")
        elif start_date == "YESTERDAY":
            start_date = yesterday_et
            logger.info(f"YESTERDAY start_date resolved to: {start_date}")
        elif start_date == "TOMORROW":
            start_date = tomorrow_et
            logger.info(f"TOMORROW start_date resolved to: {start_date}")

        if end_date == "TODAY":
            end_date = today_et
            logger.info(f"TODAY end_date resolved to: {end_date}")
        elif end_date == "YESTERDAY":
            end_date = yesterday_et
            logger.info(f"YESTERDAY end_date resolved to: {end_date}")
        elif end_date == "TOMORROW":
            end_date = tomorrow_et
            logger.info(f"TOMORROW end_date resolved to: {end_date}")

        # Map processor names to classes
        processor_map = {
            'PlayerGameSummaryProcessor': PlayerGameSummaryProcessor,
            'TeamOffenseGameSummaryProcessor': TeamOffenseGameSummaryProcessor,
            'TeamDefenseGameSummaryProcessor': TeamDefenseGameSummaryProcessor,
            'UpcomingPlayerGameContextProcessor': UpcomingPlayerGameContextProcessor,
            'UpcomingTeamGameContextProcessor': UpcomingTeamGameContextProcessor,
        }
        
        if not processor_names:
            # Default: run all processors
            processors_to_run = list(processor_map.values())
        else:
            processors_to_run = [processor_map[name] for name in processor_names if name in processor_map]

        # Build options dict for all processors
        # Note: skip_downstream_trigger=True means completion message won't be published
        # to Pub/Sub, so Phase 4 won't auto-trigger and Firestore completion won't be updated.
        # For backfill_mode, we skip downstream triggers since historical data shouldn't
        # trigger Phase 4 re-processing.
        skip_downstream = data.get('skip_downstream_trigger', backfill_mode)

        opts = {
            'start_date': start_date,
            'end_date': end_date,
            'project_id': get_project_id(),
            'triggered_by': 'manual',
            'backfill_mode': backfill_mode,
            'skip_downstream_trigger': skip_downstream,
            'dataset_prefix': dataset_prefix
        }

        if backfill_mode:
            logger.info(f"Running {len(processors_to_run)} processors in BACKFILL mode (PARALLEL)")
        if skip_downstream:
            logger.info(f"⏸️  Downstream triggers DISABLED - Phase 4 will not auto-trigger")

        # Execute processors in PARALLEL for faster manual runs
        logger.info(f"🚀 Running {len(processors_to_run)} analytics processors in PARALLEL for {start_date} to {end_date}")
        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            # Submit all processors for parallel execution
            futures = {
                executor.submit(run_single_analytics_processor, processor_class, opts): processor_class
                for processor_class in processors_to_run
            }

            # Collect results as they complete
            for future in as_completed(futures):
                processor_class = futures[future]
                try:
                    result = future.result(timeout=600)  # 10 min timeout per processor
                    results.append(result)
                except TimeoutError:
                    logger.error(f"⏱️ Processor {processor_class.__name__} timed out after 10 minutes")
                    results.append({
                        "processor": processor_class.__name__,
                        "status": "timeout"
                    })
                except Exception as e:
                    logger.error(f"❌ Failed to get result from {processor_class.__name__}: {e}")
                    results.append({
                        "processor": processor_class.__name__,
                        "status": "exception",
                        "error": str(e)
                    })
        
        return jsonify({
            "status": "completed",
            "date_range": f"{start_date} to {end_date}",
            "results": results
        }), 200
        
    except Exception as e:
        logger.error(f"Error in manual date range processing: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
