# Session 483 Handoff — 2026-03-22

**Date:** 2026-03-22 (Sunday)
**Commits:** `2d11ac60` (guardrails), `SESSION_483_FINAL` (MLB + monitoring + docs)

---

## What Was Done This Session

### 1. March 8 Autopsy
- Root cause: `lgbm_vw015` flooded 9/16 picks into a TIGHT market (Vegas MAE 4.40)
- UNDER collapse: 7 losses from blowout_risk/starter_under signals in a scoring eruption
- 3 rescued OVER picks (edge 3.1-3.2, `sharp_book_lean_over`) all lost in tight market
- **The system had already built every guardrail — none were blocking**

### 2. 7 Guardrails Activated (`ml/signals/aggregator.py`, `regime_context.py`, `signal_health.py`)

| # | Change | Effect |
|---|--------|--------|
| 1 | `mae_gap_obs` → active when gap > 0.5 | Blocks OVER when model badly losing to Vegas |
| 2 | `regime_rescue_blocked` → active | Blocks OVER rescue in cautious/TIGHT regimes |
| 3 | `over_edge_floor_delta` → applied | Floor actually rises 5.0→6.0 when regime triggered |
| 4 | `vegas_mae_7d` added to regime_context | TIGHT market (MAE<4.5) auto-raises floor + disables rescue |
| 5 | OVER edge 7+ bypass `sc3_over_block` | Mirrors UNDER bypass (78.8% HR at edge 7+) |
| 6 | `home_under` → BASE_SIGNALS | 48% 30d HR removed from scoring + rescue |
| 7 | HOT gate: picks_7d>=5 AND hr_30d>=50% | Prevents N=1 flukes from getting 1.2x multiplier |

### 3. MLB Fixes
- `mlb-pitcher-props-validator-4hourly` scheduler: `4-10` → `3-10` (Opening Day is Mar 27)
- `mlb_phase5_to_phase6/main.py`: Slack alert when grading returns non-200 (closes silent-503 gap)

### 4. Fleet Cleanup
- 6 BLOCKED models hard-deactivated (audit trail cascaded)
- One model (`catboost_v12_noveg_train0109_0305`) had `status=active` while blocked — fixed
- Remaining 2 BLOCKED models kept for monitoring comparison

### 5. Market Monitoring Added to `signal_decay_monitor.py`
- `query_market_health()` function: queries `league_macro_daily` for regime + BB HR trend
- **TIGHT market alert**: 2+ consecutive days vegas_mae < 4.5 → `#nba-betting-signals`
- **Fleet BB HR alert**: 3+ consecutive days < 58%, N≥20 → `#nba-betting-signals`

---

## System State

### NBA Fleet (2 enabled models — BELOW MIN_ENABLED_MODELS=3)
| Model | State | HR 7d | Notes |
|-------|-------|-------|-------|
| `lgbm_v12_noveg_train0103_0227` | HEALTHY | 60.0% (N=20) | Primary |
| `lgbm_v12_noveg_train1215_0214` | HEALTHY | 60.0% (N=15) | avg_edge 1.34 — watch |

**CRITICAL:** Fleet is at 2 models, below the 3-model safety floor. Priority action:
retrain with `--train-end 2026-02-28` to rebuild the fleet.

### Market State
- Vegas MAE: 5.43 (NORMAL) — retrain gate condition NOT met (gate: MAE < 5.0 to retrain)
- New guardrails would have blocked March 8 picks entirely (MAE was 4.40 TIGHT that day)
- 30d HR = 50% (March 8 dominated); ex-March-8 = 57.4%; washes out ~April 7

---

## Immediate Next Steps

### Mar 23 (tomorrow)
- 10-game slate — first real pick volume test for new guardrails
- Verify both models still HEALTHY in `model_performance_daily`
- Check that vegas_mae stays above 4.5 (NORMAL) going in

### Mar 24
- Run `./bin/mlb-season-resume.sh` (mlb-resume-reminder fires 8 AM ET)
- Pitcher-props-validator now fires hourly in March (schedule fixed)

### Mar 25 — 12-game slate (biggest NBA day)
- lgbm_1215_0214 decision: deactivate if HR < 52.4% BUT only if there's a replacement
- Currently at 2 models — cannot deactivate without dropping below safety floor

### RETRAIN (do when ready)
```bash
# Unpause retrain with Feb 28 training cutoff
./bin/retrain.sh --all --enable --train-end 2026-02-28
# Or trigger CF directly:
gcloud scheduler jobs run weekly-retrain --location=us-west2 \
  --project=nba-props-platform
```
Note: The retrain gate (Vegas MAE < 5.0) is backwards — MAE 5.43 is LOOSE market,
best time to train. The gate was paused incorrectly. See Session 483 learnings.

### Mar 27 — MLB Opening Day
1. Verify `mlb_predictions.pitcher_strikeout_predictions` has rows
2. Check orchestrator payload has `write_to_bigquery: true` (agent found possible bug)
3. Grading service now alerts on non-200 (just deployed)

---

## Pending (NOT done this session)
- [ ] Weekly-retrain CF unpause with --train-end 2026-02-28 (needs explicit trigger)
- [ ] Verify MLB orchestrator writes predictions (check if payload has write_to_bigquery)
- [ ] Enable fresh models after retrain (requires governance gates passing)
- [ ] Monitoring: single-model dominance alert (>40% from one model) — design done, not coded

---

## Key Constraints (unchanged)
- `catboost_v9_low_vegas`: **DO NOT RE-ENABLE** (DEGRADING, 40+ days stale)
- OVER floor: **5.0** (now regime-adaptive: rises to 6.0 in TIGHT markets automatically)
- `weekly-retrain` CF: currently paused — the gate logic is backwards per Session 483 analysis

---

## New Gotchas Learned

**Observation filters accumulate technical debt.** Every filter added as "observation only"
needs a scheduled promotion. Without that, the system logs that it would have prevented
a disaster without ever preventing it. See CLAUDE.md common issues.

**`catboost_v12_noveg_train0109_0305` had status=active while blocked.** The deactivation
cascade fixed it. Always run `bin/deactivate_model.py` for confirmed-dead models, not just
registry updates.

**MLB pitcher-props-validator was April-only.** Season starts March 27. Fixed to March-October.
