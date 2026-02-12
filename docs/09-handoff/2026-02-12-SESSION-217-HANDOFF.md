# Session 217 Handoff — game_id Format Mismatch Fix

**Date:** 2026-02-12
**Session:** 217
**Status:** Complete — Pipeline recovered for Feb 11, fix deployed

## What Happened

Feb 12 morning: Phase 3 was stuck in a retry storm for Feb 11 data. Only 105 early predictions existed for Feb 12. The entire pipeline was blocked.

## Root Cause

**game_id format mismatch** in the boxscore completeness check (`main_analytics_service.py:262-332`):

- `nbac_schedule` uses numeric game_ids: `0022500775`
- `nbac_gamebook_player_stats` uses date format: `20260211_MIL_ORL`

The code compared these directly (`if nba_game_id not in boxscore_game_ids`), which NEVER matches. Result: all 14 games reported as "missing" despite 100% coverage. This caused:

1. Phase 3 returned HTTP 500 (boxscore "incomplete")
2. Pub/Sub retried up to 5 times, then sent to DLQ
3. Each retry triggered redundant re-scrape of gamebook data
4. Phase 3 never advanced to Phase 4/5/6

**Origin:** Session 198 switched from BDL (same game_id format as schedule) to NBA.com gamebook (different format) but didn't update the comparison logic.

## Fix Applied

**Commit:** `3b7f0ab9` — Match games by (away_team, home_team) pairs instead of game_id.

### File 1: `data_processors/analytics/main_analytics_service.py`
- Parse gamebook game_ids (`YYYYMMDD_AWAY_HOME`) into team pairs
- Compare schedule games against team pairs instead of raw game_ids
- Comment documents the format difference

### File 2: `orchestration/cloud_functions/phase3_to_phase4/main.py`
- Same format mismatch in coverage check (EXCEPT query between schedule and analytics)
- Fixed with LEFT JOIN on team tricodes instead of game_id EXCEPT
- Note: This was a cosmetic/logging bug only — the count-based coverage check worked correctly

## Deployment

Cloud Build auto-deploy had Docker layer caching that served stale code. Fixed with `./bin/hot-deploy.sh nba-phase3-analytics-processors` which forced a fresh image build.

**Lesson:** Cloud Build triggers deploying doc-only commits may use cached layers for code files. Hot-deploy is the reliable fallback.

## Recovery Steps

1. Hot-deployed Phase 3 service (revision `00269-nq7`)
2. Manually triggered Phase 3 for Feb 11 via `/process-date-range` with `backfill_mode: true`
3. Phase 3 completeness check now PASSES: "14/14 games"
4. Manually triggered Phase 4 for Feb 11 and Feb 12

## Systemic Findings

### game_id Format Mismatch Audit (3 agents)

The codebase has two game_id formats:
- **Schedule (`nbac_schedule`):** 10-digit numeric (e.g., `0022500775`)
- **Analytics/Predictions:** `YYYYMMDD_AWAY_HOME` (e.g., `20260211_MIL_ORL`)

A `GameIdConverter` utility exists at `shared/utils/game_id_converter.py` but isn't used consistently.

| Location | Status |
|----------|--------|
| Boxscore completeness check | FIXED (this session) |
| Phase 3→4 orchestrator coverage | FIXED (this session) |
| Game coverage alert | Already handled (constructs pred format) |
| Shared CTEs | Already handled (CONCAT conversion) |
| BDB arrival trigger | RISKY but BDL disabled |
| `trace_entity.py` | Needs verification |

### Validation Gaps

None of the current validation tools would have caught this bug:
- `validate-daily`: No game_id format alignment check
- `reconcile-yesterday`: Direct game_id JOIN (would false alarm but not explain WHY)
- `validate-phase3-season`: Count-based only
- Pre-commit hooks: Only check code structure, not runtime data

**Recommendation:** Add a game_id format alignment check to `validate-daily` that verifies schedule vs boxscore game_ids can be matched by team pairs.

### Phase 3 Pub/Sub Retry

- Subscription: `nba-phase3-analytics-sub`, max 5 delivery attempts, DLQ: `nba-phase2-raw-complete-dlq`
- Retry storm was bounded (max 5 retries → DLQ)
- However, re-scrape triggers created new Phase 2 completion messages, perpetuating the cycle

## Follow-Up Items

- [ ] Investigate Docker layer caching in Cloud Build — may need `--no-cache` for code-changing commits
- [ ] Add game_id format validation to `validate-daily` skill
- [ ] Verify `trace_entity.py` handles game_id format differences
- [ ] Monitor Feb 12 predictions — should increase once Phase 4/5 complete
- [ ] Phase 4 completion publish has "Missing required field: game_date" error — investigate

## CLAUDE.md Updates

Add to Common Issues table:
```
| game_id format mismatch | "Missing: N games" but 100% coverage | Schedule uses numeric, gamebook uses YYYYMMDD_AWAY_HOME. Match by team pairs. |
| Cloud Build Docker cache | Old code deployed despite new commit | Use `./bin/hot-deploy.sh` to force fresh build |
```
