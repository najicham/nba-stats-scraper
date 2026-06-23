# RESULT: Signal trust-map — the OVER signal layer is pervasively 2025-26-overfit

**Date:** 2026-06-23 · **Status:** Closed (screening-strength). **Method:** 5-season walk-forward CatBoost
V12_NOVEG predictions, `DiscoveryDataset(min_edge=3.0)` (N=1,803: 822 OVER, 981 UNDER). Each ACTIVE signal
reconstructed from feature-store columns, HR computed per season + pooled, with a 2025-26-vs-prior Fisher exact
test. **Side baselines: OVER 54.1%, UNDER 57.3%; breakeven ≈ 53.5%.**

**CAVEATS (read first):** per-season cell N is small (single digits to ~160); thresholds are reconstructions,
not the exact production values; conditions are on a single-model walk-forward, not the live fleet. The
**regime-split Fisher tests are the reliable part**; per-season points are noisy. Treat as a trust-map
screening, strong enough to flag what to distrust at season open — not to delete signals off-season.

## OVER signals (baseline 54.1%) — 4 of 5 are recency artifacts

| Signal (status) | Pooled HR (N) | 2021-22 | 2022-23 | 2023-24 | 2024-25 | 2025-26 | prior vs 25-26 | Verdict |
|---|---|---|---|---|---|---|---|---|
| `fast_pace_over` (ACTIVE) | 61.1 (190) | 58 | 47 | 49 | 59 | **78** | 52.4→78.1, **p<0.001** | **RECENCY-ARTIFACT** |
| `cold_3pt_over` (ACTIVE w2.0) | 51.1 (182) | 34 | 46 | 42 | 46 | **72** | 41.6→71.9, **p<0.001** | **RECENCY-ARTIFACT** (sub-breakeven 4/5 yrs) |
| `line_rising_over` (ACTIVE w3.0) | 53.6 (84) | — | — | — | — | 63 | 49.1→63.0, p=0.25 | WEAK / no durable edge |
| `book_disagree_over` (ACTIVE w3.0) | 56.1 (41) | — | — | — | — | 64 | 53.3→63.6, p=0.73 | NO-EDGE |
| `stars_out_over` (ACTIVE) | 68.0 (25) | — | — | — | — | 68 | recent-only data | PLAUSIBLE (injury mechanism), thin |

**`line_rising_over` cross-check:** using `line_movement≥0.5` (vs `prop_line_delta≥0.5` above) it pools to 61%
but 2025-26 vs prior is **p=0.001** — see `2026-06-23-crossbook-OVER-multiseason-RESULT.md`. Either feature →
2025-26-only.

**Bottom line OVER:** the apparent OVER edge is a 2025-26 regime phenomenon across nearly the whole signal
layer. `fast_pace_over` and `cold_3pt_over` are *below breakeven* in multiple prior seasons (cold_3pt_over in
4/5). This is the **structural mechanism** behind the Jan 2026 (80%) → Mar 2026 (47%) OVER collapse: the
signals were tuned on, and only fire profitably in, the 2025-26 regime. The system's high OVER floor (6.0) +
edge-based auto-halt are the correct defense.

## UNDER signals (baseline 57.3%) — durable or neutral

| Signal (status) | Pooled HR (N) | by season (21-22…25-26) | Verdict |
|---|---|---|---|
| `home_under` (ACTIVE w1.0) | 58.5 (467) | 60 / 48 / 56 / 55 / 66 | **DURABLE** (≥55% in 4/5 yrs) |
| `volatile_starter_under` (ACTIVE) | 58.0 (326) | ≈ baseline | NEUTRAL (≈ side) |
| `line_drifted_down_under` (ACTIVE w2.0) | 56.8 (111) | stable, prior 58.5 / 25-26 51.7 | STABLE ≈ baseline |
| `mean_reversion_under` (ACTIVE) | 58.9 (263) | 53 / 44 / 55 / 63 / 70 | MILD-RECENCY (some support) |
| `hot_3pt_under` (ACTIVE w2.5) | 56.3 (158) | 48 / 59 / 52 / 56 / 73 | MILD-RECENCY, modest |
| `b2b_under` (REMOVED S494) | 54.3 (35) | 2025-26 only | NO-EDGE (removal correct) |

**Bottom line UNDER:** the UNDER signal layer is healthier — `home_under` is genuinely durable, several are at
the (already-good 57.3%) baseline, and the two recency-leaning ones still have some cross-season support. This
matches the long-standing "UNDER is the stable side / signal-first UNDER ranking" posture.

## Implications & actions (NO deploy change off-season)
1. **OVER signals are the system's biggest hidden risk for 2026-27.** `fast_pace_over`, `cold_3pt_over`,
   `line_rising_over`, `book_disagree_over` should ALL be on a season-resume decay watch. Re-grade each by
   ~Dec 2026; if 2026-27 HR is not clearly above breakeven at N≥30, demote weight / move to shadow. Do not
   trust their current high weights (3.0 / 2.5 / 2.0) — those reflect 2025-26 fits.
2. **`cold_3pt_over` is the worst offender** (sub-breakeven in 4/5 seasons). Strongest candidate for proactive
   demotion to shadow at season open, pending fresh data.
3. **Lean on the UNDER side + edge5+** for durable value; `home_under` and the volatile/mean-reversion UNDER
   signals are the more trustworthy base.
4. **Why this matters:** the OVER collapse was not bad luck — it was overfit signals reverting. A signal that
   only beats breakeven in the season it was discovered is not an edge; it's a backtest. Every future OVER
   signal must clear ≥3/5 seasons above breakeven before promotion (the discovery framework's gate — enforce it).
