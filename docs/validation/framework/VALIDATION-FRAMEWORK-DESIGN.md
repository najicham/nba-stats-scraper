# Improved Validation Framework Design
**Date**: 2026-01-05
**Purpose**: Prevent missing tables and incomplete backfills
**Based on**: Phase 3 table gap lessons learned

---

## Executive Summary

We missed 3 of 5 Phase 3 tables (team_defense_game_summary, upcoming_player_game_context, upcoming_team_game_context) because we lacked:
1. **Pre-flight validation** - No comprehensive check before starting
2. **Exhaustive checklists** - No definitive list of all required tables
3. **Automatic validation gates** - No fail-fast on incomplete dependencies
4. **Continuous monitoring** - No alerting when tables degrade

This framework fixes all four problems with production-ready tooling.

---

## 1. Pre-Flight Validation Suite

### Purpose
**Run BEFORE any backfill to validate:**
- All prerequisites are met
- Current state of all tables
- What actually needs backfilling
- Estimated runtime and resource requirements

### Design: `bin/backfill/preflight_comprehensive.py`

```python
#!/usr/bin/env python3
"""
Comprehensive Pre-Flight Validation
Validates entire pipeline state before backfill execution.

Usage:
    # Validate readiness for Phase 4 backfill
    python bin/backfill/preflight_comprehensive.py \
        --target-phase 4 \
        --start-date 2021-10-19 \
        --end-date 2025-06-22

    # Strict mode - fail on any warnings
    python bin/backfill/preflight_comprehensive.py \
        --target-phase 4 \
        --start-date 2021-10-19 \
        --end-date 2025-06-22 \
        --strict

    # JSON output for automation
    python bin/backfill/preflight_comprehensive.py \
        --target-phase 4 \
        --start-date 2021-10-19 \
        --end-date 2025-06-22 \
        --json > preflight_results.json
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import date
import sys


@dataclass
class PreFlightResult:
    """Results of pre-flight validation."""
    phase: int
    check_name: str
    status: str  # 'PASS', 'WARN', 'FAIL'
    message: str
    details: Optional[Dict] = None
    blocking: bool = False  # True if FAIL should block execution


class PreFlightValidator:
    """Comprehensive pre-flight validator for backfill operations."""

    PHASE_DEPENDENCIES = {
        3: [],  # Phase 3 depends on Phase 2 (raw data)
        4: [3],  # Phase 4 depends on Phase 3
        5: [4],  # Phase 5 depends on Phase 4
    }

    PHASE_3_TABLES = [
        'player_game_summary',
        'team_defense_game_summary',  # CRITICAL - was missed!
        'team_offense_game_summary',
        'upcoming_player_game_context',  # CRITICAL - was missed!
        'upcoming_team_game_context',  # CRITICAL - was missed!
    ]

    PHASE_4_TABLES = [
        'player_composite_factors',
        'team_defense_zone_analysis',
        'player_shot_zone_analysis',
        'player_daily_cache',
        'ml_feature_store_v2',
    ]

    def __init__(self, target_phase: int, start_date: date, end_date: date):
        self.target_phase = target_phase
        self.start_date = start_date
        self.end_date = end_date
        self.results: List[PreFlightResult] = []
        self.client = bigquery.Client()

    def run_all_checks(self) -> bool:
        """
        Run all pre-flight checks.

        Returns:
            True if safe to proceed, False if critical issues found
        """
        print("=" * 80)
        print(" COMPREHENSIVE PRE-FLIGHT VALIDATION")
        print("=" * 80)
        print(f"Target Phase: {self.target_phase}")
        print(f"Date Range: {self.start_date} to {self.end_date}")
        print()

        # 1. Check all prerequisite phases are complete
        self._check_prerequisite_phases()

        # 2. Check current state of target phase
        self._check_current_state()

        # 3. Identify what needs backfilling
        self._identify_gaps()

        # 4. Validate data quality of existing data
        self._validate_existing_quality()

        # 5. Check for conflicts (running processes, duplicates)
        self._check_conflicts()

        # 6. Estimate resource requirements
        self._estimate_resources()

        # 7. Verify environment prerequisites
        self._check_environment()

        # Print results
        self._print_results()

        # Determine if safe to proceed
        return self._is_safe_to_proceed()

    def _check_prerequisite_phases(self):
        """Check all prerequisite phases are complete."""
        print("\n[CHECK 1] Prerequisite Phases")
        print("-" * 80)

        prerequisites = self.PHASE_DEPENDENCIES.get(self.target_phase, [])

        if not prerequisites:
            self.results.append(PreFlightResult(
                phase=self.target_phase,
                check_name="prerequisites",
                status="PASS",
                message="No prerequisites required",
            ))
            return

        for prereq_phase in prerequisites:
            if prereq_phase == 3:
                self._check_phase3_complete()
            elif prereq_phase == 4:
                self._check_phase4_complete()

    def _check_phase3_complete(self):
        """Check ALL 5 Phase 3 tables are complete."""
        print("  Checking Phase 3 tables...")

        # Get expected game dates
        expected_dates = self._get_expected_game_dates()
        non_bootstrap_dates = self._filter_bootstrap_dates(expected_dates)

        incomplete_tables = []

        for table_name in self.PHASE_3_TABLES:
            coverage = self._get_table_coverage(
                f"nba_analytics.{table_name}",
                "game_date",
                non_bootstrap_dates
            )

            print(f"    {table_name}: {coverage:.1f}%")

            if coverage < 95.0:
                incomplete_tables.append(f"{table_name} ({coverage:.1f}%)")

        if incomplete_tables:
            self.results.append(PreFlightResult(
                phase=3,
                check_name="phase3_completeness",
                status="FAIL",
                message=f"Phase 3 has {len(incomplete_tables)} incomplete tables",
                details={'incomplete_tables': incomplete_tables},
                blocking=True
            ))
        else:
            self.results.append(PreFlightResult(
                phase=3,
                check_name="phase3_completeness",
                status="PASS",
                message=f"All {len(self.PHASE_3_TABLES)} Phase 3 tables >95% complete"
            ))

    def _get_table_coverage(self, table: str, date_col: str,
                           expected_dates: set) -> float:
        """Get coverage percentage for a table."""
        query = f"""
        SELECT COUNT(DISTINCT {date_col}) as actual_dates
        FROM `nba-props-platform.{table}`
        WHERE {date_col} >= @start_date
          AND {date_col} <= @end_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", self.start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", self.end_date),
            ]
        )

        try:
            result = self.client.query(query, job_config=job_config).result()
            actual_dates = next(iter(result)).actual_dates

            if len(expected_dates) == 0:
                return 0.0

            return (actual_dates / len(expected_dates)) * 100.0
        except Exception as e:
            print(f"    ERROR querying {table}: {e}")
            return 0.0

    # ... Additional methods for other checks ...

    def _print_results(self):
        """Print validation results in human-readable format."""
        print("\n" + "=" * 80)
        print(" VALIDATION RESULTS")
        print("=" * 80)

        passed = [r for r in self.results if r.status == "PASS"]
        warnings = [r for r in self.results if r.status == "WARN"]
        failures = [r for r in self.results if r.status == "FAIL"]

        if passed:
            print(f"\n✅ PASSED ({len(passed)} checks)")
            for result in passed:
                print(f"   {result.check_name}: {result.message}")

        if warnings:
            print(f"\n⚠️  WARNINGS ({len(warnings)} checks)")
            for result in warnings:
                print(f"   {result.check_name}: {result.message}")
                if result.details:
                    for key, value in result.details.items():
                        print(f"      {key}: {value}")

        if failures:
            print(f"\n❌ FAILURES ({len(failures)} checks)")
            for result in failures:
                print(f"   {result.check_name}: {result.message}")
                if result.details:
                    for key, value in result.details.items():
                        print(f"      {key}: {value}")

    def _is_safe_to_proceed(self) -> bool:
        """Determine if safe to proceed with backfill."""
        blocking_failures = [r for r in self.results
                            if r.status == "FAIL" and r.blocking]

        if blocking_failures:
            print("\n" + "=" * 80)
            print("❌ PRE-FLIGHT FAILED - DO NOT PROCEED")
            print("=" * 80)
            print(f"\nFound {len(blocking_failures)} blocking issue(s):")
            for failure in blocking_failures:
                print(f"  - {failure.message}")
            print("\nFix these issues before running backfill.")
            return False

        warnings = [r for r in self.results if r.status == "WARN"]
        if warnings:
            print("\n" + "=" * 80)
            print("⚠️  PRE-FLIGHT PASSED WITH WARNINGS")
            print("=" * 80)
            print("\nReview warnings above. Proceed with caution.")
        else:
            print("\n" + "=" * 80)
            print("✅ PRE-FLIGHT PASSED - SAFE TO PROCEED")
            print("=" * 80)

        return True


def main():
    parser = argparse.ArgumentParser(
        description='Comprehensive pre-flight validation for backfill operations'
    )
    parser.add_argument('--target-phase', type=int, required=True,
                       choices=[3, 4, 5],
                       help='Phase to validate for (3=Analytics, 4=Precompute, 5=Predictions)')
    parser.add_argument('--start-date', type=str, required=True,
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True,
                       help='End date (YYYY-MM-DD)')
    parser.add_argument('--strict', action='store_true',
                       help='Fail on warnings')
    parser.add_argument('--json', action='store_true',
                       help='Output JSON instead of human-readable')

    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

    validator = PreFlightValidator(args.target_phase, start_date, end_date)
    safe_to_proceed = validator.run_all_checks()

    if args.strict:
        warnings = [r for r in validator.results if r.status == "WARN"]
        if warnings:
            print("\nSTRICT MODE: Failing due to warnings")
            sys.exit(1)

    sys.exit(0 if safe_to_proceed else 1)


if __name__ == "__main__":
    main()
```

### Key Features

1. **Exhaustive table checking** - Hardcoded list of ALL tables per phase
2. **Prerequisite validation** - Verifies all upstream phases are complete
3. **Gap identification** - Shows exactly what dates need backfilling
4. **Conflict detection** - Checks for duplicates, running processes
5. **Resource estimation** - Calculates expected runtime and data volume
6. **Blocking vs non-blocking** - Critical failures block execution
7. **JSON output** - Machine-readable for automation

---

## 2. Post-Backfill Validation Suite

### Purpose
**Run AFTER backfills to confirm:**
- Data was written successfully
- Coverage meets requirements
- Data quality is acceptable
- Dependencies are satisfied for next phase

### Design: `bin/backfill/postflight_comprehensive.py`

```python
#!/usr/bin/env python3
"""
Comprehensive Post-Flight Validation
Validates data quality and completeness after backfill.

Usage:
    # Validate Phase 3 backfill results
    python bin/backfill/postflight_comprehensive.py \
        --phase 3 \
        --start-date 2021-10-19 \
        --end-date 2025-06-22

    # Generate detailed report
    python bin/backfill/postflight_comprehensive.py \
        --phase 3 \
        --start-date 2021-10-19 \
        --end-date 2025-06-22 \
        --report backfill_report.json
"""

from dataclasses import dataclass
from typing import Dict, List
from datetime import date
import json


@dataclass
class PostFlightResult:
    """Results of post-flight validation."""
    table_name: str
    status: str  # 'COMPLETE', 'PARTIAL', 'INCOMPLETE'
    coverage_pct: float
    record_count: int
    expected_count: int
    quality_score: Optional[float] = None
    issues: List[str] = None


class PostFlightValidator:
    """Comprehensive post-flight validator."""

    # Same table definitions as PreFlightValidator
    PHASE_3_TABLES = [
        'player_game_summary',
        'team_defense_game_summary',
        'team_offense_game_summary',
        'upcoming_player_game_context',
        'upcoming_team_game_context',
    ]

    QUALITY_THRESHOLDS = {
        'coverage_pct': 95.0,
        'min_production_ready_pct': 80.0,
        'minutes_played_null_pct_max': 10.0,
        'usage_rate_null_pct_max': 55.0,  # Accounts for pre-2024 data
    }

    def __init__(self, phase: int, start_date: date, end_date: date):
        self.phase = phase
        self.start_date = start_date
        self.end_date = end_date
        self.results: List[PostFlightResult] = []
        self.client = bigquery.Client()

    def run_all_checks(self) -> bool:
        """
        Run all post-flight validation checks.

        Returns:
            True if backfill successful, False if issues found
        """
        print("=" * 80)
        print(" POST-FLIGHT VALIDATION")
        print("=" * 80)
        print(f"Phase: {self.phase}")
        print(f"Date Range: {self.start_date} to {self.end_date}")
        print()

        # Get table list for phase
        tables = self._get_phase_tables()

        # Validate each table
        for table_name in tables:
            print(f"\n[VALIDATING] {table_name}")
            print("-" * 80)
            result = self._validate_table(table_name)
            self.results.append(result)

        # Print summary
        self._print_summary()

        # Generate report if requested
        return self._all_complete()

    def _validate_table(self, table_name: str) -> PostFlightResult:
        """Validate a single table."""
        # Get coverage
        coverage = self._get_coverage(table_name)

        # Get record counts
        actual, expected = self._get_record_counts(table_name)

        # Calculate quality score
        quality = self._calculate_quality_score(table_name)

        # Check for common issues
        issues = self._check_data_quality(table_name)

        # Determine status
        if coverage >= self.QUALITY_THRESHOLDS['coverage_pct']:
            status = 'COMPLETE'
        elif coverage >= 50.0:
            status = 'PARTIAL'
        else:
            status = 'INCOMPLETE'

        return PostFlightResult(
            table_name=table_name,
            status=status,
            coverage_pct=coverage,
            record_count=actual,
            expected_count=expected,
            quality_score=quality,
            issues=issues
        )

    def _check_data_quality(self, table_name: str) -> List[str]:
        """Check for common data quality issues."""
        issues = []

        # Check for NULL critical fields
        if 'player' in table_name:
            null_pct = self._get_null_percentage(table_name, 'minutes_played')
            if null_pct > self.QUALITY_THRESHOLDS['minutes_played_null_pct_max']:
                issues.append(f"High NULL rate for minutes_played: {null_pct:.1f}%")

            usage_null_pct = self._get_null_percentage(table_name, 'usage_rate')
            if usage_null_pct > self.QUALITY_THRESHOLDS['usage_rate_null_pct_max']:
                issues.append(f"High NULL rate for usage_rate: {usage_null_pct:.1f}%")

        # Check for duplicates
        dup_count = self._check_duplicates(table_name)
        if dup_count > 0:
            issues.append(f"Found {dup_count} duplicate records")

        # Check for future dates
        future_count = self._check_future_dates(table_name)
        if future_count > 0:
            issues.append(f"Found {future_count} records with future dates")

        return issues

    def _print_summary(self):
        """Print validation summary."""
        print("\n" + "=" * 80)
        print(" VALIDATION SUMMARY")
        print("=" * 80)

        complete = [r for r in self.results if r.status == 'COMPLETE']
        partial = [r for r in self.results if r.status == 'PARTIAL']
        incomplete = [r for r in self.results if r.status == 'INCOMPLETE']

        print(f"\n✅ Complete: {len(complete)}/{len(self.results)} tables")
        for result in complete:
            print(f"   {result.table_name}: {result.coverage_pct:.1f}% coverage")

        if partial:
            print(f"\n⚠️  Partial: {len(partial)} tables")
            for result in partial:
                print(f"   {result.table_name}: {result.coverage_pct:.1f}% coverage")

        if incomplete:
            print(f"\n❌ Incomplete: {len(incomplete)} tables")
            for result in incomplete:
                print(f"   {result.table_name}: {result.coverage_pct:.1f}% coverage")

        # Print issues
        issues_found = [r for r in self.results if r.issues]
        if issues_found:
            print(f"\n⚠️  Issues Found:")
            for result in issues_found:
                print(f"\n   {result.table_name}:")
                for issue in result.issues:
                    print(f"     - {issue}")

    def _all_complete(self) -> bool:
        """Check if all tables are complete."""
        incomplete = [r for r in self.results if r.status != 'COMPLETE']
        return len(incomplete) == 0


def main():
    parser = argparse.ArgumentParser(
        description='Comprehensive post-flight validation after backfill'
    )
    parser.add_argument('--phase', type=int, required=True,
                       choices=[3, 4, 5],
                       help='Phase to validate (3=Analytics, 4=Precompute, 5=Predictions)')
    parser.add_argument('--start-date', type=str, required=True,
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True,
                       help='End date (YYYY-MM-DD)')
    parser.add_argument('--report', type=str,
                       help='Output report to JSON file')

    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

    validator = PostFlightValidator(args.phase, start_date, end_date)
    success = validator.run_all_checks()

    # Save report if requested
    if args.report:
        report_data = {
            'phase': args.phase,
            'date_range': {
                'start': args.start_date,
                'end': args.end_date
            },
            'results': [
                {
                    'table': r.table_name,
                    'status': r.status,
                    'coverage_pct': r.coverage_pct,
                    'record_count': r.record_count,
                    'issues': r.issues or []
                }
                for r in validator.results
            ],
            'overall_success': success
        }

        with open(args.report, 'w') as f:
            json.dump(report_data, f, indent=2)

        print(f"\nReport saved to: {args.report}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
```

### Key Features

1. **Data quality checks** - NULL rates, duplicates, future dates
2. **Coverage validation** - Ensures >95% coverage
3. **Issue reporting** - Detailed list of problems found
4. **JSON reports** - Machine-readable output for tracking
5. **Configurable thresholds** - Adjust per table/phase requirements

---

## 3. Integration with Orchestrator

### Design: Enhanced Orchestrator Template

Update `/home/naji/code/nba-stats-scraper/scripts/backfill_orchestrator.sh`:

```bash
#!/bin/bash
# Enhanced Backfill Orchestrator with Validation Gates
#
# New Features:
# - Pre-flight validation before starting
# - Post-flight validation after each phase
# - Automatic rollback on validation failures
# - Checkpoint-based resume capability

set -e

# ... existing configuration ...

# =============================================================================
# PRE-FLIGHT VALIDATION GATE
# =============================================================================

log_section "PRE-FLIGHT VALIDATION"

log_info "Running comprehensive pre-flight checks..."

# Run pre-flight validation
if ! python3 bin/backfill/preflight_comprehensive.py \
    --target-phase 4 \
    --start-date "$PHASE4_START" \
    --end-date "$PHASE4_END" \
    --strict; then

    log_error "PRE-FLIGHT VALIDATION FAILED"
    log_error "Cannot proceed with backfill - fix issues above"
    exit 1
fi

log_success "PRE-FLIGHT VALIDATION PASSED"
echo ""

# =============================================================================
# PHASE 3: Run Backfill (existing code)
# =============================================================================

# ... existing Phase 3 backfill code ...

# =============================================================================
# POST-FLIGHT VALIDATION GATE (NEW)
# =============================================================================

log_section "POST-FLIGHT VALIDATION - PHASE 3"

log_info "Validating Phase 3 backfill results..."

# Run post-flight validation
if ! python3 bin/backfill/postflight_comprehensive.py \
    --phase 3 \
    --start-date "$PHASE3_START" \
    --end-date "$PHASE3_END" \
    --report "logs/phase3_validation_report.json"; then

    log_error "POST-FLIGHT VALIDATION FAILED"
    log_error "Phase 3 backfill incomplete - do NOT proceed to Phase 4"

    # Show which tables failed
    python3 -c "
import json
with open('logs/phase3_validation_report.json') as f:
    data = json.load(f)
    incomplete = [r for r in data['results'] if r['status'] != 'COMPLETE']
    if incomplete:
        print('\nIncomplete tables:')
        for r in incomplete:
            print(f\"  - {r['table']}: {r['coverage_pct']:.1f}% coverage\")
            for issue in r.get('issues', []):
                print(f\"    Issue: {issue}\")
    "

    exit 1
fi

log_success "POST-FLIGHT VALIDATION PASSED - Phase 3 complete"
echo ""

# =============================================================================
# PHASE 4: Run Backfill (only if Phase 3 validated)
# =============================================================================

log_section "PHASE 4: STARTING (Phase 3 validated)"

# ... Phase 4 backfill code ...
```

### Validation Checkpoints

```bash
# Checkpoint file structure
CHECKPOINT_FILE="/tmp/backfill_checkpoints/phase4_${START_DATE}_${END_DATE}.json"

# Save checkpoint after each phase
save_checkpoint() {
    local phase=$1
    local status=$2

    cat > "$CHECKPOINT_FILE" <<EOF
{
  "phase": $phase,
  "status": "$status",
  "timestamp": "$(date -Iseconds)",
  "start_date": "$START_DATE",
  "end_date": "$END_DATE",
  "validation_report": "logs/phase${phase}_validation_report.json"
}
EOF
}

# Resume from checkpoint
resume_from_checkpoint() {
    if [[ -f "$CHECKPOINT_FILE" ]]; then
        local last_phase=$(jq -r '.phase' "$CHECKPOINT_FILE")
        local last_status=$(jq -r '.status' "$CHECKPOINT_FILE")

        if [[ "$last_status" == "validated" ]]; then
            log_info "Resuming from Phase $last_phase (validated)"
            RESUME_PHASE=$((last_phase + 1))
        else
            log_warning "Last run failed at Phase $last_phase"
            log_info "Re-running from Phase $last_phase"
            RESUME_PHASE=$last_phase
        fi
    fi
}
```

---

## 4. Phase Completion Checklists

### Phase 3 Completion Checklist

File: `/home/naji/code/nba-stats-scraper/docs/validation-framework/PHASE3-COMPLETION-CHECKLIST.md`

```markdown
# Phase 3 Analytics - Completion Checklist

**Before declaring Phase 3 COMPLETE, verify ALL items below:**

## Required Tables (5/5 must be complete)

- [ ] **player_game_summary**
  - Coverage: ≥95% of game dates
  - Validation: `bin/backfill/verify_phase3_for_phase4.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD`
  - Critical fields: minutes_played, usage_rate, points, rebounds, assists

- [ ] **team_defense_game_summary**
  - Coverage: ≥95% of game dates
  - Critical fields: defensive_rating, opponent_fg_pct, turnovers_forced

- [ ] **team_offense_game_summary**
  - Coverage: ≥95% of game dates
  - Critical fields: team_pace, offensive_rating, points_scored

- [ ] **upcoming_player_game_context**
  - Coverage: ≥95% of game dates
  - Critical fields: has_prop_line, player_lookup, game_date

- [ ] **upcoming_team_game_context**
  - Coverage: ≥95% of game dates
  - Critical fields: spread, total, team_abbr

## Data Quality Checks

- [ ] **No duplicates in any table**
  ```sql
  -- Run for each table
  SELECT game_id, game_date, player_lookup, COUNT(*) as dup_count
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= 'START_DATE' AND game_date <= 'END_DATE'
  GROUP BY game_id, game_date, player_lookup
  HAVING COUNT(*) > 1
  LIMIT 10;
  -- Should return 0 rows
  ```

- [ ] **minutes_played NULL rate <10%**
  ```sql
  SELECT
    COUNTIF(minutes_played IS NULL) * 100.0 / COUNT(*) as null_pct
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= 'START_DATE' AND game_date <= 'END_DATE'
    AND points IS NOT NULL;  -- Exclude DNPs
  -- Should be <10%
  ```

- [ ] **usage_rate coverage ≥45%** (accounting for pre-2024 data)
  ```sql
  SELECT
    COUNTIF(usage_rate IS NOT NULL) * 100.0 / COUNT(*) as coverage_pct
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= 'START_DATE' AND game_date <= 'END_DATE'
    AND minutes_played > 0;
  -- Should be ≥45%
  ```

- [ ] **Quality score ≥75.0**
  ```sql
  SELECT AVG(quality_score) as avg_quality
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= 'START_DATE' AND game_date <= 'END_DATE';
  -- Should be ≥75.0
  ```

## Dependency Validation

- [ ] **Phase 4 can run successfully**
  ```bash
  # Test 1 sample date
  python bin/backfill/preflight_comprehensive.py \
    --target-phase 4 \
    --start-date 2024-01-15 \
    --end-date 2024-01-15
  # Should PASS
  ```

## Final Verification

- [ ] **Run comprehensive validation**
  ```bash
  python bin/backfill/postflight_comprehensive.py \
    --phase 3 \
    --start-date 2021-10-19 \
    --end-date 2025-06-22 \
    --report phase3_final_report.json
  ```

- [ ] **Review validation report**
  - All 5 tables show "COMPLETE"
  - No critical issues reported
  - Coverage ≥95% for all tables

## Sign-Off

Date: _______________
Validated by: _______________
Report: `phase3_final_report.json`

**Phase 3 is COMPLETE and ready for Phase 4**
```

### Phase 4 Completion Checklist

File: `/home/naji/code/nba-stats-scraper/docs/validation-framework/PHASE4-COMPLETION-CHECKLIST.md`

```markdown
# Phase 4 Precompute - Completion Checklist

**Before declaring Phase 4 COMPLETE, verify ALL items below:**

## Required Tables (5/5 must be complete)

- [ ] **player_composite_factors**
  - Coverage: ≥88% (accounts for 14-day bootstrap)
  - Critical fields: fatigue_factor, shot_zone_mismatch, pace_differential

- [ ] **team_defense_zone_analysis**
  - Coverage: ≥88%
  - Critical fields: rim_defense_rating, three_pt_defense_rating

- [ ] **player_shot_zone_analysis**
  - Coverage: ≥70% (only players with shot data)
  - Critical fields: rim_efficiency, three_pt_efficiency

- [ ] **player_daily_cache**
  - Coverage: ≥88%
  - Critical fields: l5_avg_points, l10_avg_points, season_avg_points

- [ ] **ml_feature_store_v2**
  - Coverage: ≥88%
  - All 21+ features populated
  - No NaN/Inf values in feature columns

## Bootstrap Period Validation

- [ ] **Bootstrap dates correctly excluded**
  ```sql
  -- First 14 days of each season should be excluded
  SELECT season_year, MIN(game_date) as first_date
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  GROUP BY season_year
  ORDER BY season_year;
  -- Each season should start ~14 days after season start
  ```

## Data Quality Checks

- [ ] **No duplicates**
  ```sql
  SELECT game_id, game_date, player_lookup, COUNT(*) as dup_count
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= 'START_DATE' AND game_date <= 'END_DATE'
  GROUP BY game_id, game_date, player_lookup
  HAVING COUNT(*) > 1
  LIMIT 10;
  ```

- [ ] **No NULL critical features**
  ```sql
  SELECT
    COUNTIF(fatigue_factor IS NULL) * 100.0 / COUNT(*) as fatigue_null_pct,
    COUNTIF(shot_zone_mismatch IS NULL) * 100.0 / COUNT(*) as zone_null_pct,
    COUNTIF(pace_differential IS NULL) * 100.0 / COUNT(*) as pace_null_pct
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= 'START_DATE' AND game_date <= 'END_DATE';
  -- All should be <5%
  ```

## ML Training Readiness

- [ ] **ML feature store validation**
  ```bash
  python bin/backfill/validate_ml_ready.py \
    --start-date 2021-10-19 \
    --end-date 2025-06-22
  # Should report "ML TRAINING READY"
  ```

- [ ] **Sample training run succeeds**
  ```bash
  # Test with 100 samples
  python ml/train_real_xgboost.py --sample-size 100
  # Should complete without errors
  ```

## Final Verification

- [ ] **Run comprehensive validation**
  ```bash
  python bin/backfill/postflight_comprehensive.py \
    --phase 4 \
    --start-date 2021-10-19 \
    --end-date 2025-06-22 \
    --report phase4_final_report.json
  ```

## Sign-Off

Date: _______________
Validated by: _______________
Report: `phase4_final_report.json`

**Phase 4 is COMPLETE and ready for ML Training**
```

---

## 5. Continuous Validation

### Daily Monitoring Script

File: `/home/naji/code/nba-stats-scraper/scripts/monitoring/daily_validation.py`

```python
#!/usr/bin/env python3
"""
Daily Validation Monitor
Runs every morning to check for pipeline degradation.

Schedule with cron:
    0 8 * * * /path/to/daily_validation.py --alert-on-failure

What it checks:
- Phase 3 tables coverage hasn't dropped
- Phase 4 tables coverage hasn't dropped
- No duplicates introduced
- Recent data quality maintained
"""

from datetime import date, timedelta
from typing import Dict, List
import smtplib
from email.message import EmailMessage


class DailyValidator:
    """Daily validation monitor for continuous health checking."""

    COVERAGE_THRESHOLDS = {
        'phase3': {
            'player_game_summary': 95.0,
            'team_defense_game_summary': 95.0,
            'team_offense_game_summary': 95.0,
            'upcoming_player_game_context': 95.0,
            'upcoming_team_game_context': 95.0,
        },
        'phase4': {
            'player_composite_factors': 88.0,
            'team_defense_zone_analysis': 88.0,
            'player_shot_zone_analysis': 70.0,
            'player_daily_cache': 88.0,
            'ml_feature_store_v2': 88.0,
        }
    }

    def __init__(self):
        self.client = bigquery.Client()
        self.issues: List[str] = []

        # Check last 30 days
        self.end_date = date.today() - timedelta(days=1)  # Yesterday
        self.start_date = self.end_date - timedelta(days=30)

    def run_daily_checks(self):
        """Run all daily validation checks."""
        print("=" * 80)
        print(" DAILY VALIDATION MONITOR")
        print("=" * 80)
        print(f"Date Range: {self.start_date} to {self.end_date} (last 30 days)")
        print()

        # Check Phase 3 coverage
        self._check_phase_coverage(3)

        # Check Phase 4 coverage
        self._check_phase_coverage(4)

        # Check for new duplicates
        self._check_new_duplicates()

        # Check recent data quality
        self._check_recent_quality()

        # Report results
        self._report_results()

    def _check_phase_coverage(self, phase: int):
        """Check coverage for a phase hasn't degraded."""
        print(f"\n[CHECK] Phase {phase} Coverage")
        print("-" * 80)

        thresholds = self.COVERAGE_THRESHOLDS[f'phase{phase}']

        for table_name, min_coverage in thresholds.items():
            dataset = 'nba_analytics' if phase == 3 else 'nba_precompute'
            actual_coverage = self._get_coverage(dataset, table_name)

            status = "✅" if actual_coverage >= min_coverage else "❌"
            print(f"{status} {table_name}: {actual_coverage:.1f}% (threshold: {min_coverage}%)")

            if actual_coverage < min_coverage:
                self.issues.append(
                    f"Phase {phase} table {table_name} coverage dropped to "
                    f"{actual_coverage:.1f}% (below {min_coverage}%)"
                )

    def _get_coverage(self, dataset: str, table: str) -> float:
        """Get coverage for last 30 days."""
        # Get expected dates
        expected_query = """
        SELECT COUNT(DISTINCT game_date) as expected
        FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
        WHERE game_date >= @start_date
          AND game_date <= @end_date
        """

        # Get actual dates
        actual_query = f"""
        SELECT COUNT(DISTINCT game_date) as actual
        FROM `nba-props-platform.{dataset}.{table}`
        WHERE game_date >= @start_date
          AND game_date <= @end_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", self.start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", self.end_date),
            ]
        )

        try:
            expected = next(iter(self.client.query(expected_query, job_config=job_config).result())).expected
            actual = next(iter(self.client.query(actual_query, job_config=job_config).result())).actual

            if expected == 0:
                return 0.0

            return (actual / expected) * 100.0
        except Exception as e:
            print(f"  ERROR: {e}")
            return 0.0

    def _report_results(self):
        """Report validation results and send alerts if needed."""
        print("\n" + "=" * 80)
        print(" VALIDATION RESULTS")
        print("=" * 80)

        if not self.issues:
            print("\n✅ ALL CHECKS PASSED")
            print("Pipeline health is good for last 30 days")
        else:
            print(f"\n❌ FOUND {len(self.issues)} ISSUE(S)")
            for issue in self.issues:
                print(f"  - {issue}")

            # Send alert email
            self._send_alert_email()

    def _send_alert_email(self):
        """Send alert email when issues found."""
        # Configure email settings
        msg = EmailMessage()
        msg['Subject'] = f'NBA Pipeline Alert: {len(self.issues)} issue(s) detected'
        msg['From'] = 'pipeline-monitor@nba-props-platform.com'
        msg['To'] = 'your-email@example.com'

        body = "Daily validation found the following issues:\n\n"
        for issue in self.issues:
            body += f"- {issue}\n"

        body += "\nPlease investigate and take corrective action.\n"
        body += f"\nValidation period: {self.start_date} to {self.end_date}"

        msg.set_content(body)

        # Send email (configure SMTP settings)
        # with smtplib.SMTP('smtp.gmail.com', 587) as server:
        #     server.starttls()
        #     server.login('user', 'password')
        #     server.send_message(msg)

        print(f"\n📧 Alert email would be sent to: {msg['To']}")


def main():
    parser = argparse.ArgumentParser(
        description='Daily validation monitor for pipeline health'
    )
    parser.add_argument('--alert-on-failure', action='store_true',
                       help='Send email alert if issues found')

    args = parser.parse_args()

    validator = DailyValidator()
    validator.run_daily_checks()

    # Exit with error code if issues found (for cron alerting)
    if args.alert_on_failure and validator.issues:
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### Weekly Coverage Report

File: `/home/naji/code/nba-stats-scraper/scripts/monitoring/weekly_coverage_report.py`

```python
#!/usr/bin/env python3
"""
Weekly Coverage Report
Generates comprehensive coverage report for all phases.

Schedule with cron:
    0 9 * * 1 /path/to/weekly_coverage_report.py --email --output reports/
"""

# ... Similar structure to daily_validation.py but:
# - Checks last 7 days instead of 30
# - Generates detailed HTML report
# - Includes trend charts (coverage over time)
# - Emails PDF summary to team
```

---

## 6. Validation Commands Reference

### Quick Reference Card

File: `/home/naji/code/nba-stats-scraper/docs/validation-framework/VALIDATION-COMMANDS.md`

```markdown
# Validation Commands - Quick Reference

## Pre-Flight Validation

**Before Phase 3 backfill:**
```bash
python bin/backfill/preflight_comprehensive.py \
  --target-phase 3 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22
```

**Before Phase 4 backfill:**
```bash
python bin/backfill/preflight_comprehensive.py \
  --target-phase 4 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --strict
```

## Post-Flight Validation

**After Phase 3 backfill:**
```bash
python bin/backfill/postflight_comprehensive.py \
  --phase 3 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --report logs/phase3_validation.json
```

**After Phase 4 backfill:**
```bash
python bin/backfill/postflight_comprehensive.py \
  --phase 4 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --report logs/phase4_validation.json
```

## Phase 3 Specific Validation

**Verify Phase 3 for Phase 4 readiness:**
```bash
python bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --verbose
```

**Check specific Phase 3 table:**
```sql
-- player_game_summary coverage
SELECT
  COUNT(DISTINCT game_date) as dates_with_data,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22';
```

## Phase 4 Specific Validation

**Check Phase 4 coverage:**
```bash
python scripts/validation/validate_backfill_features.py \
  --start-date 2021-10-19 \
  --end-date 2025-06-22
```

**Verify ML readiness:**
```bash
python bin/backfill/validate_ml_ready.py \
  --start-date 2021-10-19 \
  --end-date 2025-06-22
```

## Continuous Monitoring

**Daily validation (run at 8 AM):**
```bash
python scripts/monitoring/daily_validation.py --alert-on-failure
```

**Weekly coverage report (run Monday 9 AM):**
```bash
python scripts/monitoring/weekly_coverage_report.py \
  --email \
  --output reports/$(date +%Y-%m-%d)_coverage.pdf
```

## Data Quality Checks

**Check for duplicates in Phase 3:**
```sql
SELECT table_name, COUNT(*) as dup_count
FROM (
  SELECT 'player_game_summary' as table_name, game_id, game_date, player_lookup, COUNT(*) as cnt
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-19'
  GROUP BY game_id, game_date, player_lookup
  HAVING COUNT(*) > 1
)
GROUP BY table_name;
```

**Check NULL rates:**
```sql
SELECT
  'minutes_played' as field,
  COUNTIF(minutes_played IS NULL) * 100.0 / COUNT(*) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND points IS NOT NULL
UNION ALL
SELECT
  'usage_rate' as field,
  COUNTIF(usage_rate IS NULL) * 100.0 / COUNT(*) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND minutes_played > 0;
```

## Emergency Validation

**Quick health check (all phases):**
```bash
python scripts/validation/validate_pipeline_completeness.py \
  --start-date $(date -d '30 days ago' +%Y-%m-%d) \
  --end-date $(date +%Y-%m-%d) \
  --alert-on-gaps
```

**Full pipeline audit:**
```bash
python scripts/validation/full_pipeline_audit.py \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --output audit_report.html
```
```

---

## Implementation Plan

### Phase 1: Core Validators (Week 1)
1. Build `preflight_comprehensive.py` (2 days)
2. Build `postflight_comprehensive.py` (2 days)
3. Test on sample date ranges (1 day)

### Phase 2: Orchestrator Integration (Week 2)
1. Update `backfill_orchestrator.sh` (1 day)
2. Add validation gates (1 day)
3. Add checkpoint/resume logic (2 days)
4. End-to-end testing (1 day)

### Phase 3: Checklists & Documentation (Week 3)
1. Create Phase 3 checklist (1 day)
2. Create Phase 4 checklist (1 day)
3. Create Phase 5 checklist (1 day)
4. Validation commands reference (1 day)
5. User training/documentation (1 day)

### Phase 4: Continuous Monitoring (Week 4)
1. Build `daily_validation.py` (2 days)
2. Build `weekly_coverage_report.py` (2 days)
3. Set up cron schedules (1 day)

### Total Timeline: 4 weeks

---

## Success Metrics

After implementation, measure:

1. **Zero missed tables** - All required tables identified in checklists
2. **Fast failure** - Catch issues in pre-flight (minutes) vs post-backfill (hours)
3. **No duplicate backfills** - Validation prevents running when already complete
4. **Continuous health** - Daily monitoring catches degradation within 24 hours
5. **Confidence** - Team can declare "COMPLETE" with 100% certainty

---

## Next Steps

1. Review this design document
2. Prioritize which components to build first
3. Create implementation tickets
4. Start with Phase 1 (core validators)
5. Iterate based on feedback

---

**This framework ensures we NEVER miss tables again.**
