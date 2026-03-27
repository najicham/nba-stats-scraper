# Session 496 Handoff — 2026-03-27

**Date:** 2026-03-27 (~11:15 AM ET)
**Commit:** `7fc1e01b`

---

## What Happened Today

### 0 NBA Picks — Why It's Correct

Today (Friday, 10-game slate) has 0 picks. All filters working correctly:

| Filter | CF HR | Verdict |
|--------|-------|---------|
| `med_usage_under` | 45.2% (N=52) | ✅ Correctly blocking losers |
| `q4_scorer_under_block` | 40.0% (N=8) | ✅ Correctly blocking losers |
| `signal_density` | 44.2% (N=48) | ✅ Correctly blocking losers |
| `friday_over_block` | N/A | Active — blocks all Friday OVER |

**Root cause of 0 picks:**
1. `friday_over_block` blocks all 14 OVER candidates
2. `under_low_rsc` (real_sc >= 2 required) blocks UNDER picks with only home_under (real_sc=1)
3. 3 candidates survived to filter stage (Tatum UNDER 8.8/7.0, Pritchard UNDER 5.4, Reaves UNDER 4.9)
4. Tatum and Pritchard blocked by `med_usage_under` (teammate usage 15-30 → historically bad UNDER)
5. Reaves blocked by `q4_scorer_under_block`

**For Saturday: no friday_over_block + home_over_obs in observation → picks expected.**

---

## Session 496 Changes (commit `7fc1e01b`)

### 1. `home_over_obs` Reverted to Observation
- **Why:** BB-level CF HR = 70% (N=10) — filter was blocking winners, not losers
- Raw prediction CF HR was 49.7% (N=4,278) but at BB-qualified level, 70% of blocked home OVER picks WIN
- Algorithm version: `v496_home_over_revert_batch_subset`
- **Impact today:** None (friday_over_block already blocks all OVER)
- **Impact Saturday+:** Home OVER picks now eligible

### 2. Fixed `current_subset_picks` Streaming Buffer Error
- **Root cause:** `signal_subset_materializer.py` and `cross_model_subset_materializer.py` used `insert_rows_json` (streaming insert). BigQuery streaming inserts can't be DELETEd for ~90 min.
- **Fix:** Switched both to `load_table_from_json` (batch load). DELETE now works on previously batch-loaded rows.
- **Impact:** Phase 6 no longer accumulates duplicate rows in `current_subset_picks` across daily re-runs.

### 3. Decay-Detection CF Auto-Disabled 2 BLOCKED Models (11 AM ET run)
- `lgbm_v12_noveg_train0103_0228` → blocked/disabled ✅
- `lgbm_v12_noveg_train1215_0214` → blocked/disabled ✅
- Kept `catboost_v12_noveg_train0118_0315` (N=8 < 15 minimum, not enough BB picks to disable)

### 4. Model Registry Now Clean
4 enabled models:
| Model | State | Notes |
|-------|-------|-------|
| `lgbm_v12_noveg_train0103_0227` | WATCH (55.4% HR) | Primary workhorse |
| `catboost_v12_noveg_train0121_0318` | No data yet | NEW — training data Jan 21-Mar 18 |
| `lgbm_v12_noveg_train0121_0318` | No data yet | NEW — training data Jan 21-Mar 18 |
| `catboost_v12_noveg_train0118_0315` | BLOCKED (50%, N=8) | Low N — pending auto-disable |

---

## Current System State

### Phase 6 Status
- Streaming buffer fix deployed and working
- `best_bets_filtered_picks` partition fix from `a176e89a` also confirmed working
- Phase 6 re-runs at 1 PM ET and 5 PM ET (scheduled). Last manual trigger at 16:17 UTC = 11:17 AM ET → 0 picks (correct)

### Signal Health
- `home_under`: HOT at 66.7-69.2% HR 7d (strongest active signal)
- All other UNDER signals: COLD or NORMAL
- `line_rising_over`: NORMAL at 50-58%
- `usage_surge_over`: NORMAL at 54-58%
- TIGHT market: Not active (no regime_context throttling)

### Model Performance (as of March 26)
- Fleet HR 7d: 55% (WATCH territory)
- Weekly retrain Monday March 30 at 5 AM ET — check Slack #nba-alerts

---

## Pending Items for Next Chat

### 1. Saturday Verification (HIGH PRIORITY)
After Saturday's picks publish (1 PM ET Saturday):
```sql
SELECT recommendation, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-28'
GROUP BY 1
```
Expected: 5-15 picks including home OVER candidates

### 2. `catboost_v12_noveg_train0118_0315` Monitoring
- State: BLOCKED in model_performance_daily but still enabled (N=8 < 15 auto-disable floor)
- Will auto-disable once it accumulates N >= 15 BB picks with consecutive_alert >= 3
- Monitor: Will likely auto-disable within 1-2 days

### 3. Monday Retrain (March 30)
- Weekly-retrain CF fires 5 AM ET
- 60% governance gate — ~35-45% pass probability
- If passes: new models registered, need `./bin/model-registry.sh sync`
- If fails: existing models continue unchanged

### 4. MLB Phase 3/4 Bootstrap
**Today is Opening Day.** No predictions possible until 2026 games play out and Phase 3/4 run.

**Timeline:**
- Tonight: First 2026 games play (game results)
- Phase 1 scrapers collect stats (MLB phase1 runs ~10:30 PM ET)
- **Phase 2 needs MANUAL run** (no automation): GCS → BQ
- Phase 3 can then process game analytics
- Phase 4 computes features
- Predictions possible March 28 IF Phase 2/3/4 run

**Automation gap:** `mlb-phase2-raw-processors` service doesn't exist. Need to create or set up a scheduler. See `bin/raw/deploy/mlb/deploy_mlb_processors.sh` and `bin/pubsub/setup_mlb_subscriptions.sh`.

**For manual Phase 2 after tonight:**
```bash
# Check if Phase 1 scraped data arrived in GCS
gsutil ls gs://nba-scraped-data/mlb/ | grep $(date +%Y-%m-%d)

# Manually trigger Phase 2 (if service existed)
# Currently must run locally or via direct BQ loads
```

### 5. Over_edge_floor CF HR = 58.1% (N=92) — Observation
- Daily variation too high (0-100%) to act on seasonal average
- Not changing edge floor — 5-season data says edge 3-5 OVER is net-negative
- Keep monitoring

---

## Diagnostic Queries

```sql
-- Saturday picks check
SELECT recommendation, COUNT(*) as picks, AVG(edge) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-28'
GROUP BY 1;

-- Model registry clean state
SELECT model_id, status, enabled FROM nba_predictions.model_registry
WHERE enabled = true ORDER BY model_id;

-- Check BLOCKED model performance (catboost_0118 pending auto-disable)
SELECT model_id, state, rolling_hr_7d, rolling_n_7d, consecutive_days_below_alert
FROM nba_predictions.model_performance_daily
WHERE game_date = CURRENT_DATE() - 1
  AND model_id = 'catboost_v12_noveg_train0118_0315';
```

---

## Key Commits This Session

| Commit | Description |
|--------|-------------|
| `7fc1e01b` | home_over_obs observation + streaming buffer fix + algorithm v496 |
