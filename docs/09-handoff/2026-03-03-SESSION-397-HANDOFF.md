# Session 397 Handoff — Shadow Fleet Deployment + Q4 Scoring Signal + SC Architecture Refactor

**Date:** 2026-03-03 (evening)
**Status:** 3 deployments pushed, 3 new shadow models registered, Q4 scoring filter live, SC architecture refactored

---

## What Was Done

### 1. Session 396 Code Deployed
- Pushed: `b2b_boost_over` signal, `rest_advantage_2d` disabled, NBA.com PBP `record_count` fix
- Cloud Build triggered, auto-deploying to all services

### 2. Shadow Fleet Expanded (3 New Models)
Uploaded to GCS + registered in `model_registry` + worker cache refreshed.

| Model ID | Framework | HR 3+ | N | Status |
|----------|-----------|-------|---|--------|
| `xgb_v12_noveg_s42_train1215_0208` | XGBoost | 71.7% | 46 | shadow, enabled |
| `xgb_v12_noveg_s999_train1215_0208` | XGBoost | 69.6% | 46 | shadow, enabled |
| `lgbm_v12_noveg_vw015_train1215_0208` | LightGBM | 66.7% | 63 | shadow, enabled |

XGBoost already supported in worker (pinned at 3.1.2). No additional code changes needed.

### 3. Experiments Run

| Config | HR 3+ | N | Verdict |
|--------|-------|---|---------|
| XGBoost + V13 features (A3) | 63.64% | 33 | Dead end — vegas leaks through V13 features |
| XGBoost + vegas=0.15 | 71.74% | 46 | Identical to vw025 — XGBoost insensitive to vegas weight |

**Key learning:** XGBoost V12_noveg is the sweet spot. V13 features hurt XGBoost. Vegas weight doesn't matter for XGBoost (unlike CatBoost/LightGBM where 0.15-0.25 is optimal).

### 4. Q4 Scoring Ratio — UNDER Block + OVER Signal (DEPLOYED)

Built from BigDataBall play-by-play data (402K+ rows):

| Q4 Ratio | OVER HR | OVER N | UNDER HR | UNDER N |
|----------|---------|--------|----------|---------|
| 35%+ | 64.4% | 292 | **34.0%** | 359 |
| 30-35% | 62.4% | - | 50.9% | 340 |
| <30% | 63.3% | - | 50.3% | - |

**Implemented:**
- **Filter:** `q4_scorer_under_block` in aggregator — blocks UNDER when Q4 ratio >= 0.35 (34.0% HR, N=359)
- **Signal:** `q4_scorer_over` — fires on Q4 ratio >= 0.35 + OVER (64.4% HR)
- **Data pipeline:** Separate BQ query in `supplemental_data.py` → rolling 5-game Q4 ratio from BDL PBP → `pred['q4_scoring_ratio']`

### 5. SC Architecture Refactor (DEPLOYED)

**Problem:** Base signals (model_health, high_edge, edge_spread_optimal) fire on ~100% of picks, inflating SC to 3 minimum with zero discriminative power. SC=3 is meaningless — it just means "base signals fired."

**Fix:** Introduced `real_sc` = non-base signal count.
- Unified SC=3 OVER block + signal_density into single `real_sc == 0` check:
  - OVER + real_sc=0: blocked (45.5% HR)
  - UNDER + real_sc=0 + edge<7: blocked (57.1% HR)
  - UNDER + real_sc=0 + edge 7+: allowed (edge bypass)
- Starter OVER now checks `real_sc >= 1` (equivalent to old SC >= 4)
- Added `real_signal_count` to pick output for analytics
- Algorithm version: `v397_q4_scorer_under_block`

### 6. Signal Firing Audit Added to /daily-steering

New Step 2.25 in daily-steering SKILL.md:
- Queries `signal_best_bets_picks` for per-signal firing counts (7d/30d/total)
- Classifies each signal as ACTIVE, DEAD, or NEVER_FIRED
- Documents known silent signals and root causes

### 7. Silent Signals Root Cause Analysis

**Finding:** 7 signals never reach best bets. The handoff from Session 396 attributed this to `signal_density` filter — **this was incorrect**. Real causes:

| Signal | Root Cause |
|--------|-----------|
| `line_rising_over` | Was dead until Session 387 fix — should start firing now |
| `fast_pace_over` | Was dead until Session 387 threshold fix — should start firing now |
| `starter_under` | Picks killed by `starter_v12_under` filter upstream |
| `high_scoring_environment_over` | `implied_team_total >= 120` too narrow |
| `self_creation_over` | `self_creation_rate_last_10` often NULL |
| `sharp_line_move_over` | `dk_line_move_direction` needs both DK snapshots — HIGH nullability |
| `sharp_line_drop_under` | Same DK data issue |

**No code change needed for these** — signal_density wasn't the blocker. `line_rising_over` and `fast_pace_over` should naturally start appearing after Session 387 fixes.

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/q4_scorer_over.py` | NEW — Q4 scorer OVER signal |
| `ml/signals/aggregator.py` | Q4 UNDER block filter + SC refactor (real_sc) |
| `ml/signals/supplemental_data.py` | Q4 ratio BDL PBP query |
| `ml/signals/registry.py` | Register q4_scorer_over |
| `.claude/skills/daily-steering/SKILL.md` | Signal firing audit (Step 2.25) |

---

## Next Session Plan

### Priority 1: Signal Standalone Picks Research

**User directive:** Signals with 75%+ HR should be able to qualify picks for best bets independently, even without model edge. Track their performance daily.

**Research needed:**
1. Query `signal_best_bets_picks` for signals with 75%+ HR:
   - `combo_3way`: 83.3% (N=7, backtest 95.5%)
   - `combo_he_ms`: 83.3% (N=7, backtest 94.9%)
   - `line_rising_over`: 96.6% backtest (0 live — just fixed)
   - `q4_scorer_over`: 64.4% (N=292 raw — below 75% threshold)
   - `low_line_over`: 78.1% backtest
   - `fast_pace_over`: 81.5% backtest (just fixed)

2. **Key question:** Can these signals generate picks that DON'T already come through the model pipeline? Check:
   ```sql
   -- How many picks would standalone signals add that model pipeline misses?
   -- Need to identify players/games where signal fires but no model prediction has edge 3+
   ```

3. **Implementation options:**
   - **Option A:** Add a "signal rescue" path in aggregator — picks blocked by edge floor get rescued if they have a 75%+ signal
   - **Option B:** Create a parallel "signal-only" pick stream alongside model-based best bets
   - **Option C:** Lower the edge floor for picks with high-HR signals (e.g., edge 1+ if signal HR >= 75%)

4. **Monitoring:** Build per-signal rolling 30d HR into daily-steering. Track each signal's current-season and 30d record.

### Priority 2: Monitor New Deployments

1. **Check XGBoost models loading correctly:**
   ```bash
   # Check worker logs for model loading
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND textPayload:xgb_v12_noveg" --limit=20 --format="value(textPayload)" --project=nba-props-platform
   ```

2. **Check Q4 scorer filter firing:**
   ```bash
   # After next game day, check filter audit
   bq query --use_legacy_sql=false "
   SELECT game_date,
     JSON_VALUE(rejected_json, '$.q4_scorer_under_block') as q4_blocked
   FROM \`nba-props-platform.nba_predictions.best_bets_filter_audit\`
   WHERE game_date >= CURRENT_DATE() - 1
   ORDER BY game_date DESC"
   ```

3. **Run daily-steering to verify new signal firing audit section:**
   ```bash
   /daily-steering
   ```

### Priority 3: 3PT Mean Reversion Feature (Session 396 Discovery)

From BDL PBP analysis: cold 3PT shooters → OVER at 57.9%, hot → UNDER at 53.1%.

**Implementation (same pattern as Q4 ratio):**
1. Add rolling 3-game 3PT% query to `supplemental_data.py`
2. Create `cold_shooter_over` signal (3PT% < 30% + OVER)
3. Consider filter: block OVER on hot 3PT shooters (48.4% HR)

```sql
-- BQ query for 3PT mean reversion
WITH player_game_3pt AS (
  SELECT
    REGEXP_REPLACE(player_1_lookup, r'^[0-9]+', '') as player_lookup,
    game_date,
    SAFE_DIVIDE(
      SUM(CASE WHEN shot_made = true THEN 1 ELSE 0 END),
      COUNT(*)
    ) as three_pct
  FROM `nba_raw.bigdataball_play_by_play`
  WHERE game_date >= '2025-10-01'
    AND event_type = 'shot' AND shot_distance >= 22
  GROUP BY 1, 2
  HAVING COUNT(*) >= 3  -- minimum 3 three-point attempts
)
```

### Priority 4: Backfill NBA.com PBP from GCS to BQ

The `record_count` fix is deployed. 59 dates of GCS data need reprocessing:
- **Option A:** Manually publish Pub/Sub messages for each date
- **Option B:** Re-run scraper workflow for historical dates

### Priority 5: Per-Signal Performance Monitoring

Build a daily per-signal rolling HR tracker:
1. Query `signal_best_bets_picks` + `prediction_accuracy` for per-signal 7d/14d/30d HR
2. Add to `signal_health_daily` table or create new `signal_performance_daily` table
3. Integrate into `/daily-steering` signal health section
4. Add automatic disable logic: signal drops below 50% HR on 30+ picks → auto-disable

---

## Dead Ends Confirmed This Session

| What | Result | Why |
|------|--------|-----|
| XGBoost + V13 features | 63.64% HR (N=33) | Vegas leaks through V13 shooting features in XGBoost |
| XGBoost + vegas=0.15 | 71.74% (N=46) | Identical to vw025 — XGBoost insensitive to vegas weight |
| Signal_density as blocker of 7 signals | NOT the cause | Root cause is NULL data + narrow thresholds |

## Key Learnings

1. **XGBoost is vegas-weight-insensitive:** vw015 = vw025 = 71.7%. Don't bother testing more weights.
2. **V13 features hurt XGBoost:** Vegas dominates in XGBoost's gradient computation, overwhelming the shooting features.
3. **Q4 scoring ratio from BDL PBP is strong:** 18.4pp spread between High Q4 OVER and UNDER. The 35%+ threshold is catastrophically bad for UNDER (34.0%).
4. **real_sc > 0 is the meaningful SC metric:** Base signals inflate SC by +3 with zero discriminative power. Future SC analysis should use real_sc.
5. **Signal diagnosis was wrong in Session 396:** 7 silent signals fail due to NULL data, not signal_density. Always verify root causes independently.

## Quick Reference Commands

```bash
# Check new models loaded in worker
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND textPayload:xgb_v12" --limit=10 --format="value(textPayload)" --project=nba-props-platform

# Check Q4 scoring ratio data
bq query --use_legacy_sql=false 'SELECT COUNT(DISTINCT player_lookup), AVG(q4_ratio) FROM (SELECT REGEXP_REPLACE(player_1_lookup, r"^[0-9]+", "") as player_lookup, SAFE_DIVIDE(SUM(CASE WHEN period=4 THEN points_scored ELSE 0 END), SUM(points_scored)) as q4_ratio FROM nba_raw.bigdataball_play_by_play WHERE game_date >= "2025-10-01" AND event_type IN ("shot","free throw") AND points_scored > 0 GROUP BY 1, game_date HAVING SUM(points_scored) >= 5)'

# Run signal firing audit manually
bq query --use_legacy_sql=false "SELECT signal_tag, COUNT(*) as fires FROM nba_predictions.signal_best_bets_picks, UNNEST(signal_tags) as signal_tag WHERE game_date >= CURRENT_DATE() - 7 GROUP BY 1 ORDER BY fires DESC"

# Validate model registry
python bin/validation/validate_model_registry.py
```
