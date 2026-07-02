# Result — MQ / distributional diversity-model experiment

**Date:** 2026-06-18
**Verdict:** **FAIL (clean negative result).** Diversity is NOT worth chasing via a CatBoost MultiQuantile model this off-season.
**Handoff this answers:** `docs/09-handoff/2026-06-18-mq-diversity-build-handoff.md`

---

## TL;DR

Trained ONE structurally-"different" model (CatBoost `MultiQuantile:alpha=0.25,0.5,0.75`) on clean
post-Session-458 data and measured it against the pre-registered bar. It **fails the diversity bar
decisively** and only marginally passes accuracy — so OVERALL FAIL.

| Pre-registered bar | Result | Pass? |
|---|---|---|
| **Diversity:** mean `r < 0.85` vs CatBoost mass | **r = 0.932** | ❌ FAIL |
| **Accuracy:** ≥ 53% HR @ edge 5+ | 54.1% (N=61); 47.5% @ edge6+ | ⚠️ marginal PASS |

**Both must hold → FAIL.** The MultiQuantile loss does not change the functional form enough: the
p50 (median) is still a boosted-tree point estimate on the same features, so it clones the CatBoost
fleet exactly as the 2026-06-18 fleet-diversity diagnosis predicted for "same algo family."

---

## Setup (clean, leakage-safe)

- **Model:** `quick_retrain.py --multi-quantile --no-vegas --feature-set v12 --no-production-lines`
  (V12_NOVEG, 50 features, CatBoost MultiQuantile loss). Shadow-only (`--skip-auto-upload/register`) — nothing deployed.
- **Train:** 2025-11-06 → 2025-12-31 (56-day window, the validated sweet spot).
- **Eval:** 2026-01-01 → 2026-01-31 (clean, post-458, **pre-late-season**, loose market). Chosen because
  January production has multiple CatBoost models — `v8`, `v9`, `v12` variants — to correlate against as
  the "CatBoost mass." Eval strictly after train end → no temporal leakage.
- **Eval N:** 2,692 predictions. Edge3+ N=238, edge5+ N=61.
- De-correlation measured exactly as the handoff query specifies: corr of `predicted_points` (MQ p50)
  vs each production model on shared `(player_lookup, game_date)` rows.

## Diversity result — the MQ p50 is a CatBoost clone

corr(MQ p50, production model), January 2026:

| Model | Family | r | n |
|---|---|---|---|
| `catboost_v9_train1102_0108` | catboost | **0.976** | 1852 |
| `catboost_v12_train1102_1225` | catboost | **0.955** | 1298 |
| `catboost_v12_train1102_0125` | catboost | **0.953** | 543 |
| `catboost_v9` | catboost | **0.936** | 1941 |
| `moving_average_baseline_v1` | structural | 0.918 | 365 |
| `moving_average` | structural | 0.907 | 2145 |
| `ensemble_v1_1` | structural | 0.887 | 1211 |
| `ensemble_v1` | structural | 0.878 | 2509 |
| `xgboost_v1` | structural | 0.878 | 323 |
| `similarity_balanced_v1` | structural | 0.852 | 2034 |
| `catboost_v8` | catboost | 0.840 | 5857 |
| `zone_matchup_v1` | structural | **0.773** | 2509 |

- **Mean r vs CatBoost mass = 0.932** (bar < 0.85). The most feature-comparable models (`v9`/`v12`,
  trained on overlapping windows) sit at **0.95–0.98 — essentially identical predictions.**
- `catboost_v8` is the lowest CatBoost (0.840) only because it's an older feature set (v8 vs v12). The more
  comparable the feature set, the higher the correlation — exactly the fleet-diversity finding.
- **Measurement validated:** `zone_matchup_v1` reproduces the known de-correlated structural signal at
  **0.773**, matching the diagnosis's ~0.795. So the query is sound; the MQ model genuinely sits in the clone regime.

## Accuracy result — marginal, not robust

- HR @ edge3+: 51.7% (N=238) — below 53%, CI spans it (governance "INCONCLUSIVE").
- HR @ edge5+: **54.1% (N=61)** — nominally clears the 53% bar but small N, and **edge6+ drops to 47.5% (N=40)**.
- Quantile signals collapsed out-of-sample vs Session 521's tiny-N first test (N=10, 90%):
  `QUANTILE_CEIL_UNDER` **51.3%** (40/78), `QUANTILE_FLOOR_OVER` **48.4%** (15/31). The original
  reason MQ existed (the CEIL_UNDER spread signal) does **not** replicate on a real month.
- Governance gates all PASSED (eligible for shadow), but accuracy is right at break-even — not a model
  worth adding even setting diversity aside.

## Why this kills the diversity thesis for MQ specifically

`combo_3way` (the one genuine cross-MODEL signal) fires on **direction agreement of point estimates**.
With MQ p50 at r = 0.93–0.98 vs the CatBoost fleet, it agrees on direction nearly always → it **cannot**
resurrect `combo_3way`. A MultiQuantile head is still a gradient-boosted tree; the loss function changes
the *target quantile*, not the *functional form*. De-correlation requires a genuinely different functional
form (kernel/similarity/distributional-NN), and the existing models of that kind
(`moving_average`/`zone_matchup`/`similarity_balanced`) are individually sub-break-even at edge 5+.

## Conclusion (per pre-registered protocol)

FAIL → **diversity isn't worth chasing this off-season via the MQ/quantile direction.** A CatBoost-family
quantile model is a clone with a different loss. The honest options going forward, none cheap:
1. Accept the clone fleet; lean on cross-BOOK signals (`book_disagreement`, `is_model_dependent=FALSE`)
   which do **not** depend on fleet diversity (60.3% HR, 68 picks/season — already working).
2. If diversity is ever revisited: it must be a non-tree functional form that is *also* accurate at edge 5+
   — a much larger build than a loss-function swap, and out of scope for a bounded off-season experiment.

Cadence (7d vs 14d retrain) remains worth settling independently — it was never a diversity question.

## Artifacts / repro

- Training log: `/tmp/mq_diversity/mq_train.log`; eval dump: `/tmp/mq_diversity/mq_preds.csv` (2,692 rows).
- Analysis: `/tmp/mq_diversity/analyze.py` (HR + correlation + verdict).
- Tooling change (uncommitted, working tree): added `--dump-eval-predictions PATH` to
  `ml/experiments/quick_retrain.py` — dumps per-row eval predictions (incl. p25/p50/p75 for MQ) for
  offline correlation work. Inert unless the flag is passed. Keep or drop at will.
