# Validation Documentation

> **Entry point for all validation-related documentation.**

---

## What Are You Validating?

| Validation Type | Go To | Description |
|-----------------|-------|-------------|
| **Daily orchestration** | [../02-operations/MORNING-VALIDATION-GUIDE.md](../02-operations/MORNING-VALIDATION-GUIDE.md) | Today's or yesterday's pipeline runs |
| **Season completeness** | [../08-projects/current/historical-backfill-audit/](../08-projects/current/historical-backfill-audit/) | Entire season data coverage |
| **Backfill validation** | [../02-operations/backfill/backfill-validation-checklist.md](../02-operations/backfill/backfill-validation-checklist.md) | Pre/during/post backfill checks |
| **Framework design** | [framework/](./framework/) | Validation system architecture |
| **Daily tasks** | [operational/](./operational/) | Current priorities and findings |

---

## Quick Season Validation Commands

### Check Season Coverage

```bash
# Season date ranges
# 2024-25: Oct 22, 2024 - Jun 2025 (current)
# 2023-24: Oct 24, 2023 - Jun 2024
# 2022-23: Oct 18, 2022 - Jun 2023
# 2021-22: Oct 19, 2021 - Jun 2022

# Check Phase 3 analytics coverage for a season
bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT game_date) as dates_with_data,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2024-10-22' AND game_date <= CURRENT_DATE()"

# Check predictions coverage
bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT game_date) as dates_with_predictions,
  COUNT(*) as total_predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date >= '2024-10-22' AND game_date <= CURRENT_DATE()"

# Check grading coverage
bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT game_date) as dates_graded,
  COUNTIF(actual_value IS NOT NULL) as graded_predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date >= '2024-10-22' AND game_date <= CURRENT_DATE()"
```

### Validate Pipeline for Date Range

```bash
# Single date
python bin/validate_pipeline.py 2024-10-22

# Date range
python bin/validate_pipeline.py 2024-10-22 2025-01-24
```

---

## Directory Structure

```
validation/
├── README.md           # THIS FILE - start here
├── framework/          # Validation system design & architecture
│   ├── VALIDATION-FRAMEWORK-DESIGN.md
│   ├── IMPLEMENTATION-PLAN.md
│   └── EXECUTIVE-SUMMARY.md
├── operational/        # Current tasks and findings
│   ├── NBA_PRIORITIES_TODO_LIST.md
│   ├── NBA_VALIDATION_TODO_LIST.md
│   └── 2026-01-16-OPERATIONAL-FINDINGS.md
├── reports/            # Historical validation reports
│   └── JAN_*_REPORT.md
└── guides/             # User guides and references
    ├── VALIDATION-GUIDE.md
    └── VALIDATION-COMMANDS-REFERENCE.md
```

---

## Related Documentation

| Topic | Location |
|-------|----------|
| Morning validation | `docs/02-operations/MORNING-VALIDATION-GUIDE.md` |
| Backfill procedures | `docs/02-operations/backfill/` |
| Historical audit project | `docs/08-projects/current/historical-backfill-audit/` |
| Phase 1 orchestration | `docs/03-phases/phase1-orchestration/` |

---

## Season Coverage Summary

From historical-backfill-audit project (as of Jan 2026):

| Season | Analytics | Predictions | Grading | Notes |
|--------|-----------|-------------|---------|-------|
| 2021-22 | 93.4% | 93.4% | 93.4% | ~14-day bootstrap gap |
| 2022-23 | 93.4% | 93.4% | 93.4% | ~14-day bootstrap gap |
| 2023-24 | 93.2% | 93.2% | 93.2% | ~14-day bootstrap gap |
| 2024-25 | 93.4% | 93.4% | 93.4% | ~14-day bootstrap gap |
| 2025-26 | 97.8% | 97.8% | ~65% | Current season, grading ongoing |

**Note:** Every season has ~14-day bootstrap gap at start because predictions require historical rolling averages.

---

**Last Updated:** 2026-01-24
