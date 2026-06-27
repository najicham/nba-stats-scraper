# CLV validation — build scope

> ## PHASE 0 RESULT (2026-06-24) — CONDITIONAL GO (3 seasons, not 5)
> Feasibility check complete. Findings:
> - **`odds_api_player_points_props` is richer than feared:** 22.5M rows, has a `player_lookup`
>   column (direct join to `prediction_accuracy`, no name-mapping) and `minutes_before_tipoff`
>   (closing line = smallest positive value — no timestamp math). Reconstruction is easy.
> - **Coverage (graded pick → pre-tip snapshot):** 2023-24 **77%**, 2024-25 **77%**, 2025-26 **88%**
>   — all clear the 70% gate. **2021-22 absent; 2022-23 only 2.9% → EXCLUDED.** 5-season CLV is OUT.
> - **Granularity caveat:** pre-2025-26 has ~1 snapshot/game at **~T-2.2hr** (a near-close proxy that
>   misses the final ~2hr of movement); **only 2025-26 has to-the-tip granularity** (12 books, snaps
>   to/after tip). Pre-2025-26 CLV is therefore conservative.
> - **CLV is mechanically measurable:** pick-line vs close differs for **47-61%** of picks (mean move
>   0.41-0.70 pts, ~36% move ≥0.5) — if they'd been ~identical, CLV would be dead. They're not.
> - **Why it's still worth it:** the 3 usable seasons include **two NON-anomaly seasons** (2023-24,
>   2024-25), so we can test "do UNDER picks beat the close in *normal* seasons" — the exact
>   real-edge-vs-2025-26-noise question. **→ Proceed to Phase 1.** Validated recipe + first cut:
>   `scripts/nba/training/discovery/clv_validation.py`.

> ## PHASE 1 FIRST-CUT RESULT (2026-06-24) — CLV independently confirms the thesis
> edge3+ graded picks, median near-close line, by direction × season:
>
> | dir | 2023-24 | 2024-25 | 2025-26 |
> |---|---|---|---|
> | **UNDER mean CLV** | **+0.257** | **+0.199** | +0.632 |
> | **OVER mean CLV**  | **−0.087** | **−0.055** | +0.743 |
>
> - **UNDER beats the close in ALL THREE seasons (positive CLV incl. both NON-anomaly seasons)** ⇒
>   the UNDER edge is real, independently confirmed by a lower-variance lens — NOT a 2025-26 artifact.
> - **OVER gets a WORSE number than the close in both normal seasons (negative CLV), positive ONLY in
>   2025-26** ⇒ OVER-fragility independently re-confirmed via CLV (not HR). Same conclusion, new lens.
> - **CAVEAT — CLV is NOT yet a usable per-pick GATE:** within-direction, HR|+CLV ≈ HR|−CLV pre-2025-26
>   (sometimes inverted), because the pre-2025-26 "close" is a T-2.2hr proxy + a selection confound
>   (the model already picked high-HR spots). CLV validates the THESIS, not (yet) per-pick quality.
> - **Phase 2 (next session):** (1) true-close cut on 2025-26 ONLY (`minutes_before_tipoff <= 15`) to
>   test CLV-as-gate without the proxy; (2) CLV on actual best-bets picks (`signal_best_bets_picks`) by
>   signal tag — does each UNDER signal (b2b/slow_pace/downtrend/...) carry positive CLV?

> ## PHASE 2 RESULT (2026-06-25) — CLV is a usable per-pick gate on a REAL close; 4 UNDER signals independently trust-validated
> Extended `clv_validation.py`. Architecture: ONE 22M-row odds scan (`--build-cache`, background)
> materialises per-(game_date,player_lookup) median close at BOTH 0–180min (near) and 0–15min (true)
> to a local parquet; all reports join cheaply against it. 44,021 player-games cached; 2,828 have a
> true-close snapshot (effectively 2025-26 only — the lone to-the-tip season).
>
> **TASK 1 — true-close gate (2025-26, `minutes_before_tipoff ≤ 15`, N=1,155 edge3+ w/ true close):**
> With a REAL close (no T-2.2hr proxy) CLV *separates* — it is a usable per-pick screen:
>
> | dir / band | HR\|+CLV | HR\|−CLV | gap |
> |---|---|---|---|
> | UNDER edge3+ | **63.4%** (N=238) | **49.5%** (N=101) | **+14pp** |
> | UNDER edge5+ | 63.8% (N=130) | 55.6% (N=45) | +8pp |
> | OVER edge3+ | 66.9% (N=130) | 52.7% (N=93) | +14pp |
>
> UNDER CLV calibration (true close): `clv≤−0.5` → **43.9%** HR (N=82); `clv=0` → 60.0% (N=418);
> `clv>0.5` → 63.4% (N=202). **The value is the NEGATIVE tail:** a pick whose line moved against it
> by ≥0.5 pts by tip is a ~44% loser. ⇒ a live de-risk rule (drop/flag a pick if by tip the close has
> moved ≥0.5 against it) is supported. **This FLIPS the Phase-1 "not yet a gate" caveat — the proxy WAS
> hiding it; on a real close +CLV clearly beats −CLV.** CAVEAT: only demonstrable in 2025-26 (no
> true-close pre-2025-26); cross-season confirmation needs live 2026-27 true-close data. OVER's gate
> "works" too but only inside 2025-26 where OVER won — do NOT read it as OVER rehabilitation.
>
> **TASK 2b — candidate UNDER slate via CLV, reconstructed cross-season (near-close proxy, 3 seasons):**
>
> | signal | 2023-24 | 2024-25 | 2025-26 | verdict |
> |---|---|---|---|---|
> | `slow_pace_under` | +0.49 / 60.0% | +0.38 / 58.6% | +0.43 / 56.8% | **+CLV both normal seasons → TRUST** |
> | `ft_anomaly_under` | +0.34 / 58.8% | +0.23 / 56.8% | +0.32 / 63.2% | **TRUST** |
> | `downtrend_under` | +0.39 / 55.6% | +0.29 / 58.3% | +0.38 / 53.1% | **TRUST** (HR modest, CLV consistent) |
> | `high_line_under` | +0.36 / 59.3% | +0.24 / 59.3% | +0.32 / 61.7% | **TRUST** (consistent +CLV; magnitude modest) |
> | `b2b_fatigue_under` | n/a | n/a | +0.20 / 48.0% | **INCONCLUSIVE** — `back_to_back` unpopulated pre-2025 in cache; weak in its lone (known-weakest) testable season, N=25 |
> | `book_disagree_under` | N=0 | N=1 | +1.13 / 68.8% | **UNDERPOWERED** — prod predicate `multi_book_line_std≥1.0` is rare (N=17 total); +CLV where present |
>
> (cells = mean CLV pts / HR. Predicates mirror `shadow_backlog_gate.py`.) **4 of 6 slate signals carry
> positive CLV in BOTH non-anomaly seasons + positive HR → independent low-variance confirmation of the
> season-open UNDER slate.** b2b can't be CLV-tested from this cache (data gap, NOT a kill — keep the
> shadow→active plan, gate on live N≥30). book_disagree needs the multi-book feed live.
>
> **TASK 2a — CLV on actually-fired tags** (pick_signal_tags, exists 2026-02+ only → 2025-26-partial,
> the Mar-collapse window): every UNDER tag shows POSITIVE mean CLV (book_disagreement +3.41,
> ft_anomaly +0.58, slow_pace +0.57, downtrend +0.49) even as HR sagged (40–54%) — i.e. the picks kept
> beating the close while losing outright, consistent with the production-side (not model) March
> collapse. Directional only; do NOT demote on this N.
>
> **NET:** CLV independently (a) re-confirms the UNDER-edge thesis a 4th time, (b) trust-validates 4 of
> the 6 season-open UNDER signals cross-season, and (c) yields a NEW live tool — a negative-CLV de-risk
> screen — once 2026-27 supplies to-the-tip closes. Research arc is complete; rest is season-open exec.

**Status:** PHASE 0 + 1 + 2 DONE (2026-06-25). Off-season CLV research complete. **Created:** 2026-06-23 (session 4).
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
