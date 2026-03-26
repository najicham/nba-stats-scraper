# Multi-Sport Frontend — Project Overview

*Created: Session 488 (2026-03-25)*
*Status: Planning*
*Priority: High — MLB Opening Day is 2026-03-27*

## Goal

Show both NBA Player Points picks and MLB Pitcher Strikeouts picks on `playerprops.io`. Currently the frontend is 100% NBA-only. The backend MLB exporters are already written and tested — the work is wiring them up and adding a sport switcher to the frontend.

## Context from 5-Agent Review

Agents reviewed: best-bets data flow, API types, MLB GCS data, picks routing, and pick card components.

### What already works

- **MLB exporters are complete** — `mlb_best_bets_exporter.py`, `mlb_predictions_exporter.py`, `mlb_results_exporter.py`, `mlb_system_performance_exporter.py` all exist and are tested
- **GCS path defined** — `v1/mlb/best-bets/{date}.json` hardcoded in exporter code
- **Frontend pick components are sport-agnostic** — `RecordHero`, `WeeklyHistory`, `BetCard`, `TodayPicksTable` all render direction (OVER/UNDER), line, edge, result the same way regardless of sport
- **MLB field names map cleanly** — `pitcher_name` → `player`, `strikeouts_line` → `line`, `recommendation` → `direction`, stat = `"K"`

### What's missing

**Backend:**
- No Cloud Scheduler job to trigger MLB exports
- Phase 6 CF doesn't route to MLB exporters (no `sport: "mlb"` handling)
- No `v1/mlb/best-bets/all.json` (history + record windows) — current exporter only writes per-date files

**Frontend:**
- No `sport` field in any TypeScript type
- Stat labels hardcoded: `{ PTS: "pts", REB: "reb", AST: "ast", "3PM": "3pm" }` — need `K: "k"`
- No sport switcher in nav or on the Best Bets page
- API fetch always hits `best-bets/all.json` — needs sport param

## Chosen Approach

**Sport tabs on `/best-bets`** — NBA | MLB pill switcher at the top of the page.

Rationale:
- Least code change — same components, same layout, different data
- Can ship before/on Opening Day
- Clean upgrade path to separate routes later if needed

## File Map

### Docs in this directory

| File | Contents |
|------|----------|
| `00-OVERVIEW.md` | This file — context, approach, status |
| `01-BACKEND-PLAN.md` | Backend: Phase 6 routing, scheduler, all.json builder |
| `02-FRONTEND-PLAN.md` | Frontend: types, stat labels, sport switcher, API layer |
| `03-SCHEMA-MAPPING.md` | Field-by-field MLB→NBA pick schema mapping |

### Key code files

**Backend (nba-stats-scraper repo):**
| File | Role |
|------|------|
| `data_processors/publishing/mlb/mlb_best_bets_exporter.py` | Exports per-date MLB picks to GCS |
| `orchestration/cloud_functions/phase6_export/main.py` | Phase 6 CF — needs MLB routing |
| `config/phase6_publishing.yaml` | Publishing schedule config — needs MLB jobs |

**Frontend (props-web repo):**
| File | Role |
|------|------|
| `src/app/best-bets/page.tsx` | Main page — add sport tab state |
| `src/lib/best-bets-types.ts` | Add `sport?` field to `BestBetsPick` |
| `src/lib/best-bets-api.ts` | Add `sport` param to fetch function |
| `src/components/best-bets/TodayPicksTable.tsx` | `statLabel()` — add K |
| `src/components/best-bets/BetCard.tsx` | `statLabel()` — add K |
| `src/app/api/proxy/[...path]/route.ts` | Add `mlb/` cache config |

## Status

- [x] 5-agent review completed (Session 488)
- [x] Plan documented
- [ ] Backend: Phase 6 CF MLB routing
- [ ] Backend: MLB `all.json` builder (history + record windows)
- [ ] Backend: Cloud Scheduler job
- [ ] Frontend: Sport tabs + API param
- [ ] Frontend: Stat label extension
- [ ] Frontend: Player modal disabled for MLB
- [ ] Verification: Opening Day picks show on site
