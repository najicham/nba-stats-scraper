# Session 319 Handoff

**Date:** 2026-02-21
**Commits:** `8d61df29` → `3e657734` (6 commits on main, all pushed + deployed)
**Focus:** Frontend data design, admin dashboard, daily ops, schema fixes

---

## What Was Built

### New GCS Endpoints (5 new exporters)

| Endpoint | Exporter File | Audience | Content |
|----------|--------------|----------|---------|
| `v1/best-bets/all.json` | `best_bets_all_exporter.py` | **End user (PRIMARY)** | Record + streak + today's picks + full history. Single file, ~200KB max. |
| `v1/best-bets/today.json` | `today_best_bets_exporter.py` | End user (backup) | Clean picks only. Superseded by all.json. |
| `v1/admin/dashboard.json` | `admin_dashboard_exporter.py` | **Admin** | Model health + signal health + subset performance + picks + filter funnel |
| `v1/admin/picks/{date}.json` | `admin_picks_exporter.py` | Admin | Per-date deep dive with all candidates + filter_summary |
| (existing endpoints unchanged) | | | |

All wired into `backfill_jobs/publishing/daily_export.py` as export types: `best-bets-all`, `best-bets-today`, `admin-dashboard`, `admin-picks`.

### Schema Changes (applied to production BQ)

| Table | Column Added | Type |
|-------|-------------|------|
| `prediction_accuracy` | `feature_quality_score` | FLOAT64 |
| `prediction_accuracy` | `data_quality_tier` | STRING |
| `signal_best_bets_picks` | `filter_summary` | STRING (JSON) |

The grading processor already writes `feature_quality_score` and `data_quality_tier` (lines 827-828 of prediction_accuracy_processor.py). Schema SQL now matches production. `filter_summary` is written as JSON by `SignalBestBetsExporter._write_to_bigquery()`.

### Admin Dashboard Data (dashboard.json contents)

Model health entries include full lifecycle data from model_registry:
- `model_id`, `family`, `registry_status` (production/active/deprecated)
- `is_production`, `enabled`, `parent_model_id`
- `production_start`, `production_end`
- `training_start`, `training_end`, `days_since_training`
- `eval_mae`, `eval_hr_edge3`, `feature_count`, `loss_function`, `quantile_alpha`
- Rolling HR: 7d/14d/30d with N counts
- Decay `state`: HEALTHY/WATCH/DEGRADING/BLOCKED/INSUFFICIENT_DATA

Subset performance entries include `label` (display name from `SUBSET_PUBLIC_NAMES`) and `losses` in each window.

`champion_model_state` at top level for status bar.

`filter_summary` with stable key set (documented in spec).

---

## Frontend Specs (4 docs)

All at `docs/08-projects/current/frontend-data-design/`:

| File | Content | Status |
|------|---------|--------|
| `01-API-SPEC.md` | Initial API spec (two audiences) | Superseded by 02 |
| `02-FRONTEND-PROMPT.md` | **Final end-user spec.** Single file, editorial layout, weekly accordion, no signals. | FINAL |
| `03-ADMIN-DASHBOARD-SPEC.md` | **Admin dashboard spec.** 5 sections, filter funnel, subset table. Updated with frontend review feedback. | FINAL |
| `04-ADMIN-DASHBOARD-FRONTEND-REVIEW.md` | Frontend team's review + feedback on admin spec | Reference |
| `05-MODEL-LIFECYCLE-SPEC.md` | **Model lifecycle + multi-model architecture.** Families, lineage, lifecycle stages. Has 4 open questions for frontend. | AWAITING FRONTEND REVIEW |

### Key Design Decisions (Locked)

- **Single file** for end users (`all.json`) — frontend chose Option A
- **Best Bets = landing page** — first nav item
- **Editorial layout** — full-width pick cards, not PlayerCards
- **Weekly accordion** — no calendar grid (too sparse)
- **Angles only** — no signal tags for end users
- **Admin at `/admin`** — same site, Firebase Auth, email allowlist

### Open Questions (05-MODEL-LIFECYCLE-SPEC.md)

1. Family-grouped vs flat table for model health?
2. Lineage display depth (full chain vs one-liner)?
3. Model ID truncation strategy?
4. Stale model visual warning beyond age badge?

---

## Other Deliverables

- **Daily ops checklist:** `docs/02-operations/daily-operations-checklist.md`
- **Session 319 handoff:** this file

---

## What's NOT Done

1. **Exports haven't run yet** — all.json, dashboard.json etc. will populate on next daily export cycle (~6 AM ET tomorrow). To test now: `PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2026-02-21 --only best-bets-all,admin-dashboard`
2. **Frontend build** — specs are ready, frontend can start
3. **C5 (deferred):** Signal observatory subsets for removed signals
4. **Frontend review of 05-MODEL-LIFECYCLE-SPEC.md** — 4 open questions on model display

---

## Files Changed This Session

**New files:**
- `data_processors/publishing/best_bets_all_exporter.py`
- `data_processors/publishing/today_best_bets_exporter.py`
- `data_processors/publishing/admin_dashboard_exporter.py`
- `data_processors/publishing/admin_picks_exporter.py`
- `docs/08-projects/current/frontend-data-design/01-API-SPEC.md`
- `docs/08-projects/current/frontend-data-design/02-FRONTEND-PROMPT.md`
- `docs/08-projects/current/frontend-data-design/03-ADMIN-DASHBOARD-SPEC.md`
- `docs/08-projects/current/frontend-data-design/05-MODEL-LIFECYCLE-SPEC.md`
- `docs/02-operations/daily-operations-checklist.md`

**Modified files:**
- `backfill_jobs/publishing/daily_export.py` — 5 new export types
- `data_processors/publishing/signal_best_bets_exporter.py` — writes filter_summary to BQ
- `schemas/bigquery/nba_predictions/prediction_accuracy.sql` — +2 columns
- `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` — +1 column
