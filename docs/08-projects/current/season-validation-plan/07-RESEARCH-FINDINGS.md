# Research Findings - Plan Refinements

## Overview

Additional research conducted on Jan 25, 2026 revealed important details that refine our validation approach.

## 1. Schema Corrections

### player_game_summary

**Original assumption:** Has `is_production_ready`, `completeness_pct`
**Actual:** Does NOT have these columns

**Correct columns for quality validation:**
- `data_quality_tier` (STRING) - Values: 'high', 'medium', 'low'
- `processed_with_issues` (BOOLEAN)
- `source_{prefix}_completeness_pct` - Per-source completeness (7 sources)

**Updated validation query:**
```sql
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(data_quality_tier = 'high') as high_quality,
  COUNTIF(data_quality_tier = 'medium') as medium_quality,
  COUNTIF(data_quality_tier = 'low') as low_quality,
  COUNTIF(processed_with_issues = TRUE) as has_issues
FROM `nba_analytics.player_game_summary`
WHERE game_date BETWEEN @start_date AND @end_date
GROUP BY game_date
```

### ml_feature_store_v2

**Confirmed columns:**
- `is_production_ready` (BOOLEAN) - TRUE if completeness >= 90% AND upstream complete
- `completeness_percentage` (FLOAT64) - 0-100%
- `data_quality_issues` (ARRAY<STRING>)
- `historical_completeness` (STRUCT) - Contains cascade detection

### player_daily_cache

**Confirmed columns:**
- `is_production_ready` (BOOLEAN)
- `completeness_percentage` (FLOAT64)
- Multi-window completeness:
  - `l5_completeness_pct`, `l5_is_complete`
  - `l10_completeness_pct`, `l10_is_complete`
  - `l7d_completeness_pct`, `l7d_is_complete`
  - `l14d_completeness_pct`, `l14d_is_complete`
  - `all_windows_complete` (BOOLEAN) - ALL must pass

---

## 2. Threshold Corrections

### Production Ready: 70% (Confirmed)

From `shared/utils/completeness_checker.py`:
```python
# Lowered from 90 to 70 to account for BDL API data gaps
self.production_ready_threshold = 70.0  # Percentage
```

**Rationale:** BDL API consistently misses west coast late games.

### Window Sizes: NO L20!

**Original assumption:** L5, L10, L14d, L20
**Actual windows:**
- L5: 5 games
- L10: 10 games
- L7d: 7 calendar days
- L14d: 14 calendar days

**No L20 window exists.** Cascade impact is shorter than assumed.

### Bootstrap Period: 14 Days (Confirmed)

From `shared/validation/config.py`:
```python
BOOTSTRAP_DAYS = 14  # Days 0-13 of each season
```

### Multi-Window Validation

ALL 4 windows must independently reach 70% for `all_windows_complete = TRUE`:
```python
all_windows_complete = (
    comp_l5['is_production_ready'] and    # >= 70%
    comp_l10['is_production_ready'] and   # >= 70%
    comp_l7d['is_production_ready'] and   # >= 70%
    comp_l14d['is_production_ready']      # >= 70%
)
```

---

## 3. Recent Known Issues (as of Jan 25, 2026)

### Critical Issues to Validate

| Issue | Impact | Status |
|-------|--------|--------|
| Firestore 45-hour outage (Jan 23) | All workflows stuck, quality degraded | FIXED |
| Prediction duplicates (6,473 rows) | Bloated predictions table | PENDING CLEANUP |
| nbac_player_boxscore Jan 24 failure | 85.7% complete (6/7 games) | IN RETRY QUEUE |
| 618 orphaned analytics records | Analytics without raw boxscores | UNDER INVESTIGATION |
| Feature quality all bronze | 64.4 avg quality score | RECOVERING |

### Affected Date Ranges

| Date Range | Issue | Validation Focus |
|------------|-------|------------------|
| Jan 23-25, 2026 | Firestore outage recovery | Check workflow decisions resumed |
| Jan 24, 2026 | Missing game data | Verify 7/7 games now present |
| Jan 15-25, 2026 | Duplicate predictions | Check for duplicate business keys |
| Jan 1-25, 2026 | Feature store 80% failure | Verify historical_completeness fixed |

### Quality Recovery Timeline

After the Jan 23 outage:
- L5D (last 5 days): ~2-3 days to recover
- L10D (last 10 days): ~7-10 days to recover
- Full recovery: ~2 weeks

---

## 4. Existing Infrastructure to Leverage

### BigQuery Tables Already Available

```sql
-- Validation results (populated by validators)
SELECT * FROM `validation.validation_results` WHERE ...

-- Pre-built view for recent failures
SELECT * FROM `validation.validation_failures_recent`

-- Processor health summary
SELECT * FROM `validation.processor_health_summary`

-- Current processor status
SELECT * FROM `validation.processor_status_current`

-- Processor run history (comprehensive audit trail)
SELECT * FROM `nba_reference.processor_run_history`
```

### Existing Validation Script

```bash
# Already exists and covers all phases
python3 bin/validate_pipeline.py 2026-01-20 --verbose

# Date range validation
python3 bin/validate_pipeline.py 2024-10-22 2026-01-25 --output json
```

### Existing Validation Reports

Located at:
- `/validation_results/january_2026_complete/final_report.txt`
- `/docs/02-operations/validation-reports/2026-01-*.md`
- `/docs/validation/reports/*.md`

---

## 5. Updated Cascade Impact Calculation

### Corrected Window Impact

Since there's no L20, cascade impact is shorter:

| Gap Phase | Max Downstream Impact |
|-----------|----------------------|
| Phase 2 | 14 days (L14d window) |
| Phase 3 | 14 days (L14d window) |
| Phase 4 | 10 days (L10 window) |
| Phase 5 | 0 days (no cascade) |

### Updated Cascade Query

```sql
-- Cascade impact (corrected for actual windows)
SELECT
  gap_date,
  affected_date,
  DATE_DIFF(affected_date, gap_date, DAY) as days_downstream,
  CASE
    WHEN DATE_DIFF(affected_date, gap_date, DAY) <= 5 THEN 'L5_IMPACT'
    WHEN DATE_DIFF(affected_date, gap_date, DAY) <= 7 THEN 'L7D_IMPACT'
    WHEN DATE_DIFF(affected_date, gap_date, DAY) <= 10 THEN 'L10_IMPACT'
    ELSE 'L14D_IMPACT'
  END as impact_window
FROM gaps g
CROSS JOIN game_dates d
WHERE d.game_date > g.gap_date
  AND d.game_date <= DATE_ADD(g.gap_date, INTERVAL 14 DAY)  -- Max 14 days, not 30
```

---

## 6. Recommendations

### Use Existing Tools First

1. **Run `bin/validate_pipeline.py`** - Already covers all phases
2. **Query `processor_run_history`** - Has comprehensive audit trail
3. **Check `validation.processor_status_current`** - Quick health view

### Focus Validation on Known Issues

1. **Jan 23-25 recovery** - Verify Firestore fix propagated
2. **Jan 24 missing game** - Confirm retry succeeded
3. **Duplicate predictions** - Run deduplication check
4. **Quality scores** - Track bronze → silver → gold recovery

### Revised Cascade Estimates

Original plan assumed 30-day cascade; actual is **14-day max**. This means:
- Fewer dates need re-running after gap fixes
- Recovery is faster than estimated
- Priority scores should be recalculated

---

## 7. Schema File References

For future reference, schema definitions are at:
- `/schemas/bigquery/analytics/player_game_summary_tables.sql`
- `/schemas/bigquery/predictions/04_ml_feature_store_v2.sql`
- `/schemas/bigquery/precompute/player_daily_cache.sql`
- `/schemas/bigquery/validation/validation_results.sql`
- `/schemas/bigquery/nba_reference/processor_run_history.sql`
