# Session 113 Complete Handoff

## Status: Waiting on L5 Feature Bug Fix

**Do NOT start Phase 6 exporter until the L5 feature bug is fixed.**

A separate Sonnet chat is investigating/fixing the `points_avg_last_5` calculation bug. Once that's resolved, proceed with the Phase 6 exporter.

---

## What Was Accomplished in Session 113

| Task | Status | Notes |
|------|--------|-------|
| Validate V8 vs V9 scenario patterns | ✅ Complete | `optimal_over` and `optimal_under` work for both models |
| Backfill scenario_category | ✅ Complete | 16,721 predictions classified |
| SMS notification setup | ⏸️ Paused | Twilio needs 10DLC registration, using Slack instead |
| Historical data audit | ✅ Complete | Found L5 feature bug (26% of records wrong) |
| L5 feature bug investigation | 🔄 In Progress | Separate chat handling this |

---

## Critical Bug: L5 Feature Calculation

**26% of `points_avg_last_5` values are significantly wrong.**

| Player | Feature L5 | Actual L5 | Difference |
|--------|-----------|-----------|------------|
| Nikola Jokic | 6.2 | 31.0 | 24.8 pts! |
| Lauri Markkanen | 3.8 | 26.6 | 22.8 pts! |
| Kawhi Leonard | 9.0 | 29.2 | 20.2 pts! |
| Luka Doncic | 18.4 | 33.4 | 15.0 pts! |

**Handoff doc for bug fix:** `docs/09-handoff/2026-02-04-SESSION-113-L5-FEATURE-BUG-HANDOFF.md`

---

## Next Task: Phase 6 Exporter + Slack Notifications

### Goal

Export optimal subset picks to GCS for website consumption AND send daily picks to a dedicated Slack channel.

### Slack Setup Required

**Create a new Slack channel and webhook:**

1. Create channel: `#nba-optimal-picks` (or similar)
2. Create webhook: Slack → Apps → Incoming Webhooks → Add to channel
3. Set environment variable: `SLACK_WEBHOOK_URL_OPTIMAL_PICKS`

**Webhook URL format:**
```
https://hooks.slack.com/services/T0900NBTAET/BXXXXXXXX/xxxxxxxxxxxxxxxx
```

### What to Export

**Daily optimal picks JSON to GCS:**
```
gs://nba-props-platform-api/
  daily/
    2026-02-04/
      optimal-picks.json
      signal.json
  latest/
      optimal-picks.json
      signal.json
```

**Suggested JSON structure:**
```json
{
  "game_date": "2026-02-04",
  "generated_at": "2026-02-04T10:30:00Z",
  "signal": {
    "daily_signal": "GREEN",
    "pct_over": 58.3,
    "optimal_over_count": 3,
    "optimal_under_count": 2,
    "ultra_high_edge_count": 1
  },
  "optimal_picks": [
    {
      "player": "Trae Young",
      "player_lookup": "traeyoung",
      "team": "ATL",
      "opponent": "BOS",
      "game_id": "20260204_ATL_BOS",
      "recommendation": "OVER",
      "line": 10.5,
      "predicted": 16.2,
      "edge": 5.7,
      "scenario": "optimal_over",
      "confidence": 0.72,
      "expected_hit_rate": 87.3
    }
  ],
  "avoid_picks": [
    {
      "player": "Luka Doncic",
      "player_lookup": "lukadoncic",
      "reason": "blacklisted_player",
      "scenario": "under_risky"
    }
  ]
}
```

---

## Scenario/Subset System Reference

### Scenario Categories (in `player_prop_predictions.scenario_category`)

| Scenario | Filters | Hit Rate | Action |
|----------|---------|----------|--------|
| `optimal_over` | OVER + Line <12 + Edge ≥5 | **87.3%** | BET |
| `ultra_high_edge_over` | OVER + Edge ≥7 | **88.5%** | BET |
| `optimal_under` | UNDER + Line ≥25 + Edge ≥3 + Not blacklisted | **70.7%** | BET |
| `under_safe` | UNDER + Line ≥20 + Not blacklisted/risky | **65.0%** | BET |
| `high_edge_over` | OVER + Edge ≥5 | ~75% | SELECTIVE |
| `anti_under_low_line` | UNDER + Line <15 | 53.8% | **AVOID** |
| `under_risky` | UNDER + Blacklisted/Risky opponent | ~45% | **AVOID** |
| `low_edge` | Edge <3 | 51.5% | **SKIP** |

### Player Blacklist (UNDER bets only)

```python
UNDER_BLACKLIST_PLAYERS = {
    'lukadoncic',      # 45.5% UNDER hit rate
    'juliusrandle',    # 42.9%
    'jarenjacksonjr',  # 28.6%
    'lameloball',      # 44.4%
    'dillonbrooks',    # 40.0%
    'michaelporterjr', # 40.0%
}
```

### Opponent Risk List (UNDER bets only)

```python
UNDER_RISK_OPPONENTS = {'PHI', 'MIN', 'DET', 'MIA', 'DEN'}
```

---

## Key Queries

### Today's Optimal Picks

```sql
SELECT
  player_lookup,
  recommendation,
  current_points_line as line,
  ROUND(predicted_points, 1) as predicted,
  ROUND(ABS(predicted_points - current_points_line), 1) as edge,
  scenario_category,
  ROUND(confidence_score, 2) as confidence,
  game_id
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND is_active = TRUE
  AND scenario_category IN ('optimal_over', 'optimal_under', 'ultra_high_edge_over')
ORDER BY
  CASE scenario_category
    WHEN 'ultra_high_edge_over' THEN 1
    WHEN 'optimal_over' THEN 2
    WHEN 'optimal_under' THEN 3
  END,
  edge DESC;
```

### Today's Signal

```sql
SELECT
  game_date,
  daily_signal,
  pct_over,
  optimal_over_count,
  optimal_under_count,
  ultra_high_edge_count,
  anti_pattern_count
FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9';
```

### Picks to Avoid

```sql
SELECT
  player_lookup,
  recommendation,
  current_points_line as line,
  scenario_category,
  scenario_flags
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND is_active = TRUE
  AND scenario_category IN ('anti_under_low_line', 'under_risky', 'low_edge')
ORDER BY scenario_category;
```

---

## Documents to Read

| Document | Purpose |
|----------|---------|
| `docs/09-handoff/2026-02-04-SESSION-113-L5-FEATURE-BUG-HANDOFF.md` | L5 bug details (check if fixed) |
| `docs/09-handoff/2026-02-04-SESSION-113-PHASE6-EXPORTER-HANDOFF.md` | Phase 6 exporter details |
| `docs/09-handoff/2026-02-03-SESSION-112-HANDOFF.md` | Scenario system implementation |
| `docs/03-phases/` | Phase architecture |
| `shared/notifications/subset_picks_notifier.py` | Existing notification code (can reuse) |
| `predictions/coordinator/signal_calculator.py` | Where signals are calculated |

---

## Code References

| File | Purpose |
|------|---------|
| `predictions/worker/worker.py` lines 398-485 | `_classify_scenario()` function |
| `shared/notifications/subset_picks_notifier.py` | Existing picks notifier (has query logic) |
| `shared/utils/slack_channels.py` | Slack posting utilities |
| `predictions/coordinator/signal_calculator.py` | Daily signal + notification trigger |

---

## Environment Variables Needed

```bash
# New Slack webhook for optimal picks channel
SLACK_WEBHOOK_URL_OPTIMAL_PICKS=https://hooks.slack.com/services/...

# Existing (already set)
SLACK_WEBHOOK_URL_SIGNALS  # #nba-betting-signals
```

---

## Deployments After Changes

If you modify these services, deploy them:

```bash
./bin/deploy-service.sh prediction-coordinator  # If signal_calculator.py changes
./bin/deploy-service.sh prediction-worker       # If worker.py changes
```

---

## Task Checklist

### Pre-requisites (wait for these)
- [ ] L5 feature bug fixed (separate chat)
- [ ] Predictions regenerated with correct features

### Slack Setup
- [ ] Create `#nba-optimal-picks` channel in Slack
- [ ] Create incoming webhook for channel
- [ ] Set `SLACK_WEBHOOK_URL_OPTIMAL_PICKS` env var on coordinator

### Phase 6 Exporter
- [ ] Create export function for optimal picks JSON
- [ ] Add daily signal to export
- [ ] Set up GCS paths (`gs://nba-props-platform-api/daily/`, `latest/`)
- [ ] Add to daily pipeline (trigger after predictions)
- [ ] Test export and verify JSON structure

### Slack Notifications
- [ ] Add Slack notification for optimal picks to new channel
- [ ] Format message with picks, signal, and expected hit rates
- [ ] Test notification

---

## Slack Message Format (Suggested)

```
🏀 *NBA Optimal Picks - 2026-02-04*

🟢 *GREEN Signal* (58% OVER)

*OPTIMAL OVER (87% HR):*
1. T.Young - OVER 10.5 pts (edge: 5.7)
2. J.Brunson - OVER 11.0 pts (edge: 5.2)

*OPTIMAL UNDER (71% HR):*
1. N.Jokic - UNDER 26.5 pts (edge: 4.1)

*ULTRA HIGH EDGE (89% HR):*
1. D.Fox - OVER 8.5 pts (edge: 7.3)

⚠️ *AVOID:*
- L.Doncic UNDER (blacklisted)
- Any UNDER vs PHI (risky opponent)

_Historical: 85% hit rate on optimal picks (last 30 days)_
```

---

## Session 113 Summary

- **Validated** that optimal_over/optimal_under patterns work for both V8 and V9
- **Backfilled** 16,721 historical predictions with scenario_category
- **Discovered** L5 feature calculation bug affecting 26% of records
- **Set up** Twilio (blocked by 10DLC), will use Slack instead
- **Created** handoff docs for L5 bug fix and Phase 6 exporter

---

**Created:** 2026-02-04 Session 113
**Author:** Claude Opus 4.5
