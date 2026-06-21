# STEP 5 (re-scoped Action A) — staleness arm RESULT

**Date:** 2026-06-21
**Status:** 5a COMPLETE. **Decision: STOP — do NOT proceed to 5b.** Action A downgraded.
**Nothing deployed.** Eval-only, on the leak-clean walk-forward foundation. Single season (2025-26).

## What was tested

Hypothesis (from the action plan + strategy doc): the production Jan 73.8% → Mar 46.7% best-bets
collapse is a **model-staleness** effect, not a model-quality one — because the clean fresh walk-forward
(7d cadence) shows NO late-season collapse (2025-26 is the *strongest* raw WF season). If so,
`cap_to_pre_late_season` + retrain cadence are the recovery lever.

To reproduce staleness, added a `--stale-arms` mode to
`scripts/nba/training/discovery/build_walkforward_predictions.py`: rebuild 2025-26 with **window=56
fixed** at four retrain regimes, one bulk BQ load shared across arms:

- `cad7_fresh` — retrain every 7d (≤6d stale) — the baseline
- `cad21` — retrain every 21d (≤20d stale)
- `cad28` — retrain every 28d (≤27d stale)
- `frozen_feb28` — fresh 7d until train-end passes 2026-02-28, then **frozen** (no retrain) through
  season end. This is the maximal-staleness arm and is the closest analogue to what
  `cap_to_pre_late_season` produces (capping `train_end` ≈ freezing the model after the cap date).

Identical eval coverage across arms (same 10,420 graded preds, same monthly N). Decision rule
(pre-registered in the plan): collapse only in frozen/28d → staleness reproduced; **frozen-Feb28 holds →
STOP, downgrade Action A.**

## Result

**Mar+Apr pooled (the production collapse window):**

| Arm | trains | all HR (N=4135) | e3+ HR | e5+ HR |
|---|---|---|---|---|
| `cad7_fresh` | 16 | 52.1% | 64.0% (164) | **79.4% (34)** |
| `cad21` | 6 | 51.1% | 63.4% (172) | 77.5% (40) |
| `cad28` | 4 | 51.8% | 67.1% (140) | 81.8% (33) |
| `frozen_feb28` | 10 | 51.7% | 60.5% (167) | **61.5% (39)** |

**Monthly HR (all picks) — flat across every arm, no collapse anywhere:**

| month | cad7_fresh | cad21 | cad28 | frozen_feb28 |
|---|---|---|---|---|
| 2025-12 | 53.2 | 52.7 | 52.7 | 53.2 |
| 2026-01 | 51.0 | 51.4 | 51.9 | 51.0 |
| 2026-02 | 50.8 | 50.0 | 52.1 | 50.8 |
| 2026-03 | 51.0 | 50.0 | 51.0 | 50.8 |
| 2026-04 | 55.2 | 54.3 | 54.1 | 54.1 |

(Full-season: cad7_fresh e3+ 67.4%/e5+ 80.0% N=95 — reproduces the INC-4 RAW baseline e3+ 68.0%/e5+
78.9% N=95, so the arm machinery is consistent with the prior cache.)

## Verdict

**1. The production Mar 46.7% collapse is NOT reproduced by any staleness arm.** The *worst* arm
(`frozen_feb28`) is 51.7% all-picks / **61.5% edge5+** in Mar+Apr — degraded, but still well above the
real breakeven (~53.5%) and nowhere near the production 46.7%. ⇒ On clean WF data, **model staleness
alone does not explain the production collapse.** The collapse is a *production-specific* confound
(scoring-regime shift + dirty/late line snapshots since fixed + the LGBM/CatBoost fleet-clone collapse),
not something a training cap fixes.

**2. The cap's own premise is contradicted on clean data.** `cap_to_pre_late_season` ≈ the
`frozen_feb28` arm (capping `train_end` at ~Feb 28 makes every later retrain reuse the same
Feb-capped window = a frozen model). That arm is the **WORST** late-season edge5+ performer
(61.5% vs 79.4% fresh, ~18pp). The `cad21`/`cad28` arms barely differ from fresh. So **fresh retraining
that INCLUDES March data is best**, and freezing/capping at Feb 28 HURTS edge5+ — the opposite of the
"March training compresses edge" (Session 508) thesis, on this clean foundation.

**3. Decision: STOP. Do NOT run 5b** (capped-vs-uncapped multi-season). Its precondition (5a reproduces
staleness) failed. Action A is **downgraded** from "biggest profit lever" to: keep
`cap_to_pre_late_season` only as insurance, and treat its profit-lever justification as **not supported
— arguably refuted** — by clean-WF evidence. Any future cap decision should be re-derived from the clean
foundation, not the Session-508 production observation.

**4. Bonus — extends the settled cadence finding.** MEMORY's cadence result (7d ≈ 14d, HR-equivalent)
explicitly did NOT test 21d/28d. This run does: on 2025-26, **cad21 and cad28 are HR-equivalent to
cad7** at every band (e3+ 64.6/65.5 vs 67.4; e5+ 77.2/78.2 vs 80.0 — all within noise). Only a *true
freeze* degrades edge5+. ⇒ Retrain cadence is even more relaxable than thought (≤28d ≈ weekly for HR);
14-day adoption (halving retrain cost) is further de-risked. Still single-season; not a deploy trigger.

## Caveats (do not over-read)
- **Single season (2025-26).** Decision rule was 2025-26-scoped by design. 5b would have been the
  multi-season test; it's skipped because the premise failed.
- **edge5+ N is small** (33–40/arm in Mar+Apr). The frozen 18pp edge5+ drop is ~1.6 SE — suggestive,
  not p<0.05. The robust read is the *direction*: frozen is worst, cad21/28 ≈ fresh, no arm collapses.
- This is the **raw single-model** WF (V12_NOVEG), not the BB pipeline or the production fleet.

## Artifacts
- Code: `scripts/nba/training/discovery/build_walkforward_predictions.py` (`--stale-arms`, `run_arm`,
  `grade`, `stale_arms`). Eval-only; the cache-rebuild path is unchanged.
- Data (gitignored): `results/nba_staleness/staleness_arms_2025_26.csv` (41,680 rows),
  `staleness_monthly_hr_2025_26.csv`.
- Reproduce: `PYTHONPATH=. python -u scripts/nba/training/discovery/build_walkforward_predictions.py --stale-arms`
</content>
</invoke>
