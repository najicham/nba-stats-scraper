# Subset Pick System Architecture
## Layered Filtering Strategy for Prediction Systems
**Date**: 2026-01-16
**Session**: 75
**Status**: 📐 DESIGN DOCUMENT - Ready for Implementation

---

## Philosophy: Foundation vs Layers

### Current Problem
- Systems generate all predictions (good and bad mixed together)
- Filtering decisions are unclear (in code? in queries? in UI?)
- Hard to A/B test different filtering strategies
- Can't track subset performance independently

### Proposed Solution: Clean Separation

```
┌──────────────────────────────────────────────────┐
│  LAYER 1: FOUNDATION (Prediction Generation)     │
│  ────────────────────────────────────────────    │
│  • catboost_v8: Generate ALL picks              │
│  • xgboost_v1: Generate ALL picks               │
│  • other systems: Generate ALL picks            │
│                                                  │
│  Purpose: Pure model output                      │
│  Filtering: Minimal (confidence ≥ 60%)          │
│  Storage: nba_predictions.player_prop_predictions│
│  Code Changes: NEVER (stable foundation)        │
└──────────────────────────────────────────────────┘
              │
              │ Materialized in BigQuery
              ▼
┌──────────────────────────────────────────────────┐
│  LAYER 2: SUBSETS (Pick Selection/Curation)      │
│  ────────────────────────────────────────────    │
│  Virtual Systems (query-based):                  │
│                                                  │
│  • catboost_v8_premium (conf ≥ 92%)            │
│  • catboost_v8_quality (conf 86-92%, exclude gaps)│
│  • xgboost_v1_elite_unders (UNDER + conf ≥ 90%) │
│  • ensemble_consensus (3+ systems agree)        │
│  • high_volume_players (avg ≥ 20 pts/game)     │
│  • contrarian_picks (against public)           │
│                                                  │
│  Purpose: Curated pick sets for different strategies│
│  Filtering: Complex, multi-factor              │
│  Storage: nba_predictions.prediction_subsets   │
│  Code Changes: FREQUENT (rapid iteration)      │
└──────────────────────────────────────────────────┘
              │
              │ Exposed via API/UI
              ▼
┌──────────────────────────────────────────────────┐
│  LAYER 3: PRESENTATION (User-Facing)             │
│  ────────────────────────────────────────────    │
│  • Subset pick recommendations                  │
│  • Tier-based grouping (Elite/Quality/Volume)  │
│  • A/B testing different subsets               │
│  • Performance tracking per subset             │
└──────────────────────────────────────────────────┘
```

---

## Benefits of This Architecture

### 1. Foundation Stability ✅
- Base systems (catboost_v8, xgboost_v1) **never change**
- Historical data remains consistent
- Easy to reproduce past results
- No "which version?" confusion

### 2. Rapid Iteration ⚡
- Create new subsets in minutes (just SQL)
- No code deployments needed
- A/B test multiple strategies simultaneously
- Kill underperforming subsets instantly

### 3. Clear Accountability 📊
- Each subset has independent performance metrics
- Easy to compare: "Premium picks: 71.8% vs Quality picks: 57.7%"
- Know exactly what users are betting on
- Track ROI per subset

### 4. Flexibility 🎯
- Different subsets for different risk tolerances
- Combine multiple factors (confidence + edge + consistency)
- Seasonal adjustments without touching base systems
- Easy to add new filtering criteria

---

## Implementation Plan

### Phase 1: Infrastructure (Week 1)

#### 1.1 Create Subset Table Schema

```sql
CREATE TABLE `nba-props-platform.nba_predictions.prediction_subsets` (
  -- Identity
  subset_id STRING NOT NULL,  -- e.g., "catboost_v8_premium"
  parent_system_id STRING NOT NULL,  -- e.g., "catboost_v8"
  prediction_id STRING NOT NULL,  -- FK to player_prop_predictions

  -- Game/Player Info
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  player_lookup STRING NOT NULL,

  -- Prediction Details (denormalized for convenience)
  predicted_points NUMERIC,
  line_value NUMERIC,
  recommendation STRING,
  confidence_score NUMERIC,

  -- Subset Metadata
  subset_category STRING,  -- "confidence_tier", "strategy", "player_type"
  subset_description STRING,
  filter_criteria JSON,  -- Store exact filter rules

  -- Tracking
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  subset_version STRING,  -- For A/B testing

  -- Performance (updated post-game)
  actual_points NUMERIC,
  prediction_correct BOOLEAN,
  absolute_error NUMERIC
)
PARTITION BY game_date
CLUSTER BY subset_id, parent_system_id, game_date;
```

#### 1.2 Create Subset Configuration Table

```sql
CREATE TABLE `nba-props-platform.nba_predictions.subset_definitions` (
  subset_id STRING PRIMARY KEY,
  parent_system_id STRING NOT NULL,

  -- Definition
  subset_name STRING,
  description STRING,
  filter_query STRING,  -- SQL WHERE clause

  -- Categorization
  tier STRING,  -- "elite", "quality", "volume", "experimental"
  risk_level STRING,  -- "low", "medium", "high"

  -- Status
  is_active BOOLEAN DEFAULT TRUE,
  created_date DATE,
  deactivated_date DATE,

  -- Performance Targets
  target_win_rate NUMERIC,
  min_daily_volume INT64,

  -- Metadata
  created_by STRING,
  notes STRING
);
```

### Phase 2: Define Initial Subsets (Week 1)

#### CatBoost V8 Subsets

```sql
-- 1. Premium Tier (Highest Confidence)
INSERT INTO subset_definitions VALUES (
  'catboost_v8_premium',
  'catboost_v8',
  'CatBoost V8 - Premium Tier',
  'Top-tier picks with 92%+ confidence. Expected 71.8% win rate.',
  'confidence_score >= 92',
  'elite',
  'low',
  TRUE,
  '2026-01-17',
  NULL,
  70.0,
  10,
  'automated',
  'Initial tier based on Dec 20 - Jan 15 analysis'
);

-- 2. Quality Tier (High Confidence, Refined)
INSERT INTO subset_definitions VALUES (
  'catboost_v8_quality',
  'catboost_v8',
  'CatBoost V8 - Quality Tier',
  'High confidence picks 86-92%, excluding problematic 88-90% sub-tier if validated.',
  'confidence_score >= 86 AND confidence_score < 92',
  'quality',
  'medium',
  TRUE,
  '2026-01-17',
  NULL,
  57.0,
  20,
  'automated',
  'Need to analyze 88-90% sub-tier performance before finalizing filter'
);

-- 3. Premium UNDERS (Highest Confidence + Direction)
INSERT INTO subset_definitions VALUES (
  'catboost_v8_premium_unders',
  'catboost_v8',
  'CatBoost V8 - Premium UNDERS',
  'Premium tier UNDER picks only. Combining high confidence with favorable direction.',
  'confidence_score >= 92 AND recommendation = "UNDER"',
  'elite',
  'low',
  TRUE,
  '2026-01-17',
  NULL,
  75.0,
  5,
  'automated',
  'UNDERS historically outperform OVERS in aggregate data'
);

-- 4. Volume Tier (Track Only)
INSERT INTO subset_definitions VALUES (
  'catboost_v8_volume',
  'catboost_v8',
  'CatBoost V8 - Volume Tier',
  'All picks with confidence 60-86%. Monitor only, not for betting.',
  'confidence_score >= 60 AND confidence_score < 86',
  'volume',
  'high',
  FALSE,  -- Not active for betting
  '2026-01-17',
  NULL,
  52.4,
  50,
  'automated',
  'Baseline tier. Expected to underperform. Track for model improvement.'
);
```

#### XGBoost V1 Subsets (Future - After Real Line Validation)

```sql
-- Will add after Jan 17+ when xgboost_v1 has real line data:
-- - xgboost_v1_elite_unders
-- - xgboost_v1_high_confidence
-- - xgboost_v1_high_edge (predicted - line > 2.5)
```

#### Multi-System Subsets

```sql
-- 5. Consensus Picks (Multiple Systems Agree)
INSERT INTO subset_definitions VALUES (
  'consensus_3plus',
  'multi_system',
  'Consensus - 3+ Systems',
  'Picks where 3 or more systems recommend same direction (OVER/UNDER).',
  -- Complex query - handled in materialization logic
  NULL,
  'elite',
  'low',
  TRUE,
  '2026-01-17',
  NULL,
  65.0,
  5,
  'automated',
  'Wisdom of crowds. Strong historical performance when systems agree.'
);
```

### Phase 3: Materialization Strategy (Week 1)

#### Option A: Scheduled Query (RECOMMENDED)

```sql
-- Create scheduled query to run daily at 11 AM ET (after predictions generated)
-- Schedule: 0 16 * * * (4 PM UTC = 11 AM ET)

CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions.prediction_subsets_daily`
PARTITION BY game_date AS

WITH base_predictions AS (
  SELECT
    p.*,
    a.actual_points,
    a.prediction_correct,
    a.absolute_error
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
  LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` a
    ON p.prediction_id = a.prediction_id
  WHERE p.game_date >= CURRENT_DATE() - 7  -- Last 7 days
    AND p.line_value != 20.0  -- Exclude placeholder lines
)

-- Generate subsets
SELECT
  CONCAT(parent_system, '_', tier) as subset_id,
  parent_system as parent_system_id,
  prediction_id,
  game_id,
  game_date,
  player_lookup,
  predicted_points,
  line_value,
  recommendation,
  confidence_score,
  tier as subset_category,
  CONCAT('Confidence tier: ', tier) as subset_description,
  TO_JSON_STRING(STRUCT(
    confidence_score,
    tier,
    filter_rule
  )) as filter_criteria,
  CURRENT_TIMESTAMP() as created_at,
  'v1' as subset_version,
  actual_points,
  prediction_correct,
  absolute_error
FROM (
  SELECT
    *,
    system_id as parent_system,
    CASE
      WHEN confidence_score >= 92 THEN 'premium'
      WHEN confidence_score >= 86 AND confidence_score < 92 THEN 'quality'
      WHEN confidence_score >= 60 AND confidence_score < 86 THEN 'volume'
      ELSE 'excluded'
    END as tier,
    CASE
      WHEN confidence_score >= 92 THEN 'confidence >= 92'
      WHEN confidence_score >= 86 THEN 'confidence >= 86 AND < 92'
      WHEN confidence_score >= 60 THEN 'confidence >= 60 AND < 86'
      ELSE 'excluded'
    END as filter_rule
  FROM base_predictions
  WHERE system_id IN ('catboost_v8', 'moving_average', 'ensemble_v1')  -- Add systems as validated
)
WHERE tier != 'excluded'

UNION ALL

-- Premium UNDERS subset
SELECT
  CONCAT(system_id, '_premium_unders') as subset_id,
  system_id as parent_system_id,
  prediction_id,
  game_id,
  game_date,
  player_lookup,
  predicted_points,
  line_value,
  recommendation,
  confidence_score,
  'strategy' as subset_category,
  'Premium confidence + UNDER recommendation' as subset_description,
  TO_JSON_STRING(STRUCT(
    confidence_score,
    'UNDER' as recommendation,
    'confidence >= 92 AND recommendation = UNDER' as filter_rule
  )) as filter_criteria,
  CURRENT_TIMESTAMP() as created_at,
  'v1' as subset_version,
  actual_points,
  prediction_correct,
  absolute_error
FROM base_predictions
WHERE system_id = 'catboost_v8'
  AND confidence_score >= 92
  AND recommendation = 'UNDER';
```

#### Option B: Real-time View (For exploration)

```sql
-- Create view for ad-hoc subset exploration
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.prediction_subsets_view` AS
-- Same query as above, but as a view
-- Use for: exploring new subset ideas, quick analysis
-- Don't use for: production picks (use scheduled table instead)
```

### Phase 4: Performance Tracking (Week 1)

#### Daily Subset Performance Report

```sql
CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions.subset_performance_daily`
PARTITION BY report_date AS

SELECT
  CURRENT_DATE() as report_date,
  subset_id,
  parent_system_id,
  subset_category,

  -- Volume
  COUNT(*) as total_picks,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT game_id) as unique_games,

  -- Performance
  COUNTIF(prediction_correct = TRUE) as wins,
  COUNTIF(prediction_correct = FALSE) as losses,
  COUNTIF(prediction_correct IS NULL) as pending,

  SAFE_DIVIDE(
    COUNTIF(prediction_correct = TRUE),
    COUNTIF(prediction_correct IS NOT NULL)
  ) * 100 as win_rate,

  AVG(absolute_error) as avg_error,
  STDDEV(absolute_error) as std_error,

  AVG(confidence_score) as avg_confidence,
  MIN(confidence_score) as min_confidence,
  MAX(confidence_score) as max_confidence,

  -- Profitability (assuming $100 per pick at -110 odds)
  COUNTIF(prediction_correct = TRUE) * 90.91 as gross_wins_dollars,
  COUNTIF(prediction_correct = FALSE) * 100 as gross_losses_dollars,
  (COUNTIF(prediction_correct = TRUE) * 90.91) - (COUNTIF(prediction_correct = FALSE) * 100) as net_profit_dollars,

  SAFE_DIVIDE(
    (COUNTIF(prediction_correct = TRUE) * 90.91) - (COUNTIF(prediction_correct = FALSE) * 100),
    COUNTIF(prediction_correct IS NOT NULL) * 100
  ) * 100 as roi_percent

FROM `nba-props-platform.nba_predictions.prediction_subsets_daily`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY subset_id, parent_system_id, subset_category;
```

### Phase 5: Alerting & Monitoring (Week 2)

#### Subset Performance Alerts

```python
# monitoring/subset_performance_monitor.py

import logging
from google.cloud import bigquery
from shared.utils.notification_system import NotificationRouter

logger = logging.getLogger(__name__)

SUBSET_THRESHOLDS = {
    'catboost_v8_premium': {
        'min_win_rate': 65.0,
        'min_daily_picks': 5,
        'max_error': 4.5
    },
    'catboost_v8_quality': {
        'min_win_rate': 55.0,
        'min_daily_picks': 10,
        'max_error': 6.0
    }
}

def check_subset_performance():
    """Monitor subset performance and alert on threshold violations"""

    client = bigquery.Client()

    query = """
    SELECT
        subset_id,
        total_picks,
        win_rate,
        avg_error,
        net_profit_dollars,
        roi_percent
    FROM `nba-props-platform.nba_predictions.subset_performance_daily`
    WHERE report_date = CURRENT_DATE()
    """

    results = client.query(query).to_dataframe()

    alerts = []

    for _, row in results.iterrows():
        subset_id = row['subset_id']

        if subset_id not in SUBSET_THRESHOLDS:
            continue

        thresholds = SUBSET_THRESHOLDS[subset_id]

        # Check win rate
        if row['win_rate'] < thresholds['min_win_rate']:
            alerts.append({
                'severity': 'WARNING',
                'subset': subset_id,
                'metric': 'win_rate',
                'value': row['win_rate'],
                'threshold': thresholds['min_win_rate'],
                'message': f"{subset_id} win rate ({row['win_rate']:.1f}%) below threshold ({thresholds['min_win_rate']:.1f}%)"
            })

        # Check volume
        if row['total_picks'] < thresholds['min_daily_picks']:
            alerts.append({
                'severity': 'INFO',
                'subset': subset_id,
                'metric': 'volume',
                'value': row['total_picks'],
                'threshold': thresholds['min_daily_picks'],
                'message': f"{subset_id} low volume ({row['total_picks']} picks, expected {thresholds['min_daily_picks']}+)"
            })

        # Check error
        if row['avg_error'] > thresholds['max_error']:
            alerts.append({
                'severity': 'WARNING',
                'subset': subset_id,
                'metric': 'error',
                'value': row['avg_error'],
                'threshold': thresholds['max_error'],
                'message': f"{subset_id} error ({row['avg_error']:.2f} pts) above threshold ({thresholds['max_error']} pts)"
            })

    # Send alerts if any
    if alerts:
        notification_router = NotificationRouter()

        alert_message = "NBA Subset Performance Alerts:\n\n"
        for alert in alerts:
            alert_message += f"• {alert['severity']}: {alert['message']}\n"

        notification_router.send_email(
            subject="NBA Subset Performance Alert",
            message=alert_message,
            severity='warning'
        )

    logger.info(f"Subset performance check complete. {len(alerts)} alerts generated.")
```

---

## Usage Examples

### Example 1: Get Today's Premium Picks

```sql
-- For users: "Show me your best picks today"
SELECT
  player_lookup,
  game_id,
  predicted_points,
  line_value,
  recommendation,
  confidence_score
FROM `nba-props-platform.nba_predictions.prediction_subsets_daily`
WHERE subset_id = 'catboost_v8_premium'
  AND game_date = CURRENT_DATE()
  AND recommendation IN ('OVER', 'UNDER')
ORDER BY confidence_score DESC;
```

### Example 2: Compare Subset Performance

```sql
-- "How are different tiers performing this week?"
SELECT
  subset_id,
  total_picks,
  win_rate,
  avg_error,
  net_profit_dollars,
  roi_percent
FROM `nba-props-platform.nba_predictions.subset_performance_daily`
WHERE report_date >= CURRENT_DATE() - 7
  AND parent_system_id = 'catboost_v8'
ORDER BY roi_percent DESC;
```

### Example 3: Create Experimental Subset

```sql
-- "What if we only bet on high scorers (avg > 25 pts/game) with high confidence?"
CREATE TEMP TABLE experimental_high_scorer_premium AS
SELECT
  CONCAT(system_id, '_high_scorer_premium') as subset_id,
  *
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= CURRENT_DATE() - 30
  AND system_id = 'catboost_v8'
  AND confidence_score >= 90
  AND line_value > 25  -- High scoring props
  AND line_value != 20.0;

-- Evaluate performance
SELECT
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) / COUNT(*) * 100 as win_rate,
  AVG(absolute_error) as avg_error
FROM experimental_high_scorer_premium e
JOIN `nba-props-platform.nba_predictions.prediction_accuracy` a
  ON e.prediction_id = a.prediction_id;
```

---

## Subset Ideas Backlog

### Confidence-Based
- [x] Premium tier (≥92%)
- [x] Quality tier (86-92%)
- [ ] Ultra-elite tier (≥95%)
- [ ] Confidence + consistency (high conf + low std dev)

### Direction-Based
- [x] Premium UNDERS
- [ ] Premium OVERS
- [ ] All UNDERS (compare to OVERS across systems)

### Edge-Based
- [ ] Large edge picks (|predicted - line| > 3)
- [ ] Small edge picks (good for low variance)
- [ ] Contrarian picks (against public betting %)

### Player-Based
- [ ] High volume players (≥ 20 pts/game)
- [ ] Low volume players (< 10 pts/game)
- [ ] Starters only
- [ ] Bench players only

### Game Context
- [ ] Home underdogs
- [ ] Rested teams (2+ days rest)
- [ ] Back-to-back games
- [ ] Playoff implications

### Multi-System
- [x] Consensus (3+ systems agree)
- [ ] Unanimous (all systems agree)
- [ ] Contrarian (1 system vs rest)
- [ ] Best-of-breed (top system per player type)

### Experimental
- [ ] Momentum picks (player on hot streak)
- [ ] Fade-the-public (< 30% public betting)
- [ ] Sharp line movement (line moved > 1.5 pts)
- [ ] Live betting (in-game picks)

---

## Migration Path

### Week 1: Build Infrastructure
- [x] Design architecture (this document)
- [ ] Create tables (subset_definitions, prediction_subsets)
- [ ] Set up scheduled query for materialization
- [ ] Create performance tracking tables

### Week 2: Launch Initial Subsets
- [ ] Deploy catboost_v8 premium/quality tiers
- [ ] Set up monitoring/alerting
- [ ] Run backtest on Dec 20 - Jan 15 data
- [ ] Validate performance matches expectations

### Week 3: Add More Subsets
- [ ] Add xgboost_v1 subsets (after real line validation)
- [ ] Add multi-system consensus picks
- [ ] Experiment with 3-5 new subset ideas
- [ ] A/B test: premium vs ultra-elite

### Week 4: Production Ready
- [ ] API endpoints for subset picks
- [ ] UI for subset selection
- [ ] Documentation for users
- [ ] Automated daily reports

---

## Success Metrics

### System Health
- ✅ 100% of predictions from foundation systems have real lines (no placeholders)
- ✅ Subsets materialize successfully every day by 11 AM ET
- ✅ Performance tracking updates within 1 hour of game completion

### Subset Performance
- ✅ Premium tier: ≥65% win rate, ≥20% ROI
- ✅ Quality tier: ≥55% win rate, ≥10% ROI
- ⚠️ Volume tier: ≥52.4% win rate (breakeven)

### User Engagement
- Track which subsets users select most often
- Measure user-reported satisfaction per subset
- Monitor bankroll performance per subset

---

## Conclusion

This architecture provides:
1. **Stability** - Foundation never changes
2. **Flexibility** - Rapid subset iteration
3. **Clarity** - Clean performance tracking
4. **Scalability** - Easy to add new systems/subsets

**Next Action**: Implement Phase 1 (infrastructure) this week.
