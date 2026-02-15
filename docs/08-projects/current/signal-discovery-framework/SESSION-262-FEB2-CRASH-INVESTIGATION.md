# Session 262: February 2 Crash — Root Cause Investigation

**Date:** 2026-02-15
**Status:** Investigation complete. Root cause identified. Recommendations actionable.
**Scope:** Deep dive into why picks crashed the week of Feb 1-7, with multi-season historical analysis

---

## Executive Summary

On February 2, 2026, the champion model (catboost_v9) produced 33 edge 3+ picks with only 5 wins (15.2% HR). This was the single worst day in the model's history, and the surrounding week (Feb 1-7) was devastating across all models. We investigated five angles: pick-level forensics, data pipeline quality, cross-model comparison, signal effectiveness, and external NBA context.

### Root Cause: Model Decay + Record-Breaking Trade Deadline Chaos

The crash was caused by **two independent factors compounding**:

1. **Model decay** (primary): The champion was 25+ days stale and already declining (77.4% → 57.3% over 3 weeks). The 7-day rolling HR crossed the 58% watch threshold on Jan 28 — 5 days before the crash.

2. **Record-breaking trade deadline week** (amplifier): The NBA trade deadline was Feb 5, 2026. Feb 2 was the start of deadline week, with 28 trades involving 73 players (both records). This created unprecedented roster chaos.

**Critically, the trade deadline alone would not have caused the crash.** V8 historical data shows deadline weeks performed at 73-82% HR across 4 prior seasons. The deadline amplified existing model decay into a catastrophe.

---

## Finding 1: Catastrophic UNDER Bias

94% of edge 3+ picks on Feb 2 were UNDER (31 of 33), hitting at just 12.9%.

| Direction | Picks | Wins | HR | Avg Bias |
|-----------|------:|-----:|---:|------:|
| UNDER | 31 | 4 | 12.9% | -11.33 |
| OVER | 2 | 1 | 50.0% | +5.40 |

The model predicted players would score far below their lines, but they massively over-performed. Average prediction error: **-10.32 points**.

### Worst Individual Picks

| Player | Predicted | Line | Actual | Error | Context |
|--------|-------:|-----:|-------:|------:|---------|
| Jaren Jackson Jr | 13.8 | 22.5 | **30** | -16.2 | Traded to Jazz 3 days later — showcase game |
| Trey Murphy III | 11.1 | 22.5 | **27** | -15.9 | NOP missing DeJounte Murray |
| Jaden McDaniels | 13.3 | 16.5 | **29** | -15.7 | MIN game, ANT questionable |
| Tyrese Maxey | 16.1 | 25.5 | **29** | -12.9 | PHI @ LAC, Paul George suspended |
| Jabari Smith Jr | 9.4 | 17.5 | **19** | -9.6 | HOU missing KD/VanVleet/Adams |

JJJ alone had 5 UNDER picks in edge 3+ — all lost with -16.2 error. He was listed "questionable," being traded days later, yet scored 30 in a showcase performance.

---

## Finding 2: Every Model Crashed (Market-Wide Event)

| Model | Feb 2 Picks | Wins | HR | Avg Bias |
|-------|----:|----:|---:|------:|
| moving_average | 25 | 12 | 48.0% | -6.98 |
| ensemble_v1_1 | 11 | 5 | 45.5% | -5.47 |
| similarity_balanced_v1 | 7 | 3 | 42.9% | -6.29 |
| zone_matchup_v1 | 8 | 3 | 37.5% | -1.63 |
| catboost_v8 | 14 | 4 | 28.6% | -6.93 |
| catboost_v9 | 33 | 5 | 15.2% | -10.32 |

**Every model had negative bias.** V8 (4-year champion, 27K+ graded picks, 79.7% lifetime HR) also crashed to 28.6%. V9 was worst because its decay amplified the market disruption.

---

## Finding 3: Model-Dependent Signals Amplified the Damage

| Signal Status | Picks | Wins | HR |
|--------------|------:|-----:|---:|
| Has signals | 75 | 6 | **8.0%** |
| No signals | 24 | 9 | **37.5%** |

Signal-tagged picks performed **4.7x worse** than untagged picks.

| Signal | Picks | Wins | HR | Type |
|--------|------:|-----:|---:|------|
| high_edge | 75 | 6 | 8.0% | Model-dependent |
| edge_spread_optimal | 51 | 3 | 5.9% | Model-dependent |
| prop_value_gap_extreme | 5 | 0 | 0.0% | Model-dependent |
| **minutes_surge** | **3** | **3** | **100%** | **Behavioral** |
| **combo_he_ms** | **2** | **2** | **100%** | **Behavioral** |

**Key insight:** Model-dependent signals concentrate bets on the model's highest-confidence picks. When the model is wrong, they concentrate losses. Behavioral signals (`minutes_surge`) were the only winners — all OVER predictions.

---

## Finding 4: No Data Quality Issues

| Metric | Good Week (Jan 12-18) | Bad Week (Feb 1-7) |
|--------|----------------------|-------------------|
| Feature quality avg | 80-83 | 80-83 |
| Avg bias | +0.01 | -3.37 |
| Std error | 6.93 | 9.78 |
| MAE | 5.65 | 8.30 |

Feature quality was stable. Line coverage was normal (ACTUAL_PROP only, no ODDS_API/BETTINGPROS). The crash was purely a prediction accuracy issue, not a pipeline failure.

---

## Finding 5: Higher Edge Thresholds Did NOT Help

| Edge Bucket | Picks | Wins | HR | Avg Bias |
|------------|------:|-----:|---:|------:|
| Edge 5+ | 20 | 3 | 15.0% | -11.51 |
| Edge 3-5 | 13 | 2 | 15.4% | -8.48 |

Both equally bad. The model's highest-confidence predictions were its biggest misses.

---

## Finding 6: Trade Deadline Context

**NBA Trade Deadline: February 5, 2026 at 3 PM ET**

| Timeline | Event |
|----------|-------|
| Jan 31 | 3-team trade (SAC/CLE/CHI). 10 deals finalized by Sunday. |
| Feb 1 | ATL-POR trade. Deadline week officially begins. |
| **Feb 2** | **Our crash day. JJJ questionable (showcase game). Massive star absences.** |
| Feb 3 | Harden-Garland talks ramp up. |
| Feb 4 | Anthony Davis traded to Wizards. |
| Feb 5 | Deadline: **28 trades, 73 players moved — both records. 27/30 teams involved.** |

**Star absences on Feb 2:**
- HOU: Kevin Durant, Steven Adams, Fred VanVleet (Sengun put up 39 pts)
- IND: Tyrese Haliburton, Obi Toppin
- MEM: Ja Morant + 5 others (JJJ questionable but played 30 pts)
- MIN: Anthony Edwards (questionable), Julius Randle (questionable)
- PHI: Paul George (suspended)
- LAC: Bradley Beal, Derrick Jones

---

## Finding 7: V8 Multi-Season Historical Analysis

**This is the most important finding for future prevention.**

### Trade Deadline Week HR — V8 Across 5 Seasons

| Season | Deadline Week HR | Post-Deadline HR | All-Star Week HR | Late Feb HR |
|--------|----------------|-----------------|-----------------|-------------|
| 2021-22 | 78.2% | 82.8% | 81.1% | 79.7% |
| 2022-23 | 81.9% | 84.0% | 80.0% | 84.5% |
| 2023-24 | 73.3% | 73.1% | 86.7%* | 77.0% |
| 2024-25 | 80.3% | 80.4% | 62.9% | 82.8% |
| **2025-26** | **47.9%** | **40.0%** | — | — |

*2024 All-Star week had only 15 picks

**Conclusion: The trade deadline does NOT historically cause crashes.** V8 maintained 73-84% HR across deadline weeks in 4 prior seasons. **2026 is a dramatic outlier**, not a recurring pattern.

### V8 Monthly Performance (All Seasons)

| Month | Picks | HR | Avg Bias |
|-------|------:|---:|------:|
| November | 3,810 | 84.1% | +0.72 |
| December | 5,258 | 78.7% | +0.63 |
| January | 6,006 | 75.9% | +0.16 |
| **February** | **3,722** | **76.0%** | **+0.32** |
| March | 4,813 | 82.1% | +0.25 |
| April | 3,095 | 81.7% | +0.24 |
| May (playoffs) | 852 | 87.2% | -0.44 |
| June (finals) | 119 | 89.1% | +0.29 |

**February is the weakest month** (76.0%), tied with January (75.9%). But both are still well above breakeven. The seasonal pattern shows a dip in Dec-Feb (mid-season, more uncertainty) and peak performance in playoffs (May-June).

### V8 Worst Days (All Time, 10+ Picks)

Of V8's **20 worst single days ever**, 14 are from the 2025-26 season:
- 7 in Feb 2026 (including Feb 2 at #3)
- 7 in Jan 2026
- 2 in Nov/Dec 2025
- Only 1 from a prior season (2024-02-22 at 46.5%)

**This means the entire 2025-26 season has been anomalously bad for V8**, not just the trade deadline. The model was already decaying across the board.

---

## What We Could Have Spotted Earlier

### Warning Signs That Were Visible Before Feb 2

| Date | Signal | Value | Action We Should Have Taken |
|------|--------|-------|---------------------------|
| Jan 19 | First 7d rolling HR dip below 60% | ~56.5% | WATCH alert |
| Jan 27 | V8 worst day (25.0%, 32 picks) | Daily HR | Anomaly day flag |
| Jan 28 | 7d rolling HR crosses 58% threshold | 59.2% → declining | **WATCH should fire** |
| Jan 31 | 7d rolling below 55% for 2+ days | ~55% | **ALERT should fire** |
| Feb 1 | Multiple COLD signals in signal_health | 7-14 COLD | Signal health warning |
| Feb 2 | 94% UNDER directional concentration | Single direction | **Directional skew flag** |

### Detectable Indicators (4-5 Days of Lead Time)

1. **7-day rolling HR** crossing 58% on Jan 28 — the Session 261 WATCH threshold is correct
2. **Signal health COLD count** spiking to 7-14 from Jan 27 onward
3. **V8 simultaneous crash** on Jan 27 (25.0%) — if both V8 and V9 crash on the same day, it's a market event

### What We Could NOT Have Spotted

1. Trade deadline's specific impact (no historical precedent for 28-trade weeks)
2. JJJ showcase performance (trade rumors not in our data pipeline)
3. The specific UNDER directional bias (emerged on the crash day itself)

---

## Recommendations

### Immediate (Before Feb 19 Games Resume)

1. **Verify COLD model-dependent signal handling.** Current: 0.5x weight. Recommended: **0.0x weight** during COLD. Evidence: 5.9-8.0% HR vs 100% for behavioral signals on Feb 2.

2. **Add directional concentration check.** If >80% of edge 3+ picks are in the same direction on a given day, flag as high-risk. On Feb 2, 94% were UNDER.

### Phase 2 (Build Before Next Season)

3. **Calendar-aware risk flags:**
   - Trade deadline week (deadline day -5 to deadline day): Reduce pick volume
   - All-Star break week: Reduce pick volume
   - These are NOT auto-block (V8 historically handled them fine), but they should increase the sensitivity of decay detection thresholds

4. **Cross-model anomaly detection.** If 2+ models crash below 40% on the same day, flag as "market disruption" rather than "model decay." Different root cause → different response.

5. **Replay tool calibration.** Run V8 multi-season replay with the WATCH/ALERT/BLOCK thresholds to verify they would have provided adequate lead time without too many false positives. The data shows the thresholds (58%/55%/52.4%) would have worked for 2026 but may be too tight for normal seasonal fluctuations.

### Next Season (2026-27)

6. **Integrate injury severity into predictions.** When >3 star players are OUT across the game slate, increase uncertainty. The Feb 2 slate had KD, Haliburton, Ja Morant, Paul George, and potentially Edwards all missing.

7. **Trade rumor awareness.** Players listed as "questionable" during deadline week who are in active trade discussions should be excluded or flagged. JJJ alone accounted for 5 of the 33 edge 3+ picks.

8. **Monthly model health reporting.** February and January are the weakest months (76% HR for V8). These months should trigger more aggressive monitoring and earlier retrain windows.

---

## Key Queries for Future Investigation

```sql
-- Check if current day has directional concentration risk
SELECT
  recommendation,
  COUNT(*) as picks,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND ABS(predicted_points - current_points_line) >= 3.0
  AND is_active = TRUE
GROUP BY 1;
-- Alert if any direction > 80%

-- Cross-model crash detection
SELECT
  system_id,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE game_date = CURRENT_DATE() - 1
  AND prediction_correct IS NOT NULL
  AND ABS(predicted_points - line_value) >= 3.0
GROUP BY 1
HAVING COUNT(*) >= 5;
-- Alert if 2+ models below 40%
```

---

## Files Referenced

| File | Purpose |
|------|---------|
| `docs/09-handoff/session-prompts/SESSION-261-FEB2-INVESTIGATION.md` | Original investigation prompt |
| `docs/08-projects/current/signal-discovery-framework/SESSION-261-HISTORICAL-REPLAY-AND-DECISION-FRAMEWORK.md` | Replay analysis context |
| `ml/signals/aggregator.py` | Signal health weighting code |
| `ml/signals/signal_health.py` | Signal health computation |
