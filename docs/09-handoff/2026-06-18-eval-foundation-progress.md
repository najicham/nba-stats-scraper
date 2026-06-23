# Eval-Foundation rebuild — session progress

**Date:** 2026-06-18
**Why:** Off-season. The system's recurring failure mode is conclusions drawn on small/contaminated
samples then reversed. The tools that would prevent that are broken: the signal-discovery stack
FileNotFoundErrors (no `bb_enriched_simulator.py`, no walk-forward CSV cache), all P/L is fictional
flat −110, CF-HR only spans toxic March. Decision (with user): rebuild a **trustworthy multi-season
walk-forward evaluation foundation** before any more signal/model work. **Nothing here is deployed.**

## Increment ladder

| INC | What | Status |
|---|---|---|
| INC-1 | Walk-forward **predictions cache** (5 seasons, leak-clean w56_r7) | ✅ DONE |
| INC-2 | Rebuild the 6 `results/bb_simulator/*.csv` **enrichment extracts** (revive `bb_enriched_simulator`) | ✅ DONE |
| INC-3 | Verify `feature_scanner`/`combo_tester` run end-to-end + real-odds available | ✅ DONE (simulator P/L rewiring = follow-up) |
| INC-4 | **BB-pipeline injection** (scratch table → `simulate_best_bets` on counterfactual preds) | pending |

## INC-2 + INC-3 — DONE (discovery stack revived)

`scripts/nba/training/discovery/build_bb_simulator_cache.py` regenerates the 6 enrichment extracts the
lost `bb_enriched_simulator.py` produced. **36/49 columns are direct `feature_N_value` extracts** (incl. 2
naming-variant renames: `avg_pts_vs_opponent`=FS#29, `margin_vs_line_avg_last5`=FS#56). The **13
player_game_summary columns** are computed with **leakage-safe window functions** (every frame ends at
`1 PRECEDING`, per the MEMORY rule) over prior played games. Built:
- `feature_store_enrichment.csv` (116,275×25), `feature_store_extra.csv` (116,275×15),
  `player_game_summary_enrichment.csv` (138,461×15), `bettingpros_multibook.csv` (87,566×8,
  **carries real `over_odds_median` for P/L**), `schedule_enrichment.csv` (138,417×4).
- **bettingpros covers all 5 seasons** (2021:6.3K … 2026:11.8K) → cross-book signals work throughout.

**Verification (INC-3):** both consumers run end-to-end on the rebuilt cache:
- `feature_scanner.py --min-edge 3`: loads 47,585×72 (all joins OK, 5 seasons), 312 hypotheses,
  **63 cross-season-validated** signals, 61 new. Sensible top signals (`three_pct_season` high→UNDER 65%,
  `vegas_points_line` high→UNDER 60%, `fta_cv` low→UNDER 60%).
- `combo_tester.py --min-edge 3`: runs in 4s; fires the **cross-book `bp_dropped_under`** signal (confirms
  the bettingpros extract), finds 70.6% OVER combos (`hse_over+rest_advantage_over+high_spread`) and 62%
  UNDER combos.

**⇒ The discovery stack is operational again** — ~10 briefing experiments (feature/combo/archetype scans,
the cross-BOOK `combo_3way` replacement search) are unblocked. Real odds are in the cache; the remaining
INC-3 sub-item is wiring `over_odds_median` into the simulators' P/L (currently flat −110).

## INC-1 — DONE

`scripts/nba/training/discovery/build_walkforward_predictions.py` regenerates the lost prediction cache:
- **Engine:** reuses `ml/experiments/season_walkforward.py` training primitives; one bulk BQ load per
  season then in-memory rolling **w56_r7** (train prior 56d, predict next 7d, step 7d). Inherently
  leak-safe (each cycle trains only on past). Model = **CatBoost V12_NOVEG** (production base; noveg
  keeps edge non-circular). Line = **`feature_25_value`** (in-store vegas line — only source covering all
  5 seasons; DraftKings odds only cover 2023-26). Grade vs `player_game_summary.points`. No BQ/GCS writes.
- **Output** (exact paths `discovery/data_loader.py` expects):
  `results/nba_walkforward_2021/`, `_2022/`, `_clean/` (2023-24+2024-25), `bb_simulator/predictions_2025_26_all_models.csv`.
  Columns: `game_date, player_lookup, predicted_points, line, actual_points, edge, direction, correct`.
- **Built:** 47,521 graded preds across 5 seasons (2021-22: 8.7K, 2022-23: 5.6K, 2023-24: 10.7K,
  2024-25: 12.1K, 2025-26: 10.4K). `results/` cache dirs added to `.gitignore` (reproducible).

### Data-quality caveat
2021-22 / 2022-23 rely on **backfilled `feature_25` lines** (lower N, 2022-23 only 5.6K preds, sub-50%
raw HR). Treat the **3 recent seasons (2023-24/24-25/25-26) as high-confidence**, the 2 oldest as
lower-confidence.

## First payload — edge-strategy belief re-validation (5 seasons)

Tool: `scripts/nba/training/discovery/edge_belief_audit.py`. RAW single-model HR (not BB-pipeline), flat −110.

| Belief (CLAUDE.md/MEMORY) | Result on clean cache | Verdict |
|---|---|---|
| **B1:** OVER net-negative at edge 3-5 in 4/5 seasons | 48.2 / 47.3 / 48.1 / 52.1 / **65.8%** → net-neg 4/5 | ✅ **REPLICATES** |
| **B2:** UNDER stable ~57-58% across edges | edge0-3 **52.7%**, 3-5 56.6%, 5+ 61.0% (rises, not flat) | ⚠️ partial — ~57% at edge3+, but sub-edge3 ≈53% and 5+ ≈61% |
| **B3:** edge 6-8 ≈61% **consistent** all seasons | 25 / 50 / 56 / 78 / 83% by season (N=8–41); pooled 67.9% | ❌ **NOT per-season consistent** — pooled/small-N effect |
| **B4:** edge5+ money zone ≥60% | pooled **63.9%** (N=249); per-season only 2/5 clear 60% | ⚠️ holds pooled & recent seasons; not robust 2021-23 |

**Takeaways:**
1. B1 replicating on an independent clean rebuild **validates the cache** for OVER edge analysis.
2. B3/B4 "consistent across seasons" framing is **overstated** — they're pooled effects on tiny
   per-season N (the exact small-sample trap the foundation exists to expose). Edge-floor decisions for
   next season should lean on B1 (robust) and treat high-edge consistency claims cautiously.
3. **Edge5+ is structurally sparse** (249 picks / 5 seasons for ONE noveg model). Robust edge5+ /
   best-bets conclusions require the **fleet or BB-pipeline**, not a single model → this is the concrete
   motivation for **INC-4 (BB-pipeline injection)**.
4. **2025-26 is the STRONGEST season on a fresh walk-forward** (e3+ 68%, e5+ 78.9%) — re-confirms the
   live collapse was **stale-model/fleet**, not the season itself (consistent with `2025-26-anomaly-rootcause`).

## INC-2 scope (next session) — the 6 enrichment extracts

`discovery/data_loader.py` joins these on `(game_date, player_lookup)`; the exact required columns were
mapped from `feature_scanner.py:507-526`:
- `feature_store_enrichment.csv` — named features aliased from `feature_N_value` via the contract:
  days_rest, opponent_pace, scoring_trend_slope, points_std_last_10, prop_under/over_streak,
  over_rate_last_10, implied_team_total, spread_magnitude, multi_book_line_std, games_vs_opponent,
  star_teammates_out, points_avg_season, rest_advantage, vegas_points_line, minutes_avg_last_10,
  game_total_line, points_avg_last_3, consecutive_games_below_avg, usage_rate_last_5, back_to_back, home_away.
- `feature_store_extra.csv` — prop_line_delta, points_avg_last_5/last_10, recent_trend, team_pace,
  team_win_pct, avg_pts_vs_opponent, dnp_rate, pts_slope_10g, minutes_load_last_7d,
  deviation_from_avg_last3, line_vs_season_avg, margin_vs_line_avg_last5.
- `player_game_summary_enrichment.csv` — usage_rate, fg_pct_season, three_pct_season, three_pa_per_game,
  fta_avg_last_10, fta_cv_last_10, minutes_avg_season, fg_pct_last_3, three_pct_last_3, mean_points_10g,
  prev_pm_1/2/3. **RISK:** several are rolling stats that may NOT sit in `player_game_summary` directly —
  may need computation from game logs. This is the hard part of INC-2.
- `bettingpros_multibook.csv` — line_std, line_movement (+ book_count). **This is also the real-odds
  source for INC-3** (`odds_american` per book).
- `schedule_enrichment.csv` — rest/opponent context (no explicit columns referenced; metadata).

Plan: one script `scripts/nba/training/discovery/build_bb_simulator_cache.py` that emits all 6 CSVs from
BQ, mapping `feature_N_value`→named via `shared/ml/feature_contract.FEATURE_STORE_NAMES`. Verify by
running `feature_scanner.py`/`combo_tester.py` end-to-end and reproducing a known archetype
(low-line/low-var UNDER 62%).

## Real-odds reckoning (2026-06-19) — flat −110 FLIPS the marginal cells

Tool: `scripts/nba/training/discovery/real_odds_reckoning.py`. Attaches ACTUAL bettingpros odds (both
sides, **97.6% coverage**, 80.3% exact-line) to every cache pick and recomputes ROI vs flat −110.

- **Real median odds: OVER −115, UNDER −117** (vs assumed −110) → **real breakeven ≈ 53.5%**, not 52.4%.
  Real vig is a **−2 to −4.5pp ROI drag** vs flat −110, consistently (bigger at high edge where payouts matter).
- **Marginal cells FLIP from "profitable" to losing at real prices:**
  - **UNDER edge 0-3: +0.6% → −2.2%** (FLIPS, 4/5 seasons) — the high-volume low-edge UNDER (18K picks) is a
    **vig trap**, not a small edge.
  - **OVER edge 3-5: +0.8% → −2.3%** (FLIPS) — sharpens B1; clearly negative at real odds.
- **Robust winners SURVIVE (with thinner margin):** edge5+ OVER **+27.5%**, edge5+ UNDER **+11.3%**,
  edge3-5 UNDER +5.7% (good seasons only; negative in 2024-25). edge3+ stays positive pooled both directions.
- **Operating rule for next season:** real breakeven ≈ **53.5%**; **edge5+ is the durable money zone** both
  directions; **sub-edge-3 UNDER and edge3-5 OVER are vig traps** — never bet them. Any signal/filter
  promoted on a flat-−110 ~52-54% HR is suspect — re-evaluate at real odds.

This is the foundation proving its worth on day one: it caught a systematic bias (flat −110) that flips real
conclusions, exactly the kind of error the rebuild exists to prevent.

## Artifacts
- Builder: `scripts/nba/training/discovery/build_walkforward_predictions.py`
- Audit: `scripts/nba/training/discovery/edge_belief_audit.py`
- Cache: `results/nba_walkforward_*/predictions_w56_r7.csv`, `results/bb_simulator/predictions_2025_26_all_models.csv` (gitignored)
