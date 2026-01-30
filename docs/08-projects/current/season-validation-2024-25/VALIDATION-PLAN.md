# Comprehensive Historical Validation Plan

**Created:** 2026-01-29
**Scope:** 4 seasons (2021-22, 2022-23, 2023-24, 2024-25)
**Goal:** Complete data quality validation with lineage verification

---

## Season Overview

| Season | Dates | Records | Status |
|--------|-------|---------|--------|
| 2024-25 | Oct 22, 2024 - Jun 22, 2025 | 28,240 | ✅ Initial validation complete |
| 2023-24 | Oct 24, 2023 - Jun 17, 2024 | 28,203 | 📋 Pending |
| 2022-23 | Oct 18, 2022 - Jun 12, 2023 | 27,839 | 📋 Pending |
| 2021-22 | Oct 19, 2021 - Jun 16, 2022 | 28,516 | 📋 Pending |

---

## Validation Categories

### 1. Data Completeness
- [ ] Phase 2 (Raw): Game coverage vs NBA schedule
- [ ] Phase 3 (Analytics): Player records per game
- [ ] Phase 4 (Precompute): Cache coverage
- [ ] Phase 5 (Predictions): Prediction generation
- [ ] Phase 6 (Grading): Grading completeness

### 2. Data Lineage (Calculation Verification)
- [ ] Points arithmetic: `points = 2*(FG-3P) + 3*3P + FT`
- [ ] Rolling averages: L5, L10 match recalculated
- [ ] Usage rate: Formula verification
- [ ] Feature store: Matches source tables

### 3. Grading & Accuracy
- [ ] Grading coverage analysis
- [ ] Accuracy by system
- [ ] Backfill missing grades (where data exists)

### 4. Anomaly Detection
- [ ] Statistical outliers
- [ ] Cross-source discrepancies
- [ ] Missing player records

---

## Phase 1: Data Completeness Checks

### 1.1 Analytics Coverage by Season

```sql
-- Run for each season_year
SELECT
  season_year,
  COUNT(*) as records,
  COUNT(DISTINCT game_date) as dates,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT game_id) as games
FROM `nba_analytics.player_game_summary`
WHERE season_year IN (2021, 2022, 2023, 2024)
GROUP BY season_year
ORDER BY season_year
```

### 1.2 Cache Coverage by Season

```sql
SELECT
  EXTRACT(YEAR FROM cache_date) as year,
  COUNT(DISTINCT cache_date) as dates,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as records
FROM `nba_precompute.player_daily_cache`
GROUP BY year
ORDER BY year
```

### 1.3 Prediction Coverage by Season

```sql
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as predictions,
  COUNT(DISTINCT game_date) as dates,
  COUNT(DISTINCT player_lookup) as players
FROM `nba_predictions.player_prop_predictions`
GROUP BY year
ORDER BY year
```

---

## Phase 2: Data Lineage Validation

### 2.1 Points Arithmetic (All Seasons)

```sql
-- Verify points = 2*(FG-3P) + 3*3P + FT for all seasons
SELECT
  season_year,
  COUNT(*) as total,
  COUNTIF(points = (2 * (fg_makes - three_pt_makes) + 3 * three_pt_makes + ft_makes)) as correct,
  COUNTIF(points != (2 * (fg_makes - three_pt_makes) + 3 * three_pt_makes + ft_makes)) as incorrect
FROM `nba_analytics.player_game_summary`
WHERE points IS NOT NULL AND fg_makes IS NOT NULL
GROUP BY season_year
ORDER BY season_year
```

### 2.2 Rolling Average Validation (Sample per Season)

For each season, sample 20 player-dates and verify:
- `points_avg_last_5` matches AVG of last 5 games
- `points_avg_last_10` matches AVG of last 10 games

**Tolerance:** ≤0.5 points difference acceptable

### 2.3 Usage Rate Formula Check

```sql
-- USG% = 100 × (FGA + 0.44 × FTA + TO) × 48 / (MP × Team_Usage)
-- Sample 20 records per season and verify
```

---

## Phase 3: Grading Analysis

### 3.1 Grading Coverage by Season

```sql
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as total,
  COUNTIF(prediction_correct IS NOT NULL) as graded,
  COUNTIF(prediction_correct IS NULL) as ungraded,
  COUNTIF(actual_points IS NOT NULL) as has_actual,
  COUNTIF(line_value IS NOT NULL) as has_line
FROM `nba_predictions.prediction_accuracy`
GROUP BY year
ORDER BY year
```

### 3.2 Accuracy by System per Season

```sql
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  system_id,
  COUNT(*) as predictions,
  COUNTIF(prediction_correct = true) as correct,
  ROUND(100.0 * COUNTIF(prediction_correct = true) /
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as accuracy
FROM `nba_predictions.prediction_accuracy`
GROUP BY year, system_id
ORDER BY year, accuracy DESC
```

### 3.3 Backfill Opportunity Analysis

Records with `actual_points` AND `line_value` but `prediction_correct IS NULL`:

```sql
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as backfill_candidates
FROM `nba_predictions.prediction_accuracy`
WHERE prediction_correct IS NULL
  AND actual_points IS NOT NULL
  AND line_value IS NOT NULL
GROUP BY year
```

---

## Phase 4: Anomaly Detection

### 4.1 Statistical Outliers

```sql
-- Find games with unusual stats
SELECT *
FROM `nba_analytics.player_game_summary`
WHERE minutes_played > 48
   OR points > 70
   OR usage_rate > 100
   OR fg_attempts < fg_makes
```

### 4.2 Missing Player Records

```sql
-- Players in predictions but not in analytics for same game
SELECT p.player_lookup, p.game_date, p.game_id
FROM `nba_predictions.player_prop_predictions` p
LEFT JOIN `nba_analytics.player_game_summary` a
  ON p.player_lookup = a.player_lookup AND p.game_date = a.game_date
WHERE a.player_lookup IS NULL
```

### 4.3 Cross-Source Reconciliation

Compare NBA.com (NBAC) vs BDL for point totals:
```sql
-- Find discrepancies > 2 points between sources
```

---

## Execution Plan

### Session 2: Complete 2024-25 Deep Validation
- [ ] Run all Phase 2 lineage checks
- [ ] Investigate rolling average discrepancies
- [ ] Document grading backfill opportunity
- [ ] Run anomaly detection

### Session 3: 2023-24 Season Validation
- [ ] Apply same framework
- [ ] Compare patterns to 2024-25
- [ ] Document any differences

### Session 4: 2022-23 Season Validation
- [ ] Apply same framework
- [ ] Note any schema changes over time

### Session 5: 2021-22 Season Validation
- [ ] Apply same framework
- [ ] Complete cross-season comparison

### Session 6: Final Report
- [ ] Consolidate findings
- [ ] Prioritize remediation
- [ ] Document prevention mechanisms

---

## Tools & Skills to Use

| Task | Tool/Skill |
|------|------------|
| Historical completeness | `/validate-historical` |
| Data lineage | `/validate-lineage` |
| Spot checks | `scripts/spot_check_data_accuracy.py` |
| Player deep dive | `/spot-check-player` |
| System-wide gaps | `/spot-check-gaps` |
| Cascade analysis | `/spot-check-cascade` |

---

## Success Criteria

| Metric | Target | Current (2024-25) |
|--------|--------|-------------------|
| Points arithmetic | 100% correct | ✅ 100% |
| Rolling avg match | ≥90% within 0.5 | ⚠️ 20-40% |
| Analytics coverage | ≥95% of schedule | TBD |
| Grading coverage | ≥80% with lines | 36% |
| Anomaly rate | <0.1% | TBD |

---

## Questions to Answer

1. **Why do rolling averages differ?**
   - Different game inclusion rules?
   - DNP handling?
   - Timing of cache generation?

2. **Why are 38,522 predictions with all data ungraded?**
   - Grading logic bug?
   - Never ran?
   - Filter criteria?

3. **Is catboost_v8 consistently best across seasons?**
   - Check per-season accuracy
   - Identify if model improved over time

4. **Are there systematic data gaps?**
   - Specific teams?
   - Specific time periods?
   - West coast games?
