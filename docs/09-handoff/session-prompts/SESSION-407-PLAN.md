# Session 407 Plan — Verify Session 406 Fixes, Shadow Signal Accumulation, Fleet Health

**Created:** 2026-03-05 (Session 406)
**Scope:** Session 407 (Mar 5-6)
**Goal:** Confirm all Session 406 scraper/signal fixes are producing data in BQ, start shadow signal accumulation monitoring, assess pick volume improvement.

---

## Context: What Session 406 Did

Session 406 fixed **3 broken scrapers**, **re-added Playwright** to the Docker image, **lowered combo signal MIN_EDGE** to 3.0, and added **play_probability** extraction to RotoWire. All code is pushed and deployed. **No code changes expected this session** — this is a verification + analysis session.

| Fix | Status | What to verify |
|-----|--------|----------------|
| NumberFire GraphQL schema (`sport: NBA`, `id`) | Deployed, 120 players confirmed in GCS | Data in BQ via Phase 2? |
| VSiN `recursive=False` + `resolve_team` | Deployed, 14 games confirmed in GCS | Data in BQ via Phase 2? |
| NBA Tracking proxy support | Deployed, 546 players confirmed in BQ | Ongoing daily data? |
| Playwright for FP/Dimers | Deployed (build succeeded) | Full player count (>10 FP, >20 Dimers)? |
| combo_3way/combo_he_ms MIN_EDGE 3.0 | Deployed | Signals actually firing? |
| RotoWire play_probability | Deployed | play_probability in BQ? |
| DVP rank computation (Session 405) | Deployed | dvp_favorable_over firing? |

**Algorithm version:** `v406_scraper_fixes_combo_edge3`

---

## Step 1: Run Daily Steering + Validate Pipeline (5 min)

```bash
/daily-steering
/validate-daily
```

Get the lay of the land — model health, signal health, pick volume, any pipeline issues.

---

## Step 2: Verify All Scraper Data in BQ (10 min)

**Critical check:** Session 406 scrapers published to GCS with potentially non-standard names (`number_fire_projections_scraper` instead of `numberfire_projections_scraper`). Phase 2 might not recognize them.

```sql
-- 2a. All 10 scraper sources — today's data?
SELECT 'numberfire' as src, game_date, COUNT(*) as cnt FROM nba_raw.numberfire_projections WHERE game_date >= '2026-03-05' GROUP BY 1,2
UNION ALL SELECT 'fantasypros', game_date, COUNT(*) FROM nba_raw.fantasypros_projections WHERE game_date >= '2026-03-05' GROUP BY 1,2
UNION ALL SELECT 'dimers', game_date, COUNT(*) FROM nba_raw.dimers_projections WHERE game_date >= '2026-03-05' GROUP BY 1,2
UNION ALL SELECT 'vsin', game_date, COUNT(*) FROM nba_raw.vsin_betting_splits WHERE game_date >= '2026-03-05' GROUP BY 1,2
UNION ALL SELECT 'nba_tracking', game_date, COUNT(*) FROM nba_raw.nba_tracking_stats WHERE game_date >= '2026-03-05' GROUP BY 1,2
UNION ALL SELECT 'teamrankings', game_date, COUNT(*) FROM nba_raw.teamrankings_pace WHERE game_date >= '2026-03-05' GROUP BY 1,2
UNION ALL SELECT 'hashtag_dvp', game_date, COUNT(*) FROM nba_raw.hashtagbasketball_dvp WHERE game_date >= '2026-03-05' GROUP BY 1,2
UNION ALL SELECT 'rotowire', game_date, COUNT(*) FROM nba_raw.rotowire_lineups WHERE game_date >= '2026-03-05' GROUP BY 1,2
UNION ALL SELECT 'covers_ref', game_date, COUNT(*) FROM nba_raw.covers_referee_stats WHERE game_date >= '2026-03-05' GROUP BY 1,2
ORDER BY src, game_date DESC

-- 2b. NumberFire specifically — should be 120+ players (was 0 before fix)
SELECT game_date, COUNT(*) as players, MIN(projected_points) as min_pts, MAX(projected_points) as max_pts
FROM nba_raw.numberfire_projections
WHERE game_date >= '2026-03-04'
GROUP BY 1 ORDER BY 1 DESC

-- 2c. VSiN specifically — should be 14 games (was 0 before fix)
SELECT game_date, COUNT(*) as games
FROM nba_raw.vsin_betting_splits
WHERE game_date >= '2026-03-04'
GROUP BY 1 ORDER BY 1 DESC

-- 2d. FantasyPros — did Playwright increase from 10 to more?
SELECT game_date, COUNT(*) as players, MIN(projected_points) as min_pts, MAX(projected_points) as max_pts
FROM nba_raw.fantasypros_projections
WHERE game_date >= '2026-03-04' AND projected_points BETWEEN 5 AND 60
GROUP BY 1 ORDER BY 1 DESC

-- 2e. Dimers — did Playwright help with PTS data?
SELECT game_date, COUNT(*) as players, COUNTIF(projected_points IS NOT NULL) as has_pts
FROM nba_raw.dimers_projections
WHERE game_date >= '2026-03-04'
GROUP BY 1 ORDER BY 1 DESC

-- 2f. RotoWire play_probability — new field
SELECT game_date, COUNT(*) as players, COUNTIF(play_probability IS NOT NULL) as has_play_prob
FROM nba_raw.rotowire_lineups
WHERE game_date >= '2026-03-04'
GROUP BY 1 ORDER BY 1 DESC
```

**If NumberFire/VSiN empty in BQ:** Phase 2 routing issue. Check:
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase2-raw-processors" AND (textPayload=~"numberfire" OR textPayload=~"number_fire" OR textPayload=~"vsin" OR textPayload=~"v_si_n")' --limit=20 --format='table(timestamp,textPayload)' --project=nba-props-platform
```

**If routing is the issue:** Fix the Phase 2 processor name mapping or the scraper's Pub/Sub message scraper_name field to match what Phase 2 expects. Check `data_processors/raw/` for the processor registry.

---

## Step 3: Verify Shadow Signals Firing (10 min)

**This is the money check.** Session 406 unblocked projection_consensus, sharp_money, and dvp_favorable. Combo signals lowered to edge 3.0.

```sql
-- 3a. All shadow signal fires today
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags
CROSS JOIN UNNEST(signal_tags) AS signal_tag
WHERE signal_tag IN (
  'projection_consensus_over', 'projection_consensus_under',
  'predicted_pace_over', 'dvp_favorable_over',
  'sharp_money_over', 'sharp_money_under',
  'minutes_surge_over',
  'positive_clv_over', 'positive_clv_under',
  'combo_3way', 'combo_he_ms',
  'q4_scorer_over', 'self_creation_over',
  'public_fade_filter', 'projection_disagreement', 'negative_clv_filter'
)
AND game_date >= '2026-03-05'
GROUP BY 1 ORDER BY fires DESC

-- 3b. Signal firing history (should see new signals appear for first time)
SELECT game_date, signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags
CROSS JOIN UNNEST(signal_tags) AS signal_tag
WHERE signal_tag IN (
  'projection_consensus_over', 'projection_consensus_under',
  'sharp_money_over', 'sharp_money_under',
  'dvp_favorable_over', 'combo_3way', 'combo_he_ms'
)
AND game_date >= '2026-03-03'
GROUP BY 1, 2 ORDER BY game_date DESC, fires DESC
```

**Expected signals to fire for first time:**
| Signal | Expected | Dependency |
|--------|----------|------------|
| `projection_consensus_over` | 5-15/day | NumberFire + Dimers/FP (2+ sources) |
| `projection_consensus_under` | 3-8/day | NumberFire + Dimers/FP (2+ sources) |
| `sharp_money_over` | 1-4/day | VSiN data |
| `sharp_money_under` | 1-3/day | VSiN data |
| `dvp_favorable_over` | 1-2/day | DVP rank computation fix |
| `combo_3way` | 0-1/day | Edge 3+ OVER + minutes surge + ESO |
| `combo_he_ms` | 0-2/day | Edge 3+ OVER + minutes surge |

**If projection_consensus NOT firing:**
1. Check if NumberFire data reached the supplemental_data query
2. Check `ml/signals/supplemental_data.py` — is it querying BQ correctly?
3. Check `ml/signals/projection_consensus.py` — MIN_SOURCES_ABOVE threshold
4. Check player_lookup format matching between projections and predictions

**If sharp_money NOT firing:**
1. Check if VSiN data is in BQ
2. Check `ml/signals/sharp_money.py` — handle/ticket divergence thresholds
3. Check join logic between VSiN (team-level) and predictions (player-level)

**If combo signals NOT firing:**
1. Check how many OVER predictions have edge >= 3.0 today
2. Check minutes_surge data availability (note: minutes_surge_over is PERMANENTLY BLOCKED because RotoWire has no minutes data)
3. If minutes surge is the bottleneck, combo signals will remain rare (this is expected)

---

## Step 4: Check Pick Volume + Grade Recent Picks (10 min)

**Key metric:** Was 2 picks/day. Should improve with new signals.

```sql
-- 4a. Best bets pick volume trend
SELECT game_date, COUNT(*) as picks,
  COUNTIF(recommendation = 'OVER') as over_picks,
  COUNTIF(recommendation = 'UNDER') as under_picks,
  ROUND(AVG(real_signal_count), 1) as avg_real_sc,
  COUNTIF(signal_rescued) as rescued
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-01'
GROUP BY 1 ORDER BY 1 DESC

-- 4b. Grade today/yesterday
SELECT bb.game_date, bb.player_lookup, bb.recommendation,
  ROUND(ABS(bb.predicted_points - bb.line_value), 1) as edge,
  bb.system_id, bb.real_signal_count,
  bb.signal_rescued, bb.rescue_signal,
  pa.prediction_correct as hit, pa.actual_points, bb.line_value,
  ARRAY_TO_STRING(bb.signal_tags, ', ') as signals
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date >= '2026-03-04'
ORDER BY bb.game_date DESC, bb.composite_score DESC

-- 4c. Best bets filter audit — what's getting rejected?
SELECT game_date, total_candidates, passed_filters, algorithm_version
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-04'
ORDER BY game_date DESC
```

---

## Step 5: Shadow Signal Accumulation Baseline (5 min)

Set the baseline for the Phase 2 monitoring period (per SESSION-405-PLAN Phase 2).

```sql
-- 5a. Current shadow signal cumulative data
SELECT signal_tag,
  COUNT(*) as total_fires,
  COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr,
  MIN(pst.game_date) as first_fire, MAX(pst.game_date) as last_fire
FROM nba_predictions.pick_signal_tags pst
CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON pst.player_lookup = pa.player_lookup AND pst.game_date = pa.game_date AND pst.system_id = pa.system_id
WHERE signal_tag IN (
  'projection_consensus_over', 'projection_consensus_under',
  'predicted_pace_over', 'dvp_favorable_over',
  'sharp_money_over', 'sharp_money_under',
  'positive_clv_over', 'positive_clv_under',
  'combo_3way', 'combo_he_ms',
  'q4_scorer_over', 'self_creation_over'
)
GROUP BY 1 ORDER BY total_fires DESC
```

**Track this weekly** until N=30 for each signal (promotion/disable decision point).

---

## Step 6: Fleet Health + Model Performance (10 min)

```sql
-- 6a. Model fleet best bets contribution
SELECT bb.system_id,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date >= '2026-02-20'
GROUP BY 1 HAVING COUNTIF(pa.prediction_correct IS NOT NULL) >= 3
ORDER BY hr DESC

-- 6b. Edge 3+ performance by model (last 14 days)
SELECT system_id,
  COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_total,
  COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge3_wins,
  ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) /
    NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND has_prop_line = TRUE AND prediction_correct IS NOT NULL
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY 1
HAVING edge3_total >= 10
ORDER BY edge3_hr DESC

-- 6c. Decay state check
SELECT model_id, decay_state, consecutive_days_below, rolling_hr_7d, rolling_hr_14d, brier_score_14d
FROM nba_predictions.model_performance_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.model_performance_daily)
ORDER BY decay_state DESC, rolling_hr_14d ASC
```

**Action items:**
- Any model DEGRADING/BLOCKED → investigate with `bin/deactivate_model.py MODEL_ID --dry-run`
- Any model < 45% HR on 20+ best bets picks → disable candidate
- Session 405 retrained models (`catboost_v12_noveg_train0107_0219`, `xgb_v12_noveg_train0107_0219`) → check initial performance

---

## Step 7: Deployment Drift Check (3 min)

```bash
./bin/check-deployment-drift.sh --verbose
```

Multiple pushes in Session 406 — verify all services are at HEAD.

---

## Step 8: Fix Any Phase 2 Routing Issues (if needed, 15 min)

If Step 2 shows NumberFire/VSiN data NOT in BQ despite being in GCS:

1. Check `data_processors/raw/` for the processor registry that maps scraper names to processors
2. Fix the scraper's `scraper_name` property to match what Phase 2 expects
3. OR fix the Phase 2 routing to accept the new names
4. Manually trigger Phase 2 for the missing data

```bash
# Check GCS to confirm data is there
gsutil ls gs://nba-scraped-data/projections/numberfire/2026-03-05/ 2>/dev/null
gsutil ls gs://nba-scraped-data/external/vsin/2026-03-05/ 2>/dev/null
```

---

## Step 9: Signal Rescue Validation Check (5 min)

Signal rescue has been live since Session 398 (~1 week). Check if we have enough data for initial validation.

```sql
-- 9a. Signal rescue cumulative performance
SELECT
  rescue_signal,
  COUNT(*) as total,
  COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.signal_rescued = TRUE
GROUP BY 1 ORDER BY total DESC
```

**If N >= 15:** Start evaluating which rescue signals are performing.

---

## Decision Tree

```
Start
  ├─ /daily-steering → health overview
  ├─ Step 2: Scraper data in BQ?
  │   ├─ YES → Continue to Step 3
  │   └─ NO → Step 8 (fix Phase 2 routing) → re-trigger scrapers
  ├─ Step 3: Shadow signals firing?
  │   ├─ YES → Record baseline (Step 5), continue monitoring
  │   └─ NO → Debug signal code (check supplemental_data, signal thresholds)
  ├─ Step 4: Pick volume improved?
  │   ├─ 4+ picks/day → Great, monitor quality
  │   ├─ 2-3 picks/day → Expected if signals just started, need accumulation
  │   └─ 0-1 picks/day → Something still broken, investigate edge compression
  └─ Step 6: Fleet healthy?
      ├─ All HEALTHY → Continue accumulation
      └─ Any DEGRADING/BLOCKED → Investigate, possible disable
```

---

## Don't Do

- Don't lower edge floors below 3.0 (25% HR below edge 3 in best bets)
- Don't promote shadow signals to rescue yet — need N >= 15 graded (per SESSION-405-PLAN Phase 3)
- Don't retrain models — 12 in fleet, focus on evaluation
- Don't add features to models (77+ dead ends)
- Don't try to fix `minutes_surge_over` — RotoWire has no minutes data (permanently blocked)
- Don't re-add DFF to projection consensus — it's DFS FPTS, not NBA points
- Don't change signal thresholds without data — wait for N=30

---

## Success Criteria for This Session

| Metric | Pass | Fail |
|--------|------|------|
| NumberFire data in BQ | 100+ players | 0 players |
| VSiN data in BQ | 10+ games | 0 games |
| projection_consensus signal firing | 1+ fires | 0 fires |
| sharp_money signal firing | 1+ fires | 0 fires |
| Pick volume | >= 2/day (maintained) | < 2/day (regression) |
| No deployment drift | All services at HEAD | Services behind |
| Builds green | Latest build SUCCESS | Build FAILURE |

---

## Forward Look (Phases 2-8 from SESSION-405-PLAN)

This session covers Phase 1 verification + Phase 2 baseline. The remaining phases:

- **Phase 2 (Mar 5-12):** Daily shadow signal monitoring, accumulate N=30
- **Phase 3 (Mar 10-14):** First promotion window — signals with N >= 30 get promote/disable decisions
- **Phase 4 (Mar 12-20):** Threshold experiments (SQL-only, no code changes)
- **Phase 5 (Mar 15-20):** Signal combination discovery
- **Phase 6 (Mar 20-25):** Model fleet cleanup — disable underperformers
- **Phase 7 (ongoing):** Pick volume optimization
- **Phase 8 (Mar 25+):** Advanced experiments (Brier-weighted selection, dynamic edge floors)

**Key target:** 4-8 picks/day at 58%+ HR by end of March.
