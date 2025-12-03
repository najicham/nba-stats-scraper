# Data Flow Documentation

**Last Updated:** 2025-12-02
**Purpose:** Data lineage, field mappings, and transformations across pipeline phases
**Audience:** Engineers understanding data flow and debugging data issues
**Status:** All Phases Deployed - Backfill in Progress

---

## 📖 Overview

This directory will contain documentation showing how data transforms as it moves through the 6-phase pipeline:

1. **Phase 1→2:** Scraper outputs (GCS JSON) → Raw tables (BigQuery nba_raw)
2. **Phase 2→3:** Raw tables → Analytics tables (BigQuery nba_analytics)
3. **Phase 3→4:** Analytics → Precompute (BigQuery nba_precompute)
4. **Phase 4→5:** Precompute → Predictions (BigQuery nba_predictions)
5. **Phase 5→6:** Predictions → Web app API (Firestore/JSON)

---

## 📊 Pipeline at a Glance

### Complete Data Flow (End-to-End)

```
┌──────────────────────────────────────────────────────────────────┐
│ PHASE 1: Data Collection (26 Scrapers)                          │
│ Sources: nba.com, BigDataBall, Odds APIs, ESPN                  │
│ Output: GCS JSON files (~50 files/day)                          │
│ Docs: 01-phase1-scraper-outputs.md                              │
└──────────────────────────────────────────────────────────────────┘
                            ↓
                    [21 Processors]
                    Doc: 02 (Phase 1→2)
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ PHASE 2: Raw Storage                                             │
│ Dataset: nba_raw (BigQuery)                                      │
│ Tables: 21 raw tables (boxscores, schedules, odds, injuries)    │
│ Pattern: APPEND_ALWAYS / MERGE_UPDATE                           │
└──────────────────────────────────────────────────────────────────┘
                            ↓
                    [7 Processors]
                    Docs: 03-07 (Phase 2→3)
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ PHASE 3: Analytics                                               │
│ Dataset: nba_analytics (BigQuery)                               │
│ Tables: 5 analytics tables (game summaries, context)            │
│ Aggregation: Rolling windows, advanced metrics                  │
│ Status: ✅ All deployed and operational                          │
└──────────────────────────────────────────────────────────────────┘
                            ↓
                    [5 Processors]
                    Docs: 08-12 (Phase 3→4)
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ PHASE 4: Precompute (ML Features)                               │
│ Datasets: nba_precompute + nba_predictions                      │
│ Tables: 5 precompute tables (zone analysis, features, cache)    │
│ Purpose: Daily ML feature generation (25 features/player)       │
│ Status: ✅ All deployed and operational                          │
└──────────────────────────────────────────────────────────────────┘
                            ↓
                    [5 Prediction Systems]
                    Doc: 13 (Phase 4→5)
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ PHASE 5: Predictions                                             │
│ Dataset: nba_predictions (BigQuery)                             │
│ Output: 2,250 predictions/day (450 players × 5 systems)         │
│ Systems: Moving Avg, Zone Matchup, Similarity, XGBoost, Ensemble│
│ Status: ✅ Deployed and operational                               │
└──────────────────────────────────────────────────────────────────┘
                            ↓
                    [Future: Phase 6]
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ PHASE 6: Publishing (Future)                                     │
│ Output: Web API, Firestore                                      │
│ Status: Not yet documented                                      │
└──────────────────────────────────────────────────────────────────┘
```

### Key Metrics

| Phase | Processors | Input Tables | Output Tables | Daily Volume | Status |
|-------|-----------|--------------|---------------|--------------|--------|
| 1→2 | 21 | 26 scrapers | 21 raw tables | ~50 JSON files | ✅ Deployed |
| 2→3 | 5 | 21 raw tables | 5 analytics tables | ~2,000 rows | ✅ Deployed |
| 3→4 | 5 | 5 analytics tables | 5 precompute tables | ~1,350 rows | ✅ Deployed |
| 4→5 | 5 systems | 1 feature store | 1 predictions table | ~2,250 rows | ✅ Deployed |

### Quick Navigation by Use Case

**"Where does this field come from?"**
1. Start with Phase 5 output → Doc 13
2. Trace back to Phase 4 → Docs 08-12
3. Trace back to Phase 3 → Docs 03-07
4. Trace back to Phase 2 → Doc 02
5. Trace back to scrapers → Doc 01

**"What depends on this table?"**
- See "Reverse Index: Table Consumers" section below

**"Why is my prediction missing?"**
1. Check Phase 5 (Doc 13) → features loaded?
2. Check Phase 4 (Doc 12) → ml_feature_store_v2 exists?
3. Check Phase 4 (Docs 08-11) → dependencies complete?
4. Check Phase 3 (Docs 03-07) → analytics tables populated?

**"What's blocking deployment?"**
- See "Deployment Status Summary" section below

---

## 📚 Complete Documentation Index

### Quick Reference: All Docs

| # | Document | Phase | Input | Output | Status |
|---|----------|-------|-------|--------|--------|
| **01** | Scraper Outputs | 1 | APIs | GCS JSON | Deployed |
| **02** | Phase 1→2 Transform | 1→2 | GCS JSON | 21 raw tables | Deployed |
| **03** | Team Offense | 2→3 | nbac_team_boxscore | team_offense_game_summary | Deployed |
| **04** | Team Defense | 2→3 | nbac_team_boxscore | team_defense_game_summary | Deployed |
| **05** | Upcoming Team Context | 2→3 | 5 raw tables | upcoming_team_game_context | Deployed |
| **06** | Upcoming Player Context | 2→3 | 8 raw tables | upcoming_player_game_context | Deployed |
| **07** | Player Game Summary | 2→3 | 6 raw tables | player_game_summary | Deployed |
| **08** | Team Defense Zones | 3→4 | team_defense_game_summary | team_defense_zone_analysis | Deployed |
| **09** | Player Shot Zones | 3→4 | player_game_summary | player_shot_zone_analysis | Deployed |
| **10** | Player Daily Cache | 3→4 | 3 analytics + 1 phase4 | player_daily_cache | Deployed |
| **11** | Composite Factors | 3→4 | 2 analytics + 2 phase4 | player_composite_factors | Deployed |
| **12** | ML Feature Store | 3→4 | 3 analytics + 4 phase4 | ml_feature_store_v2 | Deployed |
| **13** | Feature Consumption | 4→5 | ml_feature_store_v2 | player_prop_predictions | Deployed |

**Legend:**
- ✅ Deployed - All sources available, processor implemented, output table exists

### Deployment Status Summary

**All Phases Deployed ✅**

All 13 data flow documents are now production-ready:
- Docs 01-02: Phase 1→2 (scrapers and raw processors)
- Docs 03-07: Phase 2→3 (analytics processors)
- Docs 08-12: Phase 3→4 (precompute processors)
- Doc 13: Phase 4→5 (prediction systems)

**System Status:**
- Phase 3: 5 analytics processors operational
- Phase 4: 5 precompute processors operational
- Phase 5: Coordinator + Worker deployed and generating predictions

---

## 🔗 Reverse Index: Table Consumers

**"Which processors depend on this table?"**

### Phase 2 Raw Tables → Phase 3 Processors

| Raw Table | Consumed By (Phase 3) |
|-----------|----------------------|
| `nba_raw.nbac_team_boxscore` | team_offense (03), team_defense (04) |
| `nba_raw.nbac_gamebook_player_stats` | team_defense (04), player_game_summary (07) |
| `nba_raw.bdl_player_boxscores` | team_defense (04), player_game_summary (07), upcoming_player_context (06) |
| `nba_raw.nbac_schedule` | upcoming_team_context (05), upcoming_player_context (06) |
| `nba_raw.odds_api_game_lines` | upcoming_team_context (05), upcoming_player_context (06) |
| `nba_raw.odds_player_props` | upcoming_player_context (06), Phase 5 coordinator |
| `nba_raw.nbac_injury_report` | upcoming_team_context (05), upcoming_player_context (06) |
| `nba_raw.bigdataball_play_by_play` | player_game_summary (07) |

### Phase 3 Analytics → Phase 4 Processors

| Analytics Table | Consumed By (Phase 4) |
|-----------------|--------------------|
| `nba_analytics.team_defense_game_summary` | team_defense_zone_analysis (08) |
| `nba_analytics.player_game_summary` | player_shot_zone_analysis (09), player_daily_cache (10), ml_feature_store_v2 (12), Phase 5 workers |
| `nba_analytics.team_offense_game_summary` | player_daily_cache (10), ml_feature_store_v2 (12) |
| `nba_analytics.upcoming_player_game_context` | player_daily_cache (10), player_composite_factors (11), ml_feature_store_v2 (12), Phase 5 coordinator |
| `nba_analytics.upcoming_team_game_context` | player_composite_factors (11), ml_feature_store_v2 (12) |

### Phase 4 Precompute → Phase 4 Processors (Internal Dependencies)

| Precompute Table | Consumed By (Phase 4) |
|------------------|--------------------|
| `nba_precompute.player_shot_zone_analysis` | player_daily_cache (10), player_composite_factors (11), ml_feature_store_v2 (12) |
| `nba_precompute.team_defense_zone_analysis` | player_composite_factors (11), ml_feature_store_v2 (12) |
| `nba_precompute.player_daily_cache` | ml_feature_store_v2 (12) |
| `nba_precompute.player_composite_factors` | ml_feature_store_v2 (12) |

### Phase 4 Features → Phase 5 Systems

| Feature Store | Consumed By (Phase 5) |
|---------------|-------------------|
| `nba_predictions.ml_feature_store_v2` | ALL 5 prediction systems (Moving Average, Zone Matchup, Similarity, XGBoost, Ensemble) |

---

## 🎯 Common Patterns

### Pattern 1: Multi-Source Fallback
Several processors use primary + fallback sources:

**Example: Player Game Summary (Doc 07)**
```
Primary: nba_raw.nbac_gamebook_player_stats (95% coverage)
Fallback: nba_raw.bdl_player_boxscores (100% coverage)
Shot zones: nba_raw.bigdataball_play_by_play (optional)
```

**Example: ML Feature Store (Doc 12)**
```
Tier 1: Phase 4 tables (preferred, highest quality)
Tier 2: Phase 3 tables (fallback, calculated on-the-fly)
Tier 3: Hardcoded defaults (last resort)
```

### Pattern 2: Rolling Window Aggregations
Phase 3→4 processors compute rolling windows:

- **Team Defense Zones (08):** Last 15 games per team
- **Player Shot Zones (09):** Last 10 games + Last 20 games (dual windows)
- **Player Daily Cache (10):** Last 5, 10, season aggregations
- **Composite Factors (11):** Last 7 days, last 14 days

### Pattern 3: Early Season Handling
Processors gracefully degrade when insufficient data:

- **Phase 4 processors:** Write placeholder rows with `early_season_flag = TRUE`
- **Phase 5 systems:** Skip players with `early_season_flag = TRUE`
- **Threshold:** Usually triggered when >50% of players lack historical data

### Pattern 4: Quality Scoring
Phase 4 processors track data quality:

- **Source weighting:** phase4=100, phase3=75, calculated=100, default=40
- **Completeness:** Track % of expected data found
- **Validation:** Consumer systems check quality_score ≥70 before using
- **Monitoring:** Average quality_score ≥85 for 85%+ of players

### Pattern 5: Array-Based Storage (Evolution-Friendly)
Phase 4→5 uses arrays for future-proofing:

```sql
-- Current: 25 features
features ARRAY<FLOAT64>  -- [f0, f1, ..., f24]

-- Future: Add features without schema change
features ARRAY<FLOAT64>  -- [f0, f1, ..., f46]  (47 features)

-- Consumers extract by index (works with any length ≥25)
points_avg_last_5 = features[0]
```

### Pattern 6: v4.0 Dependency Tracking
Phase 4 processors track their sources:

**Per source: 3 fields**
- `source_<name>_last_updated` - When source was last processed
- `source_<name>_rows_found` - Number of rows retrieved
- `source_<name>_completeness_pct` - Percentage of expected data found

**Benefits:**
- Trace data freshness
- Identify incomplete dependencies
- Debug missing data

---

## 🗂️ What Will Go in This Directory

**Data Flow** = How data transforms between phases

**Will belong here:**
- ✅ Field mapping tables (raw field → analytics field)
- ✅ Transformation logic documentation
- ✅ Schema evolution tracking
- ✅ End-to-end data lineage (scraper → API)
- ✅ Example traces ("follow a stat from scraper to web")
- ✅ Join relationships between tables
- ✅ Data type conversions

**Will NOT belong here:**
- ❌ Operational guides (goes in phase directories)
- ❌ Troubleshooting procedures (goes in phase directories)
- ❌ Infrastructure configuration (goes in `infrastructure/`)
- ❌ Business logic (goes in code, referenced from phase docs)

**Rule of thumb:** If it answers "where does this data come from?" or "how does field X become field Y?", it goes here.

---

## 📋 Current Content

### Phase 1: Data Collection

**01-phase1-scraper-outputs.md** ✅
- Complete catalog of 26 scrapers across 7 data sources
- API response structures and field definitions
- GCS storage patterns and naming conventions
- Update frequencies and data quality metrics
- Foundation for understanding what data is collected

**02-phase1-to-phase2-transformations.md** ✅
- 21 processors transforming JSON/GCS → BigQuery raw tables
- Common transformation patterns (game_id, player_lookup, team codes)
- Field-by-field mappings for each processor
- Processing strategies (APPEND_ALWAYS, MERGE_UPDATE, INSERT_NEW_ONLY)
- Data quality validations and schema references

### Phase 2→3: Raw → Analytics

**03-phase2-to-phase3-team-offense.md** ✅ ⚠️
- **Status:** Implementation complete, blocked on Phase 2 deployment
- Raw: `nba_raw.nbac_team_boxscore` (MISSING - critical blocker)
- Analytics: `nba_analytics.team_offense_game_summary` (47 fields)
- Advanced metrics: offensive rating, pace, possessions, true shooting %
- v2.0 schema: is_home field, dual game IDs, simplified self-join
- Optional shot zones from play-by-play

**04-phase2-to-phase3-team-defense.md** ✅ ⚠️
- **Status:** Implementation complete, blocked on Phase 2 deployment
- Raw: `nba_raw.nbac_team_boxscore` (MISSING - critical blocker)
- Raw: `nba_raw.nbac_gamebook_player_stats` (EXISTS)
- Raw: `nba_raw.bdl_player_boxscores` (EXISTS - fallback)
- Analytics: `nba_analytics.team_defense_game_summary` (54 fields)
- Multi-source fallback logic (gamebook → BDL → nbac)
- Opponent offense perspective flip
- v2.0: Phase 2 architecture (fixed circular dependency)

**05-phase2-to-phase3-upcoming-team-game-context.md** ✅ 🟡
- **Status:** Implementation in progress, source tracking incomplete
- **5 Phase 2 sources** (most complex processor):
  - `nba_raw.nbac_schedule` (CRITICAL - status unknown)
  - `nba_raw.odds_api_game_lines` (OPTIONAL - status unknown)
  - `nba_raw.nbac_injury_report` (OPTIONAL - EXISTS)
  - `nba_raw.espn_scoreboard` (FALLBACK - status unknown)
  - `nba_static.travel_distances` (ENRICHMENT - status unknown)
- Analytics: `nba_analytics.upcoming_team_game_context`
- Context types: fatigue, betting, personnel, momentum, travel
- Multi-source fallback (schedule + ESPN backup)
- Team name mapping challenges (Odds API)
- Comprehensive troubleshooting guide

**06-phase2-to-phase3-upcoming-player-game-context.md** ✅ ⚠️
- **Status:** Implementation complete, blocked on Phase 2 deployment
- **8 Phase 2 sources** (most complex Phase 3 processor):
  - `nba_raw.odds_api_player_points_props` (DRIVER - MISSING - critical blocker)
  - `nba_raw.nbac_schedule` (CRITICAL - MISSING - critical blocker)
  - `nba_raw.bdl_player_boxscores` (PRIMARY - EXISTS)
  - `nba_raw.odds_api_game_lines` (OPTIONAL - MISSING)
  - `nba_raw.espn_team_rosters` (OPTIONAL - EXISTS)
  - `nba_raw.nbac_injury_report` (OPTIONAL - EXISTS)
  - `nba_raw.bdl_injuries` (OPTIONAL - EXISTS)
  - `nba_reference.nba_players_registry` (OPTIONAL - EXISTS)
- Analytics: `nba_analytics.upcoming_player_game_context` (72 fields)
- Pre-game context: fatigue, performance trends, prop line movement
- Driver pattern: Props table identifies which players to process
- Quality tiers based on sample size (high/medium/low)

**07-phase2-to-phase3-player-game-summary.md** ✅ 🟢
- **Status:** Production ready - All critical sources available
- **6 Phase 2 sources** with intelligent fallback:
  - `nba_raw.nbac_gamebook_player_stats` (PRIMARY - EXISTS - ~95% coverage)
  - `nba_raw.bdl_player_boxscores` (FALLBACK - EXISTS - 100% coverage)
  - `nba_raw.bigdataball_play_by_play` (OPTIONAL - EXISTS - shot zones verified)
  - `nba_raw.nbac_play_by_play` (BACKUP - EXISTS - shot zones unverified)
  - `nba_raw.bettingpros_player_points_props` (OPTIONAL - EXISTS - prop lines backup)
  - `nba_reference.nba_players_registry` (OPTIONAL - EXISTS)
- Analytics: `nba_analytics.player_game_summary` (72 fields)
- Unified player boxscore: stats, shot zones, prop results, advanced metrics
- Multi-pass architecture: Core stats (Pass 1) → Shot zones (Pass 2) → Props (Pass 3)
- RegistryReader integration for universal player IDs
- 18 source tracking fields (3 per source × 6 sources)

### Phase 3→4: Analytics → Precompute

**08-phase3-to-phase4-team-defense-zone-analysis.md** ✅ 🟢
- **Status:** Production ready - All sources available
- **Phase 3 Source:** `nba_analytics.team_defense_game_summary` (EXISTS)
- **Phase 4 Processor:** `team_defense_zone_analysis_processor.py` (implemented)
- **Precompute Table:** `nba_precompute.team_defense_zone_analysis` (~35 fields)
- **Rolling 15-game windows** per team
- Zone-by-zone defense: paint, mid-range, three-point
- League-relative metrics (vs league average in percentage points)
- Strength/weakness identification per team
- Early season handling for teams with <15 games
- 90-day retention, nightly updates

**09-phase3-to-phase4-player-shot-zone-analysis.md** ✅ 🟢
- **Status:** Production ready - All sources available
- **Phase 3 Source:** `nba_analytics.player_game_summary` (EXISTS)
- **Phase 4 Processor:** `player_shot_zone_analysis_processor.py` (implemented)
- **Precompute Table:** `nba_precompute.player_shot_zone_analysis` (~450 rows/day)
- **Dual rolling windows:** Last 10 games (primary) + Last 20 games (trend)
- Shot distribution by zone (paint, mid-range, three-point rate %)
- Shooting efficiency (FG% by zone)
- Volume metrics (attempts per game)
- Shot creation (assisted vs unassisted rate)
- Primary scoring zone identification (paint/perimeter/mid-range/balanced)
- Data quality tiers based on sample size (high/medium/low)

**10-phase3-to-phase4-player-daily-cache.md** ✅ 🟢
- **Status:** Production ready - All sources available
- **Multi-source aggregation:** 3 Phase 3 tables + 1 Phase 4 table
  - `nba_analytics.player_game_summary` (EXISTS)
  - `nba_analytics.team_offense_game_summary` (EXISTS)
  - `nba_analytics.upcoming_player_game_context` (EXISTS)
  - `nba_precompute.player_shot_zone_analysis` (EXISTS - Phase 4 dependency)
- **Phase 4 Processor:** `player_daily_cache_processor.py` (implemented)
- **Precompute Table:** `nba_precompute.player_daily_cache` (~450 rows/day)
- **Daily cache pattern:** Load once at 12:00 AM, reuse all day
- Performance optimization: Reduces BQ queries by 99.75% (1 vs 400/day)
- Recent performance windows (last 5, 10, season)
- Team context (pace, offensive rating)
- Fatigue metrics (pre-calculated from upcoming_context)
- Shot zone tendencies (pre-calculated from shot_zone_analysis)
- 30-day retention

**11-phase3-to-phase4-player-composite-factors.md** ✅ 🟢
- **Status:** Production ready - All sources available
- **Multi-source integration:** 2 Phase 3 tables + 2 Phase 4 tables
  - `nba_analytics.upcoming_player_game_context` (EXISTS)
  - `nba_analytics.upcoming_team_game_context` (EXISTS)
  - `nba_precompute.player_shot_zone_analysis` (EXISTS - Phase 4 dependency)
  - `nba_precompute.team_defense_zone_analysis` (EXISTS - Phase 4 dependency)
- **Phase 4 Processor:** `player_composite_factors_processor.py` (implemented)
- **Precompute Table:** `nba_precompute.player_composite_factors` (~450 rows/day)
- **8 composite factors:** 4 active (fatigue, shot zone mismatch, pace, usage spike) + 4 deferred (zeros)
- Score-to-adjustment conversion for point predictions
- Week 1-4 strategy: Monitor XGBoost feature importance before activating deferred factors
- Data quality tracking: completeness %, warnings, version metadata
- 90-day retention, nightly updates at 11:30 PM

**12-phase3-to-phase4-ml-feature-store-v2.md** ✅ ⚠️
- **Status:** Blocked - Processor implemented, output table missing
- **Multi-source integration:** 3 Phase 3 tables + 4 Phase 4 tables
  - Phase 3: `nba_analytics.upcoming_player_game_context` (EXISTS)
  - Phase 3: `nba_analytics.player_game_summary` (EXISTS)
  - Phase 3: `nba_analytics.team_offense_game_summary` (EXISTS)
  - Phase 4: `nba_precompute.player_daily_cache` (EXISTS)
  - Phase 4: `nba_precompute.player_composite_factors` (EXISTS)
  - Phase 4: `nba_precompute.player_shot_zone_analysis` (EXISTS)
  - Phase 4: `nba_precompute.team_defense_zone_analysis` (EXISTS)
- **Phase 4 Processor:** `ml_feature_store_processor.py` (implemented)
- **Output Table:** `nba_predictions.ml_feature_store_v2` (**MISSING** - blocker)
- **25 ML features:** Stored as ARRAY<FLOAT64> for schema flexibility
- Three-tier fallback: Phase 4 (preferred) → Phase 3 (fallback) → Defaults
- Quality scoring: 0-100 weighted by data source (phase4=100, phase3=75, default=40)
- v4.0 dependency tracking: 12 source fields (4 sources × 3 fields)
- Runs LAST in Phase 4 (12:00 AM) after all dependencies complete
- Cross-dataset write to nba_predictions (requires special permissions)

### Phase 4→5: Precompute → Predictions

**13-phase4-to-phase5-feature-consumption.md** ✅ ⚠️
- **Status:** Blocked - Source table missing, contract fully defined
- **Phase 4 Source:** `nba_predictions.ml_feature_store_v2` (**MISSING** - blocker)
- **Phase 5 Consumers:** 5 prediction systems (all depend on feature store)
- **Phase 5 Output:** `nba_predictions.player_prop_predictions` (**MISSING** - not verified)
- **Feature consumption matrix:** 25 features → 5 systems (10-25 features each)
  - Moving Average: 10 of 25 features (performance + matchup)
  - Zone Matchup V1: 14 of 25 features (composite + shot zones)
  - Similarity: 15 of 25 features + historical games
  - XGBoost: ALL 25 features (ML model)
  - Ensemble: ALL 25 features (meta-learning)
- **Quality contract:** Phase 4 guarantees ≥85% with score ≥85, Phase 5 requires ≥70
- **Array-based extraction:** Systems extract features by index (0-24)
- **Graceful degradation:** Skip players with early_season_flag or quality <70
- **Feature version:** v1_baseline_25 (validates before use)
- **Processing:** 450 players × 5 systems = 2,250 predictions/day

---

## 📋 Planned Content

### Phase-to-Phase Mappings

**Future Phase-to-Phase Mappings:**

**14-phase5-to-phase6-mapping.md** (Future)
- Predictions → API payload format
- Publishing and caching strategy

### End-to-End Examples

**99-end-to-end-example.md** (Future)
- Complete trace: Specific stat from scraper → API
- Example: "LeBron's points total" journey through all 6 phases
- Debugging guide: "How do I trace a missing/incorrect stat?"

---

## 🔗 Related Documentation

**Operational Guides:**
- **Phase 1:** `docs/orchestration/` - Scraper orchestration
- **Phase 2:** `docs/processors/` - Processor operations
- **Monitoring:** `docs/monitoring/` - Data quality metrics

**System Design:**
- **Architecture:** `docs/01-architecture/` - Overall pipeline design
- **Schemas:** `docs/orchestration/03-bigquery-schemas.md` - Phase 1 table schemas

---

## 📝 Adding Data Mapping Documentation

**When you're ready to add data mappings:**

1. **Start with Phase 1→2** - Most immediate value for debugging

2. **Create file:** `01-phase1-to-phase2-mapping.md`

3. **Include:**
   - Field-by-field mapping tables
   - Transformation logic explanations
   - Example JSON input → SQL output
   - Edge cases and special handling

4. **Use standard metadata header**

5. **Update this README** with actual content

**Suggested format for mapping docs:**

```markdown
## Scraper: nbac_schedule_api

### Input (GCS JSON)
```json
{
  "gameId": "0022400123",
  "gameDate": "2025-01-15",
  ...
}
```

### Output (BigQuery nba_raw.nbac_schedule)
| Raw Field | BQ Field | Transformation | Notes |
|-----------|----------|----------------|-------|
| gameId | game_id | Direct copy | String |
| gameDate | game_date | Parse to DATE | YYYY-MM-DD |
...
```

**See:** `docs/DOCUMENTATION_GUIDE.md` for file organization standards

---

## 🚀 Use Cases

**Why data flow docs are valuable:**

1. **Debugging Missing Data**
   - "Why is this field NULL in analytics?"
   - Trace backwards: Analytics ← Raw ← Scraper
   - Find where the data was lost

2. **Understanding Transformations**
   - "How is `efficiency_rating` calculated?"
   - Follow the transformation chain
   - See the business logic

3. **Schema Changes**
   - "If I change this raw field, what breaks?"
   - See all downstream dependencies
   - Plan the impact

4. **Onboarding**
   - "How does this pipeline work?"
   - Follow a concrete example end-to-end
   - Understand the big picture

---

**Directory Status:** ✅ Complete (All phases documented and deployed)
**File Organization:** Chronological numbering (01-99)
**Next Available Number:** 14

---

*This directory is ready for data mapping documentation. When ready, add field mappings showing how data transforms at each phase boundary.*
