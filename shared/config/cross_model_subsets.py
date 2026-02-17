"""Cross-model observation subset definitions.

Defines 5 meta-subsets that observe cross-model agreement patterns.
These are observation-only subsets written to current_subset_picks
with system_id='cross_model'. The existing SubsetGradingProcessor
handles grading automatically (grades by subset_id, agnostic to system_id).

Session 277: Initial creation.
"""

# Model groups for cross-model analysis
MAE_MODELS = [
    'catboost_v9_train1102_0205',
    'catboost_v12_noveg_train1102_0205',
]

QUANTILE_MODELS = [
    'catboost_v9_q43_train1102_0125',
    'catboost_v9_q45_train1102_0125',
    'catboost_v12_noveg_q43_train1102_0125',
    'catboost_v12_noveg_q45_train1102_0125',
]

ALL_MODELS = MAE_MODELS + QUANTILE_MODELS

# Feature set grouping (for diversity scoring)
V9_FEATURE_SET = {
    'catboost_v9_train1102_0205',
    'catboost_v9_q43_train1102_0125',
    'catboost_v9_q45_train1102_0125',
}

V12_FEATURE_SET = {
    'catboost_v12_noveg_train1102_0205',
    'catboost_v12_noveg_q43_train1102_0125',
    'catboost_v12_noveg_q45_train1102_0125',
}


# Cross-model subset definitions
CROSS_MODEL_SUBSETS = {
    'xm_consensus_3plus': {
        'description': '3+ models agree on direction, all with edge >= 3',
        'min_agreeing_models': 3,
        'min_edge': 3.0,
        'direction': None,  # ANY direction
        'top_n': None,      # No limit
    },
    'xm_consensus_5plus': {
        'description': '5+ models agree, top 5 picks by avg edge',
        'min_agreeing_models': 5,
        'min_edge': 3.0,
        'direction': None,
        'top_n': 5,
    },
    'xm_quantile_agreement_under': {
        'description': 'All 4 quantile models agree UNDER, edge >= 3',
        'min_agreeing_models': 4,
        'min_edge': 3.0,
        'direction': 'UNDER',
        'required_models': QUANTILE_MODELS,
        'top_n': None,
    },
    'xm_mae_plus_quantile_over': {
        'description': 'MAE model says OVER + any quantile confirms OVER',
        'min_agreeing_models': 2,
        'min_edge': 3.0,
        'direction': 'OVER',
        'require_mae_and_quantile': True,
        'top_n': None,
    },
    'xm_diverse_agreement': {
        'description': 'V9 + V12 (different feature sets) agree, both edge >= 3',
        'min_agreeing_models': 2,
        'min_edge': 3.0,
        'direction': None,
        'require_feature_diversity': True,
        'top_n': None,
    },
}
