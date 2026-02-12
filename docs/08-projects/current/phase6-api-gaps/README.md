# Phase 6 API Gaps - Frontend Integration Project

**Date:** February 11, 2026
**Status:** Analysis Complete - Ready for Implementation
**Source:** Frontend team comprehensive API review
**Sprint Duration:** 3 sprints (~10.5 hours total)

---

## 📋 Project Overview

The frontend team (props-web) conducted a comprehensive review of all Phase 6 API endpoints and identified gaps blocking features and UX improvements. This project addresses **16 issues across 12 endpoints** with prioritized implementation plan.

**Current State:**
- ✅ 6 endpoints working well
- ⚠️ 4 endpoints missing or incomplete
- 🔧 Multiple data quality issues affecting 16% of players
- 🚫 Key features blocked (prediction reasoning, accurate O/U history)

**Post-Implementation State:**
- ✅ 10 endpoints fully functional
- ✅ All data quality issues resolved
- ✅ High-impact features unlocked (prediction factors, best bets)
- ✅ Enhanced UX (calendar, date navigation, complete player data)

---

## 📄 Documentation Files

| File | Purpose | Audience |
|------|---------|----------|
| `00-FRONTEND-GAP-ANALYSIS.md` | **Detailed analysis** - Root causes, solutions, estimates | Technical implementation |
| `01-QUICK-REFERENCE.md` | **Quick wins & high-impact items** - Code snippets, testing | Developers |
| `02-IMPLEMENTATION-CHECKLIST.md` | **Task tracking** - Step-by-step checklist with validation | Implementation team |
| `README.md` (this file) | **Project overview** - Summary and navigation | All stakeholders |

---

## 🎯 Key Issues Identified

### P0 - Data Quality (Affects Accuracy)
1. **31 players with all-dash O/U history** - Frontend using inaccurate workaround (16% of lined players)
2. **Bogus odds data** - Values like 199900 (clearly invalid)
3. **Live grading stuck** - Historical games showing "in-progress"

### P1 - Missing Fields (Features Blocked)
4. **`prediction.factors`** - 0/192 populated - **#1 frontend request** - "Why this pick?" reasoning
5. **`days_rest`** - 0/192 populated - UI component ready, no data
6. **`recent_form`** - 0/192 populated - Hot/Cold/Neutral indicator
7. **`minutes_avg`** - 0/192 populated - Duplicate of `season_mpg` (different name)
8. **`player_lookup` in picks** - Needed to link picks to player cards
9. **`results/latest.json` stale** - Feb 10 data missing

### P2 - New Endpoints (Unlock Features)
10. **`tonight/{date}.json`** - Historical date browsing (404)
11. **`calendar/game-counts.json`** - Calendar widget (404)
12. **`news/latest.json`** - News integration (404, deferred)

### P3 - Schema Alignment (Nice-to-Have)
13. **Confidence scale** - 0-100 vs 0.0-1.0 (frontend handles, but inconsistent)
14. **`game_time` whitespace** - Leading space on times
15. **Best bets methodology** - Too restrictive, returns 0 picks for current date
16. **Profile field names** - `team` vs `team_abbr`, `fg` string vs numbers

---

## 🚀 Implementation Plan

### Sprint 1: Quick Wins (30 minutes)
**Impact:** Immediate data completeness improvement

✅ 7 quick fixes:
- `days_rest` - Already queried, just add to output (5 min)
- `minutes_avg` - Alias for existing field (2 min)
- `game_time` - Trim whitespace (2 min)
- `confidence` - Convert to 0.0-1.0 scale (5 min)
- `recent_form` - Calculate from last_5 vs season (15 min)
- Odds validation - Filter out 199900 values (30 min)
- `player_lookup` in picks - Add to output (30 min)

**Files Modified:** 3 files
**Deploy:** Push to main → auto-deploy

---

### Sprint 2: High-Impact Features (8 hours)
**Impact:** Major UX features unlocked

✅ 2 major features:

**1. `prediction.factors` (6 hours)**
- Human-readable reasoning for picks
- 4 factors max per player
- Uses existing feature store data
- Example: "Faces weak defense", "Hot streak: 7-3 L10", "Strong model edge (5.2 points)"

**2. `last_10_lines` array (2 hours)**
- Fixes inaccurate O/U history for 31 players
- Enables accurate sparkline calculations
- Frontend can compare `last_10_points[i]` to `last_10_lines[i]`

**3. Best bets fix (1 hour)**
- Current date returns 0 picks (queries wrong table)
- Fix: Use `player_prop_predictions` for future dates, `prediction_accuracy` for historical

**Files Modified:** 2 files
**Deploy:** Push to main → auto-deploy → trigger Phase 6 export

---

### Sprint 3: Enhancements (2 hours)
**Impact:** Enhanced navigation and discoverability

✅ 2 new features:

**1. Date-specific tonight files (15 min)**
- Export both `/tonight/all-players.json` AND `/tonight/{date}.json`
- Enables historical date browsing

**2. Calendar game counts (1 hour)**
- New endpoint: `/calendar/game-counts.json`
- Shows game indicators on calendar widget
- 30+ days of data

**Files Modified:** 2 files (1 new)
**Deploy:** Push to main → auto-deploy → trigger Phase 6 export

---

## 📊 Impact Summary

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Lined players with complete data** | 161/192 (84%) | 192/192 (100%) | +16% |
| **Endpoints working** | 6/10 | 10/10 | +4 endpoints |
| **Prediction reasoning** | 0% | 100% | Feature unlocked |
| **Accurate O/U history** | 84% | 100% | +16% accuracy |
| **Best bets current date** | 0 picks | 10-25 picks | Feature fixed |
| **Historical date browsing** | Not available | Available | Feature unlocked |
| **Calendar widget** | Empty | Functional | Feature unlocked |

---

## 🧪 Testing Strategy

### Automated Tests
- [ ] Unit tests for new helper functions (`safe_odds`, `_build_prediction_factors`)
- [ ] Integration tests for exporters
- [ ] Schema validation for JSON outputs

### Manual Validation
- [ ] Export for current date → verify all fields populated
- [ ] Export for historical date → verify graded data correct
- [ ] Check 10 sample players → verify factor quality
- [ ] Test edge cases (rookies, missing data, NULL values)

### Frontend Validation
- [ ] All TypeScript interfaces satisfied
- [ ] No console errors
- [ ] "Why this pick?" displays correctly
- [ ] Calendar widget functional
- [ ] Historical date navigation works

---

## 🔧 Technical Details

### Files Modified

| File | Changes | Complexity |
|------|---------|------------|
| `tonight_all_players_exporter.py` | Add 7 fields + factors logic + last_10_lines | High |
| `best_bets_exporter.py` | Fix table selection for current dates | Medium |
| `all_subsets_picks_exporter.py` | Add player_lookup to output | Low |
| `exporter_utils.py` | Add safe_odds() helper | Low |
| `calendar_exporter.py` | NEW FILE - game counts endpoint | Medium |
| `daily_export.py` | Add calendar to export types | Low |

### Dependencies

- No new Python packages required
- All data available in BigQuery
- Uses existing infrastructure (BaseExporter, GCS uploads)

### Deployment

- Auto-deploy via Cloud Build on push to main
- Phase 6 export service (`nba-scrapers`)
- Triggers Phase 6 daily export job

---

## 📈 Success Metrics

**Immediate (Sprint 1):**
- [ ] 0 fields missing for lined players
- [ ] 0 invalid odds values in export
- [ ] Frontend confirms data completeness

**Post-Sprint 2:**
- [ ] 100% of lined players have prediction factors
- [ ] 0% O/U calculation errors (was 16%)
- [ ] Best bets section shows picks on all game days

**Post-Sprint 3:**
- [ ] Historical date browsing functional
- [ ] Calendar widget shows game counts
- [ ] Frontend removes all workarounds from `api-adapters.ts`

---

## 🚦 Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Confidence scale breaking change | Medium | Medium | Check all consumers, update together |
| Factor generation performance | Low | Low | Factors built from existing queries |
| `last_10_lines` array size | Low | Low | Adds 40-200 bytes per player (minimal) |
| Best bets query complexity | Low | Medium | Test both historical and current dates |
| Calendar endpoint timeout | Low | Low | Simple aggregation query (<1s) |

**Rollback Plan:**
- Confidence scale: Revert to 0-100
- Factors: Return empty array
- Hotfix: `./bin/hot-deploy.sh nba-scrapers`

---

## 📞 Stakeholders

**Backend Team:**
- Implementation
- Testing
- Deployment
- Documentation

**Frontend Team (props-web):**
- Requirements
- Validation
- Integration testing
- UX verification

**Users:**
- Better prediction reasoning
- More accurate historical data
- Enhanced navigation

---

## 📝 Next Steps

1. **Review:** Team review of implementation plan
2. **Approval:** User sign-off on sprint allocation
3. **Sprint 1:** Implement quick wins (30 min)
4. **Deploy 1:** Push + validate
5. **Sprint 2:** Implement high-impact features (8 hours)
6. **Deploy 2:** Push + validate
7. **Sprint 3:** Implement enhancements (2 hours)
8. **Deploy 3:** Push + validate
9. **Documentation:** Update CLAUDE.md and API docs
10. **Handoff:** Create session handoff document

---

## 📚 Reference Links

**Source Document:**
- `/home/naji/code/props-web/docs/08-projects/current/backend-integration/API_ENDPOINT_REVIEW_2026-02-11.md`

**Related Documentation:**
- CLAUDE.md - System architecture
- `docs/02-operations/` - Runbooks
- `data_processors/publishing/` - Exporter code

**Frontend Repository:**
- `props-web/src/lib/api-adapters.ts` - Current workarounds
- `props-web/src/types/api.ts` - TypeScript interfaces

---

**Project Status:** ✅ Analysis Complete - Ready for Implementation
**Estimated Effort:** 10.5 hours across 3 sprints
**Expected Impact:** High - Unlocks major UX features and improves data quality
**Next Action:** User approval to begin Sprint 1
