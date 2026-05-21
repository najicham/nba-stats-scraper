# MLB Pitcher-Props Project — Execution Plan

**Created:** 2026-05-20 · **Rewritten:** 2026-05-21 (post-validation strategic pivot).
**Status:** Strategic pivot — the founding thesis was refuted by a leak-free validation.

This doc is "what to do next." The old machinery/features plan and the specs
`00-PROJECT-SPEC.md` / `01-DISCOVERY-HARNESS-SPEC.md` are **superseded** — see "Retired".

---

## Where we are (2026-05-21)

A full leak-free validation of the pitcher-strikeout system is complete. It overturned
the project's founding thesis.

- **Phase 0 — DONE.** MLB lineup capture (broken all of 2026, ~0% night-game coverage)
  fixed and verified — `mlb-lineups-afternoon`/`-overnight` schedulers + a dedup-guard
  fix (`eb056db4`).
- **A critical look-ahead leak was found and fixed.** `fangraphs_pitcher_season_stats`
  held only post-season snapshots; a same-season join leaked completed-season FIP/swstr/
  csw into mid-season games — ~23% of model feature importance. Fixed: prior-season join
  across 9 files + a `pitcher_game_summary` backfill (`a490ddc2`, `e1c7a667`).
- **A leak-free validation harness was built** — `season_replay.py` (rewired) +
  `calibration_report.py`. This is the project's durable asset.
- **The validation verdict (2 seasons × 5 seeds, 20-agent reviewed):**
  - The de-leaked model has **no real edge over the market** — 2024 model MAE 1.787 is
    *worse* than the line (1.763); 2025 barely wins. The handoff's "model matches market
    1.83 vs 1.85" was the *leaked* model.
  - The betting machinery has **no profit leak** — Poisson `p_over` ≈ the old sigmoid,
    the model-market blend hurts, signal-rescue is marginal, per-signal pruning yields
    nothing, UNDER needs a build with no evidence it pays.
  - The backtest's +3–7% ROI is **optimistic** — it used different-book aggregated odds
    and a look-ahead `innings_pitched≥3` filter. Realistic ≈ breakeven.
- **10 commits, none pushed.**

## What changed — the strategic pivot

The founding thesis ("the model matches the market; the betting machinery leaks the
value; fix the machinery, add features second") was **built on the leaked model** and is
**refuted**. The real finding:

> **You cannot out-predict an efficient market with public data.** The model ≈ the
> market because both use the same public stats (FanGraphs, Statcast, box scores).
> Starter-strikeout props are a heavily-modeled, efficient market. Better features,
> probability, or machinery can only *harvest* an edge — they cannot *create* one.

The project pivots from **out-modeling the market** to **finding an edge that can
structurally exist**, judged by the only honest scoreboard: **closing-line value (CLV)**.

---

## The new sequence

Legend: `[x]` done · `[~]` in progress · `[ ]` todo. Critical path: **A → B → C**.

### Phase A — Correctness (gate before the system places further bets)

| | Item | Effort | Notes |
|--|------|--------|-------|
| `[x]` | Leak fix + leak-free validation harness | — | `a490ddc2`,`8b074f63`,`13d0185f`,`e1c7a667` |
| `[ ]` | Push the 10 commits, then immediately retrain leak-free + shadow + promote | Med | The live model trains on leaked data — a real bug. Pushing the leak-fix code alone leaves a leak-trained model serving de-leaked features, so the retrain is **mandatory and paired**. It produces a no-edge model — a correctness fix, not a profit fix. Skip only if the project is being wound down. |

### Phase B — Build the CLV instrument (gates everything after)

The project has never measured closing-line value — every ROI number to date is against
opening/aggregated odds and means little. **Beating the closing line is the only reliable
evidence of edge.** Status (verified 2026-05-21 via `scripts/mlb/clv_report.py`): no new
*subscription* is needed, but the **closing-line capture is broken** — `oddsa_pitcher_props`
snapshots intraday lines well, but only ~2.6% of game-pitchers get a true ≤30-min-pre-pitch
snapshot and 66% have nothing within 4 h. So CLV is **not measurable from stored data**;
the capture must be fixed first, and CLV then accrues going forward only.

| | Item | Effort | Notes |
|--|------|--------|-------|
| `[ ]` | **Fix the closing-line capture** — schedule the `oddsa_pitcher_props` pitcher-props scrape to run reliably ~5–15 min before each game's first pitch (per-game-staggered, or a tight cadence over the game-time cluster). The scraper exists; the scheduling does not capture close. $0 — a scheduling/orchestration fix. | Med | The actual blocker. CLV accrues from when this lands. |
| `[ ]` | Rebuild `pitcher_props_closing` from the genuine near-pitch snapshot (kills the 98%-synthetic path); CLV per pick via `scripts/mlb/clv_report.py` | Med | The report tool is already built — it works once real closing snapshots exist. |
| `[ ]` | (Optional) backfill 2025 CLV via the historical scraper `mlb_pitcher_props_his.py` | Low–Med | The only way to get past closing lines — metered Odds API historical credits on the existing plan, **no new subscription**. |

### Phase C — Pursue a real edge (validated leak-free **and** by CLV)

Two structural sources of edge. Pursue C1 first — the infrastructure already exists.

| | Item | Effort | Rationale |
|--|------|--------|-----------|
| `[ ]` | **C1 — Information-speed edge (the lineup early-hook).** The project is named for this. Quantify: when confirmed lineups / scratches / weather land *before* the book moves the line, is there CLV in that window? If so, bet it. | Med | A genuine, repeatable, structural edge — and Phase 0 already built the lineup-capture infra. This is the most promising thread. |
| `[ ]` | **C2 — Softer markets.** Backtest `outs`/innings pitcher props and batter props on the leak-free harness — less-modeled than starter Ks. Batter-prop scrapers were stopped 2025-09-28 and need re-enabling. | Med–High | Edge lives in market *inefficiency*; starter Ks are efficient, these may not be. |

**The leak-free harness gates everything** — no strategy is believed until it validates
leak-free *and* shows positive CLV.

### The stop criterion

If, after the odds feed lands and CLV is measured honestly, there is **no CLV on any
strategy or subset**, that is decisive evidence this is not a beatable game and
**stopping is the correct decision.** Measuring CLV exists precisely to make that call on
data rather than grinding indefinitely.

---

## Retired / superseded

- **"Fix the betting machinery" (old Stage 1.1–1.5)** — done and validated; no profit
  leak. Poisson `p_over` / the blend ship inert; **do not activate the blend.** The
  machinery is roughly fine — it is not the opportunity.
- **"Strikeout features" (old Stage 2) + the discovery-harness MVH** — demoted. Adding
  *public* features to a model on an efficient market cannot create edge. (An
  information-*speed* "feature" is different — that is C1.) Revisit only if a CLV-positive
  strategy emerges that a feature could amplify.
- **Stage 3 per-batter model** — retired (unchanged).
- A point-in-time in-season FanGraphs feed was considered and rejected: point-in-time
  *public* stats are already priced into the line.

## Risks & notes

- **The biggest risk is no longer "planning as progress" — it is grinding the machinery.**
  Every machinery/signal lever has been tested and is empty. Do not keep poking it.
- **C1/C2 may also come up breakeven.** That is an acceptable, informative outcome — CLV
  turns it into a clean decision instead of an endless one.
- **Deploy discipline:** the Phase A retrain is a real model swap — upload + register +
  shadow in GCS first; the MLB worker auto-deploys.
- **Housekeeping (no-regret, low priority):** deploy `mlb_freshness_checker`; repoint code
  refs `mlb_game_feed` → `mlb_game_feed_pitches` (the former is empty).
