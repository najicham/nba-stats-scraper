# Session 489 Handoff — Multi-Sport: Full Backend + Frontend Implementation

**Date:** 2026-03-26
**Context:** MLB Opening Day is TODAY. This session designs and implements multi-sport support end-to-end — backend publishing pipeline AND frontend display — so MLB Pitcher Strikeouts picks appear alongside NBA Player Points on `playerprops.io`.
**Repos involved:** `nba-stats-scraper` (backend) + `props-web` (frontend, at `/home/naji/code/props-web`)

**This session owns everything:** backend `all.json` builder, Phase 6 CF routing, Cloud Scheduler setup, and all frontend changes. The planning is done. The next session implements.

---

## Start Here

Read the planning docs first (they have all the detail you need):
```
docs/08-projects/current/multi-sport-frontend/00-OVERVIEW.md      — what + why
docs/08-projects/current/multi-sport-frontend/01-BACKEND-PLAN.md  — backend implementation detail
docs/08-projects/current/multi-sport-frontend/02-FRONTEND-PLAN.md — frontend implementation detail
docs/08-projects/current/multi-sport-frontend/03-SCHEMA-MAPPING.md — field mapping reference
```

Then come back here for the session checklist and verification steps.

---

## What Was Already Done (Session 488)

5 agents reviewed the full stack. Findings are documented in:
```
docs/08-projects/current/multi-sport-frontend/
├── 00-OVERVIEW.md      — context, approach, status checklist
├── 01-BACKEND-PLAN.md  — Phase 6 CF routing, all.json builder, scheduler commands
├── 02-FRONTEND-PLAN.md — every file to touch, exact code, ~1h of work
└── 03-SCHEMA-MAPPING.md — field-by-field MLB→NBA pick mapping
```

**TL;DR of findings:**
- **Backend:** All 4 MLB exporters exist and are tested. Nothing runs them. No `all.json` exists. Two gaps to close.
- **Frontend:** 100% NBA-only. The pick card components are already sport-agnostic. Needs: sport tabs, one stat label (`K`), sport-aware API fetch, player modal disabled for MLB.

---

## The Two Repos

```
/home/naji/code/nba-stats-scraper/   — backend (GCS publishing, Phase 6 CF)
/home/naji/code/props-web/           — frontend (Next.js, playerprops.io)
```

**Frontend key files:**
```
src/app/best-bets/page.tsx                        ← Main page to modify
src/lib/best-bets-types.ts                        ← Add Sport type + sport? field
src/lib/best-bets-api.ts                          ← Add sport param to fetch
src/components/best-bets/BetCard.tsx              ← Add K: "k" to statLabel()
src/components/best-bets/TodayPicksTable.tsx      ← Add K: "k" to statLabel()
src/app/api/proxy/[...path]/route.ts              ← Add mlb/ cache TTLs
```

**Backend key files:**
```
data_processors/publishing/mlb/mlb_best_bets_exporter.py  ← Extend with export_all()
orchestration/cloud_functions/phase6_export/main.py       ← Add sport: "mlb" routing
```

---

## What Needs to Happen This Session

### Priority 1 (Backend — unlock everything else)

**A. Extend `mlb_best_bets_exporter.py` to write `all.json`**

Current exporter only writes per-date files (`v1/mlb/best-bets/{date}.json`). The frontend needs `v1/mlb/best-bets/all.json` with this structure:
```json
{
  "date": "2026-03-27",
  "season": "2026",
  "generated_at": "...",
  "record": {
    "season": { "wins": 0, "losses": 0, "pct": 0.0 },
    "month":  { "wins": 0, "losses": 0, "pct": 0.0 },
    "week":   { "wins": 0, "losses": 0, "pct": 0.0 },
    "last_10": { "wins": 0, "losses": 0, "pct": 0.0 }
  },
  "streak": { "type": "win", "count": 0 },
  "best_streak": { "type": "win", "count": 0 },
  "today": [
    {
      "rank": 1,
      "player": "Gerrit Cole",
      "player_lookup": "gerritcole",
      "team": "NYY",
      "opponent": "BOS",
      "home": true,
      "direction": "OVER",
      "stat": "K",
      "line": 6.5,
      "edge": 2.0,
      "angles": [],
      "game_time": "2026-03-27T18:05:00Z",
      "actual": null,
      "result": null,
      "sport": "mlb"
    }
  ],
  "weeks": [],
  "total_picks": 0,
  "graded": 0
}
```

Key mapping from BQ → JSON:
- `pitcher_name` → `player`
- `pitcher_lookup` → `player_lookup`
- `strikeouts_line` → `line`
- `recommendation` → `direction`
- `"K"` is hardcoded as `stat`
- `is_correct: true` → `result: "WIN"`, `is_correct: false` → `result: "LOSS"`
- `actual_strikeouts` → `actual`

**B. Add `sport: "mlb"` routing to Phase 6 CF**

File: `orchestration/cloud_functions/phase6_export/main.py`

Add so this message works:
```bash
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"sport":"mlb","export_types":["best-bets"],"target_date":"2026-03-27"}'
```

**C. Verify `all.json` is live**
```bash
gcloud storage cat gs://nba-props-platform-api/v1/mlb/best-bets/all.json \
  --project=nba-props-platform | python3 -m json.tool | head -50
```

---

### Priority 2 (Frontend — ~1 hour once backend is live)

See `docs/08-projects/current/multi-sport-frontend/02-FRONTEND-PLAN.md` for exact diffs. Summary:

**1. `src/lib/best-bets-types.ts`** — Add `Sport` type:
```typescript
export type Sport = "nba" | "mlb";
// Add to BestBetsPick: sport?: Sport;
// Add to BestBetsAllResponse: sport?: Sport;
```

**2. `src/lib/best-bets-api.ts`** — Add `sport` param:
```typescript
export async function fetchBestBetsAll(sport: Sport = "nba") {
  const path = sport === "mlb" ? "mlb/best-bets/all.json" : "best-bets/all.json";
  return fetchBestBetsJson<BestBetsAllResponse>(path);
}
```

**3. `BetCard.tsx` + `TodayPicksTable.tsx`** — Add `K: "k"` to `statLabel()`:
```typescript
const labels = { PTS: "pts", REB: "reb", AST: "ast", "3PM": "3pm", K: "k" };
```

**4. `src/app/best-bets/page.tsx`** — Add sport tab state + re-fetch:
```typescript
const [sport, setSport] = useState<Sport>("nba");
// Add pill tabs: [🏀 NBA] [⚾ MLB]
// Re-fetch when sport changes
// Pass no-op to onPlayerClick when sport === "mlb" (no pitcher profiles)
```

**5. `src/app/api/proxy/[...path]/route.ts`** — Add `mlb/` cache TTLs:
```typescript
if (path.startsWith("mlb/best-bets")) return 5 * 60;
```

**6. Add "No picks" empty state** — `today[]` will be empty on off-days.

---

### Priority 3 (Scheduler — make it run daily)

Only needed if you want MLB picks to auto-publish from now on. Can do manually for Opening Day:
```bash
# Create daily Cloud Scheduler job (March–October only)
gcloud scheduler jobs create pubsub mlb-daily-best-bets-publish \
  --project=nba-props-platform \
  --location=us-central1 \
  --schedule="0 14 * 3-10 *" \
  --time-zone="America/New_York" \
  --topic=nba-phase6-export-trigger \
  --message-body='{"sport":"mlb","export_types":["best-bets"],"target_date":"today"}'
```

---

## Key Decisions Already Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| UX pattern | Sport tabs on `/best-bets` | Least code, ships fastest, same components |
| Stat label for strikeouts | `"K"` → renders as `"k"` | Standard baseball notation |
| MLB pick `stat` field | Always `"K"` (hardcoded in exporter) | Only strikeouts for now |
| Player modal for MLB | Disabled (no-op click) | No pitcher profiles in Tonight page |
| GCS path for MLB | `v1/mlb/best-bets/all.json` | Matches existing exporter pattern |
| MLB record season start | 2026-03-27 (Opening Day) | Computed by backend |

---

## What the Frontend Currently Looks Like

- `/best-bets` — shows NBA signal best bets, 3-column grid: player | "O 25.5 pts" | NYY vs BOS WIN
- Data source: `GET /api/proxy/best-bets/all.json` → GCS `v1/best-bets/all.json`
- Proxy is at `src/app/api/proxy/[...path]/route.ts`, passes through to GCS
- `RecordHero`, `WeeklyHistory` are already sport-agnostic — zero changes needed
- `BetCard` / `TodayPicksTable` have hardcoded stat labels — add `K: "k"` only

---

## Verification Checklist

After implementation:
```
[ ] v1/mlb/best-bets/all.json exists in GCS with today[] picks
[ ] Frontend /best-bets shows NBA | MLB tabs
[ ] MLB tab shows "O 6.5 k" format for strikeout picks
[ ] Clicking pitcher name does NOT open player modal
[ ] Record shows 0-0 (no graded picks yet on Opening Day)
[ ] Empty state shows for MLB on off-days
[ ] NBA tab still works exactly as before (no regression)
```

---

## Not In Scope for This Session

- MLB Tonight page (lineup view, pitcher matchups)
- MLB player profiles
- MLB live grading
- MLB admin picks page
- Sport switcher in the global header/nav
- Additional MLB stats beyond strikeouts (H, ERA, BB)
- `/best-bets/nba` and `/best-bets/mlb` separate routes (tabs are sufficient for now)

---

## Quick Reference

```bash
# Trigger MLB best-bets export manually
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"sport":"mlb","export_types":["best-bets"],"target_date":"2026-03-27"}'

# Verify GCS output
gcloud storage cat gs://nba-props-platform-api/v1/mlb/best-bets/all.json \
  --project=nba-props-platform | python3 -m json.tool | head -60

# Check MLB predictions exist in BQ
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT COUNT(*), recommendation FROM mlb_predictions.pitcher_strikeouts
 WHERE game_date = '2026-03-27' GROUP BY 2"

# Run frontend dev server
cd /home/naji/code/props-web && npm run dev
```
