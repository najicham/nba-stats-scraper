#!/usr/bin/env python3
"""
Prediction Monitoring Cloud Function

Endpoints:
- /validate-freshness: Check data freshness before Phase 5
- /check-missing: Detect missing predictions after Phase 5
- /reconcile: End-to-end daily reconciliation

Author: Claude Code
Created: 2026-01-18
Session: 106
"""

import functions_framework
import logging
import os
from datetime import datetime, date, timedelta
from flask import jsonify, Request

# Import local modules (copied to same directory during deployment)
from data_freshness_validator import get_freshness_validator
from missing_prediction_detector import get_missing_prediction_detector

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@functions_framework.http
def validate_freshness(request: Request):
    """
    Validate data freshness before predictions run.

    Query params:
        game_date: Date to validate (default: today)
        max_age_hours: Max acceptable data age (default: 24)

    Returns:
        JSON with validation results
    """
    try:
        # Parse request
        request_json = request.get_json(silent=True) or {}
        game_date_str = request_json.get('game_date') or request.args.get('game_date')
        max_age_hours = int(request_json.get('max_age_hours') or request.args.get('max_age_hours', 24))

        # Parse game_date
        if game_date_str:
            # Handle special date keywords
            if game_date_str.upper() == "TOMORROW":
                game_date = date.today() + timedelta(days=1)
            elif game_date_str.upper() == "TODAY":
                game_date = date.today()
            elif game_date_str.upper() == "YESTERDAY":
                game_date = date.today() - timedelta(days=1)
            else:
                game_date = date.fromisoformat(game_date_str)
        else:
            game_date = date.today()

        logger.info(f"Validating data freshness for {game_date}, max_age={max_age_hours}h")

        # Validate
        validator = get_freshness_validator()
        all_fresh, errors, details = validator.validate_all(game_date, max_age_hours)

        # Build response
        response = {
            'fresh': all_fresh,
            'game_date': game_date.isoformat(),
            'max_age_hours': max_age_hours,
            'errors': errors,
            'details': details,
            'timestamp': datetime.utcnow().isoformat()
        }

        if all_fresh:
            logger.info(f"✅ Data is fresh for {game_date}")
            return jsonify(response), 200
        else:
            logger.warning(f"⚠️ Stale data detected for {game_date}: {errors}")
            return jsonify(response), 400  # Bad request - data not fresh

    except Exception as e:
        logger.error(f"Error validating freshness: {e}", exc_info=True)
        return jsonify({
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@functions_framework.http
def check_missing(request: Request):
    """
    Check for missing predictions and send alerts.

    Query params:
        game_date: Date to check (default: today)

    Returns:
        JSON with missing prediction details
    """
    try:
        # Parse request
        request_json = request.get_json(silent=True) or {}
        game_date_str = request_json.get('game_date') or request.args.get('game_date')

        # Parse game_date
        if game_date_str:
            # Handle special date keywords
            if game_date_str.upper() == "TOMORROW":
                game_date = date.today() + timedelta(days=1)
            elif game_date_str.upper() == "TODAY":
                game_date = date.today()
            elif game_date_str.upper() == "YESTERDAY":
                game_date = date.today() - timedelta(days=1)
            else:
                game_date = date.fromisoformat(game_date_str)
        else:
            game_date = date.today()

        logger.info(f"Checking for missing predictions on {game_date}")

        # Detect missing predictions and send alert
        detector = get_missing_prediction_detector()
        result = detector.check_and_alert(game_date)

        # Build response
        missing_count = result.get('missing_count', 0)
        status_code = 200 if missing_count == 0 else 400

        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"Error checking missing predictions: {e}", exc_info=True)
        return jsonify({
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@functions_framework.http
def reconcile(request: Request):
    """
    End-to-end daily reconciliation.

    Validates entire pipeline from Phase 3 → Phase 4 → Phase 5.

    Query params:
        game_date: Date to reconcile (default: today)

    Returns:
        JSON with full reconciliation report
    """
    try:
        # Parse request
        request_json = request.get_json(silent=True) or {}
        game_date_str = request_json.get('game_date') or request.args.get('game_date')

        # Parse game_date
        if game_date_str:
            # Handle special date keywords
            if game_date_str.upper() == "TOMORROW":
                game_date = date.today() + timedelta(days=1)
            elif game_date_str.upper() == "TODAY":
                game_date = date.today()
            elif game_date_str.upper() == "YESTERDAY":
                game_date = date.today() - timedelta(days=1)
            else:
                game_date = date.fromisoformat(game_date_str)
        else:
            game_date = date.today()

        logger.info(f"Running end-to-end reconciliation for {game_date}")

        # Step 1: Validate data freshness
        validator = get_freshness_validator()
        all_fresh, freshness_errors, freshness_details = validator.validate_all(game_date, max_age_hours=48)

        # Step 2: Check for missing predictions
        detector = get_missing_prediction_detector()
        missing_result = detector.check_and_alert(game_date)

        # Build reconciliation report
        report = {
            'game_date': game_date.isoformat(),
            'timestamp': datetime.utcnow().isoformat(),
            'freshness': {
                'passed': all_fresh,
                'errors': freshness_errors,
                'details': freshness_details
            },
            'coverage': {
                'missing_count': missing_result.get('missing_count', 0),
                'missing_players': missing_result.get('missing_players', []),
                'summary': missing_result.get('summary', {}),
                'alert_sent': missing_result.get('alert_sent', False)
            },
            'overall_status': 'PASS' if all_fresh and missing_result.get('missing_count', 0) == 0 else 'FAIL'
        }

        # Log summary
        if report['overall_status'] == 'PASS':
            logger.info(f"✅ Reconciliation PASSED for {game_date}")
        else:
            logger.warning(f"⚠️ Reconciliation FAILED for {game_date}")
            logger.warning(f"Freshness errors: {freshness_errors}")
            logger.warning(f"Missing predictions: {missing_result.get('missing_count', 0)}")

        status_code = 200 if report['overall_status'] == 'PASS' else 400

        return jsonify(report), status_code

    except Exception as e:
        logger.error(f"Error during reconciliation: {e}", exc_info=True)
        return jsonify({
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@functions_framework.http
def health(request):
    """Health check endpoint for prediction_monitoring."""
    return json.dumps({
        'status': 'healthy',
        'function': 'prediction_monitoring',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}
