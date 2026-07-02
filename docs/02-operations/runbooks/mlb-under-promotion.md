# Runbook — Promoting MLB UNDER picks from shadow to live

**Owner:** user (Naji). No automated promotion — this is always a deliberate human flip.

## State today

- `MLB_UNDER_ENABLED` defaults to `false` in `ml/signals/mlb/best_bets_exporter.py:64`.
- The deployed `mlb-prediction-worker` service has **no override** — the env var is not set anywhere in `cloudbuild-mlb-worker.yaml` or `bin/scrapers/deploy/mlb/`, so the default applies.
- Shadow UNDER picks land in `nba-props-platform.mlb_predictions.blacklist_shadow_picks` (existing table; not UNDER-specific yet — Agent 2 owns the schema decision).

## Pre-flip gates (ALL must hold)

1. **Shadow N** — Agent 2 sets target. Suggested floor: N ≥ 30 graded shadow UNDER picks.
2. **Shadow rolling HR** — Agent 2 sets target. Suggested floor: ≥ 56% over the last 30 days.
3. **No alerts firing** — `mlb-under-shadow-monitor` (see alert section) has been GREEN for 7+ consecutive days.
4. **Signal coverage** — Agent 4's UNDER signals (`book_disagree_under`, `velocity_drift_under`, etc.) live and producing.
5. **Filter coverage** — Agent 5's UNDER negative filters merged and audit-clean.
6. **User sign-off** — explicit go.

## Promotion steps

1. **Review** — pull last 30 days of shadow UNDERs:
   ```sql
   SELECT game_date, COUNT(*) AS n,
          COUNTIF(prediction_correct) AS hits,
          ROUND(COUNTIF(prediction_correct)/COUNT(*)*100,1) AS hr
   FROM `nba-props-platform.mlb_predictions.blacklist_shadow_picks`
   WHERE recommendation = 'UNDER'
     AND game_date BETWEEN CURRENT_DATE() - 30 AND CURRENT_DATE() - 1
     AND prediction_correct IS NOT NULL
   GROUP BY 1 ORDER BY 1 DESC;
   ```
2. **Confirm gates met** — write a one-paragraph promotion memo in the session handoff.
3. **Flip the flag:**
   ```bash
   gcloud run services update mlb-prediction-worker \
     --region=us-west2 --project=nba-props-platform \
     --update-env-vars=MLB_UNDER_ENABLED=true
   ```
   (NEVER use `--set-env-vars` — wipes the rest.)
4. **Verify revision live:**
   ```bash
   gcloud run services describe mlb-prediction-worker --region=us-west2 \
     --format='value(status.traffic[0].latestRevision,status.traffic[0].percent)'
   # expect: <revision-name>, 100
   ```
5. **Tomorrow morning check** — count today's UNDER picks in production:
   ```sql
   SELECT recommendation, COUNT(*) FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
   WHERE game_date = CURRENT_DATE() GROUP BY 1;
   ```
   Also check `best_bets_filter_audit` for any `direction_filter` blocks (should be zero).
6. **Watch week 1** — the `mlb-under-shadow-monitor` keeps firing on the same query in live mode. Auto-pages if 7d UNDER HR < 50% or 5+ days with zero UNDER picks.

## Rollback (if HR collapses)

```bash
gcloud run services update mlb-prediction-worker \
  --region=us-west2 --project=nba-props-platform \
  --update-env-vars=MLB_UNDER_ENABLED=false
```
This stops new UNDER picks within one prediction-worker invocation (~5 min). Existing UNDER picks already in `signal_best_bets_picks` and the published JSON stay until graded — that's correct (don't retroactively delete real picks). Document the rollback in a session handoff with the trailing HR and the suspected cause (signal regime shift, model drift, schedule artifact).

## Threshold sources (defer to)

- **Pre-flip N/HR thresholds:** Agent 2 — shadow design.
- **Volume cap interplay:** `MAX_PICKS_PER_DAY = 5` is a single shared bucket in `ml/signals/mlb/best_bets_exporter.py:82`. UNDER competes with OVER for slots; rank is `over_picks + under_picks` (`best_bets_exporter.py:589`). If UNDER quality is real, it will displace marginal OVERs. No quota split today — don't add one without 30+ days of live data.
