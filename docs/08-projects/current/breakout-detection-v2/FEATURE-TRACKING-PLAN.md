# Breakout Detection v2 - Feature Tracking Plan

**Status:** Data Collection Phase
**Started:** 2026-02-05 (Session 127)
**Next Review:** 2026-02-26 (3 weeks)

---

## What Was Deployed (2026-02-05)

### Features 37-38 Infrastructure ✅
- **Feature 37:** `breakout_risk_score` (0-100) - Composite breakout probability
- **Feature 38:** `composite_breakout_signal` (0-5) - Simple factor count

**Deployed Services:**
- ✅ nba-phase4-precompute-processors (6b52f0d9) - Calculates features 37-38
- ✅ nba-phase3-analytics-processors (6b52f0d9) - Dependency
- ✅ prediction-worker (eb7ce85b) - Uses feature store
- ✅ prediction-coordinator (eb7ce85b) - Orchestrates predictions

**What's Generating:**
- Breakout risk calculator with 6 components:
  - Hot streak (15%)
  - Cold streak bonus (10%)
  - **Volatility/CV ratio (25%)** - strongest predictor
  - Opponent defense (20%)
  - Opportunity (15%) - includes placeholder injured_teammates_ppg
  - Historical breakout rate (10%)

---

## Current State

### Historical Data (Before Feb 5, 2026)
```sql
-- All historical records have 37 features (0-36)
SELECT COUNT(*) as records_with_37_features
FROM nba_predictions.ml_feature_store_v2
WHERE game_date < '2026-02-05'
  AND ARRAY_LENGTH(features) = 37;
-- Result: ~24,000 records
```

**Features 37-38:** NULL for all historical data

### New Data (Feb 5, 2026 onwards)
```sql
-- New records should have 39 features (0-38)
SELECT
  game_date,
  COUNT(*) as records,
  AVG(ARRAY_LENGTH(features)) as avg_feature_count,
  ROUND(AVG(features[OFFSET(37)]), 1) as avg_breakout_risk,
  ROUND(AVG(features[OFFSET(38)]), 1) as avg_composite_signal
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-02-05'
GROUP BY game_date
ORDER BY game_date;
```

**Expected:**
- ~200-300 records/day (all players in games)
- Feature count = 39
- breakout_risk_score: 0-100
- composite_breakout_signal: 0-5

---

## Monitoring Schedule

### Daily Checks (First Week: Feb 5-11)
**Purpose:** Verify features are generating correctly

```sql
-- Quick daily verification
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(ARRAY_LENGTH(features) = 39) as records_with_39_features,
  COUNTIF(features[OFFSET(37)] IS NOT NULL) as breakout_risk_populated,
  COUNTIF(features[OFFSET(38)] IS NOT NULL) as composite_signal_populated,
  ROUND(AVG(features[OFFSET(37)]), 1) as avg_risk,
  ROUND(AVG(features[OFFSET(38)]), 1) as avg_signal
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-02-05'
GROUP BY game_date
ORDER BY game_date DESC;
```

**Success Criteria:**
- ✅ All records have 39 features
- ✅ Features 37-38 are NOT NULL
- ✅ breakout_risk_score: 0-100 range
- ✅ composite_breakout_signal: 0-5 range

### Weekly Checks (Weeks 2-3: Feb 12-26)
**Purpose:** Track data accumulation for classifier training

```sql
-- Weekly data accumulation check
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_date) as days_collected,
  COUNT(DISTINCT player_lookup) as unique_players,
  -- Role player focus (8-16 PPG)
  COUNTIF(features[OFFSET(2)] BETWEEN 8 AND 16) as role_player_records,
  -- Breakout distribution
  COUNTIF(features[OFFSET(37)] >= 60) as high_risk_records,
  COUNTIF(features[OFFSET(38)] >= 4) as strong_signal_records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-02-05';
```

**Training Readiness:**
- Need: 2,000+ role player records (8-16 PPG)
- Need: 15+ days of data (reduces recency bias)
- Expected: ~3,000-4,500 total records after 3 weeks

---

## Key Metrics to Track

### 1. Feature Coverage
- **Metric:** % of records with 39 features
- **Target:** 100%
- **Check:** Daily (first week), then weekly

### 2. Feature Quality
- **Metric:** breakout_risk_score range (0-100), composite_signal range (0-5)
- **Target:** No values outside expected ranges
- **Check:** Daily (first week)

### 3. Role Player Representation
- **Metric:** Records for players with 8-16 season PPG
- **Target:** 2,000+ records before training
- **Check:** Weekly

### 4. Breakout Signal Distribution
- **Metric:** Distribution of high-risk scores (60+) and strong signals (4+)
- **Target:** Should see ~20-30% high risk based on Session 126 findings
- **Check:** Weekly

---

## Decision Gates

### Gate 1: Week 1 Verification (Feb 12)
**Question:** Are features generating correctly?

**Checks:**
- [ ] All records have 39 features
- [ ] Features 37-38 are populated (not NULL)
- [ ] Values are in expected ranges
- [ ] No errors in Phase 4 logs

**If PASS:** Continue collecting
**If FAIL:** Debug and fix feature generation

### Gate 2: Week 3 Readiness (Feb 26)
**Question:** Do we have enough data to train classifier?

**Checks:**
- [ ] 2,000+ role player records (8-16 PPG)
- [ ] 15+ days of data collected
- [ ] Feature quality looks good
- [ ] No systematic issues detected

**If PASS:** Proceed to classifier training
**If FAIL:** Collect 1-2 more weeks

---

## Next Steps (After 3 Weeks)

### 1. Define Role Player Criteria (P3)
**Decision needed:** How to filter training data?
- **Option A (Recommended):** Season PPG 8-16 on final training date
- **Option B:** Per-game rolling PPG
- **Option C:** Minutes played (15-28 min)
- **Option D:** Hybrid (PPG + minutes)

### 2. Train Breakout Classifier (P4)
```bash
# After collecting 3 weeks of data
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
    --name "BREAKOUT_V1" \
    --train-start 2026-02-05 \
    --train-end 2026-02-26 \
    --eval-start 2026-02-27 \
    --eval-end 2026-03-05
```

**Target:** AUC >= 0.65 (predicting role player breakout games)

### 3. Shadow Mode Validation (P5)
- Collect 100+ samples per filter category
- Verify hit rates before enabling production filters
- Compare to baseline (no breakout filtering)

### 4. Production Enablement (If Validated)
- Enable breakout-based filters in prediction worker
- Monitor impact on hit rate and ROI
- Document performance in production

---

## Immediate Priorities (While Data Collects)

### ✅ P1: Implement Real injured_teammates_ppg (COMPLETED - Session 127)
**Status:** ✅ Implemented and committed (58b3c217)
**Impact:** 30+ PPG injured → 24.5% breakout rate vs 16.2% baseline
**Files:**
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:1790` - Added `_get_injured_teammates_ppg()`
- `data_processors/precompute/ml_feature_store/breakout_risk_calculator.py:454` - Uses team_context

**Implementation:**
```python
def _get_injured_teammates_ppg(self, team_abbr: str, game_date: date) -> float:
    """
    Calculate total PPG of injured teammates (OUT/QUESTIONABLE/DOUBTFUL).

    Queries bdl_injuries for latest injury status, joins with feature store
    for season PPG, returns sum of injured teammates' scoring.
    """
```

**Data Source:** `nba_raw.bdl_injuries` (Ball Don't Lie injuries)
**Injury Statuses:** 'out', 'questionable', 'doubtful' (lowercase)
**PPG Source:** `nba_predictions.ml_feature_store_v2` features[2] (season PPG)

**Example Results (2026-02-05):**
- OKC: 110.1 PPG injured (Shai 31.8, Chet 17.7, Jalen Williams 17.1)
- BOS: 83.5 PPG injured (Jaylen Brown 28.9)
- MIN: 55.9 PPG injured (Anthony Edwards 29.3, Julius Randle 22.2)

**Next:** Deploy phase4 service to activate in production

### P2: Monitor Feature Generation
- Daily checks (first week)
- Weekly checks (ongoing)
- Fix any issues quickly

### P3: Document Findings
- Update design doc with feature performance
- Track any unexpected patterns
- Note data quality issues

---

## Verification Queries

### Daily: Feature Generation Check
```sql
-- Run daily for first week
SELECT
  'Today' as period,
  COUNT(*) as records,
  COUNTIF(ARRAY_LENGTH(features) = 39) as has_39_features,
  ROUND(100.0 * COUNTIF(ARRAY_LENGTH(features) = 39) / COUNT(*), 1) as pct_complete,
  ROUND(AVG(features[OFFSET(37)]), 1) as avg_breakout_risk,
  ROUND(AVG(features[OFFSET(38)]), 1) as avg_composite_signal
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE() - 1;  -- Yesterday's games
```

### Weekly: Data Accumulation Check
```sql
-- Run weekly
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_date) as days_collected,
  COUNT(DISTINCT player_lookup) as unique_players,
  ROUND(AVG(features[OFFSET(2)]), 1) as avg_season_ppg,
  -- Role players (8-16 PPG)
  COUNTIF(features[OFFSET(2)] BETWEEN 8 AND 16) as role_player_records,
  -- High risk distribution
  COUNTIF(features[OFFSET(37)] >= 60) as high_risk_count,
  ROUND(100.0 * COUNTIF(features[OFFSET(37)] >= 60) / COUNT(*), 1) as pct_high_risk
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-02-05';
```

### Training Readiness Check (Week 3)
```sql
-- Run before training classifier
WITH role_players AS (
  SELECT
    player_lookup,
    game_date,
    features[OFFSET(2)] as season_ppg,
    features[OFFSET(37)] as breakout_risk,
    features[OFFSET(38)] as composite_signal
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= '2026-02-05'
    AND features[OFFSET(2)] BETWEEN 8 AND 16  -- Role players
)
SELECT
  COUNT(*) as total_role_player_records,
  COUNT(DISTINCT game_date) as days_covered,
  COUNT(DISTINCT player_lookup) as unique_role_players,
  ROUND(AVG(season_ppg), 1) as avg_ppg,
  ROUND(AVG(breakout_risk), 1) as avg_risk,
  -- Distribution
  COUNTIF(breakout_risk >= 60) as high_risk,
  COUNTIF(composite_signal >= 4) as strong_signal,
  -- Readiness
  CASE
    WHEN COUNT(*) >= 2000 AND COUNT(DISTINCT game_date) >= 15
    THEN '✅ READY FOR TRAINING'
    ELSE '❌ NEED MORE DATA'
  END as training_status
FROM role_players;
```

---

## Known Issues / Placeholders

### 1. ~~injured_teammates_ppg~~ ✅ FIXED (Session 127)
**Status:** ✅ Implemented and committed (58b3c217)
**Impact:** Now properly accounts for injury opportunities in breakout risk
**Deployed:** ⏳ Pending deployment (commit 58b3c217 not yet deployed)

### 2. Role Player Definition (P3 - Decide Before Training)
**Status:** Not yet defined
**Impact:** Need clear criteria for classifier training filter
**Options:** See "Define Role Player Criteria" section above

---

## Success Metrics (Post-Implementation)

Once classifier is trained and validated:

### Shadow Mode Targets
- 100+ samples per filter category
- Breakout-flagged OVERs: Hit rate >= 60%
- Non-breakout OVERs: Baseline comparison
- ROI improvement: +5% or more

### Production Targets (If Enabled)
- Overall hit rate: Maintain or improve (currently 54.7%)
- Medium quality (3+ edge): Maintain 65%+ hit rate
- High quality (5+ edge): Maintain 79%+ hit rate
- Breakout-enhanced picks: 60%+ hit rate

---

## Timeline

| Date | Milestone | Status |
|------|-----------|--------|
| 2026-02-05 | Deploy features 37-38 infrastructure | ✅ Done |
| 2026-02-05 | Implement real injured_teammates_ppg | ✅ Done (Session 127) |
| 2026-02-06 | Deploy injured_teammates_ppg fix | ⏳ Pending |
| 2026-02-12 | Week 1 verification gate | 🔄 Pending |
| 2026-02-19 | Week 2 data check | 🔄 Pending |
| 2026-02-26 | Week 3 training readiness gate | 🔄 Pending |
| 2026-03-05 | Train classifier (if ready) | ⏳ Future |
| 2026-03-12 | Shadow mode validation | ⏳ Future |
| 2026-03-19 | Production decision | ⏳ Future |

---

## References

- **Design Doc:** `docs/08-projects/current/breakout-detection-v2/BREAKOUT-DETECTION-V2-DESIGN.md`
- **Session 126 Handoff:** `docs/09-handoff/2026-02-04-SESSION-126-HANDOFF.md`
- **Session 127 Start:** `docs/09-handoff/2026-02-05-SESSION-127-BREAKOUT-START.md`
- **Risk Calculator:** `data_processors/precompute/ml_feature_store/breakout_risk_calculator.py:21`
- **Feature Store:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:1`
- **Feature Contract:** `shared/ml/feature_contract.py:1`

---

*Last Updated: 2026-02-05 (Session 127)*
