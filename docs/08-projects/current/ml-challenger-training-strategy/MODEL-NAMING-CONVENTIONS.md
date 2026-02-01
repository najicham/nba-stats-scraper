# ML Model Naming Conventions

**Date:** 2026-01-31 (Session 60)
**Purpose:** Establish clear naming conventions for experimental vs production models

---

## Current State (Messy)

Looking at `ml/experiments/results/`, we have:
- `catboost_v9_exp_A1_*` through `catboost_v9_exp_JAN_*` (40+ variants)
- `catboost_v11_exp_*` (3 variants)
- `catboost_v12_*` (3 variants)
- `ensemble_exp_ENS_*` (2 variants)

**Problem:** "V9" through "V12" suggest production versions, but these are all experimental.

---

## Proposed Naming Convention

### Production Models: `catboost_vN`

Only use version numbers (`v8`, `v9`, etc.) for **production deployed models**.

| Version | Status | Deployed | Notes |
|---------|--------|----------|-------|
| v8 | PRODUCTION | Yes | Current production model |
| v9 | RESERVED | No | Next production version |
| v10+ | RESERVED | No | Future versions |

### Experimental Models: `exp_YYYYMMDD_HYPOTHESIS`

Use date-based naming with hypothesis suffix:

```
exp_20260131_draftkings_only
exp_20260131_recency_90d
exp_20260131_multi_book
exp_20260131_seasonal_weighted
```

**Format:** `exp_YYYYMMDD_[brief_hypothesis]`

### Challenger Models: `challenger_YYYYMMDD_HYPOTHESIS`

When an experiment is promoted for shadow evaluation:

```
challenger_20260201_recency_90d
```

### Model Files

```
# Experiment
ml/experiments/results/exp_20260131_recency_90d.cbm
ml/experiments/results/exp_20260131_recency_90d_metadata.json

# Promoted to challenger
models/challengers/challenger_20260201_recency_90d.cbm

# Production (only after proven)
models/catboost_v9_20260215.cbm
```

---

## Experiment Registry Integration

The `experiment_registry.py` already tracks experiments in BigQuery. Enhance it to:

1. **Enforce naming**: Reject `v*` names for experiments
2. **Track status**: pending → running → completed → validated → promoted → rejected
3. **Link models**: Store GCS path to model artifact

```python
# Good
registry.register(
    experiment_id="exp_20260131_recency_90d",
    name="90-day recency weighting test",
    hypothesis="Recent games should be weighted more heavily"
)

# Bad - would be rejected
registry.register(
    experiment_id="v9_recency",  # ERROR: Cannot use vN naming for experiments
    ...
)
```

---

## Training Data Bookmaker Strategy

### Question: V8 used Consensus - should V9 use one book or all?

**Options:**

| Strategy | Pros | Cons |
|----------|------|------|
| **Single Book (DraftKings)** | Matches user betting experience | Less training data |
| **Consensus** | Most stable/robust lines | Calibration mismatch with DK |
| **Multi-Book with indicator** | Model learns book-specific patterns | More complex, needs more data |

### Recommendation: Start Simple

**Phase 1: Train on DraftKings only**
- Use Odds API DraftKings for Oct-Jan 2025-26 (~40K samples)
- Compare hit rates vs V8 (Consensus-trained)
- If better, promote to production

**Phase 2: Consider Multi-Book (later)**
- Add bookmaker as a categorical feature
- Let model learn book-specific biases
- Requires more training data

### Why Not All Books At Once?

1. **Calibration noise**: Different books have different biases
2. **Harder to debug**: Which book's pattern is causing issues?
3. **Training efficiency**: Start with the book users bet on

---

## Historical Validator Enhancement

### Current State

`/validate-historical` checks `player_game_summary` field completeness.

### Gaps to Add

Should also check:
1. **Game lines coverage** (spreads/totals per game)
2. **Player props coverage** (lines per player)
3. **Feature store coverage** (ML features per game)

### Proposed Enhancement

Add to `/validate-historical`:

```sql
-- Check game lines coverage
SELECT game_date,
  COUNT(DISTINCT s.game_id) as scheduled,
  COUNT(DISTINCT g.game_id) as with_lines,
  ROUND(100.0 * COUNT(DISTINCT g.game_id) / COUNT(DISTINCT s.game_id), 1) as lines_pct
FROM schedule s
LEFT JOIN game_lines g ON s.game_id = g.game_id
WHERE game_date BETWEEN @start AND @end
GROUP BY 1

-- Check player props coverage
SELECT game_date,
  COUNT(*) as players_with_lines
FROM odds_api_player_points_props
WHERE game_date BETWEEN @start AND @end
GROUP BY 1
```

**Alternative:** Keep `/validate-scraped-data` separate for raw data, `/validate-historical` for processed data.

---

## Action Items

1. **Rename existing experiments** (or leave as-is, just follow new convention going forward)
2. **Update experiment_registry.py** to enforce naming
3. **Create experiment naming validation** in pre-commit hook
4. **Enhance validate-historical** or integrate with validate-scraped-data
5. **Train first DraftKings-only experiment** with proper naming

---

## Example: Next Experiment

```python
from ml.experiments.experiment_registry import ExperimentRegistry

registry = ExperimentRegistry()

# Register with proper naming
registry.register(
    experiment_id="exp_20260201_dk_only",
    name="DraftKings-only training",
    hypothesis="Training on DraftKings lines will improve hit rate for DK bettors",
    test_type="comparison",
    config={
        "bookmaker": "draftkings",
        "data_source": "odds_api",
        "date_range": "2025-10-22 to 2026-01-31",
        "train_split": 0.8,
        "recency_weighting": False
    }
)

# Run training...

# Complete with results
registry.complete(
    experiment_id="exp_20260201_dk_only",
    results={
        "mae": 3.42,
        "hit_rate_premium": 0.54,
        "sample_size": 38000
    },
    model_path="ml/experiments/results/exp_20260201_dk_only.cbm"
)
```

---

*Created: 2026-01-31*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
