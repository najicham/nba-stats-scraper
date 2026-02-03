# Phase 6 Enhancement - Action Plan
**Date:** 2026-02-03
**Based on:** Opus Review (Session 87) + Sonnet Analysis

## Status Summary

| Item | Status | Notes |
|------|--------|-------|
| Subset infrastructure | ✅ READY | All 9 subsets active, 173 days of data |
| Model attribution schema | ✅ READY | Fields exist in schema |
| Model attribution data | ✅ **FIXED** | prediction-worker deployed (rev 00081-z97) |
| View period_type column | ⚠️ ADJUST | Doesn't exist - use manual date filters |
| Session 81 alignment | ⚠️ UPDATE | Switch from confidence-based to edge-based tiers |

## Phase 0: Verify Model Attribution Fix ✅

**Status:** COMPLETED 2026-02-03
- ✅ Deployed prediction-worker with Session 84 code (commit 5002a7d1)
- ✅ New revision: `prediction-worker-00081-z97`
- ⏳ Waiting for next prediction run (overnight at 7 AM ET or 2:30 AM ET early run)

**Verification (after next run):**
```bash
# Check if model_file_name is populated (run after 7 AM ET)
bq query --use_legacy_sql=false "
SELECT model_file_name, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
GROUP BY model_file_name"

# Expected: catboost_v9_feb_02_retrain.cbm with ~140+ records
```

## Phase 1: Subset Exporters (3-4 days)

### Exporter 1: SubsetDefinitionsExporter
**Priority:** HIGH
**Path:** `data_processors/publishing/subset_definitions_exporter.py`
**Output:** `gs://nba-props-platform-api/v1/systems/subsets.json`
**Cache:** 24 hours

**Query:**
```sql
SELECT
  subset_id,
  subset_name,
  subset_description,
  system_id,
  use_ranking,
  top_n,
  min_edge,
  min_confidence,
  signal_condition,
  is_active,
  notes
FROM nba_predictions.dynamic_subset_definitions
WHERE is_active = TRUE
ORDER BY subset_id
```

**JSON Structure:** See `JSON_EXAMPLES.md` Section 1

---

### Exporter 2: DailySignalsExporter
**Priority:** HIGH
**Path:** `data_processors/publishing/daily_signals_exporter.py`
**Output:** `gs://nba-props-platform-api/v1/signals/{date}.json`
**Cache:** 5 minutes

**Query:**
```sql
SELECT
  game_date,
  system_id,
  total_picks,
  high_edge_picks,
  premium_picks,
  pct_over,
  pct_under,
  avg_confidence,
  avg_edge,
  skew_category,
  daily_signal,
  signal_explanation
FROM nba_predictions.daily_prediction_signals
WHERE game_date = @target_date
  AND system_id = 'catboost_v9'
```

**Historical export:** Last 7 days + today (8 dates total)

**JSON Structure:** See `JSON_EXAMPLES.md` Section 2

---

### Exporter 3: SubsetPicksExporter
**Priority:** HIGH
**Path:** `data_processors/publishing/subset_picks_exporter.py`
**Output:** `gs://nba-props-platform-api/v1/subsets/{subset_id}/{date}.json`
**Cache:** 5 minutes

**Implementation notes:**
- Create one file per subset per date (9 files/day)
- Query predictions + apply subset filters dynamically
- Join with daily_prediction_signals for signal context
- Calculate composite_score: `(edge * 10) + (confidence * 0.5)`
- Rank picks if subset uses ranking strategy

**Query pattern:**
```sql
-- Get subset definition
SELECT * FROM nba_predictions.dynamic_subset_definitions
WHERE subset_id = @subset_id

-- Get predictions matching subset criteria
SELECT
  p.*,
  (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) as composite_score,
  s.daily_signal,
  s.pct_over
FROM nba_predictions.player_prop_predictions p
LEFT JOIN nba_predictions.daily_prediction_signals s
  ON p.game_date = s.game_date AND p.system_id = s.system_id
WHERE p.game_date = @target_date
  AND p.system_id = 'catboost_v9'
  AND p.is_active = TRUE
  AND p.recommendation IN ('OVER', 'UNDER')  -- CRITICAL: Exclude PASS
  AND ABS(p.predicted_points - p.current_points_line) >= 5  -- High edge filter
ORDER BY composite_score DESC
LIMIT 5  -- If top_n = 5
```

**JSON Structure:** See `JSON_EXAMPLES.md` Section 3

---

### Exporter 4: SubsetPerformanceExporter
**Priority:** MEDIUM
**Path:** `data_processors/publishing/subset_performance_exporter.py`
**Output:** `gs://nba-props-platform-api/v1/subsets/performance.json`
**Cache:** 1 hour

**Query (corrected for no period_type column):**
```sql
-- Last 7 days
SELECT
  subset_id,
  subset_name,
  SUM(graded_picks) as total_picks,
  SUM(wins) as total_wins,
  ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as hit_rate,
  ROUND(AVG(avg_edge), 1) as avg_edge,
  ROUND(AVG(avg_confidence), 3) as avg_confidence,
  ROUND(SUM(CASE WHEN wins > 0 THEN wins * 0.909 ELSE -(graded_picks - wins) END), 1) as profit_units,
  ROUND(100.0 * SUM(CASE WHEN wins > 0 THEN wins * 0.909 ELSE -(graded_picks - wins) END) / NULLIF(SUM(graded_picks), 0), 1) as roi_pct
FROM nba_predictions.v_dynamic_subset_performance
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY subset_id, subset_name
ORDER BY hit_rate DESC

-- Repeat for 30 days and season (change date filter)
```

**Signal breakdown query:**
```sql
-- Performance by signal color
SELECT
  subset_id,
  daily_signal,
  SUM(graded_picks) as picks,
  ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as hit_rate,
  ROUND(AVG(avg_edge), 1) as avg_edge
FROM nba_predictions.v_dynamic_subset_performance
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY subset_id, daily_signal
```

**JSON Structure:** See `JSON_EXAMPLES.md` Section 4

---

## Phase 2: Model Attribution Exporters (2-3 days)

**DEPENDS ON:** Phase 0 verification (model fields populated)

### Exporter 5: ModelRegistryExporter
**Priority:** MEDIUM
**Path:** `data_processors/publishing/model_registry_exporter.py`
**Output:** `gs://nba-props-platform-api/v1/systems/models.json`
**Cache:** 24 hours

**Data sources:**
1. Code: `predictions/worker/prediction_systems/catboost_v9.py` TRAINING_INFO dict
2. BigQuery: Recent predictions for deployment tracking

**Query:**
```sql
SELECT DISTINCT
  system_id,
  model_file_name,
  model_training_start_date,
  model_training_end_date,
  model_expected_mae,
  model_expected_hit_rate,
  model_trained_at
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
  AND model_file_name IS NOT NULL
ORDER BY model_trained_at DESC
```

**Implementation:**
- Read TRAINING_INFO from Python modules dynamically
- Merge with BigQuery deployment data
- Format as JSON per `JSON_EXAMPLES.md` Section 7

---

### Modification 1: Enhance SystemPerformanceExporter
**Path:** `data_processors/publishing/system_performance_exporter.py`
**Output:** `gs://nba-props-platform-api/v1/systems/performance.json` (existing)

**Add to existing structure:**
1. `model_info` section with file name, training dates, expected performance
2. `tier_breakdown` with edge-based quality tiers (Session 81)

**Query additions:**
```sql
-- Model metadata (add to existing query)
SELECT DISTINCT
  model_file_name,
  model_trained_at,
  model_expected_mae,
  model_expected_hit_rate
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 1
  AND system_id = 'catboost_v9'
  AND model_file_name IS NOT NULL

-- Tier breakdown (NEW - Session 81 edge-based)
SELECT
  CASE
    WHEN ABS(predicted_points - line_value) >= 5 THEN 'High Quality (5+ edge)'
    WHEN ABS(predicted_points - line_value) >= 3 THEN 'Medium Quality (3-5 edge)'
    ELSE 'Low Quality (<3 edge)'
  END as tier,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - line_value)), 1) as avg_edge,
  ROUND(AVG(ABS(predicted_points - actual_points)), 1) as mae,
  ROUND(SUM(CASE WHEN prediction_correct THEN 0.909 ELSE -1.0 END) / COUNT(*) * 100, 1) as roi_pct
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND recommendation IN ('OVER', 'UNDER')  -- Exclude PASS
  AND prediction_correct IS NOT NULL
GROUP BY tier
ORDER BY MIN(ABS(predicted_points - line_value)) DESC
```

**JSON Structure:** See `JSON_EXAMPLES.md` Section 5

---

### Modification 2: Add Model Attribution to PredictionsExporter
**Path:** `data_processors/publishing/predictions_exporter.py`
**Output:** `gs://nba-props-platform-api/v1/predictions/{date}.json` (existing)

**Change:** Add `model_attribution` object to each prediction

**Fields to include:**
- model_file_name
- model_training_start_date
- model_training_end_date
- model_expected_mae
- model_expected_hit_rate
- model_trained_at
- build_commit_sha
- deployment_revision

**JSON Structure:** See `JSON_EXAMPLES.md` Section 6

---

### Modification 3: Add Model Attribution to BestBetsExporter
**Path:** `data_processors/publishing/best_bets_exporter.py`
**Output:** `gs://nba-props-platform-api/v1/best-bets/{date}.json` (existing)

**Change:** Same as PredictionsExporter - add `model_attribution` to each pick

---

## Integration & Orchestration

### Update daily_export.py
**Path:** `backfill_jobs/publishing/daily_export.py`

**Add to EXPORT_TYPES:**
```python
EXPORT_TYPES = {
    # ... existing exporters ...
    'subset_definitions': SubsetDefinitionsExporter,
    'daily_signals': DailySignalsExporter,
    'subset_picks': SubsetPicksExporter,
    'subset_performance': SubsetPerformanceExporter,
    'model_registry': ModelRegistryExporter,
}

# Add to TONIGHT_EXPORT_TYPES (event-driven after Phase 5)
TONIGHT_EXPORT_TYPES = [
    # ... existing ...
    'daily_signals',  # Today's signal
    'subset_picks',   # Today's subset picks
]

# Add to DAILY_EXPORT_TYPES (scheduled 5 AM)
DAILY_EXPORT_TYPES = [
    # ... existing ...
    'subset_definitions',  # Once daily
    'subset_performance',  # Daily rollup
    'model_registry',      # Track model versions
]
```

**Update export_date() function:**
```python
def export_date(date_str: str, export_types: List[str]) -> Dict[str, Any]:
    # ... existing logic ...

    # NEW: Export subset picks for all 9 subsets
    if 'subset_picks' in export_types:
        subset_ids = [
            'v9_high_edge_top1', 'v9_high_edge_top3', 'v9_high_edge_top5',
            'v9_high_edge_top10', 'v9_high_edge_balanced', 'v9_high_edge_any',
            'v9_high_edge_warning', 'v9_premium_safe', 'v9_high_edge_top5_balanced'
        ]
        for subset_id in subset_ids:
            exporter = SubsetPicksExporter(subset_id=subset_id)
            results['subset_picks'][subset_id] = exporter.export(date_str)

    # NEW: Export daily signals (today + last 7 days for history)
    if 'daily_signals' in export_types:
        for days_back in range(8):  # 0-7 days back
            signal_date = (datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=days_back)).strftime('%Y-%m-%d')
            exporter = DailySignalsExporter()
            results['daily_signals'][signal_date] = exporter.export(signal_date)
```

---

## Testing Plan

### Unit Tests
**Path:** `tests/unit/test_phase6_exporters.py`

```python
def test_subset_definitions_exporter():
    exporter = SubsetDefinitionsExporter()
    result = exporter.generate_json()

    assert 'subsets' in result
    assert len(result['subsets']) == 9
    assert all(s['is_active'] for s in result['subsets'])
    assert all('subset_id' in s for s in result['subsets'])

def test_daily_signals_exporter():
    exporter = DailySignalsExporter()
    result = exporter.generate_json('2026-02-02')

    assert 'daily_signal' in result
    assert result['daily_signal'] in ['GREEN', 'YELLOW', 'RED']
    assert 'pct_over' in result
    assert 0 <= result['pct_over'] <= 100

def test_subset_picks_exporter():
    exporter = SubsetPicksExporter(subset_id='v9_high_edge_top5')
    result = exporter.generate_json('2026-02-02')

    assert 'picks' in result
    assert len(result['picks']) <= 5  # top_n = 5
    if result['picks']:
        assert 'composite_score' in result['picks'][0]
        assert 'rank' in result['picks'][0]
```

### Integration Tests
**Run after deployment:**

```bash
# 1. Verify subset definitions
gsutil cat gs://nba-props-platform-api/v1/systems/subsets.json | \
  jq '.subsets | length'
# Expected: 9

# 2. Verify today's signal
gsutil cat gs://nba-props-platform-api/v1/signals/$(date +%Y-%m-%d).json | \
  jq '.daily_signal'
# Expected: "GREEN", "YELLOW", or "RED"

# 3. Verify subset picks exist
gsutil ls gs://nba-props-platform-api/v1/subsets/v9_high_edge_top5/*.json | wc -l
# Expected: 1+ files

# 4. Verify model attribution populated (after Phase 0 verification)
gsutil cat gs://nba-props-platform-api/v1/predictions/$(date +%Y-%m-%d).json | \
  jq '.predictions[0].model_attribution.model_file_name'
# Expected: "catboost_v9_feb_02_retrain.cbm"

# 5. Verify performance has tier breakdown
gsutil cat gs://nba-props-platform-api/v1/systems/performance.json | \
  jq '.systems[] | select(.system_id == "catboost_v9") | .tier_breakdown'
# Expected: Object with high_quality, medium_quality, all_predictions
```

---

## Deployment Sequence

### Step 1: Phase 0 Verification (NEXT)
**Date:** 2026-02-03 (after 7 AM ET prediction run)

```bash
# Verify model attribution fields populated
bq query --use_legacy_sql=false "
SELECT model_file_name, COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
GROUP BY model_file_name"

# Expected: catboost_v9_feb_02_retrain.cbm with count > 0
# If NULL, wait for next run or investigate logs
```

**If verification fails:** Check prediction-worker logs for errors.

---

### Step 2: Implement Phase 1 Exporters
**Date:** 2026-02-03 to 2026-02-05
**Estimated time:** 3-4 days

**Order:**
1. SubsetDefinitionsExporter (simplest, no date parameter)
2. DailySignalsExporter (simple query, date-based)
3. SubsetPerformanceExporter (aggregation logic)
4. SubsetPicksExporter (most complex, multiple subsets)

**Each exporter:**
1. Create class file
2. Write generate_json() method
3. Add unit test
4. Test locally with sample date
5. Commit

---

### Step 3: Deploy Phase 1
**Date:** 2026-02-05

```bash
# Add to orchestration
git add data_processors/publishing/*_exporter.py
git add backfill_jobs/publishing/daily_export.py
git commit -m "feat: Add Phase 6 subset exporters"

# Deploy Cloud Function (if orchestration changed)
gcloud functions deploy phase6-export \
  --source orchestration/cloud_functions/phase6_export \
  --runtime python311 \
  --region us-west2

# Or run manual export to test
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
  --date $(date +%Y-%m-%d) \
  --types subset_definitions,daily_signals,subset_picks,subset_performance
```

---

### Step 4: Verify Phase 1 (2026-02-05)

Run integration tests (see above) and check:
- [ ] All 9 subset files created
- [ ] Signal files for last 8 days exist
- [ ] Performance JSON has all subsets
- [ ] Hit rates match database (79-82% for top subsets)
- [ ] No errors in Cloud Function logs

---

### Step 5: Implement Phase 2 Exporters
**Date:** 2026-02-05 to 2026-02-06
**Estimated time:** 2-3 days

**Order:**
1. ModelRegistryExporter (new, standalone)
2. Modify SystemPerformanceExporter (add sections)
3. Modify PredictionsExporter (add attribution)
4. Modify BestBetsExporter (add attribution)

**Prerequisite:** Phase 0 verification must pass (model fields populated)

---

### Step 6: Deploy Phase 2
**Date:** 2026-02-06

```bash
# Commit changes
git add data_processors/publishing/*
git commit -m "feat: Add Phase 6 model attribution exports"

# Deploy
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
  --date $(date +%Y-%m-%d) \
  --types model_registry

# Verify
gsutil cat gs://nba-props-platform-api/v1/systems/models.json | \
  jq '.models[] | select(.system_id == "catboost_v9")'
```

---

### Step 7: Monitor First Week
**Date:** 2026-02-06 to 2026-02-13

**Daily checks:**
```bash
# 1. Export success rate
gcloud logging read 'resource.type="cloud_function"
  AND resource.labels.function_name="phase6-export"
  AND severity>=ERROR' \
  --limit=20 --freshness=1d

# 2. GCS file counts
gsutil ls -r gs://nba-props-platform-api/v1/subsets/ | wc -l
# Expect: 9 subsets × 8 days = 72+ files

# 3. Hit rate sanity check
gsutil cat gs://nba-props-platform-api/v1/subsets/performance.json | \
  jq '.performance_windows.last_7_days.subsets[] | select(.subset_id == "v9_high_edge_balanced") | .hit_rate'
# Expect: 75-85%
```

---

## Success Criteria

### Phase 1 Success
- [ ] All 9 subset files export daily
- [ ] Signal data matches BigQuery source
- [ ] Performance metrics accurate (verified vs direct BQ query)
- [ ] Exports complete within 5 minutes
- [ ] No BigQuery quota errors
- [ ] Cache headers set correctly

### Phase 2 Success
- [ ] Model registry shows current deployment
- [ ] All predictions have model_attribution populated
- [ ] System performance has tier_breakdown
- [ ] Tier breakdown uses Session 81 edge-based filters
- [ ] All fields match TRAINING_INFO dict

### Overall Success
- [ ] Website can query all new endpoints
- [ ] JSON structure validated against examples
- [ ] No breaking changes to existing endpoints
- [ ] Circuit breaker doesn't trip
- [ ] Firestore heartbeats working

---

## Rollback Procedures

### If Phase 1 Fails
```bash
# Disable new exporters in orchestration
# Edit backfill_jobs/publishing/daily_export.py
# Comment out new EXPORT_TYPES entries
git commit -m "fix: Disable subset exporters temporarily"

# Redeploy
gcloud functions deploy phase6-export --source=...
```

### If Phase 2 Fails
```bash
# Revert exporter modifications
git checkout HEAD~1 -- data_processors/publishing/system_performance_exporter.py
git checkout HEAD~1 -- data_processors/publishing/predictions_exporter.py
git checkout HEAD~1 -- data_processors/publishing/best_bets_exporter.py
git commit -m "fix: Revert model attribution exports"
```

---

## Documentation Updates

After successful deployment:
1. Update `CLAUDE.md` with new endpoint references
2. Create Phase 6 subset runbook in `docs/02-operations/`
3. Update API documentation for frontend team
4. Session handoff with implementation notes

---

## Estimated Timeline

| Phase | Duration | Start | End |
|-------|----------|-------|-----|
| Phase 0 Verification | 1 day | 2026-02-03 | 2026-02-03 |
| Phase 1 Implementation | 3-4 days | 2026-02-03 | 2026-02-05 |
| Phase 1 Deployment | 1 day | 2026-02-05 | 2026-02-05 |
| Phase 2 Implementation | 2-3 days | 2026-02-05 | 2026-02-06 |
| Phase 2 Deployment | 1 day | 2026-02-06 | 2026-02-06 |
| Monitoring Period | 7 days | 2026-02-06 | 2026-02-13 |

**Total:** 13-17 days (2-3 weeks)
