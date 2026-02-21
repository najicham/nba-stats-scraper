# Session 320 Handoff

**Date:** 2026-02-21
**Focus:** Daily ops, export testing, bug fixes, production wiring, frontend comms

---

## What Was Done

### 1. Daily Steering Report

Full steering report run. Key findings:
- **Model health (as of 2/19):** Champion `catboost_v9` is INSUFFICIENT_DATA (N=3 in 7d, 14d old). V12_noveg HEALTHY at 80% HR. V12_noveg_q45 BLOCKED at 44.4%.
- **Market regime:** RED across the board — compression 0.455, max edge 3.73 (7d avg), zero edge 5+ picks/day. Post-ASB market fully compressed.
- **Best bets:** 7d: 2-4 (33.3%), 14d: 6-10 (37.5%), 30d: 29-18 (61.7%). Short-term ugly but tiny N from ASB gap.
- **Recommendation:** WATCH. Model is 3 days fresh. Let post-ASB market normalize this week before any decisions.

### 2. Daily Validation

Pipeline is functional. All 12+ models produced 36 predictions each across 6 games. Feature store has 109 rows for 6 games. UPCG has 210 players.

**Key finding:** Zero edge 3+ picks today. Zero edge 5+ picks. Market fully compressed — system correctly producing nothing to bet on. Pre-game signal is RED (UNDER_HEAVY, 8.3% OVER).

Feature quality at 35.8% ready (39/109) — zero-tolerance blocking working as designed.

### 3. Updated 05-MODEL-LIFECYCLE-SPEC.md

Replaced "Questions for Frontend" section with "Frontend Decisions (Resolved)":
1. Family-grouped table (Option A)
2. One-liner lineage only
3. Family badge + short ID suffix + tooltip
4. Yellow left-border for stale models (days_since_training > 14)

### 4. Added `season` Field to Exporters

Added dynamic `_compute_season_label()` to both:
- `data_processors/publishing/best_bets_all_exporter.py`
- `data_processors/publishing/admin_dashboard_exporter.py`

Logic: month >= 10 → `"{year}-{year+1}"`, else `"{year-1}-{year}"`. Verified in exports: `"season": "2025-26"`.

### 5. Fixed Column Name Bugs in New Exporters

Two exporters had BQ column name mismatches when querying `player_prop_predictions`:

| File | Bug | Fix |
|------|-----|-----|
| `admin_dashboard_exporter.py` | `line_value` → column doesn't exist | Changed to `current_points_line` |
| `admin_picks_exporter.py` | `line_value` + `player_name` + `team_abbr` → don't exist | Changed to `current_points_line AS line_value`, `player_lookup AS player_name`, removed `team_abbr` |

### 6. Wired New Export Types into Production Triggers

**Problem:** The 4 new export types were in `daily_export.py` but no production trigger sent them.

**Fixed in 2 files:**

| File | Change |
|------|--------|
| `orchestration/cloud_functions/phase5_to_phase6/main.py` | Added `best-bets-all`, `best-bets-today`, `admin-dashboard`, `admin-picks` to `TONIGHT_EXPORT_TYPES` |
| `bin/deploy/deploy_phase6_scheduler.sh` | Added `admin-dashboard`, `admin-picks` to `phase6-daily-results` job (5 AM ET); added `best-bets-all`, `best-bets-today` to `phase6-tonight-picks` job (1 PM ET) |

**NOT YET DEPLOYED:** These changes need `git push` (auto-deploys CF) + `./bin/deploy/deploy_phase6_scheduler.sh` (updates scheduler jobs).

### 7. Tested All New Exports Successfully

All 3 new export types verified in GCS:

| File | Size | Content |
|------|------|---------|
| `v1/best-bets/all.json` | 55KB | season: 2025-26, record 92-32 (74.2%), 0 picks today |
| `v1/admin/dashboard.json` | 17KB | 10 models, 25 subsets, champion INSUFFICIENT_DATA |
| `v1/admin/picks/2026-02-21.json` | 97KB | 447 candidates, 0 picks (all filtered) |

---

## What's NOT Done

### Must Do (Next Session)

1. **Git push + deploy** — All changes are local. Push to trigger auto-deploy of:
   - Phase 5→6 orchestrator (new export types)
   - Admin dashboard exporter (column fix)
   - Admin picks exporter (column fix)
   - Best bets all exporter (season field)

2. **Run scheduler deploy** — After push: `./bin/deploy/deploy_phase6_scheduler.sh` to update the scheduler jobs with new export types.

3. **Ghost signal cleanup** — `cold_snap`, `home_dog`, `minutes_surge`, `prop_value_gap_extreme` appear in `signal_health_daily` despite being removed. Root cause: `signal_health.py` has no allowlist — it processes whatever tags exist in `pick_signal_tags` table. Fix options:
   - Add `ALLOWED_SIGNALS` filter to `compute_signal_health()`, OR
   - Purge stale signal tags from `pick_signal_tags`

4. **V12_noveg_q45 BLOCKED** — At 44.4% HR, 25 days stale. Needs retrain or retirement decision.

5. **Quantile models 25 days stale** — q43/q45 models approaching retrain threshold. Monitor this week.

6. **Audit `season` field across ALL exporters** — We added `"season": "2025-26"` to `best_bets_all_exporter.py` and `admin_dashboard_exporter.py`, but NOT to:
   - `today_best_bets_exporter.py` — should probably have it (end-user facing)
   - `admin_picks_exporter.py` — should probably have it (per-date admin view)
   - Any other existing exporters (`signal_best_bets_exporter.py`, `tonight_exporter.py`, etc.) — audit whether they need a season field too
   - Also verify that `all.json` record/weeks data is actually scoped to the current season only (not bleeding across seasons). Check the BQ queries — do they filter by season start date (e.g., `>= '2025-10-22'`) or just pull all historical data?

### Deferred

- **Frontend build** — All specs finalized, all questions answered, data endpoints live. Frontend can build.
- **Backfill exports for historical dates** — `best-bets/all.json` only has data from today's export run. Historical `admin/picks/{date}.json` files can be backfilled: `PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date YYYY-MM-DD --only best-bets-all,admin-dashboard,admin-picks`
- **validation-runner deployment drift** — 3 commits behind but all are docs/publishing changes, not functional. Low priority.
- **`today_best_bets_exporter.py` redundancy** — Superseded by `all.json` but cheap to run. No action needed.

---

## Files Changed

**Modified:**
- `docs/08-projects/current/frontend-data-design/05-MODEL-LIFECYCLE-SPEC.md` — Replaced open questions with resolved answers
- `data_processors/publishing/best_bets_all_exporter.py` — Added `_compute_season_label()`, `season` field
- `data_processors/publishing/admin_dashboard_exporter.py` — Added `_compute_season_label()`, `season` field, fixed `line_value` → `current_points_line`
- `data_processors/publishing/admin_picks_exporter.py` — Fixed `line_value`/`player_name`/`team_abbr` column mismatches
- `orchestration/cloud_functions/phase5_to_phase6/main.py` — Added 4 new export types to `TONIGHT_EXPORT_TYPES`
- `bin/deploy/deploy_phase6_scheduler.sh` — Added new export types to scheduler jobs

**New:**
- `docs/09-handoff/2026-02-21-SESSION-320-HANDOFF.md` — This file

---

## Key Context for Next Session

- **Market is compressed post-ASB.** Zero edge 5+ picks. This is expected and will likely normalize over the coming week as lines settle.
- **Champion model is 3 days fresh** (retrained Feb 18, promoted Feb 19). Do NOT retrain or switch. Let it accumulate data.
- **Frontend has everything it needs.** Specs finalized, data endpoints live, all questions answered. The frontend message about season scoping and lifecycle decisions should be sent.
- **Season field added dynamically.** Both `all.json` and `dashboard.json` now include `"season": "2025-26"` computed from the export date.
