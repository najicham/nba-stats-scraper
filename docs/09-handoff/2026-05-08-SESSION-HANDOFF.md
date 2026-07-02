# Session Handoff — 2026-05-08

**Status at start of next session:** NBA halted (playoffs), MLB healthy, /mlb date selector now wired (backend writes date-keyed history; frontend fetches per selected date).

---

## What shipped this session

### MLB date-keyed leaderboard (closes the architectural gap from 2026-05-04)
- **Backend** (nba-stats-scraper, commit `950daaf2`):
  - `data_processors/publishing/mlb/mlb_pitcher_exporter.py` writes a second copy to `gs://nba-props-platform-api/v1/mlb/pitchers/history/{game_date}.json` (CACHE_LONG) on every run, alongside the unchanged latest pointer at `mlb/pitchers/leaderboard.json`.
  - Returns `history_path` in the export result.
  - Auto-deployed via Cloud Build (`deploy-phase6-export`, `deploy-post-grading-export`, `deploy-live-export` all WORKING at push time).
- **Frontend** (props-platform-web, commit `c3ca12e`):
  - `src/lib/pitchers-api.ts` — `fetchPitcherLeaderboard(date?)`. Today/undefined → latest pointer; past → `mlb/pitchers/history/{date}.json`.
  - `src/app/[sport]/page.tsx` — MLB effect deps now `[sport, selectedDate]`, clears state on date change, passes `formatDateForApi(selectedDate)`. Empty-state UI ("No leaderboard for this date") rendered when fetch returns null.
  - Vercel auto-deployed.

**Caveat for the user:** No retroactive backfill — past dates before deploy will show the empty state until the backend has accumulated history (one history file per scheduled run going forward). A backfill script that rebuilds payloads from BigQuery for prior days is open if needed.

### Daily steering report run (partial — 2026-05-08 09:34 PT)

```
NBA: HALTED (playoffs)
  All 7 NBA models: INSUFFICIENT_DATA (last data 2026-05-07, 0 picks/0 graded)
  Days since training: 34-35
  Edge-based auto-halt: still active

MLB: HEALTHY, NORMAL regime
  League macro 7d: vegas MAE 1.89, model MAE 1.66 (model AHEAD by 0.23), avg K 4.8
                   vegas bias +0.22, model HR 54.0%, BB HR 64.7% (N=17)
  7d trend: 47.6% (Apr 28) → 64.7% (May 7) — recovering
  Best bets:
    Last 7d:    8-3  (72.7%)  N=11
    Days 8-14:  8-8  (50.0%)  N=16
    Days 15-30: 12-9 (57.1%)  N=21
  Signal health: HOT — elite_peripherals_over (80%), k_trending_over (80%), recent_k_above_line (66.7%)
                 WATCH/COLD — pitch_efficiency_depth_over (33.3% → 25.0% 7d)

DEPLOYMENT DRIFT:
  ❌ validation-runner STALE — deployed commit 12b9f65, current 950daaf2 (last change 2026-04-08)
  ⚠️  nba-phase2-raw-processors, nba-admin-dashboard: source timestamps unreadable (probe issue)
  ✓ 13 other services up to date; model deployment matches manifest; traffic on latest revisions

RISK FACTORS:
  - MLB schedule loaded only for today (15 games). Next 6 days NOT loaded — schedule scraper may not have run.
  - validation-runner is 1 month stale.
  - pitch_efficiency_depth_over signal degrading (45.5% 30d → 25.0% 7d, N=4 — small but trend wrong).

RECOMMENDATION: ALL CLEAR for MLB betting today.
```

---

## What the next session should do — explicit checklist

### 1. Finish the morning routine (started but interrupted)
- [ ] `/best-bets-config` — single-pane view of current thresholds, active models, signals, sync status. **Skipped this session** — run first.
- [ ] `/validate-daily` — full pipeline orchestration health check across all 6 phases. **Skipped this session** — run second.

### 2. Investigate the schedule freshness gap
**Symptom:** `nba-props-platform.mlb_raw.mlb_schedule` only has rows for `2026-05-08` when querying `BETWEEN CURRENT_DATE() AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)`.
- [ ] Check whether the MLB schedule scraper ran in the last 24h. Cloud Scheduler likely under `mlb-schedule-*`.
- [ ] If stale, kick a manual run that writes 7+ days ahead. Tomorrow's predictions need next-day games loaded by morning.
- [ ] Verify normal cadence — scheduler timing + frequency.

### 3. Validate the MLB date-keyed leaderboard end-to-end
The 10:45 AM ET and 1 PM ET pitcher exports (`mlb-pitcher-export-morning`, `mlb-pitcher-export-pregame`) should produce the first history files today. After they run:
- [ ] `gsutil ls gs://nba-props-platform-api/v1/mlb/pitchers/history/` — confirm `2026-05-08.json` exists.
- [ ] `curl -sS https://playerprops.io/api/proxy/mlb/pitchers/history/2026-05-08.json | jq '.game_date, .tonight.count'` — confirm content.
- [ ] In a browser, load `/mlb`, change to today's date via the picker, confirm panel re-renders. Then change to a date with no history file (anything before 2026-05-08), confirm the "No leaderboard for this date" empty state renders.

### 4. Fix the validation-runner drift (low priority but easy)
- [ ] `gcloud builds list --region=us-west2 --filter="trigger_id:deploy-validation-runner"` — see why auto-deploy didn't fire.
- [ ] If trigger is healthy, push a no-op touch or manually rebuild. If trigger is misconfigured, fix it.

### 5. Address handoff items still open from 2026-05-04 followups
From `docs/09-handoff/2026-05-04-mlb-tonight-bug-followups.md`:
- [ ] **F1** — Playwright sport-render spec (~30m, single highest-leverage item — would have caught the original /mlb regression on commit).
- [ ] **F2** — Synthetic HTML check in `daily_health_check` CF (~3h).
- [ ] **F3** — Frontend CLAUDE.md + halt-mode runbook (~3h).

### 6. Phase 3 scheduler decision (carried from 2026-05-03)
Other Phase 3 schedulers (`evening-analytics-10pm-et`, `overnight-analytics-6am-et`, `same-day-phase3-tomorrow`, `evening-analytics-6pm-et`) remain PAUSED. **Decision needed pre-NBA-resume in October**, not urgent during halt.

---

## Context for the next session

### What's healthy and working
- Tonight content guard (ARMED, Sentinel verified end-to-end on 2026-05-03).
- `same-day-phase3` scheduler RESUMED after Apr 28+ outage.
- MLB grading (fixed Session 520, backfilled Apr 1-9: 6-6).
- MLB worker auto-deployed (Session 514).
- All Cloud Run traffic-routing fixes from Sessions 516+520 holding.
- Edge-based auto-halt active and correctly silencing NBA.

### Known structural issues
- **NBA**: All 7 models BLOCKED, 34-35 days stale. Do **not** retrain — late-season data poisons. See MEMORY notes on `cap_to_pre_late_season()` (Session 514) and the auto-halt fix (Session 516).
- **MLB schedule freshness**: only today loaded — recurring or one-off?
- **validation-runner CF**: 1 month stale, no functional impact observed.

### Where to look first
1. `MEMORY.md` (always loaded).
2. `docs/09-handoff/2026-05-04-mlb-tonight-bug-followups.md` — F1-F7 followups.
3. `docs/09-handoff/2026-05-02-tonight-content-guard.md` — content guard architecture.
4. `docs/09-handoff/2026-05-02-SESSION-HANDOFF.md` — broader cross-system audit.

---

## Files touched this session

- `data_processors/publishing/mlb/mlb_pitcher_exporter.py` — date-keyed history write (commit `950daaf2`)
- `props-platform-web/src/lib/pitchers-api.ts` — date-aware fetcher (commit `c3ca12e`)
- `props-platform-web/src/app/[sport]/page.tsx` — selectedDate wiring + empty state (commit `c3ca12e`)
- `docs/09-handoff/2026-05-08-SESSION-HANDOFF.md` — this file

## Production state at end of session

- /mlb renders today's pitchers correctly
- Date selector wired but past-date data not yet accumulated (will populate after first scheduled MLB pitcher export run)
- Backend + frontend deploys confirmed pushed; verifying first history-file write is item #3 above
- No pending alerts, no halts changed, no model deployments changed
