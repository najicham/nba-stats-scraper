# Halt-Mode Operations Runbook

**Audience:** on-call. **Last updated:** 2026-05-09 (pipeline-state-redesign Phase B).

## Overview

`nba_orchestration.halt_state` is the single source of truth for "is the system producing picks today?" One row per `(effective_date, sport)`. Every Phase 6 exporter reads from it via `BaseExporter.halt_envelope()`. When the row is missing or stale, exporters emit `halt_reason='unknown_state'`.

## How it gets set

`halt_state_writer` Cloud Function runs daily at 5 AM ET (scheduler `halt-state-writer-daily`). For each sport (NBA + MLB) it walks this decision tree and returns at the first match:

1. **Schedule presence** — any games in `nba_reference.nba_schedule` / `mlb_raw.mlb_schedule` within ±21 days of today? If not → `halt_reason='off_season'`.
2. **Calendar window** — is today within the sport's regular season + playoffs window (NBA Oct 1 – Jun 30; MLB Mar 1 – Nov 15)? If not → `halt_reason='off_season'`.
3. **Between rounds** — in-season but no games scheduled in the next 14 days (e.g. NBA between playoff rounds) → `halt_reason='between_rounds'`. Auto-clears when next round's schedule lands.
4. **NBA edge collapse** (Session 515) — 7d avg edge < 5.0 AND edge-5+ pick rate < 50% AND days_sampled ≥ 3 → `halt_reason='edge_collapse'`.
5. **NBA fleet blocked** — all enabled NBA models in `model_performance_daily` state='BLOCKED' → `halt_reason='fleet_blocked'`.
6. **Predictions inactive** — games scheduled but zero predictions in last 3 days → `halt_reason='predictions_inactive'`. Catches operator-paused schedulers, prediction worker crashes, and the season-restart cold-start state.

NBA can fall through 1 → 2 → 3 → 4 → 5 → 6. MLB only checks 1 + 2 + 3 today (no edge/fleet/predictions logic). Reserved-but-not-emitted: `tight_market` (when vegas_mae_7d < 4.5 — to be wired up).

## How to inspect today's halt state

```sql
SELECT * FROM `nba-props-platform.nba_orchestration.halt_state`
WHERE effective_date = CURRENT_DATE()
ORDER BY sport
```

Expected: 2 rows (one nba, one mlb) with `written_at` < 12 hours ago.

## How to inspect history

```sql
SELECT effective_date, sport, halt_active, halt_reason, halt_since
FROM `nba-props-platform.nba_orchestration.halt_state`
WHERE effective_date >= CURRENT_DATE() - 14
ORDER BY effective_date DESC, sport
```

`halt_since` is preserved across rows — if NBA halted on 2026-04-19 and stayed halted, every row from then on shows `halt_since='2026-04-19'`.

## Manual override

If the auto-halt logic gets it wrong (rare), write a row manually:

```sql
MERGE `nba-props-platform.nba_orchestration.halt_state` T
USING (
  SELECT
    CURRENT_DATE() AS effective_date,
    'nba' AS sport,
    TRUE AS halt_active,
    'manual' AS halt_reason,
    DATE '2026-05-09' AS halt_since,
    PARSE_JSON('{"reason": "operator override during incident"}') AS halt_metrics,
    'manual_override' AS source,
    CURRENT_TIMESTAMP() AS written_at,
    'on-call' AS actor
) S
ON T.effective_date = S.effective_date AND T.sport = S.sport
WHEN MATCHED THEN UPDATE SET
  halt_active = S.halt_active, halt_reason = S.halt_reason,
  halt_since = S.halt_since, halt_metrics = S.halt_metrics,
  source = S.source, written_at = S.written_at, actor = S.actor
WHEN NOT MATCHED THEN INSERT VALUES (...);
```

Set `actor` to your name + ticket so the audit trail makes sense.

The next halt_state_writer run will overwrite your manual row at 5 AM ET, so for sustained overrides set `actor='manual_override'` and skip the daily — the writer will detect that source and respect the manual entry (TODO: implement in writer; today, manual overrides last only until the next 5 AM run).

## Manually trigger the writer

```bash
CF_URL=$(gcloud functions describe halt-state-writer --gen2 \
  --region=us-west2 --project=nba-props-platform \
  --format='value(serviceConfig.uri)')

curl -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences=${CF_URL}/)" \
  "${CF_URL}/?sport=all"
```

Optional query params:
- `target_date=2026-05-09` — backfill for a specific date.
- `sport=nba` — single sport.
- `actor=on_call_<name>` — audit trail.

## What if halt_state is stale?

Symptom: alert `halt-state-stale` fires. `written_at` for today's row is > 36h ago.

Diagnosis:
1. Scheduler paused / failed: `gcloud scheduler jobs describe halt-state-writer-daily --location=us-west2 --project=nba-props-platform`. State should be `ENABLED`. `lastAttemptTime` should be recent.
2. CF crashing: `gcloud functions logs read halt-state-writer --gen2 --region=us-west2 --limit=50`.
3. BQ unavailable: less likely — check Cloud Monitoring "BigQuery Query Errors".

Recovery: manual trigger above. Once the row updates, downstream exporters will pick up the correct state on their next run.

## Frontend impact when halt_state is unknown

`BaseExporter.halt_envelope` is fail-open. If it can't read halt_state, it returns:
```json
{"halt_active": false, "halt_reason": "unknown_state", "halt_since": null, ...}
```

Frontend treats `unknown_state` as "system uncertain — show available data; render a discreet warning."

This is intentional — we'd rather publish picks with an uncertainty label than block all publishing on a telemetry failure.

## Verifying that exporters see the right state

After a halt_state change, the next Phase 6 export run will pick it up. To verify:

```bash
# Latest signal-best-bets JSON for today
gcloud storage cat gs://nba-props-platform-api/v1/signal-best-bets/$(date +%Y-%m-%d).json | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print({k: d.get(k) for k in ['halt_active','halt_reason','halt_since']})"
```

Expected output reflects what's in halt_state.
