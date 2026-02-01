# Session 70 Design Review - Dynamic Subset System

**Reviewer**: Session 70 (Opus)
**Date**: February 1, 2026
**Status**: REVIEWED - Ready for Implementation Planning

---

## Executive Summary

The dynamic subset system design is **well-architected and ready for implementation**. The pct_over signal has strong statistical backing (p=0.0065), and the layered architecture is clean and extensible.

**Recommendation**: Proceed with implementation in a Sonnet session, starting with signal infrastructure.

---

## Design Strengths

### 1. Statistically Validated Signal

| Metric | Value | Assessment |
|--------|-------|------------|
| P-value | 0.0065 | Strong (p < 0.01) |
| Hit rate difference | 28 points (82% vs 54%) | Substantial |
| Sample size | 87 high-edge picks over 23 days | Adequate for initial validation |

This isn't random noise - there's a real pattern here.

### 2. Composite Scoring Formula

```
composite_score = (edge * 10) + (confidence * 0.5)
```

**Why this works**:
- A 1-point edge difference = 10 score points
- A 20% confidence difference = 10 score points
- Edge correctly dominates (it's the primary value driver)
- Confidence serves as tiebreaker

**Example validation**:
| Player | Edge | Conf | Score | Rank |
|--------|------|------|-------|------|
| A | 7.2 | 87% | 115.5 | 1 |
| B | 6.5 | 91% | 110.5 | 2 |
| C | 5.8 | 92% | 104.0 | 3 |

Player A with higher edge beats Player C with higher confidence. Correct behavior.

### 3. Layered Architecture

```
Layer 1: Base predictions (foundation)
    ↓
Layer 2A: Static filters (existing - edge, confidence thresholds)
    ↓
Layer 2B: Dynamic signals (NEW - pct_over, volume, daily_signal)
    ↓
Layer 3: Dynamic subsets (combining static + dynamic)
    ↓
Layer 3B: Pick ranking (composite score, top-N selection)
    ↓
Layer 4: Presentation (skills, dashboard)
```

This is clean, testable, and extensible. Each layer has a single responsibility.

### 4. A/B Testing Strategy

Tracking all subset variations simultaneously is the right approach:
- `v9_high_edge_top3` vs `top5` vs `top10` vs `all`
- `balanced` vs `any` vs `warning`
- Signal + ranking vs ranking only

After 2-4 weeks, data will reveal the optimal combination rather than guessing.

### 5. Comprehensive SQL Queries

The design doc includes production-ready SQL for:
- Daily signal calculation
- Ranked pick selection
- Historical performance comparison
- Subset membership evaluation

This accelerates implementation significantly.

---

## Areas for Consideration

### 1. Sample Size Monitoring

**Current state**: 23 days, 87 high-edge picks
**Recommendation**: Continue validation for 30-60 more days

| Milestone | Action |
|-----------|--------|
| Day 30 | Re-run z-test, confirm p < 0.05 |
| Day 60 | Consider threshold adjustments if needed |
| Monthly | Recalculate statistical significance |

Add to `validation-tracker.md` and check weekly.

### 2. Threshold Sensitivity

Current thresholds:
- UNDER_HEAVY: pct_over < 25%
- BALANCED: pct_over 25-40%
- OVER_HEAVY: pct_over > 40%

**Consideration**: These are based on visual inspection of the data. Could be refined with:
- ROC curve analysis to find optimal cutoffs
- More data points (especially for OVER_HEAVY, which has only 1 day)

**Recommendation**: Keep current thresholds for now, revisit after 30 days.

### 3. Fallback Behavior Decision

The design doc lists three options for RED signal days:
- Option A: Hide picks entirely
- Option B: Show with prominent warning
- Option C: Show reduced list (highest edge only)

**My recommendation: Option B** (show with warning)

Reasons:
1. Users can still track RED day performance (validates the signal)
2. Transparency builds trust
3. Some users may want to bet anyway (their choice)
4. Hiding data feels paternalistic

### 4. Future Enhancements (Not for v1)

These could improve the system later but aren't needed for initial launch:

| Enhancement | Benefit | Complexity |
|-------------|---------|------------|
| Line movement signal | Catch sharp money | Medium |
| Back-to-back game factor | Context awareness | Low |
| Per-game signals (vs per-day) | More granular | High |
| Multi-model consensus signal | V8+V9 agreement | Medium |

Defer these until v1 is validated.

---

## Implementation Recommendations

### Phase 1: Signal Infrastructure (Priority: CRITICAL)

**Deliverables**:
1. Create `daily_prediction_signals` table
2. Implement signal calculation query
3. Backfill Jan 9 - Feb 1 historical signals
4. Add to prediction workflow (calculate after predictions)

**Estimated effort**: 2-3 hours for Sonnet

**Success criteria**:
- Table exists and is populated
- Historical data matches manual analysis
- Today's signal matches expected value

### Phase 2: Quick Win - Add Warning to Existing Skill

Before building new skills, add pct_over check to `/validate-daily` or `/top-picks`:

```sql
-- Add to existing skill output
SELECT
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
  CASE
    WHEN ... < 25 THEN '⚠️ UNDER_HEAVY - Historical 54% HR'
    ELSE '✅ BALANCED - Historical 82% HR'
  END as signal_warning
FROM predictions
WHERE game_date = CURRENT_DATE()
```

**Estimated effort**: 30 minutes
**Immediate value**: Users see warning today

### Phase 3: Dynamic Subset Tables

**Deliverables**:
1. Create `dynamic_subset_definitions` table
2. Insert 5 initial subset definitions
3. Create view joining predictions + signals + definitions

**Estimated effort**: 1-2 hours

### Phase 4: New Skills

**Deliverables**:
1. `/subset-picks` - Query picks from any subset with signal context
2. `/subset-performance` - Compare subset performance over time

**Estimated effort**: 3-4 hours total

### Phase 5: Integration & Monitoring

**Deliverables**:
1. Dashboard signal indicator
2. Slack alert for RED days (optional)
3. Daily validation tracking

**Estimated effort**: 2-3 hours

---

## Sonnet Session Handoff Recommendation

### Should We Create a Master Plan for Sonnet?

**Yes** - This is well-suited for a Sonnet implementation session:

1. **Clear scope**: Tables, queries, and skills are well-defined
2. **Production-ready SQL**: Design doc includes copy-paste queries
3. **Low ambiguity**: Architecture decisions are made
4. **Testable deliverables**: Each phase has clear success criteria

### Suggested Sonnet Session Structure

**Session Goal**: Implement Phase 1 + Phase 2 (Quick Win)

**Prompt outline**:
```
1. Read the design documents:
   - DYNAMIC-SUBSET-DESIGN.md
   - SESSION-70-MASTER-PLAN.md
   - SESSION-70-DESIGN-REVIEW.md (this doc)

2. Create daily_prediction_signals table in BigQuery

3. Backfill historical signals (Jan 9 - Feb 1)

4. Add pct_over warning to /validate-daily skill

5. Verify with today's data (expect RED signal, ~10% pct_over)

6. Commit changes
```

**Expected duration**: 1-2 hours

---

## Today's Validation Opportunity

Feb 1 has pct_over = 9% (extreme RED signal). After tonight's games complete:

1. Calculate actual high-edge hit rate for Feb 1
2. If hit rate < 55%: Signal correctly predicted poor performance
3. If hit rate > 70%: Signal may need recalibration
4. Update `validation-tracker.md` with results

This is a natural experiment - the model is predicting a bad day.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Signal stops working | Low | High | Ongoing validation, threshold tuning |
| Sample size too small | Medium | Medium | Continue tracking, wait for 60 days |
| Over-reliance on signal | Medium | Medium | Keep `_any` subsets as control |
| Implementation complexity | Low | Low | Use provided SQL, incremental rollout |

---

## Conclusion

The dynamic subset system is well-designed and ready for implementation. The statistical backing is solid, the architecture is clean, and the implementation path is clear.

**Next step**: Create a Sonnet handoff prompt for Phase 1 + Quick Win implementation.

---

*Reviewed by: Claude Opus 4.5*
*Session: 70*
*Date: February 1, 2026*
