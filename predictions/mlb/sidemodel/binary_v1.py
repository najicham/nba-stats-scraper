# predictions/mlb/sidemodel/binary_v1.py
"""
MLB binary side-model (v1) — shadow scorer for pick probability.

Target: P(prediction_correct = True | features, recommendation).

Slice 1 plumbing — this loader runs alongside the production regressor and
writes its probability to `pitcher_strikeouts.p_sidemodel`. No filter or
pick-ranking changes downstream until N >= 100 shadow rows accumulate and a
CF analysis decides whether to promote.

Artifact contract
-----------------
The pickle at MLB_SIDEMODEL_PATH must contain a dict with:

    {
        'model':         <fitted estimator with .predict_proba(X)>,
        'feature_names': [<str>, ...]   # order matches X columns
        'version':       '<str>'        # e.g. 'binary_v1_20260520'
    }

`feature_names` may include the synthetic columns `recommendation_OVER` and
`recommendation_UNDER` — this loader injects 1/0 values for those before
the vector is built, so the trainer can treat them like any other feature.

Failure modes (return None from `score()`):
- model_path is None / env var unset       -> no-op
- pickle download or unpickle fails        -> no-op (logged at init)
- a required feature is missing from input -> None

Mirrors the GCS load pattern from
`predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.load_model`.
"""

from __future__ import annotations

import logging
import os
import pickle
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class BinaryV1SideModel:
    """Shadow binary classifier producing P(prediction_correct=True)."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self.model = None
        self.feature_names: List[str] = []
        self.version: Optional[str] = None
        self._loaded = False

        if self.model_path:
            self._load()
        else:
            logger.info(
                "[binary_v1_sidemodel] No model_path provided (MLB_SIDEMODEL_PATH unset). "
                "score() will return None."
            )

    def _load(self) -> None:
        """Download + unpickle the artifact from GCS. Failures are logged, not raised."""
        try:
            from google.cloud import storage

            if not self.model_path.startswith('gs://'):
                logger.error(
                    "[binary_v1_sidemodel] Expected gs:// path, got %s. Side-model disabled.",
                    self.model_path,
                )
                return

            bucket_name, blob_path = self.model_path.replace('gs://', '').split('/', 1)
            local_path = '/tmp/mlb_sidemodel_binary_v1.pkl'

            logger.info("[binary_v1_sidemodel] Loading artifact from %s", self.model_path)
            client = storage.Client()
            client.bucket(bucket_name).blob(blob_path).download_to_filename(local_path)

            with open(local_path, 'rb') as f:
                artifact = pickle.load(f)

            self.model = artifact['model']
            self.feature_names = list(artifact['feature_names'])
            self.version = str(artifact['version'])
            self._loaded = True

            logger.info(
                "[binary_v1_sidemodel] Loaded version=%s features=%d",
                self.version, len(self.feature_names),
            )

        except Exception as exc:
            logger.error(
                "[binary_v1_sidemodel] Failed to load artifact (%s). Side-model disabled.",
                exc, exc_info=True,
            )
            self.model = None
            self._loaded = False

    def score(self, features: Dict, recommendation: str) -> Optional[float]:
        """
        Return P(prediction_correct=True) given the feature dict and the
        regressor's OVER/UNDER recommendation. Returns None if the side-model
        isn't loaded, the recommendation isn't OVER/UNDER, or any required
        feature is missing.
        """
        if not self._loaded or self.model is None:
            return None
        if recommendation not in ('OVER', 'UNDER'):
            return None

        # Inject recommendation one-hots so the trainer can treat them as
        # ordinary feature columns.
        enriched = dict(features)
        enriched['recommendation_OVER'] = 1.0 if recommendation == 'OVER' else 0.0
        enriched['recommendation_UNDER'] = 1.0 if recommendation == 'UNDER' else 0.0

        try:
            row = []
            for name in self.feature_names:
                if name not in enriched or enriched[name] is None:
                    return None
                row.append(float(enriched[name]))

            proba = self.model.predict_proba([row])
            return float(proba[0][1])

        except Exception as exc:
            logger.warning(
                "[binary_v1_sidemodel] score() failed (rec=%s): %s",
                recommendation, exc,
            )
            return None
