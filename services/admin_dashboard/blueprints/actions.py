"""
Actions Blueprint - Admin actions (POST endpoints)

Routes:
- POST /force-predictions: Force prediction generation
- POST /retry-phase: Retry a failed phase
- POST /trigger-self-heal: Trigger self-heal process
"""

import os
import json
import logging
import requests
from flask import Blueprint, jsonify, request
from google.cloud import pubsub_v1
import google.auth.transport.requests
import google.oauth2.id_token

from services.admin_dashboard.services.rate_limiter import rate_limit
from services.admin_dashboard.services.auth import check_auth
from services.admin_dashboard.services.audit_logger import get_audit_logger
from shared.config.service_urls import get_service_url, Services

logger = logging.getLogger(__name__)

# GCP Configuration
GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

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

        # Publish to prediction-coordinator Pub/Sub topic
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(GCP_PROJECT_ID, 'nba-predictions-trigger')

        message_data = {
            'game_date': target_date,
            'action': 'predict',
            'force': True,
            'triggered_by': 'admin_dashboard'
        }

        message_bytes = json.dumps(message_data).encode('utf-8')
        future = publisher.publish(topic_path, message_bytes)
        message_id = future.result()

        logger.info(f"Force predictions published to Pub/Sub: message_id={message_id}, date={target_date}")

        # Log the action
        audit_logger.log_action(
            action_type='force_predictions',
            action_details={'date': target_date, 'message_id': message_id},
            success=True,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'status': 'triggered',
            'date': target_date,
            'message_id': message_id,
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

        # Map phase to Cloud Run endpoint - using centralized service_urls
        phase_urls = {
            'phase_2': f'{get_service_url(Services.PHASE2_PROCESSORS)}/process',
            'phase_3': f'{get_service_url(Services.PHASE3_ANALYTICS)}/process',
            'phase_4': f'{get_service_url(Services.PHASE4_PRECOMPUTE)}/process',
            'phase_5': f'{get_service_url(Services.PREDICTION_COORDINATOR)}/predict',
        }

        url = phase_urls.get(phase)
        if not url:
            valid_phases = list(phase_urls.keys())
            return jsonify({'error': f'Invalid phase. Must be one of: {valid_phases}'}), 400

        # Get authentication token for Cloud Run
        auth_req = google.auth.transport.requests.Request()
        id_token = google.oauth2.id_token.fetch_id_token(auth_req, url)

        # Call Cloud Run endpoint
        headers = {
            'Authorization': f'Bearer {id_token}',
            'Content-Type': 'application/json'
        }
        payload = {
            'game_date': target_date,
            'force': True
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        success = response.status_code == 200

        logger.info(f"Phase retry request sent: phase={phase}, date={target_date}, "
                   f"status_code={response.status_code}")

        # Log the action
        audit_logger.log_action(
            action_type='retry_phase',
            action_details={
                'phase': phase,
                'date': target_date,
                'status_code': response.status_code
            },
            success=success,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'status': 'triggered' if success else 'failed',
            'phase': phase,
            'date': target_date,
            'status_code': response.status_code,
            'message': f'Retry triggered for {phase} on {target_date}'
        }), (200 if success else 500)

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

        # Publish to self-heal Pub/Sub topic
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(GCP_PROJECT_ID, 'self-heal-trigger')

        message_data = {
            'game_date': target_date,
            'action': 'heal',
            'mode': mode,
            'triggered_by': 'admin_dashboard'
        }

        message_bytes = json.dumps(message_data).encode('utf-8')
        future = publisher.publish(topic_path, message_bytes)
        message_id = future.result()

        logger.info(f"Self-heal published to Pub/Sub: message_id={message_id}, date={target_date}, mode={mode}")

        # Log the action
        audit_logger.log_action(
            action_type='trigger_self_heal',
            action_details={
                'date': target_date,
                'mode': mode,
                'message_id': message_id
            },
            success=True,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'status': 'triggered',
            'date': target_date,
            'mode': mode,
            'message_id': message_id,
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
