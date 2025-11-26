# Phase 5 Architectural Design Decisions

**File:** `docs/predictions/design/01-architectural-decisions.md`
**Created:** 2025-11-16
**Purpose:** Document key architectural design decisions and rationale for Phase 5 prediction system
**Status:** ✅ Current

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [The 5 Prediction Systems](#prediction-systems)
3. [Why Cloud Run + Pub/Sub](#cloud-run-pubsub)
4. [Why Hybrid Approach](#hybrid-approach)
5. [Evolution Strategy](#evolution-strategy)
6. [Comparison to Alternatives](#alternatives)
7. [Key Architectural Principles](#principles)
8. [Related Documentation](#related-docs)

---

## 🎯 Executive Summary {#executive-summary}

Phase 5 implements a hybrid prediction approach using 5 independent systems that run in parallel on Cloud Run infrastructure. This document explains **WHY** we designed it this way and the rationale behind key architectural decisions.

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Hybrid Approach** | 2 rules-based + 1 similarity + 1 ML + 1 ensemble |
| **Cloud Run Services** | NOT Flask (requires orchestration + parallelism) |
| **Pub/Sub Orchestration** | Fan-out pattern for 450 players × 5 systems |
| **5 Independent Systems** | Each optimized for different scenarios |
| **Meta Ensemble** | Combines all 4 base systems intelligently |

### Why NOT Pure Machine Learning?

| Issue | Impact |
|-------|--------|
| ❌ Black box | Hard to debug and explain |
| ❌ Requires lots of training data | For edge cases |
| ❌ Can fail catastrophically | In novel situations |
| ❌ Single point of failure | If model breaks, everything breaks |

### Why NOT Pure Rules?

| Issue | Impact |
|-------|--------|
| ❌ Can't discover complex patterns | Across 25 features |
| ❌ Manual tuning required | For every situation |
| ❌ Doesn't adapt automatically | To NBA evolution |
| ❌ Human bias | In rule creation |

### Why Hybrid? ✅

| Benefit | Value |
|---------|-------|
| ✅ Best of both worlds | Explainability + Pattern Discovery |
| ✅ Diversification | Different systems excel in different situations |
| ✅ Redundancy | If one system fails, others keep working |
| ✅ Learning | Compare approaches to improve both rules and ML |
| ✅ Confidence | Agreement between systems = higher confidence |

---

## 🤖 The 5 Prediction Systems {#prediction-systems}

### System 1: Moving Average Baseline

**Type:** Rules-Based (Simple)
**Purpose:** Fast, reliable baseline using weighted averages
**Complexity:** Low
**Implementation:** Week 1

**Algorithm Overview:**

1. Calculate weighted average: Last 5 (40%) + Last 10 (35%) + Season (25%)
2. Apply composite factor adjustments (fatigue, zone mismatch, pace, usage)
3. Add venue adjustment (home +1.2, away -0.8)
4. Calculate confidence based on consistency and data quality

**When It Excels:**

- ✅ Players with consistent performance
- ✅ Normal game circumstances
- ✅ Good recent sample size (8+ games)

**When It Struggles:**

- ❌ Players returning from injury (limited recent data)
- ❌ Extreme matchup advantages/disadvantages
- ❌ Novel situations (rookie debuts, position changes)

**Typical Performance:**

- O/U Accuracy: 50-54%
- MAE: 4.7-5.0 points
- Speed: Very fast (<50ms per prediction)

### System 2: Zone Matchup V1

**Type:** Rules-Based (Advanced)
**Purpose:** Emphasize shot zone analysis and matchup-specific factors
**Complexity:** Medium
**Implementation:** Week 1

**Algorithm Overview:**

1. Analyze player's shot distribution (paint/mid/3pt rates)
2. Compare with opponent's defensive weaknesses by zone
3. Calculate expected points by zone with matchup adjustments
4. Apply fatigue, pace, and usage adjustments
5. High confidence when zone mismatch is extreme

**When It Excels:**

- ✅ Extreme matchup advantages (paint scorer vs weak paint defense)
- ✅ Specialist players (3pt shooters, paint scorers)
- ✅ Well-studied team defensive schemes

**When It Struggles:**

- ❌ Players with balanced shot distribution
- ❌ Opponents with average defense across all zones
- ❌ Limited shot zone data (new players)

**Typical Performance:**

- O/U Accuracy: 52-56%
- MAE: 4.5-4.8 points
- Speed: Fast (100-150ms per prediction)

### System 3: Similarity Balanced V1

**Type:** Hybrid (Similarity Matching + Rules)
**Purpose:** Find similar historical games and learn from outcomes
**Complexity:** High
**Implementation:** Week 3

**Algorithm Overview:**

1. Find 10-20 most similar historical games using cosine similarity
2. Weight by similarity score and recency
3. Calculate baseline from weighted historical outcomes
4. Apply smaller composite factor adjustments (trust history more)
5. High confidence when many high-similarity matches found

**When It Excels:**

- ✅ Common game situations (seen many times before)
- ✅ Players with long history (3+ seasons of data)
- ✅ Repeating patterns (back-to-backs, home/away splits)

**When It Struggles:**

- ❌ Novel situations (no similar historical games)
- ❌ Rookies and new players (limited history)
- ❌ Rapidly changing players (injury recovery, age decline)

**Typical Performance:**

- O/U Accuracy: 54-58%
- MAE: 4.3-4.6 points
- Speed: Moderate (200-400ms per prediction)

### System 4: XGBoost V1

**Type:** Machine Learning (Gradient Boosted Trees)
**Purpose:** Learn complex patterns across all 25 features automatically
**Complexity:** Very High
**Implementation:** Week 2

**Algorithm Overview:**

1. Load trained model from GCS (trained on 365 days of data)
2. Prepare feature vector (all 25 features in exact order)
3. Model predicts points using learned decision tree ensemble
4. Extract confidence from model's internal uncertainty
5. Model retrained weekly to adapt to NBA changes

**When It Excels:**

- ✅ Complex multi-factor situations (fatigue + matchup + pace + usage)
- ✅ Finding non-obvious interactions between features
- ✅ Adapting to long-term trends (NBA evolution)
- ✅ Large sample sizes (season-long patterns)

**When It Struggles:**

- ❌ Novel situations not in training data
- ❌ Small samples (new players, unusual circumstances)
- ❌ Sudden rule changes or dramatic shifts
- ❌ Explainability (hard to debug why it predicted X)

**Typical Performance:**

- O/U Accuracy: 56-60%
- MAE: 4.2-4.5 points
- Speed: Fast (50-100ms per prediction once model loaded)

**Training:**

- Frequency: Weekly (Sunday 3 AM)
- Training Data: 365 days rolling window
- Duration: 5-10 minutes
- Storage: `gs://nba-props-ml-models/xgboost_v1_YYYYMMDD.json`

### System 5: Meta Ensemble V1

**Type:** Ensemble (Combines Systems 1-4)
**Purpose:** Intelligent weighted combination of all other systems
**Complexity:** High
**Implementation:** Week 4

**Algorithm Overview:**

1. Collect predictions from all 4 base systems
2. Weight by recent 30-day performance of each system
3. Adjust weights by each system's confidence
4. Calculate weighted average prediction
5. High confidence when systems agree, low when they disagree

**When It Excels:**

- ✅ Always - combines strengths of all systems
- ✅ Hedges against individual system failures
- ✅ Highest accuracy in most situations
- ✅ Adaptive weighting responds to which systems are performing best

**When It Struggles:**

- ❌ When all base systems struggle (novel situations)
- ❌ Requires at least 2 base systems to be working
- ❌ Can be conservative (averages out extreme predictions)

**Typical Performance:**

- O/U Accuracy: 58-62% (best overall)
- MAE: 4.0-4.3 points (best overall)
- Speed: Fast (just combines others, <10ms)

**This is your PRIMARY system for betting recommendations**

### Why 5 Systems?

| Reason | Benefit |
|--------|---------|
| **Diversification** | Different strengths in different situations |
| **Redundancy** | If XGBoost fails, rules still work |
| **Learning** | Compare to improve both approaches |
| **Confidence** | Agreement = high confidence, disagreement = pass |
| **Evolution** | Easy to add System 6, 7, etc. later |

---

## ☁️ Why Cloud Run + Pub/Sub {#cloud-run-pubsub}

### Why NOT Flask (Like Phase 2/3/4)?

Phase 2, 3, 4 use Flask because:

- Linear data transformation (JSON → BigQuery)
- Single processor per file/game
- Simple request/response pattern
- No fan-out needed

**Phase 5 is DIFFERENT:**

- Need to predict 450 players × 5 systems = 2,250 predictions
- Requires orchestration (coordinator + workers)
- Need true parallelism (50 workers simultaneously)
- Systems need to combine results
- **Flask isn't designed for this pattern**

### The Cloud Run + Pub/Sub Pattern

**Benefits of This Architecture:**

| Benefit | Value |
|---------|-------|
| ✅ Parallel Processing | 50 workers run simultaneously |
| ✅ Auto-Scaling | Scales up during prediction, down to 0 after |
| ✅ Fault Tolerance | If worker fails, Pub/Sub retries |
| ✅ Decoupling | Coordinator doesn't wait for workers |
| ✅ Cost Effective | Pay only when running |
| ✅ Observable | Each service logs independently |

**Target Performance:**

- **Coordinator:** 1-2 minutes to fan out 450 tasks
- **Workers:** Complete all 2,250 predictions in 3-5 minutes
- **Total:** 6:00 AM start → 6:05 AM complete

### Why Separate Coordinator & Workers?

**Coordinator (Single Instance):**

- Queries today's games (Phase 3)
- Fetches betting lines (Odds API)
- Publishes 450 player tasks to Pub/Sub
- Simple, stateless, runs once per day

**Workers (0-50 Instances):**

- Receive player tasks from Pub/Sub
- Run all 5 prediction systems
- Write predictions to BigQuery
- Scale based on queue depth
- Fault-tolerant via Pub/Sub retries

**Why Separate?**

- Different scaling needs (1 vs 50 instances)
- Different execution patterns (once vs on-demand)
- Different failure modes (coordinator failure blocks all, worker failure affects one player)
- Easier to monitor and debug

---

## 🔀 Why Hybrid Approach {#hybrid-approach}

### The Hybrid Philosophy

**Core Insight:** No single approach is perfect for all situations.

**Rules-Based Systems:**

- Strengths: Explainable, fast, work with limited data
- Weaknesses: Can't discover complex patterns, manual tuning

**ML Systems:**

- Strengths: Find complex patterns, adapt automatically
- Weaknesses: Black box, requires lots of data, can fail on novel situations

**Hybrid Solution:**

- Use rules for explainability and edge case handling
- Use ML for pattern discovery and complex interactions
- Combine outputs for best of both worlds

### Real-World Example

**Player:** LeBron James
**Game:** @ Phoenix Suns
**Line:** 24.5 points

**System Outputs:**

| System | Prediction | Confidence | Reasoning |
|--------|------------|------------|-----------|
| Moving Average | 26.2 | 68 | Recent avg is 26.1, slight boost |
| Zone Matchup | 28.5 | 75 | Paint mismatch strongly favors LeBron |
| Similarity | 24.8 | 62 | Historical games vs PHX average 24.8 |
| XGBoost | 22.1 | 71 | Model sees fatigue + travel factors |
| **Ensemble** | **25.4** | **58** | **Low confidence due to disagreement** |

**Interpretation:**

- Systems disagree significantly (22.1 to 28.5 range)
- Ensemble detects disagreement → assigns low confidence (58)
- **Recommendation: PASS** (don't bet when uncertain)

**This is good!** We avoid bets with high uncertainty.

---

## 🚀 Evolution Strategy {#evolution-strategy}

### Current: v1_baseline_25 (Phase 5 Weeks 1-4)

**Features:** 25 features

- 4 active composite factors (fatigue, zone, pace, usage)
- 4 deferred composite factors (set to 0)

**Systems:** 5 systems

- Week 1: Moving Average + Zone Matchup
- Week 2: + XGBoost
- Week 3: + Similarity
- Week 4: + Meta Ensemble

**Status:** CURRENT IMPLEMENTATION

### Future: v2_enhanced_47 (Phase 5 Week 5+)

**Features:** 47 features (add 22 more)

- Activate 4 deferred factors (referee, look-ahead, matchup history, momentum)
- Add 18 advanced features:
  - Home/away splits
  - Clutch performance
  - Player age curves
  - Team roster strength
  - Playoff implications
  - Advanced shot charts
  - Player combinations
  - Rest advantage

**Systems:** Same 5, but:

- Retrain XGBoost on 47 features
- Update composite factor calculations
- Possibly add System 6 (specialized system)

**Expected Improvements:**

- O/U Accuracy: 58-62% → 60-64%
- MAE: 4.0-4.3 → 3.7-4.0
- Confidence calibration: Better

### Extensibility: Adding System 6

Architecture makes it easy to add new systems:

```python
# Create new predictor class
class DeepLearningV1(BasePredictor):
    def predict(self, features):
        # Load LSTM model
        # Make prediction
        # Return result

# Update Worker to call System 6
predictions = [
    sys1.predict(features),
    sys2.predict(features),
    sys3.predict(features),
    sys4.predict(features),
    sys6.predict(features),  # NEW
    sys5.predict([sys1, sys2, sys3, sys4, sys6])  # Ensemble
]
```

**That's it! No other changes needed.**

### Potential Future Systems

| System | Type | Purpose |
|--------|------|---------|
| **System 6** | Deep Learning (LSTM) | Time series patterns |
| **System 7** | Player-Specific Models | Train separate model per player |
| **System 8** | Lineup Analysis | How player performs with specific teammates |
| **System 9** | Betting Market Analysis | Reverse engineer sharp money |
| **System 10** | Weather/Travel Specialist | Focus on fatigue factors |

The architecture supports unlimited systems, and Ensemble will automatically weight them based on performance.

---

## 🔄 Comparison to Alternatives {#alternatives}

### Alternative 1: Pure ML (Single XGBoost Model)

**Pros:**

- ✅ Simpler implementation
- ✅ Faster (only one prediction)

**Cons:**

- ❌ Single point of failure
- ❌ Black box - hard to debug
- ❌ Can fail catastrophically in novel situations
- ❌ Requires extensive data for every edge case
- ❌ No diversification

**Why We Chose Hybrid:** More robust, explainable, diversified

### Alternative 2: Pure Rules (Only Moving Average)

**Pros:**

- ✅ Completely explainable
- ✅ No training required
- ✅ Fast and simple

**Cons:**

- ❌ Can't discover complex patterns
- ❌ Manual tuning required
- ❌ Doesn't adapt automatically
- ❌ Limited by human intuition

**Why We Chose Hybrid:** Need to discover patterns rules can't capture

### Alternative 3: Flask Monolith (Single Service)

**Pros:**

- ✅ Simpler deployment
- ✅ Fewer moving parts

**Cons:**

- ❌ Can't scale beyond ~10 concurrent predictions
- ❌ Single point of failure
- ❌ Hard to deploy individual systems
- ❌ All systems in one process (coupling)

**Why We Chose Cloud Run:** Need to scale to 450 players, separate concerns

### Alternative 4: Ensemble of 10 ML Models

**Pros:**

- ✅ High accuracy in steady-state
- ✅ Automated (no rule writing)

**Cons:**

- ❌ Training/maintaining 10 models is expensive
- ❌ All have same weaknesses (novel situations)
- ❌ No explainability
- ❌ Computational cost 10x

**Why We Chose Hybrid:** Balance explainability, cost, robustness

---

## ⚖️ Key Architectural Principles {#principles}

### Design Philosophy

| Principle | Rationale |
|-----------|-----------|
| **Hybrid > Pure** | Combining rules + ML > either alone |
| **Diversification > Optimization** | 5 good systems > 1 perfect system (which doesn't exist) |
| **Redundancy > Efficiency** | Worth running extra systems for fault tolerance |
| **Separation of Concerns** | Each Cloud Run service has one job |
| **Observable > Opaque** | Can see what each system predicts and why |
| **Evolvable > Static** | Easy to add System 6, 7, etc. without rewriting everything |
| **Cloud Run > Flask** | For orchestration when you need fan-out and parallelism |
| **Confidence Matters** | Disagreement between systems = useful signal = PASS |

### Guiding Questions for Future Decisions

When considering changes to Phase 5 architecture, ask:

1. **Does it improve diversification?** (More system diversity = more robust)
2. **Does it maintain explainability?** (Can we understand why it predicted X?)
3. **Does it support evolution?** (Can we add features/systems easily?)
4. **Does it scale efficiently?** (Cost-effective at 450 players/day?)
5. **Does it preserve redundancy?** (What happens if one system fails?)

---

## 🔗 Related Documentation {#related-docs}

**Phase 5 Operations:**

- **Deployment Guide:** `../operations/01-deployment-guide.md` - How to deploy the architecture
- **Worker Deep-Dive:** `../operations/04-worker-deepdive.md` - Implementation details
- **Parallelization Strategy:** `../architecture/01-parallelization-strategy.md` - Scaling decisions

**Phase 5 Algorithms:**

- **Composite Factors:** `../algorithms/01-composite-factor-calculations.md` - Rule-based calculations
- **Confidence Scoring:** `../algorithms/02-confidence-scoring-framework.md` - How confidence works

**Phase 5 ML:**

- **Model Training:** `../ml-training/01-initial-model-training.md` - How XGBoost is trained
- **Continuous Retraining:** `../ml-training/02-continuous-retraining.md` - Model lifecycle

**Architecture Context:**

- **Processor Cards:** `docs/processor-cards/phase5-prediction-coordinator.md` - System overview
- **Event-Driven Pipeline:** `docs/architecture/04-event-driven-pipeline-architecture.md` - Overall pipeline design

---

**Last Updated:** 2025-11-16
**Next Steps:** Review deployment guide to understand how these decisions translate to infrastructure
**Status:** ✅ Current

---

## Quick Reference

**Design Decisions Summary:**

| What | Why |
|------|-----|
| 5 Systems | Diversification + redundancy |
| Hybrid (Rules + ML) | Explainability + pattern discovery |
| Cloud Run + Pub/Sub | Scalability + fault tolerance |
| Ensemble as Primary | Combines strengths of all systems |
| Confidence Scoring | Avoid uncertain bets |
| Extensible Architecture | Easy to add System 6, 7, etc. |

**When in doubt:** Favor diversification, explainability, and redundancy over pure optimization.
