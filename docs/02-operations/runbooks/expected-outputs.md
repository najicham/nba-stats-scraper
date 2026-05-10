# Expected Outputs Runbook

**Audience:** on-call + data engineers. **Last updated:** 2026-05-09.

## What this is

`nba_orchestration.expected_outputs` is the pipeline's date-grid contract. One row per `(season, game_date, sport, phase, output_type)`. For every date in the season, every phase, every output, the table answers "what should exist?"

It replaces the old, phase-siloed completeness checks (`data-completeness-checker` 7d, `scraper-gap-backfiller` 14d, `daily-health-check` today/yesterday) with a single source of truth that works at any historical depth.

## Status enum

| Status | Meaning |
|---|---|
| `EXPECTED` | Planner created the row; reconciler hasn't seen actuals yet OR the row is past expected_by but not yet at the FAILED cap. |
| `RUNNING` | Reconciler observed in-progress write (rare — reconciler typically sees terminal state). |
| `COMPLETE` | Actual partition / file present with row_count > 0. The healthy state. |
| `EMPTY_OK` | Actual is empty but legitimately so — `halt_state.halt_active=true` OR no games on schedule for that date. |
| `FAILED` | gap_detector exhausted MAX_BACKFILL_ATTEMPTS (3). Permanent loss documented. |
| `DEGRADED` | Actuals present but failed validation (low row count, content guard tripped). |

## Quick check from the command line

`bin/validate-season.sh` answers the user-facing question "is every past date of the season processed?" in <30 seconds:

```bash
./bin/validate-season.sh                                # NBA + MLB, season-to-date
./bin/validate-season.sh nba                            # NBA only
./bin/validate-season.sh nba 2026-04-01 2026-04-30      # explicit range
```

It prints (1) coverage % per phase, (2) the 20 oldest unresolved gaps, (3) dates with zero healthy outputs, and writes per-row gap detail to `/tmp/season-gaps.csv`. This is the canonical interactive answer to the recurring "did this date process?" question.

## Common queries

### What's missing right now?

```sql
SELECT * FROM `nba-props-platform.nba_orchestration.expected_outputs_gaps`
ORDER BY hours_overdue DESC LIMIT 50
```

This view encodes the canonical "what's overdue" question. Returns `EXPECTED`, `FAILED`, and `DEGRADED` rows whose `expected_by < NOW()`.

### Coverage % per date per phase

```sql
SELECT * FROM `nba-props-platform.nba_orchestration.expected_outputs_coverage`
WHERE game_date >= CURRENT_DATE() - 14
ORDER BY game_date DESC, phase
```

Powers the `nba-pipeline-health` Cloud Monitoring dashboard.

### Show all outputs for a specific date

```sql
SELECT phase, output_type, status, row_count, last_error, attempts
FROM `nba-props-platform.nba_orchestration.expected_outputs`
WHERE sport = 'nba' AND game_date = '2025-12-15'
ORDER BY phase, output_type
```

### Drill into a single phase

```sql
SELECT game_date, output_type, status, row_count
FROM `nba-props-platform.nba_orchestration.expected_outputs`
WHERE sport = 'nba' AND phase = 'phase4_precompute'
  AND game_date >= '2025-10-21'
ORDER BY game_date DESC, output_type
```

## Adding a new expected output

1. Edit `orchestration/cloud_functions/expected_outputs_planner/main.py` `OUTPUT_TYPE_REGISTRY`. Add a tuple `(output_type, partition_template, sla_hours)` under the right `(sport, phase)`.
2. The next nightly planner run materializes EXPECTED rows for all dates in the lookback + lookahead window.
3. The next reconciler run starts checking actuals.

If you want to backfill historical EXPECTED rows for the new output:

```bash
# Local invocation against today's data
CF_URL=$(gcloud functions describe expected-outputs-planner --gen2 \
  --region=us-west2 --format='value(serviceConfig.uri)')

curl -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences=${CF_URL}/)" \
  "${CF_URL}/?history_seed_date=2025-10-01&lookahead_days=14"
```

The MERGE is idempotent — re-runs don't duplicate or overwrite existing terminal-status rows.

## Seeing what gap_detector is doing

```bash
gcloud functions logs read gap-detector --gen2 --region=us-west2 --limit=20
```

Each run logs `eligible_rows`, `published`, `failed_marked`, `skipped_at_cap`. Pub/Sub messages go to `projects/nba-props-platform/topics/nba-backfill-trigger`.

## Why is a date `EMPTY_OK`?

Two legitimate causes:
1. **No games on schedule.** Most weekday off-days for either sport.
2. **Halt active.** `halt_state.halt_active=true` for that date. Reconciler reads halt_state; if halted, zero-row outputs are correctly empty rather than missing.

The reconciler distinguishes these from genuine gaps:
- `row_count == 0 + halt_active=true` → EMPTY_OK
- `row_count == 0 + games scheduled` → EXPECTED (will become DEGRADED at attempts ≥ 3)

## Why is a date FAILED?

`gap_detector` published 3 backfill messages, the scraper either kept failing or the data is permanently unavailable (e.g. paid Odds API historical we don't have a license for). The row stays FAILED until manually overridden — it documents the loss.

To override (e.g. you've manually re-run a scraper that succeeded):

```sql
UPDATE `nba-props-platform.nba_orchestration.expected_outputs`
SET status = 'EXPECTED',
    attempts = 0,
    last_error = NULL,
    updated_at = CURRENT_TIMESTAMP(),
    source = 'manual_reset'
WHERE sport = 'nba'
  AND game_date = '2025-12-15'
  AND phase = 'phase2_raw'
  AND output_type = 'nbac_play_by_play'
```

The next reconciler run will re-check the actual.
