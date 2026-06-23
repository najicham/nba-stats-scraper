# Strategy: Improve the core, or expand to more markets/sports?

**Date:** 2026-06-20
**Method:** 52-agent workflow (`sports-expansion-strategy`) — 12 system-inventory agents, 28 opportunity
agents (one per sport×market), 8 adversarial verifiers on the top picks, a 3-lens strategy panel, 1
synthesizer. ~4.0M tokens. Read-only; grounded in this repo's code/docs; skeptical by design.

## Verdict: **IMPROVE THE CORE** (unanimous, high-confidence)

Harden the proven NBA points best-bets engine first. Keep the assists/rebounds data clock running as a cheap
option. **Build no new betting market and no new sport until a multi-season walk-forward proves post-vig
edge.** All three independent strategy lenses (pure ROI, effort/risk, competitive moat) reached `improve_core`
on their own.

### Why (the evidence)
- **The NBA points pipeline is the only asset in the estate with a proven, multi-month, post-vig edge:**
  2025-26 best-bets 415-235 (63.8%); filters add +13.7pp over the ~52-53% raw model; edge-5+ at 60-66%;
  top combos 74-83%.
- **Every one of the 28 candidate markets scored EV=low / edge=low**, and **all 8 adversarially-verified top
  picks resolved to `skip`** (one, MLB batter hits, was downgraded "overstated → skip"). Two reasons recur:
  (a) the markets are demonstrably efficient (the MLB 519K-row, 13-market scan found edge nowhere; the
  strikeout fork was a full build that ended a permanent NO-GO), and (b) the cost is near-greenfield, not a
  config flip.
- **The pipeline is structurally POINTS-LOCKED (code-verified):** `market_type='points'` is hardcoded in
  `feature_extractor.py` and `per_model_pipeline.py`, the training label is `pgs.points`, and there is no
  `market_type` dimension in `player_prop_predictions` or grading. So **assists/rebounds is a parallel
  modeling fork, not a label swap** — the assists/rebounds subsystem scored 12/100 maturity.
- **The core's recent failure is known and recoverable, not fatal:** Jan 73.8% → Mar 46.7% is stale models +
  scoring-regime shift + a fleet collapsed into LGBM/CatBoost clones (r=0.93-0.99). The edge-based auto-halt
  (`regime_context.py`, 7d avg edge < 5.0) already protects bankroll. Fixing this recovers real dollars on
  infrastructure that already exists — low effort, zero new services/schedulers/schemas.
- **Expansion is the opposite trade:** high effort (an MLB-clone-sized fork drove GCP ~$150 → ~$994/mo)
  against unproven, likely-zero edge behind a season-to-multi-season data wait. The project's documented
  failure mode — over-optimism on thin/contaminated samples that later reverses — argues directly against
  committing modeling effort to any market without a clean season-plus of labels.

## Ranked opportunities (all 28 → EV=low, every rec = skip/pilot)

| Score | Sport | Market | Rec | Data we have | Infra reuse | Effort |
|---|---|---|---|---|---|---|
| 9.7 | MLB | pitcher hits allowed | skip | have | 85% | L |
| 9.6 | MLB | pitcher outs recorded | skip | have | 80% | L |
| 9.1 | MLB | batter hits | pilot→skip | have | 55% | L |
| 8.6 | NBA | assists | skip | have | 55% | XL |
| 8.5 | MLB | batter RBIs | skip | have | 50% | XL |
| 6.1 | NBA | rebounds | pilot | partial | 45% | XL |
| 6.1 | NBA | threes / PRA combos | skip | partial | 45% | XL |
| 3.7 | NFL/NHL | pass/rush/rec yds, SOG, points, saves | skip | **none** | 35% | XL |
| 3.5 | Soccer | shots / shots on target | skip | **none** | 27% | XL |

The high "data we have" scores for MLB pitcher/batter markets reflect that the *plumbing* exists — but
verifiers confirmed the *edge* does not, and the markets are presumed efficient until proven. NFL/NHL/soccer
score lowest because we scrape **no** data for them — they're full new-sport builds.

## System inventory (maturity)
85 nba-model-fleet · 85 feature-store · 82 nba-signals · 80 odds-coverage · 72 pipeline-infra ·
72 scraper-inventory · 72 eval-foundation · 70 cost/ops · 62 publishing-frontend · 62 governance/monitoring ·
**45 mlb-system** · **12 nba-assists/rebounds**.

## What to DO — top improvements (all on the one proven asset)
1. **Recover the late-season collapse (effort M).** On the leak-clean walk-forward, verify that the
   late-season training cap (`cap_to_pre_late_season`) + 14-day retrain cadence (MEMORY: HR-equivalent, halves
   retrain cost) actually lift Mar/Apr edge-5+ HR. Largest recoverable profit lever. (experiment ≠ deploy →
   needs sign-off.)
2. **Reallocate volume into the edge-5+ money zone (effort S).** Raise the min pick threshold toward
   edge ≥ 3.0, keep the OVER floor at 6.0 (`aggregator.py:652`), tighten Ultra public exposure until N≥50.
   Edge-5+ is 60-66% BB HR (edge 7+ UNDER 18-0); edge 3-5 is net-negative (36-44%). Pure reallocation inside a
   fully-built pipeline.
3. **Build ONE structurally-different, accurate-at-edge-5+ model (effort L).** A non-tree functional form is
   the only genuine ML diversity lever left (GBDT/feature-set/MQ all confirmed clones) — it's what could
   revive cross-model signals `combo_3way`/`book_disagreement`. Meanwhile lean on `book_disagreement`
   (cross-BOOK, fleet-independent).
4. **Close coupling bugs (effort S).** `quick_retrain.py` eval hardcoded to `catboost_v9` (L569, forces
   `--no-production-lines`); `model_bb_candidates` writes 30/45 cols, 15 silently NULL (Task #39).

## What to KEEP as a cheap option (no model build)
- **NBA assists/rebounds DATA CLOCK** (~$5-15/mo): 4 schedulers live since 2026-04-06, BettingPros market IDs
  151/157, raw table ready. Keeping them firing accrues the season of lines+actuals that is the *only* thing
  gating a future multi-season backtest. Near-zero regret; preserves a real option.
- **NBA assists/rebounds INFO PRODUCT** (effort M, optional): the frontend pick contract is already
  stat-agnostic (`BestBetsPick.stat`, `stat-labels.ts` maps PTS/REB/AST/3PM). Ship lines/trends/projection-vs-
  line with **no edge claim** — mirrors the MLB-strikeout info-only template, deepens the NBA product.
- Optionally turn on one MLB batter-props scraper scheduler to *start* that clock (data only; no product).

## What to AVOID
- **No new BETTING market now** (NBA assists/rebounds/threes/combos; MLB batter hits/TB/RBI/HRR; pitcher
  hits/outs/ER) — all 8 verified picks → skip; markets efficient + pipeline points-locked = greenfield fork.
- **No new SPORT this horizon** (NFL/NHL/WNBA/soccer) — replays the full MLB clone (~5 Cloud Run services,
  ~12 schedulers, 4 cloudbuild YAMLs, forked retrain/decay/governance), ~$150→$994/mo, and still ended NO-GO.
- **Don't train on the ~3 playoff-biased weeks** of assists/rebounds history — thin, unrepresentative,
  manufactures a false positive (the recurring failure mode).
- **Don't re-run GBDT/feature-set/MQ-quantile diversity grids** (confirmed clones) or **re-pitch MLB
  strikeout betting** (settled NO-GO).
- **Don't relax the OVER floor (6.0)** or push volume into edge 3-5, and **don't demote filters on thin
  short-window CF HR**.

## Recommended sequence
1. (Now, off-season) Walk-forward-verify the late-season cap + 14-day cadence lift Mar/Apr edge-5+ HR →
   schedule for next-season adoption if confirmed (sign-off required).
2. (Now, low-effort) Reallocate volume to edge-5+; keep OVER floor 6.0; tighten Ultra exposure.
3. (Now, low-effort) Close the `catboost_v9` eval hardcode + `model_bb_candidates` NULL-column bugs.
4. (Off-season, cheap) Confirm assists/rebounds schedulers fire year-round; optionally add one MLB
   batter-props scheduler to start that clock. Build NO models/signals/market_type schema yet.
5. (Off-season, larger ML bet) Attempt one structurally-different non-tree model accurate at edge-5+; if it
   fails to de-correlate or fails edge-5+ accuracy, fall back to `book_disagreement`.
6. (Pre-season 2026-27) Re-run the leak-clean multi-season walk-forward to confirm 5-season signal HRs hold
   post-leakage-fix before trusting any weight.
7. (Feb-Mar 2027, gated) ONLY after a full 2026-27 season of assists/rebounds lines+actuals accrues, run a
   multi-season walk-forward; build a dedicated model + `market_type` plumbing ONLY if it clears ~53.5%
   post-vig. Earliest credible ship: Feb-Mar 2027.

---
*Generated by the `sports-expansion-strategy` workflow. Full structured result:
`tasks/w6ue6at4w.output` (transcript dir under the session's workflows/).*
