# Session 13B Complete Handoff: Player Lookup Normalization Fix

**Date:** January 12, 2026
**Session Focus:** Data Quality Investigation - line_value = 20
**Status:** CODE DEPLOYED - Backfill Pending
**Commit:** `167a942`
**Revision:** `nba-phase2-raw-processors-00085-n2q`

---

## Executive Summary

### What Was Fixed
**Root Cause:** Player name normalization was inconsistent across processors:
- ESPN rosters and BettingPros **REMOVED** suffixes (Jr., Sr., II, III)
- Odds API props **KEPT** suffixes

**Impact:** JOINs failed for suffix players → predictions used `line_value = 20` default → corrupted win rate metrics (showed 51.6% instead of actual 73.1% for OVER picks).

**Fix Applied:** Both ESPN roster and BettingPros processors now use the shared `normalize_name()` function which KEEPS suffixes.

---

## Deployment Details

| Item | Value |
|------|-------|
| **Service** | `nba-phase2-raw-processors` |
| **Revision** | `nba-phase2-raw-processors-00085-n2q` |
| **Commit** | `167a942` |
| **Deploy Time** | 15m 26s |
| **Health Check** | Passed |
| **Region** | us-west2 |

---

## What Was Completed

### 1. Root Cause Investigation
- Traced data flow from ESPN rosters → upcoming_player_game_context → predictions
- Identified normalization inconsistency as the cause of JOIN failures
- Documented affected players (Michael Porter Jr., Gary Payton II, etc.)

### 2. Code Changes (Deployed)
| File | Change |
|------|--------|
| `data_processors/raw/espn/espn_team_roster_processor.py` | Now imports and uses shared `normalize_name()` at line 166 |
| `data_processors/raw/bettingpros/bettingpros_player_props_processor.py` | Now imports and uses shared `normalize_name()` at line 297 |

### 3. Supporting Files Created
| File | Purpose |
|------|---------|
| `bin/patches/patch_player_lookup_normalization.sql` | Backfill SQL with verification queries |
| `bin/patches/verify_normalization_fix.py` | Pre-deployment verification (22 tests passed) |
| `docs/08-projects/.../data-quality/2026-01-12-PLAYER-LOOKUP-NORMALIZATION-MISMATCH.md` | Full investigation report |

### 4. Documentation Updated
- `docs/08-projects/current/pipeline-reliability-improvements/MASTER-TODO.md` - Session 13B progress + P1-DATA-3/4 marked complete
- `docs/09-handoff/2026-01-12-SESSION-13B-DATA-QUALITY.md` - Updated with implementation details

---

## What Remains To Be Done

### IMMEDIATE: Run Backfill SQL (P2-DATA-3, P2-DATA-4)

The code fix is deployed, but **historical data still has wrong `player_lookup` values**. Run the backfill to fix existing data.

**Step 1: Open BigQuery Console**
Navigate to: https://console.cloud.google.com/bigquery?project=nba-props-platform

**Step 2: Test SQL Produces Correct Output**
Run Step 4 from `bin/patches/patch_player_lookup_normalization.sql`:
```sql
SELECT
    name,
    REGEXP_REPLACE(LOWER(NORMALIZE(name, NFD)), r'[^a-z0-9]', '') as normalized
FROM UNNEST([
    'Michael Porter Jr.',
    'Gary Payton II',
    'LeBron James',
    'Nikola Jokić',
    "D'Angelo Russell"
]) as name;
```

Expected:
- `Michael Porter Jr.` → `michaelporterjr`
- `Gary Payton II` → `garypaytonii`
- `LeBron James` → `lebronjames`
- `Nikola Jokić` → `nikolajokic`
- `D'Angelo Russell` → `dangelorussell`

**Step 3: Run ESPN Rosters Backfill**
```sql
UPDATE `nba-props-platform.nba_raw.espn_team_rosters`
SET player_lookup = REGEXP_REPLACE(
    LOWER(NORMALIZE(player_full_name, NFD)),
    r'[^a-z0-9]', ''
)
WHERE player_lookup IS NOT NULL
  AND player_full_name IS NOT NULL;
```

**Step 4: Run BettingPros Props Backfill**
```sql
UPDATE `nba-props-platform.nba_raw.bettingpros_player_points_props`
SET player_lookup = REGEXP_REPLACE(
    LOWER(NORMALIZE(player_name, NFD)),
    r'[^a-z0-9]', ''
)
WHERE player_lookup IS NOT NULL
  AND player_name IS NOT NULL;
```

**Step 5: Verify JOINs Work**
Run Step 3 from the SQL file to verify suffix players now match.

### FOLLOW-UP: Regenerate Downstream Data

After backfill, regenerate `upcoming_player_game_context` for affected dates:
```bash
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
    --start-date 2025-11-01 --end-date 2025-12-31
```

---

## Key Files for Next Session to Study

### Investigation & Documentation
1. **Investigation Report:** `docs/08-projects/current/pipeline-reliability-improvements/data-quality/2026-01-12-PLAYER-LOOKUP-NORMALIZATION-MISMATCH.md`
   - Complete root cause analysis
   - Impact assessment
   - All code changes documented

2. **Project TODO:** `docs/08-projects/current/pipeline-reliability-improvements/MASTER-TODO.md`
   - Session 13B progress section
   - P1-DATA-3 and P1-DATA-4 items

### Code to Understand
1. **Shared Normalizer:** `data_processors/raw/utils/name_utils.py`
   - The `normalize_name()` function all processors should use
   - KEEPS suffixes (Jr., Sr., II, III)

2. **Fixed Processors:**
   - `data_processors/raw/espn/espn_team_roster_processor.py` - See line 166 and deprecated method at 447
   - `data_processors/raw/bettingpros/bettingpros_player_props_processor.py` - See line 297 and deprecated method at 150

3. **How Data Flows:**
   - `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
   - Lines 723-754 show the JOIN between rosters and props

### Backfill Scripts
1. **SQL Backfill:** `bin/patches/patch_player_lookup_normalization.sql`
   - Complete step-by-step guide
   - Verification queries

2. **Verification Script:** `bin/patches/verify_normalization_fix.py`
   - Run to verify code is correct: `PYTHONPATH=. python bin/patches/verify_normalization_fix.py`

---

## Verification Commands

### Check Deployment Status
```bash
gcloud run services describe nba-phase2-raw-processors \
    --region us-west2 \
    --format="value(status.latestReadyRevisionName)"
# Expected: nba-phase2-raw-processors-00085-n2q
```

### Verify Commit Deployed
```bash
gcloud run services describe nba-phase2-raw-processors \
    --region us-west2 \
    --format="value(metadata.labels.commit-sha)"
# Expected: 167a942
```

### Run Verification Script
```bash
PYTHONPATH=. python bin/patches/verify_normalization_fix.py
# Expected: ALL CHECKS PASSED
```

---

## Expected Impact After Backfill

After running the backfill SQL:
1. ESPN rosters will have `player_lookup = michaelporterjr` (suffix kept)
2. BettingPros props will have `player_lookup = michaelporterjr` (suffix kept)
3. Odds API props already have `player_lookup = michaelporterjr` (no change needed)
4. JOINs between rosters and props will succeed for suffix players
5. Predictions will use real Vegas lines instead of default `line_value = 20`
6. OVER pick win rate should improve from corrupted 51.6% to true **73.1%**

---

## Git Status

```
Commit: 167a942
Message: fix(processors): Use consistent player_lookup normalization to keep suffixes

Files Changed:
- data_processors/raw/espn/espn_team_roster_processor.py (modified)
- data_processors/raw/bettingpros/bettingpros_player_props_processor.py (modified)
- bin/patches/patch_player_lookup_normalization.sql (new)
- bin/patches/verify_normalization_fix.py (new)
- docs/08-projects/.../data-quality/2026-01-12-PLAYER-LOOKUP-NORMALIZATION-MISMATCH.md (new)
```

---

*Last Updated: January 12, 2026 04:38 UTC*
*Deployment Status: SUCCESS*
*Backfill Status: PENDING*
