# Handoff Document: Registry Fix Complete + Coverage Gap Investigation

**Date:** 2026-01-10
**Session Duration:** ~3 hours
**Status:** Registry Fix Complete, Coverage Investigation In Progress
**Priority:** High

---

## Executive Summary

This session completed the registry system fix deployment and discovered a new issue: prediction coverage is only 31.5% due to incomplete data pipeline processing.

**Two distinct issues were found:**
1. ✅ **Registry system** - Fixed and deployed (was blocking predictions for unresolved names)
2. 🔴 **Coverage gap** - NEW ISSUE: Only 7 of 20 teams have prediction context for Jan 9

---

## What Was Completed

### Registry System Fix (100% Complete)

| Task | Status |
|------|--------|
| Push commits to origin | ✅ 14 commits pushed |
| Create BigQuery reprocessing_runs table | ✅ Created |
| Deploy reference service to Cloud Run | ✅ Deployed (with fixes) |
| Create scheduler jobs | ✅ 2 jobs created (4:30 AM, 5:00 AM ET) |
| Run backfill recovery | ✅ 1,064 failures marked resolved |
| AI resolution endpoint | ✅ Working |
| Create missing alias | ✅ `vincentwilliamsjr` → `vincewilliamsjr` |

**Service URL:** `https://nba-reference-service-756957797294.us-west2.run.app`

**Scheduler Jobs:**
- `registry-ai-resolution` - 4:30 AM ET daily
- `registry-health-check` - 5:00 AM ET daily

---

## Open Issue: Prediction Coverage Gap (31.5%)

### The Problem

For games on 2026-01-09:
- 146 players had betting lines
- Only 46 players got predictions
- **Coverage: 31.5%**

### Root Causes Identified

**Issue 1: Phase 2 - Missing Boxscores (6 teams)**
```
Teams WITH boxscores (14): ATL, BKN, BOS, DEN, LAC, MEM, NOP, NYK, OKC, ORL, PHI, PHX, TOR, WAS
Teams MISSING boxscores (6): GSW, HOU, LAL, MIL, POR, SAC
```

**Issue 2: Phase 3 - Missing Context (7 more teams)**
```
Teams WITH context (7): ATL, DEN, NOP, NYK, ORL, PHX, WAS
Teams MISSING context but HAVE boxscores (7): BKN, BOS, LAC, MEM, OKC, PHI, TOR
```

### Data Flow

```
20 teams played on Jan 9
    ↓
Phase 2: bdl_player_boxscores → 14 teams (70%)
    ↓ [6 teams lost - BDL scraper issue]
    ↓
Phase 3: upcoming_player_game_context → 7 teams (35%)
    ↓ [7 more teams lost - context processor issue]
    ↓
Phase 4: predictions → 46/146 players (31.5%)
```

### Immediate Fix Available

Run context backfill for Jan 9:
```bash
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2026-01-09 --end-date 2026-01-09
```

This will regenerate context for teams that have boxscores but missing context.

### Investigation Needed

1. **BDL Scraper** - Why are 6 teams missing from boxscores?
   - Check scraper logs for Jan 9
   - Possible API issues, timing problems, or scraper failures

2. **Context Processor** - Why did 7 teams with boxscores not get context?
   - Check Pub/Sub message delivery
   - Check for processing errors in logs
   - Review mode detection (DAILY vs BACKFILL)

---

## Key Files to Study

### Registry System (Completed)

| File | Purpose |
|------|---------|
| `shared/utils/player_name_resolver.py` | Name resolution logic (4-step pipeline) |
| `tools/player_registry/resolve_unresolved_batch.py` | AI resolution + auto-reprocessing |
| `tools/player_registry/recover_backfill_failures.py` | Historical failure recovery |
| `data_processors/reference/main_reference_service.py` | Cloud Run service with /resolve-pending endpoint |
| `docker/reference-service.Dockerfile` | Deployment config (includes tools/ directory) |

### Coverage Gap Investigation

| File | Purpose |
|------|---------|
| `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | Context generation (4600+ lines) |
| `tools/monitoring/check_prediction_coverage.py` | Coverage gap detection tool |
| `scrapers/bigdataball/` | BDL boxscore scraping |
| `data_processors/raw/bigdataball/bdl_player_boxscores_processor.py` | BDL processing |

### Documentation

| File | Purpose |
|------|---------|
| `docs/08-projects/current/registry-system-fix/README.md` | Registry fix project status |
| `docs/08-projects/current/pipeline-reliability-improvements/README.md` | Coverage gap documented here |
| `docs/09-handoff/2026-01-10-REGISTRY-COMPLETE-HANDOFF.md` | Previous handoff (registry focus) |

---

## Current Database State

### Registry Failures
```sql
SELECT
  CASE
    WHEN reprocessed_at IS NOT NULL THEN 'complete'
    WHEN resolved_at IS NOT NULL THEN 'ready_to_reprocess'
    ELSE 'pending_resolution'
  END as status,
  COUNT(DISTINCT player_lookup) as players
FROM `nba_processing.registry_failures`
GROUP BY status;
```

**Result:**
- `ready_to_reprocess`: 607 players, 3,202 records
- `pending_resolution`: 19 players, 1,074 records (DATA_ERROR cached)

### Context Coverage for Jan 9
```sql
SELECT team_abbr, COUNT(*) as players
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = '2026-01-09'
GROUP BY team_abbr;
```

**Result:** Only 7 teams: ATL, DEN, NOP, NYK, ORL, PHX, WAS (108 players total)

---

## Commands Reference

### Check System Health
```bash
# Reference service health
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://nba-reference-service-756957797294.us-west2.run.app/health

# Prediction coverage check
python tools/monitoring/check_prediction_coverage.py --date 2026-01-09 --detailed

# Registry status
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN reprocessed_at IS NOT NULL THEN 'complete'
       WHEN resolved_at IS NOT NULL THEN 'ready_to_reprocess'
       ELSE 'pending' END as status,
  COUNT(*) as records
FROM \`nba_processing.registry_failures\`
GROUP BY status"
```

### Run Backfills
```bash
# Context backfill (fixes coverage for teams with boxscores)
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2026-01-09 --end-date 2026-01-09

# Trigger AI resolution via Cloud Run
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" -d '{}' \
  https://nba-reference-service-756957797294.us-west2.run.app/resolve-pending
```

---

## Architecture Overview

### Registry Resolution Flow
```
Player name from scraper
    ↓
1. Alias table lookup (fast path)
    ↓
2. Registry validation (season/team context)
    ↓
3. AI cache lookup (DATA_ERROR skips, MATCH creates alias)
    ↓
4. Unresolved queue (manual review)
```

### Prediction Pipeline
```
Phase 1: Scrapers → odds_api_player_points_props (betting lines)
Phase 2: Processors → bdl_player_boxscores (game stats)
Phase 3: Analytics → upcoming_player_game_context (prediction features)
Phase 4: Predictions → player_prop_predictions (actual predictions)
```

---

## Known Issues

### 19 Players Cached as DATA_ERROR
These are G-League/rookie players the AI incorrectly marked as invalid:
```
alexantetokounmpo, airiousbailey, jahmaimashack, grantnelson, julianreese,
boobuie, danielbatcho, fanbozeng, etc.
```

To fix: Add to registry, invalidate cache entries, re-run AI resolution.

### Reprocessing Pending
3,202 records are marked `resolved` but not yet `reprocessed`. The scheduled job at 4:30 AM will handle this, or manually trigger via Cloud Run.

---

## Next Steps (Priority Order)

1. **Run context backfill** for Jan 9 (immediate fix for 7 missing teams)
2. **Investigate BDL scraper** for 6 teams with no boxscores
3. **Check context processor logs** for why 7 teams failed
4. **Monitor scheduled jobs** (4:30 AM resolution, 5:00 AM health check)
5. **Consider adding missing G-League players** to registry

---

## Git Status

All changes committed and pushed:
```
0f7a6e1 docs(pipeline): Add prediction coverage gap investigation
d9bd986 docs(registry): Mark project complete with known gaps documented
a12da6e fix(reference-service): Add dependencies for AI resolution endpoint
947b0ca fix(docker): Add raw processor dependencies to reference service
```

---

**Last Updated:** 2026-01-10 17:30 ET
**Author:** Claude Code (Opus 4.5)
