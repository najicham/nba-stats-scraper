# Handoff — MLB Pitcher-Strikeout Project: aspirations, state, and the plan forward

**Date:** 2026-05-21 · **Supersedes:** `2026-05-20-3-mlb-strikeout-stage-1.1.md`
**Project folder:** `docs/08-projects/current/mlb-lineup-early-hook/`

> **⚠️ SUPERSEDED — PROJECT CONCLUDED 2026-05-22.** This handoff described a measurement
> window ending 2026-06-20. That plan was **not** executed: a 21-agent review found the CLV
> instrument broken and underpowered, and direct well-powered evidence (model MAE + a
> 0/33 signal backtest + a signal-confluence backtest) concluded the project. The finding:
> **MLB starter strikeouts are not a beatable market with these tools.** See
> `docs/08-projects/current/mlb-lineup-early-hook/03-FINDING-market-is-efficient.md`.
> The text below is retained for history only.

---

## 0. Read this first (orientation for a new session)

You are picking up the **MLB pitcher-strikeout prop-betting project**, a sub-project of
the `nba-stats-scraper` repo (the repo's main mission is NBA props). To get oriented:

1. Read this whole doc.
2. Read `docs/08-projects/current/mlb-lineup-early-hook/02-EXECUTION-PLAN.md` — the live
   plan, including the **pre-registered kill-criterion** (Phase C → "Decision framework").
3. The auto-memory file `mlb-strikeout-project.md` has the running detail.

**Current operational state, in one breath:** the MLB pitcher-strikeout betting system's
public output is **paused**; the closing-line capture was just **fixed**; the project is
in a ~4-week **measurement window** that ends with a **dated go/no-go decision on
2026-06-20**. There is nothing to actively build until then — by design.

---

## 1. The aspiration

Build a **profitable MLB pitcher-strikeout prop-betting system** — predict each starting
pitcher's strikeout count, compare to the sportsbook line, and bet the over/under edges
that clear the vig. The dream version: a disciplined daily pipeline that ships a small set
of high-confidence picks with a real, measured edge.

That aspiration is still on the table — but it is now subject to a hard, honest test (see
§4). The project has been run with genuine rigor: pre-registered pass/fail bars, leak-free
validation, and killing dead threads cleanly. The aspiration is **"a profitable system OR
a documented, honest proof that this market isn't beatable with these tools"** — both are
acceptable, successful outcomes. What is *not* acceptable is grinding indefinitely without
a verdict.

---

## 2. Where we are now (2026-05-21)

A full leak-free validation (≈65 agents over many sessions) overturned the project's
founding thesis. The honest picture today:

- **The model has no edge over the market.** A critical FanGraphs look-ahead leak was
  found and fixed; the de-leaked model's MAE is at or slightly worse than the betting
  line. The market is efficient.
- **The betting machinery has no profit leak.** Poisson p_over, the model-market blend,
  signal rescue — all tested, all empty.
- **Model features don't help.** Two feature hypotheses (a mid/high-K niche; an
  opponent-lineup feature) each failed pre-registered bars. Adding *public* features to a
  model on an efficient market cannot create edge.
- **C2 — "softer markets" — tested and dead.** `scripts/mlb/market_efficiency_scan.py`
  scanned all 13 MLB prop markets (5 pitcher + 8 batter, ~519K rows): every one is
  efficient, no naive directional bet clears the vig.
- **C1 — the "lineup early-hook" information-speed edge — is the last thread**, but an
  8-agent review (2026-05-21) found it is **not operationally capturable** with this
  system (no bet-placement code, cron- not event-driven data; a live capture would be a
  multi-month new system class). C1 is therefore downgraded from "a build" to **one
  honest measurement**: does the system's edge anticipate closing-line movement (CLV)?

### What was done this session (all committed + pushed, builds green)

- **Leak fix + leak-free validation harness** — `season_replay.py`, `calibration_report.py`
  (prior-season FanGraphs join across 9 files; `pitcher_game_summary` backfilled).
- **MLB public output PAUSED (durable).** New table `nba_orchestration.halt_overrides`;
  `halt_state_writer` CF extended to honor it; `mlb_best_bets_exporter` now actually
  suppresses picks on `halt_active` (was advisory-only). Reason: the live worker serves a
  leak-trained model on de-leaked features (train/serve skew).
- **Closing-line capture FIXED.** The two pre-game burst schedulers
  (`mlb-oddsa-pitcher-props-burst-afternoon`/`-evening`) — built but left PAUSED — were
  re-enabled. They fire every 30 min, 1:00–11:30 PM ET; the materializer
  (`mlb-pitcher-props-closing-materialize`) heals `pitcher_props_closing` automatically.
- **C2 tested and closed** — `scripts/mlb/market_efficiency_scan.py` committed.
- **CLV instrument fixed** — `scripts/mlb/clv_report.py` had a real bug (closing line
  computed over 1–2 books, not a consensus); rewritten to source the materialized
  `pitcher_props_closing` and report N / SE / bootstrap 95% CI with a gated verdict.
- **Pre-registered kill-criterion written into the execution plan** (see §4).

---

## 3. The story — how we got here (concise)

The project began as "fix the betting machinery, then add features." A 15-agent review of
Stage 1.1 found a **FanGraphs look-ahead leak** — `fangraphs_pitcher_season_stats` holds
only post-season snapshots, and a same-season join leaked completed-season FIP/swstr/csw
(~23% of feature importance) into mid-season games. Fixing it (prior-season join) and
re-validating leak-free overturned the founding thesis: the model never matched the market
on clean data — the old "1.83 vs 1.85" was the leaked model.

From there the project narrowed, thread by thread, each killed with a pre-registered bar:
machinery → no leak; features → don't help; C2 softer markets → all efficient. C1
(information-speed) is the last corner — and the 8-agent review concluded it is not
realistically capturable. That narrowing is disciplined work, not failure — but it has
also been flagged (by the meta reviewer) as carrying **sunk-cost risk**: the project keeps
finding "one more thread." Hence the kill-criterion below.

---

## 4. The plan forward — the decision framework

**The whole project now rests on one measurement and one date.** This is pre-registered
in `02-EXECUTION-PLAN.md` → "Decision framework" — reproduced here so it cannot drift:

### The decisive test
Mean **closing-line value (CLV)** of the system's best-bets picks vs. the genuine closing
line — measured by `scripts/mlb/clv_report.py` (reports N, SE, bootstrap 95% CI, gated
verdict). Beating the closing line is the only reliable evidence of betting edge.

### Pre-registered PASS / FAIL
- **PASS:** mean CLV bootstrap 95% CI lower bound **strictly > 0** at **N ≥ 120** graded
  picks with a genuine (`is_synthetic=FALSE`) closing line — **confirmed on leak-free
  retrained picks**.
- **FAIL:** CI lower bound ≤ 0, **or** N < 120 by the deadline. → **Conclude the project.**
  No re-slicing by handedness/park/book, no "one more subset," no window extension.
- **Confound:** the live model is leak-trained; the leak can manufacture spurious positive
  CLV (it biases *which* pitchers get picked). Any positive read on current shadow picks
  is **PROVISIONAL** until re-measured on leak-free retrained picks.

### Milestones
- **2026-05-23** — local **smoke-test** (not a verdict). Confirm the burst capture is
  producing genuine closing lines and the pipe flows. N will be ~5–15 — far below 120.
- **~2026-06-20** — the **go/no-go verdict** against the criterion above.

### If PASS
C1 is real — *then and only then* evaluate the operational build to actually capture it.
That build is **large, separate, and explicitly gated** (real-time event detection +
automated bet placement — a different system class). PASS unlocks that decision; it does
not assume it.

### If FAIL
Conclude the project. Write *"MLB starter strikeouts are not a beatable market with these
tools"* as the documented finding, leave MLB output halted, and close it. This is a
**completed research project that answered its own question** — a successful outcome.

---

## 5. The aspirations beyond the verdict

Honest forward-looking notes for a future session, so nothing is lost:

- **If the system ever does go live:** it would need the operational build above
  (bet-placement integration, staking, limits) — none of which exists today. Treat that
  as a fresh project, not a continuation.
- **NBA-side leak audit (separate, worthwhile regardless of the C1 verdict).** The same
  leak class — joining post-season snapshot tables on the same season — very likely
  exists in the NBA pipeline. Auditing NBA feature joins for look-ahead leakage is a
  high-value follow-on that stands on its own.
- **The durable assets are the real deliverable** and should be maintained whatever
  happens to C1: the leak-free walk-forward harness (`season_replay.py`),
  `calibration_report.py`, the CLV instrument (`clv_report.py`), the fixed MLB lineup
  capture, and the market-efficiency scanner (`market_efficiency_scan.py`).

---

## 6. Operational reference

| Need | How |
|------|-----|
| **Resume MLB public output** (after a clean model exists) | `UPDATE nba_orchestration.halt_overrides SET active=FALSE WHERE sport='mlb'` — next `halt_state_writer` run (5 AM ET) reverts to the natural decision. |
| Check halt state | `SELECT * FROM nba_orchestration.halt_state WHERE sport='mlb' AND effective_date >= CURRENT_DATE()-2` |
| Run the CLV checkpoint (LOCAL only — needs GCP creds) | `PYTHONPATH=. .venv/bin/python scripts/mlb/clv_report.py --start 2026-05-22` |
| Verify closing capture healed | `bq query "SELECT COUNTIF(is_synthetic=FALSE) real, COUNTIF(is_synthetic=TRUE) synth FROM \`nba-props-platform.mlb_raw.pitcher_props_closing\` WHERE game_date >= '2026-05-22'"` |
| Re-run the C2 market scan | `PYTHONPATH=. python scripts/mlb/market_efficiency_scan.py` |
| Leak-free retrain (Phase A, when ready) | `scripts/mlb/training/train_regressor_v2.py --training-start 2024-04-01` (2 Aprils — see memory) |

**Key tables:** `mlb_raw.pitcher_props_closing` (materialized closing lines),
`mlb_raw.oddsa_pitcher_props` (raw odds time-series, 5 markets), `mlb_predictions.
signal_best_bets_picks` (best-bets / shadow picks), `nba_orchestration.halt_overrides`
(the durable manual halt).

---

## 7. Deferred / open items

None of these are needed before the 2026-06-20 verdict; do them only if the project
continues past it. Listed so they are not forgotten.

| Item | Why it matters | Severity |
|------|----------------|----------|
| Burst schedulers exist only in gcloud, not a config file | A scheduler-setup re-run could silently drop them → CLV capture reverts to synthetic mid-measurement. Watch the `is_synthetic` split in `clv_report.py`. Fix: add `deployment/scheduler/mlb/clv-capture-schedulers.yaml`. | HIGH (during the measurement window) |
| `snapshot_time` = Phase-2 processing time, not scrape time (`mlb_pitcher_props_processor.py`) | Can mis-flag the `is_synthetic` 30-min boundary if Phase-2 lags. Fix: scraper should emit a real `snapshot_timestamp`. | MEDIUM |
| Early-afternoon games (~12–1 PM ET first pitch) start before the first 1 PM burst | Those stay `is_synthetic=TRUE`. Fix: add an ~11:30 AM ET burst fire. | MEDIUM |
| The un-pause will be forgotten — no reminder/alert on a stale `halt_overrides` row | MLB output could stay dark indefinitely after a clean model is ready. Add a reminder to the Phase A retrain task. | MEDIUM |
| `prediction_accuracy.clv_*` columns exist but are unpopulated (A5 Layer B never built) | No persistent per-pick CLV / no CLV auto-demote. `clv_report.py` works without it. Optional productionization. | MEDIUM |
| Odds API credit cost from +24 burst fires/day | Not monitored anywhere. Eyeball the Odds API dashboard. | LOW |
| Materializer hardcoded to `market_key='pitcher_strikeouts'` | Correct for this project; blocks reuse for other markets. | LOW |

---

## 8. Discipline notes for the future session

- **Every test gets a pre-registered pass/fail bar set before it runs.** This is how the
  niche, the opponent-lineup feature, and C2 were each cleanly killed. Honor it.
- **Do not re-litigate dead threads** (machinery, model features, C2). They are dead.
- **The biggest risk to a good outcome is sunk-cost reasoning** — reinterpreting a
  breakeven CLV read as "promising, needs more data." The kill-criterion exists precisely
  so the 2026-06-20 call is arithmetic, not a judgment made under pressure. Trust it.
- **"A good place" for this project is a *finished* one** — a profitable system, or a
  documented honest "no edge" verdict. Both are wins. "Still betting with no measured
  edge" is not.
- The owner values **honesty over optimism** and has (rightly) resisted premature
  wind-down before — but has also agreed that discipline and the kill-criterion matter.

---

*All session commits are on `main` and auto-deployed. Nothing is in-flight. The next
action is the 2026-05-23 smoke-test, then the 2026-06-20 verdict.*
