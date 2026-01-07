# Validation Framework - Implementation Plan
**Date**: 2026-01-05
**Goal**: Build production-ready validation framework
**Timeline**: 4 weeks
**Priority**: High (prevents data loss)

---

## Overview

This plan implements the comprehensive validation framework designed in `VALIDATION-FRAMEWORK-DESIGN.md`.

**Why this matters:**
- Prevents missing tables (like we missed 3/5 Phase 3 tables)
- Catches issues in minutes (pre-flight) vs hours (post-backfill)
- Provides continuous monitoring to detect degradation
- Gives confidence to declare "COMPLETE" with certainty

---

## Phase 1: Core Validators (Week 1)

### Day 1-2: Build Pre-Flight Validator

**File**: `/home/naji/code/nba-stats-scraper/bin/backfill/preflight_comprehensive.py`

**Tasks:**
1. Create base `PreFlightValidator` class
2. Implement prerequisite checking
   - Phase 3 requires Phase 2 raw data
   - Phase 4 requires ALL 5 Phase 3 tables (not just player_game_summary!)
   - Phase 5 requires Phase 4
3. Implement gap identification
   - Query each table for coverage
   - Compare against expected game dates
   - Identify missing date ranges
4. Implement conflict detection
   - Check for running processes
   - Check for duplicates in target tables
5. Implement resource estimation
   - Calculate expected runtime
   - Estimate data volume
   - Check BigQuery quota availability
6. Add output formats
   - Human-readable console output
   - JSON for automation
   - Exit codes (0=pass, 1=fail, 2=warnings)

**Success Criteria:**
```bash
# Should PASS - Phase 3 is complete
python bin/backfill/preflight_comprehensive.py \
  --target-phase 4 \
  --start-date 2024-01-01 \
  --end-date 2024-12-31

# Should FAIL - Phase 3 incomplete for 2021-2023
python bin/backfill/preflight_comprehensive.py \
  --target-phase 4 \
  --start-date 2021-10-19 \
  --end-date 2023-06-30

# Should output valid JSON
python bin/backfill/preflight_comprehensive.py \
  --target-phase 4 \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --json | jq .
```

**Code Structure:**
```python
class PreFlightValidator:
    # Hardcoded table lists (CRITICAL - prevents missing tables)
    PHASE_3_TABLES = [
        'player_game_summary',
        'team_defense_game_summary',      # Was missed!
        'team_offense_game_summary',
        'upcoming_player_game_context',   # Was missed!
        'upcoming_team_game_context',     # Was missed!
    ]

    PHASE_4_TABLES = [
        'player_composite_factors',
        'team_defense_zone_analysis',
        'player_shot_zone_analysis',
        'player_daily_cache',
        'ml_feature_store_v2',
    ]

    def run_all_checks(self) -> bool:
        """Run all pre-flight checks."""
        self._check_prerequisite_phases()
        self._check_current_state()
        self._identify_gaps()
        self._validate_existing_quality()
        self._check_conflicts()
        self._estimate_resources()
        self._check_environment()
        return self._is_safe_to_proceed()
```

### Day 3-4: Build Post-Flight Validator

**File**: `/home/naji/code/nba-stats-scraper/bin/backfill/postflight_comprehensive.py`

**Tasks:**
1. Create base `PostFlightValidator` class
2. Implement coverage validation
   - Check each table meets ≥95% threshold (or 88% for Phase 4 with bootstrap)
   - Identify missing date ranges
3. Implement data quality checks
   - NULL rates for critical fields
   - Duplicate detection
   - Future date detection
   - Quality score validation
4. Implement dependency validation
   - Verify next phase can run
   - Check all required fields exist
5. Generate detailed reports
   - JSON reports with all metrics
   - HTML reports for human review
   - CSV exports for tracking over time

**Success Criteria:**
```bash
# Should PASS - Phase 3 is complete for 2024
python bin/backfill/postflight_comprehensive.py \
  --phase 3 \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --report logs/phase3_2024_validation.json

# Should FAIL - Phase 3 incomplete for 2021-2023
python bin/backfill/postflight_comprehensive.py \
  --phase 3 \
  --start-date 2021-10-19 \
  --end-date 2023-06-30 \
  --report logs/phase3_2021-2023_validation.json

# Report should be valid JSON
jq . logs/phase3_2024_validation.json
```

**Code Structure:**
```python
class PostFlightValidator:
    QUALITY_THRESHOLDS = {
        'coverage_pct': 95.0,
        'minutes_played_null_pct_max': 10.0,
        'usage_rate_null_pct_max': 55.0,
        'min_quality_score': 75.0,
    }

    def run_all_checks(self) -> bool:
        """Run all post-flight checks."""
        tables = self._get_phase_tables()

        for table in tables:
            result = self._validate_table(table)
            self.results.append(result)

        self._print_summary()
        return self._all_complete()

    def _validate_table(self, table_name: str):
        """Validate a single table."""
        coverage = self._get_coverage(table_name)
        quality = self._calculate_quality_score(table_name)
        issues = self._check_data_quality(table_name)

        return PostFlightResult(
            table_name=table_name,
            coverage_pct=coverage,
            quality_score=quality,
            issues=issues
        )
```

### Day 5: Integration Testing

**Tasks:**
1. Test pre-flight validator on real data
   - Run against 2024 data (should PASS)
   - Run against 2021-2023 data (should FAIL for Phase 4)
2. Test post-flight validator on real data
   - Run after Phase 3 backfill
   - Verify reports are accurate
3. Test edge cases
   - Empty date ranges
   - Invalid dates
   - Network failures
   - BigQuery quota errors
4. Create test suite
   - Unit tests for validators
   - Integration tests with real BigQuery

**Deliverables:**
- [ ] `bin/backfill/preflight_comprehensive.py` working
- [ ] `bin/backfill/postflight_comprehensive.py` working
- [ ] Test suite in `tests/validation/`
- [ ] Documentation in each script's docstring

---

## Phase 2: Orchestrator Integration (Week 2)

### Day 1: Update Orchestrator Template

**File**: `/home/naji/code/nba-stats-scraper/scripts/backfill_orchestrator_v2.sh`

**Tasks:**
1. Add pre-flight validation gate at start
   ```bash
   # GATE 1: Pre-flight validation
   if ! python3 bin/backfill/preflight_comprehensive.py \
       --target-phase $TARGET_PHASE \
       --start-date $START_DATE \
       --end-date $END_DATE; then
       log_error "PRE-FLIGHT FAILED - aborting"
       exit 1
   fi
   ```

2. Add post-flight validation after each phase
   ```bash
   # GATE 2: Post-flight validation
   if ! python3 bin/backfill/postflight_comprehensive.py \
       --phase $PHASE \
       --start-date $START_DATE \
       --end-date $END_DATE \
       --report logs/phase${PHASE}_validation.json; then
       log_error "POST-FLIGHT FAILED - do not proceed to next phase"
       exit 1
   fi
   ```

3. Add fail-fast on validation errors
   - Stop immediately if pre-flight fails
   - Stop immediately if post-flight fails
   - Prevent starting next phase if previous phase incomplete

**Success Criteria:**
```bash
# Should stop at pre-flight if Phase 3 incomplete
./scripts/backfill_orchestrator_v2.sh \
  --target-phase 4 \
  --start-date 2021-10-19 \
  --end-date 2023-06-30
# Should exit with code 1 before running any backfill

# Should stop after Phase 3 if validation fails
./scripts/backfill_orchestrator_v2.sh \
  --phases 3,4 \
  --start-date 2024-01-01 \
  --end-date 2024-12-31
# Should run Phase 3, validate, then proceed to Phase 4
```

### Day 2: Add Checkpoint System

**Tasks:**
1. Create checkpoint file structure
   ```bash
   CHECKPOINT_DIR="/tmp/backfill_checkpoints"
   CHECKPOINT_FILE="$CHECKPOINT_DIR/phase${PHASE}_${START_DATE}_${END_DATE}.json"
   ```

2. Save checkpoint after each successful validation
   ```bash
   save_checkpoint() {
       cat > "$CHECKPOINT_FILE" <<EOF
   {
     "phase": $PHASE,
     "status": "validated",
     "timestamp": "$(date -Iseconds)",
     "validation_report": "$VALIDATION_REPORT",
     "next_phase": $((PHASE + 1))
   }
   EOF
   }
   ```

3. Add resume capability
   ```bash
   # Resume from last validated phase
   ./scripts/backfill_orchestrator_v2.sh \
     --resume \
     --checkpoint /tmp/backfill_checkpoints/phase3_2024-01-01_2024-12-31.json
   ```

**Success Criteria:**
```bash
# Run Phase 3, create checkpoint
./scripts/backfill_orchestrator_v2.sh --phase 3 --start-date 2024-01-01 --end-date 2024-12-31

# Resume from Phase 4 (skips Phase 3)
./scripts/backfill_orchestrator_v2.sh --resume --checkpoint /tmp/backfill_checkpoints/phase3_*.json
```

### Day 3-4: Validation Gate Logic

**Tasks:**
1. Implement smart validation decisions
   ```python
   def should_run_backfill(phase, start_date, end_date):
       """Determine if backfill is needed."""
       # Check current coverage
       coverage = get_phase_coverage(phase, start_date, end_date)

       # If already >95%, skip
       if coverage >= 95.0:
           return False, "Already complete"

       # If <50%, recommend full backfill
       if coverage < 50.0:
           return True, "Low coverage - full backfill needed"

       # If 50-95%, recommend incremental backfill
       return True, "Partial coverage - incremental backfill recommended"
   ```

2. Add automatic rollback on failure
   ```bash
   rollback_on_failure() {
       local phase=$1
       log_error "Phase $phase validation FAILED"
       log_info "Rolling back changes..."

       # Delete data for this date range
       bq query --use_legacy_sql=false "
         DELETE FROM \`nba-props-platform.nba_analytics.player_game_summary\`
         WHERE game_date >= '$START_DATE'
           AND game_date <= '$END_DATE'
           AND created_at >= TIMESTAMP('$BACKFILL_START_TIME')
       "

       log_success "Rollback complete"
   }
   ```

3. Add dry-run mode
   ```bash
   ./scripts/backfill_orchestrator_v2.sh \
     --phase 3 \
     --start-date 2024-01-01 \
     --end-date 2024-12-31 \
     --dry-run
   # Should show what would happen without actually running
   ```

**Success Criteria:**
- Orchestrator only runs backfill if needed
- Automatic rollback on validation failure
- Dry-run shows complete execution plan

### Day 5: End-to-End Testing

**Tasks:**
1. Test full orchestration flow
   - Phase 3 backfill → validation → Phase 4 backfill → validation
2. Test failure scenarios
   - Phase 3 validation fails → stops before Phase 4
   - Phase 4 validation fails → rollback Phase 4 data
3. Test resume capability
   - Run Phase 3 → checkpoint → resume from Phase 4
4. Performance testing
   - Validate orchestrator doesn't add significant overhead

**Deliverables:**
- [ ] `scripts/backfill_orchestrator_v2.sh` fully integrated
- [ ] Checkpoint system working
- [ ] Validation gates preventing bad backfills
- [ ] Test results documented

---

## Phase 3: Checklists & Documentation (Week 3)

### Day 1: Phase 3 Completion Checklist

**File**: `/home/naji/code/nba-stats-scraper/docs/validation-framework/PHASE3-COMPLETION-CHECKLIST.md`

**Content:**
- [ ] All 5 Phase 3 tables listed (with checkboxes)
- [ ] Coverage requirements for each table
- [ ] Data quality checks to run
- [ ] Validation commands
- [ ] Sign-off section

**Format:**
```markdown
# Phase 3 Analytics - Completion Checklist

## Required Tables (5/5)

- [ ] player_game_summary (≥95% coverage)
  ```bash
  python bin/backfill/verify_phase3_for_phase4.py --start-date X --end-date Y
  ```

- [ ] team_defense_game_summary (≥95% coverage)
  ```sql
  SELECT COUNT(DISTINCT game_date) FROM ...
  ```

...

## Sign-Off

Date: _______________
Validated by: _______________
Report: `phase3_validation_report.json`
```

### Day 2: Phase 4 Completion Checklist

**File**: `/home/naji/code/nba-stats-scraper/docs/validation-framework/PHASE4-COMPLETION-CHECKLIST.md`

**Content:**
- [ ] All 5 Phase 4 tables listed
- [ ] Bootstrap period validation
- [ ] ML readiness checks
- [ ] Feature validation
- [ ] Sign-off section

### Day 3: Phase 5 Completion Checklist

**File**: `/home/naji/code/nba-stats-scraper/docs/validation-framework/PHASE5-COMPLETION-CHECKLIST.md`

**Content:**
- [ ] Predictions table validation
- [ ] All 5 prediction systems present
- [ ] Prop line coverage checks
- [ ] Quality tier distribution
- [ ] Sign-off section

### Day 4: Validation Commands Reference

**File**: `/home/naji/code/nba-stats-scraper/docs/validation-framework/VALIDATION-COMMANDS.md`

**Content:**
```markdown
# Validation Commands - Quick Reference

## Pre-Flight

### Phase 3
\`\`\`bash
python bin/backfill/preflight_comprehensive.py --target-phase 3 --start-date X --end-date Y
\`\`\`

### Phase 4
\`\`\`bash
python bin/backfill/preflight_comprehensive.py --target-phase 4 --start-date X --end-date Y --strict
\`\`\`

## Post-Flight

### Phase 3
\`\`\`bash
python bin/backfill/postflight_comprehensive.py --phase 3 --start-date X --end-date Y --report validation.json
\`\`\`

...
```

### Day 5: User Training Materials

**Tasks:**
1. Create training video/walkthrough
2. Create troubleshooting guide
3. Update main README with validation section
4. Create validation framework index

**Deliverables:**
- [ ] 3 completion checklists (Phase 3, 4, 5)
- [ ] Validation commands reference
- [ ] Troubleshooting guide
- [ ] Training materials

---

## Phase 4: Continuous Monitoring (Week 4)

### Day 1-2: Daily Validation Monitor

**File**: `/home/naji/code/nba-stats-scraper/scripts/monitoring/daily_validation.py`

**Tasks:**
1. Build `DailyValidator` class
   - Check last 30 days coverage for all phases
   - Compare against thresholds
   - Detect degradation
2. Add alerting
   - Email on coverage drop
   - Slack webhook integration
   - Log to monitoring system
3. Create cron schedule
   ```bash
   # Run daily at 8 AM
   0 8 * * * cd /home/naji/code/nba-stats-scraper && python scripts/monitoring/daily_validation.py --alert-on-failure
   ```

**Success Criteria:**
```bash
# Should PASS for recent data
python scripts/monitoring/daily_validation.py

# Should send alert if coverage drops
# (Test by temporarily deleting recent data)
python scripts/monitoring/daily_validation.py --alert-on-failure
```

### Day 3-4: Weekly Coverage Report

**File**: `/home/naji/code/nba-stats-scraper/scripts/monitoring/weekly_coverage_report.py`

**Tasks:**
1. Build `WeeklyCoverageReport` class
   - Generate coverage trends over time
   - Create charts/visualizations
   - Export to PDF/HTML
2. Add historical tracking
   - Save weekly snapshots
   - Track coverage over months
   - Identify long-term trends
3. Create cron schedule
   ```bash
   # Run weekly on Monday at 9 AM
   0 9 * * 1 cd /home/naji/code/nba-stats-scraper && python scripts/monitoring/weekly_coverage_report.py --email
   ```

**Deliverables:**
- [ ] `daily_validation.py` with alerting
- [ ] `weekly_coverage_report.py` with visualizations
- [ ] Cron schedules configured
- [ ] Alert email templates
- [ ] Dashboard for tracking (optional)

---

## Testing & Validation (Throughout)

### Unit Tests

**File**: `/home/naji/code/nba-stats-scraper/tests/validation/test_preflight.py`

```python
def test_preflight_detects_missing_tables():
    """Test that pre-flight catches missing Phase 3 tables."""
    validator = PreFlightValidator(
        target_phase=4,
        start_date=date(2021, 10, 19),
        end_date=date(2023, 6, 30)
    )

    # Should fail because Phase 3 incomplete for 2021-2023
    assert not validator.run_all_checks()

    # Should identify which tables are incomplete
    failures = [r for r in validator.results if r.status == 'FAIL']
    assert len(failures) > 0
```

### Integration Tests

**File**: `/home/naji/code/nba-stats-scraper/tests/validation/test_orchestrator_integration.py`

```python
def test_orchestrator_stops_on_preflight_failure():
    """Test that orchestrator stops if pre-flight fails."""
    # Run orchestrator for incomplete date range
    result = subprocess.run([
        './scripts/backfill_orchestrator_v2.sh',
        '--target-phase', '4',
        '--start-date', '2021-10-19',
        '--end-date', '2023-06-30'
    ], capture_output=True)

    # Should exit with error code
    assert result.returncode == 1

    # Should not have run backfill
    assert 'PRE-FLIGHT FAILED' in result.stderr.decode()
```

---

## Success Metrics

Track these metrics to measure framework effectiveness:

### Before Framework
- **Tables missed**: 3/5 Phase 3 tables (60% accuracy)
- **Time to detect gap**: 3 months
- **False "COMPLETE" declarations**: Multiple
- **Manual validation effort**: ~2 hours per backfill

### After Framework
- **Tables missed**: 0 (100% accuracy)
- **Time to detect gap**: <5 minutes (pre-flight)
- **False "COMPLETE" declarations**: 0 (checkklist sign-off required)
- **Manual validation effort**: ~10 minutes (run commands)

### Continuous Improvement
- **Coverage monitoring**: Daily checks
- **Degradation detection**: Within 24 hours
- **Alert response time**: <2 hours
- **False positive rate**: <5%

---

## Rollout Strategy

### Week 1 (Phase 1)
1. Build validators in parallel (pre-flight + post-flight)
2. Test on sample data
3. Deploy to dev environment

### Week 2 (Phase 2)
1. Integrate with orchestrator
2. Test full backfill flow
3. Deploy to staging environment

### Week 3 (Phase 3)
1. Create checklists
2. Train team on new workflow
3. Update documentation

### Week 4 (Phase 4)
1. Set up continuous monitoring
2. Configure alerts
3. Deploy to production
4. Monitor for 1 week

### Week 5 (Validation)
1. Retrospective on framework
2. Gather feedback
3. Iterate on improvements

---

## Maintenance Plan

### Monthly
- Review validation reports
- Update thresholds if needed
- Check for false positives

### Quarterly
- Add new tables to validators
- Update checklists
- Review alert effectiveness

### Annually
- Major version updates
- Architecture improvements
- Add new validation types

---

## Budget & Resources

### Developer Time
- **Week 1**: 40 hours (1 FTE)
- **Week 2**: 40 hours (1 FTE)
- **Week 3**: 40 hours (1 FTE)
- **Week 4**: 40 hours (1 FTE)
- **Total**: 160 hours

### Infrastructure
- BigQuery query costs: ~$50/month
- Email/alerting: ~$20/month
- Storage for reports: ~$5/month
- **Total**: ~$75/month

### ROI Calculation
- **Time saved per backfill**: 1.5 hours
- **Backfills per month**: ~4
- **Monthly savings**: 6 hours
- **Annual savings**: 72 hours
- **Payback period**: ~2.2 months

---

## Next Steps

1. **Review this plan** with team
2. **Get approval** to proceed
3. **Create tickets** for each phase
4. **Assign ownership** for each component
5. **Start Week 1** implementation

---

**Let's build a validation framework that ensures we NEVER miss tables again!**
