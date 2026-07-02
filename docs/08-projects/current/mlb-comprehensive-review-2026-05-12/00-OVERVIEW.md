# MLB Comprehensive Review — 2026-05-12

**Investigation:** 20 parallel agents auditing the MLB UNDER shadow rollout plan + the walk-forward auditability proposal, plus 10 open-ended lanes generating new improvement ideas.
**Predecessor projects:**
- `docs/08-projects/current/mlb-under-shadow-rollout/` (6-agent investigation, plan-stage)
- `docs/08-projects/current/mlb-improvements-2026-05/` (23-agent broader MLB review, plan-stage)

**Status:** Review complete. 5-agent follow-up review complete. No code shipped. **Canonical action plan is `05-REVISED-PLAN.md`** (supersedes `03-RECOMMENDED-PLAN.md` after follow-up review found a fatal flaw in original A1).

## Critical update from 5-agent review

**Agent D's BQ check revealed Lane 16's "30-minute lineup feature wire-up" is vapor.** Five of six "already-computed" features (`f26`, `f27`, `f33`, `f34`) are 0.0 constants across all 976 rows of `mlb_precompute.pitcher_ml_features`. The sixth (`f25`) fires only 12% of the time. Wiring them into the model would ship placeholders, not features. The upstream `lineup_k_analysis` precompute is not producing values. This downgrades A1 from "ship first" to "investigate upstream first, defer feature wire-up indefinitely."

The five agents converged on a revised sequencing: **A4 (Poisson) ships first**, with A2/A3/A5 in parallel as code/config-only. A1 is removed from Phase A; replaced by X1 (upstream pipeline investigation).

## Headline

**The shadow rollout plan as drafted has three plan-killing problems AND it's chasing the wrong opportunity.** Several agents independently converged on much bigger wins sitting in plain sight — chiefly 6 lineup features the precompute pipeline already pays to produce that are silently discarded before reaching the model.

## Plan-killers found

1. **Graduation gate is statistically incapable of distinguishing signal from noise.** Wilson 95% lower bound for N=60 at exactly 56% HR is 43.4% — below breakeven at -110 vig. The "monthly bucket ≥ 50% at N=10" gate has near-zero statistical power. (Lane 1)
2. **Both proposed UNDER filters are overfit.** `elite_k9_under_block` shows 96.9% → 65.2% cross-season collapse and the plan re-frames the collapse as justification. Ship as OBSERVATION-ONLY, not ACTIVE blocks. (Lane 2)
3. **Engineering hazards.** Existing `_write_shadow_picks` at `best_bets_exporter.py:1020` issues unscoped DELETE — new `under_shadow` writer will mutually annihilate blacklist rows unless retrofitted in the same PR. (Lane 3)

## Top opportunities the plan missed

- **6 lineup features (`f25`-`f34`) are already computed and discarded.** Wiring them into `CATBOOST_V2_FEATURES` + retrain is a 30-minute edit. (Lane 16 — biggest single finding)
- **OVER ranking is inverted.** Edge 0.5-0.99 = 59% HR (N=295). Edge 1.0-1.49 = 43.75% HR (N=48). Current sort_key ranks edge DESC, preferring losers. (Lane 14)
- **Poisson loss > Quantile loss.** Single-line model change gives a calibrated `p_over` for free via Poisson CDF, replacing the decorative `SIGMOID_SCALE=0.7` hack. (Lane 12)
- **Weather scraper built, never scheduled.** `mlb_weather` table has zero rows since season start — two weather signals silently dead. (Lane 17)
- **Early-warning could have fired April 28 instead of May 12** — 14 days late. (Lane 19)
- **MLB has no CLV tracking.** ~7h to ship a closing-line table + CLV columns. Leading indicator that would have caught the May collapse ~10 days early. (Lane 18)

## All 5 verified numerical claims from prior investigation are CORRECT (Lane 7)

| Claim | Result |
|---|---|
| 2026 UNDER overall N=204, HR=53.4% | CONFIRMED exact |
| May 2026 UNDER N=66, HR=40.9% | CONFIRMED exact |
| Week May 11-17 UNDER 0/3 | CONFIRMED exact |
| Edge ≥1.0 UNDER 2026 N=8, HR=100% | CONFIRMED exact |
| UNDER bias -0.45 K | CONFIRMED (-0.446) |

The DIRECTIONAL motivation for keeping UNDER disabled is statistically real. The PLAN built on top of that motivation has structural problems.

## Files in this project

- `00-OVERVIEW.md` — this file
- `01-AGENT-FINDINGS.md` — distilled report from all 20 agents (preserved evidence trail)
- `02-SYNTHESIS.md` — cross-cutting analysis: plan-killers, opportunities, contradictions
- `03-RECOMMENDED-PLAN.md` — initial re-sequenced action plan (SUPERSEDED by 05)
- `04-FINAL-REVIEW.md` — 5-agent review that uncovered the A1 vapor finding
- `05-REVISED-PLAN.md` — single-week execution plan (after both rounds of review)
- **`06-MULTI-SESSION-ROADMAP.md` — CANONICAL multi-session plan tackling all clusters across ~12 weeks**

## Decision pending — see `05-REVISED-PLAN.md`

The original shadow rollout plan must not ship as-drafted. The 5-agent follow-up converged on a revised sequence in `05-REVISED-PLAN.md`:

- **A4 Poisson loss retrain (walk-forward only — no deploy without approval)**
- **A2 OVER ranking fix (code-only, can ship same day)**
- **A3 weather + 2nd pre-game export (config-only)**
- **A5 CLV tracking foundation (promoted from B2 — Phase C decision needs it)**
- **X1 lineup pipeline upstream investigation (background, replaces vapor A1)**
- **B1 early-warning detector (next week, after backtest validates false-positive rate)**

User decisions needed: approve A4 walk-forward run; approve A2/A3/A5 to ship in parallel; approve X1/X2 diagnostic. Phase C/D are decisions for Week 3 after Phase A is measured — no commitment needed now.
