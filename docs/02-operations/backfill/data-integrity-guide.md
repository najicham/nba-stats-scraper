# Data Integrity Guide

**File:** `docs/02-operations/backfill/data-integrity-guide.md`
**Created:** 2025-12-08 02:00 PM PST
**Last Updated:** 2025-12-08 02:00 PM PST
**Purpose:** Prevent, detect, and recover from data gaps and cascade contamination
**Status:** Current

---

## Overview

This guide covers how to maintain data integrity across the NBA stats pipeline, including:
- **Prevention**: Stop gaps before they happen
- **Detection**: Find gaps and cascade contamination quickly
- **Recovery**: Fix issues with proper backfill ordering

### Real Incident That Drove This Guide

Missing shot zone data in Phase 3 (`team_defense_game_summary.opp_paint_attempts = NULL`) cascaded through Phase 4 → Phase 5, resulting in **10,068 records** with `opponent_strength_score = 0`.

```
Root Cause: team_defense_game_summary.opp_paint_attempts = NULL
    ↓
Cascade L1: team_defense_zone_analysis.paint_defense_vs_league_avg = NULL
    ↓
Cascade L2: player_composite_factors.opponent_strength_score = 0
    ↓
Cascade L3: ml_feature_store_v2 would have bad features
```

---

## 1. Types of Data Gaps

| Gap Type | Description | Detection | Severity |
|----------|-------------|-----------|----------|
| **Missing Date** | Entire date missing from table | Date diff query | HIGH |
| **Partial Data** | Fewer records than expected | COUNT comparison | MEDIUM |
| **NULL Field** | Critical fields are NULL | NULL count query | HIGH |
| **Zero-Value** | Fields have 0 instead of calculated value | Zero detection | MEDIUM |
| **Cascade** | Upstream gap propagates downstream | Cascade validation | CRITICAL |

### Cascade Contamination (Most Dangerous)

**Cascade Contamination** occurs when gaps in upstream data cause downstream processes to produce records that:
1. **Exist** (pass existence checks)
2. **Look valid** (have timestamps, IDs, etc.)
3. **Contain invalid values** (NULLs, zeros, or incorrect calculations)

This is harder to detect than missing data because records exist but are corrupt.

---

## 2. Pipeline Architecture

```
Phase 3: Analytics (nba_analytics)
    ├── player_game_summary
    ├── team_defense_game_summary    ← Shot zone data
    └── team_offense_game_summary
    ↓
Phase 4: Precompute (nba_precompute)
    ├── team_defense_zone_analysis (TDZA)  ← Uses team_defense_game_summary
    ├── player_shot_zone_analysis (PSZA)
    ├── player_composite_factors (PCF)     ← Uses TDZA
    └── player_daily_cache (PDC)
    ↓
Phase 5: Predictions (nba_predictions)
    └── ml_feature_store_v2              ← Extracts from PCF
```

### Critical Fields Registry

| Table | Critical Fields | Valid Condition |
|-------|-----------------|-----------------|
| team_defense_game_summary | opp_paint_attempts | > 0 |
| team_defense_game_summary | opp_mid_range_attempts | > 0 |
| team_defense_zone_analysis | paint_defense_vs_league_avg | IS NOT NULL |
| player_composite_factors | opponent_strength_score | > 0 |
| player_shot_zone_analysis | paint_fg_pct | IS NOT NULL |
| ml_feature_store_v2 | opponent_strength_score | > 0 |

---

## 3. Prevention: Three-Layer Defense

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: PRE-RUN VALIDATION (Prevent)                      │
│  Before processing, verify upstream critical fields         │
│  have valid data. Fail fast if contaminated.                │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: POST-RUN VALIDATION (Detect)                      │
│  After processing, verify output critical fields.           │
│  Alert and halt if contamination found.                     │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: LINEAGE TRACKING (Trace)                          │
│  Record upstream state when downstream computed.            │
│  Enable staleness detection on future runs.                 │
└─────────────────────────────────────────────────────────────┘
```

### Validation Modes

| Mode | Pre-run | Post-run | Use Case |
|------|---------|----------|----------|
| **strict** | FAIL on invalid | FAIL + ALERT | Production runs |
| **backfill** | WARN only | FAIL | Ordered backfills |
| **force** | SKIP | WARN | Emergency/testing |

---

## 4. Detection Methods

### 4.1 Automated Validation Scripts

```bash
# Check coverage and failures (player-level)
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --details --reconcile

# Check data quality (cascade contamination)
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --strict
```

### 4.2 Contamination Status Levels

| Status | Definition | Action |
|--------|------------|--------|
| **CLEAN** | 99%+ valid | None |
| **PARTIAL** | 50-99% valid | Investigate |
| **CONTAMINATED** | <50% valid | Reprocess required |

### 4.3 Quick Health Check Queries

```bash
# Check Phase 3 paint data
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as total, COUNTIF(opp_paint_attempts > 0) as valid
FROM nba_analytics.team_defense_game_summary
WHERE game_date BETWEEN "2021-12-01" AND "2021-12-31"
GROUP BY 1 ORDER BY 1'

# Check Phase 4 opponent strength
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as total, COUNTIF(opponent_strength_score > 0) as valid
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN "2021-12-01" AND "2021-12-31"
GROUP BY 1 ORDER BY 1'
```

### 4.4 Full Pipeline Health Check Query

```sql
WITH validation AS (
  SELECT 'Phase3_TDGS' as stage, game_date as check_date, COUNT(*) as total,
         COUNTIF(opp_paint_attempts > 0) as valid
  FROM `nba_analytics.team_defense_game_summary`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
  UNION ALL
  SELECT 'Phase4_TDZA', analysis_date, COUNT(*),
         COUNTIF(paint_defense_vs_league_avg IS NOT NULL)
  FROM `nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date BETWEEN @start_date AND @end_date
  GROUP BY analysis_date
  UNION ALL
  SELECT 'Phase4_PCF', game_date, COUNT(*), COUNTIF(opponent_strength_score > 0)
  FROM `nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
)
SELECT stage, check_date, total, valid,
  ROUND(100.0 * valid / NULLIF(total, 0), 1) as valid_pct,
  CASE WHEN valid = 0 THEN 'CONTAMINATED'
       WHEN valid < total THEN 'PARTIAL' ELSE 'CLEAN' END as status
FROM validation
WHERE valid < total
ORDER BY stage, check_date;
```

---

## 5. Recovery Procedures

### 5.1 Recovery Flowchart

```
Gap/Contamination Detected
        │
        ▼
┌───────────────────┐
│ 1. IDENTIFY ROOT  │  Which upstream table/field is the source?
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 2. SCOPE IMPACT   │  Run cascade detection query
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 3. FIX UPSTREAM   │  Backfill the root cause table first
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 4. VALIDATE FIX   │  Verify upstream now has valid data
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ 5. REPROCESS      │  Backfill downstream in dependency order
│    DOWNSTREAM     │  Validate after each stage
└───────────────────┘
```

### 5.2 Backfill Order (Critical!)

**Always backfill in dependency order:**

```bash
# 1. Phase 3 - Fix root cause
.venv/bin/python backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31

# 2. Phase 4 - TDZA and PSZA can run in parallel
.venv/bin/python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31

.venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31

# 3. Phase 4 - PCF and PDC (depend on TDZA/PSZA)
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-11-05 --end-date 2021-12-31

.venv/bin/python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31

# 4. Phase 5
.venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2021-11-05 --end-date 2021-12-31
```

### 5.3 Validation Gates

Run validation after each backfill stage before proceeding:

```bash
# After Phase 3
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --stage phase3

# After TDZA
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --table team_defense_zone_analysis

# After PCF
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --table player_composite_factors
```

---

## 6. Validation Tools Reference

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `scripts/validate_backfill_coverage.py` | Player-level coverage check | `--details`, `--reconcile` |
| `scripts/validate_cascade_contamination.py` | Critical field validation | `--strict`, `--stage` |
| `bin/backfill/preflight_check.py` | Pre-backfill data check | `--phase`, `--verbose` |
| `bin/backfill/verify_phase3_for_phase4.py` | Phase 3 readiness | `--verbose` |
| `bin/backfill/verify_backfill_range.py` | Full verification | `--verbose` |

---

## 7. Implementation Status

### Currently Implemented
- ✅ Dependency checking via `check_dependencies()`
- ✅ Completeness validation before backfill
- ✅ `validate_cascade_contamination.py` script
- ✅ `validate_backfill_coverage.py` script
- ✅ Failure tracking in BigQuery tables
- ✅ Lightweight existence check in backfill mode

### Future Improvements
- ⬜ Critical field validation mixin in base processors
- ⬜ Automated cascade impact analyzer
- ⬜ Data lineage dashboard
- ⬜ Self-healing workflows

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **Cascade Contamination** | Invalid data propagating through pipeline layers |
| **Critical Field** | A field that must have valid values for downstream to work |
| **Contaminated** | >90% of records have invalid critical field values |
| **Validation Gate** | Checkpoint between pipeline stages |

## Appendix B: Quick Reference Commands

```bash
# Full validation workflow
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2021-11-01 --end-date 2021-12-31

# Coverage check with reconciliation
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --reconcile

# Pre-flight check
.venv/bin/python bin/backfill/preflight_check.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --verbose
```

---

## Related Documentation

- [README.md](./README.md) - Validation workflow and script references
- [backfill-guide.md](./backfill-guide.md) - Complete backfill procedures
- [backfill-mode-reference.md](./backfill-mode-reference.md) - Backfill mode behaviors
