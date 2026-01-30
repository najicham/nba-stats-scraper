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
- `nba_predictions.prediction_grades`

**Metrics:**
- Grading coverage percentage
- Win rate by system
- Ungraded predictions

**Acceptable Thresholds:**
- Grading coverage: ≥80%

**Query Template:**
```sql
-- Phase 6 Grading Analysis
SELECT
  g.game_date,
  COUNT(DISTINCT g.prediction_id) as graded,
  COUNT(DISTINCT p.id) as total_predictions,
  ROUND(100.0 * COUNT(DISTINCT g.prediction_id) / NULLIF(COUNT(DISTINCT p.id), 0), 1) as grading_pct
FROM `nba-props-platform.nba_predictions.prediction_grades` g
RIGHT JOIN `nba-props-platform.nba_predictions.player_prop_predictions` p
  ON g.prediction_id = p.id
WHERE p.game_date BETWEEN '2024-10-22' AND '2025-06-22'
GROUP BY g.game_date
ORDER BY g.game_date
```

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
