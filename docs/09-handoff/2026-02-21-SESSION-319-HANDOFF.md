# Session 319 Handoff

**Date:** 2026-02-21
**Focus:** Frontend data design, daily ops checklist, backend endpoints + schema fixes

## What Was Done

### Infrastructure (Earlier This Session)
- Added `ml/**` to 3 Cloud Build triggers (phase6-export, live-export, post-grading-export)
- Created missing `deploy-post-grading-export` trigger
- Pushed Session 318 commits to origin (were never pushed)
- All 3 Cloud Functions rebuilt with `0bfb9d3` — Session 318 signal cleanup now LIVE
- Verified: 16 signals deployed, UNDER 7+ unconditional block, rest_advantage week 15 cap

### C1: prediction_accuracy Schema Fix
- Added `feature_quality_score FLOAT64` and `data_quality_tier STRING` to `prediction_accuracy.sql`
- Columns already existed in production BQ (previously added via ALTER TABLE)
- Schema SQL now matches production — grading processor already writes these (lines 827-828)

### C2: `v1/best-bets/today.json` Endpoint (NEW)
- **New file:** `data_processors/publishing/today_best_bets_exporter.py`
- Strips internal metadata (composite_score, signal_tags, model IDs)
- Keeps: player, team, opponent, direction, line, edge, pick_angles (max 3), rank
- Integrated into `daily_export.py` as `best-bets-today` export type
- **Superseded by `all.json`** — kept for backwards compatibility

### C3: `v1/admin/picks/{date}.json` Endpoint (NEW)
- **New file:** `data_processors/publishing/admin_picks_exporter.py`
- Full metadata: all signal tags, composite scores, model provenance, filter_summary
- Includes ALL candidates (not just top picks) with edge and quality scores
- Per-date deep dive for debugging "why was player X picked/not picked?"

### C4: filter_summary in BQ
- Added `filter_summary STRING` to `signal_best_bets_picks.sql` schema + production BQ table
- `SignalBestBetsExporter` now writes JSON-serialized filter_summary with each pick
- Enables historical analysis of filtering decisions

### Consolidated Best Bets (`v1/best-bets/all.json`) — PRIMARY FRONTEND ENDPOINT
- **New file:** `data_processors/publishing/best_bets_all_exporter.py`
- Single file with record + streak + today's picks (with angles) + full history by week/day
- Frontend team chose single-file over three separate files (~50-200 KB, one fetch)
- Day-level `status` field: `"pending"` / `"sweep"` / `"split"` / `"miss"` for color coding
- Today's picks appear in both `today` (hero) and `weeks` (history continuity)

### Admin Dashboard (`v1/admin/dashboard.json`)
- **New file:** `data_processors/publishing/admin_dashboard_exporter.py`
- Consolidated admin view: model health, signal health, subset performance, picks, filter funnel
- Single file replaces need to fetch 4+ separate admin endpoints
- Lives at `playerprops.io/admin` behind Firebase Auth (Google sign-in, email allowlist)

### Frontend Specs (Final)
- **End-user spec:** `docs/08-projects/current/frontend-data-design/02-FRONTEND-PROMPT.md`
  - Editorial layout, full-width pick cards, weekly accordion (no calendar)
  - No signal tags for end users (angles only)
  - Best Bets as first nav item / landing page
- **Admin spec:** `docs/08-projects/current/frontend-data-design/03-ADMIN-DASHBOARD-SPEC.md`
  - Dense dashboard: status bar, picks table, filter funnel, subset grid, model/signal health
  - Per-date deep dive via date picker loading `admin/picks/{date}.json`
  - Auth: Firebase + Google sign-in, 1-email allowlist

### Documentation
- **Daily operations checklist:** `docs/02-operations/daily-operations-checklist.md`

## Files Changed

| File | Change |
|------|--------|
| `schemas/bigquery/nba_predictions/prediction_accuracy.sql` | +2 columns |
| `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` | +1 column (filter_summary) |
| `data_processors/publishing/signal_best_bets_exporter.py` | Write filter_summary to BQ |
| `data_processors/publishing/today_best_bets_exporter.py` | **NEW** |
| `data_processors/publishing/admin_picks_exporter.py` | **NEW** |
| `data_processors/publishing/best_bets_all_exporter.py` | **NEW** (primary frontend endpoint) |
| `data_processors/publishing/admin_dashboard_exporter.py` | **NEW** |
| `backfill_jobs/publishing/daily_export.py` | +5 export types |
| `docs/08-projects/current/frontend-data-design/01-API-SPEC.md` | **NEW** |
| `docs/08-projects/current/frontend-data-design/02-FRONTEND-PROMPT.md` | **NEW** (final frontend spec) |
| `docs/08-projects/current/frontend-data-design/03-ADMIN-DASHBOARD-SPEC.md` | **NEW** (admin spec) |
| `docs/02-operations/daily-operations-checklist.md` | **NEW** |

## New GCS Endpoints

| Endpoint | Audience | Cache | Content |
|----------|----------|-------|---------|
| `v1/best-bets/all.json` | End user | 300s | Record + today + history (single file) |
| `v1/best-bets/today.json` | End user | 300s | Today's clean picks (backup) |
| `v1/admin/dashboard.json` | Admin | 300s | Full system state + picks + subsets |
| `v1/admin/picks/{date}.json` | Admin | 3600s | Per-date deep dive with all candidates |

## Deployment Notes

- Push to main → auto-deploys via Cloud Build triggers
- New exporters run on next daily export cycle
- BQ schema changes already applied to production
- No re-export of historical files needed

## What's Next

1. **Frontend:** Build Best Bets page from `02-FRONTEND-PROMPT.md`
2. **Frontend:** Build admin dashboard from `03-ADMIN-DASHBOARD-SPEC.md`
3. **C5 (deferred):** Signal observatory subsets for removed signals
4. **Future:** Push notifications, shareable pick cards, per-date admin deep dive
