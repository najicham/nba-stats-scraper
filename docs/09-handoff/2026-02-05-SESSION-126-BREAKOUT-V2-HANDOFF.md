# Session 126 Handoff - Breakout Detection v2

**Date:** 2026-02-05
**Duration:** ~2 hours
**Status:** Core implementation complete, one task remaining

---

## Quick Start for Next Session

```bash
# 1. Check deployment status (Session 125B filters are deployed)
./bin/check-deployment-drift.sh --verbose

# 2. Deploy Phase 4 if needed (has new features)
./bin/deploy-service.sh nba-phase4-precompute-processors

# 3. Remaining task: Implement real injured_teammates_ppg
# See Task #11 section below
```

---

## What Was Done

### 1. Deployed Session 125B Filters (P1)
All 3 breakout filters from Session 125B are now live:
- `role_player_under_low_edge`: Skip role player UNDER when edge < 5
- `hot_streak_under_risk`: Skip UNDER when L5 > season + 3 (14% hit rate!)
- `low_data_quality`: Skip when quality_score < 80

### 2. Opus Agent Research (3 Agents)
Spawned 3 Opus agents to comprehensively analyze breakout detection:

**Agent 1 - Implementation Review:**
- Identified critical gap: breakout_risk_score NOT integrated
- Sample sizes are small (7-14 predictions)
- Opportunity component uses placeholder data

**Agent 2 - Additional Strategies:**
- Injured teammates 30+ PPG: +8% breakout rate (24.5% vs 16.2%)
- Usage trend (rising): +7% breakout rate (23.5% vs 16.1%)
- Minutes opportunity: +33% for extra 5-10 min (retrospective)

**Agent 3 - Historical Patterns:**
- CV Ratio: STRONGEST signal (+0.198 correlation)
- Cold players break out MORE: 27.1% vs 17.2% (mean reversion!)
- Composite score 4+: 37% breakout rate (2x baseline)

### 3. Breakout Detection v2 Implementation

**New features added to ML feature store (v2_39features):**

| Feature # | Name | Description |
|-----------|------|-------------|
| 37 | breakout_risk_score | 0-100 composite score (now integrated) |
| 38 | composite_breakout_signal | 0-5 factor count |

**Enhanced breakout_risk_calculator.py:**

| Component | Old Weight | New Weight | Change |
|-----------|------------|------------|--------|
| Hot Streak | 30% | 15% | Reduced (less important than thought) |
| Cold Streak Bonus | 0% | 10% | NEW - mean reversion signal |
| Volatility (CV ratio) | 20% | 25% | Enhanced with CV ratio |
| Opponent Defense | 20% | 20% | Unchanged |
| Opportunity | 15% | 15% | Enhanced with usage trend |
| Historical | 15% | 15% | Unchanged |

**Composite Breakout Signal (0-5):**
- +1 High variance (CV >= 60%)
- +1 Cold streak (L5 20%+ below L10)
- +1 Starter status
- +1 Home game
- +1 Rested (<=2 games in 7 days)

Historical performance:
- Score 5: 57.1% breakout rate
- Score 4: 37.4% breakout rate
- Score 3: 29.6% breakout rate

---

## Files Changed

| File | Changes |
|------|---------|
| `breakout_risk_calculator.py` | +CV ratio, +cold streak bonus, +usage trend, +composite signal |
| `ml_feature_store_processor.py` | Integrated features 37-38 |
| `feature_contract.py` | Updated to v2_39features |
| `test_breakout_risk_calculator.py` | Updated tests for new components |
| `docs/.../BREAKOUT-DETECTION-V2-DESIGN.md` | Design document |

---

## Commits

```
5a7e3431 - feat: Add breakout detection v2 with CV ratio, usage trend, and composite signal (Session 126)
```

---

## Remaining Task (#11)

### Implement Real injured_teammates_ppg

**Current state:** The opportunity component uses a placeholder value (20.0) because team injury context isn't passed to the calculator.

**To implement:**

1. **Update feature_extractor.py** to fetch injury data:
```sql
SELECT
    ir.team_abbr,
    ir.game_date,
    SUM(COALESCE(pdc.points_avg_season, 10.0)) as injured_teammates_ppg
FROM nba_raw.nbac_injury_report ir
LEFT JOIN nba_precompute.player_daily_cache pdc
    ON ir.player_lookup = pdc.player_lookup
    AND ir.game_date = pdc.cache_date + 1
WHERE ir.injury_status = 'Out'
GROUP BY ir.team_abbr, ir.game_date
```

2. **Pass team_context** to breakout_risk_calculator:
```python
team_context = {
    'injured_teammates_ppg': injury_data.get(team_abbr, 0.0)
}
```

3. **Test with historical data** to validate the +8% signal

**Expected Impact:**
- When 30+ PPG injured: 24.5% breakout rate (vs 16.2% baseline)
- 51% increase in breakout probability

---

## Deployments Needed

After implementing #11:
```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

---

## Key Insights from Opus Agents

### Counter-Intuitive Findings

1. **Cold players break out MORE than hot players**
   - Mean reversion is real in NBA scoring
   - Cold streak (L5 20%+ below L10): 27.1% breakout rate
   - Hot streak (L5 20%+ above L10): 21.7% breakout rate

2. **CV ratio is the strongest predictor**
   - High variance (CV 60%+): 29.5% breakout rate
   - Very consistent (CV <25%): 9.0% breakout rate
   - 3.3x difference!

3. **Simple composite outperforms complex models**
   - 5 binary factors → 37% breakout rate at 4+ factors
   - Easier to explain and debug than ML model

### Validation Recommendations

- Run new features in shadow mode for 2-4 weeks
- Accumulate 100+ samples per filter category
- Make thresholds configurable via env vars

---

## Documentation

- **Design doc:** `docs/08-projects/current/breakout-detection-v2/BREAKOUT-DETECTION-V2-DESIGN.md`
- **Session 125B handoff:** `docs/09-handoff/2026-02-05-SESSION-125B-BREAKOUT-DETECTION-HANDOFF.md`

---

*Session 126 - Breakout Detection v2 Enhancement*
