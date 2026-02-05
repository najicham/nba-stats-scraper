# Next Session Quick Start - Data Quality Fix Implementation

**Date:** February 6, 2026
**Session Type:** Implementation
**Priority:** HIGH
**Estimated Time:** 4-8 hours

---

## 🎯 Mission

Implement defense-in-depth validation to prevent bad data (0-value records) from propagating through the pipeline.

**What happened:** Feb 3 had 2 teams (PHX/POR) with points=0 in `nbac_team_boxscore`. The fallback chain accepted this bad data, causing 20 players to have NULL usage_rate.

**Why it matters:** This is a systemic design flaw affecting multiple processors. Fix it now to prevent recurrence.

---

## 📋 Pre-Session Checklist (5 minutes)

**Read these first:**
1. ✅ This file (you're reading it!)
2. ✅ Full handoff: `docs/09-handoff/2026-02-05-SESSION-117-DATA-QUALITY-VALIDATION-GAP.md`
3. ✅ Focus on Section 6 "Implementation Roadmap" → Day 1 tasks

**Check current state:**
```bash
# Is Feb 3 still broken?
bq query "SELECT team_abbr, points_scored, fg_attempts FROM nba_analytics.team_offense_game_summary WHERE game_date = '2026-02-03' AND team_abbr IN ('PHX', 'POR')"

# Expected if broken: points_scored=0, fg_attempts=0
# Expected if fixed: points_scored ~125-130, fg_attempts ~95-97
```

---

## 🚀 Implementation Plan

### Option A: Quick Fix Only (30 minutes)

**If you just want to fix Feb 3 and prevent tonight's data from breaking:**

```bash
# 1. Enable emergency override
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --update-env-vars FORCE_TEAM_RECONSTRUCTION=true

# 2. Regenerate Feb 3
ANALYTICS_URL="https://nba-phase3-analytics-processors-756957797294.us-west2.run.app"
TOKEN=$(gcloud auth print-identity-token)

curl -X POST "${ANALYTICS_URL}/process-date-range" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2026-02-03",
    "end_date": "2026-02-03",
    "processors": ["TeamOffenseGameSummaryProcessor"],
    "backfill_mode": true,
    "trigger_reason": "session_117_quick_fix"
  }'

# 3. Verify fix
bq query "SELECT team_abbr, points_scored, fg_attempts, primary_source_used FROM nba_analytics.team_offense_game_summary WHERE game_date = '2026-02-03' AND team_abbr IN ('PHX', 'POR')"

# Expected: points_scored ~125-130, primary_source_used = 'reconstructed_team_from_players'
```

**Pros:** Fast, safe
**Cons:** Doesn't prevent recurrence, band-aid solution

---

### Option B: Proper Fix (4 hours - RECOMMENDED)

**Implements all Day 1 tasks from handoff doc:**

#### Hour 1: Add Quality Validation to Extractor (2 hours)

**File to edit:** `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`

**Location:** Line 547-553 in `_extract_from_nbac_team_boxscore()`

**What to add:**
```python
def _extract_from_nbac_team_boxscore(self, start_date: str, end_date: str) -> pd.DataFrame:
    """Extract team offensive data from nbac_team_boxscore (PRIMARY source)."""
    query = f"""
    ... existing query (lines 431-545) ...
    """

    try:
        df = self.bq_client.query(query).to_dataframe()

        # ===== NEW: Quality validation (Session 117) =====
        if df is None or df.empty:
            logger.info("No data returned from nbac_team_boxscore")
            return pd.DataFrame()

        # Filter out invalid rows (0 values = placeholder/incomplete data)
        valid_mask = (df['points'] > 0) & (df['fg_attempted'] > 0)
        invalid_rows = df[~valid_mask]

        if len(invalid_rows) > 0:
            invalid_teams = invalid_rows['team_abbr'].tolist()
            logger.warning(
                f"⚠️  QUALITY CHECK: Found {len(invalid_rows)} teams with invalid data "
                f"(0 points or 0 FGA): {invalid_teams}. Filtering out for reconstruction."
            )
            df = df[valid_mask]

        # If >50% invalid, treat source as failed
        expected_teams = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days * 2 + 2
        if len(df) < expected_teams * 0.5:
            logger.error(
                f"❌ QUALITY CHECK FAILED: Only {len(df)} valid teams, expected ~{expected_teams}. "
                f"Returning empty to trigger fallback."
            )
            return pd.DataFrame()
        # ===== END NEW CODE =====

        logger.info(f"✅ Extracted {len(df)} valid team-game records from nbac_team_boxscore")
        return df

    except Exception as e:
        logger.error(f"Failed to extract from nbac_team_boxscore: {e}")
        return pd.DataFrame()
```

**Test locally:**
```bash
# Run processor test
PYTHONPATH=. python -m pytest tests/processors/analytics/test_team_offense_processor.py -v

# Or manual test
PYTHONPATH=. python -c "
from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import TeamOffenseGameSummaryProcessor
p = TeamOffenseGameSummaryProcessor()
result = p._extract_from_nbac_team_boxscore('2026-02-03', '2026-02-03')
print(f'Extracted {len(result)} teams')
print(result[['team_abbr', 'points']].to_string())
"
```

#### Hour 2: Add Pre-Write Validation Rules (1 hour)

**New file:** `shared/validation/rules/team_offense_game_summary.yaml`

```yaml
# Validation rules for team_offense_game_summary table
# Session 117: Prevent 0-value bad data from being written

table: team_offense_game_summary
enabled: true

rules:
  - name: points_not_zero
    level: ERROR
    field: points_scored
    condition: "points_scored = 0"
    message: "Team scored 0 points - bad source data or placeholder"

  - name: fg_attempts_not_zero
    level: ERROR
    field: fg_attempts
    condition: "fg_attempts = 0"
    message: "Team has 0 FG attempts - bad source data"

  - name: possessions_required
    level: ERROR
    field: possessions
    condition: "possessions IS NULL"
    message: "Possessions NULL - cannot calculate usage_rate"

  - name: unusually_low_score
    level: WARNING
    field: points_scored
    condition: "points_scored > 0 AND points_scored < 80"
    message: "Team scored <80 points - unusual but possible"
```

**Verify validation framework exists:**
```bash
# Check if pre-write validator is set up
ls -la shared/validation/pre_write_validator.py

# If it exists, just add the YAML file above
# If not, you'll need to implement the validator (see handoff doc)
```

#### Hour 3: Deploy & Test (1 hour)

```bash
# 1. Commit changes
git add data_processors/analytics/team_offense_game_summary/
git add shared/validation/rules/
git commit -m "fix: Add data quality validation to team_offense processor (Session 117)

- Filter 0-value rows in nbac_team_boxscore extractor
- Trigger fallback if >50% data invalid
- Add pre-write validation rules
- Prevents bad data propagation

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# 2. Deploy
./bin/deploy-service.sh nba-phase3-analytics-processors

# 3. Wait for deployment
gcloud run revisions list --service=nba-phase3-analytics-processors --region=us-west2 --limit=3

# 4. Test with Feb 3 (should filter bad data, use reconstruction)
curl -X POST "${ANALYTICS_URL}/process-date-range" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2026-02-03",
    "end_date": "2026-02-03",
    "processors": ["TeamOffenseGameSummaryProcessor"],
    "backfill_mode": true,
    "trigger_reason": "session_117_validation_test"
  }'

# 5. Verify logs show quality filtering
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors" AND textPayload=~"QUALITY CHECK"' --limit=10 --freshness=10m

# Expected log: "Found 2 teams with invalid data (0 points or 0 FGA): ['PHX', 'POR']"
```

#### Hour 4: Verify & Monitor

```bash
# Check Feb 3 data corrected
bq query "
SELECT team_abbr, points_scored, fg_attempts, possessions, primary_source_used
FROM nba_analytics.team_offense_game_summary
WHERE game_date = '2026-02-03' AND team_abbr IN ('PHX', 'POR')
"
# Expected: points ~125-130, primary_source_used = 'reconstructed_team_from_players'

# Check player usage_rate restored
bq query "
SELECT game_id,
  COUNTIF(is_dnp = FALSE) as active,
  COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL) as has_usage_rate,
  ROUND(100.0 * COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL) / COUNTIF(is_dnp = FALSE), 1) as pct
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-02-03'
GROUP BY game_id
HAVING game_id = '20260203_PHX_POR'
"
# Expected: 100% coverage

# Monitor tonight's processing (Feb 5 games)
# Check logs tomorrow morning for any quality warnings
```

---

## 🧪 Testing Checklist

After implementation, verify:

- [ ] Feb 3 PHX/POR data corrected (points ~125-130)
- [ ] Usage_rate coverage 100% for PHX/POR game
- [ ] Logs show quality filtering working
- [ ] Bad data rejected, fallback to reconstruction triggered
- [ ] No new errors introduced
- [ ] Pre-write validation active (if implemented)

---

## 🚨 If Something Goes Wrong

**Issue: Deployment fails**
```bash
# Check deployment logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase3-analytics-processors"' --limit=20 --freshness=10m

# Rollback if needed
gcloud run services update-traffic nba-phase3-analytics-processors --region=us-west2 --to-revisions=PREVIOUS_REVISION=100
```

**Issue: Quality validation too aggressive (filtering good data)**
```bash
# Temporarily disable with env var
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --update-env-vars DISABLE_QUALITY_VALIDATION=true

# Investigate logs
# Adjust threshold (50% → 70%?)
# Redeploy
```

**Issue: Still getting 0-value data**
```bash
# Use emergency override as backup
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --update-env-vars FORCE_TEAM_RECONSTRUCTION=true
```

---

## 📚 Reference Links

**Full handoff doc:** `docs/09-handoff/2026-02-05-SESSION-117-DATA-QUALITY-VALIDATION-GAP.md`

**Key sections:**
- Section 3: Technical Deep Dive (code locations)
- Section 6: Implementation Roadmap (detailed steps)
- Section 6.1: Day 1 tasks (what you're implementing)

**Related docs:**
- `docs/05-development/PROCESSOR-PATTERNS.md` - Fallback pattern
- `docs/02-operations/troubleshooting-matrix.md` - Data quality issues

---

## ✅ Success Criteria

**Minimum (Quick fix):**
- Feb 3 data corrected
- Tonight's data won't break

**Full success (Proper fix):**
- Quality validation in extractor prevents bad data
- Fallback to reconstruction triggered automatically
- Pre-write validation blocks bad writes
- System is self-healing

---

## 📊 Current Status (as of Session 117 end)

**Feb 3 Data:**
- ❌ PHX/POR: points=0, fg_attempts=0 (BROKEN)
- ✅ Other 18 teams: Correct data
- ❌ 20 players: NULL usage_rate

**Feb 4 Data:**
- ℹ️ Games scheduled for tonight, check tomorrow

**Feb 5 Data:**
- ℹ️ Tomorrow's games, predictions don't exist yet (normal)

**Services:**
- ✅ All deployed with latest code (no deployment drift)
- ⚠️ No quality validation active yet

**Next Steps:**
- 🎯 Implement quality validation (this session!)
- 🎯 Fix Feb 3 data
- 📊 Monitor Feb 5 processing tomorrow

---

**Good luck! 🚀**

**Questions?** Check the full handoff doc or grep for "Session 117" in the codebase.
