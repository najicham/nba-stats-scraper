# Grading Table Consolidation - Implementation Summary

**Date:** 2026-01-29
**Implemented By:** Validation Chat (Session 25)
**For:** CatBoost/ML Chat

---

## What Was Done

Per your recommendation to consolidate to `prediction_accuracy`, I implemented the following changes:

### 1. Updated 5 Views

All views now query `prediction_accuracy` (419K records, Nov 2021+) instead of `prediction_grades` (9K records, Jan 2026 only).

| View | Status |
|------|--------|
| `confidence_calibration.sql` | ✅ Updated |
| `player_insights_summary.sql` | ✅ Updated |
| `player_prediction_performance.sql` | ✅ Updated |
| `prediction_accuracy_summary.sql` | ✅ Updated |
| `roi_simulation.sql` | ✅ Updated |

**Note:** `roi_summary.sql` reads from `roi_simulation`, so it will automatically use the correct data.

### 2. Schema Field Mapping

The two tables have slightly different schemas. Here's how fields were mapped:

| `prediction_grades` Field | `prediction_accuracy` Field | Notes |
|--------------------------|----------------------------|-------|
| `margin_of_error` | `absolute_error` | Same meaning |
| `has_issues = FALSE` | `is_voided IS NULL OR is_voided = FALSE` | Inverted logic |
| `line_margin` | `actual_margin` | Same meaning |
| `player_dnp` | `is_voided` | DNP = voided |
| `data_quality_tier` | (removed) | Not in prediction_accuracy |

### 3. Added Deprecation Notice

Added to `schemas/bigquery/nba_predictions/prediction_grades.sql`:

```sql
-- DEPRECATED: 2026-01-29
-- Use `prediction_accuracy` table instead for all grading queries.
-- This table only contains Jan 2026 data and is no longer actively maintained.
-- The `prediction_accuracy` table has full historical data from Nov 2021.
```

### 4. Updated CLAUDE.md

Added a "Grading Tables" section to ensure future sessions use the correct table:

```markdown
### Grading Tables

**IMPORTANT:** Use the correct grading table:

| Table | Use For | Data Range |
|-------|---------|------------|
| `prediction_accuracy` | **All grading queries** | Nov 2021 - Present (419K+ records) |
| `prediction_grades` | DEPRECATED - do not use | Jan 2026 only (9K records) |
```

---

## Files Changed

```
schemas/bigquery/nba_predictions/
├── prediction_grades.sql                    # Added deprecation notice
└── views/
    ├── confidence_calibration.sql           # Updated
    ├── player_insights_summary.sql          # Updated
    ├── player_prediction_performance.sql    # Updated
    ├── prediction_accuracy_summary.sql      # Updated
    └── roi_simulation.sql                   # Updated

CLAUDE.md                                    # Added grading table guidance
```

---

## What Needs To Be Done Next

### 1. Deploy Views to BigQuery

The SQL files are updated but the views in BigQuery need to be recreated:

```bash
# Option A: Run each file manually
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/views/confidence_calibration.sql
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/views/player_insights_summary.sql
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/views/player_prediction_performance.sql
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/views/prediction_accuracy_summary.sql
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/views/roi_simulation.sql

# Option B: If there's a deployment script
# ./bin/deploy-views.sh or similar
```

### 2. Verify Views Work

After deployment, verify the views return data:

```sql
-- Should now show data from Nov 2021, not just Jan 2026
SELECT MIN(first_prediction_date), MAX(last_prediction_date)
FROM `nba_predictions.player_prediction_performance`;

-- Should show full historical accuracy
SELECT system_id, COUNT(*) as predictions,
       ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as accuracy
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= '2024-01-01'
GROUP BY system_id;
```

### 3. (Optional) Disable Scheduled Queries

The scheduled queries that write to `prediction_grades` can be disabled:
- `grade_predictions_query.sql`
- `SCHEDULED_QUERY_READY.sql`

Or leave them running if you want `prediction_grades` as a "live" table for recent data only.

---

## Why This Matters

Before this change:
- Views showed only Jan 2026 data (2 weeks)
- CatBoost V8's true 74.3% accuracy was hidden
- Historical analysis was impossible through views

After this change:
- Views show Nov 2021 - present (4+ years)
- Full accuracy history visible
- Calibration curves will be meaningful

---

## Questions?

If anything doesn't work or you need clarification:
1. Check `GRADING-TABLE-CONSOLIDATION-REVIEW.md` for full context
2. Check the view SQL files for the exact changes
3. The field mapping table above explains schema differences
