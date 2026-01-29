# Admin Dashboard Blueprints
#
# Blueprint Structure:
# - status: Main dashboard, status API, games
# - grading: Grading metrics and history
# - analytics: Coverage metrics, calibration
# - trends: Trend charts and analysis
# - latency: Latency metrics and bottlenecks
# - costs: Scraper costs and leaderboard
# - reliability: Reconciliation and reliability summary
# - actions: Admin actions (POST endpoints)
# - audit: Audit logs and summary
# - partials: HTMX partial views
# - source_blocks: Source-blocked resources monitoring
# - data_quality: Data quality monitoring and prevention system effectiveness

from .status import status_bp
from .grading import grading_bp
from .analytics import analytics_bp
from .trends import trends_bp
from .latency import latency_bp
from .costs import costs_bp
from .reliability import reliability_bp
from .actions import actions_bp
from .audit import audit_bp
from .partials import partials_bp
from .source_blocks import source_blocks_bp
from .data_quality import data_quality_bp


def register_blueprints(app):
    """Register all blueprints with the Flask app."""
    app.register_blueprint(status_bp)
    app.register_blueprint(grading_bp, url_prefix='/api/grading')
    app.register_blueprint(analytics_bp, url_prefix='/api')
    app.register_blueprint(trends_bp, url_prefix='/api/trends')
    app.register_blueprint(latency_bp, url_prefix='/api/latency')
    app.register_blueprint(costs_bp, url_prefix='/api/scraper-costs')
    app.register_blueprint(reliability_bp, url_prefix='/api/reliability')
    app.register_blueprint(actions_bp, url_prefix='/api/actions')
    app.register_blueprint(audit_bp, url_prefix='/api/audit-logs')
    app.register_blueprint(partials_bp, url_prefix='/partials')
    app.register_blueprint(source_blocks_bp)  # Source blocks (includes /api/source-blocks and /source-blocks)
    app.register_blueprint(data_quality_bp)  # Data quality (includes /api/data-quality/*)


__all__ = [
    'status_bp',
    'grading_bp',
    'analytics_bp',
    'trends_bp',
    'latency_bp',
    'costs_bp',
    'reliability_bp',
    'actions_bp',
    'audit_bp',
    'partials_bp',
    'source_blocks_bp',
    'data_quality_bp',
    'register_blueprints',
]
