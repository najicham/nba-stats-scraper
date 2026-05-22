# MLB Pitcher-Props Project — Execution Plan

**Created:** 2026-05-20 · **Rewritten:** 2026-05-21 (post-validation strategic pivot).
**Status:** SUPERSEDED — PROJECT CONCLUDED 2026-05-22.

> **⚠️ This plan is superseded.** The Phase C / CLV decision path below was not executed —
> the CLV instrument was found broken and underpowered. The project concluded on direct
> well-powered evidence (model has no edge; 0/33 signals pass a pre-registered backtest;
> signal confluence adds nothing). Final finding:
> `03-FINDING-market-is-efficient.md` — *MLB starter strikeouts are not a beatable market
> with these tools.* The text below is retained for history only.

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
- **All commits pushed + auto-deployed.** As of 2026-05-21: MLB public output is paused
  (Phase A), the closing-line capture is fixed (Phase B), and the handoff is at
  `docs/09-handoff/2026-05-21-1-mlb-strikeout-clv-pivot.md`.

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
| `[x]` | Push all commits | — | All on `main`, auto-deployed. |
| `[x]` | **Pause MLB public output** instead of an immediate forced retrain (operator decision 2026-05-21). The live worker serves a leak-trained model on de-leaked features (train/serve skew); rather than rush a no-edge retrain, public best-bets output is halted until a clean model is ready. Mechanism: `nba_orchestration.halt_overrides` row (sport=mlb, reason=manual, open-ended) → durable halt across daily `halt_state_writer` runs. The MLB exporter now actually suppresses picks on `halt_active` (was advisory-only). **To resume:** `UPDATE nba_orchestration.halt_overrides SET active=FALSE WHERE sport='mlb'`. | — | Done. Commit `869fe4b8`. The worker still generates BQ shadow picks (useful for CLV) — only the public JSON is suppressed. |
| `[ ]` | Retrain leak-free → shadow → promote, then lift the halt | Med | Produces a no-edge model — a correctness fix, not a profit fix. Do this when ready; until then the halt holds. Use `scripts/mlb/training/train_regressor_v2.py --training-start 2024-04-01` (include 2 Aprils — see memory). |

### Phase B — Build the CLV instrument (gates everything after)

The project has never measured closing-line value — every ROI number to date is against
opening/aggregated odds and means little. **Beating the closing line is the only reliable
evidence of edge.**

**Status update 2026-05-21 — the closing-line capture is FIXED.** Root cause: the
capture infrastructure already existed but was dormant. The Session 2 A5 design
(`docs/08-projects/current/mlb-comprehensive-review-2026-05-12/08-A5-CLV-DESIGN.md`)
built two pre-game *burst* schedulers (`mlb-oddsa-pitcher-props-burst-afternoon`,
`-burst-evening`) and left them **PAUSED** pending a cost check — so `oddsa_pitcher_props`
only got the 10:30/12:30 daily snapshots, hours before first pitch, and
`pitcher_props_closing` materialized 98% synthetic. **Fix: both burst schedulers
re-enabled 2026-05-21.** Together they fire every 30 min, 1:00 PM–11:30 PM ET — every
game's last pre-pitch snapshot is now ≤30 min old. The materializer
(`mlb-pitcher-props-closing-materialize`, already running daily) heals automatically as
real snapshots land. CLV accrues going forward from 2026-05-22.

| | Item | Effort | Notes |
|--|------|--------|-------|
| `[x]` | **Fix the closing-line capture** — re-enabled the two burst schedulers (2026-05-21). $0 — Odds API credits on the existing plan; watch usage on the Odds API dashboard for the first few days. | — | The actual blocker — done. |
| `[~]` | `pitcher_props_closing` heals automatically — the materializer runs daily; `is_synthetic=FALSE` rows accrue from 2026-05-22. CLV per pick via `scripts/mlb/clv_report.py` (derives closing from `oddsa_pitcher_props` directly — works now). | — | Verify after ~2 game days: `is_synthetic=FALSE` should be the majority. |
| `[ ]` | (Optional, productionization) Wire CLV into grading — populate the `prediction_accuracy.clv_*` columns (they exist, all NULL) from `pitcher_props_closing` via an idempotent trailing-window UPDATE. Not a blocker — `clv_report.py` already measures CLV ad-hoc. Enables CLV-based auto-demote later. | Low–Med | A5 Layer B, never built. |
| `[ ]` | (Optional) backfill 2025 CLV via the historical scraper `mlb_pitcher_props_his.py` | Low–Med | The only way to get past closing lines — metered Odds API historical credits on the existing plan, **no new subscription**. |
| `[ ]` | (Housekeeping) the burst schedulers exist only in gcloud — no config file. Capture them in `deployment/scheduler/mlb/clv-capture-schedulers.yaml` so a scheduler-setup re-run can't drop them. | Low | Config drift. |

### Phase C — the last question, and how it gets answered

| | Item | Status |
|--|------|--------|
| `[x]` | **C2 — Softer markets — TESTED 2026-05-21, DEAD.** `scripts/mlb/market_efficiency_scan.py` scanned all 13 MLB prop markets (5 pitcher + 8 batter, ~519K rows). Every market is efficient — no naive OVER/UNDER bet clears the vig in *both* 2024 and 2025. (Scope: this rules out market-wide naive bias, not a conditional-subset edge — but conditional-subset hunting is the same "find a feature/slice that beats the market" that has already failed twice. Not pursued.) | Dead |
| `[~]` | **C1 — Information-speed edge — DOWNGRADED to a measurement, not a build.** An 8-agent review (2026-05-21) found C1 is **not operationally capturable** with this system: pitcher-K lines are driven by the pitcher and opponent *team* K-rate (known days ahead — the market already prices the projected lineup, per the failed opponent-lineup test); the genuine line-movers (elite-hitter scratches, weather) are watched by the books on the same feeds and move lines in seconds; and the repo has **zero bet-placement code** and only cron-scraped (not event-driven) data. Capturing C1 live would be a multi-month new system class, not a feature. So C1 is **not a build** — it reduces to one honest measurement: does the system's edge anticipate closing-line movement at all? | Measure only |

**What's left is not a strategy to build — it is one question to answer:** measure CLV
honestly, and let the number decide. Every other thread (model features, machinery, C2)
is exhausted.

### Decision framework — the pre-registered kill-criterion

Written **before** the data lands so the call is arithmetic, not a judgment made under
sunk-cost pressure. (8-agent review, 2026-05-21 — both the strategy and meta reviewers
flagged that the live risk to a good outcome is the *owner*, not the data: a breakeven
read getting reinterpreted as "promising, needs more data.")

- **The single decisive test:** mean CLV on the system's best-bets picks vs. the genuine
  closing line — `scripts/mlb/clv_report.py` (now reports N, SE, bootstrap 95% CI, and a
  gated verdict).
- **Sample-size floor:** N ≥ 120 graded picks with a genuine (`is_synthetic=FALSE`)
  closing line. One game day (~5–15 picks) is a plumbing smoke-test, not a verdict —
  ~3–4 weeks of capture from 2026-05-22.
- **Confound:** the live model is leak-trained — the leak can manufacture spurious
  positive CLV (it biases *which* pitchers get picked). A positive read on shadow picks
  is **PROVISIONAL** until re-measured on leak-free retrained picks (Phase A row 5).
- **PASS:** mean CLV bootstrap 95% CI lower bound **strictly > 0**, confirmed on
  leak-free picks. → C1 is real; *then and only then* evaluate the (large, separate,
  explicitly-gated) operational build.
- **FAIL:** CI lower bound ≤ 0 (breakeven or negative). → **Conclude the project.**
  No re-slicing by handedness / park / book, no "one more subset," no window extension.
- **Deadline:** **2026-06-20.** If N ≥ 120 has not accrued by then, that is itself a
  FAIL signal (the system is not even producing enough picks to bet) → conclude.

### What "a good place" means

This is a **research project**, and a good place is a *finished* one — not "still
betting." It has already produced durable value regardless of the C1 verdict: a
leak-free walk-forward harness, a working CLV instrument, the fixed MLB lineup capture,
and a reusable market-efficiency scanner. If C1 FAILS, the correct, honest outcome is to
**write "MLB starter strikeouts are not a beatable market with these tools" as the
project's finding**, leave MLB output halted, and close the project. That is a completed
research project that answered its own question — not a failure. (Follow-on, separate:
the same leak class — post-season snapshot joins — likely exists NBA-side; worth an
audit there.)

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
