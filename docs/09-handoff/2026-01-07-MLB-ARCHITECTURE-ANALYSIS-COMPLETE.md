# MLB Pitcher Strikeouts - Architecture Analysis Complete

**Date**: 2026-01-07
**Status**: Comprehensive gap analysis completed, implementation roadmap defined

---

## Session Summary

This session conducted a thorough comparison of NBA's production architecture with MLB's current state to identify gaps and create an implementation roadmap.

### What Was Analyzed

Used 3 exploration agents to analyze:
1. **NBA Phase 2-3** (Raw + Analytics): 6 data sources, 6 analytics tables, 254+ fields
2. **NBA Phase 4** (Precompute): 7 tables, 5 processors, 25 ML features, smart patterns
3. **NBA Phase 5-6** (Predictions): 5 systems, coordinator/worker, grading pipeline

---

## Key Findings

### MLB is AHEAD on Scrapers/Raw

| Component | NBA | MLB | Status |
|-----------|-----|-----|--------|
| Scrapers | 27 | 28 | MLB ahead |
| Raw Tables | 18 | 22 | MLB ahead |
| Raw Processors | 13+ | 8 | Close |

### MLB is BEHIND on Analytics/Precompute

| Component | NBA | MLB | Gap |
|-----------|-----|-----|-----|
| Analytics Tables | 6 (254 fields) | 2 (80 fields) | **Missing 4 tables** |
| Precompute Tables | 7 | 1 | **Missing 6 tables** |
| ML Feature Store | Production | Partial | Needs enhancement |
| Prediction Systems | 5 | 0 | **Not started** |
| Grading Pipeline | Complete | 0 | **Not started** |

---

## Critical Missing Tables

### Analytics (Phase 3) - 4 Tables Needed

1. **upcoming_pitcher_game_context** (50+ fields) - CRITICAL
   - Pre-game context for predictions
   - Betting lines, opponent analysis, weather
   - Similar to NBA's upcoming_player_game_context

2. **team_game_summary** (45+ fields) - HIGH
   - Team-level aggregates
   - Batting/pitching averages
   - Supports bottom-up model

3. **upcoming_team_game_context** (30+ fields) - MEDIUM
   - Pre-game team context
   - Series info, travel, betting

### Precompute (Phase 4) - 4 Tables Needed

1. **pitcher_daily_cache** (35+ fields) - HIGH
   - Fast lookup cache (79% cost reduction)
   - Eliminates repeated queries
   - Pattern from NBA's player_daily_cache

2. **pitcher_composite_factors** (25+ fields) - HIGH
   - 4 adjustment scores: fatigue, matchup, ballpark, form
   - Feeds ML features
   - Pattern from NBA's player_composite_factors

3. **opponent_lineup_analysis** (30+ fields) - MEDIUM
   - Bottom-up K calculation
   - Per-batter analysis
   - Unique to MLB (no NBA equivalent)

4. **ml_feature_store (enhanced)** - HIGH
   - Add 14-field completeness checking
   - Add source tracking (v4.0 pattern)
   - Add smart idempotency

---

## Implementation Roadmap

### Phase 1: Analytics Foundation (Week 1-2)
- Create upcoming_pitcher_game_context
- Create team_game_summary
- Add source tracking v4.0 pattern

### Phase 2: Precompute Pipeline (Week 2-3)
- Create pitcher_daily_cache
- Create pitcher_composite_factors
- Create opponent_lineup_analysis
- Enhance ml_feature_store

### Phase 3: ML Training (Week 3-4)
- Historical backfill (2023-2024 seasons)
- Create training script
- Train initial XGBoost model

### Phase 4: Prediction System (Week 4-5)
- Moving Average Baseline
- XGBoost V1
- Ensemble V1
- Worker + Coordinator

### Phase 5: Grading & Evaluation (Week 5-6)
- Prediction accuracy processor
- Performance summary
- Calibration analysis

---

## Documentation Created

| File | Purpose |
|------|---------|
| `PHASE-ARCHITECTURE-ANALYSIS.md` | Detailed gap analysis (400+ lines) |
| `ULTRATHINK-MLB-SPECIFIC-ARCHITECTURE.md` | **NEW** - MLB-specific requirements vs NBA |
| `CURRENT-STATUS.md` | Updated with gap summary |
| This handoff doc | Session summary |

---

## ULTRATHINK: MLB-Specific Architecture

The second analysis focused on what makes MLB fundamentally DIFFERENT from NBA:

### The Key Insight

**NBA**: Unknown matchups - "Who guards LeBron?" is probabilistic
**MLB**: KNOWN matchups - "Pitcher faces batters 1-9 in order" is deterministic

The **bottom-up model** (sum of individual batter K probabilities) is THE key feature for MLB.

### New Tables Needed (MLB-Specific)

| Table | Purpose | Priority |
|-------|---------|----------|
| `lineup_k_analysis` | Per-game lineup K calculation | CRITICAL |
| `pitcher_arsenal_summary` | Pitch mix, whiff rates, velocity | HIGH |
| `batter_k_profile` | Individual K vulnerability, platoon splits | HIGH |
| `umpire_game_assignment` | Umpire strike zone tendencies | MEDIUM |
| `pitcher_innings_projection` | Expected IP (affects K opportunities) | MEDIUM |
| `pitcher_batter_history` | Historical pitcher vs specific batter | LOWER |

### New Features to Add (f25-f34)

| Feature | Name | Why It Matters |
|---------|------|----------------|
| f25 | bottom_up_k_expected | Sum of individual batter K probs - THE KEY |
| f26 | lineup_k_vs_hand | Lineup K rate vs pitcher's handedness |
| f27 | platoon_advantage | LHP vs RHH lineup advantage |
| f28 | umpire_k_factor | Umpire's impact on Ks |
| f29 | projected_innings | Expected IP (more IP = more K opportunities) |
| f30 | velocity_trend | Velo up/down from season average |
| f31 | whiff_rate | Swing-and-miss ability |
| f32 | put_away_rate | K rate with 2 strikes |
| f33 | lineup_weak_spots | Number of high-K-rate batters in lineup |
| f34 | matchup_edge | Historical advantage vs this lineup |

### Grading Differences

MLB needs **dual grading** to account for IP variance:
1. **Absolute Grading** - For betting (predicted K vs actual K)
2. **Rate-Adjusted Grading** - For model improvement (K/9 comparison)

---

## Key Architectural Patterns to Implement

From NBA that MLB needs:

1. **Smart Idempotency** - data_hash field for duplicate detection
2. **Source Tracking v4.0** - 4 fields per upstream source
3. **14-Field Completeness Checking** - Production readiness gates
4. **Circuit Breaker** - Stop after 5 failures, 24h cooldown
5. **Early Season Handling** - Placeholder records first 7 days
6. **Batch Consolidation** - Staging tables + MERGE (avoids DML limits)

---

## Next Steps (Choose One)

### Option A: Start with Analytics Tables
```bash
# Create upcoming_pitcher_game_context table
# Then create processor
# Then backfill job
```

### Option B: Start with Historical Backfill
```bash
# Run scrapers for 2024 season
# Process raw data
# Populate existing tables first
```

### Option C: Create Training Script First
```bash
# Adapt NBA template (ml/train_real_xgboost.py)
# Won't work without data but gets structure ready
```

**Recommendation**: Option A - Create analytics infrastructure first, then backfill will populate all layers correctly.

---

## Copy-Paste for Next Session

```
Continue the MLB pitcher strikeouts project.

Read: docs/08-projects/current/mlb-pitcher-strikeouts/PHASE-ARCHITECTURE-ANALYSIS.md

COMPLETED THIS SESSION:
- Comprehensive NBA vs MLB architecture comparison
- Identified 4 missing analytics tables
- Identified 4 missing precompute tables
- Created detailed implementation roadmap

CURRENT STATE:
- Scrapers: 28/28 complete (ahead of NBA)
- Raw Tables: 22/22 complete
- Analytics: 2/6 (missing 4)
- Precompute: 1/7 (missing 6)
- Predictions: 0/5 (not started)

PRIORITY GAPS:
1. upcoming_pitcher_game_context (50+ fields)
2. pitcher_daily_cache (35+ fields)
3. pitcher_composite_factors (25+ fields)
4. ml_feature_store enhancements

NEXT STEPS:
1. Create upcoming_pitcher_game_context schema + processor
2. Create pitcher_daily_cache schema + processor
3. Run historical backfill
4. Create training script
```
