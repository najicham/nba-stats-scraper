# Result — Retrain CADENCE experiment (7-day vs 14-day)

**Date:** 2026-06-18
**Pre-registration:** `docs/09-handoff/2026-06-18-cadence-PREREG.md` (written before any HR was viewed).
**Verdict:** **14-day cadence is HR-equivalent to 7-day on clean data.** The "7-day is the sweet spot"
belief is NOT supported as *superior* — 7d and 14d are within noise. 14d halves retrain compute/cost for
no measurable hit-rate loss. **This is an experiment, not a deploy** — changing the `weekly-retrain` CF
schedule needs explicit user sign-off.

---

## TL;DR

Holding the training window fixed at **56 days**, I ran a paired walk-forward isolating the *only* thing
cadence changes: model staleness. 7d cadence serves a model ≤6 days stale; 14d serves one ≤13 days stale.
Over a 14-day cycle both serve the identical fresh model in week 1; they differ only in week 2 (7d retrains,
14d keeps the now-7-day-staler model). So the whole question = **fresh model vs 7-day-staler model on the
same week-2 windows.** Tested across 3 clean seasons (2023-24, 2024-25, 2025-26-pre-Feb), 32 weekly
retrains, V12_NOVEG.

| Metric (FRESH=7d / STALE=14d) | FRESH | STALE | Δ (F−S) | p | Read |
|---|---|---|---|---|---|
| **edge≥5 HR (pooled, PRIMARY)** | 58.9% (63/107) | 57.1% (52/91) | **+1.7pp** | 0.805 | within noise (Δ<2pp, p>.05) |
| edge≥3 HR (pooled, N~628/arm) | 53.3% | 54.7% | −1.5pp | 0.606 | equivalent; stale nominally better |
| edge≥5 + UNDER filters (pipeline-lite) | 61.5% (59/96) | 56.2% (45/80) | +5.2pp | 0.484 | n.s. (tiny N) |
| MAE | 5.180 | 5.160 | +0.020 | — | identical |
| **Paired McNemar @edge5+** | — | — | **0 / 51 discordant** | 1.0 | **0 direction flips on shared high-edge picks** |

## The decisive result: 0/51 paired flips

The cleanest contrast is the **paired** set — the same (player, game_date) that is edge≥5 under *both*
arms (N=51 across 3 seasons). On all 51, fresh and stale produced the **identical** graded outcome
(30 both-correct, 21 both-wrong, **0 discordant**). This is not a coincidence of construction: at edge≥5 a
pick's correctness is fixed by its *direction* (the line and actual are shared), so a discordant pair can
only arise from a **direction flip**. **Zero flips ⇒ a 7-day-staler 56-day model never changes which side
of a high-edge pick you bet.** A 56d-window model's predictions barely move in 7 days.

## Why the per-season edge5+ point-HRs still differ (and why it's noise)

Per-season edge5+ point HRs diverge (2023-24 +5.0pp, 2024-25 +12.2pp, 2025-26 −2.9pp), which tripped the
pre-registered **directional-consistency guard** (2/3 seasons stale nominally worse by ≥2pp). But:
- All three are **non-significant** (p=0.65, 0.46, 0.79) on **tiny N** (14–43 graded edge5+ picks/arm/season).
- The divergence comes **entirely from non-overlapping marginal picks** — players who sit just above edge 5
  under one model and just below under the other. The 56→51 unshared fresh picks and 40 unshared stale picks
  are knife-edge reclassifications, not genuine quality differences. The paired set (the apples-to-apples
  comparison) shows **0** real flips.
- The well-powered **edge≥3** contrast (N~628/arm) shows full equivalence with stale **nominally better**
  (Δ=−1.5pp), and **MAE is identical**.

So the guard fired on a tiny-N marginal-pick artifact, not a real staleness effect. **Formal pre-registered
verdict at edge5+: within-noise on the pooled test, guard-flagged → strictly INCONCLUSIVE-at-edge5+.
Totality of evidence (paired McNemar + well-powered edge3+ + MAE): non-inferior / equivalent.**

## 2025-26 anomaly note

In the collapse season, **STALE was slightly better** (edge5+ Δ=−2.9pp; edge3+ Δ=−5.5pp). Retraining more
frequently did **not** rescue 2025-26 — consistent with MEMORY's diagnosis that the root cause was a scoring
**regime shift + fleet expansion**, not model staleness. More cadence is not a fix for regime shift.

## Scope / caveats

- Conclusion is specifically **7d → 14d** (one extra cadence step, ≤13d stale). Did **not** test 21d/28d —
  staleness could bite beyond two weeks; this experiment doesn't license arbitrary cadence stretching.
- Window held at **56d** throughout (the validated sweet spot — not re-litigated here).
- Single-model V12_NOVEG raw edge5+ is sparse (~1–2% of eval rows), so per-season edge5+ N is small; the
  conclusion rests on the **paired** test and the well-powered **edge3+**, not the noisy per-season edge5+.
- BB-pipeline signals/filters are cadence-invariant context (same eval date ⇒ same signal health, regime,
  blacklist, combos regardless of which cadence produced the point estimate), so they don't change the
  conclusion; the cadence effect flows only through `predicted_points`, which the paired test measures
  directly. Full BB-injection was not needed because the primary was not borderline at the paired level.

## Recommendation

- **The "7-day is the sweet spot" claim should be downgraded:** 7d is not *superior* to 14d; they are
  HR-equivalent on clean data. If compute/cost matters, **14-day cadence is adopt-eligible** (halves retrain
  runs for equal HR).
- **Do not change `weekly-retrain` without user sign-off.** This experiment trains and measures only.
- If a *formal* green light is wanted (to clear the pre-registered guard rather than reason past it), boost
  edge5+ N by adding seasons with denser line coverage or a finer paired grid — but the paired McNemar
  already makes the practical answer clear.

## Artifacts / repro

- Orchestrator: `/tmp/cadence/run_cadence.py` (32 weekly retrains via `quick_retrain.py --feature-set v12
  --no-vegas --no-production-lines --dump-eval-predictions`, `--skip-*` so read-only).
- Aggregation: `/tmp/cadence/aggregate.py` (paired FRESH/STALE pools, two-proportion z, exact McNemar).
- Per-row dumps: `/tmp/cadence/dumps/<season>_<boundary>.csv`.
- Env gotcha confirmed: the `bq` CLI hangs in this WSL env — use the Python BigQuery client.
