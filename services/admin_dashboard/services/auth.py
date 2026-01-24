"""
Authentication Service for Admin Dashboard

Provides API key authentication for dashboard endpoints.
"""

import os
import logging
import secrets
from functools import wraps
from flask import request, jsonify

logger = logging.getLogger(__name__)


def check_auth():
    """
    Validate API key from request headers or query params.

    Checks for API key in:
    1. X-API-Key header
    2. api_key query parameter

    Returns:
        Tuple of (is_valid, error_response_or_None)
    """
    expected_key = os.environ.get('ADMIN_DASHBOARD_API_KEY')
    if not expected_key:
        logger.error("ADMIN_DASHBOARD_API_KEY not configured")
        return False, jsonify({'error': 'Server configuration error'}), 500

    # Check header first, then query param
    provided_key = request.headers.get('X-API-Key')
    if not provided_key:
        provided_key = request.args.get('api_key')

    if not provided_key:
        return False, jsonify({'error': 'Missing API key'}), 401

    # Use constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(provided_key, expected_key):
        logger.warning(f"Invalid API key attempt from {request.remote_addr}")
        return False, jsonify({'error': 'Invalid API key'}), 403

    return True, None


def require_auth(f):
    """
    Decorator to require authentication for a route.

    Usage:
        @app.route('/api/protected')
        @require_auth
        def protected_endpoint():
            return jsonify({'message': 'authenticated'})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_valid, error_response = check_auth()
        if not is_valid:
            return error_response
        return f(*args, **kwargs)
    return decorated_function
