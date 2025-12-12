# Implementation Plan: Adaptive Learning System

**Last Updated:** 2025-12-11

---

## Overview

This plan takes us from static ensemble to adaptive, context-aware predictions.

```
Current State                         Target State
─────────────                         ────────────
Static 25/25/25/25 weights    →    Context-aware dynamic weights
Tier adjustments only          →    Multi-dimensional adjustments
Manual analysis                →    Automated pattern discovery
No experimentation             →    Continuous A/B testing
```

---

## Prerequisites

Before starting this project:

- [ ] **Four-season backfill complete** (all phases through grading)
- [ ] **Tier adjustments validated** (improving MAE)
- [ ] **Daily orchestration running** (new data flowing)

---

## Phase 1: Discovery (Analysis Only)

**Goal:** Determine if context-aware weights are worth building.

**Duration:** After backfill completes

### Tasks

1. **Run baseline analysis**
   ```bash
   # Run queries from ANALYSIS-QUERIES.md
   # Query 1: Overall system performance
   # Query 9: Compare static vs oracle best
   ```

2. **Quantify the opportunity**
   - What's the MAE gap between static ensemble and "oracle" (always picking best system)?
   - If gap < 0.05: Stop here, not worth complexity
   - If gap > 0.1: High value, proceed

3. **Identify key context dimensions**
   - Which dimensions show largest performance differences?
   - Are patterns consistent across seasons?

4. **Document findings**
   - Create `DISCOVERY-RESULTS.md` with analysis results
   - Recommendation: proceed or not

### Decision Gate

| Finding | Decision |
|---------|----------|
| Gap < 0.05 MAE | Stop - not worth it |
| Gap 0.05-0.10 MAE | Proceed with caution |
| Gap > 0.10 MAE | Full speed ahead |

---

## Phase 2: Static Context Weights

**Goal:** Implement context-aware weights as a lookup table (not dynamic ML).

**Duration:** After Phase 1 confirms value

### Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                    CONTEXT WEIGHT LOOKUP TABLE                          │
│                                                                         │
│  season_phase │ scoring_tier │ xgboost │ similarity │ zone │ mov_avg  │
│  ─────────────│──────────────│─────────│────────────│──────│──────────│
│  EARLY        │ BENCH        │ 0.20    │ 0.35       │ 0.25 │ 0.20     │
│  EARLY        │ ROTATION     │ 0.22    │ 0.33       │ 0.25 │ 0.20     │
│  EARLY        │ STARTER      │ 0.25    │ 0.30       │ 0.25 │ 0.20     │
│  EARLY        │ STAR         │ 0.28    │ 0.27       │ 0.25 │ 0.20     │
│  MID_EARLY    │ BENCH        │ 0.28    │ 0.27       │ 0.25 │ 0.20     │
│  ...          │ ...          │ ...     │ ...        │ ...  │ ...      │
└────────────────────────────────────────────────────────────────────────┘
```

### Tasks

1. **Create schema**
   ```sql
   -- schemas/bigquery/nba_predictions/context_weights.sql
   CREATE TABLE nba_predictions.context_weights (
     context_id STRING,          -- Hash of context dimensions
     season_phase STRING,
     scoring_tier STRING,
     xgboost_weight FLOAT64,
     similarity_weight FLOAT64,
     zone_weight FLOAT64,
     moving_avg_weight FLOAT64,
     sample_size INT64,
     mae_at_computation FLOAT64,
     computed_at TIMESTAMP,
     valid_from DATE,
     valid_until DATE
   )
   ```

2. **Create weight computation processor**
   ```
   data_processors/ml_feedback/context_weight_processor.py
   - Queries historical performance by context
   - Computes inverse-MAE weights
   - Applies guardrails (min 0.1, max 0.6 per system)
   - Stores in context_weights table
   ```

3. **Create weight lookup service**
   ```
   predictions/worker/services/weight_service.py
   - get_weights(season_phase, scoring_tier) -> dict
   - Fallback to defaults if context not found
   - Cache for performance
   ```

4. **Create ensemble_v2 predictor**
   ```
   predictions/worker/prediction_systems/ensemble_v2_context.py
   - Uses weight_service instead of static weights
   - Otherwise identical to ensemble_v1
   ```

5. **Backfill with new system**
   - Run ensemble_v2_context for all historical dates
   - Compare MAE vs ensemble_v1
   - Validate improvement

### Validation

```sql
-- Compare v1 vs v2 on same predictions
SELECT
  'ensemble_v1' as system,
  AVG(absolute_error) as mae
FROM prediction_accuracy
WHERE system_id = 'ensemble_v1'

UNION ALL

SELECT
  'ensemble_v2_context' as system,
  AVG(absolute_error) as mae
FROM prediction_accuracy
WHERE system_id = 'ensemble_v2_context';
```

---

## Phase 3: Additional Adjustments

**Goal:** Add context-specific bias corrections beyond tier.

### 3A: Age-Based Adjustments

**Hypothesis:** Veterans on back-to-backs need larger downward adjustment.

1. **Enrich predictions with player age**
   - Add age to ml_feature_store or prediction record

2. **Compute age-rest adjustments**
   ```sql
   -- Find bias by age group + rest status
   SELECT
     age_group,
     rest_status,
     AVG(signed_error) as bias,
     COUNT(*) as n
   FROM enriched_accuracy
   GROUP BY 1, 2
   ```

3. **Create context_adjustments table**
   ```sql
   INSERT INTO context_adjustments
   VALUES ('AGE_REST', 'VETERAN_B2B', -2.1, 0.75, 500, 'HIGH', ...)
   ```

4. **Apply in prediction pipeline**
   - After tier adjustment, check for applicable context adjustments
   - Stack adjustments (tier + age_rest + home_away)

### 3B: Opponent Defense Adjustments

**Hypothesis:** Elite defenses suppress scoring more than models expect.

1. **Enrich with opponent defensive rating**
2. **Compute bias by opponent tier**
3. **Add adjustment for ELITE_DEFENSE context**

### 3C: Fatigue Adjustments

**Hypothesis:** High minutes + back-to-back = significant dropoff for older players.

1. **Create fatigue risk score**
   ```python
   fatigue_risk = (
     (age - 25) * 0.1 +           # Age factor
     (recent_minutes - 30) * 0.05 + # Minutes load
     (is_b2b * 2.0)                # Back-to-back
   )
   ```

2. **Apply adjustment based on fatigue risk**

---

## Phase 4: Automated Learning Loop

**Goal:** System continuously improves without manual intervention.

### Weekly Recomputation Job

```python
# jobs/weekly_model_update.py
def weekly_update():
    """Run every Monday 6am."""

    # 1. Recompute context weights from last 60 days
    context_weight_processor.compute_weights(
        lookback_days=60,
        as_of_date=today()
    )

    # 2. Recompute tier adjustments
    tier_processor.process(today())

    # 3. Recompute context adjustments
    context_adjustment_processor.process(today())

    # 4. Validate all changes improve MAE
    validate_changes()

    # 5. Log to evolution_log
    log_update(...)
```

### Automated Alerting

```python
# Alert if patterns shift significantly
def check_pattern_drift():
    """Alert if optimal weights changed significantly."""
    old_weights = get_weights(last_week)
    new_weights = get_weights(this_week)

    for context, weights in new_weights.items():
        for system, weight in weights.items():
            old = old_weights[context][system]
            if abs(weight - old) > 0.1:
                alert(f"Weight drift: {context}/{system}: {old} -> {weight}")
```

---

## Phase 5: Experimentation Framework

**Goal:** Test new ideas safely before deploying.

### Experiment Workflow

```
1. Create experiment
   - Define hypothesis
   - Define test system_id
   - Set duration

2. Shadow run
   - Run test system alongside production
   - Don't use results for publishing

3. Analyze
   - Compare MAE, win rate, bias
   - Check statistical significance

4. Decide
   - Promote: Make test the new default
   - Reject: Archive learnings
   - Extend: Need more data

5. Log
   - Record decision and rationale
```

### Experiment Table

```sql
CREATE TABLE nba_predictions.experiments (
  experiment_id STRING,
  name STRING,
  hypothesis STRING,
  status STRING,  -- 'SHADOW', 'ANALYZING', 'PROMOTED', 'REJECTED'

  test_system_id STRING,
  baseline_system_id STRING,

  start_date DATE,
  end_date DATE,

  results STRUCT<
    baseline_mae FLOAT64,
    test_mae FLOAT64,
    improvement FLOAT64,
    p_value FLOAT64,
    sample_size INT64
  >,

  decision STRING,
  decision_notes STRING,
  decided_by STRING,
  decided_at TIMESTAMP
);
```

---

## Timeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          PROJECT TIMELINE                                │
│                                                                          │
│  Prerequisite: Four-season backfill must complete first                 │
│                                                                          │
│  Phase 1: Discovery                                                      │
│  └── Run analysis queries                                               │
│  └── Document findings                                                   │
│  └── Go/No-go decision                                                   │
│                                                                          │
│  Phase 2: Static Context Weights                                         │
│  └── Create context_weights table                                        │
│  └── Build weight processor                                              │
│  └── Build ensemble_v2                                                   │
│  └── Backfill and validate                                               │
│                                                                          │
│  Phase 3: Additional Adjustments                                         │
│  └── Age-based adjustments                                               │
│  └── Opponent defense adjustments                                        │
│  └── Fatigue modeling                                                    │
│                                                                          │
│  Phase 4: Automated Learning                                             │
│  └── Weekly recomputation job                                            │
│  └── Drift alerting                                                      │
│                                                                          │
│  Phase 5: Experimentation                                                │
│  └── Experiment framework                                                │
│  └── Shadow testing capability                                           │
│  └── Statistical significance testing                                    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Success Criteria

| Milestone | Criteria |
|-----------|----------|
| Phase 1 complete | Analysis documented, decision made |
| Phase 2 complete | ensemble_v2 MAE < ensemble_v1 MAE by > 0.05 |
| Phase 3 complete | Additional adjustments improve MAE |
| Phase 4 complete | Weekly job running, no manual intervention needed |
| Phase 5 complete | Can run experiments without production risk |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Overfitting to historical data | Validate on holdout seasons |
| Context weights too unstable | Apply smoothing, min sample sizes |
| Complexity without improvement | Gate each phase on measured improvement |
| Backfill takes too long | Start with prediction-only changes first |

---

## Files to Create

```
data_processors/ml_feedback/
├── context_weight_processor.py    # Phase 2
├── context_adjustment_processor.py # Phase 3
└── experiment_analyzer.py          # Phase 5

predictions/worker/
├── services/
│   └── weight_service.py           # Phase 2
└── prediction_systems/
    └── ensemble_v2_context.py      # Phase 2

schemas/bigquery/nba_predictions/
├── context_weights.sql             # Phase 2
├── context_adjustments.sql         # Phase 3
├── experiments.sql                 # Phase 5
└── evolution_log.sql               # Phase 4

jobs/
└── weekly_model_update.py          # Phase 4
```

---

## Next Action

**Wait for four-season backfill to complete, then:**

1. Run Query 1 and Query 9 from ANALYSIS-QUERIES.md
2. Document the MAE gap between static and oracle
3. Make go/no-go decision on Phase 2
