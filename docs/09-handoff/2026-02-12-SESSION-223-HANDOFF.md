# Session 223 Handoff — Experiment Review & Next Steps

**Date:** 2026-02-12
**Session:** 223
**Status:** Research complete, experiment roadmap refined

## Context Recovery

Sessions 219-222 accomplished massive infrastructure + model work:
- **Sessions 219/219B:** Fixed ALL 15 failing scheduler jobs → 0 failures
- **Session 220:** Phase 4 same-day bypass, auto-retry fix, Docker cache busting, recovered Feb 12 to 337 predictions
- **Session 221:** Deploy sweep (4 deploys), deployment drift 0/16, enrichment verified
- **Session 222:** Deep model decay analysis, 96 prior experiments reviewed, 5 experiment proposals documented
- **Lost session (222B):** Ran 16 experiments + February analysis. Hit context limit during results analysis. Results summarized below.

## Experiment Results (16 Experiments from Lost Session)

All experiments trained Nov 2 start date, evaluated on Feb 1-11 (or Feb 8-11 for Feb 7 cutoff).

### Wave 1: Core Techniques (8 experiments)

| # | Name | Train End | Technique | Edge 3+ HR | Edge 3+ N | MAE | Verdict |
|---|------|-----------|-----------|-----------|-----------|-----|---------|
| 1 | BASELINE_JAN31 | Jan 31 | Default | 0.0% | 4 | 4.96 | Too few edge picks |
| 2 | BASELINE_FEB7 | Feb 7 | Default | 50.0% | 2 | 4.65 | Too few edge picks |
| 3 | Q43_JAN31 | Jan 31 | Quantile 0.43 | **51.4%** | 35 | 5.04 | Role UNDER 73% (n=15) |
| 4 | Q43_FEB7 | Feb 7 | Quantile 0.43 | 42.1% | 19 | 4.64 | Role UNDER 67% (n=6) |
| 5 | TUNED_JAN31 | Jan 31 | Grid search (18) | 0.0% | 5 | 4.97 | Too few edge picks |
| 6 | RECENCY30_JAN31 | Jan 31 | 30d half-life | 50.0% | 12 | 4.99 | Stars UNDER 75% (n=4) |
| 7 | VEGAS30_JAN31 | Jan 31 | Vegas weight 30% | **52.8%** | 36 | 5.03 | Stars 80%, High lines 73% |
| 8 | Q43_RECENCY_FEB7 | Feb 7 | Q43 + 21d recency | 47.8% | 23 | 4.65 | Stars UNDER 71% (n=7) |

### Wave 2: Hypothesis-Driven (8 experiments)

| # | Name | Technique | Edge 3+ HR | Edge 3+ N | MAE | Verdict |
|---|------|-----------|-----------|-----------|-----|---------|
| 9 | Q40_JAN31 | Quantile 0.40 | **53.7%** | **136** | 5.26 | Most volume, Starters UNDER 60.5% (n=38) |
| 10 | Q42_JAN31 | Quantile 0.42 | **53.6%** | 84 | 5.14 | Stars UNDER 67% (n=12) |
| 11 | Q55_JAN31 | Quantile 0.55 (OVER) | 45.5% | 11 | 4.99 | OVER specialist FAILS |
| 12 | Q57_JAN31 | Quantile 0.57 (OVER) | **18.2%** | 11 | 5.00 | OVER is catastrophic |
| 13 | Q43_VEGAS30 | Q43 + Vegas 30% | 49.3% | 134 | 5.27 | Too diluted |
| 14 | HUBER5_JAN31 | Huber loss delta=5 | 47.4% | 38 | 5.01 | Starters UNDER 67% |
| 15 | Q43_RECENCY14 | Q43 + 14d recency | **55.4%** | **92** | 5.16 | BEST: Starters UNDER 67% (n=18) |
| 16 | PERF_BOOST | Perf 2x, matchup 1.5x, vegas 0.5x | **55.6%** | 45 | 5.01 | UNDER overall 58.8% (n=34) |

### BigQuery Experiment (Session 222)

| Name | Technique | Edge 3+ HR | Edge 3+ N | Gates |
|------|-----------|-----------|-----------|-------|
| V9_FEB_RETRAIN_Q43 | Q43, train Dec 7 - Feb 4 | 51.4% | 35 | FAILED (HR < 60%, direction imbalance) |

## Key Findings

### What Works
1. **Q43 + aggressive recency (14d)** — 55.4% HR on 92 picks. Best volume + accuracy combo.
2. **Performance boost (perf 2x, vegas 0.5x)** — 55.6% HR on 45 picks. Best raw HR but fewer picks.
3. **Q40 for volume** — 53.7% HR on 136 picks. Near breakeven with massive volume for data accumulation.
4. **UNDER filter** — Across all models, filtering to UNDER-only boosts HR by 5-10pp. Stars/Starters UNDER consistently at 60-75%.

### What Doesn't Work
1. **OVER specialist models (Q55, Q57)** — 45.5% and 18.2% HR. Even though players score MORE in Feb, OVER bets lose because Vegas already adjusts lines upward.
2. **Baseline/tuned retrains** — Generate almost no edge 3+ picks (4-5 out of 1000+). Fresh models track Vegas too closely.
3. **Combining Q43 + Vegas dampening** — Dilutes the signal (49.3% on 134 picks vs 51.4% on 35 for Q43 alone).
4. **More recent training data (Feb 7 cutoff)** — Doesn't help, just shrinks eval window.

### Why February Is Tough (Root Cause Analysis from Session 222)
1. **Model decay cliff at day 25** — HR drops from 55.6% → 34.6% around week 4
2. **UNDER prediction collapse** — Players scoring +0.8 pts more than predicted; UNDER went from 60% → 34% HR
3. **Trade deadline roster upheaval (Feb 6)** — 246 players OUT in week of Feb 2 (+23% spike)
4. **Vegas adapting, model not** — Vegas MAE stable but model MAE jumped +0.48pts
5. **More catastrophic misses** — 14.2% of predictions off by >10 points (was 9.6% in Jan)

### The Retrain Paradox (Still Unsolved)
- Stale models generate edge through natural drift from Vegas → that drift IS the betting edge
- Fresh retrains eliminate drift → no edge → not profitable
- Quantile regression (Q43) is the **only technique** that creates artificial drift when fresh
- But Q43 is 100% UNDER direction, which is currently the weakest direction

## None of These Pass Governance Gates

All 17 experiments fail the 60% edge 3+ HR gate. The best (55.6%) is close but not there. The fundamental issue is that **February 2026 is a structurally difficult market** — trade deadline upheaval, scoring environment shift, and model staleness all converge.

## Proposed Next Steps (Updated from Session 222 Roadmap)

### Immediate (Next Session)

1. **Run multi-season training (Session 222 Experiment 1)**
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py \
       --name "V9_MULTISZN_Q43" \
       --quantile-alpha 0.43 \
       --train-start 2023-10-01 \
       --train-end 2026-02-10 \
       --recency-weight 120 \
       --walkforward --force
   ```
   Rationale: We're using only 13% of available training data (8.4K of 63K rows). More data may improve generalization.

2. **Run Q43 + 14d recency with Feb 7 cutoff (best from Wave 2)**
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py \
       --name "V9_Q43_R14_FEB7" \
       --quantile-alpha 0.43 \
       --recency-weight 14 \
       --train-start 2025-11-02 \
       --train-end 2026-02-07 \
       --walkforward --force
   ```

3. **Simulate direction filter on existing predictions (no code change)**
   ```sql
   -- Test if suppressing Role Player UNDER improves champion
   SELECT
     CASE WHEN predicted_direction = 'UNDER' AND player_tier = 'Role' THEN 'FILTERED_OUT'
          ELSE 'KEPT' END as filter_status,
     COUNT(*) as picks,
     COUNTIF(is_correct) as correct,
     ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as hr
   FROM nba_predictions.prediction_accuracy
   WHERE system_id = 'catboost_v9' AND game_date >= '2026-02-01' AND edge >= 3
   GROUP BY 1;
   ```

4. **Simulate ensemble of stale + fresh models (Session 222 Experiment 5)**
   ```sql
   -- Check if combining champion OVER + Q43 UNDER outperforms either alone
   -- Use prediction_accuracy data to simulate without retraining
   ```

### Medium Term

5. **Build `star_teammate_out` feature** — Biggest missing signal. When stars sit, role player lines should be OVER but model doesn't know.
6. **Evaluate V10 feature set** — Features 33-38 already exist in BigQuery (`dnp_rate`, `pts_slope_10g`, `pts_vs_season_zscore`)
7. **Deploy best experiment as shadow** — Once any model hits 55%+ consistently

### Experiment Parameter Cheat Sheet

```bash
# Available techniques for quick_retrain.py:
--quantile-alpha 0.43    # Quantile regression (0.40-0.57 tested)
--recency-weight 14      # Exponential decay half-life in days
--feature-weights name=wt # Per-feature weights (vegas_points_line=0.3)
--category-weight cat=wt  # Per-category (vegas=0.3,composite=0.5)
--loss-function Huber:delta=5  # Loss function
--tune                    # 18-combo grid search
--walkforward             # Per-week temporal breakdown
--no-vegas                # Drop all vegas features
--rsm 0.5                # Feature subsampling per split
--bootstrap MVS           # Importance sampling
```

## Commits This Session

None — research/documentation only.

## Uncommitted Files

- `docs/09-handoff/2026-02-12-SESSION-221-HANDOFF.md` — from Session 221 (deploy sweep)
- `docs/09-handoff/2026-02-12-SESSION-223-HANDOFF.md` — this document

## Infrastructure Status (Healthy)

- Scheduler: 0/110 failing (fixed from 15 in Sessions 219/219B)
- Deployment drift: 0/16 (cleared in Session 221)
- Pipeline: Producing predictions daily
- Grading: 98%+ coverage
- Champion model: DECAYING (39.9% edge 3+ HR, 35+ days stale)
