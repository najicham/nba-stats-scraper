# Session 135 Handoff - Breakout Classifier V3 Ready

**Date:** 2026-02-05
**Status:** V2 deployed, V3 roadmap complete, ready to implement
**Next Session Focus:** Add high-impact contextual features to V3

---

## TL;DR

- ✅ Deployed V2 model with shared features (AUC 0.5708)
- ✅ Refactored experiment runner for consistency
- ❌ V2 shows NO high-confidence predictions (max < 0.6)
- 🎯 V3 plan: Add 3-5 contextual features for high-confidence signals

---

## Current State

### Production Model
- **File:** `gs://nba-props-platform-models/breakout/v1/breakout_shared_v1_20251102_20260205.cbm`
- **Features:** 14 (V2)
- **Performance:** AUC 0.5708, precision@0.5 = 23.9%
- **Critical Issue:** No predictions above 0.6 confidence
- **Status:** Shadow mode (not affecting production bets)

### What Works
- ✅ Shared feature module prevents train/eval mismatch
- ✅ `minutes_increase_pct` is 2nd most important feature (16.9%)
- ✅ Experiment runner has dual modes (shared/experimental)

### What Doesn't Work
- ❌ Model too conservative (no high-confidence predictions)
- ❌ `fourth_quarter_trust` broken (zero variance)
- ❌ Current features lack strong signal

---

## V3 Roadmap (HIGH PRIORITY)

### Philosophy: Quality > Quantity

**Start with:** V1 (10 features) + `minutes_increase_pct` = 11 base features
**Add:** 3-5 high-impact contextual features
**Goal:** AUC > 0.70, precision@0.769 > 50%

### Tier 1 Features (Add These First)

#### 1. star_teammate_out (HIGHEST IMPACT)
- **What:** Count of star teammates (15+ PPG) OUT for game
- **Why:** Role players get 5-10 extra shots when star is out
- **Source:** `nbac_injury_report` + join with `player_daily_cache`
- **Expected gain:** +0.04-0.07 AUC
- **Complexity:** Medium (requires injury data join)

```sql
-- Pseudocode
SELECT
  COUNT(*) as star_teammate_out
FROM nbac_injury_report
WHERE team = player_team
  AND game_date = target_date
  AND status IN ('OUT', 'DOUBTFUL')
  AND player_season_ppg >= 15.0
```

#### 2. fg_pct_last_game
- **What:** Field goal % in previous game
- **Why:** Hot shooting carries over (rhythm effect)
- **Source:** `player_game_summary`
- **Expected gain:** +0.02-0.04 AUC
- **Complexity:** Low (already in game summary)

#### 3. points_last_4q
- **What:** Points scored in 4Q of previous game
- **Why:** 4Q performance signals confidence/rhythm
- **Source:** `player_game_summary` or `nbac_play_by_play`
- **Expected gain:** +0.02-0.04 AUC
- **Complexity:** Medium (may need play-by-play parsing)

#### 4. opponent_key_injuries
- **What:** Count of opponent starters OUT
- **Why:** Weakened defense = easier scoring
- **Source:** `nbac_injury_report`
- **Expected gain:** +0.03-0.05 AUC
- **Complexity:** Medium

### Implementation Order

1. **star_teammate_out** - Highest impact, start here
2. **fg_pct_last_game** - Easy win
3. **points_last_4q** - Momentum signal
4. Train V3a and measure improvement
5. Add **opponent_key_injuries** if needed

---

## Critical Files

```
ml/features/breakout_features.py          # Shared feature module (extend for V3)
ml/experiments/train_and_evaluate_breakout.py  # Training script
models/breakout_v2_14features.cbm          # Current best model
predictions/shared/injury_integration.py   # Injury data handling (USE THIS!)
```

---

## Feature Quality Validation (BUILD THIS)

**Problem:** V2 had broken feature (`fourth_quarter_trust` = all 25.0)

**Solution:** Add validation before training

```python
class FeatureQualityValidator:
    """Ensure features meet quality before training."""

    def validate(self, df, feature_name):
        """
        Returns: (is_valid, issues)
        """
        issues = []

        # Check 1: NULL rate < 5%
        null_rate = df[feature_name].isnull().mean()
        if null_rate > 0.05:
            issues.append(f"NULL rate too high: {null_rate:.1%}")

        # Check 2: Variance > 0 (catch flat features)
        if df[feature_name].std() == 0:
            issues.append(f"Zero variance (all values same)")

        # Check 3: No infinite values
        if np.isinf(df[feature_name]).any():
            issues.append(f"Contains infinite values")

        return len(issues) == 0, issues
```

**Usage:**
```python
validator = FeatureQualityValidator()
for feature in new_features:
    valid, issues = validator.validate(df_train, feature)
    if not valid:
        print(f"❌ {feature}: {issues}")
        # Don't add to model
```

---

## Key Learnings

### Anti-Pattern: Assuming Fields Exist
**Session 135:** Tried to use `minutes_avg_season` and `is_starter` - neither existed
**Fix:** Always check schema first:
```bash
bq show --schema nba-props-platform:nba_precompute.player_daily_cache | jq -r '.[].name'
```

### Learning: Context Beats Statistics
**Observation:** Statistical features (avg, std, trends) provide weak signal
**Better:** Contextual features (star out, opponent weak, hot shooting)
**V3 Strategy:** Add features that capture **opportunity** and **matchup quality**

### Learning: High Confidence Requires Strong Features
**V2 Problem:** No predictions > 0.6 confidence
**Why:** Weak features → weak conviction
**V3 Goal:** Strong contextual signals → high-confidence predictions (>0.769)

---

## Next Session Quick Start

### Step 1: Read Context (5 min)
```bash
# Read this handoff
cat docs/09-handoff/2026-02-05-SESSION-135-HANDOFF.md

# Read V3 plan details
cat docs/09-handoff/2026-02-05-SESSION-135-BREAKOUT-V2-AND-V3-PLAN.md

# Check current production state
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" | grep BREAKOUT
```

### Step 2: Build star_teammate_out Feature (30-60 min)

**Existing infrastructure to leverage:**
```python
# Injury integration already exists!
from predictions.shared.injury_integration import (
    get_team_injuries,
    get_injury_impact_for_player
)

# Use this to get teammate injuries
injuries = get_team_injuries(team='LAL', game_date='2026-02-05')
star_out = len([i for i in injuries if i['status'] == 'OUT' and i['ppg'] >= 15])
```

**Add to shared feature module:**
```python
# In ml/features/breakout_features.py

# 1. Add to BREAKOUT_FEATURE_ORDER_V3
BREAKOUT_FEATURE_ORDER_V3 = BREAKOUT_FEATURE_ORDER_V1 + [
    "minutes_increase_pct",    # Proven winner from V2
    "star_teammate_out",       # V3: High-impact contextual
    # ... more V3 features
]

# 2. Add to get_training_data_query()
# Join with injury data to compute star_teammate_out

# 3. Add to prepare_feature_vector()
# Extract star_teammate_out from query results
```

### Step 3: Train V3a (10 min)
```bash
PYTHONPATH=. python ml/experiments/train_and_evaluate_breakout.py \
  --train-start 2025-11-02 \
  --train-end 2026-01-31 \
  --eval-start 2026-02-01 \
  --eval-end 2026-02-04 \
  --save-model models/breakout_v3a_star_teammate.cbm
```

**Look for:**
- AUC improvement > +0.04 vs V2 (0.5708)
- Predictions with confidence > 0.7 (finally!)
- `star_teammate_out` feature importance > 10%

### Step 4: Iterate
- If V3a works: Add `fg_pct_last_game` and `points_last_4q`
- If V3a fails: Debug feature quality, check NULL rates
- Target: AUC > 0.70 with high-confidence predictions

---

## Success Criteria for V3

| Metric | V2 Actual | V3 Minimum | V3 Target |
|--------|-----------|------------|-----------|
| AUC | 0.5708 | 0.65 | 0.70+ |
| Precision@0.5 | 23.9% | 30% | 40% |
| Max confidence | <0.6 | 0.7+ | 0.8+ |
| Predictions@0.769 | 0 | Some | 10%+ of eval set |

---

## Common Pitfalls to Avoid

1. **Don't assume fields exist** - Check schema first
2. **Don't skip feature validation** - Catch broken features early
3. **Don't add features blindly** - One at a time, measure AUC delta
4. **Don't forget to commit** - Save work incrementally
5. **Don't deploy without testing** - Validate on holdout set first

---

## Questions to Consider

1. Should we lower precision target from 60% to 40% at threshold 0.5?
2. Should we change breakout definition to 1.75x or 2.0x (more extreme)?
3. Should we focus on specific props (rebounds/assists) instead of points?

---

## Documentation References

- **Full V3 Plan:** `docs/09-handoff/2026-02-05-SESSION-135-BREAKOUT-V2-AND-V3-PLAN.md`
- **Session 134 Context:** `docs/09-handoff/2026-02-05-SESSION-134-COMPLETE-SUMMARY.md`
- **CLAUDE.md [BREAKOUT]:** Production guide and model info
- **Data Sources Research:** Session 135 Explore agent findings

---

## Final Notes

**V3 is the real opportunity.** V2 proved that:
- Feature engineering matters more than hyperparameters
- Statistical features plateau around AUC 0.60
- Contextual features (teammate out, hot shooting) should unlock high-confidence predictions

**The infrastructure is ready.** Injury integration exists, feature module is solid, experiment framework works.

**Next session should focus entirely on adding and testing the 3-5 Tier 1 V3 features.**

Good luck! 🚀

---

**Session 135 Status:** COMPLETE ✅
**V3 Status:** READY TO BUILD 🎯
**Production Status:** V2 deployed, shadow mode 🔄
