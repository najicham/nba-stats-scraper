# Monitoring Checklist

Single source of truth for all pending monitoring items, deferred decisions, and "check back later" tasks. Review at the start of each session via `/daily-steering` or manually.

**How to use:**
- Items are sorted by check date
- When an item is resolved, move it to the RESOLVED section at the bottom with the outcome
- When new items arise from a session, add them here (not just in the handoff doc)
- Each item has: what to check, when, the query/command, and the decision criteria

---

## ACTIVE ITEMS

### Due: Mar 6-8 (Immediate)

#### 1. Verify pick locking deployed correctly
**Added:** Session 412 (Mar 5) | **Type:** Deployment verification
```sql
-- Pick count should never decrease across re-exports for same game_date
SELECT game_date, COUNT(*) as picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1 DESC;

-- No more 'dropped' status
SELECT signal_status, COUNT(*)
FROM nba_predictions.best_bets_published_picks
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1;
```
**Pass:** Pick counts non-decreasing, no 'dropped' statuses. **Fail:** Re-investigate `_write_to_bigquery()`.

#### 2. Verify regime context firing
**Added:** Session 413 (Mar 5) | **Type:** Feature verification
```sql
-- Should see regime_over_floor or regime_rescue_blocked entries after a bad day
SELECT filter_reason, COUNT(*)
FROM nba_predictions.best_bets_filtered_picks
WHERE filter_reason LIKE 'regime_%' AND game_date >= '2026-03-06'
GROUP BY 1;

-- Also check filter audit for regime_context in filter_summary
SELECT game_date, JSON_EXTRACT_SCALAR(filter_summary, '$.regime_context.regime_state') as regime
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-05'
ORDER BY game_date DESC LIMIT 5;
```
**Pass:** Regime state logged (even if 'normal' = working). **Fail:** Check import path in exporter.

#### 3. Verify new filters firing
**Added:** Session 413 (Mar 5) | **Type:** Feature verification
```sql
-- flat_trend_under should be blocking UNDER picks with flat trends
-- high_spread_over_would_block should be logging (not blocking) spread 7+ OVER
-- mean_reversion_under should appear in signal_tags
SELECT filter_reason, COUNT(*)
FROM nba_predictions.best_bets_filtered_picks
WHERE filter_reason IN ('flat_trend_under', 'high_spread_over_would_block')
  AND game_date >= '2026-03-06'
GROUP BY 1;

SELECT t, COUNT(*)
FROM nba_predictions.signal_best_bets_picks, UNNEST(JSON_VALUE_ARRAY(signal_tags)) t
WHERE t = 'mean_reversion_under' AND game_date >= '2026-03-06'
GROUP BY 1;
```
**Pass:** At least some counts > 0 within a few days. **Fail:** Check aggregator filter order / signal registration.

---

### Due: ~Mar 12 (1 Week)

#### 4. Counterfactual evaluation of new filters
**Added:** Session 413 (Mar 5) | **Type:** Effectiveness check
```sql
SELECT filter_reason, COUNT(*) as suppressed,
  COUNTIF(prediction_correct) as would_have_won,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as counterfactual_hr
FROM nba_predictions.best_bets_filtered_picks
WHERE filter_reason IN ('regime_over_floor', 'regime_rescue_blocked',
                        'flat_trend_under', 'high_spread_over_would_block',
                        'toxic_starter_over_would_block', 'toxic_star_over_would_block')
  AND prediction_correct IS NOT NULL
  AND game_date >= '2026-03-06'
GROUP BY 1;
```
**Decision:**
- `counterfactual_hr > 55%` → filter is hurting (suppressing winners), dial back
- `counterfactual_hr < 50%` → filter is saving us, keep or strengthen
- `counterfactual_hr 50-55%` → inconclusive, wait for more data

---

### Due: ~Mar 19 (2 Weeks)

#### 5. Signal rescue performance review (target N=25-30)
**Added:** Session 412 (Mar 5) | **Type:** Decision point
```sql
SELECT signal_rescued, rescue_signal,
  COUNT(*) as total,
  COUNTIF(p.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(p.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.signal_best_bets_picks b
JOIN nba_predictions.prediction_accuracy p
  ON b.player_lookup = p.player_lookup AND b.game_date = p.game_date AND b.system_id = p.system_id
WHERE b.game_date >= '2026-01-01' AND p.prediction_correct IS NOT NULL
  AND b.signal_rescued = TRUE
GROUP BY 1, 2 ORDER BY hr;
```
**Currently:** 3-3 (50% HR, N=6). **Decision at N=25-30:**
- HR < 55% → remove `low_line_over` and `volatile_scoring_over` from rescue tags
- HR < 50% → also tighten `signal_stack_2plus` from 2+ to 3+ real signals
- HR >= 60% → rescue is working, keep as-is

#### 6. Mean reversion UNDER promotion check
**Added:** Session 413 (Mar 5) | **Type:** Signal promotion decision
```sql
SELECT
  COUNT(*) as picks,
  COUNTIF(p.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(p.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.signal_best_bets_picks b,
  UNNEST(JSON_VALUE_ARRAY(b.signal_tags)) as tag
JOIN nba_predictions.prediction_accuracy p
  ON b.player_lookup = p.player_lookup AND b.game_date = p.game_date AND b.system_id = p.system_id
WHERE tag = 'mean_reversion_under'
  AND b.game_date >= '2026-03-06'
  AND p.prediction_correct IS NOT NULL;
```
**Research baseline:** 77.8% HR (N=212). **Decision at N>=15 BB picks:**
- HR >= 65% → promote to production signal, add to rescue_tags for UNDER
- HR 55-65% → keep shadow, monitor another 2 weeks
- HR < 55% → keep shadow, investigate discrepancy vs research

#### 7. Spread observation filter evaluation (target N=50)
**Added:** Session 413 (Mar 5) | **Type:** Filter activation decision
```sql
SELECT filter_reason, COUNT(*) as n,
  COUNTIF(prediction_correct) as would_have_won,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.best_bets_filtered_picks
WHERE filter_reason = 'high_spread_over_would_block'
  AND prediction_correct IS NOT NULL AND game_date >= '2026-03-06'
GROUP BY 1;
```
**Decision at N>=50:**
- HR delta >= 10pp vs non-tagged OVER → promote to active negative filter
- HR delta < 5pp → discard, effect was toxic window artifact

---

### Due: ~Apr 5 (1 Month)

#### 8. Tier 2 experiments: projection_delta + sharp_money
**Added:** Session 408-409 (Mar 3-4) | **Type:** Feature experiment
- VSiN data started Mar 4 — needs 30 days accumulation
- NumberFire projections running since Session 401
- **Action:** Run backfill + experiment harness for `projections_v1`, `sharp_money_v1`, `dvp_v1`
```bash
python bin/backfill_experiment_features.py --experiment projections_v1 --start 2026-03-04
python bin/backfill_experiment_features.py --experiment sharp_money_v1 --start 2026-03-04
PYTHONPATH=. python ml/experiments/experiment_harness.py --experiment projections_v1 --seeds 5 --persist
```

#### 9. Player streak signal (deferred, N >= 300)
**Added:** Session 413 (Mar 5) | **Type:** Deferred investigation
- 3+ loss streak OVER = 51.7% HR (N=118), effect modest
- `consecutive_line_misses` computed in supplemental_data but not wired to prediction dict
- **Prerequisite:** Wire streak data through exporter before implementing
- **Check:** Has N grown to 300+? Is the effect still significant?

---

### Ongoing (Check Weekly)

#### 10. Star UNDER weekly tracking
**Added:** Session 400 (Feb 26) | **Type:** Ongoing monitoring
```sql
SELECT FORMAT_DATE('%Y-W%V', b.game_date) as week,
  COUNT(*) as picks, COUNTIF(p.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(p.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.signal_best_bets_picks b
JOIN nba_predictions.prediction_accuracy p
  ON b.player_lookup = p.player_lookup AND b.game_date = p.game_date AND b.system_id = p.system_id
WHERE b.recommendation = 'UNDER' AND b.line_value >= 25
  AND p.prediction_correct IS NOT NULL AND b.game_date >= CURRENT_DATE() - 28
GROUP BY 1 ORDER BY 1;
```
**Alert:** If HR < 50% for 2 consecutive weeks, re-evaluate star UNDER block.

#### 11. Shadow signal fire rates
**Added:** Session 411 (Mar 5) | **Type:** Ongoing monitoring
```sql
SELECT tag, COUNT(*) as fires,
  MIN(b.game_date) as first_seen, MAX(b.game_date) as last_seen
FROM nba_predictions.signal_best_bets_picks b,
  UNNEST(JSON_VALUE_ARRAY(b.signal_tags)) as tag
WHERE tag IN ('mean_reversion_under', 'usage_surge_over', 'scoring_momentum_over',
              'career_matchup_over', 'minutes_load_over', 'blowout_risk_under',
              'projection_consensus_over', 'projection_consensus_under',
              'predicted_pace_over', 'dvp_favorable_over',
              'clv_positive_over', 'clv_negative_under',
              'hot_form_over', 'consistent_scorer_over', 'over_trend_over')
  AND b.game_date >= CURRENT_DATE() - 14
GROUP BY 1 ORDER BY fires DESC;
```
**Promotion criteria:** HR >= 60% + N >= 30 → production. HR >= 65% + N >= 15 → rescue.

#### 12. Deployment drift check
**Added:** Standing | **Type:** Infrastructure
```bash
./bin/check-deployment-drift.sh --verbose
```
Run after every push to main. Auto-deploy should handle it, but verify no drift.

---

### Infrastructure (Do When Convenient)

#### 13. Schedule data source health canary
**Added:** Session 409 (Mar 4) | **Type:** Infrastructure setup
- `bin/monitoring/data_source_health_canary.py` exists but NOT scheduled
- **Action:** Create Cloud Scheduler job, daily 10 AM ET
- **Monitors:** NumberFire, TeamRankings, DVP, RotoWire, VSiN, Covers, Tracking

#### 14. Verify AUTO_DISABLE_ENABLED on decay-detection CF
**Added:** Session 405 (Mar 1) | **Type:** Infrastructure verification
```bash
gcloud functions describe decay-detection --region=us-west2 --format='value(environmentVariables)'
```
**Expected:** `AUTO_DISABLE_ENABLED=true`. If missing, BLOCKED models won't auto-disable.

---

## RESOLVED

_Move items here when complete, with date and outcome._

| # | Item | Resolved | Outcome |
|---|------|----------|---------|
| - | Session 412 commit and deploy | Mar 5 | Committed + pushed. Auto-deployed. |
| - | Worker crash fix (filter_reason=None) | Mar 5 | Fixed Session 407, deployed. |
| - | v401 algorithm deployment | Mar 5 | Deployed with pick locking + regime context. |
| - | Mar 4 backfill (KAT + Jalen Johnson) | Mar 5 | 9 picks in table, both graded. |
| - | rest_advantage_2d disappearance | Mar 5 | Not broken — MAX_SEASON_WEEKS=15 expired Feb 10. Re-enable Oct. |
| - | UNDER conviction gap | Mar 5 | Found mean_reversion_under (77.8% HR). Deployed as shadow signal. |
