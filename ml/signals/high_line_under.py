"""High-line UNDER signal — prop lines >= 25 systematically overpriced by market.

DISCOVERED via formal discovery gate (pre-registered, BH-FDR corrected, cross-season).

Evidence (5-season, N-large, from discovery framework):
  - line >= 25, UNDER: 59.9% HR, above breakeven 5/5 seasons (p=0.0007)
  - Additive over the high-line baseline: orthogonal to whole_line_precision

Mechanism: At high scoring lines (stars, 25+ pts/game), the market anchors to
reputation and consistently overprices the OVER. High lines have less sharp liquidity
and wider disagreement between books. Model edge at these lines tends to be more
reliable (same mechanism as whole_line_precision — book uncertainty).

Relationship to star_line_under:
  - star_line_under = line >= 25 + edge 3-7 (UNDER) — a strict subset of this signal
  - high_line_under = line >= 25 (UNDER, no edge gate) — the edge-ungated version
  - high_line_under is intended as the eventual REPLACEMENT for star_line_under
    (no artificial edge band restriction)
  - 2025-26 warning: star_line_under is 35.3% HR this season (N=17) — the line >= 25
    UNDER thesis is stressed in 2025-26. Watch high_line_under live HR carefully.
    Do NOT graduate if live HR < 58% or < 3/4 seasons pass breakeven.

Status: SHADOW (zero pick impact). Promote to UNDER_SIGNAL_WEIGHTS at weight 1.0
after live N>=30 at HR>=58% in 2026-27. Before graduating, stratify by edge band —
the discovery HR of 59.9% may be concentrated in a specific edge range.
If graduated: deprecate star_line_under (it's a subset with artificial edge constraints).

Detail: docs/09-handoff/2026-06-29-3-session-handoff.md (priority list, item 9)
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class HighLineUnderSignal(BaseSignal):
    tag = "high_line_under"
    description = (
        "UNDER with prop line >= 25 — market systematically overprices high-line stars "
        "(59.9% HR 5-season, edge-ungated superset of star_line_under, shadow)"
    )

    MIN_LINE = 25.0
    CONFIDENCE = 0.65

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        line = prediction.get('line_value') or prediction.get('current_points_line')
        if line is None:
            return self._no_qualify()

        if float(line) < self.MIN_LINE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'line_value': round(float(line), 1),
                'backtest_hr': 0.599,
                'overlap_note': 'superset_of_star_line_under',
                'status': 'shadow',
            },
        )
