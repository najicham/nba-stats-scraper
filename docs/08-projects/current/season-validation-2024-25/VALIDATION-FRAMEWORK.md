# Validation Framework - 2024-25 Season

## Overview

Multi-phase validation approach to ensure data quality across the entire 2024-25 NBA season pipeline.

## Validation Phases

### Phase 2: Raw Data Completeness

**Tables:**
- `nba_raw.bdl_player_boxscores` - Ball Don't Lie API data
- `nba_raw.nbac_gamebook_player_stats` - NBA.com Gamebook data
- `nba_raw.bettingpros_player_props` - Prop lines

**Metrics:**
- Games scraped vs. games scheduled
- Player records per game
- Source completeness percentage

**Acceptable Thresholds:**
- Game coverage: ≥95%
- Player coverage: ≥92%

**Query Template:**
```sql
-- Phase 2 Raw Data Coverage
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as player_records,
  COUNT(DISTINCT player_lookup) as unique_players
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date BETWEEN '2024-10-22' AND '2025-06-22'
  AND season_year = 2024
GROUP BY game_date
ORDER BY game_date
```

---

### Phase 3: Analytics Completeness

**Tables:**
- `nba_analytics.player_game_summary` - 92-field enriched player stats

**Metrics:**
- Records per game date
- Data quality tier distribution
- Source tracking completeness
- DNP visibility

**Acceptable Thresholds:**
- Records per date: ≥120 (typical ~130-150)
- High quality tier: ≥70%
- Source completeness: ≥85%

**Query Template:**
```sql
-- Phase 3 Analytics Quality
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(data_quality_tier = 'HIGH') as high_quality,
  COUNTIF(is_dnp = true) as dnp_count,
  ROUND(100.0 * COUNTIF(data_quality_tier = 'HIGH') / COUNT(*), 1) as high_quality_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2024-10-22' AND '2025-06-22'
  AND season_year = 2024
GROUP BY game_date
ORDER BY game_date
```

---

### Phase 4: Precompute Coverage

**Tables:**
- `nba_precompute.player_daily_cache`
- `nba_precompute.player_composite_factors`
- `nba_precompute.player_shot_zone_analysis`
- `nba_precompute.team_defense_zone_analysis`

**Metrics:**
- Processor completion status
- Rolling average completeness
- Composite factor coverage

**Acceptable Thresholds:**
- All 4-5 processors complete per date
- Historical completeness ≥90%

**Query Template:**
```sql
-- Phase 4 Precompute Status
SELECT
  game_date,
  COUNT(DISTINCT processor_name) as processors_complete,
  SUM(record_count) as total_records
FROM `nba-props-platform.nba_orchestration.processor_runs`
WHERE game_date BETWEEN '2024-10-22' AND '2025-06-22'
  AND phase = 'phase4'
  AND status = 'success'
GROUP BY game_date
ORDER BY game_date
```

---

### Phase 5: Predictions Coverage

**Tables:**
- `nba_predictions.player_prop_predictions`
- `nba_predictions.ml_feature_store_v2`

**Metrics:**
- Predictions generated per game date
- Unique players with predictions
- Feature store completeness

**Acceptable Thresholds:**
- Predictions: Present for each game date
- Feature coverage: ≥85%

**Query Template:**
```sql
-- Phase 5 Predictions Coverage
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT prediction_system) as systems_used
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date BETWEEN '2024-10-22' AND '2025-06-22'
GROUP BY game_date
ORDER BY game_date
```

---

### Phase 6: Grading Coverage

**Tables:**
- `nba_predictions.prediction_accuracy` - **Primary grading table (use this!)**
- `nba_predictions.prediction_grades` - Limited recent data only, do NOT use for historical

**IMPORTANT:** Use `prediction_accuracy` for all grading validation. The `prediction_grades` table only has recent data (Jan 2026+).

**Metrics:**
- Grading coverage for actionable picks (OVER/UNDER)
- Accuracy by system
- Push rate

**Acceptable Thresholds:**
- Grading coverage for actionable picks: ≥99%
- Push rate: ~0.3% (expected)

**Understanding "Ungraded":**
- `PASS` recommendation → Expected NULL (no bet suggested)
- `NO_LINE` recommendation → Expected NULL (no line available)
- Push (actual == line) → Expected NULL (neither win nor loss)
- `OVER/UNDER` with line, not push → Should be graded (TRUE/FALSE)

**Query Template:**
```sql
-- Phase 6 Grading Analysis (CORRECTED)
SELECT
  recommendation,
  COUNT(*) as total,
  COUNTIF(prediction_correct = true) as correct,
  COUNTIF(prediction_correct = false) as incorrect,
  COUNTIF(prediction_correct IS NULL) as ungraded,
  ROUND(100.0 * COUNTIF(prediction_correct = true) /
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as accuracy_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date BETWEEN '2024-10-22' AND '2025-06-22'
GROUP BY recommendation
ORDER BY total DESC
```

**Accuracy by System:**
```sql
SELECT
  system_id,
  COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable_picks,
  COUNTIF(prediction_correct IS NOT NULL) as graded,
  COUNTIF(prediction_correct = true) as correct,
  ROUND(100.0 * COUNTIF(prediction_correct = true) /
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as accuracy_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date BETWEEN '2024-10-22' AND '2025-06-22'
GROUP BY system_id
ORDER BY accuracy_pct DESC
```

---

### Cache Lineage Validation

**Purpose:** Verify that cached rolling averages match recalculated values from source data.

**CRITICAL:** Validation queries MUST exactly match processor logic:

| Filter | Processor Logic | Why |
|--------|-----------------|-----|
| Date comparison | `game_date < cache_date` | Cache is generated BEFORE the day's games |
| Season filter | `season_year = X` | Only same-season games |
| Active filter | `is_active = TRUE` | Only active roster players |
| DNP filter | `minutes_played > 0 OR points > 0` | Exclude DNP records |

**Query Template (CORRECT):**
```sql
-- Cache lineage validation - matches processor logic exactly
WITH sample_cache AS (
  SELECT player_lookup, cache_date, points_avg_last_5 as cached_l5
  FROM `nba_precompute.player_daily_cache`
  WHERE cache_date = @validate_date
    AND points_avg_last_5 IS NOT NULL
  LIMIT 50
),
games_ranked AS (
  SELECT
    g.player_lookup,
    s.cache_date,
    g.points,
    ROW_NUMBER() OVER (PARTITION BY g.player_lookup ORDER BY g.game_date DESC) as rn
  FROM sample_cache s
  JOIN `nba_analytics.player_game_summary` g
    ON g.player_lookup = s.player_lookup
    AND g.game_date < s.cache_date  -- CRITICAL: strictly BEFORE
    AND g.season_year = @season_year
    AND g.is_active = TRUE
    AND (g.minutes_played > 0 OR g.points > 0)
),
recalc AS (
  SELECT player_lookup, ROUND(AVG(points), 1) as calc_l5
  FROM games_ranked WHERE rn <= 5
  GROUP BY player_lookup
)
SELECT
  s.player_lookup,
  s.cached_l5,
  r.calc_l5,
  CASE WHEN ABS(s.cached_l5 - r.calc_l5) < 0.1 THEN 'MATCH' ELSE 'DIFF' END as status
FROM sample_cache s
JOIN recalc r ON s.player_lookup = r.player_lookup
```

**Acceptable Thresholds:**
- Exact match rate: 100% (within 0.1 pts for rounding)
- Any DIFF indicates a bug in processor or validation query

**Common Mistakes to Avoid:**
- ❌ Using `<=` instead of `<` for date comparison
- ❌ Forgetting season_year filter (includes prior season games)
- ❌ Forgetting is_active filter
- ❌ Forgetting DNP filter

---

## Validation Approach

### Tier 1: Aggregate Validation (~5 min)
- Run summary queries for each phase
- Identify dates with coverage below thresholds
- Flag critical gaps (P1/P2)

### Tier 2: Sample Validation (flagged dates only)
- Deep dive on specific dates with issues
- Check individual player records
- Identify root causes

### Tier 3: Cascade Analysis (if issues found)
- Trace upstream dependencies
- Identify contaminated downstream data
- Generate remediation plan

---

## Known Risk Factors

### Expected Gaps
- **Bootstrap period** (Oct 22 - Nov 5): New players have incomplete rolling windows
- **All-Star weekend** (Feb): No regular games
- **Trade deadline**: Player ID changes

### Data Collection Timing
- West coast games: Data arrives late
- Back-to-back games: Tight processing windows
- Postponed games: Schedule mismatches

---

## Tools and Skills

| Tool | Purpose | Usage |
|------|---------|-------|
| `/validate-historical` | Full date range validation | `/validate-historical 2024-10-22 2025-06-22` |
| `/validate-lineage` | Cascade detection | `/validate-lineage investigate 2024-11-15` |
| `check_cascade.py` | Downstream impact | `python bin/check_cascade.py --backfill-date 2024-11-15` |
| `validate_historical_season.py` | Full season script | `python scripts/validate_historical_season.py --season 2024-25` |

---

## Output Artifacts

After validation, the following will be generated:

1. **CSV Report:** `data/validation-results-2024-25.csv`
2. **Summary Metrics:** [DATA-QUALITY-METRICS.md](./DATA-QUALITY-METRICS.md)
3. **Issue Analysis:** [VALIDATION-RESULTS-SUMMARY.md](./VALIDATION-RESULTS-SUMMARY.md)
4. **Remediation Plan:** [PREVENTION-MECHANISMS.md](./PREVENTION-MECHANISMS.md)
