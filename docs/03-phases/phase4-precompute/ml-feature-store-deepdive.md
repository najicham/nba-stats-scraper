# Phase 4: ML Feature Store V2 Deep-Dive

**File:** `docs/processors/08-phase4-ml-feature-store-deepdive.md`
**Created:** 2025-11-15 16:30 PST
**Last Updated:** 2025-11-25
**Purpose:** Deep-dive on ML Feature Store V2 orchestration - the most complex processor in the system
**Status:** ✅ Deployed & operational
**Audience:** Engineers implementing and operating the ML Feature Store V2 processor

---

## Executive Summary

**ML Feature Store V2** is the most complex data processor in the NBA Props Platform, serving as the critical bridge between Phase 4 precompute aggregations and Phase 5 ML predictions. This document provides a comprehensive deep-dive into its orchestration challenges, implementation strategies, and operational procedures.

**Why This Processor is Special:**
- ✅ **4-way dependency**: Waits for ALL 4 upstream Phase 4 processors to complete
- ✅ **Cross-dataset writes**: Writes to `nba_predictions` dataset (not `nba_precompute`)
- ✅ **Phase 3 fallback**: Gracefully degrades when Phase 4 data unavailable
- ✅ **Quality scoring**: 0-100 quality score with granular component tracking
- ✅ **Critical path blocker**: Phase 5 predictions cannot run until this completes
- ✅ **Complex data lineage**: Combines 4 upstream processors + Phase 3 fallback

**Processor Overview:**

| Attribute | Details |
|-----------|---------|
| **Processor** | `ml_feature_store_v2` |
| **Cloud Run Service** | `phase4-ml-feature-store-v2` |
| **Target Dataset** | `nba_predictions` (cross-dataset write!) |
| **Target Table** | `ml_feature_store_v2` |
| **Dependencies** | ALL 4 Phase 4 processors (team_defense_zone_analysis, player_shot_zone_analysis, player_composite_factors, player_daily_cache) |
| **Phase 3 Fallback** | Uses Phase 3 analytics tables when Phase 4 data unavailable |
| **Execution Window** | 11:25 PM - 11:50 PM EST (25 minutes) |
| **Success Criteria** | 200+ player rows, quality_score ≥ 75, all 4 dependencies present |
| **Criticality** | **P0** - Blocks entire Phase 5 prediction pipeline |

**Read this guide if you need to:**
- Understand why ML Feature Store orchestration is uniquely complex
- Implement the 4-way dependency orchestration
- Configure Phase 3 fallback behavior
- Monitor quality scores and data completeness
- Troubleshoot ML Feature Store failures
- Optimize performance (currently 25 minutes, target 15 minutes)

---

## Table of Contents

1. [Why ML Feature Store Orchestration is Complex](#why-ml-feature-store-orchestration-is-complex)
2. [Four-Way Dependency Orchestration](#four-way-dependency-orchestration)
3. [Phase 3 Fallback Orchestration](#phase-3-fallback-orchestration)
4. [Quality Score Monitoring](#quality-score-monitoring)
5. [Cross-Dataset Write Orchestration](#cross-dataset-write-orchestration)
6. [Integration with Phase 5](#integration-with-phase-5)
7. [Data Flow Diagrams](#data-flow-diagrams)
8. [Operational Procedures](#operational-procedures)
9. [Incident Response Playbook](#incident-response-playbook)
10. [Performance Optimization](#performance-optimization)

---

## Why ML Feature Store Orchestration is Complex

ML Feature Store V2 presents **6 unique complexity factors** not found in other processors:

### 1. Four-Way Dependency

**Challenge:** ML Feature Store must wait for ALL 4 upstream processors to complete before starting.

**Why it's complex:**
- Standard Pub/Sub triggers on single events (1:1 relationship)
- ML Feature Store needs 4:1 relationship (wait for ALL 4)
- Partial data is worse than no data (predictions will be incorrect)
- Need state tracking across 4 independent Cloud Run executions

**Example failure scenario:**
```
11:00 PM - P1 (team_defense_zone_analysis) completes ✅
11:05 PM - P2 (player_shot_zone_analysis) completes ✅
11:10 PM - P3 (player_composite_factors) completes ✅
11:15 PM - P4 (player_daily_cache) FAILS ❌
11:25 PM - ML Feature Store triggers anyway (only saw 3 completions)
Result: Missing player_daily_cache data → incorrect predictions → BAD
```

**Solution:** See [Four-Way Dependency Orchestration](#four-way-dependency-orchestration) section.

---

### 2. Cross-Dataset Write

**Challenge:** ML Feature Store writes to `nba_predictions` dataset, not `nba_precompute`.

**Why it's complex:**
- Different IAM permissions required
- Different dataset quotas and billing
- Data governance boundaries (predictions vs precompute)
- Cannot use same service account as other Phase 4 processors

**Example:**
```sql
-- Other Phase 4 processors write here:
INSERT INTO `nba-props-platform.nba_precompute.player_composite_factors` ...

-- ML Feature Store writes here (different dataset!):
INSERT INTO `nba-props-platform.nba_predictions.ml_feature_store_v2` ...
```

**Why this design:** Phase 5 prediction models read from `nba_predictions` dataset. ML Feature Store is the bridge between Phase 4 aggregations and Phase 5 predictions.

**Solution:** See [Cross-Dataset Write Orchestration](#cross-dataset-write-orchestration) section.

---

### 3. Phase 3 Fallback

**Challenge:** When Phase 4 data unavailable, gracefully degrade to Phase 3 analytics tables.

**Why it's complex:**
- Need dual data path logic (Phase 4 primary, Phase 3 fallback)
- Quality score must reflect data source (Phase 4 = 100, Phase 3 = 75)
- Cannot blindly fail when Phase 4 missing (show must go on)
- Need monitoring to detect when running in degraded mode

**Example scenarios:**

| Scenario | Phase 4 Available? | Phase 3 Available? | Behavior | Quality Score |
|----------|-------------------|-------------------|----------|---------------|
| **Nominal** | ✅ Yes | ✅ Yes | Use Phase 4 | 100 |
| **Degraded** | ❌ No | ✅ Yes | Use Phase 3 | 75 |
| **Critical** | ❌ No | ❌ No | FAIL | 0 |
| **Partial** | ⚠️ Some | ✅ Yes | Phase 4 where available, Phase 3 elsewhere | 80-95 |

**Solution:** See [Phase 3 Fallback Orchestration](#phase-3-fallback-orchestration) section.

---

### 4. Quality Score Tracking

**Challenge:** Track data quality with 0-100 score across 6 components.

**Why it's complex:**
- Need granular component tracking (phase4_availability, phase3_fallback_rate, data_freshness, etc.)
- Quality score affects downstream Phase 5 model confidence
- Need historical trending (quality degrading over time?)
- Alert thresholds vary by component

**Quality Score Components (each 0-100):**
1. **phase4_availability** (40 points max) - % of players with Phase 4 data
2. **phase3_fallback_rate** (20 points max) - Penalty for Phase 3 fallback usage
3. **data_freshness** (15 points max) - How recent is the data?
4. **dependency_completeness** (15 points max) - All 4 dependencies present?
5. **row_completeness** (5 points max) - Expected # of players (200+)?
6. **null_field_rate** (5 points max) - % of NULL fields

**Example:**
```sql
-- Quality score breakdown for analysis_date = '2024-12-15'
phase4_availability: 95/100 (380 of 400 players have Phase 4 data)
phase3_fallback_rate: 18/20 (only 5% using Phase 3 fallback)
data_freshness: 15/15 (data from today)
dependency_completeness: 15/15 (all 4 dependencies present)
row_completeness: 5/5 (400 players, expected 200+)
null_field_rate: 4/5 (2% NULL rate, threshold <5%)
---
TOTAL QUALITY SCORE: 92/100 ✅ PASS (threshold: 75)
```

**Solution:** See [Quality Score Monitoring](#quality-score-monitoring) section.

---

### 5. Critical Path Blocker

**Challenge:** Phase 5 predictions CANNOT run until ML Feature Store completes.

**Why it's complex:**
- Single point of failure for entire prediction pipeline
- Delays cascade to Phase 5 (predictions) and Phase 6 (web app)
- Need aggressive SLAs (15 minute target execution time)
- P0 incidents when this processor fails

**Impact of failure:**

```
ML Feature Store fails at 11:25 PM
  ↓
Phase 5 cannot start (no features available)
  ↓
Phase 6 cannot publish (no predictions available)
  ↓
Web app shows stale predictions (from previous day)
  ↓
Users see outdated prop recommendations
  ↓
P0 INCIDENT (business impact)
```

**Solution:** See [Incident Response Playbook](#incident-response-playbook) section.

---

### 6. Complex Data Lineage

**Challenge:** Combines data from 4 Phase 4 processors + Phase 3 fallback + Phase 2 raw tables.

**Why it's complex:**
- Data lineage spans 3 phases (Phase 2 → Phase 3 → Phase 4)
- Debugging missing data requires tracing through 6+ tables
- Different data freshness across sources (Phase 4 = today, Phase 3 = yesterday)
- Need comprehensive logging of data source decisions

**Data Lineage Diagram (see [Data Flow Diagrams](#data-flow-diagrams) for visual):**

```
Phase 2 Raw Tables
  ↓
Phase 3 Analytics (player_game_summary, team_offense/defense_game_summary)
  ↓
Phase 4 Precompute (4 processors in parallel)
  ├─ team_defense_zone_analysis
  ├─ player_shot_zone_analysis
  ├─ player_composite_factors
  └─ player_daily_cache
       ↓
ML Feature Store V2 (merges all 4 + Phase 3 fallback)
       ↓
nba_predictions.ml_feature_store_v2
       ↓
Phase 5 Predictions (ML models)
```

**Example debug query:**
```sql
-- Trace data lineage for player_id = 203999 (Nikola Jokic) on 2024-12-15
SELECT
  'Phase 4: team_defense_zone_analysis' as source,
  COUNT(*) as rows,
  MAX(processed_at) as last_processed
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = '2024-12-15'
  AND player_id = 203999

UNION ALL

SELECT
  'Phase 4: player_shot_zone_analysis' as source,
  COUNT(*) as rows,
  MAX(processed_at) as last_processed
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = '2024-12-15'
  AND player_id = 203999

-- ... (repeat for other 2 Phase 4 processors)

UNION ALL

SELECT
  'Phase 3 Fallback: player_game_summary' as source,
  COUNT(*) as rows,
  MAX(processed_at) as last_processed
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2024-12-14' -- yesterday (Phase 3 historical)
  AND player_id = 203999

-- Result shows which data sources contributed to ML Feature Store
```

**Solution:** Comprehensive logging in processor code + lineage tracking table (see [Data Flow Diagrams](#data-flow-diagrams)).

---

## Four-Way Dependency Orchestration

**Problem:** ML Feature Store must wait for ALL 4 upstream processors to complete before starting.

**Solution:** Three implementation strategies with increasing complexity:

### Strategy 1: Cloud Function with Firestore State Tracking (Recommended for Hybrid)

**How it works:**
1. Each Phase 4 processor publishes success event to `phase4-processor-success` topic
2. Cloud Function listens to this topic
3. Function tracks completion status in Firestore document (keyed by analysis_date)
4. When all 4 processors complete, function publishes event to `phase4-ml-feature-store-trigger` topic
5. ML Feature Store Cloud Run service subscribes to this trigger topic

**Firestore document structure:**
```json
{
  "analysis_date": "2024-12-15",
  "completions": {
    "team_defense_zone_analysis": {
      "completed_at": "2024-12-15T23:05:00Z",
      "status": "success",
      "row_count": 30
    },
    "player_shot_zone_analysis": {
      "completed_at": "2024-12-15T23:10:00Z",
      "status": "success",
      "row_count": 400
    },
    "player_composite_factors": {
      "completed_at": "2024-12-15T23:15:00Z",
      "status": "success",
      "row_count": 400
    },
    "player_daily_cache": {
      "completed_at": "2024-12-15T23:20:00Z",
      "status": "success",
      "row_count": 400
    }
  },
  "all_complete": true,
  "ml_feature_store_triggered_at": "2024-12-15T23:20:05Z"
}
```

**Cloud Function implementation:**

```python
import functions_framework
from google.cloud import pubsub_v1, firestore
import json
from datetime import datetime

# Initialize clients
publisher = pubsub_v1.PublisherClient()
db = firestore.Client()

PROJECT_ID = "nba-props-platform"
TRIGGER_TOPIC = f"projects/{PROJECT_ID}/topics/phase4-ml-feature-store-trigger"

REQUIRED_PROCESSORS = [
    "team_defense_zone_analysis",
    "player_shot_zone_analysis",
    "player_composite_factors",
    "player_daily_cache"
]

@functions_framework.cloud_event
def track_phase4_completion(cloud_event):
    """
    Track Phase 4 processor completions and trigger ML Feature Store when all 4 complete.

    Triggered by: phase4-processor-success Pub/Sub topic
    Publishes to: phase4-ml-feature-store-trigger Pub/Sub topic (when all 4 complete)
    """
    # Parse Pub/Sub message
    import base64
    message_data = json.loads(base64.b64decode(cloud_event.data["message"]["data"]).decode())

    processor = message_data["processor"]
    analysis_date = message_data["analysis_date"]
    status = message_data["status"]
    row_count = message_data.get("row_count", 0)

    print(f"Received completion for {processor} on {analysis_date}: {status} ({row_count} rows)")

    # Get or create Firestore document
    doc_ref = db.collection("phase4_orchestration").document(analysis_date)
    doc = doc_ref.get()

    if doc.exists:
        data = doc.to_dict()
    else:
        data = {
            "analysis_date": analysis_date,
            "completions": {},
            "all_complete": False
        }

    # Update completion status
    data["completions"][processor] = {
        "completed_at": datetime.utcnow().isoformat() + "Z",
        "status": status,
        "row_count": row_count
    }

    # Check if all 4 processors complete
    completed_processors = [p for p in REQUIRED_PROCESSORS if p in data["completions"]]
    all_complete = len(completed_processors) == len(REQUIRED_PROCESSORS)

    data["all_complete"] = all_complete

    # Save to Firestore
    doc_ref.set(data)

    print(f"Completion status: {len(completed_processors)}/{len(REQUIRED_PROCESSORS)}")

    # If all complete, trigger ML Feature Store
    if all_complete and "ml_feature_store_triggered_at" not in data:
        print(f"All 4 processors complete! Triggering ML Feature Store for {analysis_date}")

        # Publish trigger event
        trigger_message = {
            "processor": "ml_feature_store_v2",
            "analysis_date": analysis_date,
            "trigger_source": "four_way_dependency_complete",
            "upstream_completions": data["completions"]
        }

        future = publisher.publish(
            TRIGGER_TOPIC,
            json.dumps(trigger_message).encode("utf-8")
        )

        print(f"Published trigger message: {future.result()}")

        # Update Firestore to prevent duplicate triggers
        data["ml_feature_store_triggered_at"] = datetime.utcnow().isoformat() + "Z"
        doc_ref.set(data)
    else:
        print(f"Waiting for remaining processors: {set(REQUIRED_PROCESSORS) - set(completed_processors)}")

    return "OK"
```

**Deployment:**

```bash
# 1. Deploy Cloud Function
gcloud functions deploy track-phase4-completion \
  --gen2 \
  --runtime python311 \
  --trigger-topic phase4-processor-success \
  --entry-point track_phase4_completion \
  --region us-central1 \
  --memory 256MB \
  --timeout 60s \
  --set-env-vars PROJECT_ID=nba-props-platform

# 2. Create ML Feature Store trigger topic
gcloud pubsub topics create phase4-ml-feature-store-trigger

# 3. Create ML Feature Store Cloud Run subscription
gcloud run services update phase4-ml-feature-store-v2 \
  --update-env-vars PUBSUB_TOPIC=phase4-ml-feature-store-trigger
```

**Pros:**
- ✅ Real-time triggering (ML Feature Store starts immediately when 4th processor completes)
- ✅ State persistence (Firestore document shows completion history)
- ✅ Idempotent (prevents duplicate triggers via `ml_feature_store_triggered_at` flag)
- ✅ Debuggable (Firestore document shows which processors completed, when, row counts)

**Cons:**
- ❌ Additional infrastructure (Cloud Function + Firestore)
- ❌ More complex debugging (need to check Firestore document state)
- ❌ Firestore quotas (writes per second, document size)

**When to use:** Hybrid orchestration (event-driven Phase 4 → ML Feature Store).

---

### Strategy 2: Cloud Workflows (Recommended for Production)

**How it works:**
1. Cloud Scheduler triggers Cloud Workflow at 11:00 PM
2. Workflow executes Phase 4 processors in sequence with parallelization
3. Parallel Set 1: team_defense_zone_analysis + player_shot_zone_analysis (concurrent)
4. Parallel Set 2: player_composite_factors + player_daily_cache (concurrent, waits for Set 1)
5. ML Feature Store: Executes after Set 2 completes (implicit 4-way dependency)

**Cloud Workflow YAML:**

```yaml
# phase4-orchestration.yaml
main:
  params: [input]
  steps:
    # Extract analysis_date from input or default to yesterday
    - init:
        assign:
          - analysis_date: ${default(map.get(input, "analysis_date"), text.substring(time.format(sys.now()), 0, 10))}
          - project_id: "nba-props-platform"

    # Parallel Set 1: team_defense_zone_analysis + player_shot_zone_analysis
    - parallel_set_1:
        parallel:
          branches:
            - branch_team_defense:
                steps:
                  - call_team_defense:
                      call: http.post
                      args:
                        url: https://phase4-team-defense-zone-analysis-XXXXX.run.app/process
                        auth:
                          type: OIDC
                        body:
                          analysis_date: ${analysis_date}
                      result: team_defense_result
                  - log_team_defense:
                      call: sys.log
                      args:
                        text: ${"team_defense_zone_analysis completed: " + string(team_defense_result.body.row_count) + " rows"}

            - branch_player_shot:
                steps:
                  - call_player_shot:
                      call: http.post
                      args:
                        url: https://phase4-player-shot-zone-analysis-XXXXX.run.app/process
                        auth:
                          type: OIDC
                        body:
                          analysis_date: ${analysis_date}
                      result: player_shot_result
                  - log_player_shot:
                      call: sys.log
                      args:
                        text: ${"player_shot_zone_analysis completed: " + string(player_shot_result.body.row_count) + " rows"}

    # Parallel Set 2: player_composite_factors + player_daily_cache
    # (Implicitly waits for Set 1 to complete)
    - parallel_set_2:
        parallel:
          branches:
            - branch_composite:
                steps:
                  - call_composite:
                      call: http.post
                      args:
                        url: https://phase4-player-composite-factors-XXXXX.run.app/process
                        auth:
                          type: OIDC
                        body:
                          analysis_date: ${analysis_date}
                      result: composite_result
                  - log_composite:
                      call: sys.log
                      args:
                        text: ${"player_composite_factors completed: " + string(composite_result.body.row_count) + " rows"}

            - branch_daily_cache:
                steps:
                  - call_daily_cache:
                      call: http.post
                      args:
                        url: https://phase4-player-daily-cache-XXXXX.run.app/process
                        auth:
                          type: OIDC
                        body:
                          analysis_date: ${analysis_date}
                      result: daily_cache_result
                  - log_daily_cache:
                      call: sys.log
                      args:
                        text: ${"player_daily_cache completed: " + string(daily_cache_result.body.row_count) + " rows"}

    # ML Feature Store V2 (waits for Set 2, which waited for Set 1)
    # (Implicit 4-way dependency: all 4 processors completed)
    - ml_feature_store:
        call: http.post
        args:
          url: https://phase4-ml-feature-store-v2-XXXXX.run.app/process
          auth:
            type: OIDC
          body:
            analysis_date: ${analysis_date}
            upstream_completions:
              team_defense_zone_analysis: ${team_defense_result.body.row_count}
              player_shot_zone_analysis: ${player_shot_result.body.row_count}
              player_composite_factors: ${composite_result.body.row_count}
              player_daily_cache: ${daily_cache_result.body.row_count}
        result: ml_result

    # Log final result
    - return_result:
        return:
          analysis_date: ${analysis_date}
          team_defense_rows: ${team_defense_result.body.row_count}
          player_shot_rows: ${player_shot_result.body.row_count}
          composite_rows: ${composite_result.body.row_count}
          daily_cache_rows: ${daily_cache_result.body.row_count}
          ml_feature_store_rows: ${ml_result.body.row_count}
          quality_score: ${ml_result.body.quality_score}
          status: "success"
```

**Deployment:**

```bash
# 1. Deploy workflow
gcloud workflows deploy phase4-orchestration \
  --source phase4-orchestration.yaml \
  --location us-central1

# 2. Create Cloud Scheduler job to trigger workflow
gcloud scheduler jobs create http phase4-workflow-trigger \
  --schedule "0 23 * * *" \
  --time-zone "America/New_York" \
  --uri "https://workflowexecutions.googleapis.com/v1/projects/nba-props-platform/locations/us-central1/workflows/phase4-orchestration/executions" \
  --http-method POST \
  --oauth-service-account-email phase4-scheduler@nba-props-platform.iam.gserviceaccount.com \
  --message-body '{"argument": "{\"analysis_date\": \"2024-12-15\"}"}'

# 3. Grant Cloud Scheduler permission to execute workflow
gcloud workflows add-iam-policy-binding phase4-orchestration \
  --location us-central1 \
  --member serviceAccount:phase4-scheduler@nba-props-platform.iam.gserviceaccount.com \
  --role roles/workflows.invoker
```

**Pros:**
- ✅ Implicit 4-way dependency (workflow execution order guarantees all 4 complete)
- ✅ Built-in retry/error handling
- ✅ Visual execution history in Cloud Console
- ✅ No additional state tracking infrastructure needed
- ✅ Timeout enforcement (25 minute max for critical path)

**Cons:**
- ❌ Time-based only (cannot react to early completions)
- ❌ Harder to debug mid-execution (need to check workflow execution logs)
- ❌ Less flexible (changing execution order requires YAML redeployment)

**When to use:** Production orchestration with deterministic execution order.

---

### Strategy 3: Time-Based with Validation (Simplest)

**How it works:**
1. Cloud Scheduler triggers ML Feature Store at fixed time (11:25 PM)
2. ML Feature Store processor validates all 4 dependencies exist before processing
3. If any dependency missing, processor fails with clear error message
4. Retry mechanism attempts up to 3 times with 5-minute delays

**ML Feature Store processor validation logic:**

```python
def validate_dependencies(analysis_date: str) -> dict:
    """
    Validate all 4 Phase 4 dependencies exist for analysis_date.

    Returns:
        dict with validation results:
        {
            "all_present": bool,
            "missing": list of missing processor names,
            "row_counts": dict of processor -> row_count
        }
    """
    from google.cloud import bigquery

    client = bigquery.Client()

    dependencies = [
        "team_defense_zone_analysis",
        "player_shot_zone_analysis",
        "player_composite_factors",
        "player_daily_cache"
    ]

    validation_results = {
        "all_present": True,
        "missing": [],
        "row_counts": {}
    }

    for processor in dependencies:
        query = f"""
        SELECT COUNT(*) as row_count
        FROM `nba-props-platform.nba_precompute.{processor}`
        WHERE analysis_date = '{analysis_date}'
        """

        result = client.query(query).result()
        row_count = list(result)[0].row_count

        validation_results["row_counts"][processor] = row_count

        if row_count == 0:
            validation_results["all_present"] = False
            validation_results["missing"].append(processor)
            print(f"❌ Dependency missing: {processor} (0 rows for {analysis_date})")
        else:
            print(f"✅ Dependency present: {processor} ({row_count} rows for {analysis_date})")

    return validation_results

# In main processor logic:
def process_ml_feature_store(analysis_date: str):
    # Validate dependencies first
    validation = validate_dependencies(analysis_date)

    if not validation["all_present"]:
        missing_str = ", ".join(validation["missing"])
        raise ValueError(
            f"Cannot process ML Feature Store: missing dependencies [{missing_str}] "
            f"for analysis_date={analysis_date}. "
            f"Row counts: {validation['row_counts']}"
        )

    print(f"✅ All 4 dependencies present: {validation['row_counts']}")

    # Proceed with processing...
```

**Cloud Scheduler job:**

```bash
# Trigger ML Feature Store at 11:25 PM (assumes 25 min buffer for upstream processors)
gcloud scheduler jobs create http phase4-ml-feature-store-time-based \
  --schedule "25 23 * * *" \
  --time-zone "America/New_York" \
  --uri "https://phase4-ml-feature-store-v2-XXXXX.run.app/process" \
  --http-method POST \
  --message-body '{"analysis_date": "2024-12-15"}' \
  --oidc-service-account-email phase4-scheduler@nba-props-platform.iam.gserviceaccount.com

# Configure retry policy (3 attempts, 5 min delay)
gcloud scheduler jobs update http phase4-ml-feature-store-time-based \
  --retry-count 3 \
  --retry-duration 5m
```

**Pros:**
- ✅ Simplest implementation (no orchestration infrastructure)
- ✅ Easy to debug (just check BigQuery for dependency data)
- ✅ Retry mechanism handles transient failures

**Cons:**
- ❌ Fixed timing (cannot adapt to early/late completions)
- ❌ Wasteful retries (if dependency truly failed, retries won't help)
- ❌ Harder to distinguish between "not ready yet" vs "failed"

**When to use:** Early prototyping or simple deployments.

---

### Recommendation

**Start with Strategy 3 (Time-Based), evolve to Strategy 2 (Cloud Workflows) in production.**

**Rationale:**
1. **Week 1-2:** Deploy with Strategy 3 to validate processor logic
2. **Week 3-4:** Monitor timing consistency (do upstream processors always finish by 11:25 PM?)
3. **Month 2:** If timing reliable, stay with Strategy 3. If timing variable, upgrade to Strategy 2.
4. **Month 3+:** For production scale, migrate to Strategy 2 (Cloud Workflows) for deterministic execution.

**Do NOT use Strategy 1 (Cloud Function)** unless you need real-time triggering (e.g., intraday ML Feature Store updates).

---

## Phase 3 Fallback Orchestration

**Problem:** When Phase 4 data unavailable (processor failures, early season), ML Feature Store must gracefully degrade to Phase 3 analytics tables.

**Solution:** Dual data path with quality score adjustments.

### Fallback Decision Logic

```python
def get_data_source(analysis_date: str, player_id: int, metric: str) -> dict:
    """
    Determine data source for metric: Phase 4 (preferred) or Phase 3 (fallback).

    Returns:
        {
            "source": "phase4" | "phase3",
            "value": float,
            "quality_penalty": int (0-20 points)
        }
    """
    from google.cloud import bigquery

    client = bigquery.Client()

    # Try Phase 4 first
    phase4_query = f"""
    SELECT {metric}
    FROM `nba-props-platform.nba_precompute.player_composite_factors`
    WHERE analysis_date = '{analysis_date}'
      AND player_id = {player_id}
    """

    phase4_result = client.query(phase4_query).result()

    for row in phase4_result:
        if row[metric] is not None:
            return {
                "source": "phase4",
                "value": row[metric],
                "quality_penalty": 0  # No penalty for Phase 4 data
            }

    # Fallback to Phase 3
    # Note: Phase 3 uses game_date (historical), not analysis_date (forward-looking)
    # Use previous day's game_date
    from datetime import datetime, timedelta
    game_date = (datetime.fromisoformat(analysis_date) - timedelta(days=1)).date()

    phase3_query = f"""
    SELECT {metric}
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date = '{game_date}'
      AND player_id = {player_id}
    ORDER BY processed_at DESC
    LIMIT 1
    """

    phase3_result = client.query(phase3_query).result()

    for row in phase3_result:
        if row[metric] is not None:
            print(f"⚠️ Using Phase 3 fallback for player {player_id}, metric {metric}")
            return {
                "source": "phase3",
                "value": row[metric],
                "quality_penalty": 20  # 20-point penalty for Phase 3 fallback
            }

    # No data available in either phase
    raise ValueError(
        f"No data available for player {player_id}, metric {metric} "
        f"in Phase 4 (analysis_date={analysis_date}) or Phase 3 (game_date={game_date})"
    )
```

### Fallback Scenarios

**Scenario 1: Complete Phase 4 Failure (all 4 processors missing)**

```python
# ML Feature Store detects no Phase 4 data
validation = validate_dependencies(analysis_date)
if not validation["all_present"]:
    print(f"⚠️ Phase 4 incomplete: missing {validation['missing']}")
    print(f"⚠️ Attempting Phase 3 fallback for all players")

    # Switch to Phase 3 for ALL metrics
    use_phase3_fallback = True
    quality_score_penalty = 25  # Major penalty
```

**Scenario 2: Partial Phase 4 Failure (1-3 processors missing)**

```python
# Example: player_composite_factors missing, others present
missing = ["player_composite_factors"]

# For affected metrics, use Phase 3
for metric in ["offensive_rating", "usage_rate"]:  # Metrics from player_composite_factors
    data = get_data_source(analysis_date, player_id, metric)
    if data["source"] == "phase3":
        quality_score_penalty += data["quality_penalty"]
```

**Scenario 3: Individual Player Missing (Phase 4 has data, but specific player missing)**

```python
# Example: Nikola Jokic (203999) missing from Phase 4 (injury scratch?)
try:
    data = get_data_source(analysis_date, 203999, "points_projection")
except ValueError:
    # Neither Phase 4 nor Phase 3 has data (player didn't play yesterday)
    print(f"⚠️ Player 203999 has no recent data, skipping from ML Feature Store")
    # ML Feature Store will have 399 players instead of 400 (acceptable)
```

### Quality Score Adjustments

| Fallback Level | Quality Score Impact | Example |
|----------------|---------------------|---------|
| **No fallback** (100% Phase 4) | 0 penalty | Quality score = 100 |
| **Partial fallback** (5-25% Phase 3) | -5 to -10 points | Quality score = 90-95 |
| **Moderate fallback** (25-50% Phase 3) | -10 to -20 points | Quality score = 80-90 |
| **Heavy fallback** (50-100% Phase 3) | -20 to -25 points | Quality score = 75-80 |
| **Complete fallback** (100% Phase 3) | -25 points | Quality score = 75 (minimum acceptable) |

**Why 75 is minimum:** Phase 5 prediction models require quality_score ≥ 75 to run. Below 75, predictions are considered unreliable and Phase 5 fails with clear error message.

### Fallback Monitoring

```sql
-- Daily Phase 3 fallback rate
SELECT
  analysis_date,
  COUNT(*) as total_players,
  COUNTIF(data_source = 'phase3') as phase3_fallback_count,
  ROUND(COUNTIF(data_source = 'phase3') / COUNT(*) * 100, 1) as fallback_rate_pct,
  AVG(quality_score) as avg_quality_score
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE analysis_date >= CURRENT_DATE() - 7
GROUP BY analysis_date
ORDER BY analysis_date DESC

-- Expected output:
-- analysis_date | total_players | phase3_fallback_count | fallback_rate_pct | avg_quality_score
-- 2024-12-15    | 400           | 0                     | 0.0               | 100.0  ✅ Nominal
-- 2024-12-14    | 395           | 20                    | 5.1               | 95.2   ✅ OK (partial fallback)
-- 2024-12-13    | 380           | 380                   | 100.0             | 75.0   ⚠️ DEGRADED (complete fallback)
-- 2024-12-12    | 0             | 0                     | NULL              | NULL   ❌ FAILED (no data)
```

**Alert thresholds:**
- **fallback_rate_pct > 10%**: Warning (investigate Phase 4 processors)
- **fallback_rate_pct > 50%**: Critical (major Phase 4 failure)
- **fallback_rate_pct = 100%**: P1 incident (complete Phase 4 failure, running degraded)

---

## Quality Score Monitoring

**Purpose:** Track ML Feature Store data quality with 0-100 score across 6 components.

### Quality Score Components

Each component contributes to total score (max 100):

#### 1. Phase 4 Availability (40 points max)

**What it measures:** % of players with Phase 4 data available (not using Phase 3 fallback).

**Calculation:**
```sql
-- Phase 4 availability score
SELECT
  analysis_date,
  ROUND(
    (COUNTIF(data_source = 'phase4') / COUNT(*)) * 40,
    1
  ) as phase4_availability_score
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE analysis_date = CURRENT_DATE()
GROUP BY analysis_date

-- Example: 380 of 400 players have Phase 4 data
-- (380 / 400) * 40 = 38.0 points ✅
```

**Thresholds:**
- **40 points** (100% Phase 4): Perfect
- **36-40 points** (90-100% Phase 4): Acceptable
- **32-36 points** (80-90% Phase 4): Warning
- **<32 points** (<80% Phase 4): Critical

---

#### 2. Phase 3 Fallback Rate (20 points max)

**What it measures:** Penalty for using Phase 3 fallback data.

**Calculation:**
```sql
-- Phase 3 fallback penalty
SELECT
  analysis_date,
  ROUND(
    20 - (COUNTIF(data_source = 'phase3') / COUNT(*) * 20),
    1
  ) as phase3_fallback_score
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE analysis_date = CURRENT_DATE()
GROUP BY analysis_date

-- Example: 20 of 400 players using Phase 3 fallback
-- 20 - (20 / 400 * 20) = 20 - 1.0 = 19.0 points ✅
```

**Thresholds:**
- **20 points** (0% fallback): Perfect
- **18-20 points** (0-10% fallback): Acceptable
- **15-18 points** (10-25% fallback): Warning
- **<15 points** (>25% fallback): Critical

---

#### 3. Data Freshness (15 points max)

**What it measures:** How recent is the Phase 4 data?

**Calculation:**
```sql
-- Data freshness score
SELECT
  analysis_date,
  CASE
    -- Data from today = perfect
    WHEN MAX(source_data_date) = CURRENT_DATE() THEN 15.0
    -- Data from yesterday = minor penalty
    WHEN MAX(source_data_date) = CURRENT_DATE() - 1 THEN 12.0
    -- Data from 2 days ago = major penalty
    WHEN MAX(source_data_date) = CURRENT_DATE() - 2 THEN 8.0
    -- Data older than 2 days = critical
    ELSE 0.0
  END as data_freshness_score
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE analysis_date = CURRENT_DATE()
GROUP BY analysis_date
```

**Thresholds:**
- **15 points** (today): Perfect
- **12 points** (yesterday): Acceptable (game day +1)
- **8 points** (2 days ago): Warning
- **0 points** (>2 days ago): Critical

---

#### 4. Dependency Completeness (15 points max)

**What it measures:** Are all 4 Phase 4 dependencies present?

**Calculation:**
```sql
-- Dependency completeness score
WITH dependency_check AS (
  SELECT
    'team_defense_zone_analysis' as processor,
    COUNT(*) as row_count
  FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date = CURRENT_DATE()

  UNION ALL

  SELECT 'player_shot_zone_analysis', COUNT(*)
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date = CURRENT_DATE()

  UNION ALL

  SELECT 'player_composite_factors', COUNT(*)
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE analysis_date = CURRENT_DATE()

  UNION ALL

  SELECT 'player_daily_cache', COUNT(*)
  FROM `nba-props-platform.nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE()
)
SELECT
  ROUND(
    (COUNTIF(row_count > 0) / 4.0) * 15,
    1
  ) as dependency_completeness_score
FROM dependency_check

-- Example: All 4 dependencies present
-- (4 / 4) * 15 = 15.0 points ✅
```

**Thresholds:**
- **15 points** (4/4 dependencies): Perfect
- **11.25 points** (3/4 dependencies): Warning (one missing)
- **7.5 points** (2/4 dependencies): Critical
- **0 points** (0-1/4 dependencies): Fail

---

#### 5. Row Completeness (5 points max)

**What it measures:** Do we have expected number of players (200+)?

**Calculation:**
```sql
-- Row completeness score
SELECT
  analysis_date,
  CASE
    WHEN COUNT(*) >= 400 THEN 5.0  -- Full roster
    WHEN COUNT(*) >= 300 THEN 4.0  -- Most players
    WHEN COUNT(*) >= 200 THEN 3.0  -- Minimum acceptable
    WHEN COUNT(*) >= 100 THEN 1.0  -- Critical
    ELSE 0.0                        -- Fail
  END as row_completeness_score
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE analysis_date = CURRENT_DATE()
GROUP BY analysis_date
```

**Thresholds:**
- **5 points** (400+ players): Perfect
- **4 points** (300-399 players): Good
- **3 points** (200-299 players): Acceptable (minimum)
- **1 point** (100-199 players): Critical
- **0 points** (<100 players): Fail

---

#### 6. NULL Field Rate (5 points max)

**What it measures:** % of required fields that are NULL (data quality).

**Calculation:**
```sql
-- NULL field rate score
WITH null_analysis AS (
  SELECT
    COUNT(*) as total_rows,
    COUNTIF(points_projection IS NULL) as null_points,
    COUNTIF(rebounds_projection IS NULL) as null_rebounds,
    COUNTIF(assists_projection IS NULL) as null_assists,
    COUNTIF(offensive_rating IS NULL) as null_off_rating,
    COUNTIF(defensive_rating IS NULL) as null_def_rating
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE analysis_date = CURRENT_DATE()
)
SELECT
  ROUND(
    5.0 - (
      (null_points + null_rebounds + null_assists + null_off_rating + null_def_rating)
      / (total_rows * 5.0) * 5.0
    ),
    1
  ) as null_field_rate_score
FROM null_analysis

-- Example: 8 NULL fields out of 2000 total (400 players * 5 fields)
-- 5.0 - (8 / 2000 * 5.0) = 5.0 - 0.02 = 4.98 points ✅
```

**Thresholds:**
- **5 points** (0-1% NULL): Perfect
- **4-5 points** (1-5% NULL): Acceptable
- **3-4 points** (5-10% NULL): Warning
- **<3 points** (>10% NULL): Critical

---

### Overall Quality Score

**Total Score = Sum of all 6 components (max 100)**

**Example Calculation:**

```sql
-- Overall quality score for analysis_date = 2024-12-15
WITH quality_components AS (
  -- Component 1: Phase 4 Availability (40 max)
  SELECT
    38.0 as phase4_availability,  -- 380/400 players = 95%

    -- Component 2: Phase 3 Fallback Rate (20 max)
    19.0 as phase3_fallback,      -- 20/400 players = 5% fallback

    -- Component 3: Data Freshness (15 max)
    15.0 as data_freshness,       -- Data from today

    -- Component 4: Dependency Completeness (15 max)
    15.0 as dependency_complete,  -- All 4 dependencies present

    -- Component 5: Row Completeness (5 max)
    5.0 as row_completeness,      -- 400 players (full roster)

    -- Component 6: NULL Field Rate (5 max)
    4.8 as null_field_rate        -- 2% NULL rate
)
SELECT
  phase4_availability +
  phase3_fallback +
  data_freshness +
  dependency_complete +
  row_completeness +
  null_field_rate AS total_quality_score
FROM quality_components

-- Result: 38.0 + 19.0 + 15.0 + 15.0 + 5.0 + 4.8 = 96.8 / 100 ✅ EXCELLENT
```

### Quality Score Thresholds

| Score Range | Status | Action |
|-------------|--------|--------|
| **90-100** | ✅ Excellent | No action required |
| **80-89** | ✅ Good | Monitor for trends |
| **75-79** | ⚠️ Acceptable | Investigate cause of degradation |
| **65-74** | ⚠️ Warning | P2 incident - investigate immediately |
| **50-64** | ❌ Critical | P1 incident - Phase 5 may fail |
| **<50** | ❌ Fail | P0 incident - Block Phase 5 execution |

**Phase 5 Requirement:** ML Feature Store quality_score must be ≥ 75 for Phase 5 predictions to run.

### Daily Quality Dashboard

```sql
-- 7-day quality score trend
SELECT
  analysis_date,
  quality_score,
  phase4_availability_score,
  phase3_fallback_score,
  data_freshness_score,
  dependency_completeness_score,
  row_completeness_score,
  null_field_rate_score,
  CASE
    WHEN quality_score >= 90 THEN '✅ Excellent'
    WHEN quality_score >= 80 THEN '✅ Good'
    WHEN quality_score >= 75 THEN '⚠️ Acceptable'
    WHEN quality_score >= 65 THEN '⚠️ Warning'
    WHEN quality_score >= 50 THEN '❌ Critical'
    ELSE '❌ Fail'
  END as status
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2_quality_metrics`
WHERE analysis_date >= CURRENT_DATE() - 7
ORDER BY analysis_date DESC

-- Expected output:
-- analysis_date | quality_score | status
-- 2024-12-15    | 96.8          | ✅ Excellent
-- 2024-12-14    | 92.5          | ✅ Excellent
-- 2024-12-13    | 75.0          | ⚠️ Acceptable (complete Phase 3 fallback)
-- 2024-12-12    | 88.3          | ✅ Good
```

**Alert Configuration:**

```yaml
# Alert when quality score drops below 80
- name: ml_feature_store_quality_degradation
  condition: quality_score < 80
  severity: warning
  notification: slack #data-quality

# Alert when quality score drops below 75
- name: ml_feature_store_quality_critical
  condition: quality_score < 75
  severity: critical
  notification: pagerduty + slack #incidents
  message: "ML Feature Store quality score below 75 - Phase 5 predictions may fail"
```

---

## Cross-Dataset Write Orchestration

**Challenge:** ML Feature Store writes to `nba_predictions` dataset, while other Phase 4 processors write to `nba_precompute`.

**Why:** Phase 5 prediction models read from `nba_predictions` dataset. ML Feature Store is the bridge between Phase 4 aggregations and Phase 5 predictions.

### IAM Configuration

**Problem:** Phase 4 processors use service account `phase4-processor@nba-props-platform.iam.gserviceaccount.com` with write access to `nba_precompute` dataset. ML Feature Store needs write access to `nba_predictions` dataset.

**Solution 1: Dedicated Service Account (Recommended)**

```bash
# 1. Create dedicated service account for ML Feature Store
gcloud iam service-accounts create ml-feature-store \
  --display-name "ML Feature Store V2 Service Account"

# 2. Grant BigQuery write access to nba_predictions dataset
bq add-iam-policy-binding \
  --member serviceAccount:ml-feature-store@nba-props-platform.iam.gserviceaccount.com \
  --role roles/bigquery.dataEditor \
  nba_predictions

# 3. Grant BigQuery read access to nba_precompute dataset (for Phase 4 dependencies)
bq add-iam-policy-binding \
  --member serviceAccount:ml-feature-store@nba-props-platform.iam.gserviceaccount.com \
  --role roles/bigquery.dataViewer \
  nba_precompute

# 4. Grant BigQuery read access to nba_analytics dataset (for Phase 3 fallback)
bq add-iam-policy-binding \
  --member serviceAccount:ml-feature-store@nba-props-platform.iam.gserviceaccount.com \
  --role roles/bigquery.dataViewer \
  nba_analytics

# 5. Update ML Feature Store Cloud Run service to use new service account
gcloud run services update phase4-ml-feature-store-v2 \
  --service-account ml-feature-store@nba-props-platform.iam.gserviceaccount.com
```

**Pros:**
- ✅ Least privilege (ML Feature Store only has write access to nba_predictions)
- ✅ Clear separation of concerns (different service accounts for different datasets)
- ✅ Easier auditing (can track all nba_predictions writes to this service account)

**Cons:**
- ❌ Additional service account to manage

---

**Solution 2: Shared Service Account with Broader Permissions (Not Recommended)**

```bash
# Grant existing phase4-processor service account write access to nba_predictions
bq add-iam-policy-binding \
  --member serviceAccount:phase4-processor@nba-props-platform.iam.gserviceaccount.com \
  --role roles/bigquery.dataEditor \
  nba_predictions
```

**Pros:**
- ✅ Simpler (one service account for all Phase 4 processors)

**Cons:**
- ❌ Violates least privilege (all Phase 4 processors can write to nba_predictions)
- ❌ Harder to audit (cannot distinguish ML Feature Store writes from other processors)
- ❌ Security risk (if any Phase 4 processor compromised, attacker can write to nba_predictions)

**Recommendation:** Use Solution 1 (dedicated service account).

---

### Testing Cross-Dataset Writes

**Test 1: Write Permission Verification**

```bash
# Test write access to nba_predictions dataset
bq query --use_legacy_sql=false \
  --service_account_file /path/to/ml-feature-store-key.json \
  "INSERT INTO \`nba-props-platform.nba_predictions.ml_feature_store_v2_test\`
   (analysis_date, player_id, points_projection)
   VALUES (CURRENT_DATE(), 999999, 25.5)"

# Expected output: Query successfully executed
```

**Test 2: Read Permission Verification (Phase 4 dependencies)**

```bash
# Test read access to nba_precompute dataset
bq query --use_legacy_sql=false \
  --service_account_file /path/to/ml-feature-store-key.json \
  "SELECT COUNT(*) FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
   WHERE analysis_date = CURRENT_DATE()"

# Expected output: Row count (should be 400+)
```

**Test 3: Read Permission Verification (Phase 3 fallback)**

```bash
# Test read access to nba_analytics dataset
bq query --use_legacy_sql=false \
  --service_account_file /path/to/ml-feature-store-key.json \
  "SELECT COUNT(*) FROM \`nba-props-platform.nba_analytics.player_game_summary\`
   WHERE game_date = CURRENT_DATE() - 1"

# Expected output: Row count (should be 200+)
```

**Test 4: End-to-End Integration Test**

```python
# test_cross_dataset_write.py
from google.cloud import bigquery
import os

def test_cross_dataset_write():
    """Test ML Feature Store cross-dataset write permissions."""

    # Use ML Feature Store service account
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/path/to/ml-feature-store-key.json"

    client = bigquery.Client()

    # Test 1: Read from nba_precompute (Phase 4 dependencies)
    query1 = """
    SELECT COUNT(*) as count
    FROM `nba-props-platform.nba_precompute.player_composite_factors`
    WHERE analysis_date = CURRENT_DATE()
    """
    result1 = client.query(query1).result()
    assert list(result1)[0].count > 0, "Cannot read from nba_precompute"

    # Test 2: Read from nba_analytics (Phase 3 fallback)
    query2 = """
    SELECT COUNT(*) as count
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date = CURRENT_DATE() - 1
    """
    result2 = client.query(query2).result()
    assert list(result2)[0].count > 0, "Cannot read from nba_analytics"

    # Test 3: Write to nba_predictions
    query3 = """
    CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2_test` AS
    SELECT
      CURRENT_DATE() as analysis_date,
      999999 as player_id,
      25.5 as points_projection
    """
    client.query(query3).result()

    # Test 4: Verify write succeeded
    query4 = """
    SELECT COUNT(*) as count
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2_test`
    WHERE player_id = 999999
    """
    result4 = client.query(query4).result()
    assert list(result4)[0].count == 1, "Write to nba_predictions failed"

    print("✅ All cross-dataset permission tests passed")

if __name__ == "__main__":
    test_cross_dataset_write()
```

---

## Integration with Phase 5

**ML Feature Store is the critical bridge between Phase 4 precompute and Phase 5 predictions.**

### Phase 5 Dependencies

Phase 5 prediction models **cannot run** until ML Feature Store completes successfully.

**Phase 5 Validation Logic:**

```python
def validate_ml_feature_store_ready(prediction_date: str) -> bool:
    """
    Validate ML Feature Store data available for prediction_date.

    Phase 5 predictions require:
    1. ML Feature Store table exists for prediction_date
    2. Row count >= 200 players
    3. Quality score >= 75

    Returns:
        True if ML Feature Store ready, False otherwise
    """
    from google.cloud import bigquery

    client = bigquery.Client()

    # Check 1: ML Feature Store table exists for prediction_date
    query = f"""
    SELECT
      COUNT(*) as row_count,
      AVG(quality_score) as avg_quality_score
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE analysis_date = '{prediction_date}'
    """

    result = client.query(query).result()

    for row in result:
        row_count = row.row_count
        avg_quality_score = row.avg_quality_score

        # Check 2: Row count >= 200
        if row_count < 200:
            print(f"❌ ML Feature Store has insufficient data: {row_count} rows (need 200+)")
            return False

        # Check 3: Quality score >= 75
        if avg_quality_score < 75:
            print(f"❌ ML Feature Store quality too low: {avg_quality_score:.1f} (need 75+)")
            return False

        print(f"✅ ML Feature Store ready: {row_count} rows, quality {avg_quality_score:.1f}")
        return True

    # No data found
    print(f"❌ ML Feature Store has no data for {prediction_date}")
    return False

# In Phase 5 processor:
if not validate_ml_feature_store_ready(prediction_date):
    raise ValueError(f"Cannot run Phase 5: ML Feature Store not ready for {prediction_date}")
```

### Phase 5 Trigger Strategies

**Strategy 1: Event-Driven (Pub/Sub)**

ML Feature Store publishes success event → Phase 5 listens and triggers automatically.

```python
# In ML Feature Store processor:
def publish_success_event(analysis_date: str, row_count: int, quality_score: float):
    """Publish success event to trigger Phase 5."""
    from google.cloud import pubsub_v1
    import json

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path("nba-props-platform", "ml-feature-store-success")

    message = {
        "processor": "ml_feature_store_v2",
        "analysis_date": analysis_date,
        "row_count": row_count,
        "quality_score": quality_score,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    future = publisher.publish(topic_path, json.dumps(message).encode("utf-8"))
    print(f"Published success event to {topic_path}: {future.result()}")
```

**Phase 5 Cloud Run Subscription:**

```bash
# Create Pub/Sub topic
gcloud pubsub topics create ml-feature-store-success

# Create Cloud Run subscription (triggers Phase 5 automatically)
gcloud run services update phase5-prediction-models \
  --update-env-vars PUBSUB_TOPIC=ml-feature-store-success
```

---

**Strategy 2: Time-Based with Validation (Simpler)**

Phase 5 triggers at fixed time (11:50 PM), validates ML Feature Store ready before processing.

```bash
# Cloud Scheduler job for Phase 5
gcloud scheduler jobs create http phase5-predictions-trigger \
  --schedule "50 23 * * *" \
  --time-zone "America/New_York" \
  --uri "https://phase5-prediction-models-XXXXX.run.app/predict" \
  --http-method POST \
  --message-body '{"prediction_date": "2024-12-15"}' \
  --oidc-service-account-email phase5-scheduler@nba-props-platform.iam.gserviceaccount.com
```

**Phase 5 validation:**
```python
# In Phase 5 processor:
if not validate_ml_feature_store_ready(prediction_date):
    # Retry logic (ML Feature Store might still be running)
    time.sleep(300)  # Wait 5 minutes
    if not validate_ml_feature_store_ready(prediction_date):
        raise ValueError("ML Feature Store not ready after retry")
```

---

### Phase 5 Feature Access

**Phase 5 models read directly from ML Feature Store table:**

```python
def load_features_for_prediction(prediction_date: str) -> pd.DataFrame:
    """Load ML features for prediction_date."""
    from google.cloud import bigquery

    client = bigquery.Client()

    query = f"""
    SELECT
      player_id,
      player_name,
      team_abbreviation,
      opponent_abbreviation,

      -- Phase 4 features (from 4-way dependency merge)
      offensive_rating,
      defensive_rating,
      usage_rate,
      true_shooting_pct,

      -- Zone analysis features
      restricted_area_shot_pct,
      three_point_attempt_rate,

      -- Opponent defense features
      opponent_def_rating,
      opponent_rim_protection_rating,

      -- Quality metadata
      quality_score,
      data_source,  -- 'phase4' or 'phase3'

      -- Fallback indicators
      phase4_available,
      phase3_fallback_used

    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE analysis_date = '{prediction_date}'
      AND quality_score >= 75  -- Only use high-quality features
    ORDER BY player_id
    """

    df = client.query(query).to_dataframe()

    print(f"Loaded {len(df)} player features for {prediction_date}")
    print(f"Quality score range: {df['quality_score'].min():.1f} - {df['quality_score'].max():.1f}")
    print(f"Phase 3 fallback rate: {(df['phase3_fallback_used'].sum() / len(df) * 100):.1f}%")

    return df
```

**Feature Columns Available to Phase 5:**

| Feature Category | Column Names | Source |
|------------------|--------------|--------|
| **Player Identity** | player_id, player_name, team_abbreviation, opponent_abbreviation | Phase 2 raw |
| **Offensive Metrics** | offensive_rating, usage_rate, true_shooting_pct, points_per_36 | player_composite_factors (P4) |
| **Defensive Metrics** | defensive_rating, defensive_win_shares, steal_rate, block_rate | player_composite_factors (P4) |
| **Shot Zone Analysis** | restricted_area_shot_pct, paint_shot_pct, mid_range_shot_pct, three_point_attempt_rate | player_shot_zone_analysis (P4) |
| **Opponent Defense** | opponent_def_rating, opponent_rim_protection_rating, opponent_perimeter_def_rating | team_defense_zone_analysis (P4) |
| **Recent Performance** | last_5_games_ppg, last_10_games_ppg, season_avg_ppg | player_daily_cache (P4) |
| **Quality Metadata** | quality_score, data_source, phase4_available, phase3_fallback_used | ML Feature Store logic |

**Total Features:** 40+ columns per player

---

## Data Flow Diagrams

### High-Level Data Flow (Phase 2 → Phase 5)

```
┌─────────────────────────────────────────────────────────────────┐
│                         Phase 2: Raw Data                        │
│  (GCS JSON → BigQuery raw tables: nbac_boxscore_traditional,    │
│   nbac_player_list, nbac_team_list, odds_events, etc.)          │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Phase 3: Analytics                          │
│  - player_game_summary (historical player stats)                │
│  - team_offense_game_summary (team offensive metrics)           │
│  - team_defense_game_summary (team defensive metrics)           │
│  - upcoming_team_game_context (next game context)               │
│  - upcoming_player_game_context (next game player context)      │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 4: Precompute (4 Parallel)              │
│  Parallel Set 1:                                                 │
│    - team_defense_zone_analysis (opponent defense by zone)      │
│    - player_shot_zone_analysis (player shooting by zone)        │
│  Parallel Set 2 (waits for Set 1):                              │
│    - player_composite_factors (offensive/defensive ratings)     │
│    - player_daily_cache (recent performance aggregates)         │
└───┬───────────┬────────────┬──────────────┬──────────────────────┘
    │           │            │              │
    │           │            │              │
    └───────────┴────────────┴──────────────┘
                        │
                (4-way merge waits for ALL 4)
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│           Phase 4: ML Feature Store V2 (4-way merge)             │
│  - Merges all 4 Phase 4 processors                               │
│  - Phase 3 fallback when Phase 4 unavailable                     │
│  - Quality score calculation (0-100)                             │
│  - Cross-dataset write → nba_predictions.ml_feature_store_v2    │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Phase 5: Prediction Models                     │
│  - Load features from ml_feature_store_v2                        │
│  - XGBoost models for points/rebounds/assists predictions       │
│  - Confidence scores based on quality_score                      │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                        ▼
                  nba_predictions.player_prop_predictions
                  (ready for Phase 6 web app)
```

---

### ML Feature Store 4-Way Dependency Detail

```
┌──────────────────────────────────────────────────────────────────┐
│              Phase 4: Four Processors (Sequential + Parallel)     │
└──────────────────────────────────────────────────────────────────┘

11:00 PM ──┐
           │  Parallel Set 1 (concurrent execution)
           │  ┌─────────────────────────────────────────┐
           ├──┤ P1: team_defense_zone_analysis          │
           │  │  Duration: 5 min                        │
           │  │  Output: 30 team records                │
           │  └─────────────────────────────────────────┘
           │
           │  ┌─────────────────────────────────────────┐
           └──┤ P2: player_shot_zone_analysis           │
              │  Duration: 10 min (CRITICAL PATH)       │
              │  Output: 400 player records             │
              └──────────────────┬──────────────────────┘
                                 │
                    (Both P1 and P2 must complete)
                                 │
11:10 PM ────────────────────────┴──────────────────┐
                                                     │
           Parallel Set 2 (concurrent execution)    │
           ┌─────────────────────────────────────┐  │
           │ P3: player_composite_factors        │◄─┤
           │  Duration: 5 min                    │  │
           │  Output: 400 player records         │  │
           └─────────────────────────────────────┘  │
                                                     │
           ┌─────────────────────────────────────┐  │
           │ P4: player_daily_cache              │◄─┘
           │  Duration: 5 min                    │
           │  Output: 400 player records         │
           └──────────────────┬──────────────────┘
                              │
                 (All 4 processors must complete)
                              │
11:15 PM ─────────────────────┴───────────────────────┐
                                                       │
           ┌───────────────────────────────────────┐  │
           │ P5: ml_feature_store_v2               │◄─┘
           │  4-WAY DEPENDENCY:                    │
           │   - Reads P1 (team defense)           │
           │   - Reads P2 (player shot zones)      │
           │   - Reads P3 (composite factors)      │
           │   - Reads P4 (daily cache)            │
           │                                        │
           │  Fallback: Phase 3 analytics          │
           │  Quality Score: 0-100                 │
           │  Duration: 25 min                     │
           │  Output: 400 player features          │
           │                                        │
           │  Cross-dataset write:                 │
           │   → nba_predictions.ml_feature_store_v2│
           └───────────────────────────────────────┘
                              │
11:40 PM ─────────────────────┘

Critical Path: 11:00 PM (start) → 11:40 PM (P5 complete) = 40 minutes
  - P2 (10 min) + P3/P4 (5 min, sequential) + P5 (25 min) = 40 min
```

---

### Phase 3 Fallback Decision Tree

```
                    ML Feature Store Start
                              │
                              ▼
              ┌───────────────────────────────┐
              │ Check Phase 4 Dependencies    │
              │ (team_defense, player_shot,   │
              │  composite_factors,            │
              │  player_daily_cache)          │
              └───────────────┬───────────────┘
                              │
                ┌─────────────┴─────────────┐
                │                           │
                ▼                           ▼
      ┌─────────────────────┐    ┌──────────────────────┐
      │ All 4 Present?      │    │ 1-3 Present?         │
      │ (100% Phase 4)      │    │ (Partial Phase 4)    │
      └──────┬──────────────┘    └──────┬───────────────┘
             │                           │
             ▼                           ▼
      ┌─────────────────────┐    ┌──────────────────────┐
      │ Use Phase 4 Only    │    │ Use Phase 4 where    │
      │ Quality Score: 100  │    │ available, Phase 3   │
      │                     │    │ for missing metrics  │
      └─────────────────────┘    │ Quality Score: 80-95 │
                                 └──────────────────────┘
                                           │
                ┌──────────────────────────┴─────────────┐
                │                                        │
                ▼                                        ▼
      ┌─────────────────────┐                  ┌─────────────────────┐
      │ 0 Present?          │                  │ Check Phase 3       │
      │ (No Phase 4)        │                  │ (player_game_summary│
      │                     │                  │  team_offense/      │
      │                     │                  │  defense_summary)   │
      └──────┬──────────────┘                  └──────┬──────────────┘
             │                                        │
             ▼                                        ▼
      ┌─────────────────────┐              ┌─────────────────────────┐
      │ Phase 3 Available?  │              │ Phase 3 Available?      │
      │                     │              │                         │
      └──────┬──────────────┘              └──────┬──────────────────┘
             │                                    │
    ┌────────┴─────────┐              ┌──────────┴───────────┐
    │                  │              │                      │
    ▼                  ▼              ▼                      ▼
┌────────┐    ┌──────────────┐  ┌────────┐        ┌──────────────┐
│ Yes    │    │ No           │  │ Yes    │        │ No           │
└───┬────┘    └───┬──────────┘  └───┬────┘        └───┬──────────┘
    │             │                 │                  │
    ▼             ▼                 ▼                  ▼
┌────────────┐ ┌────────────┐ ┌────────────┐   ┌──────────────┐
│Use Phase 3 │ │ FAIL       │ │Use Phase 3 │   │ FAIL         │
│Complete    │ │ No data    │ │Partial     │   │ No data      │
│Fallback    │ │ available  │ │            │   │ available    │
│Quality: 75 │ │ P0 INCIDENT│ │Quality:    │   │ P0 INCIDENT  │
│⚠️ DEGRADED │ │            │ │80-90       │   │              │
└────────────┘ └────────────┘ └────────────┘   └──────────────┘
```

---

## Operational Procedures

### Daily Operations (6 minutes)

**Goal:** Verify ML Feature Store ran successfully and quality meets standards.

**Checklist:**

```bash
# 1. Check ML Feature Store execution status (30 sec)
bq query --use_legacy_sql=false "
SELECT
  analysis_date,
  COUNT(*) as player_count,
  AVG(quality_score) as avg_quality_score,
  MAX(processed_at) as last_processed
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE analysis_date = CURRENT_DATE()
GROUP BY analysis_date
"

# Expected: 400 players, quality_score 90+, processed_at = today 11:40 PM

# 2. Check 4-way dependency status (1 min)
bq query --use_legacy_sql=false "
SELECT
  'team_defense_zone_analysis' as processor,
  COUNT(*) as rows,
  MAX(processed_at) as last_run
FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_shot_zone_analysis', COUNT(*), MAX(processed_at)
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_composite_factors', COUNT(*), MAX(processed_at)
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_daily_cache', COUNT(*), MAX(processed_at)
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE analysis_date = CURRENT_DATE()
"

# Expected: All 4 processors with rows > 0

# 3. Check Phase 3 fallback rate (1 min)
bq query --use_legacy_sql=false "
SELECT
  COUNTIF(data_source = 'phase3') as phase3_count,
  COUNTIF(data_source = 'phase4') as phase4_count,
  ROUND(COUNTIF(data_source = 'phase3') / COUNT(*) * 100, 1) as fallback_pct
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE analysis_date = CURRENT_DATE()
"

# Expected: fallback_pct < 10%

# 4. Check quality score components (2 min)
bq query --use_legacy_sql=false "
SELECT
  analysis_date,
  phase4_availability_score,
  phase3_fallback_score,
  data_freshness_score,
  dependency_completeness_score,
  row_completeness_score,
  null_field_rate_score,
  quality_score
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2_quality_metrics\`
WHERE analysis_date = CURRENT_DATE()
"

# Expected: All component scores green, quality_score 90+

# 5. Check Phase 5 integration (1.5 min)
bq query --use_legacy_sql=false "
SELECT
  prediction_date,
  COUNT(*) as prediction_count,
  AVG(confidence_score) as avg_confidence
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE prediction_date = CURRENT_DATE()
GROUP BY prediction_date
"

# Expected: 400+ predictions, avg_confidence 75+
```

**Actions:**
- ✅ **All green:** No action required
- ⚠️ **fallback_pct > 10%:** Investigate Phase 4 processor failures (see [Incident Response](#incident-response-playbook))
- ❌ **quality_score < 75:** P1 incident - Phase 5 may fail
- ❌ **player_count < 200:** P0 incident - Critical data missing

---

### Weekly Review (25 minutes)

**Goal:** Analyze trends, identify degradation patterns, optimize performance.

**Week 1: Quality Score Trends (5 min)**

```sql
-- 7-day quality score trend
SELECT
  analysis_date,
  quality_score,
  phase4_availability_score,
  phase3_fallback_score,
  COUNTIF(data_source = 'phase3') as phase3_fallback_count
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2_quality_metrics`
  LEFT JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` USING (analysis_date)
WHERE analysis_date >= CURRENT_DATE() - 7
GROUP BY analysis_date, quality_score, phase4_availability_score, phase3_fallback_score
ORDER BY analysis_date DESC
```

**Look for:**
- Quality score declining over time (burndown chart)
- Increasing Phase 3 fallback rate (Phase 4 degradation)
- Days with quality_score < 80 (investigate cause)

---

**Week 2: Dependency Reliability (5 min)**

```sql
-- Which Phase 4 processor fails most often?
SELECT
  analysis_date,
  COUNTIF(team_defense_available = FALSE) as team_defense_failures,
  COUNTIF(player_shot_available = FALSE) as player_shot_failures,
  COUNTIF(composite_available = FALSE) as composite_failures,
  COUNTIF(daily_cache_available = FALSE) as daily_cache_failures
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2_dependency_tracking`
WHERE analysis_date >= CURRENT_DATE() - 7
GROUP BY analysis_date
ORDER BY analysis_date DESC
```

**Look for:**
- Repeated failures from single processor (needs investigation)
- Failures on specific days of week (scheduling issue?)

---

**Week 3: Performance Analysis (10 min)**

```sql
-- ML Feature Store execution duration trend
SELECT
  analysis_date,
  TIMESTAMP_DIFF(completed_at, started_at, MINUTE) as duration_minutes,
  row_count,
  quality_score
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2_execution_log`
WHERE analysis_date >= CURRENT_DATE() - 7
ORDER BY analysis_date DESC
```

**Look for:**
- Execution duration increasing (performance degradation)
- Duration > 30 minutes (approaching timeout threshold)
- Correlation between row_count and duration (scaling issues?)

**Action:** If duration > 25 minutes consistently, see [Performance Optimization](#performance-optimization).

---

**Week 4: Phase 5 Impact (5 min)**

```sql
-- How does ML Feature Store quality affect Phase 5 predictions?
SELECT
  fs.analysis_date,
  fs.quality_score as ml_feature_store_quality,
  AVG(pred.confidence_score) as avg_prediction_confidence,
  COUNT(pred.player_id) as prediction_count
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2_quality_metrics` fs
  LEFT JOIN `nba-props-platform.nba_predictions.player_prop_predictions` pred
    ON fs.analysis_date = pred.prediction_date
WHERE fs.analysis_date >= CURRENT_DATE() - 7
GROUP BY fs.analysis_date, fs.quality_score
ORDER BY fs.analysis_date DESC
```

**Look for:**
- Correlation: Low ML Feature Store quality → Low prediction confidence
- Days where prediction_count < 400 (missing predictions due to low quality?)

---

### Monthly Optimization (45 minutes)

**Goal:** Deep-dive performance optimization, cost analysis, infrastructure improvements.

**Month 1: Execution Time Optimization**

See [Performance Optimization](#performance-optimization) section for 4 strategies.

---

**Month 2: Cost Analysis**

```sql
-- BigQuery slot usage for ML Feature Store
SELECT
  DATE(creation_time) as execution_date,
  SUM(total_slot_ms) / 1000 / 60 / 60 as total_slot_hours,
  SUM(total_bytes_processed) / 1024 / 1024 / 1024 as total_gb_processed,
  COUNT(*) as query_count
FROM `nba-props-platform.region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE
  creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND job_type = 'QUERY'
  AND user_email = 'ml-feature-store@nba-props-platform.iam.gserviceaccount.com'
GROUP BY execution_date
ORDER BY execution_date DESC
```

**Action:** If slot_hours > 2 per day or gb_processed > 50 GB per day, optimize queries.

---

**Month 3: Infrastructure Review**

- Review service account permissions (still least privilege?)
- Review Pub/Sub topic retention (7 days sufficient?)
- Review Firestore quotas (if using Cloud Function strategy)
- Review Cloud Run timeout settings (still 60 minutes?)
- Review alerting thresholds (false positives?)

---

## Incident Response Playbook

**ML Feature Store failures are P0/P1 severity because they block Phase 5 predictions.**

### Severity Levels

| Severity | Condition | Impact | Response Time |
|----------|-----------|--------|---------------|
| **P0** | quality_score < 50 OR row_count < 100 | Phase 5 predictions fail completely | Immediate (24/7) |
| **P1** | quality_score 50-74 OR row_count 100-199 | Phase 5 predictions degraded | <2 hours |
| **P2** | quality_score 75-79 OR fallback_pct > 25% | Phase 5 predictions acceptable but degraded | <4 hours |
| **P3** | quality_score 80-89 OR fallback_pct 10-25% | Minor quality degradation | Next business day |

---

### P0 Incident: ML Feature Store Complete Failure

**Symptoms:**
- ML Feature Store table has 0 rows for today
- OR quality_score < 50
- OR row_count < 100

**Impact:**
- Phase 5 predictions CANNOT run
- Web app shows stale predictions
- Business impact: Users see outdated prop recommendations

**Immediate Actions (5 minutes):**

```bash
# 1. Check if ML Feature Store Cloud Run service is down
gcloud run services describe phase4-ml-feature-store-v2 --region us-central1

# 2. Check recent Cloud Run logs for errors
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=phase4-ml-feature-store-v2" \
  --limit 50 \
  --format json

# 3. Check if any Phase 4 dependencies failed
bq query --use_legacy_sql=false "
SELECT
  'team_defense_zone_analysis' as processor,
  COUNT(*) as rows
FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_shot_zone_analysis', COUNT(*)
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_composite_factors', COUNT(*)
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_daily_cache', COUNT(*)
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE analysis_date = CURRENT_DATE()
"

# 4. Check if Phase 3 data available (can we fallback?)
bq query --use_legacy_sql=false "
SELECT COUNT(*) as player_count
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = CURRENT_DATE() - 1
"
```

**Root Cause Analysis (10 minutes):**

**Scenario A: All 4 Phase 4 dependencies failed**
→ Upstream failure in Phase 3 or Phase 2
→ Escalate to Phase 3/2 owner
→ ML Feature Store cannot run until dependencies fixed

**Scenario B: 1-3 Phase 4 dependencies failed**
→ Specific processor failure (check logs for failed processor)
→ Attempt manual trigger for failed processor (see `05-phase4-operations-guide.md`)
→ If manual trigger succeeds, retry ML Feature Store

**Scenario C: All Phase 4 dependencies present, ML Feature Store failed**
→ ML Feature Store processor bug (check Cloud Run logs)
→ Common issues: BigQuery quota, IAM permissions, timeout

**Mitigation (15 minutes):**

```bash
# Option 1: Manual retry with Phase 3 fallback forced
curl -X POST https://phase4-ml-feature-store-v2-XXXXX.run.app/process \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_date": "2024-12-15",
    "force_phase3_fallback": true
  }'

# Option 2: If Cloud Run service unhealthy, redeploy latest revision
gcloud run services update-traffic phase4-ml-feature-store-v2 \
  --to-revisions LATEST=100 \
  --region us-central1

# Option 3: If complete failure and no recovery possible, use yesterday's data
# (This is LAST RESORT - predictions will be stale)
bq query --use_legacy_sql=false "
INSERT INTO \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
SELECT
  CURRENT_DATE() as analysis_date,  -- Use today's date
  player_id,
  player_name,
  -- ... (copy all fields from yesterday)
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE analysis_date = CURRENT_DATE() - 1
"
```

**Follow-Up:**
- Post-mortem within 48 hours
- Update runbook with learnings
- Add monitoring to prevent recurrence

---

### P1 Incident: ML Feature Store Degraded Quality

**Symptoms:**
- quality_score 50-74
- OR row_count 100-199
- OR fallback_pct > 50%

**Impact:**
- Phase 5 predictions run but with low confidence
- Web app shows predictions with warnings
- Business impact: Users may see unreliable recommendations

**Actions (2 hours):**

```bash
# 1. Check quality score breakdown
bq query --use_legacy_sql=false "
SELECT
  analysis_date,
  quality_score,
  phase4_availability_score,
  phase3_fallback_score,
  data_freshness_score,
  dependency_completeness_score,
  row_completeness_score,
  null_field_rate_score
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2_quality_metrics\`
WHERE analysis_date = CURRENT_DATE()
"

# 2. Identify which component(s) causing low score
# Example: If dependency_completeness_score low, check which dependency missing

# 3. Attempt to fix missing dependency
# See `07-phase4-troubleshooting.md` for processor-specific recovery

# 4. If Phase 4 cannot be fixed, verify Phase 3 fallback working correctly
bq query --use_legacy_sql=false "
SELECT
  data_source,
  COUNT(*) as count
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE analysis_date = CURRENT_DATE()
GROUP BY data_source
"

# Expected: Some Phase 3, most Phase 4
```

**Mitigation:**
- If quality_score < 75: Block Phase 5 (predictions unreliable)
- If quality_score 75-80: Allow Phase 5 with warnings
- If quality_score 80-90: Allow Phase 5 normally (monitor for trends)

---

### P2 Incident: Moderate Quality Degradation

**Symptoms:**
- quality_score 75-79
- OR fallback_pct 25-50%

**Actions (4 hours):**
- Investigate root cause (which Phase 4 processor degraded?)
- Monitor for trends (is quality declining over time?)
- Plan fix for next maintenance window

---

### P3 Incident: Minor Quality Degradation

**Symptoms:**
- quality_score 80-89
- OR fallback_pct 10-25%

**Actions (Next business day):**
- Log issue for weekly review
- Add to monthly optimization backlog

---

## Performance Optimization

**Current Performance:** 25 minutes execution time (target: 15 minutes)

**Performance Bottlenecks:**

1. **BigQuery query execution** (20 minutes) - Joining 4 Phase 4 tables + Phase 3 fallback
2. **Cross-dataset write** (3 minutes) - Writing 400 rows to nba_predictions dataset
3. **Quality score calculation** (2 minutes) - Computing 6 quality components

---

### Strategy 1: Query Optimization

**Problem:** Joining 4 large tables (team_defense, player_shot, composite_factors, daily_cache) is slow.

**Solution:** Use BigQuery clustering and partitioning.

```sql
-- Current schema (no optimization)
CREATE TABLE `nba-props-platform.nba_precompute.player_composite_factors` (
  analysis_date DATE,
  player_id INT64,
  offensive_rating FLOAT64,
  -- ...
);

-- Optimized schema (partitioned by analysis_date, clustered by player_id)
CREATE TABLE `nba-props-platform.nba_precompute.player_composite_factors` (
  analysis_date DATE,
  player_id INT64,
  offensive_rating FLOAT64,
  -- ...
)
PARTITION BY analysis_date
CLUSTER BY player_id;
```

**Expected improvement:** 20 min → 12 min (40% faster)

**Deployment:**

```bash
# Recreate each Phase 4 table with partitioning/clustering
for table in team_defense_zone_analysis player_shot_zone_analysis player_composite_factors player_daily_cache; do
  bq query --use_legacy_sql=false "
  CREATE OR REPLACE TABLE \`nba-props-platform.nba_precompute.${table}\`
  PARTITION BY analysis_date
  CLUSTER BY player_id
  AS SELECT * FROM \`nba-props-platform.nba_precompute.${table}\`
  "
done
```

---

### Strategy 2: Parallel Processing

**Problem:** Processing 400 players sequentially is slow.

**Solution:** Batch processing with parallel Cloud Run instances.

```python
# Current: Sequential processing
for player_id in all_players:
    features = extract_features(player_id)
    insert_to_bq(features)

# Optimized: Parallel batches
from concurrent.futures import ThreadPoolExecutor

def process_player_batch(player_ids):
    """Process 50 players at a time."""
    features = extract_features_batch(player_ids)  # Single BigQuery query
    insert_to_bq_batch(features)  # Single batch insert

# Process 400 players in 8 batches of 50
batches = [all_players[i:i+50] for i in range(0, len(all_players), 50)]

with ThreadPoolExecutor(max_workers=8) as executor:
    executor.map(process_player_batch, batches)
```

**Expected improvement:** 25 min → 18 min (28% faster)

---

### Strategy 3: Materialized Views

**Problem:** Re-joining same Phase 4 tables every day is wasteful.

**Solution:** Create materialized view with pre-joined data.

```sql
-- Create materialized view (refreshes automatically)
CREATE MATERIALIZED VIEW `nba-props-platform.nba_precompute.ml_feature_store_base_mv`
PARTITION BY analysis_date
CLUSTER BY player_id
AS
SELECT
  p.analysis_date,
  p.player_id,
  p.player_name,
  p.offensive_rating,
  p.defensive_rating,
  s.restricted_area_shot_pct,
  s.three_point_attempt_rate,
  t.opponent_def_rating,
  d.last_5_games_ppg
FROM `nba-props-platform.nba_precompute.player_composite_factors` p
  LEFT JOIN `nba-props-platform.nba_precompute.player_shot_zone_analysis` s USING (analysis_date, player_id)
  LEFT JOIN `nba-props-platform.nba_precompute.team_defense_zone_analysis` t ON p.analysis_date = t.analysis_date AND p.opponent_abbreviation = t.team_abbreviation
  LEFT JOIN `nba-props-platform.nba_precompute.player_daily_cache` d USING (analysis_date, player_id);

-- ML Feature Store reads from materialized view (much faster)
SELECT * FROM `nba-props-platform.nba_precompute.ml_feature_store_base_mv`
WHERE analysis_date = CURRENT_DATE();
```

**Expected improvement:** 25 min → 10 min (60% faster)

**Cons:**
- Materialized view refresh adds 5 minutes (but happens async, doesn't block ML Feature Store)
- Additional storage costs ($5/month for 400 players * 365 days)

---

### Strategy 4: Caching Phase 3 Fallback Data

**Problem:** Querying Phase 3 analytics tables for fallback is slow (especially when many players need fallback).

**Solution:** Pre-cache Phase 3 data in temporary table during Phase 3 execution.

```sql
-- Create Phase 3 cache table (populated during Phase 3 execution)
CREATE TABLE `nba-props-platform.nba_precompute.phase3_fallback_cache` (
  cache_date DATE,
  player_id INT64,
  points_projection FLOAT64,
  rebounds_projection FLOAT64,
  assists_projection FLOAT64,
  -- ... (pre-computed fallback values)
)
PARTITION BY cache_date
CLUSTER BY player_id;

-- ML Feature Store reads from cache (instant lookup)
SELECT * FROM `nba-props-platform.nba_precompute.phase3_fallback_cache`
WHERE cache_date = CURRENT_DATE()
  AND player_id = 203999;
```

**Expected improvement:** 2-5 minutes saved when fallback rate > 25%

---

### Recommended Optimization Path

**Month 1:** Implement Strategy 1 (Query Optimization) - Low risk, high reward
**Month 2:** Implement Strategy 2 (Parallel Processing) - Medium risk, medium reward
**Month 3:** Implement Strategy 3 (Materialized Views) - High reward, requires testing
**Month 4:** Implement Strategy 4 (Phase 3 Cache) - Only if high fallback rate

**Target Performance after all optimizations:** 10-12 minutes (from 25 minutes)

---

## Summary

ML Feature Store V2 is the most complex processor in the NBA Props Platform due to:

1. **4-way dependency**: Must wait for ALL 4 Phase 4 processors
2. **Cross-dataset writes**: Writes to nba_predictions (not nba_precompute)
3. **Phase 3 fallback**: Gracefully degrades when Phase 4 unavailable
4. **Quality scoring**: Tracks data quality with 6-component 0-100 score
5. **Critical path blocker**: Phase 5 cannot run until this completes
6. **Complex data lineage**: Combines 4 Phase 4 processors + Phase 3 fallback

**Key Takeaways:**

- Use **Cloud Workflows** for production orchestration (deterministic 4-way dependency)
- Monitor **quality score ≥ 75** (Phase 5 requirement)
- Watch **Phase 3 fallback rate** (indicates Phase 4 health)
- **P0 incidents** block Phase 5 entirely (immediate response required)
- **Performance target**: 15 minutes (currently 25 minutes)

**Next Steps:**

1. Review `05-phase4-operations-guide.md` for processor specifications
2. Review `06-phase4-scheduling-strategy.md` for deployment strategies
3. Review `07-phase4-troubleshooting.md` for failure recovery procedures
4. Implement orchestration strategy (start with time-based, upgrade to Cloud Workflows)
5. Monitor quality scores daily
6. Optimize performance using strategies in this guide

---

**Last Updated:** 2025-11-15 16:30 PST
**Next Review:** After Phase 4 deployment
**Feedback:** Report issues to data-engineering team
