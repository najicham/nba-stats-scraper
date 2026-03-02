# Session 388 Prompt — Verify Signal Fixes & Monitor Fleet

## Context

Session 387 made critical fixes:
1. Revived `line_rising_over` (96.6% HR) — was dead due to champion model dependency
2. Revived `fast_pace_over` (81.5% HR) — threshold was on wrong scale
3. Deployed signal firing canary — automated detection for dead signals
4. Fixed `prop_line_delta` — 3 negative filters were silently broken
5. Cleaned fleet, fixed edge storage, updated all docs

## Priority 1: Verify Signal Fixes on Game Day

Run after predictions have run for a game day:

```sql
-- Are the revived signals firing?
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags
CROSS JOIN UNNEST(signal_tags) AS signal_tag
WHERE game_date = CURRENT_DATE()
  AND signal_tag IN ('line_rising_over', 'fast_pace_over')
GROUP BY 1;

-- Is prop_line_delta populated?
SELECT
  COUNT(*) as total_picks,
  COUNTIF(prop_line_delta IS NOT NULL) as has_delta,
  ROUND(100.0 * COUNTIF(prop_line_delta IS NOT NULL) / COUNT(*), 1) as pct
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = CURRENT_DATE();

-- Did signal count increase? (more signals = more picks pass SC>=3)
SELECT game_date,
  AVG(signal_count) as avg_signals,
  COUNT(*) as picks,
  COUNTIF(signal_count >= 3) as pass_sc3
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1 ORDER BY 1;

-- Check canary ran and found our fixed signals
-- (line_rising_over and fast_pace_over should move from NEVER_FIRED to HEALTHY)
```

**Expected outcomes:**
- `line_rising_over` fires on OVER picks where today's line > yesterday's line
- `fast_pace_over` fires on OVER picks vs opponents with pace > 75th percentile
- `prop_line_delta` populated for most players (was always NULL)
- Best bets volume may increase (more signals = more SC>=3 qualifiers)

## Priority 2: Signal Canary Verification

The canary runs in `post_grading_export` CF after grading. Check:
```bash
# Look for canary output in Cloud Run logs
gcloud logging read 'resource.type="cloud_run_revision" AND textPayload=~"Signal firing canary"' --limit=5 --freshness=24h --project=nba-props-platform

# Or run manually
PYTHONPATH=. python ml/signals/signal_health.py --canary
```

**Expected:** `line_rising_over` and `fast_pace_over` should move from NEVER_FIRED to HEALTHY once they fire on a game day.

## Priority 3: Monitor combo_3way and combo_he_ms

The canary flagged these as DEAD (0 fires in 7d). These are combo signals that require multiple other signals to align, so they may be legitimately rare during low-volume periods. But monitor:
- If still DEAD after 2+ game days with 8+ games, investigate
- These depend on `high_edge` + `model_spread` (combo_he_ms) and `high_edge` + `model_spread` + a third signal (combo_3way)

## Priority 4: Watch New Shadow Models

13 enabled models, 2 freshly deployed:
- `catboost_v12_train1228_0222` (76.9% backtest) — needs N>=25
- `catboost_v12_noveg_train1228_0222` (68.8% backtest) — needs N>=25

```sql
SELECT model_id, rolling_hr_7d, rolling_n_7d, rolling_hr_14d, rolling_n_14d, state
FROM nba_predictions.model_performance_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.model_performance_daily)
  AND model_id LIKE '%train1228_0222%'
ORDER BY model_id;
```

**Don't act until N>=25.** The multi-model system is working — shadow models sourced 100% HR picks while champion sourced 25% HR in the last 14 days.

## Priority 5: OVER Performance Tracking

OVER was at 53.8% HR (14d) going into Session 387. The signal fixes should help because:
- `line_rising_over` (96.6% HR) specifically targets OVER
- `fast_pace_over` (81.5% HR) specifically targets OVER
- Both add signal count → more OVER picks qualify past SC>=3 filter

```sql
SELECT recommendation,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 1) as hr
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.signal_best_bets_picks sb
  ON pa.player_lookup = sb.player_lookup
  AND pa.game_date = sb.game_date
  AND pa.system_id = sb.system_id
WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY 1;
```

## Items NOT to Do

- **Don't retrain** — wait for signal fix impact data (1-2 weeks)
- **Don't promote a champion** — no model at N>=25 yet
- **Don't add new signals** — verify existing fixes first
- **Don't expand OVER restrictions** — the two revived signals ARE the OVER fix

## Deferred Items (Future Sessions)

### Phase 3: Auto-Disable BLOCKED Models
When: After canary is validated in production (1-2 weeks)
What: Extend decay_detection CF to auto-disable shadow models that hit BLOCKED state
Plan: `docs/08-projects/current/fleet-lifecycle-automation/00-PLAN.md`

### Phase 4: Registry Hygiene Automation
When: When convenient (low priority — fleet is clean after Session 387)
What: Weekly scheduler job to enforce status consistency

### Phase 5: Champion Promotion Pipeline
When: When a shadow model reaches N>=25 with HR>=60%
What: Automated evaluation and recommendation (human approval still required)

### self-heal-predictions Timeout
The Cloud Function is at Gen1 max (540s). Needs code optimization or Gen2 migration. Low priority — hasn't caused data loss, just scheduler noise.

### Deployment Trigger Coverage
`prediction-coordinator` Cloud Build only watches `predictions/coordinator/**`, NOT `ml/signals/`. Signal changes need manual deploy. Could expand trigger path.
