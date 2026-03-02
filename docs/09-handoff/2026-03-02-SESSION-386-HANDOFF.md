# Session 386 Handoff — Poisoned Published Picks Prevention System

**Date:** 2026-03-02
**Focus:** Fix poisoned XGBoost picks on site + build systemic prevention

## Incident Summary

XGBoost model (`xgb_v12_noveg_train1221_0208`) with version mismatch (trained 3.1.2, production 2.0.2) produced predictions ~8.6pts too low — all UNDER with inflated edges (-8 to -10). These got locked into `best_bets_published_picks` before the model was deactivated in Session 383B. After deactivation, 8 poisoned picks persisted on the site as phantom ungraded picks because:

1. Signal pipeline correctly dropped them from `signal_best_bets_picks`
2. But pick locking (Session 340) preserved them in `best_bets_published_picks`
3. The all.json exporter only JOINs grading for picks IN `signal_best_bets_picks`
4. Published-only picks had no `system_id` — source model was invisible

## What Was Done

### Immediate Cleanup (Part 1)
- Deleted 8 poisoned picks from `best_bets_published_picks` for 2026-03-01
- Re-exported all.json — now shows only 2 legitimate picks (Cam Thomas WIN, Kawhi Leonard WIN)

### Structural Fixes (Parts 2-5)
1. **system_id + signal_status on published picks** — Published picks now track which model sourced them (`system_id`) and their lifecycle state (`signal_status`: active/dropped/model_disabled). Schema + code + BQ ALTER TABLE done.

2. **Published-only grading** — New `_query_grading_for_published_picks()` method grades locked-but-dropped picks using prediction_accuracy (with player_game_summary fallback). Derives `prediction_correct` from actual vs line when using fallback.

3. **Disabled model detection** — `_merge_and_lock_picks()` checks model_registry for disabled models. Locked picks from disabled models get marked `model_disabled`. Signal exporter also filters disabled models before writing to `signal_best_bets_picks` (defense-in-depth).

4. **Pick event logging** — New `best_bets_pick_events` BQ table (partitioned by game_date) tracks lifecycle events with `event_type` (dropped_from_signal, model_disabled, manually_removed), reason, system_id, and edge/rank snapshot.

### Operational Tooling (Part 6)
- **`bin/deactivate_model.py`** — Proper model deactivation cascade:
  ```
  python bin/deactivate_model.py MODEL_ID [--date YYYY-MM-DD] [--dry-run] [--re-export]
  ```
  Steps: verify model → disable in registry → deactivate predictions → remove signal picks → audit trail → optional re-export

## Files Changed

| File | Change |
|------|--------|
| `data_processors/publishing/best_bets_all_exporter.py` | system_id/signal_status tracking, grading for published-only picks, disabled model check, pick event logging, enhanced audit snapshot |
| `data_processors/publishing/signal_best_bets_exporter.py` | Defense-in-depth disabled model filter before BQ write |
| `schemas/bigquery/nba_predictions/best_bets_published_picks.sql` | Added `system_id`, `signal_status` columns |
| `schemas/bigquery/nba_predictions/best_bets_pick_events.sql` | New table |
| `bin/deactivate_model.py` | New CLI script |
| `CLAUDE.md` | Updated issues table + cross-model monitoring |
| `docs/02-operations/session-learnings.md` | Session 386 entry |

## BQ Schema Changes Applied

```sql
-- Already executed:
ALTER TABLE best_bets_published_picks ADD COLUMN system_id STRING, ADD COLUMN signal_status STRING;
CREATE TABLE best_bets_pick_events (...);  -- See schema file
```

## Prevention Architecture (6 layers)

```
Layer 1: Model sanity guard (aggregator) — blocks >95% same-direction
Layer 2: Signal exporter disabled model filter — prevents entry to signal_best_bets_picks
Layer 3: Published picks disabled model detection — marks locked picks model_disabled
Layer 4: Published-only grading — grades dropped picks via prediction_accuracy/player_game_summary
Layer 5: Pick event logging — structured audit trail for all drops
Layer 6: Deactivation CLI — single command for proper cascade
```

## Deployment

Commit `5eccddbe` auto-deployed via Cloud Build. Changes affect:
- `prediction-coordinator` (via `data_processors/publishing/`)
- No new Cloud Functions needed

Verify with: `./bin/check-deployment-drift.sh --verbose`

## What's NOT Done

- Pick events are only logged during all.json export (not real-time). This is fine since exports run every hour during game days.
- Historical published picks don't have `system_id` backfilled (only new writes populate it). Not worth backfilling — forward-looking only.
- The deactivation CLI doesn't auto-detect poisoned models. That's still the model sanity guard's job (Layer 1).

## Verification

After next game day with drops:
1. Check `best_bets_published_picks` has `system_id` and `signal_status` populated
2. Check `best_bets_pick_events` has event rows for any drops
3. If a model gets disabled, verify `deactivate_model.py --dry-run` shows correct counts
