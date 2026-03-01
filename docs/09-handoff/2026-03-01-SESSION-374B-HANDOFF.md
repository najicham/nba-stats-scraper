# Session 374b Handoff — Strategy Analysis & Implementation

**Date:** 2026-03-01 (Feb 28 evening)
**Commits:** `61fff46a`, `9058bff3`, `eaf1b197`
**Status:** Deployed, coordinator manual deploy in progress

## What Was Done

### Research Phase (4 parallel strategy agents)
Ran 27+ BQ queries across 4 strategy dimensions: signal combos, filter health, OVER recovery, retraining opportunities. Key discovery: **Feature 41 (spread_magnitude) has been ALL ZEROS since November** — a 4-month data bug.

### Implementation (2 commits)

**Commit `eaf1b197` — Session 374 Implementation:**
1. **star_teammates_out bug fix** — Season avg fallback for long-term injuries (Giannis, Tatum, Morant missed by 10-day window). 42% of season-identified stars were invisible.
2. **SC=3 edge restriction** — Blocks SC=3 picks with edge < 7.0 (48.4% HR N=31 vs 85.7% at edge 7+)
3. **3 new signals** — fast_pace_over (81.5%), volatile_scoring_over (81.5%), low_line_over (78.1%)

**Commit `61fff46a` — Session 374b Strategy Implementation:**
1. **Feature 41 spread fix** — `betting_data.py` spread query took median of BOTH sides (+4/-4 = 0). Added `AND (outcome_point <= 0 OR @market_key != 'spreads')` to opening AND current queries.
2. **SC=3 restriction OVER-only** — SC=3 UNDER at edge 3-7 = 62.5% HR (profitable, keep). SC=3 OVER = 33.3% (block).
3. **OVER + line dropped filter** — 39.1% HR Feb (N=23). Blocks OVER + prop_line_delta <= -2.0. Symmetric to existing UNDER filter.
4. **Opponent depleted UNDER filter** — UNDER + 3+ opponent stars out = 44.4% HR (N=207). Separate query in supplemental_data.py (team_stars_out dict).
5. **prop_line_drop_over DISABLED** — Conceptually backward. Line drops are BEARISH for OVER, not bullish. 53.3% Feb HR. Was inflating SC on losing picks.
6. **line_rising_over signal** — OVER + line went UP = 96.6% HR (29/30). Feb-resilient at 100% (5/5). Replaces prop_line_drop_over.

### Backfill Validation
- v374b: 108 picks, 96 graded: 60W-36L = 62.5% HR, +$2,040
- line_dropped_over: blocked 22 picks
- sc3_edge_floor (OVER-only): 37 blocks
- opponent_depleted_under: 1 block

## What Still Needs Doing (Priority Order)

### P1: Feature Store Backfill for Spread Fix
The spread fix only affects NEW data. Historical Feature 41/42 values are still 0. Need to:
1. Recompute Feature 41 (spread_magnitude) and Feature 42 (implied_team_total) for all historical dates
2. This requires running the Phase 4 precompute pipeline with the fixed betting_data.py
3. After backfill, retrain to let model learn from actual spread data

### P2: Urgent Retrain
All models are BLOCKED/degrading. Production model at 51.8% HR latest week.
- **Window:** 49 days (Jan 10 - Feb 27), V12_NOVEG, vw015
- **After spread backfill** so model can learn from actual spread data
- Command: `PYTHONPATH=. python ml/experiments/quick_retrain.py --feature-set v12_noveg --category-weight vegas=0.15 --training-start 2026-01-10 --training-end 2026-02-27`

### P3: Monitor New Signals in Production
Session 374 signals (fast_pace_over, volatile_scoring_over, low_line_over) + Session 374b (line_rising_over) should fire starting with next prediction run. Verify with:
```sql
SELECT signal_name, COUNT(*) as fires
FROM `nba-props-platform.nba_predictions.pick_signal_tags`,
UNNEST(signal_tags) as signal_name
WHERE game_date = CURRENT_DATE()
GROUP BY signal_name ORDER BY fires DESC
```

### P4: Fleet Triage
Models to kill (from strategy analysis):
- `catboost_v12_q43_train1225_0205` (33.3% edge 5+ HR)
- `catboost_v12_noveg_q57_train1225_0209` (25.0% HR N=4)
- `catboost_v12_train1225_0205` (40.9% HR N=22)

Models to watch:
- `catboost_v9_low_vegas_train0106_0205` — best UNDER model (59.6% HR N=47)
- `catboost_v9_50f_noveg_train1225_0205` — 61.5% HR (N=13), needs more data

### P5: Experiment Ideas (Not Previously Tried)
1. **Direction-specific models** — Separate OVER/UNDER regression models
2. **Dynamic edge threshold by model age** — `edge >= 3 + 0.5 * weeks_since_training`
3. **Post-All-Star-Break regime training** — Train exclusively on post-ASB data
4. **Ensemble of time windows** — Average predictions from 35d/49d/63d models
5. **Line-level segmentation** — Different edge floors for low (<15) vs high (25+) lines

## Key Strategy Findings

### OVER Collapse Root Causes
| Factor | Jan HR | Feb HR |
|--------|--------|--------|
| Line dropped OVER | 50.0% | 39.1% |
| Role/Starter tier | 79.0% | 35.0% |
| HOME venue | 84.2% | 43.8% |
| SC=3 OVER | 50.0% | 28.6% |

### Signal Insights
- combo_he_ms + rest_advantage_2d = 86.7% HR (13-2, N=15) — strongest triple
- rest_advantage_2d WITHOUT combo = 44.4% Feb (declining rapidly)
- book_disagreement broke today: 1-2 on low-line picks from shadow models
- v12_retrained OVER is 17-0 — extraordinary
- usage_spike_score = 0.0 for ALL predictions — completely dead feature

### Deployment Status
- All Cloud Builds succeeded from push
- prediction-coordinator manual deploy in progress
- Only `validation-runner` has minor drift (docs-only, not critical)
- Algorithm version: `v374b_spread_fix_over_filters_signals`

## Files Changed
```
data_processors/analytics/upcoming_player_game_context/betting_data.py  — spread fix
data_processors/analytics/upcoming_player_game_context/team_context.py  — star bug fix (3 functions)
ml/signals/aggregator.py        — 3 new filters, SC=3 OVER-only, version bump
ml/signals/supplemental_data.py — opponent_stars_out query, opponent_pace, points_std
ml/signals/line_rising_over.py  — new signal (replaces prop_line_drop_over)
ml/signals/fast_pace_over.py    — new signal
ml/signals/volatile_scoring_over.py — new signal
ml/signals/low_line_over.py     — new signal
ml/signals/registry.py          — register 4 signals, disable prop_line_drop_over
ml/signals/pick_angle_builder.py — angle templates
CLAUDE.md                       — full docs update
```
