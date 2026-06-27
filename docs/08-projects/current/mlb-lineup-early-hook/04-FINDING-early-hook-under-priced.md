# FINDING — "early-hook UNDER" is priced into the line, not the vig

**Date:** 2026-06-26 · **Status:** THREAD CLOSED (hypothesis killed at Phase-0)
**Context:** Follow-on to `03-FINDING-market-is-efficient.md`. The 2026-06-25/26 8-agent MLB
resume deep-dive surfaced "early-hook UNDER" as the one structural inefficiency never
properly tested (every prior backtest deleted short starts via an `innings_pitched >= 3.0`
look-ahead filter at `season_replay.py:381`). The owner chose to scope it. It was
pre-registered and tested. It fails.

---

## The hypothesis

A short start (pitcher pulled early) → few strikeouts → UNDER on the pitcher-K prop hits.
If short starts are predictable **pre-game** AND the market **under-discounts** that risk,
there is a real UNDER edge in a pocket prior backtests literally threw away.

## The pre-registered Phase-0 gates (set before looking at data)

| Gate | Bar | Result |
|------|-----|--------|
| 1. Predictable beyond the line | pre-game risk score predicts IP<4 OOS, *beyond what the K line already encodes* | **FAIL** |
| 2. Volume | high-risk subset ≥100 picks/season | PASS (not binding) |
| 3. Not already priced (killer) | UNDER clears **true vig** (actual under_price) by ≥2pp in BOTH 2024 & 2025 | **FAIL** |
| 4. CLV | positive reconstructed-close CLV | not reached (gates 1+3 already killed it) |

## The evidence

**The premise is TRUE.** Short starts overwhelmingly cash the UNDER (source:
`mlb_analytics.pitcher_game_summary` actuals + K line):

| Season | Starts | IP<4 rate | UNDER-hit IP<4 | UNDER-hit IP<3 | UNDER-hit all starts |
|--------|--------|-----------|----------------|----------------|----------------------|
| 2024 | 5,077 | 12.2% | 80.1% | 96.5% | 45.5% |
| 2025 | 5,072 | 12.6% | 77.4% | 90.4% | 45.8% |

Perfect-prediction ceiling (bet UNDER only on starts that actually went IP<4, at true odds):
**+49% ROI** (2024 +54%, 2025 +45%). The old `innings≥3` filter was deleting these
near-certain winners — that part of the critique was correct.

**Gate 1 — predictable, but not beyond the line.** A GBM on pre-game-knowable features
(recent IP trend, pitch-count trend, days rest, rolling ERA/WHIP) predicts IP<4 at **AUC
0.61** OOS; top-5% bucket goes short 20% vs 9.4% base (2.15× lift). BUT the **K line alone
already predicts IP<4 at AUC 0.60**; our features add only **+0.01 AUC**. Realized UNDER on
the model's top-5% short-risk pitchers = **47.6%** (sub-breakeven) because the book sets them
a low line (avg 4.3 K).

**Gate 3 — already priced (decisive).** `corr(recent IP, K line) = +0.378`: the book sets
materially lower K lines for likely-short starters (recent-IP≤4 → 3.9 line, over-prob shaded
to ~−15.7). **0 of 9** ex-ante high-risk proxies clear the +2pp bar in both seasons:

| Proxy | 2024 ROI | 2025 ROI |
|-------|----------|----------|
| recent IP < 5.0 | +0.1% | −8.2% |
| recent IP < 4.5 | +2.9% | −13.2% |
| K line ≤ 4.5 | −0.6% | −2.7% |
| season K/9 < 7.5 | −0.1% | −3.7% |
| first/spot start | −25.7% | −8.8% |
| short rest ≤3 | −12.6% | +3.3% |
| (+3 more) | all FAIL | all FAIL |

Baseline all-starts UNDER at true vig already loses (2024 −2.5%, 2025 −4.0%) — UNDERs on
low-K pitchers draw −120 to −150.

## The mechanism (the one-line reason)

The early-hook edge is real but lives **entirely in the unpredictable in-game tail**
(blowups, weather, injury). Every *pre-game* proxy for short-start risk is also visible to
the book, which prices it **into the line** (a lower number), not just the vig. Select on any
forward-knowable signal and the ~80% UNDER rate collapses to ~50%. Same efficient-market
verdict as the rest of the project, one layer deeper.

## Disposition

- **MLB strikeout betting stays HALTED.** No change. (`nba_orchestration.halt_overrides`
  row, sport=mlb.)
- **Do NOT re-litigate early-hook UNDER.** Pre-registered, cross-season, true-vig tested,
  killed. The blowout-risk extension is unbuildable anyway (`game_total_line`,
  opponent-offense columns 100% NULL in `pitcher_game_summary`).
- **Durable byproduct:** the 8-agent deep dive also produced the first working **CLV
  reconstruction from `oddsa_pitcher_props` snapshots** (the instrument the project never
  had). It confirmed no-edge with a low-variance arbiter for the first time: the leak-trained
  model's OVER picks carry **negative CLV** (−0.12 K, 19% positive-CLV); K lines drift up
  open→close. The close disagrees with our picks.
- The only genuinely-untested upside is a **new data source** (sharp-vs-retail / Pinnacle via
  Odds API `regions=eu`) — a new project, not a resume, against the standing "improve NBA
  core, don't expand" direction.
