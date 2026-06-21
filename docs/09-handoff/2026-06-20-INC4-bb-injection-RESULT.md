# INC-4 BB-pipeline injection — RESULT

**Date:** 2026-06-20
**Status:** Non-zero BB picks achieved; single-model 2025-26 BB-vs-raw measurement produced.
**Nothing deployed.** Training/eval only. The 4 prod-code fixes below are STAGED for sign-off (they
auto-deploy on push to main and touch the live best-bets path).

## Headline

The handoff's `picks=0` diagnosis ("edges too tight for OVER floor 6.0" + "no signal history → UNDER
can't reach real_sc>=2") was a **red herring**. The real cause was a **units bug** in the scratch-table
builder: `build_sim_predictions_table.py` set `feature_quality_score = 1.0`, but the aggregator's
`quality_floor` blocks anything `< 85` (0–100 scale, `ml/signals/aggregator.py:741`). So EVERY candidate
that cleared the edge floor was silently killed at `quality_floor` — which is exactly why the rejection
histogram showed all downstream gates (`over_edge_floor`, `under_low_rsc`, `signal_density`, `sc3_over_block`)
at **0**: they never executed. This is the same 0-1-vs-0-100 class of bug as the recurring `pct` convention
incident in MEMORY.

**Fleet-scale edges were NOT needed to get picks.** picks=0 was a data bug, not edge-tightness. Single-model
is in fact the cleanest apples-to-apples test of "do signals/filters beat raw edge" (same predictions, same
line/direction/edge; the fleet would conflate model-selection effects). Fleet is only needed for production
*volume* and cross-model signals — a separate question.

## How we got non-zero picks (the fix chain)

Diagnostic = `scripts/nba/training/discovery/bb_injection_diagnose.py` (new; prints the full per-date
`filter_summary['rejected']` histogram). Fixes, in the order they unblocked:

1. **`build_sim_predictions_table.py`**: `feature_quality_score` 1.0 → **100.0** (the real blocker). The WF
   cache is built only on quality-ready rows (`get_quality_where_clause`), so 100.0 is defensible. Scratch
   table reloaded.
2. **`ml/signals/supplemental_data.py:831`** (PROD): DvP gamebook-fallback `g.minutes` → `g.minutes_played`.
   The column is `minutes_played`; the fallback query had been throwing (caught/non-fatal) on EVERY call, so
   DvP self-computation never worked in prod. After the fix the fallback loads (verified: "DvP fallback
   loaded for 30 teams").
3. **`ml/signals/aggregator.py:706`** (PROD): `pred.get('source_model_family', '')` →
   `pred.get('source_model_family') or ''`. `classify_system_id()` returns **None** for unclassified ids and
   `dict.get`'s default does NOT apply when the key exists with a None value → `None.startswith('v9')` crash.
4. **`ml/signals/ultra_bets.py:80`** (PROD): same `or ''` fix → `None.startswith('v12')` crash in
   `classify_ultra_pick`.
5. **`ml/signals/per_model_pipeline.py:758`** (PROD): twin of fix #2 (`g.minutes` → `g.minutes_played`) on
   the actual production per-model path. Found by the review agent.

Result on the first test date (2025-12-23): **209 candidates → 8 BB picks** (was 0).

## The prod fixes are REAL bug fixes (not just sim-enablers)

A dedicated adversarial review (agent) confirmed all four are SAFE TO PUSH and that #3/#4 close **live**
crash paths in production: `classify_system_id` returns None for `lightgbm_v1`, `xgboost_v1`, the diversity
models (`similarity_balanced_v1`, `ensemble_v1`, `moving_average`, `zone_matchup_v1`), `catboost_mq_v12`,
and bare `catboost_v16_noveg` — all enabled/deployable fleet models. In production, an UNDER pick at edge ≥ 7
(aggregator) or any ultra-candidate (ultra_bets) **from any of those models** would crash aggregation for the
whole date. The DvP `g.minutes` bug existed in BOTH `supplemental_data.py` and the production-path
`per_model_pipeline.py` (both now fixed); blast radius is shadow-only (`dvp_favorable_over` is a SHADOW
signal), so it never changed which picks shipped — but it meant the DvP SPOF-mitigation fallback was dead.

**Recommendation:** push fixes #2–#5 as a standalone `fix:` commit after review. They are independent of the
eval work and harden the live path. (#1 is sim-only.)

## Measurement: BB-pipeline vs RAW (single model wf_sim_v12noveg, 2025-26)

Run = `scripts/nba/training/discovery/bb_injection_run.py --start 2025-10-28 --end 2026-04-12`
(picks → `results/bb_simulator/bb_injection_picks_2025_26.csv`). Comparison =
`scripts/nba/training/discovery/bb_vs_raw_compare.py`. Both raw and BB are graded against the identical cache
`correct` column (same predictions/line/direction/edge), so this is a clean relative test.

**RAW baseline (all cache predictions at edge band, 2025-26):**
- edge3+: 68.0% (N=431) | edge5+: **78.9% (N=95)** | edge6+: 83.3% (N=48) | edge7+: 87.0% (N=23)
- (2025-26 is the STRONGEST raw season on a fresh walk-forward — the documented "raw ≈53%" is the
  cross-season figure. So the BB pipeline here is tested against an unusually high raw bar.)

**BB-pipeline result** (102 dates, timeouts=0 → full coverage, comparison is exact):

| Edge band | RAW HR | BB-pipeline HR | Lift |
|---|---|---|---|
| ALL | 51.5% (N=10386) | 58.2% (N=208) | +6.7pp |
| edge3+ | 68.1% (N=427) | 85.0% (N=20) | +16.9pp |
| edge5+ | **78.9% (N=95)** | **91.7% (N=12)** | **+12.8pp** |

**The BB pipeline beats raw at every edge band** — it concentrates picks into higher-HR subsets even on the
anomalously-strong 2025-26 raw season. ✅ INC-4 acceptance met (signals/filters add value over raw). BUT the
high-edge N is SMALL (edge5+ N=12, edge3+ N=20) — directionally right, not a robust point estimate. The
trustworthy-N signal is the broad set: ALL 208 picks at 58.2% vs raw 51.5% (+6.7pp).

**Pick mix is the real story — 188 of 208 picks are edge<3, 182/208 are OVER:**

| edge | N | HR | | dir | N | HR |
|---|---|---|---|---|---|---|
| <2 | 154 | 53.9% | | OVER | 182 | — |
| 2-3 | 34 | 61.8% | | UNDER | 26 | — |
| 3-5 | 8 | 75.0% | | | | |
| 5+ | 12 | 91.7% | | | | |

The slate is dominated (133/208) by **HSE-rescued low-line OVER picks** at edge<2 hitting only **~55%** —
barely above the ~53.5% real breakeven. Verified by dumping picks: every low-edge OVER carries
`rescue_signal='high_scoring_environment_over'` on low lines (5.5–13.5), real_sc 3–4.

### 🔍 Genuine finding: HSE OVER rescue at scale ≈ 55%, NOT the "100% (N=3)" belief
CLAUDE.md/MEMORY hold `high_scoring_environment_over` = "100% BB HR (3-0) — only validated OVER rescue".
The walk-forward foundation shows that at **N=133** the HSE rescue lane is **~55%** — the 100% was a textbook
N=3 small-sample artifact (exactly what this foundation exists to catch). **THREE confounds make ~55% a soft
number — do not act on it before the gated re-run:**
1. **No `signal_health`** passed → production's **rescue-health gate** (`RESCUE_MIN_HR_7D=60`, demotes HSE when
   its 7d HR < 60%) is OFF in the sim.
2. **No `regime_context`** passed → TIGHT-market `disable_over_rescue` + the 6.0→7.0 OVER-floor raise are OFF.
   2025-26 had sustained TIGHT windows (late-Feb→March) where production would have killed this lane outright.
3. **`quality_floor` bypassed** (scratch `feature_quality_score`=100): the 133 HSE picks are LOW-LINE players
   (5.5–13.5) — exactly the fringe/role players most likely to carry default features and be blocked by
   production's zero-tolerance/`quality_floor (≥85)`. So a chunk of this lane wouldn't exist in production at all.
**Net:** the sim shows the HSE lane *ungated + on a fuller candidate pool*; production suppresses much of it via
(1)+(2)+(3). So this is BOTH a fidelity gap AND a real flag that the "100%" belief rests on N=3. **The ~55% is
not a production estimate — it's the ceiling of how bad an ungated HSE lane gets.** Action: the gated re-run
(below) resolves (1)+(2); a real-quality scratch join resolves (3). Consider an explicit edge/line floor on HSE
rescue regardless.

**Monthly BB HR:** Dec 66.7% (N=30), Jan 50.9% (N=55), Feb 48.5% (N=33), Mar 56.9% (N=65), Apr 80.0% (N=25) —
the Jan-Feb sag is the ungated rescue lane in the weak/tight window (production would have gated/halted it).

**Pick volume:** thin — ~2 BB picks/date (single model, no fleet, no regime/health context). Production gets
~10–15/day via the fleet (more edge5+ candidates) + live context. Fleet matters for *volume*, not for getting
picks at all.

## Faithfulness of the measurement (audit agent)

Faithful for the RELATIVE BB-vs-raw question; the structural signal core all fires on the real date (edge,
minutes/combos, 3PT/FG, pace, implied total, line-rising, blowout/spread, FTA, teammate usage, prop-streak,
home/away). Known deviations from production (do NOT read sim ABSOLUTE HR as production-comparable):
- **`quality_floor` is bypassed** (scratch `feature_quality_score`=100). For the relative comparison this is
  fine (raw and BB use the same cache pool, quality≥70), but sim pick COUNTS are not production counts. To make
  it production-faithful, join real `ml_feature_store_v2.feature_quality_score` in the builder instead of 100.
- **Betting-feed signals are PARTIAL** historically (odds_api/bettingpros snapshot coverage):
  `line_drifted_down_under`, `sharp_line_drop_under`, `book_disagree_*`, `over_line_rose_heavy`,
  `counter_market_under` under-fire where coverage is thin.
- **No regime/health context** is passed by `simulate_date` (`_regime_context={}`, `_signal_health={}`) → OVER
  floor stays 6.0 (no TIGHT raise), no COLD downweighting, no auto-halt. This is the *correct regime-neutral
  baseline*, but it's more permissive than production in 2025-26's late-Feb→March tight windows.
- **Immaterial deadness:** streak signals (`streak_data` keyed on the synthetic system_id → empty) and
  `v12_preds` consensus feed only SHADOW signals / `per_model_pipeline` — no active real_sc signal reads them
  in the single-model path. `quantile_*` signals are dead (point model, no quantile columns) — expected.
- UNDER real_sc≥2 in the sim realistically needs two of {home_under, volatile_starter_under, hot_3pt_under,
  bench_under} — a FAITHFUL reproduction of production's UNDER drought, not a sim artifact.

## Leakage audit (agent) — cache is TRUSTWORTHY

Walk-forward training is temporally clean (train `[es-56..es-1]` strictly before eval `[es..ee]`, 0 overlap
violations simulated), `actual_points` is target-only, vegas features excluded so edge is non-circular, and
every enrichment window ends at `1 PRECEDING`. Residual risk RESOLVED: the line/edge come from `feature_25`,
which had an in-game-snapshot leak fixed+backfilled 2026-05-22 — the cache CSVs are dated **2026-06-18**
(post-backfill), so they're clean.

## Multi-season extension (agent scoping) — NOT done, scoped

The measurement is 2025-26-only because `supplemental_data.py` has ~6 hardcoded `2025-10-22` season-window
literals (lines 333, 521, 627, 655, 688, 1603). Minimal faithful extension to 2023-24/2024-25:
- **Tier 1 (~1h):** parametrize those 6 literals via `get_season_start_date(get_season_year_from_date(date))`.
- **Tier 2 (~15m):** null `v12_preds` for all seasons (it silently works only for 2025-26 → parity bug).
- **Tier 3 (~1h):** emit a per-season "dead-signal manifest" (BettingPros/RotoWire/VSiN/projections are
  2025-26-only; flag, don't fix).
- **Tier 4 (skip):** a historical signal_health/regime shim — NOT recommended; fail-open neutral is the
  correct baseline, retro-applying 2025-26-tuned regime logic would bias the result.
The scratch table already spans all 5 seasons; `build_sim_predictions_table.py`/`bb_injection_run.py` need no
changes. Worth doing because 2025-26's raw is anomalously strong — multi-season would test BB lift on
non-anomalous seasons (where raw ≈53%, the documented +13.7pp filter lift should be more visible).

## Artifacts

- New: `scripts/nba/training/discovery/bb_injection_diagnose.py` (rejection histogram),
  `bb_vs_raw_compare.py` (BB-vs-raw table).
- Edited: `build_sim_predictions_table.py` (quality 100), `bb_injection_run.py` (--out CSV).
- Prod fixes (staged, NOT pushed): `aggregator.py`, `ultra_bets.py`, `supplemental_data.py`,
  `per_model_pipeline.py`.
- Picks CSV: `results/bb_simulator/bb_injection_picks_2025_26.csv` (gitignored).

## Bonus — cross-BOOK combo_3way replacement search (queued item #1, done)

Ran `combo_tester.py --min-edge {3,5}` on the 5-season cache (now trustworthy) to find a fleet-diversity-PROOF
(`is_model_dependent=FALSE`) replacement for the cross-MODEL `combo_3way`. **Verdict: no cross-book combo can
structurally replace it** — there are NO synergistic cross-book pairings (the "partner" signal fires on the
same rows, so the combo == the standalone signal), and at edge5+ (combo_3way's money zone) cross-book N
collapses to single digits/season (same low-volume problem combo_3way has, minus the fleet dependency). But
two fleet-proof STANDALONE cross-book candidates are worth accumulating in shadow (real breakeven ≈53.5%
applied):
- **`bp_dropped_heavy_under`** (UNDER, multi-book line_movement ≤ −1.0): 64.0% HR, N=89, beats real-BE in
  **3/3 seasons** (N≥15), +11pp over real vig. Best candidate — but ~half its N is from the 2 newest seasons;
  needs forward N≥30 graded before counting toward `real_sc`.
- **`book_disagree_under`** (UNDER, line_std ≥ 1.0): 60.5% HR, N=76, 2/3 seasons, +7.5pp. Closest analogue to
  the existing `book_disagreement` rescue. Shadow-accumulate.
`bp_rose_over`/`bp_dropped_under` are FDR-significant (N≈155–169) but only 2/4 seasons and lean on 2025-26 —
keep ADDITIVE, do not promote. `book_disagree_over` (56.1%, N=41) is a thin/real-vig-marginal artifact. Bottom
line: strengthen the cross-book rescue LANE with these standalones; there is no drop-in combo_3way replacement.

## Next

1. Push the prod crash/DvP fixes (#2–#5) as a standalone `fix:` commit — needs user sign-off.
2. **Gated re-run** (highest-value follow-up): pass `signal_health` + `regime_context` into the aggregator in
   `simulate_date`, so the rescue-health gate + regime gating apply. Tests whether the HSE-rescue lane
   (~55% ungated, N=133) is suppressed in production and whether the high-edge lift survives.
   **Exact recipe** (all loaders verified to exist):
   - In `bin/simulate_best_bets.py::simulate_date`, before `aggregator = BestBetsAggregator(...)`:
     ```python
     from ml.signals.signal_health import get_signal_health_summary   # ml/signals/signal_health.py:689
     from ml.signals.regime_context import get_regime_context         # ml/signals/regime_context.py:28 (str|date ok)
     try:    signal_health = get_signal_health_summary(bq_client, target_date)
     except Exception: signal_health = {}
     try:    regime_context = get_regime_context(bq_client, target_date)
     except Exception: regime_context = {}
     ```
   - Pass `signal_health=signal_health, regime_context=regime_context` to the `BestBetsAggregator(...)` call
     (both are accepted constructor kwargs — aggregator.py:332/358; see the production wiring in
     `per_model_pipeline.py:1481,1519,1612-1622`). Keep `mode` default (production).
   - Point-in-time safe: `signal_health_daily`/`league_macro_daily` for date D are computed from games
     BEFORE D, and are populated for 2025-26 production dates. No look-ahead.
   - Then re-run `bb_injection_run.py` + `bb_vs_raw_compare.py`. Expect the HSE low-line OVER lane to shrink
     hard in TIGHT windows; watch whether edge5+ lift survives. Also consider an explicit edge/line floor on
     HSE OVER rescue regardless.
3. (Optional) production-faithful candidate pool: join real `ml_feature_store_v2.feature_quality_score` in the
   builder instead of 100.0, so `quality_floor` behaves as in production.
4. (Optional) Tier 1+2 multi-season extension for a non-anomalous-season BB-vs-raw read (raw ≈53%, where the
   pipeline's +13.7pp filter lift should be more visible than on 2025-26's already-78.9% raw).
5. Then the rest of the queued value work: low-line/low-var UNDER archetype gating, feature_scanner triage —
   plus the cross-BOOK candidates surfaced above (`bp_dropped_heavy_under`, `book_disagree_under`).
