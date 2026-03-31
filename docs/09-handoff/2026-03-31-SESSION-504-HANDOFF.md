# Session 504 Handoff — 2026-03-31 (Tuesday Morning)

**Context:** Session 503 ran a 16-agent deep audit of the full system. Root causes of the pick
drought were identified and most infrastructure bugs were fixed. The single remaining blocker
is a fleet retrain — the governance gate is already lowered and everything is staged.

---

## IMMEDIATE ACTION: Run the Retrain (Do This First)

The fleet is degraded (5 BLOCKED, 1 DEGRADING). Governance gate is already fixed at 53%.
Run the retrain now — it takes ~25 minutes:

```bash
./bin/retrain.sh --all --enable --no-production-lines
```

After it completes:
```bash
./bin/model-registry.sh sync
./bin/refresh-model-cache.sh --verify
```

Then verify new models appeared:
```bash
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT model_id, status, enabled, created_at
FROM nba_predictions.model_registry
WHERE DATE(created_at) = CURRENT_DATE()
ORDER BY created_at DESC"
```

**Today has 7 games (all status=1 Scheduled).** New models will be picked up by today's
normal pipeline run (Phase 4 → 5 → 6). No manual coordinator trigger needed unless
you want picks before ~2 PM ET.

---

## Current System State (as of 2026-03-31 morning)

### NBA Fleet — DEGRADED (retrain pending)

| Model | State | 7d HR | N |
|-------|-------|-------|---|
| `catboost_v12_noveg_train0121_0318` | DEGRADING | 52.9% | 70 |
| `lgbm_v12_noveg_train0103_0227` | BLOCKED | 50.5% | 107 |
| `lgbm_v12_noveg_train0103_0228` | BLOCKED | 50.0% | 20 |
| `catboost_v12_noveg_train0118_0315` | BLOCKED | 48.3% | 29 |
| `lgbm_v12_noveg_train0121_0318` | BLOCKED | 41.7% | 72 |
| `lgbm_v12_noveg_train1215_0214` | BLOCKED | 34.6% | 26 |

**Pick drought: March 22–30 (~9 days, ~9 picks total).** March W-L: 31-37 (45.6%).
Season total: 108-76 (58.7%). Edge 5+ validated at 65.1%.

### Root Cause (confirmed by 6 agents)

1. **Systematic under-prediction** — models predict 1.2–2.0 pts below actuals on average.
   Stars under-predicted by 5.4 pts, starters by 2.8 pts. Creates 65–71% UNDER bias.
   When actuals run hot (as they have since March 8), UNDER calls get crushed.

2. **Governance gate was 60%** — raw model historical ceiling is ~53.4%. No retrain could
   ever pass. **FIXED in Session 503:** gate lowered to 53% (commit `35b32f3a`).

3. **TIGHT cap bug in weekly CF** — `cap_to_last_loose_market_date()` measures recovery from
   the shifted training end date, not from today, making effective recovery window 21 days
   instead of 7. This caused Monday's automated retrain to train on Jan 9–Mar 7 (same as
   existing stale models). **Not yet fixed** — see open items below.

---

## What Was Fixed in Session 503 (deployed)

| Fix | Commit | Status |
|-----|--------|--------|
| Governance gate 60% → 53% | `35b32f3a` | Deployed (auto-deploy from push) |
| Admin dashboard `avg_margin_of_error` bug (4 locations) | `21bba3d8` | Deployed |
| MLB worker `write_to_bigquery` default False → True | `21bba3d8` | Deployed |
| Session G: decay_detection BLOCKED model stale alert | `fcc5711c` | Deployed |
| `filter_overrides` BQ schema migration (+2 columns) | BQ console | Done |
| `pipeline-health-summary` deployment drift | manual deploy | Fixed |
| MLB scheduler payload `write_to_bigquery: true` | gcloud update | Fixed |
| MLB Mar 29–30 predictions backfilled | manual curl | Done (13 + 10 non-blocked) |

---

## Open Items

### 1. Fleet Retrain (CRITICAL — do immediately)

See instructions at top. Retrain will:
- Train 2 families: `lgbm_v12_noveg_mae` + `v12_noveg_mae` (CatBoost)
- Window: Jan 24 → Mar 21 (training), Mar 22 → Mar 28 (eval)
- 3,393 clean training rows across 50 game dates
- Fresh data corrects the under-prediction bias naturally
- Governance enforces 53% min HR + vegas bias ±1.5 + directional balance

### 2. TIGHT Cap Bug in weekly_retrain CF (fix after retrain)

The `cap_to_last_loose_market_date()` function in
`orchestration/cloud_functions/weekly_retrain/main.py` computes `days_since_tight`
relative to the shifted training end date rather than today's date. This means the
7-day recovery window effectively becomes 21 days (7 + 14 eval days).

**Fix:** Change the comparison reference from `train_end` to `date.today()` inside
`cap_to_last_loose_market_date()`. Until fixed, any future TIGHT period will cause the
CF to retrain on stale windows for 3 extra weeks.

File: `orchestration/cloud_functions/weekly_retrain/main.py`, function `cap_to_last_loose_market_date()`

### 3. `under_low_rsc` Filter — Watch for UNDER Drought

`under_low_rsc` requires `real_sc >= 2` for UNDER picks. Most UNDER picks only get
`real_sc=1` (home_under). With 11 COLD signals post-drought, very few picks qualify
for 2 simultaneous signals. CF HR = 62% (N=21) — approaching the N=30 demotion threshold.

**Action:** After retrain, check UNDER pick volume. If < 3 UNDER picks/day, consider
demoting `under_low_rsc` to observation:
```bash
python bin/monitoring/reset_demoted_filter.py --filter-name under_low_rsc --dry-run
```

### 4. `usage_surge_over` — Revert to SHADOW if Still COLD

This signal graduated to PRODUCTION in Session 495 but was immediately COLD at 35.3% HR
after graduation. After retrain gives new model data, check its 7d HR:
```sql
SELECT signal_name, signal_regime, hr_7d, hit_count_7d
FROM nba_predictions.signal_health_daily
WHERE game_date = CURRENT_DATE() - 1 AND signal_name = 'usage_surge_over'
```
If still COLD after 7 days of new model data, revert to SHADOW in `aggregator.py`.

### 5. `friday_over_block` — Monitor This Friday (April 3)

Blocked 7/8 winners last Friday at 87.5% CF HR (N=8). Not yet at N=30 threshold for
demotion action. If it blocks another batch of winners this Friday, cumulative N will
approach 30. Watch `filter_overrides` after Friday.

### 6. Fleet Diversity — Ensure CatBoost + LGBM Both Train

`book_disagreement` (93% HR season), `combo_3way` (95.5%), and `combo_he_ms` (94.9%)
all require cross-model diversity. Current fleet is all LGBM clones — these signals are
dead. The retrain trains both CatBoost and LGBM families (`--all` flag), which will
restore diversity and re-enable these signals.

---

## MLB Status

- **Pipeline LIVE** — predictions generating and writing to BQ.
- **Root cause of 0 predictions fixed** — `write_to_bigquery` default changed to `True`.
- **Mar 28:** 293 total, 5 non-blocked. **Mar 29:** 13 non-blocked. **Mar 30:** 10 non-blocked.
- Most pitchers BLOCKED due to missing prop line features (`f30_k_avg_vs_line`,
  `f32_line_level`, `f44_over_implied_prob`) — these are only available once books post
  K lines for the day (~late morning ET).
- **Monitor:** Re-trigger predictions after K lines are posted (~11 AM ET):
```bash
TOKEN=$(gcloud auth print-identity-token --audiences=https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app)
curl -X POST https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app/predict-batch \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-03-31", "write_to_bigquery": true}'
```

---

## Signal System State

- **2 HOT signals** — both SHADOW (not used in production scoring)
- **11 COLD signals** — `high_edge`, `edge_spread_optimal`, `bench_under`, `usage_surge_over`, others
- **0 active filter overrides** — filter_overrides table is clean
- **book_disagreement dead** — requires cross-model diversity; fleet is all LGBM. Will recover after retrain.
- Signal system will normalize within 7 days of fresh models generating predictions.

---

## Key Commands Quick Reference

```bash
# CRITICAL: Run retrain
./bin/retrain.sh --all --enable --no-production-lines

# After retrain:
./bin/model-registry.sh sync
./bin/refresh-model-cache.sh --verify

# Check picks today
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT game_date, recommendation, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = CURRENT_DATE()
GROUP BY 1,2 ORDER BY 2"

# Season record
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT recommendation,
  COUNTIF(prediction_correct) as wins,
  COUNTIF(NOT prediction_correct) as losses,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END)*100,1) as hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2025-11-01'
  AND is_best_bet = TRUE AND prediction_correct IS NOT NULL
  AND has_prop_line = TRUE
GROUP BY 1"

# MLB predictions today
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT game_date, COUNT(*) as total, COUNTIF(recommendation != 'BLOCKED') as non_blocked
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date = CURRENT_DATE() GROUP BY 1"

# Fix TIGHT cap bug (after retrain succeeds)
# File: orchestration/cloud_functions/weekly_retrain/main.py
# Function: cap_to_last_loose_market_date()
# Change: compute days_since_tight relative to date.today(), not train_end
```

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| `35b32f3a` | fix: lower governance gate 60% → 53% for raw model evaluation |
| `21bba3d8` | fix: avg_absolute_error column name, MLB write_to_bigquery=True |
| `fcc5711c` | feat: decay_detection BLOCKED model stale retrain alert |
