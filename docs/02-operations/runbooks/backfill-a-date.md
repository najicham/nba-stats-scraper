# How to Backfill a Date

**Audience:** on-call. **Last updated:** 2026-05-09.

The pipeline-state-redesign makes backfilling a single date a routine, hands-free operation. The TL;DR:

1. Find what's missing.
2. Optionally reset FAILED rows to EXPECTED.
3. Wait for the auto-loop (gap_detector → Pub/Sub → scraper-gap-backfiller → reconciler) — typically completes within 30 min.
4. Verify in `expected_outputs`.

If something is permanently unrecoverable (e.g. paid historical odds we don't have access to), the row stays `FAILED` and that documents the loss.

## Step 1 — Find what's missing

```sql
SELECT
  game_date, phase, output_type, status, attempts, last_error
FROM `nba-props-platform.nba_orchestration.expected_outputs`
WHERE sport = 'nba' AND game_date = '2025-12-15'
ORDER BY phase, output_type
```

A healthy date has all rows in `COMPLETE` or `EMPTY_OK`. Any other status indicates a gap (or an intentional pause if `halt_state.halt_active=true` for that date).

## Step 2 — Reset FAILED rows (optional, if you've made a recovery action)

```sql
UPDATE `nba-props-platform.nba_orchestration.expected_outputs`
SET status = 'EXPECTED', attempts = 0, last_error = NULL,
    updated_at = CURRENT_TIMESTAMP(), source = 'manual_reset'
WHERE sport = 'nba'
  AND game_date = '2025-12-15'
  AND status = 'FAILED'
```

Skip this if you want to wait for the regular cadence to retry.

## Step 3 — Trigger the gap detector (optional)

`gap_detector` runs every 30 min anyway. To get an immediate retry:

```bash
CF_URL=$(gcloud functions describe gap-detector --gen2 \
  --region=us-west2 --project=nba-props-platform \
  --format='value(serviceConfig.uri)')

curl -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences=${CF_URL}/)" \
  "${CF_URL}/?limit=20"
```

The CF logs published count + skipped_at_cap.

## Step 4 — Watch the loop

```bash
# Pub/Sub messages flowing through?
gcloud pubsub topics list-subscriptions nba-backfill-trigger \
  --project=nba-props-platform

# scraper-gap-backfiller running?
gcloud run services logs read scraper-gap-backfiller \
  --region=us-west2 --project=nba-props-platform --limit=20
```

## Step 5 — Verify

After ~30 min for in-window dates, query `expected_outputs` again. Rows should be `COMPLETE` or, if applicable, `EMPTY_OK`.

If a row stays `EXPECTED + attempts > 0`, the scraper got the message but actual data write is in progress. Wait one more reconciler cycle (next :00 or :30).

## Backfilling many dates at once

For the Oct 2025 – Feb 2026 109-day NBA recovery (Phase F of the redesign):

1. Confirm the historical seed in `expected_outputs` covers the range:
   ```sql
   SELECT MIN(game_date), MAX(game_date), COUNT(DISTINCT game_date)
   FROM `nba-props-platform.nba_orchestration.expected_outputs`
   WHERE sport='nba'
   ```
   Expected: ≥ 235 distinct dates back to 2025-10-01.

2. The `gap_detector` MAX_PUBLISHES_PER_RUN cap is 50. With 30-min cadence and 21 outputs per missing NBA date, 109 dates × 21 = 2,289 outputs. At 50/run, that's ~46 hours of saturated firing — too long. For bulk backfills, raise the cap via env var:
   ```bash
   gcloud functions deploy gap-detector --gen2 --region=us-west2 \
     --update-env-vars=MAX_PUBLISHES_PER_RUN=200
   ```
   And revert when done.

3. Monitor coverage:
   ```sql
   SELECT phase, status, COUNT(*) AS n
   FROM `nba-props-platform.nba_orchestration.expected_outputs`
   WHERE sport='nba' AND game_date BETWEEN '2025-10-21' AND '2026-02-06'
   GROUP BY phase, status ORDER BY phase, status
   ```

4. Some Phase 1 outputs (paid-source historicals: `odds_api_*`, `bettingpros_*`, `numberfire_projections`, etc.) will exhaust attempts and end up `FAILED`. Document that as expected loss in `docs/08-projects/current/pipeline-state-redesign-2026-05/03-BACKFILL-MANIFEST.md`.

## Manual scraper invocation (when the loop isn't enough)

If a scraper bug prevents `scraper-gap-backfiller` from succeeding, run it manually:

```bash
# NBA gamebook for a specific date
gcloud run services proxy nba-scrapers --region=us-west2 --project=nba-props-platform &
PROXY_PID=$!

curl http://localhost:8080/scrape \
  -d '{"scraper":"nbac_gamebook_player_stats","date":"2025-12-15"}' \
  -H "Content-Type: application/json"

kill $PROXY_PID
```

Then run Phase 2 / 3 / 4 / 5 for that date as needed (same scraper service has processor endpoints, or trigger via the orchestrators directly).

## When the system is FULLY caught up

`expected_outputs_coverage` shows ≥ 99% completion across all phases for the audit window. The `expected_output_overdue` alert clears. The `nba-pipeline-health` dashboard goes green.
