# Handoff: Validation Framework Development - January 25, 2026

**Created:** 2026-01-25 ~9:30 PM PST
**Session Focus:** Building comprehensive validation to catch daily orchestration failures
**Priority:** P0 - Pipeline reliability

---

## TL;DR

The NBA pipeline fails silently almost every day. We built a new validation framework with 25 validation angles to catch issues. **Key finding:** A data bug caused 98% of predictions to be skipped during grading. Fixed.

---

## Context: Why This Matters

### The Problem
1. **Pipeline fails daily** - Orchestration issues, data gaps, silent failures
2. **Existing validation misses issues** - Only checks record counts, not quality
3. **Issues compound** - One failure cascades (no boxscores → no analytics → no predictions → no grading)

### Recent Outage (Jan 23-25)
- **45-hour master controller outage** due to Firestore permission error
- **Zero** workflow decisions made during this window
- **Feature quality dropped** from 75 to 64 (rolling windows became stale)
- **Prediction coverage dropped** to 30% of normal
- **Grading was 5%** (only 4 of 85 predictions graded)

---

## What We Built This Session

### 1. Comprehensive Health Check Script

**Location:** `bin/validation/comprehensive_health_check.py`

Validates 9 dimensions (not just counts!):
- Workflow decision gaps
- Feature quality scores
- Prediction funnel drop-off
- Rolling window completeness
- Grading lag
- Cross-phase consistency
- Props coverage
- Schedule freshness
- Prop line data consistency

**Usage:**
```bash
python bin/validation/comprehensive_health_check.py --date 2026-01-23
python bin/validation/comprehensive_health_check.py --alert  # Send Slack alerts
```

### 2. Validation Framework Documentation

**Location:** `docs/08-projects/current/validation-framework/`

| Document | Purpose |
|----------|---------|
| `README.md` | Project overview |
| `VALIDATION-ANGLES.md` | 25 validation angles with SQL queries |
| `ROOT-CAUSE-ANALYSIS.md` | Deep dive on Jan 23-25 failures |
| `CURRENT-FINDINGS.md` | Investigation results |
| `ISSUES-TO-FIX.md` | Prioritized bug list |
| `BACKFILL-PLAN.md` | Recovery steps |

### 3. Grading Processor Fix

**File Changed:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

**Bug:** Grading filtered on `has_prop_line = TRUE`, but `has_prop_line` field has data bugs
**Fix:** Use `line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')` instead
**Impact:** Jan 23 grading went from 21 → 1,294 predictions

---

## Key Findings

### Finding 1: 45-Hour Workflow Gap

```sql
-- This query found the outage
SELECT MAX(gap_minutes) as longest_gap
FROM (
  SELECT TIMESTAMP_DIFF(decision_time, LAG(decision_time) OVER (ORDER BY decision_time), MINUTE) as gap_minutes
  FROM nba_orchestration.workflow_decisions
  WHERE decision_time >= '2026-01-20'
)
-- Result: 2,714 minutes (45.2 hours)
```

**Lesson:** Need automated alert when decisions stop.

### Finding 2: has_prop_line Data Bug

```sql
-- 98% of ACTUAL_PROP predictions have wrong has_prop_line flag
SELECT line_source, has_prop_line, COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-23' AND system_id = 'catboost_v8'
GROUP BY 1, 2
-- Result: 218 with has_prop_line=false but line_source='ACTUAL_PROP' (BUG)
```

**Lesson:** Don't trust derived flags - use authoritative source (line_source).

### Finding 3: Feature Quality Degradation

| Date | Avg Quality | Low Quality % |
|------|-------------|---------------|
| Jan 22 | 75.49 | 8.8% |
| Jan 23 | 69.07 | 23.1% |
| Jan 24 | 64.43 | 74.6% |

**Lesson:** Rolling window calculations degrade when pipeline stops.

### Finding 4: Props Coverage is 33-62%

Not a bug - intentional filtering:
- Players with props but low features → filtered (OK)
- Players with props and good features but no prediction → **BUG (9 players)**

---

## Validation Philosophy

### Count-Based Validation is Insufficient

**Old approach:** `COUNT(*) > 0` → "Data exists, we're good"
**Problem:** Data can exist but be degraded, wrong, or incomplete

**New approach:** Check QUALITY metrics:
- Feature quality scores > 70
- Rolling window completeness > 80%
- Prediction funnel conversion rates
- Cross-phase consistency

### Multiple Angles Catch Different Issues

| Angle | Catches |
|-------|---------|
| End-to-end flow | Missing phase data |
| Feature quality | Stale/degraded features |
| Prediction funnel | Filtering issues |
| Workflow decisions | Controller outages |
| Props coverage | Missed betting opportunities |
| Grading lag | Stalled grading pipeline |

### Discrepancies Reveal Bugs

When two angles disagree, there's a bug:
- `line_source='ACTUAL_PROP'` but `has_prop_line=false` → Data bug
- `boxscores=8 games` but `analytics=0 games` → Phase 3 failed
- `predictions=100` but `graded=4` → Grading filter issue

---

## How to Run Validation

### Morning Check (Daily)
```bash
# Yesterday's data
python bin/validation/comprehensive_health_check.py

# Last 7 days completeness
python bin/validation/daily_data_completeness.py --days 7

# Multi-angle cross-validation
python bin/validation/multi_angle_validator.py --days 7
```

### After Outage Recovery
```bash
# Check specific dates
python bin/validation/comprehensive_health_check.py --date 2026-01-23
python bin/validation/multi_angle_validator.py --start-date 2026-01-20 --end-date 2026-01-25
```

### Investigation Queries
See `docs/08-projects/current/validation-framework/VALIDATION-ANGLES.md` for 25 SQL queries.

---

## What to Study for More Validation Angles

### Key Tables to Understand

| Table | Purpose |
|-------|---------|
| `nba_orchestration.workflow_decisions` | Controller decisions |
| `nba_orchestration.pipeline_event_log` | Processor start/complete events |
| `nba_orchestration.processor_completions` | Phase 2 completions |
| `nba_predictions.ml_feature_store_v2` | Feature quality scores |
| `nba_analytics.upcoming_team_game_context` | Rolling window completeness |
| `nba_predictions.player_prop_predictions` | Predictions with line source |
| `nba_predictions.prediction_accuracy` | Grading results |

### Key Metrics to Monitor

| Metric | Normal Range | Alert If |
|--------|--------------|----------|
| Feature quality avg | 70-80 | < 65 |
| Rolling window L7D | 80-100% | < 70% |
| Workflow decision gap | < 60 min | > 120 min |
| Grading coverage | > 90% | < 50% |
| Props coverage | 70-90% | < 50% |

### Ways to Find New Angles

1. **Follow the data flow:** Phase 1 → 2 → 3 → 4 → 5 → 6, check each transition
2. **Compare related metrics:** If A should equal B, validate they match
3. **Check timing:** Did things happen in expected order/windows?
4. **Check distributions:** Are values in expected ranges?
5. **Check consistency:** Do different sources agree?

---

## Remaining Work

### Immediate (Today/Tomorrow)
- [ ] Run grading backfill for Jan 15-24 (fix already applied)
- [ ] Wait for Jan 24 games to complete
- [ ] Regenerate Phase 3/4 for Jan 23-24

### This Week
- [ ] Add workflow decision gap to Cloud Monitoring alerts
- [ ] Investigate the 9 players with good features but no predictions
- [ ] Fix has_prop_line data bug in prediction generator (line 390 of player_loader.py)

### Validation Improvements
- [ ] Create more angles (see list of 25 in VALIDATION-ANGLES.md)
- [ ] Add automated hourly validation
- [ ] Build dashboard for validation metrics

---

## Files Changed This Session

| File | Change |
|------|--------|
| `bin/validation/comprehensive_health_check.py` | NEW - 9-check health validator |
| `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` | Fixed has_prop_line filter |
| `docs/08-projects/current/validation-framework/*` | NEW - 6 documentation files |

---

## Quick Commands Reference

```bash
# Health check
python bin/validation/comprehensive_health_check.py --date 2026-01-23

# Grading backfill
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-15 --end-date 2026-01-24

# Workflow decision gaps
bq query "
SELECT MAX(gap_minutes) FROM (
  SELECT TIMESTAMP_DIFF(decision_time, LAG(decision_time) OVER (ORDER BY decision_time), MINUTE) as gap_minutes
  FROM nba_orchestration.workflow_decisions WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
)"

# Feature quality
bq query "
SELECT game_date, ROUND(AVG(feature_quality_score), 1) as avg_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1 ORDER BY 1"
```

---

## Key Insight for Next Session

**The goal is to make failures LOUD, not silent.**

Every day, something breaks. The question is: did we notice?

With solid validation:
- Failures get detected within hours, not days
- Root causes are identifiable from the data
- Recovery is targeted and efficient

Without validation:
- Issues compound silently
- We discover problems days later
- Debugging is painful and time-consuming

**Keep adding validation angles. Each new angle catches different failures.**

---

**End of Handoff Document**
