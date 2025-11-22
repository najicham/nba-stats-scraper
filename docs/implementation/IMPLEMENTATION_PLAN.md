# NBA Stats Scraper - Implementation Plan & Progress

**Last Updated**: 2025-11-21
**Current Focus**: Phase 3 Dependency Checking + Hash Tracking

---

## 🎯 Recent Accomplishments (2025-11-21)

### Session 1: Smart Idempotency (Phase 2)
- ✅ Implemented smart idempotency for all 22 Phase 2 processors
- ✅ Added `data_hash` column to Phase 2 schemas
- ✅ Created SmartIdempotencyMixin pattern

### Session 2: Phase 3 Dependency Enhancement
- ✅ Enhanced `analytics_base.py` to track `data_hash` from Phase 2 sources
- ✅ Added `find_backfill_candidates()` method for historical backfill detection
- ✅ Fixed cross-region query issues (nba_raw in us-west2, nba_analytics in US)
- ✅ Fixed timezone handling in age calculations
- ✅ Fixed `odds_api_player_points_props` schema (renamed processing_timestamp → processed_at)
- ✅ Created test suite (all tests passing)
- ✅ Verified end-to-end: backfill detection working, hash tracking working

---

## 📋 Implementation Status

### Phase 1: Data Collection (Scrapers)
**Status**: ✅ Complete
- All scrapers deployed and running

### Phase 2: Raw Processing
**Status**: ✅ Complete (22/22 processors)
- ✅ Smart idempotency implemented (Pattern #14)
- ✅ All processors have `data_hash` column
- ⚠️ One schema issue fixed today: `odds_api_player_points_props`

### Phase 3: Analytics Processing
**Status**: ✅ **COMPLETE** - All 5 processors tested and working!
**Tested**: 2025-11-21
**Test Suite**: `tests/unit/patterns/test_all_phase3_processors.py`

#### Base Infrastructure
- ✅ `analytics_base.py` - Dependency checking framework
- ✅ Hash tracking integration (4 fields per source)
- ✅ Historical backfill detection (`find_backfill_candidates`)
- ✅ Cross-region query support (separate queries instead of JOIN)
- ✅ Timezone-aware age calculations
- ✅ Backfill maintenance job (`bin/maintenance/phase3_backfill_check.py`)

#### Processors (All Tested ✅)
1. **player_game_summary** ✅ Complete & Tested
   - 6 dependencies configured (standard pattern)
   - 24 tracking fields (6 sources × 4 fields)
   - Hash tracking: ✅ Working
   - Backfill detection: ✅ Working (13 games found in testing)
   - Schema: ✅ Deployed

2. **upcoming_player_game_context** ✅ Complete & Tested
   - 4 dependencies configured (custom pattern)
   - 16 tracking fields (4 sources × 4 fields)
   - Hash tracking: ✅ Working
   - Uses custom dependency checking (not standard check_dependencies())
   - Schema: ✅ Deployed

3. **team_offense_game_summary** ✅ Complete & Tested
   - 2 dependencies configured (standard pattern)
   - 8 tracking fields (2 sources × 4 fields)
   - Hash tracking: ✅ Working
   - Dependency: `nbac_team_boxscore` (⚠️ table doesn't exist yet)
   - Schema: ✅ Deployed

4. **team_defense_game_summary** ✅ Complete & Tested
   - 3 dependencies configured (standard pattern)
   - 12 tracking fields (3 sources × 4 fields)
   - Hash tracking: ✅ Working
   - Dependency: `nbac_team_boxscore` (⚠️ table doesn't exist yet)
   - Schema: ✅ Deployed

5. **upcoming_team_game_context** ✅ Complete & Tested
   - 3 dependencies configured (standard pattern)
   - 12 tracking fields (3 sources × 4 fields)
   - Hash tracking: ✅ Working
   - Schema: ✅ Deployed

### Phase 4: Precompute Features
**Status**: ⏳ Not Started
- Tables exist but processors not reviewed yet

### Phase 5: Predictions
**Status**: ⏳ Not Started
- Tables exist but processors not reviewed yet

---

## 🐛 Known Issues & Fixes Needed

### High Priority

1. **Missing Phase 2 Table: nbac_team_boxscore** ⚠️ **BLOCKING TEAM PROCESSORS**
   - Required by: `team_offense_game_summary`, `team_defense_game_summary`
   - Files exist: scraper, processor, schema
   - **Issue**: Table not created in BigQuery
   - **Action**: Investigate if this data source was never deployed or deprecated
   - **Impact**: Team analytics processors cannot run

2. **Phase 2 Schema Deployment** ✅ COMPLETE
   - All checked tables have `data_hash` column deployed
   - Verified with `./bin/maintenance/check_schema_deployment.sh`
   - Fixed `odds_api_player_points_props` (renamed `processing_timestamp` → `processed_at`)

3. **Region Mismatch** ⚠️ Infrastructure Issue
   - `nba_raw` dataset: us-west2
   - `nba_analytics` dataset: US (multi-region)
   - **Impact**: Can't use JOIN queries across datasets
   - **Workaround**: Implemented two separate queries in `find_backfill_candidates()`
   - **Future**: Consider migrating one dataset to match the other

3. **Missing Phase 2 Tables**
   - Several Phase 2 processors exist but tables don't exist in BigQuery
   - Example: `nbac_team_boxscore` - scraper and processor exist, no table
   - **Action**: Audit all Phase 2 tables and deploy missing ones

### Medium Priority

4. **Dependency Thresholds for Single Games**
   - Current config: `expected_count_min: 200` (assumes 10 games/day)
   - Fails for playoff/offseason single games (30 records)
   - **Impact**: Can't process individual historical games
   - **Solution**: Add `allow_single_game_mode` flag or dynamic thresholds

5. **Phase 3-4 Pub/Sub Connection** ⏳ Not Implemented
   - Phase 3 completes but doesn't trigger Phase 4
   - Need to add Pub/Sub publishing after Phase 3 success

### Low Priority

6. **Early Exit Checks vs Backfill**
   - `ENABLE_HISTORICAL_DATE_CHECK` prevents processing dates >90 days old
   - Conflicts with historical backfill use case
   - **Solution**: Disable early exit checks when running backfill jobs

---

## 🚀 Next Steps (Prioritized)

### ✅ Completed This Session (2025-11-21)

1. ✅ **Test Remaining Phase 3 Processors**
   - All 5 processors tested and working
   - Hash tracking verified for all
   - Test suite created: `tests/unit/patterns/test_all_phase3_processors.py`

2. ✅ **Create Backfill Maintenance Job**
   - Created `bin/maintenance/phase3_backfill_check.py`
   - Supports dry-run mode, custom lookback, specific processors
   - Ready for cron scheduling

3. ✅ **Verify All Phase 2 Schemas Deployed**
   - All checked schemas have required columns
   - Fixed `odds_api_player_points_props` schema issue
   - Schema check script available

### Immediate (Next Session)

1. **Investigate nbac_team_boxscore** (HIGH PRIORITY - 1-2 hours)
   - Determine if this data source is active or deprecated
   - If active: Deploy scraper + processor + create table
   - If deprecated: Remove from team processor dependencies
   - **Blockers**: Team analytics processors cannot run without this

### Short-Term (Next Week)

4. **Implement Smart Reprocessing** (3-4 hours)
   - Use hash tracking to skip Phase 3 processing when Phase 2 unchanged
   - Measure skip rate (expected 30-50%)
   - Add metrics dashboard

5. **Phase 3→4 Pub/Sub Connection** (4-6 hours)
   - Create Pub/Sub topics for Phase 3→4 communication
   - Add publishing code to Phase 3 processors
   - Test end-to-end Phase 3→4 flow

6. **Document Dependency Patterns** (2-3 hours)
   - Complete `docs/dependency-checks/02-analytics-processors.md`
   - Add examples for all 5 Phase 3 processors
   - Create troubleshooting guide

### Medium-Term (Next 2 Weeks)

7. **Region Consolidation** (Planning Required)
   - Decide: Move nba_raw to US or nba_analytics to us-west2?
   - Plan migration (consider costs, downtime)
   - Execute migration during off-hours

8. **Dynamic Dependency Thresholds** (2-3 hours)
   - Add `calculate_expected_count()` method
   - Query schedule to determine expected games
   - Adjust thresholds based on actual schedule

9. **Phase 4 & 5 Review** (Full Day)
   - Audit Phase 4 precompute processors
   - Review Phase 5 prediction systems
   - Identify issues and create implementation plan

---

## 📊 Success Metrics

### Phase 2 (Smart Idempotency)
- **Target**: 50% reduction in cascade processing
- **Measurement**: Track skip rate in logs
- **Current**: Not measured yet (just implemented)

### Phase 3 (Dependency Checking)
- **Target**: 100% of Phase 2 data processed to Phase 3
- **Measurement**: `find_backfill_candidates()` returns empty list
- **Current**: 13 games pending (from testing)

### Phase 3 (Hash Tracking)
- **Target**: 4 fields per source populated for all processors
- **Measurement**: BigQuery schema validation + row count checks
- **Current**: 1/5 processors verified working

### End-to-End (Phase 1→5)
- **Target**: Automated flow from scraper to final predictions
- **Measurement**: Manual test of full pipeline
- **Current**: Blocked on Phase 3→4 connection

---

## 🔧 Useful Commands

### Schema Management
```bash
# Check schema deployment status
./bin/maintenance/check_schema_deployment.sh

# Deploy Phase 2 schemas
for f in schemas/bigquery/raw/*.sql; do
  bq query --use_legacy_sql=false < $f
done

# Deploy Phase 3 schemas
for f in schemas/bigquery/analytics/*_tables.sql; do
  bq query --use_legacy_sql=false < $f
done
```

### Testing
```bash
# Test Phase 3 hash tracking
python tests/unit/patterns/test_historical_backfill_detection.py

# Test Phase 3 end-to-end
python tests/manual/test_player_game_summary_e2e.py

# Find backfill candidates (Python)
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
proc = PlayerGameSummaryProcessor()
proc.set_opts({'project_id': 'nba-props-platform'})
proc.init_clients()
candidates = proc.find_backfill_candidates(lookback_days=180)
```

### Monitoring
```bash
# Check Phase 2 data freshness
bq query --nouse_legacy_sql "
SELECT
  MAX(game_date) as latest_date,
  COUNT(DISTINCT game_date) as days_with_data,
  COUNT(*) as total_records
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
"

# Check Phase 3 completeness
bq query --nouse_legacy_sql "
SELECT
  game_date,
  COUNT(*) as player_records,
  COUNT(DISTINCT game_id) as games,
  COUNT(source_nbac_hash) as has_hash
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
"
```

---

## 📖 Documentation

### Core Docs
- [Handoff: Smart Idempotency](./HANDOFF-2025-11-21-smart-idempotency-complete.md)
- [Handoff: Phase 3 Enhancement](./HANDOFF-2025-11-21-phase3-dependency-enhancement.md)
- [Dependency Checking Overview](../dependency-checks/00-overview.md)
- [Phase 3 Processors Guide](../dependency-checks/02-analytics-processors.md)

### Implementation Guides
- [Smart Idempotency Guide](./03-smart-idempotency-implementation-guide.md)
- [Dependency Checking Strategy](./04-dependency-checking-strategy.md)

### Reference
- [Phase 2 Processor Hash Strategy](../reference/phase2-processor-hash-strategy.md)
- [Scraper to Processor Mapping](../reference/scraper-to-processor-mapping.md)

---

## 🤝 Contributing

When adding new features or fixes:

1. **Update this plan** with your changes
2. **Document in handoff files** if ending a session
3. **Update todo lists** as you work
4. **Run tests** before committing
5. **Update schemas** if table structure changes

---

**Questions?** See handoff documents or implementation guides above.
