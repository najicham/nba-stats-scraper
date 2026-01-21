"""
ML Model Loader

Dynamically loads ML models based on type (catboost, xgboost, lightgbm, etc.)
Supports loading from local files or GCS.

Usage:
    from ml.model_loader import load_model, ModelInfo

    model_info = ModelInfo(
        model_id='catboost_v8',
        model_type='catboost',
        model_path='gs://bucket/models/catboost_v8.cbm',
        model_format='cbm'
    )
    model = load_model(model_info)
    prediction = model.predict(features)
"""

from dataclasses import dataclass
from typing import Optional, Any, Dict, List
from pathlib import Path
import hashlib
import logging
import os
import tempfile
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    """Information about a model from the registry"""
    model_id: str
    model_type: str  # 'catboost', 'xgboost', 'lightgbm', 'sklearn'
    model_path: str  # Local path or GCS path
    model_format: str  # 'cbm', 'json', 'txt', 'pkl'
    feature_count: int
    feature_list: Optional[List[str]] = None


class ModelWrapper:
    """Wrapper that provides consistent interface across model types"""

    def __init__(self, model: Any, model_info: ModelInfo):
        self.model = model
        self.model_info = model_info

    def predict(self, features: np.ndarray) -> np.ndarray:
        """Make prediction using the underlying model"""
        return self.model.predict(features)

    @property
    def model_id(self) -> str:
        return self.model_info.model_id

    @property
    def feature_count(self) -> int:
        return self.model_info.feature_count


def load_model(model_info: ModelInfo) -> Optional[ModelWrapper]:
    """
    Load a model based on its type and path

    Args:
        model_info: Model information from registry

    Returns:
        ModelWrapper or None if loading fails
    """
    try:
        # Download from GCS if needed
        local_path = _ensure_local(model_info.model_path)

        if local_path is None:
            logger.error(f"Could not get local path for {model_info.model_path}")
            return None

        # Load based on type
        if model_info.model_type == 'catboost':
            model = _load_catboost(local_path, model_info.model_format)
        elif model_info.model_type == 'xgboost':
            model = _load_xgboost(local_path, model_info.model_format)
        elif model_info.model_type == 'lightgbm':
            model = _load_lightgbm(local_path, model_info.model_format)
        elif model_info.model_type == 'sklearn':
            model = _load_sklearn(local_path)
        else:
            logger.error(f"Unknown model type: {model_info.model_type}")
            return None

        if model is None:
            return None

        logger.info(f"Loaded model {model_info.model_id} ({model_info.model_type})")
        return ModelWrapper(model, model_info)

    except Exception as e:
        logger.error(f"Error loading model {model_info.model_id}: {e}")
        return None


def _ensure_local(path: str) -> Optional[str]:
    """Ensure we have a local path to the model file"""
    if path.startswith("gs://"):
        return _download_from_gcs(path)
    elif Path(path).exists():
        return path
    else:
        # Try relative to models/ directory
        models_dir = Path(__file__).parent.parent / "models"
        local_path = models_dir / Path(path).name
        if local_path.exists():
            return str(local_path)
        logger.error(f"Model file not found: {path}")
        return None


def _download_from_gcs(gcs_path: str) -> Optional[str]:
    """Download model from GCS to temp file"""
    try:
        from google.cloud import storage

        # Parse GCS path
        parts = gcs_path.replace("gs://", "").split("/", 1)
        bucket_name, blob_path = parts[0], parts[1]

        # Create temp file with appropriate extension
        suffix = Path(blob_path).suffix
        temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)

        # Download
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.download_to_filename(temp_file.name)

        logger.info(f"Downloaded {gcs_path} to {temp_file.name}")
        return temp_file.name

    except Exception as e:
        logger.error(f"Error downloading from GCS: {e}")
        return None


def _load_catboost(path: str, format: str) -> Optional[Any]:
    """Load CatBoost model"""
    try:
        import catboost as cb

        model = cb.CatBoostRegressor()
        model.load_model(path, format=format)
        return model

    except ImportError:
        logger.error("CatBoost not installed. Run: pip install catboost")
        return None
    except Exception as e:
        logger.error(f"Error loading CatBoost model: {e}")
        return None


def _load_xgboost(path: str, format: str) -> Optional[Any]:
    """Load XGBoost model"""
    try:
        import xgboost as xgb

        if format == 'json':
            model = xgb.Booster()
            model.load_model(path)
            # Wrap in a regressor-like interface
            return XGBoostWrapper(model)
        else:
            model = xgb.XGBRegressor()
            model.load_model(path)
            return model

    except ImportError:
        logger.error("XGBoost not installed. Run: pip install xgboost")
        return None
    except Exception as e:
        logger.error(f"Error loading XGBoost model: {e}")
        return None


class XGBoostWrapper:
    """Wrapper for XGBoost Booster to provide predict() interface"""

    def __init__(self, booster):
        self.booster = booster

    def predict(self, features: np.ndarray) -> np.ndarray:
        import xgboost as xgb
        dmatrix = xgb.DMatrix(features)
        return self.booster.predict(dmatrix)


def _load_lightgbm(path: str, format: str) -> Optional[Any]:
    """Load LightGBM model"""
    try:
        import lightgbm as lgb

        model = lgb.Booster(model_file=path)
        return LightGBMWrapper(model)

    except ImportError:
        logger.error("LightGBM not installed. Run: pip install lightgbm")
        return None
    except Exception as e:
        logger.error(f"Error loading LightGBM model: {e}")
        return None


class LightGBMWrapper:
    """Wrapper for LightGBM Booster to provide consistent predict() interface"""

    def __init__(self, booster):
        self.booster = booster

    def predict(self, features: np.ndarray) -> np.ndarray:
        return self.booster.predict(features)


def _load_sklearn(path: str) -> Optional[Any]:
    """
    Load sklearn model with integrity validation.

    Requires: {path}.sha256 file with expected hash
    Raises: ValueError if hash validation fails
    """
    try:
        import joblib

        # Step 1: Load expected hash
        hash_file = f"{path}.sha256"
        if not os.path.exists(hash_file):
            raise ValueError(f"Model hash file missing: {hash_file}")

        with open(hash_file, 'r') as f:
            expected_hash = f.read().strip()

        # Step 2: Compute actual hash
        with open(path, 'rb') as f:
            content = f.read()
            actual_hash = hashlib.sha256(content).hexdigest()

        # Step 3: Verify integrity
        if actual_hash != expected_hash:
            raise ValueError(
                f"Model integrity check FAILED!\n"
                f"Expected: {expected_hash}\n"
                f"Got:      {actual_hash}\n"
                f"Possible tampering detected - refusing to load"
            )

        # Step 4: Log validation success
        logger.info(f"Loading model from {path}")
        logger.info(f"Expected hash: {expected_hash[:16]}...")
        logger.info(f"Actual hash:   {actual_hash[:16]}...")
        logger.info("✅ Hash validation passed")

        # Step 5: Load with joblib (safer than pickle)
        return joblib.load(path)

    except Exception as e:
        logger.error(f"Error loading sklearn model: {e}")
        return None


# Cache for loaded models
_model_cache: Dict[str, ModelWrapper] = {}


def get_cached_model(model_info: ModelInfo) -> Optional[ModelWrapper]:
    """Get model from cache or load it"""
    if model_info.model_id not in _model_cache:
        model = load_model(model_info)
        if model:
            _model_cache[model_info.model_id] = model
    return _model_cache.get(model_info.model_id)


def clear_model_cache():
    """Clear the model cache"""
    _model_cache.clear()
