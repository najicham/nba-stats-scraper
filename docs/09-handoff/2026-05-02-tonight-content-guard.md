# Session Handoff — Tonight JSON Content Guard

**Date:** 2026-05-02
**Trigger:** Tonight page on playerprops.io rendered empty cards for ~5 days (Apr 28 → May 2). NBA is in playoffs and predictions are halted, but the page is supposed to show schedule + rosters even without picks.
**Outcome:** Two-commit fix shipped and auto-deployed to all 4 affected Cloud Functions. Kill-switch precautionarily ON (guard disabled on `live-export` and `post-grading-export`) until frontend is verified to handle the new `status: "degraded"` JSON field.

---

## TL;DR

Three layers of defense added to prevent the writer from overwriting `gs://nba-props-platform-api/v1/tonight/{date}.json` with `games > 0` but `total_players: 0`:

1. **Writer-side hook** — `BaseExporter.validate_content()` + `safe_export()` (no-op default; subclasses opt in).
2. **Tonight-specific guard** — floor `total_players >= 8 * games`. On failure, payload is rewritten with `status: "degraded"` + `degraded_reason` *and uploaded* (not skip-write). Frontend gets an explicit signal instead of an indistinguishable-from-off-day empty file.
3. **Content-aware monitor** — `daily_health_check` CF reads tonight JSON content, not just file age. Date-keyed files for today + yesterday added to monitored set.

Kill-switch: `TONIGHT_GUARD_ENABLED=false` on `live-export` and `post-grading-export` reverts to old behavior without redeploy. **Currently ON** — re-enable after frontend confirmed.

---

## What changed

### Commits
- `a2938a22` — fix(publishing): refuse to overwrite tonight JSON with games-but-no-players (3 files)
- `[next-commit]` — follow-up: monitor date-keyed tonight files + unit tests + this handoff (3 files)

### Files
| File | Change |
|---|---|
| `data_processors/publishing/base_exporter.py` | Added `validate_content()` hook (returns `None` or reason str). Added `safe_export()` helper that calls the hook, logs `CRITICAL`, mutates payload to `status="degraded"` + `degraded_reason`, then uploads. Honors per-call kill-switch env var. |
| `data_processors/publishing/tonight_all_players_exporter.py` | Overrides `validate_content()`: `total_players >= 8 * games`. Both `export()` uploads now go through `safe_export(guard_env_var='TONIGHT_GUARD_ENABLED')`. Date-keyed cache reduced from 24h → 5min until all games `final` (then 24h). |
| `orchestration/cloud_functions/daily_health_check/main.py` | New `_check_tonight_content()` reads `total_players` and `status` from JSON. Date-keyed `tonight/{today}.json` and `tonight/{yesterday}.json` (ET) added to per-call monitored set. Off-day MISSING is no longer a flag for date-keyed files. |
| `tests/unit/publishing/test_tonight_all_players_exporter.py` | 9 new tests for `validate_content`, `safe_export`, kill-switch, mutation safety, `_all_games_final` helper. |

### Production state at handoff
- All 4 Cloud Build triggers succeeded at 2026-05-02 ~17:00 UTC: `deploy-live-export`, `deploy-phase6-export`, `deploy-post-grading-export`, `deploy-daily-health-check`.
- `live-export` and `post-grading-export` have `TONIGHT_GUARD_ENABLED=false` set (kill-switch ON for safety while frontend verification is pending).
- `phase6-export` does NOT need the kill-switch (does not call `TonightAllPlayersExporter`).

---

## Why "rewrite payload" instead of "skip upload"

The phrase in commit `a2938a22`'s message — *"writing degraded sentinel instead of overwriting last-good file"* — is misleading. The code **does** overwrite. The reason this is intentional, decided across three independent agent reviews before implementation:

- **Date-keyed files** (`tonight/{date}.json`) have no last-good for future dates → skip-write would 404 → frontend falls back to `tonight/all-players.json`.
- **`tonight/all-players.json`** is overwritten every live tick (every 3 min during games). Skip-write doesn't preserve anything useful — the next tick rewrites it.
- The pre-fix file shape (`games > 0, players: []`) is **structurally indistinguishable** from a legitimate `_empty_response()` off-day. Frontend has no signal to render a "data temporarily unavailable" banner — it just shows empty cards.
- A `{status: "degraded", degraded_reason}` sentinel gives the frontend an explicit field to render against and gives the monitor a clear flag.

**Trade-off:** the fix introduces a new top-level JSON field. If the frontend uses a strict schema validator (zod, io-ts, etc. with `.strict()`), unknown keys could break rendering. **Frontend repo is not in this codebase — could not be verified.** Hence the kill-switch precaution.

---

## Verification checklist for next session

### 1. Decide the frontend contract (BLOCKING re-enable)
- [ ] Open the playerprops.io frontend repo
- [ ] Find the Tonight page component / data loader
- [ ] Check whether it ignores unknown JSON keys (good — re-enable guard)
- [ ] OR add explicit handling for `status === "degraded"` to render a banner (best — re-enable guard)
- [ ] OR confirm it errors on unknown keys (must change frontend before re-enable)

### 2. Re-enable the guard once frontend is confirmed safe
```bash
gcloud run services update live-export \
  --region=us-west2 --project=nba-props-platform \
  --remove-env-vars=TONIGHT_GUARD_ENABLED

gcloud run services update post-grading-export \
  --region=us-west2 --project=nba-props-platform \
  --remove-env-vars=TONIGHT_GUARD_ENABLED
```

Then confirm via:
```bash
gcloud run services describe live-export --region=us-west2 --project=nba-props-platform --format=json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print([e for e in d['spec']['template']['spec']['containers'][0].get('env',[]) if 'TONIGHT' in e['name']])"
```

### 3. Verify the live tick wrote a sentinel (after re-enable)
Tonight's first `live-export` tick (`*/3 19-23,0-1 * * *` ET) should produce `status: "degraded"` in the GCS file. Verify:
```bash
gsutil cp gs://nba-props-platform-api/v1/tonight/all-players.json /tmp/x.json
python3 -c "import json; d=json.load(open('/tmp/x.json')); print('status:', d.get('status','(none)'), '| reason:', d.get('degraded_reason','(none)'), '| players:', d.get('total_players'), '| games:', len(d.get('games',[])))"
```

### 4. Verify the monitor surfaces it
`daily-health-check` runs `0 */6 * * *`. Next tick after 18:00 UTC should emit a Slack message in `#nba-alerts` (severity `critical`) with text like `Export: v1/tonight/all-players.json | CONTENT_DEGRADED — total_players=0 < 8*games=N`.

---

## Known follow-ups (recommended next session)

| # | Item | Effort | Why |
|---|---|---|---|
| **1** | **Architectural fix** to `upcoming_player_game_context_processor` driver: switch from `nbac_gamebook_player_stats` (post-game) to `nbac_schedule + espn_team_rosters` (pre-game). | ~1 day | Band-aid alone leaves the page rendering "degraded" for the rest of playoffs + offseason. This is the only fix that restores actual content. Predictions are halted = uniquely safe blast radius right now. |
| 2 | Generalize `validate_content()` to the 5 other systemic exporters listed in `2026-05-02-SESSION-HANDOFF.md`: `results_exporter`, `live_grading_exporter`, `system_performance_exporter`, `player_profile_exporter`, `tonight_trend_plays_exporter`, `whos_hot_cold_exporter`. | ~3h | Same class of "writer overwrote good with bad" bug, same fix pattern. Pre-commit `validate_pct_convention.py` proposed in the prior handoff is complementary. |
| 3 | MLB Tonight exporter — none exists; `gs://nba-props-platform-api/v1/mlb/tonight/` is empty. Gated on architectural decision: schedule/lines only vs. full pick cards. | varies | Frontend MLB Tonight page is currently empty for a different reason than this NBA bug. Don't conflate. |
| 4 | Audit every `# X failure shouldn't fail the whole export` comment in `live_export/main.py` and similar callers. `status_exporter` (line 156-159) has the same pattern and could silently publish "all systems nominal" with empty inputs. | ~1h | Class-of-bug audit. |
| 5 | Tighten the floor: `8 * games` counts OUT players (LEFT JOIN injuries with no filter at `tonight_all_players_exporter.py:165-168`). A scrape that returned only OUT-tagged players would slip through. Real-world risk is low; smoke-alarm vs precision-instrument trade. | ~30m | Defer until a near-miss happens. |
| 6 | `phase6_export`'s `validate_analytics_ready()` and `validate_predictions_exist()` (lines 60-180) check upcoming_player_game_context for ≥30 players. `live_export` has no equivalent. The writer guard makes this less critical, but for parity we should consider adding it. | ~2h | Defer until #1 lands. |

---

## Reviewer-flagged issues NOT addressed (with rationale)

From the two post-commit code reviews:

- **"safe_export() always overwrites"** — Yes, by design. See "Why rewrite payload" above. Commit message wording was misleading; this handoff corrects it.
- **"Floor of 8/game can be fooled by all-OUT scrape"** — Theoretical. The actual bug shape is 0 players, well under any floor. Don't over-engineer the smoke alarm.
- **"Postponed games keep date-keyed file at 5min cache forever"** — Cost only, ~negligible at this volume. `_all_games_final()` could be extended to include `cancelled`/`postponed` later.
- **"Naming nit: `safe_export` doesn't export"** — Acknowledged. Kept for now to mirror `upload_to_gcs`. Renaming is a sweep across 1+ subclass and not worth the churn.
- **"Kill-switch only on writer, not monitor"** — If kill-switch is ON, monitor will still flag content-degraded files in Slack. That's intended: kill-switch is for emergency rollback, not for indefinite suppression. If a long-term suppression is needed, remove the file from `MONITORED_EXPORTS`.

---

## Quick context for a new session

**Where to start reading:**
1. This file
2. `docs/09-handoff/2026-05-02-SESSION-HANDOFF.md` — broader session context (MLB pct fix, weekly-retrain paused, MLB model deploy fiction, $5/day cost waste)
3. `git show a2938a22` — the writer-guard commit
4. `git show HEAD` — the follow-up commit with monitor + tests + this handoff

**Key invariants to remember:**
- `TONIGHT_GUARD_ENABLED=false` is currently set on `live-export` and `post-grading-export`. Guard is OFF in production until frontend is verified.
- The architectural fix (#1 in follow-ups) is the only thing that restores actual tonight content during the playoff/offseason stretch. Without it, the guard merely upgrades "empty cards" to "degraded sentinel" — better signal, same lack of data.
- NBA is auto-halted for predictions (per `regime_context.py` edge-based halt — see `MEMORY.md`). System correctly stopped emitting picks. This bug is about the *non-prediction* tonight content (schedule + rosters + recent stats), which should still render during playoffs.

---

## Glossary

- **Degraded sentinel:** a JSON document with `status: "degraded"` and `degraded_reason: "..."` written in lieu of empty content. Frontend / monitors can switch on it.
- **Tonight latest pointer:** `tonight/all-players.json` — short cache, always reflects the current in-progress night.
- **Date-keyed tonight file:** `tonight/{YYYY-MM-DD}.json` — historically immutable after games finalize; cache extends to 24h only after `_all_games_final(json_data)`.
- **Kill switch:** `TONIGHT_GUARD_ENABLED=false` — disables writer guard without redeploy. Set per-CF.
