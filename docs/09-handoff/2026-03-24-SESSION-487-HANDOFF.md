# Session 487 Handoff — 2026-03-24

**Latest commit:** `687a3a88` — fix: demote volatile_scoring_over to SHADOW_SIGNALS
**Branch:** main (auto-deployed)

---

## System State: RECOVERING

### NBA Fleet (4 enabled models)
| Model | Framework | Train Window | State | Notes |
|-------|-----------|-------------|-------|-------|
| `lgbm_v12_noveg_train0103_0227` | LGBM | Jan 3 – Feb 27 | HEALTHY 59.5% 7d | Anchor model |
| `lgbm_v12_noveg_train0103_0228` | LGBM | Jan 3 – Feb 28 | BLOCKED 50.0% 7d | Monitor — 1 day BLOCKED |
| `lgbm_v12_noveg_train1215_0214` | LGBM | Dec 15 – Feb 14 | BLOCKED 45.7% 7d | Monitor — decay CF may auto-disable |
| `catboost_v12_noveg_train0118_0315` | CatBoost | Jan 18 – Mar 15 | active (re-enabled) | HEALTHY 7 days before disable; framework diversity |

**`catboost_v12_noveg_train0118_0315` first real predictions: Mar 25.** Watch avg_abs_diff and whether it unlocks any cross-model signals.

---

## What Was Done This Session (487)

### 1. 9-Agent Review Panel (6 analysis + 3 review)

**Six analysis agents** covered: pick drought root cause, filter CF data, signal shadow status, UNDER filter stack, Monday retrain planning, holistic gaps.

**Three review agents** (2 Opus, 1 Sonnet) then validated the action plan before execution.

**Key reversals from original analysis:**
- `high_spread_over_would_block` demotion: **REJECTED** — "87.5% CF HR" was cherry-picked from last 8 picks. All-time is 50.0% (7-7, N=14). Filter has only existed 19 days.
- Pick drought cause: **Not LGBM conservatism** — all properly-trained models converge to avg_abs_diff 1.0-1.8. Real cause: fleet diversity collapse (5 LGBM clones at r≥0.95, no cross-model signals).
- `cap_to_last_loose_market_date()` on Mar 30: **DOES fire** — CF's `train_end = Mar 29`, eval reserves 14 days → actual_train_end = Mar 15, only 2 days after last TIGHT (Mar 13) → 2 < 7 → cap fires → training Jan 10–Mar 7, zero TIGHT contamination.
- `mae_gap_obs` promotion: **REJECTED** — holistic agent's "34.2% CF HR, N=38" was wrong (actual: 18.2%, N=22, only 7 days of data). Would incorrectly block UNDER picks.

### 2. Model Fleet Cleanup

**Deactivated (2 models):**
- `lgbm_v12_noveg_train1001_0316` — 167-day window (Oct 1–Mar 16), trained through TIGHT period, avg_abs_diff 1.43 (worse than existing fleet), enabled only hours before deactivation. No picks affected (0 BB picks).
- `catboost_v12_noveg_train0103_0228` — re-enabled at 05:25 UTC for unknown reasons, avg_abs_diff 1.13 (worst in fleet), zero edge 5+ predictions. No picks affected.

**Re-enabled (1 model):**
- `catboost_v12_noveg_train0118_0315` — was HEALTHY 7 consecutive days (60–71.4% 7d HR) before decay CF disabled it. Jan 18–Mar 15 training window (optimal 56 days, zero TIGHT contamination). Only CatBoost in fleet — provides framework diversity that LGBM clones cannot. Low avg_abs_diff (0.95–1.12) means it cannot dominate the pipeline but can unlock cross-model signals.

**Worker cache refreshed** → new revision `prediction-worker-00430-hzk` live.

### 3. `volatile_scoring_over` → SHADOW_SIGNALS (commit `687a3a88`)

Added `'volatile_scoring_over'` to `SHADOW_SIGNALS` frozenset in `ml/signals/aggregator.py` (line 124).

**Why:** Signal was NOT in SHADOW_SIGNALS, counting toward `real_sc`, with 20% BB HR (1 win, 4 losses, N=5). Was helping picks pass the real signal count gate that they should not pass. Moving to shadow:
- Stops it from inflating `real_sc`
- Stops it from contributing 0.5x weight to composite score
- Keeps data accumulating for future re-evaluation
- Does NOT remove it from signal firing or pick tagging

Auto-deployed to all services (3 builds SUCCESS).

---

## Pick Drought Root Cause Analysis

**The system generated 2 picks in 7 days (Mar 18–24) across 40+ games.** On Mar 23 (10-game slate): 645 predictions, 57 at edge 3+, 0 published.

**Root cause: fleet diversity collapse, not LGBM conservatism.**

All properly-trained models (CatBoost, LGBM, XGBoost) converge to avg_abs_diff 1.0–1.8. The old high-edge models (catboost_v8 at 2.92) were noisy and had sub-50% accuracy at edge 5+ — generating noise, not signal. The current fleet is 5 LGBM clones at r≥0.95 correlation. No model disagreement → `book_disagreement`, `combo_3way`, `combo_he_ms` signals cannot fire → no `real_sc` → `signal_density` and `under_low_rsc` block everything.

**The CatBoost re-enablement is the partial fix.** Even at low avg_abs_diff, a different framework predicts differently enough to potentially fire cross-model signals. Full fix requires Monday's retrain to produce models with higher avg_abs_diff.

**Funnel on Mar 24 (4-game slate):**
- 17 candidates entered the pipeline
- 14 UNDER candidates: correctly blocked by `signal_density` (8), `flat_trend_under_obs` (6), `line_jumped_under_obs` (6), `blowout_risk_under_block_obs` (5), `tanking_risk_obs` (4)
- 3 OVER candidates: blocked by `over_edge_floor` (1), `high_spread_over_would_block` (1), `blacklist`+obs (1)
- 0 published

---

## Monday Retrain (Mar 30, 5 AM ET) — Corrected Plan

The original plan ("cap won't fire, 11% TIGHT contamination") was wrong.

**Actual behavior:**
- CF fires Mar 30 → `train_end = Mar 29` → eval window = Mar 16–29 → `actual_train_end = Mar 15`
- Mar 15 is 2 days after last TIGHT day (Mar 13) → 2 < 7 recovery_days → **cap fires**
- Cap sets `train_end = Mar 7` (day before TIGHT started Mar 8)
- Training window: **Jan 10 – Mar 7** (56 days, **zero TIGHT contamination**)
- Eval window: Mar 16–29 (~500 edge 3+ records — well above N=15 gate)

Both families will be retrained: `lgbm_v12_noveg_mae` and `v12_noveg_mae` (CatBoost). Expected IDs: `lgbm_v12_noveg_train0110_0307`, `catboost_v12_noveg_train0110_0307`.

The catboost_v9 eval bug in `quick_retrain.py` does NOT affect the CF — the CF has its own `load_eval_data()` function and does not call `quick_retrain.py`.

**After Monday's retrain:** Check avg_abs_diff of new models on first production day. If still ≤1.5, pick drought is structural and requires architectural investigation (not just window changes).

---

## New Gotchas (Session 487)

**`high_spread_over_would_block` all-time CF HR is 50%, not 87.5%.** The 87.5% figure was from the last 8 of 14 graded picks — the filter had a 6-1 loss streak in its first week (Mar 7–8) followed by a winning streak (Mar 9–23). All-time 50.0% (7-7, N=14). The filter has been flipped 3 times in 19 days already — do NOT demote again without 30+ graded picks.

**Fleet diversity collapse is the real pick drought cause.** Adding more LGBM models trained on the same data does not help — they're all r≥0.95 clones. Need at least one CatBoost or XGBoost in the fleet generating different predictions to unlock combo signals.

**`volatile_scoring_over` was in combo_registry.py as PRODUCTION.** Moving it to SHADOW_SIGNALS in `aggregator.py` is sufficient — combos still fire but the signal no longer counts toward `real_sc` or composite score. No change to combo_registry needed.

**`mae_gap_obs` should NOT be promoted yet.** The holistic agent's claim of "34.2% CF HR, N=38" was wrong — actual data shows 18.2% CF HR (N=22, only 7 days). The graduated approach (observe at 0.15, block OVER at 0.5) is correct. Revisit after 30+ days if CF HR stays below 40%.

**`catboost_v12_noveg_train0118_0315` re-enabled with caveat.** Its avg_abs_diff is 0.95–1.12 — very low. It will rarely produce edge 5+ picks independently. Its value is framework diversity for cross-model signals. If it generates 0 picks over 5 days, reassess.

**`usage_surge_over` prediction-level HR ≠ BB-level HR.** Signal_health_daily shows 68.2% HR 30d (N=22). Actual BB-level: 40% (N=5). Do not graduate. The aggregator comment at line 95 says "75% HR (N=8)" — stale, should be updated to "40% HR (N=5) current BB data."

---

## Pending Items

- [ ] **Mar 25** — Monitor catboost_v12_noveg_train0118_0315 avg_abs_diff and whether it unlocks combo signals
- [ ] **Mar 25** — Decay CF may auto-disable `lgbm_v12_noveg_train1215_0214` (BLOCKED, days_below_alert=1). Monitor fleet count — must stay ≥3.
- [ ] **Mar 27** — MLB Opening Day verification (queries in Session 486 handoff)
- [ ] **Mar 28** — MLB `mlb_league_macro.py` backfill after first games grade
- [ ] **Mar 30** — Weekly retrain CF fires 5 AM ET. Expected: `lgbm_v12_noveg_train0110_0307`, `catboost_v12_noveg_train0110_0307`. Watch avg_abs_diff on first production day.
- [ ] **Post-retrain** — Clean up BLOCKED models if still enabled after retrain
- [ ] **Observation filter debt** — `thin_slate_obs`, `neg_pm_streak_obs` showed 60–62% CF HR since January in holistic agent. Agents disagreed (UNDER filter agent found no issues in 30-day window). Needs dedicated investigation with full-season data.
- [ ] **Apr 14** — Playoffs shadow mode
- [ ] **Ongoing** — `usage_surge_over` graduation watch (N=5 at 40% BB HR — do not graduate until N≥30 at ≥60%)

---

## Key Active Constraints

- **OVER edge floor: 5.0** (auto-rises to 6.0 when vegas_mae < 4.5 TIGHT)
- **`high_spread_over_would_block`: KEEP ACTIVE** — all-time CF HR 50% (7-7, N=14). Do not demote without 30+ graded picks showing CF HR ≥55%
- **`projection_consensus_over`: DO NOT GRADUATE** — BB-level HR 1-8 (12.5%), still catastrophic
- **`usage_surge_over`: DO NOT GRADUATE** — BB-level HR 40% (N=5), not the prediction-level 68%
- **`mae_gap_obs`: KEEP AS OBSERVATION** — revisit at N≥30 graded with CF HR ≤40% sustained 7+ days
- **Fleet minimum: 3 enabled models** — currently 4 (above floor)

---

## Session 487 Commits (1 total)
```
687a3a88 fix: demote volatile_scoring_over to SHADOW_SIGNALS
```

### Registry changes (BQ-only, no commit):
- `catboost_v12_noveg_train0103_0228`: enabled=FALSE (deactivated)
- `lgbm_v12_noveg_train1001_0316`: enabled=FALSE (deactivated)
- `catboost_v12_noveg_train0118_0315`: enabled=TRUE (re-enabled for diversity)
