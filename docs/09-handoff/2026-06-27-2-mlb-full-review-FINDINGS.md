# MLB full review — tried / failed / open map + web-sourced shortlist + recommendation

**Date:** 2026-06-27 · **Session:** answers the 2026-06-27 kickoff
(`2026-06-27-mlb-full-review-and-web-scan-kickoff.md`).
**Method:** 4 parallel repo agents (efficient-market finding verify, chronological blow-by-blow,
tooling+Pinnacle feasibility, live operational state) + a 102-agent `deep-research` web workflow
(20 sources fetched, 65 claims extracted, 25 adversarially verified at 2/3-refute, 12 confirmed /
13 killed).

## TL;DR

**The verdict holds and is now externally corroborated: stay halted, information product only.**
Independent web research reaches the *same* conclusion the internal work did — sharp/professional
bettors do **not** beat MLB starter-strikeout props with prediction models; the only structurally
credible outside angle is **hold-reduction / line-shopping**, which is (a) not a prediction problem,
(b) capped by limits ($200–300, often $10–50) so it can't scale, and (c) has its highest-prior
sub-case — the **sharp-vs-retail/Pinnacle divergence edge — REFUTED** (Pinnacle/Circa deprioritize
props and don't post sharp K lines; "bet stale retail when the sharp book disagrees" lost 0-3 in
verification). No §4 frontier survived contact with the evidence at a quality high enough to justify a
scoped project. Net new actionable work: **near-zero** — one optional ~1–2 credit API coverage check,
plus map corrections.

---

## 1. The pre-registered bar (unchanged, quoted)

> **Resume bar:** OVER edge≥0.75 sustaining **≥58% HR WITH positive CLV (bootstrap 95% CI lower
> bound > 0) at N≥100.** Both halves required; CLV is decisive.

The web research independently validates *why* CLV is the decisive half: **CLV is a trustworthy profit
proxy specifically in efficient markets** (Unabated, 3-0). The retail K market is efficient → our
negative shadow-OVER CLV (−0.12 K, 19% positive) is **meaningful evidence against an edge, not noise.**
The opposing claims ("CLV is meaningless for props," "CLV over 200+ bets is the single reliable edge
indicator") were both refuted 0-3 — CLV is neither useless nor a silver bullet here; it's a valid
*negative* signal.

---

## 2. Tried / failed map — refreshed, with corrections to the kickoff doc

The kickoff §3 dead list is **substantially accurate** (8/10 claims confirmed to exact figures). Four
corrections / clarifications surfaced:

| Item | Kickoff said | Correction (sourced) |
|------|--------------|----------------------|
| **UNDER clean cross-season** | "49.5%, worse with edge" | Docs 03/04 actually show **45.5% (2024), 45.8% (2025)** all-starts UNDER hit. The 49.5% figure isn't in those two docs (may be a different slice/an ROI-vs-HR conflation). **Verdict unchanged** — both are far below breakeven. Reconcile the number before quoting it again. |
| **Batter props 0/212** | listed in dead list | Confirmed real but sourced from the **2026-06-17 batter backtest** (0/212 subsets clear breakeven), not docs 03/04. Build OFF, schedulers deleted. |
| **Closing-line capture** | implied working | **Was never actually fixed.** The 2026-05-21 "fixed" claim is wrong — burst schedulers pointed at the stale `mlb-phase1-scrapers` service and never fired; `pitcher_props_closing` stayed ~100% synthetic. This is precisely *why* the 2026-06-25 CLV-reconstruction-from-`oddsa_pitcher_props`-snapshots method exists. |
| **"Model matches market 1.83 vs 1.85"** | (historical thesis) | Mirage — that was the **leak-trained** model. De-leaked: 2024 model MAE **1.787 worse** than line 1.763; 2025 barely 1.710 vs 1.722. |

**Also worth recording (from the comprehensive-review thread, not in the kickoff):**
- **A4 (Poisson/Quantile loss) was tested and REJECTED** — RMSE wins decisively on walk-forward; deploy skipped.
- **A1 (wire "already-computed" lineup K features) is vapor** — 5 of 6 features are 0.0 constants across all 976 rows (`mlb_precompute.pitcher_ml_features`); the upstream `lineup_k_analysis_processor` isn't producing real values. Any "30-minute wiring" claim is false until that pipeline is fixed.
- **A2 (MAX_EDGE 1.5→1.25) shipped** ~2026-05-13; **B1 early-warning CF is live** (currently DEGRADING).

**The dead list — do NOT re-run:** founding thesis (FanGraphs same-season-snapshot leak, ~23% of
importance), model edge (WF MAE ties/trails line), features, betting machinery (blend hurts, p_over
correct), 0/33 signals (fewer than chance), signal confluence, C2 13-market scan (all efficient,
~519K rows), batter props (0/212), home-pitcher bias (−5.5% ROI; the "58%" was the `innings≥3.0`
look-ahead artifact), steam (2026 −14.8%), UNDER cross-season (≈45.5–45.8%), early-hook UNDER
(short-start risk priced into the *line*, corr recent-IP↔K-line +0.378), CLV-on-shadow-picks (negative).

---

## 3. Live operational state (verified today)

- **Halt is durable, two independent layers:** `nba_orchestration.halt_overrides` row `sport=mlb,
  active=TRUE, reason=manual` (open-ended, since 2026-05-21) **AND** `mlb-best-bets-generate`
  scheduler PAUSED. 30 of 60 MLB schedulers paused (betting/output side); data pipeline side enabled.
- **Kept alive & healthy:** `mlb-prediction-worker` (rev …00097, traffic→latest), full phase 1–6 data
  pipeline, `mlb-predictions-generate` (ENABLED) → fresh slates daily (`mlb_predictions.pitcher_strikeouts`
  max date 2026-06-27, ~17–28 rows/day). The tonight-page information product is live.
- **Odds feed:** `mlb_raw.oddsa_pitcher_props` fresh (today; 86.8K rows/7d), **12 US/offshore retail
  books** (DK, FD, MGM, …, bovada, betonlineag) — **zero sharp book (no Pinnacle, no Circa).**
- **Un-halt is not a one-liner:** flipping `active=FALSE` is insufficient — `mlb-grading-daily` and the
  shadow/regime/CF monitors are paused, so a leak-free retrain couldn't be auto-shadow-graded without
  re-enabling that path too.
- **Live model is leak-trained** (May-17 `.cbm`) serving de-leaked features → overshoots K, mechanically
  flatters directional OVER. Any HR/CLV read on *current* shadow picks is PROVISIONAL.

---

## 4. The §4 frontiers, re-scored against the evidence

### Frontier 1 — Sharp-vs-retail book disagreement (Pinnacle/Circa) → **CLOSED** (owner-confirmed no Pinnacle on our Odds API plan, 2026-06-27)
The kickoff called this the highest-prior new lever. The web research **undercuts its core premise**:
- **Sharp/market-making books deliberately deprioritize props** — lower limits, higher vig (~3–5% on
  props vs ~2% on sides; Pinnacle's own published differential). "There is no sharp book for props the
  way there is for sides/totals" (ETR, Unabated; confirmed 3-0).
- The specific edge mechanism — **"bet the stale retail number when the sharp book disagrees" — was
  REFUTED 0-3**, as was "Pinnacle's no-vig line is the sharpest reference" (0-3) and "an edge at a soft
  book persists vs the close" (0-3). These were survivorship/marketing claims.
- **We don't even ingest a sharp book**, and the angle is **not backtestable** (no historical Pinnacle
  snapshots) — it could only ever be a forward-only live experiment.

**Coverage question resolved (2026-06-27):** owner confirms the Odds API plan does **not** return
Pinnacle for MLB. So there is no sharp K line to ingest, the mechanism is refuted *and* the data is
unavailable — the frontier is **fully closed**, not merely low-prior. (For the record, had it been
worth checking, the call was a ~1–2 credit
`GET .../events/{eventId}/odds?regions=eu&markets=pitcher_strikeouts` with **no** `bookmakers=`
filter; `ODDS_API_KEY` exists and `regions` is CLI-overridable. Not needed.)

### Frontier 2 — Information-speed edge → **unchanged: not justified now**
Act on genuine news before repricing. Requires real-time event detection + **automated bet placement**
(repo has zero). A multi-month new *class* of system. The web adds a hard ceiling: even a real prop edge
gets **limited to $200–300 (some books $10–50)** once you win (confirmed, high verifier confidence) — so
this can't scale to meaningful bankroll regardless. Against the standing "improve NBA core, don't expand"
verdict, not justified.

### Frontier 3 — Non-public / proprietary data → **none identified**
The Statcast "underweighted edge" candidates the kickoff asked about were checked and are priced-in or
too noisy:
- **Catcher framing** — publicly quantified and driving roster decisions since ~2014-17 (implausible a
  modern book misses it); per-start effect far **too noisy** to isolate (season runs-saved 95% CIs span
  ~22 runs; e.g. Lucroy [8.16, 30.49]). A called strike ≈ 0.11 runs (the mechanism is real), but the
  big-effect "45-run best-vs-worst spread" framing-as-signal claim was refuted 1-2. **2026 ABS challenge
  system** further erodes framing on contestable pitches (but is rule-context, not a betting edge).
- General "props are an inefficient/beatable market" and "exotic props priced with weaker models" were
  both refuted 0-3. Even MLB **main** moneylines show only a small favorite-longshot bias with **no
  profitable bettable range** (peer-reviewed, 3-0) — a profitable edge on the softer, higher-vig K prop
  is implausible by extension.

---

## 5. Web-sourced shortlist (every idea classified vs the bar)

| Idea | Class | Survives skeptical bar? | Disposition |
|------|-------|------------------------|-------------|
| Prediction model vs consensus line | §3 dead | No — efficient, 10–15% holds, "extremely difficult" (3-0) | Already refuted internally; corroborated |
| **Line-shopping / beat-the-number across books** | §4-adjacent (market structure) | Partially — props are softly priced, but it's hold-reduction not prediction | **Only credible angle**, but capped by limits → non-scalable; not a model play |
| Sharp-vs-retail (Pinnacle divergence) | §4.1 frontier | **No — mechanism refuted 0-3**; Pinnacle not sharp on props | Downgraded; optional 1–2 credit coverage check only |
| CLV as the arbiter | (method, not edge) | Yes — valid negative signal in efficient mkt (3-0) | Reinforces the kill; keep using the snapshot-reconstruction instrument |
| Catcher framing edge | §4.3 non-public-ish | No — priced-in since ~2014-17 + too noisy per-start (3-0) | Drop |
| Exchanges / P2P (ProphetX, Sporttrade) | open | Underpowered/refuted (thin liquidity, e.g. $247 on one K market; 2% commission claim refuted 0-3) | **Genuinely-open but low-prior** (see §6) |
| F5 / alt-K ladders / live in-game K | open | Not addressed by web or internal C2 (full-game only) | **Genuinely-open but not backtestable** (we don't ingest these); high vig prior is low |
| "Pitcher Ks have the widest edges / 18% have 3%+ CLV gaps" | marketing | **Refuted 0-3** — survivorship hype | Do not resurrect |

**Honest open questions the research could not close** (none rise to project-worthy): (a) is there a
*measurable, persistent* line-shopping divergence on K props before limits hit; (b) do exchanges/P2P
offer enough liquidity AND better effective pricing; (c) does the 2026 ABS system create a transient
mispricing during the books' adjustment window; (d) are F5/alt-K/live-K derivative markets softer than
full-game lines. All are forward-only or need new data; all have low priors given the efficient-market +
high-vig + non-scalable-limit evidence.

---

## 6. Recommendation

**Stay halted; remain a pure information product.** This is a *successful* outcome under the project's
own standard — the no-edge verdict is now quintuple-confirmed and, for the first time, corroborated by
independent outside research that specifically tried to find what sharp bettors do differently. Nothing
in the web scan is a public-data prediction angle we hadn't already refuted, and the one genuinely-new
lever (sharp-vs-retail) had its premise knocked out.

**Concrete next actions (all small):**
1. ~~Run the `regions=eu` coverage call.~~ **DONE/moot** — owner confirmed (2026-06-27) the Odds API plan
   does not return Pinnacle. Frontier 1 closed. No call needed.
2. **No retrain, no un-halt.** Keep the worker writing the factual tonight-page slate.
3. **Map hygiene:** fix the four stale items in §2 wherever they're quoted (kickoff doc, memory) — esp.
   the "closing-line capture fixed" claim (it wasn't) and the UNDER 45.5–45.8% vs 49.5% number.
4. **If the owner ever wants to spend real effort on MLB**, the only directions with any residual prior
   are forward-only market-structure plays (exchanges/P2P liquidity; a deliberate 2026-ABS-adjustment
   mispricing watch; F5/alt-K market softness) — each a separate, deliberate project decision against
   "improve NBA core, don't expand," not a backtest, and each low-prior. Recommend **none** absent a
   named reason to revisit.

**Bottom line:** the box is mapped to the edges. The answer is still no, and now the *outside world*
agrees with the *inside* analysis. Honor the bar; keep the information product; spend the energy on the
NBA core.
