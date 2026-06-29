"""Whole-number prop line precision signal — model predictions are significantly more
accurate when the book has set the line at a whole number (no .5 increment).

DISCOVERED 2026-06-29 via structural data analysis on 5-season prediction_accuracy.

Evidence (raw model at edge>=3, 2022-23 through 2025-26, N=6977 whole-line picks):
  - whole_line OVER: 74-84% HR by season (avg ~76.8%) vs 63-67% half-line
  - whole_line UNDER: 74-83% HR by season (avg ~76.8%) vs 61-63% half-line
  - Gap of +10-20pp CONSISTENT across ALL 5 seasons and ALL line buckets (<12, 12-18, 18-24, 24-30, 30+)
  - Push rate: ~3.5-3.9% (minor bonus — most of the gap is real model accuracy, not push mechanics)

BB-level evidence (Jan-Mar 2026, N=54 OVER, 34 UNDER):
  - whole_line OVER: 68.5% vs 66.5% half-line (+2pp, NOT significant — already selected by signals)
  - whole_line UNDER: 70.6% vs 58.3% half-line (+12.3pp, consistent with 5-season raw finding)

Mechanism (leading hypothesis): Sportsbooks use whole-number lines when they have LOWER
conviction about the exact line — either because:
  (a) It's an early-market line before sharp action has sharpened it to X.5, OR
  (b) The player's historical scoring distribution is bimodal (sits between two round numbers)
  making the book less confident in setting a fractional line.
When the book has lower conviction, our model's edge is more reliable — the book is
pricing a harder-to-model player in a less efficient way.

Regression-to-pushes argument (alternative): Whole-number lines are slightly weaker
in EV terms (push = money back, not a win), but with only 3.5-3.9% push rate, the push
economics are NOT a sufficient explanation for the +10-20pp gap.

Status: SHADOW (registered, tracked, EXCLUDED from real_sc via SHADOW_SIGNALS → zero pick
impact). Promote to UNDER_SIGNAL_WEIGHTS at season open after live N>=30 at HR>=62% in
2026-27 (conservative given the BB-level UNDER evidence; OVER needs N>=50 at HR>=70% given
BB-context evidence is weak). Also check overlap with existing edge and line-value signals.

Pre-registration: docs/08-projects/current/whole-line-precision/00-PREREGISTRATION.md
Detail: docs/09-handoff/2026-06-29-whole-line-precision-discovery.md
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class WholeLinePrecisionSignal(BaseSignal):
    tag = "whole_line_precision"
    description = (
        "Whole-number prop line — book set line at integer (no .5), "
        "model accuracy +10-20pp (76% vs 63% raw 5-season, shadow)"
    )

    CONFIDENCE_OVER = 0.60
    CONFIDENCE_UNDER = 0.65   # stronger BB-level evidence for UNDER

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        recommendation = prediction.get('recommendation')
        if recommendation not in ('OVER', 'UNDER'):
            return self._no_qualify()

        line = prediction.get('line_value') or prediction.get('current_points_line')
        if line is None:
            return self._no_qualify()

        line = float(line)

        # Whole-number gate: line must be an integer (no fractional part)
        if line != int(line):
            return self._no_qualify()

        confidence = self.CONFIDENCE_UNDER if recommendation == 'UNDER' else self.CONFIDENCE_OVER

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'line_value': int(line),
                'mechanism': 'whole_number_line_lower_book_conviction',
                'raw_5season_hr': 0.768,
                'bb_level_under_hr': 0.706,
                'bb_level_over_hr': 0.685,
                'status': 'shadow',
            },
        )
