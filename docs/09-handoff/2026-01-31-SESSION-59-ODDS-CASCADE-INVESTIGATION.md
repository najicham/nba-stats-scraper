# Session 59 Handoff - Odds Data Cascade Investigation

**Date:** 2026-01-31
**Focus:** Vegas line data sources, cascade priority, ML training implications
**Status:** Investigation complete, fixes implemented, follow-up items identified

---

## Quick Start for Next Session

```bash
# Read the full project doc
cat docs/08-projects/current/odds-data-cascade-investigation/README.md

# Run the backfill script (after reviewing)
PYTHONPATH=. python scripts/backfill_feature_store_vegas.py --start 2025-11-01 --end 2025-12-31 --dry-run
```

---

## Key Discoveries

### 1. V8 Was Trained on BettingPros Consensus (NOT DraftKings)

```python
# From ml/train_final_ensemble_v8.py line 62-63
FROM `nba_raw.bettingpros_player_points_props`
WHERE bookmaker = 'BettingPros Consensus'  # <-- CONSENSUS, not DraftKings!
```

**Implication:** V8's predictions are calibrated to BettingPros Consensus lines, not DraftKings. If users bet on DraftKings, there may be a slight line mismatch.

### 2. BettingPros Scraper Was Never in Workflow

- Scraper code existed since Aug 2025
- But was **never added to `config/workflows.yaml`**
- Fixed in Session 157 (Dec 21, 2025)
- Data only exists from Dec 20, 2025 onwards

### 3. Feature Store Used Wrong Source

**Bug:** `feature_extractor._batch_extract_vegas_lines()` queried `bettingpros_player_points_props` directly, ignoring `odds_api` which had full coverage.

**Fix Applied:** Now reads from `upcoming_player_game_context` (Phase 3) which has proper cascade.

### 4. We DO Track Bookmaker in Phase 3

| Field | Values |
|-------|--------|
| `current_points_line_source` | "odds_api", "bettingpros", "draftkings", "fanduel" |
| `opening_points_line_source` | Same |
| `game_spread_source` | "draftkings", "fanduel" |

**But:** `prediction_accuracy` only has `line_source = 'ACTUAL_PROP'` - doesn't track specific bookmaker.

---

## Data Source Coverage Summary

### Odds API (Primary for Player Props)

| Bookmaker | Records (V8 Period) | Coverage |
|-----------|---------------------|----------|
| draftkings | 30,296 | 50% |
| fanduel | 30,514 | 50% |

### BettingPros (Fallback)

| Bookmaker | Records (V8 Period) | Coverage |
|-----------|---------------------|----------|
| BettingPros Consensus | 197,024 | 14% |
| FanDuel | 151,560 | 11% |
| DraftKings | 104,196 | 8% |
| BetMGM | 160,334 | 12% |
| ... many others | | |

---

## Current Cascade Logic

### Game Lines (Spreads/Totals)
```
1. Odds API DraftKings  ✅ Implemented
2. Odds API FanDuel     ✅ Implemented
(No BettingPros fallback for game lines)
```

### Player Props
```
1. Odds API (no DK>FD preference)  ⚠️ Takes latest by timestamp
2. BettingPros (no DK>FD preference)  ⚠️ Takes "best_line" flag
```

---

## Fixes Applied This Session

### 1. Feature Store Cascade Fix ✅

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

Changed `_batch_extract_vegas_lines()` to read from `upcoming_player_game_context` instead of `bettingpros_player_points_props` directly.

### 2. Backfill Script Created ✅

**File:** `scripts/backfill_feature_store_vegas.py`

Can fix ~3,500 records from Nov-Dec 2025 with missing Vegas data.

### 3. Documentation Created ✅

**File:** `docs/08-projects/current/odds-data-cascade-investigation/README.md`

Comprehensive cascade documentation.

---

## Follow-Up Items for Future Sessions

### P0 - Should Address Soon

1. **Add bookmaker to prediction_accuracy table**
   - Currently only tracks "ACTUAL_PROP" vs "NO_PROP_LINE"
   - Should track: "draftkings", "fanduel", "consensus", etc.
   - Enables filtering hit rates by bookmaker

2. **Run the backfill script**
   ```bash
   PYTHONPATH=. python scripts/backfill_feature_store_vegas.py --start 2025-11-01 --end 2025-12-31
   ```

### P1 - Consider for ML Improvements

3. **Add DraftKings preference to player props cascade**
   - Currently no DK > FD priority in `betting_data.py`
   - Game lines have this, player props don't

4. **Consider training V9 on DraftKings lines only**
   - V8 trained on BettingPros Consensus
   - If users bet on DraftKings, model should be calibrated to DK lines
   - Would require ~30K DraftKings records from Odds API (limited)
   - OR use BettingPros DraftKings data (~104K records)

5. **Add bookmaker grouping to hit-rate-analysis skill**
   - Allow `/hit-rate-analysis --bookmaker draftkings`
   - Show hit rate breakdown by bookmaker

### P2 - Nice to Have

6. **Track line staleness in predictions**
   - We have `snapshot_timestamp` and `minutes_before_tipoff` in odds_api
   - Could track how fresh the line was at prediction time

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                     BETTING DATA FLOW                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  SCRAPERS (Phase 1)                                                 │
│  ┌─────────────────────┐     ┌─────────────────────┐               │
│  │ Odds API            │     │ BettingPros         │               │
│  │ • DraftKings        │     │ • DraftKings        │               │
│  │ • FanDuel           │     │ • FanDuel           │               │
│  │                     │     │ • Consensus         │               │
│  │                     │     │ • 15+ other books   │               │
│  └─────────┬───────────┘     └─────────┬───────────┘               │
│            │                           │                            │
│            ▼                           ▼                            │
│  RAW TABLES (Phase 2)                                               │
│  ┌─────────────────────┐     ┌─────────────────────┐               │
│  │odds_api_player_     │     │bettingpros_player_  │               │
│  │points_props         │     │points_props         │               │
│  │• snapshot_timestamp │     │• bookmaker          │               │
│  │• minutes_before_tip │     │• is_best_line       │               │
│  │• bookmaker (dk/fd)  │     │• opening_line       │               │
│  └─────────┬───────────┘     └─────────┬───────────┘               │
│            │                           │                            │
│            └───────────┬───────────────┘                            │
│                        ▼                                            │
│  ANALYTICS (Phase 3)                                                │
│  ┌─────────────────────────────────────────────────┐               │
│  │ upcoming_player_game_context                    │               │
│  │ • current_points_line                           │               │
│  │ • current_points_line_source (tracks bookmaker) │               │
│  │ • Cascade: Odds API first, BettingPros fallback │               │
│  └─────────────────────┬───────────────────────────┘               │
│                        │                                            │
│                        ▼                                            │
│  FEATURE STORE (Phase 4)                                            │
│  ┌─────────────────────────────────────────────────┐               │
│  │ ml_feature_store_v2                             │               │
│  │ • vegas_points_line (feature[25])               │               │
│  │ • NOW reads from Phase 3 ✅ (was bettingpros)   │               │
│  └─────────────────────┬───────────────────────────┘               │
│                        │                                            │
│                        ▼                                            │
│  PREDICTIONS (Phase 5)                                              │
│  ┌─────────────────────────────────────────────────┐               │
│  │ prediction_accuracy                             │               │
│  │ • line_value                                    │               │
│  │ • line_source = 'ACTUAL_PROP' (not bookmaker!) │               │
│  │ • ⚠️ MISSING: specific bookmaker tracking      │               │
│  └─────────────────────────────────────────────────┘               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Key Questions Answered

### Q: Did V8 train only on Odds API DraftKings?
**A: No.** V8 trained on `BettingPros Consensus` exclusively (line 63 of train_final_ensemble_v8.py).

### Q: How long has feature store used BettingPros?
**A: Since the beginning.** v2_33features (Nov 2021) always queried BettingPros.

### Q: Can we group hit rates by bookmaker?
**A: Not currently.** `prediction_accuracy.line_source` only has "ACTUAL_PROP", not the specific bookmaker. Would need schema change.

### Q: Do we track snapshot time and minutes to game?
**A: Yes, in raw tables.** `odds_api_player_points_props` has `snapshot_timestamp` and `minutes_before_tipoff`. But this isn't propagated to predictions.

---

## Files Changed This Session

| File | Change |
|------|--------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Read from Phase 3 instead of bettingpros |
| `scripts/backfill_feature_store_vegas.py` | New backfill script |
| `docs/08-projects/current/odds-data-cascade-investigation/README.md` | Project documentation |
| `docs/05-development/model-comparison-v8-vs-monthly-retrain.md` | V8 vs retrain analysis |
| `ml/experiments/quick_retrain.py` | Fixed recommendation logic, datetime warning |

---

## Commits This Session

```
f9bdf678 docs: Add V8 vs monthly retrain deep dive analysis
f744a932 docs: Add odds data cascade investigation project doc
bde97bd7 feat: Fix feature store to use Phase 3 cascade for Vegas lines
```

---

## Recommendations

### For Immediate Betting
- **Use DraftKings lines for betting** - They're the sharpest
- **Be aware V8 was trained on Consensus** - Slight calibration difference possible

### For Model Development
- Consider training V9 on DraftKings-only lines
- Or train separate models for each major book
- Add bookmaker to grading to measure per-book accuracy

### For System Improvement
- Add bookmaker field to `prediction_accuracy` schema
- Implement DK > FD priority in player props cascade
- Backfill Oct-Nov 2025 feature store data

---

*Session 59 Complete*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
