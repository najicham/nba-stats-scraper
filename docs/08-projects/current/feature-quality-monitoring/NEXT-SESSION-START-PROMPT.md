# Feature Quality Monitoring - Next Session Start Prompt

**Created:** 2026-01-31
**For:** Next session to continue feature quality work
**Priority:** Deploy fixes, then address remaining broken features

---

## Context

Sessions 44-48 investigated and fixed ML feature quality issues. Key accomplishments:

1. **fatigue_score bug FIXED** - Was returning 0 instead of 0-100 score (Jan 25-30)
2. **Vegas lines query bug FIXED** - Was missing `market_type = 'points'` filter
3. **Pre-write validation IMPLEMENTED** - Catches range violations before BigQuery write
4. **Monitoring table CREATED** - `nba_monitoring_west2.feature_health_daily`

**BUT** the fixes need deployment and there are remaining broken features.

---

## Start Prompt for Next Session

```
Continue the feature quality monitoring work from Sessions 47-48.

## Read First
cat docs/08-projects/current/feature-quality-monitoring/COMBINED-FINDINGS.md
cat docs/08-projects/current/feature-quality-monitoring/README.md

## Priority 1: Deploy Fixes (5 min)

The Vegas query fix and pre-write validation are committed but NOT deployed:

./bin/deploy-service.sh nba-phase4-precompute-processors

Then verify:
bq query --use_legacy_sql=false --location=us-west2 "
SELECT game_date,
  COUNTIF(features[OFFSET(25)] > 0) as has_vegas,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1"

## Priority 2: Backfill ML Feature Store for Jan 30

Session 47 found Jan 30 ML feature store was generated before source data existed.
Delete and regenerate:

bq query --use_legacy_sql=false --location=us-west2 "
DELETE FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-01-30'"

Then trigger regeneration via Phase 4 endpoint (see Session 48 handoff for pattern).

## Priority 3: Fix Remaining Broken Features

### 3a. team_win_pct (always 0.5)
Root cause: Calculated but not passed to final record
File: data_processors/analytics/upcoming_player_game_context/calculators/context_builder.py

### 3b. usage_spike_score (always 0)
Root cause: projected_usage_rate = None (TODO in code)
File: data_processors/analytics/upcoming_player_game_context/calculators/context_builder.py:295
Note: This requires play-by-play data - may be intentionally deferred

## Priority 4: Set Up Scheduled Query

Create Cloud Scheduler job to populate feature_health_daily table daily.
See: schemas/bigquery/monitoring/feature_health_daily.sql

## Key Files

| Purpose | File |
|---------|------|
| Combined findings | docs/08-projects/current/feature-quality-monitoring/COMBINED-FINDINGS.md |
| Project README | docs/08-projects/current/feature-quality-monitoring/README.md |
| Pre-write validation | data_processors/precompute/ml_feature_store/ml_feature_store_processor.py |
| Vegas query (fixed) | data_processors/precompute/ml_feature_store/feature_extractor.py:628 |
| Monitoring table | schemas/bigquery/monitoring/feature_health_daily.sql |
| Session 48 handoff | docs/09-handoff/2026-01-31-SESSION-48-FEATURE-QUALITY-MONITORING-HANDOFF.md |

## Verification Queries

# Check feature health
bq query --use_legacy_sql=false --location=us-west2 "
SELECT feature_name, health_status, ROUND(mean, 2) as mean, zero_pct
FROM nba_monitoring_west2.feature_health_daily
WHERE report_date >= CURRENT_DATE() - 3
ORDER BY health_status, report_date DESC"

# Check fatigue is correct
bq query --use_legacy_sql=false --location=us-west2 "
SELECT game_date, ROUND(AVG(fatigue_score), 2) as avg, COUNTIF(fatigue_score = 0) as zeros
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2026-01-25'
GROUP BY 1 ORDER BY 1"
```

---

## What's Already Done (Don't Redo)

| Task | Status | Commit |
|------|--------|--------|
| Fatigue bug fix (processor.py) | ✅ Done | cec08a99 |
| Fatigue bug fix (worker.py) | ✅ Done | c475cb9e |
| Vegas query fix | ✅ Done | 0ea398bd |
| Pre-write validation | ✅ Done | 0ea398bd |
| Monitoring table created | ✅ Done | BigQuery |
| Monitoring table populated | ✅ Done | 7 days of data |
| Phase 4 deployed (fatigue fix) | ✅ Done | Revision 00084-lqh |
| Backfill Jan 25-30 (composite factors) | ✅ Done | All dates successful |

---

## What Needs Doing

| Task | Priority | Effort |
|------|----------|--------|
| Deploy Phase 4 (Vegas + validation) | HIGH | 5 min |
| Backfill Jan 30 ML feature store | HIGH | 10 min |
| Fix team_win_pct passthrough | MEDIUM | 30 min |
| Set up scheduled health query | MEDIUM | 15 min |
| Fix usage_spike_score | LOW | 2+ hours (needs play-by-play) |
| Integrate schedule_context_calculator | LOW | 1 hour |

---

## Success Criteria

After this session:
1. Phase 4 deployed with Vegas fix + pre-write validation active
2. Jan 30 ML feature store regenerated with correct fatigue values
3. team_win_pct fixed (should show variance, not always 0.5)
4. Scheduled query set up for daily health monitoring

---

*Handoff created: 2026-01-31 (Session 48)*
