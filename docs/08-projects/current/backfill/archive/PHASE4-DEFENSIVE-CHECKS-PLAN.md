# Phase 4 Defensive Checks Implementation Plan

**Created:** 2025-11-28
**Status:** Planning
**Priority:** HIGH - Required before historical backfill
**Owner:** Engineering Team

---

## 📋 Executive Summary

Phase 4 (Precompute) processors currently have basic dependency checking but lack the robust **defensive checks** that Phase 3 (Analytics) processors have. This creates a risk during backfills where Phase 4 could process with incomplete Phase 3 data.

**Goal:** Add Phase 3-style defensive checks to Phase 4 processors to prevent processing with incomplete upstream data.

---

## 🔍 Current State Analysis

### Phase 4 Processors (5 total)

| Processor | Purpose | Depends On | Has Defensive Checks? |
|-----------|---------|-----------|---------------------|
| **team_defense_zone_analysis** | Team defensive metrics by zone | Phase 3: team_defense_game_summary | ❌ No |
| **player_shot_zone_analysis** | Player shot distribution | Phase 3: player_game_summary | ❌ No |
| **player_composite_factors** | Composite adjustment factors | Phase 3 + Phase 4 (team_defense_zone, player_shot_zone) | ❌ No |
| **player_daily_cache** | Cached player data for Phase 5 | Phase 3 + Phase 4 (all other Phase 4 tables) | ❌ No |
| **ml_feature_store** | ML features for predictions | Phase 3 + Phase 4 (all Phase 4 tables) | ❌ No |

**Processing Order:** (must run in this order due to dependencies)
1. team_defense_zone_analysis (11:00 PM) - depends only on Phase 3
2. player_shot_zone_analysis (11:15 PM) - depends only on Phase 3
3. player_composite_factors (11:30 PM) - depends on Phase 3 + Phase 4 tables from steps 1-2
4. player_daily_cache (11:45 PM) - depends on Phase 3 + all Phase 4 tables
5. ml_feature_store (12:00 AM) - depends on Phase 3 + all Phase 4 tables

### What Phase 4 Currently Has ✅

1. **CompletenessChecker imported** - All processors already import this
2. **Basic dependency checking** - `get_dependencies()` method defines upstream tables
3. **`check_dependencies()` method** - Checks if data exists and freshness
4. **Source metadata tracking** - Tracks upstream table versions
5. **Run history logging** - Via `RunHistoryMixin`

### What Phase 4 is Missing ❌

Comparing to Phase 3's defensive checks in `analytics_base.py:255-358`:

1. **`strict_mode` parameter** - Enable/disable defensive checks
2. **Gap detection in lookback windows** - Check for missing dates
3. **Upstream processor failure detection** - Check if upstream processor failed
4. **DependencyError exception** - Raised when checks fail
5. **Automatic bypass for backfill mode** - Defensive checks skip when `is_backfill_mode=True`
6. **Detailed alert notifications** - Alert with recovery steps

---

## 🎯 What Needs to Be Added

### 1. Update `precompute_base.py` (Base Class)

Add defensive checks method similar to Phase 3:

```python
def _run_defensive_checks(self, analysis_date: date, strict_mode: bool) -> None:
    """
    Run defensive checks to prevent processing with incomplete upstream data.

    Only runs when:
    - strict_mode=True (default)
    - is_backfill_mode=False (skip checks during backfills)

    Checks:
    1. Upstream processor status (did upstream processor succeed?)
    2. Gap detection in lookback window (any missing dates?)

    Raises:
        DependencyError: If defensive checks fail
    """
    # Skip defensive checks in backfill mode
    if self.is_backfill_mode:
        logger.info("⏭️  Skipping defensive checks (backfill mode)")
        return

    # Skip if strict mode disabled
    if not strict_mode:
        logger.info("⏭️  Defensive checks disabled (strict_mode=false)")
        return

    logger.info("🛡️  Running defensive checks...")

    # Import here to avoid circular dependency
    from shared.utils.completeness_checker import CompletenessChecker, DependencyError
    from datetime import timedelta

    checker = CompletenessChecker(self.bq_client, self.project_id)

    # DEFENSE 1: Check upstream Phase 3 processor status
    # Check if yesterday's Phase 3 processor succeeded
    # (Phase 4 typically runs day-of, so check day-before)
    if hasattr(self, 'upstream_processor_name') and self.upstream_processor_name:
        yesterday = analysis_date - timedelta(days=1)

        status = checker.check_upstream_processor_status(
            processor_name=self.upstream_processor_name,
            data_date=yesterday
        )

        if not status['safe_to_process']:
            error_msg = f"⚠️ Upstream processor {self.upstream_processor_name} failed for {yesterday}"

            # Send alert with recovery details
            self._send_defensive_check_alert(
                title=f"Precompute BLOCKED: Upstream Failure - {self.__class__.__name__}",
                message=error_msg,
                details={
                    'blocked_date': str(analysis_date),
                    'missing_upstream_date': str(yesterday),
                    'upstream_processor': self.upstream_processor_name,
                    'upstream_error': status['error_message'],
                    'resolution': f'Fix {self.upstream_processor_name} for {yesterday} first'
                }
            )

            raise DependencyError(error_msg)

    # DEFENSE 2: Check for gaps in lookback window
    # Check Phase 3 table for missing dates
    if hasattr(self, 'upstream_table') and hasattr(self, 'lookback_days'):
        lookback_start = analysis_date - timedelta(days=self.lookback_days)

        gaps = checker.check_date_range_completeness(
            table=self.upstream_table,
            date_column='game_date',
            start_date=lookback_start,
            end_date=analysis_date
        )

        if gaps['has_gaps']:
            error_msg = f"⚠️ {gaps['gap_count']} gaps in {self.upstream_table} lookback window"

            self._send_defensive_check_alert(
                title=f"Precompute BLOCKED: Data Gaps - {self.__class__.__name__}",
                message=error_msg,
                details={
                    'analysis_date': str(analysis_date),
                    'lookback_window': f"{lookback_start} to {analysis_date}",
                    'missing_dates': [str(d) for d in gaps['missing_dates'][:10]],
                    'gap_count': gaps['gap_count'],
                    'table': self.upstream_table,
                    'resolution': 'Fill gaps in upstream table before proceeding'
                }
            )

            raise DependencyError(error_msg)

    logger.info("✅ Defensive checks passed")
```

### 2. Add to `PrecomputeProcessorBase.run()` Method

Insert defensive checks before `check_dependencies()`:

```python
def run(self, **opts) -> bool:
    """Main processing method with defensive checks."""
    try:
        # ... existing setup code ...

        # Parse options
        self.opts = opts
        analysis_date = opts.get('analysis_date')
        strict_mode = opts.get('strict_mode', True)  # Default: enabled

        # ... existing validation ...

        # RUN DEFENSIVE CHECKS (NEW!)
        # This must run BEFORE check_dependencies()
        self._run_defensive_checks(analysis_date, strict_mode)

        # Check dependencies (existing code)
        dep_result = self.check_dependencies(analysis_date)

        # ... rest of existing code ...
```

### 3. Add Configuration to Each Phase 4 Processor

Each processor needs to define defensive check configuration:

**Example for `team_defense_zone_analysis_processor.py`:**

```python
class TeamDefenseZoneAnalysisProcessor(PrecomputeProcessorBase):

    # ... existing code ...

    # DEFENSIVE CHECK CONFIGURATION
    upstream_processor_name = 'TeamDefenseGameSummaryProcessor'  # Phase 3 processor
    upstream_table = 'nba_analytics.team_defense_game_summary'
    lookback_days = 15  # Check for gaps in last 15 days
```

**For all 5 processors:**

| Processor | upstream_processor_name | upstream_table | lookback_days |
|-----------|------------------------|---------------|---------------|
| **team_defense_zone_analysis** | TeamDefenseGameSummaryProcessor | nba_analytics.team_defense_game_summary | 15 |
| **player_shot_zone_analysis** | PlayerGameSummaryProcessor | nba_analytics.player_game_summary | 10 |
| **player_composite_factors** | UpcomingPlayerGameContextProcessor | nba_analytics.upcoming_player_game_context | 14 |
| **player_daily_cache** | PlayerGameSummaryProcessor | nba_analytics.player_game_summary | 10 |
| **ml_feature_store** | PlayerGameSummaryProcessor | nba_analytics.player_game_summary | 10 |

### 4. Add `DependencyError` to Completeness Checker

Already exists in `shared/utils/completeness_checker.py` - no changes needed.

### 5. Update CLI Parsers (Optional)

Add `--strict-mode` flag to each processor's CLI (if they have one):

```python
parser.add_argument(
    '--strict-mode',
    type=lambda x: x.lower() == 'true',
    default=True,
    help='Enable defensive checks (default: true, disable for testing)'
)
```

---

## ✅ Implementation Checklist

### Code Changes

- [ ] **Update `precompute_base.py`**
  - [ ] Add `_run_defensive_checks()` method
  - [ ] Add `_send_defensive_check_alert()` helper method
  - [ ] Call `_run_defensive_checks()` in `run()` method before `check_dependencies()`
  - [ ] Add `strict_mode` parameter to `run()` signature
  - [ ] Add `is_backfill_mode` detection logic

- [ ] **Update 5 Phase 4 processors**
  - [ ] team_defense_zone_analysis: Add defensive check config
  - [ ] player_shot_zone_analysis: Add defensive check config
  - [ ] player_composite_factors: Add defensive check config
  - [ ] player_daily_cache: Add defensive check config
  - [ ] ml_feature_store: Add defensive check config

- [ ] **Add CLI support (optional)**
  - [ ] Add `--strict-mode` flag to processors that have CLIs

### Testing Required

- [ ] Unit tests for `_run_defensive_checks()`
  - [ ] Test with upstream failure
  - [ ] Test with gaps in lookback window
  - [ ] Test backfill mode bypass
  - [ ] Test strict_mode=false bypass

- [ ] Integration tests
  - [ ] Simulate Phase 3 failure and verify Phase 4 blocks
  - [ ] Simulate Phase 3 gap and verify Phase 4 blocks
  - [ ] Verify backfill mode bypasses checks
  - [ ] Verify alerts are sent correctly

- [ ] End-to-end test
  - [ ] Test with small date range (1 week)
  - [ ] Verify Phase 3→4 cascade works
  - [ ] Verify defensive checks block bad data

---

## 🚀 Implementation Plan

### Phase 1: Base Class Updates (2-3 hours)

1. Update `precompute_base.py` with defensive checks method
2. Add helper methods for alerts
3. Integrate into `run()` method
4. Add backfill mode detection

### Phase 2: Processor Updates (1-2 hours)

1. Add defensive check config to all 5 processors
2. Test each processor individually
3. Verify configurations are correct

### Phase 3: Testing (2-3 hours)

1. Write unit tests for defensive checks
2. Write integration tests
3. End-to-end test with simulated failures

### Phase 4: Documentation (1 hour)

1. Update processor documentation
2. Update backfill guide
3. Create troubleshooting guide

**Total Estimated Time:** 6-9 hours

---

## 📊 Success Criteria

**Defensive checks successfully implemented when:**

1. ✅ Phase 4 processors block when Phase 3 upstream processor fails
2. ✅ Phase 4 processors block when gaps detected in Phase 3 lookback window
3. ✅ Defensive checks automatically bypassed in backfill mode
4. ✅ Clear, actionable alerts sent when blocking occurs
5. ✅ All tests passing
6. ✅ No false positives in production

---

## 🔗 Related Documents

- **Backfill Strategy:** `BACKFILL-STRATEGY-PHASES-1-5.md`
- **Pipeline Integrity:** `../pipeline-integrity/BACKFILL-STRATEGY.md`
- **Phase 3 Implementation:** See `analytics_base.py:255-358` for reference

---

## 📝 Notes

**Why Phase 4 Needs This:**

During backfills, if Phase 3 has failures or gaps, Phase 4 should NOT process until Phase 3 is fixed. Without defensive checks:
- Phase 4 processes with incomplete Phase 3 data
- Bad precompute data cascades to Phase 5
- Phase 5 predictions are based on incomplete features
- Data integrity compromised

**Why Backfill Mode Bypass:**

During historical backfills, we batch load Phase 3 for all dates first, THEN run Phase 4. By the time Phase 4 runs, all Phase 3 data is complete. Defensive checks would be redundant and might cause false positives, so we bypass them in backfill mode.

**Phase 5 Not Included:**

Phase 5 (Predictions) is forward-looking only. It queries upcoming games from Phase 3 and features from Phase 4. It's not part of historical backfill workflow, so no defensive check changes needed.

---

**Status:** Ready for Implementation
**Next Step:** Update `precompute_base.py` with defensive checks
**Owner:** Engineering Team
**Created:** 2025-11-28
