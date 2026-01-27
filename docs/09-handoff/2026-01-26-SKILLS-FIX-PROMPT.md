# Fix Prompt: Validation Skills Cleanup

Please fix the following issues in the validation skills:

---

## 1. Fix Cascade Window Inconsistency in validate-historical

**File**: `.claude/skills/validate-historical/SKILL.md`

**Problem**: The skill says "21 days forward" in one place but "5-10 days" elsewhere.

**Fix**: Update to be consistent and accurate:
- L5 averages → affected for 5 days
- L10 averages → affected for 10 days
- L21 averages (if used) → affected for 21 days

Change line 26 from:
```
**Cascade Window**: Missing data on date X affects rolling averages for **21 days forward**.
```

To:
```
**Cascade Window**: Missing data on date X affects rolling averages for:
- L5 averages: 5 days forward
- L10 averages: 10 days forward
- ML features using longer windows: up to 21 days forward
```

Also update line 188 and any other references to use "5-21 days" instead of fixed numbers.

---

## 2. Add Missing `--game` Mode Section

**File**: `.claude/skills/validate-historical/SKILL.md`

**Problem**: `--game <id>` is listed in the flags but has no dedicated Mode section.

**Add** after Mode 3 (Player-Specific):

```markdown
## Mode 4: Game-Specific (`--game <id>`)

**When**: `--game` flag with game ID or description
**Purpose**: Validate all data for a single game - all players, all stats, all pipeline stages

### Workflow

#### Step 1: Identify the Game

```bash
# If user provided game_id directly
GAME_ID="0022500123"

# If user provided description, find the game
bq query --use_legacy_sql=false "
SELECT game_id, game_date, home_team_abbr, away_team_abbr
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = DATE('2026-01-25')
  AND (home_team_abbr = 'LAL' OR away_team_abbr = 'LAL')
LIMIT 1"
```

#### Step 2: Check All Players for Game

```bash
bq query --use_legacy_sql=false "
WITH raw AS (
  SELECT player_lookup, points as raw_points, minutes as raw_minutes
  FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
  WHERE game_id = '0022500123'
),
analytics AS (
  SELECT player_lookup, points as analytics_points, minutes_played, usage_rate
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_id = '0022500123'
),
predictions AS (
  SELECT player_lookup, COUNT(*) as prediction_count
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE game_id = '0022500123' AND is_active = TRUE
  GROUP BY player_lookup
)
SELECT
  COALESCE(r.player_lookup, a.player_lookup) as player,
  r.raw_points,
  a.analytics_points,
  a.usage_rate,
  COALESCE(p.prediction_count, 0) as predictions,
  CASE
    WHEN r.player_lookup IS NULL THEN 'MISSING_RAW'
    WHEN a.player_lookup IS NULL THEN 'MISSING_ANALYTICS'
    WHEN a.usage_rate IS NULL THEN 'MISSING_USAGE'
    ELSE 'COMPLETE'
  END as status
FROM raw r
FULL OUTER JOIN analytics a ON r.player_lookup = a.player_lookup
LEFT JOIN predictions p ON a.player_lookup = p.player_lookup
ORDER BY status DESC, player"
```

#### Step 3: Verify Team Totals

```bash
# Check team stats exist and sum correctly
bq query --use_legacy_sql=false "
SELECT
  team_abbr,
  SUM(points) as team_points,
  (SELECT points FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\` t
   WHERE t.game_id = '0022500123' AND t.team_abbr = p.team_abbr) as recorded_team_points
FROM \`nba-props-platform.nba_analytics.player_game_summary\` p
WHERE game_id = '0022500123'
GROUP BY team_abbr"
```

### Output Format

```markdown
## Game Validation: LAL vs GSW (2026-01-25)

**Game ID**: 0022500123

### Player Data Completeness

| Player | Raw | Analytics | Usage | Predictions | Status |
|--------|-----|-----------|-------|-------------|--------|
| lebronjames | 28 | 28 | 32.1% | 4 | ✅ COMPLETE |
| anthonydavis | 24 | 24 | 28.5% | 4 | ✅ COMPLETE |
| austinreaves | 18 | 18 | NULL | 3 | ⚠️ MISSING_USAGE |

### Team Totals

| Team | Player Sum | Recorded | Match |
|------|------------|----------|-------|
| LAL | 118 | 118 | ✅ |
| GSW | 112 | 112 | ✅ |

### Issues Found
- 2 players missing usage_rate (team stats may be incomplete)
```
```

---

## 3. Add Missing `--export` Mode Section

**File**: `.claude/skills/validate-historical/SKILL.md`

**Problem**: `--export <path>` is listed in flags but has no Mode section.

**Add** after Mode 7 (Compare Sources):

```markdown
## Mode 8: Export Results (`--export <path>`)

**When**: `--export` flag with file path
**Purpose**: Save validation results to JSON for tracking, alerting, or dashboards

### Usage

Can be combined with any other mode:

```bash
/validate-historical 7 --export validation-2026-01-26.json
/validate-historical --deep-check 2026-01-18 --export deep-check-results.json
```

### Output Format

```json
{
  "validation_type": "standard",
  "date_range": {
    "start": "2026-01-19",
    "end": "2026-01-26"
  },
  "run_timestamp": "2026-01-26T17:45:00Z",
  "summary": {
    "status": "ISSUES_FOUND",
    "total_dates": 8,
    "complete_dates": 7,
    "gap_dates": 1,
    "overall_integrity": 87.5
  },
  "gaps": [
    {
      "date": "2026-01-23",
      "type": "INCOMPLETE",
      "raw_records": 240,
      "analytics_records": 45,
      "completion_pct": 18.75,
      "cascade_impact": {
        "affected_dates": ["2026-01-24", "2026-01-25", "..."],
        "affected_predictions": 150
      },
      "severity": "P1",
      "remediation": "python scripts/backfill_player_game_summary.py --date 2026-01-23"
    }
  ],
  "quality_metrics": {
    "spot_check_accuracy": 72.0,
    "usage_coverage": 35.0,
    "minutes_coverage": 100.0
  }
}
```

### Use Cases

1. **Automated Monitoring**: CI/CD pipeline runs validation, exports results, alerts on P1/P2 issues
2. **Historical Tracking**: Store daily validation results, build trend dashboards
3. **Integration**: Feed results into Slack alerts, PagerDuty, or custom dashboards
```

---

## 4. Fix Remediation Script Paths

**File**: `.claude/skills/validate-historical/SKILL.md`

**Problem**: The remediation commands reference scripts that may not exist:
- `python scripts/backfill_player_game_summary.py`
- `python scripts/regenerate_player_daily_cache.py`

**Fix**: Check which scripts/commands actually exist and update accordingly.

**Option A** - If the scripts exist, keep as-is.

**Option B** - If using processors directly, change to:
```bash
# Phase 3: Regenerate analytics
python -m data_processors.analytics.player_game_summary --date 2026-01-23

# Phase 4: Regenerate cache
python -m data_processors.precompute.player_daily_cache --start-date 2026-01-23 --end-date 2026-02-13
```

**To verify**, run:
```bash
ls scripts/backfill*.py scripts/regenerate*.py 2>/dev/null
# AND
ls data_processors/analytics/player_game_summary/ data_processors/precompute/
```

Then update the skill to use whichever approach actually works.

---

## 5. Add Sample Size Guidance for Deep Check

**File**: `.claude/skills/validate-historical/SKILL.md`

**Problem**: No guidance on how many samples to check in deep-check mode.

**Add** to Mode 2 (Deep Check) section, after the workflow:

```markdown
### Sample Size Recommendations

| Date Range | Recommended Samples | Rationale |
|------------|---------------------|-----------|
| 1-3 days | 10-15 samples | Focused check, quick |
| 7 days | 20 samples | Weekly health check |
| 14 days | 30 samples | Bi-weekly audit |
| 30+ days | 50 samples | Monthly/season audit |

**Trade-off**: More samples = higher confidence but longer runtime (~2-3 seconds per sample for BigQuery queries).

**Minimum**: Always check at least 10 samples for statistical relevance.
```

---

## 6. Update Interactive Mode Question for validate-historical

**File**: `.claude/skills/validate-historical/SKILL.md`

**Problem**: The interactive mode Question 2 doesn't include all modes.

**Fix**: Update Question 2 options to include Game-specific:

```markdown
**Question 2: "What type of validation do you need?"**
Options:
  - "Standard validation (Recommended)" - Find gaps, assess quality, get remediation plan
  - "Deep check" - Recalculate rolling averages from source to verify accuracy
  - "Player-specific" - Deep dive into a single player's data history
  - "Game-specific" - Validate all data for a single game
  - "Verify backfill" - Confirm a recent backfill succeeded and cascade is resolved
  - "Quick coverage scan" - Fast completeness check without deep analysis
  - "Find anomalies" - Detect statistical outliers and suspicious data
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `.claude/skills/validate-historical/SKILL.md` | Fix cascade window (5-21 days) |
| `.claude/skills/validate-historical/SKILL.md` | Add Mode 4: Game-Specific |
| `.claude/skills/validate-historical/SKILL.md` | Add Mode 8: Export Results |
| `.claude/skills/validate-historical/SKILL.md` | Fix remediation script paths |
| `.claude/skills/validate-historical/SKILL.md` | Add sample size guidance |
| `.claude/skills/validate-historical/SKILL.md` | Update interactive mode Q2 |

---

## Verification

After making changes, verify:

1. **Skill loads correctly**: Restart Claude Code, run `/validate-historical`
2. **Interactive mode shows all options**: Including Game-specific
3. **Scripts exist**: Test one remediation command to ensure path is correct
4. **No broken references**: Search for "21 days" and ensure consistency
