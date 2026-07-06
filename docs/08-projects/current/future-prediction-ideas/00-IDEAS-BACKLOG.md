# Future Prediction Ideas — Backlog

**Created:** 2026-07-05 (off-season, opener ~Oct 21 2026) · **Status:** ideation, nothing built
**Source:** 8 parallel ideation agents, one per lens, each grounded in the established findings
below so they push into *new* territory rather than re-deriving what's known.

> **For the future session that picks this up:** this is a menu, not a plan. Nothing here is
> validated — every idea is a hypothesis with a feasibility read. Before building ANY of it,
> respect the "Walls" section and the "Cross-cutting rules." Start from the **Top Priorities**
> shortlist; the per-lens catalog below is the full inventory with detail. Discoverable via the
> MEMORY.md pointer (`future-prediction-ideas-backlog-2026-07-05`).

---

## The Walls (what every idea must respect — these are hard-won)

1. **Point accuracy is MAXED.** Held-out R² predicting the residual from player/context features
   ≈ +0.004 (~0), 3 independent confirmations. **Do not propose "add feature X to the points
   regressor."** Edge lives on the SELECTION / CONFIDENCE / SIZING surface.
2. **UNDER is the durable, profitable side.** UNDER edge≥6 ~61% cross-season; edge≥3 ~56%+.
   High-edge OVER had NO cross-season edge — the 2025-26 OVER boom was a scoring-environment
   anomaly. Tilt every new NBA-points signal UNDER-first.
3. **CLV is the validated arbiter / #1 known lever.** Beating the close is the profit signal, not
   short-run HR.
4. **Line-movement / cross-book signals are repeatedly 2025-26 artifacts.** Everything must clear
   the ≥3/5-season discovery gate (BH-FDR) before it's trusted.
5. **Live graded N is tiny (~175 BB picks) and `prediction_accuracy` is leak-contaminated pre-2026.**
   Train/validate on `load_live_verified_data()` (pre-game `created_at`), walk-forward, shadow-first.
   Sizing decisions are data-blocked until ~mid-2026-27.
6. **Look-ahead is lethal** for anything using lineups/injury/minutes — must use the latest snapshot
   stamped *before tip* (the `minutes_before_tipoff` / `report_timestamp` guard pattern). Grading
   must confirm the player actually played.
7. **New markets/sports are points-locked forks**, not feature flags — a parallel model + line
   feature, not a tweak. Prior "improve don't expand" verdict stands *except* where an idea dodges
   both the points-lock and the clone-cost (see WNBA).

---

## Top Priorities (cross-cutting synthesis, best-first)

Ranked by (edge plausibility × feasibility × backtestable-now). Tier A = do this off-season on
stored data; Tier B = build now, gate live; Tier C = bigger bets / season-open probes.

### Tier A — backtestable NOW on stored data, low lift

1. **Use the stored `over_price`/`under_price` columns for selection.** The pipeline snapshots
   two-sided prices per book but has *never* used them for pick selection (everything to date is
   line-value based). Two low-difficulty, fully-backtestable wins:
   - **No-vig probability edge:** de-vig the two-sided price into a fair P(under), compare to the
     model's implied P(under), bet the gap. A proper "value" gate that also down-weights
     heavily-juiced (sharp-priced) picks. *(microstructure #1)*
   - **Best-number / line-shopping capture:** enrichment currently quotes a *priority* book
     (DK>FD>MGM…), not the *best* book. Always taking the best line across the 12+ books we already
     ingest is free EV; quantify the HR uplift and surface best-book in the payload. *(microstructure #3)*

2. **New prediction targets: Rebounds / Assists / 3PM props, UNDER-tilted.** BettingPros lines are
   **already backfillable to 2021** (`bettingpros_player_rebounds_props` / `_assists_props` tables
   exist; scraper supports rebounds/assists/threes market types), actuals are in
   `player_game_summary`, projection-consensus signals come free from NumberFire/Dimers. Rebounds &
   assists are **lower-variance than points and more role/minutes-driven** — where our existing
   features may retain predictive power (the R²≈0 wall is points-specific). This is the strongest
   counter to "the points model is done" and is backtestable this off-season with existing tooling.
   Caveat: discrete low-mean grids make the O/U coarse — recompute edge in each target's own units;
   a "3-point edge" heuristic does NOT transfer. *(player-targets #1-3)*

3. **Distributional tail-probability bet using the p25/p50/p75 the fleet already serves.** The
   MultiQuantile model emits quantiles; reconstruct a per-pick CDF and compute P(points < line)
   directly, then bet where it beats the book's implied prob. This directly attacks the *documented*
   reason the current edge-only P(win) calibrator is flat: edge collapses the distribution to one
   number and is tier-confounded. Generalizes the one quantile signal that already works
   (`quantile_ceiling_under`) from a corner case to a continuous edge. *(modeling #1)*

4. **Travel / schedule-density microstructure feature.** Timezone crossings, cumulative flight
   miles (static arena lat/long table, ~30 rows), 3-in-4 / 4-in-6 density, circadian road games —
   the continuous version of the validated `b2b_fatigue_under` (63.2% cross-season). The rare idea
   that is BOTH genuinely new information AND fully backfillable across all 5 seasons. Must show
   incremental edge beyond `is_b2b`/`days_rest`. *(novel-data #2, player-state #8)*

### Tier B — build now, deploy gated (respect the N-block and shadow-first discipline)

5. **Explicit minutes-projection model → minutes-gap signals.** Minutes is the master latent
   variable for every counting stat. A dedicated minutes head (RotoWire projected_minutes + injury
   + rest + blowout_risk) that disagrees with the line's implied minutes is orthogonal information,
   reusable for assists/rebounds too. Pair with **injury-return-ramp UNDER** (first 1-3 games back
   from a ≥2-game absence, minutes-capped, line still anchored to healthy baseline) and the
   **minutes-shortfall UNDER** (RotoWire projects ≥3 min below season avg — the missing UNDER mirror
   of the existing `minutes_surge_over`). All UNDER-tilted, all operationalize minutes-as-master.
   *(player-state #1, #2, #7)*

6. **Multi-feature confidence meta-model — a learned P(pick wins).** Extend the flat edge-only
   calibrator into a small, heavily-regularized classifier over SELECTION-surface context (edge,
   line level, quantile IQR, no-vig implied prob, regime, whole-line flag, CLV proxy, national-TV).
   The natural home for the ~30 signals that each independently correlate with HR. **Highest overfit
   risk on the list** — pre-register features, logistic-first, monotone edge constraint, walk-forward
   only, ALL graded live predictions (not just BB-selected) to fight small N. *(modeling #2)*

7. **Portfolio correlation-aware daily-card sizing.** Stop treating the daily list as N independent
   singles. Build the pairwise correlation matrix (same-game co-directional +ρ≈0.27-0.31,
   opposite-team +0.44, cross-game ≈0) and allocate stakes for risk-adjusted growth. The principled
   generalization of the pre-registered ⅓-Kelly same-game haircut. Pure sizing, zero prediction
   dependency, all data on hand — but sizing *deployment* is N-blocked until mid-2026-27, so build
   the machinery now. *(bet-products #5, modeling #5)*

8. **Injury-report resolution TIMING / velocity.** Not *whether* a star is out but *how late* the
   status flips (GTD→OUT in the 90-30 min window) — the sharpest structural mispricing (teammate
   usage repriced with a lag). Collection infra was just built (2026-06-29), so backtest is thin
   until ~2027; forward-collect now, validate live. *(novel-data #1)*

### Tier C — larger bets / season-open probes / honest reconsiderations

9. **WNBA points props — the one honest "expand" reconsideration.** The softest genuinely-adjacent
   market; our SELECTION edge is *larger* in soft markets. Dodges both the points-lock (still points)
   and the MLB-clone cost trap (still basketball — stats.wnba.com mirrors the nba_api endpoints we
   already call; Odds API + BettingPros carry WNBA props). Run as a *thin fork* (league dimension on
   existing services), NOT a parallel stack. Gated by short season → ~1.5 seasons before edge is
   testable. **NBA Summer League (July)** is the near-free annual softness-sensor / dress-rehearsal
   precursor. *(competitive #1, #2)*

10. **Referee-conditioned game-total UNDER + 1H/1Q derivative totals.** Team/game targets using data
    already ingested (`covers_referee_stats.over_percentage` × `nbac_referee_assignments`, team
    pace/efficiency summaries). Referee assignments post game-morning and are under-weighted;
    derivative half/quarter totals are softer than the razor-sharp full-game total. UNDER-only.
    *(team #1, #3)*

11. **Predict-the-close / CLV as a pre-game signal.** Turn CLV from a reactive T-3h gate into a
    forecast of the closing line from the morning snapshot, bet ahead of the move to lock positive
    CLV by construction. High ceiling but you're essentially forecasting sharp money; single-season
    snapshot density limits training. *(microstructure #2, competitive #5)*

---

## Dead ends & do-not-pursue (honest flags from the agents)

- **Steals / blocks props** — near-Poisson, mean ~1, one event flips it. SNR floor too low for 55%.
- **Point spread & full-game total (main markets)** — the sharpest, most-modeled markets; commodity
  efficiency-differential models are fully priced. Only useful as a CLV/efficiency benchmark.
- **Altitude / arena micro-factors** — Denver altitude is the most famous NBA "edge"; almost
  certainly priced. Test only as a free add-on to the travel table (#4).
- **NCAA / G-League / international** — softness is real but there's a **data wall**: no nba_api-grade
  point-in-time source; incompatible with the zero-tolerance-defaults doctrine. Data-engineering
  green-field, not a fork.
- **Injury-news speed / line front-running** — real mechanism but a **latency wall**: cron-cadence
  feeds, zero bet-placement code, books move in seconds. Same reason MLB's early-hook angle died.
  Scoped latency feasibility probe only, not a build.
- **Promo / soft-book / bonus harvesting** — real money but brutally non-scalable (limits/bans,
  one-time boosts). Keep as a free precision bump for the manual bettor (take the best of the books
  we already scrape), not infrastructure.
- **Market-making / exchange liquidity** — a different business (two-sided quoting, inventory, capital),
  not an extension of the points engine.
- **OVER-stacked same-game parlays** — collides with the OVER-fragility finding; if SGPs at all,
  UNDER-stacked in slow/low-total games only, and only if a cache backtest shows books don't already
  correlation-adjust their SGP pricing.
- **Prop-derivative synthesis (price PRA off our points edge)** — the non-points variance is noise we
  can't price; likely dilutes rather than transfers edge. Skip unless alt-line calibration (below) proves
  our distribution's tails are trustworthy.

---

## Full idea catalog by lens

Each entry: **angle** · why-edge · data · feasibility(risk) · relation-to-prior. Tier tags reference
the shortlist above. Ideas already surfaced in Top Priorities are marked ⭐.

### Lens 1 — New player-level targets beyond points
1. ⭐ **Rebounds UNDER** — role/minutes-driven, lower-variance, softer secondary market. Backfillable
   (BP rebounds table exists). Med (grid coarseness, minutes-uncertainty). Novel target; R²≈0 is
   points-specific. **Strongest new-target candidate.**
2. ⭐ **Assists UNDER for playmakers** — hostage to teammate FG% + lineup; we hold that context.
   Backfillable. Med-High (noisier than rebounds; look-ahead on teammate-out). Novel + extends our
   injury/lineup edge.
3. ⭐ **3PM UNDER anchored on attempt-rate** — fade make-streaks with stable attempts; native market
   for the validated `hot_3pt_under` reversion. Backfillable. Med (coarse 1.5-3.5 grid). Extension.
4. **PRA / combo props** — softest, highest-hold market; aggregate independent component models
   accounting for shared-minutes covariance. Line availability UNCONFIRMED (likely new pull). Med-High,
   gated behind #1-3.
5. **Turnovers O/U** — usage×pace×pressure. Actuals backfillable; **line source unconfirmed**. Med model /
   High line-availability. Exploratory — check lines first.
6. **Double-double / triple-double YES/NO** — classification on joint thresholds; fade over-juiced YES.
   Depends on #1-2; DD/TD odds not ingested. High. Phase-2 candidate.
7. **Minutes O/U** — the master variable sold as a prop, reacts slowly to rotation news. Lines thinly
   offered / not ingested; backtest likely impossible. Med model / High market. Feasibility-check only.
8. **Steals/blocks** — DEAD (variance floor). Do not build.

### Lens 2 — Team / game-level targets
1. ⭐ **Referee-conditioned game-total UNDER** — low-`over_percentage` crews AND model agrees. All data
   ingested. Med (partially priced; season-cumulative ref N regresses — require N≥30 crew games).
2. **Game-total via pace×efficiency, UNDER-only** — raw ingredients on hand. Med-High (SHARPEST market;
   research probe not near-term revenue).
3. ⭐ **1H / 1Q derivative totals** — softer than full-game; clean PBP labels; starters reduce noise.
   **Confirm Odds API returns half/quarter total keys** (likely scraper extension). Med.
4. **Team 3PM O/U** — lift `hot_3pt_under` reversion to team level. Team-3PM prop lines unconfirmed
   (likely new key/scraper). Med-High.
5. **Team-total (single side) UNDER** — softer derivative, decouples opponent noise. Confirm team-totals
   key. Med (books derive team-totals from total+spread → residual softness may be thin).
6. **Blowout-risk classifier → total UNDER + feature** — margin labels + spread interaction; reusable
   feature more than a standalone bet. Med.
7. **Point spread (main market)** — near-dead; sharp-syndicate territory. SKIP for stakes.
8. **Race-to-N / largest-lead exotics** — very soft but low limits + lines likely absent. High. Park.

> Single cheapest next step for this whole lens: **confirm Odds API/BettingPros coverage of team-props
> and half/quarter/derivative market keys** — it gates ideas 3/4/5/8.

### Lens 3 — Novel data sources & information edges
1. ⭐ **Injury-report timing/velocity** (Tier B #8) — late GTD→OUT flips; sharpest structural mispricing.
   Buildable from existing hourly ESPN/`nba_injury_snapshots`/Bluesky feeds. Med (look-ahead lethal;
   forward-collect only, thin until ~2027).
2. ⭐ **Travel / schedule-density microstructure** (Tier A #4) — timezone/miles/3-in-4. Fully backfillable
   from schedule + static arena table. Low (may be partly priced beyond b2b).
3. **Referee crew × player-FTr interaction** — crew whistle tendency × high-free-throw-rate scorers.
   Data ingested (assignments × Covers). Med (game-level ref effect may be priced; per-player noisy —
   pairing signal).
4. **Coach blowout-benching profiles** — per-coach hook aggressiveness from PBP × pre-game spread →
   starter UNDER. Backfillable. Extends blowout/starter-under family (UNDER).
5. **Confirmed-lineup role-change detection** — RotoWire projected minutes vs recent actuals → line lags
   new role. Med (must use projected, not post-game). Novel; extends the "line lags reality" thesis.
6. **Cross-book line origination / steam timing** — which book moves first as a Pinnacle-substitute.
   From existing multi-book snapshots IF cadence is fine-grained enough. Med-High (2h cadence may be too
   coarse; single-season). Extends CLV.
7. **DFS ownership (Stokastic) as public-shading proxy** — high projected ownership → shaded line → UNDER.
   Scraper built 2026-06-29 (forward-only). Low (already-priced risk; no history until ~2027).
8. **Arena/altitude** — DEAD-adjacent (priced). Free add-on to the travel table only.

### Lens 4 — Market microstructure & CLV
1. ⭐ **No-vig probability edge** (Tier A #1) — de-vig two-sided price vs model P(under). Stored prices,
   unused. Low (model prob calibration is the weak link — validate implied-prob vs realized HR by decile).
2. ⭐ **Predict-the-close** (Tier C #11) — forecast the closing line, bet ahead. Needs a build + dense
   open→close pairs (2025-26+). Med-High (forecasting sharp money; class-imbalanced).
3. ⭐ **Best-number capture / line shopping** (Tier A #1) — quote best of 12+ books, not priority book.
   Stored. Low (best number often on soft/low-limit books; filter stale outliers vs consensus).
4. **Reverse-line-movement vs VSiN public %** — line moves against the crowd = sharp tell. Both ingested.
   Med (VSiN prop-level coverage may be thin; must pass discovery gate, UNDER-first).
5. **Book-count / liquidity as a confidence weight** — universal reliability multiplier, not a fire
   condition. Stored (COUNT DISTINCT bookmaker). Low (non-monotonic across book regimes — cf. the
   `sharp_consensus_under` reversal; calibrate on current regime only).
6. **Steam velocity (Δline per unit time)** — isolate informed fast moves; block on steam-against-us.
   Timestamped snapshots exist but 2h cadence undersamples; T-30 sweep helps the tail. Med. Extends CLV.
7. **Per-book sharpness anchor** — rank books by historical closeness to outcome, fade recreational
   divergence from the sharpest. Needs an offline sharpness study. Med-High (no Pinnacle; prop sharpness
   unstable; overfit risk).
8. **Price-move (juice) vs line-move coherence** — juice shifts before the line breaks → lead on the move.
   `over_price`/`under_price` deltas computed in the movements view but unused downstream. Med (juice noisy;
   near-close only). Genuinely unmined dimension.

### Lens 5 — Player-state / minutes / injury / role
1. ⭐ **Injury-return ramp UNDER** (Tier B #5) — first 1-3 games back, minutes-capped. Mostly in-pipeline.
   Low-Med (pre-tip snapshot discipline). Novel.
2. ⭐ **Explicit minutes model → minutes-gap signals** (Tier B #5) — biggest structural lever here;
   reusable for any counting stat. Med-High.
3. **Foul-trouble-prone × high-whistle-ref UNDER** — minutes truncation. In-pipeline. Med (ref pre-tip
   reliability; drop ref cross if unreliable, use foul-rate × pace-up alone).
4. **"Questionable-that-plays" limited-role UNDER** — Q players who suit up are minutes-managed; line
   didn't fully adjust. In-pipeline. Low-Med. Extends the injury-status feature into a selection signal.
5. **Teammate-OUT redistribution — the UNDER complement** — invert `star_out_rescue` for squeezed
   tertiary scorers. Reuses existing supplemental context. Low (validate incremental, not headline;
   double-count risk).
6. **Blowout-risk × big-favorite starter UNDER** — add the missing pre-game *spread* interaction to
   `blowout_risk_under`. In-pipeline. Low. Cheap high-confidence improvement.
7. ⭐ **Minutes-shortfall UNDER** (Tier B #5) — RotoWire ≥3 min below avg; the missing mirror of
   `minutes_surge_over`. Nearly free (negate existing threshold). Low.
8. ⭐ **Dense-schedule deep fatigue UNDER** (folds into Tier A #4) — 3-in-4/4-in-6 beyond b2b, older/
   high-load stars. In-pipeline (feature_40). Low-Med (correlated with b2b — prove incremental).

### Lens 6 — Modeling technique (selection, not point accuracy)
1. ⭐ **Distributional tail-probability bet** (Tier A #3) — full quantile CDF vs implied prob. Quantiles
   serve live. Med (MultiQuantile-only coverage → small N; keep CDF shape 1-parameter). Attacks the
   flat-calibrator wall directly.
2. ⭐ **Confidence meta-model — learned P(win)** (Tier B #6) — GBM over selection context. Med-High.
   **Highest overfit risk** — pre-register, regularize, walk-forward.
3. **Model-reliability regime gate (per model × day)** — predict if a model's picks clear breakeven
   today (rolling HR/Brier + regime + days-since-retrain). Targets the diagnosed March root cause with
   pre-tip data. Med (coarse model-day unit; keep soft weight, don't re-learn the auto-halt).
4. **Conformal prediction intervals** — distribution-free coverage-guaranteed bands, fleet-wide (residual-
   based, not quantile-limited); bet when line is outside the interval. Low-Med (regime shift breaks
   exchangeability — rolling recalibration + Mondrian/tier-conditional). Generalizes `quantile_ceiling_under`.
5. ⭐ **Learned fractional-Kelly sizing** (Tier B #7) — stake from calibrated P(win)+odds. Downstream of
   #1/#2. Med (only as good as calibration; N-blocked → build now, deploy later; ≤½-Kelly cap).
6. **Quantile SKEW / relative-IQR as a signal** — third moment beyond the validated IQR-width finding
   (narrow IQR → +8pp). Quantiles live. Low (MultiQuantile-only N; pre-register, BH-FDR). Cheap.
7. **Bayesian per-player reliability shrinkage** — shrink per-player HR/bias (not the point) toward tier
   prior; trust historically-nailed players. Med (leakage/point-in-time; small per-player N; stale on
   role change). Novel complement to the meta-model.

### Lens 7 — Bet products & correlation structure
1. **Star-OUT correlated singles bundle** — one injury thesis → 2-3 correlated singles (teammate OVER +
   team-total UNDER), staked as one risk unit (eats the ⅓-Kelly haircut). Injury/lineup feeds on hand;
   needs a usage-vacuum estimator. Med. Positive-correlation-by-design case.
2. **Pace-up multiple-OVER SGP** — books pricing legs near-independently misprice the positive within-game
   correlation. Needs SGP quote capture. High + **collides with OVER-fragility** → probably dead for OVER.
3. **UNDER-stacked SGP in slow/low-total games** — the correct-direction version of #2. High (SGP-pricing
   dependency; real intra-game UNDER ρ modest, CI touches 0). Best-founded SGP candidate.
4. **Alt-line ladder for UNDER** — buy points for better prob-per-dollar; UNDER's flat edge across lines
   makes it convex. **Needs `player_points_alternate` capture** + a calibrated per-line distribution.
   Med-High. Cleanest "product not prediction" lever, gated on calibration (ties to modeling #1/#4).
5. ⭐ **Portfolio correlation-aware card sizing** (Tier B #7) — covariance-aware allocation. All data on
   hand. Med (noisy covariance at 3-4 picks/day). Lowest-risk, highest-certainty; generalizes the haircut.
6. **Middling from intraday line movement** — take the opposite side at a moved number for a free-roll
   middle. Snapshots exist (2025-26). Med (rare/thin; needs live re-betting — we're daily-batch).
7. **Live/in-game UNDER after hot Q1** — behavioral overreaction + mean-reversion/blowout. **Needs a live
   odds feed + sub-minute execution.** High. Season-3+ moonshot.
8. **Prop-derivative synthesis (PRA off points edge)** — DEAD-likely (non-points variance is noise). Skip
   unless #4 calibration proves out.

### Lens 8 — Adjacent leagues & competitive red-team
1. ⭐ **WNBA points props** (Tier C #9) — softest genuine adjacency; thin fork not a clone. Med (short
   season → ~1.5 seasons to test; lower limits). The honest "expand" reconsideration.
2. ⭐ **NBA Summer League** (Tier C #9) — near-free annual softness sensor + off-season dress-rehearsal.
   Med (tiny sample, low limits — a harness, not a profit center).
3. **NBA assists/rebounds props** — the already-blessed cheap "data clock" (live since 2026-04-06). Keep
   running, reassess ~Feb-Mar 2027. Don't accelerate; don't train on the playoff-biased weeks. (Overlaps
   Lens 1 #1-2.)
4. **NCAA / G-League / international** — DEAD (data wall; incompatible with zero-tolerance defaults).
5. ⭐ **Operationalize CLV discipline** (Tier C #11) — bet-early/grade-at-close as the *primary* selection
   loop; the red-team capability we're most built for. Low-Med (execution speed at open is the gap).
6. **Injury-news speed front-running** — DEAD-ish (latency wall; no bet-placement code). Latency probe only.
7. **Correlated SGPs as an edge** — reframe our known same-game correlation liability as an asset. Med
   (books increasingly correlation-adjust; low limits). Cache-backtest vs SGP prices before any build.
8. **Promo / soft-book harvesting** — real but non-scalable. Free precision bump for the manual bettor only.
9. **Market-making / exchange** — out of scope (different business).

---

## Cross-cutting rules for whoever executes

- **Backtest on real book lines, not the raw-model proxy**, and per-season — the raw-edge proxy is what
  produced the retracted "edge-5 money zone" / OVER findings. Clear breakeven cross-season (≥3/5) before
  promoting anything.
- **UNDER-first.** Validate the UNDER side before even looking at OVER for any new NBA-points signal.
- **Shadow-first, then live N≥30 / HR-gate promotion** — the established path for every signal here.
- **Confirm line availability BEFORE modeling** for every new-target / derivative / alt-line idea — it's
  the cheapest de-risking step and kills several ideas outright (turnovers, minutes, team-props, PRA).
- **Watch the small-N + leakage trap** on the modeling/sizing ideas — `load_live_verified_data()`,
  walk-forward, pre-registered features. Sizing deployment is N-blocked until ~mid-2026-27.

## Suggested sequencing (if/when the season reopens this)

1. **Off-season, now:** the Tier A quartet — they're backtestable on stored data with existing tooling and
   don't touch the serve path: (1) no-vig + best-number from stored prices, (2) rebounds/assists/3PM UNDER
   backtests, (3) distributional tail-prob using served quantiles, (4) travel/density feature. Plus the
   free line-availability audit for team-props/derivatives/alt-lines.
2. **Build-now / gate-live:** minutes model + injury-return/shortfall UNDER, confidence meta-model,
   portfolio sizing machinery, injury-timing forward collection.
3. **Season-open probes:** predict-the-close, referee/derivative totals, WNBA thin-fork scoping, Summer
   League dress-rehearsal, CLV-discipline operationalization.

Nothing here changes live pick behavior until explicitly built, validated, and signed off.
