# CLV validation — build scope

**Status:** SCOPED, not started. **Owner:** next session. **Created:** 2026-06-23 (session 4).
**Origin:** the one genuinely-unexplored high-value lever from the off-season research arc
(see `docs/09-handoff/2026-06-23-SESSION-4-frame-breaking-RESULT.md`). Everything else converged.

## Why this matters (the one-paragraph case)
Every edge we've validated this off-season was measured with **hit rate** — a high-variance
metric that needs a full season to trust, which is exactly why we keep fighting "is this real
or 2025-26 noise?" **Closing line value is far lower variance:** if our UNDER picks systematically
get a better number than the closing line, that confirms genuine edge with a fraction of the
sample. CLV is the single most reliable predictor of long-run betting profitability. It would
(a) independently validate-or-kill the UNDER+edge thesis, (b) give us a per-pick quality signal
that doesn't wait on graded outcomes, and (c) let us settle signal/selection questions in weeks
instead of seasons. It is also the natural follow-up to session 4's hint that **static-line picks
underperform (51.7% vs ~58%)** — there is market-information structure here to mine.

## What CLV is, precisely (get the sign right)
CLV = did we beat the closing number, in the direction we bet.
- **UNDER** at pick-line `L_pick`: positive CLV ⟺ closing line `L_close < L_pick` (line dropped
  toward the under after we bet). CLV points = `L_pick − L_close`.
- **OVER** at `L_pick`: positive CLV ⟺ `L_close > L_pick` (line rose). CLV points = `L_close − L_pick`.
- Positive average CLV across a pick set ⇒ we are systematically on the side sharp money moved
  toward ⇒ real edge. It should also correlate with HR (validation that CLV "works" here).

## Data: reconstruct the closing line (no closing column exists)
Production has NO closing-line column (checked: `prediction_accuracy` has only `line_value`,
`line_source`, `line_bookmaker`; no CLV table). BUT the raw odds snapshots support reconstruction:

- **Source:** `nba_raw.odds_api_player_points_props` — has `snapshot_timestamp`, `game_start_time`,
  `bookmaker`, `game_id`, player identity, the over/under line + prices, plus `bookmaker_last_update`.
- **Closing line per (game_id, player, bookmaker)** = the row with `MAX(snapshot_timestamp)` such
  that `snapshot_timestamp < game_start_time`. Then take a **cross-bookmaker consensus** (median
  line) to define the market closing line — mirror whatever consensus our pick-time line uses.
- **Pick-time line** = `prediction_accuracy.line_value` (the number we actually graded against),
  joined on `(game_date, player_lookup, system_id)` with the standard dedup. Use the BB picks
  (`signal_best_bets_picks`) for the picks-that-mattered view, and all graded predictions for the
  full-population view.

## ⚠️ Risks / unknowns to resolve in Phase 0 BEFORE building
1. **Snapshot coverage/sparsity.** Session-4 probe of `odds_api_player_points_props` (Nov-Feb)
   returned surprisingly few rows per `snapshot_tag` (tags are time-based like `snap-1431`, not
   semantic). MUST measure: of graded picks, what % have ≥1 snapshot with `snapshot_timestamp <
   game_start_time`? If <~70%, CLV is biased/unusable and this stops here.
2. **Timezone correctness.** `snapshot_timestamp` vs `game_start_time` must be the same tz (likely
   UTC) — a tz bug silently makes every snapshot "pre-tip" or "post-tip". Validate on known games.
3. **Bookmaker alignment.** The closing consensus should use the same book set as the pick-time
   line, else CLV measures book-disagreement not time-movement. Check `line_bookmaker`/`line_source`.
4. **Line vs price.** Props move on BOTH the line (24.5→25.5) and the price (−110→−130). v1 measures
   LINE CLV (the dominant effect); note PRICE CLV as a v2 refinement (session-4 showed price alone
   carries no usable signal, so line-CLV is the right v1 focus).
5. **Backfill depth.** Snapshots may only exist for recent seasons (the cache's pre-2025 enrichment
   is thin — see the 3 single-season-coverage artifacts). CLV may be a **2024-25 + 2025-26** result,
   not 5-season. That's still valuable (2 seasons of low-variance CLV >> 5 seasons of noisy HR).

## Phasing
- **Phase 0 — feasibility (half day, DO FIRST):** measure pick→snapshot join coverage by season +
  validate tz on a handful of known games. Gate: proceed only if coverage ≥~70% for ≥1 full season.
  Deliverable: a coverage report; STOP if it fails.
- **Phase 1 — single-season CLV (1 day):** `scripts/nba/training/discovery/clv_validation.py`.
  Reconstruct closing lines, join to 2025-26 picks, compute per-pick CLV. Report: mean CLV by
  direction; % positive-CLV; CLV vs HR calibration (do positive-CLV picks win more?); CLV by edge
  band and by signal tag.
- **Phase 2 — cross-season + by-signal (1 day):** extend to all seasons with snapshot coverage.
  Re-validate the durable UNDER signals (b2b_under, slow_pace_under, high_line_under, home_under)
  through CLV — a signal with both HR edge AND positive CLV is trustworthy; HR-only is not. This is
  the cross-validation payoff: confirm/kill the season-open slate with an independent low-variance lens.

## Definition of done
A `clv_validation.py` that, for any season window, reports per-direction and per-signal mean CLV +
%-positive + CLV/HR calibration, with the Phase-0 coverage caveat printed inline. Success = a clear
verdict on whether UNDER+edge picks beat the close cross-season. If yes, CLV becomes a per-pick
quality gate and ongoing validator; if no, it forces a hard rethink of the UNDER thesis.

## Explicitly OUT of scope
New markets/sports; model-feature work (proven done — error-decomposition); price-CLV v2;
real-time/production CLV monitoring (this is a research validation, not a pipeline).
