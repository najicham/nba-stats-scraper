# ML Data Quality Requirements

**Purpose**: Data quality standards for ML model training
**Last Updated**: January 6, 2026

---

## Critical Requirements

### 1. Usage Rate ≥0.95

**What it is**: `usage_rate` = percentage of expected player-game records present

**Requirement**: Average usage_rate ≥0.95 across training data

**Why it matters**: Low usage_rate indicates missing player data (incomplete games). Training on incomplete data produces poor predictions.

**Check**:
```sql
SELECT
  ROUND(AVG(usage_rate), 3) as avg_usage_rate,
  COUNTIF(usage_rate >= 0.95) as high_quality_count,
  COUNT(*) as total_count,
  ROUND(100.0 * COUNTIF(usage_rate >= 0.95) / COUNT(*), 1) as pct_high_quality
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
```

**Expected**:
- avg_usage_rate ≥0.95
- pct_high_quality ≥90%

**If fails**: Run backfills to complete missing data

### 2. No NULL in Critical Fields

**Critical fields**:
- `minutes_played` (when player participated)
- `points`, `rebounds`, `assists`
- `usage_rate`
- `team_id`, `opponent_id`

**Check**:
```sql
SELECT
  COUNTIF(minutes_played IS NULL AND minutes_played_str IS NOT NULL) as bad_minutes_nulls,
  COUNTIF(points IS NULL) as null_points,
  COUNTIF(usage_rate IS NULL) as null_usage_rate
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
```

**Expected**: All = 0

**If fails**: Data quality bug, fix processor and reprocess

**Historical bug**: Jan 2026 - `minutes_played` incorrectly coerced to NULL. Fixed in commit 83d91e2.

### 3. Minimum Dataset Size

**Requirement**: ≥500K player-game records for training

**Why**: Smaller datasets lead to overfitting

**Check**:
```sql
SELECT COUNT(*) as total_rows
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND usage_rate >= 0.95
```

**Expected**: ≥500,000 rows

### 4. Date Range Coverage

**Requirement**: ≥850 game dates (92% of 918 full history)

**Why**: Need multiple seasons for pattern learning

**Check**:
```sql
SELECT COUNT(DISTINCT game_date) as unique_dates
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND usage_rate >= 0.95
```

**Expected**: ≥850 dates

---

## Data Quality Lessons (Jan 2026)

### Discovery: 55% Fake Mock Data

**What happened**: Before Jan 2026 backfills, training data contained:
- Real data: ~45% (400/918 dates)
- Fake/mock data: ~55% (518/918 dates with usage_rate <0.10)

**Impact**: Models trained on this data had MAE >5.0 (poor performance)

**Fix**: Complete backfills to achieve 918/918 date coverage

**Result**: MAE improved from 5.20 → 4.15 (20% improvement)

### minutes_played NULL Bug

**What happened**: Field incorrectly coerced to NULL despite valid data in `minutes_played_str`

**Impact**: ~30% of training rows had NULL minutes, breaking model

**Fix**: Commit 83d91e2 - Proper field parsing

**Lesson**: Always validate data extraction, never assume fields are correct

---

## Validation Checklist

Before training any model:

- [ ] Usage rate ≥0.95 average
- [ ] ≥90% of rows have usage_rate ≥0.95
- [ ] Zero NULLs in critical fields
- [ ] ≥500K total rows
- [ ] ≥850 unique dates
- [ ] No duplicate (game_date, player_lookup) pairs
- [ ] Data range includes recent season (for relevance)

---

**Related Documentation**:
- [ML Training Procedures](./training-procedures.md)
- [Backfill Master Guide](../../02-operations/backfill/master-guide.md)
