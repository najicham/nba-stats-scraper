"""Low-Variance Mid-Line UNDER — archetype grid completion (Wave 1).

Pre-registered hypothesis (no backtest). Completes the 3x3 archetype grid.

THE GRID (line bucket x variance bucket):
  low_line  + low_var UNDER: 62.0% HR (N=819, 4/4 seasons) — known finding
  mid_line  + low_var UNDER: UNTESTED — this signal
  high_line + low_var UNDER: UNTESTED — companion to implement separately

Hypothesis: consistent mid-tier scorers (std < 4.5, line 15-25) have the same
structural market mispricing as low-line consistent scorers: the line is set
assuming more upside than a tight distribution allows. Their scoring floor is
high but their ceiling is equally constrained — the book doesn't discount the
ceiling constraint enough.

Distinct from low_variance_under_block (the observation-mode FILTER in aggregator.py):
that filter blocks at edge 3-5 regardless of line bucket. This is a POSITIVE shadow
signal that contributes to signal tracking. They are complementary.

Data sources:
  pred['points_std_last_10'] — feature_3_value, already in pred dict
  pred['line_value'] — always present

Created: 2026-07-01 (pre-registered, promote at N>=30 HR>=60% live 2026-27)
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class LowVarMidLineUnderSignal(BaseSignal):
    tag = "low_var_mid_line_under"
    description = (
        "Low variance (std < 4.5) + mid-line (15-25) UNDER — archetype grid completion "
        "(pre-registered, shadow)"
    )

    STD_THRESHOLD = 4.5    # matches low_variance_under_block gate
    LINE_MIN = 15.0
    LINE_MAX = 25.0
    CONFIDENCE = 0.62      # prior from low_line + low_var cell HR

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        line = float(prediction.get('line_value') or prediction.get('current_points_line') or 0)
        if not (self.LINE_MIN <= line <= self.LINE_MAX):
            return self._no_qualify()

        pts_std = prediction.get('points_std_last_10')
        if pts_std is None or float(pts_std) <= 0:
            return self._no_qualify()

        if float(pts_std) >= self.STD_THRESHOLD:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'points_std_last_10': round(float(pts_std), 2),
                'line_value': round(line, 1),
                'archetype_cell': 'mid_line+low_var',
                'pre_registered': '2026-07-01',
            },
        )
