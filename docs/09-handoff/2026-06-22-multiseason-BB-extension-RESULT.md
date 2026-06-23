# Multi-season BB-injection extension — RESULT (negative / fidelity-limited)

**Date:** 2026-06-22
**Status:** DONE. Outcome: the BB-vs-raw harness is **NOT faithful on 2023-24/2024-25** — the OVER-side
signal feeds are data-dead historically, so the pipeline degenerates to a UNDER-only low-edge slate.
**The documented "+13.7pp filter lift" could NOT be cross-validated; it rests on 2025-26 data only.**
Eval-only, single model (`wf_sim_v12noveg`), leak-clean cache. Nothing deployed.

## What was done
- Fixed the hardcoded `WHERE game_date >= '2025-10-22'` season floor in `supplemental_data.py` (7 sites →
  dynamic `@season_start` from `target_date`'s season; commit `1cb056cc`). Without this, every
  season-stat feature was empty for pre-2025 dates. Also a latent prod fix (2026-27 would have pulled
  prior-season rows). Tier 2 (`null v12_preds`) skipped — confirmed immaterial (feeds shadow signals
  only, not `real_sc`/picks).
- Ran `bb_injection_run.py` on the full 2023-24 (109 dates) and 2024-25 (109 dates) seasons,
  timeouts=0. Compared to the raw cache (`nba_walkforward_clean`).

## Results

| | 2023-24 | 2024-25 |
|---|---|---|
| BB picks | 65 (**64 UNDER, 1 OVER**) | 67 (**67 UNDER, 0 OVER**) |
| ALL HR: raw → BB | 51.0% → 55.4% (**+4.4pp**) | 50.4% → 49.3% (**−1.1pp**) |
| edge3+: raw → BB | 54.5% → 50.0% (−4.5pp, N=10) | 51.7% → 75.0% (+23.3pp, N=8) |
| edge5+: raw → BB | 54.0% → 50.0% (N=4) | 65.5% → 100% (N=1) |
| dominant lane | edge<2 UNDER, 50 @ 56.0% | edge<2 UNDER, 56 @ **44.6%** |

(2025-26 for reference: 208 picks, 182 OVER, ALL +6.7pp, dominated by the HSE OVER lane.)

## Why — the OVER side is data-dead pre-2025 (verified)
Per-date supplement logs for 2023-24/2024-25 show: **TeamRankings pace = 0 teams, projections = 0
players, sharp book lean = 0 players** (BettingPros line movement has partial coverage, 37–76 players).
So the OVER-rescue infrastructure (`fast_pace_over`/`predicted_pace_over`, projection consensus, sharp
signals, and the scoring-environment inputs behind `high_scoring_environment_over`) **cannot fire**. With
no OVER rescue and the 6.0 OVER floor intact, ~zero OVER picks survive → the slate is **all UNDER**.
Regime/health gating correctly fail-open (0 fires, no contamination). This is the INC-4 "betting-feed
signals are PARTIAL historically" caveat, manifesting as a total OVER-side blackout.

## Conclusions
1. **The "+13.7pp filter lift" is NOT multi-season-validated — it rests on 2025-26 (the only season with
   full betting/pace/projection feeds).** This run does NOT refute it (the OVER lane that carries the lift
   is untestable historically), but it cannot confirm it either. **Treat +13.7pp as single-season-
   supported; do not weight it as a cross-season truth.** This is exactly the project's recurring
   "thin/contaminated-sample" caution applied to our own headline number.
2. **The one historically-testable lane — low-edge UNDER (mostly `home_under`, real_sc=1) — does NOT beat
   raw** (edge<2 UNDER: 56.0% in 2023-24, **44.6% in 2024-25**; raw ALL ≈50-51%). This **corroborates the
   real-odds reckoning rule** ([[eval-foundation-rebuild-2026-06]]): sub-edge-3 UNDER is a vig trap. The
   single-model pipeline adds no lift to that lane.
3. **edge3+ BB N is tiny (8–10) and inconsistent** (−4.5pp in 2023-24 vs +23.3pp in 2024-25) — not
   interpretable. No robust high-edge cross-season read is possible from a single model.
4. **Eval-foundation limit identified:** cross-season OVER-side BB testing is blocked by missing
   historical raw feeds (TeamRankings/projections/sharp/VSiN don't exist pre-2025-26). Fixing it would
   require backfilling those raw tables, which is not possible (the data was never scraped). So the BB
   pipeline's OVER-side value is **structurally only testable from 2025-26 forward.**

## Recommendation
- **Stop trying to cross-validate the OVER-side BB lift on pre-2025 seasons** — the data doesn't exist.
  Any further BB-vs-raw cross-season work should be UNDER-only (the feed-independent lane) or wait for
  2025-26+ to accrue more seasons of full feeds.
- **Down-weight "+13.7pp filter lift" in any decision** to "2025-26-only, ~+6.7pp on the trustworthy
  broad-N set (INC-4)." The robust, cross-season-safe facts remain: edge5+ is the money zone; sub-edge-3
  UNDER and edge3-5 OVER are vig traps (real-odds reckoning).
- This strengthens the case to lean on **feed-independent** signals (e.g. `book_disagreement` is
  cross-BOOK and partially present historically; `home_under`) and to treat feed-dependent OVER rescues
  (HSE, pace, sharp) as **unvalidated outside 2025-26**.

## Artifacts
- Code: `ml/signals/supplemental_data.py` (`@season_start`, commit `1cb056cc`, branch only).
- Data (gitignored): `results/bb_simulator/bb_injection_picks_{2023_24,2024_25}.csv`.
- Reproduce: `PYTHONPATH=. python -u scripts/nba/training/discovery/bb_injection_run.py --start <season-open> --end <season-end> --out <csv>`.
</content>
