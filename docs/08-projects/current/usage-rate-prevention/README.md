# Usage Rate Prevention Project

**Created:** 2026-02-03 (Session 96)
**Completed:** 2026-02-03 (Session 96)
**Verified:** 2026-02-03 (Session 97) ✅
**Status:** COMPLETE - VERIFIED
**Priority:** P0

## Problem Statement

On Feb 2, 2026, all players had 0% usage_rate coverage despite valid team data existing for 3/4 games. Root cause: a global 80% threshold in `_check_team_stats_available()` blocked ALL usage_rate calculations when a single game (PHI-LAC) was delayed.

### Impact
- 0% usage_rate for Feb 2 (vs expected 95%+)
- Degraded ML feature quality
- Poor prediction accuracy (49.1% hit rate on "high-edge" picks)

### Immediate Fix (Session 96)
Lowered threshold from 80% to 50%. This is a band-aid - the fundamental design is flawed.

## Long-Term Improvements

| # | Priority | Improvement | Status |
|---|----------|-------------|--------|
| 1 | P0 | Per-game usage rate calculation | **COMPLETE** |
| 2 | P1 | Automated data quality alerts | **COMPLETE** |
| 3 | P1 | Unit tests for edge cases | **COMPLETE** |
| 4 | P2 | Pre-prediction analytics quality gate | **COMPLETE** |
| 5 | P2 | Data quality runbook | **COMPLETE** |

## Improvement Details

### 1. Per-Game Usage Rate Calculation (P0)

**Current (flawed):**
```python
# Global check - affects ALL games
self._team_stats_available = check_threshold(80%)
if not self._team_stats_available:
    usage_rate = None  # ALL players get NULL
```

**Target:**
```python
# Per-game - only affected game gets NULL
# LEFT JOIN team_offense_game_summary ON game_id
# If team data exists for THIS game → calculate
# If not → NULL only for THIS game's players
```

**Files to modify:**
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

### 2. Automated Data Quality Alerts (P1)

**Schedule:** 7:30 AM ET (after Phase 3, before predictions)

**Checks:**
- usage_rate coverage >= 80%
- minutes coverage >= 90%
- Active players per game >= 15

**Alert channels:** Slack #nba-alerts

**Files to create:**
- `functions/monitoring/analytics_quality_check/main.py`
- Cloud Scheduler job: `analytics-quality-check-morning`

### 3. Unit Tests (P1)

**Test scenarios:**
1. Partial team data (2/4 games have team stats)
2. One game delayed (3/4 games ready)
3. No team data (all games missing)
4. Full team data (all games ready)

**Files to create:**
- `tests/data_processors/analytics/test_usage_rate_calculation.py`

### 4. Pre-Prediction Analytics Quality Gate (P2)

Extend existing quality gate to check analytics data:
- Block predictions if usage_rate coverage < 50%
- Log warning if coverage < 80%

**Files to modify:**
- `predictions/coordinator/quality_gate.py`

### 5. Data Quality Runbook (P2)

Document investigation and fix process for:
- usage_rate = 0%
- minutes_played missing
- player data incomplete

**Files to create:**
- `docs/02-operations/runbooks/data-quality-runbook.md`

## Success Criteria

1. One delayed game does NOT block usage_rate for other games
2. Alerts fire before predictions when data quality is low
3. Tests catch regressions in threshold logic
4. Quality gate prevents bad predictions from going out
5. Runbook enables fast incident response

## Implementation Summary

### Commits
| Commit | Description |
|--------|-------------|
| `395df684` | fix: Lower threshold 80%→50% (band-aid) |
| `cf25b5e2` | refactor: Per-game usage_rate calculation |
| `c44bbfeb` | feat: Add comprehensive prevention system |

### Infrastructure Deployed
| Resource | Type | Schedule |
|----------|------|----------|
| `analytics-quality-check` | Cloud Function | 7:30 AM ET |
| `analytics-quality-check-morning` | Cloud Scheduler | Daily |

### Files Created/Modified
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` - Per-game logic
- `predictions/coordinator/quality_gate.py` - AnalyticsQualityGate class
- `functions/monitoring/analytics_quality_check/` - Quality check function
- `tests/data_processors/analytics/test_usage_rate_calculation.py` - 11 unit tests
- `docs/02-operations/runbooks/data-quality-runbook.md` - Investigation runbook

### Verification (Session 96)
Feb 2 data after fixes:
- usage_rate coverage: 98.8% (was 0%)
- All 4 games have usage_rate data
- PHI-LAC game (previously missing) now at 100% coverage

### Session 97 Verification & Bug Fixes

**Verified Working:**
| Layer | Status | Notes |
|-------|--------|-------|
| 1. Per-game usage_rate | ✅ Working | 98.8% coverage for Feb 2 |
| 3. data_quality_history table | ✅ Fixed | Was empty, now recording |
| 4. analytics-quality-check function | ✅ Working | Returns correct metrics |
| 5. morning-deployment-check function | ✅ Fixed | False positive bug fixed |

**Bug Fixes Applied (Session 97):**
1. **morning-deployment-check**: Changed from SHA comparison to timestamp comparison. Was reporting 4 stale services when 0 were stale.
2. **analytics-quality-check**: Added `write_quality_history()` to populate `data_quality_history` table.

**Verification Commands:**
```bash
# Check deployment status (should be all healthy)
curl -s -X POST "https://us-west2-nba-props-platform.cloudfunctions.net/morning-deployment-check" | jq .status
# Expected: "healthy"

# Check quality history is recording
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_analytics.data_quality_history"
# Expected: > 0
```

## Related Documents

- [Feb 2 Validation Issues](../feb-2-validation/FEB-2-VALIDATION-ISSUES-2026-02-03.md)
- [Session 96 Handoff](../../09-handoff/2026-02-03-SESSION-96-HANDOFF.md)
- [Session Learnings](../../02-operations/session-learnings.md)
- [Data Quality Runbook](../../02-operations/runbooks/data-quality-runbook.md)
