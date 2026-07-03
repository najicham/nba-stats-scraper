# Edge Calibrator — Retrain + Reliability Report

**Date:** 2026-07-03
**Author:** calibration-wiring session
**Component:** `ml/calibration/edge_calibrator.py` (`EdgeCalibrator`, per-(family,direction) isotonic `edge → P(win)`)
**Status:** Retrained, reliability-gated, wired as SHADOW `win_prob` (informational only; does NOT affect ranking/selection).

---

## 1. What changed and why

The `EdgeCalibrator` was written but idle — imported nowhere in the serve path. The pkls in
`models/edge_calibrators/` were from March 2026 (pre-leakage-fix) and stale. This session
**retrained** on clean multi-season graded data and wired the resulting `win_prob` into the
best-bets export as a shadow (informational) field.

## 2. Train window

- **Training:** `2022-11-01 .. 2025-06-30` — three clean seasons (2022-23, 2023-24, 2024-25).
  Deliberately **excludes** the 2025-26 scoring-anomaly season so the fit reflects durable,
  cross-season behavior (prior research: OVER edge is a 2025-26 anomaly; UNDER is durable).
- **Source:** `nba_predictions.prediction_accuracy` (~419K rows total; ~94.8K gradable in window).
  Filter: `has_prop_line = TRUE AND recommendation IN ('OVER','UNDER') AND prediction_correct IS NOT NULL AND is_voided IS NOT TRUE AND ABS(predicted_points - line_value) >= 1.0`.
  Edge computed as `ROUND(ABS(predicted_points - line_value), 1)` (no `edge` column exists).
- **New pkl path (versioned, does NOT overwrite March):**
  `models/edge_calibrators/v2026-07-03/`
  - `edge_cal_None_UNDER.pkl`, `edge_cal_None_OVER.pkl`, `edge_cal__global.pkl`, `calibration_stats.pkl`

### 2.1 Important data caveat — family keys

Nearly all graded rows in 2022-2025 come from **legacy systems** (`catboost_v8`, `ensemble_v1`,
`zone_matchup_v1`, `moving_average_baseline_v1`, `similarity_balanced_v1`). `classify_system_id()`
returns `None` for all of these (they aren't v9/v12 catboost families). The current production
families (`catboost_v9`, `catboost_v12`, …) only appear **from 2026-01-09 onward** — a short,
single-season window that overlaps the anomaly and is too thin for per-family cross-season fits.

**Consequence:** the clean-season fit produces only three curves: `None_UNDER`, `None_OVER`,
and `_global`. Production families (e.g. `v12_noveg`, `v9_mae`) are **not** present as keys, so
at serve time they fall through `predict_win_prob()` to the `_global` calibrator (by design —
graceful fallback). The `None_*` and `_global` curves ARE the durable cross-season curves; this
is the best available clean signal and is the correct thing to ship for a shadow field.

## 3. Trained calibration curves (edge → P(win), integer edge points)

```
Group            N       WR   | E2  E3  E4  E5  E6  E7  E8  E9  E10
None_OVER      30416   64.8%  | 60% 61% 63% 68% 75% 76% 81% 83% 84%
None_UNDER     64382   62.8%  | 60% 61% 65% 65% 65% 65% 65% 65% 65%
_global        94798   63.4%  | 60% 61% 63% 66% 68% 68% 69% 69% 70%
```

- **UNDER** saturates at ~65% and is flat above edge 4 — matches prior research that UNDER edge
  is durable but does NOT keep climbing with edge (signal-first ranking, not edge-first).
- **OVER** keeps climbing with edge on the clean seasons (to 84% at edge 10). This is the curve
  to treat as **provisional** — see §4.2.

## 4. Reliability evaluation (the gate)

Two holdouts: (A) the **2025-26 anomaly season** (regime-shift stress test) and
(B) a **clean in-regime season** (2024-25) trained on 2022-24. Deciles of predicted `p_win`
vs observed hit rate; real Brier score and ECE per direction.

### 4.1 Clean in-regime holdout — 2024-25 (train 2022-24) — THE PASS/FAIL GATE

| Direction | N | Brier | ECE | Monotone |
|-----------|---|-------|-----|----------|
| ALL   | 35,982 | 0.2307 | **0.0075** | Yes |
| UNDER | 24,079 | 0.2345 | **0.0085** | Yes |
| OVER  | 11,903 | 0.2230 | **0.0066** | Yes |

Per-decile (predicted vs observed):

```
ALL     [0.5,0.6) N=4906  pred=59.3% obs=60.4%
        [0.6,0.7) N=28521 pred=63.0% obs=62.3%
        [0.7,0.8) N=1743  pred=74.0% obs=74.3%
        [0.8,0.9) N=733   pred=84.6% obs=83.1%
        [0.9,1.0) N=79    pred=96.1% obs=89.9%

UNDER   [0.6,0.7) N=23893 pred=62.9% obs=62.1%
        [0.7,0.8) N=137   pred=71.5% obs=66.4%
        [0.8,0.9) N=43    pred=83.0% obs=76.7%
        [0.9,1.0) N=6     pred=100%  obs=100%

OVER    [0.5,0.6) N=4906  pred=59.3% obs=60.4%
        [0.6,0.7) N=4628  pred=63.2% obs=63.2%
        [0.7,0.8) N=1606  pred=74.2% obs=75.0%
        [0.8,0.9) N=690   pred=84.7% obs=83.5%
        [0.9,1.0) N=73    pred=95.8% obs=89.0%
```

**Verdict — UNDER PASSES.** ECE=0.0085, monotone, near-diagonal (predicted within ~1pp of
observed in the populated bins). The two sparse high-p_win UNDER bins (N=43, N=6) are noise.
ALL and OVER are also near-diagonal in a clean regime.

### 4.2 Anomaly holdout — 2025-26 (train 2022-25) — regime-shift stress test

| Direction | N | Brier | ECE | Monotone |
|-----------|---|-------|-----|----------|
| ALL   | 25,967 | 0.2546 | 0.0809 | Yes |
| UNDER | 17,863 | 0.2528 | 0.0727 | (sparse bins break it) |
| OVER  | 8,104  | 0.2584 | 0.0988 | Yes |

Per-decile shows systematic **over-confidence** (predicted > observed everywhere), e.g. OVER
[0.9,1.0) pred=94.8% but obs=65.4%. This is **regime shift, not miscalibration**: the 2025-26
season had lower realized hit rates than the training seasons. It is the same phenomenon that
drove the Jan→Mar collapse. The clean-regime holdout (§4.1) shows the curve itself is sound; it
just cannot anticipate a regime the training data never saw.

**Consequence for OVER:** treat the OVER curve as **provisional**. In a shifted (e.g. tight or
anomalous) market it over-promises. UNDER degrades far less. This is why the wiring is
**shadow-only** for now — `win_prob` is informational and must NOT gate selection until it has
been validated on live 2026-27 data (and ideally re-fit once production-family graded volume
accrues).

## 5. Wiring (shadow field)

- `win_prob` is attached to each pick in the exporter's JSON pick_dict as `win_prob`
  (`data_processors/publishing/signal_best_bets_exporter.py`).
- It is computed as `predict_win_prob(edge, source_model_family, direction)`.
- **It does NOT enter the BigQuery write** (`signal_best_bets_picks` has no suitable column and
  schema changes are out of scope) and **does NOT affect pick ordering/selection**.
- Graceful failure: if the pkl dir is missing or a (family,direction) key is absent, the loader
  returns `None`/falls back to `_global`; on any error `win_prob` is `null` and the exporter does
  not crash. Loaded once per export, cached.

## 6. Next steps (NOT done this pass — sizing consumption is out of scope)

1. Accumulate live 2026-27 `win_prob` vs graded outcome; re-check UNDER ECE at N≥30/decile.
2. Re-fit once production-family (v12_noveg / v9_mae) graded volume is cross-season, so per-family
   curves replace the `_global` fallback.
3. Only after live validation: let sizing consume `win_prob` (handled elsewhere, `pipeline_merger`).
