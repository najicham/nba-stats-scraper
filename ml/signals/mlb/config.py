"""Shared MLB best-bets configuration constants.

Single source of truth for regime + threshold values used in multiple
modules. Centralized 2026-05-17 after a 7-agent review found that
`TIGHT_VEGAS_MAE_THRESHOLD` had drifted between `best_bets_exporter.py`
(1.5, lowered to end the 5/14-5/17 pick drought) and
`ml/analysis/mlb_league_macro.py` (still 1.7), so `league_macro_daily`
was labeling rows TIGHT that the exporter then treated as NORMAL.

Any future cross-module regime/cap value should live here. Single-module
values (like `MAX_PICKS_PER_DAY`) can stay where they are.
"""

# Vegas-MAE threshold for the TIGHT market regime.
# Lowered from 1.7 → 1.5 on 2026-05-17. At 1.7 the gate caught the
# bottom 20% of MLB days (p25 = 1.71, p50 = 1.80), causing multi-day
# pick droughts whenever combined with the +0.5K regime floor delta
# and the MAX_EDGE=1.25 cap. 1.5 catches ~0.5% of days — true anomalies
# only. See `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/`
# and the 7-agent analysis in this session's handoff.
TIGHT_VEGAS_MAE_THRESHOLD = 1.5

# When TIGHT fires, raise the OVER edge floor by this amount.
# See `ml/signals/mlb/best_bets_exporter.py:_get_regime_context`.
TIGHT_OVER_FLOOR_DELTA = 0.5
