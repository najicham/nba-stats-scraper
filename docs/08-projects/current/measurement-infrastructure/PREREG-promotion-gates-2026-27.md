# PRE-REGISTERED Two-Tier Promotion Gates — 2026-27 Season

**Pre-registration date: 2026-07-04** (git commit of this file + the structured
`promotion:` blocks in `shared/registry/signals.yaml` / `filters.yaml` IS the
pre-registration timestamp). Measurement-infra Component 3
(`docs/08-projects/current/measurement-infrastructure/00-SPEC.md`).

This document freezes — **before any 2026-27 data exists** — the exact rules by
which the six shadow signals / observation filters below may be promoted,
demoted, or killed. Nothing here is evaluated until live data accrues; every
promotion still needs explicit user sign-off. The point of pre-registration is
to prevent post-hoc threshold-shopping (the failure mode that produced the
2025-26 OVER-layer overfit).

---

## Why two tiers, and the bias control

Realized published-pick volume is ~3.4/day (189 picks / 89 days), so a
published-only N≥30 gate takes 150–430 days to resolve — most gates would never
close in-season. The **stream** (`v_bb_candidate_signal_stream`, C1) widens the
evidence ~4-6× by adding the candidates that were *filtered* or *lost the
per-model merge* but were still evaluated against the full signal registry
(including SHADOW_SIGNALS) before the aggregator ran.

That widening is only sound if the *reason* a candidate was excluded is
**independent of the shadow signal's mechanism**. So the stream is stratified by
block class (N is too small for regression adjustment):

- **Class A — selection-orthogonal → INCLUDED in Tier-1.** Structural gates whose
  firing does not correlate with whether a shadow signal fired: SC/real-signal
  gates (shadow tags are excluded from `real_sc` **by construction** — the
  cleanest orthogonality argument), quality/confidence floors, merge caps
  (team/volume/rescue/dedup), blacklist, model-sanity, edge floors.
- **Class B — outcome-correlated → EXCLUDED (diagnostic only).** Blocks that are
  themselves correlated with the outcome the shadow signal predicts:
  cold/hot-shooting blocks, line-move blocks (incl. `clv_diverge_under_block`),
  counter-market / book-disagreement blocks, blowout-risk, opponent/teammate
  context blocks, prediction-sanity, regime/day-of-week/line-level context.

**DEFAULT = Class B.** Any active/observation filter not on the Class-A list is
treated as Class B (conservative: over-including in A would bias; over-including
in B only shrinks the evidence base). The machine-readable lists live in
`shared/registry/filters.yaml → stream_block_class` (read by the C4 tracker).

- **Tier 1** = published ∪ retracted ∪ Class-A-blocked ∪ merge-rejected, graded,
  deduped to one row per (game_date, player_lookup, recommendation).
- **Tier 2** = published-only monitoring. A promotion is **vetoed** if the
  published-only HR grossly contradicts the Tier-1 verdict.

### Class-A block reasons (the full frozen list)

SC/rsc gates: `signal_count`, `signal_density`, `sc3_over_block`,
`starter_over_sc_floor`, `under_low_rsc`, `over_low_rsc_obs`,
`zero_signal_extreme_underprediction`, `signal_stack_2plus_obs`.
Quality/confidence: `quality_floor`, `confidence`.
Merge caps: `team_cap`, `rescue_cap`, `regime_rescue_blocked`.
Blacklist: `blacklist`, `legacy_block`.
Model-sanity: `model_direction_affinity`, `model_profile_would_block`.
Edge floors: `edge_floor`, `over_edge_floor`, `under_edge_7plus`,
`regime_over_floor`, `anti_pattern`.

Everything else (`cold_fg_under`, `cold_3pt_under`, `clv_diverge_under_block`,
`line_jumped_under`, `line_dropped_under`, `over_line_rose_heavy`,
`line_anomaly_extreme_drop`, `counter_market_under`, `high_book_std_under`,
`blowout_risk_under_block`, `tanking_risk_obs`, `opponent_under_block`,
`opponent_depleted_under`, `q4_scorer_under_block`, `med_usage_under`,
`prediction_sanity`, `star_under`, `under_star_away`, `neg_pm_streak`,
`flat_trend_under`, `under_after_streak`, `under_after_bad_miss`, `bench_under`,
`bench_over_block`, `role_over_block`, `mid_line_over_obs`, `home_over_obs`,
`monday_over_obs`, `friday_over_block`, `depleted_stars_over_obs`,
`bias_regime_over_obs`, `hot_streak_under_obs`, `low_variance_under_block`,
`player_under_suppression_obs`, `toxic_*_would_block`, `mae_gap_*`,
`ft_anomaly_over_block`, `hot_shooting_over_block`, `hot_shooting_reversion_obs`,
`high_skew_over_block`, `thin_slate_obs`, `solo_game_pick_obs`, …) = **Class B**.

---

## What stream evidence CAN and CANNOT license

- **CAN:** ranking-weight promotion (shadow → `UNDER_SIGNAL_WEIGHTS`).
- **CANNOT:** rescue activation — that needs the incremental-zone test (edge
  3–5.9, per the 2026-07-01 `star_out_rescue` rule), not a headline HR.
- **CANNOT:** any OVER promotion — the OVER layer is **frozen** (2025-26 was a
  scoring-environment anomaly; high-edge OVER has no cross-season edge).

### Power honesty

At N≥100 with a Wilson lower-90% bound ≥ 52.4% (the −110 breakeven), the
**observed** HR must be ≈ **60.5%** or higher. So these gates can only resolve
true effects of roughly **+6pp or larger**. Smaller-but-real edges will read as
"ON_TRACK / UNRESOLVABLE," never "READY," and that is the honest outcome — do
not lower the bar to force a resolution.

---

## The six pre-registered gates

Every promotion below requires explicit user sign-off; the C4 weekly tracker
only reports READY/ON_TRACK/AT_RISK/KILL/UNRESOLVABLE/DATA_GATED.

### 1. `line_converging_under` (signal, UNDER) — DATA_GATED
- **Tier 1:** N≥100 UNDER, HR≥58%, Wilson-LCB90≥52.4% → **eligible** (weight
  ~1.5, non-rescue).
- **Tier 2 veto:** N≥15, veto if published-only HR < 50%.
- **Kill:** N≥100 and HR < 52.4%.
- **DATA_GATED** on `phase6-clv-reexport` + the intraday odds-snapshot
  schedulers (no T-3h line snapshot ⇒ the signal can't fire ⇒ gate can't
  resolve). These must be restored (Wave in the scheduler-restore manifest).
- **Clock:** ~mid-Dec 2026.

### 2. `whole_line_precision` (signal, UNDER only — OVER frozen)
- **Tier 1:** N≥100, HR≥60%, Wilson-LCB90≥53.5% → **eligible** (weight 1.0–1.5).
- **Kill:** N≥100 and HR < 55%.
- **Clock:** ~Jan 2027.

### 3. `b2b_fatigue_under` (signal, UNDER)
- **Pre-condition:** `rest_days` non-NULL on ≥90% of the UNDER stream (the S494
  removal was a data bug — `is_b2b` was populated 0× in 2021–25).
- **Tier 1:** N≥100, HR≥58%, Wilson-LCB90≥52.4% → **eligible** (weight ~2.0).
- **Fallback path:** the registry's published N≥30 HR≥58% gate stays valid.
- **Clock:** ~Feb 2027.

### 4. `national_tv_under` (signal, UNDER) — UNRESOLVABLE this season
- Declared **unresolvable in 2026-27**: the claimed +1.2pp effect needs N≈1,900.
- **Harm gate only:** N≥100 and HR < 50% → remove; else **hold** and pool with
  2027-28.
- **Pairing-signal path only** (never standalone weight this season): in the
  line≥22 stratum, HR(fired) − HR(not-fired) ≥ +4pp with N≥60 per cell.

### 5. `low_variance_under_block` (observation filter, UNDER)
- Uses **CF HR** = hit rate of the BLOCKED picks (low CF HR = correctly blocking
  losers).
- **Activate** (observation → active block) if live CF HR ≤ 48% at N≥30.
- **Delete** if CF HR ≥ 58% at N≥30 (the 2025-26-style inversion — the filter
  would be blocking winners).
- Else **hold**.

### 6. `clv_diverge_under_block` (active filter, UNDER)
- **Keep** if CF HR ≤ 50% at N≥30 by ~2027-01-15.
- **Demote to observation** if CF HR ≥ 55% at N≥30 (add to
  `ELIGIBLE_FOR_AUTO_DEMOTE` with min_picks=30).
- 50–55% → re-check at N≥60.
- The `retracted_clv` lane is measured separately in the stream.

---

## Amendment policy

Changing any threshold, N, or class assignment after this commit is a
**post-registration amendment** and must be recorded as a new dated commit with
an explicit rationale — never a silent edit. The whole value of this file is
that the diff history shows every threshold was fixed before the data arrived.
