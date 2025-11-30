# Data Source Coverage Matrix

**Created:** 2025-11-30
**Last Updated:** 2025-11-30
**Purpose:** Document historical coverage for all raw data sources
**Period Analyzed:** 2021-10-01 to 2024-06-30 (4 seasons)

---

## Coverage Summary

### Player Statistics

| Table | Dates | Coverage | Notes |
|-------|-------|----------|-------|
| `nbac_gamebook_player_stats` | ~630 | 98.7% | NBA.com official stats |
| `bdl_player_boxscores` | 631 | 98.9% | BigDataBall backup |

**Fallback**: `nbac_gamebook_player_stats` → `bdl_player_boxscores`

### Team Statistics

| Table | Dates | Coverage | Notes |
|-------|-------|----------|-------|
| `nbac_team_boxscore` | 638 | **100%** | NBA.com official stats |

**Fallback**: None needed (100% coverage)

### Betting Data - Player Props

| Table | Dates | Coverage | Notes |
|-------|-------|----------|-------|
| `odds_api_player_points_props` | 271 | **40%** | Odds API (limited historical) |
| `bettingpros_player_points_props` | 673 | **99.7%** | BettingPros (comprehensive) |

**Fallback**: `odds_api_player_points_props` → `bettingpros_player_points_props` ✅ **IMPLEMENTED**

### Betting Data - Game Lines (Spreads/Totals)

| Table | Dates | Coverage | Notes |
|-------|-------|----------|-------|
| `odds_api_game_lines` | 632 | **99.1%** | Spreads and totals |

**Missing Dates** (6 total - All-Star Weekend):
- 2022-02-18, 2022-02-20
- 2023-02-17, 2023-02-19
- 2024-02-16, 2024-02-18

**Fallback**: None needed (99.1% coverage, missing = exhibition games)

### Schedule Data

| Table | Dates | Coverage | Notes |
|-------|-------|----------|-------|
| `nbac_schedule` | 638 | **100%** | NBA.com official schedule |

**Fallback**: None needed (100% coverage)

### Injury Data

| Table | Dates | Coverage | Notes |
|-------|-------|----------|-------|
| `bdl_injuries` | ~600+ | 95%+ | BigDataBall injury reports |

**Fallback**: None needed (injury data is supplementary)

---

## Coverage by Season

### Season 2021-22 (Oct 2021 - Jun 2022)

| Data Type | Primary | Fallback | Effective Coverage |
|-----------|---------|----------|-------------------|
| Player Props | 0% (Odds API) | 100% (BettingPros) | **100%** |
| Game Lines | 99%+ | - | 99%+ |
| Team Boxscores | 100% | - | 100% |
| Player Boxscores | 98%+ | 99%+ (BDL) | **99%+** |

### Season 2022-23 (Oct 2022 - Jun 2023)

| Data Type | Primary | Fallback | Effective Coverage |
|-----------|---------|----------|-------------------|
| Player Props | ~40% (Odds API) | 100% (BettingPros) | **100%** |
| Game Lines | 99%+ | - | 99%+ |
| Team Boxscores | 100% | - | 100% |
| Player Boxscores | 98%+ | 99%+ (BDL) | **99%+** |

### Season 2023-24 (Oct 2023 - Jun 2024)

| Data Type | Primary | Fallback | Effective Coverage |
|-----------|---------|----------|-------------------|
| Player Props | ~60% (Odds API) | 100% (BettingPros) | **100%** |
| Game Lines | 99%+ | - | 99%+ |
| Team Boxscores | 100% | - | 100% |
| Player Boxscores | 98%+ | 99%+ (BDL) | **99%+** |

### Season 2024-25 (Current)

| Data Type | Primary | Fallback | Effective Coverage |
|-----------|---------|----------|-------------------|
| Player Props | 95%+ (Odds API) | 100% (BettingPros) | **100%** |
| Game Lines | 99%+ | - | 99%+ |
| Team Boxscores | 100% | - | 100% |
| Player Boxscores | 99%+ | 99%+ (BDL) | **99%+** |

---

## BettingPros Tables Available

These tables exist in `nba_raw`:

| Table | Purpose | Has Fallback Logic? |
|-------|---------|---------------------|
| `bettingpros_player_points_props` | Player points props | ✅ Used in `upcoming_player_game_context` |
| `bettingpros_props_best_lines` | Best line aggregation | Not used as fallback |
| `bettingpros_props_recent` | Recent props snapshot | Not used as fallback |
| `bettingpros_props_validated` | Validated player props | Not used as fallback |

**Note**: No BettingPros game lines (spreads/totals) table exists. Only player props.

---

## BigDataBall Tables Available

| Table | Purpose | Has Fallback Logic? |
|-------|---------|---------------------|
| `bdl_player_boxscores` | Player boxscore stats | ✅ Used in `player_game_summary` |
| `bdl_injuries` | Injury reports | Primary source (no fallback needed) |
| `bdl_standings` | League standings | Primary source (no fallback needed) |
| `bdl_active_players_current` | Active roster | Primary source (no fallback needed) |

**Note**: No `bdl_team_boxscores` table exists. Team stats must come from `nbac_team_boxscore` or be aggregated from player boxscores.

---

## Coverage Queries

### Check All Source Coverage

```sql
-- Run this to verify current coverage
SELECT
  'odds_api_player_points_props' as source,
  COUNT(DISTINCT game_date) as dates,
  ROUND(COUNT(DISTINCT game_date) * 100.0 / 675, 1) as pct
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date BETWEEN '2021-10-01' AND '2024-06-30'

UNION ALL

SELECT
  'bettingpros_player_points_props',
  COUNT(DISTINCT game_date),
  ROUND(COUNT(DISTINCT game_date) * 100.0 / 675, 1)
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE game_date BETWEEN '2021-10-01' AND '2024-06-30'

UNION ALL

SELECT
  'odds_api_game_lines',
  COUNT(DISTINCT game_date),
  ROUND(COUNT(DISTINCT game_date) * 100.0 / 638, 1)
FROM `nba-props-platform.nba_raw.odds_api_game_lines`
WHERE game_date BETWEEN '2021-10-01' AND '2024-06-30'

UNION ALL

SELECT
  'nbac_team_boxscore',
  COUNT(DISTINCT game_date),
  ROUND(COUNT(DISTINCT game_date) * 100.0 / 638, 1)
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
WHERE game_date BETWEEN '2021-10-01' AND '2024-06-30'

UNION ALL

SELECT
  'bdl_player_boxscores',
  COUNT(DISTINCT game_date),
  ROUND(COUNT(DISTINCT game_date) * 100.0 / 638, 1)
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date BETWEEN '2021-10-01' AND '2024-06-30'

ORDER BY source
```

---

## Key Insights

1. **Player Props was the critical gap** - Without BettingPros fallback, only 40% of historical dates would have player prop context

2. **All-Star Weekend has no betting lines** - This is expected for exhibition games

3. **Team boxscores have 100% coverage** - No fallback needed

4. **BDL provides excellent backup for player stats** - 98.9% coverage complements NBA.com data

5. **No BettingPros game lines exist** - Can't add fallback for spreads/totals even if we wanted to

---

## Change Log

| Date | Change |
|------|--------|
| 2025-11-30 | Initial document created |
| 2025-11-30 | Added BettingPros fallback implementation note |
