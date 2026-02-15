# Comprehensive Model Validation Results — Session 253

Date: 2026-02-14
Total experiments: 42 (20 baseline + 8 tier + 4 lines-only + 6 staleness + 4 from prior W4)

## Methodology

- **Clean 7-day gap** between train-end and eval-start (prevents rolling feature bleed)
- **Production lines** for eval (prediction_accuracy multi-source cascade)
- **Zero-tolerance quality** (required_default_count = 0, quality >= 70)
- **Hit rate at edge 3+** as primary metric (minimum threshold for profitable betting)
- Breakeven: 52.4% HR (standard -110 odds)

---

## Step 1: Multi-Window Baseline Matrix

### HR 3+ Results

| Config | Description | W1 (Dec 8-21) | W2 (Jan 5-18) | W3 (Jan 19-Feb 1) | W4 (Feb 1-13) | AVG | Consistency |
|--------|-------------|---------------|---------------|-------------------|---------------|-----|-------------|
| **E: V9 MAE** | 33f, default | **71.3%** (n=80) | **81.6%** (n=103) | **93.5%** (n=46) | 66.7% (n=6) | **78.3%** | 4/4 > 52.4% |
| **C: V12 MAE RSM50** | 50f, no-vegas, rsm=0.5, depth | 67.3% (n=104) | 80.3% (n=122) | **85.9%** (n=64) | 57.9% (n=38) | **72.9%** | 4/4 > 52.4% |
| **A: V12 MAE default** | 50f, no-vegas | 61.6% (n=86) | **88.4%** (n=103) | 84.1% (n=63) | 57.1% (n=21) | **72.8%** | 4/4 > 52.4% |
| **D: V12 Q43** | 50f, no-vegas, quantile | 59.5% (n=168) | 74.2% (n=124) | 62.2% (n=135) | 58.2% (n=79) | **63.5%** | 4/4 > 52.4% |
| **B: V12 Huber RSM50** | 50f, no-vegas, Huber:5 | 55.2% (n=201) | 72.9% (n=144) | 67.2% (n=137) | 50.8% (n=67) | **61.5%** | 3/4 > 52.4% |

### Key Findings

1. **All configs beat breakeven on average** — the model architecture works across time periods
2. **Config E (V9 MAE 33f)** has highest average but W3/W4 have tiny samples (46, 6 picks)
3. **Config C (V12 MAE RSM50)** is the most reliable V12 variant — strong everywhere, largest consistent N
4. **W4 (Feb 1-13) is the hardest window** — all configs drop significantly
5. **W2 (Jan 5-18) is easiest** — all configs show 70%+ HR
6. **Huber loss (B) consistently underperforms** MAE — don't use it
7. **Q43 quantile (D) has the most picks** but lower HR — wider net catches more noise

### Pick Volume (edge 3+ picks per window)

| Config | W1 | W2 | W3 | W4 | Total |
|--------|-----|-----|-----|-----|-------|
| E (V9) | 80 | 103 | 46 | 6 | 235 |
| C (V12 RSM50) | 104 | 122 | 64 | 38 | 328 |
| A (V12 MAE) | 86 | 103 | 63 | 21 | 273 |
| D (V12 Q43) | 168 | 124 | 135 | 79 | 506 |
| B (V12 Huber) | 201 | 144 | 137 | 67 | 549 |

Config E generates the fewest edge 3+ picks (especially W4: only 6!). Config C has good volume with high accuracy.

---

## Step 2: Player Tier Experiments

Stars-only (min-ppg 25) failed for both configs — only ~255 training samples, below 1000 minimum.

### Config E (V9 MAE) — Tier Results

| Training Pop | W2 HR 3+ (N) | W4 HR 3+ (N) |
|-------------|-------------|-------------|
| All players | 81.6% (103) | 66.7% (6) |
| Starters+ (ppg>=15) | 60.3% (317) | 54.8% (301) |
| Role only (ppg<15) | 74.7% (182) | 58.2% (67) |

### Config C (V12 MAE RSM50) — Tier Results

| Training Pop | W2 HR 3+ (N) | W4 HR 3+ (N) |
|-------------|-------------|-------------|
| All players | 80.3% (122) | 57.9% (38) |
| Starters+ (ppg>=15) | 59.9% (354) | 53.9% (317) |
| Role only (ppg<15) | 66.3% (240) | 56.3% (174) |

### Key Findings

1. **Tier-filtered training HURTS performance** — training on all players is best
2. **Starters+ filter is worst** — drops HR by 20+ pp vs all-players (60.3% vs 81.6%)
3. **Role-only is middle ground** — better than Starters+ but worse than all
4. **The full player pool provides better signal** — more data points help model generalize
5. **Don't build tier-specific models** — universal model is superior

---

## Step 3: Lines-Only Training

### Config C (V12 MAE RSM50)

| Training Pop | W2 HR 3+ (N) | W4 HR 3+ (N) |
|-------------|-------------|-------------|
| All players | 80.3% (122) | 57.9% (38) |
| Lines-only | 74.7% (142) | 70.6% (34) |

### Config E (V9 MAE)

| Training Pop | W2 HR 3+ (N) | W4 HR 3+ (N) |
|-------------|-------------|-------------|
| All players | 81.6% (103) | 66.7% (6) |
| Lines-only | 88.0% (100) | 50.0% (4) |

### Key Findings

1. **Lines-only is a mixed bag** — improves W4 for Config C (+12.7pp!) but hurts W2 (-5.6pp)
2. **Config E lines-only W2 is best single result** — 88.0% HR (n=100), impressive
3. **W4 sample sizes are tiny** — can't draw conclusions from n=4 or n=34
4. **No clear winner** — lines-only changes the distribution, sometimes helping, sometimes hurting
5. **Needs more eval windows** to determine if lines-only is consistently better

---

## Step 4: Staleness Curve (Config C, eval Feb 1-13)

| Gap (days) | Train End | HR 3+ | N 3+ | MAE |
|-----------|-----------|-------|------|-----|
| 7 | Jan 25 | 57.9% | 38 | 4.89 |
| 14 | Jan 18 | 62.9% | 35 | 4.85 |
| 21 | Jan 11 | 56.4% | 39 | 4.91 |
| 28 | Jan 4 | 66.7% | 36 | 4.84 |
| 42 | Dec 21 | 60.9% | 64 | 4.95 |
| 63 | Nov 30 | 60.7% | 89 | 5.02 |

### Key Findings

1. **No clear staleness decay pattern!** — 28-day gap (66.7%) beats 7-day gap (57.9%)
2. **Even 63-day gap maintains 60.7%** — far above breakeven
3. **MAE slowly increases with gap** (4.84 → 5.02) but HR doesn't correlate
4. **HR fluctuation is dominated by small sample noise** — 35-39 picks in most windows
5. **Retrain cadence: Monthly is fine** — no evidence weekly retraining helps
6. **More training data helps volume** — 63-day gap produces 89 picks vs 35-38 for shorter gaps

---

## Master Summary

### Overall Rankings

| Rank | Config | Avg HR 3+ | Best Window | Worst Window | Strengths | Weaknesses |
|------|--------|----------|-------------|-------------|-----------|------------|
| 1 | **E: V9 MAE 33f** | 78.3% | W3: 93.5% | W4: 66.7% | Highest avg, simplest | Tiny N in later windows |
| 2 | **C: V12 MAE RSM50** | 72.9% | W3: 85.9% | W4: 57.9% | Consistent, good N | Slightly lower than E |
| 3 | **A: V12 MAE default** | 72.8% | W2: 88.4% | W4: 57.1% | Good W2 performance | Small N in W4 |
| 4 | D: V12 Q43 | 63.5% | W2: 74.2% | W4: 58.2% | Highest pick volume | Lower accuracy |
| 5 | B: V12 Huber | 61.5% | W2: 72.9% | W4: 50.8% | High volume | Below breakeven W4 |

### Decision Criteria Assessment

| Criterion | E (V9 MAE) | C (V12 MAE RSM50) |
|-----------|-----------|-------------------|
| All windows > 52.4%? | YES (4/4) | YES (4/4) |
| N >= 50 in all windows? | NO (W4=6) | NO (W4=38) |
| OVER + UNDER balanced? | YES | YES (most windows) |
| Better than champion 39.9%? | YES (78.3% avg) | YES (72.9% avg) |
| Retrain cadence OK? | Monthly fine | Monthly fine |

### Recommendations

1. **Both E and C massively beat the decayed champion** (39.9% → 72-78% avg)
2. **Config E (V9 33f MAE) is the best performer** but generates very few edge 3+ picks in recent windows
3. **Config C (V12 50f MAE RSM50, no-vegas) is the best deployable option** — good accuracy + reasonable volume
4. **Don't tier-filter training data** — universal model is best
5. **Lines-only training is inconclusive** — needs more investigation
6. **Monthly retraining is sufficient** — no evidence of fast decay within 4 weeks
7. **W4 (most recent) is hardest for all configs** — may indicate regime shift or sample noise

### Critical Caveat

Config E's W3 (93.5%, n=46) and W4 (66.7%, n=6) have very small samples. The high average may be inflated. Config C is more trustworthy due to larger, more consistent sample sizes.

### Next Steps

1. Deploy best config as shadow model for 2+ days
2. For V9 (Config E): investigate why it generates so few edge 3+ picks in Feb
3. For V12 RSM50 (Config C): consider as primary shadow challenger
4. Monitor both configs via `compare-model-performance.py`
5. If deploying: use W2 train dates (Nov 2 → Dec 28) for freshest model
