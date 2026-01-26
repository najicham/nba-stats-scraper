"""
Audit Blueprint - Audit logs and summary

Routes:
- GET /: Get audit logs
- GET /summary: Get audit summary
"""

import logging
from flask import Blueprint, jsonify, request

from services.admin_dashboard.services.rate_limiter import rate_limit
from services.admin_dashboard.services.auth import check_auth
from services.admin_dashboard.services.audit_logger import get_audit_logger

logger = logging.getLogger(__name__)

audit_bp = Blueprint('audit', __name__)


def clamp_param(value: int, min_val: int, max_val: int, default: int) -> int:
    """Clamp a parameter value to a valid range."""
    try:
        val = int(value)
        return max(min_val, min(max_val, val))
    except (TypeError, ValueError):
        return default


@audit_bp.route('/')
@rate_limit
def api_audit_logs():
    """Get audit logs."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    limit = clamp_param(request.args.get('limit', 50), 1, 500, 50)
    hours = clamp_param(request.args.get('hours', 24), 1, 168, 24)
    action_type = request.args.get('action_type')

    try:
        audit_logger = get_audit_logger()

        if action_type:
            logs = audit_logger.get_logs_by_action_type(action_type, limit=limit)
        else:
            logs = audit_logger.get_recent_logs(limit=limit, hours=hours)

        return jsonify({
            'logs': logs,
            'count': len(logs),
            'limit': limit,
            'hours': hours
        })

    except Exception as e:
        logger.error(f"Error fetching audit logs: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@audit_bp.route('/summary')
@rate_limit
def api_audit_logs_summary():
    """Get audit summary."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    hours = clamp_param(request.args.get('hours', 24), 1, 168, 24)

    try:
        audit_logger = get_audit_logger()
        summary = audit_logger.get_audit_summary(hours=hours)

        return jsonify(summary)

    except Exception as e:
        logger.error(f"Error fetching audit summary: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
