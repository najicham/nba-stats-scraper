# Handoff — New frontier: narrative / news / emotional factors as a winning-pick edge

**Date:** 2026-06-28 · **Type:** Research-direction handoff (off-season) · **State:** NBA cache-mining research is CONVERGED (see below); this opens a NEW, genuinely-untested modality.

## Mission for the next session

Keep hunting for factors that flag a winning pick — **especially rare, situational, "only-happens-a-few-times-a-season" spots** — but on a frontier we have NOT touched: **narrative / news / emotional context.** The owner's thesis: after bad press, a benching, public criticism, a revenge spot, etc., some players are primed to bounce back (or collapse), and the market — which prices hard stats well — may under-react to the *soft, story-driven* information. We currently encode **zero** of this. That's the opportunity.

## The one finding that does NOT foreclose this (the intellectual core — read this)

Every prior "we're at the efficient frontier" conclusion rests on the **error-decomposition result**: held-out R² predicting the model's residual from *player/context features ≈ +0.004 ≈ 0.* People keep (correctly) citing this to kill new-feature ideas. **But that result is about the EXISTING 60 features** (box-score, matchup, market, team-context). News sentiment / narrative is **information that lives nowhere in the current pipeline** — it is outside that feature set, so it is NOT covered by "features are exhausted."

The honest counter-bar, though: the residual being ~white-noise from the model's view means *if narrative were strongly and obviously predictive, the market (which sets the line) would likely have priced it* — beat writers and sharp bettors read the same news. **So the real target is narrative information the market UNDER-weights or is slow on.** Markets are demonstrably slower on soft/narrative info than on hard injury/stat news. That's the seam. It is narrow, but it is real and untested.

## Hypotheses to pursue (rare/situational winning factors)

Narrative/emotional spots, roughly ranked by plausibility of a *market under-reaction*:

1. **Bounce-back after a "bad press" game** — blowout-loss, public benching/DNP-CD, a viral bad performance, trade-rumor week. Does the player over-produce next game? (We already know **box-score bounce-back is AWAY-only: bad miss + away = 56.2%, home 47.8%** — narrative may add resolution to *which* bad games trigger it.)
2. **Revenge / motivation spots** — first game vs a former team (trade/FA departure), first game after being benched, "they said I couldn't" press cycles.
3. **Stage/spotlight games** — nationally-televised / primetime / marquee matchups; some players elevate for the big stage. (Partly backfillable from schedule broadcast flags.)
4. **Contract-year / milestone chases** — approaching a career mark, contract year, free-agency audition. (Milestones backfillable from career stats; contract status needs external data.)
5. **Adversity inversion (the owner's specific idea)** — bad press / criticism *brings out the best* in specific player archetypes. This is a player×narrative INTERACTION (some players sulk, some respond) — likely needs a per-player or per-archetype response profile.

Each hypothesis should resolve to: **direction (OVER/UNDER), the trigger definition, and the cross-season hit rate vs the edge-matched baseline** — same discipline as every prior signal.

## Smart attack order — de-risk BEFORE you build a scraper

The binding constraint is **historical backfill**: news is point-in-time, and you cannot easily reconstruct "what was being written about player X the night before a 2022 game." Backtesting 5 seasons of news is the hard part, not the sentiment analysis (LLMs make that cheap now). So attack in this order:

**Phase 0 — Feasibility (do this FIRST, ~1 session).** Can point-in-time news be backfilled at all? Investigate: historical news archives with timestamps (GDELT, news APIs with date filters, Reddit/r-nba pushshift-style archives, beat-writer RSS archives, theScore/ESPN article timestamps). If 5-season point-in-time backfill is **infeasible**, the only path is **forward-collection** — start scraping now, accumulate, and validate live over 2026-27+ (slow, but the owner explicitly wants this regardless). Decide this before writing any scraper.

**Phase 1 — Backfillable narrative PROXIES (cheap, no scraping, HIGH VALUE).** Many "emotional" triggers have hard-data proxies already in the cache — test these first. If even the proxies show nothing, news scraping is unlikely to rescue it; if they show something, news adds resolution and the scraper is justified:
- Bad-game bounce-back: prior-game blowout-loss / season-low minutes / DNP-CD → next-game OVER/UNDER (extends the AWAY-56.2% finding).
- Revenge: player facing a former team (needs player→team history — partially derivable from roster/gamelog history).
- Stage games: national-TV / primetime flags from `nba_raw.nbac_schedule` (check for broadcast columns).
- Return-from-absence "statement" games: backfillable from game gaps + injury report.
- Milestone proximity: approaching round-number career marks (backfillable from career totals).
These are runnable on the existing cache with the standard ≥3/5-season pre-registration. **This is the recommended first real test wave.**

**Phase 2 — News scraping + LLM sentiment (ONLY if Phase 0 says backfillable AND/OR Phase 1 warrants).** Build a news scraper into the existing scraper architecture (`scrapers/`), run articles through an LLM for player-level sentiment / narrative tags (criticism, hype, trade-rumor, revenge-framing, confidence), join to predictions, validate. This is the expensive build — earn it with Phase 0/1 first.

## Data sources & infra

- **Existing scraper architecture:** `scrapers/` (40+ scrapers → GCS JSON → BQ raw). A news scraper fits here; follow the ConfigMixin/`resolve_today()` patterns and the deploy flow. External-analytics scrapers live in `scrapers/external/`.
- **Already-scraped narrative-adjacent data:** `nba_raw.nbac_injury_report`, `nba_raw.rotowire_lineups` (+ RotoWire news), `nba_raw.nbac_schedule` (broadcast/rest), `nba_raw.covers_referee_stats`, `nba_raw.vsin_betting_splits` (public sentiment proxy!). VSiN public-betting % is itself a crude "narrative/public-perception" signal already in the cache — cheap to test.
- **Sentiment analysis:** LLM-based (cheap, high quality now). Tag at the (player, date) grain, timestamped PRE-game.
- **Candidate news sources:** ESPN, theScore, RotoWire, beat-writer RSS, r/nba, X/Twitter. Mind ToS and historical-access limits (that's the Phase-0 question).

## Methodology discipline (non-negotiable — this is where narrative research dies)

1. **Look-ahead is lethal here.** News/sentiment MUST be timestamped strictly BEFORE tip. A post-game recap leaking into a "pre-game" feature will manufacture a fake edge instantly. Verify timestamps obsessively.
2. **Narrative is a story-generator → maximum overfitting risk.** It is trivially easy to find a post-hoc "revenge game" story for any outcome. Pre-register the trigger definition and direction BEFORE looking at results. BH-FDR across hypotheses.
3. **Cross-season ≥3/5 gate is mandatory** (kills 2025-26 artifacts). If forward-only (Phase 0 infeasible), pre-register and accept it can't promote until live N accumulates.
4. **The market-under-reaction bar:** a narrative that the market already prices is worthless. Where possible, check the signal against line movement (does the line already reflect the story?).
5. **Experiments are not deploys.** Same governance as everything else — nothing ships without owner sign-off; stage in SHADOW first.

## Honest risk assessment

- **Most narrative edges are priced in.** Revenge games and bounce-backs are the *most-discussed* angles in sports media; the market is not naive about them. The win, if any, is in *which* narratives the market under-weights and *which player archetypes* actually respond.
- **Backfill is the real wall.** If Phase 0 says no historical news, this becomes a multi-season forward-collection project — worth starting, but slow to validate.
- **But it is genuinely new.** Unlike the last several research waves (which re-mined an exhausted cache), this is a new information modality not covered by the residual-R²≈0 finding. That alone makes it the most interesting open direction. Pursue it — disciplined.

## Current converged state (context so you don't re-mine dead ends)

**Read `MEMORY.md` → "Strategic Direction" + these memory files first:**
- `confidence-surface-exploration-2026-06-27.md` — the imagination→testing sweep; edges live on the confidence/selection surface, not point accuracy.
- `research-wave1-results-2026-06-27.md` — 6+2 pre-registered tests, 0 deploy-ready; the full dead-end list and the 3 staged-for-live items.

**DEAD ENDS — do not repeat:** new point-model features (residual R²≈0 *for existing modalities*); GBDT/feature-set/algo model diversity (clones); MQ/quantile head; structurally-diverse-model build (combo_3way is single-model, verified); fleet-disagreement trust filter (edge proxy, inverts); roster zero-sum / teammate hedge (priced, ρ≈0); drawdown seasonal stop; bias-velocity collapse siren (fires late); abstention-as-alpha; low-σ "Sharpe" volume gate (inverted — low-σ UNDER is the *worst*). External-projection agreement (10% BB HR).

**STAGED FOR SEASON-OPEN (all shadow, live-gated, none deployed):** (1) CLV `line_converging_under` flag; (2) `low_variance_under_block` filter (σ<4.5, regime-dependent — note: low-σ low-edge UNDER is a *block* candidate, the inverse of a bet); (3) same-game co-directional Kelly haircut.

**WHAT WORKS (the engine to protect):** UNDER + edge + signals (UNDER edge≥6 ≈61% cross-season). OVER is a 2025-26 scoring anomaly — never assume OVER is profitable. Edge-based auto-halt is the vindicated collapse guard.

**Env/schema gotchas:** `bq` CLI HANGS in this WSL env — use the Python BQ client (`PYTHONPATH=. .venv/bin/python3`), project `nba-props-platform`. Always partition-filter. `prediction_accuracy`: NO `edge` (compute ABS(predicted_points−line_value)), NO `hit` (use `prediction_correct`); filter has_prop_line=TRUE, recommendation IN OVER/UNDER, prediction_correct NOT NULL. `player_prop_predictions` line = `current_points_line`. **Real best-bets picks (`signal_best_bets_picks`) are EMPTY before 2026-01-09** — pre-2026 backtests must use a champion-system edge≥3 proxy (label it). Breakeven HR ≈ 52.4%. Cross-season = 2021-22 … 2025-26.

## Recommended first move for the new chat

Start with **Phase 0 (news-backfill feasibility)** and **Phase 1 (backfillable narrative proxies — lead with the bad-game bounce-back extension and national-TV/stage-game test)** in parallel. Do NOT build a news scraper until Phase 0 confirms it's backtestable or the owner commits to forward-collection. Pre-register every trigger. Bring back real numbers + the standard PASS/FAIL/INCONCLUSIVE verdicts.
