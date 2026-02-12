# Session 210 Handoff - Frontend API Gap Resolution & GCS Race Condition Fix

**Date:** 2026-02-11
**Branch:** main (all changes merged)
**Trigger:** Frontend team API endpoint review document

---

## What Happened

Frontend team provided a comprehensive API endpoint review (`props-web/docs/08-projects/current/backend-integration/API_ENDPOINT_REVIEW_2026-02-11.md`) cataloging 13 issues across 12 endpoints. We resolved all actionable items and discovered + fixed a hidden GCS race condition causing silent export failures.

---

## Changes Made

### Code Changes (2 commits)

**Commit `1b76014` - Frontend API enhancements** (merged earlier in session)
- `player_profile_exporter.py`: Added `team_abbr` field, separate `fg_makes`/`fg_attempts`, `three_makes`/`three_attempts`, `ft_makes`/`ft_attempts` (kept string format for backwards compat)
- `phase5_to_phase6/main.py`: Added `calendar` to `TONIGHT_EXPORT_TYPES` so calendar exports run automatically
- `CLAUDE.md`: Condensed and streamlined

**Commit `7a06ead` - GCS 409 fix + monitoring**
- `base_exporter.py`: Eliminated GCS 409 Conflict race condition by setting `cache_control` before `upload_from_string()` instead of separate `patch()` call. Added `Conflict` to retry exception list.
- `phase6_picks_canary.py`: Enhanced from existence-only to existence + freshness checks. Now monitors `results/latest.json` (30h threshold) and `tonight/all-players.json` (6h threshold).

### Infrastructure Changes
- **Deleted** duplicate Pub/Sub subscription `eventarc-us-west2-phase5-to-phase6-578429-sub-264` (was causing double Phase 6 triggers)
- **Deleted** stale Cloud Run service `phase5-to-phase6` (old, replaced by `phase5-to-phase6-orchestrator`)
- **Re-exported** `results/latest.json` for Feb 10 and Feb 11, `live-grading/2026-02-10.json`

### Already on branch from earlier commits (Session 209)
These were already merged before this session started:
- `prediction.factors` — directional logic with up to 4 factors per pick
- `recent_form` — Hot/Cold/Neutral based on last_5 vs season avg
- `minutes_avg` — maps to season_mpg
- `tonight/YYYY-MM-DD.json` — date-specific exports alongside all-players.json
- `calendar/game-counts.json` — CalendarExporter (30 days back + 7 forward)
- `last_10_lines` array — null where line was missing
- `game_time` LTRIM — trimmed in SQL
- `injury_status` null → "available" — COALESCE in query
- `fatigue_level` uses "fresh"/"normal"/"tired"
- `player_lookup` in picks — was already in AllSubsetsPicksExporter

---

## Root Cause: Stale Export Pipeline

### Symptom
`results/latest.json` stuck on Feb 9 (2 days stale). Frontend reported stale data.

### Root Cause Chain
1. **Two Cloud Run services** (`phase5-to-phase6` and `phase5-to-phase6-orchestrator`) both had Pub/Sub subscriptions on `nba-phase5-predictions-complete`
2. Every Phase 5 completion triggered Phase 6 exports **twice concurrently**
3. `base_exporter._upload_blob_with_retry()` did `upload_from_string()` then `blob.patch()` — a two-step non-atomic operation
4. Concurrent writers raced on `patch()`, causing GCS 409 Conflict errors
5. Exports died partway through (e.g., 56/80 player files written)
6. No freshness monitoring existed to detect this — only file existence checks

### Fix
- Eliminated `patch()` call (set cache_control before upload — single atomic operation)
- Added `Conflict` to retry exceptions as defense-in-depth
- Deleted duplicate subscription and stale service
- Added freshness monitoring to canary

---

## Frontend Communication

### Resolved (tell frontend to remove workarounds)
| Item | Status |
|------|--------|
| `prediction.factors` | Now populated (up to 4 directional factors) |
| `recent_form` | Now populated (Hot/Cold/Neutral) |
| `minutes_avg` | Now populated (= season_mpg) |
| `tonight/YYYY-MM-DD.json` | Now generated for date browsing |
| `calendar/game-counts.json` | Now generated |
| `results/latest.json` stale | Fixed (race condition resolved) |
| `game_time` whitespace | Already trimmed |
| `injury_status` null | Already sends "available" |
| `fatigue_level` "rested" | Already sends "fresh" |
| `player_lookup` in picks | Was already there |
| Profile `team_abbr` | Added alongside `team` |
| Profile fg/3pt/ft separate fields | Added (string format kept for backwards compat) |
| `days_rest` workaround | Can be removed (was fixed earlier) |

### Not changing
| Item | Reason |
|------|--------|
| Confidence 0-100 scale | Changing to 0-1 would require backfilling 4 seasons |

### Known limitations
| Item | Detail |
|------|--------|
| 26 all-dash players | Zero historical lines — not fixable retroactively |
| 5 all-dash with lines | Missing `over_under_result` in player_game_summary — Phase 3 analytics gap |
| `news/latest.json` | Path is `player-news/nba/tonight-summary.json` and `player-news/nba/{lookup}.json` |

---

## Open Items for Next Session

### Should Do
- **Duplicate Phase 4→5 subscriptions**: 3 subscriptions on `nba-phase4-precompute-complete`. Same pattern as Phase 5→6 duplicate. Check:
  ```bash
  gcloud pubsub subscriptions list --project=nba-props-platform --format="table(name.basename(),topic.basename())" | grep phase4
  ```
- **Investigate 5 all-dash players with lines**: Players like Kevin Huerter (2 lines), Bennedict Mathurin (1 line) had `points_line` but no `over_under_result`. Phase 3 `player_game_summary` may not be computing O/U results for players with sparse line data.

### Nice to Have
- **Audit all duplicate Eventarc subscriptions**: The duplication pattern suggests old service versions leave orphan subscriptions during re-deploys. Consider a cleanup script.
- **News endpoint alignment**: Frontend expects `news/latest.json` but data is at `player-news/nba/tonight-summary.json`. Either redirect or tell frontend the correct path.

---

## Deployment Status

All services up to date, no drift. Builds succeeded.
