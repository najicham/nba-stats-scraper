# Handoff: Validation Issues & System Resilience
**Date:** 2026-01-25
**Session Focus:** Validation findings, backfill requirements, and resilience improvements

---

## Executive Summary

This session completed streaming buffer fixes and ran comprehensive validation for 2026-01-24. We found:
- **1 missing game** (GSW@MIN) with no boxscore data
- **2 games with analytics gaps** (NYK@PHI, WAS@CHA have fewer analytics players than boxscores)
- **45-hour orchestration gap** (Jan 23 04:20 → Jan 25 01:35 UTC) caused processing delays
- **Feature quality regression** detected by multiple validation angles

The system has recovered and is processing normally now, but backfill is needed and resilience improvements should be implemented.

---

## What Was Completed This Session

### 1. Streaming Buffer Fixes (Root Cause Fix)
Converted `insert_rows_json()` → `insert_bigquery_rows()` (batch loading) in:
- `shared/utils/bdl_availability_logger.py`
- `shared/utils/scraper_availability_logger.py`
- `shared/utils/mlb_player_registry/resolver.py`

### 2. Cloud Function Sync Script
Created `bin/orchestrators/sync_shared_utils.sh` that syncs 91 files across 7 cloud functions:
- auto_backfill_orchestrator
- daily_health_summary
- phase2_to_phase3, phase3_to_phase4, phase4_to_phase5, phase5_to_phase6
- self_heal

### 3. Phase Transition Gating
Added 80% coverage check to `phase3_to_phase4` orchestrator:
- `check_data_coverage()` function compares actual vs scheduled games
- Blocks Phase 4 if coverage < 80%
- Sends Slack alert when blocked
- Configurable via `COVERAGE_THRESHOLD_PCT` and `COVERAGE_GATING_ENABLED` env vars

---

## Validation Findings for 2026-01-24

### Pipeline Status by Game

| Game | Boxscores | Analytics | Predictions | Issue |
|------|-----------|-----------|-------------|-------|
| BOS@CHI | ✅ 35 | ✅ 36 | ✅ 78 | OK |
| CLE@ORL | ✅ 34 | ✅ 35 | ✅ 71 | OK |
| LAL@DAL | ✅ 36 | ✅ 36 | ✅ 80 | OK |
| MIA@UTA | ✅ 35 | ✅ 37 | ✅ 36 | OK |
| NYK@PHI | ✅ 34 | ⚠️ 19 | ✅ 94 | **Analytics player gap (19 vs 34)** |
| WAS@CHA | ✅ 35 | ⚠️ 20 | ✅ 72 | **Analytics player gap (20 vs 35)** |
| GSW@MIN | ❌ 0 | ❌ 0 | ✅ 55 | **MISSING - no boxscore data** |

### Validation Check Results

| Validation Script | Status | Key Findings |
|-------------------|--------|--------------|
| `comprehensive_health_check.py` | 🔴 1 critical, 4 errors | Feature quality 64.43% (threshold 65%), rolling window incomplete |
| `workflow_health.py` | ⚠️ 1 error | No phase transitions in 48 hours |
| `phase_transition_health.py` | ⚠️ | 2026-01-24 partial (85.7% schedule→boxscores) |
| `multi_angle_validator.py` | ⚠️ 2 issues | 1 missing boxscore, analytics player discrepancy |
| `advanced_validation_angles.py` | ⚠️ 2 warnings | System consistency, feature regression |
| `daily_pipeline_doctor.py` | 🔴 1 critical | 1 game missing boxscore |
| `root_cause_analyzer.py` | 🔴 | Missing boxscores prevent grading |

### Root Causes Identified

1. **45-hour orchestration outage** (same as documented in previous handoff)
   - Gap: 2026-01-23 04:20 UTC → 2026-01-25 01:35 UTC
   - Caused delayed processing of Jan 24 games

2. **BDL API did not return GSW@MIN data**
   - Multiple scrape attempts logged, all showing `was_available=False`
   - Need to investigate if this is API issue or scraper bug

3. **Analytics player gaps for NYK@PHI and WAS@CHA**
   - Boxscores have 34-35 players, analytics only 19-20
   - Suggests analytics processor skipped some players

---

## Immediate Backfill Required

### Priority 1: Missing Boxscore (GSW@MIN)
```bash
# Try to fetch the missing game
PYTHONPATH=. python bin/backfill/bdl_boxscores.py --date 2026-01-24

# If BDL API still doesn't have it, check alternative sources
PYTHONPATH=. python bin/scrapers/nba_official_boxscores.py --date 2026-01-24 --game-id 0022500644
```

### Priority 2: Analytics Gaps
```bash
# Re-run analytics for games with player discrepancies
PYTHONPATH=. python bin/backfill/analytics.py --date 2026-01-24 --force

# Or target specific games
PYTHONPATH=. python data_processors/analytics/player_game_summary_processor.py --date 2026-01-24 --games 20260124_NYK_PHI,20260124_WAS_CHA
```

### Priority 3: Grading Backfill
```bash
# After boxscores are complete, run grading
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --start-date 2026-01-24 --end-date 2026-01-24
```

---

## Resilience Improvements Needed

### P0: Critical (Do First)

#### 1. BDL Scrape Availability Logging Fix
The availability logger shows `was_available=False` even when data exists. Fix:

**File:** `shared/utils/bdl_availability_logger.py`

The logger checks availability BEFORE data is written to BigQuery. It should:
1. Check if boxscore data was actually returned in the API response
2. Log player_count from the response, not from BigQuery

```python
# Current (broken):
was_available = False  # Always false because data not in BQ yet

# Should be:
was_available = len(box_scores) > 0
player_count = sum(len(bs.get('players', [])) for bs in box_scores)
```

#### 2. Missing Game Alert
Add proactive alerting when a game is missing from BDL response:

**File:** `scrapers/bdl_boxscores_scraper.py`

```python
# After fetching boxscores, check for missing games
expected_games = get_expected_games_from_schedule(game_date)
fetched_games = set(bs['game_id'] for bs in box_scores)
missing_games = expected_games - fetched_games

if missing_games:
    logger.error(f"BDL API missing {len(missing_games)} games: {missing_games}")
    send_slack_alert(
        channel='#data-alerts',
        message=f":warning: BDL API missing games for {game_date}: {missing_games}"
    )
```

#### 3. Analytics Player Count Validation
Add validation to detect when analytics has fewer players than boxscores:

**File:** `data_processors/analytics/player_game_summary_processor.py`

```python
# After processing, validate player counts
boxscore_count = get_boxscore_player_count(game_id, game_date)
analytics_count = get_analytics_player_count(game_id, game_date)

if analytics_count < boxscore_count * 0.9:  # Allow 10% variance
    logger.warning(
        f"Analytics player gap: {game_id} has {analytics_count} analytics "
        f"vs {boxscore_count} boxscore players ({analytics_count/boxscore_count:.0%})"
    )
```

### P1: Important (Do Soon)

#### 4. Phase Execution Logging Enhancement
The `phase_execution_log` table had no records for 2026-01-24. Ensure all phase transitions are logged:

**Files to check:**
- `orchestration/cloud_functions/phase2_to_phase3/main.py`
- `orchestration/cloud_functions/phase3_to_phase4/main.py`
- `orchestration/cloud_functions/phase4_to_phase5/main.py`

Each should call:
```python
from shared.utils.phase_execution_logger import log_phase_execution

log_phase_execution(
    phase_name='phase3_to_phase4',
    game_date=game_date,
    status='success',
    games_processed=len(games),
    duration_seconds=elapsed
)
```

#### 5. Workflow Decision Gap Detection
Add automatic detection of workflow decision gaps:

**File:** `bin/monitoring/workflow_gap_detector.py` (create new)

```python
"""
Detect gaps in workflow decisions and alert if orchestration appears stuck.
Run every 30 minutes via Cloud Scheduler.
"""

def check_workflow_gap():
    # Get most recent decision
    last_decision = get_last_workflow_decision()
    gap_minutes = (now - last_decision).total_seconds() / 60

    if gap_minutes > 120:  # 2 hour threshold
        send_critical_alert(
            f"Workflow decisions stopped {gap_minutes:.0f} min ago! "
            f"Last decision at {last_decision}"
        )
```

#### 6. Daily Reconciliation Report
Create automated daily reconciliation that compares:
- Scheduled games vs boxscore games
- Boxscore players vs analytics players
- Analytics players vs feature players
- Feature players vs predictions

**File:** `bin/monitoring/daily_reconciliation.py` (create new)

### P2: Nice to Have

#### 7. Validation Dashboard
Create a simple dashboard showing:
- Pipeline health by date
- Missing data at each phase
- Trend of validation check results

#### 8. Auto-Retry for Missing Games
When a game is missing from BDL, automatically:
1. Wait 30 minutes
2. Retry the fetch
3. After 3 retries, try alternative sources
4. Send alert if still missing

---

## Key Files Reference

### Validation Scripts
```
bin/validation/
├── comprehensive_health_check.py  # Main health check
├── workflow_health.py             # Orchestration workflow health
├── phase_transition_health.py     # Phase transition validation
├── multi_angle_validator.py       # Cross-table validation
├── advanced_validation_angles.py  # Advanced checks
├── daily_pipeline_doctor.py       # Automated diagnosis
└── root_cause_analyzer.py         # Root cause analysis
```

### Orchestration
```
orchestration/cloud_functions/
├── phase2_to_phase3/main.py       # Phase 2→3 orchestrator
├── phase3_to_phase4/main.py       # Phase 3→4 orchestrator (has new gating)
├── phase4_to_phase5/main.py       # Phase 4→5 orchestrator
└── phase5_to_phase6/main.py       # Phase 5→6 orchestrator
```

### Shared Utilities (Fixed This Session)
```
shared/utils/
├── bigquery_utils.py              # insert_bigquery_rows (batch loading)
├── bdl_availability_logger.py     # BDL scrape logging (fixed)
├── scraper_availability_logger.py # Scraper logging (fixed)
├── phase_execution_logger.py      # Phase execution logging
└── completeness_checker.py        # Completeness checking
```

### Sync Script
```
bin/orchestrators/sync_shared_utils.sh  # Syncs shared utils to cloud functions
```

---

## Quick Commands

### Run All Validation
```bash
# Comprehensive validation for a date
PYTHONPATH=. python bin/validation/comprehensive_health_check.py --date 2026-01-24
PYTHONPATH=. python bin/validation/multi_angle_validator.py --date 2026-01-24
PYTHONPATH=. python bin/validation/advanced_validation_angles.py --date 2026-01-24
PYTHONPATH=. python bin/validation/daily_pipeline_doctor.py --start-date 2026-01-24 --end-date 2026-01-24
```

### Check Pipeline Status
```bash
# Direct BigQuery check for a date
PYTHONPATH=. python -c "
from google.cloud import bigquery
client = bigquery.Client()
date = '2026-01-24'

query = f'''
SELECT
    'schedule' as phase, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_raw.v_nbac_schedule_latest\`
WHERE game_date = '{date}'
UNION ALL
SELECT 'boxscores', COUNT(DISTINCT game_id)
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE game_date = '{date}'
UNION ALL
SELECT 'analytics', COUNT(DISTINCT game_id)
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '{date}'
UNION ALL
SELECT 'predictions', COUNT(DISTINCT game_id)
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '{date}' AND is_active = TRUE
'''
for row in client.query(query).result():
    print(f'{row.phase}: {row.games} games')
"
```

### Sync Cloud Functions
```bash
./bin/orchestrators/sync_shared_utils.sh
```

---

## Git Status

Modified files (not committed):
- `shared/utils/bdl_availability_logger.py` - streaming fix
- `shared/utils/scraper_availability_logger.py` - streaming fix
- `shared/utils/mlb_player_registry/resolver.py` - streaming fix
- `orchestration/cloud_functions/phase3_to_phase4/main.py` - coverage gating
- Multiple cloud function shared utils (synced)

New files:
- `bin/orchestrators/sync_shared_utils.sh` - sync script
- `schemas/bigquery/raw/v_game_id_mappings.sql` - game ID mapping view

---

## Recommended Next Steps (Priority Order)

1. **Backfill missing GSW@MIN game** - highest impact
2. **Fix BDL availability logging** - currently shows false negatives
3. **Add analytics player count validation** - catch gaps early
4. **Re-run analytics for NYK@PHI and WAS@CHA** - fix player gaps
5. **Add workflow gap detection** - prevent future 45-hour outages
6. **Create daily reconciliation report** - automated health tracking
7. **Deploy the game ID mapping view** - helps with cross-source joins
8. **Commit and deploy cloud function changes** - get fixes into production

---

## Questions for Next Session

1. Why did BDL API not return GSW@MIN data? Is this a persistent issue?
2. Why do NYK@PHI and WAS@CHA have fewer analytics players? Check processor logs.
3. Should we add alternative boxscore sources (NBA.com API) as fallback?
4. What caused the 45-hour orchestration gap? (See previous handoff for details)

---

*End of Handoff*
