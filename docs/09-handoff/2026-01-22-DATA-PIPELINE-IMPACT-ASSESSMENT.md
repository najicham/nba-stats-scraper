# Data Pipeline Impact Assessment

**Date:** January 22, 2026
**Purpose:** Reference document for understanding data dependencies and cascade effects
**Use Case:** When validating data quality or investigating missing/bad data

---

## Executive Summary

A gap in `nbac_team_boxscore` raw data (454 games missing from Oct-Dec 2025) caused cascade contamination through the entire pipeline, resulting in:
- 29% of team defense records missing paint/zone data
- **100% of player_composite_factors having invalid opponent_strength_score**
- Degraded ML features and predictions

---

## Data Dependency Chain

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            RAW LAYER (Phase 1)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  nbac_team_boxscore ──────┬──► team_offense_game_summary                    │
│  (team stats per game)    │                                                  │
│                           └──► team_defense_game_summary                     │
│                                  (paint_attempts, mid_range, 3pt zones)      │
│                                                                              │
│  nbac_gamebook_player_stats ──► player_game_summary                         │
│  (individual player stats)       (points, rebounds, assists, etc.)          │
│                                                                              │
│  nbac_schedule ──────────────► upcoming_team_game_context                   │
│  (game schedule)                upcoming_player_game_context                 │
│                                                                              │
│  odds_api_game_lines ────────► upcoming_team_game_context                   │
│  nbac_injury_report ─────────► upcoming_player_game_context                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ANALYTICS LAYER (Phase 3)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  team_offense_game_summary ────► team_defense_zone_analysis                 │
│  team_defense_game_summary ────► team_defense_zone_analysis                 │
│                                  player_shot_zone_analysis                   │
│                                                                              │
│  player_game_summary ──────────► player_daily_cache                         │
│                                  player_shot_zone_analysis                   │
│                                                                              │
│  upcoming_team_game_context ───► player_composite_factors                   │
│  upcoming_player_game_context ─► player_composite_factors                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PRECOMPUTE LAYER (Phase 4)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  team_defense_zone_analysis ───► ml_feature_store_v2                        │
│  player_shot_zone_analysis ────► ml_feature_store_v2                        │
│  player_daily_cache ───────────► ml_feature_store_v2                        │
│  player_composite_factors ─────► ml_feature_store_v2                        │
│                                  (opponent_strength_score, matchup scores)   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PREDICTION LAYER (Phase 5)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  ml_feature_store_v2 ──────────► predictions                                │
│                                  (points, rebounds, assists over/under)      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Impact Matrix: What Breaks When Data Is Missing

### If `nbac_team_boxscore` is missing:

| Downstream Table | Impact | Severity |
|------------------|--------|----------|
| `team_offense_game_summary` | Missing team offensive stats | HIGH |
| `team_defense_game_summary` | Missing paint/mid-range/3pt zone data | HIGH |
| `team_defense_zone_analysis` | Incomplete zone defense calculations | HIGH |
| `player_composite_factors` | `opponent_strength_score = 0` | **CRITICAL** |
| `ml_feature_store_v2` | Bad `opp_def_*` features | **CRITICAL** |
| Predictions | Using incorrect opponent strength | **CRITICAL** |

### If `nbac_gamebook_player_stats` is missing:

| Downstream Table | Impact | Severity |
|------------------|--------|----------|
| `player_game_summary` | Missing individual player stats | HIGH |
| `player_daily_cache` | Stale rolling averages | MEDIUM |
| `player_shot_zone_analysis` | Missing shot zone breakdowns | HIGH |
| `ml_feature_store_v2` | Bad player stat features | HIGH |

### If `nbac_schedule` is missing/stale:

| Downstream Table | Impact | Severity |
|------------------|--------|----------|
| `upcoming_team_game_context` | No context for upcoming games | **CRITICAL** |
| `upcoming_player_game_context` | No context for upcoming games | **CRITICAL** |
| Predictions | Cannot generate (blocked) | **CRITICAL** |

### If `odds_api_game_lines` is missing:

| Downstream Table | Impact | Severity |
|------------------|--------|----------|
| `upcoming_team_game_context` | Missing spread/total data | MEDIUM |
| `player_composite_factors` | Missing Vegas-implied metrics | MEDIUM |

### If `nbac_injury_report` is missing:

| Downstream Table | Impact | Severity |
|------------------|--------|----------|
| `upcoming_player_game_context` | Missing injury status | MEDIUM |
| `player_composite_factors` | Missing injury adjustments | MEDIUM |

---

## Validation Queries

### 1. Check Raw Layer Coverage

```sql
-- Compare expected vs actual game counts
WITH expected AS (
  SELECT game_date, COUNT(DISTINCT game_id) as expected
  FROM `nba_raw.nbac_gamebook_player_stats`
  WHERE game_date >= "2025-10-22"
  GROUP BY game_date
),
actual AS (
  SELECT game_date, COUNT(DISTINCT nba_game_id) as actual
  FROM `nba_raw.nbac_team_boxscore`
  WHERE game_date >= "2025-10-22"
  GROUP BY game_date
)
SELECT
  e.game_date,
  e.expected,
  COALESCE(a.actual, 0) as actual,
  e.expected - COALESCE(a.actual, 0) as missing
FROM expected e
LEFT JOIN actual a ON e.game_date = a.game_date
WHERE COALESCE(a.actual, 0) < e.expected
ORDER BY game_date;
```

### 2. Check Phase 3 Cascade Contamination

```sql
-- Check team_defense_game_summary for zero/null critical fields
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(opp_paint_attempts = 0 OR opp_paint_attempts IS NULL) as bad_paint,
  COUNTIF(opp_mid_range_attempts = 0 OR opp_mid_range_attempts IS NULL) as bad_midrange,
  ROUND(100.0 * COUNTIF(opp_paint_attempts = 0) / COUNT(*), 1) as pct_bad
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date >= "2025-10-22"
GROUP BY game_date
HAVING pct_bad > 0
ORDER BY game_date;
```

### 3. Check Phase 4 Cascade Contamination

```sql
-- Check player_composite_factors for zero opponent_strength_score
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(opponent_strength_score = 0 OR opponent_strength_score IS NULL) as bad_records,
  ROUND(100.0 * COUNTIF(opponent_strength_score = 0) / COUNT(*), 1) as pct_bad
FROM `nba_precompute.player_composite_factors`
WHERE game_date >= "2025-10-22"
GROUP BY game_date
HAVING pct_bad > 0
ORDER BY game_date;
```

### 4. Check Context Tables for Gaps

```sql
-- Check upcoming_team_game_context for gaps
SELECT
  MAX(game_date) as last_date,
  DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
FROM `nba_analytics.upcoming_team_game_context`;

-- Should be 0-1 days stale for today's games
```

### 5. Full Pipeline Coverage Summary

```sql
SELECT
  'nbac_team_boxscore' as table_name,
  COUNT(DISTINCT game_date) as dates,
  MIN(game_date) as min_date,
  MAX(game_date) as max_date
FROM `nba_raw.nbac_team_boxscore` WHERE game_date >= "2025-10-22"
UNION ALL
SELECT 'team_defense_game_summary', COUNT(DISTINCT game_date), MIN(game_date), MAX(game_date)
FROM `nba_analytics.team_defense_game_summary` WHERE game_date >= "2025-10-22"
UNION ALL
SELECT 'player_composite_factors', COUNT(DISTINCT game_date), MIN(game_date), MAX(game_date)
FROM `nba_precompute.player_composite_factors` WHERE game_date >= "2025-10-22"
UNION ALL
SELECT 'ml_feature_store_v2', COUNT(DISTINCT game_date), MIN(game_date), MAX(game_date)
FROM `nba_predictions.ml_feature_store_v2` WHERE game_date >= "2025-10-22"
ORDER BY table_name;
```

---

## Current State (January 22, 2026)

### Coverage Summary

| Layer | Table | Expected Dates | Actual Dates | Coverage |
|-------|-------|----------------|--------------|----------|
| RAW | nbac_team_boxscore | 92 | 27 | 29% ❌ |
| RAW | nbac_gamebook_player_stats | 92 | 42 | 46% ⚠️ |
| PHASE 3 | team_offense_game_summary | 92 | 90 | 98% ✅ |
| PHASE 3 | team_defense_game_summary | 92 | 90 | 98% ✅ |
| PHASE 3 | upcoming_team_game_context | 92 | 77 | 84% ⚠️ |
| PHASE 4 | team_defense_zone_analysis | 92 | 66 | 72% ⚠️ |
| PHASE 4 | player_composite_factors | 92 | 78 | 85% ⚠️ |
| PHASE 5 | ml_feature_store_v2 | 92 | 77 | 84% ⚠️ |

### Data Quality Issues

| Table | Field | Issue | % Affected |
|-------|-------|-------|------------|
| team_defense_game_summary | opp_paint_attempts | = 0 or NULL | 29.2% |
| team_defense_game_summary | opp_mid_range_attempts | = 0 or NULL | 29.2% |
| player_composite_factors | opponent_strength_score | = 0 | **100%** |

### Missing Raw Data

- **nbac_team_boxscore**: ~454 games missing (Oct 22 - Dec 26, 2025)
- **nbac_gamebook_player_stats**: ~50 dates missing

---

## Backfill Order (Dependency-Safe)

When backfilling, follow this order to avoid cascade contamination:

1. **Raw Layer**
   - `nbac_team_boxscore` (backfill scraper)
   - `nbac_gamebook_player_stats` (if needed)

2. **Phase 3 Processors** (after raw is complete)
   - `TeamOffenseGameSummaryProcessor`
   - `TeamDefenseGameSummaryProcessor`
   - `PlayerGameSummaryProcessor`
   - `UpcomingTeamGameContextProcessor`
   - `UpcomingPlayerGameContextProcessor`

3. **Phase 4 Processors** (after Phase 3 is complete)
   - `TeamDefenseZoneAnalysisProcessor`
   - `PlayerShotZoneAnalysisProcessor`
   - `PlayerDailyCacheProcessor`
   - `PlayerCompositeFactorsProcessor`

4. **Phase 5 Processors** (after Phase 4 is complete)
   - `MLFeatureStoreProcessor`

5. **Validation**
   - Run `scripts/validate_cascade_contamination.py`
   - Run `bin/spot_check_features.py`

---

## Staleness Thresholds (from processors)

| Source Table | Warning Age | Fail Age | Used By |
|--------------|-------------|----------|---------|
| nbac_schedule | 12h | 36h | upcoming_team_game_context |
| odds_api_game_lines | 4h | 12h | upcoming_team_game_context |
| nbac_injury_report | 8h | 24h | upcoming_player_game_context |
| team_defense_game_summary | 24h | 48h | team_defense_zone_analysis |
| player_game_summary | 24h | 48h | player_daily_cache |

---

## Quick Diagnostic Commands

```bash
# Check cascade contamination
PYTHONPATH=. python scripts/validate_cascade_contamination.py \
  --start-date 2025-10-22 --end-date 2026-01-22

# Spot check ML features
PYTHONPATH=. python bin/spot_check_features.py --date 2026-01-21 --count 10

# Validate pipeline completeness
PYTHONPATH=. python bin/validate_pipeline.py today

# Check team boxscore coverage
bq query --use_legacy_sql=false "
  SELECT game_date, COUNT(DISTINCT nba_game_id) as games
  FROM nba_raw.nbac_team_boxscore
  WHERE game_date >= '2025-10-22'
  GROUP BY 1 ORDER BY 1"
```

---

## Related Documentation

- `docs/09-handoff/2026-01-22-NBA-API-V2-TO-V3-MIGRATION.md` - V2→V3 API fix
- `docs/09-handoff/2026-01-22-PROXY-INFRASTRUCTURE-AND-VALIDATION.md` - Proxy fixes
- `docs/08-projects/current/data-cascade-architecture/` - Cascade architecture docs
- `scripts/validate_cascade_contamination.py` - Contamination checker
- `bin/spot_check_features.py` - Feature validation tool

---

## Action Items from This Assessment

1. **IMMEDIATE**: Backfill 454 missing `nbac_team_boxscore` games (Oct-Dec 2025)
2. **AFTER BACKFILL**: Re-run Phase 3 processors to fix team_defense_game_summary
3. **AFTER PHASE 3**: Re-run Phase 4 processors to fix player_composite_factors
4. **VALIDATE**: Run cascade contamination check to confirm fix

---

**Document Status:** Complete - Use as reference for future validation sessions
