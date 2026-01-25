# Sonnet Handoff: Season Validation Execution

## Quick Context

We've completed planning for validating and backfilling the 2025-26 NBA season data. Real validation scans have been run, and the actual state is documented.

**Project Location:** `/docs/08-projects/current/season-validation-plan/`

## Current State (as of Jan 25, 2026)

| Phase | Coverage | Action Needed |
|-------|----------|---------------|
| Phase 2 (BDL) | 96.2% | Minor - 24 games missing across 14 dates |
| Phase 3 (Analytics) | 100% | None |
| Phase 5 (Predictions) | 95.3% | None |
| **Phase 6 (Grading)** | **45.9%** | **CRITICAL - Major backfill needed** |

## Priority Tasks (In Order)

### Task 1: Grading Backfill (P0 - Critical)

Over half of predictions have never been graded. This is the top priority.

**Step 1A: Early season (Nov 4 - Dec 15) - 0% grading**
```bash
source .venv/bin/activate
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-11-04 --end-date 2025-12-15
```

**Step 1B: Recent period (Dec 16 - Jan 24) - Low grading**
```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-12-16 --end-date 2026-01-24
```

**Verify after:**
```bash
python bin/validation/daily_data_completeness.py --days 30
```

### Task 2: BDL Boxscore Backfill (P1 - High)

14 dates are missing some games (24 total missing):

```bash
# High priority dates (recent, more missing)
python bin/backfill/bdl_boxscores.py --date 2026-01-15  # missing 3
python bin/backfill/bdl_boxscores.py --date 2026-01-14  # missing 2
python bin/backfill/bdl_boxscores.py --date 2026-01-13  # missing 2
python bin/backfill/bdl_boxscores.py --date 2026-01-12  # missing 2

# Lower priority (older, less missing)
python bin/backfill/bdl_boxscores.py --date 2026-01-07  # missing 2
python bin/backfill/bdl_boxscores.py --date 2026-01-05  # missing 2
python bin/backfill/bdl_boxscores.py --date 2026-01-03  # missing 2
python bin/backfill/bdl_boxscores.py --date 2026-01-02  # missing 2
python bin/backfill/bdl_boxscores.py --date 2026-01-01  # missing 2
```

Note: Jan 24 is missing due to GSW@MIN postponement (rescheduled to Jan 25), not a data issue.

### Task 3: Verification (P1)

After backfills complete:

```bash
# Quick verification
python bin/validation/daily_data_completeness.py --days 90

# Full season reconciliation
python bin/validation/season_reconciliation.py --full-season -v
```

### Task 4: Duplicate Prediction Cleanup (P2)

6,473 duplicate predictions exist. Check handoff docs for cleanup query:
- `/docs/09-handoff/2026-01-25-ADDITIONAL-RECOMMENDATIONS.md`

## Key Files for Reference

| File | Purpose |
|------|---------|
| `08-ACTUAL-STATE-SUMMARY.md` | Current state with real data |
| `07-RESEARCH-FINDINGS.md` | Schema corrections and thresholds |
| `05-EXECUTION-PLAN.md` | Full execution commands |
| `06-PRIORITIZATION-FRAMEWORK.md` | How to prioritize work |

## Important Notes

1. **Grading is the main issue** - Analytics (Phase 3) is actually 100% complete
2. **Window sizes**: L5, L10, L7d, L14d (NOT L20 as originally assumed)
3. **Production threshold**: 70% (not 90%)
4. **Bootstrap period**: First 14 days of season (Oct 22 - Nov 5)
5. **Postponed games**: GSW@MIN and CHI@MIA rescheduled - will show as anomalies

## Success Metrics

| Metric | Before | Target |
|--------|--------|--------|
| Grading coverage | 45.9% | >80% |
| Dates with 0% grading | 17 | 0 |
| BDL coverage | 96.2% | >98% |

## Questions?

Full planning documentation is in this directory. Key context:
- Recent Firestore outage (Jan 23-25) may have caused some issues
- Feature quality is degraded (all bronze tier) but recovering
- The `player_game_summary` table does NOT have `is_production_ready` column - use `data_quality_tier` instead
