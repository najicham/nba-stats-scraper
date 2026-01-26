"""
cleanup.py

Flask blueprint for cleanup processor endpoint.
Extracted from main_scraper_service.py

Path: scrapers/routes/cleanup.py
"""

from flask import Blueprint, jsonify, current_app

# Create blueprint
cleanup_bp = Blueprint('cleanup', __name__)


# Lazy-load orchestration component
_cleanup = None


def get_cleanup():
    """Lazy loader for CleanupProcessor instance."""
    global _cleanup
    if _cleanup is None:
        from orchestration.cleanup_processor import CleanupProcessor
        _cleanup = CleanupProcessor()
    return _cleanup


@cleanup_bp.route('/cleanup', methods=['POST'])
def run_cleanup():
    """
    Run the cleanup processor to detect and fix missing data.
    Called every 15 minutes by Cloud Scheduler.

    Note: CleanupProcessor.run() checks recent dates automatically.
    No parameters needed.
    """
    try:
        current_app.logger.info("🧹 Running cleanup processor")

        cleanup = get_cleanup()
        result = cleanup.run()

        return jsonify({
            "status": "success",
            "cleanup_result": result
        }), 200

    except Exception as e:
        current_app.logger.error(f"Cleanup failed: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }), 500
