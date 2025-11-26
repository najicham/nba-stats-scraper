# Daily Processing Timeline - Workflow Card

**Last Updated**: 2025-11-15
**Type**: Workflow Reference Card
**Purpose**: Complete daily orchestration sequence from game completion to prediction readiness

---

## Timeline Overview

```
7:00 PM - 10:00 PM  │ Games complete throughout evening
10:00 PM - 10:30 PM │ Phase 3 Analytics (game-level)
10:30 PM - 11:00 PM │ Phase 3 Analytics (context)
11:00 PM - 12:00 AM │ Phase 4 Precompute (nightly sequence)
12:00 AM - 6:00 AM  │ System ready for next day
6:15 AM             │ Phase 5 Prediction Coordinator (batch predictions)
6:15 AM - 11:00 PM  │ Phase 5 Real-time updates (when odds change)
```

---

## Detailed Sequence

### Evening: Games Complete (7:00 PM - 10:00 PM)

**What Happens:**
- NBA games finish throughout evening (typically 7-10 PM ET)
- Phase 2 scrapers run on game completion triggers
- Raw data lands in `nba_raw.*` tables

**Tables Updated:**
- `nba_raw.nbac_gamebook_player_stats`
- `nba_raw.bdl_player_boxscores`
- `nba_raw.nbac_team_boxscore`
- `nba_raw.bigdataball_play_by_play`

**Monitoring:**
- Check scraper Cloud Run logs
- Verify row counts in raw tables
- Alert if games missing after 2 hours

---

### Phase 3 Part 1: Game-Level Analytics (10:00 PM - 10:30 PM)

**Processors Run:**
1. **Player Game Summary** (2-5 min)
   - Reads: 6 Phase 2 sources
   - Writes: `nba_analytics.player_game_summary`
   - Output: ~300 player records per game

2. **Team Offense Game Summary** (1-2 min)
   - Reads: `nbac_team_boxscore`, `nbac_play_by_play`
   - Writes: `nba_analytics.team_offense_game_summary`
   - Output: 2 team records per game

3. **Team Defense Game Summary** (2-3 min)
   - Reads: `nbac_team_boxscore`, `nbac_gamebook_player_stats`
   - Writes: `nba_analytics.team_defense_game_summary`
   - Output: 2 team records per game

**Total Time:** ~5-10 minutes
**Success Criteria:** All games from tonight have analytics records

---

### Phase 3 Part 2: Context Analytics (10:30 PM - 11:00 PM)

**Processors Run:**
4. **Upcoming Player Game Context** (3-5 min)
   - Reads: Schedule, props, historical player data
   - Writes: `nba_analytics.upcoming_player_game_context`
   - Output: ~450 players for tomorrow's games

5. **Upcoming Team Game Context** (1-2 min)
   - Reads: Schedule, odds, injuries, team data
   - Writes: `nba_analytics.upcoming_team_game_context`
   - Output: ~30 teams for tomorrow's games

**Total Time:** ~5-7 minutes
**Success Criteria:** All tomorrow's games have context records

---

### Phase 4: Nightly Precompute Sequence (11:00 PM - 12:00 AM)

**CRITICAL: These must run in order due to dependencies**

#### 11:00 PM - P1: Team Defense Zone Analysis (~2 min)
```
Phase 3: team_defense_game_summary
    ↓
Phase 4: team_defense_zone_analysis (30 teams)
```
- **Window:** Last 15 games per team
- **Output:** Zone strengths/weaknesses by team
- **Consumers:** Player Composite Factors (P3)

#### 11:15 PM - P2: Player Shot Zone Analysis (~5-8 min)
```
Phase 3: player_game_summary
    ↓
Phase 4: player_shot_zone_analysis (450 players)
```
- **Window:** Last 10 & 20 games per player
- **Output:** Shot distribution and efficiency by zone
- **Consumers:** Player Composite Factors (P3)
- **Can run in PARALLEL with P1** (both read Phase 3 only)

#### 11:30 PM - P3: Player Composite Factors (~10-15 min)
```
Phase 3: upcoming_player_context + upcoming_team_context
Phase 4: player_shot_zone_analysis + team_defense_zone_analysis
    ↓
Phase 4: player_composite_factors (450 players)
```
- **Calculates:** 4 active adjustment factors (fatigue, matchup, pace, usage)
- **Output:** Composite scores for today's players
- **Consumers:** ML Feature Store (P5)
- **WAITS FOR:** P1 and P2 to complete

#### 12:00 AM - P4 & P5: Cache and Features (~7-12 min)
```
Phase 3: player_game_summary + team_offense + upcoming_player
Phase 4: player_shot_zone_analysis
    ↓
Phase 4: player_daily_cache (450 players)

ALL Phase 3 + ALL Phase 4 (P1-P3)
    ↓
nba_predictions: ml_feature_store_v2 (450 players)
```
- **P4 - Player Daily Cache** (5-10 min):
  - Caches static daily stats (won't change during day)
  - Saves $27/month by avoiding repeated queries

- **P5 - ML Feature Store V2** (~2 min):
  - Extracts 25 features with Phase 4 → Phase 3 fallback
  - Quality scoring based on data sources
  - **Can run in PARALLEL with P4** (independent)

**Total Phase 4 Time:** ~20-27 minutes
**Success Criteria:** All 5 processors complete by 12:30 AM

---

### Early Morning: System Ready (12:00 AM - 6:00 AM)

**What Happens:**
- All precompute tables are fresh
- System is idle (no processing)
- Data is ready for Phase 5 predictions

**Tables Ready:**
- ✅ `nba_precompute.team_defense_zone_analysis`
- ✅ `nba_precompute.player_shot_zone_analysis`
- ✅ `nba_precompute.player_composite_factors`
- ✅ `nba_precompute.player_daily_cache`
- ✅ `nba_predictions.ml_feature_store_v2`

---

### Morning: Phase 5 Batch Predictions (6:15 AM)

**Coordinator Triggered:** Cloud Scheduler job `phase5-daily-predictions-trigger`

**What Happens:**
1. **Prediction Coordinator** starts (Cloud Run Job)
2. Loads daily cache from Phase 4 (player_daily_cache + ml_feature_store_v2)
3. Spawns **Worker** instances to run 5 prediction systems in parallel
4. Generates initial predictions for all players with games today

**Prediction Systems (All 5 Run):**
- **Moving Average Baseline** - Simple baseline (always works)
- **XGBoost V1** - Primary ML model (needs trained model)
- **Zone Matchup V1** - Shot zone analysis
- **Similarity Balanced V1** - Pattern matching
- **Ensemble V1** - Combines all 4 systems with confidence weighting

**Output Table:**
- `nba_predictions.player_points_predictions` (100-450 players)
- Each player gets: ensemble_prediction, ensemble_confidence, recommendation (OVER/UNDER/PASS)

**Duration:** 2-5 minutes for all predictions

**Real-Time Updates:**
- 6:15 AM - 11:00 PM: When odds change, workers re-run predictions (<1s per update)
- Uses cached player data (no additional BQ queries)

**References:**
- Phase 5 processor card: `docs/processor-cards/phase5-prediction-coordinator.md`
- Real-time flow: `docs/processor-cards/workflow-realtime-prediction-flow.md`
- Phase 5 getting started: `docs/predictions/tutorials/01-getting-started.md`

---

## Timing Dependencies

```
Phase 3 Game Analytics (10:00-10:30 PM)
    ├─→ Phase 3 Context (10:30-11:00 PM)
    └─→ Phase 4 Zone Analysis (11:00-11:30 PM)
            ├─→ Team Defense Zone (P1) ──┐
            └─→ Player Shot Zone (P2) ────┤
                                          ├─→ Player Composite (P3) ──┐
                                          │                           │
Phase 3 Context ──────────────────────────┘                           │
                                                                      │
All Phase 3 + Phase 4 P1-P3 ──────────────────────────────────────→ ML Feature Store (P5)
All Phase 3 ──────────────────────────────────────────────────────→ Player Daily Cache (P4)
```

---

## Health Checks

### 10:45 PM - Phase 3 Game Analytics Complete?
```sql
-- Expect: 2 teams × 10-15 games = 20-30 rows
SELECT COUNT(*) FROM nba_analytics.team_offense_game_summary
WHERE game_date = CURRENT_DATE();

-- Expect: ~300 players × 10-15 games = 3000-4500 rows
SELECT COUNT(*) FROM nba_analytics.player_game_summary
WHERE game_date = CURRENT_DATE();
```

### 11:15 PM - Phase 3 Context Complete?
```sql
-- Expect: ~450 players for tomorrow
SELECT COUNT(*) FROM nba_analytics.upcoming_player_game_context
WHERE game_date = CURRENT_DATE() + 1;

-- Expect: ~30 teams for tomorrow
SELECT COUNT(*) FROM nba_analytics.upcoming_team_game_context
WHERE game_date = CURRENT_DATE() + 1;
```

### 12:30 AM - Phase 4 Complete?
```sql
-- Expect: 30 teams
SELECT COUNT(*) FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = CURRENT_DATE();

-- Expect: 400-450 players
SELECT COUNT(*) FROM nba_precompute.player_shot_zone_analysis
WHERE analysis_date = CURRENT_DATE();

-- Expect: 400-450 players
SELECT COUNT(*) FROM nba_precompute.player_composite_factors
WHERE game_date = CURRENT_DATE() + 1;

-- Expect: 100-450 players (game day dependent)
SELECT COUNT(*) FROM nba_precompute.player_daily_cache
WHERE cache_date = CURRENT_DATE() + 1;

-- Expect: 100-450 players (game day dependent)
SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE() + 1;
```

### 7:00 AM - Phase 5 Predictions Complete?
```sql
-- Expect: 100-450 predictions (depends on games today)
SELECT
  COUNT(*) as prediction_count,
  AVG(ensemble_confidence) as avg_confidence,
  COUNT(CASE WHEN recommendation != 'PASS' THEN 1 END) as actionable_picks,
  AVG(systems_count) as avg_systems
FROM `nba_predictions.player_points_predictions`
WHERE prediction_date = CURRENT_DATE();

-- Expected values:
-- prediction_count: 100-450
-- avg_confidence: 70-80
-- actionable_picks: 30-150 (30-50% actionable)
-- avg_systems: 3.8-4.0 (all 4 systems should run)
```

---

## Common Issues

### Issue 1: Phase 4 Starts Before Phase 3 Complete
**Symptom:** Low row counts in Phase 4 tables
**Fix:** Check orchestration triggers - Phase 4 should wait for Phase 3 completion events

### Issue 2: Phase 4 P3 Fails (Missing Dependencies)
**Symptom:** `player_composite_factors` has 0 rows
**Diagnosis:** Check if P1 (team defense zone) and P2 (player shot zone) completed
**Fix:** Ensure P3 doesn't start until P1 and P2 both emit completion events

### Issue 3: Phase 5 Loads Stale Cache
**Symptom:** Predictions using yesterday's data
**Diagnosis:** Check `cache_date` field in loaded data
**Fix:** Verify Phase 4 completed before 6:15 AM startup
**Reference:** See `docs/operations/cross-phase-troubleshooting-matrix.md` Section 1.3

### Issue 4: No Games Tomorrow (Off Day)
**Symptom:** 0 rows in Phase 4 daily cache and ML feature store
**Expected:** This is normal! On off-days (no games scheduled):
- Phase 3 context processors skip (no players to process)
- Phase 4 cache/features are empty
- Phase 5 has nothing to predict
**Action:** No fix needed, this is expected behavior

---

## Performance Benchmarks

| Phase | Duration | Tables Updated | Rows/Day |
|-------|----------|----------------|----------|
| Phase 3 Game Analytics | 5-10 min | 3 tables | 3,000-4,500 |
| Phase 3 Context | 5-7 min | 2 tables | ~480 |
| Phase 4 Zone Analysis | 7-10 min | 2 tables | ~480 |
| Phase 4 Composite/Cache | 12-17 min | 3 tables | ~900 |
| Phase 5 Batch Predictions | 2-5 min | 1 table | ~450 |
| **Total** | **31-49 min** | **11 tables** | **~6,310** |

---

## Monitoring Alerts

| Time | Check | Threshold | Severity |
|------|-------|-----------|----------|
| 10:45 PM | Phase 3 game analytics complete | Within 45 min of last game | Warning |
| 11:15 PM | Phase 3 context complete | By 11:15 PM | Critical |
| 11:30 PM | Phase 4 P1+P2 complete | By 11:30 PM | Critical |
| 12:30 AM | Phase 4 all complete | By 12:30 AM | Critical |
| 6:15 AM | Phase 5 predictions start | Coordinator triggered | Warning |
| 6:30 AM | Phase 5 batch complete | < 15 min duration | Warning |
| 7:00 AM | Phase 5 predictions available | prediction_count > 100 | Critical |

---

## Quick Links

- 📄 **Processor Cards**: `docs/processor-cards/README.md`
- 📊 **Orchestration Details**: `docs/orchestration/01-how-it-works.md`
- 🔍 **Monitoring Guide**: `docs/monitoring/01-grafana-monitoring-guide.md`
- ⚡ **Real-Time Flow**: `docs/processor-cards/workflow-realtime-prediction-flow.md`
- 🤖 **Phase 5 Details**: `docs/processor-cards/phase5-prediction-coordinator.md`
- 🎯 **Phase 5 Getting Started**: `docs/predictions/tutorials/01-getting-started.md`

---

**Card Version**: 1.0
**Created**: 2025-11-15
**Verified Against**: Production orchestration (commit 71f4bde)
