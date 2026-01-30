# Validation Improvements Plan

**Date:** 2026-01-29
**For:** New Session
**From:** Feature Store Patch Session
**Priority:** HIGH - Prevent future bugs like the L5/L10 issue

---

## Background

During Session 27, we discovered and fixed a bug where `ml_feature_store_v2` had incorrect L5/L10 values for ~8,500 records. The bug went undetected because we lacked proper validation between the feature store and its source (player_daily_cache).

This document outlines validation improvements to catch similar issues earlier.

---

## Current State

The `/validate-lineage` skill exists at `.claude/skills/validate-lineage.md` and has:
- Tier 1-3 validation methodology
- Quality metadata analysis
- Interactive mode
- Basic feature store vs cache check (added Session 27)

**What's missing:**
- Automated execution (skill is documentation, not code)
- Duplicate detection
- Cross-table consistency checks
- Pre-commit validation hooks
- Alerting on anomalies

---

## Validation Opportunities

### 1. Feature Store vs Cache Consistency

**What:** Ensure L5/L10 in feature store match cache values
**Why:** Caught the Session 27 bug - feature store had data leakage

```sql
-- Run daily or after backfills
WITH comparison AS (
  SELECT
    FORMAT_DATE('%Y-%m', fs.game_date) as month,
    ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1 as l5_match,
    ABS(fs.features[OFFSET(1)] - c.points_avg_last_10) < 0.1 as l10_match
  FROM `nba_predictions.ml_feature_store_v2` fs
  JOIN `nba_precompute.player_daily_cache` c
    ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
  WHERE fs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
)
SELECT
  month,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(l5_match) / COUNT(*), 1) as l5_match_pct,
  ROUND(100.0 * COUNTIF(l10_match) / COUNT(*), 1) as l10_match_pct
FROM comparison
GROUP BY 1
ORDER BY 1;
```

**Alert if:** Match rate < 95%

---

### 2. Duplicate Detection

**What:** Find duplicate (player_lookup, game_date) pairs
**Why:** Found duplicates during Session 27 MERGE operation

```sql
-- Feature store duplicates
SELECT player_lookup, game_date, COUNT(*) as cnt
FROM `nba_predictions.ml_feature_store_v2`
GROUP BY 1, 2
HAVING COUNT(*) > 1;

-- Cache duplicates
SELECT player_lookup, cache_date, COUNT(*) as cnt
FROM `nba_precompute.player_daily_cache`
GROUP BY 1, 2
HAVING COUNT(*) > 1;

-- Predictions duplicates
SELECT player_lookup, game_date, model_version, prop_type, COUNT(*) as cnt
FROM `nba_predictions.player_prop_predictions`
GROUP BY 1, 2, 3, 4
HAVING COUNT(*) > 1;
```

**Alert if:** Any duplicates found

---

### 3. Data Source Tracking

**What:** Verify records used cache (not fallback)
**Why:** Fallback path had the bug

```sql
-- Check data source distribution
SELECT
  data_source,
  CASE WHEN source_daily_cache_rows_found IS NULL THEN 'No tracking'
       WHEN source_daily_cache_rows_found = 0 THEN 'Cache miss'
       ELSE 'Cache hit'
  END as cache_status,
  COUNT(*) as records,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1, 2
ORDER BY 1, 2;
```

**Alert if:** Cache miss rate > 10% for recent data

---

### 4. Creation Timestamp Analysis

**What:** Check when data was created
**Why:** Detect if backfill created all data at once (potential batch bug)

```sql
-- Check if dates have uniform creation times (suspicious)
SELECT
  game_date,
  COUNT(DISTINCT DATE(created_at)) as distinct_create_dates,
  MIN(created_at) as first_created,
  MAX(created_at) as last_created
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= '2024-10-01'
GROUP BY 1
HAVING COUNT(DISTINCT DATE(created_at)) = 1
ORDER BY 1;
```

**Alert if:** Historical data all created on same day (backfill may have bugs)

---

### 5. Cross-Season Consistency

**What:** Compare metrics across seasons
**Why:** Bug affected 2024-25 but not 2022-24 - should have been flagged

```sql
-- Compare L5/L10 match rates by season
WITH match_rates AS (
  SELECT
    CASE
      WHEN game_date < '2022-07-01' THEN '2021-22'
      WHEN game_date < '2023-07-01' THEN '2022-23'
      WHEN game_date < '2024-07-01' THEN '2023-24'
      WHEN game_date < '2025-07-01' THEN '2024-25'
      ELSE '2025-26'
    END as season,
    ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1 as l5_match
  FROM `nba_predictions.ml_feature_store_v2` fs
  JOIN `nba_precompute.player_daily_cache` c
    ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
)
SELECT
  season,
  COUNT(*) as records,
  ROUND(100.0 * COUNTIF(l5_match) / COUNT(*), 1) as l5_match_pct
FROM match_rates
GROUP BY 1
ORDER BY 1;
```

**Alert if:** Any season differs by > 5% from others

---

### 6. Array Integrity Checks

**What:** Validate features array structure
**Why:** Catch corrupted or incomplete feature vectors

```sql
-- Check feature array integrity
SELECT
  CASE
    WHEN features IS NULL THEN 'NULL array'
    WHEN ARRAY_LENGTH(features) < 33 THEN 'Short array'
    WHEN ARRAY_LENGTH(features) > 33 THEN 'Long array'
    ELSE 'Valid (33 features)'
  END as array_status,
  COUNT(*) as records
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1;

-- Check for NaN/Inf values
SELECT
  player_lookup,
  game_date,
  ARRAY_TO_STRING(features, ',') as features_str
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND (
    EXISTS(SELECT 1 FROM UNNEST(features) f WHERE IS_NAN(f))
    OR EXISTS(SELECT 1 FROM UNNEST(features) f WHERE IS_INF(f))
  )
LIMIT 10;
```

**Alert if:** Any invalid arrays or NaN/Inf values

---

### 7. Patch Audit Trail Monitoring

**What:** Monitor the patch audit table for unexpected changes
**Why:** Track all data corrections

```sql
-- Recent patches
SELECT
  patch_id,
  DATE(MIN(patch_date)) as patch_date,
  COUNT(*) as records_patched,
  MIN(game_date) as min_date,
  MAX(game_date) as max_date,
  ROUND(AVG(ABS(l5_diff)), 2) as avg_l5_correction
FROM `nba_predictions.feature_store_patch_audit`
GROUP BY 1
ORDER BY MIN(patch_date) DESC
LIMIT 10;
```

**Alert if:** New patches appear (triggers review)

---

### 8. Rolling Window Spot Check

**What:** Randomly verify L5/L10 calculations
**Why:** Catch calculation bugs before they affect many records

```sql
-- Spot check: Recompute L5 for random players
WITH recent_games AS (
  SELECT
    player_lookup,
    game_date,
    points,
    AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
    ) as computed_l5
  FROM `nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),
sample AS (
  SELECT * FROM recent_games
  WHERE RAND() < 0.01  -- 1% sample
)
SELECT
  s.player_lookup,
  s.game_date,
  s.computed_l5,
  c.points_avg_last_5 as cache_l5,
  ABS(s.computed_l5 - c.points_avg_last_5) as diff
FROM sample s
JOIN `nba_precompute.player_daily_cache` c
  ON s.player_lookup = c.player_lookup AND s.game_date = c.cache_date
WHERE s.computed_l5 IS NOT NULL
  AND ABS(s.computed_l5 - c.points_avg_last_5) > 0.1
LIMIT 20;
```

**Alert if:** Any mismatches found

---

### 9. Code Pattern Detection (Pre-commit)

**What:** Flag potentially buggy date comparisons in code
**Why:** The bug was `<=` instead of `<` in date comparisons

```python
# .pre-commit-hooks/check_date_comparisons.py

import re
import sys

SUSPICIOUS_PATTERNS = [
    # game_date <= (should usually be <)
    r"game_date\s*<=\s*['\"]?\{",
    r"game_date\s*<=\s*@",
    # cache_date <= (should usually be <)
    r"cache_date\s*<=\s*['\"]?\{",
    # CURRENT ROW in window (includes current)
    r"ROWS BETWEEN.*AND CURRENT ROW",
]

EXCEPTIONS = [
    # These are OK
    r"days_rest",  # days_rest calculation needs <=
    r"WHERE clause for range",  # End of range is OK
]

def check_file(filepath):
    issues = []
    with open(filepath) as f:
        for line_num, line in enumerate(f, 1):
            for pattern in SUSPICIOUS_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    if not any(re.search(exc, line) for exc in EXCEPTIONS):
                        issues.append((line_num, line.strip(), pattern))
    return issues
```

---

### 10. Daily Validation Summary

**What:** Automated daily validation report
**Why:** Catch issues within 24 hours

```sql
-- Daily validation summary
CREATE OR REPLACE VIEW `nba_predictions.daily_validation_summary` AS
WITH checks AS (
  -- Check 1: Feature store vs cache
  SELECT 'feature_cache_match' as check_name,
    ROUND(100.0 * COUNTIF(ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) / COUNT(*), 1) as value,
    95 as threshold,
    'pct' as unit
  FROM `nba_predictions.ml_feature_store_v2` fs
  JOIN `nba_precompute.player_daily_cache` c
    ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
  WHERE fs.game_date = CURRENT_DATE() - 1

  UNION ALL

  -- Check 2: No duplicates
  SELECT 'duplicate_count' as check_name,
    COUNT(*) as value,
    0 as threshold,
    'count' as unit
  FROM (
    SELECT player_lookup, game_date
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date = CURRENT_DATE() - 1
    GROUP BY 1, 2
    HAVING COUNT(*) > 1
  )

  UNION ALL

  -- Check 3: Valid feature arrays
  SELECT 'invalid_arrays' as check_name,
    COUNTIF(ARRAY_LENGTH(features) != 33 OR features IS NULL) as value,
    0 as threshold,
    'count' as unit
  FROM `nba_predictions.ml_feature_store_v2`
  WHERE game_date = CURRENT_DATE() - 1
)
SELECT
  check_name,
  value,
  threshold,
  unit,
  CASE
    WHEN unit = 'pct' AND value < threshold THEN 'FAIL'
    WHEN unit = 'count' AND value > threshold THEN 'FAIL'
    ELSE 'PASS'
  END as status
FROM checks;
```

---

## Implementation Priority

### P0 - Immediate (This Week)

1. **Feature store vs cache validation** - Add to daily checks
2. **Duplicate detection** - Add to daily checks
3. **Array integrity** - Add to daily checks

### P1 - Short Term (This Month)

4. **Data source tracking** - Monitor cache hit rates
5. **Cross-season consistency** - Run after backfills
6. **Patch audit monitoring** - Review all patches

### P2 - Medium Term (Next Quarter)

7. **Pre-commit hook** - Flag suspicious date patterns
8. **Rolling window spot check** - Weekly sampling
9. **Daily validation view** - Automated summary

### P3 - Long Term

10. **Alerting integration** - Slack/email on failures
11. **Dashboard** - Visual validation status
12. **CI/CD integration** - Block deployments on validation failures

---

## Skill Updates Needed

Update `.claude/skills/validate-lineage.md` to:

1. Add all the queries above as runnable commands
2. Implement actual Python/SQL execution (currently documentation only)
3. Add `--alert` flag to send notifications
4. Add `--ci` flag for exit codes in automation
5. Create `validate-feature-store` sub-command

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `.claude/skills/validate-lineage.md` | Update | Add new validation queries |
| `shared/validation/feature_store_validator.py` | Create | Implement feature store checks |
| `shared/validation/daily_validation.py` | Create | Automated daily validation |
| `.pre-commit-hooks/check_date_comparisons.py` | Create | Code pattern detection |
| `schemas/bigquery/views/daily_validation_summary.sql` | Create | Validation summary view |
| `.github/workflows/daily-validation.yml` | Create | Scheduled validation |

---

## Success Criteria

After implementation:

1. Feature store vs cache mismatch would trigger alert within 24 hours
2. Duplicates would be caught before they cause MERGE failures
3. Backfill bugs would be detected by cross-season comparison
4. Suspicious code patterns flagged at commit time
5. Daily validation summary shows all checks passing

---

## Related Documents

- `docs/09-handoff/2026-01-29-SESSION-27-HANDOFF.md` - Bug fix details
- `docs/08-projects/.../FEATURE-STORE-BUG-INVESTIGATION.md` - Root cause
- `schemas/bigquery/patches/2026-01-29_patch_l5_l10_from_cache.sql` - Fix applied

---

*Handoff from Session 27 - 2026-01-29*
