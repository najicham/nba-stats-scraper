# ULTRATHINK: Model Improvement Execution Plan

**Date**: January 9, 2026
**Objective**: Systematically explore all improvement opportunities to push MAE from 4.14 toward 3.50
**Approach**: Prioritized execution with validation gates

---

## STRATEGIC ANALYSIS

### Current Position
- **XGBoost v6**: 4.14 MAE (13.6% better than mock's 4.80)
- **Known issues**: DNPs (~800 large errors), high-scorer variance, regression to mean
- **Ceiling estimate**: ~3.50 MAE with perfect data (based on inherent game variance)

### Key Insight: Compound Improvements
Each improvement builds on the previous. Order matters:
1. **Understand errors first** → Know where to focus
2. **Quick wins second** → Build momentum, validate approach
3. **Feature engineering third** → Improve signal
4. **New data last** → Highest effort, highest potential

### Dependency Graph
```
Error Analysis ─────┬──→ Ensemble v6+mock ──→ Best ensemble
                    │
                    ├──→ DNP Quantification ──→ Injury Integration
                    │
                    └──→ Player Type Analysis ──→ Position Models
                                              └──→ Minutes Model
```

---

## EXECUTION PLAN

### BLOCK 1: Rapid Error Analysis (45 min total)
**Goal**: Understand where errors come from before trying to fix them

| Step | Analysis | Output | Time |
|------|----------|--------|------|
| 1.1 | DNP impact on MAE | MAE without DNPs | 10 min |
| 1.2 | Error by position | Position-specific MAE | 10 min |
| 1.3 | Error by usage tier | Usage-specific patterns | 10 min |
| 1.4 | Error by minutes bucket | Minutes-specific patterns | 10 min |
| 1.5 | Synthesize findings | Priority matrix | 5 min |

### BLOCK 2: Quick Win Experiments (1 hour total)
**Goal**: Find easy improvements with minimal effort

| Step | Experiment | Hypothesis | Time |
|------|------------|------------|------|
| 2.1 | Ensemble v6 + mock | Combine strengths | 20 min |
| 2.2 | Ensemble weight optimization | Find optimal α | 20 min |
| 2.3 | Segment-specific ensemble | Different α by segment | 20 min |

### BLOCK 3: Feature Engineering (2 hours total)
**Goal**: Add new predictive signals from existing data

| Step | Feature | Rationale | Time |
|------|---------|-----------|------|
| 3.1 | Minutes volatility | Stable minutes = predictable | 30 min |
| 3.2 | Usage trend | Rising/falling role | 30 min |
| 3.3 | Opponent matchup quality | Defense matters | 30 min |
| 3.4 | Retrain v7 with new features | Test impact | 30 min |

### BLOCK 4: Model Architecture (2 hours total)
**Goal**: Try different modeling approaches

| Step | Approach | Expected Benefit | Time |
|------|----------|------------------|------|
| 4.1 | Two-stage (minutes → points) | Separate concerns | 45 min |
| 4.2 | Position-specific models | Position patterns | 45 min |
| 4.3 | Best architecture selection | Compare all | 30 min |

### BLOCK 5: Synthesis & Documentation (30 min)
**Goal**: Combine learnings into production-ready model

| Step | Task | Output |
|------|------|--------|
| 5.1 | Select best configuration | Final model spec |
| 5.2 | Validate on holdout | Confirmed MAE |
| 5.3 | Document findings | Handoff doc |

---

## EXECUTION SCRIPT

### Block 1: Error Analysis Script
```python
# Run all error analyses in one script
# Outputs: error_analysis_report.json
```

### Block 2: Ensemble Experiments
```python
# Test v6 + mock ensembles
# Outputs: best_ensemble_config.json
```

### Block 3: Feature Engineering
```python
# Add features, retrain, evaluate
# Outputs: v7_model.json
```

### Block 4: Architecture Experiments
```python
# Test two-stage, position models
# Outputs: architecture_comparison.json
```

---

## SUCCESS CRITERIA

| Block | Success Metric | Go/No-Go |
|-------|----------------|----------|
| Block 1 | Clear error patterns identified | Document findings |
| Block 2 | Ensemble MAE < 4.10 | Use if better |
| Block 3 | v7 MAE < best ensemble | Use if better |
| Block 4 | Architecture MAE < v7 | Use if better |

### Cumulative Target

| After Block | Target MAE | Improvement vs Mock |
|-------------|------------|---------------------|
| Block 1 | 4.14 (baseline) | 13.6% |
| Block 2 | 4.05 | 15.6% |
| Block 3 | 3.95 | 17.7% |
| Block 4 | 3.85 | 19.8% |

---

## LET'S EXECUTE

Starting with Block 1: Rapid Error Analysis
