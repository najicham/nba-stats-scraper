# Chat 5: Validation Coverage Improvements

## Copy Everything Below This Line

---

## Context

You are implementing validation improvements for an NBA Props Platform. Today (Jan 27, 2026), we discovered a bug where `usage_rate` was NULL for 9 days of historical data even though all the required data existed. The root cause was that the processor SQL was extracting BDL fields as NULL when they actually have values.

**The bug was caught late because:**
1. Daily validation only checks current data (today/yesterday)
2. No automatic validation after backfills
3. No field-level NULL rate checks (we checked usage_rate but not the underlying fields)

**Your mission**: Implement validation improvements to prevent similar issues from going undetected.

---

## Project Documentation

**Read this first**:
```bash
cat docs/08-projects/current/validation-coverage-improvements/README.md
```

This contains the full design for all improvements.

---

## Your Tasks (In Priority Order)

### Task 1: Add Field-Level Completeness Checks (2-4 hours)

**Goal**: Check NULL rates for critical source fields, not just derived metrics.

**File to modify**: `scripts/validate_tonight_data.py`

**Add to `check_data_quality()` method** (around line 456):

```python
def check_field_completeness(self, check_date: date) -> bool:
    """
    Check NULL rates for critical fields.

    These are the SOURCE fields needed for calculations like usage_rate.
    If these are NULL, downstream calculations will fail.
    """
    query = f"""
    SELECT
        COUNT(*) as total,
        -- Source fields (from raw data extraction)
        ROUND(100.0 * COUNTIF(field_goals_attempted IS NOT NULL) / NULLIF(COUNT(*), 0), 1) as fg_attempts_pct,
        ROUND(100.0 * COUNTIF(free_throws_attempted IS NOT NULL) / NULLIF(COUNT(*), 0), 1) as ft_attempts_pct,
        ROUND(100.0 * COUNTIF(three_pointers_attempted IS NOT NULL) / NULLIF(COUNT(*), 0), 1) as three_attempts_pct,
        -- For active players only
        COUNTIF(minutes_played > 0) as active_players,
        ROUND(100.0 * COUNTIF(minutes_played > 0 AND field_goals_attempted IS NOT NULL) /
              NULLIF(COUNTIF(minutes_played > 0), 0), 1) as active_fg_pct
    FROM `{self.project}.nba_analytics.player_game_summary`
    WHERE game_date = '{check_date}'
    """

    result = list(self.client.query(query).result())[0]

    # Thresholds
    FG_THRESHOLD = 90.0  # At least 90% should have field_goals_attempted
    FT_THRESHOLD = 90.0

    passed = True

    if result.active_fg_pct and result.active_fg_pct < FG_THRESHOLD:
        self.add_issue('field_completeness',
            f'field_goals_attempted coverage is {result.active_fg_pct}% for active players (threshold: {FG_THRESHOLD}%)',
            severity='CRITICAL')
        passed = False

    # Add to stats for reporting
    self.stats['field_fg_attempts_pct'] = result.active_fg_pct
    self.stats['field_ft_attempts_pct'] = result.ft_attempts_pct

    print(f"{'✅' if passed else '❌'} Field Completeness ({check_date}):")
    print(f"   - field_goals_attempted: {result.active_fg_pct}% for active players")
    print(f"   - free_throws_attempted: {result.ft_attempts_pct}%")

    return passed
```

**Then call it from the main validation flow**.

### Task 2: Create `/validate-historical` Skill (4-6 hours)

**Goal**: Enable auditing historical date ranges with one command.

**File to create**: `.claude/skills/validate-historical.md`

```markdown
---
name: validate-historical
description: Validate historical data completeness and quality over date ranges
---

# /validate-historical - Historical Coverage Audit

Audit data quality across a date range to find coverage gaps and field completeness issues.

## Usage

```
/validate-historical [start_date] [end_date]
/validate-historical --season 2025-26
```

## What This Skill Does

### Step 1: Query Coverage by Date

```sql
SELECT
    game_date,
    COUNT(*) as total_records,
    COUNTIF(minutes_played > 0) as active_players,
    -- Field completeness
    ROUND(100.0 * COUNTIF(field_goals_attempted IS NOT NULL) / NULLIF(COUNT(*), 0), 1) as fg_attempts_pct,
    ROUND(100.0 * COUNTIF(free_throws_attempted IS NOT NULL) / NULLIF(COUNT(*), 0), 1) as ft_attempts_pct,
    -- Derived metric coverage
    ROUND(100.0 * COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) /
          NULLIF(COUNTIF(minutes_played > 0), 0), 1) as usage_rate_pct,
    -- Status
    CASE
        WHEN COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) /
             NULLIF(COUNTIF(minutes_played > 0), 0) < 0.5 THEN 'CRITICAL'
        WHEN COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) /
             NULLIF(COUNTIF(minutes_played > 0), 0) < 0.9 THEN 'WARNING'
        ELSE 'OK'
    END as status
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN @start_date AND @end_date
GROUP BY game_date
ORDER BY game_date
```

### Step 2: Identify Problem Dates

Flag dates where:
- `usage_rate_pct` < 90% for active players
- `fg_attempts_pct` < 95%
- `ft_attempts_pct` < 95%

### Step 3: Generate Report

```
=== HISTORICAL COVERAGE AUDIT ===
Period: {start_date} to {end_date}

SUMMARY:
- Total dates checked: 27
- Dates with issues: 11
- Critical issues: 9 (Jan 15-23)
- Warnings: 2 (Jan 24-25)

PROBLEM DATES:
| Date       | Active | usage_rate | fg_attempts | Status   |
|------------|--------|------------|-------------|----------|
| 2026-01-15 |    205 |       0.0% |        0.0% | CRITICAL |
| 2026-01-16 |    198 |       0.0% |        0.0% | CRITICAL |
...

RECOMMENDED ACTIONS:
1. For CRITICAL dates (Jan 15-23):
   - Check if processor was updated with fix
   - Re-run backfill for affected dates
   - Verify team_offense_game_summary exists

2. For WARNING dates (Jan 24-25):
   - Investigate source data availability
   - Check for partial processing
```

## Thresholds

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| usage_rate (active) | ≥90% | 50-89% | <50% |
| fg_attempts | ≥95% | 80-94% | <80% |
| ft_attempts | ≥95% | 80-94% | <80% |

## When to Use

- After deploying processor changes
- After running backfills
- Weekly data quality audit
- Before ML model retraining
- When investigating historical issues
```

### Task 3: Create Post-Backfill Validation Module (4-6 hours)

**Goal**: Automatically validate data after backfills complete.

**File to create**: `shared/validation/backfill_validator.py`

```python
"""
Post-Backfill Validation Module

Automatically validates data quality after backfill operations complete.
Catches issues like NULL field extraction, missing joins, calculation failures.

Usage:
    from shared.validation.backfill_validator import BackfillValidator

    validator = BackfillValidator(bq_client, project_id)
    report = validator.validate_dates(processed_dates)

    if not report.passed:
        logger.error(f"Backfill validation FAILED: {report.issues}")
        # Optionally: raise exception, send alert, etc.
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Optional
from google.cloud import bigquery

logger = logging.getLogger(__name__)


@dataclass
class FieldCompletenessResult:
    """Result of field completeness check."""
    date: date
    total_records: int
    active_players: int
    fg_attempts_pct: float
    ft_attempts_pct: float
    usage_rate_pct: float
    passed: bool
    issues: List[str]


@dataclass
class ValidationReport:
    """Overall validation report for backfill."""
    dates_checked: int
    dates_passed: int
    dates_failed: int
    passed: bool
    issues: List[str]
    results_by_date: Dict[date, FieldCompletenessResult]


class BackfillValidator:
    """Validates data quality after backfill operations."""

    # Thresholds
    FG_ATTEMPTS_THRESHOLD = 90.0
    FT_ATTEMPTS_THRESHOLD = 90.0
    USAGE_RATE_THRESHOLD = 80.0  # Slightly lower for backfills

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        self.client = bq_client
        self.project = project_id

    def validate_dates(self, dates: List[date]) -> ValidationReport:
        """
        Validate all processed dates.

        Args:
            dates: List of dates that were processed

        Returns:
            ValidationReport with overall status and per-date results
        """
        results = {}
        issues = []

        for d in dates:
            result = self.check_date_quality(d)
            results[d] = result
            if not result.passed:
                issues.extend([f"{d}: {issue}" for issue in result.issues])

        dates_passed = sum(1 for r in results.values() if r.passed)
        dates_failed = len(dates) - dates_passed

        return ValidationReport(
            dates_checked=len(dates),
            dates_passed=dates_passed,
            dates_failed=dates_failed,
            passed=(dates_failed == 0),
            issues=issues,
            results_by_date=results
        )

    def check_date_quality(self, check_date: date) -> FieldCompletenessResult:
        """Check field completeness for a single date."""
        query = f"""
        SELECT
            COUNT(*) as total_records,
            COUNTIF(minutes_played > 0) as active_players,
            ROUND(100.0 * COUNTIF(minutes_played > 0 AND field_goals_attempted IS NOT NULL) /
                  NULLIF(COUNTIF(minutes_played > 0), 0), 1) as fg_attempts_pct,
            ROUND(100.0 * COUNTIF(minutes_played > 0 AND free_throws_attempted IS NOT NULL) /
                  NULLIF(COUNTIF(minutes_played > 0), 0), 1) as ft_attempts_pct,
            ROUND(100.0 * COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) /
                  NULLIF(COUNTIF(minutes_played > 0), 0), 1) as usage_rate_pct
        FROM `{self.project}.nba_analytics.player_game_summary`
        WHERE game_date = '{check_date}'
        """

        result = list(self.client.query(query).result())[0]

        issues = []
        passed = True

        # Check thresholds
        if result.fg_attempts_pct is not None and result.fg_attempts_pct < self.FG_ATTEMPTS_THRESHOLD:
            issues.append(f"field_goals_attempted coverage {result.fg_attempts_pct}% < {self.FG_ATTEMPTS_THRESHOLD}%")
            passed = False

        if result.ft_attempts_pct is not None and result.ft_attempts_pct < self.FT_ATTEMPTS_THRESHOLD:
            issues.append(f"free_throws_attempted coverage {result.ft_attempts_pct}% < {self.FT_ATTEMPTS_THRESHOLD}%")
            passed = False

        if result.usage_rate_pct is not None and result.usage_rate_pct < self.USAGE_RATE_THRESHOLD:
            issues.append(f"usage_rate coverage {result.usage_rate_pct}% < {self.USAGE_RATE_THRESHOLD}%")
            passed = False

        return FieldCompletenessResult(
            date=check_date,
            total_records=result.total_records or 0,
            active_players=result.active_players or 0,
            fg_attempts_pct=result.fg_attempts_pct or 0,
            ft_attempts_pct=result.ft_attempts_pct or 0,
            usage_rate_pct=result.usage_rate_pct or 0,
            passed=passed,
            issues=issues
        )

    def log_report(self, report: ValidationReport) -> None:
        """Log validation report."""
        if report.passed:
            logger.info(f"✅ Backfill validation PASSED: {report.dates_passed}/{report.dates_checked} dates OK")
        else:
            logger.error(f"❌ Backfill validation FAILED: {report.dates_failed}/{report.dates_checked} dates with issues")
            for issue in report.issues[:10]:  # Limit to first 10
                logger.error(f"   - {issue}")
            if len(report.issues) > 10:
                logger.error(f"   ... and {len(report.issues) - 10} more issues")
```

### Task 4: Integrate Validator into Backfill Scripts (2 hours)

**Goal**: Call the validator after backfills complete.

**File to modify**: `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py`

**Add after processing completes**:

```python
# After all dates processed, validate results
from shared.validation.backfill_validator import BackfillValidator

validator = BackfillValidator(self.bq_client, self.project_id)
report = validator.validate_dates(processed_dates)
validator.log_report(report)

if not report.passed:
    logger.warning("Backfill completed but validation found issues - review before proceeding")
    # Could optionally: raise exception, send alert, etc.
```

---

## Files to Read for Context

Before starting, read these:

```bash
# Current validation script
cat scripts/validate_tonight_data.py | head -200

# Spot check system
cat scripts/spot_check_data_accuracy.py | head -100

# Existing validate-daily skill
cat .claude/skills/validate-daily/SKILL.md | head -100

# Existing spot-check-gaps skill (for reference)
cat .claude/skills/spot-check-gaps.md

# Processing gate (already built but not deployed)
cat shared/validation/processing_gate.py | head -50

# Project documentation
cat docs/08-projects/current/validation-coverage-improvements/README.md
```

---

## Testing Your Work

### Test Field Completeness Check

```bash
# Run validation for today
python scripts/validate_tonight_data.py

# Should now show field completeness in output
```

### Test `/validate-historical` Skill

After creating the skill file, test it:
```
/validate-historical 2026-01-15 2026-01-27
```

### Test BackfillValidator Module

```python
# Quick test
python -c "
from shared.validation.backfill_validator import BackfillValidator
from google.cloud import bigquery
from datetime import date

client = bigquery.Client()
validator = BackfillValidator(client, 'nba-props-platform')

# Test on one date
result = validator.check_date_quality(date(2026, 1, 22))
print(f'Date: {result.date}')
print(f'Active players: {result.active_players}')
print(f'FG attempts: {result.fg_attempts_pct}%')
print(f'Usage rate: {result.usage_rate_pct}%')
print(f'Passed: {result.passed}')
print(f'Issues: {result.issues}')
"
```

---

## Success Criteria

Before finishing, verify:

- [ ] `validate_tonight_data.py` includes field completeness checks
- [ ] Field completeness output shows fg_attempts and ft_attempts coverage
- [ ] `/validate-historical` skill file created
- [ ] `BackfillValidator` module created and tested
- [ ] At least one backfill script calls the validator
- [ ] All code passes basic syntax checks (imports work)

---

## Handoff Notes

When complete, create:
`docs/09-handoff/2026-01-27-VALIDATION-IMPROVEMENTS-COMPLETE.md`

Include:
- Files created/modified
- How to use new features
- Any remaining work (e.g., adding to more backfill scripts)
- Test results

---

**END OF CHAT 5 PROMPT**
