# Session 534 Handoff — MLB best bets scheduler wiring

**Date:** 2026-04-15 (late session, continuation of 533)
**Focus:** Diagnosed and fixed a 5-day MLB best bets generation gap. Root cause: the `/best-bets` endpoint on the MLB worker had never been automated.
**Commits:** None. All changes are Cloud Scheduler edits (no YAML source-of-truth exists for these jobs).

---

## TL;DR

Session 533's handoff said "MLB operational. BB HR 7d: 100% (N=3)". That was misleading. **MLB best bets had never been in automated production.** `signal_best_bets_picks` had exactly 3 historical rows (Apr 9-10, N=3), all from manual curl invocations. Between Apr 11-15 zero new picks were generated.

The gap had two layers:
1. **No scheduler invoked `/best-bets`** on the MLB worker — the endpoint that actually generates picks.
2. **The MLB pitcher-export schedulers** published `export_types: ["pitchers"]` only — never `["best-bets"]`. So even if picks existed, nothing was publishing them to GCS.

Both layers fixed in Session 534. Today's first automated run produced **0 picks** — consistent with early-season signal/feature dormancy documented in the handoff (`season_csw_pct` NULL until ~May, 2026 FanGraphs data not yet available). The pipeline is now correctly wired; picks will flow as season data matures.

---

## What was applied

### 1. Edited two existing schedulers (add "best-bets" to payload)

| Scheduler | Schedule | Old payload | New payload |
|---|---|---|---|
| `mlb-pitcher-export-morning` | 10:45 AM ET Mar-Oct | `["pitchers"]` | `["pitchers","best-bets"]` |
| `mlb-pitcher-export-pregame` | 1:00 PM ET Mar-Oct | `["pitchers"]` | `["pitchers","best-bets"]` |

These publish to `nba-phase6-export-trigger` Pub/Sub topic → `phase6_export` Cloud Function → `MlbBestBetsExporter` (in `data_processors/publishing/mlb/mlb_best_bets_exporter.py`) which reads from `signal_best_bets_picks` and writes GCS JSON.

### 2. Created new scheduler (auto-trigger pick generation)

| Property | Value |
|---|---|
| Name | `mlb-best-bets-generate` |
| Schedule | `55 12 * 3-10 *` (12:55 PM ET daily Mar-Oct) |
| Method | HTTP POST |
| URI | `https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app/best-bets` |
| Body | `{"game_date": "TODAY"}` |
| Auth | OIDC `756957797294-compute@developer.gserviceaccount.com` |
| Deadline | 180s (observed ~22s cold-start runtime) |

This calls `predictions/mlb/worker.py:614` `@app.route('/best-bets', methods=['POST'])` which runs the full pipeline (predictions → signals → filters → ranking → ultra → BQ write to `signal_best_bets_picks`).

### Timing flow

```
12:30 PM ET — mlb-oddsa-pitcher-props-pregame    (Odds API props scraped)
12:45 PM ET — mlb-bp-props-pregame               (BettingPros props scraped)
12:55 PM ET — mlb-best-bets-generate             NEW: /best-bets → writes picks
 1:00 PM ET — mlb-predictions-generate           (existing, idempotent via per-pitcher dedup)
 1:00 PM ET — mlb-pitcher-export-pregame         EDITED: publishes pitchers + BB JSON
10:00 AM ET (next day) — mlb-grading-daily       (grades yesterday)
10:45 AM ET (next day) — mlb-pitcher-export-morning  EDITED: republishes BB JSON with actuals
```

### Validation

- Manual curl at 23:52 UTC: `{"best_bets_count": 0, "predictions_count": 25, "duration_seconds": 22.2}` — pipeline healthy, 0 picks is current legitimate output.
- Scheduler test-fire at 23:54 UTC: `User-Agent: Google-Cloud-Scheduler`, status 200. IAM + OIDC confirmed working.

---

## Why 0 picks today (not a bug)

From 533's handoff:
> Dead signals early season: `high_csw_over` (season_csw_pct NULL until ~May), `elite_peripherals_over` (FanGraphs FIP max_year=2025, no 2026 data). Expected — activate later in season.

Worker logs during today's BB run also warned:
> [catboost_v2_regressor] 3 features missing: `f08_season_games`, `f09_season_k_total`, `f23_season_ip_total`

So the model is making predictions with missing features, and most signals (which rely on rolling season data) are dormant. The BB pipeline requires `real_signal_count >= 2` for OVER picks (aggregator.py constant `MIN_SIGNAL_COUNT`). With signals dormant, nothing qualifies.

---

## Monitoring for next 7-14 days

Check daily whether picks start generating as season data accumulates:

```sql
-- Daily BB generation
SELECT game_date, COUNT(*) bb_picks
FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY 1 ORDER BY 1 DESC
```

Also watch the filter audit (empty today, should populate once picks are being filtered):

```sql
SELECT game_date, filter_name, filter_result, COUNT(*) cnt
FROM `nba-props-platform.mlb_predictions.best_bets_filter_audit`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1,2,3 ORDER BY 1 DESC, cnt DESC
```

### Decision tree if still zero picks by May 1

If 0 picks persists past May 1 despite season data maturing:

1. **Check `best_bets_filter_audit`** — if empty, pipeline isn't even reaching filter stage (likely feature-loading failure). If populated, some filter is blocking 100% of candidates.
2. **Check `signal_health_daily`** for MLB — which signals are firing? If all rows stale at Apr 10, signal evaluation is broken upstream.
3. **Check model state** — `catboost_v2_regressor` was DEGRADING/BLOCKED Apr 10-13, WATCH Apr 14. If it returns to BLOCKED, that could kill confidence downstream.
4. **Check MAE gap gate** — `league_macro_daily.mae_gap_7d` has been NULL all season (blocking gate can't fire on NULL), but if the grading pipeline starts populating it and it goes >0.3K, all OVER picks get blocked at exporter.py line 213.

---

## What's NOT fixed

### Option 3 from the diagnosis (post-grading refresh via dedicated trigger)
Deemed redundant — the 10:45 AM `mlb-pitcher-export-morning` runs 45 min after grading (10:00 AM `mlb-grading-daily`) and now re-publishes BB JSON with fresh actuals baked in via the existing Session 520 grading flow. No CF code change needed.

### Infrastructure-as-code drift
Neither the edited schedulers nor the new one exist in any YAML source-of-truth. `deployment/scheduler/mlb/` contains only `monitoring-schedules.yaml` and `validator-schedules.yaml`. Consider adding a scheduler-jobs YAML + deploy script so these aren't lost on a project reset. Low priority.

---

## Validation commands

```bash
# All three Session 534 schedulers
for j in mlb-pitcher-export-morning mlb-pitcher-export-pregame mlb-best-bets-generate; do
  echo "=== $j ==="
  gcloud scheduler jobs describe $j --project=nba-props-platform --location=us-west2 \
    --format="value(schedule,state,lastAttemptTime,status.code)"
done

# Today's BB picks (should grow as season matures)
bq query --use_legacy_sql=false \
  "SELECT game_date, COUNT(*) bb FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\`
   WHERE game_date >= CURRENT_DATE() - 7 GROUP BY 1 ORDER BY 1 DESC"

# Manual fire if needed
TOKEN=$(gcloud auth print-identity-token)
curl -X POST "https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app/best-bets" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"game_date": "TODAY"}'
```

---

## Session 533 handoff addendum

The 533 handoff's **one-thing-to-check** (`usage_surge_over` HOT at 83.3% N=6) was verified clean: signal remains in `SHADOW_SIGNALS` at `ml/signals/aggregator.py:96`. The HOT rows in `signal_health_daily` track shadow signal appearances, not active rescues. No action needed.

---

## Model Recommendation for Next Session

**Sonnet.** Remaining work is daily monitoring queries and potentially tracking down why signals stay dormant if April rolls over without picks. If you end up investigating MLB signal logic (`ml/signals/mlb/best_bets_exporter.py` is ~1100 lines with multiple filter classes), switch to Opus for that code dive; Sonnet for the BQ monitoring and scheduler ops.

---

## Memory updates made

- `memory/session-534.md` — full root cause + fix record
- `memory/MEMORY.md` — added session-534 index entry
