# Admin Dashboard Blueprints
#
# Each blueprint is imported lazily inside `register_blueprints()` so that a
# broken import for one blueprint does not prevent the rest from loading. This
# is a defensive pattern — at one point `source_blocks` had a stale
# `log_action` import that crashed app startup entirely.

import logging

logger = logging.getLogger(__name__)


# Order matters only for the dashboard nav; functionally each is independent.
# Tuple format: (import_path, attribute_name, register_kwargs)
_BLUEPRINT_SPECS = [
    ('.status',         'status_bp',         {}),
    ('.grading',        'grading_bp',        {'url_prefix': '/api/grading'}),
    ('.analytics',      'analytics_bp',      {'url_prefix': '/api'}),
    ('.trends',         'trends_bp',         {'url_prefix': '/api/trends'}),
    ('.latency',        'latency_bp',        {'url_prefix': '/api/latency'}),
    ('.costs',          'costs_bp',          {'url_prefix': '/api/scraper-costs'}),
    ('.reliability',    'reliability_bp',    {'url_prefix': '/api/reliability'}),
    ('.actions',        'actions_bp',        {'url_prefix': '/api/actions'}),
    ('.audit',          'audit_bp',          {'url_prefix': '/api/audit-logs'}),
    ('.partials',       'partials_bp',       {'url_prefix': '/partials'}),
    ('.source_blocks',  'source_blocks_bp',  {}),
    ('.data_quality',   'data_quality_bp',   {}),
    ('.league_trends',  'league_trends_bp',  {}),
    ('.model_health',   'model_health_bp',   {}),
]


def register_blueprints(app):
    """Register every blueprint, isolating failures per blueprint."""
    import importlib
    registered = []
    failed = []
    for module_path, attr, kwargs in _BLUEPRINT_SPECS:
        try:
            module = importlib.import_module(module_path, package=__name__)
            bp = getattr(module, attr)
            app.register_blueprint(bp, **kwargs)
            registered.append(attr)
        except Exception as e:
            logger.warning(f"Skipping blueprint {attr}: {type(e).__name__}: {e}")
            failed.append((attr, str(e)))
    logger.info(f"Blueprints registered ({len(registered)}): {registered}")
    if failed:
        logger.warning(f"Blueprints skipped ({len(failed)}): "
                       f"{[name for name, _ in failed]}")


__all__ = ['register_blueprints']
