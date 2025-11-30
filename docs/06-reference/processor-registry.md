# Processor Registry Reference

**File:** `docs/reference/04-processor-registry-reference.md`
**Created:** 2025-11-23
**Purpose:** Quick reference for Pub/Sub processor registries
**Audience:** Engineers needing to know which processors run when

---

## Quick Lookup

**"What processors run when bdl_player_boxscores completes?"**
→ PlayerGameSummary, TeamOffenseGameSummary, UpcomingPlayerGameContext

**"What triggers TeamDefenseZoneAnalysisProcessor?"**
→ When `team_defense_game_summary` table is updated (Phase 3 completion)

**"Which processors check multiple dependencies?"**
→ PlayerCompositeFactors (CASCADE), MLFeatureStore (CASCADE)

---

## Phase 3: Analytics Triggers

**File Location:** `data_processors/analytics/main_analytics_service.py`
**Registry Name:** `ANALYTICS_TRIGGERS`

### Trigger Registry

| Source Table (Phase 2) | Triggers These Phase 3 Processors |
|------------------------|----------------------------------|
| `bdl_player_boxscores` | • PlayerGameSummaryProcessor<br>• TeamOffenseGameSummaryProcessor<br>• UpcomingPlayerGameContextProcessor |
| `nbac_scoreboard_v2` | • TeamOffenseGameSummaryProcessor<br>• TeamDefenseGameSummaryProcessor<br>• UpcomingTeamGameContextProcessor |
| `nbac_gamebook_player_stats` | • PlayerGameSummaryProcessor |
| `nbac_injury_report` | • PlayerGameSummaryProcessor |
| `odds_api_player_points_props` | • PlayerGameSummaryProcessor |
| `bdl_standings` | (No processors yet) |

### Processor Details

| Processor | Triggered By | Frequency | Purpose |
|-----------|-------------|-----------|---------|
| **PlayerGameSummaryProcessor** | 4 sources | Per game | Aggregate player stats |
| **TeamOffenseGameSummaryProcessor** | 2 sources | Per game | Team offensive metrics |
| **TeamDefenseGameSummaryProcessor** | 1 source | Per game | Team defensive metrics |
| **UpcomingPlayerGameContextProcessor** | 1 source | Per game | Player prop context |
| **UpcomingTeamGameContextProcessor** | 1 source | Per game | Team context |

### How It Works

```python
# In main_analytics_service.py

ANALYTICS_TRIGGERS = {
    'bdl_player_boxscores': [
        PlayerGameSummaryProcessor,
        TeamOffenseGameSummaryProcessor,
        UpcomingPlayerGameContextProcessor
    ],
    'nbac_scoreboard_v2': [
        TeamOffenseGameSummaryProcessor,
        TeamDefenseGameSummaryProcessor,
        UpcomingTeamGameContextProcessor
    ],
}

# When Phase 2 publishes:
# {"source_table": "bdl_player_boxscores", "game_date": "2024-11-22"}
#
# Phase 3 automatically runs:
# - PlayerGameSummaryProcessor
# - TeamOffenseGameSummaryProcessor
# - UpcomingPlayerGameContextProcessor
```

---

## Phase 4: Precompute Triggers

**File Location:** `data_processors/precompute/main_precompute_service.py`
**Registry Name:** `PRECOMPUTE_TRIGGERS`

### Trigger Registry

| Analytics Table (Phase 3) | Triggers These Phase 4 Processors |
|---------------------------|----------------------------------|
| `player_game_summary` | • PlayerDailyCacheProcessor |
| `team_defense_game_summary` | • TeamDefenseZoneAnalysisProcessor |
| `team_offense_game_summary` | • PlayerShotZoneAnalysisProcessor |
| `upcoming_player_game_context` | • PlayerDailyCacheProcessor |
| `upcoming_team_game_context` | (No triggers yet) |

### Processor Details

| Processor | Triggered By | Type | Purpose |
|-----------|-------------|------|---------|
| **TeamDefenseZoneAnalysisProcessor** | `team_defense_game_summary` | Standard | Zone defense analysis |
| **PlayerShotZoneAnalysisProcessor** | `team_offense_game_summary` | Standard | Shot zone patterns |
| **PlayerDailyCacheProcessor** | `player_game_summary`, `upcoming_player_game_context` | Standard | Player daily aggregates |
| **PlayerCompositeFactorsProcessor** | Manual/Scheduled | **CASCADE** | Composite scoring factors |
| **MLFeatureStoreProcessor** | Manual/Scheduled | **CASCADE** | ML feature generation |

### How It Works

```python
# In main_precompute_service.py

PRECOMPUTE_TRIGGERS = {
    'player_game_summary': [PlayerDailyCacheProcessor],
    'team_defense_game_summary': [TeamDefenseZoneAnalysisProcessor],
    'team_offense_game_summary': [PlayerShotZoneAnalysisProcessor],
    'upcoming_player_game_context': [PlayerDailyCacheProcessor],
}

# When Phase 3 publishes:
# {"source_table": "team_defense_game_summary", "analysis_date": "2024-11-22"}
#
# Phase 4 automatically runs:
# - TeamDefenseZoneAnalysisProcessor
```

---

## CASCADE Processors (Multiple Dependencies)

**Registry Name:** `CASCADE_PROCESSORS` (documented, not auto-triggered)

CASCADE processors check `is_production_ready` from **all** upstream dependencies before processing.

### PlayerCompositeFactorsProcessor

**Checks 4 upstreams:**
1. `team_defense_zone_analysis` (Phase 4)
2. `player_shot_zone_analysis` (Phase 4)
3. `player_daily_cache` (Phase 4)
4. `upcoming_player_game_context` (Phase 3)

**Trigger:** Manual or scheduled (11 PM daily)

**Behavior:**
- Queries all 4 upstreams for `is_production_ready`
- Only processes if ALL upstreams are production-ready
- Populates `data_quality_issues` array if any missing
- Sends email alert if critical dependencies missing

### MLFeatureStoreProcessor

**Checks 5 upstreams (all Phase 4):**
1. `team_defense_zone_analysis`
2. `player_shot_zone_analysis`
3. `player_daily_cache`
4. `player_composite_factors`
5. `ml_feature_store_v2` (historical)

**Trigger:** Manual or scheduled (11:30 PM daily)

**Behavior:**
- Checks all Phase 4 processors are production-ready
- Final step before Phase 5 predictions
- Most stringent dependency checking

---

## Manual Endpoints

### Phase 3: `/process-date-range`

**URL:** `https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range`

**Processors Available:**
```bash
# All 5 processors can be triggered manually
processors=(
  "PlayerGameSummaryProcessor"
  "TeamOffenseGameSummaryProcessor"
  "TeamDefenseGameSummaryProcessor"
  "UpcomingPlayerGameContextProcessor"
  "UpcomingTeamGameContextProcessor"
)
```

**Example:**
```bash
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "processors": ["UpcomingPlayerGameContextProcessor"],
    "start_date": "2024-11-22",
    "end_date": "2024-11-22"
  }'
```

### Phase 4: `/process-date`

**URL:** `https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date`

**Processors Available:**
```bash
# All 5 processors can be triggered manually
processors=(
  "TeamDefenseZoneAnalysisProcessor"
  "PlayerShotZoneAnalysisProcessor"
  "PlayerDailyCacheProcessor"
  "PlayerCompositeFactorsProcessor"
  "MLFeatureStoreProcessor"
)
```

**Example:**
```bash
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "processors": ["PlayerCompositeFactorsProcessor"],
    "analysis_date": "2024-11-22"
  }'
```

---

## Pub/Sub Message Format

### Phase 2 → Phase 3

```json
{
  "message": {
    "data": "eyJzb3VyY2VfdGFibGUiOiAiYmRsX3BsYXllcl9ib3hzY29yZXMiLCAiZ2FtZV9kYXRlIjogIjIwMjQtMTEtMjIiLCAic3VjY2VzcyI6IHRydWV9",
    "messageId": "1234567890",
    "publishTime": "2024-11-22T10:00:00Z"
  }
}
```

**Decoded data:**
```json
{
  "source_table": "bdl_player_boxscores",
  "game_date": "2024-11-22",
  "success": true
}
```

### Phase 3 → Phase 4

```json
{
  "source_table": "team_defense_game_summary",
  "analysis_date": "2024-11-22",
  "processor_name": "TeamDefenseGameSummaryProcessor",
  "success": true
}
```

---

## Flow Diagrams

### Complete Phase 2→3→4 Flow

```
Phase 2: bdl_player_boxscores completes
    ↓ publishes to nba-phase2-raw-complete
Phase 3: Receives Pub/Sub message
    ↓ looks up ANALYTICS_TRIGGERS['bdl_player_boxscores']
    ↓ runs 3 processors:
    ├─ PlayerGameSummaryProcessor
    │    ↓ publishes to nba-phase3-analytics-complete
    │    Phase 4: PlayerDailyCacheProcessor (triggered)
    │
    ├─ TeamOffenseGameSummaryProcessor
    │    ↓ publishes to nba-phase3-analytics-complete
    │    Phase 4: PlayerShotZoneAnalysisProcessor (triggered)
    │
    └─ UpcomingPlayerGameContextProcessor
         ↓ publishes to nba-phase3-analytics-complete
         Phase 4: PlayerDailyCacheProcessor (triggered again)

Later (11 PM daily):
    ↓ Scheduler triggers CASCADE processors
    ├─ PlayerCompositeFactorsProcessor
    │    ↓ checks all 4 upstreams
    │    ↓ processes if all production-ready
    │
    └─ MLFeatureStoreProcessor
         ↓ checks all 5 upstreams
         ↓ processes if all production-ready
```

---

## Common Questions

### Q: How do I add a new processor to Phase 3?

**A:** Update 3 places:
1. Import the processor class
2. Add to `ANALYTICS_TRIGGERS` dict
3. Add to manual endpoint `processor_map`

See: `docs/guides/07-adding-processors-to-pubsub-registry.md`

### Q: Why don't some processors trigger automatically?

**A:** CASCADE processors (PlayerCompositeFactors, MLFeatureStore) check multiple dependencies and are scheduled to run at specific times (11 PM, 11:30 PM) to ensure all upstreams are ready.

### Q: Can I trigger a processor manually?

**A:** Yes! Use the `/process-date-range` (Phase 3) or `/process-date` (Phase 4) endpoints.

### Q: What happens if a Pub/Sub message fails?

**A:**
- Pub/Sub automatically retries up to 5 times
- After 5 failures, message goes to Dead Letter Queue
- Email alert sent for investigation

### Q: How do I see which processors ran for a specific date?

**A:** Check Cloud Run logs:
```bash
gcloud run services logs read nba-phase3-analytics-processors \
  --region us-west2 \
  --filter "2024-11-22"
```

---

## Related Documentation

- **Adding Processors:** `docs/05-development/guides/pubsub-registry.md`
- **Deployment Status:** `docs/04-deployment/status.md`
- **Orchestrators:** `docs/01-architecture/orchestration/orchestrators.md`
- **Pub/Sub Topics:** `docs/01-architecture/orchestration/pubsub-topics.md`
- **Operations Guide:** `docs/02-operations/orchestrator-monitoring.md`

---

**Document Status:** ✅ Current as of 2025-11-23
**Last Updated:** 2025-11-23 14:10:00 PST
**Maintained By:** NBA Platform Team
