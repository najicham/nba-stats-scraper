# STEP 4 (gated re-run) + STEP 3 validation — RESULT

**Date:** 2026-06-21
**Status:** STEP 4 core DONE (regime+health gating sized). STEP 3 floor empirically validated in-sim.
**Nothing deployed.** Eval-only, single model (`wf_sim_v12noveg`), 2025-26, on the leak-clean WF cache.

## What was run
3-way on the INC-4 BB-injection harness (`bb_injection_run.py` → `simulate_date` → real aggregator),
grading against the same WF cache `correct`:
1. **UNGATED** = the INC-4 baseline (no `signal_health`/`regime_context`; HSE floor off). 208 picks.
2. **GATED** = STEP 4: wired `get_signal_health_summary` + `get_regime_context` into `simulate_date`
   (`bin/simulate_best_bets.py`), production-history-derived, point-in-time safe. HSE floor off.
   (Full-season = a through-Mar7 run + a Mar8–Apr12 tail; the first run hit a wall-clock cap.)
3. **GATED+FLOOR (STEP 3)** = same + `HSE_RESCUE_FLOOR_ENABLED=true` (line≥18 AND edge≥4 to bypass).

`feature_quality_score` stayed at the scratch 100.0 for all three (the optional real-quality join,
INC-4 confound (3), was deferred — it would only further shrink the low-line HSE lane, reinforcing the
same conclusion; it needs a scratch reload + another long run for diminishing returns).

## Results (full season 2025-26)

| Run | picks | ALL HR | OVER | UNDER | HSE-lane (OVER,edge<2) | edge5+ |
|---|---|---|---|---|---|---|
| UNGATED | 208 | 58.2% | 59.3% (182) | 50.0% (26) | **133 @ 54.9%** | 91.7% (12) |
| GATED | 149 | 53.0% | 54.9% (122) | 44.4% (27) | 90 @ 47.8% | 90.9% (11) |
| GATED+FLOOR | 57 | 47.4% | **100.0% (5)** | 42.3% (52) | **0** | 87.5% (8) |

**HSE-lane (OVER & edge<2) pick count by month, ungated → gated → floor:**
Dec 24→24→(in 9 total) · Jan 26→26 · Feb 22→22 · Mar 44→**12** · Apr 17→**6** → (floor: 0 all months).

## STEP 4 finding — how much does production ALREADY suppress the HSE lane?
**Only ~32%, and ENTIRELY in Mar/Apr.** Dec/Jan/Feb HSE-lane suppression under regime+health gating is
**0%** — the full ~55% lane is live in production for the first three months. Gating only bites once the
cautious/TIGHT regime triggers (~Mar 7+: `disable_over_rescue`, OVER-floor→7.0). Even after gating, **90
HSE-lane picks survive at 47.8% HR** — gating trims the late tail but does NOT fix the lane. It also cuts
overall HR (58.2%→53.0%) because it bluntly removes April's strong picks (25→12) alongside weak ones.
⇒ **Regime gating is a late, blunt instrument; it is NOT a substitute for the targeted STEP 3 floor.**

(Note: the HSE-lane proxy here is "OVER & edge<2"; it recovers the INC-4 lane almost exactly — 133 picks
@ 54.9% vs INC-4's "133 @ ~55%".)

## STEP 3 finding — the floor does exactly its job on OVER, and unmasks a separate UNDER issue
- ✅ **The floor cleanly removes the HSE OVER lane:** HSE-lane 133→**0**; OVER-at-edge<2 → **0**. The only
  surviving OVER picks are **5 @ 100% HR, all edge5+** — the floor concentrates OVER into the genuine
  money zone, refuting the need for the "100% (3-0)" carve-out that bypassed the 6.0 floor + bench/role.
- ⚠️ **On 2025-26 (the strongest raw season) the removed HSE lane was marginally PROFITABLE (54.9%)** —
  just above the ~53.5% breakeven. So on a good season the floor trims a little profit; its value is
  protection on NORMAL seasons, where OVER edge<3 is net-negative in 4/5 seasons (documented). The floor
  removes a *small-sample-justified, season-fragile* carve-out — sound risk management, not a free win.
- ⚠️ **Floor-on overall HR (47.4%) is LOWER — but this is a composition artifact, not the floor harming
  OVERs.** Removing the dominant OVER lane frees volume-cap/rescue-cap slots, so the single-model sim
  admits **2× more low-edge UNDER (52 vs 26), a pre-existing UNDER-edge<2 lane @ 39.1% (N=46)**. This is a
  SINGLE-MODEL-SIM interaction (the sim's known UNDER-drought / cap dynamics); production's `under_low_rsc`
  (real_sc≥2) + the fleet pool handle UNDER differently, so this lane likely won't replicate at production
  scale. It is NOT caused by the floor making any pick worse — every OVER the floor kept is 100%.

## Recommendation (for sign-off)
The STEP 3 floor is implemented behind `HSE_RESCUE_FLOOR_ENABLED` (default OFF → zero behavior change) on
branch `offseason-eval-foundation-2026-06`, with all six falsified "100% (3-0)" comments corrected to
cite INC-4. Per the action plan: **ship the flag (default OFF), shadow via `filter_counterfactual`, and
enable only after CF HR ≤ 45% at N ≥ 30.** Do NOT flip it on blind — the in-sim UNDER-lane interaction
means the net production effect must be confirmed in shadow first. `MIN_EDGE` (3.0) and the 6.0 OVER floor
are unchanged.

## Caveats
- Single model (`wf_sim_v12noveg`), 2025-26 only. Not the fleet. Sim ABSOLUTE HR is not
  production-comparable (quality_floor bypassed at 100.0; betting-feed signals partial). The RELATIVE
  3-way comparison is the trustworthy read.
- edge5+ N is tiny (5–12). The OVER-side conclusion rests on the lane *counts* (133→0) and direction, not
  the edge5+ point HRs.
- `regime_context` for the sim is production-history-derived (yesterday's prod BB HR + `league_macro_daily`),
  so the GATED run reflects what production gating actually applied on those dates — not a counterfactual.

## Artifacts
- Code (eval bucket): `bin/simulate_best_bets.py` (loads signal_health+regime),
  `scripts/nba/training/discovery/build_sim_predictions_table.py` (`--real-quality` flag, unused here).
- Code (live path, branch, default-OFF): `ml/signals/aggregator.py` STEP 3 floor + comment fixes.
- Data (gitignored): `results/bb_simulator/bb_injection_picks_gated_q100{,_tail}.csv`,
  `bb_injection_picks_gated_floor_on.csv`.
- Reproduce floor-on: `HSE_RESCUE_FLOOR_ENABLED=true PYTHONPATH=. python -u
  scripts/nba/training/discovery/bb_injection_run.py --start 2025-10-28 --end 2026-04-12 --out <csv>`.
</content>
