# BigDataBall (BDB) Data Strategy & Reprocessing

**Created**: 2026-01-31
**Status**: ✅ Phase 1 Complete - Production Ready (Partial)
**Priority**: P1 - Critical for prediction quality
**Last Updated**: 2026-01-31 (Implementation Complete)

## Executive Summary

BigDataBall (BDB) play-by-play data is the **primary source** for shot zone features (#3 most important feature at 11% importance). When BDB data arrives late (45+ hours after games), the system currently re-runs Phase 3-4 but **NOT Phase 5 predictions**, leaving production predictions using degraded features.

**Key Finding**: Shot zone features provide **+2.3% accuracy** and **-0.96 MAE** improvement when present vs absent. While modest individually, they're part of the cumulative model quality that achieves production targets.

**Critical Gap**: 48 games from Jan 17-24 were processed with NBAC fallback or no shot zones. When BDB data arrives, predictions are NOT regenerated, leaving stale predictions in production.

---

## Problem Statement

### Current State Issues

1. **BDB Coverage Gaps** (Jan 17-24, 2026)
   - 0% coverage for Jan 17-19 (24 games)
   - 14-57% coverage for Jan 20-24 (44 games)
   - Total: **48 games** missing complete BDB data

2. **Incomplete Reprocessing Pipeline**
   - ✅ Phase 1: BDB catch-up workflows run 3x daily
   - ✅ Phase 2-4: Data flows and reprocesses correctly
   - ❌ **Phase 5: Predictions NOT regenerated** when upstream features change

3. **No Prediction Superseding**
   - Old predictions (made with NBAC fallback) remain in production
   - New BDB-enhanced features exist but aren't used
   - No mechanism to mark old predictions as "superseded"

### Impact

| Metric | Without BDB | With BDB | Difference |
|--------|-------------|----------|------------|
| Hit Rate | 36.3% | 38.6% | **+2.3%** |
| Mean Absolute Error | 6.21 | 5.25 | **-0.96** |
| Quality Tier | SILVER/BRONZE | GOLD | 2 tiers |
| Feature Completeness | ~70% | ~95% | +25% |

---

## BDB vs NBAC: Feature Comparison

### What BDB Provides That NBAC Doesn't

| Category | Features | Importance |
|----------|----------|------------|
| **Shot Coordinates** | original_x/y, converted_x/y, precise shot_distance | Enables heat maps, zone validation |
| **Shot Creation** | Assisted FG, unassisted FG | 11% feature importance (#3 overall) |
| **And-1 Tracking** | Made shot + shooting foul counts | Momentum metrics, FT volume |
| **Blocks by Zone** | Paint/mid/three blocks (blocker perspective) | Defensive range analysis |
| **Lineup Data** | Full 10-player lineups | On/off-court analysis |
| **Rich Timing** | elapsed_time, play_length | Fatigue modeling, game flow |

### Feature Availability Matrix

| Feature Set | BDB | NBAC Fallback | Neither |
|-------------|-----|---------------|---------|
| Basic shot zones (paint/mid/three) | ✅ | ✅ | ❌ |
| Shot coordinates | ✅ | ❌ | ❌ |
| Assisted/unassisted | ✅ | ❌ | ❌ |
| And-1 counts | ✅ | ❌ | ❌ |
| Blocks by zone | ✅ | ❌ | ❌ |
| Full lineups | ✅ | ❌ | ❌ |
| Rich timing | ✅ | ❌ | ❌ |

**Quality Tiers**:
- **GOLD** (95-100): BDB available, all zones complete
- **SILVER** (70-94): NBAC fallback, basic zones only
- **BRONZE** (<70): No shot zone data

---

## Current Reprocessing Flow

### What Works ✅

```
BDB Data Arrives Late (45+ hours)
    ↓
[Phase 1] bdl_catchup_midday/afternoon/evening (10 AM, 2 PM, 6 PM ET)
    ├─ Detects Final games missing BDL data (lookback: 3 days)
    └─ Triggers BDL scraper retry
    ↓
[Phase 2] nba_raw.bdl_player_boxscores updated (MERGE strategy)
    ↓
[Phase 3] player_game_summary detects hash change
    ├─ Re-runs extraction with new BDB data
    └─ MERGE_UPDATE strategy (replaces matching records)
    ↓
[Phase 4] All precompute processors re-run
    ├─ player_shot_zone_analysis (shot effectiveness zones)
    ├─ player_composite_factors (multi-factor metrics)
    ├─ player_daily_cache (fast lookup cache)
    └─ ml_feature_store_v2 (33+ ML features) ← CRITICAL
    ↓
[Phase 4→5 Orchestrator] Detects Phase 4 completion
    └─ Triggers prediction coordinator
```

### What's Broken ❌

```
[Phase 5] Prediction Coordinator
    ├─ Receives trigger from Phase 4→5 orchestrator
    ├─ Generates predictions for TODAY'S games ONLY
    └─ ❌ Does NOT re-generate for games with late-arriving BDB data
    ↓
Result: Production predictions use stale features from NBAC fallback
```

---

## Root Cause Analysis

### Why Predictions Aren't Regenerated

1. **Coordinator Logic** (`predictions/coordinator/coordinator.py`)
   - Only processes `CURRENT_DATE` games
   - No concept of "feature version changed, re-run historical"

2. **Missing Prediction Detector** (`missing_prediction_detector.py`)
   - Only checks for missing predictions TODAY
   - Doesn't compare feature versions to detect superseding

3. **No Deletion/Replacement Logic**
   - Predictions are append-only
   - No "mark as superseded" functionality
   - No cleanup of old predictions

4. **No Cost Optimization**
   - Could batch-reprocess multiple affected dates
   - Currently would require manual intervention per date

---

## Proposed Solution

### Strategy: Automatic BDB Reprocessing with Prediction Regeneration

**Goal**: When BDB data arrives late, automatically trigger full pipeline reprocessing including prediction regeneration with superseding logic.

### Architecture

```
┌─────────────────────────────────────────────────┐
│ BDB Retry Processor (NEW - Session 53)         │
│ ───────────────────────────────────────────────│
│ 1. Detect BDB data availability (hourly)       │
│ 2. Trigger Phase 3 re-run ✅                   │
│ 3. Trigger Phase 4 re-run ✅                   │
│ 4. Trigger Phase 5 re-run ✅ NEW               │
│ 5. Mark old predictions as superseded ✅ NEW   │
└─────────────────────────────────────────────────┘
```

### Implementation Plan

#### Phase 1: Extend BDB Retry Processor (IMMEDIATE)

**File**: `bin/monitoring/bdb_retry_processor.py`

**Enhancement**:
```python
def trigger_full_reprocessing_pipeline(self, game: Dict) -> bool:
    """
    Trigger complete re-processing when BDB data arrives.

    Steps:
    1. Phase 3: player_game_summary (already implemented)
    2. Phase 4: precompute processors (NEW)
    3. Phase 5: re-generate predictions (NEW)
    4. Supersede: Mark old predictions (NEW)
    """
    game_date = game['game_date']
    game_id = game['game_id']

    # Step 1: Phase 3 (already implemented)
    self.trigger_phase3_rerun(game)

    # Step 2: Phase 4 reprocessing
    self.publisher.publish('nba-phase4-trigger', {
        'game_date': game_date,
        'reason': 'bdb_data_available',
        'processors': [
            'player_shot_zone_analysis',
            'player_composite_factors',
            'ml_feature_store'
        ],
        'mode': 'reprocess_specific_date'
    })

    # Step 3: Phase 5 prediction regeneration
    self.publisher.publish('nba-prediction-trigger', {
        'game_date': game_date,
        'reason': 'bdb_upgrade',
        'mode': 'regenerate_with_supersede',
        'metadata': {
            'original_source': game.get('fallback_source'),
            'upgrade_from': 'nbac_fallback',
            'upgrade_to': 'bigdataball',
            'trigger_type': 'bdb_retry_processor'
        }
    })

    # Step 4: Mark old predictions as superseded
    self._mark_predictions_superseded(game_date, game_id)

    return True
```

#### Phase 2: Add Prediction Superseding Logic (HIGH PRIORITY)

**File**: `predictions/coordinator/coordinator.py`

**New Endpoint**: `/regenerate-with-supersede`
```python
@app.route('/regenerate-with-supersede', methods=['POST'])
def regenerate_with_supersede():
    """
    Regenerate predictions and mark old ones as superseded.

    Request body:
    {
        "game_date": "2026-01-17",
        "reason": "bdb_upgrade",
        "metadata": {...}
    }
    """
    data = request.json
    game_date = data['game_date']

    # 1. Mark existing predictions as superseded
    update_query = f"""
    UPDATE `{PROJECT}.nba_predictions.player_prop_predictions`
    SET superseded = TRUE,
        superseded_at = CURRENT_TIMESTAMP(),
        superseded_reason = '{data['reason']}'
    WHERE game_date = '{game_date}'
      AND superseded = FALSE
    """
    bq_client.query(update_query).result()

    # 2. Generate new predictions
    result = generate_predictions_for_date(game_date)

    # 3. Track in audit log
    log_prediction_regeneration(game_date, data['metadata'])

    return jsonify({
        'status': 'success',
        'game_date': game_date,
        'superseded_count': result['superseded'],
        'regenerated_count': result['new_predictions']
    })
```

#### Phase 3: Schema Enhancement (MEDIUM PRIORITY)

**Table**: `nba_predictions.player_prop_predictions`

```sql
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS superseded BOOL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS superseded_reason STRING,
ADD COLUMN IF NOT EXISTS superseded_by_prediction_id STRING,
ADD COLUMN IF NOT EXISTS feature_version_hash STRING,
ADD COLUMN IF NOT EXISTS data_source_tier STRING;  -- GOLD/SILVER/BRONZE
```

**Table**: `nba_predictions.prediction_accuracy`

```sql
ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN IF NOT EXISTS shot_zones_source STRING,
ADD COLUMN IF NOT EXISTS data_quality_tier STRING,
ADD COLUMN IF NOT EXISTS feature_completeness_pct FLOAT64,
ADD COLUMN IF NOT EXISTS bdb_available_at_prediction BOOL;
```

#### Phase 4: Feature Version Tracking (LOW PRIORITY)

**File**: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Enhancement**: Add version hash to each feature store record
```python
def _calculate_feature_version_hash(self, features: Dict) -> str:
    """
    Calculate hash of source data versions that contributed to features.

    Components:
    - player_game_summary.updated_at hash
    - shot_zones_source ('bigdataball_pbp' vs 'nbac_play_by_play')
    - Data quality tier
    """
    hash_components = [
        features.get('shot_zones_source', 'unknown'),
        features.get('data_quality_tier', 'bronze'),
        str(features.get('source_shot_zones_last_updated')),
        str(features.get('source_boxscore_last_updated'))
    ]
    return hashlib.md5('|'.join(hash_components).encode()).hexdigest()
```

---

## Cost-Benefit Analysis

### Costs of Implementing Full Reprocessing

| Component | Cost Type | Estimate |
|-----------|-----------|----------|
| **Development** | Engineering time | 2-3 days |
| **BigQuery** | Additional queries | ~$5-10/month |
| **Compute** | Prediction regeneration | ~$2-5/regeneration batch |
| **Storage** | Superseded predictions | Minimal (soft delete) |

**Total Monthly**: ~$15-25 (assuming 2-3 BDB reprocessing events/month)

### Benefits

| Benefit | Impact | Value |
|---------|--------|-------|
| **Accuracy Improvement** | +2.3% hit rate | Higher user satisfaction |
| **MAE Reduction** | -0.96 MAE | Better prediction precision |
| **Quality Tier** | SILVER → GOLD | Consistent production quality |
| **Feature Completeness** | +25% completeness | Full model capability |
| **User Trust** | Consistent quality | Reduced churn |

**ROI**: **High** - $15-25/month cost for measurable accuracy improvement

---

## Implementation Roadmap

### Week 1: Foundation (IMMEDIATE) - ✅ COMPLETE

- [x] ✅ Create BDB retry processor (Session 53)
- [x] ✅ Implement pending_bdb_games tracking
- [x] ✅ Add Phase 3 reprocessing trigger
- [x] ✅ Extend to trigger Phase 4-5 pipeline
- [x] ✅ Add basic prediction superseding
- [x] ✅ Schema migrations (13 columns + 1 audit table)
- [x] ✅ Coordinator endpoint for superseding

**See**: [IMPLEMENTATION-LOG.md](./IMPLEMENTATION-LOG.md) for complete details

### Week 2: Production Deployment (HIGH PRIORITY) - 🚧 IN PROGRESS

- [x] ✅ Add superseded columns to predictions table (DONE)
- [x] ✅ Add source tracking to grading table (DONE)
- [x] ✅ Create prediction audit log writer (DONE)
- [ ] ⚠️ Verify/create Pub/Sub topic `nba-prediction-trigger`
- [ ] ⚠️ Deploy coordinator with new endpoint
- [ ] ⚠️ Implement actual prediction regeneration logic
- [ ] ⚠️ End-to-end integration test

### Week 3: Analysis & Calibration (MEDIUM PRIORITY)

- [ ] Backfill source columns for Jan 2026 predictions
- [ ] Analyze BDB vs NBAC accuracy differences
- [ ] Calibrate confidence penalties if needed
- [ ] Create BDB coverage dashboard

### Week 4: Automation & Monitoring (LOW PRIORITY)

- [ ] Schedule BDB retry processor (hourly)
- [ ] Add alerts for stuck retries (>24 hours)
- [ ] Create weekly BDB quality report
- [ ] Document runbooks for manual intervention

---

## Success Metrics

### Technical Metrics

- **BDB Coverage**: ≥80% of games within 12 hours
- **Retry Success Rate**: ≥95% of pending games resolved within 3 days
- **Reprocessing Latency**: <6 hours from BDB arrival to new predictions
- **Superseding Accuracy**: 100% of old predictions marked

### Business Metrics

- **Prediction Quality**: GOLD tier ≥80% of predictions
- **Accuracy Improvement**: +2-3% hit rate vs NBAC-only baseline
- **User Impact**: Reduced complaints about "inconsistent quality"

---

## Testing Strategy

### Scenario 1: Historical Jan 17-24 Reprocessing

**Goal**: Validate full pipeline with real late-arriving BDB data

**Steps**:
1. Manually trigger retry for Jan 17 (known NBAC fallback day)
2. Verify Phase 3 reprocesses with BDB
3. Verify Phase 4 updates features
4. Verify Phase 5 regenerates predictions
5. Verify old predictions marked superseded
6. Compare old vs new accuracy

**Expected**: +2-3% accuracy improvement

### Scenario 2: Future Late BDB Data

**Goal**: Test automatic pipeline on next BDB delay

**Steps**:
1. Wait for natural BDB delay (West Coast games often 24+ hours)
2. Monitor BDB retry processor logs
3. Verify automatic trigger of full pipeline
4. Verify superseding logic
5. Measure end-to-end latency

**Expected**: <6 hours BDB arrival → new predictions in production

---

## Risks & Mitigation

### Risk 1: Cost Overrun

**Risk**: Frequent reprocessing increases BigQuery costs

**Mitigation**:
- Batch reprocess multiple dates together
- Use query caching where possible
- Set max retries per game (72 checks = 3 days)

### Risk 2: Prediction Churn

**Risk**: Users see predictions change after initial publication

**Mitigation**:
- Only regenerate if quality tier improves (SILVER → GOLD)
- Add "updated" flag in UI
- Don't regenerate after game starts

### Risk 3: Feature Version Conflicts

**Risk**: Multiple feature versions for same game create confusion

**Mitigation**:
- Use feature_version_hash to detect changes
- Only supersede if hash changed significantly
- Keep superseded predictions for audit trail

---

## Open Questions

1. **Should we regenerate predictions after games start?**
   - Leaning NO - only pre-game predictions should be updated
   - Post-game accuracy grading uses prediction at game start

2. **How long to keep superseded predictions?**
   - Leaning 30 days for audit, then delete
   - Or keep forever for analysis (storage is cheap)

3. **Should we alert users when predictions change?**
   - Leaning NO - silent upgrade maintains trust
   - But add "Last updated" timestamp in UI

4. **What about Vegas line changes?**
   - Out of scope for BDB project
   - Vegas changes are separate reprocessing trigger

---

## Related Documentation

- `/docs/09-handoff/2026-01-31-SESSION-53-BDB-RETRY-SYSTEM-HANDOFF.md` - BDB retry system implementation
- `/docs/09-handoff/2026-01-31-DOWNSTREAM-DATA-QUALITY-TRACKING.md` - Downstream data quality analysis
- `/docs/08-projects/current/shot-zone-data-quality/INVESTIGATION-AND-FIX-PLAN.md` - Shot zone data investigation
- `/docs/09-handoff/2026-01-31-SHOT-ZONE-DATA-INVESTIGATION.md` - Detailed shot zone analysis

---

**Next Steps**:
1. Review and approve this strategy
2. Prioritize Week 1 tasks (extend retry processor)
3. Test with Jan 17-24 historical backfill
4. Monitor first automatic reprocessing event

**Owner**: TBD
**Status**: Draft - Ready for Review
**Last Updated**: 2026-01-31
