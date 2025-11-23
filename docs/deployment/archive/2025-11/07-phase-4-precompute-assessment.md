# Phase 4 Precompute: Smart Patterns Assessment

**Created:** 2025-11-21 17:50:00 PST
**Last Updated:** 2025-11-21 18:15:00 PST
**Status:** ✅ Schema Updates Complete - Ready for BigQuery Deployment
**Purpose:** Design hash column strategy for Phase 4 precompute tables

---

## 📊 Phase 4 Precompute Tables (4 Total)

### 1. team_defense_zone_analysis
- **Dataset:** nba_precompute
- **Purpose:** Team defensive performance by shot zone (last 15 games rolling)
- **Schedule:** Nightly at 11:00 PM (runs FIRST in Phase 4)
- **Processing Strategy:** MERGE_UPDATE
- **Dependencies:**
  - Phase 3: `nba_analytics.team_defense_game_summary` (CRITICAL)
- **Current State:** ✅ Has `processed_at`, ❌ Missing hash columns

### 2. player_shot_zone_analysis
- **Dataset:** nba_precompute
- **Purpose:** Player shot distribution and efficiency by court zone (last 10 games)
- **Schedule:** Nightly at 11:15 PM (after team defense)
- **Processing Strategy:** MERGE_UPDATE
- **Dependencies:**
  - Phase 3: `nba_analytics.player_game_summary` (CRITICAL)
- **Current State:** ✅ Has `processed_at`, ❌ Missing hash columns

### 3. player_daily_cache
- **Dataset:** nba_precompute
- **Purpose:** Daily snapshot of player data (speeds up line change updates 2000x)
- **Schedule:** Nightly at 11:45 PM (after composite factors)
- **Processing Strategy:** MERGE_UPDATE
- **Dependencies:**
  - Phase 3: `nba_analytics.player_game_summary` (CRITICAL)
  - Phase 3: `nba_analytics.team_offense_game_summary` (CRITICAL)
- **Current State:** ✅ Has `processed_at`, ❌ Missing hash columns

### 4. player_composite_factors
- **Dataset:** nba_precompute
- **Purpose:** Pre-calculated composite adjustment factors for player predictions
- **Schedule:** Nightly at 11:30 PM (runs LAST in Phase 4 - depends on other precompute)
- **Processing Strategy:** MERGE_UPDATE
- **Dependencies:**
  - Phase 3: `nba_analytics.upcoming_player_game_context` (CRITICAL)
  - Phase 3: `nba_analytics.upcoming_team_game_context` (CRITICAL)
  - Phase 4: `nba_precompute.player_shot_zone_analysis` (must complete first)
  - Phase 4: `nba_precompute.team_defense_zone_analysis` (must complete first)
- **Current State:** ✅ Has `processed_at`, ❌ Missing hash columns

---

## 🎯 Pattern Strategy for Phase 4

### Both Patterns Needed

Phase 4 tables need **BOTH** smart patterns:

1. **Smart Reprocessing** (like Phase 3)
   - Read upstream Phase 3 hash values
   - Skip processing if upstream data unchanged
   - Expected skip rate: 30-50%
   - **Why:** Phase 4 depends on Phase 3 analytics tables

2. **Smart Idempotency** (like Phase 2)
   - Compute hash of own output
   - Skip BigQuery writes if data unchanged
   - Expected skip rate: 20-40%
   - **Why:** Even if inputs change, computed outputs may be stable

### Processing Flow Example

**team_defense_zone_analysis:**
```
1. Read source_team_defense_hash from nba_analytics.team_defense_game_summary
2. Compare to previous run's source hash
3. IF unchanged → Skip processing (Smart Reprocessing)
4. IF changed → Process data
5. Compute data_hash of output
6. IF data_hash unchanged → Skip BigQuery write (Smart Idempotency)
7. IF data_hash changed → Write to BigQuery with new hash
```

---

## 📐 Hash Column Design

### Required Hash Columns Per Table

**1. team_defense_zone_analysis**
```sql
-- Smart Idempotency
data_hash STRING,                           -- SHA256 of meaningful output fields

-- Smart Reprocessing (1 upstream source)
source_team_defense_hash STRING,            -- Hash from team_defense_game_summary
source_team_defense_last_updated TIMESTAMP, -- When source was last updated
source_team_defense_rows_found INT64,       -- Number of source rows found
source_team_defense_completeness_pct NUMERIC(5,2), -- Data completeness %
```

**2. player_shot_zone_analysis**
```sql
-- Smart Idempotency
data_hash STRING,                           -- SHA256 of meaningful output fields

-- Smart Reprocessing (1 upstream source)
source_player_game_hash STRING,             -- Hash from player_game_summary
source_player_game_last_updated TIMESTAMP,  -- When source was last updated
source_player_game_rows_found INT64,        -- Number of source rows found
source_player_game_completeness_pct NUMERIC(5,2), -- Data completeness %
```

**3. player_daily_cache**
```sql
-- Smart Idempotency
data_hash STRING,                           -- SHA256 of meaningful output fields

-- Smart Reprocessing (2 upstream sources)
source_player_game_hash STRING,             -- Hash from player_game_summary
source_player_game_last_updated TIMESTAMP,
source_player_game_rows_found INT64,
source_player_game_completeness_pct NUMERIC(5,2),

source_team_offense_hash STRING,            -- Hash from team_offense_game_summary
source_team_offense_last_updated TIMESTAMP,
source_team_offense_rows_found INT64,
source_team_offense_completeness_pct NUMERIC(5,2),
```

**4. player_composite_factors**
```sql
-- Smart Idempotency
data_hash STRING,                           -- SHA256 of meaningful output fields

-- Smart Reprocessing (4 upstream sources: 2 Phase 3, 2 Phase 4)
source_upcoming_player_hash STRING,         -- Hash from upcoming_player_game_context
source_upcoming_player_last_updated TIMESTAMP,
source_upcoming_player_rows_found INT64,
source_upcoming_player_completeness_pct NUMERIC(5,2),

source_upcoming_team_hash STRING,           -- Hash from upcoming_team_game_context
source_upcoming_team_last_updated TIMESTAMP,
source_upcoming_team_rows_found INT64,
source_upcoming_team_completeness_pct NUMERIC(5,2),

source_player_shot_zone_hash STRING,        -- Hash from player_shot_zone_analysis (Phase 4!)
source_player_shot_zone_last_updated TIMESTAMP,
source_player_shot_zone_rows_found INT64,
source_player_shot_zone_completeness_pct NUMERIC(5,2),

source_team_defense_zone_hash STRING,       -- Hash from team_defense_zone_analysis (Phase 4!)
source_team_defense_zone_last_updated TIMESTAMP,
source_team_defense_zone_rows_found INT64,
source_team_defense_zone_completeness_pct NUMERIC(5,2),
```

### Total Hash Columns to Add

| Table | data_hash | Source Hashes | Total New Columns |
|-------|-----------|---------------|-------------------|
| team_defense_zone_analysis | 1 | 4 (1 source × 4 fields) | 5 |
| player_shot_zone_analysis | 1 | 4 (1 source × 4 fields) | 5 |
| player_daily_cache | 1 | 8 (2 sources × 4 fields) | 9 |
| player_composite_factors | 1 | 16 (4 sources × 4 fields) | 17 |
| **TOTAL** | **4** | **32** | **36 columns** |

---

## 🔄 Dependency Chain

```
Phase 3 Analytics (has data_hash)
  ├── team_defense_game_summary.data_hash
  ├── player_game_summary.data_hash
  ├── team_offense_game_summary.data_hash
  ├── upcoming_player_game_context.data_hash
  └── upcoming_team_game_context.data_hash
         ↓
Phase 4 Precompute (reads Phase 3 hashes as source_*_hash)
  ├── team_defense_zone_analysis
  │     Reads: source_team_defense_hash
  │     Writes: data_hash
  │
  ├── player_shot_zone_analysis
  │     Reads: source_player_game_hash
  │     Writes: data_hash
  │
  ├── player_daily_cache
  │     Reads: source_player_game_hash, source_team_offense_hash
  │     Writes: data_hash
  │
  └── player_composite_factors
        Reads: source_upcoming_player_hash, source_upcoming_team_hash
               source_player_shot_zone_hash (Phase 4!),
               source_team_defense_zone_hash (Phase 4!)
        Writes: data_hash
         ↓
Phase 5 Predictions (reads Phase 4 hashes)
  └── All prediction systems read Phase 4 data_hash values
```

---

## ⚡ Expected Performance Impact

### Cost Savings
- **Without patterns:** Process all 450 players nightly (~$50/month)
- **With patterns:** Skip 30-40% of processing (~$30-35/month saved)
- **Additional savings:** Skip duplicate BigQuery writes (~$5/month saved)
- **Total savings:** ~$35-40/month (40-50% reduction)

### Processing Time Savings
- **Current:** 25-30 minutes nightly (all 4 processors)
- **With patterns:** 15-20 minutes nightly (skipping unchanged data)
- **Time saved:** 33-40%

### When Patterns Activate
- **Smart Reprocessing:** Skips when NBA has no games (off-season, all-star break)
- **Smart Idempotency:** Skips when calculated values stable despite input changes
- **Combined effect:** Maximum efficiency during low-activity periods

---

## 📋 Implementation Plan

### Phase 1: Schema Updates (This Session) ✅ COMPLETE
1. ✅ Identify all 4 Phase 4 tables
2. ✅ Map dependencies (Phase 3 sources)
3. ✅ Design hash column strategy
4. ✅ Update 4 schema files with hash columns
5. ⏭️ Deploy schema updates to BigQuery (next: when user returns)

### Phase 2: Processor Updates (Next Session)
1. Update 4 processors with SmartIdempotencyMixin
2. Update 4 processors with dependency hash extraction
3. Add hash computation logic
4. Add skip logic based on hashes
5. Test locally

### Phase 3: Deployment & Verification (Final Session)
1. Deploy Phase 4 processors to Cloud Run
2. Monitor first nightly run
3. Verify hash columns populated
4. Measure skip rates
5. Calculate cost savings

---

## 🔗 Related Documentation

**Pattern Guides:**
- `docs/guides/processor-patterns/01-smart-idempotency.md`
- `docs/guides/processor-patterns/03-smart-reprocessing.md`

**Phase 3 Reference:**
- `docs/deployment/01-phase-3-4-5-deployment-assessment.md`
- `docs/deployment/04-phase-3-schema-verification.md`

**Monitoring:**
- `docs/deployment/03-phase-3-monitoring-quickstart.md`
- `docs/monitoring/PATTERN_MONITORING_QUICK_REFERENCE.md`

---

**Created with:** Claude Code
**Next Action:** Update Phase 4 schema files with hash columns
**Estimated Time:** 30-45 minutes for all 4 schemas
