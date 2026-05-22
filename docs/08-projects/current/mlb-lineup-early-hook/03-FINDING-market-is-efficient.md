# FINDING — MLB starter strikeouts are not a beatable market with these tools

**Date:** 2026-05-22 · **Status:** PROJECT CONCLUDED
**Supersedes:** `02-EXECUTION-PLAN.md` (the Phase C / CLV decision path) and
`docs/09-handoff/2026-05-21-1-mlb-strikeout-clv-pivot.md` (the 2026-06-20 measurement window).

This is the MLB pitcher-strikeout prop-betting project's final, documented finding. The
project is **concluded**.

---

## The finding

**MLB starting-pitcher strikeout props are an efficient market. They are not beatable with
a prediction system built on public data — not with a better model, more features, an
ensemble, signals, filters, signal confluence, market selection, or patience.**

This is a successful research outcome, not a failure. The project asked a clear question —
*is there a profitable, capturable edge in MLB starter-strikeout props?* — and, after
unusually thorough adversarial testing, answered it honestly: **no.**

---

## How the verdict was reached

The pre-registered kill-criterion (`02-EXECUTION-PLAN.md` → "Decision framework") made the
decisive test a closing-line-value (CLV) measurement with a 2026-06-20 deadline. That test
was **not used as the decider**, for an honest reason: a 21-agent adversarial review
(2026-05-21 → 22) found the CLV apparatus could not function as one —

- the closing-line capture is non-functional — `pitcher_props_closing` is ~100% synthetic;
  the burst schedulers point at a stale service (`mlb-phase1-scrapers`) and never fired;
- `clv_report.py` has bugs — its verdict gate counts all matched picks (~97% synthetic)
  rather than genuine closing lines, and the picks↔closing join is broken;
- the N=120 CLV bar is statistically underpowered — ~10% power to detect a real 54% edge.

So the CLV test, as built, could only have produced a FAIL on a technicality. Instead the
project concluded on **stronger, well-powered direct evidence**: a walk-forward MAE
comparison and a series of pre-registered backtests, each one explicitly commissioned by
the owner, all returning the same answer.

---

## The evidence — every layer was tested

| Thread | Test | Result |
|--------|------|--------|
| Founding thesis | leak-free re-validation | **OVERTURNED** — the original "model matches market (1.83 vs 1.85)" was a FanGraphs look-ahead leak: `fangraphs_pitcher_season_stats` holds only post-season snapshots, joined same-season → ~23% of feature importance was leaked completed-season data. |
| Model edge | walk-forward MAE vs the line, well-powered (could detect any edge > ~0.02 K) | **NO EDGE** — de-leaked model MAE ties or trails the line (2024: 1.787 vs 1.763; 2025: 1.711 vs 1.722). |
| Betting machinery | Poisson `p_over`, model-market blend, signal rescue | **CLEAN** — no profit leak; the blend hurts; `p_over` is correctly specified (K counts are not overdispersed conditional on the prediction). |
| Model features | mid/high-K niche, opponent-lineup feature | **DON'T HELP** — both failed pre-registered bars. Adding *public* features to a model on an efficient market cannot create edge. |
| C2 — other markets | 13 MLB prop markets scanned, ~519K rows | **ALL EFFICIENT** — no naive directional bet clears the vig in both 2024 and 2025. |
| Home-pitcher bias | standalone backtest at real closing odds | **DEAD** — pooled ROI −5.5% (N=4,451), negative all 3 seasons. The earlier "~58% home-OVER" was an artifact of the `innings_pitched ≥ 3.0` look-ahead filter. |
| Steam / line movement | bet with the move | **DEAD** — 2024/2025 have no usable line-movement data; 2026 (N=100) returned −14.8% ROI. |
| Individual signals | all 54 registered signals/filters, pre-registered, BH FDR-corrected | **0 of 33 testable PASS.** Under the efficient-market null, chance alone predicts ~8 both-season winners; only 2 appeared — *fewer than noise.* |
| Signal confluence | `real_signal_count` ≥2/≥3/≥4/≥5 gradient + the full assembled pipeline | **NO** — ROI is not monotonic with signal count; negative in 2024 at every threshold; 0 subsets clear the bar. |
| Highest-confidence subset | the live config's actual best-bets | **UNMEASURABLE BY CONSTRUCTION** — the live MLB config yields only 93 best-bets across two full seasons (22 + 71). Too thin to ever validate. |
| Negative filters | what each filter blocks | **WORK AS DESIGNED** — they correctly block losing subsets (`whole_line_over` strongest). But a filter only *reduces losses*; it cannot *create* an edge. |

Nothing remains untested. "Model + signals + filters + market selection, on public data"
has no further distinct hypotheses in it.

---

## Why — the one-line reason

The model ≈ the market because both consume the same public information (FanGraphs,
Statcast, box scores, schedule). Starter-strikeout props are a heavily-modeled, liquid,
efficient market. A model can at best *tie* the line; to *beat* it you need information the
market lacks, or the speed to act before it — and a public-data prediction model is
neither.

---

## Disposition — what happens to the system

- **MLB public best-bets / picks output stays HALTED — permanently** for the strikeout
  betting product. Mechanism: the `nba_orchestration.halt_overrides` row (sport=mlb).
  Do **not** resume it. There is no "+EV" output to ship.
- **The data pipeline, the "tonight page," and the season trends are RETAINED — as a pure
  information product.** Per the owner's decision (2026-05-22), these surfaces display
  **no model predictions of any kind** — only factual data (schedules, matchups, betting
  lines, season stats, game logs, pitch arsenal, hot/cold trends). All model-prediction
  fields (projected K, edge, recommendation, best-bet flags, track record, the
  "Model Trusts Him" leaderboard, the OVER/UNDER "lean" on Key Angles) were stripped from
  the MLB pitcher JSON exporter (`mlb_pitcher_exporter.py`) and the props-web frontend.
- **No leak-free retrain is needed.** It was originally planned to make tonight-page
  *projections* honest — but with no projections displayed anywhere, the MLB model serves
  nothing user-facing. The prediction worker can be left dormant or decommissioned later
  to save cost.

---

## Durable assets (keep + maintain regardless)

- `scripts/mlb/training/season_replay.py` — leak-free walk-forward harness
- `scripts/mlb/calibration_report.py` — calibration instrument
- `scripts/mlb/clv_report.py` — CLV instrument (carries known bugs — see the 21-agent review)
- `scripts/mlb/market_efficiency_scan.py` — market-efficiency scanner (reusable for any market)
- the FanGraphs look-ahead leak fix (prior-season join across 9 files)
- the MLB lineup-capture fix
- the signal/filter backtest method (`/tmp/mlb_signal_backtest_*.csv` build process)

---

## Known issue to fix before any reuse

`season_replay.py` applies an `innings_pitched >= 3.0` filter that is a **look-ahead
artifact** — innings pitched is not known pre-game. It silently drops short starts
(near-certain OVER losses), inflating measured OVER hit-rate by ~1–2pp, and it manufactured
the spurious "home-pitcher bias." Anyone reusing the harness should remove or fix it. It
does **not** change this conclusion — it made the system look *better* than reality, so the
corrected picture is, if anything, firmer.

---

## Follow-on — a separate, high-value project

The same leak class — joining a post-season / end-of-period snapshot table on the *same*
season — very likely exists in the **NBA** feature pipeline. NBA is live, with real money
on it. Auditing the NBA feature joins for look-ahead leakage is a high-value, independent
follow-on and the recommended next use of effort.

---

## If MLB strikeout betting is ever reopened

This finding closes "model + signals + filters + market selection on public data." It does
**not** close — because they were never in scope and cannot be reached by backtesting — two
things:

1. An **information-speed** edge (acting on genuine news before the market reprices — the
   old "C1"). This requires real-time event detection plus automated bet placement: a
   different class of system, a fresh project.
2. A genuinely **non-public** data source — proprietary information the market does not
   have. By definition this cannot be scraped off the web.

Reopening is justified only if one of those genuinely materializes. It is **not** justified
by more backtesting — the public-data search space is exhausted, and re-running it only
manufactures false positives.
