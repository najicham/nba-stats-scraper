# Pattern Coverage Gaps - Implementation Handoff

**Date:** 2025-11-29
**Status:** Ready for Implementation
**Priority:** Low-Medium (optimization, not blocking)
**Prerequisite:** Read `docs/01-architecture/data-readiness-patterns.md` first

---

## Context

During documentation of data readiness patterns, I identified gaps where patterns are not uniformly applied across processors. These are optimization opportunities, not bugs - the current implementation is production-ready.

---

## Gaps Summary

### Phase 3: Missing QualityMixin (4 processors)

**What:** `QualityMixin` enables source coverage tracking (Gold/Silver/Bronze quality tiers).

**Currently:** Only `PlayerGameSummaryProcessor` has it.

**Missing from:**
- `TeamDefenseGameSummaryProcessor`
- `TeamOffenseGameSummaryProcessor`
- `UpcomingPlayerGameContextProcessor`
- `UpcomingTeamGameContextProcessor`

**Priority:** Low - useful for monitoring but not critical.

**Implementation pattern:**
```python
# Current
class TeamDefenseGameSummaryProcessor(
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    AnalyticsProcessorBase
):

# Add QualityMixin
from shared.processors.patterns import QualityMixin

class TeamDefenseGameSummaryProcessor(
    QualityMixin,          # Add this
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    AnalyticsProcessorBase
):
```

**Files:**
- `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py`
- `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`

---

### Phase 3: Missing Change Detection (2 processors)

**What:** `get_change_detector()` enables incremental processing - only process entities that changed.

**Currently:** Only `PlayerGameSummaryProcessor` has it.

**Missing from:**
- `TeamDefenseGameSummaryProcessor`
- `TeamOffenseGameSummaryProcessor`

**Priority:** Medium - could reduce mid-day update processing by ~90%.

**Why it matters:** Currently these processors do full-batch (all 30 teams) every run. With change detection, mid-day updates would only process 2-4 teams that played.

**Implementation requires:**
1. Create `TeamChangeDetector` class (similar to `PlayerChangeDetector`)
2. Add `get_change_detector()` method to processors
3. Update `extract_raw_data()` to filter by changed teams

**Reference implementation:**
- `shared/change_detection/change_detector.py` - `PlayerChangeDetector`
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py:209-219`

---

### Phase 5: RunHistoryMixin Integration

**What:** `PredictionCoordinator` has its own `ExecutionLogger` but doesn't integrate with `processor_run_history` table.

**Currently:** Phase 5 logs are separate from Phase 2-4 logs.

**Priority:** Medium - would enable unified monitoring across all phases.

**Consideration:** Phase 5 architecture is different (Flask app, not processor class). May need adapter pattern.

**Files:**
- `predictions/coordinator/coordinator.py`
- `predictions/worker/execution_logger.py`

---

## Recommended Implementation Order

1. **QualityMixin to team processors** (30 min each, low risk)
   - Simple mixin addition
   - No logic changes needed
   - Enables future source coverage monitoring

2. **TeamChangeDetector** (2-4 hours, medium complexity)
   - Create detector class
   - Add to `TeamDefenseGameSummaryProcessor`
   - Add to `TeamOffenseGameSummaryProcessor`
   - Test with mid-day updates

3. **Phase 5 RunHistory integration** (4-8 hours, higher complexity)
   - Design adapter for Flask-based services
   - Coordinate with prediction worker logging
   - Consider if worth the complexity

---

## Testing Approach

For each pattern addition:

1. **Unit test:** Verify mixin is called
2. **Integration test:** Run processor with pattern, verify behavior
3. **Regression test:** Ensure existing functionality unchanged

For change detection specifically:
```bash
# Test incremental mode
python -m data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor \
  --start-date 2025-11-28 --end-date 2025-11-28 --debug

# Verify log shows "INCREMENTAL: 2/30 teams changed"
```

---

## Files Referenced

| File | Purpose |
|------|---------|
| `docs/01-architecture/data-readiness-patterns.md` | Full pattern documentation |
| `shared/processors/patterns/__init__.py` | Pattern mixin exports |
| `shared/processors/patterns/quality_mixin.py` | QualityMixin implementation |
| `shared/change_detection/change_detector.py` | PlayerChangeDetector (reference) |
| `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | Reference for both patterns |

---

## Decision Points

Before implementing, consider:

1. **QualityMixin:** Do we need source coverage tracking for team-level data? If monitoring doesn't need it, skip.

2. **Change Detection:** How often do mid-day team updates happen? If rare, benefit is minimal.

3. **Phase 5 RunHistory:** Is unified monitoring worth the complexity? Or keep Phase 5 logging separate?

---

## Out of Scope

These are NOT gaps to fix:
- Phase 2 processors don't need dependency checking (they ARE the source)
- Phase 4 processors don't need change detection (they process all entities daily)
- Bootstrap period is correctly Phase 4 only

---

**Created by:** Claude Code
**Reference:** Pattern analysis session 2025-11-29
