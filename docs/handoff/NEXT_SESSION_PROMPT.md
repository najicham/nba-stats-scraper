# Next Session Prompt: Completeness Checking Rollout (Weeks 2-6)

Copy this entire prompt into your next Claude Code session to continue the work.

---

## Context: What Was Completed

We just finished **Week 1 of Phase 4 Completeness Checking implementation**. Here's what's done:

### ✅ Infrastructure Complete
1. **CompletenessChecker Service** - Created and tested (`/shared/utils/completeness_checker.py`)
   - 22 unit tests passing
   - Batch checking (2 queries for all entities)
   - Supports 'games' and 'days' window types
   - Bootstrap mode and season boundary detection

2. **Circuit Breaker Tracking** - Deployed to BigQuery
   - Table: `nba_orchestration.reprocess_attempts`
   - Prevents reprocessing oscillation (max 3 attempts, 7-day cooldown)

3. **First Processor Complete** - `team_defense_zone_analysis`
   - Schema updated (14 completeness columns)
   - Processor integrated with completeness checking
   - Circuit breaker logic working
   - All metadata fields populated in output

### ✅ Documentation Complete
- `/docs/implementation/HANDOFF-week1-completeness-rollout.md` - **READ THIS FIRST**
- `/docs/implementation/WEEK1_COMPLETE.md` - Week 1 summary with examples
- `/docs/implementation/11-phase3-phase4-completeness-implementation-plan.md` - Full plan (7 processors)

---

## Your Mission: Weeks 2-6

**Goal**: Roll out completeness checking to the remaining **6 processors** (2 Phase 3 + 4 Phase 4)

**Estimated Time**: 5-6 hours total (or 1-2 hours per day for a week)

**What You'll Do**:
- Add 14 completeness checking columns to each schema
- Deploy schemas to BigQuery
- Integrate CompletenessChecker service into each processor
- Add circuit breaker logic
- Test each processor

---

## Immediate First Steps

### Step 1: Read the Handoff Document (15 min) ⚠️ CRITICAL

**You MUST read this before starting**:
```
/docs/implementation/HANDOFF-week1-completeness-rollout.md
```

This document contains:
- Step-by-step instructions for each processor
- Code templates (copy-paste ready)
- Processor-specific notes (multi-window, cascade dependencies)
- Testing checklist
- Common patterns

### Step 2: Review Week 1 Summary (5 min)

```
/docs/implementation/WEEK1_COMPLETE.md
```

Shows how completeness checking works with real examples.

### Step 3: Reference the Completed Processor

**Template to copy from**:
```
/data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py
```

**Look at these sections**:
- Lines 45: Import CompletenessChecker
- Lines 118: Initialize in __init__()
- Lines 537-635: Circuit breaker methods
- Lines 665-743: Batch completeness checking in calculate_precompute()
- Lines 813-840: Output metadata fields

---

## Week 2: Start Here (Next Task)

**Processor**: `player_shot_zone_analysis` (simplest remaining processor)

**Location**:
- Schema: `/schemas/bigquery/precompute/player_shot_zone_analysis.sql`
- Processor: `/data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

**Key Differences from team_defense_zone_analysis**:
- Entity type: `'player'` (not 'team')
- Upstream table: `'nba_analytics.player_game_summary'`
- Entity field: `'player_lookup'`
- Lookback window: 10 games (not 15)

**Follow the handoff doc Step 1-4** for this processor.

**Estimated time**: 40 minutes

---

## Remaining Processors (After Week 2)

**Week 3**: `player_daily_cache` (~60 min)
- **Special**: Multi-window complexity (L5, L7d, L10, L14d)
- Needs 9 additional schema columns
- ALL windows must be 90% complete

**Week 4**: `player_composite_factors` + `ml_feature_store` (~100 min total)
- **Special**: Cascade dependencies (depend on other Phase 4 processors)
- Track upstream completeness, don't cascade-fail

**Weeks 5-6**: `upcoming_player_game_context` + `upcoming_team_game_context` (~110 min total)
- **Special**: Phase 3 processors (different directory)
- Date-based windows (L7 days, L14 days) instead of game-count
- Multiple windows like player_daily_cache

---

## Key Files Reference

### Service (Don't Modify - Already Complete)
```
/shared/utils/completeness_checker.py
```

### Schemas to Update (6 remaining)
```
Phase 4:
/schemas/bigquery/precompute/player_shot_zone_analysis.sql
/schemas/bigquery/precompute/player_daily_cache.sql
/schemas/bigquery/precompute/player_composite_factors.sql
/schemas/bigquery/precompute/ml_feature_store.sql

Phase 3:
/schemas/bigquery/analytics/upcoming_player_game_context_tables.sql
/schemas/bigquery/analytics/upcoming_team_game_context_tables.sql
```

### Processors to Update (6 remaining)
```
Phase 4:
/data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py
/data_processors/precompute/player_daily_cache/player_daily_cache_processor.py
/data_processors/precompute/player_composite_factors/player_composite_factors_processor.py
/data_processors/precompute/ml_feature_store/ml_feature_store_processor.py

Phase 3:
/data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
/data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py
```

---

## The Pattern (Repeat 6 Times)

For each processor:

1. **Update Schema** (10 min)
   - Add 14 completeness columns to CREATE TABLE
   - Add 14 columns to ALTER TABLE
   - Update field count in comments

2. **Deploy Schema** (1 min)
   ```bash
   bq query --use_legacy_sql=false --project_id=nba-props-platform "
   ALTER TABLE \`nba-props-platform.nba_precompute.[TABLE_NAME]\`
   ADD COLUMN IF NOT EXISTS expected_games_count INT64 OPTIONS (description='...'),
   # ... (all 14 columns)
   "
   ```

3. **Update Processor** (20 min)
   - Add import: `from shared.utils.completeness_checker import CompletenessChecker`
   - Initialize in __init__: `self.completeness_checker = CompletenessChecker(...)`
   - Add circuit breaker methods (copy from team_defense_zone_analysis)
   - Add batch completeness check before processing loop
   - Add completeness checks inside loop
   - Add 14 metadata fields to output record

4. **Test** (5 min)
   ```bash
   pytest tests/unit/utils/test_completeness_checker.py -v
   # Verify BigQuery schema
   bq show --schema nba-props-platform:nba_precompute.[TABLE_NAME] | grep completeness
   ```

---

## Testing Validation

After each processor integration:

```sql
-- Check completeness metadata populated (if data available)
SELECT
  [ENTITY_FIELD],
  completeness_percentage,
  is_production_ready,
  expected_games_count,
  actual_games_count,
  backfill_bootstrap_mode,
  processing_decision_reason
FROM `nba-props-platform.[DATASET].[TABLE_NAME]`
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
LIMIT 5;

-- Check circuit breaker tracking
SELECT *
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE processor_name = '[TABLE_NAME]'
ORDER BY attempted_at DESC
LIMIT 5;
```

---

## Success Criteria (When Complete)

- [ ] All 7 processors have completeness checking (1 done, 6 to go)
- [ ] All 7 schemas deployed with 14+ columns
- [ ] Unit tests passing (22/22)
- [ ] Completeness metadata visible in BigQuery output
- [ ] Circuit breaker tracking working
- [ ] No errors during processing

---

## What to Tell Me

When you start the session, say:

**"I'm continuing the completeness checking rollout. I've read the handoff document and I'm ready to start with Week 2: player_shot_zone_analysis. I'll follow the step-by-step pattern from the handoff doc."**

Then I'll know you have context and we can dive right in!

---

## Quick Tips

✅ **Use team_defense_zone_analysis as your reference** - It's the template for everything
✅ **Copy-paste liberally** - The pattern is proven, just adjust entity_type and upstream_table
✅ **Read the handoff doc** - It has all the processor-specific notes you need
✅ **Test incrementally** - After each processor, verify schema and run unit tests
✅ **Don't modify CompletenessChecker** - It's done and tested, just use it

❌ **Don't skip the handoff doc** - It has critical processor-specific details
❌ **Don't guess at upstream tables** - Each processor is documented in the handoff
❌ **Don't try to parallelize** - Do one processor at a time, test, then move on

---

## Timeline Expectation

**Realistic pace**:
- Week 2: player_shot_zone_analysis (40 min)
- Week 3: player_daily_cache (60 min - multi-window)
- Week 4: player_composite_factors (50 min)
- Week 4: ml_feature_store (50 min)
- Week 5: upcoming_player_game_context (60 min)
- Week 6: upcoming_team_game_context (50 min)

**Total: 5-6 hours** or spread across 1-2 hours per day for a week

You got this! 🚀

---

## Ready? Start Here:

1. Read: `/docs/implementation/HANDOFF-week1-completeness-rollout.md`
2. Reference: `/data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`
3. Begin: `player_shot_zone_analysis` schema update
