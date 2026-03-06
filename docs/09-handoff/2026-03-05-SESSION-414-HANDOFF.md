# Session 414 Handoff — Grading Prep, Daily Ops, Scraper Deploy

**Date:** 2026-03-05
**Type:** Operations, monitoring, deployment
**Key Insight:** Mar 5 games haven't played yet (all status=1), so grading deferred. Duplicate filter already removed in ed351d84. Scraper deployment in progress.

---

## What This Session Did

### 1. Attempted Mar 5 Grading — Games Not Yet Played
All 9 Mar 5 games are still `game_status=1` (Scheduled). Grading queries are ready — run tomorrow morning.

### 2. Daily Steering Report
| Metric | Value | Status |
|--------|-------|--------|
| Fleet | 4 HEALTHY, 1 WATCH, 2 DEGRADING, 19 BLOCKED | Auto-disabled |
| Market compression | 1.000 (was 0.596) | Stabilized (30d normalized) |
| 7d avg max edge | 6.4 | YELLOW (below 7.0) |
| BB HR 7d / 14d / 30d | 46.7% / 55.6% / 53.8% | 7d YELLOW |
| OVER 14d / UNDER 14d | 50.0% / 66.7% | UNDER carrying |
| Signal rescue | 3-3 (50%) N=6 | Too early |
| 3d rolling HR | 42.9% (N=7) | RED |
| Residual bias | -0.59 pts | OK (slight underprediction) |

**Market compression ratio jumped 0.596 → 1.000** — NOT an improvement. The 30d window now fully includes post-ASB data, so denominator dropped to match 7d. Actual edge magnitude (6.4) is stable but low.

### 3. Duplicate Spread Filter Cleanup — Already Done
The post-scored `high_spread_over_would_block` duplicate (L931-950) was already removed in commit `ed351d84` (latest on main). BQ confirmed double-counting: 6 filtered_picks rows for 3 players (Booker, Allen, Santos × 2 each). Now fixed.

### 4. Pipeline Validation
| Check | Status | Details |
|-------|--------|---------|
| Deployment drift | 1 stale | `nba-scrapers` at 69d06c97 (5 behind) |
| Phase 3 | OK | same_day mode, 1/1 complete, triggered |
| Feature store | OK | 148 features, 9 games, 69.6% quality-ready |
| Predictions | OK | 1,313 active across 9 games |
| Best bets | OK | 12 picks (8 OVER, 4 UNDER) |
| Scheduler | 4 failing | monitoring functions, not critical |

### 5. Scraper Deployment (IN PROGRESS)
`nba-scrapers` service deployment started — was 5 commits behind (69d06c97 → ed351d84). Missing: TeamRankings fix, worker NoneType fix, Playwright fixes. Deploy building when session ended.

**IMPORTANT:** Check if deploy completed:
```bash
gcloud run services describe nba-scrapers --region=us-west2 --format="value(metadata.labels.commit-sha)"
# Expected: ed351d84
```

If not deployed, re-run:
```bash
./bin/deploy-service.sh nba-scrapers
```

---

## Tonight's Picks (Mar 5 — 12 picks)

| Player | Dir | Line | Edge | Rescued | Key Signals |
|--------|-----|------|------|---------|-------------|
| Devin Booker | OVER | 24.5 | 5.0 | No | line_rising, self_creation, usage_surge |
| Tre Johnson | OVER | 13.5 | 4.8 | Yes (HSE) | scoring_cold_streak, HSE, consistent_scorer |
| Grayson Allen | OVER | 17.5 | 4.4 | Yes (stack) | consistent_scorer, usage_surge |
| Bilal Coulibaly | OVER | 12.5 | 4.1 | Yes (HSE) | ft_rate_bench, HSE, over_trend |
| Scottie Barnes | OVER | 17.5 | 3.9 | Yes (stack) | line_rising, consistent_scorer |
| Gui Santos | OVER | 12.5 | 3.8 | Yes (combo) | combo_he_ms, combo_3way |
| Nolan Traore | OVER | 11.5 | 3.3 | Yes (combo) | combo_he_ms, combo_3way, low_line |
| Cody Williams | OVER | 8.5 | 3.3 | Yes (HSE) | b2b_boost, HSE, low_line, dvp_favorable |
| Tyler Herro | UNDER | 21.5 | 4.2 | No | home_under, starter_under, blowout_risk |
| Austin Reaves | UNDER | 19.5 | 4.0 | No | starter_under, blowout_risk |
| Kevin Durant | UNDER | 25.5 | 3.7 | No | home_under, projection_consensus |
| Jalen Duren | UNDER | 18.5 | 3.0 | No | starter_under, projection_consensus, blowout_risk |

**Changes vs yesterday's picks:**
- 3 new picks: Nolan Traore (OVER, combo rescued), Tyler Herro (UNDER), Kevin Durant (UNDER)
- Herro and KD were blocked by `flat_trend_under` yesterday but now pass — lines shifted
- 7/8 OVER picks are rescued (88%)
- `day_of_week_over` and `predicted_pace_over` firing on ALL OVER picks (Thursday)

---

## Signal Rescue Performance (14d cumulative)

| Signal | Dir | W-L | HR | Avg Edge |
|--------|-----|-----|----|----------|
| combo_he_ms | OVER | 1-1 | 50% | 3.9 |
| high_scoring_environment | OVER | 1-0 | 100% | 3.7 |
| low_line_over | OVER | 0-1 | 0% | 4.0 |
| sharp_book_lean_over | OVER | 1-0 | 100% | 3.9 |
| signal_stack_2plus | OVER | 0-1 | 0% | 3.1 |
| **TOTAL RESCUED** | | **3-3** | **50%** | |
| **TOTAL NORMAL** | | **14-11** | **56%** | |

Rescue is -6pp vs normal at N=6. `low_line_over` and `signal_stack_2plus` are weakest. Still too early to act.

---

## Next Session — Priority Tasks

### 1. Grade Mar 5 Results (FIRST THING)
Run these queries to grade last night's picks:

```sql
-- 1. How did the 12 active picks do?
SELECT b.player_lookup, b.recommendation, b.line_value,
  pa.actual_points, pa.prediction_correct, b.signal_rescued, b.rescue_signal
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON b.player_lookup = pa.player_lookup AND b.game_date = pa.game_date AND b.system_id = pa.system_id
WHERE b.game_date = '2026-03-05'
ORDER BY b.recommendation, b.player_lookup;

-- 2. Counterfactual: would blocked/flagged picks have won?
SELECT fp.filter_reason, fp.player_lookup, fp.recommendation, fp.edge,
  pa.actual_points, pa.prediction_correct
FROM `nba-props-platform.nba_predictions.best_bets_filtered_picks` fp
LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON fp.player_lookup = pa.player_lookup AND fp.game_date = pa.game_date AND fp.system_id = pa.system_id
WHERE fp.game_date = '2026-03-05'
  AND fp.filter_reason IN ('flat_trend_under', 'high_spread_over_would_block',
                           'regime_rescue_blocked', 'regime_over_floor',
                           'mid_line_over_obs', 'monday_over_obs', 'home_over_obs')
ORDER BY fp.filter_reason;

-- 3. Signal rescue cumulative HR (should now have N=12+)
SELECT signal_rescued, COUNT(*) as total,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) as hr
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON b.player_lookup = pa.player_lookup AND b.game_date = pa.game_date AND b.system_id = pa.system_id
WHERE b.game_date >= '2026-01-01' AND pa.prediction_correct IS NOT NULL
GROUP BY 1;
```

**Key questions from grading:**
- Did the 7 rescued OVER picks win? (50% HR at N=6 prior)
- Did spread-flagged picks lose? (Booker/Allen spread 10.5, Santos 8.5)
- Did Herro/KD UNDER hit? (newly passing flat_trend today with higher lines)
- Did combo signals (Santos, Traore) perform? Both have combo_he_ms + combo_3way
- Signal rescue cumulative should hit N=13+ — if HR stays below 55%, plan tightening

### 2. Verify Scraper Deployment
```bash
gcloud run services describe nba-scrapers --region=us-west2 --format="value(metadata.labels.commit-sha)"
# Expected: ed351d84
```
If not complete, re-deploy: `./bin/deploy-service.sh nba-scrapers`

### 3. Signal Rescue Evaluation (~Mar 10-15, N=15-20)
If rescue HR stays below 55% at N=15+:
- Consider raising `signal_stack_2plus` from 2+ to 3+ real signals
- Consider removing `low_line_over` from rescue set (0-1 historically)
- Evaluate `high_scoring_environment_over` separately (most common rescue)

### 4. 4 Failing Scheduler Jobs
Not critical but should investigate:
- `morning-deployment-check`: INTERNAL
- `analytics-quality-check-morning`: INTERNAL
- `monthly-retrain-job`: INTERNAL
- `self-heal-predictions`: DEADLINE_EXCEEDED

### 5. Monitor 7d HR Trend
7d BB HR at 46.7% (below breakeven). Two bad days in a row (Feb 28 40%, Mar 4 42.9%). If stays below 50% through Mar 8, consider reducing pick count. Autocorrelation (r=0.43) suggests next day after bad should average 53.9%.

---

## Model Health Summary

| State | Count | Top Models |
|-------|-------|------------|
| HEALTHY | 4 | lgbm_v12_noveg (71.4%), cb_v12_noveg_60d (66.7%), cb_v16_noveg (61.5%) |
| WATCH | 1 | cb_v12_noveg_tw_vw025 (57.1%) |
| DEGRADING | 2 | lgbm_v12_noveg_1102 (54.2%), cb_v12_noveg_0110 (53.3%) |
| BLOCKED | 19+ | Auto-disabled by decay_detection |

---

## Commits This Session

None — all changes were already in latest commit `ed351d84`.

---

## Known Issues

- **Scraper deployment in progress** — may need verification next session
- **4 scheduler jobs failing** — monitoring functions, not pipeline-critical
- **7d BB HR 46.7%** — below breakeven, monitoring
- **Signal rescue 50% HR** — 6pp below normal picks, N=6 too small to act
