# Validation Coverage Improvements

**Status**: ✅ COMPLETE & COMMITTED
**Implementation Date**: 2026-01-27
**Git Commits**: `b7057482`, `38fdf6bd`, `4c160376`, `9a6baaa9`
**Priority**: P1 - Data Quality Prevention
**Created**: 2026-01-27
**Origin**: Lessons learned from BDL field extraction bug (usage_rate NULL issue)

**📋 Documentation**:
- **For Review**: [`2026-01-27-VALIDATION-IMPROVEMENTS-FOR-REVIEW.md`](../../09-handoff/2026-01-27-VALIDATION-IMPROVEMENTS-FOR-REVIEW.md)
- **Implementation Guide**: [`2026-01-27-VALIDATION-IMPROVEMENTS-COMPLETE.md`](../../09-handoff/2026-01-27-VALIDATION-IMPROVEMENTS-COMPLETE.md)
- **Session Summary**: [`2026-01-27-SESSION-SUMMARY.md`](../../09-handoff/2026-01-27-SESSION-SUMMARY.md)

---

## Problem Statement

On Jan 27, 2026, we discovered that usage_rate was NULL for all players on Jan 15-23 even though:
1. Team stats existed and could be joined
2. The calculation logic was correct
3. Manual queries worked perfectly

**Root Cause**: The processor SQL was extracting BDL shooting stats as NULL (`NULL as field_goals_attempted`) even though BDL actually has these fields. The bug existed in historical data but wasn't caught because:

1. **Daily validation only checks current data** - Historical data isn't validated
2. **No post-backfill validation** - After running backfills, we don't automatically verify quality
3. **No field-level NULL rate checks** - We check usage_rate coverage but not the underlying fields

---

## Current Validation Architecture

### What We Have

| Component | Coverage | Gap |
|-----------|----------|-----|
| `validate_tonight_data.py` | Today/yesterday data | No historical |
| `spot_check_data_accuracy.py` | Sample-based accuracy | No field completeness |
| `/validate-daily` skill | Comprehensive daily checks | No post-backfill |
| `/spot-check-gaps` skill | Player coverage gaps | No field-level analysis |
| Data Lineage gates | Processing order | Not deployed yet |

### Thresholds (Already Defined)

From `validate_tonight_data.py`:
```python
MINUTES_THRESHOLD = 90.0  # Alert if <90% have minutes_played
USAGE_THRESHOLD = 90.0    # Alert if <90% of active players have usage_rate
```

### The Gap

| Scenario | Currently Covered? | Impact |
|----------|-------------------|--------|
| Today's data has low usage_rate coverage | ✅ Yes | Caught |
| Historical data has low usage_rate coverage | ❌ No | **BUG MISSED** |
| Backfill completes but doesn't improve data | ❌ No | **BUG MISSED** |
| Source fields (fg_attempts) are NULL | ❌ No | **ROOT CAUSE MISSED** |
| Processor change breaks historical processing | ❌ No | **REGRESSION MISSED** |

---

## Proposed Improvements

### 1. Post-Backfill Validation (HIGH PRIORITY)

**Goal**: After any backfill completes, automatically run validation on affected dates.

**Implementation**:
```python
# In backfill base class or wrapper
class BackfillValidator:
    def validate_after_backfill(self, processed_dates: List[date]) -> ValidationReport:
        """Run validation checks on all processed dates."""
        issues = []
        for date in processed_dates:
            result = self.check_date_quality(date)
            if not result.passed:
                issues.append(result)

        if issues:
            self.alert_and_log(issues)
            return ValidationReport(status='FAILED', issues=issues)

        return ValidationReport(status='PASSED')

    def check_date_quality(self, date: date) -> DateQualityResult:
        """Check all quality metrics for a single date."""
        return DateQualityResult(
            date=date,
            player_coverage=self._check_player_coverage(date),
            usage_rate_coverage=self._check_usage_rate(date),
            field_completeness=self._check_field_completeness(date),
            passed=all([...])
        )
```

**Files to create/modify**:
- `shared/validation/backfill_validator.py` (NEW)
- `backfill_jobs/base_backfill.py` (ADD validation hook)

### 2. Field-Level Completeness Check (HIGH PRIORITY)

**Goal**: Track NULL rates for critical fields, not just derived metrics.

**Critical Fields to Monitor**:
| Table | Field | Expected NULL Rate |
|-------|-------|-------------------|
| player_game_summary | field_goals_attempted | <5% for active players |
| player_game_summary | free_throws_attempted | <5% for active players |
| player_game_summary | usage_rate | <10% for active players |
| player_game_summary | source_team_last_updated | <5% |
| team_offense_game_summary | fg_attempts | 0% |

**Implementation**:
```python
def check_field_completeness(self, date: date, table: str) -> FieldCompletenessReport:
    """Check NULL rates for critical fields."""
    query = f"""
    SELECT
        '{date}' as game_date,
        COUNT(*) as total,
        COUNTIF(field_goals_attempted IS NULL) as fg_attempts_null,
        COUNTIF(free_throws_attempted IS NULL) as ft_attempts_null,
        COUNTIF(usage_rate IS NULL AND minutes_played > 0) as usage_null_active,
        ROUND(100.0 * COUNTIF(field_goals_attempted IS NULL) / COUNT(*), 1) as fg_null_pct,
        ROUND(100.0 * COUNTIF(free_throws_attempted IS NULL) / COUNT(*), 1) as ft_null_pct
    FROM `{project}.nba_analytics.player_game_summary`
    WHERE game_date = '{date}'
    """
    # ... run and check against thresholds
```

**Files to create/modify**:
- `shared/validation/field_completeness.py` (NEW)
- `scripts/validate_tonight_data.py` (ADD field checks)

### 3. Historical Coverage Audit Skill (MEDIUM PRIORITY)

**Goal**: A `/validate-historical` skill that checks coverage across date ranges.

**Usage**:
```
/validate-historical 2026-01-01 2026-01-27
/validate-historical --season 2025-26
```

**Output**:
```
=== HISTORICAL COVERAGE AUDIT ===
Period: 2026-01-01 to 2026-01-27

FIELD COMPLETENESS BY DATE:
| Date       | Total | usage_rate | fg_attempts | ft_attempts | Status |
|------------|-------|------------|-------------|-------------|--------|
| 2026-01-15 |   316 |       0.0% |        0.0% |        0.0% | FAIL   |
| 2026-01-16 |   298 |       0.0% |        0.0% |        0.0% | FAIL   |
| ...        |   ... |        ... |         ... |         ... |  ...   |
| 2026-01-24 |   312 |      78.2% |       99.1% |       98.7% | WARN   |
| 2026-01-25 |   305 |      35.4% |       99.0% |       98.5% | WARN   |

DATES NEEDING ATTENTION:
- 2026-01-15 to 2026-01-23: usage_rate at 0% (CRITICAL)
- 2026-01-24 to 2026-01-25: usage_rate below 90% (WARNING)

RECOMMENDED ACTIONS:
1. Reprocess player_game_summary for Jan 15-25
2. Verify team_offense_game_summary exists for those dates
3. Check processor logs for errors
```

**Files to create**:
- `.claude/skills/validate-historical.md` (NEW)
- `scripts/validate_historical_coverage.py` (NEW)

### 4. Pre-Deployment Regression Test (MEDIUM PRIORITY)

**Goal**: Before deploying processor changes, run on sample historical dates and verify no regression.

**Implementation**:
```python
# In CI/CD or pre-deploy script
def regression_test_processor(processor_class, sample_dates=['2026-01-15', '2026-01-22']):
    """
    Run processor on historical dates and verify output quality.

    Checks:
    1. Extraction includes expected fields (not NULL)
    2. Coverage meets thresholds
    3. Calculations produce non-NULL results
    """
    for date in sample_dates:
        processor = processor_class()
        processor.extract_raw_data(date, date)

        # Check critical fields aren't NULL
        assert processor.raw_data['field_goals_attempted'].notna().mean() > 0.9, \
            f"field_goals_attempted NULL rate too high for {date}"

        # Run transform and check output
        processor.transform_data()
        usage_coverage = processor.processed_data['usage_rate'].notna().mean()
        assert usage_coverage > 0.8, \
            f"usage_rate coverage {usage_coverage:.1%} below 80% for {date}"

    return True
```

**Files to create**:
- `tests/regression/test_processor_historical.py` (NEW)
- `.github/workflows/regression-test.yml` (ADD step)

### 5. Automated Alert for Coverage Drops (LOW PRIORITY)

**Goal**: If daily validation shows coverage drop vs previous day, alert immediately.

**Implementation**:
```python
def check_coverage_trend(self, current_date: date) -> TrendAlert:
    """Compare today's coverage to yesterday's."""
    today = self.get_coverage(current_date)
    yesterday = self.get_coverage(current_date - timedelta(days=1))

    if today.usage_rate_pct < yesterday.usage_rate_pct - 10:
        return TrendAlert(
            severity='CRITICAL',
            message=f'usage_rate coverage dropped from {yesterday.usage_rate_pct}% to {today.usage_rate_pct}%',
            recommended_action='Check processor changes, raw data availability'
        )
```

---

## Integration with Existing System

### Skill Integration

| New Component | Integrates With |
|---------------|-----------------|
| Post-backfill validation | `backfill_jobs/base_backfill.py` |
| Field completeness checks | `scripts/validate_tonight_data.py` |
| `/validate-historical` skill | `.claude/skills/` directory |
| Regression tests | CI/CD pipeline, `tests/` |

### Where to Hook In

1. **Backfill scripts**: Add `BackfillValidator.validate_after_backfill()` call after processing
2. **Daily validation**: Add field completeness checks to `check_data_quality()` method
3. **Skills**: Create new skill file following existing patterns
4. **CI/CD**: Add regression test step before deployment

---

## Implementation Priority

| Task | Priority | Effort | Impact |
|------|----------|--------|--------|
| Post-backfill validation | HIGH | 4-6 hours | Catches issues immediately |
| Field-level completeness | HIGH | 2-4 hours | Would have caught today's bug |
| `/validate-historical` skill | MEDIUM | 4-6 hours | Enables historical audits |
| Regression tests | MEDIUM | 4-6 hours | Prevents future regressions |
| Coverage trend alerts | LOW | 2 hours | Nice-to-have alerting |

---

## Files Reference

### Existing Files to Study
- `scripts/validate_tonight_data.py` - Current validation script
- `scripts/spot_check_data_accuracy.py` - Spot check implementation
- `.claude/skills/validate-daily/SKILL.md` - Daily validation skill
- `.claude/skills/spot-check-gaps.md` - Gap detection skill
- `shared/validation/processing_gate.py` - Processing gates (NEW, not deployed)
- `shared/validation/window_completeness.py` - Window completeness (NEW, not deployed)

### New Files to Create
- `shared/validation/backfill_validator.py`
- `shared/validation/field_completeness.py`
- `.claude/skills/validate-historical.md`
- `scripts/validate_historical_coverage.py`
- `tests/regression/test_processor_historical.py`

---

## Success Criteria

After implementation:

- [ ] Running a backfill automatically validates results
- [ ] Field NULL rates are checked (not just derived metrics)
- [ ] Historical date ranges can be audited with one command
- [ ] Processor changes are tested against historical data before deploy
- [ ] Coverage drops trigger immediate alerts

---

## Related Documentation

- [Data Lineage Integrity](../data-lineage-integrity/README.md) - Cascade contamination tracking
- [Validation Framework](../validation-framework/README.md) - Multi-angle validation
- [Spot Check System](../../../06-testing/SPOT-CHECK-SYSTEM.md) - Data accuracy verification

---

**Created**: 2026-01-27 by Opus
**Origin**: Jan 27 usage_rate bug investigation
