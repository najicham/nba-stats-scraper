# Session 26 Handoff - Data Source Research & Enhancement Planning

**Date:** January 12, 2026
**Previous Session:** Session 25 (System Health Restoration)
**Status:** RESEARCH COMPLETE - Implementation Plans Ready
**Focus:** Evaluate new data sources, create implementation plans for improvements

---

## Quick Start for Next Session

```bash
# 1. Review the data source enhancement project
cat docs/08-projects/current/data-source-enhancements/README.md

# 2. Two detailed implementation plans ready for review:
cat docs/08-projects/current/data-source-enhancements/PLAYER-TRAVEL-IMPLEMENTATION-PLAN.md
cat docs/08-projects/current/data-source-enhancements/REFEREE-TENDENCIES-IMPLEMENTATION-PLAN.md

# 3. Quick win - enable player travel (currently hardcoded to 0):
grep -n "travel_adj = 0.0" data_processors/precompute/player_composite_factors/player_composite_factors_processor.py
```

---

## Session 26 Summary

This session conducted **research on potential data sources** to improve prediction accuracy and created detailed implementation plans for two high-value enhancements.

### Key Findings

#### 1. DraftKings API Evaluation

| Endpoint | Status | Notes |
|----------|--------|-------|
| **DFS API** (`api.draftkings.com`) | ✅ Works | Player salaries, FPPG, contests - no auth needed |
| **Sportsbook** (`sportsbook.draftkings.com`) | ❌ Blocked | Akamai protection, even with proxy + Playwright |
| **FanDuel** | ❌ Blocked | Requires authentication |

**Conclusion:** DraftKings DFS API accessible but **not needed** - our system already has more sophisticated player projections.

#### 2. System Data Gap Analysis

| Component | Current State | Gap |
|-----------|---------------|-----|
| **Travel distances** | ✅ Static table with 870 team pairs | |
| **Team-level travel** | ✅ Calculated in team context | |
| **Player-level travel** | ❌ Schema exists, all fields = None | `travel_adj = 0.0` hardcoded |
| **Referee assignments** | ✅ Who refs which game | |
| **Referee tendencies** | ❌ Not calculated | `referee_adj = 0.0` hardcoded |

#### 3. External Data Source Assessment

| Source | Value | Cost | Recommendation |
|--------|-------|------|----------------|
| **OddsJam API** | Sharp money, line movement | $500-1000+/mo | Skip - too expensive |
| **NBA.com Tracking** | Speed, touches, drives | Free | Consider later |
| **NBAstuffer Referees** | Historical ref stats | Paid | Build our own instead |

---

## Deliverables Created

### New Project Directory

```
docs/08-projects/current/data-source-enhancements/
├── README.md                              # Project overview & priorities
├── 01-referee-tendencies.md               # Brief overview
├── 02-player-travel-impact.md             # Brief overview
├── 03-tracking-stats.md                   # NBA.com tracking (future)
├── 04-line-movement.md                    # Sharp money (future)
├── 05-future-considerations.md            # Lower priority ideas
├── PLAYER-TRAVEL-IMPLEMENTATION-PLAN.md   # 524 lines - READY FOR REVIEW
└── REFEREE-TENDENCIES-IMPLEMENTATION-PLAN.md # 816 lines - READY FOR REVIEW
```

### Implementation Plans Summary

#### Player Travel (P2 - 4-6 hours)

**Problem:** Infrastructure exists but `travel_adj = 0.0` is hardcoded

**Files to modify:**
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Key changes:**
1. Implement `get_travel_last_n_days()` in travel_utils (currently returns zeros)
2. Populate 5 travel fields in player context (currently all None)
3. Calculate `travel_adj` based on cumulative miles and time zones

#### Referee Tendencies (P1 - 6-8 hours)

**Problem:** Have referee assignments but no historical tendencies

**Files to create:**
- `schemas/bigquery/analytics/referee_tendencies_tables.sql`
- `data_processors/analytics/referee_tendencies/referee_tendencies_processor.py`

**Files to modify:**
- `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`
- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Key changes:**
1. Create processor that joins referee assignments + game results
2. Calculate rolling averages: total points, O/U record, pace
3. Add crew-level aggregation (chief 40% + crew 60%)
4. Calculate `referee_adj` based on crew tendencies vs league average

---

## Recommended Priority Order

1. **Quick win (30 min):** Wire up player travel adjustment
   - Replace `travel_adj = 0.0` with calculation
   - Team-level travel already works

2. **Medium effort (1 day):** Build referee tendencies processor
   - High value - refs affect 5-10 point game swings
   - All source data already exists

3. **Later:** NBA.com tracking stats, line movement/CLV

---

## Questions for Reviewer

### Player Travel Plan
1. Is -3.0 max adjustment appropriate?
2. Should we add travel to fatigue_score (0-100) or keep separate?
3. Should player inherit team-level travel or recalculate?

### Referee Tendencies Plan
1. Weight chief 40%, crew 60% - appropriate?
2. Minimum games: 50 for MEDIUM, 100 for HIGH confidence?
3. Use opening or closing line for O/U calculations?
4. Include prior season data for new refs?

---

## No Immediate Action Required

This was a **research and planning session**. The implementation plans are ready for a future session to review and execute.

### Files Modified
- None (research only)

### Files Created
- `docs/08-projects/current/data-source-enhancements/` (8 files)

---

## Related Documentation

- Player travel utils: `data_processors/analytics/utils/travel_utils.py`
- Referee schema: `schemas/bigquery/raw/nbac_referee_tables.sql`
- Referee pivot view: `schemas/bigquery/raw/nbac_referee_pivot_view.sql`
- Composite factors: `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`
