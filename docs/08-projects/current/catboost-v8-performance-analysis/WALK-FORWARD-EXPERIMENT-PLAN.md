# Walk-Forward Validation Experiment Plan

**Created:** 2026-01-29
**Status:** PLANNING
**Goal:** Understand optimal training strategy through systematic experimentation

---

## 1. Experiment Overview

### Questions We Want to Answer

| Question | How We'll Answer It |
|----------|---------------------|
| How much training data is optimal? | Compare 1-season vs 2-season vs 3-season training |
| How quickly does model performance decay? | Track hit rate by months-since-training |
| Is recent data more valuable than older data? | Compare same-size windows at different recencies |
| How often should we retrain? | Analyze decay curves to find optimal refresh rate |

### Data Available

| Season | Feature Records | Prop Lines Overlap | Usable for Training | Usable for Evaluation |
|--------|-----------------|-------------------|---------------------|----------------------|
| 2021-22 | 29,417 | 13,782 | Yes | Yes |
| 2022-23 | 25,565 | 13,611 | Yes | Yes |
| 2023-24 | 25,948 | 14,776 | Yes | Yes |
| 2024-25 | 25,846 | 17,498 | Yes | Yes |
| 2025-26 | 20,899 | 4,658 | Partial | Yes (forward-looking) |

---

## 2. Model Naming Convention

**Format:** `catboost_v{version}_{experiment}_{timestamp}`

| Component | Description | Example |
|-----------|-------------|---------|
| version | Major version (v9 for this experiment series) | v9 |
| experiment | Experiment identifier | exp_1season, exp_2season |
| timestamp | Training timestamp | 20260129_143022 |

**Examples:**
- `catboost_v9_exp_1season_A_20260129_143022` - Trained on 2021-22, predicts 2022-23
- `catboost_v9_exp_2season_B_20260129_150000` - Trained on 2021-23, predicts 2023-24
- `catboost_v9_prod_20260201_120000` - Final production model after experiments

---

## 3. Experiment Definitions

### Experiment Series A: Training Window Size

**Question:** How much historical data should we train on?

| Exp ID | Train Period | Train Seasons | Eval Period | Eval Months |
|--------|--------------|---------------|-------------|-------------|
| A1 | 2021-22 | 1 season | 2022-23 | Full season |
| A2 | 2021-22 to 2022-23 | 2 seasons | 2023-24 | Full season |
| A3 | 2021-22 to 2023-24 | 3 seasons | 2024-25 | Full season |

### Experiment Series B: Recency vs Volume

**Question:** Is 1 recent season better than 2 older seasons?

| Exp ID | Train Period | Train Seasons | Eval Period | Notes |
|--------|--------------|---------------|-------------|-------|
| B1 | 2021-22 to 2022-23 | 2 seasons (older) | 2024-25 | Older data, more volume |
| B2 | 2023-24 | 1 season (recent) | 2024-25 | Recent data, less volume |
| B3 | 2022-23 to 2023-24 | 2 seasons (recent) | 2024-25 | Balance of both |

### Experiment Series C: Decay Analysis

**Question:** How quickly does model performance degrade?

| Exp ID | Train Period | Eval Periods (Monthly) |
|--------|--------------|------------------------|
| C1 | 2021-22 to 2022-23 | Nov 2023, Dec 2023, Jan 2024, ..., Jun 2024 |

We'll measure hit rate for each month to see the decay curve.

### Experiment Series D: Current Model Validation

**Question:** Does the current V8 training (2021-24) still have value?

| Exp ID | Description | What We Measure |
|--------|-------------|-----------------|
| D1 | Use existing V8 model | Hit rate on 2024-25 season (already have this data!) |
| D2 | Retrain V8 with same params on 2021-25 | Compare to D1 |

---

## 4. Evaluation Metrics

### Primary Metrics

| Metric | Formula | Target | Breakeven |
|--------|---------|--------|-----------|
| **Hit Rate** | Hits / (Hits + Misses) | >55% | 52.4% |
| **ROI** | (Wins × 0.909 - Losses) / Total | >5% | 0% |

### Secondary Metrics

| Metric | Purpose |
|--------|---------|
| MAE (Mean Absolute Error) | Point prediction accuracy |
| Confidence Calibration | Does 90% confidence = 90% hit rate? |
| OVER vs UNDER split | Are we better at one direction? |
| By player tier (stars vs role) | Segment analysis |

### Evaluation Rules

1. **Exclude pushes** - When actual = line
2. **Exclude NULL points** - Games not played / DNP
3. **Only evaluate on games with prop lines** - Can't bet without a line
4. **Normalize confidence scores** - Convert all to 0-100 scale

---

## 5. Implementation Plan

### Step 1: Create Experiment Training Script

Create `ml/experiments/train_walkforward.py` that:
- Takes command-line args for train start/end dates
- Uses consistent feature extraction (same as V8)
- Saves model with proper naming convention
- Outputs metadata JSON with all params

### Step 2: Create Evaluation Script

Create `ml/experiments/evaluate_model.py` that:
- Takes model path and eval period as args
- Generates predictions for eval period
- Calculates all metrics
- Outputs results to JSON

### Step 3: Create Results Tracker

Create `ml/experiments/results/` directory with:
- JSON file per experiment
- Summary dashboard script
- Comparison charts

### Step 4: Run Experiments

Priority order:
1. **D1** - Already have data, just need to calculate
2. **A1, A2, A3** - Understand training window size
3. **B1, B2, B3** - Understand recency vs volume
4. **C1** - Understand decay curve

---

## 6. Results Tracking Template

### Per-Experiment JSON

```json
{
  "experiment_id": "A1",
  "model_name": "catboost_v9_exp_1season_A1_20260129_143022",
  "train_period": {
    "start": "2021-11-01",
    "end": "2022-06-30",
    "samples": 29417,
    "seasons": 1
  },
  "eval_period": {
    "start": "2022-11-01",
    "end": "2023-06-30",
    "predictions": 13611,
    "graded": 12500
  },
  "results": {
    "hit_rate": 0.0,
    "hits": 0,
    "misses": 0,
    "roi": 0.0,
    "mae": 0.0
  },
  "by_confidence": {
    "95+": {"predictions": 0, "hit_rate": 0.0},
    "90-95": {"predictions": 0, "hit_rate": 0.0},
    "85-90": {"predictions": 0, "hit_rate": 0.0},
    "80-85": {"predictions": 0, "hit_rate": 0.0},
    "<80": {"predictions": 0, "hit_rate": 0.0}
  },
  "by_direction": {
    "OVER": {"predictions": 0, "hit_rate": 0.0},
    "UNDER": {"predictions": 0, "hit_rate": 0.0}
  },
  "trained_at": "2026-01-29T14:30:22Z",
  "evaluated_at": "2026-01-29T14:45:00Z"
}
```

### Summary Table (to be populated)

| Exp | Train Period | Train Samples | Eval Period | Hit Rate | ROI | MAE |
|-----|--------------|---------------|-------------|----------|-----|-----|
| A1 | 2021-22 | ~29K | 2022-23 | TBD | TBD | TBD |
| A2 | 2021-23 | ~55K | 2023-24 | TBD | TBD | TBD |
| A3 | 2021-24 | ~81K | 2024-25 | TBD | TBD | TBD |
| B1 | 2021-23 | ~55K | 2024-25 | TBD | TBD | TBD |
| B2 | 2023-24 | ~26K | 2024-25 | TBD | TBD | TBD |
| B3 | 2022-24 | ~51K | 2024-25 | TBD | TBD | TBD |

---

## 7. Success Criteria

After experiments, we should be able to answer:

1. **Optimal training window:** "Train on X seasons of data"
2. **Retrain frequency:** "Retrain every X months"
3. **Expected performance:** "Expect Y% hit rate in month 1, decaying to Z% by month 6"
4. **Production strategy:** Clear recommendation for V9 production model

---

## 8. Next Steps

- [ ] Review and approve this experiment plan
- [ ] Create `ml/experiments/` directory structure
- [ ] Implement training script with date parameters
- [ ] Implement evaluation script
- [ ] Run Experiment D1 first (uses existing V8 model)
- [ ] Run Series A experiments
- [ ] Analyze results and adjust plan

---

*Document created: 2026-01-29*
*Status: Awaiting review*
