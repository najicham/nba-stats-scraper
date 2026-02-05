# System Features Reference

Detailed documentation for major system features. For quick reference, see CLAUDE.md.

---

## Table of Contents

1. [Heartbeat System](#heartbeat-system)
2. [Evening Analytics Processing](#evening-analytics-processing)
3. [Early Prediction Timing](#early-prediction-timing)
4. [Model Attribution Tracking](#model-attribution-tracking)
5. [Enhanced Notifications](#enhanced-notifications)
6. [Phase 6 - Subset Exporters](#phase-6---subset-exporters)
7. [Dynamic Subset System](#dynamic-subset-system)
8. [Deep Health Checks & Smoke Tests](#deep-health-checks--smoke-tests)

---

## Heartbeat System

**Purpose:** Processors emit periodic heartbeats to Firestore to track health and progress in the unified dashboard.

**Implementation:** `shared/monitoring/processor_heartbeat.py`

### How It Works

1. **Each processor has ONE Firestore document** identified by `processor_name`
2. **Heartbeats update this single document** with current status, progress, timestamp
3. **Dashboard queries Firestore** to show health score and recent activity

**Document structure:**
```python
{
    "processor_name": "PlayerGameSummaryProcessor",
    "status": "running",  # or "completed", "failed"
    "last_heartbeat": timestamp,
    "progress": {"current": 50, "total": 100},
    "data_date": "2026-02-01",
    "run_id": "abc123"
}
```

### Critical Design: One Document Per Processor

**Correct implementation:**
```python
@property
def doc_id(self) -> str:
    return self.processor_name  # ONE document per processor
```

**Anti-pattern (WRONG):**
```python
def doc_id(self) -> str:
    return f"{self.processor_name}_{self.data_date}_{self.run_id}"  # Creates unbounded growth!
```

### Cleanup Script

Run `bin/cleanup-heartbeat-docs.py` if:
- Dashboard health score is unexpectedly low (<50/100)
- Firestore collection has >100 documents (should be ~30)

```bash
# Preview
python bin/cleanup-heartbeat-docs.py --dry-run

# Execute
python bin/cleanup-heartbeat-docs.py
```

### Verification

```bash
# Check dashboard health score (should be 70+/100)
curl https://unified-dashboard-f7p3g7f6ya-wl.a.run.app/api/services/health
```

**References:** Session 61 handoff, `shared/monitoring/processor_heartbeat.py`

---

## Evening Analytics Processing

**Purpose:** Process completed games same-night instead of waiting until 6 AM next day.

**Added:** Session 73

### Evening Schedulers

| Job | Schedule (ET) | Purpose |
|-----|---------------|---------|
| `evening-analytics-6pm-et` | 6 PM Sat/Sun | Weekend matinees |
| `evening-analytics-10pm-et` | 10 PM Daily | 7 PM games |
| `evening-analytics-1am-et` | 1 AM Daily | West Coast games |
| `morning-analytics-catchup-9am-et` | 9 AM Daily | Safety net |

### Boxscore Fallback

`PlayerGameSummaryProcessor` normally requires `nbac_gamebook_player_stats` (from PDF parsing, available next morning). For evening processing, it falls back to `nbac_player_boxscores` (scraped live during games).

**Flow:**
```
Check nbac_gamebook_player_stats → Has data? → Use gamebook (gold)
                                      ↓ No
Check nbac_player_boxscores (Final) → Has data? → Use boxscores (silver)
                                      ↓ No
                                Skip processing
```

**Configuration:** `USE_NBAC_BOXSCORES_FALLBACK = True` in `player_game_summary_processor.py`

**Verify source used:**
```sql
SELECT game_date,
  COUNTIF(primary_source_used = 'nbac_boxscores') as from_boxscores,
  COUNTIF(primary_source_used = 'nbac_gamebook') as from_gamebook
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date ORDER BY game_date DESC
```

**References:** Session 73 handoff, `docs/08-projects/current/evening-analytics-processing/`

---

## Early Prediction Timing

**Purpose:** Generate predictions earlier (2:30 AM ET) using REAL_LINES_ONLY mode, instead of waiting until 7 AM.

**Added:** Session 74

### Background

Vegas lines are available at ~2:00 AM ET (from BettingPros), but predictions were running at 7:00 AM. This 5-hour delay meant predictions might miss optimal timing for user consumption.

### Prediction Schedulers

| Job | Schedule (ET) | Mode | Expected Players |
|-----|---------------|------|-----------------|
| `predictions-early` | 2:30 AM | REAL_LINES_ONLY | ~140 |
| `overnight-predictions` | 7:00 AM | ALL_PLAYERS | ~200 |
| `same-day-predictions` | 11:30 AM | ALL_PLAYERS | Catch stragglers |

### REAL_LINES_ONLY Mode

The `require_real_lines` parameter filters out players without real betting lines:

```bash
curl -X POST https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Content-Type: application/json" \
  -d '{"game_date": "TODAY", "require_real_lines": true, "force": true}'
```

**How it works:**
- Players with `line_source='ACTUAL_PROP'` are included
- Players with `line_source='NO_PROP_LINE'` are filtered out
- Results in ~140 high-quality predictions at 2:30 AM

### Verify Line Availability

```sql
-- Check lines available for today
SELECT COUNT(DISTINCT player_lookup) as players_with_lines
FROM nba_raw.bettingpros_player_points_props
WHERE game_date = CURRENT_DATE() AND points_line IS NOT NULL;
```

**References:** Session 74 handoff, `predictions/coordinator/player_loader.py`

---

## Model Attribution Tracking

**Purpose:** Track which exact model file generated which predictions for debugging, A/B testing, and compliance.

**Added:** Session 84

### Schema Fields (in `player_prop_predictions`)

| Field | Type | Example |
|-------|------|---------|
| `model_file_name` | STRING | `catboost_v9_feb_02_retrain.cbm` |
| `model_training_start_date` | DATE | `2025-11-02` |
| `model_training_end_date` | DATE | `2026-01-31` |
| `model_expected_mae` | FLOAT64 | `4.12` |
| `model_expected_hit_rate` | FLOAT64 | `74.6` |
| `model_trained_at` | TIMESTAMP | `2026-02-02T10:15:00Z` |

### Verification

```bash
./bin/verify-model-attribution.sh --game-date YYYY-MM-DD
```

### Query Performance by Model

```sql
SELECT model_file_name, COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND model_file_name IS NOT NULL
  AND ABS(predicted_points - line_value) >= 5
GROUP BY model_file_name
ORDER BY mae ASC
```

**References:** Session 84/85, `docs/08-projects/current/model-attribution-tracking/`

---

## Enhanced Notifications

**Purpose:** Daily subset picks notifications include model attribution metadata.

**Added:** Session 85

### Slack Format

```
🏀 Today's Top Picks - 2026-02-04

🟢 GREEN SIGNAL (35.5% OVER)
✅ Normal confidence - bet as usual

🤖 Model: V9 Feb 02 Retrain (MAE: 4.12, HR: 74.6%)

Top 5 Picks:
1. Player Name - OVER 25.5 pts
   Edge: 6.5 | Conf: 89%
```

**Implementation:** `shared/notifications/subset_picks_notifier.py`

**Backward Compatible:** Gracefully handles predictions without attribution (pre-Feb 4)

**References:** Session 83 Task #4, Session 85

---

## Phase 6 - Subset Exporters

**Purpose:** Export curated prediction subsets to GCS for clean public API access, keeping proprietary data private.

**Background:** Phase 6 is the final step in the six-phase data pipeline:
1. Phase 1 - Scrapers → Cloud Storage JSON
2. Phase 2 - Raw Processing → BigQuery raw tables
3. Phase 3 - Analytics → Player/team summaries
4. Phase 4 - Precompute → Performance aggregates
5. Phase 5 - Predictions → ML models (CatBoost V9)
6. **Phase 6 - Publishing → JSON exports to GCS API**

### Four Subset Exporters

| Exporter | Output | Purpose | Location |
|----------|--------|---------|----------|
| **AllSubsetsPicksExporter** | `all_subsets_combined.json` | All 9 subset picks in one file | `predictions/exporters/all_subsets_picks_exporter.py` |
| **SubsetDefinitionsExporter** | `subset_definitions.json` | Subset metadata (names, criteria, edge thresholds) | `predictions/exporters/subset_definitions_exporter.py` |
| **DailySignalsExporter** | `daily_signals.json` | Daily prediction signals (GREEN/YELLOW/RED) | `predictions/exporters/daily_signals_exporter.py` |
| **SubsetPerformanceExporter** | `subset_performance.json` | Performance metrics by subset | `predictions/exporters/subset_performance_exporter.py` |

### Data Privacy

**Excluded from exports:**
- Proprietary features (usage_rate, rest_impact, matchup_advantage)
- Model training data
- Internal system metadata
- Raw scraper data

**Included in exports:**
- Player name, team
- Game info (opponent, home/away, date, time)
- Prop market (line_value, recommendation)
- Edge and confidence scores
- Subset classification
- Model attribution (which model generated prediction)

### AllSubsetsPicksExporter - Combined File Approach

**File:** `all_subsets_combined.json`

**Structure:**
```json
{
  "generated_at": "2026-02-02T14:30:00Z",
  "game_date": "2026-02-02",
  "system_id": "catboost_v9",
  "subsets": [
    {
      "subset_id": "high_edge",
      "subset_name": "High Edge (5+)",
      "criteria": "edge >= 5.0",
      "picks": [
        {
          "player_name": "LeBron James",
          "team": "LAL",
          "opponent": "GSW",
          "home_away": "HOME",
          "game_time": "19:30",
          "prop_market": "points",
          "line_value": 25.5,
          "recommendation": "OVER",
          "edge": 6.2,
          "confidence": 87.3,
          "model_file": "catboost_v9_feb_retrain.cbm"
        }
      ]
    },
    {
      "subset_id": "medium_edge",
      "subset_name": "Medium Edge (3-5)",
      "criteria": "edge >= 3.0 AND edge < 5.0",
      "picks": [...]
    }
  ]
}
```

**Design Decision:** Single combined file instead of 9 separate files
- **Pros:** Atomic consistency, simpler API, fewer HTTP requests
- **Cons:** Larger file size (~200-500 KB vs 9 × 20-60 KB)
- **Chosen:** Combined approach for simplicity and consistency

### Deployment

**Trigger:** Phase 5 completion event via Pub/Sub

**GCS Bucket:** `gs://nba-props-api-exports/`

**Paths:**
```
/subsets/all_subsets_combined.json
/subsets/subset_definitions.json
/daily/daily_signals.json
/performance/subset_performance.json
```

**Access:** Public read, CORS enabled for web access

### Verification Query

```sql
SELECT game_date, COUNT(*) as total_picks
FROM `nba_predictions.player_prop_predictions`
WHERE game_date >= CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND ABS(predicted_points - line_value) >= 3.0  -- Medium+ edge
GROUP BY game_date
```

**Implementation:** Sessions 87-91, Opus architectural review in Session 91

---

## Dynamic Subset System

**Purpose:** Classify predictions into 9 strategic subsets based on edge, confidence, market type, and game context for signal-aware betting strategies.

**Background:** Analysis showed 73% of predictions have edge < 3 and lose money. Subset system enables filtering to profitable picks only.

### 9 Subsets Defined

| Subset ID | Criteria | Hit Rate | ROI | Typical Count |
|-----------|----------|----------|-----|---------------|
| **high_edge** | edge >= 5.0 | 79.0% | +50.9% | 15-25 picks/day |
| **medium_edge** | edge >= 3.0 AND edge < 5.0 | 65.0% | +24.0% | 40-60 picks/day |
| **high_confidence** | confidence >= 85% | 68.5% | +28.3% | 30-50 picks/day |
| **points_specialists** | prop_market = 'points' AND edge >= 3 | 66.2% | +26.1% | 20-35 picks/day |
| **assists_specialists** | prop_market = 'assists' AND edge >= 3 | 64.8% | +23.7% | 10-20 picks/day |
| **rebounds_specialists** | prop_market = 'rebounds' AND edge >= 3 | 63.5% | +21.9% | 10-20 picks/day |
| **home_advantage** | home_away = 'HOME' AND edge >= 3 | 65.8% | +25.4% | 25-40 picks/day |
| **primetime_games** | game_time >= 19:00 AND edge >= 3 | 66.9% | +27.2% | 15-30 picks/day |
| **all_picks** | No filter (reference baseline) | 54.7% | +4.5% | 150-250 picks/day |

### Signal-Aware Filtering

**Daily Signal System:** Predicts overall prediction quality for the day

| Signal | Meaning | Action | Expected Hit Rate |
|--------|---------|--------|-------------------|
| **GREEN** | High confidence day (>15 high-edge picks, >60% overall edge) | Bet medium+ edge picks | 82% on GREEN days |
| **YELLOW** | Mixed day (5-15 high-edge picks) | Bet high-edge only | 68% on YELLOW days |
| **RED** | Low confidence day (<5 high-edge picks) | Skip or bet high-edge only | 51% on RED days |

**Strategy:** On GREEN days, bet `medium_edge` + `high_edge`. On RED days, skip or bet `high_edge` only.

### Implementation

**Subset Classification:**
```python
def classify_subset(prediction: dict) -> List[str]:
    """Classify prediction into applicable subsets."""
    subsets = []

    edge = prediction.get('edge', 0)
    confidence = prediction.get('confidence', 0)
    prop_market = prediction.get('prop_market')
    home_away = prediction.get('home_away')
    game_time = prediction.get('game_time')

    # Edge-based
    if edge >= 5.0:
        subsets.append('high_edge')
    if 3.0 <= edge < 5.0:
        subsets.append('medium_edge')

    # Confidence-based
    if confidence >= 85.0:
        subsets.append('high_confidence')

    # Market specialists (with edge filter)
    if edge >= 3.0:
        if prop_market == 'points':
            subsets.append('points_specialists')
        elif prop_market == 'assists':
            subsets.append('assists_specialists')
        elif prop_market == 'rebounds':
            subsets.append('rebounds_specialists')

    # Context-based (with edge filter)
    if edge >= 3.0:
        if home_away == 'HOME':
            subsets.append('home_advantage')
        if game_time and game_time >= '19:00':
            subsets.append('primetime_games')

    # Reference baseline
    subsets.append('all_picks')

    return subsets
```

**Daily Signal Calculation:**
```sql
SELECT
  game_date,
  COUNT(*) as total_picks,
  COUNTIF(edge >= 5.0) as high_edge_picks,
  COUNTIF(edge >= 3.0) as medium_plus_edge_picks,
  ROUND(AVG(edge), 2) as avg_edge,
  ROUND(100.0 * COUNTIF(edge >= 5.0) / COUNT(*), 1) as pct_high_edge,
  CASE
    WHEN COUNTIF(edge >= 5.0) > 15 AND AVG(edge) > 3.5 THEN 'GREEN'
    WHEN COUNTIF(edge >= 5.0) BETWEEN 5 AND 15 THEN 'YELLOW'
    ELSE 'RED'
  END as daily_signal
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
GROUP BY game_date
```

### Performance Validation

**Query to verify subset performance:**
```sql
SELECT
  subset_id,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(100.0 * (SUM(IF(prediction_correct, 1, 0)) - SUM(IF(NOT prediction_correct, 1.1, 0))) / COUNT(*), 1) as roi
FROM nba_predictions.prediction_accuracy,
  UNNEST(subsets) as subset_id
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY subset_id
ORDER BY roi DESC
```

### Key Learnings

1. **Edge >= 3 threshold is critical:** 73% of predictions below this lose money
2. **GREEN day strategy works:** 82% hit rate vs 54.7% baseline
3. **Combined file export:** Simpler than 9 separate files
4. **Subset overlap is intentional:** One pick can belong to multiple subsets (e.g., high_edge + points_specialists)

**Implementation:** Sessions 71-91, Subset definitions in `predictions/exporters/subset_definitions.json`

**References:**
- 2026-01.md summary lines 40-41, 74-76
- Phase 6 architecture review (Session 91)
---

## Deep Health Checks & Smoke Tests

**Implemented:** Session 129 (Feb 5, 2026)
**Purpose:** Prevent silent service failures through defense-in-depth validation

### Problem Statement

**What we're preventing:**
- Services that start successfully but crash on every request
- Missing module imports not caught until runtime
- Broken database connectivity discovered too late
- 39-hour outage (Feb 4-5, 2026) from missing `predictions/` module

**Root cause:** Shallow health checks only verify "is the process running?" not "can it do its job?"

### Solution: Defense-in-Depth

Five layers of validation from build to recovery:

```
Layer 1: Build       - Dockerfile validation (planned)
Layer 2: Test        - Dependency verification (existing)
Layer 3: Deploy      - Smoke tests (NEW)
Layer 4: Monitor     - Deep health checks (NEW)
Layer 5: Recover     - Auto-backfill (planned)
```

### Layer 3: Deployment Smoke Tests

**Location:** `bin/deploy-service.sh` (Step 6.5/8)

**What it does:**
- Runs immediately after Cloud Run deployment
- Tests actual service functionality (not just availability)
- **Fails deployment** if tests don't pass
- Provides rollback instructions on failure

**Example (Grading Service):**
```bash
# Test 1: Deep health check
DEEP_HEALTH=$(curl -s "$SERVICE_URL/health/deep")
if [ "$(echo $DEEP_HEALTH | jq -r '.status')" != "healthy" ]; then
    echo "❌ CRITICAL: Service cannot function!"
    exit 1  # Fail deployment
fi

# Test 2: Basic response
HEALTH_STATUS=$(curl -s "$SERVICE_URL/health" -w '%{http_code}')
if [ "$HEALTH_STATUS" != "200" ]; then
    echo "❌ CRITICAL: Health check failed!"
    exit 1
fi
```

**Impact:** Would have caught the Feb 4-5 grading service failure immediately.

### Layer 4: Deep Health Checks

**Location:** Service code (e.g., `data_processors/grading/nba/main_nba_grading_service.py`)

**Endpoint:** `/health/deep`

**What it validates:**
1. ✅ Critical module imports (catches missing modules)
2. ✅ BigQuery connectivity
3. ✅ Firestore connectivity
4. ✅ All required dependencies

**Response format:**
```json
// Healthy
{
  "status": "healthy",
  "checks": {
    "imports": {"status": "ok"},
    "bigquery": {"status": "ok"},
    "firestore": {"status": "ok"}
  }
}

// Unhealthy (returns 503)
{
  "status": "unhealthy",
  "checks": {
    "imports": {
      "status": "failed",
      "error": "No module named 'predictions'"
    }
  }
}
```

**Implementation:**
```python
@app.route('/health/deep', methods=['GET'])
def health_check_deep():
    checks = {}
    all_healthy = True

    # Check critical imports
    try:
        from predictions.shared.distributed_lock import DistributedLock
        checks['imports'] = {'status': 'ok'}
    except ImportError as e:
        checks['imports'] = {'status': 'failed', 'error': str(e)}
        all_healthy = False

    # Check BigQuery
    try:
        client = get_bigquery_client()
        client.query("SELECT 1").result()
        checks['bigquery'] = {'status': 'ok'}
    except Exception as e:
        checks['bigquery'] = {'status': 'failed', 'error': str(e)}
        all_healthy = False

    status_code = 200 if all_healthy else 503
    return jsonify({
        "status": "healthy" if all_healthy else "unhealthy",
        "checks": checks
    }), status_code
```

### Usage

**During deployment:**
```bash
./bin/deploy-service.sh nba-grading-service
# Smoke tests run automatically at step [6.5/8]
# Deployment fails if tests don't pass
```

**Manual testing:**
```bash
# Test deep health check
curl https://SERVICE-URL/health/deep | jq

# Expected (healthy)
{"status": "healthy", "checks": {...}}

# Expected (broken)
{"status": "unhealthy", "checks": {"imports": {"status": "failed", ...}}}
```

**Continuous monitoring:**
```bash
# Add uptime check for /health/deep
gcloud monitoring uptime-checks create https \
    --display-name="grading-deep-health" \
    --monitored-resource="SERVICE-URL/health/deep" \
    --check-interval=60s
```

### Services Implemented

| Service | Deep Health Check | Smoke Tests | Status |
|---------|-------------------|-------------|--------|
| nba-grading-service | ✅ Implemented | ✅ Implemented | Session 129 |
| prediction-worker | ⏳ Planned | ✅ Basic | Session 129 |
| Others | ⏳ Planned | ✅ Basic | Session 129 |

### Key Metrics

**Before (Feb 4-5, 2026):**
- Time to detect service failure: 39 hours
- Predictions affected: 48 (all Feb 4 games)
- Detection method: Manual investigation

**After (Feb 5+, 2026):**
- Time to detect service failure: < 1 minute (deployment smoke tests)
- Predictions affected: 0 (deployment fails before going live)
- Detection method: Automated smoke tests + deep health checks

### Future Enhancements

**Layer 1: Dockerfile Validation**
- Validate all Python imports have corresponding COPY commands
- Prevent deployments with missing modules

**Layer 5: Auto-Recovery**
- Automatic backfill for failed operations
- Self-healing for transient failures

**Full documentation:** `docs/05-development/health-checks-and-smoke-tests.md`

**Implementation:** Session 129
**Prevents:** Silent service failures, 39-hour outages, missing module imports
