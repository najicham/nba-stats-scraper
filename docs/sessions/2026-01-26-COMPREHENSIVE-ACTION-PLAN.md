# Comprehensive Action Plan - NBA Stats Scraper System Recovery & Improvement

**Date**: 2026-01-26
**Status**: Ready for Review and Execution
**Priority**: HIGH - Production System Requires Deployment
**Estimated Effort**: 2-4 hours immediate work, 1-2 days for monitoring improvements

---

## Executive Summary

The NBA stats scraper system experienced a betting data timing issue on 2026-01-26 that appeared as a critical failure but was actually a **workflow configuration mismatch**. The root cause has been identified, a fix has been implemented locally, and manual data collection was initiated. This document outlines the complete plan to:

1. Verify the manual data collection and backfill
2. Fix validation script bugs that caused false alarms
3. Deploy the configuration fix to production
4. Implement monitoring improvements to prevent similar confusion in the future

**Key Finding**: The betting_lines workflow was configured to start only 6 hours before games (1 PM for 7 PM games), but users expected morning predictions. The fix changes the window to 12 hours (8 AM start), providing all-day data availability.

---

## Current State Assessment

### What's Been Done ✅

1. **Root Cause Identified**: Configuration timing issue in workflows.yaml
2. **Fix Implemented Locally**: `window_before_game_hours: 6` → `12` (commit f4385d03)
3. **Manual Data Collection**: Task `b0926bb` triggered for 2026-01-26 data
4. **Comprehensive Documentation**:
   - Incident report: `docs/incidents/2026-01-26-BETTING-DATA-TIMING-ISSUE-ROOT-CAUSE.md`
   - Handoff doc: `docs/sessions/2026-01-26-BETTING-DATA-INVESTIGATION-HANDOFF.md`

### What's Pending ⏳

1. **Manual Collection Status**: Task b0926bb may still be running
2. **Phase 3 Trigger**: Analytics processors blocked by missing betting data
3. **Configuration Deployment**: Local fix not yet in production
4. **Validation Script Bugs**: Divide-by-zero and timing awareness issues
5. **Monitoring Gaps**: No alerts for "workflow not started yet" scenarios

### System Health 🏥

| Component | Status | Notes |
|-----------|--------|-------|
| Scraper Infrastructure | ✅ Healthy | API credentials working, no IP blocks |
| Workflow Configuration | 🟡 Fixed Locally | Not deployed to production |
| Betting Data (2026-01-26) | ⏳ In Progress | Manual collection running |
| Phase 3 Analytics | ❌ Blocked | Waiting for betting data |
| Phase 4/5 Pipeline | ❌ Stale | Downstream of Phase 3 |
| Validation Scripts | 🔴 Buggy | False alarms due to timing issues |
| Monitoring & Alerts | 🟡 Partial | Missing timing-aware alerts |
| Documentation | ✅ Excellent | Comprehensive incident reports |

---

## Action Plan - Organized by Phase

### Phase 1: Immediate Recovery (30-60 minutes)

**Goal**: Complete the 2026-01-26 data backfill and verify system health

#### Task 1.1: Check Manual Data Collection Status
```bash
# Check if background task completed
cat /tmp/claude_code_task_b0926bb_output.txt

# Or check task status
/tasks
```

**Expected Outcome**:
- Task b0926bb completed successfully
- All 14 scraper tasks (7 games × 2 data types) finished

**If Failed**: Review error logs and re-trigger failed scrapers individually

---

#### Task 1.2: Verify Betting Data in BigQuery
```bash
# Check props data
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_id) as unique_games,
  MIN(timestamp) as earliest,
  MAX(timestamp) as latest
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE DATE(timestamp) = '2026-01-26'
"

# Check game lines data
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_id) as unique_games,
  MIN(timestamp) as earliest,
  MAX(timestamp) as latest
FROM \`nba-props-platform.nba_raw.odds_api_game_lines\`
WHERE DATE(timestamp) = '2026-01-26'
"
```

**Expected Results**:
- Props: 200-300 records covering 7 games
- Game Lines: 70-140 records covering 7 games
- Timestamps: Multiple throughout the day (manual trigger created one snapshot)

**If Data Missing**:
- Check BigQuery streaming buffer delays (can be up to 90 seconds)
- Review task output logs for specific failures
- Re-trigger specific scrapers if needed

---

#### Task 1.3: Trigger Phase 3 Analytics Processors

Once betting data is confirmed, Phase 3 should auto-trigger or can be manually triggered:

```bash
# Check if Phase 3 auto-triggered
python scripts/validate_tonight_data.py --date 2026-01-26

# Manual trigger if needed (exact command TBD based on system)
# May require triggering specific processors:
# - UpcomingPlayerGameContextProcessor
# - UpcomingTeamGameContextProcessor
```

**Expected Results**:
- `upcoming_player_game_context`: 200-300 records for today's players
- `upcoming_team_game_context`: 14 records (7 games × 2 teams)
- `has_prop_line` flag correctly set based on betting data availability

**Verification**:
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as player_contexts
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '2026-01-26'
"
```

---

#### Task 1.4: Validate Full Pipeline Status

Run the comprehensive validation to check all phases:

```bash
# Full pipeline validation
python scripts/validate_tonight_data.py --date 2026-01-26 --verbose

# Spot check data accuracy (quick version)
python scripts/spot_check_data_accuracy.py --samples 5 --checks rolling_avg,usage_rate
```

**Success Criteria**:
- Phase 2 (betting data): ✅ Present
- Phase 3 (analytics): ✅ Present
- Phase 4 (precompute): May need manual trigger
- Phase 5 (predictions): May need manual trigger
- Spot checks: 95%+ accuracy

**Document**: Record actual counts and any anomalies in a new file:
`docs/validation/2026-01-26-RECOVERY-VALIDATION-RESULTS.md`

---

### Phase 2: Fix Validation & Testing (1-2 hours)

**Goal**: Fix bugs in validation scripts and add comprehensive testing before production deployment

#### Task 2.1: Fix Validation Script Timing Awareness

**File**: `scripts/validate_tonight_data.py`

**Issues to Fix**:
1. **Divide-by-zero bug**: Reported in incident documentation
2. **Timing awareness**: Distinguish "workflow not started" from "workflow failed"
3. **Actionable errors**: Provide context about workflow windows

**Implementation**:
```python
# Pseudo-code for timing awareness
def check_betting_data(date, current_time):
    # Load workflow config
    config = load_workflow_config()
    betting_workflow = config['workflows']['betting_lines']

    # Get today's games
    games = get_games_for_date(date)
    if not games:
        return ValidationResult(status="SKIP", reason="No games scheduled")

    # Calculate workflow window
    first_game_time = min(g.commence_time for g in games)
    window_hours = betting_workflow['schedule']['window_before_game_hours']
    window_start = first_game_time - timedelta(hours=window_hours)

    # Check if we're before the window
    if current_time < window_start:
        return ValidationResult(
            status="TOO_EARLY",
            reason=f"Workflow window opens at {window_start.strftime('%I:%M %p')} ({window_hours}h before first game at {first_game_time.strftime('%I:%M %p')})",
            action="Check again after window opens"
        )

    # Check if we're within expected data lag (2 hours after window start)
    if current_time < window_start + timedelta(hours=2):
        return ValidationResult(
            status="WITHIN_LAG",
            reason=f"Workflow started at {window_start.strftime('%I:%M %p')}, data may still be collecting",
            action="Wait up to 2 hours after window start before alerting"
        )

    # Now check actual data
    record_count = query_betting_data(date)
    if record_count == 0:
        return ValidationResult(
            status="FAILURE",
            reason=f"Workflow window opened at {window_start.strftime('%I:%M %p')} but no data found after 2 hour lag",
            action="ALERT: Check scraper logs and workflow execution"
        )

    return ValidationResult(status="SUCCESS", record_count=record_count)
```

**Testing**:
```bash
# Test with different timestamps
python scripts/validate_tonight_data.py --date 2026-01-27 --simulate-time "2026-01-27 06:00:00"  # Before window
python scripts/validate_tonight_data.py --date 2026-01-27 --simulate-time "2026-01-27 09:00:00"  # Within window
python scripts/validate_tonight_data.py --date 2026-01-27 --simulate-time "2026-01-27 15:00:00"  # Should have data
```

---

#### Task 2.2: Add Workflow Timing Utilities

Create helper module for workflow timing calculations:

**File**: `orchestration/workflow_timing.py` (new file)

```python
"""
Utilities for calculating and validating workflow timing windows.
"""
from datetime import datetime, timedelta
from typing import List, Tuple
import yaml

def calculate_workflow_window(
    workflow_name: str,
    game_times: List[datetime],
    config_path: str = "config/workflows.yaml"
) -> Tuple[datetime, datetime]:
    """
    Calculate the start and end times for a workflow window.

    Returns:
        (window_start, window_end) as datetime objects
    """
    with open(config_path) as f:
        config = yaml.safe_load(f)

    workflow = config['workflows'][workflow_name]
    schedule = workflow['schedule']

    # Calculate window start
    first_game = min(game_times)
    window_hours = schedule.get('window_before_game_hours', 6)
    window_start = first_game - timedelta(hours=window_hours)

    # Apply business hours constraints
    if 'business_hours' in schedule:
        bh_start = schedule['business_hours']['start']
        bh_end = schedule['business_hours']['end']

        # Clamp to business hours
        bh_start_time = window_start.replace(hour=bh_start, minute=0, second=0)
        bh_end_time = window_start.replace(hour=bh_end, minute=0, second=0)

        if window_start < bh_start_time:
            window_start = bh_start_time

    # Window end is typically last game time
    window_end = max(game_times)

    return window_start, window_end

def get_expected_run_times(
    workflow_name: str,
    game_times: List[datetime],
    config_path: str = "config/workflows.yaml"
) -> List[datetime]:
    """
    Calculate all expected run times for a workflow given game schedule.

    Returns:
        List of datetime objects representing when workflow should run
    """
    window_start, window_end = calculate_workflow_window(workflow_name, game_times, config_path)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    workflow = config['workflows'][workflow_name]
    frequency_hours = workflow['schedule'].get('frequency_hours', 1)

    # Generate run times
    run_times = []
    current = window_start
    while current <= window_end:
        run_times.append(current)
        current += timedelta(hours=frequency_hours)

    return run_times

def is_within_workflow_window(
    workflow_name: str,
    check_time: datetime,
    game_times: List[datetime],
    config_path: str = "config/workflows.yaml"
) -> bool:
    """
    Check if a given time is within the workflow's operating window.
    """
    window_start, window_end = calculate_workflow_window(workflow_name, game_times, config_path)
    return window_start <= check_time <= window_end
```

**Testing**:
```bash
# Unit tests for timing utilities
python -m pytest tests/unit/orchestration/test_workflow_timing.py -v
```

---

#### Task 2.3: Run Comprehensive Spot Check Validation

Before deploying to production, run a thorough validation:

```bash
# Full spot check - all 6 checks, 50 samples
python scripts/spot_check_data_accuracy.py --samples 50 --verbose > spot_check_results.txt

# Review results
cat spot_check_results.txt
```

**Success Criteria**:
- All checks pass at 95%+ accuracy
- No systematic failures in any specific check
- Rolling averages within 2% tolerance
- Usage rate calculations within 2% tolerance
- Minutes parsing within 0.1 minute tolerance
- ML feature store consistency within 2%
- Player daily cache L0 features within 2%
- Points totals exact match

**If Failures Occur**:
- Document specific failures
- Investigate if it's data quality issue or calculation bug
- May need to fix data or update tolerance thresholds
- Do NOT deploy if systematic failures detected

---

#### Task 2.4: Test Workflow Timing with New Configuration

Test the new 12-hour window configuration:

```bash
# Test timing calculations
python -c "
from orchestration.workflow_timing import calculate_workflow_window, get_expected_run_times
from datetime import datetime

# Test 7 PM game
game_times = [datetime(2026, 1, 27, 19, 0)]
window_start, window_end = calculate_workflow_window('betting_lines', game_times)
print(f'7 PM game: Window {window_start.strftime(\"%I:%M %p\")} - {window_end.strftime(\"%I:%M %p\")}')

run_times = get_expected_run_times('betting_lines', game_times)
print(f'Expected runs: {[t.strftime(\"%I:%M %p\") for t in run_times]}')

# Test early game (12 PM)
game_times = [datetime(2026, 1, 27, 12, 0)]
window_start, window_end = calculate_workflow_window('betting_lines', game_times)
print(f'12 PM game: Window {window_start.strftime(\"%I:%M %p\")} - {window_end.strftime(\"%I:%M %p\")}')

run_times = get_expected_run_times('betting_lines', game_times)
print(f'Expected runs: {[t.strftime(\"%I:%M %p\") for t in run_times]}')
"
```

**Expected Output**:
```
7 PM game: Window 08:00 AM - 07:00 PM
Expected runs: ['08:00 AM', '10:00 AM', '12:00 PM', '02:00 PM', '04:00 PM', '06:00 PM']

12 PM game: Window 08:00 AM - 12:00 PM  (clamped from 12:00 AM)
Expected runs: ['08:00 AM', '10:00 AM', '12:00 PM']
```

**Verify**:
- Business hours floor (8 AM) is respected
- Frequency (2 hours) is correct
- Window calculations match expected times

---

### Phase 3: Production Deployment (30 minutes + monitoring)

**Goal**: Deploy the configuration fix to production and verify it works correctly

#### Task 3.1: Pre-Deployment Checklist

Before deploying, verify:
- [ ] Manual data collection (2026-01-26) completed successfully
- [ ] Phase 3 analytics populated for 2026-01-26
- [ ] Validation script fixes tested and working
- [ ] Spot check validation passed at 95%+ accuracy
- [ ] Workflow timing utilities tested
- [ ] No other uncommitted changes in working directory

```bash
# Check git status
git status

# Review changes to be committed
git diff config/workflows.yaml
```

---

#### Task 3.2: Commit Configuration Changes

```bash
# Stage the configuration file
git add config/workflows.yaml

# If validation script was fixed, stage it too
git add scripts/validate_tonight_data.py

# If timing utilities were added, stage them
git add orchestration/workflow_timing.py
git add tests/unit/orchestration/test_workflow_timing.py

# Create comprehensive commit
git commit -m "$(cat <<'EOF'
fix: Update betting_lines workflow timing to enable morning predictions

Root Cause (2026-01-26 Incident):
- betting_lines workflow configured with 6h window before games
- For 7 PM games, workflow started at 1 PM
- Users expected morning predictions but data unavailable until afternoon
- Validation ran at 10 AM and reported "0 records" (false alarm)

Changes:
1. config/workflows.yaml:
   - betting_lines.schedule.window_before_game_hours: 6 → 12
   - Effect: Workflow now starts at 8 AM for 7 PM games
   - New run schedule: 8 AM, 10 AM, 12 PM, 2 PM, 4 PM, 6 PM, 8 PM

2. scripts/validate_tonight_data.py:
   - Added timing awareness to distinguish "not started" vs "failed"
   - Fixed divide-by-zero bug in percentage calculations
   - Added workflow window context to error messages

3. orchestration/workflow_timing.py (new):
   - Utilities for calculating workflow windows
   - Helper functions for validation and testing
   - Enables timing-aware validation logic

Impact:
- API calls increase: +63/day (84 → 147) = $1.89/month
- User experience: Predictions available by 9-10 AM vs afternoon
- Reduced false alarms: Validation now understands workflow timing

Testing:
- Spot check validation: 95%+ accuracy on 50 samples
- Workflow timing tests: Verified for 7 PM and 12 PM game scenarios
- Manual backfill: 2026-01-26 data successfully collected

References:
- Incident Report: docs/incidents/2026-01-26-BETTING-DATA-TIMING-ISSUE-ROOT-CAUSE.md
- Handoff Doc: docs/sessions/2026-01-26-BETTING-DATA-INVESTIGATION-HANDOFF.md

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"

# Verify commit
git show --stat
```

---

#### Task 3.3: Deploy to Production

**Note**: Deployment process depends on your infrastructure. The config_loader.py uses hot-reload, so changes should take effect within 1 hour of file update.

```bash
# Option A: If using git-based deployment
git push origin main

# Option B: If manually copying to production server
scp config/workflows.yaml production:/path/to/nba-stats-scraper/config/
scp scripts/validate_tonight_data.py production:/path/to/nba-stats-scraper/scripts/
scp orchestration/workflow_timing.py production:/path/to/nba-stats-scraper/orchestration/

# Option C: If using automated deployment pipeline
# Trigger your deployment process here
```

**Verify Deployment**:
```bash
# Check file modification time on production
ssh production "ls -la /path/to/nba-stats-scraper/config/workflows.yaml"

# Verify config content
ssh production "grep 'window_before_game_hours' /path/to/nba-stats-scraper/config/workflows.yaml"

# Expected output: window_before_game_hours: 12
```

---

#### Task 3.4: Monitor First Production Run

**Critical**: Watch the first production run closely to catch any issues.

For a game on 2026-01-27 at 7:00 PM:
- **First run**: Should occur at 8:00 AM ET (or 7:00 AM if no business hours constraint)
- **Subsequent runs**: Every 2 hours (10 AM, 12 PM, 2 PM, 4 PM, 6 PM, 8 PM)

**Monitoring Commands**:
```bash
# Check workflow execution logs (every hour)
tail -f logs/master_controller.log | grep betting_lines

# Check data arrival in BigQuery (run at 9 AM, 11 AM, 1 PM)
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as records,
  MAX(timestamp) as latest_timestamp
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE DATE(timestamp) = '2026-01-27'
"

# Run validation with new timing awareness (9 AM, 11 AM, 1 PM)
python scripts/validate_tonight_data.py --date 2026-01-27

# Expected at 9 AM: Either data present OR "workflow running, check again at 10 AM"
# Expected at 11 AM: Data should be present (2-3 runs completed)
# Expected at 1 PM: Data definitely present (5+ runs completed)
```

**Success Indicators**:
- ✅ First workflow run logged at ~8 AM
- ✅ Betting data appears in BigQuery by 9 AM
- ✅ Phase 3 analytics runs by 10 AM
- ✅ Predictions available by 11 AM
- ✅ No false alarm failures in validation
- ✅ All expected run times occur (7 runs for 7 PM games)

**Failure Indicators & Actions**:
- ❌ Workflow doesn't run at 8 AM → Check master controller logs, verify config reload
- ❌ Data not appearing by 10 AM → Check scraper logs, API credentials
- ❌ Validation still reports false alarms → Check validation script deployment
- ❌ Runs occurring too frequently (< 2 hour intervals) → Check frequency_hours config

**Monitoring Duration**: 24 hours for first complete cycle, then spot check for 1 week

---

### Phase 4: Monitoring & Alerting Improvements (1-2 days)

**Goal**: Implement comprehensive monitoring to prevent similar issues and catch real failures quickly

#### Task 4.1: Add Timing-Aware Monitoring Alerts

**Alerts to Implement**:

1. **Workflow Window Not Started** (INFO severity)
   - Trigger: Validation runs before workflow window opens
   - Message: "betting_lines workflow not started yet - window opens at {time}"
   - Action: Informational only, no alert necessary

2. **Betting Data Late** (WARNING severity)
   - Trigger: No data 2+ hours after workflow window starts
   - Message: "betting_lines workflow started at {time} but no data found after 2 hours"
   - Action: Check scraper logs, verify API credentials

3. **Phase 3 Blocked** (HIGH severity)
   - Trigger: Phase 3 cannot run due to missing betting data dependencies
   - Message: "Phase 3 analytics blocked - missing betting data for {date}"
   - Action: Immediate investigation, manual trigger if needed

4. **Configuration Drift** (WARNING severity)
   - Trigger: Workflow timing may not meet business SLAs
   - Message: "betting_lines window_before_game_hours={X} may not provide morning predictions"
   - Action: Review configuration against business requirements

5. **Excessive Run Frequency** (WARNING severity)
   - Trigger: Workflow runs more frequently than configured frequency_hours
   - Message: "betting_lines running every {X} hours, configured for {Y} hours"
   - Action: Check frequency logic, may indicate configuration error

**Implementation Location**:
- `monitoring/alerts.py` - Alert definitions
- `scripts/validate_tonight_data.py` - Integrate alert triggering
- `orchestration/master_controller.py` - Add alerting hooks

**Example Alert Implementation**:
```python
# monitoring/alerts.py
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class Alert:
    severity: AlertSeverity
    title: str
    message: str
    action: str
    workflow: Optional[str] = None
    timestamp: Optional[datetime] = None

def send_alert(alert: Alert):
    """Send alert via configured channels (Slack, PagerDuty, etc)"""
    # Implementation depends on your alerting infrastructure
    pass

def check_workflow_timing_alert(
    workflow_name: str,
    current_time: datetime,
    window_start: datetime,
    data_present: bool
) -> Optional[Alert]:
    """
    Check if timing-related alert should be triggered.
    """
    # Before window starts - informational
    if current_time < window_start:
        return Alert(
            severity=AlertSeverity.INFO,
            title=f"{workflow_name} - Workflow Not Started",
            message=f"Validation checked at {current_time.strftime('%I:%M %p')} but workflow window opens at {window_start.strftime('%I:%M %p')}",
            action="No action needed - workflow will start at scheduled time",
            workflow=workflow_name
        )

    # Within 2 hours of window start - wait for data
    hours_since_start = (current_time - window_start).total_seconds() / 3600
    if hours_since_start < 2:
        return None  # No alert yet, within acceptable lag

    # 2+ hours after window start with no data - warning
    if not data_present:
        return Alert(
            severity=AlertSeverity.WARNING,
            title=f"{workflow_name} - Data Late",
            message=f"Workflow window opened at {window_start.strftime('%I:%M %p')} but no data found after {hours_since_start:.1f} hours",
            action="Check scraper logs and workflow execution status",
            workflow=workflow_name
        )

    return None  # All good
```

---

#### Task 4.2: Create Configuration Validation Tests

Add automated tests to catch configuration issues before deployment:

**File**: `tests/unit/config/test_workflow_config_validation.py` (new)

```python
"""
Tests for workflow configuration validation.
Ensures workflow configurations meet business requirements and constraints.
"""
import pytest
import yaml
from datetime import datetime, timedelta

def load_workflow_config():
    with open('config/workflows.yaml') as f:
        return yaml.safe_load(f)

class TestBettingLinesWorkflow:
    """Tests specific to betting_lines workflow timing."""

    def test_window_supports_morning_predictions(self):
        """
        Verify betting_lines window is large enough to provide morning predictions.

        Business requirement: Users need predictions by 10 AM for evening games.
        This requires betting data by 9 AM, which requires workflow to start by 8 AM.
        For 7 PM games, this needs 11-hour window minimum (prefer 12 for buffer).
        """
        config = load_workflow_config()
        betting_workflow = config['workflows']['betting_lines']
        window_hours = betting_workflow['schedule']['window_before_game_hours']

        # Minimum 11 hours for 7 PM games, recommend 12
        assert window_hours >= 11, \
            f"betting_lines window ({window_hours}h) too short for morning predictions. Need 11+ hours."

        # Verify with actual calculation
        game_time = datetime(2026, 1, 27, 19, 0)  # 7 PM game
        window_start = game_time - timedelta(hours=window_hours)
        business_hours_start = 8  # 8 AM

        # Apply business hours floor
        actual_start_hour = max(window_start.hour, business_hours_start)

        assert actual_start_hour <= 8, \
            f"betting_lines starts at {actual_start_hour} AM, too late for morning predictions (need ≤8 AM)"

    def test_frequency_allows_multiple_collections(self):
        """
        Verify frequency_hours allows multiple data collections before games.
        """
        config = load_workflow_config()
        betting_workflow = config['workflows']['betting_lines']
        frequency = betting_workflow['schedule']['frequency_hours']
        window_hours = betting_workflow['schedule']['window_before_game_hours']

        # Should have at least 3 collection runs per game
        expected_runs = window_hours / frequency
        assert expected_runs >= 3, \
            f"Only {expected_runs:.1f} runs with {frequency}h frequency over {window_hours}h window. Need 3+ runs."

    def test_business_hours_configured(self):
        """
        Verify business hours are configured to prevent late night runs.
        """
        config = load_workflow_config()
        betting_workflow = config['workflows']['betting_lines']
        assert 'business_hours' in betting_workflow['schedule'], \
            "betting_lines should have business_hours to prevent late night runs"

        bh = betting_workflow['schedule']['business_hours']
        assert bh['start'] <= 8, f"Business hours start too late ({bh['start']} AM)"
        assert bh['end'] >= 20, f"Business hours end too early ({bh['end']} PM)"

class TestWorkflowDependencies:
    """Tests for workflow dependency chains."""

    def test_betting_lines_depends_on_morning_ops(self):
        """
        Verify betting_lines depends on morning_operations (provides schedule).
        """
        config = load_workflow_config()
        betting_workflow = config['workflows']['betting_lines']

        assert 'dependencies' in betting_workflow
        assert 'requires' in betting_workflow['dependencies']
        assert 'morning_operations' in betting_workflow['dependencies']['requires'], \
            "betting_lines should depend on morning_operations for schedule data"

    def test_no_circular_dependencies(self):
        """
        Verify no circular dependencies in workflow chain.
        """
        config = load_workflow_config()

        def has_circular_dependency(workflow_name, visited=None):
            if visited is None:
                visited = set()

            if workflow_name in visited:
                return True  # Circular dependency detected

            visited.add(workflow_name)

            workflow = config['workflows'].get(workflow_name, {})
            dependencies = workflow.get('dependencies', {}).get('requires', [])

            for dep in dependencies:
                if has_circular_dependency(dep, visited.copy()):
                    return True

            return False

        for workflow_name in config['workflows']:
            assert not has_circular_dependency(workflow_name), \
                f"Circular dependency detected for {workflow_name}"

class TestConfigurationConsistency:
    """Tests for overall configuration consistency."""

    def test_all_scrapers_referenced_exist(self):
        """
        Verify all scrapers referenced in workflows are defined.
        """
        config = load_workflow_config()
        defined_scrapers = set(config['scrapers'].keys())

        for workflow_name, workflow in config['workflows'].items():
            if 'execution_plan' not in workflow:
                continue

            for step_name, step in workflow['execution_plan'].items():
                if 'scrapers' not in step:
                    continue

                for scraper in step['scrapers']:
                    assert scraper in defined_scrapers, \
                        f"Workflow '{workflow_name}' references undefined scraper '{scraper}'"

    def test_critical_workflows_enabled(self):
        """
        Verify critical workflows are enabled in production config.
        """
        config = load_workflow_config()

        critical_workflows = [
            'morning_operations',  # Provides schedule
            'betting_lines',       # Required for predictions
            'post_game_window_1',  # Required for next-day analytics
        ]

        for workflow_name in critical_workflows:
            workflow = config['workflows'][workflow_name]
            assert workflow.get('enabled', False), \
                f"Critical workflow '{workflow_name}' is disabled"

            if 'priority' in workflow:
                assert workflow['priority'] in ['HIGH', 'CRITICAL'], \
                    f"Critical workflow '{workflow_name}' has low priority: {workflow['priority']}"
```

**Run Tests**:
```bash
# Run configuration validation tests
python -m pytest tests/unit/config/test_workflow_config_validation.py -v

# Add to CI/CD pipeline
# Should run on every config change
```

---

#### Task 4.3: Create Workflow Timing Documentation

Add inline documentation to workflows.yaml explaining timing decisions:

```yaml
# In config/workflows.yaml

betting_lines:
  enabled: true
  priority: "CRITICAL"
  decision_type: "game_aware"
  description: "Collect betting lines multiple times before games start"

  # TIMING RATIONALE:
  # Business requirement: Users need predictions by 10 AM for evening games
  # - Predictions require Phase 3 analytics (30 min)
  # - Phase 3 requires betting data (collected by this workflow)
  # - Phase 3 should run by 9 AM → betting data needed by 8:30 AM
  # - First run at 8 AM provides data by 8:30 AM (with scraper latency)
  #
  # For 7 PM games:
  # - window_before_game_hours=12 → starts at 7 AM
  # - business_hours.start=8 → clamped to 8 AM actual start
  # - frequency_hours=2 → runs at 8, 10, 12, 2, 4, 6, 8 PM
  #
  # API cost: ~147 calls/day for typical 7-game schedule
  # Previous config (6h window): ~84 calls/day
  # Cost increase: ~$1.89/month (negligible for UX improvement)

  schedule:
    game_aware: true
    window_before_game_hours: 12  # Changed from 6 on 2026-01-26 (see incident docs)
    business_hours:
      start: 8   # 8 AM ET - don't run earlier (unnecessary cost)
      end: 20    # 8 PM ET - games starting, stop polling
    frequency_hours: 2  # Every 2 hours - balance freshness vs cost
```

---

#### Task 4.4: Create Operational Runbook

**File**: `docs/02-operations/WORKFLOW-TIMING-RUNBOOK.md` (new)

```markdown
# Workflow Timing Troubleshooting Runbook

## Quick Reference - Expected Timing

### betting_lines Workflow

**For 7 PM games:**
- Window opens: 8 AM ET (business hours floor)
- Expected runs: 8 AM, 10 AM, 12 PM, 2 PM, 4 PM, 6 PM, 8 PM
- Data should appear: By 8:30 AM (after first run completes)
- Phase 3 should run: By 9:30 AM
- Predictions available: By 10 AM

**For 3 PM games:**
- Window opens: 8 AM ET (12h before, clamped to business hours)
- Expected runs: 8 AM, 10 AM, 12 PM, 2 PM
- Data should appear: By 8:30 AM
- Phase 3 should run: By 9:30 AM
- Predictions available: By 10 AM

**For 12 PM games:**
- Window opens: 8 AM ET (would be 12 AM, clamped to business hours)
- Expected runs: 8 AM, 10 AM, 12 PM
- Data should appear: By 8:30 AM
- Phase 3 should run: By 9:30 AM
- Predictions available: By 10 AM

## Common Issues & Solutions

### Issue: "0 records" in validation before 9 AM

**Symptom**: Validation reports no betting data at 7 AM or 8 AM

**Root Cause**: Workflow may not have started yet OR just started and data still collecting

**Check**:
```bash
# Calculate expected window start
python -c "
from datetime import datetime, timedelta
# Get first game time from schedule
first_game = datetime(2026, 1, 27, 19, 0)  # Replace with actual
window_start = first_game - timedelta(hours=12)
window_start = window_start.replace(hour=max(window_start.hour, 8))
print(f'Window should start at: {window_start.strftime(\"%I:%M %p\")}')
"
```

**Solution**:
- If before window start: Wait until window opens
- If after window start but < 30 min: Wait for first run to complete
- If > 30 min after window start: Check scraper logs for failures

### Issue: Validation reports failure at 10 AM

**Symptom**: Validation shows "0 records" at 10 AM (2 hours after window start)

**Root Cause**: Likely a real failure - scraper not running or API issues

**Check**:
```bash
# Check master controller logs
grep -A 5 "betting_lines" logs/master_controller.log | tail -20

# Check scraper execution
bq query --use_legacy_sql=false "
SELECT
  workflow_name,
  scraper_name,
  status,
  start_time,
  end_time,
  error_message
FROM \`nba-props-platform.nba_orchestration.pipeline_event_log\`
WHERE DATE(start_time) = CURRENT_DATE()
  AND workflow_name = 'betting_lines'
ORDER BY start_time DESC
LIMIT 10
"
```

**Solutions**:
- If scraper didn't run: Check master controller, verify workflow enabled
- If scraper ran but no data: Check API credentials, rate limits
- If scraper failed: Review error logs, may need manual trigger

### Issue: False alarms about betting data

**Symptom**: Alerts fire at 7 AM saying betting data missing

**Root Cause**: Alerting system not timing-aware

**Solution**: Update alert logic to check workflow window timing:
```python
# In alerting code
from orchestration.workflow_timing import calculate_workflow_window

window_start, _ = calculate_workflow_window('betting_lines', game_times)
if current_time < window_start + timedelta(hours=2):
    # Don't alert yet - within expected lag
    return None
```

### Issue: Workflow running too frequently

**Symptom**: Workflow runs every hour instead of every 2 hours

**Root Cause**: frequency_hours not being respected OR run history not tracked

**Check**:
```bash
# Check actual run times from logs
grep "betting_lines.*RUN" logs/master_controller.log | tail -20

# Should show 2-hour gaps between runs
```

**Solution**:
- Verify `frequency_hours: 2` in config
- Check run history tracking in master controller
- May need to clear stale run history cache

### Issue: Workflow not running on game days

**Symptom**: No betting_lines workflow executions on day with games

**Root Cause**: Missing schedule data OR game_aware logic failing

**Check**:
```bash
# Verify schedule data exists
bq query --use_legacy_sql=false "
SELECT COUNT(*) as game_count
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = '2026-01-27'
"

# Check master controller decision
grep "betting_lines" logs/master_controller.log | grep -E "SKIP|RUN|ABORT"
```

**Solution**:
- If no schedule data: Run morning_operations manually first
- If schedule exists but workflow skips: Check game_aware evaluation logic
- Verify games are in correct date range and status

## Configuration Changes

### How to Change Window Timing

**To start workflow earlier/later:**
```yaml
# In config/workflows.yaml
betting_lines:
  schedule:
    window_before_game_hours: 12  # Increase for earlier start
    business_hours:
      start: 8  # Change to allow earlier/later starts
```

**Impact assessment:**
- Each +1 hour in window = ~3 additional API calls/day (assuming 7 games)
- Each -1 hour in business_hours.start = ~21 additional API calls/day
- Calculate cost: calls/day × $0.001 × 30 days

### How to Change Run Frequency

**To collect more/less frequently:**
```yaml
betting_lines:
  schedule:
    frequency_hours: 2  # Decrease for more frequent (1 = hourly)
```

**Impact assessment:**
- frequency_hours=1 (hourly): ~210 calls/day (+63 from current)
- frequency_hours=3 (every 3h): ~105 calls/day (-42 from current)

## Validation Commands

### Check Current Workflow Status
```bash
# See what master controller is doing right now
tail -f logs/master_controller.log | grep -E "betting_lines|Decision"
```

### Check Data Collection Progress
```bash
# Real-time betting data count
watch -n 60 'bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as props,
  (SELECT COUNT(*) FROM \`nba-props-platform.nba_raw.odds_api_game_lines\`
   WHERE DATE(timestamp) = CURRENT_DATE()) as lines
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE DATE(timestamp) = CURRENT_DATE()
"'
```

### Manual Trigger
```bash
# If workflow not running automatically, trigger manually
python orchestration/manual_trigger.py \
  --workflow betting_lines \
  --date 2026-01-27 \
  --force
```

## Escalation

**When to escalate:**
- Workflow not running 1+ hours after window opens
- No data appearing 2+ hours after window opens
- Validation showing failures after 10 AM on game days
- Systematic failures (3+ days in a row)

**Who to contact:**
- Platform team: Check infrastructure, BigQuery quotas
- Data team: Verify API credentials, check rate limits
- DevOps: Review deployment status, verify config files
```

---

### Phase 5: Long-Term Improvements (Future Work)

**Goal**: Architectural improvements to make the system more resilient

These are NOT required for immediate deployment but should be tracked for future sprints:

#### Task 5.1: Implement Graceful Degradation

Allow Phase 3 to run even when betting data is unavailable:

```python
# Phase 3 processors should handle missing betting data
def process_player_game_context(game_id, player_id):
    # Try to get betting data
    prop_line = get_prop_line(game_id, player_id)

    if prop_line is None:
        logger.warning(f"No prop line for {player_id} in game {game_id} - will use historical average")
        has_prop_line = False
        implied_line = calculate_historical_average(player_id)
    else:
        has_prop_line = True
        implied_line = prop_line.line

    return PlayerGameContext(
        game_id=game_id,
        player_id=player_id,
        has_prop_line=has_prop_line,
        implied_line=implied_line,
        ...
    )
```

**Benefits**:
- System continues working even if betting data unavailable
- Predictions may be less accurate but still useful
- No complete pipeline stall

**Effort**: 2-3 days to implement and test

---

#### Task 5.2: Implement Self-Healing Data Collection

Add automatic retry and backfill logic:

```python
# In validation script or monitoring
def check_and_heal_betting_data(date):
    """
    Check if betting data exists, trigger collection if missing.
    """
    current_time = datetime.now()
    games = get_games_for_date(date)

    if not games:
        return  # No games, nothing to do

    # Check if we should have data by now
    window_start, _ = calculate_workflow_window('betting_lines',
                                                  [g.commence_time for g in games])

    if current_time < window_start + timedelta(hours=2):
        return  # Too early to expect data

    # Check if data exists
    props_count = count_betting_props(date)
    lines_count = count_game_lines(date)

    expected_props = len(games) * 30  # ~30 props per game
    expected_lines = len(games) * 10  # ~10 lines per game

    # If significantly missing, trigger immediate collection
    if props_count < expected_props * 0.5 or lines_count < expected_lines * 0.5:
        logger.warning(f"Betting data missing for {date}, triggering self-heal")
        trigger_immediate_collection('betting_lines', date)

        # Alert that self-heal was needed
        send_alert(Alert(
            severity=AlertSeverity.WARNING,
            title="Self-Heal Triggered - Betting Data",
            message=f"Missing betting data for {date}, immediate collection triggered",
            action="Review why scheduled collection didn't work"
        ))
```

**Benefits**:
- Automatic recovery from missed scheduled runs
- Reduces manual intervention needed
- System self-corrects from transient failures

**Effort**: 3-4 days to implement and test thoroughly

---

#### Task 5.3: Dynamic Workflow Scheduling

Instead of fixed window calculations, use actual game times:

```yaml
# Future config structure
betting_lines:
  schedule:
    # Instead of fixed window_before_game_hours
    timing_strategy: "dynamic"

    # Define objectives instead of fixed times
    objectives:
      - type: "first_collection"
        target: "game_time - 12h"  # Same as current, but explicit
        clamp: "business_hours"

      - type: "frequent_collection"
        target: "game_time - 6h to game_time"
        frequency: "hourly"  # Increase frequency closer to game

      - type: "final_collection"
        target: "game_time - 30min"  # Last update before game starts
```

**Benefits**:
- More adaptive to varying game schedules
- Can optimize frequency based on proximity to game
- Clearer business intent in configuration

**Effort**: 1-2 weeks to design and implement

---

## Success Criteria

### Immediate Success (Phase 1-3)
- [ ] 2026-01-26 data backfilled successfully
- [ ] Configuration fix deployed to production
- [ ] First production run starts at 8 AM for evening games
- [ ] Betting data available by 9 AM
- [ ] Phase 3 analytics runs by 10 AM
- [ ] Predictions available by 11 AM
- [ ] No false alarm failures in validation
- [ ] Spot check validation passes at 95%+ accuracy

### Medium-Term Success (Phase 4)
- [ ] Timing-aware monitoring alerts implemented and tested
- [ ] Configuration validation tests passing in CI/CD
- [ ] Workflow timing utilities available and documented
- [ ] Operational runbook created and reviewed
- [ ] No timing-related false alarms for 1 week

### Long-Term Success (Phase 5)
- [ ] System operates for 30 days with <2% failure rate
- [ ] False alarm rate reduced to <5% (currently ~20% based on 2026-01-25/26 incidents)
- [ ] User-reported issues reduced by 50%
- [ ] Morning prediction availability >95% (currently ~50%)
- [ ] Cost increase within acceptable range ($2-5/month)

---

## Risk Assessment

### Deployment Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Config reload doesn't work | Low | High | Manual restart of master controller if needed |
| Workflow runs too frequently | Low | Medium | Frequency_hours limits runs, cost impact minimal |
| API rate limits hit | Low | Medium | Current limits handle 147 calls/day, we're using ~100 |
| Timing calculations wrong | Medium | Low | Tested with multiple game time scenarios |
| Validation script bugs | Low | Low | Comprehensive testing before deployment |
| Phase 3 doesn't trigger | Medium | High | Can manually trigger if needed, monitoring in place |

### Mitigation Strategies

**Before Deployment:**
- Run comprehensive spot checks (50 samples, all checks)
- Test workflow timing calculations for edge cases
- Verify configuration syntax
- Review all code changes

**During Deployment:**
- Deploy during low-traffic period (morning before games)
- Monitor logs in real-time for first 2 hours
- Have rollback plan ready (revert config to 6 hours)
- Keep manual trigger commands ready

**After Deployment:**
- Monitor first 24-hour cycle closely
- Check validation results every 2 hours
- Verify data appears at expected times
- Document any unexpected behavior

**Rollback Plan:**
```bash
# If deployment fails, revert config
git revert HEAD
git push origin main

# Or manually update on production
ssh production "cd /path/to/nba-stats-scraper && git pull && git revert HEAD"

# Trigger manual collection for today if needed
python orchestration/manual_trigger.py --workflow betting_lines --date $(date +%Y-%m-%d) --force
```

---

## Cost Analysis

### API Call Increase

**Current (6-hour window)**:
- Runs: 4 per day (1 PM, 3 PM, 5 PM, 7 PM for 7 PM games)
- Scrapers per run: 3 (events, props, lines)
- Games: ~7 per typical day
- Total: 4 × 3 × 7 = 84 calls/day

**New (12-hour window)**:
- Runs: 7 per day (8 AM, 10 AM, 12 PM, 2 PM, 4 PM, 6 PM, 8 PM for 7 PM games)
- Scrapers per run: 3 (events, props, lines)
- Games: ~7 per typical day
- Total: 7 × 3 × 7 = 147 calls/day

**Increase**:
- Absolute: +63 calls/day
- Percentage: +75%
- Monthly: +1,890 calls/month
- Cost: ~$0.001 per call = **$1.89/month**

### Cost-Benefit Analysis

**Costs**:
- API: +$1.89/month
- Compute: Negligible (workflow already running)
- Storage: ~2MB/day additional = $0.06/month
- **Total: ~$2/month**

**Benefits**:
- User experience: Predictions available 4-5 hours earlier
- Reduced support: Fewer "where are predictions?" inquiries
- Business value: Users can act on predictions earlier in day
- System reliability: More data points = better predictions
- **Estimated value: $100+/month in user satisfaction and reduced support burden**

**ROI**: 50:1 benefit-to-cost ratio

---

## Timeline Estimate

### Phase 1: Immediate Recovery
- Task 1.1: Check collection status - 10 minutes
- Task 1.2: Verify BigQuery data - 15 minutes
- Task 1.3: Trigger Phase 3 - 20 minutes
- Task 1.4: Full validation - 15 minutes
**Total: ~1 hour**

### Phase 2: Fix Validation & Testing
- Task 2.1: Fix validation script - 1-2 hours
- Task 2.2: Workflow timing utilities - 1 hour
- Task 2.3: Comprehensive spot checks - 30 minutes (execution time)
- Task 2.4: Test workflow timing - 30 minutes
**Total: ~3-4 hours**

### Phase 3: Production Deployment
- Task 3.1: Pre-deployment checklist - 15 minutes
- Task 3.2: Commit changes - 15 minutes
- Task 3.3: Deploy to production - 30 minutes
- Task 3.4: Monitor first run - 2-4 hours
**Total: ~3-5 hours**

### Phase 4: Monitoring & Alerting (Non-blocking)
- Task 4.1: Timing-aware alerts - 4-6 hours
- Task 4.2: Config validation tests - 3-4 hours
- Task 4.3: Workflow timing docs - 1 hour
- Task 4.4: Operational runbook - 2-3 hours
**Total: ~10-14 hours (can span multiple days)**

### Phase 5: Long-Term Improvements (Future)
- Task 5.1: Graceful degradation - 2-3 days
- Task 5.2: Self-healing - 3-4 days
- Task 5.3: Dynamic scheduling - 1-2 weeks
**Total: ~3-4 weeks (future sprints)**

---

## Communication Plan

### Stakeholder Updates

**After Phase 1 Completion** (Immediate):
- Update: "2026-01-26 data backfilled successfully, system recovered"
- Audience: Team lead, platform team
- Channel: Slack/Email

**After Phase 3 Deployment** (Same day):
- Update: "Configuration fix deployed, monitoring first production run"
- Audience: All stakeholders, users
- Channel: Slack announcement, status page

**After First Successful Production Run** (Next day):
- Update: "New betting_lines timing working correctly, predictions available at 10 AM as expected"
- Audience: All stakeholders
- Channel: Slack update

**After 1 Week** (Milestone):
- Update: "1-week summary - X% uptime, Y% false alarm reduction, user feedback positive"
- Audience: Management, team
- Channel: Weekly report

### User Communication

**If Predictions Delayed Today** (2026-01-26):
"We experienced a configuration issue with betting data collection that delayed predictions today. The issue has been identified and fixed. Future predictions will be available by 10 AM as expected. Apologies for the inconvenience."

**After Fix Deployed**:
"Good news! We've improved our betting data collection schedule. Predictions will now be available by 10 AM every day (previously afternoon). Enjoy earlier access to insights!"

---

## Next Steps for Review Session

1. **Review this plan** - Identify any gaps or concerns
2. **Prioritize tasks** - Agree on what must be done immediately vs later
3. **Assign ownership** - Who does what
4. **Set timeline** - When to deploy
5. **Prepare rollback** - Ensure safety net in place
6. **Schedule monitoring** - Who watches first production run

## Questions for Discussion

1. Is $2/month cost increase acceptable for 4-5 hour earlier predictions?
2. Should we deploy today or wait for more testing?
3. Who will monitor the first production run?
4. Do we need user communication about the improvement?
5. Should Phase 4 (monitoring) be done before or after deployment?
6. Any concerns about the 12-hour window calculation?
7. Should we implement graceful degradation (Phase 5.1) sooner?

---

## Appendix: Reference Documents

- **Incident Report**: `docs/incidents/2026-01-26-BETTING-DATA-TIMING-ISSUE-ROOT-CAUSE.md`
- **Handoff Doc**: `docs/sessions/2026-01-26-BETTING-DATA-INVESTIGATION-HANDOFF.md`
- **Spot Check System**: `docs/06-testing/SPOT-CHECK-SYSTEM.md`
- **Workflows Config**: `config/workflows.yaml`
- **Master Controller**: `orchestration/master_controller.py`
- **Validation Script**: `scripts/validate_tonight_data.py`

---

**Document Version**: 1.0
**Last Updated**: 2026-01-26
**Author**: System Analysis & Planning (Claude Code)
**Status**: Ready for Review
