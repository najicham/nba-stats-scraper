# Granular Updates & Efficiency Optimizations

**File:** `docs/01-architecture/change-detection/granular-updates.md`
**Created:** 2025-11-14 22:16 PST
**Last Updated:** 2025-11-15 (Status update, content reduction)
**Purpose:** Entity-level granularity design for incremental updates (performance optimization)
**Status:** Planned Enhancement - Date-level processing ships first, entity-level in Sprint 8
**Related:** [04-event-driven-pipeline-architecture.md](./04-event-driven-pipeline-architecture.md) (complete architecture)

---

## Table of Contents

1. [Opportunistic Triggering Behavior](#opportunistic-triggering-behavior)
2. [Granular Entity-Level Updates](#granular-entity-level-updates)
3. [Pub/Sub Multi-Subscriber Pattern](#pubsub-multi-subscriber-pattern)
4. [Phase 6 Publishing Layer](#phase-6-publishing-layer)
5. [Efficiency Optimizations](#efficiency-optimizations)

---

## Opportunistic Triggering Behavior

**Summary:** Each Phase 2 update triggers Phase 3 processors, which check dependencies and skip if not ready (automatic retry on next event). This provides automatic retries without complex state management.

**For detailed explanation with timeline examples**, see [04-event-driven-pipeline-architecture.md](./04-event-driven-pipeline-architecture.md) "Addressing Concern 1: Dependency Coordination" (lines 182-292).

### Key Points

**1. Automatic Retries** - Each Phase 2 completion triggers Phase 3, which checks dependencies via `check_dependencies()`. If not ready, it skips (will retry on next trigger).

**2. Idempotency** - Processors track recent executions to prevent duplicate processing of the same data.

**3. Critical vs Optional Dependencies** - Can process with critical dependencies only; optional ones enhance but don't block.

**4. Self-Healing** - Late-arriving dependencies automatically trigger re-evaluation (but idempotency prevents unnecessary reprocessing).

---

## Granular Entity-Level Updates

### The Problem: All or Nothing

**Current Plan:**
```python
# Phase 2 message
{
    "game_date": "2025-11-15",
    "record_count": 450
}

# Phase 3 processes ALL players for that date
processor.run({'start_date': '2025-11-15', 'end_date': '2025-11-15'})
# → Processes ALL 450 player records
```

**Your Question:** "What about when one team's data changes in phase 2? ... not re-run the processor for all teams and all players."

**Answer:** Right now it IS "all or nothing" - but we can fix this! Here's how:

### Solution: Entity-Level Granularity

**Enhanced Phase 2 Message:**

```json
{
  "event_type": "raw_data_loaded",
  "source_table": "nbac_injury_report",
  "game_date": "2025-11-15",
  "record_count": 1,

  "affected_entities": {
    "players": ["1630567"],           // LeBron James universal_player_id
    "teams": ["LAL"],                 // Lakers
    "games": ["0022500225"]           // LAL vs BOS game
  },

  "change_type": "incremental",       // or "full_load"
  "timestamp": "2025-11-15T14:30:00Z"
}
```

**Phase 3 Processor Enhancement:**

```python
class PlayerGameSummaryProcessor(AnalyticsProcessorBase):

    def run(self, opts: dict) -> bool:
        """
        Enhanced to support entity-level processing.

        opts can include:
        - start_date/end_date: Process all players for date range (existing)
        - player_ids: Process only specific players (NEW)
        - game_ids: Process only specific games (NEW)
        - team_ids: Process all players for specific teams (NEW)
        """

        # Determine processing scope
        if 'player_ids' in opts and opts['player_ids']:
            # Incremental: Process only specified players
            self.processing_mode = 'incremental_players'
            logger.info(f"Processing {len(opts['player_ids'])} specific players")

        elif 'game_ids' in opts and opts['game_ids']:
            # Game-level: Process all players in specified games
            self.processing_mode = 'incremental_games'
            logger.info(f"Processing {len(opts['game_ids'])} specific games")

        elif 'team_ids' in opts and opts['team_ids']:
            # Team-level: Process all players for specified teams
            self.processing_mode = 'incremental_teams'
            logger.info(f"Processing {len(opts['team_ids'])} specific teams")

        else:
            # Full: Process all players for date range
            self.processing_mode = 'full_date_range'
            logger.info(f"Processing full date range: {opts['start_date']} to {opts['end_date']}")

        # ... rest of processing
```

### Real-World Scenarios

#### Scenario 1: Injury Report Update (Pre-Game)

**What happens:**
```
2:00 PM - LeBron James ruled OUT for tonight's game

Phase 1: nbac_injury_report scraper runs
         → Finds 1 new injury
         → Publishes to Phase 2

Phase 2: NbacInjuryReportProcessor runs
         → Loads 1 record to nba_raw.nbac_injury_report
         → Publishes:
         {
           "source_table": "nbac_injury_report",
           "game_date": "2025-11-15",
           "affected_entities": {
             "players": ["1630567"],    // LeBron
             "teams": ["LAL"],
             "games": ["0022500225"]
           },
           "change_type": "incremental"
         }

Phase 3: Analytics service receives event
         → Triggers: PlayerGameSummaryProcessor
         → Passes player_ids=['1630567']
         → Processor updates ONLY LeBron's record
         → Takes 0.5 seconds (vs 30 seconds for all players)
         → Publishes to Phase 4:
         {
           "affected_entities": {
             "players": ["1630567"]
           }
         }

Phase 4: Precompute processors
         → Update ONLY LeBron's precomputed features
         → Fast incremental update

Phase 5: Prediction processors
         → Re-run predictions for games involving LeBron
         → game_ids=["0022500225"]
         → Don't re-run predictions for other games
```

**Result:** Injury update propagates through entire pipeline in **seconds**, not minutes!

#### Scenario 2: Betting Line Update (Pre-Game)

**What happens:**
```
5:00 PM - Lakers point spread moves from -5.5 to -6.5

Phase 1: oddsa_current_game_lines scraper runs
         → Finds 1 updated line
         → Publishes to Phase 2

Phase 2: OddsGameLinesProcessor runs
         → Updates 1 record in nba_raw.odds_api_game_lines
         → Publishes:
         {
           "source_table": "odds_api_game_lines",
           "affected_entities": {
             "games": ["0022500225"],
             "teams": ["LAL", "BOS"]
           },
           "change_type": "incremental"
         }

Phase 3: Analytics service receives
         → Triggers: TeamOffenseProcessor, TeamDefenseProcessor
         → Passes game_ids=["0022500225"]
         → Updates only this game's context

Phase 4-5: Incremental updates for this game only
```

#### Scenario 3: Post-Game Boxscore (Full Load)

**What happens:**
```
10:05 PM - All boxscores for all games load

Phase 2: NbacGamebookProcessor runs
         → Loads 450 player records (10 games × 25 players × 1.8)
         → Publishes:
         {
           "source_table": "nbac_gamebook_player_stats",
           "game_date": "2025-11-15",
           "affected_entities": {
             "games": ["0022500225", "0022500226", ...],  // All 10 games
             "players": [...],  // All 450 players
             "teams": [...]     // All 20 teams
           },
           "change_type": "full_load"
         }

Phase 3: Analytics service receives
         → change_type = "full_load"
         → Processes ALL players for the date
         → This is expected and correct for post-game
```

### Implementation Strategy

**Phase 1: Ship with Date-Level Granularity**
- Simple, working system
- Process entire game_date
- Document the pattern for future enhancement

**Phase 2: Add Game-Level Granularity (Week 5-6)**
- Add `game_ids` parameter support
- Phase 2 messages include affected games
- Reduces processing scope significantly

**Phase 3: Add Entity-Level Granularity (Week 7-8)**
- Add `player_ids`, `team_ids` parameters
- Phase 2 messages track which entities changed
- Maximum efficiency for incremental updates

**Benefits of Phased Approach:**
- Ship working system quickly
- Optimize later based on real metrics
- Don't over-engineer upfront

---

## Pub/Sub Multi-Subscriber Pattern

**Answer:** ✅ YES - Multiple Phase 3 processors can use the same Phase 2 message. This is the fundamental value of Pub/Sub's fan-out pattern!

**For complete explanation** with architecture diagrams and code examples, see [04-event-driven-pipeline-architecture.md](./04-event-driven-pipeline-architecture.md) "Addressing Concern 3: Pub/Sub Multi-Subscriber Pattern" (lines 472-587).

### Key Benefits

1. **Fan-Out** - One Phase 2 event triggers multiple Phase 3 processors independently
2. **Independent Execution** - One processor failure doesn't block others
3. **Future Extensibility** - Add monitoring/audit subscriptions without affecting existing flow
4. **Reliability** - Each processor has its own retry logic and DLQ

---

## Phase 6 Publishing Layer

### Overview

**Phase 6: Publishing to Web App**
```
Phase 5 (Predictions) → Phase 6 (Publishing) → Firestore + GCS
                                               → Web App reads
```

### Why Phase 6 Exists

**Separation of Concerns:**
- Phases 1-5: Data pipeline (internal)
- Phase 6: External API layer (public-facing)

**Benefits:**
1. **Optimized for reads**: Firestore is real-time, GCS is cacheable
2. **Security**: Only published data exposed to web app
3. **Versioning**: Can publish different views/versions
4. **Performance**: Pre-computed, denormalized for fast reads

### Proposed Architecture

**Input:** Phase 5 analytics tables
```
nba_predictions.game_predictions
nba_predictions.player_prop_predictions
nba_predictions.ensemble_predictions
```

**Output:** Published formats
```
Firestore:
  /predictions/daily/{date}
  /predictions/games/{game_id}
  /predictions/players/{player_id}/props

GCS:
  gs://nba-predictions-public/
    ├─ latest/
    │  ├─ daily.json
    │  ├─ games/{game_id}.json
    │  └─ players/{player_id}.json
    ├─ historical/
    │  └─ {date}/...
    └─ api/
       └─ v1/...
```

### Triggering Strategy

**Option A: Event-Driven (Recommended)**
```
Phase 5 completes → Publishes "predictions_ready" event
                 → Phase 6 PublishingService receives
                 → Publishes to Firestore + GCS
```

**Option B: Scheduled**
```
Cron: Every hour → Check for new predictions
                 → Publish if updated
```

**Option C: Hybrid**
```
Event-driven for live games (real-time)
Scheduled for daily summaries (batch)
```

### Message Format (Phase 5 → Phase 6)

```json
{
  "event_type": "predictions_ready",
  "prediction_type": "game_predictions",
  "game_date": "2025-11-15",
  "game_ids": ["0022500225", "0022500226"],
  "prediction_count": 24,
  "timestamp": "2025-11-15T17:00:00Z",
  "model_version": "ensemble_v2.1",
  "confidence_threshold": 0.65
}
```

### Publishing Service (Conceptual)

```python
class PublishingService:
    """
    Phase 6: Publishes predictions to Firestore and GCS for web app consumption.
    """

    def process_event(self, message):
        """Handle prediction_ready events."""

        game_date = message['game_date']
        game_ids = message['game_ids']

        # Fetch predictions from BigQuery
        predictions = self.fetch_predictions(game_date, game_ids)

        # Transform to web-friendly format
        published_data = self.transform_for_web(predictions)

        # Publish to Firestore (real-time access)
        self.publish_to_firestore(published_data)

        # Publish to GCS (cacheable, CDN-friendly)
        self.publish_to_gcs(published_data)

        # Update metadata
        self.update_publish_metadata(game_date)

    def transform_for_web(self, predictions):
        """
        Transform BigQuery schema to web-friendly JSON.

        - Denormalize (include team names, not just IDs)
        - Add computed fields (human-readable labels)
        - Filter (only high-confidence predictions)
        - Sort (by start time, by confidence)
        """
        return {
            "games": [...],
            "player_props": [...],
            "meta": {
                "generated_at": "...",
                "model_version": "...",
                "game_count": 10
            }
        }
```

### Data Flow Example

```
6:00 PM - Pre-game predictions ready

Phase 5: EnsemblePredictor completes
         → 24 game predictions + 200 player prop predictions
         → Writes to BigQuery:
           - nba_predictions.game_predictions
           - nba_predictions.player_prop_predictions
         → Publishes Pub/Sub event

Phase 6: PublishingService receives event
         ├─→ Fetches predictions from BigQuery
         ├─→ Transforms to web format (denormalized)
         ├─→ Publishes to Firestore:
         │   /predictions/daily/2025-11-15
         │   /predictions/games/0022500225
         │   /predictions/games/0022500226
         │   ...
         ├─→ Publishes to GCS:
         │   gs://.../latest/daily.json
         │   gs://.../latest/games/0022500225.json
         │   ...
         └─→ Updates metadata (last_published timestamp)

Web App: Reads from Firestore (real-time)
         OR reads from GCS (cached via CDN)
```

### Benefits of Separate Phase 6

**1. Flexibility**
- Can publish different formats (JSON, Protocol Buffers, etc.)
- Can version APIs (v1, v2)
- Can A/B test prediction models

**2. Performance**
- Pre-computed queries
- Denormalized data (fast reads)
- CDN caching (GCS)
- Real-time updates (Firestore)

**3. Security**
- Only published data exposed
- Can filter sensitive fields
- Can add authentication layer

**4. Decoupling**
- Web app doesn't query BigQuery directly
- Can change prediction schema without breaking web app
- Can rate limit / throttle if needed

---

## Efficiency Optimizations

### Summary of Efficiency Features

| Feature | Status | Benefit |
|---------|--------|---------|
| Entity-level granularity | Planned (Phase 2-3) | 10-100x faster for incremental updates |
| Idempotency checking | Planned (Phase 1) | Prevents duplicate processing |
| Dependency tracking | ✅ Implemented | Only process when ready |
| Multi-subscriber Pub/Sub | ✅ By design | No message duplication needed |
| Opportunistic triggering | Planned (Phase 1) | Automatic retries |
| MERGE_UPDATE strategy | ✅ Implemented | Upsert semantics (no duplicates) |

### Expected Performance

**Initial Implementation (Date-Level):**
```
Injury update (1 player) → Processes 450 players → 30 seconds
Boxscore load (all games) → Processes 450 players → 30 seconds
```

**With Entity-Level Optimization:**
```
Injury update (1 player) → Processes 1 player → 0.5 seconds (60x faster!)
Boxscore load (all games) → Processes 450 players → 30 seconds (same)
```

**Trade-off:**
- Initial: Simpler, works correctly, slightly wasteful
- Optimized: More complex, maximally efficient

**Recommendation:** Ship initial, optimize based on metrics.

---

## Implementation Roadmap

**For complete prioritized roadmap and effort estimates**, see [05-implementation-status-and-roadmap.md](./05-implementation-status-and-roadmap.md).

### Entity-Level Granularity Timeline

**Sprint 1-3 (Weeks 1-3):** Ship with **date-level granularity**
- Simple, working system
- Process entire game_date
- Validate architecture patterns

**Sprint 8 (Week 7-8):** Add **entity-level granularity** (~12 hours)
- Add `player_ids`, `game_ids`, `team_ids` parameters
- Measure performance improvements
- Expected: 60x faster for single-player updates (0.5s vs 30s)

---

## Corner Cases & Edge Cases

### 1. Message Ordering

**Q:** What if Phase 2 messages arrive out of order?

**A:** Not a problem!
- Each message is processed independently
- Dependency checking ensures data exists
- BigQuery MERGE handles upserts correctly
- Latest data wins (based on timestamps)

### 2. Duplicate Messages

**Q:** What if Pub/Sub delivers the same message twice?

**A:** Idempotency handles this
- Check if already processed recently
- If yes → skip
- No data corruption

### 3. Partial Failures

**Q:** What if 2 of 3 Phase 3 processors succeed?

**A:** That's OK!
- Each processor independent
- Failed one can be retried manually
- Message is acknowledged
- System keeps moving

### 4. Late-Arriving Dependencies

**Q:** What if optional dependency arrives 2 hours later?

**A:** Current design: Won't re-process (idempotency)
**Future:** Could add "force_refresh" parameter if needed

### 5. Concurrent Updates

**Q:** What if two Phase 2 updates happen simultaneously?

**A:** Both trigger Phase 3 independently
- First one processes
- Second one skipped (idempotency)
- OR: Could process if >1 hour apart

---

## Next Steps

**Immediate:**
1. Review this granular update design
2. Decide: Ship date-level first, or include game-level from start?
3. Approve Pub/Sub multi-subscriber pattern
4. Approve Phase 6 architecture concept

**Implementation:**
1. Start with date-level (simpler, faster to ship)
2. Measure actual performance
3. Optimize to game/entity-level if needed
4. Add Phase 6 when predictions ready

---

**Key Takeaway:** The architecture supports efficient incremental updates, we just need to implement the granularity levels progressively. Start simple, optimize based on real data.

**Last Updated:** 2025-11-15
