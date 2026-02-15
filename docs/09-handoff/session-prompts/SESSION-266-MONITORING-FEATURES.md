# Session 266: Monitoring Features — Directional Concentration, Cross-Model Crash, Meta-Monitoring, Baseline Dashboard

## Context

Session 263 review identified several monitoring gaps. These are all small, related features that can be built in one session. Games resume Feb 19 — these should be live by then or shortly after.

## What to Build

### 1. Directional Concentration Monitor

**Problem:** On Feb 2, 94% of V9 picks were UNDER — a red flag that was only visible day-of. If the model is systematically biased in one direction, we should flag it.

**Implementation:**
- Add a check in `validate-daily` (`.claude/skills/validate-daily/SKILL.md`) or as a new Phase in the validation
- Query: For today's predictions with edge >= 3, what % are OVER vs UNDER?
- Alert threshold: >80% same direction = warning
- Alert channel: same as decay detection

```sql
SELECT recommendation, COUNT(*) as picks,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = @model_id
  AND ABS(predicted_points - current_points_line) >= 3.0
  AND is_active = TRUE
GROUP BY 1
```

### 2. Cross-Model Crash Detector

**Problem:** On Feb 2, EVERY model crashed (V8 28.6%, V9 15.2%, moving_average 48.0%). When 2+ models crash simultaneously, it's a market event, not model-specific decay. The response should be different (halt all betting vs switch models).

**Implementation:**
- Add to `decay-detection` CF or as a separate check in `post_grading_export`
- Query `model_performance_daily` for the latest date
- If 2+ models have daily_hr < 40% on the same date → market disruption alert
- Different Slack message than single-model decay

### 3. Meta-Monitoring (Monitor the Monitors)

**Problem:** If `model_performance_daily` stops being computed (e.g., post_grading_export import fails silently), or `signal_health_daily` stops updating, the decay detection system has stale data and won't alert properly. Nothing currently catches this.

**Implementation:**
- Add a check to `daily-health-check` CF or `validate-daily`
- Verify: `model_performance_daily` has a row for yesterday (when games were played)
- Verify: `signal_health_daily` has rows for yesterday
- Verify: `decay-detection-daily` scheduler job ran in the last 25 hours
- Alert if any check fails

```sql
-- Check model_performance_daily freshness
SELECT MAX(game_date) as latest, DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
FROM nba_predictions.model_performance_daily;

-- Check signal_health_daily freshness
SELECT MAX(game_date) as latest, DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
FROM nba_predictions.signal_health_daily;
```

### 4. Baseline Comparison in Dashboard

**Problem:** We track V9/V12 performance but don't surface how they compare to simple baselines. If our complex system can't beat moving_average on a rolling basis, something is broken.

**Implementation:**
- Add to `validate-daily` Phase 0.58 (model performance dashboard)
- Show moving_average's rolling 7d HR alongside the active models
- Flag if best_bets_model HR < moving_average HR for 3+ consecutive days

## Key Files

- `orchestration/cloud_functions/decay_detection/main.py` — for cross-model crash
- `.claude/skills/validate-daily/SKILL.md` — for directional, meta-monitoring, baseline
- `orchestration/cloud_functions/post_grading_export/main.py` — if adding checks here
- `orchestration/cloud_functions/daily_health_check/main.py` — for meta-monitoring

## Priority Order

1. Meta-monitoring (highest impact — prevents silent monitoring failures)
2. Directional concentration (catches the Feb 2 pattern)
3. Cross-model crash detector (distinguishes market events from model decay)
4. Baseline dashboard (operational awareness)

## Constraints

- All checks should be non-blocking (log + alert, don't break existing functionality)
- Use existing Slack channels (`#nba-alerts` for warnings)
- Commit and push when done
