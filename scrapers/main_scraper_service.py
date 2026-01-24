"""
main_scraper_service.py

Single Cloud Run service that routes to all scrapers AND orchestration endpoints.
Version 2.3.0 - Added Phase 1 Workflow Executor support (HTTP-based scraper calls)

Path: scrapers/main_scraper_service.py
"""

import os
import sys
import logging
from datetime import datetime, timezone
from flask import Flask, request, jsonify
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
import pytz

# Import from centralized registry
from scrapers.registry import (
    get_scraper_instance,
    get_scraper_info,
    list_scrapers,
    scraper_exists
)

# Import orchestration components
from orchestration.master_controller import MasterWorkflowController
from orchestration.workflow_executor import WorkflowExecutor
from orchestration.cleanup_processor import CleanupProcessor
from orchestration.schedule_locker import DailyScheduleLocker
from orchestration.config_loader import WorkflowConfig


def extract_scrapers_from_execution_plan(execution_plan):
    """
    Extract all scrapers from an execution plan, handling both structures:
    1. Simple: execution_plan.scrapers = ['scraper1', 'scraper2']
    2. Multi-step: execution_plan.step_1.scrapers, execution_plan.step_2.scrapers
    
    Args:
        execution_plan: Dict containing the execution plan from workflows.yaml
        
    Returns:
        List[str]: Flat list of all scraper names
    """
    if not execution_plan:
        return []
    
    # Case 1: Simple structure with direct scrapers list
    if 'scrapers' in execution_plan:
        scrapers = execution_plan['scrapers']
        # Ensure it's a list of strings
        if isinstance(scrapers, list):
            return scrapers
        return []
    
    # Case 2: Multi-step structure (step_1, step_2, etc.)
    all_scrapers = []
    for key, value in execution_plan.items():
        if key.startswith('step_') and isinstance(value, dict):
            step_scrapers = value.get('scrapers', [])
            if isinstance(step_scrapers, list):
                all_scrapers.extend(step_scrapers)
    
    return all_scrapers


def create_app():
    """Create the main scraper routing service with orchestration."""
    app = Flask(__name__)
    if load_dotenv:
        load_dotenv()
    
    # Configure logging for Cloud Run
    if not app.debug:
        logging.basicConfig(level=logging.INFO)
    
    # Initialize orchestration components (lazy load to avoid startup overhead)
    _controller = None
    _executor = None
    _cleanup = None
    _locker = None
    _config = None
    
    def get_controller():
        nonlocal _controller
        if _controller is None:
            _controller = MasterWorkflowController()
        return _controller
    
    def get_executor():
        nonlocal _executor
        if _executor is None:
            _executor = WorkflowExecutor()
        return _executor
    
    def get_cleanup():
        nonlocal _cleanup
        if _cleanup is None:
            _cleanup = CleanupProcessor()
        return _cleanup
    
    def get_locker():
        nonlocal _locker
        if _locker is None:
            _locker = DailyScheduleLocker()
        return _locker
    
    def get_config():
        nonlocal _config
        if _config is None:
            _config = WorkflowConfig()
        return _config
    
    # ==========================================================================
    # BASIC ENDPOINTS
    # ==========================================================================
    
    @app.route('/', methods=['GET'])
    @app.route('/health', methods=['GET'])
    def health_check():
        """Enhanced health check with orchestration component status."""
        try:
            # Check orchestration components
            config = get_config()
            enabled_workflows = config.get_enabled_workflows()
            
            health_status = {
                "status": "healthy",
                "service": "nba-scrapers",
                "version": "2.3.0",
                "deployment": "orchestration-phase1-enabled",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "components": {
                    "scrapers": {
                        "available": len(list_scrapers()),
                        "status": "operational"
                    },
                    "orchestration": {
                        "master_controller": "available",
                        "workflow_executor": "available",
                        "cleanup_processor": "available",
                        "schedule_locker": "available",
                        "enabled_workflows": len(enabled_workflows),
                        "workflows": enabled_workflows
                    }
                }
            }
            
            return jsonify(health_status), 200
            
        except Exception as e:
            app.logger.error(f"Health check failed: {e}")
            return jsonify({
                "status": "degraded",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }), 503
    
    @app.route('/scrapers', methods=['GET'])
    def list_all_scrapers():
        """List all available scrapers with their module information."""
        scraper_info = get_scraper_info()
        return jsonify(scraper_info), 200
    
    # ==========================================================================
    # SCRAPER EXECUTION ENDPOINT
    # ==========================================================================
    
    @app.route('/scrape', methods=['POST'])
    def route_scraper():
        """Route to the appropriate scraper based on 'scraper' parameter."""
        try:
            # Get parameters from JSON body or query params
            params = None
            if request.is_json:
                params = request.get_json(silent=True)
            
            # Fallback to query params if JSON is None or not provided
            if params is None:
                params = request.args.to_dict()
            
            # Final safety check - ensure params is never None
            if params is None:
                params = {}
            
            # Get scraper name
            scraper_name = params.get("scraper")
            if not scraper_name:
                return jsonify({
                    "error": "Missing required parameter: scraper",
                    "available_scrapers": list_scrapers(),
                    "note": "Provide scraper name in JSON body or query parameter"
                }), 400
            
            # Verify scraper exists
            if not scraper_exists(scraper_name):
                return jsonify({
                    "error": f"Unknown scraper: {scraper_name}",
                    "available_scrapers": list_scrapers()
                }), 400
            
            # Load scraper using registry
            try:
                app.logger.info(f"Loading scraper: {scraper_name}")
                scraper = get_scraper_instance(scraper_name)
                app.logger.info(f"Successfully loaded {scraper_name}")
            except (ImportError, AttributeError) as e:
                app.logger.error(f"Failed to import scraper {scraper_name}: {e}")
                return jsonify({
                    "error": f"Failed to load scraper: {scraper_name}",
                    "details": str(e)
                }), 500
            
            # Remove 'scraper' from params before passing to scraper
            scraper_params = {k: v for k, v in params.items() if k != "scraper"}
            
            # Add default values
            scraper_params.setdefault("group", "prod")
            scraper_params.setdefault("debug", False)
            
            # Set debug logging if requested
            if scraper_params.get("debug"):
                logging.getLogger().setLevel(logging.DEBUG)
            
            # Run the scraper
            app.logger.info(f"Running scraper {scraper_name} with params: {scraper_params}")
            result = scraper.run(scraper_params)
            
            if result:
                return jsonify({
                    "status": "success",
                    "message": f"{scraper_name} completed successfully",
                    "scraper": scraper_name,
                    "run_id": scraper.run_id,
                    "data_summary": scraper.get_scraper_stats()
                }), 200
            else:
                return jsonify({
                    "status": "error",
                    "message": f"{scraper_name} failed",
                    "scraper": scraper_name,
                    "run_id": scraper.run_id
                }), 500
                
        except Exception as e:
            app.logger.error(f"Scraper routing error: {str(e)}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "scraper": params.get("scraper", "unknown") if params else "unknown",
                "error_type": type(e).__name__
            }), 500
    
    # ==========================================================================
    # ORCHESTRATION ENDPOINTS
    # ==========================================================================
    
    @app.route('/evaluate', methods=['POST'])
    def evaluate_workflows():
        """
        Master controller endpoint - evaluates all workflows and logs decisions.
        Called hourly by Cloud Scheduler at :00 (e.g., 6:00, 7:00, 8:00).
        
        Returns decisions but does NOT execute workflows.
        Execution happens via /execute-workflows (called 5 min later).
        """
        try:
            app.logger.info("🎯 Master Controller: Evaluating all workflows")
            
            controller = get_controller()
            ET = pytz.timezone('America/New_York')
            current_time = datetime.now(ET)
            
            # Evaluate all workflows
            decisions = controller.evaluate_all_workflows(current_time)
            
            # Format response
            response = {
                "status": "success",
                "evaluation_time": current_time.isoformat(),
                "workflows_evaluated": len(decisions),
                "decisions": [
                    {
                        "workflow": d.workflow_name,
                        "action": d.action.value,
                        "reason": d.reason,
                        "priority": d.priority,
                        "alert_level": d.alert_level.value,
                        "scrapers": d.scrapers if d.scrapers else [],
                        "next_check": d.next_check_time.isoformat() if d.next_check_time else None
                    }
                    for d in decisions
                ]
            }
            
            app.logger.info(f"✅ Evaluated {len(decisions)} workflows")
            return jsonify(response), 200
            
        except Exception as e:
            app.logger.error(f"Evaluation failed: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "error_type": type(e).__name__
            }), 500
    
    @app.route('/execute-workflows', methods=['POST'])
    def execute_workflows():
        """
        🆕 PHASE 1: Execute pending workflows (reads RUN decisions from BigQuery).
        
        Called by Cloud Scheduler at :05 (5 minutes after /evaluate).
        
        This is the NEW Phase 1 endpoint that:
        1. Reads RUN decisions from workflow_decisions table
        2. Resolves parameters for each scraper
        3. Calls scrapers via HTTP (POST /scrape)
        4. Tracks execution in workflow_executions table
        
        Optional JSON body:
        {
            "max_age_minutes": 60  # Only execute decisions from last N minutes
        }
        
        Returns:
            Dict with execution summary
        """
        try:
            app.logger.info("🚀 Workflow Executor: Processing pending workflows")
            
            executor = get_executor()
            result = executor.execute_pending_workflows()
            
            return jsonify({
                "status": "success",
                "execution_result": result
            }), 200
            
        except Exception as e:
            app.logger.error(f"Workflow execution failed: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "error_type": type(e).__name__
            }), 500
    
    @app.route('/execute-workflow', methods=['POST'])
    def execute_workflow():
        """
        Execute a specific workflow by name (manual trigger).
        
        ⚠️  UPDATED FOR PHASE 1: Now uses HTTP-based executor instead of direct Python calls.
        
        Expected JSON body:
        {
            "workflow_name": "morning_operations"
        }
        
        Returns:
            Dict with execution result
        """
        try:
            data = request.get_json() or {}
            workflow_name = data.get('workflow_name')
            
            if not workflow_name:
                return jsonify({
                    "error": "Missing required parameter: workflow_name",
                    "available_workflows": get_config().get_enabled_workflows()
                }), 400
            
            # Get workflow config
            config = get_config()
            workflow_config = config.get_workflow_config(workflow_name)
            
            if not workflow_config:
                return jsonify({
                    "error": f"Workflow not found: {workflow_name}",
                    "available_workflows": config.get_enabled_workflows()
                }), 404
            
            # Extract scrapers using helper function (handles both simple and multi-step)
            execution_plan = workflow_config.get('execution_plan', {})
            scrapers = extract_scrapers_from_execution_plan(execution_plan)
            
            if not scrapers:
                return jsonify({
                    "error": f"No scrapers defined for workflow: {workflow_name}",
                    "execution_plan": execution_plan
                }), 400
            
            app.logger.info(f"🎯 Manual workflow execution: {workflow_name} with {len(scrapers)} scrapers")
            
            # Use new HTTP-based executor
            executor = get_executor()
            result = executor.execute_workflow(
                workflow_name=workflow_name,
                scrapers=scrapers
            )
            
            return jsonify({
                "status": "success",
                "workflow": workflow_name,
                "execution": result.to_dict()
            }), 200
            
        except Exception as e:
            app.logger.error(f"Workflow execution failed: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "error_type": type(e).__name__
            }), 500
    
    @app.route('/cleanup', methods=['POST'])
    def run_cleanup():
        """
        Run the cleanup processor to detect and fix missing data.
        Called every 15 minutes by Cloud Scheduler.
        
        Note: CleanupProcessor.run() checks recent dates automatically.
        No parameters needed.
        """
        try:
            app.logger.info("🧹 Running cleanup processor")
            
            cleanup = get_cleanup()
            result = cleanup.run()
            
            return jsonify({
                "status": "success",
                "cleanup_result": result
            }), 200
            
        except Exception as e:
            app.logger.error(f"Cleanup failed: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "error_type": type(e).__name__
            }), 500
    
    @app.route('/generate-daily-schedule', methods=['POST'])
    def generate_schedule():
        """
        Generate expected daily schedule for monitoring.
        Called once daily at 5 AM ET by Cloud Scheduler.
        
        Optional JSON body:
        {
            "date": "2025-01-15"  # Optional - default is today
        }
        """
        try:
            data = request.get_json(silent=True, force=True) or {}
            target_date = data.get('date')
            
            app.logger.info("📅 Generating daily expected schedule")
            
            locker = get_locker()
            result = locker.generate_daily_schedule(target_date)
            
            return jsonify({
                "status": "success",
                "schedule": result
            }), 200
            
        except Exception as e:
            app.logger.error(f"Schedule generation failed: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "error_type": type(e).__name__
            }), 500
    
    # ==========================================================================
    # CATCH-UP ENDPOINT (for late/missing data retries)
    # ==========================================================================

    @app.route('/catchup', methods=['POST'])
    def catchup_scraper():
        """
        Catch-up endpoint for retrying scrapers with missing data.
        Called by Cloud Scheduler at various times throughout the day.

        Expected JSON body:
        {
            "scraper_name": "bdl_box_scores",
            "lookback_days": 3,
            "workflow": "bdl_catchup_midday"
        }

        Flow:
        1. Runs completeness check to find dates with missing data
        2. For each missing date, invokes the scraper via /scrape
        3. Returns summary of retries
        """
        try:
            data = request.get_json() or {}

            scraper_name = data.get('scraper_name')
            if not scraper_name:
                return jsonify({
                    "error": "Missing required parameter: scraper_name",
                    "available_scrapers": ["bdl_box_scores", "nbac_gamebook_pdf", "oddsa_player_props"]
                }), 400

            lookback_days = data.get('lookback_days', 3)
            workflow = data.get('workflow', 'catchup')

            app.logger.info(f"🔄 Catch-up: {scraper_name} (lookback: {lookback_days} days, workflow: {workflow})")

            # Step 1: Find missing dates using completeness query
            try:
                from google.cloud import bigquery
                import yaml
                from pathlib import Path

                bq_client = bigquery.Client()

                # Load config to get the completeness query
                config_path = Path(__file__).parent.parent / "shared" / "config" / "scraper_retry_config.yaml"

                if not config_path.exists():
                    return jsonify({
                        "status": "error",
                        "message": f"Config not found: {config_path}",
                        "scraper_name": scraper_name
                    }), 500

                with open(config_path) as f:
                    config = yaml.safe_load(f)

                # Get completeness query for this scraper
                queries = config.get("completeness_queries", {})
                query_template = queries.get(scraper_name)

                if not query_template:
                    return jsonify({
                        "status": "error",
                        "message": f"No completeness query configured for {scraper_name}",
                        "scraper_name": scraper_name
                    }), 400

                # Format query with lookback days
                query = query_template.format(lookback_days=lookback_days)
                app.logger.info(f"Running completeness check for {scraper_name}...")

                results = bq_client.query(query).result()

                missing_dates = set()
                for row in results:
                    if hasattr(row, 'game_date'):
                        missing_dates.add(str(row.game_date))

                missing_dates = sorted(missing_dates)
                app.logger.info(f"Found {len(missing_dates)} dates with missing {scraper_name} data")

            except FileNotFoundError as e:
                app.logger.error(f"Completeness config not found: {e}")
                return jsonify({
                    "status": "error",
                    "message": f"Config file not found: {e}",
                    "scraper_name": scraper_name
                }), 500
            except (KeyError, TypeError) as e:
                app.logger.error(f"Completeness config parse error: {e}")
                return jsonify({
                    "status": "error",
                    "message": f"Config parse error: {e}",
                    "scraper_name": scraper_name
                }), 500
            except Exception as e:
                app.logger.error(f"Completeness check failed ({type(e).__name__}): {e}", exc_info=True)
                return jsonify({
                    "status": "error",
                    "message": f"Completeness check failed: {e}",
                    "scraper_name": scraper_name
                }), 500

            if not missing_dates:
                app.logger.info(f"✅ No missing data found for {scraper_name}")
                return jsonify({
                    "status": "complete",
                    "message": "No missing data to retry",
                    "scraper_name": scraper_name,
                    "lookback_days": lookback_days,
                    "dates_checked": 0
                }), 200

            app.logger.info(f"Found {len(missing_dates)} dates with missing data: {missing_dates}")

            # Step 2: Invoke scraper for each missing date
            results = []
            successes = 0
            failures = 0

            for date in missing_dates:
                try:
                    # Get scraper instance and run it
                    if not scraper_exists(scraper_name):
                        results.append({"date": date, "status": "error", "message": f"Unknown scraper: {scraper_name}"})
                        failures += 1
                        continue

                    app.logger.info(f"  Retrying {scraper_name} for {date}...")
                    scraper = get_scraper_instance(scraper_name)

                    # Run scraper with date and workflow
                    scraper_params = {
                        "date": date,
                        "workflow": workflow,
                        "group": "prod"
                    }

                    result = scraper.run(scraper_params)

                    if result:
                        results.append({
                            "date": date,
                            "status": "success",
                            "run_id": scraper.run_id,
                            "stats": scraper.get_scraper_stats()
                        })
                        successes += 1
                    else:
                        results.append({
                            "date": date,
                            "status": "failed",
                            "run_id": scraper.run_id
                        })
                        failures += 1

                except (ImportError, AttributeError) as e:
                    app.logger.error(f"  Failed to load scraper for {date}: {e}")
                    results.append({
                        "date": date,
                        "status": "error",
                        "message": f"Scraper load error: {e}"
                    })
                    failures += 1
                except (ValueError, KeyError, TypeError) as e:
                    app.logger.error(f"  Data error retrying {date}: {e}")
                    results.append({
                        "date": date,
                        "status": "error",
                        "message": f"Data error: {e}"
                    })
                    failures += 1
                except Exception as e:
                    app.logger.error(f"  Failed to retry {date} ({type(e).__name__}): {e}", exc_info=True)
                    results.append({
                        "date": date,
                        "status": "error",
                        "message": str(e)
                    })
                    failures += 1

            status = "complete" if failures == 0 else "partial"
            app.logger.info(f"🔄 Catch-up complete: {successes} succeeded, {failures} failed")

            return jsonify({
                "status": status,
                "scraper_name": scraper_name,
                "lookback_days": lookback_days,
                "workflow": workflow,
                "dates_retried": len(missing_dates),
                "successes": successes,
                "failures": failures,
                "results": results
            }), 200

        except Exception as e:
            app.logger.error(f"Catch-up failed: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "error_type": type(e).__name__
            }), 500

    @app.route('/trigger-workflow', methods=['POST'])
    def trigger_workflow():
        """
        Manual workflow trigger for testing (bypasses all conditions).
        
        ⚠️  DEPRECATED: Use /execute-workflow instead (same functionality).
        
        Expected JSON body:
        {
            "workflow_name": "morning_operations"
        }
        """
        try:
            data = request.get_json() or {}
            workflow_name = data.get('workflow_name')
            
            if not workflow_name:
                return jsonify({
                    "error": "Missing required parameter: workflow_name",
                    "available_workflows": get_config().get_enabled_workflows()
                }), 400
            
            # Get workflow config
            config = get_config()
            workflow_config = config.get_workflow_config(workflow_name)
            
            if not workflow_config:
                return jsonify({
                    "error": f"Workflow not found: {workflow_name}",
                    "available_workflows": config.get_enabled_workflows()
                }), 404
            
            # Extract scrapers using helper function (handles both simple and multi-step)
            execution_plan = workflow_config.get('execution_plan', {})
            scrapers = extract_scrapers_from_execution_plan(execution_plan)
            
            if not scrapers:
                return jsonify({
                    "error": f"No scrapers defined for workflow: {workflow_name}",
                    "execution_plan": execution_plan
                }), 400
            
            app.logger.info(f"🎯 Manual trigger: {workflow_name} with {len(scrapers)} scrapers")
            
            executor = get_executor()
            result = executor.execute_workflow(
                workflow_name=workflow_name,
                scrapers=scrapers
            )
            
            return jsonify({
                "status": "success",
                "message": f"Manually triggered {workflow_name}",
                "workflow": workflow_name,
                "execution": result.to_dict()
            }), 200
            
        except Exception as e:
            app.logger.error(f"Manual trigger failed: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "error_type": type(e).__name__
            }), 500

    @app.route('/fix-stale-schedule', methods=['POST'])
    def fix_stale_schedule():
        """
        Fix stale schedule data - marks old in-progress games as Final.

        This prevents analytics processors from skipping due to ENABLE_GAMES_FINISHED_CHECK
        when schedule data hasn't been refreshed.

        Games are considered stale if:
        - game_status is 1 (Scheduled) or 2 (In Progress)
        - game_date is in the past
        - More than 4 hours have passed since the assumed game time

        Added: Jan 23, 2026 - Automated via Cloud Scheduler (every 4 hours)
        """
        try:
            from google.cloud import bigquery

            app.logger.info("🔧 Running stale schedule fix...")

            from shared.config.gcp_config import get_project_id
            client = bigquery.Client(project=get_project_id())

            # Find stale games
            query = """
            SELECT
                game_id,
                game_date,
                game_status,
                time_slot,
                home_team_tricode as home_team_abbr,
                away_team_tricode as away_team_abbr,
                TIMESTAMP_DIFF(CURRENT_TIMESTAMP(),
                    TIMESTAMP(CONCAT(CAST(game_date AS STRING), ' 19:00:00'), 'America/New_York'),
                    HOUR) as hours_since_start
            FROM `nba_raw.nbac_schedule`
            WHERE game_status IN (1, 2)
              AND game_date < CURRENT_DATE('America/New_York')
            ORDER BY game_date DESC, time_slot
            """

            results = list(client.query(query).result())
            stale_games = []

            for row in results:
                if row.hours_since_start and row.hours_since_start > 4:
                    stale_games.append({
                        'game_id': row.game_id,
                        'game_date': str(row.game_date),
                        'current_status': row.game_status,
                        'matchup': f"{row.away_team_abbr}@{row.home_team_abbr}",
                        'hours_since_start': row.hours_since_start
                    })

            if not stale_games:
                app.logger.info("✅ No stale games found")
                return jsonify({
                    "status": "success",
                    "message": "No stale games found",
                    "games_fixed": 0
                }), 200

            # Group by date for partition-safe updates
            games_by_date = {}
            for game in stale_games:
                gdate = game['game_date']
                if gdate not in games_by_date:
                    games_by_date[gdate] = []
                games_by_date[gdate].append(game['game_id'])

            # Update games
            total_updated = 0
            for gdate, gids in games_by_date.items():
                game_ids_str = "', '".join(gids)
                update_query = f"""
                UPDATE `nba_raw.nbac_schedule`
                SET game_status = 3, game_status_text = 'Final'
                WHERE game_date = '{gdate}'
                  AND game_id IN ('{game_ids_str}')
                """
                client.query(update_query).result()
                total_updated += len(gids)
                app.logger.info(f"  Updated {len(gids)} games for {gdate}")

            app.logger.info(f"✅ Fixed {total_updated} stale games")

            return jsonify({
                "status": "success",
                "message": f"Fixed {total_updated} stale games",
                "games_fixed": total_updated,
                "games": [g['matchup'] for g in stale_games]
            }), 200

        except Exception as e:
            app.logger.error(f"Stale schedule fix failed: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "error_type": type(e).__name__
            }), 500

    return app


# Create app instance for gunicorn
app = create_app()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="NBA Scrapers Service with Phase 1 Orchestration")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8080)))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--host", default="0.0.0.0")
    
    args = parser.parse_args()
    
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)