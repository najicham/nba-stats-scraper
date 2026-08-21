# Halt-Mode Operations Runbook

**Audience:** on-call. **Last updated:** 2026-08-21 (halt_state became the publish gate).

## Overview — read this first, it changed

`nba_orchestration.halt_state` is the single source of truth for "is the system producing
picks today?" One row per `(effective_date, sport)`.

**Since 2026-08-21 it is also the GATE, not just a label.** An active NBA row makes
`signal_best_bets_exporter.generate_json` return zero picks at Step 0, before the
per-model pipelines even run. MLB has gated on it since 2026-05. Before that change the
NBA exporter only *stamped* the envelope onto the payload — a `manual` or `fleet_blocked`
row published a full slate under `halt_active: true`.

Two consequences on-call must internalise:

- **A missing row costs a slate.** `BaseExporter.halt_envelope` looks for today's row,
  then carries forward any row from the previous 3 days, and if it finds neither for a
  recent date it fails **CLOSED** (`halt_active=true`, `halt_reason='unknown_state'`).
  That is deliberate — publishing through a real halt is the worse error — but it means
  a dead writer is now a pick outage. See "Writer not writing" below.
- **`unknown_state` is not a legitimate zero.** The content guard deliberately does NOT
  excuse it, so a fail-closed export writes a `status="degraded"` sentinel and a CRITICAL
  log rather than quietly replacing a good file with an empty one.

## How it gets set

`halt_state_writer` runs daily at 5 AM ET (scheduler `halt-state-writer-daily`). For each
sport it walks this decision tree and stops at the first match:

1. **Schedule presence** — any games within ±21 days? If not → `off_season`.
2. **Calendar window** — NBA Oct 1 – Jun 30, MLB Mar 1 – Nov 15. Outside → `off_season`.
3. **Between rounds** — in-season, no games in the next 14 days → `between_rounds`.
   Auto-clears when the next round's schedule lands.
4. **NBA edge degeneracy guard** — `shared/config/edge_halt.py`. 7d median-across-models
   edge < **0.35** AND edge-3+ share < **0.30%** → `edge_collapse`. If the state cannot be
   resolved at all → `edge_state_unknown` (fail-closed). Details below.
5. **NBA/MLB fleet blocked** — all enabled models BLOCKED, with a 5-day
   fleet-in-transition grace → `fleet_blocked`.
6. **Predictions inactive** — games scheduled, zero predictions in 3 days, **and at least
   one past day in that window actually had games** → `predictions_inactive`.
7. **MLB pick drought** — predictions flowing but 2+ days of zero picks → `pick_drought`.
8. **Operator override** — an active row in `nba_orchestration.halt_overrides` → its
   reason (usually `manual`). Applied LAST and **add-only**: an override can force a halt
   but can never resume the system.

`tight_market` is a valid reason string but the tree never emits it; it is reachable only
through `halt_overrides`.

### The edge degeneracy guard (step 4)

**It is a pathology detector, not a market circuit breaker.** Read the module docstring in
`shared/config/edge_halt.py` before acting on it or changing any number — the thresholds
were deliberately loosened from the old 1.4 / 10%, which measured fleet composition rather
than the market. Behaviour on-call needs:

- **Basis:** per-model medians aggregated across models, restricted to model *families*
  with 7+ prediction-days. Keyed on family, not `system_id`, because the weekly retrainer
  mints a new train-stamped id every generation.
- **Release:** either condition recovering past a 10% band for 2 consecutive evaluable
  days, **or** the halt hitting its **14-day automatic lifetime**, whichever comes first.
- **After an auto-release the guard will not re-fire on the same episode.** It re-arms
  only after a sustained recovery. If the halt was real, that is your cue: write a
  `halt_overrides` row.
- **Dormancy is normal early season.** The basis is empty for roughly the first 7
  game-days, so the guard simply does not evaluate. `edge_halt_dormant` in `halt_metrics`
  and `models_7d` tell you whether it looked at anything.
- **Known blind spot:** this guard only catches edges collapsing toward zero. A frozen
  line feed or a constant-serving model produces *large* edges and reads as healthier.
  See the docstring's coverage note.

## Inspect today's state

```sql
SELECT * FROM `nba-props-platform.nba_orchestration.halt_state`
WHERE effective_date = CURRENT_DATE()
ORDER BY sport
```

Expected: 2 rows (nba, mlb), `written_at` < 12 hours ago. History:

```sql
SELECT effective_date, sport, halt_active, halt_reason, halt_since,
       JSON_VALUE(halt_metrics, '$.edge_halt_source')   AS edge_source,
       JSON_VALUE(halt_metrics, '$.edge_halt_models_7d') AS models_7d
FROM `nba-props-platform.nba_orchestration.halt_state`
WHERE effective_date >= CURRENT_DATE() - 14
ORDER BY effective_date DESC, sport
```

`halt_since` is preserved across rows: if NBA halted on 2026-04-19 and stayed halted,
every row from then on shows `halt_since='2026-04-19'`.

## Operator halt — `halt_overrides`, not a manual MERGE

**Do not hand-write rows into `halt_state`.** The writer overwrites them at 5 AM. The
implemented mechanism is `nba_orchestration.halt_overrides`:

```sql
INSERT INTO `nba-props-platform.nba_orchestration.halt_overrides`
  (sport, halt_reason, start_date, end_date, active, note, created_by, created_at)
VALUES ('nba', 'manual', CURRENT_DATE(), NULL, TRUE,
        '<ticket / one-line why>', '<your name>', CURRENT_TIMESTAMP());
```

`end_date = NULL` means open-ended. To end an operator halt, set `active = FALSE` before
the next 5 AM run.

**Overrides can only ADD a halt.** There is no operator "resume" — that is the design, so
a forgotten override can never publish picks during a real off-season. To end an automatic
halt you either fix the underlying metric or wait out the 14-day lifetime.

## Manually trigger the writer

```bash
CF_URL=$(gcloud functions describe halt-state-writer --gen2 \
  --region=us-west2 --project=nba-props-platform \
  --format='value(serviceConfig.uri)')

curl -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences=${CF_URL}/)" \
  "${CF_URL}/?sport=all"
```

Params: `target_date=YYYY-MM-DD` (backfill one date), `sport=nba`, `actor=on_call_<name>`.

## Writer not writing — now a Critical

Symptom: alert **"halt_state_writer not writing"** (absence-based; fires after 30h with no
`halt_state_age_hours` metric). The metric is emitted only on a successful write, so a
dead writer emits nothing — that is why the condition is absence, not a threshold.

Impact: **picks stop publishing** once the 3-day carry-forward window is exhausted.

1. Scheduler: `gcloud scheduler jobs describe halt-state-writer-daily --location=us-west2
   --project=nba-props-platform`. Should be `ENABLED` with a recent `lastAttemptTime`.
2. CF logs: `gcloud functions logs read halt-state-writer --gen2 --region=us-west2 --limit=50`.
3. Trigger manually (above), then **backfill every missed date** with `target_date=` —
   nothing does this automatically. The 2026-08-16..19 gap was four consecutive days and
   was never backfilled.

`halt-state-writer` has **no Cloud Build trigger**. Redeploy with
`./bin/deploy-function.sh halt-state-writer`, and verify by comparing the deployed
`BUILD_COMMIT` to the commit SHA — never by revision equality.

## Verify what the exporter actually saw

```bash
gcloud storage cat gs://nba-props-platform-api/v1/signal-best-bets/$(date +%Y-%m-%d).json | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
    print({k: d.get(k) for k in ['halt_active','halt_reason','halt_since','total_picks','status']})"
```

`halt_metrics.halt_source` distinguishes which gate fired: `halt_state` (Step 0),
`exporter_recompute` (the exporter's own same-day edge check — the backstop for a day the
writer failed to write), or a `carried_forward_from` date.

If the file shows `status: "degraded"`, the content guard refused to publish — that is the
`unknown_state` path, and the fix is to repair the writer and re-export, not to re-run the
exporter and hope.

## Related

- `shared/config/edge_halt.py` — the guard, its calibration and its honest limits.
- `docs/09-handoff/2026-08-21-SESSION-4-AUTO-HALT-REBUILD.md` — why it was demoted.
- `docs/02-operations/runbooks/halt-mode-frontend-impact.md` — frontend checklist.
- `docs/02-operations/runbooks/season-resume-2026-27.md` — opener sequence.
