# Session 490 Handoff — Multi-Sport Frontend + Schema Review

**Date:** 2026-03-26
**Status:** Implementation complete + schema review done. Ready for Opening Day (Mar 27).

---

## What Was Done This Session

### 1. Full multi-sport implementation shipped

**Backend** (`nba-stats-scraper`, commits `eb571e04` + `203b1185`):

- **`mlb_best_bets_exporter.py`** — Added `export_all()` + 4 helpers that generate
  `v1/mlb/best-bets/all.json` in the `BestBetsAllResponse` shape (today picks, record
  windows, streak, 8-week history). Mapped from `pitcher_strikeouts` BQ → frontend schema.
- **`phase6_export/main.py`** — `sport:"mlb"` Pub/Sub message routes to MLB exporter,
  bypasses NBA analytics/prediction validation checks entirely.
- **Cloud Scheduler** `mlb-daily-best-bets-publish` created in `us-central1`:
  `0 14 * 3-10 *` America/New_York (2 PM ET, March–October).

**Frontend** (`props-web`, commit `9cd4a94`):

- `Sport = "nba" | "mlb"` type + `sport?` field on `BestBetsPick`
- `fetchBestBetsAll(sport)` routes to `mlb/best-bets/all.json` for MLB
- `K → "k"` stat label in BetCard + TodayPicksTable (renders as `O 6.5 k`)
- `🏀 NBA | ⚾ MLB` pill tabs on `/best-bets` — switches sport, resets + refetches
- No-op `onPlayerClick` for MLB (no pitcher profiles)
- Proxy TTLs: `mlb/best-bets` → 5 min, `mlb/results` → 24h

### 2. Schema review — everything verified

Reviewed `mlb_predictions.pitcher_strikeouts` actual BQ schema. Key findings:

| Field | Status | Note |
|-------|--------|------|
| `pitcher_lookup` | ✅ EXISTS | player_lookup in frontend |
| `pitcher_name` | ✅ EXISTS | player in frontend |
| `team_abbr` | ✅ EXISTS | |
| `opponent_team_abbr` | ✅ EXISTS | |
| `is_home` | ✅ EXISTS | BOOLEAN |
| `strikeouts_line` | ✅ EXISTS | FLOAT |
| `recommendation` | ✅ EXISTS | 'OVER'/'UNDER'/'PASS'/'NO_LINE' |
| `edge` | ✅ EXISTS | predicted_strikeouts - strikeouts_line |
| `confidence` | ✅ EXISTS FLOAT, **0-100 scale** | base=75, typical=75-95 |
| `is_correct` | ✅ EXISTS | BOOLEAN, null until graded |
| `actual_strikeouts` | ✅ EXISTS | INTEGER, null until graded |
| `game_time` | ❌ NOT IN TABLE | Schema mapping doc was wrong. Fixed: set to None. |
| `system_id` | ✅ EXISTS | model identifier, not used in export yet |

**`MIN_CONFIDENCE = 70` is correct** — confidence is 0-100 (base 75 + data quality adjustments).
The `03-SCHEMA-MAPPING.md` that showed `0.72` was wrong.

**`game_time` bug fixed** — removed from SELECT, hardcoded `None` in frontend pick.
Frontend handles `game_time: null` gracefully (hides time display).

### 3. Infrastructure review

| Component | Status |
|-----------|--------|
| Phase 6 CF (`phase6-export`) | ✅ DEPLOYED (build `12a5547e`) |
| MLB prediction worker Cloud Run | ✅ RUNNING |
| MLB schedulers (30 total, us-west2) | ✅ ALL ENABLED |
| `mlb-predictions-generate` | `0 13 * * *` UTC = 9 AM ET |
| `mlb-daily-best-bets-publish` (new) | `0 14 * 3-10 *` ET = 2 PM ET |
| `mlb-opening-day-check` | Fires 2 PM UTC March 27 (10 AM ET) |

**Timing is correct:** predictions at 9 AM ET → best-bets export at 2 PM ET (5h gap).

**Note:** New `mlb-daily-best-bets-publish` is in `us-central1`, all other MLB schedulers
are in `us-west2`. No functional impact, just an inconsistency.

---

## State Right Now

- **MLB predictions in BQ:** NONE (expected — Opening Day is March 27)
- **`v1/mlb/best-bets/all.json` in GCS:** ✅ EXISTS — pre-season stub with `today:[]`, `season_start:"2026-03-27"`
- **Frontend `/best-bets`:** ✅ Shows segmented control `🏀 nba | ⚾ mlb`. MLB tab shows pre-season card.
- **Pre-season card:** ⚾ "MLB Season Begins / March 27, 2026 / Pitcher strikeout picks will appear here on Opening Day."

### Agent review results (both completed)

**Backend review found 1 bug (FIXED):**
- Phase 6 CF MLB block had no try/except — export failure left `result = None` → crash at `result.get('status')`.
  Fixed: wrapped in try/except, returns `status: "partial"` with error logged.

**Frontend review found 1 bug (FIXED):**
- `WeeklyHistory` MLB no-op `() => {}` was TS-invalid — signature requires `(string, string?) => void`.
  Fixed: changed to `(_l: string, _d?: string) => {}`.

**All else verified correct:**
- `_compute_record()` uses `is True`/`is False` — `None` properly excluded ✅
- Date string sorting/comparison — CAST in SQL, `str()` idempotent ✅
- `sportRef` pattern — standard latest-value ref, safe ✅
- `games_scheduled ?? 0` — handles missing MLB field ✅
- Proxy cache TTL order — `mlb/best-bets` fires before default ✅

---

## Opening Day Checklist (March 27, 2026)

### Morning
```bash
# 1. Verify predictions generated (should happen ~9 AM ET automatically)
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT COUNT(*) as picks, COUNTIF(recommendation='OVER') as overs,
        COUNTIF(recommendation='UNDER') as unders
 FROM mlb_predictions.pitcher_strikeouts
 WHERE game_date = '2026-03-27'"

# 2. Check data quality
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT recommendation, COUNT(*) as n, AVG(confidence) as avg_conf,
        AVG(ABS(edge)) as avg_edge
 FROM mlb_predictions.pitcher_strikeouts
 WHERE game_date = '2026-03-27' AND recommendation IN ('OVER','UNDER')
   AND confidence >= 70 AND ABS(edge) >= 1.0
 GROUP BY 1"
```

### Afternoon (2 PM ET — scheduler fires automatically)
```bash
# If scheduler doesn't fire, trigger manually:
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"sport":"mlb","export_types":["best-bets"],"target_date":"2026-03-27"}'

# Verify GCS output
gcloud storage cat gs://nba-props-platform-api/v1/mlb/best-bets/all.json \
  --project=nba-props-platform | python3 -m json.tool | head -60
```

### Frontend verification
```
[ ] /best-bets shows 🏀 NBA | ⚾ MLB tabs
[ ] MLB tab shows picks in "O 6.5 k" format
[ ] Clicking pitcher name does NOT open player modal
[ ] Record shows 0-0 (no graded picks yet on Opening Day)
[ ] 🏀 NBA tab still works exactly as before
```

---

## Additional Changes (Session 490 continued)

### Sport switcher moved to global header

**Commits:** `111c34f`, `3b5ab63`

- `SportContext` created at `src/contexts/SportContext.tsx` — global `sport: Sport` state
- `SportProvider` added to `src/app/providers.tsx` inside `NavigationProvider`
- `Header.tsx` now renders compact `NBA | MLB` toggle (right side, before Settings)
  - Only shown on `/`, `/best-bets`, `/trends`
  - `cursor-pointer` on buttons — fixes the hover cursor bug
  - Sticky header position means no layout flicker on switch
- `best-bets/page.tsx` uses `useSport()` — local sport state and in-page tabs removed
- `page.tsx` (Tonight): `sport === "mlb"` → "MLB Tonight — Coming Soon" placeholder
- `trends/page.tsx`: `sport === "mlb"` → "MLB Trends — Coming Soon" placeholder
- Pre-season stub `v1/mlb/best-bets/all.json` published with `season_start: "2026-03-27"`
- Best Bets MLB tab shows: ⚾ "MLB Season Begins / March 27, 2026"

### All bugs found and fixed

| Bug | File | Fix |
|-----|------|-----|
| CF MLB block crashes if export fails (`result=None`) | `phase6_export/main.py` | try/except, returns `status: partial` |
| WeeklyHistory no-op signature mismatch | `best-bets/page.tsx` | `(_l: string, _d?: string) => {}` |
| `game_time` not in `pitcher_strikeouts` table | `mlb_best_bets_exporter.py` | removed from query, set to `null` |
| Provider nesting indentation wrong | `providers.tsx` | fixed indentation |

### Known Issues / Future Work

- **`game_time` is `null` for all MLB picks** — no game_time in BQ table. Enhancement: join MLB schedule table. Not blocking.
- **MLB results export** — next-morning grading refresh needs `mlb-daily-results-publish` scheduler targeting `["results","best-bets"]` for yesterday
- **`SEASON_START = '2026-03-27'` hardcoded** — make dynamic from `min(game_date)` in future
- **MLB Tonight / Trends data** — backend work needed (pitcher matchup data, strikeout trends)
- **Additional MLB stats** — beyond strikeouts (H, IP, ERA)

---

## Quick Reference

```bash
# Check MLB predictions
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT CAST(game_date AS STRING), COUNT(*) FROM mlb_predictions.pitcher_strikeouts
 WHERE game_date >= '2026-03-27' GROUP BY 1 ORDER BY 1 DESC LIMIT 5"

# Trigger MLB export
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"sport":"mlb","export_types":["best-bets"],"target_date":"today"}'

# Verify all.json
gcloud storage cat gs://nba-props-platform-api/v1/mlb/best-bets/all.json \
  --project=nba-props-platform | python3 -m json.tool | head -40

# Full schema
bq show --schema --format=prettyjson nba-props-platform:mlb_predictions.pitcher_strikeouts
```
