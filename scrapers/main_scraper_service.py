"""
main_scraper_service.py

Single Cloud Run service that routes to all scrapers AND orchestration endpoints.
Version 2.2.3 - Added support for multi-step execution plans (step_1, step_2, etc.)

Path: scrapers/main_scraper_service.py
"""

import os
import sys
import logging
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from dotenv import load_dotenv
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
                "version": "2.2.3",
                "deployment": "orchestration-enabled",
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
        Called hourly by Cloud Scheduler.
        
        Returns decisions but does NOT execute workflows.
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
    
    @app.route('/execute-workflow', methods=['POST'])
    def execute_workflow():
        """
        Execute a specific workflow by name.
        
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
            
            app.logger.info(f"🚀 Executing workflow: {workflow_name} with {len(scrapers)} scrapers")
            
            executor = get_executor()
            result = executor.execute(workflow_name, scrapers)
            
            return jsonify({
                "status": "success",
                "workflow": workflow_name,
                "execution": result
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
    
    @app.route('/trigger-workflow', methods=['POST'])
    def trigger_workflow():
        """
        Manual workflow trigger for testing.
        Bypasses all conditions and executes immediately.
        
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
            result = executor.execute(workflow_name, scrapers)
            
            return jsonify({
                "status": "success",
                "message": f"Manually triggered {workflow_name}",
                "workflow": workflow_name,
                "execution": result
            }), 200
            
        except Exception as e:
            app.logger.error(f"Manual trigger failed: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "error_type": type(e).__name__
            }), 500
    
    return app


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="NBA Scrapers Service with Orchestration")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8080)))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--host", default="0.0.0.0")
    
    args = parser.parse_args()
    
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)