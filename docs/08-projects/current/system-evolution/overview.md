# System Evolution: Adaptive Learning Framework

**Status:** Planning
**Created:** 2025-12-11
**Priority:** High (post-backfill)

---

## Vision

Build a prediction system that **learns which approaches work best in different contexts** and automatically adapts.

Instead of one static ensemble, the system will:
- Know that `similarity_balanced` excels early season (limited data)
- Know that `xgboost` shines mid-season (enough training data)
- Know that `zone_matchup` is best for role players with defined roles
- Know that fatigue adjustments matter more for older players
- Continuously discover new patterns and adapt

---

## Core Insight

**Not all prediction systems work equally well in all situations.**

| Context | Best System (Hypothesis) | Why |
|---------|-------------------------|-----|
| Early season (games 1-20) | similarity_balanced | Historical patterns matter more than limited current data |
| Mid-season (games 40-60) | xgboost | Enough data to train, patterns established |
| Late season (games 70+) | zone_matchup | Teams tank, matchups become key |
| Role players | moving_average | Consistent, defined minutes |
| Stars | xgboost | Complex usage patterns need ML |
| Young players (<25) | similarity_balanced | Match to similar developmental arcs |
| Veterans (>32) | Needs fatigue weighting | Load management, back-to-backs matter |
| Back-to-back games | Needs fatigue adjustment | Rest matters |
| Home games | May need bias correction | Home court advantage varies |

**Goal:** Discover these patterns from data and codify them into an adaptive system.

---

## What We're Building

### Phase 1: Discovery (Analysis)
Analyze 4 seasons of backfill data to discover:
- Which system wins in which context?
- Are patterns consistent across seasons?
- What are the biggest performance gaps?

### Phase 2: Context-Aware Weights
Replace static ensemble weights with dynamic weights:
```python
# Current: Static
weights = {'xgboost': 0.25, 'similarity': 0.25, 'zone': 0.25, 'moving_avg': 0.25}

# Future: Context-aware
weights = get_optimal_weights(
    season_game_number=45,
    player_age=28,
    player_tier='STARTER',
    is_back_to_back=True,
    is_home=False
)
```

### Phase 3: Automated Learning
System continuously updates its understanding:
- Weekly analysis of recent performance
- Automatic weight adjustments
- Alerts when patterns shift

---

## Documents

| Document | Purpose |
|----------|---------|
| **START-HERE.md** | Post-backfill action plan - read this first! |
| **DESIGN.md** | Technical architecture for adaptive ensemble |
| **CONTEXT-DIMENSIONS.md** | All dimensions to analyze (season, player type, age, etc.) |
| **ANALYSIS-QUERIES.md** | SQL queries to discover patterns |
| **IMPLEMENTATION-PLAN.md** | Phased implementation approach |
| **ADDITIONAL-ANGLES.md** | Deep-dive analyses: error patterns, calibration, meta-learning |
| **QUICK-WINS.md** | Highest ROI improvements to implement first |
| **EXPERIMENT-WITHOUT-BACKFILL.md** | How to test ensemble combinations on existing data |
| **PLAYER-INVESTIGATION-TEMPLATE.md** | Deep-dive template for single-player analysis |

---

## Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Overall MAE | ~4.7 | < 4.5 | Across all predictions |
| Early season MAE | TBD | < 5.5 | Games 1-20 of season |
| Veteran accuracy | TBD | Improve 5% | Players age 32+ |
| Back-to-back accuracy | TBD | Improve 5% | B2B game predictions |
| Context-aware improvement | 0% | > 3% | vs static ensemble |

---

## Dependencies

- **Four-season backfill complete** - Need historical data to analyze
- **Grading complete** - Need `prediction_accuracy` populated
- **Tier adjustments working** - Foundation for context-aware adjustments

---

## Key Questions to Answer

1. **Is there signal?** Do systems actually perform differently by context, or is it noise?
2. **Is it consistent?** Do patterns hold across multiple seasons?
3. **Is it actionable?** Can we improve MAE by > 0.1 with context-aware weights?
4. **Is it stable?** Do optimal weights change dramatically season-to-season?

---

## Related Projects

- `four-season-backfill/` - Prerequisite: need historical data
- `phase-5c-ml-feedback/` - Foundation: tier adjustments pattern
