# Broad research findings — 5-season walk-forward (2026-06-23)

**Method:** `DiscoveryDataset(min_edge=0.0)`, walk-forward CatBoost V12_NOVEG predictions, 5 seasons
(2021-22…2025-26). P/L at −110 (win +0.909u, loss −1.0u; nominal breakeven 52.4%, real ~53.5%). Wilson 95% CIs,
per-season + regime-split. Caveat throughout: per-season cell N is modest; cross-season *consistency* is the
reliable signal, not single cells. Single-model walk-forward (fleet is mostly CatBoost clones → representative).

## 1. P/L by strategy — UNDER-only is the robust core
| Strategy | Total ROI | Seasons profitable | Note |
|---|---|---|---|
| ALL edge3+ (both dir) | +6.6% | **2/5** | net loser ex-2025-26 (−9u without it) |
| OVER-only edge3+ | +3.4% | **1/5** | profitable ONLY in 2025-26; bleeds in normal years |
| **UNDER-only edge3+** | **+9.4%** | **4/5** | robust; only 2022-23 loses (−4.5%, N=82) |
| Current-floor (UNDER e3+ + OVER e6+) | +10.5% | 3/5 | extra return is ENTIRELY 2025-26 OVER |
| UNDER-only edge5+ | +16.5% | 4/5 | higher ROI, lower volume (159 picks/5yr) |
| UNDER-only edge6+ | +23.2% | 4/5 | highest ROI, ~12 picks/season |

**Takeaway:** dropping OVER costs ~1pp total ROI but buys 4/5-vs-3/5 consistency and removes the normal-season
OVER drag. OVER inclusion only pays in anomaly seasons (2025-26). **UNDER + edge is where durable EV lives.**

## 2. Late-season decay is NOT universal — and the Mar-2026 collapse is production-side
UNDER edge3+ early(Oct-Dec)→late(Feb-Apr) by season: +2 / −2 / −9 / −2 / **−1** pp. No systematic late
collapse; only 2023-24 dips meaningfully (−9pp, still 55%). **2025-26 UNDER was stable late (64%→63%).**
OVER actually *improves* late in 4/5 seasons. **Critically: in clean walk-forward, the 2025-26 raw model held
up in March (UNDER 58%, OVER 73% at edge3+) — yet production BB collapsed to 46.7%.** So the March collapse
originates DOWNSTREAM of raw model quality — in pick selection (overfit OVER signals), live-market tightening,
or model staleness — not a seasonal or model-quality limitation. Consistent with STEP5 (cadence/staleness
didn't reproduce it on clean WF).

## 3. Model calibration — unbiased every season; 2025-26 = bigger edges that paid
- `pred − actual` (model bias): −0.07…+0.11 across all seasons incl. 2025-26 (−0.03). **Model is essentially
  unbiased; the anomaly was NOT model bias.**
- `pred − line` (model lean): +0.13…+0.29 — the model **structurally leans OVER**, which is why it generates
  OVER picks (that mostly lose). A candidate bias to correct.
- `mean |edge|` at edge3+: ~3.9 normal seasons vs **4.36 in 2025-26** — the soft/beatable market: bigger
  model-vs-line gaps that actually hit. This is the mechanism of the 2025-26 anomaly (not bias, but exploitable
  edge availability).
- **UNDER edge is monotonically reliable across all 5 seasons:** HR rises 52.7→54.8→56.2→57.4→58.9→70.0% by
  edge bucket. Edge genuinely predicts UNDER quality → validates UNDER edge-ranking. (OVER's high-edge buckets
  are 2025-26-inflated.)

## 4. Where the UNDER edge concentrates (segmentation, UNDER edge3+, base 57.3%)
| Segment | HR | Seasons > breakeven | Verdict |
|---|---|---|---|
| **Back-to-back (days_rest=1)** | **63.2%** | **5/5** | **STRONGEST durable edge** (see §5) |
| Mid volatility (std 5.5-8) | 58.3% | 5/5 | robust |
| Normal rest (2 days) | 58.3% | 5/5 | robust (the bulk) |
| High line / star (25+) | 59.9% | 4/5 | robust |
| Home | 58.5% | 4/5 | robust |
| Slow opp pace | 58.7% | 4/5 | robust |
| **Rested (3+ days)** | **52.4%** | **1/5** | **TRAP — avoid UNDER on rested players** |
| Low usage (<20) | 50.0% | 2/5 | weak (role players) |
| Low line (<18) | 55.0% | 2/5 | weak (corroborates failed low-line archetype) |
| Away | 56.2% | 2/5 | inconsistent |

## 5. ACTIONABLE: rebuild `b2b_under` — wrongly removed due to a data-coverage artifact
- **b2b (days_rest=1) UNDER edge3+ = 63.2% [55.8, 70.0], N=174, above breakeven in ALL 5 seasons** (60/56/73/
  56/54). +7pp vs non-b2b UNDER (Fisher p=0.091; the 5/5 consistency is the real evidence). edge5+ b2b UNDER
  = 65.7%. Mechanistically sound (fatigue → underperformance). **Notably WEAKEST in 2025-26 (54.3%) — the
  opposite of the OVER artifacts → strong cross-season validity.**
- **Root cause of the wrong removal:** the production `b2b_under` signal used the `is_b2b` feature, which is
  **populated 0 times in 2021-22…2024-25 and only in 2025-26** (verified). So Session-494's evaluation saw ONLY
  2025-26 (b2b UNDER's weakest season, 54.3%) → removed at "54% CF HR." The 5-season truth via `days_rest==1`
  is 63%.
- **Recommendation (season-open, needs sign-off):** rebuild `b2b_under` on `days_rest==1` (or backfill `is_b2b`
  for 2021-25) and reinstate as an ACTIVE UNDER signal. Pair with a **`rested_under_block`** candidate (UNDER
  on 3+ days rest = 52.4%, 1/5 seasons — block or down-weight). Both are cross-season-validated, deployable,
  and independent of the fragile OVER side.

## Consolidated picture
The system's durable engine is **UNDER + edge**, concentrated in **b2b / high-line / home / normal-rest**
players. OVER is structurally fragile (no cross-season edge band; signals overfit to 2025-26). The 2025-26
boom + Mar collapse was a soft-market anomaly (bigger edges that paid, then reverted) amplified by OVER-heavy
pick selection — not a model or seasonal flaw. **2026-27 posture: UNDER-dominant; reinstate b2b_under;
treat OVER as unproven until the scoring environment confirms.**
