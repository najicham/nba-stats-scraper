# Phase 4 Operations Guide - Precompute Processors

**File:** `docs/processors/05-phase4-operations-guide.md`
**Created:** 2025-11-15 15:30 PST
**Last Updated:** 2025-11-15 15:30 PST
**Purpose:** Operations guide for Phase 4 precompute processors (nba_analytics → nba_precompute)
**Status:** Draft (awaiting deployment)
**Audience:** Engineers deploying and operating Phase 4 precompute processors

**Related Docs:**
- **Scheduling:** See `06-phase4-scheduling-strategy.md` for dependency orchestration
- **Troubleshooting:** See `07-phase4-troubleshooting.md` for failure recovery
- **ML Feature Store Deep-Dive:** See `08-phase4-ml-feature-store-deepdive.md` for P5 details
- **Phase 3:** See `02-phase3-operations-guide.md` for upstream dependencies

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Phase 4 Mission](#phase-4-mission)
3. [System Architecture](#system-architecture)
4. [Processor Specifications](#processor-specifications)
5. [Daily Timeline](#daily-timeline)
6. [Success Criteria](#success-criteria)
7. [Quick Reference](#quick-reference)

---

## Executive Summary

### What is Phase 4?

**Phase 4** pre-aggregates analytics from Phase 3 into fast-query tables for Phase 5 predictions. Eliminates repeated BigQuery queries, enabling sub-second predictions.

**Input:** Phase 3 analytics tables (nba_analytics dataset)
**Output:** Phase 4 precompute tables (nba_precompute dataset) + ML features (nba_predictions dataset)
**Trigger:** Time-based (Cloud Scheduler at 11:00 PM ET) + Event-driven (Pub/Sub)
**Duration:** 25-40 minutes total (sequential with parallelization)

### Phase 4 Processors (5 total)

**Parallel Set 1 (Run simultaneously at 11:00 PM ET):**
1. **team_defense_zone_analysis** - Team defensive metrics (30 teams, 2 min)
2. **player_shot_zone_analysis** - Player shooting zones (450 players, 5-8 min)

**Parallel Set 2 (After Set 1 completes):**
3. **player_composite_factors** - Combined player factors (450 players, 10-15 min)
4. **player_daily_cache** - Pre-computed player stats (150-300 players, 5-10 min)

**Final (After all 4 complete):**
5. **ml_feature_store_v2** - ML features for predictions (450 players, 2 min)

### Current Status

**Deployment Status:** 🚧 Planned (not yet deployed)
**Expected Deployment:** TBD
**Dependencies:** Phase 3 analytics must be operational (🚧 Currently documented)

---

## Phase 4 Mission

Pre-aggregate analytics from Phase 3 into fast-query tables for Phase 5 predictions.

**Key Benefits:**
- **Speed:** Eliminates 15x slower Phase 3 queries during predictions
- **Cost:** Reduces Phase 5 BigQuery costs by 80%
- **Reliability:** Pre-computed data = predictable query performance
- **Quality:** Validates and scores data quality (0-100 scale)

**Critical Deadline:** Phase 5 predictions start at 6:00 AM ET and require complete Phase 4 data

### Timing Windows

| Phase | Timing | Purpose |
|-------|--------|---------|
| **Parallel Set 1** | 11:00-11:10 PM ET | Process team defense + player shot zones |
| **Parallel Set 2** | 11:30-11:45 PM ET | Process composite factors + daily cache |
| **ML Feature Store** | 12:00-12:05 AM ET | Assemble ML features |
| **Target Complete** | 12:30 AM ET | All Phase 4 done |
| **Hard Deadline** | 1:00 AM ET | Must complete before this |
| **Phase 5 Start** | 6:00 AM ET | Phase 5 predictions begin |

---

## System Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  Cloud Scheduler (11:00 PM ET)                                  │
│  Triggers: phase4-start (Pub/Sub topic)                         │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  Parallel Set 1: team_defense + player_shot_zone               │
│  Listen: phase4-start                                           │
│  Publish: team-defense-complete, player-shot-zone-complete     │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  Parallel Set 2: player_composite + player_daily_cache         │
│  Listen: team-defense-complete AND player-shot-zone-complete   │
│  Publish: player-composite-complete, player-daily-cache-complete │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  ml_feature_store_v2                                            │
│  Listen: ALL 4 upstream processors complete                     │
│  Publish: phase4-complete                                       │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  Phase 5 Predictions (6:00 AM ET)                               │
│  Listen: phase4-complete                                        │
└─────────────────────────────────────────────────────────────────┘
```

### Execution Strategy

**Sequential with Parallelization:**
- P1 + P2 run in parallel (11:00 PM)
- P3 + P4 wait for P1+P2, then run in parallel (11:30 PM)
- P5 waits for ALL 4, then runs alone (12:00 AM)

**Event-Driven:**
- Pub/Sub topics trigger downstream processors
- No fixed delays (adapts to processing speed)

**Fail-Fast:**
- Critical dependencies missing → processor fails immediately
- Clear error messages indicate which upstream processor failed

**Graceful Early Season:**
- First 3 weeks create placeholders (don't fail on insufficient data)
- Quality scores track data reliability

---

## Processor Specifications

### 1. Team Defense Zone Analysis

**Cloud Run Job:** `phase4-team-defense-zone-analysis`
**Purpose:** Pre-aggregate defensive metrics by zone for all teams

| Attribute | Value |
|-----------|-------|
| **Trigger** | Pub/Sub: phase4-start (parallel with P2) |
| **Duration** | 2 minutes (typical), 5 minutes (alert threshold) |
| **Volume** | 30 teams |
| **Output Table** | nba_precompute.team_defense_zone_analysis |
| **Strategy** | DELETE all existing → INSERT 30 new rows |

**Dependencies:**

**CRITICAL:**
- ✅ `nba_analytics.team_defense_game_summary` (Phase 3)

**Downstream:**
- Blocks: `player_composite_factors` (P3)
- Feeds: `ml_feature_store_v2` (P5, features 13-14)

**Success Criteria:**
```sql
-- Must have exactly 30 teams
SELECT COUNT(*) = 30 as success
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE();
```

**Key Features:**
- Zone-based defensive ratings
- Opponent shooting percentages by zone
- Defensive strength scores

**Early Season Behavior:**
- First 3 weeks: May create <30 rows (some teams with <10 games)
- Don't fail: Placeholders acceptable
- Alert: Only if 0 rows (actual failure)

---

### 2. Player Shot Zone Analysis

**Cloud Run Job:** `phase4-player-shot-zone-analysis`
**Purpose:** Pre-aggregate shooting performance by zone for all players

| Attribute | Value |
|-----------|-------|
| **Trigger** | Pub/Sub: phase4-start (parallel with P1) |
| **Duration** | 5-8 minutes (typical), 15 minutes (alert threshold) |
| **Volume** | ~450 active players |
| **Output Table** | nba_precompute.player_shot_zone_analysis |
| **Strategy** | DELETE all existing → INSERT 450 new rows |

**Dependencies:**

**CRITICAL:**
- ✅ `nba_analytics.player_game_summary` (Phase 3)

**OPTIONAL:**
- `nba_analytics.bigdataball_play_by_play` (shot zones enhancement)

**Downstream:**
- Blocks: `player_composite_factors` (P3), `player_daily_cache` (P4), `ml_feature_store_v2` (P5)
- Feeds: All downstream processors depend on this

**Success Criteria:**
```sql
-- Must have at least 400 players
SELECT COUNT(*) >= 400 as success
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE();
```

**Key Features:**
- FG% by zone (paint, mid-range, 3PT)
- Shot volume trends
- Zone preference analysis

**Early Season Behavior:**
- First 3 weeks: May create <400 rows (many players with <7 games)
- Don't fail: Placeholders acceptable
- Alert: Only if <100 rows (actual failure)

---

### 3. Player Composite Factors

**Cloud Run Job:** `phase4-player-composite-factors`
**Purpose:** Combine multiple data sources into composite player factors

| Attribute | Value |
|-----------|-------|
| **Trigger** | Pub/Sub: BOTH team-defense-complete AND player-shot-zone-complete |
| **Duration** | 10-15 minutes (typical), 20 minutes (alert threshold) |
| **Volume** | ~450 players with games next day |
| **Output Table** | nba_precompute.player_composite_factors |
| **Strategy** | DELETE existing date → INSERT 450 new rows |

**Dependencies:**

**CRITICAL (BOTH required):**
- ✅ `nba_precompute.team_defense_zone_analysis` (P1)
- ✅ `nba_precompute.player_shot_zone_analysis` (P2)
- ✅ `nba_analytics.upcoming_player_game_context` (Phase 3)
- ✅ `nba_analytics.upcoming_team_game_context` (Phase 3)

**Downstream:**
- Blocks: `ml_feature_store_v2` (P5)
- Feeds: ML features 5-8

**Success Criteria:**
```sql
-- Must have at least 100 players
SELECT COUNT(*) >= 100 as success
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE();
```

**Key Features:**
- Fatigue composite (rest + back-to-back + minutes)
- Matchup strength (player vs opponent defense)
- Betting context (line movement + public sentiment)
- Momentum factors (recent performance trends)

**Early Season Behavior:**
- First 3 weeks: Uses defaults when sources incomplete
- Creates records with default values instead of failing
- Alert: Only if 0 rows (actual failure)

---

### 4. Player Daily Cache

**Cloud Run Job:** `phase4-player-daily-cache`
**Purpose:** Pre-compute rolling aggregates for fast Phase 5 queries

| Attribute | Value |
|-----------|-------|
| **Trigger** | Pub/Sub: player-shot-zone-complete |
| **Duration** | 5-10 minutes (typical), 15 minutes (alert threshold) |
| **Volume** | ~150-300 players with games next day |
| **Output Table** | nba_precompute.player_daily_cache |
| **Strategy** | DELETE existing date → INSERT new rows |

**Dependencies:**

**CRITICAL:**
- ✅ `nba_precompute.player_shot_zone_analysis` (P2)
- ✅ `nba_analytics.player_game_summary` (Phase 3, 180 days lookback)
- ✅ `nba_analytics.team_offense_game_summary` (Phase 3, 30 days lookback)
- ✅ `nba_analytics.upcoming_player_game_context` (Phase 3)

**Downstream:**
- Blocks: `ml_feature_store_v2` (P5)
- Feeds: ML features 0-4, 22-23

**Success Criteria:**
```sql
-- Must have at least 100 players (game day)
SELECT COUNT(*) >= 100 as success
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE();
```

**Key Features:**
- Points/rebounds/assists averages (last 5/10/30 days)
- Usage rate trends
- Team pace factors
- Prop line history

**Early Season Behavior:**
- First 3 weeks: Skips players with <5 games
- May have <100 rows (acceptable early season)
- Alert: Only if 0 rows on game day (actual failure)

---

### 5. ML Feature Store V2

**Cloud Run Job:** `phase4-ml-feature-store-v2`
**Purpose:** Assemble 25 ML features from all Phase 4 + Phase 3 sources

| Attribute | Value |
|-----------|-------|
| **Trigger** | Pub/Sub: ALL 4 upstream processors complete |
| **Duration** | 2 minutes (typical), 5 minutes (alert threshold) |
| **Volume** | ~450 players with games next day |
| **Output Table** | **nba_predictions.ml_feature_store_v2** (cross-dataset!) |
| **Strategy** | DELETE existing date → Batch INSERT (100 rows per batch) |

**Dependencies:**

**CRITICAL (ALL 4 required):**
- ✅ `nba_precompute.team_defense_zone_analysis` (P1)
- ✅ `nba_precompute.player_shot_zone_analysis` (P2)
- ✅ `nba_precompute.player_composite_factors` (P3)
- ✅ `nba_precompute.player_daily_cache` (P4)

**FALLBACK (if Phase 4 incomplete):**
- `nba_analytics.player_game_summary` (Phase 3)
- `nba_analytics.upcoming_player_game_context` (Phase 3)
- `nba_analytics.team_offense_game_summary` (Phase 3)

**Downstream:**
- Blocks: ALL Phase 5 prediction systems
- This is the single source of truth for predictions

**Success Criteria:**
```sql
-- Must have at least 100 players with quality >= 70
SELECT
  COUNT(*) >= 100 as enough_players,
  AVG(feature_quality_score) >= 70 as good_quality
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
```

**Key Features:**
- 25 features total (see deep-dive doc for complete list)
- Quality score (0-100) based on data sources
- Phase 3 fallback for missing Phase 4 data
- Cross-dataset write (nba_predictions not nba_precompute)

**Unique Characteristics:**
- **Most complex processor** in Phase 4
- **4-way dependency** (most in system)
- **Intelligent fallback** (Phase 3 if Phase 4 fails)
- **Quality scoring** (tracks data reliability)
- **Cross-dataset write** (special IAM permissions required)

**See:** `08-phase4-ml-feature-store-deepdive.md` for complete details

**Early Season Behavior:**
- First 3 weeks: Creates placeholders with NULL features
- Quality scores will be low (<50)
- Don't fail: Placeholders acceptable
- Alert: Only if 0 rows on game day (actual failure)

---

## Daily Timeline

### Typical Night (19 games scheduled next day)

```
11:00 PM ET - Cloud Scheduler Triggers
├─ Pub/Sub: phase4-start published
└─ P1 + P2 start in parallel

11:00-11:02 PM - P1: team_defense_zone_analysis ⏱️ 2 minutes
├─ Process 30 teams
├─ Write to nba_precompute.team_defense_zone_analysis
└─ Pub/Sub: team-defense-complete published

11:00-11:08 PM - P2: player_shot_zone_analysis ⏱️ 8 minutes (parallel with P1)
├─ Process 450 players
├─ Write to nba_precompute.player_shot_zone_analysis
└─ Pub/Sub: player-shot-zone-complete published

11:30 PM - Both P1 + P2 Complete
├─ P3 + P4 start in parallel (different triggers)

11:30-11:45 PM - P3: player_composite_factors ⏱️ 15 minutes
├─ Wait for BOTH P1 + P2 complete
├─ Process 450 players
├─ Write to nba_precompute.player_composite_factors
└─ Pub/Sub: player-composite-complete published

11:30-11:40 PM - P4: player_daily_cache ⏱️ 10 minutes (parallel with P3)
├─ Wait for P2 complete (independent of P1)
├─ Process 200 players (only those with games tomorrow)
├─ Write to nba_precompute.player_daily_cache
└─ Pub/Sub: player-daily-cache-complete published

12:00 AM - All P1-P4 Complete
├─ P5 starts (waits for ALL 4)

12:00-12:02 AM - P5: ml_feature_store_v2 ⏱️ 2 minutes
├─ Wait for P1 + P2 + P3 + P4 ALL complete
├─ Assemble 25 features from all sources
├─ Calculate quality scores
├─ Write to nba_predictions.ml_feature_store_v2
└─ Pub/Sub: phase4-complete published

12:30 AM - Target Complete
└─ All Phase 4 done (30 minutes before hard deadline)
```

**Total Phase 4 Duration:**
- Critical path: P2 (8 min) → P3 (15 min) → P5 (2 min) = **25 minutes**
- Parallelization saves: 7 minutes vs sequential (27% faster)

---

## Success Criteria

### Critical Metrics

| Metric | Query | Alert Threshold |
|--------|-------|-----------------|
| **P1 Rows** | `SELECT COUNT(*) FROM team_defense_zone_analysis WHERE analysis_date = CURRENT_DATE()` | < 20 teams |
| **P2 Rows** | `SELECT COUNT(*) FROM player_shot_zone_analysis WHERE analysis_date = CURRENT_DATE()` | < 400 players |
| **P3 Rows** | `SELECT COUNT(*) FROM player_composite_factors WHERE game_date = CURRENT_DATE()` | < 100 players |
| **P4 Rows** | `SELECT COUNT(*) FROM player_daily_cache WHERE cache_date = CURRENT_DATE()` | < 100 players (game day) |
| **P5 Rows** | `SELECT COUNT(*) FROM ml_feature_store_v2 WHERE game_date = CURRENT_DATE()` | < 100 players |
| **P5 Quality** | `SELECT AVG(feature_quality_score) FROM ml_feature_store_v2 WHERE game_date = CURRENT_DATE()` | < 70 (after week 3) |
| **Processing Time** | Track via logs: completed_at - trigger_time per processor | > processor max duration |
| **Overall Duration** | Time from phase4-start to phase4-complete | > 60 minutes |

### Overall Phase 4 Status Check

```sql
-- Check if all processors completed today
SELECT
  'team_defense' as processor,
  CASE WHEN COUNT(*) >= 20 THEN '✅' ELSE '❌' END as status,
  COUNT(*) as rows,
  MAX(processed_at) as last_run
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT
  'player_shot_zone',
  CASE WHEN COUNT(*) >= 400 THEN '✅' ELSE '❌' END,
  COUNT(*),
  MAX(processed_at)
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT
  'player_composite',
  CASE WHEN COUNT(*) >= 100 THEN '✅' ELSE '❌' END,
  COUNT(*),
  MAX(processed_at)
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()

UNION ALL

SELECT
  'player_daily_cache',
  CASE WHEN COUNT(*) >= 100 THEN '✅' ELSE '❌' END,
  COUNT(*),
  MAX(processed_at)
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()

UNION ALL

SELECT
  'ml_feature_store',
  CASE WHEN COUNT(*) >= 100 AND AVG(feature_quality_score) >= 70 THEN '✅' ELSE '❌' END,
  COUNT(*),
  MAX(created_at)
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
```

**Expected Output (Healthy System):**
```
processor           | status | rows | last_run
--------------------|--------|------|-------------------------
team_defense        | ✅     | 30   | 2025-11-15 23:02:15 UTC
player_shot_zone    | ✅     | 452  | 2025-11-15 23:08:42 UTC
player_composite    | ✅     | 435  | 2025-11-15 23:45:18 UTC
player_daily_cache  | ✅     | 178  | 2025-11-15 23:40:05 UTC
ml_feature_store    | ✅     | 435  | 2025-11-16 00:02:33 UTC
```

---

## Quick Reference

### Cloud Run Jobs

```bash
# List all Phase 4 jobs
gcloud run jobs list --region=us-central1 | grep phase4

# View job details
gcloud run jobs describe phase4-team-defense-zone-analysis --region=us-central1

# View recent executions
gcloud run jobs executions list --job=phase4-team-defense-zone-analysis --region=us-central1 --limit=5
```

### Manual Triggers

**Trigger entire Phase 4 pipeline:**
```bash
# Trigger via Pub/Sub (starts P1 + P2)
gcloud pubsub topics publish phase4-start \
  --message '{"processor":"phase4_start","phase":"4","analysis_date":"'$(date +%Y-%m-%d)'"}'
```

**Trigger individual processors:**
```bash
# P1: Team defense
gcloud run jobs execute phase4-team-defense-zone-analysis \
  --region us-central1 \
  --set-env-vars "ANALYSIS_DATE=$(date +%Y-%m-%d)"

# P2: Player shot zones
gcloud run jobs execute phase4-player-shot-zone-analysis \
  --region us-central1 \
  --set-env-vars "ANALYSIS_DATE=$(date +%Y-%m-%d)"

# P3: Player composite (after P1+P2 complete)
gcloud run jobs execute phase4-player-composite-factors \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"

# P4: Player daily cache (after P2 complete)
gcloud run jobs execute phase4-player-daily-cache \
  --region us-central1 \
  --set-env-vars "CACHE_DATE=$(date +%Y-%m-%d)"

# P5: ML feature store (after ALL 4 complete)
gcloud run jobs execute phase4-ml-feature-store-v2 \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"
```

### Key BigQuery Tables

| Table | Purpose | Partition | Update Frequency |
|-------|---------|-----------|------------------|
| `nba_precompute.team_defense_zone_analysis` | Team defensive metrics | analysis_date | Once nightly (11 PM) |
| `nba_precompute.player_shot_zone_analysis` | Player shooting zones | analysis_date | Once nightly (11 PM) |
| `nba_precompute.player_composite_factors` | Combined player factors | game_date | Once nightly (11:30 PM) |
| `nba_precompute.player_daily_cache` | Pre-computed player stats | cache_date | Once nightly (11:30 PM) |
| `nba_predictions.ml_feature_store_v2` | ML features (cross-dataset!) | game_date | Once nightly (12 AM) |

### Common Queries

**Check today's processing:**
```sql
-- Simple row count check (all processors)
SELECT
  COUNT(*) as team_defense_rows
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE();
-- Expected: 30 teams

SELECT
  COUNT(*) as player_shot_zone_rows
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE();
-- Expected: 400-500 players

SELECT
  COUNT(*) as ml_features_rows,
  AVG(feature_quality_score) as avg_quality
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
-- Expected: 400-500 players, quality 85-100
```

**Processing time breakdown:**
```sql
-- See how long each processor took
SELECT
  'team_defense' as processor,
  MIN(processed_at) as start_time,
  MAX(processed_at) as end_time,
  TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), SECOND) as duration_seconds
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
-- Repeat for each processor
```

### Troubleshooting Quick Links

| Issue | See |
|-------|-----|
| **All Phase 4 fails** | `07-phase4-troubleshooting.md` → Scenario 6 (Phase 3 incomplete) |
| **P2 fails (blocks everything)** | `07-phase4-troubleshooting.md` → Scenario 2 |
| **P5 (ML Feature Store) fails** | `08-phase4-ml-feature-store-deepdive.md` → Incident Response |
| **Dependency orchestration issues** | `06-phase4-scheduling-strategy.md` → Dependency Management |
| **Cross-dataset permission errors** | `08-phase4-ml-feature-store-deepdive.md` → Cross-Dataset Write |
| **Early season low quality** | `07-phase4-troubleshooting.md` → Scenario 7 (Early Season) |

---

## Related Documentation

**Scheduling & Orchestration:**
- `06-phase4-scheduling-strategy.md` - Dependency management, Cloud Scheduler, Pub/Sub

**Troubleshooting:**
- `07-phase4-troubleshooting.md` - Failure scenarios, recovery procedures

**ML Feature Store Deep-Dive:**
- `08-phase4-ml-feature-store-deepdive.md` - Complete P5 documentation

**Infrastructure:**
- `docs/infrastructure/01-pubsub-integration-verification.md` - Pub/Sub setup

**Upstream Dependencies:**
- `02-phase3-operations-guide.md` - Phase 3 analytics processors

**Monitoring:**
- `docs/monitoring/01-grafana-monitoring-guide.md` - Grafana dashboards

---

**Last Updated:** 2025-11-15 15:30 PST
**Status:** 🚧 Draft (awaiting deployment)
**Next Review:** After Phase 4 deployment
