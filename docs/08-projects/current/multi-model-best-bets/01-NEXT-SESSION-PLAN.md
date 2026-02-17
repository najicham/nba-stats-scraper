# Next Session Plan: Pick Angles, Confidence Fix, Smart Filters

**Session:** 278 (continuation of 277)
**Priority:** HIGH — implement before Feb 19th game day if possible
**Estimated scope:** 1 session

---

## Context from Session 277

### What Was Shipped
- 3-layer multi-model architecture (V12 signals unlocked, cross-model subsets, consensus scoring)
- All deployed to production, BQ schema updated, Cloud Build succeeded

### Critical Findings from Deep Analysis

**1. The 0.92 Confidence Bug (Structural)**
The confidence formula `75 + quality_bucket + std_bucket` in `catboost_v8.py` (inherited by ALL models) produces 9 discrete values. The 0.92 tier maps to "consistent bench players with high data quality" — the hardest cohort to predict. Result: 0.92 = 47.5% HR (316 picks), worse than 0.90 (52.7%) and 0.89 (54.8%). For quantile models, the inversion is total: 0.95 = 39-42% HR.

**2. Bench UNDER Is Catastrophic**
V9 UNDER on bench players (line < 12): 35.1% HR (37 picks). The model under-predicts by 6 points on average while players actually score above the line. This is the single worst segment.

**3. High Relative Edge Is Noise**
Picks where |edge/line| >= 30% hit at only 49.7% — dominated by bench players with inflated edges on small lines. The sweet spot is 10-15% relative edge (61.1% HR).

**4. Feature Quality < 85 Is Poison**
Picks with quality < 85 hit at 24.0% (50 picks). Removing them alone lifts HR from 52.2% to 56.2%.

**5. V9's Strengths Are Specific**
- V9 OVER at edge 7+: 72.7% HR
- V9 UNDER on Stars (25+ line): 65.9% HR
- V9 OVER on Bench/Home: 58.0% HR
- B2B picks: ~79% HR (both directions)

**6. V12 Is a Better UNDER Filter**
- V12 UNDER overall: 56.8% HR
- When V12 disagrees with V9 (V12=OVER, V9=UNDER): V12 right 65.6%, V9 only 34.4%

---

## Part 1: Smart Filters (Immediate Profit Impact)

### Filter A: Block Quality < 85 Picks from Best Bets
**Impact:** +4.0% HR (52.2% → 56.2%), removes 50 poison picks
**File:** `ml/signals/aggregator.py` — add quality gate before scoring
**Logic:** If `pred.get('feature_quality_score', 100) < 85`, skip pick
**Note:** Zero-tolerance already blocks `default_feature_count > 0`. This adds a quality floor.

### Filter B: Block Bench UNDER from Best Bets
**Impact:** +1.7% HR, removes 37 losing picks
**File:** `ml/signals/aggregator.py` — add direction+tier filter
**Logic:** If `pred.get('line_value', 0) < 12 and pred.get('recommendation') == 'UNDER'`, skip
**Alternative:** Create a new signal `bench_under_block` that explicitly blocks these

### Filter C: Block High Relative Edge
**Impact:** +1.9% HR, removes 175 losing picks
**File:** `ml/signals/aggregator.py` — add relative edge cap
**Logic:** If `abs(edge) / max(line_value, 1) >= 0.30`, skip pick
**Note:** This mainly blocks bench players with inflated edges on small lines

### Combined Impact
All 3 filters: **195 picks at 56.4% HR** (from 395 at 52.2%)
Cuts volume 50% but crosses the 55% profitability threshold.

---

## Part 2: Pick Angles System (New Feature)

### Concept
Each pick gets a `pick_angles` array of human-readable reasons explaining WHY it was selected. Angles combine model output, signal tags, historical context, and cross-model consensus into clear one-liners.

### Example Output
```json
{
  "player": "LeBron James",
  "direction": "UNDER",
  "edge": 4.2,
  "pick_angles": [
    "V9 confidence 0.89 (56.5% season HR at this tier)",
    "Star UNDER: 65.9% HR historically for high-line players",
    "3 of 6 models agree UNDER with avg edge 3.8",
    "bench_under signal: non-starter pattern (76.6% HR)"
  ],
  "confidence_context": {
    "tier": "0.89",
    "tier_hr": 56.5,
    "tier_sample": 92,
    "player_tier": "Stars (25+)",
    "direction_tier_hr": 65.9
  }
}
```

### Architecture

**New file: `ml/signals/pick_angle_builder.py` (~200 lines)**

Takes a prediction dict + supplemental data + signal results + cross-model factors and produces a list of angle strings:

```python
class PickAngleBuilder:
    def build_angles(self, pred, signals, xm_factors, historical_rates) -> List[str]:
        angles = []

        # 1. Model confidence angle
        conf = pred.get('confidence_score')
        conf_hr = CONFIDENCE_HR_MAP.get(round(conf, 2))
        if conf_hr:
            angles.append(f"Model confidence {conf:.0%} ({conf_hr}% season HR)")

        # 2. Direction + tier angle
        tier = get_player_tier(pred.get('line_value'))
        dir_tier_hr = DIRECTION_TIER_HR.get((pred['recommendation'], tier))
        if dir_tier_hr:
            angles.append(f"{tier} {pred['recommendation']}: {dir_tier_hr}% HR historically")

        # 3. Cross-model consensus angle
        if xm_factors:
            n = xm_factors.get('model_agreement_count', 0)
            if n >= 3:
                angles.append(f"{n} of 6 models agree {xm_factors['majority_direction']} "
                             f"with avg edge {xm_factors['avg_edge_agreeing']}")

        # 4. Signal-specific angles
        for signal in signals:
            if signal.qualifies:
                angle = SIGNAL_ANGLE_MAP.get(signal.source_tag)
                if angle:
                    angles.append(angle.format(**signal.metadata))

        return angles[:4]  # Max 4 angles per pick
```

**Historical rate maps (loaded from BQ or hardcoded initially):**
```python
CONFIDENCE_HR_MAP = {
    0.95: 55.4, 0.92: 47.5, 0.90: 52.7, 0.89: 54.8, 0.87: 50.9
}

DIRECTION_TIER_HR = {
    ('UNDER', 'Stars'): 65.9,
    ('OVER', 'Bench'): 58.0,
    ('OVER', 'Stars'): 54.5,
    ('UNDER', 'Bench'): 35.1,  # Will show as warning
    # ...
}

SIGNAL_ANGLE_MAP = {
    'bench_under': "Bench UNDER signal: {under_rate:.0%} historical rate",
    'high_edge': "Strong model edge ({edge:.1f} points)",
    'dual_agree': "V9 + V12 both agree {direction} (edge {v9_edge:.1f} / {v12_edge:.1f})",
    'b2b_fatigue_under': "Back-to-back fatigue (79% HR historically)",
    'rest_advantage_2d': "Rest advantage: {rest_gap} extra rest days",
    # ...
}
```

### Integration Points

1. **`signal_best_bets_exporter.py`** — Call `PickAngleBuilder.build_angles()` for each top pick, include in JSON output
2. **`signal_annotator.py`** — Same for bridged picks in `current_subset_picks`
3. **`cross_model_subset_materializer.py`** — Generate angles for cross-model picks (e.g., "5 of 6 models agree")
4. **BQ schema** — Add `pick_angles ARRAY<STRING>` to `signal_best_bets_picks` and optionally `current_subset_picks`
5. **GCS JSON** — `signal-best-bets/{date}.json` picks gain `pick_angles` array

### Warning Angles (Negative)
When a pick has known anti-patterns, include warning angles:
```json
"warning_angles": [
  "Bench UNDER: historically 35.1% HR — low conviction",
  "Confidence 0.92 tier: 47.5% HR — below breakeven"
]
```

---

## Part 3: Confidence Score Overhaul (Medium-term)

### Problem
`_calculate_confidence()` in `catboost_v8.py` uses `75 + quality_bucket + std_bucket` — a heuristic with NO relationship to actual prediction accuracy. The result is inverted for quantile models.

### Solution: Calibrated Confidence

Replace the heuristic with a lookup table based on actual historical performance:

```python
def _calculate_confidence_v2(self, features, prediction, line_value):
    """Calibrated confidence based on actual hit rates by cohort."""
    direction = 'OVER' if prediction > line_value else 'UNDER'
    tier = get_player_tier(line_value)
    edge = abs(prediction - line_value)

    # Lookup key: (direction, tier, edge_bucket)
    edge_bucket = 'high' if edge >= 5 else 'medium' if edge >= 3 else 'low'
    key = (direction, tier, edge_bucket)

    # Pre-computed from historical data
    calibrated = CALIBRATED_CONFIDENCE.get(key, 0.50)
    return calibrated
```

### Implementation Steps
1. Query historical hit rates by (direction, player_tier, edge_bucket) for each model
2. Build lookup tables
3. Replace `_calculate_confidence` in V8/V9/V12 base class
4. A/B test: run old + new confidence in shadow mode for 7 days
5. Promote if new confidence is monotonic (higher confidence = higher HR)

### Scope: Separate session (needs careful testing)

---

## Part 4: Model-Specific Routing (Future)

Based on the profile analysis:

| Scenario | Best Model | Expected HR |
|----------|-----------|-------------|
| OVER, Star, Home | V9 | ~65%+ |
| OVER, Bench, Home | V9 | ~58% |
| OVER, Edge 7+ | V9 | ~73% |
| UNDER, Star (25+) | V9 | ~66% |
| UNDER, Role Player | V12 or Q45 | ~71-80% |
| UNDER, general | V12 | ~57% |
| V9=UNDER, V12=OVER | V12 | ~66% |
| UNDER, Bench (<12) | **BLOCK** | 35% |
| UNDER, Edge 7+ | **BLOCK** | 39% |

This would be implemented as a routing layer in the aggregator that selects which model's prediction to use based on the pick characteristics. Not for Session 278 — needs 14+ days of retrained model data.

---

## Part 5: Additional Investigations

### 5a. Team-Level Blocklist
V9 loses money on MEM (22.2%), MIA (28.6%), PHX (33.3%), LAC (33.3%), HOU (35.3%). Consider a dynamic team blocklist that auto-updates from rolling 14d performance per team.

### 5b. 2+ Days Rest UNDER
Worst segment: 32.9% HR (82 picks). Model predicts players will regress after rest, but well-rested players actually score above the line. Investigate if the model's rest features are inverted or if this is a Vegas line adjustment issue.

### 5c. Quantile Confidence Fix
Q43/Q45 models have fully inverted confidence (0.95 = 39-42% HR). These models need a SEPARATE confidence calibration or confidence should be ignored entirely for quantile models.

### 5d. Signal Metadata Persistence
Currently signal metadata (z-scores, thresholds, actual values) is computed but NOT stored in BQ. Adding a `signal_metadata` JSON column to `pick_signal_tags` would enable deeper retroactive analysis.

---

## Execution Order for Session 278

| Step | Task | Estimated Effort | Impact |
|------|------|-----------------|--------|
| 1 | Smart filters (A+B+C) in aggregator | 30 min | +4% HR |
| 2 | Pick angles builder + integration | 1-2 hours | User understanding |
| 3 | BQ schema changes for angles | 15 min | Storage |
| 4 | Deploy + verify on Feb 19th data | 30 min | Validation |
| 5 | Monitor cross-model subsets | Ongoing | Data collection |

### Pre-requisites
- All Session 277 changes deployed (DONE)
- BQ schema updated (DONE)
- V12-quantile subset definitions inserted (DONE)

### Verification Queries (Post Feb 19th)
```sql
-- Check pick angles are populated
SELECT game_date, player_name, pick_angles, signal_tags
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-02-19'
ORDER BY rank;

-- Check smart filters reduced bad picks
SELECT
  COUNTIF(line_value < 12 AND recommendation = 'UNDER') as bench_under_blocked,
  COUNTIF(ABS(edge) / NULLIF(line_value, 0) >= 0.30) as rel_edge_blocked
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-02-19';

-- Check cross-model subsets generating data
SELECT subset_id, COUNT(*) as picks
FROM nba_predictions.current_subset_picks
WHERE game_date = '2026-02-19' AND subset_id LIKE 'xm_%'
GROUP BY 1;
```

---

## Key Data Points to Reference

### Confidence Tier Hit Rates (V9, Edge 3+)
| Tier | HR | N | Action |
|------|----|---|--------|
| 0.95 | 55.4% | 83 | Keep |
| 0.92 | 47.5% | 316 | **Flag in angles, consider filter** |
| 0.90 | 52.7% | 188 | Keep |
| 0.89 | 54.8% | 407 | Best volume tier |
| 0.87 | 50.9% | 395 | Marginal |

### Direction x Tier Hit Rates (V9, Edge 3+)
| Segment | HR | N | Action |
|---------|-----|---|--------|
| OVER, Edge 7+ | 72.7% | 11 | Signal boost |
| UNDER, Stars | 65.9% | 44 | Signal boost |
| OVER, Bench | 58.0% | 81 | Good |
| UNDER, Bench | 35.1% | 37 | **BLOCK** |
| UNDER, Edge 7+ | 38.5% | 26 | **BLOCK** |
| UNDER, 2+ Rest | 32.9% | 82 | **BLOCK** |

### Cross-Model Agreement (Feb 1-12)
| Scenario | N | V9 HR | V12 HR |
|----------|---|-------|--------|
| Both UNDER | 173 | 53.8% | 53.8% |
| V9=UNDER, V12=OVER | 32 | 34.4% | 65.6% |
| Both OVER | 48 | 47.9% | 41.7% |

### Files to Modify
| File | Changes |
|------|---------|
| `ml/signals/aggregator.py` | Add 3 smart filters before scoring |
| `ml/signals/pick_angle_builder.py` | **NEW** — angle generation |
| `data_processors/publishing/signal_best_bets_exporter.py` | Wire in angle builder |
| `data_processors/publishing/signal_annotator.py` | Wire in angle builder for bridge |
| `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` | Add `pick_angles` column |
| `predictions/worker/prediction_systems/catboost_v8.py` | Future: confidence overhaul |
