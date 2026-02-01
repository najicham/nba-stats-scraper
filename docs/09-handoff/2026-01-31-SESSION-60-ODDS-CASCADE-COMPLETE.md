# Session 60 Complete Handoff - Odds Data Cascade & V9 Training Prep

**Date:** 2026-01-31
**Session:** 60 (Odds Cascade track)
**Status:** ✅ COMPLETE - Ready for V9 training

---

## Executive Summary

Investigated V8 training data, implemented DraftKings-priority cascade, and filled all historical game lines gaps for the 2025-26 season.

**Key Finding:** V8 was trained on BettingPros Consensus, not DraftKings. This is a calibration mismatch with user betting experience.

---

## What Was Accomplished

### 1. V8 Training Data Investigation ✅

**Finding:** V8 trained on `BettingPros Consensus` (76,863 samples, Nov 2021 - Jun 2024)

**Evidence:** `ml/train_final_ensemble_v8.py` line 63:
```sql
WHERE bookmaker = 'BettingPros Consensus'
```

**Documentation:** `docs/05-ml/V8-TRAINING-DATA-ANALYSIS.md`

---

### 2. DraftKings-Priority Cascade Implemented ✅

**New cascade order:**
1. Odds API DraftKings (primary)
2. BettingPros DraftKings (fills 15% gap)
3. Odds API FanDuel
4. BettingPros FanDuel
5. BettingPros Consensus (last resort)

**Files modified:**
- `data_processors/analytics/upcoming_player_game_context/betting_data.py`
- `data_processors/analytics/upcoming_player_game_context/async_upcoming_player_game_context_processor.py`
- `data_processors/analytics/upcoming_player_game_context/loaders/game_data_loaders.py`

---

### 3. Bookmaker Tracking Added ✅

Added to `prediction_accuracy` schema:
- `line_bookmaker` - e.g., 'DRAFTKINGS', 'FANDUEL'
- `line_source_api` - e.g., 'ODDS_API', 'BETTINGPROS'

Enables per-bookmaker hit rate analysis going forward.

---

### 4. Historical Game Lines Backfilled ✅

| Month | Before | After | Status |
|-------|--------|-------|--------|
| Oct 2025 | 1 game | 80 games | **100%** ✅ |
| Nov 2025 | 0 games | 219 games | **100%** ✅ |
| Dec 2025 | 197 games | 198 games | **100%** ✅ |
| Jan 2026 | 163 games | 163 games | 70% (future games) |

**Why Oct 22 was the starting date:** The original date list was generated from schedule queries that missed Oct 21 (season opener with only 2 games). Fixed in this session.

---

### 5. Skills Created/Updated ✅

- **`/validate-scraped-data`** - New skill for GCS vs BigQuery coverage audit
- **`/validate-daily`** - Added Priority 2E for scraped data coverage check

---

### 6. Game ID Format Investigation ✅

Discovered 5 different game_id formats across tables:

| Format | Example | Used By |
|--------|---------|---------|
| Standard | `20260130_MEM_NOP` | Most analytics/predictions |
| NBA Official | `0022500080` | Schedule tables |
| Odds API Hash | `dfa56bede06...` | odds_api_game_lines |
| Basketball Ref | `2026-01-27-BKN` | bref tables |

**Key insight:** `odds_api_game_lines` uses hash format that can't join by game_id. Joins must use `game_date + team_abbrs`.

---

## Data Gaps Remaining

### Feature Store (Oct 2025) 🔴

No feature store records exist for Oct 2025. Need to run feature generation backfill.

```bash
# TODO: Run feature generation for Oct 2025
```

### Phase 3 Context (Oct-Nov spreads) 🔴

Oct-Nov context records have `game_spread = NULL` because game lines weren't available when processed.

```bash
# TODO: Reprocess Phase 3 for Oct-Nov with new game lines
```

---

## Model Naming Convention Proposed

**Experiments:** `exp_YYYYMMDD_hypothesis` (e.g., `exp_20260201_dk_only`)
**Production:** `catboost_vN` (reserve for deployed models)

See: `docs/08-projects/current/ml-challenger-training-strategy/MODEL-NAMING-CONVENTIONS.md`

---

## Key Commits

| Commit | Description |
|--------|-------------|
| `741d8b09` | Implement DraftKings-priority betting cascade |
| `719e3b1b` | Add /validate-scraped-data skill |
| `d32dda7a` | Add scraped data coverage to /validate-daily |
| `68d1e707` | Model naming conventions, fix backfill script |
| `000f161e` | Add 2025-26 season data gaps analysis |

---

## Files to Know

| File | Purpose |
|------|---------|
| `docs/05-ml/V8-TRAINING-DATA-ANALYSIS.md` | V8 training data findings |
| `docs/08-projects/current/ml-challenger-training-strategy/` | V9 training project |
| `data_processors/analytics/upcoming_player_game_context/betting_data.py` | Cascade implementation |
| `scripts/backfill_odds_game_lines.py` | GCS → BQ processor |
| `backfill_jobs/scrapers/odds_api_lines/` | Historical scraper |

---

## Quick Commands

### Check game lines coverage
```bash
bq query --use_legacy_sql=false "
SELECT FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(DISTINCT CONCAT(game_date, '-', home_team, '-', away_team)) as games
FROM nba_raw.odds_api_game_lines
WHERE game_date >= '2025-10-01' AND market_key = 'spreads'
GROUP BY 1 ORDER BY 1"
```

### Check feature store coverage
```bash
bq query --use_legacy_sql=false "
SELECT FORMAT_DATE('%Y-%m', game_date) as month, COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-10-01'
GROUP BY 1 ORDER BY 1"
```

### Run historical scraper
```bash
echo "YYYY-MM-DD" > /tmp/dates.txt
PYTHONPATH=. python backfill_jobs/scrapers/odds_api_lines/odds_api_lines_scraper_backfill.py \
  --service-url="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app" \
  --dates-file="/tmp/dates.txt"
```

### Process GCS to BigQuery
```bash
python scripts/backfill_odds_game_lines.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

---

## Next Session Priorities

1. **Backfill Oct 2025 feature store** - No ML features exist for Oct
2. **Reprocess Oct-Nov Phase 3 context** - Add game spreads to context
3. **Deploy cascade changes** to Phase 3/4 processors
4. **Train first DraftKings-only experiment** - `exp_YYYYMMDD_dk_only`
5. **Run per-bookmaker hit rate analysis** - Use new `line_bookmaker` field

---

## V9 Training Data Strategy

**Recommended:** Train on Odds API DraftKings (~40K samples Oct-Jan 2025-26)

**Rationale:**
- Matches user betting experience (users bet on DraftKings)
- Full season coverage available
- Simpler than multi-book training

**Alternative:** BettingPros DraftKings has more data but only starts Dec 20, 2025.

---

*Created: 2026-01-31 19:55 UTC*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
