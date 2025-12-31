# Comprehensive System Handoff - 2025-12-02

**Purpose:** Enable a new session to review and verify the orchestration system, validation system, and backfill plan.

---

## System Overview

This is an NBA player points prediction pipeline with 5 phases:

```
Phase 1: Scrapers (fetch data from APIs)
    ↓ Pub/Sub: nba-phase2-raw-complete
Phase 2: Raw Processors (GCS → BigQuery)
    ↓ Pub/Sub: nba-phase3-trigger (via orchestrator)
Phase 3: Analytics Processors (aggregations, summaries)
    ↓ Pub/Sub: nba-phase4-trigger (via orchestrator)
Phase 4: Precompute Processors (ML features, caches)
    ↓ Pub/Sub: nba-phase4-precompute-complete (via orchestrator)
Phase 5: Predictions (similarity-based player point predictions)
```

---

## 1. ORCHESTRATION SYSTEM

### Cloud Functions (Event-Driven)

| Function | Trigger Topic | Purpose |
|----------|---------------|---------|
| `phase2-to-phase3-orchestrator` | `nba-phase2-raw-complete` | Waits for 21 Phase 2 processors, triggers Phase 3 |
| `phase3-to-phase4-orchestrator` | `nba-phase3-analytics-complete` | Waits for 5 Phase 3 processors, triggers Phase 4 |
| `phase4-to-phase5-orchestrator` | `nba-phase4-precompute-complete` | Waits for 5 Phase 4 processors, triggers predictions |
| `transition-monitor` | HTTP (Cloud Scheduler) | Detects stuck transitions, returns JSON status |

### Key Files

```
orchestration/cloud_functions/
├── phase2_to_phase3/main.py      # 21 processors → Phase 3
├── phase3_to_phase4/main.py      # 5 processors → Phase 4
├── phase4_to_phase5/main.py      # 5 processors → Predictions
└── transition_monitor/main.py    # Stuck detection

shared/config/
├── orchestration_config.py       # Centralized config (processor lists, timeouts)
└── pubsub_topics.py              # Topic name constants
```

### Critical Fix Applied (2025-12-02)

**Processor Name Normalization:** Processors publish class names (e.g., `BdlPlayerBoxscoresProcessor`) but config expects snake_case (e.g., `bdl_player_boxscores`). All orchestrators now include `normalize_processor_name()` function.

### Verification Commands

```bash
# List all cloud functions
gcloud functions list --project=nba-props-platform

# Test transition monitor
curl https://transition-monitor-f7p3g7f6ya-wl.a.run.app

# Check Firestore completion state
# (via Firebase Console or Firestore API)
```

---

## 2. VALIDATION SYSTEM

### Purpose

Validates that all pipeline phases have correct data for a given date range.

### Key Files

```
bin/validate_pipeline.py                    # Main entry point
shared/validation/
├── config.py                               # Phase/table configs, get_processing_mode()
├── chain_config.py                         # Chain definitions, virtual source deps
├── context/
│   ├── schedule_context.py                 # Game count, bootstrap detection
│   └── player_universe.py                  # Player sets (daily vs backfill mode)
└── validators/
    └── chain_validator.py                  # Chain validation logic
```

### Mode-Aware Validation

The system auto-detects mode based on date:
- **Daily mode** (today/future): Uses schedule + roster for player universe
- **Backfill mode** (historical): Uses gamebook for player universe

```python
from shared.validation.config import get_processing_mode
mode = get_processing_mode(game_date)  # Returns 'daily' or 'backfill'
```

### Running Validation

```bash
# Single date
python3 bin/validate_pipeline.py 2024-11-15

# Date range
python3 bin/validate_pipeline.py 2024-11-15 2024-11-20

# JSON output
python3 bin/validate_pipeline.py 2024-11-15 --format json

# Chain view (V2, default)
python3 bin/validate_pipeline.py 2024-11-15 --view chain
```

### Chain Structure

```
player_points_chain:     bdl_boxscores → gamebook → player_game_summary → ml_feature_store → predictions
team_defense_chain:      boxscores → team_defense_summary → team_defense_zone_analysis
schedule_chain:          nbac_schedule → espn_scoreboard
props_chain:             odds_api_props → bettingpros_props
```

---

## 3. BACKFILL PLAN

### Current Status

The pipeline has been backfilling historical NBA seasons. Key dates:
- **2021-10-19**: First game of 2021-22 season
- **Bootstrap period**: First 14 days of each season need special handling

### Backfill Architecture

```
backfill_jobs/
├── analytics/           # Phase 3 backfill scripts
├── precompute/          # Phase 4 backfill scripts
└── run_backfill.py      # Orchestrates backfill runs
```

### Running Backfill

```bash
# Validate date range first
python3 bin/validate_pipeline.py 2021-10-19 2021-10-25

# Run backfill for a phase
./bin/run_backfill.sh analytics 2021-10-19 2021-10-25

# Or trigger via Cloud Run
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-analytics" \
  -H "Content-Type: application/json" \
  -d '{"processor": "player_game_summary", "start_date": "2021-10-19", "end_date": "2021-10-25"}'
```

### Bootstrap Handling

First 14 days of season have incomplete historical context:
- `player_game_summary` uses rolling averages that need history
- Validation shows "Bootstrap (Days 0-13)" for these dates
- Predictions may be less accurate for bootstrap period

---

## 4. KEY CONFIGURATION

### Orchestration Config (`shared/config/orchestration_config.py`)

```python
@dataclass
class PhaseTransitionConfig:
    phase2_expected_processors: List[str]  # 21 raw processors
    phase3_expected_processors: List[str]  # 5 analytics processors
    phase4_expected_processors: List[str]  # 5 precompute processors

@dataclass
class ProcessingModeConfig:
    mode: str = 'auto'  # 'daily', 'backfill', or 'auto'
```

### Environment Variables

```bash
PROCESSING_MODE=daily|backfill      # Override auto-detection
SCHEDULE_STALENESS_OVERRIDE_HOURS=24  # When NBA.com is down
```

---

## 5. CLOUD RUN SERVICES

| Service | Purpose |
|---------|---------|
| `nba-phase1-scrapers` | Fetch data from NBA.com, ESPN, etc. |
| `nba-phase2-raw-processors` | GCS → BigQuery raw tables |
| `nba-phase3-analytics-processors` | Aggregations and summaries |
| `nba-phase4-precompute-processors` | ML features, caches |
| `prediction-coordinator` | Orchestrates prediction batch |
| `prediction-worker` | Executes individual predictions |

---

## 6. THINGS TO VERIFY

### Orchestration Health

```bash
# Check all functions are active
gcloud functions list --project=nba-props-platform

# Check transition monitor
curl https://transition-monitor-f7p3g7f6ya-wl.a.run.app | jq .

# Look for stuck transitions (age_hours > timeout_hours)
```

### Validation Coverage

```bash
# Run validation on recent dates
python3 bin/validate_pipeline.py 2024-11-20 2024-11-25

# Check for missing chains or incomplete phases
```

### Pub/Sub Topics

```bash
# List topics
gcloud pubsub topics list --project=nba-props-platform | grep nba-phase

# Check subscriptions
gcloud pubsub subscriptions list --project=nba-props-platform
```

---

## 7. KNOWN ISSUES / TODOS

### HIGH PRIORITY

1. **Roster scraper freshness** - Roster data is 45 days stale (from 2025-10-18). Affects daily predictions only, not backfill. Action: Schedule `espn_team_rosters` scraper to run daily.

### RESOLVED (2025-12-02)

- ✅ Processor name normalization in all orchestrators
- ✅ Phase 4→5 orchestrator deployed
- ✅ Transition monitor deployed
- ✅ Daily vs backfill mode detection in validation
- ✅ BQ query timeout in validation (30s)

---

## 8. DOCUMENTATION REFERENCES

| Document | Purpose |
|----------|---------|
| `docs/09-handoff/2025-12-02-ORCHESTRATION-IMPROVEMENTS-HANDOFF.md` | Detailed orchestration changes |
| `docs/09-handoff/2025-12-02-SESSION-HANDOFF-COMPREHENSIVE.md` | Original session context |
| `docs/08-projects/current/validation/VALIDATION-V2-DESIGN.md` | Validation system design |
| `docs/08-projects/current/backfill/BACKFILL-MASTER-PLAN.md` | Backfill strategy |

---

## 9. QUICK START FOR NEW SESSION

1. **Check system health:**
   ```bash
   curl https://transition-monitor-f7p3g7f6ya-wl.a.run.app | jq '.phase2_to_phase3.stuck_transitions'
   ```

2. **Run validation:**
   ```bash
   python3 bin/validate_pipeline.py today
   ```

3. **Review recent commits:**
   ```bash
   git log --oneline -10
   ```

4. **Read key config:**
   ```bash
   cat shared/config/orchestration_config.py
   ```
