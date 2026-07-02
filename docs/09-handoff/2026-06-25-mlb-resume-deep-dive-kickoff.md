# Kickoff — MLB deep dive: can we post MLB picks again?

**Date:** 2026-06-25 · **Owner ask:** "deep dive on MLB again and see if we can post the picks again."
**Branch to start from:** `offseason-eval-foundation-2026-06` (or merge it to `main` first — it's all
research/docs/tooling, safe). **Prereqs to read:** this doc, then memory `[[mlb-strikeout-project]]`
(the running detail), then `docs/08-projects/current/mlb-lineup-early-hook/03-FINDING-market-is-efficient.md`.

---

## 0. The one question (and the honest starting point)

**Can MLB pitcher-strikeout betting clear its pre-registered resume bar?** If yes, un-halt and post.
If no, it stays halted. Nothing else is in scope.

**Be honest with yourself before you start:** MLB starter-K betting was *concluded* as a
**no-edge / efficient market** and halted on purpose. That verdict is **triple-confirmed**:
- 2026-05-22: 21-agent hostile review + model-MAE (well-powered, detects any edge >0.02 K) +
  **0 of 33 signals pass** a pre-registered backtest + signal-confluence fail + home-pitcher bias
  FAIL + steam FAIL + all 13 markets efficient (C2 scan).
- 2026-06-16 re-check on ~25 days of fresh data: a profitable-*looking* window (61.7% HR, N=47) that
  **failed the bar** (one-sided binomial p=0.128, CI lower bound 0.487 — below breakeven; a hot streak).

So this is not "flip the halt switch." It is **"produce evidence strong enough to overturn a
thrice-confirmed no-edge conclusion."** The owner has been flagged repeatedly for **sunk-cost risk**
(reinterpreting a breakeven read as "promising"). The whole point of the pre-registered bar is to make
the resume decision **arithmetic, not optimism**. Honor it.

---

## 1. The pre-registered resume bar (quote it — do not move it)

From the 2026-06-16 re-check (`[[mlb-strikeout-project]]`, last block):

> **Resume bar:** OVER edge≥0.75 sustaining **≥58% HR WITH positive CLV at N≥100**.
> Until then: keep halted, shadow only, **fix closing-line capture first.**

Two halves, BOTH required: (a) ≥58% HR at N≥100 on edge≥0.75 OVER picks, AND (b) **positive CLV**
(bootstrap 95% CI lower bound > 0) on genuine closing lines. CLV is the decisive half — HR alone is a
hot-streak trap at these N (that's exactly what killed the 2026-06-16 read).

---

## 2. Why now / why this is worth a session (the new lever)

**The decisive instrument has never worked — and I just built the thing that fixes it.**

- Every prior MLB conclusion is HR-based. CLV — the only low-variance arbiter — was **never
  measurable**: `mlb_raw.pitcher_props_closing` is ~100% synthetic, the burst-capture schedulers were
  found pointing at the stale `mlb-phase1-scrapers` service and never fired, and
  `prediction_accuracy.clv_*` is unpopulated. The 2026-05-21 "closing capture FIXED" claim was **wrong**
  (corrected 2026-05-22). As of 2026-06-16, CLV is still **100% NULL**.
- **The NBA off-season CLV work (just finished, 2026-06-25) solved this exact problem for NBA:**
  reconstruct the closing line directly from the raw odds snapshot time-series (no dependence on a
  brittle "closing materializer"). Recipe: `nba_raw.odds_api_player_points_props` grouped by
  (game_date, player) with `minutes_before_tipoff` → median of the near-tip snapshots = the close.
  See `scripts/nba/training/discovery/clv_validation.py` (`--build-cache`) and
  `docs/08-projects/current/clv-validation/00-SCOPE.md`.
- **MLB has the analogous raw table:** `mlb_raw.oddsa_pitcher_props` (raw odds time-series, has
  snapshot timestamps + `game_start_time`/first-pitch). So the NBA reconstruction recipe ports
  directly: reconstruct the MLB close from snapshots, bypass the broken `pitcher_props_closing`
  entirely, and finally **measure CLV on MLB shadow picks** — the decisive test that has never run.

This is the genuinely-new capability since the project was concluded. It's why "deep dive again" is
justified rather than re-litigation.

---

## 3. The plan (bounded, pre-registered, ~1 session + maybe a retrain)

**Step A — Reconstruct the MLB closing line from snapshots (port the NBA recipe).**
- Phase-0 feasibility first (mirror NBA): in `mlb_raw.oddsa_pitcher_props`, confirm the snapshot
  schema (snapshot timestamp + first-pitch time + a `player_lookup`/`pitcher_lookup` join key + the K
  line), then measure: of graded shadow picks, what % have ≥1 genuine pre-first-pitch snapshot?
  Gate: ≥~70% coverage for ≥1 season, else CLV stays unmeasurable and the answer is "still can't test."
- **Heavy odds scan → run in BACKGROUND** (the NBA odds table was 22M rows; MLB similar). Materialize
  the reconstructed close to a local parquet once, join cheaply after — same architecture as
  `clv_validation.py --build-cache`.
- Cross-check against `scripts/mlb/clv_report.py` (the existing CLV instrument — but it depends on the
  synthetic `pitcher_props_closing`; the snapshot reconstruction is the trustworthy path).

**Step B — Measure CLV on shadow picks against the bar (the verdict).**
- Shadow picks live in `mlb_predictions.signal_best_bets_picks` (worker still writes them; only the
  public GCS JSON is suppressed). Filter edge≥0.75 OVER, join the reconstructed close, compute CLV.
- **CONFOUND — read this twice:** the live worker serves a **leak-trained model on de-leaked features**
  (it systematically overshoots K, worsening into June → mechanically flatters a directional OVER
  strategy and can manufacture *spurious* positive CLV by biasing *which* pitchers get picked). So a
  positive CLV read on **current shadow picks is PROVISIONAL only.**
- **Pre-register the read before you run it:** PASS only if BOTH halves of §1 clear. If HR clears but
  CLV CI straddles 0 → FAIL (efficient market, the 58% is a streak). If CLV is clearly positive on
  provisional (leak-confounded) picks → it's a *green light to do Step C*, not a resume.

**Step C — Only if Step B is provisionally green: leak-free retrain, then re-measure CLV.**
- `scripts/mlb/training/train_regressor_v2.py --training-start 2024-04-01` (2 Aprils — avoids the
  April-bias trap, see memory). This removes the leak confound so the CLV read is trustworthy.
- Re-run Step B on leak-free picks. Clears the bar on leak-free picks at N≥100 → **resume**:
  `UPDATE nba_orchestration.halt_overrides SET active=FALSE WHERE sport='mlb'` (next `halt_state_writer`
  5 AM ET run reverts to the natural decision). Note: a resume also needs the leak-free `.cbm` actually
  deployed (worker currently serves the leak-trained model), and predictions were STRIPPED from the
  tonight page/frontend on 2026-05-22 — re-exposing them is a separate frontend change in the
  **`/home/naji/code/props-web`** repo.

If any gate fails: document the verdict, leave halted. "A finished research project with an honest
verdict" is a successful outcome — the same standard the NBA arc just held itself to.

---

## 4. DEAD threads — do NOT re-litigate (all pre-registered-tested, all empty)

- **Model features / accuracy.** Model = market (MAE), well-powered no-edge. Mid/high-K niche,
  opponent-lineup feature, the Poisson p_over, the model-market blend — all FAILED their bars.
- **The signal layer.** **0 of 33** signals pass; signal-confluence fails; fewer signals clear +2%
  than chance predicts. The "NBA-style signal pipeline" was the owner's strongest hope — tested
  directly on MLB's 2 seasons, came back empty.
- **Other markets (C2).** All 13 MLB prop markets efficient (519K rows). **Batter props
  (total_bases/hits) backtest = NO-GO** (0/212 subsets, 2026-06-17). Batter build OFF, schedulers
  deleted. MLB betting avenues are exhausted *except* the CLV-on-pitcher-K question above.
- **Home-pitcher bias, steam/line-movement** — both FAIL (the "58% home-OVER" was an `innings≥3`
  look-ahead artifact). **Note the `innings_pitched ≥ 3.0` look-ahead filter in `season_replay.py`** —
  it fabricated the fake home bias; make sure any new backtest does not reintroduce it.

The ONLY live thread is: **does the pitcher-K OVER edge beat a genuine (reconstructed) closing line at
N≥100?** That has never been answerable. Now it is. That's the whole deep dive.

---

## 5. Operational reference

| Need | How |
|------|-----|
| Check MLB halt state | `SELECT * FROM nba_orchestration.halt_state WHERE sport='mlb' AND effective_date >= CURRENT_DATE()-2` |
| Why halted (durable override) | `SELECT * FROM nba_orchestration.halt_overrides WHERE sport='mlb'` — active row forces halt; only un-set resumes |
| Single-pane MLB config | skill `/mlb-best-bets-config` (read-only: fleet, regime, halt, filters, recent CF HR) |
| Shadow picks (still written) | `mlb_predictions.signal_best_bets_picks` (public JSON suppressed; BQ rows usable for CLV) |
| Raw odds time-series (reconstruct close) | `mlb_raw.oddsa_pitcher_props` (5 pitcher markets; `market_key='pitcher_strikeouts'`) |
| Existing (synthetic-dependent) CLV tool | `scripts/mlb/clv_report.py` — cross-check only; prefer snapshot reconstruction |
| Leak-free retrain | `scripts/mlb/training/train_regressor_v2.py --training-start 2024-04-01` |
| Resume output (after a clean PASS) | `UPDATE nba_orchestration.halt_overrides SET active=FALSE WHERE sport='mlb'` |
| NBA CLV reference (the recipe to port) | `scripts/nba/training/discovery/clv_validation.py`, `docs/08-projects/current/clv-validation/00-SCOPE.md` |

**Gotchas:** `bq` CLI hangs in this WSL env → use the Python BigQuery client. Local gcloud/bq default
project is `jett-prod` (WRONG) → always pass `--project=nba-props-platform`. Heavy odds scans → run in
background. Don't `git add -A` (large pre-existing dirty tree). Don't `--set-env-vars`.

---

## 6. Copy-paste kickoff prompt for the new session

> Deep dive on MLB pitcher-strikeout betting: can we clear the pre-registered resume bar and post
> picks again? Read `docs/09-handoff/2026-06-25-mlb-resume-deep-dive-kickoff.md` first, then memory
> `mlb-strikeout-project` and `docs/08-projects/current/mlb-lineup-early-hook/03-FINDING-market-is-efficient.md`.
> The bar (do not move it): OVER edge≥0.75 sustaining ≥58% HR WITH positive CLV (bootstrap CI lower
> bound >0) at N≥100. The new capability: I just built CLV closing-line reconstruction from odds
> snapshots for NBA (`scripts/nba/training/discovery/clv_validation.py`) — port that recipe to
> `mlb_raw.oddsa_pitcher_props` to finally measure MLB CLV (it has never been measurable; capture was
> broken). Do Phase-0 coverage feasibility first, run the heavy odds scan in the background, then
> measure CLV on shadow picks (`mlb_predictions.signal_best_bets_picks`, edge≥0.75 OVER) against the
> bar. Remember the live model is leak-trained → any positive CLV on current shadow picks is
> PROVISIONAL; a clean read needs the leak-free retrain. Pre-register PASS/FAIL before each test. Do
> NOT re-litigate the dead threads (model features, the 0/33 signals, C2/batter markets, home-pitcher,
> steam). Honest verdict either way is the goal.
