# Session 136 Prompt - Breakout Classifier V3 Implementation

Copy and paste this to start the next session:

---

## Context

I'm continuing work on the NBA breakout classifier (Session 136). Previous session (135) deployed V2 model but found it produces NO high-confidence predictions (max confidence <0.6, need 0.769+).

**Quick background:**
- **Goal:** Predict when role players (8-16 PPG) will have "breakout games" (1.5x season avg)
- **Use case:** Filter OUT high-risk breakout candidates from UNDER bets
- **Current model:** V2 (AUC 0.5708, 14 features, shadow mode)
- **Problem:** No predictions above 0.6 confidence → can't use in production
- **Root cause:** Current features are all statistical (avg, std, trends) - weak signal

## What I Need You To Do

**Build V3 with high-impact contextual features** that unlock high-confidence predictions.

### Priority 1: Add star_teammate_out Feature

**What it is:** Count of star teammates (15+ PPG) OUT for the game
**Why it matters:** Role players get 5-10 extra shots when star is out → strong breakout signal
**Expected improvement:** +0.04-0.07 AUC, enables confidence > 0.7 predictions

**Implementation:**
1. Extend `ml/features/breakout_features.py` with V3 feature set
2. Add `star_teammate_out` to training query (join with injury data)
3. Use existing `predictions/shared/injury_integration.py` infrastructure
4. Add feature quality validation (NULL rate, variance checks)

### Priority 2: Add fg_pct_last_game & points_last_4q

**fg_pct_last_game:** Hot shooting carries over (rhythm effect)
**points_last_4q:** 4Q performance signals confidence

Both should be easy - data exists in `player_game_summary`

### Priority 3: Train and Evaluate V3a

Train with new features, measure:
- AUC > 0.65 (vs V2: 0.5708)
- Max confidence > 0.7 (vs V2: <0.6)
- Feature importance of new features

## Key Files to Work With

```
ml/features/breakout_features.py              # Extend for V3
ml/experiments/train_and_evaluate_breakout.py # Training script
predictions/shared/injury_integration.py      # Injury data (already exists!)
docs/09-handoff/2026-02-05-SESSION-135-HANDOFF.md  # Full handoff
```

## Quick Start Commands

```bash
# 1. Read the detailed handoff
cat docs/09-handoff/2026-02-05-SESSION-135-HANDOFF.md

# 2. Check schema for available fields
bq show --schema nba-props-platform:nba_precompute.player_daily_cache | jq -r '.[].name'

# 3. Test current V2 model
PYTHONPATH=. python ml/experiments/train_and_evaluate_breakout.py \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-04
```

## Success Criteria

- ✅ V3a AUC > 0.65 (minimum) or 0.70 (target)
- ✅ At least SOME predictions with confidence > 0.769
- ✅ Precision@0.5 > 30%
- ✅ `star_teammate_out` feature importance > 10%

## Critical Reminders

1. **Always validate features** - Check NULL rate < 5%, std > 0 before training
2. **Check schema first** - Don't assume fields exist (Session 135 lesson!)
3. **Add one feature at a time** - Measure AUC delta for each
4. **Use existing injury integration** - Don't rebuild what exists
5. **Commit incrementally** - Save work as you go

## What Previous Session Learned

**Anti-Pattern:** Adding features blindly without validation
- V2 added 4 features, 1 was broken (zero variance)
- Modest improvement (+0.007 AUC) for significant complexity

**Key Insight:** Quality > Quantity
- `minutes_increase_pct` alone contributed 16.9% importance
- Contextual features (teammate out, hot shooting) should be even stronger

**Infrastructure Ready:**
- Shared feature module prevents train/eval mismatch
- Experiment runner has dual modes (shared/experimental)
- Injury data readily available

## Expected Outcomes

By end of session, you should have:
1. V3a model trained with `star_teammate_out` feature
2. AUC improvement measured (expect +0.04-0.07)
3. High-confidence predictions unlocked (>0.7)
4. Feature quality validation framework built
5. Next features ready to add (fg_pct, 4Q points)

## If You Get Stuck

**SQL errors:** Check schema with `bq show --schema` before using field names
**Broken features:** Add validation - print NULL rate, std, min/max before training
**Low AUC improvement:** Feature might not be populated - check data availability first

## Documentation

Full context in:
- `docs/09-handoff/2026-02-05-SESSION-135-HANDOFF.md` (read this first!)
- `docs/09-handoff/2026-02-05-SESSION-135-BREAKOUT-V2-AND-V3-PLAN.md` (deep dive)
- `CLAUDE.md` section [BREAKOUT] (production reference)

---

**Ready to build V3 and unlock high-confidence breakout predictions! Let's do this.** 🚀
