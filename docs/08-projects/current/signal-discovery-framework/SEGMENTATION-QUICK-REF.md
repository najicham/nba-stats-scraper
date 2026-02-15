# Harmful Signals Segmentation - Quick Reference

**Session 256** | **Date:** 2026-02-14 | **Status:** BOTH SIGNALS SALVAGEABLE

## TL;DR

Both "harmful" signals are **profitable in specific niches**. Re-enable with conditional logic.

| Signal | Original HR | Salvaged HR | Condition | N |
|--------|-------------|-------------|-----------|---|
| `prop_value_gap_extreme` | 12.5% | **89.3%** | `line < 15 AND OVER` | 28 |
| `edge_spread_optimal` | 47.4% | **76.9%** | `OVER AND edge >= 5` | 65 |

## Code Changes Required

### 1. prop_value_gap_extreme.py

```python
def evaluate(self, prediction: Dict, features: Optional[Dict] = None,
             supplemental: Optional[Dict] = None) -> SignalResult:
    edge = abs(prediction.get('edge', 0))
    line_value = prediction.get('line_value', 0)
    recommendation = prediction.get('recommendation', '')

    if edge < self.MIN_EDGE:  # MIN_EDGE = 10.0
        return self._no_qualify()

    # NEW: Block mid-tier and UNDER bets (toxic)
    if line_value >= 15:
        return self._no_qualify()
    if recommendation != 'OVER':
        return self._no_qualify()

    return SignalResult(
        qualifies=True,
        confidence=0.92,  # Based on 89.3% empirical HR
        source_tag=self.tag,
        metadata={'edge': round(edge, 2), 'line_value': line_value}
    )
```

### 2. edge_spread_optimal.py

```python
def evaluate(self, prediction: Dict, features: Optional[Dict] = None,
             supplemental: Optional[Dict] = None) -> SignalResult:
    edge = abs(prediction.get('edge', 0))
    recommendation = prediction.get('recommendation', '')

    if edge < self.MIN_EDGE:  # MIN_EDGE = 5.0
        return self._no_qualify()

    # NEW: OVER-only (UNDER is toxic 46.8% HR)
    if recommendation != 'OVER':
        return self._no_qualify()

    # REMOVED: Confidence band filtering (70-88%, exclude 88-90%) — adds no value

    return SignalResult(
        qualifies=True,
        confidence=0.85,  # Based on 76.9% empirical HR
        source_tag=self.tag,
        metadata={'edge': round(edge, 2)}
    )
```

### 3. Re-enable in registry (ml/signals/registry.py)

```python
def build_default_registry() -> SignalRegistry:
    registry = SignalRegistry()
    # ... existing signals
    registry.register(PropValueGapExtremeSignal())  # Re-enable
    registry.register(EdgeSpreadOptimalSignal())     # Re-enable
    return registry
```

## Why It Works

### prop_value_gap_extreme
- Detects all-stars with underpriced lines (LeBron @ 7.9, Embiid @ 8.4)
- Mid-tier (15-25 line): 6.5% HR (TOXIC)
- UNDER bets: 16.7% HR (TOXIC)
- Role players (<15) + OVER: 89.3% HR (PROFITABLE)

### edge_spread_optimal
- High edge (5+) OVER bets capture upside when model has strong conviction
- UNDER bets: 46.8% HR (TOXIC)
- OVER bets: 76.9% HR (PROFITABLE)
- Confidence band filtering: NO VALUE

## Key Pattern: OVER Bias

| Signal | OVER HR | UNDER HR | Delta |
|--------|---------|----------|-------|
| prop_value_gap_extreme | 84.4% | 16.7% | +67.7% |
| edge_spread_optimal | 76.6% | 46.8% | +29.8% |

**Model excels at identifying upside, struggles with downside.**

## Implementation Checklist

- [ ] Update `ml/signals/prop_value_gap_extreme.py` with conditions
- [ ] Update `ml/signals/edge_spread_optimal.py` with OVER-only logic
- [ ] Re-enable both in `ml/signals/registry.py`
- [ ] Backfill signal tags for 2026-01-09 to present
- [ ] Monitor for 7 days with `validate-daily` Phase 0.58
- [ ] Promote to Best Bets if 7-day HR >= 65%

## Expected Impact

- **prop_value_gap_extreme**: 12.5% → 89.3% HR (7.1x improvement)
- **edge_spread_optimal**: 47.4% → 76.9% HR (1.6x improvement)
- **Combined**: ~90 high-quality picks per month vs 0 today

## Full Analysis

See: `docs/08-projects/current/signal-discovery-framework/HARMFUL-SIGNALS-SEGMENTATION.md`

## Validation Query

```sql
-- Confirm salvaged performance
WITH prop_extreme AS (
  SELECT COUNT(*) as picks, COUNTIF(pa.prediction_correct) as wins
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa USING (player_lookup, game_id, system_id)
  JOIN nba_predictions.player_prop_predictions pp USING (player_lookup, game_id, system_id)
  WHERE pst.game_date >= '2026-01-09'
    AND 'prop_value_gap_extreme' IN UNNEST(pst.signal_tags)
    AND pa.line_value < 15 AND pa.recommendation = 'OVER'
),
edge_optimal AS (
  SELECT COUNT(*) as picks, COUNTIF(pa.prediction_correct) as wins
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa USING (player_lookup, game_id, system_id)
  JOIN nba_predictions.player_prop_predictions pp USING (player_lookup, game_id, system_id)
  WHERE pst.game_date >= '2026-01-09'
    AND 'edge_spread_optimal' IN UNNEST(pst.signal_tags)
    AND pa.recommendation = 'OVER' AND ABS(pp.line_margin) >= 5
)
SELECT * FROM prop_extreme UNION ALL SELECT * FROM edge_optimal;
```

Expected: 28 picks 25 wins (89.3%), 65 picks 50 wins (76.9%)
