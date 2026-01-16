# MLB Pre-Season Checklist & Technical Roadmap

**Created**: 2026-01-15 (Session 63)
**Updated**: 2026-01-16 (Session 64)
**Target**: MLB Opening Day (Late March 2026)

---

## Executive Summary

The MLB batter/pitcher props system is **90% production-ready**. Core infrastructure (scrapers, processors, BigQuery tables) is complete. BettingPros live scraper integrated and aligned with processor. Remaining work is E2E testing and deployment.

---

## Current State (As of 2026-01-16)

### Data Pipeline Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Scrapers** | ✅ Complete | ODDS API + BettingPros (live + historical) |
| **Processors** | ✅ Complete | All use ProcessorBase correctly |
| **BigQuery Tables** | ✅ Complete | `oddsa_batter_props`, `bp_batter_props`, `bp_pitcher_props` |
| **Historical Backfill** | ✅ Complete | 635K ODDS API + 775K BettingPros batter props loaded |
| **BettingPros Live Scraper** | ✅ Integrated | `bp_mlb_player_props` - aligned with processor format |
| **Output Validation Table** | ✅ Created | `mlb_orchestration.processor_output_validation` |
| **MLB Error Patterns** | ✅ Added | rainout, postponed, doubleheader patterns |
| **Shadow Mode** | ✅ Fixed | Threshold-free for maximum data collection |
| **V1.6 Model** | ✅ Validated | 69.9% accuracy (12% better than V1.4) |
| **Scheduler Jobs** | ✅ Configured | 11 jobs paused, ready to enable |

### Data Coverage

| Source | Date Range | Records |
|--------|------------|---------|
| **BettingPros Pitcher** | Apr 2022 - Sep 2025 | ~30K props |
| **BettingPros Batter** | Apr 2022 - Sep 2025 | 775K props |
| **ODDS API Batter** | Apr 2024 - Sep 2025 | 635K props |
| **ODDS API Pitcher** | Apr 2024 - Sep 2025 | ~200K props |

### BettingPros Integration (Session 64)

**Scraper**: `scrapers/bettingpros/bp_mlb_player_props.py`
- Registered in `scrapers/registry.py` as `bp_mlb_player_props`
- Uses same API as historical backfill (`/v3/props`)
- Custom `transform_data()` produces format matching processor expectations
- GCS output: `bettingpros-mlb/{market_name}/{date}/props.json`

**Processor**: `data_processors/raw/mlb/mlb_bp_historical_props_processor.py`
- Handles both historical and live data (same format)
- Deduplication via `source_file_path`
- Writes to `mlb_raw.bp_pitcher_props` and `mlb_raw.bp_batter_props`

---

## CRITICAL: Must Complete Before Season (5 hours remaining)

### 1. ~~Verify Output Validation Table~~ ✅ DONE (Session 64)
**Completed**: 2026-01-16
- Created `mlb_orchestration.processor_output_validation` from NBA template
- 7000 rows copied

---

### 2. ~~Add MLB-Specific Error Patterns~~ ✅ DONE (Session 64)
**Completed**: 2026-01-16
- Added to `data_processors/raw/processor_base.py` in `_categorize_failure()`:
  - `postponed`, `rainout`, `weather delay`
  - `no props available`, `lines not posted`
  - `doubleheader`, `split admission`

---

### 3. Deploy MLB Prediction Worker (1 hour)
**Risk**: Shadow mode fixes not in production

```bash
# Deploy with Session 63 fixes
./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh

# Verify deployment
curl -X POST https://mlb-prediction-worker-xxx.run.app/health
```

**Why**: Picks up shadow mode fixes (missing features, threshold removal).

---

### 4. E2E Pipeline Test (4 hours)
**Risk**: Unknown production issues

```bash
# Run full pipeline replay
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28

# Verify outputs
# - Predictions appear in mlb_predictions.pitcher_strikeouts
# - Shadow mode comparison in mlb_predictions.shadow_model_comparison
# - Exports generated correctly
```

**Why**: Validates entire flow before season with real data.

---

## IMPORTANT: Should Do Soon (8 hours)

### 5. Enable Data Reconciliation (R-007) for MLB (2 hours)
Configure daily reconciliation job for MLB datasets:
- `mlb_raw.oddsa_batter_props`
- `mlb_raw.bp_batter_props`
- `mlb_predictions.pitcher_strikeouts`

### 6. Expand Player Registry (4 hours)
Add common name variants:
- Nick → Nicholas, Mike → Michael, etc.
- Jr., Sr., III suffixes
- Accent handling (José → Jose)

### 7. Team Mapping Updates (2 hours)
- A's relocation to Sacramento (if applicable)
- Verify Vegas naming conventions match API

---

## NICE-TO-HAVE: Tech Debt for Later

### 8. Document MLB Pipeline Architecture (4 hours)
Create architecture diagram and data flow documentation.

### 9. Add Unit Tests for MLB Processors (8 hours)
Improve test coverage for edge cases.

### 10. Consolidate Team Mapping Code (4 hours)
Currently duplicated across 5+ files. Create centralized `MLBTeamMapper`.

---

## NOT NEEDED: Analysis Findings

### SmartIdempotencyMixin
**Decision**: NOT needed for MLB processors

**Reason**: MLB uses `APPEND_ALWAYS` strategy for time-series odds data. SmartIdempotencyMixin only prevents duplicate writes with `MERGE_UPDATE` strategy. For append operations, it only adds hash computation overhead without benefit.

### Circuit Breaker Pattern
**Decision**: NOT needed

**Reason**: Self-heal mechanism (`mlb_self_heal/main.py`) already handles recovery for missing predictions.

### Batch Loader Refactoring
**Decision**: NOT needed

**Reason**: Batch loaders are one-time historical backfill scripts. They work correctly for their purpose. No need to integrate into ProcessorBase framework since they won't be reused.

---

## Opening Day Checklist

### Week Before Opening Day
- [ ] Enable scheduler jobs (all 11 paused jobs)
- [ ] Verify scraper credentials (ODDS_API_KEY, proxies)
- [ ] Test notification channels (Slack, email)
- [ ] Confirm BigQuery quotas

### Day Before Opening Day
- [ ] Run E2E test with previous day's data
- [ ] Verify worker health endpoints
- [ ] Check GCS bucket permissions
- [ ] Review monitoring dashboards

### Opening Day
- [ ] Monitor first game predictions
- [ ] Verify shadow mode captures both V1.4 and V1.6
- [ ] Check grading service after games complete
- [ ] Review any error notifications

---

## Shadow Mode Strategy

**Duration**: First 30 days (April 1 - April 30)

**Purpose**: Collect live performance data for V1.6 vs V1.4 comparison

**Success Criteria**:
- V1.6 maintains 65%+ accuracy on live data
- V1.6 UNDER predictions remain >70% accurate
- No systematic prediction failures

**Promotion Decision**: May 1, 2026
- If V1.6 outperforms: Promote to production
- If inconclusive: Extend shadow mode
- If V1.6 underperforms: Keep V1.4

---

## Key URLs

| Service | URL |
|---------|-----|
| MLB Prediction Worker | `https://mlb-prediction-worker-756957797294.us-west2.run.app` |
| MLB Grading Service | `https://mlb-grading-service-756957797294.us-west2.run.app` |

---

## Session History

| Session | Date | Focus |
|---------|------|-------|
| 63 | 2026-01-15 | Shadow mode fixes, V1.6 validation, batter props backfill |
| 62-58 | 2026-01-10 to 14 | E2E testing, scheduler setup, reliability fixes |
| 54 | 2026-01-05 | TODO analysis, feature prioritization |

---

## Contact

For questions about this checklist, see:
- `docs/09-handoff/2026-01-15-SESSION-63-MLB-HANDOFF.md`
- `docs/08-projects/current/mlb-pitcher-strikeouts/PROJECT-ROADMAP.md`
