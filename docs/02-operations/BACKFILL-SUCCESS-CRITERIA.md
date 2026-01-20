# Backfill Success Criteria

**Purpose**: Define clear thresholds for "backfill success" per pipeline phase
**Created**: 2026-01-20
**Use Case**: Verify backfills worked without manual BigQuery console checking

---

## 🎯 Overall Success Definition

A backfill is **successful** when:
1. ✅ All required phases have data
2. ✅ Health score ≥ 70% (acceptable) or ≥ 85% (excellent)
3. ✅ No critical data gaps (missing tables, 0 records)
4. ✅ Downstream dependencies met

---

## 📊 Phase-by-Phase Success Criteria

### Phase 2: Scrapers (Raw Data Collection)

**What it does**: Scrapes box scores and gamebook data from external APIs

**Success Thresholds**:
- ✅ **EXCELLENT**: Coverage ≥ 90% of scheduled games
- ⚠️ **ACCEPTABLE**: Coverage 70-89% of scheduled games
- ❌ **FAIL**: Coverage < 70% OR both sources have 0 records

**How to verify**:
```sql
-- Check coverage
SELECT
  game_date,
  scheduled_games,
  bdl_box_scores,
  nbac_gamebook,
  GREATEST(bdl_box_scores, nbac_gamebook) as best_coverage,
  ROUND(GREATEST(bdl_box_scores, nbac_gamebook) / scheduled_games * 100, 1) as coverage_pct
FROM (
  SELECT
    s.game_date,
    COUNT(DISTINCT s.game_id) as scheduled_games,
    COUNT(DISTINCT b.game_id) as bdl_box_scores,
    COUNT(DISTINCT g.game_id) as nbac_gamebook
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  LEFT JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
    ON s.game_date = b.game_date
  LEFT JOIN `nba-props-platform.nba_raw.nbac_gamebook_player_stats` g
    ON s.game_date = g.game_date
  WHERE s.game_date = '2026-01-20'  -- Your backfill date
  GROUP BY s.game_date
)
```

**Quick check** (smoke test):
```bash
python scripts/smoke_test.py 2026-01-20
# Output: P2:PASS means at least one source has data
```

**Notes**:
- At least ONE box score source (bdl OR nbac) must have data
- BDL is primary source, nbac is backup
- Missing box scores cascade to Phase 4 PSZA failures

---

### Phase 3: Analytics (Feature Calculation)

**What it does**: Processes raw data into analytics tables

**Success Thresholds**:
- ✅ **EXCELLENT**: All 3 tables populated + record counts match expected (~10-20 per game)
- ⚠️ **ACCEPTABLE**: All 3 tables have data (any count > 0)
- ❌ **FAIL**: Any of the 3 tables has 0 records

**Required tables**:
1. `player_game_summary` - Player stats per game (SOURCE OF TRUTH)
2. `team_defense_game_summary` - Team defensive metrics
3. `upcoming_player_game_context` - Lookahead features for predictions

**How to verify**:
```sql
-- Check all 3 tables exist
SELECT
  'player_game_summary' as table_name,
  COUNT(*) as record_count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2026-01-20'

UNION ALL

SELECT
  'team_defense_game_summary',
  COUNT(*)
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date = '2026-01-20'

UNION ALL

SELECT
  'upcoming_player_game_context',
  COUNT(*)
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date = '2026-01-20'
```

**Quick check** (smoke test):
```bash
python scripts/smoke_test.py 2026-01-20
# Output: P3:PASS means player_game_summary exists
```

**Notes**:
- `player_game_summary` is CRITICAL - all downstream depends on it
- Expect ~8-20 records per game (players who played)
- Expect ~2-4 records per game in team_defense (home/away teams)
- Phase 4 will fail if Phase 3 is incomplete

---

### Phase 4: Precompute (Feature Engineering)

**What it does**: Computes ML features for predictions

**Success Thresholds**:
- ✅ **EXCELLENT**: All 4 processors completed
- ⚠️ **ACCEPTABLE**: ≥3 processors completed (early season bootstrap)
- ❌ **FAIL**: <3 processors OR missing critical processors (PDC, MLFS expected later in season)

**Processors** (in dependency order):
1. **TDZA** (Team Defense Zone Analysis) - Can run parallel
2. **PSZA** (Player Shot Zone Analysis) - Can run parallel
3. **PCF** (Player Composite Factors) - Needs TDZA + PSZA
4. **PDC** (Player Daily Cache) - Needs Phase 3

**How to verify**:
```sql
-- Check processor completion
SELECT
  'PDC' as processor,
  COUNT(*) as records,
  IF(COUNT(*) > 0, 'COMPLETE', 'MISSING') as status
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = '2026-01-20'

UNION ALL

SELECT 'PSZA', COUNT(*), IF(COUNT(*) > 0, 'COMPLETE', 'MISSING')
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = '2026-01-20'

UNION ALL

SELECT 'PCF', COUNT(*), IF(COUNT(*) > 0, 'COMPLETE', 'MISSING')
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = '2026-01-20'

UNION ALL

SELECT 'TDZA', COUNT(*), IF(COUNT(*) > 0, 'COMPLETE', 'MISSING')
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = '2026-01-20'
```

**Quick check** (smoke test):
```bash
python scripts/smoke_test.py 2026-01-20
# Output: P4:PASS means ≥3 processors completed
```

**Notes**:
- Early season (first 14 days): Expect 50-90% processors to fail (bootstrap period)
- PDC is CRITICAL for predictions
- PSZA depends on box scores (cascades from Phase 2 failures)
- Phase 5 predictions need ≥3 processors to run

---

### Phase 5: Predictions (Model Outputs)

**What it does**: Generates player prop predictions from 5 systems

**Success Thresholds**:
- ✅ **EXCELLENT**: All 5 systems + MAE < 6 + predictions > 500
- ⚠️ **ACCEPTABLE**: All 5 systems present + MAE < 8
- ❌ **FAIL**: <5 systems OR no predictions

**Systems** (all required):
1. `moving_average_baseline`
2. `zone_matchup_v1`
3. `similarity_balanced_v1`
4. `xgboost_v1`
5. `ensemble_v1`

**How to verify**:
```sql
-- Check predictions
SELECT
  COUNT(*) as total_predictions,
  COUNT(DISTINCT system_id) as unique_systems,
  COUNT(DISTINCT player_lookup) as unique_players,
  ROUND(AVG(confidence), 2) as avg_confidence,
  ARRAY_AGG(DISTINCT system_id) as systems_present
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = '2026-01-20'
```

**Expected**:
- Systems: 5 (all present)
- Total predictions: 400-800 (varies by game count)
- Confidence: 0.3-0.7 average
- Unique players: 80-200 (varies by game count)

**Quick check** (smoke test):
```bash
python scripts/smoke_test.py 2026-01-20
# Output: P5:PASS means predictions exist
```

**Notes**:
- Will NOT run if Phase 4 has <3 processors
- Early season may skip if features not production-ready
- Recent dates (future) won't have predictions if no betting lines available

---

### Phase 6: Grading (Model Evaluation)

**What it does**: Compares predictions to actual game results

**Success Thresholds**:
- ✅ **EXCELLENT**: Coverage ≥ 95% of predictions
- ⚠️ **ACCEPTABLE**: Coverage ≥ 80% of predictions
- ❌ **FAIL**: Coverage < 80% OR no grading

**How to verify**:
```sql
-- Check grading coverage
SELECT
  p.game_date,
  COUNT(DISTINCT p.prediction_id) as total_predictions,
  COUNT(DISTINCT g.prediction_id) as total_graded,
  ROUND(COUNT(DISTINCT g.prediction_id) / COUNT(DISTINCT p.prediction_id) * 100, 1) as coverage_pct,
  ROUND(AVG(CASE WHEN g.prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate_pct
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
LEFT JOIN `nba-props-platform.nba_predictions.prediction_grades` g
  ON p.prediction_id = g.prediction_id
WHERE p.game_date = '2026-01-20'
GROUP BY p.game_date
```

**Expected**:
- Coverage: 80-100% (some predictions may fail to grade)
- Win rate: 45-65% (varies by date/quality)

**Quick check** (smoke test):
```bash
python scripts/smoke_test.py 2026-01-20
# Output: P6:PASS means grading exists
```

**Notes**:
- Grading runs 24-48 hours AFTER games complete
- Future dates won't have grading (games haven't happened)
- Some predictions fail to grade if actuals missing

---

## 🚦 Traffic Light System

Use this quick reference for any date:

| Health Score | Status | Action |
|-------------|--------|--------|
| **≥ 85%** | 🟢 **EXCELLENT** | No action needed, backfill succeeded |
| **70-84%** | 🟡 **ACCEPTABLE** | Backfill worked, minor gaps acceptable |
| **50-69%** | 🟠 **NEEDS REVIEW** | Investigate which phases failed |
| **< 50%** | 🔴 **FAILED** | Backfill failed, needs retry |

---

## 📋 Quick Verification Checklist

After running backfill for a date, verify:

- [ ] **Phase 2**: Box scores exist (≥1 source)
- [ ] **Phase 3**: All 3 analytics tables have data
- [ ] **Phase 4**: ≥3 processors completed
- [ ] **Phase 5**: All 5 systems generated predictions (if applicable)
- [ ] **Phase 6**: Grading coverage ≥80% (if applicable)
- [ ] **Overall**: Health score ≥70%

**Fast way**: Run smoke test
```bash
python scripts/smoke_test.py <YOUR_DATE>
# ✅ = PASS, ❌ = FAIL
```

---

## 🔧 Troubleshooting Guide

### If Phase 2 fails:
- **Cause**: BDL scraper failed or nbac gamebook missing
- **Action**: Re-run scraper backfill
- **Note**: This will cascade to Phase 4 PSZA

### If Phase 3 fails:
- **Cause**: Phase 2 data missing or analytics processor failed
- **Action**: Check Phase 2 first, then re-run Phase 3 backfill

### If Phase 4 fails:
- **Cause**: Missing upstream data (Phase 2/3) or processor timeout
- **Action**: Verify Phase 3 complete, then re-run Phase 4 backfill

### If Phase 5 fails:
- **Cause**: <3 Phase 4 processors or no betting lines
- **Action**: Verify Phase 4 complete (≥3 processors), check if lines available

### If Phase 6 fails:
- **Cause**: Game hasn't finished yet or actuals missing
- **Action**: Wait 24-48 hours after game, then trigger grading

---

## 📊 Batch Verification

For multiple dates:

```bash
# Verify 10 dates at once
python scripts/smoke_test.py 2026-01-10 2026-01-20

# Output shows PASS/FAIL per date
# Summary shows: 8/10 passed (80%)
```

For detailed analysis:
```bash
# Full validation with health scores
python scripts/validate_historical_season.py --start 2026-01-10 --end 2026-01-20
```

---

## ✅ Success Examples

**Excellent backfill** (Health ≥85%):
```
✅ 2026-01-20: P2:PASS P3:PASS P4:PASS P5:PASS P6:PASS [Overall: PASS]
Health score: 92.3%
- Phase 2: 100% coverage (all box scores)
- Phase 3: All 3 tables complete
- Phase 4: 4/4 processors
- Phase 5: All 5 systems, 687 predictions
- Phase 6: 95% grading coverage
```

**Acceptable backfill** (Health 70-84%):
```
⚠️ 2026-01-15: P2:PASS P3:PASS P4:PASS P5:PASS P6:FAIL [Overall: ACCEPTABLE]
Health score: 73.2%
- Phase 2: 85% coverage (some box scores missing)
- Phase 3: All 3 tables complete
- Phase 4: 3/4 processors (PSZA failed, expected)
- Phase 5: All 5 systems, 512 predictions
- Phase 6: 45% grading coverage (game just finished, more grading coming)
```

**Failed backfill** (Health <50%):
```
❌ 2024-10-22: P2:PASS P3:PASS P4:FAIL P5:FAIL P6:FAIL [Overall: FAIL]
Health score: 40.0%
- Phase 2: 100% coverage
- Phase 3: All 3 tables complete
- Phase 4: 0/4 processors (early season bootstrap, expected)
- Phase 5: No predictions (insufficient features)
- Phase 6: No grading
ACTION: This is early season - likely expected, verify bootstrap period
```

---

## 🎯 When to Backfill vs Skip

**Always backfill if**:
- Health score < 70%
- Phase 2 or 3 has 0 data
- Recent date (<14 days old)

**Consider skipping if**:
- Health score ≥ 85%
- >90 days old (historical data, low priority)
- Early season (Oct 22-Nov 5) with expected bootstrap failures

**Priority order**:
1. **CRITICAL**: Recent dates (<14 days) with <50% health
2. **HIGH**: Recent dates (<30 days) with 50-70% health
3. **MEDIUM**: Any date with Phase 2/3 failures (cascades)
4. **LOW**: Old dates (>60 days) with minor Phase 4/6 gaps

---

**Last Updated**: 2026-01-20
**Maintained By**: Data Engineering Team
**Questions**: Check #nba-alerts Slack channel
