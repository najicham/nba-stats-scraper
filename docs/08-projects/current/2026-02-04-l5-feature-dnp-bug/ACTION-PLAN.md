# L5 Feature DNP Bug - Action Plan

**Status:** IN PROGRESS
**Priority:** HIGH
**Created:** 2026-02-04 Session 113

## Progress Tracker

- [x] **Phase 1:** Identify root cause
- [x] **Phase 2:** Fix DNP handling code
- [x] **Phase 3:** Deploy fix to production
- [x] **Phase 4:** Document findings
- [ ] **Phase 5:** Reprocess ML feature store
- [ ] **Phase 6:** Regenerate predictions
- [ ] **Phase 7:** Validate fix
- [ ] **Phase 8:** Investigate secondary issues

## Phase 5: Reprocess ML Feature Store

**Objective:** Regenerate all ML feature store records with fixed DNP handling

### Commands

```bash
# Reprocess entire season (Nov 4 - Feb 4)
PYTHONPATH=. python data_processors/precompute/ml_feature_store/ml_feature_store_processor.py \
  --start-date 2025-11-04 \
  --end-date 2026-02-04 \
  --backfill
```

**Estimated Time:** 2-3 hours for ~24,000 records

**Success Criteria:**
- All records reprocessed
- data_source distribution improved (less 'mixed', more 'phase4')
- L5/L10 values match manual calculations
- No new errors introduced

### Validation After Reprocessing

Run these queries to verify fix:

```sql
-- 1. Check data_source distribution
SELECT
  data_source,
  COUNT(*) as records,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-02-04'  -- After reprocessing
GROUP BY data_source;

-- Expected: Lower % of 'mixed' if Phase 4 coverage improved

-- 2. Spot check Donovan Mitchell (Nov 15)
SELECT
  player_lookup,
  game_date,
  ROUND(features[OFFSET(0)], 1) as pts_l5,
  ROUND(features[OFFSET(1)], 1) as pts_l10,
  data_source
FROM nba_predictions.ml_feature_store_v2
WHERE player_lookup = 'donovanmitchell'
  AND game_date = '2025-11-15';

-- Expected L5: 31.6 (not 29.2)
-- Expected L10: ~30.6 (not 30.3)

-- 3. Spot check Kawhi Leonard (Jan 30) - from handoff doc
SELECT
  player_lookup,
  game_date,
  ROUND(features[OFFSET(0)], 1) as pts_l5_ml,
  data_source
FROM nba_predictions.ml_feature_store_v2
WHERE player_lookup = 'kawhileonard'
  AND game_date = '2026-01-30';

-- Expected: 28.2 (not 14.6)

-- 4. Validate against player_daily_cache for all star players
WITH star_players AS (
  SELECT DISTINCT player_lookup
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date = '2026-01-30'
    AND features[OFFSET(0)] > 25  -- Stars
  LIMIT 20
)
SELECT
  f.player_lookup,
  ROUND(f.features[OFFSET(0)], 1) as ml_l5,
  ROUND(c.points_avg_last_5, 1) as cache_l5,
  ROUND(ABS(f.features[OFFSET(0)] - c.points_avg_last_5), 1) as diff
FROM nba_predictions.ml_feature_store_v2 f
JOIN nba_precompute.player_daily_cache c
  ON f.player_lookup = c.player_lookup
  AND f.game_date = c.cache_date
WHERE f.game_date = '2026-01-30'
  AND f.player_lookup IN (SELECT player_lookup FROM star_players)
ORDER BY diff DESC;

-- Expected: All diff < 1.0
```

## Phase 6: Regenerate Predictions

**Objective:** Generate new predictions using corrected ML features

**Scope:**
- Date range: 2025-11-04 to 2026-02-04
- Systems: prediction-coordinator, prediction-worker

**Process:**
1. ML feature store reprocessed with correct L5/L10 ✅ (from Phase 5)
2. Delete old predictions for date range
3. Regenerate using prediction-coordinator
4. Validate prediction quality improved

**Commands:**

```bash
# 1. Delete old predictions (CAUTION!)
# TBD - Need safe deletion strategy

# 2. Regenerate via coordinator
# TBD - Coordinate with prediction team
```

**Risk Mitigation:**
- Backup old predictions before deletion
- Test on single date first (e.g., 2026-01-30)
- Monitor grading after regeneration

## Phase 7: Validate Fix

### Diagnostic Query from Handoff Doc

```sql
-- Compare ML features vs manual calculation
WITH manual_calc AS (
  SELECT
    player_lookup,
    game_date,
    ROUND(AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
    ), 1) as manual_l5
  FROM nba_analytics.player_game_summary
  WHERE game_date >= '2025-12-01'
    AND points IS NOT NULL
),
feature_values AS (
  SELECT player_lookup, game_date, features[OFFSET(0)] as ml_l5
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= '2026-01-01'
)
SELECT
  f.player_lookup,
  f.game_date,
  ROUND(f.ml_l5, 1) as ml_l5,
  m.manual_l5,
  ROUND(ABS(f.ml_l5 - m.manual_l5), 1) as difference,
  CASE
    WHEN ABS(f.ml_l5 - m.manual_l5) < 1 THEN 'accurate'
    WHEN ABS(f.ml_l5 - m.manual_l5) < 3 THEN 'close'
    WHEN ABS(f.ml_l5 - m.manual_l5) < 5 THEN 'off'
    ELSE 'wrong'
  END as accuracy_tier
FROM feature_values f
JOIN manual_calc m
  ON f.player_lookup = m.player_lookup
  AND f.game_date = m.game_date
WHERE ABS(f.ml_l5 - m.manual_l5) > 1
ORDER BY difference DESC
LIMIT 50;
```

**Success Criteria:**
- Accurate (<1 pt off): >80% (currently 51.5%)
- Wrong (>5 pts): <5% (currently 15.7%)
- No star players with 10+ pt errors

### Hit Rate Comparison

```sql
-- Before vs After hit rates for high-edge picks
-- TBD - Need prediction regeneration first
```

## Phase 8: Investigate Secondary Issues

### Issue 1: Unmarked DNPs

**Query:**
```sql
-- Find all games that look like DNPs but aren't marked
SELECT
  game_date,
  player_lookup,
  points,
  minutes_played,
  is_dnp,
  dnp_reason,
  team_abbr,
  opponent_team_abbr
FROM nba_analytics.player_game_summary
WHERE game_date >= '2025-10-01'
  AND (
    (points = 0 AND minutes_played IS NULL AND is_dnp IS NULL)
    OR (points IS NULL AND is_dnp IS NULL AND minutes_played IS NULL)
  )
ORDER BY game_date DESC
LIMIT 200;
```

**Action Items:**
1. Run audit query
2. Identify affected dates/players
3. Determine root cause (upstream data issue vs processing bug)
4. Add validation to flag unmarked DNPs
5. Consider reprocessing player_game_summary if systematic

### Issue 2: Team Pace Calculation Mismatch

**Investigation:**
1. Check if pace/offensive_rating fields are swapped in source
2. Verify TeamAggregator is using correct fields
3. Compare player_daily_cache vs manual calculation for multiple teams
4. If bug found, fix and reprocess player_daily_cache

**Query:**
```sql
-- Validate team pace for all teams on Nov 15
WITH team_stats AS (
  SELECT
    team_abbr,
    ROUND(AVG(pace) OVER (
      PARTITION BY team_abbr
      ORDER BY game_date DESC
      ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
    ), 2) as manual_pace_l10,
    ROUND(AVG(offensive_rating) OVER (
      PARTITION BY team_abbr
      ORDER BY game_date DESC
      ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
    ), 2) as manual_off_rating_l10
  FROM nba_analytics.team_offense_game_summary
  WHERE game_date < '2025-11-15'
),
cache_stats AS (
  SELECT DISTINCT
    c.player_lookup,
    p.team_abbr,
    c.team_pace_last_10,
    c.team_off_rating_last_10
  FROM nba_precompute.player_daily_cache c
  JOIN nba_analytics.upcoming_player_game_context p
    ON c.player_lookup = p.player_lookup AND c.cache_date = p.game_date
  WHERE c.cache_date = '2025-11-15'
)
SELECT
  cs.team_abbr,
  ROUND(AVG(cs.team_pace_last_10), 2) as cache_pace,
  ROUND(AVG(cs.team_off_rating_last_10), 2) as cache_off_rating,
  -- Compare to manual
  (SELECT manual_pace_l10 FROM team_stats WHERE team_abbr = cs.team_abbr LIMIT 1) as manual_pace,
  (SELECT manual_off_rating_l10 FROM team_stats WHERE team_abbr = cs.team_abbr LIMIT 1) as manual_off_rating
FROM cache_stats cs
GROUP BY cs.team_abbr
ORDER BY cs.team_abbr;
```

### Issue 3: Season Average Discrepancy

**Investigation:**
1. Verify season_year filtering in season stats calculation
2. Check if playoff games are being included
3. Test with multiple players to see if pattern exists
4. If systematic, fix and reprocess

## Timeline

| Phase | Task | Duration | Status | Blocker |
|-------|------|----------|--------|---------|
| 5 | Reprocess ML features | 2-3 hrs | ⏳ READY | None |
| 6 | Regenerate predictions | 2-4 hrs | 🔒 BLOCKED | Awaits Phase 5 |
| 7 | Validate fix | 30 min | 🔒 BLOCKED | Awaits Phase 6 |
| 8.1 | Investigate unmarked DNPs | 1 hr | ⏳ READY | None |
| 8.2 | Investigate team pace | 1 hr | ⏳ READY | None |
| 8.3 | Investigate season avg | 30 min | ⏳ READY | None |

**Total Remaining Time:** ~8-10 hours across multiple sessions

## Success Metrics

### Primary Success (L5/L10 Fix)
- [ ] Reprocessing completes without errors
- [ ] Spot checks show L5/L10 within 1 pt of manual calc
- [ ] Kawhi Leonard Jan 30: 28.2 (not 14.6)
- [ ] Donovan Mitchell Nov 15: 31.6 (not 29.2)
- [ ] No star players with >5 pt L5 errors

### Secondary Success (Data Quality)
- [ ] Unmarked DNPs identified and documented
- [ ] Team pace mismatch explained or fixed
- [ ] Season avg discrepancy resolved
- [ ] Updated spot-check-features skill deployed

### Business Impact
- [ ] Hit rate improvement measured (TBD after regeneration)
- [ ] Prediction confidence calibrated correctly
- [ ] V9 model retrained on clean features (if needed)

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Reprocessing fails mid-run | LOW | HIGH | Checkpointing, can restart |
| New bugs introduced | MEDIUM | HIGH | Thorough validation queries |
| Prediction regeneration issues | LOW | MEDIUM | Test on single date first |
| Additional features broken | LOW | MEDIUM | Complete 37-feature validation |
| Performance degradation | LOW | LOW | Monitor query costs |

## Rollback Plan

If reprocessing fails or introduces new issues:
1. Keep backup of old ML feature store (already exists - historical data)
2. Can revert code changes if needed (git revert 8eba5ec3)
3. Can regenerate from player_daily_cache (has correct values)
4. Predictions can be regenerated from any feature store state

**Rollback Decision Criteria:**
- >10% features show new errors
- Critical features (Vegas lines, team context) broken
- Reprocessing introduces data loss

## Communication Plan

**Stakeholders:**
- Data Quality Team (owner)
- ML Model Team (predictions affected)
- Product Team (user-facing impact)

**Updates:**
- [ ] Pre-reprocessing: Notify teams of maintenance window
- [ ] During reprocessing: Monitor logs, report progress
- [ ] Post-reprocessing: Share validation results
- [ ] After regeneration: Compare hit rate metrics

---

**Owner:** Session 113 / Claude Sonnet 4.5
**Last Updated:** 2026-02-04
**Next Review:** After Phase 5 completion
