# Session 303B Handoff: Multi-Book Line Research & BookDisagreementSignal

**Date:** 2026-02-19
**Focus:** Multi-book line research (Session 300 queries), line_std signal discovery, BookDisagreementSignal implementation, historical backfill completion.

## TL;DR

Ran the Session 300 research queries against 12-book odds data. Discovered that cross-book line standard deviation (line_std) is the strongest predictive signal in the system: **93% HR at edge 3+ when std > 1.5** (N=43). The signal is NOT driven by injury uncertainty (0/47 picks were on injury report), NOT driven by bovada's bias (removing bovada strengthens it to 94.9%), and works for both OVER (90.5%) and UNDER (92.0%). Implemented `BookDisagreementSignal` in WATCH status. Completed historical backfill for Jan 25-Feb 7 (now 11-12 books per day).

## Key Discovery: Line Std Signal

### Core Finding

| Line Std | Overall HR | Edge 3+ HR | Edge 3+ N |
|----------|-----------|------------|-----------|
| > 1.5 (high) | 85.9% | **93.0%** | 43 |
| 1.0-1.5 | — | 58.2% | 110 |
| 0.5-1.0 | 52.5% | 54.5% | 246 |
| < 0.5 (low) | 50.6% | 61.5% | 52 |

### Properties

- **Direction-agnostic:** OVER 90.5%, UNDER 92.0%
- **Edge-agnostic:** Even sub-edge-3 hits 75.9% (vs 50.7% baseline)
- **Not injury-driven:** 0 of 47 qualifying picks were Questionable/GTD/Doubtful/Probable
- **Not bovada-driven:** Excluding bovada strengthens to 94.9% HR
- **Broadly distributed:** 30+ different players, stars and role players
- **Rare:** Only 3.2% of player-games qualify (std > 1.5)
- **Time stability:** January: 87.5-100% across 3 weeks. February: N=5, inconclusive (entire model crashed)

### V12 Shadow Check

V12 shadow model had 0 high-std edge 3+ picks in graded data (only 39 normal-std picks total). Too few graded predictions to evaluate whether f50 contributes to V12 performance. Need more post-ASB graded data.

## Other Multi-Book Research Findings

### Bovada is NOT Sharp for Player Points

| Book | MAE | Bias |
|------|-----|------|
| Fliff | 4.88 | +0.02 (sharpest) |
| DraftKings | 4.89 | +0.14 |
| FanDuel | 4.89 | +0.13 |
| Bovada | 5.33 | **-2.65** (worst) |

Bovada systematically sets player point lines 2.65 points below actuals. For multi-book features, use Fliff/DK/FD as sharp reference, not bovada.

### Juice Alignment at Edge 3+

| Direction | Juice Signal | HR | N |
|-----------|-------------|-----|---|
| OVER | books favor OVER | **67.1%** | 158 |
| UNDER | books favor OVER (misaligned) | 53.8% | 186 |
| UNDER | books favor UNDER (aligned) | 66.7% | 12 |

When prediction direction aligns with juice asymmetry, HR is ~67%. When UNDER picks go against juice, HR drops to near-coinflip.

## Implementation: BookDisagreementSignal

### Files Changed

| File | Change |
|------|--------|
| `ml/signals/book_disagreement.py` | **NEW** — Signal fires when multi_book_line_std > 1.5, WATCH status |
| `ml/signals/registry.py` | Register BookDisagreementSignal (18th signal) |
| `ml/signals/pick_angle_builder.py` | Add angle template for book_disagreement |
| `ml/signals/supplemental_data.py` | Add book_stats CTE joining f50 from ml_feature_store_v2 |

### Signal Details

- **Tag:** `book_disagreement`
- **Status:** WATCH
- **Fires when:** `multi_book_line_std > 1.5` (from feature store f50)
- **Confidence:** 0.85 base, scaling to 0.95 at std 2.5+
- **Safety:** Requires book_count >= 5 when available; passes through when book_count unknown
- **Direction:** Both OVER and UNDER

### Supplemental Data Changes

Added CTE in `supplemental_data.py` that queries `feature_50_value` from `ml_feature_store_v2` and passes it as `supp['book_stats']['multi_book_line_std']`. No additional BQ cost (feature store already queried at prediction time).

## Pipeline Status (Feb 19)

| Component | Status |
|-----------|--------|
| Feb 19 predictions | 81/model, fresh retrained V9 deployed |
| Feb 19 games | Status=1 (Scheduled), games tonight |
| Feb 20 pipeline | Auto-runs ~6 AM ET tomorrow |
| Model decay table | Stale (last: Feb 12, shows BLOCKED for old model) |
| Historical backfill | **Complete**: Jan 25-Feb 7 now 11-12 books/day |

### Pre-ASB Champion Performance (for reference)

| Date | Graded | Overall HR | Edge 3+ HR | Edge 3+ N |
|------|--------|-----------|------------|-----------|
| Feb 12 | 16 | 62.5% | 75.0% | 4 |
| Feb 11 | 105 | 47.6% | 45.5% | 33 |
| Feb 10 | 13 | 38.5% | 20.0% | 5 |
| Feb 9 | 41 | 48.8% | 44.4% | 9 |

Model was in BLOCKED state (44.1% 7d HR) before retrain. Fresh V9 deployed Feb 18 — first test is tonight's games.

## Agent Recommendations (Captured for Next Session)

### Path A vs B for Line Std

**Consensus: Path A (signal/filter) only for now. Do NOT add as model feature (Path B).**

Reasons:
1. f50 already exists in V12 feature contract — V12 shadow models already consume it. Check V12 shadow HR on high-std picks once more data accumulates.
2. N=100 high-std events in 42-day training window is too few for CatBoost to learn reliable splits
3. V9 uses 33 features — adding f50 requires a version bump
4. Risk of overfitting to the specific 100 high-std player-games in the training window
5. The edge-first architecture means signals annotate/filter, never override — low risk

### Last Season's Odds Data

**Not worth pursuing.**
- Only DraftKings and FanDuel available for 2024-25 (2 books)
- STDDEV of 2 books is meaningless for the line_std signal
- 42-day rolling window never reaches last season
- f50 was NULL/default for all historical data pre-Session 287

### Multi-Snapshot Line Movement

**Defer. Do three low-effort steps first:**

1. **Load existing snap-0200 closing data from GCS to BQ** (zero API cost, data already captured). Session 298 documented this gap.
2. **Complete 12-book backfill** — Done this session.
3. **Research: does intraday movement predict accuracy at edge 3+?** Use `nba_raw.odds_api_line_movements` view. If signal exists, add morning scraper run at ~14:00 UTC.

Existing evidence (Session dedup fix handoff):
- 51-86% of lines move between snap-1800 and snap-0200
- Avg move: 1.5-2.4 pts, max: 12-13 pts
- But predictions run at 6 AM ET, before most movement — closing line data is backtesting value, not live prediction

## Next Session Research Agenda

### P1: Grade Feb 19 Games
Games finish ~11 PM ET. Check morning grading:
```sql
SELECT game_date, COUNT(*) as graded,
  ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / COUNT(*), 1) as hit_rate,
  COUNTIF(ABS(predicted_margin) >= 3) as edge3_n,
  ROUND(100.0 * COUNTIF(ABS(predicted_margin) >= 3 AND prediction_correct = TRUE) /
    NULLIF(COUNTIF(ABS(predicted_margin) >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-02-19' AND system_id = 'catboost_v9'
GROUP BY 1;
```

### P2: Verify Feb 20 Pipeline
```sql
SELECT system_id, COUNT(*) as total
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-20' AND system_id = 'catboost_v9'
GROUP BY 1;
-- Expected: >>6 predictions
```

### P3: Load snap-0200 Closing Line Data to BQ
Session 298 documented that snap-0200 data exists in GCS but isn't loaded to BQ. Find the GCS paths and load them. This enables line movement research.

### P4: Juice Alignment Signal Research
The juice asymmetry data (OVER + books_favor_over = 67.1% at edge 3+, N=158) is promising. Research deeper:
- Time stability (monthly/weekly breakdown)
- Player tier interaction
- Interaction with line_std signal (do they stack?)

### P5: Build `player_line_summary` Phase 4 Processor
Session 300 designed the table schema:
```sql
CREATE TABLE nba_predictions.player_line_summary (
  player_lookup STRING,
  game_date DATE,
  consensus_line FLOAT64,
  line_std FLOAT64,
  line_range FLOAT64,
  book_count INT64,
  sharp_book_avg FLOAT64,      -- fliff, DK, FanDuel
  soft_book_avg FLOAT64,       -- bovada, betonlineag
  sharp_soft_delta FLOAT64,
  avg_over_juice FLOAT64,
  avg_under_juice FLOAT64,
  juice_asymmetry FLOAT64,
  computed_at TIMESTAMP
);
```
Note: "sharp" and "soft" definitions are INVERTED from Session 300's original plan — Fliff/DK/FD are sharp, bovada is soft.

### P6: Monitor V12 Shadow on High-Std Picks
Once post-ASB grading accumulates (2-3 days), re-run:
```sql
WITH line_data AS (
  SELECT player_lookup, game_date,
    STDDEV(points_line) as line_std
  FROM nba_raw.odds_api_player_points_props
  WHERE points_line IS NOT NULL AND game_date >= '2026-02-19'
  GROUP BY 1, 2
  HAVING COUNT(DISTINCT bookmaker) >= 5
)
SELECT pa.system_id,
  CASE WHEN ld.line_std > 1.5 THEN 'high_std' ELSE 'normal_std' END as std_bucket,
  COUNT(*) as n,
  COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
  ROUND(100.0 * COUNTIF(pa.prediction_correct = TRUE) /
    NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hit_rate
FROM line_data ld
JOIN nba_predictions.prediction_accuracy pa
  ON ld.player_lookup = pa.player_lookup AND ld.game_date = pa.game_date
WHERE pa.system_id LIKE 'catboost_v12%'
  AND ABS(pa.predicted_margin) >= 3
GROUP BY 1, 2
ORDER BY 1, 2;
```

### P7: Retrain Shadow Models
Wait for 2-3 days of post-ASB graded data. All shadow models stale. Champion V9 was just retrained (Feb 18).

## Commits This Session

To be committed after review.

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/book_disagreement.py` | **NEW** — BookDisagreementSignal (WATCH) |
| `ml/signals/registry.py` | Register new signal (18 total) |
| `ml/signals/pick_angle_builder.py` | Add book_disagreement angle template |
| `ml/signals/supplemental_data.py` | Add book_stats CTE for f50 data |

## Key Learnings

1. **Cross-book line std is the strongest signal discovered.** 93% HR at edge 3+ when std > 1.5. This captures genuine market disagreement — not injury, not bovada bias, not data artifacts.

2. **Bovada is NOT sharp for NBA player points.** It has the worst MAE (5.33) and -2.65 systematic bias. The "sharp book" framing in Session 300 was inverted. Fliff (social sportsbook) is actually the sharpest by MAE.

3. **Juice alignment is directional.** When our UNDER prediction goes against juice (books favor OVER), HR drops to 53.8% at edge 3+. When aligned, HR is ~67%.

4. **Signal approach (Path A) is safer than model feature (Path B).** With N=43, adding to the signal system (WATCH, observe) is low risk. Adding as a model feature risks overfitting with only ~100 high-std training examples in the 42-day window.

5. **V12 shadow has too few graded predictions to test f50 contribution.** Need more post-ASB data.

6. **No injury confound whatsoever.** Zero of 47 high-std qualifying picks at edge 3+ involved players on the injury report. The book disagreement is about fundamental pricing, not injury information flow.

7. **Last season's odds data is not worth pursuing.** Only 2 books available, 42-day window never reaches it.

8. **Multi-snapshot line movement should be deferred.** Load existing snap-0200 from GCS first (zero cost), then research before committing to new scraper runs.
