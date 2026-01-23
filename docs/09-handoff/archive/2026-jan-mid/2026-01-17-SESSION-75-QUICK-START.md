# Session 75 Quick Start - CatBoost V8 Crisis
**Date**: 2026-01-17
**Priority**: 🚨 P0 CRITICAL
**Read Full Handoff**: 2026-01-17-SESSION-75-CATBOOST-INVESTIGATION-HANDOFF.md

---

## THE CRISIS (30 Second Version)

CatBoost V8 broken since Jan 8, 2026:
- **Zero premium picks (≥92% confidence) for 8 days**
- **Confidence stuck at 89%, 84%, 50% only**
- **89% picks = 41.4% win rate (losing money)**
- **Root cause**: Jan 7 commit broke feature_quality_score

---

## WHAT YOU NEED TO DO

**USE AGENTS** to investigate and fix. Do NOT attempt manual review.

### 5 Agent Tasks (Run in Order)

1. **Review Jan 7 Commit** (general-purpose agent)
   - Command: `git show 0d7af04c0c1e1bf6cfc5a6326cac589ccaa277dd`
   - File: player_aggregations.py (274 lines changed)
   - Question: What broke feature_quality_score?

2. **Trace Feature Pipeline** (Explore agent, very thorough)
   - Start: predictions/worker/prediction_systems/catboost_v8.py
   - Question: How is feature_quality_score calculated?

3. **Query BigQuery** (general-purpose agent)
   - Table: ml_nba.ml_feature_store_v2
   - Question: Compare quality Dec vs Jan, what degraded?

4. **Find Related Changes** (Explore agent, medium)
   - Date: Jan 5-10, 2026
   - Question: What else changed in analytics?

5. **Propose Fix** (general-purpose agent)
   - Based on: Tasks 1-4
   - Question: Revert commit or targeted fix?

---

## THE PROBLEM EXPLAINED

### Confidence Formula
```python
# When features are broken (quality 80-89):
base = 82
consistency_bonus = 7
quality_bonus = 0  # No bonus because quality < 90

confidence = 82 + 7 + 0 = 89%  # Stuck here!
```

### Timeline
- **Dec 20 - Jan 7**: Healthy (quality 90+, premium picks daily)
- **Jan 7, 1:19 PM**: Commit 0d7af04c deployed
- **Jan 8+**: Broken (quality 80-89, zero premium picks)

---

## SUCCESS CRITERIA

System is fixed when:
- ✅ Premium picks (≥92%) appearing daily (10-50 per day)
- ✅ Confidence continuous (not just 3 values)
- ✅ Feature quality ≥90 (not 80-89)
- ✅ 3+ days of healthy data

---

## VALIDATION QUERIES (After Fix)

```sql
-- Check confidence distribution
SELECT ROUND(confidence_score, 2) as conf, COUNT(*) as picks
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'catboost_v8' AND game_date >= CURRENT_DATE() - 3
  AND line_value != 20.0
GROUP BY 1 ORDER BY 1 DESC;
-- Expected: Many values, not just 0.89, 0.84, 0.50

-- Check feature quality
SELECT game_date, AVG(feature_quality_score) as avg_quality
FROM `nba-props-platform.ml_nba.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date ORDER BY game_date DESC;
-- Expected: avg_quality >= 90

-- Check premium picks
SELECT game_date,
  COUNT(CASE WHEN confidence_score >= 0.92 THEN 1 END) as premium_picks
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'catboost_v8' AND game_date >= CURRENT_DATE() - 7
  AND line_value != 20.0
GROUP BY game_date ORDER BY game_date DESC;
-- Expected: premium_picks > 0 every day
```

---

## BLOCKED WORK

DO NOT proceed until fixed:
- ❌ Filtering strategies
- ❌ Subset system implementation
- ❌ Historical data backfill
- ❌ Any confidence-based analysis

---

## REFERENCE DOCUMENTS

**Full Handoff**: 2026-01-17-SESSION-75-CATBOOST-INVESTIGATION-HANDOFF.md
**Investigation Report**: CATBOOST_V8_SYSTEM_INVESTIGATION_REPORT.md
**Online Chat Summary**: ../../INVESTIGATION_RESULTS_FOR_ONLINE_CHAT.txt

---

## ACTION PLAN

1. **Read full handoff** (10 minutes)
2. **Launch agent investigations** (2-3 hours)
3. **Implement fix** (1-2 hours)
4. **Validate fix** (30 minutes next day)
5. **Monitor 3 days** (15 min daily)
6. **Resume other work** (after healthy)

---

**END OF QUICK START - READ FULL HANDOFF FOR DETAILS**
