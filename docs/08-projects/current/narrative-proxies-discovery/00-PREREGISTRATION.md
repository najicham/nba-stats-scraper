# Pre-Registration — Narrative/Emotional Proxy Signals (Phase 1)

**Date:** 2026-06-28 · **Status:** PRE-REGISTERED (written before any hit rates were computed)
**Origin:** `docs/09-handoff/2026-06-28-narrative-news-factors-frontier.md`

## Why pre-register

Narrative research is a story-generator — it is trivial to find a post-hoc "revenge" story for any
outcome. Per the frontier doc's methodology section, trigger definitions and bet directions are
committed HERE, before results are seen. We run the tests exactly as written, once, and report
PASS / FAIL / INCONCLUSIVE. No trigger re-definition based on results (that would be p-hacking).

## Framing

**Standalone narrative bet (framing B).** For each trigger, when it fires we "bet" the pre-registered
direction and grade the player's actual points vs the prop line. This is the cleanest test of "does
this narrative context carry information the line under-weights." (This is the same framing as the
known **AWAY bad-game bounce-back = 56.2%** finding.) If a standalone rule clears breakeven
cross-season, signal-integration with model picks (framing A) is a follow-up — but if it can't clear
breakeven standalone, it won't help as a signal either.

## Population & grading

- Source: `nba_predictions.prediction_accuracy`, `has_prop_line=TRUE`, `actual_points NOT NULL`,
  `line_value NOT NULL`, `is_voided=FALSE`. Deduped to one row per (player_lookup, game_id).
- Outcome: `over_hit = actual_points > line_value`; `under_hit = actual_points < line_value`;
  pushes (actual == line) excluded.
- Seasons: 2021-22 … 2025-26 (5), season_year = month>=10 ? year : year-1.
- **Breakeven = 52.4%** (-110 vig). A trigger must beat this, not just 50%.
- Within-population unconditional OVER/UNDER rate reported alongside each trigger as a sanity baseline
  (lift over "just bet every over").

## Gates (must pass ALL to be VALIDATED)

1. BH-FDR significant across the 6 tests (α=0.05), binomial vs 52.4%.
2. Cross-season consistency: ≥3/5 seasons above 52.4% among seasons with N≥30.
3. Pooled HR point estimate above 52.4% with bootstrap CI excluding 52.4%.

Verdicts: **VALIDATED** (all gates) / **MARGINAL** (FDR-sig but consistency or CI fails) /
**FAIL** (below breakeven) / **INCONCLUSIVE** (underpowered, N too small).

## The 6 pre-registered triggers

| ID | Trigger (per player-game) | Bet | Thesis |
|----|---------------------------|-----|--------|
| **H1 Stage** | `has_national_tv = TRUE` AND `line >= 20` (featured scorer) | OVER | Stars elevate on the big stage; market under-prices spotlight bump |
| **H2 BouncebackAway** | `prior_game_pts <= 0.6 * trailing10_avg_pts` (and trailing10_avg_pts >= 10) AND current game AWAY | OVER | Adds "how bad" resolution to the known AWAY-56.2% bounce-back |
| **H3 BlowoutLossAway** | `prior_game_team_margin <= -20` AND current game AWAY | OVER | Blowout-loss embarrassment → away bounce-back |
| **H4 BenchedBounce** | `prior_game_minutes <= 20` AND `trailing10_avg_minutes >= 28` (DNP/benching for a normal starter) | OVER | Statement game after an unusual benching |
| **H5 Revenge** | opponent is a team the player last played for within the prior 2 seasons (former team) | OVER | Revenge/motivation vs former team |
| **H6 VSiNFade** | game `over_ticket_pct >= 65` (public loves the over) | UNDER | Fade lopsided public sentiment on the game total |

**Notes / known limitations committed up front:**
- Milestone proximity (career-mark chases) was DROPPED: career totals only exist from 2021-22 in the
  warehouse, so a player's true career cumulative is unknown → uncomputable without look-ahead/error.
- H1 stage: national-TV N is small in 2021-22/2022-23 (~101 games/season) → may be INCONCLUSIVE early.
- H5 revenge: 2021-22 is the first warehouse season, so "former team" history is shallow that season
  (can only see teams since Oct 2021) → expect weak early-season N; judged on later seasons.
- VSiN is game-level only (no player-prop split) → H6 is a coarse public-sentiment proxy.
- All triggers use strictly pre-game info (prior games, schedule, line). No post-game leakage.
