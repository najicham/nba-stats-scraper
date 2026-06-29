"""National-TV / primetime high-line UNDER signal — featured scorers underperform inflated
marquee-game lines.

DISCOVERED 2026-06-28 (narrative-proxies Phase 1). Pre-registered as a national-TV OVER trigger
("stars elevate on the big stage"); it FAILED that direction (45.4% OVER) and inverted cleanly into a
durable UNDER edge. Triaged as a post-hoc finding → SHADOW pending live 2026-27 confirmation.

5-season standalone evidence (player-game vs prop line, 2021-22…2025-26, breakeven 52.4%):
  - (has_national_tv OR is_primetime) AND line>=22 → UNDER ≈ 54.7% (N≈1,951), above breakeven 5/5 seasons.
  - ADDITIVE, not the high-line effect in disguise: NON-national-TV line>=20 UNDER = 52.0% (2/5 seasons);
    national-TV & line<20 UNDER = 51.6%; the CONJUNCTION (TV AND high line) carries the +2.6pp lift.
  - Robust across line thresholds (18→25: 53.4-54.7%) and both TV definitions (national_tv & primetime).
  - 2024-25 is the weakest season (~50-52.6%) but still at/above breakeven except line>=25.

Mechanism (market mis-weighting story): recreational money concentrates on stars to go OVER in
marquee/primetime games ("watch X drop 40 on national TV"), inflating featured-scorer lines, while
marquee games trend toward tougher defense / slower grind-it-out pace → UNDER value on the high line.
This is an UNDER signal — the engine's structurally favored side (unconditional OVER-vs-line ≈ 48%).

Status: SHADOW (registered + tracked, EXCLUDED from real_sc via SHADOW_SIGNALS, NOT in
UNDER_SIGNAL_WEIGHTS → zero pick impact). Promote to UNDER_SIGNAL_WEIGHTS at season open with sign-off
once it accrues N>=30 BB-level picks at HR>=55% in live 2026-27 (clear of the 53.5% real breakeven).
Before weighting, check overlap with star_line_under / high-line UNDER (additive in backtest; confirm
live it is not redundant with what already fires).

Detail: docs/08-projects/current/narrative-proxies-discovery/01-FINDINGS.md.
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class NationalTvUnderSignal(BaseSignal):
    tag = "national_tv_under"
    description = ("National-TV/primetime high-line UNDER — featured scorers underperform inflated "
                   "marquee-game lines (54.7% HR 5-season, shadow)")

    MIN_LINE = 22.0          # the most consistent threshold in backtest (5/5 seasons)
    CONFIDENCE_BASE = 0.55   # ~ the 5-season HR

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Marquee-game gate: national TV OR primetime. Flags plumbed into the prediction dict from
        # nba_raw.nbac_schedule by supplemental_data.query_predictions_with_supplements.
        national_tv = bool(prediction.get('has_national_tv'))
        primetime = bool(prediction.get('is_primetime'))
        if not (national_tv or primetime):
            return self._no_qualify()

        # High-line gate (featured scorer)
        line = prediction.get('line_value') or prediction.get('current_points_line')
        if line is None:
            return self._no_qualify()
        line = float(line)
        if line < self.MIN_LINE:
            return self._no_qualify()

        # Confidence scales modestly with line height (higher line = stronger overpricing).
        confidence = min(0.65, self.CONFIDENCE_BASE + (line - self.MIN_LINE) * 0.01)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'line_value': round(line, 1),
                'has_national_tv': national_tv,
                'is_primetime': primetime,
                'backtest_hr_5season': 0.547,
                'backtest_n': 1951,
                'status': 'shadow',
                'signal_mechanism': 'marquee-game star overpricing → UNDER (5-season validated)',
            },
        )
