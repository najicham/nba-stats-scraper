# Architecture Improvements Design Document

**Date**: 2026-01-27
**Author**: Claude Opus 4.5
**Status**: Proposed
**Context**: Root cause analysis revealed systemic issues requiring architectural changes

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current State Analysis](#current-state-analysis)
3. [Design 1: Phase 3 Sub-Phases](#design-1-phase-3-sub-phases)
4. [Design 2: Betting Lines Coordination](#design-2-betting-lines-coordination)
5. [Design 3: Distributed Lock System](#design-3-distributed-lock-system)
6. [Design 4: Circuit Breakers](#design-4-circuit-breakers)
7. [Migration Plan](#migration-plan)
8. [Risk Assessment](#risk-assessment)
9. [Implementation Priority](#implementation-priority)

---

## Executive Summary

Four systemic architectural improvements are proposed to prevent the data quality issues discovered during the 2026-01-27 investigation:

| Issue | Root Cause | Proposed Solution |
|-------|-----------|-------------------|
| 71% NULL usage_rate | No processing order in Phase 3 | Phase 3 Sub-Phases (3a, 3b, 3c) |
| 0 predictions generated | Betting lines scraped AFTER Phase 3 | Event-driven betting lines coordination |
| 93 duplicate records | Non-atomic MERGE fallback, no distributed locks | Firestore-based distributed locking |
| Silent failures | Quality gates don't catch edge cases | Enhanced circuit breakers with data quality checks |

---

## Current State Analysis

### Current Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           CURRENT PIPELINE ARCHITECTURE                          │
└─────────────────────────────────────────────────────────────────────────────────┘

PHASE 1: Raw Data Collection (Cloud Scheduler → HTTP → Scrapers)
┌────────────────────────────────────────────────────────────────────────────────┐
│  morning_operations: 7 AM ET                                                    │
│  ├── nbac_schedule_api                                                         │
│  ├── bdl_active_players                                                        │
│  └── br_roster_scraper                                                         │
│                                                                                 │
│  betting_lines: 8 AM-5 PM ET (every 2 hours)                                   │
│  ├── odds_api_events        ─────┐                                             │
│  └── bettingpros_props      ─────┴── NO COORDINATION WITH PHASE 3              │
│                                                                                 │
│  post_game_*: 10 PM, 2 AM, 6 AM ET                                             │
│  ├── bdl_boxscores                                                             │
│  └── nbac_gamebook                                                             │
└────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
PHASE 2: Raw Processing (Pub/Sub → Cloud Run)
┌────────────────────────────────────────────────────────────────────────────────┐
│  nba-raw-complete topic                                                         │
│  ├── nbac_player_boxscore_processor                                            │
│  ├── nbac_gamebook_processor                                                   │
│  ├── bdl_boxscores_processor                                                   │
│  └── bettingpros_player_props_processor                                        │
│                                       │                                         │
│                                       ▼                                         │
│                        phase2_to_phase3 orchestrator                           │
│                        (Firestore state tracking)                              │
└────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
PHASE 3: Analytics (Pub/Sub → Cloud Run) ⚠️ ALL RUN IN PARALLEL - NO ORDER
┌────────────────────────────────────────────────────────────────────────────────┐
│  nba-phase3-analytics-trigger topic                                             │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ ALL 5 PROCESSORS RUN SIMULTANEOUSLY (current design)                    │   │
│  │                                                                          │   │
│  │  ┌──────────────────────┐  ┌──────────────────────┐                     │   │
│  │  │ team_offense_game    │  │ team_defense_game    │                     │   │
│  │  │ _summary             │  │ _summary             │                     │   │
│  │  └──────────────────────┘  └──────────────────────┘                     │   │
│  │           ▲                                                              │   │
│  │           │ HIDDEN DEPENDENCY (not enforced)                            │   │
│  │           │                                                              │   │
│  │  ┌──────────────────────┐  ┌──────────────────────┐                     │   │
│  │  │ player_game_summary  │  │ upcoming_player_     │                     │   │
│  │  │ (needs team stats    │  │ game_context         │                     │   │
│  │  │  for usage_rate!)    │  │                      │                     │   │
│  │  └──────────────────────┘  └──────────────────────┘                     │   │
│  │                                                                          │   │
│  │  ┌──────────────────────┐                                               │   │
│  │  │ upcoming_team_game   │                                               │   │
│  │  │ _context             │                                               │   │
│  │  └──────────────────────┘                                               │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                       │                                         │
│                                       ▼                                         │
│                        phase3_to_phase4 orchestrator                           │
│                        (waits for all 5, no ordering)                          │
└────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
PHASE 4: Precompute (Pub/Sub → Cloud Run)
┌────────────────────────────────────────────────────────────────────────────────┐
│  nba-phase4-trigger topic                                                       │
│  ├── player_daily_cache_processor                                              │
│  ├── player_composite_factors_processor                                        │
│  ├── ml_feature_store_processor                                                │
│  └── player_shot_zone_analysis_processor                                       │
└────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
PHASE 5: Predictions (HTTP Trigger → Cloud Run)
┌────────────────────────────────────────────────────────────────────────────────┐
│  prediction-coordinator service                                                 │
│  ├── Loads players from upcoming_player_game_context                           │
│  ├── Filters by has_prop_line = TRUE  ⚠️ REQUIRES BETTING LINES               │
│  ├── Generates predictions                                                     │
│  └── Writes to nba_predictions.player_prop_predictions                         │
└────────────────────────────────────────────────────────────────────────────────┘
```

### Current Processor Dependencies (Mapped)

```
Phase 3 Processor Dependency Graph
==================================

team_offense_game_summary
├── Sources: nbac_gamebook, bdl_player_boxscores
├── Depends on: Phase 2 raw data (via JOIN)
└── Outputs: team-level offensive stats per game

team_defense_game_summary
├── Sources: nbac_gamebook, bdl_player_boxscores
├── Depends on: Phase 2 raw data (via JOIN)
└── Outputs: team-level defensive stats per game

player_game_summary ⚠️ HIDDEN DEPENDENCY
├── Sources: nbac_gamebook, bdl_player_boxscores, odds_api_props
├── Depends on: Phase 2 raw data (via JOIN)
├── Depends on: team_offense_game_summary (for usage_rate calculation!)  ← NOT ENFORCED
└── Outputs: player-level stats with prop results

upcoming_player_game_context ⚠️ TIMING DEPENDENCY
├── Sources: player_game_summary, betting_lines_raw
├── Depends on: player_game_summary for historical stats
├── Depends on: bettingpros_player_props for has_prop_line  ← SCRAPED AFTER PROCESSING
└── Outputs: forward-looking context for predictions

upcoming_team_game_context
├── Sources: team_offense/defense_game_summary, schedule
├── Depends on: team summaries
└── Outputs: team-level forward-looking context
```

### Current Timing Issues

```
CURRENT TIMING DIAGRAM (Problem Case)
=====================================

Time (ET)    Event                                  Result
---------    -----                                  ------
6:00 AM      Phase 2 completes (yesterday's data)
6:10 AM      Phase 3 triggered
6:15 AM      ├── player_game_summary STARTS
6:17 AM      │   └── JOINs to team_offense...      team stats don't exist yet!
6:18 AM      │       └── usage_rate = NULL         ⚠️ 71% NULL values
6:20 AM      ├── team_offense_game_summary STARTS
6:25 AM      │   └── team stats computed           Too late for player_game_summary
6:30 AM      Phase 3 "complete" (all 5 done)       usage_rate NOT corrected

3:30 PM      Phase 3 REFRESH (same-day mode)
3:35 PM      upcoming_player_game_context runs
3:40 PM      ├── Checks for betting lines          Lines not scraped yet!
3:45 PM      └── has_prop_line = FALSE for all     ⚠️ 0 eligible players

4:46 PM      betting_lines workflow runs
4:50 PM      bettingpros_props scraped             Too late - Phase 3 already done

5:00 PM      Phase 5 triggered
5:01 PM      prediction_coordinator runs
5:02 PM      └── 0 eligible players (no lines)    ⚠️ 0 PREDICTIONS GENERATED
```

### Current Race Condition (Backfill Duplicates)

```
CURRENT BACKFILL RACE CONDITION
===============================

Time         Process A (Backfill Job 1)    Process B (Backfill Job 2)    BigQuery State
----         -------------------------     -------------------------     --------------
T+0          Starts backfill Jan 8                                        100 records
T+1          MERGE fails (syntax)                                         100 records
T+2          Fallback to DELETE+INSERT                                    100 records
T+3          DELETE query executes                                        0 records
T+4                                        Starts backfill Jan 8          0 records
T+5          INSERT query starts                                          0 records
T+6                                        MERGE succeeds                 100 records (new)
T+7          INSERT completes                                             193 records ⚠️ DUPLICATES!
```

---

## Design 1: Phase 3 Sub-Phases

### Problem Statement

All 5 Phase 3 processors run in parallel with no mechanism to enforce the dependency that `player_game_summary` requires `team_offense_game_summary` to exist first for `usage_rate` calculation.

### Proposed Solution

Split Phase 3 into three ordered sub-phases using the existing Pub/Sub architecture:

```
PROPOSED PHASE 3 SUB-PHASES
===========================

┌─────────────────────────────────────────────────────────────────────────────┐
│                        PHASE 3a: TEAM FOUNDATIONS                            │
│                                                                              │
│  Trigger: nba-phase3a-trigger                                               │
│                                                                              │
│  ┌────────────────────────┐    ┌────────────────────────┐                   │
│  │ team_offense_game      │    │ team_defense_game      │                   │
│  │ _summary               │    │ _summary               │                   │
│  │ (parallel)             │    │ (parallel)             │                   │
│  └────────────────────────┘    └────────────────────────┘                   │
│                                                                              │
│  Orchestrator: phase3a_to_phase3b                                           │
│  Completion: Wait for BOTH team processors                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PHASE 3b: PLAYER SUMMARIES                            │
│                                                                              │
│  Trigger: nba-phase3b-trigger                                               │
│                                                                              │
│  ┌────────────────────────┐                                                 │
│  │ player_game_summary    │                                                 │
│  │ (has team stats!)      │                                                 │
│  └────────────────────────┘                                                 │
│                                                                              │
│  Orchestrator: phase3b_to_phase3c                                           │
│  Completion: Wait for player_game_summary                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PHASE 3c: FORWARD-LOOKING CONTEXT                     │
│                                                                              │
│  Trigger: nba-phase3c-trigger                                               │
│                                                                              │
│  ┌────────────────────────┐    ┌────────────────────────┐                   │
│  │ upcoming_player_game   │    │ upcoming_team_game     │                   │
│  │ _context (parallel)    │    │ _context (parallel)    │                   │
│  └────────────────────────┘    └────────────────────────┘                   │
│                                                                              │
│  Orchestrator: phase3_to_phase4 (existing, no changes needed)               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation Details

#### New Pub/Sub Topics

```python
# shared/config/pubsub_topics.py (additions)

PHASE3A_TRIGGER = "nba-phase3a-trigger"
PHASE3A_COMPLETE = "nba-phase3a-analytics-complete"
PHASE3B_TRIGGER = "nba-phase3b-trigger"
PHASE3B_COMPLETE = "nba-phase3b-analytics-complete"
PHASE3C_TRIGGER = "nba-phase3c-trigger"
# Phase 3c uses existing nba-phase3-analytics-complete
```

#### New Orchestrator: phase3a_to_phase3b

```python
# orchestration/cloud_functions/phase3a_to_phase3b/main.py

"""
Phase 3a → Phase 3b Orchestrator

Tracks team processor completion and triggers player processor when ready.

Architecture:
- Listens to: nba-phase3a-analytics-complete
- Tracks state in: Firestore collection 'phase3a_completion/{game_date}'
- Publishes to: nba-phase3b-trigger

Expected Processors:
- team_offense_game_summary
- team_defense_game_summary
"""

EXPECTED_PROCESSORS = [
    'team_offense_game_summary',
    'team_defense_game_summary',
]

@functions_framework.cloud_event
def orchestrate_phase3a_to_phase3b(cloud_event):
    """
    Handle Phase 3a completion events and trigger Phase 3b when team stats complete.
    """
    message_data = parse_pubsub_message(cloud_event)
    game_date = message_data.get('game_date')
    processor_name = normalize_processor_name(message_data.get('processor_name'))

    # Update Firestore state atomically
    doc_ref = db.collection('phase3a_completion').document(game_date)
    transaction = db.transaction()
    should_trigger = update_completion_atomic(
        transaction, doc_ref, processor_name, EXPECTED_PROCESSORS
    )

    if should_trigger:
        # Validate team data exists in BigQuery before triggering
        team_games = verify_team_data_exists(game_date)
        if team_games == 0:
            raise ValueError(f"No team stats found for {game_date} - blocking Phase 3b")

        # Trigger Phase 3b (player_game_summary)
        publish_to_topic(PHASE3B_TRIGGER, {
            'game_date': game_date,
            'correlation_id': message_data.get('correlation_id'),
            'trigger_source': 'phase3a_to_phase3b',
            'team_games_verified': team_games
        })
```

#### Updated phase2_to_phase3 Orchestrator

```python
# orchestration/cloud_functions/phase2_to_phase3/main.py (modification)

# CHANGE: Trigger Phase 3a (team processors) instead of all Phase 3 processors

PHASE3A_TRIGGER_TOPIC = 'nba-phase3a-trigger'  # Changed from 'nba-phase3-trigger'

def trigger_phase3(game_date: str, correlation_id: str, ...):
    """
    Publish message to trigger Phase 3a (team processors first).
    """
    message = {
        'game_date': game_date,
        'correlation_id': correlation_id,
        'trigger_source': 'phase2_to_phase3',
        # Only trigger team processors initially
        'target_processors': [
            'team_offense_game_summary',
            'team_defense_game_summary',
        ]
    }
    publisher.publish(PHASE3A_TRIGGER_TOPIC, json.dumps(message).encode())
```

### Configuration Changes

```yaml
# shared/config/orchestration_config.py (additions)

phase_transitions:
  # Phase 3 sub-phase configuration
  phase3_sub_phases:
    enabled: true  # Feature flag for gradual rollout

    phase3a:
      name: "Team Foundations"
      expected_processors:
        - team_offense_game_summary
        - team_defense_game_summary
      trigger_topic: "nba-phase3a-trigger"
      complete_topic: "nba-phase3a-analytics-complete"
      timeout_minutes: 15

    phase3b:
      name: "Player Summaries"
      expected_processors:
        - player_game_summary
      trigger_topic: "nba-phase3b-trigger"
      complete_topic: "nba-phase3b-analytics-complete"
      timeout_minutes: 20
      depends_on: ["phase3a"]  # Explicit dependency

    phase3c:
      name: "Forward-Looking Context"
      expected_processors:
        - upcoming_player_game_context
        - upcoming_team_game_context
      trigger_topic: "nba-phase3c-trigger"
      complete_topic: "nba-phase3-analytics-complete"  # Existing topic
      timeout_minutes: 15
      depends_on: ["phase3b"]
```

### Backward Compatibility

1. **Feature flag**: `phase3_sub_phases.enabled` allows gradual rollout
2. **Existing topic preserved**: Phase 3c completion still publishes to `nba-phase3-analytics-complete`
3. **phase3_to_phase4 unchanged**: Existing orchestrator works as-is
4. **Processor code unchanged**: Processors don't need modifications

### Performance Impact

| Metric | Current | Proposed | Impact |
|--------|---------|----------|--------|
| Total Phase 3 time | ~15 min (parallel) | ~25 min (sequential) | +10 min |
| Error recovery | Rerun all 5 | Rerun only failed sub-phase | -50% wasted work |
| Data quality | 71% NULL usage_rate | 0% NULL | +71% coverage |

---

## Design 2: Betting Lines Coordination

### Problem Statement

Betting lines are scraped at 4:46 PM but Phase 3 (upcoming_player_game_context) runs at 3:30 PM, causing `has_prop_line = FALSE` for all players, resulting in 0 predictions.

### Option Analysis

| Option | Description | Pros | Cons | Recommendation |
|--------|-------------|------|------|----------------|
| **A** | Betting lines trigger Phase 3c refresh | Lines drive timing | Couples scraper to processor | **Recommended** |
| **B** | Phase 3c waits for betting lines | Guaranteed data | Complex coordination | Too complex |
| **C** | Prediction coordinator queries raw lines | No Phase 3 change | Duplicates logic | Violates separation |

### Proposed Solution: Option A - Event-Driven Refresh

```
PROPOSED BETTING LINES COORDINATION
===================================

┌───────────────────────────────────────────────────────────────────────────────┐
│                              TIMING FLOW                                       │
└───────────────────────────────────────────────────────────────────────────────┘

Time (ET)    Event
---------    -----
6:00 AM      Phase 2 completes (overnight data)
6:30 AM      Phase 3 completes (team + player stats)
             └── has_prop_line = FALSE (no lines yet) ← OK, expected

...          (no predictions needed yet - games not until 7 PM)

3:00 PM      betting_lines workflow triggered
3:05 PM      ├── odds_api_events runs
3:15 PM      ├── bettingpros_props runs
3:20 PM      └── Publishes to: nba-betting-lines-complete  ← NEW TOPIC

3:21 PM      betting_lines_to_phase3c orchestrator receives event
3:22 PM      └── Triggers Phase 3c refresh (only upcoming_* processors)

3:25 PM      Phase 3c refresh starts
3:35 PM      ├── upcoming_player_game_context
             │   └── NOW has betting lines → has_prop_line = TRUE
3:40 PM      └── upcoming_team_game_context

3:45 PM      Phase 3c complete
4:00 PM      Phase 5 triggered
4:05 PM      └── prediction_coordinator finds eligible players → PREDICTIONS!
```

### Implementation Details

#### New Pub/Sub Topic and Orchestrator

```python
# orchestration/cloud_functions/betting_lines_to_phase3c/main.py

"""
Betting Lines → Phase 3c Refresh Orchestrator

When betting lines are scraped, triggers a refresh of the upcoming_* processors
to populate has_prop_line correctly.

Architecture:
- Listens to: nba-betting-lines-complete (NEW)
- Validates: betting lines exist in BigQuery
- Publishes to: nba-phase3c-trigger

Timing:
- Runs whenever betting lines scraper completes
- Only refreshes Phase 3c (upcoming_* processors)
- Does NOT re-run Phase 3a/3b (team/player stats)
"""

import functions_framework
from google.cloud import pubsub_v1, firestore, bigquery
import json
import logging

logger = logging.getLogger(__name__)

PHASE3C_TRIGGER_TOPIC = 'nba-phase3c-trigger'

@functions_framework.cloud_event
def on_betting_lines_complete(cloud_event):
    """
    Handle betting lines completion and trigger Phase 3c refresh.
    """
    message_data = parse_pubsub_message(cloud_event)
    game_date = message_data.get('game_date')

    logger.info(f"Betting lines complete for {game_date}, triggering Phase 3c refresh")

    # Validate betting lines actually exist
    lines_count = verify_betting_lines_exist(game_date)
    if lines_count < 50:  # Sanity check - should have lines for ~150+ players
        logger.warning(f"Only {lines_count} betting lines found for {game_date}")
        # Don't block - might be early games with fewer lines

    # Check if Phase 3a/3b already ran today (don't trigger if not)
    if not verify_phase3b_complete(game_date):
        logger.warning(f"Phase 3b not complete for {game_date}, skipping Phase 3c refresh")
        return

    # Trigger Phase 3c refresh
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, PHASE3C_TRIGGER_TOPIC)

    message = {
        'game_date': game_date,
        'correlation_id': message_data.get('correlation_id'),
        'trigger_source': 'betting_lines_to_phase3c',
        'is_refresh': True,  # Flag to indicate this is a betting lines refresh
        'betting_lines_count': lines_count,
        'target_processors': [
            'upcoming_player_game_context',
            'upcoming_team_game_context',
        ]
    }

    publisher.publish(topic_path, json.dumps(message).encode())
    logger.info(f"Published Phase 3c refresh trigger for {game_date}")


def verify_betting_lines_exist(game_date: str) -> int:
    """
    Check if betting lines exist in raw table for game_date.
    """
    bq_client = bigquery.Client()
    query = f"""
    SELECT COUNT(DISTINCT player_name) as player_count
    FROM `nba-props-platform.nba_raw.bettingpros_player_props`
    WHERE DATE(scraped_at) = '{game_date}'
    """
    result = list(bq_client.query(query).result())
    return result[0].player_count if result else 0


def verify_phase3b_complete(game_date: str) -> bool:
    """
    Check if Phase 3b has completed for this game_date.
    """
    db = firestore.Client()
    doc = db.collection('phase3b_completion').document(game_date).get()
    return doc.exists and doc.to_dict().get('_triggered', False)
```

#### Scraper Modification to Publish Completion

```python
# scrapers/bettingpros/bp_player_props.py (modification)

def scrape_and_save(self, game_date: str):
    """
    Scrape player props and save to BigQuery.

    After successful save, publishes to nba-betting-lines-complete topic
    to trigger Phase 3c refresh.
    """
    # ... existing scraping logic ...

    rows_saved = self.save_to_bigquery(props_data)

    if rows_saved > 0:
        # Publish completion event for downstream orchestration
        self.publish_completion_event(game_date, rows_saved)

    return rows_saved


def publish_completion_event(self, game_date: str, rows_saved: int):
    """
    Publish betting lines completion to trigger Phase 3c refresh.
    """
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(
        self.project_id,
        'nba-betting-lines-complete'
    )

    message = {
        'game_date': game_date,
        'scraper': 'bettingpros_player_props',
        'rows_saved': rows_saved,
        'timestamp': datetime.utcnow().isoformat(),
        'correlation_id': self.correlation_id
    }

    publisher.publish(topic_path, json.dumps(message).encode())
    logger.info(f"Published betting lines completion for {game_date}")
```

### Fallback: Prediction Coordinator Direct Query

If betting lines coordination fails, add fallback in prediction coordinator:

```python
# predictions/coordinator/player_loader.py (enhancement)

def load_eligible_players(self, game_date: date) -> List[PlayerContext]:
    """
    Load eligible players for prediction.

    ENHANCED: If has_prop_line = FALSE for all, fall back to direct query.
    """
    # Try primary path: upcoming_player_game_context
    players = self._load_from_context_table(game_date)

    # Check if betting lines issue
    with_lines = [p for p in players if p.has_prop_line]
    if len(players) > 0 and len(with_lines) == 0:
        logger.warning(
            f"0 players have has_prop_line=TRUE for {game_date}. "
            f"Checking raw betting lines directly..."
        )

        # Fallback: Query raw betting lines
        raw_lines = self._get_raw_betting_lines(game_date)

        if len(raw_lines) > 0:
            # We have betting lines but Phase 3c didn't process them
            logger.error(
                f"Found {len(raw_lines)} betting lines in raw table but "
                f"upcoming_player_game_context has no lines. "
                f"Phase 3c may not have run after betting lines scraped."
            )

            # Alert operators
            notify_error(
                title="Betting Lines Timing Issue",
                message=f"Found {len(raw_lines)} raw betting lines but Phase 3c didn't process them",
                details={
                    'game_date': game_date.isoformat(),
                    'raw_lines_count': len(raw_lines),
                    'context_players_count': len(players),
                    'action': 'Manual Phase 3c refresh may be needed'
                }
            )

            # OPTION: Enrich players with raw lines here
            players = self._enrich_with_raw_lines(players, raw_lines)

    return players
```

---

## Design 3: Distributed Lock System

### Problem Statement

Concurrent backfill operations create duplicate records because:
1. MERGE fallback to DELETE+INSERT is not atomic
2. No distributed lock prevents concurrent processing of the same game_date
3. Streaming buffer can block DELETE but allow INSERT

### Proposed Solution: Enhanced Firestore-Based Locking

The codebase already has a distributed lock implementation in `orchestration/shared/utils/distributed_lock.py`. Extend this for backfill operations.

```
PROPOSED DISTRIBUTED LOCK ARCHITECTURE
======================================

┌─────────────────────────────────────────────────────────────────────────────┐
│                           FIRESTORE LOCK DESIGN                              │
└─────────────────────────────────────────────────────────────────────────────┘

Collection: backfill_locks
Document ID: {processor_name}_{game_date}  (e.g., "player_game_summary_2026-01-08")

Document Schema:
{
    "lock_type": "backfill",
    "processor_name": "player_game_summary",
    "game_date": "2026-01-08",
    "operation_id": "backfill_job_abc123",
    "holder_id": "worker_1",
    "acquired_at": <timestamp>,
    "expires_at": <timestamp + 10 minutes>,
    "lock_key": "backfill_player_game_summary_2026-01-08"
}

Lock Lifecycle:
1. ACQUIRE: Transaction checks expires_at, sets if available
2. HOLD: Process executes backfill
3. RELEASE: Delete document on success
4. EXPIRE: Stale locks automatically invalid after expires_at
```

### Implementation Details

#### Enhanced DistributedLock Class

```python
# orchestration/shared/utils/distributed_lock.py (enhancement)

class BackfillLock(DistributedLock):
    """
    Specialized distributed lock for backfill operations.

    Features:
    - Longer timeout (10 minutes) for large date ranges
    - Per-processor + per-date granularity
    - Automatic cleanup of stale locks
    - Metrics logging for lock contention
    """

    # Backfill operations may take longer than regular operations
    LOCK_TIMEOUT_SECONDS = 600  # 10 minutes
    MAX_ACQUIRE_ATTEMPTS = 30   # 30 * 10s = 5 minutes max wait
    RETRY_DELAY_SECONDS = 10

    def __init__(self, project_id: str, processor_name: str):
        """
        Initialize backfill lock for a specific processor.

        Args:
            project_id: GCP project ID
            processor_name: Name of processor (e.g., "player_game_summary")
        """
        super().__init__(project_id, lock_type="backfill")
        self.processor_name = processor_name
        self.collection_name = "backfill_locks"

    def _generate_lock_key(self, game_date: str) -> str:
        """
        Generate lock key scoped to processor + game_date.

        This allows different processors to backfill the same date concurrently,
        but prevents the SAME processor from running twice on the same date.
        """
        return f"backfill_{self.processor_name}_{game_date}"

    @contextmanager
    def acquire_for_date_range(
        self,
        start_date: date,
        end_date: date,
        operation_id: str
    ):
        """
        Acquire locks for a range of dates.

        IMPORTANT: Acquires ALL locks upfront to prevent deadlock.
        If any lock fails, releases all acquired locks.

        Args:
            start_date: Start of date range
            end_date: End of date range
            operation_id: Unique identifier for this operation

        Yields:
            List of locked dates
        """
        dates = self._generate_date_range(start_date, end_date)
        acquired_locks = []

        try:
            # Acquire locks in order (prevents deadlock)
            for game_date in sorted(dates):
                date_str = game_date.strftime('%Y-%m-%d')
                lock_acquired = self._try_acquire(
                    lock_key=self._generate_lock_key(date_str),
                    operation_id=operation_id,
                    holder_id=f"{operation_id}_{date_str}"
                )

                if not lock_acquired:
                    # Another operation has this date - skip it
                    logger.warning(
                        f"Could not acquire lock for {date_str}, skipping. "
                        f"Another backfill may be running."
                    )
                    continue

                acquired_locks.append(date_str)

            if not acquired_locks:
                raise LockAcquisitionError(
                    f"Could not acquire any locks for range {start_date} to {end_date}"
                )

            logger.info(
                f"Acquired {len(acquired_locks)}/{len(dates)} locks for backfill: "
                f"{acquired_locks[0]} to {acquired_locks[-1]}"
            )

            yield acquired_locks

        finally:
            # Release all acquired locks
            for date_str in acquired_locks:
                try:
                    self._release(
                        self._generate_lock_key(date_str),
                        operation_id
                    )
                except Exception as e:
                    logger.error(f"Failed to release lock for {date_str}: {e}")

    def _generate_date_range(self, start_date: date, end_date: date) -> List[date]:
        """Generate list of dates in range."""
        dates = []
        current = start_date
        while current <= end_date:
            dates.append(current)
            current += timedelta(days=1)
        return dates
```

#### Backfill Job Integration

```python
# backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py (modification)

from orchestration.shared.utils.distributed_lock import BackfillLock, LockAcquisitionError

class PlayerGameSummaryBackfill:
    """
    Backfill processor with distributed locking.
    """

    def __init__(self):
        self.processor = PlayerGameSummaryProcessor()
        self.processor_name = "player_game_summary"

        # Initialize distributed lock
        self.lock = BackfillLock(
            project_id=os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
            processor_name=self.processor_name
        )

    def run_backfill(
        self,
        start_date: date,
        end_date: date,
        dry_run: bool = False
    ) -> Dict:
        """
        Run backfill with distributed locking.
        """
        operation_id = f"backfill_{self.processor_name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        logger.info(
            f"Starting backfill for {self.processor_name}: "
            f"{start_date} to {end_date} (operation_id={operation_id})"
        )

        try:
            # Acquire locks for the entire date range
            with self.lock.acquire_for_date_range(start_date, end_date, operation_id) as locked_dates:
                logger.info(f"Processing {len(locked_dates)} dates with exclusive locks")

                results = {
                    'operation_id': operation_id,
                    'dates_locked': len(locked_dates),
                    'dates_processed': 0,
                    'dates_failed': 0,
                    'dates_skipped': 0
                }

                for date_str in locked_dates:
                    game_date = datetime.strptime(date_str, '%Y-%m-%d').date()

                    try:
                        if dry_run:
                            logger.info(f"[DRY RUN] Would process {date_str}")
                            results['dates_skipped'] += 1
                        else:
                            self.processor.process_date(game_date, is_backfill=True)
                            results['dates_processed'] += 1

                    except Exception as e:
                        logger.error(f"Failed to process {date_str}: {e}")
                        results['dates_failed'] += 1

                return results

        except LockAcquisitionError as e:
            logger.error(f"Could not acquire locks: {e}")
            return {
                'operation_id': operation_id,
                'error': str(e),
                'dates_locked': 0
            }
```

### BigQuery Save Enhancement

```python
# data_processors/analytics/operations/bigquery_save_ops.py (enhancement)

def _save_with_delete_insert(
    self,
    rows: List[Dict],
    table_id: str,
    table_schema: List,
    game_date: str
) -> int:
    """
    Save with DELETE+INSERT pattern (used as MERGE fallback).

    ENHANCED: Atomic delete-insert within same job using scripting.
    """
    # Build atomic DELETE+INSERT script
    delete_query = f"""
    DELETE FROM `{table_id}`
    WHERE game_date = '{game_date}'
    """

    # Build INSERT from temp table
    insert_query = f"""
    INSERT INTO `{table_id}`
    SELECT * FROM UNNEST(@rows)
    """

    # Execute as atomic script
    script = f"""
    BEGIN TRANSACTION;

    -- Delete existing records
    {delete_query};

    -- Insert new records
    {insert_query};

    COMMIT TRANSACTION;
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("rows", "STRUCT", rows)
        ]
    )

    try:
        job = self.bq_client.query(script, job_config=job_config)
        job.result()  # Wait for completion

        logger.info(f"Atomic DELETE+INSERT completed for {game_date}")
        return len(rows)

    except Exception as e:
        logger.error(f"Atomic DELETE+INSERT failed: {e}")
        # Transaction rolled back automatically
        raise
```

---

## Design 4: Circuit Breakers

### Problem Statement

Silent failures occur because:
1. Quality gates exist but don't catch edge cases (0 players, 100% NULL)
2. Phases proceed even with incomplete/corrupt data
3. No automatic rollback when quality thresholds aren't met

### Proposed Solution: Enhanced Circuit Breakers with Data Quality Checks

```
PROPOSED CIRCUIT BREAKER ARCHITECTURE
=====================================

┌─────────────────────────────────────────────────────────────────────────────┐
│                         CIRCUIT BREAKER LOCATIONS                            │
└─────────────────────────────────────────────────────────────────────────────┘

Phase Boundary Circuit Breakers:
┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   Phase 2   │ ──CB──   Phase 3a  │ ──CB──   Phase 3b  │ ──CB──   Phase 3c  │
│             │      │             │      │             │      │             │
│  Raw Data   │      │ Team Stats  │      │Player Stats │      │  Upcoming   │
└─────────────┘      └─────────────┘      └─────────────┘      └─────────────┘
                                                                      │
                                                                     CB
                                                                      │
┌─────────────┐      ┌─────────────┐                            ┌─────────────┐
│   Phase 6   │ ──CB──   Phase 5   │ ──────────CB──────────────   Phase 4   │
│  Grading    │      │ Predictions │                            │ Precompute  │
└─────────────┘      └─────────────┘                            └─────────────┘

CB = Circuit Breaker with Data Quality Check
```

### Implementation Details

#### Phase Boundary Circuit Breaker

```python
# shared/validation/phase_circuit_breaker.py (NEW FILE)

"""
Phase Boundary Circuit Breaker

Validates data quality before allowing phase transitions.
Blocks progression if data quality thresholds aren't met.

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Tuple, Optional
from datetime import date

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation, phase can proceed
    OPEN = "open"          # Quality check failed, block phase
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class QualityThreshold:
    """Data quality threshold configuration."""
    metric_name: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_count: Optional[int] = None
    max_null_pct: Optional[float] = None
    severity: str = "critical"  # critical = blocks, warning = alerts only


class PhaseCircuitBreaker:
    """
    Circuit breaker that validates data quality at phase boundaries.

    Prevents phase progression if data quality thresholds aren't met,
    stopping cascade contamination early.
    """

    # Quality thresholds per phase transition
    THRESHOLDS = {
        'phase3a_to_phase3b': [
            QualityThreshold(
                metric_name='team_offense_game_count',
                min_count=1,  # At least 1 team game record
                severity='critical'
            ),
            QualityThreshold(
                metric_name='team_offense_fg_attempts',
                min_value=50,  # Sanity check for complete games
                severity='critical'
            ),
        ],
        'phase3b_to_phase3c': [
            QualityThreshold(
                metric_name='player_game_count',
                min_count=20,  # At least 20 player records
                severity='critical'
            ),
            QualityThreshold(
                metric_name='usage_rate_null_pct',
                max_null_pct=30.0,  # Max 30% NULL usage_rate
                severity='critical'
            ),
        ],
        'phase3_to_phase4': [
            QualityThreshold(
                metric_name='upcoming_player_count',
                min_count=50,  # At least 50 players
                severity='critical'
            ),
            QualityThreshold(
                metric_name='has_prop_line_pct',
                min_value=10.0,  # At least 10% have betting lines
                severity='warning'  # Alert but don't block (timing may vary)
            ),
        ],
        'phase4_to_phase5': [
            QualityThreshold(
                metric_name='ml_feature_count',
                min_count=50,  # At least 50 players in feature store
                severity='critical'
            ),
        ],
    }

    def __init__(self, transition_name: str, bq_client, project_id: str):
        """
        Initialize circuit breaker for a phase transition.

        Args:
            transition_name: Name of transition (e.g., "phase3a_to_phase3b")
            bq_client: BigQuery client
            project_id: GCP project ID
        """
        self.transition_name = transition_name
        self.bq_client = bq_client
        self.project_id = project_id
        self.thresholds = self.THRESHOLDS.get(transition_name, [])
        self.state = CircuitState.CLOSED

    def check_and_block(self, game_date: date) -> Tuple[bool, List[str], Dict]:
        """
        Check data quality and determine if phase should proceed.

        Args:
            game_date: Date being processed

        Returns:
            (can_proceed, errors, metrics)
        """
        errors = []
        metrics = {}

        for threshold in self.thresholds:
            try:
                value = self._measure_metric(threshold.metric_name, game_date)
                metrics[threshold.metric_name] = value

                # Check threshold violations
                if threshold.min_value is not None and value < threshold.min_value:
                    msg = f"{threshold.metric_name}={value} below min {threshold.min_value}"
                    if threshold.severity == 'critical':
                        errors.append(msg)
                    else:
                        logger.warning(f"Quality warning: {msg}")

                if threshold.max_value is not None and value > threshold.max_value:
                    msg = f"{threshold.metric_name}={value} above max {threshold.max_value}"
                    if threshold.severity == 'critical':
                        errors.append(msg)
                    else:
                        logger.warning(f"Quality warning: {msg}")

                if threshold.min_count is not None and value < threshold.min_count:
                    msg = f"{threshold.metric_name}={value} below min count {threshold.min_count}"
                    if threshold.severity == 'critical':
                        errors.append(msg)
                    else:
                        logger.warning(f"Quality warning: {msg}")

                if threshold.max_null_pct is not None and value > threshold.max_null_pct:
                    msg = f"{threshold.metric_name}={value}% above max NULL {threshold.max_null_pct}%"
                    if threshold.severity == 'critical':
                        errors.append(msg)
                    else:
                        logger.warning(f"Quality warning: {msg}")

            except Exception as e:
                logger.error(f"Failed to measure {threshold.metric_name}: {e}")
                if threshold.severity == 'critical':
                    errors.append(f"Failed to measure {threshold.metric_name}")

        can_proceed = len(errors) == 0

        if not can_proceed:
            self.state = CircuitState.OPEN
            logger.error(
                f"Circuit breaker OPEN for {self.transition_name}: {errors}"
            )
        else:
            self.state = CircuitState.CLOSED
            logger.info(
                f"Circuit breaker CLOSED for {self.transition_name}: metrics={metrics}"
            )

        return can_proceed, errors, metrics

    def _measure_metric(self, metric_name: str, game_date: date) -> float:
        """
        Measure a specific data quality metric.
        """
        game_date_str = game_date.isoformat()

        queries = {
            'team_offense_game_count': f"""
                SELECT COUNT(DISTINCT game_id) as value
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE game_date = '{game_date_str}'
            """,
            'team_offense_fg_attempts': f"""
                SELECT AVG(fg_attempts) as value
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE game_date = '{game_date_str}'
            """,
            'player_game_count': f"""
                SELECT COUNT(*) as value
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date = '{game_date_str}'
            """,
            'usage_rate_null_pct': f"""
                SELECT
                    ROUND(100.0 * COUNTIF(usage_rate IS NULL) / COUNT(*), 1) as value
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date = '{game_date_str}'
            """,
            'upcoming_player_count': f"""
                SELECT COUNT(DISTINCT player_lookup) as value
                FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
                WHERE game_date = '{game_date_str}'
            """,
            'has_prop_line_pct': f"""
                SELECT
                    ROUND(100.0 * COUNTIF(has_prop_line = TRUE) / COUNT(*), 1) as value
                FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
                WHERE game_date = '{game_date_str}'
            """,
            'ml_feature_count': f"""
                SELECT COUNT(DISTINCT player_lookup) as value
                FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
                WHERE game_date = '{game_date_str}'
            """,
        }

        if metric_name not in queries:
            raise ValueError(f"Unknown metric: {metric_name}")

        result = list(self.bq_client.query(queries[metric_name]).result())
        return result[0].value if result and result[0].value is not None else 0
```

#### Integration with Phase Orchestrators

```python
# orchestration/cloud_functions/phase3a_to_phase3b/main.py (enhancement)

from shared.validation.phase_circuit_breaker import PhaseCircuitBreaker

def trigger_phase3b(game_date: str, ...):
    """
    Trigger Phase 3b after validating Phase 3a data quality.
    """
    # Circuit breaker check
    circuit_breaker = PhaseCircuitBreaker(
        transition_name='phase3a_to_phase3b',
        bq_client=get_bigquery_client(),
        project_id=PROJECT_ID
    )

    can_proceed, errors, metrics = circuit_breaker.check_and_block(
        game_date=datetime.strptime(game_date, '%Y-%m-%d').date()
    )

    if not can_proceed:
        logger.error(
            f"Circuit breaker BLOCKING Phase 3b trigger: {errors}"
        )

        # Send alert
        notify_error(
            title=f"Phase 3a→3b Blocked by Circuit Breaker",
            message=f"Data quality check failed for {game_date}",
            details={
                'game_date': game_date,
                'errors': errors,
                'metrics': metrics
            },
            processor_name='phase3a_to_phase3b'
        )

        # Log to BigQuery for monitoring
        log_circuit_breaker_block(game_date, 'phase3a_to_phase3b', errors, metrics)

        # CRITICAL: Do NOT trigger Phase 3b
        return None

    # Data quality OK - proceed with Phase 3b trigger
    publisher.publish(PHASE3B_TRIGGER_TOPIC, ...)
```

#### Automatic Rollback for Quality Failures

```python
# shared/validation/auto_rollback.py (NEW FILE)

"""
Automatic Rollback for Data Quality Failures

When a processor completes but data quality check fails,
automatically delete the bad data and alert operators.
"""

class AutoRollback:
    """
    Automatically rolls back bad data when quality checks fail.
    """

    def __init__(self, bq_client, project_id: str):
        self.bq_client = bq_client
        self.project_id = project_id

    def rollback_phase_data(
        self,
        phase_name: str,
        game_date: str,
        reason: str
    ) -> bool:
        """
        Delete data for a specific phase and game_date.

        Args:
            phase_name: Phase to rollback (e.g., "phase3b")
            game_date: Date to rollback
            reason: Reason for rollback (for audit)
        """
        # Map phase to tables
        phase_tables = {
            'phase3a': [
                'nba_analytics.team_offense_game_summary',
                'nba_analytics.team_defense_game_summary',
            ],
            'phase3b': [
                'nba_analytics.player_game_summary',
            ],
            'phase3c': [
                'nba_analytics.upcoming_player_game_context',
                'nba_analytics.upcoming_team_game_context',
            ],
            'phase4': [
                'nba_predictions.ml_feature_store_v2',
                'nba_precompute.player_daily_cache',
            ],
        }

        tables = phase_tables.get(phase_name, [])
        if not tables:
            logger.warning(f"No tables defined for phase {phase_name}")
            return False

        # Log rollback intent
        logger.warning(
            f"AUTO ROLLBACK: Deleting {phase_name} data for {game_date}. "
            f"Reason: {reason}. Tables: {tables}"
        )

        # Delete from each table
        for table in tables:
            try:
                query = f"""
                DELETE FROM `{self.project_id}.{table}`
                WHERE game_date = '{game_date}'
                """
                job = self.bq_client.query(query)
                job.result()

                logger.info(f"Rolled back {table} for {game_date}")

            except Exception as e:
                logger.error(f"Failed to rollback {table}: {e}")
                return False

        # Log to audit table
        self._log_rollback(phase_name, game_date, reason, tables)

        # Send alert
        notify_warning(
            title=f"Auto Rollback: {phase_name} data deleted",
            message=f"Bad data automatically rolled back for {game_date}",
            details={
                'phase': phase_name,
                'game_date': game_date,
                'reason': reason,
                'tables_affected': tables
            },
            processor_name='AutoRollback'
        )

        return True
```

---

## Migration Plan

### Phase 1: Foundation (Week 1)

```
Priority: P0 - Critical
Duration: 3-5 days

Tasks:
1. Create Pub/Sub topics:
   - nba-phase3a-trigger
   - nba-phase3a-analytics-complete
   - nba-phase3b-trigger
   - nba-phase3b-analytics-complete
   - nba-phase3c-trigger
   - nba-betting-lines-complete

2. Deploy new orchestrators:
   - phase3a_to_phase3b
   - phase3b_to_phase3c
   - betting_lines_to_phase3c

3. Add feature flags:
   - PHASE3_SUB_PHASES_ENABLED=false (disabled initially)
   - BETTING_LINES_COORDINATION_ENABLED=false

4. Deploy monitoring:
   - Circuit breaker metrics to BigQuery
   - Slack alerts for circuit breaker blocks
```

### Phase 2: Gradual Rollout (Week 2)

```
Priority: P1 - High
Duration: 3-5 days

Tasks:
1. Enable Phase 3 sub-phases for overnight mode only:
   - Set PHASE3_SUB_PHASES_ENABLED=true
   - Set PHASE3_SUB_PHASES_MODE=overnight_only
   - Monitor for 2 days

2. Validate team stats -> player stats dependency:
   - Run backfill for Jan 20-26 with new ordering
   - Verify usage_rate NULL rate drops to <5%

3. Enable betting lines coordination:
   - Set BETTING_LINES_COORDINATION_ENABLED=true
   - Monitor betting_lines -> Phase 3c refresh flow
```

### Phase 3: Full Rollout (Week 3)

```
Priority: P2 - Medium
Duration: 5-7 days

Tasks:
1. Enable Phase 3 sub-phases for all modes:
   - Remove overnight_only restriction
   - Enable for same_day and tomorrow modes

2. Deploy distributed lock for backfills:
   - Update all backfill jobs with BackfillLock
   - Test with concurrent backfill scenarios

3. Deploy circuit breakers at all phase boundaries:
   - Phase 2 -> Phase 3a
   - Phase 3a -> Phase 3b
   - Phase 3b -> Phase 3c
   - Phase 3c -> Phase 4
   - Phase 4 -> Phase 5

4. Enable auto-rollback for quality failures:
   - Deploy AutoRollback class
   - Test rollback scenarios
```

### Phase 4: Monitoring & Refinement (Week 4+)

```
Priority: P3 - Ongoing
Duration: Ongoing

Tasks:
1. Tune quality thresholds based on production data:
   - Adjust usage_rate_null_pct threshold
   - Adjust has_prop_line_pct threshold

2. Add dashboard for phase latencies:
   - Track Phase 3a, 3b, 3c separately
   - Identify bottlenecks

3. Document runbooks for circuit breaker scenarios:
   - What to do when phase3a_to_phase3b blocks
   - How to force proceed if false positive
```

---

## Risk Assessment

### High Risk Items

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Phase 3 sub-phases increase total latency | High | Medium | Accept 10 min increase; parallelize within sub-phases |
| Betting lines scraper completion topic not published | Medium | High | Fallback: prediction coordinator direct query |
| Distributed locks cause deadlock | Low | High | Sort dates before locking; use timeout |
| Circuit breaker false positives block good data | Medium | Medium | Start with warning-only; tune thresholds |

### Rollback Plan

Each change has a feature flag that can be toggled:

```python
# Feature flags for instant rollback
PHASE3_SUB_PHASES_ENABLED = os.environ.get('PHASE3_SUB_PHASES_ENABLED', 'false')
BETTING_LINES_COORDINATION_ENABLED = os.environ.get('BETTING_LINES_COORDINATION_ENABLED', 'false')
BACKFILL_LOCKING_ENABLED = os.environ.get('BACKFILL_LOCKING_ENABLED', 'false')
CIRCUIT_BREAKERS_BLOCKING = os.environ.get('CIRCUIT_BREAKERS_BLOCKING', 'false')  # vs warning-only
```

---

## Implementation Priority

| Priority | Component | Effort | Impact | Dependencies |
|----------|-----------|--------|--------|--------------|
| **P0** | Phase 3 Sub-Phases Design | High | Critical | None |
| **P0** | Betting Lines Coordination | Medium | Critical | Pub/Sub topic |
| **P1** | Circuit Breakers (warning mode) | Medium | High | BigQuery metrics |
| **P1** | Distributed Lock for Backfills | Medium | High | Firestore |
| **P2** | Circuit Breakers (blocking mode) | Low | Medium | P1 complete |
| **P2** | Auto-Rollback | Medium | Medium | Circuit breakers |
| **P3** | Latency Dashboard | Low | Low | All above |

### Quick Wins (Can implement today)

1. **Alert for 0 predictions**: Add `notify_error()` in coordinator.py when 0 eligible players
2. **Alert for high NULL usage_rate**: Add scheduled BigQuery query
3. **Alert for 100% has_prop_line=FALSE**: Add scheduled BigQuery query

---

## Appendix: Code Locations

| Component | File Path |
|-----------|-----------|
| Master Controller | `/home/naji/code/nba-stats-scraper/orchestration/master_controller.py` |
| Workflow Executor | `/home/naji/code/nba-stats-scraper/orchestration/workflow_executor.py` |
| Distributed Lock | `/home/naji/code/nba-stats-scraper/orchestration/shared/utils/distributed_lock.py` |
| Circuit Breaker | `/home/naji/code/nba-stats-scraper/orchestration/shared/utils/circuit_breaker.py` |
| Phase 3->4 Orchestrator | `/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/phase3_to_phase4/main.py` |
| Player Game Summary | `/home/naji/code/nba-stats-scraper/data_processors/analytics/player_game_summary/player_game_summary_processor.py` |
| Prediction Coordinator | `/home/naji/code/nba-stats-scraper/predictions/coordinator/coordinator.py` |
| Backfill Job | `/home/naji/code/nba-stats-scraper/backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py` |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-27 | Claude Opus 4.5 | Initial design document |
