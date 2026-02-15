# Comprehensive Signal Testing — Next Session Prompt

**Goal:** Run exhaustive validation tests across all dimensions to achieve HIGH confidence in signal decisions

**Time estimate:** 8-12 hours (can run many queries in parallel)

**Context:** Session 256 completed initial analysis with MODERATE confidence (~20% combo coverage, ~8% segment coverage). Now run comprehensive tests across all meaningful dimensions.

---

## Background: What We Know (Session 256)

Read these files first:
1. `docs/09-handoff/2026-02-14-SESSION-256-FINAL-HANDOFF.md` — Complete analysis summary
2. `docs/08-projects/current/signal-discovery-framework/COMPREHENSIVE-SIGNAL-ANALYSIS.md` — Signal decisions
3. `docs/08-projects/current/signal-discovery-framework/TESTING-COVERAGE-ANALYSIS.md` — Gaps identified

**Key findings to validate:**
- Production combo: `high_edge + minutes_surge` (79.4% HR, 34 picks) — **needs temporal validation**
- Combo-only signals: `edge_spread_optimal` (88.2% in 3-way), `prop_value_gap_extreme` (73.7% with high_edge)
- Anti-pattern: `high_edge + edge_spread` 2-way (31.3% HR, -37.4% ROI) — **needs confirmation across segments**
- OVER bias: Both combo-only signals (+67.7% and +29.8% delta vs UNDER) — **needs validation**

**Current confidence levels:**
- HIGH (>80%): Anti-patterns, 100+ sample decisions
- MODERATE (50-80%): Production combo (34 sample), combo-only signals
- LOW (<50%): Small sample combos (N < 15), signal families

---

## Your Mission: Comprehensive Validation Testing

Run tests in 3 tiers (Tier 1 is highest priority, most likely to change decisions):

### TIER 1: CRITICAL VALIDATION (2-3 hours, run FIRST)

These tests validate the production-ready combo and could invalidate current decisions:

#### Test 1A: Temporal Robustness (30 min)

**Query all top combos across 5 evaluation windows:**

```sql
WITH tagged_picks AS (
  SELECT
    pst.signal_tags,
    pa.prediction_correct,
    pa.game_date,
    pa.model_edge,
    ppp.predicted_points - ppp.current_points_line as edge_calc
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  JOIN nba_predictions.player_prop_predictions ppp
    ON ppp.player_lookup = pa.player_lookup
    AND ppp.game_id = pa.game_id
    AND ppp.system_id = pa.system_id
  WHERE pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
),
combos AS (
  SELECT
    CASE
      WHEN game_date BETWEEN '2025-10-22' AND '2025-11-20' THEN 'W1_Early_Season'
      WHEN game_date BETWEEN '2025-11-21' AND '2025-12-20' THEN 'W2_Model_Aging'
      WHEN game_date BETWEEN '2025-12-21' AND '2026-01-20' THEN 'W3_Mid_Season'
      WHEN game_date BETWEEN '2026-01-21' AND '2026-02-20' THEN 'W4_Model_Stale'
      ELSE NULL
    END as eval_window,
    CASE
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'minutes_surge' IN UNNEST(signal_tags) THEN 'high_edge+minutes_surge'
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'prop_value_gap_extreme' IN UNNEST(signal_tags) THEN 'high_edge+prop_value'
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'minutes_surge' IN UNNEST(signal_tags) AND 'edge_spread_optimal' IN UNNEST(signal_tags) THEN '3way_combo'
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'edge_spread_optimal' IN UNNEST(signal_tags) AND NOT 'minutes_surge' IN UNNEST(signal_tags) THEN 'high_edge+edge_spread_2way'
    END as combo,
    prediction_correct,
    edge_calc
  FROM tagged_picks
)
SELECT
  eval_window,
  combo,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
  ROUND(AVG(edge_calc), 2) as avg_edge,
  ROUND(100.0 * ((COUNTIF(prediction_correct) / COUNT(*)) * 2 - 1), 1) as roi
FROM combos
WHERE eval_window IS NOT NULL AND combo IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2
```

**Decision criteria:**
- If ANY window has HR < 55% → combo is unstable, DEFER
- If HR range > 20% across windows → high variance, add temporal filter
- If early season (W1) significantly different → model needs early-season data

#### Test 1B: Home vs Away Split (20 min)

```sql
WITH tagged_picks AS (
  SELECT
    pst.signal_tags,
    pa.prediction_correct,
    pa.player_lookup,
    pa.game_id,
    ppp.predicted_points - ppp.current_points_line as edge
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  JOIN nba_predictions.player_prop_predictions ppp
    ON ppp.player_lookup = pa.player_lookup
    AND ppp.game_id = pa.game_id
  WHERE pst.game_date >= '2026-01-09'
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
),
with_location AS (
  SELECT
    tp.*,
    CASE
      WHEN pgs.team_tricode = s.home_team_tricode THEN TRUE
      WHEN pgs.team_tricode = s.away_team_tricode THEN FALSE
    END as is_home
  FROM tagged_picks tp
  LEFT JOIN nba_analytics.player_game_summary pgs
    ON pgs.player_lookup = tp.player_lookup
    AND pgs.game_id = tp.game_id
  LEFT JOIN nba_reference.nba_schedule s
    ON s.game_id = tp.game_id
),
combos AS (
  SELECT
    CASE WHEN is_home THEN 'Home' ELSE 'Away' END as location,
    CASE
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'minutes_surge' IN UNNEST(signal_tags) THEN 'high_edge+minutes_surge'
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'prop_value_gap_extreme' IN UNNEST(signal_tags) THEN 'high_edge+prop_value'
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'edge_spread_optimal' IN UNNEST(signal_tags) AND NOT 'minutes_surge' IN UNNEST(signal_tags) THEN 'high_edge+edge_spread_2way'
    END as combo,
    prediction_correct,
    edge
  FROM with_location
  WHERE is_home IS NOT NULL
)
SELECT
  location,
  combo,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
  ROUND(AVG(edge), 2) as avg_edge
FROM combos
WHERE combo IS NOT NULL
GROUP BY 1, 2
HAVING COUNT(*) >= 5
ORDER BY 2, 1
```

**Decision criteria:**
- If delta > 15% → add location filter
- If home significantly better → recommend "high_edge+minutes_surge (home only)"

#### Test 1C: Model Staleness Effect (20 min)

```sql
-- Champion model trained through 2026-01-08
WITH tagged_picks AS (
  SELECT
    pst.signal_tags,
    pa.prediction_correct,
    pa.game_date,
    DATE_DIFF(pa.game_date, DATE '2026-01-08', DAY) as days_since_training,
    ppp.predicted_points - ppp.current_points_line as edge
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  JOIN nba_predictions.player_prop_predictions ppp
    ON ppp.player_lookup = pa.player_lookup
    AND ppp.game_id = pa.game_id
  WHERE pst.game_date >= '2026-01-09'
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
),
combos AS (
  SELECT
    CASE
      WHEN days_since_training <= 7 THEN 'Fresh (<7d)'
      WHEN days_since_training <= 14 THEN 'Recent (7-14d)'
      WHEN days_since_training <= 21 THEN 'Aging (14-21d)'
      WHEN days_since_training <= 28 THEN 'Stale (21-28d)'
      ELSE 'Very Stale (28+d)'
    END as model_age,
    CASE
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'minutes_surge' IN UNNEST(signal_tags) THEN 'high_edge+minutes_surge'
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'prop_value_gap_extreme' IN UNNEST(signal_tags) THEN 'high_edge+prop_value'
      WHEN 'cold_snap' IN UNNEST(signal_tags) THEN 'cold_snap'
      WHEN 'blowout_recovery' IN UNNEST(signal_tags) THEN 'blowout_recovery'
    END as combo,
    prediction_correct
  FROM tagged_picks
)
SELECT
  model_age,
  combo,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combos
WHERE combo IS NOT NULL
GROUP BY 1, 2
HAVING COUNT(*) >= 5
ORDER BY 2, 1
```

**Decision criteria:**
- If HR drops >15% at "Very Stale" → model_health gate is critical
- If player-behavior signals (cold_snap, blowout_recovery) stable → confirms decay resistance

#### Test 1D: Position Split (20 min)

```sql
WITH tagged_picks AS (
  SELECT
    pst.signal_tags,
    pa.prediction_correct,
    pa.player_lookup,
    ppp.predicted_points - ppp.current_points_line as edge
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  JOIN nba_predictions.player_prop_predictions ppp
    ON ppp.player_lookup = pa.player_lookup
    AND ppp.game_id = pa.game_id
  WHERE pst.game_date >= '2026-01-09'
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
),
with_position AS (
  SELECT
    tp.*,
    pi.position
  FROM tagged_picks tp
  LEFT JOIN nba_reference.player_info pi
    ON pi.player_lookup = tp.player_lookup
),
combos AS (
  SELECT
    CASE
      WHEN position IN ('PG', 'SG') THEN 'Guards'
      WHEN position IN ('SF', 'PF') THEN 'Forwards'
      WHEN position = 'C' THEN 'Centers'
      ELSE 'Unknown'
    END as position_group,
    CASE
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'minutes_surge' IN UNNEST(signal_tags) THEN 'high_edge+minutes_surge'
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'prop_value_gap_extreme' IN UNNEST(signal_tags) THEN 'high_edge+prop_value'
      WHEN '3pt_bounce' IN UNNEST(signal_tags) THEN '3pt_bounce'
    END as combo,
    prediction_correct
  FROM with_position
)
SELECT
  position_group,
  combo,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combos
WHERE combo IS NOT NULL AND position_group != 'Unknown'
GROUP BY 1, 2
HAVING COUNT(*) >= 5
ORDER BY 2, 1
```

**Decision criteria:**
- If guards significantly different from forwards/centers → add position filter
- If 3pt_bounce only works for guards → expected (shooting signal)

---

### TIER 2: COMPREHENSIVE COMBO TESTING (4-6 hours)

#### Test 2A: Systematic 3-Way Combos (3-4 hours)

Test all 35 possible 3-way combinations for 7 signals:

```python
from itertools import combinations

signals = ['high_edge', 'minutes_surge', '3pt_bounce', 'blowout_recovery',
           'cold_snap', 'edge_spread_optimal', 'prop_value_gap_extreme']

query_template = """
WITH tagged_picks AS (
  SELECT
    pst.signal_tags,
    pa.prediction_correct,
    ppp.predicted_points - ppp.current_points_line as edge
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  JOIN nba_predictions.player_prop_predictions ppp
    ON ppp.player_lookup = pa.player_lookup
    AND ppp.game_id = pa.game_id
  WHERE pst.game_date >= '2026-01-09'
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
)
SELECT
  '{s1}+{s2}+{s3}' as combo,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
  ROUND(AVG(edge), 2) as avg_edge,
  ROUND(100.0 * ((COUNTIF(prediction_correct) / COUNT(*)) * 2 - 1), 1) as roi
FROM tagged_picks
WHERE '{s1}' IN UNNEST(signal_tags)
  AND '{s2}' IN UNNEST(signal_tags)
  AND '{s3}' IN UNNEST(signal_tags)
HAVING COUNT(*) >= 5
"""

results = []
for s1, s2, s3 in combinations(signals, 3):
    query = query_template.format(s1=s1, s2=s2, s3=s3)
    # Run query via bq
    # Append to results

# Output top 10 3-way combos by HR
```

**Decision criteria:**
- If new 3-way combo > 80% HR with N >= 15 → production candidate
- If multiple strong 3-way combos → identify common signals (universal connectors)

#### Test 2B: Rest and Back-to-Back Analysis (1-2 hours)

```sql
WITH tagged_picks AS (
  SELECT
    pst.signal_tags,
    pa.prediction_correct,
    pa.player_lookup,
    pa.game_id,
    pa.game_date
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  WHERE pst.game_date >= '2026-01-09'
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
),
with_rest AS (
  SELECT
    tp.*,
    DATE_DIFF(tp.game_date, LAG(pgs.game_date) OVER (PARTITION BY tp.player_lookup ORDER BY pgs.game_date), DAY) as rest_days
  FROM tagged_picks tp
  LEFT JOIN nba_analytics.player_game_summary pgs
    ON pgs.player_lookup = tp.player_lookup
    AND pgs.game_date <= tp.game_date
),
combos AS (
  SELECT
    CASE
      WHEN rest_days = 0 THEN 'Back-to-Back (0d)'
      WHEN rest_days = 1 THEN 'Standard (1d)'
      WHEN rest_days = 2 THEN 'Extra Rest (2d)'
      WHEN rest_days >= 3 THEN 'Long Rest (3+d)'
    END as rest_category,
    CASE
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'minutes_surge' IN UNNEST(signal_tags) THEN 'high_edge+minutes_surge'
      WHEN 'blowout_recovery' IN UNNEST(signal_tags) THEN 'blowout_recovery'
      WHEN 'b2b_fatigue_under' IN UNNEST(signal_tags) THEN 'b2b_fatigue_under'
    END as combo,
    prediction_correct
  FROM with_rest
  WHERE rest_days IS NOT NULL
)
SELECT
  rest_category,
  combo,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combos
WHERE combo IS NOT NULL
GROUP BY 1, 2
HAVING COUNT(*) >= 5
ORDER BY 2, 1
```

**Decision criteria:**
- If B2B (0d rest) HR delta > 15% → critical filter
- If `b2b_fatigue_under` performs well on B2B games → salvageable prototype

#### Test 2C: Team Strength Analysis (1 hour)

```sql
WITH team_standings AS (
  SELECT
    team_tricode,
    SUM(CASE WHEN game_status = 3 AND winning_team = team_tricode THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN game_status = 3 THEN 1 ELSE 0 END) as games,
    SAFE_DIVIDE(
      SUM(CASE WHEN game_status = 3 AND winning_team = team_tricode THEN 1 ELSE 0 END),
      SUM(CASE WHEN game_status = 3 THEN 1 ELSE 0 END)
    ) as win_pct
  FROM nba_reference.nba_schedule
  WHERE game_date < '2026-01-09'
  GROUP BY 1
),
team_tiers AS (
  SELECT
    team_tricode,
    win_pct,
    NTILE(3) OVER (ORDER BY win_pct DESC) as tier
  FROM team_standings
),
tagged_picks AS (
  SELECT
    pst.signal_tags,
    pa.prediction_correct,
    pa.player_lookup,
    pa.game_id
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  WHERE pst.game_date >= '2026-01-09'
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
),
with_team_tier AS (
  SELECT
    tp.*,
    tt.tier
  FROM tagged_picks tp
  LEFT JOIN nba_analytics.player_game_summary pgs
    ON pgs.player_lookup = tp.player_lookup
    AND pgs.game_id = tp.game_id
  LEFT JOIN team_tiers tt
    ON tt.team_tricode = pgs.team_tricode
),
combos AS (
  SELECT
    CASE
      WHEN tier = 1 THEN 'Top Teams (Tier 1)'
      WHEN tier = 2 THEN 'Middle Teams (Tier 2)'
      WHEN tier = 3 THEN 'Bottom Teams (Tier 3)'
    END as team_strength,
    CASE
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'minutes_surge' IN UNNEST(signal_tags) THEN 'high_edge+minutes_surge'
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'prop_value_gap_extreme' IN UNNEST(signal_tags) THEN 'high_edge+prop_value'
    END as combo,
    prediction_correct
  FROM with_team_tier
  WHERE tier IS NOT NULL
)
SELECT
  team_strength,
  combo,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combos
WHERE combo IS NOT NULL
GROUP BY 1, 2
HAVING COUNT(*) >= 5
ORDER BY 2, 1
```

**Decision criteria:**
- If top teams significantly different → add team strength filter
- If bottom teams higher HR → value in inefficient markets

---

### TIER 3: ADVANCED SEGMENTATION (2-3 hours)

#### Test 3A: Prop Type Analysis (1 hour)

```sql
WITH tagged_picks AS (
  SELECT
    pst.signal_tags,
    pa.prediction_correct,
    pa.prop_type
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  WHERE pst.game_date >= '2026-01-09'
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
),
combos AS (
  SELECT
    prop_type,
    CASE
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'minutes_surge' IN UNNEST(signal_tags) THEN 'high_edge+minutes_surge'
      WHEN '3pt_bounce' IN UNNEST(signal_tags) THEN '3pt_bounce'
      WHEN 'prop_value_gap_extreme' IN UNNEST(signal_tags) THEN 'prop_value_gap_extreme'
    END as combo,
    prediction_correct
  FROM tagged_picks
)
SELECT
  prop_type,
  combo,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combos
WHERE combo IS NOT NULL
GROUP BY 1, 2
HAVING COUNT(*) >= 5
ORDER BY 2, 1
```

**Decision criteria:**
- If points props perform differently than rebounds/assists → segment by prop type
- If 3pt_bounce only works for 3PT props → expected

#### Test 3B: Conference Split (30 min)

```sql
-- Test if combos work differently in East vs West conferences
WITH tagged_picks AS (
  SELECT
    pst.signal_tags,
    pa.prediction_correct,
    pa.player_lookup,
    pa.game_id
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  WHERE pst.game_date >= '2026-01-09'
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
),
with_conference AS (
  SELECT
    tp.*,
    ti.conference
  FROM tagged_picks tp
  LEFT JOIN nba_analytics.player_game_summary pgs
    ON pgs.player_lookup = tp.player_lookup
    AND pgs.game_id = tp.game_id
  LEFT JOIN nba_reference.team_info ti
    ON ti.team_tricode = pgs.team_tricode
),
combos AS (
  SELECT
    conference,
    CASE
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'minutes_surge' IN UNNEST(signal_tags) THEN 'high_edge+minutes_surge'
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'prop_value_gap_extreme' IN UNNEST(signal_tags) THEN 'high_edge+prop_value'
    END as combo,
    prediction_correct
  FROM with_conference
)
SELECT
  conference,
  combo,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combos
WHERE combo IS NOT NULL AND conference IS NOT NULL
GROUP BY 1, 2
HAVING COUNT(*) >= 5
ORDER BY 2, 1
```

#### Test 3C: Divisional Games (30 min)

```sql
-- Test if combos perform differently in divisional matchups
WITH tagged_picks AS (
  SELECT
    pst.signal_tags,
    pa.prediction_correct,
    pa.game_id
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  WHERE pst.game_date >= '2026-01-09'
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
),
with_divisional AS (
  SELECT
    tp.*,
    CASE
      WHEN ht.division = at.division THEN 'Divisional'
      WHEN ht.conference = at.conference THEN 'Conference'
      ELSE 'Cross-Conference'
    END as matchup_type
  FROM tagged_picks tp
  JOIN nba_reference.nba_schedule s ON s.game_id = tp.game_id
  LEFT JOIN nba_reference.team_info ht ON ht.team_tricode = s.home_team_tricode
  LEFT JOIN nba_reference.team_info at ON at.team_tricode = s.away_team_tricode
),
combos AS (
  SELECT
    matchup_type,
    CASE
      WHEN 'high_edge' IN UNNEST(signal_tags) AND 'minutes_surge' IN UNNEST(signal_tags) THEN 'high_edge+minutes_surge'
    END as combo,
    prediction_correct
  FROM with_divisional
)
SELECT
  matchup_type,
  combo,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combos
WHERE combo IS NOT NULL
GROUP BY 1, 2
HAVING COUNT(*) >= 5
ORDER BY 2, 1
```

---

## Deliverables for This Session

### 1. Comprehensive Testing Results Document

Create: `docs/08-projects/current/signal-discovery-framework/COMPREHENSIVE-TESTING-RESULTS.md`

**Structure:**
- Executive summary (confidence levels after testing)
- Tier 1 results (temporal, home/away, staleness, position)
- Tier 2 results (3-way combos, rest/B2B, team strength)
- Tier 3 results (prop type, conference, divisional)
- Updated signal decisions (any changes from Session 256)
- Production deployment recommendations

### 2. Signal Decision Matrix

Create: `docs/08-projects/current/signal-discovery-framework/SIGNAL-DECISION-MATRIX.md`

**Format:**

| Signal/Combo | Standalone HR | Best Combo HR | Temporal Stable? | Home/Away Delta | Position Effect | Rest Effect | Final Decision | Confidence |
|--------------|---------------|---------------|------------------|-----------------|-----------------|-------------|----------------|------------|
| high_edge+minutes_surge | 48.2% / 43.8% | 79.4% | ✅ / ❌ / ⚠️ | +X% home | Guards +Y% | B2B -Z% | PRODUCTION | HIGH / MED |
| ... | ... | ... | ... | ... | ... | ... | ... | ... |

### 3. Conditional Deployment Guide

Create: `docs/08-projects/current/signal-discovery-framework/CONDITIONAL-DEPLOYMENT-GUIDE.md`

**Example:**

```python
# Production deployment with conditional filters based on testing

class HighEdgeMinutesSurgeComboSignal(BaseSignal):
    tag = "high_edge_minutes_surge_combo"

    def evaluate(self, prediction: Dict, features: Dict, supplemental: Dict) -> SignalResult:
        # Base qualification
        if 'high_edge' not in prediction.tags or 'minutes_surge' not in prediction.tags:
            return self._no_qualify()

        # Conditional filters based on comprehensive testing

        # If home/away matters (Tier 1 Test 1B)
        if supplemental.get('is_home') == False:
            confidence_penalty = 0.1  # Away games perform 15% worse

        # If position matters (Tier 1 Test 1D)
        if supplemental.get('position') in ['PG', 'SG']:
            confidence_boost = 0.05  # Guards perform 10% better

        # If model staleness matters (Tier 1 Test 1C)
        if supplemental.get('days_since_training') > 28:
            return self._no_qualify()  # Don't fire when model very stale

        # If rest matters (Tier 2 Test 2B)
        if supplemental.get('rest_days') == 0:
            confidence_penalty = 0.15  # B2B games perform 20% worse

        return SignalResult(
            qualifies=True,
            confidence=0.85 - confidence_penalty + confidence_boost,
            source_tag=self.tag
        )
```

### 4. Testing Coverage Summary

Update: `docs/08-projects/current/signal-discovery-framework/TESTING-COVERAGE-ANALYSIS.md`

Add section: "Session 257 Comprehensive Testing"
- What was tested in this session
- Coverage achieved (X% of combos, Y% of segments)
- Remaining gaps (if any)
- Confidence levels achieved

---

## Expected Outcomes

### Best Case
- **HIGH confidence (>80%)** on production combo across all dimensions
- Discover 2-3 additional strong combos (HR > 75%, N >= 20)
- Identify critical filters (home vs away, rest, position) that boost HR +10-15%
- Validate anti-patterns hold across all segments

### Moderate Case
- **MODERATE confidence (60-80%)** on production combo (some segments weak)
- Discover 1-2 additional combos worth monitoring
- Identify some useful filters but not game-changing
- Anti-patterns confirmed

### Worst Case
- Production combo fails temporal validation (HR < 60% in some windows) → DEFER
- No new strong combos discovered
- Filters don't significantly improve performance
- Need to go back to drawing board

---

## Time Allocation

**Total: 8-12 hours**

- Tier 1 (critical): 2-3 hours
- Tier 2 (comprehensive): 4-6 hours
- Tier 3 (advanced): 2-3 hours
- Documentation: 1-2 hours

**Parallel execution:** Many queries can run simultaneously. Spawn multiple Task agents to maximize throughput.

---

## Success Criteria

Session is successful if:
- ✅ Tier 1 tests complete (all 4 critical dimensions)
- ✅ Production combo validated or invalidated with HIGH confidence
- ✅ Comprehensive testing results documented
- ✅ Signal decision matrix complete
- ✅ Conditional deployment guide created
- ✅ Updated confidence levels for all signal decisions

---

## Starting Point

1. Read Session 256 handoff: `docs/09-handoff/2026-02-14-SESSION-256-FINAL-HANDOFF.md`
2. Read testing coverage gaps: `docs/08-projects/current/signal-discovery-framework/TESTING-COVERAGE-ANALYSIS.md`
3. Run Tier 1 tests FIRST (highest priority)
4. Based on Tier 1 results, decide whether to proceed with Tier 2-3
5. Document all findings comprehensively

**Let's achieve HIGH confidence through exhaustive testing! 🚀**
