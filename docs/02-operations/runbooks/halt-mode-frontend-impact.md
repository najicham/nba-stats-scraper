# Halt-Mode Frontend Impact — Operator Checklist

**Audience:** backend operators about to ship changes that affect halt-mode or empty-payload publishing.
**Why this exists:** April 2026 incident — `/mlb` rendered nothing for ~5 days because frontend's master loading guard depended on NBA `gameCounts` being populated. NBA halt → empty feed → frontend never settled. See `docs/09-handoff/2026-05-04-mlb-tonight-bug-followups.md`.

## When This Matters

This checklist applies before merging any change that touches:

- `ml/signals/regime_context.py` (auto-halt logic, edge floors, market regime)
- `ml/signals/signal_best_bets_exporter.py` (BB pick output, halt sentinels)
- `data_processors/publishing/**` (any GCS JSON exporter — NBA or MLB)
- `data_processors/publishing/*_exporter.py` content-guard / sentinel writes
- Any code path that can publish `{ "status": "degraded" }`, an empty `games[]`, an empty `picks[]`, or a 404-able date-keyed file
- Schedulers that gate exports on game presence (e.g. `same-day-phase3`, `tonight-export`)

## Pre-Change Checklist

- [ ] **Verify the frontend handles your empty payload.** Open `props-web/src/lib/types.ts` and confirm consumers use `?? []` / optional chaining for any field your change might omit. If the field is newly optional, update the type.
- [ ] **Match the GCS sentinel format the frontend expects.** Tonight content guard writes `{ "status": "degraded", "reason": "..." }` — do not invent a new shape. See `tonight-content-guard.md`.
- [ ] **Test both routes after deploy.** Hit `https://playerprops.io/nba` and `https://playerprops.io/mlb` in a real browser. Both must render content (or an explicit empty/degraded banner) within ~5 seconds. A spinner that never stops = bug.
- [ ] **Check `gameCounts.json` is still populated.** Many frontend gates depend on it. If your change suppresses writes during halt, confirm at minimum a `{}` (empty object) is published, not a 404.
- [ ] **For date-keyed exporters:** verify both the latest pointer (`leaderboard.json`) and the date-keyed file (`history/{date}.json`) are written. Frontend falls back across both — missing one breaks the date selector.
- [ ] **Read `props-web/CLAUDE.md` § Halt-Mode Behavior** to refresh on the per-sport-state contract before changing cross-cutting publishing logic.

## If the Frontend Breaks

1. **Roll back the backend change first.** `git revert` and re-deploy via Cloud Build. Frontend is a thin client — backend payload shape is the contract.
2. **Verify GCS payload directly.** `curl -s https://storage.googleapis.com/nba-props-platform-api/v1/<path> | jq` — confirm shape matches what `props-web/src/lib/types.ts` expects.
3. **If the bug is frontend-side** (guard never resolves, wrong cross-sport coupling), open an issue in `props-web` referencing this runbook and the broken commit. Do NOT paper over with backend hacks.

## Cross-Links

- Frontend project instructions: `~/code/props-web/CLAUDE.md`
- April 2026 incident handoff: `docs/09-handoff/2026-05-04-mlb-tonight-bug-followups.md`
- Tonight content guard: `.claude/projects/-home-naji-code-nba-stats-scraper/memory/tonight-content-guard.md`
- BACKEND CONTRACT in `~/code/props-web/CLAUDE.md` lists all GCS endpoints the frontend reads.
