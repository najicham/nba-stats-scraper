"""
Model codename mappings for testing/development.

Simple alphanumeric codes to identify models without exposing
technical details during testing phase.
"""

# Model codename mapping
MODEL_CODENAMES = {
    'catboost_v9': '926A',
    'catboost_v9_202602': '926B',  # Feb 2026 retrain
    'ensemble_v1': 'E01',
    'similarity_v1': 'S01',
    'xgboost_v2': 'X02',
    'catboost_v8': '825A',  # Legacy
}

# Reverse lookup
CODENAME_TO_MODEL = {v: k for k, v in MODEL_CODENAMES.items()}


def get_model_codename(system_id: str) -> str:
    """Get codename for a model system_id."""
    return MODEL_CODENAMES.get(system_id, system_id)


def get_model_from_codename(codename: str) -> str:
    """Get system_id from codename."""
    return CODENAME_TO_MODEL.get(codename, codename)


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
