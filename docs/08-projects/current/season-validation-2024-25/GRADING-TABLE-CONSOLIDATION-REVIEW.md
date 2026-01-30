# Grading Table Consolidation Review

**Created:** 2026-01-29
**For Review By:** CatBoost/ML Chat
**Priority:** P2 - Data Architecture Issue
**Status:** ✅ RESOLVED - Consolidated to prediction_accuracy

## Resolution (2026-01-29)

Per CatBoost chat recommendation, implemented Option 1 (Consolidate to `prediction_accuracy`):

1. ✅ Updated 5 views to use `prediction_accuracy`:
   - `confidence_calibration.sql`
   - `player_insights_summary.sql`
   - `player_prediction_performance.sql`
   - `prediction_accuracy_summary.sql`
   - `roi_simulation.sql`

2. ✅ Added deprecation notice to `prediction_grades.sql`

3. ✅ Updated `CLAUDE.md` with grading table guidance

**Next step:** Deploy the updated views to BigQuery.

---

## Summary

During historical validation of the 2024-25 season, we discovered **two separate grading tables** that appear to serve similar purposes but have different data:

| Table | Records | Date Range | Written By |
|-------|---------|------------|------------|
| `prediction_accuracy` | 419,176 | Nov 2021 - Jan 2026 | Python processor |
| `prediction_grades` | 9,238 | Jan 2026 only | Scheduled SQL query |

**Impact:** Views and validation may be using incomplete data if they reference `prediction_grades` instead of `prediction_accuracy`.

---

## Discovery Context

While validating 2024-25 season grading coverage:

1. Initial query on `prediction_grades` showed only Jan 2026 data
2. Concluded "grading not working for 2024-25" - **incorrect**
3. Later found `prediction_accuracy` has full historical grading
4. Realized there are two parallel systems

---

## Table Comparison

### `prediction_accuracy` (Primary - Full History)

**Schema:** `schemas/bigquery/nba_predictions/prediction_accuracy.sql`

**Written by:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

**Key characteristics:**
- 419,176 total records
- Data from Nov 2021 to present
- Used by downstream processors:
  - `performance_summary_processor.py`
  - `system_daily_performance_processor.py`
  - `system_performance_tracker.py`
- 35 columns including team context, confidence deciles, injury voiding

**Sample data (2024-25 season):**
```
Actionable picks (OVER/UNDER): 36,102
Graded (TRUE/FALSE): 35,987
catboost_v8 accuracy: 74.3%
```

### `prediction_grades` (Secondary - Recent Only)

**Schema:** `schemas/bigquery/nba_predictions/prediction_grades.sql`

**Written by:** Scheduled SQL queries:
- `grade_predictions_query.sql`
- `grade_predictions_query_v2.sql`
- `SCHEDULED_QUERY_READY.sql`

**Key characteristics:**
- 9,238 total records
- Data from Jan 1, 2026 to Jan 16, 2026 only
- Used by views:
  - `confidence_calibration.sql`
  - `player_insights_summary.sql`
  - `player_prediction_performance.sql`
  - `prediction_accuracy_summary.sql`
  - `roi_simulation.sql`
- 25 columns, slightly different structure (has `prediction_id` FK)

---

## Questions That Need Answers

### 1. What is the intended purpose of each table?

- Is `prediction_grades` meant to replace `prediction_accuracy`?
- Or are they for different use cases (real-time vs batch)?
- Why was a scheduled SQL query approach added?

### 2. Why does `prediction_grades` only have Jan 2026 data?

- Was the scheduled query just recently set up?
- Was there a backfill planned that didn't happen?
- Is it intentionally only for "live" grading?

### 3. Which table should be the source of truth?

- For ML training: `prediction_accuracy` has the history
- For views/dashboards: Currently using `prediction_grades` (incomplete)
- For validation: We discovered `prediction_accuracy` is correct

### 4. Should the views be updated?

Current views using `prediction_grades`:
```
schemas/bigquery/nba_predictions/views/
├── confidence_calibration.sql      → Uses prediction_grades
├── player_insights_summary.sql     → Uses prediction_grades
├── player_prediction_performance.sql → Uses prediction_grades
├── prediction_accuracy_summary.sql → Uses prediction_grades
├── roi_simulation.sql              → Uses prediction_grades
└── roi_summary.sql                 → Unknown
```

These views only show Jan 2026 data because that's all `prediction_grades` has.

---

## Schema Differences

### Fields in `prediction_accuracy` but NOT in `prediction_grades`:
- `team_abbr`, `opponent_team_abbr` (team context)
- `confidence_decile` (for calibration curves)
- `referee_adjustment`, `pace_adjustment`, `similarity_sample_size` (feature inputs)
- `predicted_margin`, `actual_margin` (betting evaluation)
- `within_3_points`, `within_5_points` (threshold accuracy)
- `pre_game_injury_flag`, `pre_game_injury_status`, `injury_confirmed_postgame` (injury tracking)

### Fields in `prediction_grades` but NOT in `prediction_accuracy`:
- `prediction_id` (FK to player_prop_predictions)
- `actual_vs_line` (OVER/UNDER/PUSH string)
- `margin_of_error` (deprecated, use absolute_error)
- `has_issues`, `issues` (quality flags)
- `player_dnp` (deprecated, use is_voided)

---

## Grading Logic Comparison

Both tables use similar grading logic:

```python
# OVER correct when: actual > line AND recommendation == 'OVER'
# UNDER correct when: actual < line AND recommendation == 'UNDER'
# Push (NULL) when: actual == line
# NULL when: recommendation in ('PASS', 'HOLD', 'NO_LINE')
```

The core logic is the same, just implemented in different places:
- `prediction_accuracy`: Python processor
- `prediction_grades`: SQL scheduled query

---

## Validation Findings (2024-25 Season)

Using `prediction_accuracy` (the correct table):

| Metric | Value |
|--------|-------|
| Total predictions | 99,932 |
| Actionable (OVER/UNDER) | 36,102 |
| Graded (TRUE/FALSE) | 35,987 |
| Pushes | 115 |
| Grading rate (actionable) | 99.7% |

**By System:**
| System | Actionable | Accuracy |
|--------|------------|----------|
| catboost_v8 | 13,373 | 74.3% |
| zone_matchup_v1 | 6,682 | 52.3% |
| ensemble_v1 | 6,456 | 60.1% |
| similarity_balanced_v1 | 4,291 | 50.8% |
| moving_average_baseline_v1 | 5,300 | 62.1% |

---

## Recommendations

### Option 1: Consolidate to `prediction_accuracy` (Recommended)

**Pros:**
- Has full historical data
- Already used by ML/analysis processors
- More complete schema

**Actions needed:**
1. Update views to use `prediction_accuracy`
2. Deprecate `prediction_grades` or limit to real-time use
3. Update documentation

### Option 2: Backfill `prediction_grades`

**Pros:**
- Keeps existing view structure
- May have been the intended direction

**Actions needed:**
1. Backfill from `prediction_accuracy` to `prediction_grades`
2. Ensure ongoing sync between tables
3. More maintenance overhead

### Option 3: Keep Both (Document the Split)

**Pros:**
- No immediate code changes

**Cons:**
- Confusing for validation
- Views remain limited to Jan 2026+
- Technical debt

---

## Files to Review

### Processors (write to `prediction_accuracy`):
- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

### Scheduled Queries (write to `prediction_grades`):
- `schemas/bigquery/nba_predictions/grade_predictions_query.sql`
- `schemas/bigquery/nba_predictions/grade_predictions_query_v2.sql`
- `schemas/bigquery/nba_predictions/SCHEDULED_QUERY_READY.sql`

### Views (read from `prediction_grades`):
- `schemas/bigquery/nba_predictions/views/*.sql`

### Schemas:
- `schemas/bigquery/nba_predictions/prediction_accuracy.sql`
- `schemas/bigquery/nba_predictions/prediction_grades.sql`

---

## Action Items for CatBoost Chat

1. **Clarify intent:** What was the original purpose of having two tables?

2. **Decide on source of truth:** Which table should views/dashboards use?

3. **Historical accuracy:** Do we need 2021-2024 data in dashboards, or is Jan 2026+ sufficient?

4. **Recommend consolidation approach:** Option 1, 2, or 3?

5. **Update validation framework:** Document which table to use for what purpose.

---

## Contact

Created during Session 25 (2026-01-29) historical validation work.

See related docs:
- `GRADING-SYSTEM-ANALYSIS.md` - How grading logic works
- `VALIDATION-FRAMEWORK.md` - Updated to use correct table
- `DATA-QUALITY-METRICS.md` - Accuracy metrics from `prediction_accuracy`
