"""Lazy, cached loader for the shadow win-probability calibrator.

Wraps `EdgeCalibrator` with graceful failure so the best-bets exporter can
attach an informational `win_prob` to each pick without any risk of crashing.

- Loads the versioned calibrator from CALIBRATOR_DIR once and caches it.
- `attach_win_prob(edge, family, direction)` returns a float in [0,1] or None.
- Never raises: any load/predict failure -> None (win_prob simply absent).

v2026-07-04-live: refit on provenance-verified LIVE rows only (prediction
created pre-game; the 2022-25 `prediction_accuracy` strata are backfill-leaked
and must never be trained on — see edge_calibrator.validate_training_provenance).
Reliability: see docs/08-projects/current/calibration-wiring/RELIABILITY-REPORT.md
SHADOW ONLY: this value is informational and must NOT gate selection/ranking.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Versioned live-verified calibrators. The v2026-07-03 dir is QUARANTINED
# (backfill-leaked training data — do not point back at it).
CALIBRATOR_DIR = Path('models/edge_calibrators/v2026-07-04-live')

_calibrator = None            # cached EdgeCalibrator instance
_load_attempted = False       # so we only try (and log) once


def _get_calibrator():
    """Load and cache the calibrator once. Returns None on any failure."""
    global _calibrator, _load_attempted
    if _load_attempted:
        return _calibrator
    _load_attempted = True
    try:
        stats_path = CALIBRATOR_DIR / 'calibration_stats.pkl'
        if not stats_path.exists():
            logger.warning(
                "win_prob calibrator not found at %s — win_prob will be null",
                CALIBRATOR_DIR,
            )
            return None
        from ml.calibration.edge_calibrator import EdgeCalibrator
        cal = EdgeCalibrator().load(CALIBRATOR_DIR)
        if not cal.calibrators:
            logger.warning("win_prob calibrator loaded but empty — win_prob will be null")
            return None
        _calibrator = cal
        logger.info(
            "Loaded shadow win_prob calibrator from %s (%d curves)",
            CALIBRATOR_DIR, len(cal.calibrators),
        )
    except Exception as e:  # noqa: BLE001 — never let this break export
        logger.warning("Failed to load win_prob calibrator: %s — win_prob will be null", e)
        _calibrator = None
    return _calibrator


def attach_win_prob(edge, family, direction) -> Optional[float]:
    """Return calibrated P(win) in [0,1], or None if unavailable.

    Graceful: missing pkl, unknown (family, direction), or bad inputs -> None.
    The family is passed through as-is (production `source_model_family`, e.g.
    'v12_noveg_mae'); EdgeCalibrator's fallback chain is (family, direction)
    → _pooled_{direction} → _global. The old `'_none'` substitution was the
    direction-blind bug: it never matched a fitted key, so every pick routed
    to _global, which pools OVER+UNDER.
    """
    cal = _get_calibrator()
    if cal is None:
        return None
    try:
        e = float(edge)
        if direction not in ('OVER', 'UNDER'):
            return None
        p = cal.predict_win_prob(e, family or None, direction)
        if p is None:
            return None
        p = float(p)
        # Clamp defensively; isotonic already bounds to [0,1].
        return max(0.0, min(1.0, round(p, 4)))
    except Exception as e:  # noqa: BLE001
        logger.debug("attach_win_prob failed (edge=%s fam=%s dir=%s): %s", edge, family, direction, e)
        return None
