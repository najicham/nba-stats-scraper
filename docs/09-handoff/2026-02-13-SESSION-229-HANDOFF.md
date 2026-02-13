# Session 229 Handoff — Trends Tonight Exporter + Picks Dedup Fix

## What Was Done

### 1. Created Consolidated Trends Tonight Exporter (NEW)

**File:** `data_processors/publishing/trends_tonight_exporter.py` (~500 lines)

Single endpoint `GET /v1/trends/tonight.json` that powers the redesigned frontend Trends page. Four sections:

- **players.hot/cold** (max 10 each) — Reuses `WhosHotColdExporter.generate_json()`, filters to `playing_tonight == True`, enriches with prop lines from UPCG
- **players.bounce_back** (max 5) — Reuses `BounceBackExporter.generate_json()`, same filter + enrichment
- **matchups** (1 per game) — NEW SQL joining `upcoming_team_game_context`, `team_defense_zone_analysis`, `player_game_summary` over-rates. Includes spread, total, defense, rest, injuries, pace, over-rate, auto-generated `key_insight`
- **insights** (max 12) — 10 generators, sorted by confidence (high → medium → low):
  1. B2B alert, 2. Rest advantage, 3. Pace clash, 4. Defense exploit, 5. Hot streakers, 6. Bounce-back alert, 7. Day-of-week, 8. Home/away OVER rate, 9. Model performance, 10. Scoring tier gap

**Registered in:** `backfill_jobs/publishing/daily_export.py` as `'trends-tonight'` (also in `trends-daily` and `trends-all` shorthand groups)

**Tests:** `tests/unit/publishing/test_trends_tonight_exporter.py` — 28 tests, all passing

**Endpoint is LIVE:** `https://storage.googleapis.com/nba-props-platform-api/v1/trends/tonight.json` (uploaded successfully, 6.5KB, 3 games tonight)

### 2. Fixed Picks Duplicate Bug

**Root cause:** `data_processors/publishing/subset_materializer.py` line ~247 — `_query_all_predictions()` used `UNION ALL` in the `team_info` CTE to combine `player_game_summary` and `upcoming_player_game_context`. Players appearing in BOTH tables (post-game: results in PGS + pre-game context in UPCG) got 2 rows, causing the subsequent JOIN to multiply every prediction × 2.

**Fix (2 changes):**
1. `subset_materializer.py`: Changed `UNION ALL` to a deduplicated CTE using `ROW_NUMBER()` with `source_priority` (PGS preferred over UPCG)
2. `all_subsets_picks_exporter.py`: Added defense-in-depth dedup in `_build_json_from_materialized()` keyed on `(system_id, subset_id, player_lookup)` — handles historical bad data already in `current_subset_picks`

**Backfilled:** Feb 7-11 picks re-exported to GCS. All verified clean (0 duplicates).

### 3. Frontend Integration Doc

**File:** `docs/08-projects/current/trends-tonight/FRONTEND-INTEGRATION.md`

Documents mismatches between backend output and current frontend types. Decision: **frontend updates types to match backend** (Option B). Key diffs:

| Area | Frontend expects | Backend sends |
|---|---|---|
| Bounce-back | `streak`/`baseline`/`signal_strength` | `shortfall`/`bounce_back_rate`/`significance` |
| Matchups | nested `matchup_insights` | flat `defense`/`rest`/`pace`/`injuries` |
| Insight type | `"stat"/"pattern"/"alert"/"trend"` | `"alert"/"info"/"positive"` |
| Matchup `game_time` | expected | not sent |

## Remaining Work

### Frontend Type Updates Needed
The frontend (`/home/naji/code/props-web`) needs to update its TypeScript types to match what the backend sends. The integration doc at `docs/08-projects/current/trends-tonight/FRONTEND-INTEGRATION.md` has exact type definitions. Key changes:
- New `TrendsTonightResponse` type replacing `TrendsPageDataV2`
- `TonightBounceBack` replacing `BounceBackCandidate` (shortfall model)
- `TonightMatchupCard` replacing `TonightMatchup` (flat structure)
- `TonightInsight` with backend's type enum (`"alert"/"info"/"positive"`)

### Optional: Add `game_time` to Matchups
The frontend expects `game_time` on matchup cards but the backend doesn't send it (not available from `upcoming_team_game_context`). Could add by joining schedule data via `NBAScheduleService`. Low priority since the frontend can derive it from the schedule it already fetches.

### Deploy
Changes are NOT committed yet. Files modified:
- `data_processors/publishing/trends_tonight_exporter.py` (NEW)
- `tests/unit/publishing/test_trends_tonight_exporter.py` (NEW)
- `backfill_jobs/publishing/daily_export.py` (import + registration)
- `data_processors/publishing/subset_materializer.py` (dedup fix)
- `data_processors/publishing/all_subsets_picks_exporter.py` (defense-in-depth dedup)
- `docs/08-projects/current/trends-tonight/FRONTEND-INTEGRATION.md` (NEW)

Commit and push to deploy via Cloud Build auto-triggers.

## Column Name Corrections Made During Implementation
- `prediction_accuracy.edge` → `predicted_margin` (actual column name)
- `prediction_accuracy.is_correct` → `prediction_correct` (actual column name)
- `player_game_summary.home_game` doesn't exist — derived from `game_id` split (`team_abbr = SPLIT(game_id, '_')[OFFSET(2)]`)

## Key Files
- Exporter: `data_processors/publishing/trends_tonight_exporter.py`
- Tests: `tests/unit/publishing/test_trends_tonight_exporter.py`
- Registration: `backfill_jobs/publishing/daily_export.py` (search for `trends-tonight`)
- Materializer fix: `data_processors/publishing/subset_materializer.py` (search for `Session 226`)
- Exporter dedup: `data_processors/publishing/all_subsets_picks_exporter.py` (search for `Session 226`)
- Frontend spec: `docs/08-projects/current/trends-tonight/FRONTEND-INTEGRATION.md`

## Run Commands
```bash
# Generate trends tonight
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2026-02-12 --only trends-tonight

# Re-export picks (with dedup)
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2026-02-11 --only subset-picks

# Run unit tests
PYTHONPATH=. python -m pytest tests/unit/publishing/test_trends_tonight_exporter.py -v --no-cov

# Verify endpoint
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/trends/tonight.json" | python3 -m json.tool | head -20
```
