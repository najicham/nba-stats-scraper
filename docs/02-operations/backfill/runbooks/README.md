# Backfill Runbooks

**Last Updated:** 2025-12-17

Step-by-step guides for specific backfill operations.

---

## Available Runbooks

| Runbook | Purpose | When to Use |
|---------|---------|-------------|
| [phase4-precompute-backfill.md](./phase4-precompute-backfill.md) | Phase 4 step-by-step execution | Running Phase 4 backfills |
| [phase4-dependencies.md](./phase4-dependencies.md) | Dependency diagrams, issue categories | Understanding Phase 4 architecture |
| [phase5b-prediction-grading-backfill.md](./phase5b-prediction-grading-backfill.md) | **Phase 5B prediction grading** | Grading predictions against results |
| [name-resolution.md](./name-resolution.md) | Player name resolution | Debugging name matching issues |
| [nbac-team-boxscore.md](./nbac-team-boxscore.md) | NBA.com team boxscore | Phase 2 raw data backfills |

### Phase 5B Note (December 2025)

**IMPORTANT:** The Phase 5B prediction grading infrastructure exists but tables are EMPTY.
Run the backfill to populate `prediction_accuracy` and `system_daily_performance`.

```bash
# Quick command to populate prediction grading data
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-10-21 --end-date 2025-12-17
```

See [phase5b-prediction-grading-backfill.md](./phase5b-prediction-grading-backfill.md) for full details.

---

## When to Use Runbooks vs Main Docs

| Need | Use |
|------|-----|
| Quick start / first backfill | [../quick-start.md](../quick-start.md) |
| Understanding backfill concepts | [../README.md](../README.md) |
| Comprehensive procedures | [../backfill-guide.md](../backfill-guide.md) |
| Step-by-step for specific task | **Runbooks (this folder)** |
| Troubleshooting gaps | [../README.md#troubleshooting](../README.md#troubleshooting) |

---

## Creating New Runbooks

When documenting a new backfill operation:

**File naming:** `{processor-name}.md` or `{phase}-{topic}.md`

**Required sections:**
1. Overview - What and why
2. Prerequisites - What must exist first
3. Steps - Exact commands
4. Validation - How to verify success
5. Troubleshooting - Common issues

---

**Parent:** [../README.md](../README.md) - Backfill Documentation Hub
