# Data Source Fallback Strategies

**Created:** 2025-11-30
**Last Updated:** 2025-11-30
**Purpose:** Document implemented fallback logic and assess need for additional fallbacks

---

## Fallback Status Summary

| Data Type | Primary Source | Fallback Source | Status | Impact |
|-----------|---------------|-----------------|--------|--------|
| Player Props | Odds API | BettingPros | ✅ **IMPLEMENTED** | 40% → 99.7% |
| Player Boxscores | NBA.com Gamebook | BDL Boxscores | ✅ **IMPLEMENTED** | 95% → 99%+ |
| Team Boxscores | NBA.com | (aggregate from players) | **NOT NEEDED** | 100% coverage |
| Game Lines | Odds API | None available | **NOT NEEDED** | 99.1% coverage |
| Schedule | NBA.com | ESPN (partial) | ✅ **IMPLEMENTED** | 100% coverage |
| Injuries | BDL | None | **NOT NEEDED** | Supplementary data |

---

## Implemented Fallbacks

### 1. Player Props: Odds API → BettingPros ✅

**Processor:** `upcoming_player_game_context` (v3.1)

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Implementation:**
```python
def _extract_players_with_props(self):
    # Step 1: Try Odds API first
    df = query_odds_api(target_date)

    # Step 2: If empty, fall back to BettingPros
    if df.empty:
        logger.info(f"No Odds API data for {target_date}, using BettingPros fallback")
        self._props_source = 'bettingpros'
        df = self._extract_players_from_bettingpros()
```

**Coverage Improvement:** 40% → 99.7%

**Schema Differences Handled:**
- BettingPros lacks `game_id` → JOIN with `nbac_schedule`
- BettingPros lacks `home_team_abbr`/`away_team_abbr` → Derived from schedule
- BettingPros has `opening_line` field → Used directly (vs deriving from snapshots)

**Date Added:** 2025-11-30

---

### 2. Player Boxscores: NBA.com → BDL ✅

**Processor:** `player_game_summary`

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Implementation:**
```sql
-- Multi-source UNION with preference order
WITH combined_data AS (
    -- Source 1: NBA.com Gamebook (preferred)
    SELECT *, 'nbac_gamebook' as primary_source
    FROM nba_raw.nbac_gamebook_player_stats
    WHERE game_date BETWEEN ...

    UNION ALL

    -- Source 2: BDL Boxscores (fallback)
    SELECT *, 'bdl_boxscores' as primary_source
    FROM nba_raw.bdl_player_boxscores
    WHERE game_date BETWEEN ...
      AND game_id NOT IN (SELECT DISTINCT game_id FROM nbac_gamebook_player_stats)
)
```

**Coverage Improvement:** 95% → 99%+

---

### 3. Schedule: NBA.com → ESPN ✅

**Processor:** `upcoming_team_game_context`

**File:** `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`

**Note:** Limited fallback for schedule gaps, but `nbac_schedule` has 100% coverage so rarely triggered.

---

## Fallbacks NOT Needed

### Team Boxscores

**Primary Source:** `nbac_team_boxscore`
**Coverage:** 100%
**Status:** No fallback needed

**Potential Fallback (if ever needed):**
Could aggregate from player boxscores:
```sql
SELECT
  game_id,
  team_abbr,
  SUM(points) as team_points,
  SUM(rebounds) as team_rebounds,
  SUM(assists) as team_assists,
  -- etc
FROM nba_raw.bdl_player_boxscores
GROUP BY game_id, team_abbr
```

**Why Not Implemented:** Primary source has 100% coverage.

---

### Game Lines (Spreads/Totals)

**Primary Source:** `odds_api_game_lines`
**Coverage:** 99.1%
**Status:** No fallback needed

**Why No Fallback:**
1. 99.1% coverage is excellent
2. Missing 6 dates are ALL All-Star Weekend (exhibition games - no betting expected)
3. **No BettingPros game lines table exists** - only player props

---

### Injuries

**Primary Source:** `bdl_injuries`
**Coverage:** 95%+
**Status:** No fallback needed

**Why No Fallback:**
1. Injury data is supplementary (not critical path)
2. Missing injury data doesn't break processing
3. No alternative injury source with better coverage

---

## Fallback Decision Framework

When evaluating whether to add a fallback:

### Add Fallback If:

1. **Coverage gap > 5%** - Primary source missing significant data
2. **Data is DRIVER** - Without it, processor outputs nothing
3. **Fallback source exists** - Alternative with better coverage
4. **Schema mappable** - Can reasonably map fields between sources

### Don't Add Fallback If:

1. **Coverage > 95%** - Primary source is comprehensive
2. **Data is OPTIONAL** - Missing data doesn't break processing
3. **No alternative source** - Nothing to fall back to
4. **Schema incompatible** - Too complex to map fields

---

## Fallback Implementation Checklist

When implementing a new fallback:

- [ ] Verify primary source coverage is actually low
- [ ] Verify fallback source has better coverage
- [ ] Document schema differences
- [ ] Implement fallback query/logic
- [ ] Add logging to track which source was used
- [ ] Test with date that only has fallback data
- [ ] Update this documentation

---

## Processors Without Fallbacks (Assessment)

| Processor | Primary Source | Fallback Needed? | Reason |
|-----------|---------------|------------------|--------|
| `team_offense_game_summary` | `nbac_team_boxscore` | **NO** | 100% coverage |
| `team_defense_game_summary` | `nbac_team_boxscore` | **NO** | 100% coverage |
| `upcoming_team_game_context` | `odds_api_game_lines` | **NO** | 99.1% (All-Star gaps only) |
| `team_defense_zone_analysis` | Phase 3 analytics | **NO** | Depends on upstream |
| `player_shot_zone_analysis` | Phase 3 analytics | **NO** | Depends on upstream |
| `player_composite_factors` | Phase 3 analytics | **NO** | Depends on upstream |
| `player_daily_cache` | Phase 3 analytics | **NO** | Depends on upstream |
| `ml_feature_store` | Phase 4 precompute | **Partial** | Has Phase 3 fallback |

---

## Historical Context

### Why Odds API Has Low Player Props Coverage

Odds API player props collection started late in our data collection timeline. Historical backfill was limited.

### Why BettingPros Has Better Coverage

BettingPros data was backfilled comprehensively from historical sources, providing 99.7% coverage back to 2021.

### Why No BettingPros Game Lines

BettingPros API focuses on player props. Game lines (spreads/totals) come from different APIs that we didn't integrate for historical data.

---

## Change Log

| Date | Change |
|------|--------|
| 2025-11-30 | Initial document with BettingPros player props fallback |
