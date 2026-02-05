# Session 124: Model Naming Refresh & Subset Review

**Date:** 2026-02-04
**Status:** In Progress
**Goal:** Create properly named models and validate subset performance

---

## Background

### Current Problem
- `catboost_v9` is ambiguous - could be original (trained to Jan 8) or retrain (to Jan 31)
- No way to know training dates from system_id
- Subset filtering may be too restrictive (top 5 limit)

### Decision: Create New Models vs Rename
- **Chosen:** Create new models (safer, no data migration needed)
- Renaming would affect 1,148+ references across codebase

---

## Naming Convention

**Format:** `catboost_v9_{start_date}_{end_date}`

| Model | system_id | Training Window |
|-------|-----------|-----------------|
| Original V9 | `catboost_v9_20251102_20260108` | Nov 2, 2025 → Jan 8, 2026 |
| Feb Retrain | `catboost_v9_20251102_20260131` | Nov 2, 2025 → Jan 31, 2026 |

**Feature count:** Store in DB (`ml_model_registry.feature_count`) not in name

---

## Tasks

### 1. Validate Experiment Skill
- [ ] Run experiments on both training windows
- [ ] Compare skill output to production performance
- [ ] Check if skill should include subset filtering

### 2. Train New Models with Proper Names
- [ ] Train `catboost_v9_20251102_20260108` (original window)
- [ ] Train `catboost_v9_20251102_20260131` (extended window)
- [ ] Register in ml_model_registry with feature_count

### 3. Review Subset Filtering
- [ ] Check if top_n=5 is too restrictive
- [ ] Consider `v9_high_edge_any` (all qualifying picks)
- [ ] Compare historical performance: top 5 vs all qualifying

---

## Subset Definitions (Current)

| subset_id | min_edge | top_n | use_ranking |
|-----------|----------|-------|-------------|
| v9_high_edge_any | 5.0 | NULL | false |
| v9_high_edge_top5 | 5.0 | 5 | true |
| v9_high_edge_top10 | 5.0 | 10 | true |
| optimal_over | 5.0 | NULL | false |
| optimal_under | 3.0 | NULL | false |

**Question:** Should default recommendation use `v9_high_edge_any` (all edge>=5) instead of `v9_high_edge_top5`?

---

## Experiment Plan

### Experiment 1: Original Training Window
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_20251102_20260108" \
    --train-start 2025-11-02 --train-end 2026-01-08 \
    --eval-start 2026-01-09 --eval-end 2026-01-31 \
    --hypothesis "Original V9 training window validation"
```

### Experiment 2: Extended Training Window
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_20251102_20260131" \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-03 \
    --hypothesis "Extended training window with more data"
```

---

## Success Criteria

1. Both models train successfully with proper names
2. Performance metrics comparable to current V9 baseline
3. Clear recommendation on subset filtering (top N vs all)
4. Model registered with feature_count metadata

---

## Files Modified

| File | Change |
|------|--------|
| TBD | TBD |

---

*Session 124 - Model Naming Refresh*
