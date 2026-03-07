# Start Your Next Session Here

**Updated:** 2026-03-06 (Session 428 — Filter Cleanup)
**Status:** NBA v428 deployed. 4 harmful filters demoted to observation. MLB Sprint 2 complete.

## What Happened in Session 428

### Filter Cleanup — 4 Filters Demoted

Session 427 research found 6 filters blocking profitable picks. Session 428 validated and demoted 4:

| Filter | CF HR | N | Action |
|--------|-------|---|--------|
| `neg_pm_streak` | 64.5% | 758 | DEMOTED — was blocking highest-HR picks |
| `line_dropped_over` | 60.0% | 477 | DEMOTED — toxic window original data |
| `flat_trend_under` | 59.2% | 211 | DEMOTED — above breakeven |
| `mid_line_over` | 55.8% | 926 | DEMOTED — weekly noise (13.6pp stddev) |

**Kept:** `under_edge_7plus` — BQ validated v9 UNDER edge 7+ = **34.1% HR** (N=41). The Session 427 CF HR of 60.2% was incorrectly computed across ALL models.

**Already handled:** `star_under` (removed Session 400), `bench_under` (demoted Session 419).

Algorithm version: `v428_filter_cleanup`

### Additional Findings

- `predicted_pace_over`: Dropped from 63.6% (N=22) to **53.6% (N=28)** — NOT promotion-ready
- Session 427 signals (bounce_back_over, CLV, under_after_bad_miss) haven't fired yet — code pushed after Mar 6 pipeline ran. First test: Mar 7.
- Model-aware filtering (v9_mae low-line UNDER block) deferred to future session — needs architecture work.

---

## What to Do Next

### Priority 1: Monitor Filter Demotion Impact (Mar 7-14)

Track BB HR and pick volume for 7 days after deployment. Key metrics:
- BB HR should stay >= 55% (current: ~62%)
- Pick volume will increase (more picks passing through)
- Watch for any single-day HR collapse

```sql
-- Daily BB performance post-demotion
SELECT game_date, recommendation, COUNT(*) as picks,
  ROUND(AVG(CAST(prediction_correct AS INT64)) * 100, 1) as hr
FROM `nba_predictions.signal_best_bets_picks`
WHERE game_date >= '2026-03-07'
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2
```

### Priority 2: Check Mar 7 Signal Fires

First production data for:
- `bounce_back_over` (with shooting quality tiers)
- `over_streak_reversion_under`
- CLV signals (`positive_clv_over/under`) — fixed snapshot bug
- `under_after_bad_miss` negative filter

### Priority 3: Model-Aware Filtering (Phase 2)

Architecture question: `aggregator.py` doesn't know which model(s) support a pick. Quick win:
- v9_mae UNDER on low-line (<15) = 36.3% HR — but how to check `system_id` in multi-model aggregation?
- See `docs/08-projects/current/filter-tuning-427/PLAN.md` Phase 2

### Priority 4: MLB Sprint 3

- Run Statcast backfill Jul-Sep 2025
- Run walk-forward simulation
- Train CatBoost V1 model
- Deploy + resume schedulers for Mar 27
- **Status:** `docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md`

## Deployment State

- Algorithm: `v428_filter_cleanup`
- New signals from Session 427 deploying with this push
- Drift: nba-phase1-scrapers (stale), pipeline-health-summary (stale) — not urgent
