# Session 470 Handoff — Mar 7-8 Autopsy, Filter Demotion, Model Refresh

**Date:** 2026-03-12
**Previous:** Session 469 (health-aware weights, directional signals, line rose block)

## What Was Done

### 1. Mar 7-8 Autopsy (12.5% and 25% HR Days)

Deep analysis of the two worst days in the recent downturn. Three root causes identified:

| Root Cause | Impact | Fix Status |
|-----------|--------|------------|
| **Stale LGBM dominance** — `lgbm_v12_noveg_vw015_train1215_0208` sourced 14/26 picks (54%), went 2/11 (18.2%). Trained through Feb 8, nearly a month stale. | Primary driver of losses | **FIXED** — weekly retrain ran Mar 10-11, 7 fresh models active |
| **Low-line OVER rescue trap** — Rescued OVER picks (edge <5) at lines under 12 went 0/7 (0%). Traore 9.5→2, Horford 9.5→4, Konchar 5.5→2, Yabusele 11.5→4. | 5-7 losing picks | **Already fixed** by v468 (HSE-only OVER rescue + 5.0 floor) |
| **UNDER collapse Mar 8** — Stars scored big (Booker 30, Wemby 29, KAT 25, Thompson 23, Castle 23). 5/7 UNDER lost. | One-off event | No action needed — not systematic |

### 2. Filter Audit (Agent-Assisted)

Three filters flagged from autopsy as potentially blocking winners:

| Filter | Actual Status | In-Season CF HR | Action Taken |
|--------|--------------|-----------------|-------------|
| `high_skew_over_block` | **Active blocker** | 75% (3/4 graded) — blocking winners | **DEMOTED to observation** |
| `under_star_away` | Already observation (Session 415) | 50% (N=16) — coin flip | No action needed |
| `b2b_under_block` | Already observation (Session 462) | 16.7% (N=6) — correctly blocking | No action needed |

### 3. Low-Line OVER Investigation (Agent-Assisted)

Key finding: the problem is NOT the line level, it's the rescue mechanism.
- **Low-line OVER at edge 5+: 77.3% HR** — excellent
- **Low-line OVER rescued (edge <5): 0/7 = 0% HR** — catastrophic

No new filter needed — v468's HSE-only OVER rescue + 5.0 floor already blocks this failure mode.

### 4. Retrained Model Validation (Agent-Assisted)

7 new models created Mar 10-11, all enabled. Two issues found:

| Issue | Status |
|-------|--------|
| `catboost_v16_noveg_train0112_0309` — ghost model (enabled, 0 predictions) | **Fix deployed** — worker cache refreshed via v470 push |
| `catboost_v9_low_vegas_train0106_0205` — zombie model (disabled, still predicting) | **Fix deployed** — same cache refresh |
| LightGBM/XGBoost trained through Feb 23 only (42-day vs 56-day target) | Monitor — borderline, not critical |

### 5. Existing Commits Pushed

- `291be145` — Session 469 handoff (was stuck from SSH timeout)
- `c6cae2d0` — Exporter pick-vanishing fix (Session 468)
- Both already pushed by previous session retry

## Implementation Details

| Change | File | Details |
|--------|------|---------|
| `high_skew_over_block` → observation | `aggregator.py` | Removed `continue`, changed filter_reason to `high_skew_over_block_obs` |
| Algorithm version bump | `pipeline_merger.py` | `v470_demote_high_skew` |
| Version test update | `test_aggregator.py` | `v46` → `v47` prefix check |

### Test Results
- **254 passed, 0 failed**

### Deployment
- 1 push, all builds SUCCESS
- Services auto-deployed: prediction-worker, prediction-coordinator, phase6-export, post-grading-export, live-export

## Current State

### Algorithm: `v470_demote_high_skew`

Changes from v469:
- `high_skew_over_block` demoted to observation (was blocking 75% winners)
- All v469 changes retained (health-aware weights, book_disagree directional, over_line_rose_heavy, OVER floor 5.0)

### Model Fleet
- 7 enabled models (all retrained Mar 10-11)
- Ghost model should start predicting after cache refresh
- Zombie model should stop predicting after cache refresh

### BB Performance (Entering v470)
- 7d HR: ~37.5% (prolonged downturn)
- Mar 10: 57.1% (7 picks) — first bounce
- Mar 11: 2 picks (Quickley OVER 16.5, Zion UNDER 21.5) — first v470 test, ungraded

## Priority Tasks (Next Session)

### P0 — Grade Mar 11 + Verify Model Fix

1. Grade Mar 11 results (grading runs ~9 AM ET):
   ```sql
   SELECT player_name, recommendation, line_value, edge, prediction_correct, actual_points
   FROM nba_predictions.signal_best_bets_picks b
   JOIN nba_predictions.prediction_accuracy pa
     ON b.player_lookup = pa.player_lookup AND b.game_date = pa.game_date AND b.system_id = pa.system_id
   WHERE b.game_date = '2026-03-11'
   ```

2. Verify ghost model (`catboost_v16_noveg_train0112_0309`) is now predicting:
   ```sql
   SELECT system_id, COUNT(*) as predictions
   FROM nba_predictions.player_prop_predictions
   WHERE game_date = '2026-03-12'
   AND system_id = 'catboost_v16_noveg_train0112_0309'
   GROUP BY 1
   ```

3. Verify zombie model (`catboost_v9_low_vegas_train0106_0205`) stopped:
   ```sql
   SELECT system_id, COUNT(*) as predictions
   FROM nba_predictions.player_prop_predictions
   WHERE game_date = '2026-03-12'
   AND system_id = 'catboost_v9_low_vegas_train0106_0205'
   GROUP BY 1
   ```

### P1 — Monitor v470 Performance (3-Day Window)

**Decision gates:**
- v470 HR >= 50% over 3 days → keep
- v470 HR < 40% over 3 days → deeper investigation needed
- Track whether `high_skew_over_block_obs` would have helped or hurt

### P2 — Graduate book_disagree Signals (~Mar 18)

Check when `book_disagree_over` reaches N >= 30 at BB level with HR >= 60%:
```sql
SELECT signal_tag, COUNT(*) as n,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb,
UNNEST(bb.signal_tags) AS signal_tag
JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE signal_tag LIKE 'book_disagree%' AND pa.prediction_correct IS NOT NULL
GROUP BY 1
```

### P3 — LightGBM/XGBoost Short Training Window

Both trained through Feb 23 (42 days vs target 56). If next Monday's retrain doesn't fix this, investigate the weekly-retrain CF logic for these families.

### P4 — Season-End Planning

NBA regular season ends ~Apr 13. Consider:
- When to stop making picks (last 2 weeks = tanking teams)
- Season autopsy: `/season-autopsy` across full season
- What to preserve for 2026-27 pre-season

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/aggregator.py` | high_skew demotion, all filter logic |
| `ml/signals/pipeline_merger.py` | ALGORITHM_VERSION = v470 |

## What NOT to Do
- Don't re-activate `high_skew_over_block` without N >= 20 and CF HR < 45%
- Don't add a `low_line_over_block` filter — the rescue mechanism is the issue, and it's already fixed
- Don't manually disable LightGBM/XGBoost for the short training window — let next retrain fix it
