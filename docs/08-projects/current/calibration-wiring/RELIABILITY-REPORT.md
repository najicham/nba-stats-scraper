# Edge Calibrator — Retrain + Reliability Report

**Date:** 2026-07-03 (v2 refit: 2026-07-03, P1.1)
**Author:** calibration-wiring session
**Component:** `ml/calibration/edge_calibrator.py` (`EdgeCalibrator`, per-(family,direction) isotonic `edge → P(win)`)
**Status:** Wired as SHADOW `win_prob` (informational only; does NOT affect ranking/selection).

> **✅ RESOLVED — superseded by the clean refit `v2026-07-04-live` (see §7, added for P1.1).**
> The loader now points at `models/edge_calibrators/v2026-07-04-live`, which was fit on
> provenance-verified live-only rows, passed the reliability gate on a live regime-shifted
> holdout (UNDER ECE 0.0022, monotone), and fixed the direction-blind keying. The warning
> below stands as the record of why `v2026-07-03` is quarantined — never point back at it,
> and never train on the 2022-25 `prediction_accuracy` strata.

---

> ## ⚠️ DO NOT CONSUME — TRAINING DATA IS BACKFILL-LEAKED (added 2026-07-03, adversarial review)
>
> A follow-up adversarial review (BQ-verified) found this calibrator was fit on a **leaked** stratum
> of `nba_predictions.prediction_accuracy`: **all ~94.8K training rows were graded in a single backfill
> batch on 2026-01-10**, with impossible win rates (catboost_v8 74.4%, a moving-average baseline 62.8%
> at edge≥1 — the Session 458 leakage signature). Against **live** v12-family rows (2026-01-09→present)
> the true WR is ~45-55% across edges 3-8, while the served `_global` curve returns **61-68%** — an
> over-promise of **6-20pp**. The ECE 0.0085 "pass" is circular (the holdout is the same contaminated
> batch). The loader is also **direction-blind** (`fam = family if family else '_none'` never matches a
> fit key → every pick routes to `_global`, which pools OVER+UNDER — the per-direction tables below are
> never actually served).
>
> **Consequence:** re-running the Kelly sizing sim with this `win_prob` would flip Kelly from
> falsely-negative to **falsely-POSITIVE** (bet large fractions on negative-EV picks). Do NOT ship the
> pkls, do NOT consume `win_prob`, and do NOT re-run Kelly with it until the calibrator is **refit on
> live-only rows or the clean walk-forward cache**, with a training-time assertion rejecting bulk-batch
> `graded_at` dates, and the loader keying fixed. The reliability numbers below stand only as a record
> of the (invalid) fit and MUST NOT be cited as evidence of calibration quality.

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

---

## 7. v2 CLEAN REFIT — `v2026-07-04-live` (P1.1, done 2026-07-03)

### 7.1 The provenance discovery (what "live-only" actually requires)

`graded_at` alone does NOT separate clean from leaked rows. BQ-verified:

- Bulk grading batches exist on **2026-01-10** (123.8K rows, game_dates 2021→2025 — the fully
  leaked strata), **2026-01-25** (8.2K rows) and **2026-02-22** (19K rows, game_dates
  Dec 20→Feb 21). The later batches **MIX** two populations: predictions **created pre-game and
  graded late** (legitimate; ~8K rows since 2025-12-20) and predictions **created 24h+ after the
  game** (backfilled/leaked; ~18.8K rows).
- The correct discriminator is **`player_prop_predictions.created_at` before the end of the game
  day** — prediction creation time, not grading time. Since 2026-01-09, only 6,043 rows were
  promptly graded but **9,998 rows (from 2026-01-04) are provenance-verified live**.

Implemented as `load_live_verified_data()` (pre-game `created_at` join) plus a training-time
guard `validate_training_provenance()` that **refuses to fit** on (a) any unverified frame where
one `graded_at` day holds >30% of rows spanning >14d of game_dates (the bulk-batch signature) or
(b) unverified rows graded >10d late. Both loaders in `edge_calibrator.py` now pass through the
guard; regression tests in `tests/unit/ml/test_edge_calibrator.py` (12 tests).

### 7.2 Fit + keying fixes

- **Train:** provenance-verified live rows 2026-01-04 → 2026-02-28 (N=6,800).
- **Holdout:** 2026-03-01 → 2026-06-30 (N=2,726) — deliberately the **regime-shifted**
  (TIGHT-market / March-collapse) window; season effectively ends early April.
- **Pooled-only ship** (`--pooled-only`): per-family isotonic curves at N=300-650 saturate at
  0/100% in sparse tails (e.g. `v12_mae_UNDER` served 100% at edge 9 — the exact over-promise
  failure mode being purged). Shipped keys: `_pooled_OVER`, `_pooled_UNDER`, `_global` only;
  per-family curves return once cross-season live volume accrues (~1K+/key).
- **Direction-blind loader bug FIXED:** `EdgeCalibrator.predict_win_prob` now falls back
  `(family, direction)` → `_pooled_{direction}` → `_global`, and `win_prob_loader` passes the
  production family through unmangled (the old `'_none'` substitution never matched any key, so
  every pick had routed to the direction-pooled `_global`).

Shipped curves (honest and humble — this is what live raw-stream edge is actually worth):

```
Group            N      WR   | E2  E3  E4  E5  E6  E7  E8  E9  E10
_pooled_OVER    1853   49.3% | 49% 49% 51% 51% 51% 51% 51% 51% 51%
_pooled_UNDER   4947   51.0% | 50% 51% 51% 51% 51% 53% 54% 54% 54%
_global         6800   50.5% | 50% 51% 51% 51% 51% 53% 53% 53% 53%
```

### 7.3 Gate results (live holdout Mar 1 – Jun 30, N=2,726; `ml/calibration/evaluate_reliability.py`)

| Calibrator | UNDER ECE | UNDER Brier | Monotone | Gate |
|---|---|---|---|---|
| **`v2026-07-04-live`** (ship) | **0.0022** | 0.2500 | Yes | **PASS** |
| `v2026-07-03` (leaked, quarantined) | 0.1213 | 0.2662 | NO | FAIL |
| WF-cache fit (Arm B, non-anomaly 5-season, N=15.9K) | 0.0545 | 0.2613 | NO | FAIL |

- The leaked calibrator's failure on live data (predicted 59.8/62.2/66.6% vs observed
  48.9/53.9/48.8%) **independently confirms the adversarial review's 6-20pp over-promise**.
- The WF-cache fit also fails: the cross-season durable curve (UNDER 55-57% at edge 3-6) does
  **not** transfer to the live 2026 raw stream — regime + fleet differ. Live-fit wins on both
  honesty and ECE.

### 7.4 Interpretation & consequences for Phase 2 (sizing)

- The passing curve is **nearly flat at ~50-51%**: on the LIVE raw prediction stream, edge buys
  almost no win-probability (live UNDER edge→WR is actually *inverted*: 60.9% at edge 1-2 down
  to ~44-47% at edge 5-8; monotone isotonic honestly flattens it). The BB pipeline's selection
  lift (+7-12pp) is NOT modeled by this calibrator, so `win_prob` on exported BB picks
  **understates** their true win rate — the conservative direction for any future sizing use.
- **A raw-stream p_win near breakeven means Kelly-on-raw would bet ~nothing** — consistent with
  the narrowed Kelly verdict. The P2 sizing-only re-run must therefore size on the **BB stream's**
  empirical win rate, and note: **only 175 graded live BB picks exist (102 OVER / 73 UNDER)**,
  below the N≥300 the gameplan assumed. P2 is data-blocked until 2026-27 live picks accrue;
  the earliest honest sizing decision is mid-season 2026-27.
- ⚠️ These curves are fit on the 2025-26 anomaly season's live window (the only clean live data
  that exists). Re-fit + re-gate on 2026-27 live data once N accrues (P4 promotion-tracker item).

### 7.5 Remaining to ship (P3, unchanged)

Ship `models/edge_calibrators/v2026-07-04-live/*.pkl` to the deployed runtime (GCS or image),
add scikit-learn/joblib to `phase6_export/requirements-lock.txt`, make `CALIBRATOR_DIR`
absolute, and verify `win_prob` populates in the preseason dress rehearsal.
