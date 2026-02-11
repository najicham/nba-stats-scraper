"""
Model codename mappings for public-facing exports.

All public names are opaque — no model architecture, algorithm, or strategy
details are exposed. Codenames are thematic (cities) so they reveal nothing
about the underlying model to anyone watching network traffic.

Session 188: Created. Opaque codenames for website JSON exports.
"""

# Internal system_id -> public codename (opaque, thematic)
MODEL_CODENAMES = {
    'catboost_v9': 'phoenix',
    'catboost_v9_202602': 'phoenix-b',  # Feb 2026 retrain (deprecated)
    'catboost_v9_q43_train1102_0131': 'aurora',
    'catboost_v9_q45_train1102_0131': 'summit',
    'catboost_v8': 'atlas',  # Legacy
    'ensemble_v1': 'echo',
    'similarity_v1': 'drift',
    'xgboost_v2': 'flint',
}

# Reverse lookup
CODENAME_TO_MODEL = {v: k for k, v in MODEL_CODENAMES.items()}

# Champion codename — used for sort ordering in exports
CHAMPION_CODENAME = 'phoenix'

# Display info for website rendering (Session 188)
# Only models with active subset definitions need entries here.
# CRITICAL: Nothing in this dict should reveal model architecture,
# algorithm type, training method, or strategy. Use generic descriptions only.
MODEL_DISPLAY_INFO = {
    'catboost_v9': {
        'codename': 'phoenix',
        'display_name': 'Phoenix',
        'model_type': 'primary',
        'description': 'Our primary prediction engine',
        'strengths': 'Balanced predictions across all players',
    },
    'catboost_v9_q43_train1102_0131': {
        'codename': 'aurora',
        'display_name': 'Aurora',
        'model_type': 'specialist',
        'description': 'Specialist engine with a different approach',
        'strengths': 'Strong on high-confidence picks',
    },
    'catboost_v9_q45_train1102_0131': {
        'codename': 'summit',
        'display_name': 'Summit',
        'model_type': 'specialist',
        'description': 'Conservative specialist engine',
        'strengths': 'Selective, high-conviction picks',
    },
}


def get_model_codename(system_id: str) -> str:
    """Get codename for a model system_id."""
    return MODEL_CODENAMES.get(system_id, system_id)


def get_model_from_codename(codename: str) -> str:
    """Get system_id from codename."""
    return CODENAME_TO_MODEL.get(codename, codename)


def get_model_display_info(system_id: str) -> dict:
    """Get display info for a model, for website rendering."""
    if system_id in MODEL_DISPLAY_INFO:
        return MODEL_DISPLAY_INFO[system_id]
    codename = get_model_codename(system_id)
    return {
        'codename': codename,
        'display_name': codename,
        'model_type': 'unknown',
        'description': '',
        'strengths': '',
    }


def get_codename_description(system_id: str) -> dict:
    """Get codename with basic description."""
    descriptions = {
        'catboost_v9': {
            'codename': '926A',
            'description': 'Current season model',
            'version': 'V9',
        },
        'catboost_v9_202602': {
            'codename': '926B',
            'description': 'Feb 2026 retrain',
            'version': 'V9.1',
        },
        'ensemble_v1': {
            'codename': 'E01',
            'description': '4-model ensemble',
            'version': 'V1',
        },
    }
    return descriptions.get(system_id, {
        'codename': system_id,
        'description': '',
        'version': '',
    })
