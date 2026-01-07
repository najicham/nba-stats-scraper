"""
Cloud Function to execute BigQuery table backups.
Triggered daily by Cloud Scheduler.
"""
import subprocess
import logging
from flask import jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def backup_bigquery_tables(request):
    """
    HTTP Cloud Function to execute BigQuery backup script.

    Args:
        request (flask.Request): HTTP request object

    Returns:
        tuple: (response_body, status_code, headers)
    """
    try:
        # Validate request (optional: check for secret token)
        backup_type = request.args.get('type', 'daily')

        logger.info(f"Starting BigQuery backup (type: {backup_type})")

        # Execute backup script
        script_path = '/workspace/bin/operations/export_bigquery_tables.sh'
        result = subprocess.run(
            ['/bin/bash', script_path, backup_type],
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )

        if result.returncode == 0:
            logger.info("Backup completed successfully")
            return jsonify({
                'status': 'success',
                'message': 'BigQuery backup completed',
                'backup_type': backup_type,
                'output': result.stdout[-500:]  # Last 500 chars
            }), 200
        else:
            logger.error(f"Backup failed: {result.stderr}")
            return jsonify({
                'status': 'error',
                'message': 'BigQuery backup failed',
                'error': result.stderr[-500:]
            }), 500

    except subprocess.TimeoutExpired:
        logger.error("Backup timed out after 1 hour")
        return jsonify({
            'status': 'error',
            'message': 'Backup timed out'
        }), 500

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
