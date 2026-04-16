---
name: Session 533 — NBA playoffs hold + edge 5+ architecture finding
description: NBA playoffs started April 15 2026, all models BLOCKED, auto-halt active. Edge 5+ models profitable despite BLOCKED overall. usage_surge_over status unclear.
type: project
---

## NBA Playoffs — Do Not Retrain

NBA playoffs started 2026-04-15. All models BLOCKED, edge-based auto-halt active (avg edge ~4.0, below 5.0 floor). 0 picks since ~March 28.

Season final record: **415-235 (63.8%)**. System correctly halted before late-March collapse (Mar 46.7%, Apr ~50%).

**Why:** Playoff data contaminates regular-season training set. Models not calibrated for playoffs.
**How to apply:** Do NOT retrain or force picks until 2026-27 regular season (October 2026). Let the halt stand.

---

## Edge 5+ Architecture Finding (Off-Season Priority)

3 models hit 60% HR at edge 5+ while BLOCKED overall (14d window, April 2026):
- `catboost_v12_noveg_mq_train0206_0402`: 60% edge5+ (N=20), 26.2% overall → **+33.8pp premium**
- `catboost_v12_noveg_train1227_0221`: 60% edge5+ (N=10), 47.2% overall → +12.8pp premium
- `catboost_v12_noveg_train0126_0323`: 60% edge5+ (N=5)

**Why:** Low-edge predictions (edge 1-3) drag down overall HR → trigger BLOCKED state → silence the high-edge picks that were actually working.
**How to apply:** Off-season architecture change — raise minimum prediction output threshold to edge ≥ 3.0 (currently models emit all predictions). Would reduce HR denominator and keep good models out of BLOCKED. Do not act during playoffs.

---

## usage_surge_over Status Unclear

Was reverted to SHADOW in Session 506 (COLD 33.3% HR at N=15). Now showing HOT in `signal_health_daily` at 83.3% (N=6, 7d).

**Why:** Unclear if re-promoted or if shadow signal appearances are being tracked in signal_health.
**How to apply:** Verify with `grep -n "usage_surge_over" ml/signals/aggregator.py`. If in ACTIVE_SIGNALS and winning at 83.3%, may be legitimately HOT. If in SHADOW_SIGNALS, no action (just informational tracking).

---

## MLB Status (April 2026)

- Model HR 7d: 56.6%, BB HR 7d: 100% (N=3 small sample)
- Vegas MAE 7d NULL in league_macro — not a bug, early season, insufficient graded data
- Session 524 April-training bias fix deployed, working
- Next frontend work: Strike Zone Heartbeat (Project B, needs backend `strikeout_locations` exporter)
