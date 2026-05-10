# Pipeline State Redesign — Off-Season 2026

**Started:** 2026-05-09
**Target completion:** before NBA preseason (~2026-09-30)
**Scope:** Restructure NBA stats pipeline so data gaps are impossible-by-design, halt mode is first-class, monitoring is unified, and historical backfill (Oct 2025 – Feb 2026) is recovered.

---

## Why this exists

Two recurring failure modes prompted a full audit:

1. **109 days of NBA scraper output absent from GCS** for 2025-10-21 → 2026-02-06 (most of the regular season). Root cause: no scheduled tool checks historical date coverage; gaps are only noticed when something downstream breaks.
2. **`best-bets/all.json` frozen since 2026-04-18** because `post_grading_export` early-returns when `graded_count == 0`, before the history exporter runs. Root cause: halt-mode behavior is split across multiple files with no single source of truth.

Two earlier incidents (Dec 2025 – Jan 2026 lost 26 days; April 2026 `/mlb` broken 5 days) follow the same pattern: silent failure during off/idle states, caught by the user.

This project replaces ad-hoc calendar logic and scattered monitoring with a **date-grid + first-class halt-state** model.

---

## Phases (12 total)

| # | Phase | Status | Deliverable |
|---|---|---|---|
| A | Bug fixes + scaffolding | in_progress | This doc; cap_to_pre_late_season fix; post_grading_export split; rescue-gate 5→6; skill drift cleanup |
| B | halt_state as first-class state | pending | BQ table + writer CF + BaseExporter.halt_envelope; wired to all NBA Phase 6 exporters; frontend HaltBanner |
| C | expected_outputs date-grid | pending | BQ table + planner CF; one row per (date, phase, output) for next 14d + 2024-25 + 2025-26 historical seed |
| D | Unified observability layer | pending | shared/observability/metrics.py; Cloud Monitoring custom metrics; reconciler CF; nba-pipeline-health dashboard |
| E | Self-healing gap detector | pending | gap_detector CF → Pub/Sub backfill trigger; scraper-gap-backfiller subscribes; retire historical_completeness_monitor |
| F | Backfill Oct 2025 – Feb 2026 | pending | Re-scrape 109 days NBA.com data; document recovered vs lost; rerun Phase 2/3/4 |
| G | Cloud Monitoring alerts + retire monitors | pending | 3 alert policies; alert-router CF; retire 8 of 10 monitoring CFs; drop month: "10-4" filters |
| H | Signal/filter/skill registry | pending | shared/registry/{signals,filters}.yaml; pre-commit drift hook; skill file sweep |
| I | Frontend monitoring | pending | One GCP uptime check + content matcher; Sentry un-suppress; stuck-loading watchdog |
| J | Frontend bug fixes (B + C) | pending | sessionStorage banner persistence; VirtualizedGrid sub-640px overflow |
| K | Documentation refresh | pending | CLAUDE.md; 01-architecture; 02-operations runbooks; session-learnings; handoff; memory cleanup |
| L | Pre-presentation verification | pending | End-to-end demo path; rollback plan; on-call cheatsheet |

Issue A (Best Bets stuck loading) is fixed by Phase A (immediate) and Phase B (structural).

---

## Sequencing

- **A → B → C** are foundational; each enables the next.
- **D, E** depend on C (date-grid is the contract).
- **F (backfill)** runs in parallel from week 2 onward; uses E's gap_detector once available.
- **G** depends on D for the metrics emitter.
- **H, I, J** are independent tracks; can run in parallel.
- **K** (docs) updates continuously; final pass after L.
- **L** is the demo dress-rehearsal.

---

## Non-goals

- Don't lock down all 49 `allUsers` services — limit to `prediction-coordinator` + `prediction-worker` (budget-burn risk). Full IAM sweep is a separate project.
- Don't migrate to a new BQ project / region.
- Don't rewrite scrapers; only the orchestration + observability layer.
- Don't change the Phase 6 JSON public schema in breaking ways. `halt_active`/`halt_reason`/`halt_since` are additive.

---

## Risk + rollback

- **Auto-deploy from main** means every push deploys. Land changes incrementally; keep MLB live throughout.
- **halt_state cutover (Phase B)** is shadow-write first: writer CF populates the table for ~3 days before any consumer reads from it.
- **expected_outputs (Phase C)** ships read-only first; no consumer depends on it until Phase D wires the reconciler.
- **Monitoring CF retirement (Phase G)** waits until new metrics/alerts have run for 7 days clean.
- **Backfill (Phase F)** writes to staging tables first, swap-overs are explicit per-date and reversible.

---

## Files in this project directory

- `00-PROJECT-PLAN.md` — this file (phases, sequencing, risk)
- `01-ARCHITECTURE.md` — design sketch: PipelineState model, halt_state, observability
- `02-EXECUTION-LOG.md` — running log of code changes per phase, commit refs
- `03-BACKFILL-MANIFEST.md` — per-date / per-source backfill status (recovered / failed / lost)
- `04-DEMO-SCRIPT.md` — pre-presentation walkthrough + rollback cheatsheet
