# Handoff — Narrative proxies wave DONE; `national_tv_under` wired SHADOW

**Date:** 2026-06-29 · **Type:** Research + wiring (off-season) · **Branch:** `narrative-national-tv-under-shadow` (NOT merged to main)
**Prereg:** `docs/08-projects/current/narrative-proxies-discovery/00-PREREGISTRATION.md` · **Results:** `…/01-FINDINGS.md`

## What happened this session

Executed Phase 0 + Phase 1 of the narrative/news frontier (from `2026-06-28-narrative-news-factors-frontier.md`).

**Phase 0 — news-backfill feasibility:** feasible but HARD, game-day timestamp resolution only. No
off-the-shelf 5-season point-in-time NBA news product. Twitter prohibitive ($5k+/mo), Bing News retired
(Aug 2025), GDELT timestamp trap (~33% sub-day, doc-level tone). Best free path if ever pursued = ESPN
hidden API (`now.core.api.espn.com/v1/sports/news/{id}`, true timestamps + native `athleteId`) +
Wayback/Common Crawl for ID discovery; cheapest PoC = `nbainjuries` package (MIT, 2021-22→present,
15-min snapshots). **The bad-press/benching "blurb" modality is NOT backfillable → forward-collection
only. → DO NOT build a news scraper now.**

**Phase 1 — 6 pre-registered backfillable proxies** (standalone bets vs the line, 72,340 deduped
player-games, 5 seasons, breakeven 52.4%, BH-FDR + ≥3/5-season gate): **0 PASS — 5 FAIL, 1 INCONCLUSIVE.**
- Structural frame: unconditional OVER-vs-line is only **~48%** (UNDER ~52%) all 5 seasons → OVER bets
  fight a headwind; re-confirms UNDER is the engine.
- H1 national-TV+line≥20 OVER 45.4% (FAIL, inverts), H2 AWAY bad-game bounce-back OVER 48.6% (**did NOT
  replicate the known "AWAY 56.2%" standalone**), H3 blowout-loss-away OVER 50.1%, H4 benched-bounce
  OVER 47.6%, H5 revenge-vs-former-team OVER 51.3% (decays 55.6→45.9, market prices it), H6 VSiN
  over-ticket≥65 fade UNDER 52.8% (2025-only → INCONCLUSIVE, VSiN coverage gap pre-2025). Milestone
  DROPPED (career totals only exist from 2021-22 → uncomputable without look-ahead).

**The one survivor (post-hoc directional flip of H1):** **national-TV / primetime + high line → UNDER.**
- `(has_national_tv OR is_primetime) AND line≥22 → UNDER ≈ 54.7%` (N≈1,951), **above breakeven 5/5 seasons.**
- ADDITIVE, not the high-line effect in disguise: NON-natlTV line≥20 UNDER = 52.0% (2/5); natlTV
  line<20 = 51.6%; the **conjunction** carries the +2.6pp lift. Robust across thresholds (18→25:
  53.4-54.7%) and both TV defs. 2024-25 weakest (~50-52.6%) but ≥breakeven except line≥25.
- Mechanism: rec money piles on stars OVER in marquee games → inflated featured-scorer lines + tougher
  D/slower pace → UNDER value. A genuine market-mis-weighting story, on the engine's strong (UNDER) side.

## What got wired (this branch, SHADOW, zero pick impact)

New signal `national_tv_under`, following the `b2b_fatigue_under` template:
- `ml/signals/national_tv_under.py` — class (UNDER + (national_tv|primetime) + line≥22).
- `ml/signals/supplemental_data.py` — **plumbed schedule broadcast flags into the live signal context**
  (`schedule_tv_map`, keyed by tricodes parsed from `game_id` because `nbac_schedule.game_id` is the
  10-digit official id, NOT the `YYYYMMDD_AWAY_HOME` key the other tables use). Sets
  `pred['has_national_tv']` / `pred['is_primetime']`. **This is what lets the shadow signal actually fire.**
- `ml/signals/registry.py` — registered.
- `ml/signals/aggregator.py` — added to `SHADOW_SIGNALS` (excluded from `real_sc`).
- `shared/registry/signals.yaml` — `status: shadow` stub.

Verified: smoke test (fires UNDER+TV+line≥22, blocks OVER/low-line/non-TV), `in SHADOW_SIGNALS=True`,
`in UNDER_SIGNAL_WEIGHTS=False`, `py_compile` clean, `validate_signal_references.py` exit 0.

## State / next steps

- **Branch `narrative-national-tv-under-shadow` is pushed but NOT merged to main.** Push to main
  auto-deploys prediction-worker/coordinator (they watch `ml/`+`shared/`). The change is shadow / zero
  pick impact, so deploying is safe — **but merging is a deliberate step that needs owner OK.** To
  activate tracking in production: merge to main (auto-deploys), then the signal accumulates `national_tv_under`
  fires in `model_bb_candidates` / signal tracking over 2026-27.
- **PROMOTE criteria (season-open, needs sign-off):** after live 2026-27 N≥30 BB-level picks at HR≥55%
  (clear of the 53.5% real breakeven): remove from `SHADOW_SIGNALS` + add to `UNDER_SIGNAL_WEIGHTS`
  (~1.5). **First check overlap with `star_line_under` / `high_line_under`** — additive in backtest,
  confirm live it isn't redundant.
- Season-open shadow queue now: `b2b_fatigue_under`, `national_tv_under`, plus the staged-not-wired
  items from prior waves (CLV `line_converging_under`, `low_variance_under_block`, same-game co-dir
  Kelly haircut). Research is converged; the remaining work is LIVE EXECUTION + confirmation, not more
  cache-mining.

## Reusable gotchas (BQ)

- `nbac_schedule.game_id` = 10-digit official id (`0022400603`); `prediction_accuracy` /
  `player_game_summary` use `YYYYMMDD_AWAY_HOME`. Rebuild the key from `game_date` + tricodes to join.
- `prediction_accuracy.is_voided` is NULL in older seasons → `is_voided = FALSE` silently drops all but
  the latest season. Use `(is_voided IS NULL OR is_voided = FALSE)`.
- `bq` CLI hangs in this WSL env — use the Python BQ client (`PYTHONPATH=. .venv/bin/python3`),
  project `nba-props-platform`. Always partition-filter.
- Analysis script (reusable for re-test): `scratchpad/narrative_phase1.py` (scratchpad, not committed).
