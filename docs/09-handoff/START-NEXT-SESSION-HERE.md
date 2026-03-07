# Start Your Next Session Here

**Updated:** 2026-03-07 (Sessions 428 + MLB Sprint 3)
**Status:** NBA v428 deployed (4 filters demoted). MLB CatBoost V1 trained (NOT deployed). Signal validation needed.

---

## NBA Session 429: Signal Validation + Cleanup

Session 428 demoted 4 harmful filters and deployed v428. Mar 7 is the first day with the new filter stack AND Session 427's new signals. This session validates the changes, fixes mean_reversion_under, and promotes validated shadow signals.

### Task 1: Validate Filter Demotion Impact

Check Mar 7+ best bets. Compare pick count and HR to recent days (which had mixed algorithm versions from deployment drift).

```sql
-- Compare v428 to prior versions
SELECT game_date, algorithm_version, recommendation,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(AVG(CAST(prediction_correct AS INT64)) * 100, 1) as hr
FROM `nba_predictions.signal_best_bets_picks`
WHERE game_date >= '2026-03-04'
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
```

**Expected:** More picks (4 fewer active filters), HR >= 55%. Algorithm should be `v428_filter_cleanup` consistently (prior days had mixed v406/v414/v415).

**What was demoted:** `neg_pm_streak` (64.5% CF HR), `line_dropped_over` (60.0%), `flat_trend_under` (59.2%), `mid_line_over` (55.8%). All still track in observation mode with `_obs` suffix.

**What was kept:** `under_edge_7plus` — BQ validated v9 UNDER edge 7+ = 34.1% HR (N=41). Filter correctly targets only v9 models.

**Key file:** `ml/signals/aggregator.py` — lines 548-700 (filter logic), line 54 (ALGORITHM_VERSION)
**Research:** `docs/08-projects/current/filter-tuning-427/PLAN.md`

### Task 2: Check New Signal Fires

First production day for Session 427 signals. Check whether they're reaching best bets.

| Signal | Type | What to check |
|--------|------|---------------|
| `bounce_back_over` | Active | Shooting quality tiers (severe+bad_shooting = max confidence) |
| `under_after_bad_miss` | Neg filter | Blocking AWAY + bad miss + bad shooting UNDER picks |
| CLV (`positive_clv_over/under`) | Shadow | Fixed snapshot bug — should fire for first time ever |
| `over_streak_reversion_under` | Shadow | Check fire count |
| `volatile_starter_under` | Shadow | Cross-season validated (+11.1pp lift). Check fire count. |
| `downtrend_under` | Shadow | Cross-season validated (+8.1pp lift). Check fire count. |

```sql
-- Signal fires in today's best bets
SELECT player_lookup, recommendation, signal_tags, pick_angles, edge, prediction_correct
FROM `nba_predictions.signal_best_bets_picks`
WHERE game_date = CURRENT_DATE()
ORDER BY recommendation, player_lookup
```

```sql
-- Signal health for new signals
SELECT signal_tag, picks_season, hr_season, regime, picks_30d, hr_30d
FROM `nba_predictions.signal_health_daily`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
  AND signal_tag IN ('bounce_back_over', 'over_streak_reversion_under',
    'positive_clv_over', 'positive_clv_under',
    'volatile_starter_under', 'downtrend_under', 'under_after_bad_miss')
ORDER BY game_date DESC, signal_tag
```

**Key files:**
- `ml/signals/bounce_back_over.py`
- `ml/signals/clv_signal.py`
- `ml/signals/volatile_starter_under.py`, `ml/signals/downtrend_under.py`
- `ml/signals/aggregator.py:654-667` (under_after_bad_miss filter)

### Task 3: Fix mean_reversion_under (URGENT)

Cross-season analysis shows decay **below 2026 baseline**:
- 2024: 75.7% → 2025: 65.2% → 2026: **53.0%** (baseline is 54.3%)
- Already removed from rescue tags (Session 427, `aggregator.py:365`)
- Still weighted at **1.5** in `UNDER_SIGNAL_WEIGHTS` — contributing to UNDER pick ranking

**Action:** Set weight to 0 or remove from `UNDER_SIGNAL_WEIGHTS` entirely. A signal below baseline should not influence UNDER ranking.

**Key file:** `ml/signals/aggregator.py:73` — `UNDER_SIGNAL_WEIGHTS` dict
**Cross-season data:** Memory file `sessions-416-426.md` (Session 426 section)

### Task 4: Promote Validated Shadow UNDER Signals

Session 426 cross-season validation confirmed:

| Signal | 2026 Lift vs Baseline | Current Weight | Action |
|--------|----------------------|----------------|--------|
| `volatile_starter_under` | +11.1pp (BEST) | 1.5 | Increase to **2.0** |
| `downtrend_under` | +8.1pp (HEALTHY) | 1.5 | Increase to **2.0** |
| `star_favorite_under` | +0.7pp (NOISE) | removed | Confirm removed |

**Wait for** Mar 7+ fire count data — need N >= 5 at BB level before promoting.

**Key files:**
- `ml/signals/aggregator.py:60-90` — `UNDER_SIGNAL_WEIGHTS`
- `ml/signals/volatile_starter_under.py`, `ml/signals/downtrend_under.py`
- Signal inventory: `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`

### Task 5: Fix Stale Deployments

```bash
./bin/deploy-service.sh nba-phase1-scrapers      # Stale since Mar 4
./bin/deploy-service.sh pipeline-health-summary   # Stale since Mar 4
./bin/check-deployment-drift.sh --verbose         # Verify
```

### Task 6: predicted_pace_over — Monitor Only

HR dropped from 63.6% (N=22) to **53.6% (N=28)**. Not promotion-ready. Check if trend continues.

### Bump ALGORITHM_VERSION after changes

If modifying signal weights or removing mean_reversion_under:
```python
ALGORITHM_VERSION = 'v429_signal_weight_cleanup'
```

---

## MLB: Deploy Sprint 2+3 (Separate Priority)

CatBoost V1 model trained + in GCS/BQ (NOT deployed). Sprint 2+3 code NOT committed.
Full deploy steps: `docs/09-handoff/2026-03-07-MLB-SPRINT3-HANDOFF.md`

---

## Reference Documents

| Doc | What |
|-----|------|
| `docs/08-projects/current/filter-tuning-427/PLAN.md` | Filter research + Phase 1 results |
| `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` | Full signal inventory |
| `docs/08-projects/current/player-deep-dive/` | Bounce-back, streak analysis |
| Memory: `sessions-416-426.md` | Cross-season signal validation |
| `docs/09-handoff/2026-03-07-MLB-SPRINT3-HANDOFF.md` | MLB deploy steps |

## Key Code Locations

| File | Lines | What |
|------|-------|------|
| `ml/signals/aggregator.py` | 54 | `ALGORITHM_VERSION` |
| `ml/signals/aggregator.py` | 60-90 | `UNDER_SIGNAL_WEIGHTS` |
| `ml/signals/aggregator.py` | 334-410 | Signal rescue logic |
| `ml/signals/aggregator.py` | 548-700 | All negative filters |
| `ml/signals/aggregator.py` | 782-850 | Signal evaluation + real_sc gate |
| `ml/signals/registry.py` | — | Signal registration |

## Deployment State

- **NBA:** Algorithm `v428_filter_cleanup` deployed to all 5 services (Mar 7 02:17 UTC)
- **MLB:** Sprint 2+3 code NOT committed. CatBoost V1 in GCS, not enabled.
- **Drift:** nba-phase1-scrapers, pipeline-health-summary (stale since Mar 4)
