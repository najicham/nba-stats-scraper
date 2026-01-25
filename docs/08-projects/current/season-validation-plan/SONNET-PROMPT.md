# Sonnet Prompt: Season Validation Backfill Execution

Copy everything below the line to start a Sonnet chat:

---

## Task: Execute Season Validation Backfill

I need you to execute backfill operations to fix data gaps in my NBA stats pipeline for the 2025-26 season. Comprehensive planning has been completed and documented.

### Context

We ran validation scans and discovered:
- **Phase 6 (Grading) is only 45.9% complete** - This is the critical issue
- Phase 2 (BDL) is 96.2% complete (minor gaps)
- Phase 3 (Analytics) is 100% complete (no action needed)
- Phase 5 (Predictions) is 95.3% complete (no action needed)

The main problem: **Over half of our predictions have never been graded against actual results.**

### Documentation Location

All planning documentation is at:
```
/home/naji/code/nba-stats-scraper/docs/08-projects/current/season-validation-plan/
```

Key files to read:
- `SONNET-HANDOFF.md` - Quick handoff summary with commands
- `08-ACTUAL-STATE-SUMMARY.md` - Real validation data from scans
- `07-RESEARCH-FINDINGS.md` - Important schema corrections

### Your Tasks (In Priority Order)

#### Task 1: Grading Backfill (P0 - Critical)

First, verify the grading backfill script exists and check its usage:
```bash
ls -la backfill_jobs/grading/prediction_accuracy/
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --help
```

Then run grading backfill in two phases:

**Phase A: Early season with 0% grading (Nov 4 - Dec 15)**
```bash
source .venv/bin/activate
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-11-04 --end-date 2025-12-15
```

**Phase B: Recent period with low grading (Dec 16 - Jan 24)**
```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-12-16 --end-date 2026-01-24
```

#### Task 2: Verify Grading Improvement

After grading backfill:
```bash
python bin/validation/daily_data_completeness.py --days 90
```

Target: Grading coverage should improve from 45.9% to >80%

#### Task 3: BDL Boxscore Backfill (P1 - If Time Permits)

14 dates have minor BDL gaps (24 missing games total). Priority dates:
```bash
python bin/backfill/bdl_boxscores.py --date 2026-01-15  # missing 3 games
python bin/backfill/bdl_boxscores.py --date 2026-01-14  # missing 2 games
python bin/backfill/bdl_boxscores.py --date 2026-01-13  # missing 2 games
```

Note: Jan 24 shows as a gap but it's due to GSW@MIN postponement, not missing data.

### Important Notes

1. **Always activate venv first**: `source .venv/bin/activate`
2. **Grading is the priority** - BDL gaps are minor and don't block anything
3. **If a script fails**, check the error and read the relevant docs before retrying
4. **Checkpoint files** - Backfill scripts auto-resume from checkpoints
5. **Schema note**: `player_game_summary` uses `data_quality_tier` NOT `is_production_ready`

### Success Criteria

| Metric | Before | Target |
|--------|--------|--------|
| Grading coverage | 45.9% | >80% |
| Dates with 0% grading | 17 | 0 |
| BDL coverage | 96.2% | >98% |

### If You Encounter Issues

1. **Script not found**: Check the exact path in `backfill_jobs/` directory
2. **Permission errors**: May need to set `GOOGLE_APPLICATION_CREDENTIALS`
3. **BigQuery errors**: Check if table names match (some may be in different datasets)
4. **Timeout**: Scripts have checkpoints, just re-run to continue

Report back with:
- Commands you ran
- Any errors encountered
- Final validation results showing improvement

Good luck!
