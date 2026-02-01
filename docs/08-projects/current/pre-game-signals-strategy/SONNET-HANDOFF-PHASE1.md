# Sonnet Handoff: Pre-Game Signals Phase 1

**Copy everything below this line into a new Sonnet chat:**

---

## Task: Implement Pre-Game Signal Infrastructure

You are implementing Phase 1 of the dynamic subset system - the signal infrastructure that will enable filtering picks based on daily pre-game signals.

### Context

We discovered that the `pct_over` signal (% of predictions recommending OVER) strongly correlates with high-edge hit rate:

| pct_over | Hit Rate | Sample |
|----------|----------|--------|
| <25% (UNDER_HEAVY) | 54% | 26 picks |
| ≥25% (BALANCED) | 82% | 61 picks |

**Statistical significance**: p=0.0065 (highly significant)

This means we can improve hit rates by ~28 points by only betting on "balanced" days.

### Read These Documents First

```bash
# Read in this order:
cat docs/08-projects/current/pre-game-signals-strategy/README.md
cat docs/08-projects/current/pre-game-signals-strategy/DYNAMIC-SUBSET-DESIGN.md
cat docs/08-projects/current/pre-game-signals-strategy/SESSION-70-DESIGN-REVIEW.md
```

### Your Tasks

Complete these tasks in order:

---

#### Task 1: Create the daily_prediction_signals Table

Create this table in BigQuery:

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.daily_prediction_signals` (
  -- Identity
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,

  -- Counts
  total_picks INT64,
  high_edge_picks INT64,
  premium_picks INT64,

  -- Signals
  pct_over FLOAT64,
  pct_under FLOAT64,
  avg_confidence FLOAT64,
  avg_edge FLOAT64,

  -- Classifications
  skew_category STRING,
  volume_category STRING,
  daily_signal STRING,
  signal_explanation STRING,

  -- Metadata
  calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
OPTIONS (
  description = 'Daily pre-game signals for prediction filtering. Created Session 70.'
);
```

Run this via:
```bash
bq query --use_legacy_sql=false "$(cat <<'EOF'
CREATE TABLE IF NOT EXISTS ...
EOF
)"
```

---

#### Task 2: Backfill Historical Signals (Jan 9 - Feb 1)

Run this query to populate historical signal data:

```sql
INSERT INTO `nba-props-platform.nba_predictions.daily_prediction_signals`
SELECT
  game_date,
  system_id,

  COUNT(*) as total_picks,
  COUNTIF(ABS(predicted_points - current_points_line) >= 5) as high_edge_picks,
  COUNTIF(confidence_score >= 0.92 AND ABS(predicted_points - current_points_line) >= 3) as premium_picks,

  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
  ROUND(100.0 * COUNTIF(recommendation = 'UNDER') / COUNT(*), 1) as pct_under,

  ROUND(AVG(confidence_score), 4) as avg_confidence,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_edge,

  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25 THEN 'UNDER_HEAVY'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 40 THEN 'OVER_HEAVY'
    ELSE 'BALANCED'
  END as skew_category,

  CASE
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3 THEN 'LOW'
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) > 8 THEN 'HIGH'
    ELSE 'NORMAL'
  END as volume_category,

  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25 THEN 'RED'
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3 THEN 'YELLOW'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 45 THEN 'YELLOW'
    ELSE 'GREEN'
  END as daily_signal,

  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25
      THEN 'Heavy UNDER skew - historically 54% hit rate vs 82% on balanced days'
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3
      THEN 'Low pick volume - high variance expected'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 45
      THEN 'Heavy OVER skew - monitor for potential issues'
    ELSE 'Balanced signals - historical 82% hit rate on high-edge picks'
  END as signal_explanation,

  CURRENT_TIMESTAMP() as calculated_at

FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= DATE('2026-01-09')
  AND game_date <= CURRENT_DATE()
  AND current_points_line IS NOT NULL
  AND system_id IN ('catboost_v9', 'catboost_v8')
GROUP BY game_date, system_id;
```

---

#### Task 3: Verify Backfill Results

Run these verification queries:

```sql
-- Check record count (expect ~40-50 rows: ~23 days x 2 models)
SELECT COUNT(*) as total_rows,
       COUNT(DISTINCT game_date) as days,
       COUNT(DISTINCT system_id) as models
FROM nba_predictions.daily_prediction_signals;

-- Check V9 signal distribution
SELECT skew_category, daily_signal, COUNT(*) as days
FROM nba_predictions.daily_prediction_signals
WHERE system_id = 'catboost_v9'
GROUP BY 1, 2
ORDER BY 1, 2;

-- Verify today's signal (expect RED, pct_over ~9-10%)
SELECT game_date, system_id, pct_over, skew_category, daily_signal
FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE()
ORDER BY system_id;
```

**Expected results**:
- ~23 days of data for each model
- Several UNDER_HEAVY/RED days for V9
- Today (Feb 1) should show RED signal with ~9-10% pct_over

---

#### Task 4: Add Signal Warning to /validate-daily Skill

Edit `.claude/skills/validate-daily/SKILL.md` to add a new section after the predictions check.

Find the section that checks predictions and add this new phase:

```markdown
### Phase X: Pre-Game Signal Check (NEW)

**Purpose**: Check if today's predictions have favorable signal characteristics.

**Query**:
\`\`\`sql
SELECT
  system_id,
  pct_over,
  high_edge_picks,
  skew_category,
  daily_signal,
  signal_explanation
FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
\`\`\`

**Interpretation**:

| daily_signal | Meaning | Action |
|--------------|---------|--------|
| GREEN | Balanced pct_over (25-40%), normal volume | ✅ High confidence in high-edge picks |
| YELLOW | Slight skew or low volume | ⚠️ Proceed with caution |
| RED | Heavy UNDER skew (<25% pct_over) | ⚠️ Historical 54% HR - reduce bet sizing |

**If RED signal**: Display prominent warning:
\`\`\`
⚠️ PRE-GAME SIGNAL WARNING
Today's pct_over: X% (UNDER_HEAVY)
Historical high-edge hit rate on similar days: 54%
Recommendation: Reduce bet sizing or skip high-edge picks today
\`\`\`
```

Make sure to:
1. Find the appropriate location (after predictions check, before grading)
2. Add as a new numbered phase
3. Include both the query and interpretation guidance

---

#### Task 5: Verify the Skill Update

Test the updated skill by running:
```bash
# The skill should now include the signal check
# Verify the SKILL.md file has the new section
grep -A 20 "Pre-Game Signal" .claude/skills/validate-daily/SKILL.md
```

---

#### Task 6: Commit Your Changes

```bash
git add schemas/bigquery/predictions/ .claude/skills/validate-daily/SKILL.md
git status

git commit -m "$(cat <<'EOF'
feat: Add pre-game signal infrastructure

Phase 1 of dynamic subset system:
- Created daily_prediction_signals table
- Backfilled historical signals (Jan 9 - Feb 1)
- Added signal warning to /validate-daily skill

The pct_over signal predicts high-edge hit rate:
- UNDER_HEAVY (<25%): 54% historical HR
- BALANCED (25-40%): 82% historical HR
- Statistical significance: p=0.0065

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>
EOF
)"
```

---

### Success Criteria

Before finishing, verify:

1. [ ] `daily_prediction_signals` table exists in BigQuery
2. [ ] Table has ~40-50 rows (Jan 9 - Feb 1, both models)
3. [ ] Today's V9 signal shows RED with pct_over ~9-10%
4. [ ] `/validate-daily` skill includes signal check section
5. [ ] Changes committed

---

### If You Have Extra Time

**Optional Task**: Create a standalone signal check query file:

```bash
# Create a quick diagnostic script
cat > docs/08-projects/current/pre-game-signals-strategy/check-todays-signal.sql << 'EOF'
-- Run this each morning to check today's signal
SELECT
  game_date,
  system_id,
  total_picks,
  high_edge_picks,
  ROUND(pct_over, 1) as pct_over,
  skew_category,
  daily_signal,
  signal_explanation
FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE()
ORDER BY system_id;
EOF
```

---

### Do NOT Do These Things

- Do NOT modify the prediction worker or coordinator
- Do NOT create new Cloud Functions
- Do NOT change any model code
- Do NOT implement the `/subset-picks` skill yet (that's Phase 3)
- Do NOT create the `dynamic_subset_definitions` table yet (that's Phase 2)

Focus only on signal infrastructure and the quick win of adding the warning.

---

### Questions?

If anything is unclear:
1. Read the design documents listed above
2. Check existing patterns in `.claude/skills/` for skill formatting
3. The SQL queries are production-ready - use them as-is

---

**End of Sonnet Handoff Prompt**
