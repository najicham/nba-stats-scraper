# Pattern Rollout Plan

**File:** `docs/implementation/pattern-rollout-plan.md`
**Created:** 2025-11-20
**Last Updated:** 2025-11-25
**Status:** 🟡 In Progress - Week 1 Complete, Week 2+ Pending
**Timeline:** Week 1 (Foundation) → Week 8 (Phase 3 Decision)

---

## Quick Status

| Phase | Status | Completed |
|-------|--------|-----------|
| **Week 1: Foundation Patterns** | ✅ Complete | 2025-11-20 |
| **Week 2: Monitoring Setup** | 🔴 Not Started | - |
| **Week 1-8: Data Collection** | 🔴 Not Started | - |
| **Week 4: Mid-Point Check** | 🔴 Not Started | - |
| **Week 8: Phase 3 Decision** | 🔴 Not Started | - |
| **Post-Week 8: Historical Backfill** | 📝 Planning | - |

> **Note:** Week 1 Day 1-5 implementation details archived to `archive/2025-11/WEEK1_PATTERN_ROLLOUT.md`

---

## Overview

**Goal:** Implement foundation patterns (#1, #3, #5) across all phases, monitor effectiveness, and decide on situational patterns based on data.

**What We Have:**
- ✅ Pattern #2: Dependency Precheck (analytics_base.py:319-413)
- ✅ Pattern #9: BigQuery Batching (analytics_base.py:746-814)
- ✅ Pattern #4: Processing Metadata - partial (analytics_base.py:908-927)

**What We're Adding:**
- 🔴 Pattern #1: Smart Skip (Week 1)
- 🔴 Pattern #3: Early Exit (Week 1)
- 🔴 Pattern #5: Circuit Breakers (Week 1)

**What We're Monitoring:**
- Pattern #13: Smart Caching (implement IF slow queries detected)
- Pattern #14: Smart Idempotency (implement IF duplicates > 10%)
- Pattern #15: Smart Backfill (implement IF gaps frequent)

---

## Week 1: Foundation Patterns Implementation ✅ COMPLETE

**Completed:** 2025-11-20
**Details:** [archive/2025-11/WEEK1_PATTERN_ROLLOUT.md](archive/2025-11/WEEK1_PATTERN_ROLLOUT.md)

### Summary

| Day | Task | Status |
|-----|------|--------|
| Day 1 | Schema Changes | ✅ 5 migrations complete |
| Day 2 | Create Pattern Mixins | ✅ 3 mixins created |
| Day 3 | Phase 3 Processors | ✅ 5 processors updated |
| Day 4 | Phase 4 Processors | ✅ 5 processors updated |
| Day 5 | Phase 5 Worker | ✅ Circuit breakers integrated |

### What Was Implemented:
- **Pattern #1 (Smart Skip):** Source filtering to skip irrelevant triggers
- **Pattern #3 (Early Exit):** Date-based exits for old/invalid data
- **Pattern #5 (Circuit Breaker):** Failure protection across all phases

### Files Created:
- `shared/processors/patterns/smart_skip_mixin.py`
- `shared/processors/patterns/early_exit_mixin.py`
- `shared/processors/patterns/circuit_breaker_mixin.py`
- `predictions/worker/system_circuit_breaker.py`
- `predictions/worker/execution_logger.py`

### Implementation Guide:
- [ADDING_PATTERNS_GUIDE.md](ADDING_PATTERNS_GUIDE.md) - Step-by-step instructions
- [SCHEMA_MIGRATION_SUMMARY.md](SCHEMA_MIGRATION_SUMMARY.md) - Schema changes

---

## Week 1 Detailed Logs (Archived)

> **Note:** Detailed Day 1-5 implementation logs have been archived to
> [archive/2025-11/WEEK1_PATTERN_ROLLOUT.md](archive/2025-11/WEEK1_PATTERN_ROLLOUT.md)

---

### Day 1: Schema Changes (30 minutes)

**Status:** ✅ **COMPLETED** (2025-11-20)

- [x] Create schema SQL files
  - [x] `monitoring/schemas/add_skip_reason_to_processor_runs.sql` (Phase 2)
  - [x] `monitoring/schemas/add_skip_reason_column.sql` (Phase 3)
  - [x] `monitoring/schemas/create_precompute_processor_runs_table.sql` (Phase 4)
  - [x] `monitoring/schemas/circuit_breaker_state_table.sql` (All phases)
  - [x] `monitoring/schemas/create_prediction_worker_runs_table.sql` (Phase 5)
- [x] Run schema migrations
  - [x] Add `skip_reason` column to `nba_processing.processor_runs` (Phase 2)
  - [x] Add `skip_reason` column to `nba_processing.analytics_processor_runs` (Phase 3)
  - [x] Create `nba_processing.precompute_processor_runs` table (Phase 4)
  - [x] Create `nba_orchestration.circuit_breaker_state` table (All phases)
  - [x] Create `nba_predictions.prediction_worker_runs` table (Phase 5)
- [x] Verify schema changes
  - [x] All tables created successfully
  - [x] All columns added successfully

**Completed:** 2025-11-20 21:03 PST

**Notes:**
- All 5 schema migrations completed successfully
- Original schema files also updated in `schemas/bigquery/` directories
- Phase 4 table was missing (code referenced it but didn't exist) - now fixed ✅
- Phase 5 added comprehensive worker execution tracking

---

### Day 2: Create Pattern Mixins (1 hour)

**Status:** ✅ **COMPLETED** (2025-11-20)

- [x] Create mixin directory structure
  - [x] `mkdir -p shared/processors/patterns`
  - [x] `touch shared/processors/patterns/__init__.py`
- [x] Create Pattern #1 (Smart Skip)
  - [x] `shared/processors/patterns/smart_skip_mixin.py`
  - [x] Implementation from [docs/patterns/08-smart-skip-implementation.md](../patterns/08-smart-skip-implementation.md)
  - [x] Test imports ✅
- [x] Create Pattern #3 (Early Exit)
  - [x] `shared/processors/patterns/early_exit_mixin.py`
  - [x] Implementation from [docs/patterns/03-early-exit-implementation.md](../patterns/03-early-exit-implementation.md)
  - [x] Test imports ✅
- [x] Create Pattern #5 (Circuit Breaker)
  - [x] `shared/processors/patterns/circuit_breaker_mixin.py`
  - [x] Implementation from [docs/patterns/01-circuit-breaker-implementation.md](../patterns/01-circuit-breaker-implementation.md)
  - [x] Test imports ✅

**Completed:** 2025-11-20 21:14 PST

**Notes:**
- All 3 mixin files created successfully
- All imports tested and working
- Files are 3.1KB (smart_skip), 5.3KB (early_exit), 12KB (circuit_breaker)
- Ready to add to processors in Day 3

---

### Day 3: Add to Phase 3 Processors (1 hour)

**Status:** ✅ **COMPLETED** (2025-11-20)

**📖 See:** [Adding Patterns Guide](ADDING_PATTERNS_GUIDE.md) for step-by-step instructions

**Phase 3 Processors to Update:**
- [x] `data_processors/analytics/player_game_summary_processor.py` ✅ **PILOT**
  - [x] Add SmartSkipMixin
  - [x] Add EarlyExitMixin
  - [x] Add CircuitBreakerMixin
  - [x] Configure RELEVANT_SOURCES (15 sources: 6 relevant, 9 irrelevant)
  - [x] Test locally (syntax check passed)
- [x] `data_processors/analytics/team_defense_game_summary_processor.py`
  - [x] Add all three mixins
  - [x] Configure patterns (17 sources configured)
  - [x] Test locally (syntax check passed)
- [x] `data_processors/analytics/team_offense_game_summary_processor.py`
  - [x] Add all three mixins
  - [x] Configure patterns (17 sources configured)
  - [x] Test locally (syntax check passed)
- [x] `data_processors/analytics/upcoming_player_game_context_processor.py`
  - [x] Add all three mixins
  - [x] Configure patterns (17 sources configured)
  - [x] Test locally (syntax check passed)
- [x] `data_processors/analytics/upcoming_team_game_context_processor.py`
  - [x] Add all three mixins
  - [x] Configure patterns (19 sources configured)
  - [x] Test locally (syntax check passed)

**Completed:** 2025-11-20 (continued session)

**Notes:**
- All 5 Phase 3 processors updated with all 3 patterns
- All syntax checks passed successfully
- RELEVANT_SOURCES configured uniquely per processor type
- Early Exit historical date check disabled for "upcoming" context processors

---

### Day 4: Add to Phase 4 Processors (30 minutes)

**Status:** ✅ **COMPLETED** (2025-11-20)

**Phase 4 Processors to Update:**
- [x] `data_processors/precompute/player_composite_factors_processor.py`
  - [x] Add all three mixins
  - [x] Configure patterns (14 sources configured)
  - [x] Test locally (syntax check passed)
- [x] `data_processors/precompute/player_shot_zone_analysis_processor.py`
  - [x] Add all three mixins
  - [x] Configure patterns (13 sources configured)
  - [x] Test locally (syntax check passed)
- [x] `data_processors/precompute/team_defense_zone_analysis_processor.py`
  - [x] Add all three mixins
  - [x] Configure patterns (13 sources configured)
  - [x] Test locally (syntax check passed)
- [x] `data_processors/precompute/player_daily_cache_processor.py`
  - [x] Add all three mixins
  - [x] Configure patterns (14 sources configured)
  - [x] Test locally (syntax check passed)
- [x] `data_processors/precompute/ml_feature_store_processor.py`
  - [x] Add all three mixins
  - [x] Configure patterns (14 sources configured)
  - [x] Test locally (syntax check passed)

**Completed:** 2025-11-20 (continued session)

**Notes:**
- All 5 Phase 4 processors updated with all 3 patterns
- All syntax checks passed successfully
- Phase 4 processors depend on Phase 3/4 sources, not Phase 2 directly
- Early Exit no-games check disabled for analysis-type processors

---

### Day 5: Add Pattern Support to Phase 5 Worker (1 hour)

**Status:** ✅ **COMPLETED** (2025-11-20)

**Phase 5 has Different Architecture:**
- Worker-based (Flask app receiving pub/sub messages), not processor-based
- Handles 450 players in parallel (not sequential processing)
- Already has `prediction_worker_runs` table created ✅
- Circuit breaker is **system-level** (per prediction system) not processor-level

**Phase 5 Pattern Implementation:**
- [x] Create `predictions/worker/system_circuit_breaker.py` ✅
  - [x] System-level circuit breaker class (~450 lines)
  - [x] State management (CLOSED/OPEN/HALF_OPEN)
  - [x] BigQuery state persistence
  - [x] Memory caching (30-second TTL)
  - [x] Syntax check passed ✅
- [x] Create `predictions/worker/execution_logger.py` ✅
  - [x] Execution logging helper (~300 lines)
  - [x] Logs to `prediction_worker_runs` table
  - [x] Tracks system success/failure
  - [x] Records data quality metrics
  - [x] Syntax check passed ✅
- [x] Update `predictions/worker/worker.py` ✅
  - [x] Import pattern helpers
  - [x] Initialize circuit breaker and logger
  - [x] Add execution logging to request handler
  - [x] Add performance timing
  - [x] Update `process_player_predictions` signature
  - [x] Add metadata tracking structure
  - [x] Complete circuit breaker integration for all 5 systems ✅
    - [x] moving_average (lines 394-432)
    - [x] zone_matchup_v1 (lines 434-472)
    - [x] similarity_balanced_v1 (lines 474-526)
    - [x] xgboost_v1 (lines 528-573)
    - [x] ensemble_v1 (lines 575-615)
  - [x] Add success/failure recording calls ✅
- [x] Test with syntax check ✅

**Completed:** 2025-11-20 (100% complete)

**See:** `DAY5_PROGRESS.md` for complete implementation details

**Notes:**
- Phase 5 schema migration already complete ✅ (`prediction_worker_runs` table exists)
- Phase 5 uses system-level circuit breakers, not processor-level
- Different from Phase 3/4: Can have partial success (3 out of 5 systems work)
- All helper classes complete and syntax-checked ✅
- Worker fully integrated with all 5 systems wrapped in circuit breakers ✅

---

### Day 6: Deploy & Initial Monitoring (30 minutes)

**Status:** 🔴 Not Started

- [ ] Run tests
  - [ ] Unit tests for mixins
  - [ ] Integration tests for processors
- [ ] Deploy to Cloud Run
  - [ ] Deploy Phase 3 processors
  - [ ] Deploy Phase 4 processors
  - [ ] Deploy Phase 5 processors
- [ ] Initial smoke tests
  - [ ] Trigger one processor manually
  - [ ] Check logs for pattern usage
  - [ ] Verify no errors

**Completed:** _Not yet_

**Notes:**
-

---

## Week 2: Monitoring Setup

**Target:** Complete in 2 hours
**Status:** 🔴 Not Started

### Task 1: Create Monitoring Scripts (1 hour)

**Status:** 🔴 Not Started

- [ ] Create script directory
  - [ ] `mkdir -p monitoring/scripts`
- [ ] Daily health check script
  - [ ] `monitoring/scripts/check_pattern_health.py`
  - [ ] Test locally
  - [ ] Set up Cloud Scheduler job (daily 6 AM)
- [ ] Decision query script
  - [ ] `monitoring/scripts/pattern_decision_queries.py`
  - [ ] Test locally
  - [ ] Document usage
- [ ] Weekly effectiveness report
  - [ ] `monitoring/scripts/pattern_effectiveness_report.py`
  - [ ] Test locally
  - [ ] Set up Cloud Scheduler job (Monday 8 AM)

**Completed:** _Not yet_

**Notes:**
-

---

### Task 2: Create Grafana Dashboard (1 hour)

**Status:** 🔴 Not Started

- [ ] Create dashboard JSON
  - [ ] `monitoring/dashboards/pattern-effectiveness.json`
  - [ ] Panel: Smart Skip effectiveness
  - [ ] Panel: Early Exit impact
  - [ ] Panel: Circuit Breaker status
  - [ ] Panel: Pattern adoption by processor
- [ ] Import to Grafana
  - [ ] Test all panels load correctly
  - [ ] Verify data sources connected
- [ ] Configure alerts
  - [ ] Alert: Circuit breaker opened
  - [ ] Alert: Skip rate > 80% (might be misconfigured)
  - [ ] Alert: No pattern usage detected

**Completed:** _Not yet_

**Notes:**
-

---

## Week 1-8: Data Collection Period

**Status:** 🔴 Not Started

### Monitoring Checklist

**Daily (automated):**
- [ ] Pattern health check runs (6 AM)
- [ ] Review health check output
- [ ] Check Grafana dashboard
- [ ] Verify no circuit breakers stuck open

**Weekly (automated):**
- [ ] Effectiveness report runs (Monday 8 AM)
- [ ] Review effectiveness metrics
- [ ] Identify any issues or trends
- [ ] Adjust pattern configurations if needed

**Manual tracking:**
- [ ] Week 1: Initial baseline
- [ ] Week 2: Stability check
- [ ] Week 3: Performance review
- [ ] Week 4: **Mid-point decision check** (see below)
- [ ] Week 5: Continue monitoring
- [ ] Week 6: Continue monitoring
- [ ] Week 7: Continue monitoring
- [ ] Week 8: **Final decision point** (see below)

**Notes:**
-

---

## Week 4: Mid-Point Check

**Target:** Review data, decide on any adjustments
**Status:** 🔴 Not Started

### Decision Queries to Run

- [ ] Run Pattern #13 decision query (slow queries)
  - [ ] `python monitoring/scripts/pattern_decision_queries.py --pattern=caching`
  - [ ] Document results
  - [ ] **Decision:** Implement Pattern #13? Yes / No / Wait
- [ ] Run Pattern #14 decision query (duplicates)
  - [ ] `python monitoring/scripts/pattern_decision_queries.py --pattern=idempotency`
  - [ ] Document results
  - [ ] **Decision:** Implement Pattern #14? Yes / No / Wait
- [ ] Run Pattern #15 decision query (gaps)
  - [ ] `python monitoring/scripts/pattern_decision_queries.py --pattern=backfill`
  - [ ] Document results
  - [ ] **Decision:** Implement Pattern #15? Yes / No / Wait

**Decisions Made:**
- Pattern #13 (Caching): _TBD_
- Pattern #14 (Idempotency): _TBD_
- Pattern #15 (Backfill): _TBD_

**Notes:**
-

---

## Week 8: Phase 3 Decision

**Target:** Decide on Phase 3 (entity-level processing)
**Status:** 🔴 Not Started

### Final Review

- [ ] Review all monitoring data from Week 1-8
- [ ] Run final decision queries
  - [ ] Pattern #13: Slow queries still an issue?
  - [ ] Pattern #14: Duplicates still frequent?
  - [ ] Pattern #15: Gaps still occurring?
- [ ] Assess Phase 3 need
  - [ ] Entity-level optimization needed?
  - [ ] Batch coalescing needed (Pattern #7)?
  - [ ] Processing priority needed (Pattern #8)?
  - [ ] Checkpoints needed (Pattern #6)?
  - [ ] Change classification needed (Pattern #12)?

**Phase 3 Decision:** _TBD_
- [ ] Stay in Phase 1 (date-range processing)
- [ ] Move to Phase 3 (entity-level processing)
- [ ] Hybrid approach

**Rationale:**
-

**Next Steps:**
-

---

## Situational Pattern Implementation

**Implement these ONLY if Week 4/8 data shows need**

### Pattern #13: Smart Caching

**Status:** 🔴 Not Decided Yet

**Criteria:** Slow queries > 20 min/day

- [ ] Week 4 check: _Result TBD_
- [ ] Week 8 check: _Result TBD_
- [ ] **Decision:** _TBD_

**If implementing:**
- [ ] Add SmartCacheMixin to affected processors
- [ ] Configure cache TTL
- [ ] Optional: Set up Redis if multi-instance
- [ ] Monitor cache hit rates

**Completed:** _Not yet_

---

### Pattern #14: Smart Idempotency

**Status:** 🔴 Not Decided Yet

**Criteria:** Duplicate processing > 10%

- [ ] Week 4 check: _Result TBD_
- [ ] Week 8 check: _Result TBD_
- [ ] **Decision:** _TBD_

**If implementing:**
- [ ] Create `processing_keys` table
- [ ] Add SmartIdempotencyMixin to affected processors
- [ ] Configure idempotency window
- [ ] Set up weekly cleanup job
- [ ] Monitor duplicate prevention

**Completed:** _Not yet_

---

### Pattern #15: Smart Backfill

**Status:** 🔴 Not Decided Yet

**Criteria:** Dependency gaps > 3/week

- [ ] Week 4 check: _Result TBD_
- [ ] Week 8 check: _Result TBD_
- [ ] **Decision:** _TBD_

**If implementing:**
- [ ] Add SmartBackfillMixin to affected processors
- [ ] Configure auto-backfill threshold
- [ ] Set up gap detection monitoring
- [ ] Monitor backfill effectiveness

**Completed:** _Not yet_

---

## Phase 3 Pattern Implementation

**Implement these ONLY if moving to Phase 3**

### Pattern #6: Processing Checkpoints

**Status:** 🔴 Phase 3 Only

**Criteria:** Phase 3 + frequent failures + long processing

- [ ] Phase 3 decision: _TBD_
- [ ] Failure analysis: _TBD_
- [ ] **Decision:** _TBD_

**If implementing:**
- [ ] Add checkpoint tracking infrastructure
- [ ] Add ProcessingCheckpointsMixin
- [ ] Configure checkpoint frequency
- [ ] Monitor recovery success rate

---

### Pattern #7: Batch Coalescing

**Status:** 🔴 Phase 3 Only

**Criteria:** Phase 3 + burst updates > 5/30 seconds

- [ ] Phase 3 decision: _TBD_
- [ ] Burst analysis: _TBD_
- [ ] **Decision:** _TBD_

**If implementing:**
- [ ] Add entity buffering infrastructure
- [ ] Add BatchCoalescingMixin
- [ ] Configure coalescing window
- [ ] Monitor batch sizes

---

### Pattern #8: Processing Priority

**Status:** 🔴 Phase 3 Only

**Criteria:** Phase 3 + critical updates delayed

- [ ] Phase 3 decision: _TBD_
- [ ] Priority analysis: _TBD_
- [ ] **Decision:** _TBD_

**If implementing:**
- [ ] Add priority queue infrastructure
- [ ] Add ProcessingPriorityMixin
- [ ] Configure priority levels
- [ ] Monitor queue latency by priority

---

### Pattern #12: Change Classification

**Status:** 🔴 Phase 3 Only

**Criteria:** Phase 3 + minor-change noise > 30%

- [ ] Phase 3 decision: _TBD_
- [ ] Noise analysis: _TBD_
- [ ] **Decision:** _TBD_

**If implementing:**
- [ ] Add field-level change detection
- [ ] Add ChangeClassificationMixin
- [ ] Configure field priorities
- [ ] Monitor noise reduction

---

## Historical Backfill Strategy (Post-Week 8)

**Status:** 📝 Planning Phase
**Timeline:** After Phase 1-5 validated with current data
**Scope:** 4 NBA seasons (2019-2020 through current 2024-2025)
**Estimated Volume:** ~800-1000 game dates, ~30,000 games

---

### Overview & Requirements

**Purpose:** Populate analytics tables with 4 years of historical data for:
1. **ML Training Data** - Need historical outcomes to train prediction models
2. **Context Calculations** - Current predictions need rolling averages, season stats, matchup history
3. **Validation** - Verify system works across different seasons and scenarios

**Critical Constraint:** **Sequential processing required**
- Must process 2019-10-22 BEFORE 2019-10-23
- Rolling averages depend on prior dates existing
- Season statistics accumulate over time
- Cannot parallelize across dates (but CAN parallelize within a date)

**Backfill vs Production Mode Differences:**

| Aspect | Production Mode | Backfill Mode |
|--------|----------------|---------------|
| **Trigger** | Pub/Sub (event-driven) | Orchestration script (date loop) |
| **Processing Order** | Any order (async) | Sequential by date (sync) |
| **Date Range** | Current date ± few days | 2019-10-22 → today |
| **Dependencies** | Assume data available | Building up incrementally |
| **Validation** | Monitor for anomalies | MUST validate before next date |
| **Speed Priority** | Skip what you can | Process thoroughly |
| **Error Handling** | Retry a few times | More tolerant, investigate |

---

### Open Questions & Decisions Needed

**🔴 CRITICAL - Need to Decide:**

1. **What scraped data do we have?**
   - [ ] Audit existing Phase 2 data coverage (2019-2025)
   - [ ] Identify gaps in scraper data
   - [ ] Determine what additional scraping is needed
   - **Question:** Do we have game_schedule for all dates? (needed for Early Exit pattern)
   - **Question:** Do we have boxscores for all games?
   - **Question:** Do we have odds data historically? (often missing for old dates)

2. **How to handle missing scraped data?**
   - **Option A:** Skip dates with missing data (document gaps)
   - **Option B:** Backfill scrapers first, then run analytics
   - **Option C:** Partial processing (process what we have, mark missing)
   - **Decision:** _TBD_

3. **Processing order within a date?**
   - **Option A:** Strict dependency order (Phase 2 → Phase 3 → Phase 4 → Phase 5)
   - **Option B:** Parallel within phase, sequential across phases
   - **Option C:** Intelligent dependency graph (process when dependencies ready)
   - **Decision:** _TBD_
   - **Research:** How long does one date take to process? (affects feasibility)

4. **Validation threshold for proceeding?**
   - **Question:** What % completion is acceptable before moving to next date?
   - 100%? 95%? 90%?
   - **Question:** Which failures are blocking vs warning?
   - Circuit breaker open = blocking?
   - Missing non-critical data = warning?
   - **Decision:** _TBD_

5. **Backfill speed vs thoroughness trade-off?**
   - **Fast:** Process 1 date per hour = 1000 hours (42 days)
   - **Thorough:** Process 1 date per 4 hours = 4000 hours (167 days)
   - **Question:** Can we parallelize within a date to speed up?
   - **Question:** What's acceptable timeline for backfill completion?
   - **Decision:** _TBD_

6. **How to track backfill progress?**
   - **Option A:** Simple log file with completed dates
   - **Option B:** Database table tracking state per date
   - **Option C:** Checkpointing system (resume from failure)
   - **Decision:** _TBD_

---

### Technical Challenges to Figure Out

**🟡 IMPORTANT - Need to Research:**

1. **Missing Historical Dependencies**

   **Challenge:** Early dates lack prior data for calculations

   **Examples:**
   - 2019-10-22 (season opener): No prior games for rolling averages
   - First 10 games of season: Rolling 10-game average incomplete
   - New players (rookies): No historical stats

   **Questions to answer:**
   - How do we handle NULL rolling averages? Use available games? League average?
   - Do we backfill season stats retroactively after more data available?
   - How do we mark which calculations are "incomplete" due to missing data?

   **Proposed approach:**
   ```python
   # Graceful degradation
   def calculate_rolling_average(player_id, game_date, stat, window=10):
       prior_games = get_prior_games(player_id, game_date, limit=window)

       if len(prior_games) == 0:
           return None, 'no_prior_games'
       elif len(prior_games) < window:
           return calculate_avg(prior_games), f'partial_{len(prior_games)}_games'
       else:
           return calculate_avg(prior_games), 'complete'
   ```

   **Need to decide:** Document strategy in metadata? Add `calculation_quality` field?

2. **Pattern Configuration for Backfill Mode**

   **Challenge:** Patterns optimized for production hurt backfill

   **Pattern #1 (Smart Skip):**
   - Production: Skip irrelevant sources
   - Backfill: Need ALL sources to populate historical data
   - **Solution:** Disable in backfill mode? Override RELEVANT_SOURCES?

   **Pattern #3 (Early Exit):**
   - Production: Skip historical games (no odds updates needed)
   - Backfill: Must process historical games (building the data!)
   - **Solution:** Disable no_games check? Use game state but process HISTORICAL?

   **Pattern #5 (Circuit Breaker):**
   - Production: Open after 5 failures (prevent cascade)
   - Backfill: More tolerant (historical issues might not matter)
   - **Solution:** Higher threshold? Different recovery strategy?

   **Pattern #13 (Caching):**
   - Production: Cache rolling averages (reused frequently)
   - Backfill: No reuse (one-time processing per date)
   - **Solution:** Disable caching entirely in backfill mode?

   **Need to implement:** `backfill_mode` flag system

3. **Validation Strategy**

   **Challenge:** How to verify date processed correctly before moving on?

   **Questions:**
   - What constitutes "complete" for a date?
   - Which processors MUST succeed vs nice-to-have?
   - How to detect silent failures (processor ran but produced garbage)?
   - Can we validate data quality automatically or need manual review?

   **Validation levels to define:**

   **Level 1: Execution Validation**
   ```sql
   -- Did all processors run?
   SELECT processor_name, status, COUNT(*)
   FROM analytics_processing_metadata
   WHERE game_date = '2019-10-22'
   GROUP BY processor_name, status

   -- Expected: All processors status = 'completed'
   ```

   **Level 2: Output Validation**
   ```sql
   -- Did processors produce data?
   SELECT
       'player_game_summary' as table_name,
       COUNT(*) as row_count,
       COUNT(DISTINCT universal_player_id) as unique_players
   FROM nba_analytics.player_game_summary
   WHERE game_date = '2019-10-22'

   -- Expected: row_count ≈ 240 (10 games × ~24 players)
   -- If 0: FAIL
   -- If < 100: WARNING
   ```

   **Level 3: Data Quality Validation**
   ```sql
   -- Are values reasonable?
   SELECT
       COUNT(*) as total_rows,
       COUNTIF(points IS NULL) as null_points,
       COUNTIF(points < 0) as negative_points,
       COUNTIF(points > 100) as impossible_points,
       AVG(points) as avg_points
   FROM nba_analytics.player_game_summary
   WHERE game_date = '2019-10-22'

   -- Expected: null_points = 0, negative = 0, avg ≈ 10-15
   ```

   **Need to decide:**
   - Validation checklist per phase
   - Automated vs manual validation
   - Blocking vs non-blocking validation failures

4. **Orchestration Architecture**

   **Challenge:** How to coordinate processing across 1000+ dates?

   **Options:**

   **Option A: Simple Python Script**
   ```python
   # bin/backfill/run_historical_backfill.py
   for date in date_range('2019-10-22', 'today'):
       process_date(date)
       validate_date(date)
       if not valid:
           log_error_and_stop()
   ```
   - ✅ Simple
   - ❌ No parallelization
   - ❌ Hard to resume from failures

   **Option B: Cloud Workflows**
   ```yaml
   # Workflow orchestrates phases sequentially
   # Can retry, has state management
   # Can parallelize within date
   ```
   - ✅ Built-in retry/error handling
   - ✅ Can parallelize processors within date
   - ❌ More complex to set up

   **Option C: Airflow DAG**
   ```python
   # DAG with dependency graph
   # Each date is a task
   # Sequential execution enforced
   ```
   - ✅ Powerful dependency management
   - ✅ Good UI for monitoring
   - ❌ Requires Airflow infrastructure

   **Need to decide:** Which approach? Research time/complexity trade-offs

5. **Recovery from Failures**

   **Challenge:** What if backfill fails halfway through?

   **Scenarios:**
   - Circuit breaker opens on date 2020-03-15 (COVID interruption in data?)
   - BigQuery quota exceeded on date 2021-05-20
   - Validation fails on date 2022-11-10
   - Infrastructure failure after processing 200 dates

   **Questions:**
   - Can we resume from checkpoint?
   - Do we reprocess failed date or skip?
   - How to investigate failures without blocking entire backfill?
   - Should we process in batches (1 month at a time) to limit blast radius?

   **Need to design:**
   - Checkpoint system
   - Failure investigation workflow
   - Skip/retry/abort decision tree

6. **Performance Optimization**

   **Challenge:** 1000 dates × 4 hours each = 167 days (unacceptable)

   **Optimization opportunities:**

   **Within-date parallelization:**
   - Phase 3 processors independent (can run in parallel)
   - Phase 4 processors independent (can run in parallel)
   - **Research:** Cloud Run max concurrency limits?

   **Batch processing:**
   - Process multiple games within date in single query?
   - Batch BigQuery writes across processors?

   **Smart skipping (for backfill):**
   - If Phase 2 data unchanged, skip Phase 3 reprocessing?
   - Cache intermediate results during backfill?

   **Need to measure:**
   - Current processing time per date (with test date)
   - Parallelization potential
   - BigQuery query costs for full backfill

---

### Pattern Behavior in Backfill Mode

**Configuration changes needed:**

**Pattern #1: Smart Skip**
```python
class SmartSkipMixin:
    def __init__(self, backfill_mode=False):
        self.backfill_mode = backfill_mode

    def should_process_source(self, source_table: str) -> bool:
        if self.backfill_mode:
            # In backfill mode, process ALL sources
            # We need to populate historical data
            return True

        # Normal production logic
        return self.RELEVANT_SOURCES.get(source_table, True)
```

**Pattern #3: Early Exit**
```python
class EarlyExitMixin:
    def __init__(self, backfill_mode=False):
        self.backfill_mode = backfill_mode

    def _is_too_historical(self, game_date: str) -> bool:
        if self.backfill_mode:
            # In backfill mode, historical is the point!
            return False

        # Normal production logic
        return (datetime.now() - game_date).days > 90
```

**Pattern #5: Circuit Breaker**
```python
class CircuitBreakerMixin:
    def __init__(self, backfill_mode=False):
        # Higher threshold in backfill mode
        self.CIRCUIT_BREAKER_THRESHOLD = 10 if backfill_mode else 5
        self.CIRCUIT_BREAKER_TIMEOUT = 600 if backfill_mode else 300
```

**Pattern #13: Caching**
```python
class SmartCacheMixin:
    def __init__(self, backfill_mode=False):
        # Disable caching in backfill mode (no reuse)
        self.CACHE_ENABLED = not backfill_mode
```

**Need to implement:**
- [ ] Add `backfill_mode` parameter to AnalyticsProcessorBase
- [ ] Propagate to all mixins
- [ ] Add runtime configuration (environment variable? CLI flag?)

---

### Validation Framework Design

**Per-Date Validation Checklist:**

**✅ Phase 1: Execution Validation**
- [ ] All Phase 3 processors completed (no failures)
- [ ] All Phase 4 processors completed (no failures)
- [ ] All Phase 5 processors completed (no failures)
- [ ] No circuit breakers in OPEN state
- [ ] Processing time reasonable (< 4 hours per date?)

**✅ Phase 2: Output Volume Validation**
- [ ] player_game_summary: ~240 rows (10 games × 24 players)
- [ ] team_game_summary: ~20 rows (10 games × 2 teams)
- [ ] player_prop_predictions: ~1000 rows (predictable props)
- [ ] All tables have > 0 rows

**✅ Phase 3: Data Quality Validation**
- [ ] No NULL values in required fields
- [ ] No impossible values (negative points, > 100 rebounds, etc.)
- [ ] Averages within reasonable ranges
- [ ] All foreign keys resolve (player_id exists, team_id exists)

**✅ Phase 4: Dependency Chain Validation**
- [ ] Phase 3 tables updated_at > Phase 2 tables updated_at
- [ ] Phase 4 tables updated_at > Phase 3 tables updated_at
- [ ] Phase 5 tables updated_at > Phase 4 tables updated_at

**✅ Phase 5: Business Logic Validation (Sampling)**
- [ ] Sample 10 players: rolling averages calculated correctly
- [ ] Sample 5 teams: matchup history calculated correctly
- [ ] Sample predictions: values reasonable

**Tool to build:** `bin/backfill/validate_date.py`
```bash
# Usage
python bin/backfill/validate_date.py --date 2019-10-22 --level all

# Output
# ✅ Execution: PASS
# ✅ Output Volume: PASS
# ✅ Data Quality: PASS
# ✅ Dependencies: PASS
# ⚠️  Business Logic: WARNING (2 players missing data)
#
# Overall: PASS (safe to proceed)
```

---

### Missing Data Handling Strategy

**Types of Missing Data:**

**1. Missing Scraped Data (Phase 2)**
- **Example:** No odds data for 2019 games
- **Impact:** Can't calculate odds-based features
- **Strategy:**
  - Mark as missing in metadata: `missing_sources: ['odds_api_spreads']`
  - Proceed with partial data
  - Document coverage gaps
- **Alternative:** Attempt to scrape from alternative sources? (research needed)

**2. Missing Prior History (Early Season)**
- **Example:** 2019-10-22 has no prior games for rolling averages
- **Impact:** Can't calculate 10-game averages
- **Strategy:**
  - Use available games (< 10): Mark as `partial_rolling_avg_5_games`
  - Store calculation quality in metadata
  - Flag for potential reprocessing later

**3. Missing Dependencies (New Players)**
- **Example:** Rookie has no historical stats
- **Impact:** Can't calculate season averages, matchup history
- **Strategy:**
  - Use NULL for missing values
  - Use league averages as fallback?
  - Mark in metadata: `missing_player_history: true`

**Metadata schema additions:**
```python
processing_metadata = {
    # Existing fields
    'processor_name': 'PlayerGameSummaryProcessor',
    'game_date': '2019-10-22',
    'status': 'completed',

    # NEW: Backfill-specific metadata
    'backfill_mode': True,
    'missing_sources': ['odds_api_spreads'],  # Scraped data gaps
    'incomplete_calculations': {
        'rolling_avg_10': 'partial_3_games',  # Only 3 prior games
        'season_avg': 'complete',
        'matchup_history': 'no_prior_matchups'
    },
    'data_quality_score': 0.85,  # 85% complete
    'can_use_for_ml_training': False,  # Too incomplete
}
```

**Need to decide:**
- Minimum data quality score to consider "valid"
- Which incomplete calculations are blocking vs acceptable
- How to mark data as "ML training quality" vs "reference only"

---

### Orchestration Script Design (High-Level)

**Pseudo-code for backfill orchestration:**

```python
# bin/backfill/orchestrate_historical_backfill.py

def run_historical_backfill(
    start_date='2019-10-22',
    end_date='today',
    batch_size=30,  # Process 1 month at a time
    validation_level='all'
):
    """
    Orchestrate sequential backfill of historical data.

    Strategy:
    1. Process dates sequentially (dependencies require order)
    2. Validate each date before proceeding
    3. Checkpoint progress for recovery
    4. Parallelize within date when possible
    """

    # Load checkpoint (resume from failures)
    checkpoint = load_checkpoint()
    current_date = checkpoint.get('last_completed_date', start_date)

    # Process in batches (for manageable chunks)
    for batch in batch_dates(current_date, end_date, batch_size):
        logger.info(f"Processing batch: {batch[0]} to {batch[-1]}")

        for date in batch:
            # STEP 1: Check if scraped data exists
            if not check_phase2_data_exists(date):
                logger.warning(f"Missing Phase 2 data for {date}, skipping")
                mark_date_skipped(date, reason='missing_phase2_data')
                continue

            # STEP 2: Process all phases for this date
            try:
                process_date_with_backfill_mode(date)
            except Exception as e:
                logger.error(f"Failed to process {date}: {e}")
                mark_date_failed(date, error=str(e))

                # Decision: skip and continue or abort?
                if is_critical_date(date):
                    raise  # Abort entire backfill
                else:
                    continue  # Skip and move on

            # STEP 3: Validate before proceeding
            validation_result = validate_date(date, level=validation_level)

            if not validation_result.passed:
                logger.error(f"Validation failed for {date}: {validation_result}")
                mark_date_failed(date, reason='validation_failed')

                # Decision: skip or abort?
                if validation_result.is_blocking:
                    raise
                else:
                    continue

            # STEP 4: Update checkpoint
            save_checkpoint({'last_completed_date': date})
            logger.info(f"✅ {date} completed and validated")

        logger.info(f"Batch completed: {batch[0]} to {batch[-1]}")

        # Optional: Generate batch report
        generate_batch_report(batch)

def process_date_with_backfill_mode(game_date: str):
    """Process all phases for a single date with backfill mode enabled."""

    # Set backfill mode globally
    os.environ['BACKFILL_MODE'] = 'true'

    # Phase 3: Analytics (can parallelize within phase)
    phase3_processors = [
        'PlayerGameSummaryProcessor',
        'TeamDefenseSummaryProcessor',
        'UpcomingPlayerGameContextProcessor',
    ]

    # Run Phase 3 in parallel
    run_processors_parallel(phase3_processors, game_date)

    # Phase 4: Aggregations (depends on Phase 3)
    phase4_processors = [
        'TeamAggregationProcessor',
        'MatchupHistoryProcessor',
    ]

    run_processors_parallel(phase4_processors, game_date)

    # Phase 5: Predictions (depends on Phase 4)
    phase5_processors = [
        'PlayerPropPredictionProcessor',
        'GameOutcomePredictionProcessor',
    ]

    run_processors_parallel(phase5_processors, game_date)

    # Clear backfill mode
    del os.environ['BACKFILL_MODE']

def validate_date(game_date: str, level: str) -> ValidationResult:
    """Run validation checks for a processed date."""
    # See validation framework section above
    pass

# Questions to answer before implementing:
# 1. How long does one date take to process?
# 2. Can we actually parallelize within phase?
# 3. What's the failure rate? (affects batch_size)
# 4. How much BigQuery quota do we use per date?
```

**Need to implement:**
- [ ] Checkpoint system (JSON file? Database table?)
- [ ] Parallel processor execution (Cloud Run concurrent requests?)
- [ ] Validation tooling
- [ ] Progress reporting/dashboard
- [ ] Error investigation workflow

---

### Implementation Timeline (Tentative)

**Prerequisites (must complete first):**
- [ ] Phase 1-5 implemented and tested with current data
- [ ] Week 8 decision made (Phase 3 or not)
- [ ] All foundation patterns deployed and stable
- [ ] Monitoring in place and working

**Phase A: Planning & Research (1-2 weeks)**
- [ ] Audit Phase 2 data coverage (what do we have?)
- [ ] Test processing 1 historical date (measure time, identify issues)
- [ ] Design validation framework
- [ ] Decide on orchestration approach
- [ ] Design backfill_mode flag system

**Phase B: Infrastructure (1-2 weeks)**
- [ ] Implement backfill_mode flag propagation
- [ ] Create validation tooling (`bin/backfill/validate_date.py`)
- [ ] Create orchestration script (`bin/backfill/orchestrate_historical_backfill.py`)
- [ ] Set up checkpoint system
- [ ] Create monitoring dashboard for backfill progress

**Phase C: Pilot Run (1 week)**
- [ ] Test on 1 month of data (October 2019)
- [ ] Validate results manually
- [ ] Measure performance (time per date)
- [ ] Identify issues and iterate
- [ ] Document any missing data patterns

**Phase D: Full Backfill (4-8 weeks)**
- [ ] Run full backfill (2019-2025)
- [ ] Monitor progress daily
- [ ] Investigate and resolve failures
- [ ] Generate validation reports
- [ ] Document data quality issues

**Phase E: Validation & Cleanup (1 week)**
- [ ] Comprehensive validation across all dates
- [ ] Sample testing for data quality
- [ ] Document gaps and limitations
- [ ] Mark ML-training-ready data

**Total estimated timeline:** 8-14 weeks after Phase 1-5 complete

---

### Deferred Implementation Details

**Don't implement these yet - will design when ready:**

1. ❌ Detailed orchestration script code
2. ❌ Validation tooling implementation
3. ❌ Checkpoint system details
4. ❌ Parallel processing infrastructure
5. ❌ Error recovery workflows
6. ❌ Data quality scoring algorithm
7. ❌ ML training data selection criteria
8. ❌ Performance optimization strategies

**Why defer:**
- Phase 1-5 not finalized yet
- Patterns might evolve
- Schema might change
- Will learn from pilot run
- Premature optimization

**What we HAVE documented:**
- ✅ Requirements and constraints
- ✅ Open questions to answer
- ✅ Technical challenges to solve
- ✅ High-level strategy
- ✅ Validation approach
- ✅ Pattern configuration needs

---

### Next Steps (When Ready to Start)

**Before starting backfill implementation:**

1. [ ] Complete Week 8 review and Phase 3 decision
2. [ ] Ensure all phases stable with current data
3. [ ] Review and answer all open questions in this section
4. [ ] Make decisions on all "TBD" items
5. [ ] Create detailed implementation plan (Phase A-E above)
6. [ ] Get approval for timeline and resource commitment

**First concrete task:**
- [ ] Audit Phase 2 data coverage (2019-2025)
- [ ] Answer: "What scraped data do we actually have?"

---

## Learnings & Notes

### Issues Encountered

_Document any issues here as they come up_

---

### Configuration Adjustments

_Document any pattern configuration changes_

---

### Performance Observations

_Document any performance improvements or regressions_

---

### Unexpected Benefits

_Document any unexpected positive outcomes_

---

## Reference Links

### Pattern Documentation
- [Pattern Catalog](../reference/02-optimization-pattern-catalog.md)
- [Pattern #1: Smart Skip](../patterns/08-smart-skip-implementation.md)
- [Pattern #3: Early Exit](../patterns/03-early-exit-implementation.md)
- [Pattern #5: Circuit Breaker](../patterns/01-circuit-breaker-implementation.md)
- [Pattern #13: Smart Caching](../patterns/11-smart-caching-reference.md)
- [Pattern #14: Smart Idempotency](../patterns/12-smart-idempotency-reference.md)
- [Pattern #15: Smart Backfill](../patterns/09-smart-backfill-detection.md)

### Implementation Resources
- [Phase 2→3 Roadmap](../architecture/09-phase2-phase3-implementation-roadmap.md)
- [Week 1 Schema Changes](../architecture/10-week1-schema-and-code-changes.md)

---

**Last Updated:** 2025-11-20 9:14 PM PST (Day 1-2 complete: schemas + mixins)
**Next Review:** After Day 3 (patterns added to Phase 3 processors)
