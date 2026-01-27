# Quick Start - Validation Improvements

**Status**: ✅ LIVE (Opus Approved - Rating A)
**Last Updated**: 2026-01-27

Quick reference for using the new validation improvements.

---

## Daily Validation (Automatic)

**What**: Field completeness checks run automatically
**When**: Every time you run daily validation
**How**:
```bash
python scripts/validate_tonight_data.py
```

**Look for this section in output**:
```
✓ Field Completeness (2026-01-26):
   - 198 active players (out of 312 total)
   - field_goals_attempted: 99.5% for active players
   - free_throws_attempted: 99.0% for active players
   - three_pointers_attempted: 99.3% for active players
```

**Alert if**: Any percentage drops below 90% (CRITICAL)

---

## Historical Audit (Manual)

**What**: Audit data quality across date ranges
**When**: After backfills, processor changes, weekly audits
**How**:
```
/validate-historical 2026-01-15 2026-01-27
```

**What it shows**:
- Dates with CRITICAL issues (source fields NULL)
- Dates with WARNING issues (derived metrics NULL)
- Root cause diagnosis
- Recommended remediation steps

**Use cases**:
- After deploying processor changes
- After running backfills
- Investigating historical data issues
- Before ML model retraining

---

## Backfill Validation (Automatic)

**What**: Automatic quality checks after backfills
**When**: Every backfill completes
**How**: Already integrated - nothing to do!

**Where to see it**:
```bash
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2026-01-24 --end-date 2026-01-26
```

**Look for this section at the end**:
```
================================================================================
POST-BACKFILL VALIDATION
================================================================================
✅ Backfill validation PASSED: 13/13 dates OK
================================================================================
```

**If validation fails**:
- Review the validation report
- Check the issues listed
- Investigate root cause
- Re-run backfill after fix

---

## Programmatic Usage (Manual)

**What**: Use BackfillValidator directly in code
**When**: Custom scripts, notebooks, one-off investigations
**How**:
```python
from google.cloud import bigquery
from datetime import date
from shared.validation.backfill_validator import BackfillValidator

# Initialize
client = bigquery.Client()
validator = BackfillValidator(client, 'nba-props-platform')

# Validate specific dates
dates = [date(2026, 1, 15), date(2026, 1, 16), date(2026, 1, 17)]
report = validator.validate_dates(dates)

# Check results
if report.passed:
    print(f"✅ All {report.dates_passed} dates passed")
else:
    print(f"❌ {report.dates_failed} dates failed:")
    for issue in report.issues:
        print(f"  - {issue}")

# Log to logger
validator.log_report(report)

# Or print to stdout
validator.print_report(report, detailed=True)
```

---

## Thresholds

| Metric | Threshold | Severity |
|--------|-----------|----------|
| field_goals_attempted | ≥90% for active players | CRITICAL |
| free_throws_attempted | ≥90% for active players | CRITICAL |
| three_pointers_attempted | ≥85% for active players | WARNING |
| usage_rate (daily) | ≥90% for active players | CRITICAL |
| usage_rate (backfill) | ≥80% for active players | CRITICAL |

**Adjust if needed**: Modify class constants in `BackfillValidator`

---

## Common Scenarios

### Scenario 1: Daily Check Shows Low Coverage

**Symptom**: Field completeness check shows fg_attempts at 30%

**What to do**:
1. Check if processor ran successfully
2. Check if raw data exists (BDL tables)
3. Check processor SQL for NULL extraction
4. Re-run processor if needed

### Scenario 2: Backfill Validation Fails

**Symptom**: POST-BACKFILL VALIDATION shows failures

**What to do**:
1. Review the issues in the validation report
2. Check if it's a source field issue (CRITICAL) or derived metric issue (WARNING)
3. For source fields: Check processor SQL extraction
4. For derived metrics: Check join to team stats, calculation logic
5. Fix processor and re-run backfill

### Scenario 3: Historical Audit Finds Old Issues

**Symptom**: `/validate-historical` shows 9 CRITICAL dates

**What to do**:
1. Identify the date range and issue type
2. Check if processor was updated to fix the issue
3. If fixed: Re-run backfill for those dates
4. If not fixed: Fix processor first, then backfill
5. Verify fix with another `/validate-historical` run

---

## Troubleshooting

### Validation Hanging or Timing Out

**Cause**: BigQuery query taking too long
**Fix**: Check date range (limit to 30 days at a time for large audits)

### False Positives

**Cause**: Thresholds too strict for historical data
**Fix**: Adjust thresholds in `BackfillValidator` class constants

### Validation Not Running

**Cause**: Integration not in your backfill script
**Fix**: Add validation call (see integration example in player_game_summary backfill)

---

## Getting Help

**Documentation**:
- Full guide: `docs/09-handoff/2026-01-27-VALIDATION-IMPROVEMENTS-COMPLETE.md`
- Review doc: `docs/09-handoff/2026-01-27-VALIDATION-IMPROVEMENTS-FOR-REVIEW.md`
- Skill doc: `.claude/skills/validate-historical.md`

**Code**:
- BackfillValidator: `shared/validation/backfill_validator.py`
- Field checks: `scripts/validate_tonight_data.py` (method: `check_field_completeness`)
- Integration example: `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py`

**Questions**: Check inline docstrings - all code is well-documented

---

## Quick Commands Cheat Sheet

```bash
# Daily validation (includes field checks)
python scripts/validate_tonight_data.py

# Test backfill with validation
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2026-01-24 --end-date 2026-01-26

# Historical audit (via Claude skill)
/validate-historical 2026-01-15 2026-01-27

# Quick programmatic test
python -c "
from google.cloud import bigquery
from datetime import date
from shared.validation.backfill_validator import BackfillValidator

client = bigquery.Client()
validator = BackfillValidator(client, 'nba-props-platform')
result = validator.check_date_quality(date(2026, 1, 22))
print(f'Date: {result.date}')
print(f'Passed: {result.passed}')
print(f'FG: {result.fg_attempts_pct}%, Usage: {result.usage_rate_pct}%')
print(f'Issues: {result.issues}')
"
```

---

**Last Updated**: 2026-01-27
**Status**: ✅ LIVE & APPROVED (Opus Rating: A)
