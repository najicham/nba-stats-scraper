# Historical Dependency Checking - Phase Applicability Assessment

**Date:** 2025-11-22
**Context:** User request to apply completeness checking to "Phase 3 and Phase 4, maybe even Phase 5"
**Decision Required:** Which phases need this feature? Should we implement now or save for later?

---

## Executive Summary

**Recommendation:** **PARTIALLY APPLICABLE** across phases
- **Phase 3**: 2 of 5 processors need it (40%)
- **Phase 4**: 5 of 5 processors need it (100%) ✅ PRIMARY TARGET
- **Phase 5**: Would need it when implemented (predictions)

**Next Action:** Implement for Phase 4 first (highest need), then extend to relevant Phase 3 processors

---

## Phase 3 Analytics - Detailed Assessment

### Processors WITHOUT Historical Dependencies (3 processors - 60%)

**Point-in-time processors** that only process specific dates, no lookback:

#### 1. player_game_summary_processor.py
- **Query Pattern**: `WHERE game_date BETWEEN '{start_date}' AND '{end_date}'`
- **Data Access**: Single-date only (lines 230-396)
- **Dependency Type**: Date match (same day)
- **Historical Window**: NONE
- **Needs Completeness Checking?** ❌ NO

#### 2. team_offense_game_summary_processor.py
- **Query Pattern**: `WHERE game_date BETWEEN '{start_date}' AND '{end_date}'`
- **Data Access**: Single-date only (lines 198-252)
- **Dependency Type**: Date match (same day)
- **Historical Window**: NONE
- **Needs Completeness Checking?** ❌ NO

#### 3. team_defense_game_summary_processor.py
- **Query Pattern**: `WHERE game_date BETWEEN '{start_date}' AND '{end_date}'`
- **Data Access**: Single-date only (lines 225-343, 423-454)
- **Dependency Type**: Date match (same day)
- **Historical Window**: NONE
- **Needs Completeness Checking?** ❌ NO

**Why they don't need it:**
- Process one date at a time (no rolling windows)
- If Phase 2 data exists for date X, they can process date X
- No dependency on historical data quality
- Simple reprocessing (just rerun for that date)

---

### Processors WITH Historical Dependencies (2 processors - 40%)

**Context processors** that require historical lookback windows:

#### 4. upcoming_player_game_context_processor.py ✅ NEEDS IT
- **Query Pattern**: `WHERE player_lookup IN (...) AND game_date >= '{start_date}' AND game_date < '{self.target_date}'`
- **Historical Window**: **L30 days** (line 418: `lookback_days = 30`)
- **Window Type**: Date-based (last 30 calendar days)
- **Uses History For**:
  - Fatigue metrics (lines 942-994)
    - `days_rest`, `back_to_back`, `games_in_last_7_days`, `games_in_last_14_days`
    - `minutes_in_last_7_days`, `avg_minutes_per_game_last_7`
  - Performance metrics (lines 996-1037)
    - `points_avg_last_5`, `points_avg_last_10`

**Evidence from code:**
```python
# Line 418
start_date = self.target_date - timedelta(days=self.lookback_days)  # 30 days

# Lines 436-441 - Historical extraction
query = f"""
SELECT player_lookup, game_date, team_abbr, points, minutes, ...
FROM nba_raw.bdl_player_boxscores
WHERE player_lookup IN ('{player_lookups_str}')
  AND game_date >= '{start_date}'
  AND game_date < '{self.target_date}'
ORDER BY player_lookup, game_date DESC
"""
```

**Completeness Challenge:**
- If processing Nov 22, needs complete data from Oct 23 - Nov 21
- Missing even 1 day in that window affects fatigue calculations
- **Needs schedule-based completeness checking** ✅

#### 5. upcoming_team_game_context_processor.py ✅ NEEDS IT
- **Query Pattern**: Extended schedule window for context
- **Historical Window**: **L30 days lookback, 7 days lookahead** (lines 432-433)
- **Window Type**: Date-based (30 calendar days back)
- **Uses History For**:
  - Fatigue context (lines 1046-1105)
    - `team_days_rest`, `team_back_to_back`
    - `games_in_last_7_days`, `games_in_last_14_days`
  - Momentum context (lines 1303-1370)
    - `team_win_streak_entering`, `team_loss_streak_entering`
    - `last_game_margin`, `last_game_result`
  - Travel context (lines 1372-1414)

**Evidence from code:**
```python
# Lines 432-433
extended_start = start_date - timedelta(days=30)  # 30-day lookback
extended_end = end_date + timedelta(days=7)       # 7-day lookahead

# Lines 438-455 - Extended schedule extraction
query = f"""
SELECT game_id, game_date, season_year, home_team_tricode, away_team_tricode, ...
FROM nba_raw.nbac_schedule
WHERE game_date BETWEEN '{extended_start}' AND '{extended_end}'
  AND game_status IN (1, 3)  -- Scheduled or Final
ORDER BY game_date, game_id
"""
```

**Completeness Challenge:**
- If processing Nov 22, needs complete schedule from Oct 23 - Nov 29
- Missing games in that window breaks streak/fatigue calculations
- **Needs schedule-based completeness checking** ✅

---

## Phase 3 Summary

| Processor | Historical Window | Needs Checking? | Notes |
|-----------|------------------|----------------|-------|
| player_game_summary | None | ❌ NO | Point-in-time only |
| team_offense_game_summary | None | ❌ NO | Point-in-time only |
| team_defense_game_summary | None | ❌ NO | Point-in-time only |
| **upcoming_player_game_context** | **L30 days** | ✅ YES | Fatigue + performance metrics |
| **upcoming_team_game_context** | **L30 days** | ✅ YES | Fatigue + momentum + travel |

**Phase 3 Verdict:**
- **40% of processors need it** (2 of 5)
- Focus on the 2 "upcoming context" processors
- Skip the 3 "game summary" processors (unnecessary)

---

## Phase 4 Precompute - Assessment

**Already covered in Opus document** (docs/implementation/09-historical-dependency-checking-plan-v2.1-OPUS.md)

All 5 Phase 4 processors use historical windows:

| Processor | Historical Window | Needs Checking? |
|-----------|------------------|----------------|
| team_defense_zone_analysis | L15 games | ✅ YES |
| player_shot_zone_analysis | L10/L20 games | ✅ YES |
| player_daily_cache | L5/L7/L10/L14 mixed | ✅ YES |
| player_composite_factors | Cascade dependencies | ✅ YES |
| ml_feature_store | Cascade dependencies | ✅ YES |

**Phase 4 Verdict:**
- **100% of processors need it** (5 of 5) ✅
- **PRIMARY TARGET** for implementation
- Highest value, most complexity

---

## Phase 5 Predictions - Assessment

**Status:** Not yet implemented (no processor files found)

**When implemented, would need completeness checking?** ✅ YES

**Rationale:**
- Predictions depend on Phase 4 precompute outputs
- Phase 4 has historical dependencies
- Therefore Phase 5 inherits those dependencies via cascade
- Opus document already addresses this (decision visibility schema)

**Example prediction dependency chain:**
```
Phase 5: Make prediction for Player X on Nov 22
  ↓ Depends on
Phase 4: player_daily_cache for Player X on Nov 22
  ↓ Depends on (L10 games)
Phase 3: player_game_summary for last 10 games
  ↓ Depends on
Phase 2: Raw boxscore data for last 10 games
```

If Phase 4 has incomplete data (only 8 of 10 games), Phase 5 prediction would be unreliable.

**Phase 5 Verdict:**
- **Would need it when implemented** ✅
- Already covered by Opus design (decision visibility)
- Not urgent (doesn't exist yet)

---

## Cross-Phase Comparison

| Phase | Processors | Need Checking | Percentage | Priority |
|-------|-----------|--------------|-----------|----------|
| **Phase 2** (Raw) | 22 | 0 | 0% | N/A |
| **Phase 3** (Analytics) | 5 | 2 | 40% | Medium |
| **Phase 4** (Precompute) | 5 | 5 | 100% | **HIGH** ⭐ |
| **Phase 5** (Predictions) | TBD | TBD | TBD | Low (future) |

**Why Phase 2 doesn't need it:**
- Raw scrapers = point-in-time data collection
- No historical dependencies (just scrape what exists)
- Smart idempotency sufficient (detect changes to scraped data)

---

## Implementation Complexity Assessment

### Difficulty by Phase

**Phase 4 (5 processors):**
- **Complexity**: HIGH
- **Why**:
  - "Last N games" windows (not "last N days")
  - Multi-window processors (player_daily_cache: L5/L7/L10/L14)
  - Cascade dependencies (Phase 4 → Phase 4)
  - Bootstrap problem (first dates from 4 years ago)
- **Estimated Time**: 6-10 weeks (per Opus doc)
- **Cost**: $2.60/month

**Phase 3 (2 processors):**
- **Complexity**: LOW-MEDIUM
- **Why**:
  - Date-based windows (simpler than game-count windows)
  - L30 days fixed (no multi-window complexity)
  - No cascade dependencies (Phase 2 → Phase 3 only)
  - No bootstrap problem (only for upcoming games)
- **Estimated Time**: 2-3 weeks
- **Cost**: ~$0.50/month

**Phase 5 (future):**
- **Complexity**: MEDIUM (when implemented)
- **Why**:
  - Depends on Phase 4 completeness
  - Decision visibility schema (already in Opus design)
- **Estimated Time**: 3-4 weeks (after Phase 4 complete)
- **Cost**: ~$1/month

---

## Recommendation: Phased Implementation

### Option 1: Phase 4 Only (Opus Document) ⭐ RECOMMENDED

**Scope:** Implement for all 5 Phase 4 processors only
**Timeline:** 6-10 weeks
**Cost:** $2.60/month
**Pros:**
- ✅ Solves highest-value problem (Phase 4 = most complex)
- ✅ Proven design from Opus review
- ✅ Can extend to Phase 3 later if needed
- ✅ Focused scope (easier to complete)

**Cons:**
- ⚠️ Leaves Phase 3 context processors without checking
- ⚠️ May need to retrofit Phase 3 later

**When to extend to Phase 3:**
- After Phase 4 stable (2-3 months)
- If Phase 3 quality issues emerge
- Simpler implementation (learned from Phase 4)

---

### Option 2: Phase 3 + Phase 4 Simultaneously

**Scope:** Implement for 2 Phase 3 + 5 Phase 4 = 7 processors
**Timeline:** 8-12 weeks
**Cost:** $3.10/month
**Pros:**
- ✅ Complete solution for all historical dependencies
- ✅ Consistent approach across phases
- ✅ No retrofitting needed

**Cons:**
- ❌ Longer timeline (scope creep risk)
- ❌ More complex testing (7 processors vs 5)
- ❌ Two different window types (dates vs games)
- ❌ Higher risk of delays

---

### Option 3: Phase 4 First, Then Phase 3

**Scope:** Phase 4 (6-10 weeks) → Phase 3 (2-3 weeks) = 8-13 weeks total
**Timeline:** Staged rollout
**Cost:** $3.10/month (after both complete)
**Pros:**
- ✅ Tackles highest complexity first
- ✅ Learn from Phase 4, apply to Phase 3
- ✅ Can pause after Phase 4 if needed
- ✅ Lower risk (incremental)

**Cons:**
- ⚠️ Longer total timeline
- ⚠️ Phase 3 left incomplete temporarily

---

## My Recommendation: Option 1 (Phase 4 Only) ⭐

**Rationale:**
1. **Phase 4 has 100% need** (all 5 processors)
2. **Phase 3 has 40% need** (only 2 of 5 processors)
3. **Phase 4 is more complex** (game-count windows, multi-window, bootstrap)
4. **Proven design** (Opus document is comprehensive)
5. **Can extend later** if Phase 3 quality issues emerge

**Phase 3 can wait because:**
- Only affects "upcoming context" (pre-game analysis)
- Not as critical as Phase 4 (actual predictions/features)
- Simpler to retrofit later (date-based windows)
- Can manually monitor for now

**Implementation Plan:**
1. **Weeks 1-2**: Implement Opus plan for Phase 4
2. **Weeks 3-10**: Roll out across 5 Phase 4 processors
3. **Weeks 11-12**: Monitor Phase 3 quality issues
4. **Decision Point**: Extend to Phase 3 if needed

---

## Answer to User's Questions

### Q1: "Can it be applied to all processors and phases?"

**Answer:** **PARTIALLY**

- **Phase 2 (Raw)**: ❌ Not needed (point-in-time scrapers)
- **Phase 3 (Analytics)**: ⚠️ Only 2 of 5 processors (40%)
  - upcoming_player_game_context ✅
  - upcoming_team_game_context ✅
  - player_game_summary ❌
  - team_offense_game_summary ❌
  - team_defense_game_summary ❌
- **Phase 4 (Precompute)**: ✅ All 5 processors (100%)
- **Phase 5 (Predictions)**: ✅ Would apply when implemented

**Total applicability:** 7 of 32 processors (~22%)

### Q2: "Should we save this document somewhere or start implementing and save the doc later?"

**Answer:** **SAVE NOW, IMPLEMENT AFTER DECISION**

**Already saved:**
- ✅ `/docs/implementation/09-historical-dependency-checking-plan-v2.1-OPUS.md` (Opus plan)
- ✅ `/docs/implementation/10-phase-applicability-assessment.md` (this document)

**Before implementing, need to decide:**
1. **Scope**: Phase 4 only? Or Phase 3 + 4?
2. **Timeline**: 6-10 weeks realistic? Or extend to 12 weeks?
3. **Priority**: Block other work? Or parallel development?

**My suggestion:**
1. Review this assessment + Opus plan
2. Decide on scope (I recommend Phase 4 only)
3. Get approval on 6-10 week timeline
4. THEN start implementation

**Don't start coding yet** - design is solid, but need scope decision first.

---

## Difficulty Assessment (Per Opus Plan)

**Overall Difficulty:** 7/10

**Easy Parts (30%):**
- Schema migrations (add 14 columns per table)
- Circuit breaker logic (max 3 attempts, 7-day gaps)
- Boolean flags (is_production_ready, backfill_bootstrap_mode)

**Medium Parts (50%):**
- CompletenessChecker service (batch queries for all entities)
- Multi-window handling (player_daily_cache: L5/L7/L10/L14)
- Monitoring infrastructure (6 BigQuery views + daily job)

**Hard Parts (20%):**
- Edge case handling (early season, partial data, missing dates)
- Coordination (Phase 4 → Phase 4 cascade reprocessing)
- Testing (6-7 week staged rollout with validation)
- Season boundary detection

**Can one engineer do this?**
- ✅ Yes, but needs **full focus** for 6-10 weeks
- ⚠️ Timeline will slip if interrupted
- ✅ Opus design is excellent (reduces complexity)

---

## Next Steps

### If Proceeding with Phase 4 Only (Recommended):

1. **Week 0** (this week):
   - [ ] Review Opus document thoroughly
   - [ ] Get user approval on scope (Phase 4 only)
   - [ ] Get user approval on timeline (6-10 weeks)
   - [ ] Decide on start date

2. **Week 1** (prototype):
   - [ ] Implement core infrastructure (CompletenessChecker)
   - [ ] Add schema columns to team_defense_zone_analysis
   - [ ] Prototype completeness checking for ONE processor
   - [ ] Build kill switch
   - [ ] Get approval to continue

3. **Weeks 2-10** (full rollout):
   - Follow Opus implementation plan exactly
   - Stage rollout across 5 processors
   - Monitor and adjust

### If Extending to Phase 3:

- Add 2-3 weeks to timeline (total: 8-13 weeks)
- Implement Phase 3 AFTER Phase 4 stable
- Simpler than Phase 4 (date-based windows)

---

## Files for Review

**Before starting implementation, review these documents:**

1. **Opus Plan**: `/docs/implementation/09-historical-dependency-checking-plan-v2.1-OPUS.md`
   - Comprehensive implementation guide
   - Circuit breaker, multi-window logic, monitoring
   - 6-10 week timeline

2. **This Assessment**: `/docs/implementation/10-phase-applicability-assessment.md`
   - Which phases need it (3, 4, 5)
   - Which processors need it (7 of 32)
   - Phased implementation options

3. **Phase 4 Analysis**: `/docs/implementation/05-phase4-historical-dependencies-complete.md`
   - Detailed processor requirements
   - Bootstrap problem analysis
   - Week-by-week backfill timeline

4. **Original Context**: `/docs/for-review/OPUS_REVIEW_historical-dependency-checking.md`
   - Full problem statement
   - 14 questions for reviewer
   - Background on why we need this

---

## Final Recommendation to User

**Start with Phase 4 only** using the Opus plan:
- ✅ Highest value (100% of processors need it)
- ✅ Most complex (learn the hard parts first)
- ✅ Proven design (Opus review was thorough)
- ✅ Can extend to Phase 3 later (simpler retrofitting)

**Save implementation for after approval:**
- Review Opus plan carefully
- Approve 6-10 week timeline
- Approve $2.60/month cost
- Decide on start date

**Phase 3 extension:**
- Can add later (2-3 weeks)
- Only 2 processors need it
- Lower priority than Phase 4
- Simpler implementation

**Do you want to:**
1. Proceed with Phase 4 implementation (Opus plan)?
2. Extend scope to include Phase 3 (2 processors)?
3. Review documents first before deciding?
