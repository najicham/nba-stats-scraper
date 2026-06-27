# Kickoff — MLB full review: map everything we've tried, then scan the web for genuinely-new ideas

**Date:** 2026-06-27 · **Owner ask:** "Review all our docs and code: what we've tried in MLB,
what didn't work, what could work. Maybe scrape the web for ideas."

**Read this whole doc before doing anything.** It exists so you DON'T waste the session re-running
threads that are already dead. Your value is in (a) building the complete tried/failed/open map from
the repo, and (b) bringing in **outside** ideas (web) that are NOT already on the dead list and
holding them to the same bar everything else was held to.

---

## 0. The honest starting point (do not skip)

MLB pitcher-strikeout prop betting was **concluded as a no-edge / efficient market** and **halted on
purpose**. As of this writing that verdict is **quadruple-confirmed**:

1. **2026-05-22** — 21-agent hostile review + well-powered walk-forward MAE (detects any edge >0.02 K)
   + **0 of 33 signals pass** a pre-registered backtest + signal-confluence fail + home-pitcher bias
   FAIL + steam FAIL + all 13 markets efficient (C2 scan).
2. **2026-06-16** — re-check on fresh data: a profitable-*looking* window (61.7% HR, N=47) that
   **failed the bar** (binomial p=0.128, CI lower bound 0.487 < breakeven — a hot streak).
3. **2026-06-25** — 8-agent resume deep dive: bar fails both halves; **CLV finally measured for the
   first time (reconstructed from raw odds snapshots) and it is NEGATIVE** on the model's OVER picks
   (−0.12 K, 19% positive-CLV; K lines drift *up* open→close). The decisive low-variance arbiter ran
   and said no. Then **early-hook UNDER** (the one structurally-untested pocket) was scoped + **killed**
   (short-start risk is priced into the *line*, not the vig).
4. UNDER got its first clean cross-season test → **fails** (49.5%, worse with edge).

**The owner has been repeatedly flagged for sunk-cost bias** (reading a breakeven streak as
"promising"). The pre-registered bar exists to make the decision arithmetic, not optimism. Honor it.
**A documented "no" is a successful outcome**, identical to the standard the NBA work holds itself to.

**This does NOT mean the session is pointless.** The concluded finding closes one specific box —
*"model + signals + filters + market selection on PUBLIC data, vs the retail consensus line."* It
explicitly leaves three things open (§4). Your job is to map the box rigorously and probe only the
genuinely-open edges — including with outside/web ideas.

---

## 1. The pre-registered bar (quote it — do not move it)

> **Resume bar:** OVER edge≥0.75 sustaining **≥58% HR WITH positive CLV (bootstrap 95% CI lower
> bound > 0) at N≥100.**

Both halves required. **CLV is the decisive half** — HR alone at these N is a hot-streak trap (that's
exactly what killed the 2026-06-16 read). Any new idea, web-sourced or not, must end at a test against
this bar (or, for a forward-only idea, a clearly pre-registered kill-criterion).

---

## 2. What to read first (build the map from these)

Repo: `/home/naji/code/nba-stats-scraper`. Read in this order:
- `docs/08-projects/current/mlb-lineup-early-hook/03-FINDING-market-is-efficient.md` — the concluded
  finding + the full evidence table (every layer tested).
- `docs/08-projects/current/mlb-lineup-early-hook/04-FINDING-early-hook-under-priced.md` — early-hook
  UNDER killed (2026-06-26).
- `docs/09-handoff/2026-06-25-mlb-resume-deep-dive-kickoff.md` — the 8-agent deep-dive plan + CLV pivot.
- Memory: `/home/naji/.claude/projects/-home-naji-code-nba-stats-scraper/memory/mlb-strikeout-project.md`
  — the running blow-by-blow (start here for "what exactly was tried and what the numbers were").
- Memory: `next-market-opportunity-2026-06.md` — the deferred-candidate analysis (incl. the Pinnacle /
  sharp-vs-retail idea and the batter NO-GO).
- The C2 / comprehensive review project: `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/`
  (`00-OVERVIEW` → `10-A4-DECISION`) and `docs/08-projects/current/mlb-under-shadow-rollout/`,
  `star-out-vacated-touches-discovery/`.
- Other MLB handoffs: `docs/09-handoff/*mlb*` (several).
- Code/tooling (the durable assets — reuse, don't rebuild): `scripts/mlb/training/season_replay.py`
  (leak-free walk-forward harness — **note the `innings_pitched >= 3.0` look-ahead filter ~line 381;
  do NOT reintroduce it in any backtest**), `scripts/mlb/market_efficiency_scan.py` (13-market scanner),
  `scripts/mlb/calibration_report.py`, `scripts/mlb/clv_report.py` (synthetic-dependent — prefer the
  snapshot reconstruction below), and the NBA CLV recipe ported to MLB this session
  (`scripts/nba/training/discovery/clv_validation.py` as the template; reconstruct from
  `mlb_raw.oddsa_pitcher_props` snapshots).

---

## 3. What we've tried and what DIDN'T work (the dead list — do NOT re-run these)

| Thread | How it was tested | Result |
|--------|-------------------|--------|
| **Founding thesis** ("model matches market") | leak-free re-validation | OVERTURNED — was a FanGraphs same-season-snapshot look-ahead leak (~23% of feature importance) |
| **Model edge** | walk-forward MAE vs line, well-powered (detects edge >0.02 K) | NO EDGE — de-leaked model ties/trails the line (2024 1.787 vs 1.763; 2025 1.711 vs 1.722) |
| **Model features** | mid/high-K niche, opponent-lineup K-rate feature | FAIL — niche was a look-ahead artifact; market already prices opponent strength |
| **Betting machinery** | Poisson `p_over`, model-market blend | blend HURTS; `p_over` correctly specified; no profit leak |
| **Signals** | all 54 registered, pre-registered, BH-FDR | **0 of 33 testable pass** — fewer than chance predicts |
| **Signal confluence** | real_signal_count ≥2/3/4/5 + full pipeline | NO — ROI not monotonic with signal count; 0 subsets clear |
| **C2 — other markets** | 13 MLB prop markets, ~519K rows | ALL EFFICIENT — no naive directional bet clears the vig both seasons |
| **Batter props** | total_bases / hits subset backtest | NO-GO — 0/212 subsets; build OFF, schedulers deleted |
| **Home-pitcher bias** | standalone backtest at real closing odds | DEAD — pooled ROI −5.5%; the "58% home-OVER" was the `innings≥3` artifact |
| **Steam / line movement** | bet with the move | DEAD — 2026 N=100, ROI −14.8% |
| **UNDER (clean cross-season)** | dedicated WF test, true vig | FAIL — 49.5%, worse with edge; NBA's "UNDER is robust" does NOT port |
| **Early-hook UNDER** | pre-registered, cross-season, true vig | DEAD — short-start risk priced into the *line* (corr recent-IP↔K-line +0.378); edge lives only in the unpredictable in-game tail |
| **CLV on shadow picks** | reconstructed close (2026), the decisive arbiter | NEGATIVE — the close moves *against* our OVER picks |
| **The 2026-06-16 "61.7%" window** | binomial vs breakeven | hot streak (N=47, p=0.128, CI below breakeven) |

**The one-line reason it's efficient:** model ≈ market because both consume the same public info
(FanGraphs, Statcast, box scores, schedule). Starter-K props are heavily-modeled, liquid, efficient.
To beat the line you need info the market lacks, or the speed to act before it reprices.

---

## 4. What is genuinely still OPEN ("what could work") — the only legitimate frontiers

The concluded finding closes "public-data prediction vs the retail consensus." It does NOT close:

1. **Sharp-vs-retail book disagreement (highest-prior new lever).** All ~12 MLB books in our
   warehouse are retail US books. A sharp book (Pinnacle, Circa) is a *different, sharper* line —
   betting a stale retail number when the sharp book disagrees is a different mechanism than
   "predict K better" (the model is irrelevant). **Prior plausibility:** NBA's `book_disagreement` is
   fleet-independent and survived. **The catch:** we have **no historical Pinnacle snapshots**, so it
   is **not backtestable** — it's a forward-only live experiment. Cheap first step: confirm Odds API
   `regions=eu` even returns Pinnacle for MLB `pitcher_strikeouts` (coverage is the open question).
2. **Information-speed edge (the old "C1").** Act on genuine news (elite-hitter scratch, weather,
   opener announcement) before the market reprices. Requires real-time event detection + **automated
   bet placement** (the repo has zero). A multi-month new *class* of system, not a backtest.
3. **Non-public / proprietary data.** By definition unscrapeable. Needs a named, real source the
   market underuses. None has been identified — finding a candidate is itself a valid outcome.

Everything outside these three, on public data, is the dead list (§3). If a web idea maps to §3, it's
already refuted — say so and move on.

---

## 5. The web-research mandate (the new input you asked for)

Use the `deep-research` skill (or WebSearch/WebFetch) to bring in OUTSIDE knowledge. Goal: find
approaches/data/angles **we have not already refuted**, and a reality-check on whether sharp bettors
consider starter-K props beatable at all. Concretely investigate:
- **How do sharp bettors actually approach MLB pitcher-strikeout props?** (Expect: CLV / line-shopping
  / beating-the-number / limits — NOT prediction models. Confirm or refute.)
- **Are there known soft books or structural inefficiencies** specific to pitcher Ks (alt-K markets,
  first-5-innings Ks, live/in-game, low-limit books, exchange/peer-to-peer)?
- **What edge-data do pros use** that the major-book model might underweight (catcher framing, ump
  K-tendency, weather/air-density, pitch-mix shifts, minor-league call-up effects, park)? For each:
  is it *plausibly not already priced* by a Statcast-aware market? (Be skeptical — most are priced.)
- **Proprietary / non-public data sources** for pitcher performance that a retail scraper can't get.
- **Any published evidence** that starter-K props are or aren't beatable, and at what bankroll/limits.

**Discipline for web ideas:** for each idea, classify it — (a) already on the dead list (§3) → drop;
(b) a public-data prediction angle → almost certainly dead by the efficient-market finding, justify
why it'd be different; (c) a §4 frontier (cross-book / info-speed / non-public) → the only ones worth
scoping. Cite sources; adversarially verify claims (betting content is full of survivorship hype).
Bring back a ranked shortlist, each with: mechanism, why-it-might-not-be-priced, how to test it against
the §1 bar (or a forward kill-criterion), effort, and honest P(real edge).

---

## 6. Operational state (so you know what exists right now)

- **Betting is HALTED durably:** `nba_orchestration.halt_overrides` row, `sport=mlb` (an active row
  forces halt; only un-setting it resumes). To check:
  `SELECT * FROM nba_orchestration.halt_overrides WHERE sport='mlb'`.
- **Mothballed 2026-06-26:** ~28 MLB betting/prediction scheduler jobs PAUSED (burst CLV capture,
  best-bets gen, shadow grading, regime monitor, retrain, etc.). Reversible:
  `gcloud scheduler jobs resume NAME --project=nba-props-platform --location=us-west2`.
- **KEPT alive (do not touch):** the `mlb-prediction-worker` + `mlb-predictions-generate` + the
  phase1-4 data pipeline — because the worker's `/predict-batch` writes the **factual tonight-page
  slate** (line+matchup) into `mlb_predictions.pitcher_strikeouts`; model predictions were STRIPPED
  from the frontend (`/home/naji/code/props-web` repo) on 2026-05-22. The MLB product is now a pure
  information product.
- **The live model is leak-trained** (May-17 `.cbm`, pre-leak-fix) on de-leaked features → it
  overshoots K and mechanically flatters directional OVER. Any CLV/HR read on *current* shadow picks
  is PROVISIONAL; a clean read needs the leak-free retrain
  (`scripts/mlb/training/train_regressor_v2.py --training-start 2024-04-01`).
- **CLV is now measurable** (the one genuinely-new capability): reconstruct the close from
  `mlb_raw.oddsa_pitcher_props` snapshots (join `REPLACE(pitcher_lookup,'_','')`; close = median of
  smallest-positive `minutes_before_tipoff` snaps). It came back NEGATIVE on OVER — reuse the
  instrument, don't rebuild it.

---

## 7. Guardrails (anti-sunk-cost — read before concluding anything)

- **Do NOT re-run the §3 dead threads.** They were pre-registered, BH-FDR-corrected, hostile-reviewed.
  Re-running them only manufactures false positives.
- **Do NOT reinterpret a breakeven/streak read as "promising."** N at these volumes can't tell a thin
  edge from noise — that's why CLV is the decider.
- **The `innings_pitched >= 3.0` look-ahead filter** in `season_replay.py` fabricated the fake home
  bias. Any new backtest must not reintroduce it; use only pre-game-knowable features; use true
  per-pick odds (UNDER on low-K pitchers draws −120 to −150, not flat −110).
- **A clear "no" is the goal as much as a "yes."** If the web turns up nothing in §4 that's testable,
  the correct deliverable is "still no beatable edge; here's the exhaustively-mapped why," plus any
  forward-only experiment worth a deliberate (separate-project) decision.
- **Reopening the betting product is justified only by a §4 frontier materializing**, not by more
  public-data backtesting. The standing strategic verdict is "improve the NBA core, don't expand"
  (`memory/expand-vs-improve-2026-06.md`) — a new MLB data project is a deliberate owner decision.

---

## 8. Deliverable for the session

1. A consolidated **tried / failed / open** map (this doc's §3-4, refreshed against a fresh read of all
   the docs/code — flag anything I mis-stated or that's stale).
2. A **web-sourced shortlist** (§5) of outside ideas, each classified and rated against the bar.
3. A **recommendation**: is there any §4 frontier worth a scoped forward experiment (with a hard
   kill-criterion), or is the honest verdict "stay halted, information product only"? Either is a win.

---

## 9. Copy-paste kickoff prompt for the new session

> Review everything we've tried in MLB pitcher-strikeout betting and assess what didn't work and what
> could work, including scraping the web for outside ideas. FIRST read
> `docs/09-handoff/2026-06-27-mlb-full-review-and-web-scan-kickoff.md` in full, then memory
> `mlb-strikeout-project` and `docs/08-projects/current/mlb-lineup-early-hook/03-FINDING-market-is-efficient.md`
> and `04-FINDING-early-hook-under-priced.md`. The product is quadruple-confirmed no-edge and halted —
> your job is NOT to re-run the dead threads (model/features, the 0/33 signals, C2/batter markets,
> home-pitcher, steam, early-hook UNDER, CLV-on-current-picks) but to (1) build the complete
> tried/failed/open map from the repo, (2) use the deep-research skill to find OUTSIDE ideas we haven't
> refuted — especially how sharp bettors actually beat (or don't beat) starter-K props, soft books,
> non-public data, and the sharp-vs-retail/Pinnacle angle — and (3) hold every idea to the
> pre-registered bar (OVER edge≥0.75 ≥58% HR + positive CLV at N≥100, CLV decisive) or a forward
> kill-criterion. Be the anti-sunk-cost conscience; an honest "still no edge" is a successful outcome.
