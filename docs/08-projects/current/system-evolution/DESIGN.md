# Adaptive Ensemble Design

**Last Updated:** 2025-12-11

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PREDICTION REQUEST                                    │
│                                                                              │
│  Player: LeBron James                                                        │
│  Game: Dec 15, 2024 vs Warriors                                              │
│  Context: Game #28 of season, Age 40, Back-to-back, Away game               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      CONTEXT EXTRACTOR                                       │
│                                                                              │
│  season_phase: 'MID_SEASON'     (game 21-50)                                │
│  player_tier: 'STAR'            (30+ avg)                                   │
│  player_age_group: 'VETERAN'    (35+)                                       │
│  rest_status: 'BACK_TO_BACK'                                                │
│  location: 'AWAY'                                                           │
│  opponent_strength: 'TOP_10_DEFENSE'                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      WEIGHT LOOKUP                                           │
│                                                                              │
│  Query: system_context_performance                                          │
│  Filter: season_phase='MID_SEASON', player_tier='STAR', age_group='VETERAN' │
│                                                                              │
│  Historical MAE by system for this context:                                 │
│    xgboost_v1:              4.2  →  weight: 0.35                            │
│    similarity_balanced_v1:  4.8  →  weight: 0.20                            │
│    zone_matchup_v1:         4.5  →  weight: 0.25                            │
│    moving_average_v1:       5.1  →  weight: 0.20                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      WEIGHTED ENSEMBLE                                       │
│                                                                              │
│  xgboost:     24.5 pts × 0.35 = 8.575                                       │
│  similarity:  23.8 pts × 0.20 = 4.760                                       │
│  zone:        25.1 pts × 0.25 = 6.275                                       │
│  moving_avg:  24.2 pts × 0.20 = 4.840                                       │
│                                                                              │
│  Raw prediction: 24.45 pts                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      TIER + CONTEXT ADJUSTMENTS                              │
│                                                                              │
│  Tier adjustment (STAR): +1.2 pts                                           │
│  Veteran B2B adjustment: -2.5 pts                                           │
│  Away game adjustment: -0.3 pts                                             │
│                                                                              │
│  Final prediction: 22.85 pts                                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### 1. `system_context_performance` - Historical Performance by Context

Stores aggregated performance metrics for each system in each context combination.

```sql
CREATE TABLE nba_predictions.system_context_performance (
  -- Context dimensions
  season_phase STRING,           -- 'EARLY', 'MID', 'LATE', 'PLAYOFFS'
  player_tier STRING,            -- 'BENCH', 'ROTATION', 'STARTER', 'STAR'
  player_age_group STRING,       -- 'YOUNG', 'PRIME', 'VETERAN'
  rest_status STRING,            -- 'RESTED', 'NORMAL', 'BACK_TO_BACK'
  location STRING,               -- 'HOME', 'AWAY'
  opponent_defense STRING,       -- 'ELITE', 'GOOD', 'AVERAGE', 'POOR'

  -- System being evaluated
  system_id STRING,

  -- Performance metrics
  sample_size INT64,
  mae FLOAT64,
  bias FLOAT64,
  win_rate FLOAT64,
  within_3_pct FLOAT64,
  within_5_pct FLOAT64,

  -- Derived weight (inverse MAE, normalized)
  computed_weight FLOAT64,

  -- Metadata
  computed_at TIMESTAMP,
  lookback_start DATE,
  lookback_end DATE,
  season STRING                  -- Which season(s) this was computed from
)
PARTITION BY DATE_TRUNC(computed_at, MONTH)
CLUSTER BY season_phase, player_tier, system_id;
```

### 2. `context_adjustments` - Additive Corrections by Context

Like tier adjustments, but for other contexts.

```sql
CREATE TABLE nba_predictions.context_adjustments (
  adjustment_type STRING,        -- 'VETERAN_B2B', 'HOME_COURT', 'ELITE_DEFENSE'
  context_key STRING,            -- Specific context value

  adjustment_value FLOAT64,      -- Points to add/subtract
  adjustment_factor FLOAT64,     -- Scaling factor (0-1)

  sample_size INT64,
  confidence STRING,             -- 'HIGH', 'MEDIUM', 'LOW'

  as_of_date DATE,
  computed_at TIMESTAMP
)
PARTITION BY as_of_date
CLUSTER BY adjustment_type;
```

### 3. `experiment_registry` - Track Experiments

```sql
CREATE TABLE nba_predictions.experiment_registry (
  experiment_id STRING,
  name STRING,
  hypothesis STRING,

  -- What we're testing
  test_type STRING,              -- 'WEIGHT_CHANGE', 'NEW_SYSTEM', 'NEW_ADJUSTMENT'
  baseline_config JSON,          -- Current configuration
  test_config JSON,              -- What we're testing

  -- Timeline
  status STRING,                 -- 'SHADOW', 'BACKFILL', 'VALIDATED', 'PROMOTED', 'REJECTED'
  started_date DATE,
  ended_date DATE,

  -- Results
  baseline_mae FLOAT64,
  test_mae FLOAT64,
  improvement FLOAT64,
  sample_size INT64,
  p_value FLOAT64,
  is_significant BOOL,

  -- Decision
  decision STRING,               -- 'PROMOTE', 'REJECT', 'NEEDS_MORE_DATA'
  decision_notes STRING,

  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

### 4. `evolution_log` - Track All Changes

Audit trail of every change to the system.

```sql
CREATE TABLE nba_predictions.evolution_log (
  log_id STRING,
  timestamp TIMESTAMP,

  change_type STRING,            -- 'WEIGHT_UPDATE', 'ADJUSTMENT_UPDATE', 'NEW_SYSTEM'
  component STRING,              -- 'ensemble_weights', 'tier_adjustments', 'context_adjustments'

  before_value JSON,
  after_value JSON,

  trigger STRING,                -- 'MANUAL', 'EXPERIMENT_PROMOTION', 'SCHEDULED_RECOMPUTE'
  experiment_id STRING,          -- If from experiment

  impact_mae_change FLOAT64,     -- Measured impact
  notes STRING
);
```

---

## Weight Computation Algorithm

### Option A: Inverse MAE Weighting

Simple approach - weight systems inversely by their MAE in each context.

```python
def compute_context_weights(context: dict, lookback_days: int = 90) -> dict:
    """
    Compute optimal weights for a given context based on historical performance.
    """
    # Query historical performance for this context
    performance = query_system_performance(
        season_phase=context['season_phase'],
        player_tier=context['player_tier'],
        player_age_group=context['player_age_group'],
        lookback_days=lookback_days
    )

    # Filter to contexts with enough samples
    MIN_SAMPLES = 50
    performance = {k: v for k, v in performance.items() if v['sample_size'] >= MIN_SAMPLES}

    # Compute inverse MAE weights
    inverse_maes = {sys: 1.0 / perf['mae'] for sys, perf in performance.items()}
    total = sum(inverse_maes.values())

    weights = {sys: inv_mae / total for sys, inv_mae in inverse_maes.items()}

    return weights
```

### Option B: Softmax Temperature Weighting

More aggressive differentiation between systems.

```python
def compute_context_weights_softmax(context: dict, temperature: float = 0.5) -> dict:
    """
    Use softmax with temperature to compute weights.
    Lower temperature = more weight to best system.
    Higher temperature = more equal weights.
    """
    performance = query_system_performance(context)

    # Convert MAE to scores (negative so lower MAE = higher score)
    scores = {sys: -perf['mae'] for sys, perf in performance.items()}

    # Apply softmax with temperature
    exp_scores = {sys: math.exp(score / temperature) for sys, score in scores.items()}
    total = sum(exp_scores.values())

    weights = {sys: exp / total for sys, exp in exp_scores.items()}

    return weights
```

### Option C: Bayesian Weight Learning

Most sophisticated - learns optimal weights with uncertainty.

```python
def compute_bayesian_weights(context: dict) -> dict:
    """
    Use Bayesian optimization to find weights that minimize MAE.
    Returns weights with uncertainty estimates.
    """
    # This would use historical predictions to find optimal weight combination
    # through cross-validation on past data
    pass
```

---

## Context Hierarchy

Not all context dimensions are equally important. Use a hierarchy:

```
Level 1 (Always use):
├── season_phase          (games 1-20, 21-50, 51-70, 70+)
└── player_tier           (BENCH, ROTATION, STARTER, STAR)

Level 2 (Use if enough samples):
├── player_age_group      (YOUNG <25, PRIME 25-31, VETERAN 32+)
└── rest_status           (RESTED 2+days, NORMAL, B2B)

Level 3 (Use for adjustments only):
├── location              (HOME, AWAY)
└── opponent_defense      (ELITE top-5, GOOD 6-15, AVERAGE 16-25, POOR 26-30)
```

**Fallback Strategy:**
```python
def get_weights_with_fallback(context: dict) -> dict:
    """
    Try most specific context first, fall back to broader context if insufficient samples.
    """
    # Try full context
    weights = lookup_weights(context)
    if weights and weights['min_samples'] >= 50:
        return weights

    # Fall back to Level 1 only
    weights = lookup_weights({
        'season_phase': context['season_phase'],
        'player_tier': context['player_tier']
    })
    if weights and weights['min_samples'] >= 100:
        return weights

    # Fall back to defaults
    return DEFAULT_WEIGHTS
```

---

## Update Cadence

| Component | Update Frequency | Trigger |
|-----------|-----------------|---------|
| Context weights | Weekly | Scheduled job (Monday 6am) |
| Tier adjustments | Weekly | After weight update |
| Context adjustments | Weekly | After tier adjustments |
| Full recompute | Monthly | 1st of month |
| Experiment evaluation | Daily | Automated |

---

## Guardrails

### 1. Minimum Sample Size
Never use weights from contexts with < 50 predictions.

### 2. Maximum Weight
No single system can have weight > 0.6 (prevent over-reliance).

### 3. Minimum Weight
Every system must have weight >= 0.1 (maintain diversity).

### 4. MAE Validation
After any change, validate that overall MAE improved or stayed flat.

```python
def validate_change(before_mae: float, after_mae: float) -> bool:
    """
    Change is valid if MAE improved or got worse by less than 0.05.
    """
    return after_mae <= before_mae + 0.05
```

### 5. Seasonal Consistency
Before promoting a change, verify it improves MAE in at least 2 of 4 seasons.

---

## Integration Points

### Current System
```python
# predictions/worker/prediction_systems/ensemble_v1.py
class EnsembleV1(BasePredictor):
    WEIGHTS = {  # Static weights
        'xgboost_v1': 0.25,
        'moving_average_baseline_v1': 0.25,
        'similarity_balanced_v1': 0.25,
        'zone_matchup_v1': 0.25
    }
```

### Future System
```python
# predictions/worker/prediction_systems/ensemble_v2_adaptive.py
class EnsembleV2Adaptive(BasePredictor):
    def get_weights(self, player_context: dict) -> dict:
        """Dynamically compute weights based on context."""
        return self.weight_service.get_optimal_weights(player_context)
```

---

## Migration Path

1. **Phase 1**: Keep `ensemble_v1` unchanged, add `ensemble_v2_adaptive` as new system
2. **Phase 2**: Run both in parallel, compare performance
3. **Phase 3**: If v2 wins, make it the default in publishing
4. **Phase 4**: Deprecate v1 after full validation
