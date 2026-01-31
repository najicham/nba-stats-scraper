# Session 41 Handoff - Soft Dependencies & BDL Quality Monitoring

**Date:** 2026-01-30
**Status:** Complete

---

## Executive Summary

Implemented soft dependency thresholds (80% coverage) for Phase 3 analytics and added comprehensive BDL quality monitoring infrastructure to track when BDL can be safely re-enabled as a backup data source.

---

## Changes Made

### 1. Soft Dependency Threshold (P2 from Phase 3 Improvement Plan)

**Files Modified:**
- `data_processors/analytics/mixins/dependency_mixin.py`
- `data_processors/analytics/analytics_base.py`

**What It Does:**
- When `use_soft_dependencies=True` and coverage >= 80%, allows processing in "degraded" mode
- Coverage = row_count / expected_count_min
- Tracks degraded state in stats for monitoring

**How to Enable:**
```python
class MyProcessor(AnalyticsProcessorBase):
    use_soft_dependencies = True
    soft_dependency_threshold = 0.80
```

### 2. BDL Quality Monitoring

**Files Modified/Created:**
- `orchestration/cloud_functions/data_quality_alerts/main.py` - Added `check_bdl_quality()`
- `schemas/bigquery/nba_orchestration/source_discrepancies.sql` - Added `bdl_quality_trend` view

**Infrastructure:**
| Component | Purpose |
|-----------|---------|
| Cloud Function | Daily BDL vs NBAC comparison at 7 PM ET |
| `source_discrepancies` table | Stores quality metrics |
| `bdl_quality_trend` view | Shows trend with `bdl_readiness` indicator |

**BDL Readiness Criteria:**
- `READY_TO_ENABLE`: <5% major discrepancies for 7 consecutive days
- `IMPROVING`: <10% major discrepancies
- `NOT_READY`: >10% major discrepancies

### 3. Documentation Updates

- Updated `CLAUDE.md` with BDL monitoring guidance
- Updated `/validate-daily` skill with BDL quality trend check
- Created `docs/07-monitoring/data-source-quality.md`

---

## Deployments

| Service | Status | Notes |
|---------|--------|-------|
| `data-quality-alerts` Cloud Function | ✅ Deployed | Revision 00004-yef |
| `bdl_quality_trend` BigQuery View | ✅ Created | In nba_orchestration dataset |

---

## Decision: BDL Fallback

**Decision:** Keep BDL disabled

**Reason:** BDL data quality investigation showed ~50% accuracy for many players. No way to validate which records are accurate without a reference source.

**Path to Re-enable:**
1. Monitor `bdl_quality_trend` view daily
2. When `bdl_readiness = 'READY_TO_ENABLE'` for latest date
3. Set `USE_BDL_DATA = True` in `player_game_summary_processor.py`
4. Deploy Phase 3 processors

---

## Commits

| Commit | Description |
|--------|-------------|
| `0206470b` | feat: Add soft dependency threshold and BDL quality monitoring |

---

## Known Issues Still Open

1. **Jan 22-23 data gaps** - NBAC has 0 records, BDL unreliable. Need to re-run NBAC scraper if source data still available.
2. **BDL data quality** - Currently shows ~58% major discrepancies (Jan 27). Not safe to use.

---

## Verification Commands

```bash
# Check BDL quality trend
bq query --use_legacy_sql=false "
SELECT game_date, major_discrepancy_pct, bdl_readiness
FROM nba_orchestration.bdl_quality_trend
ORDER BY game_date DESC LIMIT 7"

# Test the data-quality-alerts function
curl "https://data-quality-alerts-f7p3g7f6ya-wl.a.run.app?checks=bdl_quality&dry_run=true"
```

---

## Next Session Checklist

1. [ ] Monitor BDL quality trend over next few days
2. [ ] Consider running backfill for Jan 22-23 if NBAC scraper can get data
3. [ ] Enable soft dependencies for specific processors if needed
4. [ ] Review Phase 3 Improvement Plan for remaining tasks (P4, P5)

---

## Files Changed This Session

| File | Changes |
|------|---------|
| `data_processors/analytics/mixins/dependency_mixin.py` | Soft dependency support |
| `data_processors/analytics/analytics_base.py` | Degraded state tracking |
| `orchestration/cloud_functions/data_quality_alerts/main.py` | BDL quality check |
| `schemas/bigquery/nba_orchestration/source_discrepancies.sql` | BDL quality trend view |
| `.claude/skills/validate-daily/SKILL.md` | BDL trend check section |
| `CLAUDE.md` | BDL monitoring guidance |
| `docs/07-monitoring/data-source-quality.md` | New documentation |

---

*Session 41 complete. Soft dependencies and BDL monitoring infrastructure deployed.*
