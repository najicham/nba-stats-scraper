"""
Actions Blueprint - Admin actions (POST endpoints)

Routes:
- POST /force-predictions: Force prediction generation
- POST /retry-phase: Retry a failed phase
- POST /trigger-self-heal: Trigger self-heal process
"""

import os
import logging
from flask import Blueprint, jsonify, request

from ..services.rate_limiter import rate_limit
from ..services.auth import check_auth
from ..services.audit_logger import get_audit_logger

logger = logging.getLogger(__name__)

actions_bp = Blueprint('actions', __name__)


@actions_bp.route('/force-predictions', methods=['POST'])
@rate_limit
def action_force_predictions():
    """Force prediction generation."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    audit_logger = get_audit_logger()

    try:
        data = request.get_json() or {}
        target_date = data.get('date')

        if not target_date:
            return jsonify({'error': 'Missing required parameter: date'}), 400

        # Log the action
        audit_logger.log_action(
            action_type='force_predictions',
            action_details={'date': target_date},
            success=True,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # TODO: Implement actual prediction triggering logic
        # This would typically call a Cloud Run service or publish to Pub/Sub

        return jsonify({
            'status': 'triggered',
            'date': target_date,
            'message': f'Prediction generation triggered for {target_date}'
        })

    except Exception as e:
        logger.error(f"Error forcing predictions: {e}", exc_info=True)

        audit_logger.log_action(
            action_type='force_predictions',
            action_details={'date': request.get_json().get('date') if request.get_json() else None},
            success=False,
            error_message=str(e),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'error': str(e)}), 500


@actions_bp.route('/retry-phase', methods=['POST'])
@rate_limit
def action_retry_phase():
    """Retry a failed phase."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    audit_logger = get_audit_logger()

    try:
        data = request.get_json() or {}
        phase = data.get('phase')
        target_date = data.get('date')

        if not phase or not target_date:
            return jsonify({'error': 'Missing required parameters: phase and date'}), 400

        # Validate phase
        valid_phases = ['phase_1', 'phase_2', 'phase_3', 'phase_4', 'phase_5', 'phase_6']
        if phase not in valid_phases:
            return jsonify({'error': f'Invalid phase. Must be one of: {valid_phases}'}), 400

        # Log the action
        audit_logger.log_action(
            action_type='retry_phase',
            action_details={'phase': phase, 'date': target_date},
            success=True,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # TODO: Implement actual phase retry logic
        # This would typically call a Cloud Run service or publish to Pub/Sub

        return jsonify({
            'status': 'triggered',
            'phase': phase,
            'date': target_date,
            'message': f'Retry triggered for {phase} on {target_date}'
        })

    except Exception as e:
        logger.error(f"Error retrying phase: {e}", exc_info=True)

        data = request.get_json() or {}
        audit_logger.log_action(
            action_type='retry_phase',
            action_details={'phase': data.get('phase'), 'date': data.get('date')},
            success=False,
            error_message=str(e),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'error': str(e)}), 500


@actions_bp.route('/trigger-self-heal', methods=['POST'])
@rate_limit
def action_trigger_self_heal():
    """Trigger self-heal process."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    audit_logger = get_audit_logger()

    try:
        data = request.get_json() or {}
        target_date = data.get('date')
        mode = data.get('mode', 'auto')  # auto, force, dry_run

        # Log the action
        audit_logger.log_action(
            action_type='trigger_self_heal',
            action_details={'date': target_date, 'mode': mode},
            success=True,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # TODO: Implement actual self-heal triggering logic
        # This would typically call the self_heal Cloud Function

        return jsonify({
            'status': 'triggered',
            'date': target_date,
            'mode': mode,
            'message': f'Self-heal triggered in {mode} mode'
        })

    except Exception as e:
        logger.error(f"Error triggering self-heal: {e}", exc_info=True)

        data = request.get_json() or {}
        audit_logger.log_action(
            action_type='trigger_self_heal',
            action_details={'date': data.get('date'), 'mode': data.get('mode')},
            success=False,
            error_message=str(e),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'error': str(e)}), 500
