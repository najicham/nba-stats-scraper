# Session 302 Handoff — Phase 3 Partial Processing Fix, Canary Auto-Heal, Visibility

**Date:** 2026-02-23
**Previous Session:** 332 — Tonight Re-Export Fix, Completeness Checker Bug, Pipeline Recovery

## What Happened

On Feb 22, an 11-game night exposed a cascade of failures:

1. **Team boxscore scraper wrote zero-value placeholders** for 10 teams (5 games still in progress)
2. **TeamOffenseGameSummaryProcessor quality check rejected ALL 22 teams** because ANY team had zeros — even though 12 teams (6 completed games) had valid data
3. **PlayerGameSummaryProcessor blocked** because team stats dependency showed 0/22 teams
4. **No canary detected partial processing** — existing checks only caught 0/N, not 7/11
5. **No self-healing re-triggered Phase 3** when remaining games finished

### Root Cause Chain

```
Scraper writes 0-value placeholders for in-progress games
  → Quality check: ANY team has zeros → reject ALL teams (even valid ones)
    → TeamOffense: 0 records for Feb 22
      → PlayerGameSummary: team dependency fails (0/22 teams)
        → Phase 4/5/6 cascade: no features, no predictions, no grading
```

## What Was Fixed

### 1. Quality check: filter invalid rows instead of rejecting all (Area A)

**File:** `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py` (lines ~555-568)

**Before:** If ANY team had points=0 or fg_attempted=0, the entire DataFrame was rejected (returned empty), triggering fallback to reconstruction.

**After:** Invalid rows are filtered out. Valid teams are kept. If ALL teams are invalid, still returns empty (fallback chain activates). Logged with count of filtered vs kept teams.

**Visibility:** When teams are filtered, a `notify_warning` Slack alert fires immediately to `#nba-alerts` with the list of filtered teams and a note to re-run Phase 3 after remaining games finish. This ensures partial processing is immediately visible (not buried in logs).

**Why safe:** The completeness validation at lines 377-413 already handles the case where too few teams remain (threshold: 10). If we filter to 12 valid teams from 22 total, it passes completeness.

### 2. Partial-processing canary with auto-heal (Area B)

**File:** `bin/monitoring/pipeline_canary_queries.py`

**New canary:** "Phase 3 - Partial Game Coverage" compares scheduled final games vs games in `player_game_summary`. Detects partial gaps (e.g., 7/11 games processed) — existing gap detection only caught complete gaps (0/N).

**Auto-heal:** When partial gap detected, automatically re-triggers Phase 3 via `POST /process-date-range` with `backfill_mode: true`. Safe because Phase 3 uses MERGE_UPDATE strategy.

**New function:** `auto_retrigger_phase3()` — follows same auth pattern as `auto_backfill_shadow_models()`.

### 3. Phase 0.35 game-level coverage check in `/validate-daily` (Area C)

**File:** `.claude/skills/validate-daily/SKILL.md`

**New check:** Phase 0.35 (between Phase 0.3 Deployment Drift and Phase 0.4 Grading Completeness) compares scheduled final games vs analytics per-game. Shows per-game OK/MISSING status. Provides remediation curl command.

### 4. CLAUDE.md common issues updated (Area E)

Added three entries:
- Phase 3 partial game processing — quality check now filters instead of rejecting
- Team boxscore zeros — expected for in-progress games, filtered at processing time
- Cloud Function env vars — use `gcloud functions describe`, not `gcloud run services describe`

## Visibility: 3-Layer Partial Processing Detection

When Team Offense filters invalid teams, three layers ensure visibility and recovery:

| Layer | When | What |
|-------|------|------|
| **Slack alert** (processor) | Immediately during Phase 3 | `notify_warning` with filtered team list + "re-run after games finish" |
| **Canary auto-heal** (every 30 min) | Next canary cycle | Detects partial gap → auto-triggers Phase 3 reprocessing |
| **validate-daily Phase 0.35** (manual) | Next morning validation | Per-game OK/MISSING status with remediation command |

## Related: Session 332 Findings (Parallel Backend Chat)

Session 332 (same day, different context) fixed related issues on the same Feb 22 11-game night:

1. **Completeness checker CASE WHEN bug** — `TeamDefenseZoneAnalysisProcessor` only produced data for 11/30 teams because the completeness checker undercounted expected games by ~50%. Fixed with UNNEST.
2. **Tonight JSON re-export** — Frontend "Waiting on Results" bug fixed by adding step 6 to `post_grading_export`.
3. **overnight-phase4 scheduler** — Updated to run all 5 Phase 4 processors (was MLFS only).

See: `docs/09-handoff/2026-02-22-SESSION-332-HANDOFF.md`

## Related: Frontend Live-Grading Stale Data Bug

The frontend reported (`docs/08-projects/current/frontend-data-design/11-LIVE-GRADING-STALE-DATA-BUG.md`) that `live-grading/latest.json` showed all predictions as "scheduled"/"pending" despite games being final. Root cause: `BDL_API_KEY` was missing from the `live-export` Cloud Function (env var wiped by `--set-env-vars`).

**Fix already in this session:** The live-grading content quality canary (added to `pipeline_canary_queries.py`) now detects this scenario — zero graded predictions despite final games = canary failure. The env var drift detection for Cloud Functions was also added.

**Remaining risk:** `BDL_API_KEY` may be lost again on redeploy. Consider moving to Secret Manager volume mount.

## What Still Needs Attention

### Immediate

- **Feb 22 data**: May need manual reprocessing if auto-heal hasn't caught it yet. Verify with:
  ```sql
  SELECT COUNT(DISTINCT game_id) as games
  FROM nba_analytics.player_game_summary
  WHERE game_date = '2026-02-22'
  ```
  Expected: 11 games. If less, run:
  ```bash
  curl -X POST https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d '{"start_date":"2026-02-22","end_date":"2026-02-22","backfill_mode":true}'
  ```

### Known Behaviors (Won't Fix)

- **Team boxscore scraper writes zeros for in-progress games**: By design. The scraper captures whatever data is available when it runs. Now filtered at processing time instead of causing cascade rejection.
- **Gamebook scraper timing** (4 AM ET `post_game_window_3`): Working correctly — processes games after they're final.

## Verification Commands

```bash
# 1. Syntax check on modified files
python3 -c "import py_compile; py_compile.compile('data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('bin/monitoring/pipeline_canary_queries.py', doraise=True)"

# 2. Run canary queries — new "Phase 3 - Partial Game Coverage" check should appear
python bin/monitoring/pipeline_canary_queries.py

# 3. Check Feb 22 analytics coverage
bq query --nouse_legacy_sql "SELECT COUNT(DISTINCT game_id) as games FROM nba_analytics.player_game_summary WHERE game_date = '2026-02-22'"
```

## Architecture: Failure Cascade and Fix Points

```
Scraper writes 0-value placeholders for in-progress games
  │
  ├─ [FIX A] Quality check now FILTERS invalid rows instead of rejecting all
  │    → Valid teams proceed, invalid teams dropped with warning
  │
  ├─ [FIX B] Canary detects partial gaps (was: only detected 0/N)
  │    → Auto-heals by re-triggering Phase 3 for affected date
  │
  └─ [FIX C] /validate-daily Phase 0.35 shows per-game coverage
       → Manual visibility + remediation command
```

## Files Changed

| File | Change |
|------|--------|
| `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py` | Quality check: filter-not-reject |
| `bin/monitoring/pipeline_canary_queries.py` | New canary + auto-heal function |
| `.claude/skills/validate-daily/SKILL.md` | Phase 0.35 game-level coverage |
| `CLAUDE.md` | Common issues table updates |
| `docs/09-handoff/2026-02-23-SESSION-302-HANDOFF.md` | This handoff |
