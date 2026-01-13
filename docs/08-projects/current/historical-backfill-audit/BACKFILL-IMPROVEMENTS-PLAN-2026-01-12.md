# Backfill System Improvements Plan
**Date:** 2026-01-12
**Trigger:** Partial backfill incident on Jan 6, 2026
**Goal:** Prevent silent failures and improve observability

---

## Priority Overview

| Priority | Category | Impact | Effort | Target |
|----------|----------|--------|--------|--------|
| 🔴 P0 | Coverage Validation | HIGH | LOW | This week |
| 🔴 P0 | Defensive Logging | HIGH | LOW | This week |
| 🟡 P1 | Fallback Logic Fix | MEDIUM | MEDIUM | Next week |
| 🟡 P1 | Data Cleanup | MEDIUM | LOW | Next week |
| 🟢 P2 | Alerting | MEDIUM | MEDIUM | 2 weeks |
| 🟢 P2 | Validation Framework | HIGH | HIGH | 1 month |

---

## 🔴 P0: Critical Immediate Fixes (This Week)

### 1. Add Coverage Validation to Backfill Script

**Problem:** Backfill completes "successfully" even when processing < 1% of expected players

**Solution:** Add post-processing validation before checkpointing

**Location:** `backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py`

**Implementation:**
```python
def _validate_coverage(self, analysis_date: date, players_processed: int) -> bool:
    """Validate that we processed the expected number of players."""

    # Get expected count from player_game_summary
    query = f"""
    SELECT COUNT(DISTINCT player_lookup) as expected_players
    FROM `{project_id}.nba_analytics.player_game_summary`
    WHERE game_date = '{analysis_date}'
    """
    result = bq_client.query(query).to_dataframe()
    expected = result['expected_players'].iloc[0] if not result.empty else 0

    if expected == 0:
        logger.warning(f"No expected players for {analysis_date} (off-day or bootstrap)")
        return True  # Allow empty dates

    coverage_pct = (players_processed / expected) * 100 if expected > 0 else 0

    # Critical threshold: Must process at least 90% of expected players
    if coverage_pct < 90:
        logger.error(
            f"❌ COVERAGE VALIDATION FAILED for {analysis_date}: "
            f"Processed {players_processed}/{expected} players ({coverage_pct:.1f}%)"
        )
        return False

    # Warning threshold: Flag if less than 95%
    elif coverage_pct < 95:
        logger.warning(
            f"⚠️  Low coverage for {analysis_date}: "
            f"Processed {players_processed}/{expected} players ({coverage_pct:.1f}%)"
        )

    logger.info(
        f"✅ Coverage validation passed for {analysis_date}: "
        f"{players_processed}/{expected} players ({coverage_pct:.1f}%)"
    )
    return True

# In main backfill loop:
for game_date in game_dates:
    result = processor.run(analysis_date=game_date)
    players_processed = result.get('players_processed', 0)

    # VALIDATION GATE - Do not checkpoint if validation fails
    if not _validate_coverage(game_date, players_processed):
        logger.error(f"Halting backfill due to coverage validation failure")
        checkpoint.mark_failed(game_date, reason="coverage_validation_failed")
        # Option 1: Continue to next date
        # Option 2: sys.exit(1) to halt entire backfill
        raise ValueError(f"Coverage validation failed for {game_date}")

    checkpoint.mark_success(game_date)
```

**Acceptance Criteria:**
- ✅ Compare actual vs expected player count
- ✅ Block checkpoint if coverage < 90%
- ✅ Log warning if coverage < 95%
- ✅ Exit code 1 if validation fails (for CI/CD)

**Effort:** 2-3 hours
**Testing:** Run on 2023-02-23 dry-run (should fail before fix, pass after)

---

### 2. Add Defensive Logging to PCF Processor

**Problem:** No visibility into what data source was used or why

**Solution:** Add comprehensive logging at key decision points

**Location:** `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Implementation:**
```python
def extract_raw_data(self, analysis_date: date) -> None:
    """Extract player context with defensive logging."""

    # Query upcoming_player_game_context
    self.player_context_df = self.bq_client.query(player_context_query).to_dataframe()
    upcg_count = len(self.player_context_df)

    # Get expected count from player_game_summary
    pgs_query = f"""
    SELECT COUNT(DISTINCT player_lookup) as player_count
    FROM `{self.project_id}.nba_analytics.player_game_summary`
    WHERE game_date = '{analysis_date}'
    """
    pgs_result = self.bq_client.query(pgs_query).to_dataframe()
    expected_count = pgs_result['player_count'].iloc[0] if not pgs_result.empty else 0

    # DEFENSIVE LOGGING
    logger.info(
        f"📊 Data source check for {analysis_date}:\n"
        f"  - upcoming_player_game_context: {upcg_count} players\n"
        f"  - player_game_summary: {expected_count} players\n"
        f"  - Coverage: {(upcg_count/expected_count*100) if expected_count > 0 else 0:.1f}%"
    )

    # Enhanced fallback logic
    if upcg_count == 0 and self.is_backfill_mode:
        logger.warning(
            f"⚠️  No upcoming_player_game_context for {analysis_date}, "
            f"generating synthetic context from PGS (backfill mode)"
        )
        self._generate_synthetic_player_context(analysis_date)

    elif upcg_count < expected_count * 0.9 and self.is_backfill_mode:
        logger.error(
            f"❌ INCOMPLETE DATA DETECTED for {analysis_date}:\n"
            f"  - upcoming_player_game_context has only {upcg_count}/{expected_count} players "
            f"({(upcg_count/expected_count*100):.1f}%)\n"
            f"  - This indicates stale/partial data in UPCG table\n"
            f"  - Falling back to synthetic context from player_game_summary"
        )
        self._generate_synthetic_player_context(analysis_date)

    elif upcg_count > 0:
        logger.info(
            f"✅ Using upcoming_player_game_context: {upcg_count} players\n"
            f"  - Expected: {expected_count} (from PGS)\n"
            f"  - Source: UPCG table"
        )

    else:
        logger.warning(
            f"⚠️  No players found for {analysis_date} in any source\n"
            f"  - This might be an off-day or bootstrap period"
        )
```

**Acceptance Criteria:**
- ✅ Log player counts from both sources (UPCG and PGS)
- ✅ Log which source is being used and why
- ✅ Log coverage percentage for comparison
- ✅ Clearly flag incomplete data situations

**Effort:** 1-2 hours
**Testing:** Run on 2023-02-23 and verify logs show the comparison

---

### 3. Fix Fallback Logic Threshold

**Problem:** Fallback only triggers when UPCG is completely empty, not when incomplete

**Solution:** Enhance condition to check for substantial incompleteness

**Location:** `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py:678`

**Current Code:**
```python
if self.player_context_df.empty and self.is_backfill_mode:
    self._generate_synthetic_player_context(analysis_date)
```

**Improved Code:**
```python
# Calculate expected player count
expected_query = f"""
SELECT COUNT(DISTINCT player_lookup) as player_count
FROM `{self.project_id}.nba_analytics.player_game_summary`
WHERE game_date = '{analysis_date}'
"""
expected_result = self.bq_client.query(expected_query).to_dataframe()
expected_count = expected_result['player_count'].iloc[0] if not expected_result.empty else 0

actual_count = len(self.player_context_df)

# Trigger fallback if UPCG is empty OR substantially incomplete
if self.is_backfill_mode and (actual_count == 0 or actual_count < expected_count * 0.9):
    if actual_count == 0:
        logger.warning(
            f"No upcoming_player_game_context for {analysis_date}, "
            "generating synthetic context from PGS"
        )
    else:
        logger.error(
            f"INCOMPLETE upcoming_player_game_context for {analysis_date}: "
            f"{actual_count}/{expected_count} players ({actual_count/expected_count*100:.1f}%), "
            "falling back to synthetic context from PGS"
        )

    self._generate_synthetic_player_context(analysis_date)
```

**Acceptance Criteria:**
- ✅ Trigger fallback when UPCG count < 90% of PGS count
- ✅ Log clear reason why fallback was triggered
- ✅ Prevent partial data from being used silently

**Effort:** 2 hours
**Testing:** Create test case with partial UPCG data, verify fallback triggers

---

### 4. Clear Stale upcoming_player_game_context Records

**Problem:** Historical dates have stale data in "upcoming" table

**Solution:** One-time cleanup + ongoing TTL policy

**Implementation:**

**One-Time Cleanup:**
```sql
-- Backup first
CREATE TABLE `nba-props-platform.nba_analytics.upcoming_player_game_context_backup_20260112` AS
SELECT * FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`;

-- Delete historical records (anything older than 7 days)
DELETE FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date < CURRENT_DATE() - INTERVAL 7 DAY;

-- Verify deletion
SELECT
  'Before' as period,
  COUNT(*) as records,
  MIN(game_date) as oldest_date,
  MAX(game_date) as newest_date
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context_backup_20260112`

UNION ALL

SELECT
  'After' as period,
  COUNT(*) as records,
  MIN(game_date) as oldest_date,
  MAX(game_date) as newest_date
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`;
```

**Ongoing TTL Policy:**
Add to daily cleanup job:
```python
# In orchestration/cloud_functions/daily_cleanup/main.py
def cleanup_upcoming_context_tables():
    """Remove stale data from upcoming_* tables after games complete."""

    cleanup_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    tables = [
        'nba_analytics.upcoming_player_game_context',
        'nba_analytics.upcoming_team_game_context'
    ]

    for table in tables:
        query = f"""
        DELETE FROM `{project_id}.{table}`
        WHERE game_date < '{cleanup_date}'
        """

        job = bq_client.query(query)
        deleted = job.result().total_rows

        logger.info(f"Cleaned up {table}: deleted {deleted} stale records older than {cleanup_date}")
```

**Acceptance Criteria:**
- ✅ Backup existing data before cleanup
- ✅ Delete records older than 7 days
- ✅ Automated daily cleanup going forward
- ✅ Verify no upcoming games are deleted

**Effort:** 1 hour (cleanup) + 2 hours (TTL automation)
**Testing:** Verify cleanup doesn't delete truly upcoming games

---

## 🟡 P1: Important Near-Term Fixes (Next 2 Weeks)

### 5. Add Pre-Flight Coverage Check

**Problem:** Backfill starts without verifying upstream data is complete

**Solution:** Add validation before processing begins

**Location:** `backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py`

**Implementation:**
```python
def _pre_flight_coverage_check(date_range: List[date]) -> bool:
    """Verify upstream data completeness before starting backfill."""

    logger.info("=" * 80)
    logger.info("PRE-FLIGHT COVERAGE CHECK")
    logger.info("=" * 80)

    issues_found = []

    for analysis_date in date_range:
        # Check player_game_summary
        pgs_query = f"""
        SELECT COUNT(DISTINCT player_lookup) as player_count
        FROM `{project_id}.nba_analytics.player_game_summary`
        WHERE game_date = '{analysis_date}'
        """
        pgs_result = bq_client.query(pgs_query).to_dataframe()
        pgs_count = pgs_result['player_count'].iloc[0] if not pgs_result.empty else 0

        # Check upcoming_player_game_context
        upcg_query = f"""
        SELECT COUNT(DISTINCT player_lookup) as player_count
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{analysis_date}'
        """
        upcg_result = bq_client.query(upcg_query).to_dataframe()
        upcg_count = upcg_result['player_count'].iloc[0] if not upcg_result.empty else 0

        # Detect potential issues
        if pgs_count == 0:
            logger.info(f"  {analysis_date}: No games (off-day or bootstrap)")
        elif upcg_count > 0 and upcg_count < pgs_count * 0.9:
            issue = {
                'date': analysis_date,
                'pgs_count': pgs_count,
                'upcg_count': upcg_count,
                'coverage': (upcg_count / pgs_count * 100) if pgs_count > 0 else 0
            }
            issues_found.append(issue)
            logger.warning(
                f"  ⚠️  {analysis_date}: UPCG has partial data "
                f"({upcg_count}/{pgs_count} = {issue['coverage']:.1f}%)"
            )
        else:
            logger.info(f"  ✅ {analysis_date}: Data looks good (PGS: {pgs_count}, UPCG: {upcg_count})")

    if issues_found:
        logger.error("=" * 80)
        logger.error("⚠️  PRE-FLIGHT CHECK FOUND ISSUES")
        logger.error("=" * 80)
        logger.error(f"Found {len(issues_found)} dates with partial upcoming_player_game_context data:")
        for issue in issues_found:
            logger.error(
                f"  - {issue['date']}: {issue['upcg_count']}/{issue['pgs_count']} "
                f"({issue['coverage']:.1f}% coverage)"
            )
        logger.error("")
        logger.error("RECOMMENDATION: Clear stale UPCG records before running backfill:")
        logger.error("  DELETE FROM upcoming_player_game_context WHERE game_date IN (...)")
        logger.error("  OR ensure fallback logic will handle incomplete data correctly")
        logger.error("=" * 80)

        # Option to proceed anyway
        if not args.force:
            logger.error("Aborting backfill (use --force to proceed anyway)")
            return False

    logger.info("✅ Pre-flight coverage check complete")
    return True

# In main():
if not args.skip_preflight:
    if not _pre_flight_coverage_check(game_dates):
        sys.exit(1)
```

**Acceptance Criteria:**
- ✅ Check all dates in range before processing
- ✅ Detect partial data in UPCG table
- ✅ Provide clear remediation steps
- ✅ Allow --force to proceed anyway

**Effort:** 3-4 hours
**Testing:** Run on date ranges with partial UPCG data

---

### 6. Enhanced Failure Tracking

**Problem:** No records in `precompute_failures` table for partial coverage

**Solution:** Track both failures AND suboptimal successes

**Location:** `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Implementation:**
```python
def finalize(self):
    """Enhanced finalize with coverage tracking."""

    # Existing failure tracking...
    super().finalize()

    # NEW: Track suboptimal coverage
    if self.is_backfill_mode and hasattr(self, 'players_processed'):
        analysis_date = self.opts.get('analysis_date')

        # Get expected count
        expected_query = f"""
        SELECT COUNT(DISTINCT player_lookup) as player_count
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date = '{analysis_date}'
        """
        result = self.bq_client.query(expected_query).to_dataframe()
        expected = result['player_count'].iloc[0] if not result.empty else 0

        actual = self.players_processed
        coverage_pct = (actual / expected * 100) if expected > 0 else 100

        # Log to processing metadata table
        metadata_record = {
            'processor_name': 'PlayerCompositeFactorsProcessor',
            'run_id': self.run_id,
            'analysis_date': analysis_date,
            'expected_players': expected,
            'actual_players': actual,
            'coverage_pct': coverage_pct,
            'data_source': 'UPCG' if self.used_upcg else 'PGS_SYNTHETIC',
            'status': 'COMPLETE' if coverage_pct >= 90 else 'INCOMPLETE',
            'created_at': datetime.now(timezone.utc)
        }

        # Insert into new tracking table
        self._insert_processing_metadata(metadata_record)

        # Also add to failures table if substantially incomplete
        if coverage_pct < 90:
            self.track_failure(
                entity_id=f"coverage_{analysis_date}",
                entity_type='DATE',
                category='INCOMPLETE_COVERAGE',
                reason=f"Only processed {actual}/{expected} players ({coverage_pct:.1f}%)",
                can_retry=True,
                missing_game_ids=None
            )
```

**Acceptance Criteria:**
- ✅ Track expected vs actual player counts
- ✅ Record which data source was used (UPCG vs synthetic)
- ✅ Add failure record if coverage < 90%
- ✅ Create processing_metadata table for trend analysis

**Effort:** 4 hours
**Testing:** Verify metadata is logged for both complete and incomplete runs

---

## 🟢 P2: Medium-Term Improvements (Next Month)

### 7. Alerting and Monitoring

**Goal:** Real-time notification of backfill issues

**Components:**
1. **Slack Alerts** for coverage < 90%
2. **Email Summary** of backfill completion
3. **Datadog Metrics** for coverage trends

**Implementation:**
```python
# In backfill script
def _alert_on_coverage_issues(issues: List[Dict]):
    """Send Slack alert for coverage validation failures."""

    if not issues:
        return

    message = {
        "text": "⚠️ Backfill Coverage Issues Detected",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Backfill Coverage Alert*\nFound {len(issues)} dates with incomplete coverage:"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*{issue['date']}*\n{issue['actual']}/{issue['expected']} ({issue['coverage']:.1f}%)"
                    }
                    for issue in issues[:10]  # Limit to 10
                ]
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Logs"},
                        "url": f"https://console.cloud.google.com/logs?project=nba-props-platform"
                    }
                ]
            }
        ]
    }

    requests.post(SLACK_WEBHOOK_URL, json=message)
```

**Metrics to Track:**
- `backfill.coverage_pct` (by date, processor)
- `backfill.players_processed` (by date)
- `backfill.players_expected` (by date)
- `backfill.data_source` (UPCG vs synthetic)

**Effort:** 6-8 hours
**Testing:** Trigger on test backfill with incomplete data

---

### 8. Separate Historical vs Upcoming Code Paths

**Goal:** Clear separation of concerns for backfill vs real-time

**Approach:**
```python
class PlayerCompositeFactorsProcessor:

    def extract_raw_data(self, analysis_date: date):
        if self._is_historical_date(analysis_date):
            return self._extract_historical_data(analysis_date)
        else:
            return self._extract_upcoming_data(analysis_date)

    def _is_historical_date(self, analysis_date: date) -> bool:
        """Determine if this is a historical backfill vs upcoming game."""
        return analysis_date < date.today()

    def _extract_historical_data(self, analysis_date: date):
        """Always use player_game_summary for historical dates."""
        logger.info(f"Historical mode: Using player_game_summary for {analysis_date}")
        self._generate_synthetic_player_context(analysis_date)
        # ... rest of extraction

    def _extract_upcoming_data(self, analysis_date: date):
        """Use upcoming_player_game_context for future games."""
        logger.info(f"Upcoming mode: Using upcoming_player_game_context for {analysis_date}")
        # ... existing UPCG logic
```

**Benefits:**
- Clear intent in code
- No fallback logic needed for historical dates
- Prevents stale UPCG data from being used for backfills

**Effort:** 8-10 hours
**Testing:** Verify both paths work correctly

---

### 9. Automated Validation Framework

**Goal:** Comprehensive post-backfill verification suite

**Components:**
1. Coverage validation (player count)
2. Data quality validation (NULL checks, range checks)
3. Cascade validation (downstream dependencies)
4. Historical comparison (vs previous backfills)

**Implementation:**
```python
# scripts/validate_backfill_results.py

class BackfillValidator:

    def validate_coverage(self, date_range: List[date]) -> ValidationReport:
        """Validate player coverage for date range."""
        # Compare PCF vs PGS counts
        # Flag any date with < 90% coverage
        pass

    def validate_data_quality(self, date_range: List[date]) -> ValidationReport:
        """Validate data quality metrics."""
        # Check for NULL in critical fields
        # Validate value ranges (scores 0-100, etc.)
        # Check for suspicious values (all zeros, etc.)
        pass

    def validate_cascade(self, date_range: List[date]) -> ValidationReport:
        """Validate downstream dependencies are satisfied."""
        # Check if Phase 5 can be triggered
        # Verify no missing dependencies
        pass

    def generate_report(self) -> str:
        """Generate comprehensive validation report."""
        # Markdown report with all validation results
        # Include pass/fail for each check
        # Provide remediation steps for failures
        pass

# Usage in backfill script:
validator = BackfillValidator()
report = validator.run_full_validation(start_date, end_date)
if not report.all_passed:
    logger.error(report.summary)
    sys.exit(1)
```

**Effort:** 16-20 hours (full framework)
**Testing:** Run on completed backfills, verify catches known issues

---

## Implementation Timeline

### Week 1 (Jan 13-19)
- [x] Day 1-2: P0 items 1-2 (Coverage validation + defensive logging)
- [ ] Day 3: P0 item 3 (Fallback logic fix)
- [ ] Day 4: P0 item 4 (Data cleanup)
- [ ] Day 5: Testing and documentation

### Week 2 (Jan 20-26)
- [ ] Day 1-2: P1 item 5 (Pre-flight check)
- [ ] Day 3-4: P1 item 6 (Failure tracking)
- [ ] Day 5: Testing

### Week 3-4 (Jan 27 - Feb 9)
- [ ] P2 items 7-9 (Alerting, code separation, validation framework)

---

## Success Metrics

### Immediate (After P0)
- ✅ Zero partial backfills (coverage always >= 90%)
- ✅ Clear log messages indicating data source and coverage
- ✅ Validation failures caught before checkpointing

### Near-Term (After P1)
- ✅ Pre-flight checks catch 100% of stale data issues
- ✅ All incomplete runs logged to failures table
- ✅ Zero silent failures

### Long-Term (After P2)
- ✅ Automated daily validation runs
- ✅ Slack alerts for any coverage < 95%
- ✅ Datadog dashboard showing backfill health trends
- ✅ Mean-time-to-detect (MTTD) < 1 hour for issues

---

## Testing Strategy

### Unit Tests
```python
def test_coverage_validation_fails_on_partial_data():
    # Arrange: Mock PGS with 100 players, PCF processed 50
    # Act: Run _validate_coverage()
    # Assert: Returns False, logs error
    pass

def test_fallback_triggers_on_partial_upcg():
    # Arrange: UPCG has 10 players, PGS has 100
    # Act: Run extract_raw_data()
    # Assert: Uses synthetic context from PGS
    pass
```

### Integration Tests
```python
def test_backfill_with_stale_upcg_data():
    # Arrange: Insert partial UPCG data
    # Act: Run backfill
    # Assert: Fails pre-flight check OR uses fallback correctly
    pass
```

### End-to-End Tests
```python
def test_full_backfill_with_validation():
    # Arrange: Clear UPCG for test date
    # Act: Run backfill with all validations enabled
    # Assert: 100% coverage, all validations pass
    pass
```

---

## Rollout Plan

### Phase 1: Deploy P0 (Week 1)
1. Deploy defensive logging (low risk)
2. Deploy coverage validation (medium risk - could block backfills)
3. Deploy fallback fix (medium risk - changes core logic)
4. Run data cleanup (one-time, reversible with backup)

**Rollback Plan:** If coverage validation blocks legitimate backfills, add --skip-validation flag

### Phase 2: Deploy P1 (Week 2)
1. Deploy pre-flight check (low risk - informational only)
2. Deploy failure tracking (low risk - additive only)
3. Enable pre-flight blocking (medium risk - could prevent backfills)

**Rollback Plan:** Use --skip-preflight flag to bypass if needed

### Phase 3: Deploy P2 (Weeks 3-4)
1. Deploy alerting (low risk - notification only)
2. Deploy code separation (high risk - major refactor)
3. Deploy validation framework (medium risk - can run separately)

**Rollback Plan:** Code separation is reversible with git revert

---

## Documentation Updates Needed

1. **Backfill Guide:**
   - Add section on coverage validation
   - Document --force and --skip-validation flags
   - Add troubleshooting guide for stale UPCG data

2. **Operations Runbook:**
   - Add section on monitoring backfill health
   - Document how to investigate coverage alerts
   - Add standard remediation steps

3. **Architecture Docs:**
   - Document historical vs upcoming data paths
   - Explain UPCG cleanup policy
   - Document validation framework

---

## Cost/Benefit Analysis

### Costs
- **Development Time:** ~40-50 hours total
- **Testing Time:** ~10-15 hours
- **Code Complexity:** Moderate increase (validation logic)
- **Maintenance:** Additional monitoring to maintain

### Benefits
- **Prevent Data Loss:** Zero tolerance for partial backfills
- **Faster Detection:** < 1 hour vs 6 days
- **Reduced Investigation Time:** Clear logs save hours
- **Improved Confidence:** Validated data quality
- **Better Observability:** Real-time metrics and alerts

### ROI
- **Time Saved:** 6 days detection + hours of investigation = ~50 hours saved per incident
- **Risk Reduction:** Critical data quality issues caught immediately
- **Trust:** Engineering and business trust in data pipeline

**Conclusion:** High ROI, especially for P0 and P1 items (20 hours investment, 50+ hours saved)

---

**Status:** Ready for implementation
**Owner:** TBD
**Review Date:** Weekly during implementation
