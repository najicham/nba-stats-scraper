# Pipeline Validation Checklist

**Use this checklist after EVERY backfill or when investigating data issues!**

Created: Jan 3, 2026
Purpose: Standardized validation process to prevent gaps like Phase 4 issue

---

## Pre-Flight Checks

- [ ] Define date range to validate
- [ ] Confirm BigQuery access working
- [ ] Latest code pulled from main

---

## Run Multi-Layer Validation

```bash
cd /home/naji/code/nba-stats-scraper

# Validate last 30 days
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py

# Or specific date range
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py \
  --start-date=YYYY-MM-DD \
  --end-date=YYYY-MM-DD
```

**Expected Output**: Should show coverage percentages for all layers

**Action if fails**:
- Note which layers are failing
- Check specific date gaps
- Proceed to manual checks below

---

## Manual Verification Queries

### Layer 1: Raw Data

```sql
SELECT
  'BDL Boxscores' as source,
  COUNT(DISTINCT game_id) as games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date >= '[START_DATE]'
```

**Acceptance Criteria**:
- [ ] Games count >= expected (check NBA schedule)
- [ ] No gaps > 3 consecutive days
- [ ] Date range matches backfill period

---

### Layer 3: Analytics

```sql
SELECT
  'Analytics' as source,
  COUNT(DISTINCT game_id) as games,
  COUNTIF(minutes_played IS NULL) as null_minutes,
  ROUND(COUNTIF(minutes_played IS NULL) / COUNT(*) * 100, 1) as null_pct,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '[START_DATE]'
```

**Acceptance Criteria**:
- [ ] Games >= 90% of Layer 1
- [ ] No gaps > 3 consecutive days
- [ ] NULL rate acceptable for period:
  - Historical (2021-2023): < 5%
  - Recent backfill (2024): < 45%
  - Current season: < 80%

---

### Layer 4: Precompute (CRITICAL!)

```sql
SELECT
  'Precompute' as source,
  COUNT(DISTINCT game_id) as games,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '[START_DATE]'
```

**Acceptance Criteria**:
- [ ] Games >= 80% of Layer 1 ⚠️ **CRITICAL THRESHOLD**
- [ ] No gaps > 3 consecutive days
- [ ] **This was missing before - ALWAYS check!**

---

### Cross-Layer Comparison

```sql
WITH all_layers AS (
  SELECT
    (SELECT COUNT(DISTINCT game_id) FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
     WHERE game_date >= '[START_DATE]') as layer1,
    (SELECT COUNT(DISTINCT game_id) FROM `nba-props-platform.nba_analytics.player_game_summary`
     WHERE game_date >= '[START_DATE]') as layer3,
    (SELECT COUNT(DISTINCT game_id) FROM `nba-props-platform.nba_precompute.player_composite_factors`
     WHERE game_date >= '[START_DATE]') as layer4
)
SELECT
  layer1,
  layer3,
  layer4,
  ROUND(100.0 * layer3 / NULLIF(layer1, 0), 1) as l3_pct,
  ROUND(100.0 * layer4 / NULLIF(layer1, 0), 1) as l4_pct
FROM all_layers
```

**Acceptance Criteria**:
- [ ] L3_pct >= 90%
- [ ] L4_pct >= 80% ⚠️ **ML training threshold**

---

## Post-Backfill Validation

### After Phase 3 (Analytics) Backfill

```sql
-- Check NULL rates by year
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as total_records,
  COUNTIF(minutes_played IS NULL) as null_minutes,
  ROUND(COUNTIF(minutes_played IS NULL) / COUNT(*) * 100, 1) as null_pct,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'
GROUP BY year
ORDER BY year DESC
```

**Acceptance**:
- [ ] 2021-2023: NULL < 5%
- [ ] 2024: NULL < 45%
- [ ] Total records: 80,000-100,000

---

### After Phase 4 (Precompute) Backfill

```sql
-- Check 2024-25 season coverage
WITH layer1 AS (
  SELECT COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= '2024-10-01'
),
layer4 AS (
  SELECT COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= '2024-10-01'
)
SELECT
  l1.games as layer1_games,
  l4.games as layer4_games,
  ROUND(100.0 * l4.games / l1.games, 1) as coverage_pct
FROM layer1 l1, layer4 l4
```

**Acceptance**:
- [ ] Coverage >= 80%
- [ ] If 2024-25: Should be ~1,620+ games (80% of ~2,027)

---

## Troubleshooting

### If Layer 4 Coverage < 80%

1. **Identify missing dates**:
```bash
PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py \
  --start-date=2024-10-01 \
  --end-date=2025-12-31
```

2. **Check specific date**:
```sql
SELECT COUNT(DISTINCT game_id) as games
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE DATE(game_date) = '[SPECIFIC_DATE]'
```

3. **Backfill missing dates**:
```bash
# Document in runbook
```

---

### If NULL Rates Too High

1. **Check data sources**:
```sql
SELECT
  primary_source_used,
  COUNT(*) as records,
  COUNTIF(minutes_played IS NULL) as null_count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '[START_DATE]'
GROUP BY primary_source_used
```

2. **Investigate specific games**:
```sql
SELECT game_id, game_date, primary_source_used
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE minutes_played IS NULL
  AND game_date >= '[START_DATE]'
LIMIT 10
```

---

## Weekly Health Check

Run every Sunday:
```bash
./scripts/monitoring/weekly_pipeline_health.sh
```

**Review log**:
```bash
ls -lht logs/monitoring/weekly_health_*.log | head -1
```

**If gaps found**:
- [ ] Document in GitHub issue
- [ ] Prioritize based on impact (blocks ML? blocks predictions?)
- [ ] Schedule backfill
- [ ] Re-validate after backfill

---

## Sign-Off

**Backfill Details**:
- Backfill type: _______________ (Phase 3 / Phase 4 / Other)
- Date range: _______________
- Execution date: _______________

**Validation Results**:
- Validated by: _______________
- Validation date: _______________
- Validation tool used: [ ] Auto script [ ] Manual queries
- All checks passed: [ ] YES [ ] NO

**Issues Found**:
- [ ] None
- [ ] Documented in: _______________

**Approved for**:
- [ ] Production use
- [ ] ML training
- [ ] Prediction generation

---

## Related Documents

- **Validation Script**: `scripts/validation/validate_pipeline_completeness.py`
- **Weekly Health**: `scripts/monitoring/weekly_pipeline_health.sh`
- **Data State Analysis**: `docs/09-handoff/2026-01-03-DATA-STATE-ANALYSIS.md`
- **Strategic Plan**: `docs/09-handoff/2026-01-04-STRATEGIC-ULTRATHINK.md`

---

**Remember**: The Phase 4 gap went undetected for 3 months. This checklist prevents that!
