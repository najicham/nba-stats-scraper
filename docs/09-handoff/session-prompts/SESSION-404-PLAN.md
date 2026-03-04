# Session 404 Plan

**Prerequisites:** Session 403 deployed. All 3 failing scrapers fixed + Playwright removed. Exporter consistency bug fixed. Build succeeded. v401 active.

**When to run:** Mar 5+ (after first full pipeline run with fixed scrapers).

---

## Step 1: Verify Scraper Deploy + First Data (10 min)

**Why:** Three scrapers were just fixed and deployed. Need to confirm they produce data.

```sql
-- 1a. NumberFire projections (should have data if FanDuel GraphQL works)
SELECT game_date, COUNT(*) as players, MAX(scraped_at) as latest
FROM nba_raw.numberfire_projections
WHERE game_date >= '2026-03-05'
GROUP BY 1

-- 1b. VSiN betting splits (should have data from server-rendered HTML)
SELECT game_date, COUNT(*) as games, MAX(scraped_at) as latest
FROM nba_raw.vsin_betting_splits
WHERE game_date >= '2026-03-05'
GROUP BY 1

-- 1c. NBA Tracking stats (may still fail — stats.nba.com blocks proxies)
SELECT game_date, COUNT(*) as players, MAX(scraped_at) as latest
FROM nba_raw.nba_tracking_stats
WHERE game_date >= '2026-03-05'
GROUP BY 1
```

**If NumberFire/VSiN still empty:**
```bash
# Check Cloud Run logs for scraper errors
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-scrapers" AND (textPayload=~"numberfire" OR textPayload=~"vsin") AND severity>=WARNING' --limit=10 --format='table(timestamp,textPayload)' --project=nba-props-platform
```

**If NBA Tracking still fails:** Expected. stats.nba.com may block all proxy IPs. Disable scheduler if no data after 3 days:
```bash
gcloud scheduler jobs pause nba-tracking-stats-daily --location=us-west2
```

---

## Step 2: Grade Mar 4 Picks + Signal Rescue (5 min)

**Why:** Two signal-rescued picks were made for Mar 4. First production rescue data.

```sql
-- 2a. Mar 4 pick results
SELECT bb.game_date, bb.player_lookup, bb.recommendation,
  ROUND(bb.edge, 1) as edge, bb.system_id,
  bb.signal_rescued, bb.rescue_signal,
  pa.prediction_correct as hit, pa.actual_points, bb.line_value
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date = '2026-03-04'

-- 2b. Cumulative signal rescue performance
SELECT
  COUNT(*) as total, COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.signal_rescued = TRUE
```

**Action if rescue HR < 40% on 10+ graded:** Review rescue signal criteria.

---

## Step 3: Check Mar 5 v401 Volume (5 min)

**Why:** First FULL day with v401 + fixed scrapers + projection consensus.

```sql
-- 3a. Filter audit
SELECT game_date, total_candidates, passed_filters, algorithm_version,
  rejected_json
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-05'
ORDER BY game_date DESC

-- 3b. Best bets picks
SELECT game_date, player_lookup, recommendation, ROUND(edge, 1) as edge,
  system_id, real_signal_count, signal_rescued,
  ARRAY_TO_STRING(signal_tags, ', ') as signals
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-05'
ORDER BY composite_score DESC
```

**Expected:** 3-6 picks per day (up from 1-2). If still 1-2, check if projection_consensus signal is firing.

---

## Step 4: Projection Consensus Signal Check (10 min)

**Why:** Wired 4 projection sources into supplemental_data. Need to verify signal fires.

```sql
-- 4a. Check if projection_consensus appears in signal tags
SELECT game_date,
  COUNTIF('projection_consensus' IN UNNEST(signal_tags)) as has_consensus,
  COUNT(*) as total_picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-05'
GROUP BY 1

-- 4b. Check projection data availability for consensus
SELECT
  COUNTIF(fp.projected_points IS NOT NULL) as has_fantasypros,
  COUNTIF(dff.projected_points IS NOT NULL) as has_dff,
  COUNTIF(dim.projected_points IS NOT NULL) as has_dimers,
  COUNTIF(nf.projected_points IS NOT NULL) as has_numberfire,
  COUNT(*) as total_players
FROM nba_predictions.player_prop_predictions p
LEFT JOIN nba_raw.fantasypros_projections fp
  ON p.player_lookup = fp.player_lookup AND p.game_date = fp.game_date
LEFT JOIN nba_raw.dailyfantasyfuel_projections dff
  ON p.player_lookup = dff.player_lookup AND p.game_date = dff.game_date
LEFT JOIN nba_raw.dimers_projections dim
  ON p.player_lookup = dim.player_lookup AND p.game_date = dim.game_date
LEFT JOIN nba_raw.numberfire_projections nf
  ON p.player_lookup = nf.player_lookup AND p.game_date = nf.game_date
WHERE p.game_date >= '2026-03-05'
```

**If consensus not firing:** Check `ml/signals/projection_consensus.py` threshold (MIN_SOURCES=2). If NumberFire not flowing, 3 sources may still be enough.

---

## Step 5: Model Promotion Assessment (10 min)

**Why:** V16 was at 15 graded edge 3+ with 73.3% HR. May have hit 20+ by now.

```sql
SELECT system_id,
  COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_total,
  COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge3_wins,
  ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) /
    NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-02-15'
  AND has_prop_line = TRUE AND prediction_correct IS NOT NULL
  AND system_id IN (SELECT model_id FROM nba_predictions.model_registry WHERE enabled = TRUE)
GROUP BY 1
HAVING edge3_total >= 10
ORDER BY edge3_hr DESC
```

**Promote if:** Any model has 20+ graded edge 3+ AND >= 65% HR. Use:
```bash
# Update model_registry to set is_production = TRUE
bq query --use_legacy_sql=false "UPDATE nba_predictions.model_registry SET status = 'production' WHERE model_id = 'MODEL_ID'"
```

---

## Step 6: Exporter Consistency Verification (5 min)

**Why:** Session 403 moved disabled model filter upstream. Verify GCS and BQ match.

```bash
# Compare GCS picks vs BQ picks for Mar 5
gsutil cat gs://nba-props-platform-api/v1/signal-best-bets/2026-03-05.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'GCS: {d[\"total_picks\"]} picks')"

bq query --use_legacy_sql=false "SELECT COUNT(*) as bq_picks FROM nba_predictions.signal_best_bets_picks WHERE game_date = '2026-03-05'"
```

**Expected:** GCS picks == BQ picks. If not, the fix didn't fully resolve the issue.

---

## Step 7: Brier-Weighted Model Selection Research (20 min, if models have data)

**Prerequisite:** At least 2 models with 50+ graded picks.

```sql
-- Check fleet Brier scores
SELECT model_id,
  ROUND(brier_score_14d, 4) as brier_14d,
  ROUND(rolling_hr_14d, 1) as hr_14d,
  rolling_n_14d as n_14d
FROM nba_predictions.model_performance_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.model_performance_daily)
  AND model_id IN (SELECT model_id FROM nba_predictions.model_registry WHERE enabled = TRUE)
  AND rolling_n_14d >= 20
ORDER BY brier_14d ASC
```

**If sufficient data:** Simulate Brier-weighted selection:
- Current: `ORDER BY edge DESC` for per-player model selection
- Proposed: `ORDER BY edge * (1 / GREATEST(brier_score_14d, 0.15)) DESC`
- Compare which model wins per player under both schemes

---

## Step 8: Fleet Health Check (5 min)

```sql
-- Any model with losing record in best bets?
SELECT bb.system_id,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date >= '2026-02-20'
GROUP BY 1 HAVING graded >= 5
ORDER BY hr ASC
```

**Disable if:** Model has < 45% HR on 20+ graded best bets picks.

---

## Priority Order

1. **Step 1** — Verify scraper deploy (always first)
2. **Step 2** — Grade Mar 4 picks + signal rescue
3. **Step 3** — Check Mar 5 volume
4. **Step 4** — Projection consensus check
5. **Step 5** — Model promotion
6. **Step 6** — Exporter consistency
7. **Step 7** — Brier research (if data ready)
8. **Step 8** — Fleet health

---

## Don't Do

- Don't re-add Playwright to Docker — all scrapers work without it
- Don't re-add away_noveg or star_under filters
- Don't promote models with < 20 graded edge 3+ picks
- Don't retrain — 10 models in fleet, focus on evaluation
- Don't touch signal rescue criteria — need 14+ days of data
- Don't lower OVER edge floor below 5.0
- Don't try to fix game_id format mismatch — use team+opponent+date joins instead
