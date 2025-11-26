# Adding Processors to Pub/Sub Registry

**File:** `docs/guides/07-adding-processors-to-pubsub-registry.md`
**Created:** 2025-11-23
**Purpose:** Step-by-step guide for registering new processors for Pub/Sub triggers
**Audience:** Engineers adding new processors to Phase 3 or Phase 4

---

## Overview

When you create a new processor, it won't automatically run when upstream data arrives. You must **register** it in the appropriate Pub/Sub registry.

**What this guide covers:**
- Adding processors to Phase 3 (Analytics)
- Adding processors to Phase 4 (Precompute)
- Testing your registration
- Deploying the changes
- Common mistakes

---

## Phase 3: Adding Analytics Processors

### When to Use This

You're adding a new processor that should run when Phase 2 raw data completes.

**Examples:**
- New analytics table (player stats, team metrics, etc.)
- New data source triggers analytics processing
- Adding processor to existing trigger

### Step-by-Step

#### 1. Import Your Processor

**File:** `data_processors/analytics/main_analytics_service.py`

```python
# At the top of the file, add your import
from data_processors.analytics.your_new_processor.your_new_processor_processor import YourNewProcessorProcessor
```

**Example:**
```python
from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
```

#### 2. Add to ANALYTICS_TRIGGERS Registry

**File:** `data_processors/analytics/main_analytics_service.py`

Find the `ANALYTICS_TRIGGERS` dictionary and add your processor:

```python
ANALYTICS_TRIGGERS = {
    'bdl_player_boxscores': [
        PlayerGameSummaryProcessor,
        TeamOffenseGameSummaryProcessor,
        YourNewProcessorProcessor,  # ADD HERE
    ],
    # Or create a new trigger:
    'your_new_source_table': [
        YourNewProcessorProcessor,
    ],
}
```

**Choosing the right trigger:**
- Use `bdl_player_boxscores` if your processor needs player boxscore data
- Use `nbac_scoreboard_v2` if your processor needs scoreboard data
- Create a new entry if your processor uses a different source

#### 3. Add to Manual Endpoint

**File:** `data_processors/analytics/main_analytics_service.py`

Find the `processor_map` in the `/process-date-range` endpoint:

```python
processor_map = {
    'PlayerGameSummaryProcessor': PlayerGameSummaryProcessor,
    'TeamOffenseGameSummaryProcessor': TeamOffenseGameSummaryProcessor,
    'TeamDefenseGameSummaryProcessor': TeamDefenseGameSummaryProcessor,
    'YourNewProcessorProcessor': YourNewProcessorProcessor,  # ADD HERE
}
```

**Why?** This allows manual testing via HTTP API.

#### 4. Deploy to Cloud Run

```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
```

**Wait for:** Health check to pass (~5 minutes)

#### 5. Test Your Registration

**Test Pub/Sub trigger:**
```bash
# Publish a test message to Phase 2 topic
gcloud pubsub topics publish nba-phase2-raw-complete \
  --message='{"source_table": "bdl_player_boxscores", "game_date": "2024-11-22", "success": true}'

# Check Cloud Run logs
gcloud run services logs read nba-phase3-analytics-processors \
  --region us-west2 \
  --limit 50
```

**Look for:** Log line showing your processor ran:
```
INFO: Running YourNewProcessorProcessor for 2024-11-22
```

**Test manual endpoint:**
```bash
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "processors": ["YourNewProcessorProcessor"],
    "start_date": "2024-11-22",
    "end_date": "2024-11-22"
  }'
```

---

## Phase 4: Adding Precompute Processors

### When to Use This

You're adding a new processor that should run when Phase 3 analytics completes.

**Examples:**
- New precompute table
- New analytics source triggers precompute
- CASCADE processor with multiple dependencies

### Step-by-Step

#### 1. Import Your Processor

**File:** `data_processors/precompute/main_precompute_service.py`

```python
# At the top of the file
from data_processors.precompute.your_new_processor.your_new_processor_processor import YourNewProcessorProcessor
```

#### 2. Add to PRECOMPUTE_TRIGGERS Registry

**File:** `data_processors/precompute/main_precompute_service.py`

```python
PRECOMPUTE_TRIGGERS = {
    'player_game_summary': [PlayerDailyCacheProcessor],
    'team_defense_game_summary': [TeamDefenseZoneAnalysisProcessor],
    'your_new_analytics_table': [YourNewProcessorProcessor],  # ADD HERE
}
```

**OR** if it's a CASCADE processor:

```python
CASCADE_PROCESSORS = {
    'player_composite_factors': PlayerCompositeFactorsProcessor,
    'ml_feature_store': MLFeatureStoreProcessor,
    'your_cascade_processor': YourCascadeProcessorProcessor,  # ADD HERE
}
```

**Choosing between PRECOMPUTE_TRIGGERS vs CASCADE_PROCESSORS:**
- **PRECOMPUTE_TRIGGERS:** Runs automatically when 1 specific upstream completes
- **CASCADE_PROCESSORS:** Runs on schedule, checks MULTIPLE upstreams

#### 3. Add to Manual Endpoint

**File:** `data_processors/precompute/main_precompute_service.py`

```python
processor_map = {
    'TeamDefenseZoneAnalysisProcessor': TeamDefenseZoneAnalysisProcessor,
    'PlayerShotZoneAnalysisProcessor': PlayerShotZoneAnalysisProcessor,
    'PlayerDailyCacheProcessor': PlayerDailyCacheProcessor,
    'YourNewProcessorProcessor': YourNewProcessorProcessor,  # ADD HERE
}
```

#### 4. Deploy to Cloud Run

```bash
./bin/precompute/deploy/deploy_precompute_processors.sh
```

**Wait for:** Health check to pass (~3 minutes)

#### 5. Test Your Registration

**Test Pub/Sub trigger:**
```bash
# Publish a test message to Phase 3 topic
gcloud pubsub topics publish nba-phase3-analytics-complete \
  --message='{"source_table": "team_defense_game_summary", "analysis_date": "2024-11-22", "success": true}'

# Check logs
gcloud run services logs read nba-phase4-precompute-processors \
  --region us-west2 \
  --limit 50
```

**Test manual endpoint:**
```bash
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "processors": ["YourNewProcessorProcessor"],
    "analysis_date": "2024-11-22"
  }'
```

---

## Common Mistakes

### 1. Forgot to Import Processor

**Error:**
```
NameError: name 'YourNewProcessorProcessor' is not defined
```

**Fix:** Add import at top of file:
```python
from data_processors.analytics.your_new_processor.your_new_processor_processor import YourNewProcessorProcessor
```

### 2. Wrong Processor Name in Manual Endpoint

**Error:**
```
KeyError: 'YourProcessor'
```

**Fix:** Processor name must EXACTLY match the class name:
```python
# In ANALYTICS_TRIGGERS
YourNewProcessorProcessor  # Class name

# In processor_map
'YourNewProcessorProcessor': YourNewProcessorProcessor  # EXACT match
```

### 3. Forgot to Deploy After Changes

**Symptom:** Processor doesn't run even though you added it

**Fix:** Always redeploy after changing registries:
```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
# or
./bin/precompute/deploy/deploy_precompute_processors.sh
```

### 4. Wrong Trigger Source

**Symptom:** Processor never runs automatically

**Problem:** Processor added to wrong source table in ANALYTICS_TRIGGERS

**Example:**
```python
# WRONG - processor needs bdl_player_boxscores but added to nbac_scoreboard_v2
ANALYTICS_TRIGGERS = {
    'nbac_scoreboard_v2': [YourNewProcessorProcessor],  # ❌ WRONG
}

# RIGHT
ANALYTICS_TRIGGERS = {
    'bdl_player_boxscores': [YourNewProcessorProcessor],  # ✅ CORRECT
}
```

**Fix:** Check what source table your processor reads from, add to correct trigger.

### 5. CASCADE Processor in PRECOMPUTE_TRIGGERS

**Problem:** CASCADE processor added to PRECOMPUTE_TRIGGERS instead of CASCADE_PROCESSORS

**Symptom:** Processor tries to run before all dependencies ready

**Fix:**
```python
# WRONG
PRECOMPUTE_TRIGGERS = {
    'some_table': [YourCascadeProcessor],  # ❌ Will fail - dependencies not ready
}

# RIGHT
CASCADE_PROCESSORS = {
    'your_cascade': YourCascadeProcessor,  # ✅ Scheduled, checks all deps
}
```

---

## Testing Checklist

Before considering your registration complete:

- [ ] Processor imported at top of service file
- [ ] Processor added to appropriate registry (ANALYTICS_TRIGGERS or PRECOMPUTE_TRIGGERS)
- [ ] Processor added to manual endpoint processor_map
- [ ] Changes deployed to Cloud Run
- [ ] Health check passes
- [ ] Manual endpoint test succeeds
- [ ] Pub/Sub trigger test succeeds (if applicable)
- [ ] Processor appears in Cloud Run logs
- [ ] Output data appears in BigQuery

---

## Real-World Example

### Adding UpcomingPlayerGameContextProcessor (2025-11-23)

**What we needed:**
- Run UpcomingPlayerGameContextProcessor when player boxscores arrive
- Enable manual testing via HTTP

**Changes made:**

#### 1. Import (line 19)
```python
from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
```

#### 2. ANALYTICS_TRIGGERS (line 29)
```python
ANALYTICS_TRIGGERS = {
    'bdl_player_boxscores': [
        PlayerGameSummaryProcessor,
        TeamOffenseGameSummaryProcessor,
        UpcomingPlayerGameContextProcessor,  # ADDED
    ],
}
```

#### 3. processor_map (line 174)
```python
processor_map = {
    'PlayerGameSummaryProcessor': PlayerGameSummaryProcessor,
    'TeamOffenseGameSummaryProcessor': TeamOffenseGameSummaryProcessor,
    'TeamDefenseGameSummaryProcessor': TeamDefenseGameSummaryProcessor,
    'UpcomingPlayerGameContextProcessor': UpcomingPlayerGameContextProcessor,  # ADDED
}
```

#### 4. Deploy
```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
# Deployed as revision 00004
```

#### 5. Test
```bash
# Manual test
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"processors": ["UpcomingPlayerGameContextProcessor"], "start_date": "2024-11-22", "end_date": "2024-11-22"}'

# Result: ✅ SUCCESS
```

---

## Troubleshooting

### Processor Doesn't Appear in Logs

**Check:**
1. Did you deploy? (`gcloud run services describe nba-phase3-analytics-processors`)
2. Is the source table name correct in ANALYTICS_TRIGGERS?
3. Is the Pub/Sub message formatted correctly?
4. Check for errors in Cloud Run logs

### "No processors configured for {source_table}"

**Problem:** Your source table isn't in the registry

**Fix:** Add it:
```python
ANALYTICS_TRIGGERS = {
    'your_source_table': [YourProcessor],  # Add this
}
```

### Processor Runs But Fails

**This is different from registration!** The processor is registered correctly, but has a bug.

**Check:**
- Processor code for errors
- Dependencies are met
- Completeness checking thresholds
- BigQuery table schemas match

---

## Best Practices

### 1. Test Locally First

Before adding to Pub/Sub registry, test processor locally:
```bash
python -m data_processors.analytics.your_processor.your_processor_processor 2024-11-22
```

### 2. Add to Manual Endpoint Always

Even if you only use Pub/Sub, add to manual endpoint for easier debugging.

### 3. Document Your Trigger

Update `docs/reference/04-processor-registry-reference.md` with your new processor.

### 4. One Processor, One PR

Don't add multiple processors in one deployment - makes rollback easier.

### 5. Monitor After Deployment

Watch logs for 24 hours after adding new processor:
```bash
gcloud run services logs read nba-phase3-analytics-processors \
  --region us-west2 \
  --follow
```

---

## Related Documentation

- **Processor Registry Reference:** `docs/reference/04-processor-registry-reference.md`
- **Deployment Status:** `docs/deployment/00-deployment-status.md`
- **Processor Development Guide:** `docs/guides/01-processor-development-guide.md`
- **Pub/Sub Integration:** `docs/infrastructure/01-pubsub-integration-verification.md`

---

## Quick Reference

**Phase 3 Service File:** `data_processors/analytics/main_analytics_service.py`
**Phase 4 Service File:** `data_processors/precompute/main_precompute_service.py`

**Deploy Phase 3:**
```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
```

**Deploy Phase 4:**
```bash
./bin/precompute/deploy/deploy_precompute_processors.sh
```

**Test Manual Endpoint:**
```bash
# Phase 3
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"processors": ["YourProcessor"], "start_date": "2024-11-22", "end_date": "2024-11-22"}'

# Phase 4
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"processors": ["YourProcessor"], "analysis_date": "2024-11-22"}'
```

---

**Document Status:** ✅ Current as of 2025-11-23
**Last Updated:** 2025-11-23 14:15:00 PST
**Maintained By:** NBA Platform Team
