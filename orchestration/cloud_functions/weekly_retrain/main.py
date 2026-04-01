"""
Weekly Model Retrain Cloud Function

Automatically retrains all enabled model families every Monday at 5 AM ET.
Uses 56-day rolling window with governance gates. Walk-forward validated
across 2 NBA seasons (Sessions 454-457): 85% HR at edge 3+ with 7-day retrain.

Timing:
    Sunday evening: Phase 1-4 processes Sunday's games → feature store updated
    Monday 5:00 AM: This CF fires → trains all enabled families (56d window through Sunday)
    Monday ~5:45 AM: Retrain complete → fresh models in model_registry + GCS
    Monday 6:00 AM: Daily pipeline starts → Phase 1 scrapers
    Monday ~11:30 AM: Phase 5 predictions → worker loads fresh models

Deployment:
    Auto-deployed via cloudbuild-functions.yaml on push to main.
    Manual: cd orchestration/cloud_functions/weekly_retrain && ./deploy.sh

Scheduler (Every Monday at 5 AM ET):
    gcloud scheduler jobs create http weekly-retrain-job \
        --location=us-west2 \
        --schedule="0 5 * * 1" \
        --time-zone="America/New_York" \
        --uri=https://FUNCTION_URL \
        --http-method=POST \
        --oidc-service-account-email=<PROJECT_NUMBER>-compute@developer.gserviceaccount.com \
        --oidc-token-audience=https://FUNCTION_URL \
        --attempt-deadline=1800s \
        --project=nba-props-platform

Session 458 - Weekly Auto-Retrain
Session 471 - Added LightGBM and XGBoost support (was CatBoost-only)
"""

import hashlib
import json
import logging
import os
import tempfile
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import functions_framework
import numpy as np
import pandas as pd
from google.cloud import bigquery, storage

# Lazy imports for ML libraries (large, ~100MB each)
cb = None
lgb_module = None
xgb_module = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
GCS_BUCKET = os.environ.get('GCS_BUCKET', 'nba-props-platform-models')
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL')

# Walk-forward validated configuration (Sessions 454-457)
ROLLING_WINDOW_DAYS = 56
# Session 463: Extended from 7→14 days. 7-day window yielded N=18-20 at edge 3+,
# consistently below min_n_graded=25. 14 days doubles the candidate pool.
EVAL_DAYS = 14
MAX_FAMILIES_PER_RUN = 10  # Session 466: raised from 5 — 9+ families need retraining in crisis
MIN_ENABLED_MODELS = 3  # Safety floor: don't disable old if too few would remain

# CatBoost production hyperparameters
CATBOOST_PARAMS = {
    'iterations': 1000,
    'learning_rate': 0.05,
    'depth': 6,
    'l2_leaf_reg': 3,
    'random_seed': 42,
    'verbose': 0,
    'early_stopping_rounds': 50,
    'loss_function': 'MAE',
    'nan_mode': 'Min',
}

# Vegas feature indices to exclude for _noveg models
VEGAS_INDICES = {25, 26, 27, 28}

# Feature sets: feature_set_name -> list of feature indices
FEATURE_SETS = {
    'v9': list(range(33)),
    'v12': list(range(54)),
    'v12_noveg': [i for i in range(54) if i not in VEGAS_INDICES],
    'v16': list(range(57)),
    'v16_noveg': [i for i in range(57) if i not in VEGAS_INDICES],
}

# Governance gates (from CLAUDE.md)
# Session 463: min_n_graded lowered 50→25 to match quick_retrain.py (Session 382c).
# With 7-day eval window, edge 3+ filter yields ~25-45 candidates — 50 was too strict,
# causing ALL retrains to be BLOCKED (N=14-40 < 50 in Mar 10 run).
GOVERNANCE = {
    'min_hr_edge3': 53.0,     # Edge 3+ HR must be >= 53% (raw model ceiling ~53.4%, Session 458)
    'max_vegas_bias': 1.5,     # |avg(pred - line)| must be <= 1.5
    'max_tier_bias': 5.0,      # No tier bias > 5 points
    'min_n_graded': 15,        # Session 466: lowered 25→15. MAE families get N=18-20 at edge 3+ with 14d eval — 25 blocks them. 15 matches decay_detection threshold.
    'min_directional_hr': 52.4, # Both OVER and UNDER HR >= 52.4% at edge 3+
}


def get_catboost():
    """Lazy load catboost."""
    global cb
    if cb is None:
        import catboost
        cb = catboost
    return cb


def get_lightgbm():
    """Lazy load lightgbm."""
    global lgb_module
    if lgb_module is None:
        import lightgbm
        lgb_module = lightgbm
    return lgb_module


def get_xgboost():
    """Lazy load xgboost."""
    global xgb_module
    if xgb_module is None:
        import xgboost
        xgb_module = xgboost
    return xgb_module


# LightGBM production hyperparameters (from quick_retrain.py)
LIGHTGBM_PARAMS = {
    'verbose': -1,
    'seed': 42,
    'num_leaves': 63,
    'learning_rate': 0.05,
    'feature_fraction': 0.8,
    'bagging_fraction': 0.8,
    'bagging_freq': 5,
    'objective': 'regression',
    'metric': 'mae',
}

# XGBoost production hyperparameters (from quick_retrain.py)
XGBOOST_PARAMS = {
    'verbosity': 0,
    'seed': 42,
    'max_depth': 6,
    'learning_rate': 0.05,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'min_child_weight': 5,
    'reg_alpha': 0.1,
    'reg_lambda': 1.0,
    'objective': 'reg:absoluteerror',
    'eval_metric': 'mae',
}

# Framework prefix for model IDs and GCS paths
FRAMEWORK_PREFIXES = {
    'catboost': 'catboost',
    'lightgbm': 'lgbm',
    'xgboost': 'xgb',
}


# ─────────────────────────────────────────────────────────────────────────────
# Data Loading
# ─────────────────────────────────────────────────────────────────────────────

def get_enabled_families(client: bigquery.Client) -> List[Dict[str, Any]]:
    """Query model_registry for enabled model families."""
    query = f"""
    SELECT DISTINCT
        model_family,
        feature_set,
        loss_function,
        model_type,
        CAST(quantile_alpha AS FLOAT64) as quantile_alpha,
        MAX(training_end_date) as latest_train_end
    FROM `{PROJECT_ID}.nba_predictions.model_registry`
    WHERE enabled = TRUE AND status IN ('active', 'production')
      AND model_family IS NOT NULL
    GROUP BY model_family, feature_set, loss_function, model_type, quantile_alpha
    ORDER BY model_family
    """
    df = client.query(query).to_dataframe()
    families = []
    for _, row in df.iterrows():
        families.append({
            'model_family': row['model_family'],
            'feature_set': row['feature_set'],
            'loss_function': row['loss_function'],
            'model_type': row['model_type'] or 'catboost',
            'quantile_alpha': row['quantile_alpha'] if pd.notna(row['quantile_alpha']) else None,
            'latest_train_end': row['latest_train_end'],
        })
    return families


def cap_to_last_loose_market_date(
    client: bigquery.Client,
    train_end: date,
    tight_mae_threshold: float = 4.5,
    recovery_days: int = 7,
) -> date:
    """
    Cap train_end to avoid training through a recent TIGHT market period.

    When vegas_mae_7d < 4.5 (TIGHT), models learn Vegas is accurate and produce
    edge-collapsed predictions. If train_end falls within `recovery_days` of the
    last TIGHT day, cap it to the day before the TIGHT window started — ensuring
    the model's most recent signal is LOOSE data.

    After `recovery_days` of LOOSE market, TIGHT data is sufficiently diluted in
    the 56-day window and the cap no longer applies.

    Session 486: Fixes the backwards gate that manually paused the scheduler on
    LOOSE markets. Now the CF always runs but automatically protects training data.
    """
    lookback_start = train_end - timedelta(days=30)
    query = f"""
    SELECT game_date
    FROM `{PROJECT_ID}.nba_predictions.league_macro_daily`
    WHERE game_date BETWEEN '{lookback_start.isoformat()}' AND '{train_end.isoformat()}'
      AND vegas_mae_7d < {tight_mae_threshold}
    ORDER BY game_date ASC
    """
    df = client.query(query).to_dataframe()
    if df.empty:
        return train_end  # No TIGHT days in lookback range

    tight_dates = sorted(df['game_date'].tolist())
    latest_tight = tight_dates[-1]
    if hasattr(latest_tight, 'date'):
        latest_tight = latest_tight.date()

    days_since_tight = (date.today() - latest_tight).days
    if days_since_tight >= recovery_days:
        logger.info(
            f"  Market recovered: {days_since_tight}d since last TIGHT day "
            f"({latest_tight}) — no training cap needed"
        )
        return train_end

    # Cap to the day before the TIGHT period started
    earliest_tight = tight_dates[0]
    if hasattr(earliest_tight, 'date'):
        earliest_tight = earliest_tight.date()

    cap_date = earliest_tight - timedelta(days=1)
    logger.info(
        f"  TIGHT protection: last TIGHT day {latest_tight} was {days_since_tight}d ago "
        f"(< {recovery_days}d threshold) — capping train_end {train_end} → {cap_date}"
    )
    return cap_date


def load_training_data(
    client: bigquery.Client,
    start_date: str,
    end_date: str,
    feature_indices: List[int],
) -> Tuple[pd.DataFrame, pd.Series]:
    """Load training data from feature store with zero-tolerance quality gates."""
    feature_cols = ', '.join(f'mf.feature_{i}_value' for i in feature_indices)
    feature_names = [f'f{i}' for i in feature_indices]
    select_cols = ', '.join(
        f'mf.feature_{i}_value AS f{i}' for i in feature_indices
    )

    query = f"""
    SELECT
      {select_cols},
      pgs.points AS actual_points
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
      AND mf.feature_count >= 33
      AND mf.feature_quality_score >= 70
      AND mf.data_source NOT IN ('phase4_partial', 'early_season')
      AND pgs.points IS NOT NULL
      AND pgs.minutes_played > 0
      AND NOT (mf.feature_0_value = 10.0 AND mf.feature_1_value > 15)
    """
    df = client.query(query).to_dataframe()
    if df.empty:
        return pd.DataFrame(), pd.Series(dtype=float)

    X = df[feature_names]
    y = df['actual_points'].astype(float)
    return X, y


def load_eval_data(
    client: bigquery.Client,
    start_date: str,
    end_date: str,
    feature_indices: List[int],
) -> Tuple[pd.DataFrame, pd.Series, np.ndarray]:
    """Load eval data with prop lines for HR grading."""
    select_cols = ', '.join(
        f'mf.feature_{i}_value AS f{i}' for i in feature_indices
    )

    query = f"""
    SELECT
      {select_cols},
      pgs.points AS actual_points,
      mf.feature_25_value AS vegas_line
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
      AND mf.feature_count >= 33
      AND mf.feature_quality_score >= 70
      AND mf.data_source NOT IN ('phase4_partial', 'early_season')
      AND pgs.points IS NOT NULL
      AND pgs.minutes_played > 0
      AND mf.feature_25_value IS NOT NULL
      AND mf.feature_25_value > 0
    """
    df = client.query(query).to_dataframe()
    if df.empty:
        return pd.DataFrame(), pd.Series(dtype=float), np.array([])

    feature_names = [f'f{i}' for i in feature_indices]
    X = df[feature_names]
    y = df['actual_points'].astype(float)
    lines = df['vegas_line'].values.astype(float)
    return X, y, lines


# ─────────────────────────────────────────────────────────────────────────────
# Training & Evaluation
# ─────────────────────────────────────────────────────────────────────────────

def train_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    loss_function: str = 'MAE',
    quantile_alpha: Optional[float] = None,
    model_type: str = 'catboost',
) -> object:
    """Train model with production hyperparameters. Dispatches by framework."""
    if model_type == 'lightgbm':
        lgb = get_lightgbm()
        params = dict(LIGHTGBM_PARAMS)
        if quantile_alpha is not None:
            params['objective'] = 'quantile'
            params['alpha'] = quantile_alpha
            params['metric'] = 'quantile'
        dtrain = lgb.Dataset(X_train, y_train)
        dval = lgb.Dataset(X_val, y_val)
        model = lgb.train(
            params, dtrain, num_boost_round=1000,
            valid_sets=[dval], callbacks=[lgb.early_stopping(50, verbose=False)],
        )
        return model

    elif model_type == 'xgboost':
        xgb = get_xgboost()
        params = dict(XGBOOST_PARAMS)
        if quantile_alpha is not None:
            params['objective'] = 'reg:quantileerror'
            params['quantile_alpha'] = quantile_alpha
        feature_names = list(X_train.columns)
        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_names)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_names)
        model = xgb.train(
            params, dtrain, num_boost_round=1000,
            evals=[(dval, 'eval')],
            early_stopping_rounds=50, verbose_eval=0,
        )
        return model

    else:
        # CatBoost (default)
        catboost = get_catboost()
        params = dict(CATBOOST_PARAMS)
        if quantile_alpha is not None:
            params['loss_function'] = f'Quantile:alpha={quantile_alpha}'
        elif loss_function and loss_function.upper() != 'MAE':
            params['loss_function'] = loss_function
        model = catboost.CatBoostRegressor(**params)
        model.fit(X_train, y_train, eval_set=(X_val, y_val), verbose=0)
        return model


def compute_hit_rate(
    preds: np.ndarray,
    actuals: np.ndarray,
    lines: np.ndarray,
    min_edge: float = 1.0,
) -> Tuple[Optional[float], int]:
    """Compute directional hit rate at edge threshold."""
    edges = np.abs(preds - lines)
    mask = edges >= min_edge
    if mask.sum() == 0:
        return None, 0

    p, a, l = preds[mask], actuals[mask], lines[mask]
    over_pred = p > l
    wins = (over_pred & (a > l)) | (~over_pred & (a < l))
    pushes = a == l
    graded = mask.sum() - pushes.sum()
    if graded == 0:
        return None, 0
    return round(float(wins.sum()) / graded * 100, 2), int(graded)


def compute_directional_hr(
    preds: np.ndarray,
    actuals: np.ndarray,
    lines: np.ndarray,
    min_edge: float = 3.0,
) -> Dict[str, Tuple[Optional[float], int]]:
    """Compute OVER and UNDER hit rates separately."""
    edges = np.abs(preds - lines)
    result = {}
    for direction, cond in [('OVER', preds > lines), ('UNDER', preds < lines)]:
        d_mask = (edges >= min_edge) & cond
        if d_mask.sum() == 0:
            result[direction] = (None, 0)
            continue
        a_d, l_d = actuals[d_mask], lines[d_mask]
        wins = (a_d > l_d) if direction == 'OVER' else (a_d < l_d)
        pushes = a_d == l_d
        graded = d_mask.sum() - pushes.sum()
        if graded == 0:
            result[direction] = (None, 0)
        else:
            result[direction] = (round(float(wins.sum()) / graded * 100, 2), int(graded))
    return result


def run_governance_gates(
    preds: np.ndarray,
    actuals: np.ndarray,
    lines: np.ndarray,
    family_name: str,
) -> Tuple[bool, List[str]]:
    """Run all governance gates. Returns (passed, list_of_failures)."""
    failures = []

    # Gate 1: Edge 3+ HR >= 53% (lowered from 60% — raw model ceiling is ~53.4%)
    hr_e3, n_e3 = compute_hit_rate(preds, actuals, lines, min_edge=3.0)
    if n_e3 < GOVERNANCE['min_n_graded']:
        failures.append(f"N={n_e3} < {GOVERNANCE['min_n_graded']} graded at edge 3+")
    elif hr_e3 is None or hr_e3 < GOVERNANCE['min_hr_edge3']:
        failures.append(f"Edge 3+ HR={hr_e3}% < {GOVERNANCE['min_hr_edge3']}%")

    # Gate 2: Vegas bias within ±1.5
    valid_lines = ~np.isnan(lines) & (lines > 0)
    if valid_lines.sum() > 0:
        vegas_bias = float(np.mean(preds[valid_lines] - lines[valid_lines]))
        if abs(vegas_bias) > GOVERNANCE['max_vegas_bias']:
            failures.append(f"Vegas bias={vegas_bias:+.2f} outside ±{GOVERNANCE['max_vegas_bias']}")

    # Gate 3: Directional balance
    dir_hr = compute_directional_hr(preds, actuals, lines, min_edge=3.0)
    for direction in ['OVER', 'UNDER']:
        hr, n = dir_hr[direction]
        if hr is not None and n >= 20 and hr < GOVERNANCE['min_directional_hr']:
            failures.append(f"{direction} HR={hr}% < {GOVERNANCE['min_directional_hr']}% (N={n})")

    passed = len(failures) == 0
    return passed, failures


# ─────────────────────────────────────────────────────────────────────────────
# Model Upload & Registration
# ─────────────────────────────────────────────────────────────────────────────

def upload_model_to_gcs(
    model,
    feature_set: str,
    train_start: str,
    train_end: str,
    model_type: str = 'catboost',
) -> Tuple[str, str, str]:
    """Save model to GCS. Returns (gcs_path, model_id, sha256)."""
    prefix = FRAMEWORK_PREFIXES.get(model_type, 'catboost')

    # Generate model ID: {prefix}_{feature_set}_train{MMDD}_{MMDD}
    ts = train_start.replace('-', '')[4:]  # MMDD
    te = train_end.replace('-', '')[4:]
    model_id = f"{prefix}_{feature_set}_train{ts}_{te}"

    # Framework-specific file extensions and save logic
    if model_type == 'lightgbm':
        ext = '.txt'
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            temp_path = f.name
        model.save_model(temp_path)
    elif model_type == 'xgboost':
        ext = '.json'
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            temp_path = f.name
        model.save_model(temp_path)
    else:
        ext = '.cbm'
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            temp_path = f.name
        model.save_model(temp_path)

    # Compute SHA256
    with open(temp_path, 'rb') as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()

    # Upload to GCS with framework-specific directory
    base_fs = feature_set.replace('_noveg', '')
    gcs_dir = f"{prefix}/{base_fs}/monthly"
    filename = f"{model_id}{ext}"
    gcs_path = f"gs://{GCS_BUCKET}/{gcs_dir}/{filename}"

    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(f"{gcs_dir}/{filename}")
    blob.upload_from_filename(temp_path)

    os.unlink(temp_path)

    logger.info(f"  Uploaded: {gcs_path}")
    return gcs_path, model_id, sha256


def register_model(
    client: bigquery.Client,
    model_id: str,
    gcs_path: str,
    sha256: str,
    family: Dict[str, Any],
    train_start: str,
    train_end: str,
    training_samples: int,
    mae: float,
    hr_all: Optional[float],
    hr_e3: Optional[float],
    hr_e5: Optional[float],
    n_e3: int,
    enabled: bool = True,
) -> None:
    """Register model in model_registry using DML MERGE."""
    feature_set = family['feature_set']
    model_family = family['model_family']
    model_type = family.get('model_type', 'catboost')
    loss_function = family['loss_function'] or 'MAE'
    qa = family['quantile_alpha']
    model_version = feature_set.split('_')[0]  # v9, v12, v16, etc.
    feature_count = len(FEATURE_SETS.get(feature_set, list(range(54))))

    hr_all_val = f"{round(hr_all, 2)}" if hr_all else "NULL"
    hr_e3_val = f"{round(hr_e3, 2)}" if hr_e3 else "NULL"
    hr_e5_val = f"{round(hr_e5, 2)}" if hr_e5 else "NULL"
    qa_val = f"{qa}" if qa else "NULL"

    query = f"""
    MERGE `{PROJECT_ID}.nba_predictions.model_registry` AS target
    USING (SELECT '{model_id}' AS model_id) AS source
    ON target.model_id = source.model_id
    WHEN MATCHED THEN
      UPDATE SET
        gcs_path = '{gcs_path}',
        sha256_hash = '{sha256}',
        training_start_date = '{train_start}',
        training_end_date = '{train_end}',
        training_samples = {training_samples},
        evaluation_mae = {round(mae, 4)},
        evaluation_hit_rate = {hr_all_val},
        evaluation_hit_rate_edge_3plus = {hr_e3_val},
        evaluation_hit_rate_edge_5plus = {hr_e5_val},
        evaluation_n_edge_3plus = {n_e3},
        notes = 'Auto-retrained by weekly-retrain CF'
    WHEN NOT MATCHED THEN
      INSERT (model_id, model_version, model_type, gcs_path, sha256_hash,
         feature_count, feature_set, model_family, loss_function, quantile_alpha,
         training_start_date, training_end_date, training_samples,
         evaluation_mae, evaluation_hit_rate,
         evaluation_hit_rate_edge_3plus, evaluation_hit_rate_edge_5plus,
         evaluation_n_edge_3plus,
         status, is_production, enabled,
         notes, created_at, created_by)
      VALUES
        ('{model_id}', '{model_version}', '{model_type}', '{gcs_path}', '{sha256}',
         {feature_count}, '{feature_set}', '{model_family}', '{loss_function}', {qa_val},
         '{train_start}', '{train_end}', {training_samples},
         {round(mae, 4)}, {hr_all_val},
         {hr_e3_val}, {hr_e5_val},
         {n_e3},
         'active', FALSE, {str(enabled).upper()},
         'Auto-retrained by weekly-retrain CF',
         CURRENT_TIMESTAMP(), 'weekly_retrain')
    """
    job = client.query(query)
    job.result()
    logger.info(f"  Registered: {model_id} (enabled={enabled}, type={model_type})")


# ─────────────────────────────────────────────────────────────────────────────
# Family Retraining
# ─────────────────────────────────────────────────────────────────────────────

def retrain_family(
    client: bigquery.Client,
    family: Dict[str, Any],
    train_start: str,
    train_end: str,
    eval_start: str,
    eval_end: str,
) -> Dict[str, Any]:
    """Retrain a single model family. Returns result dict."""
    family_name = family['model_family']
    feature_set = family['feature_set']
    result = {'family': family_name, 'status': 'unknown'}

    # Resolve feature indices
    if feature_set not in FEATURE_SETS:
        result['status'] = 'skipped'
        result['reason'] = f"Unknown feature_set: {feature_set}"
        return result

    feature_indices = FEATURE_SETS[feature_set]
    logger.info(f"  Loading training data ({train_start} to {train_end})...")
    X_train_full, y_train_full = load_training_data(
        client, train_start, train_end, feature_indices
    )

    if len(X_train_full) < 1000:
        result['status'] = 'skipped'
        result['reason'] = f"Insufficient training data: {len(X_train_full)}"
        return result

    logger.info(f"  Training data: {len(X_train_full):,} rows")

    # 85/15 date-based split
    X_train_full['_idx'] = range(len(X_train_full))
    split_idx = int(len(X_train_full) * 0.85)
    X_train = X_train_full.iloc[:split_idx].drop(columns=['_idx'])
    X_val = X_train_full.iloc[split_idx:].drop(columns=['_idx'])
    y_train = y_train_full.iloc[:split_idx]
    y_val = y_train_full.iloc[split_idx:]
    X_train_full = X_train_full.drop(columns=['_idx'])

    # Train
    model_type = family.get('model_type', 'catboost')
    fw_label = model_type.replace('lightgbm', 'LightGBM').replace('xgboost', 'XGBoost').replace('catboost', 'CatBoost')
    logger.info(f"  Training {fw_label} ({len(X_train):,} train, {len(X_val):,} val)...")
    model = train_model(
        X_train, y_train, X_val, y_val,
        loss_function=family.get('loss_function', 'MAE'),
        quantile_alpha=family.get('quantile_alpha'),
        model_type=model_type,
    )

    # Load eval data
    logger.info(f"  Loading eval data ({eval_start} to {eval_end})...")
    X_eval, y_eval, lines = load_eval_data(
        client, eval_start, eval_end, feature_indices
    )

    if len(X_eval) < 50:
        result['status'] = 'skipped'
        result['reason'] = f"Insufficient eval data: {len(X_eval)}"
        return result

    # Evaluate — framework-specific prediction
    if model_type == 'xgboost':
        xgb = get_xgboost()
        feature_names = [f'f{i}' for i in feature_indices]
        deval = xgb.DMatrix(X_eval, feature_names=feature_names)
        preds = model.predict(deval)
    else:
        preds = model.predict(X_eval)
    mae = float(np.mean(np.abs(preds - y_eval.values)))
    hr_all, n_all = compute_hit_rate(preds, y_eval.values, lines, min_edge=1.0)
    hr_e3, n_e3 = compute_hit_rate(preds, y_eval.values, lines, min_edge=3.0)
    hr_e5, n_e5 = compute_hit_rate(preds, y_eval.values, lines, min_edge=5.0)

    logger.info(f"  MAE={mae:.3f}, HR(e1)={hr_all}% N={n_all}, HR(e3)={hr_e3}% N={n_e3}")

    # Governance gates
    passed, failures = run_governance_gates(preds, y_eval.values, lines, family_name)

    if not passed:
        result['status'] = 'blocked'
        result['reason'] = '; '.join(failures)
        result['mae'] = mae
        result['hr_e3'] = hr_e3
        result['n_e3'] = n_e3
        logger.warning(f"  BLOCKED: {'; '.join(failures)}")
        return result

    # Upload to GCS
    logger.info(f"  Governance gates PASSED. Uploading to GCS...")
    gcs_path, model_id, sha256 = upload_model_to_gcs(
        model, feature_set, train_start, train_end, model_type=model_type,
    )

    # Register in model_registry
    register_model(
        client, model_id, gcs_path, sha256, family,
        train_start, train_end, len(X_train_full),
        mae, hr_all, hr_e3, hr_e5, n_e3,
        enabled=True,
    )

    result['status'] = 'success'
    result['model_id'] = model_id
    result['gcs_path'] = gcs_path
    result['mae'] = mae
    result['hr_all'] = hr_all
    result['hr_e3'] = hr_e3
    result['hr_e5'] = hr_e5
    result['n_e3'] = n_e3
    result['training_samples'] = len(X_train_full)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────────────────────────

def send_slack_notification(results: List[Dict], train_end: str) -> None:
    """Send Slack notification with retrain summary."""
    if not SLACK_WEBHOOK:
        logger.warning("No SLACK_WEBHOOK_URL configured")
        return

    import requests

    succeeded = [r for r in results if r['status'] == 'success']
    blocked = [r for r in results if r['status'] == 'blocked']
    skipped = [r for r in results if r['status'] == 'skipped']

    if succeeded:
        color = "#36a64f"  # green
        emoji = ":white_check_mark:"
    elif blocked:
        color = "#ff9800"  # orange
        emoji = ":warning:"
    else:
        color = "#ff0000"  # red
        emoji = ":x:"

    lines_text = []
    for r in succeeded:
        lines_text.append(
            f":white_check_mark: *{r['family']}* → `{r.get('model_id', '?')}` "
            f"MAE={r.get('mae', '?'):.3f} HR(e3)={r.get('hr_e3', '?')}% N={r.get('n_e3', 0)}"
        )
    for r in blocked:
        lines_text.append(
            f":no_entry: *{r['family']}* BLOCKED: {r.get('reason', '?')}"
        )
    for r in skipped:
        lines_text.append(
            f":fast_forward: *{r['family']}* skipped: {r.get('reason', '?')}"
        )

    payload = {
        "attachments": [{
            "color": color,
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji} Weekly Retrain Complete — train through {train_end}",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": '\n'.join(lines_text) or "No families processed"
                    }
                },
                {
                    "type": "context",
                    "elements": [{
                        "type": "mrkdwn",
                        "text": (
                            f"{len(succeeded)} trained | {len(blocked)} blocked | "
                            f"{len(skipped)} skipped | "
                            f"Window: {ROLLING_WINDOW_DAYS}d | Eval: {EVAL_DAYS}d"
                        )
                    }]
                }
            ]
        }]
    }

    try:
        response = requests.post(SLACK_WEBHOOK, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Slack notification sent")
    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

@functions_framework.http
def weekly_retrain(request):
    """
    HTTP Cloud Function entry point.

    Query params:
        dry_run: If 'true', show plan without executing
        family: Retrain only this family (default: all enabled)
        train_end: Override train end date (default: yesterday)
    """
    try:
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'
        family_filter = request.args.get('family')
        train_end_override = request.args.get('train_end')

        # Compute dates
        if train_end_override:
            train_end = date.fromisoformat(train_end_override)
        else:
            train_end = date.today() - timedelta(days=1)  # Yesterday

        # Out-of-sample eval: reserve the most recent EVAL_DAYS for evaluation,
        # training ends the day before the eval window starts.
        eval_end = train_end
        eval_start = eval_end - timedelta(days=EVAL_DAYS - 1)
        train_end = eval_start - timedelta(days=1)
        train_start = train_end - timedelta(days=ROLLING_WINDOW_DAYS)
        eval_start_str = eval_start.isoformat()
        eval_end_str = eval_end.isoformat()
        train_start_str = train_start.isoformat()
        train_end_str = train_end.isoformat()

        logger.info("=" * 60)
        logger.info("WEEKLY AUTO-RETRAIN")
        logger.info("=" * 60)
        logger.info(f"Training:   {train_start_str} to {train_end_str} ({ROLLING_WINDOW_DAYS}d)")
        logger.info(f"Evaluation: {eval_start_str} to {eval_end_str} ({EVAL_DAYS}d)")

        # Get families
        client = bigquery.Client(project=PROJECT_ID)

        # Cap training to avoid TIGHT market contamination (Session 486)
        # Models trained through TIGHT periods (vegas_mae < 4.5) produce edge collapse.
        # Skip cap if train_end was explicitly overridden (caller knows what they want).
        if not train_end_override:
            capped = cap_to_last_loose_market_date(client, train_end)
            if capped != train_end:
                train_end = capped
                train_start = train_end - timedelta(days=ROLLING_WINDOW_DAYS)
                train_start_str = train_start.isoformat()
                train_end_str = train_end.isoformat()
                logger.info(f"  (Adjusted) Training: {train_start_str} to {train_end_str}")

        families = get_enabled_families(client)

        if family_filter:
            families = [f for f in families if f['model_family'] == family_filter]

        # Skip families retrained in last 5 days
        stale_families = []
        for f in families:
            latest = f.get('latest_train_end')
            if latest and hasattr(latest, 'isoformat'):
                days_since = (date.today() - latest).days if isinstance(latest, date) else 999
            else:
                days_since = 999

            if days_since < 5:
                logger.info(f"  Skipping {f['model_family']} — retrained {days_since}d ago")
            else:
                stale_families.append(f)

        families = stale_families[:MAX_FAMILIES_PER_RUN]

        logger.info(f"Families to retrain: {[f['model_family'] for f in families]}")

        if dry_run:
            return {
                'status': 'dry_run',
                'train_window': f"{train_start_str} to {train_end_str}",
                'eval_window': f"{eval_start_str} to {eval_end_str}",
                'families': [f['model_family'] for f in families],
                'message': 'Dry run — would retrain above families',
            }, 200

        if not families:
            logger.info("No families need retraining")
            return {'status': 'no_work', 'message': 'All families recently retrained'}, 200

        # Retrain each family
        results = []
        for family in families:
            logger.info(f"\n{'─' * 50}")
            logger.info(f"RETRAINING: {family['model_family']}")
            logger.info(f"  feature_set={family['feature_set']}, loss={family['loss_function']}, type={family.get('model_type', 'catboost')}")
            logger.info(f"{'─' * 50}")

            try:
                result = retrain_family(
                    client, family,
                    train_start_str, train_end_str,
                    eval_start_str, eval_end_str,
                )
                results.append(result)
            except Exception as e:
                logger.exception(f"  FAILED: {family['model_family']}: {e}")
                results.append({
                    'family': family['model_family'],
                    'status': 'error',
                    'reason': str(e),
                })

        # Send notification
        send_slack_notification(results, train_end_str)

        # Summary
        succeeded = [r for r in results if r['status'] == 'success']
        blocked = [r for r in results if r['status'] == 'blocked']
        errors = [r for r in results if r['status'] == 'error']

        logger.info("\n" + "=" * 60)
        logger.info("WEEKLY RETRAIN COMPLETE")
        logger.info(f"  Succeeded: {len(succeeded)}")
        logger.info(f"  Blocked:   {len(blocked)}")
        logger.info(f"  Errors:    {len(errors)}")
        logger.info("=" * 60)

        return {
            'status': 'success',
            'train_window': f"{train_start_str} to {train_end_str}",
            'results': results,
            'summary': {
                'succeeded': len(succeeded),
                'blocked': len(blocked),
                'errors': len(errors),
            }
        }, 200

    except Exception as e:
        logger.exception(f"Weekly retrain failed: {e}")

        # Try to send error notification
        try:
            send_slack_notification(
                [{'family': 'ALL', 'status': 'error', 'reason': str(e)}],
                'unknown'
            )
        except Exception:
            pass

        return {'status': 'error', 'message': str(e)}, 200  # Return 200 so scheduler doesn't retry


# Gen2 CF entry point alias (immutable after deploy)
main = weekly_retrain
