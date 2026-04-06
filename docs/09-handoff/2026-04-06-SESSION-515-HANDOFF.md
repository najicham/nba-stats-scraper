# Session 515 Handoff — Edge Auto-Halt, MLB Pipeline Fix, Assists/Rebounds, Signal Revert

**Date:** 2026-04-06
**Focus:** Edge-based auto-halt implementation, MLB pipeline resurrection (3 cascading failures), assists/rebounds data collection, sharp_consensus_under revert
**Commits:** `cdf6acc7` (MLB fixes + signal revert), `64409bbd` (auto-halt + events path fix)

---

## What Was Done This Session

### 1. Edge-Based Auto-Halt (NEW FEATURE)

**Trigger:** 7d avg edge < 5.0 AND edge-5+ pick rate < 50% AND >= 3 days sampled
**Effect:** Zero BB picks exported. Exporter returns early with `halt_active: true` + halt metrics.
**Currently:** ACTIVE (avg edge 1.45, 1.2% edge-5+)

**Implementation:**
- `ml/signals/regime_context.py` — queries `player_prop_predictions` for 7d rolling edge metrics, adds `bb_auto_halt_active` + `bb_auto_halt_reason` to regime context
- `data_processors/publishing/signal_best_bets_exporter.py` — checks halt flag after `run_all_model_pipelines()`, returns zero-pick JSON with halt metadata

**Walk-forward validation (Session 514):**
- Normal seasons (2021-2025): never fires (edge stays 4.0+ through April)
- 2025-26: fires late Feb → saves +8 units, 34.5% better P/L

### 2. MLB Pipeline — 3 Cascading Failures Fixed

**Root cause chain:** BP events crash → BP props can't find events → no lines → 100% BLOCKED

| # | Issue | Root Cause | Fix |
|---|-------|-----------|-----|
| 1 | BP Events scraper crashes | `BETTINGPROS_API_KEY` not mounted on `mlb-phase1-scrapers` | Added to `deploy_mlb_scrapers.sh` `--set-secrets` |
| 2 | 5 scheduler URLs stale | `756957797294.us-west2.run.app` instead of `f7p3g7f6ya-wl.a.run.app` | Updated via `gcloud scheduler jobs update` |
| 3 | Events processor rejects GCS data | GCS files contain raw list, processor expects dict with `events` key | Made processor accept both formats, derive `game_date` from `commence_time` |

**Additional findings:**
- BettingPros `/v3/events` endpoint **doesn't support MLB** — only NBA/NFL. Dead end, not fixable.
- Odds API is the correct source for MLB lines. Working end-to-end.
- `SKIP_DEDUPLICATION = True` was in code but deployed service was stale. Fresh deploy fixed Phase 2 dedup.
- `TODAY` literal in GCS path: set `opts["date"]` before `super().set_additional_opts()` + final guard.

**Result:** 9 pitchers with predictions (1 OVER, 8 SKIP) — up from 0 active.

### 3. Assists/Rebounds Line Scraping — Data Clock Started

**4 Cloud Scheduler jobs created:**
- `nba-assists-props-morning` (10 AM ET)
- `nba-rebounds-props-morning` (10:05 AM ET)
- `nba-assists-props-pregame` (4 PM ET)
- `nba-rebounds-props-pregame` (4:05 PM ET)

**Zero code changes** — BettingPros scraper already supports market IDs 151 (assists), 157 (rebounds). BQ table `bettingpros_player_points_props` already has `market_type` column.

**First batch results (Apr 6):**
- Assists: 4,014 records, 50 players
- Rebounds: 5,643 records, 62 players

### 4. sharp_consensus_under — REVERTED to SHADOW

**Problem:** Graduated signal (std >= 1.0 + line drop) contradicts `high_book_std_under_block` (blocks UNDER at std >= 0.75).

**Root cause:** Book count scaling. 5-season 69.3% HR was from 4-5 book markets (Odds API). With 12+ books in 2025-26, std >= 0.75 is noise (0-14 BB record).

**Action:** Moved from `UNDER_SIGNAL_WEIGHTS` back to `SHADOW_SIGNALS` in `aggregator.py`.

**To re-graduate:** Recalibrate threshold by book source (probably 1.5+ for BettingPros vs 1.0 for Odds API). Check `feature_50_source` column.

### 5. MLB Deploy + Service Fixes

- Deployed `mlb-phase1-scrapers` with `BETTINGPROS_API_KEY` secret
- MLB prediction worker auto-deploy verified working
- MLB events scraper: 13 events found for Apr 6
- MLB pitcher props: 2,273 rows scraped, 91 K-lines for 9 pitchers in BQ
- Algorithm version unchanged: `v514_rsc_revert_solo_under_rescue`

---

## Current System State

### NBA
- **Season: 108-76 (58.7%)** — pick drought Day 7+
- **Auto-halt ACTIVE:** avg edge 1.45, 1.2% edge-5+ (well below 5.0/50% threshold)
- **4 models enabled**, all producing avg edge 1.3-1.5
- **Monday retrain** at 5 AM ET will use Feb 28 training anchor

### MLB
- **9/303 predictions active** (1 OVER: Bubba Chandler, 8 SKIP)
- **Odds API pipeline working** end-to-end (events → props → Phase 2 → predictions)
- **BettingPros MLB events dead** — API doesn't support MLB, not fixable
- **Phase 3 analytics current** (20,660 pitcher game summaries through Apr 4)

### New Markets
- **Assists:** 4,014 records/day, 50 players — accumulating
- **Rebounds:** 5,643 records/day, 62 players — accumulating
- Dedicated models required for predictions (points model captures zero signal)

---

## Monday April 7 Risks

1. **`weekly-retrain` CF fires 5 AM ET** — has `cap_to_pre_late_season()` (Feb 28 anchor). Verify it produces models with higher edge.
2. **Auto-halt may persist** — if retrained models still have low edge, halt continues. This is correct behavior.
3. **MLB morning pipeline** — events scraper at 10:15 AM ET, pitcher props at 1 PM ET. Line coverage should improve as more books post.
4. **Assists/rebounds schedulers** — first automated run at 10 AM ET. Verify data lands correctly.

---

## Quick Start for Next Session

```bash
# 1. Check if Monday retrain produced good models
./bin/model-registry.sh list

# 2. Check if auto-halt is still active (should be until edge recovers)
bq --project_id=nba-props-platform query --nouse_legacy_sql "
WITH daily_edges AS (
  SELECT game_date,
    AVG(ABS(predicted_points - current_points_line)) as avg_edge,
    COUNTIF(ABS(predicted_points - current_points_line) >= 5.0) as edge_5plus,
    COUNT(*) as total
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND game_date < CURRENT_DATE()
  GROUP BY game_date
)
SELECT ROUND(AVG(avg_edge), 2) as avg_edge_7d,
  ROUND(100.0 * SUM(edge_5plus) / NULLIF(SUM(total), 0), 1) as pct_edge_5plus,
  CASE WHEN AVG(avg_edge) < 5.0 AND 100.0 * SUM(edge_5plus) / NULLIF(SUM(total), 0) < 50.0
       THEN 'HALT' ELSE 'NORMAL' END as status
FROM daily_edges"

# 3. Check MLB predictions for today
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT recommendation, COUNT(*) as cnt
FROM mlb_predictions.pitcher_strikeouts WHERE game_date = CURRENT_DATE()
GROUP BY 1 ORDER BY 1"

# 4. Verify assists/rebounds data accumulating
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT market_type, COUNT(*) as records, COUNT(DISTINCT player_lookup) as players
FROM nba_raw.bettingpros_player_points_props
WHERE game_date >= CURRENT_DATE() - 1 AND market_type IN ('assists', 'rebounds')
GROUP BY 1 ORDER BY 1"

# 5. Check deployment drift
./bin/check-deployment-drift.sh --verbose
```

---

## Key Files Changed

| Purpose | File |
|---------|------|
| Edge-based auto-halt (regime query) | `ml/signals/regime_context.py` |
| Auto-halt early return (exporter) | `data_processors/publishing/signal_best_bets_exporter.py` |
| sharp_consensus revert | `ml/signals/aggregator.py` |
| MLB events processor (list format) | `data_processors/raw/mlb/mlb_events_processor.py` |
| MLB events path extractor (TODAY/) | `data_processors/raw/path_extractors/mlb_extractors.py` |
| MLB events GCS path fix | `scrapers/mlb/oddsapi/mlb_events.py` |
| MLB deploy script (BP API key) | `bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh` |

---

## Infrastructure Changes (No Code)

| Change | Details |
|--------|---------|
| 5 MLB scheduler URLs fixed | `mlb-events-morning`, `mlb-lineups-pregame`, `mlb-box-scores-daily`, `mlb-schedule-yesterday`, `mlb-reddit-discussion` |
| 4 new scheduler jobs created | `nba-assists-props-morning/pregame`, `nba-rebounds-props-morning/pregame` |
| Scheduler times corrected | Assists/rebounds from 2PM/8PM to 10AM/4PM ET |
| `mlb-phase1-scrapers` deployed | With `BETTINGPROS_API_KEY` secret, null guards, latest code |
| Run history cleared | `MlbPitcherPropsProcessor` + `MlbEventsProcessor` for Apr 6 (one-time) |

---

## Next Session Priorities

| Priority | Task | Effort | Notes |
|----------|------|--------|-------|
| **P0** | Verify Monday retrain with Feb 28 anchor | 30 min | Should produce models with higher edge |
| **P0** | Verify auto-halt JSON in production Phase 6 | 15 min | Check `halt_active` field in exported JSON |
| **P1** | Cost fixes (logging exclusions, legacy cleanup) | 2 hours | ~$74/mo savings |
| **P1** | Edge compression governance gate | 1 hour | Reject models with avg edge < 3.0 |
| **P2** | Recalibrate sharp_consensus_under by book source | 2 hours | Needs separate thresholds for Odds API vs BettingPros |
| **P2** | Fix BettingPros MLB props to bypass events endpoint | 1 hour | Use `/v3/props` with `event_id=ALL` + FantasyPros headers |

---

## Strategic Notes

1. **Auto-halt is working as designed** — edge drought means the system correctly stops picking. Monday retrain is the recovery mechanism.
2. **Assists is the most promising expansion market** — 1.8x book disagreement vs points, highest autocorrelation. Data accumulating. Need dedicated Phase 3/4/5 pipeline.
3. **MLB pipeline is functional but fragile** — depends solely on Odds API (BettingPros dead). Coverage improves later in day as books post.
4. **Book count scaling is a systemic issue** — any signal calibrated on 4-5 book data needs recalibration for 12+ book era. Feature 50 (`multi_book_line_std`) source tracking exists via `feature_50_source`.
