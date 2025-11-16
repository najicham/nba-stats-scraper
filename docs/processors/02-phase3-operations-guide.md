# Phase 3 Operations Guide - Analytics Processors

**File:** `docs/processors/02-phase3-operations-guide.md`
**Created:** 2025-11-15 14:30 PST
**Last Updated:** 2025-11-15 14:30 PST
**Purpose:** Operations guide for Phase 3 analytics processors (nba_raw → nba_analytics)
**Status:** Draft (awaiting deployment)
**Audience:** Engineers deploying and operating Phase 3 analytics processors

**Related Docs:**
- **Scheduling:** See `03-phase3-scheduling-strategy.md` for Cloud Scheduler and Pub/Sub configuration
- **Troubleshooting:** See `04-phase3-troubleshooting.md` for failure recovery and runbooks
- **Architecture:** See `docs/architecture/04-event-driven-pipeline-architecture.md` for overall design

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Phase 3 Mission](#phase-3-mission)
3. [System Architecture](#system-architecture)
4. [Processor Specifications](#processor-specifications)
5. [Daily Timeline](#daily-timeline)
6. [Success Criteria](#success-criteria)
7. [Quick Reference](#quick-reference)

---

## Executive Summary

### What is Phase 3?

**Phase 3** transforms raw Phase 2 data into analytics-ready tables that combine multi-source data, universal player identification, comprehensive validation, and pre-game context generation.

**Input:** Phase 2 raw tables (nba_raw dataset)
**Output:** Phase 3 analytics tables (nba_analytics dataset)
**Trigger:** Time-based (Cloud Scheduler) + Event-driven (Pub/Sub)
**Duration:** 30-40 seconds total for all processors

### Phase 3 Processors (5 total)

**Historical Data (Run once daily at 2:30 AM ET):**
1. **player_game_summary** - Player performance across all games (450 rows/day)
2. **team_offense_game_summary** - Team offensive stats (20-30 rows/day)
3. **team_defense_game_summary** - Team defensive stats (20-30 rows/day)

**Upcoming Context (Run multiple times daily: 6 AM, 12 PM, 5 PM ET):**
4. **upcoming_team_game_context** - Pre-game team context (60 rows/day)
5. **upcoming_player_game_context** - Pre-game player context (150-250 rows/day)

### Current Status

**Deployment Status:** 🚧 Planned (not yet deployed)
**Expected Deployment:** TBD
**Dependencies:** Phase 2 processors must be operational (✅ Currently deployed)

---

## Phase 3 Mission

Transform raw Phase 2 data into analytics-ready tables combining:
- **Multi-source fallback** - Primary + fallback data sources for reliability
- **Universal player IDs** - Consistent player identification across all sources
- **Comprehensive validation** - Data quality checks and graceful degradation
- **Pre-game context** - Fatigue, betting, injury, and momentum factors

**Critical Deadline:** Phase 4 processors start at 11:00 PM ET and require complete Phase 3 data

### Timing Windows

| Phase | Timing | Purpose |
|-------|--------|---------|
| **Historical** | 2:30-2:40 AM ET | Process yesterday's completed games |
| **Morning Context** | 6:00-6:30 AM ET | Initial context after props scraped |
| **Midday Context** | 12:00-12:30 PM ET | Updated injury reports |
| **Pre-Game Context** | 5:00-5:30 PM ET | Final betting lines |
| **Phase 4 Deadline** | 11:00 PM ET | Phase 4 precompute starts |

---

## System Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  Phase 2 Complete (2:00 AM ET)                                   │
│  All scrapers finished, raw data in BigQuery                     │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  Parallel Set: Historical Game Data (2:30 AM ET)                │
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐│
│  │ player_game      │  │ team_offense     │  │ team_defense  ││
│  │ summary          │  │ game_summary     │  │ game_summary  ││
│  │ (3-5s)           │  │ (3-5s)           │  │ (3-5s)        ││
│  └──────────────────┘  └──────────────────┘  └───────────────┘│
│                                                                   │
│  Listen: nba-raw-data-complete (event-driven)                   │
│  Fallback: phase3-start (time-based 2:30 AM)                    │
│  Publish: phase3-historical-complete                             │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  Sequential Set 1: Team Context (6:00 AM ET)                    │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ upcoming_team_game_context                                │  │
│  │ (5-10s)                                                    │  │
│  │ Multiple runs: 6 AM, 12 PM, 5 PM ET                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                   │
│  Listen: props-updated OR time-based (6 AM, 12 PM, 5 PM)        │
│  Publish: team-context-updated                                   │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  Sequential Set 2: Player Context (6:30 AM ET)                  │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ upcoming_player_game_context                              │  │
│  │ (5-15s)                                                    │  │
│  │ Multiple runs: 6:30 AM, 12:30 PM, 5:30 PM ET             │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                   │
│  Listen: props-updated OR team-context-updated                   │
│  Publish: phase3-complete                                        │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  Phase 4 Precompute (11:00 PM ET)                               │
│  Uses complete Phase 3 analytics data                            │
└─────────────────────────────────────────────────────────────────┘
```

### Execution Strategy

**Parallel Execution (Historical):**
- First 3 processors have no inter-dependencies
- Run simultaneously at 2:30 AM ET
- Combined duration: max(3s, 3s, 3s) = ~3-5 seconds (not 9-15 sequential)

**Sequential Execution (Upcoming Context):**
- Team context runs first (independent)
- Player context waits 30 min to use team context (optional)
- Both triggered by props-updated event

**Event-Driven:**
- Multiple triggers throughout day for "upcoming" processors
- Responds to betting lines and injury report updates
- Pub/Sub topics: props-updated, team-context-updated, phase3-complete

**Fail-Fast:**
- Critical dependencies missing → processor fails immediately with clear error
- Graceful degradation for optional sources → continue with partial data, log warnings

---

## Processor Specifications

### 1. Player Game Summary

**Cloud Run Job:** `phase3-player-game-summary`
**Purpose:** Consolidate player performance data from multiple sources

| Attribute | Value |
|-----------|-------|
| **Trigger** | Pub/Sub: nba-raw-data-complete (event-driven) OR phase3-start (time-based 2:30 AM ET) |
| **Duration** | 3-5 seconds (typical), 10 seconds (alert threshold) |
| **Volume** | ~450 player-game records per day |
| **Output Table** | nba_analytics.player_game_summary |
| **Strategy** | MERGE_UPDATE (allows multi-pass enrichment) |

**Dependencies:**

**CRITICAL (need at least one):**
- ✅ `nba_raw.nbac_gamebook_player_stats` (PRIMARY - preferred)
- ✅ `nba_raw.bdl_player_boxscores` (FALLBACK - required if gamebook unavailable)

**OPTIONAL:**
- `nba_raw.bigdataball_play_by_play` (shot zones)
- `nba_raw.odds_api_player_points_props` (prop lines)
- `nba_raw.nbac_play_by_play` (backup shot zones)

**Key Features:**
- Multi-source fallback for reliability
- Universal player IDs across all sources
- Prop results tracking (over/under outcomes)
- Data quality tier tracking (high/medium/low)

**Success Criteria:**
```sql
-- Must have at least 200 player records on game day
SELECT COUNT(*) >= 200 as success
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE() - 1;
```

**Graceful Degradation:**
- If gamebook unavailable → Use BDL fallback (data_quality_tier = 'medium')
- If play-by-play unavailable → Continue without shot zones
- If props unavailable → Continue without prop lines (over_under_result = NULL)

---

### 2. Team Offense Game Summary

**Cloud Run Job:** `phase3-team-offense-game-summary`
**Purpose:** Calculate advanced team offensive metrics

| Attribute | Value |
|-----------|-------|
| **Trigger** | Pub/Sub: nba-raw-data-complete (event-driven) OR phase3-start (time-based) |
| **Duration** | 3-5 seconds (typical), 10 seconds (alert threshold) |
| **Volume** | ~20-30 team records per day (2 teams × 10-15 games) |
| **Output Table** | nba_analytics.team_offense_game_summary |
| **Strategy** | MERGE_UPDATE (allows adding shot zones later) |

**Dependencies:**

**CRITICAL:**
- ✅ `nba_raw.nbac_team_boxscore` (team stats, minutes, game info)

**OPTIONAL:**
- `nba_raw.nbac_play_by_play` (shot zones enhancement)

**Key Features:**
- Advanced metrics: ORtg, pace, possessions, TS%
- Overtime handling
- Shot zone analysis (when available)

**Success Criteria:**
```sql
-- Must have at least 20 team records on game day
SELECT COUNT(*) >= 20 as success
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date = CURRENT_DATE() - 1;
```

---

### 3. Team Defense Game Summary

**Cloud Run Job:** `phase3-team-defense-game-summary`
**Purpose:** Calculate defensive metrics using perspective flip logic

| Attribute | Value |
|-----------|-------|
| **Trigger** | Pub/Sub: nba-raw-data-complete (event-driven) OR phase3-start (time-based) |
| **Duration** | 3-5 seconds (typical), 10 seconds (alert threshold) |
| **Volume** | ~20-30 team records per day |
| **Output Table** | nba_analytics.team_defense_game_summary |
| **Strategy** | MERGE_UPDATE |

**Dependencies:**

**CRITICAL:**
- ✅ `nba_raw.nbac_team_boxscore` (opponent offensive stats via perspective flip)

**OPTIONAL:**
- `nba_raw.nbac_gamebook_player_stats` (defensive actions - PRIMARY)
- `nba_raw.bdl_player_boxscores` (defensive actions - FALLBACK)

**Key Features:**
- Perspective flip logic (opponent offense = team defense)
- Multi-source defensive actions (steals, blocks)
- Defensive rating calculations

**Success Criteria:**
```sql
-- Must have at least 20 team records on game day
SELECT COUNT(*) >= 20 as success
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date = CURRENT_DATE() - 1;
```

**Graceful Degradation:**
- If gamebook unavailable → Use BDL fallback (data_quality_tier = 'medium')
- If both unavailable → Use opponent stats only (data_quality_tier = 'low')

---

### 4. Upcoming Team Game Context

**Cloud Run Job:** `phase3-upcoming-team-game-context`
**Purpose:** Generate pre-game team context (fatigue, betting, personnel)

| Attribute | Value |
|-----------|-------|
| **Trigger** | Multiple: props-updated OR schedule-updated OR injuries-updated |
| **Duration** | 5-10 seconds (typical), 20 seconds (alert threshold) |
| **Volume** | ~60 rows per day (30 team-games × 2 perspectives) |
| **Output Table** | nba_analytics.upcoming_team_game_context |
| **Strategy** | DELETE existing date range → INSERT new records |

**Dependencies:**

**CRITICAL:**
- ✅ `nba_raw.nbac_schedule` (game dates, teams, matchups)
- ✅ `nba_static.travel_distances` (arena distances)

**OPTIONAL (AUTO-FALLBACK):**
- `nba_raw.espn_scoreboard` (backup schedule for gaps)

**OPTIONAL:**
- `nba_raw.odds_api_game_lines` (spreads, totals, line movement)
- `nba_raw.nbac_injury_report` (player availability)

**Key Features:**
- Fatigue context (back-to-back, 3-in-4, rest days)
- Betting context (spreads, totals, line movement)
- Personnel context (injuries, player availability)
- Momentum context (recent win/loss streaks)
- Travel context (distance, time zones)

**Multiple Daily Runs:**

| Run Time | Purpose |
|----------|---------|
| 6:00 AM ET | Initial context generation |
| 12:00 PM ET | Updated injury reports |
| 5:00 PM ET | Final betting lines |
| On-Demand | When props/injuries update significantly |

**Success Criteria:**
```sql
-- Must have at least 20 team records on game day
SELECT COUNT(*) >= 20 as success
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
WHERE game_date = CURRENT_DATE();
```

**Graceful Degradation:**
- If nbac_schedule has gaps → Automatically use ESPN fallback
- If odds unavailable → Continue without spreads/totals (fields = NULL)
- If injuries unavailable → Continue with injury counts = 0

---

### 5. Upcoming Player Game Context

**Cloud Run Job:** `phase3-upcoming-player-game-context`
**Purpose:** Generate pre-game player context (fatigue, recent performance, prop context)

| Attribute | Value |
|-----------|-------|
| **Trigger** | Multiple: props-updated OR team-context-updated |
| **Duration** | 5-15 seconds (typical), 30 seconds (alert threshold) |
| **Volume** | 150-250 players with props per day |
| **Output Table** | nba_analytics.upcoming_player_game_context |
| **Strategy** | DELETE existing date → INSERT new records |

**Dependencies:**

**CRITICAL (DRIVER):**
- ✅ `nba_raw.odds_api_player_points_props` (determines which players to process)

**CRITICAL:**
- ✅ `nba_raw.bdl_player_boxscores` (historical performance, last 30 days)
- ✅ `nba_raw.nbac_schedule` (game timing, back-to-back detection)
- ✅ `nba_raw.odds_api_game_lines` (game spreads and totals)

**OPTIONAL (can inherit from team context):**
- `nba_analytics.upcoming_team_game_context` (team-level fatigue/betting)

**Key Features:**
- 14 fatigue metrics (minutes played, rest days, back-to-back)
- Recent performance (last 5/10/30 days)
- Prop context (current lines, historical prop results)
- 84 total fields per player

**Multiple Daily Runs:**

| Run Time | Purpose |
|----------|---------|
| 6:30 AM ET | Initial context after props scraped |
| 12:30 PM ET | Midday update |
| 5:30 PM ET | Pre-game final update |
| On-Demand | When prop lines move significantly |

**Success Criteria:**
```sql
-- Must have at least 100 players on game day
SELECT COUNT(*) >= 100 as success
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE();
```

**Graceful Degradation:**
- If player has <5 games → Process with defaults (data_quality_tier = 'low')
- If game lines missing → Continue without spread/total (fields = NULL)
- If team context unavailable → Skip team-level fields (36 fields = NULL)

---

## Daily Timeline

### Typical Game Day (19 games)

```
2:00 AM ET - Phase 2 Complete
├─ All scrapers finished
├─ Raw data in BigQuery tables
└─ Pub/Sub: phase2-complete published

2:30 AM ET - Parallel Set: Historical Data ⏱️ 3-5 seconds
├─ player_game_summary (3-5s) ──┐
├─ team_offense_game_summary (3-5s) ──┼─ Run in parallel
└─ team_defense_game_summary (3-5s) ──┘

2:35 AM ET - Historical Complete
└─ Pub/Sub: phase3-historical-complete published

6:00 AM ET - Morning Context Update ⏱️ 15 seconds
├─ upcoming_team_game_context (5-10s)
│  └─ Pub/Sub: team-context-updated published
│
└─ upcoming_player_game_context (5-15s) [30 min later]
   └─ Pub/Sub: phase3-complete published

12:00 PM ET - Midday Context Update ⏱️ 15 seconds
├─ upcoming_team_game_context (5-10s)
└─ upcoming_player_game_context (5-15s)

5:00 PM ET - Pre-Game Context Update ⏱️ 15 seconds
├─ upcoming_team_game_context (5-10s)
└─ upcoming_player_game_context (5-15s)

11:00 PM ET - Phase 4 Start
└─ Uses complete Phase 3 analytics data
```

**Total Phase 3 Duration:**
- Historical: ~5 seconds
- Morning context: ~15 seconds
- **Overall:** ~20 seconds (well under 11 PM deadline)

---

## Success Criteria

### Critical Metrics

| Metric | Query | Alert Threshold |
|--------|-------|-----------------|
| **Historical Rows** | `SELECT COUNT(*) FROM player_game_summary WHERE game_date = CURRENT_DATE() - 1` | < 200 player records |
| **Team Offense Rows** | `SELECT COUNT(*) FROM team_offense_game_summary WHERE game_date = CURRENT_DATE() - 1` | < 20 team records |
| **Team Defense Rows** | `SELECT COUNT(*) FROM team_defense_game_summary WHERE game_date = CURRENT_DATE() - 1` | < 20 team records |
| **Upcoming Team** | `SELECT COUNT(*) FROM upcoming_team_game_context WHERE game_date = CURRENT_DATE()` | < 20 team records (game day) |
| **Upcoming Player** | `SELECT COUNT(*) FROM upcoming_player_game_context WHERE game_date = CURRENT_DATE()` | < 100 players (game day) |
| **Data Quality** | `SELECT AVG(source_nbac_completeness_pct) FROM player_game_summary WHERE game_date = CURRENT_DATE() - 1` | < 90% |
| **Processing Time** | Track via logs: completed_at - trigger_time | > 60 seconds for any processor |

### Overall Phase 3 Status Check

```sql
-- Check if all processors completed for yesterday
SELECT
  'player_game_summary' as processor,
  CASE WHEN COUNT(*) >= 200 THEN '✅' ELSE '❌' END as status,
  COUNT(*) as rows,
  MAX(processed_at) as last_run
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT
  'team_offense_game_summary',
  CASE WHEN COUNT(*) >= 20 THEN '✅' ELSE '❌' END,
  COUNT(*),
  MAX(processed_at)
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT
  'team_defense_game_summary',
  CASE WHEN COUNT(*) >= 20 THEN '✅' ELSE '❌' END,
  COUNT(*),
  MAX(processed_at)
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT
  'upcoming_team_game_context',
  CASE WHEN COUNT(*) >= 20 THEN '✅' ELSE '❌' END,
  COUNT(*),
  MAX(processed_at)
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
WHERE game_date = CURRENT_DATE()

UNION ALL

SELECT
  'upcoming_player_game_context',
  CASE WHEN COUNT(*) >= 100 THEN '✅' ELSE '❌' END,
  COUNT(*),
  MAX(processed_at)
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE();
```

**Expected Output (Healthy System):**
```
processor                        | status | rows | last_run
---------------------------------|--------|------|-------------------------
player_game_summary              | ✅     | 452  | 2025-11-15 02:33:15 UTC
team_offense_game_summary        | ✅     | 28   | 2025-11-15 02:33:18 UTC
team_defense_game_summary        | ✅     | 28   | 2025-11-15 02:33:20 UTC
upcoming_team_game_context       | ✅     | 60   | 2025-11-15 17:05:42 UTC
upcoming_player_game_context     | ✅     | 178  | 2025-11-15 17:06:15 UTC
```

---

## Quick Reference

### Cloud Run Jobs

```bash
# List all Phase 3 jobs
gcloud run jobs list --region=us-central1 | grep phase3

# View job details
gcloud run jobs describe phase3-player-game-summary --region=us-central1

# View recent executions
gcloud run jobs executions list --job=phase3-player-game-summary --region=us-central1 --limit=5
```

### Manual Triggers

**Historical processors (for yesterday's games):**
```bash
# Trigger all 3 in parallel
gcloud run jobs execute phase3-player-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=2025-11-14,END_DATE=2025-11-14" &

gcloud run jobs execute phase3-team-offense-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=2025-11-14,END_DATE=2025-11-14" &

gcloud run jobs execute phase3-team-defense-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=2025-11-14,END_DATE=2025-11-14" &

wait  # Wait for all 3 to complete
```

**Upcoming contexts (for today's games):**
```bash
# Team context first
gcloud run jobs execute phase3-upcoming-team-game-context \
  --region us-central1 \
  --set-env-vars "START_DATE=2025-11-15,END_DATE=2025-11-15"

# Player context (can run immediately after team context)
gcloud run jobs execute phase3-upcoming-player-game-context \
  --region us-central1 \
  --set-env-vars "GAME_DATE=2025-11-15"
```

### Key BigQuery Tables

| Table | Purpose | Partition | Update Frequency |
|-------|---------|-----------|------------------|
| `nba_analytics.player_game_summary` | Historical player performance | game_date | Once daily (2:30 AM) |
| `nba_analytics.team_offense_game_summary` | Team offensive stats | game_date | Once daily (2:30 AM) |
| `nba_analytics.team_defense_game_summary` | Team defensive stats | game_date | Once daily (2:30 AM) |
| `nba_analytics.upcoming_team_game_context` | Pre-game team context | game_date | 3x daily (6 AM, 12 PM, 5 PM) |
| `nba_analytics.upcoming_player_game_context` | Pre-game player context | game_date | 3x daily (6:30 AM, 12:30 PM, 5:30 PM) |

### Common Queries

**Check yesterday's processing:**
```sql
-- Simple row count check
SELECT
  COUNT(*) as player_records
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE() - 1;
-- Expected: 400-500 records
```

**Check today's upcoming context:**
```sql
-- Verify upcoming context for today's games
SELECT
  COUNT(DISTINCT player_id) as players_with_context,
  COUNT(DISTINCT game_id) as games_covered
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE();
-- Expected: 150-250 players, 10-15 games
```

**Data quality check:**
```sql
-- Check data quality tiers
SELECT
  data_quality_tier,
  COUNT(*) as records,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE() - 1
GROUP BY data_quality_tier
ORDER BY records DESC;
-- Expected: >90% 'high' tier
```

### Troubleshooting Quick Links

| Issue | See |
|-------|-----|
| **Processor fails all retries** | `04-phase3-troubleshooting.md` → Failure Scenario 1-4 |
| **Missing dependencies** | `04-phase3-troubleshooting.md` → Scenario 2 |
| **Low data quality** | `04-phase3-troubleshooting.md` → Data Quality Issues |
| **Manual trigger needed** | `04-phase3-troubleshooting.md` → Runbook: Manual Phase 3 Trigger |
| **Scheduling questions** | `03-phase3-scheduling-strategy.md` → Cloud Scheduler Configuration |
| **Pub/Sub issues** | `docs/infrastructure/01-pubsub-integration-verification.md` |

---

## Related Documentation

**Scheduling & Orchestration:**
- `03-phase3-scheduling-strategy.md` - Cloud Scheduler jobs, Pub/Sub topics, event payloads

**Troubleshooting:**
- `04-phase3-troubleshooting.md` - Failure scenarios, recovery procedures, runbooks

**Infrastructure:**
- `docs/infrastructure/01-pubsub-integration-verification.md` - Pub/Sub setup and testing

**Monitoring:**
- `docs/monitoring/01-grafana-monitoring-guide.md` - Grafana dashboards for Phase 3

**Architecture:**
- `docs/architecture/04-event-driven-pipeline-architecture.md` - Overall pipeline design

---

**Last Updated:** 2025-11-15 14:30 PST
**Status:** 🚧 Draft (awaiting deployment)
**Next Review:** After Phase 3 deployment
