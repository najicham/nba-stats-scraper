# Session 347 Handoff — Health Gate Removal

**Date:** 2026-02-26
**Status:** DEPLOYED. Best bets now flow through even when model HR < breakeven.

---

## What Changed

### Health Gate Removed from Signal Best Bets Exporter

**Commit:** `59cc22c1` — `fix: remove health gate that blocked profitable best bets picks`

**File:** `data_processors/publishing/signal_best_bets_exporter.py`

The health gate in the signal best bets exporter blocked ALL picks when the champion model's raw 7-day hit rate on edge 3+ predictions dropped below 52.4% (breakeven at -110 odds). This was restored in Session 323 based on a Session 322 replay study.

**Why it was removed:**

The gate measured the wrong thing. It checked single-model raw HR to block multi-model filtered output — a category error. The actual signal best bets (after 10+ negative filters) were performing well:

| Metric | HR | N |
|--------|-----|---|
| Signal best bets (Jan 28 – Feb 26) | **62.8%** | 27-16 |
| Signal best bets (Feb 19+) | **66.7%** | 8-4 |
| Raw model HR (what gate used) | 50.0% | — |
| Raw edge 5+ all models | 49.8% | 207 |

The filter pipeline (player blacklist, model-direction affinity, bench-under block, edge floor, prop line volatility, 2-signal minimum, etc.) was converting a 50% raw model into 63%+ filtered picks. The gate was blocking profitable output.

**Session 322 replay invalidity:** The replay was conducted on a single-model V9 pipeline before:
- Multi-model candidate generation (Session 307)
- Model-direction affinity blocking (Session 330/343)
- Player blacklist (Session 284)
- Prop line volatility filters (Session 294/306)

The replay's `BestBetsAggregator` was instantiated without `player_blacklist`, `model_direction_blocks`, or `model_direction_affinity_stats` — it tested a pipeline that no longer exists.

**What was kept:**
- Health status computation (`blocked`/`watch`/`healthy`) — still in JSON output for transparency
- `model_health` field in JSON — consumers can see model state
- `health_gate_active: false` field added to JSON — signals the gate is off
- Informational `logger.info()` when model HR < breakeven (was `logger.warning()`)

**What was removed:**
- The early return block (lines 141-193) that exported 0 picks when `health_status == 'blocked'`
- 56 lines of code deleted, 16 added (net -40 lines)

### Immediate Result

First export after deployment produced **5 picks for Feb 26** (10-game slate):

| # | Player | Pick | Line | Edge | Model |
|---|--------|------|------|------|-------|
| 1 | Kawhi Leonard | UNDER | 29.5 | 7.7 | v12_noveg_q43 |
| 2 | Joel Embiid | UNDER | 27.5 | 6.7 | v12_noveg_q43 |
| 3 | Luka Doncic | UNDER | 30.5 | 5.9 | v12_noveg_q43 |
| 4 | Anthony Edwards | UNDER | 28.5 | 5.5 | v12_noveg_q43 |
| 5 | Jalen Green | UNDER | 20.5 | 5.1 | v9_low_vegas |

100 candidates → 5 passed filters. Rejections: 92 edge floor, 2 model-direction affinity, 1 line-dropped-under. 4 of 5 are ULTRA bets.

---

## Agent Review Process

4 independent agents (2 Sonnet, 2 Opus) reviewed the decision with identical context:

| Agent | Vote | Key Argument |
|-------|------|--------------|
| Sonnet A | Remove gate | "Category error" — measures unfiltered to block filtered output |
| Sonnet B | Lower to 45% | Bridge until grading fixed, wants safety net for catastrophic collapse |
| Opus A | Remove gate | Session 322 replay has 5 flaws; tests a pipeline that no longer exists |
| Opus B | Remove gate | Filter pipeline empirically works; gate prevents 0-pick product failure |

**3-1 consensus: remove entirely.** Dissent (Sonnet B) acknowledged the metric is wrong but preferred a lower threshold as a bridge.

---

### AWAY Noveg Negative Filter Added

**File:** `ml/signals/aggregator.py`

Investigation 3 found that v12_noveg models (q43, q45, q55, q55_tw, q57) hit **57-59% at HOME but only 43-44% AWAY** — a +15pp gap with N=40+ on each side. This is structural to the no-vegas feature set.

**Filter logic:** Block any v12_noveg prediction where `is_home = False`. Uses `get_affinity_group()` to identify noveg models (covers all current and future v12_noveg variants).

**Position in filter chain:** After model-direction affinity block, before familiar matchup check. Both are model-family-specific filters.

**Impact:** Approximately half of v12_noveg best bets candidates are AWAY games. This filter removes the ~44% HR AWAY picks, keeping only the ~58% HR HOME picks. Net effect: fewer noveg picks but higher quality.

---

## Known Issue: Broken Best Bets Grading

`signal_best_bets_picks` table has `prediction_correct = NULL` for most rows (only 7 of 49 picks since Jan 28 are graded). This means:

1. We cannot automatically track best bets performance
2. The 62.8% HR figure was computed by manually joining with `prediction_accuracy`
3. Future best-bets-based gating (Option 2) requires fixing grading first

**Next session should investigate:** Why is `prediction_correct` not being backfilled in `signal_best_bets_picks`? The data exists in `prediction_accuracy` — the grading service just isn't writing it back to this table.

---

## Deployment Status

All services up to date as of this session:
- `phase6-export`: deployed with `59cc22c` (health gate removal)
- `live-export`: deployed with `59cc22c`
- `post-grading-export`: deployed with `59cc22c`
- `prediction-worker`: deployed with `dd66d113` (Session 346)
- All other services: current

---

## Validation Findings (Pre-Game Check)

### Pipeline Health
- **10 games scheduled** for Feb 26
- **117 predictions per model** across all 10 games (6 main models producing)
- **Feature quality:** 67.2% quality-ready (117/174 players), 0 red alerts
- **Deployment drift:** All services up to date

### Model State (Unchanged — System-Wide Crisis)
All models BLOCKED or DEGRADING:
- `catboost_v12` (champion): 47.6-50.0% 7d HR
- `catboost_v12_noveg_q43_train0104_0215`: 18.5% 7d HR (but sourcing winning best bets)
- `catboost_v9`: 45.0% 7d HR
- `catboost_v9_low_vegas_train0106_0205`: 51.8-53.7% 7d HR (closest to healthy)

### Non-Critical Errors
- `zone_matchup_v1` feature errors for cobywhite, clintcapela, dorianfinneysmith (secondary system)
- `circuit_breaker_state` concurrent update (transient BQ error)
- Unknown `low_vegas_*` subset IDs (cosmetic warning)

### Shadow Model Coverage Gap
4 older shadow models (`*_train1225_0209`) only produced 6 predictions vs 117 for main models. These are from the Dec 25 – Feb 9 training window and may not be loading the full player list.

---

## Next Session Priorities

### Priority 0: Fix Best Bets Grading
- Investigate why `signal_best_bets_picks.prediction_correct` is NULL for most rows
- The grading service writes to `prediction_accuracy` but doesn't backfill to `signal_best_bets_picks`
- Consider adding a post-grading job that joins `prediction_accuracy` actuals into `signal_best_bets_picks`
- **This is critical for monitoring** — without it we can't track best bets performance programmatically

### Priority 1: Monitor Tonight's Best Bets Performance
- 5 picks exported for Feb 26 — first picks since health gate removal
- Track results tomorrow morning: did the filtered picks win?
- Compare against what the health gate would have blocked (all 5)

### Priority 2: Shadow Model Investigation
- `*_train1225_0209` models only producing 6/117 predictions — investigate why
- These are the Session 343-344 shadow models (q55_tw, q57, q55, v9_low_vegas old) that were the best performers

### Priority 3: CLAUDE.md Updates
- Update MODEL section: note health gate removed in Session 347
- Update SIGNALS section: `model_health` signal is informational only (no gate)
- Update dead ends: add "health gate on raw model HR" to dead ends list

### Priority 4: Monitor AWAY Noveg Filter Impact
- Track how many v12_noveg AWAY picks are blocked in daily filter summaries
- Compare remaining HOME-only noveg picks against pre-filter performance
- If too aggressive (blocking good picks), consider limiting to AWAY + UNDER only

---

## Key Files

| File | Change |
|------|--------|
| `data_processors/publishing/signal_best_bets_exporter.py` | Health gate early return removed |
| `ml/signals/aggregator.py` | AWAY noveg negative filter added |
| `ml/signals/model_health.py` | No change (already informational since Session 270) |
| `ml/analysis/steering_replay.py` | No change (has `--with-health-gate` toggle, off by default) |
