"""
orchestration.py

Flask blueprint for orchestration endpoints.
Extracted from main_scraper_service.py to modularize route handling.

Routes:
- POST /evaluate - Master controller endpoint for workflow evaluation
- POST /execute-workflows - Execute pending workflows (Phase 1)
- POST /execute-workflow - Execute a specific workflow by name
- POST /trigger-workflow - Manual workflow trigger (deprecated, use /execute-workflow)

Path: scrapers/routes/orchestration.py
"""

import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
import pytz

from orchestration.master_controller import MasterWorkflowController
from orchestration.workflow_executor import WorkflowExecutor
from orchestration.config_loader import WorkflowConfig


# Create blueprint
orchestration = Blueprint('orchestration', __name__)


# ==========================================================================
# HELPER FUNCTION
# ==========================================================================

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


# ==========================================================================
# LAZY-LOADED ORCHESTRATION COMPONENTS
# ==========================================================================

_controller = None
_executor = None
_config = None

def get_controller():
    global _controller
    if _controller is None:
        _controller = MasterWorkflowController()
    return _controller

def get_executor():
    global _executor
    if _executor is None:
        _executor = WorkflowExecutor()
    return _executor

def get_config():
    global _config
    if _config is None:
        _config = WorkflowConfig()
    return _config


# ==========================================================================
# ORCHESTRATION ROUTES
# ==========================================================================

@orchestration.route('/evaluate', methods=['POST'])
def evaluate_workflows():
    """
    Master controller endpoint - evaluates all workflows and logs decisions.
    Called hourly by Cloud Scheduler at :00 (e.g., 6:00, 7:00, 8:00).

    Returns decisions but does NOT execute workflows.
    Execution happens via /execute-workflows (called 5 min later).
    """
    try:
        current_app.logger.info("🎯 Master Controller: Evaluating all workflows")

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

        current_app.logger.info(f"✅ Evaluated {len(decisions)} workflows")
        return jsonify(response), 200

    except Exception as e:
        current_app.logger.error(f"Evaluation failed: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }), 500


@orchestration.route('/execute-workflows', methods=['POST'])
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
        current_app.logger.info("🚀 Workflow Executor: Processing pending workflows")

        executor = get_executor()
        result = executor.execute_pending_workflows()

        return jsonify({
            "status": "success",
            "execution_result": result
        }), 200

    except Exception as e:
        current_app.logger.error(f"Workflow execution failed: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }), 500


@orchestration.route('/execute-workflow', methods=['POST'])
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

        current_app.logger.info(f"🎯 Manual workflow execution: {workflow_name} with {len(scrapers)} scrapers")

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
        current_app.logger.error(f"Workflow execution failed: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }), 500


@orchestration.route('/trigger-workflow', methods=['POST'])
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

        current_app.logger.info(f"🎯 Manual trigger: {workflow_name} with {len(scrapers)} scrapers")

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
        current_app.logger.error(f"Manual trigger failed: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }), 500
