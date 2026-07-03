# 10-Agent Whole-System Review — Improvement Ideas & New Angles (2026-07-03)

**Context:** Off-season, halt active. 10 parallel agents each studied a distinct slice of the
system (data sources, CLV/microstructure, signals, bet-sizing, regime/halt, narrative,
ensemble/calibration, alt-markets, pipeline reliability, adversarial red-team) with the memory
loaded so they'd push past already-refuted ground. This is the synthesis.

**One concrete deliverable already landed:** `tests/scrapers/unit/test_dknetwork_betting_splits.py`
(53 tests, all pass) — de-risks the DK Network season-open smoke test. `resolve_team()` was
traced and empirically confirmed to handle all 30 NBA franchises (it keys off the *nickname*, not
the prefix code, so it's robust even if DK's NBA prefix differs from MLB). Residual risk is
format-only (a bare 2-letter code with no nickname), confirmable only on a live game day. **File is
untracked — commit it.**

---

## The two highest-confidence findings (independent agents converged)

### A. There is a fully-written, idle isotonic `edge→P(win)` calibrator. Wiring it unlocks a whole tier.
`ml/calibration/edge_calibrator.py` (per-`(family,direction)` `IsotonicRegression`, with fit/save/load)
is complete and **imported nowhere in `predictions/` or `ml/signals/`** (verified: zero serve-path
imports). Both the bet-sizing agent and the ensemble/calibration agent found this independently.

Consequences of it being idle:
- The system has **no calibrated win-probability in production.** Every pick is ranked by a
  hand-weighted `composite_score`; `confidence_score` is an explicit heuristic, not a probability.
- `model_performance_daily.brier` is a **pseudo-Brier** — it plugs `edge/15` in for probability. Not
  a real calibration metric.
- Bet sizing is effectively **flat** (`bet_size_units` = 1.0, with one 2-day-old `×0.67` same-team
  co-directional haircut in `pipeline_merger.py`). Kelly is impossible without a calibrated `p_win`.
- The **MLB bankroll simulator** (`scripts/mlb/bankroll_simulation.py` — flat/Kelly/edge-prop/ultra,
  drawdown + Monte-Carlo) is directly portable to NBA and there is no NBA equivalent.

**This is the highest EV-per-effort lever in the whole review.** The payoff is honest: given point
accuracy is dead (residual R²≈0) and HR is already high, sizing's win is **variance/drawdown
reduction (surviving a March-type collapse) + modest ROI uplift**, not a big HR jump. Fit **UNDER
first** (durable); treat OVER's curve as provisional (2025-26 anomaly).

### B. The CLV UNDER edge — the one surviving off-season signal — is validated on snapshot density the live pipeline does NOT produce.
`line_converging_under` (shadow) + `clv_diverge_under_block` (active) are ~80% wired. But the
`betting_lines` scraper workflow **ends at 8 PM ET** (`config/workflows.yaml:248` — confirmed), and
NBA games tip 7:30–10:30 PM ET. So for the whole late slate the "closing" line is captured at
T-2h+ (often T-3.5h to T-6h), **not the to-the-tip snapshot the +15.8pp UNDER edge (p=5e-26,
N=1,155) was measured on.** Extending scraper cadence to true tip-off is **season-open-blocking** —
you cannot retroactively capture closes, and every other CLV item is degraded without it.

---

## Cross-cutting theme: the system is fragile exactly at season open

The red-team's #1 finding, reinforced by others: **the entire dynamic-protection layer fails OPEN
when its trailing window is empty** — which is precisely the state at 2026-27 tip-off.
- Edge auto-halt (`regime_context.py:220`), TIGHT-market OVER-floor raise (`:150`), cautious-regime
  tightening (`:347`), and COLD-signal health suppression all default to "off" / 1.0x with no
  history. For ~1-2 weeks the system exports on **static 2025-26-tuned floors only, with zero
  adaptive protection**, exactly when the freshly-retrained fleet is least calibrated (Nov 2025 had
  the worst pred_bias in the dataset).
- **Fix:** a season-open warmup guard — when `days_sampled < 3`, fail *closed* (raise OVER floor,
  disable OVER rescue, require `real_sc≥2` on all UNDERs). Small change, biggest single exposure.

---

## Ranked action list

### Tier 0 — Season-open-BLOCKING (must ship before opening night; can't be backfilled)
1. **Extend odds-scraper cadence to true tip-off** (`workflows.yaml` `end: 20→23` + per-game T-30
   snapshot; redefine "closing" as last snapshot with `minutes_before_tipoff ∈ [0,45]`). Keystone
   for all CLV work. Watch Odds API quota. *(Finding B)*
2. **Season-open warmup guard — fail closed while `days_sampled < 3`.** *(red-team #1)*

### Tier 1 — High EV, mostly pre-built, off-season backtestable
3. **Retrain + wire the isotonic calibrator → emit `p_win` per pick** (UNDER first, per family×dir;
   rides existing `critical_features` JSON, no DDL). Fixes the fake Brier as a byproduct. *(Finding A)*
4. **Port the MLB bankroll sim to NBA; prove fractional-Kelly (¼) vs flat on the 5-season cache**
   at real BettingPros odds. Depends on #3. Frame win = drawdown control. *(bet-sizing)*
5. **Promote `line_converging_under` shadow→active** after #1 lands and live N≥30 / HR≥58%. *(CLV)*

### Tier 2 — Cheap correctness fixes (ship anytime; protective)
6. **Fix the dead `book_count` guard.** `supplemental_data.py` never puts `book_count` into
   `book_stats`, so the `< 5` liquidity guard in `book_disagreement` / `book_disagree_over/under` /
   `sharp_consensus_under` silently never fires. One CTE join. *(CLV)*
7. **Port book-count-aware std thresholds to the UNDER *filters*.** `high_book_std_under_block`
   (≥0.75) and `counter_market_under` (≥1.0) use flat thresholds the code itself calls "noise" under
   the 12-book regime — they over-block the durable UNDER side. Signal side was already fixed
   (Session 522); filter side wasn't. *(red-team #2)*
8. **Fail-closed the 3 latent null-guard bugs** before any promotion: `mean_reversion_under.py:52`
   (`over_rate or 0` defeats the high-scorer exclusion), `book_disagree_under.py:46`,
   `whole_line_precision.py:65` (`0.0` line reads as whole number). All shadow now = latent, not
   live. *(red-team #3)*
9. **Enforce a fleet correlation budget at enable-time** (r<0.95 vs enabled models + ≥1 non-CatBoost
   floor). Diversity is monitored but never enforced → the Session 487 all-LGBM-clone collapse (kills
   `combo_3way`/`book_disagreement`) can silently recur. *(ensemble #3)*
10. **Blank/recompute the hardcoded `UNDER_TOXIC_OPPONENTS` frozenset** (`{MIN,MEM,MIL,IND}`, "last
    validated 2026-02-28") — it's a 2025-26 roster property that will misfire on stale team identities
    after offseason trades. Blank it for month 1. Add the missing 2026 key to
    `FALLBACK_SEASON_START_DATES`. *(red-team #5, process)*

### Tier 3 — New research (backtest-then-shadow; each needs the discovery gate ≥3/5 seasons)
- **Best new signal hypotheses** (UNDER, favor cross-season power): `matchup_pace_squeeze_under`
  (slow opp × line≥22 interaction) and `whole_line × high_line_under` combo — both build on
  already-validated 5-season components and directly attack the `real_sc=1` UNDER drought.
  Secondary: `star_out_absorber_under` (rank-6+ usage-redistribution UNDER), `high_usage_regression_under`.
  *(signal agent — full list in transcript)*
- **Calibrated abstention** (skip picks whose calibrated `p_win` Wilson-LCB < 52.4%) — the
  principled per-pick version of the fleet-wide edge-halt. Depends on #3. *(ensemble #2)*
- **Continuous regime-conditional signal weighting** — replace the binary TIGHT OVER-gate with a
  `regime × direction` multiplier table; directly implements the open `downtrend_under` /
  `mean_reversion_under` "LOOSE-market-only" promotion gate. *(regime #2)*
- **Leading same-day edge-availability index** — halt on *today's* pre-tip pred-vs-line compression
  instead of waiting 3 graded days (the reactive halt is why March 8 slipped). *(regime #1)*
- **Algorithm-version-churn guardrail** — freeze config deploys during TIGHT/degrading regimes;
  March 2026 had 10+ algo versions vs 1 in January, the one collapse-cause with zero mitigation.
  Cheapest March-specific fix. *(regime #4)*
- **New backfillable data (only 2 survive the "already-ingested" filter):** (1) **Pinnacle/sharp-book
  line** — the one market input structurally absent (whole fleet is recreational books); high EV,
  but forward-collect only + geo/Cloudflare risk. (2) **Defender-availability matchup** — "the guy
  who usually guards him is Out" from existing `nbac_play_by_play` + injury report; fully
  backfillable, no new scraper. *(data agent)*
- **Narrative next wave:** `br_roster_changes` is the unlock — **post-trade / new-team debut window**
  (UNDER, role dilution) is the only narrative idea fully backfillable today, outside the 60
  features, and not yet signaled. *(narrative agent)*

### Tier 4 — Reliability (close the "COMPLETE-but-garbage" hole)
- The canary + `expected_outputs` verify **row-count + freshness only** — nothing catches
  `COMPLETE`-but-all-zeros (the `nba_tracking` drives bug, Jan shot-zone zeros) or partial coverage
  (1 of 156 rows reads healthy). Add per-source value-sanity (`COUNTIF(key!=0)/COUNT(*)`) +
  cardinality-vs-schedule checks to the canary. First target: `nba_tracking_stats` drives (open
  incident, still all 0.0). *(reliability agent)*

---

## Alt-markets verdict (asked explicitly): CONFIRM SKIP, bank the cheap option
Rebounds UNDER is the best candidate (maps onto existing rest/pace/blowout UNDER mechanics, softer
market). But it's **not** cheap: the historical *lines* don't exist (BettingPros has 19 scattered
rebound-days vs 979 points-days; Odds API processor hardcodes `!= 'player_points': continue`), and
the pipeline is points-*forked* not points-*configurable* (~1.5-2 wks + a line-acquisition tail).
**Cheap move the prior review missed:** turn on the free BettingPros rebounds/assists daily scrape
now (data clock only, ~zero marginal cost) so a real backtest series exists by 2026-27 mid-season.
Don't fork the model until that data shows an edge. *(alt-market agent)*

---

## Explicitly refuted / do-NOT-build (save future cycles)
- More model **features** (residual R²≈0, now a 4th independent confirmation).
- Any **OVER** microstructure/narrative/scoring-env signal — 2025-26 anomaly; OVER floor stays static
  edge-6; scoring-env gate REFUTED (no forward-detectable OVER regime).
- No-vig / juiced-over "fade" and price-CLV-as-direction (price carries no direction signal; only
  *line* movement does). No-vig is filter-only, low priority.
- Fleet-disagreement "trust" signal (was an edge proxy; sign inverts within edge band).
- Bias-velocity siren, drawdown-stops (all beaten by edge-halt); relaxing the late-season train cap.
- Travel/rest/fatigue narrative angles (already model features AND 5 existing UNDER signals).
- Flight-delay/weather travel feed (teams fly charter; commercial APIs can't see it).
- `nba_tracking` drives-based signals (scraper writes 0.0 — fix the scraper, don't signal on it).

---

## Recommended sequencing
1. **Commit the DK test file** (done work, untracked).
2. **Tier 0 (#1, #2)** — the only two truly season-open-blocking items; schedule for pre-opening-night.
3. **Tier 1 #3 → #4** — calibrator then bankroll sim; the highest-leverage build, all off-season
   backtestable, both prerequisites already ~80% written.
4. **Tier 2 quick fixes** (#6-#10) — batch them; each is small, protective, and independent.
5. Tier 3/4 research as bandwidth allows — all gated shadow-first, no live deploy while halted.

Nothing here deploys live now (halt active). The through-line: **the edge is entirely on the
selection/confidence/sizing surface, none on point accuracy** — and the two biggest wins
(calibration→sizing, CLV closing-line capture) are things the system already half-built and left idle.
