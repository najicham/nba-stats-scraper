# Session 525 Handoff — FanGraphs 2026 Data, NBA Off-Season Prep

**Date:** 2026-04-11
**Focus:** MLB FanGraphs FIP data gap fix, scheduler hardening, NBA off-season prep
**Commits:** `6829a9c8` — fix: FanGraphs 2026 data gap — v2 API + snapshot dedup + NBA market schedulers

---

## TL;DR

Five items from the Session 524 handoff addressed:
1. **P1 (Apr 12 validation)** — Pending. Apr 12 pipeline runs 6 AM ET Apr 12. Query below.
2. **P2 (FanGraphs FIP)** — FIXED. 2026 data loaded (447 pitchers). `elite_peripherals_over` and `xfip_elite_over` now have data.
3. **P3 (MLB UNDER)** — No action. Still 4-1 (N=5). Need N≥15 with new model.
4. **P4 (biweekly scheduler)** — FIXED. Reminder updated with `--training-start 2024-04-01`.
5. **P5 (NBA off-season)** — Assists/rebounds codified. weekly_retrain handles offseason automatically.

---

## What Was Done

### P2 — FanGraphs FIP Fix (Multi-Part)

**Root cause of dead `elite_peripherals_over` signal:**
- `fangraphs_pitcher_season_stats` had no 2026 rows — backfill script used pybaseball which hit FanGraphs 403
- Three JOIN sites (`pitcher_loader.py`, `train_regressor_v2.py`, `season_replay.py`) had no snapshot dedup → fanout risk when multiple snapshots exist for same pitcher+season

**Fix 1 — Backfill script rewritten** (`scripts/mlb/backfill_fangraphs_stats.py`):
- Replaced pybaseball (`pitching_stats()` → 403 blocked) with direct FanGraphs v2 JSON API
- URL: `https://www.fangraphs.com/api/leaders/major-league/data?...&type=8`
- **Critical**: FanGraphs WAF blocks full Chrome UA (`...KHTML, like Gecko... Chrome/120...`) and `Accept: application/json` header. Use truncated UA: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36`
- Updated column mapping (v2 API uses `PlayerName`, `TeamNameAbb`, `C+SwStr%` instead of pybaseball's `Name`, `Team`, `CSW%`)

**Fix 2 — Snapshot dedup** in all 3 JOIN sites:
```sql
-- Before (fanout if 2 snapshots exist for same pitcher+season):
LEFT JOIN `mlb_raw.fangraphs_pitcher_season_stats` fg
    ON ... AND fg.season_year = EXTRACT(YEAR FROM ...)

-- After (always latest snapshot):
LEFT JOIN (
    SELECT * FROM `mlb_raw.fangraphs_pitcher_season_stats`
    QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup, season_year ORDER BY snapshot_date DESC) = 1
) fg ON ... AND fg.season_year = EXTRACT(YEAR FROM ...)
```

**Fix 3 — 2026 data loaded:**
- `PYTHONPATH=. .venv/bin/python3 scripts/mlb/backfill_fangraphs_stats.py --season 2026 --qual 0`
- 447 pitchers loaded, snapshot_date = 2026-04-11
- 15+ starters qualify for `elite_peripherals_over` (FIP < 3.5, K/9 ≥ 9.0, GS ≥ 2)
- Notable: Gausman (FIP 1.24), Nick Pivetta (FIP 1.46), Dylan Cease (FIP 1.65), Matthew Boyd (FIP 1.86)

**Fix 4 — Monthly refresh scheduler added:**
- New reminder: `mlb-monthly-fangraphs-refresh` (1st of month, 10 AM ET, Apr-Oct)
- Message: `PYTHONPATH=. .venv/bin/python3 scripts/mlb/backfill_fangraphs_stats.py --season 2026 --qual 0`
- Next fire: May 1, 2026

### P4 — Biweekly Retrain Scheduler Updated

`mlb-biweekly-retrain` Cloud Scheduler message updated. Previous message said "120-day window" — updated to:
```
PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \
    --training-start 2024-04-01 --training-end YYYY-MM-DD --output-dir models/mlb/
```
Next fire: April 15, 9 AM ET.

### P5 — NBA Off-Season Prep

**Weekly retrain CF:** No changes needed. Governance gates handle offseason gracefully — no eval data → gates fail → no retrain. In October, `GOVERNANCE_SEASON_RESTART` loosened gates auto-detect via avg_edge check. Training anchors to Feb 28, 2026 (pre-late-season cap).

**Assists/rebounds schedulers codified** (`bin/schedulers/setup_nba_player_props_schedulers.sh`):
- 4 jobs: `nba-assists-props-morning`, `nba-assists-props-pregame`, `nba-rebounds-props-morning`, `nba-rebounds-props-pregame`
- All point to `nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape` with `market_type: assists/rebounds`
- Data accumulation (since Apr 6): 2.5K-102K rows/day per market

---

## System State

### MLB Pipeline
- **New model deployed** (Apr 11, session 524): `mlb-prediction-worker-00055-pv8`
- **FanGraphs 2026 data**: 447 pitchers as of Apr 11 snapshot
- **signals now active**: `elite_peripherals_over`, `xfip_elite_over` (FIP data available)
- **signals still dead**: `high_csw_over` (CSW% NULL until ~May), `high_k_vs_lineup_over` if lineup data missing
- **UNDER**: disabled (`MLB_UNDER_ENABLED=false`). 4-1 (80%) at N=5. Need N≥15 to decide.
- **MLB best bets**: 3-0 (100%) all-time (Springs Apr9, Ginn Apr10, Montero Apr10)

### NBA Pipeline
- **Last regular season games**: Apr 12, 2026
- **Playoffs**: Continue after Apr 12
- **Auto-halt active**: 415-235 (63.8%) season. Zero BB picks.
- **Assists/rebounds data**: Accumulating since Apr 6; dedicated models needed before predictions

---

## Continuation: What to Work on Next

### Priority 1: Validate Apr 12 MLB Predictions (new model)

```sql
-- Run this Saturday Apr 12 afternoon/evening:
SELECT recommendation,
  COUNT(*) as n,
  ROUND(AVG(predicted_strikeouts), 2) as avg_pred,
  ROUND(AVG(strikeouts_line), 2) as avg_line,
  ROUND(AVG(predicted_strikeouts - strikeouts_line), 2) as avg_bias
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date = '2026-04-12' AND strikeouts_line IS NOT NULL
GROUP BY 1
```
**Expected:** OVER avg_bias near 0 ± 0.3 K (was +1.15 K with old model). Row count ~20-30.

Also check which signals fired — `elite_peripherals_over` should now appear:
```sql
SELECT signal_tags, COUNT(*) as n, ROUND(AVG(edge), 2) as avg_edge
FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
WHERE game_date = '2026-04-12'
GROUP BY 1
```

### Priority 2: MLB UNDER Enable Decision

Track graded UNDER picks. Enable when N≥15 at HR≥65%:
```sql
SELECT recommendation, COUNT(*) as n,
  COUNTIF((recommendation='OVER' AND actual_strikeouts > strikeouts_line) OR
          (recommendation='UNDER' AND actual_strikeouts < strikeouts_line)) as hits,
  ROUND(100.0 * COUNTIF(...)/ COUNT(*), 1) as hr_pct
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= '2026-04-01' AND actual_strikeouts IS NOT NULL AND strikeouts_line IS NOT NULL
GROUP BY 1
```
Enable: `gcloud run services update mlb-prediction-worker --update-env-vars="MLB_UNDER_ENABLED=true"`

### Priority 3: Monthly FanGraphs Refresh (May 1)

First scheduled refresh fires May 1. Verify the scheduler fires:
```bash
PYTHONPATH=. .venv/bin/python3 scripts/mlb/backfill_fangraphs_stats.py --season 2026 --qual 0
```
Check that row counts increase (447 → ~700+ as more pitchers accumulate starts).

### Priority 4: NBA Playoffs / Off-Season

- **Apr 12**: Last regular season game
- **Playoffs start**: ~Apr 20 — NBA auto-halt remains active (avg edge too low for BB picks)
- **Off-season (Jul-Sep)**: Scrapers return empty, weekly_retrain fails governance gracefully
- **October**: Season restart, GOVERNANCE_SEASON_RESTART auto-detected, models retrain on Dec 2025-Feb 2026 data

No action required — system handles all phases automatically.

---

## Key Files Changed

| File | Change |
|------|--------|
| `scripts/mlb/backfill_fangraphs_stats.py` | Rewritten to use FanGraphs v2 API (was pybaseball) |
| `predictions/mlb/pitcher_loader.py` | FanGraphs JOIN deduped with QUALIFY |
| `scripts/mlb/training/train_regressor_v2.py` | FanGraphs JOIN deduped with QUALIFY |
| `scripts/mlb/training/season_replay.py` | FanGraphs JOIN deduped with QUALIFY |
| `bin/schedulers/setup_mlb_reminders.sh` | Biweekly retrain message fixed; monthly FanGraphs reminder added |
| `bin/schedulers/setup_nba_player_props_schedulers.sh` | NEW: Codifies assists/rebounds schedulers |

---

## Deployment Notes

- Commit `6829a9c8` pushed to main → auto-deploy triggered for `mlb-prediction-worker` (via `cloudbuild-mlb-worker.yaml`)
- GCP Cloud Scheduler updated: `mlb-biweekly-retrain` message updated, `mlb-monthly-fangraphs-refresh` created
- `fangraphs_pitcher_season_stats` table: 447 rows for 2026 (snapshot 2026-04-11). Data appended — existing 2025/2024 snapshots unchanged.

---

## Important Notes for Next Session

**FanGraphs API quirks:**
- Do NOT use `Accept: application/json` header → 403
- Do NOT use full Chrome UA string → 403
- Use truncated UA: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36`
- The `backfill_fangraphs_stats.py` script already has the correct headers

**MLB UNDER is NOT enabled:** Has 4-1 (80%) promise but N=5. Track until N≥15.

**Next biweekly retrain due:** April 15, 9 AM ET. Command:
```bash
PYTHONPATH=. .venv/bin/python3 scripts/mlb/training/train_regressor_v2.py \
    --training-start 2024-04-01 \
    --training-end 2026-04-13 \
    --output-dir models/mlb/
```
