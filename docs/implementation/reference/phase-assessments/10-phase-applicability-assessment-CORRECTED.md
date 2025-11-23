# Historical Dependency Checking - Phase Applicability Assessment (CORRECTED)

**Date:** 2025-11-22
**Context:** User request to apply completeness checking to "Phase 3 and Phase 4, maybe even phase 5"
**Status:** CORRECTED after reviewing actual schemas

---

## CORRECTION: Phase 3 Analysis

**My Initial Assessment Was WRONG**

I incorrectly stated only 2 of 5 Phase 3 processors need completeness checking. After reviewing the actual **schema files** (not just processor code), I found:

### Phase 3 Processors WITH Historical Dependencies: 2 of 5 ✅

**These DO calculate historical windows during processing:**

#### 1. upcoming_player_game_context ✅ CONFIRMED
**Schema Evidence:** `/schemas/bigquery/analytics/upcoming_player_game_context_tables.sql`

**Historical Fields Stored in Table** (lines 88-129):
```sql
-- PLAYER FATIGUE ANALYSIS (12 fields) - L7 days, L14 days
games_in_last_7_days INT64,                       -- Weekly load
games_in_last_14_days INT64,                      -- Bi-weekly load
minutes_in_last_7_days INT64,                     -- Weekly minutes
minutes_in_last_14_days INT64,                    -- Bi-weekly minutes
avg_minutes_per_game_last_7 NUMERIC(5,1),         -- Recent intensity
back_to_backs_last_14_days INT64,                 -- Recent compression

-- RECENT PERFORMANCE CONTEXT (8 fields) - L5, L10 games
points_avg_last_5 NUMERIC(5,1),                   -- Recent form
points_avg_last_10 NUMERIC(5,1),                  -- Broader trend
prop_over_streak INT64,                           -- Current over streak
prop_under_streak INT64,                          -- Current under streak
```

**Processor Code** (lines 84, 942-994, 996-1037):
- `lookback_days = 30` - queries last 30 days of boxscores
- Calculates: `days_rest`, `games_in_last_7_days`, `games_in_last_14_days`, `minutes_in_last_7_days`, `avg_minutes_per_game_last_7`, `back_to_backs_last_14_days`
- Calculates: `points_avg_last_5`, `points_avg_last_10`

**Historical Windows:**
- **L30 days** (boxscore data)
- **L7 days** (fatigue metrics)
- **L14 days** (fatigue metrics)
- **L5 games** (performance metrics)
- **L10 games** (performance metrics)

**Needs Completeness Checking?** ✅ YES - Multiple historical windows

---

#### 2. upcoming_team_game_context ✅ CONFIRMED
**Schema Evidence:** `/schemas/bigquery/analytics/upcoming_team_game_context_tables.sql`

**Processor Code** (lines 432-433, 1046-1105, 1303-1370):
```python
# Extended lookback window
extended_start = start_date - timedelta(days=30)  # 30-day lookback
extended_end = end_date + timedelta(days=7)       # 7-day lookahead

# Fatigue context
team_days_rest
team_back_to_back
games_in_last_7_days
games_in_last_14_days

# Momentum context
team_win_streak_entering
team_loss_streak_entering
last_game_margin
last_game_result
```

**Historical Windows:**
- **L30 days** (schedule data)
- **L7 days** (game count)
- **L14 days** (game count)

**Needs Completeness Checking?** ✅ YES - Date-based historical windows

---

### Phase 3 Processors WITHOUT Historical Dependencies: 3 of 5 ❌

**These process single games only (point-in-time):**

#### 3. player_game_summary ❌ NO
**Schema Evidence:** `/schemas/bigquery/analytics/player_game_summary_tables.sql`

**Fields Stored:**
```sql
-- Single game stats only
points INT64
minutes_played NUMERIC(5,1)
assists INT64
rebounds INT64
```

**Note:** The `AVG()` queries I saw (lines 389-391, 414-415) are in **HELPER VIEWS** that analyze the table AFTER processing:
```sql
-- View 1: player_performance_summary (NOT part of processor)
CREATE OR REPLACE VIEW ... AS
SELECT
  player_lookup,
  AVG(points) as avg_points,  -- This is a POST-PROCESSING view
  AVG(ts_pct) as avg_ts_pct
```

**Processor Logic:**
- Processes ONE game at a time
- No lookback queries
- No historical windows

**Needs Completeness Checking?** ❌ NO - Point-in-time only

---

#### 4. team_offense_game_summary ❌ NO
**Schema Evidence:** `/schemas/bigquery/analytics/team_offense_game_summary_tables.sql`

**Processor Logic:**
- Processes ONE game at a time
- Aggregates Phase 2 player stats into team totals
- No lookback queries

**Needs Completeness Checking?** ❌ NO - Point-in-time only

---

#### 5. team_defense_game_summary ❌ NO
**Schema Evidence:** `/schemas/bigquery/analytics/team_defense_game_summary_tables.sql`

**Processor Logic:**
- Processes ONE game at a time
- Aggregates Phase 2 defensive stats
- No lookback queries

**Needs Completeness Checking?** ❌ NO - Point-in-time only

---

## Phase 3 Summary (CORRECTED)

| Processor | Historical Window | Needs Checking? | Notes |
|-----------|------------------|----------------|-------|
| player_game_summary | None | ❌ NO | Point-in-time game stats |
| team_offense_game_summary | None | ❌ NO | Point-in-time team stats |
| team_defense_game_summary | None | ❌ NO | Point-in-time team stats |
| **upcoming_player_game_context** | **L5/L7/L10/L14/L30** | ✅ YES | Multiple historical windows |
| **upcoming_team_game_context** | **L7/L14/L30** | ✅ YES | Fatigue + momentum metrics |

**Phase 3 Verdict:** **40% of processors need it** (2 of 5)

---

## What I Confused: Tables vs Views

**My Mistake:**
I saw `AVG()` queries in the schema files and thought those were stored fields. They're actually **helper views** for post-processing analysis.

**Example - player_game_summary_tables.sql:**
```sql
-- Line 31: THE TABLE (what processor writes)
CREATE TABLE IF NOT EXISTS player_game_summary (
  points INT64,  -- Single game value
  ...
);

-- Lines 380-400: HELPER VIEW (post-processing analysis)
CREATE OR REPLACE VIEW player_performance_summary AS
SELECT
  player_lookup,
  AVG(points) as avg_points,  -- Averages ACROSS multiple games
  AVG(ts_pct) as avg_ts_pct
FROM player_game_summary
GROUP BY player_lookup;
```

**The difference:**
- **Table fields** = stored during processing = would need completeness checking if historical
- **View calculations** = post-processing queries = don't need completeness checking

**What I learned:**
- `upcoming_player_game_context` stores `points_avg_last_5` **IN THE TABLE** (calculated during processing)
- `player_game_summary` has `AVG(points)` **IN A VIEW** (calculated after processing)

---

## Full Opus Document Saved

I've now saved the full Opus document you provided to:
`/docs/implementation/09-historical-dependency-checking-plan-v2.1-OPUS.md`

**Document includes:**
- Circuit breaker protection (max 3 attempts, 7-day gaps)
- Season boundary detection
- Multi-window ALL-complete logic
- Concrete alert thresholds (Day 10: 30%, Day 20: 80%, Day 30: 95%)
- Integration testing checklists per week
- Hybrid reprocessing (auto for 60 days, manual for historical)
- Decision visibility schema
- Comprehensive monitoring with 6 BigQuery views
- Rollback procedures
- Cost analysis (~$2.60/month)
- Timeline: 6-10 weeks (realistic: 8-10 weeks)

---

## Updated Recommendation

### Option 1: Phase 4 Only (Original Opus Scope) ⭐ STILL RECOMMENDED

**Rationale:**
- Phase 4: 5 of 5 processors need it (100%)
- Phase 3: 2 of 5 processors need it (40%)
- **Phase 4 is more complex:**
  - Game-count windows (L10, L15 games) vs date-based windows (L7, L14 days)
  - Multi-window processors (player_daily_cache: L5/L7/L10/L14)
  - Bootstrap problem (first dates from 4 years ago)
  - Cascade dependencies (Phase 4 → Phase 4)
- **Opus document is Phase 4-focused** (proven design)
- **Phase 3 can be retrofitted later** (simpler date-based windows)

**Timeline:** 6-10 weeks
**Cost:** $2.60/month

---

### Option 2: Phase 3 + Phase 4 Simultaneously

**Scope:** 2 Phase 3 + 5 Phase 4 = 7 processors total

**Additional Complexity for Phase 3:**
- Different window types:
  - Phase 3: Date-based (L7 days, L14 days, L30 days)
  - Phase 4: Game-count (L10 games, L15 games)
- Different query patterns:
  - Phase 3: `WHERE game_date BETWEEN date - 30 AND date`
  - Phase 4: `WHERE game_rank <= 15` (ROW_NUMBER partitioning)

**Timeline:** 8-12 weeks (2-4 weeks longer)
**Cost:** ~$3.50/month (+$0.90 for Phase 3)

**Why longer:**
- Need to adapt Opus design for date-based windows
- Different schema additions (no game_rank logic needed)
- More integration testing (7 processors vs 5)

---

### Option 3: Phase 4 First, Then Phase 3 (Staged)

**Scope:**
- Stage 1: Phase 4 (6-10 weeks) → Learn from implementation
- Stage 2: Phase 3 (2-3 weeks) → Apply learnings to simpler case

**Why this is smart:**
- **Learn the hard parts first** (game-count windows, multi-window, bootstrap)
- **Apply to easier case** (date-based windows are simpler)
- **Can pause after Phase 4** if needed (Phase 3 less critical)

**Timeline:** 8-13 weeks total (staged)
**Cost:** $3.50/month (after both complete)

---

## My Recommendation: Still Option 1 (Phase 4 Only)

**Why:**
1. **Phase 4 = 100% need**, Phase 3 = 40% need
2. **Opus document is Phase 4-focused** (comprehensive, proven)
3. **Phase 3 processors are less critical:**
   - `upcoming_player_game_context` = pre-game analysis (helpful but not core predictions)
   - `upcoming_team_game_context` = pre-game analysis
4. **Can monitor Phase 3 quality manually** while Phase 4 rolls out
5. **Phase 3 retrofitting is simpler** (date-based windows, no bootstrap problem)

**Implementation Plan:**
1. **Weeks 1-10:** Implement Opus plan for Phase 4 (all 5 processors)
2. **Week 11:** Monitor Phase 3 quality (are there issues?)
3. **Decision Point:**
   - If Phase 3 quality issues emerge → Extend completeness checking (2-3 weeks)
   - If Phase 3 quality is fine → Defer extension

**Phase 3 can wait because:**
- Only 2 processors need it (vs 5 for Phase 4)
- "Upcoming context" tables are pre-game analysis (not core predictions like Phase 4)
- Simpler to retrofit (date-based windows, no game-count complexity)
- Lower priority than getting Phase 4 rock-solid first

---

## Phase 5 Assessment (Services, Not Processors)

You're right - Phase 5 is in `/predictions/` and uses services, not processors.

**From the Opus document:**
- Phase 5 already addressed via **Decision Visibility Schema**
- Services can track: `was_processed`, `skip_reason`, `upstream_completeness_pct`
- Same pattern applies: track all processing decisions (success + skip)

**When Phase 5 needs it:**
- When prediction services depend on Phase 4 precompute data
- Use Phase 4's `is_production_ready` flags to filter input
- Track prediction attempts (successful vs skipped due to incomplete upstream)

**Already covered in Opus document** (lines addressing Phase 5 integration)

---

## Key Insight from Schema Review

**Helper Views ≠ Processor Logic**

Many schema files have **helper views** with `AVG()`, `SUM()`, etc. - these are POST-PROCESSING analysis queries, not part of the processor's calculation logic.

**Rule of thumb:**
- **CREATE TABLE** = what processor writes → check for historical fields
- **CREATE VIEW** = post-processing analysis → ignore for completeness checking

**Example:**
```sql
-- Processor writes THIS (single game)
CREATE TABLE player_game_summary (
  points INT64,  -- Single value per game
  game_date DATE
);

-- Analysts query THIS (aggregates across games)
CREATE VIEW player_averages AS
SELECT
  player_id,
  AVG(points) as avg_points  -- This is NOT stored, it's calculated on-demand
FROM player_game_summary
GROUP BY player_id;
```

---

## Summary of All Documents Created

1. **Full Opus Plan (v2.1):** `/docs/implementation/09-historical-dependency-checking-plan-v2.1-OPUS.md`
   - Complete implementation guide from Opus AI
   - Circuit breaker, multi-window, monitoring, rollback
   - 6-10 week timeline, $2.60/month cost

2. **Phase Applicability Assessment:** `/docs/implementation/10-phase-applicability-assessment.md`
   - My initial (incorrect) assessment
   - Superseded by corrected version below

3. **Phase Applicability Assessment (CORRECTED):** `/docs/implementation/10-phase-applicability-assessment-CORRECTED.md` (this document)
   - Corrected after reviewing actual schemas
   - Phase 3: 2 of 5 need it (40%)
   - Phase 4: 5 of 5 need it (100%)
   - Phase 5: covered via decision visibility

---

## Next Steps

**Recommend you:**
1. Review the full Opus document (file #1 above)
2. Review this corrected assessment (this file)
3. Decide on scope:
   - **Option 1 (recommended):** Phase 4 only (6-10 weeks)
   - **Option 2:** Phase 3 + 4 simultaneously (8-12 weeks)
   - **Option 3:** Phase 4 first, then Phase 3 (8-13 weeks staged)

**Before starting implementation, you need to decide:**
- Which phases to include? (I recommend Phase 4 only initially)
- What's the timeline? (6-10 weeks realistic? Or extend to 12 weeks?)
- What's the priority? (Block other work? Or parallel development?)

**I can start implementation once you approve the scope.**
