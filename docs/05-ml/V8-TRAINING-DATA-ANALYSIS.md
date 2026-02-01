# V8 Training Data Analysis

**Date:** 2026-01-31 (Session 60)
**Purpose:** Document exactly what data V8 was trained on to inform future training decisions

---

## Executive Summary

**V8 was trained on BettingPros Consensus lines, NOT DraftKings lines.**

This is significant because:
- Users bet on DraftKings, but the model was calibrated to Consensus lines
- Consensus is an aggregate across multiple books - may not match DraftKings exactly
- Future models (V9+) should consider training on DraftKings-specific lines

---

## Evidence

### 1. Training Script Analysis

**File:** `ml/train_final_ensemble_v8.py`

Lines 59-65 show the Vegas lines query:
```python
vegas_lines AS (
  SELECT game_date, player_lookup, points_line as vegas_points_line,
         opening_line as vegas_opening_line, (points_line - opening_line) as vegas_line_move
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE bookmaker = 'BettingPros Consensus' AND bet_side = 'over'
    AND game_date BETWEEN '2021-11-01' AND '2024-06-01'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY processed_at DESC) = 1
),
```

**Key finding:** `WHERE bookmaker = 'BettingPros Consensus'` - explicitly filters to Consensus only.

### 2. Training Metadata

**File:** `models/ensemble_v8_20260108_211817_metadata.json`

```json
{
  "version": "v8",
  "timestamp": "20260108_211817",
  "training_samples": 76863,
  "best_model": "Stacked",
  "best_mae": 3.4045369834154213
}
```

**Note:** The metadata does NOT record which bookmaker was used - this is a gap we should fix for future models.

### 3. Git History

**Command:** `git log --oneline --follow ml/train_final_ensemble_v8.py`

```
42bad1c0 feat: Add feature statistics capture and model contract during training
7ab8739b feat(ml): Add training scripts for v6-v10 model experiments
```

Only 2 commits - the script was created and then feature stats were added. The bookmaker filter has **never been changed** from Consensus.

### 4. Data Availability During Training Period

**Query run:**
```sql
SELECT bookmaker, COUNT(*) as records
FROM nba_raw.bettingpros_player_points_props
WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01'
  AND market_type = 'points' AND bet_side = 'over'
GROUP BY 1
ORDER BY 2 DESC
```

**Results:**
| Bookmaker | Records |
|-----------|---------|
| BettingPros Consensus | 98,512 |
| BetMGM | 80,172 |
| PartyCasino | 79,890 |
| FanDuel | 75,778 |
| BetRivers | 60,254 |
| SugarHouse | 59,942 |
| Caesars | 53,894 |
| **DraftKings** | **52,098** |
| PointsBet | 23,042 |
| bet365 | 21,734 |

**DraftKings had 52,098 records available but was NOT used.** The training script explicitly chose Consensus instead.

---

## Implications for Future Training

### Why This Matters

1. **Line Calibration Mismatch**: Model learned to predict relative to Consensus lines, but users bet against DraftKings lines. If DK lines differ from Consensus, the model's edge calculations may be off.

2. **Hit Rate Analysis**: When we analyze hit rates, we should segment by bookmaker to see if performance varies.

3. **V9 Training Decision**: Should V9 train on:
   - DraftKings only (matches user betting experience)
   - Consensus (larger dataset, more stable)
   - Both (separate models or features)

### Data Available for V9 Training

From Session 59 analysis:

| Source | DraftKings Records | Date Range |
|--------|-------------------|------------|
| Odds API | 30,296 | May 2023 - Jun 2024 only |
| BettingPros | 104,196 | May 2022 - Jun 2024 |

**BettingPros DraftKings has 3x more data** because:
- Longer history (2022 vs 2023)
- More frequent snapshots (4/day vs 2/day)
- More player coverage (294 vs 252 unique players)

### Recommended V9 Approach

**Option A: Train on BettingPros DraftKings**
- Pros: Large dataset, DraftKings-specific calibration
- Cons: May miss some edge cases covered by Consensus

**Option B: Train on Consensus, grade on DraftKings**
- Pros: Maximum training data
- Cons: Calibration mismatch continues

**Option C: Multi-book training with book indicator**
- Pros: Model learns book-specific patterns
- Cons: More complex, may need more data

---

## How to Verify This Analysis

### Check Training Script
```bash
# View the bookmaker filter in training script
grep -A5 "vegas_lines AS" ml/train_final_ensemble_v8.py
```

### Check Available Bookmakers
```sql
-- What bookmakers are in BettingPros for any date range?
SELECT DISTINCT bookmaker
FROM nba_raw.bettingpros_player_points_props
WHERE market_type = 'points'
ORDER BY 1
```

### Compare Consensus vs DraftKings Lines
```sql
-- How often do Consensus and DraftKings lines match?
WITH lines AS (
  SELECT game_date, player_lookup,
    MAX(CASE WHEN bookmaker = 'BettingPros Consensus' THEN points_line END) as consensus,
    MAX(CASE WHEN bookmaker = 'DraftKings' THEN points_line END) as draftkings
  FROM nba_raw.bettingpros_player_points_props
  WHERE market_type = 'points' AND bet_side = 'over'
    AND game_date >= '2025-12-01'
  GROUP BY 1, 2
  HAVING consensus IS NOT NULL AND draftkings IS NOT NULL
)
SELECT
  COUNTIF(consensus = draftkings) as exact_match,
  COUNTIF(ABS(consensus - draftkings) <= 0.5) as within_half_point,
  COUNTIF(ABS(consensus - draftkings) > 1) as more_than_1pt_diff,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(consensus = draftkings) / COUNT(*), 1) as exact_match_pct
FROM lines
```

---

## Files Referenced

| File | Purpose |
|------|---------|
| `ml/train_final_ensemble_v8.py` | V8 training script - shows bookmaker filter |
| `models/ensemble_v8_20260108_211817_metadata.json` | Training metadata |
| `docs/08-projects/current/odds-data-cascade-investigation/README.md` | Full cascade investigation |
| `docs/05-development/model-comparison-v8-vs-monthly-retrain.md` | V8 vs retrain analysis |

---

## Action Items for V9

- [ ] Decide on bookmaker strategy (DraftKings-only vs Consensus vs multi-book)
- [ ] Add `training_bookmaker` field to model metadata
- [ ] Run Consensus vs DraftKings line comparison query
- [ ] Analyze hit rates by bookmaker (requires `line_bookmaker` in prediction_accuracy - added Session 60)
- [ ] Consider A/B test: V8 (Consensus-trained) vs V9 (DK-trained)

---

## Session 60 Changes

Added bookmaker tracking to enable per-bookmaker analysis:

1. **Schema changes:**
   - Added `line_bookmaker` to `prediction_accuracy` table
   - Added `line_source_api` to `prediction_accuracy` table

2. **Cascade changes:**
   - Implemented DraftKings-priority cascade in `betting_data.py`
   - Order: Odds API DK → BettingPros DK → Odds API FD → BettingPros FD → Consensus

This will allow us to analyze hit rates by bookmaker going forward.

---

*Document created: Session 60, 2026-01-31*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
