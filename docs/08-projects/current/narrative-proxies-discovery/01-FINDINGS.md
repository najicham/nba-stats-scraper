# Findings — Narrative/Emotional Proxy Discovery (Phase 0 + Phase 1)

**Date:** 2026-06-28 · **Status:** COMPLETE · Pre-reg: `00-PREREGISTRATION.md`
**Origin:** `docs/09-handoff/2026-06-28-narrative-news-factors-frontier.md`

## TL;DR

- **Phase 0 (news backfill feasibility): feasible but hard, game-day resolution only.** No off-the-shelf
  5-season point-in-time NBA news product exists. The "bad-press/benching blurb" modality is NOT
  backfillable → forward-collection only. **Recommendation: do NOT build a news scraper now.**
- **Phase 1 (6 pre-registered backfillable proxies): 0 pass — 5 FAIL, 1 INCONCLUSIVE.** The narrative
  proxies carry no standalone edge. Per the frontier doc's own logic ("if even the proxies show
  nothing, news scraping is unlikely to rescue it"), this further argues against the scraper build.
- **ONE survivor from the rubble (post-hoc, needs live confirmation):** national-TV / primetime games
  with a high line (≥22) → **UNDER ~54.7%, 5/5 seasons**, additive over the high-line baseline.
  This is a modest new UNDER candidate → stage SHADOW for 2026-27, do NOT deploy.

## Method (faithful to the discovery framework)

Standalone narrative bets graded vs the prop line. Population: `prediction_accuracy`,
`has_prop_line=TRUE`, deduped to one row per (player, game) = **72,340 player-games, 5 seasons
(2021-22…2025-26)**. Breakeven = 52.4%. Gates: BH-FDR (binomial vs 52.4%) + ≥3/5 seasons above
breakeven (N≥30) + bootstrap CI excluding breakeven. Triggers/directions pre-registered before results.

**Structural finding that frames everything:** the unconditional OVER-vs-line hit rate is only
**~48%** (UNDER ~52%) across all 5 seasons. Every OVER-direction bet fights a headwind; UNDER is the
structurally favored side. (Re-confirms "UNDER is the engine.")

## Phase 1 results (the 6 pre-registered triggers)

| ID | Trigger → bet | Pooled HR | N | Seasons >52.4% | Verdict |
|----|---------------|-----------|---|----------------|---------|
| H1 Stage | national-TV & line≥20 → **OVER** | 45.4% | 2427 | 0/5 | **FAIL** (inverts — see below) |
| H2 BouncebackAway | prior_pts ≤0.6×t10 & away → OVER | 48.6% | 3816 | 0/5 | **FAIL** |
| H3 BlowoutLossAway | prior margin ≤−20 & away → OVER | 50.1% | 3439 | 1/5 | **FAIL** |
| H4 BenchedBounce | prior_min ≤20 & t10_min ≥28 → OVER | 47.6% | 944 | 1/5 | **FAIL** |
| H5 Revenge | vs former team (≤2 seasons) → OVER | 51.3% | 835 | 2/4 | **FAIL** (decays 55.6→45.9) |
| H6 VSiNFade | game over_ticket% ≥65 → UNDER | 52.8% | 1050 | 1/1 | **INCONCLUSIVE** (2025-only, not sig) |

Notable: **the AWAY bad-game bounce-back OVER thesis did NOT replicate standalone** (48.6% = base
rate). The known "AWAY bounce-back 56.2%" must be definition/population-specific; betting OVER after a
poor away-eligible game has no edge vs the line. Revenge is real-sounding but decaying and unprofitable
(market prices it). Benched/blowout: nothing. VSiN only joined for 2025-26 (coverage gap pre-2025).

## The survivor: national-TV / primetime + high line → UNDER

H1 failed as registered (OVER) but **inverted hard and consistently**. Triage (post-hoc, treated as
hypothesis-generating, not a validated claim):

**Orthogonality — it is additive, not the high-line effect in disguise:**
| Cell | UNDER HR | N | seasons >52.4% |
|------|----------|---|----------------|
| natlTV & line≥20 (trigger) | **54.6%** | 2427 | 4/5 |
| NON-natlTV & line≥20 (high-line baseline) | 52.0% | 11177 | 2/5 |
| natlTV & line<20 (TV alone) | 51.6% | 9716 | 1/5 |
| NON-natlTV & line<20 (base) | 51.5% | 49020 | 2/5 |

The **conjunction** (national TV AND high line) gives +2.6pp over the nearest confound and is far more
consistent (4/5 vs 2/5). TV-alone and high-line-alone are both near-base.

**Robustness — stable, not knife-edge:**
| Variant | UNDER HR | N | seasons >52.4% |
|---------|----------|---|----------------|
| national_tv & line≥18 | 53.4% | 3030 | 4/5 |
| national_tv & line≥20 | 54.6% | 2427 | 4/5 |
| national_tv & line≥22 | **54.7%** | 1951 | **5/5** |
| national_tv & line≥25 | 54.6% | 1297 | 4/5 |
| primetime & line≥20 | 54.4% | 2140 | 4/5 |
| primetime & line≥25 | 55.3% | 1151 | 4/5 |

Holds across thresholds and both TV definitions. 2024-25 is the weakest season (~50–52.6%) but still
at/above breakeven except line≥25.

**Mechanism (plausible market story):** marquee/primetime games concentrate recreational money on
stars to go OVER ("watch X drop 40 on national TV"), inflating featured-scorer lines; meanwhile
marquee games trend toward tougher defense / slower, grind-it-out pace. Net → UNDER value on
high-line scorers. This is a genuine market-mis-weighting story (the frontier doc's bar), and an
UNDER signal (the engine's strong side).

**Status & next step:** post-hoc directional flip → NOT validated, NOT deployed. WIRED SHADOW for 2026-27.
- **Trigger:** `(has_national_tv OR is_primetime) AND line >= 22` → **UNDER**.
- **WIRED 2026-06-28 (shadow, zero pick impact):** `ml/signals/national_tv_under.py` →
  registered in `ml/signals/registry.py`, added to `SHADOW_SIGNALS` in `ml/signals/aggregator.py`
  (excluded from real_sc), NOT in `UNDER_SIGNAL_WEIGHTS`, registry stub in `shared/registry/signals.yaml`.
  Schedule broadcast flags plumbed into the live signal context via
  `ml/signals/supplemental_data.py` (`schedule_tv_map`, keyed by tricodes parsed from game_id since
  `nbac_schedule.game_id` is the 10-digit official id). Smoke-tested + `validate_signal_references.py` passes.
- **Promote** shadow→active only after live 2026-27 N≥30 at HR≥55% (clear of the 53.5% real breakeven):
  move out of `SHADOW_SIGNALS` + add to `UNDER_SIGNAL_WEIGHTS` (~1.5). Needs sign-off.
- Check overlap with existing `high_line_under` / `star_line_under` before wiring weight (it is
  additive over high-line in backtest, but confirm live it isn't redundant with what's already firing).

## Phase 0 detail (news backfill)

- **Twitter** prohibitive ($5k/mo+); **Bing News** retired (Aug 2025); **GDELT** has a timestamp
  leakage trap (only ~33% sub-day resolution; tone is document-level not per-player).
- **Best free path if pursued:** ESPN hidden API (`now.core.api.espn.com/v1/sports/news/{id}`) —
  true publish timestamps + native `athleteId`; ID discovery via Wayback CDX / Common Crawl.
- **Cheapest PoC:** backfill the official injury report via the `nbainjuries` package (MIT, exactly
  2021-22→present, 15-min timestamped snapshots) — structured, mandated, pre-game narrative we partly
  already own.
- **Verdict:** since the backfillable proxies showed nothing, defer the scraper. If the owner still
  wants the narrative modality, it's a forward-collection project starting 2026-27 (slow to validate).

## Dead ends logged (do not repeat)

Standalone narrative-OVER bets (bounce-back, blowout-loss, benched, revenge, stage-as-OVER) — all at
or below the ~48% OVER base rate. VSiN game-total fade as a player-prop UNDER proxy — underpowered /
coverage-limited. Milestone proximity — uncomputable (career totals only exist from 2021-22).
