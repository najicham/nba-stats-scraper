# Handoff — NBA vegas-line look-ahead leak: fix + re-backfill

**Date:** 2026-05-22 · **Type:** single scoped fix
**Related:** `docs/08-projects/current/mlb-lineup-early-hook/03-FINDING-market-is-efficient.md`
(the MLB project conclusion that prompted this audit) · auto-memory `nba-feature-leak-audit.md`

---

## 0. Orientation — the one task

A 6-agent look-ahead-leak audit of the **NBA** feature pipeline (2026-05-22) found the
pipeline is **mostly clean** — but surfaced **one confirmed leak**: the vegas line feature
(`feature_25`) pulls **post-tipoff / in-game** odds snapshots. This handoff is to **fix
that one leak and re-backfill** the affected feature-store rows. Nothing else from the
audit needs action — §2 lists what was already verified clean so you don't re-audit it.

---

## 1. The finding — confirmed leak

**`feature_25` (vegas_points_line) is contaminated with in-game odds.**

In `data_processors/precompute/ml_feature_store/feature_extractor.py`, the method
`_batch_extract_vegas_lines` (defined ~line 951) selects the latest odds snapshot by
`ORDER BY ... snapshot_timestamp DESC` with **no `minutes_before_tipoff >= 0` filter**.
The raw table `nba_raw.odds_api_player_points_props` contains **post-tipoff / in-game
snapshots** (27,106 rows with `minutes_before_tipoff < 0` in Feb 2026 alone, down to
−116 min). The `DESC` sort actively prefers the latest snapshot, so when an in-game
snapshot exists the feature grabs a **line set while the game was already being played** —
a line that already reflects how the game is going.

The same defect is in the `dk_closing` CTE (~line 2389) that feeds **feature 60**
(`line_movement_direction`) — its "closing line" is literally the latest snapshot
regardless of tipoff.

**Quantified (Feb 2026, N=2,675 player-games):** ~266 selected a post-tipoff row; **195
ended up with a line different from the correct latest pre-tipoff line** (avg abs diff
0.27 K... points; max larger).

**Leak class:** form C (post-game data in a pre-game feature) + form D (train/serve skew —
historical feature-store rows are contaminated, but live serving is clean because no
post-tip snapshot exists *before* tipoff).

**Affected features:** 25 (`vegas_points_line`), 27 (`vegas_line_move`, derived from 25),
60 (`line_movement_direction`). Feature 61 (`vig_skew`) was flagged SUSPICIOUS — re-check
it. Feature 63 (`late_line_movement_count`) is **already correct** — its query (lines
~2450-2458) filters `minutes_before_tipoff IS NOT NULL AND minutes_before_tipoff <= 240`.
**Copy that pattern.**

**2022-23 caveat:** `feature_25` for 2022-23 was backfilled from `prediction_accuracy`,
and `minutes_before_tipoff` was 100% NULL in 2022 / 24% NULL in 2023 — so those rows
**cannot be confirmed pre-game and cannot be perfectly cleaned.** See §5.

---

## 2. What the audit already verified CLEAN — do NOT re-audit

The 6-agent audit (full detail in auto-memory `nba-feature-leak-audit.md`) checked the
whole pipeline against a 4-form leak taxonomy. Clean, with evidence:

- **Phase 3 analytics** — every rolling window strictly `game_date < target`.
- **Phase 4 precompute** — head-to-head / matchup history verified leak-free by direct
  row inspection.
- **Feature-store rolling features** — features 0, 1, 55, 56 etc. all strictly prior-game.
- **External-data & projection joins** — NBA external tables are daily point-in-time
  snapshots joined with a correct `MAX(game_date) <= target` as-of pattern, and they feed
  only the signal layer, not the model. (This is *not* the MLB bug class.)
- **Training assembly** — column-based, same path as serving; no target bleed.
- **The Session 458 leak is fully fixed** — verified: `feature_0` correlates 0.68-0.72
  with same-game actuals across all seasons (a residual leak would show ≥0.95).

The vegas line is the **only** open finding.

---

## 3. The fix

Small, surgical. In `data_processors/precompute/ml_feature_store/feature_extractor.py`,
add a pre-tipoff filter to the odds-snapshot selection in **both** leaky queries:

1. `_batch_extract_vegas_lines` (~line 951+; the snapshot pick the audit flagged near
   line 1021).
2. The `dk_closing` CTE (~lines 2389-2401; audit flagged ~lines 2385, 2398).

Add `AND minutes_before_tipoff >= 0` (at-or-before tipoff; `< 0` = in-game) to the
`WHERE` of each odds query so the `snapshot_timestamp DESC` pick can only ever land on a
genuine pre-tipoff snapshot. **Line numbers are from the audit and approximate — verify
against the live code; feature 63's query is the working reference pattern.** Also
re-check feature 61 (`vig_skew`) while you are in that code.

Decide `>= 0` vs `> 0` for a snapshot exactly at tipoff — `>= 0` (at-or-before) is the
intended behavior.

---

## 4. Re-backfill

After the code fix, the historical `nba_predictions.ml_feature_store_v2` rows still hold
the contaminated values — they must be recomputed. Re-run the feature-store extractor in
backfill mode (`_batch_extract_vegas_lines` takes a `backfill_mode` arg; there is also a
standalone `backfill_feature_store_vegas.py`, though it sources a different path — confirm
which path actually writes `feature_25_value` before relying on it).

- Scope: re-backfill the vegas-category columns (features 25, 27, 60, and 61 if changed)
  for **2024-01-01 → present** (the range with reliable `minutes_before_tipoff`).
- This is a data operation — size it and watch BQ cost.

---

## 5. The 2022-23 decision (needs the owner)

2022-23 `feature_25` rows cannot be perfectly cleaned (`minutes_before_tipoff` mostly
NULL). Options — pick one with the owner:
- **Accept** — leave 2022-23 as-is; flag it as a known soft spot.
- **Exclude** — drop 2022-23 from training windows.
- **Best-effort** — re-derive from `upcoming_player_game_context` (a pre-game table) where
  possible.
Recommendation: lean **exclude** for any new training, since the project already retrains
on rolling recent windows and 2022-23 is old.

---

## 6. Verification (pre-registered)

Before the fix, run this to lock the baseline magnitude; after the fix + re-backfill,
re-run to confirm it is resolved:

For game_dates 2026-01-01..2026-02-28, per player-game compute `line_pre` = latest
`odds_api_player_points_props` snapshot with `minutes_before_tipoff >= 0`, and
`line_stored` = `ml_feature_store_v2.feature_25_value`.
- **Leak present if:** `COUNTIF(ABS(line_stored - line_pre) > 0.5) / COUNT(*) > 1%`
  **AND** mean(`actual_points` − `line_stored`) for the differing rows is significantly
  closer to 0 than for clean rows (post-tip lines track outcomes — this proves it is a
  *predictive* leak, not just a line difference).
- **Pass after fix:** that differing-rows fraction drops to ~0.

---

## 7. Severity — what this does and does not mean

**Real, worth fixing — but modest. NOT a results-overturning leak.** ~7% of player-game
rows, ~0.27 avg line error.
- The **live 63.8% best-bets record stands** — live picks were generated *before* games
  with clean pre-game lines (no post-tip snapshot exists yet at serve time).
- The leak contaminates **model training data** and any **backtest that reads the feature
  store** — those run slightly optimistic. After the fix, expect walk-forward / backtest
  numbers to come in marginally lower and *more honest*.
- Vegas is the model's strongest feature category, which is why it rates attention — but
  the magnitude is small. Do not over-react.

---

## 8. Deploy / operational notes

- `feature_extractor.py` is in the NBA precompute pipeline. Pushing to `main`
  auto-deploys the affected service — keep the commit deployable.
- The fix (code) and the re-backfill (data) are separate steps. Land + deploy the code
  first, verify a fresh feature-store run is clean, then re-backfill history.
- Consider a guard: the repo already has a `check_date_comparisons` pre-commit hook (from
  the Session 458 fix). A similar hook asserting odds queries carry a
  `minutes_before_tipoff` bound would prevent regression.

---

## 9. Out of scope / already done

- **MLB pitcher-strikeout project is concluded** (efficient market, no edge) — see the
  finding doc referenced at the top. Nothing to do there; MLB output stays halted.
- The other 5 audit slices are verified clean (§2) — do not re-audit them.
- This handoff is one scoped fix: fix the filter, re-backfill, verify. That's it.
