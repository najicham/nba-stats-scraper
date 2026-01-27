# Fix Prompt: `/validate-daily` Date Handling

**Issue**: The skill uses `CURRENT_DATE()` for all queries, but "yesterday's results" validation needs to check two different dates.

**Problem Timeline**:
```
Jan 25th 7-11 PM ET:  Games played
Jan 26th 12-6 AM ET:  Box score scrapers run, Phase 3 processes
Jan 26th 6 AM ET:     User runs /validate-daily "yesterday's results"
```

When validating "yesterday's results", we need:
- `game_date = Jan 25th` (when games were played)
- `processing_date = Jan 26th` (when scrapers/analytics ran)

---

## Changes Required

### 1. Add Date Determination Section

**File**: `.claude/skills/validate-daily/SKILL.md`

**Add after Interactive Mode section** (before "Current Context & Timing Awareness"):

```markdown
## Date Determination

After determining what to validate, set the target dates:

**If "Today's pipeline (pre-game check)"**:
- `game_date` = TODAY (games scheduled for tonight)
- `processing_date` = TODAY (data should be ready now)

**If "Yesterday's results (post-game check)"**:
- `game_date` = YESTERDAY (games that were played)
- `processing_date` = TODAY (scrapers ran after midnight)

**If "Specific date"**:
- `game_date` = USER_PROVIDED_DATE
- `processing_date` = DAY_AFTER(USER_PROVIDED_DATE)

```bash
# Set dates in bash for queries
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)      # For yesterday's results
PROCESSING_DATE=$(date +%Y-%m-%d)               # Today (when processing ran)

# Or for pre-game check
GAME_DATE=$(date +%Y-%m-%d)                     # Today's games
PROCESSING_DATE=$(date +%Y-%m-%d)               # Today
```

**Critical**: Use `GAME_DATE` for game data queries, `PROCESSING_DATE` for processing status queries.
```

---

### 2. Add "Yesterday's Results" Validation Workflow

**File**: `.claude/skills/validate-daily/SKILL.md`

**Add new section** after the Standard Validation Workflow:

```markdown
## Yesterday's Results Validation Workflow

When user selects "Yesterday's results (post-game check)", follow this prioritized workflow:

### Priority 1: Critical Checks (Always Run)

#### 1A. Box Scores Complete

Verify all games from yesterday have complete box score data:

```bash
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT game_id) as games_with_data,
  COUNT(*) as player_records,
  COUNTIF(points IS NOT NULL) as has_points,
  COUNTIF(minutes_played IS NOT NULL) as has_minutes
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = DATE('${GAME_DATE}')"
```

**Expected**:
- `games_with_data` matches scheduled games for that date
- `player_records` ~= games × 25-30 players per game
- `has_points` and `has_minutes` = 100% of records

#### 1B. Prediction Grading Complete

Verify predictions were graded against actual results:

```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_predictions,
  COUNTIF(actual_value IS NOT NULL) as graded,
  COUNTIF(actual_value IS NULL) as ungraded,
  ROUND(COUNTIF(actual_value IS NOT NULL) * 100.0 / COUNT(*), 1) as graded_pct
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = DATE('${GAME_DATE}')
  AND is_active = TRUE"
```

**Expected**:
- `graded_pct` = 100% (all predictions should have actual values)
- If `ungraded` > 0, check if games were postponed or data source blocked

#### 1C. Scraper Runs Completed

Verify box score scrapers ran successfully (they run after midnight):

```bash
PROCESSING_DATE=$(date +%Y-%m-%d)

bq query --use_legacy_sql=false "
SELECT
  scraper_name,
  status,
  records_processed,
  completed_at
FROM \`nba-props-platform.nba_orchestration.scraper_run_history\`
WHERE DATE(started_at) = DATE('${PROCESSING_DATE}')
  AND scraper_name IN ('nbac_gamebook', 'bdl_player_boxscores')
ORDER BY completed_at DESC"
```

**Expected**: Both scrapers show `status = 'success'`

### Priority 2: Pipeline Completeness (Run if P1 passes)

#### 2A. Analytics Generated

```bash
bq query --use_legacy_sql=false "
SELECT
  'player_game_summary' as table_name,
  COUNT(*) as records
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = DATE('${GAME_DATE}')
UNION ALL
SELECT
  'team_offense_game_summary',
  COUNT(*)
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date = DATE('${GAME_DATE}')"
```

**Expected**:
- `player_game_summary`: ~200-300 records per night (varies by games)
- `team_offense_game_summary`: 2 × number of games (home + away)

#### 2B. Phase 3 Completion Status

Check that Phase 3 processors completed (they run after midnight, so check today's date):

```bash
python3 << 'EOF'
from google.cloud import firestore
from datetime import datetime
db = firestore.Client()
# Phase 3 runs after midnight, so check TODAY's completion record
processing_date = datetime.now().strftime('%Y-%m-%d')
doc = db.collection('phase3_completion').document(processing_date).get()
if doc.exists:
    data = doc.to_dict()
    print(f"Phase 3 Status for {processing_date}:")
    for processor, status in sorted(data.items()):
        print(f"  {processor}: {status.get('status', 'unknown')}")
else:
    print(f"No Phase 3 completion record for {processing_date}")
EOF
```

#### 2C. Cache Updated

Verify player_daily_cache was refreshed (needed for today's predictions):

```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT player_lookup) as players_cached,
  MAX(updated_at) as last_update
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date = DATE('${GAME_DATE}')"
```

**Expected**: `last_update` should be within last 12 hours

### Priority 3: Quality Verification (Run if issues suspected)

#### 3A. Spot Check Accuracy

```bash
python scripts/spot_check_data_accuracy.py \
  --start-date ${GAME_DATE} \
  --end-date ${GAME_DATE} \
  --samples 10 \
  --checks rolling_avg,usage_rate
```

**Expected**: ≥95% accuracy

#### 3B. Prediction Accuracy Summary

```bash
bq query --use_legacy_sql=false "
SELECT
  prop_type,
  COUNT(*) as predictions,
  COUNTIF(
    (predicted_value > line_value AND actual_value > line_value) OR
    (predicted_value < line_value AND actual_value < line_value)
  ) as correct,
  ROUND(COUNTIF(
    (predicted_value > line_value AND actual_value > line_value) OR
    (predicted_value < line_value AND actual_value < line_value)
  ) * 100.0 / COUNT(*), 1) as accuracy_pct
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = DATE('${GAME_DATE}')
  AND is_active = TRUE
  AND actual_value IS NOT NULL
GROUP BY prop_type
ORDER BY predictions DESC"
```

**Note**: This is informational, not pass/fail. Prediction accuracy varies.
```

---

### 3. Update Existing Queries to Use Variables

**File**: `.claude/skills/validate-daily/SKILL.md`

**Replace hardcoded `CURRENT_DATE()` in these sections:**

#### Phase 4 Check (Line ~139-145)
**Before**:
```sql
WHERE game_date = CURRENT_DATE()
```

**After**:
```sql
WHERE game_date = DATE('${GAME_DATE}')
```

#### Phase 5 Check (Line ~149-153)
**Before**:
```sql
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
```

**After**:
```sql
WHERE game_date = DATE('${GAME_DATE}') AND is_active = TRUE
```

#### Phase 3 Firestore Check (Line ~125-137)
**Before**:
```python
today = datetime.now().strftime('%Y-%m-%d')
doc = db.collection('phase3_completion').document(today).get()
```

**After**:
```python
import os
# Use PROCESSING_DATE for completion status (processing happens after midnight)
processing_date = os.environ.get('PROCESSING_DATE', datetime.now().strftime('%Y-%m-%d'))
doc = db.collection('phase3_completion').document(processing_date).get()
```

---

### 4. Update Interactive Mode Question 2

**File**: `.claude/skills/validate-daily/SKILL.md`

**Update the thoroughness question to apply to both modes:**

```markdown
Question 2: "How thorough should the validation be?"
Options:
  - "Standard (Recommended)" - Priority 1 + Priority 2 checks
  - "Quick" - Priority 1 only (box scores + grading)
  - "Comprehensive" - All priorities including spot checks
```

**Then add logic:**
```markdown
Based on their answers, determine scope:

| Mode | Thoroughness | Checks Run |
|------|--------------|------------|
| Today pre-game | Standard | Health check + validation + spot checks |
| Today pre-game | Quick | Health check only |
| Yesterday results | Standard | P1 (box scores, grading) + P2 (analytics, cache) |
| Yesterday results | Quick | P1 only (box scores, grading) |
| Yesterday results | Comprehensive | P1 + P2 + P3 (spot checks, accuracy) |
```

---

### 5. Update Output Format for Yesterday's Results

**File**: `.claude/skills/validate-daily/SKILL.md`

**Add output template for yesterday's results:**

```markdown
### Output Format (Yesterday's Results)

```
## Yesterday's Results Validation - [GAME_DATE]

### Summary: [STATUS]
Processing date: [PROCESSING_DATE] (scrapers/analytics ran after midnight)

### Priority 1: Critical Checks

| Check | Status | Details |
|-------|--------|---------|
| Box Scores | ✅/❌ | [X] games, [Y] player records |
| Prediction Grading | ✅/❌ | [X]% graded ([Y] predictions) |
| Scraper Runs | ✅/❌ | nbac_gamebook: [status], bdl: [status] |

### Priority 2: Pipeline Completeness

| Check | Status | Details |
|-------|--------|---------|
| Analytics | ✅/❌ | player_game_summary: [X] records |
| Phase 3 | ✅/❌ | [X]/5 processors complete |
| Cache Updated | ✅/❌ | Last update: [timestamp] |

### Priority 3: Quality (if run)

| Check | Status | Details |
|-------|--------|---------|
| Spot Check Accuracy | ✅/⚠️/❌ | [X]% |
| Prediction Accuracy | ℹ️ | Points: [X]%, Rebounds: [Y]%, ... |

### Issues Found
[List any issues with severity]

### Recommended Actions
[Prioritized list of fixes]
```
```

---

### 6. Add Key Concept Callout

**File**: `.claude/skills/validate-daily/SKILL.md`

**Add near the top, after "Your Mission":**

```markdown
## Key Concept: Game Date vs Processing Date

**Important**: For yesterday's results validation, data spans TWO calendar dates:

```
┌─────────────────────────────────────────────────────────────┐
│ Jan 25th (GAME_DATE)           │ Jan 26th (PROCESSING_DATE) │
├────────────────────────────────┼────────────────────────────┤
│ • Games played (7-11 PM)       │ • Box score scrapers run   │
│ • Player performances          │ • Phase 3 analytics run    │
│ • Predictions made (pre-game)  │ • Predictions graded       │
│                                │ • Cache updated            │
│                                │ • YOU RUN VALIDATION       │
└────────────────────────────────┴────────────────────────────┘
```

**Use the correct date for each query:**
- Game data (box scores, stats, predictions): Use `GAME_DATE`
- Processing status (scraper runs, Phase 3 completion): Use `PROCESSING_DATE`
```

---

## Summary of Changes

| Section | Change |
|---------|--------|
| Date Determination | NEW - Explains GAME_DATE vs PROCESSING_DATE |
| Key Concept Callout | NEW - Visual diagram of date spanning |
| Yesterday's Results Workflow | NEW - Prioritized P1/P2/P3 checks |
| Existing Queries | UPDATE - Use ${GAME_DATE} instead of CURRENT_DATE() |
| Interactive Mode Q2 | UPDATE - Add thoroughness options for yesterday |
| Output Format | NEW - Template for yesterday's results |

---

## Verification After Changes

### Test 1: Pre-game Check (uses today)
```bash
/validate-daily
→ Select: Today's pipeline (pre-game check)
# Queries should use CURRENT_DATE for game_date
```

### Test 2: Yesterday's Results (uses yesterday + today)
```bash
/validate-daily
→ Select: Yesterday's results
# Game queries should use yesterday's date
# Processing queries should use today's date
```

### Test 3: Quick vs Comprehensive
```bash
/validate-daily
→ Select: Yesterday's results
→ Select: Quick
# Should only run P1 checks (box scores + grading)

/validate-daily
→ Select: Yesterday's results
→ Select: Comprehensive
# Should run P1 + P2 + P3 checks
```

---

## Files to Modify

1. `.claude/skills/validate-daily/SKILL.md` - All changes above

---

## Expected Outcome

After this fix:
- ✅ "Yesterday's results" correctly checks game_date = yesterday
- ✅ Processing status checks use today's date (when scrapers ran)
- ✅ Prioritized validation (P1 critical → P2 completeness → P3 quality)
- ✅ User can choose quick vs comprehensive
- ✅ Output clearly shows both dates being validated
