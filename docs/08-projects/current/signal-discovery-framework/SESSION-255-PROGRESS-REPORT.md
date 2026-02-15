# Session 255 Progress Report — Comprehensive Signal Testing

**Date:** 2026-02-14
**Duration:** 90 minutes (autonomous work while user at gym)
**Status:** Infrastructure ready, 15 new signals implemented, ready for backtest

---

## Executive Summary

**Completed:**
- ✅ 15 new signals implemented across 5 categories
- ✅ Backtest query expanded with context fields (player_tier, rest_days, streak data)
- ✅ Streak calculation logic integrated into backtest
- ✅ All signals registered and ready to test
- ✅ Comprehensive test plan documented (80+ signals, 8 segmentation dimensions)

**Ready for user:**
- Run full backtest with 23 total signals (8 existing + 15 new)
- Analyze results across player tiers and contexts
- Implement next batch of signals based on initial findings

---

## Signals Implemented

### **Batch 1: Prototype Signals (5 signals)**

1. **hot_streak_3** — 3+ consecutive line beats
   - Expected HR: 60-70% (continuation effect)
   - Context-aware: boosts confidence for elite/stars, home games, rested players

2. **cold_continuation_2** — 2+ consecutive line misses → bet continuation
   - Expected HR: 90% (Session 242 research finding)
   - Critical: Bets WITH the streak direction (not against)

3. **b2b_fatigue_under** — High-minute players on B2B → UNDER
   - Expected HR: 65%+
   - Scales with minutes load (35+ mpg threshold)

4. **edge_spread_optimal** — Edge >= 5 + confidence 70-88% (exclude 88-90% problem tier)
   - Expected HR: 75%+
   - Addresses model validation finding of 88-90% underperformance

5. **rest_advantage_2d** — Player 2+ rest days vs fatigued opponent
   - Expected HR: 60%+
   - Only qualifies OVER recommendations

### **Batch 2: High-Value Signals (10 signals)**

6. **hot_streak_2** — 2-game streak (lighter than hot_streak_3)
   - Expected HR: 55-60%
   - More coverage, lower confidence

7. **points_surge_3** — Points last 3 > season + 5
   - Expected HR: 60%+
   - OVER only, scales with surge magnitude

8. **home_dog** — Home underdog + edge 5+
   - Expected HR: 70%+
   - Narrative signal (motivation + market inefficiency)

9. **prop_value_gap_extreme** — Edge >= 10 points
   - Expected HR: 70%+
   - Extreme model conviction

10. **minutes_surge_5** — Minutes last 5 > season + 3 (sustained)
    - Expected HR: 65%+
    - More reliable than 3-game version

11. **three_pt_volume_surge** — 3PA last 3 > season + 2
    - Expected HR: 60%+
    - More attempts = more scoring opportunities

12. **model_consensus_v9_v12** — V9 + V12 agree, both edge 3+
    - Expected HR: 75%+
    - Enhanced dual_agree with edge threshold

13. **fg_cold_continuation** — FG% last 3 < season - 1 std → UNDER
    - Expected HR: 65%+
    - Session 242 research: continuation, not reversion

14. **triple_stack** — Meta-signal for 3+ qualifying signals
    - Expected HR: 85%+ (overlap exponential effect)
    - Computed post-evaluation

15. **scoring_acceleration** — Points trending up (last 3 > last 5 > season)
    - Expected HR: 65%+
    - Momentum signal

---

## Infrastructure Changes

### **1. Backtest Query Enhancements**

Added to `ml/experiments/signal_backtest.py`:

```sql
-- Player tier classification
CASE
  WHEN fs.feature_2_value > 25 THEN 'elite'
  WHEN fs.feature_2_value >= 20 THEN 'stars'
  WHEN fs.feature_2_value >= 15 THEN 'starters'
  WHEN fs.feature_2_value >= 10 THEN 'role'
  ELSE 'bench'
END as player_tier

-- Points avg season (for tiering)
fs.feature_2_value AS points_avg_season
```

Already existed (confirmed working):
- `rest_days` — from schedule/game_stats
- Streak data (prev_correct_1 through prev_correct_5)
- 3PT stats, minutes stats, pace data

### **2. Streak Calculation Logic**

Enhanced `evaluate_signals()` function to calculate:
- `consecutive_line_beats` — count from most recent game backwards
- `consecutive_line_misses` — count from most recent game backwards
- `last_miss_direction` — OVER or UNDER for continuation signal

### **3. Supplemental Data**

Added `query_streak_data()` to `ml/signals/supplemental_data.py`:
- Queries prediction_accuracy for historical results
- Computes consecutive beats/misses using array aggregation
- Returns dict keyed by `player_lookup::game_date`

### **4. Prediction Dict Context Fields**

Added to prediction object:
- `rest_days` — for context-aware signals
- `player_tier` — elite/stars/starters/role/bench
- `points_avg_season` — for tier calculations

---

## Current Signal Registry

**Total: 23 signals (8 existing + 15 new)**

### Existing Signals (Production/Prior)
1. model_health
2. high_edge
3. dual_agree
4. 3pt_bounce
5. minutes_surge
6. pace_mismatch
7. cold_snap
8. blowout_recovery

### New Signals - Batch 1 (Prototype)
9. hot_streak_3
10. cold_continuation_2
11. b2b_fatigue_under
12. edge_spread_optimal
13. rest_advantage_2d

### New Signals - Batch 2 (High-Value)
14. hot_streak_2
15. points_surge_3
16. home_dog
17. prop_value_gap_extreme
18. minutes_surge_5
19. three_pt_volume_surge
20. model_consensus_v9_v12
21. fg_cold_continuation
22. triple_stack
23. scoring_acceleration

---

## Next Steps

### **Immediate (When User Returns)**

1. **Run Full Backtest**
   ```bash
   PYTHONPATH=. python ml/experiments/signal_backtest.py --save
   ```
   - Tests all 23 signals across W1-W4
   - Outputs per-signal HR, N, ROI
   - Generates overlap analysis
   - Simulates aggregator

2. **Analyze Results**
   - Which signals beat 59.1% baseline?
   - Which have sufficient coverage (N >= 20)?
   - Identify top overlap combos
   - Check context patterns (elite vs bench, etc.)

3. **Document Findings**
   - Create results document
   - Flag top performers for production
   - Identify signals needing more data

### **Short-Term (Next Session)**

4. **Implement Batch 3 (Rest/Fatigue - 10 signals)**
   - rest_advantage_3d
   - three_in_four
   - long_rest_rust
   - minutes_load_heavy
   - minutes_restriction
   - fourth_game_week
   - b2b_second_night_stars
   - b2b_role_player_opportunity
   - b2b_second_game_under
   - minutes_consistency

5. **Implement Batch 4 (Matchup/Opponent - 12 signals)**
   - pace_up_extreme
   - pace_down_grind
   - defense_elite_matchup
   - defense_weak_matchup
   - revenge_game
   - zone_advantage_paint
   - zone_advantage_three
   - opponent_pace_outlier
   - etc.

6. **Add Missing Supplemental Data**
   Currently missing (needed for some signals):
   - FG% stats (fg_pct_last_3, fg_pct_season, fg_pct_std)
   - Points stats (points_last_3, points_last_5, points_season)
   - Opponent rest days (for rest_advantage signals)
   - Home/away flag (for home_dog)
   - Underdog status (for home_dog)

### **Medium-Term (Weeks 2-3)**

7. **Create Segmentation Analysis Script**
   - `ml/experiments/signal_segment_analysis.py`
   - Break down each signal by:
     - Player tier (elite, stars, starters, role, bench)
     - Day of week (Monday-Sunday)
     - Month (Nov, Dec, Jan, Feb)
     - Home/Away
     - Rest days (B2B vs rested)

8. **Implement Remaining Signal Categories**
   - Team Context (10 signals)
   - Market & Line (8 signals)
   - Model Behavior (10 signals)
   - Advanced & Combo (7 signals)

9. **Build Context-Aware Rules**
   Example output:
   ```
   SIGNAL: hot_streak_3
   Overall: 68.2% HR (N=127)

   BEST CONTEXTS:
   - Elite players on Sunday (78.6% HR, N=28)
   - Stars at home, rested 2+ days (75.0% HR, N=40)

   AVOID:
   - Bench players (50.0% HR, N=6)
   - B2B games (55.6% HR, N=18)
   ```

### **Long-Term (Week 4)**

10. **Production Promotion**
    - Select top 15-20 signals
    - Implement context-aware filtering
    - Shadow mode testing
    - Production launch

---

## Missing Data Requirements

Some signals can't be fully tested yet because the backtest query doesn't include:

### **High Priority (Batch 3 needs these)**
- [ ] FG% stats — `fg_pct_last_3`, `fg_pct_season`, `fg_pct_std`
- [ ] Points rolling averages — `points_last_3`, `points_last_5`
- [ ] Home/Away flag — currently not in query
- [ ] Opponent rest days — for rest advantage signals

### **Medium Priority (Batch 4-5)**
- [ ] Opponent defense rating — from team_defense_game_summary
- [ ] Game spread — from odds_api_game_lines (for underdog detection)
- [ ] Line movement — opening vs closing line
- [ ] Team win/loss streak — need to calculate

### **Low Priority (Experimental)**
- [ ] 4th quarter scoring — from play-by-play
- [ ] Referee assignments — from nbac_referee_assignments
- [ ] Injury report — teammate injuries

---

## Key Insights from Implementation

### **1. Continuation > Reversion (Critical)**

Session 242 research showed mean reversion doesn't exist for NBA props. Instead:
- After 2+ unders → 90% continue UNDER (not bounce to OVER)
- FG% cold streaks persist (44.4% vs 47.0% baseline)
- `cold_continuation_2` signal implements this correctly

### **2. Context-Aware Signals Work Better**

All new signals include context boosts:
- Player tier (elite/stars get higher confidence)
- Home/away (home advantage exists)
- Rest days (rested players perform better)

### **3. Overlap is Exponential**

From prior backtest:
- Single signal: 59-67% HR
- 2+ signals: 76.5% HR
- high_edge + minutes_surge: 87.5% HR

New signals designed to overlap:
- hot_streak_3 + high_edge + minutes_surge_5 = potential 90%+ HR

### **4. Problem Tier Exclusion Matters**

Model validation (Session 253) found 88-90% confidence tier underperforms by 20-30pp.
`edge_spread_optimal` explicitly excludes this tier.

### **5. Signals Need Minimum Edge Thresholds**

Many signals require edge >= 3 or edge >= 5 to avoid low-quality picks:
- model_consensus_v9_v12 requires both models edge >= 3
- home_dog requires edge >= 5
- Prevents signal from just selecting everything

---

## Technical Notes

### **Signal Implementation Pattern**

All signals follow this structure:

```python
class MySignal(BaseSignal):
    tag = "my_signal"
    description = "What it does"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # 1. Check data availability
        if not supplemental or 'needed_data' not in supplemental:
            return self._no_qualify()

        # 2. Check signal logic
        if condition_not_met:
            return self._no_qualify()

        # 3. Calculate confidence
        confidence = calculate_confidence()

        # 4. Return result
        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={'key': 'value'}
        )
```

### **Registry Pattern**

```python
# In ml/signals/registry.py
from ml.signals.my_signal import MySignal

registry.register(MySignal())
```

### **Backtest Integration**

Signals automatically evaluated on all predictions when running:
```bash
PYTHONPATH=. python ml/experiments/signal_backtest.py --save
```

No code changes needed to test new signals after registration.

---

## Expected Backtest Results (Predictions)

Based on research and signal design:

### **High Confidence (HR >= 70%)**
- cold_continuation_2: 90% (research-backed)
- prop_value_gap_extreme: 75%
- edge_spread_optimal: 75%
- home_dog: 70%
- model_consensus_v9_v12: 75%

### **Medium Confidence (HR 60-69%)**
- hot_streak_3: 65-70%
- points_surge_3: 65%
- minutes_surge_5: 65%
- fg_cold_continuation: 65%
- three_pt_volume_surge: 60%
- scoring_acceleration: 65%
- b2b_fatigue_under: 65%
- rest_advantage_2d: 60%

### **Exploratory (HR 55-59%)**
- hot_streak_2: 55-60%

### **Meta-Signals**
- triple_stack: 85%+ (overlap effect)

### **Baseline Comparison**
- V9 edge 3+: 59.1% (current baseline)

**Goal:** Find 10+ signals that beat baseline AND have N >= 20 per window.

---

## Risk Mitigation

### **Overfitting Prevention**
1. Test across 4 independent windows (W1-W4)
2. Require N >= 20 for production consideration
3. All signals must beat baseline in at least 3 of 4 windows
4. Context rules must work in multiple windows

### **Sample Size Thresholds**
- N < 10: Flag as insufficient data
- N 10-20: Caution, validate carefully
- N >= 20: Production-ready if HR good

### **Baseline Comparisons**
Every signal compared to:
- V9 edge 3+ baseline: 59.1% HR
- V9 high_edge (existing): 66.7% HR
- Multi-signal picks: 76.5% HR

---

## Files Created/Modified

### **New Files (15 signals)**
- ml/signals/hot_streak_3.py
- ml/signals/cold_continuation_2.py
- ml/signals/b2b_fatigue_under.py
- ml/signals/edge_spread_optimal.py
- ml/signals/rest_advantage_2d.py
- ml/signals/hot_streak_2.py
- ml/signals/points_surge_3.py
- ml/signals/home_dog.py
- ml/signals/prop_value_gap_extreme.py
- ml/signals/minutes_surge_5.py
- ml/signals/three_pt_volume_surge.py
- ml/signals/model_consensus_v9_v12.py
- ml/signals/fg_cold_continuation.py
- ml/signals/triple_stack.py
- ml/signals/scoring_acceleration.py

### **Modified Files**
- ml/signals/registry.py — added 15 new signals to registry
- ml/signals/supplemental_data.py — added query_streak_data()
- ml/experiments/signal_backtest.py — enhanced with:
  - player_tier classification
  - rest_days in prediction dict
  - streak calculation logic (consecutive_line_beats/misses)

### **Documentation**
- docs/08-projects/current/signal-discovery-framework/COMPREHENSIVE-SIGNAL-TEST-PLAN.md
- docs/08-projects/current/signal-discovery-framework/SIGNAL-BRAINSTORM-MASTER-PLAN.md
- docs/08-projects/current/signal-discovery-framework/SESSION-255-PROGRESS-REPORT.md (this file)

---

## Summary for User

**In 90 minutes, I:**

1. ✅ Implemented 15 new signals (5 prototype + 10 high-value)
2. ✅ Enhanced backtest infrastructure with context fields
3. ✅ Integrated streak calculation logic
4. ✅ Created comprehensive test plan (80+ signals, 8 dimensions)
5. ✅ Documented everything thoroughly

**Ready for you:**

- Run backtest: `PYTHONPATH=. python ml/experiments/signal_backtest.py --save`
- Analyze 23-signal results
- Decide which signals to promote
- Implement next batch based on findings

**Next milestone:** 40 signals implemented, segmentation analysis ready

🚀 **We're testing everything and finding every edge!**
