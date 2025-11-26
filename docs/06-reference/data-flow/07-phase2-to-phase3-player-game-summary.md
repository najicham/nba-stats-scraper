# Phase 2→3 Mapping: Player Game Summary

**File:** `docs/data-flow/07-phase2-to-phase3-player-game-summary.md`
**Created:** 2025-01-15
**Last Updated:** 2025-11-25
**Purpose:** Data mapping from Phase 2 raw tables to Phase 3 unified player boxscore analytics
**Audience:** Engineers implementing Phase 3 processors and debugging player stat transformations
**Status:** ✅ Production Ready - Implementation complete, all critical sources available

---

## 🚧 Current Deployment Status

**Implementation:** ✅ **COMPLETE**
- Phase 2 Processors: Multiple scrapers deployed (NBA.com gamebook, BDL, Big Ball Data, BettingPros)
- Phase 3 Processor: `data_processors/analytics/player_game_summary/player_game_summary_processor.py` (798 lines, 96 tests)
- Analytics Table: `nba_analytics.player_game_summary` (created, 72 fields)

**Blocker:** ✅ **NONE - Ready for deployment**
- ✅ `nba_raw.nbac_gamebook_player_stats` - EXISTS (primary stats source)
- ✅ `nba_raw.bdl_player_boxscores` - EXISTS (fallback source)
- ✅ `nba_raw.bigdataball_play_by_play` - EXISTS (shot zones primary)
- ✅ `nba_raw.nbac_play_by_play` - EXISTS (shot zones backup)
- ✅ `nba_raw.bettingpros_player_points_props` - EXISTS (prop lines backup)
- ✅ `nba_reference.nba_players_registry` - EXISTS (universal player IDs)

**Optional Sources (Missing but have fallbacks):**
- ❌ `nba_raw.odds_api_player_points_props` - MISSING (has fallback: BettingPros)
- Impact: Use BettingPros for prop lines instead (60-70% coverage, same as Odds API)

**Processing Strategy:**
- **Multi-pass architecture** - 3 passes to handle async data availability:
  - **Pass 1 (Immediate):** Core stats from NBA.com/BDL → Insert initial records
  - **Pass 2 (~4 hours):** Add shot zones from Big Ball Data/NBA.com PBP/estimation
  - **Pass 3 (Anytime):** Add prop results after game completion
- Uses MERGE (UPDATE or INSERT) to progressively enrich records
- Alternative: Single-pass processing (simpler but may miss late-arriving data)

**See:** `docs/processors/` for Phase 3 deployment procedures

---

## 📊 Executive Summary

This Phase 3 processor transforms raw player boxscore data from multiple Phase 2 sources into a **unified analytics table** with complete player performance stats, shot zone breakdowns, shot creation analysis, prop betting results, and advanced efficiency metrics. It's the most comprehensive player performance record in the pipeline.

**Processor:** `player_game_summary_processor.py`
**Output Table:** `nba_analytics.player_game_summary`
**Processing Strategy:** MERGE_UPDATE (multi-pass or single-pass)
**Update Frequency:** Post-game (Pass 1), then enrichment passes
**Version:** 2.0 (production-ready design with RegistryReader integration)

**Key Features:**
- **6 Phase 2 sources** with intelligent fallback logic
- **Universal player ID** via RegistryReader (batch lookup)
- **Shot zones** from play-by-play (paint, mid-range, three-point)
- **Shot creation** analysis (assisted vs unassisted field goals)
- **Prop betting results** with margin calculation
- **Advanced metrics** (TS%, eFG%, usage rate)
- **18 source tracking fields** (3 per source × 6 sources) per dependency tracking v4.0 spec
- **Multi-pass processing** handles async data availability

**Data Quality:** High - NBA.com gamebook is authoritative (~95% coverage), BDL provides 100% fallback coverage

---

## 🗂️ Raw Sources (Phase 2)

### Source Architecture

**Priority System:**
- **PRIMARY:** NBA.com Gamebook (~95% coverage, includes plus_minus, pre-converted minutes)
- **FALLBACK:** BDL Boxscores (100% coverage, basic stats only)
- **OPTIONAL 1:** Big Ball Data Play-by-Play (shot zones preferred - verified)
- **OPTIONAL 2:** BettingPros Player Props (prop lines backup - has opening line built-in)
- **BACKUP 1:** NBA.com Play-by-Play (shot zones if Big Ball unavailable - UNVERIFIED)
- **BACKUP 2:** Odds API Player Props (prop lines primary - MISSING, has fallback)

---

### Source 1: NBA.com Gamebook Player Stats (PRIMARY - ~95% Coverage)

**Table:** `nba_raw.nbac_gamebook_player_stats`
**Status:** ✅ **EXISTS**
**Update Frequency:** ~2 hours after game completion
**Dependency:** PRIMARY - Preferred source for all player statistics
**Priority:** Use first, fall back to BDL if unavailable

**Purpose:**
- Complete player statistics with plus/minus
- Pre-converted minutes (no parsing needed!)
- Name resolution tracking (built-in quality monitoring)
- Split rebounds (offensive and defensive tracked separately)

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| game_id | STRING | "20240101_BKN_MIL" (standardized) |
| game_date | DATE | Partition key |
| season_year | INT64 | 2024 = 2024-25 season |
| player_lookup | STRING | Normalized for matching |
| player_name | STRING | Final resolved name |
| team_abbr | STRING | Player's team |
| player_status | STRING | 'active', 'inactive', 'dnp' |
| name_resolution_confidence | FLOAT64 | 0.0-1.0 confidence score |
| minutes_decimal | FLOAT64 | ✅ Already converted to decimal! |
| plus_minus | INT64 | ✅ Only available in NBA.com! |
| points, assists, steals, blocks, turnovers, personal_fouls | INT64 | Basic stats |
| field_goals_made/attempted, three_pointers_made/attempted, free_throws_made/attempted | INT64 | Shooting stats |
| offensive_rebounds, defensive_rebounds, total_rebounds | INT64 | ✅ Split rebounds! |

**Key Advantages:**
- ✅ Pre-converted minutes: `minutes_decimal` already calculated
- ✅ Plus/minus stat: Only source with this critical metric
- ✅ Name resolution tracking: Built-in quality monitoring
- ✅ Split rebounds: Offensive and defensive tracked separately

**Quality Filtering:**
```sql
WHERE player_status = 'active'
  AND name_resolution_confidence >= 0.8
  AND (requires_manual_review IS NULL OR requires_manual_review = FALSE)
```

**Known Gaps:** ~5% of games don't produce gamebook (use BDL fallback)

---

### Source 2: BDL Player Boxscores (FALLBACK - 100% Coverage)

**Table:** `nba_raw.bdl_player_boxscores`
**Status:** ✅ **EXISTS**
**Update Frequency:** ~1 hour after game completion
**Dependency:** FALLBACK - Only use when NBA.com gamebook unavailable
**Priority:** Use only for games NOT in NBA.com gamebook (~5% of games)

**Purpose:**
- Comprehensive fallback coverage (99%+ of games)
- Faster update than NBA.com (~1 hour vs ~2 hours)
- Basic stats when gamebook unavailable

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| game_id | STRING | Standardized game ID |
| player_lookup | STRING | Join key |
| minutes | STRING | ⚠️ STRING format ("MM:SS" or "35") |
| points, assists, rebounds, steals, blocks, turnovers, personal_fouls | INT64 | Basic stats |
| field_goals_made/attempted, three_pointers_made/attempted, free_throws_made/attempted | INT64 | Shooting stats |

**Key Limitations:**
- ❌ No plus/minus: Not available in BDL data
- ❌ Minutes as STRING: Must parse "MM:SS" format
- ❌ Combined rebounds: Only `rebounds` total (splits may be NULL)

**When to Use:**
```sql
-- Only for games NOT in NBA.com gamebook
WHERE game_id NOT IN (
  SELECT DISTINCT game_id
  FROM nba_raw.nbac_gamebook_player_stats
  WHERE game_date BETWEEN @start_date AND @end_date
)
```

---

### Source 3: Big Ball Data Play-by-Play (OPTIONAL - Shot Zones Primary)

**Table:** `nba_raw.bigdataball_play_by_play`
**Status:** ✅ **EXISTS**
**Update Frequency:** ~2-4 hours after game completion
**Dependency:** OPTIONAL - Preferred source for shot zone data
**Priority:** Use first for shot zones (verified accurate)

**Purpose:**
- Shot zones (paint, mid-range, three-point) with distance data
- Shot creation analysis (assisted vs unassisted)
- Blocks by zone
- AND-1 tracking

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| game_id | STRING | Join key |
| player_1_lookup | STRING | Shooter |
| shot_made | BOOLEAN | TRUE if shot made |
| shot_type | STRING | "2PT", "3PT", "FT" |
| shot_distance | FLOAT64 | Distance in feet |
| player_2_role | STRING | "assist", "block", etc. |

**Zone Definitions:**
- **Paint:** `shot_distance <= 8 feet`
- **Mid-Range:** `8 < shot_distance <= 23 feet AND shot_type = '2PT'`
- **Three-Point:** `shot_type = '3PT'`

**Quality Flags:**
- `shot_zones_estimated = FALSE`
- `shot_zones_verified = TRUE`

---

### Source 4: BettingPros Player Props (OPTIONAL - Prop Lines Backup)

**Table:** `nba_raw.bettingpros_player_points_props`
**Status:** ✅ **EXISTS**
**Update Frequency:** Live (pre-game)
**Dependency:** OPTIONAL - Backup for prop betting lines
**Priority:** Use if Odds API unavailable (CURRENT SITUATION)

**Purpose:**
- Prop betting lines with opening line built-in
- Line movement tracking
- Best line flagging

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| game_date | DATE | Join key |
| player_lookup | STRING | Join key |
| points_line | NUMERIC | Current prop line |
| opening_line | NUMERIC | ✅ Built-in opening line! |
| bookmaker | STRING | Bookmaker name |
| is_best_line | BOOLEAN | Pre-calculated best line flag |

**Key Advantages Over Odds API:**
- ✅ Opening line tracking built-in (no MIN() aggregation needed)
- ✅ Line movement data automatic
- ✅ Best line flagging pre-calculated

**Prop Result Calculation:**
```python
if points >= points_line:
    over_under_result = 'OVER'
else:
    over_under_result = 'UNDER'

margin = float(points) - float(points_line)
```

---

### Source 5: NBA.com Play-by-Play (BACKUP - Shot Zones UNVERIFIED)

**Table:** `nba_raw.nbac_play_by_play`
**Status:** ✅ **EXISTS**
**Update Frequency:** ~2 hours after game completion
**Dependency:** BACKUP - Use only if Big Ball Data unavailable
**Priority:** Use only if `source_bbd_completeness_pct < 85%`

**Purpose:**
- Shot zones backup when Big Ball Data unavailable
- Same schema structure as Big Ball Data

**⚠️ IMPORTANT - UNVERIFIED:**
- Schema looks complete (all necessary fields present)
- Data quality UNKNOWN (needs validation vs Big Ball Data)
- Field population rates UNKNOWN
- Calculation accuracy UNKNOWN

**Quality Flags:**
- `shot_zones_estimated = FALSE`
- `shot_zones_verified = FALSE` (UNVERIFIED)
- `processed_with_issues = TRUE`

---

### Source 6: NBA Players Registry (OPTIONAL)

**Table:** `nba_reference.nba_players_registry`
**Status:** ✅ **EXISTS**
**Update Frequency:** Daily
**Dependency:** OPTIONAL - Universal player ID resolution
**Priority:** Use for all players (lenient mode - skip if not found)

**Purpose:**
- Universal player ID resolution across seasons
- Player metadata enrichment

**Integration:** Via RegistryReader (batch lookup)

---

## 🔄 Data Flow

### Multi-Pass Processing Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Pass 1: Core Stats (Immediate - ~1-2 hours after game)          │
│ NBA.com Gamebook (95%) → BDL Fallback (5%) → Core Analytics    │
│ • Basic stats (points, rebounds, assists, shooting)            │
│ • Plus/minus (NBA.com only)                                    │
│ • Minutes already converted to decimal (NBA.com)               │
│ • Universal player ID via RegistryReader (batch)               │
│ • Shot zones set to NULL (will update later)                   │
│ • Prop results set to NULL (will update later)                 │
│ Strategy: INSERT initial records                               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Pass 2: Shot Zones (~4 hours after game)                        │
│ Big Ball Data → NBA.com PBP → Estimation Fallback              │
│ • Paint/mid-range/three-point attempts & makes                │
│ • Assisted vs unassisted field goals                           │
│ • Shot creation rates                                          │
│ • shot_zones_estimated flag (if using estimation)             │
│ Strategy: MERGE UPDATE (enrich existing records)               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Pass 3: Prop Results (anytime after game)                       │
│ BettingPros (current) → Calculate Outcomes                     │
│ • Opening and closing lines                                    │
│ • Over/under result (OVER/UNDER)                               │
│ • Margin (actual points - line)                                │
│ • Line movement tracking                                       │
│ Strategy: MERGE UPDATE (enrich existing records)               │
└─────────────────────────────────────────────────────────────────┘
```

**MERGE Strategy:**
- Preserves `created_at` from Pass 1
- Updates `processed_at` on each pass
- Uses `COALESCE(source.field, target.field)` for additive updates

---

## 📋 Field Mappings Summary

### Output Schema: 72 Fields

**Core Identifiers (8 fields):**
- `player_lookup`, `universal_player_id`, `player_full_name`
- `game_id`, `game_date`, `team_abbr`, `opponent_team_abbr`, `season_year`

**Basic Performance (16 fields):**
- `points`, `minutes_played`, `assists`, `offensive_rebounds`, `defensive_rebounds`
- `steals`, `blocks`, `turnovers`, `personal_fouls`, `plus_minus`
- `fg_attempts`, `fg_makes`, `three_pt_attempts`, `three_pt_makes`
- `ft_attempts`, `ft_makes`

**Shot Zones (8 fields):**
- `paint_attempts`, `paint_makes`, `mid_range_attempts`, `mid_range_makes`
- `paint_blocks`, `mid_range_blocks`, `three_pt_blocks`, `and1_count`

**Shot Creation (2 fields):**
- `assisted_fg_makes`, `unassisted_fg_makes`

**Advanced Efficiency (5 fields):**
- `usage_rate` (deferred Phase 3.1), `ts_pct`, `efg_pct`, `starter_flag`, `win_flag`

**Prop Betting (7 fields):**
- `points_line`, `over_under_result`, `margin`
- `opening_line`, `line_movement`, `points_line_source`, `opening_line_source`

**Player Availability (2 fields):**
- `is_active`, `player_status`

**Source Tracking (18 fields):**
- 3 fields per source × 6 sources (per dependency tracking v4.0 spec):
  - `source_nbac_last_updated`, `source_nbac_rows_found`, `source_nbac_completeness_pct`
  - `source_bdl_last_updated`, `source_bdl_rows_found`, `source_bdl_completeness_pct`
  - `source_bbd_last_updated`, `source_bbd_rows_found`, `source_bbd_completeness_pct`
  - `source_odds_last_updated`, `source_odds_rows_found`, `source_odds_completeness_pct`
  - `source_nbac_pbp_last_updated`, `source_nbac_pbp_rows_found`, `source_nbac_pbp_completeness_pct`
  - `source_bp_last_updated`, `source_bp_rows_found`, `source_bp_completeness_pct`

**Data Quality (4 fields):**
- `data_quality_tier`, `primary_source_used`, `processed_with_issues`, `shot_zones_estimated`

**Processing Metadata (2 fields):**
- `created_at`, `processed_at`

---

## 🎯 Shot Zone Calculation Strategy

### Three-Tier Approach

**Tier 1: Big Ball Data (Preferred)**
- Source: `nba_raw.bigdataball_play_by_play`
- Aggregation: COUNT by zone with distance filters
- Quality: `shot_zones_estimated = FALSE`, `shot_zones_verified = TRUE`
- Validation: Total zone attempts should match FGA (±1 tolerance)

**Tier 2: NBA.com Play-by-Play (Backup - UNVERIFIED)**
- Source: `nba_raw.nbac_play_by_play`
- Use when: `source_bbd_completeness_pct < 85.0`
- Quality: `shot_zones_estimated = FALSE`, `shot_zones_verified = FALSE`
- Flag: `processed_with_issues = TRUE`

**Tier 3: Estimation Algorithm (Fallback)**
- Use when: Neither Big Ball Data nor NBA.com PBP available
- Method: League average zone distribution (47% paint, 53% mid-range of 2PT shots)
- Quality: `shot_zones_estimated = TRUE`, `shot_zones_verified = FALSE`
- Sets assisted/unassisted to NULL (cannot estimate)

---

## ⚠️ Known Issues & Edge Cases

### Issue 1: Minutes Parsing (BDL source)
**Problem:** BDL stores minutes as STRING ("35:24" or "35")
**Solution:** Parse "MM:SS" → decimal, NBA.com already has `minutes_decimal`

### Issue 2: Plus/Minus Availability
**Problem:** Only NBA.com has plus/minus (BDL doesn't)
**Solution:** Accept NULL for ~5% of records using BDL fallback

### Issue 3: NBA.com PBP Unverified
**Problem:** Haven't validated shot zone accuracy vs Big Ball Data
**Solution:** Mark `shot_zones_verified = FALSE`, `processed_with_issues = TRUE`

### Issue 4: Rookie Players (First Games)
**Problem:** Player in game but may not be in registry yet
**Solution:** RegistryReader lenient mode - skip if not found, log to unresolved table

### Issue 5: Player Recently Traded
**Problem:** Player shows up with new team
**Solution:** Universal player ID stays same, `team_abbr` shows new team

---

## ✅ Validation Rules

### Critical Validations (Reject Record)
- ✅ `player_lookup` IS NOT NULL
- ✅ `game_id` IS NOT NULL
- ✅ `team_abbr` IS NOT NULL
- ✅ `points` BETWEEN 0 AND 100
- ✅ `minutes_played` BETWEEN 0 AND 53

### Statistical Integrity Checks (Flag but Process)
- ⚠️ FGM > FGA → Flag `processed_with_issues = TRUE`
- ⚠️ Calculated points != actual points (±3 tolerance) → Flag issue
- ⚠️ Shot zones sum != FGA (±1 tolerance) → Flag issue
- ⚠️ Assisted + unassisted != FGM → Recalculate unassisted to force balance

---

## 📈 Success Criteria

**Processing Success:**
- ✅ Coverage: At least 95% of games produce analytics records
- ✅ Performance: Processing completes within 10 minutes for typical game day (15-20 games)
- ✅ Completeness: <5% of records have `processed_with_issues = TRUE`
- ✅ Registry Integration: <5% skip rate for players not in registry

**Data Quality Success:**
- ✅ Core Stats: 100% of records have points, minutes, team populated
- ✅ Shot Zones: 80%+ have actual zones (not estimated)
- ✅ Prop Lines: 60-70% have prop lines (expected coverage)
- ✅ Source Tracking: 100% of records have all 18 tracking fields populated
- ✅ Quality Tiers: 70%+ records are 'high' quality, <10% are 'low'

**Multi-Pass Success:**
- ✅ Pass 1: 100% completion within 2 hours of game end
- ✅ Pass 2: 80%+ shot zones added within 6 hours of game end
- ✅ Pass 3: 100% prop results calculated within 12 hours of game end
- ✅ MERGE: No duplicate records, proper update behavior

---

## 🔗 Related Documentation

**Processor Implementation:**
- Code: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
- RegistryReader: `shared/utils/player_registry.py`

**Phase 2 Dependencies:**
- Schema: Run `bq show --schema nba_raw.nbac_gamebook_player_stats`
- Schema: Run `bq show --schema nba_raw.bdl_player_boxscores`
- Schema: Run `bq show --schema nba_raw.bigdataball_play_by_play`

**Dependency Tracking:**
- Spec: Dependency tracking v4.0 (3 fields per source)

**Monitoring:**
- `docs/monitoring/` - Data quality metrics for Phase 3

---

**Document Version:** 2.0
**Status:** ✅ Production Ready - All critical sources available, ready for deployment
**Next Steps:** Deploy Phase 3 processor, run backfill for historical seasons
