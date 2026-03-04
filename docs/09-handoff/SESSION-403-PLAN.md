# Session 403 Plan

**Prerequisites:** Session 402 deployed. Algorithm `v401_away_noveg_removed`. Both star_under and away_noveg filters removed. 10 models enabled, 0 production champions.

**When to run:** Mar 5+ (ideally after first full pipeline run with v401 active).

---

## Step 1: Validate v401 + Grade Results (15 min)

**Why:** First day with both filter removals active. Need to confirm deployment landed and check volume/quality.

```sql
-- 1a. Confirm algorithm version
SELECT DISTINCT algorithm_version, game_date
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-05'

-- 1b. Volume comparison — should see significant increase
SELECT game_date, total_candidates, passed_filters, algorithm_version,
  COALESCE(CAST(JSON_VALUE(rejected_json, '$.away_noveg') AS INT64), 0) as away_blocked,
  COALESCE(CAST(JSON_VALUE(rejected_json, '$.star_under') AS INT64), 0) as star_blocked
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-03'
ORDER BY game_date DESC

-- 1c. All best bets picks with grading
SELECT bb.game_date, bb.player_lookup, bb.recommendation,
  ROUND(bb.edge, 1) as edge, bb.system_id,
  bb.real_signal_count, bb.signal_rescued,
  ROUND(bb.composite_score, 2) as composite,
  pa.prediction_correct as hit, pa.actual_points
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date >= '2026-03-03'
ORDER BY bb.game_date DESC, bb.composite_score DESC

-- 1d. Grade Mar 3-4 picks (should be graded by now)
SELECT bb.game_date, bb.player_lookup, bb.recommendation,
  ROUND(bb.edge, 1) as edge, pa.prediction_correct as hit,
  pa.actual_points, bb.line_value
FROM nba_predictions.signal_best_bets_picks bb
JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date BETWEEN '2026-03-03' AND '2026-03-04'
ORDER BY bb.game_date
```

**Expected:** away_noveg = 0, star_under = 0, passed_filters 3-8x higher than pre-v401.
**If volume didn't increase:** Check Cloud Build succeeded, check deployment drift.

---

## Step 2: AWAY Picks Quality Check (10 min)

**Why:** First time AWAY noveg picks are flowing into best bets. Verify they're not diluting quality.

```sql
-- 2a. Check if any AWAY picks appeared in best bets
SELECT bb.game_date, bb.player_lookup, bb.recommendation,
  ROUND(bb.edge, 1) as edge, bb.system_id,
  CASE WHEN s.home_team_tricode = bb.team THEN 'HOME' ELSE 'AWAY' END as location,
  pa.prediction_correct as hit
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
LEFT JOIN nba_reference.nba_schedule s
  ON bb.game_id = s.game_id AND bb.game_date = s.game_date
WHERE bb.game_date >= '2026-03-05'
ORDER BY bb.game_date DESC

-- 2b. HOME vs AWAY HR in best bets (cumulative, for trend)
SELECT
  CASE WHEN s.home_team_tricode = bb.team THEN 'HOME' ELSE 'AWAY' END as location,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
LEFT JOIN nba_reference.nba_schedule s
  ON bb.game_id = s.game_id AND bb.game_date = s.game_date
WHERE bb.game_date >= '2026-03-05'
GROUP BY 1
```

**Action:** If AWAY HR drops below 45% on 15+ graded picks, consider re-adding a narrower filter (model-specific rather than blanket).

---

## Step 3: Star UNDER Monitor (5 min)

**Why:** star_under filter removed since v400b (active Mar 5). Track that star UNDER doesn't collapse.

```sql
SELECT FORMAT_DATE("%Y-W%V", pa.game_date) as week,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy pa
WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 28 DAY)
  AND pa.has_prop_line = TRUE AND pa.recommendation = 'UNDER'
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND pa.line_value >= 25 AND pa.prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1
```

**Threshold:** If < 50% on 30+ graded for 2 consecutive weeks, investigate. Don't add permanent filter (research proved it's model-specific).

---

## Step 4: Model Promotion Assessment (10 min)

**Why:** `catboost_v12_noveg_train0104_0215` has been in shadow since Mar 4. No production champion designated.

```sql
-- 4a. New model live performance
SELECT system_id,
  COUNT(*) as graded,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
  COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct IS NOT NULL) as edge3_total,
  COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge3_wins,
  ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) /
    NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct IS NOT NULL), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-03-04'
  AND has_prop_line = TRUE AND prediction_correct IS NOT NULL
  AND system_id IN (SELECT model_id FROM nba_predictions.model_registry WHERE enabled = TRUE)
GROUP BY 1 HAVING graded >= 5
ORDER BY edge3_hr DESC

-- 4b. Which models are sourcing best bets picks
SELECT bb.system_id,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date >= '2026-03-01'
GROUP BY 1 ORDER BY picks DESC
```

**Decision framework:**
- **Promote** `catboost_v12_noveg_train0104_0215` to production if: edge 3+ HR >= 60% on 10+ graded picks
- **If < 10 graded:** Wait another session. Backtest was 67.57% — patience.
- **Also consider:** Promote whichever model has best edge 3+ HR on 20+ graded picks as interim champion

---

## Step 5: Signal Rescue Validation (5 min)

```sql
-- 5a. All rescued picks
SELECT game_date, player_lookup, recommendation, rescue_signal,
  ROUND(edge, 1) as edge, real_signal_count, pa.prediction_correct as hit
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.signal_rescued = TRUE AND bb.game_date >= '2026-03-01'
ORDER BY bb.game_date

-- 5b. Rescued pick HR (when enough data)
SELECT
  COUNT(*) as total_rescued,
  COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.signal_rescued = TRUE AND bb.game_date >= '2026-03-01'
```

**If N >= 10 rescued:** Start evaluating per-tag HR. Otherwise just note volume.

---

## Step 6: Fix Failing Scrapers (30 min, if time)

**Why:** 3/10 new scrapers are failing. These feed future signals (projection_consensus, CLV, etc).

### 6a. NumberFire → FanDuel redirect
- NumberFire now redirects to FanDuel research
- Options: (1) Scrape FanDuel projections directly (may need Playwright for JS), (2) Find alternative free projection source, (3) Disable and rely on FantasyPros + DFF + Dimers for consensus
- **Recommended:** Disable NumberFire scheduler, rely on the 3 working projection scrapers

### 6b. VSiN betting splits (AJAX)
- Site loads data via JavaScript — HTML scraping gets empty tables
- Options: (1) Find the underlying API endpoint via browser devtools, (2) Use Playwright, (3) Disable
- **Check:** `curl -s https://www.vsin.com/nba/betting-splits/ | grep -c "table"` — if 0, confirm JS-only

### 6c. NBA tracking stats (timeout)
- stats.nba.com blocks/throttles cloud IPs
- Options: (1) Use `nba_api` Python library instead of direct HTTP, (2) Route through proxy, (3) Increase timeout to 120s with retries
- **Recommended:** Install `nba_api` and refactor scraper to use it

```bash
# Disable failing schedulers (recommended if not fixing immediately)
gcloud scheduler jobs pause numberfire-projections-daily --location=us-west2
# Fix and re-enable later
```

---

## Step 7: Brier-Weighted Model Selection Research (20 min, if time)

**Why:** The fleet now has ~10 days of multi-model data. Brier calibration could improve per-player model selection.

**Prerequisite:** At least 3-4 enabled models with 50+ graded edge 3+ picks (check Step 4 first).

```sql
-- Current fleet Brier scores
SELECT model_id,
  ROUND(brier_score_14d, 4) as brier_14d,
  ROUND(brier_score_30d, 4) as brier_30d,
  ROUND(rolling_hr_14d, 1) as hr_14d,
  rolling_n_14d as n_14d,
  state
FROM nba_predictions.model_performance_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.model_performance_daily)
  AND model_id IN (SELECT model_id FROM nba_predictions.model_registry WHERE enabled = TRUE)
  AND rolling_n_14d >= 10
ORDER BY brier_14d ASC
```

**If sufficient data exists:**
- Compare: Would Brier-weighted selection change which model wins per-player picks?
- Concept: `ORDER BY edge * (1 / GREATEST(brier_score_14d, 0.15)) DESC` in per-player selection
- Simulate against historical data to measure impact on best bets HR

**If insufficient:** Defer to Session 404+. Focus on validation steps.

---

## Step 8: Fleet Cleanup Review (10 min, if time)

**Why:** 10 models is a lot. Check if any are consistently losing in best bets context.

```sql
-- Models in best bets with losing records
SELECT bb.system_id,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date >= '2026-02-20'
GROUP BY 1
HAVING graded >= 5
ORDER BY hr ASC
```

**Disable if:** Model has < 45% HR on 20+ graded best bets picks.
**Use:** `python bin/deactivate_model.py MODEL_ID [--dry-run]`

---

## Priority Order

1. **Step 1** — Validate v401, grade results (always first)
2. **Step 2** — AWAY picks quality (critical to verify removal was correct)
3. **Step 3** — Star UNDER monitor (quick check)
4. **Step 4** — Model promotion (if data supports)
5. **Step 5** — Signal rescue check (30 seconds)
6. **Step 6** — Fix failing scrapers (if time)
7. **Step 7** — Brier research (if models have enough data)
8. **Step 8** — Fleet cleanup (if any model clearly failing)

---

## Don't Do

- Don't re-add away_noveg filter — data is clear (60% HR, root cause was staleness)
- Don't add seasonal star_under — research proved Feb collapse was model-specific
- Don't promote models with < 10 graded edge 3+ picks — patience
- Don't retrain more models — fleet has 10, focus on evaluation
- Don't touch signal rescue criteria — need 14+ days of production data
- Don't lower OVER edge floor below 5.0 — 25% HR in best bets context
- Don't disable models without checking best bets impact first (user preference)

---

## Key Metrics to Track Going Forward

| Metric | Pre-v401 Baseline | Target |
|--------|-------------------|--------|
| Daily picks | 1-2 | 3-6 |
| Filter pass rate | ~7% | ~20-30% |
| Best bets HR (rolling 14d) | 61.1% | >= 55% |
| AWAY picks HR | N/A (blocked) | >= 55% |
| Star UNDER HR | N/A (blocked) | >= 55% |
| Rescued pick HR | N/A (1 pick) | >= 55% |

---

## Context: What Happened in Sessions 400-402

| Session | Key Change | Status |
|---------|-----------|--------|
| 400 | Signal-first UNDER architecture | Deployed, active Mar 5+ |
| 400b | star_under filter removed | Deployed, active Mar 5+ |
| 401 | 10 new scrapers + processors + signals | Deployed, 7/10 working |
| 402 | away_noveg filter removed + fleet evaluation | Deployed, active Mar 5+ |
