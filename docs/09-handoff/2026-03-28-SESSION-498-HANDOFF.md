# Session 498 Handoff — 2026-03-28

**Date:** 2026-03-28 (morning ET)
**Commits:** None (exploration/monitoring only session)

---

## What Happened Today

Session 497 fixed 3 MLB pipeline bugs (OIDC auth, hardcoded NBA topics in analytics_base + precompute_base). This session was monitoring/exploratory: verified those deploys, ran signal health + fleet + BB performance analysis, and confirmed Opening Day MLB status this morning.

---

## Critical Issues for Next Session

### 1. MLB Pipeline — Opening Day Cascade FAILED (HIGH PRIORITY)

**Status:** 0 MLB predictions ever. 0 records in `mlb_analytics.pitcher_game_summary`. Opening Day (March 27) games played but the cascade never fired.

**What we know:**
- Phase 3-6 OIDC auth was fixed in Session 497 ✓
- `analytics_base.py` and `precompute_base.py` sport-aware topics fixed ✓
- Phase 2 raw processing for MLB may not have run — `mlb_analytics.pitcher_game_summary` has 0 rows

**Investigation needed:**
```bash
# 1. Did MLB Phase 2 run? Check for raw data
bq query --nouse_legacy_sql --project_id=nba-props-platform \
  "SELECT MAX(game_date), COUNT(*) FROM mlb_raw.pitcher_game_logs WHERE game_date >= '2026-03-27'"

# 2. Did Phase 1 (scraper) write any data?
bq query --nouse_legacy_sql --project_id=nba-props-platform \
  "SELECT table_name FROM mlb_raw.INFORMATION_SCHEMA.TABLES"

# 3. Check MLB scraper logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=mlb-scrapers AND timestamp>=\"2026-03-27T22:00:00Z\"" --limit=50 --project=nba-props-platform
```

**If Phase 2 raw data exists but Phase 3 didn't run, manually trigger:**
```bash
TOKEN=$(gcloud auth print-identity-token --audiences="https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app")
curl -s -X POST https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-03-27"}'
```

---

### 2. NBA Fleet in Distress (MEDIUM PRIORITY — watch, may self-heal Monday)

| Model | State | 7d HR | N | Consecutive |
|---|---|---|---|---|
| `catboost_v12_noveg_train0118_0315` | BLOCKED | 46.2% | 13 | 3 |
| `catboost_v12_noveg_train0121_0318` | BLOCKED | 45.5% | 11 | 1 |
| `lgbm_v12_noveg_train0103_0227` | DEGRADING | 53.0% | 83 | 1 |
| `lgbm_v12_noveg_train0121_0318` | WATCH | 56.5% | 23 | 0 |

**Key concerns:**
- `catboost_v12_noveg_train0121_0318` is **BLOCKED on day 1** (registered March 27, already BLOCKED with N=11). This is suspicious — N=11 is too small to trust. Likely statistical noise.
- `catboost_v12_noveg_train0118_0315` has N=13, consecutive=3. Auto-disable fires when N≥15 AND consecutive≥3. One more day with picks could trigger it. When it does, fleet drops to 3 models (safety floor).
- `lgbm_v12_noveg_train0103_0227` (DEGRADING) is the largest sample (N=83) — most trustworthy state reading.
- Only `lgbm_v12_noveg_train0121_0318` (WATCH) is stable.

**Auto-disable check at 11 AM ET daily:**
```sql
SELECT model_id, state, rolling_hr_7d, rolling_n_7d, consecutive_days_below_alert
FROM nba_predictions.model_performance_daily
WHERE game_date = CURRENT_DATE()
  AND model_id IN (SELECT model_id FROM nba_predictions.model_registry WHERE enabled = TRUE)
ORDER BY model_id
```

**Note:** Do NOT manually disable `catboost_v12_noveg_train0121_0318` yet — N=11 is too small. Let it accumulate picks before acting. If it's still BLOCKED at N=30+, then investigate.

---

### 3. NBA Picks Drought — 0 Picks March 28 (WATCH)

March 28 has 6 games and the fleet generated predictions, but `signal_best_bets_picks` is empty. This may be:
1. **Phase 6 export hasn't fired yet** (pipeline runs through the day — check again after noon ET)
2. **Fleet degradation suppressing picks** — BLOCKED models may have reduced weight in the BB pipeline

Check at noon ET:
```sql
SELECT game_date, recommendation, COUNT(*) AS picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-28'
GROUP BY 1, 2
```

Best available model edge (March 28):
- `lgbm_v12_noveg_train0121_0318`: 6 OVER (2 at edge 5+), 8 UNDER (2 at edge 5+) — these should generate picks if pipeline runs

---

## Monday Retrain (March 30, 5 AM ET) — CRITICAL

This retrain is the most important event of the next few days. The fleet is degraded and fresh models are needed.

**What will happen:**
- 3 families retrain: `lgbm_v12_noveg_mae`, `v12_mae` (CatBoost), `v12_noveg_mae` (CatBoost)
- **TIGHT market cap fires:** train_end capped at March 7 (last day before TIGHT window). New model IDs will be `*_train0110_0307`
- Training window: Jan 10 – Mar 7 (8,058 rows — solid)
- Eval window: Mar 16 – Mar 29 (1,029 rows — healthy for governance)

**Watch in Slack `#deployment-alerts` at ~5:45 AM ET:**
- Expected: "Weekly Retrain Complete — train through 2026-03-07, 3 trained, 0 blocked"
- "TIGHT protection: last TIGHT day 2026-03-13 was Xd ago" in CF logs = expected, not a bug
- If `retrain-reminder` fires at 9 AM ET = 5 AM run failed, check CF logs

**After retrain completes:**
```bash
./bin/model-registry.sh sync    # Update registry
./bin/refresh-model-cache.sh --verify  # Immediate effect (worker auto-refreshes every 4h otherwise)
```

---

## NBA Performance Context

### Season Record: 103-68 (60.2%) — as of March 26
| Bucket | HR% | N |
|---|---|---|
| Edge 5+ | **65.3%** | 123 |
| Edge 3-5 | 45.9% | 48 |
| Ultra OVER | **85.7%** | 21 |

### Monthly Trend — March is bad
| Month | Picks | HR% |
|---|---|---|
| Jan 2026 | 67 | 73.1% |
| Feb 2026 | 48 | 56.3% |
| Mar 2026 | 56 | **48.2%** |

March dragged below break-even by March 7-8 catastrophe (1/19). OVER pick drought since March 12 (15 days, 0 OVER picks).

### Signal Environment
- **Market:** NORMAL (vegas_mae_7d = 5.41 March 27 — improved from 4.84)
- **HOT UNDER signals:** `positive_clv_under` (85.7%), `ft_anomaly_under` (85.7%), `home_under` (66.7%), `downtrend_under` (63.6%)
- **No strong OVER signals** — `high_edge` + `edge_spread_optimal` COLD (2 days, reduces SC)

---

## Pending Items Priority Order

| Priority | Item | When |
|---|---|---|
| 1 | MLB pipeline investigation — why no Opening Day data | Now |
| 2 | NBA picks check for March 28 | Noon ET today |
| 3 | CatBoost 0118 auto-disable watch | 11 AM ET daily |
| 4 | **Monday retrain** — check Slack, run `model-registry.sh sync` | March 30, 5-6 AM ET |
| 5 | New models (`*_train0110_0307`) governance gates | After retrain |
| 6 | Ultra OVER public exposure (need ~29 more picks at N=50) | Ongoing |

---

## Key Commands Reference

```bash
# MLB manual trigger (if cascade still broken)
TOKEN=$(gcloud auth print-identity-token --audiences="https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app")
curl -s -X POST https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"game_date": "2026-03-27"}'

# After Monday retrain
./bin/model-registry.sh sync
./bin/refresh-model-cache.sh --verify

# Fleet state check
bq query --nouse_legacy_sql --project_id=nba-props-platform \
  "SELECT model_id, state, rolling_hr_7d, rolling_n_7d, consecutive_days_below_alert
   FROM nba_predictions.model_performance_daily
   WHERE game_date = CURRENT_DATE()
     AND model_id IN (SELECT model_id FROM nba_predictions.model_registry WHERE enabled = TRUE)
   ORDER BY model_id"
```
